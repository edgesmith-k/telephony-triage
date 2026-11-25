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
from triagelib import core, modulecmd  # noqa: E402

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
    for msg, want in (("mCallback.onError called", 3), ("result.isError=false", 3),      # 머리 아님(오류 문구 등급)
                      ("java.lang.IllegalStateException: x", 1), ("android.os.DeadObjectException", 1)):
        assert window.rank({"level": "D", "msg": msg}) == want, msg


def test_fold_key_keeps_slots_and_levels_apart():
    """4: 다른 SIM 슬롯·레벨의 같은 문구를 한 줄로 접지 않는다(merge_rows F2와 같은 원칙)."""
    from triagelib import window
    base = {"tag": "DNC", "level": "E", "msg": "setup failed 3", "phone_id": 0}
    assert window._fold_key(base) != window._fold_key({**base, "phone_id": 1})
    assert window._fold_key(base) != window._fold_key({**base, "level": "W"})
    assert window._fold_key(base) == window._fold_key({**base, "msg": "setup failed 4"})


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
    """F > 예외·crash 머리 > E > 그 밖의 레벨 중 오류 문구(0 값 오류 칸 제외) > W > 나머지."""
    from triagelib import window
    recs = [{"level": "I", "msg": "deactivate rsp error=0"}, {"level": "W", "msg": "poll slow"},
            {"level": "I", "msg": "setup rsp error=38"}, {"level": "E", "msg": "setup failed"},
            {"level": "I", "msg": "ofonod[812]: Aborting (signal 11) [/usr/sbin/ofonod]"}, {"level": "F", "msg": "x"}]
    assert [window.rank(r) for r in recs] == [5, 4, 3, 2, 1, 0]
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
