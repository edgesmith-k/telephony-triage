#!/usr/bin/env python3
"""config.py — 사용자 config, 사내 기본값, 호환성 판정 (02-config.md §4·§5.3, contracts.md §3.2,
06-collaboration.md §6.4, 16-existing-assets.md §16.1).

설정 우선순위: 사용자 config(`~/.telephony-triage/config.yaml`) > 플러그인 `site-defaults.yaml` >
코드 내장 기본값. `site-defaults.yaml`이 없으면 모든 서브커맨드가 종료 코드 2로 멈춘다
("사내 기본값 없음"). `site-defaults.example.yaml`은 읽지 않는다.

서브커맨드
  show [--keys a,b.c]          해석된 설정 (우선순위 적용). --keys면 그 키 값만
                               `{user_config, values{키: 값}, missing[]}` (점 표기, 없는 키는 missing)
  site-defaults                site-defaults.yaml 내용
  init [--answers <json>]      config 생성 (setup 1). --answers가 없으면 stdin으로 항목별로 묻는다.
                               경로가 없으면 거부한다. 홈·work_dir은 권한 700.
                               답한 값만 저장(선택 항목은 팀 기본값과 다를 때만, 나머지는 site-defaults·내장 기본값 상속).
  set <key> <value>            값 하나 바꾸기 (경로 값은 존재 검증)
  sync-scripts-path            plugin.scripts_path = ${CLAUDE_PLUGIN_ROOT}/scripts (setup 2, SessionStart hook)
  jira-candidates [--mcp-config <json>...] [--tools-json <json>]
                               등록된 MCP 서버에서 jira.tools·읽기 도구 후보 (setup 4). exclude_servers 적용
  set-jira --server <s> --get-issue <전체 이름> [--search-issues ..] [--get-comments ..] [--read-tools a,b]
                               사용자가 확인한 값을 저장. read_tools에 jira.tools 값을 포함한다
  install-hooks [--db <path>]  git config core.hooksPath .githooks, 값이 정확히 .githooks인지 확인 (setup 5)
  check [--db <path>] [--for write|dry-run]
                               호환성 판정: 스키마·생성기 버전·파서 백엔드·외부 파서, (write면) gh 인증
                               → writable / push_allowed. `migrate/schema-v<N>` 브랜치는 버전을 보지 않는다.
  gh-status                    gh 인증 확인 (setup 9). 실패면 로그인 안내와 종료 코드 2
  doctor [--format json|markdown]
                               환경 점검 한 장(python·deps·config·clone·hook·guard 자가시험·Jira 매핑·gh·스냅샷·
                               호환성·lock). **읽기 전용**
                               (mkdir·fetch·lock·쓰기 없음). 행마다 ok|warn|fail|skip. fail이 있으면 종료 코드 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from common.versions import GENERATOR_VERSION, SCHEMA_VERSION  # noqa: E402

# 의존성(PyYAML 등)이 없으면 traceback 대신 안내하고 종료 2(자기 실행 불가)로 멈춘다 (`main`)
try:
    import adapters  # noqa: E402
    from common import compat, dbpath, ghcli, mcptools, session_lock, site_defaults, userconfig, yamlio  # noqa: E402
    from common import compiled as compiled_cache  # noqa: E402
    IMPORT_ERROR: ImportError | None = None
except ImportError as _exc:   # noqa: BLE001
    IMPORT_ERROR = _exc

SUPPORTED_SCHEMA = (SCHEMA_VERSION, SCHEMA_VERSION)  # (min, max), 06-collaboration.md §6.4
MIGRATE_BRANCH_RE = re.compile(r"^migrate/schema-v\d+$")
YEAR_SOURCES = ("jira", "file-mtime", "ask")
TOOL_NAME_RE = re.compile(r"^mcp__(?P<server>[^_].*?)__(?P<tool>[^_].*)$")

# setup 1에서 묻는 항목: (키, 질문, 종류, 필수)
FIELDS = [
    ("user.ghe_id", "GHE 아이디", "text", True),
    ("issue_db.path", "이슈 DB 로컬 clone 경로 (없으면 만들 위치)", "clone-path", True),
    ("issue_db.remote", "이슈 DB 원격 URL", "text", True),
    ("issue_db.base_branch", "base 브랜치", "text", False),
    ("issue_db.ghe_host", "GHE 호스트 (gh의 GH_HOST)", "text", False),
    ("jira.timezone", "Jira 시각 타임존 (IANA)", "tz", False),
    ("logcat.timezone", "logcat 시각 타임존 (IANA)", "tz", False),
    ("logcat.year_source", "연도 결정 방식 (jira | file-mtime | ask)", "year-source", False),
    ("log_dir", "logcat 기본 탐색 경로 (선택, 빈 값이면 건너뜀)", "dir", False),
    ("work_dir", "작업 디렉토리 (작업 계획·스냅샷·lock)", "work-dir", False),
]
PATH_KINDS = {"issue_db.path": "clone-path", "log_dir": "dir", "work_dir": "work-dir"}


class UsageError(Exception):
    pass


# -- 값 검사 ---------------------------------------------------------------------------


def validate(kind: str, value) -> str | None:
    """오류 메시지 또는 None."""
    if value in (None, ""):
        return None
    text = str(value)
    if kind == "dir":
        return None if Path(text).expanduser().is_dir() else f"디렉토리가 없습니다: {text}"
    if kind == "clone-path":
        p = Path(text).expanduser()
        if p.exists() and not p.is_dir():
            return f"디렉토리가 아닙니다: {text}"
        if not p.exists() and not p.parent.is_dir():
            return f"상위 디렉토리가 없습니다: {p.parent}"
        return None
    if kind == "work-dir":
        p = Path(text).expanduser()
        return None if (p.is_dir() or p.parent.is_dir()) else f"상위 디렉토리가 없습니다: {p.parent}"
    if kind == "tz":
        from platforms.android import logcat

        try:
            logcat.get_tz(text)
        except ValueError as exc:
            return str(exc)
        return None
    if kind == "year-source":
        return None if text in YEAR_SOURCES else f"{' | '.join(YEAR_SOURCES)} 중 하나여야 합니다: {text}"
    return None


def _default_for(key: str, defaults: dict):
    return userconfig.get(userconfig.merged(defaults, {}), key)


# -- 서브커맨드 ---------------------------------------------------------------------------


def cmd_init(args, defaults: dict) -> dict:
    existing = userconfig.load_user()
    if existing is not None and not args.force:
        raise UsageError(f"config가 이미 있습니다: {userconfig.path()} (바꾸려면 set, 다시 만들려면 --force)")
    answers = {}
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        errors = []
        for key, _, kind, required in FIELDS:
            value = answers.get(key)
            if required and value in (None, ""):
                errors.append(f"{key}: 값이 필요합니다")
            elif (msg := validate(kind, value)):
                errors.append(f"{key}: {msg}")
        if errors:
            raise UsageError("config 값이 잘못됐습니다:\n  " + "\n  ".join(errors))
    else:
        for key, question, kind, required in FIELDS:
            default = _default_for(key, defaults)
            for _attempt in range(3):
                hint = f" [{default}]" if default not in (None, "", [], {}) else ""
                print(f"{question}{hint}: ", end="", file=sys.stderr, flush=True)
                line = sys.stdin.readline()
                if not line:
                    raise UsageError(f"{key}: 입력이 끝났습니다.")
                value = line.strip() or (default if default not in ([], {}) else "")
                if required and not value:
                    print("  값이 필요합니다.", file=sys.stderr)
                    continue
                msg = validate(kind, value)
                if msg:
                    print(f"  거부: {msg}", file=sys.stderr)
                    continue
                answers[key] = value
                break
            else:
                raise UsageError(f"{key}: 올바른 값을 받지 못했습니다.")

    data: dict = {}
    for key, _, _kind, required in FIELDS:
        value = answers.get(key)
        if value in (None, "") or (not required and value == _default_for(key, defaults)):
            continue        # 답하지 않았거나 팀 기본값과 같으면 저장하지 않는다(이후 팀 기본값 변경을 상속)
        userconfig.set_value(data, key, value)
    data.setdefault("plugin", {})["scripts_path"] = str(_plugin_root(args) / "scripts")
    effective = userconfig.merged(defaults, data)
    userconfig.ensure_private_dir(userconfig.home())
    userconfig.ensure_private_dir(Path(userconfig.get(effective, "work_dir")).expanduser())
    path = userconfig.save(data)
    clone = Path(userconfig.get(effective, "issue_db.path")).expanduser()
    return {"config": str(path), "clone_exists": clone.is_dir() and (clone / ".git").exists(),
            "suggest_clone": None if (clone / ".git").exists() else
            f"git clone {userconfig.get(effective, 'issue_db.remote')} {clone}"}


def _parse_value(text: str):
    import yaml

    from common import yamlio

    try:
        return yamlio.safe_load(text)
    except yaml.YAMLError:
        return text


def cmd_set(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 setup(config.py init)을 한다.")
    value = _parse_value(args.value)
    kind = PATH_KINDS.get(args.key) or ("tz" if args.key.endswith(".timezone") else
                                        "year-source" if args.key == "logcat.year_source" else "")
    msg = validate(kind, value)
    if msg:
        raise UsageError(f"{args.key}: {msg}")
    userconfig.set_value(data, args.key, value)
    userconfig.save(data)
    return {"config": str(userconfig.path()), "key": args.key, "value": value}


def _plugin_root(args) -> Path:
    root_opt = getattr(args, "plugin_root", None)
    return Path(root_opt) if root_opt else site_defaults.plugin_root()


def cmd_sync_scripts_path(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    scripts = str(_plugin_root(args) / "scripts")
    if data is None:
        return {"config": None, "scripts_path": scripts, "note": "config가 없어 기록하지 않았습니다 (setup 전)"}
    old = userconfig.get(data, "plugin.scripts_path")
    if old != scripts:
        userconfig.set_value(data, "plugin.scripts_path", scripts)
        userconfig.save(data)
    return {"config": str(userconfig.path()), "scripts_path": scripts, "changed": old != scripts}


def cmd_jira_candidates(args, defaults: dict) -> dict:
    merged = userconfig.merged(defaults)
    exclude = list(userconfig.get(merged, "jira.exclude_servers", []) or [])
    servers: dict[str, list[str] | None] = {}
    errors: dict[str, str] = {}
    if args.tools_json:
        for name, tools in json.loads(Path(args.tools_json).read_text(encoding="utf-8")).items():
            servers[name] = [t.split("__", 2)[-1] if t.startswith("mcp__") else t for t in tools]
    configs = [Path(p) for p in args.mcp_config] if args.mcp_config else [Path.home() / ".claude.json"]
    for name, conf in mcptools.load_servers(configs).items():
        if name in servers:
            continue
        if any(__import__("fnmatch").fnmatch(name, p) for p in exclude):
            servers[name] = None
            continue
        try:
            servers[name] = mcptools.list_tools(conf)
        except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
            servers[name] = None
            errors[name] = str(exc)
    team = userconfig.get(defaults, "jira.tools", {}) or {}
    result = mcptools.candidates(servers, exclude, team, errors)
    usable = [s for s in result if not s["excluded"] and s["jira_tools"].get("get_issue")]
    return {
        "exclude_servers": exclude,
        "servers": result,
        "usable": [s["server"] for s in usable],
        "next": ("사용자에게 서버와 jira.tools·read_tools를 확인받고 config.py set-jira로 저장한다"
                 if usable else "Jira MCP를 찾지 못했다. 사용자 범위(user scope)로 등록하는 방법을 안내하고 중단한다"),
    }


def _tool_problems(server: str, names: list[str]) -> list[str]:
    """도구 이름이 전체 이름이고 그 서버의 것인지 검사한 문제 목록 (set-jira·doctor 공유). 서버는 정규화 비교."""
    problems = []
    for name in names:
        hit = TOOL_NAME_RE.match(str(name))
        if not hit:
            problems.append(f"도구 이름은 전체 이름(mcp__<server>__<tool>)이어야 합니다: {name}")
        elif mcptools.server_segment(hit.group("server")) != mcptools.server_segment(server):
            problems.append(f"{name}는 서버 {server}의 도구가 아닙니다.")
    return problems


def cmd_set_jira(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 config.py init을 한다.")
    tools = {"get_issue": args.get_issue, "search_issues": args.search_issues, "get_comments": args.get_comments}
    tools = {k: v for k, v in tools.items() if v}
    read_tools = [t.strip() for t in (args.read_tools or "").split(",") if t.strip()]
    problems = _tool_problems(args.server, list(tools.values()) + read_tools)
    if problems:
        raise UsageError(problems[0])
    added = [t for t in tools.values() if t not in read_tools]
    read_tools = sorted(set(read_tools) | set(tools.values()))  # read_tools는 jira.tools 값을 포함한다
    userconfig.set_value(data, "jira.mcp_server", args.server)
    userconfig.set_value(data, "jira.tools", tools)
    userconfig.set_value(data, "jira.read_tools", read_tools)
    userconfig.save(data)
    return {"mcp_server": args.server, "tools": tools, "read_tools": read_tools, "added_to_read_tools": added}


def _git_out(repo: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _hooks_value(db: Path) -> str | None:
    return _git_out(db, "config", "--get", "core.hooksPath")


def _gh_auth(defaults: dict) -> tuple[str | None, bool, str]:
    """(호스트, 인증 여부, 메시지) — check·gh-status·doctor 공유."""
    host = userconfig.get(userconfig.merged(defaults), "issue_db.ghe_host")
    ok, message = ghcli.auth_status(host)
    return host, ok, message


def _db(args, defaults: dict) -> Path:
    try:
        return dbpath.resolve(args.db, user_config_path=lambda: userconfig.issue_db_path(defaults))
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc


def cmd_install_hooks(args, defaults: dict) -> dict:
    db = _db(args, defaults)
    proc = subprocess.run(["git", "-C", str(db), "config", "core.hooksPath", ".githooks"],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise UsageError(f"core.hooksPath 설정 실패: {proc.stderr.strip()}")
    value = _hooks_value(db)
    if value != ".githooks":
        raise UsageError(f"core.hooksPath가 '{value}'입니다. 정확히 .githooks여야 한다 (08-safety.md §9).")
    return {"db": str(db), "core.hooksPath": value}


def check(db: Path, defaults: dict, for_: str) -> dict:
    cfg = compat.load_db_config(db)
    if not cfg:
        raise UsageError(f"이슈 DB 설정을 읽을 수 없습니다: {db}")
    branch = _git_out(db, "rev-parse", "--abbrev-ref", "HEAD")
    migrate = bool(branch and MIGRATE_BRANCH_RE.match(branch))
    reasons: list[dict] = []
    schema = cfg.get("schema_version")
    generator = cfg.get("generator_version")
    env = compiled_cache.environment(defaults)
    if not migrate:
        if not isinstance(schema, int) or schema > SUPPORTED_SCHEMA[1]:
            reasons.append({"code": "schema-too-new", "message":
                            f"이슈 DB schema_version {schema}가 플러그인 지원 범위 {SUPPORTED_SCHEMA}보다 새롭다. "
                            "플러그인을 업데이트한다 (읽기 전용 분석만)."})
        elif schema < SUPPORTED_SCHEMA[0]:
            reasons.append({"code": "schema-too-old", "message":
                            f"이슈 DB schema_version {schema}가 플러그인 지원 범위 {SUPPORTED_SCHEMA}보다 옛 버전이다. "
                            "메인테이너에게 마이그레이션이 필요하다고 알린다."})
        if cfg.get("ci_mode", "local") != "actions-build" and generator != GENERATOR_VERSION:
            reasons.append({"code": "generator-mismatch", "message":
                            f"generator_version {generator} ≠ 플러그인 {GENERATOR_VERSION}. 이슈 DB 쓰기 전체를 막는다."})
        reasons += compat.check_parser_backend(cfg, env["backend"]["name"], str(env["backend"]["version"]))
        configured = {}
        for category, conf in (defaults.get("external_parsers") or {}).items():
            try:
                module = adapters.load((conf or {}).get("adapter"))
                configured[category] = {"adapter": module.ADAPTER_NAME,
                                        "version": (conf or {}).get("version") or module.VERSION, "available": True}
            except adapters.AdapterError:
                configured[category] = {"adapter": (conf or {}).get("adapter"), "available": False}
        reasons += compat.check_external(cfg, configured)
    writable = not reasons
    gh = {"checked": False, "ok": None, "host": None}
    if for_ == "write":
        host, ok, message = _gh_auth(defaults)
        gh = {"checked": True, "ok": ok, "host": host}
        if not ok:
            reasons.append({"code": "gh-auth", "message": f"gh 인증 없음 ({host}): gh auth login --hostname {host}"
                                                          f" 후 다시 시도한다. {message[:120]}"})
    push_allowed = writable and for_ == "write" and bool(gh["ok"])
    return {
        "db": str(db),
        "for": for_,
        "branch": branch,
        "migrate_branch": migrate,
        "writable": writable,
        "push_allowed": push_allowed,
        "read_only": not writable,
        "versions": {"schema": {"db": schema, "supported": list(SUPPORTED_SCHEMA)},
                     "generator": {"db": generator, "plugin": GENERATOR_VERSION},
                     "backend": env["backend"]},
        "gh": gh,
        "reasons": reasons,
    }


def cmd_check(args, defaults: dict) -> tuple[dict, int]:
    result = check(_db(args, defaults), defaults, args.for_)
    ok = result["push_allowed"] if args.for_ == "write" else result["writable"]
    return result, (OK if ok else USAGE)


def cmd_gh_status(args, defaults: dict) -> tuple[dict, int]:
    host, ok, message = _gh_auth(defaults)
    result = {"host": host, "ok": ok}
    if not ok:
        result["message"] = (f"쓰기 불가(gh 인증 없음). `gh auth login --hostname {host}`로 로그인한다. "
                             "읽기 설정은 끝났으므로 읽기 전용 분석과 --dry-run 연습은 된다.")
    return result, (OK if ok else USAGE)


# -- doctor (읽기 전용 점검) -----------------------------------------------------------------

SNAPSHOT_STALE_DAYS = 7
DETAIL_MAX = 80
MIN_PYTHON = (3, 11)   # pyproject requires-python
GUARD_SELFTEST_TIMEOUT = 20


def _row(check: str, status: str, detail: str, next_: str | None = None) -> dict:
    row = {"check": check, "status": status, "detail": detail if len(detail) <= DETAIL_MAX else detail[:DETAIL_MAX - 1] + "…"}
    if next_:
        row["next"] = next_
    return row


def _guard_selftest(args, clone: Path | None) -> dict:
    """guard.py에 거부돼야 할 hook 입력을 주고 응답 구조·결정을 본다: (1) 이름에 jira가 든 서버의 쓰기 도구(설정과
    무관하게 deny), (2) clone이 있으면 clone 파일 Write(deny)."""
    root = _plugin_root(args)
    home = str(Path.home())
    # hooks.json은 `python3`(PATH)로 guard를 부른다: 같은 해석기로 시험한다(의존성이 그 해석기에 있어야 한다)
    python = shutil.which("python3")
    other = python is not None and os.path.realpath(python) != os.path.realpath(sys.executable)
    python = python or sys.executable
    events = [{"hook_event_name": "PreToolUse", "tool_name": "mcp__probe-jira__jira_add_comment", "tool_input": {},
               "cwd": home}]
    if clone is not None:
        events.append({"hook_event_name": "PreToolUse", "tool_name": "Write",
                       "tool_input": {"file_path": str(clone / "README.md")}, "cwd": home})
    for event in events:
        try:
            proc = subprocess.run([python, str(root / "scripts" / "guard.py"), "--plugin-root", str(root)],
                                  input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=GUARD_SELFTEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return _row("guard", "fail", f"응답 없음 ({GUARD_SELFTEST_TIMEOUT}s 초과)", "guard.py 직접 실행해 stderr 확인")
        try:
            out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else {}
        except (ValueError, KeyError, TypeError):
            out = {}
        if proc.returncode != 0 or not isinstance(out, dict) or out.get("hookEventName") != "PreToolUse" \
                or out.get("permissionDecision") != "deny":
            got = out.get("permissionDecision") if isinstance(out, dict) else None
            return _row("guard", "fail", f"응답 구조 불일치: {event['tool_name']} 종료 {proc.returncode}·결정 {got or '없음'}",
                        "guard.py 직접 실행해 stderr 확인")
        reason = str(out.get("permissionDecisionReason") or "")
        if "의존성 없음" in reason or "내부 오류" in reason:   # 판정이 아니라 degraded 거부다
            return _row("guard", "fail", f"{'hook python3' if other else 'guard'}: {reason.removeprefix('[telephony-triage] ')}",
                        f"{python}에 pyproject 의존성 설치" if "의존성 없음" in reason else "guard.py 직접 실행해 stderr 확인")
    return _row("guard", "ok", f"deny {len(events)}/{len(events)}" + (" (hook python3≠doctor python)" if other else ""))


def _doctor_rows(args, defaults: dict) -> list[dict]:
    """점검 행. 행 단위로 예외를 흡수한다(그 행 fail). 앞선 행이 실패하면 의존 행은 skip.
    아무것도 만들거나 바꾸지 않는다 (mkdir·fetch·lock·쓰기 없음)."""
    rows: list[dict] = []
    skip = lambda name, why: rows.append(_row(name, "skip", why))  # noqa: E731

    def guarded(name: str, func) -> None:
        try:
            func()
        except Exception as exc:    # noqa: BLE001 — 한 행의 실패가 표 전체를 막지 않는다
            rows.append(_row(name, "fail", f"점검 실패: {type(exc).__name__}: {exc}"))

    # 0 python·deps (config보다 먼저: 이것이 깨지면 나머지 판정이 무의미하다)
    if sys.version_info >= MIN_PYTHON:
        rows.append(_row("python", "ok", ".".join(map(str, sys.version_info[:3]))))
    else:
        rows.append(_row("python", "fail", ".".join(map(str, sys.version_info[:3])),
                         f"Python {'.'.join(map(str, MIN_PYTHON))}+"))

    def deps():
        # PyYAML이 없으면 config.py는 import에서 종료 2로 멈춘다(여기까지 오지 않는다). jsonschema만 따로 본다.
        import yaml
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            rows.append(_row("deps", "fail", "jsonschema 없음", "pip install (pyproject 의존성)"))
            return
        from importlib.metadata import version
        libyaml = "libyaml" if getattr(yaml, "CSafeLoader", None) else "pure"
        rows.append(_row("deps", "ok", f"PyYAML {yaml.__version__}({libyaml})·jsonschema {version('jsonschema')}"))
    guarded("deps", deps)

    # 1 config
    user, cfg = None, None
    try:
        user = userconfig.load_user()
        if user is None:
            rows.append(_row("config", "fail", "사용자 config 없음", "/telephony-triage:setup"))
        else:
            cfg = userconfig.merged(defaults, user)
            rows.append(_row("config", "ok", "config.yaml 있음"))
    except Exception as exc:    # noqa: BLE001 — 읽기 실패도 한 행의 fail이다
        rows.append(_row("config", "fail", f"config 읽기 실패: {exc}", "config.yaml 확인 또는 setup"))
    ok_cfg = cfg is not None

    # 2 scripts_path
    def scripts_path():
        have = userconfig.get(cfg, "plugin.scripts_path")
        want = str(_plugin_root(args) / "scripts")
        if have == want:
            rows.append(_row("scripts_path", "ok", "플러그인 경로와 같음"))
        else:
            rows.append(_row("scripts_path", "warn", "config의 경로가 이 플러그인과 다름" if have else "scripts_path 비어 있음",
                             "config.py sync-scripts-path"))
    guarded("scripts_path", scripts_path) if ok_cfg else skip("scripts_path", "config 없음")

    # 3 clone
    repo_box: list = []

    def clone():
        raw = userconfig.get(cfg, "issue_db.path")
        if not raw:
            rows.append(_row("clone", "fail", "issue_db.path 비어 있음", "setup 1"))
            return
        repo = Path(str(raw)).expanduser()
        if (repo / ".git").exists():
            rows.append(_row("clone", "ok", f"{repo}"))
            repo_box.append(repo)
        else:
            remote = userconfig.get(cfg, "issue_db.remote")
            rows.append(_row("clone", "fail", "이슈 DB clone 없음", f"git clone {remote} {repo}" if remote else "setup 3"))
    guarded("clone", clone) if ok_cfg else skip("clone", "config 없음")

    # 4 hook
    def hook():
        value = _hooks_value(repo_box[0])
        if value == ".githooks":
            rows.append(_row("hook", "ok", "core.hooksPath=.githooks"))
        else:
            rows.append(_row("hook", "fail", f"core.hooksPath={value or '(없음)'}", "config.py install-hooks"))
    guarded("hook", hook) if repo_box else skip("hook", "clone 없음")

    # 4b guard 자가시험 (읽기 전용: guard는 판정만 한다)
    guarded("guard", lambda: rows.append(_guard_selftest(args, repo_box[0] if repo_box else None)))

    # 5 jira (매핑만 본다)
    def jira():
        server = userconfig.get(cfg, "jira.mcp_server")
        tools = userconfig.get(cfg, "jira.tools", {})
        read_tools = userconfig.get(cfg, "jira.read_tools", [])
        hint = "setup 4 (Jira MCP 확인)"
        if tools is None:
            tools = {}
        if read_tools is None:
            read_tools = []
        if not isinstance(tools, dict) or not isinstance(read_tools, list):
            rows.append(_row("jira", "fail", "jira.tools(매핑)·read_tools(목록) 형식 오류", hint))
            return
        names = [v for v in tools.values() if v] + read_tools
        if not server:
            rows.append(_row("jira", "fail", "jira.mcp_server 비어 있음", hint))
        elif not tools.get("get_issue"):
            rows.append(_row("jira", "fail", "jira.tools.get_issue 매핑 비어 있음", hint))
        else:
            problems = _tool_problems(str(server), names)
            if problems:
                rows.append(_row("jira", "fail", problems[0], hint))
            else:
                rows.append(_row("jira", "ok", f"{server} / get_issue 매핑 있음"))
    guarded("jira", jira) if ok_cfg else skip("jira", "config 없음")

    # 6 gh
    def gh():
        host, ok, _message = _gh_auth(defaults)
        if ok:
            rows.append(_row("gh", "ok", f"인증됨 ({host})"))
        else:
            rows.append(_row("gh", "warn", f"gh 인증 없음 ({host}) — 쓰기 불가", f"gh auth login -h {host}"))
    guarded("gh", gh) if ok_cfg else skip("gh", "config 없음")

    # 7 snapshot
    snap_box: list = []
    work_raw = userconfig.get(cfg, "work_dir") if ok_cfg else None
    work = Path(str(work_raw)).expanduser() if work_raw else None

    def snapshot():
        snap_dir = work / session_lock.SNAPSHOT_DIR
        if not (snap_dir / ".git").exists():
            rows.append(_row("snapshot", "warn", "읽기 스냅샷 없음", "/telephony-triage:sync"))
            return
        snap_box.append(snap_dir)
        meta_path = work / session_lock.SNAPSHOT_META
        if not meta_path.is_file():
            rows.append(_row("snapshot", "warn", "시각 기록 없음 (나이 불명)", "/telephony-triage:sync"))
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age = session_lock.now() - session_lock.parse(meta["at"])
            sha = str(meta.get("sha") or "")[:7]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            snap_box.clear()
            rows.append(_row("snapshot", "fail", f"{session_lock.SNAPSHOT_META} 손상: {type(exc).__name__}", "/telephony-triage:sync"))
            return
        days = int(age.total_seconds() // 86400)
        if age > timedelta(days=SNAPSHOT_STALE_DAYS):
            rows.append(_row("snapshot", "warn", f"{days}일 전 ({sha}, {SNAPSHOT_STALE_DAYS}일 초과)", "/telephony-triage:sync"))
        else:
            rows.append(_row("snapshot", "ok", f"{days}일 전 ({sha})"))
    if not ok_cfg:
        skip("snapshot", "config 없음")
    elif work is None:
        skip("snapshot", "work_dir 없음")
    else:
        guarded("snapshot", snapshot)

    # 8 compat (<work_dir>/_snapshot 기준)
    if not snap_box:
        skip("compat", "스냅샷 없음")
    else:
        try:
            result = check(snap_box[0], defaults, "dry-run")
            if result["writable"]:
                rows.append(_row("compat", "ok", "스키마·생성기·파서 호환"))
            else:
                codes = ",".join(r["code"] for r in result["reasons"])
                rows.append(_row("compat", "fail", f"쓰기 막힘: {codes}", "config.py check --for dry-run"))
        except Exception as exc:    # noqa: BLE001
            rows.append(_row("compat", "fail", f"판정 실패: {exc}"))

    # 9 lock
    if not ok_cfg:
        skip("lock", "config 없음")
    elif work is None:
        skip("lock", "work_dir 없음")
    else:
        try:
            held = session_lock.describe(session_lock.read(work))
            if held is None:
                rows.append(_row("lock", "ok", "세션 lock 없음"))
            else:
                mins = held["age_sec"] // 60
                state = "만료" if held["expired"] else "보유 중"
                rows.append(_row("lock", "warn", f"{state}: {held['job']} ({mins}분 전)",
                                 f"끝난 세션이면 db_pr lock release {held['job']} --force"))
        except Exception as exc:    # noqa: BLE001 — 손상 lock 포함
            rows.append(_row("lock", "fail", str(exc) or type(exc).__name__,
                             f"lock 파일 확인: {work / session_lock.LOCK_FILE} — 그 세션이 끝났으면 "
                             "db_pr lock release <작업 키> --force(.corrupt-<ts>로 백업 후 제거)"))
    return rows


def _doctor_markdown(rows: list[dict], counts: dict) -> str:
    cell = lambda text: str(text).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    with_next = any(r.get("next") for r in rows)
    head = "| 점검 | 상태 | 내용 |" + (" 다음 |" if with_next else "")
    lines = [head, "|---|---|---|" + ("---|" if with_next else "")]
    for r in rows:
        line = f"| {r['check']} | {r['status']} | {cell(r['detail'])} |"
        if with_next:
            line += f" {cell(r.get('next', ''))} |"
        lines.append(line)
    lines += ["", " · ".join(f"{k} {counts[k]}" for k in ("ok", "warn", "fail", "skip"))]
    return "\n".join(lines) + "\n"


def cmd_doctor(args, defaults: dict) -> tuple[dict, int]:
    rows = _doctor_rows(args, defaults)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "warn", "fail", "skip")}
    return {"rows": rows, "counts": counts}, (CHECK_FAILED if counts["fail"] else OK)


_MISSING = object()


def cmd_show(args, defaults: dict) -> dict:
    user = userconfig.load_user()
    if args.keys:
        effective = userconfig.merged(defaults, user or {})
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
        found = {k: userconfig.get(effective, k, _MISSING) for k in keys}
        return {"user_config": str(userconfig.path()) if user is not None else None,
                "values": {k: v for k, v in found.items() if v is not _MISSING},
                "missing": [k for k, v in found.items() if v is _MISSING]}
    return {"plugin_root": str(_plugin_root(args)), "site_defaults": str(_plugin_root(args) / site_defaults.FILENAME),
            "user_config": str(userconfig.path()) if user is not None else None,
            "effective": userconfig.merged(defaults, user or {})}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS, help="플러그인 루트 (기본: ${CLAUDE_PLUGIN_ROOT})")
    parser = argparse.ArgumentParser(prog="config.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", parents=[common])
    p.add_argument("--keys", metavar="a,b.c", help="쉼표로 구분한 키(점 표기)만 보인다 (예: work_dir,jira.tools)")
    sub.add_parser("site-defaults", parents=[common])
    p = sub.add_parser("init", parents=[common])
    p.add_argument("--answers")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("set", parents=[common])
    p.add_argument("key")
    p.add_argument("value")
    sub.add_parser("sync-scripts-path", parents=[common])
    p = sub.add_parser("jira-candidates", parents=[common])
    p.add_argument("--mcp-config", action="append")
    p.add_argument("--tools-json")
    p = sub.add_parser("set-jira", parents=[common])
    p.add_argument("--server", required=True)
    p.add_argument("--get-issue", required=True)
    p.add_argument("--search-issues")
    p.add_argument("--get-comments")
    p.add_argument("--read-tools")
    p = sub.add_parser("install-hooks", parents=[common])
    p.add_argument("--db", default=None)
    p = sub.add_parser("check", parents=[common])
    p.add_argument("--db", metavar="path", default=None)
    p.add_argument("--for", dest="for_", choices=["write", "dry-run"], default="write")
    sub.add_parser("gh-status", parents=[common])
    p = sub.add_parser("doctor", parents=[common])
    p.add_argument("--format", choices=("json", "markdown"), default="json",
                   help="markdown: 표 하나와 마지막 줄 카운트 (기본 json, --json과 함께 못 쓴다)")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    if IMPORT_ERROR is not None:
        print(f"의존성 없음: {getattr(IMPORT_ERROR, 'name', None) or IMPORT_ERROR} — pyproject 의존성(PyYAML·jsonschema)을 "
              f"설치한 뒤 다시 실행한다 ({type(IMPORT_ERROR).__name__}: {IMPORT_ERROR})", file=sys.stderr)
        return USAGE
    # 어떤 서브커맨드든 사내 기본값이 먼저다. 없으면 종료 코드 2 (example은 읽지 않는다).
    defaults = site_defaults.load_or_exit(getattr(args, "plugin_root", None))
    code = OK
    try:
        if args.cmd == "site-defaults":
            result = defaults
        elif args.cmd == "show":
            result = cmd_show(args, defaults)
        elif args.cmd == "init":
            result = cmd_init(args, defaults)
        elif args.cmd == "set":
            result = cmd_set(args, defaults)
        elif args.cmd == "sync-scripts-path":
            result = cmd_sync_scripts_path(args, defaults)
        elif args.cmd == "jira-candidates":
            result = cmd_jira_candidates(args, defaults)
        elif args.cmd == "set-jira":
            result = cmd_set_jira(args, defaults)
        elif args.cmd == "install-hooks":
            result = cmd_install_hooks(args, defaults)
        elif args.cmd == "check":
            result, code = cmd_check(args, defaults)
        elif args.cmd == "doctor":
            if args.format == "markdown" and getattr(args, "json", False):
                raise UsageError("--format markdown은 --json과 함께 쓸 수 없다.")
            result, code = cmd_doctor(args, defaults)
            if args.format == "markdown":
                print(_doctor_markdown(result["rows"], result["counts"]), end="")
                return code
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return code
        else:
            result, code = cmd_gh_status(args, defaults)
    except (UsageError, yamlio.YamlFileError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for reason in (result.get("reasons") or []) if isinstance(result, dict) else []:
        print(f"{reason['code']}: {reason['message']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=args.cmd == "site-defaults"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
