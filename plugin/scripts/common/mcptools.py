"""이미 등록된 MCP 서버의 도구 목록과 Jira 도구 후보 (16-existing-assets.md §16.1, 02-config.md §4 setup 4).

- 서버 목록: Claude Code MCP 설정 JSON의 `mcpServers`(기본은 사용자 범위 `~/.claude.json`).
  stdio 서버는 직접 띄워 `initialize` → `tools/list`로 도구 이름을 읽는다. 원격(http/sse) 서버는
  여기서 읽지 못하므로, 스킬이 세션에서 보이는 도구 이름을 `--tools-json`으로 넘긴다.
- `site-defaults.yaml`의 `jira.exclude_servers`(fnmatch 패턴, 기본 `['mock-*']`)에 맞는 서버는
  후보에서 뺀다.
- 도구 전체 이름은 `mcp__<server>__<tool>`이고, `<server>`의 `[A-Za-z0-9_-]` 밖 글자는 `_`로 바뀐다 — TODO(SITE:S1)
  사내 Claude Code 버전에서 확인한다 (치환 규칙은 공식 문서에 없어 관측 기반 추정이다).
- 후보는 이름으로만 고른다. **사용자 확인을 받은 뒤** `config.py set-jira`로 저장한다.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
from pathlib import Path

PROTOCOL_VERSION = "2025-06-18"
# 쓰기형 단어. 뒷줄은 비Jira MCP(GitHub 등)의 이슈 DB 쓰기 판정(guard 규칙 11)용이다. `request`는 넣지 않는다
# (`pull_request_read`가 걸린다). Jira 쪽은 read_tools가 명시 허용 목록이라 늘려도 안전 쪽이다.
WRITE_WORDS = ("create", "add", "update", "delete", "remove", "transition", "assign", "post", "edit",
               "set", "link", "upload", "attach", "move", "close", "reopen", "worklog", "write",
               "push", "merge", "fork", "dispatch", "trigger", "resolve", "unresolve", "enable", "disable", "submit",
               "cancel", "rerun", "dismiss", "lock", "unlock", "archive", "rename")
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
    return [w for w in re.split(r"[^a-z0-9]+", tool.lower()) if w]


def is_write(tool: str) -> bool:
    return any(w in WRITE_WORDS or w.startswith(WRITE_WORDS) for w in _words(tool))


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


def list_tools(conf: dict, timeout: float = 20.0) -> list[str]:
    """stdio MCP 서버를 띄워 도구 이름 목록을 읽는다. 원격 서버면 ValueError."""
    if not conf.get("command"):
        raise ValueError("stdio 서버가 아니다(원격 서버는 --tools-json으로 준다)")
    command = shutil.which(conf["command"]) or conf["command"]
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                    "clientInfo": {"name": "telephony-triage-setup", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = "\n".join(json.dumps(r) for r in requests) + "\n"
    proc = subprocess.run([command, *conf.get("args", [])], input=payload, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, cwd=conf.get("cwd"),
                          env=None if not conf.get("env") else {**__import__("os").environ, **conf["env"]})
    for line in proc.stdout.splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == 2 and "result" in msg:
            return [t["name"] for t in msg["result"].get("tools", []) if t.get("name")]
    raise ValueError(f"tools/list 응답이 없다: {proc.stderr.strip()[:200]}")


def candidates(servers: dict[str, list[str] | None], exclude: list[str], team_tools: dict | None = None,
               errors: dict[str, str] | None = None) -> list[dict]:
    """서버별 후보. `servers`는 `{서버: [도구 이름] 또는 None(읽지 못함)}`."""
    out = []
    for server in sorted(servers):
        tools = servers[server]
        excluded = any(fnmatch.fnmatch(server, pattern) for pattern in exclude or [])
        entry = {"server": server, "excluded": excluded, "error": (errors or {}).get(server),
                 "tools": [], "jira_tools": {}, "read_tools": [], "suggested": {}}
        if excluded or tools is None:
            out.append(entry)
            continue
        entry["tools"] = sorted(full_name(server, t) for t in tools)
        jira_tools: dict[str, list[str]] = {"get_issue": [], "search_issues": [], "get_comments": []}
        for tool in sorted(tools):
            for action in classify(tool):
                jira_tools[action].append(full_name(server, tool))
        entry["jira_tools"] = jira_tools
        entry["read_tools"] = sorted(full_name(server, t) for t in tools if is_read(t))
        prefix = full_name(server, "")
        for action, name in (team_tools or {}).items():  # 팀 기본값(site-defaults)을 먼저 제안
            if isinstance(name, str) and normalize(name).startswith(prefix) and normalize(name) in entry["tools"]:
                entry["suggested"][action] = normalize(name)
        for action, names in jira_tools.items():
            if action not in entry["suggested"] and names:
                entry["suggested"][action] = names[0]
        out.append(entry)
    return out
