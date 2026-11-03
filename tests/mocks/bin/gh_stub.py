#!/usr/bin/env python3
"""`gh` CLI 스텁 (15-local-draft.md §15.2). 사내 GHE를 대신한다.

지원: `auth status`, `pr create`, `pr list`(`--search`, `--author`), `pr view`, `pr edit`, `pr merge`, `pr review`, `repo view`,
`api`(GET `repos/<o>/<r>/pulls/<n>/reviews`만 — REST 리뷰 목록).
`pr view --json`의 `author`는 `{login, is_bot}`, `reviews`는 gh GraphQL 모양(`author{login}`만 — 실제 gh처럼 봇 표시 없음),
`reviewRequests`는 리뷰어(`/`가 있으면 Team). `api` 리뷰 목록은 REST 모양(`user{login, type}`, `commit_id`, `submitted_at`).
리뷰 = `MOCK_GH_REVIEWS`(앞) + `pr review`가 상태에 쓴 것(뒤).
상태는 `tests/mocks/gh-state/prs.json`에 저장한다
(`MOCK_GH_STATE_DIR`로 바꿀 수 있다).

테스트는 `PATH` 앞에 `tests/mocks/bin`을 둔다. `db_pr`은 PATH의 `gh`를 쓰므로
코드 변경이 없다.

동작을 바꾸는 환경변수 (테스트용):
  MOCK_GH_STATE_DIR   상태 파일 디렉토리
  MOCK_GH_UNAUTH=1    `auth status`를 실패시킨다 (setup 9번 경로 시험)
  MOCK_GH_USER        `--author @me`가 가리키는 사용자 (기본 mock-user). `pr create`가 author로 기록한다
  MOCK_GH_FAIL_LIST=1 `pr list`를 실패시킨다 (my-prs의 gh 실패 경로 시험)
  MOCK_GH_BAD_JSON=<문자열>  `pr list`가 그 문자열(1이면 html)을 stdout에 내고 0으로 끝난다 (my-prs 경고 경로 시험)
  MOCK_GH_CHECKS      `pr view`의 statusCheckRollup: none(기본, 빈 목록) | pass | pending | fail
  MOCK_GH_MERGE_STATE `pr view`의 mergeStateStatus (기본 CLEAN)
  MOCK_GH_REVIEW_DECISION `pr view`의 reviewDecision (기본 빈 값 — 필수 리뷰 없음)
  MOCK_GH_MERGE_METHODS `repo view`가 허용하는 병합 방식(쉼표, 기본 merge,squash,rebase)
  MOCK_GH_FAIL_MERGE=1 `pr merge`를 실패시킨다
  MOCK_GH_UNKNOWN_REVIEWERS=<쉼표 목록>  `pr create --reviewer`·`pr edit --add-reviewer`에 그 값이 있으면 종료 1
                      (`could not request reviewer`, PR을 만들거나 고치지 않는다 — 없는 팀·사용자)
  MOCK_GH_CREATE_THEN_FAIL=1 `pr create`가 PR을 만든 뒤 종료 1 (publish의 head 브랜치 재조회 경로 시험)
  MOCK_GH_REVIEWS     리뷰(쉼표 목록) `[<선택자>=]<종류>:<login>@<커밋>`. 선택자 = PR 번호 또는 head 브랜치(없으면 모든 PR),
                      종류 = approve | request-changes | comment | dismissed | pending, 커밋 = head(보기 때의 headRefOid) |
                      old(이전 커밋) | none(commit 없음) | 7~40 hex. 형식이 틀리면 종료 2 (`parse_reviews`)
  MOCK_GH_REVIEW_COMMIT `pr review`가 기록하는 커밋 (기본 지금 headRefOid — 이전 커밋 승인을 만들 때)
  MOCK_GH_NOW         `pr review`가 기록하는 시각 (기본 지금 UTC)
  MOCK_GH_FAIL_REVIEWS=1 `api` 리뷰 목록을 실패시킨다 (종료 1)
  GH_HOST             호스트 이름 (없으면 ghe.mock.invalid)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "gh-state"
DEFAULT_HOST = "ghe.mock.invalid"
MOCK_USER = "mock-user"
OLD_OID = hashlib.sha1(b"mock-old-commit").hexdigest()
REVIEW_KINDS = {"approve": "APPROVED", "request-changes": "CHANGES_REQUESTED", "comment": "COMMENTED",
                "dismissed": "DISMISSED", "pending": "PENDING"}
REVIEW_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[bot\])?$")
REVIEWS_ENDPOINT_RE = re.compile(r"^/?repos/([^/]+)/([^/]+)/pulls/(\d+)/reviews/?(?:\?.*)?$")


def state_path() -> Path:
    base = Path(os.environ.get("MOCK_GH_STATE_DIR") or DEFAULT_STATE_DIR)
    base.mkdir(parents=True, exist_ok=True)
    return base / "prs.json"


def load_state() -> dict:
    path = state_path()
    if not path.is_file():
        return {"next_number": 1, "prs": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"next_number": 1, "prs": []}


def unknown_reviewers(requested: list[str]) -> list[str]:
    bad = {r.strip() for r in (os.environ.get("MOCK_GH_UNKNOWN_REVIEWERS") or "").split(",") if r.strip()}
    return [r for r in requested if r in bad]


def save_state(state: dict) -> None:
    state_path().write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


def me() -> str:
    return os.environ.get("MOCK_GH_USER") or MOCK_USER


def host() -> str:
    return os.environ.get("GH_HOST") or DEFAULT_HOST


def repo_key() -> str:
    """`gh`는 cwd의 origin으로 레포를 정한다. 스텁도 같은 방식으로 키를 만든다."""
    explicit = os.environ.get("GH_REPO")
    if explicit:
        return explicit
    try:
        url = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown/unknown"
    name = Path(url).name
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return f"mock-org/{name}"


def current_branch() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "HEAD"


def head_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def pr_url(repo: str, number: int) -> str:
    return f"https://{host()}/{repo}/pull/{number}"


def cmd_auth(argv: list[str]) -> int:
    if not argv or argv[0] != "status":
        print(f"gh 스텁: 지원하지 않는 auth 하위 명령: {argv}", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--hostname", default=host())
    args, _ = parser.parse_known_args(argv[1:])
    if os.environ.get("MOCK_GH_UNAUTH") == "1":
        print(
            "You are not logged into any GitHub hosts. "
            f"Run gh auth login to authenticate. (host: {args.hostname})",
            file=sys.stderr,
        )
        return 1
    print(args.hostname)
    print(f"  - Logged in to {args.hostname} as {MOCK_USER} (oauth_token)")
    return 0


def _emit_json(fields: list[str], rows: list[dict]) -> None:
    if not fields:
        print(json.dumps(rows, ensure_ascii=False))
        return
    trimmed = [{k: row.get(k) for k in fields} for row in rows]
    print(json.dumps(trimmed, ensure_ascii=False))


def cmd_pr(argv: list[str]) -> int:
    if not argv:
        print("gh 스텁: pr 하위 명령이 필요합니다.", file=sys.stderr)
        return 2
    sub, rest = argv[0], argv[1:]
    state = load_state()
    repo = repo_key()

    if sub == "create":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--title", default="")
        parser.add_argument("--body", default="")
        parser.add_argument("--body-file", default=None)
        parser.add_argument("--base", default="main")
        parser.add_argument("--head", default=None)
        parser.add_argument("--reviewer", action="append", default=[])
        parser.add_argument("--draft", action="store_true")
        args, _ = parser.parse_known_args(rest)
        body = args.body
        if args.body_file:
            body = Path(args.body_file).read_text(encoding="utf-8")
        branch = args.head or current_branch()
        unknown = unknown_reviewers(args.reviewer)
        if unknown:
            print(f"could not request reviewer: '{unknown[0]}' not found", file=sys.stderr)
            return 1
        existing = [
            p
            for p in state["prs"]
            if p["repo"] == repo and p["branch"] == branch and p["state"] == "OPEN"
        ]
        if existing:
            print(
                f"a pull request for branch {branch!r} already exists: "
                f"{existing[0]['url']}",
                file=sys.stderr,
            )
            return 1
        number = state["next_number"]
        state["next_number"] = number + 1
        pr = {
            "repo": repo,
            "number": number,
            "title": args.title,
            "body": body,
            "base": args.base,
            "baseRefName": args.base,
            "branch": branch,
            "headRefName": branch,
            "headRefOid": head_sha(),
            "author": me(),
            "state": "OPEN",
            "isDraft": args.draft,
            "reviewers": args.reviewer,
            "url": pr_url(repo, number),
        }
        state["prs"].append(pr)
        save_state(state)
        if os.environ.get("MOCK_GH_CREATE_THEN_FAIL") == "1":
            print("gh 스텁: PR을 만든 뒤 실패 (MOCK_GH_CREATE_THEN_FAIL)", file=sys.stderr)
            return 1
        print(pr["url"])
        return 0

    if sub == "list":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--search", default=None)
        parser.add_argument("--state", default="open")
        parser.add_argument("--head", default=None)
        parser.add_argument("--author", default=None)
        parser.add_argument("--json", dest="json_fields", default=None)
        parser.add_argument("--limit", type=int, default=30)
        args, _ = parser.parse_known_args(rest)
        if os.environ.get("MOCK_GH_FAIL_LIST") == "1":
            print("gh 스텁: pr list 실패 (MOCK_GH_FAIL_LIST)", file=sys.stderr)
            return 1
        bad = os.environ.get("MOCK_GH_BAD_JSON")
        if bad:
            print("<html>proxy error</html>" if bad == "1" else bad)
            return 0
        rows = [p for p in state["prs"] if p["repo"] == repo]
        if args.author:
            who = me() if args.author == "@me" else args.author
            rows = [p for p in rows if p.get("author", MOCK_USER) == who]
        if args.state and args.state != "all":
            rows = [p for p in rows if p["state"] == args.state.upper()]
        if args.head:
            rows = [p for p in rows if p["branch"] == args.head]
        if args.search:
            needle = args.search.lower()
            rows = [
                p
                for p in rows
                if needle in (p["title"] or "").lower()
                or needle in (p["body"] or "").lower()
                or needle in p["branch"].lower()
            ]
        rows = rows[: args.limit]
        if args.json_fields is not None:
            _emit_json([f for f in args.json_fields.split(",") if f], rows)
        else:
            for p in rows:
                print(f"#{p['number']}\t{p['title']}\t{p['branch']}\t{p['state']}")
        return 0

    if sub in ("view", "edit"):
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("selector", nargs="?", default=None)
        parser.add_argument("--json", dest="json_fields", default=None)
        parser.add_argument("--title", default=None)
        parser.add_argument("--body", default=None)
        parser.add_argument("--body-file", default=None)
        parser.add_argument("--add-reviewer", action="append", default=[])
        args, _ = parser.parse_known_args(rest)
        selector = args.selector or current_branch()
        match = None
        for p in state["prs"]:
            if p["repo"] != repo:
                continue
            if selector.isdigit() and p["number"] == int(selector):
                match = p
                break
            if p["branch"] == selector and p["state"] == "OPEN":
                match = p
                break
        if match is None:
            print(f"no pull requests found for {selector!r}", file=sys.stderr)
            return 1
        if sub == "edit":
            unknown = unknown_reviewers(args.add_reviewer)
            if unknown:
                print(f"could not request reviewer: '{unknown[0]}' not found", file=sys.stderr)
                return 1
            if args.title is not None:
                match["title"] = args.title
            if args.body_file:
                match["body"] = Path(args.body_file).read_text(encoding="utf-8")
            elif args.body is not None:
                match["body"] = args.body
            for reviewer in args.add_reviewer:
                if reviewer not in match["reviewers"]:
                    match["reviewers"].append(reviewer)
            if args.title is not None or args.body is not None or args.body_file:
                # 재게시(제목·본문 고치기)는 push 뒤에 온다 — 그때만 head를 다시 본다. --add-reviewer만이면 head를 바꾸지 않는다
                # (사용자 clone(main) 등 다른 cwd에서 불러도 PR head 그대로)
                match["headRefOid"] = head_sha()
            save_state(state)
            print(match["url"])
            return 0
        if args.json_fields is not None:
            fields = [f for f in args.json_fields.split(",") if f]
            author = match.get("author", MOCK_USER)
            view = {**match, "statusCheckRollup": _rollup(), "mergeStateStatus": os.environ.get("MOCK_GH_MERGE_STATE") or "CLEAN",
                    "isDraft": bool(match.get("isDraft")), "reviewDecision": os.environ.get("MOCK_GH_REVIEW_DECISION") or "",
                    "author": author if isinstance(author, dict) else {"login": author, "is_bot": False},
                    "reviewRequests": _review_requests(match)}
            if "reviews" in fields:
                try:
                    view["reviews"] = [_graphql_review(r) for r in _reviews_of(match)]
                except ValueError as exc:
                    print(f"gh 스텁: MOCK_GH_REVIEWS 형식 오류: {exc}", file=sys.stderr)
                    return 2
            print(json.dumps({k: view.get(k) for k in fields}, ensure_ascii=False))
        else:
            print(f"#{match['number']} {match['title']}")
            print(match["body"])
        return 0

    if sub == "review":
        return _pr_review(rest, state, repo)

    if sub == "merge":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("selector")
        parser.add_argument("--merge", action="store_true")
        parser.add_argument("--squash", action="store_true")
        parser.add_argument("--rebase", action="store_true")
        parser.add_argument("--match-head-commit", default=None)
        parser.add_argument("--delete-branch", "-d", action="store_true")
        args, _ = parser.parse_known_args(rest)
        match = next((p for p in state["prs"] if p["repo"] == repo and str(p["number"]) == args.selector), None)
        if match is None:
            print(f"no pull requests found for {args.selector!r}", file=sys.stderr)
            return 1
        methods = [m for m in ("merge", "squash", "rebase") if getattr(args, m)]
        if len(methods) != 1:
            print("--merge, --rebase, --squash 중 하나만", file=sys.stderr)
            return 1
        if os.environ.get("MOCK_GH_FAIL_MERGE") == "1":
            print("gh 스텁: pr merge 실패 (MOCK_GH_FAIL_MERGE)", file=sys.stderr)
            return 1
        if match["state"] != "OPEN":
            print(f"Pull request #{match['number']} is not open", file=sys.stderr)
            return 1
        if args.match_head_commit and args.match_head_commit != match.get("headRefOid"):
            print("Head branch was modified. Review and try the merge again.", file=sys.stderr)
            return 1
        oid = hashlib.sha1(f"{repo}#{match['number']}:{match.get('headRefOid')}".encode()).hexdigest()
        match.update(state="MERGED", mergeCommit={"oid": oid}, mergedWith=methods[0],
                     deleteBranch=args.delete_branch)
        save_state(state)
        print(f"✓ Merged pull request #{match['number']}")
        return 0

    print(f"gh 스텁: 지원하지 않는 pr 하위 명령: {sub}", file=sys.stderr)
    return 2


def parse_reviews(spec: str | None) -> list[dict]:
    """`MOCK_GH_REVIEWS` → `[{selector, state, login, commit}]`(목록 순서 = 만든 순서). commit은 "head"(보기 때 headRefOid로 푼다),
    `OLD_OID`, None, 소문자 hex. 형식이 틀리면 ValueError(틀린 항목). skill_eval_env가 같은 파서로 setup을 검증한다."""
    out = []
    for item in (spec or "").split(","):
        item = item.strip()
        if not item:
            continue
        selector, eq, rest = item.rpartition("=")
        kind, colon, who = rest.partition(":")
        name, at, commit = who.partition("@")
        if (eq and (not selector or any(c.isspace() for c in selector))) or not colon or not at \
                or kind not in REVIEW_KINDS or not REVIEW_LOGIN_RE.fullmatch(name) \
                or not (commit in ("head", "old", "none") or re.fullmatch(r"[0-9a-fA-F]{7,40}", commit)):
            raise ValueError(item)
        out.append({"selector": selector if eq else None, "state": REVIEW_KINDS[kind], "login": name,
                    "commit": {"old": OLD_OID, "none": None}.get(commit, commit if commit == "head" else commit.lower())})
    return out


def _reviews_of(pr: dict) -> list[dict]:
    """그 PR의 리뷰(한 모양 `{login, state, commit, at, body}`): env 리뷰(앞, head는 지금 headRefOid로) + 상태에 저장된 리뷰(뒤)."""
    out = []
    for i, r in enumerate(parse_reviews(os.environ.get("MOCK_GH_REVIEWS")), 1):
        sel = r["selector"]
        if sel is not None and not (str(pr["number"]) == sel if sel.isdigit() else pr.get("branch") == sel):
            continue
        commit = pr.get("headRefOid") if r["commit"] == "head" else r["commit"]
        out.append({"login": r["login"], "state": r["state"], "commit": commit, "at": f"2026-01-01T00:00:{i:02d}Z",
                    "body": ""})
    return out + [r for r in pr.get("reviews") or [] if isinstance(r, dict)]


def _graphql_review(r: dict) -> dict:
    """gh `pr view --json reviews` 모양. 실제 gh처럼 작성자는 `{login}`뿐이다(봇 표시 없음)."""
    return {"author": {"login": r.get("login")}, "state": r.get("state"),
            "commit": {"oid": r["commit"]} if r.get("commit") else None, "submittedAt": r.get("at"), "body": r.get("body") or ""}


def _rest_review(i: int, r: dict) -> dict:
    """REST `pulls/<n>/reviews` 항목 모양."""
    name = str(r.get("login") or "")
    return {"id": i, "user": {"login": name, "type": "Bot" if name.endswith("[bot]") else "User"}, "state": r.get("state"),
            "commit_id": r.get("commit") or None, "submitted_at": r.get("at"), "author_association": "MEMBER",
            "body": r.get("body") or ""}


def _review_requests(pr: dict) -> list[dict]:
    out = []
    for r in pr.get("reviewers") or []:
        if "/" in r:
            slug = r.rsplit("/", 1)[1]
            out.append({"__typename": "Team", "name": slug, "slug": slug})
        else:
            out.append({"__typename": "User", "login": r})
    return out


def _login_of(author) -> str:
    return str(author.get("login") if isinstance(author, dict) else author or "")


def _pr_review(rest: list[str], state: dict, repo: str) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("selector", nargs="?", default=None)
    parser.add_argument("-a", "--approve", action="store_true")
    parser.add_argument("-r", "--request-changes", action="store_true")
    parser.add_argument("-c", "--comment", action="store_true")
    parser.add_argument("-b", "--body", default=None)
    parser.add_argument("-F", "--body-file", default=None)
    args, _ = parser.parse_known_args(rest)
    kinds = [k for k, on in (("approve", args.approve), ("request-changes", args.request_changes),
                             ("comment", args.comment)) if on]
    if len(kinds) != 1:
        print("--approve, --request-changes, or --comment required", file=sys.stderr)
        return 1
    kind = kinds[0]
    body = args.body or ""
    if args.body_file:
        body = sys.stdin.read() if args.body_file == "-" else Path(args.body_file).read_text(encoding="utf-8")
    if kind != "approve" and not body.strip():
        print(f"body cannot be blank for {kind} review", file=sys.stderr)
        return 1
    selector = args.selector or current_branch()
    match = next((p for p in state["prs"] if p["repo"] == repo and p["state"] == "OPEN"
                  and (p["number"] == int(selector) if selector.isdigit() else p["branch"] == selector)), None)
    if match is None:
        print(f"no pull requests found for {selector!r}", file=sys.stderr)
        return 1
    if kind != "comment" and _login_of(match.get("author", MOCK_USER)).casefold() == me().casefold():
        what = "approve" if kind == "approve" else "request changes on"
        print(f"failed to create review: GraphQL: Review Can not {what} your own pull request (addPullRequestReview)",
              file=sys.stderr)
        return 1
    at = os.environ.get("MOCK_GH_NOW") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    match.setdefault("reviews", []).append({"login": me(), "state": REVIEW_KINDS[kind],
                                            "commit": os.environ.get("MOCK_GH_REVIEW_COMMIT") or match.get("headRefOid"),
                                            "at": at, "body": body})
    save_state(state)
    done = {"approve": "Approved", "request-changes": "Requested changes to", "comment": "Reviewed"}[kind]
    print(f"✓ {done} pull request #{match['number']}")
    return 0


def cmd_api(argv: list[str]) -> int:
    """`gh api [--hostname <h>] [--paginate] [-X GET] repos/<o>/<r>/pulls/<n>/reviews[?…]`만. REST 모양 배열 하나를 낸다."""
    endpoint, method, i = None, "GET", 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("--hostname", "-X", "--method") and i + 1 < len(argv):
            if tok != "--hostname":
                method = argv[i + 1].upper()
            i += 2
            continue
        if tok.startswith(("--hostname=", "--method=")):
            if tok.startswith("--method="):
                method = tok.split("=", 1)[1].upper()
        elif tok == "--paginate":
            pass
        elif not tok.startswith("-") and endpoint is None:
            endpoint = tok
        else:
            endpoint = None
            break
        i += 1
    m = REVIEWS_ENDPOINT_RE.match(endpoint or "")
    if m is None or method != "GET":
        print(f"gh 스텁: 지원하지 않는 api: {argv}", file=sys.stderr)
        return 2
    owner, name, number = m.groups()
    slug = repo_key() if (owner, name) == ("{owner}", "{repo}") else f"{owner}/{name}"
    if os.environ.get("MOCK_GH_FAIL_REVIEWS") == "1":
        print("gh 스텁: 리뷰 읽기 실패 (MOCK_GH_FAIL_REVIEWS)", file=sys.stderr)
        return 1
    match = next((p for p in load_state()["prs"]
                  if str(p.get("repo", "")).casefold() == slug.casefold() and p["number"] == int(number)), None)
    if match is None:
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        return 1
    try:
        items = [_rest_review(n, r) for n, r in enumerate(_reviews_of(match), 1)]
    except ValueError as exc:
        print(f"gh 스텁: MOCK_GH_REVIEWS 형식 오류: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(items, ensure_ascii=False))
    return 0


def _rollup() -> list[dict]:
    kind = os.environ.get("MOCK_GH_CHECKS") or "none"
    if kind == "pass":
        return [{"__typename": "CheckRun", "name": "db-check", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    if kind == "pending":
        return [{"__typename": "CheckRun", "name": "db-check", "status": "IN_PROGRESS", "conclusion": ""}]
    if kind == "fail":
        return [{"__typename": "StatusContext", "context": "db-check", "state": "FAILURE"}]
    return []


def cmd_repo(argv: list[str]) -> int:
    if not argv or argv[0] != "view":
        print(f"gh 스텁: 지원하지 않는 repo 하위 명령: {argv}", file=sys.stderr)
        return 2
    allowed = set((os.environ.get("MOCK_GH_MERGE_METHODS") or "merge,squash,rebase").split(","))
    print(json.dumps({"mergeCommitAllowed": "merge" in allowed, "squashMergeAllowed": "squash" in allowed,
                      "rebaseMergeAllowed": "rebase" in allowed}))
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print("gh 스텁: 명령이 필요합니다 (auth | pr | repo | api).", file=sys.stderr)
        return 2
    if argv[0] == "--version":
        print("gh version 0.0.0-mock (stub)")
        return 0
    if argv[0] == "auth":
        return cmd_auth(argv[1:])
    if argv[0] == "pr":
        return cmd_pr(argv[1:])
    if argv[0] == "repo":
        return cmd_repo(argv[1:])
    if argv[0] == "api":
        return cmd_api(argv[1:])
    print(f"gh 스텁: 지원하지 않는 명령: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
