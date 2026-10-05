"""RIL 줄 해석과 요청/응답 페어링 (04-parser-matching.md §5.8 (2), 07-workflow.md §Step 3).

페어링 키는 `(pid, phone_id, serial)`이고 `phone_id`를 못 뽑으면 `(pid, None, serial)`
이다. phone 프로세스 재시작(pid 변경)이나 슬롯별 serial 충돌로 요청·응답이 잘못
짝지어지지 않게 하기 위해서다. 같은 키에 기다리는 요청이 여럿이면 요청 이름이 같은
가장 최근 요청과 짝짓는다.

페어링은 윈도우를 자르기 **전에** 파일 전체로 한다. 응답 없음·에러·지연 이벤트는
`ril.yaml`(timeout)을 아는 `parse_logcat.py`가 이 결과로 만든다.

RILJ 출력 형식은 placeholder다 — TODO(SITE:S9). 벤더 RIL 태그·슬롯 표기는 `platform.ril.tags`·`platform.log.phone_id`로 바꾼다.
"""

from __future__ import annotations

import re

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
