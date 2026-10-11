#!/usr/bin/env python3
"""Jira 결과 게시(코멘트 1건) 본문·승인 (07-workflow.md §Step 9, 08-safety.md §9 규칙 2).

스크립트 이름: issue_post.py issuepost guard.py jira_bridge.py

- `render`: 결정적 칸(스크립트)과 LLM 칸(`post.fill.json`) 분리, fill 검사(basis·길이·TODO·로그 원문 줄·Jira 원문 인용),
  마스킹(남은 식별자 0), 형식 렌더러(jira-wiki·markdown), 같은 입력이면 같은 sha.
- 게시 가능 조건(dry-run·analysis-only·offline·`origin: file`·쓰기 도구 미설정·이미 게시)과 종료 코드.
- `approve`: sha·post.md·request_hash 대조, 승인 기록(600, 30분), 도구 인자 매핑. 다시 render하면 승인 무효.
- 끝에서 끝: 실제 `triage.py run`(Jira는 모의 MCP 응답을 bridge로) → render → approve → guard ask → bridge 결과 → 상태 posted.

`pytest tests/test_issue_post.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from datetime import timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, run, tmp  # noqa: E402
from workspace import Workspace  # noqa: E402

from common import issuepost, masking  # noqa: E402

KEY = "MOCK-1001"
NOTE_TOOL = "mcp__mock-jira__jira_ticket_add_note"
MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
DATA_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
PLANS = REPO / "tests" / "fixtures" / "plans"
POST_FILES = ("post.md", "post.fill.json", "post.render.json", "post.approved.json", "post.result.json", "plan.json")
FILL = {"problem": "LTE는 표시되지만 데이터 통신이 되지 않는다",
        "cause": [{"basis": "log", "text": "사용자 설정 변경 직후 데이터 평가가 DATA_DISABLED로 거부됐다"},
                  {"basis": "code", "text": "설정이 꺼져 있으면 연결을 만들지 않는 분기로 보인다"}],
        "next": ["설정 메뉴에서 모바일 데이터 상태를 확인한다"],
        "code_location": None}

_WS: Workspace | None = None
_SAVED: dict[str, bytes] = {}


def _bridge(ws: Workspace, event: dict) -> str:
    proc = run("jira_bridge.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"] if proc.stdout.strip() else ""


def shared() -> Workspace:
    """Jira를 모의 MCP 응답(bridge)으로 받은 보통 analyze 결과(mode write, origin mcp, dry_run 아님). lock은 푼다."""
    global _WS
    if _WS is None:
        ws = Workspace()
        args = ["run", KEY, "--logs", DATA_LOG, "--code", "skip"]
        assert ws.json("triage.py", args)["needs_input"]["kind"] == "jira"
        issue = yaml.safe_load((MOCK_JIRA / f"{KEY}.yaml").read_text(encoding="utf-8"))
        _bridge(ws, {"tool_name": "mcp__mock-jira__jira_fetch_ticket", "tool_input": {"ticket": KEY},
                     "tool_response": {"content": [{"type": "text", "text": json.dumps(issue, ensure_ascii=False)}]}})
        done = ws.json("triage.py", args)
        assert done["status"] == "ok" and done["mode"] == "write" and done["jira"]["origin"] == "mcp"
        ws.json("triage.py", ["release", KEY])
        for name in ("analysis.json", "triage-state.json", "jira.json"):
            _SAVED[name] = (ws.job_dir(KEY) / name).read_bytes()
        _WS = ws
    reset(_WS)
    return _WS


def reset(ws: Workspace) -> None:
    job = ws.job_dir(KEY)
    for name in POST_FILES:
        (job / name).unlink(missing_ok=True)
    for name, data in _SAVED.items():
        (job / name).write_bytes(data)


def edit_json(ws: Workspace, name: str, func) -> None:
    path = ws.job_dir(KEY) / name
    data = json.loads(path.read_text(encoding="utf-8"))
    func(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def fill(ws: Workspace, doc) -> Path:
    path = ws.job_dir(KEY) / "post.fill.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def render(ws: Workspace, *args, expect=0) -> dict:
    return ws.json("issue_post.py", ["render", KEY, "--json", *args], expect=expect)


def status(ws: Workspace) -> dict:
    return ws.json("issue_post.py", ["status", KEY, "--json"])


def post_md(ws: Workspace) -> str:
    return (ws.job_dir(KEY) / "post.md").read_text(encoding="utf-8")


# -- render ------------------------------------------------------------------------------------


def test_render_without_fill_is_a_draft_with_todo_and_no_hash():
    ws = shared()
    assert status(ws)["state"] == "none"
    out = render(ws)
    assert out["post_sha256"] is None and out["slots_missing"] == ["problem", "cause"] and out["postable"] is True
    assert "TODO(LLM)" in out["screen"] and "post_sha256:" not in out["screen"] and "선택: 승인" not in out["screen"]
    assert not (ws.job_dir(KEY) / "post.md").exists()
    assert status(ws)["state"] == "draft"
    # 기본 출력은 화면 마크다운 그대로
    proc = ws.run("issue_post.py", ["render", KEY])
    assert proc.returncode == 0 and proc.stdout.startswith(f"## Jira 게시 전 확인: {KEY} → 코멘트 1건 ({NOTE_TOOL})")


def test_render_with_fill_writes_post_md_and_hash_line():
    ws = shared()
    out = render(ws, "--fill", fill(ws, FILL))
    assert out["problems"] == [] and out["postable"] is True, out
    body = post_md(ws)
    heads = [ln for ln in body.splitlines() if ln.startswith("h3. ")]
    assert heads == ["h3. PROBLEM", "h3. CAUSE", "h3. NEXT ACTION", "h3. ANALYSIS"]
    analysis = json.loads(_SAVED["analysis.json"])
    for line in analysis["must_show"]:
        assert f"* 주의: {line}" in body                      # must_show 글자 그대로
    code = body.split("{noformat}")[1].strip("\n").splitlines()
    assert 0 < len(code) <= 6 and all(len(ln) <= 160 for ln in code)
    assert "\\[로그로 확인\\] 사용자 설정 변경" in body and "\\[코드로 추정\\]" in body
    assert "* 다음 확인: 설정 메뉴에서 모바일 데이터 상태를 확인한다" in body
    assert "자동 분석 1위 후보 — 사람이 확정하지 않음" in body and "* 이슈 DB: 기록 안 함" in body
    assert "* 코드 위치: 코드 미확인" in body and "Jira·로그 원문은 싣지 않는다" in body
    assert "LTE 표시는 뜨는데" not in body                    # Jira 설명 원문은 싣지 않는다
    sha = issuepost.body_sha256(body)
    lines = out["screen"].rstrip("\n").splitlines()
    assert lines[-1] == f"post_sha256: {sha}" and lines[-2] == "선택: 승인 / 수정 요청 / 취소" and out["post_sha256"] == sha
    assert masking.new_masker().find(body) == []
    assert stat.S_IMODE((ws.job_dir(KEY) / "post.md").stat().st_mode) == 0o600
    assert render(ws, "--fill", fill(ws, FILL))["post_sha256"] == sha      # 결정성
    assert status(ws)["state"] == "rendered"
    md = render(ws, "--fill", fill(ws, FILL), "--format", "markdown")
    assert "### PROBLEM" in post_md(ws) and "[로그로 확인]" in post_md(ws) and md["post_sha256"] != sha


def test_fill_checks_fail_with_exit_1():
    ws = shared()
    log_line = "09-20 14:30:03.000  1234  1250 I DSMGR-0: notifyDataEnabledChanged: enabled=false"
    desc = "LTE 표시는 뜨는데 인터넷이 되지 않습니다. 재부팅하면 잠시 되다가 다시 끊깁니다."
    cases = {
        "basis": {**FILL, "cause": [{"text": "근거 없음"}]},
        "basis-value": {**FILL, "cause": [{"basis": "guess", "text": "x"}]},
        "unknown-key": {**FILL, "status": "Resolved"},
        "todo": {**FILL, "next": ["TODO 나중에"]},
        "log-line": {**FILL, "cause": [{"basis": "log", "text": log_line}]},
        "jira-quote": {**FILL, "problem": desc},
        "too-long": {**FILL, "cause": [{"basis": "log", "text": "가" * 301}]},
        "too-many": {**FILL, "next": ["a", "b", "c", "d"]},
        "newline": {**FILL, "problem": "한 줄\n두 줄"},
        "code-skipped": {**FILL, "code_location": "DataNetworkController.java:120 — enabled 검사"},
        "no-problem": {**FILL, "problem": None},
        "not-object": ["x"],
    }
    for name, doc in cases.items():
        out = render(ws, "--fill", fill(ws, doc), expect=1)
        assert out["problems"] and out["post_sha256"] is None, name
        assert "post_sha256:" not in out["screen"] and not (ws.job_dir(KEY) / "post.md").exists(), name
    assert any("basis" in p for p in render(ws, "--fill", fill(ws, cases["basis"]), expect=1)["problems"])
    assert any("Jira 원문" in p for p in render(ws, "--fill", fill(ws, cases["jira-quote"]), expect=1)["problems"])
    assert any("로그 원문" in p for p in render(ws, "--fill", fill(ws, cases["log-line"]), expect=1)["problems"])
    # 전체 칸 상한: 결정적 내용이 길면 --omit을 안내한다
    edit_json(ws, "analysis.json", lambda a: a.update(must_show=["주의 " + "가" * 150] * 6))
    out = render(ws, "--fill", fill(ws, {**FILL, "cause": [{"basis": "log", "text": "나" * 300}] * 4}), expect=1)
    assert any("상한" in p for p in out["problems"])


def test_masking_llm_slots_continue_existing_tokens():
    ws = shared()
    edit_json(ws, "analysis.json", lambda a: a["candidates"][0]["evidence"][0].update(
        msg=a["candidates"][0]["evidence"][0]["msg"] + " imei=<IMEI#1>"))
    doc = {**FILL, "cause": [{"basis": "log", "text": "단말 IMEI 356938035643809 에서 거부"},
                             {"basis": "log", "text": "발신 sip:+821012345678@ims.mnc001.mcc450.3gppnetwork.org 실패"}],
           "next": ["010-1234-5678 번호로 재현한다"]}
    out = render(ws, "--fill", fill(ws, doc))
    body = post_md(ws)
    assert out["problems"] == [] and "356938035643809" not in body and "<IMEI#2>" in body and "<IMEI#1>" in body
    assert "821012345678" not in body and "1234-5678" not in body
    assert masking.new_masker().find(body) == []


def test_renderers_escape_and_normalized_hash():
    sections = {"PROBLEM": [{"kind": "line", "text": "a [b] {c} |d| !e! \\f"}, {"kind": "line", "text": "* 머리"}],
                "CAUSE": [{"kind": "code", "text": ["x {noformat} y", "```z```"]}],
                "NEXT ACTION": [{"kind": "line", "text": "h1. 제목 ``` 펜스"}], "ANALYSIS": []}
    wiki = issuepost.render_jira_wiki(sections, "꼬리")
    assert "* a \\[b\\] \\{c\\} \\|d\\| \\!e\\! \\\\f" in wiki and "* \\* 머리" in wiki and "* \\h1. 제목" in wiki
    assert wiki.count("{noformat}") == 2 and "x  y" in wiki and wiki.endswith("----\n_꼬리_")
    md = issuepost.render_markdown(sections, "꼬리")
    assert md.count("```") == 2 and "- h1. 제목  펜스" in md and md.startswith("### PROBLEM")
    assert issuepost.body_sha256("a  \r\nb\t\r\n\r\n") == issuepost.body_sha256("\na\nb") == issuepost.body_sha256("a\nb\n")
    assert issuepost.body_sha256("a\nb") != issuepost.body_sha256("a\nb!")


# -- 게시 가능 조건 ------------------------------------------------------------------------------


def test_not_postable_cases_render_0_approve_2():
    ws = shared()
    cases = [
        ("analysis-only", lambda: edit_json(ws, "analysis.json", lambda a: a.update(mode="analysis-only"))),
        ("offline", lambda: edit_json(ws, "analysis.json", lambda a: a.update(mode="offline"))),
        ("--dry-run", lambda: edit_json(ws, "triage-state.json", lambda s: s["job"]["runs"][-1].update(dry_run=True))),
        ("dry-run 여부", lambda: edit_json(ws, "triage-state.json", lambda s: s["job"]["runs"][-1].pop("dry_run"))),
        ("origin: file", lambda: edit_json(ws, "analysis.json", lambda a: a["jira"].update(origin="file"))),
        ("triage-state", lambda: edit_json(ws, "triage-state.json",
                                           lambda s: s["job"]["runs"][-1].update(request_hash="0" * 16))),
    ]
    for want, apply in cases:
        reset(ws)
        apply()
        out = render(ws, "--fill", fill(ws, FILL))
        assert out["postable"] is False and want in out["reason"], (want, out["reason"])
        assert (ws.job_dir(KEY) / "post.md").is_file() and "post_sha256:" not in out["screen"]
        assert "게시 가능: 아니오" in out["screen"] and "JOB/post.md에만" in out["screen"]
        proc = ws.run("issue_post.py", ["approve", KEY, "--sha", out["post_sha256"], "--json"])
        assert proc.returncode == 2 and "게시할 수 없다" in proc.stderr, want
    # 쓰기 도구 미설정(사용자 config에서 도구를 비움)
    reset(ws)
    cfg = ws.home / "config.yaml"
    saved = cfg.read_text(encoding="utf-8")
    try:
        ws.json("config.py", ["set", "jira.write_tools.add_comment.tool", '""'])
        out = render(ws, "--fill", fill(ws, FILL))
        assert out["postable"] is False and "쓰기 도구 미설정" in out["reason"] and "(미설정)" in out["screen"]
        assert status(ws)["tool"] is None
    finally:
        cfg.write_text(saved, encoding="utf-8")


def test_already_posted_needs_again():
    ws = shared()
    (ws.job_dir(KEY) / "post.result.json").write_text(json.dumps(
        {"schema": 1, "status": "posted", "key": KEY, "body_sha256": "x", "posted_at": "2026-10-11T00:00:00+00:00",
         "comment_id": "c-9"}), encoding="utf-8")
    out = render(ws, "--fill", fill(ws, FILL))
    assert out["postable"] is False and "이미 게시함" in out["reason"] and "c-9" in out["reason"]
    again = render(ws, "--fill", fill(ws, FILL), "--again")
    assert again["postable"] is True and again["screen"].rstrip().endswith(again["post_sha256"])
    assert ws.json("issue_post.py", ["approve", KEY, "--sha", again["post_sha256"], "--json"])["tool"] == NOTE_TOOL


# -- approve -------------------------------------------------------------------------------------


def test_approve_checks_and_writes_record():
    ws = shared()
    job = ws.job_dir(KEY)
    out = render(ws, "--fill", fill(ws, FILL))
    sha = out["post_sha256"]
    bad = ws.run("issue_post.py", ["approve", KEY, "--sha", "0" * 64, "--json"])
    assert bad.returncode == 1 and "post_sha256" in bad.stderr
    body = post_md(ws)
    (job / "post.md").write_text(body + "추가\n", encoding="utf-8")
    edited = ws.run("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
    assert edited.returncode == 1 and "post.md" in edited.stderr
    (job / "post.md").write_text(body, encoding="utf-8")
    # 그 사이 재분석(request_hash가 analysis.json·상태 모두 바뀜): 종료 1
    edit_json(ws, "analysis.json", lambda a: a.update(request_hash="1" * 16))
    edit_json(ws, "triage-state.json", lambda s: s["job"]["runs"][-1].update(request_hash="1" * 16))
    moved = ws.run("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
    assert moved.returncode == 1 and "request_hash" in moved.stderr
    reset(ws)
    cfg = ws.home / "config.yaml"
    saved = cfg.read_text(encoding="utf-8")
    try:
        ws.json("config.py", ["set", "jira.write_tools.add_comment.extra_args", '{"visibility": "internal"}'])
        sha = render(ws, "--fill", fill(ws, FILL))["post_sha256"]
        done = ws.json("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
    finally:
        cfg.write_text(saved, encoding="utf-8")
    assert done["tool"] == NOTE_TOOL and done["body_sha256"] == sha
    assert done["arguments"] == {"ticket": KEY, "text": issuepost.normalize_body(post_md(ws)), "visibility": "internal"}
    record = json.loads((job / "post.approved.json").read_text(encoding="utf-8"))
    assert {k: record[k] for k in ("schema", "key", "tool", "key_arg", "body_sha256", "format", "used_at")} == {
        "schema": 1, "key": KEY, "tool": NOTE_TOOL, "key_arg": "ticket", "body_sha256": sha, "format": "jira-wiki",
        "used_at": None}
    assert issuepost.parse_iso(record["expires_at"]) - issuepost.parse_iso(record["approved_at"]) == timedelta(minutes=30)
    assert stat.S_IMODE((job / "post.approved.json").stat().st_mode) == 0o600
    assert status(ws)["state"] == "approved"
    render(ws, "--fill", fill(ws, FILL))                     # 다시 그리면 승인은 무효
    assert not (job / "post.approved.json").exists()


def test_omit_and_plan_classification():
    ws = shared()
    edit_json(ws, "analysis.json", lambda a: a["jira"].update(failed_step={"text": "Step 3 데이터 연결 확인", "source": "jira"}))
    out = render(ws, "--fill", fill(ws, FILL))
    assert "* 실패 스텝(보조 정보): Step 3 데이터 연결 확인" in post_md(ws) and "{noformat}" in post_md(ws)
    out = render(ws, "--fill", fill(ws, FILL), "--omit", "evidence,failed_step")
    assert "{noformat}" not in post_md(ws) and "실패 스텝" not in post_md(ws)
    assert "- 빠진 항목(--omit): evidence, failed_step" in out["screen"]
    assert ws.run("issue_post.py", ["render", KEY, "--omit", "summary"]).returncode == 2
    # 사용자 확정 계획 + PR: 확정 표시·PR, note가 있으면 problem은 무시(경고)
    plan = json.loads((PLANS / "p7-analyze-append.plan.json").read_text(encoding="utf-8"))
    plan["jira"]["key"] = KEY
    plan["feedback"].update(decision="accepted", final="DATA-001-01")
    plan["pr"]["number"] = 7
    ws.plan(KEY, plan, base_sha="0" * 40, match=None)
    out = render(ws, "--fill", fill(ws, FILL))
    body = post_md(ws)
    assert "사용자 확정(accepted)" in body and "* 이슈 DB: PR #7 리뷰 중" in body and "* 해결책: " in body
    assert "* 요약: 로밍 SIM으로 데이터가 붙지 않음" in body and "증상:" not in body
    assert "plan의 jira.note" in out["screen"] and "- 분류 출처: JOB/plan.json (2026-09-29T10:00+09:00)" in out["screen"]
    # 원인 미확정 계획(PR 없음)
    plan["feedback"].update(decision="unresolved", final="unresolved")
    plan["operations"] = [{"op": "unresolved", "type": "DATA-001"}]
    plan["pr"]["number"] = None
    ws.plan(KEY, plan, base_sha="0" * 40, match=None)
    render(ws, "--fill", fill(ws, FILL))
    body = post_md(ws)
    assert "DATA-001 > 원인 미확정 — 원인 미확정(사용자 판단)" in body
    assert "* 원인 미확정 — 추가 로그·재현 정보 필요" in body and "* 이슈 DB: 계획만 저장(이슈 DB 미반영)" in body


def test_usage_errors_exit_2():
    ws = shared()
    assert ws.run("issue_post.py", ["render", "../MOCK-1001"]).returncode == 2
    assert ws.run("issue_post.py", ["render", "MOCK-9999"]).returncode == 2          # analysis.json 없음
    assert ws.json("issue_post.py", ["status", "MOCK-9999", "--json"])["state"] == "none"
    nohome = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}
    proc = ws.run("issue_post.py", ["status", KEY], env=nohome)
    assert proc.returncode == 2 and "사용자 config" in proc.stderr


# -- 끝에서 끝 ------------------------------------------------------------------------------------


def test_end_to_end_approve_guard_ask_bridge_posted():
    ws = shared()
    sha = render(ws, "--fill", fill(ws, FILL))["post_sha256"]
    done = ws.json("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])

    def guard(tool_input: dict) -> dict | None:
        event = {"hook_event_name": "PreToolUse", "tool_name": done["tool"], "tool_input": tool_input, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=json.dumps(event, ensure_ascii=False))
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

    out = guard(done["arguments"])
    assert out["permissionDecision"] == "ask" and sha[:12] in out["permissionDecisionReason"]
    changed = dict(done["arguments"], text=done["arguments"]["text"] + "\n* 끼워 넣기")
    assert guard(changed)["permissionDecision"] == "deny"
    shown = _bridge(ws, {"tool_name": done["tool"], "tool_input": done["arguments"],
                         "tool_response": {"content": [{"type": "text", "text": json.dumps(
                             {"ok": True, "ticket": KEY, "comment_id": "mock-c-1"})}], "isError": False}})
    assert "게시했다" in shown
    st = status(ws)
    assert st["state"] == "posted" and st["comment_id"] == "mock-c-1" and st["postable"] is False
    assert guard(done["arguments"])["permissionDecision"] == "deny"      # 1회용
    assert render(ws, "--fill", fill(ws, FILL))["postable"] is False      # 이미 게시함


def _all_tests():
    return [(name, func) for name, func in sorted(globals().items()) if name.startswith("test_") and callable(func)]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {exc}")
    os._exit(1 if failures else 0)
