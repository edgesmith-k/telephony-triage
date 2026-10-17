import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
import usage_stats  # noqa: E402
from common import shown  # noqa: E402

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
    assert lines[-1] == "토큰: 미측정 (--transcripts 없음)"
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


# -- --transcripts: transcript usage를 단계별로 ------------------------------------------------------------------------

SID = "11111111-2222-3333-4444-555555555555"


class _T:
    """합성 transcript(Claude Code 줄 모양: sessionId·message.id·usage, tool_use/tool_result)."""

    def __init__(self, sid=SID, version="2.1.300"):
        self.lines, self.sid, self.version, self.n = [], sid, version, 0

    def resp(self, *tools, usage=(10, 1, 100, 5), split=False, sidechain=False, model="claude-sonnet-5-5"):
        self.n += 1
        mid = f"msg_{self.n}"
        u = None if usage is None else dict(zip(("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                 "cache_creation_input_tokens"), usage))
        content = [{"type": "text", "text": "SECRET-TEXT"}]
        ids = []
        for name, inp, *_ in tools:
            ids.append(f"tu_{self.n}_{len(ids)}")
            content.append({"type": "tool_use", "id": ids[-1], "name": name, "input": inp})
        chunks = [[c] for c in content] if split else [content]
        for c in chunks:      # 한 응답이 여러 줄(같은 message.id) — usage는 줄마다 같은 값(중간값이면 작다)
            self.lines.append({"type": "assistant", "sessionId": self.sid, "version": self.version, "isSidechain": sidechain,
                               "message": {"id": mid, "model": model, "role": "assistant", "content": c,
                                           **({"usage": u} if u else {})}})
        for (name, inp, *rest), tid in zip(tools, ids):
            result, err = (rest + [("ok", False)])[0] if rest else ("ok", False)
            self.lines.append({"type": "user", "sessionId": self.sid, "isSidechain": sidechain, "message": {"role": "user",
                               "content": [{"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": err}]}})
        return self

    def user(self, text):
        self.lines.append({"type": "user", "sessionId": self.sid, "isMeta": True, "message": {"role": "user", "content": text}})
        return self

    def write(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in self.lines), encoding="utf-8")
        return path


def bash(cmd, result="ok", err=False):
    return ("Bash", {"command": cmd}, (result, err))


S = "python3 /p/scripts"


def test_transcripts_stage_markers_and_first_marker_attribution(tmp_path):
    t = _T()
    t.resp(usage=(1, 1, 1, 1))                                          # 첫 표식 전 → 첫 표식(basic) 단계
    t.resp(bash(f"{S}/triage.py run SECRET-KEY-1 --logs /secret/path.log"), split=True)
    t.resp(("Read", {"file_path": "/src/Foo.java"}))                    # basic 응답, 다음은 code
    t.resp(("Grep", {"pattern": "x", "path": "/src", "glob": "*.kt"}))  # code
    t.resp(bash("ls"))                                                  # code 응답, 코드 아닌 도구 → basic
    t.resp(("Skill", {"skill": "mock-analyzers:mock-data-analyzer"}))   # basic 응답, 다음 deep
    t.resp(bash(f"{S}/triage.py explore SECRET-KEY-1"))                  # deep
    t.resp(("Read", {"file_path": "/p/skills/telephony-triage/reference/db-authoring.md"}))   # explore
    t.resp(("Write", {"file_path": "/w/K/draft/x.yaml", "content": "c"}))                     # new_cause
    t.resp(bash(f"{S}/db_verify.py rules --plan p --draft d"), bash(f"{S}/parse_logcat.py cut x"),
           bash(f"{S}/db_add.py similar x"))                                                  # new_cause
    t.resp(("Write", {"file_path": "/w/K/plan.json", "content": "{}"}))                       # new_cause → write
    t.resp(bash(f"{S}/db_pr.py stage /w/K/plan.json --wt /w/K/wt --then-summary"))            # write
    t.resp(bash(f"{S}/issue_post.py render K"))                                               # write → post
    t.resp()                                                                                  # post
    t.write(tmp_path / "proj" / "a" / f"{SID}.jsonl")
    tok = usage_stats.transcripts(tmp_path / "proj")
    calls = {k: v["calls"] for k, v in tok["by_stage"].items() if v["calls"]}
    assert calls == {"basic": 4, "code": 2, "deep": 1, "explore": 1, "new_cause": 3, "write": 2, "post": 1}
    assert tok["by_stage"]["basic"]["input"] == 1 + 10 * 3                # 같은 message.id 두 줄은 한 번
    assert (tok["sessions"], tok["analyze_sessions"], tok["deep_calls"], tok["usage_missing"]) == (1, 1, 1, 0)
    total = tok["total"]
    assert total["calls"] == 14 and sum(v["input"] for v in tok["by_stage"].values()) == total["input"]
    assert tok["models"] == {"claude-sonnet-5-5": 14} and tok["versions"] == {"2.1.300": 1}


def test_transcripts_retry_window_subagent_asks_and_guard(tmp_path):
    t = _T()
    t.resp(bash(f"{S}/triage.py run K"))
    t.resp(bash(f"{S}/db_pr.py stage p --wt w", "Exit code 2\n계획 형식 오류", True))   # basic 응답, 실패 → retry
    t.resp()                                                                          # retry(도구 없음)
    t.resp(bash(f"{S}/db_pr.py stage p --wt w"))                                      # retry(도구 부름, 포함) → write
    t.resp(bash(f"{S}/db_pr.py stage p --wt w", "Exit code 3\n승인 필요", True))       # write, 종료 3은 실패 아님
    t.resp(("AskUserQuestion", {"questions": [{"question": "q"}]}, ("답", False)))      # write
    t.resp(("AskUserQuestion", {"questions": []}, ("InputValidationError: 선택지", True)))   # 입력 오류 질문은 안 셈
    t.resp(("AskUserQuestion", {"questions": []},
            (f"PreToolUse:AskUserQuestion hook error: {shown.MARKER} push:x — 거부됨", True)))   # 거부 → retry
    t.resp(bash("echo hi"))                                                             # retry
    t.user(f"Stop hook feedback:\n{shown.MARKER} report:K#1 — 되돌림(오류 아님)")           # Stop 되돌림 → retry
    t.resp(usage=None)                                                                 # retry, usage 없음
    t.resp(("mcp__mock__ask_user", {"question": "q"}, ("y", False)))                    # retry(도구) → 끝
    t.resp()                                                                           # write
    t.write(tmp_path / "proj" / "a" / f"{SID}.jsonl")
    sub = _T()
    sub.n = 100                                                          # message.id는 세션 안에서 응답마다 다르다
    sub.resp(bash("grep x"), usage=(7, 7, 7, 7), sidechain=True)
    sub.write(tmp_path / "proj" / "a" / SID / "subagents" / "agent-1.jsonl")
    side = _T()
    side.n = 200
    side.resp(usage=(2, 2, 2, 2), sidechain=True).write(tmp_path / "proj" / "a" / "side.jsonl")
    tok = usage_stats.transcripts(tmp_path / "proj")
    calls = {k: v["calls"] for k, v in tok["by_stage"].items() if v["calls"]}
    assert calls == {"basic": 2, "retry": 4, "write": 5, "subagent": 2}
    assert tok["by_stage"]["subagent"]["input"] == 9
    assert (tok["asks"], tok["show_guard"], tok["script_errors"], tok["usage_missing"]) == (2, {"stop": 1, "deny": 1}, 1, 1)
    assert sum(v["calls"] for v in tok["by_stage"].values()) == tok["total"]["calls"] == 13


def test_transcripts_skip_non_plugin_sessions_and_stream_json(tmp_path):
    other = _T(sid="other")
    other.resp(bash("python3 x.py"), ("Skill", {"skill": "dataviz"})).write(tmp_path / "p" / "o.jsonl")
    stream = [{"type": "assistant", "session_id": SID, "message": {"id": "m", "content": [{"type": "tool_use", "id": "t",
               "name": "Bash", "input": {"command": "triage.py run K"}}], "usage": {"input_tokens": 99}}},
              {"type": "result", "session_id": SID, "usage": {"input_tokens": 99}}]
    (tmp_path / "p" / "events.jsonl").write_text("".join(json.dumps(x) + "\n" for x in stream) + "not json\n", encoding="utf-8")
    tok = usage_stats.transcripts(tmp_path / "p")
    assert tok["sessions"] == 0 and tok["total"] is None
    _T().resp(("Skill", {"skill": "telephony-triage:analyze"}), usage=None).write(tmp_path / "p" / "s.jsonl")
    tok = usage_stats.transcripts(tmp_path / "p")
    assert tok["sessions"] == 1 and tok["total"] is None and tok["usage_missing"] == 1     # usage 없음 = 미측정(0 아님)


def test_transcripts_cli_output_has_numbers_only(tmp_path, capsys):
    t = _T()
    t.resp(bash(f"{S}/triage.py run SECRET-KEY-1 --logs /secret/path.log"))
    t.resp(("AskUserQuestion", {"questions": [{"question": "SECRET-Q"}]}, ("SECRET-ANSWER", False)))
    t.write(tmp_path / "proj" / "x" / f"{SID}.jsonl")
    (tmp_path / "work").mkdir()
    assert usage_stats.main(["--work-dir", str(tmp_path / "work"), "--transcripts", str(tmp_path / "proj"), "--json"]) == 0
    out = capsys.readouterr().out
    tok = json.loads(out)["tokens"]
    assert tok["sessions"] == 1 and tok["asks"] == 1 and tok["total"]["input"] == 20
    assert usage_stats.main(["--work-dir", str(tmp_path / "work"), "--transcripts", str(tmp_path / "proj")]) == 0
    text = capsys.readouterr().out
    assert text.splitlines()[-1].startswith("토큰(transcript, 세션 1·analyze 1)") and "대화 질문 1" in text
    for blob in (out, text):
        for secret in ("SECRET", SID, "path.log", "triage.py"):
            assert secret not in blob
    assert usage_stats.main(["--work-dir", str(tmp_path / "work"), "--transcripts", str(tmp_path / "none")]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("토큰: 미측정")
