#!/usr/bin/env python3
"""OpenCode 어댑터(`plugin/scripts/common/oc_adapter.py`, 계획 I O1·O2b) — opencode 없이 도는 표 테스트.

- 변환 표: 1.19.5 내장 도구마다 Claude Code PreToolUse 입력(또는 통과·거부), bash `workdir` → cwd, 상대 `filePath`,
  apply_patch 경로(1.19.5 파서와 같은 규칙), MCP 서버 접두사(가장 긴 것 먼저, 모든 후보), 모르는 도구·서버 → 거부.
  계획 I 실험에서 찾은 시제품 결함(x1 workdir, x5 apply_patch → `mcp__apply__patch`, `corp_jira_*` 서버 오분할)을 표로 막는다.
- guard 다리: 바뀌지 않은 guard.py를 하위 프로세스로 돌린 결정(설정된 이슈 DB clone 작업공간), `ask` → 거부 + 정확한 명령,
  guard 비정상(시그널·종료 코드·시간 초과·JSON 아님·모르는 결정) → 거부.
- v1 분석 전용: db_pr publish·merge, skill_patch apply, issue_post approve, 리뷰어 요청, module_eval 거부. Jira 읽기 관문·코멘트
  늘 거부, 설정을 덮는 환경변수 → 모두 거부.
- jira_bridge 다리(after): 마스킹 요약으로 대체, 원문은 파일로만, 비Jira MCP는 그대로, 실패는 오류 문구.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from common import oc_adapter as oc
from common import oc_version
from runner import plugin_root, run, tmp

IMSI = "450081234567890"
JIRA = ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets", "mcp__mock-jira__jira_ticket_comments"]


def _dir() -> Path:
    d = tmp("tt-oc-")
    (d / "sub").mkdir()
    (d / "file.txt").write_text("x", encoding="utf-8")
    return d.resolve()


def _map(tool: str, args: dict, directory: Path, servers=None, err=None):
    return oc.map_tool({"tool": tool, "args": args, "directory": str(directory), "sessionID": "s1", "callID": "c1"},
                       servers, err)


# -- 변환 표 --------------------------------------------------------------------------------------------


def test_builtin_table_is_explicit_and_pinned():
    assert oc.OPENCODE_VERSION == oc_version.OPENCODE_VERSION   # 고정값 자체는 tests/test_oc_version.py
    passes = {"invalid", "question", "read", "glob", "grep", "skill", "lsp", "todowrite"}
    denies = {"task", "webfetch", "websearch", "codesearch", "execute", "plan", "list_mcp_resources",
              "list_mcp_resource_templates", "read_mcp_resource"}
    assert {k for k, v in oc.BUILTINS.items() if v[0] == oc.PASS} == passes
    assert {k for k, v in oc.BUILTINS.items() if v[0] == oc.DENY} == denies
    assert set(oc.BUILTINS) == passes | denies | {"bash", "edit", "write", "apply_patch"}
    # JS 플러그인의 after 건너뛰기 표도 같은 이름이다
    js = (REPO / "opencode" / "plugins" / "tt-guard.js").read_text(encoding="utf-8")
    block = js.split("const BUILTINS = new Set([", 1)[1].split("])", 1)[0]
    assert {s.strip().strip('"') for s in block.replace("\n", " ").split(",") if s.strip()} == set(oc.BUILTINS)


@pytest.mark.parametrize("tool", ["read", "glob", "grep", "skill", "todowrite", "invalid", "question", "lsp"])
def test_read_only_builtins_pass(tool):
    m = _map(tool, {"filePath": "/etc/passwd", "pattern": "*"}, _dir())
    assert m.deny is None and m.events == [] and m.kind == oc.PASS


@pytest.mark.parametrize("tool", sorted(k for k, v in oc.BUILTINS.items() if v[0] == oc.DENY))
def test_denied_builtins(tool):
    m = _map(tool, {"prompt": "CHILDTASK", "url": "https://mock-site.invalid"}, _dir())
    assert m.deny and m.events == []
    if tool == "task":
        assert "전역 거부" in m.deny


def test_bash_cwd_comes_from_workdir():
    d = _dir()
    m = _map("bash", {"command": "git push origin main", "description": "x"}, d)
    assert m.events[0]["cwd"] == str(d) and m.command == "git push origin main"
    for workdir in (str(d / "sub"), "sub", "./sub/", "sub/../sub"):        # x1: workdir가 실제로 명령을 돌리는 곳
        m = _map("bash", {"command": "git push origin main", "workdir": workdir}, d)
        ev = m.events[0]
        assert ev["cwd"] == str(d / "sub"), workdir
        assert ev["tool_name"] == "Bash" and ev["tool_input"] == {"command": "git push origin main"}
        assert ev["hook_event_name"] == "PreToolUse" and ev["session_id"] == "s1" and ev["tool_use_id"] == "c1"
        assert m.command == f"cd {d / 'sub'} && git push origin main"


@pytest.mark.parametrize("workdir", ["nope", "file.txt", "~/x", "~", 5, ["sub"]])
def test_bash_bad_workdir_denied(workdir):
    m = _map("bash", {"command": "ls", "workdir": workdir}, _dir())
    assert m.deny and m.events == []


def test_bash_symlink_workdir_resolves_to_real_path():
    d = _dir()
    (d / "link").symlink_to(d / "sub")
    assert _map("bash", {"command": "ls", "workdir": "link"}, d).events[0]["cwd"] == str(d / "sub")


def test_bash_command_must_be_string():
    assert _map("bash", {"command": ["git", "push"]}, _dir()).deny


def test_edit_write_paths_resolve_against_directory():
    d = _dir()
    m = _map("edit", {"filePath": "sub/a.md", "oldString": "a", "newString": "b", "replaceAll": True}, d)
    assert m.events[0]["tool_name"] == "Edit"
    assert m.events[0]["tool_input"] == {"file_path": str(d / "sub" / "a.md"), "old_string": "a", "new_string": "b",
                                         "replace_all": True}
    m = _map("write", {"filePath": "../out.txt", "content": "z"}, d)
    assert m.events[0]["tool_input"] == {"file_path": str(d.parent / "out.txt"), "content": "z"}
    m = _map("write", {"filePath": "/abs/x.txt", "content": ""}, d)
    assert m.events[0]["tool_input"]["file_path"] == "/abs/x.txt"
    # OpenCode는 `~`를 풀지 않는다: `<dir>/~/x`. guard(expanduser)에 홈 경로로 보이지 않게 절대 경로로 준다
    assert _map("write", {"filePath": "~/x", "content": ""}, d).events[0]["tool_input"]["file_path"] == str(d / "~" / "x")
    assert _map("edit", {"oldString": "a"}, d).deny and _map("write", {"filePath": ""}, d).deny


PATCHES = [
    ("*** Begin Patch\n*** Add File: sub/new.txt\n+written\n*** End Patch", ["sub/new.txt"]),            # x5
    ("*** Begin Patch\n*** Update File: a.txt\n*** Move to: b/c.txt\n@@\n-x\n+y\n*** Delete File: d.txt\n*** End Patch",
     ["a.txt", "b/c.txt", "d.txt"]),
    ("<<'EOF'\n*** Begin Patch\n*** Delete File: /abs/z\n*** End Patch\nEOF", ["/abs/z"]),
    (("  *** Begin Patch  \n*** Add File:   s p.txt  \n+a\n+b\n*** Update File: u\n@@ ctx\n x\n*** End of File\n"
      "*** End Patch\n"), ["s p.txt", "u"]),
    ("*** Begin Patch\n*** Add File:\n*** Add File: real\n*** Bogus: x\n*** End Patch", ["real"]),      # 빈 경로는 1.19.5도 건너뛴다
]


@pytest.mark.parametrize("text,want", PATCHES)
def test_apply_patch_paths(text, want):
    assert oc.patch_paths(text) == want


@pytest.mark.parametrize("text", ["", "*** Add File: x\n+y", "*** End Patch\n*** Begin Patch", "*** Begin Patch\n*** End Patch",
                                  "*** Begin Patch\n+x\n*** End Patch", None])
def test_apply_patch_unparsable_denied(text):
    with pytest.raises(oc.PatchError):
        oc.patch_paths(text)
    assert _map("apply_patch", {"patchText": text}, _dir()).deny


def test_apply_patch_maps_each_path_to_write():
    d = _dir()
    m = _map("apply_patch", {"patchText": PATCHES[1][0]}, d)
    assert [e["tool_name"] for e in m.events] == ["Write"] * 3
    assert [e["tool_input"]["file_path"] for e in m.events] == [str(d / "a.txt"), str(d / "b" / "c.txt"), str(d / "d.txt")]
    assert not any(e["tool_name"].startswith("mcp__") for e in m.events)                  # x5: mcp__apply__patch 아님


def test_mcp_longest_prefix_and_all_candidates():
    d = _dir()
    m = _map("corp_jira_update_issue", {"key": "A-1"}, d, ["corp", "corp_jira"])
    assert [e["tool_name"] for e in m.events] == ["mcp__corp_jira__update_issue", "mcp__corp__jira_update_issue"]
    assert m.events[0]["tool_input"] == {"key": "A-1"}
    m = _map("mock-jira_jira_fetch_ticket", {"ticket": "MOCK-1"}, d, ["mock-jira"])
    assert [e["tool_name"] for e in m.events] == ["mcp__mock-jira__jira_fetch_ticket"]
    # OpenCode 이름 정리: `jira.corp` → `jira_corp`
    m = _map("jira_corp_get_issue", {}, d, ["jira.corp"])
    assert [e["tool_name"] for e in m.events] == ["mcp__jira_corp__get_issue"]


@pytest.mark.parametrize("tool,servers", [("corp_jira_x", []), ("frob", ["corp"]), ("corp_", ["corp"]),
                                          ("multiedit", []), ("list", []), ("patch", []), ("todoread", [])])
def test_unknown_tool_or_server_denied(tool, servers):
    m = _map(tool, {}, _dir(), servers)
    assert m.deny and "모르는 도구" in m.deny and m.events == []


def test_builtin_name_shadowed_by_mcp_server_denied():
    m = _map("apply_patch", {"patchText": PATCHES[0][0]}, _dir(), ["apply"])
    assert m.deny and "둘로 읽힌다" in m.deny


def test_mcp_with_unreadable_server_list_denied():
    m = _map("corp_get", {}, _dir(), [], "opencode.json: JSONDecodeError")
    assert m.deny and "MCP 서버 목록" in m.deny
    assert _map("bash", {"command": "ls"}, _dir(), [], "x").deny is None      # 내장 도구는 그대로


def test_missing_directory_denied():
    assert oc.map_tool({"tool": "read", "args": {}}, []).deny
    assert oc.map_tool({"tool": "read", "args": {}, "directory": "rel"}, []).deny


# -- opencode.json 서버 목록 ------------------------------------------------------------------------------


def _env(home: Path) -> dict:
    return {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}


def test_mcp_servers_union_jsonc():
    home, proj = tmp("tt-oc-home-"), _dir()
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".config" / "opencode" / "opencode.jsonc").write_text(
        '// global\n{"mcp": {"glob-srv": {"type": "local"},}, /* c */ "x": "a//b"}', encoding="utf-8")
    (proj / "opencode.json").write_text(json.dumps({"mcp": {"corp_jira": {}, "corp": {}}}), encoding="utf-8")
    (proj / "sub" / ".opencode").mkdir()
    (proj / "sub" / ".opencode" / "opencode.json").write_text('{"mcp": {"deep": {}}}', encoding="utf-8")
    names, err = oc.mcp_servers(str(proj / "sub"), _env(home))
    assert err is None and {"glob-srv", "corp_jira", "corp", "deep"} <= set(names)


@pytest.mark.parametrize("text", ["{not json", '{"mcp": ["a"]}'])
def test_mcp_servers_unreadable_is_error(text):
    home, proj = tmp("tt-oc-home-"), _dir()
    (proj / "opencode.json").write_text(text, encoding="utf-8")
    _names, err = oc.mcp_servers(str(proj), _env(home))
    assert err


# -- 환경변수 --------------------------------------------------------------------------------------------


def test_refused_env():
    assert oc.refused_env({"PATH": "/bin", "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1"}) == []
    env = dict.fromkeys(("OPENCODE_PERMISSION", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG", "OPENCODE_PURE",
                         "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_EXPERIMENTAL_LSP_TOOL", "OPENCODE_EXPERIMENTAL"), "")
    assert oc.refused_env(env) == sorted(env)
    out = oc.before({"tool": "read", "args": {}, "directory": str(_dir())}, env={"OPENCODE_PERMISSION": '{"bash":"allow"}'})
    assert out["decision"] == "deny" and "OPENCODE_PERMISSION" in out["reason"]


# -- guard 다리: 닫힘 실패 --------------------------------------------------------------------------------


def _proc(rc=0, out="", err=""):
    return subprocess.CompletedProcess(["guard"], rc, out, err)


DENY_OUT = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                              "permissionDecisionReason": "[telephony-triage] no"}})


@pytest.mark.parametrize("result,decision", [
    (_proc(0, "", ""), "allow"),
    (_proc(0, "", "[telephony-triage] 경고 하나\n"), "allow"),
    (_proc(0, DENY_OUT), "deny"),
    (_proc(-9, ""), "deny"),                                   # SIGKILL → 거부 (시제품은 허용했다)
    (_proc(1, ""), "deny"),
    (_proc(1, DENY_OUT.replace("deny", "allow")), "deny"),    # 종료 코드≠0이면 allow 출력도 믿지 않는다
    (_proc(0, "not json"), "deny"),
    (_proc(0, json.dumps({"hookSpecificOutput": {"permissionDecision": "maybe"}})), "deny"),
    (_proc(0, json.dumps({"x": 1})), "deny"),
    ("guard.py 시간 초과(30초)", "deny"),
    ("guard.py 실행 실패(OSError)", "deny"),
])
def test_run_guard_fail_closed(monkeypatch, result, decision):
    monkeypatch.setattr(oc, "run_script", lambda *a, **k: result)
    got = oc.run_guard({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/"}, 30)
    assert got.decision == decision, got
    if isinstance(result, subprocess.CompletedProcess) and result.stderr:
        assert got.warnings == ["[telephony-triage] 경고 하나"]


def test_run_script_budget_exhausted():
    assert isinstance(oc.run_script("guard.py", {}, 0), str)


def test_before_any_candidate_deny_wins(monkeypatch):
    seen = []

    def fake(event, timeout, env=None):
        seen.append(event["tool_name"])
        return oc.HookRun("deny" if event["tool_name"] == "mcp__corp__jira_update_issue" else "allow", "r", [])
    monkeypatch.setattr(oc, "run_guard", fake)
    monkeypatch.setattr(oc, "tracker_view", lambda: oc.TrackerView(set(), None, ()))
    out = oc.before({"tool": "corp_jira_update_issue", "args": {}, "directory": str(_dir())}, env={},
                    servers=["corp", "corp_jira"])
    assert out["decision"] == "deny" and seen == ["mcp__corp_jira__update_issue", "mcp__corp__jira_update_issue"]


def test_before_tracker_config_error_denies_mcp(monkeypatch):
    def boom():
        raise RuntimeError("x")
    monkeypatch.setattr(oc, "tracker_view", boom)
    out = oc.before({"tool": "corp_get", "args": {}, "directory": str(_dir())}, env={}, servers=["corp"])
    assert out["decision"] == "deny" and "트래커 설정" in out["reason"]


# -- v1 쓰기 흐름 ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("command", [
    "python3 /p/scripts/db_pr.py publish --job J", "python3 db_pr.py merge --pr 3", "python3 db_pr.py publish --and-merge",
    "python3 skill_patch.py --apply x", "python3 issue_post.py approve --key MOCK-1", "gh pr edit 3 --add-reviewer bob",
    "gh api repos/o/r/pulls/3/requested_reviewers -f reviewers[]=x", "python3 tools/module_eval.py run c1",
    "python3 tools/'module_eval'.py",
])
def test_v1_write_flows_denied_with_exact_command(command):
    d = _dir()
    assert oc.v1_write_flow(command)
    out = oc.before({"tool": "bash", "args": {"command": command, "workdir": "sub"}, "directory": str(d)}, env={},
                    servers=[])
    assert out["decision"] == "deny"
    assert out["reason"].endswith(f"{oc.ASK_PREFIX}cd {d / 'sub'} && {command}")


@pytest.mark.parametrize("command", ["python3 db_pr.py stage --job J", "python3 triage.py run --key MOCK-1",
                                     "python3 issue_post.py render --key MOCK-1", "grep -n publish README.md",
                                     "python3 db_pr.py summary"])
def test_v1_analysis_commands_not_flagged(command):
    assert oc.v1_write_flow(command) is None


# -- guard 다리: 설정된 작업공간(실제 guard.py) ---------------------------------------------------------------

_WS = None


def ws():
    global _WS
    if _WS is None:
        from workspace import Workspace
        _WS = Workspace()
        _WS.json("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA[0],
                               "--search-issues", JIRA[1], "--get-comments", JIRA[2]])
    return _WS


def cli(mode: str, payload: dict, env: dict | None = None, root: Path | None = None) -> dict:
    w = ws()
    proc = run("common/oc_adapter.py", [mode], root=root or w.root, env={**w.env(), **(env or {})}, cwd=w.base,
               stdin=json.dumps(payload, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def bash(command: str, directory: Path, workdir: str | None = None, **kw) -> dict:
    args = {"command": command, **({"workdir": workdir} if workdir is not None else {})}
    return cli("before", {"tool": "bash", "args": args, "directory": str(directory), "sessionID": "s", "callID": "c"}, **kw)


def test_configured_push_by_workdir_denied_and_by_project_dir_too():
    w = ws()
    out = bash("git push origin HEAD:main", w.base, workdir=str(w.clone))
    assert out["decision"] == "deny" and "telephony-triage" in out["reason"] and out["events"] == ["Bash"]
    out = bash("git push origin HEAD:main", w.clone)                      # 프로젝트 디렉토리가 clone
    assert out["decision"] == "deny"
    out = bash("git push origin HEAD:main", w.base)          # 이슈 DB가 아닌 곳: guard는 허용, v1 bash 허용 목록이 막는다
    assert out["decision"] == "deny" and "bash 허용 목록" in out["reason"]


def test_configured_ask_becomes_deny_with_exact_command():
    w = ws()
    out = bash("git push origin feature-x", w.base, workdir=str(w.clone))
    assert out["decision"] == "deny"
    assert out["reason"].endswith(f"{oc.ASK_PREFIX}cd {w.clone.resolve()} && git push origin feature-x")


def test_configured_file_tools_in_clone_denied():
    w = ws()
    rel = os.path.relpath(w.clone / "README.md", w.base)
    out = cli("before", {"tool": "write", "args": {"filePath": rel, "content": "x"}, "directory": str(w.base)})
    assert out["decision"] == "deny" and "규칙 8" in out["reason"]
    patch = f"*** Begin Patch\n*** Update File: {rel}\n@@\n-a\n+b\n*** End Patch"
    out = cli("before", {"tool": "apply_patch", "args": {"patchText": patch}, "directory": str(w.base)})
    assert out["decision"] == "deny" and "규칙 8" in out["reason"]
    out = cli("before", {"tool": "write", "args": {"filePath": "notes.txt", "content": "x"}, "directory": str(w.base)})
    assert out["decision"] == "allow"


def test_configured_raw_read_and_plain_bash():
    w, d = ws(), _dir()
    (d / "job").mkdir()
    (d / "job" / "issue_raw.json").write_text("{}", encoding="utf-8")
    assert bash("cat job/issue_raw.json", d)["decision"] == "deny"
    assert bash("ls -la", w.base)["decision"] == "allow"
    assert cli("before", {"tool": "read", "args": {"filePath": "x"}, "directory": str(w.base)})["decision"] == "allow"


def _jira_payload(tool: str, args: dict, directory: Path) -> dict:
    (directory / "opencode.json").write_text(json.dumps({"mcp": {"mock-jira": {"type": "local", "command": ["x"]}}}),
                                             encoding="utf-8")
    return {"tool": tool, "args": args, "directory": str(directory), "sessionID": "s", "callID": "c"}


def test_jira_gate_closed_denies_reads():
    assert not hasattr(oc, "JIRA_READ_RELEASED")          # 코드 상수 관문은 없다 — 사용자 설정 + 통과 기록(oc_jira_gate)
    d = _dir()
    out = cli("before", _jira_payload("mock-jira_jira_fetch_ticket", {"ticket": "MOCK-1001"}, d))
    assert out["decision"] == "deny" and "관문이 닫혀" in out["reason"] and "config.py set opencode.jira_read open" in out["reason"]
    # 서버 이름에 jira가 든 설정 밖 서버도 같다
    (d / "opencode.json").write_text(json.dumps({"mcp": {"corp-jira": {}}}), encoding="utf-8")
    out = cli("before", {"tool": "corp-jira_get_issue", "args": {}, "directory": str(d)})
    assert out["decision"] == "deny" and "관문이 닫혀" in out["reason"]


def test_jira_gate_open_reads_follow_guard_and_comment_always_denied():
    d, gate = _dir(), {oc.JIRA_GATE_ENV: "open"}
    assert cli("before", _jira_payload("mock-jira_jira_fetch_ticket", {"ticket": "MOCK-1001"}, d), gate)["decision"] == "allow"
    out = cli("before", _jira_payload("mock-jira_jira_move_ticket", {"ticket": "MOCK-1001"}, d), gate)
    assert out["decision"] == "deny" and "규칙 2" in out["reason"]
    out = cli("before", _jira_payload("mock-jira_jira_ticket_add_note", {"ticket": "MOCK-1001", "text": "x"}, d), gate)
    assert out["decision"] == "deny" and "코멘트 게시는 OpenCode v1" in out["reason"]


def test_non_jira_mcp_goes_to_guard():
    d = _dir()
    (d / "opencode.json").write_text(json.dumps({"mcp": {"docs": {}}}), encoding="utf-8")
    assert cli("before", {"tool": "docs_search", "args": {"q": "x"}, "directory": str(d)})["decision"] == "allow"
    assert cli("before", {"tool": "nosrv_search", "args": {}, "directory": str(d)})["decision"] == "deny"


def test_cli_bad_input_fails_closed():
    w = ws()
    for stdin in ("not json", "[1]"):
        proc = run("common/oc_adapter.py", ["before"], root=w.root, env=w.env(), stdin=stdin)
        assert proc.returncode == 0 and json.loads(proc.stdout)["decision"] == "deny"
        proc = run("common/oc_adapter.py", ["after"], root=w.root, env=w.env(), stdin=stdin)
        assert json.loads(proc.stdout)["replace"] == oc.BRIDGE_FAILED
    assert run("common/oc_adapter.py", ["nope"], root=w.root, env=w.env(), stdin="{}").returncode == 2
    proc = run("common/oc_adapter.py", ["env-check"], root=w.root, env={**w.env(), "OPENCODE_PURE": "1"}, stdin="")
    assert "OPENCODE_PURE" in json.loads(proc.stdout)["refused"]


# -- jira_bridge 다리(after) -----------------------------------------------------------------------------


def _issue_blocks(key: str = "MOCK-1001") -> list:
    issue = {"key": key, "fields": {"summary": "데이터 끊김", "description": f"imsi={IMSI} 재부팅하면 잠시 됨",
                                    "status": {"name": "Open"}}}
    return [{"type": "text", "text": json.dumps(issue, ensure_ascii=False)}]


def test_after_masks_jira_read_and_saves_raw_to_file():
    w, d = ws(), _dir()
    raw = w.work / "MOCK-1001" / "issue_raw.json"
    raw.unlink(missing_ok=True)
    payload = {**_jira_payload("mock-jira_jira_fetch_ticket", {"ticket": "MOCK-1001"}, d), "content": _issue_blocks()}
    out = cli("after", payload)
    assert isinstance(out["replace"], str) and IMSI not in out["replace"] and "데이터 끊김" in out["replace"]
    assert IMSI in raw.read_text(encoding="utf-8")


def test_after_non_jira_and_builtin_unchanged():
    d = _dir()
    (d / "opencode.json").write_text(json.dumps({"mcp": {"docs": {}}}), encoding="utf-8")
    assert cli("after", {"tool": "docs_search", "args": {}, "directory": str(d),
                         "content": [{"type": "text", "text": "hello"}]})["replace"] is None
    assert cli("after", {"tool": "bash", "args": {}, "directory": str(d)})["replace"] is None


def test_after_unknown_tool_and_bridge_failure_replaced(monkeypatch):
    d = _dir()
    assert oc.after({"tool": "nosrv_x", "args": {}, "directory": str(d)}, env={}, servers=[])["replace"] == oc.BRIDGE_FAILED
    for result in (_proc(1, ""), _proc(-9, ""), _proc(0, "garbage"), "jira_bridge.py 시간 초과(30초)",
                   _proc(0, json.dumps({"hookSpecificOutput": {"updatedToolOutput": {"x": 1}}}))):
        monkeypatch.setattr(oc, "run_script", lambda *a, _r=result, **k: _r)
        got = oc.after({"tool": "docs_x", "args": {}, "directory": str(d), "content": []}, env={}, servers=["docs"])
        assert got["replace"] == oc.BRIDGE_FAILED, result


def test_after_bridge_error_path_hides_raw():
    """설정을 읽지 못하면(옛 설정 키) jira_bridge가 모든 mcp__ 결과를 오류 문구로 바꾼다 — 다리도 그 글을 그대로 쓴다."""
    home = tmp("tt-oc-legacy-")
    (home / "config.yaml").write_text("jira:\n  mcp_server: mock-jira\n", encoding="utf-8")
    d = _dir()
    payload = {**_jira_payload("mock-jira_jira_fetch_ticket", {"ticket": "MOCK-1001"}, d), "content": _issue_blocks()}
    proc = run("common/oc_adapter.py", ["after"], root=plugin_root(), env={"TELEPHONY_TRIAGE_HOME": home},
               stdin=json.dumps(payload, ensure_ascii=False))
    text = json.loads(proc.stdout)["replace"]
    assert isinstance(text, str) and "원문은 표시하지 않는다" in text and IMSI not in text


# -- 리뷰 수정(계획 I 2단계): bash 허용 목록·보호 경로·apply_patch 경로 글자·막힘 표시 --------------------------------------


def _scripts() -> str:
    return str(ws().root / "scripts")


def test_p0_indirect_issue_db_push_denied():
    """P0: guard는 거부 목록이라 셸 간접 실행을 못 본다(실제 1.19.5에서 스크립트 파일 push가 원격에 닿았다). 허용 목록이 막는다."""
    w, s = ws(), _scripts()
    clone = w.clone.resolve()
    forms = [
        f"printf 'TT_PUBLISH_TOKEN=manual git -C {clone} push origin HEAD:refs/heads/via-script' > p.sh && sh p.sh",
        "sh p.sh", f"bash -c 'git -C {clone} push'",
        f"python3 -c \"import subprocess; subprocess.run(['git', '-C', '{clone}', 'push', 'origin', 'HEAD:refs/heads/x'])\"",
        f"A=pub; python3 {s}/db_pr.py ${{A}}lish --job J",
        f"TT_PUBLISH_TOKEN=manual git -C {clone} push origin HEAD:refs/heads/x",
        "gh api repos/o/r/git/refs -X POST -f ref=refs/heads/x", "env git push", "xargs git push < /dev/null",
        f"git -C {clone} push --no-verify origin HEAD:refs/heads/oc-rv-pushed",
    ]
    for command in forms:
        out = bash(command, w.base)
        assert out["decision"] == "deny" and out["reason"].startswith(oc.MARK), (command, out)


@pytest.mark.parametrize("args,label", [
    (["db_pr.py", '"pub""lish"', "--job", "J"], "db_pr publish"), (["db_pr.py", "merge", "--job", "J"], "db_pr merge"),
    (["db_pr.py", "request-review", "--job", "J"], "request-review"), (["issue_post.py", "approve", "K"], "issue_post approve"),
    (["skill_patch.py", "K", "--appl", "--sha", "x"], "skill_patch --apply"), (["module_eval.py", "run"], "module_eval"),
])
def test_quoted_or_abbreviated_write_flows_print_command(args, label):
    w, s = ws(), _scripts()
    command = f"python3 {s}/{args[0]} {' '.join(args[1:])}"
    out = bash(command, w.base)
    assert out["decision"] == "deny" and label in out["reason"] and out["reason"].endswith(f"{oc.ASK_PREFIX}{command}")


def test_analysis_commands_still_run():
    w, s = ws(), _scripts()
    (w.work).mkdir(parents=True, exist_ok=True)
    (w.work / "notes.txt").write_text("x", encoding="utf-8")
    for command in (f'python3 "{s}/config.py" show 2>&1 | head -20', "ls -la", f"cd {w.work} && cat notes.txt",
                    f"python3 {s}/db_search.py --db {w.clone} \"데이터 끊김\" --limit 3 --brief 2>/dev/null",
                    f"git -C {w.clone} log --oneline -3", "find . -name '*.json'"):
        out = bash(command, w.base)
        assert out["decision"] == "allow", (command, out)


def test_dry_run_stage_reaches_confirmation_screen_without_env_owner():
    """런타임 리뷰 1: OpenCode bash 허용 목록은 `TT_LOCK_OWNER=…` 대입을 받지 않는다(그대로 둔다). analyze `--dry-run`의 stage는
    대입 없는 모양으로 허용되고, 스크립트는 그 작업 디렉토리의 triage-state.json owner로 확인 화면까지 간다(discard도)."""
    w, s = ws(), _scripts()
    job, oc_env = "MOCK-7001", {"TT_RUNTIME": "opencode", "TT_LOCK_OWNER": ""}
    w.plan(job, "p7-analyze-append.plan.json")
    owner = w.db_pr("lock", "acquire", job, "--command", "analyze", "--take-over", env={"TT_LOCK_OWNER": ""})["lock"]["owner"]
    (w.job_dir(job) / "triage-state.json").write_text(json.dumps({"owner": owner}), encoding="utf-8")
    argv = ["stage", w.job_dir(job) / "plan.json", "--wt", w.wt(job), "--branch", f"issue/{job}", "--dry-run",
            "--then-summary"]
    command = f'python3 "{s}/db_pr.py" ' + " ".join(map(str, argv))
    assert bash(command, w.base)["decision"] == "allow"
    out = bash(f"TT_LOCK_OWNER={owner} {command}", w.base)
    # 2차 P2-1: 거부는 그대로, 사유만 "접두를 빼고 같은 명령"(tt-oc가 막힌 호출로 세지 않는 표시로 시작)
    assert out["decision"] == "deny" and out["reason"] == oc.LOCK_OWNER_DENY
    assert out["reason"].startswith(oc.LOCK_OWNER_RETRY) and "접두만 빼고 같은 명령" in out["reason"]
    other = bash(f"FOO=1 {command}", w.base)
    assert other["decision"] == "deny" and "환경변수 대입(`FOO=`)" in other["reason"] and oc.LOCK_OWNER_RETRY not in other["reason"]
    proc = w.run("db_pr.py", argv, env=oc_env, unauth=True)
    assert proc.returncode in (0, 3), proc.stderr
    assert proc.stdout.startswith("## push 전 확인"), proc.stdout[:300]
    assert w.db_pr("discard", w.wt(job), env=oc_env)["discarded"] is True
    assert w.db_pr("lock", "status")["held"] is False


def test_tamper_and_nested_runtime_denied():
    """P1: guard 플러그인 삭제·adapter 수정(다음 세션에 guard 없음), 중첩 opencode/claude(플러그인·설정 deny 우회)."""
    w, s = ws(), _scripts()
    for command in ("rm -f .opencode/plugins/tt-guard.js", f"sed -i 's/deny/allow/' {s}/common/oc_adapter.py",
                    f"python3 -c \"open('{s}/guard.py', 'w').write('')\"", "cp /dev/null opencode.json",
                    "python3 -c \"import json; json.dump({}, open('opencode.json', 'w'))\"",
                    "OPENCODE_PERMISSION='{\"*\":\"allow\"}' opencode run --pure 'cat job/issue_raw.json > LEAK.txt'",
                    "opencode run --pure x", "claude -p x", "node -e 1", "npx opencode-ai run x"):
        out = bash(command, w.base)
        assert out["decision"] == "deny", (command, out)


def test_file_tools_cannot_touch_guard_or_config():
    d = _dir()
    (d / ".opencode" / "plugins").mkdir(parents=True)
    (d / "link").symlink_to(ws().root)
    for path in (str(ws().root / "scripts" / "common" / "oc_adapter.py"), ".opencode/plugins/tt-guard.js", "opencode.json",
                 "sub/AGENTS.md", "tt-oc.json", "link/scripts/guard.py"):
        out = cli("before", {"tool": "write", "args": {"filePath": path, "content": "x"}, "directory": str(d)})
        assert out["decision"] == "deny" and "고치지 않는다" in out["reason"], (path, out)
        patch = f"*** Begin Patch\n*** Add File: {path}\n+x\n*** End Patch"
        assert cli("before", {"tool": "apply_patch", "args": {"patchText": patch}, "directory": str(d)})["decision"] == "deny"
    assert cli("before", {"tool": "write", "args": {"filePath": "sub/notes.txt", "content": "x"},
                          "directory": str(d)})["decision"] == "allow"


def test_apply_patch_path_trim_matches_js():
    """P1: 1.19.5는 JS `.trim()`으로 경로를 다듬는다(U+FEFF를 지운다). Python `str.strip()`은 U+FEFF를 남겨 상대 경로로 읽었다."""
    assert oc.js_trim("\ufeff\xa0 /a \u3000") == "/a" and oc.js_trim("\x1f/a") == "\x1f/a"
    for bad in ("\u200b/abs/x", "a\x1fb", "/abs/\u202ex"):
        with pytest.raises(oc.PatchError):
            oc.patch_paths(f"*** Begin Patch\n*** Add File: {bad}\n+x\n*** End Patch")
    assert oc.patch_paths("*** Begin Patch\n*** Add File: \ufeff/abs/x\n+x\n*** End Patch") == ["/abs/x"]
    assert oc.patch_paths("*** Begin Patch\n*** Add File: \xa0/abs/x\u3000\n+x\n*** End Patch") == ["/abs/x"]
    assert _map("write", {"filePath": "\ufeff/abs/x", "content": "x"}, _dir()).deny


def test_apply_patch_bom_path_into_work_root_denied():
    """리뷰 재현: BOM + work 루트 아래 승인 기록 경로가 허용됐다(BOM 없는 같은 경로는 규칙 2로 거부). 이제 같은 경로로 읽혀 거부."""
    w = ws()
    target = w.work / "K-1" / "post.approved.json"
    patch = f"*** Begin Patch\n*** Add File: \ufeff{target}\n+{{}}\n*** End Patch"
    out = cli("before", {"tool": "apply_patch", "args": {"patchText": patch}, "directory": str(w.base)})
    plain = cli("before", {"tool": "apply_patch", "args": {"patchText": patch.replace("\ufeff", "")},
                           "directory": str(w.base)})
    assert out["decision"] == plain["decision"] == "deny"
    assert out["reason"] == plain["reason"]


def test_every_deny_reason_is_marked():
    """P1: tt-oc는 `[telephony-triage]`로 막힘을 알아본다 — guard 사유를 그대로 넘기는 거부도 표시가 붙어야 한다."""
    w, d = ws(), _dir()
    (d / "job").mkdir()
    (d / "job" / "issue_raw.json").write_text("{}", encoding="utf-8")
    for out in (bash("cat job/issue_raw.json", d), bash("git push origin HEAD:main", w.base, workdir=str(w.clone)),
                cli("before", {"tool": "task", "args": {}, "directory": str(d)})):
        assert out["decision"] == "deny" and out["reason"].startswith(oc.MARK), out


@pytest.mark.parametrize("command,want", [
    ("echo 'a;b|c$d' \"x y\"", [["echo", "a;b|c$d", "x y"]]),
    ("a && b || c | d; e\nf;", [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]),
    ("cat x 2>&1 2>/dev/null </dev/null >/dev/null", [["cat", "x"]]),
    ("echo p'ub'\"lish\"", [["echo", "publish"]]),
])
def test_split_bash_subset(command, want):
    assert oc.split_bash(command) == want


@pytest.mark.parametrize("command", ["echo $HOME", "echo `id`", "echo \"$(id)\"", "cat a*", "echo ~", "echo {a,b}",
                                     "cat x > y", "cat x >> /dev/null", "cat <<EOF", "echo a &", "(cd x)", "echo a\\ b",
                                     "a |", "| a", "&& a", "cat x 3>/dev/null", "echo 'open", "cat x 2>&12", "echo #c", ""])
def test_split_bash_rejects_outside_subset(command):
    with pytest.raises(oc.ShellSubsetError):
        oc.split_bash(command)


def _gh_mcp(tool: str, args: dict) -> dict:
    d = _dir()
    (d / "opencode.json").write_text(json.dumps({"mcp": {"github": {}}}), encoding="utf-8")
    return cli("before", {"tool": f"github_{tool}", "args": args, "directory": str(d)})


def test_before_mcp_merge_ask_is_refused_in_opencode():
    """규칙 11(F1): 대상 인자 이름 변형(`repo_full_name`)의 이슈 DB 병합은 OpenCode에서도 허용되지 않는다(guard는 병합 계열을
    ask로 내고(4-c), OpenCode v1은 ask를 거부로 돌린다)."""
    out = _gh_mcp("merge_pull_request", {"repo_full_name": "mock-org/telephony-issue-db", "pull_number": 3})
    assert out["decision"] == "deny" and "머지" in out["reason"]


def test_before_mcp_merge_without_target_is_not_allowed():
    """규칙 11(F1): 대상 인자가 없는 병합도 guard ask(대상을 보지 않는다) — OpenCode에서는 allow가 아니다."""
    assert _gh_mcp("merge_pull_request", {"pull_number": 3})["decision"] != "allow"
    assert _gh_mcp("list_pull_requests", {})["decision"] == "allow"


def test_before_plugin_script_out_into_clone_denied():
    """규칙 8(F2): 플러그인 스크립트의 `--out`이 clone 안이면 OpenCode에서도 거부."""
    w = ws()
    out = bash(f"python3 {_scripts()}/mask_pii.py safe.txt --out {w.clone}/CONTRIBUTING.md", w.base)
    assert out["decision"] == "deny" and "규칙 8" in out["reason"]


# -- OC-B: config.py 쓰기는 직접 실행·--plugin-root 거부·git 메타데이터·출력은 작업 루트 안 ------------------------------------------


def _py(script: str, *args: str) -> str:
    return f"python3 {oc.SCRIPTS}/{script} " + " ".join(args)


@pytest.fixture
def plugin_config(monkeypatch):
    """이 테스트 프로세스의 `config`는 임시 플러그인 사본에서 불렸다(conftest) — 어댑터가 보는 `oc.SCRIPTS/config.py`로 바꿔 둔다
    (어댑터는 다른 파일의 `config`면 판정하지 않는다, 정정 6)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("config", oc.SCRIPTS / "config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setitem(sys.modules, "config", mod)


CONFIG_RUN_YOURSELF = [   # (인자, 쓰기 흐름에 들 글)
    ("set work_dir /x", "config.py set"), ("set tracker x", "config.py set"), ("set tracker.tools.get_issue x", "config.py set"),
    ("set -- k v", "config.py set"), ("set 'plugin.scripts_path' /x", "config.py set"),
    ("--platform android set k v", "config.py set"), ("set k v --platform android", "config.py set"),
    ("init", "config.py init"), ("init --force", "config.py init"),
    ("set-tracker --server s --get-issue g", "config.py set-tracker"), ("set-tracker --serv s --get-iss g", "config.py set-tracker"),
    ("install-hooks", "config.py install-hooks"), ("install-hooks --db /x", "config.py install-hooks"),
    ("rename-legacy --apply", "config.py rename-legacy"), ("rename-legacy --app", "config.py rename-legacy"),
    ("tracker-candidates --mcp-config f", "config.py tracker-candidates"),
    ("tracker-candidates --opencode-config=f", "config.py tracker-candidates"),
]
CONFIG_UNREADABLE = ["sett k v", "set k", "se k v", "@args.txt", "--platform set k v", ""]
CONFIG_ALLOWED = ["show", "show --keys work_dir", "site-defaults", "check", "check --roots", "doctor", "doctor --format markdown",
                  "gh-status", "rename-legacy", "sync-scripts-path", "tracker-candidates", "tracker-candidates --tools-json f",
                  "--help", "set --help", "set -h"]


@pytest.mark.parametrize("args,label", CONFIG_RUN_YOURSELF)
@pytest.mark.usefixtures("plugin_config")
def test_config_write_subcommands_are_run_yourself(args, label):
    """조각 1: 사용자 config를 쓰거나 지정 파일의 프로그램을 띄우는 config.py 하위 명령은 config.py 자신의 파서로 읽어 직접 실행."""
    v = oc.bash_allowlist(_py("config.py", args), str(_dir()), str(_dir()), {})
    assert v.deny is None and v.flow and label in v.flow, (args, v)


@pytest.mark.parametrize("args", CONFIG_UNREADABLE)
@pytest.mark.usefixtures("plugin_config")
def test_config_unreadable_args_denied(args):
    v = oc.bash_allowlist(_py("config.py", args).rstrip(), str(_dir()), str(_dir()), {})
    assert v.deny == "config.py 인자를 읽지 못해 거부한다" and v.flow is None, (args, v)


@pytest.mark.parametrize("args", CONFIG_ALLOWED)
@pytest.mark.usefixtures("plugin_config")
def test_config_read_subcommands_allowed(args):
    assert oc.bash_allowlist(_py("config.py", args), str(_dir()), str(_dir()), {}) == oc.BashVerdict(), args


@pytest.mark.usefixtures("plugin_config")
def test_config_set_shapes_not_bypassable(tmp_path):
    """조각 1 반증 꼴: python·`..`·`./`·심볼릭 링크·연산자 뒤·개행도 같은 판정."""
    s = oc.SCRIPTS
    (tmp_path / "c.py").symlink_to(s / "config.py")
    for cmd in (f"python {s}/config.py set k v", f"python3 {s}/../scripts/config.py set k v", f"python3 {s}/./config.py set k v",
                f"python3 {tmp_path}/c.py set k v", f"ls && python3 {s}/config.py set k v",
                f"ls; python3 {s}/config.py set k v", f"python3 {s}/config.py set k v | head",
                f"ls\npython3 {s}/config.py set k v"):
        v = oc.bash_allowlist(cmd, str(tmp_path), str(tmp_path), {})
        assert v.flow == "사용자 설정 변경(config.py set)", (cmd, v)
    # 기존 `set opencode.*` 그물과 문구는 그대로(before가 guard보다 먼저 낸다)
    assert oc.v1_write_flow(_py("config.py", "set opencode.jira_read open")).startswith("OpenCode 설정 변경")


@pytest.mark.parametrize("args", ["init --answers a.json", "init --ans=a.json", "--platform android init --answers a.json"])
@pytest.mark.usefixtures("plugin_config")
def test_config_init_answers_is_plain_refusal(args):
    """OC-C (6): `init --answers`는 "직접 실행" 꼴이 아니라 일반 거부 — 모델이 쓴 답 파일을 넣은 명령을 붙여 넣을 명령으로 보이지 않는다.
    tt-oc는 그 거부에서 직접 실행할 명령을 뽑지 않는다(`USER_CMD`)."""
    v = oc.bash_allowlist(_py("config.py", args), str(_dir()), str(_dir()), {})
    assert v.flow is None and "--answers 파일은 모델이 쓴 것" in v.deny and "`config.py init`(대화형)" in v.deny, v
    w = ws()
    out = bash(f"python3 {w.root}/scripts/config.py {args}", w.base)
    assert out["decision"] == "deny" and "--answers 파일은 모델이 쓴 것" in out["reason"] and oc.ASK_PREFIX not in out["reason"]
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("tt_oc_answers", str(REPO / "opencode" / "bin" / "tt-oc"))
    tt = importlib.util.module_from_spec(importlib.util.spec_from_loader("tt_oc_answers", loader))
    loader.exec_module(tt)
    assert tt.USER_CMD.search(out["reason"]) is None


def test_git_safe_env_required_for_git_and_scripts():
    """OC-C (2): tt-oc가 준 git 설정(GIT_SAFE)이 없으면 bash의 git·플러그인 스크립트는 거부(tt-oc 밖에서 시작), 읽기 명령은 그대로.
    시험 헬퍼(`runner.run`)는 어댑터에 GIT_SAFE_ENV를 기본으로 준다(tt-oc의 child_env와 같은 값)."""
    from runner import GIT_SAFE_ENV
    assert oc.git_safe_missing(GIT_SAFE_ENV) is False
    assert GIT_SAFE_ENV["GIT_CONFIG_COUNT"] == str(len(oc.GIT_SAFE)) and all(
        (GIT_SAFE_ENV[f"GIT_CONFIG_KEY_{i}"], GIT_SAFE_ENV[f"GIT_CONFIG_VALUE_{i}"]) == kv for i, kv in enumerate(oc.GIT_SAFE))
    w = ws()
    gone = {"GIT_CONFIG_COUNT": ""}
    for command in (f"git -C {w.clone} log --oneline -1", f"cd {w.clone} && git status", f'python3 "{w.root}/scripts/config.py" show'):
        assert bash(command, w.base)["decision"] == "allow", command
        out = bash(command, w.base, env=gone)
        assert out["decision"] == "deny" and "tt-oc로 시작하지 않았다" in out["reason"] and "tt-oc --project" in out["reason"], out
        assert out["reason"].startswith(oc.MARK)
    assert bash("ls -la", w.base, env=gone)["decision"] == "allow"
    # 사용자 항목 뒤에 붙은 꼴은 통과, 같은 키를 뒤에서 다시 정하거나·깨졌거나·`git -c`(GIT_CONFIG_PARAMETERS)가 정하면 없음으로 본다
    user = {"GIT_CONFIG_COUNT": "3", "GIT_CONFIG_KEY_0": "core.pager", "GIT_CONFIG_VALUE_0": "cat",
            **{f"GIT_CONFIG_{p}_{i + 1}": GIT_SAFE_ENV[f"GIT_CONFIG_{p}_{i}"] for i in range(2) for p in ("KEY", "VALUE")}}
    assert oc.git_safe_missing(user) is False
    assert oc.git_safe_missing({**GIT_SAFE_ENV, "GIT_CONFIG_KEY_1": "SAFE.BAREREPOSITORY", "GIT_CONFIG_VALUE_1": "all"})
    for broken in ({}, {**GIT_SAFE_ENV, "GIT_CONFIG_COUNT": "x"}, {**GIT_SAFE_ENV, "GIT_CONFIG_COUNT": "3"},
                   {**GIT_SAFE_ENV, "GIT_CONFIG_COUNT": "1"},
                   {**GIT_SAFE_ENV, "GIT_CONFIG_PARAMETERS": "'safe.bareRepository'='all'"}):
        assert oc.git_safe_missing(broken), broken


def test_config_call_refuses_foreign_config_module(monkeypatch):
    """정정 6: `sys.modules["config"]`가 플러그인 config.py가 아니면 판정하지 않는다(예외 → main이 거부)."""
    import types
    fake = types.ModuleType("config")
    fake.__file__ = "/elsewhere/config.py"
    monkeypatch.setitem(sys.modules, "config", fake)
    with pytest.raises(ImportError):
        oc._config_call(["show"])


def test_config_call_output_channel_is_one_json():
    """파서 출력(--help)은 버린다: before의 stdout은 JSON 하나."""
    w = ws()
    proc = run("common/oc_adapter.py", ["before"], root=w.root, env=w.env(), cwd=w.base, stdin=json.dumps(
        {"tool": "bash", "args": {"command": f"python3 {w.root}/scripts/config.py set --help"}, "directory": str(w.base)}))
    assert proc.returncode == 0 and json.loads(proc.stdout)["decision"] == "allow"
    assert len(proc.stdout.strip().splitlines()) == 1
    out = bash(f"python3 {w.root}/scripts/config.py set work_dir /x", w.base)
    assert out["decision"] == "deny" and "사용자 설정 변경(config.py set)" in out["reason"] and oc.ASK_PREFIX in out["reason"]


@pytest.mark.usefixtures("plugin_config")
@pytest.mark.parametrize("script", ["config.py doctor", "parse_logcat.py parse x.log", "job_status.py",
                                    "config.py sync-scripts-path"])
@pytest.mark.parametrize("opt", ["--plugin-root X", "--plugin-r=X", "--plu X"])
def test_plugin_root_denied_for_every_script(script, opt):
    """P: `--plugin-root`(줄임말·`=` 꼴, 하위 명령 앞)는 모든 플러그인 스크립트에서 거부."""
    name, *rest = script.split()
    v = oc.bash_allowlist(_py(name, opt, *rest), str(_dir()), str(_dir()), {})
    assert v.deny and "--plugin-root" in v.deny and v.flow is None, v
    assert oc.bash_allowlist(_py("config.py", "doctor"), str(_dir()), str(_dir()), {}) == oc.BashVerdict()


GIT_META = [".git/config", ".GIT/x", "w/K-1/.git", "HEAD", "w/Head", "wt/.githooks/post-index-change", "x/.git/refs/heads/m"]


@pytest.mark.parametrize("path", GIT_META)
def test_file_tools_cannot_write_git_metadata(path):
    """W1: 모델이 만든 `.git`(config의 core.fsmonitor 등)·`.githooks`·`HEAD`는 허용된 git 읽기가 실행으로 잇는다."""
    d = _dir()
    payloads = [{"tool": "write", "args": {"filePath": path, "content": "x"}},
                {"tool": "edit", "args": {"filePath": path, "oldString": "a", "newString": "b"}},
                {"tool": "apply_patch", "args": {"patchText": f"*** Begin Patch\n*** Add File: {path}\n+x\n*** End Patch"}},
                {"tool": "apply_patch", "args": {"patchText": f"*** Begin Patch\n*** Update File: {path}\n@@\n-a\n+b\n*** End Patch"}},
                {"tool": "apply_patch", "args": {"patchText": "*** Begin Patch\n*** Update File: ok.txt\n"
                                                              f"*** Move to: {path}\n@@\n-a\n+b\n*** End Patch"}}]
    for p in payloads:
        out = oc.before({**p, "directory": str(d)}, env={}, servers=[])
        assert out["decision"] == "deny" and "git 메타데이터" in out["reason"] and out["reason"].startswith(oc.MARK), (p, out)


def test_git_metadata_lookalikes_allowed(tmp_path):
    for path in ("w/K-1/headers.txt", ".gitattributes", ".gitignore", "br/config", "w/head.log", "w/git/x"):
        assert oc._git_meta(str(tmp_path / path)) is None, path
    (tmp_path / ".git").mkdir()
    (tmp_path / "lnk").symlink_to(tmp_path / ".git", target_is_directory=True)
    assert oc._git_meta(str(tmp_path / "lnk" / "config"))          # 실제 경로가 .git 아래
    w = ws()
    assert cli("before", {"tool": "write", "args": {"filePath": ".gitignore", "content": "x"},
                          "directory": str(w.base)})["decision"] == "allow"


def _work_tree(tmp_path: Path, meta: bool = True):
    """(프로젝트 폴더, 작업 루트, env). 프로젝트 폴더의 tt-oc.json이 작업 루트를 적는다(gen_opencode install과 같다)."""
    proj, root, home = tmp_path / "proj", tmp_path / "work", tmp_path / "home"
    for x in (proj, root / "K-1", home):
        x.mkdir(parents=True)
    if meta:
        (proj / "tt-oc.json").write_text(json.dumps({"work_root": str(root)}), encoding="utf-8")
    return proj, root, {"HOME": str(home)}


def test_script_outputs_must_stay_in_work_root(tmp_path):
    """W2: 스크립트 출력 인자(`guard._script_out_targets`)는 작업 루트 안. 밖(~/.gitconfig·사용자 site `.pth` 등)이면 거부."""
    proj, root, env = _work_tree(tmp_path)
    home = env["HOME"]
    (root / "lnk").symlink_to(tmp_path / "home", target_is_directory=True)
    denied = [_py("mask_pii.py", "in.txt", "--out", f"{home}/.gitconfig"),
              _py("mask_pii.py", "in.txt", f"--out={home}/.local/lib/python3.12/site-packages/x.pth"),
              _py("mask_pii.py", "in.txt", "--o", f"{root}/../x"), _py("db_review.py", "cat", "--out", "/tmp/x"),
              _py("mask_pii.py", "--in-place", "/outside/f"), _py("jira_fields.py", "extract", "/outside/f", "--consume"),
              _py("parse_logcat.py", "cut", "a.log", "--out", f"{root}/lnk/.bashrc"),           # 실제 경로가 밖
              _py("mask_pii.py", "in.txt", "--out", "x.json")]                                    # cwd(프로젝트 폴더) 기준 밖
    for cmd in denied:
        v = oc.bash_allowlist(cmd, str(proj), str(proj), env)
        assert v.deny and "작업 루트" in v.deny and v.flow is None, (cmd, v)
    for cmd in (_py("mask_pii.py", "in.txt", "--out", f"{root}/K-1/.git/config"), _py("mask_pii.py", "--out", f"{root}/K-1/HEAD")):
        v = oc.bash_allowlist(cmd, str(proj), str(proj), env)
        assert v.deny and "git 메타데이터" in v.deny, (cmd, v)
    allowed = [_py("mask_pii.py", "in.txt", "--out", f"{root}/K-1/x.json"), _py("db_build.py", "--preview", f"{root}/preview-1"),
               _py("jira_fields.py", "extract", f"{root}/K-1/issue_raw.json", "--consume"), _py("db_search.py", "x")]
    for cmd in allowed:
        assert oc.bash_allowlist(cmd, str(proj), str(proj), env) == oc.BashVerdict(), cmd
    # 상대 경로는 모든 cwd 후보 기준: workdir가 작업 루트면 허용, `cd` 뒤면 처음 cwd(프로젝트 폴더) 기준으로도 봐서 거부
    rel = _py("parse_logcat.py", "cut", "a.log", "--out", "K-1/fixtures/cut-1.log")
    assert oc.bash_allowlist(rel, str(root), str(proj), env) == oc.BashVerdict()
    assert "작업 루트" in oc.bash_allowlist(f"cd {root} && {rel}", str(proj), str(proj), env).deny


def test_script_outputs_closed_without_tt_oc_json(tmp_path):
    proj, root, env = _work_tree(tmp_path, meta=False)
    v = oc.bash_allowlist(_py("mask_pii.py", "in.txt", "--out", f"{root}/K-1/x.json"), str(proj), str(proj), env)
    assert v.deny and "tt-oc.json" in v.deny and "판정할 수 없다" in v.deny
    assert oc.bash_allowlist(_py("db_search.py", "x"), str(proj), str(proj), env) == oc.BashVerdict()   # 출력 없는 호출은 그대로
    for text in ("{not json", "[]", "{}", json.dumps({"work_root": "work"}), json.dumps({"work_root": 3})):
        (proj / "tt-oc.json").write_text(text, encoding="utf-8")
        v = oc.bash_allowlist(_py("mask_pii.py", "--out", f"{root}/K-1/x"), str(proj), str(proj), env)
        assert v.deny and "판정할 수 없다" in v.deny and str(proj / "tt-oc.json") in v.deny and "gen_opencode.py install" in v.deny, text


def test_script_outputs_edge_values(tmp_path, monkeypatch):
    """검증 정정(별개 눈): 안/밖은 실제 경로 하나 — symlink를 거친 작업 루트의 정당한 출력은 허용, `없는폴더/../..`는 거부.
    따옴표 `~`, `-`·두 번·빈 값, guard를 못 불러오면 거부(닫힘)."""
    proj, root, env = _work_tree(tmp_path)
    (tmp_path / "wlink").symlink_to(root, target_is_directory=True)
    assert oc.bash_allowlist(_py("mask_pii.py", "--out", f"{tmp_path}/wlink/K-1/x.json"), str(proj), str(proj), env) == oc.BashVerdict()
    (proj / "tt-oc.json").write_text(json.dumps({"work_root": str(tmp_path / "wlink")}), encoding="utf-8")   # 적힌 루트가 symlink
    assert oc.bash_allowlist(_py("mask_pii.py", "--out", f"{root}/K-1/x.json"), str(proj), str(proj), env) == oc.BashVerdict()
    denied = [_py("mask_pii.py", "--out", f"{root}/nodir/../../x"), _py("triage.py", "run", "K-1", "--out", "'~/x'"),
              _py("mask_pii.py", "--out", "-"), _py("mask_pii.py", "--out", f"{root}/K-1/a", "--out", f"{tmp_path}/home/b"),
              _py("mask_pii.py", "--out=")]
    for cmd in denied:
        v = oc.bash_allowlist(cmd, str(proj), str(proj), env)
        assert v.deny and ("작업 루트" in v.deny or "`~`" in v.deny), (cmd, v)
    assert oc.bash_allowlist(_py("mask_pii.py", "--out", "-"), str(root), str(proj), env) == oc.BashVerdict()   # cwd가 루트면 안
    monkeypatch.setitem(sys.modules, "guard", None)                         # import guard → ImportError
    v = oc.bash_allowlist(_py("db_search.py", "x"), str(proj), str(proj), env)
    assert v.deny and "guard를 불러오지 못해" in v.deny


def test_outside_outputs_normcase(tmp_path):
    """작업 루트 비교는 normcase(Windows에서도 돈다): 대소문자 무시 파일 시스템이면 대소문자만 다른 루트도 같은 폴더."""
    proj, root, env = _work_tree(tmp_path)
    words = ["python3", str(oc.SCRIPTS / "mask_pii.py"), "--out", str(root / "K-1" / "x.json")]
    assert oc._outside_outputs(words, [str(proj)], str(proj)) is None
    (proj / "tt-oc.json").write_text(json.dumps({"work_root": str(root).upper() if os.name == "nt" else str(root) + "/"}),
                                     encoding="utf-8")
    assert oc._outside_outputs(words, [str(proj)], str(proj)) is None
    assert "작업 루트" in oc._outside_outputs([*words[:3], str(tmp_path / "workx" / "y")], [str(proj)], str(proj))


@pytest.mark.skipif(sys.platform != "linux", reason="통합 회귀는 리눅스에서(경로·git)")
def test_integration_git_and_gitconfig_writes_refused(tmp_path):
    """통합 회귀: 실제 임시 폴더에서 어댑터 판정대로 했을 때 `.git` 쓰기와 `--out ~/.gitconfig`(HOME은 임시 폴더)는 일어나지 않고,
    작업 루트 안 출력은 실제로 쓰인다."""
    w = ws()
    proj, root, env = _work_tree(tmp_path)
    (root / "K-1" / "in.txt").write_text("hello\n", encoding="utf-8")
    home = Path(env["HOME"])

    def act(payload: dict) -> str:
        out = cli("before", {**payload, "directory": str(proj), "sessionID": "s", "callID": "c"}, env=env)
        if out["decision"] == "allow":
            if payload["tool"] == "write":
                target = Path(payload["args"]["filePath"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(payload["args"]["content"], encoding="utf-8")
            else:
                run_env = {**os.environ, **{k: str(v) for k, v in w.env().items()}, **env, "CLAUDE_PLUGIN_ROOT": str(w.root)}
                subprocess.run(payload["args"]["command"], shell=True, cwd=proj, env=run_env, check=False, capture_output=True)
        return out["decision"]

    fsmonitor = "[core]\n\tfsmonitor = touch PWNED\n"
    assert act({"tool": "write", "args": {"filePath": str(root / "K-1" / "r" / ".git" / "config"), "content": fsmonitor}}) == "deny"
    assert act({"tool": "write", "args": {"filePath": str(root / "K-1" / "r" / ".git" / "HEAD"), "content": "ref: x\n"}}) == "deny"
    assert not (root / "K-1" / "r").exists()
    s = f"{w.root}/scripts"
    assert act({"tool": "bash", "args": {"command": f"python3 {s}/mask_pii.py {root}/K-1/in.txt --out {home}/.gitconfig"}}) == "deny"
    assert not (home / ".gitconfig").exists()
    ok = f"python3 {s}/mask_pii.py {root}/K-1/in.txt --out {root}/K-1/masked.txt"
    assert act({"tool": "bash", "args": {"command": ok}}) == "allow" and (root / "K-1" / "masked.txt").is_file()
