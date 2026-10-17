import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
import usage_stats  # noqa: E402

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
START = T0.isoformat()
ANALYZE = {"source": "analyze", "started_at": START, "pr": {"number": None, "branch": "issue/X", "head_sha": None}}


def at(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def key(m=0):      # triage가 check_key에서 남기는 행(script 있음, start보다 먼저 쓰인다)
    return {"ts": at(m), "step": "0-key", "script": "jira_fields.py", "args": ["check-key", "SECRET-KEY-1"], "exit": 0}


def start(m=0):
    return {"ts": at(m), "step": "start", "v": 2, "pid": 1}


def row(step, m=0, **f):
    return {"ts": at(m), "step": step, **f}


def run(m=0):      # analyze 한 번(분석 완료까지)
    return [key(m), start(m), row("done", m + 5, candidates=1, calls=9)]


def _job(root: Path, name: str, plan=None, rows=(), tstate=None, files=(), analysis=None) -> Path:
    d = root / name
    d.mkdir(parents=True)
    for fname, doc in (("plan.json", plan), ("triage-state.json", tstate), ("analysis.json", analysis)):
        if doc is not None:
            (d / fname).write_text(json.dumps(doc), encoding="utf-8")
    if rows:
        (d / "trace.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    for f in files:
        if f == "wt":
            (d / "wt").mkdir()
        else:
            (d / f).write_text("{}", encoding="utf-8")
    return d


def _pr_plan(n=1):
    return {**ANALYZE, "pr": {"number": n, "branch": "issue/X", "head_sha": "a" * 40}}


def test_pr_time_from_trace_events_not_plan_mtime(tmp_path):
    # 회귀: 다음 날 같은 PR을 다시 publish(edited)해 plan.json이 바뀌어도 PR까지 시간은 첫 analyze → 첫 created
    rows = [*run(0), row("stage", 20, v=2, result="ok", dry_run=False),
            row("publish", 30, v=2, action="created", pr=1, gh_ok=True),
            row("discard", 31, v=2, outcome="after-publish"),
            row("publish", 1440, v=2, action="edited", pr=1, gh_ok=True)]
    d = _job(tmp_path, "A-1", _pr_plan(), rows)
    later = T0.timestamp() + 3 * 86400
    os.utime(d / "plan.json", (later, later))
    s = usage_stats.stats(tmp_path)
    assert s["states"]["pr"] == 1 and s["pr_minutes"] == {"n": 1, "median": 30.0, "mean": 30.0, "values": [30.0]}
    assert s["analysis_minutes"]["values"] == [5.0] and s["pr_unmeasured"] == 0


def test_pr_creation_failure_or_missing_events_is_unmeasured(tmp_path):
    _job(tmp_path, "A-1", _pr_plan(), [*run(0), row("publish", 30, v=2, action="created", pr=None, gh_ok=False)])
    _job(tmp_path, "R-1", {**_pr_plan(2), "source": "record"}, [row("stage", 1, v=2, result="ok", dry_run=False)])
    s = usage_stats.stats(tmp_path)
    assert s["states"]["pr"] == 2 and s["pr_minutes"]["n"] == 0 and s["pr_unmeasured"] == 2


@pytest.mark.parametrize("pushed_files", [["state.json"], []])     # push 기록은 state.json 유무와 무관하게 취소가 아니다
def test_pushed_without_number_is_separate(tmp_path, pushed_files):
    plan = {**ANALYZE, "pr": {"number": None, "branch": "issue/X", "head_sha": "a" * 40}}
    _job(tmp_path, "B-2", plan, run(0), files=pushed_files)
    s = usage_stats.stats(tmp_path)
    assert s["states"]["pushed"] == 1 and s["states"]["cancelled"] == 0


def test_saved_plan_only_is_held_not_cancelled(tmp_path):
    # 회귀: 예전엔 계획만 있고 PR·state·wt가 없으면 취소로 셌다
    _job(tmp_path, "H-1", ANALYZE, run(0))
    _job(tmp_path, "H-2", ANALYZE, run(0), tstate={"job": {"runs": [{"n": 1, "mode": "read-only", "dry_run": False}]}})
    s = usage_stats.stats(tmp_path)
    assert s["states"]["held"] == 2 and s["held_read_only"] == 1 and s["states"]["cancelled"] == 0
    assert s["cancel_ratio"] == 0


def test_cancel_then_resume_and_practice(tmp_path):
    cancel = [*run(0), row("stage", 10, v=2, result="ok", dry_run=False), row("discard", 12, v=2, outcome="cancel")]
    _job(tmp_path, "C-1", ANALYZE, cancel)                                  # 취소
    _job(tmp_path, "C-2", ANALYZE, [*cancel, *run(60)])                     # 취소 뒤 다시 analyze → 보류
    _job(tmp_path, "P-1", ANALYZE, [*run(0), row("stage", 9, v=2, result="ok", dry_run=True),
                                    row("discard", 10, v=2, outcome="dry-run")])
    _job(tmp_path, "P-2", None, run(0), analysis={"status": "ok"},
         tstate={"job": {"runs": [{"n": 1, "mode": "write", "dry_run": True}]}})
    s = usage_stats.stats(tmp_path)
    st = s["states"]
    assert (st["cancelled"], st["held"], st["practice"]) == (1, 1, 2)
    assert s["cancel_ratio"] == 0.5          # 취소 1 / (측정 4 − 연습 2)


def test_in_progress_analysis_only_no_result_unknown(tmp_path):
    _job(tmp_path, "I-1", ANALYZE, run(0), files=["state.json"])            # stage됨
    _job(tmp_path, "I-2", ANALYZE, run(0), files=["wt"])                    # wt 남음
    _job(tmp_path, "I-3", None, [key(0), start(0)], tstate={"pending": {"kind": "time", "asked_at": START}})
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "session.lock").write_text(json.dumps({"job": "I-3", "owner": "o", "command": "analyze",
                                                       "started_at": now, "updated_at": now}), encoding="utf-8")
    _job(tmp_path, "N-1", None, [key(0), start(0)], tstate={"pending": {"kind": "time", "asked_at": START}})
    _job(tmp_path, "N-2", None, [key(0), start(0), row("error", 1, exit=2, message="secret-msg")])
    _job(tmp_path, "AO-1", None, run(0), analysis={"status": "ok"},
         tstate={"job": {"runs": [{"n": 1, "mode": "analysis-only", "dry_run": False},
                                  {"n": 2, "mode": "analysis-only", "dry_run": False}]}})
    _job(tmp_path, "U-1", {**ANALYZE, "pr": {"number": "x"}}, run(0))      # 형식 손상
    s = usage_stats.stats(tmp_path)
    st = s["states"]
    assert (st["in_progress"], st["no_result"], st["analysis_only"], st["unknown"]) == (3, 2, 1, 1)
    assert s["analysis_only_runs"] == 2 and s["jobs"] == 7
    assert s["cancel_ratio"] == 0            # 분모 = 7 − 진행 중 3 − 손상 1


def test_legacy_other_flows_and_excluded_folders(tmp_path):
    _job(tmp_path, "L-1", _pr_plan(), [key(0), {"ts": at(0), "step": "start", "pid": 1}])   # 업데이트 전 기록(v 없음)
    _job(tmp_path, "L-2", ANALYZE, [])                                                     # trace 없는 옛 계획
    _job(tmp_path, "O-1", {**ANALYZE, "source": "review"}, [row("stage", 1, v=2, result="ok", dry_run=False)])
    _job(tmp_path, "_snapshot", ANALYZE, run(0))
    _job(tmp_path, "_x", ANALYZE, run(0))
    _job(tmp_path, ".shown", None, run(0))
    (tmp_path / "LOGS-1" / "logs").mkdir(parents=True)                                     # 표식 없는 폴더
    s = usage_stats.stats(tmp_path)
    assert s["jobs"] == 0 and s["other_flows"] == 1
    assert s["legacy"] == {"jobs": 2, "stages": {"plan-saved": 1, "pr-created": 1}}
    assert s["pr_minutes"]["n"] == 0 and s["questions"]["total"] == 0 and s["cancel_ratio"] is None


def test_questions_survive_answer_reset_and_skip_issue_kind(tmp_path):
    # 회귀: 저장된 답(answers)은 reset·--answer로 바뀌지만 needs_input 행은 세션을 넘겨 남는다
    rows = [key(0), start(0), row("needs_input", 1, kind="issue"), row("needs_input", 2, kind="time"),
            key(30), start(30), row("needs_input", 31, kind="code"), key(60), start(60), row("needs_input", 61, kind="time"),
            row("done", 70)]
    _job(tmp_path, "Q-1", None, rows, tstate={"answers": {}}, analysis={"status": "ok"})
    _job(tmp_path, "Q-2", None, run(0), analysis={"status": "ok"})
    q = usage_stats.stats(tmp_path)["questions"]
    assert q == {"jobs": 2, "total": 3, "per_job": 1.5, "by_kind": {"code": 1, "time": 2}}


def test_retries_runs_errors_stages_failed(tmp_path):
    rows = [key(0), start(0), row("error", 1, exit=2, message="x"), *run(10),
            row("stage", 20, v=2, result="drift", dry_run=False), row("stage", 21, v=2, result="check-failed", dry_run=False),
            row("stage", 22, v=2, result="error", dry_run=False, message="m"),
            row("stage", 23, v=2, result="needs-approval", dry_run=False), row("stage", 24, v=2, result="ok", dry_run=False)]
    _job(tmp_path, "R-1", ANALYZE, rows, files=["state.json"])
    assert usage_stats.stats(tmp_path)["retries"] == {"runs": 2, "errors": 1, "stages": 5, "stage_failed": 3}


def test_json_and_text_carry_counts_only(tmp_path, capsys):
    _job(tmp_path, "SECRET-KEY-1", ANALYZE, [*run(0), row("error", 1, exit=2, message="secret-msg"),
                                              row("stage", 2, v=2, result="error", dry_run=False, message="secret-msg")])
    assert usage_stats.main(["--work-dir", str(tmp_path), "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["format"] == 2 and data["platform"] is None and data["tokens"] is None
    assert set(data) == {"format", "platform", "work_dir", "jobs", "states", "held_read_only", "analysis_only_runs",
                         "cancel_ratio", "pr_minutes", "pr_unmeasured", "analysis_minutes", "questions", "retries",
                         "legacy", "other_flows", "tokens"}
    assert usage_stats.main(["--work-dir", str(tmp_path)]) == 0
    text = capsys.readouterr().out
    lines = text.splitlines()
    assert len(lines) == 9 and lines[0].startswith("집계 대상:") and any("취소 비율" in ln for ln in lines)
    assert lines[-1] == "토큰: 미측정"
    for blob in (out, text):
        assert "SECRET-KEY-1" not in blob and "secret-msg" not in blob


@pytest.fixture
def two_platforms(tmp_path, monkeypatch, capsys):
    """android work_dir(보류 1건)·ofono work_dir(PR 2건)을 가진 사용자 config와 `main` 호출 도우미."""
    import yaml

    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import platforms
    from common import userconfig
    from runner import plugin_root

    root = plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv(userconfig.HOME_ENV, str(home))
    monkeypatch.delenv(platforms.ENV, raising=False)
    wa, wo = tmp_path / "wa", tmp_path / "wo"
    _job(wa, "A-1", ANALYZE, run(0))
    _job(wo, "O-1", _pr_plan(1), run(0))
    _job(wo, "O-2", _pr_plan(2), run(0))
    data = {"work_dir": str(wa), "platforms": {"ofono": {"work_dir": str(wo)}}}

    def write(**over):
        (home / "config.yaml").write_text(yaml.safe_dump({**data, **over}), encoding="utf-8")

    def main(*args):
        code = usage_stats.main([*args, "--plugin-root", str(root)])
        return code, capsys.readouterr()

    write()
    return {"main": main, "write": write, "wa": wa, "wo": wo, "env": platforms.ENV, "mp": monkeypatch}


def test_default_platform_is_android_and_first_line_names_target(two_platforms):
    code, out = two_platforms["main"]()
    lines = out.out.splitlines()
    assert code == 0 and lines[0] == f"집계 대상: 플랫폼 android · work_dir {two_platforms['wa']}"
    assert "상태: PR 0 " in out.out and "보류 1(" in out.out and "취소 비율 0/1 (0%)" in out.out


def test_user_config_platform_and_env_select_ofono(two_platforms):
    two_platforms["write"](platform="ofono")
    code, out = two_platforms["main"]()
    assert code == 0 and out.out.startswith(f"집계 대상: 플랫폼 ofono · work_dir {two_platforms['wo']}")
    assert "상태: PR 2 " in out.out
    two_platforms["write"]()
    two_platforms["mp"].setenv(two_platforms["env"], "ofono")
    code, out = two_platforms["main"]()
    assert code == 0 and out.out.startswith("집계 대상: 플랫폼 ofono") and "상태: PR 2 " in out.out
    code, out = two_platforms["main"]("--platform", "android")       # --platform이 TT_PLATFORM보다 우선
    assert code == 0 and "상태: PR 0 " in out.out


def test_explicit_work_dir_and_errors(two_platforms, tmp_path):
    main = two_platforms["main"]
    code, out = main("--work-dir", str(two_platforms["wo"]))
    assert code == 0 and out.out.splitlines()[0] == f"집계 대상: work_dir {two_platforms['wo']} (--work-dir 지정)"
    assert "상태: PR 2 " in out.out
    with pytest.raises(SystemExit) as exc:                            # 둘은 함께 쓸 수 없다(argparse)
        main("--work-dir", str(two_platforms["wo"]), "--platform", "android")
    assert exc.value.code == 2
    code, out = main("--work-dir", str(tmp_path / "nope"))
    assert code == 2 and "work_dir가 없다" in out.err
    code, out = main("--platform", "nosuch")
    assert code == 2 and "nosuch" in out.err


def test_json_output_has_counts_only(two_platforms):
    code, out = two_platforms["main"]("--work-dir", str(two_platforms["wo"]), "--json")
    data = json.loads(out.out)
    assert code == 0 and data["platform"] is None and data["work_dir"] == str(two_platforms["wo"])
    assert (data["states"]["pr"], data["jobs"], data["states"]["cancelled"]) == (2, 2, 0)
