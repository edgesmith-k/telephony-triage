import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import usage_stats  # noqa: E402

START = "2026-10-01T00:00:00+00:00"
START_EPOCH = 1790812800   # 2026-10-01T00:00:00Z


def _job(root: Path, key: str, plan: dict, answers: dict, files=()):
    d = root / key
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (d / "triage-state.json").write_text(json.dumps({"answers": answers}), encoding="utf-8")
    for f in files:
        (d / f).write_text("{}", encoding="utf-8")
    return d


def test_three_numbers_from_three_jobs(tmp_path):
    (tmp_path / "_snapshot").mkdir()
    done = _job(tmp_path, "A-1", {"started_at": START, "pr": {"number": 1}}, {"time": "x", "anchor": "off"})
    os.utime(done / "plan.json", (START_EPOCH + 1800, START_EPOCH + 1800))                          # PR까지 30분
    _job(tmp_path, "A-2", {"started_at": START}, {"time": "x", "year": "2026", "code": "c"})        # 취소
    _job(tmp_path, "A-3", {"started_at": START}, {}, files=["state.json"])                          # 진행 중
    s = usage_stats.stats(tmp_path)
    assert (s["cancelled"], s["started"], s["pr_jobs"]) == (1, 3, 1)
    assert s["pr_minutes"] == 30
    assert s["questions"] == (1 + 3 + 0) / 3
