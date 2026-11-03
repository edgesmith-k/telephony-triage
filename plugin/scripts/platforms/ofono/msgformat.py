"""형식 가정(placeholder) — 구성요소(데몬)별 메시지 하위 형식 함수. TODO(SITE:S24)

`SPEC.msg_formats`에 `(이름, 함수)`로 등록하고 site-defaults `platform.others.ofono.components.<이름>.msg_format`으로
고른다(17-platforms §9). 함수는 `msg -> MsgView | None`: 앞머리를 뗀 본문(짝 규칙 annotate 입력)과 하위 식별
(`split_tag`일 때 이벤트 tag `ident/subtag`)을 주고, 형식이 맞지 않는 줄은 None(원문 그대로 쓴다).
이벤트 `msg`는 바꾸지 않는다. 사내 데몬 형식을 더하는 곳은 여기 함수 하나 + `FORMATS` 한 항목뿐이다.

- `file_func`: 공개 upstream oFono DBG 앞머리 `src/x.c:func() 본문` 가정 → 본문, 하위 식별 = 파일 이름 줄기(`x`).

아래 4개는 사외 공개 표본에서 본 벤더 데몬 앞머리 **모양**이다(데몬 이름 없음 — 어느 데몬에 쓸지는 site가 정한다,
TODO(SITE:S24·S25)). 하위 식별(파일 줄기)은 백엔드 `SUBTAG_RE` 모양일 때만 tag에 붙는다.
- `tid_file_paren`: `tid:<n> <File>.cpp(<줄>):<func> > 본문` → `> ` 뒤 본문, 하위 식별 = `File`.
- `level_tid_file`: `[<L>][tid=<n>] <file>.cpp:<줄> <ns>::<Class>::<func>() 본문`(L = V/D/I/W/E/F) → `func() ` 뒤, `file`.
  두 형식의 함수 칸(`<func>`·`<ns>::<Class>::<func>`)은 마스킹 토큰(`<IP#n>`)도 받는다 — C++ 범위 연산자 조각이 문맥
  없는 IPv6 규칙에 가려져도 마스킹본(`mask_pii`·`cut` fixture 재파싱)이 원문과 같은 본문·하위 식별을 낸다(08-safety §8
  분석과 회귀 일치). 토큰 모양은 `common.masking.TOKEN_RE`와 같게 인라인했다(테스트가 고정).
- `slot_level_seq`: `[SLOT_<n>][<L>] <seq> 본문` → seq 뒤 본문, 하위 식별 없음.
- `src_suffix`: 끝에 소스 위치 `  path/file.go:<줄>` 또는 `[./path/file.cxx +<줄>]`·`[File.cpp+<줄>]` → 꼬리 뗀 앞, 파일 줄기.
- `[Class::Method] 본문` 형식은 아직 없다(P2).

표준 라이브러리와 `platforms.base`만 쓴다(`platforms/ofono/__init__.py`가 불러온다 — guard 규칙 10 경로라 가볍게).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from platforms.base import MsgView

_FILE_FUNC = re.compile(r"^(?P<file>[\w./-]+\.c):(?P<func>\w+)\(\)\s?(?P<body>.*)$")
_EXT = r"(?:c|cc|cpp|cxx|h|hh|hpp)"
_SRC_EXT = r"(?:c|cc|cpp|cxx|h|hh|hpp|go|java|kt|py|rs)"
# 마스킹 토큰 — `common.masking.TOKEN_RE`와 같은 모양(이 모듈은 표준 라이브러리·platforms.base만 쓰므로 인라인, 테스트가 같은지 고정)
_MASK_TOKEN = r"<[A-Z][A-Z0-9]*#\d+>"
# C++ 함수 칸(`ns::Cls::~Cls`). 범위 연산자 조각(`ns::Cls`의 `::C`, `std::`의 `d::`)은 문맥 없는 IPv6 규칙에 `<IP#n>`으로
# 가려지므로 토큰도 받는다 — 마스킹본(fixture 재파싱)이 원문과 같은 본문·하위 식별을 낸다(08-safety §8). 토큰 없는 줄은
# 맞는 문자열 집합이 `[\w:~]+`와 같다(토큰 첫 글자 `<`는 `[\w:~]` 밖).
_CXX_FUNC = r"(?:[\w:~]|" + _MASK_TOKEN + r")+"
_TID_FILE_PAREN = re.compile(r"^tid:\d+\s+(?P<file>[\w.-]+\." + _EXT + r")\(\d+\):" + _CXX_FUNC + r"\s+>\s?(?P<body>.*)$")
_LEVEL_TID_FILE = re.compile(
    r"^\[[VDIWEF]\]\[tid=\d+\]\s+(?P<file>[\w.-]+\." + _EXT + r"):\d+\s+" + _CXX_FUNC + r"\(\)\s?(?P<body>.*)$")
_SLOT_LEVEL_SEQ = re.compile(r"^\[SLOT_\d+\]\[[VDIWEF]\]\s+\d+\s?(?P<body>.*)$")
_SRC_SUFFIX = re.compile(r"(?:\s+(?P<p1>[\w./-]+\." + _SRC_EXT + r"):\d+|\s*\[(?:\./)?(?P<p2>[\w./-]+\." + _SRC_EXT
                         + r")\s*\+\s*\d+\])\s*$")
_TAIL_SCAN = 512


def _stem(path: str) -> str | None:
    return PurePosixPath(path).stem or None


def file_func(msg: str) -> MsgView | None:
    """`src/example.c:example_cb() 본문` → `MsgView("본문", "example")`. 맞지 않으면 None."""
    hit = _FILE_FUNC.match(msg)
    if not hit:
        return None
    return MsgView(hit.group("body"), _stem(hit.group("file")))


def tid_file_paren(msg: str) -> MsgView | None:
    """`tid:12 Example.cpp(34):Run > 본문` → `MsgView("본문", "Example")`. 맞지 않으면 None."""
    hit = _TID_FILE_PAREN.match(msg)
    return MsgView(hit.group("body"), _stem(hit.group("file"))) if hit else None


def level_tid_file(msg: str) -> MsgView | None:
    """`[I][tid=12] example.cpp:34 ns::Cls::run() 본문` → `MsgView("본문", "example")`. 맞지 않으면 None."""
    hit = _LEVEL_TID_FILE.match(msg)
    return MsgView(hit.group("body"), _stem(hit.group("file"))) if hit else None


def slot_level_seq(msg: str) -> MsgView | None:
    """`[SLOT_0][D] 123 본문` → `MsgView("본문")`(하위 식별 없음). 맞지 않으면 None."""
    hit = _SLOT_LEVEL_SEQ.match(msg)
    return MsgView(hit.group("body")) if hit else None


def src_suffix(msg: str) -> MsgView | None:
    """`본문  path/example.go:12`·`본문[./path/example.cxx +12]` → `MsgView("본문", "example")`. 맞지 않으면 None."""
    cut = max(0, len(msg) - _TAIL_SCAN)          # 끝부분만 본다: 긴 공백 열에서 search가 제곱 시간이 되지 않게
    hit = _SRC_SUFFIX.search(msg, cut)
    return MsgView(msg[:hit.start()], _stem(hit.group("p1") or hit.group("p2"))) if hit else None


FORMATS = (("file_func", file_func), ("tid_file_paren", tid_file_paren), ("level_tid_file", level_tid_file),
           ("slot_level_seq", slot_level_seq), ("src_suffix", src_suffix))
