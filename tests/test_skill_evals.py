"""실행되지 않은 평가를 통과로 세지 않고 API 중단을 보존한다."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "skill_evals"))
import grade as grader  # noqa: E402

spec = importlib.util.spec_from_file_location("skill_eval_run", REPO / "tests" / "skill_evals" / "run.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def run_dir(tmp_path):
    run = tmp_path / "with_skill"
    (run / "outputs").mkdir(parents=True)
    return run


def test_empty_output_directory_is_not_a_success(tmp_path):
    run = run_dir(tmp_path)
    result = grader.grade(24, run, tmp_path / "nonexistent-env", ["기록하지 않고 끝냄"])
    assert result["status"] == "not-run"
    assert result["summary"]["passed"] == 0
    assert result["summary"]["undecided"] == result["summary"]["total"]
    assert all(row["passed"] is None for row in result["expectations"])


@pytest.mark.parametrize("has_artifacts", [True, False])
def test_api_failure_is_incomplete_even_with_output_artifacts(tmp_path, has_artifacts):
    run = run_dir(tmp_path)
    if has_artifacts:
        for name in ("transcript.md", "commands.md"):
            (run / "outputs" / name).write_text("일부 실행 기록", encoding="utf-8")
    (run / "execution.json").write_text(json.dumps({"status": "blocked", "reason": "HTTP 429"}), encoding="utf-8")
    result = grader.grade(24, run, tmp_path / "nonexistent-env", ["lock 해제"])
    assert result["status"] == "incomplete"
    assert result["expectations"][0]["evidence"] == "HTTP 429"
    assert result["summary"]["passed"] == 0


def test_machine_grades_refresh_but_manual_grades_are_preserved(tmp_path, monkeypatch):
    run = run_dir(tmp_path)
    for name in ("transcript.md", "commands.md"):
        (run / "outputs" / name).write_text("실행 기록", encoding="utf-8")
    (run / "grading.json").write_text(json.dumps({"expectations": [
        {"text": "기계", "passed": True, "source": "script", "evidence": "옛 결과"},
        {"text": "대화", "passed": True, "source": "manual", "evidence": "독립 평가"},
        {"text": "새 수동 항목", "passed": True, "source": "script", "evidence": "폐기할 옛 기계 판정"},
    ]}), encoding="utf-8")
    class FakeContext:
        def __init__(self, *_):
            pass
        def raw_full_reads(self):
            return []
        def raw_reads_blocked(self):
            return []
        def jira_writes(self):
            return True, "쓰기 없음"
    monkeypatch.setattr(grader, "Ctx", FakeContext)
    monkeypatch.setattr(grader, "checks", lambda *_: [lambda: (False, "새 상태 실패"), None, None])
    result = grader.grade(1, run, tmp_path, ["기계", "대화", "새 수동 항목"])
    assert result["expectations"][0]["passed"] is False
    assert result["expectations"][1]["passed"] is True
    assert result["expectations"][1]["evidence"] == "독립 평가"
    assert result["expectations"][2]["passed"] is None
    assert result["expectations"][2]["source"] == "manual"


def test_weekly_limit_stops_batch_without_claiming_completion():
    status, reason = evaluation.classify_result({"is_error": True, "api_error_status": 429,
                                                "result": "weekly limit"}, 1)
    assert status == "blocked"
    assert reason == "weekly limit"


def test_evaluator_prompt_does_not_leak_expected_answers(tmp_path):
    entry = {"prompt": "로그 분석해줘", "user_replies": ["취소"],
             "assertions": ["SECRET_EXPECTATION"], "expected_output": "SECRET_ANSWER"}
    prompt = evaluation.evaluation_prompt(entry, {"skill": "isolated/skill"}, tmp_path, tmp_path)
    assert "SECRET_EXPECTATION" not in prompt and "SECRET_ANSWER" not in prompt
    assert "로그 분석해줘" in prompt and "취소" in prompt


def test_plugin_prompt_sends_request_verbatim_without_answers_or_skill_paths(tmp_path):
    entry = {"prompt": "/telephony-triage:record MOCK-1 --dry-run", "user_replies": ["취소"],
             "assertions": ["SECRET_EXPECTATION"], "expected_output": "SECRET_ANSWER"}
    user, system = evaluation.plugin_prompt(entry, tmp_path, tmp_path)
    assert user == entry["prompt"]                       # 슬래시 커맨드가 그대로 첫 메시지여야 커맨드로 들어간다
    assert "SECRET" not in user + system and "취소" in system
    assert "SKILL.md" not in system and "call.py" not in system   # 스킬 위치·모의 호출법을 알려주지 않는다


def test_prepare_plugin_mode_builds_mcp_config_and_analyzer_plugin(tmp_path):
    info = {"plugin_root": str(tmp_path / "root"),
            "env": {"MOCK_JIRA_DIR": "J", "MOCK_JIRA_WRITE_LOG": "W", "PYTHONIOENCODING": "utf-8"}}
    out = evaluation.prepare_plugin_mode({"setup": {"analyzer_fail": True}}, info, tmp_path)
    mcp = json.loads(Path(out["mcp_config"]).read_text(encoding="utf-8"))["mcpServers"]["mock-jira"]
    assert mcp["args"][0].endswith("jira_mcp/server.py") and mcp["env"]["MOCK_JIRA_DIR"] == "J"
    approver = json.loads(Path(out["mcp_config"]).read_text(encoding="utf-8"))["mcpServers"]["eval-approver"]
    assert approver["env"]["MOCK_APPROVALS_LOG"] == str(tmp_path / "approvals.json")
    analyzer = Path(out["plugin_dirs"][1])
    assert out["plugin_dirs"][0] == info["plugin_root"]
    assert json.loads((analyzer / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"] == "mock-analyzers"
    skill = analyzer / "skills" / "mock-data-analyzer"
    assert "tests/mocks/skills" not in (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "internal error" in (skill / "run.py").read_text(encoding="utf-8")      # analyzer_fail


def _init(plugins, servers):
    return {"type": "system", "subtype": "init", "plugins": [{"name": p} for p in plugins],
            "mcp_servers": [{"name": n, "status": st} for n, st in servers.items()]}


def test_plugin_check_flags_missing_plugin_or_mcp_and_summarizes_calls():
    tool = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": "telephony-triage:telephony-triage"}},
        {"type": "tool_use", "name": "mcp__mock-jira__jira_post_comment", "input": {}}]}}
    hook = {"type": "system", "subtype": "hook_response", "hook_event": "PreToolUse",
            "hook_name": "PreToolUse:mcp__mock-jira__jira_post_comment", "exit_code": 2, "output": ""}
    connected = {"mock-jira": "connected", "eval-approver": "connected"}
    ok, seen = evaluation.plugin_check([_init(["telephony-triage"], connected), tool, hook])
    assert ok is None and seen["skill_calls"] == ["telephony-triage:telephony-triage"]
    assert seen["mcp_calls"] == ["mcp__mock-jira__jira_post_comment"] and seen["hooks"] == {"PreToolUse": 1}
    assert seen["hooks_blocked"] == ["PreToolUse:mcp__mock-jira__jira_post_comment"]
    assert evaluation.plugin_check([_init([], connected)])[0]
    assert evaluation.plugin_check([_init(["telephony-triage"], {**connected, "mock-jira": "failed"})])[0]
    assert evaluation.plugin_check([_init(["telephony-triage"], {"mock-jira": "connected"})])[0]   # 승인 서버 없음
    assert evaluation.plugin_check([])[0]


def test_approver_allows_and_logs_permission_requests(tmp_path, monkeypatch):
    spec_a = importlib.util.spec_from_file_location("eval_approver", REPO / "tests" / "mocks" / "approver_mcp" / "server.py")
    approver = importlib.util.module_from_spec(spec_a)
    spec_a.loader.exec_module(approver)
    log = tmp_path / "approvals.json"
    monkeypatch.setenv("MOCK_APPROVALS_LOG", str(log))
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "approve", "arguments": {"tool_name": "Bash", "input": {"command": "db_pr.py publish"}}}}
    reply = json.loads(approver.handle(call)["result"]["content"][0]["text"])
    assert reply == {"behavior": "allow", "updatedInput": {"command": "db_pr.py publish"}}
    monkeypatch.setenv("EVAL_APPROVER_DENY", "1")
    assert json.loads(approver.handle(call)["result"]["content"][0]["text"])["behavior"] == "deny"
    assert [r["decision"] for r in json.loads(log.read_text(encoding="utf-8"))] == ["allow", "deny"]


# -- 정의 정합성 (실행 없이) ---------------------------------------------------------------------

EVALS = REPO / "tests" / "skill_evals"
sys.path.insert(0, str(REPO / "tests" / "helpers"))


def _entries() -> list[dict]:
    return json.loads((EVALS / "evals.json").read_text(encoding="utf-8"))["evals"]


def test_eval_ids_are_unique_and_consecutive():
    ids = [e["id"] for e in _entries()]
    assert ids == list(range(1, len(ids) + 1)), ids


def test_every_eval_has_required_keys_and_assertions():
    for e in _entries():
        for key in ("id", "name", "prompt", "setup", "user_replies", "expected_output", "assertions"):
            assert e.get(key), (e["id"], key)
        assert all(isinstance(a, str) and a for a in e["assertions"]), e["id"]


def test_eval_setup_references_resolve():
    import make_variant_dbs
    import skill_eval_env
    from runner import fixture_path

    dbs = {"issue-db-sample", *make_variant_dbs.VARIANTS}
    for e in _entries():
        setup = e["setup"]
        assert setup.get("db", "issue-db-sample") in dbs, (e["id"], setup.get("db"))
        for key in setup.get("jira") or []:
            assert skill_eval_env._find_jira(key).is_file(), (e["id"], key)
        for item in setup.get("logs") or []:
            if "src" in item:
                assert fixture_path(item["src"]).is_file(), (e["id"], item["src"])
            else:
                assert (EVALS / "scenarios" / item["scenario"]).is_file(), (e["id"], item["scenario"])
        for inj in setup.get("inject_main") or []:
            assert (EVALS / "scenarios" / inj["scenario"]).is_file(), (e["id"], inj["scenario"])


def test_split_buffers_setup_writes_one_file_per_buffer(tmp_path):
    import skill_eval_env

    entry = next(e for e in _entries() if e["id"] == 50)
    env = skill_eval_env.build(entry, tmp_path / "env")
    assert env is not None
    logs = sorted(p.name for p in (tmp_path / "env" / "logs").iterdir())
    assert logs == ["e050.main.log", "e050.radio.log"], logs


# --- 3D-C: eval 실행기·채점 보정 ---------------------------------------------------------

def _bash_events(run, *commands, extra=()):
    rows = []
    for c in commands:
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": c}}]}})
    for name, inp in extra:
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})
    (run / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _synthetic_env(tmp_path):
    env_dir = tmp_path / "env"
    (env_dir / "logs").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    (env_dir / "env.json").write_text(json.dumps({"remote": str(tmp_path / "remote"), "work_dir": str(work),
                                                  "issue_db_clone": str(tmp_path / "clone"),
                                                  "gh_state": str(tmp_path / "gh")}), encoding="utf-8")
    (env_dir / "before.json").write_text("{}", encoding="utf-8")
    return env_dir


def test_e50_order_uses_ran_not_command_descriptions(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    # commands.md 표의 설명 칸에 (역순) cut 문장이 있어도 실제 실행 기록이 기준이다
    (run / "outputs" / "commands.md").write_text(
        "| 1 | 로그 자르기 | python3 x.py |\n| 2 | e050.radio.log e050.main.log 순으로 cut … --evidence | python3 y.py |\n",
        encoding="utf-8")
    (run / "outputs" / "transcript.md").write_text("t", encoding="utf-8")
    _bash_events(run, "python3 triage.py cut --evidence /e/logs/e050.main.log /e/logs/e050.radio.log")
    ctx = grader.Ctx(env_dir, run)
    assert "e050.radio.log e050.main.log" in ctx.invoked      # 설명 칸이 invoked에는 섞여 들어간다
    assert "e050.radio.log e050.main.log" not in ctx.ran
    fns = grader.checks(50, ctx)
    assert fns[0]()[0] is True
    assert fns[2]()[0] is True, fns[2]()


def test_raw_full_reads_metric(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    (run / "outputs" / "transcript.md").write_text("t", encoding="utf-8")
    (run / "outputs" / "commands.md").write_text("c", encoding="utf-8")
    _bash_events(run, "cat logs/e.log", "head -c 100000 logs/e.log", "head -n 20 logs/e.log", "grep X logs/e.log",
                 "unzip -p logs/a.zip", "cat notes.txt", "less jira_raw.json", "strings logs/e.log | head",
                 extra=[("Read", {"file_path": "/x/logs/e.log"}),
                        ("Read", {"file_path": "/x/logs/e.log", "limit": 50}),
                        ("Read", {"file_path": "/x/events.json"}),
                        ("Read", {"file_path": "/x/other.md"})])
    reads = grader.Ctx(env_dir, run).raw_full_reads()
    assert len(reads) == 7, reads
    assert not any("head -n" in r or "grep" in r or "notes.txt" in r or "limit" in r for r in reads)
    assert "Read /x/events.json" in reads


def test_plugin_mode_env_json_has_no_direct_tool_keys(tmp_path):
    import skill_eval_env

    entry = next(e for e in _entries() if e["id"] == 40)
    plugin_info = skill_eval_env.build(entry, tmp_path / "plugin", direct_tools=False)
    stored = json.loads((tmp_path / "plugin" / "env.json").read_text(encoding="utf-8"))
    for key in ("jira_call", "jira_tools_list", "analyzer_run"):
        assert key not in plugin_info and key not in stored, key
    direct = skill_eval_env.build(entry, tmp_path / "direct")
    assert all(k in direct for k in ("jira_call", "jira_tools_list", "analyzer_run"))


# --- 3E-B: 규칙 10 반영·e40 순서·e46/e47 explore ---------------------------------------------

def _seq_events(run, items):
    """items: ("text", 문장) | ("tool", id, 이름, 입력, 결과|None, 오류여부)."""
    rows = []
    for it in items:
        if it[0] == "text":
            rows.append({"type": "assistant", "message": {"content": [{"type": "text", "text": it[1]}]}})
            continue
        _, tid, name, inp, result, err = it
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}})
        if result is not None:
            rows.append({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": err}]}})
    (run / "events.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def _write_artifacts(run):
    (run / "outputs" / "transcript.md").write_text("t", encoding="utf-8")
    (run / "outputs" / "commands.md").write_text("c", encoding="utf-8")


def test_e40_plan_with_plugin_seen_skill_calls_does_not_raise(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    job = tmp_path / "work" / "MOCK-9040"
    job.mkdir(parents=True)
    (job / "plan.json").write_text(json.dumps({"operations": [{"op": "append", "cause": "DATA-001-01"}],
                                                "feedback": {"decision": "chose-other"}}), encoding="utf-8")
    for plugin in ({"seen": {"skill_calls": ["mock-analyzers:mock-data-analyzer"]}},
                   {"skill_calls": ["mock-analyzers:mock-data-analyzer"]}):
        (run / "execution.json").write_text(json.dumps({"plugin": plugin}), encoding="utf-8")
        ok, evidence = grader.checks(40, grader.Ctx(env_dir, run))[4]()
        assert ok is True, evidence
    (run / "execution.json").write_text(json.dumps({"plugin": {"seen": {"skill_calls": []}}}), encoding="utf-8")
    assert grader.checks(40, grader.Ctx(env_dir, run))[4]()[0] is False


def test_blocked_raw_reads_are_counted_separately(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _seq_events(run, [
        ("tool", "t1", "Bash", {"command": "cat logs/e.log"}, "[telephony-triage] 로그 원문은 통째로 읽지 않는다(규칙 10)", True),
        ("tool", "t2", "Bash", {"command": "unzip -p logs/a.zip"}, "binary", False),
        ("tool", "t3", "Bash", {"command": "cat logs/e.log"}, "permission denied", True),   # 다른 오류: 읽기 시도로 센다
        ("tool", "t4", "Read", {"file_path": "/x/events.json"}, "[telephony-triage] 규칙 10", True),
    ])
    ctx = grader.Ctx(env_dir, run)
    assert ctx.raw_full_reads() == ["unzip -p logs/a.zip", "cat logs/e.log"]
    assert ctx.raw_reads_blocked() == ["cat logs/e.log", "Read /x/events.json"]


def test_child_env_strips_parent_session_identity_but_keeps_auth_and_proxy():
    env = {"CLAUDE_CODE_SESSION_ID": "s", "CLAUDE_CODE_REMOTE_SESSION_ID": "r", "CLAUDE_CODE_REMOTE": "true",
           "CLAUDE_CODE_CONTAINER_ID": "c", "TRACEPARENT": "t", "CLAUDE_CODE_MESSAGING_TOKEN": "m",
           "HTTPS_PROXY": "p", "ANTHROPIC_BASE_URL": "u", "GH_TOKEN": "g", "PATH": "/bin", "CLAUDE_CODE_VERSION": "1"}
    kept, stripped = evaluation.child_env(env)
    assert set(kept) == {"HTTPS_PROXY", "ANTHROPIC_BASE_URL", "GH_TOKEN", "PATH", "CLAUDE_CODE_VERSION"}
    assert "CLAUDE_CODE_REMOTE_SESSION_ID" in stripped and "CLAUDE_CODE_SESSION_ID" in stripped
    assert evaluation.NO_ATTRIBUTION_SETTINGS and json.loads(evaluation.NO_ATTRIBUTION_SETTINGS)["attribution"] == {"commit": "", "pr": ""}


def test_rules_use_absolute_result_paths_and_commit_message_line(tmp_path):
    rules = evaluation._rules({"user_replies": ["예"]}, tmp_path / "run")
    out = (tmp_path / "run" / "outputs").as_posix()
    assert f"{out}/transcript.md" in rules and f"{out}/commands.md" in rules and f"{out}/notes.md" in rules
    assert "커밋 메시지는 확인 화면 commit_message 그대로(trailer·서명 줄 없음)" in rules


def test_missing_result_files_are_derived_from_events(tmp_path):
    run = run_dir(tmp_path)
    (run / "outputs" / "notes.md").write_text("실행자 노트", encoding="utf-8")
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "안녕하세요"},
                                                      {"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "ls | wc -l"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "content": "x", "is_error": True}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": "pwd"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "b", "content": "/", "is_error": False}]}},
    ]
    made = evaluation.derive_outputs(run, events)
    assert made == ["transcript.md", "commands.md"]
    assert (run / "outputs" / "notes.md").read_text(encoding="utf-8") == "실행자 노트"
    transcript = (run / "outputs" / "transcript.md").read_text(encoding="utf-8")
    commands = (run / "outputs" / "commands.md").read_text(encoding="utf-8")
    assert transcript.startswith(evaluation.DERIVED_HEADER) and "안녕하세요" in transcript
    assert commands.startswith(evaluation.DERIVED_HEADER)
    assert "| 1 | ls \\| wc -l | error |" in commands and "| 2 | pwd | ok |" in commands


def _explore_events(run, *, ask=True, read_before=False, explore=True):
    items = []
    if read_before:
        items.append(("tool", "r0", "Read", {"file_path": "/w/MOCK-9046/timeline.md"}, "x", False))
    if ask:
        items.append(("text", "탐색 분석을 실행할까요?"))
    if explore:
        items.append(("tool", "e1", "Bash", {"command": "python3 triage.py explore MOCK-9046"}, "ok", False))
    items.append(("tool", "r1", "Read", {"file_path": "/w/MOCK-9046/timeline.md"}, "x", False))
    _seq_events(run, items)


@pytest.mark.parametrize("kwargs,item1,scope_ok", [
    ({}, True, True),
    ({"ask": False}, False, True),
    ({"explore": False}, False, False),
    ({"read_before": True}, True, False),
])
def test_e46_e47_ask_before_explore_and_read_timeline_after(tmp_path, kwargs, item1, scope_ok):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _explore_events(run, **kwargs)
    ctx = grader.Ctx(env_dir, run)
    fns = grader.checks(46, ctx)
    assert fns[0]()[0] is item1, fns[0]()
    assert fns[1]()[0] is scope_ok, fns[1]()
    assert grader.checks(47, ctx)[1]()[0] is scope_ok
