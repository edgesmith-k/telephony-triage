#!/usr/bin/env python3
"""본 타임라인 중심(`summary.timeline_center` → `report.select_rows`): 시각 입력이 없을 때 줄을 고르는 중심.

합성 로그(AOSP·에뮬레이터 모양 문구만): 50분에 약 3000줄 — 1초마다 데이터 이벤트 줄(data_internet_state_changed)이고, 40분쯤에
로밍 꺼짐 증상 줄(DATA-001 근거)이 있다. 시각·기준 줄 입력이 없으면 `run`이 증상 시각 후보(`time_candidates`)를 남긴다.
중심이 없던 때는 본 타임라인이 로그 맨 앞 200줄(0~3분)이라 실패 줄이 빠졌다. `pytest tests/test_timeline_center.py`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, run_json, tmp  # noqa: E402
from triagelib import core, modulecmd, report, summary  # noqa: E402

KEY = "MOCK-9311"
FAIL = "Data disallowed reasons: ROAMING_DISABLED"
FAIL_SEC = 2400      # 40분
ROAMING = [(0, "D SST-1: onRoamingOn: roaming=true"), (2, "D DSMGR-1: DataRoamingEnabled changed to false"),
           (3, "I DNC-1: onEvaluateNetworkRequests: reason=ROAMING_STATE_CHANGED"),
           (3.5, "W DNC-1: Data evaluation: evaluation reason:ROAMING_ENABLED_CHANGED, Data disallowed reasons: ROAMING_DISABLED, "
                 "candidate profile=null"),
           (13.5, "W DNC-1: Data evaluation: evaluation reason:ROAMING_ENABLED_CHANGED, Data disallowed reasons: ROAMING_DISABLED, "
                  "candidate profile=null"),
           (18.5, "D DRM-1: no retry scheduled: setup not allowed")]


def _stamp(sec: float) -> str:
    ms = int(round(sec * 1000))
    m, rest = divmod(ms, 60_000)
    s, ms = divmod(rest, 1000)
    return f"09-22 {8 + m // 60:02d}:{m % 60:02d}:{s:02d}.{ms:03d}"


def _log(path: Path) -> None:
    rows = [(k, "D DNC-0: Internet data state changed from DISCONNECTED to CONNECTED.")
            for k in range(3000) if not FAIL_SEC <= k < FAIL_SEC + 20]
    rows += [(FAIL_SEC + off, msg) for off, msg in ROAMING]
    rows.sort(key=lambda r: r[0])
    path.write_text("".join(f"{_stamp(s)}  1234  1250 {m}\n" for s, m in rows), encoding="utf-8")


_JOB: list = []


def _job() -> Path:
    if _JOB:
        return _JOB[0]
    out = tmp("tt-center-") / "j"
    log = out.parent / "in.log"
    _log(log)
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": KEY, "summary": "로밍 중 데이터 안 됨 (합성)"}), encoding="utf-8")   # 발생 시각 없음
    done = run_json("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", out, "--logs", log, "--issue-meta", meta,
                                  "--tz", "UTC", "--year", "2026", "--explore"])
    assert done["status"] == "ok" and done["step_anchor"]["source"] == "symptom_scan", done
    _JOB.append(out)
    return out


def _variant(name: str, change) -> tuple[Path, str]:
    """`run`이 만든 작업을 복사해 explore-input.json만 `change(spec)`로 바꾸고 `explore` → (작업, timeline.md 글)."""
    job = tmp(f"tt-center-{name}-") / "j"
    shutil.copytree(_job(), job)
    path = job / core.EXPLORE_INPUT_FILE
    spec = json.loads(path.read_text(encoding="utf-8"))
    for k in ("anomaly", "summary"):
        spec.pop(k, None)
    change(spec)
    path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    run_json("triage.py", ["explore", KEY, "--out", job])
    return job, (job / core.TIMELINE_FILE).read_text(encoding="utf-8")


def _main(text: str) -> str:
    """요약 절과 이상 줄 절을 뺀 본 타임라인."""
    start = text.find("## 본 타임라인\n\n")
    text = text[start:] if start >= 0 else text
    return text.split("\n## 이상 줄")[0]


def _e1_same(job: Path) -> None:
    """`modulecmd._explore_inputs`(E1 재계산)가 `triage._explore`와 같은 바이트를 낸다(다르면 NoJob)."""
    class NoJob(Exception):
        pass

    events = json.loads((job / "events.json").read_text(encoding="utf-8"))
    modulecmd._explore_inputs(job, KEY, events, {}, NoJob)


def test_symptom_candidates_center_the_timeline_on_the_late_failure():
    job, text = _variant("guess", lambda spec: None)
    spec = json.loads((job / core.EXPLORE_INPUT_FILE).read_text(encoding="utf-8"))
    guess = [t["ts"] for t in spec["time_candidates"]]
    assert any(g.startswith("2026-09-22T08:40") for g in guess), guess
    assert FAIL in _main(text)                                  # 고치기 전: 맨 앞 200줄(08:00~08:03)만 남아 없었다
    assert f"- 줄 고른 기준: 증상 시각 후보 {len(guess)}개 {', '.join(guess)} (증상 시각 후보 기준, 스크립트 추정이라 확정 아님." in text
    assert "(이벤트·경고·오류 줄 우선, 아래 기준에 가까운 순으로 골랐다" in text
    assert "기준: 증상 시각 후보" in text                         # 요약 머리도 같은 기준(추정)
    _e1_same(job)


def test_comment_clue_centers_the_timeline_and_heads_say_not_confirmed():
    fail_ts = f"2026-09-22T08:40:03.500Z"

    def clue(spec):
        spec.pop("time_candidates", None)
        spec["clue_at"] = fail_ts

    job, text = _variant("clue", clue)
    assert FAIL in _main(text)
    assert f"- 줄 고른 기준: 코멘트 단서 시각 {fail_ts} (코멘트 단서 기준, 확정 아님)" in text
    assert f"기준: {fail_ts} (코멘트 단서 기준, 확정 아님)" in text         # 요약·이상 줄 절 머리
    _e1_same(job)


def test_no_center_keeps_log_head_and_says_so():
    def bare(spec):
        spec.pop("time_candidates", None)

    job, text = _variant("none", bare)
    main = _main(text)
    assert FAIL not in main and "08:03:20" not in main and "08:03:19.000" in main      # 지금처럼 맨 앞 200줄
    assert "- 줄 고른 기준: 없음 (실패 스텝·코멘트 단서·증상 시각 후보가 없어 로그 맨 앞부터 골랐다" in text
    _e1_same(job)


def test_scores_and_decision_do_not_depend_on_explore():
    """explore는 analysis.json·report.md 판단 줄을 건드리지 않는다(표시만) — 중심이 바뀌어도 같은 바이트."""
    job = _job()
    before = (job / "analysis.json").read_bytes()
    for name, change in (("a", lambda s: None), ("b", lambda s: s.update(clue_at="2026-09-22T08:40:03.500Z"))):
        other, _ = _variant(name, change)
        assert (other / "analysis.json").read_bytes() == before


def test_center_rules_and_unchanged_bytes():
    assert summary.timeline_center({"around": "2026-09-22T08:40:00Z"}) == (["2026-09-22T08:40:00Z"], None)
    anchor = {"around": "2026-09-22T08:40:00Z", "anchor": {"fail": "2026-09-22T08:40:00Z", "source": "steps_file"},
              "clue_at": "2026-09-22T08:10:00Z"}
    assert summary.timeline_center(anchor) == (["2026-09-22T08:40:00Z"], None)         # 실패 스텝 > 코멘트 단서
    clue = summary.timeline_center({"around": "2026-09-22T08:00:00Z", "clue_at": "2026-09-22T08:10:00Z"})
    assert clue[0] == ["2026-09-22T08:10:00Z"] and "확정 아님" in clue[1]                  # 코멘트 단서 > 발생 시각(요약과 같다)
    rows = [{"ts": f"2026-09-22T08:00:{s:02d}.000Z", "tag": "T", "msg": "m", "level": "D", "phone": None, "marks": ["e"]}
            for s in range(30)]
    items, total = report.select_rows(rows, ["2026-09-22T08:00:05Z", "2026-09-22T08:00:25Z"], 4)
    assert [r["ts"][17:19] for r in items] == ["04", "05", "06", "25"]      # 가장 가까운 후보까지 거리(같으면 시각순)
    assert report.select_rows(rows, "2026-09-22T08:00:05Z", 4) == report.select_rows(rows, ["2026-09-22T08:00:05Z"], 4)
    small, n = report.select_rows(rows, None, 100)                 # 상한 아래면 고르지 않는다 — 머리 글도 없다(이전과 같은 바이트)
    ev = {"input": {}}
    assert report.render_timeline("K", ev, small, n, None, 100) == report.render_timeline("K", ev, small, n, None, 100, basis="없음")


def test_view_center_keeps_old_values_for_anchor_and_time_input():
    """모듈 보기 중심(`summary.view_center`): 앵커 실패 시각·발생 시각만 있는 기존 경우는 예전 식과 같은 값(보기 바이트 그대로)."""
    def old(spec):
        anchor = spec.get("anchor") or {}
        return (anchor.get("fail") or spec.get("around"),
                ("기준 줄" if anchor.get("source") == "look_at" else "실패 스텝") if anchor.get("fail") else "발생 시각")

    t = "2026-09-20T05:32:10Z"
    for spec in ({"around": t}, {"around": t, "anchor": {"source": "steps_file", "fail": t}},
                 {"around": t, "anchor": {"source": "look_at", "fail": t}},
                 {"around": t, "anchor": {"source": "step_order", "fail": t}, "time_candidates": [{"ts": "x"}]}):
        assert summary.view_center(spec) == old(spec), spec
    one = summary.view_center({"time_candidates": [{"ts": t, "type": "A"}]})
    assert one == (t, "증상 시각 후보, 스크립트 추정이라 확정 아님")
    many = summary.view_center({"time_candidates": [{"ts": t}, {"ts": "2026-09-20T05:40:00Z"}]})
    assert many[0] is None and "하나로 못 정해 중심 없음" in many[1] and "확정 아님" in many[1]
