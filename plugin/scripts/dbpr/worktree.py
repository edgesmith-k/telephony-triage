"""git·스냅샷·작업 컨텍스트(`Ctx`)·worktree 준비/제거·discard·cleanup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import userconfig
from common.buildname import is_valid_branch_name
from common import checks as checks_mod
from common import ghcli

from .lock import (JOB_KEY_RE, Lock, PASTED_STEPS, PLAN, SNAPSHOT_DIR, SNAPSHOT_META, STATE, TOOL_PREFIX, UsageError,
                   WORK_FILES, _iso, _read_json, _write_json, now)


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
    try:
        previous = _read_json(lock.work_dir / SNAPSHOT_META)
    except (OSError, ValueError):
        previous = None
    previous_sha = (previous.get("sha") if isinstance(previous, dict) and isinstance(previous.get("sha"), str)
                    and previous.get("base") == base else None)    # base 브랜치가 바뀌었으면 비교하지 않는다
    try:
        _write_json(lock.work_dir / SNAPSHOT_META, {"sha": sha, "base": base, "at": _iso(now())})
        meta_written = True
    except OSError:
        meta_written = False

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
            "previous_sha": previous_sha, "base_sha_changed": None if previous_sha is None else previous_sha != sha,
            "snapshot_meta_written": meta_written, "pulled": pulled, "pull_skipped_reason": reason, "post_lint": post_lint(snap)}


def post_lint(snap: Path) -> dict:
    """사후 lint (06-collaboration.md §6.3 ⑤). 보고만 한다."""
    code, data, err = run_script("db_lint.py", ["--all", "--db", str(snap)])
    if data is None:
        return {"ran": False, "error": _err_brief(err)}
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


def _err_brief(err: str, limit: int = 300) -> str:
    """하위 스크립트 stderr를 사용자에게 보일 만큼만. Traceback이면 마지막 줄만 내고 내부 오류로 표시한다."""
    text = (err or "").strip()
    if any(line.startswith("Traceback (most recent call last)") for line in text.splitlines()):
        last = next((line.strip() for line in reversed(text.splitlines()) if line.strip()), "")
        return f"{last} (내부 오류 — 스크립트 버그로 보고)"
    return text[:limit]


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


# -- stage 도우미 (stage는 publish.py) -----------------------------------------------------


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


def _drop_pasted_steps(ctx: Ctx, job: str) -> None:
    """자기 작업의 lock을 풀 때 붙여넣은 스텝 원문을 지운다(discard 없이 끝나는 경로, 08-safety.md §8.1)."""
    if not JOB_KEY_RE.fullmatch(job or ""):
        return
    job_dir = ctx.work_dir / job
    if job_dir.is_symlink() or not job_dir.is_dir():
        return
    try:
        (job_dir / PASTED_STEPS).unlink(missing_ok=True)
    except OSError:
        pass    # 지우지 못해도 lock 해제는 끝낸다(남은 파일은 cleanup이 보여준다)


JOB_MARKERS = (PLAN, "state.json", "trace.jsonl", "jira_raw.json", "triage-state.json")   # logs/는 흔한 이름이라 표식이 아니다
RAW_MARKERS = ("logs", "jira_raw.json")
RETAINED_NOTES = {      # PR 생성 실패라고 단정하지 않는다: PR은 만들어졌는데 번호만 기록되지 않았을 수 있다
    "unpublished": "미게시 계획 보존 — 재개 또는 명시적 폐기(discard) 필요",
    "pushed-no-pr": "push 기록 있음, PR 연결 미확인 — 원격 브랜치·열린 PR 확인 후 publish 재시도 또는 "
                    "`sync-pr <브랜치>`로 복구(discard는 복구가 아니라 중단·로컬 정리)",
}


def _tree_mtime(job_dir: Path) -> float:
    """폴더 자신·하위 폴더·파일 중 가장 최근 mtime(방금 만든 빈 폴더나 옛 mtime 파일을 복사한 폴더는 최근이다).
    git worktree(`wt`·`draft`)는 건너뛴다. 훑는 도중 사라진 파일의 OSError는 무시한다."""
    newest = job_dir.stat().st_mtime
    for root, dirs, files in os.walk(job_dir):
        if root == str(job_dir):
            dirs[:] = [d for d in dirs if d not in ("wt", "draft")]
        for name in (*dirs, *files):
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
    return newest


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
    retained = []
    if older_than is not None:
        limit = now() - timedelta(days=older_than)
        for job_dir in sorted(p for p in ctx.work_dir.iterdir() if p.is_dir()) if ctx.work_dir.is_dir() else []:
            # 도구가 만든 작업 폴더만: 작업 키 형식 + 표식(그 밖의 하위 폴더·`.` 폴더는 건드리지 않는다)
            if job_dir.name in (SNAPSHOT_DIR, held) or not JOB_KEY_RE.fullmatch(job_dir.name):
                continue
            if not any((job_dir / m).exists() for m in JOB_MARKERS):
                continue
            mtime = _tree_mtime(job_dir)
            if datetime.fromtimestamp(mtime, timezone.utc) > limit:
                continue
            plan = _read_json(job_dir / PLAN)
            number = ((plan or {}).get("pr") or {}).get("number")
            if not number and plan is not None:     # 미게시 계획: 일괄 정리에서 빼고 따로 알린다 (S14에서 원문 보존 결정)
                pushed = bool((plan.get("pr") or {}).get("head_sha"))   # branch는 계획을 만들 때부터 있다(스키마 필수)
                retained.append({"job": job_dir.name, "path": str(job_dir), "days": (now() - datetime.fromtimestamp(
                    mtime, timezone.utc)).days, "raw_remains": any((job_dir / m).exists() for m in RAW_MARKERS),
                    "state": "pushed-no-pr" if pushed else "unpublished",
                    "note": RETAINED_NOTES["pushed-no-pr" if pushed else "unpublished"]})
                continue
            if not number:      # 계획 없는 중단 작업(원문만 남음): 같은 기한이 지나면 디렉토리째
                targets.append({"kind": "job-dir", "job": job_dir.name, "path": str(job_dir), "pr": None,
                                "pr_state": None})
                continue
            proc = _gh(ctx, ["pr", "view", str(number), "--json", "state"], ctx.repo)
            state = (json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else {}).get("state")
            if state in ("MERGED", "CLOSED"):
                targets.append({"kind": "job-dir", "job": job_dir.name, "path": str(job_dir), "pr": number,
                                "pr_state": state})
    done, failed = [], []
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
                if Path(t["path"]).exists():      # 지우지 못했으면 지웠다고 보고하지 않는다
                    failed.append(t)
                    continue
            done.append(t)
        _git(ctx.repo, "worktree", "prune", check=False)
        for t in targets:
            if t["kind"] == "branch":
                _git(ctx.repo, "branch", "-D", t["name"], check=False)
    return {"dry_run": not yes, "lock_job": held, "targets": targets, "removed": done if yes else [],
            "failed": failed, "retained": retained}
