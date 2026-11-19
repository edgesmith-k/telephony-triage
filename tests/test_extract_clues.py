"""시제품(설계 메모 DESIGN-AUTO-CLUE-1120 (A)): 코멘트 단서 자동 추출 규칙 — 회차 경계·ipc 짝·log_line·일부만 읽음·상한."""

from triagelib import problem as pb

LINE = "11-14 10:02:00.624  2101  2101 D DNC-0   : onDataNetworkSetupDataFailed: cause=MISSING_UNKNOWN_APN(0x1b)"


def _x(comments, desc="", **kw):
    return pb.extract_clues(comments, desc, "VIPC_", "VIPC_E_", **kw)


def test_retest_boundary_keeps_only_after_last_retest_comment():
    clues, drop = _x(["VIPC_SETUP_DATA (token=0x0de) 실패. 재시험 요청", "VIPC_SETUP_DATA (token=0x1a2) 또 실패"])
    assert [(c["comment"], c["token"]) for c in clues] == [(2, "0x1a2")] and drop["old_round"] == 1
    clues, drop = _x(["VIPC_SETUP_DATA (token=0x0de) 실패", "수정 빌드 올렸습니다. Retest 부탁"])     # 결과 없는 재시험 요청 → 없음
    assert clues == [] and drop["old_round"] == 1


def test_ipc_pairs_name_with_following_token_and_skips_error_names():
    clues, _ = _x(["VIPC_DATA_CALL_REQ (token=0x3e0) 정상, VIPC_DATA_CALL_CNF (token=0x3e1) 실패 Error(VIPC_E_X) token=0x5"])
    assert [(c["name"], c["token"]) for c in clues] == [("VIPC_DATA_CALL_REQ", "0x3e0"), ("VIPC_DATA_CALL_CNF", "0x3e1")]
    assert _x(["VIPC_SETUP_DATA 실패입니다"])[0] == []      # 이름만은 뽑지 않는다


def test_log_line_needs_logcat_stamp_and_newest_first_dedup():
    clues, _ = _x(["> " + LINE, "본문만 onDataNetworkSetupDataFailed", LINE], desc=LINE)
    assert [(c["comment"], c["kind"]) for c in clues] == [(3, "log_line")]


def test_partial_and_cap():
    assert _x(["VIPC_A (token=1)"], reported_total=2) == ([], {"partial": True, "old_round": 0, "over": 0, "invalid": 0})
    clues, drop = _x([f"VIPC_A (token={n})" for n in range(1, 13)])
    assert len(clues) == pb.CLUES_MAX and drop["over"] == 2 and clues[0]["token"] == "12"
