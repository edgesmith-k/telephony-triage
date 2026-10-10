#!/usr/bin/env python3
"""스텝 순서로 실패 구간 정렬 (07-workflow.md §Step 3, 04-parser-matching.md §5.8 (5), contracts.md §3.2).

실제 logcat에는 시험 스텝의 START/FAIL 마커가 없고 시험 장비 시계는 단말과 다를 수 있다. 시험 절차(report.html·zip·붙여넣기)의
PASS 스텝 순서를 이슈 DB `step_events` 규칙으로 로그의 흔적과 맞춰 마지막 일치 뒤를 실패 구간으로 본다.

1. `common/stepanchor.py order_walk` 단위: 가장 이른 흔적, 미끼 무시, 관측 불가·놓침, 반복, 실패 스텝 흔적, seq 순서, 결정성.
2. `parse_logcat.py markers --step-events`: 규칙별 흔적(라벨만), 플래그 없으면 그대로, 잘못된 규칙·상한.
3. `triage.py`(오프라인) + 변형 DB `issue-db-step-events`: zip(report.html)·붙여넣기, 샘플 DB 대체 경로, 바이트 동일성.

`pytest tests/test_step_order.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import random
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import stepanchor  # noqa: E402
from runner import SAMPLE, copy_db, edit, run_json, tmp, variant_db  # noqa: E402

UTC = timezone.utc
BASE = datetime(2026, 9, 20, 5, 30, 0, tzinfo=UTC)
LOG = REPO / "tests" / "fixtures" / "logs" / "step-order.log"
TZ = ["--tz", "Asia/Seoul", "--year", "2026"]
KEY = "MOCK-9001"


# -- 1. order_walk ---------------------------------------------------------------------------------


def _steps(n_pass: int) -> list[dict]:
    rows = [{"index": i, "number": i + 1, "name_raw": f"스텝 {i + 1}", "status": "pass", "time_raw": None} for i in range(n_pass)]
    rows.append({"index": n_pass, "number": n_pass + 1, "name_raw": "실패 스텝", "status": "fail", "time_raw": None})
    return rows


def _ts(sec: float) -> str:
    return (BASE + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(round(sec % 1 * 1000)):03d}Z"


def _hit(rule: int, sec: float, seq: int = 0, label: str = "x") -> dict:
    return {"rule": rule, "ts": _ts(sec), "seq": seq, "label": label}


def _walk(n_pass, rule_of, hits, **cfg):
    steps = _steps(n_pass)
    cfg.setdefault("coverage_last", _ts(1000))
    return stepanchor.order_walk(steps, n_pass, rule_of, hits, cfg)


def test_walk_takes_earliest_hit_after_previous_match_and_ignores_decoys():
    # 스텝 0은 규칙 0, 스텝 1은 규칙 1, 스텝 2는 규칙 0 (같은 규칙을 다시 쓴다)
    hits = [_hit(0, 2), _hit(0, 10), _hit(1, 5), _hit(1, 30)]
    result, info, warnings = _walk(3, {0: 0, 1: 1, 2: 0}, hits)
    assert warnings == [] and result is not None
    assert [(k, ts) for k, ts, _ in info["evidence"]] == [(0, _ts(2)), (1, _ts(5)), (2, _ts(10))]
    assert (info["matched"], info["observable"], info["missed"], info["unobservable"]) == (3, 3, 0, 0)
    assert result["last_ts"] == BASE + timedelta(seconds=10) and result["failed_hit"] is None
    # 미끼: 규칙 1의 흔적이 스텝 0의 흔적보다 앞서면 스텝 1은 그 뒤 것을 쓴다
    result, info, _ = _walk(2, {0: 0, 1: 1}, [_hit(1, 1), _hit(0, 4), _hit(1, 8)])
    assert [(k, ts) for k, ts, _ in info["evidence"]] == [(0, _ts(4)), (1, _ts(8))]


def test_walk_window_and_center_without_failed_step_hit():
    result, info, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 20), _hit(1, 50)], coverage_last=_ts(2000))
    assert result["start"] == BASE + timedelta(seconds=40)                 # L - pre_sec(10)
    assert result["fail"] == BASE + timedelta(seconds=50)                  # 실패 스텝 흔적이 없으면 마지막 일치 시각
    assert result["end"] == BASE + timedelta(seconds=50 + 900)             # L + max_span_sec(900)
    # 끝은 로그 범위로 자른다(버리지 않는다)
    result, _, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 20), _hit(1, 50)], coverage_last=_ts(300))
    assert result["end"] == BASE + timedelta(seconds=300)
    # 설정 가능: pre_sec·window.max_span_sec
    result, _, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 20), _hit(1, 50)], order={"pre_sec": 3}, window={"max_span_sec": 60})
    assert result["start"] == BASE + timedelta(seconds=47) and result["end"] == BASE + timedelta(seconds=110)


def test_walk_unobservable_steps_are_not_misses():
    result, info, _ = _walk(4, {0: 0, 1: None, 2: None, 3: 1}, [_hit(0, 5), _hit(1, 9)])
    assert result is not None
    assert (info["matched"], info["observable"], info["missed"], info["unobservable"]) == (2, 2, 0, 2)
    # 규칙 없는 스텝(키 없음)도 관측 불가
    result, info, _ = _walk(3, {0: 0, 2: 1}, [_hit(0, 5), _hit(1, 9)])
    assert info["unobservable"] == 1 and info["missed"] == 0
    # 관측 가능한 스텝이 하나도 없으면 앵커 없음
    result, info, _ = _walk(3, {}, [_hit(0, 5)])
    assert result is None and info["reason"] == "관측 가능한 PASS 스텝 없음"
    assert (info["matched"], info["observable"]) == (0, 0)


def test_walk_max_missing_and_last_observable_missed():
    rule_of = {0: 0, 1: 1, 2: 2}
    # 가운데 스텝 하나를 놓쳐도(max_missing 1) 앵커가 있다
    result, info, _ = _walk(3, rule_of, [_hit(0, 5), _hit(2, 20)])
    assert result is not None and (info["matched"], info["missed"]) == (2, 1)
    # 둘을 놓치면 없다
    result, info, _ = _walk(3, rule_of, [_hit(2, 20)])
    assert result is None and info["reason"] == "놓친 스텝 2개"
    result, _, _ = _walk(3, rule_of, [_hit(2, 20)], order={"max_missing": 2})
    assert result is not None
    # 마지막 관측 가능 스텝을 놓치면 없다
    result, info, _ = _walk(3, rule_of, [_hit(0, 5), _hit(1, 9)])
    assert result is None and info["reason"] == "마지막 관측 가능 스텝 미발견"
    # 마지막이 관측 불가면 그 앞 관측 가능 스텝이 기준
    result, _, _ = _walk(3, {0: 0, 1: 1, 2: None}, [_hit(0, 5), _hit(1, 9)])
    assert result is not None
    # min_matched
    result, info, _ = _walk(2, {0: 0, 1: 1}, [_hit(1, 5)], order={"min_matched": 2, "max_missing": 5})
    assert result is None and "일치한 스텝이 적다" in info["reason"]


def test_walk_repeated_sequence_gives_no_anchor():
    hits = [_hit(0, 5), _hit(1, 9), _hit(0, 100), _hit(1, 104)]          # 같은 순서가 두 번
    result, info, _ = _walk(2, {0: 0, 1: 1}, hits)
    assert result is None and "반복" in info["reason"]
    assert info["matched"] == 2                                          # 사유와 함께 첫 걸음의 집계는 남긴다
    # 일부만 반복(둘째 걸음이 덜 맞음)이면 앵커가 있다
    result, _, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 5), _hit(1, 9), _hit(0, 100)])
    assert result is not None and result["last_ts"] == BASE + timedelta(seconds=9)


def test_walk_observable_failed_step_tightens_end_and_centers_on_hit():
    # 실패 스텝(규칙 2)의 흔적 중 마지막 일치(9초) 뒤의 가장 이른 것(30초)이 중심, 끝은 +120초
    hits = [_hit(0, 5), _hit(1, 9), _hit(2, 3), _hit(2, 30), _hit(2, 60)]
    result, info, _ = _walk(2, {0: 0, 1: 1, 2: 2}, hits, coverage_last=_ts(1000))
    assert result["fail"] == BASE + timedelta(seconds=30) and result["failed_hit"] == BASE + timedelta(seconds=30)
    assert result["end"] == BASE + timedelta(seconds=150)
    assert result["start"] == BASE + timedelta(seconds=-1)
    # 로그가 더 일찍 끝나면 로그 끝
    result, _, _ = _walk(2, {0: 0, 1: 1, 2: 2}, hits, coverage_last=_ts(100))
    assert result["end"] == BASE + timedelta(seconds=100)


def test_walk_equal_timestamps_are_ordered_by_seq_and_result_is_deterministic():
    # 같은 시각의 흔적은 seq 순서: 스텝 1의 흔적(seq 3)은 스텝 0의 흔적(seq 5)보다 앞이라 쓸 수 없다
    result, info, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 5, seq=5), _hit(1, 5, seq=3)])
    assert result is None
    result, info, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 5, seq=3), _hit(1, 5, seq=5)])
    assert result is not None and [k for k, _, _ in info["evidence"]] == [0, 1]
    hits = [_hit(0, 5, 1), _hit(1, 9, 2), _hit(0, 100, 7), _hit(1, 3, 0), _hit(2, 40, 9)]
    first = _walk(2, {0: 0, 1: 1, 2: 2}, hits)
    for seed in range(5):
        shuffled = list(hits)
        random.Random(seed).shuffle(shuffled)
        assert _walk(2, {0: 0, 1: 1, 2: 2}, shuffled) == first


def test_walk_truncated_rule_gives_no_anchor():
    result, info, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 5), _hit(1, 9)], truncated_rules=[1])
    assert result is None and "상한" in info["reason"]
    result, _, _ = _walk(2, {0: 0, 1: 1}, [_hit(0, 5), _hit(1, 9)], truncated_rules=[7])      # 쓰지 않는 규칙
    assert result is not None


# -- 2. markers --step-events -------------------------------------------------------------------------


def _markers(db: Path, *extra, log=LOG) -> dict:
    return run_json("parse_logcat.py", ["markers", log, "--rules", db / "parser-rules", *TZ, *extra])


def test_markers_step_events_on_fixture_gives_labels_only():
    out = _markers(variant_db("issue-db-step-events"), "--step-events")
    assert out["warnings"] == [] and out["markers"] == []
    got = [(h["rule"], h["ts"], h["label"]) for h in out["step_events"]]
    assert got == [
        (4, "2026-09-20T05:30:02.000Z", "data_setting_changed"),            # 미끼(BOOT, enabled=true)
        (1, "2026-09-20T05:30:05.000Z", "ConnectivityService"),
        (2, "2026-09-20T05:30:20.000Z", "ConnectivityService"),
        (3, "2026-09-20T05:31:30.000Z", "UNSOL_RESPONSE_NETWORK_STATE_CHANGED"),
        (4, "2026-09-20T05:32:50.000Z", "data_setting_changed"),
        (5, "2026-09-20T05:33:03.000Z", "data_setting_changed"),            # enabled=false
        (1, "2026-09-20T05:34:10.000Z", "ConnectivityService"),            # 정리
    ]
    seqs = [h["seq"] for h in out["step_events"]]
    assert seqs == [1, 2, 4, 6, 7, 8, 14]
    assert set(out["step_events"][0]) == {"rule", "ts", "seq", "label"}
    assert "setAirplaneMode" not in json.dumps(out, ensure_ascii=False)         # 로그 본문은 나가지 않는다
    assert out["step_events"] == sorted(out["step_events"], key=lambda h: (h["ts"], h["seq"], h["rule"]))


def test_markers_without_flag_or_rules_is_unchanged():
    db = variant_db("issue-db-step-events")
    plain = _markers(db)
    assert "step_events" not in plain
    assert _markers(db, "--step-events")["step_events"]                           # 같은 입력, 플래그만 다름
    assert {k: v for k, v in _markers(db, "--step-events").items() if k != "step_events"} == plain
    assert _markers(SAMPLE, "--step-events")["step_events"] == []                 # 규칙이 없으면 빈 목록
    assert _markers(SAMPLE) == plain


def test_markers_step_events_invalid_rules_are_warnings_and_skipped():
    db = copy_db(variant_db("issue-db-step-events"))
    # 주석의 예시와 겹치지 않게 들여쓴 실제 규칙 줄만 바꾼다
    edit(db / "issue-db.config.yaml", "  - {pattern: '(?i)(망|network)\\s*등록', ril: UNSOL_RESPONSE_NETWORK_STATE_CHANGED}",
         "  - {pattern: '(?i)(망|network)\\s*등록', ril: UNSOL_RESPONSE_NETWORK_STATE_CHANGED, dir: sideways}")
    edit(db / "issue-db.config.yaml", "  - {pattern: '(?i)재부팅|reboot', match: '^(?:Zygote|AndroidRuntime): '}",
         "  - {pattern: '(?i)재부팅|reboot', match: '(', ril: DIAL}")
    out = _markers(db, "--step-events")
    assert sorted(w["code"] for w in out["warnings"]) == ["step-event-rule", "step-event-rule"]
    assert all(h["rule"] not in (3, 8) for h in out["step_events"]) and out["step_events"]


def test_markers_step_events_caps_per_rule():
    d = tmp("tt-cap-")
    lines = [f"09-20 14:30:{(i // 1000) % 60:02d}.{i % 1000:03d}  1234  1244 D ConnectivityService: setAirplaneMode enabled=true"
             for i in range(1100)]
    log = d / "many.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = _markers(variant_db("issue-db-step-events"), "--step-events", log=log)
    assert len([h for h in out["step_events"] if h["rule"] == 1]) == 1000
    warn = [w for w in out["warnings"] if w["code"] == "step-events-truncated"]
    assert len(warn) == 1 and warn[0]["truncated_rules"] == [1]


# -- 3. triage -----------------------------------------------------------------------------------------

STEP_NAMES = ["비행기 모드 켜기", "비행기 모드 끄기", "IMS 등록 확인", "망 등록 확인", "CP 파라미터 설정", "모바일 데이터 켜기",
              "데이터 연결 확인"]


def _report_html() -> str:
    rows = "".join(f"<tr><td>{i}</td><td>{name}</td><td>{'FAIL' if i == 7 else 'PASS'}</td><td></td></tr>"
                   for i, name in enumerate(STEP_NAMES, 1))
    return ("<html><head><style>td{x}</style><script>var s = '비행기 모드 켜기 FAIL';</script></head><body>"
            "<table><tr><td>Overall result</td><td>FAIL</td></tr></table>"
            f"<table><tr><th>No</th><th>Step</th><th>Result</th><th>Comment</th></tr>{rows}</table></body></html>")


def _zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("index.html", "<table><tr><td>1</td><td>가짜</td><td>FAIL</td></tr></table>")
        zf.writestr("run_01/report.html", _report_html())
    return path


def _paste(path: Path) -> Path:
    path.write_text("".join(f"Step {i}: {name} {'FAIL' if i == 7 else 'PASS'}\n" for i, name in enumerate(STEP_NAMES, 1)),
                    encoding="utf-8")
    return path


def _offline(db: Path, steps: Path | None, *extra, occurred="2026-09-20T14:31:00+09:00", name="job"):
    out = tmp("tt-order-") / name
    meta = out.parent / "meta.json"
    meta.write_text(json.dumps({"key": KEY, "occurred_at": occurred, "summary": ""}), encoding="utf-8")
    args = ["run", KEY, "--offline-db", db, "--out", out, "--logs", LOG, "--jira-meta", meta, *TZ, *extra]
    if steps is not None:
        args += ["--steps-file", steps]
    return run_json("triage.py", args), out


def _causes(analysis: dict) -> list[str]:
    return [c["cause"] for c in analysis.get("candidates") or []]


def _strip(a: dict) -> dict:
    return {k: v for k, v in a.items() if k not in ("generated_at", "files", "request_hash")}


def test_triage_aligns_failure_window_by_step_order_without_any_clock():
    db = variant_db("issue-db-step-events")
    done, job = _offline(db, _zip(tmp("tt-zip-") / "att.zip"))
    sa = done["step_anchor"]
    assert sa["source"] == "step_order" and sa["step"] == "7 | 데이터 연결 확인"
    assert sa["order"] == {"matched": 4, "observable": 4, "missed": 0,
                           "last": {"step": "6 | 모바일 데이터 켜기", "ts": "2026-09-20T05:32:50.000Z"}}
    assert "clock" not in sa
    assert done["logs"]["window"] == {"start": "2026-09-20T05:32:40.000Z", "end": "2026-09-20T05:34:10.000Z"}
    assert _causes(done) == ["DATA-001-01"]                                  # 이른 IMS 403은 구간 밖
    assert not any("스텝 순서 정렬 안 함" in w for w in done.get("warnings") or [])
    assert done["jira"]["failed_step"] == {"text": "7 | 데이터 연결 확인", "source": "steps_file"}
    assert len((job / "analysis.json").read_bytes()) <= 4096
    meta = json.loads((job / "match_meta.json").read_text(encoding="utf-8"))
    assert meta["occurred_at"] == "2026-09-20T05:32:50.000Z"                 # 실패 스텝 흔적이 없으면 마지막 일치 시각
    report = (job / "report.md").read_text(encoding="utf-8")
    assert ("- 실패 스텝 구간 (step_order): 7 | 데이터 연결 확인 — 마지막 확인 스텝 6 | 모바일 데이터 켜기 "
            "2026-09-20T05:32:50.000Z 이후 → 분석 범위 2026-09-20T05:32:40.000Z ~ 2026-09-20T05:34:10.000Z "
            "(관측 가능 4개 중 4개 일치, 놓침 0, 관측 불가 2)") in report
    assert "  - 4 | 망 등록 확인 → 2026-09-20T05:31:30.000Z UNSOL_RESPONSE_NETWORK_STATE_CHANGED" in report
    assert "  - 1 | 비행기 모드 켜기 → 2026-09-20T05:30:05.000Z ConnectivityService" in report
    assert "- 시험 절차: zip 안 run_01/report.html" in report
    # Jira 발생 시각은 분석 범위 밖: 그 근처 오류 이벤트는 개수·표본만 알리고 근거·점수에는 쓰지 않는다
    assert sa["outside_errors"] == 2 and "outside_errors" not in json.dumps(done["candidates"])
    assert "- 분석 범위 밖 오류 이벤트 (Jira 발생 시각 " in report and "ims_registration_failed" in report
    assert "근거·점수에 쓰지 않음): 2건" in report
    # 끄면(anchor=off) 오늘의 동작: Jira 시각 ±5분 → IMS-001-01이 1위
    off, off_job = _offline(db, _zip(tmp("tt-zip-") / "att.zip"), "--answer", "anchor=off")
    assert _causes(off)[0] == "IMS-001-01" and "order" not in off.get("step_anchor", {})
    assert "outside_errors" not in off.get("step_anchor", {})                 # 앵커가 없으면 키도 없다
    # 스텝 이름·HTML 문구는 하위 스크립트 인자(trace.jsonl)와 상태 파일에 없다. markers 호출은 한 번, 플래그만 붙는다
    trace = (job / "trace.jsonl").read_text(encoding="utf-8")
    for text in (*STEP_NAMES, "Overall result", "report.html", "가짜"):
        assert text not in trace, text
    calls = [json.loads(line) for line in trace.splitlines() if json.loads(line).get("step") == "3-markers"]
    assert len(calls) == 1 and "--step-events" in calls[0]["args"]
    state = job / "triage-state.json"
    assert not state.exists() or not any(t in state.read_text(encoding="utf-8") for t in STEP_NAMES)


def test_triage_paste_text_gives_same_result_as_html():
    db = variant_db("issue-db-step-events")
    html, _ = _offline(db, _zip(tmp("tt-zip-") / "att.zip"))
    paste, job = _offline(db, _paste(tmp("tt-paste-") / "steps-pasted.txt"))
    assert _strip(paste)["step_anchor"] == _strip(html)["step_anchor"]
    assert _causes(paste) == _causes(html) and paste["logs"] == html["logs"]
    assert "- 시험 절차: zip" not in (job / "report.md").read_text(encoding="utf-8")


def test_triage_falls_back_to_jira_window_when_no_step_events_in_db():
    done, job = _offline(SAMPLE, _zip(tmp("tt-zip-") / "att.zip"))
    assert done["step_anchor"] == {"source": "jira", "order": {"matched": 0, "observable": 0, "missed": 0,
                                                              "reason": "관측 가능한 PASS 스텝 없음"}}
    assert "스텝 순서 정렬 안 함: 관측 가능한 PASS 스텝 없음 — Jira 발생 시각 기준으로 분석했다" in done["warnings"]
    assert done["logs"]["window"] == {"start": "2026-09-20T05:26:00.000Z", "end": "2026-09-20T05:36:00.000Z"}
    assert _causes(done)[0] == "IMS-001-01" and not (job / "match_meta.json").exists()
    steps = [json.loads(line).get("step") for line in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    trace = [json.loads(line) for line in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "3-markers" in steps and not any("--step-events" in str(r.get("args")) for r in trace)       # 규칙이 없으면 플래그도 없다


def test_triage_order_failure_reasons_fall_back_with_warning():
    db = variant_db("issue-db-step-events")
    only_fail = tmp("tt-p-") / "p.txt"
    only_fail.write_text("Step 1: 데이터 연결 확인 FAIL\n", encoding="utf-8")     # 앞선 PASS 스텝이 없다 — 시도하지 않는다
    done, _ = _offline(db, only_fail)
    assert done["step_anchor"] == {"source": "jira"} and not any("스텝 순서" in w for w in done.get("warnings") or [])
    # 마지막 관측 가능 스텝(데이터 켜기)의 흔적이 없는 로그(앞부분만)
    short = tmp("tt-s-") / "short.log"
    short.write_text("".join(line + "\n" for line in LOG.read_text(encoding="utf-8").splitlines()[:7]), encoding="utf-8")
    out = tmp("tt-order-") / "x"
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": KEY, "occurred_at": "2026-09-20T14:31:00+09:00", "summary": ""}), encoding="utf-8")
    done = run_json("triage.py", ["run", KEY, "--offline-db", db, "--out", out, "--logs", short, "--jira-meta", meta, *TZ,
                                  "--steps-file", _paste(tmp("tt-paste-") / "p.txt")])
    assert done["step_anchor"]["source"] == "jira" and done["step_anchor"]["order"]["reason"] == "마지막 관측 가능 스텝 미발견"
    assert "스텝 순서 정렬 안 함: 마지막 관측 가능 스텝 미발견 — Jira 발생 시각 기준으로 분석했다" in done["warnings"]


def test_triage_without_steps_file_has_no_clock_order_or_markers_call():
    db = variant_db("issue-db-step-events")
    done, job = _offline(db, None)
    assert "step_anchor" not in done
    steps = [json.loads(line).get("step") for line in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "3-markers" not in steps
    assert "order" not in json.dumps(done.get("step_anchor", {})) and "clock" not in done


def test_fit_drops_order_last_before_clock_reason_before_focus():
    import importlib
    triage = importlib.import_module("triage")

    def make(n: int) -> dict:
        return {"jira": {"summary": "s" * n}, "files": {"report": "r"},
                "step_anchor": {"source": "step_order", "step": "7", "focus": ["DATA-001"],
                                "order": {"matched": 4, "observable": 4, "missed": 0,
                                          "last": {"step": "6 | " + "가" * 30, "ts": "2026-09-20T05:32:50.000Z"}},
                                "clock": {"mode": "none", "reason": "시계 차 모름"}}}

    def size(r: dict) -> int:
        return len(triage.dumps(r).encode("utf-8")) + 1   # analysis.json 파일 바이트(끝 개행 포함)

    n = 3000
    while size(make(n)) <= triage.ANALYSIS_MAX:
        n += 1
    fitted = triage.fit(make(n))                # 겨우 넘친다 → order.last만 버린다
    sa = fitted["step_anchor"]
    assert "last" not in sa["order"] and sa["clock"]["reason"] == "시계 차 모름" and sa["focus"] == ["DATA-001"]
    assert fitted["truncated"] is False
    m = n
    while True:                                  # order.last를 버려도 겨우 넘치는 크기
        probe = make(m)
        probe["step_anchor"]["order"].pop("last")
        if size(probe) > triage.ANALYSIS_MAX:
            break
        m += 1
    over = triage.fit(make(m))                   # 더 넘치면 clock.reason도 버린다(focus는 남는다)
    assert "reason" not in over["step_anchor"]["clock"] and over["step_anchor"]["focus"] == ["DATA-001"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
