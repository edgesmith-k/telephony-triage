"""`tools/make_module_repo.py` (H C1 C1D §3.4): 템플릿 → 한 커밋 모듈 레포. 네트워크·push 없음."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "make_module_repo.py"
TEMPLATES = REPO / "templates" / "module-skills"
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import skillcheck  # noqa: E402

sys.path.insert(0, str(REPO / "tools"))
from make_module_repo import PLACEHOLDER_RE as PLACEHOLDER  # noqa: E402

ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True, env=ENV).stdout.strip()


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True,
                          encoding="utf-8", check=False, env=ENV)


@pytest.fixture(scope="module")
def src(tmp_path_factory) -> Path:
    """레포 템플릿을 담은 임시 git 레포(커밋 날짜 고정) — 실제 레포 HEAD에 기대지 않는다."""
    root = tmp_path_factory.mktemp("src")
    shutil.copytree(TEMPLATES, root / "module-skills", ignore=shutil.ignore_patterns("results", "__pycache__"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@invalid", "-c", "commit.gpgsign=false", "commit",
                    "-q", "-m", "t", "--date", "2026-11-05T00:00:00+00:00"], cwd=str(root), check=True,
                   env={**ENV, "GIT_COMMITTER_DATE": "2026-11-05T00:00:00+00:00"})
    return root / "module-skills"


def _make(src: Path, out: Path, *extra) -> subprocess.CompletedProcess:
    return _run(out, "--templates", src, *extra)


def test_creates_single_commit_repo(src, tmp_path):
    out = tmp_path / "repo"
    proc = _make(src, out)
    assert proc.returncode == 0, proc.stderr
    sha = _git(out, "rev-parse", "HEAD")
    assert proc.stdout.strip() == f"{out} {sha}"
    assert _git(out, "rev-list", "--count", "HEAD") == "1"
    assert _git(out, "log", "-1", "--format=%an|%cn|%s").startswith("telephony-triage|telephony-triage|module-skills: import")
    assert _git(out, "branch", "--show-current") == "main"


def test_tree_equals_allowed_template_files(src, tmp_path):
    out = tmp_path / "repo"
    assert _make(src, out).returncode == 0
    tracked = set(_git(out, "ls-files").splitlines())
    want = {p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()}
    assert tracked == want
    assert all(any(rx.fullmatch(t) for rx in skillcheck.ALLOWED) for t in tracked)


def test_refuses_non_empty_out(src, tmp_path):
    out = tmp_path / "repo"
    out.mkdir()
    (out / "x").write_text("x")
    assert _make(src, out).returncode == 2


def test_refuses_out_inside_repo(src):
    assert _make(src, REPO / "tmp-module-repo-test").returncode == 2
    assert not (REPO / "tmp-module-repo-test").exists()


def test_bad_template_creates_nothing(src, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(src, bad)
    run = bad / "ofono" / "data" / "run.sh"
    run.write_text("#!/bin/sh\n")
    run.chmod(0o755)
    out = tmp_path / "repo"
    proc = _make(bad, out)
    assert proc.returncode == 1 and "ofono/data/run.sh" in proc.stdout
    assert not out.exists()


def test_no_remote_configured(src, tmp_path):
    out = tmp_path / "repo"
    assert _make(src, out).returncode == 0
    assert _git(out, "remote") == ""


def test_same_input_same_tree_sha(src, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert _make(src, a).returncode == 0 and _make(src, b, "--json").returncode == 0
    assert _git(a, "rev-parse", "HEAD^{tree}") == _git(b, "rev-parse", "HEAD^{tree}")
    assert _git(a, "rev-parse", "HEAD") == _git(b, "rev-parse", "HEAD")


def test_files_mode_644(src, tmp_path):
    out = tmp_path / "repo"
    assert _make(src, out).returncode == 0
    modes = {line.split()[0] for line in _git(out, "ls-files", "-s").splitlines()}
    assert modes == {"100644"}
    for p in out.rglob("*"):
        if p.is_file() and ".git" not in p.relative_to(out).parts:
            assert stat.S_IMODE(p.stat().st_mode) == 0o644, p


# -- --site-overlay (사내 스냅샷 덮어쓰기). 스냅샷은 합성(demo-x) -------------------------------------------

SNAP = {
    "README.md": "# demo-x 모듈 스킬\n\n스냅샷 덮어쓰기 시험용 합성 문서.\n",
    "ofono/data/explore.md": "# demo-x data 탐색\n\n- demo-x 구성요소 줄을 먼저 본다.\n",
}


def _rename(text: str) -> str:
    """사내 스냅샷처럼 placeholder 이름을 같은 규칙으로 바꾼다(합성: `x<이름>`·`{{demo-site:`, IPC 이름은 대문자 꼴 그대로 `X<이름>`)."""
    def sub(m):
        g = m.group(0)
        return "{{demo-site:" if g == "{{site:" else ("X" if g.startswith("VIPC_") else "x") + g
    return PLACEHOLDER.sub(sub, text)


def _full(src: Path, files: dict[str, str] | None = None) -> dict[str, str]:
    """evals 밖 템플릿 파일 전부를 placeholder 없이 바꾼 스냅샷(+ files로 덮음) — 스냅샷 범위 그대로."""
    base = {p.relative_to(src).as_posix(): _rename(p.read_text(encoding="utf-8")) for p in sorted(src.rglob("*"))
            if p.is_file() and "evals" not in p.relative_to(src).parts}
    return {**base, **(files or {})}


def _snapshot(root: Path, files: dict[str, str], source: str | None = "label=import-demo sha=0000000 date=2026-11-10") -> Path:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    if source is not None:
        (root / "SOURCE").write_text(source + "\n", encoding="utf-8")
    return root


def test_overlay_replaces_files_and_reports_json(src, tmp_path):
    full = _full(src, SNAP)
    snap = _snapshot(tmp_path / "snap", full)
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["overlay"] == sorted(full) and data["source"] == "label=import-demo sha=0000000 date=2026-11-10"
    for rel, text in full.items():
        assert (out / rel).read_text(encoding="utf-8") == text
    tracked = set(_git(out, "ls-files").splitlines())
    assert tracked == {p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()}   # SOURCE는 들어가지 않는다
    assert skillcheck.check_worktree(out) == []
    assert not any(PLACEHOLDER.search((out / rel).read_text(encoding="utf-8")) for rel in full)


def test_overlay_adds_file_missing_from_template(src, tmp_path):
    snap = _snapshot(tmp_path / "snap", _full(src, {"ofono/modem/references/MODEM-001.md": "# demo-x modem 참고\n"}),
                     source=None)
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["source"] is None
    assert "ofono/modem/references/MODEM-001.md" in _git(out, "ls-files").splitlines()


def test_snapshot_missing_template_file_with_placeholder_creates_nothing(src, tmp_path):
    """스냅샷에 없는 템플릿 파일(evals 밖)이 placeholder를 담으면 `스냅샷에 없음`(빈 스냅샷도 같다). placeholder 없는 파일은 빠져도 된다."""
    full = _full(src, SNAP)
    gone = "ofono/_common/layers.md"
    assert PLACEHOLDER.search((src / gone).read_text(encoding="utf-8"))
    snap = _snapshot(tmp_path / "snap", {k: v for k, v in full.items() if k != gone})
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap)
    assert proc.returncode == 1 and proc.stdout.strip() == f"스냅샷에 없음: {gone}", proc.stdout
    assert not out.exists()
    (tmp_path / "empty").mkdir()
    proc = _make(src, out, "--site-overlay", tmp_path / "empty")
    assert proc.returncode == 1 and f"스냅샷에 없음: {gone}" in proc.stdout.splitlines() and not out.exists()
    plain = next(k for k in sorted(full) if not PLACEHOLDER.search((src / k).read_text(encoding="utf-8")))
    snap3 = _snapshot(tmp_path / "snap3", {k: v for k, v in full.items() if k != plain})
    assert _make(src, out, "--site-overlay", snap3).returncode == 0


def test_overlay_is_deterministic(src, tmp_path):
    a = tmp_path / "a"
    assert _make(src, a).returncode == 0
    snap = _snapshot(tmp_path / "snap", _full(src, SNAP))
    c, d = tmp_path / "c", tmp_path / "d"
    assert _make(src, c, "--site-overlay", snap).returncode == 0 and _make(src, d, "--site-overlay", snap).returncode == 0
    assert _git(c, "rev-parse", "HEAD") == _git(d, "rev-parse", "HEAD") != _git(a, "rev-parse", "HEAD")


@pytest.mark.parametrize("text", ["# x\n\n- vrild 줄\n", "# x\n\n{{site:data}}\n", "# x\n\n- VRIL-IMS 태그\n",
                                  "# x\n\n- datad2 줄\n", "# x\n\n- networkd 줄\n", "# x\n\n- `[IpcCtx_0]` 줄\n",
                                  "# x\n\n- OnIpcComplete 줄\n", "# x\n\n- IMSD 태그\n", "# x\n\n- DATAD_X 값\n",
                                  "# x\n\n- `VIPC_DIAL` 줄\n", "# x\n\n- `Error(VIPC_E_BUSY)` 줄\n"])
def test_incomplete_snapshot_creates_nothing(src, tmp_path, text):
    snap = _snapshot(tmp_path / "snap", _full(src, {**SNAP, "ofono/data/explore.md": text}))
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap)
    assert proc.returncode == 1 and proc.stdout.strip() == "스냅샷이 불완전: ofono/data/explore.md", proc.stdout
    assert not out.exists()


def test_snapshot_with_site_todo_marker_passes(src, tmp_path):
    """`TODO(SITE:S25)`는 사내 스냅샷 문서에도 있을 수 있는 표식이라 불완전 표시가 아니다."""
    snap = _snapshot(tmp_path / "snap",
                     _full(src, {**SNAP, "ofono/data/explore.md": "# demo-x\n\n<!-- TODO(SITE:S25) 사내 확인 -->\n"}))
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "TODO(SITE:S25)" in (out / "ofono/data/explore.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["file", "dir"])
def test_snapshot_symlink_is_refused(src, tmp_path, kind):
    """링크는 따라가지 않는다(스냅샷 밖 내용 복사·디렉토리 조용히 빠짐 방지) — `<파일> 링크`로 종료 1."""
    outside = tmp_path / "outside"
    (outside / "sub").mkdir(parents=True)
    (outside / "x.md").write_text("# demo-x 밖\n", encoding="utf-8")
    snap = _snapshot(tmp_path / "snap", SNAP)
    rel = "ofono/data/references" if kind == "dir" else "ofono/data/SKILL.md"
    try:
        (snap / rel).symlink_to(outside / "sub" if kind == "dir" else outside / "x.md", target_is_directory=(kind == "dir"))
    except OSError as exc:            # Windows 권한 없음(WinError 1314) 등
        pytest.skip(f"심볼릭 링크를 만들 수 없음: {exc}")
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap)
    assert proc.returncode == 1 and f"{rel} 링크" in proc.stdout, proc.stdout
    assert not out.exists()


def test_snapshot_source_not_utf8_exits_2_before_creating(src, tmp_path):
    snap = _snapshot(tmp_path / "snap", SNAP, source=None)
    (snap / "SOURCE").write_bytes(b"label=\xff\xfe\n")
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap, "--json")
    assert proc.returncode == 2 and "SOURCE" in proc.stderr and "Traceback" not in proc.stderr, proc.stderr
    assert not out.exists()


def test_snapshot_source_read_error_or_link_is_usage(tmp_path, monkeypatch):
    """SOURCE 읽기 실패(OSError)·링크는 고정 문구의 사용 오류(종료 2). 링크를 못 만드는 환경은 그 부분만 skip."""
    import make_module_repo as mmr

    snap = _snapshot(tmp_path / "snap", SNAP)
    real = Path.read_text

    def deny(self, *a, **k):
        if self.name == "SOURCE":
            raise PermissionError("denied")
        return real(self, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(Path, "read_text", deny)
        with pytest.raises(mmr.Usage, match="SOURCE를 읽지 못했다"):
            mmr._read_source(snap)
    assert mmr._read_source(snap).startswith("label=") and mmr._read_source(None) is None
    linked = tmp_path / "linked"
    linked.mkdir()
    try:
        (linked / "SOURCE").symlink_to(snap / "SOURCE")
    except OSError as exc:            # Windows 권한 없음(WinError 1314) 등
        pytest.skip(f"심볼릭 링크를 만들 수 없음: {exc}")
    with pytest.raises(mmr.Usage, match="SOURCE가 링크다"):
        mmr._read_source(linked)


def test_snapshot_with_evals_is_refused(src, tmp_path):
    snap = _snapshot(tmp_path / "snap", {**SNAP, "ofono/data/evals/demo-case/case.yaml": "synthetic: true\n"})
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap)
    assert proc.returncode == 1 and "ofono/data/evals/demo-case/case.yaml 스냅샷에 evals" in proc.stdout
    assert not out.exists()


def test_overlay_runs_strict_validation_and_tree_rules(src, tmp_path):
    import yaml

    doc = yaml.safe_load((src / "modules.yaml").read_text(encoding="utf-8"))
    plat = sorted(doc["platforms"])[0]
    first = sorted(doc["platforms"][plat]["modules"])[0]
    doc["platforms"][plat]["modules"][first]["demo_x_key"] = []           # strict에서만 오류인 모르는 키
    # 사내 스냅샷처럼 placeholder 이름 없이: 이름을 같은 규칙으로 바꾼 전체 스냅샷에 modules.yaml만 다시 덮는다
    snap = _snapshot(tmp_path / "snap", _full(src, {"modules.yaml": _rename(yaml.safe_dump(doc, allow_unicode=True,
                                                                                         sort_keys=False))}))
    out = tmp_path / "repo"
    proc = _make(src, out, "--site-overlay", snap)
    assert proc.returncode == 1 and proc.stdout.strip() == "modules.yaml 검증(strict) 1건", proc.stdout
    assert not out.exists()
    snap2 = _snapshot(tmp_path / "snap2", _full(src, {"ofono/data/notes.txt": "demo-x\n"}))
    proc = _make(src, tmp_path / "repo2", "--site-overlay", snap2)
    assert proc.returncode == 1 and "ofono/data/notes.txt 허용 이름 밖" in proc.stdout


def test_overlay_not_a_directory(src, tmp_path):
    assert _make(src, tmp_path / "repo", "--site-overlay", tmp_path / "nosuch").returncode == 2
