"""PR 공용 조각(이슈 DB `db_pr`, 뒤의 모듈 스킬 `skill_pr`): PR 보기, 리뷰 목록(REST), 검사 요약, 병합 방식, +1 관문 사유.

gh는 부르는 쪽이 `run(target, args, cwd) -> CompletedProcess`로 넘긴다(시간 초과 처리·예외는 부르는 쪽 그대로 —
`dbpr.worktree._gh`는 UsageError). target은 `repo`(gh cwd)·`base`·`host`를 가진 객체다(`dbpr.worktree.Ctx`가 그대로 맞다).
PR 만들기·고치기·lease push는 skill_pr(단계 E)가 생길 때, 리뷰어 요청은 request-review(A2)와 함께 옮긴다.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from common import ghreview

AUTHOR_FIELD = "author"
PR_URL_RE = re.compile(r"^https?://([^/\s]+)/([^/\s]+)/([^/\s]+)/pull/(\d+)/?$")
NO_URL = "PR 주소를 알 수 없다(gh url)"
PASS_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
PASS_STATES = {"SUCCESS"}
PENDING_STATES = {"PENDING", "EXPECTED"}


class Target(Protocol):
    repo: Path
    base: str
    host: str | None


Run = Callable[..., subprocess.CompletedProcess]     # (target, args, cwd)


def view(target: Target, number, fields: str, run: Run) -> tuple[dict | None, str | None]:
    """`gh pr view <n> --json <fields>` → `(dict, None)` 또는 `(None, 사유)`."""
    proc = run(target, ["pr", "view", str(number), "--json", fields], target.repo)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[:300]
    try:
        doc = json.loads(proc.stdout or "{}")
    except ValueError:
        return None, f"JSON 아님: {(proc.stdout or '').strip()[:100]}"
    return (doc if isinstance(doc, dict) else None), (None if isinstance(doc, dict) else "객체 아님")


def reviews(target: Target, pr_view: dict, number, run: Run) -> tuple[list | None, str | None]:
    """REST 리뷰 목록 `(list, None)` 또는 `(None, 사유)`. 엔드포인트는 view의 `url`(`https://<host>/<o>/<r>/pull/<n>`)에서
    만든다 — `{owner}/{repo}` 자리표시자는 gh api와 gh pr의 레포 해석이 달라(포크·원격 여럿) 쓰지 않는다.
    url을 못 풀거나 번호가 다르면 gh를 부르지 않고 `(None, NO_URL)`. 쪽 수 한계 없음(`--paginate`, `--slurp`는 쓰지 않는다)."""
    m = PR_URL_RE.match(str((pr_view or {}).get("url") or "").strip())
    if not m or (number is not None and m.group(4) != str(number)):
        return None, NO_URL
    host, owner, repo, n = m.groups()
    proc = run(target, ["api", "--hostname", host, f"repos/{owner}/{repo}/pulls/{n}/reviews?per_page=100", "--paginate"],
               target.repo)
    if proc.returncode != 0:
        return None, (proc.stderr or proc.stdout).strip()[:300]
    items = ghreview.parse_pages(proc.stdout or "")
    if items is None:
        return None, f"JSON 배열 아님: {(proc.stdout or '').strip()[:100]}"
    return items, None


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


def merge_method(target: Target, run: Run) -> str:
    """레포가 허용하는 병합 방식(merge > squash > rebase). 확인하지 못하면 merge(GHE 기본)."""
    proc = run(target, ["repo", "view", "--json", "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"], target.repo)
    try:
        allowed = json.loads(proc.stdout) if proc.returncode == 0 else {}
    except ValueError:
        allowed = {}
    for key, method in (("mergeCommitAllowed", "merge"), ("squashMergeAllowed", "squash"), ("rebaseMergeAllowed", "rebase")):
        if isinstance(allowed, dict) and allowed.get(key) is True:
            return method
    return "merge"


def with_link(message: str, url: str | None, number=None) -> str:
    """`<메시지>. PR: <url>`(url이 없으면 `PR: #<n>`)."""
    return f"{message}. PR: {url}" if url else f"{message}. PR: #{number if number is not None else '?'}"


def plus_one(pr_view: dict, revs: list, url: str | None = None, number=None) -> dict:
    """+1 관문 한 걸음: `{review: {code, approvals}, approvers, reason, brief}`. ok면 reason·brief는 None,
    거부면 reason은 링크로 끝나고(링크는 view `url` > 인자 `url` > `#<n>`) brief는 링크 없는 사유(trace용)다."""
    res = ghreview.judge(pr_view, revs)
    msg = ghreview.message(res)
    link = (pr_view or {}).get("url") if isinstance(pr_view, dict) else None
    return {"review": {"code": res["code"], "approvals": res["approvals"]}, "approvers": ghreview.head_approvers(res),
            "reason": None if msg is None else with_link(msg, link or url, number), "brief": msg}
