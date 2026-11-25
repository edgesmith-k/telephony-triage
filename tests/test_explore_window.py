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
    sys.path.insert(0, str(REPO / "tests"))
    from test_explore_anomaly import no_summary
    main, _, block = no_summary((job / "timeline.md").read_text(encoding="utf-8")).partition("\n## 이상 줄")
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
    _window(job, "--at", AT, "--lines", 2)
    rec = json.loads((job / core.WINDOW_RECORD).read_text(encoding="utf-8"))      # 상한(50)까지 부르는 대신 기록을 채운다
    rec["windows"] = rec["windows"] * core.WINDOWS_MAX
    (job / core.WINDOW_RECORD).write_text(json.dumps(rec), encoding="utf-8")
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
    text = (job / grep["window"]).read_text(encoding="utf-8")
    assert grep["lines"] == 1 and HIDDEN_ROW in text
    # G-2: 구간 파일 머리에 고른 줄의 날짜 포함 처음·끝 시각(게이트 4가 읽는다), 줄 모양(인용 대조 대상)은 그대로
    from triagelib import window
    m = window.LINE_TS_RE.search(text)
    assert m and m.group(1) == m.group(2) and m.group(2).startswith("2026-09-20T" + HIDDEN_ROW[:12]), text
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


def test_grep_without_span_searches_whole_log():
    """`--span` 없는 `--grep`은 분석 범위 밖도 찾는다(11/25 사용자 결정: 탐색은 최후의 보루 — 리뷰 7의 분석 범위 제한을 뒤집음)."""
    job = _job()
    path = job / "events.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["input"]["window"] = {"start": "2026-09-20T05:33:10.000Z", "end": "2026-09-20T05:34:00.000Z"}   # HIDDEN(05:33:05)은 밖
    path.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    assert _window(job, "--at", AT, "--grep", r"carrier link \w+")["lines"] == 1
    assert _window(job, "--at", AT, "--grep", r"carrier link \w+", "--span", 60)["lines"] == 1


def test_parse_at_clock_falls_back_to_whole_log_and_grep_timeout_suggests_span(monkeypatch):
    """11/25 리뷰: 시각만 쓴 `--at`이 분석 범위 밖이면 로그 전체(coverage)에서 날을 찾는다(탐색은 구간 밖 사본 줄도 본다).
    `--grep` 시간 초과 안내는 `--span`으로 좁히는 길도 준다."""
    import types

    from common import patterns
    from triagelib import window

    ev = {"input": {"window": {"start": "2026-09-20T05:33:10.000Z", "end": "2026-09-20T05:34:00.000Z"}},
          "coverage": {"first_ts": "2026-09-20T05:00:00.000Z", "last_ts": "2026-09-20T06:00:00.000Z"}}
    assert window.parse_at("05:33:30", ev)[0].isoformat() == "2026-09-20T05:33:30+00:00"
    assert window.parse_at("05:10:00", ev)[0].isoformat() == "2026-09-20T05:10:00+00:00"       # 분석 범위 밖, 로그 안
    assert "안에 없다" in window.parse_at("07:00:00", ev)[1]

    class Slow:
        def __init__(self, *_a):
            pass

        def __enter__(self):
            raise patterns.PatternTimeout("(a+)+$", 1)

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(patterns, "PatternRunner", Slow)
    args = types.SimpleNamespace(tag=None, slot=None, cat=None, grep="(a+)+$")
    try:
        window._narrow(args, [{"tag": "T", "msg": "aaa"}], Path("."), {})
    except window._Stop as stop:
        assert "--span" in stop.detail
    else:
        raise AssertionError("시간 초과가 사용 오류가 아니다")


def test_normalize_ts_reads_any_fraction_width():
    """리뷰 7: 3.10 fromisoformat은 초 소수 3·6자리만 읽는다 — 1·2·4·5·7자리도 6자리로 맞춰 읽는다."""
    from common import logtime

    for text, want in (("05:33:05.5Z", "05:33:05.500"), ("05:33:05.12Z", "05:33:05.120"), ("05:33:05.1234Z", "05:33:05.123"),
                       ("14:33:05.12345+0900", "05:33:05.123"), ("05:33:05.1234567Z", "05:33:05.123"), ("05:33:05Z", "05:33:05.000")):
        assert logtime.format_ts(logtime.normalize_ts("2026-09-20T" + text, "UTC", 2026))[11:23] == want, text


# --- R-30(11/25 리뷰 2-4): `--at` 현지 시각·연도 없는 스탬프·oFono syslog ---------------------------------------------

def test_parse_at_reads_local_clock_year_and_syslog():
    from triagelib.window import parse_at

    ev = {"input": {"tz": "Asia/Seoul", "year": None,
                    "window": {"start": "2026-09-20T05:29:00.000Z", "end": "2026-09-20T05:39:00.000Z"}},
          "coverage": {"first_ts": "2026-09-20T05:00:00.000Z", "last_ts": "2026-09-20T06:00:00.000Z"}}
    want = "2026-09-20T05:33:05+00:00"
    assert parse_at("05:33:05", ev)[0].isoformat() == want                         # 타임라인(UTC) 시각
    assert parse_at("14:33:05", ev)[0].isoformat() == want                         # 사본(현지 KST) 시각 — 예전엔 범위 밖 오류
    assert parse_at("09-20 14:33:05.000", ev)[0].isoformat() == want               # 연도 없는 스탬프: 범위 첫 시각의 연도(2000 아님)
    assert parse_at("Sep 20 14:33:05", ev)[0].isoformat() == want                  # oFono syslog(BSD) 모양
    assert parse_at("Sep 20 14:33:05.25", ev)[0].isoformat() == "2026-09-20T05:33:05.250000+00:00"
    both = {"input": {"tz": "Asia/Seoul", "window": None},
            "coverage": {"first_ts": "2026-09-20T00:00:00.000Z", "last_ts": "2026-09-20T23:00:00.000Z"}}
    dt, why = parse_at("10:00:00", both)            # UTC 10:00·KST 10:00(=01:00Z) 둘 다 로그 안: 가를 줄이 없으면 UTC(C-4 — 거부하지 않음)
    assert dt.isoformat() == "2026-09-20T10:00:00+00:00" and "UTC로 읽음" in why
    utc = {"input": {"tz": "UTC", "window": None}, "coverage": both["coverage"]}
    assert parse_at("10:00:00", utc)[0].isoformat() == "2026-09-20T10:00:00+00:00"   # UTC 작업은 예전과 같다


def test_window_head_shows_given_and_converted_center():
    job = _job()
    out = _window(job, "--at", "14:33:05", "--lines", 2)                   # 작업 tz Asia/Seoul — 사본 시각 그대로
    assert out["at"] == "2026-09-20T05:33:05.000Z"
    assert "- 중심: 2026-09-20T05:33:05.000Z (받은 값 14:33:05)" in (job / out["window"]).read_text(encoding="utf-8")
    same = _window(job, "--at", "2026-09-20T05:33:05.000Z", "--lines", 2)
    assert "받은 값" not in (job / same["window"]).read_text(encoding="utf-8")


# --- R-21(11/25 리뷰 4-1): 탐색 중 `run --look-at`을 다시 해도 탐색 타임라인이 남는다 ------------------------------------

def test_rerun_during_explore_rebuilds_timeline():
    job = _job()
    meta, log = job.parent / "m.json", job.parent / "in.log"
    args = ["run", KEY, "--offline-db", SAMPLE, "--out", job, "--logs", log, "--issue-meta", meta, "--tz", "Asia/Seoul",
            "--year", "2026", "--explore", "--look-at-source", "model", "--look-at", "carrier link lost on rmnet_data3"]
    proc = run("triage.py", args)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "ok"                                    # 출력은 run JSON 하나 그대로
    text = (job / "timeline.md").read_text(encoding="utf-8")
    assert "기준 줄(모델이 코멘트에서 고른 지점" in text                               # 새 explore 입력(새 기준)으로 다시 만들었다
    assert core.EXPLORE_DONE_LINE.split("{")[0] in (job / "report.md").read_text(encoding="utf-8")
    assert _window(job, "--at", AT, "--lines", 2)["lines"] == 2                       # 탐색을 시작한 작업으로 본다
    fresh = _job(explore=False)                                                        # explore 전이면 run이 만들지 않는다
    args[5], args[7], args[9] = fresh, fresh.parent / "in.log", fresh.parent / "m.json"
    assert run("triage.py", args).returncode == 0 and not (fresh / "timeline.md").exists()


# --- 11/25 확인 리뷰 고침(C-4·C-5) -------------------------------------------------------------------------------

def test_c04_ambiguous_clock_is_read_not_refused():
    """C-4: 작업 tz가 UTC가 아니고 로그가 길어 UTC·현지 둘 다 범위 안이면 거부하지 않는다 — 가를 근거가 없으면 UTC(옛 동작),
    가르는 함수(`pick`)가 현지라 하면 현지 시각. 읽은 쪽은 둘째 값(머리 `중심`에 적는다)."""
    from triagelib.window import parse_at

    ev = {"input": {"tz": "Asia/Seoul", "window": {"start": "2026-11-10T08:03:00.000Z", "end": "2026-11-10T08:13:00.000Z"}},
          "coverage": {"first_ts": "2026-11-10T02:00:00.000Z", "last_ts": "2026-11-10T14:00:00.000Z"}}
    dt, note = parse_at("11:30:00.000", ev)
    assert dt.isoformat() == "2026-11-10T11:30:00+00:00" and "UTC" in note
    dt, note = parse_at("11:30:00.000", ev, lambda utc, local: False)
    assert dt.isoformat() == "2026-11-10T02:30:00+00:00" and "Asia/Seoul" in note
    assert parse_at("08:09:42.442", ev) == (parse_at("08:09:42.442", ev)[0], None)      # 분석 범위 안(UTC 하나): 적을 것 없음


def test_c04_window_reads_clock_by_where_the_line_is():
    """C-4: 타임라인에 그 시각으로 시작하는 줄이 있으면 UTC, 사본에만 있으면 현지 시각. 머리 `중심`에 어느 쪽으로 읽었는지."""
    job = _job()
    path = job / "events.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    ev["input"]["window"] = None
    ev["coverage"] = {"first_ts": "2026-09-20T00:00:00.000Z", "last_ts": "2026-09-20T23:00:00.000Z"}
    path.write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    out = _window(job, "--at", "05:33:05.000", "--lines", 2)              # 타임라인 줄(UTC)
    assert out["at"] == "2026-09-20T05:33:05.000Z"
    assert "UTC로 읽음" in (job / out["window"]).read_text(encoding="utf-8")
    out = _window(job, "--at", "14:33:05.200", "--lines", 2)              # HIDDEN 줄의 사본(KST) 시각 — 타임라인엔 없다
    assert out["at"] == "2026-09-20T05:33:05.200Z"
    assert "Asia/Seoul 현지 시각으로 읽음" in (job / out["window"]).read_text(encoding="utf-8")


def test_c05_rerun_during_explore_says_what_to_get_again():
    """C-5: 탐색 중 run(--look-at)이 지운 모듈 보기·심층 분석(5-1) 결과 — 낡은 결과는 남기지 않고(지운다), run 출력 `next`가
    모듈 보기를 다시 받는 명령과 받은 심층 분석 줄을 답에 다시 적으라고 알린다."""
    job = _job()
    (job / "deep-output.md").write_text("원인 층: x\n", encoding="utf-8")
    (job / "check-output.json").write_text(json.dumps({"deep": {"mode": "module", "at": "x", "output_sha256": "0"}}),
                                           encoding="utf-8")
    (job / "module-skill" / "explore").mkdir(parents=True)
    (job / "module-skill" / "explore" / "timeline.md").write_text("x\n", encoding="utf-8")
    (job / "module-skill.json").write_text(json.dumps({"explore": {"module": "android/data", "sha": "a" * 40}}), encoding="utf-8")
    meta, log = job.parent / "m.json", job.parent / "in.log"
    out = run_json("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", job, "--logs", log, "--issue-meta", meta, "--tz",
                                 "Asia/Seoul", "--year", "2026", "--explore", "--look-at-source", "model", "--look-at",
                                 "carrier link lost on rmnet_data3"])
    assert (job / "timeline.md").is_file() and not (job / "deep-output.md").exists() and not (job / "module-skill").exists()
    assert f"triage.py module {KEY} --for explore --module android/data" in out["next"] and "- 심층 분석" in out["next"]
    deep = [x for x in (job / "report.md").read_text(encoding="utf-8").split("\n") if x.startswith("- 심층 분석")]
    assert all("TODO" in x or "생략" in x for x in deep), deep      # 낡은 5-1 결과가 새 분석 줄로 남지 않는다
    plain = _job()                                                       # 지울 것이 없었으면 next도 없다
    out = run_json("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", plain, "--logs", plain.parent / "in.log", "--issue-meta",
                                 plain.parent / "m.json", "--tz", "Asia/Seoul", "--year", "2026", "--explore"])
    assert "next" not in out
