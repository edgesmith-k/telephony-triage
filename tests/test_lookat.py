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
        == "RIL: [TX] VIPC_SETUP_DATA, REQ, token=0x0de"          # 태그는 남긴다(코덱스 K02 — 비교 글이 `태그: 메시지`)
    assert L.clean("2026-09-20 14:33:05.000 +0900 1000 1234 1244 I DNC-0: a  b") == "DNC-0: a b"        # 연도·zone·uid
    assert L.clean("09-20 14:33:05.000 D/RIL( 1234): [RX] x") == "RIL: [RX] x"                        # time 형식
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
    assert L.clean("11-21 06:42:42.000  1001  1002 D SST     : E radio: off pollState") == "SST: E radio: off pollState"
    texts = ["RILJ: Service DATA has died. [PHONE0]", "Phone-0: setAllowedNetworkTypes: subId=1, reason=user"]
    for line, want in (("D RILJ    : Service DATA has died.", [0]), ("Phone-0 : setAllowedNetworkTypes: subId=1", [1])):
        assert L.text_hits(L.needle(L.query(line)), texts) == want, line


def test_loosely_typed_line_colonless_ellipsis_and_word_order():
    """sim1121 P0(ROOTCAUSE 4): 사람이 대충 적은 기준 줄 — 태그 뒤 `:`를 뺀 `태그 메시지`, 중간을 `...`·`…`로 줄인 글(앞뒤 조각이
    순서대로), 중간을 말없이 뺀 글(낱말이 순서대로, 낱말 경계에서 시작). 엉뚱한 줄은 안 맞는다(음성)."""
    def hits(line, texts):
        return L.text_hits(L.needle(L.query(line)), texts)
    stall = ["DNC-0: onDataStallReestablishInternet: Tear down data networks", "DNC-1: onDataStallReestablishInternet: x",
             "DSRM-0: broadcastDataStallDetected"]
    assert hits("DNC-0 onDataStallReestablishInternet", stall) == [0]
    calls = ["RILJ: [2729]< SETUP_DATA_CALL DataCallResponse: { cause=X retry=-1 cid=-1",
             "RILJ: [2730]< SETUP_DATA_CALL DataCallResponse: { cause=X retry=5000 cid=-1",
             "RILJ: [2728]> SETUP_DATA_CALL,reason=NORMAL retry=-1"]
    for line in ("2026-11-11 16:20:33.541 < SETUP_DATA_CALL ... retry=-1", "< SETUP_DATA_CALL … retry=-1"):
        assert hits(line, calls) == [0], line
    failed = ["DNC-0: onDataNetworkSetupDataFailed: [DataNetwork: DN-1], cause=RADIO_NOT_AVAILABLE(0x10001), retry=10000",
              "DNC-0: onDataNetworkSetupDataFailed: [DataNetwork: DN-2], cause=NO_SERVICE(0x1), retry=10000",
              "DNC-1: onDataNetworkSetupDataFailed: cause=RADIO_NOT_AVAILABLE(0x10001)"]
    assert hits("DNC-0 onDataNetworkSetupDataFailed cause=RADIO_NOT_AVAILABLE(0x10001)", failed) == [0]
    # 찾기 방식: 줄 그대로·콜론 없음·`...` 생략은 text, 낱말 순서로만 맞으면 words(확정으로 올리지 않는다), 끄면(코멘트 단서) 없음
    words = L.needle(L.query("DNC-0 onDataNetworkSetupDataFailed cause=RADIO_NOT_AVAILABLE(0x10001)"))
    assert L.text_find(words, failed) == ([0], "words") and L.text_find(words, failed, loose=False) == ([], "text")
    assert L.text_find(L.needle(L.query("DNC-0 onDataStallReestablishInternet")), stall) == ([0], "text")
    # 음성: 낱말이 다른 낱말 한가운데(`setup`이 `onDataNetworkSetup…`)면 안 맞고, 순서가 바뀌거나 값이 다르면 안 맞는다
    assert hits("DNC-0 setup data failed", failed) == []
    assert hits("cause=RADIO_NOT_AVAILABLE(0x10001) DNC-0 onDataNetworkSetupDataFailed", failed) == []
    assert hits("DNC-0 onDataStallReestablishInternet result=ok", stall) == []
    # 줄 그대로 맞는 곳이 있으면 낱말 순서로만 맞는 줄은 더하지 않는다
    assert hits("DNC-0 onDataStall", ["DNC-0: onDataStall x", "DNC-0: y onDataStall"]) == [0]


def test_clock_without_date_is_cut_and_kept_for_picking():
    """날짜 없는 앞 시각(`22:18:58.695 pcscf=[]`)은 떼어 본문으로 찾고 시각은 같은 곳 고르기에만(`clock`·`same_clock`)."""
    assert L.clean("22:18:58.695 pcscf=[]") == "pcscf=[]" and L.clock("22:18:58.695 pcscf=[]") == "22:18:58.695"
    assert L.clean("[22:18:58] x y z w") == "x y z w" and L.clock("[22:18:58] x") == "22:18:58"
    assert L.clean("16:50:42") == "" and L.clock("16:50:42") == "16:50:42"
    assert L.clock("11-10 22:18:58.695 radio 1 2 D DNC-0: x") is None and L.stamp("22:18:58.695 x") is None
    assert L.clean("12:03:44.123  1234  1300 D DNC-0   : msg here") == "DNC-0 : msg here"
    t = "16:50:42.480"      # 로그 줄에 찍힌 시각 글(시간대를 바꾸지 않은 그대로)
    assert L.same_clock("16:50:42", t) and L.same_clock("16:50:42.48", t) and L.same_clock("16:50:42.4800", t)
    assert not L.same_clock("16:50:42.481", t) and not L.same_clock("16:50:43", t) and not L.same_clock("16:50:42.5", t)
