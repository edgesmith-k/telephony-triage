"""빌드명 정규화 (contracts.md §3.2 sanitize_build).

fixture 파일명(§fixture)과 브랜치 이름(§브랜치)이 이 함수를 공유한다.
"""

import re

_ALLOWED = re.compile(r"[^A-Za-z0-9._+-]")


def sanitize_build(build: str) -> str:
    """`[A-Za-z0-9._+-]` 밖의 문자를 `_`로, 연속된 `.`을 `_` 하나로,
    첫 글자·끝 글자 `.`를 `_`로, 끝의 `.lock`을 `_lock`으로 바꾼다."""
    s = _ALLOWED.sub("_", build)
    s = re.sub(r"\.{2,}", "_", s)
    if s.startswith("."):
        s = "_" + s[1:]
    if s.endswith(".lock"):
        s = s[: -len(".lock")] + "_lock"
    if s.endswith("."):
        s = s[:-1] + "_"
    return s
