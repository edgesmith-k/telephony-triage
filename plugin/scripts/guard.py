#!/usr/bin/env python3
"""guard.py — Claude Code PreToolUse hook 판정 (08-safety.md §9, contracts.md §3.2).

    stdin: hook 입력 JSON ({tool_name, tool_input, cwd, ...})
    stdout: 권한 결정 JSON {"hookSpecificOutput": {"hookEventName": "PreToolUse",
            "permissionDecision": "deny"|"ask", "permissionDecisionReason": "..."}}
            판정할 것이 없으면 아무것도 내지 않는다(평소 권한 흐름). 종료 코드는 항상 0.

`hooks/hooks.json`의 matcher는 도구 이름까지만 거른다. 명령 내용·서버 판정은 여기서 한다.

TODO(SITE:S1) hook 입력 필드(`tool_name`, `tool_input.command|file_path|notebook_path`, `cwd`)와 권한 결정 출력
형식(`hookSpecificOutput.permissionDecision`)을 사내 Claude Code 버전에서 확인한다 (사외 빈 플러그인 실험도 미확인).
TODO(SITE:S3) 플러그인 hook에 보이는 MCP 도구 이름이 `mcp__<server>__<tool>`이고 `<server>`가 config
`jira.mcp_server`를 `[^A-Za-z0-9_-]`→`_`로 바꾼 문자열인지 확인한다 (치환 규칙은 관측 기반 추정, `mcptools.server_segment`).

| # | 규칙 | 대상 |
|---|---|---|
| 2 | Jira 쓰기 차단: Jira 서버(`jira.mcp_server`와 `jira.tools` 도구 이름의 서버 접두사, 이름 정규화) 도구 중 `jira.read_tools`(전체 이름, 정규화 비교)에 없는 것은 거부 | `mcp__.*` |
| 3 | PII 검사: `git commit`이면 `mask_pii --check --staged` | Bash, 이슈 DB |
| 4 | 생성 파일 정합성: `git commit`이면 `db_build --verify --staged`(`actions-build`면 생성 파일 staged 거부), `.cache/` staged 거부 | Bash, 이슈 DB |
| 5 | hook 우회 차단: 커밋의 `--no-verify`·`-n`, `-c core.hooksPath=…`(모든 git 명령), 유효 `core.hooksPath`가 정확히 `.githooks`가 아니면 커밋 거부, `core.hooksPath`를 바꾸거나 해제하는 `git config` 거부(정확히 `.githooks`로 설정은 허용) | Bash, 이슈 DB |
| 6 | base 브랜치 push 차단: refspec의 대상 ref(없으면 현재 브랜치), `--all`/`--mirror`, push `--no-verify` | Bash, 이슈 DB |
| 7 | push 확인 강제: 이슈 DB `git push`와 `db_pr.py publish`는 `ask` (옵션 `--commit`·`--and-discard`와 무관: `publish` 토큰만 본다) | Bash |
| 8 | 사용자 clone 직접 편집 차단: 대상 파일이 `issue_db.path` 안이면 거부(`work_dir` 아래는 제외) | Write/Edit/MultiEdit/NotebookEdit |
| 10 | 로그 원문 통독 차단: cat·tac·nl·less·more·bat·strings·zcat·zless·bzcat·xzcat, `head/tail -c`, `unzip -p/-c`가 로그 원문·zip·bugreport·`events*.json`·`jira_raw.json`·`match.json`을 통째로 읽으면 거부(`fixtures/`·`draft/` 제외, 사용자 config와 무관) | Bash |

(1번은 SessionStart의 `config.py sync-scripts-path`다.)

**레포 판별**: git 규칙은 명령의 작업 디렉토리(cwd, `cd <dir>`, `git -C <dir>`)에서
`git rev-parse --git-common-dir`를 구해 config `issue_db.path`의 것과 같을 때만(그 worktree·읽기 스냅샷 포함) 적용한다.

**명령 파싱은 최선 노력**이다: `;`/`&&`/`||`/`|`/줄바꿈으로 이은 명령, `cd <dir>`, 앞의 환경변수 대입과
래퍼(`WRAPPERS`: env·timeout·nice·ionice·stdbuf·sudo·setsid·time·exec·nohup·command), `sh -c`/`bash -c` 안쪽(중첩 한도 있음),
heredoc 본문 제외. 변수 치환·별칭·백틱·`$( )`·`GIT_DIR=`·표 밖 래퍼·스크립트 파일 안의 git 호출은 보지 못한다.
진짜 강제는 git hook(pre-commit·pre-push)과 GHE 브랜치 보호다.

**설정 없음**: 사용자 config가 없거나 `issue_db.path`로 레포를 판별할 수 없으면 git·파일 규칙은 적용하지 않는다.
`jira.mcp_server`와 `jira.tools`가 모두 비어 있으면 Jira 규칙은 적용하지 않고 경고만 한다. `jira.read_tools`가 비어 있으면 그 서버 도구는
모두 거부한다. hook은 모든 도구 호출에 걸리므로, `site-defaults.yaml`이 없어도 guard는 멈추지 않고 사용자 config만으로
판정한다(경고). 이때 커밋 검사(3·4번)가 부르는 스크립트는 종료 코드 2를 내므로 이슈 DB 커밋은 거부된다.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import checks, mcptools, site_defaults, userconfig  # noqa: E402

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
HOOKS_PATH_KEY = "core.hookspath"
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n", "|&", ";;"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
MAX_DEPTH = 3
# 다른 명령을 실행하는 앞 래퍼: 이름 → (값을 다음 토큰으로 받는 옵션, 옵션 뒤 건너뛸 위치 인자 수).
# 값이 붙은 옵션(`-oL`, `--signal=KILL`, `nice -5`)은 한 칸. 표 밖 래퍼(xargs·watch·flock 등)는 보지 못한다.
WRAPPERS = {
    "env": ({"-u", "--unset", "-C", "--chdir"}, 0), "command": (set(), 0), "builtin": (set(), 0),
    "nohup": (set(), 0), "setsid": (set(), 0), "exec": ({"-a"}, 0),
    "time": ({"-f", "--format", "-o", "--output"}, 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1), "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "--class", "-n", "--classdata"}, 0),
    "stdbuf": ({"-i", "-o", "-e", "--input", "--output", "--error"}, 0),
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group", "--host",
              "--prompt", "--chdir"}, 0),
}
CHDIR_OPTS = {"env": {"-C", "--chdir"}, "sudo": {"-D", "--chdir"}}
HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

# 규칙 10: 로그 원문 통독 차단
RAW_ALWAYS_CMDS = {"cat", "tac", "nl", "less", "more", "bat", "strings", "zcat", "zless", "bzcat", "xzcat"}
RAW_NAMES = {"events.json", "events-full.json", "jira_raw.json", "match.json"}
RAW_EXEMPT_DIRS = {"fixtures", "draft"}
RAW_GLOB_MAX = 20
RAW_SNIFF_BYTES = 8192
RAW_SNIFF_LINES = 30
REDIRECT_RE = re.compile(r"^(?:\d*>>?|\d*>&|&>>?)(.*)$")

# git 전역 옵션 중 값을 받는 것 (값이 다음 토큰)
GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env",
                       "--super-prefix", "--list-cmds", "--attr-source"}
# git commit 옵션 중 값을 다음 토큰으로 받는 것
COMMIT_LONG_WITH_ARG = {"--message", "--file", "--author", "--date", "--template", "--reuse-message",
                        "--reedit-message", "--fixup", "--squash", "--cleanup", "--trailer", "--pathspec-from-file"}
COMMIT_SHORT_WITH_ARG = set("mFCct")
PUSH_LONG_WITH_ARG = {"--repo", "--receive-pack", "--exec", "--push-option"}
PUSH_SHORT_WITH_ARG = set("o")
CONFIG_WITH_ARG = {"--file", "-f", "--blob", "--type", "--default", "--comment", "--value", "--fixed-value"}
CONFIG_READ_ACTIONS = {"get", "get-all", "get-regexp", "get-urlmatch", "get-color", "get-colorbool", "list",
                       "name-only", "show-origin", "show-scope"}
CONFIG_SUBCOMMANDS = {"get", "set", "unset", "list", "edit", "rename-section", "remove-section"}


# -- 결정 --------------------------------------------------------------------------------


class Decision:
    def __init__(self):
        self.deny: list[str] = []
        self.ask: list[str] = []
        self.warn: list[str] = []

    def output(self) -> dict | None:
        if self.deny:
            return _decision("deny", "\n".join(dict.fromkeys(self.deny)))
        if self.ask:
            return _decision("ask", "\n".join(dict.fromkeys(self.ask)))
        return None


def _decision(kind: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": kind,
                                   "permissionDecisionReason": f"[telephony-triage] {reason}"}}


# -- 설정 --------------------------------------------------------------------------------


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.realpath(str(p)))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


class Config:
    def __init__(self, plugin_root: str | None = None):
        self.warnings: list[str] = []
        try:
            defaults = site_defaults.load(Path(plugin_root) if plugin_root else None)
        except site_defaults.SiteDefaultsMissing:
            defaults = {}
            self.warnings.append("site-defaults.yaml이 없다 (S-3 미완료). 사용자 config만으로 판정한다.")
        self.plugin_root = plugin_root
        self.raw_names, self.raw_exempt = self._raw_read(defaults)
        self.user = userconfig.load_user()
        self.cfg = userconfig.merged(defaults, self.user or {})
        self.clone = None
        self.clone_common = None
        self.work_dir = None
        if self.user:
            clone = userconfig.get(self.user, "issue_db.path")
            if clone and Path(str(clone)).expanduser().is_dir():
                self.clone = Path(str(clone)).expanduser()
                self.clone_common = _common_dir(self.clone)
            self.work_dir = Path(str(userconfig.get(self.cfg, "work_dir"))).expanduser()
        self.base = str(userconfig.get(self.cfg, "issue_db.base_branch") or "main")

    def _raw_read(self, defaults: dict) -> tuple[set, set]:
        """규칙 10 목록: 내장 ∪ site-defaults `guard.raw_read`. 잘못된 값은 경고하고 내장만 쓴다."""
        names, exempt = set(RAW_NAMES), set(RAW_EXEMPT_DIRS)
        guard = defaults.get("guard")
        site = guard.get("raw_read") if isinstance(guard, dict) else guard
        if site is None:
            return names, exempt
        ok = isinstance(site, dict) and set(site) <= {"names", "exempt_dirs"} and all(
            isinstance(site.get(k, []), list)
            and all(isinstance(v, str) and v and "/" not in v and "\\" not in v for v in site.get(k, []))
            for k in ("names", "exempt_dirs"))
        if not ok:
            self.warnings.append("site-defaults의 guard.raw_read가 {names: [문자열], exempt_dirs: [문자열]} 형식이 "
                                 "아니다. 내장 목록만 쓴다.")
            return names, exempt
        return names | set(site.get("names", [])), exempt | set(site.get("exempt_dirs", []))

    @property
    def git_rules(self) -> bool:
        return self.clone_common is not None


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _common_dir(cwd: Path) -> str | None:
    if not cwd.is_dir():
        return None
    proc = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return _norm(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


# -- Jira (2) --------------------------------------------------------------------------------


def check_mcp(tool: str, conf: Config, dec: Decision) -> None:
    # Jira 서버 접두사: mcp_server ∪ jira.tools 이름의 서버 (플러그인 번들 `mcp__plugin_…`도 덮는다). 넓을수록 안전 쪽
    server = userconfig.get(conf.cfg, "jira.mcp_server")
    tools = userconfig.get(conf.cfg, "jira.tools")
    prefixes = {mcptools.full_name(str(server), "")} if server else set()
    prefixes |= {mcptools.server_prefix(v) for v in (tools.values() if isinstance(tools, dict) else [])
                 if mcptools.server_prefix(v)}
    if not prefixes:
        dec.warn.append("jira.mcp_server가 비어 있어 Jira 읽기 전용 규칙을 적용하지 않았다 (setup 전).")
        return
    name = mcptools.normalize(tool)
    if not any(name.startswith(p) for p in prefixes):
        return   # 다른 MCP 서버 도구는 영향 없음
    read_tools = userconfig.get(conf.cfg, "jira.read_tools") or []
    if name not in {mcptools.normalize(t) for t in read_tools}:
        dec.deny.append(f"이 플러그인은 Jira 읽기 전용이다. {tool}은(는) jira.read_tools에 없어 거부한다 (규칙 2).")


# -- 파일 도구 (8) -------------------------------------------------------------------------


def check_file(tool_input: dict, cwd: Path, conf: Config, dec: Decision) -> None:
    if conf.clone is None:
        return
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = cwd / path
    target = _norm(path)
    if conf.work_dir is not None and _inside(target, _norm(conf.work_dir)):
        return
    if _inside(target, _norm(conf.clone)):
        dec.deny.append("이슈 DB clone은 도구가 직접 고치지 않는다. 직접 편집은 사용자가 한다 "
                        f"(규칙 8: {raw}). 도구 변경은 작업 계획과 db_pr stage로 작업 worktree에서 만든다.")


# -- Bash 명령 파싱 ------------------------------------------------------------------------


def _strip_heredocs(command: str) -> str:
    """heredoc 본문을 뺀다 (본문의 글자를 명령으로 읽지 않게)."""
    lines = command.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for m in HEREDOC_RE.finditer(line):
            tag = m.group(2)
            while i < len(lines) and lines[i].strip() != tag:
                i += 1
            i += 1
    return "\n".join(out)


def _tokens(command: str) -> list[str]:
    text = _strip_heredocs(command).replace("\n", " \n ")
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    try:
        return list(lex)
    except ValueError:   # 따옴표 불균형 등: 공백으로만 나눈다 (보수적)
        return re.split(r"[ \t\r]+", text)


def _segments(tokens: list[str]) -> list[list[str]]:
    segs, cur = [], []
    for tok in tokens:
        if tok in SEPARATORS or (tok and set(tok) <= set(";&|()")):
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        segs.append(cur)
    return segs


def _expand(word: str) -> str:
    return os.path.expanduser(os.path.expandvars(word))


def _strip_prefix(seg: list[str], cwd: Path) -> tuple[list[str], Path]:
    """앞의 `VAR=값`과 래퍼(`WRAPPERS`: env·timeout·nice·sudo 등)를 옵션째 뗀다. `env -S`는 풀어 읽고,
    `env -C`·`sudo -D`는 작업 디렉토리로 반영한다."""
    i = 0
    while i < len(seg):
        tok = seg[i]
        name = _base(tok)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
            continue
        if name not in WRAPPERS:
            break
        with_arg, positional = WRAPPERS[name]
        i += 1
        while i < len(seg) and seg[i].startswith("-"):
            opt = seg[i]
            if opt == "--":
                i += 1
                break
            # 값 받는 옵션(이름, 값, 차지한 토큰 수): 긴 옵션은 `--x=v`|`--x v`, 짧은 묶음(`-Eu x`, `-vS'…'`, `-C/dir`)은
            # 값 받는 첫 글자에서 멈추고 묶음 나머지가 값(없으면 다음 토큰)
            key, value, used = None, None, 1
            takes = with_arg | ({"-S", "--split-string"} if name == "env" else set())
            if opt.startswith("--"):
                key, eq, value = opt.partition("=")
                if not eq:
                    value, used = (seg[i + 1], 2) if key in takes and i + 1 < len(seg) else (None, 1)
            else:
                for k, ch in enumerate(opt[1:], 1):
                    if "-" + ch in takes:
                        key, value = "-" + ch, opt[k + 1:]
                        if not value:
                            value, used = (seg[i + 1], 2) if i + 1 < len(seg) else ("", 1)
                        break
            if key in ("-S", "--split-string") and value is not None:
                try:
                    split = shlex.split(value)
                except ValueError:
                    split = value.split()
                seg = seg[:i] + split + seg[i + used:]
                continue   # 풀린 토큰을 다시 옵션·명령으로 읽는다
            if key in CHDIR_OPTS.get(name, set()) and value:
                d = _expand(value)
                cwd = Path(d) if Path(d).is_absolute() else cwd / d
            i += used
        i += positional
    return seg[i:], cwd


def _base(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


class Invocation:
    def __init__(self, cwd: Path, argv: list[str]):
        self.cwd = cwd
        self.argv = argv


def invocations(command: str, cwd: Path, depth: int = 0) -> list[Invocation]:
    out: list[Invocation] = []
    for seg in _segments(_tokens(command)):
        seg, seg_cwd = _strip_prefix(seg, cwd)
        if not seg:
            continue
        name = _base(seg[0])
        if name in ("cd", "pushd"):
            args = [a for a in seg[1:] if not a.startswith("-")]
            target = _expand(args[0]) if args else str(Path.home())
            cwd = Path(target) if Path(target).is_absolute() else cwd / target
            continue
        if name in SHELLS and depth < MAX_DEPTH:
            for i, tok in enumerate(seg[1:], 1):
                if tok.startswith("-") and not tok.startswith("--") and "c" in tok[1:] and i + 1 < len(seg):
                    out += invocations(seg[i + 1], seg_cwd, depth + 1)
                    break
            continue
        out.append(Invocation(seg_cwd, seg))
    return out


# -- git 명령 판정 ----------------------------------------------------------------------------


class GitCall:
    """`git [전역 옵션] <sub> <args>`를 나눈다."""

    def __init__(self, inv: Invocation):
        argv = inv.argv
        cwd = inv.cwd
        self.config_overrides: list[str] = []
        self.sub = None
        self.args: list[str] = []
        i = 1
        while i < len(argv):
            tok = argv[i]
            if tok == "-C" and i + 1 < len(argv):
                d = _expand(argv[i + 1])
                cwd = Path(d) if Path(d).is_absolute() else cwd / d
                i += 2
            elif tok == "-c" and i + 1 < len(argv):
                self.config_overrides.append(argv[i + 1])
                i += 2
            elif tok.startswith("--config-env="):
                self.config_overrides.append(tok.split("=", 1)[1])
                i += 1
            elif tok.startswith("--git-dir="):
                d = _expand(tok.split("=", 1)[1])
                cwd = Path(d) if Path(d).is_absolute() else cwd / d
                i += 1
            elif tok in GIT_GLOBAL_WITH_ARG:
                if tok == "--config-env" and i + 1 < len(argv):
                    self.config_overrides.append(argv[i + 1])
                i += 2
            elif tok.startswith("-"):
                i += 1
            else:
                self.sub = tok
                self.args = argv[i + 1:]
                break
        self.cwd = cwd

    def overrides_hooks_path(self) -> bool:
        return any(o.split("=", 1)[0].strip().lower() == HOOKS_PATH_KEY for o in self.config_overrides)


def _is_no_verify(arg: str) -> bool:
    name = arg.split("=", 1)[0]
    return len(name) >= len("--no-v") and "--no-verify".startswith(name)


def commit_bypass(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            break
        if a.startswith("--"):
            if _is_no_verify(a):
                return a
            if a in COMMIT_LONG_WITH_ARG:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:], 1):
                if ch == "n":
                    return a
                if ch in COMMIT_SHORT_WITH_ARG:
                    if j == len(a) - 1:
                        i += 1
                    break
        i += 1
    return None


def push_targets(args: list[str]) -> tuple[list[str], dict]:
    """(위치 인자, 플래그). 위치 인자 = [원격, refspec...]."""
    pos, flags = [], {}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            flags[name] = True
            if _is_no_verify(a):
                flags["no-verify"] = True
            if a in PUSH_LONG_WITH_ARG:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for j, ch in enumerate(a[1:], 1):
                flags["-" + ch] = True
                if ch in PUSH_SHORT_WITH_ARG:
                    if j == len(a) - 1:
                        i += 1
                    break
        else:
            pos.append(a)
        i += 1
    return pos, flags


def _dst_of(spec: str, current: str | None) -> str | None:
    spec = spec.lstrip("+")
    if ":" in spec:
        return spec.split(":", 1)[1] or None
    if spec == "HEAD":
        return current
    return spec


def _branch_name(ref: str) -> str:
    return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def check_push(call: GitCall, conf: Config, dec: Decision) -> None:
    pos, flags = push_targets(call.args)
    if flags.get("no-verify"):
        dec.deny.append("git push의 --no-verify는 pre-push 검사를 건너뛰므로 금지한다 (규칙 5).")
    current = _git(call.cwd, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip() or None
    if flags.get("--all") or flags.get("--mirror") or flags.get("--branches"):
        dec.deny.append(f"--all/--mirror push는 base 브랜치({conf.base})를 포함할 수 있어 금지한다 (규칙 6).")
    specs = pos[1:]
    dsts = [_dst_of(s, current) for s in specs] if specs else [current]
    if any(s.lstrip("+") == ":" for s in specs):   # `git push origin :` = 같은 이름 브랜치 전부(matching)
        dsts.append(conf.base)
    for dst in dsts:
        if dst and _branch_name(dst) == conf.base:
            dec.deny.append(f"base 브랜치({conf.base})로 직접 push하지 않는다 (규칙 6). 브랜치를 올리고 PR을 만든다.")
    dec.ask.append("이슈 DB push다. 확인 화면(변경 파일·diff·검사 결과·커밋 메시지)을 승인한 뒤에만 진행한다 (규칙 7).")


def check_config(call: GitCall, dec: Decision) -> None:
    args = call.args
    action = None
    pos: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in CONFIG_WITH_ARG:
            i += 2
            continue
        if a.startswith("--"):
            name = a[2:].split("=", 1)[0]
            if name in CONFIG_READ_ACTIONS or name in ("unset", "unset-all", "replace-all", "add", "edit",
                                                       "remove-section", "rename-section"):
                action = action or name
        elif a == "-e":
            action = action or "edit"
        elif a == "-l":
            action = action or "list"
        elif a.startswith("-"):
            pass
        else:
            if not pos and action is None and a in CONFIG_SUBCOMMANDS:
                action = a
            else:
                pos.append(a)
        i += 1
    if action in CONFIG_READ_ACTIONS:
        return
    if action == "edit":
        dec.deny.append("이슈 DB에서 git config --edit는 core.hooksPath를 바꿀 수 있어 금지한다 (규칙 5).")
        return
    if action in ("remove-section", "rename-section"):
        if pos and pos[0].lower() == "core":
            dec.deny.append("core 섹션을 지우거나 바꾸면 core.hooksPath가 해제된다 (규칙 5).")
        return
    if not pos or pos[0].lower() != HOOKS_PATH_KEY:
        return
    if action in ("unset", "unset-all"):
        dec.deny.append("core.hooksPath 해제는 금지다 (규칙 5). git hook(pre-commit·pre-push)이 꺼진다.")
        return
    if len(pos) < 2:
        return   # 값 없이 키만: 읽기
    if pos[1] != ".githooks":
        dec.deny.append(f"core.hooksPath는 정확히 .githooks여야 한다 (규칙 5): '{pos[1]}'는 거부한다.")


def check_commit(call: GitCall, conf: Config, dec: Decision) -> None:
    flag = commit_bypass(call.args)
    if flag:
        dec.deny.append(f"git commit {flag}는 pre-commit 검사를 건너뛰므로 금지한다 (규칙 5).")
        return
    hooks = _git(call.cwd, "config", "--get", "core.hooksPath").stdout.strip()
    if hooks != ".githooks":
        dec.deny.append(f"이 레포의 core.hooksPath가 '{hooks or '(없음)'}'다. 정확히 .githooks여야 커밋할 수 있다 "
                        "(규칙 5). /telephony-triage:setup 을 다시 실행한다.")
        return
    top = _git(call.cwd, "rev-parse", "--show-toplevel").stdout.strip()
    if not top:
        return
    staged = [p for p in _git(Path(top), "diff", "--cached", "--name-only", "-z").stdout.split("\0") if p]
    if not staged:
        return
    try:
        from common import yamlio
        db_cfg = yamlio.safe_load((Path(top) / "issue-db.config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        db_cfg = {}
    ci_mode = db_cfg.get("ci_mode", "local")
    branch = _git(Path(top), "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() if ci_mode != "actions-build" else ""
    ctx = checks.Ctx(db=top, scope="staged", files=staged, branch=branch, ci_mode=ci_mode, db_cfg=db_cfg,
                     plugin_root=conf.plugin_root)
    # 단계 순서(마스킹 → 캐시 → 생성 파일)와 migrate 브랜치 허용은 common/checks.py guard 프로필이 정한다.
    # 여기서는 실패한 단계를 deny 문구로 바꾼다 (실행 불가 2도 거부다).
    dec.deny.extend(checks.guard_deny_messages(checks.run_checks(checks.PROFILES["guard"], ctx).steps))


# -- 로그 원문 통독 차단 (10) ---------------------------------------------------------------


def _raw_cmd_verb(inv: Invocation) -> str | None:
    """원문 통독이 될 수 있는 명령이면 표시용 동사(`cat`, `head -c`, `unzip -p`), 아니면 None."""
    name = _base(inv.argv[0])
    flags = [a for a in inv.argv[1:] if a.startswith("-") and a != "-"]
    if name in RAW_ALWAYS_CMDS:
        return name
    if name in ("head", "tail"):
        for a in flags:
            if a == "--bytes" or a.startswith("--bytes="):
                return f"{name} -c"
            if not a.startswith("--") and "c" in re.split(r"\d", a[1:], 1)[0]:
                return f"{name} -c"
    elif name == "unzip":
        for a in flags:
            if not a.startswith("--") and ("p" in a[1:] or "c" in a[1:]):
                return "unzip -p"
    return None


# 모든 줄에 맞는 패턴·스크립트: 통독과 같다 (보수적인 목록만)
MATCH_ALL_PATTERNS = {"", "^", ".*", "$", ".", "^.*$"}
MATCH_ALL_AWK = {"{print}", "{print$0}", "1"}
MATCH_ALL_SED = {"", "p", "1,$p", "0,$p"}
GREP_NON_DUMP_FLAGS = set("cqlL")   # 개수·존재만 내는 옵션은 통독이 아니다


def _words_and_stdin(argv: list[str]) -> tuple[list[str], list[str]]:
    """플래그를 남기고 출력 리디렉션·heredoc을 뺀 단어와, `<` 입력 파일."""
    words: list[str] = []
    stdin: list[str] = []
    skip = redir_in = False
    for tok in argv[1:]:
        if skip:
            skip = False
        elif redir_in:
            redir_in = False
            stdin.append(tok)
        elif tok.startswith("<<"):
            continue
        elif tok == "<":
            redir_in = True
        elif tok.startswith("<") and len(tok) > 1:
            stdin.append(tok[1:])
        elif tok and REDIRECT_RE.match(tok):
            skip = not REDIRECT_RE.match(tok).group(1)
        else:
            words.append(tok)
    return words, stdin


def _dump_verb_and_files(inv: Invocation) -> tuple[str, list[str]] | None:
    """grep·rg·awk·sed가 모든 줄을 내보내는 형태면 (표시 동사, 대상 인자들), 아니면 None."""
    name = _base(inv.argv[0])
    if name not in ("grep", "egrep", "fgrep", "rg", "awk", "gawk", "mawk", "sed"):
        return None
    words, stdin = _words_and_stdin(inv.argv)
    pos: list[str] = []
    pats: list[str] = []
    short_flags = ""
    quiet_kinds = False
    i = 0
    while i < len(words):
        w = words[i]
        i += 1
        if w == "--":
            pos += words[i:]
            break
        if w.startswith("--") and len(w) > 2:
            if name in ("grep", "egrep", "fgrep", "rg"):
                if w.startswith("--regexp="):
                    pats.append(w.split("=", 1)[1])
                elif w == "--regexp" and i < len(words):
                    pats.append(words[i])
                    i += 1
                elif w in ("--count", "--quiet", "--silent", "--files-with-matches", "--files-without-match"):
                    quiet_kinds = True
            elif name == "sed":
                if w.startswith("--expression="):
                    pats.append(w.split("=", 1)[1])
                elif w == "--expression" and i < len(words):
                    pats.append(words[i])
                    i += 1
                elif w in ("--quiet", "--silent"):
                    short_flags += "n"
            continue
        if w.startswith("-") and len(w) > 1:
            cluster = w[1:]
            short_flags += cluster
            takes = {"grep": "efmAB", "egrep": "efmAB", "fgrep": "efmAB", "rg": "efmABg",
                     "awk": "Fvf", "gawk": "Fvf", "mawk": "Fvf", "sed": "ef"}[name]
            # 값을 받는 옵션이 클러스터 끝에 오면 다음 단어가 값, 중간에 오면 나머지가 값
            for k, ch in enumerate(cluster):
                if ch in takes:
                    rest = cluster[k + 1:]
                    val = rest if rest else (words[i] if i < len(words) else None)
                    if not rest:
                        i += 1
                    if ch == "e" and val is not None:
                        pats.append(val)
                    elif ch in "fv" and name in ("awk", "gawk", "mawk", "sed", "grep", "egrep", "fgrep", "rg"):
                        if ch == "f":
                            pats.append("\0file")   # 파일에서 읽는 프로그램·패턴: 판단하지 않는다
                    break
            continue
        pos.append(w)
    if name in ("grep", "egrep", "fgrep", "rg"):
        if set(short_flags) & GREP_NON_DUMP_FLAGS or quiet_kinds:
            return None
        if not pats:
            if not pos:
                return None
            pats, pos = [pos[0]], pos[1:]
        hit = any(p in MATCH_ALL_PATTERNS for p in pats) and "\0file" not in pats
        if "v" in short_flags or "--invert-match" in inv.argv:
            hit = False
        verb = f"{name} {pats[0]!r}"
    elif name == "sed":
        if not pats:
            if not pos:
                return None
            pats, pos = [pos[0]], pos[1:]
        script = pats[0].replace(" ", "")
        hit = len(pats) == 1 and "\0file" not in pats and script in MATCH_ALL_SED and "i" not in short_flags
        verb = f"sed {pats[0]!r}"
    else:
        if not pats or "\0file" in pats:
            if not pos:
                return None
            prog, pos = pos[0], pos[1:]
        else:
            return None
        hit = prog.replace(" ", "").rstrip(";") in MATCH_ALL_AWK or prog.replace(" ", "") in ("{print;}",)
        verb = f"{name} {prog!r}"
    if not hit:
        return None
    return verb, pos + stdin


def _raw_args(argv: list[str]) -> list[str]:
    """위치 인자와 `<` 대상. `>`·`>>`·`2>` 등 출력 리디렉션과 heredoc은 뺀다."""
    out: list[str] = []
    skip = False
    redir_in = False
    for tok in argv[1:]:
        if skip:
            skip = False
            continue
        if redir_in:
            redir_in = False
            out.append(tok)
            continue
        if tok.startswith("<<"):
            continue
        if tok == "<":
            redir_in = True
            continue
        if tok.startswith("<") and len(tok) > 1:
            out.append(tok[1:])
            continue
        m = REDIRECT_RE.match(tok)
        if m:
            skip = not m.group(1)
            continue
        if tok.startswith("-") and tok != "-":
            continue
        out.append(tok)
    return out


def _is_raw_file(path: Path, names: set, exempt: set) -> bool:
    real = _norm(path)
    segs = real.replace("\\", "/").split("/")
    if exempt & set(segs[:-1]):
        return False
    if not os.path.isfile(real):
        return False
    if path.name in names:
        return True
    with open(real, "rb") as fh:
        head = fh.read(RAW_SNIFF_BYTES)
    if head.startswith(b"PK\x03\x04") or head.startswith(b"\x1f\x8b"):
        return True
    lines = head.decode("utf-8", errors="replace").splitlines()[:RAW_SNIFF_LINES]
    try:
        from platforms.android import logcat   # 이 명령이 나올 때만 불러온다
    except ImportError:
        logcat = None
    for line in lines:
        if logcat is not None and (logcat.THREADTIME_RE.match(line) or logcat.TIME_RE.match(line)):
            return True
        if line.startswith("== dumpstate") or (line.startswith("------ ") and line.rstrip().endswith(" ------")):
            return True
    return False


def check_raw_read(command: str, cwd: Path, dec: Decision, conf: Config) -> None:
    names, exempt = conf.raw_names, conf.raw_exempt
    for inv in invocations(command, cwd):
        verb = _raw_cmd_verb(inv)
        if verb is not None:
            args = _raw_args(inv.argv)
        else:
            dump = _dump_verb_and_files(inv)
            if dump is None:
                continue
            verb, args = dump
        for arg in args:
            word = _expand(arg)
            path = Path(word) if Path(word).is_absolute() else inv.cwd / word
            cands = [path]
            if any(ch in word for ch in "*?["):
                cands = [Path(p) for p in sorted(glob.glob(str(path)))[:RAW_GLOB_MAX]]
            for cand in cands:
                try:
                    hit = _is_raw_file(cand, names, exempt)
                except OSError:
                    hit = False
                if hit:
                    dec.deny.append(
                        "로그 원문·zip·events/jira_raw/match.json은 통째로 읽지 않는다(원칙 §로그 원문, "
                        f"규칙 10: {verb} {arg}). grep -n '<패턴>' <파일> 또는 sed -n '<a>,<b>p' <파일>로 필요한 "
                        "줄만, bugreport는 parse_logcat.py extract-bugreport. Read 도구도 limit·offset으로 구간만.")
                    return


def check_bash(command: str, cwd: Path, conf: Config, dec: Decision) -> None:
    check_raw_read(command, cwd, dec, conf)
    for inv in invocations(command, cwd):
        name = _base(inv.argv[0])
        is_db_pr = name == "db_pr.py" or (name.startswith("python")
                                           and any(_base(a) == "db_pr.py" for a in inv.argv[1:]))
        if is_db_pr and "publish" in inv.argv:
            if conf.user is not None:
                dec.ask.append("db_pr.py publish는 이슈 DB에 push한다. 확인 화면을 승인한 뒤에만 진행한다 (규칙 7).")
            continue
        if name != "git" or not conf.git_rules:
            continue
        call = GitCall(inv)
        if call.sub not in ("commit", "config", "push") and not call.overrides_hooks_path():
            continue
        if _common_dir(call.cwd) != conf.clone_common:
            continue   # 이슈 DB가 아니다: 어떤 git 규칙도 적용하지 않는다
        if call.overrides_hooks_path():
            dec.deny.append("git -c core.hooksPath=… 로 hook을 바꾸는 것은 금지다 (규칙 5).")
            continue
        if call.sub == "commit":
            check_commit(call, conf, dec)
        elif call.sub == "config":
            check_config(call, dec)
        elif call.sub == "push":
            check_push(call, conf, dec)


# -- 진입점 ----------------------------------------------------------------------------------


def judge(event: dict, plugin_root: str | None = None) -> tuple[dict | None, list[str]]:
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}
    cwd = Path(str(event.get("cwd") or os.getcwd()))
    conf = Config(plugin_root)
    dec = Decision()
    dec.warn += conf.warnings
    if tool.startswith("mcp__"):
        check_mcp(tool, conf, dec)
    elif tool in FILE_TOOLS:
        check_file(tool_input, cwd, conf, dec)
    elif tool == "Bash":
        check_bash(str(tool_input.get("command") or ""), cwd, conf, dec)
    return dec.output(), dec.warn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guard.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("[telephony-triage] guard: hook 입력이 JSON이 아니다. 판정하지 않는다.", file=sys.stderr)
        return 0
    try:
        out, warnings = judge(event, args.plugin_root)
    except Exception as exc:  # noqa: BLE001 — hook이 모든 도구 호출을 막지 않게 한다
        tool = str(event.get("tool_name") or "")
        print(f"[telephony-triage] guard 내부 오류: {exc}", file=sys.stderr)
        if tool.startswith("mcp__"):   # Jira 쓰기 차단은 guard가 유일한 장치다: 오류면 막는다
            out, warnings = _decision("deny", f"guard 내부 오류로 MCP 도구 판정을 못 했다: {exc}"), []
        else:
            return 0
    for w in warnings:
        print(f"[telephony-triage] {w}", file=sys.stderr)
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
