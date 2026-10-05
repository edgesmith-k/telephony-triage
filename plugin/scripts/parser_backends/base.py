"""파서 백엔드 인터페이스 (contracts.md §기존 자산 연결 계약, 16-existing-assets.md §16.3).

`parse_logcat.py`가 `site-defaults.yaml`의 `parser.backend`(site | reference)로
백엔드를 고르고, 백엔드 패키지의 `BACKEND` 객체를 쓴다.

백엔드가 하는 일: 포맷 처리, 시각을 UTC로 정렬, RIL 요청/응답 페어링
(키 `(pid, phone_id, serial)`), 윈도우 자르기. builtin 판별 이벤트
(`builtin.<category>.<이름>`, `source: backend:<name>`).

백엔드가 하지 않는 일(= `parse_logcat.py`가 한다): 마스킹(extractor 전),
`parser-rules` extractor 실행, 태그 → 카테고리 매핑, 외부 파서(어댑터) 병합.

같은 입력이면 항상 같은 출력이어야 한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Sequence

# (start, end) — tz-aware UTC datetime. None이면 파일 전체(--full).
Window = tuple[datetime, datetime]


class ParserBackend(ABC):
    """모든 파서 백엔드의 부모. site 백엔드는 reference를 상속해 builtin 판별만
    더해도 된다 (16-existing-assets.md §16.3 "reference 백엔드의 역할")."""

    #: 백엔드 이름. 이벤트 `source`는 `backend:<name>`이다.
    name: str = ""

    @abstractmethod
    def parse(
        self,
        paths: Sequence[str | Path],
        tz: str | None,
        year: int | None,
        window: Window | None,
    ) -> list[dict]:
        """이벤트 목록. 각 이벤트는
        `{ts, pid, tid, level, tag, msg, phone_id, category_hint, ril, event, fields, source, line_ref}`.
        로그 한 줄은 `event: None`인 줄 레코드이고, builtin 판별은 별도 레코드다.
        `line_ref`는 `{file_index, line_no}`(입력 `paths`의 0부터 순번, 1부터 센 물리 줄 번호)로, builtin 레코드는
        그 줄 레코드의 값을 그대로 가진다. 줄 위치를 줄 수 없는 백엔드는 `None`을 줘도 된다(`postprocess`가 빠진 키를
        `None`으로 채운다). 경로·본문은 넣지 않는다 (04-parser-matching.md §5.8 (6)).
        레코드 형식·검사: `common/events.py` (`Event`, `validate_event`).
        RIL 페어링은 윈도우를 자르기 **전에** 파일 전체로 한다."""

    @abstractmethod
    def builtin_events(self) -> list[str]:
        """코드에 든 판별 로직이 내는 이벤트 이름 (`builtin.<category>.<이름>`).
        `db_lint`가 `must_event: builtin.*` 참조를 이 목록으로 검사한다."""

    @abstractmethod
    def version(self) -> str:
        """백엔드 버전. 이슈 DB `parser_backend.min_version`과 비교하고 캐시 해시에 넣는다."""

    def coverage(
        self, paths: Sequence[str | Path], tz: str | None, year: int | None
    ) -> dict:
        """`{first_ts, last_ts, clock_anomalies: [{ts, kind, delta_sec}], stats}`.
        윈도우와 상관없이 파일 전체를 본다. `stats`는
        `{lines, unparsed, missing_year, missing_zone}`이고 `parse_logcat.py`가
        경고를 만든 뒤 출력에서 뺀다. 기본 구현은 reference의 공통 줄 해석
        (`parser_backends/logcat.py`)을 쓴다. 형식을 직접 해석하는 백엔드는 바꾼다."""
        from . import logcat

        files = []
        stats = {"lines": 0, "unparsed": 0, "missing_year": False, "missing_zone": False}
        for index, path in enumerate(paths):
            lines, st = logcat.read_file(path, index, tz, year)
            files.append(lines)
            stats["lines"] += st.lines
            stats["unparsed"] += st.unparsed
            stats["missing_year"] |= st.missing_year
            stats["missing_zone"] |= st.missing_zone
        result = logcat.coverage(files)
        result["stats"] = stats
        return result
