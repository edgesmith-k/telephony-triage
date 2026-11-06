"""`tools/make_module_repo.py` (H C1 C1D §3.4): 템플릿 → 한 커밋 모듈 레포. 네트워크·push 없음."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "make_module_repo.py"
TEMPLATES = REPO / "templates" / "module-skills"
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import skillcheck  # noqa: E402

ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", check=False, env=ENV)


@pytest.fixture(scope="module")
def src(tmp_path_factory) -> Path:
    """레포 템플릿을 담은 임시 git 레포(커밋 날짜 고정) — 실제 레포 HEAD에 기대지 않는다."""
    root = tmp_path_factory.mktemp("src")
    shutil.copytree(TEMPLATES, root / "module-skills", ignore=shutil.ignore_patterns("results", "__pycache__"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false", "commit",
                    "-q", "-m", "t", "--date", "2026-11-05T00:00:00+00:00"], cwd=str(root), check=True,
                   env={**ENV, "GIT_COMMITTER_DATE": "2026-11-05T00:00:00+00:00"})
    return root / "module-skills"


def _make(src: Path, out: Path, *extra) -> subprocess.CompletedProcess:
    return _run(out, "--templates", src, *extra)


def test_creates_single_commit_repo(src, tmp_path):
    out = tmp_path / "repo"
    proc = _make(src, out)
    assert proc.returncode == 0, proc.stderr
    sha = _git(out, "rev-parse", "HEAD")
    assert proc.stdout.strip() == f"{out} {sha}"
    assert _git(out, "rev-list", "--count", "HEAD") == "1"
    assert _git(out, "log", "-1", "--format=%an|%cn|%s").startswith("telephony-triage|telephony-triage|module-skills: import")
    assert _git(out, "branch", "--show-current") == "main"


def test_tree_equals_allowed_template_files(src, tmp_path):
    out = tmp_path / "repo"
    assert _make(src, out).returncode == 0
    tracked = set(_git(out, "ls-files").splitlines())
    want = {p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()}
    assert tracked == want
    assert all(any(rx.fullmatch(t) for rx in skillcheck.ALLOWED) for t in tracked)


def test_refuses_non_empty_out(src, tmp_path):
    out = tmp_path / "repo"
    out.mkdir()
    (out / "x").write_text("x")
    assert _make(src, out).returncode == 2


def test_refuses_out_inside_repo(src):
    assert _make(src, REPO / "tmp-module-repo-test").returncode == 2
    assert not (REPO / "tmp-module-repo-test").exists()


def test_bad_template_creates_nothing(src, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(src, bad)
    run = bad / "ofono" / "data" / "run.sh"
    run.write_text("#!/bin/sh\n")
    run.chmod(0o755)
    out = tmp_path / "repo"
    proc = _make(bad, out)
    assert proc.returncode == 1 and "ofono/data/run.sh" in proc.stdout
    assert not out.exists()


def test_no_remote_configured(src, tmp_path):
    out = tmp_path / "repo"
    assert _make(src, out).returncode == 0
    assert _git(out, "remote") == ""


def test_same_input_same_tree_sha(src, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert _make(src, a).returncode == 0 and _make(src, b, "--json").returncode == 0
    assert _git(a, "rev-parse", "HEAD^{tree}") == _git(b, "rev-parse", "HEAD^{tree}")
    assert _git(a, "rev-parse", "HEAD") == _git(b, "rev-parse", "HEAD")


def test_files_mode_644(src, tmp_path):
    out = tmp_path / "repo"
    assert _make(src, out).returncode == 0
    modes = {line.split()[0] for line in _git(out, "ls-files", "-s").splitlines()}
    assert modes == {"100644"}
    for p in out.rglob("*"):
        if p.is_file() and ".git" not in p.relative_to(out).parts:
            assert stat.S_IMODE(p.stat().st_mode) == 0o644, p
