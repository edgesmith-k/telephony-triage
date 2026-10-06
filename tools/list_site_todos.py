#!/usr/bin/env python3
"""`TODO(SITE:S<n>)` 목록을 뽑는다 (15-local-draft.md §15.4).

반입 전 체크리스트에서 이 결과를 `DRAFT_NOTES.md`의 "사내 확인 목록"에
S번호별로 묶어서 갱신한다. S번호는 `14-site.md §14.2` 레지스트리 번호다.

CLI:
    python3 tools/list_site_todos.py [--root <dir>] [--json | --markdown]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"TODO\(SITE:(?P<id>S\d+)\)(?P<rest>[^\n]*)")

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    # 설계 문서 자체는 placeholder를 설명하는 곳이므로 목록에서 뺀다.
    # 확인 대상은 코드·설정·모의 데이터에 남긴 표시다.
    "docs",
}
SKIP_FILES = {"list_site_todos.py", "DRAFT_NOTES.md"}
TEXT_SUFFIXES = {
    ".py", ".yaml", ".yml", ".json", ".md", ".sh", ".txt", ".mk",
    ".java", ".c", ".h", ".cfg", ".ini", ".toml", "",
}


def candidates(root: Path) -> list[Path]:
    """git이 추적·비추적(무시 제외)으로 보는 파일. git이 없으면(반입 묶음 등) rglob."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8", errors="replace")
        # 다른 레포의 무시 경로에 풀린 묶음이면 git은 빈 목록을 준다 → rglob
        return sorted(root / p for p in out.split(chr(0)) if p) or sorted(root.rglob("*"))
    except (OSError, subprocess.CalledProcessError):
        return sorted(root.rglob("*"))


def scan(root: Path) -> dict[str, list[dict]]:
    found: dict[str, list[dict]] = defaultdict(list)
    for path in candidates(root):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in PATTERN.finditer(line):
                found[match.group("id")].append(
                    {
                        "file": path.relative_to(root).as_posix(),
                        "line": number,
                        "note": match.group("rest").strip(" :-"),
                        "context": line.strip()[:160],
                    }
                )
    return dict(sorted(found.items(), key=lambda kv: int(kv[0][1:])))


def to_markdown(found: dict[str, list[dict]]) -> str:
    if not found:
        return "사외 초안에 남은 `TODO(SITE:S<n>)`가 없습니다.\n"
    out = []
    for site_id, items in found.items():
        out.append(f"### {site_id} ({len(items)}곳)")
        for item in items:
            note = f" — {item['note']}" if item["note"] else ""
            out.append(f"- `{item['file']}:{item['line']}`{note}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="list_site_todos.py", description=__doc__)
    parser.add_argument("--root", default=str(REPO), help="훑을 루트 (기본: 레포 루트)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true")
    group.add_argument("--markdown", action="store_true", help="기본값")
    args = parser.parse_args(argv)

    found = scan(Path(args.root).resolve())
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(to_markdown(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
