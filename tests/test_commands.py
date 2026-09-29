#!/usr/bin/env python3
"""Phase 12 완료 기준 확인: 나머지 커맨드와 offline_eval (11-phases.md Phase 12).

커맨드 본문은 스킬·스크립트를 부르는 마크다운이라 실행 자체는 Claude Code가 한다.
여기서는 (1) 파일 목록·frontmatter가 설계와 맞는지, (2) 커맨드 본문이 부르는 스크립트 순서를
스킬 없이 그대로 돌려 보고(`sync`, 인자 없는 `validate`), (3) `tools/offline_eval.py`가 합성 라벨셋에서
표를 내는지 확인한다. 플러그인 로드(`${CLAUDE_PLUGIN_ROOT}` 치환, S1)는 이 테스트로 확인할 수 없다.

`pytest tests/test_commands.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, git, git_db, run, run_json  # noqa: E402
from workspace import Workspace  # noqa: E402

COMMANDS = REPO / "plugin" / "commands"
DOCS = REPO / "docs" / "design"
EXPECTED = ["setup", "analyze", "record", "sync", "search", "sync-pr", "preview", "review", "validate",
            "verify-fix", "fix-submitted", "migrate"]
SKILL_LINKED = ["analyze", "record", "verify-fix", "fix-submitted", "validate"]
NO_ARGS = ["setup", "sync", "preview"]


def _frontmatter(name: str) -> dict:
    text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, f"{name}.md: frontmatter 없음"
    return yaml.safe_load(match.group(1))


# -- 파일 목록·frontmatter ------------------------------------------------------------------------


def test_command_files_match_design_lists():
    files = sorted(p.stem for p in COMMANDS.glob("*.md"))
    assert files == sorted(EXPECTED) and len(files) == 12
    table = (DOCS / "09-commands.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| `([a-z-]+)[ `]", table, re.M)
    assert sorted(set(names)) == sorted(EXPECTED)
    arch = (DOCS / "01-architecture.md").read_text(encoding="utf-8")
    assert "commands/" in arch and "(12개)" in arch


def test_every_command_has_description_and_argument_hint_where_it_takes_args():
    for name in EXPECTED:
        meta = _frontmatter(name)
        assert meta.get("description"), name
        if name not in NO_ARGS:
            assert meta.get("argument-hint"), f"{name}: 인자를 받는데 argument-hint 없음"


def test_skill_linked_commands_call_the_skill_and_others_call_scripts_only():
    for name in SKILL_LINKED:
        assert "telephony-triage" in (COMMANDS / f"{name}.md").read_text(encoding="utf-8"), name
    for name in ("sync", "search", "preview", "review", "sync-pr", "migrate"):
        text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}/scripts/" in text, name


def test_commands_stop_on_missing_site_defaults():
    for name in EXPECTED:
        text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "S-3" in text, f"{name}: 사내 기본값 없음 중단 규칙 없음"


def test_write_commands_take_session_lock_and_readonly_commands_do_not():
    for name in ("sync", "sync-pr"):
        text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "lock acquire" in text and "lock release" in text, name
    for name in ("search", "preview", "review"):
        assert "lock acquire" not in (COMMANDS / f"{name}.md").read_text(encoding="utf-8"), name


# -- sync: 본문이 부르는 스크립트 순서 ------------------------------------------------------------


def test_sync_sequence_lists_closed_pr_workdir_and_deletes_only_after_yes():
    ws = Workspace()
    plan = ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")
    published = ws.read_plan("MOCK-7001")
    assert (published.get("pr") or {}).get("number"), "publish가 계획에 PR 번호를 남겨야 한다"
    prs_path = ws.gh_state / "prs.json"
    state = json.loads(prs_path.read_text(encoding="utf-8"))
    state["prs"][0]["state"] = "CLOSED"
    prs_path.write_text(json.dumps(state), encoding="utf-8")
    old = time.time() - 120 * 86400
    for path in ws.job_dir("MOCK-7001").glob("*.json"):
        os.utime(path, (old, old))

    assert ws.db_pr("lock", "acquire", "sync", "--command", "sync")["acquired"]
    snap = ws.db_pr("snapshot", "--job", "sync")
    assert snap["snapshot_sha"] and "post_lint" in snap
    snapshot = ws.work / "_snapshot"
    build = ws.json("db_build.py", ["--cache-only", "--db", snapshot])
    assert build
    assert ws.db_pr("lock", "release", "sync")["released"] is True

    dry = ws.db_pr("cleanup", "--dry-run", "--older-than")
    jobs = [t for t in dry["targets"] if t["kind"] == "job-dir"]
    assert [t["job"] for t in jobs] == ["MOCK-7001"] and jobs[0]["pr_state"] == "CLOSED"
    assert dry["removed"] == [] and plan.parent.exists(), "확인 전에는 지우지 않는다"

    done = ws.db_pr("cleanup", "--yes", "--older-than")
    assert not plan.parent.exists() and any(t["kind"] == "job-dir" for t in done["removed"])
    assert (ws.work / "_snapshot").exists(), "스냅샷은 지우지 않는다"


def test_sync_sequence_keeps_recent_or_open_pr_workdirs():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")
    dry = ws.db_pr("cleanup", "--dry-run", "--older-than")
    assert not [t for t in dry["targets"] if t["kind"] == "job-dir"]


# -- 인자 없는 validate: 본문이 부르는 스크립트 순서 --------------------------------------------------


def _validate_chain(repo: Path, extra: list | None = None) -> dict[str, int]:
    """validate.md 본문 순서. 종료 코드를 단계별로 모은다."""
    steps = {
        "lint": ("db_lint.py", ["--changed", "HEAD", "--db", repo]),
        "mask": ("mask_pii.py", ["--check", "--changed", "HEAD", "--db", repo]),
        "regress": ("db_regress.py", ["--all", "--db", repo]),
        "rules": ("db_verify.py", ["rules", "--changed", "HEAD", "--db", repo, *(extra or [])]),
        "build": ("db_build.py", ["--verify", "--db", repo]),
    }
    return {name: run(script, [str(a) for a in args]).returncode for name, (script, args) in steps.items()}


def test_argless_validate_chain_passes_on_clean_db_and_catches_a_broken_change():
    repo = git_db()
    run_json("db_build.py", ["--write", "--db", repo])
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "generated")
    assert _validate_chain(repo) == {"lint": 0, "mask": 0, "regress": 0, "rules": 0, "build": 0}

    fixture = repo / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
    fixture.write_text(fixture.read_text(encoding="utf-8").replace("DATA_DISABLED", "SOMETHING_ELSE"),
                       encoding="utf-8", newline="\n")
    codes = _validate_chain(repo)
    assert codes["regress"] != 0, "양성 fixture를 깨면 전체 회귀가 잡는다"


def test_validate_changes_are_read_only():
    repo = git_db()
    before = git(repo, "status", "--porcelain")
    _validate_chain(repo)
    assert git(repo, "status", "--porcelain") == before


# -- offline_eval ------------------------------------------------------------------------------------


def _offline(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO / "tools" / "offline_eval.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_offline_eval_prints_accuracy_table_on_synthetic_labelset():
    proc = _offline(str(REPO / "tests" / "fixtures" / "offline-eval-sample.yaml"), "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    summary = out["summary"]
    assert summary["total"] == 8 and summary["errors"] == 0
    assert summary["positive"] == 7 and summary["negative"] == 1
    assert summary["top1_accuracy"] == round(6 / 7, 4)      # EVAL-8은 일부러 틀린 라벨
    assert summary["top3_inclusion"] == round(6 / 7, 4)
    assert summary["false_positive_rate"] == 0.0
    verdicts = {r["key"]: r["verdict"] for r in out["items"]}
    assert verdicts["EVAL-1"] == "1위" and verdicts["EVAL-7"] == "정답" and verdicts["EVAL-8"] == "미스"


def test_offline_eval_text_table_has_the_three_metrics():
    proc = _offline(str(REPO / "tests" / "fixtures" / "offline-eval-sample.yaml"))
    assert proc.returncode == 0, proc.stderr
    for label in ("1위 정확도", "상위 3 포함률", "오탐률", "EVAL-8"):
        assert label in proc.stdout


def test_offline_eval_counts_false_positive_when_unresolved_expected_but_candidate_produced(tmp_path):
    labelset = tmp_path / "fp.yaml"
    labelset.write_text(yaml.safe_dump({
        "db": str(SAMPLE), "tz": "Asia/Seoul", "year": 2026,
        "items": [{"key": "FP-1", "occurred_at": "2026-09-20T14:32:10+09:00", "expect": "unresolved",
                   "logs": [str(SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log")]}],
    }), encoding="utf-8")
    proc = _offline(str(labelset), "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["summary"]["false_positive_rate"] == 1.0 and out["items"][0]["verdict"] == "오탐"


def test_offline_eval_rejects_bad_labelset(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("items: [{key: X-1}]\n", encoding="utf-8")
    proc = _offline(str(bad), "--db", str(SAMPLE))
    assert proc.returncode == 2 and "logs" in proc.stderr


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
