"""C′ 부분 일치 (04-parser-matching.md §5.12): Evaluator.partial의 다섯 kind, match()의 `partial[]`·`absence_basis`,
회귀 모드는 계산하지 않음(출력 같음). 합성·마스킹된 이벤트만 쓴다."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import compiled as compiled_cache, issuedb  # noqa: E402
from common.signatures import Evaluator, compile_signature  # noqa: E402
import match_signatures  # noqa: E402

SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _ts(sec: float) -> str:
    return (T0 + timedelta(seconds=sec)).isoformat()


def _line(sec, tag, msg, line_no, phone=0):
    return {"ts": _ts(sec), "tag": tag, "msg": msg, "event": None, "phone_id": phone,
            "line_ref": {"file_index": 1, "line_no": line_no}}


def _ev(sec, event, line_no, phone=0, **fields):
    return {"ts": _ts(sec), "tag": "X", "msg": "m", "event": event, "fields": fields, "phone_id": phone,
            "line_ref": {"file_index": 1, "line_no": line_no}}


def _partial(events, raw, lo=0, hi=600):
    sig = compile_signature({"window_sec": 30, "id": "s", **raw}, "T-1")
    with Evaluator(events, T0 + timedelta(seconds=lo), T0 + timedelta(seconds=hi)) as ev:
        assert not ev.evaluate(sig).satisfied
        return ev.partial(sig)


A, B, C = ({"id": x, "pattern": f"Tag: step_{x}"} for x in "abc")


def test_missing_two_of_three():
    events = [_line(10, "Tag", "step_a", 120), _line(12, "Tag", "step_b", 131)]
    p = _partial(events, {"must_match": [A, B, C]})
    assert (p["kind"], p["m"], p["n"]) == ("missing", 2, 3)
    assert [c.id for c in p["missing"]] == ["c"]
    assert [c.id for c, _ in p["hits"]] == ["a", "b"]


def test_missing_below_half_is_none():
    assert _partial([_line(10, "Tag", "step_a", 1)], {"must_match": [A, B, C]}) is None   # 1/3 < 0.5


def test_absent_single_condition():
    p = _partial([_line(10, "Tag", "other", 1)], {"must_match": [A]})
    assert p["kind"] == "absent" and p["m"] == 0 and p["hits"] == []


def test_blocked_by_negative():
    events = [_line(10, "Tag", "step_a", 1), _line(11, "Tag", "veto", 2)]
    p = _partial(events, {"must_match": [A], "must_not_match": ["Tag: veto"]})
    assert p["kind"] == "blocked" and p["blocked_by"] == "Tag: veto"


def test_order_mismatch():
    events = [_line(10, "Tag", "step_b", 1), _line(12, "Tag", "step_a", 2)]
    p = _partial(events, {"must_match": [A, B], "sequence": ["a", "b"]})
    assert p["kind"] == "order" and p["order"] == ["a", "b"]


def test_window_too_wide():
    events = [_line(10, "Tag", "step_a", 1), _line(100, "Tag", "step_b", 2)]
    p = _partial(events, {"must_match": [A, B]})
    assert p["kind"] == "window" and p["width_sec"] == 90.0


def test_slots_kept_apart():
    events = [_line(10, "Tag", "step_a", 1, phone=0), _line(11, "Tag", "step_b", 2, phone=1)]
    p = _partial(events, {"must_match": [A, B, C]})
    assert p is None     # 슬롯별 1/3 — 다른 슬롯 줄을 합쳐 2/3으로 세지 않는다


def _doc(events):
    return {"masked": True, "events": events,
            "coverage": {"first_ts": _ts(0), "last_ts": _ts(600)},
            "input": {"window": {"start": _ts(0), "end": _ts(600)}}}


def _match(events, regress=False):
    db = issuedb.load(SAMPLE)
    return match_signatures.match(_doc(events), db, compiled_cache.compile_signatures(db), regress=regress, top=3)


def test_match_cause_unconfirmed_partial_and_absence_basis():
    events = [_ev(10, "data_evaluation_rejected", 7, reasons="DATA_DISABLED")]
    out = _match(events)
    top = out["candidates"][0]
    assert top["type"] == "DATA-001" and top["C"] == 0
    item = next(p for p in out["partial"] if p["cause"] == "DATA-001-01")
    assert item["kind"] == "missing" and item["matched"] == "1/2"
    assert [m["id"] for m in item["missing"]] == ["setting-off"]
    assert item["hits"][0]["line_ref"] == {"file_index": 1, "line_no": 7}
    assert out["absence_basis"]["signature"] == top["signature"]
    assert len(json.dumps(out["partial"], ensure_ascii=False)) < 4000


def test_regress_mode_computes_nothing():
    events = [_ev(10, "data_evaluation_rejected", 7, reasons="DATA_DISABLED")]
    out = _match(events, regress=True)
    assert "partial" not in out and "absence_basis" not in out


def test_cause_confirmed_has_no_partial():
    events = [_ev(5, "data_setting_changed", 3, enabled="false"),
              _ev(10, "data_evaluation_rejected", 7, reasons="DATA_DISABLED")]
    out = _match(events)
    assert out["candidates"][0]["C"] == 1 and "partial" not in out


# -- report.md 줄·analysis.json fit (triagelib/report.py) ----------------------------------------------------

from triagelib.report import ReportMixin, dumps, fit  # noqa: E402


def _report_input(code_status="reworded", log_refs=("f1:L42",), skipped=False):
    item = {"kind": "missing", "type": "DATA-002", "cause": "DATA-002-01", "signature": "DATA-002-01/sig1",
            "matched": "2/3", "missing": ["must_match 'DcTracker.*onDataSetupComplete'"], "at": ["f1:L120", "f1:L131"]}
    extra = {"hits": ["a (f1:L120)", "b (f1:L131)"], "missing": ["c `must_match 'DcTracker.*onDataSetupComplete'`"],
             "order": None, "width_sec": None,
             "code": [] if skipped else [{"id": "c", "status": code_status, "refs": ["aosp:fw/DataNetwork.java:1234"],
                                          "log_refs": list(log_refs), "scope": {"code_refs": "봄", "root": "건너뜀(상한)"}}]}
    return {"partial": [item], "code": {"skipped": skipped},
            "_partial": {"partial_report": [extra], "absence_basis": None, "partial_unjudged": False}}


def test_report_lines_reworded_with_log_refs():
    lines = ReportMixin.partial_lines(None, _report_input(), [])
    text = "\n".join(lines)
    assert lines[0] == "- 부분 일치 (판정·점수 아님, S/C 불변):"
    assert "DATA-002 > DATA-002-01/sig1 2/3 [missing] — 맞음 a (f1:L120), b (f1:L131) / 없음 c" in text
    assert "    - 코드 대조 c: 문구 다름 aosp:fw/DataNetwork.java:1234" in text
    assert ("규칙 제안 (부분 일치): [이슈 DB] update-signature DATA-002-01 — 근거: 부분 일치 2/3·없는 줄 c·"
            "새 문구 로그 f1:L42") in text
    assert len(text.encode("utf-8")) <= 1200


def test_report_lines_memo_not_found_same():
    text = "\n".join(ReportMixin.partial_lines(None, _report_input(log_refs=()), []))
    assert "pr_notes 메모: 문구 다름 aosp:fw/DataNetwork.java:1234 — 새 빌드 로그로 재확인" in text
    assert "규칙 제안" not in text
    text = "\n".join(ReportMixin.partial_lines(None, _report_input(code_status="not-found"), []))
    assert "못 찾음(범위: code_refs+required_dirs, ③ 건너뜀(상한))" in text and "규칙 제안 (부분 일치)" in text
    text = "\n".join(ReportMixin.partial_lines(None, _report_input(code_status="same"), []))
    assert "같음 aosp:fw/DataNetwork.java:1234" in text and "규칙 제안" not in text


def test_report_lines_none_and_code_skipped():
    assert ReportMixin.partial_lines(None, {"partial": None, "code": {}}, []) == []
    r = {"partial": [], "code": {"skipped": True}, "_partial": {"partial_unjudged": True}}
    assert ReportMixin.partial_lines(None, r, []) == ["- 부분 일치: 없음 (판정 불가 유형 제외)"]
    text = "\n".join(ReportMixin.partial_lines(None, _report_input(skipped=True), []))
    assert "코드 대조: 코드 미확인" in text.splitlines()[0]


def test_fit_trims_partial_before_top_evidence():
    ev = [{"ts": _ts(k), "tag": "T", "msg": "x" * 140} for k in range(20)]
    part = {"kind": "missing", "type": "T-0001", "cause": "T-0001-01", "signature": "T-0001-01/sig-long-name",
            "matched": "2/3", "missing": ["must_match '" + "y" * 47 + "'"] * 3, "at": ["f1:L100001"] * 3,
            "code": ["c:not-found", "d:reworded:aosp:frameworks/opt/telephony/src/X.java:1234", "e:limit"]}
    worst = len(dumps([part] * 3).encode("utf-8"))
    result = {"status": "ok", "candidates": [{"type": "T", "evidence": list(ev)}], "partial": [part] * 3,
              "files": {"report": "r"}, "warnings": []}
    out = fit(result)
    assert len(out.get("partial") or []) <= 1 and len(out["candidates"][0]["evidence"]) == 20
