#!/usr/bin/env python3
"""hook_probes.py — 고정 탐침(`tests/fixtures/hook_probes.json`)을 guard에 넣어 두 `plugin/scripts`의 판정을 비교한다(4-c 조건 B).

    python3 tools/hook_probes.py [--scripts-old <plugin/scripts>] [--scripts <plugin/scripts>] [--pin]

eval 녹화본에는 규칙 5·6·11 호출이 없어 `hook_replay.py`로는 이 판정이 시험되지 않는다 — 그래서 탐침을 데이터로 둔다. 탐침마다
`name`, `tool`(`Bash`·`Write`·`mcp__…`), `input`(`{clone}`·`{work_dir}`·`{plain}`·`{wt}` 자리표시), `cwd`(clone·plain·work_dir·
wt — clone의 도구 worktree),
선택 `files`(plain 아래에 쓸 파일), `env`(`no_yaml: true` — 의존성 없음 판정, `broken_config: true` — 깨진 사용자 config.yaml
(`{broken_config}` 자리 — 설정 읽기 오류 판정)), `setup`(`origin_ci_mode`: clone의
`refs/remotes/origin/main`의 `issue-db.config.yaml` `ci_mode`를 바꾼다, `wt_ci_mode`: 작업 트리 파일만), `expect`(지금 scripts의
결정 — `tests/test_hook_probes.py`가 고정한다), `expected_change`(`none`·`deny->ask`(병합 계열·규칙 6·규칙 5 actions만 —
`category`)·`ask->none`(인용한 heredoc 본문을 읽게 된 것만 — `category: quoted-heredoc`)·`tighten`(더 엄격해짐)), 선택
`group`(`heredoc` — heredoc·stdin 판정 묶음, 함께 돈다).

작업공간은 시험 도우미 `tests/helpers/workspace.Workspace`(임시 HOME·사용자 config·이슈 DB clone + bare origin, ci_mode local)로
만든다. guard는 하위 프로세스(`<scripts>/guard.py --plugin-root <시험 plugin root>`)로 부른다 — 시험 plugin root(`ws.root`,
`site-defaults.example.yaml`을 `site-defaults.yaml`로 넣은 임시 사본)와 공개 도우미만 쓰고 실제 `plugin/` 루트의 `site-defaults.yaml`·
`tests/test_hooks.py`의 내부 이름은 쓰지 않으므로, site-defaults가 있는 사내 PC에서도 결과가 같다
(`tests/test_hook_probes.py`가 깨진 site-defaults를 둔 plugin 사본으로 확인한다). 출력은 표 `호출 / 전 / 후 / 허용 변화인가`
(`--scripts-old`가 없으면 `전` 칸은 비운다). `--pin`은 지금 결정을 `expect`로 적는다(탐침을 더한 뒤 한 번, 사람이 확인한다).
종료 코드: 0, 허용되지 않은 변화(deny→allow 포함)나 고정과 다른 결정이 있으면 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
PROBES = REPO / "tests" / "fixtures" / "hook_probes.json"
sys.path.insert(0, str(REPO / "tests" / "helpers"))

JIRA_TOOLS = ("mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets", "mcp__mock-jira__jira_ticket_comments")
RANK = {None: 0, "allow": 0, "ask": 1, "deny": 2}
ALLOWED_DENY_TO_ASK = {"merge", "rule6", "rule5-actions"}
ALLOWED_ASK_TO_NONE = {"quoted-heredoc"}      # 끝 표시를 인용한 heredoc(`<<\EOF` 등) 본문은 글자 그대로다(4-c P0 조건)


def build():
    """탐침 작업공간, 그 clone의 처음 `origin/main`, plain 디렉토리, PyYAML import가 실패하는 PYTHONPATH 디렉토리. clone의 도구
    worktree(`<work_dir>/wt-probe`, origin/main detached)도 만든다."""
    from runner import tmp
    from workspace import Workspace, git
    ws = Workspace()
    git(ws.clone, "worktree", "add", "-q", "--detach", str(ws.work / "wt-probe"), "origin/main")
    ws.json("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA_TOOLS[0],
                          "--search-issues", JIRA_TOOLS[1], "--get-comments", JIRA_TOOLS[2]])
    no_yaml = tmp("tt-probe-noyaml-")
    (no_yaml / "yaml.py").write_text('raise ImportError("PyYAML 없음 (탐침)")\n', encoding="utf-8")
    (no_yaml / "badcfg").mkdir()          # `broken_config` 탐침의 TELEPHONY_TRIAGE_HOME(깨진 config.yaml)
    (no_yaml / "badcfg" / "config.yaml").write_text("plugin: [깨진\n", encoding="utf-8")
    return ws, git(ws.clone, "rev-parse", "refs/remotes/origin/main"), tmp("tt-probe-plain-"), no_yaml


def _set_ci(ws, orig: str, setup: dict) -> None:
    """clone을 처음 상태로 되돌린 뒤 `setup`대로 `origin/main`·작업 트리의 `ci_mode`를 바꾼다(원격·index는 그대로)."""
    from runner import tmp
    from workspace import git
    c, name = ws.clone, "issue-db.config.yaml"
    git(c, "checkout", "-q", "--", name)
    git(c, "update-ref", "refs/remotes/origin/main", orig)
    text = git(c, "show", f"{orig}:{name}") + "\n"
    if setup.get("wt_ci_mode"):
        (c / name).write_text(re.sub(r"(?m)^ci_mode:.*$", f"ci_mode: {setup['wt_ci_mode']}", text), encoding="utf-8",
                              newline="\n")
    if setup.get("origin_ci_mode"):
        env = {"GIT_INDEX_FILE": str(tmp("tt-probe-idx-") / "index")}
        git(c, "read-tree", orig, env=env)
        blob = subprocess.run(["git", "-C", str(c), "hash-object", "-w", "--stdin"], capture_output=True, text=True, check=True,
                              input=re.sub(r"(?m)^ci_mode:.*$", f"ci_mode: {setup['origin_ci_mode']}", text)).stdout.strip()
        git(c, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=env)
        tree = git(c, "write-tree", env=env)
        git(c, "update-ref", "refs/remotes/origin/main", git(c, "commit-tree", tree, "-p", orig, "-m", "탐침"))


def _fill(value, places: dict):
    if isinstance(value, str):
        for k, v in places.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, places) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, places) for v in value]
    return value


def judge(scripts: Path, ws, probe: dict, plain: Path, no_yaml: Path) -> str | None:
    import mock_env
    wt = ws.work / "wt-probe"
    broken = no_yaml / "badcfg"
    places = {"clone": ws.clone.as_posix(), "work_dir": ws.work.as_posix(), "plain": plain.as_posix(), "wt": wt.as_posix(),
              "broken_config": broken.as_posix()}
    cwd = {"clone": ws.clone, "plain": plain, "work_dir": ws.work, "wt": wt}[probe.get("cwd", "clone")]
    for rel, text in (probe.get("files") or {}).items():
        (plain / rel).parent.mkdir(parents=True, exist_ok=True)
        (plain / rel).write_text(text, encoding="utf-8", newline="\n")
    env = mock_env.env_with_mocks(plugin_root=ws.root)
    env.update({k: str(v) for k, v in ws.env().items()})
    if (probe.get("env") or {}).get("no_yaml"):
        env["PYTHONPATH"] = str(no_yaml)
    if (probe.get("env") or {}).get("broken_config"):
        env["TELEPHONY_TRIAGE_HOME"] = str(broken)
    event = {"hook_event_name": "PreToolUse", "tool_name": probe["tool"], "tool_input": _fill(probe["input"], places),
             "cwd": str(cwd)}
    proc = subprocess.run([sys.executable, str(scripts / "guard.py"), "--plugin-root", str(ws.root)], input=json.dumps(event),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=cwd)
    out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
    return out and out.get("permissionDecision")


def verdict(probe: dict, old, new) -> tuple[str, bool]:
    """(허용 변화인가 칸, 허용인가). 같으면 `-`. deny→ask·ask→None은 허용 범주(`category`)만, 더 엄격해짐은 `tighten`만 허용.
    deny→None은 언제나 허용하지 않는다."""
    if old == new:
        return "-", True
    if RANK[new] < RANK[old]:
        if (old, new) == ("deny", "ask") and probe.get("expected_change") == "deny->ask" \
                and probe.get("category") in ALLOWED_DENY_TO_ASK:
            return f"예({probe['category']})", True
        if (old, new) == ("ask", None) and probe.get("expected_change") == "ask->none" \
                and probe.get("category") in ALLOWED_ASK_TO_NONE:
            return f"예({probe['category']})", True
        return "아니오(약해짐)", False
    return ("예(강화)", True) if probe.get("expected_change") == "tighten" else ("아니오(예상 밖 강화)", False)


def run_probes(new_scripts: Path, old_scripts: Path | None = None, probes: list | None = None) -> list[dict]:
    probes = probes if probes is not None else json.loads(PROBES.read_text(encoding="utf-8"))
    ws, orig, plain, no_yaml = build()
    rows = []
    try:
        for p in probes:
            _set_ci(ws, orig, p.get("setup") or {})
            old = judge(old_scripts, ws, p, plain, no_yaml) if old_scripts else None
            new = judge(new_scripts, ws, p, plain, no_yaml)
            rows.append({"probe": p, "old": old, "new": new})
    finally:
        _set_ci(ws, orig, {})
        subprocess.run(["git", "-C", str(ws.clone), "worktree", "remove", "--force", str(ws.work / "wt-probe")],
                       capture_output=True, check=False)
    return rows


def table(rows: list[dict], with_old: bool) -> tuple[str, bool]:
    lines = ["| 호출 | 전 | 후 | 허용 변화인가 |", "|---|---|---|---|"]
    ok = True
    for r in rows:
        p = r["probe"]
        text, good = verdict(p, r["old"], r["new"]) if with_old else ("", True)
        pinned = "expect" in p and p["expect"] != r["new"]
        ok = ok and good and not pinned
        call = p["name"] + ("" if not pinned else f" (고정 {p['expect']}과 다름)")
        lines.append(f"| {call} | {r['old'] if with_old else ''} | {r['new']} | {text} |")
    return "\n".join(lines), ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scripts", default=str(PLUGIN / "scripts"))
    ap.add_argument("--scripts-old", default=None)
    ap.add_argument("--pin", action="store_true", help="지금 결정을 expect로 적는다")
    args = ap.parse_args(argv)
    os.environ.setdefault("PYTHONUTF8", "1")
    rows = run_probes(Path(args.scripts), Path(args.scripts_old) if args.scripts_old else None)
    if args.pin:
        probes = [dict(r["probe"], expect=r["new"]) for r in rows]
        PROBES.write_text(json.dumps(probes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    text, ok = table(rows, bool(args.scripts_old))
    print(text)
    return 0 if ok or args.pin else 1


if __name__ == "__main__":
    sys.exit(main())
