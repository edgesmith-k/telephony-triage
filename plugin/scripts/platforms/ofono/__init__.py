"""oFono 플랫폼 — **뼈대**(17-platforms 설계 §5). 형식 가정(placeholder)이다.

실제 로그 형식·태그·짝 규칙은 사용자가 사내 로그를 구한 뒤 정한다. 지금은 레지스트리·플랫폼 선택·이슈 DB 분리·
파서 전환이 실제로 되는지를 합성 로그로 보이는 최소 계약이다.

- 로그 줄 해석·원문 줄 판별·재부팅 표시: `journal.py`(journald/syslog 가정 형식, TODO(SITE:S24)).
- 짝 규칙(`protocols`): 없음, TODO(SITE:S26). 슬롯 표기: 없음, TODO(SITE:S29). 묶음 입력(capture): 없음.
- 소스 트리: TODO(SITE:S27). 파서 백엔드: `ofono_reference`(`backend.py`, `parser_backends/ofono_reference`).

표준 라이브러리와 이 패키지의 하위 모듈, `platforms.base`만 import한다(guard가 레지스트리로 불러온다.
`backend.py`는 불러오지 않는다 — 백엔드는 `parser_backends.<SPEC.default_backend>`가 고른다).
"""

import re

from platforms.base import LogFormat, PhoneIdRules, PlatformSpec, SourceTree

from . import journal

SPEC = PlatformSpec(
    name="ofono",
    label="oFono",
    log=LogFormat(
        read_file=journal.read_file,
        raw_line=journal.raw_line,
        find_raw=journal.find_raw,
        epoch_break=journal.epoch_break,
    ),
    phone=PhoneIdRules((), (), ()),
    protocols=(),
    source_tree=SourceTree(("src",), (("configure.ac", re.compile(r"AC_INIT\(\[?ofono\]?,\s*\[?(\d+)")),)),
    primary_root="ofono",
    default_root_keys=("ofono",),
    capture=None,
    default_backend="ofono_reference",
    block_keys=("source_tree", "log", "protocols"),
)
