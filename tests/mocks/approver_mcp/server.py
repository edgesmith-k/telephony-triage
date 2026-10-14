#!/usr/bin/env python3
"""스킬 eval용 권한 확인 응답 MCP 서버 (stdio JSON-RPC) — 서버 이름 `eval-approver`, 도구 `approve`·`ask_user`.

`claude -p --permission-prompt-tool mcp__eval-approver__approve`로 붙인다. guard hook이 `ask`를 낸 호출
(예: `db_pr.py publish`, 규칙 7)은 실제 사용자라면 권한 확인 창에서 승인한다. `-p`에는 사람이 없으므로 이 서버가
대신 **허용**하고, 무엇을 물었는지 `MOCK_APPROVALS_LOG`(JSON 배열)에 남긴다. 확인 화면을 보여주고 승인받았는지는
채점기가 transcript로 따로 본다 — 이 서버는 "권한 확인이 요청됐다"는 사실만 기록한다.

`EVAL_APPROVER_DENY=1`이면 거부한다(거부 경로 시험용). MCP SDK에 의존하지 않는다.

`ask_user`(plugin 모드 실행자 전용): 실제 사용자에게 묻는 자리(스킬의 "묻는다"·선택지·확인 화면)에서 실행자가 질문 문구를
그대로 넘긴다. 헤드리스 실행자는 글을 거의 쓰지 않고 도구만 부르므로, 질문을 글로만 남기게 하면 "응답 규칙대로 예로 진행"처럼
질문이 사라진다(eval 46). 질문을 도구 호출로 받으면 기록에 남고, 답으로는 `EVAL_USER_REPLIES`(JSON 배열, eval의 user_replies)를
돌려준다 — 실행자는 그중 이 질문에 맞는 것을 사용자의 답으로 쓴다. 질문은 `MOCK_APPROVALS_LOG`에 `kind: ask`로 남긴다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
TOOLS = [{
    "name": "approve",
    "description": "eval 전용: 권한 확인 요청에 사용자 대신 답한다",
    "inputSchema": {"type": "object", "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"},
                                                     "tool_use_id": {"type": "string"}}},
}, {
    "name": "ask_user",
    "description": "사용자에게 묻는다: 질문 문구(선택지 포함)를 그대로 넘기면 사용자의 답이 돌아온다. 답을 받기 전에는 그 질문이 막는 일을 시작하지 않는다",
    "inputSchema": {"type": "object", "properties": {"question": {"type": "string"},
                                                     "options": {"type": "array", "items": {"type": "string"}}},
                    "required": ["question"]},
}]


def _log(entry: dict) -> None:
    path = os.environ.get("MOCK_APPROVALS_LOG")
    if not path:
        return
    p = Path(path)
    rows = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []
    rows.append(entry)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def approve(arguments: dict) -> dict:
    deny = os.environ.get("EVAL_APPROVER_DENY") == "1"
    _log({"tool_name": arguments.get("tool_name"), "input": arguments.get("input"),
          "decision": "deny" if deny else "allow"})
    if deny:
        return {"behavior": "deny", "message": "사용자가 권한 확인을 거부했다 (eval)"}
    return {"behavior": "allow", "updatedInput": arguments.get("input") or {}}


def ask_user(arguments: dict) -> str:
    _log({"kind": "ask", "question": arguments.get("question"), "options": arguments.get("options")})
    try:
        replies = json.loads(os.environ.get("EVAL_USER_REPLIES") or "[]")
    except ValueError:
        replies = []
    lines = "\n".join(f"- {r}" for r in replies) or "- (응답 규칙 없음)"
    return ("[시뮬레이션 사용자] 아래 응답 규칙 중 이 질문에 맞는 것이 사용자의 답이다. 맞는 규칙이 없으면 변경하지 않는 "
            f"선택지를 고른 것으로 하고 그 사실을 transcript에 적는다.\n{lines}")


def handle(message: dict) -> dict | None:
    method, mid = message.get("method"), message.get("id")
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "eval-approver", "version": "0.0.1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") == "approve":
            text = json.dumps(approve(params.get("arguments") or {}), ensure_ascii=False)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        elif params.get("name") == "ask_user":
            result = {"content": [{"type": "text", "text": ask_user(params.get("arguments") or {})}], "isError": False}
        else:
            result = {"content": [{"type": "text", "text": f"unknown tool: {params.get('name')}"}], "isError": True}
    elif mid is None:
        return None
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> int:
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        response = handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
