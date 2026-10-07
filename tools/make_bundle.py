#!/usr/bin/env python3
"""사내 반입 묶음을 만든다 (15-local-draft.md §15.4).

반입 전 체크리스트의 자동 항목을 싼 것부터 실행하고(첫 실패에서 중단), 모두 통과하면
반입 묶음(레포 zip, 이슈 DB 뼈대 zip, SHA256SUMS, 결과 JSON, 로그)을 만든다.
사람이 확인할 항목(manual)은 판정하지 않고 목록으로 낸다. 태그는 만들지 않는다.
출력할 `git tag … && git push …` 명령은 사용자가 직접 실행한다(remote가 하나면 그 이름).
HEAD가 원격 main에 들어 있는지(`on_remote_main`)는 보고만 한다.
실행 전 할 일: `plugin/.claude-plugin/plugin.json` description에서 '사외 초안'을 빼고 커밋한다(첫 검사).

판정 기준은 각 검사 도구의 종료 코드와 이 도구의 파일 검사다. `--skip`한 검사는
통과로 세지 않고, 하나라도 건너뛰면 묶음을 만들지 않는다. 검사는 임시 디렉토리만
쓰도록 만들었고, 끝난 뒤 추적·비추적(무시 제외) 파일 기준으로 트리를 바꾸지 않았음을
확인한다 (`git status --porcelain`; 무시 파일은 보지 않는다).

CLI:
    python3 tools/make_bundle.py --label LABEL [--out DIR] [--force] [--skip ID[,ID]] [--json] [--repo DIR]

    --label  묶음 이름. `[A-Za-z0-9._-]+`이고 git 태그 이름으로 쓸 수 있어야 한다.
    --out    출력 디렉토리 (기본: <레포 상위>/tt-import-bundles/<label>/, 레포 안·레포의 상위·홈·루트는 불가)
    --force  --out이 비었거나 이전 묶음(make_bundle-result.json 있음)이면 바꿔 만든다. 다른 디렉토리는 지우지 않는다
    --skip   건너뛸 검사 id (쉼표 또는 반복). 건너뛰면 묶음을 만들지 않는다
    --repo   대상 레포 루트 (기본: 이 레포)

종료 코드 (contracts.md §종료 코드)
    1  자동 검사 실패 또는 --skip (묶음 없음)
    2  사용 오류·환경 오류 (레포 아님, 트리 더럽, 태그 불일치, 하위 도구 종료 2 포함)
    3  자동 검사 모두 통과, 묶음 생성, 사람 확인 대기 (정상 완료)
    0은 없다: 사람 확인이 남아 있으므로 이 도구는 완료를 선언하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from import_draft import is_site_path  # noqa: E402

FAILED, USAGE, NEEDS_APPROVAL = 1, 2, 3
GUARD_ENV = "TT_MAKE_BUNDLE_INNER"
LABEL_RE = re.compile(r"^[A-Za-z0-9._-]+$")
ZIP_DATE = (1980, 1, 1, 0, 0, 0)
DRAFT_NOTES_LIMIT = 8192
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache"}
# 뼈대에서 유형 디렉토리가 아닌 최상위 경로 (그 밖의 최상위 디렉토리는 빈 카테고리여야 한다).
SKELETON_NON_CATEGORY = {"schema", "templates", "parser-rules", "docs", ".github", ".githooks", "feedback"}
SYNTHETIC_RE = re.compile(r"^\s*origin:\s*['\"]?synthetic", re.MULTILINE)


class UsageError(Exception):
    """사용 오류·환경 오류 (종료 코드 2)."""


@dataclass
class CheckResult:
    status: str                      # pass | fail | error
    detail: str = ""
    data: object = None


@dataclass
class Check:
    id: str
    checklist: int                   # 15-local-draft.md §15.4 항목 번호 (1..10)
    kind: str                        # auto | manual
    fn: Callable | None = None       # fn(ctx) -> CheckResult (manual은 None)
    how: str = ""                    # manual: 사람이 할 일


class Ctx:
    """검사 실행 문맥: 레포, 임시 디렉토리, 환경, 로그, 지연 생성되는 임시 플러그인 루트."""

    def __init__(self, repo: Path, tmp: Path, env: dict):
        self.repo = repo
        self.tmp = tmp
        self.env = env
        self.logs = tmp / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self._plugin_root: Path | None = None
        self.current_log: str | None = None

    def plugin_root(self) -> Path:
        if self._plugin_root is None:
            out = self.tmp / "plugin-root"
            proc = subprocess.run(
                [sys.executable, str(self.repo / "tests" / "helpers" / "make_plugin_root.py"), "--out", str(out)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=self.env, cwd=self.tmp,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"임시 플러그인 루트를 만들지 못했습니다: {proc.stderr.strip()[-300:]}")
            self._plugin_root = out
        return self._plugin_root

    def run(self, check_id: str, argv: list[str], *, cwd: Path | None = None, env: dict | None = None,
            timeout: int = 900) -> tuple[int, str]:
        """하위 프로세스를 돌린다. 출력 전체는 logs/<id>.log에, 호출자에게는 합친 출력을 준다."""
        log = self.logs / f"{check_id}.log"
        try:
            proc = subprocess.run(argv, cwd=str(cwd or self.repo), env=env or self.env, capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=timeout)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            code, out = USAGE, _text(exc.stdout)
            err = f"시간 초과({timeout}초): {' '.join(argv)}\n{_text(exc.stderr)}"
        log.write_text(f"$ {' '.join(argv)}\n[exit {code}]\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n",
                       encoding="utf-8")
        self.current_log = f"logs/{check_id}.log"
        return code, (out + ("\n" if out and err else "") + err)


def _text(data) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)


def tail(text: str, lines: int = 20) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def from_exit(code: int, ok_detail: str, out: str) -> CheckResult:
    """하위 도구 종료 코드 → 결과 (0 통과, 1 실패, 그 밖(2 포함)은 오류)."""
    if code == 0:
        return CheckResult("pass", ok_detail)
    return CheckResult("fail" if code == 1 else "error", f"종료 {code}\n{tail(out)}")


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if check and proc.returncode != 0:
        raise UsageError(f"git {' '.join(args)} 실패: {proc.stderr.strip()}")
    return proc.stdout


def load_site_paths(repo: Path) -> list[str]:
    path = repo / "SITE_PATHS"
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]


# -- 검사 ----------------------------------------------------------------------------------


def check_plugin_json(ctx: Ctx) -> CheckResult:
    path = ctx.repo / "plugin" / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult("fail", f"{path.name}를 읽을 수 없습니다: {exc}")
    problems = []
    if "사외 초안" in str(data.get("description", "")):
        problems.append("description에서 '사외 초안'을 빼고 커밋한 뒤 실행합니다")
    if "version" in data:
        problems.append("version을 두지 않습니다 (marketplace 항목 또는 commit SHA, 15-local-draft.md §15.6)")
    if problems:
        return CheckResult("fail", "\n".join(problems))
    return CheckResult("pass", "plugin.json description 정리됨, version 없음")


def check_site_paths(ctx: Ctx) -> CheckResult:
    repo = ctx.repo
    problems = []
    if (repo / "plugin" / "site-defaults.yaml").exists():
        problems.append("plugin/site-defaults.yaml이 있습니다")
    if not (repo / "plugin" / "site-defaults.example.yaml").is_file():
        problems.append("plugin/site-defaults.example.yaml이 없습니다")
    patterns = load_site_paths(repo)
    if not patterns:
        problems.append("SITE_PATHS가 없거나 비어 있습니다")
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(repo).as_posix()
            if is_site_path(rel, patterns):
                problems.append(f"SITE_PATHS 경로에 파일이 있습니다: {rel}")
    if problems:
        return CheckResult("fail", "\n".join(problems[:20]), {"problems": len(problems)})
    return CheckResult("pass", f"site-defaults.yaml 없음, SITE_PATHS {len(patterns)}줄에 맞는 파일 없음")


def check_mcp_local(ctx: Ctx) -> CheckResult:
    problems = []
    if (ctx.repo / ".mcp.json").exists():
        problems.append("레포 루트에 .mcp.json이 있습니다 (모의 MCP는 tests/mocks/mcp.json)")
    tracked = git(ctx.repo, "ls-files", "-z", "--", ".local-draft").strip("\0")
    if tracked:
        problems.append(".local-draft가 git에 추적되고 있습니다")
    if problems:
        return CheckResult("fail", "\n".join(problems))
    return CheckResult("pass", ".mcp.json 없음, .local-draft 비추적")


def tool_check(check_id: str, tool: str, args: list[str], ok_detail: str) -> Callable:
    def fn(ctx: Ctx) -> CheckResult:
        code, out = ctx.run(check_id, [sys.executable, str(ctx.repo / "tools" / tool), *args])
        return from_exit(code, ok_detail, out)
    return fn


def check_boundary(ctx: Ctx) -> CheckResult:
    code, out = ctx.run("boundary", [sys.executable, str(ctx.repo / "tools" / "check_boundary.py"),
                                     "--root", str(ctx.repo), "--mode", "external"])
    return from_exit(code, "check_boundary --mode external 위반 없음", out)


def check_site_todos(ctx: Ctx) -> CheckResult:
    code, out = ctx.run("site-todos", [sys.executable, str(ctx.repo / "tools" / "list_site_todos.py"),
                                       "--root", str(ctx.repo), "--json"])
    if code != 0:
        return from_exit(code, "", out)
    try:
        found = json.loads(out)
    except ValueError:
        return CheckResult("error", f"출력이 JSON이 아닙니다\n{tail(out)}")
    count = sum(len(v) for v in found.values())
    return CheckResult("pass", f"TODO(SITE) {count}곳 (S번호 {len(found)}종) — 개수만 기록", {"count": count})


def check_draft_notes_size(ctx: Ctx) -> CheckResult:
    path = ctx.repo / "DRAFT_NOTES.md"
    if not path.is_file():
        return CheckResult("fail", "DRAFT_NOTES.md가 없습니다")
    size = path.stat().st_size
    status = "pass" if size <= DRAFT_NOTES_LIMIT else "fail"
    return CheckResult(status, f"DRAFT_NOTES.md {size}바이트 (한도 {DRAFT_NOTES_LIMIT})", {"bytes": size})


def verify_skeleton(root: Path) -> list[str]:
    """뼈대 디렉토리를 파일 내용·경로로 직접 확인한다 (도구 출력을 믿지 않는다)."""
    problems = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if parts[0] == "feedback" and rel != "feedback/.gitkeep":
            problems.append(f"피드백 파일: {rel}")
        elif parts[0] not in SKELETON_NON_CATEGORY and len(parts) > 1 and rel != f"{parts[0]}/.gitkeep":
            problems.append(f"카테고리에 .gitkeep 외 파일(유형·fixture 의심): {rel}")
        if "jira" in parts[:-1] or "fixtures" in parts[:-1]:
            problems.append(f"jira/fixtures 디렉토리: {rel}")
        if parts[0] not in SKELETON_NON_CATEGORY and (path.name == "type.md" or path.name.endswith(".expect.yaml")):
            problems.append(f"유형·fixture 파일: {rel}")
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SYNTHETIC_RE.search(text):
            problems.append(f"합성 fixture 표시(origin: synthetic): {rel}")
    if (root / "types").exists():
        problems.append("types/ 디렉토리가 있습니다")
    return sorted(set(problems))


def check_skeleton(ctx: Ctx) -> CheckResult:
    out_dir = ctx.tmp / "skeleton"
    code, out = ctx.run("skeleton", [sys.executable, str(ctx.repo / "tools" / "make_db_skeleton.py"), str(out_dir)])
    if code != 0:
        return from_exit(code, "", out)
    if not out_dir.is_dir() or not any(out_dir.rglob("*")):
        return CheckResult("fail", "뼈대 디렉토리가 비어 있습니다")
    problems = verify_skeleton(out_dir)
    if problems:
        return CheckResult("fail", "\n".join(problems[:20]), {"problems": len(problems)})
    count = sum(1 for p in out_dir.rglob("*") if p.is_file())
    return CheckResult("pass", f"뼈대 파일 {count}개를 직접 확인: 유형·Jira·fixture 없음, feedback은 .gitkeep뿐",
                       {"files": count})


def check_offline_eval(ctx: Ctx) -> CheckResult:
    code, out = ctx.run("offline-eval", [sys.executable, str(ctx.repo / "tools" / "offline_eval.py"),
                                         str(ctx.repo / "tests" / "fixtures" / "offline-eval-sample.yaml"),
                                         "--plugin-root", str(ctx.plugin_root()), "--json"])
    if code != 0:
        return from_exit(code, "", out)
    try:
        summary = json.loads(out)["summary"]
    except (ValueError, KeyError, TypeError):
        return CheckResult("error", f"출력을 해석하지 못했습니다\n{tail(out)}")
    if summary.get("errors") != 0:
        return CheckResult("fail", f"offline_eval 오류 {summary.get('errors')}건", summary)
    return CheckResult("pass", f"offline_eval 합성 라벨셋 {summary.get('total')}건, 오류 0", summary)


def check_regress(ctx: Ctx) -> CheckResult:
    spec = importlib.util.spec_from_file_location("tt_bundle_mock_env", ctx.repo / "tests" / "helpers" / "mock_env.py")
    mock_env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mock_env)
    root = ctx.plugin_root()
    gh_state = ctx.tmp / "gh-state"
    gh_state.mkdir(exist_ok=True)
    env = mock_env.env_with_mocks(ctx.env, gh_state_dir=gh_state, plugin_root=root)
    env["TELEPHONY_TRIAGE_HOME"] = str(ctx.tmp / "home")
    code, out = ctx.run("regress", [sys.executable, str(root / "scripts" / "db_regress.py"), "--db",
                                    str(ctx.repo / "tests" / "fixtures" / "issue-db-sample"), "--all"], env=env)
    detail_ok = "db_regress --all 통과"
    try:
        summary = json.loads(out[out.index("{"):]).get("summary", {})
        detail_ok = f"db_regress --all {summary.get('passed')}/{summary.get('total')} 통과"
    except (ValueError, AttributeError):
        pass
    return from_exit(code, detail_ok, out)


def check_evals_prepare(ctx: Ctx) -> CheckResult:
    evals = json.loads((ctx.repo / "tests" / "skill_evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    ids = [str(e["id"]) for e in evals]
    code, out = ctx.run("evals-prepare", [sys.executable, str(ctx.repo / "tests" / "skill_evals" / "run.py"),
                                          "--iteration", str(ctx.tmp / "evals"), "--prepare-only", "--eval", *ids],
                        timeout=1200)
    if code != 0:
        return from_exit(code, "", out)
    prepared = len(re.findall(r"^eval \d+: prepared", out, re.MULTILINE))
    if prepared != len(ids):
        return CheckResult("fail", f"eval {len(ids)}개 중 {prepared}개만 준비됨\n{tail(out)}", {"count": prepared})
    return CheckResult("pass", f"eval {prepared}개 준비 (prepared, not executed — 행동 평가는 실행하지 않음)",
                       {"count": prepared})


def check_pytest(ctx: Ctx) -> CheckResult:
    code, out = ctx.run("pytest", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                        timeout=3600)
    return from_exit(code, tail(out, 1) or "pytest 통과", out)


CHECKS: list[Check] = [
    Check("plugin-json", 10, "auto", check_plugin_json),
    Check("site-paths", 5, "auto", check_site_paths),
    Check("mcp-local", 6, "auto", check_mcp_local),
    Check("boundary", 2, "auto", check_boundary),
    Check("human-search", 2, "manual", None,
          "실제 회사명·서버명·팀명이 없는지 사람이 한 번 검색한다: grep -rniE '<회사명>|<사내 도메인>' ."),
    Check("schemas", 3, "auto", tool_check("schemas", "sync_schemas.py", ["--check"], "sync_schemas --check 통과")),
    Check("contracts", 4, "auto", tool_check("contracts", "gen_contracts.py", ["--check"],
                                             "gen_contracts --check 통과")),
    Check("exec-bits", 1, "auto", tool_check("exec-bits", "fix_exec_bits.py", ["--check"],
                                             "fix_exec_bits --check 통과")),
    Check("site-todos", 8, "auto", check_site_todos),
    Check("todos-seen", 8, "manual", None,
          "python3 tools/list_site_todos.py 결과를 사용자가 직접 보고, 상태 파일에는 개수만 적었는지 확인한다."),
    Check("draft-notes-size", 9, "auto", check_draft_notes_size),
    Check("draft-notes-fresh", 9, "manual", None,
          "DRAFT_NOTES.md의 진행 상태·막힌 것·활성 트랙·실험 결과 표가 최신인지 사람이 확인한다."),
    Check("skeleton", 7, "auto", check_skeleton),
    Check("offline-eval", 1, "auto", check_offline_eval),
    Check("regress", 1, "auto", check_regress),
    Check("evals-prepare", 1, "auto", check_evals_prepare),
    Check("pytest", 1, "auto", check_pytest),
]


# -- 묶음 ----------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def zip_dir_deterministic(src: Path, dest: Path) -> None:
    """디렉토리를 zip으로 묶는다. 항목 정렬, 날짜·권한 고정이라 같은 내용이면 같은 바이트다."""
    src = Path(src)
    files = sorted(p for p in src.rglob("*") if p.is_file())
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(src).as_posix(), ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            mode = 0o755 if os.access(path, os.X_OK) else 0o644
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, path.read_bytes())


def inspect_archive(zip_path: Path, site_patterns: list[str]) -> list[str]:
    """레포 zip에 들어가면 안 되는 항목."""
    bad = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            base = name.rstrip("/")
            if (base.split("/")[-1] == ".local-draft" or base == ".mcp.json"
                    or base == "plugin/site-defaults.yaml" or is_site_path(base, site_patterns)):
                bad.append(name)
    return bad


def build_bundle(repo: Path, label: str, head_sha: str, tmp: Path, skeleton_dir: Path,
                 site_patterns: list[str]) -> tuple[Path | None, str]:
    """임시 디렉토리에 묶음을 만든다. (디렉토리, 실패 사유)."""
    bundle = tmp / "bundle"
    bundle.mkdir()
    repo_zip = bundle / f"telephony-triage-{label}.zip"
    proc = subprocess.run(["git", "-C", str(repo), "archive", "--format=zip", "-o", str(repo_zip), head_sha],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return None, f"git archive 실패: {proc.stderr.strip()}"
    bad = inspect_archive(repo_zip, site_patterns)
    if bad:
        return None, "레포 zip에 들어가면 안 되는 항목: " + ", ".join(bad[:10])
    zip_dir_deterministic(skeleton_dir, bundle / f"issue-db-skeleton-{label}.zip")
    return bundle, ""


def status_clean(repo: Path) -> bool:
    return git(repo, "status", "--porcelain", "--untracked-files=normal").strip() == ""


# -- 실행 ----------------------------------------------------------------------------------


def validate_label(label: str) -> None:
    if not LABEL_RE.fullmatch(label or ""):
        raise UsageError(f"--label은 [A-Za-z0-9._-]+ 이어야 합니다: {label!r}")
    if label.startswith(("-", ".")) or label.endswith((".lock", ".")):
        raise UsageError(f"--label을 git 태그 이름으로 쓸 수 없습니다: {label!r}")
    proc = subprocess.run(["git", "check-ref-format", f"refs/tags/{label}"], capture_output=True)
    if proc.returncode != 0:
        raise UsageError(f"--label을 git 태그 이름으로 쓸 수 없습니다: {label!r}")


def _is_previous_bundle(path: Path) -> bool:
    return path.is_dir() and ((path / "make_bundle-result.json").is_file() or not any(path.iterdir()))


def resolve_out(repo: Path, label: str, out: str | Path | None, force: bool) -> Path:
    path = Path(out) if out else repo.parent / "tt-import-bundles" / label
    path = path.resolve()
    home = Path.home().resolve()
    if path == repo or repo in path.parents:
        raise UsageError(f"--out이 레포 안입니다: {path}")
    if path in repo.parents or path == Path(path.anchor):
        raise UsageError(f"--out이 레포의 상위 디렉토리(또는 루트)입니다: {path}")
    if path == home or path in home.parents:
        raise UsageError(f"--out이 홈 디렉토리(또는 그 상위)입니다: {path}")
    if path.exists() and not path.is_dir():
        raise UsageError(f"--out이 디렉토리가 아닙니다: {path}")
    if path.exists():
        if not force:
            raise UsageError(f"이미 있습니다: {path} (--force로 바꿔 만듭니다)")
        if not _is_previous_bundle(path):
            raise UsageError(f"--force는 빈 디렉토리나 이전 묶음(make_bundle-result.json 있음)만 바꿉니다: {path}")
    return path


def install_bundle(built: Path, out_dir: Path) -> None:
    """새 묶음을 out_dir 옆 임시 이름으로 옮긴 뒤 바꿔 넣는다. 실패하면 옛 묶음을 되돌린다."""
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staged = out_dir.with_name(f".{out_dir.name}.new-{os.getpid()}")
    old = out_dir.with_name(f".{out_dir.name}.old-{os.getpid()}")
    shutil.rmtree(staged, ignore_errors=True)
    try:
        shutil.move(str(built), str(staged))
        if out_dir.exists():
            if not _is_previous_bundle(out_dir):
                raise UsageError(f"--out이 그 사이 바뀌었습니다: {out_dir}")
            os.rename(out_dir, old)
        try:
            os.rename(staged, out_dir)
        except OSError:
            if old.exists():
                os.rename(old, out_dir)
            raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def check_preconditions(repo: Path, label: str) -> str:
    if subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-dir"], capture_output=True).returncode != 0:
        raise UsageError(f"git 레포가 아닙니다: {repo}")
    head = git(repo, "rev-parse", "HEAD", check=False).strip()
    if not head:
        raise UsageError("HEAD 커밋이 없습니다")
    dirty = git(repo, "status", "--porcelain", "--untracked-files=normal").strip()
    if dirty:
        lines = dirty.splitlines()
        raise UsageError(f"작업 트리가 깨끗하지 않습니다 ({len(lines)}건). 커밋하거나 치운 뒤 다시 실행합니다:\n"
                         + "\n".join(lines[:10]))
    tag = git(repo, "rev-parse", "-q", "--verify", f"refs/tags/{label}^{{commit}}", check=False).strip()
    if tag and tag != head:
        raise UsageError(f"태그 {label}이 이미 있고 HEAD({head[:12]})가 아닌 {tag[:12]}를 가리킵니다")
    return head


def _push_remote(repo: Path) -> str:
    """출력할 push 명령의 remote. 하나뿐이면 그 이름, 아니면 사용자가 채울 자리표시."""
    remotes = git(repo, "remote", check=False).split()
    return remotes[0] if len(remotes) == 1 else "<remote>"


def on_remote_main(repo: Path) -> bool:
    """main 브랜치이고 HEAD가 upstream에 들어 있는지 (보고용, 판정하지 않는다)."""
    if git(repo, "branch", "--show-current", check=False).strip() != "main":
        return False
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", "HEAD", "@{u}"],
                          capture_output=True).returncode == 0


def run(repo: Path | str, label: str, out: Path | str | None = None, checks: list[Check] | None = None,
        skip=(), force: bool = False) -> dict:
    """검사를 돌리고 묶음을 만든다. 결과 dict(`exit_code` 포함)를 준다. 사용·환경 오류는 UsageError."""
    checks = CHECKS if checks is None else checks
    repo = Path(repo).resolve()
    skip = set(skip)
    unknown = skip - {c.id for c in checks}
    if unknown:
        raise UsageError(f"--skip에 없는 검사 id: {', '.join(sorted(unknown))}")
    manual_ids = skip & {c.id for c in checks if c.kind == "manual"}
    if manual_ids:
        raise UsageError(f"사람 확인 항목은 건너뛸 수 없습니다: {', '.join(sorted(manual_ids))}")
    validate_label(label)
    out_dir = resolve_out(repo, label, out, force)
    head_sha = check_preconditions(repo, label)
    git_info = {"remote": _push_remote(repo), "on_remote_main": on_remote_main(repo)}

    env = dict(os.environ)
    env[GUARD_ENV] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    tmp = Path(tempfile.mkdtemp(prefix="tt-make-bundle-"))
    results: list[dict] = []
    manual: list[dict] = []
    bundle_info = None
    exit_code = USAGE
    try:
        ctx = Ctx(repo, tmp, env)
        stopped = False
        any_skip = False
        for check in checks:
            row = {"id": check.id, "checklist": check.checklist, "kind": check.kind, "status": "not-run",
                   "detail": "", "data": None, "duration_sec": 0.0, "log": None}
            results.append(row)
            if check.kind == "manual":
                row.update(status="manual", detail=check.how)
                manual.append({"id": check.id, "status": "manual", "how": check.how})
                continue
            if check.id in skip:
                row.update(status="skipped", detail="--skip")
                row["reason"] = "--skip"
                any_skip = True
                continue
            if stopped:
                continue
            ctx.current_log = None
            started = time.monotonic()
            try:
                res = check.fn(ctx)
            except Exception as exc:  # 검사 코드 자체의 오류는 통과로 보지 않는다
                res = CheckResult("error", f"{type(exc).__name__}: {exc}")
            row.update(status=res.status, detail=res.detail, data=res.data, log=ctx.current_log,
                       duration_sec=round(time.monotonic() - started, 2))
            if res.status != "pass":
                stopped = True

        head_now = git(repo, "rev-parse", "HEAD", check=False).strip()
        tree_clean = status_clean(repo) and head_now == head_sha
        if not tree_clean:
            results.append({"id": "tree-clean", "checklist": 1, "kind": "auto", "status": "fail",
                            "detail": "검사 뒤 트리가 더럽거나 HEAD가 바뀌었습니다:\n"
                                      + git(repo, "status", "--porcelain", "--untracked-files=normal").strip()[:600],
                            "data": None, "duration_sec": 0.0, "log": None})
            stopped = True

        statuses = [r["status"] for r in results if r["kind"] == "auto"]
        auto_all_pass = bool(statuses) and all(s == "pass" for s in statuses)
        if not auto_all_pass or any_skip:
            exit_code = FAILED if ('fail' in statuses or any_skip) else USAGE
        else:
            site_patterns = load_site_paths(repo)
            skeleton = ctx.tmp / "skeleton"
            if not skeleton.is_dir():  # skeleton 검사가 만든 뼈대를 묶는다 (다른 도구로 대신 만들지 않는다)
                raise UsageError("skeleton 검사가 만든 뼈대가 없어 묶음을 만들 수 없습니다")
            built, why = build_bundle(repo, label, head_sha, tmp, skeleton, site_patterns)
            if built is None:
                results.append({"id": "bundle", "checklist": 5, "kind": "auto", "status": "fail", "detail": why,
                                "data": None, "duration_sec": 0.0, "log": None})
                exit_code = FAILED
            else:
                files = []
                for zp in sorted(built.glob("*.zip")):
                    files.append({"name": zp.name, "sha256": sha256_file(zp), "bytes": zp.stat().st_size})
                (built / "SHA256SUMS").write_text("".join(f"{f['sha256']}  {f['name']}\n" for f in files),
                                                  encoding="utf-8")
                bundle_info = {"dir": str(out_dir), "files": files}
                exit_code = NEEDS_APPROVAL
                result = _result(label, head_sha, tree_clean, True, results, manual, bundle_info, exit_code, git_info)
                (built / "make_bundle-result.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                shutil.copytree(ctx.logs, built / "logs")
                install_bundle(built, out_dir)
        complete = exit_code == NEEDS_APPROVAL
        return _result(label, head_sha, status_clean(repo), complete, results, manual, bundle_info, exit_code,
                       git_info)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _result(label, head_sha, tree_clean, complete, checks, manual, bundle, exit_code, git_info) -> dict:
    return {"label": label, "head_sha": head_sha, "tree_clean": tree_clean, "complete": complete,
            "checks": checks, "manual": manual, "bundle": bundle, "exit_code": exit_code, **git_info}


def format_text(result: dict) -> str:
    lines = [f"반입 묶음 {result['label']} (HEAD {result['head_sha'][:12]})", ""]
    lines.append(f"{'검사':<18} {'항목':<4} {'종류':<7} {'상태':<9} 시간")
    for c in result["checks"]:
        lines.append(f"{c['id']:<18} {c['checklist']:<4} {c['kind']:<7} {c['status']:<9} {c['duration_sec']}s")
        if c["status"] in ("fail", "error"):
            lines.extend("    " + ln for ln in str(c["detail"]).splitlines())
    lines.append("")
    if result["manual"]:
        lines.append("사람이 확인할 것:")
        lines.extend(f"  - {m['id']}: {m['how']}" for m in result["manual"])
        lines.append("")
    if result["bundle"]:
        b = result["bundle"]
        lines.append(f"묶음: {b['dir']}")
        lines.extend(f"  {f['sha256']}  {f['name']} ({f['bytes']}바이트)" for f in b["files"])
        lines.append("")
        lines.append("사람 확인을 마친 뒤 태그를 직접 만들고 push합니다 (이 도구는 태그를 만들지 않습니다):")
        lines.append(f"  git tag {result['label']} {result['head_sha']} && git push {result['remote']} {result['label']}")
        if not result["on_remote_main"]:
            lines.append("경고: HEAD가 원격 main에 없습니다 — 병합 후 main에서 다시 만드세요.")
    else:
        lines.append("묶음을 만들지 않았습니다 (자동 검사 실패·건너뜀·오류).")
    return "\n".join(lines)


def main(argv: list[str] | None = None, checks: list[Check] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_bundle.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip", action="append", default=[], metavar="ID[,ID]")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--repo", default=str(REPO))
    args = parser.parse_args(argv)

    if os.environ.get(GUARD_ENV):
        print("make_bundle이 자기 자신의 검사 안에서 다시 실행되었습니다 (재귀 방지).", file=sys.stderr)
        return USAGE
    skip = [s for item in args.skip for s in item.split(",") if s]
    try:
        result = run(args.repo, args.label, args.out, checks=checks, skip=skip, force=args.force)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    except Exception as exc:  # 예기치 못한 오류는 트레이스백 대신 종료 2
        print(f"예기치 못한 오류: {type(exc).__name__}: {exc}", file=sys.stderr)
        return USAGE
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
