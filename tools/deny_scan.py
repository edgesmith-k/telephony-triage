#!/usr/bin/env python3
"""레포 밖 거부 목록의 항목이 git 추적 파일에 있는지 센다 (15-local-draft.md §15.4, make_bundle `deny-file`).

거부 목록은 레포에 두지 않는다. 경로는 `--deny` 또는 환경 변수 `TT_DENY_FILE`로만 받는다(UTF-8, BOM 허용).
한 줄에 항목 하나, 빈 줄·`#` 줄은 무시. 대소문자를 무시하고, 항목의 첫/끝 글자가 단어 글자(`_` 제외)면 그쪽에
영숫자 경계를 둔다(끝이 `.`인 접두어 항목은 그쪽 경계 없음). `_`는 경계로 본다 — 식별자 안에 든 이름도 누출이다.
경계는 ASCII 영숫자(`[A-Za-z0-9]`)만 본다: 비ASCII 항목은 더 긴 비ASCII 낱말 안에서도 맞는다(두 음절 한글 항목이
세 음절 낱말 안에서도 맞음) — 거부 목록은 ASCII 식별자라 의도한 동작이다. 한 항목이 자기와 겹쳐 맞는 자리도 모두 가린다.
파일 내용과 함께 **경로 문자열도** 검사한다(경로에 맞으면 파일당 1건). 내용은 바이트를 잃지 않고 푼다: UTF-8(잘못된
바이트는 surrogateescape로 남기고 둘레 글자는 본다), BOM·NUL이 있으면 UTF-16 LE·BE(두 정렬)·UTF-32 LE·BE로도 — 건수는 그중 큰 값.
압축 형식(zip·gzip·bzip2·xz·zstd·7z 머리)과 안에 압축 스트림이 있는 PDF·PNG는 풀지 않으므로 내용을 다 보지 못한 파일(`skipped`)로 센다.
읽을 수 없는 추적 파일(삭제됨·디렉토리 등)은 읽기 실패로 센다. 둘 중 하나라도 있으면 CLI는 종료 2.
**출력에는 경로(항목 글자가 든 부분은 경계와 상관없이 `«k»`, k = 항목 번호 — 경계 없이 맞았으면 그 항목이 든 영숫자 낱말
전체)와 건수만 낸다 — 맞은 글자·항목 글자는
내지 않는다.** 경로 건수는 내용과 같은 경계 규칙으로 센다(가림만 경계 없음).
`--no-boundary`는 길이 `LOOSE_MIN`(6)자 이상 항목만 경계 없이(부분 일치) 센다 — 붙여 쓴 이름(`lib<x>.so`·`<X>Client`)도
세지만 일반 낱말 안의 우연 일치도 센다(짧은 항목은 이 모드에서도 경계를 둔다). 판정용이 아니라 참고용이다(make_bundle `deny-file`은 이 건수를 경고 줄로만 낸다).

CLI:
    python3 tools/deny_scan.py [--root <repo>] [--deny <file>] [--no-boundary] [paths...]

    paths  root 기준 경로. 없으면 `git ls-files`의 추적 파일 전부.

종료 코드 (contracts.md §종료 코드)
    0  0건
    1  1건 이상 (`경로: n건` 줄들 + `TOTAL n hits in m files (scanned s, skipped k)`)
    2  거부 목록 없음·UTF-8 아님·비어 있음, 스캔할 추적 파일 없음, 읽기 실패, 압축 파일(내용 못 봄), git 실패
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DENY_ENV = "TT_DENY_FILE"
LOOSE_MIN = 6        # 경계 없이 셀 항목의 최소 길이(`--no-boundary`·make_bundle 경고) — 짧으면 일반 낱말마다 맞는다
_EDGE_HEAD, _EDGE_TAIL = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
_PACKED = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00", b"\x28\xb5\x2f\xfd", b"7z\xbc\xaf\x27\x1c",
           b"%PDF", b"\x89PNG\r\n\x1a\n")                    # PDF·PNG는 안에 압축 스트림이 있다 — 내용을 다 못 본 파일로 센다


def load(path: Path | str) -> list[tuple[int, re.Pattern]]:
    """(항목 번호, 정규식). 항목 글자는 정규식 안에만 있다. UTF-8이 아니면 UnicodeDecodeError."""
    entries = [ln.strip() for ln in Path(path).read_text(encoding="utf-8-sig").splitlines()]
    entries = [e for e in entries if e and not e.startswith("#")]
    out = []
    for k, e in enumerate(entries, 1):
        head = _EDGE_HEAD if re.match(r"[^\W_]", e[0]) else ""   # `_`로 시작·끝나는 항목은 그쪽 경계 없음
        tail = _EDGE_TAIL if re.match(r"[^\W_]", e[-1]) else ""
        # 너비 0 lookahead: 같은 항목이 겹쳐 맞는 자리(`-a-` in `-a-a-`)도 finditer가 모두 낸다. 구간은 그룹 1
        out.append((k, re.compile("(?=(" + head + re.escape(e) + tail + "))", re.IGNORECASE)))
    return out


def tracked(root: Path | str) -> list[str]:
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files 실패 (종료 {proc.returncode})")   # stderr엔 경로가 들 수 있다
    try:
        names = proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        raise RuntimeError("git ls-files 출력이 UTF-8 아님") from None
    return [n for n in names.split("\0") if n]


def _mask(text: str, patterns, repl=None) -> tuple[str, int]:
    """원문에서 모든 항목의 일치 구간을 모아 겹친 구간은 합쳐 한 번 세고 가린다. repl 없으면 «k»(합친 구간의 가장 작은 항목 번호)."""
    spans = sorted(((*m.span(1), k) for k, rx in patterns for m in rx.finditer(text) if m.end(1) > m.start(1)),
                   key=lambda t: (t[0], -t[1]))
    merged: list[list] = []
    for start, end, k in spans:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] = min(merged[-1][2], k)
        else:
            merged.append([start, end, k])
    for start, end, k in reversed(merged):
        text = text[:start] + (repl if repl is not None else f"«{k}»") + text[end:]
    return text, len(merged)


def loose(patterns, min_len: int = 0) -> list[tuple[int, re.Pattern]]:
    """경계 없이(부분 일치) 찾는 정규식(경로 가림·`--no-boundary`). 경계가 있던 쪽은 맞은 자리를 그 영숫자 낱말 끝까지 넓힌다 —
    일반 낱말 가운데만 가리면(`ev«k»s`) 짧은 항목을 거꾸로 짐작할 수 있다. 경계대로 맞은 자리는 넓어지지 않는다(항목만).
    `min_len`보다 짧은 항목은 원래 정규식(경계 있음) 그대로 둔다(세기용). 경로 가림은 기본 0 — 모든 항목을 경계 없이 가린다."""
    word = "[A-Za-z0-9]*"
    out = []
    for k, rx in patterns:
        body = rx.pattern[len("(?=("):-len("))")]
        head, tail = body.startswith(_EDGE_HEAD), body.endswith(_EDGE_TAIL)
        core = body.removeprefix(_EDGE_HEAD).removesuffix(_EDGE_TAIL)
        if len(re.sub(r"\\(.)", r"\1", core)) < min_len:
            out.append((k, rx))
            continue
        out.append((k, re.compile("(?=(" + (word if head else "") + core + (word if tail else "") + "))", re.IGNORECASE)))
    return out


def _texts(data: bytes) -> list[str]:
    """내용을 글로 푼다(바이트를 잃지 않음): UTF-8 + surrogateescape, BOM·NUL이 있으면 UTF-16 LE·BE 두 정렬과
    UTF-32 LE·BE(처음부터 정렬)도."""
    texts = [data.decode("utf-8", "surrogateescape")]
    if b"\0" in data or data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        texts += [data[off:].decode(enc, "replace") for enc in ("utf-16-le", "utf-16-be") for off in (0, 1)]
        texts += [data[:len(data) // 4 * 4].decode(enc, "replace") for enc in ("utf-32-le", "utf-32-be")]
    return texts


def scan(root: Path | str, patterns: list[tuple[int, re.Pattern]], files: list[str] | None = None
         ) -> tuple[list[tuple[str, int]], int, int, int]:
    """(맞은 파일 [(가린 경로, 건수)], 스캔한 파일 수, 압축 형식이라 내용을 다 보지 못한 파일 수, 읽기 실패 파일 수).
    files가 없으면 추적 파일 전부."""
    root = Path(root)
    files = tracked(root) if files is None else files
    shown_rx = loose(patterns)
    hits, skipped, errors = [], 0, 0
    for rel in files:
        shown = _mask(rel, shown_rx)[0]
        n = 1 if _mask(rel, patterns)[1] else 0
        try:
            data = (root / rel).read_bytes()
        except OSError:                # 읽을 수 없는 파일(삭제됨·디렉토리·권한)
            errors += 1
        else:
            skipped += data.startswith(_PACKED)
            n += max(_mask(text, patterns, "\0")[1] for text in _texts(data))
        if n:
            hits.append((shown, n))
    return hits, len(files), skipped, errors


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure:
        reconfigure(errors="backslashreplace")   # `«k»`·도움말 한글을 못 내는 콘솔(cp949 등)에서도 죽지 않는다
    parser = argparse.ArgumentParser(prog="deny_scan.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    parser.add_argument("--deny", default=None)
    parser.add_argument("--no-boundary", action="store_true",
                        help=f"{LOOSE_MIN}자 이상 항목은 경계 없이(부분 일치) 센다 — 참고용")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    deny = args.deny or os.environ.get(DENY_ENV)
    if not deny or not Path(deny).is_file():
        print(f"거부 목록이 없습니다: --deny <file> 또는 {DENY_ENV}를 줍니다", file=sys.stderr)
        return 2
    try:
        patterns = load(deny)
    except (OSError, UnicodeDecodeError):
        print("거부 목록을 UTF-8로 읽을 수 없습니다", file=sys.stderr)
        return 2
    if not patterns:
        print("거부 목록이 비어 있습니다", file=sys.stderr)
        return 2
    try:
        rx = loose(patterns, LOOSE_MIN) if args.no_boundary else patterns
        hits, scanned, skipped, errors = scan(args.root, rx, args.paths or None)
    except (RuntimeError, OSError):   # 예외 문구에는 경로가 들 수 있어 고정 문구만 낸다
        print("추적 파일 목록을 얻지 못했습니다 (git 실패 또는 경로 오류)", file=sys.stderr)
        return 2
    if not scanned:
        print("스캔할 추적 파일 없음", file=sys.stderr)
        return 2
    for rel, n in hits:
        print(f"{rel}: {n}건")
    total = sum(n for _, n in hits)
    print(f"TOTAL {total} hits in {len(hits)} files (scanned {scanned}, skipped {skipped})")
    if errors or skipped:
        print(f"읽기 실패 {errors}개 파일, 압축 파일 {skipped}개(내용 못 봄)", file=sys.stderr)
        return 2
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
