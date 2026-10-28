#!/usr/bin/env python3
"""Jira 응답 형식별 처리 (`jira_bridge.py` `_payload`, 사내 피드백 11: 헤드리스 record의 코멘트 도구 ScannerError).

- `_payload`는 형식 오류로 예외를 내지 않는다: structuredContent → 텍스트 블록마다 JSON → 전체 JSON → JSONL →
  `key`·`fields`·`comments` 키가 있는 YAML 객체 → 텍스트. 코멘트 본문 같은 자유 텍스트(`:`·탭·`@`·백틱·`%`)는 YAML로 읽지 않는다.
- hook(get_comments): 자유 텍스트는 코멘트 1건(`comments_format: text`)으로 저장하고 모델에는 마스킹 요약만.
  JSON 블록 여러 개·JSONL은 코멘트 목록으로 저장한다.
- hook(get_issue): 자유 텍스트는 저장하지 않고 응답 모양(내용 없음)만 알린다.
- hook(add_comment 게시 결과): `isError`가 아니면 읽기 형식 순서를 쓰지 않는다(`_post_payload` — JSON, 아니면 YAML). `error:` YAML
  객체는 실패(승인 유지), YAML로 못 읽는 텍스트는 결과 불명(`unknown`·`used_at`), `id:` YAML 객체는 comment id, `isError`는 항상 실패.
  실패 기록 `error`는 json.dumps한 글 하나를 마스킹한다(키 문맥 유지, 제어 문자 이스케이프는 `|`로 — 줄바꿈·탭 뒤 식별자).
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
from common import issuepost  # noqa: E402

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


def test_bridge_issue_free_text_is_refused_with_shape_only():
    home = _home()
    text = f"MOCK-1001 데이터 안 됨: setup: failed imsi={IMSI}"
    shown = _hook(home, ISSUE_TOOL, _blocks(text))
    assert "JSON이 아니라 저장하지 않았다(형식: text, structuredContent 없음, 텍스트 블록 1" in shown
    assert "tracker.tools.get_issue" in shown
    assert IMSI not in shown and "데이터 안 됨" not in shown and "setup" not in shown
    assert not (home / "work" / "MOCK-1001").exists()


# -- 게시 결과(add_comment) ---------------------------------------------------------------------------------------


NOTE_TOOL = "mcp__mock-jira__jira_ticket_add_note"
POST_BODY = "h3. PROBLEM\n* Jira: MOCK-1001"


def _post(text: str, is_error: bool = False) -> tuple[str, dict, dict, str]:
    """승인 기록을 두고 텍스트 블록 하나로 게시 결과 hook → (모델에 보인 글, 결과 기록, 승인 기록, stderr)."""
    home = _home()
    job = home / "work" / "MOCK-1001"
    job.mkdir(parents=True)
    approved = {"schema": 1, "key": "MOCK-1001", "tool": NOTE_TOOL, "key_arg": "ticket", "kind": "jira",
                "body_sha256": issuepost.body_sha256(POST_BODY), "approved_at": "2026-10-11T00:00:00+00:00",
                "expires_at": "2026-10-11T00:30:00+00:00", "used_at": None}
    (job / issuepost.APPROVED_FILE).write_text(json.dumps(approved), encoding="utf-8")
    response = {**_blocks(text), **({"isError": True} if is_error else {})}
    event = {"hook_event_name": "PostToolUse", "tool_name": NOTE_TOOL,
             "tool_input": {"ticket": "MOCK-1001", "text": POST_BODY}, "tool_response": response}
    proc = run("jira_bridge.py", [], root=plugin_root(), env={"TELEPHONY_TRIAGE_HOME": home},
               stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr

    def read(name: str) -> dict:
        return json.loads((job / name).read_text(encoding="utf-8"))

    shown = json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"]
    return shown, read(issuepost.RESULT_FILE), read(issuepost.APPROVED_FILE), proc.stderr


@pytest.mark.parametrize("text,is_error,status,comment_id,said", [
    (f"error: permission denied imsi={IMSI}", False, "error", None, "게시 실패"),        # YAML 객체의 error 값: 실패, 승인 유지
    ("Error: Issue does not exist: MOCK-1001", False, "unknown", None, "게시는 됐을 수 있다"),  # YAML 오류: 결과 불명(fail-closed)
    ("id: 10001\nbody: ok", False, "posted", "10001", "comment 10001"),                   # YAML 객체의 id: comment id
    ("Error: Issue does not exist: MOCK-1001", True, "error", None, "게시 실패"),         # isError는 형식과 상관없이 실패
])
def test_bridge_post_text_result_is_read_as_json_or_yaml(text, is_error, status, comment_id, said):
    """게시 결과는 읽기 형식 순서(`_payload`)를 쓰지 않는다: JSON이 아니면 YAML로 읽고, YAML로도 못 읽으면 처리 중 예외.
    `isError`면 형식과 상관없이 실패로 남기고 승인을 소모하지 않는다."""
    shown, result, approved, stderr = _post(text, is_error)
    assert result["status"] == status and result.get("comment_id") == comment_id and said in shown, shown
    assert bool(approved["used_at"]) is (status != "error")                              # 실패 응답만 승인을 남긴다
    assert IMSI not in shown + stderr + json.dumps(result) and "does not exist" not in shown + stderr
    if status == "error" and not is_error:
        assert "permission denied" in result["error"]                                      # 마스킹된 error 값


@pytest.mark.parametrize("text,is_error,token,raws", [
    (f"Error: add failed\n{IMSI}", True, "<IMSI#", [IMSI]),                                  # 자유 텍스트 → {"text": …}: 줄바꿈 뒤 식별자
    (f"Error: add failed\t{IMSI}", True, "<IMSI#", [IMSI]),                                  # 탭 뒤
    (json.dumps({"error": {"message": f"add failed\n{IMSI}"}}), False, "<IMSI#", [IMSI]),    # 중첩 error 값의 줄바꿈 뒤
    (json.dumps({"message": "auth failed", "token": "10.20.30.40/ghp_abcdefghijklmnop1234"}), True, "<CRED#",
     ["10.20.30.40", "ghp_abcdefghijklmnop1234"]),                                            # 키 문맥: IP로 시작하는 token 값 통째로
    (json.dumps({"error": {"password": "mock.user@example.com:Hunter2Secret"}}), False, "<CRED#",
     ["mock.user@example.com", "Hunter2Secret"]),                                             # 이메일로 시작하는 password 값 통째로
])
def test_bridge_post_error_detail_masks_escapes_and_keyed_values(text, is_error, token, raws):
    """실패 기록 `error`는 json.dumps한 글 하나를 마스킹한다: 제어 문자 이스케이프 뒤 식별자를 놓치지 않고, `token`·`password`
    값은 앞부분이 다른 식별자(IP·이메일)여도 키 문맥으로 통째로 가린다. 승인은 소모하지 않는다."""
    shown, result, approved, stderr = _post(text, is_error)
    assert result["status"] == "error" and approved["used_at"] is None and "게시 실패" in shown
    assert token in result["error"] and not any(r in result["error"] + shown + stderr for r in raws), result["error"]


def test_mask_detail_reads_json_escapes_left_to_right():
    """`_mask_detail`: 이스케이프한 역슬래시 뒤 `n`은 줄바꿈이 아니다(그대로), 제어 문자는 `|`, 이스케이프한 따옴표는 풀린다."""
    detail = {"path": "C:\\new", "t": "a\nb", "q": "say \"hi\""}
    assert jira_bridge._mask_detail(detail) == '{"path": "C:\\\\new", "t": "a|b", "q": "say "hi""}'
