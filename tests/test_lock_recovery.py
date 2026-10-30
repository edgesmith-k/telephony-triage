#!/usr/bin/env python3
"""손상된 `session.lock` 복구 (06-collaboration.md, contracts.md §3.2 db_pr lock).

- 손상 lock에서 `lock release <작업 키>`는 종료 코드 2이고 파일을 그대로 둔다
- 사용자가 `--force`를 명시해야 `session.lock.corrupt-<ts>`로 옮기고(지우지 않음) 푼다. 그 뒤 `acquire`가 된다
- `acquire`는 손상 lock을 자동으로 넘어가지 않는다 (lock 우회 금지)
- 같은 owner(TT_LOCK_OWNER = 보유 owner)의 재획득은 재진입(`reacquired`, owner·started_at 유지, 시각만 갱신)이다.
  owner 없이·다른 owner로는 그대로 `--take-over`가 필요하다. owner 불일치 release는 "풀리지 않았다"고 말하고 파일을 둔다.
  출력의 holder·previous owner는 앞 4자만 보인다

`pytest tests/test_lock_recovery.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from workspace import Workspace  # noqa: E402


def test_release_force_backs_up_corrupt_lock():
    ws = Workspace(build=False)
    ws.acquire("MOCK-1101")
    lock = ws.work / "session.lock"
    lock.write_text("{손상", encoding="utf-8")

    proc = ws.run("db_pr.py", ["lock", "acquire", "MOCK-1101", "--take-over"])
    assert proc.returncode == 2 and "session.lock" in proc.stderr and "Traceback" not in proc.stderr
    proc = ws.run("db_pr.py", ["lock", "release", "MOCK-1101"])
    assert proc.returncode == 2 and "--force" in proc.stderr and "Traceback" not in proc.stderr
    assert lock.read_text(encoding="utf-8") == "{손상"

    out = ws.db_pr("lock", "release", "MOCK-1101", "--force", env={"TT_NOW": "2099-01-02T03:04:05Z"})
    assert out["released"] is True and out["corrupt"] is True and out["forced"] is True and out["previous"] is None
    backups = list(ws.work.glob("session.lock.corrupt-*"))
    assert [p.name for p in backups] == ["session.lock.corrupt-20990102T030405Z"] and out["backup"] == str(backups[0])
    assert backups[0].read_text(encoding="utf-8") == "{손상"
    assert not lock.exists() and (ws.work / "session.guard").exists()

    assert ws.db_pr("lock", "status")["held"] is False            # 백업은 lock으로 읽지 않는다
    assert ws.acquire("MOCK-1102")["acquired"] is True

    # 같은 초에 또 깨지면 앞 백업을 덮지 않고 -1, -2를 붙인다
    for n in (1, 2):
        lock.write_text(f"{{손상{n}", encoding="utf-8")
        out = ws.db_pr("lock", "release", "MOCK-1102", "--force", env={"TT_NOW": "2099-01-02T03:04:05Z"})
        assert out["backup"].endswith(f"session.lock.corrupt-20990102T030405Z-{n}")
    assert sorted(p.read_text(encoding="utf-8") for p in ws.work.glob("session.lock.corrupt-*")) == \
        ["{손상", "{손상1", "{손상2"]


J = "MOCK-1001"


def test_same_owner_reacquire_is_reentrant():
    ws = Workspace(build=False)
    first = ws.db_pr("lock", "acquire", J, "--command", "record", env={"TT_NOW": "2026-09-29T09:00:00Z"})
    owner = first["lock"]["owner"]
    again = ws.db_pr("lock", "acquire", J, "--command", "record",
                     env={"TT_LOCK_OWNER": owner, "TT_NOW": "2026-09-29T09:03:00Z"})      # 10분 이내여도
    assert again["acquired"] is True and again["reacquired"] is True and again["taken_over"] is False
    assert again["lock"]["owner"] == owner and again["lock"]["started_at"] == "2026-09-29T09:00:00Z"
    assert again["lock"]["updated_at"] == "2026-09-29T09:03:00Z"
    late = ws.db_pr("lock", "acquire", J, env={"TT_LOCK_OWNER": owner, "TT_NOW": "2026-09-29T15:00:00Z"})   # 만료 뒤도
    assert late["reacquired"] is True and late["lock"]["owner"] == owner and late["lock"]["command"] == "record"
    assert ws.db_pr("lock", "release", J, env={"TT_LOCK_OWNER": owner})["released"] is True


def test_release_without_owner_keeps_lock_and_says_so():
    ws = Workspace(build=False)
    owner = ws.db_pr("lock", "acquire", J, "--command", "record")["lock"]["owner"]
    lock = ws.work / "session.lock"
    before = lock.read_text(encoding="utf-8")
    for bad in ("", "stale-owner"):
        proc = ws.run("db_pr.py", ["lock", "release", J], env={"TT_LOCK_OWNER": bad})
        assert proc.returncode == 2 and "풀리지 않았다" in proc.stderr and "--force" in proc.stderr
        detail = json.loads(proc.stdout)
        assert detail["released"] is False and detail["holder"]["owner"] == owner[:4] + "…"
        assert lock.read_text(encoding="utf-8") == before
    # 다른 세션(owner 없음)의 재획득은 여전히 이어받기 확인이 필요하다
    proc = ws.run("db_pr.py", ["lock", "acquire", J, "--command", "record"], env={"TT_LOCK_OWNER": ""})
    assert proc.returncode == 2 and "--take-over" in proc.stderr and "TT_LOCK_OWNER" in proc.stderr
    assert owner not in proc.stdout and json.loads(proc.stdout)["holder"]["owner"] == owner[:4] + "…"
    proc = ws.run("db_pr.py", ["lock", "acquire", "MOCK-1002"], env={"TT_LOCK_OWNER": ""})    # 다른 작업
    assert proc.returncode == 2 and owner not in proc.stdout


def test_acquire_after_proper_release_needs_no_takeover():
    ws = Workspace(build=False)
    owner = ws.db_pr("lock", "acquire", J, "--command", "record")["lock"]["owner"]
    ws.db_pr("lock", "release", J, env={"TT_LOCK_OWNER": owner})
    out = ws.db_pr("lock", "acquire", J, "--command", "record", env={"TT_LOCK_OWNER": ""})
    assert out["acquired"] is True and out["taken_over"] is False and out["lock"]["owner"] != owner


def test_take_over_output_masks_previous_owner():
    ws = Workspace(build=False)
    owner = ws.db_pr("lock", "acquire", J)["lock"]["owner"]
    proc = ws.run("db_pr.py", ["lock", "acquire", J, "--take-over"], env={"TT_LOCK_OWNER": ""})
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["taken_over"] is True and owner not in proc.stdout
    assert out["previous"]["owner"] == owner[:4] + "…" and out["lock"]["owner"] != owner


if __name__ == "__main__":
    test_release_force_backs_up_corrupt_lock()
    test_same_owner_reacquire_is_reentrant()
    test_release_without_owner_keeps_lock_and_says_so()
    test_acquire_after_proper_release_needs_no_takeover()
    test_take_over_output_masks_previous_owner()
    print("ok")
