"""RIL 줄 해석과 요청/응답 페어링 (04-parser-matching.md §5.8 (2), 07-workflow.md §Step 3).

페어링 키는 `(pid, phone_id, serial)`이고 `phone_id`를 못 뽑으면 `(pid, None, serial)`
이다. phone 프로세스 재시작(pid 변경)이나 슬롯별 serial 충돌로 요청·응답이 잘못
짝지어지지 않게 하기 위해서다. 같은 키에 기다리는 요청이 여럿이면 요청 이름이 같은
가장 최근 요청과 짝짓는다.

페어링은 윈도우를 자르기 **전에** 파일 전체로 한다. 응답 없음·에러·지연 이벤트는
`ril.yaml`(timeout)을 아는 `parse_logcat.py`가 이 결과로 만든다.

합성 로그 모양: 요청 `[n]> iccIO: SIM_IO …`, 숫자 오류 `[n]< REQ error <n>`(RadioError 이름, 같은 serial `RilRequest`
줄 이름이 있으면 그것), RadioConfig·RadioConfigResponseAidl 짝.

RILJ 출력 형식은 placeholder다 — TODO(SITE:S9). 벤더 RIL 태그·슬롯 표기는 `platform.ril.tags`·`platform.log.phone_id`로 바꾼다.

벤더 RIL 층 연결(`link_vendor`, 선택 `platform.ril.vendor`)은 짝 맞춤 뒤 전체 레코드로 RILJ 요청·응답에
`hal`을 단다(04-parser-matching.md §5.8 (2)). 벤더 줄에는 `ril`을 달지 않는다 — 달면 `pair()`의 pid 분할이 RILJ 짝을 깬다.
"""

from __future__ import annotations

import bisect
import re
from datetime import timedelta

from . import logcat
from platforms.base import DEFAULT_LINK_MS, VendorRules  # noqa: F401  (계약 타입, 기존 경로로 다시 내보낸다)

# RadioConfig·RadioConfigResponseAidl: 모뎀 설정 요청·응답 짝(`[PHONE]` 없음, RILJ와 같은 pid, placeholder).
# RilRequest는 짝 태그가 아니다 — RILJ 응답을 되풀이하므로 짝지으면 짝 없는 중복 `ril_error`가 생긴다. 이름 연결만 한다(`_link_names`).
RIL_TAGS = {"RILJ", "RadioConfig", "RadioConfigResponseAidl"}

REQUEST_RE = re.compile(r"^\[(?P<serial>\d+)\]>\s*(?:iccIO:\s*)?(?P<request>[A-Z][A-Z0-9_]*)")
RESPONSE_RE = re.compile(r"^\[(?P<serial>\d+)\]<\s*(?P<request>[A-Z][A-Z0-9_]*)(?P<rest>.*)$")
UNSOL_RE = re.compile(r"^\[UNSL\]<\s*(?P<request>[A-Z][A-Z0-9_]*)")
NO_ERROR = "NONE"
ERROR_RE = re.compile(r"\berror[=:]\s*(?P<error>[A-Z][A-Z0-9_]*)")
# AIDL RILJ 형식 `[0164]< SIM_IO error 2 [PHONE0]`: 숫자 RadioError.
ERROR_NUM_RE = re.compile(r"^\s*error\s+(?P<code>\d+)\b")      # 응답 이름 바로 뒤만
ERROR_NUM_LINE_RE = re.compile(r"\]<\s*[A-Z][A-Z0-9_]*\s+error\s+\d+\b")
# AOSP `RadioError` 이름 중 4개만 둔다(사내 확인 TODO(SITE:S9)).
# 그 밖의 숫자는 `RADIO_ERROR_<n>`이고, 같은 serial `RilRequest` 줄의 이름이 있으면 그것을 쓴다.
RADIO_ERROR = {0: NO_ERROR, 1: "RADIO_NOT_AVAILABLE", 2: "GENERIC_FAILURE", 6: "REQUEST_NOT_SUPPORTED", 17: "NO_SUCH_ELEMENT"}
# RilRequest: `[0158]< SIM_OPEN_CHANNEL error: com.android.internal.telephony.CommandException: NO_SUCH_ELEMENT …`
NAME_TAG = "RilRequest"
NAME_RE = re.compile(r"^\[(?P<serial>\d+)\]<\s*(?P<request>[A-Z][A-Z0-9_]*) error: \S*CommandException: (?P<name>[A-Z][A-Z0-9_]*)")
NAME_LINK = timedelta(milliseconds=10)


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
        return _ann(int(hit.group("serial")), "resp", hit.group("request"), _error(hit.group("rest")))
    hit = UNSOL_RE.match(body)
    if hit:
        return _ann(None, "unsol", hit.group("request"), None)
    return None


def _error(rest: str) -> str:
    err = ERROR_RE.search(rest)
    if err:
        return err.group("error")
    num = ERROR_NUM_RE.search(rest)
    if num:
        code = int(num.group("code"))
        return RADIO_ERROR.get(code, f"RADIO_ERROR_{code}")
    return NO_ERROR


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
    # 자기 주석만 본다(`PairProtocol` 계약): 다른 프로토콜 주석(`proto` 키가 있는 것)은 분할·짝에 쓰지 않는다.
    segments, current, radio_pid = [], [], None
    for rec in records:
        if _own(rec.get("ril")):
            if radio_pid is not None and rec["pid"] != radio_pid:
                segments.append(current)
                current = []
            radio_pid = rec["pid"]
        current.append(rec)
    if current:
        segments.append(current)
    for segment in segments:
        _pair_segment(segment)
    _link_names(records)


def _link_names(records: list[dict]) -> None:
    """숫자 오류(`error <n>`) RILJ 응답에 같은 pid·serial·요청의 `RilRequest` 줄(±10ms) 이름을 단다.
    RilRequest 줄 자체에는 `ril`을 달지 않는다."""
    names: dict[tuple, list] = {}
    for rec in records:
        if rec.get("tag") == NAME_TAG:
            hit = NAME_RE.match(rec.get("msg") or "")
            if hit:
                names.setdefault((rec["pid"], int(hit.group("serial")), hit.group("request")), []).append(
                    (rec["_dt"], hit.group("name")))
    if not names:
        return
    for rec in records:
        ann = rec.get("ril")
        if not _own(ann) or ann["dir"] != "resp" or ann["serial"] is None:
            continue
        if not ERROR_NUM_LINE_RE.search(rec.get("msg") or "") or ann["error"] == NO_ERROR:
            continue
        for dt, name in names.get((rec["pid"], ann["serial"], ann["request"]), []):
            if abs(dt - rec["_dt"]) <= NAME_LINK:
                ann["error"] = name
                break


def _own(ann) -> bool:
    """이 프로토콜(ril)의 주석인가. android 주석에는 `proto` 키가 없다(다른 프로토콜만 단다)."""
    return bool(ann) and "proto" not in ann


def _pair_segment(records: list[dict]) -> None:
    pending: dict[tuple, list[dict]] = {}
    for rec in records:
        ann = rec.get("ril")
        if not _own(ann) or ann["serial"] is None:
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
    # 관측 끝 = 세그먼트 안 그 요청과 같은 pid(RIL 프로세스)의 마지막 줄. 다른 프로세스 줄은 RILJ 흐름이
    # 이어졌다는 근거가 아니다(phone 프로세스 크래시 뒤 다른 pid 줄로 응답 없음을 단정하지 않는다).
    last_by_pid: dict = {}
    for rec in records:
        last_by_pid[rec["pid"]] = rec["ts"]
    for rec in records:
        ann = rec.get("ril")
        if _own(ann) and ann["dir"] == "req" and ann["paired_ts"] is None:
            ann["observed_until"] = last_by_pid[rec["pid"]]


# -- 벤더 RIL 층 (선택). 규칙 타입 `VendorRules`·기본 `DEFAULT_LINK_MS`는 `platforms/base.py` ----------------

# ponytail: 고정 창(HAL 앞 500ms·커버 ±60s·응답 토큰과 짝 있는 HAL 끝 = 짝+1s/짝 없으면 토큰 120s) — 사내 로그 분포로 조정, 단말마다 다르면 설정 키로
HAL_BEFORE = timedelta(milliseconds=500)
COVER = timedelta(seconds=60)
TOKEN_AFTER_RESP = timedelta(seconds=1)
TOKEN_UNPAIRED = timedelta(seconds=120)


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
                        # RILJ는 mSerial % 10000을 찍는다 — serial·token 모두 맞춘다(이미 4자리면 그대로)
                        store.setdefault(int(value) % 10000, []).append(rec["_dt"])
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
