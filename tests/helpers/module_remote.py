"""테스트 공용: 모의 모듈 스킬 레포를 결정적인 `file://` bare 원격으로 만들고, 변형(나쁜 mode·강제 push)을 push한다.

    build(out, src=MOCK, extra=None) -> "file://<out>/remote.git"
    push(out, files={}, modes={}, message="change", force_from=None) -> 새 sha
    head(out) -> bare main sha

`out/remote.git`(bare, main)과 `out/work`(작업 사본)를 쓴다. 커밋 시각은 out마다 1초씩 늘어나 SHA가 테스트마다 같다.
나쁜 fixture는 테스트 때만 만든다(커밋하지 않는다). `make_repo.make`는 쓰지 않는다(현재 시각·이슈 DB 원격 이름).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "tests" / "mocks" / "module-skills"
TEMPLATES = REPO / "templates" / "module-skills"
FIXED_ENV = {"GIT_AUTHOR_NAME": "Mock User", "GIT_AUTHOR_EMAIL": "mock@ghe.mock.invalid",
             "GIT_COMMITTER_NAME": "Mock User", "GIT_COMMITTER_EMAIL": "mock@ghe.mock.invalid",
             "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
_CLOCK: dict[str, int] = {}


def _git(cwd: Path, *args: str, out: Path, stdin: bytes | None = None) -> str:
    n = _CLOCK[str(out)] = _CLOCK.get(str(out), 0) + 1
    date = f"2026-09-20T00:{n // 60:02d}:{n % 60:02d}+00:00"
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(FIXED_ENV, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    proc = subprocess.run(["git", "-C", str(cwd), *args], input=stdin, capture_output=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout.decode("utf-8", "replace")


def _write(work: Path, files: dict) -> None:
    for rel, data in files.items():
        path = work / rel
        if data is None:
            if path.exists():
                _git(work, "rm", "-q", "--cached", "--", rel, out=work.parent)
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else str(data).encode("utf-8"))


def build(out: Path, src: Path = MOCK, extra: dict | None = None) -> str:
    """`src` 트리(+ extra 파일: bytes 쓰기, None 지우기)를 커밋한 bare 원격. 원격 URL(file://)을 돌려준다."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    bare, work = out / "remote.git", out / "work"
    _git(out, "init", "-q", "--bare", "-b", "main", str(bare), out=out)
    shutil.copytree(src, work, ignore=shutil.ignore_patterns("results"))
    _git(work, "init", "-q", "-b", "main", out=out)
    for rel, data in (extra or {}).items():
        path = work / rel
        if data is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else str(data).encode("utf-8"))
    _git(work, "add", "-A", out=out)
    _git(work, "commit", "-q", "-m", "mock", out=out)
    _git(work, "remote", "add", "origin", str(bare), out=out)
    _git(work, "push", "-q", "origin", "main", out=out)
    return "file://" + str(bare.resolve())


def push(out: Path, files: dict | None = None, modes: dict | None = None, message: str = "change",
         force_from: str | None = None) -> str:
    """변경을 커밋해 push한다. modes: path → "120000:<대상>" | "100755" | "160000:<sha>"(색인만, Windows에서도 된다).
    force_from: 먼저 `reset --hard <rev>` 하고 커밋한 뒤 `push -f`."""
    out = Path(out)
    work = out / "work"
    if force_from:
        _git(work, "reset", "-q", "--hard", force_from, out=out)
    _write(work, files or {})
    _git(work, "add", "-A", out=out)
    for rel, mode in (modes or {}).items():
        if mode == "100755":
            _git(work, "update-index", "--chmod=+x", "--", rel, out=out)
            continue
        kind, _, arg = mode.partition(":")
        if kind == "120000":
            sha = _git(work, "hash-object", "-w", "--stdin", out=out, stdin=arg.encode("utf-8")).strip()
        else:
            sha = arg
        _git(work, "update-index", "--add", "--cacheinfo", f"{kind},{sha},{rel}", out=out)
    _git(work, "commit", "-q", "--allow-empty", "-m", message, out=out)
    _git(work, "push", "-q", *(["-f"] if force_from else []), "origin", "main", out=out)
    return head(out)


def head(out: Path) -> str:
    return _git(Path(out) / "remote.git", "rev-parse", "main", out=Path(out)).strip()
