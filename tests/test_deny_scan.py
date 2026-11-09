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
    (root / "abc").mkdir(parents=True)
    files = {
        "hit.txt": "abc\n(abc) abc.\nABC\n",           # 4건 (대소문자 무시)
        "miss.txt": "abcd xabc 9abc abc1\n",           # 0건 (영숫자 경계)
        "snake.txt": "x_abc_y\n",                      # 1건: `_`는 경계 — 식별자 안의 이름도 잡는다
        "dot.txt": "zzqx.bar zzqx.\n",                 # 끝이 `.`인 항목: 2건
        "abc/note.txt": "nothing\n",                   # 경로에만 있음: 1건
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / "zzqx.bin").write_bytes(b"\xff\xfe abc \x00\x80")   # 내용은 UTF-8 아님 → 건너뜀, 경로는 1건
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    (root / "untracked.txt").write_text("abc abc\n", encoding="utf-8")   # 추적 안 됨 → 안 본다
    return root


@pytest.fixture
def deny(tmp_path):
    path = tmp_path / "deny.txt"
    path.write_text("# 주석 abcd\n\n  abc  \nzzqx.\n", encoding="utf-8")
    return path


EXPECTED = {"hit.txt": 4, "snake.txt": 1, "dot.txt": 2, "«1»/note.txt": 1, "«2»bin": 1}


def test_scan_counts_contents_and_paths(repo, deny):
    pats = ds.load(deny)
    assert [k for k, _ in pats] == [1, 2]                 # 주석·빈 줄은 항목이 아니다
    hits, scanned, skipped, errors = ds.scan(repo, pats)
    assert dict(hits) == EXPECTED and scanned == 6 and skipped == 1 and errors == 0


def test_bom_in_deny_file(repo, tmp_path):
    path = tmp_path / "bom.txt"
    path.write_text("abc\n", encoding="utf-8-sig")
    assert ds.scan(repo, ds.load(path), ["hit.txt"])[0] == [("hit.txt", 4)]


def test_underscore_edged_entry_has_no_boundary_on_that_side(tmp_path):
    (tmp_path / "x.txt").write_text("ril_abc ril_abcd\n", encoding="utf-8")
    deny = tmp_path / "d.txt"
    deny.write_text("_abc\n", encoding="utf-8")   # 앞은 `_`라 경계 없음, 뒤는 영숫자 경계
    assert ds.scan(tmp_path, ds.load(deny), ["x.txt"])[0] == [("x.txt", 1)]


def test_overlapping_entries_count_once(tmp_path):
    (tmp_path / "x.txt").write_text("zzqx.a zzqx\n", encoding="utf-8")
    deny = tmp_path / "d.txt"
    deny.write_text("zzqx.\nzzqx\n", encoding="utf-8")
    assert ds.scan(tmp_path, ds.load(deny), ["x.txt"])[0] == [("x.txt", 2)]   # 겹친 자리는 한 번만


@pytest.mark.parametrize("entries", ["alpha\nalpha-secret\n", "alpha-secret\nalpha\n"])
def test_longer_overlapping_entry_is_masked_whole(tmp_path, entries):
    (tmp_path / "alpha-secret.txt").write_text("plain\n", encoding="utf-8")
    deny = tmp_path / "d.txt"
    deny.write_text(entries, encoding="utf-8")
    hits = ds.scan(tmp_path, ds.load(deny), ["alpha-secret.txt"])[0]
    assert hits == [("«1».txt", 1)]                      # 짧은 항목이 긴 항목 일부를 남기지 않는다
    assert "alpha" not in hits[0][0] and "secret" not in hits[0][0]


def test_touching_entries_stay_separate(tmp_path):
    deny = tmp_path / "d.txt"
    deny.write_text("ab-\ncd\n", encoding="utf-8")
    assert ds._mask("ab-cd", ds.load(deny)) == ("«1»«2»", 2)   # 맞닿은 구간은 합치지 않는다


def test_non_utf8_tracked_path_exits_2(tmp_path, deny, monkeypatch):
    monkeypatch.setattr(ds.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"\xff\x00", stderr=b""))
    assert ds.main(["--root", str(tmp_path), "--deny", str(deny)]) == 2


def test_explicit_paths_only(repo, deny):
    assert ds.scan(repo, ds.load(deny), ["miss.txt", "untracked.txt"]) == ([("untracked.txt", 2)], 2, 0, 0)


def test_unreadable_tracked_file_is_error_not_skipped(repo, deny):
    (repo / "miss.txt").unlink()                          # 추적되지만 지워짐 → 읽기 실패(OSError)
    hits, scanned, skipped, errors = ds.scan(repo, ds.load(deny))
    assert (scanned, skipped, errors) == (6, 1, 1)        # zzqx.bin은 그대로 skipped(UTF-8 아님)
    proc = _cli("--root", str(repo), env_deny=deny)
    assert proc.returncode == 2 and "읽기 실패 1개 파일" in proc.stderr and "Traceback" not in proc.stderr


def _cli(*args: str, env_deny: Path | None = None):
    env = {k: v for k, v in os.environ.items() if k != ds.DENY_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    if env_deny is not None:
        env[ds.DENY_ENV] = str(env_deny)
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True, encoding="utf-8",
                          env=env, stdin=subprocess.DEVNULL)


def test_cli_output_has_masked_paths_and_counts_only(repo, deny):
    proc = _cli("--root", str(repo), env_deny=deny)
    assert proc.returncode == 1
    out = proc.stdout + proc.stderr
    for rel, n in EXPECTED.items():
        assert f"{rel}: {n}건" in out
    assert "TOTAL 9 hits in 5 files (scanned 6, skipped 1)" in out
    assert "abc" not in out.lower() and "zzqx" not in out


def test_cli_usage_errors_exit_2_without_traceback(repo, tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("qqzv\n", encoding="utf-8")
    proc = _cli("--root", str(repo), "--deny", str(clean))
    assert proc.returncode == 0 and "TOTAL 0 hits in 0 files (scanned 6, skipped 1)" in proc.stdout
    empty = tmp_path / "empty.txt"
    empty.write_text("# only comment\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfeab\x80\n")
    bare = tmp_path / "bare"
    bare.mkdir()
    _git(bare, "init", "-q")
    for args in (("--root", str(repo)),                      # --deny·환경 변수 둘 다 없음
                 ("--root", str(repo), "--deny", str(empty)),  # 빈 목록은 통과가 아니다
                 ("--root", str(repo), "--deny", str(bad)),    # UTF-8 아님
                 ("--root", str(bare), "--deny", str(clean))):  # 스캔할 추적 파일 없음
        proc = _cli(*args)
        assert proc.returncode == 2 and "Traceback" not in proc.stderr, args
    assert "스캔할 추적 파일 없음" in proc.stderr


def test_cli_git_failure_message_has_no_path(tmp_path):
    deny = tmp_path / "d.txt"
    deny.write_text("reviewsecretqq\n", encoding="utf-8")
    proc = _cli("--root", str(tmp_path / "ReviewSecretQQ-missing"), "--deny", str(deny))
    assert proc.returncode == 2 and "Traceback" not in proc.stderr
    assert "reviewsecret" not in (proc.stdout + proc.stderr).lower()

