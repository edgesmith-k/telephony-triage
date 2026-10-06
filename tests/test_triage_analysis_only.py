#!/usr/bin/env python3
"""RF-7 분석 전용 모드 `triage.py run --analysis-only` (contracts.md §3.2 `triage.py`, 07-workflow.md §분석 전용).

이슈 DB에 기록하지 않는 실행: cleanup·기존 계획 질문·열린 PR 확인을 건너뛰고, ok로 끝나면 lock을 풀어 `db_pr stage`를 막는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, tmp  # noqa: E402
from workspace import PLANS, Workspace, git  # noqa: E402

MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
KEY = "MOCK-1001"
WRITE_FLOW_STEPS = {"0-cleanup", "2-preflight"}


def _run(ws: Workspace, *extra, key=KEY, jira=None, expect=0) -> dict:
    args = ["run", key, "--jira-file", jira or MOCK_JIRA / f"{key}.yaml", "--logs", LOG, "--answer", "code=skip", *extra]
    return ws.json("triage.py", args, expect=expect)


def _only(ws: Workspace, **kw) -> dict:
    done = _run(ws, "--analysis-only", **kw)
    assert done["status"] == "ok", done
    return done


def _trace(ws: Workspace, key=KEY) -> list[dict]:
    path = ws.job_dir(key) / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _clone_state(ws: Workspace) -> tuple[str, str, str]:
    return (git(ws.clone, "rev-parse", "--abbrev-ref", "HEAD"), git(ws.clone, "status", "--porcelain"),
            git(ws.clone, "branch", "--list"))


def test_analysis_only_skips_write_flow_and_releases_lock():
    ws = Workspace()
    ws.plan(KEY, "p7-analyze-append.plan.json", pr={"number": 7, "url": "https://ghe.mock.invalid/pr/7"})
    pending = ws.home / "pending-feedback"
    pending.mkdir(parents=True, exist_ok=True)
    feedback = pending / f"{KEY}-1.yaml"
    feedback.write_text("note: 보존\n", encoding="utf-8")
    plan_before = (ws.job_dir(KEY) / "plan.json").read_bytes()
    clone_before = _clone_state(ws)

    done = _only(ws)      # 기존 계획이 있어도 묻지 않는다(cleanup·plan·open_pr 질문 없음)
    assert done["mode"] == "analysis-only" and "read_only_reasons" not in done and "open_prs" not in done
    assert done["plan"]["exists"] is True and set(done["plan"]) == {"exists", "source", "pr_number"} and done["plan"]["pr_number"] == 7
    assert done["lock_released"] is True and "lock_owner" not in done
    assert not WRITE_FLOW_STEPS & {r.get("step") for r in _trace(ws)}
    assert {"0-lock", "1-snapshot", "3-parse", "4-match"} <= {r.get("step") for r in _trace(ws)}
    assert (ws.job_dir(KEY) / "plan.json").read_bytes() == plan_before and feedback.is_file()
    assert ws.db_pr("lock", "status")["held"] is False
    assert _clone_state(ws) == clone_before, "사용자 clone은 그대로"
    report = (ws.job_dir(KEY) / "report.md").read_text(encoding="utf-8").splitlines()
    assert report[2] == "- 분석 전용: 이슈 DB에 기록하지 않는다(계획·PR 없음). 기록하려면 --analysis-only 없이 다시 실행"
    assert "- 열린 PR: 확인 안 함(분석 전용)" in report and "- 열린 PR: 없음" not in report
    assert "- 기존 작업 계획: 있음(분석 전용이라 건드리지 않음)" in report
    state = json.loads((ws.job_dir(KEY) / "triage-state.json").read_text(encoding="utf-8"))
    assert state["job"]["runs"][-1]["mode"] == "analysis-only" and state["owner"] is None


def test_analysis_only_then_stage_is_refused():
    ws = Workspace()
    _only(ws)
    ws.plan(KEY, "p7-analyze-append.plan.json")
    out = ws.run("db_pr.py", ["stage", ws.job_dir(KEY) / "plan.json", "--wt", ws.wt(KEY), "--branch", f"issue/{KEY}"])
    assert out.returncode == 2 and "lock" in out.stderr, (out.stdout, out.stderr)
    assert not ws.wt(KEY).exists()


def test_analysis_only_accepts_jira_file_without_dry_run():
    ws = Workspace()
    plain = ws.run("triage.py", ["run", KEY, "--jira-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", LOG])
    assert plain.returncode == 2 and "--analysis-only" in plain.stderr      # 안내 문구도 새 플래그를 알린다
    assert _only(ws)["jira"]["origin"] == "file"


def test_analysis_only_with_dry_run_is_usage_error():
    ws = Workspace(build=False)
    proc = ws.run("triage.py", ["run", KEY, "--analysis-only", "--dry-run", "--jira-file", MOCK_JIRA / f"{KEY}.yaml",
                                "--logs", LOG, "--answer", "code=skip"])
    assert proc.returncode == 2 and "--analysis-only" in proc.stderr and "--dry-run" in proc.stderr
    assert not proc.stdout.strip() and ws.db_pr("lock", "status")["held"] is False


def test_analysis_only_reports_existing_record_without_asking():
    ws = Workspace()
    jira = tmp("tt-ao-") / "MOCK-1101.yaml"
    doc = yaml.safe_load((MOCK_JIRA / f"{KEY}.yaml").read_text(encoding="utf-8"))
    doc["key"] = "MOCK-1101"
    jira.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    ask = _run(ws, "--dry-run", key="MOCK-1101", jira=jira)           # 보통 실행은 재분석 여부를 묻는다
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "reanalyze"
    ws.json("triage.py", ["release", "MOCK-1101"])
    done = _only(ws, key="MOCK-1101", jira=jira)
    assert done["existing"]["cause"] == "DATA-001-01" and done["lock_released"] is True


def test_analysis_only_then_normal_analyze_reuses_core_and_runs_write_questions():
    ws = Workspace()
    ws.plan(KEY, "p7-analyze-append.plan.json")
    first = _only(ws)
    assert first["run"] == 1 and "reuse" not in first
    n = len(_trace(ws))
    ask = _run(ws, "--dry-run")                                      # 보통 실행: 기존 계획 질문이 다시 나온다
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "plan"
    second = _run(ws, "--dry-run", "--answer", "plan=new")
    assert second["status"] == "ok" and second["mode"] == "write" and second["reuse"] == {"hit": True, "run": 1}
    assert second["request_hash"] == first["request_hash"] and second["run"] == 1
    assert second["plan"]["choice"] == "new" and "open_prs" not in second and second["lock_owner"]
    assert "lock_released" not in second
    rows = _trace(ws)[n:]
    assert WRITE_FLOW_STEPS <= {r.get("step") for r in rows} and not {"3-parse", "4-match"} & {r.get("step") for r in rows}
    report = (ws.job_dir(KEY) / "report.md").read_text(encoding="utf-8")
    assert "분석 전용" not in report and "- 열린 PR: 없음" in report
    assert ws.db_pr("lock", "status")["held"] is True
    ws.json("triage.py", ["release", KEY])
