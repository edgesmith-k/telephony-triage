#!/usr/bin/env python3
"""`gh` CLI 스텁 (15-local-draft.md §15.2). 사내 GHE를 대신한다.

지원: `auth status`, `pr create`, `pr list`(`--search`, `--author`), `pr view`, `pr edit`, `pr merge`, `repo view`.
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
  MOCK_GH_MERGE_METHODS `repo view`가 허용하는 병합 방식(쉼표, 기본 merge,squash,rebase)
  MOCK_GH_FAIL_MERGE=1 `pr merge`를 실패시킨다
  GH_HOST             호스트 이름 (없으면 ghe.mock.invalid)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "gh-state"
DEFAULT_HOST = "ghe.mock.invalid"
MOCK_USER = "mock-user"


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
            if args.title is not None:
                match["title"] = args.title
            if args.body_file:
                match["body"] = Path(args.body_file).read_text(encoding="utf-8")
            elif args.body is not None:
                match["body"] = args.body
            for reviewer in args.add_reviewer:
                if reviewer not in match["reviewers"]:
                    match["reviewers"].append(reviewer)
            match["headRefOid"] = head_sha()
            save_state(state)
            print(match["url"])
            return 0
        if args.json_fields is not None:
            fields = [f for f in args.json_fields.split(",") if f]
            view = {**match, "statusCheckRollup": _rollup(), "mergeStateStatus": os.environ.get("MOCK_GH_MERGE_STATE") or "CLEAN",
                    "isDraft": bool(match.get("isDraft"))}
            print(json.dumps({k: view.get(k) for k in fields}, ensure_ascii=False))
        else:
            print(f"#{match['number']} {match['title']}")
            print(match["body"])
        return 0

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
        print("gh 스텁: 명령이 필요합니다 (auth | pr).", file=sys.stderr)
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
    print(f"gh 스텁: 지원하지 않는 명령: {argv[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
