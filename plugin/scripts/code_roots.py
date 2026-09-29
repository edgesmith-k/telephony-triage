#!/usr/bin/env python3
"""code_roots.py — 분석할 소스 트리 선택 (07-workflow.md §Step 2-1, 02-config.md §4, contracts.md §3.2).

    code_roots.py suggest --version <v>
        후보: 버전이 일치하는 `code_profiles` → 최근 사용(`recent_code_roots`, 최신 순) → 나머지 프로필.
        스킬은 여기에 "직접 입력", "코드 분석 건너뛰기"를 더해 사용자에게 묻는다.
    code_roots.py validate <roots> [--version <v>] [--db <path>]
        `<roots>`: 프로필 이름, `aosp=/p,vendor_ril=/q`, 또는 경로 하나(aosp로 간주).
        키가 `code_root_keys`에 있는지, 경로가 있는지, aosp에 `frameworks/opt/telephony`가 있는지 본다.
        트리 버전을 추정해 `--version`과 다르면 경고한다. 잘못된 루트는 종료 코드 2.
    code_roots.py resolve <ref> --roots <roots>
        `<root 키>:<상대 경로>` → 절대 경로 (03-issue-db.md §5.4 code_refs).
    code_roots.py find-symbol <symbol> --roots <roots>
        `Class#method` 또는 함수 이름이 있는 위치 → `[{ref, line, kind}]` (`ref`는 `<root 키>:<상대 경로>`).
    code_roots.py remember <roots>
        직접 입력한 루트를 `recent_code_roots`에 기록한다(최근 5개).

트리 버전 추정 파일은 사내 트리에서 확인한다 — TODO(SITE:S11).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import compat, dbpath, site_defaults, userconfig  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402

DEFAULT_KEYS = ["aosp", "vendor_ril"]
RECENT_MAX = 5
TELEPHONY_DIR = "frameworks/opt/telephony"
SOURCE_SUFFIXES = {".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".aidl"}
# (파일, 정규식) 순서대로 시도한다 — TODO(SITE:S11) 최신 AOSP는 release config 쪽에 있을 수 있다.
VERSION_SOURCES = [
    ("build/release/release_config_map.textproto", re.compile(r"RELEASE_PLATFORM_VERSION\D*(\d+)")),
    ("build/make/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.M)),
    ("build/core/version_defaults.mk", re.compile(r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)", re.M)),
]


class UsageError(Exception):
    pass


def _cfg(defaults: dict) -> dict:
    return userconfig.merged(defaults)


def _keys(args, defaults) -> list[str]:
    try:
        db = dbpath.resolve(getattr(args, "db", None), user_config_path=lambda: userconfig.issue_db_path(defaults))
    except dbpath.DbPathError:
        return DEFAULT_KEYS
    return list(compat.load_db_config(db).get("code_root_keys") or DEFAULT_KEYS)


def parse_roots(text: str, cfg: dict) -> dict[str, str]:
    for profile in cfg.get("code_profiles") or []:
        if profile.get("name") == text:
            return {k: str(v) for k, v in (profile.get("roots") or {}).items()}
    text = text.strip()
    if text.startswith("{"):
        return {k: str(v) for k, v in json.loads(text).items()}
    if "=" in text:
        out = {}
        for part in text.split(","):
            key, sep, value = part.partition("=")
            if not sep:
                raise UsageError(f"루트는 <키>=<경로> 형식이다: {part}")
            out[key.strip()] = value.strip()
        return out
    return {"aosp": text}


def estimate_version(aosp: Path) -> str | None:
    for rel, regex in VERSION_SOURCES:
        path = aosp / rel
        if path.is_file():
            hit = regex.search(path.read_text(encoding="utf-8", errors="replace"))
            if hit:
                return hit.group(1)
    return None


def cmd_suggest(args, defaults) -> dict:
    cfg = _cfg(defaults)
    version = str(args.version) if args.version else None
    profiles = []
    for p in cfg.get("code_profiles") or []:
        roots = {k: str(v) for k, v in (p.get("roots") or {}).items()}
        aosp = Path(roots.get("aosp", "")).expanduser()
        profiles.append({"kind": "profile", "name": p.get("name"), "android_version": str(p.get("android_version")),
                         "roots": roots, "estimated_version": estimate_version(aosp) if aosp.is_dir() else None})
    for p in profiles:
        p["match"] = version is not None and version in (p["android_version"], p["estimated_version"])
    recent = []
    for r in sorted(cfg.get("recent_code_roots") or [], key=lambda r: str(r.get("used_on", "")), reverse=True):
        roots = {k: str(v) for k, v in (r.get("roots") or {}).items()}
        aosp = Path(roots.get("aosp", "")).expanduser()
        est = estimate_version(aosp) if aosp.is_dir() else None
        recent.append({"kind": "recent", "name": None, "roots": roots, "used_on": r.get("used_on"),
                       "android_version": est, "estimated_version": est, "match": version is not None and est == version})
    ordered = ([p for p in profiles if p["match"]] + [r for r in recent if r["match"]]
               + [r for r in recent if not r["match"]] + [p for p in profiles if not p["match"]])
    for i, item in enumerate(ordered, 1):
        item["rank"] = i
        item["recommended"] = i == 1 and item["match"]
    return {"version": version, "candidates": ordered, "extra_choices": ["직접 입력", "코드 분석 건너뛰기"]}


def validate(roots: dict[str, str], keys: list[str], version: str | None) -> dict:
    errors, warnings = [], []
    for key, value in sorted(roots.items()):
        if key not in keys:
            errors.append(f"루트 키 '{key}'가 code_root_keys({', '.join(keys)})에 없습니다.")
            continue
        if value and not Path(value).expanduser().is_dir():
            errors.append(f"{key}: 경로가 없습니다: {value}")
    aosp = roots.get("aosp")
    estimated = None
    if not aosp:
        errors.append("aosp 루트가 필요합니다.")
    elif Path(aosp).expanduser().is_dir():
        root = Path(aosp).expanduser()
        if not (root / TELEPHONY_DIR).is_dir():
            errors.append(f"aosp 루트에 {TELEPHONY_DIR}가 없습니다: {aosp}")
        estimated = estimate_version(root)
        if estimated is None:
            warnings.append("트리 버전을 추정하지 못했다 (사용자 입력을 신뢰한다)")
        elif version and estimated != str(version):
            warnings.append(f"트리 버전 {estimated}가 대상 Android {version}과 다르다. 계속할지 묻는다.")
    return {"roots": roots, "valid": not errors, "errors": errors, "warnings": warnings,
            "estimated_version": estimated, "version": version}


def cmd_validate(args, defaults) -> tuple[dict, int]:
    result = validate(parse_roots(args.roots, _cfg(defaults)), _keys(args, defaults), args.version)
    return result, (OK if result["valid"] else USAGE)


def _split_ref(ref: str) -> tuple[str, str]:
    key, sep, rel = ref.partition(":")
    if not sep or not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        raise UsageError(f"code_ref는 <root 키>:<루트 기준 상대 경로>여야 한다: {ref}")
    return key, rel


def cmd_resolve(args, defaults) -> tuple[dict, int]:
    roots = parse_roots(args.roots, _cfg(defaults))
    key, rel = _split_ref(args.ref)
    if key not in roots:
        raise UsageError(f"루트 '{key}'가 없습니다 (주어진 루트: {', '.join(sorted(roots))}).")
    path = Path(roots[key]).expanduser() / rel
    return {"ref": args.ref, "path": str(path), "exists": path.exists()}, OK


def cmd_find_symbol(args, defaults) -> dict:
    roots = parse_roots(args.roots, _cfg(defaults))
    cls, sep, member = args.symbol.partition("#")
    name_re = re.compile(rf"\b(?:class|interface|enum|object)\s+{re.escape(cls)}\b") if sep else None
    member_re = re.compile(rf"\b{re.escape(member if sep else cls)}\s*\(")
    matches = []
    for key, value in sorted(roots.items()):
        root = Path(value).expanduser()
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.suffix not in SOURCE_SUFFIXES or not path.is_file():
                continue
            if sep and path.stem != cls:
                text = path.read_text(encoding="utf-8", errors="replace")
                if not name_re.search(text):
                    continue
            else:
                text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(root).as_posix()
            for line_no, line in enumerate(text.splitlines(), 1):
                if member_re.search(line):
                    matches.append({"ref": f"{key}:{rel}", "line": line_no, "kind": "method" if sep else "function"})
                    break
            else:
                if sep:
                    matches.append({"ref": f"{key}:{rel}", "line": None, "kind": "class"})
    return {"symbol": args.symbol, "matches": matches}


def cmd_remember(args, defaults) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 setup을 한다.")
    roots = parse_roots(args.roots, _cfg(defaults))
    recent = [r for r in data.get("recent_code_roots") or [] if (r.get("roots") or {}) != roots]
    recent.insert(0, {"roots": roots, "used_on": date.today().isoformat()})
    data["recent_code_roots"] = recent[:RECENT_MAX]
    userconfig.save(data)
    return {"recent_code_roots": data["recent_code_roots"]}


def _allow_common_anywhere(parser: argparse.ArgumentParser) -> None:
    """`--json`·`--plugin-root`를 서브커맨드 앞뒤 어디에 줘도 받는다(contracts.md §3.2 공통 규칙, 다른 스크립트와 같게)."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                opts = {o for a in sub._actions for o in a.option_strings}
                if "--json" not in opts:
                    sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
                if "--plugin-root" not in opts:
                    sub.add_argument("--plugin-root", default=argparse.SUPPRESS)
                _allow_common_anywhere(sub)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code_roots.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("suggest")
    p.add_argument("--version")
    p = sub.add_parser("validate")
    p.add_argument("roots")
    p.add_argument("--version")
    p.add_argument("--db")
    p = sub.add_parser("resolve")
    p.add_argument("ref")
    p.add_argument("--roots", required=True)
    p = sub.add_parser("find-symbol")
    p.add_argument("symbol")
    p.add_argument("--roots", required=True)
    p = sub.add_parser("remember")
    p.add_argument("roots")
    _allow_common_anywhere(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    code = OK
    try:
        if args.cmd == "suggest":
            result = cmd_suggest(args, defaults)
        elif args.cmd == "validate":
            result, code = cmd_validate(args, defaults)
        elif args.cmd == "resolve":
            result, code = cmd_resolve(args, defaults)
        elif args.cmd == "find-symbol":
            result = cmd_find_symbol(args, defaults)
        else:
            result = cmd_remember(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for error in result.get("errors") or []:
        print(f"거부: {error}", file=sys.stderr)
    for warning in result.get("warnings") or []:
        print(f"경고: {warning}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
