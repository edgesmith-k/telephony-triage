"""가짜 stdio MCP 서버 — OpenCode e2e용(계획 I `fake_mcp.py`).

    python3 fake_mcp.py CALL_LOG TOOL[,TOOL...]

도구마다 `{key}`·`{body}`를 받는 스키마를 내고, 호출은 CALL_LOG에 한 줄씩 남긴다(거부된 호출이 서버까지 오지 않았는지 본다).
결과 글에는 일부러 원문 표식 `FAKE_MCP_RAW`와 IMSI 모양 숫자를 넣는다.
"""

import json
import sys

LOG = sys.argv[1]
NAMES = [n for n in sys.argv[2].split(",") if n]
TOOLS = [{"name": n, "description": f"fake tool {n}",
          "inputSchema": {"type": "object", "properties": {"key": {"type": "string"}, "body": {"type": "string"}}}}
         for n in NAMES]


def out(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    msg = json.loads(line)
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        out({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg["params"].get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}})
    elif method == "tools/list":
        out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(msg["params"]) + "\n")
        text = "FAKE_MCP_RAW imsi=450081234567890 " + json.dumps(msg["params"])
        out({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}})
    elif mid is not None:
        out({"jsonrpc": "2.0", "id": mid, "result": {}})
