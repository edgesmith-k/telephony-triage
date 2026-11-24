#!/usr/bin/env python3
"""Jira 응답 형식별 처리 (`jira_bridge.py` `_payload`, 사내 피드백 11: 헤드리스 record의 코멘트 도구 ScannerError).

- `_payload`는 예외를 내지 않는다: structuredContent → 텍스트 블록마다 JSON → 전체 JSON → JSONL →
  `key`·`fields`·`comments` 키가 있는 YAML 객체 → 텍스트. 코멘트 본문 같은 자유 텍스트(`:`·탭·`@`·백틱·`%`)는 YAML로 읽지 않는다.
- hook(get_comments): 자유 텍스트는 코멘트 1건(`comments_format: text`)으로 저장하고 모델에는 마스킹 요약만.
  JSON 블록 여러 개·JSONL은 코멘트 목록으로 저장한다.
- hook(get_issue): 자유 텍스트는 저장하지 않고 응답 모양(내용 없음)만 알린다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import plugin_root, run, tmp  # noqa: E402

import jira_bridge  # noqa: E402

IMSI = "450081234567890"
COMMENTS_TOOL = "mcp__mock-jira__jira_ticket_comments"
ISSUE_TOOL = "mcp__mock-jira__jira_fetch_ticket"
FREE_TEXTS = [
    "Comment by mock-user: setup: failed at 10:00",
    "mock-user\t2026-10-18\tradio: off",
    "@mock-lead 확인 부탁: APN 설정",
    "`setupDataCall` 실패: cause=0x1a",
    "%TEMP% 아래 로그 확인: bugreport.zip",
    "- author: mock-user\n  body: radio: off",
    f"Comment by mock-user: setup: failed\n\t@mock-lead: %TEMP% 확인 `imsi={IMSI}`",
]


def _blocks(*texts: str) -> dict:
    return {"content": [{"type": "text", "text": t} for t in texts]}


@pytest.mark.parametrize("text", FREE_TEXTS)
def test_free_text_is_text_not_yaml_error(text):
    for response in (text, _blocks(text)):
        data, shape = jira_bridge._payload(response)
        assert shape == "text" and data == {"text": text}


def test_payload_shapes():
    issue = {"key": "MOCK-1001", "fields": {"summary": "s"}}
    c1, c2 = {"body": "a: b: c"}, {"body": "@x\t%TEMP%"}
    cases = [
        ({"structuredContent": issue, "content": []}, issue, "structured"),
        (json.dumps(issue), issue, "json"),
        (_blocks(json.dumps(issue)), issue, "json"),
        (_blocks(json.dumps(issue)[:10], json.dumps(issue)[10:]), issue, "json"),       # 큰 JSON을 나눠 보낸 블록
        (_blocks(json.dumps(c1), json.dumps(c2)), [c1, c2], "json-blocks×2"),
        (_blocks(json.dumps([c1]), json.dumps([c2])), [c1, c2], "json-blocks×2"),           # 배열 블록은 펼친다
        (json.dumps(c1) + "\n" + json.dumps(c2) + "\n", [c1, c2], "jsonl"),
        (_blocks(json.dumps(c1) + "\n" + json.dumps(c2)), [c1, c2], "jsonl"),
        ("key: MOCK-1001\nfields:\n  summary: s\n", issue, "yaml"),
        ("comments: [unclosed", {"text": "comments: [unclosed"}, "text"),              # YAMLError는 텍스트로
        ("summary: s\nother: x", {"text": "summary: s\nother: x"}, "text"),            # 키 없는 YAML 객체는 텍스트
        ("- a\n- b", {"text": "- a\n- b"}, "text"),
        ("42", {"text": "42"}, "text"),
        (_blocks(), {"text": ""}, "text"),
        ({"key": "MOCK-1001"}, {"key": "MOCK-1001"}, "object"),
    ]
    for response, want, shape in cases:
        assert jira_bridge._payload(response) == (want, shape), response


def test_shape_note_has_no_content():
    note = jira_bridge._shape_note(_blocks(f"secret imsi={IMSI}", "x"))
    assert note == "형식: text, structuredContent 없음, 텍스트 블록 2, 첫 글자 글자, 28자"
    assert "secret" not in note and IMSI not in note
    assert jira_bridge._shape_note(object()).startswith("형식: ")


# -- hook ---------------------------------------------------------------------------------------------------------


def _home() -> Path:
    home = tmp("tt-bridge-fmt-")
    (home / "config.yaml").write_text(f"work_dir: {(home / 'work').as_posix()}\n", encoding="utf-8")
    return home


def _hook(home: Path, tool: str, response) -> str:
    event = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": {"ticket": "MOCK-1001"},
             "tool_response": response}
    proc = run("jira_bridge.py", [], root=plugin_root(), env={"TELEPHONY_TRIAGE_HOME": home},
               stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    assert "Error" not in proc.stderr and IMSI not in proc.stderr, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"]


def test_bridge_comments_free_text_is_saved_not_scanner_error():
    home = _home()
    raw_path = home / "work" / "MOCK-1001" / "issue_raw.json"
    text = FREE_TEXTS[-1]
    shown = _hook(home, COMMENTS_TOOL, _blocks(text))
    assert "Error" not in shown and "처리 실패" not in shown and IMSI not in shown
    assert "텍스트 한 덩어리를 코멘트 1건으로 저장했다(형식: text," in shown
    saved = json.loads(raw_path.read_text(encoding="utf-8"))
    assert saved["comments"] == [{"body": text}] and saved["comments_format"] == "text"
    brief = json.loads(shown.split("\n", 1)[1])
    assert brief["comments_total"] == 1 and "@mock-lead" in brief["last_comments"][0]

    # JSON 블록 여러 개·JSONL: 코멘트 목록으로 저장(text 표시는 지운다)
    c1, c2 = {"body": "setup: failed"}, {"body": f"radio: off imsi={IMSI}"}
    for response in (_blocks(json.dumps(c1), json.dumps(c2)), json.dumps(c1) + "\n" + json.dumps(c2)):
        shown = _hook(home, COMMENTS_TOOL, response)
        saved = json.loads(raw_path.read_text(encoding="utf-8"))
        assert saved["comments"] == [c1, c2] and "comments_format" not in saved
        assert "텍스트 한 덩어리" not in shown and IMSI not in shown
        assert json.loads(shown.split("\n", 1)[1])["comments_total"] == 2

    # 이어서 get_issue(JSON)를 받으면 텍스트 코멘트 표시도 같이 남는다
    _hook(home, COMMENTS_TOOL, text)
    _hook(home, ISSUE_TOOL, json.dumps({"key": "MOCK-1001", "fields": {"summary": "데이터 안 됨"}}, ensure_ascii=False))
    saved = json.loads(raw_path.read_text(encoding="utf-8"))
    assert saved["fields"]["summary"] == "데이터 안 됨" and saved["comments_format"] == "text"


def test_bridge_keeps_comment_page_total_for_clue_extraction():
    """코멘트 도구 응답의 전체 수·건너뛴 수를 `comments_page`로 남긴다(같은 출처 — jira_fields가 일부만 읽었는지 본다). 뒤이은
    get_issue에도 남고, 자유 텍스트 응답(전체 수 모름)이면 지운다."""
    home = _home()
    raw_path = home / "work" / "MOCK-1001" / "issue_raw.json"
    page = {"startAt": 0, "total": 2, "comments": [{"body": "a", "created": "2026-11-14T11:00:00+0900"},
                                                   {"body": "b", "created": "2026-11-14T10:00:00+0900"}]}
    _hook(home, COMMENTS_TOOL, json.dumps(page))
    assert json.loads(raw_path.read_text(encoding="utf-8"))["comments_page"] == {"startAt": 0, "total": 2}
    _hook(home, ISSUE_TOOL, json.dumps({"key": "MOCK-1001", "fields": {"summary": "s"}}))
    saved = json.loads(raw_path.read_text(encoding="utf-8"))
    assert saved["comments_page"] == {"startAt": 0, "total": 2}
    import jira_fields
    cfg = {"tracker": {"kind": "jira", "timezone": "Asia/Seoul"}, "logcat": {"timezone": "Asia/Seoul"}}
    text = jira_fields.extract(saved, cfg, None, "mcp")["text"]
    assert text["comments"] == ["b", "a"] and not any(k in text for k in ("comments_partial", "comments_unchecked"))   # 작성 순
    _hook(home, COMMENTS_TOOL, "자유 텍스트 코멘트")
    assert "comments_page" not in json.loads(raw_path.read_text(encoding="utf-8"))


def test_bridge_issue_free_text_is_refused_with_shape_only():
    home = _home()
    text = f"MOCK-1001 데이터 안 됨: setup: failed imsi={IMSI}"
    shown = _hook(home, ISSUE_TOOL, _blocks(text))
    assert "JSON이 아니라 저장하지 않았다(형식: text, structuredContent 없음, 텍스트 블록 1" in shown
    assert "tracker.tools.get_issue" in shown
    assert IMSI not in shown and "데이터 안 됨" not in shown and "setup" not in shown
    assert not (home / "work" / "MOCK-1001").exists()


@pytest.mark.parametrize("tool,response", [
    (ISSUE_TOOL, {"error": "Issue does not exist or you do not have permission to see it."}),
    (ISSUE_TOOL, {"errorMessages": ["Issue does not exist"], "errors": {}}),
    (COMMENTS_TOOL, {"error": "not found", "key": "MOCK-1001"}),
])
def test_bridge_error_shaped_response_is_not_saved_as_issue(tool, response):
    """오류를 정상 결과로 준 MCP(사내 A589: 없는 키의 원문이 `{error}`뿐인데 '읽힌 이슈'로 저장됐다): 저장하지 않고 자체 문구만."""
    home = _home()
    shown = _hook(home, tool, json.dumps(response))
    assert shown.startswith("telephony-triage: Jira가 오류 응답을 돌려줘 저장하지 않았다(키 ")
    assert "does not exist" not in shown and "not found" not in shown
    assert not (home / "work" / "MOCK-1001").exists()


def test_bridge_error_like_key_inside_real_issue_is_still_saved():
    home = _home()
    shown = _hook(home, ISSUE_TOOL, json.dumps({"key": "MOCK-1001", "fields": {"summary": "s"}, "errors": {}}))
    assert shown.startswith("telephony-triage: Jira 응답 원문은 파일로만 저장했다")
    assert (home / "work" / "MOCK-1001" / "issue_raw.json").is_file()


def test_brief_cut_never_leaves_token_piece():
    """요약 200자·설명 400자·코멘트 자름이 토큰 가운데를 끊으면 `<CRED` 조각이 다시 값으로 잡혔다(사내 A589)."""
    from common import masking
    for n in range(186, 200):
        head = "x" * n
        home = _home()
        desc = head + " password=hunter2secret " + head + f" imsi={IMSI} tail"
        shown = _hook(home, ISSUE_TOOL, json.dumps({"key": "MOCK-1001", "fields": {"summary": desc, "description": desc}}))
        brief = json.loads(shown.split("\n", 1)[1])
        for field in ("summary", "description"):
            assert masking.residual(brief[field], log_lines=False) == {}, (n, field, brief[field][-30:])
    assert masking.clip("ab <CRED#12>", 8) == "ab " and masking.clip("ab <CRED#12>", 12) == "ab <CRED#12>"
    assert masking.clip("a <HEXDUMP 12B>", 9) == "a " and masking.clip("a < b", 4) == "a < "
