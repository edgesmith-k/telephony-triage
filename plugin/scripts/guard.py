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
| 2 | Jira 쓰기 차단: Jira 서버(`jira.mcp_server`와 `jira.tools` 도구 이름의 서버 접두사, 이름 정규화) 도구 중 `jira.read_tools`(전체 이름, 정규화 비교)에 없는 것은 거부. 설정되지 않은 서버라도 이름에 jira·atlassian이 들면 쓰기형 도구 거부 | `mcp__.*` |
| 3 | PII 검사: `git commit`이면 `mask_pii --check --staged` | Bash, 이슈 DB |
| 4 | 생성 파일 정합성: `git commit`이면 `db_build --verify --staged`(`actions-build`면 생성 파일 staged 거부), `.cache/` staged 거부 | Bash, 이슈 DB |
| 5 | hook 우회 차단: 커밋의 `--no-verify`·`-n`, `-c core.hooksPath=…`(모든 git 명령), 유효 `core.hooksPath`가 정확히 `.githooks`가 아니면 커밋 거부, `core.hooksPath`를 바꾸거나 해제하는 `git config` 거부(정확히 `.githooks`로 설정은 허용), `GIT_CONFIG_*`·`GIT_INDEX_FILE` 대입이 붙은 commit·push·config 거부 | Bash, 이슈 DB |
| 6 | base 브랜치 push 차단: refspec의 대상 ref(없으면 현재 브랜치), `--all`/`--mirror`, push `--no-verify` | Bash, 이슈 DB |
| 7 | push 확인 강제: 이슈 DB `git push`와 `db_pr.py publish`는 `ask` (옵션 `--commit`·`--and-discard`와 무관: `publish` 토큰만 본다) | Bash |
| 8 | 사용자 clone 직접 편집 차단: 대상 파일이 `issue_db.path` 안이면 거부(`work_dir` 아래는 제외) | Write/Edit/MultiEdit/NotebookEdit |
| 8 | 같은 규칙, Bash: clone 본체에서 브랜치·파일을 바꾸는 git·`gh pr checkout`, clone 안으로의 파일 쓰기(리디렉션·tee·cp·rm·`sed -i` 등) 거부. migrate 브랜치 생성(깨끗한 트리)은 ask | Bash, clone 본체 |
| 10 | 로그 원문 통독 차단: cat·tac·nl·less·more·bat·strings·zcat·zless·bzcat·xzcat, `head/tail -c`, `unzip -p/-c`가 로그 원문·zip·bugreport·`events*.json`·`jira_raw.json`·`match.json`을 통째로 읽으면 거부(`fixtures/`·`draft/` 제외, 사용자 config와 무관) | Bash |
| 11 | 이슈 DB 원격 쓰기 확인: 대상이 이슈 DB인 `gh` 쓰기는 ask·`pr merge`는 거부, 비Jira MCP 쓰기형 도구(`owner`/`repo` 인자)도 같게 | Bash, `mcp__.*` |

(1번은 SessionStart의 `config.py sync-scripts-path`다.)

**레포 판별**: git 규칙은 명령의 작업 디렉토리(cwd, `cd <dir>`, `git -C <dir>`)에서
`git rev-parse --git-common-dir`를 구해 config `issue_db.path`의 것과 같을 때만(그 worktree·읽기 스냅샷 포함) 적용한다.

**명령 파싱은 최선 노력**이다: `;`/`&&`/`||`/`|`/줄바꿈으로 이은 명령, `cd <dir>`, 앞의 환경변수 대입(`GIT_DIR`·`GIT_WORK_TREE` 등은
레포 판별에 반영)과 래퍼(`WRAPPERS`: env·timeout·nice·ionice·stdbuf·sudo·setsid·time·exec·nohup·command·xargs(정적 인자만)),
`sh -c`/`bash -c`/`eval` 안쪽(중첩 한도 있음), heredoc 본문 제외. 변수 치환·별칭·백틱·`$( )`·`xargs -I{}` 항목·표 밖 래퍼·
스크립트 파일 안의 git 호출은 보지 못한다.
진짜 강제는 git hook(pre-commit·pre-push)과 GHE 브랜치 보호다.

**설정 없음**: 사용자 config가 없거나 `issue_db.path`로 레포를 판별할 수 없으면 git·파일 규칙은 적용하지 않는다.
`issue_db.remote`가 없으면 11번을 적용하지 않는다.
`jira.mcp_server`와 `jira.tools`가 모두 비어 있으면 설정 서버 규칙은 적용하지 않고 경고만 한다(이름 기반 거부는 적용). `jira.read_tools`가 비어 있으면 그 서버 도구는
모두 거부한다. hook은 모든 도구 호출에 걸리므로, `site-defaults.yaml`이 없어도 guard는 멈추지 않고 사용자 config만으로
판정한다(경고). 이때 커밋 검사(3·4번)가 부르는 스크립트는 종료 코드 2를 내므로 이슈 DB 커밋은 거부된다.

**의존성 없음·내부 오류**(`_degraded`): import 실패나 판정 중 예외면 MCP는 거부, Bash의 git·gh·`db_pr.py publish`와
파일 도구는 ask, 그 밖의 Bash는 통과 + 경고. 종료 코드는 그래도 0이다(2는 설치 명령까지 모든 Bash를 막는다).
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

# 의존성(PyYAML 등)이 없으면 import가 터진다. 종료 1(비차단 오류)로 끝나지 않게 받아 두고 `_degraded`로 판정한다.
try:
    from common import checks, mcptools, site_defaults, userconfig  # noqa: E402
    IMPORT_ERROR: Exception | None = None
except ImportError as _exc:   # noqa: BLE001
    checks = mcptools = site_defaults = userconfig = None   # type: ignore[assignment]
    IMPORT_ERROR = _exc

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
HOOKS_PATH_KEY = "core.hookspath"
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n", "|&", ";;"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
MAX_DEPTH = 3
# 다른 명령을 실행하는 앞 래퍼: 이름 → (값을 다음 토큰으로 받는 옵션, 옵션 뒤 건너뛸 위치 인자 수).
# 값이 붙은 옵션(`-oL`, `--signal=KILL`, `nice -5`)은 한 칸. 표 밖 래퍼(watch·flock 등)는 보지 못한다.
# xargs는 정적 인자만 본다(입력 항목은 모른다: `xargs -I{} git -C {} …`의 대상은 판정하지 못한다).
WRAPPERS = {
    "env": ({"-u", "--unset", "-C", "--chdir"}, 0), "command": (set(), 0), "builtin": (set(), 0),
    "nohup": (set(), 0), "setsid": (set(), 0), "exec": ({"-a"}, 0),
    "time": ({"-f", "--format", "-o", "--output"}, 0),
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1), "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "--class", "-n", "--classdata"}, 0),
    "stdbuf": ({"-i", "-o", "-e", "--input", "--output", "--error"}, 0),
    "sudo": ({"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group", "--host",
              "--prompt", "--chdir"}, 0),
    # `-i`·`-l`·`-e`·`--replace`·`--eof`는 값을 붙여서만 받는다(다음 토큰을 먹지 않는다)
    "xargs": ({"-I", "-n", "-L", "-P", "-d", "-s", "-a", "-E", "--max-args", "--max-lines", "--max-procs",
               "--delimiter", "--arg-file", "--max-chars"}, 0),
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
REDIRECT_RE = re.compile(r"^(?:\d*>&|&>>?|\d*>>?\|?)(.*)$")
# 따옴표 밖 연산자 묶음(`>>`, `2>&`, `>|`, `&&` …)을 하나씩 나눈다
OPS_RE = re.compile(r">>\||>>|>&|>\||&>>|&>|\|\||&&|\|&|;;|[;&|()>]")
OP_CHARS = set(";&|()>")

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
GIT_CONFIG_ENV = {"GIT_INDEX_FILE", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG_GLOBAL",
                  "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG"}


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
        remote = userconfig.get(self.cfg, "issue_db.remote") if self.user else None
        self.remote_slug = _repo_slug(str(remote)) if remote else None
        self._clone_git_dir: str | None = None

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

    def is_clone_body(self, cwd: Path) -> bool:
        """cwd가 사용자 clone 본체(작업 worktree·`_snapshot`이 아닌)인가. git dir(`<clone>/.git`)로 비교한다 —
        worktree의 git dir은 `<clone>/.git/worktrees/<이름>`이라 다르다."""
        if self.clone is None:
            return False
        if self._clone_git_dir is None:
            self._clone_git_dir = _git_dir(self.clone) or ""
        return bool(self._clone_git_dir) and _git_dir(cwd) == self._clone_git_dir


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _common_dir(cwd: Path) -> str | None:
    if not cwd.is_dir():
        return None
    proc = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return _norm(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def _git_dir(cwd: Path) -> str | None:
    if not cwd.is_dir():
        return None
    proc = _git(cwd, "rev-parse", "--absolute-git-dir")
    return _norm(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


def _repo_slug(value: str) -> tuple[str | None, str, str] | None:
    """원격 URL·`-R` 값을 `(host|None, owner, repo)`로 (소문자, `.git` 제거). `https://<host>/o/r(.git)`,
    `ssh://<user>@<host>[:port]/o/r`, `git@host:o/r.git`, `host/o/r`, `o/r`. 로컬 경로·형식 밖이면 None."""
    v = str(value).strip().rstrip("/")
    host = None
    if "://" in v:
        scheme, _, rest = v.partition("://")
        if scheme.lower() == "file":
            return None
        netloc, _, path = rest.partition("/")
        host = netloc.rsplit("@", 1)[-1].split(":", 1)[0]
        parts = [p for p in path.split("/") if p]
    else:
        m = re.match(r"^[^@/\s]+@([^:/]+):(.+)$", v)
        if m:
            host, parts = m.group(1), [p for p in m.group(2).split("/") if p]
        else:
            if v.startswith(("/", ".", "~")) or "\\" in v or re.match(r"^[A-Za-z]:", v):
                return None
            parts = [p for p in v.split("/") if p]
            if len(parts) >= 3:
                host, parts = parts[0], parts[1:]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        return None
    return (host.lower() if host else None, owner.lower(), repo.lower())


def _same_repo(a: tuple | None, b: tuple | None) -> bool:
    if a is None or b is None:
        return False
    if a[0] and b[0] and a[0] != b[0]:
        return False
    return a[1:] == b[1:]


def _origin_slug(cwd: Path) -> tuple | None:
    if not cwd.is_dir():
        return None
    proc = _git(cwd, "config", "--get", "remote.origin.url")
    return _repo_slug(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None


# -- Jira (2) --------------------------------------------------------------------------------


def check_mcp(tool: str, tool_input: dict, conf: Config, dec: Decision) -> None:
    # Jira 서버 접두사: mcp_server ∪ jira.tools 이름의 서버 (플러그인 번들 `mcp__plugin_…`도 덮는다). 넓을수록 안전 쪽
    server = userconfig.get(conf.cfg, "jira.mcp_server")
    tools = userconfig.get(conf.cfg, "jira.tools")
    prefixes = {mcptools.full_name(str(server), "")} if server else set()
    prefixes |= {mcptools.server_prefix(v) for v in (tools.values() if isinstance(tools, dict) else [])
                 if mcptools.server_prefix(v)}
    name = mcptools.normalize(tool)
    if prefixes and any(name.startswith(p) for p in prefixes):
        read_tools = userconfig.get(conf.cfg, "jira.read_tools") or []
        if name not in {mcptools.normalize(t) for t in read_tools}:
            dec.deny.append(f"이 플러그인은 Jira 읽기 전용이다. {tool}은(는) jira.read_tools에 없어 거부한다 (규칙 2).")
        return
    if not prefixes:
        dec.warn.append("jira.mcp_server가 비어 있어 Jira 읽기 전용 규칙을 적용하지 않았다 (setup 전).")
    hit = mcptools.NAME_RE.match(tool)
    srv, part = (hit.group(1), hit.group(2)) if hit else ("", tool)
    # 설정되지 않은 서버라도 이름에 jira/atlassian이 들면 쓰기형 도구는 거부한다 (서버 이름 휴리스틱)
    if "jira" in srv.lower() or "atlassian" in srv.lower():
        if mcptools.is_write(part):
            dec.deny.append(f"Jira/Atlassian 서버의 쓰기형 도구는 설정 여부와 무관하게 거부한다 (규칙 2: {tool}).")
        return
    check_mcp_db_write(tool, part, tool_input, conf, dec)


MCP_REPO_KEYS = ("repository", "full_name", "repo_url", "url")


def check_mcp_db_write(tool: str, part: str, tool_input: dict, conf: Config, dec: Decision) -> None:
    """비Jira MCP의 쓰기형 도구가 이슈 DB 레포를 대상으로 하면 ask, 머지면 deny (규칙 11).
    대상은 `owner`+`repo`(GitHub MCP 표준 인자) 또는 레포 문자열 인자로만 안다. 없으면 판정하지 않는다."""
    if conf.remote_slug is None or not mcptools.is_write(part) or not isinstance(tool_input, dict):
        return
    slug = None
    owner, repo = tool_input.get("owner"), tool_input.get("repo")
    if isinstance(owner, str) and isinstance(repo, str) and owner and repo:
        slug = _repo_slug(f"{owner}/{repo}") if "/" not in repo else _repo_slug(repo)
    if slug is None:
        for key in MCP_REPO_KEYS:
            if isinstance(tool_input.get(key), str) and _repo_slug(tool_input[key]):
                slug = _repo_slug(tool_input[key])
                break
    if not _same_repo(slug, conf.remote_slug):
        return
    if mcptools.verb(part) == "merge":   # 동사 자리만: `disable_pr_auto_merge`는 ask
        dec.deny.append(f"이슈 DB PR 머지는 리뷰어가 GHE에서 한다. 도구가 머지하지 않는다 (규칙 6·7: {tool}).")
    else:
        dec.ask.append(f"이슈 DB 원격을 바꾸는 MCP 도구다({tool}). 변경·검증 결과를 보고 승인한 뒤에만 진행한다 (규칙 7).")


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
    # `>`도 연산자 글자로 둔다: 공백 없이 붙은 리디렉션(`echo x>f`, `>>f`, `>|f`)을 따옴표 밖에서만 나눈다
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()>")
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    try:
        raw = list(lex)
    except ValueError:   # 따옴표 불균형 등: 공백으로만 나눈다 (보수적)
        return re.split(r"[ \t\r]+", text)
    out: list[str] = []
    prev_op = False
    for tok in raw:
        if tok and set(tok) <= OP_CHARS:
            for op in OPS_RE.findall(tok):
                if op[0] == ">" and out and out[-1].isdigit() and not prev_op:
                    out[-1] += op          # `2>`·`2>&`: 앞 숫자는 fd
                else:
                    out.append(op)
                prev_op = True
        else:
            out.append(tok)
            prev_op = False
    return out


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


def _strip_prefix(seg: list[str], cwd: Path) -> tuple[list[str], Path, dict]:
    """앞의 `VAR=값`과 래퍼(`WRAPPERS`: env·timeout·nice·sudo·xargs 등)를 옵션째 뗀다. `env -S`는 풀어 읽고,
    `env -C`·`sudo -D`는 작업 디렉토리로 반영한다. 뗀 `VAR=값`(래퍼 뒤의 것 포함)은 `env`로 돌려준다."""
    i = 0
    env: dict[str, str] = {}
    while i < len(seg):
        tok = seg[i]
        name = _base(tok)
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            key, _, value = tok.partition("=")
            env[key] = value
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
    return seg[i:], cwd, env


def _base(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


class Invocation:
    def __init__(self, cwd: Path, argv: list[str], env: dict | None = None):
        self.cwd = cwd
        self.argv = argv
        self.env = env or {}   # 앞의 `VAR=값` 대입


def invocations(command: str, cwd: Path, depth: int = 0) -> list[Invocation]:
    out: list[Invocation] = []
    for seg in _segments(_tokens(command)):
        seg, seg_cwd, env = _strip_prefix(seg, cwd)
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
        if name == "eval":
            if depth < MAX_DEPTH and len(seg) > 1:
                out += invocations(" ".join(seg[1:]), seg_cwd, depth + 1)
            continue
        out.append(Invocation(seg_cwd, seg, env))
    return out


# -- git 명령 판정 ----------------------------------------------------------------------------


class GitCall:
    """`git [전역 옵션] <sub> <args>`를 나눈다. 레포 판별 디렉토리(`cwd`)는 `-C` 뒤에 환경변수
    `GIT_DIR`·`GIT_COMMON_DIR`·`GIT_WORK_TREE`, 그 뒤에 `--git-dir`·`--work-tree`(명령줄이 환경변수보다 우선)를 반영한다
    (work tree가 있으면 그것, 없으면 git dir)."""

    def __init__(self, inv: Invocation):
        argv = inv.argv
        cwd = inv.cwd
        self.config_overrides: list[str] = []
        self.sub = None
        self.args: list[str] = []
        git_dir = work_tree = None

        def at(base: Path, value: str) -> Path:
            d = _expand(value)
            return Path(d) if Path(d).is_absolute() else base / d

        i = 1
        while i < len(argv):
            tok = argv[i]
            if tok == "-C" and i + 1 < len(argv):
                cwd = at(cwd, argv[i + 1])
                i += 2
            elif tok == "-c" and i + 1 < len(argv):
                self.config_overrides.append(argv[i + 1])
                i += 2
            elif tok.startswith("--config-env="):
                self.config_overrides.append(tok.split("=", 1)[1])
                i += 1
            elif tok.startswith(("--git-dir=", "--work-tree=")):
                key, _, value = tok.partition("=")
                if key == "--git-dir":
                    git_dir = at(cwd, value)
                else:
                    work_tree = at(cwd, value)
                i += 1
            elif tok in GIT_GLOBAL_WITH_ARG:
                if i + 1 < len(argv):
                    if tok == "--config-env":
                        self.config_overrides.append(argv[i + 1])
                    elif tok == "--git-dir":
                        git_dir = at(cwd, argv[i + 1])
                    elif tok == "--work-tree":
                        work_tree = at(cwd, argv[i + 1])
                i += 2
            elif tok.startswith("-"):
                i += 1
            else:
                self.sub = tok
                self.args = argv[i + 1:]
                break
        env = inv.env
        env_dir = env.get("GIT_DIR") or env.get("GIT_COMMON_DIR")
        git_dir = git_dir or (at(cwd, env_dir) if env_dir else None)
        work_tree = work_tree or (at(cwd, env["GIT_WORK_TREE"]) if env.get("GIT_WORK_TREE") else None)
        self.cwd = work_tree or git_dir or cwd
        # 값 해석 없이 존재만 본다: hooksPath·index를 끼워 넣는 통로이고 정상 흐름에 없다 (규칙 5)
        self.config_env = sorted(k for k in env if k in GIT_CONFIG_ENV or re.match(r"^GIT_CONFIG_(KEY|VALUE)_\d+$", k))

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


# -- gh (11) ---------------------------------------------------------------------------------

GH_READ_ACTIONS = {"list", "view", "status", "download", "watch", "verify", "diff"}
GH_ACTION_GROUPS = {"issue", "release", "label", "secret", "variable", "ruleset", "workflow", "run", "cache", "project"}
GH_PR_WRITE = {"close", "edit", "review", "comment", "create", "ready", "reopen", "lock", "unlock", "update-branch"}
GH_REPO_READ = {"view", "list", "clone"}
GH_API_WITH_ARG = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "-H", "--header", "--input", "-q", "--jq",
                   "-t", "--template", "--hostname", "--cache", "-p", "--preview"}
GH_API_FIELDS = {"-f", "-F", "--field", "--raw-field"}


def _gh_words(argv: list[str]) -> list[str]:
    """`-R/--repo` 값을 뺀 위치 인자 (그룹·동작만 본다)."""
    words, skip = [], False
    for tok in argv[1:]:
        if skip:
            skip = False
        elif tok in ("-R", "--repo"):
            skip = True
        elif not tok.startswith("-"):
            words.append(tok)
    return words


def _gh_api(argv: list[str]) -> tuple[str | None, bool]:
    """`gh api`의 (엔드포인트, 쓰기 여부). 메서드를 밝히면 GET이 아닐 때만 쓰기, 밝히지 않으면 필드·`--input`이
    있을 때 쓰기(gh 기본 POST). `graphql`은 필드 값에 `mutation`이 있거나 `--input`일 때만 쓰기."""
    args = argv[argv.index("api") + 1:]
    endpoint, method, fields, has_input = None, None, [], False
    i = 0
    while i < len(args):
        tok = args[i]
        key, eq, value = tok.partition("=") if tok.startswith("--") else (tok, "", "")
        if tok.startswith("-") and not tok.startswith("--") and len(tok) > 2 and tok[:2] in GH_API_WITH_ARG:
            key, eq, value = tok[:2], "=", tok[2:]   # `-XPUT`, `-fquery=…`
        if key in GH_API_WITH_ARG:
            if not eq:
                value = args[i + 1] if i + 1 < len(args) else ""
                i += 1
            if key in ("-X", "--method"):
                method = value.upper()
            elif key in GH_API_FIELDS:
                fields.append(value)
            elif key == "--input":
                has_input = True
        elif not tok.startswith("-") and endpoint is None:
            endpoint = tok
        i += 1
    if endpoint == "graphql":
        return endpoint, has_input or any("mutation" in f for f in fields)
    if method is not None:   # 메서드를 밝히면 그것만 본다(`-X GET -f k=v`는 쿼리 문자열이다)
        return endpoint, method != "GET"
    return endpoint, bool(fields) or has_input   # gh는 필드가 있으면 POST로 보낸다


def _gh_kind(argv: list[str]) -> str:
    """`read`|`write`|`merge`|`local`. 모르는 그룹은 read(오탐 방지)."""
    words = _gh_words(argv)
    group = words[0] if words else ""
    action = words[1] if len(words) > 1 else ""
    if group == "api":
        endpoint, write = _gh_api(argv)
        if write and re.search(r"/pulls/[^/]+/merge/?$|/merges/?$", (endpoint or "").split("?", 1)[0]):
            return "merge"
        return "write" if write else "read"
    if group == "pr":
        if action == "merge":
            return "merge"
        if action == "checkout":
            return "local"
        return "write" if action in GH_PR_WRITE else "read"
    if group in GH_ACTION_GROUPS:
        return "read" if not action or action in GH_READ_ACTIONS else "write"
    if group == "repo":
        return "read" if not action or action in GH_REPO_READ else "write"
    return "read"


def _gh_targets_db(inv: Invocation, conf: Config) -> bool:
    """대상 레포가 이슈 DB인가: api 엔드포인트의 `repos/<o>/<r>` → `-R`/`--repo`/`GH_REPO` → cwd(gh가 원격으로 정하는 레포:
    이슈 DB clone·worktree·스냅샷이거나 origin이 이슈 DB 원격)."""
    argv = inv.argv
    words = _gh_words(argv)
    if words and words[0] == "api":
        endpoint = _gh_api(argv)[0] or ""
        m = re.search(r"(?:^|/)repos/([^/]+)/([^/?#]+)", endpoint)
        if m and not any(t.startswith(("{", ":")) for t in m.groups()):
            return _same_repo(_repo_slug(f"{m.group(1)}/{m.group(2)}"), conf.remote_slug)
    repo = inv.env.get("GH_REPO")
    for i, tok in enumerate(argv[1:], 1):
        if tok in ("-R", "--repo") and i + 1 < len(argv):
            repo = argv[i + 1]
        elif tok.startswith("--repo="):
            repo = tok.split("=", 1)[1]
    if repo:
        return _same_repo(_repo_slug(_expand(repo)), conf.remote_slug)
    if conf.clone_common is not None and _common_dir(inv.cwd) == conf.clone_common:
        return True
    return _same_repo(_origin_slug(inv.cwd), conf.remote_slug)


def check_gh(inv: Invocation, conf: Config, dec: Decision) -> None:
    if conf.user is None or conf.remote_slug is None:
        return
    kind = _gh_kind(inv.argv)
    if kind == "local":
        if conf.is_clone_body(inv.cwd):
            dec.deny.append(CLONE_MUTATION_MSG)
        return
    if kind == "read" or not _gh_targets_db(inv, conf):
        return
    if kind == "merge":
        dec.deny.append("이슈 DB PR 머지는 리뷰어가 GHE에서 한다. 도구가 머지하지 않는다 (규칙 6·7).")
    else:
        dec.ask.append("이슈 DB 원격을 바꾸는 gh 명령이다. 변경·검증 결과를 보고 승인한 뒤에만 진행한다 (규칙 7).")


# -- 사용자 clone 불변 (8, Bash) -------------------------------------------------------------

CLONE_MUTATION_MSG = ("사용자 clone의 브랜치·파일은 도구가 바꾸지 않는다 (규칙 8). 분석은 _snapshot, "
                      "쓰기는 db_pr의 작업 worktree")
CLONE_GIT_SUBS = {"checkout", "switch", "reset", "merge", "rebase", "pull", "clean", "rm", "mv", "apply", "am",
                  "cherry-pick", "revert", "restore", "update-ref", "read-tree", "checkout-index", "filter-branch",
                  "filter-repo"}
BRANCH_MUTATING = {"-D", "-d", "-M", "-m", "-f", "-c", "-C", "--delete", "--move", "--force", "--copy"}
# 서브커맨드별 첫 인자로 쓰기를 정하는 것: 이름 → 바꾸는 동작
CLONE_GIT_ACTIONS = {"worktree": {"add", "remove", "prune", "move"},
                     "bisect": {"start", "good", "bad", "new", "old", "skip", "reset", "run", "replay"},
                     "sparse-checkout": {"set", "add", "init", "disable", "reapply"},
                     "submodule": {"update", "add", "deinit"}}
MIGRATE_RE = re.compile(r"^migrate/schema-v\d+$")
# 파일을 쓰는 명령: 이름 → (값을 다음 토큰으로 받는 옵션, 대상 위치 인자: "last"|"all"|"rest")
FILE_WRITERS = {
    "cp": ({"-S", "--suffix"}, "last"), "mv": ({"-S", "--suffix"}, "last"), "ln": ({"-S", "--suffix"}, "last"),
    "install": ({"-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix"}, "last"),
    "rsync": ({"-e", "--rsh", "--exclude", "--include", "--filter", "-f"}, "last"),
    "rm": (set(), "all"), "rmdir": (set(), "all"), "mkdir": ({"-m", "--mode"}, "all"), "touch": ({"-d", "-r", "-t"}, "all"),
    "truncate": ({"-s", "--size", "-r", "--reference"}, "all"), "tee": (set(), "all"),
    "chmod": (set(), "rest"), "chown": (set(), "rest"),
}


def _perl_cluster(x: str) -> tuple[bool, str | None]:
    """perl 짧은 옵션 묶음 하나: (in-place `-i` 여부, 코드 위치). 코드 위치는 "next"(다음 토큰이 코드)·"here"(묶음
    나머지가 코드)·None. 값을 받는 옵션(`-M`·`-m`·`-I`·`-x`·`-0`, 숫자가 붙은 `-l`)에서 멈춘다(`-Mstrict`의 i는 -i가 아니다).
    `-i`는 묶음 나머지를 백업 확장자로 먹는다."""
    for j in range(1, len(x)):
        ch = x[j]
        if ch == "i":
            return True, None
        if ch in "eE":
            return False, "next" if j == len(x) - 1 else "here"
        if ch in "MmIx0" or (ch == "l" and x[j + 1:j + 2].isdigit()):
            return False, None
    return False, None


def _perl_inplace_files(rest: list[str]) -> list[str]:
    inplace, script_given, pos, i = False, False, [], 0
    while i < len(rest):
        x = rest[i]
        if x == "--":
            pos += rest[i + 1:]
            break
        if x.startswith("-") and not x.startswith("--") and len(x) > 1:
            ip, code = _perl_cluster(x)
            inplace = inplace or ip
            if code:
                script_given = True
                i += 2 if code == "next" else 1
                continue
        elif not x.startswith("-"):
            pos.append(x)
        i += 1
    if not inplace:
        return []
    return pos if script_given else pos[1:]


def _write_targets(inv: Invocation) -> list[str]:
    """이 호출이 쓰는 파일 경로(펼치기 전 단어): 출력 리디렉션 대상, tee·cp·mv·rm 등의 대상, `sed -i`·`perl -i`·
    `sort -o`·`unzip -d`·`tar -x -C`·`dd of=`."""
    argv = inv.argv
    out: list[str] = []
    rest: list[str] = []
    pending = None   # 값이 다음 토큰인 리디렉션: "out"(쓰기 대상)·"dup"(fd 복제)·"in"(입력, 쓰기 아님)
    for k, tok in enumerate(argv):   # argv[0]도 본다: 리디렉션이 맨 앞에 올 수 있다
        if pending is not None:
            if pending == "out" or (pending == "dup" and not (tok.isdigit() or tok == "-")):
                out.append(tok)
            pending = None
            continue
        if tok.startswith("<"):   # 입력 리디렉션·heredoc·here-string은 쓰기가 아니다
            if tok in ("<", "<<", "<<-", "<<<"):
                pending = "in"
            continue
        m = REDIRECT_RE.match(tok) if tok else None
        if m:
            target = m.group(1)
            dup = ">&" in tok[:len(tok) - len(target)]
            if not target:
                pending = "dup" if dup else "out"
            elif not (dup and (target.isdigit() or target == "-")):
                out.append(target)
            continue
        if k:
            rest.append(tok)
    name = _base(argv[0]) if argv and not REDIRECT_RE.match(argv[0]) else ""
    if name in FILE_WRITERS:
        with_arg, which = FILE_WRITERS[name]
        pos, i = [], 0
        while i < len(rest):
            a = rest[i]
            if a in ("-t", "--target-directory") and i + 1 < len(rest):
                out.append(rest[i + 1])
                i += 2
                continue
            if a.startswith("--target-directory="):
                out.append(a.split("=", 1)[1])
            elif a in with_arg:
                i += 1
            elif not a.startswith("-") or a == "-":
                pos.append(a)
            i += 1
        out += pos[-1:] if which == "last" else pos[1:] if which == "rest" else pos
    elif name == "sed":
        if any(x.startswith("--in-place") or re.match(r"^-[A-Za-z]*i", x) for x in rest):
            pos, script_given, i = [], False, 0
            while i < len(rest):
                x = rest[i]
                if x.startswith(("--expression=", "--file=")):
                    script_given = True
                elif x in ("--expression", "--file") or (re.match(r"^-[A-Za-z]+$", x) and x[-1] in "ef"):
                    script_given = True   # 다음 토큰이 스크립트
                    i += 1
                elif not x.startswith("-"):
                    pos.append(x)
                i += 1
            out += pos if script_given else pos[1:]
    elif name == "perl":
        out += _perl_inplace_files(rest)
    elif name == "sort":
        for i, a in enumerate(rest):
            if a in ("-o", "--output") and i + 1 < len(rest):
                out.append(rest[i + 1])
            elif a.startswith("--output="):
                out.append(a.split("=", 1)[1])
            elif a.startswith("-o") and len(a) > 2 and not a.startswith("--"):
                out.append(a[2:])
    elif name == "unzip":
        out += [rest[i + 1] for i, a in enumerate(rest) if a == "-d" and i + 1 < len(rest)]
    elif name == "tar":
        if any(a == "--extract" or a == "--get" or (not a.startswith("--") and "x" in a.lstrip("-")) for a in rest[:3]):
            for i, a in enumerate(rest):
                if a in ("-C", "--directory") and i + 1 < len(rest):
                    out.append(rest[i + 1])
                elif a.startswith("--directory="):
                    out.append(a.split("=", 1)[1])
    elif name == "dd":
        out += [a[3:] for a in rest if a.startswith("of=")]
    return out


def check_clone_writes(inv: Invocation, conf: Config, dec: Decision) -> None:
    """Bash 명령의 파일 쓰기 대상이 사용자 clone 안이면 거부 (`<work_dir>` 아래는 제외)."""
    clone = _norm(conf.clone)
    work = _norm(conf.work_dir) if conf.work_dir is not None else None
    for word in _write_targets(inv):
        p = _expand(word)
        target = _norm(Path(p) if Path(p).is_absolute() else inv.cwd / p)
        if work and _inside(target, work):
            continue
        if _inside(target, clone):
            dec.deny.append(f"{CLONE_MUTATION_MSG}: {word}")
            return


def check_clone_git(call: GitCall, conf: Config, dec: Decision) -> None:
    """사용자 clone 본체에서 브랜치·파일을 바꾸는 git 명령 거부. migrate 브랜치 생성(깨끗한 트리)만 ask."""
    sub, args = call.sub, call.args
    if sub == "stash":
        mutating = not args or args[0] not in ("list", "show")
    elif sub == "branch":
        mutating = any(a in BRANCH_MUTATING or a.split("=", 1)[0] in BRANCH_MUTATING for a in args)
    elif sub in CLONE_GIT_ACTIONS:
        action = next((a for a in args if not a.startswith("-")), "")
        mutating = action in CLONE_GIT_ACTIONS[sub]
    elif sub == "symbolic-ref":   # `symbolic-ref HEAD refs/heads/x`(인자 2개)·`-d`는 HEAD를 바꾼다
        mutating = len([a for a in args if not a.startswith("-")]) >= 2 or any(a in ("-d", "--delete") for a in args)
    elif sub == "clean":          # `-n`·`--dry-run`은 지울 목록만 보인다
        mutating = not any(a == "--dry-run" or (re.match(r"^-[A-Za-z]+$", a) and "n" in a) for a in args)
    else:
        mutating = sub in CLONE_GIT_SUBS
    if not mutating or not conf.is_clone_body(call.cwd):
        return
    create = {"switch": ("-c", "-C", "--create", "--force-create"), "checkout": ("-b", "-B")}.get(sub, ())
    for i, a in enumerate(args):
        if a in create and i + 1 < len(args) and MIGRATE_RE.match(args[i + 1]):
            if not _git(call.cwd, "status", "--porcelain").stdout.strip():
                dec.ask.append("migrate 브랜치 생성: 메인테이너 흐름(migrate 커맨드)이면 승인한다 (규칙 8 예외).")
                return
    dec.deny.append(CLONE_MUTATION_MSG)


def check_bash(command: str, cwd: Path, conf: Config, dec: Decision) -> None:
    check_raw_read(command, cwd, dec, conf)
    for inv in invocations(command, cwd):
        name = _base(inv.argv[0])
        if conf.clone is not None:
            check_clone_writes(inv, conf, dec)
        is_db_pr = name == "db_pr.py" or (name.startswith("python")
                                           and any(_base(a) == "db_pr.py" for a in inv.argv[1:]))
        if is_db_pr and "publish" in inv.argv:
            if conf.user is not None:
                dec.ask.append("db_pr.py publish는 이슈 DB에 push한다. 확인 화면을 승인한 뒤에만 진행한다 (규칙 7).")
            continue
        if name == "gh":
            check_gh(inv, conf, dec)
            continue
        if name != "git" or not conf.git_rules:
            continue
        call = GitCall(inv)
        check_clone_git(call, conf, dec)
        if call.sub not in ("commit", "config", "push") and not call.overrides_hooks_path():
            continue
        if _common_dir(call.cwd) != conf.clone_common:
            continue   # 이슈 DB가 아니다: 어떤 git 규칙도 적용하지 않는다
        if call.overrides_hooks_path():
            dec.deny.append("git -c core.hooksPath=… 로 hook을 바꾸는 것은 금지다 (규칙 5).")
            continue
        if call.config_env and call.sub in ("commit", "push", "config"):
            dec.deny.append(f"환경변수로 git 설정·index를 바꾸는 커밋/푸시는 금지 (규칙 5: {', '.join(call.config_env)}).")
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
        check_mcp(tool, tool_input, conf, dec)
    elif tool in FILE_TOOLS:
        check_file(tool_input, cwd, conf, dec)
    elif tool == "Bash":
        check_bash(str(tool_input.get("command") or ""), cwd, conf, dec)
    return dec.output(), dec.warn


INSTALL_HINT = "pyproject 의존성(PyYAML·jsonschema)을 설치한 뒤 `config.py doctor`로 확인한다"


def _degraded(event: dict, why: str) -> tuple[dict | None, list[str]]:
    """의존성 없음·내부 오류로 정상 판정을 못 할 때. MCP는 거부(Jira 쓰기 차단은 guard가 유일한 장치),
    git·gh·`db_pr.py publish`와 파일 도구는 레포·clone을 판별할 수 없으므로 ask, 그 밖의 Bash는 통과 + 경고.
    종료 2(모든 Bash 차단, 설치 명령까지)는 쓰지 않는다."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    if tool.startswith("mcp__"):
        return _decision("deny", f"{why}: MCP 도구 판정 불가. {INSTALL_HINT}."), []
    if tool in FILE_TOOLS:
        return _decision("ask", f"{why}: 이슈 DB clone 경로를 판별할 수 없다 — 직접 확인한다. {INSTALL_HINT}."), []
    if tool == "Bash":
        risky = True
        try:
            invs = invocations(str(tool_input.get("command") or ""), Path(str(event.get("cwd") or os.getcwd())))
            names = [_base(i.argv[0]) for i in invs]
            risky = any(n in ("git", "gh") for n in names) or any(
                "publish" in i.argv and any(_base(a) == "db_pr.py" for a in i.argv) for i in invs) or any(
                not _expand(t).startswith("/dev/") for i in invs for t in _write_targets(i))   # 파일 쓰기(clone일 수 있다)
        except Exception:  # noqa: BLE001 — 파싱도 못 하면 사람에게 넘긴다
            pass
        if risky:
            return _decision("ask", f"{why}: 레포 판별 불가 — git·gh·publish·파일 쓰기는 직접 확인한다. "
                                    f"{INSTALL_HINT}."), []
        return None, [f"{why}: Bash 규칙을 적용하지 못했다. {INSTALL_HINT}."]
    return None, [f"{why}. {INSTALL_HINT}."]


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
    if not isinstance(event, dict):
        print("[telephony-triage] guard: hook 입력이 객체가 아니다. 판정하지 않는다.", file=sys.stderr)
        return 0
    if IMPORT_ERROR is not None:
        out, warnings = _degraded(event, f"guard 의존성 없음({type(IMPORT_ERROR).__name__}: {IMPORT_ERROR})")
    else:
        try:
            out, warnings = judge(event, args.plugin_root)
        except Exception as exc:  # noqa: BLE001 — hook이 모든 도구 호출을 막지 않게 한다
            print(f"[telephony-triage] guard 내부 오류: {exc}", file=sys.stderr)
            out, warnings = _degraded(event, f"guard 내부 오류({type(exc).__name__}: {exc})")
    for w in warnings:
        print(f"[telephony-triage] {w}", file=sys.stderr)
    if out is not None:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
