"""Android 전용 상수와 구현 (RF-3).

- `logcat.py`·`ril.py`·`backend.py`(reference 백엔드)·`bugreport.py`: 로그 형식·bugreport 처리
- 이 파일: 소스 트리 검증·버전 추정에 쓰는 Android 상수 (`code_roots.py`가 가져다 쓴다)
"""

import re

TELEPHONY_DIR = "frameworks/opt/telephony"
# aosp 루트에 있어야 하는 디렉토리 기본값 (`platform.source_tree.required_dirs`로 덮어쓴다).
REQUIRED_DIRS = (TELEPHONY_DIR,)
# (파일, 정규식) 순서대로 시도한다. 기본값이며 `platform.source_tree.version_sources`로 덮어쓴다.
VERSION_SOURCES = [
    ("build/release/release_config_map.textproto", re.compile(r"RELEASE_PLATFORM_VERSION\D*(\d+)")),
    ("build/make/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.M)),
    ("build/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.M)),
]
