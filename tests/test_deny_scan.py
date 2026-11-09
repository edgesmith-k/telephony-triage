"""tools/deny_scan.py: 레포 밖 거부 목록으로 추적 파일을 센다. 출력은 경로·건수뿐 (항목은 합성 토큰)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "deny_scan.py"
sys.path.insert(0, str(REPO / "tools"))
import deny_scan as ds  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    files = {
        "hit.txt": "abc\n(abc) abc.\nABC\n",           # 4건 (대소문자 무시)
        "miss.txt": "abcd xabc abc_d 9abc\n",          # 0건 (단어 경계)
        "dot.txt": "zzqx.bar zzqx.\n",                 # 끝이 `.`인 항목: zzqx.bar·zzqx. 2건
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / "bin.dat").write_bytes(b"\xff\xfe abc \x00\x80")   # UTF-8 아님 → 건너뜀
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    (root / "untracked.txt").write_text("abc abc\n", encoding="utf-8")   # 추적 안 됨 → 안 본다
    return root


@pytest.fixture
def deny(tmp_path):
    path = tmp_path / "deny.txt"
    path.write_text("# 주석 abcd\n\n  abc  \nzzqx.\n", encoding="utf-8")
    return path


def test_scan_counts_word_bounded_case_insensitive(repo, deny):
    pats = ds.load(deny)
    assert [k for k, _ in pats] == [1, 2]                 # 주석·빈 줄은 항목이 아니다
    assert dict(ds.scan(repo, pats)) == {"hit.txt": 4, "dot.txt": 2}


def test_overlapping_entries_count_once(tmp_path):
    (tmp_path / "x.txt").write_text("zzqx.a zzqx\n", encoding="utf-8")
    deny = tmp_path / "d.txt"
    deny.write_text("zzqx.\nzzqx\n", encoding="utf-8")
    assert ds.scan(tmp_path, ds.load(deny), ["x.txt"]) == [("x.txt", 2)]   # 겹친 자리는 한 번만


def test_explicit_paths_only(repo, deny):
    assert ds.scan(repo, ds.load(deny), ["miss.txt", "untracked.txt"]) == [("untracked.txt", 2)]


def _cli(*args: str, env_deny: Path | None = None):
    env = {k: v for k, v in os.environ.items() if k != ds.DENY_ENV}
    if env_deny is not None:
        env[ds.DENY_ENV] = str(env_deny)
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, encoding="utf-8",
                          env=env, stdin=subprocess.DEVNULL)


def test_cli_output_has_paths_and_counts_only(repo, deny):
    proc = _cli("--root", str(repo), env_deny=deny)
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    assert "hit.txt: 4건" in out and "dot.txt: 2건" in out and "TOTAL 6 hits in 2 files" in out
    assert "abc" not in out.lower() and "zzqx" not in out


def test_cli_zero_hits_and_missing_list(repo, tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("qqzv\n", encoding="utf-8")
    proc = _cli("--root", str(repo), "--deny", str(clean))
    assert proc.returncode == 0 and "TOTAL 0 hits in 0 files" in proc.stdout
    assert _cli("--root", str(repo)).returncode == 2                     # --deny·환경 변수 둘 다 없음
    empty = tmp_path / "empty.txt"
    empty.write_text("# only comment\n", encoding="utf-8")
    assert _cli("--root", str(repo), "--deny", str(empty)).returncode == 2   # 빈 목록은 통과가 아니다
