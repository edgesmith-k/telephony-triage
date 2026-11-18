#!/usr/bin/env python3
"""자격 검사(단계 5-1, `common/eligibility.py`·`match_signatures.occurrences`): 규칙별 단위 시험 + 합성 6건(Y10) + 기준 줄 묶기.

규칙 동작 확인이다(정확도 수치 아님). Y10 로그와 기대는 생성기(`tests/helpers/make_accuracy_fixtures.py`)가 만든
`tests/fixtures/accuracy/y10/`이고, 시드 DB로 `parse_logcat.py parse --full` → (기준 줄이면 `ipc --find`) → `match_signatures.py
--reference`를 그대로 돈다(triage.py가 하는 순서).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import make_accuracy_fixtures as maf  # noqa: E402
from common import eligibility as el  # noqa: E402
from common import lookat  # noqa: E402
from runner import plugin_root, run_json, tmp  # noqa: E402

T = datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)
KST = timezone(timedelta(hours=9))


def ev(typ, sec, causes=(), line=(0, 1), phone=0, after=(), **kw) -> dict:
    """사건 하나(매처 `occurrences` 모양). causes = 붙은 원인(순위 순)."""
    return {"type": typ, "at": T + timedelta(seconds=sec), "lines": {line}, "phone": phone, "raw": kw.pop("raw", []),
            "causes": [(i, c, 0.1) for i, c in enumerate(causes)], "after": list(after), "absence_unverified": [],
            "absence": False, "absence_bad": False, "unjudged": False, "gap_s": 0.1 if causes else None,
            "cause_lines": set(), "cond_lines": set(), **kw}


def point(ln, sec, **extra) -> dict:
    return {"kind": "line", "source": "look_at", "places": 1,
            "lines": [{"line_ref": {"file_index": 0, "line_no": ln}, "ts": (T + timedelta(seconds=sec)).isoformat(), "phone": 0,
                       **extra}]}


def rng(source, start, fail, places=1) -> dict:
    iso = lambda s: None if s is None else (T + timedelta(seconds=s)).isoformat()  # noqa: E731
    return {"kind": "range", "source": source, "places": places, "start": iso(start), "fail": iso(fail)}


def outcome(d: dict) -> tuple:
    return d["state"], d["reason"], d["cause"] if d["state"] == "accepted" else d["why"]


EVENTS = [ev(None, 0.62, line=(0, 5)), ev("NETWORK-001", 120, ["N3"], line=(0, 16)),
          ev("DATA-003", 200, ["D1"], line=(0, 30)), ev("DATA-003", 260, ["D2"], line=(0, 40)),
          ev("NETWORK-001", 300, [], line=(0, 50), after=["N3"])]


# -- 기준 종류 --------------------------------------------------------------------------------------------------

def test_same_line_point_adopts_attached_cause_and_typeless_line_is_symptom_not_found():
    assert outcome(el.decide(EVENTS, [point(16, 120)])) == ("accepted", "anchored_top", "N3")
    # 같은 줄이 유형 없는 실패(XM 모양: 2분 뒤 비행기 모드를 채택하지 않는다)
    assert outcome(el.decide(EVENTS, [point(5, 0.62)])) == ("held", "symptom_not_found", "same_line_typeless")


def test_same_line_counts_condition_lines_in_window_and_same_ril_request():
    """§8-1: 근거 줄이 아니어도 그 충족 구간에서 조건에 맞는 줄이면 같은 줄. 같은 RIL 요청(pid·슬롯·serial + 짝)도 같은 사건."""
    e = ev("NETWORK-001", 120, ["N8"], line=(0, 16), cond_lines={(0, 14)})
    assert outcome(el.decide([e], [point(14, 119)])) == ("accepted", "anchored_top", "N8")
    raw = {"ril": {"serial": 410, "paired_ts": "2026-11-14T01:01:59+00:00"}, "pid": 2101, "phone_id": 0,
           "ts": "2026-11-14T01:02:00+00:00"}
    e = ev("DATA-003", 120, ["D1"], line=(0, 16), raw=[raw])
    ref = point(9, 119, ril={"serial": 410, "pid": 2101, "paired_ts": "2026-11-14T01:02:00+00:00"})
    ref["lines"][0]["ts"] = "2026-11-14T01:01:59+00:00"
    assert outcome(el.decide([e], [ref])) == ("accepted", "anchored_top", "D1")
    hidden = ev("DATA-003", 120, ["D1"], line=(0, 16), raw=[{**raw, "ril": {**raw["ril"], "serial": "<CRED#1>"}}])
    assert outcome(el.decide([hidden], [ref])) == ("held", "ineligible", "near_without_symptom")   # 가린 serial은 다른 요청


def test_cp_point_links_two_seconds_after_response_same_slot():
    ipc = lambda sec, slot=None: point(4, sec, ipc={"dir": "rsp", "name": "VIPC_SETUP_DATA", "token": 222}, phone=slot)  # noqa: E731
    assert outcome(el.decide(EVENTS, [ipc(199)])) == ("accepted", "anchored_top", "D1")
    assert outcome(el.decide(EVENTS, [ipc(0.5)])) == ("held", "symptom_not_found", "typeless_failure_within_link")
    assert outcome(el.decide(EVENTS, [ipc(10)])) == ("held", "ineligible", "no_event_at_reference")
    assert outcome(el.decide(EVENTS, [ipc(197)])) == ("held", "ineligible", "no_event_at_reference")   # 3초 뒤는 안 붙는다
    other = [ev("DATA-003", 200, ["D1"], line=(0, 30), phone=1)]
    assert outcome(el.decide(other, [ipc(199, slot=0)])) == ("held", "ineligible", "no_event_at_reference")   # 다른 슬롯


def test_near_line_is_held_without_problem_types():
    """기준 줄이 실패 사건이 아니면 근처 — problem.json 없는 5-1은 붙이지 않는다."""
    assert outcome(el.decide(EVENTS, [point(99, 150)])) == ("held", "ineligible", "near_without_symptom")


def test_range_kinds():
    assert outcome(el.decide(EVENTS, [rng("log_marker", 100, 130)])) == ("accepted", "anchored_top", "N3")
    assert outcome(el.decide(EVENTS, [rng("log_marker", None, 250)])) == ("accepted", "anchored_top", "D1")   # START 없음: FAIL−120초
    assert outcome(el.decide(EVENTS, [rng("log_marker", 150, 270)])) == ("held", "ambiguous", "multiple_events")
    assert outcome(el.decide(EVENTS, [rng("log_marker", 400, 500)])) == ("held", "symptom_not_found", "no_event_in_range")
    assert outcome(el.decide(EVENTS, [rng("log_marker", 100, None)])) == ("held", "ineligible", "range_end_unknown")  # START만
    assert outcome(el.decide(EVENTS, [rng("step_order", 100, 130)])) == ("held", "ineligible", "range_end_unknown")
    assert outcome(el.decide(EVENTS, [rng("steps_file", 100, 130)])) == ("held", "ineligible", "range_without_symptom")
    same = [ev("DATA-003", 200, ["D1"]), ev("DATA-003", 230, ["D1"], line=(0, 2))]
    assert outcome(el.decide(same, [rng("log_marker", 150, 270)])) == ("accepted", "anchored_top", "D1")


def test_multiple_places_slots_sources_are_ambiguous():
    assert outcome(el.decide(EVENTS, [{**point(16, 120), "places": 2}])) == ("held", "ambiguous", "locations")
    assert outcome(el.decide(EVENTS, [rng("log_marker", 100, 130, places=2)])) == ("held", "ambiguous", "locations")
    two = point(16, 120)
    two["lines"].append({**two["lines"][0], "phone": 1})
    assert outcome(el.decide(EVENTS, [two])) == ("held", "ambiguous", "slots")
    assert outcome(el.decide(EVENTS, [point(16, 120), point(30, 200)])) == ("held", "ambiguous", "sources")


def test_rule2_cause_after_event_absence_and_unjudged():
    assert outcome(el.decide(EVENTS, [point(50, 300)])) == ("held", "cause_unconfirmed", "cause_after_event")
    assert outcome(el.decide([ev("X", 1)], [point(1, 1)])) == ("held", "cause_unconfirmed", "no_cause_before_event")
    assert outcome(el.decide([ev("X", 1, absence_bad=True)], [point(1, 1)])) == ("held", "ineligible", "absence_unverified")
    assert outcome(el.decide([ev("X", 1, absence_unverified=["X-1"])], [point(1, 1)])) == \
        ("held", "ineligible", "absence_unverified")
    assert outcome(el.decide([ev("X", 1, unjudged=True)], [point(1, 1)])) == ("held", "cause_unjudged", "cause_unjudged")
    assert outcome(el.decide(EVENTS, [])) == ("held", "no_reference", None)


def test_merge_same_type_within_one_second():
    """§8-4: 같은 유형의 시그니처 둘이 한 실패를 2ms 차이로 따로 잡으면 한 사건."""
    out = el.merge([ev("DATA-003", 10, ["D1"]), ev("DATA-003", 10.002, ["D1"], line=(0, 2)), ev("DATA-003", 12, ["D1"])])
    assert len(out) == 2 and out[0]["lines"] == {(0, 1), (0, 2)}
    assert len(el.merge([ev("DATA-003", 10), ev("DATA-003", 10.5, phone=1)])) == 2     # 다른 슬롯은 따로


def test_summary_rows_put_attached_first_and_count_totals():
    d = el.decide(EVENTS, [point(30, 200)])
    s = el.summary(d, EVENTS)
    assert (s["checked"], s["total"], s["events_total"]) == (1, 5, 4)
    assert [(r["type"], r["ref"], r["result"]) for r in s["events"][:2]] == [("DATA-003", True, "adopted"),
                                                                              ("NETWORK-001", False, "observed")]
    assert s["events"][-1]["why"] == "cause_after_event" and s["events"][0]["line"] == "f0:L30"


# -- 기준 줄 묶기·시각(§8-5) -------------------------------------------------------------------------------------

def test_group_places_pairs_request_response_and_ril_serial():
    h = lambda ts, d, tok=222: {"ts": ts, "phone": 0, "ipc": {"dir": d, "name": "VIPC_SETUP_DATA", "token": tok}}  # noqa: E731
    assert len(lookat.group_places([h("t1", "req"), h("t2", "rsp")])) == 1
    assert len(lookat.group_places([h("t1", "req"), h("t2", "rsp"), h("t3", "req"), h("t4", "rsp")])) == 2
    r = lambda ts, paired: {"ts": ts, "phone": 0, "ril": {"serial": 7, "pid": 1, "paired_ts": paired}}  # noqa: E731
    assert len(lookat.group_places([r("t1", "t2"), r("t2", "t1")])) == 1
    assert len(lookat.group_places([r("t1", "t2"), r("t9", "t8")])) == 2
    assert lookat.stamp("11-14 10:02:00.620  2101  2141 D RILJ    : x") == "11-14 10:02:00.620"
    assert lookat.stamp("RILJ: x") is None


# -- 시드 DB로 실제 경로 ----------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def seed_db() -> Path:
    return maf.build_seed_db(tmp("tt-elig-db-") / "db", plugin_root())


def _common(db: Path) -> list:
    return ["--rules", db / "parser-rules", "--tz", "Asia/Seoul", "--year", "2026"]


def _find(db: Path, log: Path, text: str, stamp: str | None = None) -> dict:
    look = tmp("tt-elig-look-") / "look-at.json"
    look.write_text(json.dumps({"look_at": lookat.clean(text), "ref": None, **({"stamp": stamp} if stamp else {})}),
                    encoding="utf-8")
    return run_json("parse_logcat.py", ["ipc", log, "--find", look, *_common(db)])["find"]


def _eligibility(db: Path, log: Path, ref: dict | None, top: int = 3) -> dict:
    work = tmp("tt-elig-")
    events = run_json("parse_logcat.py", ["parse", log, "--full", "--mask", *_common(db)])
    (work / "events.json").write_text(json.dumps(events), encoding="utf-8")
    args = ["--db", db, "--events", work / "events.json", "--top", top]
    if ref is not None:
        (work / "reference.json").write_text(json.dumps(ref), encoding="utf-8")
        args += ["--reference", work / "reference.json"]
    return run_json("match_signatures.py", args)


Y10 = json.loads((maf.OUT / "y10" / "y10.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(Y10))
def test_y10_expected_exactly(seed_db, name):
    """합성 6건: 로그가 먼저 끝남 · 정상 복구 줄 · 같은 token 두 요청 · 구간 안 같은 원인 2번 · 다른 원인 2개(§8-2·§8-3) · 원인이 사건 뒤."""
    spec, log = Y10[name], maf.OUT / "y10" / f"{name}.log"
    if spec["ref"][0] == "text":
        found = _find(seed_db, log, spec["ref"][1])
        ref = {"kind": "line", "source": "look_at", "places": found["places"], "lines": found["place"]}
    else:
        base = datetime(2026, 11, 14, tzinfo=KST)
        ref = {"kind": "range", "source": "log_marker", "places": 1,
               "start": (base + timedelta(seconds=spec["ref"][1])).isoformat(),
               "fail": (base + timedelta(seconds=spec["ref"][2])).isoformat()}
    out = _eligibility(seed_db, log, ref)
    assert out["candidates"], name
    e = out["eligibility"]
    assert [e["state"], e["reason"], e["cause"] if e["state"] == "accepted" else e["why"]] == spec["expect"]


def test_pasted_stamp_picks_the_same_place(seed_db):
    """§8-5: 같은 token이 두 요청에 있어도 붙여 넣은 줄의 시각과 같은 곳이 하나면 그곳(SAMETOKEN 로그의 실패 응답 줄)."""
    log = maf.OUT / "y10" / "Y10-SAMETOKEN.log"
    line = next(x for x in log.read_text(encoding="utf-8").splitlines() if "token=0x0e5" in x and "Error(VIPC_E_DEMO" in x)
    assert _find(seed_db, log, "VIPC_SETUP_DATA (token=0x0e5)")["places"] == 2
    found = _find(seed_db, log, line, stamp=lookat.stamp(line))
    assert (found["places"], found["stamp"]) == (1, "same")
    assert [x["ipc"]["dir"] for x in found["place"]] == ["req", "rsp"]
    out = _eligibility(seed_db, log, {"kind": "line", "source": "look_at", "places": 1, "lines": found["place"]})
    assert (out["eligibility"]["state"], out["eligibility"]["cause"]) == ("accepted", "DATA-003-01")
    assert _find(seed_db, log, line, stamp="11-14 09:00:00.000")["places"] == 2       # 다른 시각이면 그대로 여러 곳


def test_adopted_cause_outside_top_is_appended(seed_db):
    """H18: 자르기 전 순위로 판정하고, 채택 원인이 --top 밖이면 후보 끝에 붙이고 omitted에서 뺀다(selected ∈ candidates)."""
    log = maf.OUT / "mmh.log"
    found = _find(seed_db, log, "Service MODEM has died.")
    ref = {"kind": "line", "source": "look_at", "places": found["places"], "lines": found["place"]}
    full = _eligibility(seed_db, log, ref, top=0)
    names = [c["cause"] for c in full["candidates"]]
    assert full["eligibility"]["cause"] == "NETWORK-001-08" and names.index("NETWORK-001-08") > 0, names
    cut = _eligibility(seed_db, log, ref, top=1)
    assert [c["cause"] for c in cut["candidates"]] == [names[0], "NETWORK-001-08"]
    assert cut["omitted"]["candidates"] == len(names) - 2


def test_selected_not_top_shows_rank_and_keeps_invariant():
    """selected ∈ candidates(1위가 아니어도 됨): 판단 줄에 "규칙 일치 n위", 불변식 검사는 후보 중 하나면 통과."""
    from triagelib import report
    cands = [{"category": "network", "type": "NETWORK-001", "cause": "NETWORK-001-03"},
             {"category": "network", "type": "NETWORK-001", "cause": "NETWORK-001-08"}]
    dec = {"state": "accepted", "reason": "anchored_top", "selected": cands[1],
           "location": {"state": "confirmed", "source": "look_at", "kind": "near"}}
    line = report.decision_line(dec, cands)
    assert line.endswith("(실패 지점: 담당자가 지정한 기준 줄·확인됨, 자격 검사 통과, 규칙 일치 2위)"), line
    assert "규칙 일치" not in report.decision_line({**dec, "selected": cands[0]}, cands)
    assert report._decision_mismatch({"decision": dec, "candidates": cands}) is None
    assert report._decision_mismatch({"decision": dec, "candidates": cands[:1]})
    held = {"state": "held", "reason": "ineligible", "selected": None, "location": dec["location"],
            "check": {"why": "near_without_symptom", "checked": 0, "total": 2}}
    assert report.decision_line(held, cands).startswith(
        "- 판단: 원인 보류 — 실패 지점과 규칙 일치를 이을 수 없음(지정한 줄이 실패 줄이 아님 — 근처 실패를 고르려면")
