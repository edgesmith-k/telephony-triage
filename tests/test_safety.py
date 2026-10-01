"""RF-0 regressions; all plugin code and configuration run from temporary roots."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
from runner import plugin_root, git  # noqa: E402


@pytest.fixture
def safety_root(monkeypatch):
    root = plugin_root("safety")
    monkeypatch.syspath_prepend(str(root / "scripts"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
    return root


def test_r6_commit_message_is_file_data(safety_root, tmp_path):
    for relative in ("skills/telephony-triage/reference/write-flow.md", "commands/sync-pr.md",
                     "skills/telephony-triage/SKILL.md"):
        instructions = (safety_root / relative).read_text(encoding="utf-8")
        assert "commit -m" not in instructions
        assert "commit -F" in instructions
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "data").write_text("synthetic", encoding="utf-8")
    message = 'RF-0 "quoted" $(touch INJECTED) `touch INJECTED` $HOME\n\nsecond line'
    message_file = tmp_path / "message.txt"
    message_file.write_text(message, encoding="utf-8")
    git(repo, "add", "data")
    git(repo, "commit", "-F", str(message_file))
    assert git(repo, "log", "-1", "--format=%B").rstrip() == message
    assert not (repo / "INJECTED").exists()


def test_r2_corrupt_lock_fails_closed(safety_root, tmp_path):
    module = importlib.import_module("db_pr")
    (tmp_path / "session.lock").write_text("{broken", encoding="utf-8")
    with pytest.raises(module.UsageError):
        module.Lock(tmp_path).acquire("job", None, False)


def test_r2_stale_owner_cannot_touch_or_release(safety_root, tmp_path):
    module = importlib.import_module("db_pr")
    old = module.Lock(tmp_path)
    old.acquire("job", None, False)
    new = module.Lock(tmp_path)
    new.acquire("job", None, True)
    for action in (lambda: old.touch("job"), lambda: old.release("job", False)):
        with pytest.raises(module.UsageError):
            action()
    assert new.read()["owner"] == new.owner


def test_r2_concurrent_processes_only_one_acquires(safety_root, tmp_path):
    script = '''import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from db_pr import Lock, UsageError
class SlowLock(Lock):
    def read(self):
        held = super().read()
        time.sleep(.15)
        return held
try:
    SlowLock(Path(sys.argv[2])).acquire(sys.argv[3], None, False)
except UsageError:
    sys.exit(2)
'''
    processes = [subprocess.Popen([sys.executable, "-c", script, str(safety_root / "scripts"),
                                  str(tmp_path), str(i)]) for i in range(4)]
    assert sorted(p.wait(timeout=15) for p in processes) == [0, 2, 2, 2]


def safety_ctx(tmp_path):
    module = importlib.import_module("db_pr")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "--allow-empty", "-qm", "synthetic")
    work = tmp_path / "work"
    lock = module.Lock(work)
    lock.acquire("job", None, False)
    return module, module.Ctx({"issue_db": {"path": str(repo)}, "work_dir": str(work)}, lock)


@pytest.mark.parametrize("location", ["outside", "plain", "foreign", "user-branch"])
def test_r3_remove_refuses_unowned_paths(safety_root, tmp_path, location):
    module, ctx = safety_ctx(tmp_path)
    target = (tmp_path / "outside" / "job" / "wt" if location == "outside"
              else ctx.work_dir / "job" / "wt")
    target.mkdir(parents=True)
    if location == "foreign":
        git(target, "init", "-q")
    if location == "user-branch":
        git(ctx.repo, "worktree", "add", "-b", "user", str(target))
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(module.UsageError):
        module._remove_worktree(ctx, target)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_r3_git_remove_failure_preserves_files(safety_root, tmp_path, monkeypatch):
    module, ctx = safety_ctx(tmp_path)
    target = ctx.work_dir / "job" / "wt"
    git(ctx.repo, "worktree", "add", "-b", "tt/job", str(target))
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    original = module._git
    def fail_remove(repo, *args, **kwargs):
        if args[:2] == ("worktree", "remove"):
            if kwargs.get("check", True):
                raise module.UsageError("synthetic removal failure")
            return subprocess.CompletedProcess(args, 1, "", "failure")
        return original(repo, *args, **kwargs)
    monkeypatch.setattr(module, "_git", fail_remove)
    with pytest.raises(module.UsageError):
        module._remove_worktree(ctx, target)
    assert marker.exists()


def test_r3_prepare_refuses_foreign_repo(safety_root, tmp_path):
    module, ctx = safety_ctx(tmp_path)
    target = ctx.work_dir / "job" / "wt"
    target.mkdir(parents=True)
    git(target, "init", "-q")
    git(target, "commit", "--allow-empty", "-qm", "foreign")
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(module.UsageError):
        module._prepare_worktree(ctx, target, "tt/job", "HEAD")
    assert marker.exists()


def test_r3_draft_and_symlink_boundaries(safety_root, tmp_path, monkeypatch):
    module, ctx = safety_ctx(tmp_path)
    verify = importlib.import_module("db_verify")
    monkeypatch.setattr(verify.userconfig, "merged", lambda defaults: ctx.cfg)
    outside = tmp_path / "outside" / "job" / "draft"
    outside.mkdir(parents=True)
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(verify.UsageError):
        verify.remove_draft(outside, {})
    assert marker.exists()
    link = ctx.work_dir / "job"
    try:
        link.symlink_to(outside.parent, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside.parent)],
                              capture_output=True)
        assert proc.returncode == 0
    with pytest.raises(module.UsageError):
        module._remove_worktree(ctx, link / "draft")
    assert marker.exists()


@pytest.mark.parametrize("relative", ["../outside/secret", "C:/outside/secret", "link/secret"])
def test_r9_resolve_stays_inside_root(safety_root, tmp_path, monkeypatch, relative):
    module = importlib.import_module("code_roots")
    monkeypatch.setattr(module, "_cfg", lambda defaults: {})
    root = tmp_path / "source"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("synthetic", encoding="utf-8")
    if relative == "link/secret":
        try:
            (root / "link").symlink_to(outside, target_is_directory=True)
        except OSError:
            assert os.name == "nt"
            assert subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "link"), str(outside)],
                                  capture_output=True).returncode == 0
    args = SimpleNamespace(roots=json.dumps({"aosp": str(root)}), ref=f"aosp:{relative}")
    with pytest.raises(module.UsageError):
        module.cmd_resolve(args, {})


def test_r8_git_timeout_is_environment_error(safety_root, tmp_path, monkeypatch):
    module = importlib.import_module("db_pr")
    def timeout(*args, **kwargs):
        assert 0 < kwargs.get("timeout", 0) <= 120
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(module.UsageError, match="시간 초과"):
        module._git(tmp_path, "fetch", "origin")
    with pytest.raises(module.UsageError, match="시간 초과"):
        module._git(tmp_path, "status", check=False)


def test_r8_gh_timeout_returns_failure(safety_root, monkeypatch):
    module = importlib.import_module("common.ghcli")
    def timeout(*args, **kwargs):
        assert 0 < kwargs.get("timeout", 0) <= 120
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(module.subprocess, "run", timeout)
    result = module.run(["auth", "status"])
    assert result.returncode != 0 and "시간 초과" in result.stderr


def test_r11_validate_pins_selected_db_and_config_base(safety_root):
    text = (safety_root / "commands" / "validate.md").read_text(encoding="utf-8")
    assert "git -C <db> fetch origin" in text
    assert "issue_db.base_branch" in text
    for line in text.splitlines():
        if line.startswith("   - `") and any(name in line for name in
                ("db_lint.py", "mask_pii.py", "db_regress.py", "db_verify.py", "db_build.py")):
            assert "--db <db>" in line


def test_r10_dependency_manifest_has_complete_pins(safety_root):
    import importlib.metadata as metadata
    import tomllib
    from packaging.requirements import Requirement
    manifest = REPO / "pyproject.toml"
    assert manifest.is_file(), "fresh environments need a dependency manifest"
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    requirements = [Requirement(value) for value in data["project"]["dependencies"]
                    + data["project"]["optional-dependencies"]["test"]]
    pins = {r.name.lower().replace("_", "-"): r for r in requirements}
    for name in ("pyyaml", "jsonschema", "pytest"):
        assert name in pins
    for requirement in requirements:
        assert str(requirement.specifier).startswith("==") and "*" not in str(requirement.specifier)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        assert metadata.version(requirement.name) in requirement.specifier
        for raw in metadata.requires(requirement.name) or []:
            child = Requirement(raw)
            if child.marker and not child.marker.evaluate({"extra": ""}):
                continue
            name = child.name.lower().replace("_", "-")
            assert name in pins, f"unlocked transitive dependency: {raw}"


@pytest.fixture
def draft_import(safety_root):
    target = safety_root / "import_draft.py"
    shutil.copy2(REPO / "tools" / "import_draft.py", target)
    spec = importlib.util.spec_from_file_location("safety_import_draft", target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("baseline", [False, True])
def test_r7_new_file_collision_stops(draft_import, tmp_path, baseline):
    source, dest = tmp_path / "source", tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "new.py").write_text("external", encoding="utf-8")
    (dest / "new.py").write_text("local", encoding="utf-8")
    if baseline:
        (dest / draft_import.MANIFEST).write_text(json.dumps({"schema": 1, "files": {}}), encoding="utf-8")
    result = draft_import.plan(source, dest, None)
    assert [item["path"] for item in result["locally_modified"]] == ["new.py"]
    assert draft_import.main([str(source), "--dest", str(dest), "--json"]) == 1
    assert (dest / "new.py").read_text(encoding="utf-8") == "local"


def test_r7_site_paths_file_is_protected(draft_import, tmp_path):
    source, dest = tmp_path / "source", tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    (source / "SITE_PATHS").write_text("external/\n", encoding="utf-8")
    (dest / "SITE_PATHS").write_text("local/\n", encoding="utf-8")
    result = draft_import.plan(source, dest, None)
    assert "SITE_PATHS" not in result["to_write"] + result["to_delete"]


def test_r7_failed_apply_rolls_back_files_and_manifest(draft_import, tmp_path, monkeypatch):
    source, dest = tmp_path / "source", tmp_path / "dest"
    source.mkdir()
    dest.mkdir()
    for name in ("a.py", "b.py", "removed.py"):
        (source / name).write_text("old", encoding="utf-8")
    result = draft_import.plan(source, dest, None)
    draft_import.apply(result, source, dest)
    draft_import.write_manifest(result, source, dest)
    before = {p.relative_to(dest).as_posix(): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    (source / "a.py").write_text("new", encoding="utf-8")
    (source / "b.py").write_text("new", encoding="utf-8")
    (source / "removed.py").unlink()
    result = draft_import.plan(source, dest, None)
    original = draft_import.shutil.copy2
    def fail_second(src, dst, *args, **kwargs):
        if Path(dst) == dest / "b.py":
            raise OSError("synthetic write failure")
        return original(src, dst, *args, **kwargs)
    monkeypatch.setattr(draft_import.shutil, "copy2", fail_second)
    with pytest.raises(OSError):
        draft_import.apply(result, source, dest)
    after = {p.relative_to(dest).as_posix(): p.read_bytes() for p in dest.rglob("*") if p.is_file()}
    assert after == before


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "invalid-json", "partial"])
def test_r5_external_failure_preserves_backend_and_blocks_pass(safety_root, tmp_path, failure):
    import yaml
    parse = importlib.import_module("parse_logcat")
    regress = importlib.import_module("db_regress")
    verify = importlib.import_module("db_verify")
    defaults = yaml.safe_load((safety_root / "site-defaults.yaml").read_text(encoding="utf-8"))
    scripts = {"nonzero": "raise SystemExit(7)", "timeout": "import time; time.sleep(5)",
               "invalid-json": "print('invalid')", "partial":
               "import sys; print('{}') if sys.argv[1].endswith('ok.log') else sys.exit(7)"}
    defaults["external_parsers"] = {"call": {"adapter": "site_data_existing", "mode": "replace",
        "command": [sys.executable, "-c", scripts[failure], "{log}"], "timeout_sec": .1 if failure == "timeout" else 5}}
    db = REPO / "tests" / "fixtures" / "issue-db-verify"
    source = REPO / "tests" / "fixtures" / "verify-logs" / "call-fixed.log"
    paths = [source]
    if failure == "partial":
        ok = tmp_path / "ok.log"
        shutil.copy2(source, ok)
        paths.append(ok)
    run = verify.Run(db, safety_root, defaults)
    try:
        doc = run.parse(paths)
        assert any(e["source"].startswith("backend:") and e["category_hint"] == "call" for e in doc["events"])
        assert regress.match_errors({"errors": []}, doc)["errors"]
        cause = run.db.cause_by_id("CALL-001-01")
        assert verify.judge_resolution(run, cause, paths)["judgement"] == "unknown"
        assert verify.judge_fix(run, cause, paths)["judgement"] == "unknown"
    finally:
        run.close()


@pytest.mark.parametrize("sym_slot,cause_slot,gap,cross,expected", [
    (0, 1, 1, False, 0), (0, 0, 120, False, 0),
    (0, 0, 1, False, 1), (None, 1, 1, False, 1), (0, 1, 1, True, 1),
])
def test_r1_analysis_requires_compatible_symptom_and_cause(
        safety_root, sym_slot, cause_slot, gap, cross, expected):
    from datetime import datetime, timedelta, timezone
    matcher = importlib.import_module("match_signatures")
    issuedb = importlib.import_module("common.issuedb")
    compiled = importlib.import_module("common.compiled")
    db = issuedb.load(REPO / "tests" / "fixtures" / "issue-db-sample")
    db.types = db.types[:1]
    itype = db.types[0]
    itype.causes = itype.causes[:1]
    cause = itype.causes[0]
    itype.raw["symptom_signatures"] = [{"id": "sym", "must_event": [{"event": "SYM"}], "window_sec": 60}]
    cause.raw["signatures"] = [{"id": "cause", "must_event": [{"event": "CAUSE"}], "window_sec": 60,
                                "same_phone": not cross}]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def event(name, slot, offset):
        return {"ts": (start + timedelta(seconds=offset)).isoformat(), "event": name,
                "phone_id": slot, "fields": {}, "tag": "SYNTHETIC", "msg": name}
    events = [event("SYM", sym_slot, 0), event("CAUSE", cause_slot, gap)]
    doc = {"masked": True, "events": events, "coverage": {"first_ts": events[0]["ts"],
                                                            "last_ts": events[-1]["ts"]}}
    signatures = compiled.compile_signatures(db, None)
    analysis = matcher.match(doc, db, signatures, regress=False)
    assert analysis["causes"][0]["C"] == expected
    regression = matcher.match(doc, db, signatures, regress=True)
    assert regression["causes"][0]["C"] == 1, "regression C remains independent"
    # A valid later symptom on the cause slot must not be hidden by the first symptom.
    if expected == 0:
        doc["events"].append(event("SYM", cause_slot, gap))
        assert matcher.match(doc, db, signatures, regress=False)["causes"][0]["C"] == 1


def test_r1_all_sample_regressions_keep_independent_c(safety_root):
    from runner import SAMPLE, run_json
    result = run_json("db_regress.py", ["--all", "--db", SAMPLE], root=safety_root)
    assert result["summary"]["failed"] == 0


def parse_synthetic(safety_root, paths):
    import yaml
    from runner import SAMPLE
    module = importlib.import_module("db_regress")
    defaults = yaml.safe_load((safety_root / "site-defaults.yaml").read_text(encoding="utf-8"))
    return module.parse_logs(paths, SAMPLE / "parser-rules", safety_root, defaults)


def ril_line(second, message, pid=1234):
    return f"09-22 12:{second // 60:02}:{second % 60:02}.000  {pid}  {pid} D RILJ: [PHONE0] {message}\n"


def test_r4_rotated_response_pairs_before_windowing(safety_root, tmp_path):
    first, second = tmp_path / "radio.log.1", tmp_path / "radio.log"
    first.write_text(ril_line(0, "[0043]> SEND_SMS"), encoding="utf-8")
    second.write_text(ril_line(1, "[0043]< SEND_SMS error=NONE") +
                      ril_line(60, "[UNSL]< UNSOL_RESPONSE_NEW_SMS"), encoding="utf-8")
    doc = parse_synthetic(safety_root, [second, first])
    request = next(e for e in doc["events"] if e.get("ril") and e["ril"]["dir"] == "req")
    assert request["ril"]["latency_ms"] == 1000
    assert not any(e["event"] == "ril_no_response" for e in doc["events"])
    backend = importlib.import_module("parser_backends.reference").BACKEND
    logcat = importlib.import_module("parser_backends.logcat")
    stamp = logcat.parse_ts("2026-09-22T12:00:01.000Z")
    response_only = backend.parse([second, first], "UTC", 2026, (stamp, stamp))
    assert len(response_only) == 1 and response_only[0]["ril"]["latency_ms"] == 1000


@pytest.mark.parametrize("boundary", ["buffer-file", "device-directory", "buffer-header", "clock", "boot", "pid"])
def test_r4_unrelated_coverage_does_not_prove_no_response(safety_root, tmp_path, boundary):
    first = tmp_path / "radio.log"
    first.write_text(ril_line(0, "[0043]> SEND_SMS"), encoding="utf-8")
    tail = ril_line(60, "[UNSL]< UNSOL_RESPONSE_NEW_SMS")
    second = tmp_path / "main.log"
    if boundary == "device-directory":
        second = tmp_path / "other-device" / "radio.log"
        second.parent.mkdir()
    elif boundary in ("buffer-header", "clock", "boot", "pid"):
        second = first
        prefix = {"buffer-header": "--------- beginning of main\n", "clock":
                  "09-22 11:59:00.000  1234  1234 I DNC-0: clock reset\n",
                  "boot": "09-22 12:00:01.000  1  1 I boot_progress_start: 1\n", "pid": ""}[boundary]
        if boundary == "pid":
            tail = ril_line(60, "[UNSL]< UNSOL_RESPONSE_NEW_SMS", pid=2345)
        tail = first.read_text(encoding="utf-8") + prefix + tail
    second.write_text(tail, encoding="utf-8")
    paths = [first] if first == second else [first, second]
    doc = parse_synthetic(safety_root, paths)
    assert not any(e["event"] == "ril_no_response" for e in doc["events"])


def test_r4_reused_serial_after_boot_is_not_paired(safety_root, tmp_path):
    path = tmp_path / "radio.log"
    path.write_text(ril_line(0, "[0043]> SEND_SMS") +
                    "09-22 12:00:01.000  1  1 I boot_progress_start: 1\n" +
                    ril_line(2, "[0043]< SEND_SMS error=NONE"), encoding="utf-8")
    doc = parse_synthetic(safety_root, [path])
    assert all(e["ril"]["paired_ts"] is None for e in doc["events"] if e.get("ril"))
