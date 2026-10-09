#!/usr/bin/env python3
"""Phase 11 완료 기준 확인: 월간 리뷰와 통계 (11-phases.md Phase 11, 06-collaboration.md §6.6·§6.7).

- `issue-db-review`(`tests/helpers/make_variant_dbs.py`가 테스트 때 만든다, `runner.variant_db()`)에 일부러 넣은 케이스를
  `db_review.py`가 모두 잡는지 본다. 기준일은 `--as-of 2026-10-20`.
- 방치 기간(해결책 미검증, 수정 검증 대기, Jira 없는 원인의 나이)은 git 이력이 근거라서, 날짜를 지정한 커밋으로
  이력을 만든 레포에서 본다.
- STATS(§6.7): 급증은 `occurred_on` 기준(과거 이슈 일괄 기록은 급증 아님), 유형별 건수.

`pytest tests/test_db_review.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import copy_db, edit, run, run_json, tmp, variant_db  # noqa: E402

REVIEW_DB = variant_db("issue-db-review")
AS_OF = "2026-10-20"
DATA = "data/DATA-001-no-setup-data-call"
DATA2 = "data/DATA-009-legacy-evaluation"


def _review(db: Path, *extra: str) -> dict:
    return run_json("db_review.py", ["--db", db, "--as-of", AS_OF, "--json", *extra])


def _item(report: dict, key: str) -> dict:
    return next(i for i in report["items"] if i["key"] == key)


def _ids(report: dict, key: str, field: str = "cause") -> list:
    return [e.get(field) for e in _item(report, key)["entries"]]


def _commit(repo: Path, when: str, message: str, author: str = "tt") -> None:
    env = {**os.environ, "GIT_AUTHOR_DATE": f"{when}T12:00:00+0900", "GIT_COMMITTER_DATE": f"{when}T12:00:00+0900"}
    for args in (["add", "-A"], ["-c", f"user.name={author}", "-c", "user.email=tt@example.invalid", "commit", "-qm",
                                 message]):
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
        assert proc.returncode == 0, proc.stderr


def _dated_repo() -> Path:
    """2026-06-01 커밋(작성자 mock-a. DATA-009-02는 아직 open, DATA-001-02 해결책은 옛 문구)
    → 2026-10-10 커밋(작성자 mock-b, 최종 트리)."""
    db = copy_db(REVIEW_DB)
    subprocess.run(["git", "-C", str(db), "init", "-q", "-b", "main"], check=True)
    data2 = db / DATA2 / "type.md"
    final2 = data2.read_text(encoding="utf-8")
    data1 = db / DATA / "type.md"
    final1 = data1.read_text(encoding="utf-8")
    edit(data2, "    fix:\n      status: fix-submitted\n      ref: null", "    fix:\n      status: open\n      ref: null")
    edit(data1, "    resolution: 데이터 로밍 설정을 켠다", "    resolution: 로밍 설정을 확인한다")
    _commit(db, "2026-06-01", "init", author="mock-a")
    data2.write_text(final2, encoding="utf-8", newline="\n")
    data1.write_text(final1, encoding="utf-8", newline="\n")
    _commit(db, "2026-10-10", "update", author="mock-b")
    return db


def test_review_report_catches_every_planted_case():
    report = _review(REVIEW_DB)
    assert report["as_of"] == AS_OF and report["category"] is None and report["head"] is None
    assert _ids(report, "pending-signatures") == ["DATA-001-03"]
    # pending 원인은 "fixture 없는 원인"이 아니라 "시그니처 없는 원인"으로 센다
    assert _ids(report, "no-fixture") == ["DATA-009-01", "DATA-009-02"]
    assert _ids(report, "stale-unresolved", "jira") == ["MOCK-1105"]          # MOCK-1104(24일)는 아님
    low = _item(report, "low-acceptance")["entries"]
    assert [(e["signature"], e["accepted"], e["total"]) for e in low] == [("DATA-001-01/data-disabled", 2, 6)]
    dup = _item(report, "duplicate-candidates")["entries"]
    # DATA-002-01(APM) fixture 하나가 DATA-001(평가 불허+SETUP 없음)·DATA-009 증상과도 동시에 걸려 DATA-002가 낀 후보 둘이 생긴다.
    # 제목 유사도는 없다(title_similarity None). 사용자 데이터 OFF 표본(extra.1)은 must_not_match로 DATA-002 S=0이라 관여하지 않는다.
    assert [d["types"] for d in dup] == [["DATA-001", "DATA-002"], ["DATA-001", "DATA-009"], ["DATA-002", "DATA-009"]]
    assert dup[1]["fixtures"] and dup[1]["title_similarity"] >= 0.8  # 심은 중복 후보는 제목도 비슷하다
    # 지원 종료: 빈 android_versions(DATA-001-02 등)는 전 버전이라 제외
    assert _ids(report, "unsupported-versions") == ["DATA-009-01"]
    assert _ids(report, "stale-causes") == ["DATA-009-01"]
    assert _ids(report, "no-trace-signatures") == ["DATA-009-02", "IMS-001-01", "SMS-001-01"]
    assert _ids(report, "fix-fields-missing") == ["DATA-009-02"]
    assert _item(report, "fix-fields-missing")["entries"][0]["missing"] == ["ref", "fixed_in"]
    assert _ids(report, "fix-submitted-no-build") == ["DATA-009-01"]
    statement = {e["cause"]: e["sources"] for e in _item(report, "user-statement-only")["entries"]}
    assert statement == {"DATA-001-02": ["jira:MOCK-1103"], "DATA-001-03": ["method"]}
    assert _ids(report, "verification-failures") == ["CALL-001-01", "IMS-001-01"]
    allowed = _item(report, "also-allowed-accumulated")["entries"]
    assert {(e["kind"], e.get("cause") or e["fixture"]) for e in allowed} == {
        ("fixture", "network/NETWORK-001-no-service/fixtures/NETWORK-001-01.log"), ("cause", "IMS-001-01")}
    # 급증: NETWORK-001-01만. SMS-001-01은 최근에 기록했지만 발생일(occurred_on)이 과거라 아니다
    assert _ids(report, "surge") == ["NETWORK-001-01"]
    assert _ids(report, "open-with-jira")[0] == "NETWORK-001-01"
    # git 이력이 없으면 방치 기간은 판단하지 않고 "확인 불가"로 따로 보인다
    assert _item(report, "fix-submitted-stale")["entries"] == []
    assert {e["reason"] for e in _item(report, "fix-submitted-stale")["undetermined"]} == {"no-history"}


def test_manual_feedback_is_not_in_acceptance():
    report = _review(REVIEW_DB)
    # 피드백 13건: 샘플 3(manual 1) + 1위 제시 7 + manual 3
    assert report["feedback"] == {"total": 13, "manual": 4, "used_for_acceptance": 9}
    # roaming-disabled: 1위 3건(1/3)은 min_samples 미만이라 품질 항목에 없다
    assert [e["signature"] for e in _item(report, "low-acceptance")["entries"]] == ["DATA-001-01/data-disabled"]


def test_category_scope_and_owners():
    report = _review(REVIEW_DB, "sms")
    assert report["category"] == "sms"
    assert report["owners"]["sms"] == ["@mock-org/telephony-sms-owners"]
    for item in report["items"]:
        for entry in item["entries"]:
            ident = entry.get("cause") or entry.get("jira") or entry.get("signature") or entry.get("fixture") or ""
            assert "SMS-" in json.dumps(entry, ensure_ascii=False), (item["key"], ident)
    assert _ids(report, "no-trace-signatures") == ["SMS-001-01"]
    assert _item(report, "duplicate-candidates")["entries"] == []
    proc = run("db_review.py", ["--db", REVIEW_DB, "nope", "--json"])
    assert proc.returncode == 2 and "nope" in proc.stderr


def test_stale_periods_come_from_git_history():
    db = _dated_repo()
    report = _review(db)
    assert report["head"]
    unverified = _ids(report, "unverified-stale")
    # 2026-06-01부터 unverified → 141일 > 60일. DATA-001-02는 해결책이 2026-10-10에 바뀌어 10일째.
    # DATA-001-03은 pending이라 검증할 수 없으므로 뺀다.
    assert "NETWORK-001-01" in unverified and "DATA-009-01" in unverified
    assert "DATA-001-02" not in unverified and "DATA-001-03" not in unverified
    assert _item(report, "unverified-stale")["undetermined"] == []
    # fix-submitted: SIM-001-01·DATA-009-01은 2026-06-01부터, DATA-009-02는 2026-10-10에 들어감(10일)
    assert _ids(report, "fix-submitted-stale") == ["DATA-009-01", "SIM-001-01"]
    entry = _item(report, "fix-submitted-stale")["entries"][1]
    assert (entry["since"], entry["days"], entry["by"]) == ("2026-06-01", 141, "mock-a")
    # 기록자는 상태가 시작된 커밋의 작성자다. DATA-009-01의 type.md는 10-10에 mock-b가 바꿨지만 상태는 그대로다.
    first = _item(report, "fix-submitted-stale")["entries"][0]
    assert (first["cause"], first["by"]) == ("DATA-009-01", "mock-a") and "기록: mock-a" in first["text"]
    # Jira 없는 DATA-009-02는 2026-06-01에 생겼으므로 12개월이 안 됐다. 1년 뒤에는 오래 안 쓰인 원인이다.
    assert _ids(report, "stale-causes") == ["DATA-009-01"]
    later = run_json("db_review.py", ["--db", db, "--as-of", "2027-07-01", "--json"])
    assert "DATA-009-02" in _ids(later, "stale-causes")
    # 커밋 전 워킹 트리 변경으로 생긴 상태는 기간을 모른다
    edit(db / "network/NETWORK-001-no-service/type.md", "      status: open\n", "      status: fix-submitted\n")
    edit(db / "network/NETWORK-001-no-service/type.md", "      ref: null\n", "      ref: MOCKCL-22222\n")
    dirty = _review(db)
    assert {"cause": "NETWORK-001-01", "reason": "uncommitted"}.items() <= next(
        e for e in _item(dirty, "fix-submitted-stale")["undetermined"] if e["cause"] == "NETWORK-001-01").items()


def test_review_is_read_only_and_writes_markdown():
    db = _dated_repo()
    out = tmp("tt-review-") / "report.md"
    proc = run("db_review.py", ["--db", db, "data", "--as-of", AS_OF, "--out", out])
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["out"] == str(out)
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# 월간 리뷰 리포트 — data (2026-10-20)")
    assert "오너: @mock-org/telephony-data-owners" in text
    assert "## 중복 후보" in text and "DATA-001 SETUP_DATA_CALL이 발생하지 않음 ↔ DATA-009" in text
    assert "수동 기록(`decision: manual`) 4건은 수락률에서 뺐다" in text
    status = subprocess.run(["git", "-C", str(db), "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""
    # 인자 없이 --out도 없으면 stdout에 Markdown
    md = run("db_review.py", ["--db", db, "--as-of", AS_OF])
    assert md.returncode == 0 and md.stdout.startswith("# 월간 리뷰 리포트 — 전체")


def test_report_shows_branch_and_uncommitted_changes():
    db = _dated_repo()
    clean = _review(db)
    assert (clean["branch"], clean["dirty"]) == ("main", False)
    subprocess.run(["git", "-C", str(db), "switch", "-qc", "review-wip"], check=True)
    (db / "wip-note.md").write_text("x\n", encoding="utf-8")
    wip = _review(db)
    assert (wip["branch"], wip["dirty"], wip["head"]) == ("review-wip", True, clean["head"])
    md = run("db_review.py", ["--db", db, "--as-of", AS_OF]).stdout
    assert "review-wip" in md and "커밋 안 된 변경 포함" in md
    plain = _review(copy_db(REVIEW_DB))       # git 최상위가 아니면 셋 다 null
    assert (plain["head"], plain["branch"], plain["dirty"]) == (None, None, None)


def test_stats_on_review_db():
    out = tmp("tt-preview-")
    run_json("db_build.py", ["--db", REVIEW_DB, "--preview", out])
    stats = (out / "STATS.md").read_text(encoding="utf-8")
    assert "> 기준일: 2026-10-18" in stats
    surge = stats.split("## 급증 원인", 1)[1].split("\n## ", 1)[0]
    assert "| NETWORK-001-01 | 3 |" in surge and "SMS-001-01" not in surge
    assert "### 유형별" in stats and "| DATA-009 | SETUP_DATA_CALL 요청이 나가지 않음 | 1 |" in stats
    quality_section = stats.split("## 시그니처 품질", 1)[1].split("\n## ", 1)[0]
    assert "| `DATA-001-01/data-disabled` | 6 | 2 | 0.33 | 예 |" in quality_section
    checks = stats.split("## 품질 점검", 1)[1]
    assert "시그니처 없는 원인: 1 (DATA-001-03)" in checks
    assert "fixture 없는 원인: 2 (DATA-009-01, DATA-009-02)" in checks
    assert "| 2026-10 | 7 | 3 |" in stats   # 기여 현황: 분석 7, 수동 기록 3


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
