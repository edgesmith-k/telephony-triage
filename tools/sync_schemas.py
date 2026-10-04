#!/usr/bin/env python3
"""이슈 DB 스키마 사본 `plugin/schemas/` 동기화 (ARCHITECTURE_REVIEW_2026-10.md RF-2).

단일 원본은 이슈 DB 레포의 `schema/`다. 플러그인은 사본을 들고 있어서 DB 없이도
계획·fixture 기대값을 검증할 수 있고, 사본과 DB가 다르면 버전 불일치를 알 수 있다.
사외에서는 합성 샘플 `tests/fixtures/issue-db-sample/`이 원본 자리다.

CLI:
    python3 tools/sync_schemas.py --check [--db <이슈 DB>]   # 다르면 종료 코드 1
    python3 tools/sync_schemas.py --write [--db <이슈 DB>]   # 원본으로 사본을 덮어씀

`--check`에 `--db`가 없으면 합성 샘플과 대조한다 (변형은 테스트 실행 때 샘플 schema를 그대로 복사해
만들므로 따로 대조하지 않는다).

종료 코드: 0 같음·갱신함 / 1 다름 / 2 사용 오류
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
COPY = REPO / "plugin" / "schemas"
SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"

OK, DIFFERENT, USAGE = 0, 1, 2


def schema_files(directory: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(directory.glob("*.schema.json"))}


def compare(copy: dict[str, bytes], source: dict[str, bytes]) -> list[str]:
    problems = []
    for name in sorted(set(copy) | set(source)):
        if name not in source:
            problems.append(f"{name}: 원본에 없음")
        elif name not in copy:
            problems.append(f"{name}: 사본에 없음")
        elif copy[name] != source[name]:
            problems.append(f"{name}: 내용이 다름")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync_schemas.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--db", default=None, help="원본 이슈 DB (기본: 합성 샘플)")
    args = parser.parse_args(argv)

    db = Path(args.db).resolve() if args.db else SAMPLE
    if not (db / "schema").is_dir():
        print(f"스키마 디렉토리가 없습니다: {db / 'schema'}", file=sys.stderr)
        return USAGE

    if args.write:
        COPY.mkdir(parents=True, exist_ok=True)
        for stale in set(schema_files(COPY)) - set(schema_files(db / "schema")):
            (COPY / stale).unlink()
        for path in sorted((db / "schema").glob("*.schema.json")):
            shutil.copyfile(path, COPY / path.name)
        print(f"plugin/schemas/ ← {db / 'schema'}")
        return OK

    copy = schema_files(COPY)
    sources = [db / "schema"] if args.db else [SAMPLE / "schema"]
    failed = False
    for source in sources:
        problems = compare(copy, schema_files(source))
        if problems:
            failed = True
            print(f"plugin/schemas/ ≠ {source}:", file=sys.stderr)
            for line in problems:
                print(f"  - {line}", file=sys.stderr)
    if failed:
        print("원본이 맞으면 `python3 tools/sync_schemas.py --write`로 사본을 갱신한다. "
              "DB 스키마 버전이 바뀐 것이면 사용자에게 보고한다.", file=sys.stderr)
        return DIFFERENT
    print(f"plugin/schemas/ 동기화됨 ({len(copy)}개, 대조 {len(sources)}곳)")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
