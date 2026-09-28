"""`--db <path>` 기본값 (contracts.md §3.2 공통 규칙).

1. `--db`를 주면 그 값.
2. 생략했고 cwd가 이슈 DB 레포(또는 worktree) 안이면 `git rev-parse --show-toplevel`
   (toplevel에 `issue-db.config.yaml`이 있을 때).
3. 그 밖에는 사용자 config의 `issue_db.path` (Phase 6에서 연결한다).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

CONFIG = "issue-db.config.yaml"


class DbPathError(Exception):
    pass


def git_toplevel(cwd: str | Path | None = None) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return Path(proc.stdout.strip())


def resolve(arg: str | None, cwd: str | Path | None = None, user_config_path=None) -> Path:
    if arg:
        path = Path(arg).expanduser()
        if not (path / CONFIG).is_file():
            raise DbPathError(f"이슈 DB가 아닙니다({CONFIG} 없음): {path}")
        return path
    top = git_toplevel(cwd)
    if top is not None and (top / CONFIG).is_file():
        return top
    if user_config_path is not None:
        path = user_config_path()
        if path is not None:
            path = Path(path).expanduser()
            if (path / CONFIG).is_file():
                return path
            raise DbPathError(f"config의 issue_db.path가 이슈 DB가 아닙니다: {path}")
    raise DbPathError("--db가 필요합니다 (cwd가 이슈 DB가 아니고 config의 issue_db.path도 없습니다).")
