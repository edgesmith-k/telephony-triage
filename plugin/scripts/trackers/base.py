"""트래커 계약 타입 (트래커 범용화 설계 §3-1·§3-2).

트래커 하나 = `trackers/<name>.py`의 `SPEC: TrackerSpec`. 레지스트리(`trackers/__init__.py`)는 이 타입만 알고 트래커
이름은 모른다. 상수와 함수가 섞여 있으므로 플랫폼(`platforms/base.py`)과 같이 frozen dataclass와 Callable 필드를 쓴다.

**계층 규칙**(테스트로 강제): `trackers/*`는 표준 라이브러리만 import한다 — guard가 `common/issuepost`를 거쳐 불러오므로
가벼워야 한다. `common`·`platforms`·핵심 스크립트를 import하지 않고, 트래커 모듈끼리도 import하지 않는다.

함수 필드의 인자 `spec`은 `common/issuepost.spec_check`가 검증한 코멘트 도구 spec(`key_arg`·`body_arg`·`extra_args`·
`format`·`kind`), `raw`는 검증 전 `tracker.write_tools.add_comment` 매핑이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping


class TrackerConfigError(Exception):
    """`tracker.kind`(사용자·site 설정) 또는 이슈 DB `tracker.kind`가 잘못됐거나 그 트래커를 불러올 수 없다."""


@dataclass(frozen=True)
class TrackerSpec:
    name: str                                   # 레지스트리 이름(`tracker.kind` 값)
    label: str                                  # 게시 본문 머리·메시지 라벨 ("Jira")
    safe_key_re: re.Pattern                     # 작업 키 경로 안전 형식(작업 디렉토리·브랜치·피드백·DB 파일 이름)
    default_key_regex: str                      # 이슈 DB `tracker.key_regex`가 없을 때
    server_words: tuple                         # guard 규칙 2 서버 이름 휴리스틱(설정되지 않은 서버의 쓰기 거부)
    formats: tuple                              # `common/issuepost.RENDERERS` 키
    default_format: str
    text_defaults: Mapping                      # `{summary|description|comments: (경로, …)}` — field_map에 없을 때
    components_default: str                     # field_map `components`가 없을 때의 경로
    parse_key: Callable[[str], "str | None"]    # 사용자 입력 → 작업 키(경로 안전), 아니면 None
    display: Callable[[str], str]               # 작업 키 → 본문·메시지 표시
    link: Callable[[str, str], str]             # (DB `tracker.base_url`, 작업 키) → README 링크 대상
    spec_problems: Callable[[dict], list]       # raw → 키·본문 인자 설정 문제 문구 목록(트래커별)
    key_args: Callable[[dict, str], dict]       # (spec, 작업 키) → 쓰기 도구의 키 인자
    key_from_args: Callable[[dict, object], "str | None"]   # (spec, 도구 입력) → 경로 안전 작업 키, 아니면 None
    arg_names: Callable[[dict], set]            # spec → 승인 범위의 키 인자 이름 집합
    key_arg_id: Callable[[dict], str]           # spec → 승인 기록 `key_arg` 값
    read_action: Callable[[object, set], "str | None"]   # (도구 입력, 매핑된 논리 동작) → get_issue|get_comments|None|"unsupported"
    key_from_read: Callable[[object, object, re.Pattern], "str | None"]   # (응답, 도구 입력, 키 정규식) → 작업 키
    read_args: Callable[[str, str], "dict | None"]   # (논리 동작, 작업 키) → needs_input 안내 인자(없으면 None)
    classify_extra: Callable[[str, set], set]   # (도구 이름, 후보 동작) → 보강한 후보 동작(setup)
