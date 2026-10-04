#!/usr/bin/env python3
"""db_pr.py — 이슈 DB 쓰기 오케스트레이션 (contracts.md §3.2 `db_pr.py` 세부, 01-architecture.md §3.1).

    db_pr.py lock status
    db_pr.py lock acquire <작업 키> [--command <이름>] [--take-over]
    db_pr.py lock release <작업 키> [--force]
    db_pr.py snapshot --job <작업 키>
    db_pr.py cleanup (--dry-run | --yes) [--older-than [<days>]]
    db_pr.py preflight --branch <br> [--search <원인 ID|JIRA-KEY>] [--jira <KEY>]
    db_pr.py stage <plan.json> --wt <dir> --branch <br> [--dry-run]
    db_pr.py summary <wt>
    db_pr.py publish <wt> --branch <br> --lease <sha|new> --approved <hash>
    db_pr.py discard <wt>
    db_pr.py find-plan --branch <br>          (sync-pr 1~4번 보조: 계획 찾기·원격 변경 확인)

작업 디렉토리 `<work_dir>/<작업 키>/`: `plan.json`(계획), `state.json`(`{base_sha, branch, approved_hash,
commit_message, staged_at}`), `included_pending/`, `wt/`(작업 worktree). 구현 파일: `stage.json`(stage 결과,
summary 입력), `regress.json`, `pr.json`(summary가 만든 PR 제목·본문·리뷰어, publish 입력). discard가 지운다.
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

`stage` 종료 코드: 하위 결과 집계(1이 하나라도 있으면 1, 없고 3이 있으면 3). drift면 적용 전에 1.
`publish`는 승인 해시·커밋 부모·커밋 메시지·브랜치를 `state.json`과 대조하고(다르면 1), lease push 뒤
PR을 만들거나(`gh pr create`) 고친다(`gh pr edit`).

시각은 환경변수 `TT_NOW`(ISO, 테스트용)로 바꿀 수 있다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import masking, site_defaults, userconfig, yamlio  # noqa: E402
from common.buildname import is_valid_branch_name  # noqa: E402
from common import checks as checks_mod  # noqa: E402
from common import ghcli  # noqa: E402
from common.exitcodes import CHECK_FAILED, NEEDS_APPROVAL, OK, USAGE  # noqa: E402

LOCK_FILE = "session.lock"
SNAPSHOT_DIR = "_snapshot"
FRESH = timedelta(minutes=10)
EXPIRE = timedelta(hours=4)
STATE, STAGE, PR_FILE, REGRESS, PLAN = "state.json", "stage.json", "pr.json", "regress.json", "plan.json"
WORK_FILES = (STATE, STAGE, PR_FILE, REGRESS)
TOOL_PREFIX = "tt/"
GENERATED_RE = re.compile(r"^(README\.md|STATS\.md|parser-rules/CHANGELOG\.md|[^/]+/README\.md)$")
SOURCE_LABELS = {"analyze": "분석 (analyze)", "record": "수동 기록 (record)", "import": "기존 분류 가져오기 (import)",
                 "fix-submitted": "수정 CL 반영 (fix-submitted)", "verify-fix": "코드 수정 검증 (verify-fix)",
                 "validate-cause": "해결책 검증 (validate --cause)", "review": "월간 리뷰 정리 (review)",
                 "move": "유형 이동·병합 (move)"}


class UsageError(Exception):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail


def now() -> datetime:
    env = os.environ.get("TT_NOW")
    if env:
        return datetime.fromisoformat(env.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# -- lock -----------------------------------------------------------------------------


def _locked(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self.guard():
            return method(self, *args, **kwargs)
    return guarded


class Lock:
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.path = work_dir / LOCK_FILE
        self.owner = os.environ.get("TT_LOCK_OWNER")

    @contextmanager
    def guard(self):
        """Stable OS lock inode; never unlink it while other processes may wait."""
        userconfig.ensure_private_dir(self.work_dir)
        with (self.work_dir / "session.guard").open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise UsageError("session lock guard 시간 초과") from exc
                    time.sleep(.02)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def read(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not all(isinstance(data.get(k), str)
                    for k in ("job", "started_at", "updated_at")):
                raise ValueError("invalid lock record")
            _parse(data["updated_at"])
            return data
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError) as exc:
            raise UsageError("session.lock을 읽을 수 없습니다. 손상된 lock을 확인한다.") from exc

    def describe(self, data: dict | None) -> dict | None:
        if data is None:
            return None
        age = now() - _parse(data["updated_at"])
        return {**data, "expired": age > EXPIRE, "age_sec": int(age.total_seconds())}

    def write(self, data: dict) -> None:
        userconfig.ensure_private_dir(self.work_dir)
        fd, name = tempfile.mkstemp(dir=self.work_dir, prefix=".session-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    @_locked
    def acquire(self, job: str, command: str | None, take_over: bool) -> dict:
        held = self.describe(self.read())
        stamp = _iso(now())
        if held is not None and not held["expired"]:
            if held["job"] != job:
                raise UsageError(f"다른 작업({held['job']}, {held.get('command')})이 lock을 갖고 있습니다. "
                                 "그 세션이 끝났는지 확인하고, 끝났으면 lock release <작업 키> --force로 푼다.",
                                 {"holder": held})
            if now() - _parse(held["updated_at"]) <= FRESH and not take_over:
                raise UsageError(f"같은 작업({job})의 lock이 {held['age_sec']}초 전에 갱신됐습니다. 다른 세션이 "
                                 "진행 중일 수 있다. 사용자가 확인하면 --take-over로 이어받는다.", {"holder": held})
        taken_from = held
        started = held["started_at"] if (held and held["job"] == job) else stamp
        self.owner = uuid.uuid4().hex
        data = {"job": job, "owner": self.owner, "command": command or (held or {}).get("command"), "started_at": started,
                "updated_at": stamp}
        self.write(data)
        return {"acquired": True, "lock": self.describe(data),
                "taken_over": bool(taken_from), "previous": taken_from}

    @_locked
    def touch(self, job: str) -> dict:
        """lock이 그 작업 키 것인지 확인하고 `updated_at`을 갱신한다. 만료 여부는 보지 않는다: 만료는 **다른** 작업이
        `acquire`로 가져갈 수 있다는 뜻이고, 아직 같은 작업 키가 남아 있으면 아무도 가져가지 않은 것이므로 그대로
        이어간다 (확인 화면에서 4시간 넘게 기다린 뒤의 publish·discard가 멈추지 않게)."""
        held = self.describe(self.read())
        if held is None or held["job"] != job:
            raise UsageError(f"세션 lock이 작업 {job}의 것이 아닙니다. 먼저 lock acquire {job}를 한다.",
                             {"holder": held})
        self.check_owner(held)
        held.update(updated_at=_iso(now()))
        self.write({k: held[k] for k in ("job", "owner", "command", "started_at", "updated_at")})
        return held

    def check_owner(self, held: dict) -> None:
        if not self.owner or self.owner != held.get("owner"):
            raise UsageError("lock owner 불일치: acquire 결과 lock.owner를 TT_LOCK_OWNER로 전달한다.")

    @_locked
    def release(self, job: str, force: bool) -> dict:
        held = self.describe(self.read())
        if held is None:
            return {"released": False, "note": "lock이 없습니다"}
        if held["job"] != job and not force:
            raise UsageError(f"lock 보유자는 {held['job']}입니다. 그 세션이 끝났다면 --force로 푼다.", {"holder": held})
        if not force:
            self.check_owner(held)
        self.path.unlink()
        return {"released": True, "previous": held, "forced": held["job"] != job}


# -- snapshot ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise UsageError("git 시간 초과 (120초). 원격·로컬 상태를 확인한 뒤 재개한다.") from exc
    except OSError as exc:
        raise UsageError(f"git 실행 실패: {exc}") from exc
    if check and proc.returncode != 0:
        raise UsageError(f"git {' '.join(args)} 실패: {proc.stderr.strip()}")
    return proc


def snapshot(job: str, cfg: dict, lock: Lock) -> dict:
    repo = Path(str(userconfig.get(cfg, "issue_db.path") or "")).expanduser()
    if not (repo / ".git").exists():
        raise UsageError(f"issue_db.path가 git clone이 아닙니다: {repo} (setup 3에서 clone한다)")
    base = userconfig.get(cfg, "issue_db.base_branch") or "main"
    fetch = _git(repo, "fetch", "origin")
    lock.touch(job)
    ref = f"origin/{base}"
    snap = lock.work_dir / SNAPSHOT_DIR
    _git(repo, "worktree", "prune")
    if (snap / ".git").exists():
        _git(snap, "checkout", "--detach", "-f", ref)
    else:
        if snap.exists() and any(snap.iterdir()):
            raise UsageError(f"{snap}가 worktree가 아닌데 비어 있지 않습니다. 확인 후 지운다.")
        _git(repo, "worktree", "add", "--detach", str(snap), ref)
    sha = _git(snap, "rev-parse", "HEAD").stdout.strip()

    pulled, reason = False, None
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    dirty = _git(repo, "status", "--porcelain", check=False).stdout.strip()
    if branch != base:
        reason = f"사용자 clone의 현재 브랜치가 {branch}라서 pull을 건너뛰었다 ({base}일 때만)"
    elif dirty:
        reason = "사용자 clone에 커밋하지 않은 변경이 있어 pull을 건너뛰었다"
    else:
        proc = _git(repo, "pull", "--ff-only", check=False)
        if proc.returncode == 0:
            pulled = True
        else:
            reason = f"pull --ff-only 실패(자동으로 해결하지 않는다): {proc.stderr.strip()[:200]}"
    return {"fetched": fetch.returncode == 0, "snapshot": str(snap), "snapshot_sha": sha,
            "pulled": pulled, "pull_skipped_reason": reason, "post_lint": post_lint(snap)}


def post_lint(snap: Path) -> dict:
    """사후 lint (06-collaboration.md §6.3 ⑤). 보고만 한다."""
    code, data, err = run_script("db_lint.py", ["--all", "--db", str(snap)])
    if data is None:
        return {"ran": False, "error": err.strip()[:300]}
    errors = data.get("errors") or []
    dups = [e for e in errors if e.get("code") in ("duplicate-id", "duplicate-jira")]
    out = {"ran": True, "errors": len(errors), "warnings": len(data.get("warnings") or []),
           "duplicates": [{"code": e["code"], "file": e.get("file"), "message": e.get("message")} for e in dups],
           "findings": [{"code": e["code"], "file": e.get("file"), "message": e.get("message")} for e in errors]}
    if errors:
        out["notice"] = ("main 스냅샷에서 이슈 DB 규칙 위반을 찾았다. 도구는 정리하지 않는다: 문제 종류·파일·관련 PR을 "
                         "메인테이너에게 알린다 (06-collaboration.md §6.3 사후 lint 정리 정책).")
    return out


# -- 공통 도우미 ---------------------------------------------------------------------------

_PLUGIN_ROOT: str | None = None


def run_script(name: str, args: list[str], env: dict | None = None) -> tuple[int, dict | None, str]:
    """플러그인 스크립트를 부른다. (종료 코드, stdout JSON 또는 None, stderr)."""
    return checks_mod.run_script(name, args, plugin_root=_PLUGIN_ROOT, env=env)


class Ctx:
    """설정에서 정한 경로·브랜치."""

    def __init__(self, cfg: dict, lock: Lock):
        self.cfg = cfg
        self.lock = lock
        self.repo = Path(str(userconfig.get(cfg, "issue_db.path") or "")).expanduser()
        self.base = str(userconfig.get(cfg, "issue_db.base_branch") or "main")
        self.host = userconfig.get(cfg, "issue_db.ghe_host")
        self.work_dir = lock.work_dir

    def require_repo(self) -> None:
        if not (self.repo / ".git").exists():
            raise UsageError(f"issue_db.path가 git clone이 아닙니다: {self.repo} (setup 3에서 clone한다)")

    def pending_dir(self) -> Path:
        return userconfig.home() / "pending-feedback"


def _job_of(wt: Path, ctx: Ctx) -> tuple[Path, str]:
    wt = Path(wt).expanduser().absolute()
    root = ctx.work_dir.absolute()
    if wt.name not in ("wt", "draft") or wt.parent.parent != root or wt.parent.name.startswith("."):
        raise UsageError(f"작업 경로는 work_dir/<작업 키>/wt 또는 draft여야 합니다: {wt}")
    for path in (root, wt.parent, wt):
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise UsageError(f"작업 경로의 symlink/junction은 허용하지 않습니다: {path}")
    if not wt.resolve().is_relative_to(root.resolve()):
        raise UsageError(f"work_dir 밖 경로: {wt}")
    return wt.parent, wt.parent.name


def _owned_worktree(ctx: Ctx, path: Path) -> None:
    _job_of(path, ctx)
    row = next((w for w in _worktrees(ctx.repo) if _same_path(w["path"], path)), None)
    if not row or not (path / ".git").is_file():
        raise UsageError(f"등록된 도구 worktree가 아닙니다: {path}")
    branch = row.get("branch", "")
    if (path.name == "wt" and not branch.startswith("refs/heads/tt/")) or (path.name == "draft" and branch):
        raise UsageError(f"도구 worktree의 브랜치가 아닙니다: {path}")
    common = _out(_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    expected = _out(_git(ctx.repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    if not _same_path(common, expected):
        raise UsageError(f"다른 저장소 worktree: {path}")


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _out(proc: subprocess.CompletedProcess) -> str:
    return proc.stdout.strip()


def _ref_sha(repo: Path, ref: str) -> str | None:
    proc = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return _out(proc) or None


def _worktrees(repo: Path) -> list[dict]:
    """`git worktree list --porcelain` → [{path, branch, head}]."""
    rows, cur = [], {}
    for line in _out(_git(repo, "worktree", "list", "--porcelain", check=False)).splitlines() + [""]:
        if not line:
            if cur:
                rows.append(cur)
            cur = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            cur["path"] = value
        elif key == "branch":
            cur["branch"] = value
        elif key == "HEAD":
            cur["head"] = value
    return rows


def _same_path(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a) == str(b)


def _check_branch(ctx: Ctx, branch: str) -> None:
    if branch in (ctx.base, f"refs/heads/{ctx.base}") or branch.startswith(TOOL_PREFIX):
        raise UsageError(f"브랜치 {branch}는 쓸 수 없습니다 (base 브랜치이거나 도구 브랜치 접두어).")
    if not is_valid_branch_name(branch) or not is_valid_branch_name(TOOL_PREFIX + branch):
        raise UsageError(f"브랜치 이름이 올바르지 않습니다: {branch} (git check-ref-format --branch)")


def _gh(ctx: Ctx, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    proc = ghcli.run(args, host=ctx.host, cwd=str(cwd))
    if proc.returncode == 124:
        raise UsageError(proc.stderr)
    return proc


# -- preflight -----------------------------------------------------------------------------


def preflight(ctx: Ctx, branch: str, search: str | None, jira: str | None) -> dict:
    ctx.require_repo()
    _check_branch(ctx, branch)
    _git(ctx.repo, "fetch", "--prune", "origin")
    tool = TOOL_PREFIX + branch
    tool_sha = _ref_sha(ctx.repo, f"refs/heads/{tool}")
    tool_wt = next((w["path"] for w in _worktrees(ctx.repo) if w.get("branch") == f"refs/heads/{tool}"), None)
    user_sha = _ref_sha(ctx.repo, f"refs/heads/{branch}")
    remote_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{branch}")
    ahead = 0
    if user_sha:
        against = f"refs/remotes/origin/{branch}" if remote_sha else f"refs/remotes/origin/{ctx.base}"
        ahead = int(_out(_git(ctx.repo, "rev-list", "--count", f"{against}..refs/heads/{branch}", check=False)) or 0)
    open_prs, warnings = None, []
    if search:
        proc = _gh(ctx, ["pr", "list", "--search", search, "--state", "open", "--json",
                         "number,title,url,headRefName"], ctx.repo)
        if proc.returncode == 0:
            open_prs = json.loads(proc.stdout or "[]")
        else:
            warnings.append(f"열린 PR을 확인하지 못했다 (gh): {(proc.stderr or '').strip()[:200]}")
    jira_in_main = None
    if jira:
        names = _out(_git(ctx.repo, "ls-tree", "-r", "--name-only", f"origin/{ctx.base}", check=False)).splitlines()
        hit = next((n for n in names if re.fullmatch(rf"[^/]+/[^/]+/jira/{re.escape(jira)}\.yaml", n)), None)
        if hit:
            record = yamlio.loads(_out(_git(ctx.repo, "show", f"origin/{ctx.base}:{hit}", check=False))) or {}
            jira_in_main = {"path": hit, "cause": record.get("cause")}
    return {
        "branch": branch,
        "tool_branch": {"name": tool, "exists": bool(tool_sha), "sha": tool_sha, "worktree": tool_wt,
                        "residual": bool(tool_sha) and tool_wt is None},
        "user_branch": {"exists": bool(user_sha), "sha": user_sha, "ahead_of_remote": ahead},
        "remote_sha": remote_sha,
        "open_prs": open_prs,
        "jira_in_main": jira_in_main,
        "warnings": warnings,
    }


# -- stage ---------------------------------------------------------------------------------


def _pending_files(ctx: Ctx, job_dir: Path) -> list[Path]:
    seen, out = set(), []
    for d in (job_dir / "included_pending", ctx.pending_dir()):
        for path in sorted(d.glob("*.yaml")) if d.is_dir() else []:
            if path.name not in seen:
                seen.add(path.name)
                out.append(path)
    return out


def _prepare_worktree(ctx: Ctx, wt: Path, tool: str, base_sha: str) -> str:
    _job_of(wt, ctx)
    if (wt / ".git").exists():
        _owned_worktree(ctx, wt)
        for args in (("checkout", "-f", "-B", tool, base_sha), ("reset", "--hard", base_sha), ("clean", "-fd")):
            _git(wt, *args)
        return "reapplied"
    if wt.exists() and any(wt.iterdir()):
        raise UsageError(f"{wt}가 worktree가 아닌데 비어 있지 않습니다. 확인 후 지운다 (db_pr cleanup).")
    _git(ctx.repo, "worktree", "add", "--no-track", "-B", tool, str(wt), base_sha)
    return "created"


def stage(ctx: Ctx, plan_path: Path, wt: Path, branch: str, dry_run: bool) -> tuple[dict, int]:
    ctx.require_repo()
    job_dir, job = _job_of(wt, ctx)
    wt = Path(wt).expanduser().resolve()
    ctx.lock.touch(job)
    _check_branch(ctx, branch)
    tool = TOOL_PREFIX + branch
    _git(ctx.repo, "worktree", "prune")
    for w in _worktrees(ctx.repo):
        if w.get("branch") == f"refs/heads/{tool}" and not _same_path(w["path"], wt):
            raise UsageError(f"도구 브랜치 {tool}가 다른 worktree({w['path']})에 checkout돼 있습니다. 그 작업을 "
                             "끝내거나 db_pr cleanup으로 정리한다.", {"worktree": w["path"]})
    _git(ctx.repo, "fetch", "origin")
    base_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{ctx.base}")
    if not base_sha:
        raise UsageError(f"origin/{ctx.base}가 없습니다.")
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    for name in (STAGE, PR_FILE, REGRESS):
        (job_dir / name).unlink(missing_ok=True)
    state = {"base_sha": base_sha, "branch": branch, "approved_hash": None, "commit_message": None,
             "staged_at": _iso(now())}
    _write_json(job_dir / STATE, state)
    result: dict = {"job": job, "wt": str(wt), "branch": branch, "tool_branch": tool, "base_sha": base_sha,
                    "plan": str(Path(plan_path).resolve()), "dry_run": dry_run, "source": plan.get("source")}

    if plan.get("base_sha") != base_sha:
        code, data, err = run_script("db_add.py", ["drift", str(plan_path), "--onto", base_sha, "--db", str(ctx.repo)])
        if code == USAGE or data is None:
            raise UsageError(f"drift 검사 실패: {err.strip()[:300]}")
        result["drift"] = data.get("drift") or []
        if code == CHECK_FAILED:
            result["stopped"] = "drift"
            result["next"] = ("drift 항목마다 계획 값 유지 / main 값 유지(op 삭제) / 직접 입력을 골라 계획에 반영하고 "
                              f"base_sha를 {base_sha}로 바꾼 뒤 다시 stage한다 (contracts.md §작업 계획 drift).")
            _write_json(job_dir / STAGE, result)
            return result, CHECK_FAILED
    else:
        result["drift"] = []

    result["worktree"] = _prepare_worktree(ctx, wt, tool, base_sha)
    code, check, err = run_script("config.py", ["check", "--db", str(wt), "--for", "dry-run" if dry_run else "write"])
    result["config_check"] = check
    if code != OK:
        reasons = "; ".join(r.get("message", "") for r in (check or {}).get("reasons") or []) or err.strip()
        raise UsageError(f"쓰기 불가: {reasons}", result)

    pending = _pending_files(ctx, job_dir) if plan.get("source") == "analyze" else []
    args = ["apply", str(plan_path), "--db", str(wt)]
    for path in pending:
        args += ["--pending", str(path)]
    code, applied, err = run_script("db_add.py", args)
    result["apply"] = applied
    result["pending_sources"] = [str(p) for p in pending]
    if code != OK:
        _write_json(job_dir / STAGE, result)
        if code == USAGE:
            raise UsageError(f"계획을 적용할 수 없습니다: {err.strip()[:500]}", result)
        result["stopped"] = "apply"
        return result, code

    db_cfg = yamlio.load(wt / "issue-db.config.yaml") or {}
    ci_mode = db_cfg.get("ci_mode", "local")
    cctx = checks_mod.Ctx(db=wt, scope="worktree", ref=f"origin/{ctx.base}", ci_mode=ci_mode, db_cfg=db_cfg,
                          plan=plan_path, regress_json=job_dir / REGRESS, plugin_root=_PLUGIN_ROOT)

    def save_regress(res: checks_mod.StepResult) -> None:
        if res.name == "regress":
            _write_json(job_dir / REGRESS, res.data or {})

    run = checks_mod.run_checks(checks_mod.PROFILES["stage"], cctx, on_step=save_regress)
    if run.aborted is not None:
        bad = run.aborted
        if bad.name == "verify":
            # 주의: verify의 실행 불가는 checks 없이 result만 싣고 STAGE도 쓰지 않는다 (기존 동작 유지).
            raise UsageError(f"db_verify 실행 불가: {bad.stderr[:300]}", result)
        checks_so_far = _stage_checks(run)
        _write_json(job_dir / STAGE, {**result, "checks": checks_so_far})
        raise UsageError(f"{bad.script} 실행 불가: {bad.stderr[:300]}", {**result, "checks": checks_so_far})
    if ci_mode != "actions-build":
        checks_out = _stage_checks(run)
    else:
        checks_out = {"skipped": "ci_mode: actions-build — 생성·검사는 CI가 한다 (13-actions.md)"}
    result["checks"] = checks_out
    final = run.overall   # 1 > 3 > 0 (2는 위에서 중단했다)
    result["result"] = {0: "ok", 1: "check-failed", 3: "needs-approval"}[final]
    _write_json(job_dir / STAGE, result)
    return result, final


def _stage_checks(run: checks_mod.Run) -> dict:
    """`Run`을 stage 결과의 `checks` 모양 `{이름: {code, result, stderr}}`으로 (verify는 stderr 없음)."""
    out: dict = {}
    for res in run.steps:
        out[res.name] = {"code": res.code, "result": res.data}
        if res.name != "verify":
            out[res.name]["stderr"] = res.stderr[-500:] if res.code else ""
    return out


# -- summary -------------------------------------------------------------------------------


def _status_entries(wt: Path) -> list[tuple[str, str]]:
    raw = _git(wt, "status", "--porcelain=v1", "-z", "-uall").stdout
    out = []
    for entry in filter(None, raw.split("\0")):
        out.append((entry[:2], entry[3:]))
    return out


def _file_kind(path: str) -> str:
    if GENERATED_RE.match(path):
        return "생성 파일"
    if "/jira/" in path:
        return "Jira 기록"
    if path.startswith("feedback/"):
        return "피드백"
    if path.endswith("/type.md"):
        return "유형"
    if path.startswith("parser-rules/"):
        return "파서 규칙"
    if "/fixtures/" in path:
        return "fixture"
    return "기타"


def _codeowners(wt: Path) -> list[tuple[str, list[str]]]:
    path = wt / ".github" / "CODEOWNERS"
    rules = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            rules.append((parts[0], parts[1:]))
    return rules


def _owners_for(rules: list[tuple[str, list[str]]], rel: str) -> list[str]:
    owners: list[str] = []
    for pattern, who in rules:   # CODEOWNERS: 마지막으로 맞는 규칙이 이긴다
        p = pattern.lstrip("/")
        if (p.endswith("/") and rel.startswith(p)) or rel == p:
            owners = who
    return owners


def reviewers(wt: Path, paths: list[str], plan: dict, db_cfg: dict) -> list[str]:
    rules = _codeowners(wt)
    owners: list[str] = []
    for rel in paths:
        if GENERATED_RE.match(rel):   # 생성 파일은 원본 변경을 따라가므로 리뷰어 계산에서 뺀다
            continue
        owners += _owners_for(rules, rel)
        if rel.endswith("/type.md") and (wt / rel).is_file():
            from common.issuedb import read_frontmatter
            for sc in read_frontmatter(wt / rel).get("secondary_categories") or []:
                owners += _owners_for(rules, f"{sc}/")
    for op in plan.get("operations") or []:
        if op.get("op") == "allow-cause":
            name = str(op.get("fixture", "")).split("/")[-1]
            m = re.match(r"([A-Z][A-Z0-9]*)-\d{3}", name)
            cat = next((c["key"] for c in db_cfg.get("categories") or [] if m and c.get("id_prefix") == m.group(1)),
                       None)
            if cat:
                owners += _owners_for(rules, f"{cat}/")
    fmt = str((db_cfg.get("reviewers") or {}).get("format") or "{org}/{team}")
    out = []
    for owner in owners:
        org, _, team = owner.lstrip("@").partition("/")
        value = fmt.format(org=org, team=team) if team else owner.lstrip("@")
        if value not in out:
            out.append(value)
    return out


def approved_hash(wt: Path) -> str:
    """워킹 트리 전체(.gitignore 적용)를 임시 index로 올린 트리 해시. 기존 파일의 모드를 유지하려고
    HEAD에서 시작한다(`read-tree HEAD` → `add -A` → `write-tree`)."""
    fd, idx = tempfile.mkstemp(prefix="tt-approve-index-")
    os.close(fd)
    os.unlink(idx)
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    try:
        for args in (("read-tree", "HEAD"), ("add", "-A")):
            proc = _git(wt, *args, env=env)
            if proc.returncode != 0:
                raise UsageError(f"승인 해시 계산 실패 (git {' '.join(args)}): {proc.stderr.strip()}")
        proc = _git(wt, "write-tree", env=env)
        if proc.returncode != 0:
            raise UsageError(f"승인 해시 계산 실패: {proc.stderr.strip()}")
        return proc.stdout.strip()
    finally:
        if os.path.exists(idx):
            os.unlink(idx)


def _verification_rows(stage_result: dict) -> list[dict]:
    verify = ((stage_result.get("checks") or {}).get("verify") or {}).get("result") or {}
    rows = []
    for item in verify.get("rules") or []:
        shown = {"pass": "통과", "fail": "실패", "needs-approval": "승인 필요", "not-implemented": "미구현(뼈대)"}
        status = item.get("status")
        label = shown.get(status) or (f"건너뜀: {item.get('reason')}" if status == "skipped" else status)
        if status == "skipped" and item.get("review_required"):
            label = f"검증 못 함 — 리뷰 대상 ({item.get('reason')})"
        rows.append({"id": item.get("id"), "status": status, "label": label, "reason": item.get("reason"),
                     "review_required": item.get("review_required", False)})
    return rows


def _check_rows(stage_result: dict) -> dict:
    checks = stage_result.get("checks") or {}
    if "skipped" in checks:
        return {"skipped": checks["skipped"]}

    def res(name):
        return (checks.get(name) or {}).get("result") or {}

    lint, mask, ids, regress = res("lint"), res("mask"), res("ids"), res("regress")
    return {
        "lint": {"ok": (checks.get("lint") or {}).get("code") == OK, "errors": len(lint.get("errors") or []),
                 "warnings": len(lint.get("warnings") or []),
                 "findings": [f"{f.get('code')}: {f.get('file')}" for f in (lint.get("errors") or [])][:20]},
        "ids": {"ok": (checks.get("ids") or {}).get("code") == OK, "duplicates": ids.get("duplicates") or []},
        "mask": {"ok": (checks.get("mask") or {}).get("code") == OK, "detections": len(mask.get("detections") or [])},
        "regress": {"ok": (checks.get("regress") or {}).get("code") == OK,
                    "passed": (regress.get("summary") or {}).get("passed"),
                    "total": (regress.get("summary") or {}).get("total"),
                    "failed": [r.get("fixture") for r in regress.get("results") or [] if r.get("status") != "pass"]},
        "build": {"ok": (checks.get("build") or {}).get("code") == OK},
    }


def _readme_preview(wt: Path, keys: list[str]) -> list[str]:
    lines = []
    for path in [wt / "README.md", *sorted(wt.glob("*/README.md"))]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if (line.startswith("|") or line.startswith("###")) and any(k in line for k in keys) and line not in lines:
                lines.append(line)
    return lines[:20]


def _main_diff(wt: Path, entries: list[tuple[str, str]]) -> tuple[list[str], int]:
    tracked = [p for s, p in entries if s != "??" and not GENERATED_RE.match(p) and "/fixtures/" not in p]
    diff = _out(_git(wt, "diff", "--", *tracked, check=False)).splitlines() if tracked else []
    for status, path in entries:
        if status == "??" and not GENERATED_RE.match(path) and "/fixtures/" not in path:
            text = (wt / path).read_text(encoding="utf-8", errors="replace").splitlines()
            diff += [f"+++ {path} (신규)"] + ["+" + line for line in text]
    return diff[:50], len(diff)


def summary(ctx: Ctx, wt: Path) -> dict:
    job_dir, job = _job_of(wt, ctx)
    _owned_worktree(ctx, wt)
    wt = job_dir / wt.name
    ctx.lock.touch(job)
    state = _read_json(job_dir / STATE)
    stage_result = _read_json(job_dir / STAGE)
    if not state or not stage_result or not stage_result.get("apply"):
        raise UsageError("stage 결과가 없습니다. 먼저 db_pr stage를 한다.")
    plan = json.loads(Path(stage_result["plan"]).read_text(encoding="utf-8"))
    applied = stage_result["apply"]
    db_cfg = yamlio.load(wt / "issue-db.config.yaml") or {}
    entries = _status_entries(wt)
    names = {"??": "신규", " M": "수정", "M ": "수정", " D": "삭제", "D ": "삭제", "A ": "신규"}
    deleted = {Path(p).name: p for s, p in entries if "D" in s}
    files = []
    for status, path in entries:
        change = names.get(status, status.strip() or "수정")
        if status == "??" and Path(path).name in deleted and "/jira/" in path:
            change = f"이동 (← {deleted[Path(path).name]})"
        elif "D" in status and any(s == "??" and Path(p).name == Path(path).name and "/jira/" in p for s, p in entries):
            continue
        files.append({"kind": _file_kind(path), "path": path, "change": change})
    paths = [p for _, p in entries]
    jira = plan.get("jira") or {}
    ids = applied.get("ids") or []
    keys = [i["id"] for i in ids] + [jira.get("key")] if jira else [i["id"] for i in ids]
    for op in applied.get("operations") or []:
        for field in ("cause", "type", "to", "id", "a", "b", "owner"):
            if isinstance(op.get(field), str):
                keys.append(op[field])
    keys = [k for k in keys if k]
    diff, diff_total = _main_diff(wt, entries)
    checks = _check_rows(stage_result)
    verification = _verification_rows(stage_result)
    approval = [r for r in verification if r["status"] == "needs-approval"]
    verify_code = ((stage_result.get("checks") or {}).get("verify") or {}).get("code")
    if verify_code == NEEDS_APPROVAL and not approval:
        approval = [{"id": "db_verify", "status": "needs-approval", "label": "승인 필요 (종료 코드 3)"}]
    source = plan.get("source")
    notes = []
    if source == "record":
        notes.append("로그·코드 분석: 하지 않음 (수동 기록)")
    if jira.get("origin") == "file":
        notes.append("Jira 메타데이터: 오프라인 파일")
    new_pending, user_statement = [], False
    for op in applied.get("operations") or []:
        body = op.get("cause") if op.get("op") == "new-cause" else (op.get("first_cause") or {}).get("cause") \
            if op.get("op") == "new-type" else None
        cid = op.get("temp_id") if op.get("op") == "new-cause" else (op.get("first_cause") or {}).get("temp_id")
        if isinstance(body, dict):
            if body.get("signatures_pending") and not body.get("signatures"):
                new_pending.append(cid)
            if "사용자 진술" in str((body.get("resolution_verification") or {}).get("method") or ""):
                user_statement = True
    if "사용자 진술" in str(jira.get("note") or ""):
        user_statement = True
    for cid in new_pending:
        notes.append(f"{cid}: 시그니처 없음 — 매칭 불가, 리뷰 대상")
    if user_statement:
        notes.append("해결책 근거: 사용자 진술 — 카테고리 오너 리뷰 필요")
    for row in verification:
        if row["status"] == "skipped" and row.get("review_required"):
            notes.append(f"{row['id']}: 검증 못 함 — 리뷰 대상 ({row['reason']})")
    # 계획의 pr_notes: 흐름별 설명(drift 결정, verify-fix 근거, allow-cause 사유 등). 한 번 더 마스킹한다.
    masker = masking.new_masker(allow_patterns=(db_cfg.get("mask") or {}).get("allow_patterns") or [])
    notes += [masker(str(n)) for n in plan.get("pr_notes") or [] if str(n).strip()]
    check = stage_result.get("config_check") or {}
    push_allowed = bool(check.get("push_allowed")) and not stage_result.get("dry_run")
    push_note = None
    if stage_result.get("dry_run"):
        push_note = "push 안 함: --dry-run"
        gh_ok, _ = ghcli.auth_status(ctx.host)
        if not gh_ok:
            push_note = "push 불가: gh 인증 없음 (--dry-run)"
    remote_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{state['branch']}")
    open_prs = None
    search = jira.get("key") or (ids[0]["id"] if ids else None)
    if search:
        proc = _gh(ctx, ["pr", "list", "--search", search, "--state", "open", "--json", "number,title,url"], wt)
        if proc.returncode == 0:
            open_prs = json.loads(proc.stdout or "[]")
    commit_message = applied.get("commit_message") or ""
    title = commit_message.splitlines()[0] if commit_message else f"[{job}] {source}"
    revs = reviewers(wt, paths, plan, db_cfg)
    screen = {
        "source": source, "source_label": SOURCE_LABELS.get(source, source),
        "jira": {"key": jira.get("key"), "origin": jira.get("origin"),
                 "label": "Jira 메타데이터: 오프라인 파일" if jira.get("origin") == "file" else None},
        "branch": {"name": state["branch"], "remote": "갱신" if remote_sha else "신규", "remote_sha": remote_sha,
                   "base": ctx.base},
        "reviewers": revs, "open_prs": open_prs,
        "files": files, "ids": ids, "fixtures": applied.get("fixtures") or [],
        "drift_decisions": stage_result.get("drift") or [],
        "readme_preview": _readme_preview(wt, keys), "diff": diff, "diff_total_lines": diff_total,
        "diff_truncated": diff_total > 50, "checks": checks, "verification": verification,
        "approval_needed": approval, "notes": notes, "commit_message": commit_message, "pr_title": title,
        "push_allowed": push_allowed, "push_note": push_note, "pending_included": applied.get("pending_included") or [],
    }
    body = pr_body(screen, plan)
    digest = approved_hash(wt)
    state.update(approved_hash=digest, commit_message=commit_message)
    _write_json(job_dir / STATE, state)
    _write_json(job_dir / PR_FILE, {"title": title, "body": body, "reviewers": revs})
    return {**screen, "pr_body": body, "approved_hash": digest}


def pr_body(screen: dict, plan: dict) -> str:
    jira = plan.get("jira") or {}
    lines = ["## 분석 요약", "", f"- 구분: {screen['source_label']}"]
    if jira:
        info = ", ".join(f"{k}: {jira[k]}" for k in ("model", "sw", "android_version", "carrier") if jira.get(k))
        lines.append(f"- Jira: {jira.get('key')}" + (f" ({info})" if info else ""))
        if jira.get("note"):
            lines.append(f"- 메모: {jira['note']}")
    for note in screen["notes"]:
        lines.append(f"- {note}")
    if screen["ids"]:
        lines.append("- ID 할당: " + ", ".join(f"{i['temp_id']} → {i['id']}" for i in screen["ids"]))
    lines += ["", "### 변경 파일", "", "| 구분 | 파일 | 변경 |", "|---|---|---|"]
    lines += [f"| {f['kind']} | {f['path']} | {f['change']} |" for f in screen["files"]]
    checks = screen["checks"]
    lines += ["", "## 검증 결과", ""]
    if "skipped" in checks:
        lines.append(f"- 자동 검사: {checks['skipped']}")
    else:
        ok = lambda v: "✅" if v else "❌"  # noqa: E731
        lines.append(f"- 스키마·lint {ok(checks['lint']['ok'])} (경고 {checks['lint']['warnings']}건) / "
                     f"ID 중복 {ok(checks['ids']['ok'])} / 마스킹 {ok(checks['mask']['ok'])} / "
                     f"fixture 회귀 {ok(checks['regress']['ok'])} ({checks['regress']['passed']}/"
                     f"{checks['regress']['total']}) / 생성 파일 {ok(checks['build']['ok'])}")
    if screen["verification"]:
        lines += ["", "| 검증 | 결과 |", "|---|---|"]
        lines += [f"| {r['id']} | {r['label']} |" for r in screen["verification"]]
    lines.append("")
    lines.append("승인 필요: " + (", ".join(r["id"] for r in screen["approval_needed"]) + " — 메인테이너 승인 필수"
                                  if screen["approval_needed"] else "없음"))
    return "\n".join(lines) + "\n"


# -- publish -------------------------------------------------------------------------------


def publish(ctx: Ctx, wt: Path, branch: str, lease: str, approved: str) -> tuple[dict, int]:
    job_dir, job = _job_of(wt, ctx)
    _owned_worktree(ctx, wt)
    wt = job_dir / wt.name
    ctx.lock.touch(job)
    state = _read_json(job_dir / STATE)
    stage_result = _read_json(job_dir / STAGE) or {}
    pr_info = _read_json(job_dir / PR_FILE)
    if not state or not state.get("approved_hash") or not pr_info:
        raise UsageError("승인 정보가 없습니다. stage → summary(확인) → 커밋 뒤에 publish한다.")
    problems = []
    tree = _out(_git(wt, "rev-parse", "HEAD^{tree}", check=False))
    if tree != approved or tree != state["approved_hash"]:
        problems.append("커밋 트리가 승인 해시와 다르다 (승인 뒤 파일이 바뀌었다). 확인 화면을 다시 받는다.")
    parent = _out(_git(wt, "rev-parse", "HEAD^", check=False))
    merge = _out(_git(wt, "rev-parse", "--verify", "--quiet", "HEAD^2", check=False))
    if parent != state["base_sha"] or merge:
        problems.append("커밋이 기준 SHA 위의 커밋 하나가 아니다 (커밋이 둘 이상이거나 머지 커밋이거나 기준이 다르다).")
    message = _git(wt, "log", "-1", "--format=%B", "HEAD", check=False).stdout.strip()
    if message != (state.get("commit_message") or "").strip():
        problems.append("커밋 메시지가 확인받은 메시지와 다르다.")
    if branch != state["branch"] or branch == ctx.base:
        problems.append(f"브랜치 {branch}가 stage한 브랜치 {state['branch']}와 다르거나 base 브랜치다.")
    if problems:
        return {"published": False, "problems": problems}, CHECK_FAILED
    lease_arg = (f"--force-with-lease=refs/heads/{branch}:" if lease == "new"
                 else f"--force-with-lease=refs/heads/{branch}:{lease}")
    env = {**os.environ, "TT_PUBLISH_TOKEN": approved}
    push = _git(wt, "push", lease_arg, "origin", f"HEAD:refs/heads/{branch}", check=False, env=env)
    if push.returncode != 0:
        return {"published": False, "pushed": False,
                "problems": ["push가 거부됐다 (원격 브랜치가 그 사이 바뀌었거나 lease가 다르다). 원격 상태를 다시 "
                             "확인하고(preflight) 처음부터 다시 한다."],
                "stderr": push.stderr.strip()[-800:]}, CHECK_FAILED
    head = _out(_git(wt, "rev-parse", "HEAD"))
    _git(ctx.repo, "fetch", "origin", check=False)
    body_file = job_dir / "pr-body.md"
    body_file.write_text(pr_info["body"], encoding="utf-8", newline="\n")
    number, url, action, gh_error = None, None, None, None
    try:
        proc = _gh(ctx, ["pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], wt)
        existing = json.loads(proc.stdout or "[]") if proc.returncode == 0 else []
        if existing:
            number, url = existing[0]["number"], existing[0].get("url")
            proc = _gh(ctx, ["pr", "edit", str(number), "--title", pr_info["title"], "--body-file", str(body_file)],
                       wt)
            action = "edited"
        else:
            args = ["pr", "create", "--base", ctx.base, "--head", branch, "--title", pr_info["title"],
                    "--body-file", str(body_file)]
            for r in pr_info.get("reviewers") or []:
                args += ["--reviewer", r]
            proc = _gh(ctx, args, wt)
            action = "created"
            if proc.returncode == 0:
                url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
                m = re.search(r"/pull/(\d+)", url or "")
                number = int(m.group(1)) if m else None
        if proc.returncode != 0:
            gh_error = (proc.stderr or proc.stdout).strip()[:300]
    finally:
        body_file.unlink(missing_ok=True)
    # 계획 갱신 (pr, base_sha, included_pending)
    plan_path = Path(stage_result.get("plan") or job_dir / PLAN)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["pr"] = {"number": number, "branch": branch, "head_sha": head}
    plan["base_sha"] = state["base_sha"]
    included = {i["file"]: i for i in plan.get("included_pending") or []}
    inc_dir = job_dir / "included_pending"
    for src in stage_result.get("pending_sources") or []:
        src = Path(src)
        if src.parent != inc_dir and src.is_file():
            inc_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(inc_dir / src.name))
        included[src.name] = {"file": src.name, "pr": number}
    plan["included_pending"] = sorted(included.values(), key=lambda i: i["file"])
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    result = {"published": True, "pushed": True, "branch": branch, "head_sha": head, "lease": lease,
              "pr": {"number": number, "url": url, "action": action}, "plan": str(plan_path)}
    if gh_error:
        result["gh_error"] = f"push는 됐지만 PR {action}에 실패했다: {gh_error}"
        return result, USAGE
    return result, OK


# -- discard / cleanup ---------------------------------------------------------------------


def _remove_worktree(ctx: Ctx, path: Path) -> None:
    _owned_worktree(ctx, path)
    _git(ctx.repo, "worktree", "remove", "--force", str(path))


def discard(ctx: Ctx, wt: Path) -> dict:
    job_dir, job = _job_of(wt, ctx)
    wt = job_dir / wt.name
    ctx.lock.touch(job)
    state = _read_json(job_dir / STATE) or {}
    branch = state.get("branch")
    if not branch and (wt / ".git").exists():
        head = _out(_git(wt, "symbolic-ref", "--short", "HEAD", check=False))
        branch = head[len(TOOL_PREFIX):] if head.startswith(TOOL_PREFIX) else None
    removed = []
    if wt.exists():
        _remove_worktree(ctx, wt)
        removed.append(str(wt))
    _git(ctx.repo, "worktree", "prune", check=False)
    deleted_branch = None
    if branch and _ref_sha(ctx.repo, f"refs/heads/{TOOL_PREFIX}{branch}"):
        _git(ctx.repo, "branch", "-D", TOOL_PREFIX + branch)
        deleted_branch = TOOL_PREFIX + branch
    for name in WORK_FILES:
        (job_dir / name).unlink(missing_ok=True)
    released = ctx.lock.release(job, force=False)
    return {"discarded": True, "job": job, "removed_worktrees": removed, "deleted_branch": deleted_branch,
            "lock": released, "plan_kept": (job_dir / PLAN).is_file()}


def cleanup(ctx: Ctx, yes: bool, older_than: int | None) -> dict:
    ctx.require_repo()
    _git(ctx.repo, "worktree", "prune", check=False)
    held = (ctx.lock.read() or {}).get("job")
    targets = []
    checked_out = {w.get("branch") for w in _worktrees(ctx.repo)}
    for job_dir in sorted(p for p in ctx.work_dir.iterdir() if p.is_dir()) if ctx.work_dir.is_dir() else []:
        if job_dir.name in (SNAPSHOT_DIR, held):
            continue
        for sub in ("wt", "draft"):
            if (job_dir / sub).exists():
                targets.append({"kind": "worktree", "job": job_dir.name, "path": str(job_dir / sub)})
        for name in WORK_FILES:
            if (job_dir / name).is_file():
                targets.append({"kind": "state", "job": job_dir.name, "path": str(job_dir / name)})
    refs = _out(_git(ctx.repo, "for-each-ref", "--format=%(refname)", f"refs/heads/{TOOL_PREFIX}", check=False))
    for ref in refs.splitlines():
        wt_paths = [w["path"] for w in _worktrees(ctx.repo) if w.get("branch") == ref]
        will_free = wt_paths and all(any(t["kind"] == "worktree" and _same_path(t["path"], p) for t in targets)
                                     for p in wt_paths)
        if ref not in checked_out or will_free:
            targets.append({"kind": "branch", "name": ref[len("refs/heads/"):]})
    if older_than is not None:
        limit = now() - timedelta(days=older_than)
        for job_dir in sorted(p for p in ctx.work_dir.iterdir() if p.is_dir()) if ctx.work_dir.is_dir() else []:
            plan = _read_json(job_dir / PLAN) if job_dir.name not in (SNAPSHOT_DIR, held) else None
            number = ((plan or {}).get("pr") or {}).get("number")
            if not number:
                continue
            mtime = max(p.stat().st_mtime for p in job_dir.glob("*.json"))
            if datetime.fromtimestamp(mtime, timezone.utc) > limit:
                continue
            proc = _gh(ctx, ["pr", "view", str(number), "--json", "state"], ctx.repo)
            state = (json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else {}).get("state")
            if state in ("MERGED", "CLOSED"):
                targets.append({"kind": "job-dir", "job": job_dir.name, "path": str(job_dir), "pr": number,
                                "pr_state": state})
    done = []
    if yes:
        # Validate the complete deletion set before the first mutation.
        for t in targets:
            if t["kind"] in ("state", "job-dir", "worktree"):
                path = Path(t["path"])
                job_dir = ctx.work_dir / t["job"]
                _job_of(job_dir / "wt", ctx)
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    raise UsageError(f"정리 대상 symlink/junction: {path}")
                if t["kind"] == "worktree":
                    _owned_worktree(ctx, path)
        for t in targets:
            if t["kind"] == "worktree":
                _remove_worktree(ctx, Path(t["path"]))
            elif t["kind"] == "state":
                Path(t["path"]).unlink(missing_ok=True)
            elif t["kind"] == "job-dir":
                shutil.rmtree(t["path"], ignore_errors=True)
            done.append(t)
        _git(ctx.repo, "worktree", "prune", check=False)
        for t in targets:
            if t["kind"] == "branch":
                _git(ctx.repo, "branch", "-D", t["name"], check=False)
    return {"dry_run": not yes, "lock_job": held, "targets": targets, "removed": done if yes else []}


# -- find-plan (sync-pr) -------------------------------------------------------------------

MANUAL_RESYNC = [
    "자기 로컬 브랜치에서 git fetch origin 후 git rebase origin/<base>",
    "충돌이 생성 파일(README, 카테고리 README, STATS, CHANGELOG)뿐이면 main 쪽을 받고 db_build --write로 다시 만든다. "
    "다른 파일 충돌은 직접 해결한다",
    "새 ID가 main과 겹치면(db_add check-ids --base origin/<base>) db_add renumber <옛 ID>로 옮기고 "
    "db_lint --residual <옛 ID>=<새 ID>로 확인한다",
    "/telephony-triage:validate 통과 후 커밋하고 git push --force-with-lease로 올린다",
]


def find_plan(ctx: Ctx, branch: str) -> dict:
    ctx.require_repo()
    found = []
    for path in sorted(ctx.work_dir.glob(f"*/{PLAN}")) if ctx.work_dir.is_dir() else []:
        plan = _read_json(path) or {}
        if (plan.get("pr") or {}).get("branch") == branch:
            found.append((path, plan))
    if not found:
        return {"found": False, "branch": branch,
                "message": "이 브랜치의 작업 계획이 없다(직접 편집한 브랜치이거나 다른 PC에서 만든 PR). 도구는 이 브랜치를 "
                           "바꾸지 않는다. 아래 수동 재동기화 절차를 따른다 (06-collaboration.md §6.3).",
                "manual_steps": [s.replace("<base>", ctx.base) for s in MANUAL_RESYNC]}
    path, plan = found[0]
    _git(ctx.repo, "fetch", "--prune", "origin")
    remote_sha = _ref_sha(ctx.repo, f"refs/remotes/origin/{branch}")
    head_sha = (plan.get("pr") or {}).get("head_sha")
    changed = bool(remote_sha) and remote_sha != head_sha
    stat = None
    if changed and head_sha and _ref_sha(ctx.repo, head_sha):
        stat = _out(_git(ctx.repo, "diff", "--stat", head_sha, remote_sha, check=False))
    return {"found": True, "branch": branch, "job": path.parent.name, "plan": str(path), "pr": plan.get("pr"),
            "source": plan.get("source"), "schema_version": plan.get("schema_version"),
            "remote_sha": remote_sha, "remote_exists": bool(remote_sha), "remote_changed": changed,
            "remote_diff_stat": stat,
            "multiple": [str(p) for p, _ in found[1:]]}


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
    sub = parser.add_subparsers(dest="cmd", required=True)
    lock = sub.add_parser("lock")
    lock_sub = lock.add_subparsers(dest="lock_cmd", required=True)
    lock_sub.add_parser("status")
    p = lock_sub.add_parser("acquire")
    p.add_argument("job")
    p.add_argument("--command")
    p.add_argument("--take-over", action="store_true")
    p = lock_sub.add_parser("release")
    p.add_argument("job")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("snapshot")
    p.add_argument("--job", required=True)
    p = sub.add_parser("cleanup")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--yes", action="store_true")
    p.add_argument("--older-than", type=int, nargs="?", const=90, default=None, metavar="DAYS")
    p = sub.add_parser("preflight")
    p.add_argument("--branch", required=True)
    p.add_argument("--search")
    p.add_argument("--jira")
    p = sub.add_parser("stage")
    p.add_argument("plan")
    p.add_argument("--wt", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("summary")
    p.add_argument("wt")
    p = sub.add_parser("publish")
    p.add_argument("wt")
    p.add_argument("--branch", required=True)
    p.add_argument("--lease", required=True, help="원격 브랜치 SHA 또는 new(원격에 없어야 함)")
    p.add_argument("--approved", required=True)
    p = sub.add_parser("discard")
    p.add_argument("wt")
    p = sub.add_parser("find-plan")
    p.add_argument("--branch", required=True)
    _allow_common_anywhere(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    global _PLUGIN_ROOT
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    _PLUGIN_ROOT = args.plugin_root
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
        elif args.cmd == "cleanup":
            result = cleanup(ctx, args.yes, args.older_than)
        elif args.cmd == "preflight":
            result = preflight(ctx, args.branch, args.search, args.jira)
        elif args.cmd == "stage":
            result, code = stage(ctx, Path(args.plan), Path(args.wt), args.branch, args.dry_run)
        elif args.cmd == "summary":
            result = summary(ctx, Path(args.wt))
        elif args.cmd == "publish":
            result, code = publish(ctx, Path(args.wt), args.branch, args.lease, args.approved)
        elif args.cmd == "discard":
            result = discard(ctx, Path(args.wt))
        else:
            result = find_plan(ctx, args.branch)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        if exc.detail is not None:
            print(json.dumps(exc.detail, ensure_ascii=False, indent=1))
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
