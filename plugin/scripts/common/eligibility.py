"""자격 검사(단계 5): 기준(실패 지점)이 가리키는 실패 사건에 실제로 붙는 원인만 채택한다 — 순수 함수, 표준 라이브러리만.

사건 목록(`occurrences`)은 매처(`match_signatures.occurrences`)가 만든다. 사건 = 유형 시그니처 1회 충족(유형 있음) 또는 파생 오류
이벤트(`ERROR_EVENT_RE`, 유형 없음). 사건 시각(`at`) = 증상 근거 중 가장 늦은 줄. 유형 사건에는 붙은 원인(`causes`: 근거가 전부
사건 시각 이하이고 그 원인 1회 충족이 이 사건에만 붙음 — 규칙 2·§8-2), 사건 뒤에만 관측된 원인(`after`), 안 나옴을 확인 못 한
원인(`absence_unverified`)을 싣는다.

기준(`reference`, `triage.py`가 `JOB/reference.json`에 쓴다):
- `{kind: line, source: look_at, places, lines[{line_ref, ts, phone, ipc?: {dir, name, token}, ril?: {serial, pid, paired_ts}}]}`
- `{kind: range, source: log_marker|steps_file|step_order, places, start, fail}`

기준 종류는 "기준 줄 자체가 실패 사건인가"로 나눈다:
- 점(같은 줄): 기준 줄이 사건의 증상 줄·붙은 원인 줄·그 충족 구간에서 증상·붙은 원인 조건에 맞는 줄(§8-1) 중 하나이거나
  같은 RIL 요청(같은 pid·슬롯·serial + 짝 시각) → 그 사건.
- 점(CP token): 기준이 벤더 IPC 줄 → 같은 요청의 RSP(없으면 REQ) 뒤 `link_ms`(기본 `DEFAULT_LINK_MS` 2초) 안 같은 슬롯(또는 모름)
  첫 유형 사건. 유형 없는 실패만 있으면 symptom_not_found, 없으면 ineligible/no_event_at_reference.
- 근처(그 밖의 AP 줄): 문제 파악 유형이 있어야 붙인다 — 5-1은 problem.json을 읽지 않으므로 늘 ineligible/near_without_symptom.
- 구간: 로그 FAIL 마커(START, 없으면 FAIL−120초 ~ FAIL) 안 유형 사건 전부 — 채택 원인이 모두 같을 때만. steps-file 시각 구간은
  문제 파악 유형이 있어야(5-1은 ineligible/range_without_symptom), 스텝 순서·START만은 채택 안 함(ineligible/range_end_unknown).
- 여러 곳(`places` > 1) ambiguous/locations, 슬롯 둘 이상 ambiguous/slots, 출처끼리 다른 사건 ambiguous/sources.
사유 우선순위: no_candidate → no_reference → symptom_not_found → ambiguous → ineligible → cause_unjudged·cause_unconfirmed → accepted.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

ERROR_EVENT_RE = re.compile(r"(error|timeout|no_response|reject|fail|denied|lost)", re.IGNORECASE)   # 파생 오류 이벤트 이름
DEFAULT_LINK_MS = 2000      # = platforms.base.DEFAULT_LINK_MS (CP 점 → 사건 붙임 창)
RANGE_PRE_SEC = 120         # 로그 FAIL 마커에 START가 없을 때 구간 시작 = FAIL − 120초
MERGE_SEC = 1.0             # 같은 유형·슬롯 사건이 이만큼 안이면 한 사건(유형의 다른 시그니처가 같은 실패를 따로 잡은 것, §8-4)
EVENTS_MAX = 3              # analysis.json `decision.events[]` 상한(전체는 JOB/eligibility.json)
_HELD_ORDER = ("symptom_not_found", "ambiguous", "ineligible")


def ts(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def ref_key(line_ref) -> tuple | None:
    """`line_ref` `{file_index, line_no}` → (파일, 줄). 줄 번호 모르면 None."""
    if isinstance(line_ref, dict) and line_ref.get("line_no") is not None:
        return line_ref.get("file_index"), line_ref["line_no"]
    return None


def merge(events: list[dict]) -> list[dict]:
    """시각 순 사건 목록에서 같은 유형·같은 슬롯(또는 모름) 사건이 `MERGE_SEC` 안에 이어지면 하나로 합친다."""
    out: list[dict] = []
    for e in events:
        prev = next((m for m in reversed(out) if e["type"] and m["type"] == e["type"]
                     and (m.get("phone") == e.get("phone") or None in (m.get("phone"), e.get("phone")))
                     and (e["at"] - m["at"]).total_seconds() <= MERGE_SEC), None)
        if prev is None:
            out.append(e)
            continue
        prev["at"] = max(prev["at"], e["at"])
        for k in ("lines", "cause_lines", "cond_lines"):
            prev[k] = prev[k] | e[k]
        best: dict = {}
        for c in prev["causes"] + e["causes"]:
            best[c[1]] = min(best.get(c[1], c), c)
        prev["causes"] = sorted(best.values())
        prev["after"] = sorted((set(prev["after"]) | set(e["after"])) - set(best))
        prev["absence_unverified"] = sorted(set(prev["absence_unverified"]) | set(e["absence_unverified"]))
        prev["raw"] = prev["raw"] + e["raw"]
        prev["absence"] = prev["absence"] or e["absence"]
        prev["absence_bad"] = prev["absence_bad"] or e["absence_bad"]
        prev["unjudged"] = prev["unjudged"] or e["unjudged"]
    return out


# -- 판정 ---------------------------------------------------------------------------------------------------

def _held(reason: str, why: str | None, evs=()) -> dict:
    return {"state": "held", "reason": reason, "why": why, "cause": None, "events": list(evs)}


def _adopt(evs: list[dict], why: str) -> dict:
    """붙은 사건 → 채택(원인 1순위가 모두 같을 때만) 또는 보류."""
    picks = [e["causes"][0][1] if e["causes"] else None for e in evs]
    if None in picks:
        e = evs[picks.index(None)]
        if e["absence_bad"] or (e["absence_unverified"] and not e["after"]):
            return _held("ineligible", "absence_unverified", evs)     # 안 나옴 필요조건 못 채움(로그가 먼저 끝남 등)
        if e["unjudged"] and not e["after"]:
            return _held("cause_unjudged", "cause_unjudged", evs)
        return _held("cause_unconfirmed", "cause_after_event" if e["after"] else "no_cause_before_event", evs)
    if len(set(picks)) > 1:
        return _held("ambiguous", "multiple_events", evs)
    return {"state": "accepted", "reason": "anchored_top", "why": why, "cause": picks[0], "events": evs}


def _same_ril(e: dict, rils: list[dict]) -> bool:
    """같은 RIL 요청: 같은 pid·슬롯·serial(숫자만 — 가린 serial은 다르다) + 짝 시각이 이어짐."""
    for raw in e["raw"]:
        a = raw.get("ril") or {}
        if type(a.get("serial")) is not int:
            continue
        for r in rils:
            if (a["serial"] == r["serial"] and raw.get("pid") == r["pid"] and raw.get("phone_id") == r["phone"]
                    and ({a.get("paired_ts"), raw.get("ts")} & {r.get("paired_ts"), r["ts"]}) - {None}):
                return True
    return False


def _attach_line(ref: dict, events: list[dict], link_ms: int) -> tuple:
    """기준 줄(한 곳) → ('events', [사건], why) | ('held', reason, why)."""
    lines = ref.get("lines") or []
    ipc = [x for x in lines if x.get("ipc")]
    if ipc:     # CP 점: 같은 요청의 RSP(없으면 REQ) 뒤 link_ms 안 같은 슬롯(또는 모름) 실패 사건
        base = next((x for x in ipc if x["ipc"].get("dir") == "rsp"), ipc[0])
        t0, slot = ts(base["ts"]), base.get("phone")
        win = [e for e in events if t0 <= e["at"] <= t0 + timedelta(milliseconds=link_ms)
               and (slot is None or e.get("phone") in (slot, None))]
        typed = [e for e in win if e["type"]]
        if typed:
            return "events", typed[:1], "cp_point"
        return ("held", "symptom_not_found", "typeless_failure_within_link") if win else \
            ("held", "ineligible", "no_event_at_reference")
    refs = {k for k in (ref_key(x.get("line_ref")) for x in lines) if k}
    rils = [{**x["ril"], "phone": x.get("phone"), "ts": x["ts"]} for x in lines if x.get("ril")]
    same = [e for e in events if (e["lines"] | e.get("cause_lines", set()) | e.get("cond_lines", set())) & refs
            or (rils and _same_ril(e, rils))]
    if same:    # 점(같은 줄·같은 RIL 요청)
        typed = [e for e in same if e["type"]]
        return ("events", typed[:1], "same_line") if typed else ("held", "symptom_not_found", "same_line_typeless")
    return "held", "ineligible", "near_without_symptom"     # 근처: 문제 파악 유형이 있어야 붙인다(5-2)


def _attach_range(ref: dict, events: list[dict]) -> tuple:
    if ref["source"] == "step_order" or not ref.get("fail"):
        return "held", "ineligible", "range_end_unknown"
    if ref["source"] == "steps_file":
        return "held", "ineligible", "range_without_symptom"     # TC 파일 시각 구간: 문제 파악 유형이 있어야(5-2)
    fail = ts(ref["fail"])
    lo = ts(ref["start"]) if ref.get("start") else fail - timedelta(seconds=RANGE_PRE_SEC)
    inside = [e for e in events if e["type"] and lo <= e["at"] <= fail]
    return ("events", inside, "range") if inside else ("held", "symptom_not_found", "no_event_in_range")


def decide(events: list[dict], refs: list[dict], link_ms: int = DEFAULT_LINK_MS) -> dict:
    """사건 목록 + 기준(0개 이상) → `{state, reason, why, cause, events(붙은 사건)}`. 후보 없음(no_candidate)은 부른 쪽이 먼저 본다."""
    if not refs:
        return _held("no_reference", None)
    outcomes = []
    for ref in refs:
        slots = {x.get("phone") for x in ref.get("lines") or []} - {None}
        if (ref.get("places") or 1) > 1:
            outcomes.append(("held", "ambiguous", "locations"))
        elif len(slots) > 1:
            outcomes.append(("held", "ambiguous", "slots"))
        elif ref["kind"] == "range":
            outcomes.append(_attach_range(ref, events))
        else:
            outcomes.append(_attach_line(ref, events, ref.get("link_ms") or link_ms))
    got = [o for o in outcomes if o[0] == "events"]
    if len({tuple(id(e) for e in o[1]) for o in got}) > 1:
        return _held("ambiguous", "sources", [e for o in got for e in o[1]])
    if got:
        return _adopt(got[0][1], got[0][2])
    best = min(outcomes, key=lambda o: _HELD_ORDER.index(o[1]))
    return _held(best[1], best[2])


# -- 출력 ---------------------------------------------------------------------------------------------------

def _label(key) -> str | None:
    return f"f{key[0]}:L{key[1]}" if key else None


def event_row(e: dict, attached: set, result: str | None) -> dict:
    """유형 사건 하나 → 계약 모양 `{type, at, line, phone, absence, ref, result, cause, why, gap_s}`(analysis.json·eligibility.json).
    `result`: 기준에 붙은 사건은 adopted|held, 나머지는 observed(관측된 규칙 일치). `why`: 원인이 안 붙은 이유(붙었으면 null)."""
    why = None
    if not e["causes"]:
        why = ("absence_unverified" if e["absence_bad"] or (e["absence_unverified"] and not e["after"])
               else "cause_after_event" if e["after"] else "no_cause_before_event")
    return {"type": e["type"], "at": e["at"].isoformat(), "line": _label(max(e["lines"]) if e["lines"] else None),
            "phone": e.get("phone"), "absence": e["absence"], "ref": id(e) in attached,
            "result": result if id(e) in attached else "observed",
            "cause": e["causes"][0][1] if e["causes"] else None, "why": why, "gap_s": e["gap_s"]}


def summary(dec: dict, events: list[dict]) -> dict:
    """판정 + 사건 → `{state, reason, why, cause, checked, total, events_total, events(유형 사건 전부, 붙은 것 먼저)}`.
    `checked` = 기준에 붙어 검사한 사건 수, `total` = 실패 사건 수(유형 없음 포함), `events_total` = 유형 사건 수."""
    attached = {id(e) for e in dec["events"]}
    result = "adopted" if dec["state"] == "accepted" else "held"
    typed = [e for e in events if e["type"]]
    order = [e for e in dec["events"]] + [e for e in typed if id(e) not in attached]
    return {"state": dec["state"], "reason": dec["reason"], "why": dec["why"], "cause": dec["cause"],
            "checked": len(dec["events"]), "total": len(events), "events_total": len(typed),
            "events": [event_row(e, attached, result) for e in order]}


if __name__ == "__main__":     # 자기 점검(규칙별 시험은 tests/test_eligibility.py)
    T = datetime(2026, 11, 14, 1, 0)

    def ev(typ, sec, causes=(), line=(0, 1), after=()):
        return {"type": typ, "at": T + timedelta(seconds=sec), "lines": {line}, "phone": 0, "raw": [],
                "causes": [(i, c, 0.1) for i, c in enumerate(causes)], "after": list(after), "absence_unverified": [],
                "absence": False, "absence_bad": False, "unjudged": False}
    evs = [ev(None, 0.62, line=(0, 5)), ev("N", 120, ["N3"], line=(0, 16))]
    pt = {"kind": "line", "source": "look_at", "places": 1, "lines": [{"line_ref": {"file_index": 0, "line_no": 16},
                                                                       "ts": (T + timedelta(seconds=120)).isoformat()}]}
    assert decide(evs, [pt])["cause"] == "N3"
    assert decide(evs, [])["reason"] == "no_reference"
    print("eligibility self-check ok")
