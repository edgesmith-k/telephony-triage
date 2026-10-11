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
    """요청-응답 짝 규칙. 플랫폼마다 0개 이상. `name == "ril"`이면 site-defaults `platform.ril` 블록이 태그를 덮는다."""
    name: str
    default_tags: frozenset
    annotate: Callable[..., dict | None]     # (tag, msg, tags, phone) → {serial, dir, request, error, ...} | None
    pair: Callable[[list[dict]], None]       # 전체 레코드를 제자리에서. 자기 주석만 다룬다


@dataclass(frozen=True)
class CaptureSpec:
    """bugreport류 묶음 입력. 없는 플랫폼은 `PlatformSpec.capture = None`."""
    looks_like: Callable[[Path], bool]
    extract: Callable[..., dict]             # (src, out_dir, rules) → {files, build_json, build, warnings}
    error: type
    default_rules: object                    # site-defaults 블록(`block_keys`의 capture 키)으로 덮어쓴 복사본의 원본
    sniff_line: Callable[[str], bool]        # guard 규칙 10 머리 판별


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
