import json
import os
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("pushed_files", [["state.json"], []])     # push 기록은 state.json 유무와 무관하게 취소가 아니다
def test_pr_counts_only_with_number_and_pushed_without_pr_is_separate(tmp_path, pushed_files):
    # pr.branch는 계획 시작부터 있으므로 pr 키 유무로 PR 완료를 판단하지 않는다
    _job(tmp_path, "B-1", {"started_at": START, "pr": {"number": None, "branch": "issue/MOCK-1", "head_sha": None}}, {})
    _job(tmp_path, "B-2", {"started_at": START, "pr": {"number": None, "branch": "issue/MOCK-2", "head_sha": "a" * 40}},
         {}, files=pushed_files)
    s = usage_stats.stats(tmp_path)
    assert (s["started"], s["pr_jobs"], s["cancelled"], s["pushed_no_pr"]) == (2, 0, 1, 1)
