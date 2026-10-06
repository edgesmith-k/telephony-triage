"""tools/make_bundle.py 검사 (15-local-draft.md §15.4). 무거운 검사는 가짜로 바꿔 몇 초 안에 돈다."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import make_bundle as mb  # noqa: E402

LABEL = "import-t1"


@pytest.fixture(autouse=True)
def _no_guard(monkeypatch):
    # make_bundle이 돌리는 pytest 안에서도 이 테스트는 가드를 직접 제어한다.
    monkeypatch.delenv(mb.GUARD_ENV, raising=False)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "work" / "repo"
    (root / "plugin").mkdir(parents=True)
    (root / "SITE_PATHS").write_text("# 사내 전용\nSITE_PROFILE.md\ndocs/site/\nplugin/site-defaults.yaml\n",
                                     encoding="utf-8")
    (root / "plugin" / "site-defaults.example.yaml").write_text("example: true\n", encoding="utf-8")
    (root / "DRAFT_NOTES.md").write_text("# notes\n", encoding="utf-8")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    (root / ".gitignore").write_text(".local-draft\n", encoding="utf-8")
    (root / ".local-draft").write_text("", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _skeleton_dir(tmp: Path) -> Path:
    d = tmp / "skel"
    (d / "schema").mkdir(parents=True)
    (d / "schema" / "a.yaml").write_text("a: 1\n", encoding="utf-8")
    (d / "data").mkdir()
    (d / "data" / ".gitkeep").write_text("", encoding="utf-8")
    return d


def fake_checks(statuses: dict[str, str] | None = None, calls: list | None = None) -> list[mb.Check]:
    """가짜 자동 검사 3개 + 사람 확인 1개 + 가짜 뼈대 검사(뼈대 zip 재료)."""
    statuses = statuses or {}

    def make(cid):
        def fn(ctx):
            if calls is not None:
                calls.append(cid)
            return mb.CheckResult(statuses.get(cid, "pass"), f"{cid} detail")
        return fn

    def skel(ctx):
        d = ctx.tmp / "skeleton"
        (d / "schema").mkdir(parents=True)
        (d / "schema" / "a.yaml").write_text("a: 1\n", encoding="utf-8")
        return mb.CheckResult("pass", "skeleton")

    return [mb.Check("a", 1, "auto", make("a")), mb.Check("b", 2, "auto", make("b")),
            mb.Check("m", 2, "manual", None, "사람이 확인"), mb.Check("c", 3, "auto", make("c")),
            mb.Check("skel", 7, "auto", skel)]


def _zip_names(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return zf.namelist()


def test_all_pass_makes_bundle_and_exit_3(repo, tmp_path):
    out = tmp_path / "out"
    res = mb.run(repo, LABEL, out, checks=fake_checks())
    assert res["exit_code"] == 3 and res["complete"] is True and res["tree_clean"] is True
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted([f"issue-db-skeleton-{LABEL}.zip", "SHA256SUMS", "logs", "make_bundle-result.json",
                            f"telephony-triage-{LABEL}.zip"])
    assert (out / f"telephony-triage-{LABEL}.zip").is_file() and (out / f"issue-db-skeleton-{LABEL}.zip").is_file()
    on_disk = json.loads((out / "make_bundle-result.json").read_text(encoding="utf-8"))
    assert on_disk["label"] == LABEL and on_disk["head_sha"] == _git(repo, "rev-parse", "HEAD").strip()
    sums = {}
    for line in (out / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    assert set(sums) == {f"telephony-triage-{LABEL}.zip", f"issue-db-skeleton-{LABEL}.zip"}
    for name, digest in sums.items():
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert {f["name"]: f["sha256"] for f in res["bundle"]["files"]} == sums
    # 사람 확인 항목은 판정하지 않는다
    assert [m["id"] for m in res["manual"]] == ["m"]
    assert all(m["status"] == "manual" for m in res["manual"])
    assert [c["status"] for c in res["checks"] if c["kind"] == "manual"] == ["manual"]
    # 태그는 만들지 않는다
    assert _git(repo, "tag").strip() == ""


def test_middle_failure_stops_and_leaves_no_bundle(repo, tmp_path):
    out = tmp_path / "out"
    calls: list = []
    res = mb.run(repo, LABEL, out, checks=fake_checks({"b": "fail"}, calls))
    assert res["exit_code"] == 1 and res["complete"] is False and res["bundle"] is None
    status = {c["id"]: c["status"] for c in res["checks"]}
    assert status == {"a": "pass", "b": "fail", "m": "manual", "c": "not-run", "skel": "not-run"}
    assert calls == ["a", "b"]
    assert not out.exists()


def test_error_status_is_not_a_pass(repo, tmp_path):
    res = mb.run(repo, LABEL, tmp_path / "out", checks=fake_checks({"a": "error"}))
    assert res["exit_code"] == 2 and res["bundle"] is None


def test_check_exception_becomes_error(repo, tmp_path):
    def boom(ctx):
        raise RuntimeError("x")
    res = mb.run(repo, LABEL, tmp_path / "out", checks=[mb.Check("a", 1, "auto", boom)])
    assert res["exit_code"] == 2 and res["checks"][0]["status"] == "error"


def test_skip_is_never_a_pass(repo, tmp_path):
    out = tmp_path / "out"
    calls: list = []
    res = mb.run(repo, LABEL, out, checks=fake_checks(calls=calls), skip=["b"])
    assert res["exit_code"] == 1 and res["complete"] is False and res["bundle"] is None
    row = next(c for c in res["checks"] if c["id"] == "b")
    assert row["status"] == "skipped" and row["reason"] == "--skip"
    assert "b" not in calls and not out.exists()


def test_skip_unknown_id_is_usage_error(repo, tmp_path):
    with pytest.raises(mb.UsageError):
        mb.run(repo, LABEL, tmp_path / "out", checks=fake_checks(), skip=["nope"])


def test_dirty_tree_is_usage_error(repo, tmp_path):
    (repo / "stray.txt").write_text("x", encoding="utf-8")
    assert mb.main(["--repo", str(repo), "--label", LABEL, "--out", str(tmp_path / "out")],
                   checks=fake_checks()) == 2
    (repo / "stray.txt").unlink()


def test_ignored_local_draft_is_ok_and_not_archived(repo, tmp_path):
    assert (repo / ".local-draft").exists()
    out = tmp_path / "out"
    res = mb.run(repo, LABEL, out, checks=fake_checks())
    assert res["exit_code"] == 3
    names = _zip_names(out / f"telephony-triage-{LABEL}.zip")
    assert ".local-draft" not in names and "README.md" in names


def test_tag_on_other_commit_is_usage_error(repo, tmp_path):
    _git(repo, "tag", LABEL)
    (repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "next")
    with pytest.raises(mb.UsageError):
        mb.run(repo, LABEL, tmp_path / "out", checks=fake_checks())


def test_tag_on_head_is_ok(repo, tmp_path):
    _git(repo, "tag", LABEL)
    assert mb.run(repo, LABEL, tmp_path / "out", checks=fake_checks())["exit_code"] == 3


def _ctx(repo, tmp_path):
    return mb.Ctx(repo, tmp_path / "ctx", dict(os.environ))


def test_site_paths_check(repo, tmp_path):
    ctx = _ctx(repo, tmp_path)
    assert mb.check_site_paths(ctx).status == "pass"
    (repo / "plugin" / "site-defaults.yaml").write_text("x: 1\n", encoding="utf-8")
    res = mb.check_site_paths(ctx)
    assert res.status == "fail" and "site-defaults.yaml" in res.detail
    (repo / "plugin" / "site-defaults.yaml").unlink()
    (repo / "docs" / "site").mkdir(parents=True)
    (repo / "docs" / "site" / "note.md").write_text("n\n", encoding="utf-8")  # 추적 여부와 무관하게 디스크에 있으면 안 된다
    assert mb.check_site_paths(ctx).status == "fail"
    (repo / "docs" / "site" / "note.md").unlink()
    (repo / "plugin" / "site-defaults.example.yaml").unlink()
    assert mb.check_site_paths(ctx).status == "fail"


def test_mcp_local_check(repo, tmp_path):
    ctx = _ctx(repo, tmp_path)
    assert mb.check_mcp_local(ctx).status == "pass"
    (repo / ".mcp.json").write_text("{}", encoding="utf-8")
    assert mb.check_mcp_local(ctx).status == "fail"
    (repo / ".mcp.json").unlink()
    _git(repo, "add", "-f", ".local-draft")
    res = mb.check_mcp_local(ctx)
    assert res.status == "fail" and ".local-draft" in res.detail


def test_archive_with_forbidden_entry_fails_without_bundle(repo, tmp_path):
    (repo / ".mcp.json").write_text("{}", encoding="utf-8")
    _git(repo, "add", ".mcp.json")
    _git(repo, "commit", "-qm", "mcp")
    out = tmp_path / "out"
    res = mb.run(repo, LABEL, out, checks=fake_checks())  # 가짜 검사는 이걸 못 잡는다 → 압축 검사가 잡는다
    assert res["exit_code"] == 1 and res["bundle"] is None and not out.exists()
    assert any(c["id"] == "bundle" and c["status"] == "fail" for c in res["checks"])


def test_out_rules(repo, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "old.txt").write_text("old", encoding="utf-8")
    args = ["--repo", str(repo), "--label", LABEL, "--out", str(out)]
    assert mb.main(args, checks=fake_checks()) == 2 and (out / "old.txt").exists()
    # --force도 이전 묶음이 아닌 디렉토리는 지우지 않는다
    assert mb.main([*args, "--force"], checks=fake_checks()) == 2 and (out / "old.txt").exists()
    (out / "old.txt").unlink()
    assert mb.main([*args, "--force"], checks=fake_checks()) == 3  # 빈 디렉토리는 바꿔 만든다
    assert (out / "SHA256SUMS").is_file()
    (out / "marker.txt").write_text("m", encoding="utf-8")
    assert mb.main([*args, "--force"], checks=fake_checks()) == 3  # 이전 묶음(result json 있음)
    assert not (out / "marker.txt").exists() and (out / "SHA256SUMS").is_file()
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".out.")]
    assert mb.main(["--repo", str(repo), "--label", LABEL, "--out", str(repo / "bundle")], checks=fake_checks()) == 2
    assert not (repo / "bundle").exists()


def test_out_rejects_dangerous_paths(repo, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "sub").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    victim = tmp_path / "work" / "keep"
    victim.mkdir()
    (victim / "f.txt").write_text("x", encoding="utf-8")
    bad = [repo, repo / "plugin", repo.parent, tmp_path, Path("/"), home, home.parent, victim / "f.txt"]
    for path in bad:
        for force in (False, True):
            with pytest.raises(mb.UsageError):
                mb.resolve_out(repo.resolve(), LABEL, path, force)
    assert (victim / "f.txt").exists() and repo.exists()
    assert (home / "sub").is_dir()
    # 홈 아래의 일반 디렉토리는 괜찮다
    assert mb.resolve_out(repo.resolve(), LABEL, home / "sub" / "new", True) == (home / "sub" / "new").resolve()


def test_force_keeps_old_bundle_when_swap_fails(repo, tmp_path, monkeypatch):
    out = tmp_path / "out"
    assert mb.run(repo, LABEL, out, checks=fake_checks())["exit_code"] == 3
    before = (out / "SHA256SUMS").read_text(encoding="utf-8")
    real = os.rename

    def flaky(src, dst):
        if Path(src).name.startswith(".out.new") and str(dst) == str(out.resolve()):
            raise OSError("boom")
        return real(src, dst)

    monkeypatch.setattr(os, "rename", flaky)
    with pytest.raises(OSError):
        mb.run(repo, LABEL, out, checks=fake_checks(), force=True)
    monkeypatch.undo()
    assert (out / "SHA256SUMS").read_text(encoding="utf-8") == before
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".out.")]


def test_default_out_is_sibling_of_repo(repo):
    res = mb.run(repo, LABEL, None, checks=fake_checks())
    expected = repo.parent / "tt-import-bundles" / LABEL
    assert res["exit_code"] == 3 and Path(res["bundle"]["dir"]) == expected.resolve()
    assert (expected / "SHA256SUMS").is_file()


def test_manual_id_cannot_be_skipped(repo, tmp_path):
    with pytest.raises(mb.UsageError):
        mb.run(repo, LABEL, tmp_path / "out", checks=fake_checks(), skip=["m"])
    assert mb.main(["--repo", str(repo), "--label", LABEL, "--out", str(tmp_path / "o"), "--skip", "m"],
                   checks=fake_checks()) == 2


def test_check_writing_into_repo_fails_tree_clean(repo, tmp_path):
    def dirty(ctx):
        (ctx.repo / "x.txt").write_text("x", encoding="utf-8")
        return mb.CheckResult("pass", "ok")
    out = tmp_path / "out"
    checks = [mb.Check("w", 1, "auto", dirty), *fake_checks()]
    res = mb.run(repo, LABEL, out, checks=checks)
    assert res["exit_code"] == 1 and res["bundle"] is None and res["tree_clean"] is False
    assert any(c["id"] == "tree-clean" and c["status"] == "fail" for c in res["checks"])
    assert not out.exists()


def test_tree_clean_recorded_when_stopped_early(repo, tmp_path):
    def dirty_and_fail(ctx):
        (ctx.repo / "x.txt").write_text("x", encoding="utf-8")
        return mb.CheckResult("fail", "no")
    res = mb.run(repo, LABEL, tmp_path / "out", checks=[mb.Check("w", 1, "auto", dirty_and_fail), *fake_checks()])
    assert res["exit_code"] == 1
    assert any(c["id"] == "tree-clean" and c["status"] == "fail" for c in res["checks"])


def test_skip_plus_error_exits_1(repo, tmp_path):
    res = mb.run(repo, LABEL, tmp_path / "out", checks=fake_checks({"a": "error"}), skip=["b"])
    assert res["exit_code"] == 1 and res["bundle"] is None


def test_unexpected_exception_is_exit_2(repo, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(mb, "run", boom)
    assert mb.main(["--repo", str(repo), "--label", LABEL, "--out", str(tmp_path / "o")]) == 2
    assert "kaboom" in capsys.readouterr().err


def test_real_check_ids_order_and_manual_items():
    ids = [c.id for c in mb.CHECKS]
    assert ids == ["site-paths", "mcp-local", "boundary", "human-search", "schemas", "contracts", "site-todos",
                   "todos-seen", "draft-notes-size", "draft-notes-fresh", "skeleton", "offline-eval", "regress",
                   "evals-prepare", "pytest"]
    manual = [c.id for c in mb.CHECKS if c.kind == "manual"]
    assert manual == ["human-search", "todos-seen", "draft-notes-fresh"]
    assert all(c.how for c in mb.CHECKS if c.kind == "manual")
    assert {c.checklist for c in mb.CHECKS} == set(range(1, 10))


def test_checks_use_target_repo_tools(repo, tmp_path, monkeypatch):
    seen = []

    def fake_run(self, check_id, argv, **kw):
        seen.append(argv)
        return 0, "{}"
    monkeypatch.setattr(mb.Ctx, "run", fake_run)
    ctx = _ctx(repo, tmp_path)
    mb.check_boundary(ctx)
    mb.tool_check("schemas", "sync_schemas.py", ["--check"], "ok")(ctx)
    mb.check_site_todos(ctx)
    assert all(str(repo / "tools") in " ".join(a) for a in seen) and len(seen) == 3


def test_evals_prepare_output_parsing(monkeypatch, tmp_path):
    ctx = mb.Ctx(REPO, tmp_path / "ctx", dict(os.environ))
    ids = [e["id"] for e in json.loads((REPO / "tests/skill_evals/evals.json").read_text(encoding="utf-8"))["evals"]]
    good = "".join(f"eval {i}: prepared (plugin)\n" for i in ids)
    monkeypatch.setattr(mb.Ctx, "run", lambda self, *a, **k: (0, good))
    res = mb.check_evals_prepare(ctx)
    assert res.status == "pass" and res.data == {"count": len(ids)} and "not executed" in res.detail
    monkeypatch.setattr(mb.Ctx, "run", lambda self, *a, **k: (0, good.splitlines(True)[0]))
    assert mb.check_evals_prepare(ctx).status == "fail"
    monkeypatch.setattr(mb.Ctx, "run", lambda self, *a, **k: (2, "usage"))
    assert mb.check_evals_prepare(ctx).status == "error"


def test_timeout_output_is_decoded_into_log(repo, tmp_path):
    ctx = _ctx(repo, tmp_path)
    code, out = ctx.run("slow", [sys.executable, "-c", "import time;print('hi',flush=True);time.sleep(5)"], timeout=1)
    assert code == 2 and "시간 초과" in out
    log = (ctx.logs / "slow.log").read_text(encoding="utf-8")
    assert "시간 초과" in log and "hi" in log and "b'" not in log


@pytest.mark.parametrize("label", ["bad label", "a/b", "x..y", "-lead", "end.lock", "한글", "a~b"])
def test_bad_label_is_usage_error(repo, tmp_path, label):
    assert mb.main(["--repo", str(repo), f"--label={label}", "--out", str(tmp_path / "o")],
                   checks=fake_checks()) == 2


def test_not_a_git_repo_is_usage_error(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert mb.main(["--repo", str(plain), "--label", LABEL, "--out", str(tmp_path / "o")],
                   checks=fake_checks()) == 2


def test_skeleton_zip_is_deterministic(tmp_path):
    src = _skeleton_dir(tmp_path)
    (src / "schema" / "b.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (src / "schema" / "b.sh").chmod(0o755)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    mb.zip_dir_deterministic(src, a)
    os.utime(src / "schema" / "a.yaml", (1_000_000_000, 1_000_000_000))  # 수정 시각이 달라도 같아야 한다
    mb.zip_dir_deterministic(src, b)
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as zf:
        assert zf.namelist() == sorted(zf.namelist())
        assert all(i.date_time == mb.ZIP_DATE for i in zf.infolist())
        modes = {i.filename: i.external_attr >> 16 & 0o777 for i in zf.infolist()}
    assert modes["schema/b.sh"] == 0o755 and modes["schema/a.yaml"] == 0o644


def test_verify_skeleton_catches_types_jira_fixtures(tmp_path):
    ok = _skeleton_dir(tmp_path)
    assert mb.verify_skeleton(ok) == []
    (ok / "data" / "DATA-001-x").mkdir()
    (ok / "data" / "DATA-001-x" / "type.md").write_text("t", encoding="utf-8")
    (ok / "feedback").mkdir()
    (ok / "feedback" / "f1.yaml").write_text("x: 1\n", encoding="utf-8")
    (ok / "schema" / "fx.log.expect.yaml").write_text("origin: synthetic\n", encoding="utf-8")
    problems = "\n".join(mb.verify_skeleton(ok))
    assert "DATA-001-x/type.md" in problems and "feedback/f1.yaml" in problems and "origin: synthetic" in problems


def test_recursion_guard(repo, tmp_path, monkeypatch):
    monkeypatch.setenv(mb.GUARD_ENV, "1")
    assert mb.main(["--repo", str(repo), "--label", LABEL, "--out", str(tmp_path / "o")],
                   checks=fake_checks()) == 2


def test_cli_smoke_skip_heavy_checks(repo, tmp_path):
    env = {k: v for k, v in os.environ.items() if k != mb.GUARD_ENV}
    heavy = ",".join(c.id for c in mb.CHECKS if c.kind == "auto")
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "make_bundle.py"), "--repo", str(repo),
                           "--label", LABEL, "--out", str(tmp_path / "out"), "--skip", heavy, "--json"],
                          capture_output=True, text=True, encoding="utf-8", env=env)
    assert proc.returncode == 1, proc.stderr
    data = json.loads(proc.stdout)
    assert data["complete"] is False and data["bundle"] is None and data["label"] == LABEL
    assert {c["status"] for c in data["checks"] if c["kind"] == "auto"} == {"skipped"}
    assert not (tmp_path / "out").exists()
