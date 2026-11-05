"""OpenCode 1.19.5 도구 호출 → Claude Code hook 입력 변환과 guard·jira_bridge 다리 (계획 I, 분석 전용 v1 = 안 A).

OpenCode 플러그인(`opencode/plugins/tt-guard.js`)이 도구 호출마다 이 모듈을 스크립트로 부른다. 판정 규칙은 새로 만들지 않는다:
OpenCode 호출을 Claude Code PreToolUse/PostToolUse hook 입력 JSON과 **같은 모양**으로 바꿔, `hooks/hooks.json`처럼 바뀌지 않은
`guard.py`·`jira_bridge.py`를 하위 프로세스로 돌리고 그 결정을 OpenCode 쪽(허용 / 거부 + 사유)으로 되돌린다.

    python3 <plugin>/scripts/common/oc_adapter.py before   stdin {tool, args, directory, sessionID, callID}
        → stdout {"decision": "allow"|"deny", "reason": str, "warnings": [str], "events": [도구 이름]}
    python3 <plugin>/scripts/common/oc_adapter.py after    stdin {tool, args, directory, sessionID, callID, content}
        → stdout {"replace": str|null}   (null이면 결과 그대로, 문자열이면 모델에 그 글만 보인다)
    python3 <plugin>/scripts/common/oc_adapter.py env-check
        → stdout {"refused": [환경변수 이름]}

종료 코드는 0이다. 0이 아니거나·시그널·시간 초과·JSON이 아니면 플러그인이 거부(before)·오류 문구(after)로 닫는다.

**도구 표(1.19.5 고정, `BUILTINS`)**: 이름으로만 고른다. 표에 없는 이름은 MCP 서버 이름(opencode.json `mcp` 키)의 접두사로만
MCP 도구로 본다. 둘 다 아니면 거부한다(모르는 도구 = 거부). OpenCode 버전이 바뀌면 표를 다시 확인한다(`OPENCODE_VERSION`).

- bash → `Bash`. cwd는 `resolve(directory, args.workdir)`(OpenCode가 명령을 실제로 돌리는 곳). workdir가 없는 디렉토리·`~`로
  시작·디렉토리가 아니면 거부.
- edit/write → `Edit`/`Write`, `filePath`를 directory 기준 절대 경로로(OpenCode와 같게 `~`를 풀지 않는다).
- apply_patch → `*** Add/Update/Delete File:`·`*** Move to:` 경로마다 `Write` 하나. 1.19.5 파서와 같은 규칙으로 읽고, 읽지 못하거나
  hunk가 없으면 거부.
- 읽기 전용(read·glob·grep·skill·lsp·todowrite·question·invalid)은 통과.
- task(전역 거부, 사용자 결정 ⑧)·webfetch·websearch·codesearch(외부 전송)·execute·plan·MCP 리소스 도구는 v1에서 거부.
- MCP: OpenCode 이름은 `<서버>_<도구>`(둘 다 `[^A-Za-z0-9_-]`→`_`). 서버 이름 목록의 **모든** 접두사 후보(가장 긴 것 먼저)를
  `mcp__<서버>__<도구>`로 바꿔 guard에 각각 묻고 가장 엄한 결정을 쓴다(`corp`·`corp_jira`가 함께 있을 때의 모호함도 닫힌다).

**분석 전용(v1)**: guard `ask`는 거부로 바꾸고 "OpenCode v1 does not run this; run this exact command yourself: …"로 정확한
명령을 보인다. guard가 묻지 않는 쓰기 흐름도 여기서 막는다(`V1_NETS`: db_pr publish·merge, skill_patch apply, issue_post approve,
리뷰어 요청, module_eval). Jira MCP는 `jira_bridge` 마스킹 다리가 출시 관문(`JIRA_READ_RELEASED`)을 넘기 전에는 읽기도 거부하고,
코멘트 도구(`tracker.write_tools.add_comment`)는 v1에서 늘 거부한다.

**bash 허용 목록(`bash_allowlist`, guard 다음)**: guard는 거부 목록이라 셸 간접 실행(스크립트 파일·`python3 -c`·변수·중첩
`opencode run --pure`)을 다 볼 수 없다. v1 bash는 플러그인 스크립트(`python3 <plugin>/scripts/<이름>.py …`, 절대 경로)와 읽기
명령만 돌린다. 셸 부분집합(`split_bash`) 밖(펼침·파일 리디렉션·대입·서브셸·배경)은 거부한다. guard가 거부·확인한 호출은 guard
문구를 그대로 쓴다. edit·write·apply_patch는 플러그인 루트·`.opencode/`·OpenCode 전역 설정·설정/지시 파일을 고치지 못한다
(`protected_target`). apply_patch 경로는 1.19.5처럼 JS `.trim()`으로 다듬고, 보이지 않는 글자가 남은 경로는 거부한다.
모든 거부 사유는 `[telephony-triage]`로 시작한다(tt-oc가 막힌 호출로 판정한다).

**환경변수 무시 설정 거부(`REFUSED_ENV`)**: 설정을 덮거나 지우는 OpenCode 환경변수가 있으면 모든 도구를 거부한다(x3b·x4 실험).
플러그인이 아예 안 실리는 `--pure` 실행은 여기서 막을 수 없다 — `tt-oc` 래퍼가 거절한다.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if __name__ == "__main__":   # 스크립트로 불릴 때: common/ 대신 scripts/를 경로에 둔다(표준 모듈 이름 가림 방지)
    _HERE = str(Path(__file__).resolve().parent)
    sys.path[:] = [p for p in sys.path if os.path.realpath(p or os.getcwd()) != _HERE]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OPENCODE_VERSION = "1.19.5"
SCRIPTS = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SCRIPTS.parent

# -- 도구 표 -------------------------------------------------------------------------------------------

PASS, BASH, FILE, PATCH, DENY = "pass", "bash", "file", "patch", "deny"
NOT_IN_V1 = "OpenCode v1(분석 전용)에서 쓰지 않는 도구다"
BUILTINS: dict[str, tuple[str, str]] = {
    "invalid": (PASS, ""), "question": (PASS, ""), "read": (PASS, ""), "glob": (PASS, ""), "grep": (PASS, ""),
    "skill": (PASS, ""), "lsp": (PASS, ""), "todowrite": (PASS, ""),
    "bash": (BASH, ""), "edit": (FILE, "Edit"), "write": (FILE, "Write"), "apply_patch": (PATCH, ""),
    "task": (DENY, "task(하위 에이전트)는 전역 거부다(사용자 결정 ⑧). 같은 세션에서 직접 한다"),
    "webfetch": (DENY, f"{NOT_IN_V1}(외부 전송)"), "websearch": (DENY, f"{NOT_IN_V1}(외부 전송)"),
    "codesearch": (DENY, f"{NOT_IN_V1}(외부 전송)"),
    "execute": (DENY, NOT_IN_V1), "plan": (DENY, NOT_IN_V1),
    "list_mcp_resources": (DENY, f"{NOT_IN_V1}(MCP 리소스는 마스킹 다리를 거치지 않는다)"),
    "list_mcp_resource_templates": (DENY, f"{NOT_IN_V1}(MCP 리소스는 마스킹 다리를 거치지 않는다)"),
    "read_mcp_resource": (DENY, f"{NOT_IN_V1}(MCP 리소스는 마스킹 다리를 거치지 않는다)"),
}
HOOK_TIMEOUT = {"Bash": 180, "mcp": 30, "file": 30}    # hooks.json의 guard timeout(초)과 같다
BRIDGE_TIMEOUT = 30

# 설정을 덮거나 지우는 환경변수(값과 무관하게 있으면 거부). 접두사는 `REFUSED_ENV_PREFIXES`
REFUSED_ENV = ("OPENCODE_PERMISSION", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
               "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_PURE", "OPENCODE_TEST_MANAGED_CONFIG_DIR",
               "OPENCODE_TEST_HOME", "OPENCODE_ENABLE_EXA")
REFUSED_ENV_PREFIXES = ("OPENCODE_EXPERIMENTAL",)

# Jira 읽기 출시 관문: jira_bridge 다리(after)의 마스킹·오류 경로 e2e가 사내 실제 MCP 응답으로 통과한 뒤 PR로 True로 바꾼다.
# 그 전에는 Jira 서버 도구를 모두 거부한다. 테스트·사내 확인만 `TT_OC_JIRA_GATE=open`으로 연다(모델은 이 프로세스 환경을 못 바꾼다).
JIRA_READ_RELEASED = False
JIRA_GATE_ENV = "TT_OC_JIRA_GATE"

ASK_PREFIX = "OpenCode v1 does not run this; run this exact command yourself: "
BRIDGE_FAILED = ("telephony-triage: OpenCode jira_bridge 처리 실패 — 원문은 표시하지 않는다. "
                 "Claude Code에서 다시 읽거나 config.py doctor로 확인한다.")
MCP_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


def sanitize(name: str) -> str:
    """OpenCode 1.19.5 MCP 이름 정리(`w0`): `[^a-zA-Z0-9_-]` → `_`."""
    return MCP_NAME_RE.sub("_", str(name))


# -- opencode.json의 MCP 서버 이름 ---------------------------------------------------------------------


def _strip_jsonc(text: str) -> str:
    """JSONC → JSON: 문자열 밖 `//`·`/* */` 주석과 `}`·`]` 앞 쉼표를 뺀다."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def config_files(directory: str, env: dict | None = None) -> list[Path]:
    """서버 이름을 모을 설정 파일 후보(있는 것만): 관리(`/etc/opencode`), 전역(XDG), `OPENCODE_CONFIG`, directory에서
    루트까지의 `opencode.json(c)`·`.opencode/opencode.json(c)`. 합집합을 쓰므로 넓을수록 안전 쪽이다(후보만 늘어난다)."""
    env = os.environ if env is None else env
    names = ("opencode.json", "opencode.jsonc", "config.json")
    dirs = [Path("/etc/opencode"),
            Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME") or Path.home()) / ".config") / "opencode"]
    out = [d / n for d in dirs for n in names]
    if env.get("OPENCODE_CONFIG"):
        out.append(Path(env["OPENCODE_CONFIG"]))
    here = Path(directory or ".").resolve()
    for d in (here, *here.parents):
        out += [d / "opencode.json", d / "opencode.jsonc", d / ".opencode" / "opencode.json",
                d / ".opencode" / "opencode.jsonc"]
    return [p for p in dict.fromkeys(out) if p.is_file()]


def mcp_servers(directory: str, env: dict | None = None) -> tuple[list[str], str | None]:
    """(서버 이름 목록, 오류). 읽지 못한 설정 파일이 하나라도 있으면 오류 — 호출 쪽은 MCP 도구를 모두 거부한다."""
    names: list[str] = []
    for path in config_files(directory, env):
        try:
            data = json.loads(_strip_jsonc(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            return names, f"{path}: {type(exc).__name__}"
        mcp = data.get("mcp") if isinstance(data, dict) else None
        if mcp is None:
            continue
        if not isinstance(mcp, dict):
            return names, f"{path}: mcp가 객체가 아니다"
        names += [str(k) for k in mcp]
    return list(dict.fromkeys(names)), None


def mcp_candidates(tool: str, servers: list[str]) -> list[str]:
    """OpenCode MCP 도구 이름 → Claude Code 이름 후보(가장 긴 서버 접두사 먼저). 규칙은 `mcptools.opencode_candidates`
    하나다(설정 쪽 `config.py tracker-candidates`와 같다)."""
    from common import mcptools

    return mcptools.opencode_candidates(tool, servers)


# -- apply_patch ---------------------------------------------------------------------------------------


class PatchError(ValueError):
    pass


# ECMAScript `String.prototype.trim()`이 지우는 글자(WhiteSpace + LineTerminator). Python `str.strip()`과 다르다:
# U+FEFF는 JS만 지우고, U+001C~U+001F·U+0085는 Python만 지운다. 1.19.5 파서는 JS `.trim()`을 쓰므로 그대로 따른다.
JS_WS = "\t\n\u000b\u000c\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a" \
        "\u2028\u2029\u202f\u205f\u3000\ufeff"


def js_trim(text: str) -> str:
    return text.strip(JS_WS)


def odd_path_char(path: str) -> str | None:
    """경로에 보이지 않거나 제어용인 글자(Unicode Cc·Cf·Zl·Zp, 공백 아닌 Zs)가 있으면 그 글자의 표기. 판정이 OpenCode와
    어긋날 여지를 남기지 않으려고 이런 경로는 아예 거부한다."""
    import unicodedata
    for ch in path:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn") or (cat == "Zs" and ch != " "):
            return f"U+{ord(ch):04X}"
    return None


def patch_paths(text: str) -> list[str]:
    """apply_patch 본문이 건드리는 경로(Add·Update·Delete·Move to), 1.19.5 파서(`lt`·`pa`)와 같은 규칙(JS `.trim()`).
    Begin/End 표시가 없거나 hunk가 없거나 경로에 보이지 않는 글자가 있으면 PatchError."""
    if not isinstance(text, str) or not text:
        raise PatchError("patchText가 없다")
    body = js_trim(text)
    m = re.match(r"^(?:cat\s+)?<<['\"]?(\w+)['\"]?\s*\n([\s\S]*?)\n\1\s*$", body)
    lines = (m.group(2) if m else body).split("\n")
    begin = next((i for i, ln in enumerate(lines) if js_trim(ln) == "*** Begin Patch"), -1)
    end = next((i for i, ln in enumerate(lines) if js_trim(ln) == "*** End Patch"), -1)
    if begin < 0 or end < 0 or begin >= end:
        raise PatchError("Begin/End 표시가 없다")
    paths, i = [], begin + 1
    while i < end:
        line = lines[i]
        hit = next((h for h in ("*** Add File:", "*** Delete File:", "*** Update File:") if line.startswith(h)), None)
        path = js_trim(line[len(hit):]) if hit else ""
        if not hit or not path:
            i += 1
            continue
        paths.append(path)
        i += 1
        if hit == "*** Update File:" and i < len(lines) and lines[i].startswith("*** Move to:"):
            move = js_trim(lines[i][len("*** Move to:"):])
            if move:
                paths.append(move)
            i += 1
        while i < len(lines) and not lines[i].startswith("***"):   # 본문(+·-·@@ 줄). 1.19.5는 End 뒤까지 읽지 않는다
            i += 1
    if not paths:
        raise PatchError("hunk가 없다")
    for path in paths:
        bad = odd_path_char(path)
        if bad:
            raise PatchError(f"경로에 보이지 않는 글자({bad})가 있다")
    return paths


# -- 변환 ----------------------------------------------------------------------------------------------


@dataclass
class Mapped:
    kind: str
    events: list[dict] = field(default_factory=list)
    deny: str | None = None
    command: str | None = None      # bash: 사용자가 그대로 돌릴 명령(cd 포함)
    cwd: str | None = None


def _event(name: str, tool_input: dict, cwd: str, payload: dict, hook: str = "PreToolUse") -> dict:
    return {"session_id": str(payload.get("sessionID") or ""), "transcript_path": "", "cwd": cwd,
            "permission_mode": "default", "hook_event_name": hook, "tool_name": name, "tool_input": tool_input,
            "tool_use_id": str(payload.get("callID") or "")}


def _abs(directory: str, path: str) -> str:
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(directory, path))


def resolve_workdir(directory: str, workdir) -> tuple[str | None, str | None]:
    """(cwd, 거부 사유). OpenCode bash처럼 directory 기준으로 풀고 실제 경로로 바꾼다."""
    if workdir is None or workdir == "":
        return os.path.realpath(directory), None
    if not isinstance(workdir, str):
        return None, "bash workdir가 문자열이 아니다"
    if workdir.startswith("~"):
        return None, f"bash workdir `{workdir}`: `~`는 풀지 않는다 — 절대 경로로 다시 부른다"
    path = os.path.realpath(_abs(directory, workdir))
    if not os.path.isdir(path):
        return None, f"bash workdir `{workdir}`가 디렉토리가 아니다"
    return path, None


def map_tool(payload: dict, servers: list[str] | None, servers_error: str | None = None) -> Mapped:
    """OpenCode 도구 호출 → Claude Code PreToolUse 입력 목록. 실패는 `deny`에 사유."""
    tool = str(payload.get("tool") or "")
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    directory = str(payload.get("directory") or "")
    if not directory or not os.path.isabs(directory):
        return Mapped("error", deny="OpenCode 프로젝트 디렉토리를 모른다")
    directory = os.path.realpath(directory)
    candidates = mcp_candidates(tool, servers or [])
    if tool in BUILTINS:
        if candidates:
            return Mapped("error", deny=f"`{tool}`이 내장 도구와 MCP 도구({candidates[0]}) 둘로 읽힌다 — 판정할 수 없어 거부한다")
        kind, extra = BUILTINS[tool]
        if kind == PASS:
            return Mapped(kind)
        if kind == DENY:
            return Mapped(kind, deny=f"{tool}: {extra}.")
        if kind == BASH:
            command = args.get("command")
            if not isinstance(command, str):
                return Mapped(kind, deny="bash command가 문자열이 아니다")
            cwd, why = resolve_workdir(directory, args.get("workdir"))
            if why:
                return Mapped(kind, deny=why)
            tool_input = {"command": command}
            for key in ("timeout", "description"):
                if key in args:
                    tool_input[key] = args[key]
            shown = command if cwd == directory else f"cd {shlex.quote(cwd)} && {command}"
            return Mapped(kind, [_event("Bash", tool_input, cwd, payload)], command=shown, cwd=cwd)
        if kind == FILE:
            path = args.get("filePath")
            if not isinstance(path, str) or not path:
                return Mapped(kind, deny=f"{tool} filePath가 없다")
            if odd_path_char(path):
                return Mapped(kind, deny=f"{tool} filePath에 보이지 않는 글자({odd_path_char(path)})가 있다")
            target = _abs(directory, path)
            if extra == "Edit":
                tool_input = {"file_path": target, "old_string": args.get("oldString", ""),
                              "new_string": args.get("newString", ""), "replace_all": bool(args.get("replaceAll"))}
            else:
                tool_input = {"file_path": target, "content": args.get("content", "")}
            return Mapped(kind, [_event(extra, tool_input, directory, payload)], cwd=directory)
        if kind == PATCH:
            try:
                paths = patch_paths(args.get("patchText"))
            except PatchError as exc:
                return Mapped(kind, deny=f"apply_patch를 읽지 못해 거부한다: {exc}")
            events = [_event("Write", {"file_path": _abs(directory, p), "content": ""}, directory, payload)
                      for p in dict.fromkeys(paths)]
            return Mapped(kind, events, cwd=directory)
    if servers_error:
        return Mapped("mcp", deny=f"opencode.json MCP 서버 목록을 읽지 못해 MCP 도구를 거부한다 ({servers_error})")
    if not candidates:
        return Mapped("unknown", deny=f"모르는 도구 `{tool}`(OpenCode {OPENCODE_VERSION} 내장 표에도 MCP 서버 목록에도 없다) — "
                                      "거부한다")
    return Mapped("mcp", [_event(name, args, directory, payload) for name in candidates], cwd=directory)


# -- 환경 ----------------------------------------------------------------------------------------------


def refused_env(env: dict | None = None) -> list[str]:
    env = os.environ if env is None else env
    return sorted(k for k in env if k in REFUSED_ENV or k.startswith(REFUSED_ENV_PREFIXES))


def jira_gate_open(env: dict | None = None) -> bool:
    env = os.environ if env is None else env
    return JIRA_READ_RELEASED or env.get(JIRA_GATE_ENV) == "open"


def opencode_version(env: dict | None = None, timeout: float = 10) -> str | None:
    """`opencode --version`의 마지막 줄(`TT_OPENCODE`, 없으면 PATH의 `opencode` — `tt-oc --opencode` 기본값과 같다). 바이너리가
    없거나 실패하면 None. 모델·네트워크 호출 없음(`job_status.py`의 런타임 줄, O8)."""
    import shutil

    env = os.environ if env is None else env
    exe = shutil.which(env.get("TT_OPENCODE") or "opencode", path=env.get("PATH"))
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    last = (r.stdout or "").strip().splitlines()[-1:]
    if r.returncode != 0 or not last:
        return None
    return re.sub(r"[^A-Za-z0-9._+-]", "", last[0])[:40] or None


@dataclass
class TrackerView:
    prefixes: set[str]
    comment_tool: str | None
    words: tuple[str, ...]


def tracker_view() -> TrackerView:
    """guard 규칙 2와 같은 Jira 서버 판별 재료(읽기만). 예외는 호출 쪽이 받는다(모든 MCP 거부)."""
    import trackers

    from common import issuepost, site_defaults, userconfig
    try:
        defaults = site_defaults.load(PLUGIN_ROOT)
    except site_defaults.SiteDefaultsMissing:
        defaults = {}
    cfg = userconfig.merged(defaults, userconfig.load_user() or {})
    return TrackerView(issuepost.jira_prefixes(cfg), issuepost.raw_tool(cfg), trackers.all_server_words())


def is_jira(name: str, view: TrackerView) -> bool:
    from common import mcptools
    norm = mcptools.normalize(name)
    hit = mcptools.NAME_RE.match(norm)
    server = hit.group(1).lower() if hit else ""
    return any(norm.startswith(p) for p in view.prefixes) or any(w in server for w in view.words)


# -- v1 쓰기 흐름 ---------------------------------------------------------------------------------------

# (이름, 낱말, 설명): guard `word_net`과 같은 낱말 그물(이름과 낱말이 명령 글에 함께 있으면)
V1_NETS = (("db_pr", "publish", "이슈 DB push·PR(db_pr publish)"), ("db_pr", "merge", "이슈 DB PR 병합(db_pr merge)"),
           ("skill_patch", "apply", "분석 스킬 소스 적용(skill_patch --apply)"),
           ("issue_post", "approve", "Jira 코멘트 승인(issue_post approve)"),
           ("gh", "add-reviewer", "리뷰어 요청"), ("gh", "requested_reviewers", "리뷰어 요청"))
MODULE_EVAL_RE = re.compile(r"module_eval")


def _word_net():
    try:
        import guard
        return guard.word_net
    except Exception:  # noqa: BLE001 — guard를 못 불러오면 글자 포함으로 넓게 본다(거부 쪽)
        return lambda cmd, name, word: name in cmd and word in cmd


def v1_write_flow(command: str) -> str | None:
    """OpenCode v1이 돌리지 않는 쓰기 흐름이면 그 설명."""
    net = _word_net()
    for name, word, label in V1_NETS:
        try:
            hit = net(command, name, word)
        except Exception:  # noqa: BLE001
            hit = name in command and word in command
        if hit:
            return label
    if MODULE_EVAL_RE.search(re.sub(r"[\"'\\]", "", command)):
        return "모듈 스킬 평가(module_eval, 모델 호출·비용)"
    return None


# -- bash 허용 목록(v1) -------------------------------------------------------------------------------------
#
# guard는 거부 목록이라 셸 간접 실행(스크립트 파일·`python3 -c`·변수·중첩 `opencode run --pure`)을 다 볼 수 없다. 분석 전용 v1은
# 분석 흐름이 실제로 쓰는 모양만 돌린다: 플러그인 스크립트(`python3 <plugin>/scripts/<이름>.py …`)와 읽기 명령. 판정은 아래의
# 작은 셸 부분집합 파서로 한다. 펼침(`$`·`` ` ``·`*`·`{`·`~`·`\`)·대입·리디렉션(`/dev/null`과 `2>&1` 말고)·서브셸·배경 실행이
# 있으면 거부하므로, 파서가 읽은 낱말이 bash가 실제로 넘길 인자와 같다.

BASH_READ_CMDS = {"ls", "cat", "head", "tail", "wc", "grep", "pwd", "echo", "stat", "diff", "basename", "dirname",
                  "realpath", "true", "find", "git", "cd"}
BASH_PYTHON = {"python3", "python"}
FIND_DENY = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}
GIT_READ_SUBS = {"status", "log", "show", "diff", "rev-parse", "ls-files"}
GIT_DENY_OPTS = ("--output", "--ext-diff", "--textconv", "--open-files-in-pager", "--exec-path", "--git-dir",
                 "--work-tree", "--config-env", "--upload-pack", "--namespace")
SCRIPT_DENY = {"module_eval.py": "모듈 스킬 평가(module_eval, 모델 호출·비용)"}
SCRIPT_WRITE_WORDS = {"db_pr.py": {"publish": "이슈 DB push·PR(db_pr publish)", "merge": "이슈 DB PR 병합(db_pr merge)",
                                   "request-review": "리뷰어 요청(db_pr request-review)"},
                      "issue_post.py": {"approve": "Jira 코멘트 승인(issue_post approve)"}}
_WORD_CHARS = re.compile(r"[A-Za-z0-9_./,:=@%+^-]")
_REDIRECT_NULL = re.compile(r"[ \t]*/dev/null(?=$|[ \t\n;&|])")
_OP_END = " \t\n;&|"
ALLOWLIST_HELP = ("OpenCode v1(분석 전용) bash는 분석 흐름의 스크립트(`python3 \"<plugin>/scripts/<이름>.py\" …`, 절대 경로)와 "
                  "읽기 명령(" + "·".join(sorted(BASH_READ_CMDS)) + ")만 돌린다")


class ShellSubsetError(ValueError):
    pass


def split_bash(command: str) -> list[list[str]]:
    """셸 부분집합 → 명령(낱말 목록) 목록. `|`·`||`·`&&`·`;`·줄바꿈으로 나눈다. 부분집합 밖이면 ShellSubsetError."""
    segments: list[list[str]] = [[]]
    word: list[str] | None = None
    ops: list[str] = []
    i, n = 0, len(command)

    def end_word():
        nonlocal word
        if word is not None:
            segments[-1].append("".join(word))
            word = None

    def new_segment(op: str):
        end_word()
        if not segments[-1]:
            raise ShellSubsetError(f"`{op}` 앞에 명령이 없다")
        ops.append(op)
        segments.append([])

    while i < n:
        c = command[i]
        if c in " \t":
            end_word()
            i += 1
        elif c == "'":
            j = command.find("'", i + 1)
            if j < 0:
                raise ShellSubsetError("닫히지 않은 '")
            word = (word or []) + [command[i + 1:j]]
            i = j + 1
        elif c == '"':
            j = i + 1
            while j < n and command[j] != '"':
                if command[j] in "$`\\":
                    raise ShellSubsetError(f"큰따옴표 안의 `{command[j]}`(펼침)는 쓰지 않는다")
                j += 1
            if j >= n:
                raise ShellSubsetError('닫히지 않은 "')
            word = (word or []) + [command[i + 1:j]]
            i = j + 1
        elif c in "|;&\n":
            two = command[i:i + 2]
            if two in ("||", "&&"):
                new_segment(two)
                i += 2
            elif c == "&" or two in ("|&", ";;"):
                raise ShellSubsetError(f"`{two if two in ('|&', ';;') else c}`(배경 실행·특수 연산자)는 쓰지 않는다")
            else:
                new_segment(c if c != "\n" else "줄바꿈")
                i += 1
        elif c in "<>":
            fd = "".join(word) if word is not None else ""
            if word is not None and fd not in ("1", "2"):
                raise ShellSubsetError(f"리디렉션 `{c}`는 /dev/null과 2>&1만 쓴다(낱말에 붙은 리디렉션)")
            word = None
            rest = command[i + 1:]
            if c == ">" and fd == "2" and rest.startswith("&1") and (len(rest) == 2 or rest[2] in _OP_END):
                i += 3
                continue
            m = _REDIRECT_NULL.match(rest) if not (c == "<" and fd) else None
            if not m:
                raise ShellSubsetError(f"리디렉션 `{fd}{c}`는 /dev/null과 2>&1만 쓴다(파일 쓰기·읽기는 도구로)")
            i += 1 + m.end()
        elif _WORD_CHARS.match(c) or (ord(c) > 127 and c.isalnum()):
            word = (word or []) + [c]
            i += 1
        else:
            raise ShellSubsetError(f"따옴표 밖의 `{c}`(펼침·서브셸·글롭·이스케이프)는 쓰지 않는다")
    end_word()
    if not segments[-1]:
        if len(segments) == 1:
            raise ShellSubsetError("빈 명령")
        if ops[-1] not in (";", "줄바꿈"):
            raise ShellSubsetError(f"`{ops[-1]}` 뒤에 명령이 없다")
        segments.pop()          # 끝의 `;`·줄바꿈은 bash도 받는다
    return segments


def _check_python(words: list[str]) -> tuple[str | None, str | None]:
    """(거부 사유, 쓰기 흐름 설명). 둘 다 None이면 허용."""
    if len(words) < 2 or words[1].startswith("-"):
        return "python은 플러그인 스크립트 경로를 첫 인자로만 부른다(-c·-m·옵션·대화형 금지)", None
    script = words[1]
    if not os.path.isabs(script):
        return f"스크립트 `{script}`는 절대 경로로 부른다", None
    real, root = os.path.realpath(script), os.path.realpath(SCRIPTS)
    if not real.startswith(root + os.sep) or not real.endswith(".py"):
        return f"`{script}`는 플러그인 스크립트({root}/…py)가 아니다", None
    name, rest = os.path.basename(real), words[2:]
    if name in SCRIPT_DENY:
        return None, SCRIPT_DENY[name]
    for word, label in SCRIPT_WRITE_WORDS.get(name, {}).items():
        if word in rest:
            return None, label
    if name == "skill_patch.py" and any(len(w.split("=")[0]) >= 3 and "--apply".startswith(w.split("=")[0]) for w in rest):
        return None, "분석 스킬 소스 적용(skill_patch --apply)"
    return None, None


def _check_read(words: list[str]) -> str | None:
    cmd, args = words[0], words[1:]
    if cmd == "cd":
        return None if len(args) == 1 else "cd는 폴더 하나만 받는다"
    if cmd == "find":
        bad = sorted(set(args) & FIND_DENY)
        return f"find {' '.join(bad)}(실행·쓰기)는 쓰지 않는다" if bad else None
    if cmd == "git":
        i = 0
        while i < len(args) and args[i] in ("-C", "--no-pager", "-P"):
            i += 2 if args[i] == "-C" else 1
        if i >= len(args) or args[i] not in GIT_READ_SUBS:
            return f"git은 읽기 하위 명령({'·'.join(sorted(GIT_READ_SUBS))})만 쓴다(앞 옵션은 -C·--no-pager만)"
        bad = [a for a in args[i + 1:] if a.split("=")[0].startswith(GIT_DENY_OPTS) or a.startswith("-O")]
        return f"git 옵션 {' '.join(bad)}(파일 쓰기·외부 명령)는 쓰지 않는다" if bad else None
    return None


@dataclass
class BashVerdict:
    deny: str | None = None
    flow: str | None = None


def bash_allowlist(command: str) -> BashVerdict:
    """v1 bash 허용 목록 판정. flow는 사용자가 직접 실행할 쓰기 흐름(정확한 명령을 보인다)."""
    try:
        segments = split_bash(command)
    except ShellSubsetError as exc:
        return BashVerdict(deny=str(exc))
    for words in segments:
        head = words[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            return BashVerdict(deny=f"환경변수 대입(`{head.split('=')[0]}=`)은 쓰지 않는다")
        if head in BASH_PYTHON:
            why, flow = _check_python(words)
            if why or flow:
                return BashVerdict(deny=why, flow=flow)
        elif head in BASH_READ_CMDS:
            why = _check_read(words)
            if why:
                return BashVerdict(deny=why)
        else:
            return BashVerdict(deny=f"`{head}`는 허용 목록 밖이다")
    return BashVerdict()


# -- 보호 경로(edit·write·apply_patch) ------------------------------------------------------------------

PROTECTED_NAMES = {"opencode.json", "opencode.jsonc", "tt-oc.json", "AGENTS.md", "CLAUDE.md", "CONTEXT.md"}


def _real(path: str) -> str:
    """없는 끝 부분은 그대로 두고 있는 앞 부분만 실제 경로로(심볼릭 링크 폴더로 돌아가는 것을 막는다)."""
    head, tail = path, []
    while head and not os.path.exists(head) and os.path.dirname(head) != head:
        head, part = os.path.dirname(head), os.path.basename(head)
        tail.append(part)
    return os.path.join(os.path.realpath(head), *reversed(tail))


def protected_target(target: str, directory: str, env: dict | None = None) -> str | None:
    """guard·OpenCode 설정·지시 파일을 바꿀 수 있는 경로면 그 이유. 설정의 edit deny와 겹치는 다중 방어다."""
    env = os.environ if env is None else env
    real = _real(target)
    config_home = Path(env.get("XDG_CONFIG_HOME") or Path(env.get("HOME") or Path.home()) / ".config")
    roots = [(os.path.realpath(PLUGIN_ROOT), "플러그인 루트"),
             (os.path.realpath(os.path.join(directory, ".opencode")), "프로젝트 .opencode/"),
             (os.path.realpath(config_home / "opencode"), "OpenCode 전역 설정")]
    for root, label in roots:
        if real == root or real.startswith(root + os.sep):
            return label
    if os.path.basename(real) in PROTECTED_NAMES:
        return f"설정·지시 파일({os.path.basename(real)})"
    return None


# -- hook 실행 -----------------------------------------------------------------------------------------


@dataclass
class HookRun:
    decision: str           # allow | deny | ask
    reason: str
    warnings: list[str]
    stdout: str = ""


def run_script(script: str, event: dict, timeout: float, env: dict | None = None) -> subprocess.CompletedProcess | str:
    """`python3 <plugin>/scripts/<script>`에 hook 입력을 준다(hooks.json과 같은 진입점). 실패는 사유 문자열."""
    if timeout <= 0:
        return "시간 예산을 다 썼다"
    run_env = dict(os.environ if env is None else env)
    run_env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    cwd = event.get("cwd") if os.path.isdir(str(event.get("cwd") or "")) else None
    try:
        return subprocess.run([sys.executable, str(SCRIPTS / script)], input=json.dumps(event, ensure_ascii=False),
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              env=run_env, cwd=cwd, check=False)
    except subprocess.TimeoutExpired:
        return f"{script} 시간 초과({timeout:.0f}초)"
    except OSError as exc:
        return f"{script} 실행 실패({type(exc).__name__})"


def run_guard(event: dict, timeout: float, env: dict | None = None) -> HookRun:
    """바뀌지 않은 guard.py를 돌려 결정을 읽는다. 닫힘 실패: 시그널·종료 코드≠0·시간 초과·JSON 아님·모르는 결정은 거부."""
    proc = run_script("guard.py", event, timeout, env)
    if isinstance(proc, str):
        return HookRun("deny", f"guard 판정 실패: {proc}", [])
    warnings = [ln.strip() for ln in (proc.stderr or "").splitlines() if ln.strip()]
    out = (proc.stdout or "").strip()
    decision, reason = "allow", ""
    if out:
        try:
            spec = json.loads(out)["hookSpecificOutput"]
            decision, reason = spec["permissionDecision"], str(spec.get("permissionDecisionReason") or "")
        except (ValueError, KeyError, TypeError):
            return HookRun("deny", "guard 출력을 읽지 못했다", warnings, out)
        if decision not in ("allow", "deny", "ask"):
            return HookRun("deny", f"guard 결정 `{decision}`을 모른다", warnings, out)
    if proc.returncode != 0:
        why = "시그널" if proc.returncode < 0 else "종료 코드"
        return HookRun("deny", f"guard 비정상 종료({why} {proc.returncode}){': ' + reason if reason else ''}", warnings, out)
    return HookRun(decision, reason, warnings, out)


def _ask_text(mapped: Mapped, payload: dict) -> str:
    if mapped.kind == BASH and mapped.command:
        return ASK_PREFIX + mapped.command
    if mapped.kind == "mcp":
        args = json.dumps(payload.get("args") or {}, ensure_ascii=False)
        return (ASK_PREFIX + f"(Claude Code에서) {mapped.events[0]['tool_name']} {args[:400]} — "
                "guard 확인 창이 승인 단계다")
    paths = ", ".join(e["tool_input"].get("file_path", "") for e in mapped.events)
    return ASK_PREFIX + f"(직접 편집) {paths}"


def before(payload: dict, env: dict | None = None, servers: list[str] | None = None) -> dict:
    env = os.environ if env is None else env
    result = {"decision": "deny", "reason": "", "warnings": [], "events": []}
    refused = refused_env(env)
    if refused:
        result["reason"] = (f"[telephony-triage] 설정을 덮는 환경변수({', '.join(refused)})가 있어 모든 도구를 거부한다. "
                            "환경변수를 지우고 tt-oc로 다시 시작한다.")
        return result
    servers_error = None
    if servers is None:
        servers, servers_error = mcp_servers(str(payload.get("directory") or ""), env)
    mapped = map_tool(payload, servers, servers_error)
    result["events"] = [e["tool_name"] for e in mapped.events]
    if mapped.deny:
        result["reason"] = f"[telephony-triage] {mapped.deny}"
        return result
    if not mapped.events:
        result["decision"] = "allow"
        return result
    if mapped.kind == BASH:
        flow = v1_write_flow(mapped.events[0]["tool_input"]["command"])
        if flow:
            result["reason"] = f"[telephony-triage] {flow}는 OpenCode v1(분석 전용)에서 돌리지 않는다. {ASK_PREFIX}{mapped.command}"
            return result
    if mapped.kind in (FILE, PATCH):
        for event in mapped.events:
            why = protected_target(event["tool_input"]["file_path"], directory_of(payload), env)
            if why:
                result["reason"] = (f"[telephony-triage] {event['tool_input']['file_path']}: {why}는 OpenCode에서 고치지 않는다"
                                    "(guard·설정 보호).")
                return result
    if mapped.kind == "mcp":
        try:
            view = tracker_view()
        except Exception as exc:  # noqa: BLE001 — Jira 판별 불가: MCP 전체 거부(guard 설정 오류와 같은 범위)
            result["reason"] = f"[telephony-triage] 트래커 설정을 읽지 못해 MCP 도구를 거부한다({type(exc).__name__})."
            return result
        from common import mcptools
        for event in mapped.events:
            name = event["tool_name"]
            if view.comment_tool and mcptools.normalize(name) == view.comment_tool:
                result["reason"] = ("[telephony-triage] Jira 코멘트 게시는 OpenCode v1에서 하지 않는다. "
                                    "issue_post.py render → approve → 게시는 Claude Code에서 한다.")
                return result
            if is_jira(name, view) and not jira_gate_open(env):
                result["reason"] = (f"[telephony-triage] Jira MCP 도구({name})는 OpenCode에서 jira_bridge 마스킹 다리가 출시 관문을 "
                                    "넘기 전까지 쓰지 않는다. Jira 읽기는 Claude Code에서 한다.")
                return result
    # hooks.json timeout을 호출 전체의 예산으로 쓴다(apply_patch 경로 여러 개도 합쳐서) — 플러그인 timeout은 이보다 길다
    budget = HOOK_TIMEOUT["Bash" if mapped.kind == BASH else "mcp" if mapped.kind == "mcp" else "file"]
    deadline = time.monotonic() + budget
    denies, asks = [], []
    for event in mapped.events:
        got = run_guard(event, deadline - time.monotonic(), env)
        result["warnings"] += got.warnings
        if got.decision == "deny":
            denies.append(got.reason)
        elif got.decision == "ask":
            asks.append(got.reason)
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    if denies:
        result["reason"] = _marked("\n".join(dict.fromkeys(denies)))
    elif asks:
        result["reason"] = _marked("\n".join(dict.fromkeys(asks)) + "\n" + _ask_text(mapped, payload))
    elif mapped.kind == BASH:
        # guard가 허용한 bash도 v1 허용 목록을 넘어야 돈다(guard 뒤에 보는 것은 guard의 구체적인 거부·확인 문구를 살리려고)
        verdict = bash_allowlist(mapped.events[0]["tool_input"]["command"])
        if verdict.flow:
            result["reason"] = (f"{MARK} {verdict.flow}는 OpenCode v1(분석 전용)에서 돌리지 않는다. "
                                f"{ASK_PREFIX}{mapped.command}")
        elif verdict.deny:
            result["reason"] = (f"{MARK} bash 허용 목록: {verdict.deny}. {ALLOWLIST_HELP}. 다른 모양으로 다시 시도하지 말고 "
                                "이 메시지를 그대로 보인 뒤 턴을 끝낸다.")
        else:
            result["decision"] = "allow"
    else:
        result["decision"] = "allow"
    return result


MARK = "[telephony-triage]"


def _marked(reason: str) -> str:
    """막힌 호출 표시: tt-oc가 거부를 알아보도록 모든 거부 사유는 `MARK`로 시작한다(guard 사유는 그대로 뒤에 둔다)."""
    return reason if reason.startswith(MARK) else f"{MARK} {reason}"


def directory_of(payload: dict) -> str:
    return os.path.realpath(str(payload.get("directory") or "/"))


def after(payload: dict, env: dict | None = None, servers: list[str] | None = None) -> dict:
    """MCP 결과를 jira_bridge(PostToolUse)에 통과시킨다. 내장 도구는 그대로. 실패는 오류 문구로 바꾼다(닫힘)."""
    env = os.environ if env is None else env
    tool = str(payload.get("tool") or "")
    if tool in BUILTINS:
        return {"replace": None}
    servers_error = None
    if servers is None:
        servers, servers_error = mcp_servers(str(payload.get("directory") or ""), env)
    mapped = map_tool(payload, servers, servers_error)
    if mapped.deny or mapped.kind != "mcp":
        return {"replace": BRIDGE_FAILED}
    content = payload.get("content")
    response = {"content": content} if isinstance(content, list) else content
    replace = None
    for pre in mapped.events:
        event = {**pre, "hook_event_name": "PostToolUse", "tool_response": response}
        proc = run_script("jira_bridge.py", event, BRIDGE_TIMEOUT, env)
        if isinstance(proc, str) or proc.returncode != 0:
            return {"replace": BRIDGE_FAILED}
        out = (proc.stdout or "").strip()
        if not out:
            continue
        try:
            text = json.loads(out)["hookSpecificOutput"]["updatedToolOutput"]
        except (ValueError, KeyError, TypeError):
            return {"replace": BRIDGE_FAILED}
        if not isinstance(text, str):
            return {"replace": BRIDGE_FAILED}
        replace = replace if replace is not None else text
    return {"replace": replace}


# -- CLI -----------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    mode = argv[0] if argv else ""
    if mode not in ("before", "after", "env-check"):
        print("usage: oc_adapter.py (before | after | env-check)  # stdin: OpenCode 도구 호출 JSON", file=sys.stderr)
        return 2
    if mode == "env-check":
        print(json.dumps({"refused": refused_env()}))
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise TypeError("객체가 아니다")
        out = before(payload) if mode == "before" else after(payload)
    except Exception as exc:  # noqa: BLE001 — 닫힘: before는 거부, after는 오류 문구
        print(f"[telephony-triage] oc_adapter {mode} 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        out = ({"decision": "deny", "reason": f"[telephony-triage] oc_adapter 내부 오류({type(exc).__name__})로 거부한다.",
                "warnings": [], "events": []} if mode == "before" else {"replace": BRIDGE_FAILED})
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
