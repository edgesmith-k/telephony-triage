"""PR 바로 병합(본인 병합): 병합 자격(`eligibility`), publish가 남기는 병합 기록(`merge-offer.json`), 병합(`merge`).

정책(`contracts.md §3.2` `db_pr.py` 세부 `merge`, `06-collaboration.md §6.1`):
- 이슈 DB 변경은 여전히 PR로만 들어간다(main 직접 push 금지 그대로). push 전 확인 화면에서 사용자가 **"push하고 바로 병합"**을
  고르면 `publish … --and-merge` 한 명령(권한 확인 한 번)이 push·PR 뒤 같은 사용자 권한으로 병합한다. 바로 안 되면
  `db_pr merge --job <KEY> --approved <sha>`로 다시 한다. 기본값은 config `issue_db.merge`(사용자 config > site-defaults >
  내장 `self`). `review`면 확인 화면에 병합 선택지를 내지 않는다(리뷰어가 GHE에서 머지하는 이전 흐름).
- `self`여도 검증 결과 "승인 필요"(stage `needs-approval`)나 메인테이너 경로(`MAINTAINER_PATHS`) 변경이 든 PR은 자격이 없다.
  `merge`는 기록 파일만 믿지 않고 `git diff --name-only origin/<base>...<head>`로 메인테이너 경로를 다시 본다.
- 승인 토큰 = publish가 push한 커밋 SHA. PR head가 그 SHA가 아니면 병합하지 않는다(`gh pr merge --match-head-commit`도 같은 SHA).
  병합 조건: PR 검사가 모두 통과(검사가 없으면 이슈 DB `ci_mode: local`일 때만 통과 — 그 밖은 아직 안 온 것으로 본다),
  `mergeStateStatus`가 CLEAN·HAS_HOOKS, fetch한 `origin/<base>`가 PR 커밋의 조상(main이 바뀌면 `sync-pr`).
  검사 대기·병합 가능 상태 확인 중(UNKNOWN 등)·BLOCKED인데 검사가 대기·없음이면 `wait`초까지 기다렸다 다시 본다
  (기본 config `issue_db.merge_wait_seconds`, 600). 끝내 안 되면 PR을 그대로 두고 사유와 재시도 명령(`retry`)을 낸다.
- gh는 사용자 clone을 cwd로 부르되 `--delete-branch`를 쓰지 않는다(gh가 로컬 브랜치를 지우거나 checkout하지 않게 — clone 불변).
  원격 PR 브랜치 삭제는 레포 설정 "Automatically delete head branches"에 맡긴다. 병합 뒤 사용자 clone에는 `fetch`만 한다.
"""

from __future__ import annotations

import json
import re
import time

import yaml

from common import userconfig
from common.exitcodes import CHECK_FAILED, OK, USAGE

from .lock import JOB_KEY_RE, PLAN, UsageError, _iso, _read_json, _write_json, now, trace_note
from .worktree import Ctx, _gh, _git

MERGE_OFFER = "merge-offer.json"     # publish가 쓴다. 작업 파일(WORK_FILES)이 아니라 discard 뒤에도 남는다(guard가 직접 쓰기를 거부)
MODES = ("self", "review")
DEFAULT_MODE = "self"
DEFAULT_WAIT = 420      # Bash 도구 foreground 상한 600초 안에 publish 시간까지 들어가게
MAX_WAIT = 480
POLL = 15
CHOICES = ["push하고 바로 병합", "push만(리뷰어에게)", "취소"]
REVIEW_REASON = "issue_db.merge: review — 리뷰어가 GHE에서 머지한다"
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
PASS_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
PASS_STATES = {"SUCCESS"}
PENDING_STATES = {"PENDING", "EXPECTED"}
VIEW_FIELDS = "number,url,state,isDraft,headRefName,headRefOid,baseRefName,mergeStateStatus,statusCheckRollup,mergeCommit"


def merge_mode(cfg: dict) -> tuple[str, str | None]:
    """`(self|review, 경고)`. 잘못된 값은 안전한 쪽(`review`)과 경고."""
    raw = userconfig.get(cfg, "issue_db.merge")
    if raw in (None, ""):
        return DEFAULT_MODE, None
    if raw in MODES:
        return str(raw), None
    return "review", f"issue_db.merge 값 {raw!r}는 self | review가 아니다 — review로 본다"


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


def eligibility(cfg: dict, stage_result: dict, changed: list[str]) -> tuple[str, str | None]:
    """`(self|review, 사유)` — 확인 화면(summary)과 publish가 같은 판정을 쓴다."""
    mode, warning = merge_mode(cfg)
    if mode == "review":
        return "review", warning or REVIEW_REASON
    if stage_result.get("result") == "needs-approval":
        return "review", "검증 결과 '승인 필요' — 메인테이너 승인 뒤 GHE에서 머지한다"
    hit = maintainer_paths(changed)
    if hit:
        return "review", f"메인테이너 경로 변경({hit[0]}) — 메인테이너 리뷰 뒤 GHE에서 머지한다"
    return "self", None


def screen_line(mode: str, reason: str | None) -> str:
    """push 전 확인 화면의 병합 줄(`db_summary.render_markdown`)."""
    if mode == "self":
        return ("병합: push 뒤 바로 병합할 수 있다(issue_db.merge: self — 검사·브랜치 보호 조건을 확인한 뒤) — 선택지: "
                + " / ".join(CHOICES))
    return f"병합: 리뷰어가 GHE에서 머지한다 — {reason}"


def retry_command(job: str, head: str) -> str:
    return f"db_pr merge --job {job} --approved {head}"


def offer(ctx: Ctx, job_dir, job: str, stage_result: dict, changed: list[str], number, url, head: str) -> dict:
    """publish 성공 뒤 병합 기록을 `JOB/merge-offer.json`에 쓰고 publish 결과의 `merge` 블록을 돌려준다."""
    mode, reason = eligibility(ctx.cfg, stage_result, changed)
    if number is None:
        mode, reason = "review", "PR 번호를 알 수 없다 — GHE에서 머지한다"
    doc = {"mode": mode, "pr": number, "url": url, "head_sha": head, "reason": reason, "at": _iso(now())}
    _write_json(job_dir / MERGE_OFFER, doc)
    if mode == "self":
        return {"mode": mode, "approved": head, "retry": retry_command(job, head)}
    return {"mode": mode, "reason": reason}


def rollup_state(rollup) -> tuple[str, list[str]]:
    """statusCheckRollup → `(none|pass|pending|fail, 이름 목록)`. CheckRun(status·conclusion)과 StatusContext(state)를 함께 본다."""
    items = rollup if isinstance(rollup, list) else []
    if not items:
        return "none", []
    pending, failed = [], []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or it.get("context") or "?")
        if "status" in it or "conclusion" in it:        # CheckRun
            if str(it.get("status") or "").upper() != "COMPLETED":
                pending.append(name)
            elif str(it.get("conclusion") or "").upper() not in PASS_CONCLUSIONS:
                failed.append(name)
        else:                                           # StatusContext
            state = str(it.get("state") or "").upper()
            if state in PENDING_STATES:
                pending.append(name)
            elif state not in PASS_STATES:
                failed.append(name)
    if failed:
        return "fail", failed
    if pending:
        return "pending", pending
    return "pass", []


def _method(ctx: Ctx) -> str:
    """레포가 허용하는 병합 방식(merge > squash > rebase). 확인하지 못하면 merge(GHE 기본)."""
    proc = _gh(ctx, ["repo", "view", "--json", "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"], ctx.repo)
    try:
        allowed = json.loads(proc.stdout) if proc.returncode == 0 else {}
    except ValueError:
        allowed = {}
    for key, method in (("mergeCommitAllowed", "merge"), ("squashMergeAllowed", "squash"), ("rebaseMergeAllowed", "rebase")):
        if allowed.get(key) is True:
            return method
    return "merge"


def _view(ctx: Ctx, number) -> tuple[dict | None, str | None]:
    proc = _gh(ctx, ["pr", "view", str(number), "--json", VIEW_FIELDS], ctx.repo)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[:300]
    try:
        doc = json.loads(proc.stdout or "{}")
    except ValueError:
        return None, f"JSON 아님: {(proc.stdout or '').strip()[:100]}"
    return (doc if isinstance(doc, dict) else None), (None if isinstance(doc, dict) else "객체 아님")


def _ci_mode(ctx: Ctx) -> str:
    """fetch한 `origin/<base>`의 `issue-db.config.yaml` `ci_mode`(키가 없으면 local, 파일을 못 읽으면 unknown — 검사 없음을 통과로 보지 않는다)."""
    proc = _git(ctx.repo, "show", f"refs/remotes/origin/{ctx.base}:issue-db.config.yaml", check=False)
    try:
        doc = yaml.safe_load(proc.stdout) if proc.returncode == 0 else None
    except yaml.YAMLError:
        doc = None
    return str(doc.get("ci_mode") or "local") if isinstance(doc, dict) else "unknown"


class _Stop(Exception):
    """이번 시도의 결과: `retry`면 기다렸다 다시 볼 수 있는 사유."""

    def __init__(self, reason: str, code: int = CHECK_FAILED, retry: bool = False, **extra):
        super().__init__(reason)
        self.reason, self.code, self.retry, self.extra = reason, code, retry, extra


def _attempt(ctx: Ctx, number, head: str, branch: str) -> dict:
    """병합 한 번 시도. 병합했거나 이미 병합됐으면 결과 dict, 아니면 `_Stop`."""
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
    _git(ctx.repo, "fetch", "origin", check=False)    # 사용자 clone은 fetch만(브랜치·파일 불변)
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
    if checks == "pending":
        raise _Stop(f"검사 대기({', '.join(names[:5])})", retry=True, checks=checks)
    mss = str(view.get("mergeStateStatus") or "").upper()
    if mss in FINAL_STATES:
        raise _Stop(FINAL_STATES[mss].format(branch=branch), checks=checks, merge_state=mss)
    if mss == "BLOCKED":
        if checks == "none":
            raise _Stop("검사 대기(브랜치 보호: 필수 검사가 아직 보고되지 않았거나 리뷰가 필요하다)", retry=True,
                        checks=checks, merge_state=mss)
        raise _Stop(BLOCKED_REVIEW, checks=checks, merge_state=mss)
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


def merge(ctx: Ctx, job: str, approved: str, wait: int | None = None) -> tuple[dict, int]:
    if not JOB_KEY_RE.fullmatch(job or "") or job.startswith((".", "_")):
        raise UsageError(f"작업 키 형식이 아닙니다: {job}")
    ctx.require_repo()
    job_dir = ctx.work_dir / job
    try:
        rec = _read_json(job_dir / MERGE_OFFER)
        plan = _read_json(job_dir / PLAN) or {}
    except ValueError as exc:
        raise UsageError(f"병합 기록·계획을 읽을 수 없다({job_dir}): {exc}") from exc
    if not rec or not rec.get("head_sha"):
        raise UsageError(f"병합 기록이 없다({job_dir / MERGE_OFFER}) — db_pr publish로 PR을 만든 작업만 병합한다.")
    number, head = rec.get("pr"), str(rec["head_sha"])
    branch = (plan.get("pr") or {}).get("branch") or "<브랜치>"
    pr = {"number": number, "url": rec.get("url")}
    limit = wait_seconds(ctx.cfg, wait)
    started = time.monotonic()

    def refuse(stop: _Stop) -> tuple[dict, int]:
        waited = int(time.monotonic() - started)
        trace_note(job_dir, "merge", pr=number, merged=False, reason=stop.reason[:120], waited=waited)
        out = {"merged": False, "pr": pr, "reason": stop.reason, "left": "PR은 그대로 둔다", "waited": waited, **stop.extra}
        if stop.code != USAGE and rec.get("mode") == "self":
            out["retry"] = retry_command(job, head)
        return out, stop.code

    mode, warning = merge_mode(ctx.cfg)
    if rec.get("mode") != "self":
        return refuse(_Stop(rec.get("reason") or "병합 자격이 없다 — 리뷰어가 GHE에서 머지한다"))
    if mode != "self":
        return refuse(_Stop(warning or REVIEW_REASON))
    if not re.fullmatch(r"[0-9a-f]{7,64}", approved or "") or not head.startswith(approved) \
            or ((plan.get("pr") or {}).get("head_sha") not in (None, head)):
        return refuse(_Stop("승인한 커밋이 아니다(--approved는 publish 결과 merge.approved)"))
    while True:
        try:
            done = _attempt(ctx, number, head, branch)
            break
        except _Stop as stop:
            left = limit - (time.monotonic() - started)
            if not stop.retry or left <= 0:
                if stop.retry and limit:
                    stop.reason += f" — {limit}초 기다려도 안 됐다"
                return refuse(stop)
            time.sleep(min(POLL, max(1.0, left)))
    trace_note(job_dir, "merge", pr=number, merged=True, sha=done.get("merge_commit"), method=done.get("method"),
               already=bool(done.get("already")) or None, waited=int(time.monotonic() - started))
    if not done.get("already"):
        rec.update(merged_sha=done.get("merge_commit"), merged_at=_iso(now()))
        _write_json(job_dir / MERGE_OFFER, rec)
    result = {"merged": True, "pr": {"number": number, "url": done.pop("url", None) or rec.get("url")},
              **{k: v for k, v in done.items() if k != "merged"}}
    if (job_dir / "wt").exists():
        result["next"] = f"작업 worktree가 남아 있다 — db_pr discard {job_dir / 'wt'}"
    return result, OK
