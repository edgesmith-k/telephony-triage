"""git·스냅샷·작업 컨텍스트(`Ctx`)·worktree 준비/제거·discard·cleanup."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import compat, dbpath, userconfig, yamlio
from common.buildname import is_valid_branch_name
from common import checks as checks_mod
from common import ghcli

from .lock import (JOB_KEY_RE, Lock, PASTED_STEPS, PLAN, SNAPSHOT_DIR, SNAPSHOT_META, STAGE, STATE, TOOL_PREFIX,
                   UsageError, WORK_FILES, _iso, _read_json, _write_json, now, trace_note)


# -- snapshot ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    # 비대화(B-18): 인증 실패가 자격 증명 프롬프트로 120초 매달리지 않고 바로 실패로 보고되게
    env = {**(os.environ if env is None else env), "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=120, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise UsageError("git 시간 초과 (120초). 원격·로컬 상태를 확인한 뒤 재개한다.") from exc
    except OSError as exc:
        raise UsageError(f"git 실행 실패: {exc}") from exc
    if check and proc.returncode != 0:
        raise UsageError(f"git {' '.join(args)} 실패: {proc.stderr.strip()}")
    return proc


def ref_platform_mismatch(repo: Path, ref: str, platform: str) -> list[dict] | None:
    """`<ref>:issue-db.config.yaml`의 플랫폼 선언과 `platform` 대조 → 불일치 사유 목록(같으면 []). 읽을 수 없으면 None."""
    proc = _git(repo, "show", f"{ref}:issue-db.config.yaml", check=False)
    if proc.returncode != 0:
        return None
    try:
        data = yamlio.safe_load(proc.stdout)
    except Exception:   # noqa: BLE001 — YAML 오류는 대조 불가(뒤의 파일 대조·lint가 본다)
        return None
    return compat.check_platform(data if isinstance(data, dict) else {}, platform)


def _platform_error(mismatch: list[dict], where: str) -> UsageError:
    return UsageError(mismatch[0]["message"], {"code": mismatch[0]["code"], "db": where})


def clone_path(cfg: dict) -> Path:
    """`issue_db.path`의 사용자 clone. 비었거나 절대 경로가 아니거나 이슈 DB 표식이 없으면 git을 부르기 전에 UsageError —
    빈 값은 `Path("")`=현재 폴더라 무관한 저장소를 이슈 DB로 쓰게 된다(V10-01)."""
    raw = str(userconfig.get(cfg, "issue_db.path") or "")
    repo = Path(raw).expanduser()
    if not repo.is_absolute() or not (repo / dbpath.CONFIG).is_file():
        raise UsageError(f"issue_db.path가 이슈 DB clone이 아니다(설정 없음·빈 값·상대 경로·{dbpath.CONFIG} 없음): "
                         f"{raw or '(없음)'}. /telephony-triage:setup을 먼저 한다(setup 3에서 clone한다). "
                         "clone이 있으면 표식이 있는 브랜치를 checkout하고 있는지 본다.")
    if not (repo / ".git").exists():
        raise UsageError(f"issue_db.path가 git clone이 아닙니다: {repo} (setup 3에서 clone한다)")
    return repo


def snapshot(job: str, cfg: dict, lock: Lock) -> dict:
    repo = clone_path(cfg)
    base = userconfig.get(cfg, "issue_db.base_branch") or "main"
    fetch = _git(repo, "fetch", "origin")
    lock.touch(job)
    ref = f"origin/{base}"
    snap = lock.work_dir / SNAPSHOT_DIR
    platform = userconfig.platform_of(cfg)
    # 플랫폼 선언은 worktree를 만들기 전에 원격 ref에서 대조한다(다른 플랫폼 clone에 worktree를 남기지 않게)
    mismatch = ref_platform_mismatch(repo, ref, platform)
    if mismatch:
        raise _platform_error(mismatch, f"{repo} ({ref})")
    _git(repo, "worktree", "prune")
    created = False
    if (snap / ".git").exists():
        here = _git(snap, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).stdout.strip()
        want = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir", check=False).stdout.strip()
        if here and want and Path(here).resolve() != Path(want).resolve():
            raise UsageError(f"{snap}는 다른 clone({here})의 worktree다(issue_db.path를 바꿨다). 그 clone에서 "
                             f"`git worktree remove --force {snap}`로 지운 뒤 다시 snapshot한다.")
        _git(snap, "checkout", "--detach", "-f", ref)
    else:
        if snap.exists() and any(snap.iterdir()):
            raise UsageError(f"{snap}가 worktree가 아닌데 비어 있지 않습니다. 확인 후 지운다.")
        _git(repo, "worktree", "add", "--detach", str(snap), ref)
        created = True
    sha = _git(snap, "rev-parse", "HEAD").stdout.strip()
    mismatch = compat.check_platform(compat.load_db_config(snap), platform)
    if mismatch:      # 원격 ref를 읽지 못했을 때의 대조. 이번에 만든 worktree는 지운다
        if created:
            _git(repo, "worktree", "remove", "--force", str(snap), check=False)
        raise _platform_error(mismatch, str(snap))
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
    dups = [e for e in errors if e.get("code") in ("duplicate-id", "duplicate-issue")]
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
        clone_path(self.cfg)

    def pending_dir(self) -> Path:
        return userconfig.pending_feedback_dir(self.cfg)


def abs_wt(wt) -> Path:
    """작업 경로의 절대 경로(`_job_of`와 같은 기준). resolve하지 않는다 — symlink인 상위 경로에서 검사가 어긋난다. `--wt .`(wt 안에서
    실행)도 된다: `Path('.').name`은 빈 글이라 `job_dir / Path(wt).name`으로 다시 만들면 job_dir이 된다."""
    return Path(wt).expanduser().absolute()


def _job_of(wt: Path, ctx: Ctx) -> tuple[Path, str]:
    wt = abs_wt(wt)
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
    wt = abs_wt(wt)        # 절대 경로로: `git -C <clone>`이 상대 경로를 clone 기준으로 풀지 않게
    # wt의 hook(post-checkout·reference-transaction 등 — 모델이 쓸 수 있는 `.githooks`)을 돌리지 않는다 (리뷰 10a Q-2).
    # commit·push의 검증 hook은 이 함수 밖이라 그대로 돈다
    nohook = ("-c", f"core.hooksPath={os.devnull}")
    if (wt / ".git").exists():
        _owned_worktree(ctx, wt)
        # `-ffdx`: 무시된 파일·중첩 저장소까지. 남으면 계획 적용·검사·확인 화면이 그것이 있는 트리에서 돈다(무시된 `.gitattributes`가
        # diff를 가린다 — 리뷰 10a Q-1). 대상은 위에서 확인한 도구 worktree뿐이고, 계획 적용 전이라 stage가 만들 파일은 아직 없다
        for args in (("checkout", "-f", "-B", tool, base_sha), ("reset", "--hard", base_sha), ("clean", "-ffdx")):
            _git(wt, *nohook, *args)
        return "reapplied"
    if wt.exists() and any(wt.iterdir()):
        raise UsageError(f"{wt}가 worktree가 아닌데 비어 있지 않습니다. 확인 후 지운다 (db_pr cleanup).")
    _git(ctx.repo, *nohook, "worktree", "add", "--no-track", "-B", tool, str(wt), base_sha)
    return "created"


# -- discard / cleanup ---------------------------------------------------------------------


def _remove_worktree(ctx: Ctx, path: Path) -> None:
    _job_of(path, ctx)
    path = abs_wt(path)     # 절대 경로로 (`_prepare_worktree`와 같게)
    _owned_worktree(ctx, path)
    _git(ctx.repo, "worktree", "remove", "--force", str(path))


def _discard_outcome(job_dir: Path) -> str | None:
    """discard 사유(usage_stats): push 기록 있음 after-publish · dry-run stage dry-run · 그 밖 cancel. 못 읽으면 None."""
    try:
        if ((_read_json(job_dir / PLAN) or {}).get("pr") or {}).get("head_sha"):
            return "after-publish"
        return "dry-run" if (_read_json(job_dir / STAGE) or {}).get("dry_run") else "cancel"
    except (OSError, ValueError, AttributeError):
        return None


def discard(ctx: Ctx, wt: Path) -> dict:
    job_dir, job = _job_of(wt, ctx)
    wt = abs_wt(wt)
    git_skipped = None
    try:
        clone_path(ctx.cfg)
    except UsageError as exc:
        if wt.exists():     # clone에 등록된 worktree일 수 있다: 상태 파일·lock을 그대로 두고 멈춘다(고아 worktree를 만들지 않게)
            raise UsageError(f"{exc} 작업 worktree가 남아 있어 아무것도 지우지 않았다: {wt} — issue_db.path를 바로잡은 뒤 "
                             "discard를 다시 한다.") from exc
        git_skipped = str(exc)     # worktree가 없으면 git만 건너뛰고 작업 파일 삭제·lock 해제는 끝까지 간다
    ctx.lock.touch(job)
    try:
        state = _read_json(job_dir / STATE) or {}
    except ValueError:      # 손상된 state.json(JSON·UTF-8 아님): 브랜치는 worktree HEAD로 찾고 정리·lock 해제는 끝까지 간다
        state = {}
    if not isinstance(state, dict):     # 매핑이 아닌 state.json(예 `[1]`)도 손상으로 본다
        state = {}
    branch = state.get("branch")
    if not branch and (wt / ".git").exists():
        head = _out(_git(wt, "symbolic-ref", "--short", "HEAD", check=False))
        branch = head[len(TOOL_PREFIX):] if head.startswith(TOOL_PREFIX) else None
    removed = []
    if wt.exists():
        _remove_worktree(ctx, wt)
        removed.append(str(wt))
    deleted_branch = None
    if git_skipped is None:
        _git(ctx.repo, "worktree", "prune", check=False)
        if branch and _ref_sha(ctx.repo, f"refs/heads/{TOOL_PREFIX}{branch}"):
            _git(ctx.repo, "branch", "-D", TOOL_PREFIX + branch)
            deleted_branch = TOOL_PREFIX + branch
    elif branch:
        git_skipped += f" 도구 브랜치 {TOOL_PREFIX}{branch}가 clone에 남았을 수 있다(바로잡은 뒤 cleanup)."
    trace_note(job_dir, "discard", outcome=_discard_outcome(job_dir))
    for name in WORK_FILES:
        (job_dir / name).unlink(missing_ok=True)
    released = ctx.lock.release(job, force=False)
    out = {"discarded": True, "job": job, "removed_worktrees": removed, "deleted_branch": deleted_branch,
           "lock": released, "plan_kept": (job_dir / PLAN).is_file()}
    if git_skipped:
        out["git_skipped"] = git_skipped
    return out


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


from common.session_lock import JOB_MARKERS, LEGACY_JOB_FILES, tree_mtime  # noqa: E402,F401 — job_status·doctor와 공유
RAW_MARKERS = ("logs", "issue_raw.json", "jira_raw.json")
RETAINED_NOTES = {      # PR 생성 실패라고 단정하지 않는다: PR은 만들어졌는데 번호만 기록되지 않았을 수 있다
    "unpublished": "미게시 계획 보존 — 재개 또는 명시적 폐기(discard) 필요",
    "pushed-no-pr": "push 기록 있음, PR 연결 미확인 — 원격 브랜치·열린 PR 확인 후 publish 재시도 또는 "
                    "`sync-pr <브랜치>`로 복구(discard는 복구가 아니라 중단·로컬 정리)",
    "unreadable": "plan.json 읽기 실패 — 원격 브랜치·열린 PR 확인 전 지우지 않는다",
}


def _tree_mtime(job_dir: Path) -> float:
    """마지막 활동 시각 — doctor `retention` 행과 같은 정의(`session_lock.tree_mtime`)."""
    return tree_mtime(job_dir)


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
            try:
                plan = _read_json(job_dir / PLAN)
            except ValueError:      # JSONDecodeError·UnicodeDecodeError: 손상된 계획도 지우지 않는다
                plan = False
            number = (plan.get("pr") or {}).get("number") if isinstance(plan, dict) else None
            if not number and plan is not None:     # 미게시 계획: 일괄 정리에서 빼고 따로 알린다 (S14에서 원문 보존 결정)
                if not isinstance(plan, dict):      # 읽지 못한 계획(손상·매핑 아님): PR 여부를 모른다
                    kept = "unreadable"
                else:                               # branch는 계획을 만들 때부터 있다(스키마 필수)
                    kept = "pushed-no-pr" if (plan.get("pr") or {}).get("head_sha") else "unpublished"
                retained.append({"job": job_dir.name, "path": str(job_dir), "days": (now() - datetime.fromtimestamp(
                    mtime, timezone.utc)).days, "raw_remains": any((job_dir / m).exists() for m in RAW_MARKERS),
                    "state": kept, "note": RETAINED_NOTES[kept]})
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
