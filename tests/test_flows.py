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

import pytest
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
    inst = _check(rows, ("radio-on",), anomalies=[{"ts": recs[2]["ts"], "kind": "jump", "delta_sec": 3600.0}])[0]["instances"][0]
    assert inst["end"]["label"] == "로그 경계" and _sig(inst) == "ok - - - - -"
    inst = _check(rows, ("radio-on",), breaks={2})[0]["instances"][0]
    assert inst["end"] == {"label": "로그 경계", "ts": recs[2]["ts"]}


def test_clock_going_back_closes_instance_opened_in_overlap_cli():
    """F-1: 시계가 뒤로 가면(NITZ 등) 시각순 정렬에서 역행 뒤 줄이 시작 줄 앞에 놓인다 — 거짓 `없음` 대신 `로그 경계`."""
    work = tmp("tt-flows-")
    (work / "db").mkdir()
    db = _db(work / "db", "radio-on")
    rows = [(5.0, *RADIO[0][1:3]), (5.001, *RADIO[1][1:3]), (0.002, *RADIO[2][1:3]), (0.004, *RADIO[3][1:3]),
            (30.0, "Other", "tick")]
    log = _log(work / "clock.log", rows)
    out = run_json("parse_logcat.py", ["flows", log, "--rules", db / "parser-rules", "--tz", "UTC", "--year", "2026"])
    [inst] = out["flows"][0]["instances"]
    assert inst["end"]["label"] == "로그 경계" and _sig(inst) == "ok - - - - -"
    assert inst["steps"][1]["detail"] == "로그 경계로 끝남"


def _two_files(rows, second: set[int]):
    """줄 순번 `second`는 다른 파일(file_index 1)의 줄이다."""
    recs, texts = _recs(rows)
    for n in second:
        recs[n]["line_ref"] = {"file_index": 1, "line_no": n + 1}
    return flows.check(_defs("data-setup"), recs, texts, timeout_ms=0)[0][0]["instances"]


def test_same_ms_line_before_previous_step_is_looked_back_only_across_files():
    """W-3·F-9: 버퍼별 파일을 같이 주면 같은 ms에서 다음 단계 줄이 앞에 놓일 수 있다 — 다른 파일 줄만 되돌아본다."""
    rows = [(0, "DN-1-C", SETUP), (0.03, "DN-1-C", LP_OK), (0.03, "DN-1-C", RESP_OK), (0.035, "DN-1-C", CONNECTED), TICK]
    assert _sig(_two_files(rows, {1})[0]) == "ok ok ok 없음"
    rows[1] = (0.029, "DN-1-C", LP_OK)          # 다른 ms면 되돌아보지 않는다
    assert _sig(_two_files(rows, {1})[0]) == "ok 없음 - -"
    # 한 파일 안의 뒤집힌 순서(connected → link-properties → response)는 실제 순서다 — ok가 아니다
    rows = [(0, "DN-1-C", SETUP), (0.03, "DN-1-C", CONNECTED), (0.03, "DN-1-C", LP_OK), (0.03, "DN-1-C", RESP_OK), TICK]
    assert _sig(_check(rows)[0]["instances"][0]) == "ok 없음 - -"
    recs, texts = _recs(rows)
    for r in recs:
        r["line_ref"] = None                     # 파일 순번이 없으면 되돌아보지 않는다
    assert _sig(flows.check(_defs("data-setup"), recs, texts, timeout_ms=0)[0][0]["instances"][0]) == "ok 없음 - -"


def test_dual_sim_any_scope_skips_other_slot():
    """W-4: `scope: any` 단계는 슬롯이 다른 줄(SST-1의 인스턴스에 [PHONE0] 줄)을 쓰지 않는다. `None`은 와일드카드.
    F-6: 한 줄은 같은 흐름의 한 인스턴스만 쓴다 — 슬롯 없는 RIL 줄 한 벌은 먼저 연 SST-0만 쓴다."""
    one = [(r[0], r[1].replace("-0", "-1"), r[2], PHONE, 1) for r in RADIO[:2]]
    rows = sorted(RADIO[:4] + one, key=lambda r: r[0]) + [TICK]
    by = {i["key"]: _sig(i) for i in _check(rows, ("radio-on",))[0]["instances"]}
    assert by == {"SST-0": "ok ok ok 없음 - -", "SST-1": "ok 없음 - - - -"}
    rows = sorted(RADIO[:2] + one + [(r[0], r[1], r[2], PHONE, None) for r in RADIO[2:4]], key=lambda r: r[0]) + [TICK]
    assert {i["key"]: _sig(i) for i in _check(rows, ("radio-on",))[0]["instances"]} == \
        {"SST-0": "ok ok ok 없음 - -", "SST-1": "ok 없음 - - - -"}


def test_dual_sim_slotless_setup_line_goes_to_one_instance_only():
    """F-6: `DN-n-C`(슬롯 없음) setupData 하나를 두 슬롯 인스턴스가 함께 `setup-start`로 쓰고 `then`이 남의 연결에 붙지 않는다."""
    one = [(r[0], r[1].replace("-0", "-1"), r[2].replace("[PHONE0]", "[PHONE1]").replace("[0243]", "[0244]"), PHONE, 1)
           for r in RADIO[:6]]
    rows = sorted(RADIO + one, key=lambda r: r[0]) + [TICK]
    out = {f["flow"]: f for f in _check(rows, ("radio-on", "data-setup"))}
    by = {i["key"]: i for i in out["network/radio-on"]["instances"]}
    assert _sig(by["SST-0"]) == "ok ok ok ok ok ok" and by["SST-0"]["then"]["key"] == "DN-1-C"
    assert by["SST-1"]["steps"][5]["verdict"] != "ok" and by["SST-1"]["then"] is None


ALREADY = "setRadioPower mDesiredPowerState is already true Do nothing."
POLL = RADIO[4][2]


def test_radio_already_on_is_not_an_instance():
    """F-2: 이미 켜진 무선의 `setRadioPower power true`(AOSP ServiceStateTracker: 곧바로 `already true Do nothing`)는
    인스턴스가 아니다(거짓 `켬 결정 없음`·엉뚱한 원인 대신 출력 없음)."""
    rows = [(0.0, *RADIO[0][1:]), (0.001, "SST-0", ALREADY, PHONE, 0), (5.0, "SST-0", POLL, PHONE, 0), TICK]
    [f] = _check(rows, ("radio-on",))
    assert f["instances"] == []
    assert flow_section({"flows": [f]}, None, None, "17", {})[1] == ["- 흐름 점검: 해당 없음"]


def test_radio_already_on_line_inside_progress_is_ignored():
    """F-2 (c15 모양): 진행 중 인스턴스에 시작 줄이 또 오고 already-true 줄이 와도 닫히지 않고 그대로 진행한다."""
    rows = RADIO[:2] + [(0.0015, *RADIO[0][1:]), (0.0016, "SST-0", ALREADY, PHONE, 0)] + RADIO[2:] + [TICK]
    [inst] = _check(rows, ("radio-on",))[0]["instances"]
    assert _sig(inst) == "ok ok ok ok ok ok" and inst["restarts"] == 1 and inst["end"] is None


def test_optional_step_without_lines_is_not_a_deviation():
    """F-7: 선택 단계(`data-allowed`)에 맞는 줄이 하나도 없으면 `-`(줄 없음(선택 단계)) — 벗어남이 아니다.
    이상 값 줄이 계속되면 지금처럼 `값이상`. 선택 단계가 `ok`면 다음 필수 단계는 그대로 판정한다(C-2: 허용 뒤 SETUP 없음)."""
    [f] = _check(RADIO[:5] + [TICK], ("radio-on",))
    inst = f["instances"][0]
    assert _sig(inst) == "ok ok ok ok - -" and inst["steps"][4]["detail"] == flows.OPTIONAL_NONE
    assert flow_section({"flows": [f]}, None, None, "17", {})[1] == ["- 흐름 점검: 무선 켬 1회 정상(데이터 허용 줄은 없어도 되는 단계라 없음)"]
    deny = RADIO[5][2].replace("Data allowed reasons: NORMAL", "Data disallowed reasons: DATA_DISABLED")
    [f] = _check(RADIO[:5] + [(0.6, "DNC-0", deny, PHONE, 0), TICK], ("radio-on",))
    assert _sig(f["instances"][0]) == "ok ok ok ok 값이상 -"
    lines = flow_section({"flows": [f]}, None, None, "17", {})[1]
    assert lines[1].endswith("데이터 허용에서 이상한 값(평가 거부: Data disallowed reasons: DATA_DISABLED)")
    [f] = _check(RADIO[:6] + [TICK], ("radio-on",))
    assert _sig(f["instances"][0]) == "ok ok ok ok ok 없음"


def test_clock_going_back_before_any_flow_line_does_not_close_later_instance():
    """C-1: 역행 구간에 흐름 줄이 하나도 없으면(역행 뒤 첫 흐름 줄이 이미 구간 끝을 넘음) 그 뒤에 연 인스턴스는 그대로다."""
    rows = [(t + 20.0, tag, msg, *rest) for t, tag, msg, *rest in RADIO] + [(60.0, "Other", "tick")]
    recs, _ = _recs([(8.0, "Other", "b")])
    [f] = _check(rows, ("radio-on",), anomalies=[{"ts": recs[0]["ts"], "kind": "backward", "delta_sec": -2.0}])
    [inst] = f["instances"]
    assert _sig(inst) == "ok ok ok ok ok ok" and inst["end"] is None


def test_discard_line_keeps_instance_that_already_had_bad_values():
    """C-4: `as: discard` 줄은 충족된 단계도 이상 값도 없을 때만 인스턴스를 버린다."""
    bad = RADIO[1][2].replace("mRadioPowerOffReasons=[]", "mRadioPowerOffReasons=[1]")
    rows = [RADIO[0], (0.001, "SST-0", bad, PHONE, 0), (0.002, "SST-0", ALREADY, PHONE, 0), TICK]
    [inst] = _check(rows, ("radio-on",))[0]["instances"]
    assert _sig(inst).startswith("값이상")


def test_start_after_all_steps_done_is_a_new_instance():
    """11/15 리뷰 D1-02: 모든 단계를 지난 인스턴스에 같은 열쇠의 시작 줄이 또 오면 합치지 않고 닫는다(`다시 시작`) —
    다시 켠 시도가 실패했는데 "1회 끝까지 정상"으로만 보이지 않게. no-op 시작(already true)은 그대로 버려진다."""
    oos = RADIO[4][2].replace("mDataRegState=0(IN_SERVICE)", "mDataRegState=1(OUT_OF_SERVICE)")
    again = [(5.0, "SST-0", "setRadioPower power true forEmergencyCall true forceApply true reason 0", PHONE, 0),
             (5.001, "SST-0", RADIO[1][2], PHONE, 0),
             (5.002, "RILJ", "[0250]> RADIO_POWER on = true forEmergencyCall= true [PHONE0]", PHONE, 0),
             (5.004, "RILJ", "[0250]< RADIO_POWER  [PHONE0]", PHONE, 0), (5.5, "SST-0", oos, PHONE, 0)]
    [f] = _check(RADIO + again + [(40.0, "Other", "tick")], ("radio-on",))
    first, second = f["instances"]
    assert set(_sig(first).split()) == {"ok"} and first["end"]["label"] == flows.AGAIN and first["restarts"] == 0
    assert "값이상" in _sig(second) and second["restarts"] == 0
    lines = flow_section({"flows": [f]}, None, None, "17", {})[1]
    assert lines[0].startswith("- 흐름 점검 (참고용") and any("이상" in x for x in lines[1:])
    noop = [(10.0 + k, "SST-0", RADIO[0][2], PHONE, 0) for k in range(3)]
    noop += [(10.001 + k, "SST-0", ALREADY, PHONE, 0) for k in range(3)]
    [inst] = _check(sorted(RADIO + noop) + [(40.0, "Other", "tick")], ("radio-on",))[0]["instances"]
    assert set(_sig(inst).split()) == {"ok"} and inst["restarts"] == 0


def test_instances_over_cap_keep_the_tail_and_say_so():
    """F-3: 상한을 넘으면 뒤쪽 INSTANCES_MAX개를 남기고, 분석 범위에 남은 인스턴스가 없으면 '판정 못 함' 줄."""
    bad = RESP_BAD.replace("RESULT_SUCCESS", "RESULT_ERROR_INVALID_ARG")
    rows = []
    for n in range(flows.INSTANCES_MAX + 1):
        rows += [(n * 2.0, f"DN-{n}-C", SETUP), (n * 2.0 + 0.03, f"DN-{n}-C", bad)]
    [f] = _check(rows + [(3000.0, "Other", "tick")])
    assert f["truncated"] and len(f["instances"]) == flows.INSTANCES_MAX
    assert f["instances"][0]["key"] == "DN-1-C" and f["instances"][-1]["key"] == f"DN-{flows.INSTANCES_MAX}-C"
    ts = lambda s: logtime.format_ts(T0 + timedelta(seconds=s))   # noqa: E731
    lines = flow_section({"flows": [f]}, {"start": ts(-1), "end": ts(1)}, ts(0), "17", {})[1]
    assert lines == [f"- 흐름 점검: 데이터 연결 반복이 많아 마지막 {flows.INSTANCES_MAX}번만 봄 — 이 범위에서는 판단 못 함"]
    lines = flow_section({"flows": [f]}, {"start": ts(1999.5), "end": ts(2010)}, ts(2000), "17", {})[1]
    assert lines[1].startswith(f"  - 데이터 연결 DN-{flows.INSTANCES_MAX}-C ") and "이상한 값" in lines[1]
    assert not any("점검하지 못함" in x for x in lines)        # 범위가 남은 인스턴스 안에만 있으면 안내 없음
    # 11/15 리뷰 D2-01: 범위가 잘린 앞쪽에 걸치거나 범위가 없으면, 남은 것의 결과 뒤에 앞 시도를 못 봤다고 알린다
    before = f"- 흐름 점검: 데이터 연결 반복이 많아 마지막 {flows.INSTANCES_MAX}번만 봄 — 그 앞 시도는 점검하지 못함"
    assert flow_section({"flows": [f]}, {"start": ts(-1), "end": ts(5)}, ts(0), "17", {})[1][-1] == before
    assert flow_section({"flows": [f]}, None, None, "17", {})[1][-1] == before
    from triagelib.report import FLOW_REPORT_MAX     # 11/15 PR 리뷰 P140-02: 안내 줄도 절 한도(1,200 B)에 센다
    g = dict(f, flow="data-setup-2", title="데이터 연결 둘째" * 6)
    both = flow_section({"flows": [f, g]}, None, None, "17", {})[1]
    assert both[-1].endswith("그 앞 시도는 점검하지 못함") and len("\n".join(both).encode("utf-8")) <= FLOW_REPORT_MAX


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
    # 숫자로 못 읽는 이슈 버전은 모름 — 다르다고 하지 않고 기준 버전만(04 §5.13 (3))
    assert flow_section(doc, None, None, "17 QPR1", {})[1] == ["- 흐름 점검: 데이터 연결 1회 끝까지 정상 (흐름 기준 버전 17)"]


def test_version_text_tokens():
    """oFono Jira 버전 칸(제품 단위 이름·모델 코드, 지어낸 이름): 조각 하나라도 원인 값에 있으면 True, 대소문자 무시."""
    vm = flows.version_match
    assert vm(["prodx", "m100"], "PRODX") is True and vm(["prodx"], "M100") is False
    assert vm(["m100"], "prodx/M100") is True and vm(["m100"], "prodx, m100") is True and vm(["m100"], "prodx m100") is True
    assert vm(["m100"], "prodx/m200") is False
    assert vm([], "prodx") is None and vm(["prodx"], "") is None and vm(["prodx"], None) is None and vm(["prodx"], " / ") is None
    assert vm(["prodx"], "16") is False and vm(["16", "prodx"], "16.1") is True   # 숫자 꼴 이슈 값은 주 버전 비교 그대로
    assert vm(["16", "17"], "Android 16") is None and vm(["2"], "prodx") is None   # 원인 값이 모두 숫자면 글자 이슈 값은 비교 안 함


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


def _empty_home(work: Path) -> dict:
    """사용자 HOME의 `~/.telephony-triage/config.yaml`(사내 PC 실제 config)이 결과에 섞이지 않게 빈 홈을 준다."""
    home = work / "home"
    home.mkdir(exist_ok=True)
    return {"HOME": home, "USERPROFILE": home, "TELEPHONY_TRIAGE_HOME": home / ".telephony-triage"}


def _triage(db: Path, out: Path, rows=RAW) -> dict:
    log = _log(out.parent / f"{out.name}.log", rows)
    meta = out.parent / f"{out.name}.meta.json"
    meta.write_text(json.dumps({"key": "MOCK-7001", "occurred_at": "2026-11-10T12:00:01+00:00", "summary": "data"}),
                    encoding="utf-8")
    return run_json("triage.py", ["run", "MOCK-7001", "--offline-db", db, "--out", out, "--logs", log, "--issue-meta", meta,
                                  "--tz", "UTC", "--year", "2026"], env={"TT_SCHEMA_CHECK": "1", **_empty_home(out.parent)})


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
    assert lines[0] == "- 흐름 점검 (참고용, 후보 순위와 점수는 그대로; 흐름 기준 버전 17):"
    assert lines[1] == "  - 데이터 연결 DN-1-C (f0:L1): 응답 받음 정상 → 설정 만듦에서 이상한 값(주소 빔)"
    assert lines[2].startswith("    → 의심되는 곳: DataNetwork(응답 → 설정 변환) / 이 단계에 등록된 원인: DATA-001-01 ")
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
    # F-12: 흐름이 있던 작업을 흐름을 뺀 스냅샷으로 다시 돌리면 이전 flow.json이 남지 않는다
    _triage(_sample_with_flow(work / "b"), work / "c")
    assert (work / "c" / "flow.json").exists()
    _triage(SAMPLE, work / "c")
    assert not (work / "c" / "flow.json").exists()


def test_cache_key_includes_flow_files(tmp_path):
    db = _sample_with_flow(tmp_path)
    config = yaml.safe_load((db / "issue-db.config.yaml").read_text(encoding="utf-8"))
    assert db / "data" / "flows" / "data-setup.yaml" in compiled.source_files(db, config)
    before = compiled.source_hash(db, config, {})
    path = db / "data" / "flows" / "data-setup.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("title: 데이터 연결", "title: 데이터 연결2"), encoding="utf-8")
    assert compiled.source_hash(db, config, {}) != before


def test_fit_trims_flows_before_other_candidate_evidence():
    """F-4: 표시 전용 보조 칸(flows)이 다른 후보 근거보다 먼저 줄어든다 — 흐름이 있어도 후보 출력은 같다."""
    item = {"flow": "data/data-setup", "key": "DN-1-C", "step": "link-properties", "verdict": "없음", "at": "f0:L100000"}

    def doc(n, with_flows):
        ev = [{"ts": "2026-11-10T12:00:00.000Z", "tag": "DN-1-C", "msg": "x" * 100} for _ in range(n)]
        out = {"status": "ok", "candidates": [{"type": "T1", "evidence": list(ev)}, {"type": "T2", "evidence": list(ev)}],
               "files": {"report": "r"}, "warnings": []}
        return {**out, "flows": [item] * 3} if with_flows else out
    for n in range(10, 20):
        assert fit(doc(n, True))["candidates"] == fit(doc(n, False))["candidates"], n
    big = [{"ts": "t", "tag": "T", "msg": "x" * 140} for _ in range(23)]
    out = fit({"status": "ok", "candidates": [{"type": "T", "evidence": list(big)}], "flows": [item] * 3,
               "files": {"report": "r"}, "warnings": []})
    assert len(out.get("flows") or []) <= 1 and len(out["candidates"][0]["evidence"]) == 23


def _bad_resp_flow():
    rows = [(0, "DN-1-C", SETUP), (0.03, "DN-1-C", RESP_BAD.replace("RESULT_SUCCESS", "RESULT_ERROR_INVALID_ARG")), TICK]
    return {"flows": _check(rows)}


def test_step_causes_put_ranked_candidates_first():
    """(추가) 이 단계의 원인: 매칭 후보(순위 순)에 있는 원인을 먼저, 그다음 DB 순서, 상한 3."""
    causes = {"data/data-setup/response": [(f"DATA-00{n}-01", f"원인 {n}") for n in range(1, 6)]}
    analysis, lines = flow_section(_bad_resp_flow(), None, None, "17", causes, ["DATA-005-01", "OTHER-001-01", "DATA-003-01"])
    assert analysis[0]["causes"] == ["DATA-005-01", "DATA-003-01", "DATA-001-01"]
    assert "이 단계에 등록된 원인: DATA-005-01 원인 5, DATA-003-01 원인 3, DATA-001-01 원인 1" in lines[2]
    assert flow_section(_bad_resp_flow(), None, None, "17", causes)[0][0]["causes"] == ["DATA-001-01", "DATA-002-01", "DATA-003-01"]


def test_analysis_causes_only_for_deviation_and_start_repeat_wording():
    """F-11: analysis.json causes는 멈춘 단계가 값이상·없음일 때만(report.md와 같다). F-17: 합친 시작 줄 수는 '같은 시작 줄이 n번 더 나옴'."""
    causes = {"data/data-setup/link-properties": [("DATA-001-01", "x")]}
    [f] = _check(_normal()[:2] + [(3.0, "Other", "tick")])          # 설정 만듦 로그끝(판정 불가)
    assert _sig(f["instances"][0]) == "ok 로그끝 - -"
    analysis, lines = flow_section({"flows": [f]}, None, None, "17", causes)
    assert "causes" not in analysis[0] and not any("이 단계에 등록된 원인" in line for line in lines)
    rows = RADIO[:2] + [(0.0015, *RADIO[0][1:])] + [(0.002, *RADIO[2][1:])] + [TICK]
    lines = flow_section({"flows": _check(rows, ("radio-on",))}, None, None, "17", {})[1]
    assert "무선 켬 SST-0 (같은 시작 줄이 1번 더 나옴) (f0:L1)" in lines[1] and "재시작" not in lines[1]


# -- 흐름 제안 줄 (§5.13 (3), PR 2) ----------------------------------------------------------------------


def _ts(sec: float) -> str:
    return logtime.format_ts(T0 + timedelta(seconds=sec))


OOS = RADIO[4][2].replace("mDataRegState=0(IN_SERVICE)", "mDataRegState=1(OUT_OF_SERVICE)")
SET_TAIL = " (1위로 확정하면 Step 7에서 사용자 확인)"
PUT_TAIL = " (Step 7에서 사용자 확인)"
DISCONNECT = "DisconnectedState: Data network disconnected. reason=AIRPLANE_MODE_ON"


def _radio_bad(extra=(), t=0.0):
    """무선 켬 SST-0이 망 등록에서 값이상(데이터 미등록)으로 멈춘 로그. 멈춘 단계 주변 창 = RIL 응답(t+0.004)~이상 줄(t+0.5)."""
    rows = [(r[0] + t, *r[1:]) for r in RADIO[:4]] + [(t + 0.5, "SST-0", OOS, PHONE, 0), *extra]
    return rows


def _top(cause="NETWORK-001-01", category="network", ts=(0.3,), unjudged=False):
    return {"cause": cause, "category": category, "unjudged": unjudged, "ts": [_ts(t) for t in ts]}


def _lines(rows, names=("radio-on",), version="17", causes=None, top=None, log_end=10.0):
    return flow_section({"flows": _check(rows, names)}, None, None, version, causes or {}, (), top, log_end)[1]


def _hint(*args, **kw) -> list[str]:
    return [line.strip() for line in _lines(*args, **kw) if "(흐름):" in line]


def test_flow_hint_set_flow_step_needs_top_evidence_near_stopped_step():
    rows = _radio_bad([TICK])
    [line] = _hint(rows, top=_top())
    assert line == ("규칙 제안 (흐름): [이슈 DB] set-flow-step NETWORK-001-01 network/radio-on/registered — 1위 원인의 근거가 "
                    "이 단계가 멈춘 시각에 있고, 이 원인에 걸어 둔 단계가 없다" + SET_TAIL)
    lines = _lines(rows, top=_top())
    assert lines.index("    " + line) == lines.index(next(x for x in lines if "→ 의심되는 곳" in x)) + 1, "근거 인스턴스 블록 바로 뒤"
    # 이미 단계가 걸린 원인, 다른 카테고리 1위, 후보 없음이면 없다
    assert _hint(rows, causes={"network/radio-on/decide": [("NETWORK-001-01", "x")]}, top=_top()) == []
    assert _hint(rows, top=_top(cause="DATA-001-01", category="data")) == [] and _hint(rows) == []
    # F-1: 창은 인스턴스 수명이 아니라 멈춘 단계 주변(앞 단계 RIL 응답 ~ 마지막 이상 줄)이다
    assert _hint(rows, top=_top(ts=(0.001,))) == [] and _hint(rows, top=_top(ts=(0.9, 20.0))) == []


def test_flow_hint_missing_step_window_is_wait_time_not_instance_life():
    """F-1(리뷰어 재현과 같은 모양): 연결 단계 `없음`이고 1분 뒤 다른 원인(비행기 모드)으로 끊긴 인스턴스에 그 원인을 걸지 않는다.
    창 = 앞 단계(설정 만듦) 시각 ~ + log_end_sec(그 전에 끝 줄이 오면 끝 줄). 뒤 단계(망 검증) 줄은 없다 — 있으면 멈춘 단계가
    아니라 제안을 내지 않는다(리뷰 1127 6번, 아래 `..._when_later_step_progressed`)."""
    rows = _normal()[:3] + [(60.0, "DN-1-C", DISCONNECT), (70.0, "Other", "tick")]
    late, early = _top("DATA-002-01", "data", ts=(59.9, 60.0)), _top("DATA-002-01", "data", ts=(5.0,))
    for version in ("17", None):
        assert _hint(rows, ("data-setup",), version, top=late) == [], version
    assert [x.split(" — ")[0] for x in _hint(rows, ("data-setup",), "17", top=early)] == [
        "규칙 제안 (흐름): [이슈 DB] set-flow-step DATA-002-01 data/data-setup/connected"]
    assert _hint(rows, ("data-setup",), "17", top=early, log_end=3.0) == [], "DB flows.log_end_sec를 따른다"
    ended = _normal()[:3] + [(2.0, "DN-1-C", DISCONNECT), (30.0, "Other", "tick")]
    assert _hint(ended, ("data-setup",), "17", top=early) == [], "끝 줄 뒤 근거는 밖"


def test_flow_hint_new_cause_step_unless_top_cause_unjudged():
    rows = _radio_bad([TICK])
    [line] = _hint(rows, top=_top(cause=None))
    assert line == ("새 원인 초안 참고 (흐름): network/radio-on/registered — 1위 증상의 근거가 이 단계가 멈춘 시각에 있다 "
                    "(이 유형에 새 원인을 만들면 그 원인에 이 단계를 적는다)")
    assert "규칙 제안" not in line and "flow_step" not in line, "질문 항목이 아니고 내부 칸 이름을 쓰지 않는다(W-2, F-13)"
    assert _hint(rows, top=_top(cause=None, unjudged=True)) == [], "1위 유형의 원인 판정 불가면 원인을 만들지 않는다(V-2)"
    assert _hint(rows, top=_top(cause=None, category="data")) == []


def test_flow_hint_put_flow_only_when_later_step_line_appeared():
    """F-2: 버전이 다르고 단계 줄이 없어도, 그 뒤 단계 줄이 나왔을 때만 문구 다름 후보다. 실제로 멈춘 고장(모뎀 무응답)은 뒤 단계 줄이
    없어 put-flow 줄을 내지 않고, 1위 원인 근거가 창 안이면 원인-단계 줄을 낸다."""
    worded = _normal()[:3] + [_normal()[4], TICK]                    # 연결 줄만 다른 문구 → 없음, 망 검증 줄은 나옴
    [inst] = _check(worded)[0]["instances"]
    assert _sig(inst) == "ok ok 없음 -" and inst["later_step"] == "validated" and inst["steps"][1]["ts"] == _ts(0.032)
    [line] = _hint(worded, ("data-setup",), "16")
    assert line == ("규칙 제안 (흐름): [이슈 DB] put-flow data/data-setup — 근거: 이 이슈는 16, 흐름은 17 기준이고, 연결 줄 없이 "
                    "다음 망 검증 줄이 나와 문구가 바뀌었을 수 있다" + PUT_TAIL)
    for version in ("17", None, "Android 16"):                       # 버전이 같거나 모르면 없다
        assert _hint(worded, ("data-setup",), version) == [], version
    # 뒤 단계가 진행된 없음: "찾지 못함 — 뒤 단계 진행됨"으로 쓰고 의심되는 곳을 붙이지 않는다(제안 줄은 그대로)
    lines = _lines(worded, ("data-setup",), "16")
    assert "연결 줄을 로그에서 찾지 못함 — 뒤 단계(망 검증)는 진행됨" in lines[1] and "줄이 로그에 없음" not in lines[1]
    assert not any("의심되는 곳" in x for x in lines) and lines[2].strip() == line
    assert _check(_normal()[:3] + [TICK])[0]["instances"][0]["later_step"] is None
    assert _hint(_normal()[:3] + [TICK], ("data-setup",), "16") == [], "뒤 단계 줄이 없으면 실제로 멈춘 것일 수 있다"
    silent = RADIO[:3] + [TICK]                                      # RIL 응답 없음(모뎀 무응답)
    assert _sig(_check(silent, ("radio-on",))[0]["instances"][0]).startswith("ok ok 없음")
    assert _hint(silent, version="16") == []
    assert [x.split(" — ")[0] for x in _hint(silent, version="16", top=_top("NETWORK-002-01", ts=(1.0,)))] == [
        "규칙 제안 (흐름): [이슈 DB] set-flow-step NETWORK-002-01 network/radio-on/ril-response"]
    assert not any("put-flow" in x for x in _hint(_radio_bad([TICK]), version="16")), "값이상은 문구 다름이 아니다"
    # 확인 리뷰 C-1: RIL 응답 없음 + 뒤 단계(망 등록) 줄이 이상 값(서비스 없음)으로만 나옴 → 흐름이 나아간 증거가 아니다
    no_svc = RADIO[:3] + [(0.5, "SST-0", OOS, PHONE, 0), TICK]
    assert _check(no_svc, ("radio-on",))[0]["instances"][0]["later_step"] is None
    assert not any("put-flow" in x for x in _hint(no_svc, version="16"))
    # V-3: 같은 로그(범위 밖 포함)에 그 단계를 정상으로 지난 인스턴스가 있으면 문구는 맞다
    both = _check(worded[:-1] + _normal(tag="DN-2-C", t=40.0) + [(80.0, "Other", "tick")])
    assert [_sig(i) for i in both[0]["instances"]] == ["ok ok 없음 -", "ok ok ok ok"]
    assert [x for x in flow_section({"flows": both}, {"start": _ts(-1), "end": _ts(1)}, _ts(0), "16", {})[1] if "(흐름):" in x] == []


def test_flow_hint_no_stopped_step_suggestion_when_later_step_progressed():
    """리뷰 1127 6번: `없음`인데 뒤 단계가 진행된 인스턴스(줄을 찾지 못했을 뿐 멈춘 단계가 아님)에는 1위 근거가 창 안이어도
    "이 단계가 멈춘 시각" 제안(set-flow-step·새 원인 초안)을 내지 않는다 — 버전이 다르면 문구 다름 후보(put-flow)로 넘어간다."""
    worded = _normal()[:3] + [_normal()[4], TICK]
    for top in (_top("DATA-001-01", "data", ts=(0.05,)), _top(None, "data", ts=(0.05,))):
        assert _hint(worded, ("data-setup",), "17", top=top) == [], top
        assert [x.split(" — ")[0] for x in _hint(worded, ("data-setup",), "16", top=top)] == [
            "규칙 제안 (흐름): [이슈 DB] put-flow data/data-setup"], top


def test_flow_hint_looks_at_every_deviating_instance_and_moves_that_block_first():
    """F-3: 첫 블록(데이터 연결 t=0 연결 없음)이 아니라 1위 근거가 맞는 무선 켬(t=5 망 등록 값이상)에 줄을 붙이고, 그 블록을 맨 앞으로."""
    rows = _normal()[:3] + _radio_bad(t=5.0) + [(40.0, "Other", "tick")]
    plain = _lines(rows, ("radio-on", "data-setup"))
    assert plain[1].startswith("  - 데이터 연결 DN-1-C"), "제안이 없으면 analysis.json과 같은 순서"
    lines = _lines(rows, ("radio-on", "data-setup"), top=_top(ts=(5.3,)))
    assert lines[1].startswith("  - 무선 켬 SST-0") and lines[3].strip().startswith("규칙 제안 (흐름): [이슈 DB] set-flow-step")
    assert any(x.startswith("  - 데이터 연결 DN-1-C") for x in lines[4:])


def test_flow_hint_dual_sim_other_key_does_not_cut_window():
    """F-4: SST-0·SST-1이 5ms 차이로 무선 켬을 시작해도 SST-0의 창은 SST-1 시작에서 끊기지 않는다."""
    sim1 = [(t + 0.005, tag.replace("-0", "-1"), msg.replace("[PHONE0]", "[PHONE1]"), pid, 1)
            for t, tag, msg, pid, _ in RADIO[:5]]
    rows = sorted(_radio_bad(t=0.0) + sim1, key=lambda r: r[0]) + [TICK]
    insts = _check(rows, ("radio-on",))[0]["instances"]
    assert sorted(i["key"] for i in insts) == ["SST-0", "SST-1"]
    [line] = _hint(rows, top=_top(ts=(0.3,)))
    assert line.startswith("규칙 제안 (흐름): [이슈 DB] set-flow-step NETWORK-001-01 network/radio-on/registered — ")


def test_flow_hint_long_titles_keep_confirm_tail_and_section_cap():
    """F-6: 긴 단계 제목·버전 목록·원인 ID에도 줄 ≤ 260 B이고 끝의 확인 조건 글이 남는다. 절 전체 ≤ 1,200 B."""
    long_title = "아주 긴 단계 제목" * 4
    worded = _check(_normal()[:3] + [_normal()[4], TICK])
    worded[0]["platform_versions"] = ["15", "17", "18"]
    worded[0]["steps"][2]["title"] = worded[0]["steps"][3]["title"] = long_title
    [put] = [x.strip() for x in flow_section({"flows": worded}, None, None, "16.0.1", {})[1]
             if "(흐름):" in x]
    assert len(put.encode("utf-8")) <= 260 and put.endswith(PUT_TAIL)
    radio = _check(_radio_bad([TICK]), ("radio-on",))
    radio[0]["steps"][3]["title"] = long_title
    for top in (_top(cause="NETWORKLONGPREFIX-123-45"), _top(cause=None)):
        [line] = [x.strip() for x in flow_section({"flows": radio}, None, None, "17", {}, (), top)[1] if "(흐름):" in x]
        assert len(line.encode("utf-8")) <= 260 and line.endswith(")"), line
        assert line.endswith(SET_TAIL) or line.endswith("그 원인에 이 단계를 적는다)")
    data = _check([r for k in range(3) for r in _normal(tag=f"DN-{k + 1}-C", t=k * 0.01)] + [TICK])[0]
    lines = flow_section({"flows": [data, radio[0]]}, None, None, "17", {}, (), _top())[1]
    assert lines[1].startswith("  - 무선 켬 SST-0") and "(흐름):" in lines[3] and len("\n".join(lines).encode("utf-8")) <= 1200


# -- eval 81~83 시나리오 오프라인 확인 (API eval 전, 검증 W-8) ----------------------------------------------

EVALS = REPO / "tests" / "skill_evals"
EVAL_HINTS = {81: ("새 원인 초안 참고 (흐름): network/radio-on/registered", None),
              82: ("규칙 제안 (흐름): [이슈 DB] set-flow-step NETWORK-001-01 network/radio-on/registered", "NETWORK-001-01"),
              83: ("규칙 제안 (흐름): [이슈 DB] put-flow data/data-setup", "DATA-002-01")}


def _eval_run(eid: int, work: Path) -> tuple[Path, Path, dict, str]:
    """eval setup과 같은 DB(샘플 + setup `flows` 시드 흐름)·시나리오 로그·모의 Jira로 triage를 오프라인으로 돌린다."""
    import skill_eval_env
    setup = next(e for e in json.loads((EVALS / "evals.json").read_text(encoding="utf-8"))["evals"] if e["id"] == eid)["setup"]
    db = work / "db"
    shutil.copytree(SAMPLE, db)
    skill_eval_env.put_seed_flows(db, setup["flows"])
    [log] = [f for f in skill_eval_env._gen(EVALS / "scenarios" / setup["logs"][0]["scenario"], work / "gen") if f.suffix == ".log"]
    [key] = setup["jira"]
    analysis = run_json("triage.py", ["run", key, "--offline-db", db, "--out", work / "out", "--logs", log, "--issue-file",
                                      EVALS / "jira" / f"{key}.yaml", "--tz", "Asia/Seoul", "--year", "2026"],
                        env={"TT_SCHEMA_CHECK": "1", **_empty_home(work)})
    return db, log, analysis, (work / "out" / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("eid", sorted(EVAL_HINTS))
def test_eval_flow_scenarios_give_expected_hint_offline(eid):
    work = tmp("tt-flows-eval-")
    db, _, analysis, report = _eval_run(eid, work)
    line, top = EVAL_HINTS[eid]
    hints = [x.strip() for x in report.splitlines() if "(흐름):" in x]
    assert len(hints) == 1 and hints[0].startswith(line + " — "), hints
    # 제안 줄은 must_show(꼭 보일 줄)에만 실리고 analysis.json의 다른 칸은 그대로다. Jira 본문에는 가지 않는다
    must = [m for m in analysis.get("must_show") or [] if "(흐름):" in m]
    rest = {k: v for k, v in analysis.items() if k != "must_show"}
    assert analysis["candidates"][0]["cause"] == top and must == [hints[0]] and "(흐름):" not in json.dumps(rest, ensure_ascii=False)
    lint = run_json("db_lint.py", ["--db", db, "--all"], expect=(0, 1))
    assert not [i for i in lint["errors"] + lint["warnings"] if "flow" in i["code"]], "setup flows DB는 흐름 lint 0(W-9)"


def test_eval83_expected_put_flow_passes_r4_and_grader_width_check():
    """eval 83의 기대 풀이(연결 단계에 새 문구 하나·버전 16, 그 인스턴스를 cut한 정상 fixture)가 초안 검증 R4를 통과하고,
    채점기 넓이 검사가 그 풀이는 통과·`.*`처럼 넓은 문구는 실패로 본다."""
    import copy

    sys.path.insert(0, str(EVALS))
    import grade
    from workspace import Workspace
    work = tmp("tt-flows-eval-")
    db, log, analysis, _ = _eval_run(83, work)
    # F-1 리뷰어 재현: 같은 로그를 이슈 버전 17·미상으로 보면 1위 DATA-002-01(비행기 모드, 연결 1분 뒤)을 연결 단계에 걸지 않는다
    doc = json.loads((work / "out" / "flow.json").read_text(encoding="utf-8"))
    c = analysis["candidates"][0]
    top = {"cause": c["cause"], "category": c["category"], "unjudged": False, "ts": [e["ts"] for e in c["evidence"]]}
    for version in ("17", None):
        assert not [x for x in flow_section(doc, None, None, version, {}, (), top)[1] if "(흐름):" in x], version
    flow = copy.deepcopy(grade.seed_flow("data/data-setup"))
    next(s for s in flow["steps"] if s["id"] == "connected")["patterns"].append("ConnectedState: Data network connected,")
    flow["platform_versions"].append("16")
    assert all(v == "ok" for v in grade.flow_verdicts(flow, grade.E83_GOOD)[0])
    assert grade.flow_verdicts(flow, grade.E83_BROKEN)[0][2] == "없음"
    for broad in ("State: .*", "ConnectedState:", "ConnectedState: .*"):     # F-9: 상태 이름만 쓴 문구도 넓다
        wide = copy.deepcopy(flow)
        next(s for s in wide["steps"] if s["id"] == "connected")["patterns"].append(broad)
        assert all(v == "ok" for v in grade.flow_verdicts(wide, grade.E83_BROKEN)[0]), broad
    start = json.loads((work / "out" / "flow.json").read_text(encoding="utf-8"))["flows"][0]["instances"][0]["start_ts"]
    ws = Workspace(src=db)
    job = "MOCK-9083"
    ws.acquire(job)
    cut = ws.job_dir(job) / "fixtures" / "flow-1.log"
    run_json("parse_logcat.py", ["cut", log, "--around", start, "--out", cut, "--rules", db / "parser-rules", "--tz", "Asia/Seoul",
                                 "--year", "2026"])
    assert "Data network connected, transport=WWAN" in cut.read_text(encoding="utf-8")
    plan = {"source": "analyze", "schema_version": 1, "started_at": "2026-11-15T10:00+09:00", "issue": None, "feedback": None,
            "included_pending": [], "commit_message": "[flow] data/data-setup", "pr": {"number": None, "branch": "issue/MOCK-9083", "head_sha": None},
            "operations": [{"op": "put-flow", "ref": "data/data-setup", "flow": flow, "fixtures": [{"path": "fixtures/flow-1.log"}]}]}
    plan_path = ws.plan(job, plan, match=None, draft_verified=False)
    rows = {r["id"]: r for r in ws.json("db_verify.py", ["rules", "--plan", plan_path, "--draft", ws.job_dir(job) / "draft"],
                                        expect=(0, 3))["rules"]}
    assert rows["R4"]["status"] == "pass" and rows["R4"]["reason"].endswith("흐름 fixture 2개 끝까지 ok"), rows["R4"]
