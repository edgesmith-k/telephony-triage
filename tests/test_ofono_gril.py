"""oFono 내장 짝 규칙 `gril`(upstream RIL trace, 17-platforms §9-3). **합성·placeholder** 줄만 쓴다(`dut`·`daemon-a`).

- 모양: `RIL_REQUEST_`·`RIL_` 접두사 유무, `failed` 변형, 이름 없는 실패(UNKNOWN), unsol, `<INVALID>`, 다른 tag,
  슬롯 없는 Android RILJ 줄
- 짝: Android `ril.pair`와 같은 의미 — 슬롯(phone_id)별 serial, pid 재시작, 응답 먼저 무시, `observed_until`
- 슬롯 규칙(`PhoneIdRules`): `[<slot>,` 줄 앞(DBG 앞머리 뒤 포함)·`/ril_<n>`
- `parse_logcat parse --mask`(issue-db-ofono): 파생 `ril_error`·`ril_timeout`·`ril_no_response`, 이름은 마스킹 불변,
  serial은 같은 줄 가린 값(IP·번호·셀)과 숫자가 겹쳐도 그대로
- 설정: `protocols.gril.tags` 덮어쓰기·`[]`로 끄기·`kind` 거부, site `kind: regex` 짝 규칙과 함께
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(SCRIPTS))

from runner import plugin_root, run, variant_db  # noqa: E402

import platforms  # noqa: E402
from common import events  # noqa: E402
from platforms import PlatformConfigError  # noqa: E402
from platforms.ofono import gril  # noqa: E402

LOG = REPO / "tests" / "fixtures" / "logs" / "ofono" / "syslog-busybox.log"
ON = {"name": "android", "enabled": ["android", "ofono"]}
TAGS = frozenset(gril.TAGS)
IPC = {"kind": "regex", "tags": ["daemon-a"], "request": r"^ipc call (?P<serial>\d+) (?P<name>[A-Z_]+)$",
       "response": r"^ipc reply (?P<serial>\d+)(?: error=(?P<error>\S+))?$"}


def _ann(msg: str, tag: str = "ofonod"):
    return gril.annotate(tag, msg, TAGS, None)


# -- 줄 모양 ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("msg,want", [
    ("[0,0001]> RIL_REQUEST_SETUP_DATA_CALL placeholder", (1, "req", "SETUP_DATA_CALL", None)),
    ("[0,0001]> SETUP_DATA_CALL", (1, "req", "SETUP_DATA_CALL", None)),                       # 접두사 없음
    ("[1,4294967295]>PLACEHOLDER_VENDOR_REQUEST", (4294967295, "req", "PLACEHOLDER_VENDOR_REQUEST", None)),
    ("[0,0002]< RIL_REQUEST_SETUP_DATA_CALL placeholder", (2, "resp", "SETUP_DATA_CALL", "NONE")),
    ("[0,0002]< RIL_REQUEST_SETUP_DATA_CALL", (2, "resp", "SETUP_DATA_CALL", "NONE")),
    ("[0,0002]< RIL_REQUEST_SETUP_DATA_CALL failed GENERIC_FAILURE", (2, "resp", "SETUP_DATA_CALL", "GENERIC_FAILURE")),
    ("[0,0002]< RIL_REQUEST_SETUP_DATA_CALL failed: RADIO_NOT_AVAILABLE", (2, "resp", "SETUP_DATA_CALL", "RADIO_NOT_AVAILABLE")),
    ("[0,0002]< SETUP_DATA_CALL failed; error: RIL_E_GENERIC_FAILURE", (2, "resp", "SETUP_DATA_CALL", "GENERIC_FAILURE")),
    ("[0,0002]< SETUP_DATA_CALL failed RIL_E_PLACEHOLDER x=1", (2, "resp", "SETUP_DATA_CALL", "PLACEHOLDER")),
    ("[0,0002]< SETUP_DATA_CALL failed", (2, "resp", "SETUP_DATA_CALL", "UNKNOWN")),            # 이름 없는 실패
    ("[0,0002]< SETUP_DATA_CALL failed Generic text", (2, "resp", "SETUP_DATA_CALL", "UNKNOWN")),
    ("[0,0002]< SETUP_DATA_CALL failedfoo", (2, "resp", "SETUP_DATA_CALL", "NONE")),            # `failed` 낱말이 아님
    ("[0,UNSOL]< RIL_UNSOL_DATA_CALL_LIST_CHANGED placeholder", (None, "unsol", "UNSOL_DATA_CALL_LIST_CHANGED", None)),
    ("[0,UNSOL]< UNSOL_PLACEHOLDER", (None, "unsol", "UNSOL_PLACEHOLDER", None)),
])
def test_annotate_shapes(msg, want):
    ann = _ann(msg)
    assert (ann["serial"], ann["dir"], ann["request"], ann["error"]) == want
    assert list(ann) == list(events.RIL_KEYS) and ann["paired_ts"] is None and ann["latency_ms"] is None


@pytest.mark.parametrize("msg", [
    "[0,0001]> <INVALID>",                                  # 식별자 모양이 아닌 이름
    "[0,0001]> setup_data_call",
    "[0001]> SETUP_DATA_CALL",                              # 슬롯 없는 옛 형식(P2)
    "[0041]> SETUP_DATA_CALL",                              # Android RILJ 줄 모양
    "[UNSL]< UNSOL_DATA_CALL_LIST_CHANGED",
    "[0,abcd]> SETUP_DATA_CALL",
    "x [0,0001]> SETUP_DATA_CALL",
    "src/example.c:example_cb() placeholder",
])
def test_annotate_ignores_other_lines(msg):
    assert _ann(msg) is None


def test_annotate_only_configured_tags():
    assert _ann("[0,0001]> SETUP_DATA_CALL", tag="daemon-a") is None
    assert gril.annotate("daemon-a", "[0,0001]> SETUP_DATA_CALL", frozenset({"daemon-a"}))["request"] == "SETUP_DATA_CALL"


# -- 슬롯 규칙 -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("msg,want", [
    ("[1,0001]> SETUP_DATA_CALL", 1),
    ("[0,UNSOL]< UNSOL_PLACEHOLDER", 0),
    ("src/example.c:example_cb() [1,0005]< SETUP_DATA_CALL", 1),     # 같은 trace가 DBG 앞머리로 찍힌 줄
    ("src/example.c:example_cb() /ril_1 online", 1),
    ("p:/ril_0 placeholder", 0),
    ("/dev/x/ril_0 placeholder", None),                              # 경로 안의 이름은 슬롯이 아니다
    ("/ril_0x placeholder", None),
    ("[1,0001] SETUP_DATA_CALL", None),
    ("placeholder", None),
])
def test_phone_id_rules(msg, want):
    assert platforms.get("ofono").phone.phone_id("ofonod", msg) == want


# -- 짝 -------------------------------------------------------------------------------------------------


def _rec(sec: float, msg: str, pid: int = 812, tag: str = "ofonod") -> dict:
    dt = datetime(2026, 9, 20, tzinfo=timezone.utc) + timedelta(seconds=sec)
    ann = gril.annotate(tag, msg, TAGS)
    if ann:
        ann["proto"] = gril.NAME                                     # 백엔드가 다는 것과 같다
    return {"ts": dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "_dt": dt, "pid": pid, "tag": tag, "ril": ann,
            "phone_id": platforms.get("ofono").phone.phone_id(tag, msg)}


def test_pair_slots_restart_order_and_observed_until():
    records = [
        _rec(0.0, "[0,0001]> SETUP_DATA_CALL"),
        _rec(0.1, "[1,0001]> SETUP_DATA_CALL"),                      # 다른 슬롯·같은 serial
        _rec(0.2, "[1,0001]< SETUP_DATA_CALL"),
        _rec(0.5, "[0,0001]< SETUP_DATA_CALL failed GENERIC_FAILURE"),
        _rec(0.6, "[0,0009]< DIAL"),                                 # 응답 먼저(요청 없음) — 무시
        _rec(0.7, "[0,0009]> DIAL"),
        _rec(0.8, "[0,0003]> DEACTIVATE_DATA_CALL"),
        _rec(0.9, "[0,0004]> SETUP_DATA_CALL"),
        _rec(1.0, "[0,0004]< DEACTIVATE_DATA_CALL"),                 # 이름이 다르면 짝 아님
        _rec(2.0, "placeholder", pid=901, tag="daemon-a"),          # 다른 데몬 줄은 관측 끝을 늘리지 않는다
        _rec(3.0, "[0,0003]< DEACTIVATE_DATA_CALL", pid=999),        # ofonod 재시작: 다른 구간
        _rec(4.0, "[0,0005]> SETUP_DATA_CALL", pid=999),
        _rec(4.5, "[0,UNSOL]< UNSOL_PLACEHOLDER", pid=999),
        _rec(5.0, "[0,0001]> SETUP_DATA_CALL", tag="daemon-a"),     # 주석 없는 줄(tag 밖)
    ]
    other = {"serial": 1, "dir": "req", "request": "SETUP_DATA_CALL", "error": None, "paired_ts": None,
             "latency_ms": None, "proto": "ipc"}
    records.append({**_rec(5.5, "x"), "ril": other})                # 다른 프로토콜 주석: 분할·짝에 쓰지 않는다
    gril.pair(records)
    a = [r["ril"] for r in records]
    assert (a[0]["latency_ms"], a[3]["latency_ms"], a[3]["error"]) == (500, 500, "GENERIC_FAILURE")
    assert (a[1]["latency_ms"], a[2]["latency_ms"], a[2]["paired_ts"]) == (100, 100, records[1]["ts"])
    assert a[4]["paired_ts"] is None and "observed_until" not in a[4]
    assert a[5]["paired_ts"] is None and a[5]["observed_until"] == records[8]["ts"]     # 같은 pid 구간 마지막 줄
    assert a[6]["paired_ts"] is None and a[6]["observed_until"] == records[8]["ts"]     # 재시작 너머 응답과 짝짓지 않는다
    assert a[7]["paired_ts"] is None and a[8]["paired_ts"] is None
    assert a[10]["paired_ts"] is None and "observed_until" not in a[10]
    assert a[11]["observed_until"] == records[12]["ts"] and "observed_until" not in a[12]    # 새 구간의 pid 999 마지막 줄
    assert a[13] is None and other["paired_ts"] is None and "observed_until" not in other
    assert list(a[5])[-2:] == ["proto", "observed_until"]


def test_pair_same_name_most_recent_and_negative_latency():
    records = [_rec(0.0, "[0,0001]> SETUP_DATA_CALL"), _rec(1.0, "[0,0001]> SETUP_DATA_CALL"),
               _rec(1.5, "[0,0001]< SETUP_DATA_CALL")]
    gril.pair(records)
    assert records[1]["ril"]["latency_ms"] == 500 and records[0]["ril"]["paired_ts"] is None   # 가장 최근 요청과
    late = [_rec(2.0, "[0,0002]> DIAL"), _rec(1.0, "[0,0002]< DIAL")]                          # 지연 < 0은 짝 아님
    gril.pair(late)
    assert late[1]["ril"]["paired_ts"] is None


# -- 백엔드·parse_logcat ---------------------------------------------------------------------------------


def _load(**ofono):
    return platforms.load({"platform": {**ON, "others": {"ofono": ofono}}}, "ofono")


def _backend(**ofono):
    from platforms.ofono.backend import BACKEND

    return BACKEND.configure(_load(**ofono))


def _anns(out) -> list:
    return [(e["ril"]["dir"], e["ril"]["serial"], e["ril"]["request"], e["ril"]["latency_ms"]) for e in out if e["ril"]]


def test_backend_default_pairs_fixture():
    out = _backend().parse([LOG], "UTC", 2026, None)
    assert _anns(out) == [("req", 1, "SETUP_DATA_CALL", 300), ("resp", 1, "SETUP_DATA_CALL", 300),
                          ("req", 2, "SETUP_DATA_CALL", 31000), ("resp", 2, "SETUP_DATA_CALL", 31000),
                          ("unsol", None, "UNSOL_DATA_CALL_LIST_CHANGED", None),
                          ("req", 3, "PLACEHOLDER_VENDOR_REQUEST", 200), ("resp", 3, "PLACEHOLDER_VENDOR_REQUEST", 200),
                          ("req", 4, "DEACTIVATE_DATA_CALL", None)]
    assert all(e["ril"]["proto"] == "gril" for e in out if e["ril"])
    assert {e["phone_id"] for e in out if e["tag"] == "ofonod"} == {0} and {e["phone_id"] for e in out if e["tag"] != "ofonod"} == {None}
    assert next(e for e in out if e["ril"] and e["ril"]["serial"] == 4)["ril"]["observed_until"] == "2026-09-20T14:50:50.000Z"
    assert events.validate_events(out) == []


def test_dbg_prefixed_response_pairs(tmp_path):
    """같은 trace가 DBG 앞머리(`x.c:func() `)로 찍힌 응답도 본문으로 주석을 달고 슬롯을 뽑아 짝짓는다."""
    log = tmp_path / "dbg.log"
    log.write_text("Sep 20 14:50:00.000 dut daemon.debug ofonod[812]: [0,0007]> RIL_REQUEST_DIAL placeholder\n"
                   "Sep 20 14:50:00.250 dut daemon.debug ofonod[812]: src/example.c:example_cb() [0,0007]< RIL_REQUEST_DIAL\n",
                   encoding="utf-8")
    out = _backend().parse([log], "UTC", 2026, None)
    assert _anns(out) == [("req", 7, "DIAL", 250), ("resp", 7, "DIAL", 250)] and [e["phone_id"] for e in out] == [0, 0]


def test_tags_override_and_off():
    out = _backend(protocols={"gril": {"tags": ["daemon-a"]}}).parse([LOG], "UTC", 2026, None)
    assert _anns(out) == []                                          # ofonod 줄은 이제 보지 않는다
    assert _load(protocols={"gril": {"tags": []}}).protocol_tags == (("gril", frozenset()),)
    assert all(e["ril"] is None for e in _backend(protocols={"gril": {"tags": []}}).parse([LOG], "UTC", 2026, None))
    with pytest.raises(PlatformConfigError, match="platform.others.ofono.protocols.gril.kind: 알 수 없는 키"):
        _load(protocols={"gril": {"kind": "regex", "tags": ["ofonod"]}})


def test_with_site_regex_protocol(tmp_path):
    log = tmp_path / "mixed.log"
    log.write_text(LOG.read_text(encoding="utf-8")
                   + "Sep 20 14:50:51.000 dut user.info daemon-a[901]: ipc call 1 PLACEHOLDER_CALL\n"
                   + "Sep 20 14:50:51.100 dut user.info daemon-a[901]: ipc reply 1\n", encoding="utf-8")
    prof = _load(protocols={"ipc": IPC})
    assert [p.name for p in prof.protocols] == ["gril", "ipc"]
    out = _backend(protocols={"ipc": IPC}).parse([log], "UTC", 2026, None)
    by = {}
    for e in out:
        if e["ril"]:
            by.setdefault(e["ril"]["proto"], []).append((e["ril"]["dir"], e["ril"]["serial"], e["ril"]["latency_ms"]))
    assert by["ipc"] == [("req", 1, 100), ("resp", 1, 100)] and len(by["gril"]) == 8
    assert events.validate_events(out) == []


def test_parse_logcat_mask_derived_events():
    root = plugin_root("ofono-on", platform=ON)
    proc = run("parse_logcat.py", ["parse", LOG, "--rules", variant_db("issue-db-ofono") / "parser-rules", "--full", "--mask",
                                   "--tz", "UTC", "--year", "2026"], root=root)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["backend"] == {"name": "ofono_reference", "version": "0.0.5"} and out["errors"] == []
    assert events.validate_events(out["events"]) == []
    derived = [(e["event"], e["fields"]) for e in out["events"] if e["source"] == "rules"]
    assert derived == [
        ("ril_error", {"request": "SETUP_DATA_CALL", "serial": "1", "error": "GENERIC_FAILURE"}),
        ("ril_timeout", {"request": "SETUP_DATA_CALL", "serial": "2", "latency_ms": "31000", "timeout_ms": "30000"}),
        ("ril_no_response", {"request": "DEACTIVATE_DATA_CALL", "serial": "4", "timeout_ms": "10000"}),
    ]
    names = {e["ril"]["request"] for e in out["events"] if e["ril"]}
    assert names == {"SETUP_DATA_CALL", "UNSOL_DATA_CALL_LIST_CHANGED", "PLACEHOLDER_VENDOR_REQUEST", "DEACTIVATE_DATA_CALL"}
    lines = [e for e in out["events"] if e["event"] is None]
    assert [e["msg"] for e in lines] == [ln.split(": ", 1)[1] for ln in LOG.read_text(encoding="utf-8").splitlines()
                                         if not ln.startswith("tail: ")]                  # 마스킹해도 바뀌지 않는다
    req = next(e for e in lines if e["ril"] and e["ril"]["serial"] == 2 and e["ril"]["dir"] == "req")
    assert req["category_hint"] == "data" and req["level"] == "D"


def test_mask_does_not_turn_success_into_error(tmp_path):
    """리뷰 P1(11/02): `--mask`가 `proto` 주석 값을 번호 표로 다시 가리면, 앞 줄에서 가린 같은 글자(`password=NONE`)와
    우연히 같은 성공 응답 `NONE`이 토큰이 되어 가짜 `ril_error`가 났다. 마스킹 여부와 무관하게 파생 이벤트가 같아야 한다."""
    log = tmp_path / "m.log"
    log.write_text(
        "Sep 20 14:50:00.000 dut daemon.info ofonod[812]: src/example.c:apn_cb() context auth password=NONE\n"
        "Sep 20 14:50:00.100 dut daemon.debug ofonod[812]: [0,0001]> RIL_REQUEST_SETUP_DATA_CALL placeholder\n"
        "Sep 20 14:50:00.400 dut daemon.debug ofonod[812]: [0,0001]< RIL_REQUEST_SETUP_DATA_CALL placeholder\n",
        encoding="utf-8")
    root = plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    outs = {}
    for mask in (False, True):
        args = ["parse", log, "--rules", variant_db("issue-db-ofono") / "parser-rules", "--full", "--tz", "UTC",
                "--year", "2026", *(["--mask"] if mask else [])]
        proc = run("parse_logcat.py", args, root=root)
        assert proc.returncode == 0, proc.stderr
        out = json.loads(proc.stdout)
        outs[mask] = [(e["event"], e["fields"]) for e in out["events"] if e["source"] == "rules"]
        resp = [e["ril"]["error"] for e in out["events"] if e.get("ril") and e["ril"].get("dir") == "resp"]
        assert resp == ["NONE"]
    assert outs[False] == outs[True]
    assert not [ev for ev, _ in outs[True] if ev == "ril_error"]


@pytest.mark.parametrize("line,value", [
    ("ipc reply 1 token=abcdef123456", "abcdef123456"),
    ("ipc reply 1 password=Hunter2pass", "Hunter2pass"),
    ("ipc reply 1 guti=ABCDEF0123456789", "ABCDEF0123456789"),
    ("ipc reply 1 RES=ABCDEF0123456789.x", "ABCDEF0123456789.x"),     # 가린 값보다 길게 뽑은 값(재리뷰, 이전부터 있던 틈)
])
def test_mask_proto_value_from_same_line_stays_masked(line, value):
    """재리뷰 P0(11/02): site 정규식이 **같은 줄**에서 키 문맥으로 가린 값을 짝 주석(`error`)으로 뽑으면 그 값도 가린다
    (텍스트 규칙만 쓰면 키 문맥이 없어 원문이 남는다). 앞 줄과 우연히 같은 값은 위 테스트처럼 토큰이 되지 않는다."""
    import parse_logcat
    from common import masking
    m = masking.new_masker()
    rec = {"msg": line, "fields": {}, "ril": {"proto": "ipc", "dir": "resp", "serial": 1, "request": "CALL",
                                              "error": value}}
    out = parse_logcat._mask_record(rec, m)
    assert value not in out["msg"] and value not in str(out["ril"])
    secret = value.split(".")[0]
    assert secret not in str(out["ril"]) and out["ril"]["error"].startswith("<")
    assert out["ril"]["error"].split(">")[0] + ">" in out["msg"]
    assert out["ril"]["request"] == "CALL"


def test_mask_proto_value_keeps_names_and_tokens_intact():
    """재리뷰 P1(11/02): 같은 줄의 짧은 값(`lac=2`)이 이름(`PDP2_ACTIVATE`)이나 앞서 넣은 토큰 안에서 다시 바뀌지 않는다."""
    import parse_logcat
    from common import masking
    rec = {"msg": "ipc call 1 PDP2_ACTIVATE lac=2", "fields": {},
           "ril": {"proto": "ipc", "dir": "req", "serial": 1, "request": "PDP2_ACTIVATE", "error": None}}
    out = parse_logcat._mask_record(rec, masking.new_masker())
    assert out["ril"]["request"] == "PDP2_ACTIVATE" and "lac=<CELL#1>" in out["msg"]
    rec = {"msg": "ipc call 1 SLOT_2_ACTIVATE lac=2", "fields": {},
           "ril": {"proto": "ipc", "dir": "req", "serial": 1, "request": "SLOT_2_ACTIVATE", "error": None}}
    assert parse_logcat._mask_record(rec, masking.new_masker())["ril"]["request"] == "SLOT_2_ACTIVATE"
    rec = {"msg": "ipc reply 1 RES=ABCDEF0123456789.x lac=1", "fields": {},
           "ril": {"proto": "ipc", "dir": "resp", "serial": 1, "request": "CALL", "error": "ABCDEF0123456789.x"}}
    out = parse_logcat._mask_record(rec, masking.new_masker())
    assert out["ril"]["error"] == "<CRED#1>.x" and "ABCDEF0123456789" not in str(out)


@pytest.mark.parametrize("msg,serial,direction", [
    ("[0,0001]> RIL_REQUEST_SETUP_DATA_CALL 10.0.1.1 01012345671", 1, "req"),
    ("[1,0012]< RIL_REQUEST_DIAL addr=10.0.12.1 number=01012345612", 12, "resp"),
    ("src/example.c:trace() [0,0005]< RIL_REQUEST_SETUP_DATA_CALL lac=5", 5, "resp"),
])
def test_mask_keeps_gril_serial_beside_masked_values(msg, serial, direction):
    """재리뷰 P1(11/02) 오탐 가드: `--mask`의 serial 대조(같은 줄에 보이는가)는 gril serial(`[<slot>,<serial>]`)이 같은 줄
    가린 값(IP·번호·셀)에 숫자 조각으로 들어 있어도 버리지 않는다 — 숫자 조각 대조였다면 기본 설정 출력이 바뀐다."""
    import parse_logcat
    from common import masking
    ann = {**gril._ann(serial, direction, "SETUP_DATA_CALL", "NONE" if direction == "resp" else None), "proto": "gril"}
    out = parse_logcat._mask_record({"msg": msg, "fields": {}, "ril": ann}, masking.new_masker())
    assert "<" in out["msg"] and out["ril"]["serial"] == serial
