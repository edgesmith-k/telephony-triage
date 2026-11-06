"""`tools/team_stats.py`: usage_stats --json(format 2) 파일 여러 개 → 팀 표·합계 (15-local-draft.md §15.5 S-7, 종합 리뷰 C 제안)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import team_stats  # noqa: E402


def _doc(jobs, pr, analysis_only, cancel, pr_vals, an_vals, q_jobs, q_total, runs, tokens):
    return {"format": 2, "platform": None, "work_dir": "/x", "jobs": jobs,
            "states": {"pr": pr, "analysis_only": analysis_only, "cancelled": 1},
            "cancel_ratio": cancel,
            "pr_minutes": {"n": len(pr_vals), "median": None, "mean": None, "values": pr_vals},
            "analysis_minutes": {"n": len(an_vals), "median": None, "mean": None, "values": an_vals},
            "questions": {"jobs": q_jobs, "total": q_total, "per_job": None, "by_kind": {}},
            "retries": {"runs": runs, "answer_reruns": 0, "errors": 0, "stages": 0, "stage_failed": 0},
            "legacy": {"jobs": 0, "stages": {}}, "other_flows": 0,
            "tokens": None if tokens is None else {"total": tokens, "sessions": 3}}


def test_team_table_and_totals(tmp_path):
    (tmp_path / "alice.json").write_text(json.dumps(_doc(10, 6, 2, 0.1, [30, 50, 70], [10, 20], 8, 16, 3, 12000)), encoding="utf-8")
    (tmp_path / "bob.json").write_text(json.dumps(_doc(5, 2, 1, 0.4, [90], [5], 5, 5, 1, None)), encoding="utf-8")
    (tmp_path / "old.json").write_text(json.dumps({"format": 1, "jobs": 3}), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "team_stats.py"), "--json",
                           *(str(tmp_path / f) for f in ("alice.json", "bob.json", "old.json", "broken.json"))],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert [u["user"] for u in out["users"]] == ["alice", "bob"] and len(out["skipped"]) == 2
    total = out["total"]
    assert total["users"] == 2 and total["jobs"] == 15 and total["pr"] == 8 and total["analysis_only"] == 3
    assert total["pr_median"] == 60.0 and total["pr_n"] == 4 and total["analysis_median"] == 10.0
    assert total["cancel_ratio"] == round((0.1 * 10 + 0.4 * 5) / 15, 3)
    assert total["questions_per_job"] == round(21 / 13, 3) and total["retries"] == 4
    assert total["tokens"] == 12000 and total["tokens_users"] == 1
    text = subprocess.run([sys.executable, str(REPO / "tools" / "team_stats.py"), str(tmp_path / "alice.json"),
                           str(tmp_path / "bob.json")], capture_output=True, text=True, encoding="utf-8").stdout
    assert text.startswith("팀 지표: 사용자 2명") and "합계" in text and "기준선" in text
    assert "alice" in text and "bob" in text and "작업 키" not in text


def test_no_readable_file_is_exit_1(tmp_path):
    (tmp_path / "x.json").write_text("[]", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "team_stats.py"), str(tmp_path / "x.json")],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 1 and "format 2" in proc.stderr


def test_summarize_handles_missing_blocks():
    row, why = team_stats.read_one(Path("/nonexistent/u.json"))
    assert row is None and "읽을 수 없음" in why
    total = team_stats.summarize([{"user": "u", "jobs": 0, "pr": 0, "analysis_only": 0, "cancel_ratio": None, "pr_minutes": [],
                                   "analysis_minutes": [], "question_jobs": 0, "question_total": 0, "retries": 0, "tokens": None}])
    assert total["pr_median"] is None and total["cancel_ratio"] is None and total["questions_per_job"] is None and total["tokens"] is None
