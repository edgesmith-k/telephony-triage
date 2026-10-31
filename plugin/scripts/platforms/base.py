"""플랫폼 계약 타입 (17-platforms 묶음 1, 설계 §2-2).

플랫폼 하나 = `platforms/<name>/__init__.py`의 `SPEC: PlatformSpec`. 레지스트리(`platforms/__init__.py`)는
이 타입만 알고 플랫폼 이름은 모른다. 상수와 함수가 섞여 있고 site-defaults로 덮어쓴 복사본을 만들어야 하므로
ABC 대신 frozen dataclass와 Callable 필드를 쓴다.

여기 있는 타입은 표준 라이브러리만 쓴다(guard가 규칙 10에서 불러오므로 가벼워야 한다).
`LogLine`·`FileStats`·`PhoneIdRules`는 `platforms/android/logcat.py`가, `VendorRules`·`DEFAULT_LINK_MS`는
`platforms/android/ril.py`가 같은 객체를 다시 내보낸다(기존 import 경로 유지).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


# -- site-defaults 블록 검증 도구 (레지스트리와 플랫폼의 `CaptureSpec.configure`가 같이 쓴다) ------------------

CONFIG_FILE = "site-defaults.yaml"


class PlatformConfigError(Exception):
    """`platform:` 블록이 잘못됐거나 플랫폼을 불러올 수 없다. 메시지에 키 경로가 들어 있다."""


def config_error(path: str, why: str) -> PlatformConfigError:
    return PlatformConfigError(f"{CONFIG_FILE} {path}: {why}")


def cfg_mapping(value, path: str, allowed: tuple[str, ...] | None = None) -> dict:
    """None → `{}`. 매핑이 아니거나 `allowed` 밖 키가 있으면 오류."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise config_error(path, "매핑이어야 합니다.")
    if allowed is not None:
        for key in value:
            if key not in allowed:
                raise config_error(f"{path}.{key}", f"알 수 없는 키입니다 (허용: {', '.join(allowed)}).")
    return value


def cfg_list(value, path: str, *, non_empty: bool) -> list:
    if not isinstance(value, list):
        raise config_error(path, "목록이어야 합니다.")
    if non_empty and not value:
        raise config_error(path, "비어 있으면 안 됩니다.")
    return value


def cfg_compile(value, path: str, flags: int = 0, *, groups: int = 1) -> re.Pattern:
    if not isinstance(value, str) or not value:
        raise config_error(path, "비어 있지 않은 정규식 문자열이어야 합니다.")
    try:
        pattern = re.compile(value, flags)
    except re.error as exc:
        raise config_error(path, f"정규식 오류: {exc}") from exc
    if pattern.groups < groups:
        raise config_error(path, "캡처 그룹이 하나 이상 있어야 합니다 (그룹 1 = 값).")
    return pattern


@dataclass(frozen=True)
class LogLine:
    file_index: int
    line_no: int
    dt: datetime  # UTC
    pid: int
    tid: int | None
    level: str
    tag: str
    msg: str


@dataclass
class FileStats:
    lines: int = 0
    unparsed: int = 0
    missing_year: bool = False
    missing_zone: bool = False
    first_month: int | None = None  # 연도 없는 줄의 첫/끝 월 (다중 파일 해 넘김 경고용)
    last_month: int | None = None


@dataclass(frozen=True)
class PhoneIdRules:
    """슬롯 표기 규칙. 위치마다 패턴을 순서대로 보고 첫 일치를 쓴다. 그룹 1 = 슬롯 번호."""

    tag: tuple[re.Pattern, ...]      # 태그에 match
    prefix: tuple[re.Pattern, ...]   # 메시지 앞에 match
    suffix: tuple[re.Pattern, ...]   # 메시지 끝쪽에 search

    def phone_id(self, tag: str, msg: str) -> int | None:
        for patterns, text, search in ((self.tag, tag, False), (self.prefix, msg, False), (self.suffix, msg, True)):
            for pattern in patterns:
                hit = pattern.search(text) if search else pattern.match(text)
                if hit and (hit.group(1) or "").isdecimal():
                    return int(hit.group(1))
        return None

    def strip(self, msg: str) -> str:
        """슬롯 표기를 뗀 메시지 (RIL 줄 해석용. 이벤트의 `msg`는 원문 그대로 둔다)."""
        for pattern in self.prefix:
            hit = pattern.match(msg)
            if hit:
                msg = msg[hit.end():]
                break
        for pattern in self.suffix:
            hit = pattern.search(msg)
            if hit:
                msg = msg[:hit.start()] + msg[hit.end():]
                break
        return msg


# 벤더 RIL 층 연결 기본 창(ms). `platform.ril.vendor.link_ms`로 바꾼다.
DEFAULT_LINK_MS = 2000


@dataclass(frozen=True)
class VendorRules:
    """`layers`: `((tag, (패턴, ...)), ...)` — 패턴마다 이름 그룹 `serial`·`token` 중 정확히 하나(값은 10진 숫자).
    `coverage_tags`: 정규식 없이 "수집 살아 있음"만 표시하는 태그(정확한 이름)."""
    layers: tuple
    link_ms: int = DEFAULT_LINK_MS
    coverage_tags: frozenset = frozenset()


@dataclass(frozen=True)
class SourceTree:
    required_dirs: tuple[str, ...]
    version_sources: tuple[tuple[str, re.Pattern], ...]


@dataclass(frozen=True)
class LogFormat:
    """로그 줄 형식. `read_file(path, file_index, tz, year) -> (list[LogLine], FileStats)`."""
    read_file: Callable[[Path, int, str | None, int | None], tuple[list[LogLine], FileStats]]
    raw_line: Callable[[str], bool]          # 줄 맨 앞이 원문 로그 줄인가 (guard 규칙 10)
    find_raw: Callable[[str], bool]          # 문장 안에 원문 로그 줄이 끼었나 (issue_post fill 검사)
    epoch_break: Callable[[LogLine], bool]   # 재부팅 등 불연속 줄


@dataclass(frozen=True)
class PairProtocol:
    """요청-응답 짝 규칙. 플랫폼마다 0개 이상.

    태그 덮어쓰기(RF-4): `name == "ril"`이면 site-defaults `platform.ril.tags`(기존 키), 그 밖은
    `<블록>.protocols.<name>.tags`(`block_keys`에 `protocols`가 있는 플랫폼). 결과는 `PlatformProfile.protocol_tags`.
    `PlatformSpec.protocol_kinds`가 있는 플랫폼은 `<블록>.protocols.<site 이름>: {kind, ...}`로 짝 규칙을 더 만든다
    (`PlatformProfile.protocols`에 SPEC 것 뒤로 붙는다).

    주석은 이벤트의 `ril` 칸을 같이 쓴다. `name != "ril"`인 프로토콜은 주석에 `proto: <name>`을 단다.
    `pair`는 **자기 주석만** 다룬다(`proto`가 자기 이름인 것, "ril"이면 `proto`가 없는 것) — 다른 프로토콜 주석은
    짝·pid 분할에 쓰지 않는다."""
    name: str
    default_tags: frozenset
    annotate: Callable[..., dict | None]     # (tag, msg, tags, phone) → {serial, dir, request, error, ...} | None
    pair: Callable[[list[dict]], None]       # 전체 레코드를 제자리에서. 자기 주석만 다룬다


@dataclass(frozen=True)
class CaptureSpec:
    """bugreport류 묶음 입력. 없는 플랫폼은 `PlatformSpec.capture = None`.

    site-defaults의 `block_key` 블록(`block_keys`에 있어야 받는다)은 `configure(default_rules, raw, path)`가 검증해
    덮어쓴 복사본을 준다. 레지스트리는 규칙의 모양을 모른다. 오류는 `PlatformConfigError`(`config_error`)."""
    looks_like: Callable[[Path], bool]
    extract: Callable[..., dict]             # (src, out_dir, rules) → {files, build_json, build, warnings}
    error: type
    default_rules: object                    # 플랫폼 고유 규칙 객체 (android: `BugreportRules`)
    sniff_line: Callable[[str], bool]        # guard 규칙 10 머리 판별
    block_key: str = ""                      # site-defaults 블록 키 (android: "bugreport"). 비면 덮어쓰기 없음
    configure: Callable[..., object] | None = None   # (default_rules, raw 블록 | None, 키 경로) → 규칙


@dataclass(frozen=True)
class MsgView:
    """구성요소 메시지 하위 형식 함수(`PlatformSpec.msg_formats`)의 결과. 형식이 맞지 않으면 함수가 None을 준다."""
    body: str                  # 하위 형식 앞머리를 뗀 본문 (짝 규칙 annotate 입력. 이벤트 `msg`는 원문 그대로)
    subtag: str | None = None  # 하위 식별(모듈 등). 구성요소 `split_tag`일 때만, 식별자 모양이면 이벤트 tag에 붙는다


@dataclass(frozen=True)
class Component:
    """한 플랫폼 안의 구성요소(데몬) 하나 (17-platforms §9). 이름·ident·루트 키는 site가 정한다(코드에는 placeholder).

    site-defaults `<블록>.components.<name>`(`block_keys`에 `components`가 있는 플랫폼)으로 덮어쓰고, 키를 쓰면
    목록이 통째로 바뀐다. 카테고리는 여기 두지 않는다(이슈 DB `tags.yaml`이 정한다)."""
    name: str                              # ^[a-z][a-z0-9_-]*$
    idents: tuple[str, ...]                # LogLine.tag 정확한 이름, 1개 이상, 구성요소끼리 겹치지 않음
    root_key: str | None = None            # 소스 루트 키 ^[a-z][a-z0-9_]*$ (code_ref 키 형식), 구성요소끼리 겹치지 않음
    source_tree: SourceTree | None = None  # 그 루트의 required_dirs·version_sources (root_key 필요, 주 루트면 금지)
    msg_format: str | None = None          # `PlatformSpec.msg_formats` 이름
    split_tag: bool = False                # True면 이벤트 tag = f"{ident}/{subtag}" (msg_format 필요)


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    label: str                               # 출력 라벨 ("Android")
    log: LogFormat
    phone: PhoneIdRules                      # 슬롯 기본 규칙 (빈 규칙 허용)
    protocols: tuple[PairProtocol, ...]
    source_tree: SourceTree
    primary_root: str                        # 주 소스 루트 키 ("aosp")
    default_root_keys: tuple[str, ...]       # DB `code_root_keys`가 없을 때
    capture: CaptureSpec | None
    default_backend: str                     # 파서 백엔드 기본 이름 ("reference")
    block_keys: tuple[str, ...]              # site-defaults `platform:` 블록에서 받는 상수 키
    # 다중 구성요소(17-platforms §9). 뒤쪽 기본값 필드라 기존 SPEC은 그대로다(없으면 빈 튜플).
    components: tuple[Component, ...] = ()   # 코드 기본 구성요소. `block_keys`에 `components`가 있어야 덮어쓴다
    msg_formats: tuple[tuple[str, Callable[[str], MsgView | None]], ...] = ()   # (이름, msg → MsgView | None)
    # (kind, factory). factory(이름, 설정 블록, 키 경로) → PairProtocol. 자기 키를 `cfg_*`로 검증한다.
    # `<블록>.protocols.<이름>: {kind: <kind>, ...}`로 site가 이름 지은 짝 규칙을 더한다(SPEC.protocols 뒤에 붙는다).
    protocol_kinds: tuple[tuple[str, Callable[[str, dict, str], PairProtocol]], ...] = ()
