#!/usr/bin/env python3
"""손상된 `session.lock` 복구 (06-collaboration.md, contracts.md §3.2 db_pr lock).

- 손상 lock에서 `lock release <작업 키>`는 종료 코드 2이고 파일을 그대로 둔다
- 사용자가 `--force`를 명시해야 `session.lock.corrupt-<ts>`로 옮기고(지우지 않음) 푼다. 그 뒤 `acquire`가 된다
- `acquire`는 손상 lock을 자동으로 넘어가지 않는다 (lock 우회 금지)

`pytest tests/test_lock_recovery.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

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


if __name__ == "__main__":
    test_release_force_backs_up_corrupt_lock()
    print("ok")
