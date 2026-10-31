"""설정 정의 짝 규칙 kind `regex` — 형식 가정(placeholder). TODO(SITE:S26)

site-defaults `platform.others.ofono.protocols.<이름>: {kind: regex, tags, request, response}`로 site가 이름 지은
짝 규칙을 만든다(17-platforms §9, `SPEC.protocol_kinds`). 기본은 꺼져 있다(설정이 없으면 프로토콜 없음).

- `tags`(필수, 비어 있지 않음): 이 규칙을 볼 ident. 여러 구성요소(데몬)의 ident를 섞어도 된다 — 백엔드는 한
  수집(스트림) 구간의 레코드 전체를 `pair`에 넘기므로 데몬 사이(다른 pid·tag) 짝이 된다.
- `request`·`response`(필수 정규식, `re.search`): 이름 그룹 `serial`(10진 숫자) 필수. 선택 그룹: 요청 `name`,
  응답 `name`·`error`. 그 밖 이름 그룹은 무시한다. 입력은 구성요소 `msg_format`이 앞머리를 뗀 본문이다.
  한 줄에 요청을 먼저 본다. `serial`이 10진 숫자가 아니거나 `name`·`error` 값이 식별자 모양(`TOKEN_RE`: 글자로
  시작, 글자·숫자·`_`·`.`, 128자 이하)이 아니면 그 줄은 주석을 달지 않는다. 숫자로 시작하는 값(전화번호·IMSI·IP)과
  `:`이 든 값(MAC)은 여기서 막고, `--mask`면 `parse_logcat`이 `proto` 주석의 `request`·`error`를 한 번 더 마스킹한다.
- 주석: `{serial, dir, request, error, paired_ts, latency_ms}`(백엔드가 `proto: <이름>`을 단다).
- 짝: 키는 `serial`(같은 수집 구간). 나중 요청이 같은 serial의 대기 요청을 대신한다. 응답에 `name`이 없으면
  요청 이름을 채운다(반대도). 짝 없는 요청은 `observed_until` = 그 구간의 가장 늦은 레코드 시각(태그 무관, "수집이
  살아 있던 끝") → `ril.yaml`에 이름이 있으면 `ril_no_response`를 낼 수 있다. 나중 요청에 밀려난 요청은
  `observed_until`을 받지 않는다(대화 키가 없어 연결별 serial 충돌일 수 있으므로 응답 없음으로 단정하지 않는다).
  대화 키(연결별 serial 범위)는 아직 없다 — 필요 여부는 S26에서 정한다.

표준 라이브러리와 `platforms.base`만 쓴다(`platforms/ofono/__init__.py`가 불러온다). 두 번째 플랫폼이 쓰게 되면
공용 모듈로 옮긴다.
"""

from __future__ import annotations

import re
from functools import partial

from platforms.base import PairProtocol, cfg_compile, cfg_list, cfg_mapping, config_error

KIND = "regex"
KEYS = ("kind", "tags", "request", "response")
TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.]{0,127}$")


def _pattern(conf: dict, key: str, path: str) -> re.Pattern:
    at = f"{path}.{key}"
    pattern = cfg_compile(conf[key], at, groups=0)
    if "serial" not in pattern.groupindex:
        raise config_error(at, "이름 그룹 (?P<serial>...)이 필요합니다.")
    return pattern


def build(name: str, conf: dict, path: str) -> PairProtocol:
    """`protocol_kinds`의 factory. 설정 블록을 검증해 `PairProtocol`을 준다(오류는 `PlatformConfigError`)."""
    conf = cfg_mapping(conf, path, KEYS)
    for key in ("tags", "request", "response"):
        if key not in conf:
            raise config_error(path, f"'{key}'가 필요합니다.")
    tpath = f"{path}.tags"
    tags = []
    for i, tag in enumerate(cfg_list(conf["tags"], tpath, non_empty=True)):
        if not isinstance(tag, str) or not tag.strip():
            raise config_error(f"{tpath}[{i}]", "비어 있지 않은 문자열이어야 합니다.")
        tags.append(tag)
    request, response = _pattern(conf, "request", path), _pattern(conf, "response", path)
    return PairProtocol(name=name, default_tags=frozenset(tags), annotate=partial(_annotate, request, response),
                        pair=partial(_pair, name))


def _group(hit: re.Match, key: str) -> tuple[bool, str | None]:
    """`(쓸 수 있음, 값)`. 그룹이 없거나 비면 None, 식별자 모양이 아니면 쓸 수 없음."""
    value = hit.groupdict().get(key)
    if not value:
        return True, None
    return bool(TOKEN_RE.fullmatch(value)), value


def _annotate(request: re.Pattern, response: re.Pattern, tag, msg, tags, phone=None) -> dict | None:
    if tag not in tags:
        return None
    for direction, pattern in (("req", request), ("resp", response)):
        hit = pattern.search(msg)
        if not hit:
            continue
        serial = hit.group("serial") or ""
        ok_name, name = _group(hit, "name")
        ok_error, error = _group(hit, "error") if direction == "resp" else (True, None)
        if not (serial.isdecimal() and ok_name and ok_error):
            continue
        return {"serial": int(serial), "dir": direction, "request": name, "error": error,
                "paired_ts": None, "latency_ms": None}
    return None


def _own(ann, name: str) -> bool:
    return bool(ann) and ann.get("proto") == name


def _pair(name: str, records: list[dict]) -> None:
    """한 수집 구간의 레코드(시간순)를 제자리에서 짝짓는다. 자기 주석(`proto == name`)만 본다."""
    pending: dict[int, dict] = {}
    replaced: set[int] = set()      # 밀려난 요청 레코드의 id — observed_until을 주지 않는다
    for rec in records:
        ann = rec.get("ril")
        if not _own(ann, name):
            continue
        if ann["dir"] == "req":
            old = pending.get(ann["serial"])
            if old is not None:
                replaced.add(id(old))
            pending[ann["serial"]] = rec
            continue
        req = pending.get(ann["serial"])
        if req is None:
            continue
        latency = round((rec["_dt"] - req["_dt"]).total_seconds() * 1000)
        if latency < 0:
            continue
        del pending[ann["serial"]]
        req_ann = req["ril"]
        req_ann["paired_ts"], req_ann["latency_ms"] = rec["ts"], latency
        ann["paired_ts"], ann["latency_ms"] = req["ts"], latency
        if ann["request"] is None:
            ann["request"] = req_ann["request"]
        elif req_ann["request"] is None:
            req_ann["request"] = ann["request"]
    if not records:
        return
    last_ts = max(records, key=lambda rec: rec["_dt"])["ts"]   # 작은 뒤로 감김이 있어도 구간의 가장 늦은 시각
    for rec in records:
        ann = rec.get("ril")
        if (_own(ann, name) and ann["dir"] == "req" and ann["paired_ts"] is None
                and id(rec) not in replaced):
            ann["observed_until"] = last_ts
