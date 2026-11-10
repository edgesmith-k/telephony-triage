"""oFono 덤프 함수 조각 묶기 (08-safety.md §8, `tools/fixture_residual.py`·`masking.py` 공용).

oFono 덤프 함수는 한 메시지를 여러 줄에 자른다(같은 ident·pid, 시각은 ms가 바뀌고 사이에 다른 줄이 낀다). 줄 단위 규칙은
키·값이 갈린 조각을 놓치므로 이어진 조각을 이은 글에서 다시 본다. 덤프 함수 이름은 코드에 두지 않는다 — 줄 모양
(`DUMP_RE`: 메시지 안 첫 `<함수>() `, oFono 디버그 `src/<파일>.c:<함수>() ` 꼴)만 보고, 함수 이름은 잇는 키에 든다.

- 잇는 규칙: `DUMP_RE` 뒤가 조각이다. 시각을 뺀 앞머리(`ident[pid]:` 이후, 함수 이름까지)가 같고 앞 조각과 시각 차가
  `0 ≤ Δ < DUMP_GAP`이면 잇는다. 사이의 다른 줄은 건너뛴다. 시각을 못 읽으면 앞머리 전체가 같은 다음 조각 줄만 잇는다.
  같은 함수가 1초 안에 찍은 줄은 덤프가 아니어도 이어 보지만, 이은 글에서는 두 줄 이상에 걸친 맞음만 쓰므로
  더 가리는 쪽으로만 달라진다.
- 입력 어댑터: 원 줄 목록 `groups_from_lines`, 파서 레코드 목록 `groups_from_records`(키 = tag·pid·msg의 `DUMP_RE`
  끝까지, 시각 = 레코드 `ts`의 `HH:MM:SS.fff`, 열 = msg 안 `DUMP_RE` 뒤).
- 묶음은 `[(순번, 조각 시작 열), ...]`(두 줄 이상)이고 순번은 원래 순번이다.
"""

from __future__ import annotations

import re

DUMP_RE = re.compile(r"(?<![\w(])[A-Za-z_]\w*\(\) ")    # 조각 앞 `<함수>() ` (이름 글자는 보지 않는다)
DUMP_GAP = 1.0                                         # 같은 메시지 조각으로 볼 시각 차(초) 상한(미만)
_DUMP_IDENT = re.compile(r"\S+\[\d+\]:")                 # ident[pid]: (앞머리에서 시각 뒤)
_DUMP_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)")


UNTIMED = "untimed"   # 시각 없는 조각의 키 머리. 시각 있는 레코드 키도 튜플이라 이것으로 가른다


def _sec(text) -> float | None:
    t = _DUMP_TIME.search(text) if isinstance(text, str) else None
    return int(t[1]) * 3600 + int(t[2]) * 60 + float(t[3]) if t else None


def _join(items) -> list[list[tuple[int, int]]]:
    """`items` = `[(순번, 열, 키, 시각 또는 None)]`. 시각이 None이면 키는 `(UNTIMED, ...)`이다(시각 없는 줄끼리만 닫는다)."""
    groups, open_ = [], {}                             # 키 -> (묶음, 마지막 시각)
    for i, col, key, sec in items:
        if sec is None:
            for k in [k for k in open_ if isinstance(k, tuple) and k[:1] == (UNTIMED,)]:
                if k != key:
                    groups.append(open_.pop(k)[0])
        prev = open_.get(key)
        if prev and (sec is None or 0 <= sec - prev[1] < DUMP_GAP):
            prev[0].append((i, col))
            open_[key] = (prev[0], sec)
            continue
        if prev:
            groups.append(prev[0])
        open_[key] = ([(i, col)], sec)
    groups += [g for g, _s in open_.values()]
    return sorted((g for g in groups if len(g) > 1), key=lambda g: g[0][0])


def groups_from_lines(lines: list[str]) -> list[list[tuple[int, int]]]:
    """원 줄 목록의 이어진 조각 묶음."""
    items = []
    for i, line in enumerate(lines):
        d = DUMP_RE.search(line)
        if d is None:
            continue
        head = line[:d.end()]
        m, sec = _DUMP_IDENT.search(line[:d.start()]), _sec(line[:d.start()])
        if m and sec is not None:
            items.append((i, d.end(), head[m.start():], sec))
        else:
            items.append((i, d.end(), (UNTIMED, head), None))
    return _join(items)


def groups_from_records(recs: list[dict]) -> list[list[tuple[int, int]]]:
    """파서 레코드 목록(`msg`·`tag`·`pid`·`ts`)의 이어진 조각 묶음. 열은 `msg` 안이다."""
    items = []
    for i, rec in enumerate(recs):
        msg = rec.get("msg") if isinstance(rec, dict) else None
        if not isinstance(msg, str):
            continue
        d = DUMP_RE.search(msg)
        if d is None:
            continue
        key = ("rec", str(rec.get("tag")), str(rec.get("pid")), msg[:d.end()])
        sec = _sec(rec.get("ts"))
        items.append((i, d.end(), key if sec is not None else (UNTIMED, key), sec))
    return _join(items)


def cross_hits(texts: list[str], rules, groups=None) -> list[tuple[str, str, list[tuple[int, int, int]]]]:
    """조각을 이은 글에서 `rules`(`[(종류, 정규식)]`)가 맞고 그 맞은 글이 **두 줄 이상에 걸친** 것만
    `[(종류, 값, [(순번, 시작 열, 끝 열), ...])]`. 값은 이름 그룹 `v`(없으면 맞은 글 전체), 조각은 값이 든 줄만이다.
    한 줄 안에서 끝나는 맞음은 줄 단위 규칙이 이미 본다. `groups`가 없으면 `groups_from_lines(texts)`."""
    out = []
    for group in groups_from_lines(texts) if groups is None else groups:
        text, starts = "", []
        for i, col in group:
            starts.append((len(text), i, col))
            text += texts[i][col:]
        bounds = [off for off, _i, _c in starts[1:]]
        for kind, rx in rules:
            for m in rx.finditer(text):
                if not any(m.start() < x < m.end() for x in bounds):
                    continue
                a, b = m.span("v") if "v" in rx.groupindex else m.span()
                pieces = []
                for k, (off, i, col) in enumerate(starts):
                    end = starts[k + 1][0] if k + 1 < len(starts) else len(text)
                    lo, hi = max(a, off), min(b, end)
                    if lo < hi:
                        pieces.append((i, col + lo - off, col + hi - off))
                if pieces:
                    out.append((kind, text[a:b], pieces))
    return out
