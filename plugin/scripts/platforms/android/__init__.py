"""Android 플랫폼 (RF-3, 17-platforms 계약 `SPEC`).

- `logcat.py`·`ril.py`·`backend.py`(reference 백엔드)·`bugreport.py`: 로그 형식·bugreport 처리
- 이 파일: 레지스트리 계약 `SPEC`과 소스 트리 검증·버전 추정에 쓰는 Android 상수

guard(규칙 10)가 레지스트리로 불러오므로 표준 라이브러리와 이 패키지의 하위 모듈만 import한다
(`backend.py`는 불러오지 않는다 — 백엔드는 `parser_backends.<SPEC.default_backend>`가 고른다).
"""

import re

from platforms.base import CaptureSpec, LogFormat, PairProtocol, PlatformSpec, SourceTree

from . import bugreport, logcat, ril

TELEPHONY_DIR = "frameworks/opt/telephony"
# aosp 루트에 있어야 하는 디렉토리 기본값 (`platform.source_tree.required_dirs`로 덮어쓴다).
REQUIRED_DIRS = (TELEPHONY_DIR,)
# (파일, 정규식) 순서대로 시도한다. 기본값이며 `platform.source_tree.version_sources`로 덮어쓴다.
# 튜플이라 `SPEC.source_tree.version_sources`와 같은 객체다.
VERSION_SOURCES = (
    ("build/release/release_config_map.textproto", re.compile(r"RELEASE_PLATFORM_VERSION\D*(\d+)")),
    ("build/make/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.M)),
    ("build/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.M)),
)

SPEC = PlatformSpec(
    name="android",
    label="Android",
    log=LogFormat(
        read_file=logcat.read_file,
        raw_line=logcat.raw_line,
        find_raw=logcat.find_raw,
        epoch_break=logcat.epoch_break,
    ),
    phone=logcat.DEFAULT_PHONE_RULES,
    protocols=(PairProtocol(name="ril", default_tags=frozenset(ril.RIL_TAGS), annotate=ril.parse, pair=ril.pair),),
    source_tree=SourceTree(REQUIRED_DIRS, VERSION_SOURCES),
    primary_root="aosp",
    default_root_keys=("aosp", "vendor_ril"),
    capture=CaptureSpec(
        looks_like=bugreport.looks_like_bugreport,
        extract=bugreport.extract,
        error=bugreport.BugreportError,
        default_rules=bugreport.DEFAULT_RULES,
        sniff_line=bugreport.sniff_line,
    ),
    default_backend="reference",
    block_keys=("source_tree", "log", "ril", "bugreport"),
)
