"""gitscope.materialize_ref: tarfile `filter="data"`가 없는 Python(3.11.0~3.11.3)에서도 같은 결과와 안전 기준.
gitscope.materialize_ref_sparse: fixture 로그만 뺀 같은 트리, 사용자 index 불변, db_lint·db_verify 판정 불변."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, edit, git, git_db, plugin_root  # noqa: E402

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
        monkeypatch.setattr(gitscope, "_HAS_DATA_FILTER", False)   # tarfile 자체는 건드리지 않는다(3.14는 내부에서 쓴다)
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


# -- materialize_ref_sparse ------------------------------------------------------------------------------------

def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _is_fixture(rel: str) -> bool:
    parts = rel.split("/")
    return len(parts) >= 4 and parts[2] == "fixtures"


@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_sparse_is_full_tree_minus_fixtures_byte_for_byte(tmp_path, autocrlf):
    db = git_db()
    (db / "parser-rules" / "fixtures").mkdir()                        # 깊이가 다른 fixtures/는 남는다
    (db / "parser-rules" / "fixtures" / "keep.txt").write_bytes(b"k\n")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "extra")
    git(db, "config", "core.autocrlf", autocrlf)                        # 시스템 gitconfig 값과 무관하게 둘 다
    full = _files(gitscope.materialize_ref(db, "HEAD", tmp_path / "full"))
    sparse = _files(gitscope.materialize_ref_sparse(db, "HEAD", tmp_path / "sparse"))
    assert any(_is_fixture(k) for k in full) and "parser-rules/fixtures/keep.txt" in sparse
    assert sparse == {k: v for k, v in full.items() if not _is_fixture(k)}
    assert (tmp_path / "sparse" / "schema").is_dir()                   # parser_rules.load가 rules_dir.parent/schema를 읽는다
    assert not any(b"\r\n" in v for k, v in sparse.items() if k.endswith((".md", ".yaml")))   # .gitattributes eol=lf
    assert sorted(p.name for p in tmp_path.iterdir()) == ["full", "sparse"]    # 임시 index가 남지 않는다


def _subdir_db() -> Path:
    """레포 최상위가 아니라 `sub/`에 있는 이슈 DB. 첫 커밋에는 `sub/`가 없다."""
    repo = git_db().parent / "outer"
    repo.mkdir()
    (repo / "top.txt").write_text("top\n", encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "no sub")
    shutil.copytree(SAMPLE, repo / "sub")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "sub")
    return repo / "sub"


def test_sparse_in_subdir_db_matches_archive_relative_paths(tmp_path, monkeypatch, capsys):
    db = _subdir_db()
    full = _files(gitscope.materialize_ref(db, "HEAD", tmp_path / "full"))
    sparse = _files(gitscope.materialize_ref_sparse(db, "HEAD", tmp_path / "sparse"))
    assert "issue-db.config.yaml" in sparse and "top.txt" not in full
    # 하위 디렉토리에서 git archive는 그 하위의 .gitattributes(eol=lf)를 적용하지 않아 autocrlf면 CRLF가 된다.
    # sparse는 DB의 .gitattributes를 따른다(LF) — 줄 끝만 다르고 내용은 같다.
    lf = {k: v.replace(b"\r\n", b"\n") for k, v in full.items() if not _is_fixture(k)}
    assert sparse == lf and not any(b"\r\n" in v for k, v in sparse.items() if k.endswith((".md", ".yaml")))
    assert not any((gitscope.materialize_ref_sparse(db, "HEAD~1", tmp_path / "old")).iterdir())   # 그 ref에 DB가 없으면 빈 기준
    with pytest.raises(gitscope.GitError):
        gitscope.materialize_ref_sparse(db, "no-such-ref", tmp_path / "bad")

    import db_lint
    edit(db / "parser-rules/extractors.yaml", "    event: ims_registered\n    fields: [transport]",
         "    event: ims_registered\n    fields: []")
    seen, real = [], db_lint._base_causes
    monkeypatch.setattr(db_lint, "_base_causes", lambda root: seen.append(real(root)) or seen[-1])
    sparse_out = _main("db_lint", ["--changed", "HEAD", "--db", str(db)], capsys)
    _full_instead_of_sparse(monkeypatch)
    assert _main("db_lint", ["--changed", "HEAD", "--db", str(db)], capsys) == sparse_out
    assert len(seen) == 2 and seen[0] and seen[0] == seen[1]            # 기준 원인을 읽었다(None 아님)


def test_sparse_leaves_user_index_and_status_unchanged(tmp_path, monkeypatch):
    db = git_db()
    (db / "issue-db.config.yaml").write_text((db / "issue-db.config.yaml").read_text(encoding="utf-8") + "# staged\n",
                                             encoding="utf-8", newline="\n")
    git(db, "add", "issue-db.config.yaml")
    (db / "CONTRIBUTING.md").write_text("unstaged\n", encoding="utf-8")
    other = tmp_path / "other.index"
    other.write_bytes((db / ".git" / "index").read_bytes())
    state = lambda: ((db / ".git" / "index").read_bytes(), other.read_bytes(), git(db, "status", "--porcelain"))  # noqa: E731
    before = state()
    monkeypatch.setenv("GIT_INDEX_FILE", str(other))                   # 환경에 다른 index가 있어도
    gitscope.materialize_ref_sparse(db, "HEAD", tmp_path / "base")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert state() == before and " M CONTRIBUTING.md" in before[2] and "M  issue-db.config.yaml" in before[2]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["base", "other.index"]


def test_sparse_bad_ref_raises_and_leaves_no_index(tmp_path):
    db = git_db()
    with pytest.raises(gitscope.GitError):
        gitscope.materialize_ref_sparse(db, "no-such-ref", tmp_path / "base")
    assert [p.name for p in tmp_path.iterdir()] == ["base"] and not any((tmp_path / "base").iterdir())


def test_sparse_ignores_export_ignore_unlike_archive(tmp_path):
    """알려진 차이: git archive는 export-ignore를 빼지만 sparse는 꺼낸다. 이슈 DB는 export-* 속성을 쓰지 않는다."""
    assert "export-" not in (SAMPLE / ".gitattributes").read_text(encoding="utf-8")
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "a.txt").write_text("A\n", encoding="utf-8")
    (repo / ".gitattributes").write_text("a.txt export-ignore\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "attr")
    assert not (gitscope.materialize_ref(repo, "HEAD", tmp_path / "full") / "a.txt").exists()
    assert (gitscope.materialize_ref_sparse(repo, "HEAD", tmp_path / "sparse") / "a.txt").is_file()


# -- db_lint·db_verify: sparse와 전체 추출의 판정이 같다 -------------------------------------------------------

def _main(script: str, argv: list[str], capsys) -> tuple[int, str, str]:
    module = __import__(script)
    capsys.readouterr()
    code = module.main([*argv, "--plugin-root", str(plugin_root())])
    out, err = capsys.readouterr()
    return code, out, err


def _full_instead_of_sparse(monkeypatch):
    monkeypatch.setattr(gitscope, "materialize_ref_sparse",
                        lambda repo, ref, dest, exclude=None: gitscope.materialize_ref(repo, ref, dest))


def _r5_db(tmp_path) -> tuple[Path, Path]:
    """parser-rules 변경으로 R5가 실제로 도는(needs-approval) DB. 변경은 stage까지 한다."""
    db = git_db()
    edit(db / "parser-rules/extractors.yaml", "    event: ims_registered\n    fields: [transport]",
         "    event: ims_registered\n    fields: []")
    git(db, "add", "-A")
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"operations": []}), encoding="utf-8")
    return db, plan


def test_lint_and_verify_rules_same_output_with_sparse_base(tmp_path, monkeypatch, capsys):
    db, plan = _r5_db(tmp_path)
    calls = [("db_lint", ["--changed", "HEAD", "--db", str(db)]),
             ("db_lint", ["--staged", "--db", str(db)]),
             ("db_verify", ["rules", "--plan", str(plan), "--db", str(db), "--verbose"]),
             ("db_verify", ["rules", "--staged", "--db", str(db), "--verbose"]),
             ("db_verify", ["rules", "--changed", "HEAD", "--db", str(db), "--verbose"])]
    sparse = [_main(s, a, capsys) for s, a in calls]
    for code, out, _ in sparse[2:]:                                    # base schema·parser-rules가 있어 R5가 skipped가 아니다
        assert code == 3 and {r["id"]: r for r in json.loads(out)["rules"]}["R5"]["status"] == "needs-approval"
    _full_instead_of_sparse(monkeypatch)
    assert [_main(s, a, capsys) for s, a in calls] == sparse


def test_lint_broken_base_still_means_no_base_causes(monkeypatch, capsys):
    db = git_db()
    type_md = next((db / "call").glob("*/type.md"))
    good = type_md.read_bytes()
    type_md.write_text("---\nid: [\n", encoding="utf-8")
    git(db, "commit", "-qam", "broken base")
    type_md.write_bytes(good)
    import db_lint
    seen, real = [], db_lint._base_causes
    monkeypatch.setattr(db_lint, "_base_causes", lambda root: seen.append(real(root)) or seen[-1])
    sparse = _main("db_lint", ["--changed", "HEAD", "--db", str(db)], capsys)
    _full_instead_of_sparse(monkeypatch)
    assert _main("db_lint", ["--changed", "HEAD", "--db", str(db)], capsys) == sparse and seen == [None, None]


def test_failed_base_extraction_leaves_no_temp_dirs(tmp_path, monkeypatch, capsys):
    db, plan = _r5_db(tmp_path)
    temp = tmp_path / "t"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    real = gitscope.git

    def failing(repo, *args, **kw):
        if "--stdin" in args:                                          # sparse의 checkout-index만 실패
            raise gitscope.GitError("checkout-index 실패(테스트)")
        return real(repo, *args, **kw)

    monkeypatch.setattr(gitscope, "git", failing)
    for script, argv in [("db_lint", ["--changed", "HEAD", "--db", str(db)]),
                         ("db_lint", ["--staged", "--db", str(db)]),
                         ("db_verify", ["rules", "--plan", str(plan), "--db", str(db)]),
                         ("db_verify", ["rules", "--staged", "--db", str(db)])]:
        code, _, err = _main(script, argv, capsys)
        assert code == 2 and "checkout-index" in err, (script, argv, code, err)
        assert list(temp.iterdir()) == [], (script, argv)


# -- 하위 디렉토리 DB의 --staged/--changed: 경로는 DB 루트 기준 ----------------------------------------------------

_TYPE = "data/DATA-001-no-setup-data-call"


def _touch_type(db: Path, mark: str) -> None:
    path = db / _TYPE / "type.md"
    path.write_text(path.read_text(encoding="utf-8") + f"\n<!-- {mark} -->\n", encoding="utf-8", newline="\n")


def test_materialize_index_in_subdir_db_matches_top_level_db(tmp_path, monkeypatch):
    top, sub = git_db(), _subdir_db()
    for db in (top, sub):
        _touch_type(db, "staged")
        git(db, "add", "-A")
    want = _files(gitscope.materialize_index(top, tmp_path / "top"))
    assert "issue-db.config.yaml" in want and "top.txt" not in want
    assert _files(gitscope.materialize_index(sub, tmp_path / "sub")) == want
    # hook이 넘기는 GIT_INDEX_FILE(commit -a 등의 임시 index)을 그대로 따른다. 사용자 index는 그대로다.
    repo = sub.parent
    other = tmp_path / "other.index"
    other.write_bytes((repo / ".git" / "index").read_bytes())
    (sub / "extra.txt").write_text("x\n", encoding="utf-8", newline="\n")
    before = (repo / ".git" / "index").read_bytes()
    monkeypatch.setenv("GIT_INDEX_FILE", str(other))
    git(sub, "add", "extra.txt")
    got = _files(gitscope.materialize_index(sub, tmp_path / "alt"))
    assert gitscope.staged_files(sub) == sorted(["extra.txt", f"{_TYPE}/type.md"])
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert got == {**want, "extra.txt": b"x\n"} and (repo / ".git" / "index").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["alt", "other.index", "sub", "top"]   # 임시 index가 남지 않는다


def test_scope_files_in_subdir_db_are_db_relative(tmp_path):
    sub = _subdir_db()
    _touch_type(sub, "changed")
    (sub.parent / "top.txt").write_text("outside\n", encoding="utf-8")
    assert gitscope.changed_files(sub, "HEAD") == [f"{_TYPE}/type.md"]
    git(sub.parent, "add", "-A")
    assert gitscope.staged_files(sub) == [f"{_TYPE}/type.md"]
    assert "top.txt" in gitscope.staged_files(sub.parent)                         # 최상위 DB는 지금과 같다


def test_lint_and_regress_staged_in_subdir_db_check_the_changed_type(capsys):
    sub = _subdir_db()
    top = git_db()
    for db in (sub, top):
        _touch_type(db, "staged")
        git(db, "add", "-A")
    for argv in (["--staged"], ["--changed", "HEAD"]):
        got = []
        for db in (sub, top):
            code, out, err = _main("db_regress", [*argv, "--db", str(db)], capsys)
            assert code == 0, (argv, err)
            got.append(sorted(r["fixture"].replace("\\", "/") for r in json.loads(out)["results"]))
        assert got[0] and any(_TYPE in f for f in got[0]) and got[0] == got[1], (argv, got)   # 최상위 DB와 같은 범위
    for db in (sub, top):
        assert _main("db_build", ["--write", "--db", str(db)], capsys)[0] == 0
        git(db, "add", "-A")
        code, out, _ = _main("db_build", ["--verify", "--staged", "--db", str(db)], capsys)
        assert code == 0, out                                                    # index 트리를 DB 루트로 읽는다
    code, out, _ = _main("db_lint", ["--staged", "--db", str(sub)], capsys)
    assert code == 0 and json.loads(out)["summary"]["types"] > 0, out
    (sub / _TYPE / "type.md").write_text("---\nid: [\n", encoding="utf-8")
    git(sub, "add", "-A")
    code, out, _ = _main("db_lint", ["--staged", "--db", str(sub)], capsys)
    assert code == 1 and any(_TYPE in (e.get("file") or "") for e in json.loads(out)["errors"]), out


def test_mask_check_in_subdir_db_sees_only_db_files(capsys):
    sub = _subdir_db()
    note = f"{_TYPE}/issues/MOCK-1101.yaml"
    for path in (sub / note, sub.parent / "top.txt"):
        path.write_text(path.read_text(encoding="utf-8") + "# 고객 010-1234-5678\n", encoding="utf-8", newline="\n")
    (sub / "new.txt").write_text("010-1234-5678\n", encoding="utf-8")          # 추적 안 된 새 파일
    code, out, err = _main("mask_pii", ["--check", "--changed", "HEAD", "--db", str(sub)], capsys)
    assert code == 1 and sorted({d["path"] for d in json.loads(out)["detections"]}) == sorted(["new.txt", note]), (out, err)
    git(sub.parent, "add", "-A")
    code, out, err = _main("mask_pii", ["--check", "--staged", "--db", str(sub)], capsys)
    assert code == 1 and sorted({d["path"] for d in json.loads(out)["detections"]}) == sorted(["new.txt", note]), (out, err)

