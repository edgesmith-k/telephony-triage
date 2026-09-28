#!/usr/bin/env python3
"""POSIX 실행 스크립트의 git index 모드를 100755로 맞춘다.

실행 환경은 Ubuntu다 (`01-architecture.md §3`, `14-site.md` S15).
`.githooks/pre-commit`·`pre-push`, `tests/mocks/bin/gh` 같은 파일은 **커밋된
트리에서 100755**여야 다른 기여자 PC에서 실행된다.

`core.filemode`가 `false`인 환경(Windows 개발 PC 등)에서는 `git add`가 모드를
100644로 기록하므로, 커밋 전에 이 도구로 index 모드를 명시한다. Ubuntu에서는
이미 100755라 아무것도 바뀌지 않는다.

CLI:
    python3 tools/fix_exec_bits.py [--check] [--json]

    --check  바꾸지 않고 어긋난 파일만 보고한다 (어긋나면 종료 코드 1)

종료 코드 (contracts.md §종료 코드)
    0  모두 맞음 / 맞춤
    1  --check 에서 어긋난 파일이 있음
    2  사용 오류·환경 오류
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 100755여야 하는 파일 (레포 기준 상대 경로 glob).
EXEC_GLOBS = [
    "**/.githooks/*",
    "tests/mocks/bin/gh",
]
# 셰뱅(`#!`)으로 시작하는 파일도 대상에 넣는다. 다만 라이브러리로만 쓰는
# 모듈(`__init__.py`)은 제외한다.
SHEBANG_EXCLUDE = {"__init__.py"}
OK, CHECK_FAILED, USAGE = 0, 1, 2


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def tracked_or_staged() -> dict[str, str]:
    """index에 있는 파일의 {상대경로: 모드}."""
    out: dict[str, str] = {}
    for line in _git(["ls-files", "-s"]).splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        out[path] = meta.split()[0]
    return out


def _has_shebang(path: Path) -> bool:
    if path.name in SHEBANG_EXCLUDE:
        return False
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def wanted() -> list[str]:
    paths: set[str] = set()
    for pattern in EXEC_GLOBS:
        for path in REPO.glob(pattern):
            if path.is_file():
                paths.add(path.relative_to(REPO).as_posix())
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO)
        if ".git" in rel.parts or "__pycache__" in rel.parts:
            continue
        if _has_shebang(path):
            paths.add(rel.as_posix())
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fix_exec_bits.py", description=__doc__)
    parser.add_argument("--check", action="store_true", help="바꾸지 않고 보고만 한다")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        staged = tracked_or_staged()
    except subprocess.CalledProcessError as exc:
        print(f"git 호출 실패: {exc.stderr.strip()}", file=sys.stderr)
        return USAGE

    targets = wanted()
    wrong = [rel for rel in targets if staged.get(rel) not in (None, "100755")]
    untracked = [rel for rel in targets if rel not in staged]

    if args.check:
        payload = {"wrong_mode": wrong, "untracked": untracked}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            if wrong:
                print("index 모드가 100755가 아닌 실행 스크립트:")
                for rel in wrong:
                    print(f"  - {rel} ({staged.get(rel)})")
            if untracked:
                print("아직 git에 없는 실행 스크립트 (add 후 다시 실행):")
                for rel in untracked:
                    print(f"  - {rel}")
            if not wrong and not untracked:
                print("모두 100755입니다.")
        return CHECK_FAILED if wrong else OK

    changed = []
    for rel in wrong:
        _git(["update-index", "--chmod=+x", rel])
        changed.append(rel)

    if args.json:
        print(json.dumps({"changed": changed, "untracked": untracked}, ensure_ascii=False, indent=2))
    else:
        for rel in changed:
            print(f"100755 <- {rel}")
        if untracked:
            print("아직 git에 없어 건너뛴 파일 (add 후 다시 실행):")
            for rel in untracked:
                print(f"  - {rel}")
        if not changed and not untracked:
            print("바꿀 것이 없습니다.")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
