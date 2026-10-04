#!/usr/bin/env python3
"""실패 스텝 기준 분석 구간 (07-workflow.md §Step 3, contracts.md §3.2 `parse_logcat.py markers`·`--between`).

1. `common/stepanchor.py` 단위: 스텝 번호·이름 비교, FAIL 마커 선택, 시작 대체, 구간·clamp, steps-file 시각.
2. `parse_logcat.py markers`(마스킹, 정규식 오류 경고)와 `parse --between`.
3. `triage.py`(오프라인): 마커 앵커(실패 스텝 있음·없음), steps-file 앵커, `--answer anchor=off`, Jira 시각 불일치 경고,
   범위 밖 앵커 폐기, 마커 없는 입력은 이전과 같음, analysis.json ≤ 4KB.
4. 스텝 기준 우선 유형(순위 참고): `match_signatures`의 `step_focus`(map·records), score·confidence 불변, 회귀 모드 동일.

`pytest tests/test_step_anchor.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import stepanchor  # noqa: E402
from runner import SAMPLE, copy_db, edit, plugin_root, run, run_json, tmp, variant_db  # noqa: E402

UTC = timezone.utc
LOG = REPO / "tests" / "fixtures" / "logs" / "step-anchor.log"
RULES = SAMPLE / "parser-rules"
TZ = ["--tz", "Asia/Seoul", "--year", "2026"]
# 마커 패턴은 기본 꺼짐([])이다. 마커 테스트는 옛 블록 전체(plugin_root는 failed_step 블록을 통째로 바꾼다)를 켠 루트를 쓴다.
MARKER_ROOT = plugin_root("markers", failed_step={
    "marker_patterns": [r"^(?:TestRunner|Automation)\s*:\s*\[?(?i:step)\s*(?P<step>\d+)\]?\s*(?:[:-]\s*.*?\s)?(?P<status>START|PASS|FAIL)\b"],
    "marker_status": {"start": ["start", "begin", "시작"], "pass": ["pass", "ok", "성공"], "fail": ["fail", "ng", "error", "실패"]},
    "anchor_without_step": True,
    "window": {"pre_sec": 60, "post_sec": 30, "fail_only_pre_sec": 120, "max_span_sec": 900},
    "disagree_minutes": 10,
    "steps_file_tz": None,
    "clock_offset": None,
})


def _t(clock: str) -> datetime:
    """2026-09-20 05:HH:MM:SS UTC (= 14:… KST)."""
    h, m, s = map(int, clock.split(":"))
    return datetime(2026, 9, 20, h, m, s, tzinfo=UTC)


def _mk(clock: str, step: str, status: str) -> dict:
    return {"ts": _t(clock).isoformat().replace("+00:00", "Z"), "step": step, "status": status,
            "tag": "TestRunner", "msg": f"Step {step} {status.upper()}"}


# -- 1. 단위 -------------------------------------------------------------------------------------


def test_step_number_and_same_step():
    assert [stepanchor.step_number(t) for t in ("Step 5 x", "스텝 12", "단계3", "#7 a", "5 | 켜기", "  05", "켜기")] \
        == [5, 12, 3, 7, 5, 5, None]
    assert stepanchor.step_number("12345") is None            # 5자리는 번호가 아니다
    assert stepanchor.same_step("5", "Step 5 데이터 켜기")          # 번호가 같다
    assert not stepanchor.same_step("5", "Step 3 데이터 켜기")      # 번호가 다르면 이름이 같아도 다르다
    assert stepanchor.same_step("데이터 켜기", "Step 5 데이터 켜기")  # 한쪽에 번호가 없으면 이름
    assert stepanchor.same_step("5 | 데이터  켜기", "3 | 데이터 켜기", names_only=True)
    assert stepanchor.same_step("Enable DATA", "step 2: enable data call")   # casefold, 짧은 쪽 4자 이상 포함
    assert not stepanchor.same_step("on", "Step 2: power on")     # 3자 이하 포함은 같다고 보지 않는다
    assert not stepanchor.same_step("5", "데이터 켜기")             # 이름이 없는 쪽은 맞지 않는다
    assert not stepanchor.same_step("", "")


def test_status_of_uses_casefold_mapping():
    mapping = {"start": ["start", "시작"], "pass": ["pass"], "fail": ["fail", "NG"]}
    assert [stepanchor.status_of(x, mapping) for x in ("START", "시작", "Pass", "ng", "x", None)] == \
        ["start", "start", "pass", "fail", None, None]
    assert stepanchor.status_of("실패") == "fail"               # 기본 매핑


def test_compile_markers_bad_regex_and_missing_groups_warn():
    ok = r"^T:\s*(?P<step>\d+)\s*(?P<status>FAIL)"
    compiled, warns = stepanchor.compile_markers(["(", r"no groups", ok])
    assert [rx.pattern for rx in compiled] == [ok] and len(warns) == 2
    assert "정규식 오류" in warns[0] and "그룹" in warns[1]


def test_find_span_prefers_failed_step_start_and_closest_fail():
    marks = [_mk("5:30:10", "3", "start"), _mk("5:30:40", "3", "pass"), _mk("5:33:00", "5", "start"),
             _mk("5:33:30", "5", "fail")]
    span, warns = stepanchor.find_span(marks, "Step 5 데이터 켜기 FAIL", None, True)
    assert warns == [] and span["source"] == "log_marker" and span["step_from"] == "failed_step"
    assert (span["start"], span["fail"], span["end"]) == (_t("5:33:00"), _t("5:33:30"), _t("5:33:30"))
    # 실패 스텝과 같은 스텝의 FAIL이 없으면 앵커가 없다(다른 스텝의 FAIL을 쓰지 않는다)
    assert stepanchor.find_span(marks, "Step 9 다른 스텝", None, True) == (None, [])
    # 같은 스텝의 FAIL이 여럿: Jira 시각에 가장 가까운 것, 경고 하나
    marks2 = [_mk("5:30:00", "5", "start"), _mk("5:30:20", "5", "fail"), _mk("5:40:00", "5", "start"),
              _mk("5:40:20", "5", "fail")]
    span, warns = stepanchor.find_span(marks2, "step 5 x", _t("5:39:00"), True)
    assert span["fail"] == _t("5:40:20") and span["start"] == _t("5:40:00")
    assert len(warns) == 1 and "FAIL 마커 2개" in warns[0]
    span, _ = stepanchor.find_span(marks2, "step 5 x", None, True)       # Jira 시각 없음 → 첫 번째
    assert span["fail"] == _t("5:30:20")


def test_find_span_start_fallback_to_previous_marker_of_any_step():
    marks = [_mk("5:30:10", "3", "pass"), _mk("5:33:30", "5", "fail")]       # Step 5 START 없음
    span, _ = stepanchor.find_span(marks, "Step 5", None, True)
    assert span["start"] == _t("5:30:10") and span["fail"] == _t("5:33:30")
    span, _ = stepanchor.find_span([_mk("5:33:30", "5", "fail")], "Step 5", None, True)
    assert span["start"] is None


def test_find_span_start_without_fail_uses_next_marker_or_max_span():
    marks = [_mk("5:33:00", "5", "start"), _mk("5:34:00", "6", "start")]
    span, warns = stepanchor.find_span(marks, "Step 5", None, True)
    assert span["fail"] is None and span["end"] == _t("5:34:00") and len(warns) == 1
    span, _ = stepanchor.find_span(marks[:1], "Step 5", None, True, max_span_sec=600)
    assert span["end"] == _t("5:43:00")
    # 같은 스텝이 PASS로 끝났으면 실패한 스텝이 아니다
    done = [_mk("5:33:00", "5", "start"), _mk("5:33:10", "5", "pass")]
    assert stepanchor.find_span(done, "Step 5", None, True) == (None, [])


def test_find_span_without_failed_step_needs_allow_flag():
    marks = [_mk("5:30:10", "3", "start"), _mk("5:30:30", "3", "fail"), _mk("5:33:30", "5", "fail")]
    span, warns = stepanchor.find_span(marks, None, _t("5:33:00"), True)
    assert span["step_from"] == "marker" and span["step"] == "5" and span["fail"] == _t("5:33:30")
    assert len(warns) == 1
    assert stepanchor.find_span(marks, None, None, False) == (None, [])
    assert stepanchor.find_span(marks, "", None, False) == (None, [])


def test_window_and_clamp():
    span = {"start": _t("5:33:00"), "fail": _t("5:33:30"), "end": _t("5:33:30")}
    start, end, warns = stepanchor.window(span, {})
    assert (start, end, warns) == (_t("5:32:00"), _t("5:34:00"), [])
    cfg = {"window": {"pre_sec": 10, "post_sec": 5, "fail_only_pre_sec": 40, "max_span_sec": 100}}
    assert stepanchor.window(span, cfg)[:2] == (_t("5:32:50"), _t("5:33:35"))
    assert stepanchor.window({"start": None, "fail": _t("5:33:30"), "end": _t("5:33:30")}, cfg)[:2] == \
        (_t("5:32:50"), _t("5:33:35"))
    long = {"start": _t("5:20:00"), "fail": _t("5:33:30"), "end": _t("5:33:30")}      # 810초
    start, end, warns = stepanchor.window(long, cfg)
    assert start == _t("5:33:30") - timedelta(seconds=110) and end == _t("5:33:35") and len(warns) == 1
    assert "810초" in warns[0]
    # 시작만 있는 구간은 end를 쓴다
    only = {"start": _t("5:33:00"), "fail": None, "end": _t("5:34:00")}
    assert stepanchor.window(only, {})[:2] == (_t("5:32:00"), _t("5:34:30"))
    assert stepanchor.gap_minutes(_t("5:33:00"), _t("5:10:00")) == 23.0


def test_steps_file_times():
    f = stepanchor.steps_file_times
    # 오프셋 있는 ISO는 그대로
    assert f("5 | 켜기 | FAIL | 2026-09-20T14:33:00+09:00 | 2026-09-20T14:33:30+09:00", "UTC", 2026, None) == \
        (_t("5:33:00"), _t("5:33:30"))
    # 오프셋 없는 ISO(공백 구분)는 tz로
    assert f("5 | 켜기 | FAIL | 2026-09-20 14:33:00 | 2026-09-20 14:33:30", "Asia/Seoul", None, None) == \
        (_t("5:33:00"), _t("5:33:30"))
    # logcat 스탬프 + 연도
    assert f("FAIL at 09-20 14:33:30.500", "Asia/Seoul", 2026, None) == (None, _t("5:33:30") + timedelta(milliseconds=500))
    assert f("09-20 14:33:00 ~ 09-20 14:33:30", "Asia/Seoul", 2026, None) == (_t("5:33:00"), _t("5:33:30"))
    # 시각만: 날짜는 기준 시각의 현지 날짜
    ref = _t("5:31:00")
    assert f("Step 5 FAIL 14:33:00 14:33:30", "Asia/Seoul", 2026, ref) == (_t("5:33:00"), _t("5:33:30"))
    # 기준 시각이 없으면 시각만으로는 알 수 없다
    assert f("Step 5 FAIL 14:33:30", "Asia/Seoul", 2026, None) == (None, None)
    # 자정 넘김: 기준(23:50 KST) 이후 00:05는 다음 날
    late = datetime(2026, 9, 20, 14, 50, 0, tzinfo=UTC)        # 23:50 KST
    start, fail = f("23:59:00 00:05:00", "Asia/Seoul", 2026, late)
    assert start == datetime(2026, 9, 20, 14, 59, tzinfo=UTC) and fail == datetime(2026, 9, 20, 15, 5, tzinfo=UTC)
    assert f("시각 없음", "UTC", 2026, ref) == (None, None)


# -- 2. markers / --between ------------------------------------------------------------------------


def test_markers_on_fixture_masks_and_reports_coverage():
    out = run_json("parse_logcat.py", ["markers", LOG, "--rules", RULES, *TZ], root=MARKER_ROOT)
    assert out["schema"] == 1 and out["total"] == 4 and out["truncated"] is False and out["warnings"] == []
    got = [(m["ts"], m["step"], m["status"], m["tag"], m["msg"]) for m in out["markers"]]
    assert got == [
        ("2026-09-20T05:30:10.000Z", "3", "start", "TestRunner", "Step 3 START"),
        ("2026-09-20T05:30:40.000Z", "3", "pass", "TestRunner", "Step 3 PASS"),
        ("2026-09-20T05:33:00.000Z", "5", "start", "TestRunner", "Step 5 START"),
        ("2026-09-20T05:33:30.000Z", "5", "fail", "TestRunner", "Step 5 FAIL"),
    ]
    assert out["coverage"] == {"first_ts": "2026-09-20T05:30:00.000Z", "last_ts": "2026-09-20T05:34:00.000Z"}


def test_markers_mask_hit_lines_and_cap_message(tmp_path=None):
    d = tmp("tt-markers-")
    log = d / "m.log"
    log.write_text(
        "09-20 14:33:00.000  1234  1244 D TestRunner: Step 4 - 고객 010-1234-5678 확인 " + "x" * 300 + " START\n"
        "09-20 14:33:01.000  1234  1244 D TestRunner: Step 4 FAIL\n"
        "09-20 14:33:02.000  1234  1244 D Other: Step 4 FAIL\n"                  # 태그가 패턴과 다르다
        "09-20 14:33:03.000  1234  1244 D TestRunner: Step 5 UNKNOWN\n",           # 상태가 패턴과 다르다
        encoding="utf-8")
    out = run_json("parse_logcat.py", ["markers", log, "--rules", RULES, *TZ], root=MARKER_ROOT)
    assert [(m["step"], m["status"]) for m in out["markers"]] == [("4", "start"), ("4", "fail")]
    first = out["markers"][0]
    assert "010-1234-5678" not in first["msg"] and "<MSISDN#" in first["msg"] and len(first["msg"]) <= 200


def test_markers_without_patterns_gives_coverage_only():
    root = plugin_root("nomarkers", failed_step={"marker_patterns": []})
    out = run_json("parse_logcat.py", ["markers", LOG, "--rules", RULES, *TZ], root=root)
    assert out["markers"] == [] and out["total"] == 0 and out["coverage"]["first_ts"] == "2026-09-20T05:30:00.000Z"


def test_markers_bad_pattern_is_warning_not_error():
    root = plugin_root("badmarker", failed_step={"marker_patterns": [
        "(", r"^TestRunner\s*:\s*Step\s*(?P<step>\d+)\s*(?P<status>START|PASS|FAIL)"]})
    proc = run("parse_logcat.py", ["markers", LOG, "--rules", RULES, *TZ], root=root)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["total"] == 4 and [w["code"] for w in out["warnings"]] == ["marker-pattern"]
    assert "경고[marker-pattern]" in proc.stderr


def test_parse_between_sets_exact_window_and_mode():
    out = run_json("parse_logcat.py", ["parse", LOG, "--between", "2026-09-20T14:32:00+09:00",
                                       "2026-09-20T14:34:00+09:00", "--rules", RULES, "--mask", *TZ])
    assert out["input"]["mode"] == "between"
    assert out["input"]["window"] == {"start": "2026-09-20T05:32:00.000Z", "end": "2026-09-20T05:34:00.000Z"}
    assert out["coverage"]["window_in_range"] is True
    assert out["events"] and all("2026-09-20T05:32:00" <= e["ts"] <= "2026-09-20T05:34:00.000Z" for e in out["events"])
    assert not any(e["tag"].startswith("Ims") for e in out["events"])
    # 로그 범위 밖이면 around와 같은 판정
    out = run_json("parse_logcat.py", ["parse", LOG, "--between", "2026-09-20T15:00:00+09:00",
                                       "2026-09-20T15:05:00+09:00", "--rules", RULES, *TZ])
    assert out["coverage"]["window_in_range"] is False


def test_parse_between_validates_arguments():
    base = ["parse", LOG, "--rules", RULES, *TZ]
    for window in (["2026-09-20T14:34:00+09:00", "2026-09-20T14:32:00+09:00"],      # 시작 > 끝
                   ["2026-09-20T14:32:00", "2026-09-20T14:34:00"],                   # 타임존 없음
                   ["x", "y"]):
        proc = run("parse_logcat.py", [*base, "--between", *window])
        assert proc.returncode == 2 and "--between" in proc.stderr, window
    both = run("parse_logcat.py", [*base, "--between", "2026-09-20T14:32:00+09:00", "2026-09-20T14:34:00+09:00", "--full"])
    assert both.returncode == 2


# -- 3. triage (오프라인) -----------------------------------------------------------------------------

KEY = "MOCK-9001"
STEP = "Step 5 데이터 켜기 FAIL"
CSV = "no,action,result,start,end\n5,데이터 켜기,FAIL,2026-09-20 14:33:00,2026-09-20 14:33:30\n"


def _offline(name: str, *extra, occurred="2026-09-20T14:31:00+09:00", logs=(LOG,), root=None):
    """오프라인 triage 실행 → (analysis, JOB 디렉터리)."""
    out = tmp("tt-anchor-") / name
    meta = out.parent / f"{name}.meta.json"
    meta.write_text(json.dumps({"key": KEY, "occurred_at": occurred, "summary": ""}), encoding="utf-8")
    args = ["run", KEY, "--offline-db", SAMPLE, "--out", out, "--logs", *logs, "--jira-meta", meta,
            "--tz", "Asia/Seoul", "--year", "2026", *extra]
    return run_json("triage.py", args, root=root), out


def _causes(analysis: dict) -> list[str]:
    return [c["cause"] for c in analysis.get("candidates") or []]


def _markerless(d: Path) -> Path:
    path = d / "nomarker.log"
    path.write_text("".join(line + "\n" for line in LOG.read_text(encoding="utf-8").splitlines()
                            if "TestRunner" not in line), encoding="utf-8", newline="\n")
    return path


def _strip(a: dict) -> dict:
    return {k: v for k, v in a.items() if k not in ("generated_at", "files", "request_hash")}


def test_marker_anchor_with_failed_step_moves_window_and_top_candidate():
    off, _ = _offline("off", "--failed-step", STEP, "--answer", "anchor=off", root=MARKER_ROOT)
    assert _causes(off)[0] == "IMS-001-01" and off["step_anchor"] == {"source": "jira"}     # 오늘의 동작
    assert off["logs"]["window"] == {"start": "2026-09-20T05:26:00.000Z", "end": "2026-09-20T05:36:00.000Z"}

    done, job = _offline("on", "--failed-step", STEP, root=MARKER_ROOT)
    assert _causes(done) == ["DATA-001-01"]                                  # IMS는 구간 밖
    sa = done["step_anchor"]
    assert sa["source"] == "log_marker" and sa["step"] == "Step 5" and "step_from" not in sa
    assert sa["span"] == ["2026-09-20T05:33:00.000Z", "2026-09-20T05:33:30.000Z"]
    assert done["logs"]["window"] == {"start": "2026-09-20T05:32:00.000Z", "end": "2026-09-20T05:34:00.000Z"}
    assert done["jira"]["failed_step"]["text"] == STEP and done["request_hash"] != off["request_hash"]
    report = (job / "report.md").read_text(encoding="utf-8")
    assert "- 실패 스텝 구간 (log_marker): Step 5 2026-09-20T05:33:00.000Z ~ 2026-09-20T05:33:30.000Z → 분석 범위 " \
        "2026-09-20T05:32:00.000Z ~ 2026-09-20T05:34:00.000Z (Jira 발생 시각 2026-09-20T14:31:00+09:00 / 2.5분 차이)" in report
    assert "점수·S/C에 쓰지 않음; 분석 범위·순위 참고" in report
    # Jira 시각은 가까우므로 경고 없음. jira_meta.json은 그대로, 매처는 match_meta.json(발생 시각 = 스텝 실패 시각)을 쓴다
    assert not any("분 다르다" in w for w in done.get("warnings") or [])
    assert json.loads((job / "jira_meta.json").read_text(encoding="utf-8"))["occurred_at"] == "2026-09-20T14:31:00+09:00"
    assert json.loads((job / "match_meta.json").read_text(encoding="utf-8"))["occurred_at"] == "2026-09-20T05:33:30.000Z"
    # S/C는 로그가 정한다: 같은 후보의 S·C는 앵커 유무와 무관하다
    assert (done["candidates"][0]["S"], done["candidates"][0]["C"]) == (1, 1)
    trace = [json.loads(line) for line in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    calls = [row for row in trace if row.get("step") == "3-markers"]
    assert len(calls) == 1 and calls[0]["args"][0] == "markers" and not any("Step" in str(a) for a in calls[0]["args"])


def test_marker_anchor_without_failed_step_uses_marker_step_but_never_records_it():
    done, job = _offline("m", root=MARKER_ROOT)
    assert _causes(done) == ["DATA-001-01"]
    assert done["step_anchor"]["source"] == "log_marker" and done["step_anchor"]["step_from"] == "marker"
    assert done["step_anchor"]["step"] == "Step 5"
    assert "failed_step" not in done["jira"] and "failed_step" not in json.dumps(done)
    assert "failed_step" not in (job / "jira_meta.json").read_text(encoding="utf-8")
    assert "failed_step" not in (job / "match_meta.json").read_text(encoding="utf-8")
    report = (job / "report.md").read_text(encoding="utf-8")
    assert "실패 스텝 구간 (log_marker): Step 5" in report and "- 실패 스텝 (보조 정보" not in report
    # anchor_without_step: false이면 실패 스텝을 모를 때는 앵커 없음
    root = plugin_root("noanchorwithout", failed_step={"marker_patterns": [
        r"^TestRunner\s*:\s*Step\s*(?P<step>\d+)\s*(?P<status>START|PASS|FAIL)"], "anchor_without_step": False})
    plain, _ = _offline("n", root=root)
    assert "step_anchor" not in plain and _causes(plain)[0] == "IMS-001-01"


def test_steps_file_anchor_on_markerless_log_and_no_raw_text_in_job_files():
    d = tmp("tt-steps-")
    log = _markerless(d)
    steps = d / "steps.csv"
    steps.write_text(CSV, encoding="utf-8")
    done, job = _offline("s", "--steps-file", steps, "--clock-offset", "0", logs=(log,))
    assert _causes(done) == ["DATA-001-01"]
    sa = done["step_anchor"]
    assert sa["source"] == "steps_file" and sa["span"] == ["2026-09-20T05:33:00.000Z", "2026-09-20T05:33:30.000Z"]
    assert done["jira"]["failed_step"] == {"text": "5 | 데이터 켜기", "source": "steps_file"}
    assert done["logs"]["window"] == {"start": "2026-09-20T05:32:00.000Z", "end": "2026-09-20T05:34:00.000Z"}
    for path in (p for p in job.rglob("*") if p.is_file()):
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "2026-09-20 14:33:00" not in text and "14:33:30" not in text.replace("T05:33:30", "") \
            and "5,데이터 켜기,FAIL" not in text, path.name
    # 마커도 steps-file도 없는 로그에 실패 스텝만 있으면 앵커 없이 오늘과 같다
    plain, _ = _offline("p", "--failed-step", STEP, logs=(log,), root=MARKER_ROOT)
    assert plain["step_anchor"] == {"source": "jira"} and _causes(plain)[0] == "IMS-001-01"


def test_equipment_skew_never_anchors_without_offset():
    """시험 장비 시계가 단말보다 180초 느리다(장비 = 단말 − 180초). 시계 차를 모르면 장비 시각을 단말 시각으로 쓰지 않는다."""
    d = tmp("tt-skew-")
    steps = d / "steps.csv"
    steps.write_text("no,action,result,start,end\n5,데이터 켜기,FAIL,14:30:10,14:30:30\n", encoding="utf-8")
    occurred = "2026-09-20T14:33:20+09:00"
    log = REPO / "tests" / "fixtures" / "logs" / "step-anchor.log"

    # (a) 시계 차 모름: 앵커 없음 — Jira 발생 시각 ±5분 그대로
    none, job = _offline("skew-none", "--steps-file", steps, occurred=occurred, logs=(log,))
    assert none["step_anchor"] == {"source": "jira", "clock": {"mode": "none", "reason": "시계 차 모름"}}
    assert none["logs"]["window"] == {"start": "2026-09-20T05:28:20.000Z", "end": "2026-09-20T05:38:20.000Z"}
    assert "장비 시각 미사용: 시계 정렬 불가(시계 차 모름) — --clock-offset으로 맞출 수 있다" in none["warnings"]
    assert _causes(none)[0] == "DATA-001-01"
    report = (job / "report.md").read_text(encoding="utf-8")
    assert "- 장비 시각 미사용: 시계 정렬 불가(시계 차 모름)" in report and "실패 스텝 구간" not in report
    assert not (job / "match_meta.json").exists()

    # (b) 0초로 잘못 맞추면 장비 시각 그대로 쓴다 — 로그 범위 안의 엉뚱한 구간
    wrong, _ = _offline("skew-zero", "--steps-file", steps, "--clock-offset", "0", occurred=occurred, logs=(log,))
    assert wrong["step_anchor"]["source"] == "steps_file" and wrong["step_anchor"]["clock"] == {"mode": "manual", "offset_sec": 0}
    assert _causes(wrong)[0] == "IMS-001-01"

    # (c)(d) 올바른 시계 차: 같은 표기들은 같은 결과
    docs = []
    for value in ("+3m", "+00:03:00", "180"):
        done, job = _offline(f"skew{value}", "--steps-file", steps, "--clock-offset", value, occurred=occurred, logs=(log,))
        sa = done["step_anchor"]
        assert sa["source"] == "steps_file" and sa["clock"] == {"mode": "manual", "offset_sec": 180}, value
        assert done["logs"]["window"] == {"start": "2026-09-20T05:32:10.000Z", "end": "2026-09-20T05:34:00.000Z"}, value
        assert _causes(done) == ["DATA-001-01"], value
        assert "(시계 차 +180초, 수동)" in (job / "report.md").read_text(encoding="utf-8")
        docs.append(_strip(done))
        for path in (p for p in job.rglob("*") if p.is_file()):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert "14:30:10" not in text and "14:30:30" not in text, path.name      # 장비 시각 원문은 남기지 않는다
    assert docs[0] == docs[1] == docs[2]

    # (e) 형식 오류는 사용 오류(종료 코드 2)
    proc = run("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", tmp("tt-skew-") / "x", "--logs", log,
                             "--jira-meta", d / "none.json", "--steps-file", steps, "--clock-offset", "abc", *TZ])
    assert proc.returncode == 2 and "--clock-offset 형식" in proc.stderr


def test_parse_offset_formats():
    f = stepanchor.parse_offset
    assert [f(v) for v in ("+3m", "-3m", "+1h2m3s", "-90s", "+0.5s", "1h", "+00:03:00", "-00:00:45.5", "+03:00", "180", "-180.5", 180, 0)] \
        == [180, -180, 3723, -90, 0.5, 3600, 180, -45.5, 180, 180, -180.5, 180, 0]
    assert [f(v) for v in ("abc", "", None, "m", "+3x", "1m1", True, "86401", -86401, "1:2:3:4", "+3m 5")] == [None] * 11
    assert f("86400") == 86400 and f("+24h") == 86400


def test_steps_file_zip_report_uses_fail_row_and_warns_when_failed_step_differs():
    import zipfile
    d = tmp("tt-zip-")
    log = _markerless(d)
    html = ("<table><tr><th>No</th><th>Step</th><th>Result</th><th>Start</th><th>End</th></tr>"
            "<tr><td>4</td><td>망 등록</td><td>PASS</td><td>2026-09-20 14:32:00</td><td>2026-09-20 14:32:20</td></tr>"
            "<tr><td>5</td><td>데이터 켜기</td><td>FAIL</td><td>2026-09-20 14:33:00</td><td>2026-09-20 14:33:30</td></tr></table>")
    path = d / "att.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("run_01/report.html", html)
        zf.writestr("index.html", "<table><tr><td>1</td><td>가짜</td><td>FAIL</td></tr></table>")
    done, job = _offline("zip", "--steps-file", path, "--clock-offset", "0", logs=(log,))
    sa = done["step_anchor"]
    assert sa["source"] == "steps_file" and sa["span"] == ["2026-09-20T05:33:00.000Z", "2026-09-20T05:33:30.000Z"]
    assert sa["step"] == "5 | 데이터 켜기" and _causes(done) == ["DATA-001-01"]
    assert done["jira"]["failed_step"] == {"text": "5 | 데이터 켜기", "source": "steps_file"}
    assert "- 시험 절차: zip 안 run_01/report.html" in (job / "report.md").read_text(encoding="utf-8")
    assert not any("FAIL 스텝이 다르다" in w for w in done.get("warnings") or [])
    other, _ = _offline("zip2", "--steps-file", path, "--clock-offset", "0", "--failed-step", "로밍 설정 확인", logs=(log,))
    assert other["step_anchor"]["source"] == "steps_file"
    assert "실패 스텝(cli)과 steps-file의 FAIL 스텝이 다르다 — 구간은 steps-file 순서로 정했다" in other["warnings"]
    same, _ = _offline("zip3", "--steps-file", path, "--clock-offset", "0", "--failed-step", "Step 5 데이터 켜기", logs=(log,))
    assert not any("FAIL 스텝이 다르다" in w for w in same.get("warnings") or [])
    for p in (q for q in job.rglob("*") if q.is_file()):
        assert "2026-09-20 14:33:00" not in p.read_text(encoding="utf-8", errors="replace"), p.name


def test_jira_time_disagreement_warns_but_anchor_still_wins():
    done, job = _offline("far", "--failed-step", STEP, occurred="2026-09-20T14:10:00+09:00", root=MARKER_ROOT)
    assert done["step_anchor"]["source"] == "log_marker" and _causes(done) == ["DATA-001-01"]
    warns = [w for w in done["warnings"] if "분 다르다" in w]
    assert warns == ["Jira 발생 시각과 실패 스텝 시각이 24분 다르다 — 스텝 시각 기준으로 분석했다(끄기: --answer anchor=off)"]
    assert done["step_anchor"]["jira_gap_min"] == 23.5
    assert "23.5분 차이" in (job / "report.md").read_text(encoding="utf-8")
    off, _ = _offline("far-off", "--failed-step", STEP, "--answer", "anchor=off", occurred="2026-09-20T14:10:00+09:00",
                      root=MARKER_ROOT)
    assert not any("분 다르다" in w for w in off.get("warnings") or []) and off["step_anchor"] == {"source": "jira"}


def test_steps_file_time_outside_log_coverage_is_discarded_with_warning():
    d = tmp("tt-steps-")
    log = _markerless(d)
    steps = d / "steps.csv"
    steps.write_text(CSV.replace("14:33", "16:33"), encoding="utf-8")
    done, _ = _offline("out", "--steps-file", steps, "--clock-offset", "0", logs=(log,))
    assert any("로그 범위 밖" in w for w in done["warnings"])
    assert done["step_anchor"] == {"source": "jira", "clock": {"mode": "manual", "offset_sec": 0}}   # 앵커는 폐기
    assert done["logs"]["window"] == {"start": "2026-09-20T05:26:00.000Z", "end": "2026-09-20T05:36:00.000Z"}
    assert _causes(done)[0] == "IMS-001-01"


def test_marker_fail_time_outside_coverage_falls_back_to_steps_file_then_today():
    d = tmp("tt-steps-")
    log = d / "short.log"      # Step 5 FAIL 줄이 잘린 로그: START 뒤 로그가 끊겼다
    log.write_text("".join(line + "\n" for line in LOG.read_text(encoding="utf-8").splitlines()
                           if "Step 5 FAIL" not in line and "no retry" not in line), encoding="utf-8")
    done, _ = _offline("cut", "--failed-step", STEP, logs=(log,), root=MARKER_ROOT)
    sa = done["step_anchor"]          # START만 있으면 다음 마커가 없어 start+900초가 끝이다 → 로그 범위 밖이라 폐기
    assert sa == {"source": "jira"}
    assert any("로그 범위 밖" in w for w in done["warnings"])


def test_no_markers_means_output_identical_to_anchor_off_for_every_labelset_item():
    import yaml
    doc = yaml.safe_load((REPO / "tests" / "fixtures" / "offline-eval-sample.yaml").read_text(encoding="utf-8"))
    for item in doc["items"]:
        out = tmp("tt-anchor-") / "a"
        meta = out.parent / "m.json"
        meta.write_text(json.dumps({"key": item["key"], "occurred_at": item["occurred_at"],
                                    "summary": item.get("summary", "")}, ensure_ascii=False), encoding="utf-8")
        logs = [str((REPO / "tests" / "fixtures" / p).resolve()) for p in item["logs"]]
        base = ["run", item["key"], "--offline-db", SAMPLE, "--logs", *logs, "--jira-meta", meta,
                "--tz", doc["tz"], "--year", doc["year"]]
        a = run_json("triage.py", [*base, "--out", out / "x"])
        b = run_json("triage.py", [*base, "--out", out / "y", "--answer", "anchor=off"])
        assert _strip(a) == _strip(b) and "step_anchor" not in a, item["key"]
        for name in ("report.md", "jira_meta.json"):
            assert (out / "x" / name).read_bytes() == (out / "y" / name).read_bytes(), (item["key"], name)
        assert not (out / "x" / "match_meta.json").exists()
    # 마커 패턴을 비우고 steps-file도 없으면 마커 스캔 자체를 하지 않는다(trace에 3-markers 없음)
    root = plugin_root("nomarkers", failed_step={"marker_patterns": []})
    _, job = _offline("q", root=root)
    steps = [json.loads(line).get("step") for line in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "3-markers" not in steps


def test_long_failed_step_with_anchor_keeps_analysis_within_4kb_and_fit_drops_focus_first():
    done, job = _offline("long", "--failed-step", "Step 5 " + "가나다 " * 120, root=MARKER_ROOT)
    assert done["step_anchor"]["source"] == "log_marker"
    assert len((job / "analysis.json").read_bytes()) <= 4096
    import importlib
    triage = importlib.import_module("triage")
    big = {"ts": "2026-09-20T05:30:00.000Z", "tag": "DNC-0", "msg": "x" * 140, "event": "e"}
    result = {"jira": {"summary": "s" * 3650, "failed_step": {"text": "가" * 120, "source": "cli"}},
              "step_anchor": {"source": "log_marker", "step": "나" * 80, "span": ["a", "b"], "focus": ["DATA-001", "IMS-001"]},
              "warnings": ["w" * 120] * 10, "files": {"report": "r", "events": "e"},
              "candidates": [{"cause": f"C-{i}", "evidence": [dict(big) for _ in range(10)]} for i in range(3)]}
    fitted = triage.fit(result)
    assert "focus" not in fitted["step_anchor"] and len(fitted["step_anchor"]["step"]) <= 40
    assert len(fitted["jira"]["failed_step"]["text"]) <= 120


# -- 4. 스텝 기준 우선 유형 (순위 참고만) --------------------------------------------------------------


def _events_for(db: Path, name: str = "events") -> Path:
    """스텝 시나리오를 Jira 시각(14:31) ±5분으로 파싱한 마스킹 이벤트 파일."""
    out = run_json("parse_logcat.py", ["parse", LOG, "--around", "2026-09-20T14:31:00+09:00", "--minutes", "5",
                                       "--rules", db / "parser-rules", "--mask", *TZ])
    path = tmp("tt-focus-") / f"{name}.json"
    path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return path


def _match(db: Path, events: Path, failed_step: str | None = None, *extra) -> dict:
    meta = events.parent / "meta.json"
    jira = {"key": KEY, "occurred_at": "2026-09-20T14:31:00+09:00", "summary": ""}
    if failed_step:
        jira["failed_step"] = failed_step
    meta.write_text(json.dumps(jira, ensure_ascii=False), encoding="utf-8")
    return run_json("match_signatures.py", ["--db", db, "--events", events, "--jira-meta", meta, "--top", "0", *extra])


def _score_table(result: dict) -> dict:
    return {c["cause"]: (c["score"], c["confidence"], c["S"], c["C"]) for c in result["candidates"]}


def test_step_focus_reorders_ties_without_changing_score_or_confidence():
    db = variant_db("issue-db-step-focus")
    events = _events_for(db)
    plain = _match(db, events)
    assert [c["cause"] for c in plain["candidates"]] == ["IMS-001-01", "DATA-001-01"] and "step_focus" not in plain
    focused = _match(db, events, "데이터 켜기")
    assert [c["cause"] for c in focused["candidates"]] == ["DATA-001-01", "IMS-001-01"]
    assert _score_table(plain) == _score_table(focused)                                   # score·confidence·S·C 불변
    assert focused["step_focus"]["types"] == ["DATA-001"]
    by = focused["step_focus"]["by"]["DATA-001"]
    assert "map" in by and "records:2" in by
    assert focused["candidates"][0]["bonus"]["step"] == 0.05 and "step" not in focused["candidates"][1]["bonus"]
    # 앵커의 Step 번호가 붙은 전체 문구도 이름으로 같은 스텝이다
    assert _match(db, events, "Step 5 데이터 켜기 FAIL")["step_focus"]["by"]["DATA-001"] == by
    # 맞지 않는 스텝이면 우선 유형이 없다
    assert "step_focus" not in _match(db, events, "로밍 설정 확인")


def test_step_focus_sources_records_only_threshold_and_map_only():
    base = variant_db("issue-db-step-focus")
    events = _events_for(base)
    db = copy_db(base)
    cfg = db / "issue-db.config.yaml"
    edit(cfg, "  map:\n    - {pattern: '데이터', types: [DATA-001], categories: []}", "  map: []")
    only_records = _match(db, events, "데이터 켜기")
    assert only_records["step_focus"]["by"] == {"DATA-001": ["records:2"]}
    assert [c["cause"] for c in only_records["candidates"]][0] == "DATA-001-01"
    edit(cfg, "min_records: 2", "min_records: 3")                      # 기록 2건 < 3건 → 우선 유형 없음
    none = _match(db, events, "데이터 켜기")
    assert "step_focus" not in none and [c["cause"] for c in none["candidates"]][0] == "IMS-001-01"
    # map만: 카테고리로 지정하면 그 카테고리의 active 유형 전부
    edit(cfg, "  map: []", "  map:\n    - {pattern: '(?i)ims', categories: [ims]}")
    by_cat = _match(db, events, "IMS 등록 확인")
    assert by_cat["step_focus"] == {"types": ["IMS-001"], "by": {"IMS-001": ["map"]}}


def test_step_focus_is_off_in_regress_and_when_disabled():
    db = variant_db("issue-db-step-focus")
    events = _events_for(db)
    regress = _match(db, events, "데이터 켜기", "--regress")
    assert "step_focus" not in regress and all("step" not in c["bonus"] for c in regress["candidates"])
    off = copy_db(db)
    edit(off / "issue-db.config.yaml", "step_focus_bonus_max: 0.05", "step_focus_bonus_max: 0")
    assert "step_focus" not in _match(off, events, "데이터 켜기")


def test_regress_output_is_byte_identical_between_sample_and_step_focus_variant():
    variant = variant_db("issue-db-step-focus")
    full = run_json("parse_logcat.py", ["parse", LOG, "--full", "--rules", SAMPLE / "parser-rules", "--mask", *TZ])
    events = tmp("tt-focus-") / "full.json"
    events.write_text(json.dumps(full, ensure_ascii=False), encoding="utf-8")
    docs = []
    for db in (SAMPLE, variant):
        doc = run_json("match_signatures.py", ["--db", db, "--events", events, "--regress", "--top", "0"])
        docs.append(json.dumps({k: v for k, v in doc.items() if k not in ("db", "cache")}, ensure_ascii=False, sort_keys=True))
    assert docs[0] == docs[1]
    result = run_json("db_regress.py", ["--db", variant, "--all"], expect=0)
    assert result["summary"]["failed"] == 0


def test_triage_reports_focus_types_in_step_anchor_and_report():
    """전체 경로 대신 오프라인 triage를 변형 DB로: 앵커 없이(--answer anchor=off) 우선 유형이 순위·리포트에 나온다."""
    db = variant_db("issue-db-step-focus")
    out = tmp("tt-anchor-") / "f"
    meta = out.parent / "f.meta.json"
    meta.write_text(json.dumps({"key": KEY, "occurred_at": "2026-09-20T14:31:00+09:00", "summary": ""}), encoding="utf-8")
    done = run_json("triage.py", ["run", KEY, "--offline-db", db, "--out", out, "--logs", LOG, "--jira-meta", meta,
                                  "--tz", "Asia/Seoul", "--year", "2026", "--failed-step", "데이터 켜기",
                                  "--answer", "anchor=off"])
    assert _causes(done)[0] == "DATA-001-01" and done["step_anchor"] == {"source": "jira", "focus": ["DATA-001"]}
    assert "- 스텝 기준 우선 유형 (순위 참고만, 점수·S/C 불변): DATA-001" in (out / "report.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
