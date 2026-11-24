#!/usr/bin/env python3
"""벤더 IPC 메시지 줄 레코드 (11/16 설계 §1, `common/ipcseq.py`·`parse_logcat.py ipc`·설정 `platform.vendor_ipc.trace`).

합성 `VIPC_` 꼴만 쓴다(실제 벤더 형식 아님). `pytest tests/test_ipcseq.py`.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import platforms  # noqa: E402
from common import ipcseq, masking, vendor_ipc  # noqa: E402
from runner import SAMPLE, plugin_root, run, run_json, tmp  # noqa: E402

LOG = REPO / "tests" / "fixtures" / "logs" / "ipc-fail.log"
RULES = SAMPLE / "parser-rules"
TZ = ["--tz", "Asia/Seoul", "--year", "2026"]


def _recs(msg: str, spec=vendor_ipc.DEFAULT) -> list[dict]:
    out = []
    for p in ipcseq.patterns(spec):
        m = re.search(p, msg)
        if m:
            out.append(ipcseq.record(m, 0, "t"))
            break
    return out


def test_default_patterns_read_dir_name_token_result():
    (r,) = _recs("[TX] VIPC_SETUP_DATA, REQ, token=0x0de, len=24")
    assert (r["dir"], r["name"], r["token"], r["result"]) == ("req", "VIPC_SETUP_DATA", 0x0DE, None)
    (r,) = _recs("[RX] VIPC_SETUP_DATA, RSP, token=222, len=8, Error(VIPC_E_DEMO_FAILURE)")
    assert (r["dir"], r["token"], r["result"]) == ("rsp", 222, "VIPC_E_DEMO_FAILURE")
    (r,) = _recs("[RX] VIPC_SIGNAL_INFO, IND, len=16")
    assert (r["dir"], r["token"]) == ("ind", None)
    (r,) = _recs("VIPC_DEACT_DATA (token=0x0df) requested")      # 둘째 꼴: 방향 없음
    assert (r["dir"], r["name"], r["token"]) == (None, "VIPC_DEACT_DATA", 0x0DF)
    assert _recs("vendor service heartbeat") == []


def test_default_patterns_token_and_result_notation_widened():
    """단계 3: token 구분 `=`·`:`·`(`, `token` 대소문자 무시, 결과는 괄호 앞 낱말을 가리지 않는다(괄호 안이 오류 접두어일 때만)."""
    for line in ("[TX] VIPC_SETUP_DATA, REQ, Token(0x2FE), len=24", "[TX] VIPC_SETUP_DATA, REQ, TOKEN: 766",
                 "[TX] VIPC_SETUP_DATA, REQ, token=0x02FE", "[TX] VIPC_SETUP_DATA, REQ, TOKEN=0x2fe"):
        (r,) = _recs(line)
        assert (r["name"], r["token"]) == ("VIPC_SETUP_DATA", 0x2FE), line
    for line in ("VIPC_DEACT_DATA (Token(0x2FE))", "VIPC_DEACT_DATA (TOKEN: 766)", "VIPC_DEACT_DATA (token=0x2fe)"):
        (r,) = _recs(line)
        assert (r["name"], r["token"]) == ("VIPC_DEACT_DATA", 0x2FE), line
    fail = _recs("[RX] VIPC_SETUP_DATA, RSP, token=0x2fe, Fail(VIPC_E_DEMO_FAILURE)")[0]
    error = _recs("[RX] VIPC_SETUP_DATA, RSP, token=0x2fe, Error(VIPC_E_DEMO_FAILURE)")[0]
    assert fail["result"] == error["result"] == "VIPC_E_DEMO_FAILURE"
    (r,) = _recs("[RX] VIPC_SETUP_DATA, RSP, token=0x2fe, Slot(1)")          # 오류 접두어가 아닌 괄호는 결과가 아니다
    assert (r["token"], r["result"]) == (0x2FE, None)
    (r,) = _recs("[RX] VIPC_SETUP_DATA, RSP, Slot(1), token=0x2fe, Fail(VIPC_E_OK)")
    assert (r["token"], r["result"]) == (0x2FE, "VIPC_E_OK")
    assert _recs("[TX] vipc_SETUP_DATA, REQ, token=1") == [] and _recs("vipc_X (token=1)") == []   # 이름은 대소문자를 가린다


def test_result_prefers_error_word_like_detect():
    """한 줄에 `<낱말>(<오류 접두어>…)`가 여럿이면 `Error(…)`가 먼저 — `vendor_ipc.detect`(Error 기준)와 같은 값."""
    line = "[RX] VIPC_SETUP_DATA, RSP, token=1, Prev(VIPC_E_OLD), Error(VIPC_E_OK)"
    assert _recs(line)[0]["result"] == "VIPC_E_OK"
    assert vendor_ipc.detect(line) == []                                     # detect도 성공으로 본다
    assert _recs("[RX] VIPC_A, RSP, Error(VIPC_E_X), Fail(VIPC_E_Y)")[0]["result"] == "VIPC_E_X"
    assert _recs("[RX] VIPC_A, RSP, Prev(VIPC_E_X), Fail(VIPC_E_Y)")[0]["result"] == "VIPC_E_X"   # Error 없으면 첫 것


def test_default_patterns_stay_linear_on_long_lines():
    """뒤쪽 `Error(` 확인을 낱말마다 돌리면 `Error(` 없는 긴 줄에서 줄 길이의 제곱 시간(4KB 200줄 ≈ 10초) — 시간 상한에 걸려
    기본 식이 통째로 건너뛰어진다. 느슨한 상한 1초(선형이면 수십 ms)."""
    body = " ".join(f"word{i}=val{i}" for i in range(400))[:4096]
    lines = [f"[TX] VIPC_SETUP_DATA, REQ, token=0x0de, {body}"] * 200
    rxs = [re.compile(p) for p in ipcseq.patterns()]
    start = time.perf_counter()
    for line in lines:
        assert any(rx.search(line) for rx in rxs)
    assert time.perf_counter() - start < 1.0


def test_long_token_masked_to_cred_keeps_record_without_token():
    """9자리 이상 16진 token은 마스커가 `<CRED#n>`으로 바꾸며 `)`까지 먹는다 — 줄은 놓치지 않고 token만 None(P2 27)."""
    masked = masking.new_masker(log_lines=True).mask("VIPC_X (token=0x1234abcd9)")
    assert masked.startswith("VIPC_X (token=<CRED#1>") and ")" not in masked.split("token=")[1]
    (r,) = _recs(masked)
    assert (r["name"], r["token"]) == ("VIPC_X", None)


def test_long_raw_token_is_not_cut_short():
    """마스킹을 끈 로그의 긴 token은 앞 자리만 잘라 틀린 값으로 남기지 않는다 — 끝까지 읽고 16진 8자리·10진 10자리를 넘으면 None."""
    (r,) = _recs("[TX] VIPC_SETUP_DATA, REQ, token=12345678901, len=24")       # 10진 11자리
    assert (r["name"], r["token"]) == ("VIPC_SETUP_DATA", None)
    (r,) = _recs("VIPC_X (token=0x123456789) requested")                        # 16진 9자리
    assert (r["name"], r["token"]) == ("VIPC_X", None)
    assert _recs("[TX] VIPC_A, REQ, token=4294967295")[0]["token"] == 4294967295  # 10자리는 그대로
    assert _recs("VIPC_X (token=0xdeadbeef)")[0]["token"] == 0xDEADBEEF


def test_short_tokens_survive_masking():
    """짧은 token(10진 10자리·16진 8자리 이하)은 마스커가 두므로 값이 남는다(설계 §1 마지막 줄)."""
    m = masking.new_masker(log_lines=True)
    for line, token in (("[TX] VIPC_A, REQ, token=0x0de", 0x0DE), ("VIPC_A (token=0x0de)", 0x0DE),
                        ("[TX] VIPC_A, REQ, token = 0x0DE", 0x0DE), ("[TX] VIPC_A, REQ, token=222", 222),
                        ("[TX] VIPC_A, REQ, Token(0x2FE)", 0x2FE), ("VIPC_A (TOKEN: 766)", 766)):
        assert m.mask(line) == line and _recs(line)[0]["token"] == token


def test_prefix_placeholder_uses_site_prefix_escaped():
    spec = vendor_ipc.Spec(request_prefix="AB", error_prefix="AB_E_", success="AB_E_OK")
    (r,) = _recs("[TX] AB_SETUP, REQ, token=0x1", spec)
    assert r["name"] == "AB_SETUP"
    assert _recs("[TX] VIPC_SETUP, REQ", spec) == []
    assert ipcseq.fill(r"x{prefix}y{1,8}", vendor_ipc.Spec(request_prefix="A.B")) == r"xA\.By{1,8}"
    site = vendor_ipc.Spec(trace=(r"<(?P<name>{prefix}\w+)>",))
    assert _recs("<VIPC_PING>", site)[0]["name"] == "VIPC_PING"
    assert _recs("[TX] VIPC_SETUP, REQ", site) == []          # trace를 쓰면 기본 둘은 쓰지 않는다


@pytest.mark.parametrize("trace, problem", [
    ([], "비어 있으면"), ("x", "목록"), (["("], "정규식 오류"), (["(?P<x>a)"], "name"), ([r"(?P<name>a)(?P<foo>b)"], "foo"),
    (["a" * 401], "400자"), ([r"(?P<name>a)"] * 9, "8개"),
])
def test_config_trace_key_is_checked(trace, problem):
    with pytest.raises(platforms.PlatformConfigError, match=problem):
        platforms._vendor_ipc({"trace": trace}, "platform.vendor_ipc")


def test_config_trace_is_optional_sixth_key():
    assert platforms._vendor_ipc(None, "b") == vendor_ipc.DEFAULT
    spec = platforms._vendor_ipc({"trace": [r"(?P<name>{prefix}\w+)"]}, "b")       # trace만: 다섯 키 규칙과 무관
    assert spec.trace == (r"(?P<name>{prefix}\w+)",) and spec.request_prefix == "VIPC_"
    with pytest.raises(platforms.PlatformConfigError, match="함께 적어야"):           # 다섯 키 규칙은 그대로
        platforms._vendor_ipc({"context": "X_", "trace": [r"(?P<name>a)"]}, "b")
    assert vendor_ipc.KEYS == ("context", "complete", "request_prefix", "error_prefix", "success")


def test_parse_logcat_ipc_records_on_fixture():
    out = run_json("parse_logcat.py", ["ipc", LOG, "--rules", RULES, *TZ])
    recs = out["records"]
    assert out["total"] == len(recs) == 7 and out["truncated"] is False
    assert [(r["dir"], r["name"], r["token"], r["result"]) for r in recs] == [
        ("req", "VIPC_RADIO_POWER", 1, None), ("rsp", "VIPC_RADIO_POWER", 1, "VIPC_E_OK"),
        ("ind", "VIPC_SIGNAL_INFO", None, None), ("req", "VIPC_SETUP_DATA", 222, None),
        ("rsp", "VIPC_SETUP_DATA", 222, "VIPC_E_DEMO_FAILURE"), (None, "VIPC_DEACT_DATA", 0x0DF, None),
        (None, "VIPC_DEACT_DATA", None, None)]                   # `<CRED#1>`(가린 긴 token)은 None
    assert recs[0]["ts"] == "2026-09-20T05:32:00.000Z" and recs[0]["line_ref"] == {"file_index": 0, "line_no": 1}
    assert out["coverage"]["first_ts"] == "2026-09-20T05:32:00.000Z"


def test_parse_logcat_ipc_range_from_line_records_without_second_parse(monkeypatch):
    """`ipc`는 범위(처음·끝 시각)를 이미 읽은 줄 레코드에서 정한다 — `backend.coverage`로 로그 전체를 다시 파싱하지 않는다."""
    import parse_logcat
    from parser_backends import base

    monkeypatch.setattr(base.ParserBackend, "coverage", lambda *a, **k: pytest.fail("coverage로 다시 파싱했다"))
    defaults = yaml.safe_load((plugin_root() / "site-defaults.yaml").read_text(encoding="utf-8"))
    out = parse_logcat.run_ipc(SimpleNamespace(logs=[str(LOG)], rules=str(RULES), tz="Asia/Seoul", year=2026, find=None),
                               defaults)
    assert out["coverage"] == {"first_ts": "2026-09-20T05:32:00.000Z", "last_ts": "2026-09-20T05:32:06.000Z"}
    assert out["total"] == 7


def test_parse_logcat_ipc_uses_site_trace_and_tags_only():
    """사이트 정규식(`platform.vendor_ipc.trace`)으로 바꾸고, 벤더 IPC 태그(RIL)가 아닌 줄은 보지 않는다."""
    root = plugin_root("ipc-trace", platform={"name": "android", "vendor_ipc": {"trace": [r"\b(?P<name>{prefix}DEACT_\w+)"]}})
    out = run_json("parse_logcat.py", ["ipc", LOG, "--rules", RULES, *TZ], root=root)
    assert [r["name"] for r in out["records"]] == ["VIPC_DEACT_DATA", "VIPC_DEACT_DATA"]
    assert all(r["dir"] is None and r["token"] is None for r in out["records"])


# -- IPC 줄 SIM 슬롯 (단계 3, 설정 `platform.vendor_ipc.slot`) -----------------------------------------------

DUAL = REPO / "tests" / "fixtures" / "accuracy" / "dual-sim.log"     # 같은 token 0x0de가 `ipc[0]`·`ipc[1]` 두 슬롯에 나온다
SLOT_RULE = [r"^ipc\[(\d)\]"]
LOOK = {"look_at": "VIPC_SETUP_DATA (token=0x0de)", "ref": None}


@pytest.mark.parametrize("slot, problem", [
    ([], "비어 있으면"), ("x", "목록"), (["("], "정규식 오류"), (["ipc"], "그룹 1"), (["a" * 401], "400자"),
    ([r"(\d)"] * 9, "8개"), ([r"^{prefix}\w+\[(\d)\]"], "자리표시"), ([r"{error_prefix}(\d)"], "자리표시"),
])
def test_config_slot_key_is_checked(slot, problem):
    with pytest.raises(platforms.PlatformConfigError, match=problem):
        platforms._vendor_ipc({"slot": slot}, "platform.vendor_ipc")


def test_config_slot_is_optional_and_separate_from_five_keys():
    spec = platforms._vendor_ipc({"slot": SLOT_RULE}, "b")
    assert spec.slot == tuple(SLOT_RULE) and spec.trace == () and spec.request_prefix == "VIPC_"
    assert vendor_ipc.DEFAULT.slot == ()


def test_slot_value_decimal_only():
    rx = re.compile(r"ipc\[(.)\]")
    assert ipcseq.slot_value(rx.search("ipc[1]")) == 1
    assert ipcseq.slot_value(rx.search("ipc[²]")) is None       # 위첨자 2: isdigit이지만 int()가 못 읽는다 — 멈추지 않고 None
    assert ipcseq.slot_value(rx.search("ipc[x]")) is None


def _slot_root():
    return plugin_root("ipc-slot", platform={"name": "android", "vendor_ipc": {"slot": SLOT_RULE}})


def _find(root, look: dict, expect: int = 0):
    path = tmp("tt-ipc-slot-") / "look-at.json"
    path.write_text(json.dumps(look), encoding="utf-8")
    args = ["ipc", DUAL, "--rules", RULES, *TZ, "--find", path]
    return run("parse_logcat.py", args, root=root) if expect else run_json("parse_logcat.py", args, root=root)["find"]


def test_ipc_records_take_slot_from_site_rule_else_line_record():
    plain = run_json("parse_logcat.py", ["ipc", DUAL, "--rules", RULES, *TZ])["records"]
    assert plain and all(r["phone_id"] is None for r in plain)          # RIL 태그 줄엔 슬롯 표기 없음 → 줄 레코드의 None
    recs = run_json("parse_logcat.py", ["ipc", DUAL, "--rules", RULES, *TZ], root=_slot_root())["records"]
    assert [r["phone_id"] for r in recs if r["token"] == 0x0DE] == [0, 0, 1, 1]


def test_find_slot_filters_and_counts_per_slot():
    root = _slot_root()
    both = _find(root, LOOK)                                           # 슬롯 요청 없음: 두 슬롯 모두, 고르지 않고 개수만
    assert both["hits"] == 4 and both["slots"] == {"0": 2, "1": 2}
    one = _find(root, {**LOOK, "slot": 1})
    assert one["hits"] == 2 and one["slots"] == {"1": 2}
    assert _find(None, {**LOOK, "slot": 1})["slots"] == {"null": 4}    # 슬롯 규칙 없음: 슬롯 모름은 어느 요청에도 남는다


def test_ipc_records_inherit_line_slot_and_site_slot_rule_wins():
    """줄 슬롯 규칙(`platform.log.phone_id`)이 IPC 줄에 맞으면 기록이 그 슬롯을 이어받고, `vendor_ipc.slot`도 있으면 그것이 먼저."""
    log = {"phone_id": {"msg_prefix": [r"^ipc\[(\d)\]"]}}       # 줄 규칙: `ipc[<n>]`(떼어 낸 뒤 IPC 정규식이 읽는다)
    line = plugin_root("ipc-line-slot", platform={"name": "android", "log": log})
    recs = run_json("parse_logcat.py", ["ipc", DUAL, "--rules", RULES, *TZ], root=line)["records"]
    assert [r["phone_id"] for r in recs if r["token"] == 0x0DE] == [0, 0, 1, 1]
    both = plugin_root("ipc-line-and-ipc-slot", platform={"name": "android", "log": log,
                                                          "vendor_ipc": {"slot": [r"\blen=(\d)"]}})
    recs = run_json("parse_logcat.py", ["ipc", DUAL, "--rules", RULES, *TZ], root=both)["records"]
    assert [r["phone_id"] for r in recs if r["token"] == 0x0DE] == [2, 8, 2, 8]     # `len=24`·`len=8` 첫 자리 — IPC 규칙이 먼저


def test_find_text_hits_respect_slot():
    """본문 찾기도 요청 슬롯을 따른다: 슬롯 0(`DNC-0`) 줄에만 있는 글을 slot=1로 찾으면 0건."""
    look = {"look_at": "Internet data state changed", "ref": None}
    assert _find(None, look)["hits"] == 1 and _find(None, {**look, "slot": 0})["slots"] == {"0": 1}
    assert _find(None, {**look, "slot": 1}) == {"how": None, "hits": 0, "why": "일치하는 줄 없음"}


def test_find_rejects_bad_slot_value():
    proc = _find(None, {**LOOK, "slot": "1"}, expect=2)
    assert proc.returncode == 2 and "slot" in proc.stderr


# -- 응답 없는 IPC REQ (`ipc_no_response`, 표시 전용) ----------------------------------------------------------

def _rec(i, ts, d, name="VIPC_SETUP_DATA", token=0x0DE, phone=None, f=0):
    return {"i": i, "ts": f"2026-09-20T05:33:{ts}Z", "dir": d, "name": name, "token": token, "result": None,
            "line_ref": {"file_index": f, "line_no": i + 1}, "phone_id": phone}


UNTIL = "2026-09-20T05:33:40.000Z"
PAIR = [_rec(90, "00.000", "req", name="VIPC_PING", token=1), _rec(91, "00.100", "rsp", name="VIPC_PING", token=1)]


def _nr(recs, until=UNTIL, wait=30000):
    return [r["i"] for r in ipcseq.no_response(PAIR + recs, until, wait)]


def test_no_response_pairs_by_name_token_and_slot():
    assert _nr([_rec(0, "05.000", "req"), _rec(1, "05.400", "rsp")]) == []                 # 짝 → 표시 없음
    assert _nr([_rec(0, "05.000", "req")], "2026-09-20T05:33:30.000Z") == []              # 기다림 전에 로그 끝
    assert _nr([_rec(0, "05.000", "req")]) == [0]                                          # 기다림 지나도 없음
    assert _nr([_rec(0, "05.000", "req", token=None)]) == []                               # token 없음: 짝 못 지음
    assert _nr([_rec(0, "05.000", "req", phone=0), _rec(1, "05.400", "rsp", phone=1)]) == [0]
    assert _nr([_rec(0, "05.000", "req", phone=0), _rec(1, "05.400", "rsp")]) == []         # 슬롯 모름은 같다고 본다
    assert _nr([_rec(0, "05.000", "req"), _rec(1, "05.400", "rsp", name="VIPC_OTHER")]) == [0]
    # 같은 token의 REQ 둘: RSP는 가장 이른 REQ를 닫는다(FIFO) — 뒤 REQ가 응답 없음
    assert _nr([_rec(0, "01.000", "req"), _rec(1, "05.000", "req"), _rec(2, "05.400", "rsp")]) == [1]
    assert _nr([_rec(0, "05.000", "req")], None) == []


def test_no_response_line_order_per_file_end_cap_and_format_guard():
    # 시계가 뒤로 뛰어도 줄 순서로 짝짓는다: REQ(줄 1, 05초) 뒤 RSP(줄 2, 04초)는 짝
    assert _nr([_rec(0, "05.000", "req"), _rec(1, "04.000", "rsp")]) == []
    # 파일별 관측 끝: 파일 1은 10초에 끝났으면 기다림(30초) 전이라 내지 않는다, 파일 0은 40초까지라 낸다
    ends = {0: UNTIL, 1: "2026-09-20T05:33:10.000Z"}
    assert _nr([_rec(0, "05.000", "req"), _rec(1, "05.000", "req", token=7, f=1)], ends) == [0]
    # 상한 NO_RESPONSE_MAX
    many = [_rec(k, "01.000", "req", token=100 + k) for k in range(30)]
    assert len(_nr(many)) == ipcseq.NO_RESPONSE_MAX == 20
    # 짝지어진 RSP가 하나도 없으면(형식이 안 맞음) 내지 않는다
    assert ipcseq.no_response([_rec(0, "05.000", "req"), _rec(1, "06.000", "req", token=9)], UNTIL, 30000) == []


NR_LOG = [
    "09-20 14:33:00.000   900   910 D RIL     : [TX] VIPC_RADIO_POWER, REQ, token=0x001, len=4",
    "09-20 14:33:00.050   900   910 D RIL     : [RX] VIPC_RADIO_POWER, RSP, token=0x001, len=4, Error(VIPC_E_OK)",
    "09-20 14:33:01.000   900   910 D RIL     : [TX] VIPC_SETUP_DATA, REQ, token=0x0de, len=24",
    "09-20 14:33:02.000   900   910 D RIL     : [TX] VIPC_GET_X, REQ, len=24",
    "09-20 14:33:40.000   900   910 D RIL     : vendor service heartbeat",
]


def _parse(lines, root=None) -> dict:
    log = tmp("tt-ipc-nr-") / "a.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return run_json("parse_logcat.py", ["parse", log, "--full", "--rules", RULES, *TZ, "--mask"], root=root)


def test_parse_marks_unanswered_req_on_timeline_only():
    from common import parser_rules
    from triagelib import report

    out = _parse(NR_LOG)
    assert out["ipc_no_response"] == [{"line_ref": {"file_index": 0, "line_no": 3}, "ts": "2026-09-20T05:33:01.000Z",
                                       "name": "VIPC_SETUP_DATA", "token": 0x0DE, "phone_id": None, "timeout_ms": 30000}]
    assert not any("no_response" in str(e.get("event")) for e in out["events"])          # 이벤트가 아니다(매칭·자격 검사 밖)
    assert "ipc_no_response" not in parser_rules.RESERVED_EVENTS        # 자격 검사 `_fails`·매처는 events[]만 본다
    text = report.timeline("K", out, None, 200)[0]
    assert ("05:33:01.000 - D RIL [TX] VIPC_SETUP_DATA, REQ, token=0x0de, len=24  ⇒ "
            "ipc_no_response(ipc=VIPC_SETUP_DATA,timeout_ms=30000,token=0xde)") in text
    assert "ipc_no_response" not in next(x for x in text.split("\n") if "VIPC_GET_X" in x)    # token 없는 REQ
    short = _parse(NR_LOG[:4] + ["09-20 14:33:20.000   900   910 D RIL     : vendor service heartbeat"])
    assert "ipc_no_response" not in short                                                   # 기다림 전에 로그 끝: 키 없음
    site = _parse(NR_LOG[:4] + ["09-20 14:33:20.000   900   910 D RIL     : vendor service heartbeat"],
                  root=plugin_root("ipc-wait", platform={"name": "android", "vendor_ipc": {"timeout_ms": 5000}}))
    assert [r["timeout_ms"] for r in site["ipc_no_response"]] == [5000]                    # site 기다림


@pytest.mark.parametrize("value", [0, -1, "30000", True, 1.5])
def test_config_timeout_key_is_checked(value):
    with pytest.raises(platforms.PlatformConfigError, match="timeout_ms"):
        platforms._vendor_ipc({"timeout_ms": value}, "platform.vendor_ipc")
    assert platforms._vendor_ipc({"timeout_ms": 1500}, "b").timeout_ms == 1500 and vendor_ipc.DEFAULT.timeout_ms is None


def test_no_response_mark_is_display_only_for_row_selection():
    """ipc_no_response는 `marks`가 아니라 `notes`: 넘칠 때 고르는 줄(select_rows)이 표시가 있든 없든 같고 줄 끝에만 찍힌다."""
    from triagelib import report

    filler = [f"09-20 14:33:{10 + k:02d}.000   900   910 D RIL     : vendor service heartbeat {k}" for k in range(20)]
    out = _parse(NR_LOG[:4] + filler + NR_LOG[4:])
    assert out["ipc_no_response"]
    bare = {k: v for k, v in out.items() if k != "ipc_no_response"}
    pick = [[r["msg"] for r in report.select_rows(report.merge_rows(ev), "2026-09-20T05:33:30.000Z", 4)[0]] for ev in (out, bare)]
    assert pick[0] == pick[1]
    row = next(r for r in report.merge_rows(out) if "VIPC_SETUP_DATA" in str(r["msg"]))
    assert row["marks"] == [] and row["notes"][0].startswith("ipc_no_response(")
    assert report.row_line(row).endswith("⇒ " + row["notes"][0])
