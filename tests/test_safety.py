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
