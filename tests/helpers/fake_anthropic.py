#!/usr/bin/env python3
"""가짜 Anthropic Messages 서버(127.0.0.1만, 실제 모델 없음) — 계획 I C2i·C3i의 선택 실행 테스트용.

    python3 fake_anthropic.py <port-file> <request-log>

빈 포트를 잡아 <port-file>에 쓰고 요청마다 {path, auth 앞 6자, model, max_tokens, thinking 유무, tools}를 <request-log>에 한 줄씩
남긴다. 첫 요청(tool_result 없음)에 Read 도구가 있으면 `READFILE` 환경 변수 경로로 Read tool_use, 그다음은 텍스트
"FAKE-OK". 스트리밍(SSE)과 비스트리밍 둘 다. `/v1/models`는 빈 목록, `count_tokens`는 바이트/4. 실험 원본:
scratchpad planI/cc_gw/fake_anthropic.py(CLI 2.1.318에서 확인).
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT_FILE, LOG = sys.argv[1], sys.argv[2]


def has_tool_result(body):
    return any(isinstance(m.get("content"), list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                                         for b in m["content"]) for m in body.get("messages", []))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(200, json.dumps({"data": []}).encode())

    def do_HEAD(self):
        self._send(200, b"")

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            body = json.loads(raw)
        except ValueError:
            body = {}
        if "count_tokens" in self.path:
            self._send(200, json.dumps({"input_tokens": len(raw) // 4}).encode())
            return
        tools = [t.get("name") for t in body.get("tools") or []]
        auth = self.headers.get("x-api-key") or self.headers.get("authorization") or ""
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"path": self.path, "auth": auth[:6], "model": body.get("model"),
                                 "max_tokens": body.get("max_tokens"), "thinking": bool(body.get("thinking")),
                                 "tools": tools}) + "\n")
        if "Read" in tools and not has_tool_result(body):
            block = {"type": "tool_use", "id": "toolu_fake1", "name": "Read",
                     "input": {"file_path": os.environ.get("READFILE", "/dev/null")}}
        else:
            block = {"type": "text", "text": "FAKE-OK"}
        stop = "tool_use" if block["type"] == "tool_use" else "end_turn"
        msg = {"id": "msg_fake", "type": "message", "role": "assistant", "model": body.get("model"), "content": [],
               "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": len(raw) // 4, "output_tokens": 7}}
        if not body.get("stream"):
            self._send(200, json.dumps({**msg, "content": [block], "stop_reason": stop}).encode())
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()

        def ev(name, payload):
            self.wfile.write(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()
        ev("message_start", {"type": "message_start", "message": msg})
        if block["type"] == "text":
            ev("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "text_delta", "text": block["text"]}})
        else:
            ev("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {**block, "input": {}}})
            ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}})
        ev("content_block_stop", {"type": "content_block_stop", "index": 0})
        ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                             "usage": {"output_tokens": 7}})
        ev("message_stop", {"type": "message_stop"})
        self.close_connection = True


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(PORT_FILE + ".tmp", "w", encoding="utf-8") as fh:
    fh.write(str(server.server_address[1]))
os.replace(PORT_FILE + ".tmp", PORT_FILE)
server.serve_forever()
