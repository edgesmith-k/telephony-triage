#!/usr/bin/env python3
"""모의 site 파서 백엔드 (15-local-draft.md §15.2, 16-existing-assets.md §16.6).

사내에서 **검증된 기존 파서를 포팅**해 넣을 자리(`plugin/scripts/parser_backends/site/`,
SITE_PATHS)를 사외에서 흉내 낸 가짜다. `builtin.data.*` 이벤트 두 개를 낸다.

- 사외 레포의 `plugin/` 안에는 두지 않는다. SITE_PATHS 경로가 비어 있어야
  반입 체크리스트(§15.4)를 통과하기 때문이다. 테스트는
  `tests/helpers/make_plugin_root.py --with-site-backend`로 임시 플러그인
  루트의 `scripts/parser_backends/site/`에 복사해서 쓴다.
- 인터페이스는 `plugin/scripts/parser_backends/base.py`다. 이 모의 백엔드는
  reference 백엔드를 상속해 **공통 처리(포맷·시각·RIL 페어링·윈도우)를 재사용**하고
  builtin 판별(`detect`)만 더한다 (16-existing-assets.md §16.3의 한 가지 포팅 방식).
  기존 파서가 공통 처리를 직접 한다면 `ParserBackend`를 바로 상속해도 된다.

계약 (contracts.md §기존 자산 연결 계약)
    parse(paths, tz, year, window) -> events[]
    builtin_events() -> [이름]
    version() -> str

같은 입력이면 항상 같은 출력을 낸다.
"""

from __future__ import annotations

import re

from platforms.android.backend import ReferenceBackend

VERSION = "0.0.3-mock"

# 판별 규칙 — 문구는 placeholder다. TODO(SITE:S9)
# `builtin.data.ip_assigned`는 원본 값(IP)을 필드로 낸다. `parse --mask`가 builtin 필드도
# 같은 번호 토큰으로 마스킹하는지 시험하기 위한 것이다 (11-phases.md Phase 4).
DETECTORS = [
    (
        "builtin.data.setup_not_allowed",
        re.compile(r"^DNC-\d+$"),
        re.compile(r"evaluation result:\s*NOT_ALLOWED\s*reasons=\[(?P<reasons>[^\]]*)\]"),
    ),
    (
        "builtin.data.user_data_disabled",
        re.compile(r"^DSM-\d+$"),
        re.compile(r"onDataEnabledChanged:\s*enabled=(?P<enabled>false)\s*reason=(?P<reason>\w+)"),
    ),
    (
        "builtin.data.ip_assigned",
        re.compile(r"^DN-.+$"),
        re.compile(r"onConnected:.*\bip=(?P<ip>\S+)"),
    ),
]


class MockSiteBackend(ReferenceBackend):
    name = "site"

    def version(self) -> str:
        return VERSION

    def builtin_events(self) -> list[str]:
        return [name for name, _, _ in DETECTORS]

    def detect(self, record: dict) -> list[tuple[str, dict]]:
        hits = []
        for event, tag_re, msg_re in DETECTORS:
            if not tag_re.match(record["tag"]):
                continue
            found = msg_re.search(record["msg"])
            if found:
                hits.append((event, {k: v for k, v in found.groupdict().items() if v is not None}))
        return hits


BACKEND = MockSiteBackend()
