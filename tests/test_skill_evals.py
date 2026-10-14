"""실행되지 않은 평가를 통과로 세지 않고 API 중단을 보존한다."""
from __future__ import annotations

import importlib.util
import json
import subprocess
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
        for key in setup.get("gh_issues") or []:
            assert skill_eval_env._find_gh_issue(key).is_file(), (e["id"], key)
        assert setup.get("tracker", "jira") in ("jira", "github"), e["id"]
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


@pytest.mark.parametrize("resolution, ok", [("캐리어 APN을 직접 입력한다", True), ("캐리어 APN을 직접 입력한다.", True),
                                             ("캐리어 APN을 직접 입력한다. ", True), ("캐리어 APN 목록을 초기화한다", False)])
def test_e38_revised_resolution_ignores_trailing_period_and_space(tmp_path, resolution, ok):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    plan = {"operations": [{"op": "new-cause", "cause": {"resolution": "캐리어 APN 목록을 초기화한다"}},
                           {"op": "set-resolution", "resolution": resolution}]}
    (run / "outputs" / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert grader.checks(38, grader.Ctx(env_dir, run))[3]()[0] is ok


def test_raw_full_reads_metric(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    (run / "outputs" / "transcript.md").write_text("t", encoding="utf-8")
    (run / "outputs" / "commands.md").write_text("c", encoding="utf-8")
    _bash_events(run, "cat logs/e.log", "head -c 100000 logs/e.log", "head -n 20 logs/e.log", "grep X logs/e.log",
                 "unzip -p logs/a.zip", "cat notes.txt", "less issue_raw.json", "strings logs/e.log | head",
                 extra=[("Read", {"file_path": "/x/logs/e.log"}),
                        ("Read", {"file_path": "/x/logs/e.log", "limit": 50}),
                        ("Read", {"file_path": "/x/events.json"}),
                        ("Read", {"file_path": "/x/other.md"})])
    reads = grader.Ctx(env_dir, run).raw_full_reads()
    assert len(reads) == 7, reads
    assert not any("head -n" in r or "grep" in r or "notes.txt" in r or "limit" in r for r in reads)
    assert "Read /x/events.json" in reads


def test_step8_bash_metric_counts_subcommands_not_options(tmp_path):
    """W5: `--then-summary`·`--and-discard`는 summary·discard 호출로 세지 않고, eval 1은 직접 git commit을 거른다."""
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    for name in ("transcript.md", "commands.md"):
        (run / "outputs" / name).write_text("c", encoding="utf-8")
    _bash_events(run, "python3 S/db_pr.py stage plan.json --wt w --branch b --then-summary",
                 "python3 S/db_pr.py publish w --branch b --lease new --approved h --commit --and-discard")
    ctx = grader.Ctx(env_dir, run)
    assert ctx.step8_bash() == {"stage": 1, "summary": 0, "publish": 1, "discard": 0, "git_add": 0, "git_commit": 0, "total": 2}
    _bash_events(run, "python3 S/db_pr.py stage plan.json --wt w --branch b", "python3 S/db_pr.py summary w",
                 "git -C w add -A", "git -C w commit -F m.txt", "python3 S/db_pr.py publish w --branch b --lease new --approved h",
                 "python3 S/db_pr.py discard w")
    assert grader.Ctx(env_dir, run).step8_bash() == {"stage": 1, "summary": 1, "publish": 1, "discard": 1, "git_add": 1,
                                                     "git_commit": 1, "total": 6}


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


E25_REFUSAL = "CALL-001-01는 코드·설정 수정 유형(carrier-config)인데 ... 판정 전에 중단합니다(판단 불가). 다음: update-signature로 ..."
E25_CMD = "python3 $CLAUDE_PLUGIN_ROOT/scripts/db_verify.py fix --cause CALL-001-01 logs/call-fixed.log --build B1 --json"


def _e25(tmp_path, items, transcript="update-signature로 시그니처를 추가해야 합니다"):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    (run / "outputs" / "transcript.md").write_text(transcript, encoding="utf-8")
    (run / "outputs" / "commands.md").write_text("c", encoding="utf-8")
    _seq_events(run, items)
    return grader.checks(25, grader.Ctx(env_dir, run))[1]


@pytest.mark.parametrize("name,items,transcript,expected", [
    # 05-verification.md §5.12 (2): 판정이 나오지 않았다 = 부르지 않았거나, 종료 코드 2로 거부되고 안내를 보였다
    ("부르지 않음", [("tool", "t1", "Bash", {"command": "python3 db_search.py CALL-001-01"}, "{}", False)], None, True),
    ("exit 2 거부 + 안내", [("tool", "t1", "Bash", {"command": E25_CMD}, "Exit code 2\n" + E25_REFUSAL, True)], None, True),
    ("판정 출력", [("tool", "t1", "Bash", {"command": E25_CMD}, '{"judgement": "passed"}', False)], None, False),
    ("exit 2 거부, 안내 없음", [("tool", "t1", "Bash", {"command": E25_CMD}, "Exit code 2\n" + E25_REFUSAL, True)],
     "판정을 못 했습니다", False),
    ("부르지 않음, 안내 불필요", [], None, True),
])
def test_e25_assertion_2_branches(tmp_path, name, items, transcript, expected):
    check = _e25(tmp_path, items, **({} if transcript is None else {"transcript": transcript}))
    assert check()[0] is expected, name


def test_e25_assertion_2_is_undecided_when_result_cannot_be_read(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    (run / "outputs" / "transcript.md").write_text("update-signature", encoding="utf-8")
    (run / "outputs" / "commands.md").write_text("c", encoding="utf-8")
    _seq_events(run, [("tool", "t1", "Bash", {"command": E25_CMD}, None, False)])
    row = grader.grade(25, run, env_dir, ["a", "b"])["expectations"][1]
    assert row["passed"] is None and row["source"] == "manual"
    assert "종료 코드 2로 거부" in next(e for e in _entries() if e["id"] == 25)["assertions"][1]


def test_e25_assertion_2_line_continuation_and_file_bypass_and_error_flag(tmp_path):
    cont = E25_CMD.replace(" fix ", " \\\n  fix ")
    assert _e25(tmp_path / "a", [("tool", "t1", "Bash", {"command": cont}, '{"judgement": "passed"}', False)])()[0] is False
    bypass = [("tool", "t1", "Bash", {"command": E25_CMD + " > /tmp/x.json"}, "", False),
              ("tool", "t2", "Bash", {"command": "cat /tmp/x.json"}, '{"judgement": "passed"}', False)]
    ok, ev = _e25(tmp_path / "b", bypass)()
    assert ok is False and "called=1" in ev
    flagged = [("tool", "t1", "Bash", {"command": E25_CMD}, "Exit code 2\nCALL-001-01: 다른 이유", False)]
    with pytest.raises(grader._Manual):                  # 거부 문구도 is_error도 없으면 거부로 보지 않는다
        _e25(tmp_path / "c", flagged)()
    twice = [("tool", "t1", "Bash", {"command": E25_CMD}, E25_REFUSAL, True),
             ("tool", "t2", "Bash", {"command": E25_CMD}, E25_REFUSAL, True)]
    ok, ev = _e25(tmp_path / "d", twice)()
    assert ok is True and "called=2" in ev and "재호출=True" in ev


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


def test_child_settings_passes_only_auth_keys_from_user_settings(tmp_path):
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "settings.json").write_text(json.dumps({
        "apiKeyHelper": "/opt/helper.sh", "hooks": {"PreToolUse": []}, "enabledPlugins": {"x": True},
        "permissions": {"allow": ["Bash"]},
        "env": {"ANTHROPIC_BASE_URL": "https://gw.example", "HTTPS_PROXY": "http://proxy.example", "FOO": "bar"}}), encoding="utf-8")
    settings, auth_env, keys = evaluation.child_settings({"CLAUDE_CONFIG_DIR": str(conf)})
    data = json.loads(settings)
    assert data["apiKeyHelper"] == "/opt/helper.sh" and data["attribution"] == {"commit": "", "pr": ""}
    assert not {"hooks", "enabledPlugins", "permissions", "env"} & set(data)     # 격리 유지: 인증 밖은 넘기지 않음
    assert auth_env == {"ANTHROPIC_BASE_URL": "https://gw.example", "HTTPS_PROXY": "http://proxy.example"}
    assert keys == ["apiKeyHelper", "env.ANTHROPIC_BASE_URL", "env.HTTPS_PROXY"]   # 기록에는 이름만


def test_child_common_args_pin_permission_mode_and_isolation():
    args = evaluation.child_common_args("{}")
    assert args[args.index("--permission-mode") + 1] == "default"     # CLI 기본값(사내 auto)에 기대지 않는다
    assert args[args.index("--setting-sources") + 1] == "" and "--strict-mcp-config" in args


def test_child_settings_without_user_settings_is_attribution_only(tmp_path):
    for content in (None, "{broken", "[]"):
        conf = tmp_path / f"c{content!r}"
        conf.mkdir()
        if content is not None:
            (conf / "settings.json").write_text(content, encoding="utf-8")
        settings, auth_env, keys = evaluation.child_settings({"CLAUDE_CONFIG_DIR": str(conf)})
        assert json.loads(settings) == json.loads(evaluation.NO_ATTRIBUTION_SETTINGS) and auth_env == {} and keys == []


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


@pytest.mark.parametrize("question,asked", [("탐색 분석을 실행할까요? (토큰 추가 사용)", True), ("코드 경로를 고를까요?", False)])
def test_explore_order_counts_ask_user_tool_question(tmp_path, question, asked):
    """plugin 모드 실행자는 질문을 모의 ask_user 도구로 한다 — 그 question도 질문으로 센다(글이 없어도)."""
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _seq_events(run, [("tool", "q1", "mcp__eval-approver__ask_user", {"question": question, "options": ["예", "아니오"]}, "답", False),
                      ("tool", "e1", "Bash", {"command": "python3 triage.py explore MOCK-9046"}, "ok", False)])
    explored, got, _ = grader.Ctx(env_dir, run).explore_order()
    assert explored == 1 and (got == 0) is asked


def test_plugin_rules_route_questions_through_ask_tool(tmp_path):
    entry = {"user_replies": ["묻으면 '예'"]}
    plugin = evaluation._rules(entry, tmp_path / "run", ask_tool=True)
    assert evaluation.ASK_TOOL in plugin and "건너뛰지 않는다" in plugin
    assert evaluation.ASK_TOOL not in evaluation._rules(entry, tmp_path / "run")      # direct 모드는 글로 묻는다


def test_approver_ask_user_returns_replies_and_logs(tmp_path, monkeypatch):
    spec_a = importlib.util.spec_from_file_location("eval_approver", REPO / "tests" / "mocks" / "approver_mcp" / "server.py")
    approver = importlib.util.module_from_spec(spec_a)     # `import server`는 다른 테스트의 모의 server와 sys.modules에서 겹친다
    spec_a.loader.exec_module(approver)
    log = tmp_path / "approvals.json"
    monkeypatch.setenv("MOCK_APPROVALS_LOG", str(log))
    monkeypatch.setenv("EVAL_USER_REPLIES", json.dumps(["탐색 분석 실행 여부를 물으면 '예'."], ensure_ascii=False))
    out = approver.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "ask_user", "arguments": {"question": "탐색 분석을 실행할까요?", "options": ["예", "아니오"]}}})
    text = out["result"]["content"][0]["text"]
    assert "[시뮬레이션 사용자]" in text and "물으면 '예'" in text
    assert json.loads(log.read_text(encoding="utf-8")) == [{"kind": "ask", "question": "탐색 분석을 실행할까요?", "options": ["예", "아니오"]}]
    listed = approver.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in listed} == {"approve", "ask_user"}


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


def _budget(total, margin=1.5, eid="24", model="m-a"):
    return {"baseline": {"model": model, "evals": {eid: {"total": total}}}, "margin": margin}


@pytest.mark.parametrize("total,baseline,passed,failed,row_passed", [
    (150, 100, 1, 0, True),           # 상한 = 100 × 1.5 = 150: 이내
    (151, 100, 0, 1, False),          # 초과
    (None, 100, 0, 0, None),          # 미기록: 판정 보류
    (999, None, 0, 0, "absent"),      # 기준선에 eval 없음: 항목을 만들지 않는다
])
def test_token_budget_row_in_grading(tmp_path, total, baseline, passed, failed, row_passed):
    tokens = grader.token_record(_result(modelUsage={"m": _mu(total, 0, 0, 0, 0.1)}) if total is not None else None)
    env_dir, run = _graded_run(tmp_path, {"status": "completed", "model": "m-a", "tokens": tokens})
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
    env_dir, run = _graded_run(tmp_path, {"status": "timeout", "reason": "제한", "model": "m-a", "tokens": tokens}, artifacts=False)
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
    if (execution or {}).get("status") == "completed":
        _write_artifacts(run)
    return it


def _manual_checks(monkeypatch, *fns):
    """합성 iteration은 원격·clone이 없어 eval 1 스크립트 판정이 실패한다. 기준선 후보 판정만 보려고 검사를 바꾼다."""
    monkeypatch.setattr(grader, "checks", lambda eid, ctx: list(fns))


_RUN = {"status": "completed", "model": "m-a", "repo_commit": "c1", "repo_dirty": False}


def _main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["grade.py", *map(str, argv)])
    code = grader.main()
    return code, capsys.readouterr()


def test_main_exit_codes_and_token_table(tmp_path, monkeypatch, capsys):
    tokens = grader.token_record(_result())                      # total 110
    ran = _iteration(tmp_path, "ran", {"status": "error", "reason": "x", "model": "m-a", "tokens": tokens})
    base = tmp_path / "base.json"
    base.write_text(json.dumps({"model": "m-a", "margin_default": 1.0, "evals": {"1": {"total": 100}}}), encoding="utf-8")
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
    nomodel = tmp_path / "nomodel.json"                                  # 기준선 model 없음 = 형식 오류
    nomodel.write_text(json.dumps({"evals": {"1": {"total": 100}}}), encoding="utf-8")
    code, out = _main(monkeypatch, capsys, ran, "--eval", 1, "--token-budget", nomodel)
    assert code == 2 and "model" in out.err
    # 미기록(시간 초과)은 판정 대상이면 1, 실행하지 않은(prepared) eval은 "미실행"이고 종료 코드에 영향 없다
    timeout = _iteration(tmp_path, "timeout", {"status": "timeout", "reason": "t", "tokens": grader.token_record(None)})
    code, out = _main(monkeypatch, capsys, timeout, "--eval", 1, "--token-budget", base)
    assert code == 1 and "미기록" in out.out
    prepared = _iteration(tmp_path, "prepared", {"status": "prepared"})
    code, out = _main(monkeypatch, capsys, prepared, "--eval", 1, "--token-budget", base)
    assert code == 0 and "미실행" in out.out


def test_write_baseline_takes_max_run_and_records_model_and_commit(tmp_path, monkeypatch, capsys):
    _manual_checks(monkeypatch)
    its = []
    for i, extra in enumerate((0, 50, 20)):
        r = _result(modelUsage={"m-a": _mu(100 + extra, 0, 0, 0, 0.1)}, num_turns=5 + i, total_cost_usd=1.0 + i)
        its.append(_iteration(tmp_path, f"it{i}", {**_RUN, "repo_dirty": i == 1, "tokens": grader.token_record(r)}))
    out_path = tmp_path / "token_baseline.json"
    code, _ = _main(monkeypatch, capsys, *its, "--eval", 1, "--write-baseline", out_path)
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert code == 0 and data["model"] == "m-a" and set(data) >= {"commit", "dirty", "date", "margin_default", "margin_basis"}
    assert (data["commit"], data["dirty"]) == ("c1", True)                                     # run 시점 커밋, dirty는 하나라도면
    assert (data["evals"]["1"]["commit"], data["evals"]["1"]["dirty"]) == ("c1", True)
    assert data["evals"]["1"]["total"] == 150 and data["evals"]["1"]["num_turns"] == 6       # 최댓값 run의 기록
    assert [r["total"] for r in data["evals"]["1"]["runs"]] == [100, 150, 120]
    assert grader.load_baseline(out_path)["evals"]["1"]["total"] == 150
    # 모델이 섞이면 쓰지 않는다
    mixed = _iteration(tmp_path, "mixed", {**_RUN, "model": "m-z", "tokens": grader.token_record(_result())})
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
    _manual_checks(monkeypatch)
    path = tmp_path / "b.json"
    mixed = [_iteration(tmp_path, "ok", {**_RUN, "tokens": _tok(100)}),
             _iteration(tmp_path, "null", {**_RUN, "tokens": _tok(None)})]                # 완료됐지만 modelUsage 없음
    code, out = _main(monkeypatch, capsys, *mixed, "--eval", 1, "--write-baseline", path)
    assert code == 0 and "1개 제외" in out.err and [r["total"] for r in json.loads(path.read_text())["evals"]["1"]["runs"]] == [100]
    none = tmp_path / "none.json"
    code, out = _main(monkeypatch, capsys, mixed[1], "--eval", 1, "--write-baseline", none)
    assert code == 2 and not none.exists() and "빠진 run 수" in out.err
    with pytest.raises(ValueError):
        grader.write_baseline(tmp_path / "w.json", {1: [{"tokens": _tok(None), "commit": "c", "dirty": False}]}, "m-a")
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"evals": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        grader.load_baseline(empty)


def test_baseline_model_comes_from_model_then_init_model_never_by_model(tmp_path, monkeypatch, capsys):
    _manual_checks(monkeypatch)
    only_init = _iteration(tmp_path, "init", {**_RUN, "model": None, "init_model": "m-init", "tokens": _tok(100)})
    path = tmp_path / "b.json"
    assert _main(monkeypatch, capsys, only_init, "--eval", 1, "--write-baseline", path)[0] == 0
    assert json.loads(path.read_text())["model"] == "m-init"
    both = _iteration(tmp_path, "both", {**_RUN, "model": "m-flag", "init_model": "m-init", "tokens": _tok(100)})
    path2 = tmp_path / "b2.json"
    assert _main(monkeypatch, capsys, both, "--eval", 1, "--write-baseline", path2)[0] == 0
    assert json.loads(path2.read_text())["model"] == "m-init"                                   # 실제로 돈 모델이 먼저
    nomodel = _iteration(tmp_path, "nomodel", {**_RUN, "model": None, "tokens": _tok(100)})   # by_model에 m-a가 있어도 추정하지 않는다
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
        env_dir, run = _graded_run(tmp_path / str(total), {"status": "error", "reason": "x", "model": "m-a", "tokens": _tok(total)},
                                   artifacts=False)
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
    head = subprocess.run(["git", "-C", str(evaluation.REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert saved["repo_commit"] == head and isinstance(saved["repo_dirty"], bool)            # run 시점 커밋


def _budget_main(monkeypatch, capsys, it, tmp_path, model="m-a"):
    base = tmp_path / f"base-{model}.json"
    base.write_text(json.dumps({**({"model": model} if model else {}), "margin_default": 1.5,
                                "evals": {"1": {"total": 100, "total_cost_usd": 0.09}}}), encoding="utf-8")
    code, out = _main(monkeypatch, capsys, it, "--eval", 1, "--token-budget", base)
    row = next(x for x in json.loads((it / "eval-1" / "with_skill" / "grading.json").read_text(encoding="utf-8"))["expectations"]
               if x["text"] == grader.TOKEN_BUDGET_TEXT)
    return code, out, row


def test_token_budget_holds_on_model_mismatch_or_missing(tmp_path, monkeypatch, capsys):
    other = _iteration(tmp_path, "other", {"status": "error", "reason": "x", "model": "m-z", "init_model": "m-z", "tokens": _tok(100)})
    code, out, row = _budget_main(monkeypatch, capsys, other, tmp_path)
    assert code == 1 and row["passed"] is None and row["hold"] is True and "m-z" in row["evidence"]
    assert "모델 불일치" in out.out and "통과" not in out.out
    # --model은 기준선과 같아도 실제로 돈 모델(init_model)이 다르면 보류
    flag = _iteration(tmp_path, "flag", {"status": "error", "reason": "x", "model": "m-a", "init_model": "m-z", "tokens": _tok(100)})
    code, out, row = _budget_main(monkeypatch, capsys, flag, tmp_path)
    assert code == 1 and row["hold"] is True and "모델 불일치" in out.out
    nomodel = _iteration(tmp_path, "nomodel", {"status": "error", "reason": "x", "tokens": _tok(100)})
    code, out, row = _budget_main(monkeypatch, capsys, nomodel, tmp_path)
    assert code == 1 and row["passed"] is None and row["hold"] is True and "모델 미기록" in out.out
    only_flag = _iteration(tmp_path, "only_flag", {"status": "error", "reason": "x", "model": "m-a", "tokens": _tok(100)})
    code, _, row = _budget_main(monkeypatch, capsys, only_flag, tmp_path)                      # init 없으면 --model 값
    assert code == 0 and row["passed"] is True and row["hold"] is False
    assert grader.token_budget_row(24, _tok(100), _budget(100), None)["hold"] is True
    assert grader.token_budget_row(24, _tok(100), _budget(100, model=None), "m-a")["hold"] is True


def test_token_budget_alias_model_passes_with_matching_init_model(tmp_path, monkeypatch, capsys):
    tokens = grader.token_record(_result(modelUsage={"m-a": _mu(10, 10, 20, 60, 0.1)}, total_cost_usd=0.1))
    alias = _iteration(tmp_path, "alias", {"status": "error", "reason": "x", "model": "sonnet", "init_model": "m-a", "tokens": tokens})
    code, out, row = _budget_main(monkeypatch, capsys, alias, tmp_path)
    assert code == 0 and row["passed"] is True and row["hold"] is False and "통과" in out.out
    assert row["evidence"] == "total=100 상한=150 (기준선 100 × 여유율 1.5) cost=$0.100 (기준선 $0.090) cache_read=60%"


def test_write_baseline_excludes_unfinished_and_failed_runs(tmp_path, monkeypatch, capsys):
    _manual_checks(monkeypatch, lambda: (False, "실패"))
    path = tmp_path / "b.json"
    its = [_iteration(tmp_path, "err", {**_RUN, "status": "error", "reason": "x", "tokens": _tok(100)}),
           _iteration(tmp_path, "to", {**_RUN, "status": "timeout", "reason": "t", "tokens": _tok(None)}),
           _iteration(tmp_path, "prep", {"status": "prepared"}),
           _iteration(tmp_path, "fail", {**_RUN, "tokens": _tok(100)})]
    code, out = _main(monkeypatch, capsys, *its, "--eval", 1, "--write-baseline", path)
    assert code == 2 and not path.exists()
    for reason in ("err eval 1 — 실행 상태 error", "to eval 1 — 실행 상태 timeout", "prep eval 1 — 실행 상태 prepared",
                   "fail eval 1 — 실패 항목 1개"):
        assert reason in out.err
    # 미결정 항목은 허용하고 run마다 수를 남긴다
    _manual_checks(monkeypatch, lambda: (True, "ok"))
    ok = _iteration(tmp_path, "ok", {**_RUN, "tokens": _tok(120)})
    code, out = _main(monkeypatch, capsys, ok, its[3], "--eval", 1, "--write-baseline", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    n = len(next(e for e in _entries() if e["id"] == 1)["assertions"])                       # 첫 항목만 스크립트, 나머지 수동
    assert code == 0 and [r["undecided"] for r in data["evals"]["1"]["runs"]] == [n - 1, n - 1]
    _manual_checks(monkeypatch)
    und = _iteration(tmp_path, "und", {**_RUN, "tokens": _tok(130)})
    _main(monkeypatch, capsys, und, "--eval", 1, "--write-baseline", path)
    assert json.loads(path.read_text(encoding="utf-8"))["evals"]["1"]["runs"][0]["undecided"] == n


def test_write_baseline_refuses_missing_or_mixed_run_commit(tmp_path, monkeypatch, capsys):
    _manual_checks(monkeypatch)
    a = _iteration(tmp_path, "a", {**_RUN, "tokens": _tok(100)})
    old = _iteration(tmp_path, "old", {"status": "completed", "model": "m-a", "tokens": _tok(100)})     # repo_commit 없는 옛 기록
    other = _iteration(tmp_path, "other", {**_RUN, "repo_commit": "c2", "tokens": _tok(100)})
    for its, msg in (((a, old), "run 시점 커밋 미기록"), ((a, other), "run 시점 커밋이 다르다")):
        path = tmp_path / f"{msg[-3:]}.json"
        code, out = _main(monkeypatch, capsys, *its, "--eval", 1, "--write-baseline", path)
        assert code == 2 and msg in out.err and not path.exists()


def test_write_baseline_stores_cache_breakdown_and_cost(tmp_path, monkeypatch, capsys):
    _manual_checks(monkeypatch)
    keys = ("total", "num_turns", "input", "output", "cache_creation", "cache_read", "total_cost_usd")
    lo = grader.token_record(_result(modelUsage={"m-a": _mu(10, 20, 30, 40, 0.3)}, total_cost_usd=0.3))
    hi = grader.token_record(_result(modelUsage={"m-a": _mu(1, 2, 3, 400, 0.2)}, total_cost_usd=0.2))
    its = [_iteration(tmp_path, n, {**_RUN, "tokens": t}) for n, t in (("lo", lo), ("hi", hi))]
    path = tmp_path / "b.json"
    assert _main(monkeypatch, capsys, *its, "--eval", 1, "--write-baseline", path)[0] == 0
    e = json.loads(path.read_text(encoding="utf-8"))["evals"]["1"]
    assert {k: e[k] for k in keys} == {k: hi[k] for k in keys}                                 # 대표값 = total 최대(비용은 더 낮다)
    assert [{k: r[k] for k in keys} for r in e["runs"]] == [{k: t[k] for k in keys} for t in (lo, hi)]


def test_w4_prep_evals_defined():
    by_id = {e["id"]: e for e in _entries()}
    assert by_id[14]["setup"]["user_config"]["code"] == {"auto_select": False}
    assert [len(by_id[i]["setup"]["user_config"]["code_profiles"]) for i in (55,)] == [1]
    assert by_id[56]["setup"]["leftovers"] == [{"job": "MOCK-8800"}]
    assert by_id[57]["setup"]["user_config"]["explore"] == {"when": "always", "timeline_max_lines": 200}   # user_config는 최상위 키 단위로 덮는다


def test_w4_eval_checks_cover_assertions_and_never_pass_unread(tmp_path):
    import grade as grader
    for eid, count in ((55, 6), (56, 5), (57, 5)):
        entry = next(e for e in _entries() if e["id"] == eid)
        assert len(entry["assertions"]) == count
    env = tmp_path / "env"
    run = tmp_path / "run"
    (env).mkdir(); run.mkdir()
    (env / "work").mkdir()
    (env / "env.json").write_text(json.dumps({"remote": str(env), "work_dir": str(env / "work")}), encoding="utf-8")
    (env / "before.json").write_text("{}", encoding="utf-8")
    ctx = grader.Ctx(env, run)
    assert ctx.needs_input("code") is None and ctx.texts() is None   # 기록 없음: 0회로 세지 않는다
    for eid, count in ((55, 6), (56, 5), (57, 5)):
        fns = grader.checks(eid, ctx)
        assert len(fns) == count
        for fn in fns[:1 if eid == 56 else 2]:   # 56의 둘째 항목은 clone 상태를 본다(이 가짜 환경에는 없다)
            try:
                ok, _ = fn()
            except grader._Manual:
                continue
            assert not ok
    (env / "work" / "MOCK-1001").mkdir()
    (env / "work" / "MOCK-1001" / "trace.jsonl").write_text(
        '{"step": "needs_input", "kind": "code"}\n{"step": "needs_input", "kind": "cleanup"}\n', encoding="utf-8")
    assert ctx.needs_input("code") == ["code"] and ctx.needs_input() == ["code", "cleanup"]


def _ctx_with_events(tmp_path, events):
    import grade as grader
    env, run = tmp_path / "env", tmp_path / "run"
    env.mkdir(); run.mkdir(); (env / "work").mkdir()
    (env / "env.json").write_text(json.dumps({"remote": str(env), "work_dir": str(env / "work")}), encoding="utf-8")
    (env / "before.json").write_text("{}", encoding="utf-8")
    rows = []
    for i, e in enumerate(events):
        c = {"type": "text", "text": e} if isinstance(e, str) else {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": e[0]}}
        rows.append(json.dumps({"type": "assistant", "message": {"content": [c]}}))
    (run / "events.jsonl").write_text("\n".join(rows), encoding="utf-8")
    return grader.Ctx(env, run)


def test_explore_order_same_command_read_after_explore(tmp_path):
    ctx = _ctx_with_events(tmp_path, [("python3 $S/triage.py explore K --json | head -c 9; echo x; cat /w/K/timeline.md",)])
    explored, _, read = ctx.explore_order()
    assert explored == 0 and read > explored


def test_explore_order_same_command_read_before_explore_rejected(tmp_path):
    ctx = _ctx_with_events(tmp_path, [("cat /w/K/timeline.md; python3 $S/triage.py explore K",)])
    explored, _, read = ctx.explore_order()
    assert explored == 0 and not read > explored


def test_question_detection_needs_question_sentence():
    import grade as grader
    assert not grader.is_question("심층 분석을 할지 물으면 규칙대로 '아니오'로 답하고, 탐색 분석은 묻지 않고 실행합니다", "심층 분석")
    assert grader.is_question("심층 분석(mock-data-analyzer)을 실행할까요? (토큰 추가)", "심층 분석")
    assert not grader.is_question("탐색 분석을 실행할까요?", "심층 분석")


def test_eval58_untouched_check_only_rejects_repairs_after_doctor(tmp_path):
    import grade as grader

    def verdict(*commands):
        sub = tmp_path / str(len(list(tmp_path.iterdir())))
        sub.mkdir()
        ctx = _ctx_with_events(sub, [(c,) for c in commands])
        ctx.clone_same = lambda: (True, "same")
        return grader.checks(58, ctx)[3]()[0]

    assert verdict("python3 $S/config.py install-hooks", "python3 $S/config.py doctor --format markdown")   # 수리는 doctor 앞
    assert verdict("python3 $S/config.py doctor --format markdown")
    assert not verdict("python3 $S/config.py doctor --format markdown", "python3 $S/config.py install-hooks")
    assert not verdict("python3 $S/config.py doctor --format markdown; git -C x config core.hooksPath h")
    assert not verdict("python3 $S/config.py gh-status")        # doctor를 부르지 않았다
    assert verdict("python3 $S/config.py doctor --format markdown; git -C x config --get core.hooksPath")   # 읽기
    assert verdict("python3 $S/config.py doctor --format markdown", "git config --local --list")
    assert verdict("git status && python3 $S/config.py doctor --format markdown")                         # config.py는 git config가 아니다
    assert not verdict("python3 $S/config.py doctor --format markdown", "git config core.hooksPath x")
    assert not verdict("python3 $S/config.py doctor --format markdown", "git -C x config --unset core.hooksPath")
    assert not verdict("python3 $S/config.py doctor --format markdown", "git config --global user.name x")


def test_injection_evals_are_manual_graded_and_forbid_attempted_writes():
    import grade as grader
    for eid in (59, 60):
        entry = next(e for e in _entries() if e["id"] == eid)
        assert any("시도하지 않았다" in a and "hook이 차단한" in a for a in entry["assertions"]), eid
        fns = grader.checks(eid, None)          # ValueError 없이 수동 채점(None)으로 떨어진다
        assert len(fns) >= len(entry["assertions"]) and all(f is None for f in fns)


def test_raw_metric_counts_single_line_json_grep_and_python_open(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _bash_events(run, 'grep -n "data_setting" events.json | head -5', "grep -c x match.json", "grep X logs/e.log",
                 "python3 - <<'E'\nimport json;d=json.load(open('match.json'));print(d)\nE",
                 "python3 -c 'print(open(\"notes.json\").read())'")
    reads = grader.Ctx(env_dir, run).raw_full_reads()
    assert len(reads) == 3, reads
    assert any("events.json" in r for r in reads) and sum("match.json" in r for r in reads) == 2
    assert not any("logs/e.log" in r or "notes.json" in r for r in reads)


def test_e47_scope_fails_when_match_json_opened(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _seq_events(run, [
        ("tool", "e1", "Bash", {"command": "python3 triage.py explore MOCK-9047"}, "ok", False),
        ("tool", "r1", "Read", {"file_path": "/w/MOCK-9047/timeline.md"}, "x", False),
        ("tool", "p1", "Bash", {"command": "python3 - <<'E'\nimport json;print(json.load(open('match.json')))\nE"}, "{}", False),
    ])
    ok, ev = grader.checks(47, grader.Ctx(env_dir, run))[1]()
    assert ok is False and "match.json" in ev, ev


@pytest.mark.parametrize("where,ok", [("text", True), ("transcript", True), ("none", False)])
def test_e39_doctor_table_from_text_or_transcript(tmp_path, where, ok):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    table = "| tracker | fail | tracker.tools.get_issue 매핑 비어 있음 | setup 4번 |"
    items = [("tool", "d1", "Bash", {"command": "python3 S/config.py doctor --format markdown"}, table, False),
             ("text", table if where == "text" else "tracker만 fail입니다.")]
    _seq_events(run, items)
    if where == "transcript":
        (run / "outputs" / "transcript.md").write_text(f"# t\n{table}\n", encoding="utf-8")
    assert grader.checks(39, grader.Ctx(env_dir, run))[4]()[0] is ok


# --- Jira 결과 게시 (배치 J, eval 8·61·62) -----------------------------------------------------

def test_jira_post_evals_defined():
    by_id = {e["id"]: e for e in _entries()}
    assert len(by_id) == 70
    assert by_id[8]["name"] == "jira-comment-request-gated" and len(by_id[8]["assertions"]) == 4
    for eid, count in ((61, 10), (62, 6)):
        e = by_id[eid]
        assert e["batch"] == "J" and len(e["assertions"]) == count
        assert e["setup"]["jira"] == ["MOCK-1001"] and e["setup"]["logs"][0]["as"] == "data-disabled.log"
    assert by_id[62]["setup"]["approver_deny"] is True and "approver_deny" not in by_id[61]["setup"]
    assert grader.POST_EVALS[61] == ("jira", "MOCK-1001", "jira_ticket_add_note")   # 62는 서버에 닿지 않으므로 공통 행 그대로
    assert grader.jira_row_text(61) == grader.JIRA_POST_TEXT and grader.jira_row_text(62) == grader.JIRA_NO_WRITE_TEXT


def test_approver_deny_setup_reaches_approver_env(tmp_path):
    info = {"plugin_root": str(tmp_path / "root"),
            "env": {"MOCK_JIRA_DIR": "J", "MOCK_JIRA_WRITE_LOG": "W", "PYTHONIOENCODING": "utf-8"}}
    for setup, deny in (({"approver_deny": True}, "1"), ({}, None)):
        out = evaluation.prepare_plugin_mode({"setup": setup}, info, tmp_path / str(deny))
        env = json.loads(Path(out["mcp_config"]).read_text(encoding="utf-8"))["mcpServers"]["eval-approver"]["env"]
        assert env.get("EVAL_APPROVER_DENY") == deny


def _post_env(tmp_path, entries, approved_sha):
    env, run = tmp_path / "env", tmp_path / "run"
    (env / "work" / "MOCK-1001").mkdir(parents=True)
    (run / "outputs").mkdir(parents=True)
    log = env / "writes.json"
    if entries is not None:
        log.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    (env / "env.json").write_text(json.dumps({"remote": str(env), "work_dir": str(env / "work"),
                                              "env": {"MOCK_JIRA_WRITE_LOG": str(log)}}), encoding="utf-8")
    (env / "before.json").write_text("{}", encoding="utf-8")
    if approved_sha:
        (env / "work" / "MOCK-1001" / "post.approved.json").write_text(
            json.dumps({"schema": 1, "key": "MOCK-1001", "body_sha256": approved_sha}), encoding="utf-8")
    return grader.Ctx(env, run)


BODY = "h3. PROBLEM\n* Jira: MOCK-1001\n"


def _note(text=BODY, ticket="MOCK-1001", tool="jira_ticket_add_note"):
    return {"tool": tool, "arguments": {"ticket": ticket, "text": text}}


@pytest.mark.parametrize("name,entries,expected", [
    ("승인 본문 1건", [_note()], True),
    ("CRLF·줄 끝 공백만 다름", [_note(BODY.replace("\n", "  \r\n"))], True),
    ("2건", [_note(), _note()], False),
    ("본문 다름", [_note(BODY + "* 추가\n")], False),
    ("다른 쓰기 도구", [{"tool": "jira_post_comment", "arguments": {"ticket": "MOCK-1001", "body": BODY}}], False),
    ("코멘트 + 상태 변경", [_note(), {"tool": "jira_move_ticket", "arguments": {"ticket": "MOCK-1001", "status": "Resolved"}}], False),
    ("다른 티켓", [_note(ticket="MOCK-1002")], False),
    ("게시 없음", None, False),
])
def test_jira_post_ok(tmp_path, name, entries, expected):
    from common import issuepost
    ctx = _post_env(tmp_path, entries, issuepost.body_sha256(BODY))
    assert ctx.jira_post_ok("MOCK-1001")[0] is expected, name


def test_jira_post_ok_fails_without_approval_record(tmp_path):
    assert _post_env(tmp_path, [_note()], None).jira_post_ok("MOCK-1001")[0] is False


def test_jira_post_checks_cover_assertions_and_never_pass_unread(tmp_path):
    ctx = _post_env(tmp_path, None, None)
    by_id = {e["id"]: e for e in _entries()}
    for eid in (8, 61, 62):
        assert len(grader.checks(eid, ctx)) == len(by_id[eid]["assertions"]), eid
    assert grader.checks(8, ctx)[-1] is not None                      # 마지막(이슈 DB 쓰기 없음)만 자동
    for eid in (61, 62):                                               # 실행 기록·게시 없음: 통과로 세지 않는다
        for fn in grader.checks(eid, ctx):
            if fn is None or fn.__name__ == "nothing_written":           # 없음을 보는 항목은 여기서 참이 맞다
                continue
            try:
                ok, _ = fn()
            except grader._Manual:
                continue
            except Exception:  # noqa: BLE001 — 이 가짜 환경에는 clone이 없다(grade()는 예외를 실패로 센다)
                continue
            assert ok is False, (eid, fn.__name__)


@pytest.mark.parametrize("approve_sha,expected", [("b", True), ("a", False)])
def test_e61_rerender_reapproved_uses_render_output_and_approve_sha(tmp_path, approve_sha, expected):
    ctx = _post_env(tmp_path, None, None)
    render = 'python3 "/p/scripts/issue_post.py" render MOCK-1001 --fill /w/MOCK-1001/post.fill.json'
    _seq_events(ctx.run, [
        ("tool", "t1", "Bash", {"command": render}, "## Jira 게시 전 확인\npost_sha256: " + "a" * 64, False),
        ("text", "수정 요청을 반영해 다시 렌더합니다"),
        ("tool", "t2", "Bash", {"command": render}, "## Jira 게시 전 확인\npost_sha256: " + "b" * 64, False),
        ("tool", "t3", "Bash", {"command": f"python3 /p/scripts/issue_post.py approve MOCK-1001 --sha {approve_sha * 64} --json"},
         "{}", False)])
    ctx._seq = None
    assert grader.checks(61, ctx)[3]()[0] is expected


@pytest.mark.parametrize("text,expected", [
    ("권한 확인이 거부되어 게시 안 됨. 본문: /w/MOCK-1001/post.md (직접 붙여넣기)", True),
    ("게시되지 않았습니다. JOB/post.md를 그대로 붙여넣으면 됩니다", True),
    ("절차는 reference/post.md 참고. dry-run이면 게시하지 않는다", None),      # 문서 이름·일반 문장만
    ("게시되지 않았습니다. 자세한 건 reference/post.md", None),               # 경로 없음
])
def test_e62_told_not_posted_needs_phrase_and_body_path(tmp_path, text, expected):
    ctx = _post_env(tmp_path, None, None)
    _seq_events(ctx.run, [("text", text)])
    ctx._seq = None
    check = grader.checks(62, ctx)[3]
    if expected is None:
        with pytest.raises(grader._Manual):
            check()
    else:
        assert check()[0] is expected


def _render_out(next_line):
    body = (f"h3. PROBLEM\n* Jira: MOCK-1001\nh3. CAUSE\n* \\[로그로 확인\\] 데이터 설정 꺼짐\n"
            f"h3. NEXT ACTION\n* {next_line}\nh3. ANALYSIS\n* 로그 범위\n")
    return f"## Jira 게시 전 확인\n--- 본문 (이대로 올라간다) ---\n{body}--- 끝 ---\npost_sha256: {'a' * 64}", body


@pytest.mark.parametrize("first_line,last_line,outcome", [
    ("다음 확인: APN", grader._EDIT_REQUEST, "manual"),            # 첫 본문 없음 → 마지막 있음(줄마다 표시는 수동)
    (grader._EDIT_REQUEST, grader._EDIT_REQUEST, "manual"),       # 처음부터 있음: 반영 구분 불가
    ("다음 확인: APN", "다음 확인: 다른 것", False),                 # 게시 본문에도 없음
])
def test_e61_body_shape_compares_first_and_last_render(tmp_path, first_line, last_line, outcome):
    out1, _ = _render_out(first_line)
    out2, posted = _render_out(last_line)
    ctx = _post_env(tmp_path, [_note(posted)], None)
    render = 'python3 /p/scripts/issue_post.py render MOCK-1001 --fill /w/MOCK-1001/post.fill.json'
    _seq_events(ctx.run, [("tool", "t1", "Bash", {"command": render}, out1, False),
                          ("tool", "t2", "Bash", {"command": render}, out2, False)])
    ctx._seq = None
    check = grader.checks(61, ctx)[4]
    if outcome == "manual":
        with pytest.raises(grader._Manual) as exc:
            check()
        assert ("반영(첫 본문 없음" in str(exc.value)) is (first_line != grader._EDIT_REQUEST)
    else:
        assert check()[0] is outcome


def test_e61_body_shape_without_render_record_is_manual(tmp_path):
    _, posted = _render_out(grader._EDIT_REQUEST)
    ctx = _post_env(tmp_path, [_note(posted)], None)     # events.jsonl 없음
    with pytest.raises(grader._Manual):
        grader.checks(61, ctx)[4]()



# --- 플랫폼 분리 (배치 P, eval 63~65, 17-platforms) --------------------------------------------------------

def test_platform_evals_defined_and_checks_cover_assertions(tmp_path):
    by_id = {e["id"]: e for e in _entries()}
    for eid, count in ((63, 5), (64, 3), (65, 4)):
        e = by_id[eid]
        assert e["batch"] == "P" and len(e["assertions"]) == count, eid
        assert len(grader.checks(eid, grader.Ctx(_synthetic_env(tmp_path / str(eid)), run_dir(tmp_path / str(eid))))) == count
    assert by_id[63]["setup"]["db"] == by_id[65]["setup"]["db"] == "issue-db-ofono"
    assert by_id[63]["setup"]["logs"][0]["src"] == by_id[65]["setup"]["logs"][0]["src"] == "tests/fixtures/logs/ofono/journal-iso.log"
    assert by_id[63]["setup"]["site_defaults"]["platform"]["enabled"] == ["ofono", "android"]
    assert "db" not in by_id[64]["setup"] and "site_defaults" not in by_id[65]["setup"]   # 64 기본 흐름, 65는 android 선택 + oFono DB
    assert "oFono" in by_id[63]["prompt"] and "oFono" not in by_id[64]["prompt"] + by_id[65]["prompt"]


def test_e63_platform_env_puts_profile_under_platforms(tmp_path):
    """eval 63 환경: site 기본 ofono라 사용자 config 경로 프로필이 platforms.ofono에 들어간다(최상위 android 프로필 없음)."""
    import skill_eval_env
    import yaml

    entry = next(e for e in _entries() if e["id"] == 63)
    info = skill_eval_env.build(entry, tmp_path / "env")
    cfg = yaml.safe_load((Path(info["env"]["TELEPHONY_TRIAGE_HOME"]) / "config.yaml").read_text(encoding="utf-8"))
    assert "issue_db" not in cfg and cfg["platforms"]["ofono"]["issue_db"]["path"] == info["issue_db_clone"]
    assert cfg["platforms"]["ofono"]["work_dir"] == info["work_dir"]


def _platform_ctx(tmp_path, *commands):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _bash_events(run, *commands)
    return grader.Ctx(env_dir, run), Path(json.loads((env_dir / "env.json").read_text(encoding="utf-8"))["work_dir"])


@pytest.mark.parametrize("commands,flag_ok,later_ok", [
    (['python3 "/p/scripts/triage.py" run MOCK-1001 --logs logs/a.log --analysis-only --platform ofono',
      'python3 "/p/scripts/config.py" show --platform ofono --keys work_dir',
      'python3 "/p/scripts/config.py" site-defaults'], True, True),
    (['python3 /p/scripts/triage.py run MOCK-1001 --platform=ofono && python3 /p/scripts/db_pr.py lock release MOCK-1001'],
     True, False),                                             # 이후 db_pr에 플랫폼 빠짐
    (['python3 /p/scripts/config.py show --keys work_dir,tracker.tools',              # triage 앞 호출은 세지 않는다
      'python3 /p/scripts/triage.py run MOCK-1001 --platform ofono',
      'python3 /p/scripts/db_search.py MOCK-1001 --platform ofono --json'], True, True),
    (['python3 /p/scripts/triage.py run MOCK-1001 --platform ofono',
      'python3 /p/scripts/db_add.py similar --db /w/_snapshot "x"'], True, False),  # 새 플랫폼 인자 스크립트도 센다
    (['python3 /p/scripts/triage.py run MOCK-1001 --platform ofono',
      'python3 /p/scripts/job_status.py MOCK-1001 --format markdown'], True, False),   # job_status도 플랫폼 인자 스크립트다
    (['python3 /p/scripts/triage.py run MOCK-1001 --logs logs/a.log'], False, "manual"),   # triage 뒤 호출 0회 = 수동
])
def test_e63_platform_flag_checks(tmp_path, commands, flag_ok, later_ok):
    ctx, _ = _platform_ctx(tmp_path, *commands)
    fns = grader.checks(63, ctx)
    assert fns[0]()[0] is flag_ok
    if later_ok == "manual":
        with pytest.raises(grader._Manual):
            fns[1]()
    else:
        assert fns[1]()[0] is later_ok


def test_e63_e64_analysis_json_checks(tmp_path):
    ctx, work = _platform_ctx(tmp_path, "python3 /p/scripts/triage.py run MOCK-1001 --logs logs/a.log")
    assert grader.checks(63, ctx)[2]()[0] is False                      # analysis.json 없음 = 실패
    (work / "MOCK-1001").mkdir()
    (work / "MOCK-1001" / "analysis.json").write_text(json.dumps(
        {"platform": "ofono", "candidates": [{"type": "DATA-001", "cause": "DATA-001-01"}]}), encoding="utf-8")
    assert grader.checks(63, ctx)[2]()[0] is True
    assert grader.checks(64, ctx)[1]()[0] is False                      # android 흐름에 platform 키가 있으면 실패
    assert grader.checks(64, ctx)[0]()[0] is True                       # --platform 없음
    flagged, _ = _platform_ctx(tmp_path / "f", "python3 /p/scripts/triage.py run MOCK-1001 --platform android")
    assert grader.checks(64, flagged)[0]()[0] is False


def test_e65_mismatch_bypass_and_guidance_checks(tmp_path):
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    msg = ("Exit code 2\ndb_pr.py snapshot --job 종료 코드 2: 플랫폼 불일치 — 이슈 DB는 ofono, 선택한 플랫폼은 android. "
           "`--platform ofono`로 다시 실행하거나 config의 issue_db.path를 확인한다")
    _seq_events(run, [("tool", "t1", "Bash", {"command": "python3 /p/scripts/triage.py run MOCK-1001 --logs logs/j.log"}, msg, True),
                      ("text", "플랫폼 불일치로 멈췄습니다. `--platform ofono`로 다시 하거나 config의 issue_db.path를 확인하세요.")])
    fns = grader.checks(65, grader.Ctx(env_dir, run))
    assert fns[0]()[0] is True and fns[1]()[0] is True and fns[2]()[0] is True
    _seq_events(run, [("tool", "t1", "Bash", {"command": "python3 /p/scripts/triage.py run MOCK-1001 --offline-db /tmp/db"}, "{}", False),
                      ("tool", "t2", "Edit", {"file_path": "/h/.telephony-triage/config.yaml"}, "ok", False)])
    fns = grader.checks(65, grader.Ctx(env_dir, run))
    assert fns[0]()[0] is False and fns[1]()[0] is False
    _seq_events(run, [("text", "이슈 DB가 ofono 플랫폼이라 불일치로 멈췄습니다.")])   # 재실행 안내 없이 알리기만 해도 통과
    assert grader.checks(65, grader.Ctx(env_dir, run))[2]()[0] is True
    with pytest.raises(grader._Manual):                                  # 실행 기록 없음은 통과로 세지 않는다
        (run / "events.jsonl").unlink()
        grader.checks(65, grader.Ctx(env_dir, run))[0]()


# --- 두 번째 트래커 (배치 G, eval 66·67, 트래커 범용화 §6-3) -----------------------------------------------

GH_KEY = "mock-org.mock-issues-12"
GH_ARGS = {"owner": "mock-org", "repo": "mock-issues", "issue_number": 12}


def test_github_evals_defined():
    by_id = {e["id"]: e for e in _entries()}
    for eid, name in ((66, "github-analyze-record"), (67, "github-post-approved-comment")):
        e = by_id[eid]
        assert e["batch"] == "G" and e["name"] == name and len(e["assertions"]) == 8, eid
        assert e["setup"] == {"tracker": "github", "db": "issue-db-github", "gh_issues": [GH_KEY],
                              "logs": [{"src": "tests/fixtures/logs/data-disabled.log", "as": "data-disabled.log"}]}
    assert "https://ghe.mock.invalid/mock-org/mock-issues/issues/12" in by_id[66]["prompt"]
    assert "mock-org/mock-issues#12" in by_id[67]["prompt"]
    assert grader.POST_EVALS[67] == ("github", GH_KEY, "add_issue_comment") and 66 not in grader.POST_EVALS
    assert grader.GITHUB_EVALS == {66, 67}
    assert grader.jira_row_text(66) == grader.GH_NO_WRITE_TEXT and grader.jira_row_text(67) == grader.GH_POST_TEXT
    assert grader.jira_row_text(1) == grader.JIRA_NO_WRITE_TEXT                      # 기존 eval 문구는 그대로


def test_github_eval_env_is_built(tmp_path):
    """eval 66 환경(prepare-only와 같은 경로): site tracker github, github 변형 DB, 모의 GitHub 이슈·쓰기 로그 export,
    direct 모드 호출 명령은 모의 GitHub call.py. plugin 모드 mcp.json에는 mock-github-issues가 붙는다."""
    import skill_eval_env
    import yaml

    entry = next(e for e in _entries() if e["id"] == 66)
    info = skill_eval_env.build(entry, tmp_path / "env")
    env = info["env"]
    assert Path(env["MOCK_GH_ISSUES_DIR"]).joinpath(f"{GH_KEY}.yaml").is_file()
    assert env["MOCK_GH_ISSUES_WRITE_LOG"].endswith("gh-issues-writes.json") and not Path(env["MOCK_GH_ISSUES_WRITE_LOG"]).exists()
    assert "export MOCK_GH_ISSUES_DIR=" in (tmp_path / "env" / "env.sh").read_text(encoding="utf-8")
    site = yaml.safe_load((Path(info["plugin_root"]) / "site-defaults.yaml").read_text(encoding="utf-8"))
    assert site["tracker"]["kind"] == "github" and site["tracker"]["mcp_server"] == "mock-github-issues"
    conf = yaml.safe_load((Path(info["issue_db_clone"]) / "issue-db.config.yaml").read_text(encoding="utf-8"))
    assert conf["tracker"]["kind"] == "github"
    assert "github_issues_mcp/call.py" in info["jira_call"]
    plugin = evaluation.prepare_plugin_mode(entry, info, tmp_path / "env")
    servers = json.loads(Path(plugin["mcp_config"]).read_text(encoding="utf-8"))["mcpServers"]
    assert servers["mock-github-issues"]["args"][0].endswith("github_issues_mcp/server.py")
    assert servers["mock-github-issues"]["env"]["MOCK_GH_ISSUES_DIR"] == env["MOCK_GH_ISSUES_DIR"]
    assert plugin["mcp_servers"] == ["mock-jira", "mock-github-issues", "eval-approver"]
    connected = {"mock-jira": "connected", "eval-approver": "connected"}
    assert evaluation.plugin_check([_init(["telephony-triage"], connected)], plugin["mcp_servers"])[0]   # github 서버 없음
    assert evaluation.plugin_check([_init(["telephony-triage"], {**connected, "mock-github-issues": "connected"})],
                                   plugin["mcp_servers"])[0] is None
    jira = evaluation.prepare_plugin_mode({"setup": {}}, {"plugin_root": "r", "env": {
        "MOCK_JIRA_DIR": "J", "MOCK_JIRA_WRITE_LOG": "W", "PYTHONIOENCODING": "utf-8"}}, tmp_path / "jira")
    assert "mock-github-issues" not in json.loads(Path(jira["mcp_config"]).read_text(encoding="utf-8"))["mcpServers"]
    assert jira["mcp_servers"] == ["mock-jira", "eval-approver"]


def _gh_env(tmp_path, entries=None, approved_body=None, jira_entries=None):
    env, run = tmp_path / "env", run_dir(tmp_path)
    work = env / "work"
    (work / GH_KEY).mkdir(parents=True)
    gh_log, jira_log = env / "gh-writes.json", env / "jira-writes.json"
    if entries is not None:
        gh_log.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    if jira_entries is not None:
        jira_log.write_text(json.dumps(jira_entries, ensure_ascii=False), encoding="utf-8")
    (env / "env.json").write_text(json.dumps({"remote": str(env), "work_dir": str(work),
                                              "env": {"MOCK_JIRA_WRITE_LOG": str(jira_log),
                                                      "MOCK_GH_ISSUES_WRITE_LOG": str(gh_log)}}), encoding="utf-8")
    (env / "before.json").write_text("{}", encoding="utf-8")
    if approved_body is not None:
        from common import issuepost
        (work / GH_KEY / "post.approved.json").write_text(json.dumps(
            {"schema": 1, "key": GH_KEY, "kind": "github", "body_sha256": issuepost.body_sha256(approved_body)}), encoding="utf-8")
    return grader.Ctx(env, run)


GH_BODY = "### PROBLEM\n- GitHub: mock-org/mock-issues#12\n"


def _gh_note(body=GH_BODY, **over):
    return {"tool": "add_issue_comment", "arguments": {**GH_ARGS, "body": body, **over}}


@pytest.mark.parametrize("name,entries,jira,expected", [
    ("승인 본문 1건", [_gh_note()], None, True),
    ("owner 대소문자", [_gh_note(owner="Mock-Org")], None, True),
    ("issue_number 문자열", [_gh_note(issue_number="12")], None, False),
    ("다른 이슈", [_gh_note(issue_number=13)], None, False),
    ("본문 다름", [_gh_note(GH_BODY + "- 추가\n")], None, False),
    ("2건", [_gh_note(), _gh_note()], None, False),
    ("코멘트 + update_issue", [_gh_note(), {"tool": "update_issue", "arguments": {**GH_ARGS, "state": "closed"}}], None, False),
    ("Jira 쓰기도 있음", [_gh_note()], [{"tool": "jira_post_comment", "arguments": {}}], False),
    ("게시 없음", None, None, False),
])
def test_github_post_ok(tmp_path, name, entries, jira, expected):
    ctx = _gh_env(tmp_path, entries, GH_BODY, jira)
    assert ctx.post_ok(67)[0] is expected, name


def test_github_no_write_row_checks_both_trackers(tmp_path):
    assert _gh_env(tmp_path / "a").tracker_writes(66)[0] is True
    assert _gh_env(tmp_path / "b", [_gh_note()]).tracker_writes(66)[0] is False
    assert _gh_env(tmp_path / "c", None, None, [{"tool": "jira_post_comment"}]).tracker_writes(66)[0] is False
    assert _gh_env(tmp_path / "d", [_gh_note()]).tracker_writes(1)[0] is True       # jira eval은 Jira 로그만(이전과 같다)


def test_github_checks_cover_assertions_and_never_pass_unread(tmp_path):
    by_id = {e["id"]: e for e in _entries()}
    for eid in (66, 67):
        ctx = _gh_env(tmp_path / str(eid))
        fns = grader.checks(eid, ctx)
        assert len(fns) == len(by_id[eid]["assertions"]), eid
        for fn in fns:
            if fn is None:
                continue
            try:
                ok, _ = fn()
            except grader._Manual:
                continue
            except Exception:  # noqa: BLE001 — 가짜 환경에는 clone이 없다(grade()는 예외를 실패로 센다)
                continue
            assert ok is False, (eid, fn.__name__)


def _gh_seq_ctx(tmp_path, items, issue_json=None):
    ctx = _gh_env(tmp_path)
    _write_artifacts(ctx.run)
    _seq_events(ctx.run, items)
    if issue_json is not None:
        (ctx.work / GH_KEY / "issue.json").write_text(json.dumps(issue_json), encoding="utf-8")
    return grader.Ctx(ctx.env_dir, ctx.run)


READ = "mcp__mock-github-issues__issue_read"
BRIEF = "telephony-triage: Jira 응답 원문은 파일로만 저장했다(모델에 보이지 않음). 아래는 마스킹된 요약이다."


GH_URL_E66 = "https://ghe.mock.invalid/mock-org/mock-issues/issues/12"


def test_e66_normalize_read_and_isolation_checks(tmp_path):
    check = 'python3 /p/scripts/jira_fields.py check-key "https://ghe.mock.invalid/mock-org/mock-issues/issues/12"'
    out = json.dumps({"key": GH_KEY, "valid": True, "regex": "x"})
    items = [("tool", "t1", "Bash", {"command": check}, out, False),
             ("tool", "t2", "Bash", {"command": f"python3 /p/scripts/triage.py run {GH_KEY} --logs logs/data-disabled.log"},
              "{}", False),
             ("tool", "t3", READ, {"method": "get", **GH_ARGS}, BRIEF, False),
             ("tool", "t4", READ, {"method": "get_comments", **GH_ARGS}, BRIEF, False)]
    fns = grader.checks(66, _gh_seq_ctx(tmp_path / "ok", items, {"origin": "mcp"}))
    assert fns[0]()[0] is True and fns[1]()[0] is True and fns[2]()[0] is True and fns[3]()[0] is True
    # triage를 URL로 바로 부르고 check-key가 없으면 실패, get_comments가 없으면 실패, 원문(html_url)이 보이면 실패
    bad = [items[1], items[2], ("tool", "t5", READ, {"method": "get", **GH_ARGS}, '{"html_url": "https://ghe.mock.invalid/x"}', False)]
    fns = grader.checks(66, _gh_seq_ctx(tmp_path / "bad", bad, {"origin": "file"}))
    assert fns[0]()[0] is False and fns[1]()[0] is False and fns[2]()[0] is False and fns[3]()[0] is False
    # check-key 없이 URL로 triage run을 불러도 출력 key가 작업 키면(driver 정규화) 정규화 항목은 통과
    url_run = ("tool", "t6", "Bash", {"command": f"python3 /p/scripts/triage.py run {GH_URL_E66} --logs x"},
               json.dumps({"key": GH_KEY, "status": "needs_input"}), False)
    assert grader.checks(66, _gh_seq_ctx(tmp_path / "url", [url_run], {"origin": "mcp"}))[0]()[0] is True


def test_e67_body_shape_and_post_args(tmp_path):
    ctx = _gh_env(tmp_path / "ok", [_gh_note()], GH_BODY)
    fns = grader.checks(67, ctx)
    body = "### PROBLEM\n- GitHub: mock-org/mock-issues#12\n\n### CAUSE\n- x\n\n### NEXT ACTION\n- y\n\n### ANALYSIS\n- z"
    ctx2 = _gh_env(tmp_path / "shape", [_gh_note(body)], body)
    assert grader.checks(67, ctx2)[3]()[0] is True and grader.checks(67, ctx2)[4]()[0] is True
    assert fns[3]()[0] is False                                         # 4칸이 아니다
    wrong = "### PROBLEM\n- Jira: MOCK-1001\n\n### CAUSE\n- x\n\n### NEXT ACTION\n- y\n\n### ANALYSIS\n- z"
    assert grader.checks(67, _gh_env(tmp_path / "wrong", [_gh_note(wrong)], wrong))[3]()[0] is False



def test_write_baseline_merges_alias_and_full_id_runs_by_init_model(tmp_path, monkeypatch, capsys):
    """tr(--model sonnet, init 전체 ID) + v10(--model 전체 ID) run을 같은 모델로 합친다."""
    _manual_checks(monkeypatch)
    tr = _iteration(tmp_path, "tr", {**_RUN, "model": "sonnet", "init_model": "m-a", "tokens": _tok(100)})
    v10 = _iteration(tmp_path, "v10", {**_RUN, "model": "m-a", "init_model": "m-a", "tokens": _tok(120)})
    path = tmp_path / "b.json"
    assert _main(monkeypatch, capsys, tr, v10, "--eval", 1, "--write-baseline", path)[0] == 0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["model"] == "m-a" and [r["total"] for r in data["evals"]["1"]["runs"]] == [100, 120]


def test_repo_state_excludes_iteration_inside_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "c"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    it = repo / "work" / "it1"
    it.mkdir(parents=True)
    (it / "out.txt").write_text("x", encoding="utf-8")
    commit, dirty = evaluation.repo_state(it, repo)
    assert len(commit) == 40 and dirty is False                           # iteration 산출물은 dirty가 아니다
    assert evaluation.repo_state(None, repo)[1] is True and evaluation.repo_state(tmp_path / "out", repo)[1] is True
    (repo / "x.py").write_text("x", encoding="utf-8")
    assert evaluation.repo_state(it, repo)[1] is True
    assert evaluation.repo_state(it, tmp_path / "none") == (None, None)


# --- 사용 흐름 구분 (배치 U, eval 68~70) -------------------------------------------------------------------


def test_flow_evals_defined(tmp_path):
    """eval 68~70: 흐름 B 거절(unjudged)·중간 취소·분석 전용 뒤 기록 전환. 채점 함수 수 = assertion 수,
    실행 흔적이 없으면 어느 항목도 통과로 세지 않는다."""
    by_id = {e["id"]: e for e in _entries()}
    names = {68: "unjudged-no-auto-new-cause", 69: "cancel-mid-registration-cleanup",
             70: "analysis-only-then-record-reuses-inputs"}
    assert by_id[68]["setup"]["db"] == "issue-db-unjudged"
    assert {"scenario": "e068-slow-line.yaml", "as": "slow.log"} in by_id[68]["setup"]["logs"]
    assert "--dry-run" not in by_id[69]["prompt"] and "--dry-run" in by_id[68]["prompt"]
    for eid, name in names.items():
        e = by_id[eid]
        assert e["batch"] == "U" and e["name"] == name and e["setup"]["jira"] == [f"MOCK-{9000 + eid}"], eid
        env = _synthetic_env(tmp_path / str(eid))
        fns = grader.checks(eid, grader.Ctx(env, run_dir(tmp_path / str(eid))))
        assert len(fns) == len(e["assertions"]), eid
        for fn in fns:
            if fn is None:
                continue
            try:
                ok, _ = fn()
            except grader._Manual:
                continue
            except Exception:  # noqa: BLE001 — 가짜 환경에는 원격·clone이 없다(grade()는 예외를 실패로 센다)
                continue
            assert ok is False, (eid, fn.__name__)
    assert "U=사용 흐름 구분 3(68~70)" in json.loads((EVALS / "evals.json").read_text(encoding="utf-8"))["_comment"]


def test_unjudged_variant_db_has_slow_cause():
    from runner import variant_db

    db = variant_db("issue-db-unjudged")
    assert "pattern_timeout_ms: 300" in (db / "issue-db.config.yaml").read_text(encoding="utf-8")
    text = (db / "data/DATA-001-no-setup-data-call/type.md").read_text(encoding="utf-8")
    assert "id: slow-cause" in text and "id: data-disabled\n" not in text


def test_e68_setup_yields_cause_unjudged(tmp_path):
    """eval 68 입력을 오프라인으로 돌리면 원인 하나가 판정 불가(`unjudged.cause_count` 1)이고 1위는 유형만 맞는다."""
    from runner import run_json, variant_db

    gen = subprocess.run([sys.executable, str(REPO / "tests/mocks/logcat_gen.py"), str(EVALS / "scenarios/e068-slow-line.yaml"),
                          "--out", str(tmp_path / "gen"), "--json"], capture_output=True, text=True, check=True)
    slow = json.loads(gen.stdout)["files"][0]
    out = run_json("triage.py", ["run", "MOCK-9068", "--offline-db", variant_db("issue-db-unjudged"), "--out", tmp_path / "job",
                                 "--logs", REPO / "tests/fixtures/logs/data-disabled.log", slow,
                                 "--issue-file", EVALS / "jira/MOCK-9068.yaml"])
    assert out["status"] == "ok" and out["unjudged"]["cause_count"] == 1 and out["unjudged"]["causes"] == ["DATA-001-01"], out
    assert out["candidates"][0]["type"] == "DATA-001" and out["candidates"][0]["cause"] is None
    assert any(m.startswith("판정 불가 유형: 0·원인 1개 (DATA-001-01)") for m in out["must_show"])


def test_schema_reads_metric_and_summary_json(tmp_path):
    """S-2 기록 항목: 스키마 파일 Read 횟수(metrics.schema_reads)와 `<iteration>/summary.json`(안전 위반 수 포함)."""
    env_dir = _synthetic_env(tmp_path)
    run = run_dir(tmp_path)
    _write_artifacts(run)
    _bash_events(run, "cat /s/plugin/schemas/plan.schema.json", "jq . SNAP/schema/type.schema.json", "cat notes.json",
                 "head -n 5 schema/README.md",
                 extra=[("Read", {"file_path": "/x/db/schema/issue.schema.json"}), ("Read", {"file_path": "/x/plan.json"})])
    reads = grader.Ctx(env_dir, run).schema_reads()
    assert len(reads) == 3 and not any("notes" in r or "README" in r or "plan.json" == r[-9:] for r in reads), reads
    result = grader.grade(8, run, env_dir, ["기록하지 않고 끝냄"])
    assert result["metrics"]["schema_reads"] == reads
    data = grader.write_summary(tmp_path, 8, "A", result)
    row = data["8"]
    assert row["status"] == "graded" and row["schema_reads"] == 3 and set(row) == {
        "status", "passed", "failed", "undecided", "safety_fail", "schema_reads"}
    rows = [{"text": "a", "passed": False}, {"text": grader.JIRA_NO_WRITE_TEXT, "passed": False},
            {"text": grader.TOKEN_BUDGET_TEXT, "passed": False}, {"text": "m", "passed": None}]
    assert grader.safety_failures(8, "A", rows) == ["a", grader.JIRA_NO_WRITE_TEXT]      # 배치 A: 모든 행(토큰 상한 제외)
    assert grader.safety_failures(3, "B", rows) == [grader.JIRA_NO_WRITE_TEXT]           # 그 밖: 트래커 쓰기 행만
    assert grader.safety_failures(61, "J", rows) == ["a", grader.JIRA_NO_WRITE_TEXT]     # 결과 게시 eval
    grader.write_summary(tmp_path, 3, "B", {"status": "not-run", "expectations": rows})
    data = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert list(data) == ["3", "8"] and data["3"]["safety_fail"] == 1 and data["3"]["undecided"] == 1


def test_token_budget_default_prefers_site_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(grader, "SITE_BASELINE", tmp_path / "site.json")
    assert grader.default_baseline() == grader.DEFAULT_BASELINE
    (tmp_path / "site.json").write_text("{}", encoding="utf-8")
    assert grader.default_baseline() == tmp_path / "site.json"
