#!/usr/bin/env python3
"""바뀐 파일에서 관련 테스트를 고른다 (11-phases.md §11.0).

전체 `pytest tests`(수 분, 수백 건)는 코드를 한 번 고칠 때마다 돌리기엔 비싸다. 이 도구는 바뀐
파일을 보고 (1) 돌려야 할 테스트 파일 목록과 (2) 전체를 돌려야 하는지(`full`)와 그 사유를 낸다.
판정은 정적 검색이다(실행 없음): 테스트 파일 본문에서 모듈 import·스크립트 이름·경로 문자열을
찾는다. 못 찾는 쪽으로 틀리면 위험하므로, 분류할 수 없는 파일은 `full`로 보낸다.

바뀐 파일 = `git diff --name-only <base>`(워킹 트리 기준, 스테이징 포함) + 스테이징 + untracked.
`--base`가 HEAD가 아니면 `git merge-base <base> HEAD`와 비교한다(`--changed`와 같은 규칙,
contracts.md §3.2). 기본 base는 HEAD다.

선택 규칙 (상수는 아래 FULL_PATTERNS 등에서 조정한다)
    plugin/scripts/**.py   그 모듈을 import하거나(`import m`, `from m import`, `from pkg import m`)
                           스크립트 이름(`m.py`, `"m"`, `scripts/m`)으로 부르는 테스트. 거기에
                           plugin/scripts 안의 역 import 그래프(ast + 문자열 `x.py` 호출)로 얻은
                           간접 importer를 참조하는 테스트를 더한다. 간접 importer가 MAX_IMPORTERS(8)개를
                           넘으면 공용 모듈로 보고 full.
                           plugin/scripts가 바뀌면 `tests/test_safety.py`를 더한다(SAFETY_TEST).
                           이 테스트는 잠금·worktree 제거·경로 이탈·반입 롤백·분석 안전 규칙 등 여러
                           스크립트에 걸친 규칙을 고정하는데, 대부분 `db_pr`·`triage`·`parse_logcat`·
                           `match_signatures`를 이름 없이 헬퍼로 불러서 이름 검색으로는 안 잡힌다.
    tests/test_x.py        자기 자신. tests/conftest.py·tests/helpers/**·tests/__init__.py는 full.
                           tests/skill_evals/**와 helpers/skill_eval_env.py는 test_skill_evals.py.
    tests/fixtures|mocks   그 경로 조각(첫 디렉토리, 흔한 이름이면 파일 이름)을 가리키는 테스트.
                           없으면 full.
    plugin/skills|commands|hooks   파일 이름·경로 조각(`skills/`, `commands/`, `hooks.json`)을 가리키는 테스트.
    tools/<t>.*            `<t>`를 가리키는 테스트.
    docs/**, 루트 *.md     그 문서 파일 이름을 가리키는 테스트. 없으면 테스트 없음(경계 검사만).
    그 밖                  이름으로 찾고, 없으면 full(분류 불가).

CLI:
    python3 tools/related_tests.py [--base <rev>] [--files f1 f2 ...] [--json] [--run]

    --files   git 대신 이 파일 목록을 쓴다(레포 루트 기준 경로).
    --json    {"changed", "tests", "full", "reasons", "per_file"}를 stdout에 낸다.
    --run     `python3 -m pytest -q <테스트>`(full이면 `tests`)와 `tools/check_boundary.py`를 실행한다.
              테스트가 0개이고 full이 아니면 pytest는 건너뛰고 경계 검사만 한다.

종료 코드 (contracts.md §종료 코드)
    0  (--run) 테스트·경계 검사 통과, 또는 --run 없이 선택 성공
    1  (--run) 테스트 실패 또는 경계 위반
    2  사용 오류·환경 오류 (git 실패 포함)
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

OK, FAILED, USAGE = 0, 1, 2

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = "plugin/scripts"

# 바뀌면 무조건 전체 테스트인 파일 (glob, 사유). 조정은 여기서 한다.
FULL_PATTERNS = (
    ("plugin/scripts/common/*", "공용 모듈(common)"),
    ("plugin/scripts/parser_backends/base.py", "파서 백엔드 인터페이스"),
    ("plugin/scripts/platforms/__init__.py", "플랫폼 로더"),
    ("plugin/schemas/*", "스키마"),
    ("tests/conftest.py", "테스트 공용 설정"),
    ("tests/__init__.py", "테스트 공용 설정"),
    ("tests/helpers/*", "테스트 헬퍼"),
    ("pyproject.toml", "의존성 핀"),
)
# helpers/** 중 전체를 돌리지 않는 예외 (full 판정보다 먼저 본다).
SKILL_EVAL_PATHS = ("tests/skill_evals/*", "tests/helpers/skill_eval_env.py")
SKILL_EVAL_TEST = "tests/test_skill_evals.py"
SAFETY_TEST = "tests/test_safety.py"      # plugin/scripts가 바뀌면 항상 포함
MAX_IMPORTERS = 8                           # 간접 importer가 이보다 많으면 공용 모듈
GENERIC_FIXTURE_DIRS = {"logs", "plans", "golden", "scenarios"}   # 디렉토리 이름만으로는 너무 넓다
NO_TEST_ROOT_FILES = {".gitignore", ".gitattributes"}


# -- 레포 읽기 -----------------------------------------------------------------------------------

def git(*args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def changed_files(base: str) -> list[str]:
    ref = base
    if base != "HEAD":
        ref = git("merge-base", base, "HEAD").strip()
    names: set[str] = set()
    for out in (git("diff", "--name-only", ref), git("diff", "--name-only", "--cached"),
                git("ls-files", "-o", "--exclude-standard")):
        names.update(line for line in out.splitlines() if line)
    return sorted(names)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def test_files() -> dict[str, str]:
    return {p.relative_to(REPO).as_posix(): read(p) for p in sorted((REPO / "tests").glob("test_*.py"))}


# -- import 그래프 ---------------------------------------------------------------------------------

def module_name(rel: str) -> str:
    """plugin/scripts 기준 점 이름. `common/__init__.py` -> `common`."""
    parts = Path(rel).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def script_modules() -> dict[str, str]:
    """점 이름 -> 레포 상대 경로."""
    root = REPO / SCRIPTS
    return {module_name(p.relative_to(root).as_posix()): p.relative_to(REPO).as_posix()
            for p in sorted(root.rglob("*.py"))}


def _is_pkg(path: str) -> bool:
    return path.endswith("__init__.py")


def import_edges(mods: dict[str, str]) -> dict[str, set[str]]:
    """importer -> 그가 쓰는 모듈 집합 (plugin/scripts 안만)."""
    edges: dict[str, set[str]] = {m: set() for m in mods}
    for mod, rel in mods.items():
        try:
            tree = ast.parse(read(REPO / rel))
        except SyntaxError:
            continue
        pkg = mod if _is_pkg(rel) else mod.rpartition(".")[0]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    targets += [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = pkg.split(".") if pkg else []
                    anchor = anchor[:len(anchor) - (node.level - 1)] if node.level > 1 else anchor
                    base = ".".join(anchor + ([base] if base else []))
                parts = base.split(".") if base else []
                targets += [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
                targets += [f"{base}.{a.name}" if base else a.name for a in node.names]
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # 다른 스크립트를 이름(`db_pr.py`)으로 부르는 호출(같은 프로세스 호출, subprocess)
                targets += [m for m in re.findall(r"\b(\w+)\.py\b", node.value)]
            edges[mod].update(t for t in targets if t in mods and t != mod)
    return edges


def reverse_closure(edges: dict[str, set[str]], start: str) -> set[str]:
    reverse: dict[str, set[str]] = {}
    for importer, used in edges.items():
        for m in used:
            reverse.setdefault(m, set()).add(importer)
    seen: set[str] = set()
    todo = [start]
    while todo:
        for importer in reverse.get(todo.pop(), ()):
            if importer not in seen and importer != start:
                seen.add(importer)
                todo.append(importer)
    return seen


# -- 테스트 검색 -----------------------------------------------------------------------------------

_FROM_RE = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(\([^)]*\)|[^\n]*)", re.M)
_IMPORT_RE = re.compile(r"^\s*import\s+([^\n#]+)", re.M)


def imported_names(text: str) -> set[str]:
    """테스트 본문이 import하는 이름(점 이름 전체, 마지막 조각, `from pkg import x`의 pkg.x)."""
    names: set[str] = set()
    for pkg, items in _FROM_RE.findall(text):
        names.add(pkg)
        for item in re.findall(r"[\w]+", re.sub(r"\bas\s+\w+", "", items.strip("()"))):
            names.add(f"{pkg}.{item}")
            names.add(item)
    for line in _IMPORT_RE.findall(text):
        for part in line.split(","):
            names.add(part.strip().split(" as ")[0].strip())
    return names


def references_module(text: str, imports: set[str], mod: str, rel: str) -> bool:
    last = mod.rsplit(".", 1)[-1]
    if mod in imports or any(name == mod or name.startswith(mod + ".") for name in imports):
        return True
    if last in imports and "." not in mod:
        return True
    stem = rel[len(SCRIPTS) + 1:]
    patterns = [rf"\b{re.escape(last)}\.py\b", rf"""["']{re.escape(last)}["']""",
                rf"scripts/{re.escape(last)}\b", re.escape(stem)]
    return any(re.search(p, text) for p in patterns)


def grep_tests(tests: dict[str, str], needles: list[str], word: bool = False) -> set[str]:
    found = set()
    for path, text in tests.items():
        for needle in needles:
            pat = rf"(?<![\w-]){re.escape(needle)}(?![\w-])" if word else re.escape(needle)
            if re.search(pat, text):
                found.add(path)
                break
    return found


# -- 규칙 ------------------------------------------------------------------------------------------

def matches(path: str, patterns) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


class Selection:
    def __init__(self) -> None:
        self.tests: set[str] = set()
        self.reasons: list[str] = []
        self.per_file: dict[str, dict] = {}

    @property
    def full(self) -> bool:
        return bool(self.reasons)


def select(files: list[str]) -> Selection:
    sel = Selection()
    tests = test_files()
    mods = script_modules()
    edges = import_edges(mods)
    scripts_touched = False

    def add(path: str, found: set[str], note: str = "") -> None:
        sel.tests |= found
        sel.per_file[path] = {"tests": sorted(found), "note": note}

    def full(path: str, reason: str) -> None:
        sel.reasons.append(f"{path}: {reason}")
        sel.per_file[path] = {"tests": [], "note": f"full ({reason})"}

    for path in files:
        if matches(path, SKILL_EVAL_PATHS):
            add(path, {SKILL_EVAL_TEST} & set(tests))
            continue
        reason = next((why for pat, why in FULL_PATTERNS if fnmatch.fnmatch(path, pat)), None)
        if reason:
            full(path, reason)
            continue
        name = Path(path).name

        if path.startswith(SCRIPTS + "/") and path.endswith(".py"):
            scripts_touched = True
            # __init__ 변경은 패키지 전체가 바뀐 것으로 본다.
            if name == "__init__.py":
                pkg = module_name(path[len(SCRIPTS) + 1:])
                changed = [m for m in mods if m == pkg or m.startswith(pkg + ".")]
            else:
                changed = [module_name(path[len(SCRIPTS) + 1:])]
            importers: set[str] = set()
            for mod in changed:
                importers |= reverse_closure(edges, mod)
            importers -= set(changed)
            if len(importers) > MAX_IMPORTERS:
                full(path, f"공용 모듈(간접 importer {len(importers)}개 > {MAX_IMPORTERS})")
                continue
            found = set()
            for mod in set(changed) | importers:
                rel = mods.get(mod)
                if rel is None:
                    continue
                for tpath, text in tests.items():
                    if references_module(text, imported_names(text), mod, rel):
                        found.add(tpath)
            add(path, found, f"importer {len(importers)}개")
        elif path.startswith("tests/test_") and path.endswith(".py") and path.count("/") == 1:
            add(path, {path} & set(tests))
        elif path.startswith("tests/fixtures/") or path.startswith("tests/mocks/"):
            rest = path.split("/")[2:]
            if len(rest) == 1:
                needle = Path(rest[0]).stem if rest[0].endswith(".py") else rest[0]
            elif rest[0] in GENERIC_FIXTURE_DIRS:
                needle = rest[-1]
            else:
                needle = rest[0]
            found = grep_tests(tests, [needle]) - {path}
            if rest[-1] == "README.md":
                found = set()           # 문서 취급
            if found or rest[-1] == "README.md":
                add(path, found, f"참조 `{needle}`")
            else:
                full(path, f"fixture·mock을 가리키는 테스트를 못 찾음(`{needle}`)")
        elif path.startswith(("plugin/skills/", "plugin/commands/", "plugin/hooks/")):
            kind = path.split("/")[1]
            needles = [name, path.split("/", 1)[1]]
            found = grep_tests(tests, needles)
            found |= grep_tests(tests, {"skills": ["skills/", '"skills"'], "commands": ["commands/", '"commands"'],
                                        "hooks": ["hooks.json", "hooks/"]}[kind])
            add(path, found)
        elif path.startswith("tools/"):
            stem = Path(name).stem
            add(path, grep_tests(tests, [stem, name], word=True), f"참조 `{stem}`")
        elif path.startswith("docs/") or ("/" not in path and path.endswith(".md")):
            add(path, grep_tests(tests, [name, path]), "문서")
        elif "/" not in path and name in NO_TEST_ROOT_FILES:
            add(path, set(), "테스트 대상 아님")
        else:
            found = grep_tests(tests, [name, path])
            if found:
                add(path, found, "이름 참조")
            else:
                full(path, "분류할 수 없는 파일")

    if scripts_touched and SAFETY_TEST in tests:
        sel.tests.add(SAFETY_TEST)
    sel.tests &= set(tests)
    return sel


# -- 출력·실행 -------------------------------------------------------------------------------------

def run_checks(sel: Selection) -> int:
    codes = []
    if sel.full or sel.tests:
        targets = ["tests"] if sel.full else sorted(sel.tests)
        cmd = [sys.executable, "-m", "pytest", "-q", *targets]
        print(f"$ {' '.join(cmd)}", flush=True)
        code = subprocess.run(cmd, cwd=REPO, stdin=subprocess.DEVNULL).returncode
        codes.append(0 if code == 0 else 2 if code == 4 else 1)
    else:
        print("pytest: 선택된 테스트 없음, 건너뜀", flush=True)
    cmd = [sys.executable, str(REPO / "tools" / "check_boundary.py")]
    print(f"$ python3 tools/check_boundary.py", flush=True)
    code = subprocess.run(cmd, cwd=REPO, stdin=subprocess.DEVNULL).returncode
    codes.append(0 if code == 0 else 2 if code == 2 else 1)
    return USAGE if USAGE in codes else FAILED if FAILED in codes else OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="바뀐 파일에서 관련 테스트를 고른다.")
    ap.add_argument("--base", default="HEAD", help="비교 기준 rev (기본 HEAD, 그 밖은 merge-base)")
    ap.add_argument("--files", nargs="+", metavar="FILE", help="git 대신 쓸 변경 파일 목록(레포 루트 기준)")
    ap.add_argument("--json", action="store_true", help="결과를 JSON으로 낸다")
    ap.add_argument("--run", action="store_true", help="선택한 테스트와 경계 검사를 실행한다")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return USAGE if exc.code else OK
    try:
        files = sorted({f[2:] if f.startswith("./") else f for f in args.files}) if args.files \
            else changed_files(args.base)
    except RuntimeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return USAGE
    sel = select(files)
    total = len(test_files())
    if args.json:
        print(json.dumps({"changed": files, "tests": sorted(sel.tests), "full": sel.full,
                          "reasons": sel.reasons, "per_file": sel.per_file,
                          "total_tests": total}, ensure_ascii=False, indent=2))
    else:
        print(f"changed: {len(files)}개")
        for path in sorted(sel.tests):
            print(f"  {path}")
        print(f"tests: {len(sel.tests)}/{total}개 파일")
        print(f"full: {'true' if sel.full else 'false'}")
        for reason in sel.reasons:
            print(f"  - {reason}")
    if args.run:
        return run_checks(sel)
    return OK


if __name__ == "__main__":
    sys.exit(main())
