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
    (root / "zzqx.bin").write_bytes(b"\xff\xfe abc \x00\x80")   # UTF-8 아님: 바이트를 잃지 않고 풀어 내용 1건, 경로 1건
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    (root / "untracked.txt").write_text("abc abc\n", encoding="utf-8")   # 추적 안 됨 → 안 본다
    return root


@pytest.fixture
def deny(tmp_path):
    path = tmp_path / "deny.txt"
    path.write_text("# 주석 abcd\n\n  abc  \nzzqx.\n", encoding="utf-8")
    return path


EXPECTED = {"hit.txt": 4, "snake.txt": 1, "dot.txt": 2, "«1»/note.txt": 1, "«2»bin": 2}


def test_scan_counts_contents_and_paths(repo, deny):
    pats = ds.load(deny)
    assert [k for k, _ in pats] == [1, 2]                 # 주석·빈 줄은 항목이 아니다
    hits, scanned, skipped, errors = ds.scan(repo, pats)
    assert dict(hits) == EXPECTED and scanned == 6 and skipped == 0 and errors == 0


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


def test_self_overlapping_entry_is_masked_whole(tmp_path):
    deny = tmp_path / "d.txt"
    deny.write_text("-a-\n", encoding="utf-8")
    pats = ds.load(deny)
    assert ds._mask("-a-a-", pats) == ("«1»", 1)               # 같은 항목의 겹친 자리도 남기지 않는다
    (tmp_path / "-a-a-.txt").write_text("plain\n", encoding="utf-8")
    assert ds.scan(tmp_path, pats, ["-a-a-.txt"])[0] == [("«1».txt", 1)]


def test_non_utf8_contents_are_scanned_and_packed_files_skipped(tmp_path, deny):
    """UTF-8 아님(잘못된 바이트·UTF-16 BOM/NUL)도 내용을 본다. 압축 형식은 내용을 다 보지 못한 파일(skipped) → CLI 종료 2."""
    files = {"latin.txt": b"caf\xe9 abc here\n", "u16le.txt": "x abc y\n".encode("utf-16"),
             "u16be.txt": "abc\n".encode("utf-16-be"), "odd.bin": b"\x01" + "abc".encode("utf-16-le"),
             "packed.gz": b"\x1f\x8b\x08\x00 plain"}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    hits, scanned, skipped, errors = ds.scan(tmp_path, ds.load(deny), list(files))
    assert dict(hits) == {"latin.txt": 1, "u16le.txt": 1, "u16be.txt": 1, "odd.bin": 1} and (skipped, errors) == (1, 0)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "packed.gz")
    proc = _cli("--root", str(tmp_path), env_deny=deny)
    assert proc.returncode == 2 and "압축 파일 1개" in proc.stderr


def test_path_masks_entry_even_inside_longer_word(tmp_path, deny):
    """경로 가림은 경계 없이(부분 일치) — 건수는 경계 규칙 그대로(경로 `libabc`는 0건, 내용 1건)."""
    (tmp_path / "abc").mkdir()
    (tmp_path / "libabc-notes.md").write_text("see abc\n", encoding="utf-8")
    (tmp_path / "abc" / "libABC.md").write_text("nothing\n", encoding="utf-8")
    hits = ds.scan(tmp_path, ds.load(deny), ["libabc-notes.md", "abc/libABC.md"])[0]
    assert hits == [("lib«1»-notes.md", 1), ("«1»/lib«1».md", 1)]


def test_non_utf8_tracked_path_exits_2(tmp_path, deny, monkeypatch):
    monkeypatch.setattr(ds.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=b"\xff\x00", stderr=b""))
    assert ds.main(["--root", str(tmp_path), "--deny", str(deny)]) == 2


def test_explicit_paths_only(repo, deny):
    assert ds.scan(repo, ds.load(deny), ["miss.txt", "untracked.txt"]) == ([("untracked.txt", 2)], 2, 0, 0)


def test_unreadable_tracked_file_is_error_not_skipped(repo, deny):
    (repo / "miss.txt").unlink()                          # 추적되지만 지워짐 → 읽기 실패(OSError)
    hits, scanned, skipped, errors = ds.scan(repo, ds.load(deny))
    assert (scanned, skipped, errors) == (6, 0, 1)
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
    assert "TOTAL 10 hits in 5 files (scanned 6, skipped 0)" in out
    assert "abc" not in out.lower() and "zzqx" not in out


def test_cli_usage_errors_exit_2_without_traceback(repo, tmp_path):
    clean = tmp_path / "clean.txt"
    clean.write_text("qqzv\n", encoding="utf-8")
    proc = _cli("--root", str(repo), "--deny", str(clean))
    assert proc.returncode == 0 and "TOTAL 0 hits in 0 files (scanned 6, skipped 0)" in proc.stdout
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

