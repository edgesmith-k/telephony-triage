#!/usr/bin/env python3
"""탐색 타임라인 이상 줄 절(`window.anomaly` → `report.anomaly_lines`)과 `window --span` 등급 고르기.

합성 로그(AOSP·에뮬레이터 모양 문구만): 기준 시각 T(발생 시각)에 데이터 이벤트 줄 250개(본 타임라인 200줄 한도를 채운다),
T+31초 tags.yaml 밖 태그의 Java 예외 스택(AndroidRuntime), T+100초 네이티브 신호(F), T+290초 binder 예외(JavaBinder, 분석
구간 ±60초 밖), 사이에 I/D 잡음 수천 줄과 한 태그의 서로 다른 W 줄 2천 줄. `pytest tests/test_explore_anomaly.py`.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, run, run_json, tmp  # noqa: E402
from common import evidence  # noqa: E402
from triagelib import core, modulecmd, report  # noqa: E402

KEY = "MOCK-9301"
HEAD = "## 이상 줄"
FATAL = "10:00:31.000 - E AndroidRuntime FATAL EXCEPTION: main"
ISE = "10:00:31.000 - E AndroidRuntime java.lang.IllegalStateException: data network not ready"
FRAME = "10:00:31.000 - E AndroidRuntime at com.android.internal.telephony.data.DataNetwork.onSetup(DataNetwork.java:120)"
SIGNAL = "10:01:40.000 - F libc Fatal signal 6 (SIGABRT), code -1 (SI_QUEUE) in tid 4000 (rild)"
BINDER = "10:04:50.000 - E JavaBinder *** Uncaught remote exception! (Exceptions are not yet supported across processes.)"
WARN_OTHER = "10:00:20.000 - W WifiScanTag scan request throttled by caller"


def _letters(i: int) -> str:
    out = ""
    for _ in range(4):
        out, i = out + "abcdefghijklmnopqrstuvwxyz"[i % 26], i // 26
    return out


def _stamp(sec: float) -> str:
    """기준 T(11-20 10:00:00.000)에서 `sec`초 뒤(음수면 앞)의 logcat 스탬프."""
    ms = int(round((sec + 3600) * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"11-20 {9 + h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _log(path: Path) -> None:
    rows = []      # (초, 순번, 줄)
    for k in range(250):          # 이벤트 줄(data_internet_state_changed) — 본 타임라인 한도를 채운다
        rows.append((-55 + k * 0.44, 0, "  2101  2101 D DNC-0   : Internet data state changed from DISCONNECTED to CONNECTED."))
    for k in range(3000):         # I/D 잡음(tags.yaml 밖)
        rows.append((-60 + k * 0.127, 1, f"  2101  2160 {'ID'[k % 2]} NoiseTag: tick {_letters(k)}"))
    for k in range(2000):         # 한 태그의 서로 다른 W 줄(숫자 빼도 다르다)
        rows.append((-58 + k * 0.19, 2, f"  2101  2170 W ChattyTag: poll slow {_letters(k)}"))
    rows.append((20, 3, "  2101  2180 W WifiScanTag: scan request throttled by caller"))
    rows.append((-1500, 0, "  2101  2190 D CarrierCfg: attach retry count=3 cause=EMM_ACCESS_BARRED"))   # 분석 구간 25분 앞
    stack = ["E AndroidRuntime: FATAL EXCEPTION: main", "E AndroidRuntime: Process: com.android.phone, PID: 3000",
             "E AndroidRuntime: java.lang.IllegalStateException: data network not ready",
             "E AndroidRuntime: \tat com.android.internal.telephony.data.DataNetwork.onSetup(DataNetwork.java:120)",
             "E AndroidRuntime: \tat com.android.internal.telephony.data.DataNetworkController.onSetupDataNetwork(DataNetworkController.java:340)",
             "E AndroidRuntime: \tat android.os.Handler.dispatchMessage(Handler.java:106)"]
    rows += [(31, 4 + i, f"  3000  3000 {x}") for i, x in enumerate(stack)]
    rows.append((100, 4, "  4000  4000 F libc    : Fatal signal 6 (SIGABRT), code -1 (SI_QUEUE) in tid 4000 (rild)"))
    binder = ["E JavaBinder: *** Uncaught remote exception!  (Exceptions are not yet supported across processes.)",
              "E JavaBinder: java.lang.IllegalArgumentException: invalid profile id",
              "E JavaBinder: \tat com.android.internal.telephony.data.DataProfileManager.getProfile(DataProfileManager.java:88)",
              "E JavaBinder: \tat android.os.Binder.execTransact(Binder.java:1300)",
              "E JavaBinder: \tat android.os.Binder.execTransactInternal(Binder.java:1340)"]
    rows += [(290, 4 + i, f"  2101  2150 {x}") for i, x in enumerate(binder)]
    rows.sort(key=lambda r: (r[0], r[1]))
    path.write_text("".join(f"{_stamp(s)}{x}\n" for s, _o, x in rows), encoding="utf-8")


_JOBS: dict = {}


def _job(time: str = "2026-11-20T10:00:00+00:00") -> Path:
    if time in _JOBS:
        return _JOBS[time]
    out = tmp("tt-anom-") / "j"
    log = out.parent / "in.log"
    _log(log)
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": KEY, "summary": "데이터 연결 뒤 앱 멈춤 (합성)"}), encoding="utf-8")
    run_json("triage.py", ["run", KEY, "--offline-db", SAMPLE, "--out", out, "--logs", log, "--issue-meta", meta,
                           "--tz", "UTC", "--year", "2026", "--minutes", "1", "--explore", "--answer", f"time={time}"])
    run_json("triage.py", ["explore", KEY, "--out", out])
    _JOBS[time] = out
    return out


def no_summary(text: str) -> str:
    """머리의 전체 로그 모양 요약 절(`## 전체 로그 모양 요약` ~ `## 본 타임라인` 뒤 빈 줄)을 뺀 글 — 요약이 없을 때와 같은 바이트."""
    start, end = text.find("## 전체 로그 모양 요약"), text.find("## 본 타임라인\n\n")
    return text[:start] + text[end + len("## 본 타임라인\n\n"):] if start >= 0 else text


def _split(job: Path) -> tuple[str, str]:
    """(본 타임라인 — 머리의 요약 절은 뺀다, 이상 줄 절)."""
    main, sep, block = no_summary((job / core.TIMELINE_FILE).read_text(encoding="utf-8")).partition("\n" + HEAD)
    return main, sep + block


def _rows(text: str) -> list[str]:
    return [evidence.SCRIPT_NOTE_RX.sub("", x) for x in text.split("\n") if evidence.ROW_RX.match(x)]


def _times(rows: list[str]) -> list[str]:
    return [r[:12] for r in rows]


def test_block_carries_exceptions_outside_window_and_rules():
    job = _job()
    main, block = _split(job)
    assert block, "이상 줄 절이 없다"
    rows = _rows(block)
    assert not any(" W " in r or " E " in r or " F " in r for r in _rows(main))      # 본 타임라인은 이벤트 줄이 다 채웠다
    for want in (FATAL, ISE, FRAME, SIGNAL, BINDER, WARN_OTHER):     # tags.yaml 밖·분석 구간(±60초) 밖 줄
        assert want in rows, want
    assert sum("AndroidRuntime at " in r for r in rows) == 2                     # 예외 머리 뒤 프레임 2줄만
    assert len(rows) <= 80 and _times(rows) == sorted(_times(rows))                                # 별도 예산, 시각순
    assert sum("ChattyTag" in r for r in rows) < 80 - 10                           # W 잡음 2천 줄이 F/E를 밀지 않는다
    assert "+00:00" not in block and "2026-11-20T10:00:00.000Z" in block
    spec = json.loads((job / core.EXPLORE_INPUT_FILE).read_text(encoding="utf-8"))
    assert spec["anomaly"]["rows"] and spec["anomaly"]["range"][1] == "2026-11-20T10:10:00.000Z"   # 기준 + 600초


def test_block_without_reference_time():
    job = _job("full")
    _main, block = _split(job)
    rows = _rows(block)
    assert FATAL in rows and BINDER in rows and SIGNAL in rows


def test_window_span_ranks_errors_and_caps_chatty_tag():
    job = _job()
    proc = run("triage.py", ["window", KEY, "--out", job, "--at", "2026-11-20T10:00:00Z", "--span", "600"])
    assert proc.returncode == 0, proc.stderr
    text = (job / json.loads(proc.stdout.strip().splitlines()[-1])["window"]).read_text(encoding="utf-8")
    rows = _rows(text)
    assert FATAL in rows and BINDER in rows and SIGNAL in rows and _times(rows) == sorted(_times(rows))
    assert "줄 고르기: 구간 안" in text
    proc = run("triage.py", ["window", KEY, "--out", job, "--at", "2026-11-20T10:00:00Z", "--span", "600", "--lines", "150"])
    rows = _rows((job / json.loads(proc.stdout.strip().splitlines()[-1])["window"]).read_text(encoding="utf-8"))
    assert WARN_OTHER in rows and not any("NoiseTag" in r for r in rows)   # 같은 W 등급에서 50줄 넘은 태그는 뒤로, D·I는 W 뒤


def test_quote_from_block_passes_evidence_check():
    job = _job()
    (job / "explore-output.md").write_text("\n".join([
        "가설 1: 데이터 연결 처리 중 앱 예외로 phone 프로세스가 멈춤", "로그로 확인:", f"- {ISE}", f"- {BINDER}",
        "코드로 추정: 코드 근거 없음", "반대 근거: 없음", "다음 확인: 예외 직전 DataNetwork 상태"]) + "\n", encoding="utf-8")
    data = run_json("triage.py", ["check-output", KEY, "--for", "explore", "--out", job], expect=(0, 1))
    assert data["quotes"] == 2 and data["fabricated"] == 0, data


def test_e1_recompute_and_tamper():
    job = _job()
    events = json.loads((job / "events.json").read_text(encoding="utf-8"))

    class NoJob(Exception):
        pass

    got = modulecmd._explore_inputs(job, KEY, events, {}, NoJob)
    assert got["spec"]["anomaly"]["rows"]
    path = job / core.TIMELINE_FILE
    original = path.read_bytes()
    try:
        path.write_bytes(original.replace(b"invalid profile id", b"profile id missing"))
        try:
            modulecmd._explore_inputs(job, KEY, events, {}, NoJob)
        except NoJob:
            pass
        else:
            raise AssertionError("이상 줄 절을 바꾼 timeline.md를 통과시켰다")
    finally:
        path.write_bytes(original)


def test_no_masked_copy_leaves_timeline_as_before():
    job = _job()
    other = tmp("tt-anom-copy-") / "j"
    shutil.copytree(job, other)
    spec_path = other / core.EXPLORE_INPUT_FILE
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec.pop("anomaly"), spec.pop("summary")
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    before = spec_path.read_bytes()
    shutil.rmtree(other / "logs-masked")
    run_json("triage.py", ["explore", KEY, "--out", other])
    assert HEAD not in (other / core.TIMELINE_FILE).read_text(encoding="utf-8")
    assert spec_path.read_bytes() == before                                    # 사본이 없으면 입력 파일도 그대로
    main, _ = _split(job)
    assert (other / core.TIMELINE_FILE).read_text(encoding="utf-8") == main     # 이상 줄 절만 없고 본 타임라인은 같다


# --- 확인 리뷰 묶음(11/25): 항목마다 고치기 전 코드에서 실패하는 시험 --------------------------------------------

def test_main_rows_kept_for_module_view_but_not_job_timeline():
    """1: 본 타임라인 줄은 빼지 않고 `main`만 붙인다 — JOB/timeline.md는 빼고, 모듈 보기(`with_anomaly`)는 싣는다."""
    sys.path.insert(0, str(REPO / "tests"))
    from test_explore_window import _job as lookat_job
    from triagelib import report
    job = lookat_job()
    anomaly = json.loads((job / core.EXPLORE_INPUT_FILE).read_text(encoding="utf-8"))["anomaly"]
    main = [r for r in anomaly["rows"] if r.get("main")]
    from triagelib import window
    assert main and all(window.rank(r) <= window.ANOMALY_RANK_MAX for r in main)    # W/E/F·오류 문구 줄
    row = report.row_line({**main[0], "marks": []})
    _top, block = _split(job)
    assert row not in _rows(block)                                               # JOB 절: 본 줄과 겹치지 않는다
    view = report.with_anomaly("# 모듈 보기\n", anomaly)
    assert row in _rows(view) and "이미 있는 줄은 뺐다" not in view              # 모듈 보기: 본 줄을 싣지 않으니 모두
    head = {"ts": "2026-11-20T10:00:31.000Z", "phone": None, "level": "E", "tag": "AndroidRuntime",
            "msg": "java.lang.IllegalStateException: x"}                       # 예외 머리는 main이 아니다(그리는 쪽은 그대로)
    assert report.anomaly_lines({"rows": [head, {**head, "msg": "noise", "main": True}]})[-1].endswith("IllegalStateException: x")


def _recs(spec):
    out = []
    for k, (tag, level, n) in enumerate(spec):
        out += [{"ts": f"2026-11-20T10:{k:02d}:{i // 60:02d}.{i % 60:03d}Z".replace(f":{i // 60:02d}.", f":{i // 60 % 60:02d}."),
                 "tag": tag, "level": level, "msg": f"m {tag} {i}", "phone_id": None} for i in range(n)]
    return out


def test_tag_cap_only_orders_within_rank():
    """2: 태그 상한은 같은 등급 안에서만 — 한 태그의 F 60줄이 다른 태그 W보다 먼저, E는 다른 태그 D보다 먼저."""
    from triagelib import window
    recs = sorted(_recs([("A", "F", 60), ("B", "W", 100), ("C", "E", 5), ("D", "D", 100)]), key=lambda r: r["ts"])
    rows = window._pick_span(recs, "2026-11-20T10:01:00.000Z", 70)
    assert sum(" F A " in r for r in rows) == 60 and sum(" E C " in r for r in rows) == 5
    assert not any(" D D " in r for r in rows)
    order = window.ranked([(3, 0.0, 0, "x", 1), (0, 9.0, 1, "y", 13), (0, 1.0, 2, "y", 1)], 12)
    assert [it[2] for it in order] == [2, 1, 0]                                  # 상한 넘은 y의 F도 x의 W보다 앞


def test_exception_head_needs_class_name():
    """3: 메서드·필드 이름(`onError`·`isError`)은 예외 머리가 아니다."""
    from triagelib import window
    for msg, want in (("mCallback.onError called", 5), ("result.isError=false", 5),      # 머리 아님(I/D 오류 문구 등급)
                      ("java.lang.IllegalStateException: x", 1), ("android.os.DeadObjectException", 1)):
        assert window.rank({"level": "D", "msg": msg}) == want, msg


def test_fold_key_keeps_slots_and_levels_apart():
    """4: 다른 SIM 슬롯·레벨의 같은 문구를 한 줄로 접지 않는다(merge_rows F2와 같은 원칙)."""
    from triagelib import window
    base = {"tag": "DNC", "level": "E", "msg": "setup failed 3", "phone_id": 0}
    assert window._fold_key(base) != window._fold_key({**base, "phone_id": 1})
    assert window._fold_key(base) != window._fold_key({**base, "level": "W"})
    assert window._fold_key(base) == window._fold_key({**base, "msg": "setup failed 4"})
    # 11/25: 0x 없는 8자리 이상 16진수·태그 안 숫자도 접는다(이은 로그의 `DN-138-C`·`DN-140-C`, tombstone 레지스터 값)
    assert window._fold_key({**base, "tag": "DN-138-C", "msg": "x deadbeef01"}) == window._fold_key(
        {**base, "tag": "DN-140-C", "msg": "x 00007ffd3c3e"})


def test_anomaly_failure_does_not_break_explore(monkeypatch, tmp_path, capsys):
    """5: 이상 줄 고르기에서 예외가 나도 explore는 절 없이 계속한다."""
    import triage
    from triagelib import window

    def boom(*_a, **_k):
        raise RuntimeError("broken copy")

    monkeypatch.setattr(window, "anomaly", boom)
    (tmp_path / "analysis.json").write_text("{}", encoding="utf-8")
    assert triage._anomaly(tmp_path, {}, {}, {}, {}, []) is None
    assert "이상 줄 절을 만들지 못해" in capsys.readouterr().err


def test_e1_corrupt_anomaly_is_nojob_not_traceback():
    """6: 손상된 `anomaly`(range 원소 부족·after_sec·fold 키 없음)는 E1에서 작업 없음 안내다."""
    job = _job()
    other = tmp("tt-anom-bad-") / "j"
    shutil.copytree(job, other)
    path = other / core.EXPLORE_INPUT_FILE
    spec = json.loads(path.read_text(encoding="utf-8"))
    spec["anomaly"] = {"range": ["2026-11-20T09:59:00.000Z"], "ref": "2026-11-20T10:00:00.000Z",
                       "rows": [{"ts": "2026-11-20T10:00:31.000Z", "fold": {}}, "bad"]}
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    events = json.loads((other / "events.json").read_text(encoding="utf-8"))

    class NoJob(Exception):
        pass

    try:
        modulecmd._explore_inputs(other, KEY, events, {}, NoJob)
    except NoJob:
        pass
    else:
        raise AssertionError("손상된 anomaly를 통과시켰다")


def test_eval_case_input_carries_anomaly():
    """7: 모듈 eval case의 explore-input.json은 explore가 `anomaly`를 더한 뒤의 것이다(실사용 JOB과 같다)."""
    case = REPO / "templates" / "module-skills" / "android" / "data" / "evals" / "data-normal-retry-then-crash" / "files"
    rows = json.loads((case / "explore-input.json").read_text(encoding="utf-8"))["anomaly"]["rows"]
    assert any("NullPointerException" in r["msg"] for r in rows)


# --- 레벨을 믿지 못하는 줄·oFono(11/25): 레벨 대신 오류 문구로도 고르고, 네이티브·oFono·glib crash 머리 -----------------

def test_rank_order_with_error_text():
    """F > 예외·crash 머리 > E > 레벨 못 믿는 줄(`_weak`)의 오류 문구(0 값 오류 칸 제외) > W > 그 밖 I/D 오류 문구 > 나머지."""
    from triagelib import window
    recs = [{"level": "I", "msg": "deactivate rsp error=0", "_weak": True}, {"level": "D", "msg": "setup rsp error=38"},
            {"level": "W", "msg": "poll slow"}, {"level": "I", "msg": "setup rsp error=38", "_weak": True},
            {"level": "E", "msg": "setup failed"},
            {"level": "I", "msg": "ofonod[812]: Aborting (signal 11) [/usr/sbin/ofonod]"}, {"level": "F", "msg": "x"}]
    assert [window.rank(r) for r in recs] == [6, 5, 4, 3, 2, 1, 0]
    assert window.ANOMALY_RANK_MAX == window.W_RANK < window.TEXT_RANK          # 절은 W까지, I/D 오류 문구는 요약·--span만
    assert window.rank({"level": "W", "msg": "setup failed"}) == 4             # W는 오류 문구가 있어도 W
    for msg in ("Segmentation fault", "signal 11 (SIGSEGV), code 1 (SEGV_MAPERR)", "GLib-CRITICAL **: g_source_remove",
                "ofonod: assertion 'modem != NULL' failed", "*** stack smashing detected ***: terminated", "backtrace:",
                "SIGBUS", "got SIGFPE"):
        assert window.rank({"level": "I", "msg": msg}) == 1, msg
    for msg in ("SIGSEGVX", "assertion", "assertion  failed", "backtrace", "Aborting (signal x)"):
        assert not window.EXC_RX.search(msg), msg
    assert window.EXC_RX.search("assertion " + "x" * 300 + " failed") is None   # 200자 상한, 되짚기 폭주 없음


def _small_job(lines: list[str], *, db=SAMPLE, root=None, platform=None, occurred="2026-11-20T10:00:00Z",
               extra: list | None = None) -> tuple[Path, dict, dict]:
    out = tmp("tt-anom-s-") / "j"
    log = out.parent / "in.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": KEY, "summary": "합성", "occurred_at": occurred}), encoding="utf-8")
    kw = {"root": root, "env": {"TELEPHONY_TRIAGE_HOME": out.parent / "home"}} if root else {}
    run_json("triage.py", ["run", KEY, "--offline-db", db, "--out", out, "--logs", log, "--issue-meta", meta,
                           *(["--platform", platform] if platform else []), *(extra or []), "--explore"], **kw)
    run_json("triage.py", ["explore", KEY, "--out", out], **kw)
    return out, kw, json.loads((out / core.EXPLORE_INPUT_FILE).read_text(encoding="utf-8"))["anomaly"]


def test_unreliable_level_tag_error_text_in_block():
    """tags.yaml `level: unreliable` 태그(백엔드가 레벨을 I로 바꾼다)의 오류 문구 줄은 절에 들고, `error=0` 줄은 빠진다."""
    from runner import copy_db
    db = copy_db(SAMPLE, "db-unrel")
    tags = db / "parser-rules" / "tags.yaml"
    tags.write_text(tags.read_text(encoding="utf-8") + "  - {tag: vrild, category: data, level: unreliable, added_for: '-',"
                    " added_on: 2026-11-25, reason: 합성 (레벨 못 믿는 벤더 RIL)}\n", encoding="utf-8")
    _out, _kw, anomaly = _small_job([
        "11-20 10:00:00.000  2101  2101 D DNC-0   : Internet data state changed from DISCONNECTED to CONNECTED.",
        "11-20 10:00:01.000   900   900 E vrild   : SETUP_DATA_CALL rsp GENERIC_FAILURE",
        "11-20 10:00:02.000   900   900 E vrild   : setup rsp error=38 cid=1",
        "11-20 10:00:03.000   900   900 E vrild   : deactivate rsp error=0",
        "11-20 10:00:04.000   900   900 W vrild   : poll slow"], db=db, extra=["--tz", "UTC", "--year", "2026"])
    msgs = {r["msg"]: r["level"] for r in anomaly["rows"]}
    assert msgs.get("SETUP_DATA_CALL rsp GENERIC_FAILURE") == "I" and msgs.get("setup rsp error=38 cid=1") == "I"
    assert "deactivate rsp error=0" not in msgs and "poll slow" not in msgs    # 레벨 I로 바뀐 W·0 값 오류는 아니다


def test_ofono_job_block_error_text_and_crash_head():
    """oFono 작업(`--platform ofono`): journal 줄(레벨 I)의 `org.ofono.Error.Failed`·`Aborting (signal 11)`이 절에 든다."""
    from runner import plugin_root, variant_db
    root = plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    job, kw, anomaly = _small_job([
        "2026-09-20T14:32:09.100000+09:00 dut ofonod[812]: src/gprs.c:activate_cb() /modem_0 context activate requested",
        "2026-09-20T14:32:10.200000+09:00 dut ofonod[812]: src/gprs.c:activate_cb() activate failed: org.ofono.Error.Failed",
        "2026-09-20T14:32:10.300000+09:00 dut ofonod[812]: src/gprs.c:deactivate_cb() /modem_0 deactivated error=0",
        "2026-09-20T14:32:11.000000+09:00 dut ofonod[812]: Aborting (signal 11) [/usr/sbin/ofonod]"],
        db=variant_db("issue-db-ofono"), root=root, platform="ofono", occurred="2026-09-20T05:32:10Z")
    rows = anomaly["rows"]
    assert any("org.ofono.Error.Failed" in r["msg"] for r in rows)
    assert any(r["msg"].startswith("Aborting (signal 11)") for r in rows)
    assert not any("error=0" in r["msg"] for r in rows)
    from triagelib import window
    assert window.rank({"level": "I", "msg": "Aborting (signal 11) [/usr/sbin/ofonod]"}) == 1
    proc = run("triage.py", ["window", KEY, "--out", job, "--at", "2026-09-20T05:32:10Z", "--span", "60"], **kw)
    assert proc.returncode == 0, proc.stderr                                    # window도 oFono 작업에서 그대로
    text = (job / json.loads(proc.stdout.strip().splitlines()[-1])["window"]).read_text(encoding="utf-8")
    assert "Aborting (signal 11)" in text and "org.ofono.Error.Failed" in text


# --- 탐색은 최후의 보루(11/25 사용자 결정): 사본 전체 grep·구간 읽기, 인용 검사는 사본 줄까지 --------------------------

EARLY_RAW = "11-20 09:35:00.000  2101  2190 D CarrierCfg: attach retry count=3 cause=EMM_ACCESS_BARRED"


def _check(base: Path, quotes: list[str]) -> tuple[dict, Path]:
    job = tmp("tt-anom-chk-") / "j"
    shutil.copytree(base, job)          # check-output은 report 줄을 한 번만 고친다 — 판정마다 새 사본, explore로 줄을 되돌린다
    run_json("triage.py", ["explore", KEY, "--out", job])
    (job / "explore-output.md").write_text("\n".join([
        "가설 1: 망이 접속을 막아 재시도가 이어짐", "로그로 확인:", *[f"- {q}" for q in quotes],
        "코드로 추정: 코드 근거 없음", "반대 근거: 없음", "다음 확인: 망 거절 사유"]) + "\n", encoding="utf-8")
    return run_json("triage.py", ["check-output", KEY, "--for", "explore", "--out", job], expect=(0, 1)), job


def test_copy_line_quotes_pass_and_fakes_fail():
    """B: 타임라인·window에 없는 사본 줄 인용(원문 모양·행 모양)은 통과, 지어낸 인용·값 바꾼 인용은 계속 걸린다."""
    job = _job()
    assert "EMM_ACCESS_BARRED" not in (job / core.TIMELINE_FILE).read_text(encoding="utf-8")
    ok, done = _check(job, [EARLY_RAW, "09:35:00.000 - D CarrierCfg attach retry count=3 cause=EMM_ACCESS_BARRED"])
    assert ok["quotes"] == 2 and ok["fabricated"] == 0 and ok["weak"] == 0, ok
    bad, _ = _check(job, [EARLY_RAW.replace("EMM_ACCESS_BARRED", "NONE"),                       # 값 바꿈(K07 꼴)
                       "11-20 09:35:00.000  2101  2190 E CarrierCfg: modem firmware crashed with assertion in attach"])
    assert bad["fabricated"] == 2, bad
    rec = json.loads((done / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert any(str(x).startswith("logs-masked/") for x in rec["source"]), rec["source"]


def test_window_grep_whole_log_and_call_cap():
    """C: `--span` 없는 `--grep`은 로그 전체(분석 구간 밖)에서 찾고 머리에 일치 수·처음·끝 시각. 작업당 호출 상한은 폭주 방지용."""
    job = _job()
    proc = run("triage.py", ["window", KEY, "--out", job, "--at", "2026-11-20T10:00:00Z", "--grep", "EMM_ACCESS_BARRED"])
    assert proc.returncode == 0, proc.stderr
    text = (job / json.loads(proc.stdout.strip().splitlines()[-1])["window"]).read_text(encoding="utf-8")
    assert "09:35:00.000 - D CarrierCfg attach retry count=3 cause=EMM_ACCESS_BARRED" in _rows(text)
    assert "- 일치: 로그 전체 1줄(2026-11-20T09:35:00.000Z ~ 2026-11-20T09:35:00.000Z)" in text
    assert core.WINDOWS_MAX >= 50


def test_guard_allows_ranged_reads_of_masked_copy_but_not_dumps(monkeypatch):
    """사본 `grep -n`·`sed -n a,bp`는 통과, 원문 통째 출력(cat)은 계속 거부(규칙 10). 가드는 바꾸지 않았다 — 지침이 그 길을 쓰므로 고정한다.
    판정은 test_hooks의 guard 시험과 같은 작업공간(설정 있음)·같은 함수(`guard.judge`)로 본다."""
    from workspace import Workspace
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import guard as g
    ws = Workspace()
    for k, v in ws.env().items():
        monkeypatch.setenv(k, str(v))
    job = _job()
    copy = next((job / "logs-masked").iterdir())

    def judge(cmd):
        out, _ = g.judge({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(job)}, str(ws.root))
        return out and out["hookSpecificOutput"]["permissionDecision"]

    assert judge(f"grep -n EMM_ACCESS_BARRED logs-masked/{copy.name}") in (None, "allow")
    assert judge(f"sed -n '100,180p' logs-masked/{copy.name}") in (None, "allow")
    # 통째 출력 거부는 원문 대상이다(사본 통째 읽기는 기존 설계상 허용 — test_hooks `cat logs-masked/x.txt` is None)
    assert judge(f"cat {job.parent / 'in.log'}") == "deny"


def test_tt_explore_reads_masked_copies_only():
    """tt-explore(OpenCode): 사본 grep과 read 도구 구간 읽기만 — sed는 허용하지 않는다(`w`·`e` 명령이 파일 쓰기·실행), 원문 금지 유지."""
    import re
    import yaml
    sys.path.insert(0, str(REPO / "tools"))
    import gen_opencode
    text = (REPO / "opencode" / "agents" / "tt-explore.md").read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    bash, body = yaml.safe_load(m.group(1))["permission"]["bash"], text[m.end():]

    def decide(cmd):
        return [v for k, v in bash.items() if gen_opencode.OCV.wildcard_match(k, cmd)][-1]

    assert decide("grep -n EMM_ACCESS_BARRED /w/K-1/logs-masked/a.log") == "allow"
    assert decide("sed -n '1,5p' /w/K-1/logs-masked/a.log") == "deny"
    assert "JOB/logs-masked/" in body and "read tool" in body and "Never read raw logs" in body


# --- 독립 리뷰 반영(11/25): 약한 레벨만 오류 문구 등급, 본 줄은 같은 등급 뒤로, 네이티브 프레임, _Stop 경고 -------------------

def _anomaly_of(monkeypatch, recs, shown=frozenset(), cap=80):
    """`window.anomaly`를 레코드로 직접 — 사본 읽기(`served_copies`·`_records`)만 바꾼다."""
    from triagelib import window
    monkeypatch.setattr(window, "served_copies", lambda job, analysis: ([Path("x.log")], []))
    monkeypatch.setattr(window, "_records", lambda job, ev, served, defaults: (recs, None, {}))
    return window.anomaly(Path("."), {"mask_off": True}, {}, {}, "2026-11-20T10:00:00Z", 0, cap, set(shown))


def _rec(sec, level, tag, msg, pid=1, **kw):
    return {"ts": f"2026-11-20T10:00:{sec:02d}.000Z", "level": level, "tag": tag, "msg": msg, "pid": pid, "phone_id": None,
            "line_ref": {"file_index": 0, "line_no": sec + 1}, **kw}


def test_only_weak_level_error_text_enters_block(monkeypatch):
    """1: 레벨을 믿는 I/D 줄의 오류 문구(`RILJ … error 1`)는 절에 싣지 않는다(잡음) — 레벨 못 믿는 줄만. `_weak`는 출력에 없다."""
    rows = _anomaly_of(monkeypatch, [_rec(1, "D", "RILJ", "[0350]< GET_CURRENT_CALLS error 1 [PHONE0]"),
                                     _rec(2, "I", "vrild", "setup rsp error=38", _weak=True),
                                     _rec(3, "W", "X", "poll slow")])["rows"]
    assert [r["tag"] for r in rows] == ["vrild", "X"] and not any("_weak" in r for r in rows)


def test_mark_weak_uses_backend_and_ofono_levelless_files():
    """1: `_mark_weak` — 백엔드 `_level_unreliable` 태그, oFono 레벨 없는 형식 파일(줄이 모두 I). severity 있는 파일의 I 줄은 아니다."""
    from triagelib import window

    class Ofono:
        platform = "ofono"

        @staticmethod
        def _level_unreliable(*tags):
            return "vendord" in tags

    recs = [{"tag": "ofonod", "level": "I", "line_ref": {"file_index": 0}},
            {"tag": "ofonod", "level": "I", "line_ref": {"file_index": 1}},
            {"tag": "ofonod", "level": "E", "line_ref": {"file_index": 1}},
            {"tag": "vendord/sub", "level": "I", "line_ref": {"file_index": 1}}]
    window._mark_weak(Ofono(), recs)
    assert [bool(r.get("_weak")) for r in recs] == [True, False, False, True]

    class Android:
        platform = "android"

        @staticmethod
        def _level_unreliable(*tags):
            return tags == ("vrild",)

    recs = [{"tag": "vrild", "level": "I"}, {"tag": "RILJ", "level": "I"}]
    window._mark_weak(Android(), recs)
    assert [bool(r.get("_weak")) for r in recs] == [True, False]


def test_main_rows_yield_within_same_rank(monkeypatch):
    """3: 같은 등급이면 본 타임라인에 이미 보이는 줄(`main`)이 예산을 먼저 먹지 않는다(기준에 더 가까워도)."""
    near, far = _rec(1, "E", "A", "near fail"), _rec(30, "E", "B", "far fail")
    rows = _anomaly_of(monkeypatch, [near, far], shown={(near["ts"], "A", "near fail")}, cap=1)["rows"]
    assert [r["msg"] for r in rows] == ["far fail"]
    rows = _anomaly_of(monkeypatch, [near, _rec(30, "W", "B", "far warn")], shown={(near["ts"], "A", "near fail")}, cap=1)["rows"]
    assert [r["msg"] for r in rows] == ["near fail"]                                # 다른 등급은 그대로(E가 W보다 앞)


def test_native_frames_and_ofono_backtrace(monkeypatch):
    """4·5: 네이티브 프레임(`#00 pc`·`#0  0x… in`)은 머리 뒤에 붙고 따로 고르지 않는다. oFono `+++ backtrace +++`·glib 모양 머리."""
    from triagelib import window
    for msg in ("#00 pc 000000000004e0c4  /apex/com.android.runtime/lib64/bionic/libc.so (abort+164)",
                "      #01 pc 00000000000123a5  /vendor/lib64/libril.so", "#0  0x00007f3a2b in g_main_loop_run ()",
                "#1  0x0000aaaa"):
        assert window.FRAME_RX.match(msg) and window.rank({"level": "F", "msg": msg}) == 0, msg
    for msg in ("++++++++ backtrace ++++++++", "GLib-GIO-CRITICAL **: g_dbus_x: assertion 'x' failed",
                "Assertion `modem' failed.", "ofonod: assertion failed"):
        assert window.rank({"level": "I", "msg": msg}) == 1, msg
    rows = _anomaly_of(monkeypatch, [_rec(1, "F", "DEBUG", "backtrace:", pid=7),
                                     _rec(2, "F", "DEBUG", "      #00 pc 000000000004e0c4  /apex/libc.so (abort+164)", pid=7),
                                     _rec(3, "F", "DEBUG", "      #01 pc 00000000000123a5  /vendor/lib64/libril.so", pid=7),
                                     _rec(4, "F", "DEBUG", "      #02 pc 000000000006789b  /vendor/lib64/libril.so", pid=7)])
    assert [r["msg"].split()[0] for r in rows["rows"]] == ["backtrace:", "#00", "#01"] and rows["candidates"] == 1


def test_anomaly_stop_warns_on_stderr(monkeypatch, capsys):
    """6: 사본 읽기 실패(`_Stop`, 파서 규칙 오류 포함)로 절을 뺄 때 stderr 경고 한 줄."""
    from triagelib import window

    def stop(*_a):
        raise window._Stop(2, "작업 디렉토리 이상", "파서 규칙 오류: bad")

    monkeypatch.setattr(window, "served_copies", lambda job, analysis: ([Path("x.log")], []))
    monkeypatch.setattr(window, "_records", stop)
    assert window.anomaly(Path("."), {}, {}, {}, None, 0, 80, set()) is None
    assert "이상 줄 절을 만들지 못해" in capsys.readouterr().err


# --- 5-2 입력 고르기(11/25 A652·A653): 긴 로그에서 요약·이상 줄이 같은 규칙으로 기준 둘레·드문 모양·예외 머리를 남긴다 ----------
# 사내 반입 5 증상을 지어낸 이름으로 다시 만든다: 잡음 태그 모양 수백 개(각 수천 줄 — 시험 시간 때문에 1천 줄)와 드문 잡음 모양 수백 개
# 사이에, 기준 +30초·+5분에 본 타임라인 프로세스(pid 1500)가 낸 E 1줄·W 스택(각 모양 x2, 파서 규칙에 없는 태그). 레코드는
# 시험 안에서 만든다(큰 fixture 파일 없음). 고치기 전 코드는 기준이 없으면 로그 앞 잡음, 있으면 기준에 더 가까운 잡음 E가 칸을 채웠다.

T0 = "2026-11-20T10:00:00.000Z"
TARGET_E = "requestNetwork failed: slot 0 not ready"
TARGET_W = "setup aborted, keep retry timer"


_LONG: list = []


def _long_recs() -> list[dict]:
    if _LONG:
        return _LONG[0]          # 고르기는 레코드를 바꾸지 않는다(같은 입력을 여러 번 고른다)
    from datetime import timedelta
    from common import logtime
    t0 = logtime.parse_ts(T0)
    recs = []

    def add(sec, level, tag, msg, pid):
        recs.append({"ts": logtime.format_ts(t0 + timedelta(seconds=sec)), "level": level, "tag": tag, "msg": msg, "pid": pid,
                     "phone_id": None, "line_ref": {"file_index": 0, "line_no": len(recs) + 1}})

    for k in range(300):                  # 흔한 잡음 모양 300개 × 1천 줄(6시간에 고루 — 기준 둘레에도 있다), 태그 40개
        for i in range(1000):
            add(-10800 + i * 21.6 + k * 0.05, "EW"[k % 2], f"NoiseSvc{k % 40}", f"poll {_letters(k)} state", 2000 + k % 40)
    for k in range(400):                  # 드문 잡음 모양 400개(1~2줄, 다른 프로세스) — 사내 로그처럼 E/W 모양 대부분이 드물다
        for j in range(1 + k % 2):
            add((k * 557) % 21600 - 10800 + j, "EW"[k % 2], f"RareTag{k % 50}", f"odd {_letters(k + 1000)} seen", 3000 + k)
    for i in range(4000):                 # 폭주 모양 x4000(기준 +100~140초)
        add(100 + i * 0.01, "E", "BurstTag", "queue overflow", 4000)
    add(50, "E", "VendorHal", "firmware assert in modem watchdog", 3500)          # 기준 둘레의 드문 모양(밀려나면 안 된다)
    for j in range(2):                    # 문제 두 줄(각 모양 x2): 기준 +30초 E, +5분 W 스택 — 본 타임라인 프로세스 1500
        add(30 + j, "E", "ImsSvcExt", TARGET_E, 1500)
        add(300 + j, "W", "DcTrackerExt", TARGET_W, 1500)
        add(300.001 + j, "W", "DcTrackerExt", "java.lang.IllegalStateException: apn context missing", 1500)
        for f in range(3):
            add(300.002 + j + f * 0.001, "W", "DcTrackerExt", f"\tat com.example.telephony.DcHelper.step{f}(DcHelper.java:{40 + f})",
                1500)
    recs.sort(key=lambda r: r["ts"])
    _LONG.append(recs)
    return recs


def _long_pick(monkeypatch, ref, guess):
    """(요약 60칸, 이상 줄 80줄) — 사본 읽기만 바꾸고 `summary.groups`·`window.anomaly`를 그대로 부른다."""
    from triagelib import summary, window
    recs = _long_recs()
    monkeypatch.setattr(window, "served_copies", lambda job, analysis: ([Path("x.log")], []))
    monkeypatch.setattr(window, "_records", lambda job, ev, served, defaults: (recs, None, {}))
    ev = {"mask_off": True, "input": {"tz": "UTC", "window": None},
          "events": [{"pid": 1500, "ts": T0, "tag": "DNC-0", "msg": "x"}, {"pid": 1000, "ts": T0, "tag": "CS", "msg": "y"}]}
    got = summary.groups(Path("."), ev, {}, {}, ref, 60, guess=guess, after_sec=600)
    anomaly = window.anomaly(Path("."), ev, {}, {}, ref, 600, 80, set(), guess=guess)
    return got, anomaly


def test_long_log_keeps_symptom_process_lines_with_or_without_reference(monkeypatch):
    """받아들일 기준(설계 A653): 기준 시각 입력 없음(증상 시각 후보 3개만)·있음 둘 다 두 줄이 요약 60칸 또는 이상 줄 80줄 안,
    잡음 태그가 80줄을 다 채우지 않고, 폭주(x4000) 모양이 기준 둘레 드문 모양을 밀어내지 않는다. 같은 입력이면 같은 결과."""
    guess = ["2026-11-20T08:00:00.000Z", T0, "2026-11-20T12:30:00.000Z"]
    seen = {}
    for ref, cands in ((None, guess), (T0, ())):
        got, anomaly = seen[ref] = _long_pick(monkeypatch, ref, cands)
        groups, rows = got["groups"], anomaly["rows"]
        assert len(groups) == 60 and sum(1 for r in rows) <= 80
        for want in (TARGET_E, TARGET_W):
            assert any(g["msg"] == want for g in groups) or any(r["msg"] == want for r in rows), (ref, want)
        assert any(r["msg"] == TARGET_E for r in rows) and any(r["msg"] == TARGET_W for r in rows), ref     # 이상 줄 절에도 둘 다
        assert sum(r["tag"].startswith("NoiseSvc") for r in rows) < 60, ref          # 흔한 잡음 태그가 절을 다 채우지 않는다
        assert sum(r["msg"] == "queue overflow" for r in rows) == 1 and sum(g["msg"] == "queue overflow" for g in groups) <= 1
        assert any(r["msg"] == "firmware assert in modem watchdog" for r in rows), ref      # 폭주가 드문 모양을 밀지 않는다
        assert any(g["msg"] == "firmware assert in modem watchdog" for g in groups), ref
        assert [r["ts"] for r in rows] == sorted(r["ts"] for r in rows)              # 이상 줄 절은 시각순
        assert (got.get("guess") == guess and got["ref"] is None) if ref is None else (got["ref"] == T0 and "guess" not in got)
        assert (anomaly.get("guess") == guess) if ref is None else anomaly["ref"] == T0
    assert _long_pick(monkeypatch, None, guess) == seen[None]                       # 같은 입력이면 같은 결과
    assert "- 기준: 2026-11-20T10:00:00.000Z" in report.anomaly_lines(seen[T0][1])
    assert "기준: 증상 시각 후보 3개(스크립트 추정" in report.summary_lines(seen[None][0])[2]
    assert any("기준: 증상 시각 후보 3개(스크립트 추정" in x for x in report.anomaly_lines(seen[None][1]))


def test_dump_bodies_are_frames_and_hex_folds():
    """R-12·4-6: ART abort 덤프 몸통(`runtime.cc:761]` 뒤 at·native·스레드 머리·빈 줄)과 tombstone 레지스터 줄은 프레임(세지 않는다),
    덤프 머리(`Runtime aborting...`)는 남는다. 0x 없는 16진수·태그 안 숫자도 접는다."""
    from triagelib import window
    for msg in ("runtime.cc:761]   at android.os.Looper.loop(Looper.java:288)", "runtime.cc:761]   native: #00 pc 0005f4b6  /apex/libc.so",
                'runtime.cc:761] "binder:612_3" prio=5 tid=33 Native', "runtime.cc:761]   | held mutexes=", "runtime.cc:761] ",
                "runtime.cc:761]   - waiting on an unknown object", "runtime.cc:761]   (no managed stack frames)",
                "    rax 00000000000000ab  rbx 00007ffd3c3e9e58  rcx 00007f1d2b2c4e2c  rdx 000000000000000c",
                "rax 00000000000000ab rbx 00007ffd3c3e9e58", "    x0  00000000000000ab  x1  0000007fd1a2b3c0"):
        assert window.FRAME_RX.match(msg), msg
    for msg in ("runtime.cc:761] Runtime aborting...", "signal 6 (SIGABRT), code -1 (SI_QUEUE)", "rax is zero", "cid 1 state 2"):
        assert not window.FRAME_RX.match(msg), msg
    base = {"phone_id": None, "level": "E", "tag": "DN-138-C"}
    assert window._fold_key({**base, "msg": "BuildId: aa1c2bc3d4e5f607"}) == window._fold_key(
        {**base, "tag": "DN-140-C", "msg": "BuildId: 0b9a8c7d6e5f4a3b"})
