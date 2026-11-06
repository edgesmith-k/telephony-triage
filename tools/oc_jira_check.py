"""OpenCode Jira 읽기 사내 확인 — `site_step.py runtime-check opencode --jira <있는 키> [--missing-key <없는 키>]` (모델 토큰 0).

MODULE_SKILLS_DECISIONS "OpenCode Jira 읽기(11/05)". 실제 opencode(1.19.5, tt-oc와 같은 설치 폴더의 플러그인·어댑터·설정)를
127.0.0.1의 가짜 모델 서버(이 파일, 스레드)로 돌린다. 가짜 모델은 설정된 Jira MCP 읽기 도구(사용자 config `tracker.tools`의
get_issue·get_comments → opencode.json `mcp` 서버의 OpenCode 이름 `<서버>_<도구>`)를 있는 티켓·없는 티켓으로 부르고, **모델이 받은
도구 결과**(다음 요청의 tool 메시지)를 기록한다. 관문은 이 실행에만 연다(`TT_OC_JIRA_GATE=open`을 이 스크립트가 자식 환경에
넣는다 — 모델이 아니다).

판정(행):
- tools-offered: 읽기 도구가 모델 요청의 도구 목록에 있다(없으면 OpenCode 권한 deny·MCP 연결 실패 — 설치 설정·관리 설정 확인).
- success-isolation(get_issue)·comments-isolation(get_comments): 모델이 본 글이 jira_bridge 격리 문구(원문은 `<work_dir>/<KEY>/
  issue_raw.json`에만, 모델에는 마스킹된 요약 — Claude Code와 같은 `jira_bridge.py`)이고 그 파일이 이번 실행에 쓰였다.
- success-masking·comments-masking: `masking.residual(모델이 본 글) == {}`.
- error-path(없는 티켓): 오류 본문이 모델에 갔는지. 숨김(`Jira 오류(본문 숨김)`)·jira_bridge 문구면 pass, 본문이 갔으면 warn(남은
  식별자 종류·개수만, 글은 적지 않는다). `--missing-key`가 없으면 skip.
- permission(정보): 설치 설정(`opencode debug config`)이 읽기 도구를 허용하는지 — 아니면 tt-oc에서 실제로 쓰려면 다시 설치해야 한다.
- cleanup: 이 실행의 OpenCode 세션 삭제(도구 결과가 opencode.db에 남지 않게), 확인이 만든 issue_raw.json 정리(전에 있던 파일은 복원).

종료 0은 성공 경로(tools-offered·success-*·comments-*)가 모두 pass일 때만이다. 통과 기록(`common/oc_jira_gate.record_path`, 사용자
config 폴더)은 실행할 때마다 쓴다(passed·행마다 결과·OpenCode 버전·Jira 서버·도구 이름·시각·플러그인 스크립트 지문). 관문을
여는 명령(`config.py set opencode.jira_read open`)은 출력만 한다 — 사용자가 터미널에서 직접 실행한다.
"""

from __future__ import annotations

import http.server
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

BRIDGE_SAVED = "telephony-triage: Jira 응답 원문은 파일로만 저장했다"     # jira_bridge.bridge 성공 문구의 앞(바꾸면 함께)
OWN_PREFIX = "telephony-triage:"                                           # jira_bridge·어댑터 자체 문구(내용 없음)
HIDDEN_PREFIX = "Jira 오류(본문 숨김)"                                       # = oc_adapter.JIRA_ERROR_HIDDEN
SUCCESS_ROWS = ("tools-offered", "success-isolation", "success-masking", "comments-isolation", "comments-masking")
KEY_ARG_RE = re.compile(r"(?i)^(issue_?key|issueidorkey|key|issue|ticket|ticket_?key|issue_?id|id)$")
KEY_ARG_WORDS = re.compile(r"(?i)key|issue|ticket")
RUN_TIMEOUT = 300
FAKE_MODEL = "tt-runtime-check"
LOOPBACK = "127.0.0.1"       # 가짜 모델 서버가 묶는 주소(밖으로 나가지 않는다)


# -- 가짜 모델 서버(127.0.0.1, 비용 0) ------------------------------------------------------------------------------


def key_arg(schema) -> str:
    """도구 입력 스키마에서 티켓 키를 넣을 인자 이름: 이름이 키 같은 문자열 속성 → 필수 문자열 속성 → 첫 속성 → `key`."""
    props = schema.get("properties") if isinstance(schema, dict) and isinstance(schema.get("properties"), dict) else {}
    required = [r for r in (schema.get("required") or []) if r in props] if isinstance(schema, dict) else []
    strings = [n for n, v in props.items() if isinstance(v, dict) and v.get("type") in ("string", None)]
    for pick in ([n for n in strings if KEY_ARG_RE.match(n)], [n for n in strings if KEY_ARG_WORDS.search(n)],
                 [n for n in required if n in strings], strings, list(props)):
        if pick:
            return pick[0]
    return "key"


class FakeModel:
    """plan = [{"tool": OpenCode 이름, "key": 티켓 키, "label": 행 이름}]. 요청마다 assistant 메시지 수로 단계를 고른다."""

    def __init__(self, plan: list[dict]):
        self.plan = plan
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"object": "list", "data": [{"id": FAKE_MODEL, "object": "model"}]}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                size = int(self.headers.get("content-length", 0))
                try:
                    req = json.loads(self.rfile.read(size) or b"{}")
                except ValueError:
                    req = {}
                fake.respond(self, req)

        self.server = http.server.ThreadingHTTPServer((LOOPBACK, 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def respond(self, handler, req: dict) -> None:
        messages, tools = req.get("messages") or [], req.get("tools") or []
        turn = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "assistant")
        schemas = {(t.get("function") or {}).get("name"): (t.get("function") or {}).get("parameters") or {}
                   for t in tools if isinstance(t, dict)}
        tool_msgs = {str(m.get("tool_call_id")): m.get("content") for m in messages
                     if isinstance(m, dict) and m.get("role") == "tool"}
        call = None
        if tools and turn < len(self.plan):
            step = self.plan[turn]
            call = {"id": f"ttcheck_{turn}", "name": step["tool"],
                    "args": {key_arg(schemas.get(step["tool"])): step["key"]}}
            step.setdefault("arg", next(iter(call["args"])))
        with self.lock:
            self.requests.append({"main": bool(tools), "turn": turn, "tools": sorted(n for n in schemas if n),
                                  "tool_results": {k: _text(v) for k, v in tool_msgs.items()}})
        handler.send_response(200)
        handler.send_header("content-type", "text/event-stream")
        handler.end_headers()
        base = {"id": "c1", "object": "chat.completion.chunk", "created": int(time.time()), "model": req.get("model")}

        def send(delta, finish=None, usage=None):
            chunk = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            if usage:
                chunk["usage"] = usage
            handler.wfile.write(b"data: " + json.dumps(chunk, ensure_ascii=False).encode() + b"\n\n")
            handler.wfile.flush()

        if call:
            send({"role": "assistant", "tool_calls": [{"index": 0, "id": call["id"], "type": "function",
                                                       "function": {"name": call["name"],
                                                                    "arguments": json.dumps(call["args"])}}]})
            finish = "tool_calls"
        else:
            send({"role": "assistant", "content": "telephony-triage runtime-check done" if tools else "runtime-check"})
            finish = "stop"
        send({}, finish, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        handler.wfile.write(b"data: [DONE]\n\n")
        handler.wfile.flush()

    def seen(self, n: int) -> str | None:
        """n번째 계획 호출(`ttcheck_<n>`)의 결과로 모델이 받은 글(마지막 요청 기준). 못 받았으면 None."""
        for req in reversed(self.requests):
            if f"ttcheck_{n}" in req["tool_results"]:
                return req["tool_results"][f"ttcheck_{n}"]
        return None

    def offered(self) -> list[str]:
        mains = [r for r in self.requests if r["main"]]
        return mains[0]["tools"] if mains else []


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(c.get("text") or "") if isinstance(c, dict) else str(c) for c in content)
    return json.dumps(content, ensure_ascii=False)


# -- 설정 읽기 ------------------------------------------------------------------------------------------------------


def _wild(pattern: str, name: str) -> bool:
    return re.fullmatch("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern), name) is not None


def permission_action(cfg: dict, tool: str) -> str:
    """합쳐진 OpenCode 설정의 `permission`에서 도구 이름의 결정(마지막으로 맞는 문자열 규칙, 1.19.5). 규칙이 없으면 allow."""
    perm = cfg.get("permission") if isinstance(cfg, dict) else None
    if isinstance(perm, str):
        return perm
    action = "allow"
    for pattern, value in (perm or {}).items():
        if isinstance(value, str) and _wild(pattern, tool):
            action = value
    return action


def raw_mcp_entries(proj: Path, env: dict, segment: str) -> dict:
    """설치 폴더에서 OpenCode가 합치는 설정 파일의 `mcp` 중 정규화 이름이 segment인 서버(글자 그대로 — `{env:…}`를 풀지 않으므로
    자격 증명을 임시 설정에 쓰지 않는다). 뒤 파일이 이긴다(얕은 합치기, `mcptools.load_opencode_servers`와 같다)."""
    from common import mcptools, oc_adapter

    merged: dict = {}
    for path in mcptools.opencode_config_paths(str(proj), env):
        try:
            data = json.loads(oc_adapter._strip_jsonc(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        mcp = data.get("mcp") if isinstance(data, dict) else None
        for name, raw in (mcp.items() if isinstance(mcp, dict) else []):
            if isinstance(raw, dict) and mcptools.server_segment(name) == segment:
                merged[str(name)] = {**merged.get(str(name), {}), **raw}
    return merged


def _config_show(plugin_root: Path, env: dict, keys: str) -> dict:
    r = subprocess.run([sys.executable, str(plugin_root / "scripts" / "config.py"), "show", "--keys", keys],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60, check=False,
                       env={**env, "CLAUDE_PLUGIN_ROOT": str(plugin_root)})
    if r.returncode != 0:
        raise RuntimeError(f"config.py show 종료 {r.returncode}: {(r.stderr or '').strip()[-300:]}")
    return json.loads(r.stdout).get("values") or {}


def oc_names(tools: dict, servers: list[str]) -> tuple[dict, str | None, str | None]:
    """`tracker.tools`(get_issue·get_comments, `mcp__<서버>__<도구>`) → ({동작: OpenCode 이름}, 서버 정규화 이름, 문제)."""
    from common import mcptools

    out, segment = {}, None
    for action in ("get_issue", "get_comments"):
        name = tools.get(action)
        if not name:
            continue
        hit = mcptools.NAME_RE.match(mcptools.normalize(str(name)))
        if not hit:
            return {}, None, f"tracker.tools.{action}이 mcp__<서버>__<도구> 모양이 아니다: {name}"
        seg, tool = hit.group(1), mcptools.server_segment(hit.group(2))
        if segment and seg != segment:
            return {}, None, f"tracker.tools의 서버가 둘이다({segment}, {seg})"
        segment = seg
        out[action] = f"{seg}_{tool}"
    if "get_issue" not in out:
        return {}, None, "tracker.tools.get_issue가 없다 — config.py set-tracker(설정 4번)를 먼저 한다"
    if segment not in {mcptools.server_segment(s) for s in servers}:
        return out, segment, f"OpenCode 설정(opencode.json mcp)에 Jira 서버 `{segment}`가 없다"
    return out, segment, None


# -- 실행 -----------------------------------------------------------------------------------------------------------


def _row(check: str, status: str, detail: str) -> dict:
    return {"check": check, "status": status, "detail": detail}


def _first_line(text: str) -> str:
    """자체 문구(jira_bridge·어댑터)만 첫 줄을 보인다. 그 밖(응답 원문일 수 있음)은 보이지 않는다."""
    if text.startswith(OWN_PREFIX) or text.startswith(HIDDEN_PREFIX) or text.startswith("[telephony-triage]"):
        return text.splitlines()[0][:240]
    return f"(자체 문구 아님 — 내용 숨김, {len(text)}자)"


def _kinds(counts: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "없음"


def isolation_rows(label: str, seen: str | None, key: str, work_dir: Path, started: float) -> tuple[list[dict], Path | None]:
    """모델이 본 글이 jira_bridge 격리 문구인지 + 원문 파일, 그리고 마스킹 잔여. (행 2개, 원문 파일)."""
    from common import masking

    iso, mask = f"{label}-isolation", f"{label}-masking"
    if seen is None:
        return [_row(iso, "fail", "모델이 이 호출의 결과를 받지 못했다(호출이 안 됐거나 실행이 끝나지 않음)"),
                _row(mask, "fail", "건너뜀(결과 없음)")], None
    counts = masking.residual(seen)
    mask_row = _row(mask, "pass" if not counts else "fail",
                    "모델이 본 글에 남은 식별자 없음(masking.residual == {})" if not counts
                    else f"모델이 본 글에 마스킹 안 된 식별자: {_kinds(counts)}")
    if not seen.startswith(BRIDGE_SAVED):
        return [_row(iso, "fail", f"jira_bridge 격리 문구가 아니다: {_first_line(seen)}"), mask_row], None
    try:
        shown = json.loads(seen.split("\n", 1)[1])
        raw = Path(shown["saved_to"])
    except (IndexError, ValueError, KeyError, TypeError):
        return [_row(iso, "fail", "격리 문구의 요약 JSON(saved_to)을 읽지 못했다"), mask_row], None
    want = work_dir.expanduser().resolve() / key / "issue_raw.json"
    problems = []
    if raw.resolve() != want:
        problems.append(f"saved_to가 {want}가 아니다")
    if not raw.is_file():
        problems.append("원문 파일이 없다")
    elif raw.stat().st_mtime < started - 1:
        problems.append("원문 파일이 이번 실행에 쓰이지 않았다")
    elif key not in raw.read_text(encoding="utf-8", errors="replace"):
        problems.append("원문 파일에 티켓 키가 없다")
    if shown.get("key") != key:
        problems.append("요약의 key가 티켓 키와 다르다")
    if problems:
        return [_row(iso, "fail", "; ".join(problems)), mask_row], raw
    return [_row(iso, "pass", f"원문은 {raw}에만, 모델에는 마스킹된 요약(jira_bridge)"), mask_row], raw


def error_row(seen: str | None, state: dict | None) -> dict:
    """없는 티켓: 오류 본문이 모델에 갔는지(글은 적지 않는다)."""
    from common import masking

    status = (state or {}).get("status") or "?"
    if seen is None:
        return _row("error-path", "warn", f"모델이 결과를 받지 못해 판정하지 못했다(OpenCode 상태 {status})")
    if seen.startswith(HIDDEN_PREFIX):
        return _row("error-path", "pass", f"오류 본문 숨김 — 모델은 `{seen[:120]}`만 받았다(OpenCode 상태 {status})")
    if seen.startswith(BRIDGE_SAVED):
        return _row("error-path", "skip", "--missing-key 티켓이 읽혔다(없는 키가 아니다) — 오류 경로를 확인하지 못했다. "
                                          "Jira에 없는 키로 다시 돌린다")
    if seen.startswith(OWN_PREFIX):
        return _row("error-path", "pass", f"본문 없음 — jira_bridge 문구: {_first_line(seen)} (OpenCode 상태 {status})")
    counts = masking.residual(seen)
    return _row("error-path", "warn", f"오류 본문이 모델에 갔다(OpenCode 상태 {status}, {len(seen)}자) — 마스킹 안 된 식별자: "
                                       f"{_kinds(counts)}")


def _states(events: list[dict]) -> dict[str, dict]:
    out = {}
    for ev in events:
        part = ev.get("part") if isinstance(ev, dict) else None
        if isinstance(part, dict) and part.get("type") == "tool" and str(part.get("callID", "")).startswith("ttcheck_"):
            out[part["callID"]] = part.get("state") or {}
    return out


def _session_ids(events: list[dict]) -> list[str]:
    return sorted({str(ev.get("sessionID")) for ev in events if isinstance(ev, dict) and ev.get("sessionID")})


def check(tt, project: str | None, opencode: str, key: str, missing: str | None, env: dict,
          record_path: Path | None = None) -> tuple[str, int]:
    """표 + 결과 + (통과면) 여는 명령. 통과 기록을 쓴다."""
    from common import oc_adapter, oc_jira_gate as gate

    rows: list[dict] = []
    title = f"런타임 점검 opencode --jira — 모델 토큰 0(가짜 모델 서버 127.0.0.1, 실제 opencode {tt.PINNED}·실제 Jira MCP)"

    def done(extra: list[str] | None = None, code: int = 1) -> tuple[str, int]:
        table = [title, "", "| 항목 | 상태 | 내용 |", "|---|---|---|"]
        table += [f"| {r['check']} | {r['status']} | {str(r['detail']).replace('|', '/').replace(chr(10), ' ')} |" for r in rows]
        return "\n".join(table + [""] + (extra or [])), code

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", key or "") or \
            (missing is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", missing)):
        rows.append(_row("args", "fail", "티켓 키 형식: 영문·숫자·_.- (64자까지)"))
        return done(["결과: 실패 — 키 형식"])
    oc = shutil.which(opencode, path=env.get("PATH"))
    if not oc:
        rows.append(_row("opencode-version", "fail", f"opencode 없음 — OpenCode {tt.PINNED}를 설치한다"))
        return done(["결과: 실패 — opencode 없음"])
    ver_row, _ran = tt.version_row(oc, env)
    rows.append(ver_row)
    if ver_row["status"] != "ok":
        return done(["결과: 실패 — 버전 불일치(우회하지 말고 보고)"])
    try:
        proj, meta = tt.load_project(project or env.get("TT_OC_PROJECT"))
    except tt.Refused as exc:
        rows.append(_row("project", "fail", str(exc)))
        return done(["결과: 실패 — 설치 폴더(--project)"])
    plugin_root = Path(meta["plugin_root"])
    child = tt.child_env(meta)
    child.update({k: v for k, v in env.items() if k in ("PATH", "HOME", "TELEPHONY_TRIAGE_HOME")})
    try:
        values = _config_show(plugin_root, child, "tracker.tools,work_dir")
        r = subprocess.run([oc, "debug", "config"], cwd=proj, env=child, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=120, check=False)
        merged = json.loads(r.stdout) if r.returncode == 0 else None
        if not isinstance(merged, dict):
            raise RuntimeError(f"opencode debug config 종료 {r.returncode}")
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        rows.append(_row("config", "fail", f"설정 읽기 실패: {exc}"))
        return done(["결과: 실패 — 설정"])
    servers = list((merged.get("mcp") or {}).keys()) if isinstance(merged.get("mcp"), dict) else []
    names, segment, problem = oc_names(values.get("tracker.tools") or {}, servers)
    if problem:
        rows.append(_row("tracker", "fail", problem))
        return done(["결과: 실패 — Jira 도구 매핑"])
    work_dir = Path(str(values.get("work_dir") or "")).expanduser()
    rows.append(_row("tracker", "info", f"서버 {segment}, 읽기 도구 {', '.join(names.values())}"))
    denied = [n for n in names.values() if permission_action(merged, n) != "allow"]
    rows.append(_row("permission", "warn" if denied else "ok",
                     ("설치 설정이 허용하지 않는다: " + ", ".join(denied) + " — tt-oc에서 쓰려면 tools/gen_opencode.py install … "
                      + " ".join(f"--jira-read-tool {n}" for n in denied) + " --force(관리 설정 /etc/opencode의 jira_* deny는 "
                      "관리자). 이 확인은 임시 설정에서만 허용한다") if denied else "설치 설정이 읽기 도구를 허용한다"))

    plan = [{"tool": names["get_issue"], "key": key, "label": "success"}]
    if "get_comments" in names:
        plan.append({"tool": names["get_comments"], "key": key, "label": "comments"})
    if missing:
        plan.append({"tool": names["get_issue"], "key": missing, "label": "error"})
    tmp = Path(tempfile.mkdtemp(prefix="tt-ocjira-"))
    # 확인이 쓸 수 있는 원문 파일(키마다): 전에 있던 내용·폴더를 기억해 끝나면 그대로 되돌린다
    saved = {}
    for k in dict.fromkeys(s["key"] for s in plan):
        path = work_dir / k / "issue_raw.json"
        saved[path] = (path.read_bytes() if path.is_file() else None, path.parent.is_dir())
    cleanup: list[str] = []
    started = time.time()
    events: list[dict] = []
    try:
        proj_cfg = json.loads(oc_adapter._strip_jsonc((proj / "opencode.json").read_text(encoding="utf-8")))
        with FakeModel(plan) as fake:
            cfg = dict(proj_cfg)
            cfg.update({"model": f"ttcheck/{FAKE_MODEL}", "small_model": f"ttcheck/{FAKE_MODEL}", "provider": {"ttcheck": {
                "npm": "@ai-sdk/openai-compatible", "name": "telephony-triage runtime-check (fake, 127.0.0.1)",
                "options": {"baseURL": f"http://{LOOPBACK}:{fake.port}/v1", "apiKey": "dummy"},
                "models": {FAKE_MODEL: {"name": FAKE_MODEL, "limit": {"context": 202000, "output": 16000}}}}}})
            perm = dict(cfg.get("permission") or {}) if isinstance(cfg.get("permission"), dict) else {}
            for n in names.values():             # 이 임시 설정에서만 읽기 도구 허용(마지막 규칙이 이긴다)
                perm.pop(n, None)
                perm[n] = "allow"
            cfg["permission"] = perm
            cfg["mcp"] = {**(cfg.get("mcp") if isinstance(cfg.get("mcp"), dict) else {}),
                          **raw_mcp_entries(proj, child, segment)}
            if (proj / ".opencode").is_dir():
                shutil.copytree(proj / ".opencode", tmp / ".opencode", symlinks=False)
            shutil.copy2(proj / "tt-oc.json", tmp / "tt-oc.json")
            (tmp / "opencode.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
            run_env = {**child, oc_adapter.JIRA_GATE_ENV: "open", "TT_OC_GUARD_LOG": str(tmp / "oc-guard.log")}
            no_proxy = ",".join(x for x in (run_env.get("NO_PROXY"), "127.0.0.1,localhost") if x)
            run_env.update({"NO_PROXY": no_proxy, "no_proxy": no_proxy})
            cmd = [oc, "run", "--format", "json", "--agent", tt.AGENT, "--",
                   "telephony-triage runtime-check: Jira 읽기 확인(가짜 모델)"]
            events, _raw, code, tail = tt.run_opencode(cmd, cwd=tmp, env=run_env, timeout=RUN_TIMEOUT, progress=False)
            offered = fake.offered()
            seen = [fake.seen(i) for i in range(len(plan))]
        states = _states(events)
        missing_tools = [n for n in dict.fromkeys(names.values()) if n not in offered]
        rows.append(_row("tools-offered", "fail" if missing_tools else "pass",
                         ("모델 요청의 도구 목록에 없다: " + ", ".join(missing_tools) + " — OpenCode 권한 deny(관리 설정 "
                          "/etc/opencode 포함) 또는 MCP 서버 연결 실패" + (f" (opencode 종료 {code})" if code else ""))
                         if missing_tools else "읽기 도구가 모델 도구 목록에 있다"
                         + (f" (키 인자 `{plan[0].get('arg')}`)" if plan[0].get("arg") else "")))
        raws = []
        for i, step in enumerate(plan):
            if step["label"] == "error":
                rows.append(error_row(seen[i], states.get(f"ttcheck_{i}")))
            else:
                got, raw = isolation_rows(step["label"], seen[i], key, work_dir, started)
                rows += got
                raws.append(raw)
        if not missing:
            rows.append(_row("error-path", "skip", "오류 경로 확인 안 함(--missing-key 없음) — 건너뛴 확인은 통과가 아니다"))
        if code is None:
            rows.append(_row("opencode-run", "fail", f"시간 초과({RUN_TIMEOUT}초)"))
        cleanup = []
        for sid in _session_ids(events):
            r = subprocess.run([oc, "session", "delete", sid], cwd=tmp, env=run_env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=60, check=False)
            cleanup.append(f"세션 {sid} {'삭제' if r.returncode == 0 else f'삭제 실패(종료 {r.returncode})'}")
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        rows.append(_row("opencode-run", "fail", f"실행 실패: {type(exc).__name__}: {exc}"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for path, (before, dir_existed) in saved.items():
            try:      # 확인이 만든 원문 파일은 지우고, 전에 있던 파일은 그대로 되돌린다
                if before is not None:
                    path.write_bytes(before)
                    cleanup.append(f"{path.parent.name}/issue_raw.json 복원")
                elif path.is_file():
                    path.unlink()
                    cleanup.append(f"확인용 {path.parent.name}/issue_raw.json 삭제")
                if not dir_existed and path.parent.is_dir() and not any(path.parent.iterdir()):
                    path.parent.rmdir()
            except OSError as exc:
                cleanup.append(f"원문 파일 정리 실패: {exc}")
    rows.append(_row("cleanup", "info", "; ".join(cleanup) or "정리할 것 없음"))

    passed = all(r["status"] == "pass" for r in rows if r["check"] in SUCCESS_ROWS) and \
        any(r["check"] == "success-isolation" for r in rows) and not any(r["status"] == "fail" for r in rows)
    record = {"schema": gate.RECORD_SCHEMA, "at": gate.now_iso(), "passed": passed, "opencode_version": tt.PINNED,
              "jira_server": segment, "tools": list(dict.fromkeys(names.values())),
              "checks": [r for r in rows if r["check"] not in ("cleanup",)],
              "scripts_sha": gate.scripts_digest(plugin_root), "plugin_root": str(plugin_root), "project": str(proj)}
    path = gate.write_record(record, record_path)
    extra = [f"통과 기록: {path}"]
    if not passed:
        extra.insert(0, "결과: 실패 — 성공 경로가 통과하지 않아 관문을 열 수 없다(행의 안내대로 고친 뒤 다시 실행, 우회하지 않는다)")
        return done(extra, 1)
    accept = gate.needs_accept(record)
    extra.insert(0, "결과: 통과(성공 경로)" + (f" — 오류 경로 {gate.error_row(record)}: 열 때 --accept-error-bodies가 필요하다"
                                             if accept else ""))
    extra += ["관문 열기(사용자가 터미널에서 직접 — OpenCode 안의 모델은 열 수 없다):", "```sh",
              gate.open_command(plugin_root, accept), "```",
              "연 뒤에는 OpenCode(tt-oc·TUI)를 다시 시작한다 — 관문은 OpenCode가 시작할 때 한 번만 정해진다."]
    if denied:
        extra.append("tt-oc에서 실제로 읽으려면 위 permission 행대로 설치 설정에 읽기 도구를 허용한다.")
    return done(extra, 0)
