#!/usr/bin/env python3
"""db_pr.py — 이슈 DB 쓰기 오케스트레이션 (contracts.md §3.2 `db_pr.py` 세부, 01-architecture.md §3.1).

    db_pr.py lock status
    db_pr.py lock acquire <작업 키> [--command <이름>] [--take-over]
    db_pr.py lock release <작업 키> [--force]
    db_pr.py snapshot --job <작업 키>
    db_pr.py my-prs                           (읽기 전용: 내 열린 PR과 base 이동 여부, sync 5번)
    db_pr.py cleanup (--dry-run | --yes) [--older-than [<days>]]
    db_pr.py preflight --branch <br> [--search <원인 ID|JIRA-KEY>] [--jira <KEY>]
    db_pr.py stage <plan.json> --wt <dir> --branch <br> [--dry-run] [--verbose | --then-summary]
    db_pr.py summary <wt> [--format json|markdown]
    db_pr.py publish <wt> --branch <br> --lease <sha|new> --approved <hash> [--commit] [--and-discard]
    db_pr.py discard <wt>
    db_pr.py find-plan --branch <br>          (sync-pr 1~4번 보조: 계획 찾기·원격 변경 확인)

작업 디렉토리 `<work_dir>/<작업 키>/`: `plan.json`(계획), `state.json`(`{base_sha, branch, approved_hash,
commit_message, staged_at}`), `included_pending/`, `wt/`(작업 worktree). 구현 파일: `stage.json`(stage 결과,
summary 입력), `regress.json`, `pr.json`(summary가 만든 PR 제목·본문·리뷰어, publish 입력). discard가 지운다.
붙여넣은 스텝 원문 `steps-pasted.txt`는 discard·`lock release <자기 작업 키>`(--force 아님)·cleanup이 지운다.
확인 화면·PR 본문 조립은 `db_summary.py`.
도구 브랜치는 로컬 `tt/<br>`만 만든다. 사용자 clone의 로컬 `<br>`와 워킹 트리는 건드리지 않는다.

세션 lock `<work_dir>/session.lock` = `{job, command, started_at, updated_at}` (사용자별로 한 번에 한 작업)
- 다른 작업 키의 lock이 있으면 종료 코드 2와 보유자 정보. 4시간 넘게 갱신되지 않은 lock은 만료로 보고 가져온다.
- 같은 작업 키: `updated_at`이 10분 이내면 다른 세션이 진행 중일 수 있으므로 종료 코드 2
  (사용자가 확인하면 `--take-over`로 이어받는다). 10분이 넘었으면 그대로 이어받는다.
- `release --force`는 보유자와 상관없이 푼다(사용자가 "그 세션은 끝났다"고 확인한 경우).
- 프로세스 생존 여부로 판단하지 않는다(스크립트는 호출마다 끝난다).

읽기 스냅샷 `snapshot --job <작업 키>`: `git -C <issue_db.path> fetch origin` → lock 확인(그 작업 키,
`updated_at` 갱신) → `<work_dir>/_snapshot`을 `origin/<base>`로 만들거나 옮긴다(detached worktree)
→ 사용자 clone의 현재 브랜치가 `<base>`이고 깨끗할 때만 `pull --ff-only`(아니면 건너뛰고 사유)
→ **사후 lint**(`db_lint --all --db <snapshot>`, 06-collaboration.md §6.3 ⑤): ID 중복·Jira 중복 등을 `post_lint`로
보고만 한다(정리는 메인테이너 수동). **사용자 clone에서 checkout은 하지 않는다.** 스냅샷은 읽기 전용이다.
결과에 `previous_sha`(이전 스냅샷 SHA, 첫 실행·기록 없음 null)·`base_sha_changed`(이전과 달라졌는지, 첫 실행 null)를 싣고,
`<work_dir>/snapshot.json`(`{sha, base, at}`)을 best-effort로 쓴다(실패해도 snapshot은 성공, `snapshot_meta_written: false`).

`my-prs`: 읽기 전용(lock·fetch·쓰기 없음). `gh pr list --author @me --state open`의 PR마다 `git merge-base --is-ancestor
origin/<base> origin/<head>`로 `base_moved`(true/false, 로컬 원격 ref가 없으면 null)를 붙인다. fetch를 하지 않으므로
`base_moved`는 마지막 fetch 기준이다(`note`). 출력 `{base, prs|null, warnings, note}`. gh 실패는 `prs: null`+`warnings`, 종료 0.
config가 없거나 clone이 아니면 2.

`stage` stdout은 기본 요약(통과 단계·apply 세부를 접고 `detail`·`folded`를 붙인다), `--verbose`면 `stage.json`과 같은 전체.
`stage.json`은 항상 전체다. `stage` 종료 코드: 하위 결과 집계(1이 하나라도 있으면 1, 없고 3이 있으면 3). drift면 적용 전에 1.
`stage --then-summary`: stage 종료 0·3이면 같은 프로세스에서 `summary --format markdown`을 이어 부르고 stdout은 그 마크다운만
(`--json`·`--verbose`와 함께 못 쓴다). stage 1·2는 기존 그대로(summary 안 부른다), stage 성공·summary 실패는 종료 2
(stdout은 stage 요약 JSON + `summary_error`).
`publish`는 승인 해시·커밋 부모·커밋 메시지·브랜치를 `state.json`과 대조하고(다르면 1), lease push 뒤
PR을 만들거나(`gh pr create`) 고친다(`gh pr edit`).
`publish --commit`: 아직 커밋이 없으면(HEAD == base_sha) 승인 해시 → hooksPath(`.githooks`) → `git add -A` → guard 프로필 검사
→ `git commit -F <작업 디렉터리의 임시 파일>`(pre-commit 실행)을 한 뒤 위 대조·push로 간다. 이미 커밋이 있으면 건너뛴다(멱등).
`publish --and-discard`: publish 종료 0일 때만 `discard`를 이어 부른다(실패하면 worktree·lock을 남긴다).

`stage`는 계획을 읽을 때 먼저 형식을 검사한다(최상위 키·필수 키, `계획 형식 오류:` 종료 코드 2 — 이전 작업 파일은
그대로 둔다). 하위 스크립트가 Traceback으로 끝나면 사용자에게는 마지막 줄만 "내부 오류"로 보인다(`_err_brief`).
drift가 계산한 `ids_at_base`(계획 당시 기준 임시 ID 할당)는 stage 결과·`state.json`에 싣고, `summary`가 각 ID에
`expected_at_base`로 붙인다(drift를 건너뛴 재stage는 같은 base_sha의 이전 값을 이어받는다).

시각은 환경변수 `TT_NOW`(ISO, 테스트용)로 바꿀 수 있다.

이 파일은 CLI만 둔다. 구현은 `dbpr/`: `lock`(상수·`UsageError`·`Lock`), `worktree`(git·snapshot·`Ctx`·worktree 준비/제거·
discard·cleanup), `publish`(my-prs·preflight·stage·summary·승인 해시·publish·find-plan).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import site_defaults, userconfig, yamlio  # noqa: E402
import db_summary  # noqa: E402,F401 — test_db_summary가 본다
from common.exitcodes import OK, USAGE  # noqa: E402
from dbpr import worktree as _worktree_mod  # noqa: E402
from dbpr.lock import Lock, UsageError  # noqa: E402
from dbpr.publish import (_GUARD_FIX_TAIL, _brief_stage, approved_hash, find_plan, my_prs, preflight,  # noqa: E402,F401
                          publish, stage, summary)
from dbpr.worktree import (Ctx, _drop_pasted_steps, _git, _job_of, _prepare_worktree,  # noqa: E402,F401
                           _remove_worktree, cleanup, discard, snapshot)


# -- main -------------------------------------------------------------------------------


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
    parser = argparse.ArgumentParser(prog="db_pr.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="stage 전체 출력")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lock = sub.add_parser("lock")
    lock_sub = lock.add_subparsers(dest="lock_cmd", required=True)
    lock_sub.add_parser("status")
    p = lock_sub.add_parser("acquire")
    p.add_argument("job", metavar="작업 키")
    p.add_argument("--command", metavar="이름")
    p.add_argument("--take-over", action="store_true")
    p = lock_sub.add_parser("release")
    p.add_argument("job", metavar="작업 키")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("snapshot")
    p.add_argument("--job", metavar="작업 키", required=True)
    sub.add_parser("my-prs")
    p = sub.add_parser("cleanup")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--yes", action="store_true")
    p.add_argument("--older-than", type=int, nargs="?", const=90, default=None, metavar="days")
    p = sub.add_parser("preflight")
    p.add_argument("--branch", metavar="br", required=True)
    p.add_argument("--search", metavar="원인 ID|JIRA-KEY")
    p.add_argument("--jira", metavar="KEY")
    p = sub.add_parser("stage")
    p.add_argument("plan", metavar="plan.json")
    p.add_argument("--wt", metavar="dir", required=True)
    p.add_argument("--branch", metavar="br", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS, help="stdout도 stage.json과 같이 전체 (기본은 통과 항목을 접는다)")
    p.add_argument("--then-summary", action="store_true",
                   help="stage 종료 0·3이면 이어서 summary --format markdown을 부르고 그 마크다운만 출력한다 (--json·--verbose와 못 쓴다)")
    p = sub.add_parser("summary")
    p.add_argument("wt")
    p.add_argument("--format", choices=("json", "markdown"), default="json",
                   help="markdown: write-flow §4 확인 화면을 마크다운으로 (기본 json, --json과 함께 못 쓴다)")
    p = sub.add_parser("publish")
    p.add_argument("wt")
    p.add_argument("--branch", metavar="br", required=True)
    p.add_argument("--lease", metavar="sha|new", required=True, help="원격 브랜치 SHA 또는 new(원격에 없어야 함)")
    p.add_argument("--approved", metavar="hash", required=True)
    p.add_argument("--commit", action="store_true",
                   help="커밋이 없으면 승인 해시·hooksPath·guard 검사를 거쳐 summary의 commit_message로 커밋한 뒤 publish한다 (멱등)")
    p.add_argument("--and-discard", action="store_true", help="publish 종료 0일 때만 이어서 discard한다")
    p = sub.add_parser("discard")
    p.add_argument("wt")
    p = sub.add_parser("find-plan")
    p.add_argument("--branch", required=True)
    _allow_common_anywhere(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    _worktree_mod._PLUGIN_ROOT = args.plugin_root   # publish도 worktree._PLUGIN_ROOT를 읽는다
    cfg = userconfig.merged(defaults)
    lock = Lock(Path(str(userconfig.get(cfg, "work_dir"))).expanduser())
    ctx = Ctx(cfg, lock)
    code = OK
    try:
        if args.cmd == "snapshot":
            result = snapshot(args.job, cfg, lock)
        elif args.cmd == "lock":
            if args.lock_cmd == "status":
                held = lock.describe(lock.read())
                result = {"held": held is not None, "lock": held}
            elif args.lock_cmd == "acquire":
                result = lock.acquire(args.job, args.command, args.take_over)
            else:
                result = lock.release(args.job, args.force)
                if not args.force:      # 자기 작업을 끝낼 때(lock이 이미 없어도)
                    _drop_pasted_steps(ctx, args.job)
        elif args.cmd == "my-prs":
            result = my_prs(ctx)
        elif args.cmd == "cleanup":
            result = cleanup(ctx, args.yes, args.older_than)
        elif args.cmd == "preflight":
            result = preflight(ctx, args.branch, args.search, args.jira)
        elif args.cmd == "stage":
            if args.then_summary and (args.json or getattr(args, "verbose", False)):
                raise UsageError("--then-summary는 --json·--verbose와 함께 쓸 수 없다 (stdout이 마크다운이다).")
            result, code = stage(ctx, Path(args.plan), Path(args.wt), args.branch, args.dry_run)
            if not getattr(args, "verbose", False):
                result = _brief_stage(result, _job_of(Path(args.wt), ctx)[0])
            if args.then_summary and code in (OK, 3):
                try:
                    shown = summary(ctx, Path(args.wt), True)["_markdown"]
                except Exception as exc:    # stage는 성공했다: stage.json·state.json은 남아 있다
                    reason = str(exc) or type(exc).__name__
                    print(f"stage 성공, summary 실패: {reason} — db_pr summary {args.wt} --format markdown만 다시 부른다",
                          file=sys.stderr)
                    result["summary_error"] = reason
                    code = USAGE
                else:
                    print(shown, end="")
                    return code
        elif args.cmd == "summary":
            if args.format == "markdown" and args.json:
                raise UsageError("--format markdown은 --json과 함께 쓸 수 없다.")
            result = summary(ctx, Path(args.wt), args.format == "markdown")
            if args.format == "markdown":
                print(result["_markdown"], end="")
                return code
        elif args.cmd == "publish":
            result, code = publish(ctx, Path(args.wt), args.branch, args.lease, args.approved, args.commit)
            if args.and_discard:
                if code == OK:
                    try:
                        result["discard"] = discard(ctx, Path(args.wt))
                    except Exception as exc:    # PR은 이미 만들어졌다: publish를 다시 하지 않는다
                        result["discard"] = {"discarded": False, "error": str(exc) or type(exc).__name__,
                                             "next": f"PR은 만들어졌다. publish를 다시 하지 말고 db_pr discard {args.wt}만 다시 한다"}
                        code = USAGE
                elif result.get("published"):   # push는 됐고 PR 생성만 실패(gh_error)
                    result["discard"] = {"discarded": False, "skipped": "PR 생성 실패 — worktree·lock 보존",
                                         "next": f"push는 됐다. PR을 수동 처리하거나 publish 재시도를 사용자와 정한 뒤 db_pr discard {args.wt}"}
                else:
                    result["discard"] = {"discarded": False, "skipped": "publish 실패 — worktree·lock 보존"}
        elif args.cmd == "discard":
            result = discard(ctx, Path(args.wt))
        else:
            result = find_plan(ctx, args.branch)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        if exc.detail is not None:
            print(json.dumps(exc.detail, ensure_ascii=False, indent=1))
        return USAGE
    except yamlio.YamlFileError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
