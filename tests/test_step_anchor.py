#!/usr/bin/env python3
"""실패 스텝 기준 분석 구간 (07-workflow.md §Step 3, contracts.md §3.2 `parse_logcat.py markers`·`--between`).

1. `common/stepanchor.py` 단위: 스텝 번호·이름 비교, FAIL 마커 선택, 시작 대체, 구간·clamp, steps-file 시각.
2. `parse_logcat.py markers`(마스킹, 정규식 오류 경고)와 `parse --between`.

`pytest tests/test_step_anchor.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import stepanchor  # noqa: E402
from runner import SAMPLE, plugin_root, run, run_json, tmp  # noqa: E402

UTC = timezone.utc
LOG = REPO / "tests" / "fixtures" / "logs" / "step-anchor.log"
RULES = SAMPLE / "parser-rules"
TZ = ["--tz", "Asia/Seoul", "--year", "2026"]


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
    out = run_json("parse_logcat.py", ["markers", LOG, "--rules", RULES, *TZ])
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
    out = run_json("parse_logcat.py", ["markers", log, "--rules", RULES, *TZ])
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
    import json
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


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
