#!/usr/bin/env python3
"""Phase 9 완료 기준 확인: 스키마 마이그레이션 `db_migrate.py` (11-phases.md Phase 9).

- 예시 마이그레이션(`scripts/migrations/0001_example_jira_tags.py`)이 샘플 이슈 DB를 v2로 올린다
- `migrate/schema-v<N>` 브랜치에서 `migrate --to <N>` 뒤 `config.py check`·pre-commit·validate가 버전 불일치로 막히지 않고 통과한다
- 다른 브랜치 이름에서는 `--to`가 종료 코드 2이고 버전 불일치는 그대로 막힌다
- `db_add apply`는 옛 `schema_version` 계획을 거부하고, `upgrade-plan`으로 올린 계획을 `sync-pr`가 새 스키마에 재적용한다
- 스키마 범위 밖, `generator_version` 불일치(local)는 `migrate/schema-v<N>` 브랜치 말고는 모든 쓰기를 막는다

셸에 붙은 플러그인은 v1이라, 새 스키마(v2)가 필요한 시험은 `common/versions.py`를 고친 임시 플러그인 루트
(`tests/helpers/runner.py:versioned_root`)로 돈다.

`pytest tests/test_db_migrate.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, git, git_db, run, run_json, versioned_root  # noqa: E402
from workspace import PLANS, Workspace  # noqa: E402
from workspace import git as ws_git  # noqa: E402

BRANCH = "migrate/schema-v2"
CONFIG = "issue-db.config.yaml"
SIM_LOG = REPO / "tests/fixtures/issue-db-pending/data/DATA-001-no-setup-data-call/fixtures/DATA-001-03.log"


def v2():
    return versioned_root(schema=2)


def migrate(db: Path, *args, root=None, expect=0) -> dict:
    proc = run("db_migrate.py", ["--db", db, *args], root=root or v2())
    assert proc.returncode == expect, f"db_migrate {args}: 종료 코드 {proc.returncode} (기대 {expect})\n{proc.stderr}"
    return json.loads(proc.stdout)


def check(db: Path, root=None, expect=None) -> dict:
    proc = run("config.py", ["check", "--db", db, "--for", "dry-run"], root=root or v2())
    if expect is not None:
        assert proc.returncode == expect, f"config check: 종료 코드 {proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


def codes(result: dict) -> list[str]:
    return [r["code"] for r in result["reasons"]]


def schema_version(db: Path) -> int:
    return yaml.safe_load((db / CONFIG).read_text(encoding="utf-8"))["schema_version"]


def migrate_branch_db(name: str = BRANCH, src: Path = SAMPLE) -> Path:
    db = git_db(src)
    git(db, "switch", "-q", "-c", name)
    return db


def plan_v1() -> dict:
    return json.loads((PLANS / "p7-analyze-new-cause.plan.json").read_text(encoding="utf-8"))


# -- 예시 마이그레이션 ------------------------------------------------------------------------


def test_example_migration_upgrades_sample():
    db = migrate_branch_db()
    out = migrate(db, "--to", "2")
    assert out["mode"] == "migrate" and out["from"] == 1 and out["to"] == 2
    assert [s["file"] for s in out["steps"]] == ["0001_example_jira_tags.py"] and out["steps"][0]["upgrade_plan"]
    assert schema_version(db) == 2
    jira_files = sorted(SAMPLE.glob("*/*/jira/*.yaml"))
    assert jira_files and len(out["changed"]) == len(jira_files) + 2      # Jira 파일 + config + Jira 스키마
    validator = Draft202012Validator(json.loads((db / "schema/jira.schema.json").read_text(encoding="utf-8")))
    for path in jira_files:
        moved = db / path.relative_to(SAMPLE)
        text = moved.read_text(encoding="utf-8")
        assert text.startswith(path.read_text(encoding="utf-8")) and text.endswith("tags: []\n")
        data = yaml.safe_load(text)
        data["date"] = str(data["date"])
        data.pop("occurred_on", None)
        assert not list(validator.iter_errors(data)), path.name
    assert json.loads((db / "schema/jira.schema.json").read_text(encoding="utf-8"))["properties"]["tags"]["type"] == "array"
    assert git(db, "status", "--porcelain").count("\n") == len(out["changed"])


def test_dry_run_writes_nothing_and_ignores_branch():
    db = git_db()                                        # main 브랜치, 그래도 --dry-run은 된다
    before = git(db, "status", "--porcelain")
    out = migrate(db, "--to", "2", "--dry-run")
    assert out["mode"] == "dry-run" and out["branch"] == "main" and out["changed"] and out["next"] == []
    assert git(db, "status", "--porcelain") == before == ""
    assert schema_version(db) == 1


def test_already_current_and_second_run():
    db = migrate_branch_db()
    migrate(db, "--to", "2")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "schema v2")
    again = migrate(db, "--to", "2")
    assert again["steps"] == [] and again["changed"] == [] and "이미 v2" in again["message"]
    assert git(db, "status", "--porcelain") == ""


def test_generator_version_synced_but_not_for_actions_build():
    db = migrate_branch_db()
    out = migrate(db, "--to", "2", root=versioned_root(schema=2, generator=2))
    assert out["generator_version"] == {"from": 1, "to": 2, "synced": True}
    cfg = yaml.safe_load((db / CONFIG).read_text(encoding="utf-8"))
    assert cfg["schema_version"] == 2 and cfg["generator_version"] == 2
    ab = migrate_branch_db()
    edit_cfg = (ab / CONFIG).read_text(encoding="utf-8").replace("ci_mode: local", "ci_mode: actions-build")
    (ab / CONFIG).write_text(edit_cfg, encoding="utf-8", newline="\n")
    git(ab, "commit", "-qam", "ci_mode")
    out = migrate(ab, "--to", "2", root=versioned_root(schema=2, generator=2))
    assert out["generator_version"]["synced"] is False
    assert yaml.safe_load((ab / CONFIG).read_text(encoding="utf-8"))["generator_version"] == 1


# -- 실행 조건 (종료 코드 2) --------------------------------------------------------------------


def test_other_branch_names_exit_2_and_stay_blocked():
    for name in ("feature/x", "migrate/schema-v3", "migrate/ci-actions", "migrate/schema-v2-extra"):
        db = migrate_branch_db(name)
        out = migrate(db, "--to", "2", expect=2)
        assert "migrate/schema-v2" in out["error"]
        assert git(db, "status", "--porcelain") == "" and schema_version(db) == 1
        result = check(db)
        if name == "migrate/schema-v3":                        # config check는 v<숫자> 패턴만 본다 (--to는 정확한 N을 본다)
            assert result["migrate_branch"] and result["writable"]
        else:
            assert not result["writable"] and codes(result) == ["schema-too-old"], name   # 예외는 migrate/schema-v<N>뿐


def test_dirty_tree_and_untracked_exit_2():
    db = migrate_branch_db()
    (db / "stray.txt").write_text("x\n", encoding="utf-8")
    out = migrate(db, "--to", "2", expect=2)
    assert "깨끗하지" in out["error"] and "stray.txt" in out["error"]
    assert schema_version(db) == 1
    (db / "stray.txt").unlink()
    (db / "CONTRIBUTING.md").write_text("수정\n", encoding="utf-8")
    assert "깨끗하지" in migrate(db, "--to", "2", expect=2)["error"]


def test_db_must_be_clone_toplevel():
    db = migrate_branch_db()
    sub = db / "data"
    out = migrate(sub, "--to", "2", expect=2)                  # --db가 issue-db.config.yaml 없는 하위 폴더
    assert "error" in out
    plain = git_db(SAMPLE).parent / "plain"
    shutil.copytree(SAMPLE, plain)                             # git 레포가 아닌 복사본
    out = migrate(plain, "--to", "2", expect=2)
    assert "최상위" in out["error"]
    assert schema_version(plain) == 1


def test_plugin_version_and_missing_chain_exit_2():
    db = migrate_branch_db()
    out = migrate(db, "--to", "2", root=run_root_v1(), expect=2)          # 배포되는 v1 플러그인은 v2 DB를 만들지 않는다
    assert "v1까지만" in out["error"]
    db3 = migrate_branch_db("migrate/schema-v3")
    out = migrate(db3, "--to", "3", root=versioned_root(schema=3), expect=2)   # v2 → v3 마이그레이션이 없다
    assert "v2에서 시작하는 마이그레이션이 없습니다" in out["error"]      # 체인 v1 → v2 → v3 중 두 번째가 없다
    assert schema_version(db3) == 1 and git(db3, "status", "--porcelain") == ""


def run_root_v1():
    return versioned_root()


def test_downgrade_and_broken_migration_leave_tree_untouched():
    db = migrate_branch_db()
    migrate(db, "--to", "2")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "v2")
    out = migrate(db, "--to", "1", expect=2)
    assert "지원하지 않는다" in out["error"]
    broken = migrate_branch_db()
    root = versioned_root(schema=2)
    bad = root / "scripts/migrations/0001_example_jira_tags.py"
    original = bad.read_text(encoding="utf-8")
    bad.write_text(original.replace("def migrate(tree):\n", "def migrate(tree):\n    tree.write('x.txt', 'x')\n    raise RuntimeError('boom')\n", 1),
                   encoding="utf-8", newline="\n")
    try:
        out = migrate(broken, "--to", "2", root=root, expect=2)
    finally:
        bad.write_text(original, encoding="utf-8", newline="\n")
    assert "boom" in out["error"] and "아무것도 바꾸지 않았습니다" in out["error"]
    assert git(broken, "status", "--porcelain") == "" and schema_version(broken) == 1


# -- migrate 브랜치의 통과와 다른 곳의 차단 ------------------------------------------------------


def test_migrate_branch_passes_check_precommit_and_validate():
    ws = Workspace(root=v2())                                  # main은 v1 DB, 플러그인은 v2
    db = ws.clone
    main_check = check(db)
    assert not main_check["writable"] and codes(main_check) == ["schema-too-old"]      # main에서는 막힌다
    ws_git(db, "switch", "-q", "-c", BRANCH)
    before = check(db)                                         # 아직 v1이어도 이 브랜치는 버전을 안 본다
    assert before["migrate_branch"] and before["writable"] and before["reasons"] == []

    out = migrate(db, "--to", "2")
    assert out["to"] == 2
    ws.json("db_build.py", ["--write", "--db", db])
    after = check(db)
    assert after["writable"] and after["versions"]["schema"]["db"] == 2
    ws_git(db, "add", "-A")
    ws_git(db, "commit", "-q", "-m", "schema: v1→v2 migrate", env=ws.hook_env())      # .githooks/pre-commit이 돈다
    base = "origin/main"
    ws.json("db_lint.py", ["--changed", base, "--db", db])
    ws.json("db_regress.py", ["--all", "--db", db])
    ws.json("db_build.py", ["--verify", "--db", db])
    # 다른 브랜치로 옮기면 (이미 v2 DB라) 통과한다: main이 v2가 된 뒤의 정상 상태
    ws_git(db, "switch", "-q", "-c", "feature/after")
    assert check(db)["writable"]


def test_too_new_schema_blocked_except_on_migrate_branch():
    db = migrate_branch_db()
    migrate(db, "--to", "2")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "v2")
    v1 = run_root_v1()
    on_migrate = check(db, root=v1)
    assert on_migrate["writable"] and on_migrate["migrate_branch"]
    git(db, "switch", "-q", "-c", "other")
    other = check(db, root=v1)
    assert not other["writable"] and codes(other) == ["schema-too-new"]


def test_generator_mismatch_blocked_except_on_migrate_branch():
    db = git_db()
    root = versioned_root(generator=2)
    assert codes(check(db, root=root)) == ["generator-mismatch"]
    git(db, "switch", "-q", "-c", BRANCH)
    assert check(db, root=root)["writable"]
    ab = git_db()
    text = (ab / CONFIG).read_text(encoding="utf-8").replace("ci_mode: local", "ci_mode: actions-build")
    (ab / CONFIG).write_text(text, encoding="utf-8", newline="\n")
    git(ab, "commit", "-qam", "ci_mode")
    assert check(ab, root=root)["writable"]                    # actions-build는 생성기 버전을 안 본다


# -- 계획: apply 거부 · upgrade-plan · sync-pr ----------------------------------------------------


def _v2_db() -> Path:
    db = migrate_branch_db()
    migrate(db, "--to", "2")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "v2")
    return db


def test_apply_rejects_old_schema_plan():
    db = _v2_db()
    job = db.parent / "job"
    job.mkdir()
    (job / "plan.json").write_text(json.dumps(plan_v1()), encoding="utf-8")
    proc = run("db_add.py", ["apply", job / "plan.json", "--db", db, "--user", "mock-user1"], root=v2())
    assert proc.returncode == 2 and "upgrade-plan" in proc.stderr + proc.stdout


def test_upgrade_plan_cli():
    db = _v2_db()
    plan = plan_v1()
    path = db.parent / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    out = run_json("db_migrate.py", ["upgrade-plan", path, "--db", db], root=v2())
    assert out["status"] == "upgraded" and out["from"] == 1 and out["to"] == 2 and out["written"] is False
    assert out["plan"]["schema_version"] == 2
    assert {k: v for k, v in out["plan"].items() if k != "schema_version"} == {k: v for k, v in plan.items() if k != "schema_version"}
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1      # --write 없이는 그대로
    out = run_json("db_migrate.py", ["upgrade-plan", path, "--db", db, "--write"], root=v2())
    assert out["written"] and Path(out["backup"]).name == "plan.json.v1.bak"
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
    assert json.loads(Path(out["backup"]).read_text(encoding="utf-8"))["schema_version"] == 1
    again = run_json("db_migrate.py", ["upgrade-plan", path, "--db", db], root=v2())
    assert again["status"] == "current" and again["steps"] == []


def test_upgrade_plan_refuses_without_upgrade_fn_or_newer_plan():
    db = _v2_db()
    path = db.parent / "plan.json"
    path.write_text(json.dumps(plan_v1()), encoding="utf-8")
    newer = plan_v1()
    newer["schema_version"] = 3
    newer_path = db.parent / "newer.json"
    newer_path.write_text(json.dumps(newer), encoding="utf-8")
    proc = run("db_migrate.py", ["upgrade-plan", newer_path, "--db", db], root=v2())
    assert proc.returncode == 2 and "새롭습니다" in proc.stdout

    root = versioned_root(schema=3)
    extra = root / "scripts/migrations/0002_no_plan_upgrade.py"
    extra.write_text("FROM_VERSION = 2\nTO_VERSION = 3\n\ndef migrate(tree):\n    pass\n", encoding="utf-8", newline="\n")
    try:
        db3 = db.parent / "db3"
        shutil.copytree(db, db3)
        (db3 / CONFIG).write_text((db3 / CONFIG).read_text(encoding="utf-8").replace("schema_version: 2", "schema_version: 3"),
                                  encoding="utf-8", newline="\n")
        proc = run("db_migrate.py", ["upgrade-plan", path, "--db", db3], root=root)     # v1 → v3, 0002에 upgrade_plan 없음
        assert proc.returncode == 2 and "upgrade_plan()을 제공하지 않아" in proc.stdout
        assert "analyze/record를 다시" in proc.stdout
    finally:
        extra.unlink()


def test_sync_pr_reapplies_upgraded_plan_on_new_schema():
    ws = Workspace()                                           # v1 플러그인으로 계획 PR을 올린다
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.ship("MOCK-7002", "issue/MOCK-7002")

    other = ws.other_clone()                                   # 메인테이너: 마이그레이션 PR이 main에 들어간다
    ws_git(other, "switch", "-q", "-c", BRANCH)
    migrate(other, "--to", "2")
    run_json("db_build.py", ["--write", "--db", other], root=v2())
    ws_git(other, "add", "-A")
    ws_git(other, "commit", "-q", "-m", "schema: v1→v2 migrate")
    ws_git(other, "push", "-q", "origin", f"{BRANCH}:main")

    ws.root = v2()                                             # 사용자는 새 플러그인으로 sync-pr
    ws.json("config.py", ["sync-scripts-path"])                # 플러그인 업데이트 뒤 setup 2 (git hook이 새 스크립트를 본다)
    found = ws.db_pr("find-plan", "--branch", "issue/MOCK-7002")
    assert found["schema_version"] == 1
    ws.acquire(found["job"])
    ws.db_pr("snapshot", "--job", found["job"])
    snapshot = ws.work / "_snapshot"
    assert schema_version(snapshot) == 2
    ws.stage(found["job"], "issue/MOCK-7002", expect=2)        # 옛 계획은 apply가 거부한다

    plan_path = ws.job_dir(found["job"]) / "plan.json"
    out = ws.json("db_migrate.py", ["upgrade-plan", plan_path, "--db", snapshot, "--write"])
    assert out["status"] == "upgraded" and ws.read_plan(found["job"])["schema_version"] == 2
    stage = ws.stage(found["job"], "issue/MOCK-7002")
    assert stage["apply"]["ids"], stage
    summary = ws.db_pr("summary", ws.wt(found["job"]))
    ws.commit(found["job"])
    ws.db_pr("publish", ws.wt(found["job"]), "--branch", "issue/MOCK-7002", "--lease", found["remote_sha"],
             "--approved", summary["approved_hash"])
    ws.db_pr("discard", ws.wt(found["job"]))
    cfg = yaml.safe_load(ws.remote_file("issue/MOCK-7002", CONFIG))
    assert cfg["schema_version"] == 2
    jira = ws.remote_file("issue/MOCK-7002", "data/DATA-001-no-setup-data-call/jira/MOCK-7002.yaml")
    assert jira and "key: MOCK-7002" in jira


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
