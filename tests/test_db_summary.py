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
