#!/usr/bin/env python3
"""+1 판정(`common/ghreview.py`)과 PR 공용 조각(`common/ghpr.py`) 단위 테스트 (H A1, contracts.md §3.2 `db_pr.py` 세부 "+1 판정").

리뷰 입력은 REST `pulls/<n>/reviews` 모양(`user{login, type}`, `commit_id`, `submitted_at`)이 기본이다. GraphQL 모양
(`author{login}`, `commit{oid}`)은 스텁 옛 상태·뒤의 skill_pr 대비로만 받는다 — 봇 표시가 없어 판정에 쓰지 않는다.
gh를 부르지 않는다(가짜 run).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import ghpr, ghreview  # noqa: E402

HEAD = "abcdef0123456789abcdef0123456789abcdef01"
OLD = "1234567890abcdef1234567890abcdef12345678"
VIEW = {"author": {"login": "mock-user", "is_bot": False}, "headRefOid": HEAD,
        "url": "https://ghe.mock.invalid/mock-org/telephony-issue-db/pull/3"}


def rest(login: str, state: str, commit: str | None = HEAD, kind: str = "User", at: str = "2026-01-01T00:00:00Z") -> dict:
    return {"id": 1, "user": {"login": login, "type": kind}, "state": state, "commit_id": commit, "submitted_at": at}


def gql(login: str, state: str, commit: str | None = HEAD, **who) -> dict:
    return {"author": {"login": login, **who}, "state": state, "commit": {"oid": commit} if commit else None,
            "submittedAt": "2026-01-01T00:00:00Z"}


def code(reviews, view=VIEW) -> str:
    return ghreview.judge(view, reviews)["code"]


# -- judge·message --------------------------------------------------------------------------------


def test_no_approval_when_empty_or_only_comments_and_pending():
    for reviews in ([], [rest("bob", "COMMENTED")], [rest("bob", "PENDING"), rest("carol", "COMMENTED")]):
        res = ghreview.judge(VIEW, reviews)
        assert res["code"] == "no-approval" and res["approvals"] == [] and res["changes"] == [], reviews
        assert ghreview.message(res) == "승인 없음 — 작성자 외 1명의 Approve가 필요하다"


def test_ok_when_other_person_approves_head_commit():
    res = ghreview.judge(VIEW, [rest("bob", "APPROVED", HEAD.upper())])     # 대소문자 다른 oid
    assert res["code"] == "ok" and ghreview.message(res) is None
    assert res["approvals"] == [{"login": "bob", "commit": HEAD, "at": "2026-01-01T00:00:00Z"}]
    assert ghreview.head_approvers(res) == 1 and res["head"] == HEAD


def test_stale_approval_names_reviewer_and_old_commit():
    res = ghreview.judge(VIEW, [rest("bob", "APPROVED", OLD)])
    assert res["code"] == "stale-approval" and ghreview.head_approvers(res) == 0
    assert ghreview.message(res) == "승인이 이전 커밋(bob@1234567) — head abcdef0에 다시 Approve"
    many = ghreview.judge(VIEW, [rest(n, "APPROVED", OLD) for n in ("a", "b", "c", "d")])
    assert ghreview.message(many) == "승인이 이전 커밋(a@1234567, b@1234567, c@1234567 외 1명) — head abcdef0에 다시 Approve"


def test_changes_requested_wins_over_other_head_approval():
    res = ghreview.judge(VIEW, [rest("bob", "CHANGES_REQUESTED")])
    assert res["code"] == "changes-requested" and ghreview.message(res) == "변경 요청(bob)"
    res = ghreview.judge(VIEW, [rest("alice", "APPROVED"), rest("bob", "CHANGES_REQUESTED", at="x")])
    assert res["code"] == "changes-requested" and res["changes"] == [{"login": "bob", "at": "x"}]
    many = ghreview.judge(VIEW, [rest(n, "CHANGES_REQUESTED") for n in ("a", "b", "c", "d", "e")])
    assert ghreview.message(many) == "변경 요청(a, b, c 외 2명)"


def test_last_opinion_per_reviewer_in_list_order():
    assert code([rest("bob", "CHANGES_REQUESTED"), rest("bob", "APPROVED")]) == "ok"           # 변경 요청 뒤 재승인
    assert code([rest("bob", "APPROVED"), rest("bob", "CHANGES_REQUESTED")]) == "changes-requested"
    # 목록 순서가 이긴다(submitted_at으로 정렬하지 않는다)
    assert code([rest("bob", "APPROVED", at="2026-12-31"), rest("bob", "CHANGES_REQUESTED", at="2026-01-01")]) == \
        "changes-requested"


def test_dismissed_clears_that_reviewers_opinion():
    assert code([rest("bob", "APPROVED"), rest("bob", "DISMISSED")]) == "no-approval"
    assert code([rest("bob", "CHANGES_REQUESTED"), rest("bob", "DISMISSED")]) == "no-approval"
    assert code([rest("bob", "CHANGES_REQUESTED"), rest("bob", "DISMISSED"), rest("alice", "APPROVED")]) == "ok"


def test_comment_and_pending_after_approval_do_not_hide_it():
    assert code([rest("bob", "APPROVED"), rest("bob", "COMMENTED")]) == "ok"
    assert code([rest("bob", "APPROVED"), rest("bob", "PENDING")]) == "ok"


def test_author_reviews_are_ignored():
    assert code([rest("mock-user", "APPROVED")]) == "no-approval"
    assert code([rest("mock-user", "CHANGES_REQUESTED"), rest("bob", "APPROVED")]) == "ok"


def test_logins_compare_case_insensitively():
    view = {**VIEW, "author": {"login": "Mock-User"}}
    assert code([rest("mock-user", "APPROVED")], view) == "no-approval"                         # 본인
    res = ghreview.judge(VIEW, [rest("Bob", "CHANGES_REQUESTED"), rest("bob", "APPROVED")])     # 같은 사람
    assert res["code"] == "ok" and res["approvals"][0]["login"] == "bob"                        # 표시는 마지막 철자


def test_bot_reviews_are_ignored_in_real_rest_shape():
    for bot in ({"login": "github-actions[bot]", "type": "Bot"}, {"login": "copilot-pull-request-reviewer[bot]", "type": "Bot"},
                {"login": "ci-app", "type": "Bot"}, {"login": "ci[bot]"}):
        approve = {"user": bot, "state": "APPROVED", "commit_id": HEAD}
        assert code([approve]) == "no-approval", bot
        assert code([{**approve, "state": "CHANGES_REQUESTED"}, rest("bob", "APPROVED")]) == "ok", bot   # 봇 변경 요청도 무시
    res = ghreview.judge(VIEW, [{"user": {"login": "github-actions[bot]", "type": "Bot"}, "state": "APPROVED",
                                 "commit_id": HEAD}, rest("bob", "APPROVED")])
    assert res["code"] == "ok" and [a["login"] for a in res["approvals"]] == ["bob"]
    assert code([gql("github-actions", "APPROVED", __typename="Bot")]) == "no-approval"
    assert ghreview.is_bot({"login": "app/ci", "is_bot": True}) and ghreview.is_bot("app/ci") and not ghreview.is_bot("bob")


def test_graphql_review_author_has_no_bot_marker_so_db_pr_reads_rest():
    """gh `pr view --json reviews`의 작성자는 `{login}`뿐이다(GraphQL `Bot.login`에 `[bot]`이 없다). 판정은 이 모양으로는 봇을
    가려낼 수 없다 — 그래서 db_pr(ghpr.reviews)는 REST `pulls/<n>/reviews`의 `user.type`을 읽는다(Q19)."""
    assert code([gql("github-actions", "APPROVED")]) == "ok"
    assert code([rest("github-actions", "APPROVED", kind="Bot")]) == "no-approval"


def test_no_author_refuses_even_with_approval():
    for author in (None, {}, {"login": ""}, {"login": "  "}):
        res = ghreview.judge({**VIEW, "author": author}, [rest("bob", "APPROVED")])
        assert res["code"] == "no-author" and res["approvals"] == [], author
        assert ghreview.message(res) == "PR 작성자를 알 수 없다(gh author 없음) — GHE에서 PR을 확인한다"


def test_missing_commit_is_stale_and_missing_head_cannot_be_ok():
    for review in (rest("bob", "APPROVED", ""), rest("bob", "APPROVED", None), gql("bob", "APPROVED", None),
                   {"user": {"login": "bob"}, "state": "APPROVED"}):
        res = ghreview.judge(VIEW, [review])
        assert res["code"] == "stale-approval" and ghreview.message(res).startswith("승인이 이전 커밋(bob@?)"), review
    res = ghreview.judge({**VIEW, "headRefOid": ""}, [rest("bob", "APPROVED", "")])
    assert res["code"] == "stale-approval" and ghreview.head_approvers(res) == 0
    assert ghreview.message(res) == "승인이 이전 커밋(bob@?) — head ?에 다시 Approve"


def test_malformed_input_does_not_raise():
    assert code(None) == "no-approval" and code({"a": 1}) == "no-approval"
    assert code(["x", 3, None, {"state": "APPROVED"}, {"user": None, "state": "APPROVED"}]) == "no-approval"
    assert code([{"user": "bob", "state": "approved", "commit_id": HEAD}]) == "ok"         # user가 문자열(스텁 옛 상태)
    assert code([{"user": {"login": 3}, "state": "APPROVED", "commit_id": HEAD}]) == "no-approval"
    assert ghreview.judge(None, [])["code"] == "no-author"
    assert code([gql("bob", "APPROVED")]) == "ok"                                          # GraphQL 모양 commit.oid


def test_codes_and_messages_cover_every_refusal():
    assert len(ghreview.CODES) == 5 and set(ghreview.CODES) == {"ok", "no-author", "changes-requested", "stale-approval",
                                                                "no-approval"}
    for c in ghreview.CODES:
        msg = ghreview.message({"code": c, "head": HEAD, "approvals": [{"login": "b", "commit": OLD}],
                                "changes": [{"login": "b"}]})
        assert (msg is None) == (c == "ok"), c
        assert c == "ok" or isinstance(msg, str) and msg and "PR:" not in msg, c


def test_parse_pages_joins_paginated_arrays():
    a, b = {"id": 1}, {"id": 2}
    assert ghreview.parse_pages("[]") == []
    assert ghreview.parse_pages(json.dumps([a]) + json.dumps([b])) == [a, b]
    assert ghreview.parse_pages(f"{json.dumps([a])}\n{json.dumps([b])}\n") == [a, b]
    for bad in ("{}", json.dumps([a]) + "{}", "[1,", "", "  \n", None, "<html>"):
        assert ghreview.parse_pages(bad) is None, bad


# -- ghpr ----------------------------------------------------------------------------------------------


class _Target:
    repo = Path("/clone")
    base = "main"
    host = "ghe.mock.invalid"


def fake_run(stdout: str = "", code: int = 0, stderr: str = ""):
    calls = []

    def run(target, args, cwd):
        calls.append((args, cwd))
        return subprocess.CompletedProcess(["gh", *args], code, stdout, stderr)
    return run, calls


def test_with_link_and_plus_one_shape():
    link = "https://ghe.mock.invalid/o/r/pull/3"
    assert ghpr.with_link("승인 없음", link) == f"승인 없음. PR: {link}"
    assert ghpr.with_link("승인 없음", None, 3) == "승인 없음. PR: #3"
    ok = ghpr.plus_one(VIEW, [rest("bob", "APPROVED")])
    assert set(ok) == {"review", "approvers", "reason", "brief"} and set(ok["review"]) == {"code", "approvals"}
    assert ok["review"]["code"] == "ok" and ok["approvers"] == 1 and ok["reason"] is None and ok["brief"] is None
    no = ghpr.plus_one(VIEW, [])
    assert no["reason"] == f"승인 없음 — 작성자 외 1명의 Approve가 필요하다. PR: {VIEW['url']}"
    assert no["brief"] == "승인 없음 — 작성자 외 1명의 Approve가 필요하다" and "PR:" not in no["brief"]
    other = "https://other.mock.invalid/o/r/pull/3"
    assert ghpr.plus_one({**VIEW, "url": None}, [], other, 3)["reason"].endswith(f". PR: {other}")     # merge-offer url
    assert ghpr.plus_one({**VIEW, "url": None}, [], None, 3)["reason"].endswith(". PR: #3")


def test_reviews_reads_rest_endpoint_from_view_url():
    page = json.dumps([rest("bob", "APPROVED")])
    run, calls = fake_run(page + page)
    items, err = ghpr.reviews(_Target(), VIEW, 3, run)
    assert err is None and len(items) == 2
    assert calls == [(["api", "--hostname", "ghe.mock.invalid", "repos/mock-org/telephony-issue-db/pulls/3/reviews?per_page=100",
                       "--paginate"], Path("/clone"))]
    for view, number in (({**VIEW, "url": None}, 3), ({**VIEW, "url": "https://ghe.mock.invalid/o/r/issues/3"}, 3), (VIEW, 4)):
        run, calls = fake_run(page)
        assert ghpr.reviews(_Target(), view, number, run) == (None, "PR 주소를 알 수 없다(gh url)") and calls == []
    run, _ = fake_run("", 1, "HTTP 502\n")
    assert ghpr.reviews(_Target(), VIEW, 3, run) == (None, "HTTP 502")
    run, _ = fake_run('{"message": "x"}')
    assert ghpr.reviews(_Target(), VIEW, 3, run) == (None, 'JSON 배열 아님: {"message": "x"}')


def test_view_and_merge_method_keep_merge_py_behavior():
    run, calls = fake_run('{"number": 3}')
    assert ghpr.view(_Target(), 3, "number,url", run) == ({"number": 3}, None)
    assert calls[0][0] == ["pr", "view", "3", "--json", "number,url"]
    assert ghpr.view(_Target(), 3, "x", fake_run("", 1, "no pull requests\n")[0]) == (None, "no pull requests")
    assert ghpr.view(_Target(), 3, "x", fake_run("<html>")[0]) == (None, "JSON 아님: <html>")
    assert ghpr.view(_Target(), 3, "x", fake_run("[1]")[0]) == (None, "객체 아님")
    for allowed, want in (({"mergeCommitAllowed": True, "squashMergeAllowed": True}, "merge"),
                          ({"squashMergeAllowed": True, "rebaseMergeAllowed": True}, "squash"),
                          ({"rebaseMergeAllowed": True}, "rebase"), ({}, "merge")):
        run, calls = fake_run(json.dumps(allowed))
        assert ghpr.merge_method(_Target(), run) == want, allowed
    assert calls[0][0] == ["repo", "view", "--json", "mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed"]
    assert ghpr.merge_method(_Target(), fake_run("", 1)[0]) == "merge"
    assert ghpr.merge_method(_Target(), fake_run("x")[0]) == "merge"
    assert ghpr.rollup_state([{"context": "b", "state": "PENDING"}]) == ("pending", ["b"])


def _all_tests():
    return [(name, obj) for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
