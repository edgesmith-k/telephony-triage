#!/usr/bin/env python3
"""레포 밖 거부 목록의 항목이 git 추적 파일에 있는지 센다 (15-local-draft.md §15.4, make_bundle `deny-file`).

거부 목록은 레포에 두지 않는다. 경로는 `--deny` 또는 환경 변수 `TT_DENY_FILE`로만 받는다.
한 줄에 항목 하나, 빈 줄·`#` 줄은 무시. 대소문자를 무시하고, 항목의 첫/끝 글자가 단어 글자면 그쪽에
단어 경계를 둔다(끝이 `.`인 접두어 항목은 그쪽 경계 없음). UTF-8로 읽히지 않는 파일은 건너뛴다.
**출력에는 경로와 건수만 낸다 — 맞은 글자·항목 글자는 내지 않는다.**

CLI:
    python3 tools/deny_scan.py [--root <repo>] [--deny <file>] [paths...]

    paths  root 기준 경로. 없으면 `git ls-files`의 추적 파일 전부.

종료 코드 (contracts.md §종료 코드)
    0  0건
    1  1건 이상 (`경로: n건` 줄들 + `TOTAL n hits in m files`)
    2  거부 목록 없음·비어 있음, git 실패
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

DENY_ENV = "TT_DENY_FILE"
_EDGE_HEAD, _EDGE_TAIL = r"(?<![A-Za-z0-9_])", r"(?![A-Za-z0-9_])"


def load(path: Path | str) -> list[tuple[int, re.Pattern]]:
    """(항목 번호, 정규식). 항목 글자는 정규식 안에만 있다."""
    entries = [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()]
    entries = [e for e in entries if e and not e.startswith("#")]
    out = []
    for k, e in enumerate(entries, 1):
        head = _EDGE_HEAD if re.match(r"\w", e[0]) else ""
        tail = _EDGE_TAIL if re.match(r"\w", e[-1]) else ""
        out.append((k, re.compile(head + re.escape(e) + tail, re.IGNORECASE)))
    return out


def tracked(root: Path | str) -> list[str]:
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files 실패: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return [n for n in proc.stdout.decode("utf-8").split("\0") if n]


def scan(root: Path | str, patterns: list[tuple[int, re.Pattern]], files: list[str] | None = None
         ) -> list[tuple[str, int]]:
    """맞은 파일만 (root 기준 경로, 건수). files가 없으면 추적 파일 전부."""
    root = Path(root)
    hits = []
    for rel in tracked(root) if files is None else files:
        try:
            text = (root / rel).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):   # 바이너리·읽을 수 없는 파일(삭제됨·디렉토리)은 건너뛴다
            continue
        n = 0
        for _, rx in patterns:   # 맞은 자리는 지워 다음 항목이 겹쳐 다시 세지 않는다(접두어 안의 이름 등)
            text, c = rx.subn("\0", text)
            n += c
        if n:
            hits.append((rel, n))
    return hits


def main(argv: list[str] | None = None) -> int:
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
    patterns = load(deny)
    if not patterns:
        print("거부 목록이 비어 있습니다", file=sys.stderr)
        return 2
    try:
        hits = scan(args.root, patterns, args.paths or None)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for rel, n in hits:
        print(f"{rel}: {n}건")
    total = sum(n for _, n in hits)
    print(f"TOTAL {total} hits in {len(hits)} files")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
