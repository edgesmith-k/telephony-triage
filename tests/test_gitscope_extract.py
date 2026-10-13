"""gitscope.materialize_ref: tarfile `filter="data"`가 없는 Python(3.11.0~3.11.3)에서도 같은 결과와 안전 기준."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root  # noqa: E402

sys.path.insert(0, str(plugin_root() / "scripts"))

from common import gitscope  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "sub").mkdir(parents=True)
    (repo / "a.txt").write_text("A\n", encoding="utf-8")
    (repo / "sub" / "b.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "sub" / "b.sh").chmod(0o755)
    (repo / "link").symlink_to("a.txt")
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                                  "commit", "-qm", "c"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    return repo


@pytest.mark.filterwarnings("ignore:Python 3.14 will:DeprecationWarning")
@pytest.mark.parametrize("has_filter", [True, False])
def test_materialize_ref_same_tree_with_and_without_data_filter(tmp_path, monkeypatch, has_filter):
    repo = _repo(tmp_path)
    if not has_filter:
        monkeypatch.delattr(tarfile, "data_filter", raising=False)
    out = gitscope.materialize_ref(repo, "HEAD", tmp_path / "out")
    assert (out / "a.txt").read_text(encoding="utf-8") == "A\n"
    assert (out / "sub" / "b.sh").stat().st_mode & 0o111
    assert (out / "link").is_symlink() and (out / "link").read_text(encoding="utf-8") == "A\n"


def _tar(*members: tuple[str, str | None]) -> tarfile.TarFile:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, link in members:
            info = tarfile.TarInfo(name)
            if link is None:
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
            else:
                info.type, info.linkname = tarfile.SYMTYPE, link
                tar.addfile(info)
    buf.seek(0)
    return tarfile.open(fileobj=buf)


@pytest.mark.parametrize("member", [("../evil", None), ("/abs", None), ("ok/link", "../../etc/passwd"), ("ln", "/etc/passwd")])
def test_safe_members_rejects_paths_outside_dest(tmp_path, member):
    with _tar(member) as tar, pytest.raises(gitscope.GitError):
        gitscope._safe_members(tar, tmp_path)


def test_safe_members_keeps_inside_links(tmp_path):
    with _tar(("a", None), ("d/l", "../a")) as tar:
        assert [m.name for m in gitscope._safe_members(tar, tmp_path)] == ["a", "d/l"]
