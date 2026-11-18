#!/usr/bin/env python3
"""벤더 IPC 메시지 줄 레코드 (11/16 설계 §1, `common/ipcseq.py`·`parse_logcat.py ipc`·설정 `platform.vendor_ipc.trace`).

합성 `VIPC_` 꼴만 쓴다(실제 벤더 형식 아님). `pytest tests/test_ipcseq.py`.
"""

from __future__ import annotations

import json
import re
import sys
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
