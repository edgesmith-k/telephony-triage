#!/usr/bin/env python3
"""`db_lint --advice`: 시그니처가 하나뿐인 원인·유형 참고(advice) (03-issue-db.md §5.7 (2), 결정 기록 "근거 줄 소실" B).

빌드 버그로 근거 줄이 사라지면 조용히 "분류 후보 없음"·"원인 미확인"이 되고(`must_not_match` 근거면 잘못 맞는다)
다른 층 줄로 근거를 하나 더(있음은 시그니처 OR, 없음은 `must_not_match` 항목) 두라는 안내다.
참고는 옵션이 있을 때만 나오고 오류·경고 목록·수·종료 코드를 바꾸지 않는다 — 옵션이 없으면 출력(stdout·stderr)이 전과 같아 pre-commit·stage·사후 lint·site_audit·반입 멈춤 조건(`db_lint --all` 새 지적)에 들지 않는다.

`pytest tests/test_db_lint_advice.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_variant_dbs  # noqa: E402
from runner import SAMPLE, copy_db, edit, git, git_db, run, variant_db  # noqa: E402

SMS = "sms/SMS-001-sms-send-failed/type.md"
SAMPLE_TYPES = ["CALL-001", "DATA-001", "DATA-002", "IMS-001", "NETWORK-001", "SIM-001"]   # SMS-001은 증상 시그니처 둘
SAMPLE_CAUSES = ["CALL-001-01", "DATA-001-01", "DATA-001-02", "DATA-002-01", "IMS-001-01", "NETWORK-001-01",
                 "SIM-001-01", "SMS-001-01"]
SMS_SIG_END = "        must_not_match: ['RILJ.*>\\s*SEND_SMS\\b']\n        window_sec: 60\n"
SECOND_SIG = """      - id: send-request-missing-alt
        must_event:
          - {event: sms_send_failed}
        window_sec: 60
    recovery_signatures: []"""


def _lint(db, *args):
    proc = run("db_lint.py", ["--db", db, *args])
    return proc, json.loads(proc.stdout)


def _ids(advice, code):
    return sorted(f["message"].split(":", 1)[0] for f in advice if f["code"] == code)


def _dbs():
    return {"issue-db-sample": SAMPLE, **{n: variant_db(n) for n in make_variant_dbs.VARIANTS if n != "verify-logs"}}


def test_default_output_unchanged_and_advice_only_adds_keys():
    """샘플·모든 변형 DB: 옵션 없으면 `advice` 키·`참고[` 줄이 없고, 옵션이 있어도 오류·경고·종료 코드는 같다."""
    for name, db in _dbs().items():
        plain, base = _lint(db, "--all")
        flagged, extra = _lint(db, "--all", "--advice")
        assert "advice" not in base and "advice" not in base["summary"] and "참고[" not in plain.stderr, name
        assert flagged.returncode == plain.returncode, name
        advice = extra.pop("advice")
        assert extra["summary"].pop("advice") == len(advice), name
        assert extra == base, name                                       # 오류·경고 목록·수 그대로
        assert flagged.stderr.startswith(plain.stderr), name             # 기존 줄 뒤에 참고 줄만 붙는다
        added = flagged.stderr[len(plain.stderr):].splitlines()
        assert len(added) == len(advice) and all(line.startswith("참고[single-") for line in added), name
        assert all(f["level"] == "advice" for f in advice), name


def test_sample_advice_lists_every_single_signature_type_and_cause():
    proc, result = _lint(SAMPLE, "--all", "--advice")
    assert proc.returncode == 0 and result["errors"] == [] and result["warnings"] == []
    assert _ids(result["advice"], "single-symptom-signature") == SAMPLE_TYPES
    assert _ids(result["advice"], "single-signature") == SAMPLE_CAUSES
    assert all("03-issue-db §5.7 (2)" in f["message"] and "다른 층" in f["message"]
               and "must_not_match" in f["message"] for f in result["advice"])


def test_pending_cause_and_error_db_keep_exit_codes():
    """`signatures_pending` 원인은 참고에서 빠진다(경고 `signatures-pending`은 그대로). 오류 DB의 종료 코드 1도 그대로."""
    proc, result = _lint(variant_db("issue-db-pending"), "--all", "--advice")
    assert proc.returncode == 0 and "DATA-001-03" not in _ids(result["advice"], "single-signature")
    assert [w["code"] for w in result["warnings"]] == ["signatures-pending"]
    proc, result = _lint(variant_db("issue-db-lint-errors"), "--all", "--advice")
    assert proc.returncode == 1 and result["summary"]["errors"] == len(result["errors"]) > 0


def test_two_signatures_or_inactive_cause_get_no_advice():
    db = copy_db(SAMPLE)
    edit(db / SMS, SMS_SIG_END + "    recovery_signatures: []", SMS_SIG_END + SECOND_SIG)
    edit(db / "ims/IMS-001-ims-registration-failed/type.md", "  - id: IMS-001-01\n    status: active",
         "  - id: IMS-001-01\n    status: deprecated")
    edit(db / "call/CALL-001-volte-not-working/type.md", "\nstatus: active\n", "\nstatus: deprecated\n")
    proc, result = _lint(db, "--all", "--advice")
    assert proc.returncode == 0 and result["errors"] == [], result["errors"]
    causes = _ids(result["advice"], "single-signature")
    assert not {"SMS-001-01", "IMS-001-01", "CALL-001-01"} & set(causes), causes
    assert "CALL-001" not in _ids(result["advice"], "single-symptom-signature")
    assert "IMS-001" in _ids(result["advice"], "single-symptom-signature")    # 유형은 active 그대로


def test_changed_scope_filters_advice_like_findings():
    """`--changed`면 참고도 바뀐 파일 것만 낸다."""
    repo = git_db()
    git(repo, "checkout", "-qb", "work")
    edit(repo / SMS, "title: 전송 요청이 만들어지지 않음", "title: 전송 요청이 나가지 않음")
    git(repo, "commit", "-qam", "edit")
    proc, result = _lint(repo, "--changed", "main", "--advice")
    assert proc.returncode == 0
    assert {f["file"] for f in result["advice"]} == {SMS}, result["advice"]


def _all_tests():
    return [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
