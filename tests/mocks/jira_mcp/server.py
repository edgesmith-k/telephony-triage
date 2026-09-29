#!/usr/bin/env python3
"""모의 Jira MCP 서버 (stdio JSON-RPC) — 서버 이름 `mock-jira`.

15-local-draft.md §15.2. 사내 Jira MCP를 대신한다.

- 도구 이름은 **일부러 비표준**이다(`jira_fetch_ticket` 등). 스킬이 도구 이름을
  직접 쓰지 않고 `jira.tools` 매핑을 반드시 거치게 하기 위해서다
  (16-existing-assets.md §16.1).
- 커스텀 필드 이름도 일부러 사내와 다를 법한 이름(`customfield_10001` 등)으로
  두어 `jira.field_map`을 반드시 거치게 한다.
- 쓰기 도구(`jira_post_comment`, `jira_move_ticket`)는 guard 차단 테스트용이다.
  실제로 데이터를 바꾸지 않고 "차단되지 않았다"는 표식만 남긴다.
- 등록은 레포 루트 `.mcp.json`이 아니라 `tests/mocks/mcp.json`에 둔다.
  사내에서 가짜 Jira가 진짜로 잡히지 않게 하기 위해서다.

MCP SDK에 의존하지 않는다 (01-architecture.md §3: 외부 의존성 최소화).
구현 범위는 `initialize`, `tools/list`, `tools/call`과
`notifications/initialized`뿐이다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "jira"
WRITE_LOG = HERE.parent / "gh-state" / "jira-writes.json"


def _data_dir() -> Path:
    """티켓 디렉토리. `MOCK_JIRA_DIR`로 바꿀 수 있다(스킬 eval 환경마다 다른 티켓)."""
    return Path(os.environ.get("MOCK_JIRA_DIR") or DATA_DIR)


def _write_log() -> Path:
    return Path(os.environ.get("MOCK_JIRA_WRITE_LOG") or WRITE_LOG)

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "mock-jira"
SERVER_VERSION = "0.0.1"

TOOLS = [
    {
        "name": "jira_fetch_ticket",
        "description": "티켓 하나를 읽는다 (논리 동작: get_issue)",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket": {"type": "string", "description": "예: MOCK-1001"}},
            "required": ["ticket"],
        },
    },
    {
        "name": "jira_query_tickets",
        "description": "티켓을 검색한다 (논리 동작: search_issues)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "요약·설명에서 찾을 문자열"},
                "component": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "jira_ticket_comments",
        "description": "티켓의 코멘트를 읽는다 (논리 동작: get_comments)",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket": {"type": "string"}},
            "required": ["ticket"],
        },
    },
    {
        "name": "jira_post_comment",
        "description": "[쓰기] 코멘트를 단다. guard가 막아야 한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket": {"type": "string"}, "body": {"type": "string"}},
            "required": ["ticket", "body"],
        },
    },
    {
        "name": "jira_move_ticket",
        "description": "[쓰기] 상태를 바꾼다. guard가 막아야 한다.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket": {"type": "string"}, "status": {"type": "string"}},
            "required": ["ticket", "status"],
        },
    },
]

WRITE_TOOLS = {"jira_post_comment", "jira_move_ticket"}


def load_ticket(key: str) -> dict | None:
    path = _data_dir() / f"{key}.yaml"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_tickets() -> list[dict]:
    out = []
    for path in sorted(_data_dir().glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data:
            out.append(data)
    return out


def record_write(tool: str, arguments: dict) -> None:
    """쓰기 도구가 실제로 불린 것을 남긴다. guard 차단 테스트가 이 파일이
    비어 있는지로 "막혔다"를 확인한다."""
    log = _write_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if log.is_file():
        try:
            entries = json.loads(log.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = []
    entries.append({"tool": tool, "arguments": arguments})
    log.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


def call_tool(name: str, arguments: dict) -> tuple[object, bool]:
    """(결과, is_error)."""
    if name == "jira_fetch_ticket":
        ticket = load_ticket(arguments.get("ticket", ""))
        if ticket is None:
            return {"error": "not found", "ticket": arguments.get("ticket")}, True
        payload = dict(ticket)
        payload.pop("comments", None)
        return payload, False

    if name == "jira_ticket_comments":
        ticket = load_ticket(arguments.get("ticket", ""))
        if ticket is None:
            return {"error": "not found", "ticket": arguments.get("ticket")}, True
        return {"key": ticket["key"], "comments": ticket.get("comments", [])}, False

    if name == "jira_query_tickets":
        q = (arguments.get("q") or "").lower()
        component = arguments.get("component")
        limit = int(arguments.get("limit") or 20)
        hits = []
        for ticket in all_tickets():
            fields = ticket.get("fields", {})
            haystack = " ".join(
                str(fields.get(k, "")) for k in ("summary", "description")
            ).lower()
            if q and q not in haystack:
                continue
            if component and component not in [
                c.get("name") for c in fields.get("components", [])
            ]:
                continue
            hits.append({"key": ticket["key"], "summary": fields.get("summary")})
        return {"total": len(hits), "issues": hits[:limit]}, False

    if name in WRITE_TOOLS:
        record_write(name, arguments)
        return {
            "warning": "쓰기 도구가 실행됐습니다. guard가 막았어야 합니다.",
            "tool": name,
            "arguments": arguments,
        }, False

    return {"error": f"unknown tool: {name}"}, True


def wrap(result: object, is_error: bool) -> dict:
    return {
        "content": [
            {"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}
        ],
        "isError": is_error,
    }


def handle(message: dict) -> dict | None:
    method = message.get("method")
    mid = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method in ("notifications/initialized", "initialized"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        result, is_error = call_tool(name, arguments)
        return {"jsonrpc": "2.0", "id": mid, "result": wrap(result, is_error)}

    if mid is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
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
