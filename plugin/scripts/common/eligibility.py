"""자격 검사(단계 5): 기준(실패 지점)이 가리키는 실패 사건에 실제로 붙는 원인만 채택한다 — 순수 함수(예약 이벤트 이름만 parser_rules).

사건 목록(`occurrences`)은 매처(`match_signatures.occurrences`)가 만든다. 사건 = 유형 시그니처 1회 충족(유형 있음) 또는 파생 오류
이벤트(`ERROR_EVENT_RE`, 유형 없음). 사건 시각(`at`) = 증상 근거 중 가장 늦은 줄. 유형 사건에는 붙은 원인(`causes`: 근거가 전부
사건 시각 이하이고 그 원인 1회 충족이 이 사건에만 붙음 — 규칙 2·§8-2), 사건 뒤에만 관측된 원인(`after`), 안 나옴을 확인 못 한
원인(`absence_unverified`)을 싣는다.

기준(`reference`, `triage.py`가 `JOB/reference.json`에 쓴다):
- `{kind: line, source: look_at, places, lines[{line_ref, ts, phone, ipc?: {dir, name, token, ok?}, ril?: {serial, pid, paired_ts}}]}`
  (`ok: true` = 그 IPC 줄 결과가 성공 값 `vendor_ipc.success`)
- `{kind: range, source: log_marker|steps_file|step_order, places, start, fail}`

기준 종류는 "기준 줄 자체가 실패 사건인가"로 나눈다:
- 점(같은 줄): 기준 줄이 사건의 증상 줄·붙은 원인 줄·그 충족 구간에서 증상·붙은 원인 조건에 맞는 줄(§8-1) 중 하나이거나
  같은 RIL 요청(같은 pid·슬롯·serial + 짝 시각) → 그 사건. 근거 줄·같은 요청으로 못 찾고 조건 줄로만 붙어 채택하면 why는
  same_line 그대로, 결과에 `cond_line: true`(driver가 실패 지점을 confirmed로 올리지 않는다). 그 줄에 유형 사건이 여럿이고 1순위
  원인이 서로 다르면 ambiguous/multiple_events.
- 점(CP token): 기준이 벤더 IPC 줄 → 기준 응답(RSP, 없으면 REQ)이 성공 값이면 ineligible/no_event_at_reference(기준 자체가 실패가
  아니다), 아니면 그 뒤 `link_ms`(기본 `DEFAULT_LINK_MS` 2초) 안 같은 슬롯(또는 모름) **첫 세는 실패**가 유형 사건일 때만 그 사건.
  첫 세는 실패가 유형 없음(기준 요청 자신이 DB에 없는 오류로 실패)이거나 세는 실패 없이 유형 없는 실패만 있으면
  symptom_not_found/typeless_failure_within_link, 실패가 없으면 ineligible/no_event_at_reference. 붙인 사건이 같은 요청이라는
  근거는 없어 실패 지점은 found(driver).
- 근처(그 밖의 AP 줄): 문제 파악 유형이 있어야 붙인다 — 5-1은 problem.json을 읽지 않으므로 늘 ineligible/near_without_symptom.
- 구간: 로그 FAIL 마커(START, 없으면 FAIL−120초 ~ FAIL) 안 유형 사건 전부 — 채택 원인이 모두 같을 때만. 구간 안 **마지막(FAIL에
  가장 가까운) 세는 실패**가 유형 없음이면 symptom_not_found/typeless_failure_in_range(스텝의 실제 실패가 DB에 없는 오류). steps-file 시각 구간은
  문제 파악 유형이 있어야(5-1은 ineligible/range_without_symptom), 스텝 순서·START만은 채택 안 함(ineligible/range_end_unknown).
  FAIL 마커는 스텝을 감쌀 뿐 실패 사건 줄이 아니라 채택해도 실패 지점은 found(driver).
- 여러 곳(`places` > 1) ambiguous/locations, 슬롯 둘 이상 ambiguous/slots, 출처끼리 다른 사건 ambiguous/sources.
- 세는 실패(`_fails`): 유형 사건 + data RIL 요청 실패(`parser_rules.RESERVED_EVENTS` — ril_error·ril_timeout·ril_no_response, 그 요청의
  ril.yaml category가 data인 것만 — 매처가 `ril_category`를 싣는다). 창은 기준 바로 앞 `ABSORB_SEC`의 유형 없는 실패까지(자기 요청
  RIL 오류 뒤 줄을 짚은 경우). 벤더 IPC
  이벤트·추출기 파생 이벤트(Data disallowed 평가 줄 등)는 세지 않는다(`total`에는 남는다 — 기준 IPC 자신의 오류 줄이 늘 창 안에
  있다). 흡수: RIL 실패 뒤 `ABSORB_SEC` 안에 같은 슬롯(또는 모름) 유형 사건이 오면 그 RIL 실패는 그 사건의 RIL 쪽 줄로 보고 세지
  않는다(RILJ 오류 응답 바로 뒤 DNC 실패 — 정상 모양).
자기 점검은 `plugin/scripts`에서 `python -m common.eligibility`(parser_rules를 패키지로 읽는다).
사유 우선순위: no_candidate → no_reference → symptom_not_found → ambiguous → ineligible → cause_unjudged·cause_unconfirmed → accepted.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta

from .parser_rules import RESERVED_EVENTS

ERROR_EVENT_RE = re.compile(r"(error|timeout|no_response|reject|fail|denied|lost)", re.IGNORECASE)   # 파생 오류 이벤트 이름
DEFAULT_LINK_MS = 2000      # = platforms.base.DEFAULT_LINK_MS (CP 점 → 사건 붙임 창)
# ponytail: 고정 문턱 — 공개 에뮬레이터 캡처 275개의 RILJ SETUP_DATA_CALL error 188개가 모두 1~185ms(중앙값 3ms) 안에 DNC 실패로
# 이어지고 사이 새 요청 0건(11/20 설계 리뷰). 사내 S-5에서 다시 잰다. RIL serial ↔ 사건 연결이 생기면 그것으로 바꾼다.
# 남는 위험: 0.5초 안 다른 요청의 유형 사건도 흡수하고, 여러 RIL 실패가 사건 하나에 흡수될 수 있다(캡처에선 사이 새 요청 0건).
ABSORB_SEC = 0.5            # RIL 요청 실패 → 같은 실패의 유형 사건(흡수) 창, 기준 바로 앞 자기 요청 RIL 오류를 볼 창
RIL_CATEGORY = "data"       # 세는 RIL 요청 실패의 ril.yaml category
RANGE_PRE_SEC = 120         # 로그 FAIL 마커에 START가 없을 때 구간 시작 = FAIL − 120초
MERGE_SEC = 1.0             # 같은 유형·슬롯 사건이 이만큼 안이면 한 사건(유형의 다른 시그니처가 같은 실패를 따로 잡은 것, §8-4)
EVENTS_MAX = 3              # analysis.json `decision.events[]` 상한(전체는 JOB/eligibility.json)
_HELD_ORDER = ("symptom_not_found", "ambiguous", "ineligible")
_COND = ":cond"             # 내부 표시: 기준 줄이 사건의 증상·원인 근거 줄이 아니라 창 안 조건 줄(§8-1)로만 맞음


def ts(value) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def ref_key(line_ref) -> tuple | None:
    """`line_ref` `{file_index, line_no}` → (파일, 줄). 줄 번호 모르면 None."""
    if isinstance(line_ref, dict) and line_ref.get("line_no") is not None:
        return line_ref.get("file_index"), line_ref["line_no"]
    return None


def _top(e: dict) -> str | None:
    return min(e["causes"])[1] if e["causes"] else None


def merge(events: list[dict]) -> list[dict]:
    """시각 순 사건 목록에서 같은 유형·같은 슬롯(모름은 모름끼리만) 사건이 첫 사건 시각부터 `MERGE_SEC` 안이면 하나로 합친다(합친
    시각에서 다시 재지 않아 사슬처럼 늘어나지 않는다). 합친 사건 시각은 가장 늦은 것, 원인 간격(`gap_s`)은 그 시각 기준으로 다시 잰다.
    합친 사건들의 1순위 붙은 원인이 서로 다르면(한쪽만 원인이 붙은 것도) 같은 실패를 두 시그니처가 잡은 것인지 따로 난 두 실패인지
    모른다 — `mixed`를 표시해 기준이 붙으면 ambiguous/multiple_events로 보류한다(옆 실패의 원인을 기준 사건 원인으로 채택하지 않게).
    한쪽만 원인이 붙은 경우도 보류하는 것은 일부러 고른 손해다: 틀린 채택 재현(0.5초 간격)과 정상 합치기(1~3ms)가 간격만 다르고
    ms 문턱을 정할 사내 근거가 없다 — 에뮬레이터 캡처 4건(d70b·d81·d77e·d32g)이 이 때문에 채택을 잃는다(자기 기준 유지
    161→155/166). 사내 자료로 다시 본다."""
    out: list[dict] = []
    first: dict[int, datetime] = {}
    for e in events:
        prev = next((m for m in reversed(out) if e["type"] and m["type"] == e["type"] and m.get("phone") == e.get("phone")
                     and (e["at"] - first[id(m)]).total_seconds() <= MERGE_SEC), None)
        if prev is None:
            first[id(e)] = e["at"]
            out.append(e)
            continue
        if _top(prev) != _top(e):
            prev["mixed"] = True
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
    if any(e.get("mixed") for e in evs):       # 1초 안 같은 유형 사건들의 원인이 다름(merge) — 어느 실패인지 모른다
        return _held("ambiguous", "multiple_events", evs)
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


def _ril_fail(e: dict) -> bool:
    """세는 RIL 요청 실패: 예약 이벤트이고 그 요청의 ril.yaml category가 data(매처가 `ril_category`를 싣는다 — 없으면 data로 본다).
    ponytail: 이 도구 범위가 data connection이라 data 요청만 센다(사내 ril.yaml이 넓으면 SIGNAL_STRENGTH·SIM_OPEN_CHANNEL 같은
    관계없는 오류로 과보류) — 사내 S-5에서 넓힐지 잰다."""
    # REQUEST_NOT_SUPPORTED는 모뎀이 그 요청을 지원하지 않는다는 뜻이지 짚은 요청의 실패가 아니다
    return (e.get("name") in RESERVED_EVENTS and e.get("ril_category", RIL_CATEGORY) in (RIL_CATEGORY, None)
            and all((r.get("fields") or {}).get("error") != "REQUEST_NOT_SUPPORTED" for r in e.get("raw") or []))


def _fails(events: list[dict]) -> list[dict]:
    """세는 실패(시각 순): 유형 사건 + data RIL 요청 실패. 부른 쪽이 준 창 안 사건만 본다 — RIL 실패 **뒤** `ABSORB_SEC` 안 같은
    슬롯(또는 모름) 유형 사건이 창 안에 있으면 그 RIL 실패는 빼고(그 사건의 RIL 쪽 줄), 벤더 IPC·추출기 파생 이벤트는 세지 않는다."""
    f = sorted((e for e in events if e["type"] or _ril_fail(e)), key=lambda e: e["at"])   # 합친 사건은 시각이 늦어진다
    ats = [e["at"] for e in f]

    def absorbed(e) -> bool:
        lo, hi = bisect_left(ats, e["at"]), bisect_right(ats, e["at"] + timedelta(seconds=ABSORB_SEC))
        return any(n["type"] and (e.get("phone") is None or n.get("phone") in (e.get("phone"), None)) for n in f[lo:hi])
    return [e for e in f if e["type"] or not absorbed(e)]


def _attach_line(ref: dict, events: list[dict], link_ms: int) -> tuple:
    """기준 줄(한 곳) → ('events', [사건], why) | ('held', reason, why)."""
    lines = ref.get("lines") or []
    ipc = [x for x in lines if x.get("ipc")]
    if ipc:     # CP 점: 같은 요청의 RSP(없으면 REQ) 뒤 link_ms 안 같은 슬롯(또는 모름) 실패 사건
        base = next((x for x in ipc if x["ipc"].get("dir") == "rsp"), ipc[0])
        if base["ipc"].get("ok"):      # 기준 응답이 성공 값(`vendor_ipc.success`) — 기준 줄 자체가 실패가 아니다
            return "held", "ineligible", "no_event_at_reference"
        t0, slot = ts(base["ts"]), base.get("phone")
        win = [e for e in events if t0 <= e["at"] <= t0 + timedelta(milliseconds=link_ms)
               and (slot is None or e.get("phone") in (slot, None))]
        typed = [e for e in win if e["type"]]
        if len({_top(e) for e in typed}) > 1:     # 창 안 유형 사건들의 1순위 원인이 다르면(한쪽만 있어도) 첫 사건을 고르지 않는다
            return "held", "ambiguous", "multiple_events"
        # 기준 바로 앞(ABSORB_SEC) 유형 없는 실패도 본다 — 벤더가 RSP 줄을 자기 요청의 RIL 오류 뒤에 찍는 경우(rsp_late 모양)
        pre = [e for e in events if not e["type"] and t0 - timedelta(seconds=ABSORB_SEC) <= e["at"] < t0
               and (slot is None or e.get("phone") in (slot, None))]
        fails = _fails(pre + win)
        if fails and not fails[0]["type"]:     # 기준 요청 자신이 DB에 없는 오류로 실패 — 뒤 다른 요청의 사건을 붙이지 않는다
            return "held", "symptom_not_found", "typeless_failure_within_link"
        if typed:
            return "events", typed[:1], "cp_point"
        return ("held", "symptom_not_found", "typeless_failure_within_link") if win else \
            ("held", "ineligible", "no_event_at_reference")
    refs = {k for k in (ref_key(x.get("line_ref")) for x in lines) if k}
    rils = [{**x["ril"], "phone": x.get("phone"), "ts": x["ts"]} for x in lines if x.get("ril")]
    # 근거 줄(증상·원인)이 기준 줄인 사건을 먼저, 없을 때만 창 안 조건 줄(§8-1) — 앞 사건 창이 뒤 사건 증상 줄을 덮어도 뒤 사건으로
    # 조건 줄로만 붙으면 채택해도 실패 지점은 found(자주 되풀이되는 조건 줄을 글자로 짚은 것일 수 있다 — `_COND` 표시, decide가 뗀다)
    same = [e for e in events if (e["lines"] | e.get("cause_lines", set())) & refs or (rils and _same_ril(e, rils))]
    why = "same_line"
    if not same:
        same, why = [e for e in events if e.get("cond_lines", set()) & refs], "same_line" + _COND
    if same:    # 점(같은 줄·같은 RIL 요청) — 한 줄에 유형 사건이 여럿이고 1순위 원인이 다르면 고르지 않는다
        typed = [e for e in same if e["type"]]
        if len({_top(e) for e in typed}) > 1:
            return "held", "ambiguous", "multiple_events"
        return ("events", typed[:1], why) if typed else ("held", "symptom_not_found", "same_line_typeless")
    return "held", "ineligible", "near_without_symptom"     # 근처: 문제 파악 유형이 있어야 붙인다(5-2)


def _attach_range(ref: dict, events: list[dict]) -> tuple:
    if ref["source"] == "step_order" or not ref.get("fail"):
        return "held", "ineligible", "range_end_unknown"
    if ref["source"] == "steps_file":
        return "held", "ineligible", "range_without_symptom"     # TC 파일 시각 구간: 문제 파악 유형이 있어야(5-2)
    fail = ts(ref["fail"])
    lo = ts(ref["start"]) if ref.get("start") else fail - timedelta(seconds=RANGE_PRE_SEC)
    last = _fails([e for e in events if lo <= e["at"] <= fail])[-1:]
    if last and not last[0]["type"]:     # FAIL에 가장 가까운 실패가 DB에 없는 오류 — 앞 스텝 조작의 사건을 채택하지 않는다
        return "held", "symptom_not_found", "typeless_failure_in_range"
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
        why = got[0][2]
        dec = _adopt(got[0][1], why.removesuffix(_COND))
        if why.endswith(_COND) and dec["state"] == "accepted":
            dec["cond_line"] = True      # 조건 줄로만 붙은 채택 — driver가 실패 지점을 confirmed로 올리지 않는다
        return dec
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
            **({"cond_line": True} if dec.get("cond_line") else {}), "checked": len(dec["events"]), "total": len(events), "events_total": len(typed),
            "events": [event_row(e, attached, result) for e in order]}


if __name__ == "__main__":     # 자기 점검: plugin/scripts에서 `python -m common.eligibility`(규칙별 시험은 tests/test_eligibility.py)
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
