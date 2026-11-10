"""Android 플랫폼 (RF-3, 17-platforms 계약 `SPEC`).

- `logcat.py`·`ril.py`·`backend.py`(reference 백엔드)·`bugreport.py`: 로그 형식·bugreport 처리
- 이 파일: 레지스트리 계약 `SPEC`과 소스 트리 검증·버전 추정에 쓰는 Android 상수

guard(규칙 10)가 레지스트리로 불러오므로 표준 라이브러리와 이 패키지의 하위 모듈만 import한다
(`backend.py`는 불러오지 않는다 — 백엔드는 `parser_backends.<SPEC.default_backend>`가 고른다).
"""

import re

from platforms.base import CaptureSpec, LogFormat, PairProtocol, PlatformSpec, SourceTree, TemplateMeta

from . import bugreport, logcat, ril

TELEPHONY_DIR = "frameworks/opt/telephony"
# aosp 루트에 있어야 하는 디렉토리 기본값 (`platform.source_tree.required_dirs`로 덮어쓴다).
REQUIRED_DIRS = (TELEPHONY_DIR,)
# (파일, 정규식) 순서대로 시도한다. 기본값이며 `platform.source_tree.version_sources`로 덮어쓴다.
# 튜플이라 `SPEC.source_tree.version_sources`와 같은 객체다.
VERSION_SOURCES = (
    ("build/release/release_config_map.textproto", re.compile(r"RELEASE_PLATFORM_VERSION\D*(\d+)")),
    ("build/make/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.MULTILINE)),
    ("build/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.MULTILINE)),
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
        block_key="bugreport",
        configure=bugreport.configure_rules,
    ),
    default_backend="reference",
    block_keys=("source_tree", "log", "ril", "bugreport", "vendor_ipc"),
    # 모듈 스킬 템플릿·모듈 eval 자료(17-platforms §10-3). layers는 module_eval 출력 형식의 한 줄 — 바이트가 시험으로 고정돼 있다.
    # Android는 log-guide 대신 내장 log-tags·ril-requests·fail-causes(DD §4.4, H C1+D S2)
    template=TemplateMeta(
        # oFono 문서에 없어야 하는 Android 프레임워크 이름(고정 목록). oFono 로그에도 나오는 `RIL_REQUEST_*`는 뺀다
        names=re.compile(r"\bRILJ\b|\bRilRequest\b|\bDcTracker\b|\bDataNetworkController\b|\bServiceStateTracker\b"
                         r"|\bGsmCdmaPhone\b|\bImsPhone\w*|\bTelephonyManager\b|\bUiccController\b"
                         r"|\bSubscriptionManager\w*|\bandroid\.hardware\.radio\b|\bcom\.android\."),
        layers=("<프레임워크 | RILJ | RIL HAL | 벤더 RIL | 벤더 IMS | 모뎀·망 | 곁가지(<태그>) | 그 층 로그 없음(<층>) "
                "| 원인 아님(정상 동작)>"),
        builtin_docs={"pre": (("log-tags.md", "builtin/log-tags.md"), ("ril-requests.md", "builtin/ril-requests.md"),
                              ("fail-causes.md", "builtin/fail-causes.md")),
                      "post": ()},
        equals_live=(("log-tags.md", "log-tags.md"), ("ril-requests.md", "ril-requests.md"), ("fail-causes.md", "fail-causes.md")),
        deep_baseline_note="Android without = 내장 log-tags·ril-requests·fail-causes",
    ),
)
