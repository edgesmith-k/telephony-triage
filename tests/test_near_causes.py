#!/usr/bin/env python3
"""조사 모드 DB 원인 후보(반입 7 B-1·B-2): run의 analysis.json `near_causes`(부분 일치 + 요약 문장 검색, ≤ 3), 4KB 맞춤에서 맨 먼저
빠짐, check-output 탐색 `후보 확인:` 칸(없으면 형식 경고만, 인용은 원문 검사). 합성 로그·공개 표본 DB만(모델 실행 없음)."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, run_json  # noqa: E402
from tests.test_check_output import Q1  # noqa: E402
from tests.test_investigate import Q_AFTER, _failed, _job, _out, _run  # noqa: E402
from common import evidence  # noqa: E402
from triagelib import output, report  # noqa: E402

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


def test_c0_run_drops_causes_already_in_candidates_and_partial(tmp_path, monkeypatch):
    """1위 C=0(유형 DATA-001, 원인 미확인): 부분 일치 DATA-001-01(1/2)·DATA-001-02(0/1)와 검색 결과는 모두 이미 후보인 유형 DATA-001과
    그 원인이라 near_causes에서 빠지고(R-18 — analysis.json `partial`에 그대로 있다) 키가 없다. 11/25 전 기대(첫 칸 DATA-001-01)는
    리뷰 5-F4가 짚은 중복이다. match·순위·decision은 near_causes와 무관."""
    lines = [x for x in DATA_LOG.read_text(encoding="utf-8").splitlines(keepends=True) if "DSMGR" not in x]
    result, out = _offline(tmp_path, lines, "데이터가 연결되지 않음 SETUP_DATA_CALL 요청 없음", monkeypatch)
    assert result["candidates"][0]["C"] == 0 and result["investigate"]["mode"] is True
    assert [c["type"] for c in result["candidates"]] == ["DATA-001"] and "near_causes" not in result
    assert result["partial"][0]["cause"] == "DATA-001-01" and result["partial"][0]["matched"] == "1/2"
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
    base.pop("near_causes", None)        # 11/25 R-18: 이 입력은 near_causes가 비어 키가 없다 — 아래에서 직접 넣는다
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


# --- check-output 탐색: 후보 확인(B-2)·[모듈] 제안(A-1) ---------------------------------------------------------------

NEAR = [{"id": "DATA-001-01", "title": "Data disabled", "matched": "1/2", "missing": ["setting-off"]},
        {"id": "DATA-001-02", "title": "Roaming disabled", "note": WORDS_ONLY}]
FAKE = "15:10:09.999 p0 E vrild RIL_REQUEST_SETUP_DATA_CALL invented reply cause=NOT_IN_LOG"


def _near_job(base: Path, near=NEAR) -> Path:
    job = _job(base)
    path = job / "analysis.json"
    path.write_text(json.dumps({**json.loads(path.read_text(encoding="utf-8")), "near_causes": near}, ensure_ascii=False),
                    encoding="utf-8")
    return job


def _record(job: Path) -> dict:
    return json.loads((job / "check-output.json").read_text(encoding="utf-8"))["explore"]


def _explore_lines(job: Path) -> list[str]:
    return [r for r in (job / "report.md").read_text(encoding="utf-8").split("\n") if r.startswith("  - 후보 확인")]


def test_missing_candidate_check_is_a_format_warning_only(tmp_path, capsys):
    data, inv = _run(_near_job(tmp_path / "a"), _out(), capsys)
    assert output.CHECK_MISSING in data["format_warnings"] and data["investigation"] == "identified"
    _data, plain = _run(_job(tmp_path / "b"), _out(), capsys)        # near_causes 없음: 같은 출력이면 게이트 결과가 같다
    assert output.CHECK_MISSING not in (_data.get("format_warnings") or [])
    assert {k: v for k, v in inv.items() if k != "explore_sha"} == {k: v for k, v in plain.items() if k != "explore_sha"}


def test_candidate_check_quotes_go_through_source_check(tmp_path, capsys):
    """후보 확인 인용은 원문 검사: 지어낸 줄이면 그 항목에 [근거 불일치]. 게이트(가설 인용만)는 그대로다."""
    tail = ["후보 확인:", f"- DATA-001-01: 아님 — {Q1}", f"- DATA-001-02: 맞음 — {FAKE}", "- DATA-001-03: 모름 — 찾았는데 없음: 15:10 구간"]
    job = _near_job(tmp_path)
    data, inv = _run(job, _out(extra=tail), capsys)
    assert output.CHECK_MISSING not in (data.get("format_warnings") or [])
    line, = _explore_lines(job)
    assert f"DATA-001-01 아님 — {Q1}" in line and "DATA-001-02 맞음 [근거 불일치] — " in line
    assert "DATA-001-03 모름 — 찾았는데 없음" in line and data["fabricated"] == 1
    assert inv["status"] == "identified" and _failed(inv) == []


def test_db_cause_hypothesis_without_after_failure_quote_is_insufficient(tmp_path, capsys):
    """DB 원인(near_causes)을 그대로 가설로 써도 기준 시각 뒤를 안 봤으면 게이트 4에서 근거 부족."""
    tail = ["후보 확인:", f"- DATA-001-01: 맞음 — {Q1}"]
    _data, inv = _run(_near_job(tmp_path), _out(quotes=(Q1,), head="DATA-001-01 Data disabled와 같은 원인", extra=tail), capsys)
    assert inv["status"] == "insufficient_evidence" and _failed(inv) == ["실패 뒤 흔적"]


def _module_tail(*rules: str) -> list[str]:
    return ["규칙 제안:", *[f"- {r}" for r in rules]]


def test_module_lines_keep_only_grounded_known_slots(tmp_path, capsys):
    """[모듈] 줄 번호 N = explore-output.md의 `- [모듈]` 줄 순서(형식 틀린 줄도 센다). 근거 있음·지어냄·모르는 칸·형식 오류 → 1줄만."""
    good = f"[모듈] android/data 층 경로 — vrild 인증 거절은 CP 응답부터 본다 — 근거: {Q1}"
    rules = (f"[모듈] android/data 함정 — 지어낸 근거 — 근거: {FAKE}", f"[모듈] android/data 엉뚱한칸 — x — 근거: {Q1}",
             "[모듈] android/data 첫 점검 근거 칸 없음", good)
    job = _job(tmp_path)
    _run(job, _out(extra=_module_tail(*rules)), capsys)
    rec = _record(job)
    assert rec["module_lines"] == [4] and rec["rules"] == 1 and rec["rules_dropped"] == 3
    assert rec["output_sha256"] == hashlib.sha256((job / "explore-output.md").read_bytes()).hexdigest()   # skill_patch가 대조
    rows = (job / "report.md").read_text(encoding="utf-8")
    assert f"  - 규칙 제안 (탐색): [모듈 4] {good[len('[모듈] '):]}" in rows
    assert "  - 탐색 출력의 제안 3개는 근거가 원문에서 확인되지 않아 뺐다" in rows
    plain = _job(tmp_path / "none")
    _run(plain, _out(), capsys)
    assert "module_lines" not in _record(plain)        # [모듈] 줄이 없으면 키가 없다


def test_held_cause_drops_first_check_and_trap_slots(tmp_path, capsys):
    """원인 보류(decision held)면 첫 점검·함정은 빼고 층 경로는 남긴다(skill_patch --module과 같은 기준). 확정이면 셋 다."""
    rules = [f"- [모듈] android/data {slot} — 한 줄 — 근거: {Q_AFTER}" for slot in ("첫 점검", "함정", "층 경로")]
    held = _job(tmp_path / "held")
    _run(held, _out(extra=["규칙 제안:", *rules]), capsys)
    assert _record(held)["module_lines"] == [3]
    source, tags = evidence.source_text(Q_AFTER)
    lines, kept, dropped, nums = output._rule_subs("explore", [], source, tags, {"fabricated": 0}, "\n".join(rules), True)
    assert nums == [1, 2, 3] and kept == 3 and dropped == 0 and lines[0].endswith("[모듈 1] android/data 첫 점검 — 한 줄 — 근거: "
                                                                                    + Q_AFTER)


# --- R-18(11/25 리뷰 5-F4·2-5·2-6): 잡음·중복 거르기, 후보 없음의 설명 기반 검색 재사용, 검색에는 가린 요약 ----------------------

def _near(partial, candidates=(), hits=None, summary="데이터 연결 안 됨 010-1234-5678", search=()):
    """`Driver.near_causes`를 가짜 실행기로 — 검색 호출(인자)을 기록한다."""
    import types
    from triagelib import driver
    calls = []

    def call(step, script, argv, **_k):
        calls.append((step, argv[0]))
        return 0, {"results": list(search)}, ""

    me = types.SimpleNamespace(run=types.SimpleNamespace(call=call), snap="SNAP", key="MOCK-1",
                               masker=lambda **_k: (lambda text: text.replace("010-1234-5678", "<PHONE#1>")),
                               cause_entry=lambda ident: {"title": f"t-{ident}"})
    got = driver.Driver.near_causes(me, {"summary": summary}, {"partial": list(partial)}, list(candidates), {}, hits)
    return got, calls


def test_near_causes_drop_zero_match_known_candidates_and_type_with_cause():
    p = [{"type": "DATA-001", "cause": "DATA-001-01", "matched": "0/2", "missing": []},          # 맞은 조건 0개: 뺌
         {"type": "DATA-002", "cause": "DATA-002-01", "matched": "1/2", "missing": [{"desc": "x"}]},   # 이미 후보: 뺌
         {"type": "DATA-003", "cause": "DATA-003-02", "matched": "1/3", "missing": []},
         {"type": "SIM-001", "cause": None, "matched": "1/2", "missing": []}]
    cands = [{"type": "DATA-002", "cause": None, "C": 0}]
    search = [{"kind": "type", "id": "DATA-003"}, {"kind": "cause", "id": "DATA-002-05"}, {"kind": "cause", "id": "NET-004-01"},
              {"kind": "issue", "key": "MOCK-1", "cause": "NET-009-01"}]
    got, calls = _near(p, cands, search=search)
    # DATA-003(유형)은 그 원인 DATA-003-02가 있어 원인만, DATA-002-05는 후보 유형 DATA-002의 원인이라 뺌, 이 이슈 자신의 기록은 뺌
    assert [n["id"] for n in got] == ["DATA-003-02", "SIM-001", "NET-004-01"]
    assert got[0]["matched"] == "1/3" and got[2]["note"] == WORDS_ONLY
    assert calls == [("4-near", "데이터 연결 안 됨 <PHONE#1>")]                     # 검색에는 가린 요약(R-31)


def test_near_causes_reuse_search_hits_and_empty_means_no_key():
    hits = [{"id": "DATA-001-02", "kind": "cause", "title": "x"}, {"id": "MOCK-9", "kind": "issue", "title": "y"}]
    got, calls = _near([], hits=hits)
    assert [n["id"] for n in got] == ["DATA-001-02"] and calls == []               # 후보 없음 검색 결과를 다시 쓴다(검색 안 함)
    got, _calls = _near([{"type": "DATA-001", "cause": "DATA-001-01", "matched": "0/1", "missing": []}], summary="")
    assert got == []                                                                # 남는 것이 없으면 빈 목록(run은 키를 안 쓴다)
