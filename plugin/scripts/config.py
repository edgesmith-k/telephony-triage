#!/usr/bin/env python3
"""config.py — 사용자 config, 사내 기본값, 호환성 판정 (02-config.md §4·§5.3, contracts.md §3.2,
06-collaboration.md §6.4, 16-existing-assets.md §16.1).

설정 우선순위: 사용자 config(`~/.telephony-triage/config.yaml`) > 플러그인 `site-defaults.yaml` >
코드 내장 기본값. `site-defaults.yaml`이 없으면 모든 서브커맨드가 종료 코드 2로 멈춘다
("사내 기본값 없음"). `site-defaults.example.yaml`은 읽지 않는다.

서브커맨드
  show                         해석된 설정 (우선순위 적용)
  site-defaults                site-defaults.yaml 내용
  init [--answers <json>]      config 생성 (setup 1). --answers가 없으면 stdin으로 항목별로 묻는다.
                               경로가 없으면 거부한다. 홈·work_dir은 권한 700.
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
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import adapters  # noqa: E402
from common import compat, dbpath, ghcli, mcptools, site_defaults, userconfig  # noqa: E402
from common import compiled as compiled_cache  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from common.versions import GENERATOR_VERSION, SCHEMA_VERSION  # noqa: E402

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
        from parser_backends import logcat

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

    data = userconfig.deep_merge(userconfig.builtin(), userconfig.from_site_defaults(defaults))
    for key, _, _kind, _ in FIELDS:
        value = answers.get(key)
        if value not in (None, ""):
            userconfig.set_value(data, key, value)
    data.setdefault("plugin", {})["scripts_path"] = str(_plugin_root(args) / "scripts")
    userconfig.ensure_private_dir(userconfig.home())
    userconfig.ensure_private_dir(Path(userconfig.get(data, "work_dir")).expanduser())
    path = userconfig.save(data)
    clone = Path(userconfig.get(data, "issue_db.path")).expanduser()
    return {"config": str(path), "clone_exists": clone.is_dir() and (clone / ".git").exists(),
            "suggest_clone": None if (clone / ".git").exists() else
            f"git clone {userconfig.get(data, 'issue_db.remote')} {clone}"}


def _parse_value(text: str):
    import yaml

    try:
        return yaml.safe_load(text)
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


def cmd_set_jira(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 config.py init을 한다.")
    tools = {"get_issue": args.get_issue, "search_issues": args.search_issues, "get_comments": args.get_comments}
    tools = {k: v for k, v in tools.items() if v}
    read_tools = [t.strip() for t in (args.read_tools or "").split(",") if t.strip()]
    for name in list(tools.values()) + read_tools:
        hit = TOOL_NAME_RE.match(name)
        if not hit:
            raise UsageError(f"도구 이름은 전체 이름(mcp__<server>__<tool>)이어야 합니다: {name}")
        if hit.group("server") != args.server:
            raise UsageError(f"{name}는 서버 {args.server}의 도구가 아닙니다.")
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
    value = _git_out(db, "config", "--get", "core.hooksPath")
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
        host = userconfig.get(userconfig.merged(defaults), "issue_db.ghe_host")
        ok, message = ghcli.auth_status(host)
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
    host = userconfig.get(userconfig.merged(defaults), "issue_db.ghe_host")
    ok, message = ghcli.auth_status(host)
    result = {"host": host, "ok": ok}
    if not ok:
        result["message"] = (f"쓰기 불가(gh 인증 없음). `gh auth login --hostname {host}`로 로그인한다. "
                             "읽기 설정은 끝났으므로 읽기 전용 분석과 --dry-run 연습은 된다.")
    return result, (OK if ok else USAGE)


def cmd_show(args, defaults: dict) -> dict:
    user = userconfig.load_user()
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
    sub.add_parser("show", parents=[common])
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
    p.add_argument("--db", default=None)
    p.add_argument("--for", dest="for_", choices=["write", "dry-run"], default="write")
    sub.add_parser("gh-status", parents=[common])
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
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
        else:
            result, code = cmd_gh_status(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for reason in (result.get("reasons") or []) if isinstance(result, dict) else []:
        print(f"{reason['code']}: {reason['message']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=args.cmd == "site-defaults"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
