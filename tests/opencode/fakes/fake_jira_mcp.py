"""가짜 stdio Jira MCP 서버 — OpenCode Jira 읽기 관문 e2e·사내 확인(`site_step.py runtime-check opencode --jira`) 시험용.

    python3 fake_jira_mcp.py CALL_LOG

도구(일부러 사내와 다를 법한 이름·인자 `issue_key`): `get_issue {issue_key}`, `get_comments {issue_key}`, `add_comment {issue_key, body}`.
- `OCJ-…`·`MOCK-2001`처럼 `EXISTING`에 든 키: 이슈 JSON(설명·코멘트에 원문 식별자 — IMSI·전화번호·메일).
- `RPCERR-…`: JSON-RPC 오류 응답(message에 원문 식별자, HTTP 500 흉내).
- 그 밖 키: MCP `isError: true` 결과(본문 JSON에 404·원문 식별자) — 1.19.5는 이 오류에 after hook을 돌리지 않는다.
호출은 CALL_LOG에 한 줄씩 남는다(거부된 호출이 서버까지 오지 않았는지 본다).
"""

import json
import sys

LOG = sys.argv[1]
IMSI = "450081234567890"
PHONE = "010-1234-5678"
MAIL = "mock.person@corp.mock.invalid"
EXISTING = {"MOCK-2001"}
TOOLS = [
    {"name": "get_issue", "description": "Jira 이슈 하나",
     "inputSchema": {"type": "object", "properties": {"issue_key": {"type": "string"}, "fields": {"type": "string"}},
                     "required": ["issue_key"]}},
    {"name": "get_comments", "description": "Jira 이슈 코멘트",
     "inputSchema": {"type": "object", "properties": {"issue_key": {"type": "string"}}, "required": ["issue_key"]}},
    {"name": "add_comment", "description": "[쓰기] 코멘트",
     "inputSchema": {"type": "object", "properties": {"issue_key": {"type": "string"}, "body": {"type": "string"}},
                     "required": ["issue_key", "body"]}},
]


def out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def text(obj, error=False):
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}], "isError": error}


def call(name, args):
    key = str(args.get("issue_key") or "")
    if key.startswith("RPCERR-"):
        return None, {"code": -32000, "message": f"upstream HTTP 500 for {key}: imsi={IMSI} reporter {MAIL}"}
    if key not in EXISTING and not key.startswith("OCJ-"):
        return text({"status": 404, "errorMessages": [f"Issue {key} does not exist. reporter {MAIL} imsi {IMSI}"]},
                    error=True), None
    if name == "get_issue":
        return text({"key": key, "fields": {"summary": "데이터 끊김 OCJ e2e", "description": f"imsi={IMSI} tel {PHONE} 재부팅",
                                             "status": {"name": "Open"}, "created": "2026-10-01T09:00:00.000+0900"}}), None
    if name == "get_comments":
        return text({"key": key, "comments": [{"author": "mock.dev", "created": "2026-10-02T10:00:00.000+0900",
                                               "body": f"메일 {MAIL} imsi {IMSI} 확인"}]}), None
    return text({"ok": True, "warning": "쓰기 도구가 실행됐다 — 막혔어야 한다"}), None


for line in sys.stdin:
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        out({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg["params"].get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-jira", "version": "0"}}})
    elif method == "tools/list":
        out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(params, ensure_ascii=False) + "\n")
        result, error = call(params.get("name"), params.get("arguments") or {})
        out({"jsonrpc": "2.0", "id": mid, **({"error": error} if error else {"result": result})})
    elif mid is not None:
        out({"jsonrpc": "2.0", "id": mid, "result": {}})
