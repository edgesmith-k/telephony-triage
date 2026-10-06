import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import fix_exec_bits  # noqa: E402


def test_check_flags_tracked_shebang_and_skips_ignored(tmp_path, monkeypatch):
    def git(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / ".gitignore").write_text("ws/\n", encoding="utf-8")
    (tmp_path / "a.py").write_bytes(b"#!/usr/bin/env python3\n")
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "b.py").write_bytes(b"#!/usr/bin/env python3\n")
    git("add", "-A")
    git("update-index", "--chmod=-x", "a.py")
    monkeypatch.setattr(fix_exec_bits, "REPO", tmp_path)
    assert fix_exec_bits.wanted() == ["a.py"]
    assert fix_exec_bits.main(["--check"]) == 1
    assert fix_exec_bits.main([]) == 0
    assert fix_exec_bits.main(["--check"]) == 0
