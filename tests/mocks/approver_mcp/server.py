#!/usr/bin/env python3
"""스킬 eval용 권한 확인 응답 MCP 서버 (stdio JSON-RPC) — 서버 이름 `eval-approver`, 도구 `approve`.

`claude -p --permission-prompt-tool mcp__eval-approver__approve`로 붙인다. guard hook이 `ask`를 낸 호출
(예: `db_pr.py publish`, 규칙 7)은 실제 사용자라면 권한 확인 창에서 승인한다. `-p`에는 사람이 없으므로 이 서버가
대신 **허용**하고, 무엇을 물었는지 `MOCK_APPROVALS_LOG`(JSON 배열)에 남긴다. 확인 화면을 보여주고 승인받았는지는
채점기가 transcript로 따로 본다 — 이 서버는 "권한 확인이 요청됐다"는 사실만 기록한다.

`EVAL_APPROVER_DENY=1`이면 거부한다(거부 경로 시험용). MCP SDK에 의존하지 않는다.
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
        if params.get("name") != "approve":
            result = {"content": [{"type": "text", "text": f"unknown tool: {params.get('name')}"}], "isError": True}
        else:
            text = json.dumps(approve(params.get("arguments") or {}), ensure_ascii=False)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
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
