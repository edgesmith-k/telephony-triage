"""검사 오케스트레이션: 프로필(단계 목록)과 종료 코드 집계 (01-architecture.md §3.1, contracts.md §종료 코드).

세 곳이 같은 검사들을 각자 순서대로 불렀다. 단계 목록과 집계는 여기 한 곳에 두고, 호출자는 자기 선행 조건과
출력 모양만 갖는다.

| 프로필 | 호출자 | 범위 | 2(실행 불가)가 나오면 |
|---|---|---|---|
| `stage` | `db_pr.stage` | worktree (`--changed origin/<base>`, 회귀는 `--all`, 검증은 `--plan`) | 그 단계에서 중단 (`Run.aborted`) |
| `precommit` | `db_precommit.run` | index (`--staged`) | 기록하고 계속 |
| `guard` | `guard.check_commit` | index (`--staged`) | 기록하고 계속 (호출자가 거부 문구로 바꾼다) |

하위 스크립트는 지금처럼 subprocess로 부른다(프로세스 안으로 옮기지 않는다). 이 모듈은 stdlib와
`common.exitcodes`만 가져온다: guard는 `site-defaults.yaml`이 없어도 멈추면 안 되므로(모든 도구 호출에 걸린다)
`site_defaults`·yaml을 import하지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from common.exitcodes import CHECK_FAILED, NEEDS_APPROVAL, OK, USAGE

SCRIPTS = Path(__file__).resolve().parent.parent

MIGRATE_BRANCH_RE = re.compile(r"^migrate/schema-v\d+$")
RULE_FILE_RE = re.compile(r"^(parser-rules/.+\.ya?ml|[^/]+/[^/]+/type\.md|[^/]+/[^/]+/fixtures/.+\.expect\.yaml)$")
GENERATED_FIXED = ("README.md", "STATS.md", "parser-rules/CHANGELOG.md")

# migrate 브랜치에서 생성기 버전 불일치로 build 검증을 건너뛴 단계의 `StepResult.note`
NOTE_MIGRATE_TOLERATED = "migrate-tolerated"
GENERATOR_VERSION_MSG = "생성기 버전"


# -- 공통 도우미 ---------------------------------------------------------------------------


def generated_paths(db_cfg: dict) -> set[str]:
    """생성 파일 경로 (db_build.generate와 같은 목록). `key`가 없는 카테고리는 건너뛴다."""
    paths = set(GENERATED_FIXED)
    for cat in db_cfg.get("categories") or []:
        if isinstance(cat, dict) and cat.get("key"):
            paths.add(f"{cat['key']}/README.md")
    return paths


def cache_paths(files) -> list[str]:
    """staged 파일 중 `.cache/` 아래 (캐시는 커밋하지 않는다)."""
    return [p for p in files if p == ".cache" or p.startswith(".cache/")]


def is_migrate_branch(branch: str) -> bool:
    return bool(MIGRATE_BRANCH_RE.match(branch or ""))


def run_script(name: str, args: list[str], plugin_root: str | None = None,
               env: dict | None = None) -> tuple[int, dict | None, str]:
    """플러그인 스크립트를 부른다. (종료 코드, stdout JSON 또는 None, 가공 전 stderr)."""
    extra = ["--plugin-root", plugin_root] if plugin_root else []
    kwargs = {}
    if env is not None:
        full_env = dict(os.environ)
        full_env.update(env)
        kwargs["env"] = full_env
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args, *extra], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kwargs)
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return proc.returncode, data, proc.stderr


def aggregate(codes) -> int:
    """종료 코드 집계: 1이 하나라도 있으면 1, 없고 2가 있으면 2, 없고 3이 있으면 3, 아니면 0."""
    codes = list(codes)
    if CHECK_FAILED in codes:
        return CHECK_FAILED
    if USAGE in codes:
        return USAGE
    if NEEDS_APPROVAL in codes:
        return NEEDS_APPROVAL
    return OK


# -- 데이터 모양 ---------------------------------------------------------------------------


@dataclass
class Ctx:
    db: Path | str
    scope: str                      # "worktree" (stage) | "staged" (precommit·guard)
    ref: str | None = None          # worktree 범위의 `--changed` 기준 (예: origin/main)
    files: tuple | list = ()        # staged 파일 (cache·generated_staged·규칙 변경 판단)
    branch: str = ""
    ci_mode: str = "local"
    db_cfg: dict = field(default_factory=dict)
    plan: str | Path | None = None  # stage: 작업 계획 경로
    regress_json: str | Path | None = None
    plugin_root: str | None = None


@dataclass
class StepResult:
    name: str
    code: int
    data: dict | None = None        # script 단계: stdout JSON. cache·generated_staged: {"paths": [...]}
    stderr: str = ""                # strip한 stderr
    note: str | None = None
    skipped: str | None = None      # 건너뛴 사유 (`Step.when`)
    script: str | None = None
    args: list | None = None


@dataclass
class Run:
    steps: list
    overall: int
    aborted: StepResult | None = None


@dataclass
class Step:
    name: str
    kind: str                       # "script" | "cache" | "generated_staged"
    script: str | None = None
    args: Callable[[Ctx], list] | None = None
    when: Callable[[Ctx], str | None] | None = None   # 건너뛸 사유를 돌려주면 건너뛴다
    migrate_tolerant: bool = False  # migrate 브랜치에서 "생성기 버전" 2는 통과 (06-collaboration.md §6.4)


@dataclass
class Profile:
    name: str
    steps: Callable[[Ctx], list]
    abort_on_usage: bool = False
    stop_after: tuple = ()          # 이 종류의 단계를 실행한 뒤 멈춘다


# -- 단계 정의 -----------------------------------------------------------------------------


def _db(ctx: Ctx) -> str:
    return str(ctx.db)


def _scope(ctx: Ctx) -> list[str]:
    return ["--staged"] if ctx.scope == "staged" else ["--changed", str(ctx.ref)]


def _script_step(name: str, script: str, build_args: Callable[[Ctx], list]) -> Step:
    return Step(name, "script", script, build_args)


_COMPAT = _script_step("compat", "config.py", lambda c: ["check", "--db", _db(c), "--for", "dry-run"])
_CACHE = Step("cache", "cache")
_LINT = _script_step("lint", "db_lint.py", lambda c: [*_scope(c), "--db", _db(c)])
_MASK = _script_step("mask", "mask_pii.py", lambda c: ["--check", *_scope(c), "--db", _db(c)])
_BUILD_VERIFY = Step("build", "script", "db_build.py", lambda c: ["--verify", "--staged", "--db", _db(c)],
                     migrate_tolerant=True)
_GENERATED_STAGED = Step("build", "generated_staged")


def _no_rule_change(ctx: Ctx) -> str | None:
    return None if any(RULE_FILE_RE.match(p) for p in ctx.files) else "규칙 변경 없음"


def _stage_steps(ctx: Ctx) -> list[Step]:
    if ctx.ci_mode == "actions-build":
        return []   # 생성·검사는 CI가 한다 (13-actions.md)
    return [
        _script_step("build", "db_build.py", lambda c: ["--write", "--db", _db(c)]),
        _LINT,
        _MASK,
        _script_step("ids", "db_add.py", lambda c: ["check-ids", "--db", _db(c)]),
        _script_step("regress", "db_regress.py", lambda c: ["--all", "--db", _db(c)]),
        _script_step("verify", "db_verify.py",
                     lambda c: ["rules", "--plan", str(c.plan), "--db", _db(c), "--regress-json",
                                str(c.regress_json)]),
    ]


def _build_step(ctx: Ctx) -> Step:
    return _GENERATED_STAGED if ctx.ci_mode == "actions-build" else _BUILD_VERIFY


def _precommit_steps(ctx: Ctx) -> list[Step]:
    return [
        _COMPAT,
        _CACHE,
        _LINT,
        _MASK,
        _script_step("regress", "db_regress.py", lambda c: ["--staged", "--db", _db(c)]),
        Step("verify", "script", "db_verify.py", lambda c: ["rules", "--staged", "--db", _db(c)],
             when=_no_rule_change),
        _build_step(ctx),
    ]


def _guard_steps(ctx: Ctx) -> list[Step]:
    # 규칙 3(마스킹) → 규칙 4(캐시, 생성 파일). precommit과 순서가 다르다: deny 문구가 이 순서로 나간다.
    return [_MASK, _CACHE, _build_step(ctx)]


PROFILES: dict[str, Profile] = {
    "stage": Profile("stage", _stage_steps, abort_on_usage=True),
    "precommit": Profile("precommit", _precommit_steps),
    "guard": Profile("guard", _guard_steps, stop_after=("generated_staged",)),
}


# -- 실행 ----------------------------------------------------------------------------------


def _planned(profile: Profile, ctx: Ctx) -> list[Step]:
    steps = []
    for step in profile.steps(ctx):
        steps.append(step)
        if step.kind in profile.stop_after:
            break
    return steps


def plan_steps(profile: Profile, ctx: Ctx) -> list[tuple[str, str | None, list]]:
    """실행하지 않고 돌 단계 목록 `[(이름, 스크립트|None, 인자)]` (건너뛸 단계는 뺀다. cache·generated_staged는
    스크립트가 없어 `(이름, None, [])`)."""
    out = []
    for step in _planned(profile, ctx):
        if step.when is not None and step.when(ctx):
            continue
        if step.kind == "script":
            out.append((step.name, step.script, step.args(ctx)))
        else:
            out.append((step.name, None, []))
    return out


def _run_step(step: Step, ctx: Ctx, runner) -> StepResult:
    if step.when is not None:
        reason = step.when(ctx)
        if reason:
            return StepResult(step.name, OK, skipped=reason)
    if step.kind == "cache":
        hit = cache_paths(ctx.files)
        return StepResult(step.name, CHECK_FAILED if hit else OK, data={"paths": hit})
    if step.kind == "generated_staged":
        hit = sorted(set(ctx.files) & generated_paths(ctx.db_cfg))
        return StepResult(step.name, CHECK_FAILED if hit else OK, data={"paths": hit})
    args = step.args(ctx)
    code, data, err = runner(step.script, args, plugin_root=ctx.plugin_root)
    err = (err or "").strip()
    if (step.migrate_tolerant and code == USAGE and is_migrate_branch(ctx.branch)
            and GENERATOR_VERSION_MSG in err):
        return StepResult(step.name, OK, data, err, note=NOTE_MIGRATE_TOLERATED, script=step.script, args=args)
    return StepResult(step.name, code, data, err, script=step.script, args=args)


def run_checks(profile: Profile, ctx: Ctx, *, runner=run_script, on_step=None) -> Run:
    """프로필의 단계를 순서대로 돈다.

    `abort_on_usage`면 종료 코드 2인 단계에서 멈춘다(`Run.aborted`에 그 단계, 뒤 단계는 부르지 않고 `on_step`도
    부르지 않는다). 아니면 2도 기록하고 계속한다. `on_step(StepResult)`은 중단하지 않은 단계마다 그 직후에 불린다.
    """
    results: list[StepResult] = []
    aborted = None
    for step in _planned(profile, ctx):
        res = _run_step(step, ctx, runner)
        results.append(res)
        if profile.abort_on_usage and res.code == USAGE:
            aborted = res
            break
        if on_step is not None:
            on_step(res)
    return Run(results, aggregate(r.code for r in results), aborted)
