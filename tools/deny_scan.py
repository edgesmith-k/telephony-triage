#!/usr/bin/env python3
"""레포 밖 거부 목록의 항목이 git 추적 파일에 있는지 센다 (15-local-draft.md §15.4, make_bundle `deny-file`).

거부 목록은 레포에 두지 않는다. 경로는 `--deny` 또는 환경 변수 `TT_DENY_FILE`로만 받는다(UTF-8, BOM 허용).
한 줄에 항목 하나, 빈 줄·`#` 줄은 무시. 대소문자를 무시하고, 항목의 첫/끝 글자가 단어 글자(`_` 제외)면 그쪽에
영숫자 경계를 둔다(끝이 `.`인 접두어 항목은 그쪽 경계 없음). `_`는 경계로 본다 — 식별자 안에 든 이름도 누출이다.
파일 내용과 함께 **경로 문자열도** 검사한다(경로에 맞으면 파일당 1건). UTF-8로 읽히지 않는 파일은 내용을 건너뛰고 센다.
읽을 수 없는 추적 파일(삭제됨·디렉토리 등)은 읽기 실패로 세고 CLI는 종료 2.
**출력에는 경로(맞은 부분은 `«k»`, k = 항목 번호)와 건수만 낸다 — 맞은 글자·항목 글자는 내지 않는다.**

CLI:
    python3 tools/deny_scan.py [--root <repo>] [--deny <file>] [paths...]

    paths  root 기준 경로. 없으면 `git ls-files`의 추적 파일 전부.

종료 코드 (contracts.md §종료 코드)
    0  0건
    1  1건 이상 (`경로: n건` 줄들 + `TOTAL n hits in m files (scanned s, skipped k)`)
    2  거부 목록 없음·UTF-8 아님·비어 있음, 스캔할 추적 파일 없음, 읽기 실패, git 실패
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DENY_ENV = "TT_DENY_FILE"
_EDGE_HEAD, _EDGE_TAIL = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"


def load(path: Path | str) -> list[tuple[int, re.Pattern]]:
    """(항목 번호, 정규식). 항목 글자는 정규식 안에만 있다. UTF-8이 아니면 UnicodeDecodeError."""
    entries = [ln.strip() for ln in Path(path).read_text(encoding="utf-8-sig").splitlines()]
    entries = [e for e in entries if e and not e.startswith("#")]
    out = []
    for k, e in enumerate(entries, 1):
        head = _EDGE_HEAD if re.match(r"[^\W_]", e[0]) else ""   # `_`로 시작·끝나는 항목은 그쪽 경계 없음
        tail = _EDGE_TAIL if re.match(r"[^\W_]", e[-1]) else ""
        out.append((k, re.compile(head + re.escape(e) + tail, re.IGNORECASE)))
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
    spans = sorted(((m.start(), m.end(), k) for k, rx in patterns for m in rx.finditer(text) if m.end() > m.start()),
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


def scan(root: Path | str, patterns: list[tuple[int, re.Pattern]], files: list[str] | None = None
         ) -> tuple[list[tuple[str, int]], int, int, int]:
    """(맞은 파일 [(가린 경로, 건수)], 스캔한 파일 수, UTF-8 아니라 내용을 건너뛴 파일 수, 읽기 실패 파일 수).
    files가 없으면 추적 파일 전부."""
    root = Path(root)
    files = tracked(root) if files is None else files
    hits, skipped, errors = [], 0, 0
    for rel in files:
        shown, in_path = _mask(rel, patterns)
        n = 1 if in_path else 0
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except OSError:                # 읽을 수 없는 파일(삭제됨·디렉토리·권한)
            errors += 1
        except UnicodeDecodeError:     # 바이너리
            skipped += 1
        else:
            n += _mask(text, patterns, "\0")[1]
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
        hits, scanned, skipped, errors = scan(args.root, patterns, args.paths or None)
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
    if errors:
        print(f"읽기 실패 {errors}개 파일", file=sys.stderr)
        return 2
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
