"""형식 가정(placeholder) — 구성요소(데몬)별 메시지 하위 형식 함수. TODO(SITE:S24)

`SPEC.msg_formats`에 `(이름, 함수)`로 등록하고 site-defaults `platform.others.ofono.components.<이름>.msg_format`으로
고른다(17-platforms §9). 함수는 `msg -> MsgView | None`: 앞머리를 뗀 본문(짝 규칙 annotate 입력)과 하위 식별
(`split_tag`일 때 이벤트 tag `ident/subtag`)을 주고, 형식이 맞지 않는 줄은 None(원문 그대로 쓴다).
이벤트 `msg`는 바꾸지 않는다. 사내 데몬 형식을 더하는 곳은 여기 함수 하나 + `FORMATS` 한 항목뿐이다.

- `file_func`: 공개 upstream oFono DBG 앞머리 `src/x.c:func() 본문` 가정 → 본문, 하위 식별 = 파일 이름 줄기(`x`).

표준 라이브러리와 `platforms.base`만 쓴다(`platforms/ofono/__init__.py`가 불러온다 — guard 규칙 10 경로라 가볍게).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from platforms.base import MsgView

_FILE_FUNC = re.compile(r"^(?P<file>[\w./-]+\.c):(?P<func>\w+)\(\)\s?(?P<body>.*)$")


def file_func(msg: str) -> MsgView | None:
    """`src/example.c:example_cb() 본문` → `MsgView("본문", "example")`. 맞지 않으면 None."""
    hit = _FILE_FUNC.match(msg)
    if not hit:
        return None
    return MsgView(hit.group("body"), PurePosixPath(hit.group("file")).stem or None)


FORMATS = (("file_func", file_func),)
