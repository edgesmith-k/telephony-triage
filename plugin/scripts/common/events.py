"""파서 출력 이벤트 레코드 (NormalizedLogEvent) — 정의 원본은 `07-workflow.md §Step 3`·`04 §5.8 (2)(6)`·`contracts.md`.

여기는 코드 거울: 키 순서, 생성 함수, 검사. 플랫폼 무관(RF-3 전제). 출력은 바꾸지 않는다. 표준 라이브러리만.
`validate_event`는 사내 포팅 백엔드 확인과 테스트용이다(런타임 경로에서 호출하지 않는다, 예외를 내지 않는다).
"""

from __future__ import annotations

import re
from typing import NotRequired, TypedDict

SCHEMA_VERSION = 1  # events.json 최상위 "schema" (markers 출력도 같은 번호)

# 이벤트 키 순서 (출력 JSON의 키 순서와 같다).
EVENT_KEYS = ("ts", "pid", "tid", "level", "tag", "msg", "phone_id", "category_hint", "ril", "event",
              "fields", "source", "line_ref")
RIL_KEYS = ("serial", "dir", "request", "error", "paired_ts", "latency_ms")  # + 선택 `observed_until`(응답 없는 요청)·`hal`(벤더 층)
LINE_REF_KEYS = ("file_index", "line_no")

SOURCE_RULES = "rules"
BACKEND_PREFIX = "backend:"
EXTERNAL_PREFIX = "external:"
BUILTIN_PREFIX = "builtin."
EXT_EVENT_PREFIX = "ext."


class LineRef(TypedDict):
    file_index: int          # 입력 목록 0부터 순번
    line_no: int | None      # 1부터 센 물리 줄 번호. 모르면 None(외부 파서)


class RilAnnotation(TypedDict):
    serial: int | None
    dir: str | None
    request: str | None
    error: str | None
    paired_ts: str | None
    latency_ms: int | None
    observed_until: NotRequired[str]
    hal: NotRequired[str]   # responded / reached / not_reached / unknown (platform.ril.vendor 있을 때만)


class Event(TypedDict):
    ts: str
    pid: int | None
    tid: int | None
    level: str | None
    tag: str | None
    msg: str
    phone_id: int | None
    category_hint: str | None
    ril: RilAnnotation | None
    event: str | None
    fields: dict[str, str]
    source: str
    line_ref: LineRef | None


# -- 생성 ---------------------------------------------------------------------


def line_ref(file_index: int, line_no: int | None = None) -> LineRef:
    return {"file_index": file_index, "line_no": line_no}


def ref_key(ref) -> tuple[int, int] | None:
    """줄 위치 `(file_index, line_no)`. 줄 번호를 모르면(없음·None·0) None."""
    if isinstance(ref, dict) and ref.get("line_no"):
        return (ref.get("file_index"), ref["line_no"])
    return None


def ref_label(ref) -> str | None:
    """줄 위치 → `f<입력 순번>:L<줄>` (report.md 전용). 줄 번호를 모르면 None."""
    if isinstance(ref, dict) and ref.get("line_no"):
        return f"f{ref['file_index']}:L{ref['line_no']}"
    return None


def make_event(*, ts, source, pid=None, tid=None, level=None, tag=None, msg="", phone_id=None,
               category_hint=None, ril=None, event=None, fields=None, line_ref=None) -> Event:
    """`EVENT_KEYS` 순서의 이벤트 dict. `fields`는 호출자가 문자열로 바꿔 넘긴다(여기서 바꾸지 않는다)."""
    return {
        "ts": ts,
        "pid": pid,
        "tid": tid,
        "level": level,
        "tag": tag,
        "msg": msg,
        "phone_id": phone_id,
        "category_hint": category_hint,
        "ril": ril,
        "event": event,
        "fields": {} if fields is None else fields,
        "source": source,
        "line_ref": line_ref,
    }


def derived_event(base: dict, event: str, fields: dict, source: str = SOURCE_RULES) -> Event:
    """`base`(줄 레코드)의 시각·줄 정보를 물려받은 파생 이벤트. `fields` 값은 문자열로 바꾼다."""
    return make_event(
        ts=base["ts"],
        pid=base.get("pid"),
        tid=base.get("tid"),
        level=base.get("level"),
        tag=base.get("tag"),
        msg=base.get("msg"),
        phone_id=base.get("phone_id"),
        category_hint=base.get("category_hint"),
        event=event,
        fields={k: str(v) for k, v in fields.items()},
        source=source,
        line_ref=base.get("line_ref"),
    )


# -- 검사 ---------------------------------------------------------------------

_TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_event(e) -> list[str]:
    """형식 위반 목록(없으면 `[]`). 예외를 내지 않는다."""
    if not isinstance(e, dict):
        return [f"dict가 아님: {type(e).__name__}"]
    if list(e) != list(EVENT_KEYS):
        return [f"키 목록·순서가 다름: {list(e)}"]
    problems: list[str] = []
    if not isinstance(e["ts"], str) or not _TS_RE.match(e["ts"]):
        problems.append(f"ts 형식 오류: {e['ts']!r}")
    for k in ("pid", "tid", "phone_id"):
        if e[k] is not None and not _is_int(e[k]):
            problems.append(f"{k}는 int 또는 None: {e[k]!r}")
    for k in ("level", "tag", "category_hint", "event"):
        if e[k] is not None and not isinstance(e[k], str):
            problems.append(f"{k}는 str 또는 None: {e[k]!r}")
    if not isinstance(e["msg"], str):
        problems.append(f"msg는 str: {e['msg']!r}")
    fields = e["fields"]
    if not isinstance(fields, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in fields.items()):
        problems.append("fields는 dict[str, str]")
    problems += _check_source(e)
    problems += _check_ril(e)
    problems += _check_line_ref(e["line_ref"])
    return problems


def _check_source(e: dict) -> list[str]:
    source, name = e["source"], e["event"]
    named = isinstance(name, str)
    if source == SOURCE_RULES:
        if name is None:
            return ["rules 이벤트는 event가 있어야 함"]
        if named and name.startswith((BUILTIN_PREFIX, EXT_EVENT_PREFIX)):
            return [f"rules 이벤트가 예약 이름공간을 씀: {name}"]
    elif isinstance(source, str) and source.startswith(BACKEND_PREFIX) and len(source) > len(BACKEND_PREFIX):
        if named and not name.startswith(BUILTIN_PREFIX):
            return [f"backend 이벤트 이름은 {BUILTIN_PREFIX}*: {name}"]
    elif isinstance(source, str) and source.startswith(EXTERNAL_PREFIX) and len(source) > len(EXTERNAL_PREFIX):
        if named and not name.startswith(EXT_EVENT_PREFIX):
            return [f"external 이벤트 이름은 {EXT_EVENT_PREFIX}*: {name}"]
    else:
        return [f"source 형식 오류: {source!r}"]
    return []


def _check_ril(e: dict) -> list[str]:
    ril = e["ril"]
    if ril is None:
        return []
    if e["event"] is not None:
        return ["ril은 줄 레코드(event None)에만 있음"]
    if not isinstance(ril, dict):
        return [f"ril은 dict 또는 None: {type(ril).__name__}"]
    keys = list(ril)
    if keys[:len(RIL_KEYS)] != list(RIL_KEYS) or keys[len(RIL_KEYS):] not in (
            [], ["observed_until"], ["hal"], ["observed_until", "hal"]):
        return [f"ril 키 오류: {keys}"]
    return []


def _check_line_ref(ref) -> list[str]:
    if ref is None:
        return []
    if not isinstance(ref, dict) or list(ref) != list(LINE_REF_KEYS):
        return [f"line_ref 키 오류: {ref!r}"]
    problems = []
    if not _is_int(ref["file_index"]) or ref["file_index"] < 0:
        problems.append(f"line_ref.file_index는 0 이상 int: {ref['file_index']!r}")
    if ref["line_no"] is not None and (not _is_int(ref["line_no"]) or ref["line_no"] < 1):
        problems.append(f"line_ref.line_no는 1 이상 int 또는 None: {ref['line_no']!r}")
    return problems


def validate_events(events) -> list[str]:
    """이벤트 목록 검사. 각 문제 앞에 `events[i]: `를 붙인다."""
    if not isinstance(events, (list, tuple)):
        return [f"events는 list: {type(events).__name__}"]
    return [f"events[{i}]: {p}" for i, e in enumerate(events) for p in validate_event(e)]
