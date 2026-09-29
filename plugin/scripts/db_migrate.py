#!/usr/bin/env python3
"""db_migrate.py — 이슈 DB 스키마 마이그레이션 (06-collaboration.md §6.4, contracts.md §3.2).

    db_migrate.py --to <N> [--dry-run] [--db <이슈 DB>]
    db_migrate.py upgrade-plan <plan.json> [--db <이슈 DB>] [--write]

`--to <N>`: **`--db`의 워킹 트리를 직접 바꾼다.** 메인테이너가 자기 로컬 브랜치에서 직접 편집하는 흐름이라 계획·worktree·lock을
쓰지 않는다. 실제 실행은 다음을 **모두** 만족할 때만 한다(아니면 종료 코드 2, 아무것도 바꾸지 않는다).
- `--db`가 이슈 DB clone(또는 그 worktree)의 최상위이고 현재 브랜치가 정확히 `migrate/schema-v<N>`
- 워킹 트리가 깨끗함 (untracked 포함, `.gitignore` 대상 제외)
- 이슈 DB 스키마 버전 < N ≤ 플러그인 `SCHEMA_VERSION`, 그 사이 모든 버전의 마이그레이션이 있음
`--dry-run`은 아무것도 쓰지 않고 바뀔 파일만 보여주므로 브랜치·깨끗함은 보지 않는다.

마이그레이션은 `scripts/migrations/NNNN_<설명>.py`다. 모듈 계약:
    FROM_VERSION, TO_VERSION   정수. 체인은 `FROM_VERSION`으로 이어진다.
    DESCRIPTION                한 줄 설명 (선택)
    migrate(tree)              `tree`(MigrationTree)로 읽고 쓴다. 디스크는 모든 단계가 성공한 뒤에 한 번에 바뀐다
    upgrade_plan(plan)         (선택) 옛 스키마의 작업 계획을 새 형식으로 바꿔 돌려준다. `schema_version`은 db_migrate가 올린다
버전 두 개(`schema_version`, 필요하면 `generator_version`)는 db_migrate가 `issue-db.config.yaml`에서 올린다:
`generator_version`은 `ci_mode`가 `actions-build`가 아니면 플러그인 `GENERATOR_VERSION`으로 맞춘다
(`db_build --write`가 두 값이 같아야 돌기 때문이다).

`upgrade-plan`: 계획의 `schema_version`을 이슈 DB(`--db`, sync-pr는 스냅샷)의 버전까지 올린다. 그 사이 마이그레이션 중
`upgrade_plan()`이 없는 것이 있으면 종료 코드 2(계획을 다시 만든다). `--write`면 원래 파일을 `<plan>.v<옛 버전>.bak`으로
남기고 올린 계획으로 덮어쓴다.

`--to` 실행 뒤 순서는 `db_build --write` → `validate` → 커밋 → push다 (`migrate` 커맨드가 안내한다).
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import dbpath, site_defaults, yamlio  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from common.versions import GENERATOR_VERSION, SCHEMA_VERSION  # noqa: E402

MIGRATIONS_DIR = SCRIPTS / "migrations"
MODULE_RE = re.compile(r"^(\d{4})_[A-Za-z0-9_]+\.py$")
CONFIG = "issue-db.config.yaml"
SKIP_DIRS = {".git", ".cache"}


class UsageError(Exception):
    pass


# -- 마이그레이션 모듈 -------------------------------------------------------------------


class Migration:
    def __init__(self, path: Path, module):
        self.path = path
        self.name = path.name
        self.module = module
        self.from_version = module.FROM_VERSION
        self.to_version = module.TO_VERSION
        self.description = getattr(module, "DESCRIPTION", "")

    @property
    def has_upgrade_plan(self) -> bool:
        return callable(getattr(self.module, "upgrade_plan", None))

    def summary(self) -> dict:
        return {"file": self.name, "from": self.from_version, "to": self.to_version,
                "description": self.description, "upgrade_plan": self.has_upgrade_plan}


def load_migrations(directory: Path = MIGRATIONS_DIR) -> dict[int, Migration]:
    """`{FROM_VERSION: Migration}`. 모듈 계약을 어기면 종료 코드 2."""
    found: dict[int, Migration] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.iterdir()):
        if not MODULE_RE.match(path.name):
            continue
        spec = importlib.util.spec_from_file_location(f"tt_migration_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 — 모듈 코드는 무엇이든 던질 수 있다
            raise UsageError(f"마이그레이션 {path.name}을 불러오지 못했습니다: {exc}") from exc
        for attr in ("FROM_VERSION", "TO_VERSION"):
            if not isinstance(getattr(module, attr, None), int):
                raise UsageError(f"마이그레이션 {path.name}에 정수 {attr}가 없습니다.")
        if not callable(getattr(module, "migrate", None)):
            raise UsageError(f"마이그레이션 {path.name}에 migrate(tree)가 없습니다.")
        if module.TO_VERSION <= module.FROM_VERSION:
            raise UsageError(f"마이그레이션 {path.name}의 TO_VERSION이 FROM_VERSION보다 커야 합니다.")
        migration = Migration(path, module)
        if migration.from_version in found:
            raise UsageError(f"FROM_VERSION {migration.from_version}인 마이그레이션이 둘입니다: "
                             f"{found[migration.from_version].name}, {path.name}")
        found[migration.from_version] = migration
    return found


def chain(migrations: dict[int, Migration], start: int, end: int) -> list[Migration]:
    """`start`에서 `end`까지 이어지는 마이그레이션. 끊기면 종료 코드 2."""
    steps: list[Migration] = []
    version = start
    while version < end:
        migration = migrations.get(version)
        if migration is None:
            raise UsageError(f"스키마 v{version} → v{end} 사이에 v{version}에서 시작하는 마이그레이션이 없습니다 "
                             f"(scripts/migrations/). 있는 것: {sorted(m.name for m in migrations.values()) or '없음'}")
        if migration.to_version > end:
            raise UsageError(f"마이그레이션 {migration.name}은 v{migration.to_version}까지 올립니다 (요청 v{end}). "
                             f"중간 버전 v{end}로는 멈출 수 없습니다.")
        steps.append(migration)
        version = migration.to_version
    return steps


# -- 트리 (변경을 모았다가 한 번에 쓴다) -------------------------------------------------------


class MigrationTree:
    """마이그레이션이 보는 이슈 DB. 쓰기는 메모리에 모으고 `commit()`이 디스크에 반영한다."""

    def __init__(self, root: Path):
        self.root = root
        self.pending: dict[str, str | None] = {}   # None = 삭제

    def read(self, rel: str) -> str | None:
        if rel in self.pending:
            return self.pending[rel]
        path = self.root / rel
        return path.read_bytes().decode("utf-8") if path.is_file() else None

    def exists(self, rel: str) -> bool:
        return self.read(rel) is not None

    def write(self, rel: str, text: str) -> None:
        self._check(rel)
        if self.read(rel) != text:
            self.pending[rel] = text

    def delete(self, rel: str) -> None:
        self._check(rel)
        if self.exists(rel):
            self.pending[rel] = None

    def glob(self, pattern: str) -> list[str]:
        """DB 기준 상대 경로(`/` 구분) 목록. 디스크의 파일과 이번 실행에서 새로 쓴 파일(패턴은 뒤에서부터 맞춘다)."""
        hits = {p.relative_to(self.root).as_posix() for p in self.root.glob(pattern)
                if p.is_file() and not SKIP_DIRS & set(p.relative_to(self.root).parts)}
        for rel, text in self.pending.items():
            if text is not None and Path(rel).match(pattern):
                hits.add(rel)
        return sorted(rel for rel in hits if self.exists(rel))

    def changed(self) -> list[str]:
        return sorted(rel for rel, text in self.pending.items()
                      if text != (self._disk(rel)))

    def commit(self) -> list[str]:
        changed = self.changed()
        for rel in changed:
            path = self.root / rel
            text = self.pending[rel]
            if text is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(text.encode("utf-8"))
        return changed

    def _disk(self, rel: str) -> str | None:
        path = self.root / rel
        return path.read_bytes().decode("utf-8") if path.is_file() else None

    def _check(self, rel: str) -> None:
        parts = Path(rel).parts
        if Path(rel).is_absolute() or ".." in parts or SKIP_DIRS & set(parts):
            raise UsageError(f"마이그레이션이 쓸 수 없는 경로입니다: {rel}")


def _set_config_int(text: str, key: str, value: int) -> str:
    pattern = re.compile(rf"^({re.escape(key)}:[ \t]*)\d+", re.M)
    if not pattern.search(text):
        raise UsageError(f"{CONFIG}에 정수 {key}가 없습니다.")
    return pattern.sub(lambda m: f"{m.group(1)}{value}", text, count=1)


# -- git ----------------------------------------------------------------------------------


def _git(db: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(db), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _resolve_db(args, defaults: dict) -> Path:
    try:
        return dbpath.resolve(args.db)
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc


def _db_versions(db: Path) -> tuple[int, dict]:
    config = yamlio.load(db / CONFIG) or {}
    version = config.get("schema_version")
    if not isinstance(version, int):
        raise UsageError(f"{CONFIG}의 schema_version이 정수가 아닙니다: {version!r}")
    return version, config


def _require_migrate_branch(db: Path, target: int) -> str:
    top = _git(db, "rev-parse", "--show-toplevel")
    if top is None or Path(top).resolve() != db.resolve():
        raise UsageError(f"{db}는 이슈 DB clone의 최상위가 아닙니다. --to는 clone(또는 그 worktree)에서만 실행한다.")
    branch = _git(db, "rev-parse", "--abbrev-ref", "HEAD")
    expected = f"migrate/schema-v{target}"
    if branch != expected:
        raise UsageError(f"현재 브랜치가 {branch!r}입니다. --to {target}은 {expected} 브랜치에서만 실행한다: "
                         f"git switch -c {expected} (06-collaboration.md §6.4).")
    dirty = _git(db, "status", "--porcelain")
    if dirty is None:
        raise UsageError("git status를 읽지 못했습니다.")
    if dirty:
        raise UsageError("워킹 트리가 깨끗하지 않습니다. 커밋하거나 정리한 뒤 다시 실행한다:\n" + dirty[:1000])
    return branch


# -- 명령 -----------------------------------------------------------------------------------


def cmd_migrate(args, defaults: dict) -> tuple[dict, int]:
    target = args.to
    db = _resolve_db(args, defaults)
    current, config = _db_versions(db)
    if target > SCHEMA_VERSION:
        raise UsageError(f"이 플러그인은 스키마 v{SCHEMA_VERSION}까지만 지원합니다 (요청 v{target}). "
                         "플러그인을 새 버전으로 업데이트한 뒤 실행한다.")
    if target < current:
        raise UsageError(f"이슈 DB가 이미 v{current}입니다 (요청 v{target}). 되돌리는 마이그레이션은 지원하지 않는다.")
    if not args.dry_run:
        branch = _require_migrate_branch(db, target)
    else:
        branch = _git(db, "rev-parse", "--abbrev-ref", "HEAD")
    steps = chain(load_migrations(), current, target)

    tree = MigrationTree(db)
    for step in steps:
        try:
            step.module.migrate(tree)
        except UsageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UsageError(f"마이그레이션 {step.name} 실패: {type(exc).__name__}: {exc}. 아무것도 바꾸지 않았습니다.") from exc

    generator = {"from": config.get("generator_version"), "to": config.get("generator_version"), "synced": False}
    text = tree.read(CONFIG) or ""
    if steps:
        text = _set_config_int(text, "schema_version", target)
        if config.get("ci_mode", "local") != "actions-build" and config.get("generator_version") != GENERATOR_VERSION:
            text = _set_config_int(text, "generator_version", GENERATOR_VERSION)
            generator.update({"to": GENERATOR_VERSION, "synced": True})
        tree.write(CONFIG, text)
    changed = tree.changed() if args.dry_run else tree.commit()
    result = {
        "mode": "dry-run" if args.dry_run else "migrate", "db": str(db), "branch": branch,
        "from": current, "to": target if steps else current, "steps": [s.summary() for s in steps],
        "generator_version": generator, "changed": changed,
        "next": ([] if args.dry_run or not steps else
                 ["db_build.py --write", "validate", f"git commit (브랜치 {branch})", "git push -u origin HEAD"]),
    }
    if not steps:
        result["message"] = f"이슈 DB가 이미 v{current}입니다. 바꿀 것이 없습니다."
    return result, OK


def upgrade_plan(plan: dict, migrations: dict[int, Migration], target: int) -> tuple[dict, list[dict]]:
    version = plan.get("schema_version")
    if not isinstance(version, int):
        raise UsageError(f"계획의 schema_version이 정수가 아닙니다: {version!r}")
    if version > target:
        raise UsageError(f"계획 schema_version {version}이 이슈 DB v{target}보다 새롭습니다. "
                         "이슈 DB(스냅샷)를 최신으로 받았는지 확인한다.")
    steps = chain(migrations, version, target)
    missing = [s.name for s in steps if not s.has_upgrade_plan]
    if missing:
        raise UsageError(f"마이그레이션 {', '.join(missing)}이 upgrade_plan()을 제공하지 않아 계획을 올릴 수 없습니다. "
                         "analyze/record를 다시 실행해서 계획을 새로 만든다 (06-collaboration.md §6.4).")
    upgraded = copy.deepcopy(plan)
    for step in steps:
        try:
            result = step.module.upgrade_plan(upgraded)
        except Exception as exc:  # noqa: BLE001
            raise UsageError(f"{step.name}의 upgrade_plan() 실패: {type(exc).__name__}: {exc}") from exc
        if not isinstance(result, dict):
            raise UsageError(f"{step.name}의 upgrade_plan()이 계획(dict)을 돌려주지 않았습니다.")
        upgraded = result
        upgraded["schema_version"] = step.to_version
    return upgraded, [s.summary() for s in steps]


def cmd_upgrade_plan(args, defaults: dict) -> tuple[dict, int]:
    db = _resolve_db(args, defaults)
    target, _ = _db_versions(db)
    path = Path(args.plan)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"계획을 읽지 못했습니다: {path}: {exc}") from exc
    if not isinstance(plan, dict):
        raise UsageError(f"계획이 JSON 객체가 아닙니다: {path}")
    old = plan.get("schema_version")
    if old == target:
        return {"status": "current", "from": old, "to": target, "steps": [], "plan": plan, "written": False}, OK
    upgraded, steps = upgrade_plan(plan, load_migrations(), target)
    result = {"status": "upgraded", "from": old, "to": target, "steps": steps, "plan": upgraded, "written": False}
    if args.write:
        backup = path.with_name(f"{path.name}.v{old}.bak")
        shutil.copyfile(path, backup)
        path.write_text(json.dumps(upgraded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result.update(written=True, backup=str(backup))
    return result, OK


# -- CLI ------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="db_migrate.py", description=__doc__, parents=[common],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--to", type=int, metavar="N", help="이슈 DB 워킹 트리를 스키마 v<N>으로 올린다")
    parser.add_argument("--dry-run", action="store_true", help="--to와 함께: 아무것도 쓰지 않고 바뀔 파일만 보인다")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("upgrade-plan", parents=[common])
    p.add_argument("plan")
    p.add_argument("--write", action="store_true", help="올린 계획으로 파일을 덮어쓴다 (원본은 .v<옛 버전>.bak)")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    for name in ("db", "plugin_root"):
        if not hasattr(args, name):
            setattr(args, name, None)
    if args.cmd is None and args.to is None:
        parser.error("--to <N> 또는 upgrade-plan <plan.json>이 필요하다.")
    if args.cmd == "upgrade-plan" and (args.to is not None or args.dry_run):
        parser.error("--to·--dry-run은 upgrade-plan과 함께 쓰지 않는다.")
    if args.cmd is None and args.to is not None and args.to < 1:
        parser.error("--to는 1 이상이다.")
    defaults = site_defaults.load_or_exit(args.plugin_root)
    try:
        result, code = cmd_upgrade_plan(args, defaults) if args.cmd == "upgrade-plan" else cmd_migrate(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=1))
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
