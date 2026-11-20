#!/usr/bin/env python3
"""기준 줄 찾기 순수 함수 (11/16 설계 §2, `common/lookat.py`). `pytest tests/test_lookat.py`."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import lookat as L  # noqa: E402

UTC = timezone.utc


def test_clean_strips_logcat_head_and_time_brackets_only():
    assert L.clean("09-20 14:33:05.000   900   910 D RIL     : [TX] VIPC_SETUP_DATA, REQ, token=0x0de") \
        == "[TX] VIPC_SETUP_DATA, REQ, token=0x0de"
    assert L.clean("2026-09-20 14:33:05.000 +0900 1000 1234 1244 I DNC-0: a  b") == "a b"        # 연도·zone·uid
    assert L.clean("09-20 14:33:05.000 D/RIL( 1234): [RX] x") == "[RX] x"                        # time 형식
    assert L.clean("[  12.345] [IpcCtx_0] OnIpcComplete [14:32:11.001] ok") == "[IpcCtx_0] OnIpcComplete ok"   # P2 21
    assert L.clean("  plain   text ") == "plain text" and L.clean(None) == ""


def test_query_reads_name_and_token_loosely():
    assert L.query("VIPC_X (token=0x0de)") == {"text": "VIPC_X (token=0x0de)", "name": "VIPC_X", "token": 0x0DE}
    assert L.query("VIPC_X token: 222")["token"] == 222                       # 괄호 없이·콜론(P2 22)
    assert L.query("0x0DE") == {"text": "0x0DE", "name": None, "token": 0x0DE}  # token만
    assert L.query("[TX] VIPC_A, REQ")["token"] is None
    assert L.query("AB_X token=1", prefix="AB_")["name"] == "AB_X"
    assert L.query("222") == {"text": "222", "name": None, "token": 222}       # 맨몸 10진도 token 후보
    assert L.query("12345678901")["token"] is None                             # 10자리를 넘으면 token 아님


def test_query_token_forms_are_one_value():
    """단계 3: `Token(0x2FE)`·`token (0x2fe)`·`TOKEN: 766`·`token=0x02FE`가 같은 token. 닫는 괄호는 보지 않는다."""
    for text in ("VIPC_X Token(0x2FE)", "VIPC_X token (0x2fe", "VIPC_X TOKEN: 766", "VIPC_X token=0x02FE"):
        assert L.query(text)["token"] == 0x2FE, text
    assert L.query("VIPC_X tokens(0x2FE)")["token"] is None        # 낱말 경계 — `tokens(`는 token 아님


def test_ipc_hits_name_and_token_or_token_only():
    recs = [{"name": "VIPC_A", "token": 1}, {"name": "VIPC_B", "token": 1}, {"name": "VIPC_A", "token": 2}]
    assert L.ipc_hits({"name": "VIPC_A", "token": 1}, recs) == [0]
    assert L.ipc_hits({"name": None, "token": 1}, recs) == [0, 1]
    assert L.ipc_hits({"name": "VIPC_A", "token": None}, recs) == []


def test_ipc_hits_slot_filters_but_keeps_unknown_slot():
    """요청 슬롯이 있으면 그 슬롯이거나 슬롯 모름(None)만. 없으면 두 슬롯 모두 — 고르지 않는다(모호 처리는 뒤 단계)."""
    recs = [{"name": "VIPC_A", "token": 1, "phone_id": 0}, {"name": "VIPC_A", "token": 1, "phone_id": 1},
            {"name": "VIPC_A", "token": 1, "phone_id": None}, {"name": "VIPC_A", "token": 1}]
    q = {"name": "VIPC_A", "token": 1}
    assert L.ipc_hits(q, recs) == [0, 1, 2, 3]
    assert L.ipc_hits(q, recs, slot=1) == [1, 2, 3]
    assert L.ipc_hits(q, recs, slot=0) == [0, 2, 3]
    assert L.ipc_hits(q, recs, slot=2) == [2, 3]


def test_text_match_folds_mask_numbers_and_needs_eight_chars():
    assert L.needle({"text": "short"}) is None and L.needle({"text": "12345678"}) == "12345678"
    nd = L.needle({"text": "link up ip=<IP#1> IFACE"})
    texts = ["DNC-0: link up ip=10.1.2.3 iface=x", "DNC-0: link down ip=10.1.2.3 iface=x", "X: link up ip=<IP#7> iface"]
    masked = ["DNC-0: link up ip=<IP#3> iface=x", "DNC-0: link down ip=<IP#3> iface=x", texts[2]]
    assert L.text_hits(nd, texts, lambda i: masked[i]) == [0, 2]      # 번호가 달라도(입력 #1, 로그 #3·#7) 맞다
    assert L.text_hits(nd, texts) == [2]                              # 가리지 않은 원 줄은 값이 달라 안 맞는다


def test_text_match_refuses_needle_mostly_masked():
    """마스킹 토큰 밖 조각이 4자 미만이면(값이 거의 다 가려진 줄) 아무 줄에나 붙지 않게 찾지 않는다 → None."""
    nd = L.needle({"text": "<IP#1> <CRED#2> ab <IP#3>"})
    assert nd is not None and L.text_hits(nd, ["X: <IP#5> <CRED#6> ab <IP#7>", "Y: ab"]) is None
    assert L.text_hits(L.needle({"text": "<IP#1> link <IP#2>"}), ["X: <IP#4> link <IP#5>"]) == [0]   # 4자 조각은 된다


def test_pick_nearest_or_last():
    t0 = datetime(2026, 9, 20, 5, 30, tzinfo=UTC)
    times = [t0, t0 + timedelta(minutes=3), t0 + timedelta(minutes=10)]
    assert L.pick(times[:1], None) == (0, "only")
    assert L.pick(times, t0 + timedelta(minutes=4)) == (1, "nearest")
    assert L.pick(times, t0 + timedelta(minutes=1, seconds=30)) == (0, "nearest")   # 같은 거리면 앞
    assert L.pick(times, None) == (2, "last")                                       # 기준 시각 없음 → 마지막(P2 23)


def test_level_and_tag_head_without_time_is_body_search():
    """sim1120 S-11·S-39: 시각 없이 레벨·태그 머리(`D RILJ    : …`, `9995 10049 D RILJ : …`)를 붙여도, `태그 :`처럼 `:` 앞에
    공백이 있어도 `태그: 메시지` 줄을 찾는다. 레벨만 떼고 태그는 본문으로 남긴다(`Phone-0 : …`)."""
    assert L.clean("D RILJ    : Service DATA has died. [PHONE0]") == "RILJ : Service DATA has died. [PHONE0]"
    assert L.clean("radio  9995 10049 D RILJ    : Service DATA") == "RILJ : Service DATA"
    assert L.clean("Phone-0 : setAllowedNetworkTypes: subId=1") == "Phone-0 : setAllowedNetworkTypes: subId=1"
    # 시각 머리를 뗀 줄은 남은 메시지 앞(`E radio: …`)을 레벨로 떼지 않는다(리뷰 1bb528a7)
    assert L.clean("11-21 06:42:42.000  1001  1002 D SST     : E radio: off pollState") == "E radio: off pollState"
    texts = ["RILJ: Service DATA has died. [PHONE0]", "Phone-0: setAllowedNetworkTypes: subId=1, reason=user"]
    for line, want in (("D RILJ    : Service DATA has died.", [0]), ("Phone-0 : setAllowedNetworkTypes: subId=1", [1])):
        assert L.text_hits(L.needle(L.query(line)), texts) == want, line
