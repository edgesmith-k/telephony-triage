"""RF-0 regressions; all plugin code and configuration run from temporary roots."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
from runner import plugin_root, git  # noqa: E402


@pytest.fixture
def safety_root(monkeypatch):
    root = plugin_root("safety")
    monkeypatch.syspath_prepend(str(root / "scripts"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    return root


def test_r6_commit_message_is_file_data(safety_root, tmp_path):
    for relative in ("skills/telephony-triage/reference/write-flow.md", "commands/sync-pr.md"):
        instructions = (safety_root / relative).read_text(encoding="utf-8")
        assert "commit -m" not in instructions
        assert "commit -F" in instructions
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "data").write_text("synthetic", encoding="utf-8")
    message = 'RF-0 "quoted" $(touch INJECTED) `touch INJECTED` $HOME\n\nsecond line'
    message_file = tmp_path / "message.txt"
    message_file.write_text(message, encoding="utf-8")
    git(repo, "add", "data")
    git(repo, "commit", "-F", str(message_file))
    assert git(repo, "log", "-1", "--format=%B").rstrip() == message
    assert not (repo / "INJECTED").exists()


def test_r2_corrupt_lock_fails_closed(safety_root, tmp_path):
    module = importlib.import_module("db_pr")
    (tmp_path / "session.lock").write_text("{broken", encoding="utf-8")
    with pytest.raises(module.UsageError):
        module.Lock(tmp_path).acquire("job", None, False)


def test_r2_stale_owner_cannot_touch_or_release(safety_root, tmp_path):
    module = importlib.import_module("db_pr")
    old = module.Lock(tmp_path)
    old.acquire("job", None, False)
    new = module.Lock(tmp_path)
    new.acquire("job", None, True)
    for action in (lambda: old.touch("job"), lambda: old.release("job", False)):
        with pytest.raises(module.UsageError):
            action()
    assert new.read()["owner"] == new.owner


def test_r2_concurrent_processes_only_one_acquires(safety_root, tmp_path):
    script = '''import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from db_pr import Lock, UsageError
class SlowLock(Lock):
    def read(self):
        held = super().read()
        time.sleep(.15)
        return held
try:
    SlowLock(Path(sys.argv[2])).acquire(sys.argv[3], None, False)
except UsageError:
    sys.exit(2)
'''
    processes = [subprocess.Popen([sys.executable, "-c", script, str(safety_root / "scripts"),
                                  str(tmp_path), str(i)]) for i in range(4)]
    assert sorted(p.wait(timeout=15) for p in processes) == [0, 2, 2, 2]


def safety_ctx(tmp_path):
    module = importlib.import_module("db_pr")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "--allow-empty", "-qm", "synthetic")
    work = tmp_path / "work"
    lock = module.Lock(work)
    lock.acquire("job", None, False)
    return module, module.Ctx({"issue_db": {"path": str(repo)}, "work_dir": str(work)}, lock)


@pytest.mark.parametrize("location", ["outside", "plain", "foreign", "user-branch"])
def test_r3_remove_refuses_unowned_paths(safety_root, tmp_path, location):
    module, ctx = safety_ctx(tmp_path)
    target = (tmp_path / "outside" / "job" / "wt" if location == "outside"
              else ctx.work_dir / "job" / "wt")
    target.mkdir(parents=True)
    if location == "foreign":
        git(target, "init", "-q")
    if location == "user-branch":
        git(ctx.repo, "worktree", "add", "-b", "user", str(target))
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(module.UsageError):
        module._remove_worktree(ctx, target)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_r3_git_remove_failure_preserves_files(safety_root, tmp_path, monkeypatch):
    module, ctx = safety_ctx(tmp_path)
    target = ctx.work_dir / "job" / "wt"
    git(ctx.repo, "worktree", "add", "-b", "tt/job", str(target))
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    original = module._git
    def fail_remove(repo, *args, **kwargs):
        if args[:2] == ("worktree", "remove"):
            if kwargs.get("check", True):
                raise module.UsageError("synthetic removal failure")
            return subprocess.CompletedProcess(args, 1, "", "failure")
        return original(repo, *args, **kwargs)
    monkeypatch.setattr(module, "_git", fail_remove)
    with pytest.raises(module.UsageError):
        module._remove_worktree(ctx, target)
    assert marker.exists()


def test_r3_prepare_refuses_foreign_repo(safety_root, tmp_path):
    module, ctx = safety_ctx(tmp_path)
    target = ctx.work_dir / "job" / "wt"
    target.mkdir(parents=True)
    git(target, "init", "-q")
    git(target, "commit", "--allow-empty", "-qm", "foreign")
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(module.UsageError):
        module._prepare_worktree(ctx, target, "tt/job", "HEAD")
    assert marker.exists()


def test_r3_draft_and_symlink_boundaries(safety_root, tmp_path, monkeypatch):
    module, ctx = safety_ctx(tmp_path)
    verify = importlib.import_module("db_verify")
    monkeypatch.setattr(verify.userconfig, "merged", lambda defaults: ctx.cfg)
    outside = tmp_path / "outside" / "job" / "draft"
    outside.mkdir(parents=True)
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(verify.UsageError):
        verify.remove_draft(outside, {})
    assert marker.exists()
    link = ctx.work_dir / "job"
    try:
        link.symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside.parent)],
                              capture_output=True)
        assert proc.returncode == 0
    with pytest.raises(module.UsageError):
        module._remove_worktree(ctx, link / "draft")
    assert marker.exists()


@pytest.mark.parametrize("relative", ["../outside/secret", "C:/outside/secret", "link/secret"])
def test_r9_resolve_stays_inside_root(safety_root, tmp_path, monkeypatch, relative):
    module = importlib.import_module("code_roots")
    monkeypatch.setattr(module, "_cfg", lambda defaults: {})
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("synthetic", encoding="utf-8")
    if relative == "link/secret":
        try:
            (root / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            assert os.name == "nt"
            assert subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(outside)],
                                  capture_output=True).returncode == 0
    args = SimpleNamespace(roots=json.dumps({"aosp": str(root)}), ref=f"aosp:{relative}")
    with pytest.raises(module.UsageError):
        module.cmd_resolve(args, {})
