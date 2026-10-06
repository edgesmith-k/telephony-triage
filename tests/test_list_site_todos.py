import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import list_site_todos  # noqa: E402


def test_gitignored_files_are_not_counted(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ws/\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("# TODO(SITE:S1) x\n", encoding="utf-8")
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "b.py").write_text("# TODO(SITE:S2) y\n", encoding="utf-8")
    assert list(list_site_todos.scan(tmp_path)) == ["S1"]


def test_without_git_falls_back_to_rglob(tmp_path):
    (tmp_path / "a.py").write_text("# TODO(SITE:S3) x\n", encoding="utf-8")
    assert list(list_site_todos.scan(tmp_path)) == ["S3"]
