"""guard 고정 탐침(`tests/fixtures/hook_probes.json`, `tools/hook_probes.py`): 지금 scripts의 결정이 고정한 `expect`와 같은가.

4-c 조건 B — eval 녹화본에 규칙 5·6·11 호출이 없어 탐침을 데이터로 둔다. 탐침을 더하면 `python3 tools/hook_probes.py --pin`으로
`expect`를 적고 사람이 확인한다. 옛 scripts와의 비교표는 `--scripts-old <dir>`."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import hook_probes as hp  # noqa: E402


def test_probe_set_covers_required_kinds():
    probes = json.loads(hp.PROBES.read_text(encoding="utf-8"))
    assert all("expect" in p for p in probes) and len({p["name"] for p in probes}) == len(probes)
    for p in probes:
        assert p["expected_change"] in ("none", "deny->ask", "ask->none", "tighten"), p["name"]
        assert p["expected_change"] != "deny->ask" or p.get("category") in hp.ALLOWED_DENY_TO_ASK, p["name"]
        assert p["expected_change"] != "ask->none" or p.get("category") in hp.ALLOWED_ASK_TO_NONE, p["name"]
        if p["expected_change"] == "ask->none":     # 인용한 끝 표시의 heredoc 묶음 탐침만(`<<'EOF'`·`<<"EOF"`·`<<\\EOF`)
            assert p.get("group") == "heredoc" and re.search(r"<<-?\s*['\"\\\\]", p["input"]["command"]), p["name"]
    fixed = [p for p in probes if p["expected_change"] == "none" and p["expect"] == "deny"
             and any(w in p["name"] for w in ("clone", "원문", "Write", "관리 clone"))]
    assert len(fixed) >= 10            # 규칙 8·10·12 — 바뀌면 안 되는 거부


# heredoc 묶음(`group: heredoc` — 매번 함께 돈다)이 갖춰야 할 꼴(4-c 4회차): 탐침 이름 → 고정 결정
HEREDOC_CASES = {
    "heredoc 미끼 + <<EOF- 접두": "ask", "heredoc 미끼 + <<'EOF'X 접두": "ask", "heredoc 미끼 + <<EOF.x 접두": "ask",
    "heredoc 미끼 + bash -c 안 <<EOF": "ask", "heredoc stdin <<< 셸 값 + 미끼": "ask", "heredoc stdin < 파일 + 미끼": "ask",
    "heredoc 자기 heredoc 뒤 < 파일": "ask", "heredoc stdin 파이프 base64 + 미끼": "ask",
    "heredoc 인용 heredoc | base64 | gh @-": "ask", "heredoc 줄 이음 @- 본문": "ask", "heredoc 줄 이음 query=$(cat <<EOF)": "ask",
    "heredoc alias import 줄 이음": "deny", "heredoc alias import 파이프 base64": "deny",
    "GraphQL 인용 안 한 heredoc $(…)": "ask", "heredoc base64 변수 $Q": "ask", "GraphQL @- 인용 안 한 heredoc $(…)": "ask",
    "heredoc 인용 안 한 ${Q}": "ask",
    "heredoc 대조 <<'EOF' $Q 글자": None, "heredoc 대조 <<\\EOF $Q 글자": None, "heredoc 대조 @- <<'EOF' 읽기": None,
    "heredoc 대조 인용 안 한 읽기": None}


def test_heredoc_group_has_required_cases():
    probes = {p["name"]: p for p in json.loads(hp.PROBES.read_text(encoding="utf-8")) if p.get("group") == "heredoc"}
    assert set(HEREDOC_CASES) <= set(probes), set(HEREDOC_CASES) - set(probes)
    assert {n: probes[n]["expect"] for n in HEREDOC_CASES} == HEREDOC_CASES


def test_probes_match_pinned_decisions_on_current_scripts():
    rows = hp.run_probes(hp.PLUGIN / "scripts")
    bad = [(r["probe"]["name"], r["probe"]["expect"], r["new"]) for r in rows if r["new"] != r["probe"]["expect"]]
    assert not bad, bad


def test_runner_ignores_plugin_site_defaults(tmp_path):
    """사내 PC처럼 scripts가 든 plugin 루트에 `site-defaults.yaml`이 있어도 결과가 같다 — runner는 guard에 시험 plugin root
    (`--plugin-root ws.root`)만 준다. 그 파일을 읽으면 설정 읽기 오류 판정(degraded — git ask)이 나도록 깨진 YAML을 둔다."""
    import shutil
    import subprocess

    fake = tmp_path / "plugin"
    shutil.copytree(hp.PLUGIN, fake, ignore=shutil.ignore_patterns("__pycache__", "site-defaults.yaml"))
    (fake / "site-defaults.yaml").write_text("tracker: [깨진\n", encoding="utf-8")
    names = ("git status", "gh pr view", "clone > 쓰기", "원문 cat logs/*.txt", "push main")
    probes = [p for p in json.loads(hp.PROBES.read_text(encoding="utf-8")) if p["name"] in names]
    assert len(probes) == len(names)
    rows = hp.run_probes(fake / "scripts", probes=probes)
    assert [r["new"] for r in rows] == [p["expect"] for p in probes]
    # 대조: 그 plugin 루트를 guard에 주면 깨진 site-defaults를 읽어 설정 읽기 오류 판정(degraded)이 된다 — `ls`는 통과 + 경고,
    # git은 ask(위 시험이 그 파일을 실제로 피했다)
    def run(cmd):
        event = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(tmp_path)}
        return subprocess.run([sys.executable, str(fake / "scripts" / "guard.py"), "--plugin-root", str(fake)],
                              input=json.dumps(event), capture_output=True, text=True, encoding="utf-8", check=False)
    proc = run("ls")
    assert not proc.stdout.strip() and "설정 읽기 오류" in proc.stderr, (proc.stdout, proc.stderr)
    got = json.loads(run("git status").stdout)["hookSpecificOutput"]
    assert got["permissionDecision"] == "ask" and "설정 읽기 오류" in got["permissionDecisionReason"]
