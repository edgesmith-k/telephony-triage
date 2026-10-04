#!/usr/bin/env python3
"""common/checks.py: 검사 프로필(stage·precommit·guard)의 단계 목록·중단·집계 (01-architecture.md §3.1).

하위 스크립트는 부르지 않는다. 단계 목록은 `plan_steps`로, 실행 순서·중단·집계는 가짜 runner로 본다.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root  # noqa: E402

sys.path.insert(0, str(plugin_root() / "scripts"))

from common import checks  # noqa: E402
from common.checks import PROFILES, Ctx, aggregate, plan_steps, run_checks  # noqa: E402

DB = "/db"
MODES = ("local", "actions", "actions-build")
RULE_FILE = "parser-rules/data.yaml"
OTHER_FILE = "data/DATA-001-x/jira/PROJ-1.yaml"


def _ctx(profile: str, ci_mode: str = "local", branch: str = "main", files=(OTHER_FILE,)) -> Ctx:
    if profile == "stage":
        return Ctx(db=DB, scope="worktree", ref="origin/main", ci_mode=ci_mode, branch=branch,
                   plan="/job/plan.json", regress_json="/job/regress.json", plugin_root="/plug")
    return Ctx(db=DB, scope="staged", files=tuple(files), ci_mode=ci_mode, branch=branch, plugin_root="/plug")


def _names(profile: str, **kw) -> list[str]:
    return [n for n, _s, _a in plan_steps(PROFILES[profile], _ctx(profile, **kw))]


# -- plan_steps -----------------------------------------------------------------------------


def test_stage_plan_exact_args():
    assert plan_steps(PROFILES["stage"], _ctx("stage")) == [
        ("build", "db_build.py", ["--write", "--db", DB]),
        ("lint", "db_lint.py", ["--changed", "origin/main", "--db", DB]),
        ("mask", "mask_pii.py", ["--check", "--changed", "origin/main", "--db", DB]),
        ("ids", "db_add.py", ["check-ids", "--db", DB]),
        ("regress", "db_regress.py", ["--all", "--db", DB]),
        ("verify", "db_verify.py", ["rules", "--plan", "/job/plan.json", "--db", DB, "--regress-json",
                                    "/job/regress.json"]),
    ]


@pytest.mark.parametrize("mode", ("local", "actions"))
def test_stage_plan_same_for_non_build_modes(mode):
    assert plan_steps(PROFILES["stage"], _ctx("stage", mode)) == plan_steps(PROFILES["stage"], _ctx("stage"))


def test_stage_plan_actions_build_is_empty():
    assert plan_steps(PROFILES["stage"], _ctx("stage", "actions-build")) == []


@pytest.mark.parametrize("branch", ("main", "migrate/schema-v2"))
@pytest.mark.parametrize("mode", ("local", "actions"))
def test_precommit_plan_with_rule_file(mode, branch):
    ctx = _ctx("precommit", mode, branch, files=(RULE_FILE, OTHER_FILE))
    assert plan_steps(PROFILES["precommit"], ctx) == [
        ("compat", "config.py", ["check", "--db", DB, "--for", "dry-run"]),
        ("cache", None, []),
        ("lint", "db_lint.py", ["--staged", "--db", DB]),
        ("mask", "mask_pii.py", ["--check", "--staged", "--db", DB]),
        ("regress", "db_regress.py", ["--staged", "--db", DB]),
        ("verify", "db_verify.py", ["rules", "--staged", "--db", DB]),
        ("build", "db_build.py", ["--verify", "--staged", "--db", DB]),
    ]


def test_precommit_plan_without_rule_file_skips_verify():
    assert _names("precommit") == ["compat", "cache", "lint", "mask", "regress", "build"]
    res = run_checks(PROFILES["precommit"], _ctx("precommit"), runner=lambda *a, **k: (0, None, ""))
    verify = next(r for r in res.steps if r.name == "verify")
    assert verify.skipped == "규칙 변경 없음" and verify.code == 0 and verify.script is None


def test_precommit_plan_actions_build_uses_generated_staged():
    ctx = _ctx("precommit", "actions-build", files=(RULE_FILE,))
    plan = plan_steps(PROFILES["precommit"], ctx)
    assert plan[-1] == ("build", None, [])
    assert [n for n, *_ in plan] == ["compat", "cache", "lint", "mask", "regress", "verify", "build"]


@pytest.mark.parametrize("mode", MODES)
def test_guard_plan_mask_before_cache_and_no_scan_scripts(mode):
    plan = plan_steps(PROFILES["guard"], _ctx("guard", mode))
    assert plan[0] == ("mask", "mask_pii.py", ["--check", "--staged", "--db", DB])
    assert plan[1] == ("cache", None, [])
    if mode == "actions-build":
        assert plan[2:] == [("build", None, [])]
    else:
        assert plan[2:] == [("build", "db_build.py", ["--verify", "--staged", "--db", DB])]


@pytest.mark.parametrize("profile", ("stage", "precommit", "guard"))
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("branch", ("main", "migrate/schema-v3"))
def test_no_profile_emits_wrong_scope(profile, mode, branch):
    for name, script, args in plan_steps(PROFILES[profile], _ctx(profile, mode, branch, files=(RULE_FILE,))):
        if script is None:
            continue   # cache·generated_staged는 스크립트를 부르지 않는다
        if profile == "stage":
            assert "--staged" not in args, name
            assert ("--all" in args) == (name == "regress"), name
        else:
            assert "--all" not in args and "--changed" not in args, name
            if name in ("lint", "mask", "regress", "build", "verify"):
                assert "--staged" in args, name


# -- run_checks -----------------------------------------------------------------------------


class Fake:
    """호출을 기록하고 이름별로 정한 (code, data, stderr)를 돌려주는 runner."""

    def __init__(self, results=None):
        self.results = results or {}
        self.calls: list[tuple[str, list, str | None]] = []

    def __call__(self, name, args, plugin_root=None, env=None):
        self.calls.append((name, list(args), plugin_root))
        return self.results.get(name, (0, {"ok": True}, ""))


STAGE_SCRIPTS = ["db_build.py", "db_lint.py", "mask_pii.py", "db_add.py", "db_regress.py", "db_verify.py"]
STAGE_NAMES = ["build", "lint", "mask", "ids", "regress", "verify"]


@pytest.mark.parametrize("pos", range(6))
def test_stage_aborts_on_usage_at_each_position(pos):
    fake = Fake({STAGE_SCRIPTS[pos]: (2, None, "  boom  ")})
    res = run_checks(PROFILES["stage"], _ctx("stage"), runner=fake)
    assert res.aborted is not None and res.aborted.name == STAGE_NAMES[pos]
    assert res.aborted.stderr == "boom" and res.aborted.script == STAGE_SCRIPTS[pos]
    assert [c[0] for c in fake.calls] == STAGE_SCRIPTS[:pos + 1]
    assert [r.name for r in res.steps] == STAGE_NAMES[:pos + 1]
    assert all(c[2] == "/plug" for c in fake.calls)


def test_stage_overall_aggregation_and_clean_run():
    res = run_checks(PROFILES["stage"], _ctx("stage"), runner=Fake())
    assert res.aborted is None and res.overall == 0 and [r.name for r in res.steps] == STAGE_NAMES
    res = run_checks(PROFILES["stage"], _ctx("stage"),
                     runner=Fake({"db_lint.py": (3, None, ""), "db_regress.py": (1, None, "x")}))
    assert res.overall == 1
    res = run_checks(PROFILES["stage"], _ctx("stage"), runner=Fake({"db_verify.py": (3, None, "")}))
    assert res.overall == 3


def test_stage_actions_build_runs_nothing():
    fake = Fake()
    res = run_checks(PROFILES["stage"], _ctx("stage", "actions-build"), runner=fake)
    assert res.steps == [] and res.overall == 0 and fake.calls == []


def test_stage_on_step_after_regress_before_verify():
    events = []
    fake = Fake()

    def on_step(res):
        events.append(("step", res.name, len(fake.calls)))

    run_checks(PROFILES["stage"], _ctx("stage"), runner=fake, on_step=on_step)
    assert [e[1] for e in events] == STAGE_NAMES
    # regress가 끝난 직후(호출 5번째)에 불리고, verify는 그 뒤에 불린다
    assert ("step", "regress", 5) in events and ("step", "verify", 6) in events


def test_on_step_not_called_for_aborting_step():
    seen = []
    run_checks(PROFILES["stage"], _ctx("stage"), runner=Fake({"db_regress.py": (2, None, "")}),
               on_step=lambda r: seen.append(r.name))
    assert seen == ["build", "lint", "mask", "ids"]


@pytest.mark.parametrize("profile", ("precommit", "guard"))
def test_staged_profiles_record_usage_and_continue(profile):
    fake = Fake({"mask_pii.py": (2, None, "site-defaults 없음"), "db_build.py": (1, {"problems": []}, "")})
    res = run_checks(PROFILES[profile], _ctx(profile), runner=fake)
    assert res.aborted is None
    mask = next(r for r in res.steps if r.name == "mask")
    assert mask.code == 2 and mask.stderr == "site-defaults 없음"
    assert [r.name for r in res.steps][-1] == "build"
    assert res.overall == 1
    only_usage = run_checks(PROFILES[profile], _ctx(profile), runner=Fake({"mask_pii.py": (2, None, "")}))
    assert only_usage.overall == 2


def test_precommit_step_order_and_cache_hit():
    fake = Fake()
    ctx = _ctx("precommit", files=(".cache/a.json", RULE_FILE))
    res = run_checks(PROFILES["precommit"], ctx, runner=fake)
    assert [r.name for r in res.steps] == ["compat", "cache", "lint", "mask", "regress", "verify", "build"]
    cache = res.steps[1]
    assert cache.code == 1 and cache.data == {"paths": [".cache/a.json"]} and cache.script is None
    assert res.overall == 1


def test_guard_step_order_mask_then_cache():
    res = run_checks(PROFILES["guard"], _ctx("guard", files=(".cache/x",)), runner=Fake())
    assert [r.name for r in res.steps] == ["mask", "cache", "build"]
    assert res.steps[1].code == 1


GEN_ERR = "생성기 버전이 다르다"


@pytest.mark.parametrize("profile", ("precommit", "guard"))
def test_build_migrate_tolerance(profile):
    runner = Fake({"db_build.py": (2, None, GEN_ERR)})
    tolerated = run_checks(PROFILES[profile], _ctx(profile, branch="migrate/schema-v2"), runner=runner)
    build = tolerated.steps[-1]
    assert build.name == "build" and build.code == 0 and build.note == checks.NOTE_MIGRATE_TOLERATED
    assert tolerated.overall == 0
    # 다른 브랜치이거나, 다른 2 사유이면 허용하지 않는다
    other = run_checks(PROFILES[profile], _ctx(profile, branch="feature/x"), runner=runner)
    assert other.steps[-1].code == 2 and other.steps[-1].note is None
    unrelated = run_checks(PROFILES[profile], _ctx(profile, branch="migrate/schema-v2"),
                           runner=Fake({"db_build.py": (2, None, "다른 오류")}))
    assert unrelated.steps[-1].code == 2
    failed = run_checks(PROFILES[profile], _ctx(profile, branch="migrate/schema-v2"),
                        runner=Fake({"db_build.py": (1, None, GEN_ERR)}))
    assert failed.steps[-1].code == 1


def test_guard_actions_build_stops_after_generated_staged():
    fake = Fake()
    res = run_checks(PROFILES["guard"], _ctx("guard", "actions-build", files=("README.md", "data/README.md")),
                     runner=fake)
    assert [r.name for r in res.steps] == ["mask", "cache", "build"]
    assert [c[0] for c in fake.calls] == ["mask_pii.py"]
    assert res.steps[-1].code == 1 and res.steps[-1].data == {"paths": ["README.md"]}
    clean = run_checks(PROFILES["guard"], _ctx("guard", "actions-build"), runner=Fake())
    assert clean.steps[-1].code == 0 and clean.steps[-1].data == {"paths": []}


def test_generated_staged_uses_category_keys():
    ctx = _ctx("precommit", "actions-build", files=("data/README.md", "sms/README.md"))
    ctx.db_cfg = {"categories": [{"key": "data"}]}
    res = run_checks(PROFILES["precommit"], ctx, runner=Fake())
    assert res.steps[-1].data == {"paths": ["data/README.md"]}


# -- aggregate · 도우미 ----------------------------------------------------------------------


@pytest.mark.parametrize("codes,expected", [([], 0), ([0], 0), ([0, 3], 3), ([3, 1], 1), ([2, 3], 2), ([1, 2], 1),
                                            ([2], 2), ([0, 0, 3, 3], 3)])
def test_aggregate(codes, expected):
    assert aggregate(codes) == expected


def test_generated_paths_ignores_categories_without_key():
    cfg = {"categories": [{"key": "data"}, {"name": "no-key"}, {"key": ""}, "bad", None]}
    assert checks.generated_paths(cfg) == {"README.md", "STATS.md", "parser-rules/CHANGELOG.md", "data/README.md"}
    assert checks.generated_paths({}) == set(checks.GENERATED_FIXED)


def test_cache_paths_and_migrate_branch():
    assert checks.cache_paths([".cache", ".cache/a", "x/.cache/a", ".cachex"]) == [".cache", ".cache/a"]
    assert checks.is_migrate_branch("migrate/schema-v2")
    assert not checks.is_migrate_branch("migrate/schema-v") and not checks.is_migrate_branch("main")


def test_db_precommit_reexports_generated_paths():
    import db_precommit
    assert db_precommit.generated_paths is checks.generated_paths


def test_checks_imports_only_stdlib_and_exitcodes():
    """guard는 site-defaults가 없어도 멈추면 안 되므로 checks.py는 site_defaults·yaml을 가져오지 않는다."""
    tree = ast.parse(Path(checks.__file__).read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert "yaml" not in mods
    assert not any("site_defaults" in m for m in mods)
    local = {m for m in mods if m.startswith("common")}
    assert local == {"common.exitcodes"}, local
