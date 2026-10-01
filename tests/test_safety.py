"""RF-0 regressions; all plugin code and configuration run from temporary roots."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

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
