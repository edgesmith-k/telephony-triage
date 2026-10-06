"""세션 lock·스냅샷 메타의 읽기 전용 부분 (contracts.md §3.2 db_pr 세부).

`db_pr`(쓰기 오케스트레이션)와 `config doctor`(읽기 전용 점검)가 함께 쓴다. 쓰기·획득·해제는 `db_pr`의 `Lock`에 있다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOCK_FILE = "session.lock"
SNAPSHOT_DIR = "_snapshot"
SNAPSHOT_META = "snapshot.json"   # `<work_dir>/snapshot.json` = {sha, base, at}
FRESH = timedelta(minutes=10)
EXPIRE = timedelta(hours=4)


class LockError(ValueError):
    """session.lock을 읽을 수 없다(손상)."""


def now() -> datetime:
    env = os.environ.get("TT_NOW")
    if env:
        return datetime.fromisoformat(env.replace("Z", "+00:00")).astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read(work_dir: Path) -> dict | None:
    path = Path(work_dir) / LOCK_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str)
                for k in ("job", "started_at", "updated_at")):
            raise ValueError("invalid lock record")
        parse(data["updated_at"])
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise LockError("session.lock을 읽을 수 없습니다. 손상된 lock을 확인한다.") from exc


def describe(data: dict | None) -> dict | None:
    if data is None:
        return None
    age = now() - parse(data["updated_at"])
    return {**data, "expired": age > EXPIRE, "age_sec": int(age.total_seconds())}
