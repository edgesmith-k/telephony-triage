#!/usr/bin/env python3
"""Jira 코멘트 단서 자동 추출(모델 없이, `problem.extract_clues`)과 `triage.py run`의 단서 출처 고르기.

- 추출 규칙: 회차 경계(재시험 낱말), ipc 짝, log_line(시각 있는 줄, 300자 넘으면 앞 300자), 이름만 안 뽑음, 최근부터·중복 하나·상한,
  10진·16진 token 같은 값, 코멘트 번호 오프셋.
- `jira_fields.extract`: 코멘트 일부만 읽음(`comments_partial`)·오래된 것만 빠짐(`comments_skipped`)·사내 경로가 없을 때 기본 경로.
- run(오프라인 `--issue-file`, 시드 DB, `tests/fixtures/accuracy/tokpos.log` — 10:01 0x0dd 성공, 10:02 0x0e1 실패 → DATA-003-01):
  새 problem.json > 자동 추출, `--look-at`이면 자동 추출 안 씀, 시각이 다른 log_line은 버림(두 출처 모두), 합성 티켓(설계 메모 M4)
  은 채택 쪽으로 틀리지 않는다. 규칙 동작 확인이다(정확도 수치 아님 — 사내 코멘트 모양은 모른다).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import jira_fields  # noqa: E402
import make_accuracy_fixtures as maf  # noqa: E402
from runner import plugin_root, run_json, tmp  # noqa: E402
from triagelib import problem as pb  # noqa: E402

LINE = "11-14 10:02:00.624  2101  2101 D DNC-0   : onDataNetworkSetupDataFailed: [DataNetwork: DN-120-C, <APN#1>, state=null], " \
       "cause=MISSING_UNKNOWN_APN(0x1b), retryDelayMillis=-1ms."


def _x(comments, desc="", **kw):
    return pb.extract_clues(comments, desc, "VIPC_", "VIPC_E_", **kw)


def _keys(clues):
    return [(c["comment"], c["kind"], c["token"]) for c in clues]


# -- 추출 규칙 ------------------------------------------------------------------------------------------------

def test_retest_boundary_keeps_only_after_last_retest_comment():
    clues, drop = _x(["VIPC_SETUP_DATA (token=0x0de) 실패. 재시험 요청", "Re-Test 결과 VIPC_SETUP_DATA (token=0x1a2) 또 실패",
                      "VIPC_SETUP_DATA (token=0x1b0) 확인"], desc="VIPC_SETUP_DATA (token=0x011)")
    assert _keys(clues) == [(3, "ipc", "0x1b0")] and drop["old_round"] == 3      # 경계 코멘트(2번)와 그 앞·설명은 버림
    # 결과 없는 재시험 요청(결정 2): 경계가 마지막 코멘트라 단서 없음 → 보류
    clues, drop = _x(["VIPC_SETUP_DATA (token=0x0de) 실패", "수정 빌드 올렸습니다. Retest 부탁"])
    assert clues == [] and drop["old_round"] == 1
    # 사내 낱말로 바꾸면 그 낱말로만
    assert _keys(_x(["VIPC_A (token=1) 실패. 2차 진행", "VIPC_A (token=2)"], retest_words=["2차"])[0]) == [(2, "ipc", "2")]


def test_retest_without_word_is_a_known_limit():
    """알려진 한계(설계 메모 "남는 위험", 시제품 M1 104·110·111): 재시험 낱말 없이 다시 돈 회차는 가르지 못해 옛 회차 단서가
    섞인다. 채택까지 막는 것은 로그 쪽(옛 token이 새 로그에 없음·성공 응답 보류·여러 사건 보류)이다."""
    clues, drop = _x(["VIPC_SETUP_DATA (token=0x2a6) 실패", "다시 돌려 주실 수 있나요?", "VIPC_SETUP_DATA (token=0x31c) 실패"])
    assert _keys(clues) == [(3, "ipc", "0x31c"), (1, "ipc", "0x2a6")] and drop["old_round"] == 0


def test_ipc_pairs_name_with_following_token_and_skips_error_names_and_name_only():
    clues, _ = _x(["VIPC_DATA_CALL_REQ (token=0x3e0) 정상, VIPC_DATA_CALL_CNF (token=0x3e1) 실패 Error(VIPC_E_X) token=0x5"])
    assert [(c["name"], c["token"]) for c in clues] == [("VIPC_DATA_CALL_REQ", "0x3e0"), ("VIPC_DATA_CALL_CNF", "0x3e1")]
    assert _x(["VIPC_SETUP_DATA 실패입니다", "token=0x0e1 실패", "VIPC_SETUP_DATA (token=<NUM#1>) 실패"])[0] == []
    assert pb.extract_clues(["VIPC_A (token=1)"], "", "", "")[0] == []        # 요청 접두어 설정이 비면 ipc를 뽑지 않는다


def test_log_line_needs_logcat_stamp_quote_mark_newest_first_dedup():
    clues, _ = _x(["> " + LINE, "본문만 onDataNetworkSetupDataFailed: cause=MISSING_UNKNOWN_APN", LINE], desc=LINE)
    assert _keys(clues) == [(3, "log_line", None)] and clues[0]["quote"] == " ".join(LINE.split())      # 공백은 접는다
    # 같은 줄에 ipc가 있으면 ipc만
    vipc = "11-14 10:02:00.594   900   910 D RIL     : [RX] VIPC_SETUP_DATA, RSP, token=0x0e1, len=8, Error(VIPC_E_DEMO_FAILURE)"
    assert _keys(_x([vipc])[0]) == [(1, "ipc", "0x0e1")]


def test_long_line_uses_first_300_chars_and_drops_half_mask_token():
    long = " ".join(LINE.split()) + " x" * 200
    clues, _ = _x([long])
    assert len(clues) == 1 and clues[0]["quote"] == long[:pb.QUOTE_MAX].rstrip() and len(clues[0]["quote"]) <= pb.QUOTE_MAX
    head = " ".join(LINE.split())[:40]
    cut = head + "a" * (pb.QUOTE_MAX - len(head) - 3) + "<APN#12> tail"       # 300자 경계가 마스킹 토큰 가운데
    assert _x([cut])[0][0]["quote"] == cut[:pb.QUOTE_MAX - 3].rstrip()
    # RIL 응답 표시 `<`는 마스킹 토큰이 아니다(측정 M3에서 찾은 결함: `[1434]<` 뒤를 다 잘라 버렸다)
    ril = "11-14 10:02:00.052  1301  1330 D RILJ    : [1434]< DATA_REGISTRATION_STATE RegStateResult{" + "regState: REG_DENIED, " * 20
    assert _x([ril])[0][0]["quote"] == " ".join(ril.split())[:pb.QUOTE_MAX].rstrip()


def test_decimal_and_hex_token_are_one_clue_and_cap_counts_over():
    clues, _ = _x(["VIPC_SETUP_DATA (token=0xe1) 실패", "VIPC_SETUP_DATA (token=225) 실패", "VIPC_SETUP_DATA (token=0x0E1)"])
    assert _keys(clues) == [(3, "ipc", "0x0E1")]
    clues, drop = _x([f"VIPC_A (token={n})" for n in range(1, 13)])
    assert len(clues) == pb.CLUES_MAX and drop["over"] == 2 and clues[0]["token"] == "12"


def test_script_clue_passes_the_same_gate_as_model_clues():
    """이름 뒤 첫 token이 다른 IPC 메시지의 것이면(`VIPC_A 요청 후 VIPC_B (token=…)`) 관문 `_clue_problem`이 버린다."""
    clues, drop = _x(["VIPC_A 요청 후 VIPC_B (token=0x10) 실패"])
    assert [(c["name"], c["token"]) for c in clues] == [("VIPC_B", "0x10")] and drop["invalid"] == 1


def test_ipc_on_a_stamped_line_keeps_the_stamp():
    """리뷰 P1-2: 시각이 붙은 IPC 로그 줄에서 뽑은 ipc 단서는 그 시각을 인용에 남긴다 — 그 시각의 줄이 로그에 있어야 쓴다
    (모델 단서도 인용이 시각 붙은 줄이면 같다)."""
    from triagelib import anchor
    rsp = "11-14 09:30:00.594   900   910 D RIL     : [RX] VIPC_SETUP_DATA, RSP, token=0x0e1, len=8, Error(VIPC_E_DEMO_FAILURE)"
    for line in (rsp, rsp + " pad" * 80):
        [c] = _x([line])[0]
        assert c["kind"] == "ipc" and anchor._clue_text(c, pb) == ("VIPC_SETUP_DATA (token=0x0e1)", "11-14 09:30:00.594")
    assert anchor._clue_text(_x(["VIPC_SETUP_DATA (token=0x0e1) 실패"])[0][0], pb)[1] is None


def test_two_token_values_in_this_round_are_a_conflict():
    """리뷰 P1-3: 이번 회차 글에 서로 다른 token 값이 둘 이상이면(이름 없이 적은 값 포함) conflict — 정정·정상과 실패를 함께 적음."""
    for comments in (["정정: VIPC_SETUP_DATA token=0x0aa이 아니라 token=0x0e1 입니다"],
                     ["실패: VIPC_SETUP_DATA (token=0x0aa)", "정정: token은 0x0aa가 아니라 0x0e1 입니다"],
                     ["VIPC_A (token=0x0dd) 정상, VIPC_A (token=0x0e1) 실패"]):
        assert _x(comments)[1]["conflict"] is True, comments
    assert _x(["VIPC_A (token=0x0e1)", "VIPC_A token=225 다시 확인"])[1]["conflict"] is False      # 같은 값(10진·16진)
    assert _x(["VIPC_A (token=0x0aa) 실패. 재시험 요청", "VIPC_A (token=0x0e1)"])[1]["conflict"] is False   # 옛 회차는 안 셈


def test_comment_numbers_follow_skipped_old_comments():
    clues, _ = _x(["VIPC_A (token=1)", "VIPC_A (token=2)"], first=6)
    assert _keys(clues) == [(7, "ipc", "2"), (6, "ipc", "1")]
    assert all(pb._clue_problem(c, {6: "VIPC_A (token=1)", 7: "VIPC_A (token=2)"}, "VIPC_", "VIPC_E_") is None for c in clues)
    # 앞 코멘트를 건너뛰었으면 설명은 그 사이 재시험 앞일 수 있다 — 옛 회차로 센다
    clues, drop = _x(["VIPC_A (token=2)"], desc="VIPC_A (token=1)", first=4)
    assert _keys(clues) == [(4, "ipc", "2")] and drop["old_round"] == 1


# -- jira_fields: 코멘트 범위 ----------------------------------------------------------------------------------

CFG = {"tracker": {"kind": "jira", "timezone": "Asia/Seoul"}, "logcat": {"timezone": "Asia/Seoul"}}


def _text(raw: dict, cfg: dict = CFG) -> dict:
    return jira_fields.extract({"key": "X-1", **raw}, cfg, None, "file")["text"]


def test_partial_and_skipped_comments_from_total_and_start_at():
    page = {"comments": [{"body": "c3"}, {"body": "c4"}]}
    t = _text({"fields": {"comment": {"startAt": 2, "total": 4, **page}}})     # 오래된 2개만 빠짐(포털 크기 상한)
    assert t["comments"] == ["c3", "c4"] and t["comments_skipped"] == 2 and "comments_partial" not in t
    t = _text({"fields": {"comment": {"startAt": 2, "total": 5, **page}}})     # 최근 것이 빠짐
    assert t["comments_partial"] == {"total": 5, "read": 2} and "comments_skipped" not in t
    t = _text({"fields": {"comment": {"total": 3, **page}}})                   # startAt 없는 MCP 모양 = 0
    assert t["comments_partial"] == {"total": 3, "read": 2}
    t = _text({"fields": {"comment": {"total": 2, **page}}})
    assert "comments_partial" not in t and "comments_skipped" not in t
    t = _text({"fields": {"comment": {"startAt": 1, "total": 2, **page}}})     # 받은 것이 더 많다 — 수가 안 맞으면 일부만 읽음과 같게
    assert t["comments_partial"] == {"total": 2, "read": 2}


def test_comment_total_must_come_from_the_source_used_and_order_must_be_known():
    """PR #170 리뷰 P1-4: 전체 수는 실제로 쓴 코멘트와 같은 출처에서만(맨 위 `comments[]`는 jira_bridge가 남긴 `comments_page`),
    맨 위 목록은 작성 시각이 있어야(최신순으로 주는 도구) — 아니면 `comments_unchecked`(뽑지 않음). 작성 시각이 있으면 그 순서로."""
    page = {"comments": [{"body": "c3"}, {"body": "c4"}]}
    t = _text({"comments": [{"body": f"c{n}"} for n in range(1, 5)], "fields": {"comment": {"startAt": 2, "total": 4, **page}}})
    assert len(t["comments"]) == 4 and t["comments_unchecked"] == "total"          # fields.comment의 total은 다른 출처
    assert _text({"comments": [{"body": "a"}], "comments_page": {"total": 1}})["comments_unchecked"] == "order"   # 시각 없음
    newest_first = [{"body": "새", "created": "2026-11-14T13:00:00+0900"}, {"body": "옛", "created": "2026-11-14T11:00:00+0900"}]
    t = _text({"comments": newest_first, "comments_page": {"startAt": 0, "total": 2}})
    assert t["comments"] == ["옛", "새"] and not any(k in t for k in ("comments_unchecked", "comments_partial"))
    assert _text({"fields": {"comment": {"comments": [{"body": "x"}]}}})["comments_unchecked"] == "total"
    assert _text({"fields": {"comment": {"total": 2, "comments": []}}})["comments_partial"] == {"total": 2, "read": 0}


def test_custom_comments_path_falls_back_to_jira_native():
    cfg = {**CFG, "tracker": {**CFG["tracker"], "field_map": {"comments": "fields.custom_notes[].text"}}}
    assert _text({"fields": {"comment": {"total": 1, "comments": [{"body": "포털이 준 코멘트"}]}}}, cfg)["comments"] == ["포털이 준 코멘트"]
    assert _text({"fields": {"custom_notes": [{"text": "사내 경로"}], "comment": {"comments": [{"body": "x"}]}}}, cfg)["comments"] \
        == ["사내 경로"]


# -- run: 단서 출처 고르기·합성 티켓 -----------------------------------------------------------------------------

LOG = maf.OUT / "tokpos.log"


@pytest.fixture(scope="module")
def seed_db() -> Path:
    return maf.build_seed_db(tmp("tt-clue-db-") / "db", plugin_root())


def _run(db: Path, name: str, fields: dict | None = None, comments: list[str] | None = None, problem: dict | None = None,
         look_at: str | None = None, root: Path | None = None, sha: str = "same", log: Path | None = None,
         ticket: dict | None = None) -> tuple[dict, Path]:
    """--issue-file(발생 시각 칸 없음)로 run. problem이 있으면 그 단서로 problem.json을 둔다(sha "same"이면 이번 입력 해시).
    `ticket`을 주면 그 모양 그대로(코멘트 모양 시험)."""
    out = tmp("tt-clue-") / name
    out.mkdir(parents=True)
    issue = out.parent / f"{name}.issue.yaml"
    ticket = ticket or {"key": "CLUE-1", "fields": dict(fields or {"summary": "데이터 연결 실패", "description": "시험 중 실패했습니다."})}
    if comments is not None:      # 포털·Jira 모양(전체 수 있음, 작성 순)
        ticket["fields"]["comment"] = {"startAt": 0, "total": len(comments), "comments": [{"body": b} for b in comments]}
    issue.write_text(yaml.safe_dump(ticket, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if problem is not None:
        doc = {"schema_version": 1, "key": "CLUE-1", "origin": "정답 입력",
               "source_sha256": hashlib.sha256(issue.read_bytes()).hexdigest() if sha == "same" else sha,
               "symptom": {"text": "", "types": [], "not_in_db": False}, **problem}
        (out / "problem.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    args = ["run", "CLUE-1", "--offline-db", db, "--out", out, "--logs", log or LOG, "--issue-file", issue,
            "--tz", "Asia/Seoul", "--year", "2026", *(["--look-at", look_at] if look_at else [])]
    return run_json("triage.py", args, root=root), out


def _verdict(a: dict) -> tuple:
    d = a["decision"]
    return d["state"], (d["selected"] or {}).get("cause"), d["reason"], d["check"]["why"]


FAIL = "CP 확인: VIPC_SETUP_DATA (token=0x0e1) 에서 실패했습니다."
IPC = {"comment": 2, "kind": "ipc", "name": "VIPC_SETUP_DATA", "token": "0x0e1", "quote": "VIPC_SETUP_DATA (token=0x0e1)",
       "side": "cp", "stale": False}


def test_script_clue_adopts_found_location_and_reports_origin(seed_db):
    a, out = _run(seed_db, "auto", comments=["로그 첨부했습니다.", FAIL])
    assert _verdict(a) == ("accepted", "DATA-003-01", "anchored_top", "cp_point")
    d = a["decision"]
    assert d["location"] == {"state": "found", "source": "comment", "kind": "point"}       # 코멘트 출처는 확정이 아니다
    assert d["check"]["via"] == {"comment": 2, "clue": "ipc", "how": "ipc", "places": 1, "origin": "script"}
    assert "- 단서 위치: 코멘트 2번 단서(ipc, 스크립트) 로그에서 찾음" in (out / "report.md").read_text(encoding="utf-8")
    trace = [json.loads(x) for x in (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(1 for r in trace if r.get("step") == "3-clue") == 1
    # 끄면 단서 없음(no_reference), 설명만 있고 코멘트 없는 티켓·코멘트만 있고 설명 없는 티켓(포털 선별 파일)
    a, _ = _run(seed_db, "off", comments=["로그 첨부했습니다.", FAIL], root=plugin_root(eligibility={"comment_clues": False}))
    assert a["decision"]["reason"] == "no_reference"
    a, _ = _run(seed_db, "nodesc", fields={"summary": "데이터 연결 실패"}, comments=[FAIL])
    assert _verdict(a)[:2] == ("accepted", "DATA-003-01")


def test_fresh_problem_json_wins_over_script_clues(seed_db):
    comments = ["로그 첨부했습니다.", FAIL]
    a, out = _run(seed_db, "prob", comments=comments, problem={"clues": [IPC]})
    assert a["decision"]["check"]["via"]["origin"] == "problem"
    assert "단서(ipc, 문제 파악)" in (out / "report.md").read_text(encoding="utf-8")
    a, _ = _run(seed_db, "prob0", comments=comments, problem={"clues": []})          # 새 problem.json이 단서 없음이면 그대로
    assert a["decision"]["reason"] == "no_reference"
    a, _ = _run(seed_db, "stale", comments=comments, problem={"clues": []}, sha="0" * 64)     # 낡으면 자동 추출
    assert a["decision"]["check"]["via"]["origin"] == "script"
    assert any("problem.json" in w and "쓰지 않았다" in w for w in a["warnings"]), a["warnings"]


def test_look_at_turns_script_clues_off_with_one_line(seed_db):
    look = "VIPC_SETUP_DATA (token=0x0dd)"       # 성공 응답 — 기준 줄이 정한다(코멘트의 실패 token으로 바꾸지 않는다)
    a, _ = _run(seed_db, "look", comments=["로그 첨부했습니다.", FAIL], look_at=look)
    b, _ = _run(seed_db, "lookonly", comments=["로그 첨부했습니다."], look_at=look)
    assert _verdict(a) == _verdict(b) and a["decision"]["state"] == "held" and "via" not in a["decision"]["check"]
    assert "코멘트 단서 1개 안 씀 — 기준 줄(--look-at)을 썼다" in a["warnings"]


def test_log_line_with_other_stamp_is_dropped_for_both_sources(seed_db):
    other = LINE.replace("10:02:00.624", "19:02:00.624")       # CP·다른 로그 시계: 본문은 로그에 한 곳(실패 줄)
    a, out = _run(seed_db, "stamp-ok", comments=["로그 첨부", LINE])
    assert a["decision"]["check"]["via"] == {"comment": 2, "clue": "log_line", "how": "text", "places": 1, "origin": "script"}
    a, out = _run(seed_db, "stamp-auto", comments=["로그 첨부", other])
    assert a["decision"]["reason"] == "no_reference"
    assert "코멘트 단서(스크립트) 버림: 로그에 없음 1" in a["warnings"]
    assert json.loads((out / "reference.json").read_text(encoding="utf-8"))["dropped"] == \
        [{"comment": 2, "kind": "log_line", "why": "붙인 줄의 시각이 이 로그에 없음"}]
    model = {"comment": 2, "kind": "log_line", "name": None, "token": None, "quote": other, "side": "ap", "stale": False}
    a, _ = _run(seed_db, "stamp-model", comments=["로그 첨부", other], problem={"clues": [model]})
    assert a["decision"]["reason"] == "no_reference"
    assert "코멘트 2번 단서, 로그에서 못 찾음(붙인 줄의 시각이 이 로그에 없음)" in a["warnings"]
    a, _ = _run(seed_db, "stamp-model-ok", comments=["로그 첨부", LINE], problem={"clues": [{**model, "quote": LINE}]})
    assert a["decision"]["check"]["via"]["origin"] == "problem"


def test_long_pasted_line_is_found_by_its_first_300_chars(seed_db):
    long = next(x for x in LOG.read_text(encoding="utf-8").splitlines() if x.startswith("11-14 10:02:00.502"))
    assert len(long) > pb.QUOTE_MAX
    _, out = _run(seed_db, "long", comments=["로그 첨부", long])
    assert "- 단서 위치: 코멘트 2번 단서(log_line, 스크립트) 로그에서 찾음" in (out / "report.md").read_text(encoding="utf-8")


# 설계 메모 M4 합성 티켓: (이름, 코멘트, Jira 코멘트 필드(일부만 읽음), 기대 (state, cause, reason)). 채택 쪽으로 틀리지 않는다.
M4 = [
    ("정상+실패 한 줄", ["로그 첨부", "VIPC_SETUP_DATA (token=0x0dd) 는 정상 응답이고, 실패는 VIPC_SETUP_DATA (token=0x0e1) 입니다."], None,
     ("held", None, "ineligible")),     # 정상 token 단서가 성공 응답이라 보류(token 값 둘이라 어차피 보류 — 리뷰 P0·P1-3, 전에는 맞게 채택)
    ("정상 token만 이름 뒤", ["로그 첨부", "VIPC_SETUP_DATA (token=0x0dd) 정상, 다음 시도 token=0x0e1 실패"], None,
     ("held", None, "ineligible")),
    ("결과 코멘트에 재시험 낱말", ["로그 첨부", "1차: VIPC_SETUP_DATA (token=0x0dd) 실패. 재시험 요청합니다.",
                                   "재시험 결과 VIPC_SETUP_DATA (token=0x0e1) 에서 또 실패했습니다."], None, ("held", None, "no_reference")),
    ("정정 전 token만 로그에 있음", ["로그 첨부", "VIPC_SETUP_DATA (token=0x0dd) 실패입니다.",
                                     "정정: 실패한 건 VIPC_SETUP_DATA (token=0x0f7) 입니다."], None, ("held", None, "ineligible")),
    ("코멘트 일부만 읽음", None, {"total": 3, "comments": [{"body": "로그 첨부"}, {"body": FAIL}]}, ("held", None, "no_reference")),
    ("오래된 코멘트만 빠짐", None, {"startAt": 1, "total": 3, "comments": [{"body": "로그 첨부"}, {"body": FAIL}]},
     ("accepted", "DATA-003-01", "anchored_top")),
    ("CP 시계 시각 정상 줄", ["로그 첨부", "11-14 19:01:00.110  2101  2101 D DNC-0   : Internet data state changed from "
                                           "DISCONNECTED to CONNECTED."], None, ("held", None, "no_reference")),
    ("가린 10진 token", ["로그 첨부", "CP 확인: VIPC_SETUP_DATA (token=<NUM#1>) 실패"], None, ("held", None, "no_reference")),
    ("10진 token(로그는 16진)", ["로그 첨부", "CP 확인: VIPC_SETUP_DATA (token=225) 실패"], None, ("accepted", "DATA-003-01", "anchored_top")),
]


@pytest.mark.parametrize("name,comments,jira,expect", M4, ids=[m[0] for m in M4])
def test_synthetic_tickets_never_adopt_wrong(seed_db, name, comments, jira, expect):
    fields = {"summary": "데이터 연결 실패", "description": "시험 중 데이터 연결이 실패했습니다.", **({"comment": jira} if jira else {})}
    a, _ = _run(seed_db, f"m4-{M4.index(next(m for m in M4 if m[0] == name))}", fields=fields, comments=comments)
    assert _verdict(a)[:3] == expect, (name, a["decision"], a["warnings"])
    if name == "코멘트 일부만 읽음":
        assert any("일부만 읽어(전체 3개 중 2개)" in w for w in a["warnings"]), a["warnings"]
    if name == "오래된 코멘트만 빠짐":       # 코멘트 번호는 Jira 순번(앞 1개 건너뜀)
        assert a["decision"]["check"]["via"]["comment"] == 3


# -- PR #170 독립 리뷰 재현(틀린 채택 길) — 고친 뒤 모두 보류 ---------------------------------------------------------

def _variant(name: str, token: str) -> Path:
    """tokpos.log + 10:00:00.010/.030 실패 IPC 요청·응답(token) — 0x0aa면 NETWORK 사건 앞 다른 실패, 0x0e1이면 같은 token 두 곳.
    시험 안에서 만드는 임시 로그(커밋하지 않는다)."""
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        out.append(line)
        if line.startswith("11-14 10:00:00.004"):
            out += [f"11-14 10:00:00.010   900   910 D RIL     : [TX] VIPC_SETUP_DATA, REQ, token={token}, len=24",
                    f"11-14 10:00:00.030   900   910 D RIL     : [RX] VIPC_SETUP_DATA, RSP, token={token}, len=8, "
                    "Error(VIPC_E_DEMO_FAILURE)"]
    path = tmp("tt-clue-log-") / f"{name}.log"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


NET = next(x for x in LOG.read_text(encoding="utf-8").splitlines() if x.startswith("11-14 10:00:00.062"))   # NETWORK 사건 줄
RSP_0E1 = "11-14 09:30:00.594   900   910 D RIL     : [RX] VIPC_SETUP_DATA, RSP, token=0x0e1, len=8, Error(VIPC_E_DEMO_FAILURE)"
REVIEW = [      # (이름, 로그 종류, 코멘트, 기대 (state, reason, why))
    ("C1 시각 붙은 IPC 줄, 그 시각 로그에 없음", None, ["로그", RSP_0E1], ("held", "no_reference", None)),
    ("C1c 시각 붙은 IPC 줄, 다른 실패의 같은 token", "0x0aa",
     ["로그", RSP_0E1.replace("09:30:00.594", "09:00:00.030").replace("0x0e1", "0x0aa")], ("held", "no_reference", None)),
    ("C2 정정(이름+틀린 token 먼저)", "0x0aa", ["로그", "정정: VIPC_SETUP_DATA token=0x0aa이 아니라 token=0x0e1 입니다"],
     ("held", "ambiguous", "sources")),
    ("C2b 정정이 이름 없이", "0x0aa", ["로그", "실패: VIPC_SETUP_DATA (token=0x0aa)", "정정: token은 0x0aa가 아니라 0x0e1 입니다"],
     ("held", "ambiguous", "sources")),
    ("C5b 없는 날짜(02-30)", None, ["로그", LINE.replace("11-14 10:02", "02-30 10:02")], ("held", "no_reference", None)),
    ("C5c 없는 시각(25시)", None, ["로그", LINE.replace("10:02:00.624", "25:02:00.624")], ("held", "no_reference", None)),
    ("D4 실패 단서 로그에 없음 + 참고 줄", None, ["로그", "실패는 VIPC_SETUP_DATA (token=0x0f7) 입니다. 참고로 시험 전 상태:\n" + NET],
     ("held", "ambiguous", "sources")),
    ("D4b 실패 token 두 곳 + 참고 줄", "0x0e1", ["로그", "실패는 VIPC_SETUP_DATA (token=0x0e1) 입니다. 참고로 시험 전 상태:\n" + NET],
     ("held", "ambiguous", "locations")),
    ("D4c 성공 응답 + 참고 줄", None, ["로그", "VIPC_SETUP_DATA (token=0x0dd) 응답 정상인데 실패. 참고:\n" + NET],
     ("held", "ineligible", "no_event_at_reference")),
    ("D4d 실패 줄 시각 틀림 + 참고 줄", None,
     ["로그", "실패 줄:\n" + LINE.replace("10:02:00.624", "10:02:09.624") + "\n시험 전:\n" + NET], ("held", "ambiguous", "sources")),
    ("D4e 실패는 앞 코멘트, 최근은 참고 줄만", None, ["로그", "VIPC_SETUP_DATA (token=0x0f7) 실패", "비교용 정상 구간 로그:\n" + NET],
     ("held", "ambiguous", "sources")),
]


@pytest.mark.parametrize("name,variant,comments,expect", REVIEW, ids=[r[0].split()[0] for r in REVIEW])
def test_review_repros_are_held(seed_db, name, variant, comments, expect):
    log = _variant(name.split()[0], variant) if variant else None
    a, _ = _run(seed_db, "rv-" + name.split()[0], comments=comments, log=log)
    d = a["decision"]
    assert (d["state"], d["reason"], d["check"]["why"]) == expect, (name, d, a["warnings"])


def test_model_clue_with_stamped_ipc_quote_obeys_the_stamp_rule(seed_db):
    model = {"comment": 2, "kind": "ipc", "name": "VIPC_SETUP_DATA", "token": "0x0e1", "quote": RSP_0E1, "side": "cp", "stale": False}
    a, _ = _run(seed_db, "rv-model", comments=["로그", RSP_0E1], problem={"clues": [model]})
    assert a["decision"]["reason"] == "no_reference"
    assert "코멘트 2번 단서, 로그에서 못 찾음(붙인 줄의 시각이 이 로그에 없음)" in a["warnings"]


@pytest.mark.parametrize("name,ticket", [
    ("C8c 전체 수 없는 맨 위 목록", {"comments": [{"body": "VIPC_SETUP_DATA (token=0x0aa) 실패"}]}),
    ("C8d 최신순으로 준 목록(시각 없음)", {"fields": {"comment": {"total": 3, "startAt": 0}},
                                         "comments": [{"body": "새 로그 올립니다 VIPC_SETUP_DATA (token=0x0e1) 실패"},
                                                      {"body": "재시험 부탁드립니다"}, {"body": "VIPC_SETUP_DATA (token=0x0aa) 실패"}]}),
], ids=["C8c", "C8d"])
def test_review_comment_shapes_without_total_or_order_extract_nothing(seed_db, name, ticket):
    fields = {"summary": "데이터 연결 실패", "description": "시험 중 실패했습니다.", **(ticket.get("fields") or {})}
    a, _ = _run(seed_db, "rv-" + name.split()[0], ticket={"key": "CLUE-1", **ticket, "fields": fields},
                log=_variant(name.split()[0], "0x0aa"))
    assert a["decision"]["reason"] == "no_reference", a["decision"]
    assert any("안 씀 — Jira 코멘트의 전체 수·순서를 알 수 없다" in w for w in a["warnings"]), a["warnings"]


# 명시 기준(로그 마커) + 분석 구간 밖 사건을 가리키는 단서 → 다른 사건(H07, 리뷰 cases3 M2·M3). 로그에 없는 단서는 마커가 정한다.
MARKER = {"marker_patterns": [r"^(?:TestRunner|Automation)\s*:\s*\[?(?i:step)\s*(?P<step>\d+)\]?\s*(?:[:-]\s*.*?\s)?(?P<status>START|PASS|FAIL)\b"],
          "marker_status": {"start": ["start"], "pass": ["pass"], "fail": ["fail"]}, "anchor_without_step": True,
          "window": {"pre_sec": 60, "post_sec": 30, "fail_only_pre_sec": 120, "max_span_sec": 900}, "disagree_minutes": 10,
          "steps_file_tz": None, "clock_offset": None}


def _marker_log() -> Path:
    """0x0aa 변형(10:00 다른 실패) + Step 3 START 10:01:30 · FAIL 10:02:00.700(10:02 DATA 실패를 감싼다)."""
    out = []
    for line in _variant("mk", "0x0aa").read_text(encoding="utf-8").splitlines():
        if line.startswith("11-14 10:02:00.000"):
            out.append("11-14 10:01:30.000  3000  3000 I TestRunner: Step 3 START")
        out.append(line)
        if line.startswith("11-14 10:02:00.624"):
            out.append("11-14 10:02:00.700  3000  3000 I TestRunner: Step 3 FAIL")
    path = tmp("tt-clue-log-") / "marker.log"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("name,comment,expect", [
    ("same", "VIPC_SETUP_DATA (token=0x0e1) 실패", ("accepted", "anchored_top", "range")),
    ("outside", "VIPC_SETUP_DATA (token=0x0aa) 실패", ("held", "ambiguous", "sources")),
    ("notinlog", "VIPC_SETUP_DATA (token=0x0f7) 실패", ("accepted", "anchored_top", "range")),
], ids=["same", "outside", "notinlog"])
def test_marker_reference_and_clue_outside_its_window_conflict(seed_db, name, comment, expect):
    root = plugin_root(failed_step=MARKER)
    a, out = _run(seed_db, "mk-" + name, comments=[comment], log=_marker_log(), root=root)
    assert a["step_anchor"]["source"] == "log_marker"
    d = a["decision"]
    assert (d["state"], d["reason"], d["check"]["why"]) == expect, (d, a["warnings"])
    refs = json.loads((out / "reference.json").read_text(encoding="utf-8"))["refs"]
    assert [r.get("outside", False) for r in refs if r["source"] == "comment"] == ([True] if name == "outside" else
                                                                                   [False] if name == "same" else [])
