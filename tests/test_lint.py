"""tools/lint.py: 규칙 묶음(pyproject `[tool.ruff]`)으로 지적 0건. ruff(lint extra)가 없으면 건너뛰고, 버전 불일치는 실패다."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_lint_reports_nothing():
    if importlib.util.find_spec("ruff") is None and shutil.which("ruff") is None:
        pytest.skip("lint extra 미설치")
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "lint.py")], cwd=REPO, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)
    assert proc.returncode == 0, proc.stdout[-3000:] + proc.stderr[-1500:]
