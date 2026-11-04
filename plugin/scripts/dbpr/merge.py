"""+1 병합: 병합 기록(`merge-offer.json`), 리뷰어 요청(`request_review`), 병합(`merge`).

정책(`contracts.md §3.2` `db_pr.py` 세부 `merge`, `06-collaboration.md §6.1`):
- 이슈 DB 변경은 여전히 PR로만 들어간다(main 직접 push 금지 그대로). publish는 PR을 만들고 병합 기록을 남길 뿐 병합하지 않는다.
  확인 화면의 병합 줄은 `SCREEN_LINE`(`HOW`): 작성자 외 1명이 그 커밋을 Approve(+1)한 뒤 사용자가 병합을 요청하면
  `db_pr merge --job <KEY>`로, 아니면 사람이 GHE에서 병합한다. 검증 결과 "승인 필요"(stage `needs-approval`)나 메인테이너
  경로(`MAINTAINER_PATHS`) 변경이 든 PR은 병합 줄이 메인테이너 쪽이고(`how`) `merge`도 거부한다(+1이 누구 것이든 — 메인테이너
  승인은 db_pr가 가릴 수 없다). "승인 필요"는 publish가 병합 기록 `needs_approval`에 남기고(stage 결과는 git으로 다시 볼 수 없다),
  메인테이너 경로는 기록 파일만 믿지 않고 `git diff --name-only origin/<base>...<head>`로 다시 본다.
- 리뷰어는 자동 요청하지 않는다. push 뒤 리뷰어 질문에서 사용자가 고르면 `request_review`가 리뷰어마다
  `gh pr edit <n> --add-reviewer <r>`(cwd 사용자 clone, lock·worktree·fetch 없음)를 부른다. 실패는 경고이고 PR은 그대로다.
- 승인 토큰 = publish가 push한 커밋 SHA(`--approved`, 생략하면 병합 기록의 head). PR head가 그 SHA가 아니면 병합하지 않는다
  (`gh pr merge --match-head-commit`도 같은 SHA). 옛 병합 기록(사내 진행 중 PR)의 `mode`·`reason`은 "승인 필요" 거부
  (`mode: review`이고 reason이 `OLD_NEEDS_APPROVAL`로 시작)를 알아보는 데만 쓰고, 다시 쓸 때 뺀다.
- **+1 관문**(`common/ghreview.py`, contracts.md §3.2 "+1 판정"): 상태·head·base·draft 다음, fetch 앞에서 REST 리뷰 목록을 읽어
  작성자 외 1명(사람)이 head 커밋에 Approve했고 변경 요청이 없을 때만 지나간다. 없으면 기다리지 않고 사유와 PR 링크로 거부한다
  (출력 `review{code, approvals}`, trace `review`·`approvers`). 리뷰를 못 읽으면 판정하지 않고 거부(종료 2).
  병합 조건: PR 검사가 모두 통과(검사가 없으면 이슈 DB `ci_mode: local`일 때만 통과 — 그 밖은 아직 안 온 것으로 본다),
  `mergeStateStatus`가 CLEAN·HAS_HOOKS, fetch한 `origin/<base>`가 PR 커밋의 조상(main이 바뀌면 `sync-pr`).
  검사 대기·병합 가능 상태 확인 중(UNKNOWN 등)이면 `wait`초까지 기다렸다 다시 본다(기본 config `issue_db.merge_wait_seconds`).
  리뷰 필요(`reviewDecision` REVIEW_REQUIRED·CHANGES_REQUESTED)·BLOCKED는 기다리지 않는다(검사가 없는 BLOCKED는 `ci_mode: local`
  — 올 검사가 없다). 끝내 안 되면 PR을 그대로 두고 사유와 재시도 명령(`retry`)을 낸다.
- gh는 사용자 clone을 cwd로 부르되 `--delete-branch`를 쓰지 않는다(gh가 로컬 브랜치를 지우거나 checkout하지 않게 — clone 불변).
  원격 PR 브랜치 삭제는 레포 설정 "Automatically delete head branches"에 맡긴다. 병합 뒤 사용자 clone에는 `fetch`만 한다.
"""

from __future__ import annotations

import re
import subprocess
import time

import yaml

from common import ghpr, masking, userconfig, yamlio
from common.exitcodes import CHECK_FAILED, OK, USAGE

from .lock import JOB_KEY_RE, PLAN, UsageError, _iso, _read_json, _write_json, now, trace_note
from .worktree import Ctx, _gh, _git

MERGE_OFFER = "merge-offer.json"     # publish가 쓴다. 작업 파일(WORK_FILES)이 아니라 discard 뒤에도 남는다(guard가 직접 쓰기를 거부)
OFFER_KEYS = ("pr", "url", "head_sha", "needs_approval", "at")     # 병합 기록 모양(`offer`). `merge` 성공이 merged_sha·merged_at을 더한다
DEFAULT_WAIT = 420      # Bash 도구 foreground 상한 600초 안에 들어가게
MAX_WAIT = 480
POLL = 15
# 병합 줄 — 확인 화면(summary)·publish 결과 `merge.how`·eval 채점기가 같은 값을 쓴다
HOW = "작성자 외 1명이 이 커밋을 Approve(+1)한 뒤 '병합해줘'(db_pr merge) 또는 GHE에서 병합"
SCREEN_LINE = "병합: " + HOW
# 메인테이너 쪽 병합 줄(`how`). `merge`는 메인테이너 경로를 git diff로 다시 보고, "승인 필요"는 병합 기록 `needs_approval`로 거부한다
MAINTAINER_HOW = "메인테이너 경로 변경({path}) — 메인테이너가 Approve(+1)한 뒤 GHE에서 병합"
NEEDS_APPROVAL_HOW = "검증 결과 '승인 필요' — 메인테이너가 Approve(+1)한 뒤 GHE에서 병합"
# 병합 기록이 "승인 필요"면 `merge`는 gh를 부르기 전에 이 사유(+ PR 링크)로 거부한다 — 다시 불러도 같으므로 `retry` 없음
NEEDS_APPROVAL_REFUSE = "검증 결과 '승인 필요' — 메인테이너가 Approve(+1)한 뒤 GHE에서 병합한다(db_pr merge는 하지 않는다)"
OLD_NEEDS_APPROVAL = "검증 결과 '승인 필요'"     # 옛 병합 기록(A1까지) mode: review의 reason 머리. 다른 옛 사유는 +1 뒤 병합한다
NO_PR_NUMBER = "병합 기록에 PR 번호가 없다 — GHE에서 PR을 확인한다"
# 리뷰어 요청(`request_review`): 로그인 또는 <org>/<team>. 실패 경고의 확인 대상은 오너 종류별(팀 → S5·S19, 개인 → S5)
REVIEWER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9._-]+)?$")
TEAM_CHECK = "CODEOWNERS 팀 이름(TODO(SITE:S5))과 reviewers.format(TODO(SITE:S19))을 확인한다"
PERSON_CHECK = "CODEOWNERS 사용자 로그인과 그 사용자의 레포 권한(TODO(SITE:S5))을 확인한다"
# 메인테이너 경로(SITE_INSTALL §9 3번·06-collaboration §6.1 CODEOWNERS "공통"). `/`로 끝나면 폴더 아래 전부
MAINTAINER_PATHS = (".githooks/", "schema/", "parser-rules/", "templates/", ".github/", "docs/", "issue-db.config.yaml",
                    "CONTRIBUTING.md", "GLOSSARY.md", ".gitattributes")
MERGEABLE_STATES = {"CLEAN", "HAS_HOOKS"}
FINAL_STATES = {
    "BEHIND": "main이 PR보다 앞서 있다 — /telephony-triage:sync-pr {branch} 뒤 다시 병합한다",
    "DIRTY": "main과 충돌한다 — /telephony-triage:sync-pr {branch}로 다시 맞춘다",
    "DRAFT": "초안(draft) PR이다",
}
BLOCKED_REVIEW = "GHE 브랜치 보호 조건(필수 리뷰 등)을 만족하지 않는다 — 리뷰어가 GHE에서 머지한다"
BLOCKED_NO_CHECKS = ("GHE 브랜치 보호가 병합을 막는다(필수 리뷰 또는 필수 검사 — ci_mode: local이라 올 검사가 없다)"
                     " — 리뷰어가 GHE에서 머지한다")
REVIEW_BLOCKING = {"REVIEW_REQUIRED", "CHANGES_REQUESTED"}
PASS_CONCLUSIONS = ghpr.PASS_CONCLUSIONS     # 옮긴 이름(ghpr)을 그대로 다시 내보낸다
PASS_STATES = ghpr.PASS_STATES
PENDING_STATES = ghpr.PENDING_STATES
VIEW_FIELDS = ("number,url,state,isDraft,headRefName,headRefOid,baseRefName,mergeStateStatus,statusCheckRollup,mergeCommit,"
               f"reviewDecision,{ghpr.AUTHOR_FIELD}")
# --approved를 생략했는데 병합 기록 head가 계획의 PR head와 다를 때(publish가 PR 고치기 전에 끝남 등)
OFFER_MISMATCH = "병합 기록(merge-offer.json)의 head가 계획의 PR head와 다르다 — publish(sync-pr)를 다시 끝낸 뒤 병합한다"


def wait_seconds(cfg: dict, override: int | None = None) -> int:
    """병합 조건을 기다리는 최대 초: `--wait` > config `issue_db.merge_wait_seconds` > 420. 0~480으로 자른다."""
    raw = override if override is not None else userconfig.get(cfg, "issue_db.merge_wait_seconds")
    try:
        value = int(raw) if raw not in (None, "") else DEFAULT_WAIT
    except (TypeError, ValueError):
        value = DEFAULT_WAIT
    return max(0, min(MAX_WAIT, value))


def maintainer_paths(changed: list[str]) -> list[str]:
    return [f for f in changed if any(f.startswith(p) if p.endswith("/") else f == p for p in MAINTAINER_PATHS)]


def how(stage_result: dict, changed: list[str]) -> str:
    """병합 줄의 방법(확인 화면 `병합: <how>`·publish 결과 `merge.how`). 보통은 `HOW`, 검증 결과 "승인 필요"나 메인테이너 경로
    변경이 든 PR은 메인테이너 쪽(그 PR은 `merge`가 거부한다 — GHE에서 메인테이너)."""
    hit = maintainer_paths(changed)
    if hit:
        return MAINTAINER_HOW.format(path=hit[0])
    if needs_approval(stage_result):
        return NEEDS_APPROVAL_HOW
    return HOW


def needs_approval(stage_result: dict | None) -> bool:
    """stage 결과가 검증 결과 "승인 필요"(`needs-approval`, 종료 3)인가 — 병합 기록 `needs_approval`."""
    return (stage_result or {}).get("result") == "needs-approval"


def recorded_needs_approval(rec: dict) -> bool:
    """병합 기록이 "승인 필요" PR인가: 지금 모양은 `needs_approval`(false가 아니면 — 손상 값도 거부 쪽), 옛 모양(A1까지)은
    `mode: review`이고 reason이 `OLD_NEEDS_APPROVAL`로 시작할 때. 설정 review·카테고리 오너·리뷰어 지정 실패 같은 다른
    옛 사유는 +1 뒤 병합한다."""
    if "needs_approval" in rec:
        return rec.get("needs_approval") is not False
    return rec.get("mode") == "review" and str(rec.get("reason") or "").startswith(OLD_NEEDS_APPROVAL)


def retry_command(job: str, head: str) -> str:
    return f"db_pr merge --job {job} --approved {head}"


def offer(job_dir, number, url, head: str, stage_result: dict | None = None, changed: list[str] = ()) -> dict:
    """publish 성공 뒤 병합 기록 `{pr, url, head_sha, needs_approval, at}`을 `JOB/merge-offer.json`에 쓰고 publish 결과의
    `merge` 블록 `{approved, pr_url, how}`를 돌려준다. 병합은 하지 않는다(+1 뒤 사용자가 요청하면 `merge`).
    `needs_approval`(stage 결과 "승인 필요")이면 `merge`가 거부한다 — sync-pr 재publish가 그때의 stage 결과로 다시 쓴다."""
    _write_json(job_dir / MERGE_OFFER, dict(zip(OFFER_KEYS, (number, url, head, needs_approval(stage_result),
                                                             _iso(now())))))
    return {"approved": head, "pr_url": url, "how": how(stage_result, list(changed))}


def _check_job(job: str) -> None:
    if not JOB_KEY_RE.fullmatch(job or "") or job.startswith((".", "_")):
        raise UsageError(f"작업 키 형식이 아닙니다: {job}")


def _missing_offer(job_dir, what: str) -> UsageError:
    return UsageError(f"병합 기록이 없다({job_dir / MERGE_OFFER}) — db_pr publish로 PR을 만든 작업만 {what}.")


# -- request-review ------------------------------------------------------------------------


def parse_reviewers(arg: str) -> list[str]:
    """`--reviewer` 값 → 리뷰어 목록: 쉼표로 나누고 앞뒤 공백·앞 `@` 하나를 떼고 순서대로 중복을 뺀다.
    빈 칸이나 형식(`REVIEWER_RE`)이 아닌 값이 하나라도 있으면 UsageError(gh를 부르기 전)."""
    out: list[str] = []
    for part in str(arg or "").split(","):
        name = part.strip()
        name = name[1:] if name.startswith("@") else name
        if not REVIEWER_RE.fullmatch(name):
            raise UsageError(f"리뷰어 형식이 아니다: {part.strip()!r} — 로그인 또는 <org>/<team>을 쉼표로 잇는다(예: a,b)")
        if name not in out:
            out.append(name)
    return out


def _gh_soft(ctx: Ctx, args: list[str], cwd):
    """`_gh`의 시간 초과(UsageError)를 그 리뷰어 하나의 실패로 바꾼다(앞에서 요청한 리뷰어는 결과에 남는다)."""
    try:
        return _gh(ctx, args, cwd)
    except UsageError as exc:
        return subprocess.CompletedProcess(args, 124, "", str(exc) or "gh 시간 초과")


def _team_reviewers(ctx: Ctx) -> set[str]:
    """CODEOWNERS 팀 오너(`@<org>/<team>`)를 `reviewers.format`으로 바꾼 값들(형식이 `/`를 없애도 팀으로 안다). 사용자 clone의
    `origin/<base>`에서 읽는다(fetch·checkout 없음). 경고 문구 분류용일 뿐이다: 못 읽으면 빈 집합(`/`로만 판단)."""
    import db_summary

    ref = f"refs/remotes/origin/{ctx.base}"
    try:
        owners = _git(ctx.repo, "show", f"{ref}:.github/CODEOWNERS", check=False)
        conf = _git(ctx.repo, "show", f"{ref}:issue-db.config.yaml", check=False)
        teams = [o for line in (owners.stdout.splitlines() if owners.returncode == 0 else [])
                 if line.strip() and not line.strip().startswith("#") for o in line.split()[1:] if "/" in o]
        db_cfg = yamlio.safe_load(conf.stdout) if conf.returncode == 0 else {}
        return set(db_summary.format_owners(teams, db_cfg if isinstance(db_cfg, dict) else {}))
    except Exception:  # noqa: BLE001
        return set()


def request_review(ctx: Ctx, job: str, reviewer_arg: str) -> tuple[dict, int]:
    """push 뒤 리뷰어 질문에서 고른 리뷰어를 PR에 요청한다(`db_pr request-review`). 리뷰어마다 `gh pr edit <n> --add-reviewer <r>`
    (cwd 사용자 clone). lock·worktree·fetch·trace는 쓰지 않는다. 실패는 `failed`·`warnings`(오너 종류별 확인 대상)이고
    일부·전부 실패해도 종료 0 — PR은 그대로다."""
    _check_job(job)
    reviewers = parse_reviewers(reviewer_arg)
    ctx.require_repo()
    job_dir = ctx.work_dir / job
    try:
        rec = _read_json(job_dir / MERGE_OFFER)
    except ValueError as exc:
        raise UsageError(f"병합 기록을 읽을 수 없다({job_dir}): {exc}") from exc
    if not rec or not rec.get("head_sha"):
        raise _missing_offer(job_dir, "리뷰어를 요청한다")
    number = rec.get("pr")
    if number is None:
        raise UsageError(NO_PR_NUMBER)
    got = ghpr.request_reviewers(ctx, number, reviewers, _gh_soft)
    teams = _team_reviewers(ctx) if got["failed"] else set()
    warnings = [f"리뷰어 지정 실패: {f['reviewer']} — PR #{number}은 그대로다. "
                + (TEAM_CHECK if "/" in f["reviewer"] or f["reviewer"] in teams else PERSON_CHECK) for f in got["failed"]]
    return {"pr": {"number": number, "url": rec.get("url")}, "requested": got["requested"], "failed": got["failed"],
            "warnings": warnings}, OK


rollup_state = ghpr.rollup_state      # test_db_pr가 m.rollup_state로 본다


def _method(ctx: Ctx) -> str:
    """레포가 허용하는 병합 방식(merge > squash > rebase). 확인하지 못하면 merge(GHE 기본)."""
    return ghpr.merge_method(ctx, _gh)


def _view(ctx: Ctx, number) -> tuple[dict | None, str | None]:
    return ghpr.view(ctx, number, VIEW_FIELDS, _gh)


def _ci_mode(ctx: Ctx) -> str:
    """fetch한 `origin/<base>`의 `issue-db.config.yaml` `ci_mode`(키가 없으면 local, 파일을 못 읽으면 unknown — 검사 없음을 통과로 보지 않는다)."""
    proc = _git(ctx.repo, "show", f"refs/remotes/origin/{ctx.base}:issue-db.config.yaml", check=False)
    try:
        doc = yamlio.safe_load(proc.stdout) if proc.returncode == 0 else None
    except yaml.YAMLError:
        doc = None
    return str(doc.get("ci_mode") or "local") if isinstance(doc, dict) else "unknown"


class _Stop(Exception):
    """이번 시도의 결과: `retry`면 기다렸다 다시 볼 수 있는 사유. `brief`는 trace용 사유(링크 없음, 없으면 reason).
    `again`이 거짓이면 다시 불러도 같은 거부라 출력에 재시도 명령(`retry`)을 싣지 않는다."""

    def __init__(self, reason: str, code: int = CHECK_FAILED, retry: bool = False, brief: str | None = None,
                 again: bool = True, **extra):
        super().__init__(reason)
        self.reason, self.code, self.retry, self.brief, self.again, self.extra = reason, code, retry, brief, again, extra


def _attempt(ctx: Ctx, number, head: str, branch: str, seen: dict, url: str | None = None) -> dict:
    """병합 한 번 시도. 병합했거나 이미 병합됐으면 결과 dict, 아니면 `_Stop`. +1 관문을 지나면 판정을 `seen`에 남긴다
    (`review`·`approvers` — 시도마다 다시 판정한다: 기다리는 동안 승인이 취소되면 거부)."""
    seen.clear()
    view, err = _view(ctx, number)
    if view is None:
        raise _Stop(f"PR 상태를 읽지 못했다 (gh): {err}", USAGE)
    state = str(view.get("state") or "").upper()
    if state == "MERGED":
        if view.get("headRefOid") != head:
            raise _Stop("PR이 승인한 커밋과 다른 커밋으로 병합됐다 — GHE에서 PR을 확인한다")
        return {"merged": True, "already": True, "url": view.get("url"),
                "merge_commit": (view.get("mergeCommit") or {}).get("oid")}
    if state != "OPEN":
        raise _Stop(f"PR이 열려 있지 않다({state or '알 수 없음'})")
    if view.get("headRefOid") != head:
        raise _Stop("PR 브랜치가 승인한 커밋 뒤에 바뀌었다 — 바뀐 내용을 확인하고(sync-pr) 다시 확인받는다")
    if view.get("baseRefName") not in (None, ctx.base):
        raise _Stop(f"PR base가 {view.get('baseRefName')}다({ctx.base}가 아니다)")
    if view.get("isDraft"):
        raise _Stop(FINAL_STATES["DRAFT"])
    revs, err = ghpr.reviews(ctx, view, number, _gh)
    if revs is None:        # 리뷰를 못 읽으면 판정하지 않고 거부(PR 상태 읽기 실패와 같은 종료 2)
        raise _Stop(f"PR 리뷰를 읽지 못했다 (gh): {err}", USAGE)
    gate = ghpr.plus_one(view, revs, url, number)      # +1 관문. 기다리지 않는다(검사 대기에만 --wait)
    seen.update(review=gate["review"], approvers=gate["approvers"])
    if gate["reason"] is not None:
        raise _Stop(gate["reason"], brief=gate["brief"])
    fetch = _git(ctx.repo, "fetch", "origin", check=False)    # 사용자 clone은 fetch만(브랜치·파일 불변)
    if fetch.returncode != 0:      # 오래된 origin/<base>로 메인테이너 경로·main 불변을 보지 않는다
        err = masking.mask_brief((fetch.stderr or fetch.stdout or "").strip(), 200)
        raise _Stop(f"fetch 실패(종료 {fetch.returncode}: {err}) — 인증·네트워크를 확인한다", retry=True)
    diff = _git(ctx.repo, "diff", "--name-only", f"refs/remotes/origin/{ctx.base}...{head}", check=False)
    if diff.returncode != 0:
        raise _Stop("PR 변경 파일을 확인하지 못했다(git diff) — fetch 상태를 확인한다")
    hit = maintainer_paths([p for p in diff.stdout.splitlines() if p])
    if hit:
        raise _Stop(f"메인테이너 경로 변경({hit[0]}) — 메인테이너 리뷰 뒤 GHE에서 머지한다")
    checks, names = rollup_state(view.get("statusCheckRollup"))
    ci_mode = _ci_mode(ctx)
    if checks == "none" and ci_mode != "local":
        checks, names = "pending", [f"검사 결과 없음(ci_mode: {ci_mode})"]
    if checks == "fail":
        raise _Stop(f"PR 검사 실패({', '.join(names[:5])}) — 실패 원인을 고친 뒤 sync-pr로 다시 올린다", checks=checks)
    review = str(view.get("reviewDecision") or "").upper()
    if review in REVIEW_BLOCKING:      # 리뷰는 기다려도 오지 않는다 — 검사 대기 전에 멈춘다
        raise _Stop(BLOCKED_REVIEW, checks=checks, review_decision=review)
    if checks == "pending":
        raise _Stop(f"검사 대기({', '.join(names[:5])})", retry=True, checks=checks)
    mss = str(view.get("mergeStateStatus") or "").upper()
    if mss in FINAL_STATES:
        raise _Stop(FINAL_STATES[mss].format(branch=branch), checks=checks, merge_state=mss)
    if mss == "BLOCKED":        # 검사 없음이 여기 오면 ci_mode: local(그 밖은 위에서 검사 대기) — 기다리지 않는다
        raise _Stop(BLOCKED_NO_CHECKS if checks == "none" else BLOCKED_REVIEW, checks=checks, merge_state=mss)
    if mss not in MERGEABLE_STATES:
        raise _Stop(f"GHE 병합 가능 상태 확인 중({mss or '알 수 없음'})", retry=True, checks=checks, merge_state=mss)
    anc = _git(ctx.repo, "merge-base", "--is-ancestor", f"refs/remotes/origin/{ctx.base}", head, check=False).returncode
    if anc == 1:     # strict 검사가 없는 레포도 — 같은 ID가 두 번 들어가지 않게 sync-pr로 다시 맞춘다
        raise _Stop(f"main이 PR을 만든 뒤 바뀌었다 — /telephony-triage:sync-pr {branch}로 다시 맞춘 뒤 병합한다", checks=checks)
    if anc != 0:
        raise _Stop(f"main과 PR 커밋을 비교하지 못했다(git merge-base 종료 {anc}) — fetch 상태를 확인한다", checks=checks)
    method = _method(ctx)
    proc = _gh(ctx, ["pr", "merge", str(number), f"--{method}", "--match-head-commit", head], ctx.repo)
    if proc.returncode != 0:
        raise _Stop(f"gh pr merge 실패: {(proc.stderr or proc.stdout).strip()[:300]}", checks=checks, method=method)
    after, _ = _view(ctx, number)
    _git(ctx.repo, "fetch", "origin", check=False)
    return {"merged": True, "url": (after or view).get("url"),
            "merge_commit": ((after or {}).get("mergeCommit") or {}).get("oid"), "method": method, "checks": checks}


def merge(ctx: Ctx, job: str, approved: str | None = None, wait: int | None = None) -> tuple[dict, int]:
    """`approved`를 생략(None)하면 병합 기록(merge-offer.json)의 head를 쓴다(Q8 — 새 세션의 "병합해줘"는 SHA를 모른다).
    어느 쪽이든 계획의 PR head·실제 PR head와 다르면 거부한다. 병합 기록이 "승인 필요" PR이면(`recorded_needs_approval`)
    gh를 부르기 전에 거부한다(`retry` 없음 — 메인테이너가 GHE에서). 설정 조건은 없다."""
    _check_job(job)
    ctx.require_repo()
    job_dir = ctx.work_dir / job
    try:
        rec = _read_json(job_dir / MERGE_OFFER)
        plan = _read_json(job_dir / PLAN) or {}
    except ValueError as exc:
        raise UsageError(f"병합 기록·계획을 읽을 수 없다({job_dir}): {exc}") from exc
    if not rec or not rec.get("head_sha"):
        raise _missing_offer(job_dir, "병합한다")
    if rec.get("pr") is None:
        raise UsageError(NO_PR_NUMBER)
    number, head = rec.get("pr"), str(rec["head_sha"])
    branch = (plan.get("pr") or {}).get("branch") or "<브랜치>"
    pr = {"number": number, "url": rec.get("url")}
    limit = wait_seconds(ctx.cfg, wait)
    started = time.monotonic()
    seen: dict = {}         # 마지막 시도의 +1 판정(관문을 지난 시도만)

    def refuse(stop: _Stop) -> tuple[dict, int]:
        waited = int(time.monotonic() - started)
        block = seen.get("review")      # 관문 앞 거부는 출력·trace 그대로(review 없음)
        gate = {"review": block["code"], "approvers": seen.get("approvers", 0)} if block else {}
        trace_note(job_dir, "merge", pr=number, merged=False, reason=(stop.brief or stop.reason)[:120], waited=waited,
                   **gate)
        out = {"merged": False, "pr": pr, "reason": stop.reason, "left": "PR은 그대로 둔다", "waited": waited, **stop.extra,
               **({"review": block} if block else {})}
        if stop.code != USAGE and stop.again:
            out["retry"] = retry_command(job, head)
        return out, stop.code

    if recorded_needs_approval(rec):     # +1이 누구 것이든 — 메인테이너 승인은 db_pr가 가릴 수 없다(GHE에서 메인테이너)
        return refuse(_Stop(ghpr.with_link(NEEDS_APPROVAL_REFUSE, rec.get("url"), number), brief=NEEDS_APPROVAL_REFUSE,
                            again=False))

    omitted = approved is None
    if omitted:
        approved = head
    if not re.fullmatch(r"[0-9a-f]{7,64}", approved or "") or not head.startswith(approved) \
            or ((plan.get("pr") or {}).get("head_sha") not in (None, head)):
        return refuse(_Stop(OFFER_MISMATCH if omitted else "승인한 커밋이 아니다(--approved는 publish 결과 merge.approved)"))
    while True:
        try:
            done = _attempt(ctx, number, head, branch, seen, rec.get("url"))
            break
        except _Stop as stop:
            left = limit - (time.monotonic() - started)
            if not stop.retry or left <= 0:
                if stop.retry and limit:
                    stop.reason += f" — {limit}초 기다려도 안 됐다"
                return refuse(stop)
            time.sleep(min(POLL, max(1.0, left)))
    gate = {"review": seen["review"]["code"], "approvers": seen.get("approvers", 0)} if seen.get("review") else {}
    trace_note(job_dir, "merge", pr=number, merged=True, sha=done.get("merge_commit"), method=done.get("method"),
               already=bool(done.get("already")) or None, waited=int(time.monotonic() - started), **gate)
    if not done.get("already"):     # 다시 쓸 때는 지금 모양만(옛 기록의 mode·reason은 뺀다 — 여기 오면 "승인 필요"가 아니다)
        _write_json(job_dir / MERGE_OFFER, {**{k: rec.get(k) for k in OFFER_KEYS}, "needs_approval": False,
                                            "merged_sha": done.get("merge_commit"), "merged_at": _iso(now())})
    result = {"merged": True, "pr": {"number": number, "url": done.pop("url", None) or rec.get("url")},
              **{k: v for k, v in done.items() if k != "merged"}, **({"review": seen["review"]} if seen.get("review") else {})}
    if (job_dir / "wt").exists():
        result["next"] = f"작업 worktree가 남아 있다 — db_pr discard {job_dir / 'wt'}"
    return result, OK
