"""자격 검사(단계 5): 기준(실패 지점)이 가리키는 실패 사건에 실제로 붙는 원인만 채택한다 — 순수 함수, 표준 라이브러리만.

사건 목록(`occurrences`)은 매처(`match_signatures.occurrences`)가 만든다. 사건 = 유형 시그니처 1회 충족(유형 있음) 또는 파생 오류
이벤트(`ERROR_EVENT_RE`, 유형 없음). 사건 시각(`at`) = 증상 근거 중 가장 늦은 줄. 유형 사건에는 붙은 원인(`causes`: 근거가 전부
사건 시각 이하이고 그 원인 1회 충족이 이 사건에만 붙음 — 규칙 2·§8-2), 사건 뒤에만 관측된 원인(`after`), 안 나옴을 확인 못 한
원인(`absence_unverified`)을 싣는다.

기준(`reference`, `triage.py`가 `JOB/reference.json`에 쓴다):
- `{kind: line, source: look_at, places, lines[{line_ref, ts, phone, ipc?: {dir, name, token}, ril?: {serial, pid, paired_ts}}]}`
- `{kind: range, source: log_marker|steps_file|step_order, places, start, fail}`
- 문제 파악 단서(단계 5-2, `triage.py`가 같은 JOB `problem.json`의 단서를 로그에서 찾은 곳): 기준 줄과 같은 모양에 `source: comment`.

기준 종류는 "기준 줄 자체가 실패 사건인가"로 나눈다:
- 점(같은 줄): 기준 줄이 사건의 증상 줄·붙은 원인 줄·그 충족 구간에서 증상·붙은 원인 조건에 맞는 줄(§8-1) 중 하나이거나
  같은 RIL 요청(같은 pid·슬롯·serial + 짝 시각) → 그 사건.
- 점(CP token): 기준이 벤더 IPC 줄 → 같은 요청의 RSP(없으면 REQ) 뒤 `link_ms`(기본 `DEFAULT_LINK_MS` 2초) 안 같은 슬롯(또는 모름)
  첫 유형 사건. 유형 없는 실패만 있으면 symptom_not_found, 없으면 ineligible/no_event_at_reference.
- 근처(그 밖의 AP 줄): 문제 파악 유형(`allowed`)이 있을 때만 기준 시각부터 `NEAR_SEC` 안 허용 유형 첫 사건(없으면
  symptom_not_found/no_allowed_event_near), 유형이 없으면 ineligible/near_without_symptom.
- 구간: 로그 FAIL 마커(START, 없으면 FAIL−120초 ~ FAIL) 안 유형 사건(허용 유형이 있으면 그 유형만) 전부 — 채택 원인이 모두 같을
  때만. steps-file 시각 구간은 문제 파악 유형이 있어야(없으면 ineligible/range_without_symptom), 스텝 순서·START만은 채택 안 함
  (ineligible/range_end_unknown). 같은 줄 점은 유형으로 거르지 않는다.
- 여러 곳(`places` > 1) ambiguous/locations, 슬롯 둘 이상 ambiguous/slots, 출처끼리 다른 사건 ambiguous/sources.
- 출처: 명시 기준(look_at·마커·steps-file)이 있으면 그것이 정한다 — 단서는 명시 기준과 다른 사건을 가리킬 때만 ambiguous/sources로
  만든다. 단서만 있으면 단서가 정하되, `comment_adopt`가 거짓(기본)이면 붙은 사건을 싣고 ineligible/comment_unconfirmed로 보류한다.
- 문제 파악이 "DB에 없는 증상"(`not_in_db`)이면 기준이 있어도 symptom_not_found/not_in_db(다른 사건의 원인으로 대신하지 않는다).
사유 우선순위: no_candidate → no_reference → symptom_not_found → ambiguous → ineligible → cause_unjudged·cause_unconfirmed → accepted.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

ERROR_EVENT_RE = re.compile(r"(error|timeout|no_response|reject|fail|denied|lost)", re.IGNORECASE)   # 파생 오류 이벤트 이름
DEFAULT_LINK_MS = 2000      # = platforms.base.DEFAULT_LINK_MS (CP 점 → 사건 붙임 창)
NEAR_SEC = 300              # 근처 기준 → 허용 유형 첫 사건 창(= lookat.POST_SEC, 기준 줄 뒤 분석 구간)
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
    """시각 순 사건 목록에서 같은 유형·같은 슬롯(또는 모름) 사건이 첫 사건 시각부터 `MERGE_SEC` 안이면 하나로 합친다(합친 시각에서
    다시 재지 않아 사슬처럼 늘어나지 않는다). 합친 사건 시각은 가장 늦은 것, 원인 간격(`gap_s`)은 그 시각 기준으로 다시 잰다."""
    out: list[dict] = []
    first: dict[int, datetime] = {}
    for e in events:
        prev = next((m for m in reversed(out) if e["type"] and m["type"] == e["type"]
                     and (m.get("phone") == e.get("phone") or None in (m.get("phone"), e.get("phone")))
                     and (e["at"] - first[id(m)]).total_seconds() <= MERGE_SEC), None)
        if prev is None:
            first[id(e)] = e["at"]
            out.append(e)
            continue
        at = max(prev["at"], e["at"])
        causes = [(c[0], c[1], round(c[2] + (at - x["at"]).total_seconds(), 3)) for x in (prev, e) for c in x["causes"]]
        prev["at"] = at
        for k in ("lines", "cause_lines", "cond_lines"):
            prev[k] = prev[k] | e[k]
        best: dict = {}
        for c in causes:
            best[c[1]] = min(best.get(c[1], c), c)
        prev["causes"] = sorted(best.values())
        prev["gap_s"] = prev["causes"][0][2] if prev["causes"] else None
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
    if any(e["absence_bad"] for e in evs):     # 증상의 안 나옴을 확인 못 함 — 붙은 원인이 있어도 사건 자체가 미확인(먼저 보류)
        return _held("ineligible", "absence_unverified", evs)
    picks = [e["causes"][0][1] if e["causes"] else None for e in evs]
    if None in picks:
        e = evs[picks.index(None)]
        if e["absence_unverified"] and not e["after"]:
            return _held("ineligible", "absence_unverified", evs)     # 원인의 안 나옴 필요조건 못 채움(로그가 먼저 끝남 등)
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


def _attach_line(ref: dict, events: list[dict], link_ms: int, allowed: set | None = None) -> tuple:
    """기준 줄(한 곳) → ('events', [사건], why) | ('held', reason, why). `allowed` = 문제 파악 허용 유형(없으면 None)."""
    lines = ref.get("lines") or []
    ipc = [x for x in lines if x.get("ipc")]
    if ipc:     # CP 점: 같은 요청의 RSP(없으면 REQ) 뒤 link_ms 안 같은 슬롯(또는 모름) 실패 사건
        base = next((x for x in ipc if x["ipc"].get("dir") == "rsp"), ipc[0])
        t0, slot = ts(base["ts"]), base.get("phone")
        win = [e for e in events if t0 <= e["at"] <= t0 + timedelta(milliseconds=link_ms)
               and (slot is None or e.get("phone") in (slot, None))]
        typed = [e for e in win if e["type"] and (allowed is None or e["type"] in allowed)]
        if typed:
            return "events", typed[:1], "cp_point"
        return ("held", "symptom_not_found", "typeless_failure_within_link") if win else \
            ("held", "ineligible", "no_event_at_reference")
    refs = {k for k in (ref_key(x.get("line_ref")) for x in lines) if k}
    rils = [{**x["ril"], "phone": x.get("phone"), "ts": x["ts"]} for x in lines if x.get("ril")]
    # 근거 줄(증상·원인)이 기준 줄인 사건을 먼저, 없을 때만 창 안 조건 줄(§8-1) — 앞 사건 창이 뒤 사건 증상 줄을 덮어도 뒤 사건으로
    same = [e for e in events if (e["lines"] | e.get("cause_lines", set())) & refs or (rils and _same_ril(e, rils))] \
        or [e for e in events if e.get("cond_lines", set()) & refs]
    if same:    # 점(같은 줄·같은 RIL 요청) — 유형으로 거르지 않는다(사용자가 그 줄을 가리켰다)
        typed = [e for e in same if e["type"]]
        return ("events", typed[:1], "same_line") if typed else ("held", "symptom_not_found", "same_line_typeless")
    if allowed is None:
        return "held", "ineligible", "near_without_symptom"     # 근처: 문제 파악 유형이 있어야 붙인다
    t0 = min(ts(x["ts"]) for x in lines) if lines else None
    near = [e for e in events if t0 and e["type"] in allowed and t0 <= e["at"] <= t0 + timedelta(seconds=NEAR_SEC)]
    return ("events", near[:1], "near") if near else ("held", "symptom_not_found", "no_allowed_event_near")


def _attach_range(ref: dict, events: list[dict], allowed: set | None = None) -> tuple:
    if ref["source"] == "step_order" or not ref.get("fail"):
        return "held", "ineligible", "range_end_unknown"
    if ref["source"] == "steps_file" and allowed is None:
        return "held", "ineligible", "range_without_symptom"     # TC 파일 시각 구간: 문제 파악 유형이 있어야
    fail = ts(ref["fail"])
    lo = ts(ref["start"]) if ref.get("start") else fail - timedelta(seconds=RANGE_PRE_SEC)
    inside = [e for e in events if e["type"] and (allowed is None or e["type"] in allowed) and lo <= e["at"] <= fail]
    return ("events", inside, "range") if inside else ("held", "symptom_not_found", "no_event_in_range")


def _outcome(ref: dict, events: list[dict], link_ms: int, allowed: set | None) -> tuple:
    slots = {x.get("phone") for x in ref.get("lines") or []} - {None}
    if (ref.get("places") or 1) > 1:
        return "held", "ambiguous", "locations"
    if len(slots) > 1:
        return "held", "ambiguous", "slots"
    if ref["kind"] == "range":
        return _attach_range(ref, events, allowed)
    return _attach_line(ref, events, ref.get("link_ms") or link_ms, allowed)


def _pick(outcomes: list[tuple]) -> dict | tuple:
    """같은 출처 무리의 결과 → 사건이 붙은 결과(여럿이면 같은 사건일 때만) | 보류 판정(사건이 없으면 가장 앞선 사유)."""
    got = [o for o in outcomes if o[0] == "events"]
    if len({tuple(id(e) for e in o[1]) for o in got}) > 1:
        return _held("ambiguous", "sources", [e for o in got for e in o[1]])
    if got:
        return got[0]
    best = min(outcomes, key=lambda o: _HELD_ORDER.index(o[1]))
    return _held(best[1], best[2])


def decide(events: list[dict], refs: list[dict], link_ms: int = DEFAULT_LINK_MS, problem: dict | None = None,
           comment_adopt: bool = False) -> dict:
    """사건 목록 + 기준(0개 이상, 단서는 `source: comment`) + 문제 파악(`{types, not_in_db}` — types는 부른 쪽이 DB에 있는 것만
    남긴다, 없으면 None) → `{state, reason, why, cause, events(붙은 사건)}`. 후보 없음(no_candidate)은 부른 쪽이 먼저 본다."""
    if not refs:
        return _held("no_reference", None)
    if problem and problem.get("not_in_db"):
        return _held("symptom_not_found", "not_in_db")
    allowed = set(problem["types"]) if problem and problem.get("types") else None
    explicit = [_outcome(r, events, link_ms, allowed) for r in refs if r.get("source") != "comment"]
    clues = [_outcome(r, events, link_ms, allowed) for r in refs if r.get("source") == "comment"]
    if explicit:    # 명시 기준이 정한다 — 단서는 다른 사건을 가리킬 때만 모호로
        got = _pick(explicit)
        if isinstance(got, dict):
            return got
        mine = {id(e) for e in got[1]}
        other = [e for o in clues if o[0] == "events" for e in o[1] if id(e) not in mine]
        if other:
            return _held("ambiguous", "sources", got[1] + other)
        return _adopt(got[1], got[2])
    got = _pick(clues)
    if isinstance(got, dict):
        return got
    if not comment_adopt:     # 코멘트 지점 채택은 사용자 결정 전(Y1) — 붙은 사건은 싣고 보류
        return _held("ineligible", "comment_unconfirmed", got[1])
    return _adopt(got[1], got[2])


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
