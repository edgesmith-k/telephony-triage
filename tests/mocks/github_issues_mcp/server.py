#!/usr/bin/env python3
"""모의 GitHub Issues MCP 서버 (stdio JSON-RPC) — 서버 이름 `mock-github-issues`.

트래커 범용화 설계 §6-1. 두 번째 트래커(`tracker.kind: github`)를 시험한다.

- 도구 이름·인자는 **실제 GitHub MCP와 같은 표준 이름**이다(모의 Jira와 반대). 트래커 어댑터의 고정 키 인자
  (`owner`·`repo`·`issue_number`)를 검증하기 위해서다.
  - `issue_read {method: get|get_comments|get_labels, owner, repo, issue_number}`: 읽기(논리 동작 get_issue·get_comments)
  - `search_issues {query, owner?, repo?}`: 읽기(논리 동작 search_issues)
  - `add_issue_comment {owner, repo, issue_number, body}`: 승인 코멘트 게시용 쓰기(논리 동작 add_comment). 응답
    `{"id": <n>, "html_url": …}`. 호출은 쓰기 로그에 남는다
  - `update_issue`, `create_pull_request`: guard 차단 시험용 쓰기 도구. 데이터를 바꾸지 않고 쓰기 로그만 남긴다
- 데이터는 `tests/mocks/github_issues/<owner>.<repo>-<n>.yaml`(합성: `mock-org/mock-issues`, 호스트 `ghe.mock.invalid`).
  `MOCK_GH_ISSUES_DIR`로 바꿀 수 있다(스킬 eval 환경마다 다른 이슈). 쓰기 로그는 `MOCK_GH_ISSUES_WRITE_LOG`.
- 등록은 레포 루트 `.mcp.json`이 아니라 `tests/mocks/mcp.json`에 둔다.

MCP SDK에 의존하지 않는다. 구현 범위는 `initialize`, `tools/list`, `tools/call`, `notifications/initialized`, `ping`뿐이다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "github_issues"
WRITE_LOG = HERE.parent / "gh-state" / "gh-issues-writes.json"
HOST = "ghe.mock.invalid"

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "mock-github-issues"
SERVER_VERSION = "0.0.1"


def _data_dir() -> Path:
    return Path(os.environ.get("MOCK_GH_ISSUES_DIR") or DATA_DIR)


def _write_log() -> Path:
    return Path(os.environ.get("MOCK_GH_ISSUES_WRITE_LOG") or WRITE_LOG)


_REPO_ARGS = {
    "owner": {"type": "string", "description": "레포 소유자 (예: mock-org)"},
    "repo": {"type": "string", "description": "레포 이름 (예: mock-issues)"},
}
_ISSUE_ARGS = {**_REPO_ARGS, "issue_number": {"type": "number", "description": "이슈 번호"}}

TOOLS = [
    {
        "name": "issue_read",
        "description": "이슈 하나를 읽는다. method: get(이슈) | get_comments(코멘트) | get_labels(라벨)",
        "inputSchema": {
            "type": "object",
            "properties": {"method": {"type": "string", "enum": ["get", "get_comments", "get_labels"]}, **_ISSUE_ARGS},
            "required": ["method", "owner", "repo", "issue_number"],
        },
    },
    {
        "name": "search_issues",
        "description": "이슈를 검색한다 (제목·본문 부분 문자열)",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, **_REPO_ARGS},
            "required": ["query"],
        },
    },
    {
        "name": "add_issue_comment",
        "description": "[쓰기] 이슈에 코멘트를 단다 (논리 동작 add_comment). guard가 승인 기록과 대조한 뒤 ask로 허용한다.",
        "inputSchema": {
            "type": "object",
            "properties": {**_ISSUE_ARGS, "body": {"type": "string"}},
            "required": ["owner", "repo", "issue_number", "body"],
        },
    },
    {
        "name": "update_issue",
        "description": "[쓰기] 이슈를 바꾼다(제목·본문·상태·라벨). guard가 막아야 한다.",
        "inputSchema": {
            "type": "object",
            "properties": {**_ISSUE_ARGS, "title": {"type": "string"}, "body": {"type": "string"},
                           "state": {"type": "string"}},
            "required": ["owner", "repo", "issue_number"],
        },
    },
    {
        "name": "create_pull_request",
        "description": "[쓰기] PR을 만든다. 트래커 서버에서는 guard가 막아야 한다.",
        "inputSchema": {
            "type": "object",
            "properties": {**_REPO_ARGS, "title": {"type": "string"}, "head": {"type": "string"},
                           "base": {"type": "string"}, "body": {"type": "string"}},
            "required": ["owner", "repo", "title", "head", "base"],
        },
    },
]

WRITE_TOOLS = {"add_issue_comment", "update_issue", "create_pull_request"}
COMMENT_TOOL = "add_issue_comment"


def _key(owner, repo, number) -> str | None:
    if not (isinstance(owner, str) and isinstance(repo, str)) or isinstance(number, bool) or not isinstance(number, int):
        return None
    if "/" in owner + repo or ".." in owner + repo:
        return None
    return f"{owner}.{repo}-{number}".lower()


def load_issue(owner, repo, number) -> dict | None:
    key = _key(owner, repo, number)
    path = _data_dir() / f"{key}.yaml" if key else None
    if path is None or not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_issues() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(_data_dir().glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data:
            out.append((path.stem, data))
    return out


def record_write(tool: str, arguments: dict) -> int:
    """쓰기 도구가 실제로 불린 것을 남긴다(채점·guard 차단 시험이 이 파일로 본다). 기록 뒤 항목 수."""
    log = _write_log()
    log.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if log.is_file():
        try:
            entries = json.loads(log.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entries = []
    entries.append({"tool": tool, "arguments": arguments})
    log.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return len(entries)


def _not_found(arguments: dict) -> tuple[dict, bool]:
    return {"message": "Not Found", "owner": arguments.get("owner"), "repo": arguments.get("repo"),
            "issue_number": arguments.get("issue_number")}, True


def call_tool(name: str, arguments: dict) -> tuple[object, bool]:
    """(결과, is_error)."""
    owner, repo, number = arguments.get("owner"), arguments.get("repo"), arguments.get("issue_number")

    if name == "issue_read":
        issue = load_issue(owner, repo, number)
        if issue is None:
            return _not_found(arguments)
        method = arguments.get("method")
        if method == "get":
            payload = dict(issue)
            payload.pop("comments", None)
            return payload, False
        if method == "get_comments":
            return list(issue.get("comments") or []), False
        if method == "get_labels":
            return list(issue.get("labels") or []), False
        return {"message": f"unknown method: {method}"}, True

    if name == "search_issues":
        q = str(arguments.get("query") or "").lower()
        hits = []
        for stem, issue in all_issues():
            if owner and not stem.startswith(f"{str(owner).lower()}."):
                continue
            if repo and f".{str(repo).lower()}-" not in stem:
                continue
            haystack = f"{issue.get('title', '')} {issue.get('body', '')}".lower()
            if q and q not in haystack:
                continue
            hits.append({"number": issue.get("number"), "title": issue.get("title"), "html_url": issue.get("html_url"),
                         "state": issue.get("state")})
        return {"total_count": len(hits), "items": hits}, False

    if name == COMMENT_TOOL:
        if load_issue(owner, repo, number) is None:
            return _not_found(arguments)
        count = record_write(name, arguments)
        return {"id": 9000 + count,
                "html_url": f"https://{HOST}/{owner}/{repo}/issues/{number}#issuecomment-{9000 + count}"}, False

    if name in WRITE_TOOLS:
        record_write(name, arguments)
        return {"warning": "쓰기 도구가 실행됐습니다. guard가 막았어야 합니다.", "tool": name, "arguments": arguments}, False

    return {"message": f"unknown tool: {name}"}, True


def wrap(result: object, is_error: bool) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}], "isError": is_error}


def handle(message: dict) -> dict | None:
    method = message.get("method")
    mid = message.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") or {}
        result, is_error = call_tool(params.get("name", ""), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": mid, "result": wrap(result, is_error)}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


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
