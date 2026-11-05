#!/usr/bin/env python3
"""`common/modulefilter.py` (B2 §4.3·§12.4): fixture 재현율, 창·고정 줄·상한·잡음·상태·사슬, 표, 마스킹 점검,
결정성, 자식 프로세스, import 경계. 네트워크·유료 호출 없음.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import masking
from common import modulefilter as mf

FIXTURES = REPO / "tests" / "fixtures" / "module-filter"
MODULES = yaml.safe_load((REPO / "templates" / "module-skills" / "modules.yaml").read_text(encoding="utf-8"))


def _case(name: str) -> tuple[dict, dict]:
    d = FIXTURES / name
    return (yaml.safe_load((d / "expect.yaml").read_text(encoding="utf-8")),
            json.loads((d / "events.json").read_text(encoding="utf-8")))


def _cases() -> list[str]:
    return sorted(p.parent.name for p in FIXTURES.glob("*/expect.yaml"))


def _doc(expect: dict) -> dict:
    doc = copy.deepcopy(MODULES)
    over = expect.get("override") or {}
    p = doc["platforms"][expect["platform"]]
    if "ipc_re" in over:
        p["common"]["filter"]["ipc_re"] = over["ipc_re"]
    for mod, names in (over.get("ipc") or {}).items():
        p["modules"][mod]["ipc"] = names
    return doc


def _labeled(expect: dict, events: dict):
    spec = mf.compile_spec(_doc(expect), expect["platform"])
    rows = mf.rows_of(events)
    mf.label(spec, rows)
    return spec, rows


def _covered(picked) -> set:
    return set().union(*[v["row"].get("covers", v["row"]["lines"]) for v in picked]) if picked else set()


def _evidence(rows, lines) -> list[dict]:
    return [{"ts": r["ts"], "tag": r["tag"], "msg": r["msg"], "event": None} for r in rows if r["lines"] & set(lines)]


def _events(rows: list[tuple]) -> dict:
    """합성 events.json: (ts, tag, msg, level, extra dict) → 줄 레코드."""
    out = []
    for no, (ts, tag, msg, level, extra) in enumerate(rows, 1):
        rec = {"ts": ts, "pid": 1, "level": level, "tag": tag, "msg": msg, "phone_id": None, "category_hint": "common",
               "ril": None, "event": None, "fields": {}, "line_ref": {"file_index": 0, "line_no": no}}
        rec.update(extra or {})
        out.append(rec)
    return {"events": out, "mask_allow": []}


def _write_events(tmp_path: Path, events: dict) -> str:
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events), encoding="utf-8")
    return str(path)


# -- fixture 재현율 ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", _cases())
def test_deep_view_keeps_every_essential_line(name):
    expect, events = _case(name)
    spec, rows = _labeled(expect, events)
    ev = _evidence(rows, expect["essential"])
    center, window = mf.deep_window(ev, rows)
    picked, stats = mf.view(spec, rows, expect["module"], center, "deep", window=window, cap_rows=200,
                            cap_bytes=24576, pins=ev)
    missing = set(expect["essential"]) - _covered(picked)
    assert not missing, (name, sorted(missing))
    assert stats["bytes"] <= 24576 and stats["kept"] <= 200


@pytest.mark.parametrize("name", _cases())
def test_explore_view_recall(name):
    expect, events = _case(name)
    spec, rows = _labeled(expect, events)
    pins = [{"ts": r["ts"], "tag": r["tag"], "msg": r["msg"]} for r in rows if r["ts"] == expect["center"]][:5]
    picked, _ = mf.view(spec, rows, expect["module"], expect["center"], "explore", pins=pins)
    got = len(set(expect["essential"]) & _covered(picked))
    assert got >= 0.9 * len(expect["essential"]), (name, got, len(expect["essential"]))


def test_negative_fixture_rows_reach_view():
    for name in ("syn-noise-event", "syn-unmapped-ril", "syn-connman-no-such-element", "syn-qmi-ipc"):
        expect, events = _case(name)
        spec, rows = _labeled(expect, events)
        picked, _ = mf.view(spec, rows, expect["module"], expect["center"], "explore")
        assert set(expect["essential"]) <= _covered(picked), name
    expect, events = _case("syn-qmi-ipc")
    plain = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(events)
    mf.label(plain, rows)
    qmi = [r for r in rows if "QMI_" in r["msg"]]
    assert qmi and all("data" not in (r["mods"] or ()) for r in qmi)       # 기본 값으로는 data가 아니다
    spec, rows = _labeled(expect, events)
    assert all("data" in r["mods"] for r in rows if "QMI_" in r["msg"])     # ipc_re·ipc만 바꾸면 data
    expect, events = _case("syn-connman-no-such-element")
    spec, rows = _labeled(expect, events)
    assert all(r["bg"] is None for r in rows)


def test_setup_data_call_fields_masked_in_views():
    for name in _cases():
        expect, events = _case(name)
        spec, rows = _labeled(expect, events)
        picked, _ = mf.view(spec, rows, expect["module"], expect["center"], "explore")
        for v in picked:
            for m in __import__("re").finditer(r"SETUP_DATA_CALL \(([^,()]*),([^,()]*),([^,()]*),([^,()]*),([^,()]*),",
                                               v["line"]):
                for field in m.group(4, 5):
                    assert not field or masking.TOKEN_RE.fullmatch(field) or field.lower() in ("null",), (name, v["line"])


# -- 창·고정 줄·상한 ---------------------------------------------------------------------------------------------

def test_deep_window_keeps_both_ends():
    rows_in = [("2026-09-20T15:10:00.000Z", "NMD", "profile select start", "I", {"category_hint": "data"})]
    rows_in += [(f"2026-09-20T15:10:{s:02d}.000Z", "MOSE", f"tick {s}", "I", None) for s in range(1, 15)]
    rows_in += [("2026-09-20T15:10:15.000Z", "NMD", "activate result: failed", "W",
                 {"category_hint": "data", "event": None})]
    events = _events(rows_in)
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(events)
    mf.label(spec, rows)
    ev = [{"ts": rows[0]["ts"], "tag": "NMD", "msg": rows[0]["msg"], "event": None},
          {"ts": rows[-1]["ts"], "tag": "NMD", "msg": rows[-1]["msg"], "event": "x"}]
    center, (lo, hi) = mf.deep_window(ev, rows)
    assert center == "2026-09-20T15:10:15.000Z" and lo == "2026-09-20T15:09:30.000Z" and hi == "2026-09-20T15:10:20.000Z"
    picked, _ = mf.view(spec, rows, "data", center, "deep", window=(lo, hi), pins=ev)
    assert {1, 16} <= _covered(picked)


def test_deep_window_cap_60s():
    ev = [{"ts": "2026-09-20T15:00:00.000Z", "tag": "a", "msg": "x", "event": None},
          {"ts": "2026-09-20T15:02:00.000Z", "tag": "a", "msg": "y", "event": "ril_error"}]
    center, (lo, hi) = mf.deep_window(ev, [])
    assert (center, lo, hi) == ("2026-09-20T15:02:00.000Z", "2026-09-20T15:01:05.000Z", "2026-09-20T15:02:05.000Z")
    assert mf.deep_window([], []) == (None, None)


def test_pins_survive_noise_quiet_collapse_and_count_first():
    noisy = "SIT_IND_SIGNAL_STRENGTH level=3"
    rows_in = [(f"2026-09-20T15:10:{s:02d}.000Z", "NMD", f"activate result: failed {s}", "W",
                {"category_hint": "data"}) for s in range(30)]
    rows_in.append(("2026-09-20T15:10:40.000Z", "exynos-ril", noisy, "I", None))
    events = _events(rows_in)
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(events)
    mf.label(spec, rows)
    assert rows[-1]["noise"]
    pins = [{"ts": "2026-09-20T15:10:40.000Z", "tag": "exynos-ril", "msg": noisy}]
    picked, stats = mf.view(spec, rows, "data", "2026-09-20T15:10:00.000Z", "explore", cap_rows=3, pins=pins)
    assert len(picked) == 3 and noisy in picked[-1]["line"] and stats["pinned"] == 1


def test_same_ms_rows_keep_source_order_and_ip_tokens_differ():
    rows_in = [("2026-09-20T15:10:00.000Z", "NMD", "route add <IP#9> failed", "W", {"category_hint": "data"}),
               ("2026-09-20T15:10:00.000Z", "NMD", "route add <IP#10> failed", "W", {"category_hint": "data"}),
               ("2026-09-20T15:10:00.000Z", "NMD", "a first", "W", {"category_hint": "data"})]
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(_events(rows_in))
    mf.label(spec, rows)
    picked, _ = mf.view(spec, rows, "data", "2026-09-20T15:10:00.000Z", "explore")
    assert [v["row"]["msg"] for v in picked] == ["route add <IP#9> failed", "route add <IP#10> failed", "a first"]


def test_exact_repeats_collapse_with_script_note():
    rows_in = [(f"2026-09-20T15:10:00.{i:03d}Z", "NMD", "activate result: failed", "W", {"category_hint": "data"})
               for i in range(0, 500, 100)]
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(_events(rows_in))
    mf.label(spec, rows)
    picked, stats = mf.view(spec, rows, "data", "2026-09-20T15:10:00.000Z", "explore")
    assert len(picked) == 1 and "〔script: 같은 줄 ×5〕" in picked[0]["line"] and stats["collapsed"] == 4
    assert "⇒" not in picked[0]["line"]


def test_inheritance_follows_line_order():
    rows_in = [("2026-09-20T15:10:00.000Z", "ofonod", "src/gprs.c:gprs_cb() head", "I", {"pid": 7}),
               ("2026-09-20T15:10:00.002Z", "ofonod", "continuation without prefix", "I", {"pid": 7}),
               ("2026-09-20T15:10:00.010Z", "ofonod", "late continuation", "I", {"pid": 7})]
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(_events(rows_in))
    mf.label(spec, rows)
    assert rows[0]["mods"] == {"data"} and rows[1]["mods"] == {"data"} and not rows[2]["mods"]


def test_state_rows_pinned_and_never_vote():
    rows_in = [("2026-09-20T15:10:00.000Z", "ofonod", "[0,0001]> RIL_REQUEST_RADIO_POWER on", "I", None),
               ("2026-09-20T15:10:05.000Z", "NMD", "activate result: failed", "W", {"category_hint": "data"})]
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(_events(rows_in))
    mf.label(spec, rows)
    assert rows[0]["state"] is not None
    picked, _ = mf.view(spec, rows, "data", "2026-09-20T15:10:05.000Z", "explore")
    assert any("RADIO_POWER" in v["line"] for v in picked)
    items = [{"tag": "ofonod", "msg": rows[0]["msg"], "cat": "data", "ril": None}]
    assert mf.candidates(spec, items)["counts"] == {}


def test_background_family_counts_once():
    spec = mf.compile_spec(MODULES, "ofono")
    msg = "SIM_OPEN_CHANNEL failed NO_SUCH_ELEMENT"
    items = [{"tag": "LPA", "msg": msg, "cat": "sim", "ril": None}] * 4
    assert mf.candidates(spec, items)["counts"]["sim"]["lines"] == 1


def test_chain_pulls_paired_response():
    req = {"ril": {"serial": 1, "dir": "req", "request": "SETUP_DATA_CALL", "paired_ts": "2026-09-20T15:10:01.000Z"},
           "category_hint": "data"}
    rsp = {"ril": {"serial": 1, "dir": "resp", "request": "SETUP_DATA_CALL", "paired_ts": "2026-09-20T15:10:00.000Z"},
           "category_hint": "data"}
    rows_in = [("2026-09-20T15:10:00.000Z", "ofonod", "[0,0001]> RIL_REQUEST_SETUP_DATA_CALL", "D", req)]
    rows_in += [(f"2026-09-20T15:10:00.{i:03d}Z", "MOSE", f"ui tick {i}", "I", None) for i in range(100, 900, 100)]
    rows_in += [("2026-09-20T15:10:00.500Z", "exynos-ril", "RIL_SOCKET_0 REQUEST: SETUP_DATA_CALL", "I", None),
                ("2026-09-20T15:10:01.000Z", "ofonod", "[0,0001]< RIL_REQUEST_SETUP_DATA_CALL failed", "E", rsp)]
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(_events(rows_in))
    mf.label(spec, rows)
    picked, _ = mf.view(spec, rows, "data", "2026-09-20T15:10:01.000Z", "explore", cap_rows=3)
    msgs = [v["row"]["msg"] for v in picked]
    assert "[0,0001]> RIL_REQUEST_SETUP_DATA_CALL" in msgs and "RIL_SOCKET_0 REQUEST: SETUP_DATA_CALL" in msgs


# -- 표(규칙 1~3) ------------------------------------------------------------------------------------------------

def test_primary_rules():
    spec = mf.compile_spec(MODULES, "ofono")
    assert mf.primary(spec, {"tag": "NMD", "cat": "data", "ril": None}) == ("data", "tag:NMD")
    assert mf.primary(spec, {"tag": "ofonod", "cat": "sim", "ril": {"request": "SIM_IO"}}) == ("sim", "ril:SIM_IO")
    assert mf.primary(spec, {"tag": "X", "cat": "gnss", "ril": None}) == (None, "unmapped:gnss")
    assert mf.primary(spec, {"tag": "ofonod/gprs", "cat": "common", "msg": "src/gprs.c:f() x"}) == ("data", "file:src/gprs.c")
    assert mf.primary(spec, {"tag": "ofonod", "cat": "common", "msg": "drivers/rilmodem/sim.c:f() x"}) == \
        ("sim", "file:drivers/rilmodem/sim.c")
    assert mf.primary(spec, {"tag": "ofonod", "cat": "common", "msg": "src/simfs.c:f() x"}) == ("sim", "file:src/simfs.c")
    assert mf.primary(spec, {"tag": "RFSD", "cat": "common", "msg": "x"}) == ("modem", "tag:RFSD")
    assert mf.primary(spec, {"tag": "ofonod", "cat": None, "msg": "x", "ril": {"request": "RADIO_POWER"}}) == \
        ("modem", "ril:RADIO_POWER")
    out = mf.candidates(spec, [{"tag": "NMD", "cat": "data"}, {"tag": "NMD", "cat": "data"}, {"tag": "LPA", "cat": "sim"},
                               {"tag": "X", "cat": "gnss"}])
    assert out == {"counts": {"data": {"lines": 2, "why": [["tag:NMD", 2]]}, "sim": {"lines": 1, "why": [["tag:LPA", 1]]}},
                   "unmapped": {"gnss": 1}}


def test_also_signal_counts_modem_rows():
    rows_in = [("2026-09-20T15:10:00.000Z", "RFSD", "rf calibration failed", "W", None),
               ("2026-09-20T15:10:01.000Z", "NMD", "activate result: failed", "W", {"category_hint": "data"})]
    spec = mf.compile_spec(MODULES, "ofono")
    rows = mf.rows_of(_events(rows_in))
    mf.label(spec, rows)
    assert mf.also_signal(spec, rows, "2026-09-20T15:09:30.000Z", "2026-09-20T15:10:05.000Z") == \
        {"rows": 1, "why": [["tag:RFSD", 1]]}


def test_deep_evidence_from_match():
    match = {"candidates": [{"type": "A", "cause": "A-01", "evidence": [{"ts": "t1", "tag": "x", "msg": "m", "event": "e"}]},
                            {"type": "D", "cause": "D-01", "evidence": [
                                {"ts": "t1", "tag": "x", "msg": "m", "event": "e", "fields": {}},
                                {"ts": "t1", "tag": "x", "msg": "m", "event": "e2"},
                                {"ts": "t2", "tag": "y", "msg": "n", "event": None}]}]}
    assert mf.deep_evidence(match, {"type": "D", "cause": "D-01"}) == [
        {"ts": "t1", "tag": "x", "msg": "m", "event": "e"}, {"ts": "t2", "tag": "y", "msg": "n", "event": None}]
    assert mf.deep_evidence(match, {"type": "Z", "cause": "Z"}) == []


# -- build·마스킹 점검·머리말 ------------------------------------------------------------------------------------

def _view_payload(path: str, **extra) -> dict:
    payload = {"op": "view", "modules": MODULES, "platform": "ofono", "events": path, "key": "MOCK-1", "module": "data",
               "mode": "explore", "center": "2026-09-20T15:10:00.000Z", "center_source": "발생 시각", "evidence": [],
               "pins": [], "cap_rows": 150, "cap_bytes": 20480, "with_modem": False, "allow": []}
    payload.update(extra)
    return payload


def test_view_redacts_then_asserts(tmp_path, monkeypatch):
    imsi = "45005" + "1234567890"
    events = _events([("2026-09-20T15:10:00.000Z", "NMD", f"activate failed imsi={imsi}", "W", {"category_hint": "data"})])
    out = mf.build(_view_payload(_write_events(tmp_path, events)))
    assert imsi not in out["text"] and "<REDACTED:IMSI>" in out["text"] and out["stats"]["redacted"] == {"IMSI": 1}
    assert "- 가림(마스킹 점검): IMSI 1" in out["text"]
    monkeypatch.setattr(mf.masking, "redact", lambda text, allow=(): (text, {}))
    assert mf.build(_view_payload(_write_events(tmp_path, events))) == {"error": "mask", "kinds": {"IMSI": 1}}


def test_view_header_and_uncollected_names_only(tmp_path):
    events = _events([("2026-09-20T15:10:00.000Z", "NMD", "activate result: failed", "W", {"category_hint": "data"})])
    out = mf.build(_view_payload(_write_events(tmp_path, events)))
    text, stats = out["text"], out["stats"]
    assert text.startswith("# MOCK-1 모듈 타임라인 (ofono/data, 탐색)\n")
    assert "〔script: …〕는 스크립트 메모이며 근거가 아니다" in text
    data = MODULES["platforms"]["ofono"]["modules"]["data"]
    regexish = set(data.get("keywords") or []) | set(data.get("client_tags") or [])
    assert stats["uncollected"] and not set(stats["uncollected"]) & regexish
    assert all(mf.NAME_RX.fullmatch(n) for n in stats["uncollected"])
    assert set(stats) >= {"kept", "pool", "noise", "collapsed", "weak", "uncollected", "hot_modules", "center",
                          "center_source", "window", "pinned", "redacted", "bytes"}


def test_view_weak_signal_and_other_module_section(tmp_path):
    events = _events([("2026-09-20T15:10:00.000Z", "LPA", "profile download failed", "E", {"category_hint": "sim"}),
                      ("2026-09-20T15:10:01.000Z", "NMD", "profile select", "I", {"category_hint": "data"})])
    out = mf.build(_view_payload(_write_events(tmp_path, events)))
    assert out["stats"]["weak"] and "- 모듈 신호 약함:" in out["text"] and "## 다른 모듈 줄 (±15초, 경고·오류)" in out["text"]


def test_build_candidates_and_also(tmp_path):
    res = mf.build({"op": "candidates", "modules": MODULES, "platform": "ofono",
                    "items": [{"tag": "NMD", "msg": "x", "cat": "data", "ril": None, "level": "W", "marks": []}]})
    assert res["counts"]["data"]["lines"] == 1
    events = _events([("2026-09-20T15:10:00.000Z", "RFSD", "rf failed", "W", None)])
    path = _write_events(tmp_path, events)
    ev = [{"ts": "2026-09-20T15:10:00.000Z", "tag": "RFSD", "msg": "rf failed", "event": None}]
    assert mf.build({"op": "also", "modules": MODULES, "platform": "ofono", "events": path, "evidence": ev,
                     "module": "data"})["rows"] == 1
    assert mf.compile_spec(MODULES, "nope") is None


def test_child_timeout_and_crash():
    assert mf.child({"op": "view"}, timeout=0.001) == {"error": "timeout"}
    out = mf.child({"op": "nope"})
    assert out["error"] == "crash" and isinstance(out.get("detail"), str)


def test_view_bytes_deterministic_across_hash_seeds(tmp_path):
    expect, _ = _case("e1-euicc-poll")
    payload = _view_payload(str(FIXTURES / "e1-euicc-poll" / "events.json"), module="sim", center=expect["center"])
    (tmp_path / "p.json").write_text(json.dumps(payload), encoding="utf-8")
    code = ("import json,sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2]);"
            "from triagelib import report; import test_modulefilter as t;"
            "from common import modulefilter as mf;"
            "print(mf.build(json.load(open(sys.argv[3])))['text'])")
    outs = []
    for seed in ("1", "2"):
        proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS), str(REPO / "tests"), str(tmp_path / "p.json")],
                              capture_output=True, text=True, env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"})
        assert proc.returncode == 0, proc.stderr[-400:]
        outs.append(proc.stdout)
    assert outs[0] == outs[1] and outs[0].startswith("# MOCK-1 모듈 타임라인 (ofono/sim, 탐색)")


def test_run_and_explore_never_import_modulefilter():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import triage, triagelib.driver, triagelib.report;"
            "print('common.modulefilter' in sys.modules)")
    proc = subprocess.run([sys.executable, "-c", code, str(SCRIPTS)], capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.strip() == "False", proc.stderr[-400:]
