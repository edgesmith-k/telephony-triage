"""RIL 줄 해석과 요청/응답 페어링 (04-parser-matching.md §5.8 (2), 07-workflow.md §Step 3).

페어링 키는 `(pid, phone_id, serial)`이고 `phone_id`를 못 뽑으면 `(pid, None, serial)`
이다. phone 프로세스 재시작(pid 변경)이나 슬롯별 serial 충돌로 요청·응답이 잘못
짝지어지지 않게 하기 위해서다. 같은 키에 기다리는 요청이 여럿이면 요청 이름이 같은
가장 최근 요청과 짝짓는다.

페어링은 윈도우를 자르기 **전에** 파일 전체로 한다. 응답 없음·에러·지연 이벤트는
`ril.yaml`(timeout)을 아는 `parse_logcat.py`가 이 결과로 만든다.

RILJ 출력 형식은 placeholder다 — TODO(SITE:S9). 벤더 RIL 태그·슬롯 표기는 `platform.ril.tags`·`platform.log.phone_id`로 바꾼다.

벤더 RIL 층 연결(`link_vendor`, 선택 `platform.ril.vendor`)은 짝 맞춤 뒤 전체 레코드로 RILJ 요청·응답에
`hal`을 단다(04-parser-matching.md §5.8 (2)). 벤더 줄에는 `ril`을 달지 않는다 — 달면 `pair()`의 pid 분할이 RILJ 짝을 깬다.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from datetime import timedelta

from . import logcat

RIL_TAGS = {"RILJ"}

REQUEST_RE = re.compile(r"^\[(?P<serial>\d+)\]>\s*(?P<request>[A-Z][A-Z0-9_]*)")
RESPONSE_RE = re.compile(r"^\[(?P<serial>\d+)\]<\s*(?P<request>[A-Z][A-Z0-9_]*)(?P<rest>.*)$")
UNSOL_RE = re.compile(r"^\[UNSL\]<\s*(?P<request>[A-Z][A-Z0-9_]*)")
ERROR_RE = re.compile(r"\berror[=:]\s*(?P<error>[A-Z][A-Z0-9_]*)")

NO_ERROR = "NONE"


def parse(tag: str, msg: str, tags=RIL_TAGS, phone: logcat.PhoneIdRules = logcat.DEFAULT_PHONE_RULES) -> dict | None:
    """`tags`·`phone`은 `platform` 설정값이다 (기본은 코드 기본값). RIL 줄이면 `{serial, dir, request, error, paired_ts, latency_ms}`, 아니면 None.
    `dir`: `req` / `resp` / `unsol`. 응답에 에러 표기가 없으면 `error: "NONE"`."""
    if tag not in tags:
        return None
    body = phone.strip(msg)
    hit = REQUEST_RE.match(body)
    if hit:
        return _ann(int(hit.group("serial")), "req", hit.group("request"), None)
    hit = RESPONSE_RE.match(body)
    if hit:
        err = ERROR_RE.search(hit.group("rest"))
        return _ann(
            int(hit.group("serial")),
            "resp",
            hit.group("request"),
            err.group("error") if err else NO_ERROR,
        )
    hit = UNSOL_RE.match(body)
    if hit:
        return _ann(None, "unsol", hit.group("request"), None)
    return None


def _ann(serial, direction, request, error) -> dict:
    return {
        "serial": serial,
        "dir": direction,
        "request": request,
        "error": error,
        "paired_ts": None,
        "latency_ms": None,
    }


def pair(records: list[dict]) -> None:
    """한 파일의 레코드(파일 순서)를 제자리에서 짝짓는다.

    레코드는 `ril`, `pid`, `phone_id`, `ts`, `_dt` 키를 가진다. 짝을 찾으면
    양쪽 `ril.paired_ts`(상대편 시각)와 `ril.latency_ms`를 채운다.
    """
    # Split observations on radio-process restart, even if serials are reused.
    segments, current, radio_pid = [], [], None
    for rec in records:
        if rec.get("ril"):
            if radio_pid is not None and rec["pid"] != radio_pid:
                segments.append(current)
                current = []
            radio_pid = rec["pid"]
        current.append(rec)
    if current:
        segments.append(current)
    for segment in segments:
        _pair_segment(segment)


def _pair_segment(records: list[dict]) -> None:
    pending: dict[tuple, list[dict]] = {}
    for rec in records:
        ann = rec.get("ril")
        if not ann or ann["serial"] is None:
            continue
        key = (rec["pid"], rec["phone_id"], ann["serial"])
        if ann["dir"] == "req":
            pending.setdefault(key, []).append(rec)
            continue
        stack = pending.get(key) or []
        for index in range(len(stack) - 1, -1, -1):
            if stack[index]["ril"]["request"] == ann["request"]:
                req = stack.pop(index)
                latency = round((rec["_dt"] - req["_dt"]).total_seconds() * 1000)
                if latency < 0:
                    continue
                req["ril"]["paired_ts"] = rec["ts"]
                req["ril"]["latency_ms"] = latency
                ann["paired_ts"] = req["ts"]
                ann["latency_ms"] = latency
                break
    for rec in records:
        ann = rec.get("ril")
        if ann and ann["dir"] == "req" and ann["paired_ts"] is None:
            ann["observed_until"] = records[-1]["ts"]


# -- 벤더 RIL 층 (선택) ----------------------------------------------------------

DEFAULT_LINK_MS = 2000
# ponytail: 고정 창(HAL 앞 500ms·커버 ±60s·응답 토큰과 짝 있는 HAL 끝 = 짝+1s/짝 없으면 토큰 120s) — 사내 실제 로그 분포로 조정, 단말마다 다르면 설정 키로
HAL_BEFORE = timedelta(milliseconds=500)
COVER = timedelta(seconds=60)
TOKEN_AFTER_RESP = timedelta(seconds=1)
TOKEN_UNPAIRED = timedelta(seconds=120)


@dataclass(frozen=True)
class VendorRules:
    """`layers`: `((tag, (패턴, ...)), ...)` — 패턴마다 이름 그룹 `serial`·`token` 중 정확히 하나(값은 10진 숫자).
    `coverage_tags`: 정규식 없이 "수집 살아 있음"만 표시하는 태그(정확한 이름)."""
    layers: tuple
    link_ms: int = DEFAULT_LINK_MS
    coverage_tags: frozenset = frozenset()


def _within(times: list, lo, hi) -> bool:
    i = bisect.bisect_left(times, lo)
    return i < len(times) and times[i] <= hi


def link_vendor(records: list[dict], rules: VendorRules) -> None:
    """짝 맞춤이 끝난 전체 레코드(모든 스트림)에서 RILJ 요청·짝 응답의 `ril`에 `hal`을 제자리에서 단다.

    값: `responded`(같은 serial의 응답 토큰) / `reached`(HAL 줄만) / `not_reached`(±60s에 벤더·coverage 줄은
    있는데 이 serial 없음) / `unknown`(±60s에 벤더 줄이 없음 = 수집 안 됨). 짝 없는 응답에는 달지 않는다.
    """
    layers = dict(rules.layers)
    hal: dict[int, list] = {}
    tok: dict[int, list] = {}
    seen = []
    for rec in records:
        tag = rec["tag"]
        if tag in layers:
            seen.append(rec["_dt"])
            for pattern in layers[tag]:
                hit = pattern.search(rec["msg"])
                if hit:
                    key, store = ("serial", hal) if "serial" in pattern.groupindex else ("token", tok)
                    value = hit.group(key)
                    if value is not None and value.isascii() and value.isdigit():  # 10진 숫자만, 그 밖(0x29 등)은 무시
                        store.setdefault(int(value), []).append(rec["_dt"])
                    break
        elif tag in rules.coverage_tags:
            seen.append(rec["_dt"])
    for times in (seen, *hal.values(), *tok.values()):
        times.sort()
    link = timedelta(milliseconds=rules.link_ms)
    for rec in records:
        ann = rec.get("ril")
        if not ann or ann["serial"] is None or ann["dir"] not in ("req", "resp"):
            continue
        if ann["dir"] == "req":
            start = rec["_dt"]
        elif ann["latency_ms"] is not None:
            start = rec["_dt"] - timedelta(milliseconds=ann["latency_ms"])
        else:
            continue
        if ann["latency_ms"] is not None:  # 짝 있으면 HAL·토큰 창 모두 응답 + 1s까지
            end = start + timedelta(milliseconds=ann["latency_ms"]) + TOKEN_AFTER_RESP
            hal_end = max(start + link, end)
        else:
            end, hal_end = start + TOKEN_UNPAIRED, start + link
        if _within(tok.get(ann["serial"], []), start, end):
            ann["hal"] = "responded"
        elif _within(hal.get(ann["serial"], []), start - HAL_BEFORE, hal_end):
            ann["hal"] = "reached"
        elif _within(seen, start - COVER, start + COVER):
            ann["hal"] = "not_reached"
        else:
            ann["hal"] = "unknown"
