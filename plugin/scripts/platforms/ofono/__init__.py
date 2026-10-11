"""oFono 플랫폼 — **뼈대**(17-platforms 묶음 2: 최소 SPEC). 형식 가정(placeholder)이다.

실제 로그 형식·태그·짝 규칙은 사용자가 사내 로그를 구한 뒤 정한다. 이 묶음에서는 레지스트리·플랫폼 선택·이슈 DB 분리가
돌아가는지만 보이는 최소 계약이다.

- 로그 줄 해석: 아직 없다(묶음 3 `journal.py`, TODO(SITE:S24)). `read_file`은 모든 줄을 "해석 못 함"으로 센다.
- 원문 줄 판별(`raw_line`·`find_raw`): 아직 없다(False) — guard 규칙 10·Jira 게시 검사는 다른 플랫폼 판별과 내장 판별로 막는다.
- 짝 규칙(`protocols`): 없음, TODO(SITE:S26). 슬롯 표기: 없음, TODO(SITE:S29). 묶음 입력(capture): 없음.
- 소스 트리: TODO(SITE:S27). 파서 백엔드: `ofono_reference`(묶음 3에서 만든다. 지금은 불러오면 "없습니다"로 종료 코드 2).

표준 라이브러리와 `platforms.base`·`common.logtime`만 import한다(guard가 레지스트리로 불러온다).
"""

import re
from pathlib import Path

from common.logtime import open_log
from platforms.base import FileStats, LogFormat, LogLine, PhoneIdRules, PlatformSpec, SourceTree


def read_file(path: str | Path, file_index: int, tz_name: str | None, year: int | None) -> tuple[list[LogLine], FileStats]:
    """placeholder: 줄을 해석하지 않는다(빈 줄 밖의 모든 줄을 `unparsed`로 센다). TODO(SITE:S24) 묶음 3에서 바꾼다."""
    stats = FileStats()
    with open_log(path) as fh:
        for raw in fh:
            if raw.strip():
                stats.unparsed += 1
    return [], stats


def _never(_value) -> bool:
    return False


SPEC = PlatformSpec(
    name="ofono",
    label="oFono",
    log=LogFormat(read_file=read_file, raw_line=_never, find_raw=_never, epoch_break=_never),
    phone=PhoneIdRules((), (), ()),
    protocols=(),
    source_tree=SourceTree(("src",), (("configure.ac", re.compile(r"AC_INIT\(\[?ofono\]?,\s*\[?(\d+)")),)),
    primary_root="ofono",
    default_root_keys=("ofono",),
    capture=None,
    default_backend="ofono_reference",
    block_keys=("source_tree", "log", "protocols"),
)
