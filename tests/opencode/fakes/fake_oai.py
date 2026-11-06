"""가짜 OpenAI 호환 모델 서버(127.0.0.1, 비용 0) — OpenCode e2e용. 계획 I `fake_oai2.py`를 옮기고 GLM 변형을 더했다.

    python3 fake_oai.py SCRIPT_JSON REQUEST_LOG     # 첫 줄에 고른 포트를 쓴다(포트 0으로 묶는다)

SCRIPT: {"main": [step, ...], "child": [step, ...]} — 사용자 메시지에 CHILDTASK가 든 요청은 child를 쓴다. step은 그 요청까지의
assistant 메시지 수로 고른다(넘치면 마지막). 도구 목록이 없는 요청(제목 만들기 등)은 짧은 글로 답한다.

step 모양:
    {"tool": 이름, "args": {...}}                 도구 호출 1개
    {"tools": [{"tool":…, "args":…}, …]}           한 턴에 도구 호출 여러 개
    {"text": "..."}                               마지막 글
변형 키(GLM 흉내, 계획 I O9): "chunked": true(인자 JSON을 3조각으로), "reasoning": "..."(reasoning_content 먼저),
"raw_args": "..."(JSON이 아닌 인자 그대로), "finish": "stop"(도구 호출과 함께 finish_reason stop),
"content": "..."(도구 호출 대신 content에 글로 쓴 도구 호출), "empty": true(빈 마지막 글).
"""

import http.server
import json
import sys
import time

with open(sys.argv[1], encoding="utf-8") as _fh:
    SCRIPT = json.load(_fh)
LOG = sys.argv[2]


def log(entry):
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def text_of(message):
    content = message.get("content")
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"object": "list", "data": [{"id": "fake", "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        size = int(self.headers.get("content-length", 0))
        req = json.loads(self.rfile.read(size) or b"{}")
        messages, tools = req.get("messages", []), req.get("tools") or []
        turn = sum(1 for m in messages if m.get("role") == "assistant")
        child = any(m.get("role") == "user" and "CHILDTASK" in text_of(m) for m in messages)
        seq = SCRIPT["child" if child else "main"]
        step = {"text": "fake title"} if not tools else seq[min(turn, len(seq) - 1)]
        log({"kind": "main" if tools else "aux", "child": child, "turn": turn,
             "tools": [t.get("function", {}).get("name") for t in tools], "step": step,
             "tool_results": [text_of(m)[:2000] for m in messages if m.get("role") == "tool"]})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        base = {"id": "c1", "object": "chat.completion.chunk", "created": int(time.time()), "model": req.get("model")}

        def send(delta, finish=None, usage=None):
            chunk = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            if usage:
                chunk["usage"] = usage
            self.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()

        if step.get("reasoning"):
            send({"role": "assistant", "reasoning_content": step["reasoning"]})
        calls = step.get("tools") or ([{"tool": step["tool"], "args": step.get("args", {})}] if "tool" in step else [])
        if calls:
            for n, call in enumerate(calls):
                args = step.get("raw_args") if "raw_args" in step else json.dumps(call.get("args", {}), ensure_ascii=False)
                cid = f"call_{'c' if child else 'm'}_{turn}_{n}"
                pieces = [args[i:i + max(1, len(args) // 3)] for i in range(0, len(args), max(1, len(args) // 3))] \
                    if step.get("chunked") else [args]
                for k, piece in enumerate(pieces):
                    fn = {"arguments": piece}
                    if k == 0:
                        fn["name"] = call["tool"]
                    tc = {"index": n, "function": fn}
                    if k == 0:
                        tc.update({"id": cid, "type": "function"})
                    send({"role": "assistant", "tool_calls": [tc]} if k == 0 and n == 0 else {"tool_calls": [tc]})
            finish = step.get("finish", "tool_calls")
        elif "content" in step:
            send({"role": "assistant", "content": step["content"]})
            finish = "stop"
        else:
            send({"role": "assistant", "content": "" if step.get("empty") else step.get("text", "")})
            finish = "stop"
        send({}, finish, {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110})
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
print(server.server_address[1], flush=True)
server.serve_forever()
