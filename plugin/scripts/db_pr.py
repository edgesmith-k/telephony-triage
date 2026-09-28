#!/usr/bin/env python3
"""db_pr.py — 이슈 DB 쓰기 오케스트레이션 (contracts.md §3.2 `db_pr.py` 세부, 01-architecture.md §3.1).

Phase 6 범위: 세션 lock과 읽기 스냅샷. `cleanup`·`preflight`·`stage`·`summary`·`publish`·`discard`는
Phase 7에서 구현한다(지금은 종료 코드 2).

    db_pr.py lock status
    db_pr.py lock acquire <작업 키> [--command <이름>] [--take-over]
    db_pr.py lock release <작업 키> [--force]
    db_pr.py snapshot --job <작업 키>

세션 lock `<work_dir>/session.lock` = `{job, command, started_at, updated_at}` (사용자별로 한 번에 한 작업)
- 다른 작업 키의 lock이 있으면 종료 코드 2와 보유자 정보. 4시간 넘게 갱신되지 않은 lock은 만료로 보고 가져온다.
- 같은 작업 키: `updated_at`이 10분 이내면 다른 세션이 진행 중일 수 있으므로 종료 코드 2
  (사용자가 확인하면 `--take-over`로 이어받는다). 10분이 넘었으면 그대로 이어받는다.
- `release --force`는 보유자와 상관없이 푼다(사용자가 "그 세션은 끝났다"고 확인한 경우).
- 프로세스 생존 여부로 판단하지 않는다(스크립트는 호출마다 끝난다).

읽기 스냅샷 `snapshot --job <작업 키>`: `git -C <issue_db.path> fetch origin` → lock 확인(그 작업 키,
`updated_at` 갱신) → `<work_dir>/_snapshot`을 `origin/<base>`로 만들거나 옮긴다(detached worktree)
→ 사용자 clone의 현재 브랜치가 `<base>`이고 깨끗할 때만 `pull --ff-only`(아니면 건너뛰고 사유).
**사용자 clone에서 checkout은 하지 않는다.** 스냅샷은 읽기 전용이다(`.cache/`만 쓴다).

시각은 환경변수 `TT_NOW`(ISO, 테스트용)로 바꿀 수 있다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import site_defaults, userconfig  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402

LOCK_FILE = "session.lock"
SNAPSHOT_DIR = "_snapshot"
FRESH = timedelta(minutes=10)
EXPIRE = timedelta(hours=4)
PHASE7 = ("cleanup", "preflight", "stage", "summary", "publish", "discard")


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


class Lock:
    def __init__(self, work_dir: Path):
        self.work_dir = work_dir
        self.path = work_dir / LOCK_FILE

    def read(self) -> dict | None:
        if not self.path.is_file():
            return None
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def describe(self, data: dict | None) -> dict | None:
        if data is None:
            return None
        age = now() - _parse(data["updated_at"])
        return {**data, "expired": age > EXPIRE, "age_sec": int(age.total_seconds())}

    def write(self, data: dict) -> None:
        userconfig.ensure_private_dir(self.work_dir)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")

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
        data = {"job": job, "command": command or (held or {}).get("command"), "started_at": started,
                "updated_at": stamp}
        self.write(data)
        return {"acquired": True, "lock": self.describe(data),
                "taken_over": bool(taken_from), "previous": taken_from}

    def touch(self, job: str) -> dict:
        held = self.describe(self.read())
        if held is None or held["job"] != job or held["expired"]:
            raise UsageError(f"세션 lock이 작업 {job}의 것이 아닙니다. 먼저 lock acquire {job}를 한다.",
                             {"holder": held})
        held.update(updated_at=_iso(now()))
        self.write({k: held[k] for k in ("job", "command", "started_at", "updated_at")})
        return held

    def release(self, job: str, force: bool) -> dict:
        held = self.describe(self.read())
        if held is None:
            return {"released": False, "note": "lock이 없습니다"}
        if held["job"] != job and not force:
            raise UsageError(f"lock 보유자는 {held['job']}입니다. 그 세션이 끝났다면 --force로 푼다.", {"holder": held})
        self.path.unlink()
        return {"released": True, "previous": held, "forced": held["job"] != job}


# -- snapshot ---------------------------------------------------------------------------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
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
            "pulled": pulled, "pull_skipped_reason": reason}


# -- main -------------------------------------------------------------------------------


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
    for name in PHASE7:
        sub.add_parser(name).add_argument("rest", nargs="*")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    cfg = userconfig.merged(defaults)
    lock = Lock(Path(str(userconfig.get(cfg, "work_dir"))).expanduser())
    try:
        if args.cmd in PHASE7:
            raise UsageError(f"db_pr.py {args.cmd}은(는) Phase 7에서 구현한다.")
        if args.cmd == "snapshot":
            result = snapshot(args.job, cfg, lock)
        elif args.lock_cmd == "status":
            held = lock.describe(lock.read())
            result = {"held": held is not None, "lock": held}
        elif args.lock_cmd == "acquire":
            result = lock.acquire(args.job, args.command, args.take_over)
        else:
            result = lock.release(args.job, args.force)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        if exc.detail is not None:
            print(json.dumps(exc.detail, ensure_ascii=False, indent=1))
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
