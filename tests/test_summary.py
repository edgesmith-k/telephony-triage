#!/usr/bin/env python3
"""전체 로그 모양 요약(`triagelib/summary.py`, 11/25)과 5-1 후보 확인 칸.

합성 로그(AOSP 모양 문구만): 기준 시각 T(발생 시각 10:00:00)에 데이터 이벤트 줄, 한 태그의 숫자만 다른 W 줄 2천 개, 같은 문구를
두 슬롯이 낸 E 줄, T 앞뒤에 다 있는 E 줄, T+300초 tags.yaml 밖 태그의 Java 예외(분석 구간 ±60초 밖). `pytest tests/test_summary.py`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, plugin_root, run, run_json, tmp  # noqa: E402
from common import evidence  # noqa: E402
from triagelib import core, modulecmd, output, report, summary  # noqa: E402

KEY = "MOCK-9311"
HEAD = "## 전체 로그 모양 요약"
EXC = "java.lang.IllegalStateException: profile table corrupted"


def _stamp(sec: float) -> str:
    ms = int(round((sec + 3600) * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"11-20 {9 + h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _log(path: Path) -> None:
    rows = []
    for k in range(40):
        rows.append((-50 + k, 0, "  2101  2101 D DNC-0   : Internet data state changed from DISCONNECTED to CONNECTED."))
    for k in range(2000):        # 한 모양(숫자만 다르다)
        rows.append((-58 + k * 0.05, 1, f"  2101  2170 W NoisyPoll: poll slow {k} ms"))
    for k, slot in enumerate((0, 1)):      # 같은 태그·문구, 다른 슬롯
        rows.append((-10 + k, 2, f"  2101  2101 E RILJ    : [0{k}12]< SETUP_DATA_CALL error 2 [PHONE{slot}]"))
    rows.append((-30, 3, "  2101  2180 E SteadyTag: heartbeat missed 1"))
    rows.append((30, 3, "  2101  2180 E SteadyTag: heartbeat missed 2"))
    rows += [(300, 4, "  3000  3000 E LateTag : " + EXC),
             (300, 5, "  3000  3000 E LateTag : \tat com.android.internal.telephony.data.DataProfileManager.load(DataProfileManager.java:88)")]
    rows.sort(key=lambda r: (r[0], r[1]))
    path.write_text("".join(f"{_stamp(s)}{x}\n" for s, _o, x in rows), encoding="utf-8")


_JOB: list = []


def _job() -> Path:
    if _JOB:
        return _JOB[0]
    out = tmp("tt-summary-") / "j"
    log = out.parent / "in.log"
    _log(log)
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": KEY, "summary": "데이터 연결 뒤 프로필 오류 (합성)"}), encoding="utf-8")
    run_json("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", out, "--logs", log, "--issue-meta", meta,
                           "--tz", "UTC", "--year", "2026", "--minutes", "1", "--explore",
                           "--answer", "time=2026-11-20T10:00:00+00:00"])
    run_json("triage.py", ["explore", KEY, "--out", out])
    _JOB.append(out)
    return out


def _spec(job: Path) -> dict:
    return json.loads((job / core.EXPLORE_INPUT_FILE).read_text(encoding="utf-8"))


def _defaults() -> dict:
    return yaml.safe_load((plugin_root() / "site-defaults.yaml").read_text(encoding="utf-8"))


def _groups(job: Path, ref, cap: int):
    ev = json.loads((job / "events.json").read_text(encoding="utf-8"))
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    return summary.groups(job, ev, analysis, _defaults(), ref, cap)


def test_groups_flags_fold_slots_and_order():
    got = _spec(_job())["summary"]
    groups = got["groups"]
    late = next(g for g in groups if g["tag"] == "LateTag")
    assert late["msg"] == EXC and late.get("after") and late.get("outside") and late["n"] == 1     # tags.yaml 밖·실패 뒤 5분
    assert groups.index(late) < 3                                                    # E·예외 머리가 맨 앞 묶음
    noisy = [g for g in groups if g["tag"] == "NoisyPoll"]
    assert len(noisy) == 1 and noisy[0]["n"] == 2000 and noisy[0]["level"] == "W"   # 숫자만 다른 2천 줄 = 한 모양
    slots = sorted(g["phone"] for g in groups if g["tag"] == "RILJ" and "SETUP_DATA_CALL error" in g["msg"])
    assert slots == [0, 1]                                                           # 슬롯은 접지 않는다
    steady = next(g for g in groups if g["tag"] == "SteadyTag")
    assert steady["n"] == 2 and "after" not in steady                                # 기준 앞에도 있으면 '처음 나옴' 아님
    assert not any(g["tag"] == "LateTag" and g["msg"].lstrip().startswith("at ") for g in groups)    # 프레임은 세지 않는다
    levels = [g["level"] for g in groups]
    assert levels.index("W") > max(i for i, lv in enumerate(levels) if lv == "E")    # F·예외·E 다음 W
    assert max(i for i, lv in enumerate(levels) if lv in ("E", "W")) < min(i for i, lv in enumerate(levels) if lv in ("D", "I"))
    assert got["ref"] == "2026-11-20T10:00:00.000Z" and got["range"][1] >= late["ts"]


def test_caps_off_no_ref_and_determinism():
    job = _job()
    assert len(_groups(job, "2026-11-20T10:00:00Z", 3)["groups"]) == 3
    assert _groups(job, "2026-11-20T10:00:00Z", 0) is None                          # explore.summary_max_groups: 0 = 끔
    plain = _groups(job, None, 60)
    assert plain["ref"] is None and not any(g.get("after") for g in plain["groups"])
    assert _groups(job, "2026-11-20T10:00:00Z", 60) == _groups(job, "2026-11-20T10:00:00Z", 60) == _spec(job)["summary"]
    big = {"groups": [{"ts": "2026-11-20T10:00:00.000Z", "last": "2026-11-20T10:00:00.000Z", "n": 1, "phone": None,
                       "level": "E", "tag": "T", "msg": "x" * 160}] * 200}
    assert sum(len(x.encode()) + 1 for x in report.summary_rows(big)) > summary.BYTES_MAX       # 바이트 상한은 groups가 줄인다


def test_summary_in_timeline_head_e1_and_tamper():
    job = _job()
    text = (job / core.TIMELINE_FILE).read_text(encoding="utf-8")
    assert text.index("- 형식:") < text.index(HEAD) < text.index("## 본 타임라인") < text.index("## 이상 줄")
    row = next(x for x in text.split("\n") if "LateTag" in x and EXC in x)
    assert "기준 뒤 첫 등장" in row and "분석 구간 밖" in row and evidence.ROW_RX.match(row)
    events = json.loads((job / "events.json").read_text(encoding="utf-8"))

    class NoJob(Exception):
        pass

    assert modulecmd._explore_inputs(job, KEY, events, {}, NoJob)["spec"]["summary"]       # E1: 같은 바이트로 다시 계산
    path = job / core.TIMELINE_FILE
    original = path.read_bytes()
    try:
        path.write_bytes(original.replace(b"profile table corrupted", b"profile table fine"))
        try:
            modulecmd._explore_inputs(job, KEY, events, {}, NoJob)
        except NoJob:
            pass
        else:
            raise AssertionError("요약 절을 바꾼 timeline.md를 통과시켰다")
    finally:
        path.write_bytes(original)
    view = modulecmd._explore_text("# 보기\n\n- 형식: x\n\nrow\n", _spec(job))      # 탐색 모듈 보기도 머리에 같은 절
    assert view.index(HEAD) < view.index("## 본 타임라인") < view.index("\nrow\n")


def test_summary_command_writes_quotable_file():
    job = _job()
    proc = run("triage.py", ["summary", KEY, "--out", job])
    assert proc.returncode == 0, proc.stderr
    assert HEAD in proc.stdout and EXC in proc.stdout
    rec = json.loads((job / "summary.json").read_text(encoding="utf-8"))
    assert rec["path"] == "summary.md" and rec["sha256"] == output._sha((job / "summary.md").read_bytes())
    names, texts, bad = output._summary_source(job, [], [], [])
    assert names == ["summary.md"] and EXC in texts[0] and bad == []
    other = tmp("tt-summary-bad-") / "j"
    shutil.copytree(job, other)
    (other / "summary.md").write_text("bad\n", encoding="utf-8")
    assert output._summary_source(other, [], [], []) == ([], [], ["summary.md"])        # sha가 다르면 근거 원문에서 뺀다
    assert "summary.md" in core.STALE_FILES and "summary.json" in core.STALE_FILES


def test_summary_file_is_evidence_source_and_fake_still_caught(tmp_path, capsys):
    """check-output: summary.md(sha 맞음)의 줄은 타임라인에 없어도 근거로 통과, 지어낸 줄은 그대로 원문에 없음."""
    import test_check_output as tc
    job = tc.make_job(tmp_path, timeline_rows=tc.ROWS[:2])
    found = {"ref": None, "range": [tc.ROWS[0][0], tc.ROWS[-1][0]], "lines": 4, "shapes": 4, "window": None,
             "groups": [{"ts": tc.ROWS[2][0], "last": tc.ROWS[2][0], "n": 1, "phone": None, "level": "W", "tag": "ofonod",
                         "msg": tc.ROWS[2][3]}]}
    summary.write(job, tc.KEY, found, False)
    (job / "deep-output.md").write_text(tc._deep_out([tc.Q2, tc.FAKE]), encoding="utf-8")
    code, data, _ = tc.check(job, capsys=capsys)
    assert code == 0 and data["quotes"] == 2 and data["fabricated"] == 1, data


def test_candidate_check_block_parsed_and_rendered(tmp_path, capsys):
    """analyzer.md 새 칸 `후보 확인:`(후보마다 판정)을 읽어 report 줄에 후보별로 싣고, 옛 한 줄 `분석 스킬 의견:`도 받는다."""
    import test_check_output as tc
    new = "\n".join(["원인 층: 벤더 RIL(vrild) — 인증 거절", "원인 데몬: vrild", "근거:", f"- {tc.Q1}", "반대 근거: 없음",
                     "후보 확인:", "- DATA-001-01: 아님 — 찾았는데 없음: 인증 줄을 타임라인 머리 요약에서",
                     f"- `DATA-002-01`: 맞음 — {tc.Q1}", "- SIM-003: 모름", "규칙 제안:", "- 없음", ""])
    fields = evidence.parse_fields(new)
    assert [(c["cause"], c["verdict"]) for c in fields["후보 확인"]] == [("DATA-001-01", "아님"), ("DATA-002-01", "맞음"),
                                                                       ("SIM-003", "모름")]
    assert fields["분석 스킬 의견"].startswith("DATA-002-01 — ")       # 첫 맞음 후보 = 옛 의견(채택과 다르면 counter)
    old = tc._deep_out([tc.Q1])
    assert evidence.parse_fields(old)["분석 스킬 의견"] == "DATA-001-01 — 1위와 같음" and evidence.parse_fields(old)["후보 확인"] == []
    job = tc.make_job(tmp_path)
    (job / "deep-output.md").write_text(new, encoding="utf-8")
    code, data, err = tc.check(job, capsys=capsys)
    assert code == 0, err
    text = (job / "report.md").read_text(encoding="utf-8")
    assert "/ 후보 확인: DATA-001-01 아님 · DATA-002-01 맞음 · SIM-003 모름" in tc._line(job)
    assert "  - 후보 확인: DATA-001-01 아님 — 찾았는데 없음: 인증 줄을 타임라인 머리 요약에서 | DATA-002-01 맞음 — " in text

