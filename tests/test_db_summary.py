"""db_summary.py 단위 시험: 확인 화면 조각·PR 본문·리뷰어 계산 (I5, 리뷰 §Q).

`db_pr summary`의 전체 흐름은 `tests/test_db_pr.py`가 본다. 여기서는 라이브러리 경계와 순수 함수만 본다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import db_summary  # noqa: E402
from common.exitcodes import NEEDS_APPROVAL, OK  # noqa: E402


def _screen(**over) -> dict:
    base = {
        "source_label": "분석 (analyze)", "notes": [], "ids": [], "files": [],
        "checks": {"skipped": "dry-run"}, "verification": [], "approval_needed": [],
    }
    base.update(over)
    return base


FULL_CHECKS = {
    "lint": {"ok": True, "errors": 0, "warnings": 2, "findings": []},
    "ids": {"ok": True, "duplicates": []},
    "mask": {"ok": True, "detections": 0},
    "regress": {"ok": False, "passed": 3, "total": 4, "failed": ["x"]},
    "build": {"ok": True},
}


def test_pr_body_skipped_checks():
    plan = {"jira": {"key": "ABC-1", "model": "M1", "note": "메모"}}
    body = db_summary.pr_body(_screen(notes=["n1"], ids=[{"temp_id": "T1", "id": "DATA-001"}],
                                      files=[{"kind": "유형", "path": "data/DATA-001/type.md", "change": "신규"}]),
                              plan)
    assert body.startswith("## 분석 요약\n\n- 구분: 분석 (analyze)\n- Jira: ABC-1 (model: M1)\n- 메모: 메모\n- n1\n")
    assert "- ID 할당: T1 → DATA-001" in body
    assert "| 유형 | data/DATA-001/type.md | 신규 |" in body
    assert "- 자동 검사: dry-run" in body
    assert "| 검증 | 결과 |" not in body
    assert body.endswith("승인 필요: 없음\n")


def test_pr_body_shows_id_expected_at_plan_time_only_when_different():
    ids = [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-03"},
           {"temp_id": "NEW-CAUSE-2", "id": "DATA-002-01", "expected_at_base": "DATA-002-01"},
           {"temp_id": "NEW-CAUSE-3", "id": "DATA-003-01"}]
    body = db_summary.pr_body(_screen(ids=ids), {})
    assert ("- ID 할당: NEW-CAUSE-1 → DATA-001-04 (계획 당시 DATA-001-03), NEW-CAUSE-2 → DATA-002-01, "
            "NEW-CAUSE-3 → DATA-003-01\n") in body


def test_pr_body_full_checks_and_approval():
    verification = [{"id": "R4", "label": "통과"}, {"id": "R5", "label": "승인 필요"}]
    body = db_summary.pr_body(_screen(checks=FULL_CHECKS, verification=verification,
                                      approval_needed=[{"id": "R5"}]), {})
    assert "- Jira:" not in body
    assert "스키마·lint ✅ (경고 2건) / ID 중복 ✅ / 마스킹 ✅ / fixture 회귀 ❌ (3/4) / 생성 파일 ✅" in body
    assert "| R4 | 통과 |" in body
    assert body.endswith("승인 필요: R5 — 메인테이너 승인 필수\n")


def test_check_rows():
    assert db_summary._check_rows({"checks": {"skipped": "사유"}}) == {"skipped": "사유"}
    rows = db_summary._check_rows({"checks": {
        "lint": {"code": OK, "result": {"errors": [{"code": "E1", "file": "a.md"}], "warnings": [{}]}},
        "ids": {"code": 1, "result": {"duplicates": ["X"]}},
        "mask": {"code": OK, "result": {"detections": [1, 2]}},
        "regress": {"code": 1, "result": {"summary": {"passed": 1, "total": 2},
                                          "results": [{"fixture": "f1", "status": "pass"},
                                                      {"fixture": "f2", "status": "fail"}]}},
    }})
    assert rows["lint"] == {"ok": True, "errors": 1, "warnings": 1, "findings": ["E1: a.md"]}
    assert rows["ids"] == {"ok": False, "duplicates": ["X"]}
    assert rows["mask"] == {"ok": True, "detections": 2}
    assert rows["regress"] == {"ok": False, "passed": 1, "total": 2, "failed": ["f2"]}
    assert rows["build"] == {"ok": False}


def test_verification_rows():
    stage = {"checks": {"verify": {"code": NEEDS_APPROVAL, "result": {"rules": [
        {"id": "R1", "status": "pass"},
        {"id": "R2", "status": "fail"},
        {"id": "R3", "status": "needs-approval"},
        {"id": "R4", "status": "not-implemented"},
        {"id": "R5", "status": "skipped", "reason": "로그 없음"},
        {"id": "R6", "status": "skipped", "reason": "코드 없음", "review_required": True},
        {"id": "R7", "status": "other"},
    ]}}}}
    rows = {r["id"]: r for r in db_summary._verification_rows(stage)}
    assert [rows[k]["label"] for k in ("R1", "R2", "R3", "R4")] == ["통과", "실패", "승인 필요", "미구현(뼈대)"]
    assert rows["R5"]["label"] == "건너뜀: 로그 없음" and rows["R5"]["review_required"] is False
    assert rows["R6"]["label"] == "검증 못 함 — 리뷰 대상 (코드 없음)" and rows["R6"]["review_required"] is True
    assert rows["R7"]["label"] == "other"
    assert db_summary._verification_rows({}) == []


@pytest.mark.parametrize("path,kind", [
    ("README.md", "생성 파일"), ("STATS.md", "생성 파일"), ("parser-rules/CHANGELOG.md", "생성 파일"),
    ("data/README.md", "생성 파일"),
    ("data/DATA-001-x/jira/ABC-1.yaml", "Jira 기록"), ("feedback/a.md", "피드백"),
    ("data/DATA-001-x/type.md", "유형"), ("parser-rules/data.yaml", "파서 규칙"),
    ("data/DATA-001-x/fixtures/DATA-001-01.log", "fixture"), ("other.txt", "기타"),
])
def test_file_kind(path, kind):
    assert db_summary._file_kind(path) == kind


def _owners_repo(tmp_path: Path) -> Path:
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text(
        "# 주석\n\n/data/ @org/data-team\n/data/DATA-001-x/type.md @org/override @solo\n/ims/ @org/ims-team\n"
        "/README.md @org/readme\n", encoding="utf-8")
    return tmp_path


def test_reviewers_last_rule_wins_and_generated_excluded(tmp_path):
    wt = _owners_repo(tmp_path)
    paths = ["data/DATA-001-x/type.md", "data/other.md", "README.md", "data/README.md"]
    out = db_summary.reviewers(wt, paths, {}, {})
    assert out == ["org/override", "solo", "org/data-team"]   # 생성 파일(README)은 제외, 단일 이름은 그대로


def test_reviewers_format(tmp_path):
    wt = _owners_repo(tmp_path)
    out = db_summary.reviewers(wt, ["ims/x.md"], {}, {"reviewers": {"format": "{team}@{org}"}})
    assert out == ["ims-team@org"]


def test_reviewers_allow_cause_category_owner(tmp_path):
    wt = _owners_repo(tmp_path)
    plan = {"operations": [{"op": "allow-cause", "fixture": "data/DATA-001-x/fixtures/IMS-007-02.log"}]}
    cfg = {"categories": [{"key": "ims", "id_prefix": "IMS"}, {"key": "data", "id_prefix": "DATA"}]}
    assert db_summary.reviewers(wt, [], plan, cfg) == ["org/ims-team"]
    assert db_summary.reviewers(wt, [], plan, {"categories": []}) == []


def test_search_key():
    assert db_summary.search_key({"jira": {"key": "ABC-1"}}, {"ids": [{"id": "DATA-001"}]}) == "ABC-1"
    assert db_summary.search_key({}, {"ids": [{"id": "DATA-001"}]}) == "DATA-001"
    assert db_summary.search_key({}, {}) is None


def _type_md(root: Path, rel: str, fixes: dict) -> None:
    import yaml
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"id": "CALL-001", "causes": [{"id": cid, "fix": fix} for cid, fix in fixes.items()]}
    path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True) + "---\n본문\n", encoding="utf-8")


def _fix_changes(tmp_path: Path, before: dict | None, after: dict, op: dict, rel="call/CALL-001-x/type.md"):
    from types import SimpleNamespace
    wt = tmp_path / "wt"
    _type_md(wt, rel, {"CALL-001-01": after})
    if before is not None:
        _type_md(tmp_path, "old.md", {"CALL-001-01": before})
    calls = []

    def run_git(repo, *args, check=True):
        calls.append(args)
        if before is None:
            return SimpleNamespace(returncode=128, stdout="")
        return SimpleNamespace(returncode=0, stdout=(tmp_path / "old.md").read_text(encoding="utf-8"))

    out = db_summary.fix_changes(wt, [(" M", rel), (" M", "README.md")], [op], "abc123", run_git)
    assert calls == [("show", f"abc123:{rel}")]       # 이전 내용은 base_sha의 커밋에서 읽는다
    return out


FIXED = {"status": "fixed", "ref": "MOCKCL-12345", "fixed_in": [{"branch": "B77", "build": "MOCKB77_U2_20260920"}],
         "verification": {"result": "passed", "build": "MOCKB77_U2_20260920"}, "verification_history": []}


def test_fix_changes_reopen_from_fixed_keeps_history(tmp_path):
    reopened = {"status": "open", "ref": None, "fixed_in": [], "verification": None, "verification_history": [
        {"result": "reverted", "ref": "MOCKCL-12345", "fixed_in": [{"branch": "B77", "build": "MOCKB77_U2_20260920"}]}]}
    [row] = _fix_changes(tmp_path, FIXED, reopened, {"op": "update-fix", "cause": "CALL-001-01"})
    assert row["history"] == {"result": "reverted", "ref": "MOCKCL-12345", "fixed_in": ["MOCKB77_U2_20260920"]}
    assert (row["from"], row["to"]) == ("fixed", "open")
    assert row["line"] == ("CALL-001-01: fixed → open (이전 ref MOCKCL-12345·fixed_in MOCKB77_U2_20260920 "
                           "→ verification_history 보존, 결과 reverted)")


def test_fix_changes_verify_fix_failed_partial_fixed_and_submitted(tmp_path):
    failed = {"status": "open", "ref": None, "fixed_in": [], "verification": None, "verification_history": [
        {"result": "failed", "build": "B", "ref": "MOCKCL-12345", "fixed_in": [{"branch": "B77", "build": "MOCKB77_U2_20260920"}]}]}
    [row] = _fix_changes(tmp_path, FIXED, failed, {"op": "verify-fix", "cause": "CALL-001-01", "result": "failed"})
    assert row["line"].startswith("CALL-001-01: fixed → open (이전 ref MOCKCL-12345·fixed_in MOCKB77_U2_20260920")
    assert row["line"].endswith("결과 failed)")
    partial = {**FIXED, "verification_history": [{"result": "partial", "build": "B2"}]}
    [row] = _fix_changes(tmp_path, FIXED, partial, {"op": "verify-fix", "cause": "CALL-001-01", "result": "partial"})
    assert row["line"] == "CALL-001-01: verification_history에 partial 추가 (상태 fixed 유지)"
    assert row["history"] == {"result": "partial", "ref": None, "fixed_in": []}
    submitted = {"status": "fix-submitted", "ref": "MOCKCL-2", "fixed_in": [{"branch": "B77", "build": "MOCKB77_U2_20261001"}],
                 "verification": None, "verification_history": []}
    opened = {"status": "open", "ref": None, "fixed_in": [], "verification": None, "verification_history": []}
    [row] = _fix_changes(tmp_path, opened, submitted, {"op": "update-fix", "cause": "CALL-001-01"})
    assert row["line"] == "CALL-001-01: open → fix-submitted (ref MOCKCL-2, fixed_in MOCKB77_U2_20261001)" and row["history"] is None
    [row] = _fix_changes(tmp_path, submitted, FIXED, {"op": "verify-fix", "cause": "CALL-001-01", "result": "passed"})
    assert row["line"] == "CALL-001-01: fix-submitted → fixed (검증 빌드 MOCKB77_U2_20260920)"


def test_fix_changes_ignores_other_ops_and_missing_files(tmp_path):
    nothing = lambda *a, **k: None  # noqa: E731
    assert db_summary.fix_changes(tmp_path, [(" M", "call/CALL-001-x/type.md")], [{"op": "new-cause", "cause": {}}],
                                  "abc", nothing) == []
    assert db_summary.fix_changes(tmp_path, [], [{"op": "update-fix", "cause": "CALL-001-01"}], "abc", nothing) == []


def test_pr_body_lists_fix_changes_block():
    rows = [{"line": "CALL-001-01: fixed → open (이전 ref X → verification_history 보존, 결과 reverted)"}]
    body = db_summary.pr_body(_screen(fix_changes=rows), {})
    assert ("\n### 수정 상태 변경\n\n- CALL-001-01: fixed → open (이전 ref X → verification_history 보존, 결과 reverted)"
            "\n\n### 변경 파일") in body
    assert "수정 상태 변경" not in db_summary.pr_body(_screen(), {})


def test_summary_flow_reports_fix_changes_only_for_fix_ops():
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    from workspace import Workspace
    ws = Workspace()
    job = "fix-reopen-CALL-001-01"
    plan = {"source": "fix-submitted", "schema_version": 1, "started_at": "2026-10-01T10:00+09:00", "jira": None,
            "commit_message": "[X] 수정 상태 되돌림",
            "operations": [{"op": "update-fix", "cause": "CALL-001-01", "fix": {"status": "open"},
                            "history": {"result": "reverted", "note": "회귀 의심 확인"}}]}
    ws.plan(job, plan)
    ws.acquire(job)
    ws.stage(job, f"fix/{job}")
    summary = ws.db_pr("summary", ws.wt(job))
    [row] = summary["fix_changes"]
    assert row["cause"] == "CALL-001-01" and (row["from"], row["to"]) == ("fixed", "open")
    assert row["history"]["result"] == "reverted" and row["history"]["ref"] == "MOCKCL-12345"
    assert row["line"].startswith("CALL-001-01: fixed → open (이전 ref MOCKCL-12345·fixed_in MOCKB77_U2_20260920")
    assert "### 수정 상태 변경" in summary["pr_body"] and f"- {row['line']}" in summary["pr_body"]
    ws.db_pr("discard", ws.wt(job))
    other = Workspace()
    other.plan("MOCK-7003", "p7-analyze-append.plan.json")
    other.acquire("MOCK-7003")
    other.stage("MOCK-7003", "issue/MOCK-7003")
    assert "fix_changes" not in other.db_pr("summary", other.wt("MOCK-7003"))


def test_library_boundary():
    code = ("import sys; sys.path.insert(0, %r); import db_summary; "
            "assert 'db_pr' not in sys.modules; assert not hasattr(db_summary, 'main'); print('ok')" % str(SCRIPTS))
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert proc.returncode == 0 and proc.stdout.strip() == "ok", proc.stderr
    assert not (SCRIPTS / "db_summary.py").read_text(encoding="utf-8").startswith("#!")


def test_db_pr_uses_db_summary():
    import db_pr
    assert db_pr.db_summary is db_summary
    assert not hasattr(db_pr, "pr_body") and not hasattr(db_pr, "reviewers")
    assert hasattr(db_pr, "approved_hash")


# --- 마크다운 렌더 (`db_pr summary --format markdown`, write-flow.md §4) -----------------------------------------

RENDER = REPO / "tests" / "fixtures" / "render"
WRITE_FLOW = (REPO / "plugin" / "skills" / "telephony-triage" / "reference" / "write-flow.md").read_text(encoding="utf-8")


def _render_screen(**over) -> dict:
    """`screen()` 결과 모양의 합성 입력. 기본은 analyze append: 검사 5개와 R1~R6 전부 통과."""
    stage = {"checks": {"verify": {"code": OK, "result": {"rules": [
        {"id": r, "status": "pass", "reason": "통과 사유"} for r in ("R1", "R2", "R3", "R4")] + [
        {"id": "R5", "status": "pass", "reason": "추가 없음"}, {"id": "R6", "status": "pass", "reason": "표본 없음"}]}}}}
    base = {
        "source": "analyze", "source_label": "분석 (analyze)", "jira": {"key": "MOCK-7001", "origin": "mcp", "label": None},
        "branch": {"name": "issue/MOCK-7001", "remote": "신규", "remote_sha": None, "base": "main"},
        "reviewers": ["mock-org/telephony-data-owners"], "open_prs": [],
        "files": [{"kind": "Jira 기록", "path": "data/DATA-001-x/jira/MOCK-7001.yaml", "change": "신규"}],
        "ids": [], "fixtures": [], "drift_decisions": [], "readme_preview": ["| 2026-09-29 | MOCK-7001 | DATA-001-02 |"],
        "diff": ["+++ data/DATA-001-x/jira/MOCK-7001.yaml (신규)", "+key: MOCK-7001"], "diff_total_lines": 2,
        "diff_truncated": False,
        "checks": {"lint": {"ok": True, "errors": 0, "warnings": 0, "findings": []}, "ids": {"ok": True, "duplicates": []},
                   "mask": {"ok": True, "detections": 0},
                   "regress": {"ok": True, "passed": 21, "total": 21, "failed": []}, "build": {"ok": True}},
        "verification": db_summary._verification_rows(stage), "approval_needed": [], "notes": [],
        "commit_message": "[DATA-001-02] add MOCK-7001: 로밍 중 데이터 로밍 OFF", "pr_title": "[DATA-001-02] add MOCK-7001: 로밍 중 데이터 로밍 OFF",
        "push_allowed": True, "push_note": None, "pending_included": [],
    }
    base.update(over)
    return base


def _extra(**over) -> dict:
    base = {"target_id": "DATA-001-02", "target_title": "Roaming disabled", "resolution": [],
            "approved_hash": "0123456789abcdef0123456789abcdef01234567"}
    base.update(over)
    return base


def _scenario_record() -> tuple[dict, dict]:
    """record: 비성공 정보가 전부 있는 입력 — skipped·review_required·needs-approval·fail, lint·회귀 실패, push_note, diff 잘림."""
    stage = {"checks": {"verify": {"code": NEEDS_APPROVAL, "result": {"rules": [
        {"id": "R1", "status": "pass", "reason": "추출 확인"},
        {"id": "R2", "status": "fail", "reason": "DATA-001-03: C=0 | 양성 fixture"},
        {"id": "R3", "status": "skipped", "reason": "해당 없음"},
        {"id": "R4", "status": "needs-approval", "reason": "기존 이벤트 변경"},
        {"id": "R5", "status": "skipped", "reason": "코드 없음", "review_required": True},
        {"id": "R6", "status": "other", "reason": "알 수 없음"}]}}}}
    verification = db_summary._verification_rows(stage)
    diff = [f"+line {i}" for i in range(48)] + ["+```", "+끝"]
    scr = _render_screen(
        source="record", source_label="수동 기록 (record)", open_prs=None,
        jira={"key": "MOCK-7005", "origin": "file", "label": "Jira 메타데이터: 오프라인 파일"},
        pr_title="[DATA-001-04] record MOCK-7005: SIM 미준비",
        branch={"name": "issue/MOCK-7005", "remote": "갱신", "remote_sha": "abc", "base": "main"},
        reviewers=[], files=[{"kind": "유형", "path": "data/DATA-001-x/type.md", "change": "수정"},
                             {"kind": "기타", "path": "odd|name.md", "change": "신규"}],
        ids=[{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-03"},
             {"temp_id": "NEW-CAUSE-2", "id": "DATA-001-05"}],
        fixtures=[{"op_index": 1, "for": "DATA-001-04", "kind": "positive", "name": "DATA-001-04.log",
                   "path": "fixtures/DATA-001-04.log"}],
        fix_changes=[{"line": "CALL-001-01: fixed → open (이전 ref MOCKCL-12345·fixed_in MOCKB77_U2_20260920 → "
                              "verification_history 보존, 결과 reverted)"}],
        notes=["로그·코드 분석: 하지 않음 (수동 기록)", "DATA-001-04: 시그니처 없음 — 매칭 불가, 리뷰 대상",
               "drift: DATA-001-02 resolution — 계획 값 유지 (계획 값: 켠다, main 값: 끈다)", "R5: 검증 못 함 — 리뷰 대상 (코드 없음)"],
        diff=diff, diff_total_lines=80, diff_truncated=True, verification=verification,
        approval_needed=[r for r in verification if r["status"] == "needs-approval"],
        checks={"lint": {"ok": False, "errors": 2, "warnings": 1, "findings": ["E-TITLE: a.md", "E-ID: b.md"]},
                "ids": {"ok": False, "duplicates": ["DATA-001-04"]}, "mask": {"ok": False, "detections": 3},
                "regress": {"ok": False, "passed": 19, "total": 21, "failed": ["f1.log", "f2.log"]}, "build": {"ok": False}},
        commit_message="[DATA-001-04] record MOCK-7005: SIM 미준비\n\n```\n본문 펜스\n```", push_allowed=False,
        push_note="push 불가: gh 인증 없음 (--dry-run)")
    return scr, _extra(target_id="DATA-001-04", target_title="SIM 미준비",
                       resolution=[{"cause": "DATA-001-04", "state": "unverified", "reason": "신규 원인 (new-cause)"}])


def _scenario_skipped_checks() -> tuple[dict, dict]:
    return _render_screen(checks={"skipped": "dry-run: 검사 건너뜀"}, verification=[]), _extra()


SCENARIOS = {"analyze-append-pass": lambda: (_render_screen(), _extra()),
             "record-non-success": _scenario_record, "checks-skipped": _scenario_skipped_checks}

_PUB = {"number": 12, "branch": "issue/MOCK-7001", "head_sha": "a" * 40}
_ID = {"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}


def _res(reason, state="unverified"):
    return [{"cause": "DATA-001-04", "state": state, "reason": reason}]


# 결정 1~4를 잠그는 스냅샷: 케이스별 (screen, plan, extra)
PLAN_SCENARIOS = {
    "reassign-same": lambda: (_render_screen(ids=[_ID]), {"pr": {**_PUB, "ids": {"NEW-CAUSE-1": "DATA-001-04"}}}, _extra()),
    "reassign-base-differs": lambda: (_render_screen(ids=[{**_ID, "expected_at_base": "DATA-001-03"}]), {}, _extra()),
    "reassign-previous-differs": lambda: (_render_screen(ids=[{**_ID, "previous_id": "DATA-001-03"}]),
                                          {"pr": {**_PUB, "ids": {"NEW-CAUSE-1": "DATA-001-03"}}}, _extra()),
    "reassign-unknown": lambda: (_render_screen(ids=[_ID]), {"pr": _PUB}, _extra()),
    "title-present": lambda: (_render_screen(), {}, _extra()),
    "title-missing": lambda: (_render_screen(), {}, _extra(target_title=None)),
    "resolution-new-cause": lambda: (_render_screen(), {}, _extra(resolution=_res("신규 원인 (new-cause)"))),
    "resolution-set-resolution": lambda: (_render_screen(), {}, _extra(resolution=_res("해결책 변경 (set-resolution)"))),
    "resolution-user-statement": lambda: (_render_screen(), {}, _extra(resolution=_res("신규 원인 (new-cause), 근거: 사용자 진술"))),
    "resolution-null": lambda: (_render_screen(), {}, _extra(resolution=[])),
}


def _scenario(name):
    if name in PLAN_SCENARIOS:
        return PLAN_SCENARIOS[name]()
    scr, extra = SCENARIOS[name]()
    return scr, {}, extra


@pytest.mark.parametrize("name", sorted([*SCENARIOS, *PLAN_SCENARIOS]))
def test_render_markdown_snapshots(name):
    scr, plan, extra = _scenario(name)
    assert db_summary.render_markdown(scr, plan, extra) == (RENDER / f"{name}.md").read_text(encoding="utf-8")


def test_render_markdown_all_pass_has_one_check_per_rule():
    scr, extra = SCENARIOS["analyze-append-pass"]()
    text = db_summary.render_markdown(scr, {}, extra)
    assert text.splitlines()[0] == "## push 전 확인: MOCK-7001 → DATA-001-02 Roaming disabled"
    assert text.count("✅") == 5 + 6                                   # 자동 검사 5개 + R1~R6
    assert text.splitlines()[-1] == f"approved_hash: {extra['approved_hash']}"
    assert "열린 PR: 없음" in text and "승인 필요: 없음" in text


def test_render_markdown_never_shows_non_success_as_pass():
    scr, extra = _scenario_record()
    text = db_summary.render_markdown(scr, {}, extra)
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| R")}
    assert sorted(rows) == ["R1", "R2", "R3", "R4", "R5", "R6"]        # 검증 행 id는 정확히 한 번씩
    assert text.count("| R1 |") == 1
    for rid in ("R2", "R3", "R4", "R5", "R6"):                         # pass가 아닌 행에는 ✅·"통과"가 없다
        assert "✅" not in rows[rid] and "통과" not in rows[rid], rows[rid]
    assert "✅" in rows["R1"]
    assert "건너뜀: 해당 없음" in rows["R3"] and "검증 못 함 — 리뷰 대상" in rows["R5"]
    assert "❌ 실패" in rows["R2"] and "승인 필요" in rows["R4"] and "| other |" in rows["R6"]
    assert "승인 필요: R4 — 메인테이너 승인 필수" in text
    # 비성공 정보 전부: 실패 상세, 노트, 파일
    for needle in ("lint 오류: E-TITLE: a.md", "lint 오류: E-ID: b.md", "중복: DATA-001-04", "마스킹 검출 3건",
                   "회귀 실패 fixture: f1.log", "회귀 실패 fixture: f2.log", "(19/21)"):
        assert needle in text, needle
    for note in scr["notes"]:
        assert note.removeprefix("drift: ") in text.replace("drift: ", "")
    for f in scr["files"]:
        assert f["change"] in text
    assert "열린 PR: 확인 못 함" in text and "push 불가: gh 인증 없음 (--dry-run)" in text
    assert "odd\\|name.md" in text                                      # 셀의 | 는 이스케이프
    assert "전체 80줄 중 50줄" in text


def test_render_markdown_fences_stay_closed_and_commit_message_is_verbatim():
    scr, extra = _scenario_record()
    text = db_summary.render_markdown(scr, {}, extra)
    assert "````diff\n" in text and "\n````\n" in text                  # 내용에 ```가 있으면 펜스를 늘린다
    block = text.split("### 커밋 메시지 / PR 제목\n\n", 1)[1]
    assert block.startswith("````\n" + scr["commit_message"] + "\n````\n")
    assert text.splitlines()[-1].startswith("approved_hash: ") and text.endswith("\n")


def test_render_markdown_sections_for_drift_fix_changes_and_empty_values():
    scr, extra = _scenario_record()
    text = db_summary.render_markdown(scr, {}, extra)
    assert "### 수정 상태 변경\n\n- CALL-001-01: fixed → open (이전 ref" in text
    drift = text.split("### drift 결정 내역\n\n", 1)[1].split("\n\n", 1)[0]
    assert drift.startswith("- drift: DATA-001-02 resolution") and "로그·코드 분석" not in drift
    scr2, extra2 = SCENARIOS["checks-skipped"]()
    plain = db_summary.render_markdown(scr2, {}, extra2)
    assert "### 수정 상태 변경" not in plain and "### drift 결정 내역" not in plain
    assert "자동 검사: 건너뜀 — dry-run: 검사 건너뜀" in plain and "✅" not in plain
    assert "### 검증 결과\n\n검증: 건너뜀 — dry-run: 검사 건너뜀" in plain       # "없음"으로 두지 않는다
    assert "### 추가 설명\n\n없음" in plain


# 표 기반: 입력 → 기대 문구. 출처는 각 케이스 주석.
@pytest.mark.parametrize("row,expected", [
    # write-flow.md §4 "ID 할당" 항목: `ids[].expected_at_base`가 다르면 '계획 당시 DATA-001-03 → DATA-001-04 (main에 먼저 머지된 원인)'
    ({"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-03"},
     "NEW-CAUSE-1 → DATA-001-04: 계획 당시 DATA-001-03 → DATA-001-04 (main에 먼저 머지된 원인)"),
    # 같은 항목: 이전 적용(`previous_id`, 계획 pr.ids 기록)과 다르면 'DATA-001-03 → DATA-001-04 재할당'
    ({"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "previous_id": "DATA-001-03"},
     "NEW-CAUSE-1 → DATA-001-04: DATA-001-03 → DATA-001-04 재할당"),
    ({"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-02", "previous_id": "DATA-001-03"},
     "NEW-CAUSE-1 → DATA-001-04: 계획 당시 DATA-001-02 → DATA-001-04 (main에 먼저 머지된 원인); DATA-001-03 → DATA-001-04 재할당"),
    # 기본형 `NEW-CAUSE-1 → DATA-001-04`: 같거나 모를 때
    ({"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-04"}, "NEW-CAUSE-1 → DATA-001-04"),
    ({"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "previous_id": "DATA-001-04"}, "NEW-CAUSE-1 → DATA-001-04"),
    ({"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}, "NEW-CAUSE-1 → DATA-001-04"),
])
def test_id_assignment_wording(row, expected):
    assert db_summary.id_assignment(row) == expected


def test_id_assignment_phrase_is_the_one_written_in_write_flow():
    assert "'계획 당시 DATA-001-03 → DATA-001-04 (main에 먼저 머지된 원인)'" in WRITE_FLOW
    assert "'DATA-001-03 → DATA-001-04 재할당'" in WRITE_FLOW
    assert "NEW-CAUSE-1 → DATA-001-04" in WRITE_FLOW


NEW_CAUSE_USER = {"op": "new-cause", "temp_id": "DATA-001-03",
                  "cause": {"resolution_verification": {"status": "unverified", "method": "근거: 사용자 진술"}}}


@pytest.mark.parametrize("ops,expected", [
    # write-flow.md §4 "계획에 `set-resolution`이 있거나 새 원인이면 unverified"(옛 §4 L113-114); 사유 어휘는 사용자 결정(contracts.md §3.2 summary 행)
    ([{"op": "new-cause", "temp_id": "DATA-001-03"}], [("DATA-001-03", "unverified", "신규 원인 (new-cause)")]),
    ([{"op": "set-resolution", "cause": "DATA-001-02"}], [("DATA-001-02", "unverified", "해결책 변경 (set-resolution)")]),
    # db-authoring.md §2 `resolution_verification` 항목: 사용자 진술만 있으면 method "근거: 사용자 진술"(unverified)
    ([NEW_CAUSE_USER], [("DATA-001-03", "unverified", "신규 원인 (new-cause), 근거: 사용자 진술")]),
    # 어휘가 정해지지 않은 op는 op 이름만(어휘를 지어내지 않는다)
    ([{"op": "new-type", "temp_id": "NETWORK-002", "first_cause": {"temp_id": "NETWORK-002-01"}}],
     [("NETWORK-002-01", "unverified", "신규 유형 (new-type)")]),
    # "같은 계획의 `verify-resolution`이 적용된 경우만 verified"
    ([{"op": "new-cause", "temp_id": "DATA-001-03"}, {"op": "verify-resolution", "cause": "DATA-001-03"}],
     [("DATA-001-03", "verified", "verify-resolution")]),
    ([{"op": "set-resolution", "cause": "DATA-001-02"}, {"op": "verify-resolution", "cause": "DATA-001-02"}],
     [("DATA-001-02", "verified", "verify-resolution")]),
    ([{"op": "verify-resolution", "cause": "DATA-001-02"}], [("DATA-001-02", "verified", "verify-resolution")]),
    # 다른 원인의 verify-resolution은 이 원인을 올리지 않는다
    ([{"op": "new-cause", "temp_id": "DATA-001-03"}, {"op": "verify-resolution", "cause": "DATA-001-02"}],
     [("DATA-001-03", "unverified", "신규 원인 (new-cause)"), ("DATA-001-02", "verified", "verify-resolution")]),
    # 해결책을 바꾸는 op가 없으면 값 없음(null → "해당 없음")
    ([{"op": "append", "cause": "DATA-001-02"}, {"op": "update-fix", "cause": "DATA-001-02"}], []),
])
def test_resolution_states(ops, expected):
    got = [(s["cause"], s["state"], s["reason"]) for s in db_summary.resolution_states(ops)]
    assert got == expected


def test_resolution_state_lines_and_not_applicable_case():
    scr = _render_screen()
    for states, line in [
        ([{"cause": "DATA-001-03", "state": "unverified", "reason": "신규 원인 (new-cause)"}],
         "해결책 검증 상태: DATA-001-03 — unverified(신규 원인 (new-cause))"),
        ([{"cause": "DATA-001-03", "state": "unverified", "reason": "해결책 변경 (set-resolution)"}],
         "해결책 검증 상태: DATA-001-03 — unverified(해결책 변경 (set-resolution))"),
        ([{"cause": "DATA-001-03", "state": "unverified", "reason": "신규 원인 (new-cause), 근거: 사용자 진술"}],
         "해결책 검증 상태: DATA-001-03 — unverified(신규 원인 (new-cause), 근거: 사용자 진술)"),
        ([{"cause": "DATA-001-03", "state": "unverified", "reason": "신규 유형 (new-type)"}],
         "해결책 검증 상태: DATA-001-03 — unverified(신규 유형 (new-type))"),
        ([{"cause": "DATA-001-03", "state": "verified", "reason": "verify-resolution"}],
         "해결책 검증 상태: DATA-001-03 — verified(verify-resolution)"),
    ]:
        assert line in db_summary.render_markdown(scr, {}, _extra(resolution=states)).splitlines()
    none = db_summary.render_markdown(scr, {}, _extra(resolution=[]))
    assert "해결책 검증 상태: 해당 없음 (이번 계획은 해결책을 바꾸지 않음)" in none.splitlines()     # type.md 현재 상태를 읽지 않는다
    for phrase in ("해결책 검증 상태", "unverified(사유)", "verified", "set-resolution", "verify-resolution"):
        assert phrase in WRITE_FLOW, phrase                                        # write-flow.md §4 (옛 §4 L105-106, L113-114)
    assert not hasattr(db_summary, "target_resolution_raw")


def test_resolution_vocabulary_is_listed_in_contracts_and_07_example_matches_render():
    contracts = (REPO / "docs" / "design" / "contracts.md").read_text(encoding="utf-8")
    for phrase in ("신규 원인 (new-cause)", "신규 유형 (new-type)", "해결책 변경 (set-resolution)", "근거: 사용자 진술",
                   "해당 없음 (이번 계획은 해결책을 바꾸지 않음)", "재할당 내역: 확인 불가 (이전 적용 ID 기록 없음)", "pr_ids_recorded", "(제목 없음)"):
        assert phrase in contracts, phrase
    workflow = (REPO / "docs" / "design" / "07-workflow.md").read_text(encoding="utf-8")
    assert "해결책 검증 상태: DATA-001-03 — unverified(신규 원인 (new-cause))" in workflow
    assert "근거: 사용자 진술" in (REPO / "plugin/skills/telephony-triage/reference/db-authoring.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("message,target", [
    # write-flow.md 계획 형식: "commit_message": "[<원인 또는 유형 ID>] add <KEY>: <요약>"
    ("[DATA-001-03] add MOCK-7002: SIM 미준비", "DATA-001-03"),
    ("[DATA-001] add MOCK-7004: 원인 미확인", "DATA-001"),
    ("add MOCK-7002 without bracket", None), ("", None), (None, None),
    ("[NEW-CAUSE-1] add X", None), ("[DATA-1] add X", None),       # ID 패턴(common.fixtures)에 안 맞으면 대상이 아니다
])
def test_target_id(message, target):
    assert db_summary.target_id(message) == target


@pytest.mark.parametrize("target,title", [
    # write-flow.md §4 머리: `→ <원인/유형 ID 제목>` — 원인 ID면 원인 title, 유형 ID면 유형 title
    ("DATA-001-03", "SIM 미준비"), ("DATA-001-02", "Roaming disabled"), ("DATA-001", "SETUP_DATA_CALL이 발생하지 않음"),
    ("DATA-001-09", None), ("NEW-CAUSE-1", None), ("DATA-009", None), (None, None),
])
def test_target_title(tmp_path, target, title):
    import yaml
    path = tmp_path / "data" / "DATA-001-x" / "type.md"
    path.parent.mkdir(parents=True)
    data = {"id": "DATA-001", "title": "SETUP_DATA_CALL이 발생하지 않음",
            "causes": [{"id": "DATA-001-02", "title": "Roaming disabled"}, {"id": "DATA-001-03", "title": "SIM 미준비"}]}
    path.write_text("---\n" + yaml.safe_dump(data, allow_unicode=True) + "---\n본문\n", encoding="utf-8")
    assert db_summary.target_title(tmp_path, target) == title


@pytest.mark.parametrize("jira,target,title,head", [
    ({"key": "MOCK-7002"}, "DATA-001-03", "SIM 미준비", "## push 전 확인: MOCK-7002 → DATA-001-03 SIM 미준비"),
    ({"key": "MOCK-7002"}, "DATA-001-03", None, "## push 전 확인: MOCK-7002 → DATA-001-03 (제목 없음)"),   # 제목을 못 읽으면 "(제목 없음)"(contracts.md §3.2 summary 행)
    ({}, "DATA-001-03", "SIM 미준비", "## push 전 확인: DATA-001-03 → DATA-001-03 SIM 미준비"),   # KEY 없으면 원인 ID
    # 대상 ID 없음: 조용히 생략하지 않고 원값(커밋 메시지 첫 줄)을 보인다 — 문서 출처 없음
    ({"key": "MOCK-7002"}, None, None,
     "## push 전 확인: MOCK-7002 → (규칙 없음 — 원값: [DATA-001-02] add MOCK-7001: 로밍 중 데이터 로밍 OFF)"),
])
def test_render_heading(jira, target, title, head):
    out = db_summary.render_markdown(_render_screen(jira=jira), {}, _extra(target_id=target, target_title=title))
    assert out.splitlines()[0] == head


def test_md_cell_and_fence():
    assert db_summary._md_cell("a|b\nc") == "a\\|b c" and db_summary._md_cell(None) == ""
    assert db_summary._fence("x") == "```\nx\n```"
    assert db_summary._fence("a ```` b", "diff") == "`````diff\na ```` b\n`````"


def _reassign_text(ids, plan) -> str:
    return db_summary.render_markdown(_render_screen(ids=ids), plan, _extra())


UNKNOWN = "- 재할당 내역: 확인 불가 (이전 적용 ID 기록 없음)"


def test_render_markdown_reassignment_four_cases_and_no_pr():
    published = {"pr": {"number": 12, "branch": "issue/X", "head_sha": "a" * 40}}
    # 같음: 줄 없음
    same = _reassign_text([{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}], {"pr": {**published["pr"], "ids": {"NEW-CAUSE-1": "DATA-001-04"}}})
    assert "- NEW-CAUSE-1 → DATA-001-04\n" in same and "재할당" not in same and "확인 불가" not in same
    # 계획 당시 다름
    base = _reassign_text([{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-03"}], {})
    assert "- NEW-CAUSE-1 → DATA-001-04: 계획 당시 DATA-001-03 → DATA-001-04 (main에 먼저 머지된 원인)" in base
    # 이전 적용 다름
    prev = _reassign_text([{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "previous_id": "DATA-001-03"}],
                          {"pr": {**published["pr"], "ids": {"NEW-CAUSE-1": "DATA-001-03"}}})
    assert "- NEW-CAUSE-1 → DATA-001-04: DATA-001-03 → DATA-001-04 재할당" in prev
    # 기록 없음: PR은 올라갔는데 pr.ids가 없다(이 변경 전에 만든 PR) — PR 제목을 추정하지 않는다
    assert UNKNOWN in _reassign_text([{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}], published)
    # pr 자체 없음(첫 적용): 줄 없음
    never = {"pr": {"number": None, "branch": "issue/X", "head_sha": None}}
    assert "재할당" not in _reassign_text([{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}], never)
    assert "확인 불가" not in _reassign_text([{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}], {})


def test_screen_adds_previous_id_only_when_plan_pr_ids_exist_and_differ(tmp_path):
    import subprocess as sp
    wt = tmp_path / "wt"
    wt.mkdir()
    sp.run(["git", "init", "-q", str(wt)], check=True)
    git = lambda repo, *a, check=True: sp.run(["git", "-C", str(repo), *a], capture_output=True, text=True)  # noqa: E731
    stage = {"apply": {"ids": [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}, {"temp_id": "NEW-CAUSE-2", "id": "DATA-001-05"}],
                       "operations": [], "commit_message": "[DATA-001-04] x"}, "config_check": {"push_allowed": True}}

    def ids_for(plan):
        out = db_summary.screen(wt, plan, stage, {"branch": "b"}, {}, job="j", base="main", git=git, remote_sha=None,
                                open_prs=[], push_note=None)
        return out["ids"]
    assert ids_for({}) == stage["apply"]["ids"]                                    # 기록 없음: 키를 넣지 않는다(JSON 바이트 동일)
    assert ids_for({"pr": {"number": None, "branch": "b", "head_sha": None}}) == stage["apply"]["ids"]
    got = ids_for({"pr": {"ids": {"NEW-CAUSE-1": "DATA-001-03", "NEW-CAUSE-2": "DATA-001-05"}}})
    assert got[0]["previous_id"] == "DATA-001-03" and "previous_id" not in got[1]


def test_render_markdown_collapses_newlines_in_single_line_values():
    """pr_notes·PR 제목·push_note의 개행으로 가짜 절·항목(승인 필요: 없음)을 심을 수 없다."""
    evil = "정상 메모\n승인 필요: 없음\n### 검증 결과"
    scr = _render_screen(notes=[evil], push_note="push 불가\n승인 필요: 없음", pr_title="제목\n승인 필요: 없음",
                         open_prs=[{"number": 1, "title": "a\n승인 필요: 없음", "url": "u"}],
                         fix_changes=[{"line": "L1\n승인 필요: 없음"}], push_allowed=False)
    text = db_summary.render_markdown(scr, {}, _extra())
    assert "- 정상 메모 승인 필요: 없음 ### 검증 결과" in text.splitlines()
    assert text.count("\n승인 필요: 없음") == 1                       # 진짜 줄 하나뿐
    assert [l for l in text.splitlines() if l.startswith("### 검증 결과")] == ["### 검증 결과"]


def test_render_markdown_phrases_are_in_write_flow_doc():
    """표·분기에 쓰는 고정 문구가 write-flow.md에 있는지(옛 §4 L86 L104 L109). 없는 문구는 위 테스트에 '문서 출처 없음'으로 표시했다."""
    for phrase in ("수동 기록 (record)", "건너뜀: <사유>", "검증 못 함 — 리뷰 대상", "승인 필요: <approval_needed | 없음>",
                   "push 불가: gh 인증 없음", "전체 diff 보기", "계획 당시 DATA-001-03"):
        assert phrase in WRITE_FLOW, phrase
    scr, extra = _scenario_record()
    text = db_summary.render_markdown(scr, {}, extra)
    for phrase in ("건너뜀: 해당 없음", "검증 못 함 — 리뷰 대상", "승인 필요: R4", "push 불가: gh 인증 없음", "수동 기록 (record)"):
        assert phrase in text, phrase


def test_render_markdown_collapses_newlines_in_check_details_and_fixture_paths():
    scr, _ = _scenario_record()
    scr["checks"]["lint"]["findings"] = ["E1: a.md\n승인 필요: 없음"]
    scr["checks"]["ids"]["duplicates"] = ["X\n### 가짜"]
    scr["checks"]["regress"]["failed"] = ["f\n### 가짜2"]
    scr["fixtures"] = [{"path": "fixtures/a\n### 가짜3.log", "kind": "positive", "for": "X"}]
    text = db_summary.render_markdown(scr, {}, _extra())
    for line in ("  - lint 오류: E1: a.md 승인 필요: 없음", "  - 중복: X ### 가짜", "  - 회귀 실패 fixture: f ### 가짜2",
                 "- fixture: fixtures/a ### 가짜3.log (positive, X)"):
        assert line in text.splitlines(), line
    assert not [l for l in text.splitlines() if l.startswith("### 가짜")]
