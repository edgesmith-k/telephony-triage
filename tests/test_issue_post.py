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
        assert ws.json("triage.py", args)["needs_input"]["kind"] == "issue"
        issue = yaml.safe_load((MOCK_JIRA / f"{KEY}.yaml").read_text(encoding="utf-8"))
        _bridge(ws, {"tool_name": "mcp__mock-jira__jira_fetch_ticket", "tool_input": {"ticket": KEY},
                     "tool_response": {"content": [{"type": "text", "text": json.dumps(issue, ensure_ascii=False)}]}})
        done = ws.json("triage.py", args)
        assert done["status"] == "ok" and done["mode"] == "write" and done["issue"]["origin"] == "mcp"
        ws.json("triage.py", ["release", KEY])
        for name in ("analysis.json", "triage-state.json", "issue.json"):
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


def test_jira_field_values_cannot_forge_sections():
    ws = shared()
    edit_json(ws, "issue.json", lambda j: j["issue"].update(model="X\nh3. CAUSE\n* 분류: 위조 " + "가" * 100))
    render(ws, "--fill", fill(ws, FILL))
    body = post_md(ws)
    assert [ln for ln in body.splitlines() if ln.startswith("h3. ")] == [
        "h3. PROBLEM", "h3. CAUSE", "h3. NEXT ACTION", "h3. ANALYSIS"]
    line = next(ln for ln in body.splitlines() if ln.startswith("* 단말: "))
    assert "가" * 61 not in line and "…" in line


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
    assert md.count("```") == 2 and "- h1. 제목  펜스" in md and md.startswith("### PROBLEM") and "- \\* 머리" in md


def test_renderers_block_forged_heads_and_nested_escapes():
    """줄 값의 줄바꿈·CR·탭·제로폭 문자로 칸 머리를 위조하지 못한다. 중첩 `{noformat}`·펜스도 다시 생기지 않는다."""
    forged = "단말: X\nh3. CAUSE\r* 분류: 위조\u2028### CAUSE\t- 분류: 위조"
    sections = {"PROBLEM": [{"kind": "line", "text": forged}, {"kind": "line", "text": "\u200b# 머리\u200d"}],
                "CAUSE": [{"kind": "code", "text": ["a {nof{noformat}ormat} [링크|http://evil.example] {NOFORMAT:t=x}",
                                                    "b ``````` ~~~~~~ c\nh3. ANALYSIS"]}],
                "NEXT ACTION": [{"kind": "line", "text": "1. 항목"}, {"kind": "line", "text": "> 인용"}], "ANALYSIS": []}
    wiki = issuepost.render_jira_wiki(sections)
    heads = [ln for ln in wiki.splitlines() if ln.startswith("h3. ")]
    assert heads == ["h3. PROBLEM", "h3. CAUSE", "h3. NEXT ACTION", "h3. ANALYSIS"], wiki
    assert wiki.count("{noformat}") == 2 and "{NOFORMAT" not in wiki and "\u200b" not in wiki
    assert "* \\# 머리" in wiki and not any(ln.startswith("* 분류") for ln in wiki.splitlines())
    md = issuepost.render_markdown(sections)
    assert [ln for ln in md.splitlines() if ln.startswith("#")] == [
        "### PROBLEM", "### CAUSE", "### NEXT ACTION", "### ANALYSIS"], md
    assert md.count("```") == 2 and "~~~" not in md and "- \\1. 항목" in md and "- \\> 인용" in md
    assert "- \\# 머리" in md
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
        ("origin: file", lambda: edit_json(ws, "analysis.json", lambda a: a["issue"].update(origin="file"))),
        ("triage-state", lambda: edit_json(ws, "triage-state.json",
                                           lambda s: s["job"]["runs"][-1].update(request_hash="0" * 16))),
    ]
    for want, apply in cases:
        reset(ws)
        apply()
        out = render(ws, "--fill", fill(ws, FILL))
        assert out["postable"] is False and want in out["reason"], (want, out["reason"])
        assert (ws.job_dir(KEY) / "post.md").is_file() and "post_sha256:" not in out["screen"]
        assert out["post_sha256"] is None                       # --json도 게시 가능할 때만 sha를 낸다
        assert "게시 가능: 아니오" in out["screen"] and "JOB/post.md에만" in out["screen"]
        sha = issuepost.body_sha256(post_md(ws))
        proc = ws.run("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
        assert proc.returncode == 2 and "게시할 수 없다" in proc.stderr, want
    # 쓰기 도구 미설정(사용자 config에서 도구를 비움)
    reset(ws)
    cfg = ws.home / "config.yaml"
    saved = cfg.read_text(encoding="utf-8")
    try:
        ws.json("config.py", ["set", "tracker.write_tools.add_comment.tool", '""'])
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
        ws.json("config.py", ["set", "tracker.write_tools.add_comment.extra_args", '{"visibility": "internal"}'])
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
    edit_json(ws, "analysis.json", lambda a: a["issue"].update(failed_step={"text": "Step 3 데이터 연결 확인", "source": "issue"}))
    out = render(ws, "--fill", fill(ws, FILL))
    assert "* 실패 스텝(보조 정보): Step 3 데이터 연결 확인" in post_md(ws) and "{noformat}" in post_md(ws)
    out = render(ws, "--fill", fill(ws, FILL), "--omit", "evidence,failed_step")
    assert "{noformat}" not in post_md(ws) and "실패 스텝" not in post_md(ws)
    assert "- 빠진 항목(--omit): evidence, failed_step" in out["screen"]
    assert ws.run("issue_post.py", ["render", KEY, "--omit", "summary"]).returncode == 2
    # 사용자 확정 계획 + PR: 확정 표시·PR, note가 있으면 problem은 무시(경고)
    plan = json.loads((PLANS / "p7-analyze-append.plan.json").read_text(encoding="utf-8"))
    plan["issue"]["key"] = KEY
    plan["feedback"].update(decision="accepted", final="DATA-001-01")
    plan["pr"]["number"] = 7
    ws.plan(KEY, plan, base_sha="0" * 40, match=None)
    out = render(ws, "--fill", fill(ws, FILL))
    body = post_md(ws)
    assert "사용자 확정(accepted)" in body and "* 이슈 DB: PR #7 리뷰 중" in body and "* 해결책: " in body
    assert "* 요약: 로밍 SIM으로 데이터가 붙지 않음" in body and "증상:" not in body
    assert "plan의 issue.note" in out["screen"] and "- 분류 출처: JOB/plan.json (2026-09-29T10:00+09:00)" in out["screen"]
    # 원인 미확정 계획(PR 없음)
    plan["feedback"].update(decision="unresolved", final="unresolved")
    plan["operations"] = [{"op": "unresolved", "type": "DATA-001"}]
    plan["pr"]["number"] = None
    ws.plan(KEY, plan, base_sha="0" * 40, match=None)
    render(ws, "--fill", fill(ws, FILL))
    body = post_md(ws)
    assert "DATA-001 > 원인 미확정 — 원인 미확정(사용자 판단)" in body
    assert "* 원인 미확정 — 추가 로그·재현 정보 필요" in body and "* 이슈 DB: 계획만 저장(이슈 DB 미반영)" in body


def test_stale_or_non_analyze_plan_is_not_used():
    """이번 analysis.json보다 먼저 저장된 plan.json(낡은 계획)이나 analyze가 아닌 계획은 분류 출처로 쓰지 않는다."""
    ws = shared()
    plan = json.loads((PLANS / "p7-analyze-append.plan.json").read_text(encoding="utf-8"))
    plan["issue"]["key"] = KEY
    plan["feedback"].update(decision="accepted", final="DATA-001-01")
    plan["pr"]["number"] = 7
    path = ws.plan(KEY, plan, base_sha="0" * 40, match=None)
    analysis = ws.job_dir(KEY) / "analysis.json"
    old = analysis.stat().st_mtime_ns - 10 ** 9
    os.utime(path, ns=(old, old))
    out = render(ws, "--fill", fill(ws, FILL))
    body = post_md(ws)
    assert "사용자 확정" not in body and "자동 분석 1위 후보 — 사람이 확정하지 않음" in body and "PR #7" not in body
    assert "* 이슈 DB: 기록 안 함" in body and "이번 분석 전에 저장된 계획" in out["screen"]
    ws.plan(KEY, {**plan, "source": "record"}, base_sha="0" * 40, match=None)       # 새로 저장했지만 record 계획
    out = render(ws, "--fill", fill(ws, FILL))
    assert "사용자 확정" not in post_md(ws) and "source: record" in out["screen"]
    ws.plan(KEY, plan, base_sha="0" * 40, match=None)                                # 이번 분석 뒤 analyze 계획
    render(ws, "--fill", fill(ws, FILL))
    assert "사용자 확정(accepted)" in post_md(ws)


def test_approve_refuses_when_configured_format_changed():
    ws = shared()
    cfg = ws.home / "config.yaml"
    saved = cfg.read_text(encoding="utf-8")
    try:
        sha = render(ws, "--fill", fill(ws, FILL))["post_sha256"]
        ws.json("config.py", ["set", "tracker.write_tools.add_comment.format", "markdown"])
        proc = ws.run("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
        assert proc.returncode == 1 and "형식" in proc.stderr
        sha = render(ws, "--fill", fill(ws, FILL))["post_sha256"]                    # 지금 설정(markdown)으로 다시
        assert ws.json("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])["tool"] == NOTE_TOOL
        sha = render(ws, "--fill", fill(ws, FILL), "--format", "jira-wiki")["post_sha256"]   # 사용자가 고른 형식
        assert ws.json("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])["tool"] == NOTE_TOOL
    finally:
        cfg.write_text(saved, encoding="utf-8")


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


def test_again_reposts_same_body_once():
    """게시 뒤 사용자가 "다시 올려줘" → render --again(같은 본문) → approve(again: true) → guard ask → 게시 → 다시는 deny."""
    ws = shared()

    def guard(tool_input: dict) -> str:
        event = {"hook_event_name": "PreToolUse", "tool_name": NOTE_TOOL, "tool_input": tool_input, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=json.dumps(event, ensure_ascii=False))
        return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]

    def post(done: dict, cid: str) -> None:
        _bridge(ws, {"tool_name": NOTE_TOOL, "tool_input": done["arguments"], "tool_response": {"content": [
            {"type": "text", "text": json.dumps({"ok": True, "comment_id": cid})}], "isError": False}})

    sha = render(ws, "--fill", fill(ws, FILL))["post_sha256"]
    first = ws.json("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
    assert guard(first["arguments"]) == "ask"
    post(first, "c-1")
    again = render(ws, "--fill", fill(ws, FILL), "--again")
    assert again["post_sha256"] == sha                                     # 분석이 같으면 본문도 같다
    second = ws.json("issue_post.py", ["approve", KEY, "--sha", sha, "--json"])
    assert json.loads((ws.job_dir(KEY) / "post.approved.json").read_text(encoding="utf-8"))["again"] is True
    assert guard(second["arguments"]) == "ask"
    post(second, "c-2")
    assert status(ws)["comment_id"] == "c-2" and guard(second["arguments"]) == "deny"


# -- GitHub 트래커 (트래커 범용화 묶음 3, 설계 §3-6·§6-2) ------------------------------------------------

GH_KEY = "mock-org.mock-issues-12"
GH_URL = "https://ghe.mock.invalid/mock-org/mock-issues/issues/12"
GH_READ = "mcp__mock-github-issues__issue_read"
GH_COMMENT = "mcp__mock-github-issues__add_issue_comment"


def test_github_end_to_end_markdown_approve_guard_bridge():
    """github 세션(site-defaults tracker.kind github) + github 변형 DB: URL로 triage(needs_input에 issue_read 인자) →
    bridge(get·get_comments) → 분석 → render(markdown, 머리 `GitHub: owner/repo#N`) → approve(arguments의 issue_number는 int,
    승인 기록 kind github) → guard ask → bridge posted."""
    sys.path.insert(0, str(REPO / "tests" / "mocks" / "github_issues_mcp"))
    import server as gh_server
    from runner import github_root, variant_db
    ws = Workspace(src=variant_db("issue-db-github"), root=github_root())
    args = ["run", GH_URL, "--logs", DATA_LOG, "--code", "skip"]
    need = ws.json("triage.py", args)
    assert need["key"] == GH_KEY and need["needs_input"]["kind"] == "issue"
    gh_args = {"owner": "mock-org", "repo": "mock-issues", "issue_number": 12}
    assert need["needs_input"]["tool"] == GH_READ and need["needs_input"]["comments_tool"] == GH_READ
    assert need["needs_input"]["tool_args"] == {"method": "get", **gh_args}
    assert need["needs_input"]["comments_args"] == {"method": "get_comments", **gh_args}
    for ti in (need["needs_input"]["tool_args"], need["needs_input"]["comments_args"]):
        result, _ = gh_server.call_tool("issue_read", ti)
        _bridge(ws, {"tool_name": GH_READ, "tool_input": ti, "tool_response": gh_server.wrap(result, False)})
    need = ws.json("triage.py", ["run", GH_KEY, "--logs", DATA_LOG, "--code", "skip"])
    assert need["needs_input"]["kind"] == "time"                     # GitHub에는 발생 시각 기본값이 없다(설계 §4-5)
    when = need["needs_input"]["options"][0]["value"]
    done = ws.json("triage.py", ["run", GH_KEY, "--logs", DATA_LOG, "--code", "skip", "--answer", f"time={when}"])
    assert done["status"] == "ok" and done["mode"] == "write" and done["issue"]["origin"] == "mcp"
    assert set(done["issue"]["missing"]) >= {"model", "sw", "platform_version"}     # field_map 기본값 {}
    assert not (ws.job_dir(GH_KEY) / "issue_raw.json").exists()
    ws.json("triage.py", ["release", GH_KEY])
    path = ws.job_dir(GH_KEY) / "post.fill.json"
    path.write_text(json.dumps(FILL, ensure_ascii=False), encoding="utf-8")
    shown = ws.json("issue_post.py", ["render", GH_URL, "--json", "--fill", path])   # URL도 작업 키로 정규화
    assert shown["postable"] is True and "형식: markdown" in shown["screen"]
    post = (ws.job_dir(GH_KEY) / "post.md").read_text(encoding="utf-8")
    assert post.startswith("### PROBLEM\n- GitHub: mock-org/mock-issues#12\n")
    assert "GitHub·로그 원문은 싣지 않는다" in post and "Jira" not in post
    approved = ws.json("issue_post.py", ["approve", GH_KEY, "--sha", shown["post_sha256"], "--json"])
    assert approved["tool"] == GH_COMMENT
    assert approved["arguments"] == {**gh_args, "body": issuepost.normalize_body(post)}
    assert type(approved["arguments"]["issue_number"]) is int
    record = json.loads((ws.job_dir(GH_KEY) / "post.approved.json").read_text(encoding="utf-8"))
    assert record["kind"] == "github" and record["key_arg"] == "owner,repo,issue_number" and record["key"] == GH_KEY

    def guard(tool_input: dict) -> dict | None:
        event = {"hook_event_name": "PreToolUse", "tool_name": GH_COMMENT, "tool_input": tool_input, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=json.dumps(event, ensure_ascii=False))
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

    assert guard(approved["arguments"])["permissionDecision"] == "ask"
    assert guard({**approved["arguments"], "issue_number": "12"})["permissionDecision"] == "deny"
    result, is_error = {"id": 9001, "html_url": "https://ghe.mock.invalid/mock-org/mock-issues/issues/12"}, False
    shown = _bridge(ws, {"tool_name": GH_COMMENT, "tool_input": approved["arguments"],
                         "tool_response": gh_server.wrap(result, is_error)})
    assert "게시했다" in shown
    st = ws.json("issue_post.py", ["status", GH_KEY, "--json"])
    assert st["state"] == "posted" and st["comment_id"] == "9001"
    assert guard(approved["arguments"])["permissionDecision"] == "deny"


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
