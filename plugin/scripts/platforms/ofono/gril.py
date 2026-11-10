"""내장 짝 규칙 `gril` — upstream oFono `gril/` RIL trace 형식. 줄 모양 확인, 사내 확인 TODO(SITE:S26).

upstream oFono rilmodem(`gril/`)이 `ofonod` 출력에 남기는 RIL 요청·응답 trace(공개 소스의 출력 형식):
- 요청 `[<slot>,<serial>]> RIL_REQUEST_<NAME> <자유 문장>`
- 응답 `[<slot>,<serial>]< RIL_REQUEST_<NAME>[ <자유 문장>]`, 실패 응답 `... failed <ERROR>`
  (변형 `failed: X`·`failed; error: RIL_E_X`도 받는다. 이름이 없으면 `UNKNOWN`, `failed`가 없으면 `NONE`)
- 비요청 `[<slot>,UNSOL]< RIL_UNSOL_<NAME> ...`

이름은 Android RILJ·샘플 DB와 같게 쓴다: `RIL_REQUEST_X` → `X`, `RIL_UNSOL_X` → `UNSOL_X`. 접두사 없는 이름도 받는다
(벤더 요청). `<INVALID>`처럼 식별자 모양이 아닌 이름 줄과 슬롯 없는 옛 형식(`[%04d]>`, P2)은 주석을 달지 않는다.
슬롯은 `SLOT_PREFIX_RE`(줄 맨 앞 `[<slot>,` — 같은 trace가 upstream DBG 앞머리 `x.c:func() ` 뒤에 찍힌 줄도)·
`MODEM_PATH_RE`(D-Bus 모뎀 경로 `/ril_<n>`)로 `PhoneIdRules`가 원문 메시지에서 뽑는다(`platforms/ofono/__init__.py`,
TODO(SITE:S29)) — 짝 키 `(pid, phone_id, serial)`의 `phone_id`다.

- 주석: `{serial, dir, request, error, paired_ts, latency_ms}`(Android `ril.parse`와 같은 모양. 백엔드가 `proto: gril`을
  단다). 입력은 구성요소 `msg_format`이 앞머리를 뗀 본문이다(형식이 맞지 않으면 원문). `phone.strip`은 쓰지 않는다.
- 짝: Android `ril.pair`와 같은 의미 — 자기 주석(`proto == "gril"`)만 보고, 자기 주석 pid가 바뀌면 구간을 끊고, 키
  `(pid, phone_id, serial)`의 대기 요청 중 이름이 같은 가장 최근 요청과 짝짓는다(지연 ≥ 0만). 짝 없는 요청
  `observed_until` = 구간 안 같은 pid의 마지막 줄 시각. 파생 이벤트(`ril_error`·`ril_timeout`·`ril_no_response`)는
  `parse_logcat`이 `ril.yaml`로 만든다(proto 무관).

플랫폼 사이 import 금지(17-platforms §1-2)라 Android 짝 코드를 복제했다(공용화는 P2). 표준 라이브러리만 쓴다
(`platforms/ofono/__init__.py`가 불러온다 — guard 규칙 10 경로라 가볍게).
"""

from __future__ import annotations

import re

NAME = "gril"
TAGS = ("ofonod",)
NO_ERROR = "NONE"
UNKNOWN_ERROR = "UNKNOWN"

REQUEST_RE = re.compile(r"^\[(?P<slot>\d+),(?P<serial>\d{1,10})\]>\s*(?:RIL_REQUEST_)?(?P<request>[A-Z][A-Z0-9_]*)(?!\w)")
RESPONSE_RE = re.compile(
    r"^\[(?P<slot>\d+),(?P<serial>\d{1,10})\]<\s*(?:RIL_REQUEST_)?(?P<request>[A-Z][A-Z0-9_]*)(?!\w)(?P<rest>.*)$")
UNSOL_RE = re.compile(r"^\[(?P<slot>\d+),UNSOL\]<\s*(?:RIL_)?(?P<request>[A-Z][A-Z0-9_]*)(?!\w)")
# 응답 나머지(`rest`)에. 오류 이름은 식별자 모양만(`failed Generic`처럼 이어지면 이름 없음 → UNKNOWN)
FAILED_RE = re.compile(r"^\s*failed\b[;:]?\s*(?:error:\s*)?(?:(?:RIL_E_)?(?P<error>[A-Z][A-Z0-9_]*)(?!\w))?")
# 슬롯 표기(PhoneIdRules, 그룹 1 = 슬롯): 줄 맨 앞 `[<slot>,<serial>|UNSOL]<>`(upstream DBG 앞머리 `x.c:func() ` 뒤도 —
# 같은 trace가 DBG로 찍힌 줄. 앞머리 모양은 `msgformat.file_func`와 같다), D-Bus 모뎀 경로 `/ril_<n>`
SLOT_PREFIX_RE = re.compile(r"^(?:[\w./-]+\.c:\w+\(\)\s?)?\[(\d+),(?:\d{1,10}|UNSOL)\][<>]")
MODEM_PATH_RE = re.compile(r"(?<![\w/])/ril_(\d+)(?!\w)")


def annotate(tag: str, msg: str, tags, phone=None) -> dict | None:
    """gril trace 줄이면 `{serial, dir, request, error, paired_ts, latency_ms}`, 아니면 None. `dir`: req/resp/unsol."""
    if tag not in tags:
        return None
    hit = REQUEST_RE.match(msg)
    if hit:
        return _ann(int(hit.group("serial")), "req", hit.group("request"), None)
    hit = RESPONSE_RE.match(msg)
    if hit:
        failed = FAILED_RE.match(hit.group("rest"))
        error = (failed.group("error") or UNKNOWN_ERROR) if failed else NO_ERROR
        return _ann(int(hit.group("serial")), "resp", hit.group("request"), error)
    hit = UNSOL_RE.match(msg)
    if hit:
        return _ann(None, "unsol", hit.group("request"), None)
    return None


def _ann(serial, direction, request, error) -> dict:
    return {"serial": serial, "dir": direction, "request": request, "error": error, "paired_ts": None,
            "latency_ms": None}


def _own(ann) -> bool:
    return bool(ann) and ann.get("proto") == NAME


def pair(records: list[dict]) -> None:
    """한 수집 구간의 레코드(시간순, 모든 데몬 줄)를 제자리에서 짝짓는다. 자기 주석만 본다(`PairProtocol` 계약)."""
    segments, current, radio_pid = [], [], None
    for rec in records:
        if _own(rec.get("ril")):
            if radio_pid is not None and rec["pid"] != radio_pid:     # ofonod 재시작: serial이 다시 쓰여도 잇지 않는다
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
                req["ril"]["paired_ts"], req["ril"]["latency_ms"] = rec["ts"], latency
                ann["paired_ts"], ann["latency_ms"] = req["ts"], latency
                break
    # 관측 끝 = 구간 안 그 요청과 같은 pid의 마지막 줄(다른 데몬 줄은 ofonod 흐름이 이어졌다는 근거가 아니다)
    last_by_pid: dict = {}
    for rec in records:
        last_by_pid[rec["pid"]] = rec["ts"]
    for rec in records:
        ann = rec.get("ril")
        if _own(ann) and ann["dir"] == "req" and ann["paired_ts"] is None:
            ann["observed_until"] = last_by_pid[rec["pid"]]
