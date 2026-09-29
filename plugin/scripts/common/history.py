"""이슈 DB git 이력 조회 (06-collaboration.md §6.6 방치 기간, contracts.md §renumber 참조).

- `since()`: 원인이 지금 상태(예: `fix.status: fix-submitted`)에 들어간 날. `type.md`를 바꾼 커밋을
  최신부터 거슬러 보며 조건이 계속 참인 가장 오래된 커밋의 커미터 날짜를 쓴다. 이슈 DB 파일에는
  상태 전환 날짜가 없으므로(`fix`·`resolution_verification`에 날짜 필드 없음) git 이력이 유일한 근거다.
- `renumbered()`: 커밋 메시지의 `Renumbered: <옛 ID> -> <새 ID>` 트레일러 (사후 정리 커밋).

git 레포가 아니거나 이력이 없으면 `since()`는 `(None, "no-history")`를 낸다. 워킹 트리에만 있는
(커밋 전) 상태면 `(None, "uncommitted")`다. 호출하는 쪽은 이 경우를 "기간 확인 불가"로 보고한다.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Callable

import yaml

from . import yamlio

RENUMBERED_RE = re.compile(r"^Renumbered:\s*(\S+)\s*->\s*(\S+)\s*$", re.M)


def _git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def is_repo(repo: Path) -> bool:
    """`repo`가 커밋이 있는 git 레포(또는 worktree)의 **최상위**인지. 다른 레포 안의 하위 디렉토리(시험용 트리 등)는
    그 레포의 이력이 이슈 DB 이력이 아니므로 아니라고 본다."""
    top = _git(repo, "rev-parse", "--show-toplevel")
    if not top or Path(top.strip()).resolve() != Path(repo).resolve():
        return False
    out = _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    return bool(out and out.strip())


class History:
    """한 이슈 DB의 이력 조회. 파일별 커밋 목록과 커밋별 frontmatter를 캐시한다."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.enabled = is_repo(self.root)
        self._commits: dict[str, list[tuple[str, date]]] = {}
        self._docs: dict[tuple[str, str], dict | None] = {}

    def commits(self, rel: str) -> list[tuple[str, date]]:
        """`rel`을 바꾼 커밋 `(sha, 커미터 날짜)` 최신순."""
        if rel not in self._commits:
            out = _git(self.root, "log", "--format=%H %cs", "HEAD", "--", rel) if self.enabled else None
            rows = []
            for line in (out or "").splitlines():
                sha, _, when = line.partition(" ")
                try:
                    rows.append((sha, date.fromisoformat(when.strip())))
                except ValueError:
                    continue
            self._commits[rel] = rows
        return self._commits[rel]

    def frontmatter(self, sha: str, rel: str) -> dict | None:
        key = (sha, rel)
        if key not in self._docs:
            text = _git(self.root, "show", f"{sha}:{rel}")
            data = None
            if text and text.startswith("---\n"):
                end = text.find("\n---\n", 3)
                if end > 0:
                    try:
                        loaded = yamlio.loads(text[4:end])
                        data = loaded if isinstance(loaded, dict) else None
                    except yaml.YAMLError:
                        data = None
            self._docs[key] = data
        return self._docs[key]

    def since(self, rel: str, cause_id: str, pred: Callable[[dict], bool]) -> tuple[date | None, str]:
        """원인 `cause_id`가 `pred`를 만족한 연속 구간의 시작일. `(날짜, "git")` 또는 `(None, 사유)`."""
        commits = self.commits(rel)
        if not commits:
            return None, "no-history"
        start = None
        for sha, when in commits:
            doc = self.frontmatter(sha, rel)
            cause = _find_cause(doc, cause_id)
            if cause is None or not pred(cause):
                break
            start = when
        if start is None:
            return None, "uncommitted"
        return start, "git"

    def renumbered(self) -> list[dict]:
        """`Renumbered:` 트레일러 `[{from, to, commit, date}]` (오래된 커밋부터)."""
        if not self.enabled:
            return []
        out = _git(self.root, "log", "--reverse", "--format=%H%x1f%cs%x1f%B%x1e", "--grep=^Renumbered:",
                   "HEAD") or ""
        rows = []
        for chunk in out.split("\x1e"):
            parts = chunk.strip("\n").split("\x1f", 2)
            if len(parts) != 3:
                continue
            sha, when, body = parts
            for old, new in RENUMBERED_RE.findall(body):
                rows.append({"from": old, "to": new, "commit": sha.strip(), "date": when})
        return rows


def _find_cause(doc: dict | None, cause_id: str) -> dict | None:
    for cause in (doc or {}).get("causes") or []:
        if isinstance(cause, dict) and str(cause.get("id")) == cause_id:
            return cause
    return None
