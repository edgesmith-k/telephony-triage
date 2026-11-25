#!/usr/bin/env python3
"""5-1·5-2 입력 보강: `triage.py window`(마스킹 사본의 시각 둘레 줄)와 흐름 판정 요약(`report.flow_brief`·`flow_head`).

window는 오프라인 `triage.py run`(합성 `ipc-lookat.log` + tags.yaml에 없는 태그 한 줄)을 끝까지 돌린 JOB으로 본다.
흐름 요약은 합성 `flow.json`으로 본다. `pytest tests/test_explore_window.py`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, run, run_json, tmp  # noqa: E402
from common import evidence  # noqa: E402
from triagelib import core, report  # noqa: E402

KEY = "MOCK-9001"
LOG = REPO / "tests" / "fixtures" / "logs" / "ipc-lookat.log"
HIDDEN = "09-20 14:33:05.200   900   977 E HIDDENTAG: carrier link lost on rmnet_data3"     # tags.yaml에 없는 태그
HIDDEN_ROW = "05:33:05.200 - E HIDDENTAG carrier link lost on rmnet_data3"
AT = "2026-09-20T05:33:05Z"


def _job(explore: bool = True) -> Path:
    out = tmp("tt-win-") / "j"
    log = out.parent / "in.log"
    lines = LOG.read_text(encoding="utf-8").splitlines()
    k = next(i for i, x in enumerate(lines) if x.startswith("09-20 14:33:05.400"))
    log.write_text("\n".join(lines[:k] + [HIDDEN] + lines[k:]) + "\n", encoding="utf-8")
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": KEY, "summary": "", "occurred_at": "2026-09-20T14:34:00+09:00"}), encoding="utf-8")
    run_json("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", out, "--logs", log, "--issue-meta", meta,
                           "--tz", "Asia/Seoul", "--year", "2026", "--explore"])
    if explore:
        run_json("triage.py", ["explore", KEY, "--out", out])
    return out


def _window(job: Path, *extra, expect=0):
    proc = run("triage.py", ["window", KEY, "--out", job, *map(str, extra)])
    assert proc.returncode == expect, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_window_serves_dropped_tag_lines_in_timeline_form():
    job = _job()
    main, _, block = (job / "timeline.md").read_text(encoding="utf-8").partition("\n## 이상 줄")
    assert HIDDEN_ROW not in main and HIDDEN_ROW in block      # 파서가 버린 줄(tags.yaml 밖): 본 줄엔 없고 이상 줄 절(E)에만
    out = _window(job, "--at", AT, "--lines", 6)
    assert out == {"window": "window-1.md", "path": str(job / "window-1.md"), "lines": 6, "at": "2026-09-20T05:33:05.000Z",
                   "left": core.WINDOWS_MAX - 1}
    text = (job / "window-1.md").read_text(encoding="utf-8")
    rows = [x for x in text.split("\n") if evidence.ROW_RX.match(x)]
    assert len(rows) == 6 and HIDDEN_ROW in rows                                      # 시각(UTC)·슬롯·레벨·태그·메시지
    assert "05:33:05.000 - D RIL [TX] VIPC_SETUP_DATA, REQ, token=0x0de, len=24" in rows   # 타임라인과 같은 시각 변환
    assert rows == sorted(rows)
    rec = json.loads((job / core.WINDOW_RECORD).read_text(encoding="utf-8"))["windows"]
    assert rec == [{"path": "window-1.md", "sha256": hashlib.sha256((job / "window-1.md").read_bytes()).hexdigest(),
                    "at": "2026-09-20T05:33:05.000Z", "lines": 6, "tags": []}]
    tagged = _window(job, "--at", "2026-09-20T14:33:05+0900", "--tag", "HIDDENTAG")    # 오프셋 +0900(3.10 fromisoformat 밖)
    assert tagged["window"] == "window-2.md" and tagged["lines"] == 1
    assert HIDDEN_ROW in (job / "window-2.md").read_text(encoding="utf-8")


def test_window_gate_limits_and_usage():
    job = _job(explore=False)
    assert _window(job, "--at", AT, expect=1)["reason"] == "해당 없음"      # 탐색·심층을 시작하기 전
    run_json("triage.py", ["explore", KEY, "--out", job])
    for bad in (("--at", "어제 저녁"), ("--at", AT, "--lines", 201), ("--at", AT, "--tag", "a b"),
                ("--at", "2020-01-01T00:00:00Z"), ("--at", AT, "--span", 0), ("--at", AT, "--slot", -1),
                ("--at", AT, "--cat", "Data!"), ("--at", AT, "--grep", "x" * 201), ("--at", AT, "--grep", "(")):
        # 못 읽는 시각·줄 상한·태그 형식·로그 범위 밖·구간·슬롯·카테고리 형식·정규식 길이·정규식 오류
        assert _window(job, *bad, expect=2)["reason"] == "사용 오류", bad
    for _ in range(core.WINDOWS_MAX):
        _window(job, "--at", AT, "--lines", 2)
    assert _window(job, "--at", AT, expect=1)["reason"] == "구간 상한"
    assert not (job / f"window-{core.WINDOWS_MAX + 1}.md").exists()


def test_window_skips_raw_only_files_and_new_run_drops_windows():
    job = _job()
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    analysis["logs"]["masked"]["skipped"] = ["big.log"]      # 상한 초과로 사본이 없던 파일(원문만)
    (job / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    out = _window(job, "--at", AT)
    assert out["skipped"] == ["big.log"]
    assert "마스킹 사본이 없어 보여 주지 않는 파일(원문만): big.log" in (job / "window-1.md").read_text(encoding="utf-8")
    analysis["logs"]["masked"]["files"] = []
    (job / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    assert _window(job, "--at", AT, expect=1)["reason"] == "마스킹 사본 없음"
    assert core.WINDOW_RECORD in core.STALE_FILES and "window-1.md" in core.STALE_FILES     # 새 run이 지운다


def test_window_at_uses_time_answer_conversion_and_filters():
    """`--at`: 타임라인 시각만(UTC, 분석 범위 날짜)·오프셋 있는 ISO·logcat 스탬프(run의 --tz Asia/Seoul) — 출력은 UTC.
    오프셋 없는 ISO는 사용 오류(로그 시간대를 짐작하지 않는다)."""
    job = _job()
    for at in ("05:33:05.000", "09-20 14:33:05.000", "2026-09-20 14:33:05.000 +0900", "2026-09-20T14:33:05+0900", AT):
        assert _window(job, "--at", at, "--lines", 2)["at"] == "2026-09-20T05:33:05.000Z", at
    assert "Z 또는 오프셋" in run("triage.py", ["window", KEY, "--out", job, "--at", "2026-09-20T05:33:05"]).stderr
    job = _job()
    span = _window(job, "--at", AT, "--span", 1)            # ±0.5초: 05:33:04.5~05:33:05.5
    rows = [x for x in (job / span["window"]).read_text(encoding="utf-8").split("\n") if evidence.ROW_RX.match(x)]
    assert rows and all("05:33:04.5" <= x[:12] <= "05:33:05.500" for x in rows) and HIDDEN_ROW in rows
    assert _window(job, "--at", AT, "--span", 60, "--lines", 3)["lines"] == 3          # 둘 다면 적은 쪽
    grep = _window(job, "--at", AT, "--grep", r"carrier link \w+")
    assert grep["lines"] == 1 and HIDDEN_ROW in (job / grep["window"]).read_text(encoding="utf-8")
    rec = json.loads((job / core.WINDOW_RECORD).read_text(encoding="utf-8"))["windows"]
    assert rec[-1]["grep"] == r"carrier link \w+" and rec[-2]["span"] == 60


def test_window_slot_and_category_filters():
    job = _job()
    out = _window(job, "--at", AT, "--slot", 1, "--lines", 200)       # p0 줄은 빠지고 슬롯 모름(-) 줄은 남는다
    rows = [x for x in (job / out["window"]).read_text(encoding="utf-8").split("\n") if evidence.ROW_RX.match(x)]
    assert rows and all(x.split(" ")[1] == "-" for x in rows)
    cat = _window(job, "--at", AT, "--cat", "common", "--lines", 200)  # tags.yaml: RIL → common, HIDDENTAG는 매핑 없음
    rows = [x for x in (job / cat["window"]).read_text(encoding="utf-8").split("\n") if evidence.ROW_RX.match(x)]
    assert rows and all(x.split(" ")[3] == "RIL" for x in rows)
    assert _window(job, "--at", AT, "--cat", "nosuchcat", expect=1)["reason"] == "줄 없음"


def test_parse_at_clock_uses_window_date_across_midnight():
    from triagelib.window import parse_at

    ev = {"input": {"tz": "Asia/Seoul", "year": 2026,
                    "window": {"start": "2026-09-20T23:58:00.000Z", "end": "2026-09-21T00:03:00.000Z"}}}
    assert parse_at("23:59:01.5", ev)[0].isoformat() == "2026-09-20T23:59:01.500000+00:00"
    assert parse_at("00:01:00", ev)[0].isoformat() == "2026-09-21T00:01:00+00:00"       # 자정 뒤 날
    assert parse_at("12:00:00", ev)[0] is None and "안에 없다" in parse_at("12:00:00", ev)[1]
    assert parse_at("2026-09-20T23:59:01", ev)[0] is None                                 # 오프셋 없는 ISO
    long = {"input": {"window": None}, "coverage": {"first_ts": "2026-09-20T00:00:00.000Z", "last_ts": "2026-09-22T00:00:00.000Z"}}
    assert parse_at("10:00:00", long)[0] is None and "여럿" in parse_at("10:00:00", long)[1]    # 날이 둘 이상: 모호
    assert parse_at("25:00:00", ev)[0] is None and parse_at("10:00:00", {"input": {}})[0] is None


# -- 흐름 판정 요약 ---------------------------------------------------------------------------------------------

def _inst(key, start, steps):
    return {"key": key, "start_ts": start, "line_ref": None, "restarts": 0, "later_step": None, "end": None, "notes": [],
            "then": None, "steps": [{"id": i, "verdict": v, "detail": "", "line_ref": None, "ts": ts, "bad_count": 0}
                                    for i, v, ts in steps]}


FLOW = {"schema": 1, "warnings": [], "flows": [{
    "flow": "data/setup", "title": "데이터 연결", "platform_versions": [], "then": None, "truncated": False,
    "steps": [{"id": "req", "title": "요청", "suspect": "x"}, {"id": "resp", "title": "응답", "suspect": "y"}],
    "instances": [_inst("datad", "2026-09-20T05:32:01.000Z", [("req", "ok", "2026-09-20T05:32:01.500Z"), ("resp", "ok", "2026-09-20T05:32:02.000Z")]),
                  _inst("datad", "2026-09-20T05:32:08.000Z", [("req", "ok", "2026-09-20T05:32:08.500Z"), ("resp", "없음", None)]),
                  _inst("datad", "2026-09-20T06:40:00.000Z", [("req", "값이상", "2026-09-20T06:40:01.000Z"), ("resp", "-", None)])]}]}
EVENTS = {"events": [{"ts": "2026-09-20T05:32:09.000Z", "tag": "ofonod", "msg": "gprs attach failed", "level": "E", "event": None}],
          "input": {"window": {"start": "2026-09-20T05:27:00Z", "end": "2026-09-20T05:37:00Z"}}}
HEAD_BAD = "- 흐름 판정(스크립트 기대 순서, 데이터): 데이터 연결(data/setup) datad: 벗어남 — 첫 벗어난 단계 응답(resp) 없음 05:32:08.500"
HEAD_OK = "- 흐름 판정(스크립트 기대 순서, 데이터): 데이터 연결(data/setup) datad: 정상 — 끝까지 정상(시작 05:32:01.000)"


def test_flow_brief_orders_deviation_first_inside_window(tmp_path):
    (tmp_path / "flow.json").write_text(json.dumps(FLOW, ensure_ascii=False), encoding="utf-8")
    brief = report.flow_brief(tmp_path, EVENTS, "2026-09-20T05:32:09Z")
    assert brief == [{"flow": "data/setup", "key": "datad", "result": "벗어남", "at": "2026-09-20T05:32:08.500Z", "step": "resp",
                      "title": "응답", "verdict": "없음", "flow_title": "데이터 연결"},
                     {"flow": "data/setup", "key": "datad", "result": "정상", "at": "2026-09-20T05:32:01.000Z",
                      "flow_title": "데이터 연결"}]          # 범위 밖(06:40) 인스턴스는 뺀다
    assert report.flow_head(brief) == [HEAD_BAD, HEAD_OK]
    text = report.timeline(KEY, EVENTS, None, 200, flows=report.flow_head(brief))[0]
    assert HEAD_BAD in text and evidence.source_text(text)[0].count("\n") == 0       # 머리 줄은 근거 원문이 아니다


def test_no_flow_file_keeps_timeline_bytes(tmp_path):
    assert report.flow_brief(tmp_path, EVENTS) == [] and report.flow_head([]) == []
    before = report.timeline(KEY, EVENTS, "2026-09-20T05:32:09Z", 200)
    assert report.timeline(KEY, EVENTS, "2026-09-20T05:32:09Z", 200, flows=report.flow_head(report.flow_brief(tmp_path, EVENTS))) == before


def test_grep_without_span_stays_inside_analysis_window():
    """리뷰 7: `--span` 없는 `--grep`은 로그 전체가 아니라 분석 범위(events.json input.window) 안만 찾는다."""
    job = _job()
    path = job / "events.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["input"]["window"] = {"start": "2026-09-20T05:33:10.000Z", "end": "2026-09-20T05:34:00.000Z"}   # HIDDEN(05:33:05)은 밖
    path.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    assert _window(job, "--at", AT, "--grep", r"carrier link \w+", expect=1)["reason"] == "줄 없음"
    assert _window(job, "--at", AT, "--grep", r"carrier link \w+", "--span", 60)["lines"] == 1


def test_normalize_ts_reads_any_fraction_width():
    """리뷰 7: 3.10 fromisoformat은 초 소수 3·6자리만 읽는다 — 1·2·4·5·7자리도 6자리로 맞춰 읽는다."""
    from common import logtime

    for text, want in (("05:33:05.5Z", "05:33:05.500"), ("05:33:05.12Z", "05:33:05.120"), ("05:33:05.1234Z", "05:33:05.123"),
                       ("14:33:05.12345+0900", "05:33:05.123"), ("05:33:05.1234567Z", "05:33:05.123"), ("05:33:05Z", "05:33:05.000")):
        assert logtime.format_ts(logtime.normalize_ts("2026-09-20T" + text, "UTC", 2026))[11:23] == want, text
