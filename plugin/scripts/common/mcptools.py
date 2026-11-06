"""이미 등록된 MCP 서버의 도구 목록과 Jira 도구 후보 (16-existing-assets.md §16.1, 02-config.md §4 setup 4).

- 서버 목록: Claude Code MCP 설정 JSON의 `mcpServers`(기본은 사용자 범위 `~/.claude.json`).
  stdio 서버는 직접 띄워 `initialize` → `tools/list`로 도구 이름을 읽는다. 원격(http/sse) 서버는
  여기서 읽지 못하므로, 스킬이 세션에서 보이는 도구 이름을 `--tools-json`으로 넘긴다.
  stdio 확인(`list_tools`)은 서버당 최대 `PROBE_TIMEOUT`(10초), `tools/list` 응답을 받는 즉시 끝내고 프로세스 그룹(손자 포함)을
  종료한다 — 응답 뒤 끝나지 않는 서버·Windows `npx.cmd` 손자가 파이프를 쥔 경우에도 멈추지 않는다.
- `site-defaults.yaml`의 `tracker.exclude_servers`(fnmatch 패턴, 기본 `['mock-*']`)에 맞는 서버는
  후보에서 뺀다.
- 도구 전체 이름은 `mcp__<server>__<tool>`이고, `<server>`의 `[A-Za-z0-9_-]` 밖 글자는 `_`로 바뀐다 — TODO(SITE:S1)
  사내 Claude Code 버전에서 확인한다 (치환 규칙은 공식 문서에 없어 관측 기반 추정이다).
- 후보는 이름으로만 고른다. **사용자 확인을 받은 뒤** `config.py set-tracker`로 저장한다.
- OpenCode(계획 I O8): 서버는 opencode.json(JSONC)의 `mcp`(`{이름: {type: local|remote, command: [명령, 인자...],
  environment, enabled}}`)에서 읽는다(`opencode_config_paths`·`load_opencode_servers`). 세션의 도구 이름은 `<서버>_<도구>`
  (서버 부분은 같은 `_` 치환)이고, 저장하는 이름은 Claude Code와 같은 `mcp__<서버>__<도구>`다 — `oc_adapter`가 guard에 넘길 때
  같은 규칙(`opencode_candidates`)으로 바꾼다.
"""

from __future__ import annotations

import fnmatch
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
# 쓰기형 단어(완전 일치, 끝의 s·es 허용). 뒷줄은 비Jira MCP(GitHub 등)의 이슈 DB 쓰기 판정(guard 규칙 11)용이다.
# Jira 쪽은 read_tools가 명시 허용 목록이라 늘려도 안전 쪽이다.
WRITE_WORDS = ("create", "add", "update", "delete", "remove", "transition", "assign", "post", "edit",
               "set", "link", "upload", "attach", "move", "close", "reopen", "worklog", "write",
               "push", "merge", "fork", "dispatch", "trigger", "resolve", "unresolve", "enable", "disable", "submit",
               "cancel", "rerun", "dismiss", "lock", "unlock", "archive", "rename")
# 동사 자리(첫 단어)에 올 때만 쓰기인 단어: `request_copilot_review`·`run_secret_scanning`. 다른 자리의 `request`는
# 읽기일 수 있다(`pull_request_read`).
WRITE_VERBS = ("request", "run", "approve", "comment", "reply")
# 동사 자리에 오면 읽기: `list_triggers`·`get_issue_links`·`list_assignees`
READ_VERBS = ("get", "search", "list", "read", "fetch", "query", "view", "find", "show", "lookup", "download", "check")
# 동사 앞에 붙는 제품·서버 이름 (`jira_get_attachments`의 동사는 get)
NAME_WORDS = ("jira", "confluence", "atlassian", "github", "gh", "ghe", "mcp")
READ_WORDS = ("get", "search", "list", "read", "fetch", "query", "view", "find", "show", "comments")


NAME_RE = re.compile(r"^mcp__(.+?)__(.+)$")


def server_segment(server: str) -> str:
    """세션에 보이는 도구 이름 속 서버 부분 (`jira.corp` → `jira_corp`)."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(server))


def full_name(server: str, tool: str) -> str:
    return f"mcp__{server_segment(server)}__{tool}"


def normalize(name: str) -> str:
    """`mcp__<server>__<tool>`이면 서버 부분을 정규화한 이름, 아니면 그대로 (멱등)."""
    hit = NAME_RE.match(str(name))
    return full_name(hit.group(1), hit.group(2)) if hit else str(name)


def server_prefix(name: str) -> str | None:
    """도구 전체 이름의 정규화된 서버 접두사(`mcp__<server>__`), 형식이 아니면 None."""
    hit = NAME_RE.match(str(name))
    return full_name(hit.group(1), "") if hit else None


def _words(tool: str) -> list[str]:
    """단어 목록 (`_`·`-`·camelCase 경계로 나눔, 소문자)."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(tool))
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def verb(tool: str) -> str:
    """동사 자리 단어: 제품·서버 이름(`NAME_WORDS`)을 건너뛴 첫 단어 (없으면 빈 문자열)."""
    words = _words(tool)
    return next((w for w in words if w not in NAME_WORDS), words[0] if words else "")


def _is_write_word(w: str) -> bool:
    return w in WRITE_WORDS or (w.endswith("s") and w[:-1] in WRITE_WORDS) or (w.endswith("es") and w[:-2] in WRITE_WORDS)


def is_write(tool: str) -> bool:
    """쓰기형 도구인가. 동사가 읽기 동사면 읽기, 동사가 쓰기 동사면 쓰기, 아니면 쓰기 단어가 하나라도 있으면 쓰기
    (단어 완전 일치 — 접두사로 맞추지 않는다: `list_assignees`·`get_issue_links`는 읽기)."""
    v = verb(tool)
    if v in READ_VERBS:
        return False
    if v in WRITE_VERBS:
        return True
    return any(_is_write_word(w) for w in _words(tool))


def classify(tool: str) -> set[str]:
    """논리 동작 후보 (`get_issue`, `search_issues`, `get_comments`)."""
    words = _words(tool)
    if is_write(tool):
        return set()
    out = set()
    entity = any(w in ("issue", "issues", "ticket", "tickets") for w in words)
    if any(w.startswith("comment") for w in words):
        out.add("get_comments")
    elif any(w in ("search", "query", "jql") for w in words) or (entity and "list" in words):
        out.add("search_issues")
    elif entity and any(w in ("get", "fetch", "read", "view", "show") for w in words):
        out.add("get_issue")
    return out


def is_read(tool: str) -> bool:
    return not is_write(tool) and any(w in READ_WORDS or w.startswith("comment") for w in _words(tool))


def load_servers(config_paths: list[Path]) -> dict[str, dict]:
    servers: dict[str, dict] = {}
    for path in config_paths:
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for name, conf in (data.get("mcpServers") or {}).items():
            servers.setdefault(name, conf)
    return servers


PROBE_TIMEOUT = 10.0      # 서버 하나의 initialize → tools/list 응답 기다림(초)
KILL_GRACE = 1.0          # SIGTERM 뒤 SIGKILL까지(초)
NOT_STDIO = "not-stdio: stdio 서버가 아니다(원격 서버는 --tools-json으로 준다)"


class ProbeError(ValueError):
    """stdio 서버 확인 실패. `kind`: `not-stdio`·`timeout`·`exited`·`no-response`·`rpc-error`. 메시지는 `<kind>…: 설명`이고
    서버 출력(stdout·stderr) 내용은 넣지 않는다(사내 보고에 그대로 옮길 수 있게)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _kill_tree(proc: subprocess.Popen) -> None:
    """프로세스 그룹(손자 포함)을 끝낸다. POSIX: 새 세션의 그룹에 SIGTERM → 잠시 뒤 SIGKILL. Windows: `taskkill /T /F`.
    npx·uvx·mcp-remote처럼 손자가 stdout 파이프를 쥐고 있어도 읽기 스레드가 EOF를 받는다."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            proc.kill()
        except OSError:
            pass
    else:
        import signal
        for sig, grace in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, KILL_GRACE)):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass
    try:
        proc.wait(timeout=KILL_GRACE)
    except subprocess.TimeoutExpired:
        pass


def list_tools(conf: dict, timeout: float = PROBE_TIMEOUT) -> list[str]:
    """stdio MCP 서버를 띄워 도구 이름 목록을 읽는다. 원격 서버·실패면 `ProbeError`(ValueError), 띄우지 못하면 OSError.

    `initialize`·`notifications/initialized`·`tools/list`를 쓰고 stdin은 열어 둔 채 읽기 스레드가 stdout 줄을 받는다.
    `id == 2` 응답이 오면 **바로** 반환한다(응답 뒤 끝나지 않는 서버를 기다리지 않는다). 끝에서는 항상 프로세스
    그룹을 끝낸다(`_kill_tree`). `timeout`초 안에 응답이 없으면 `timeout`."""
    if not conf.get("command"):
        raise ProbeError("not-stdio", NOT_STDIO)
    command = shutil.which(conf["command"]) or conf["command"]
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "telephony-triage-setup", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = ("\n".join(json.dumps(r) for r in requests) + "\n").encode("utf-8")
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    proc = subprocess.Popen([command, *conf.get("args", [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=conf.get("cwd"),
                            env=None if not conf.get("env") else {**os.environ, **conf["env"]}, **group)
    lines: queue.Queue = queue.Queue()

    def pump_out():
        try:
            for raw in iter(proc.stdout.readline, b""):
                lines.put(raw)
        except (OSError, ValueError):
            pass
        lines.put(None)                  # EOF

    def drain_err():                     # stderr를 비워 서버가 파이프에 막히지 않게(내용은 쓰지 않는다)
        try:
            for _ in iter(lambda: proc.stderr.read(65536), b""):
                pass
        except (OSError, ValueError):
            pass

    readers = [threading.Thread(target=f, daemon=True) for f in (pump_out, drain_err)]
    for t in readers:
        t.start()
    deadline = time.monotonic() + timeout
    try:
        try:
            proc.stdin.write(payload)
            proc.stdin.flush()
        except OSError:
            pass                         # 이미 끝난 서버: 아래에서 exited로 판정
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProbeError("timeout", f"timeout({timeout:g}초): tools/list 응답이 없다")
            try:
                raw = lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if raw is None:
                try:
                    code = proc.wait(timeout=min(KILL_GRACE, max(deadline - time.monotonic(), 0.01)))
                except subprocess.TimeoutExpired:
                    raise ProbeError("no-response", "no-response: stdout이 닫혔는데 tools/list 응답이 없다") from None
                raise ProbeError("exited", f"exited({code}): tools/list 응답 전에 끝났다")
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if not isinstance(msg, dict) or msg.get("id") != 2:
                continue
            if isinstance(msg.get("result"), dict):
                return [t["name"] for t in msg["result"].get("tools", []) if isinstance(t, dict) and t.get("name")]
            code = msg.get("error", {}).get("code") if isinstance(msg.get("error"), dict) else None
            raise ProbeError("rpc-error", f"rpc-error({code}): tools/list 오류 응답")
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        _kill_tree(proc)
        for t, pipe in zip(readers, (proc.stdout, proc.stderr)):
            t.join(timeout=KILL_GRACE)
            if not t.is_alive():         # 읽는 중인 파이프를 닫으면 막힐 수 있다(그룹 밖으로 나간 손자): 데몬 스레드에 맡긴다
                try:
                    pipe.close()
                except OSError:
                    pass


def candidates(servers: dict[str, list[str] | None], exclude: list[str], team_tools: dict | None = None,
               errors: dict[str, str] | None = None, classify_extra=None) -> list[dict]:
    """서버별 후보. `servers`는 `{서버: [도구 이름] 또는 None(읽지 못함)}`. `classify_extra(도구, 후보 동작) -> 후보 동작`은
    설정 트래커의 후보 보강(`TrackerSpec.classify_extra`, 없으면 `classify` 그대로)."""
    out = []
    for server in sorted(servers):
        tools = servers[server]
        excluded = any(fnmatch.fnmatch(server, pattern) for pattern in exclude or [])
        entry = {"server": server, "excluded": excluded, "error": (errors or {}).get(server),
                 "tools": [], "tracker_tools": {}, "read_tools": [], "suggested": {}}
        if excluded or tools is None:
            out.append(entry)
            continue
        entry["tools"] = sorted(full_name(server, t) for t in tools)
        tracker_tools: dict[str, list[str]] = {"get_issue": [], "search_issues": [], "get_comments": []}
        for tool in sorted(tools):
            actions = classify(tool)
            for action in sorted(classify_extra(tool, actions) if classify_extra else actions):
                tracker_tools[action].append(full_name(server, tool))
        entry["tracker_tools"] = tracker_tools
        entry["read_tools"] = sorted(full_name(server, t) for t in tools if is_read(t))
        prefix = full_name(server, "")
        for action, name in (team_tools or {}).items():  # 팀 기본값(site-defaults)을 먼저 제안
            if isinstance(name, str) and normalize(name).startswith(prefix) and normalize(name) in entry["tools"]:
                entry["suggested"][action] = normalize(name)
        for action, names in tracker_tools.items():
            if action not in entry["suggested"] and names:
                entry["suggested"][action] = names[0]
        out.append(entry)
    return out


# -- OpenCode (계획 I O8) ----------------------------------------------------------------------------


def opencode_candidates(tool: str, servers) -> list[str]:
    """OpenCode MCP 도구 이름(`<서버>_<도구>`) → Claude Code 이름 후보 `mcp__<서버>__<도구>`(가장 긴 서버 접두사 먼저).
    서버 이름이 서로 접두사이면(`corp`·`corp_jira`) 후보가 여럿이다 — 호출 쪽이 모두 본다(`oc_adapter.mcp_candidates`)."""
    out = []
    for seg in sorted({server_segment(s) for s in servers}, key=len, reverse=True):
        if seg and tool.startswith(seg + "_") and len(tool) > len(seg) + 1:
            out.append(f"mcp__{seg}__{tool[len(seg) + 1:]}")
    return out


def tool_part(server: str, name: str, opencode: bool = False) -> str:
    """세션에 보이는 도구 이름 → 서버 안 도구 이름. `mcp__<서버>__<도구>`는 도구 부분, OpenCode(`opencode`)면 `<서버>_` 접두사를
    뗀다(서버 부분은 정규화 비교). 그 밖은 그대로(이미 도구 이름)."""
    name = str(name)
    if name.startswith("mcp__"):
        return name.split("__", 2)[-1]
    seg = server_segment(server) + "_"
    if opencode and name.startswith(seg) and len(name) > len(seg):
        return name[len(seg):]
    return name


OPENCODE_MANAGED_DIR = Path("/etc/opencode")
OPENCODE_CONFIG_NAMES = ("opencode.json", "opencode.jsonc", "config.json")


def opencode_config_paths(directory: str, env: dict | None = None) -> list[Path]:
    """`directory`에서 OpenCode가 합치는 설정 파일(있는 것만, `oc_adapter.config_files`)을 우선순위가 낮은 것부터:
    전역(XDG) → `OPENCODE_CONFIG` → 프로젝트(먼 폴더 → 가까운 폴더) → 관리(`/etc/opencode`). 뒤 파일이 이긴다."""
    from common import oc_adapter

    env = os.environ if env is None else env
    found = oc_adapter.config_files(directory, env)
    xdg = Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME") or Path.home()) / ".config") / "opencode"
    managed = [p for p in found if p.parent == OPENCODE_MANAGED_DIR]
    glob = [p for p in found if p.parent == xdg and p not in managed]
    named = [p for p in found if env.get("OPENCODE_CONFIG") and p == Path(env["OPENCODE_CONFIG"]) and p not in glob]
    chain = [p for p in found if p not in managed and p not in glob and p not in named]
    return glob + named + chain[::-1] + managed


def _opencode_conf(raw: dict) -> dict:
    """opencode.json `mcp` 항목 하나 → `list_tools`가 받는 모양(`command`·`args`·`env`) + `enabled`·`type`."""
    conf: dict = {"type": raw.get("type"), "enabled": raw.get("enabled", True) is not False}
    cmd = raw.get("command")
    if isinstance(cmd, str) and cmd:
        cmd = [cmd]
    if raw.get("type") != "remote" and isinstance(cmd, list) and cmd and all(isinstance(c, str) for c in cmd):
        conf.update(command=cmd[0], args=cmd[1:])
        if isinstance(raw.get("environment"), dict):
            conf["env"] = {str(k): str(v) for k, v in raw["environment"].items()}
    return conf


def load_opencode_servers(config_paths: list[Path]) -> dict[str, dict]:
    """opencode.json(JSONC) `mcp`의 서버 → `{이름: conf}`(`_opencode_conf`). 같은 서버는 뒤 파일의 키가 덮는다(얕은 합치기,
    프로젝트에서 `{"enabled": false}`만 두는 경우). 읽지 못하거나 `mcp`가 객체가 아니면 ValueError(파일 경로 포함)."""
    from common import oc_adapter

    merged: dict[str, dict] = {}
    for path in config_paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(oc_adapter._strip_jsonc(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: OpenCode 설정을 읽지 못함 ({type(exc).__name__})") from exc
        mcp = data.get("mcp") if isinstance(data, dict) else None
        if mcp is None:
            continue
        if not isinstance(mcp, dict):
            raise ValueError(f"{path}: mcp가 객체가 아니다")
        for name, raw in mcp.items():
            if isinstance(raw, dict):
                merged[str(name)] = {**merged.get(str(name), {}), **raw}
    return {name: _opencode_conf(raw) for name, raw in merged.items()}
