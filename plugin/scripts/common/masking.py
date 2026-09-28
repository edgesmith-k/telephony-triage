"""마스킹 함수 자리 (contracts.md §3.2 "마스킹 함수", 08-safety.md §8).

`mask_pii.py`와 `parse_logcat.py`가 공유한다. **Phase 4에서 구현한다.**
Phase 2에서는 인터페이스만 둔다: `parse_logcat.py parse --mask`는 이 함수로
마스커를 만들고, 마스커를 **extractor 실행 전에** 각 줄(백엔드·외부 파서 이벤트의
`msg`·`fields` 포함)에 적용한다.

마스커 인터페이스: `masker(text: str) -> str`. 한 번의 파싱(파일 묶음) 동안 같은
마스커를 써서 같은 값이 같은 번호 토큰을 받게 한다(`<종류#n>`, 멱등).
"""

from __future__ import annotations

from typing import Callable

Masker = Callable[[str], str]


class MaskingNotReady(NotImplementedError):
    pass


def new_masker(existing_text: str | None = None) -> Masker:
    """새 마스커. `existing_text`에 이미 있는 토큰 다음 번호부터 준다 (Phase 4)."""
    raise MaskingNotReady("마스킹 함수는 Phase 4에서 연결한다 (08-safety.md §8).")
