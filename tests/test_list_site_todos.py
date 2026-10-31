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


def test_combined_marker_counts_each_item(tmp_path):
    """`TODO(SITE:S24·S25)`처럼 묶은 표시는 항목마다 센다."""
    (tmp_path / "a.py").write_text("x = 1  # TODO(SITE:S24·S25) 구성요소\ny = 2  # TODO(SITE:S7, S9)\n", encoding="utf-8")
    found = list_site_todos.scan(tmp_path)
    assert sorted(found, key=lambda k: int(k[1:])) == ["S7", "S9", "S24", "S25"]
    assert found["S25"][0]["line"] == 1 and found["S9"][0]["line"] == 2
