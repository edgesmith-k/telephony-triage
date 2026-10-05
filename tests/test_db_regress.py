#!/usr/bin/env python3
"""Phase 5 완료 기준 확인: 회귀 `db_regress.py` (11-phases.md Phase 5, contracts.md §fixture).

- 샘플 fixture 전부 통과
- 음성 fixture를 일부러 깨면 어느 유형의 어떤 시그니처가 잡았는지 출력
- 다른 유형 원인이 C=1이 되어 깨지면 `allow-cause` 초안
- `signatures_pending` 원인의 양성 fixture가 `"<유형 ID>:unresolved"`로 포함 (`issue-db-pending/`)
- active가 아닌 원인의 fixture 제외, `--changed`·`--staged` 범위(parser-rules 변경이면 전체)
- 파서 백엔드 불일치·`--no-external`은 종료 코드 2, 정규식 시간 상한 초과는 실패

`pytest tests/test_db_regress.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, copy_db, edit, git, git_db, plugin_root, run, run_json, variant_db  # noqa: E402

D = "data/DATA-001-no-setup-data-call"
C = "call/CALL-001-volte-not-working"


def _regress(db, *scope, expect=(0, 1), **kw) -> dict:
    return run_json("db_regress.py", ["--db", db, *(scope or ("--all",))], expect=expect, **kw)


def _by_name(result) -> dict:
    return {r["fixture"].rsplit("/", 1)[1]: r for r in result["results"]}


def test_all_sample_fixtures_pass():
    result = _regress(SAMPLE, expect=0)
    assert result["summary"]["total"] == 20 and result["summary"]["failed"] == 0
    rows = _by_name(result)
    assert rows["CALL-001-01.log"]["C"] == ["CALL-001-01", "IMS-001-01"]  # also_allowed로 통과
    assert rows["CALL-001-01.fixed.MOCKB77_U2_20260920.log"]["expect"] == "expect_not: CALL-001-01"
    assert rows["DATA-001.none.2.log"]["expect"] == "expect_top: none"


def test_broken_negative_fixture_reports_type_and_signature():
    db = copy_db()
    log = db / D / "fixtures/DATA-001.none.log"
    kept = [line for line in log.read_text(encoding="utf-8").splitlines(keepends=True) if "SETUP_DATA_CALL" not in line]
    kept = [line.replace("evaluation result: ALLOWED reasons=[]", "evaluation result: NOT_ALLOWED reasons=[CONGESTED]")
            for line in kept]
    log.write_text("".join(kept), encoding="utf-8", newline="\n")
    proc = run("db_regress.py", ["--db", db, "--all"])
    assert proc.returncode == 1
    import json

    row = _by_name(json.loads(proc.stdout))["DATA-001.none.log"]
    assert row["status"] == "fail"
    (reason,) = row["reasons"]
    assert reason["type"] == "DATA-001" and reason["signature"] == "DATA-001/no-setup-data-call-request"
    assert "DATA-001/no-setup-data-call-request" in proc.stderr and "DATA-001.none.log" in proc.stderr


def test_cross_type_cause_gives_allow_cause_draft():
    db = copy_db()
    expect = db / C / "fixtures/CALL-001-01.expect.yaml"
    expect.write_text("\n".join(l for l in expect.read_text(encoding="utf-8").splitlines()
                                if "also_allowed" not in l and "IMS-001-01" not in l) + "\n",
                      encoding="utf-8", newline="\n")
    result = _regress(db, expect=1)
    row = _by_name(result)["CALL-001-01.log"]
    assert row["status"] == "fail"
    assert [r["cause"] for r in row["reasons"]] == ["IMS-001-01"]
    assert row["reasons"][0]["signature"] == "IMS-001-01/registration-forbidden"
    assert row["allow_cause_drafts"] == [{"op": "allow-cause", "fixture": "fixtures/CALL-001-01.log",
                                          "cause": "IMS-001-01"}]


def test_pending_cause_fixture_expects_unresolved():
    result = _regress(variant_db("issue-db-pending"), expect=0)
    row = _by_name(result)["DATA-001-03.log"]
    assert row["expect"] == "expect_top: DATA-001:unresolved" and row["status"] == "pass"
    assert row["S"] == ["DATA-001"] and row["C"] == []


def test_inactive_cause_fixtures_are_skipped():
    db = copy_db()
    edit(db / D / "type.md", "  - id: DATA-001-02\n    status: active", "  - id: DATA-001-02\n    status: deprecated")
    names = set(_by_name(_regress(db, expect=0)))
    assert "DATA-001-02.log" not in names and "DATA-001-02.extra.1.log" not in names
    assert "DATA-001-01.log" in names


def test_changed_and_staged_scope():
    repo = git_db()
    edit(repo / "network/NETWORK-001-no-service/type.md", "summary: ", "summary: (수정) ")
    changed = _regress(repo, "--changed", "main", expect=0)
    assert {r["fixture"].split("/")[0] for r in changed["results"]} == {"network"}
    assert changed["summary"]["expanded"] is False
    assert _regress(repo, "--staged", expect=0)["summary"]["total"] == 0  # 아직 index에 없다
    git(repo, "add", "-A")
    assert {r["fixture"].split("/")[0] for r in _regress(repo, "--staged", expect=0)["results"]} == {"network"}

    # CALL-001-01의 related(IMS-001-01)가 있는 유형이 바뀌면 그 유형도 돈다
    edit(repo / C / "type.md", "summary: ", "summary: (수정) ")
    cats = {r["fixture"].split("/")[0] for r in _regress(repo, "--changed", "main", expect=0)["results"]}
    assert cats == {"network", "call", "ims"}

    # parser-rules가 바뀌면 전체로 확장한다 (contracts.md §3.2 범위 확장 규칙)
    edit(repo / "parser-rules/ril.yaml", "reason: 초기}", "reason: 초기 (수정)}")
    expanded = _regress(repo, "--changed", "main", expect=0)
    assert expanded["summary"]["expanded"] is True and expanded["summary"]["total"] == 20


def test_backend_mismatch_and_no_external_are_usage_errors():
    root = plugin_root("site-backend", parser={"backend": "site"})
    proc = run("db_regress.py", ["--db", SAMPLE, "--all"], root=root)
    assert proc.returncode == 2 and "백엔드 불일치" in proc.stderr
    proc = run("db_regress.py", ["--db", SAMPLE, "--all", "--no-external"])
    assert proc.returncode == 2 and "--no-external" in proc.stderr


def test_pattern_timeout_is_failure():
    db = copy_db()
    edit(db / "issue-db.config.yaml", "pattern_timeout_ms: 2000", "pattern_timeout_ms: 300")
    edit(db / D / "type.md", "      - id: roaming-disabled\n",
         "      - id: slow\n        must_match: ['(a+)+$']\n        window_sec: 60\n      - id: roaming-disabled\n")
    log = db / D / "fixtures/DATA-001-01.log"
    log.write_text(log.read_text(encoding="utf-8") + "09-20 14:30:40.000  1234  1244 D DNC-0: " + "a" * 40 + "!\n",
                   encoding="utf-8", newline="\n")
    result = _regress(db, expect=1)
    row = _by_name(result)["DATA-001-01.log"]
    assert row["status"] == "fail"
    assert [r["kind"] for r in row["reasons"]] == ["error"] and row["reasons"][0]["signature"] == "DATA-001-02/slow"


def _all_tests():
    return [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
