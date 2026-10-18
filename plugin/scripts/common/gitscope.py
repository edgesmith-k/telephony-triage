"""검사 범위와 git 헬퍼 (contracts.md §3.2 공통 규칙).

- `--staged`: index 내용이 기준이다. unstaged 변경은 무시한다. 비교 기준(base)은 `HEAD`.
- `--changed <ref>`: `git merge-base <ref> HEAD`와 현재 워킹 트리의 차이. base는 그 merge-base.
- 바뀐 파일 목록은 `--no-renames`로 만든다: 이름이 바뀐 파일은 옛 경로(삭제)와 새 경로가 모두 범위다.
- `--ref <ref>`: 그 커밋의 트리.

index·ref의 트리가 필요하면 임시 디렉토리로 꺼낸다(`materialize_*`). 사용자 워킹 트리는
바꾸지 않는다. 비교 기준(base) 트리는 fixture 로그를 빼고 꺼낸다(`materialize_ref_sparse`).

경로는 DB 루트(`repo`) 기준이다: `repo`가 레포의 하위 디렉토리면 파일 목록은 그 하위 안 파일만, 꺼낸 트리는
그 하위만 낸다(최상위 DB에서는 레포 최상위 기준과 같다).
"""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from pathlib import Path


_HAS_DATA_FILTER = hasattr(tarfile, "data_filter")


class GitError(Exception):
    pass


def git(repo: Path, *args: str, binary: bool = False, env: dict | None = None, input: bytes | None = None):
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, env=env, input=input)
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} 실패: {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace")


def merge_base(repo: Path, ref: str) -> str:
    return git(repo, "merge-base", ref, "HEAD").strip()


def changed_files(repo: Path, ref: str) -> list[str]:
    """`merge-base <ref> HEAD` 이후 바뀐 파일(워킹 트리 기준, 추적 안 된 새 파일 포함, 삭제 포함)."""
    base = merge_base(repo, ref)
    names = git(repo, "diff", "--relative", "--name-only", "--no-renames", "-z", base).split("\0")
    names += git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0")     # 이미 repo 기준
    return sorted(set(filter(None, names)))


def staged_files(repo: Path) -> list[str]:
    names = git(repo, "diff", "--cached", "--relative", "--name-only", "--no-renames", "-z").split("\0")
    return sorted(set(filter(None, names)))


def materialize_index(repo: Path, dest: Path) -> Path:
    """index 내용을 `dest`로 꺼낸다. 환경의 `GIT_INDEX_FILE`(hook의 `commit -a` 임시 index 등)을 그대로 따른다.

    `repo`가 하위 디렉토리면 그 하위의 index 항목(`ls-files -s`, 경로는 하위 기준)을 `dest` 옆 임시 index에 옮겨
    꺼낸다(`materialize_ref_sparse`와 같은 상대 경로·같은 `.gitattributes` 적용: DB 안의 것만)."""
    dest.mkdir(parents=True, exist_ok=True)
    prefix = str(dest.resolve()).replace("\\", "/").rstrip("/") + "/"
    if not git(repo, "rev-parse", "--show-prefix").strip():
        git(repo, "checkout-index", "-a", "-f", f"--prefix={prefix}")
        return dest
    entries = git(repo, "ls-files", "-s", "-z", binary=True)
    top = Path(git(repo, "rev-parse", "--show-toplevel").strip())
    index = dest.parent.resolve() / f".{dest.name}.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        git(top, "update-index", "-z", "--index-info", env=env, input=entries)
        git(top, "checkout-index", "-a", "-f", f"--prefix={prefix}", env=env)
    finally:
        index.unlink(missing_ok=True)
    return dest


def materialize_ref(repo: Path, ref: str, dest: Path) -> Path:
    """커밋 `ref`의 트리를 `dest`로 꺼낸다."""
    data = git(repo, "archive", "--format=tar", ref, binary=True)
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        if _HAS_DATA_FILTER:                          # 3.11.4+·3.12+ (PEP 706)
            tar.extractall(dest, filter="data")
        else:                                         # 3.11.0~3.11.3 (예: Ubuntu 22.04 python3.11): 같은 기준을 직접 검사
            tar.extractall(dest, members=_safe_members(tar, dest))
    return dest


# 기준(base) 트리를 읽는 쪽(이슈 정의·parser-rules·schema)은 fixture 로그를 읽지 않는다 (`<카테고리>/<유형>/fixtures/`)
NO_FIXTURES = (":(exclude,glob)*/*/fixtures/**",)


def materialize_ref_sparse(repo: Path, ref: str, dest: Path, exclude: tuple[str, ...] = NO_FIXTURES) -> Path:
    """커밋 `ref`의 트리에서 `exclude` pathspec을 뺀 파일만 `dest`로 꺼낸다.

    `dest` 옆(호출자의 임시 디렉토리 안)의 임시 index에 `read-tree` → `ls-files` → `checkout-index`. 사용자
    index·워킹 트리는 건드리지 않는다(`GIT_INDEX_FILE`은 이 세 호출에서만 덮어쓴다). `repo`가 레포의 하위
    디렉토리면 그 하위 트리(`<ref>:<prefix>`)만 꺼낸다(`materialize_ref`의 git archive와 같은 상대 경로).
    쓰기는 git이 하므로 eol·필터 변환은 git archive와 같다(최상위 DB 기준). 다른 점:
    - `export-ignore`·`export-subst` 속성을 따르지 않는다(이슈 DB는 이 속성을 쓰지 않는다).
    - 심볼릭 링크는 그대로 쓴다(archive 경로의 대상 밖 링크 검사 없음, 입력은 사용자 자신의 ref).
    - ref에 `.gitattributes`가 없으면 워킹 트리의 `.gitattributes`를 쓴다(git checkout 방향 규칙).
    - 워킹 트리가 있어야 한다(bare 레포는 실패).
    - 하위 디렉토리 DB면 그 DB 안의 `.gitattributes`만 적용한다(archive는 하위 것을 무시해 autocrlf면 CRLF).
    """
    top = Path(git(repo, "rev-parse", "--show-toplevel").strip())
    sub = git(repo, "rev-parse", "--show-prefix").strip().rstrip("/")
    dest.mkdir(parents=True, exist_ok=True)
    tree = f"{ref}^{{tree}}"
    if sub:
        commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()      # 잘못된 ref는 GitError
        tree = f"{commit}:{sub}"
        if not git(top, "ls-tree", "-d", commit, "--", sub).strip():   # 손상 등 git 오류는 GitError
            return dest                                # 그 ref에 DB가 없다: 빈 기준(전부 새것)
    index = dest.parent.resolve() / f".{dest.name}.index"
    env = {k: v for k, v in os.environ.items() if k != "GIT_LITERAL_PATHSPECS"}   # exclude·glob 매직이 꺼지지 않게
    env["GIT_INDEX_FILE"] = str(index)
    prefix = str(dest.resolve()).replace("\\", "/").rstrip("/") + "/"
    try:                                               # 임시 index의 경로는 하위 트리 기준이므로 레포 최상위에서 부른다
        git(top, "read-tree", tree, env=env)
        names = git(top, "ls-files", "-z", "--", ".", *exclude, env=env, binary=True)
        git(top, "checkout-index", "-f", "-z", "--stdin", f"--prefix={prefix}", env=env, input=names)
    finally:
        index.unlink(missing_ok=True)
    return dest


def _safe_members(tar: tarfile.TarFile, dest: Path) -> list[tarfile.TarInfo]:
    """`filter="data"`가 없는 Python용: 일반 파일·디렉토리·dest 안을 가리키는 링크만 허용, 나머지는 거부."""
    root = dest.resolve()
    members = []
    for member in tar.getmembers():
        target = (root / member.name).resolve()
        if member.name.startswith(("/", "\\")) or (target != root and root not in target.parents):
            raise GitError(f"git archive 항목이 대상 밖을 가리킨다: {member.name}")
        if member.issym() or member.islnk():
            link = (target.parent / member.linkname).resolve() if member.issym() else (root / member.linkname).resolve()
            if link != root and root not in link.parents:
                raise GitError(f"git archive 링크가 대상 밖을 가리킨다: {member.name} -> {member.linkname}")
        elif not (member.isfile() or member.isdir()):
            raise GitError(f"git archive 항목 종류를 풀지 않는다: {member.name}")
        member.mode &= 0o755 if member.isdir() or member.mode & 0o111 else 0o644
        members.append(member)
    return members


def has_ref(repo: Path, ref: str) -> bool:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                          capture_output=True)
    return proc.returncode == 0
