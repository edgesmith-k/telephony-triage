"""검사 범위와 git 헬퍼 (contracts.md §3.2 공통 규칙).

- `--staged`: index 내용이 기준이다. unstaged 변경은 무시한다. 비교 기준(base)은 `HEAD`.
- `--changed <ref>`: `git merge-base <ref> HEAD`와 현재 워킹 트리의 차이. base는 그 merge-base.
- `--ref <ref>`: 그 커밋의 트리.

index·ref의 트리가 필요하면 임시 디렉토리로 꺼낸다(`materialize_*`). 사용자 워킹 트리는
바꾸지 않는다.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path


class GitError(Exception):
    pass


def git(repo: Path, *args: str, binary: bool = False):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 실패: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def merge_base(repo: Path, ref: str) -> str:
    return git(repo, "merge-base", ref, "HEAD").strip()


def changed_files(repo: Path, ref: str) -> list[str]:
    """`merge-base <ref> HEAD` 이후 바뀐 파일(워킹 트리 기준, 추적 안 된 새 파일 포함, 삭제 포함)."""
    base = merge_base(repo, ref)
    names = git(repo, "diff", "--name-only", "-z", base).split("\0")
    names += git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted(set(filter(None, names)))


def staged_files(repo: Path) -> list[str]:
    return sorted(set(filter(None, git(repo, "diff", "--cached", "--name-only", "-z").split("\0"))))


def materialize_index(repo: Path, dest: Path) -> Path:
    """index 내용을 `dest`로 꺼낸다."""
    dest.mkdir(parents=True, exist_ok=True)
    prefix = str(dest.resolve()).replace("\\", "/").rstrip("/") + "/"
    git(repo, "checkout-index", "-a", "-f", f"--prefix={prefix}")
    return dest


def materialize_ref(repo: Path, ref: str, dest: Path) -> Path:
    """커밋 `ref`의 트리를 `dest`로 꺼낸다."""
    data = git(repo, "archive", "--format=tar", ref, binary=True)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")
    return dest


def has_ref(repo: Path, ref: str) -> bool:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          capture_output=True)
    return proc.returncode == 0
