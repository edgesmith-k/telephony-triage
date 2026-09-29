#!/usr/bin/env python3
"""db_verify.py — 규칙·해결책·코드 수정 검증 (05-verification.md §5.12, contracts.md §3.2 `db_verify.py` 세부).

**Phase 7 뼈대**: `rules`는 R4(교차 회귀 = `db_regress --all`)만 실제로 돌리고 R1~R3·R5는 `not-implemented`,
R6은 `skipped`를 낸다. `not-implemented`는 종료 코드에 영향을 주지 않는다. `resolution`·`fix`는 Phase 10에서
구현한다(지금은 종료 코드 2).

    db_verify.py rules (--plan <plan.json> [--draft <dir>] | --changed <ref> | --staged) [--extra <logcat...>]
                       [--db <path>]
    db_verify.py resolution --cause <ID> <logcat...> [--plan <plan.json> --draft <dir>]   (Phase 10)
    db_verify.py fix --cause <ID> <logcat...> [--build <빌드>] [--plan <plan.json> --draft <dir>]   (Phase 10)

- `--staged`: index 내용을 임시 디렉토리로 꺼내 검사한다(unstaged 변경 무시, pre-commit).
- `--plan`만: `--db`에 계획이 이미 적용돼 있다고 보고 검사한다 (db_pr stage, Step 8-4).
- `--plan --draft <dir>`: `<dir>`에 origin/<base> 기준 분리 worktree를 만들고 계획을 적용해 검사한 뒤 지운다
  (Step 7 초안). 세션 lock이 `<dir>` 상위 디렉토리 이름(작업 키)의 것이어야 한다.
- 결과: `{rules: [{id, status, reason, targets, review_required}], ...}`. 상태는 contracts.md §상태 값.
- 종료 코드: `fail`이 있으면 1, `needs-approval`이 있으면 3, 아니면 0. 개발·테스트용으로 환경변수
  `TT_FORCE_VERIFY_EXIT=3`이면 판정 뒤 3을 낸다(실패가 있으면 1).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import dbpath, gitscope, site_defaults, userconfig  # noqa: E402
from common.exitcodes import CHECK_FAILED, NEEDS_APPROVAL, OK, USAGE  # noqa: E402

NOT_YET = "Phase 10에서 구현 (뼈대)"


class UsageError(Exception):
    pass


def _script(name: str, args: list[str], plugin_root: str | None) -> subprocess.CompletedProcess:
    extra = ["--plugin-root", plugin_root] if plugin_root else []
    return subprocess.run([sys.executable, str(SCRIPTS / name), *args, *extra], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def _check_lock(job: str, defaults: dict) -> None:
    work_dir = Path(str(userconfig.get(userconfig.merged(defaults), "work_dir"))).expanduser()
    path = work_dir / "session.lock"
    held = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if not held or held.get("job") != job:
        raise UsageError(f"세션 lock이 작업 {job}의 것이 아닙니다 (보유자: {held and held.get('job')}).")


def make_draft(plan: Path, draft: Path, defaults: dict, plugin_root: str | None) -> Path:
    """`<draft>`에 origin/<base> 기준 분리 worktree를 만들고 계획을 적용한다."""
    _check_lock(draft.parent.name, defaults)
    cfg = userconfig.merged(defaults)
    repo = Path(str(userconfig.get(cfg, "issue_db.path") or "")).expanduser()
    base = userconfig.get(cfg, "issue_db.base_branch") or "main"
    _git(repo, "worktree", "prune")
    if draft.exists():
        _git(repo, "worktree", "remove", "--force", str(draft))
        shutil.rmtree(draft, ignore_errors=True)
    proc = _git(repo, "worktree", "add", "--detach", str(draft), f"origin/{base}")
    if proc.returncode != 0:
        raise UsageError(f"draft worktree를 만들 수 없습니다: {proc.stderr.strip()}")
    applied = _script("db_add.py", ["apply", str(plan), "--db", str(draft)], plugin_root)
    if applied.returncode != 0:
        remove_draft(draft, defaults)
        raise UsageError(f"draft에 계획을 적용할 수 없습니다: {applied.stdout.strip()[:500]} {applied.stderr.strip()}")
    return draft


def remove_draft(draft: Path, defaults: dict) -> None:
    repo = Path(str(userconfig.get(userconfig.merged(defaults), "issue_db.path") or "")).expanduser()
    _git(repo, "worktree", "remove", "--force", str(draft))
    shutil.rmtree(draft, ignore_errors=True)
    _git(repo, "worktree", "prune")


def rules(args, defaults: dict) -> tuple[dict, int]:
    draft = None
    index_dir = None
    if args.draft:
        if not args.plan:
            raise UsageError("--draft는 --plan과 함께 쓴다.")
        draft = make_draft(Path(args.plan), Path(args.draft), defaults, args.plugin_root)
        db = draft
    else:
        try:
            db = dbpath.resolve(args.db)
        except dbpath.DbPathError as exc:
            raise UsageError(str(exc)) from exc
    shown_db = db
    if args.staged:   # index 내용으로 검사한다 (unstaged 변경 무시, pre-commit)
        index_dir = Path(tempfile.mkdtemp(prefix="tt-verify-index-"))
        try:
            db = gitscope.materialize_index(db, index_dir / "db")
        except gitscope.GitError as exc:
            shutil.rmtree(index_dir, ignore_errors=True)
            raise UsageError(str(exc)) from exc
    try:
        if args.regress_json:
            regress = json.loads(Path(args.regress_json).read_text(encoding="utf-8"))
            regress_code = CHECK_FAILED if regress.get("summary", {}).get("failed") else OK
        else:
            proc = _script("db_regress.py", ["--all", "--db", str(db)], args.plugin_root)
            if proc.returncode == USAGE:
                raise UsageError(f"db_regress 실행 불가: {proc.stderr.strip()}")
            regress = json.loads(proc.stdout)
            regress_code = proc.returncode
    finally:
        if draft is not None:
            remove_draft(draft, defaults)
        if index_dir is not None:
            shutil.rmtree(index_dir, ignore_errors=True)
    failed = [r for r in regress.get("results", []) if r.get("status") != "pass"]
    r4 = {"id": "R4", "status": "fail" if regress_code == CHECK_FAILED else "pass",
          "reason": (f"기대값이 깨진 fixture {len(failed)}개" if failed else
                     f"전체 fixture {regress.get('summary', {}).get('total', 0)}개 기대값 유지"),
          "targets": [r["fixture"] for r in failed], "review_required": False,
          "failures": [{"fixture": r["fixture"], "expect": r.get("expect"), "reasons": r.get("reasons"),
                        "allow_cause_drafts": r.get("allow_cause_drafts")} for r in failed]}
    items = [{"id": rid, "status": "not-implemented", "reason": NOT_YET, "targets": [], "review_required": False}
             for rid in ("R1", "R2", "R3")]
    items.append(r4)
    items.append({"id": "R5", "status": "not-implemented", "reason": NOT_YET, "targets": [], "review_required": False})
    items.append({"id": "R6", "status": "skipped", "reason": "해당 없음", "targets": [], "review_required": False})
    scope = ("plan" + (":draft" if draft else "")) if args.plan else ("staged" if args.staged else
                                                                        f"changed:{args.changed}")
    statuses = [i["status"] for i in items]
    code = CHECK_FAILED if "fail" in statuses else NEEDS_APPROVAL if "needs-approval" in statuses else OK
    if os.environ.get("TT_FORCE_VERIFY_EXIT") == "3" and code != CHECK_FAILED:
        code = NEEDS_APPROVAL
    return {"db": str(shown_db), "scope": scope, "skeleton": True, "rules": items,
            "regress": regress.get("summary")}, code


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="db_verify.py", description=__doc__, parents=[common],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("rules", parents=[common])
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--plan")
    scope.add_argument("--changed", metavar="REF")
    scope.add_argument("--staged", action="store_true")
    p.add_argument("--draft")
    p.add_argument("--extra", nargs="*", default=[])
    p.add_argument("--regress-json", help=argparse.SUPPRESS)   # db_pr stage가 이미 돌린 회귀 결과를 넘긴다
    for name in ("resolution", "fix"):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("rest", nargs="*")
        p.add_argument("--cause")
        p.add_argument("--plan")
        p.add_argument("--draft")
        p.add_argument("--build")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    for name in ("db", "plugin_root"):
        if not hasattr(args, name):
            setattr(args, name, None)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    try:
        if args.cmd != "rules":
            raise UsageError(f"db_verify.py {args.cmd}은(는) Phase 10에서 구현한다.")
        result, code = rules(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
