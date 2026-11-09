"""`tools/team_stats.py`: usage_stats --json(format 2) 파일 여러 개 → 팀 표·합계 (15-local-draft.md §15.5 S-7, 종합 리뷰 C 제안)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import team_stats  # noqa: E402


def _doc(jobs, pr, analysis_only, cancel, pr_vals, an_vals, q_jobs, q_total, runs, tokens, *, cancelled=1, in_progress=0,
         practice=0, unknown=0, inv_vals=None):
    """usage_stats --json(format 2) 실제 모양: states 9종, cancel_ratio = cancelled / (jobs − in_progress − practice − unknown),
    tokens = None(--transcripts 없음) 또는 {dir, sessions, …, total: {calls, input, output, cache_read, cache_write} | None}."""
    base = jobs - in_progress - practice - unknown
    return {"format": 2, "platform": None, "work_dir": "/x", "jobs": jobs,
            "states": {"pr": pr, "pushed": 0, "in_progress": in_progress, "practice": practice, "cancelled": cancelled, "held": 0,
                       "analysis_only": analysis_only, "no_result": 0, "unknown": unknown},
            "cancel_ratio": cancel if cancel is not None else (round(cancelled / base, 3) if base > 0 else None),
            "pr_minutes": {"n": len(pr_vals), "median": None, "mean": None, "values": pr_vals},
            "analysis_minutes": {"n": len(an_vals), "median": None, "mean": None, "values": an_vals},
            **({} if inv_vals is None else {"investigation_minutes": {"n": len(inv_vals), "median": None, "mean": None,
                                                                      "values": inv_vals}, "investigation_unmeasured": 0}),
            "questions": {"jobs": q_jobs, "total": q_total, "per_job": None, "by_kind": {}},
            "retries": {"runs": runs, "answer_reruns": 0, "errors": 0, "stages": 0, "stage_failed": 0},
            "legacy": {"jobs": 0, "stages": {}}, "other_flows": 0,
            "tokens": None if tokens is None else {"dir": "/p", "sessions": 3, "analyze_sessions": 1, "by_stage": {},
                                                   "total": None if tokens == "none" else
                                                   {"calls": 7, "input": tokens, "output": tokens // 10, "cache_read": tokens * 2,
                                                    "cache_write": 0},
                                                   "asks": 0, "usage_missing": 0}}


def test_team_table_and_totals(tmp_path):
    (tmp_path / "alice.json").write_text(json.dumps(_doc(10, 6, 2, None, [30, 50, 70], [10, 20], 8, 16, 3, 12000, cancelled=1,
                                                                         inv_vals=[40, 80])),
                                         encoding="utf-8")
    (tmp_path / "bob.json").write_text(json.dumps(_doc(5, 2, 1, None, [90], [5], 5, 5, 1, None, cancelled=2)), encoding="utf-8")
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
    # 전체 조사: bob 파일에는 키가 없다(옛 형식) — alice 값만 합친다
    assert total["investigation_median"] == 60.0 and total["investigation_n"] == 2
    assert out["users"][1]["investigation_minutes"] == []
    assert total["cancel_ratio"] == round(3 / 15, 3) and (total["cancelled"], total["cancel_base"]) == (3, 15)
    assert total["questions_per_job"] == round(21 / 13, 3) and total["retries"] == 4
    # 토큰 = 입력+출력+캐시 읽기+캐시 쓰기(12000+1200+24000+0), 응답 수 calls(7)는 더하지 않는다(코덱스 리뷰 N1)
    assert total["tokens"] == 37200 and total["tokens_users"] == 1
    assert total["tokens_detail"] == {"input": 12000, "output": 1200, "cache_read": 24000, "cache_write": 0}
    assert out["users"][0]["tokens"] == 37200 and out["users"][1]["tokens"] is None
    text = subprocess.run([sys.executable, str(REPO / "tools" / "team_stats.py"), str(tmp_path / "alice.json"),
                           str(tmp_path / "bob.json")], capture_output=True, text=True, encoding="utf-8").stdout
    assert text.startswith("팀 지표: 사용자 2명") and "합계" in text and "기준선" in text
    assert "alice" in text and "bob" in text and "작업 키" not in text
    cells = {ln.split()[0]: ln.split() for ln in text.splitlines()[3:6]}     # 데이터 칸에는 띄어쓰기가 없다
    col = team_stats.COLUMNS.index("전체 조사 중앙값(분)")
    assert "전체 조사 중앙값(분)" in text and "전체 조사 2건" in text
    assert (cells["alice"][col], cells["bob"][col], cells["합계"][col]) == ("60", "-", "60")


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


def test_cancel_ratio_pools_counts_not_rounded_ratios():
    """코덱스 리뷰 N2: A = 연습 99 + 취소 1(개인 취소율 1.0), B = 분석만 100(0.0) → 팀 취소율은 1/101이지 50%가 아니다."""
    a = _doc(100, 0, 0, None, [], [], 0, 0, 0, None, cancelled=1, practice=99)
    b = _doc(100, 0, 100, None, [], [], 0, 0, 0, None, cancelled=0)
    rows = [team_stats.read_one_doc(a, "a"), team_stats.read_one_doc(b, "b")]
    assert rows[0]["cancel_ratio"] == 1.0 and rows[1]["cancel_ratio"] == 0.0
    total = team_stats.summarize(rows)
    assert (total["cancelled"], total["cancel_base"], total["cancel_users"]) == (1, 101, 2) and total["cancel_ratio"] == round(1 / 101, 3)
    # 상태 건수가 없는 옛 파일은 팀 비율에서 빠지고(개인 비율은 그대로 보임), 분모 0이면 None
    legacy = {"format": 2, "jobs": 3, "states": {"pr": 1}, "cancel_ratio": 0.5}
    row = team_stats.read_one_doc(legacy, "old")
    assert row["cancelled"] is None and row["cancel_ratio"] == 0.5
    assert team_stats.summarize([row])["cancel_ratio"] is None and team_stats.summarize([row])["cancel_users"] == 0
    zero = _doc(2, 0, 0, None, [], [], 0, 0, 0, None, cancelled=0, in_progress=2)
    assert team_stats.summarize([team_stats.read_one_doc(zero, "z")])["cancel_ratio"] is None


def test_tokens_unmeasured_stays_unmeasured_and_calls_not_added():
    """코덱스 리뷰 N1·F5: 생산자 total이 null(대상 세션·usage 없음)이거나 tokens가 null이면 미측정(-)이고 0이 아니다."""
    none_total = team_stats.read_one_doc(_doc(1, 0, 0, None, [], [], 0, 0, 0, "none"), "u")
    assert none_total["tokens"] is None and none_total["tokens_detail"] is None
    real = team_stats.read_one_doc(_doc(1, 0, 0, None, [], [], 0, 0, 0, 100), "v")
    assert real["tokens_detail"] == {"input": 100, "output": 10, "cache_read": 200, "cache_write": 0} and real["tokens"] == 310
    legacy_number = {"format": 2, "jobs": 1, "states": {}, "tokens": {"total": 12000}}          # 옛 가짜 모양: 숫자 total
    assert team_stats.read_one_doc(legacy_number, "w")["tokens"] is None
    total = team_stats.summarize([none_total, real])
    assert total["tokens"] == 310 and total["tokens_users"] == 1
    text = team_stats.render([none_total, real], total, [])
    assert "비용 아님" in text and "1명만 측정" in text
