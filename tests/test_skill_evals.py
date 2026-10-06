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
                                                  "gh_state": str(tmp_path / "gh"),
                                                  "env": {"MOCK_JIRA_WRITE_LOG": str(tmp_path / "jira-writes.log")}}), encoding="utf-8")
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


def test_raw_metric_mirrors_guard_dumps_and_new_targets(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _bash_events(run, 'grep -n "" logs/e.log', "grep '.*' logs/e.log", "awk '{print}' logs/e.log", "sed -n p logs/e.log",
                 "grep -n RILJ logs/e.log", "sed -n 1,200p logs/e.log", "grep -c '' logs/e.log",   # 통과 형태
                 "cat fixtures/cut-1.log", "cat ./fixtures/cut-1.log", "cat JOB/fixtures/cut-1.log",   # 상대 fixture: 원문 아님
                 "cat JOB/draft/x.log", "cat JOB/match.json", "less JOB/events-full.json",
                 "cat <<'EOF'\ncat logs/e.log\nEOF")
    reads = grader.Ctx(env_dir, run).raw_full_reads()
    assert [r.split()[0] for r in reads] == ["grep", "grep", "awk", "sed", "cat", "less"], reads
    assert any("match.json" in r for r in reads) and any("events-full.json" in r for r in reads)
    assert not any("fixtures" in r or "draft" in r for r in reads)


@pytest.mark.parametrize("command,text", [
    ('python3 "/p/triage.py" explore MOCK-9046', "탐색 분석(explore)을 실행할지 묻는 단계입니다"),   # 따옴표 경로 + 할지
    ("python3 triage.py explore MOCK-9046", "탐색 분석을 진행할지 묻겠습니다"),
])
def test_explore_order_handles_quoted_paths_and_haji_questions(tmp_path, command, text):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _seq_events(run, [("text", text), ("tool", "e1", "Bash", {"command": command}, "ok", False),
                      ("tool", "r1", "Read", {"file_path": "/w/MOCK-9046/timeline.md"}, "x", False)])
    explored, asked, read = grader.Ctx(env_dir, run).explore_order()
    assert (asked, explored, read) == (0, 1, 2)


def test_explore_order_ignores_explore_text_inside_heredocs(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _seq_events(run, [("tool", "h1", "Bash", {"command": "cat > transcript.md <<'EOF'\npython3 triage.py explore X\nEOF"}, "", False),
                      ("text", "탐색 분석을 실행할까요?"),
                      ("tool", "e1", "Bash", {"command": "python3 triage.py explore X"}, "ok", False)])
    explored, asked, _ = grader.Ctx(env_dir, run).explore_order()
    assert (asked, explored) == (1, 2)


# --- W0: 토큰 기록·상한 판정 (claude 호출 없음) -------------------------------------------------

def _mu(i, o, cc, cr, cost):
    return {"inputTokens": i, "outputTokens": o, "cacheCreationInputTokens": cc, "cacheReadInputTokens": cr, "costUSD": cost}


def _result(**extra):
    return {"type": "result", "num_turns": 7, "duration_ms": 1234, "total_cost_usd": 0.5,
            "usage": {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40},
            "modelUsage": {"m-a": _mu(10, 20, 30, 40, 0.3), "m-b": _mu(1, 2, 3, 4, 0.2)}, **extra}


def test_token_record_sums_model_usage_and_keeps_usage_total_separate():
    t = grader.token_record(_result())
    assert (t["input"], t["output"], t["cache_creation"], t["cache_read"]) == (11, 22, 33, 44)
    assert t["total"] == 110 and t["usage_total"] == 100          # 보조 모델 몫이 total에만 들어간다
    assert t["by_model"]["m-b"] == {"input": 1, "output": 2, "cache_creation": 3, "cache_read": 4, "total": 10, "cost_usd": 0.2}
    assert (t["num_turns"], t["duration_ms"], t["total_cost_usd"], t["source"]) == (7, 1234, 0.5, "modelUsage")


def test_token_record_uses_null_not_zero_for_missing_values():
    r = _result()
    del r["modelUsage"]["m-b"]["outputTokens"]
    r["modelUsage"]["m-a"]["costUSD"] = True                        # bool은 정수·숫자가 아니다
    t = grader.token_record(r)
    assert t["by_model"]["m-b"]["output"] is None and t["by_model"]["m-b"]["total"] is None
    assert t["by_model"]["m-a"]["total"] == 100 and t["by_model"]["m-a"]["cost_usd"] is None
    assert t["output"] is None and t["total"] is None and t["input"] == 11 and t["usage_total"] == 100
    none = grader.token_record(None)
    assert none["total"] is None and none["usage_total"] is None and none["source"] is None and none["by_model"] == {}
    old = grader.token_record({"status": "completed", "usage": _result()["usage"], "total_cost_usd": 0.4})    # 옛 execution.json
    assert old["total"] is None and old["source"] is None and old["usage_total"] == 100 and old["total_cost_usd"] == 0.4
    assert old["num_turns"] is None


def _graded_run(tmp_path, execution, *, artifacts=True):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    if artifacts:
        _write_artifacts(run)
    if execution is not None:
        (run / "execution.json").write_text(json.dumps(execution), encoding="utf-8")
    return env_dir, run


def _budget(total, margin=1.5, eid="24"):
    return {"baseline": {"evals": {eid: {"total": total}}}, "margin": margin}


@pytest.mark.parametrize("total,baseline,passed,failed,row_passed", [
    (150, 100, 1, 0, True),           # 상한 = 100 × 1.5 = 150: 이내
    (151, 100, 0, 1, False),          # 초과
    (None, 100, 0, 0, None),          # 미기록: 판정 보류
    (999, None, 0, 0, "absent"),      # 기준선에 eval 없음: 항목을 만들지 않는다
])
def test_token_budget_row_in_grading(tmp_path, total, baseline, passed, failed, row_passed):
    tokens = grader.token_record(_result(modelUsage={"m": _mu(total, 0, 0, 0, 0.1)}) if total is not None else None)
    env_dir, run = _graded_run(tmp_path, {"status": "completed", "tokens": tokens})
    base = grader.grade(24, run, env_dir, ["lock 해제"])
    budget = _budget(baseline) if baseline else {"baseline": {"evals": {"1": {"total": 5}}}, "margin": 1.5}
    result = grader.grade(24, run, env_dir, ["lock 해제"], budget)
    rows = [r for r in result["expectations"] if r["text"] == grader.TOKEN_BUDGET_TEXT]
    assert result["tokens"] == tokens and base["tokens"] == tokens          # 예산 없이도 tokens 키는 있다
    if row_passed == "absent":
        assert not rows and result["summary"] == base["summary"]
        return
    assert [r["passed"] for r in rows] == [row_passed] and rows[0]["source"] == "script"
    assert result["summary"]["failed"] == base["summary"]["failed"] + failed
    assert len(result["expectations"]) == len(base["expectations"]) + 1
    assert "미기록" in rows[0]["evidence"] if total is None else "상한=150" in rows[0]["evidence"]


def test_token_budget_row_for_interrupted_and_not_run(tmp_path):
    tokens = grader.token_record(None)                           # 시간 초과: 전부 null
    env_dir, run = _graded_run(tmp_path, {"status": "timeout", "reason": "제한", "tokens": tokens}, artifacts=False)
    result = grader.grade(24, run, env_dir, ["lock 해제"], _budget(100))
    assert result["status"] == "incomplete" and result["tokens"] == tokens
    assert result["expectations"][-1]["text"] == grader.TOKEN_BUDGET_TEXT and result["expectations"][-1]["passed"] is None
    env_dir2, run2 = _graded_run(tmp_path / "b", {"status": "prepared"}, artifacts=False)
    not_run = grader.grade(24, run2, env_dir2, ["lock 해제"], _budget(100))
    assert not_run["status"] == "not-run" and not_run["tokens"] is None
    assert all(r["text"] != grader.TOKEN_BUDGET_TEXT for r in not_run["expectations"])


def _iteration(tmp_path, name, execution, eid=1):
    """grade.py main이 찾는 최소 iteration 디렉토리(합성 환경)."""
    it = tmp_path / name
    it.mkdir()
    (it / f"env-{eid}").mkdir()
    _synthetic_env(it / "_s")
    env = it / f"env-{eid}"
    for f in ("env.json", "before.json"):
        (env / f).write_text((it / "_s" / "env" / f).read_text(encoding="utf-8"), encoding="utf-8")
    (env / "logs").mkdir()
    run = it / f"eval-{eid}" / "with_skill"
    (run / "outputs").mkdir(parents=True)
    if execution is not None:
        (run / "execution.json").write_text(json.dumps(execution), encoding="utf-8")
    return it


def _main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["grade.py", *map(str, argv)])
    code = grader.main()
    return code, capsys.readouterr()


def test_main_exit_codes_and_token_table(tmp_path, monkeypatch, capsys):
    tokens = grader.token_record(_result())                      # total 110
    ran = _iteration(tmp_path, "ran", {"status": "error", "reason": "x", "tokens": tokens})
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"margin_default": 1.0, "evals": {"1": {"total": 100}}}), encoding="utf-8")
    code, out = _main(monkeypatch, capsys, ran, "--eval", 1)
    assert code == 0 and "미기록" not in out.out and "110" in out.out and "기준선 없음" not in out.out    # 예산 없음: 상한 열 "-"
    assert (ran / "tokens.json").is_file()
    code, out = _main(monkeypatch, capsys, ran, "--eval", 1, "--token-budget", base)           # margin_default 1.0 → 상한 100 < 110
    assert code == 1 and "초과" in out.out
    code, out = _main(monkeypatch, capsys, ran, "--eval", 1, "--token-budget", base, "--token-margin", "1.2")
    assert code == 0 and "통과" in out.out and "120" in out.out
    code, _ = _main(monkeypatch, capsys, ran, "--eval", 1, "--token-budget", tmp_path / "none.json")
    assert code == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert _main(monkeypatch, capsys, ran, "--token-budget", bad)[0] == 2
    # 미기록(시간 초과)은 판정 대상이면 1, 실행하지 않은(prepared) eval은 "미실행"이고 종료 코드에 영향 없다
    timeout = _iteration(tmp_path, "timeout", {"status": "timeout", "reason": "t", "tokens": grader.token_record(None)})
    code, out = _main(monkeypatch, capsys, timeout, "--eval", 1, "--token-budget", base)
    assert code == 1 and "미기록" in out.out
    prepared = _iteration(tmp_path, "prepared", {"status": "prepared"})
    code, out = _main(monkeypatch, capsys, prepared, "--eval", 1, "--token-budget", base)
    assert code == 0 and "미실행" in out.out


def test_write_baseline_takes_max_run_and_records_model_and_commit(tmp_path, monkeypatch, capsys):
    its = []
    for i, extra in enumerate((0, 50, 20)):
        r = _result(modelUsage={"m-a": _mu(100 + extra, 0, 0, 0, 0.1)}, num_turns=5 + i, total_cost_usd=1.0 + i)
        its.append(_iteration(tmp_path, f"it{i}", {"status": "error", "reason": "x", "model": "m-a", "tokens": grader.token_record(r)}))
    out_path = tmp_path / "token_baseline.json"
    code, _ = _main(monkeypatch, capsys, *its, "--eval", 1, "--write-baseline", out_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert code == 0 and data["model"] == "m-a" and set(data) >= {"commit", "dirty", "date", "margin_default", "margin_basis"}
    assert data["evals"]["1"]["total"] == 150 and data["evals"]["1"]["num_turns"] == 6       # 최댓값 run의 기록
    assert [r["total"] for r in data["evals"]["1"]["runs"]] == [100, 150, 120]
    assert grader.load_baseline(out_path)["evals"]["1"]["total"] == 150
    # 모델이 섞이면 쓰지 않는다
    mixed = _iteration(tmp_path, "mixed", {"status": "error", "reason": "x", "model": "m-z", "tokens": grader.token_record(_result())})
    assert _main(monkeypatch, capsys, its[0], mixed, "--eval", 1, "--write-baseline", tmp_path / "x.json")[0] == 2
    # 기존 파일과 모델이 다르면 덮어쓰지 않는다(메시지에 두 모델)
    before = out_path.read_text(encoding="utf-8")
    code, out = _main(monkeypatch, capsys, mixed, "--eval", 1, "--write-baseline", out_path)
    assert code == 2 and "m-a" in out.err and "m-z" in out.err and out_path.read_text(encoding="utf-8") == before
    # 기존 파일이 깨졌으면 2
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert _main(monkeypatch, capsys, its[0], "--eval", 1, "--write-baseline", broken)[0] == 2


def _tok(total):
    return grader.token_record(_result(modelUsage={"m-a": _mu(total, 0, 0, 0, 0.1)}) if total is not None else None)


def test_write_baseline_skips_null_runs_and_refuses_empty(tmp_path, monkeypatch, capsys):
    path = tmp_path / "b.json"
    mixed = [_iteration(tmp_path, "ok", {"status": "completed", "model": "m-a", "tokens": _tok(100)}),
             _iteration(tmp_path, "null", {"status": "timeout", "reason": "t", "model": "m-a", "tokens": _tok(None)})]
    code, out = _main(monkeypatch, capsys, *mixed, "--eval", 1, "--write-baseline", path)
    assert code == 0 and "1개 제외" in out.err and [r["total"] for r in json.loads(path.read_text())["evals"]["1"]["runs"]] == [100]
    none = tmp_path / "none.json"
    code, out = _main(monkeypatch, capsys, mixed[1], "--eval", 1, "--write-baseline", none)
    assert code == 2 and not none.exists() and "빠진 run 수" in out.err
    with pytest.raises(ValueError):
        grader.write_baseline(tmp_path / "w.json", {1: [_tok(None)]}, "m-a", "c", False)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"evals": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        grader.load_baseline(empty)


def test_baseline_model_comes_from_model_then_init_model_never_by_model(tmp_path, monkeypatch, capsys):
    only_init = _iteration(tmp_path, "init", {"status": "completed", "model": None, "init_model": "m-init", "tokens": _tok(100)})
    path = tmp_path / "b.json"
    assert _main(monkeypatch, capsys, only_init, "--eval", 1, "--write-baseline", path)[0] == 0
    assert json.loads(path.read_text())["model"] == "m-init"
    both = _iteration(tmp_path, "both", {"status": "completed", "model": "m-flag", "init_model": "m-init", "tokens": _tok(100)})
    path2 = tmp_path / "b2.json"
    assert _main(monkeypatch, capsys, both, "--eval", 1, "--write-baseline", path2)[0] == 0
    assert json.loads(path2.read_text())["model"] == "m-flag"
    nomodel = _iteration(tmp_path, "nomodel", {"status": "completed", "model": None, "tokens": _tok(100)})   # by_model에 m-a가 있어도 추정하지 않는다
    path3 = tmp_path / "b3.json"
    assert _main(monkeypatch, capsys, nomodel, "--eval", 1, "--write-baseline", path3)[0] == 2 and not path3.exists()


def test_init_model_reads_system_init_event():
    assert evaluation.init_model([{"type": "system", "subtype": "init", "model": "claude-x"}]) == "claude-x"
    assert evaluation.init_model([{"type": "system", "subtype": "init"}]) is None
    assert evaluation.init_model([]) is None


def test_token_record_real_shape_with_extra_keys_and_nested_usage():
    r = _result()
    r["usage"] = {**r["usage"], "server_tool_use": {"web_search_requests": 0}, "cache_creation": {"ephemeral_5m_input_tokens": 30},
                  "service_tier": "standard"}
    for m in r["modelUsage"].values():
        m.update(webSearchRequests=0, contextWindow=200000, maxOutputTokens=32000)
    t = grader.token_record(r)
    assert t["total"] == 110 and t["usage_total"] == 100 and set(t["by_model"]) == {"m-a", "m-b"}
    assert set(t["by_model"]["m-a"]) == {"input", "output", "cache_creation", "cache_read", "total", "cost_usd"}


def test_grade_without_budget_matches_head_behavior(tmp_path, monkeypatch, capsys):
    env_dir, run = _graded_run(tmp_path, None)
    result = grader.grade(24, run, env_dir, ["lock 해제", "기록 없음", "수동"])
    assert [(e["text"], e["passed"], e["evidence"], e["source"]) for e in result["expectations"]] == [
        ("lock 해제", None, "transcript 수동 채점 필요", "manual"), ("기록 없음", None, "transcript 수동 채점 필요", "manual"),
        ("수동", None, "transcript 수동 채점 필요", "manual"), ("Jira 쓰기 도구를 부르지 않았다", True, "쓰기 도구 호출 없음", "script")]
    assert result["summary"] == {"passed": 1, "failed": 0, "total": 4, "undecided": 3, "pass_rate": 0.25}
    assert result["status"] == "graded" and result["tokens"] is None and "tokens" in json.loads((run / "grading.json").read_text())
    (run / "execution.json").write_text(json.dumps({"status": "timeout", "reason": "제한"}), encoding="utf-8")
    cut = grader.grade(24, run, env_dir, ["a"])
    assert cut["summary"] == {"passed": 0, "failed": 0, "total": 2, "undecided": 2, "pass_rate": 0}
    assert [(e["passed"], e["evidence"], e["source"]) for e in cut["expectations"]] == [(None, "제한", "execution")] * 2
    ran = _iteration(tmp_path, "ran", {"status": "error", "reason": "x", "tokens": grader.token_record(_result())})
    assert _main(monkeypatch, capsys, ran, "--eval", 1)[0] == 0


def test_interrupted_summary_reflects_decided_budget_row(tmp_path):
    for total, passed, failed in ((100, 1, 0), (999, 0, 1)):
        env_dir, run = _graded_run(tmp_path / str(total), {"status": "error", "reason": "x", "tokens": _tok(total)}, artifacts=False)
        s = grader.grade(24, run, env_dir, ["a"], _budget(100))["summary"]
        assert (s["passed"], s["failed"], s["total"], s["undecided"]) == (passed, failed, 3, 2)


def test_read_events_takes_last_result_and_skips_garbage(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text('{"type":"system"}\nnot json\n{"type":"result","num_turns":1}\n{"type":"result","num_turns":2}\n', encoding="utf-8")
    events, result = evaluation.read_events(p)
    assert len(events) == 3 and result["num_turns"] == 2


@pytest.mark.skipif(sys.platform == "win32", reason="가짜 claude는 shebang 실행 파일")
def test_execute_records_tokens_from_stream_json_result(tmp_path, monkeypatch):
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(f"#!{sys.executable}\nimport sys\nsys.stdin.read()\n"
                    f"print({json.dumps(_result(result='ok', is_error=False, subtype='success'))!r})\n", encoding="utf-8")
    fake.chmod(0o755)
    env_dir, run = tmp_path / "env", run_dir(tmp_path)
    env_dir.mkdir()
    info = {"env": {}, "skill": str(tmp_path / "skill"), "path_prefix": [], "plugin_root": str(tmp_path / "root"), "issue_db_clone": str(tmp_path / "a" / "b" / "clone")}
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    outcome = evaluation.execute({"prompt": "p", "user_replies": []}, info, env_dir, run, str(fake), 30, None, "m-a")
    saved = json.loads((run / "execution.json").read_text(encoding="utf-8"))
    assert outcome["status"] == "completed", outcome["reason"]
    assert saved["model"] == "m-a"
    assert saved["tokens"]["total"] == 110 and saved["tokens"]["usage_total"] == 100 and saved["usage"]["input_tokens"] == 10
    assert saved["total_cost_usd"] == 0.5
