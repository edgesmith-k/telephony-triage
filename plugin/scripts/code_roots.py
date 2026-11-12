#!/usr/bin/env python3
"""code_roots.py — 분석할 소스 트리 선택 (07-workflow.md §Step 2-1, 02-config.md §4, contracts.md §3.2).

    code_roots.py suggest --version <v>
        후보: 버전이 일치하는 `code_profiles` → 최근 사용(`recent_code_roots`, 최신 순) → 나머지 프로필.
        스킬은 여기에 "직접 입력", "코드 분석 건너뛰기"를 더해 사용자에게 묻는다.
    code_roots.py validate <roots> [--version <v>] [--db <path>]
        `<roots>`: 프로필 이름, `aosp=/p,vendor_ril=/q`, 또는 경로 하나(aosp로 간주).
        키가 `code_root_keys`에 있는지, 경로가 있는지, aosp에 필수 디렉토리(`platform.source_tree.required_dirs`,
        기본 `frameworks/opt/telephony`)가 모두 있는지 본다.
        트리 버전을 추정해 `--version`과 다르면 경고한다. 잘못된 루트는 종료 코드 2.
        플랫폼에 구성요소(`platform…components`, 17-platforms §9)가 있으면 주 루트가 아닌 구성요소 루트도
        그 `source_tree`의 필수 디렉토리를 보고 버전을 추정해 `component_versions`(참고용, `--version`과 비교하지 않음)로 낸다.
    code_roots.py resolve <ref> --roots <roots>
        `<root 키>:<상대 경로>` → 절대 경로 (03-issue-db.md §5.4 code_refs).
    code_roots.py find-symbol <symbol> --roots <roots>
        `Class#method` 또는 함수 이름이 있는 위치 → `[{ref, line, kind}]` (`ref`는 `<root 키>:<상대 경로>`).
    code_roots.py find-text --roots <roots> --literals <json> [--events <마스킹된 events.json>]
        C′ 코드 대조(04-parser-matching.md §5.12): 부분 일치의 없는 조건 패턴(≤ 9)에서 찾을 글자를 만들어
        ① code_refs 디렉토리 → ② required_dirs → ③ 루트 전체 순으로 바이트 비교한다(20초·파일 1 MiB·20만 파일 상한).
        `{items[{id, status, refs[≤3 "key:rel:line"], aux_refs, log_call?, log_refs?}], scanned_files, truncated, scope}`.
        status: same|string-only|reworded|not-found|ambiguous|no-literal|limit. 줄 글자는 내지 않는다.
    code_roots.py remember <roots> [--platform-version <v>]
        직접 입력한 루트를 기억한다. `--platform-version`이 있으면 개인 `code_profiles`에
        `{name: <플랫폼><v>-<주 루트 마지막 조각>(겹치면 -2…), platform_version, roots}`로 저장한다(같은 roots 프로필이
        있으면 만들지 않는다, 최근 목록에서는 뺀다) → `{profile, saved, platform_version}`.
        없으면 `recent_code_roots`에 기록한다(최근 5개) → `{recent_code_roots}`.

트리 버전 추정 파일은 `platform.source_tree.version_sources`로 사내 트리에 맞춘다 (`platforms.load()`, 02-config.md).
`platform:`이 잘못되면 종료 코드 2.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import compat, dbpath, site_defaults, userconfig  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
import platforms  # noqa: E402
from platforms import session as platform_session  # noqa: E402

# 플랫폼 상수는 레지스트리(`platforms.get`)에서 온다. `validate()`·`estimate_version()`의 인자 기본값은 기본 플랫폼 것이다.
_DEFAULT_SPEC = platforms.get(platforms.DEFAULT_NAME)
TELEPHONY_DIR = _DEFAULT_SPEC.source_tree.required_dirs[0]   # 옛 이름 (기본 플랫폼의 첫 필수 디렉토리)
VERSION_SOURCES = _DEFAULT_SPEC.source_tree.version_sources
DEFAULT_KEYS = list(_DEFAULT_SPEC.default_root_keys)
RECENT_MAX = 5
SOURCE_SUFFIXES = {".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".aidl"}


class UsageError(Exception):
    pass


_SESSION: tuple[str, dict] | None = None     # main이 정한 (플랫폼, cfg). 없으면 처음 부를 때 정한다


def _session(defaults: dict) -> tuple[str, dict]:
    """선택 플랫폼과 그 플랫폼 경로 프로필 cfg(`--platform` > TT_PLATFORM > 사용자 config > site). 잘못되면 사용 오류."""
    global _SESSION
    if _SESSION is None:
        try:
            _SESSION = platform_session.resolve(defaults)
        except platforms.PlatformConfigError as exc:
            raise UsageError(str(exc)) from exc
    return _SESSION


def _cfg(defaults: dict) -> dict:
    return _session(defaults)[1]


def _keys(args, defaults, spec: platforms.PlatformSpec | None = None, components=()) -> list[str]:
    """DB `code_root_keys`. DB가 없으면 플랫폼 기본 루트 키 + 구성요소 루트 키(순서 유지, 중복 제거)."""
    fallback = list(spec.default_root_keys) if spec else DEFAULT_KEYS
    fallback += [c.root_key for c in components if c.root_key and c.root_key not in fallback]
    try:
        db = dbpath.resolve(getattr(args, "db", None),
                            user_config_path=lambda: userconfig.issue_db_path(defaults, _session(defaults)[0]))
    except dbpath.DbPathError:
        return fallback
    return list(compat.load_db_config(db).get("code_root_keys") or fallback)


def parse_roots(text: str, cfg: dict, primary: str = _DEFAULT_SPEC.primary_root) -> dict[str, str]:
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
    return {primary: text}


def _profile(defaults: dict) -> platforms.PlatformProfile:
    """site-defaults `platform:`(소스 트리·주 루트 키·라벨). 잘못되면 사용 오류(종료 코드 2)."""
    try:
        return platforms.load(defaults, _session(defaults)[0])
    except platforms.PlatformConfigError as exc:
        raise UsageError(str(exc)) from exc


def _tree(defaults: dict) -> platforms.SourceTree:
    """`platform.source_tree`. 잘못되면 사용 오류(종료 코드 2)."""
    return _profile(defaults).source_tree


def estimate_version(aosp: Path, sources=VERSION_SOURCES) -> str | None:
    for rel, regex in sources:
        path = aosp / rel
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:          # 읽기 권한 없음 등 — 이 파일로는 추정하지 못한다(다음 파일, 모두 실패면 None)
                continue
            hit = regex.search(text)
            if hit:
                return hit.group(1)
    return None


def cmd_suggest(args, defaults) -> dict:
    cfg = _cfg(defaults)
    profile = _profile(defaults)
    sources, primary = profile.source_tree.version_sources, profile.spec.primary_root
    version = str(args.version) if args.version else None
    profiles = []
    for p in cfg.get("code_profiles") or []:
        roots = {k: str(v) for k, v in (p.get("roots") or {}).items()}
        aosp = Path(roots.get(primary, "")).expanduser()
        profiles.append({"kind": "profile", "name": p.get("name"), "platform_version": str(p.get("platform_version")),
                         "roots": roots, "estimated_version": estimate_version(aosp, sources) if aosp.is_dir() else None})
    for p in profiles:
        p["match"] = version is not None and version in (p["platform_version"], p["estimated_version"])
    recent = []
    for r in sorted(cfg.get("recent_code_roots") or [], key=lambda r: str(r.get("used_on", "")), reverse=True):
        roots = {k: str(v) for k, v in (r.get("roots") or {}).items()}
        aosp = Path(roots.get(primary, "")).expanduser()
        est = estimate_version(aosp, sources) if aosp.is_dir() else None
        recent.append({"kind": "recent", "name": None, "roots": roots, "used_on": r.get("used_on"),
                       "platform_version": est, "estimated_version": est, "match": version is not None and est == version})
    ordered = ([p for p in profiles if p["match"]] + [r for r in recent if r["match"]]
               + [r for r in recent if not r["match"]] + [p for p in profiles if not p["match"]])
    for i, item in enumerate(ordered, 1):
        item["rank"] = i
        item["recommended"] = i == 1 and item["match"]
    return {"version": version, "candidates": ordered, "extra_choices": ["직접 입력", "코드 분석 건너뛰기"]}


def _component_versions(roots: dict[str, str], primary: str, components, errors: list[str]) -> dict:
    """주 루트가 아닌 구성요소 루트: 주어졌고 디렉토리이면 필수 디렉토리를 보고(`errors`에 더함) 버전을 추정한다.
    없는 구성요소 루트는 오류가 아니다(선택 루트). 버전은 참고용이라 경고하지 않는다(17-platforms K15)."""
    out = {}
    for comp in components:
        key = comp.root_key
        if not key or key == primary or not roots.get(key):
            continue
        root = Path(roots[key]).expanduser()
        if not root.is_dir():
            continue                      # 경로 없음 오류는 위 루트 검사가 이미 냈다
        tree = comp.source_tree
        if tree is None:
            out[key] = None
            continue
        for rel in tree.required_dirs:
            if not (root / rel).is_dir():
                errors.append(f"{key} 루트에 {rel}가 없습니다: {roots[key]}")
        out[key] = estimate_version(root, tree.version_sources)
    return out


def validate(roots: dict[str, str], keys: list[str], version: str | None,
             tree: platforms.SourceTree | None = None, spec: platforms.PlatformSpec | None = None,
             components=()) -> dict:
    """`tree`(`platform.source_tree`)가 없으면 `spec`(없으면 기본 플랫폼)의 코드 기본값.
    `components`(플랫폼 구성요소)가 있을 때만 결과에 `component_versions`가 붙는다(android는 없음 → 출력 불변)."""
    spec = spec or _DEFAULT_SPEC
    tree = tree or spec.source_tree
    required_dirs, sources = tree.required_dirs, tree.version_sources
    primary = spec.primary_root
    errors, warnings = [], []
    for key, value in sorted(roots.items()):
        if key not in keys:
            errors.append(f"루트 키 '{key}'가 code_root_keys({', '.join(keys)})에 없습니다.")
            continue
        if value and not Path(value).expanduser().is_dir():
            errors.append(f"{key}: 경로가 없습니다: {value}")
    aosp = roots.get(primary)
    estimated = None
    if not aosp:
        errors.append(f"{primary} 루트가 필요합니다.")
    elif Path(aosp).expanduser().is_dir():
        root = Path(aosp).expanduser()
        for rel in required_dirs:
            if not (root / rel).is_dir():
                errors.append(f"{primary} 루트에 {rel}가 없습니다: {aosp}")
        estimated = estimate_version(root, sources)
        if estimated is None:
            warnings.append("트리 버전을 추정하지 못했다 (사용자 입력을 신뢰한다)")
        elif version and estimated != str(version):
            warnings.append(f"트리 버전 {estimated}가 대상 {spec.label} {version}과 다르다. 계속할지 묻는다.")
    result = {"roots": roots, "valid": not errors, "errors": errors, "warnings": warnings,
              "estimated_version": estimated, "version": version}
    if components:
        result["component_versions"] = _component_versions(roots, primary, components, errors)
        result["valid"] = not errors
    return result


def cmd_validate(args, defaults) -> tuple[dict, int]:
    profile = _profile(defaults)
    keys = _keys(args, defaults, profile.spec, profile.components)
    result = validate(parse_roots(args.roots, _cfg(defaults), profile.spec.primary_root), keys,
                      args.version, profile.source_tree, profile.spec, profile.components)
    return result, (OK if result["valid"] else USAGE)


def _split_ref(ref: str) -> tuple[str, str]:
    key, sep, rel = ref.partition(":")
    if (not sep or not rel or rel.startswith(("/", "\\")) or PureWindowsPath(rel).drive
            or ".." in Path(rel).parts or ".." in PureWindowsPath(rel).parts):
        raise UsageError(f"code_ref는 <root 키>:<루트 기준 상대 경로>여야 한다: {ref}")
    return key, rel


def cmd_resolve(args, defaults) -> tuple[dict, int]:
    roots = parse_roots(args.roots, _cfg(defaults), _profile(defaults).spec.primary_root)
    key, rel = _split_ref(args.ref)
    if key not in roots:
        raise UsageError(f"루트 '{key}'가 없습니다 (주어진 루트: {', '.join(sorted(roots))}).")
    root = Path(roots[key]).expanduser().resolve()
    path = (root / rel).resolve()
    if not path.is_relative_to(root):
        raise UsageError(f"code_ref가 소스 루트 밖을 가리킵니다: {args.ref}")
    return {"ref": args.ref, "path": str(path), "exists": path.exists()}, OK


def cmd_find_symbol(args, defaults) -> dict:
    roots = parse_roots(args.roots, _cfg(defaults), _profile(defaults).spec.primary_root)
    cls, sep, member = args.symbol.partition("#")
    name_re = re.compile(rf"\b(?:class|interface|enum|object)\s+{re.escape(cls)}\b") if sep else None
    member_re = re.compile(rf"\b{re.escape(member if sep else cls)}\s*\(")
    needle = cls.encode("utf-8")  # `Class#method`는 클래스 이름, 함수 이름만 주면 그 이름 (정규식이 둘 다 글자 그대로를 요구한다)
    matches = []
    for key, value in sorted(roots.items()):
        root = Path(value).expanduser()
        if not root.is_dir():
            continue
        # 소스 트리가 크므로 확장자로 먼저 거르고, 심볼 글자가 바이트에 없는 파일은 해석하지 않는다.
        # (순서는 예전 `sorted(root.rglob("*"))`와 같다: 링크는 따라가지 않고 Path 순으로 정렬)
        found = []
        for base, _dirs, names in os.walk(root, followlinks=False):
            found += [Path(base) / n for n in names if Path(n).suffix in SOURCE_SUFFIXES]
        for path in sorted(found):
            if not path.is_file():
                continue
            # 클래스 이름과 파일 이름이 같으면 본문에 없어도 `class`로 낸다(아래 else). 그 밖에는 이름이 본문에 있어야 한다.
            data = path.read_bytes()      # 한 번만 읽는다 (걸러내기와 해석이 같은 바이트를 쓴다)
            if not (sep and path.stem == cls) and needle not in data:
                continue
            text = data.decode("utf-8", errors="replace")
            if sep and path.stem != cls and not name_re.search(text):
                continue
            rel = path.relative_to(root).as_posix()
            for line_no, line in enumerate(text.splitlines(), 1):
                if member_re.search(line):
                    matches.append({"ref": f"{key}:{rel}", "line": line_no, "kind": "method" if sep else "function"})
                    break
            else:
                if sep:
                    matches.append({"ref": f"{key}:{rel}", "line": None, "kind": "class"})
    return {"symbol": args.symbol, "matches": matches}


# -- find-text: C′ 코드 대조 (04-parser-matching.md §5.12 (5)) ------------------------------------------------
# 줄 글자(사내 코드)는 내지 않는다: 출력은 `<root 키>:<상대 경로>:<줄>`과 상태 낱말뿐이다.

LOG_CALL_RE = re.compile(rb"\w*[Ll]og[a-z]?\(|Log\.|Rlog\.|DBG\(|ofono_\w+\(")
FIND_TEXT_SEC = 20.0
FIND_TEXT_MAX_FILE = 1 << 20
FIND_TEXT_MAX_FILES = 200_000
FIND_TEXT_MAX_ITEMS = 9
FIND_TEXT_REFS = 3
EXCLUDED_DIRS = {".git", ".repo", "out", "build", "prebuilts", "node_modules"}
TEST_DIRS = {"test", "tests"}
_MASK_TOKEN_RE = re.compile(r"<[A-Z][A-Z0-9]*#\d+>")
_PATH_FRAGMENT_RE = re.compile(r"/\w+_\d+")
_LITERAL_MIN = 6
_WORD_MIN = 4


def _regex_runs(pattern: str) -> tuple[list[str], bool]:
    """정규식의 최상위 LITERAL 연속 구간들과 (?i) 여부. 분기·클래스·`.`·`\\s`·반복은 구간을 끊는다.
    그룹은 그 안으로 이어 들어가고(필수 단일 그룹), 분기는 대안이 하나일 때만, 반복은 최소 1이면 그 안만 따로 본다."""
    from db_lint import _parser_mod   # 3.10은 sre_parse·sre_constants(같은 도우미 재사용)
    sp, sc = _parser_mod()
    repeats = tuple(getattr(sc, n) for n in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT") if hasattr(sc, n))
    try:
        parsed = sp.parse(pattern)
    except re.error:
        return [], False
    runs: list[str] = []
    cur: list[str] = []

    def flush():
        if cur:
            runs.append("".join(cur))
            cur.clear()

    def walk(items):
        for op, av in items:
            if op == sc.LITERAL:
                cur.append(chr(av))
            elif op == sc.AT:
                continue
            elif op == sc.SUBPATTERN:
                walk(av[-1])
            elif op == sc.BRANCH and len(av[1]) == 1:
                walk(av[1][0])
            elif op in repeats:
                flush()
                if av[0] >= 1:
                    walk(av[2])
                    flush()
            else:
                flush()

    walk(parsed)
    flush()
    return runs, bool(parsed.state.flags & re.IGNORECASE)


_MSG_FORMAT_FNS: list | None = None


def _msg_format_fns() -> list:
    """설치된 모든 플랫폼 `SPEC.msg_formats`의 함수(이름 순). 플랫폼 이름을 코드에 적지 않는다(17-platforms §1-2 — 예전에는
    `platforms.ofono.msgformat._FILE_FUNC`를 직접 불러 핵심이 플랫폼을 알았다). 한 번만 모은다."""
    global _MSG_FORMAT_FNS
    if _MSG_FORMAT_FNS is None:
        fns = []
        for name in platforms.known():
            try:
                fns += [fn for _label, fn in platforms.get(name).msg_formats]
            except platforms.PlatformConfigError:
                continue
        _MSG_FORMAT_FNS = fns
    return _MSG_FORMAT_FNS


def derive_literal(pattern: str | None, tags=()) -> dict | None:
    """시그니처·파서 규칙 패턴 → 코드에서 찾을 글자 `{literal, aux, icase}` 또는 None(도출 불가).
    태그와 같은 구간·oFono `file.c:func()` 앞머리·`/ril_0` 꼴 경로 조각·마스킹 토큰은 버리고, `: `·`=`에서 끊는다.
    조건: 6자 이상, 영문자 2개 이상. 가장 긴 구간(동률이면 앞)이 literal, 두 번째가 aux."""
    if not pattern:
        return None
    runs, icase = _regex_runs(pattern)
    tags_l = {str(t).lower() for t in tags if t}
    pieces = []
    for run in runs:
        for fn in _msg_format_fns():       # 플랫폼 메시지 하위 형식 앞머리(oFono `file.c:func()`)를 뗀다 — 레지스트리 경유(17 §1-2)
            view = fn(run)
            if view is not None:
                run = view.body
                break
        run = _PATH_FRAGMENT_RE.sub(" ", _MASK_TOKEN_RE.sub("\0", run))
        for piece in re.split(r"\0|: |=", run):
            piece = piece.strip(" \t>:-[](){},;'\"")
            if piece.lower() in tags_l or len(piece) < _LITERAL_MIN:
                continue
            if sum(ch.isascii() and ch.isalpha() for ch in piece) < 2:
                continue
            pieces.append(piece)
    if not pieces:
        return None
    ordered = sorted(pieces, key=len, reverse=True)
    return {"literal": ordered[0], "aux": ordered[1] if len(ordered) > 1 else None, "icase": icase}


def _words(literal: str) -> list[str]:
    """리터럴의 4자 이상 낱말 중 가장 긴 둘(문구 다름 판단용). 둘이 안 되면 []."""
    words = sorted({w for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", literal) if len(w) >= _WORD_MIN},
                   key=lambda w: (-len(w), w))
    return words[:2] if len(words) >= 2 else []


def _walk_files(base: Path, deadline: float, state: dict):
    """`base` 아래 소스 파일(링크 안 따라감, 제외 디렉토리 건너뜀). 상한에 닿으면 `state['truncated']`."""
    for cur, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith("."))
        for name in sorted(names):
            if time.monotonic() > deadline or state["files"] >= FIND_TEXT_MAX_FILES:
                state["truncated"] = True
                return
            path = Path(cur) / name
            if path.suffix not in SOURCE_SUFFIXES or path.is_symlink():
                continue
            yield path


def _event_refs(events_path: str | None, words: list[str], icase: bool) -> list[str]:
    """마스킹된 events.json에서 두 낱말이 함께 든 줄의 `f:L` (≤ 3, 새 문구 제안의 유일한 원천)."""
    if not events_path or not words:
        return []
    try:
        doc = json.loads(Path(events_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or doc.get("masked") is not True:
        return []
    refs = []
    for e in doc.get("events") or []:
        text = f"{e.get('tag')}: {e.get('msg')}"
        text = text.lower() if icase else text
        ref = e.get("line_ref") or {}
        if all((w.lower() if icase else w) in text for w in words) and ref.get("line_no"):
            label = f"{ref.get('file_index')}:{ref['line_no']}"
            if label not in refs:
                refs.append(label)
        if len(refs) >= FIND_TEXT_REFS:
            break
    return refs


def cmd_find_text(args, defaults) -> dict:
    """`--literals`: `{tags[], code_refs["key:rel"], items[{id, pattern}]}` (≤ 9). 범위 ① code_refs 디렉토리 →
    ② 주 루트의 `required_dirs` → ③ 루트 전체(남은 시간). `못 찾음`은 ①②를 다 봤을 때만."""
    profile = _profile(defaults)
    roots = parse_roots(args.roots, _cfg(defaults), profile.spec.primary_root)
    try:
        spec = json.loads(Path(args.literals).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"--literals를 읽을 수 없다: {exc}") from exc
    items = []
    for raw in (spec.get("items") or [])[:FIND_TEXT_MAX_ITEMS]:
        lit = derive_literal(raw.get("pattern"), spec.get("tags") or [])
        item = {"id": str(raw.get("id")), "lit": lit, "same": [], "string": [], "reworded": [], "aux": []}
        if lit:
            item["needle"] = lit["literal"].lower().encode() if lit["icase"] else lit["literal"].encode()
            item["words"] = [(w.lower() if lit["icase"] else w).encode() for w in _words(lit["literal"])]
        items.append(item)
    live = [it for it in items if it["lit"]]
    deadline = time.monotonic() + float(os.environ.get("TT_FIND_TEXT_SEC") or FIND_TEXT_SEC)
    state = {"files": 0, "truncated": False}
    seen: set[Path] = set()

    def scan(base: Path, key: str, root: Path) -> bool:
        if not base.is_dir():
            return False
        for path in _walk_files(base, deadline, state):
            real = path.resolve()
            if real in seen:
                continue
            seen.add(real)
            state["files"] += 1
            try:
                if path.stat().st_size > FIND_TEXT_MAX_FILE:
                    state["truncated"] = True
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            hay = data.lower() if any(it["lit"]["icase"] for it in live) else None
            rel = path.relative_to(root).as_posix()
            is_test = bool(TEST_DIRS & set(Path(rel).parts[:-1]))
            lines = None
            for it in live:
                buf = hay if it["lit"]["icase"] else data
                has_lit = it["needle"] in buf
                has_words = bool(it["words"]) and all(w in buf for w in it["words"])
                if not (has_lit or has_words):
                    continue
                lines = lines if lines is not None else data.splitlines()
                for no, line in enumerate(lines, 1):
                    cmp = line.lower() if it["lit"]["icase"] else line
                    ref = f"{key}:{rel}:{no}"
                    if it["needle"] in cmp:
                        near = b"\n".join(lines[max(0, no - 3):no + 2])
                        bucket = "aux" if is_test else ("same" if LOG_CALL_RE.search(near) else "string")
                        it[bucket].append(ref)
                    elif it["words"] and all(w in cmp for w in it["words"]) and LOG_CALL_RE.search(line):
                        it["aux" if is_test else "reworded"].append(ref)
        return not state["truncated"]

    primary = profile.spec.primary_root
    ref_dirs = []
    for ref in spec.get("code_refs") or []:
        try:
            key, rel = _split_ref(str(ref))
        except UsageError:
            continue
        if key in roots:
            root = Path(roots[key]).expanduser()
            target = root / rel
            target = target.parent if target.suffix else target
            if target.is_dir():
                ref_dirs.append((target, key, root))
    scope = {"code_refs": "없음", "required_dirs": "건너뜀(상한)", "root": "건너뜀(상한)"}
    full = True
    if live:
        if ref_dirs:
            full = all([scan(d, k, r) for d, k, r in ref_dirs])
            scope["code_refs"] = "봄" if full else "건너뜀(상한)"
        # ② 필수 디렉토리: 주 root가 있고, 있는 필수 디렉토리를 하나 이상 상한 없이 다 걸었을 때만 봄
        if primary in roots and full:
            root = Path(roots[primary]).expanduser()
            req = [root / d for d in profile.source_tree.required_dirs if (root / d).is_dir()]
            full = bool(req) and all([scan(d, primary, root) for d in req])
        else:
            full = False
        scope["required_dirs"] = "봄" if full else "건너뜀(상한)"
        if full:
            whole = all([scan(Path(v).expanduser(), k, Path(v).expanduser()) for k, v in sorted(roots.items())])
            scope["root"] = "봄" if whole else "건너뜀(상한)"
    else:
        scope = {"code_refs": "없음", "required_dirs": "건너뜀(찾을 글자 없음)", "root": "건너뜀(찾을 글자 없음)"}
    out_items = []
    for it in items:
        entry = {"id": it["id"]}
        if not it["lit"]:
            entry["status"] = "no-literal"
        else:
            files = {r.rsplit(":", 1)[0] for r in it["reworded"]}
            if (it["same"] and it["reworded"]) or len(files) >= 4:
                entry["status"], refs = "ambiguous", (it["same"][:1] + it["reworded"][:1]) if it["same"] else it["reworded"][:2]
            elif it["same"]:
                entry["status"], refs = "same", it["same"]
            elif it["reworded"]:
                entry["status"], refs = "reworded", it["reworded"]
                entry["log_refs"] = _event_refs(args.events, _words(it["lit"]["literal"]), it["lit"]["icase"])
            elif it["string"]:
                entry["status"], refs = "string-only", it["string"]
            elif full:
                entry["status"], refs = "not-found", []
            else:
                entry["status"], refs = "limit", []
            entry["refs"] = refs[:FIND_TEXT_REFS]
            entry["log_call"] = entry["status"] in ("same", "reworded")
        entry["aux_refs"] = it["aux"][:FIND_TEXT_REFS]
        out_items.append(entry)
    return {"items": out_items, "scanned_files": state["files"], "truncated": state["truncated"], "scope": scope,
            **({"reason": "시간·크기 상한"} if state["truncated"] else {})}


def cmd_remember(args, defaults) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 setup을 한다.")
    primary = _profile(defaults).spec.primary_root
    roots = parse_roots(args.roots, _cfg(defaults), primary)
    platform = _session(defaults)[0]
    key = userconfig.profile_key(platform, "recent_code_roots")   # 선택 플랫폼 프로필에 기록한다
    def norm(r: dict) -> dict:    # 비교만 정규화(끝 구분자·~), 저장 값은 입력 그대로
        return {k: str(Path(str(v).rstrip("\\/") or str(v)).expanduser()) for k, v in (r or {}).items()}

    recent = [r for r in userconfig.get(data, key) or [] if norm(r.get("roots")) != norm(roots)]
    # 버전(트리 추정, 숫자)을 알면 개인 프로필로 저장하고 최근 목록에서는 뺀다(목록에 두 번 나오지 않게).
    # 숫자가 아닌 값("Android 16" 같은 문구)은 굳히지 않고 종전대로 최근 경로에만
    if args.platform_version and re.fullmatch(r"\d+", str(args.platform_version)):
        pkey = userconfig.profile_key(platform, "code_profiles")
        profiles = list(userconfig.get(data, pkey) or [])
        same = next((p for p in profiles if norm(p.get("roots")) == norm(roots)), None)
        name = same.get("name") if same else None
        if same is None:
            tail = re.sub(r"[^A-Za-z0-9._-]", "_", re.split(r"[\\/]", str(roots.get(primary, "")).rstrip("\\/"))[-1])
            base = f"{platform}{args.platform_version}-{tail.strip('_.') and tail or 'tree'}"
            names = {p.get("name") for p in profiles}
            name, n = base, 2
            while name in names:
                name, n = f"{base}-{n}", n + 1
            profiles.append({"name": name, "platform_version": str(args.platform_version), "roots": roots})
            userconfig.set_value(data, pkey, profiles)
        userconfig.set_value(data, key, recent)
        userconfig.save(data)
        return {"profile": name, "saved": same is None, "platform_version": str(args.platform_version)}
    recent.insert(0, {"roots": roots, "used_on": date.today().isoformat()})
    userconfig.set_value(data, key, recent[:RECENT_MAX])
    userconfig.save(data)
    return {"recent_code_roots": userconfig.get(data, key)}


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
                if "--platform" not in opts:
                    sub.add_argument("--platform", metavar="이름", default=argparse.SUPPRESS, help=platform_session.HELP)
                _allow_common_anywhere(sub)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code_roots.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    platform_session.add_arg(parser)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("suggest")
    p.add_argument("--version", metavar="v")
    p = sub.add_parser("validate")
    p.add_argument("roots")
    p.add_argument("--version", metavar="v")
    p.add_argument("--db")
    p = sub.add_parser("resolve")
    p.add_argument("ref")
    p.add_argument("--roots", required=True)
    p = sub.add_parser("find-symbol")
    p.add_argument("symbol")
    p.add_argument("--roots", required=True)
    p = sub.add_parser("remember")
    p.add_argument("roots")
    p.add_argument("--platform-version", metavar="v")
    p = sub.add_parser("find-text")
    p.add_argument("--roots", required=True)
    p.add_argument("--literals", required=True, metavar="json")
    p.add_argument("--events", metavar="마스킹된 events.json")
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
    global _SESSION
    _SESSION = None
    try:
        if args.platform:
            try:
                _SESSION = platform_session.resolve(defaults, args.platform)
            except platforms.PlatformConfigError as exc:
                raise UsageError(str(exc)) from exc
        if args.cmd == "suggest":
            result = cmd_suggest(args, defaults)
        elif args.cmd == "validate":
            result, code = cmd_validate(args, defaults)
        elif args.cmd == "resolve":
            result, code = cmd_resolve(args, defaults)
        elif args.cmd == "find-symbol":
            result = cmd_find_symbol(args, defaults)
        elif args.cmd == "find-text":
            result = cmd_find_text(args, defaults)
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
