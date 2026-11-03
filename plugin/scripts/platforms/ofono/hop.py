"""설정 정의 짝 규칙 kind `hop` — serial 없는 데몬 사이 연결(이름·시간 창). 형식 가정(placeholder), TODO(SITE:S26)

site-defaults `platform.others.ofono.protocols.<이름>: {kind: hop, upstream, tags, request, response, fold, window_ms}`로
위 층 짝 규칙(`upstream`, 예: 내장 `gril`)의 요청·응답 줄과, 같은 요청을 serial 없이 남기는 아래 데몬 줄을 요청 이름과
시간 창으로 잇는다(17-platforms §9-3, K20). 기본은 꺼져 있다(설정이 없으면 프로토콜 없음).

- `upstream`(필수): 위 층 짝 규칙 이름(`^[a-z][a-z0-9_]*$`, 자기 이름 아님). 프로토콜 목록에서 이 규칙보다 **앞**이어야
  한다 — `PairProtocol.reads`로 레지스트리가 확인한다. 그래서 위 `pair`가 이름·짝을 채운 뒤에 이 `pair`가 돈다.
- `tags`(필수, 비어 있지 않음): 아래 데몬 ident.
- `request`·`response`(하나 이상, `re.search`): 이름 그룹 `name` 필수. 접두사 차이는 정규식으로 흡수한다
  (`(?:RIL_REQUEST_)?(?P<name>…)`). `name`이 식별자 모양(`pairing.TOKEN_RE`)이 아니면 다음 정규식을 본다(요청 먼저).
  입력은 구성요소 `msg_format`이 앞머리를 뗀 본문이다(형식이 맞지 않으면 원문).
- `fold`(기본 false): 이름을 대소문자·`_` 무시로 비교한다(`SETUP_DATA_CALL` = `SetupDataCall`).
- `window_ms`(기본 50, 1~1000): 요청은 아래 줄이 위 요청 뒤 0~창 ms, 응답은 아래 줄이 위 응답 앞 0~창 ms
  (아래 데몬은 위로 응답을 올리기 전에 찍는다). 창이 클수록 가짜 연결이 는다 — 100 이하 권장.
- 주석은 **아래 줄에만**: `{serial: None, dir: hop_req|hop_resp, request: <이름>, error: None, paired_ts: None,
  latency_ms: None}`(백엔드가 `proto: <이름>`을 단다). 연결되면 `serial`·`request` = 위 주석 값(정규 이름),
  `paired_ts` = 위 줄 시각, `latency_ms` = 시각 차(`--mask`면 `parse_logcat`이 아래 줄 `serial`을 null로 — 위 줄
  복사본이라 그 줄에서 가린 값인지 대조할 수 없다, 08-safety §8). 위 주석은 읽기만 한다(위 규칙 소유). 연결 못 한 줄은 그대로다
  (`observed_until` 없음 — 아래 줄이 없는 원인(로그 수준·다른 경로·캡처 경계)을 구분할 수 없다).
- 짝: 일대일, 시각 차가 가장 작은 쌍부터(nearest-first, 같은 차이면 아래 줄 순서). 한 줄은 한 번만 쓴다. `phone_id`는
  둘 다 있을 때만 같아야 한다. 같은 이름이 몰리는 구간은 FIFO와 다를 수 있다(FIFO 옵션은 P2).
- 파생 이벤트는 없다: `dir`가 req·resp가 아니라 `parse_logcat` RIL 파생 이벤트·step event·`s0_stats`에 걸리지 않는다.
  미연결 수는 `tools/site_checks.py` o2.pairs가 보인다.

표준 라이브러리와 `platforms.base`·`.pairing`만 쓴다(`platforms/ofono/__init__.py`가 불러온다).
"""

from __future__ import annotations

import bisect
import re
from datetime import timedelta
from functools import partial

from platforms.base import PairProtocol, cfg_compile, cfg_mapping, config_error

from .pairing import TOKEN_RE, tag_list

KIND = "hop"
KEYS = ("kind", "upstream", "tags", "request", "response", "fold", "window_ms")
DEFAULT_WINDOW_MS = 50
MAX_WINDOW_MS = 1000
DIRS = ("hop_req", "hop_resp")
UPSTREAM_DIR = {"hop_req": "req", "hop_resp": "resp"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")     # 짝 규칙 이름(레지스트리 `NAME_RE`와 같다)


def _pattern(conf: dict, key: str, path: str) -> re.Pattern | None:
    if key not in conf:
        return None
    at = f"{path}.{key}"
    pattern = cfg_compile(conf[key], at, groups=0)
    if "name" not in pattern.groupindex:
        raise config_error(at, "이름 그룹 (?P<name>...)이 필요합니다.")
    return pattern


def build(name: str, conf: dict, path: str) -> PairProtocol:
    """`protocol_kinds`의 factory. 설정 블록을 검증해 `PairProtocol`을 준다(오류는 `PlatformConfigError`)."""
    conf = cfg_mapping(conf, path, KEYS)
    for key in ("upstream", "tags"):
        if key not in conf:
            raise config_error(path, f"'{key}'가 필요합니다.")
    upstream = conf["upstream"]
    if not isinstance(upstream, str) or not NAME_RE.fullmatch(upstream):
        raise config_error(f"{path}.upstream", f"짝 규칙 이름(^[a-z][a-z0-9_]*$)이어야 합니다: {upstream!r}")
    if upstream == name:
        raise config_error(f"{path}.upstream", "자기 이름은 쓸 수 없습니다.")
    tags = tag_list(conf["tags"], f"{path}.tags")
    if "request" not in conf and "response" not in conf:
        raise config_error(path, "'request'·'response' 중 하나 이상이 필요합니다.")
    request, response = _pattern(conf, "request", path), _pattern(conf, "response", path)
    fold = conf.get("fold", False)
    if not isinstance(fold, bool):
        raise config_error(f"{path}.fold", f"true/false여야 합니다: {fold!r}")
    window = conf.get("window_ms", DEFAULT_WINDOW_MS)
    if not isinstance(window, int) or isinstance(window, bool) or not 1 <= window <= MAX_WINDOW_MS:
        raise config_error(f"{path}.window_ms", f"1~{MAX_WINDOW_MS} 정수(ms)여야 합니다: {window!r}")
    return PairProtocol(name=name, default_tags=frozenset(tags), annotate=partial(_annotate, request, response),
                        pair=partial(_pair, name, upstream, fold, window), reads=(upstream,))


def _annotate(request, response, tag, msg, tags, phone=None) -> dict | None:
    if tag not in tags:
        return None
    for direction, pattern in (("hop_req", request), ("hop_resp", response)):
        hit = pattern.search(msg) if pattern is not None else None
        value = hit.group("name") if hit else None
        if not value or not TOKEN_RE.fullmatch(value):
            continue
        return {"serial": None, "dir": direction, "request": value, "error": None, "paired_ts": None,
                "latency_ms": None}
    return None


def _key(name: str, fold: bool) -> str:
    return name.replace("_", "").lower() if fold else name


def _pair(name: str, upstream: str, fold: bool, window_ms: int, records: list[dict]) -> None:
    """한 수집 구간의 레코드를 제자리에서 잇는다. 자기 주석(`proto == name`)만 바꾸고 위 주석은 읽기만 한다."""
    window = timedelta(milliseconds=window_ms)
    for direction in DIRS:
        uppers: dict[str, list[tuple]] = {}          # 이름 키 → [(시각, 순번)], 시각순
        lowers: list[int] = []
        for i, rec in enumerate(records):
            ann = rec.get("ril")
            if not ann or not isinstance(ann.get("request"), str):
                continue
            if ann.get("proto") == upstream and ann["dir"] == UPSTREAM_DIR[direction]:
                uppers.setdefault(_key(ann["request"], fold), []).append((rec["_dt"], i))
            elif ann.get("proto") == name and ann["dir"] == direction:
                lowers.append(i)
        if not uppers or not lowers:
            continue
        times = {}
        for key, items in uppers.items():
            items.sort()
            times[key] = [dt for dt, _ in items]
        candidates = []                               # (시각 차, 아래 순번, 위 순번)
        for i in lowers:
            low = records[i]
            key = _key(low["ril"]["request"], fold)
            if key not in uppers:
                continue
            dt = low["_dt"]
            start, end = (dt - window, dt) if direction == "hop_req" else (dt, dt + window)
            dts = times[key]
            for k in range(bisect.bisect_left(dts, start), bisect.bisect_right(dts, end)):
                up_dt, j = uppers[key][k]
                up_phone, low_phone = records[j].get("phone_id"), low.get("phone_id")
                if up_phone is not None and low_phone is not None and up_phone != low_phone:
                    continue
                candidates.append((abs(dt - up_dt), i, j))
        used_low, used_up = set(), set()
        for delta, i, j in sorted(candidates):
            if i in used_low or j in used_up:
                continue
            used_low.add(i)
            used_up.add(j)
            ann, up = records[i]["ril"], records[j]["ril"]
            ann["serial"], ann["request"] = up["serial"], up["request"]
            ann["paired_ts"], ann["latency_ms"] = records[j]["ts"], round(delta.total_seconds() * 1000)
