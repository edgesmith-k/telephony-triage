"""상수·`UsageError`·세션 lock(`Lock`)·JSON 읽기/쓰기."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

from common import userconfig
from common import session_lock


LOCK_FILE = session_lock.LOCK_FILE
SNAPSHOT_DIR = session_lock.SNAPSHOT_DIR
SNAPSHOT_META = session_lock.SNAPSHOT_META   # snapshot이 best-effort로 쓴다 (doctor가 나이를 읽는다)
FRESH = session_lock.FRESH
EXPIRE = session_lock.EXPIRE
STATE, STAGE, PR_FILE, REGRESS, PLAN = "state.json", "stage.json", "pr.json", "regress.json", "plan.json"
TRACE = "trace.jsonl"         # 작업 기록(triage Runner와 같은 파일). db_pr 행은 `v: 2`, script·args 없음
PASTED_STEPS = "steps-pasted.txt"   # 개발자가 붙여넣은 스텝 목록 원문(08-safety.md §8.1) — 작업이 끝나면 지운다
# draft-verify.json(common/draftcheck)은 작업 파일이 아니다: plan.json과 함께 남아 sync-pr 재적용·discard 뒤 재stage에서
# 작성 op가 그대로면 다시 묻지 않는다(지문이 다르면 stage가 멈춘다). cleanup --older-than은 폴더째 지운다
WORK_FILES = (STATE, STAGE, PR_FILE, REGRESS, PASTED_STEPS)
JOB_KEY_RE = session_lock.JOB_KEY_RE
TOOL_PREFIX = "tt/"


class UsageError(Exception):
    def __init__(self, message: str, detail: dict | None = None):
        super().__init__(message)
        self.detail = detail


now = session_lock.now
_iso = session_lock.iso
_parse = session_lock.parse


# -- lock -----------------------------------------------------------------------------


def _locked(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self.guard():
            return method(self, *args, **kwargs)
    return guarded


class Lock:
    """세션 lock. 플랫폼(이슈 DB)마다 그 플랫폼 `work_dir`에 따로 있다 — android·ofono 작업을 동시에 할 수 있다
    (사용자·이슈 DB별 한 번에 한 작업). 기록의 `platform`은 기본 플랫폼이 아닐 때만 넣는다(기존 기록 불변)."""

    def __init__(self, work_dir: Path, platform: str | None = None):
        self.work_dir = work_dir
        self.path = work_dir / LOCK_FILE
        self.owner = os.environ.get("TT_LOCK_OWNER")
        self.platform = platform if platform and platform != userconfig.TOP_PROFILE else None

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
            return session_lock.read(self.work_dir)
        except session_lock.LockError as exc:
            raise UsageError(str(exc)) from exc.__cause__

    def describe(self, data: dict | None) -> dict | None:
        return session_lock.describe(data)

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
        if held is not None and held["job"] == job and self.owner and self.owner == held.get("owner"):
            # 재진입: 이 세션(TT_LOCK_OWNER = 보유 owner)이 이미 잡은 lock — 만료 여부와 상관없이 owner·started_at 유지, 시각만 갱신
            data = {k: held[k] for k in ("job", "owner", "command", "started_at", "platform") if k in held}
            data.update(command=command or held.get("command"), updated_at=stamp)
            self.write(data)
            return {"acquired": True, "reacquired": True, "lock": self.describe(data), "taken_over": False,
                    "previous": None}
        if held is not None and not held["expired"]:
            if held["job"] != job:
                raise UsageError(f"다른 작업({held['job']}, {held.get('command')})이 lock을 갖고 있습니다. "
                                 "그 세션이 끝났는지 확인하고, 끝났으면 lock release <작업 키> --force로 푼다.",
                                 {"holder": mask_owner(held)})
            if now() - _parse(held["updated_at"]) <= FRESH and not take_over:
                who = ("이 세션이 잡은 lock이면 이 세션이 받은 acquire 결과의 lock.owner(lock status 값이 아님)를 TT_LOCK_OWNER로 주고 다시 acquire한다(이어받기 불필요). "
                       if not self.owner else "TT_LOCK_OWNER가 보유 owner와 다르다(다른 세션). ")
                raise UsageError(f"같은 작업({job})의 lock이 {held['age_sec']}초 전에 갱신됐습니다. 다른 세션이 "
                                 f"진행 중일 수 있다. {who}사용자가 확인하면 --take-over로 이어받는다.",
                                 {"holder": mask_owner(held)})
        taken_from = mask_owner(held)
        started = held["started_at"] if (held and held["job"] == job) else stamp
        self.owner = uuid.uuid4().hex
        data = {"job": job, "owner": self.owner, "command": command or (held or {}).get("command"), "started_at": started,
                "updated_at": stamp}
        if self.platform:
            data["platform"] = self.platform
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
                             {"holder": mask_owner(held)})
        self.check_owner(held)
        held.update(updated_at=_iso(now()))
        self.write({k: held[k] for k in ("job", "owner", "command", "started_at", "updated_at", "platform") if k in held})
        return held

    def check_owner(self, held: dict) -> None:
        if not self.owner or self.owner != held.get("owner"):
            raise UsageError("lock owner 불일치: acquire 결과 lock.owner를 TT_LOCK_OWNER로 전달한다.")

    @_locked
    def release(self, job: str, force: bool) -> dict:
        try:
            held = self.describe(session_lock.read(self.work_dir))
        except session_lock.LockError as exc:
            if not force:
                raise UsageError(f"session.lock을 읽을 수 없습니다(손상): {self.path}. 내용을 확인한 뒤 그 세션이 끝났으면 "
                                 f"lock release {job} --force로 백업(.corrupt-<ts>)하고 제거한다.") from exc.__cause__
            # 지우지 않고 옮긴다: 어떤 세션이 쓰다 깨졌는지 나중에 볼 수 있게. acquire·touch는 손상 lock에서 계속 실패한다.
            stem = f"{LOCK_FILE}.corrupt-{_iso(now()).replace('-', '').replace(':', '')}"
            backup, n = self.work_dir / stem, 0
            while backup.exists():               # 같은 초에 또 깨진 lock: 앞 백업을 덮지 않는다
                n += 1
                backup = self.work_dir / f"{stem}-{n}"
            os.replace(self.path, backup)
            return {"released": True, "forced": True, "corrupt": True, "backup": str(backup), "previous": None}
        if held is None:
            return {"released": False, "note": "lock이 없습니다"}
        if held["job"] != job and not force:
            raise UsageError(f"lock은 풀리지 않았다 — lock 보유자는 {held['job']}입니다. 그 세션이 끝났다면 --force로 푼다.",
                             {"released": False, "holder": mask_owner(held)})
        if not force and (not self.owner or self.owner != held.get("owner")):
            raise UsageError("lock owner 불일치: lock은 풀리지 않았다(session.lock 그대로). acquire 결과의 lock.owner를 "
                             "TT_LOCK_OWNER로 주고 다시 release한다. 그 세션이 끝났다고 사용자가 확인하면 --force로 푼다.",
                             {"released": False, "holder": mask_owner(held)})
        self.path.unlink()
        return {"released": True, "previous": mask_owner(held), "forced": held["job"] != job}


def mask_owner(held: dict | None) -> dict | None:
    """출력용 사본: owner 토큰은 앞 4자만 (토큰은 acquire 결과로만 전달한다 — 출력·lock 파일에서 다시 읽어 쓰지 않는다)."""
    if not held or not held.get("owner"):
        return held
    return {**held, "owner": str(held["owner"])[:4] + "…"}


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def trace_note(job_dir: Path, step: str, **fields) -> None:
    """`JOB/trace.jsonl`에 사건 한 줄 `{ts, step, v: 2, …}`(append, contracts.md §3.2 작업 기록). 채점기 trace()는 script 있는
    행만 세므로 여기 행은 보이지 않는다. 쓰지 못하면 stderr 경고만 — 종료 코드·stdout은 호출한 명령 그대로."""
    try:
        with (Path(job_dir) / TRACE).open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({"ts": _iso(now()), "step": step, "v": 2, **fields}, ensure_ascii=False) + "\n")
    except (OSError, ValueError) as exc:     # ValueError: 인코딩할 수 없는 글(서로게이트) — 원래 오류를 가리지 않는다
        print(f"[telephony-triage] 작업 기록을 쓰지 못함({step}: {type(exc).__name__}) — 운영 지표(usage_stats)에서 빠진다",
              file=sys.stderr)
