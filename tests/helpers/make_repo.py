#!/usr/bin/env python3
"""파일 트리에서 임시 git 레포와 bare 원격을 만드는 테스트 헬퍼.

`01-architecture.md §3`, `11-phases.md` Phase D0·1.

Phase 1이 만드는 합성 샘플 트리(`tests/fixtures/issue-db-sample/`)를 넣으면
사용자 clone 역할을 하는 작업 레포와 모의 GHE 역할을 하는 bare 원격
(`<dest>/remote/telephony-issue-db.git`)이 생긴다. Phase D0에서는 임의의
트리로 push·PR 경로를 시험하는 데 쓴다.

CLI:
    python3 tests/helpers/make_repo.py <src_tree> [--out <dir>] [--json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REMOTE_NAME = "telephony-issue-db.git"
DEFAULT_BRANCH = "main"

# 커밋 시 실행 비트를 세워야 하는 파일 (contracts.md는 .githooks/* 를 100755로 본다).
EXEC_SUFFIXES = {".sh", ".py"}
EXEC_DIRS = {".githooks"}


def _git(args: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        **kwargs,
    )


def _wants_exec_bit(root: Path, path: Path) -> bool:
    rel = path.relative_to(root)
    if rel.parts and rel.parts[0] in EXEC_DIRS:
        return True
    if path.suffix in EXEC_SUFFIXES:
        return True
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def _apply_exec_bits(work: Path) -> list[str]:
    """index의 모드를 100755로 맞춘다.

    Ubuntu에서는 파일 모드가 그대로 따라오므로 대부분 무동작이다.
    Windows 개발 PC는 `core.filemode`가 false라 실행 비트가 사라지므로
    `git update-index --chmod=+x`로 명시한다. 커밋되는 결과(트리의 100755)는
    양쪽이 같다.
    """
    marked = []
    for path in sorted(work.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        if _wants_exec_bit(work, path):
            rel = path.relative_to(work).as_posix()
            _git(["update-index", "--chmod=+x", rel], work)
            marked.append(rel)
    return marked


def make(src: Path, out: Path | None = None) -> dict:
    src = Path(src).resolve()
    if not src.is_dir():
        raise SystemExit(f"{src} 이(가) 디렉토리가 아닙니다.")
    base = Path(out) if out else Path(tempfile.mkdtemp(prefix="tt-repo-"))
    if out and base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)

    remote = base / "remote" / REMOTE_NAME
    remote.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch", DEFAULT_BRANCH, str(remote)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )

    work = base / "clone"
    shutil.copytree(src, work, dirs_exist_ok=True)
    _git(["init", "--initial-branch", DEFAULT_BRANCH], work)
    _git(["config", "user.name", "Mock User"], work)
    _git(["config", "user.email", "mock-user@ghe.mock.invalid"], work)
    _git(["config", "commit.gpgsign", "false"], work)
    _git(["add", "-A"], work)
    marked = _apply_exec_bits(work)
    _git(["commit", "-m", "초기 커밋 (테스트 헬퍼)"], work)
    _git(["remote", "add", "origin", str(remote)], work)
    _git(["push", "-u", "origin", DEFAULT_BRANCH], work)

    return {
        "base": str(base),
        "clone": str(work),
        "remote": str(remote),
        "branch": DEFAULT_BRANCH,
        "exec_bits": marked,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_repo.py", description=__doc__)
    parser.add_argument("src", help="레포로 만들 파일 트리")
    parser.add_argument("--out", default=None, help="만들 경로 (기본: 임시 디렉토리)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    info = make(Path(args.src), Path(args.out) if args.out else None)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        for key, value in info.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
