#!/usr/bin/env python3
"""자격 검사(단계 5-1·5-2, `common/eligibility.py`·`match_signatures.occurrences`): 규칙별 단위 시험 + 합성 6건(Y10) + 기준 줄 묶기
+ 문제 파악 입력(problem.json 유형·단서, 입력 해시·stale·설정 스위치 — `triage.py run` 오프라인).

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


def test_condition_line_fallback_adopts_but_location_stays_found():
    """리뷰 P2-3: 기준 줄이 창 안 조건 줄로만 맞으면 채택(why same_line)은 하되 실패 지점은 found·kind 그대로(포털이 확실한
    일치로 보고 본 분석을 건너뛰지 않게). 근거 줄로 맞으면 confirmed/point."""
    from triagelib import driver
    cands = [{"category": "network", "type": "NETWORK-001", "cause": "N8"}]
    text = {"state": "found", "source": "look_at", "kind": "near"}
    e = ev("NETWORK-001", 120, ["N8"], line=(0, 16), cond_lines={(0, 14)})
    by_cond = el.summary(el.decide([e], [point(14, 119)]), [e])
    assert (by_cond["state"], by_cond["why"], by_cond.get("cond_line")) == ("accepted", "same_line", True)
    assert driver._decision(cands, {"location": text}, by_cond)["location"] == text
    by_line = el.summary(el.decide([e], [point(16, 120)]), [e])
    assert (by_line["why"], "cond_line" in by_line) == ("same_line", False)
    assert driver._decision(cands, {"location": text}, by_line)["location"] == {**text, "state": "confirmed", "kind": "point"}


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
    # 증상의 안 나옴을 확인 못 한 사건은 원인이 붙어 있어도 먼저 보류(리뷰 P1-2)
    assert outcome(el.decide([ev("X", 1, ["X-1"], absence_bad=True)], [point(1, 1)])) ==         ("held", "ineligible", "absence_unverified")
    assert outcome(el.decide(EVENTS, [])) == ("held", "no_reference", None)


def test_merge_same_type_within_one_second():
    """§8-4: 같은 유형의 시그니처 둘이 한 실패를 2ms 차이로 따로 잡으면 한 사건."""
    out = el.merge([ev("DATA-003", 10, ["D1"]), ev("DATA-003", 10.002, ["D1"], line=(0, 2)), ev("DATA-003", 12, ["D1"])])
    assert len(out) == 2 and out[0]["lines"] == {(0, 1), (0, 2)}
    assert len(el.merge([ev("DATA-003", 10), ev("DATA-003", 10.5, phone=1)])) == 2     # 다른 슬롯은 따로
    assert len(el.merge([ev("DATA-003", 10, phone=None), ev("DATA-003", 10.5, phone=1)])) == 2   # 리뷰 P0: 모름은 모름끼리만
    assert len(el.merge([ev("DATA-003", 10, phone=None), ev("DATA-003", 10.5, phone=None)])) == 1
    # 첫 사건 시각부터 1초 — 0.8초 간격 사슬은 셋째에서 끊긴다, 합친 사건의 gap_s는 합친 시각(가장 늦은 것) 기준(리뷰 P2-4)
    out = el.merge([ev("DATA-003", 10, ["D1"]), ev("DATA-003", 10.8, line=(0, 2)), ev("DATA-003", 11.6, line=(0, 3))])
    assert [len(e["lines"]) for e in out] == [2, 1] and out[0]["gap_s"] == pytest.approx(0.9)


def test_merge_of_different_causes_is_held_not_pooled():
    """리뷰 P0: 0.6초 안 같은 유형 두 실패(IMS PDN·인터넷 PDN)의 원인이 다르면 합쳐도 원인을 섞어 고르지 않는다 — 기준이 붙으면 보류."""
    ims, apn = ev("DATA-003", 100.0, ["D-IMS"], line=(0, 10)), ev("DATA-003", 100.6, ["D-APN"], line=(0, 20))
    apn["causes"] = [(1, "D-APN", 0.1)]                   # 순위가 낮은 원인이라도 옆 실패의 1위 원인을 채택하면 안 된다
    m = el.merge([ims, apn])
    assert len(m) == 1 and m[0].get("mixed")
    assert outcome(el.decide(m, [point(20, 100.6)])) == ("held", "ambiguous", "multiple_events")
    # 한쪽만 원인이 붙어도 섞지 않는다(DNC 평가 두 줄 0.5초: 인터넷 DATA_DISABLED에 붙은 원인을 IMS 줄 기준으로 채택하던 것)
    half = el.merge([ev("DATA-001", 10, ["D1"]), ev("DATA-001", 10.5, [], line=(0, 2))])
    assert half[0].get("mixed") and outcome(el.decide(half, [point(2, 10.5)])) == ("held", "ambiguous", "multiple_events")
    same = el.merge([ev("DATA-003", 10, ["D1"]), ev("DATA-003", 10.002, ["D1", "D2"], line=(0, 2))])
    assert not same[0].get("mixed") and outcome(el.decide(same, [point(2, 10.002)])) == ("accepted", "anchored_top", "D1")


def test_same_line_shared_by_events_with_different_causes_is_held():
    """리뷰 P2-1: 한 기준 줄이 유형 사건 둘의 근거이고 1순위 원인이 다르면 첫 사건을 조용히 고르지 않는다."""
    a = ev("DATA-003", 100, ["D1"], line=(0, 10))
    a["lines"] |= {(0, 12)}
    b = ev("NETWORK-001", 101, ["N3"], line=(0, 12))
    assert outcome(el.decide([a, b], [point(12, 101)])) == ("held", "ambiguous", "multiple_events")
    c = ev("NETWORK-001", 101, ["D1"], line=(0, 12))
    assert outcome(el.decide([a, c], [point(12, 101)])) == ("accepted", "anchored_top", "D1")    # 같은 원인이면 채택


def test_cp_point_success_response_is_not_a_failure():
    """리뷰 P1-1: 기준 IPC 응답이 성공 값이면 기준 자체가 실패가 아니다 — 2초 안 다른 실패를 붙이지 않는다."""
    ok = point(4, 199, ipc={"dir": "rsp", "name": "VIPC_SETUP_DATA", "token": 222, "ok": True})
    assert outcome(el.decide(EVENTS, [ok])) == ("held", "ineligible", "no_event_at_reference")


def test_same_line_prefers_evidence_over_window_lines():
    """리뷰 P0-1: 앞 사건 창(cond_lines)이 뒤 사건의 증상 줄을 덮어도, 그 줄이 근거인 뒤 사건을 고른다."""
    early = ev("CALL-002", 10, ["C2"], line=(0, 3), cond_lines={(0, 9)})
    late = ev("CALL-002", 35, ["C3"], line=(0, 9))
    assert outcome(el.decide([early, late], [point(9, 35)])) == ("accepted", "anchored_top", "C3")
    assert outcome(el.decide([early], [point(9, 35)])) == ("accepted", "anchored_top", "C2")   # 근거 사건이 없을 때만 창 줄


def test_summary_rows_put_attached_first_and_count_totals():
    d = el.decide(EVENTS, [point(30, 200)])
    s = el.summary(d, EVENTS)
    assert (s["checked"], s["total"], s["events_total"]) == (1, 5, 4)
    assert [(r["type"], r["ref"], r["result"]) for r in s["events"][:2]] == [("DATA-003", True, "adopted"),
                                                                              ("NETWORK-001", False, "observed")]
    assert s["events"][-1]["why"] == "cause_after_event" and s["events"][0]["line"] == "f0:L30"


# -- 기준 줄 묶기·시각(§8-5) -------------------------------------------------------------------------------------

def test_group_places_pairs_request_response_and_ril_serial():
    h = lambda s, d, tok=222: {"ts": f"2026-11-14T10:00:{s:06.3f}+09:00", "phone": 0,  # noqa: E731
                               "ipc": {"dir": d, "name": "VIPC_SETUP_DATA", "token": tok}}
    assert len(lookat.group_places([h(1, "req"), h(1.5, "rsp")])) == 1
    assert len(lookat.group_places([h(1, "req"), h(1.5, "rsp"), h(3, "req"), h(3.5, "rsp")])) == 2
    assert len(lookat.group_places([h(1, "req"), h(4, "rsp")])) == 2              # 2초 넘은 RSP는 다른 곳(token 재사용)
    assert len(lookat.group_places([h(1, "req"), h(4, "rsp")], link_ms=5000)) == 1    # 사내 조정 값
    z = lambda s, d: {**h(s, d), "ts": f"2026-11-14T01:00:{s:06.3f}Z"}  # noqa: E731  (logtime.format_ts 꼴, Python 3.10도)
    assert [len(p) for p in lookat.group_places([z(1, "req"), z(1.5, "rsp"), z(5, "rsp")])] == [2, 1]
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


def test_success_response_reference_is_not_adopted(seed_db):
    """리뷰 P1-1 회귀(실제 경로): 성공 응답(VIPC_E_OK) 줄을 기준으로 주면 기준 자체가 실패가 아니다 — 2초 안 다른 요청의 실패
    (10:02:00.6 SETUP 실패, DATA-003-01)를 붙이지 않는다."""
    src = (maf.OUT / "y10" / "Y10-SAMETOKEN.log").read_text(encoding="utf-8").splitlines()
    ok = "11-14 10:02:00.020   900   910 D RIL     : [RX] VIPC_SETUP_DATA, RSP, token=0x0f0, len=8, Error(VIPC_E_OK)"
    k = next(i for i, x in enumerate(src) if x.startswith("11-14 10:02:00.500"))
    log = tmp("tt-elig-ok-") / "ok.log"
    log.write_text("".join(x + "\n" for x in src[:k] + [ok] + src[k:]), encoding="utf-8", newline="\n")
    found = _find(seed_db, log, ok, stamp=lookat.stamp(ok))
    assert found["places"] == 1 and found["place"][0]["ipc"].get("ok") is True, found
    e = _eligibility(seed_db, log, {"kind": "line", "source": "look_at", "places": 1, "lines": found["place"]})["eligibility"]
    assert (e["state"], e["reason"], e["why"]) == ("held", "ineligible", "no_event_at_reference"), e


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


REG = REPO / "tests" / "fixtures" / "eligibility"


def _line_ref(ln: int) -> dict:
    return {"kind": "line", "source": "look_at", "places": 1, "lines": [
        {"line_ref": {"file_index": 0, "line_no": ln}, "ts": "2026-11-14T10:00:35.101+09:00", "phone": None}]}


def test_reference_line_picks_its_own_event_not_earlier_window(seed_db):
    """리뷰 P0-1 회귀: 앞 끊김(31초)의 60초 창이 뒤 끊김 줄(9번, 35.101초)을 덮어도 9번 줄 기준은 뒤 사건의 원인(CALL-002-02)."""
    for top in (3, 1):
        out = _eligibility(seed_db, REG / "wrong-event.log", _line_ref(9), top=top)
        e = out["eligibility"]
        assert (e["state"], e["cause"]) == ("accepted", "CALL-002-02"), (top, e)
        assert "CALL-002-02" in [c["cause"] for c in out["candidates"]]


@pytest.mark.parametrize("ln", [6, 7, 8])
def test_cause_only_in_extended_end_does_not_crash(seed_db, ln):
    """리뷰 P0-2 회귀: 분석 끝을 늘린 구간에서만 충족한(후보 순위에 없는) 원인은 사건에 붙이지 않는다 — 매처가 끝나고(--top 0 포함),
    채택이면 그 원인은 후보에 있다."""
    for top in (3, 0):
        out = _eligibility(seed_db, REG / "crash-stopiteration.log", _line_ref(ln), top=top)
        e = out["eligibility"]
        assert e["state"] == "held" or e["cause"] in [c["cause"] for c in out["candidates"]], (ln, top, e)


def test_reference_on_merged_neighbour_failure_is_held(seed_db):
    """리뷰 P0 회귀(실제 경로): 0.5초 안 DNC 평가 거부 두 줄(인터넷 DATA_DISABLED, IMS NO_SUITABLE_DATA_PROFILE)을 같은 유형이라
    합쳐도, IMS 줄 기준에 인터넷 줄의 원인(DATA-001-01)을 채택하지 않는다 — 두 실패 중 어느 것인지 모르므로 보류."""
    log = tmp("tt-elig-mix-") / "mix.log"
    log.write_text("".join(x + "\n" for x in (REG / "merge-diffcause.log").read_text(encoding="utf-8").splitlines()
                           if " DPM-0 " not in x), encoding="utf-8", newline="\n")     # IMS 실패의 원인 줄(DPM)이 없는 모양
    line = log.read_text(encoding="utf-8").splitlines()[-1]
    for path in (log, REG / "merge-diffcause.log"):
        found = _find(seed_db, path, line, stamp=lookat.stamp(line))
        e = _eligibility(seed_db, path, {"kind": "line", "source": "look_at", "places": found["places"],
                                         "lines": found["place"]})["eligibility"]
        assert (e["state"], e["reason"], e["why"]) == ("held", "ambiguous", "multiple_events"), (path.name, e)


def test_absence_end_is_parse_window_end(seed_db):
    """리뷰 P1-1: 부분 파싱(--full 아님)이면 안 나옴 확인 끝은 min(로그 끝, 이번 파싱 창 끝) — 창 밖은 확인한 것으로 세지 않는다.
    통화 끊김(10:05:19.7) 뒤 로그는 10:07까지 이어지지만 창이 10:05:21에 끝나면 원인의 '없어야 할 줄'을 확인하지 못했다."""
    work = tmp("tt-elig-win-")
    lines = maf.segment(maf.DROP, maf.minute(5))
    log = work / "drop.log"
    log.write_text("".join(x + "\n" for x in lines + ["11-14 10:07:00.000" + lines[-1][18:]]), encoding="utf-8", newline="\n")
    found = _find(seed_db, log, "Call: setState ACTIVE -> DISCONNECTED")
    (work / "ref.json").write_text(json.dumps({"kind": "line", "source": "look_at", "places": found["places"],
                                               "lines": found["place"]}), encoding="utf-8")
    got = {}
    for name, extra in (("full", ["--full"]), ("part", ["--between", "2026-11-14T10:04:00+09:00", "2026-11-14T10:05:21+09:00"])):
        events = run_json("parse_logcat.py", ["parse", log, *extra, "--mask", *_common(seed_db)])
        (work / "events.json").write_text(json.dumps(events), encoding="utf-8")
        e = run_json("match_signatures.py", ["--db", seed_db, "--events", work / "events.json", "--top", 3,
                                             "--reference", work / "ref.json"])["eligibility"]
        got[name] = (e["state"], e["reason"], e["cause"] or e["why"])
    assert got == {"full": ("accepted", "anchored_top", "CALL-002-03"), "part": ("held", "ineligible", "absence_unverified")}


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


def test_selected_not_top_drives_deep_fit_hold_and_post():
    """리뷰 P1-3·P2-1: 채택 원인이 1위가 아니면 심층 분석 입력(맨 앞·top_candidates)·적합성 보류·Jira 확정 문구·4KB 압축이 그 원인 기준."""
    import issue_post
    from triagelib import modulecmd, output, report
    ev8 = [{"ts": f"t{i}", "tag": "T", "msg": "m" * 300} for i in range(8)]
    cands = [{"category": "network", "type": "NETWORK-001", "cause": "NETWORK-001-03", "C": 1, "score": 0.9,
              "confidence": "high", "evidence": list(ev8)},
             {"category": "data", "type": "DATA-003", "cause": "DATA-003-01", "C": 1, "score": 0.5,
              "confidence": "medium", "evidence": list(ev8)}]
    dec = {"state": "accepted", "reason": "anchored_top", "selected": {k: cands[1][k] for k in ("category", "type", "cause")}}
    lead = report.lead_first(dec, cands)
    assert [c["cause"] for c in lead] == ["DATA-003-01", "NETWORK-001-03"]
    assert modulecmd._top3(lead)[0]["cause"] == "DATA-003-01"
    assert report.lead_first({"state": "held"}, cands) == cands
    analysis = {"candidates": cands, "decision": dec, "explore": {"reason": "fit_check"}}
    assert output._fit_hold(analysis, {"hyps": []}) == "DATA-003-01"
    post = issue_post.classify(analysis, None)
    assert post["cand"]["cause"] == "DATA-003-01" and post["confirm"].startswith("자동 분석 채택 후보(규칙 일치 2위)")
    big = {"candidates": [dict(c, evidence=list(ev8)) for c in cands], "decision": dec, "files": {"report": "r"}}
    kept = {c["cause"]: len(c["evidence"]) for c in report.fit(big)["candidates"]}
    assert kept["DATA-003-01"] > kept["NETWORK-001-03"], kept      # 채택 원인 근거를 먼저 지킨다


def test_decision_accepted_cause_missing_from_candidates_is_held():
    """리뷰 P0-2: 자격 검사가 채택했는데 그 원인이 후보에 없으면 보류(ineligible/cause_not_in_candidates) — why와 사유가 맞는다."""
    from common import issuepost
    from triagelib import driver
    cands = [{"category": "network", "type": "NETWORK-001", "cause": "NETWORK-001-03"}]
    elig = {"state": "accepted", "reason": "anchored_top", "why": "same_line", "cause": "DATA-003-01", "checked": 1, "total": 1,
            "events": [], "events_total": 1}
    d = driver._decision(cands, {"location": {"state": "confirmed", "source": "look_at", "kind": "point"}}, elig)
    assert (d["state"], d["reason"], d["selected"], d["check"]["why"]) == ("held", "ineligible", None, "cause_not_in_candidates")
    assert "cause_not_in_candidates" in issuepost.HELD_WHY


# -- 문제 파악 입력(단계 5-2: problem.json 유형·단서) -------------------------------------------------------------

D3 = {"types": ["DATA-003"], "not_in_db": False}


def clue(ref: dict, **kw) -> dict:
    return {**ref, "source": "comment", **kw}


def test_problem_types_make_near_and_steps_file_range_eligible():
    """§2.2: 근처·TC 파일 시각 구간은 문제 파악 유형이 있어야 붙는다 — 허용 유형만, 같은 줄 점은 유형으로 거르지 않는다."""
    assert outcome(el.decide(EVENTS, [point(99, 150)], problem=D3)) == ("accepted", "anchored_top", "D1")
    assert outcome(el.decide(EVENTS, [point(99, 150)], problem={"types": ["CALL-001"], "not_in_db": False})) == \
        ("held", "symptom_not_found", "no_allowed_event_near")
    assert outcome(el.decide(EVENTS, [point(99, 600)], problem=D3)) == ("held", "symptom_not_found", "no_allowed_event_near")
    assert outcome(el.decide(EVENTS, [rng("steps_file", 150, 210)], problem=D3)) == ("accepted", "anchored_top", "D1")
    # 구간 안 NETWORK-001(N3)은 허용 유형이 아니라 빠진다 — 거르지 않으면 원인이 둘(multiple_events)
    assert outcome(el.decide(EVENTS, [rng("log_marker", 100, 210)])) == ("held", "ambiguous", "multiple_events")
    assert outcome(el.decide(EVENTS, [rng("log_marker", 100, 210)], problem=D3)) == ("accepted", "anchored_top", "D1")
    assert outcome(el.decide(EVENTS, [point(16, 120)], problem=D3)) == ("accepted", "anchored_top", "N3")   # 같은 줄
    # 유형이 비면(DB에 없는 유형만이라 매처가 비운 경우) 5-1과 같다
    assert outcome(el.decide(EVENTS, [point(99, 150)], problem={"types": [], "not_in_db": False})) == \
        ("held", "ineligible", "near_without_symptom")


def test_problem_not_in_db_holds_and_no_reference_stays():
    """`not_in_db`면 기준이 있어도 다른 사건의 원인으로 대신하지 않는다. 기준이 전혀 없으면 유형이 있어도 no_reference."""
    nid = {"types": [], "not_in_db": True}
    assert outcome(el.decide(EVENTS, [point(16, 120)], problem=nid)) == ("held", "symptom_not_found", "not_in_db")
    assert outcome(el.decide(EVENTS, [], problem=D3)) == ("held", "no_reference", None)


def test_clue_ipc_point_and_comment_adopt_switch():
    """단서 ipc = CP 점(2초 안 허용 유형 첫 사건). 코멘트 단서만이어도 채택한다(comment_adopt 기본 참, 사용자 결정 Y1 허용).
    끄면 붙은 사건을 싣고 보류."""
    ipc = clue(point(4, 199, ipc={"dir": "rsp", "name": "VIPC_SETUP_DATA", "token": 0xE3}, phone=None))
    held = el.decide(EVENTS, [ipc], problem=D3, comment_adopt=False)
    assert outcome(held) == ("held", "ineligible", "comment_unconfirmed")
    assert [e["type"] for e in held["events"]] == ["DATA-003"]          # 붙은 사건은 싣는다
    assert outcome(el.decide(EVENTS, [ipc], problem=D3)) == ("accepted", "anchored_top", "D1")
    assert outcome(el.decide(EVENTS, [ipc], problem={"types": ["CALL-001"], "not_in_db": False}, comment_adopt=True)) == \
        ("held", "symptom_not_found", "typeless_failure_within_link")     # 2초 안 사건이 허용 유형이 아님


def test_clue_keeps_real_hold_reason_whether_comment_adopt_or_not():
    """리뷰 P1-1: 단서 사건의 원인이 실패 뒤에만 있으면 comment_adopt와 무관하게 그 사유(comment_unconfirmed로 가리지 않는다)."""
    for adopt in (False, True):
        d = el.decide(EVENTS, [clue(point(50, 300), clue="log_line", how="text", places=1)], comment_adopt=adopt)
        assert outcome(d) == ("held", "cause_unconfirmed", "cause_after_event")
        assert d["via"] == {"comment": None, "clue": "log_line", "how": "text", "places": 1}


def test_clue_ipc_name_multiple_places_and_log_line_near():
    """ipc_name 본문 일치가 여러 곳이면 보류(locations). log_line은 같은 줄이면 점, 아니면 유형이 있을 때 근처."""
    assert outcome(el.decide(EVENTS, [clue(point(4, 199), places=3)], problem=D3, comment_adopt=True)) == \
        ("held", "ambiguous", "locations")
    assert outcome(el.decide(EVENTS, [clue(point(99, 150))], problem=D3, comment_adopt=True)) == ("accepted", "anchored_top", "D1")
    assert outcome(el.decide(EVENTS, [clue(point(99, 150))], comment_adopt=True)) == ("held", "ineligible", "near_without_symptom")
    assert outcome(el.decide(EVENTS, [clue(point(16, 120))], comment_adopt=True)) == ("accepted", "anchored_top", "N3")


def test_explicit_reference_wins_and_conflicting_clue_is_ambiguous():
    """명시 기준(look_at·마커)이 정한다. 단서가 다른 사건을 가리키면 ambiguous/sources, 같은 사건(구간 안 포함)이면 그대로."""
    assert outcome(el.decide(EVENTS, [point(16, 120), clue(point(30, 200))], problem=D3)) == ("held", "ambiguous", "sources")
    assert outcome(el.decide(EVENTS, [point(16, 120), clue(point(16, 120))])) == ("accepted", "anchored_top", "N3")
    assert outcome(el.decide(EVENTS, [rng("log_marker", 150, 210), clue(point(30, 200))])) == ("accepted", "anchored_top", "D1")
    # 명시 기준이 보류면 단서가 사건을 찾아도 대신하지 않는다
    assert outcome(el.decide(EVENTS, [point(5, 0.62), clue(point(30, 200))], comment_adopt=True)) == \
        ("held", "symptom_not_found", "same_line_typeless")
    # 명시 기준이 채택이고 단서가 여러 곳(보류)이면 명시 기준 그대로
    assert outcome(el.decide(EVENTS, [point(16, 120), clue(point(30, 200), places=2)])) == ("accepted", "anchored_top", "N3")


def test_reference_input_keeps_db_types_only():
    """매처가 문제 파악 유형 중 스냅샷 DB에 있는 것만 남긴다(값은 문자열 비교만). 기준 하나(5-1 모양)도 그대로 읽는다."""
    import match_signatures as ms

    class Db:
        types = [type("T", (), {"id": "DATA-003"})()]
    refs, problem, adopt = ms._reference_input({"refs": [point(16, 120), {"kind": "bad"}],
                                                "problem": {"types": ["DATA-003", "NOPE-9", 3], "not_in_db": False},
                                                "comment_adopt": True}, Db())
    assert (len(refs), problem, adopt) == (1, {"types": ["DATA-003"], "not_in_db": False}, True)
    assert ms._reference_input(point(16, 120), Db()) == ([point(16, 120)], None, True)
    # 리뷰 P2-2: 키가 없으면 참(eligibility.decide·설정 기본과 같게), 거짓은 False만
    assert ms._reference_input({"refs": []}, Db()) == ([], None, True)
    assert ms._reference_input({"refs": [], "comment_adopt": False}, Db()) == ([], None, False)


# triage.py run(오프라인)으로 problem.json 읽기: 같은 입력 해시일 때만, stale 단서 안 씀, 로그에 없는 단서는 버리고 기록, 설정 스위치
def _problem_run(db: Path, name: str, log: str, clues: list, sha: str | None = "same", look_at: str | None = None,
                 root: Path | None = None, **extra) -> tuple[dict, Path]:
    import hashlib
    out = tmp("tt-elig-prob-") / name
    out.mkdir(parents=True)
    meta = out.parent / f"{name}.meta.json"
    meta.write_text(json.dumps({"key": "CLUEPOS-1", "summary": "데이터 연결 실패"}), encoding="utf-8")
    doc = {"schema_version": 1, "key": "CLUEPOS-1", "origin": "정답 입력",
           "source_sha256": hashlib.sha256(meta.read_bytes()).hexdigest() if sha == "same" else sha,
           "symptom": {"text": "", "types": ["DATA-003"], "not_in_db": False}, "clues": clues, **extra}
    (out / "problem.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    args = ["run", "CLUEPOS-1", "--offline-db", db, "--out", out, "--logs", maf.OUT / log, "--issue-meta", meta,
            "--tz", "Asia/Seoul", "--year", "2026", *(["--look-at", look_at] if look_at else [])]
    return run_json("triage.py", args, root=root), out


IPC_CLUE = {"comment": 2, "kind": "ipc", "name": "VIPC_SETUP_DATA", "token": "0x0e3", "quote": "VIPC_SETUP_DATA (token=0x0e3)",
            "side": "cp", "stale": False}


def test_run_reads_problem_only_for_same_input_and_fresh_clues(seed_db):
    a, out = _problem_run(seed_db, "ok", "cluepos.log", [IPC_CLUE])
    d = a["decision"]
    assert (d["state"], d["selected"]["cause"], d["check"]["why"]) == ("accepted", "DATA-003-01", "cp_point")
    # 채택이어도 코멘트 단서 지점은 found(확정 아님) — "확실한 일치"(accepted + confirmed)가 되지 않는다
    assert d["location"] == {"state": "found", "source": "comment", "kind": "point"}
    bundle = json.loads((out / "reference.json").read_text(encoding="utf-8"))
    assert bundle["refs"][0]["source"] == "comment" and bundle["comment_adopt"] is True
    assert "- 단서 위치: 코멘트 2번 단서(ipc) 로그에서 찾음" in (out / "report.md").read_text(encoding="utf-8")
    # 가설·모듈·모름·side·회차는 판정에 쓰지 않는다: 그 칸만 다른 problem.json은 기준·판정이 같다
    noise = {"hypotheses": ["NETWORK-001 비행기 모드가 원인"], "modules": ["data"], "unknown": ["CP 로그 없음"],
             "rounds": {"count": 3, "last_from_comment": 1, "same_failure": "no"}}
    b, out2 = _problem_run(seed_db, "noise", "cluepos.log", [{**IPC_CLUE, "side": "ap"}], **noise)
    keep = ("state", "reason", "selected", "location", "check")       # events는 4KB 압축(경로 길이)에 따라 줄 수 있다
    assert {k: b["decision"][k] for k in keep} == {k: d[k] for k in keep}
    assert json.loads((out2 / "reference.json").read_text(encoding="utf-8")) == bundle
    assert (out2 / "eligibility.json").read_text(encoding="utf-8") == (out / "eligibility.json").read_text(encoding="utf-8")

    a, _ = _problem_run(seed_db, "other", "cluepos.log", [IPC_CLUE], sha="0" * 64)
    assert a["decision"]["reason"] == "no_reference"
    assert any("problem.json" in w and "쓰지 않았다" in w for w in a.get("warnings") or []), a.get("warnings")

    a, _ = _problem_run(seed_db, "stale", "cluepos.log", [{**IPC_CLUE, "stale": True}])
    assert a["decision"]["reason"] == "no_reference"                                     # 이전 회차 단서는 안 쓴다(H03)

    a, out = _problem_run(seed_db, "missing", "cluepos.log", [{**IPC_CLUE, "token": "0x0ff"}])
    assert a["decision"]["reason"] == "no_reference"
    assert "코멘트 2번 단서, 로그에서 못 찾음(일치하는 줄 없음)" in (a.get("warnings") or []), a.get("warnings")
    assert json.loads((out / "eligibility.json").read_text(encoding="utf-8"))["reference"]["dropped"] == \
        [{"comment": 2, "kind": "ipc", "why": "일치하는 줄 없음"}]

    a, _ = _problem_run(seed_db, "steps", "cluepos.log", [IPC_CLUE], steps_sha256="0" * 64)
    assert a["decision"]["location"]["source"] == "comment"           # --steps-file 없으면 TC 해시는 보지 않는다


def test_run_ignores_problem_when_steps_file_differs(seed_db):
    """P2-2: `--steps-file`을 주면 problem.json `steps_sha256`과도 같아야 쓴다."""
    import hashlib
    steps = tmp("tt-elig-steps-") / "tc.txt"
    steps.write_text("1 attach PASS\n2 data FAIL\n", encoding="utf-8")
    sha = hashlib.sha256(steps.read_bytes()).hexdigest()
    _, out = _problem_run(seed_db, "steps-same", "cluepos.log", [IPC_CLUE], steps_sha256=sha)
    # _problem_run은 --steps-file을 넘기지 않으므로 같은 작업 폴더로 다시 돈다
    args = ["run", "CLUEPOS-1", "--offline-db", seed_db, "--out", out, "--logs", maf.OUT / "cluepos.log",
            "--issue-meta", out.parent / "steps-same.meta.json", "--tz", "Asia/Seoul", "--year", "2026", "--steps-file", steps]

    def clue_refs() -> list:
        path = out / "reference.json"
        refs = json.loads(path.read_text(encoding="utf-8"))["refs"] if path.is_file() else []
        return [r for r in refs if r["source"] == "comment"]
    run_json("triage.py", args)
    assert clue_refs()
    doc = json.loads((out / "problem.json").read_text(encoding="utf-8"))
    (out / "problem.json").write_text(json.dumps({**doc, "steps_sha256": "0" * 64}), encoding="utf-8")
    other = run_json("triage.py", args)
    assert clue_refs() == []
    assert any("--steps-file" in w and "쓰지 않았다" in w for w in other.get("warnings") or []), other.get("warnings")


def test_run_clue_text_quotes_newline_mask_token_and_dedup(seed_db):
    """단서 글의 따옴표·정규식 글자는 글자 그대로 비교(못 찾으면 버림), 줄바꿈은 공백으로, 마스킹 토큰은 번호 없이 맞춘다.
    같은 찾을 글은 한 번만 찾는다. 같은 이름이 여러 요청에 있으면 위치 multiple."""
    line = {"comment": 3, "kind": "log_line", "name": None, "token": None, "side": "ap", "stale": False,
            "quote": "onDataNetworkSetupDataFailed: [DataNetwork: DN-120-C,\n<APN#7>, state=null]"}
    odd = {**line, "comment": 4, "quote": 'x "quoted" (.*) [a-z]+ \\ $HOME; rm -rf'}
    a, out = _problem_run(seed_db, "text", "cluepos.log", [line, odd, {**line, "comment": 5}])
    d = a["decision"]
    assert (d["state"], d["location"]) == ("accepted", {"state": "found", "source": "comment", "kind": "near"})
    bundle = json.loads((out / "reference.json").read_text(encoding="utf-8"))
    assert [r["comment"] for r in bundle["refs"]] == [3] and [x["comment"] for x in bundle["dropped"]] == [4]
    trace = [json.loads(x) for x in (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(1 for r in trace if r.get("step") == "3-clue") == 2          # 3번·4번만(5번은 3번과 같은 글)
    name = {"comment": 2, "kind": "ipc_name", "name": "VIPC_SETUP_DATA", "token": None, "quote": "VIPC_SETUP_DATA 실패",
            "side": "cp", "stale": False}
    a, _ = _problem_run(seed_db, "name", "cluepos.log", [name])
    d = a["decision"]
    assert (d["reason"], d["check"]["why"], d["location"]["state"]) == ("ambiguous", "locations", "multiple")
    # 보류(사건이 붙은 단서 없음)면 단서 중 하나라도 여러 곳일 때 multiple — 첫 단서가 한 곳이어도
    after = {**line, "quote": "VIPC_SETUP_DATA, RSP, token=0x0e4"}      # 성공 응답 줄(실패 사건 아님, 유형 없으면 근처 보류)
    a, _ = _problem_run(seed_db, "mixed", "cluepos.log", [after, name], symptom={"text": "", "types": [], "not_in_db": False})
    assert a["decision"]["state"] == "held" and a["decision"]["location"]["state"] == "multiple", a["decision"]


def test_clue_with_bad_comment_number_is_not_used():
    """코멘트 번호가 1 이상 정수나 "description"이 아니면 그 단서는 쓰지 않는다(경고·리포트의 "코멘트 n번"이 깨지지 않게)."""
    from triagelib import anchor, problem as pb
    for n in (0, -1, "2", None, True, 2.0, "x\n- 판단: 채택"):
        assert anchor._clue_text({**IPC_CLUE, "comment": n}, pb) == (None, None), n
    assert anchor._clue_text({**IPC_CLUE, "comment": "description"}, pb)[0] == "VIPC_SETUP_DATA (token=0x0e3)"


def test_run_config_switches(seed_db):
    """`eligibility.comment_adopt` 기본(참)이면 코멘트 단서 지점에서 채택하되 위치는 found(확정 아님), `false`면 붙은 사건을
    싣고 보류. `use_problem_types: false`면 유형을 안 써 근처는 5-1처럼 보류."""
    a, out = _problem_run(seed_db, "adopt", "cluepos.log", [IPC_CLUE])
    d = a["decision"]
    assert (d["state"], d["selected"]["cause"], d["location"]) == \
        ("accepted", "DATA-003-01", {"state": "found", "source": "comment", "kind": "point"})
    assert "실패 지점: Jira 코멘트·단서 위치(확정 아님)" in (out / "report.md").read_text(encoding="utf-8")
    a, _ = _problem_run(seed_db, "off", "cluepos.log", [IPC_CLUE], root=plugin_root(eligibility={"comment_adopt": False}))
    assert (a["decision"]["state"], a["decision"]["check"]["why"]) == ("held", "comment_unconfirmed")
    # 리뷰 P2-2: 참·거짓이 아닌 값(글자 "false")은 경고하고 기본(참) — 몰래 참·거짓으로 읽지 않는다
    a, out = _problem_run(seed_db, "strfalse", "cluepos.log", [IPC_CLUE], root=plugin_root(eligibility={"comment_adopt": "false"}))
    assert a["decision"]["state"] == "accepted", a["decision"]
    assert any("eligibility.comment_adopt" in w for w in a["warnings"]), a["warnings"]
    assert json.loads((out / "reference.json").read_text(encoding="utf-8"))["comment_adopt"] is True
    near = "ConnectingState: setupData: accessNetwork=EUTRAN, isSatellite=false"
    a, _ = _problem_run(seed_db, "near", "nearpos.log", [], look_at=near)
    assert (a["decision"]["state"], a["decision"]["selected"]["cause"]) == ("accepted", "DATA-003-01")
    a, _ = _problem_run(seed_db, "notypes", "nearpos.log", [], look_at=near,
                        root=plugin_root(eligibility={"use_problem_types": False}))
    assert (a["decision"]["reason"], a["decision"]["check"]["why"]) == ("ineligible", "near_without_symptom")


def test_adopted_location_follows_eligibility():
    """채택이면 실패 지점 상태는 자격 검사 결과로: 기준 줄 자체가 실패 사건이면 confirmed/point(글자 일치여도), 근처 채택은 found,
    구간은 FAIL 마커 1개일 때만 confirmed, comment 출처는 늘 found. 보류는 앵커 기준 그대로(글자 일치 한 곳 = found)."""
    from triagelib import driver
    cands = [{"category": "data", "type": "DATA-001", "cause": "DATA-001-01"}]
    text = {"state": "found", "source": "look_at", "kind": "near"}

    def loc(location, why, state="accepted", **extra):
        elig = {"state": state, "reason": "anchored_top" if state == "accepted" else "ineligible", "why": why,
                "cause": "DATA-001-01" if state == "accepted" else None, **extra}
        return driver._decision(cands, {"location": location}, elig)["location"]
    assert loc(text, "same_line") == {"state": "confirmed", "source": "look_at", "kind": "point"}
    # 리뷰 P1-1: CP 점은 응답 뒤 2초 안 첫 사건일 뿐 같은 요청이라는 근거가 없다 → found/point
    assert loc({**text, "kind": "point", "state": "confirmed"}, "cp_point") == {**text, "kind": "point", "state": "found"}
    assert loc(text, "near") == text                                   # 근처 채택(5-2) = 찾음
    point_loc = {"state": "confirmed", "source": "look_at", "kind": "point"}
    assert loc(point_loc, "near") == {**point_loc, "state": "found"}  # 마지막 갈래: confirmed가 들어와도 found
    # 리뷰 P2-3: 창 안 조건 줄로만 붙은 채택(cond_line)은 found·kind 그대로 — 글자 일치(near)가 point로 바뀌지 않는다
    assert loc(text, "same_line", cond_line=True) == text
    assert loc(point_loc, "same_line", cond_line=True) == {**point_loc, "state": "found"}
    assert loc(text, "near_without_symptom", state="held") == text            # 보류는 앵커 기준 그대로
    marker = {"state": "confirmed", "source": "log_marker", "kind": "range"}
    assert loc(marker, "range") == {**marker, "state": "found"}      # 리뷰 P2-2: FAIL 마커는 실패 사건 줄이 아니다
    assert loc({**marker, "source": "steps_file", "state": "found"}, "range")["state"] == "found"
    assert loc({**marker, "source": "steps_file"}, "range")["state"] == "found"   # confirmed여도 log_marker가 아니면 found
    assert loc({"state": "confirmed", "source": "comment", "kind": "point"}, "same_line")["state"] == "found"
