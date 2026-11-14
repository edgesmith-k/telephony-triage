"""성공 흐름 점검 (04-parser-matching.md §5.13): 엔진 판정(ok·값이상·없음·로그끝·-), 같은 열쇠 합치기(V-1), pid·로그 경계(V-2),
같은 ms 되돌아보기(W-3), 듀얼 SIM(W-4), 빈 목록·앵커(W-1), 버전 표시, 자르기(정상 로그를 단계 직전에서 잘라도 `없음`이 아님),
`then` 잇기, CLI 마스킹 경로, triage 리포트 절·analysis 키·캐시 키, 흐름 없는 DB 출력 불변(W-2).
로그는 모두 작은 합성 조각이다(AOSP 프레임워크 문구 모양, 값은 문서용 IP·마스킹 토큰)."""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from common import compiled, flows, logtime  # noqa: E402
from runner import SAMPLE, run_json, tmp  # noqa: E402
from triagelib.report import fit, flow_section  # noqa: E402

SEEDS = REPO / "templates" / "issue-db-seeds" / "android"     # 흐름 정의는 시드 계획의 put-flow 한 벌만 둔다
CATS = {"data-setup": "data", "radio-on": "network"}
T0 = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
PHONE = 100


def _flow(name: str) -> dict:
    plan = json.loads((SEEDS / CATS[name] / "plan.json").read_text(encoding="utf-8"))
    return next(op["flow"] for op in plan["operations"] if op["op"] == "put-flow" and op["ref"] == f"{CATS[name]}/{name}")


def _flow_text(name: str) -> str:
    return yaml.safe_dump(_flow(name), allow_unicode=True, sort_keys=False)


def _defs(*names) -> list[dict]:
    return [{**_flow(name), "category": CATS[name], "ref": f"{CATS[name]}/{name}"} for name in names]


def _recs(rows):
    """(초, 태그, msg[, pid[, phone]]) → (줄 레코드, `TAG: msg`). 이미 마스킹된 합성 값이다."""
    recs = []
    for n, row in enumerate(rows, 1):
        sec, tag, msg, pid, phone = (tuple(row) + (PHONE, None))[:5]
        recs.append({"ts": logtime.format_ts(T0 + timedelta(seconds=sec)), "pid": pid, "tag": tag,
                     "msg": msg, "phone_id": phone, "event": None, "line_ref": {"file_index": 0, "line_no": n}})
    return recs, [f"{r['tag']}: {r['msg']}" for r in recs]


def _check(rows, names=("data-setup",), **kw):
    recs, texts = _recs(rows)
    out, warnings = flows.check(_defs(*names), recs, texts, timeout_ms=0, **kw)
    assert not warnings
    return out


def _sig(inst) -> str:
    return " ".join(s["verdict"] for s in inst["steps"])


SETUP = "ConnectingState: setupData: accessNetwork=NGRAN, isSatellite=false"
RESP_OK = ("ConnectingState: onSetupResponse: resultCode=RESULT_SUCCESS, response=DataCallResponse: { cause=NONE(0x0) "
           "retry=-1 cid=1 ifname=rmnet0 addresses=[<IP#1>/24] dnses=[/<IP#2>] gateways=[/<IP#3>] pcscf=[]")
RESP_BAD = ("ConnectingState: onSetupResponse: resultCode=RESULT_SUCCESS, response=DataCallResponse: { cause=NONE(0x0) "
            "retry=-1 cid=1 ifname=rmnet0 addresses=[] dnses=[] gateways=[] pcscf=[]")
LP_OK = ("ConnectingState: sendLinkProperties {InterfaceName: rmnet0 LinkAddresses: [ <IP#1>/24 ] DnsAddresses: [ /<IP#2> ] "
         "Domains: null MTU: 1500 Routes: [ <IP#4>/0 -> <IP#3> rmnet0 mtu 1500 ]}")
CONNECTED = "ConnectedState: network connected."
VALID = "onDataNetworkValidationStatusChanged: [DataNetwork: DN-1-C, internet, state=ConnectedState], validation status={}, "


def _normal(tag="DN-1-C", t=0.0):
    return [(t, tag, SETUP), (t + 0.03, tag, RESP_OK), (t + 0.032, tag, LP_OK), (t + 0.035, tag, CONNECTED),
            (t + 0.3, "DNC-0", VALID.format("VALID").replace("DN-1-C", tag), PHONE, 0)]


TICK = (30.0, "Other", "tick")


# -- 판정 값 ------------------------------------------------------------------------------------------


def test_normal_instance_is_ok_through_and_log_end_when_tail_is_short():
    [f] = _check(_normal() + [TICK])
    [inst] = f["instances"]
    assert _sig(inst) == "ok ok ok ok" and inst["key"] == "DN-1-C" and inst["line_ref"] == {"file_index": 0, "line_no": 1}
    assert inst["end"] is None and inst["restarts"] == 0 and inst["steps"][0]["detail"] == "0.030s"
    # 망 검증 줄 없이 3초 만에 로그가 끝나면 판정 불가(로그끝), 10초 넘게 남으면 없음
    [f] = _check(_normal()[:4] + [(3.0, "Other", "tick")])
    assert _sig(f["instances"][0]) == "ok ok ok 로그끝"
    [f] = _check(_normal()[:4] + [TICK])
    assert _sig(f["instances"][0]) == "ok ok ok 없음" and f["instances"][0]["steps"][3]["detail"] == "뒤 로그 30s"


def test_bad_value_shows_why_and_values_then_dash():
    [f] = _check([(0, "DN-1-C", SETUP), (0.03, "DN-1-C", RESP_BAD.replace("RESULT_SUCCESS", "RESULT_ERROR_INVALID_ARG")), TICK])
    inst = f["instances"][0]
    assert _sig(inst) == "값이상 - - -" and inst["steps"][0]["bad_count"] == 1
    assert inst["steps"][0]["detail"] == "응답 오류·주소 빔·DNS 빔: resultCode=RESULT_ERROR_INVALID_ARG, cause=NONE"
    assert inst["steps"][0]["line_ref"]["line_no"] == 2


def test_ok_after_bad_counts_earlier_bad_values():
    rows = _normal()[:4] + [(0.2, "DNC-0", VALID.format("INVALID"), PHONE, 0), (0.4, "DNC-0", VALID.format("VALID"), PHONE, 0), TICK]
    inst = _check(rows)[0]["instances"][0]
    assert _sig(inst) == "ok ok ok ok" and inst["steps"][3]["bad_count"] == 1
    assert inst["steps"][3]["detail"].endswith(", 그 전 이상 값 1회")


def test_missing_step_names_end_label_and_notes():
    rows = [(0, "DN-1-C", SETUP), (0.03, "DN-1-C", RESP_OK), (0.031, "DN-1-C", "Duplicate network interface rmnet0"),
            (0.04, "DN-1-C", "DisconnectedState: Data network disconnected. reason=x"), TICK]
    inst = _check(rows)[0]["instances"][0]
    assert _sig(inst) == "ok 없음 - -" and inst["steps"][1]["detail"] == "연결 해제로 끝남"
    assert inst["end"]["label"] == "연결 해제" and inst["notes"] == ["Duplicate network interface"]


def test_empty_link_property_list_with_space_is_bad_value():
    """W-1: LinkProperties 빈 목록은 `[ ]`(공백)다 — `\\[[^\\]]`이면 ok로 샌다."""
    rows = _normal()[:2] + [(0.032, "DN-1-C", LP_OK.replace("[ <IP#1>/24 ]", "[ ]")), TICK]
    inst = _check(rows)[0]["instances"][0]
    assert _sig(inst) == "ok 값이상 - -" and inst["steps"][1]["detail"].startswith("주소 빔")


def test_named_scope_takes_only_its_own_network():
    rows = _normal()[:4] + [(0.3, "DNC-0", VALID.format("VALID").replace("DN-1-C", "DN-11-C"), PHONE, 0), TICK]
    assert _sig(_check(rows)[0]["instances"][0]) == "ok ok ok 없음"


# -- V-1·V-2·W-3·W-4 ------------------------------------------------------------------------------


RADIO = [(0.0, "SST-0", "setRadioPower power true forEmergencyCall false forceApply false reason 0", PHONE, 0),
         (0.001, "SST-0", "setPowerStateToDesired: mDeviceShuttingDown=false, mDesiredPowerState=true, getRadioState=0, "
                          "mRadioPowerOffReasons=[], IMS reg state=false", PHONE, 0),
         (0.002, "RILJ", "[0243]> RADIO_POWER on = true forEmergencyCall= false [PHONE0]", PHONE, 0),
         (0.004, "RILJ", "[0243]< RADIO_POWER  [PHONE0]", PHONE, 0),
         (0.5, "SST-0", "Poll ServiceState done: newSS={mVoiceRegState=0(IN_SERVICE), mDataRegState=0(IN_SERVICE), "
                        "mChannelNumber=1}", PHONE, 0),
         (0.6, "DNC-0", "Data evaluation: evaluation reason:DATA_SERVICE_STATE_CHANGED, Data allowed reasons: NORMAL, "
                        "[NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED] ]", PHONE, 0),
         (0.61, "DN-1-C", SETUP, PHONE, None)]


def test_same_key_restart_is_merged_and_then_links_next_flow():
    rows = RADIO[:2] + [(0.0015, "SST-0", "setRadioPower power true forEmergencyCall true forceApply false reason 0", PHONE, 0)] \
        + RADIO[2:] + [(t + 0.61, tag, msg, *rest) for t, tag, msg, *rest in _normal()[1:]] + [TICK]
    out = {f["flow"]: f for f in _check(rows, ("radio-on", "data-setup"))}
    [radio] = out["network/radio-on"]["instances"]
    assert _sig(radio) == "ok ok ok ok ok ok" and radio["restarts"] == 1
    assert radio["then"] == {"flow": "data/data-setup", "index": 0, "key": "DN-1-C",
                             "start_ts": out["data/data-setup"]["instances"][0]["start_ts"]}
    assert _sig(out["data/data-setup"]["instances"][0]) == "ok ok ok ok"
    # 대상 흐름이 없으면 잇지 않는다
    [only] = _check(rows, ("radio-on",))
    assert only["then"] is None and only["instances"][0]["then"] is None


def test_new_instance_only_after_end_line():
    rows = RADIO[:2] + [(0.1, "SST-0", "setRadioPower power false forEmergencyCall false", PHONE, 0)] \
        + [(t + 1, tag, msg, *rest) for t, tag, msg, *rest in RADIO] + [TICK]
    insts = _check(rows, ("radio-on",))[0]["instances"]
    assert [_sig(i) for i in insts] == ["ok 없음 - - - -", "ok ok ok ok ok ok"]
    assert insts[0]["steps"][1]["detail"] == "무선 끔으로 끝남"


def test_other_pid_lines_are_ignored_and_same_tag_other_pid_closes():
    rows = [(r[0], r[1], r[2], 200 if r[1] == "RILJ" else PHONE, r[4]) for r in RADIO[:4]] + [TICK]
    assert _sig(_check(rows, ("radio-on",))[0]["instances"][0]) == "ok 없음 - - - -"
    rows = RADIO[:2] + [(1.0, "SST-0", "Poll ServiceState done: newSS={mDataRegState=0(IN_SERVICE)}", 300, 0), TICK]
    inst = _check(rows, ("radio-on",))[0]["instances"][0]
    assert inst["end"]["label"] == "프로세스 재시작" and _sig(inst) == "ok - - - - -"
    assert inst["steps"][1]["detail"] == "프로세스 재시작으로 끝남"


def test_clock_anomaly_and_reboot_line_close_as_log_boundary():
    rows = RADIO[:2] + [(1.0, "Other", "x")] + [(2.0, *RADIO[2][1:])] + [TICK]
    recs, _ = _recs(rows)
    inst = _check(rows, ("radio-on",), anomalies=[recs[2]["ts"]])[0]["instances"][0]
    assert inst["end"]["label"] == "로그 경계" and _sig(inst) == "ok - - - - -"
    inst = _check(rows, ("radio-on",), breaks={2})[0]["instances"][0]
    assert inst["end"] == {"label": "로그 경계", "ts": recs[2]["ts"]}


def test_same_ms_line_before_previous_step_is_looked_back():
    """W-3: 버퍼별 파일을 같이 주면 같은 ms에서 다음 단계 줄이 앞에 놓일 수 있다."""
    rows = [(0, "DN-1-C", SETUP), (0.03, "DN-1-C", LP_OK), (0.03, "DN-1-C", RESP_OK), (0.035, "DN-1-C", CONNECTED), TICK]
    assert _sig(_check(rows)[0]["instances"][0]) == "ok ok ok 없음"
    rows[1] = (0.029, "DN-1-C", LP_OK)          # 다른 ms면 되돌아보지 않는다
    assert _sig(_check(rows)[0]["instances"][0]) == "ok 없음 - -"


def test_dual_sim_any_scope_skips_other_slot():
    """W-4: `scope: any` 단계는 슬롯이 다른 줄(SST-1의 인스턴스에 [PHONE0] 줄)을 쓰지 않는다. `None`은 와일드카드."""
    one = [(r[0], r[1].replace("-0", "-1"), r[2], PHONE, 1) for r in RADIO[:2]]
    rows = sorted(RADIO[:4] + one, key=lambda r: r[0]) + [TICK]
    by = {i["key"]: _sig(i) for i in _check(rows, ("radio-on",))[0]["instances"]}
    assert by == {"SST-0": "ok ok ok 없음 - -", "SST-1": "ok 없음 - - - -"}
    rows = sorted(RADIO[:2] + one + [(r[0], r[1], r[2], PHONE, None) for r in RADIO[2:4]], key=lambda r: r[0]) + [TICK]
    assert {i["key"]: _sig(i) for i in _check(rows, ("radio-on",))[0]["instances"]} == \
        {"SST-0": "ok ok ok 없음 - -", "SST-1": "ok ok ok 없음 - -"}


def test_cut_before_each_step_never_says_missing():
    """자르기: 끝까지 정상인 로그를 각 단계 줄 직전에서 자르면 그 단계는 `로그끝`이지 `없음`이 아니다."""
    for names, rows in ((("data-setup",), _normal()), (("radio-on",), RADIO)):
        recs, texts = _recs(rows)
        [full] = flows.check(_defs(*names), recs, texts, timeout_ms=0)[0]
        inst = full["instances"][0]
        assert set(_sig(inst).split()) == {"ok"}
        for k, step in enumerate(inst["steps"]):
            cut = step["line_ref"]["line_no"] - 1
            [part] = flows.check(_defs(*names), recs[:cut], texts[:cut], timeout_ms=0)[0]
            assert part["instances"][0]["steps"][k]["verdict"] == "로그끝", (names, step["id"])


# -- 정의·버전·CLI --------------------------------------------------------------------------------


def _db(path: Path, *names) -> Path:
    (path / "issue-db.config.yaml").write_text("categories:\n  - {key: data}\n  - {key: network}\n", encoding="utf-8")
    for name in names:
        (path / CATS[name] / "flows").mkdir(parents=True, exist_ok=True)
        (path / CATS[name] / "flows" / f"{name}.yaml").write_text(_flow_text(name), encoding="utf-8")
    return path


def test_definitions_pass_schema_and_bad_files_are_skipped(tmp_path):
    db = _db(tmp_path, "data-setup", "radio-on")
    defs, warnings = flows.load(db, {"categories": [{"key": "data"}, {"key": "network"}]})
    assert [d["ref"] for d in defs] == ["data/data-setup", "network/radio-on"] and not warnings
    (db / "data" / "flows" / "other.yaml").write_text(_flow_text("data-setup"), encoding="utf-8")
    defs, warnings = flows.load(db, {"categories": [{"key": "data"}]})
    assert [d["ref"] for d in defs] == ["data/data-setup"] and "id가 파일 이름과 다르다" in warnings[0]["message"]


def test_version_is_shown_not_filtered():
    assert flows.version_match(["17"], "17") is True and flows.version_match(["17"], "16") is False
    assert flows.version_match(["17"], "Android 17") is None and flows.version_match([], "17") is None
    import match_signatures
    cause = type("C", (), {"raw": {"platform_versions": ["16"]}})()
    assert match_signatures._version_match(cause, {"platform_version": "16.1"}) is True
    doc = {"flows": _check(_normal() + [TICK])}
    assert flow_section(doc, None, None, "16", {})[1] == [
        "- 흐름 점검: 데이터 연결 1회 끝까지 정상 (흐름 기준 버전 17 — 이 이슈는 16, 줄 문구가 다를 수 있다)"]
    assert flow_section(doc, None, None, "17", {})[1] == ["- 흐름 점검: 데이터 연결 1회 끝까지 정상"]
    assert flow_section(doc, None, None, None, {})[1] == ["- 흐름 점검: 데이터 연결 1회 끝까지 정상 (흐름 기준 버전 17)"]


THREADTIME = "11-10 12:00:{sec:06.3f}  1001 {pid} {pid} D {tag}: {msg}"


def _log(path: Path, rows) -> Path:
    lines = [THREADTIME.format(sec=r[0], pid=PHONE, tag=r[1], msg=r[2]) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


RAW = [(0, "DN-1-C", SETUP),
       (0.03, "DN-1-C", RESP_OK.replace("<IP#1>", "192.0.2.15").replace("<IP#2>", "192.0.2.3").replace("<IP#3>", "192.0.2.2")),
       (0.032, "DN-1-C", "ConnectingState: sendLinkProperties {InterfaceName: rmnet0 LinkAddresses: [ ] DnsAddresses: "
                         "[ /192.0.2.3 ] Domains: null MTU: 1500 Routes: [ 0.0.0.0/0 -> 192.0.2.2 rmnet0 mtu 1500 ]}"),
       (0.04, "DN-1-C", "DisconnectedState: Data network disconnected. reason=x"), (40.0, "Other", "tick")]


def test_cli_masks_output_lines_and_reports_steps():
    work = tmp("tt-flows-")
    (work / "db").mkdir()
    db = _db(work / "db", "data-setup")
    log = _log(work / "a.log", RAW)
    out = run_json("parse_logcat.py", ["flows", log, "--rules", db / "parser-rules", "--tz", "UTC", "--year", "2026"])
    [f] = out["flows"]
    inst = f["instances"][0]
    assert f["flow"] == "data/data-setup" and _sig(inst) == "ok 값이상 - -"
    assert inst["steps"][1]["detail"] == "주소 빔" and inst["line_ref"] == {"file_index": 0, "line_no": 1}
    assert "192.0.2" not in json.dumps(out)
    # 단계 줄은 가리지 않은 글에서 찾고, 출력에 글자가 나가는 줄(메모·값)만 가린다
    path = db / "data" / "flows" / "data-setup.yaml"
    flow = _flow("data-setup")
    flow["notes"] = [{"scope": "own", "pattern": r"addresses=\[[^\]]*\]"}]
    flow["steps"][1]["show"] = [r"DnsAddresses: \[[^\]]*\]"]
    path.write_text(yaml.safe_dump(flow, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = run_json("parse_logcat.py", ["flows", log, "--rules", db / "parser-rules", "--tz", "UTC", "--year", "2026"])
    inst = out["flows"][0]["instances"][0]
    assert _sig(inst) == "ok 값이상 - -" and "192.0.2" not in json.dumps(out)
    assert re.fullmatch(r"addresses=\[<IP#\d+>/24\]", inst["notes"][0])
    assert re.search(r"DnsAddresses: \[ /<IP#\d+> \]", inst["steps"][1]["detail"])
    # 흐름 파일이 없으면 파싱하지 않고 빈 목록
    shutil.rmtree(db / "data")
    assert run_json("parse_logcat.py", ["flows", log, "--rules", db / "parser-rules"])["flows"] == []


# -- triage ---------------------------------------------------------------------------------------


def _triage(db: Path, out: Path, rows=RAW) -> dict:
    log = _log(out.parent / f"{out.name}.log", rows)
    meta = out.parent / f"{out.name}.meta.json"
    meta.write_text(json.dumps({"key": "MOCK-7001", "occurred_at": "2026-11-10T12:00:01+00:00", "summary": "data"}),
                    encoding="utf-8")
    return run_json("triage.py", ["run", "MOCK-7001", "--offline-db", db, "--out", out, "--logs", log, "--issue-meta", meta,
                                  "--tz", "UTC", "--year", "2026"], env={"TT_SCHEMA_CHECK": "1"})


def _sample_with_flow(work: Path, flow_step: str | None = None) -> Path:
    db = work / "db"
    shutil.copytree(SAMPLE, db)
    (db / "data" / "flows").mkdir()
    (db / "data" / "flows" / "data-setup.yaml").write_text(_flow_text("data-setup"), encoding="utf-8")
    if flow_step:
        type_md = db / "data" / "DATA-001-no-setup-data-call" / "type.md"
        text = type_md.read_text(encoding="utf-8")
        type_md.write_text(text.replace("  - id: DATA-001-01\n", f"  - id: DATA-001-01\n    flow_step: {flow_step}\n", 1),
                           encoding="utf-8")
    return db


def test_triage_report_section_analysis_key_and_flow_json():
    work = tmp("tt-flows-")
    db = _sample_with_flow(work, "data/data-setup/link-properties")
    analysis = _triage(db, work / "a")
    report = (work / "a" / "report.md").read_text(encoding="utf-8")
    lines = [line for line in report.splitlines() if "흐름 점검" in line or "→ 의심" in line or "데이터 연결 DN-1-C" in line]
    assert lines[0] == "- 흐름 점검 (판정·점수 아님, S/C 불변; 흐름 기준 버전 17):"
    assert lines[1] == "  - 데이터 연결 DN-1-C (f0:L1): 응답 받음 ok → 설정 만듦 값이상(주소 빔)"
    assert lines[2].startswith("    → 의심: DataNetwork(응답 → 설정 변환) / 이 단계의 원인: DATA-001-01 ")
    assert analysis["flows"] == [{"flow": "data/data-setup", "key": "DN-1-C", "step": "link-properties", "verdict": "값이상",
                                  "at": "f0:L3", "causes": ["DATA-001-01"]}]
    assert json.loads((work / "a" / "flow.json").read_text(encoding="utf-8"))["flows"][0]["flow"] == "data/data-setup"
    # 분석 범위 밖 인스턴스만 있으면 해당 없음(버전 표시는 test_version_is_shown_not_filtered — 오프라인 메타엔 버전이 없다)
    late = [(r[0] + 59 * 60 if r[1] != "Other" else r[0], *r[1:]) for r in RAW[:4]]
    early = [(0.0, "Other", "first")] + [(r[0] + 1200, *r[1:]) for r in late]
    analysis = _triage(db, work / "c", rows=early)
    assert "- 흐름 점검: 해당 없음" in (work / "c" / "report.md").read_text(encoding="utf-8") and "flows" not in analysis


def test_triage_without_flow_files_is_unchanged():
    """W-2: 흐름 파일이 없는 DB는 흐름 단계를 부르지 않고 report.md·analysis.json에 아무것도 더하지 않는다."""
    work = tmp("tt-flows-")
    analysis = _triage(SAMPLE, work / "a")
    report = (work / "a" / "report.md").read_text(encoding="utf-8")
    assert "흐름 점검" not in report and "flows" not in analysis and not (work / "a" / "flow.json").exists()
    trace = (work / "a" / "trace.jsonl").read_text(encoding="utf-8")
    assert "4-flows" not in trace


def test_cache_key_includes_flow_files(tmp_path):
    db = _sample_with_flow(tmp_path)
    config = yaml.safe_load((db / "issue-db.config.yaml").read_text(encoding="utf-8"))
    assert db / "data" / "flows" / "data-setup.yaml" in compiled.source_files(db, config)
    before = compiled.source_hash(db, config, {})
    path = db / "data" / "flows" / "data-setup.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("title: 데이터 연결", "title: 데이터 연결2"), encoding="utf-8")
    assert compiled.source_hash(db, config, {}) != before


def test_fit_trims_flows_after_partial():
    item = {"flow": "data/data-setup", "key": "DN-1-C", "step": "link-properties", "verdict": "없음", "at": "f0:L100000"}
    big = [{"ts": "t", "tag": "T", "msg": "x" * 140} for _ in range(23)]
    out = fit({"status": "ok", "candidates": [{"type": "T", "evidence": list(big)}], "flows": [item] * 3,
               "files": {"report": "r"}, "warnings": []})
    assert len(out.get("flows") or []) <= 1 and len(out["candidates"][0]["evidence"]) == 23
