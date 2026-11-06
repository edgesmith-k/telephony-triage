"""+1 판정(이슈 DB `db_pr merge`, 뒤의 모듈 스킬 `skill_pr` 공통, contracts.md §3.2 `db_pr.py` 세부 "+1 판정"). 순수 함수다 — gh를 부르지 않는다.

입력: view = `gh pr view --json author,headRefOid,…` dict, reviews = REST `pulls/<n>/reviews` 목록(`parse_pages` 결과).
작성자 외 1명(사람)이 head 커밋에 Approve했고 변경 요청이 없어야 ok다.
- 대소문자를 무시한다(표시는 그 사람의 마지막 리뷰 철자).
- 작성자 본인 리뷰와 봇 리뷰(REST `user.type` Bot, login `…[bot]`)는 의견에서 뺀다. 봇의 변경 요청도 뺀다(Q19).
  gh `pr view --json reviews`의 리뷰 작성자에는 봇 표시가 없다 — 그래서 리뷰는 REST로 읽는다.
- 리뷰어마다 APPROVED·CHANGES_REQUESTED·DISMISSED 중 마지막 상태만 본다(COMMENTED·PENDING 무시). 목록 순서가 제출 순서다
  (`submitted_at`으로 정렬하지 않는다).
- 변경 요청이 하나라도 남아 있으면 changes-requested. head 커밋 Approve가 있으면 ok. 이전 커밋(빈 commit_id 포함)만이면
  stale-approval. 그 밖(DISMISSED만 남은 사람 포함)은 no-approval. head를 모르면 ok가 될 수 없다.
- `reviewDecision`·BLOCKED는 보지 않는다(부르는 쪽이 판정 뒤에 본다).
"""

from __future__ import annotations

import json

OK, NO_AUTHOR, CHANGES, STALE, NONE = "ok", "no-author", "changes-requested", "stale-approval", "no-approval"
CODES = (OK, NO_AUTHOR, CHANGES, STALE, NONE)
OPINIONS = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}     # COMMENTED·PENDING은 의견이 아니다
SHOW = 3                                                       # 메시지에 보이는 사람 수


def login(who) -> str:
    """리뷰·PR 작성자의 login. dict면 `login`, 문자열이면 그대로(스텁 옛 상태). 그 밖은 빈 글."""
    if isinstance(who, dict):
        who = who.get("login")
    return who.strip() if isinstance(who, str) else ""


def is_bot(who) -> bool:
    """봇인가: REST `type` Bot, GraphQL `__typename` Bot, gh `is_bot`, 또는 login이 `[bot]`으로 끝나거나 `app/`로 시작."""
    if isinstance(who, dict):
        if str(who.get("type") or "").casefold() == "bot" or str(who.get("__typename") or "").casefold() == "bot":
            return True
        if who.get("is_bot") is True:
            return True
    name = login(who).casefold()
    return name.endswith("[bot]") or name.startswith("app/")


def _who(review: dict):
    """리뷰 작성자: REST `user`, 없으면 GraphQL 모양 `author`."""
    who = review.get("user")
    return who if who is not None else review.get("author")


def _oid(review: dict) -> str:
    """리뷰한 커밋: REST `commit_id`, 없으면 GraphQL 모양 `commit.oid`. 소문자, 모르면 빈 글."""
    raw = review.get("commit_id")
    if raw is None:
        commit = review.get("commit")
        raw = commit.get("oid") if isinstance(commit, dict) else None
    return raw.strip().lower() if isinstance(raw, str) else ""


def parse_pages(text) -> list | None:
    """`gh api --paginate` 출력 → 리뷰 목록. 쪽마다 JSON 배열이 이어 나올 수 있어 최상위 값을 차례로 읽어 잇는다.
    배열 아닌 값·깨진 JSON·빈 글이면 None(부르는 쪽이 거부한다)."""
    if not isinstance(text, str):
        return None
    decoder, out, i, seen = json.JSONDecoder(), [], 0, False
    while True:
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text):
            break
        try:
            value, i = decoder.raw_decode(text, i)
        except ValueError:
            return None
        if not isinstance(value, list):
            return None
        out.extend(value)
        seen = True
    return out if seen else None


def judge(view: dict, reviews) -> dict:
    """`{code, head, approvals[{login, commit, at}], changes[{login, at}]}`. code는 `CODES` 중 하나."""
    view = view if isinstance(view, dict) else {}
    head = str(view.get("headRefOid") or "").strip().lower()
    author = login(view.get("author")).casefold()
    res = {"code": NO_AUTHOR, "head": head, "approvals": [], "changes": []}
    if not author:                      # 누구 리뷰를 뺄지 모른다
        return res
    last: dict[str, dict] = {}          # casefold login → 마지막 의견(첫 등장 순서 유지)
    for r in reviews if isinstance(reviews, list) else []:
        if not isinstance(r, dict):
            continue
        who = _who(r)
        name, state = login(who), str(r.get("state") or "").strip().upper()
        if not name or name.casefold() == author or is_bot(who) or state not in OPINIONS:
            continue
        last[name.casefold()] = {"login": name, "state": state, "commit": _oid(r),
                                 "at": r.get("submitted_at") or r.get("submittedAt")}
    res["approvals"] = [{"login": v["login"], "commit": v["commit"], "at": v["at"]}
                        for v in last.values() if v["state"] == "APPROVED"]
    res["changes"] = [{"login": v["login"], "at": v["at"]} for v in last.values() if v["state"] == "CHANGES_REQUESTED"]
    if res["changes"]:
        res["code"] = CHANGES
    elif head and any(a["commit"] == head for a in res["approvals"]):
        res["code"] = OK
    elif res["approvals"]:
        res["code"] = STALE             # 빈 commit_id도 여기 — 안전한 쪽
    else:
        res["code"] = NONE
    return res


def head_approvers(res: dict) -> int:
    """head 커밋에 Approve한 사람 수(trace `approvers`)."""
    head = res.get("head") or ""
    return sum(1 for a in res.get("approvals") or [] if head and a.get("commit") == head)


def _names(items: list, fmt) -> str:
    shown = ", ".join(fmt(x) for x in items[:SHOW])
    return shown + (f" 외 {len(items) - SHOW}명" if len(items) > SHOW else "")


def message(res: dict) -> str | None:
    """거부 사유(링크 없음). ok면 None."""
    code = res.get("code")
    if code == OK:
        return None
    if code == STALE:
        names = _names(res.get("approvals") or [], lambda a: f"{a['login']}@{a['commit'][:7] or '?'}")
        return f"승인이 이전 커밋({names}) — head {(res.get('head') or '')[:7] or '?'}에 다시 Approve"
    if code == CHANGES:
        return f"변경 요청({_names(res.get('changes') or [], lambda c: c['login'])})"
    if code == NO_AUTHOR:
        return "PR 작성자를 알 수 없다(gh author 없음) — GHE에서 PR을 확인한다"
    return "승인 없음 — 작성자 외 1명의 Approve가 필요하다"
