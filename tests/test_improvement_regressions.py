"""I0: synthetic reproductions for Handoff R1–R6, now regression tests (RF-0 repaired them in I1/I2).

The quarantine (xfail strict) is removed: a reappearing defect raises KnownDefect and fails normally.
All destructive cases use pytest-owned temporary paths, never an operational clone.
R6 checks instructions, not actual Claude behavior (reserved for I5).
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, BrokenBarrierError

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import db_pr  # noqa: E402
import db_verify  # noqa: E402
import match_signatures  # noqa: E402
from common import compiled, issuedb  # noqa: E402
from runner import SAMPLE, git, run_json  # noqa: E402
import make_plugin_root  # noqa: E402


class KnownDefect(AssertionError):
    """Raise only at the behavioral assertion identifying a reviewed defect."""


def defect(issue: str, phase: str):
    """Labels the reviewed defect a test guards. Repaired in RF-0, so no longer an expected failure."""
    return lambda test: test


def _match_slots(sym_phone: int, cause_phone: int, *, regress=False, same_phone=True) -> dict:
    db = issuedb.load(SAMPLE)
    itype = db.type_by_id("DATA-001")
    cause = db.cause_by_id("DATA-001-01")
    db.types = [itype]
    itype.causes = [cause]
    itype.raw["symptom_signatures"] = [
        {"id": "sym", "must_event": [{"event": "sym"}], "window_sec": 60, "same_phone": same_phone}]
    cause.raw["signatures"] = [
        {"id": "cause", "must_event": [{"event": "cause"}], "window_sec": 60, "same_phone": same_phone}]
    events = [{"ts": f"2026-09-20T05:30:0{i}.000Z", "event": name, "phone_id": phone,
               "tag": "SYNTHETIC", "msg": name, "fields": {}, "source": "rules"}
              for i, (name, phone) in enumerate((("sym", sym_phone), ("cause", cause_phone)))]
    doc = {"masked": True, "events": events,
           "coverage": {"first_ts": events[0]["ts"], "last_ts": "2026-09-20T05:31:00.000Z"}}
    result = match_signatures.match(doc, db, compiled.compile_signatures(db, None), regress=regress)
    assert not result["errors"]
    return result


@defect("R1 independent S/C combined across SIM slots", "I2")
def test_r1_cross_slot_symptom_and_cause_do_not_form_candidate():
    result = _match_slots(0, 1)
    assert result["types"][0]["S"] == 1
    if any(c["cause"] == "DATA-001-01" for c in result["candidates"]):
        raise KnownDefect("SIM0 symptom was combined with a complete SIM1 cause signature")


@pytest.mark.parametrize("regress,same_phone,cause_phone", [(False, True, 0), (True, True, 1),
                                                            (False, False, 1)])
def test_r1_same_slot_independent_regression_and_explicit_cross_slot_controls(regress, same_phone, cause_phone):
    result = _match_slots(0, cause_phone, regress=regress, same_phone=same_phone)
    assert any(c["cause"] == "DATA-001-01" and c["C"] == 1 for c in result["causes"])
    if not regress:
        assert any(c["cause"] == "DATA-001-01" for c in result["candidates"])


@defect("R2 concurrent lock acquisition", "I1")
def test_r2_only_one_concurrent_job_acquires_lock(tmp_path, monkeypatch):
    # Force the original read/check/write race. With serialization, the first read
    # times out at the barrier and proceeds; the second can then observe its lease.
    barrier = Barrier(2)
    original_read = db_pr.Lock.read

    def simultaneous_read(self):
        held = original_read(self)
        try:
            barrier.wait(timeout=1)
        except BrokenBarrierError:
            pass
        return held

    monkeypatch.setattr(db_pr.Lock, "read", simultaneous_read)

    def acquire(job):
        try:
            return db_pr.Lock(tmp_path / "work").acquire(job, "test", False)["acquired"]
        except db_pr.UsageError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        acquired = list(pool.map(acquire, ("job-a", "job-b")))
    assert any(acquired), "at least one contender must succeed"
    if sum(acquired) != 1:
        raise KnownDefect(f"both contenders acquired the session lock: {acquired}")


@defect("R2 corrupted lock treated as absent", "I1")
def test_r2_malformed_lock_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "session.lock"
    original = '{"job": "still-writing"'
    path.write_text(original, encoding="utf-8")
    try:
        db_pr.Lock(tmp_path).acquire("new-job", "test", False)
    except db_pr.UsageError:
        pass
    if path.read_text(encoding="utf-8") != original:
        raise KnownDefect("an unreadable lease was overwritten without a recovery decision")


@pytest.fixture
def safety_context(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "--allow-empty", "-qm", "synthetic baseline")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    lock = db_pr.Lock(tmp_path / "work")
    lock.acquire("job", "test", False)
    cfg = {"issue_db": {"path": str(repo), "base_branch": "main"}, "work_dir": str(lock.work_dir)}
    return db_pr.Ctx(cfg, lock)


@defect("R3 discard outside work_dir", "I1")
def test_r3_discard_rejects_outside_directory_without_deleting_it(tmp_path, safety_context):
    # Same parent name as the authorized job, but outside the configured work_dir.
    target = tmp_path / "unrelated" / "job" / "wt"
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("synthetic user data", encoding="utf-8")
    assert target.resolve().is_relative_to(tmp_path.resolve())
    rejected = False
    try:
        db_pr.discard(safety_context, target)
    except db_pr.UsageError:
        rejected = True
    if not rejected or not marker.is_file():
        raise KnownDefect("discard accepted an unrelated directory or deleted its contents")
    assert marker.read_text(encoding="utf-8") == "synthetic user data"


@defect("R3 draft cleanup after failed git removal", "I1")
def test_r3_draft_cleanup_preserves_unregistered_directory(tmp_path, safety_context, monkeypatch):
    target = safety_context.work_dir / "job" / "draft"
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("synthetic user data", encoding="utf-8")
    assert target.resolve().is_relative_to(tmp_path.resolve())
    monkeypatch.setattr(db_verify.userconfig, "merged", lambda defaults: safety_context.cfg)
    rejected = False
    try:
        db_verify.remove_draft(target, {})
    except db_verify.UsageError:
        rejected = True
    if not rejected or not marker.is_file():
        raise KnownDefect("draft removal did not reject a non-worktree directory safely")


def _parse_files(paths: list[Path]) -> dict:
    return run_json("parse_logcat.py", ["parse", *paths, "--full", "--mask", "--tz", "Asia/Seoul",
                                         "--year", "2026", "--rules", SAMPLE / "parser-rules"])


RIL_REQUEST = "09-22 12:00:00.000  1234  1244 D RILJ: [PHONE0] [0043]> SEND_SMS\n"
RIL_RESPONSE = "09-22 12:00:01.000  1234  1244 D RILJ: [PHONE0] [0043]< SEND_SMS error=NONE\n"
RIL_TAIL = "09-22 12:01:00.000  1234  1244 D RILJ: [PHONE0] [UNSL]< UNSOL_RESPONSE_NEW_SMS\n"


@pytest.mark.parametrize("rotated", [False, True])   # True: R4 rotated RIL response (repaired in I2)
def test_r4_normal_response_is_paired_across_capture_files(tmp_path, rotated):
    first = tmp_path / "radio-1.log"
    second = tmp_path / "radio-2.log"
    first.write_text(RIL_REQUEST + ("" if rotated else RIL_RESPONSE + RIL_TAIL), encoding="utf-8")
    second.write_text(RIL_RESPONSE + RIL_TAIL, encoding="utf-8")
    doc = _parse_files([first, second] if rotated else [first])
    requests = [e for e in doc["events"] if e.get("ril") and e["ril"].get("dir") == "req"]
    assert requests, "the synthetic request must actually be parsed"
    bad = [e for e in doc["events"] if e.get("event") == "ril_no_response"]
    if bad or not all(e["ril"].get("paired_ts") for e in requests):
        raise KnownDefect("normal response in the same capture was lost at a file boundary")


@pytest.mark.parametrize("kind", ["fix", "resolution"])
@defect("R5 external parser process failure still passes verification", "I2")
def test_r5_real_external_failure_cannot_produce_passed(tmp_path, kind):
    root = make_plugin_root.make(tmp_path / "plugin", with_site_backend=True)
    db = tmp_path / "db"
    shutil.copytree(REPO / "tests/fixtures/issue-db-verify", db)
    defaults_path = root / "site-defaults.yaml"
    defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
    defaults["external_parsers"] = {"call": {
        "command": [sys.executable, "-c", "import sys; sys.exit(7)"], "output": "json",
        "adapter": "site_data_existing", "version": "1.2.0", "mode": "replace", "timeout_sec": 5}}
    defaults_path.write_text(yaml.safe_dump(defaults, allow_unicode=True), encoding="utf-8")
    type_path = db / "call/CALL-001-volte-not-working/type.md"
    front, body = type_path.read_text(encoding="utf-8").split("---\n", 2)[1:]
    meta = yaml.safe_load(front)
    cause = next(c for c in meta["causes"] if c["id"] == "CALL-001-01")
    # Cause detection explicitly depends on the failed adapter; recovery/scenario
    # remain observable through ordinary rule events in the same synthetic log.
    cause["signatures"] = [{"id": "external-cause", "must_event": [{"event": "ext.call.failure"}],
                            "window_sec": 60}]
    type_path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                         + "---\n" + body, encoding="utf-8")
    log = REPO / "tests/fixtures/verify-logs/call-fixed.log"
    assert log.is_file()
    parsed = run_json("parse_logcat.py", ["parse", log, "--full", "--mask", "--rules", db / "parser-rules",
                                           "--tz", "Asia/Seoul", "--year", "2026"], root=root)
    assert any(w["code"] == "external-parser-failed" and "7" in w["message"] for w in parsed["warnings"])
    assert parsed["events"], "recovery must remain observable despite the external failure"
    args = [kind, "--cause", "CALL-001-01", log, "--db", db]
    if kind == "fix":
        args += ["--build", "MOCKB77_U2_20260925"]
    out = run_json("db_verify.py", args, root=root, expect=(0, 1, 2, 3))
    if out.get("judgement") == "passed":
        raise KnownDefect(f"{kind} passed although its cause parser exited with status 7")
    assert out.get("judgement") == "unknown" or out.get("error"), out


@pytest.mark.parametrize("relative", ["plugin/skills/telephony-triage/reference/write-flow.md",
                                      "plugin/skills/telephony-triage/reference/sync-pr.md",
                                      "docs/design/07-workflow.md"])
@defect("R6 approved message interpolated into shell command", "I1")
def test_r6_instructions_do_not_interpolate_approved_message(relative):
    text = (REPO / relative).read_text(encoding="utf-8")
    unsafe = re.findall(r"commit\s+-m\s+[^`\n]+", text)
    if unsafe:
        raise KnownDefect(f"{relative} inserts message data into shell syntax: {unsafe}")


def test_r6_message_file_preserves_shell_metacharacters(safety_context, tmp_path):
    # This control runs argv directly; it never executes the message as shell code.
    message = '[MOCK-1] "quoted" $HOME $(echo synthetic) `echo synthetic` ; & | < >\n\n본문\n'
    path = tmp_path / "message.txt"
    path.write_text(message, encoding="utf-8", newline="\n")
    git(safety_context.repo, "commit", "--allow-empty", "-q", "-F", str(path))
    actual = git(safety_context.repo, "log", "-1", "--format=%B")
    assert actual.rstrip("\n") == message.rstrip("\n")
