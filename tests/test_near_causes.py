#!/usr/bin/env python3
"""조사 모드 DB 원인 후보(반입 7 B-1·B-2): run의 analysis.json `near_causes`(부분 일치 + 요약 문장 검색, ≤ 3), 4KB 맞춤에서 맨 먼저
빠짐, check-output 탐색 `후보 확인:` 칸(없으면 형식 경고만, 인용은 원문 검사). 합성 로그·공개 표본 DB만(모델 실행 없음)."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, run_json  # noqa: E402
from triagelib import report  # noqa: E402

DATA_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
WORDS_ONLY = "낱말 일치만(로그 대조 안 함)"


def _offline(tmp_path: Path, lines: list[str], summary: str, monkeypatch, db: Path = SAMPLE) -> tuple[dict, Path]:
    monkeypatch.setenv("TT_SCHEMA_CHECK", "1")
    log = tmp_path / "radio.log"
    log.write_text("".join(lines), encoding="utf-8")
    meta = tmp_path / "m.json"
    meta.write_text(json.dumps({"key": "MOCK-1001", "occurred_at": "2026-09-20T14:32:10+09:00", "summary": summary},
                               ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    result = run_json("triage.py", ["run", "MOCK-1001", "--offline-db", db, "--out", out, "--logs", log,
                                    "--issue-meta", meta, "--tz", "Asia/Seoul", "--year", "2026"])
    assert result["status"] == "ok", result
    return result, out


def test_c0_run_lists_partial_then_word_search_causes(tmp_path, monkeypatch):
    """1위 C=0: 부분 일치 원인이 먼저(맞은 수·없는 조건·맞은 시각), 검색만 걸린 것은 낱말 일치만. match·순위·decision은 near_causes와 무관."""
    lines = [x for x in DATA_LOG.read_text(encoding="utf-8").splitlines(keepends=True) if "DSMGR" not in x]
    result, out = _offline(tmp_path, lines, "데이터가 연결되지 않음 SETUP_DATA_CALL 요청 없음", monkeypatch)
    assert result["candidates"][0]["C"] == 0 and result["investigate"]["mode"] is True
    near = result["near_causes"]
    assert 1 <= len(near) <= 3 and len({n["id"] for n in near}) == len(near)
    first = near[0]
    assert first["id"] == "DATA-001-01" and first["matched"] == result["partial"][0]["matched"] == "1/2"
    assert first["missing"] and first["at"] and first["title"] and "note" not in first
    assert all(n.get("note") == WORDS_ONLY and "matched" not in n for n in near if n["id"] not in
               {p.get("cause") or p["type"] for p in result["partial"]})
    match = json.loads((out / "match.json").read_text(encoding="utf-8"))
    assert [c["cause"] for c in match["candidates"]] == [c["cause"] for c in result["candidates"]]
    assert [c["score"] for c in match["candidates"]] == [c["score"] for c in result["candidates"]]
    assert "낱말 일치만" not in (out / "report.md").read_text(encoding="utf-8")      # 리포트(타임라인 머리 포함)에는 싣지 않는다


def test_c1_run_has_no_near_causes(tmp_path, monkeypatch):
    result, _out = _offline(tmp_path, DATA_LOG.read_text(encoding="utf-8").splitlines(keepends=True), "데이터 연결 안 됨",
                            monkeypatch)
    assert result["candidates"][0]["C"] == 1 and result["investigate"] == {"mode": False}
    assert "near_causes" not in result


def test_empty_db_leaves_key_out(tmp_path, monkeypatch):
    """빈 이슈 DB(뼈대): 조사 모드여도 부분 일치·검색 결과가 없으면 키가 없다(빈 목록을 쓰지 않는다)."""
    db = tmp_path / "db"
    subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(db)], check=True, capture_output=True)
    result, _out = _offline(tmp_path, DATA_LOG.read_text(encoding="utf-8").splitlines(keepends=True), "데이터 연결 안 됨",
                            monkeypatch, db)
    assert result["investigate"]["mode"] is True and not result.get("candidates")
    assert "near_causes" not in result


def test_fit_drops_near_causes_first_and_leaves_the_rest_as_without(tmp_path, monkeypatch):
    lines = [x for x in DATA_LOG.read_text(encoding="utf-8").splitlines(keepends=True) if "DSMGR" not in x]
    base, _out = _offline(tmp_path, lines, "데이터가 연결되지 않음 SETUP_DATA_CALL 요청 없음", monkeypatch)
    base.pop("truncated", None)
    assert base.pop("near_causes")
    near = [{"id": f"DATA-00{i}-01", "title": "t" * 60, "matched": "1/2", "missing": ["m" * 40] * 3,
             "at": ["2026-09-20T05:32:00.000000+00:00"] * 3} for i in range(1, 4)]
    for pad in (0, 2600, 3200, 5000):      # 넘치지 않음 / near_causes[1:]만 / near_causes 전체 / 다른 칸까지
        without = copy.deepcopy(base)
        without["warnings"] = (without.get("warnings") or []) + ["w" * 100] * (pad // 100)
        with_near = {**copy.deepcopy(without), "near_causes": copy.deepcopy(near)}
        got = report.fit(with_near)
        assert len(report.dumps(got).encode("utf-8")) + 1 <= 4096
        kept = got.pop("near_causes", None)
        if kept is None:            # 다 뺐으면 나머지는 이 칸이 없을 때 맞춤과 같다
            assert got == report.fit(copy.deepcopy(without)), pad
        else:                       # 남았으면 near_causes만 줄었다
            assert kept == near[:len(kept)] and {k: v for k, v in got.items() if k != "truncated"} == without, pad
    assert report.schema_violation({**base, "truncated": False, "near_causes": near}) is None
