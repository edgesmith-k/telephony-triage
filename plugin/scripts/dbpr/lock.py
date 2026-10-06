"""상수·`UsageError`·세션 lock(`Lock`)·JSON 읽기/쓰기."""

from __future__ import annotations

import json
import os
import re
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
PASTED_STEPS = "steps-pasted.txt"   # 개발자가 붙여넣은 스텝 목록 원문(08-safety.md §8.1) — 작업이 끝나면 지운다
WORK_FILES = (STATE, STAGE, PR_FILE, REGRESS, PASTED_STEPS)
JOB_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
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


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
