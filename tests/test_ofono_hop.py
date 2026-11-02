"""oFono 설정 정의 짝 규칙 kind `hop`(17-platforms §9-3, K20). **합성·placeholder** 줄만 쓴다(`dut`·`daemon-a`·`daemon-b`).

- 설정: 키·`upstream`·`tags`·정규식(`name` 그룹)·`fold`·`window_ms` 오류(키 경로), 레지스트리 `reads` 순서 확인
- 모양: tag 필터, `(?:RIL_REQUEST_)?` 접두사 흡수, 식별자 모양 아닌 이름(`0102`·`a:b`) 무시, 키 = `RIL_KEYS`
- 짝: 창 경계, 방향(요청은 아래가 뒤·응답은 아래가 앞), 일대일 nearest(재사용 없음), 슬롯, fold, 위 주석 불변
- 백엔드·`parse_logcat`: 아래 줄에만 주석, gril 결과·파생 이벤트는 hop 유무와 무관, `--mask`에도 이름 불변
"""

from __future__ import annotations

import copy
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
from platforms.ofono import gril, hop  # noqa: E402

LOG = REPO / "tests" / "fixtures" / "logs" / "ofono" / "syslog-hop.log"
ON = {"name": "android", "enabled": ["android", "ofono"]}
HOP = {"kind": "hop", "upstream": "gril", "tags": ["daemon-a"],
       "request": r"ipc req (?:RIL_REQUEST_)?(?P<name>[A-Z][A-Z0-9_]*)",
       "response": r"ipc rsp (?P<name>[A-Za-z]\w*)", "fold": True, "window_ms": 50}
IPC = {"kind": "regex", "tags": ["daemon-b"], "request": r"^ipc call (?P<serial>\d+) (?P<name>[A-Z_]+)$",
       "response": r"^ipc reply (?P<serial>\d+)$"}


def _defaults(**ofono) -> dict:
    return {"platform": {**ON, "others": {"ofono": ofono}}}


def _load(**ofono):
    return platforms.load(_defaults(**ofono), "ofono")


def _error(**ofono) -> str:
    with pytest.raises(PlatformConfigError) as info:
        _load(**ofono)
    return str(info.value)


# -- 설정 ------------------------------------------------------------------------------------------------


def _without(key):
    return {k: v for k, v in HOP.items() if k != key}


@pytest.mark.parametrize("conf,path,why", [
    (_without("upstream"), "protocols.h", "'upstream'가 필요"),
    (_without("tags"), "protocols.h", "'tags'가 필요"),
    ({k: v for k, v in HOP.items() if k not in ("request", "response")}, "protocols.h", "하나 이상"),
    ({**HOP, "request": r"ipc req (\w+)"}, "protocols.h.request", "(?P<name>"),
    ({**HOP, "response": r"ipc rsp (?P<serial>\d+)"}, "protocols.h.response", "(?P<name>"),
    ({**HOP, "request": "ipc req ("}, "protocols.h.request", "정규식 오류"),
    ({**HOP, "window_ms": 0}, "protocols.h.window_ms", "1~1000"),
    ({**HOP, "window_ms": 1001}, "protocols.h.window_ms", "1~1000"),
    ({**HOP, "window_ms": True}, "protocols.h.window_ms", "1~1000"),
    ({**HOP, "window_ms": "50"}, "protocols.h.window_ms", "1~1000"),
    ({**HOP, "fold": "yes"}, "protocols.h.fold", "true/false"),
    ({**HOP, "serial": "x"}, "protocols.h.serial", "알 수 없는 키"),
    ({**HOP, "upstream": "h"}, "protocols.h.upstream", "자기 이름"),
    ({**HOP, "upstream": "Gril"}, "protocols.h.upstream", "^[a-z]"),
    ({**HOP, "upstream": ["gril"]}, "protocols.h.upstream", "^[a-z]"),
    ({**HOP, "tags": []}, "protocols.h.tags", "비어 있으면"),
    ({**HOP, "tags": [""]}, "protocols.h.tags[0]", "비어 있지 않은"),
])
def test_build_errors(conf, path, why):
    msg = _error(protocols={"h": conf})
    assert f"site-defaults.yaml platform.others.ofono.{path}" in msg and why in msg, msg


def test_build_defaults_and_one_side():
    prof = _load(protocols={"h": {k: v for k, v in HOP.items() if k not in ("fold", "window_ms", "response")}})
    proto = prof.protocols[-1]
    assert proto.reads == ("gril",) and proto.default_tags == frozenset({"daemon-a"})
    assert proto.pair.args == ("h", "gril", False, hop.DEFAULT_WINDOW_MS)       # fold false, 창 50
    assert proto.annotate("daemon-a", "ipc rsp SetupDataCall", frozenset({"daemon-a"})) is None   # 응답 정규식 없음
    assert _load(protocols={"h": {**HOP, "window_ms": 1000}}).protocols[-1].pair.args[-1] == 1000


def test_registry_reads_order():
    msg = _error(protocols={"h": {**HOP, "upstream": "nosuch"}})
    assert "platform.others.ofono.protocols.h: 읽는 짝 규칙 'nosuch'가 앞에 없습니다" in msg and "gril" in msg, msg
    msg = _error(protocols={"h": {**HOP, "upstream": "ipc"}, "ipc": IPC})          # 아래에 적은 regex 규칙
    assert "읽는 짝 규칙 'ipc'가 앞에 없습니다" in msg, msg
    prof = _load(protocols={"ipc": IPC, "h": {**HOP, "upstream": "ipc"}})       # 위에 적은 것은 된다
    assert [p.name for p in prof.protocols] == ["gril", "ipc", "h"] and prof.protocols[-1].reads == ("ipc",)
    prof = _load(protocols={"gril": {"tags": []}, "h": HOP})                    # 끈 gril도 목록에는 있다(연결 0, site_checks)
    assert [p.name for p in prof.protocols] == ["gril", "h"]
    assert all(p.reads == () for p in platforms.get("ofono").protocols + platforms.get("android").protocols)
    msg = _error(protocols={"h": HOP, "h2": {**HOP, "upstream": "h"}})             # 리뷰 P2: hop은 위 층이 될 수 없다
    assert "platform.others.ofono.protocols.h2: 읽는 짝 규칙 'h'는 다른 규칙을 읽는 규칙이라" in msg, msg


# -- 줄 모양 ---------------------------------------------------------------------------------------------


def _hop(**over):
    return _load(protocols={"h": {**HOP, **over}}).protocols[-1]


@pytest.mark.parametrize("msg,want", [
    ("ipc req SETUP_DATA_CALL len=8", ("hop_req", "SETUP_DATA_CALL")),
    ("ipc req RIL_REQUEST_SETUP_DATA_CALL len=8", ("hop_req", "SETUP_DATA_CALL")),     # 접두사는 정규식이 흡수
    ("ipc rsp SetupDataCall placeholder", ("hop_resp", "SetupDataCall")),
    ("x ipc req PLACEHOLDER_QUERY", ("hop_req", "PLACEHOLDER_QUERY")),               # re.search
    ("ipc req 0102 len=8", None),
    ("ipc req setup", None),
    ("placeholder", None),
])
def test_annotate_shapes(msg, want):
    proto = _hop()
    ann = proto.annotate("daemon-a", msg, proto.default_tags)
    if want is None:
        assert ann is None
        return
    assert (ann["dir"], ann["request"]) == want and list(ann) == list(events.RIL_KEYS)
    assert (ann["serial"], ann["error"], ann["paired_ts"], ann["latency_ms"]) == (None, None, None, None)


def test_annotate_filters():
    proto = _hop(request=r"ipc req (?P<name>\S+)", response=r"ipc (?:req|rsp) (?P<name>\S+)")
    assert proto.annotate("daemon-b", "ipc req PLACEHOLDER_OTHER", proto.default_tags) is None      # tags 밖
    assert proto.annotate("daemon-a", "ipc req a:b", proto.default_tags) is None                    # `:` 든 값
    assert proto.annotate("daemon-a", "ipc req 0102", proto.default_tags) is None                   # 숫자로 시작
    assert proto.annotate("daemon-a", "ipc rsp Done", proto.default_tags)["dir"] == "hop_resp"


# -- 짝 -------------------------------------------------------------------------------------------------

T0 = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)


def _rec(ms: float, tag: str, msg: str, proto=None, phone=None) -> dict:
    dt = T0 + timedelta(milliseconds=ms)
    proto = proto or _hop()
    if tag == "ofonod":
        ann = gril.annotate(tag, msg, frozenset(gril.TAGS))
        name = gril.NAME
    else:
        ann = proto.annotate(tag, msg, proto.default_tags)
        name = proto.name
    if ann:
        ann["proto"] = name                                          # 백엔드가 다는 것과 같다
    return {"ts": dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "_dt": dt, "pid": 812 if tag == "ofonod" else 901,
            "tag": tag, "ril": ann, "phone_id": phone}


def _pair(records, proto) -> list:
    gril.pair(records)
    proto.pair(records)
    return [(r["ril"]["serial"], r["ril"]["latency_ms"]) for r in records if r["ril"] and r["ril"]["proto"] == proto.name]


def test_pair_window_direction_and_reuse():
    proto = _hop()
    records = [
        _rec(0, "ofonod", "[0,0001]> RIL_REQUEST_SETUP_DATA_CALL"),
        _rec(50, "daemon-a", "ipc req SETUP_DATA_CALL"),                    # 창 경계 50ms: 연결
        _rec(1000, "ofonod", "[0,0002]> RIL_REQUEST_SETUP_DATA_CALL"),
        _rec(1051, "daemon-a", "ipc req SETUP_DATA_CALL"),                  # 51ms: 창 밖
        _rec(1999, "daemon-a", "ipc req DEACTIVATE_DATA_CALL"),             # 아래가 먼저인 요청: 연결 없음
        _rec(2000, "ofonod", "[0,0003]> RIL_REQUEST_DEACTIVATE_DATA_CALL"),
        _rec(3000, "ofonod", "[0,0004]> RIL_REQUEST_DEACTIVATE_DATA_CALL"),
        _rec(3001, "daemon-a", "ipc req DEACTIVATE_DATA_CALL"),
        _rec(3002, "daemon-a", "ipc req DEACTIVATE_DATA_CALL"),             # 위 줄은 한 번만 쓴다
        _rec(4000, "ofonod", "[0,0005]< RIL_REQUEST_DEACTIVATE_DATA_CALL"),
        _rec(3990, "daemon-a", "ipc rsp DeactivateDataCall"),               # 응답은 아래가 10ms 앞(fold)
        _rec(4005, "daemon-a", "ipc rsp DeactivateDataCall"),               # 위 응답 뒤: 연결 없음
    ]
    gril.pair(records)
    after_gril = copy.deepcopy([r["ril"] for r in records if r["tag"] == "ofonod"])
    proto.pair(records)
    assert [r["ril"] for r in records if r["tag"] == "ofonod"] == after_gril          # 위 주석은 읽기만
    got = [(r["ril"]["dir"], r["ril"]["serial"], r["ril"]["latency_ms"]) for r in records if r["tag"] == "daemon-a"]
    assert got == [("hop_req", 1, 50), ("hop_req", None, None), ("hop_req", None, None), ("hop_req", 4, 1),
                   ("hop_req", None, None), ("hop_resp", 5, 10), ("hop_resp", None, None)]
    low = [r["ril"] for r in records if r["tag"] == "daemon-a"]
    assert low[0]["paired_ts"] == records[0]["ts"] and low[5]["request"] == "DEACTIVATE_DATA_CALL"   # 위 정규 이름
    assert low[1]["request"] == "SETUP_DATA_CALL" and "observed_until" not in low[1]


def test_pair_nearest_first_and_slots():
    proto = _hop()
    records = [
        _rec(0, "ofonod", "[0,0002]> RIL_REQUEST_DEACTIVATE_DATA_CALL"),
        _rec(10, "ofonod", "[0,0003]> RIL_REQUEST_DEACTIVATE_DATA_CALL"),
        _rec(11, "daemon-a", "ipc req DEACTIVATE_DATA_CALL"),               # 차이 1ms → 3
        _rec(12, "daemon-a", "ipc req DEACTIVATE_DATA_CALL"),               # 남은 2(12ms) — FIFO와 다르다
    ]
    assert _pair(records, proto) == [(3, 1), (2, 12)]
    slots = [
        _rec(0, "ofonod", "[1,0007]> RIL_REQUEST_SETUP_DATA_CALL", phone=1),
        _rec(1, "daemon-a", "ipc req SETUP_DATA_CALL", phone=0),             # 슬롯 1 ↔ 0: 안 된다
        _rec(2, "daemon-a", "ipc req SETUP_DATA_CALL"),                      # 아래 슬롯 모름: 된다
    ]
    assert _pair(slots, proto) == [(None, None), (7, 2)]
    exact = _hop(fold=False)
    resp = [_rec(0, "ofonod", "[0,0001]> SETUP_DATA_CALL"), _rec(9, "daemon-a", "ipc rsp SetupDataCall"),
            _rec(10, "ofonod", "[0,0001]< SETUP_DATA_CALL")]
    assert _pair(resp, exact) == [(None, None)]                              # fold 없으면 다른 이름


# -- 백엔드·parse_logcat ---------------------------------------------------------------------------------


def _backend(**ofono):
    from platforms.ofono.backend import BACKEND

    return BACKEND.configure(_load(**ofono))


def test_backend_fixture():
    out = _backend(protocols={"h": HOP}).parse([LOG], "UTC", 2026, None)
    low = [(e["ts"][11:23], e["ril"]["dir"], e["ril"]["serial"], e["ril"]["request"], e["ril"]["latency_ms"])
           for e in out if e["tag"] != "ofonod" and e["ril"]]
    assert low == [("15:00:00.001", "hop_req", 1, "SETUP_DATA_CALL", 1),
                   ("15:00:00.299", "hop_resp", 1, "SETUP_DATA_CALL", 1),
                   ("15:00:01.011", "hop_req", 3, "DEACTIVATE_DATA_CALL", 1),
                   ("15:00:01.012", "hop_req", 2, "DEACTIVATE_DATA_CALL", 12),
                   ("15:00:02.051", "hop_req", None, "PLACEHOLDER_QUERY", None),
                   ("15:00:03.000", "hop_req", None, "PLACEHOLDER_OTHER", None)]
    assert all(e["ril"]["proto"] == "h" for e in out if e["tag"] != "ofonod" and e["ril"])
    assert [e["ril"] for e in out if e["tag"] == "daemon-b"] == [None]
    plain = _backend().parse([LOG], "UTC", 2026, None)
    assert [e["ril"] for e in out if e["tag"] == "ofonod"] == [e["ril"] for e in plain if e["tag"] == "ofonod"]
    assert [e for e in plain if e["tag"] != "ofonod" and e["ril"]] == []
    assert events.validate_events(out) == [] and events.validate_events(plain) == []


@pytest.mark.parametrize("mask", [False, True])
def test_parse_logcat_hop(mask):
    rules = variant_db("issue-db-ofono") / "parser-rules"
    outs = {}
    for name, ofono in (("off", {}), ("on", {"protocols": {"h": HOP}})):
        root = plugin_root(f"ofono-hop-{name}", platform={**ON, "others": {"ofono": ofono}})
        args = ["parse", LOG, "--rules", rules, "--full", "--tz", "UTC", "--year", "2026", *(["--mask"] if mask else [])]
        proc = run("parse_logcat.py", args, root=root)
        assert proc.returncode == 0, proc.stderr
        outs[name] = json.loads(proc.stdout)
    on, off = outs["on"], outs["off"]
    assert on["errors"] == [] and events.validate_events(on["events"]) == []
    derived = [(e["event"], e["fields"]) for e in on["events"] if e["source"] == "rules"]
    assert derived == [(e["event"], e["fields"]) for e in off["events"] if e["source"] == "rules"]
    assert ("ril_error", {"request": "SETUP_DATA_CALL", "serial": "1", "error": "GENERIC_FAILURE"}) in derived
    hops = [e["ril"] for e in on["events"] if e["ril"] and e["ril"].get("proto") == "h"]
    assert [a["request"] for a in hops] == ["SETUP_DATA_CALL", "SETUP_DATA_CALL", "DEACTIVATE_DATA_CALL",
                                           "DEACTIVATE_DATA_CALL", "PLACEHOLDER_QUERY", "PLACEHOLDER_OTHER"]
    for a in hops:
        assert set(a) <= set(events.RIL_KEYS + events.RIL_OPTIONAL_KEYS)
    lines = [e for e in on["events"] if e["event"] is None]
    assert [e["msg"] for e in lines] == [e["msg"] for e in off["events"] if e["event"] is None]
