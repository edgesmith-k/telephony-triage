"""세션 lock·스냅샷 메타의 읽기 전용 부분 (contracts.md §3.2 db_pr 세부).

`db_pr`(쓰기 오케스트레이션)와 `config doctor`(읽기 전용 점검)가 함께 쓴다. 쓰기·획득·해제는 `db_pr`의 `Lock`에 있다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOCK_FILE = "session.lock"
SNAPSHOT_DIR = "_snapshot"
SNAPSHOT_META = "snapshot.json"   # `<work_dir>/snapshot.json` = {sha, base, at}
FRESH = timedelta(minutes=10)
EXPIRE = timedelta(hours=4)
# 작업 키(`<work_dir>/<작업 키>/` 폴더 이름): 트래커 키(analyze·record) 또는 fix-submit-<원인 ID>·verify-fix-…·verify-res-…·
# 브랜치 이름 기반 키(contracts.md `db_pr.py` 세부·reference/verify.md). `/`·`\`·선두 `.`·`_`를 막는다(경로 안전)
JOB_KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# 개명 전 작업 파일(jira_raw.json·jira.json·jira_meta.json)도 표식으로 본다 — 옛 JOB도 cleanup 대상·원문 잔여로 보이게(방어)
LEGACY_JOB_FILES = ("jira_raw.json", "jira.json", "jira_meta.json")
JOB_MARKERS = ("plan.json", "state.json", "trace.jsonl", "issue_raw.json", "triage-state.json",
               *LEGACY_JOB_FILES)   # logs/는 흔한 이름이라 표식이 아니다


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
        for key in ("updated_at", "started_at"):
            if parse(data[key]).tzinfo is None:     # 시각 계산이 aware 값끼리여야 한다
                raise ValueError("naive timestamp")
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise LockError("session.lock을 읽을 수 없습니다(손상). 그 세션이 끝났으면 "
                        "`db_pr lock release <작업 키> --force`가 `.corrupt-<ts>`로 백업하고 푼다.") from exc


def describe(data: dict | None) -> dict | None:
    if data is None:
        return None
    age = now() - parse(data["updated_at"])
    return {**data, "expired": age > EXPIRE, "age_sec": int(age.total_seconds())}


def is_job_dir(work_dir: Path, name: str) -> bool:
    """도구가 만든 작업 폴더 `<work_dir>/<name>/`: 이름이 작업 키 형식이고(경로 구분자·선두 `.` 없음) 표식 파일이 하나라도
    있다(트래커 키가 아닌 작업 키 판정 — job_status)."""
    if not isinstance(name, str) or not JOB_KEY_RE.fullmatch(name):
        return False
    path = Path(work_dir) / name
    try:
        return not path.is_symlink() and path.is_dir() and any((path / m).exists() for m in JOB_MARKERS)
    except OSError:
        return False


JOB_TREE_SKIP = ("wt", "draft")      # git worktree — 폴더 나이에 세지 않는다


def tree_mtime(job_dir: Path) -> float:
    """작업 폴더의 **마지막 활동** 시각 = 폴더 자신·하위 폴더·파일 중 가장 최근 mtime(방금 만든 빈 폴더나 옛 mtime 파일을 복사한
    폴더는 최근이다). 최상위 `wt`·`draft`(git worktree)는 건너뛴다. 훑는 도중 사라진 파일의 OSError는 무시한다.
    doctor `retention` 행과 `db_pr cleanup --older-than`이 같은 정의를 쓴다(코덱스 리뷰 R4: doctor는 폴더 mtime만 봐서 trace를
    방금 갱신한 작업을 "오래됨"으로 세고 cleanup은 최근으로 봤다)."""
    newest = job_dir.stat().st_mtime
    for root, dirs, files in os.walk(job_dir):
        if root == str(job_dir):
            dirs[:] = [d for d in dirs if d not in JOB_TREE_SKIP]
        for name in (*dirs, *files):
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
    return newest
