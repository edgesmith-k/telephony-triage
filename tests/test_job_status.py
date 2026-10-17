#!/usr/bin/env python3
"""작업 상태 한 화면 `job_status.py` v1 (contracts.md §3.2, 로컬 기록·읽기 전용).

- 단계: none → needs-input(→ release 뒤 needs-input-past) → analyzed(→ analysis-stale) → plan-saved → staged →
  summary-shown(사용자 승인은 늘 unknown) → committed(→ approved-tree-mismatch) → pushed-no-pr / pr-created(→ wt-after-pr).
- 읽기 전용: work_dir·clone·wt의 파일·git 상태가 그대로, 손상 lock 백업 없음.
- 민감 정보: steps-pasted.txt·issue_raw.json 내용과 needs_input 질문 문구는 출력·상태 파일에 없다.
- 키 생략: lock 작업 → 단일 작업 → 후보. markdown ≤ 3KB, json 한 줄.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import mock_env  # noqa: E402
from runner import SAMPLE, plugin_root, run, tmp  # noqa: E402
from workspace import Workspace, git  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_claude(monkeypatch, tmp_path):
    """--doctor가 진짜 `claude --version`을 부르지 않게 한다(없는 경로 → 확인 불가)."""
    monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(tmp_path / "no-claude"))

MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
KEY = "MOCK-1001"
JOB = "MOCK-7001"
BRANCH = "issue/MOCK-7001"
MD_MAX = 3072


def _status(ws: Workspace, *args, expect=0) -> dict:
    proc = ws.run("job_status.py", list(args))
    assert proc.returncode == expect, (proc.returncode, proc.stderr)
    if expect:
        return {"stderr": proc.stderr}
    assert proc.stdout.count("\n") == 1, "json은 한 줄"
    return json.loads(proc.stdout)


def _md(ws: Workspace, *args) -> str:
    proc = ws.run("job_status.py", [*args, "--format", "markdown"])
    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.encode("utf-8")) <= MD_MAX, len(proc.stdout.encode("utf-8"))
    return proc.stdout


def _codes(doc: dict) -> set:
    return {b["code"] for b in doc["blockers"]}


def _triage_args() -> list:
    return ["run", KEY, "--dry-run", "--issue-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", LOG]


def _tstate(ws: Workspace) -> dict:
    return json.loads((ws.job_dir(KEY) / "triage-state.json").read_text(encoding="utf-8"))


# -- 분석 단계 -----------------------------------------------------------------------------------------


def test_no_job_is_none_and_suggests_analyze():
    ws = Workspace()
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "none" and doc["stage"]["confidence"] == "now"
    assert doc["next"].startswith(f"/telephony-triage:analyze {KEY}")
    assert doc["target"]["remote"] == "원격 최신성: 확인하지 않음(로컬 기록만)" and doc["approval"]["user_approval"] == "unknown"
    assert not ws.job_dir(KEY).exists(), "상태 화면은 작업 디렉토리를 만들지 않는다"
    md = _md(ws, KEY)
    assert md.startswith(f"## {KEY} 작업 상태 (android)\n")
    heads = [line for line in md.splitlines() if line.startswith("### ")]
    assert heads == ["### 대상", "### 단계", "### 막힌 것", "### 다음 할 일", "### 관련 파일"]


def test_needs_input_then_past_after_release():
    ws = Workspace()
    first = ws.json("triage.py", _triage_args())
    assert first["status"] == "needs_input"
    kind = first["needs_input"]["kind"]
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "needs-input" and doc["stage"]["confidence"] == "now" and kind in doc["stage"]["label"]
    assert doc["lock"]["mine"] is True and doc["lock"]["held"] is True and f"--answer {kind}=<값>" in doc["next"]
    assert "[현재] needs-input" in _md(ws, KEY)
    ws.json("triage.py", ["release", KEY])
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "needs-input-past" and doc["stage"]["confidence"] == "recorded"
    assert "세션 끝남" in doc["stage"]["label"] and doc["lock"] == {"held": False}


def test_analyzed_and_stale_analysis():
    ws = Workspace()
    ws.json("triage.py", [*_triage_args(), "--answer", "code=skip"])
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "analyzed" and doc["stage"]["at"] and "analysis-stale" not in _codes(doc)
    assert doc["target"]["issue"] == {"key": KEY, "origin": "file"} and doc["target"]["snapshot"]["sha"]
    state = _tstate(ws)
    state["job"]["runs"][-1]["request_hash"] = "0" * 16
    (ws.job_dir(KEY) / "triage-state.json").write_text(json.dumps(state), encoding="utf-8")
    doc = _status(ws, KEY)
    stale = next(b for b in doc["blockers"] if b["code"] == "analysis-stale")
    assert "다시 분석한다" in stale["label"] and doc["next"] == stale["label"]


# -- 쓰기 단계 -----------------------------------------------------------------------------------------


def test_write_stages_plan_staged_summary_committed_and_mismatch():
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    doc = _status(ws, JOB)
    assert doc["stage"]["id"] == "plan-saved" and "미게시" in doc["stage"]["label"] and "재개 또는 명시적 폐기" in doc["next"]
    ws.acquire(JOB)
    ws.stage(JOB, BRANCH)
    doc = _status(ws, JOB)
    assert doc["stage"]["id"] == "staged" and doc["stage"]["at"] and "wt" in doc["files"]
    assert doc["lock"]["mine"] is True
    ws.db_pr("summary", ws.wt(JOB))
    pr_json = ws.job_dir(JOB) / "pr.json"
    saved = pr_json.read_bytes()
    pr_json.write_bytes(saved + b" ")
    assert "pr-json-changed" in _codes(_status(ws, JOB))          # publish가 거부할 변경
    pr_json.write_bytes(saved)
    doc = _status(ws, JOB)
    assert "pr-json-changed" not in _codes(doc)
    assert doc["stage"]["id"] == "summary-shown" and "사용자 승인 여부는 기록되지 않는다" in doc["stage"]["label"]
    assert doc["approval"]["user_approval"] == "unknown" and len(doc["approval"]["approved_hash_prefix"]) == 8
    md = _md(ws, JOB)
    for text in (json.dumps(doc, ensure_ascii=False), md):
        assert "승인됨" not in text and '"approved": true' not in text and '"approved":true' not in text
    wt = ws.wt(JOB)
    ws.commit(JOB)
    doc = _status(ws, JOB)
    assert doc["stage"]["id"] == "committed" and doc["stage"]["label"] == "승인 트리 커밋됨(미push)"
    assert doc["stage"]["confidence"] == "now" and "approved-tree-mismatch" not in _codes(doc)
    git(wt, "reset", "-q", "--soft", "HEAD~1")
    (wt / "CONTRIBUTING.md").write_text("승인 뒤 수정\n", encoding="utf-8")
    ws.commit(JOB)
    doc = _status(ws, JOB)
    assert doc["stage"]["id"] == "committed" and "approved-tree-mismatch" in _codes(doc)
    assert "summary" in doc["next"]


def test_stage_failure_and_pasted_steps_are_blockers_without_reading_content():
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    ws.acquire(JOB)
    ws.stage(JOB, BRANCH)
    stage = ws.job_dir(JOB) / "stage.json"
    doc = json.loads(stage.read_text(encoding="utf-8"))
    doc["checks"]["lint"] = {"code": 1}
    doc["result"] = "check-failed"
    stage.write_text(json.dumps(doc), encoding="utf-8")
    (ws.job_dir(JOB) / "steps-pasted.txt").write_text("1 | PASTED-SECRET-7 | FAIL\n", encoding="utf-8")
    out = _status(ws, JOB)
    failed = next(b for b in out["blockers"] if b["code"] == "stage-failed")
    assert "lint" in failed["label"] and "stage --then-summary" in failed["next"]
    assert "pasted-steps-remains" in _codes(out)
    assert "PASTED-SECRET-7" not in json.dumps(out, ensure_ascii=False) and "PASTED-SECRET-7" not in _md(ws, JOB)


def test_pushed_without_pr_then_published_pr_and_discard(tmp_path):
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    ws.acquire(JOB)
    wt = ws.wt(JOB)
    proc = ws.run("db_pr.py", ["stage", ws.job_dir(JOB) / "plan.json", "--wt", wt, "--branch", BRANCH, "--then-summary"])
    assert proc.returncode == 0, proc.stderr
    approved = json.loads((ws.job_dir(JOB) / "state.json").read_text(encoding="utf-8"))["approved_hash"]
    shim = tmp_path / "bin"
    shim.mkdir()
    real_path = mock_env.env_with_mocks(plugin_root=ws.root)["PATH"]
    (shim / "gh").write_text('#!/bin/sh\nif [ "$1" = pr ] && [ "$2" = create ]; then echo "boom" >&2; exit 1; fi\n'
                             f'PATH="{real_path}"; exec gh "$@"\n', encoding="utf-8")
    (shim / "gh").chmod(0o755)
    ws.db_pr("publish", wt, "--branch", BRANCH, "--lease", "new", "--approved", approved, "--commit",
             env={"PATH": f"{shim}:{real_path}"}, expect=2)
    doc = _status(ws, JOB)
    assert doc["stage"]["id"] == "pushed-no-pr" and doc["stage"]["confidence"] == "recorded"
    assert "PR 연결 미확인" in doc["next"] and "pushed-no-pr" in _codes(doc)

    ws2 = Workspace()
    ws2.plan(JOB, "p7-analyze-append.plan.json")
    ws2.ship(JOB, BRANCH, discard=False)
    doc = _status(ws2, JOB)
    assert doc["stage"]["id"] == "pr-created" and "지금 상태는 확인하지 않았다" in doc["stage"]["label"]
    after = next(b for b in doc["blockers"] if b["code"] == "wt-after-pr")
    assert "publish를 다시 하지 말고" in after["next"]
    ws2.db_pr("discard", ws2.wt(JOB))
    doc = _status(ws2, JOB)
    assert doc["stage"]["id"] == "pr-created" and "wt-after-pr" not in _codes(doc) and "sync-pr" in doc["next"]
    # sync-pr 재적용: PR이 있는 계획을 같은 JOB에서 다시 stage → wt-after-pr가 아니라 staged(재동기화 중)
    ws2.acquire(JOB)
    ws2.stage(JOB, BRANCH)
    doc = _status(ws2, JOB)
    assert doc["stage"]["id"] == "staged" and "재동기화 중(sync-pr)" in doc["stage"]["label"]
    assert "wt-after-pr" not in _codes(doc)


# -- 읽기 전용·민감 정보 --------------------------------------------------------------------------------------


def _tree(*roots: Path) -> list:
    out = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            st = path.lstat()
            out.append((str(path), path.is_dir(), 0 if path.is_dir() else st.st_size, st.st_mtime_ns))   # 폴더 mtime도(만들기·지우기)
    return out


def _git_state(*repos: Path) -> list:
    # 테스트 자신의 status가 index를 갱신하지 않게 --no-optional-locks
    return [(git(r, "--no-optional-locks", "status", "--porcelain"), git(r, "for-each-ref"), git(r, "count-objects", "-v"))
            for r in repos]


def test_status_changes_nothing():
    ws = Workspace()
    ws.json("triage.py", _triage_args())                       # needs_input에서 멈춘 작업 + lock
    ws.json("triage.py", ["release", KEY])
    ws.plan(JOB, "p7-analyze-append.plan.json")
    ws.acquire(JOB)
    ws.stage(JOB, BRANCH)
    ws.db_pr("summary", ws.wt(JOB))
    wt = ws.wt(JOB)
    lock = (ws.work / "session.lock").read_bytes()
    before = (_git_state(ws.clone, wt), _tree(ws.work, ws.clone, ws.home))
    for args in ([JOB], [JOB, "--format", "markdown"], [KEY], [], [JOB, "--doctor", "--format", "markdown"], [KEY, "--doctor"]):
        assert ws.run("job_status.py", args).returncode == 0
    assert (_git_state(ws.clone, wt), _tree(ws.work, ws.clone, ws.home)) == before, "job_status는 읽기 전용이다(--doctor도)"
    assert (ws.work / "session.lock").read_bytes() == lock
    ws.commit(JOB)                                              # committed 경로(wt git 읽기)도 같다
    before = (_git_state(ws.clone, wt), _tree(ws.work, ws.clone, ws.home))
    for args in ([JOB], [JOB, "--format", "markdown"]):
        assert ws.run("job_status.py", args).returncode == 0
    assert (_git_state(ws.clone, wt), _tree(ws.work, ws.clone, ws.home)) == before


def test_sensitive_files_and_question_text_never_shown():
    ws = Workspace()
    first = ws.json("triage.py", _triage_args())
    question = first["needs_input"]["question"]
    job = ws.job_dir(KEY)
    (job / "steps-pasted.txt").write_text("PASTED-MARKER-91\n", encoding="utf-8")
    (job / "issue_raw.json").write_text(json.dumps({"summary": "RAW-MARKER-92"}), encoding="utf-8")
    state_bytes = (job / "triage-state.json").read_text(encoding="utf-8")
    assert question not in state_bytes and _tstate(ws)["pending"]["kind"] == first["needs_input"]["kind"]
    lock_owner = json.loads((ws.work / "session.lock").read_text(encoding="utf-8"))["owner"]
    for text in (ws.run("job_status.py", [KEY]).stdout, _md(ws, KEY), _doctor_md(ws, KEY)):
        for marker in ("PASTED-MARKER-91", "RAW-MARKER-92", question, lock_owner):
            assert marker not in text


# -- 오류·손상 ---------------------------------------------------------------------------------------------


def test_corrupt_lock_platform_mismatch_and_missing_site_defaults():
    ws = Workspace()
    ws.work.mkdir(parents=True, exist_ok=True)
    (ws.work / "session.lock").write_text("{", encoding="utf-8")
    doc = _status(ws, KEY)
    assert "lock-corrupt" in _codes(doc) and doc["lock"] == {"held": None, "corrupt": True}
    assert "사용자 확인 후에만" in next(b for b in doc["blockers"] if b["code"] == "lock-corrupt")["next"]
    assert sorted(p.name for p in ws.work.iterdir() if p.name.startswith("session.lock")) == ["session.lock"]

    job = ws.job_dir("MOCK-7601")
    job.mkdir(parents=True)
    (job / "analysis.json").write_text(json.dumps({"status": "ok", "platform": "ofono"}), encoding="utf-8")
    err = _status(ws, "MOCK-7601", expect=2)["stderr"]
    assert "이 분석은 ofono 플랫폼이다" in err
    assert "키 형식" in _status(ws, "../x", expect=2)["stderr"]
    (job / "plan.json").write_text("{", encoding="utf-8")
    (job / "analysis.json").unlink()
    doc = _status(ws, "MOCK-7601")
    assert doc["stage"]["id"] == "unknown" and any("plan.json 손상" in w for w in doc["warnings"])

    bare = tmp("tt-js-bare-") / "root"
    shutil.copytree(plugin_root(), bare)
    (bare / "site-defaults.yaml").unlink()
    proc = run("job_status.py", [KEY], root=bare, env=ws.env())
    assert proc.returncode == 2 and proc.stdout == ""
    proc = run("job_status.py", [KEY], root=ws.root, env={"TELEPHONY_TRIAGE_HOME": tmp("tt-js-home-")})
    assert proc.returncode == 2 and "사용자 config가 없다" in proc.stderr
    proc = ws.run("job_status.py", [KEY, "--format", "markdown", "--json"])
    assert proc.returncode == 2


def test_key_omitted_lock_job_single_job_and_candidates():
    ws = Workspace()
    ws.work.mkdir(parents=True, exist_ok=True)
    out = _status(ws)
    assert out["candidates"] == []
    ws.plan(JOB, "p7-analyze-append.plan.json")
    assert _status(ws)["key"] == JOB                             # 작업 하나
    ws.plan("MOCK-7002", "p7-analyze-append.plan.json")
    (ws.work / "_scratch").mkdir()
    (ws.work / ".shown").mkdir(exist_ok=True)                   # 표시 기록 폴더(L R)도 후보가 아니다
    out = _status(ws)
    assert {c["key"] for c in out["candidates"]} == {JOB, "MOCK-7002"} and all(c["stage"] == "plan-saved"
                                                                               for c in out["candidates"])
    assert "작업 상태 후보" in _md(ws)
    ws.acquire("MOCK-7002")
    assert _status(ws)["key"] == "MOCK-7002"                     # lock 잡은 작업이 먼저


def test_registered_in_contracts_and_commands():
    import subprocess
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "gen_contracts.py"), "--check"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "## `job_status.py`" in (REPO / "docs" / "design" / "contracts-cli.md").read_text(encoding="utf-8")
    command = (REPO / "plugin" / "commands" / "status.md").read_text(encoding="utf-8")
    assert "job_status.py" in command and "lock acquire" not in command and "--format markdown" in command


def test_commit_without_summary_is_not_a_mismatch():
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    ws.acquire(JOB)
    ws.stage(JOB, BRANCH)
    ws.commit(JOB, "확인 화면 없이 커밋")
    doc = _status(ws, JOB)
    assert doc["stage"]["id"] == "committed" and "확인 화면 없음" in doc["stage"]["label"]
    assert "approved-tree-mismatch" not in _codes(doc)


# -- 기록 파일로 만든 상태(질문·형식 이상) -------------------------------------------------------------------


def _lock(ws: Workspace, job: str, owner: str = "o" * 32) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ws.work.mkdir(parents=True, exist_ok=True)
    (ws.work / "session.lock").write_text(json.dumps({"job": job, "owner": owner, "command": "analyze",
                                                       "started_at": now, "updated_at": now}), encoding="utf-8")


def _put(ws: Workspace, job: str, name: str, doc) -> None:
    path = ws.job_dir(job) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_question_kinds_live_question_outranks_plan_and_lock_question_past():
    ws = Workspace()
    _lock(ws, KEY)
    for kind, needle in (("issue", "MCP"), ("logs", "`--logs`"), ("year", "--answer year=<값>")):
        _put(ws, KEY, "triage-state.json", {"owner": "o" * 32, "pending": {"kind": kind, "asked_at": "2026-10-12T00:00:00+00:00"}})
        doc = _status(ws, KEY)
        assert doc["stage"]["id"] == "needs-input" and needle in doc["next"], (kind, doc["next"])
    ws.plan(KEY, "p7-analyze-append.plan.json", match=None, issue={"key": KEY, "origin": "mcp"})
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "needs-input"                   # 지금 기다리는 질문이 저장된 계획보다 앞선다
    _put(ws, KEY, "triage-state.json", {"owner": "x" * 32, "pending": {"kind": "lock", "asked_at": "2026-10-12T00:00:00+00:00"}})
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "plan-saved" and doc["last_question"]["kind"] == "lock"
    assert "[기록 2026-10-12T00:00:00+00:00] 마지막 analyze 실행이 질문(lock)에서 멈췄다" in _md(ws, KEY)
    (ws.job_dir(KEY) / "plan.json").unlink()
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "needs-input-past" and "세션 상태 확인 불가" in doc["stage"]["label"]


def test_plan_from_other_analysis_is_flagged():
    ws = Workspace()
    ws.plan(KEY, "p7-analyze-append.plan.json", match=None, request_hash="a" * 16)
    _put(ws, KEY, "analysis.json", {"status": "ok", "request_hash": "b" * 16})
    doc = _status(ws, KEY)
    assert doc["stage"]["id"] == "plan-saved" and "plan-stale" in _codes(doc)


def test_wrong_shape_files_are_corrupt_not_crashes():
    ws = Workspace()
    probes = [
        ("MOCK-8001", "plan.json", {"issue": "문자열", "operations": []}, "unknown"),
        ("MOCK-8002", "plan.json", {"pr": [1, 2]}, "unknown"),
        ("MOCK-8003", "triage-state.json", {"job": {"runs": 3}}, "unknown"),
        ("MOCK-8004", "triage-state.json", {"job": {"runs": [{"top": "x", "request_hash": "h"}]}}, "unknown"),
        ("MOCK-8005", "analysis.json", {"status": "ok", "read_only_reasons": 3}, "unknown"),
        ("MOCK-8006", "state.json", {"approved_hash": 7}, "unknown"),
        ("MOCK-8007", "stage.json", {"checks": "x"}, "started"),
    ]
    for job, name, doc, want in probes:
        _put(ws, job, name, doc)
        out = _status(ws, job)
        assert out["stage"]["id"] == want, (job, out["stage"])
        assert any(name in w and "손상" in w for w in out["warnings"]), (job, out["warnings"])
        _md(ws, job)
    assert all(c["stage"] == "unknown" for c in _status(ws)["candidates"] if c["key"] != "MOCK-8007")


def test_candidates_skip_vanished_dirs(monkeypatch, tmp_path):
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import jobstatus
    import re
    (tmp_path / "MOCK-1").mkdir()
    (tmp_path / "MOCK-2").mkdir()
    real = Path.stat

    def stat(self, *a, **kw):
        if self.name == "MOCK-2":
            raise FileNotFoundError(self)
        return real(self, *a, **kw)
    monkeypatch.setattr(Path, "stat", stat)
    assert [c["key"] for c in jobstatus.candidates(tmp_path, re.compile(r"[A-Z]+-\d+"))] == ["MOCK-1"]


def test_markdown_byte_budget_with_long_korean_values():
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import jobstatus
    long = "아주 긴 한국어 설명 " * 40
    doc = {"key": KEY, "platform": "android",
           "target": {"tracker": "jira", "issue": {"key": KEY, "origin": "mcp"}, "work_dir": "/작업/" + "경로" * 200,
                      "snapshot": {"sha": "abc", "base": "main", "at": "t", "source": "snapshot.json"},
                      "remote": jobstatus.REMOTE_NOTE},
           "stage": {"id": "staged", "label": long, "confidence": "recorded", "at": "t", "evidence": [long] * 10},
           "lock": {"held": True, "job": KEY, "command": "analyze", "age_sec": 1, "expired": False},
           "blockers": [{"code": f"b{i}", "label": long, "confidence": "now", "next": long + str(i)} for i in range(30)],
           "must_show": [long, long], "next": long, "approval": {"approved_hash_prefix": "12345678"},
           "post": {"state": "확인 불가", "reason": long}, "warnings": [long] * 30,
           "files": {f"f{i}": f"/작업/{'경로' * 50}/파일{i}.json" for i in range(40)}}
    text = jobstatus.markdown(doc)
    assert len(text.encode("utf-8")) <= jobstatus.MD_MAX, len(text.encode("utf-8"))
    assert text.rstrip("\n").endswith("줄(근거·경고·파일 등, JSON 출력)") and "- … 생략 " in text
    for head in ("### 대상", "### 단계", "### 막힌 것", "### 다음 할 일", "### 관련 파일"):
        assert head in text
    assert "b0:" in text                                           # 첫 막힌 것은 남는다


def test_markdown_hard_cut_when_no_droppable_lines():
    """버릴 줄이 없고 줄마다 잘라도 넘으면 상한 안의 줄 경계에서 끊는다(≤3,072B 보장)."""
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import jobstatus
    text = jobstatus._fit([("가" * 300, None)] * 100)
    assert len(text.encode("utf-8")) <= jobstatus.MD_MAX and text.endswith("\n")
    assert text.rstrip("\n").endswith("줄(근거·경고·파일 등, JSON 출력)") and "- … 생략 " in text   # 끊어도 생략 표시는 남는다
    small = jobstatus._fit([("짧은 줄", None), ("근거", 1)])
    assert small == "짧은 줄\n근거\n"


def test_lock_stop_drops_pending_question():
    ws = Workspace()
    ws.acquire(JOB)                                              # 다른 작업이 lock을 갖고 있다
    ask = ws.json("triage.py", _triage_args())
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "lock"
    assert _tstate(ws)["pending"]["kind"] == "lock"
    stopped = ws.json("triage.py", [*_triage_args(), "--answer", "lock=stop"])
    assert stopped["status"] == "stopped"
    assert "pending" not in _tstate(ws)                          # 답한 lock 질문이 상태 화면에 남지 않는다
    assert _status(ws, KEY)["stage"]["id"] != "needs-input-past"


def test_live_question_still_shows_stage_blockers():
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    ws.acquire(JOB)
    ws.stage(JOB, BRANCH)
    stage = ws.job_dir(JOB) / "stage.json"
    doc = json.loads(stage.read_text(encoding="utf-8"))
    doc["checks"]["lint"] = {"code": 1}
    doc["result"] = "check-failed"
    doc["drift"] = [{"target": "DATA-001-01"}]
    stage.write_text(json.dumps(doc), encoding="utf-8")
    owner = json.loads((ws.work / "session.lock").read_text(encoding="utf-8"))["owner"]
    _put(ws, JOB, "triage-state.json", {"owner": owner, "pending": {"kind": "plan", "asked_at": "2026-10-12T00:00:00+00:00"}})
    out = _status(ws, JOB)
    assert out["stage"]["id"] == "needs-input"                   # 지금 기다리는 질문이 앞선다
    assert {"stage-failed", "drift"} <= _codes(out), _codes(out)  # 그래도 stage 결과는 막힌 것이다


def test_resync_label_when_wt_git_unreadable():
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    ws.ship(JOB, BRANCH, discard=False)
    ws.db_pr("discard", ws.wt(JOB))
    ws.acquire(JOB)
    ws.stage(JOB, BRANCH)
    (ws.wt(JOB) / ".git").write_text("gitdir: /nonexistent/tt-broken\n", encoding="utf-8")
    doc = _status(ws, JOB)
    assert "확인 불가(git 읽기 실패)" in doc["stage"]["label"] and "재동기화 중" not in doc["stage"]["label"], doc["stage"]
    assert any("git 읽기 실패" in e for e in doc["stage"].get("evidence") or [])
    assert any("wt git 읽기 실패" in w for w in doc["warnings"])


# -- last-run-error·진단(--doctor) ---------------------------------------------------------------------------------


DOCTOR_MAX = 4096
CRED_URL = "https:" + "//u:" + "tok123@ghe.mock.invalid/x"     # 토큰 든 URL(경계 검사가 원문으로 보지 않게 나눠 쓴다)


def _trace(ws: Workspace, job: str, *rows) -> None:
    ws.job_dir(job).mkdir(parents=True, exist_ok=True)
    with (ws.job_dir(job) / "trace.jsonl").open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _doctor_md(ws: Workspace, *args, env=None) -> str:
    proc = ws.run("job_status.py", [*args, "--doctor", "--format", "markdown"], env=env)
    assert proc.returncode == 0, proc.stderr
    assert len(proc.stdout.encode("utf-8")) <= DOCTOR_MAX, len(proc.stdout.encode("utf-8"))
    return proc.stdout


def test_last_run_error_until_a_later_run_ends():
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    _trace(ws, JOB, {"ts": "2026-10-01T00:00:00+00:00", "step": "error", "exit": 2,
                     "message": "work_dir가 없다 imsi=450081234567890 " + CRED_URL})
    doc = _status(ws, JOB)
    row = next(b for b in doc["blockers"] if b["code"] == "last-run-error")
    assert row["label"].startswith("마지막 실행이 오류로 끝났다(종료 2): work_dir가 없다 imsi=<IMSI#1>")
    assert "://<CRED>@" in row["label"] and row["at"] == "2026-10-01T00:00:00+00:00" and "--doctor" in row["next"]
    for text in (json.dumps(doc, ensure_ascii=False), _md(ws, JOB)):
        assert "450081234567890" not in text and "tok123" not in text
    assert "last-run-error: 마지막 실행이 오류로 끝났다" in _md(ws, JOB)
    _trace(ws, JOB, {"ts": "2026-10-01T00:05:00+00:00", "step": "start", "v": 2}, {"step": "done"})
    assert "last-run-error" not in _codes(_status(ws, JOB))          # 뒤 실행이 끝났다
    _trace(ws, JOB, {"ts": "2026-10-01T00:09:00Z", "step": "stage", "v": 2, "result": "error", "dry_run": False,
                     "message": "계획 형식 오류: JSON을 읽을 수 없습니다"})
    row = next(b for b in _status(ws, JOB)["blockers"] if b["code"] == "last-run-error")
    assert row["label"] == "마지막 실행이 오류로 끝났다(db_pr stage): 계획 형식 오류: JSON을 읽을 수 없습니다"
    _trace(ws, JOB, {"step": "stage", "v": 2, "result": "drift", "dry_run": False})
    assert "last-run-error" not in _codes(_status(ws, JOB))          # 실패(drift)는 오류가 아니다


def test_doctor_markdown_and_json_show_versions_and_fail_warn_rows_only():
    import re
    ws = Workspace()
    ws.plan(JOB, "p7-analyze-append.plan.json")
    git(ws.clone, "config", "core.hooksPath", "hooks")                # hook fail 행
    text = _doctor_md(ws, JOB)
    status, _, diag = text.partition("### 진단 (관리자 전달용 — 이 화면을 그대로 보낸다. 로그 원문·자격증명 없음)\n")
    assert status.startswith(f"## {JOB} 작업 상태") and "### 단계" in status and diag
    assert re.search(r"^- \[현재\] 버전: 플러그인 지문 [0-9a-f]{12}\(설치 폴더 [^)]+\) · Claude Code (\d+\.\d+\.\d+|확인 불가) · "
                     r"Python 3\.\d+\.\d+ · PyYAML \S+·jsonschema \S+$", diag, re.M)
    assert re.search(r"^- \[현재\] 환경 점검\(doctor\): ok \d+ · warn \d+ · fail [1-9]\d* · skip \d+$", diag, re.M)
    rows = [ln.split(" | ") for ln in diag.splitlines() if ln.startswith("| ") and not ln.startswith(("| 점검", "|---"))]
    assert rows and [r[1] for r in rows] == sorted((r[1] for r in rows), key=lambda s: s != "fail")
    assert {r[1] for r in rows} <= {"fail", "warn"}
    hook = next(r for r in rows if r[0] == "| hook")
    assert "config.py install-hooks" in hook[3] and "setup 을 다시" not in hook[3]
    assert len(("\n" + diag).encode("utf-8")) <= 1024
    doc = _status(ws, JOB, "--doctor")
    d = doc["diagnosis"]
    assert doc["key"] == JOB and re.fullmatch(r"[0-9a-f]{12}", d["plugin"]["fingerprint"]) and d["plugin"]["dir"]
    assert d["doctor"]["exit"] == 1 and set(d["doctor"]["counts"]) == {"ok", "warn", "fail", "skip"}
    assert d["doctor"]["rows"] and all(r["status"] != "ok" for r in d["doctor"]["rows"])
    assert "diagnosis" not in _status(ws, JOB)                        # opt-in


def test_doctor_without_config_still_answers_and_masks_url_credentials():
    import yaml
    home = tmp("tt-js-home-")
    ws = Workspace()
    proc = run("job_status.py", [KEY, "--doctor", "--format", "markdown"], root=ws.root, env={"TELEPHONY_TRIAGE_HOME": home})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("## 작업 상태 — 확인 불가\n\n- 작업 상태: 확인 불가 — 사용자 config가 없다")
    assert "| config | fail |" in proc.stdout and len(proc.stdout.encode("utf-8")) <= DOCTOR_MAX
    doc = json.loads(run("job_status.py", [KEY, "--doctor"], root=ws.root, env={"TELEPHONY_TRIAGE_HOME": home}).stdout)
    assert doc["status_error"].startswith("사용자 config가 없다") and doc["diagnosis"]["doctor"]["exit"] == 1
    assert ws.run("job_status.py", [KEY, "--doctor", "--format", "markdown", "--json"]).returncode == 2
    # doctor clone 행의 다음(`git clone <remote>`)이 토큰 URL을 그대로 내도 진단에는 가려서 싣는다
    cfg_path = ws.home / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["issue_db"].update(remote=CRED_URL + ".git", path=str(ws.base / "no-clone"))
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    text = _doctor_md(ws, KEY)
    assert "| clone | fail |" in text and "://<CRED>@ghe.mock.invalid" in text and "tok123" not in text
    assert "tok123" not in ws.run("job_status.py", [KEY, "--doctor"]).stdout


def test_doctor_worst_case_fits_4096_bytes():
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import job_status
    from common import jobstatus
    long = "아주 긴 한국어 설명 " * 40
    doc = {"key": KEY, "platform": "android",
           "target": {"tracker": "jira", "issue": {"key": KEY}, "work_dir": "/w" * 300, "snapshot": None,
                      "remote": jobstatus.REMOTE_NOTE},
           "stage": {"id": "staged", "label": long, "confidence": "now", "evidence": [long] * 10},
           "lock": {"held": False}, "blockers": [{"code": f"b{i}", "label": long, "confidence": "now", "next": long}
                                                  for i in range(30)],
           "must_show": [], "next": long, "warnings": [long] * 20, "files": {}}
    diag = {"plugin": {"fingerprint": "0" * 12, "dir": "폴더" * 100, "version": "9.9.9"}, "claude_code": "확인 불가",
            "python": "3.14.0", "deps": "PyYAML 6.0·jsonschema 4.0",
            "doctor": {"exit": 1, "counts": {"ok": 1, "warn": 9, "fail": 9, "skip": 1},
                       "rows": [{"check": f"c{i}", "status": "fail" if i % 2 else "warn", "detail": "가" * 120,
                                 "next": "나" * 160} for i in range(18)]}}
    md = job_status.diagnosis_markdown(diag)
    assert len(md.encode("utf-8")) <= job_status.DIAG_MAX and md.rstrip("\n").split("\n")[-1].startswith("- … 외 ")
    assert len((jobstatus.markdown(doc) + md).encode("utf-8")) <= DOCTOR_MAX



def test_doctor_still_answers_on_unexpected_errors(monkeypatch):
    """작업 상태 쪽 예상 밖 오류(손상된 key_regex)·지문 계산 실패에도 --doctor는 진단을 낸다(종료 0, 확인 불가 — 예외 종류)."""
    import types
    ws = Workspace()
    snap = ws.work / "_snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    (snap / "issue-db.config.yaml").write_text("tracker:\n  key_regex: '('\n", encoding="utf-8")
    text = _doctor_md(ws, KEY)
    assert text.startswith("## 작업 상태 — 확인 불가\n\n- 작업 상태: 확인 불가 — ") and "### 진단" in text
    assert ws.run("job_status.py", [KEY]).returncode != 0                 # --doctor 없으면 그대로 오류
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import job_status

    def boom(root):
        raise PermissionError("locked")
    monkeypatch.setattr(job_status.versions, "plugin_fingerprint", boom)
    monkeypatch.setattr(job_status.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout=json.dumps({"rows": [], "counts": {"ok": 1, "warn": 0, "fail": 0, "skip": 0}})))
    diag = job_status.diagnosis(types.SimpleNamespace(plugin_root=str(ws.root)), None)
    assert diag["plugin"]["fingerprint"] == "확인 불가 — PermissionError" and diag["claude_code"] == "확인 불가"
    assert "플러그인 지문 확인 불가 — PermissionError" in job_status.diagnosis_markdown(diag)
