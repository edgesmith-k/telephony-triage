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
    # 확인 리뷰 P2: token 바로 뒤 값만 센다 — 같은 줄의 다른 16진 값(원인 값·길이)은 정정이 아니다
    for text in ("VIPC_A (token=0x0e1) 실패, token 처리 중 0xdead 오류", "VIPC_A (token=0x0e1) 실패 (cause 0x1b)",
                 "[RX] VIPC_A, RSP, token=0x0e1, len=0x08, Error(VIPC_E_X)"):
        assert _x([text])[1]["conflict"] is False, text


def test_stamp_unmet_guard_and_invalid_stamp_is_none(seed_db):
    """시각 규칙의 두 안전장치: 찾기 결과에 `stamp`가 없어도(읽지 못한 시각) 버리고, parse_logcat은 읽을 수 없는 시각을 `none`으로 낸다."""
    from triagelib import anchor
    assert anchor._stamp_unmet("11-14 10:02:00.624", {"hits": 1}) is True               # 결과에 stamp 칸 없음
    assert anchor._stamp_unmet("11-14 10:02:00.624", {"hits": 1, "stamp": "none"}) is True
    assert anchor._stamp_unmet("11-14 10:02:00.624", {"hits": 1, "stamp": "many"}) is False
    assert anchor._stamp_unmet(None, {"hits": 1}) is False and anchor._stamp_unmet("x", {"hits": 0}) is False
    from common import lookat
    look = tmp("tt-clue-look-") / "look-at.json"
    for stamp, want in (("02-30 10:02:00.624", "none"), ("11-14 25:02:00.624", "none"), ("11-14 10:02:00.624", "same")):
        look.write_text(json.dumps({"look_at": lookat.clean(LINE), "ref": None, "stamp": stamp}), encoding="utf-8")
        found = run_json("parse_logcat.py", ["ipc", LOG, "--find", look, "--rules", seed_db / "parser-rules", "--tz", "Asia/Seoul",
                                             "--year", "2026"])["find"]
        assert (found["hits"], found["stamp"]) == (1, want), stamp


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
    # 확인 리뷰 P1-2: 작성 시각이 같은 값이 있거나 일부만 있으면 순서를 증명할 수 없다(어느 출처든) — 시각이 전혀 없는
    # fields.comment(Jira 원본·포털)만 받은 순서를 믿는다
    tie = [{"body": "새", "created": "2026-11-14T12:00:00+0900"}, {"body": "재시험", "created": "2026-11-14T11:00:00+0900"},
           {"body": "옛", "created": "2026-11-14T11:00:00+0900"}]
    assert _text({"comments": tie, "comments_page": {"total": 3}})["comments_unchecked"] == "order"
    assert _text({"fields": {"comment": {"total": 3, "comments": tie}}})["comments_unchecked"] == "order"
    some = [{"body": "a", "created": "2026-11-14T11:00:00+0900"}, {"body": "b"}]
    assert _text({"fields": {"comment": {"total": 2, "comments": some}}})["comments_unchecked"] == "order"
    t = _text({"fields": {"comment": {"total": 2, "comments": [{"body": "a"}, {"body": "b"}]}}})
    assert t["comments"] == ["a", "b"] and "comments_unchecked" not in t
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


def _ref_cause(out: Path) -> str | None:
    """기준에 붙은 사건의 원인(보류여도 — JOB/eligibility.json 전체, analysis.json은 4KB 압축으로 사건을 뺄 수 있다)."""
    return next((e["cause"] for e in json.loads((out / "eligibility.json").read_text(encoding="utf-8"))["events"] if e["ref"]), None)


HELD_SCRIPT = ("held", None, "ineligible", "comment_unconfirmed")     # 스크립트 단서는 위치 후보로만(R3, A474 — 옛 기대는 채택)


FAIL = "CP 확인: VIPC_SETUP_DATA (token=0x0e1) 에서 실패했습니다."
IPC = {"comment": 2, "kind": "ipc", "name": "VIPC_SETUP_DATA", "token": "0x0e1", "quote": "VIPC_SETUP_DATA (token=0x0e1)",
       "side": "cp", "stale": False}


def test_script_clue_is_a_location_candidate_and_reports_origin(seed_db):
    """R3(A474, D1): 스크립트가 코멘트에서 뽑은 단서는 실패 지점 후보로만 — 붙은 사건(원인 후보 DATA-003-01)을 싣고 보류한다.
    comment_adopt 설정(기본 참)과 상관없다. 문제 파악 단서(problem.json)는 그대로 채택(test_eligibility)."""
    a, out = _run(seed_db, "auto", comments=["로그 첨부했습니다.", FAIL])
    assert _verdict(a) == HELD_SCRIPT and _ref_cause(out) == "DATA-003-01"
    assert json.loads((out / "reference.json").read_text(encoding="utf-8"))["comment_adopt"] is False
    d = a["decision"]
    assert d["location"] == {"state": "found", "source": "comment", "kind": "point"}       # 코멘트 출처는 확정이 아니다
    assert d["check"]["via"] == {"comment": 2, "clue": "ipc", "how": "ipc", "places": 1, "origin": "script"}
    assert "- 단서 위치: 코멘트 2번 단서(ipc, 스크립트) 로그에서 찾음" in (out / "report.md").read_text(encoding="utf-8")
    trace = [json.loads(x) for x in (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sum(1 for r in trace if r.get("step") == "3-clue") == 1
    # 끄면 단서 없음(no_reference), 설명만 있고 코멘트 없는 티켓·코멘트만 있고 설명 없는 티켓(포털 선별 파일)
    a, _ = _run(seed_db, "off", comments=["로그 첨부했습니다.", FAIL], root=plugin_root(eligibility={"comment_clues": False}))
    assert a["decision"]["reason"] == "no_reference"
    a, out = _run(seed_db, "nodesc", fields={"summary": "데이터 연결 실패"}, comments=[FAIL])
    assert _verdict(a) == HELD_SCRIPT and _ref_cause(out) == "DATA-003-01"


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
     ("held", None, "ineligible")),     # R3: 스크립트 단서는 보류(옛 기대 채택)
    ("CP 시계 시각 정상 줄", ["로그 첨부", "11-14 19:01:00.110  2101  2101 D DNC-0   : Internet data state changed from "
                                           "DISCONNECTED to CONNECTED."], None, ("held", None, "no_reference")),
    ("가린 10진 token", ["로그 첨부", "CP 확인: VIPC_SETUP_DATA (token=<NUM#1>) 실패"], None, ("held", None, "no_reference")),
    ("10진 token(로그는 16진)", ["로그 첨부", "CP 확인: VIPC_SETUP_DATA (token=225) 실패"], None, ("held", None, "ineligible")),     # R3
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


# -- 확인 리뷰(8de39b2f) 재현: 관문에서 버린 실패 단서 + 참고 줄, 같은 작성 시각, 좁힌 token 세기 ---------------------------

T = lambda hm: f"2026-11-14T{hm}.000+0900"
CONFIRM = [      # (이름, 로그 종류, 티켓 덮어쓰기 | 코멘트, 기대 (state, cause|reason, why))
    ("P1 관문 탈락 실패 ipc + 참고 줄", None, ["로그", "실패: VIPC_SETUP_DATA(id 0x2) token=0x0e1 응답 실패\n참고 시험 전 상태:\n" + NET],
     ("held", "ambiguous", "sources")),
    ("P1b 사이에 다른 IPC 이름 + 참고 token", "0x0aa",
     ["VIPC_SETUP_DATA 다음 VIPC_DEACT_DATA token=0x0e1 에서 실패, 참고: VIPC_SETUP_DATA (token=0x0aa)는 정상 요청"], ("held", None, None)),
    ("P1c 짧은 실패 인용 + 참고 줄", None, ["로그", "실패:\n11-14 10:02:00.624 x\n참고:\n" + NET], ("held", "ambiguous", "sources")),
    # N8: 무관한 16진은 token 충돌이 아니다 — 스크립트 단서라 채택 대신 comment_unconfirmed(R3, 옛 기대 채택 DATA-003-01 cp_point)
    ("N8 token 뒤 무관한 16진", None, ["VIPC_SETUP_DATA (token=0x0e1) 실패, token 처리 중 0xdead 오류"], ("held", "ineligible", "comment_unconfirmed")),
    ("N8b cause 16진", None, ["VIPC_SETUP_DATA (token=0x0e1) 실패 (cause 0x1b)"], ("held", "ineligible", "comment_unconfirmed")),
    ("N8c RSP 줄의 16진 len", None, ["로그", "[RX] VIPC_SETUP_DATA, RSP, token=0x0e1, len=0x08, Error(VIPC_E_DEMO_FAILURE)"],
     ("held", "ineligible", "comment_unconfirmed")),
]


@pytest.mark.parametrize("name,variant,comments,expect", CONFIRM, ids=[r[0].split()[0] for r in CONFIRM])
def test_confirm_review_repros(seed_db, name, variant, comments, expect):
    log = _variant(name.split()[0], variant) if variant else None
    a, _ = _run(seed_db, "cf-" + name.split()[0], comments=comments, log=log)
    d = a["decision"]
    got = (d["state"], (d["selected"] or {}).get("cause") if d["state"] == "accepted" else d["reason"], d["check"]["why"])
    assert got[0] == expect[0] and (expect[1] is None or got[1:] == expect[1:]), (name, d, a["warnings"])
    if name.startswith("P1 "):
        assert any("모양 안 맞음" in w for w in a["warnings"]), a["warnings"]


@pytest.mark.parametrize("name,ticket", [
    ("N5b 같은 작성 시각(fields.comment, 최신순)", {"fields": {"comment": {"total": 3, "startAt": 0, "comments": [
        {"body": "새 로그 올립니다", "created": T("12:00:00")}, {"body": "재시험 요청", "created": T("11:00:00")},
        {"body": "VIPC_SETUP_DATA (token=0x0aa) 실패", "created": T("11:00:00")}]}}}),
    ("N5c 같은 작성 시각(맨 위 목록, 최신순)", {"comments_page": {"total": 3, "startAt": 0}, "comments": [
        {"body": "새 로그 올립니다", "created": T("12:00:00")}, {"body": "재시험 요청", "created": T("11:00:00")},
        {"body": "VIPC_SETUP_DATA (token=0x0aa) 실패", "created": T("11:00:00")}]}),
], ids=["N5b", "N5c"])
def test_equal_created_times_extract_nothing(seed_db, name, ticket):
    fields = {"summary": "데이터 연결 실패", "description": "시험 중 실패했습니다.", **(ticket.get("fields") or {})}
    a, _ = _run(seed_db, "cf-" + name.split()[0], ticket={"key": "CLUE-1", **ticket, "fields": fields}, log=_variant(name.split()[0], "0x0aa"))
    assert a["decision"]["reason"] == "no_reference", a["decision"]
    assert any("전체 수·순서를 알 수 없다" in w for w in a["warnings"]), a["warnings"]


# -- 11/20 종합 리뷰 수정(설계 v2 R3·R4·R5·R7) ------------------------------------------------------------------------

OLD = "VIPC_SETUP_DATA (token=0x0aa) 실패"


@pytest.mark.parametrize("body", [
    "{quote}" + OLD + "{quote}\n위 증상은 이번엔 안 보이고, 다른 지점에서 실패합니다.",
    "앞 글 {quote}" + OLD + "{quote} 은 이번엔 안 보임",
    "{QUOTE}\n" + OLD + "\n{quote}\n다른 지점에서 실패",
    "다른 지점에서 실패\n{quote}\n" + OLD,                 # 닫히지 않은 인용은 글 끝까지
    "bq. " + OLD + "\n다른 지점에서 실패",
    "> " + OLD + "\n다른 지점에서 실패",
    "  >> " + OLD,
    "{quote:1차 시험 결과}" + OLD + "{quote}\n다른 지점에서 실패",       # 제목 붙은 인용
], ids=["block", "inline", "multiline", "unclosed", "bq", "gt", "nested-gt", "titled"])
def test_quoted_text_is_not_a_clue(body):
    """R4(C-2): 인용한 옛 회차 글(`{quote}` 블록·`bq.`·`>` 줄)에서는 단서를 뽑지 않는다(재시험 요청 뒤 코멘트가 옛 실패를 인용)."""
    clues, drop = _x([OLD, "수정 SW로 재시험 요청드립니다.", body])
    assert clues == [] and not drop["conflict"] and drop["invalid"] == 0, (clues, drop)


def test_quoted_token_is_not_counted_as_a_conflict_and_mid_line_gt_is_text():
    """R4: 인용 안 token 값은 이번 글의 token 충돌(`conflict`)로 세지 않는다. 줄 가운데 `>`는 인용이 아니다."""
    clues, drop = _x(["{quote}" + OLD + "{quote}\nVIPC_SETUP_DATA (token=0x0e1) 에서 실패"])
    assert _keys(clues) == [(1, "ipc", "0x0e1")] and not drop["conflict"]
    clues, drop = _x(["> " + OLD + "\nVIPC_SETUP_DATA (token=0x0e1) 에서 실패"])
    assert _keys(clues) == [(1, "ipc", "0x0e1")] and not drop["conflict"]
    assert _keys(_x(["결과 > VIPC_SETUP_DATA (token=0x0e1) 실패"])[0]) == [(1, "ipc", "0x0e1")]


def test_retest_word_is_a_whole_english_word():
    """R7(C-11): 영어 재시험 낱말은 낱말 단위 — `pretest`는 회차 경계가 아니고 활용형(`retests`·`retested`·`retesting`)은 경계.
    한글이 바로 붙은 `Retest결과`도 경계(Python `\\b`는 한글을 낱말 글자로 봐 놓친다). 한글 낱말은 포함 비교 그대로."""
    for word in ("pretest", "pretested", "retester"):
        clues, drop = _x([f"{word} 결과 VIPC_SETUP_DATA (token=0x0e1) 실패"])
        assert _keys(clues) == [(1, "ipc", "0x0e1")] and drop["old_round"] == 0, word
    for word in ("Retest결과", "RETEST", "re-test", "retested", "retesting", "Retests", "재시험결과"):
        clues, drop = _x([OLD, f"{word} 공유", "VIPC_SETUP_DATA (token=0x0e1) 실패"])
        assert _keys(clues) == [(3, "ipc", "0x0e1")] and drop["old_round"] == 1, word


def test_resorted_comment_page_with_start_at_is_partial():
    """R7(C-7): 작성 시각으로 다시 정렬했으면 startAt > 0일 때 건너뛴 것이 옛 것인지 모른다(최신순으로 페이지를 주는 도구) —
    `comments_skipped` 대신 `comments_partial`(뽑지 않는다). 시각 없는 `fields.comment`(오래된 것부터)는 그대로 skipped."""
    newest_first = [{"body": OLD, "created": "2026-11-14T09:00:00+0900"}, {"body": "로그 첨부", "created": "2026-11-14T08:00:00+0900"}]
    for raw in ({"comments": newest_first, "comments_page": {"startAt": 2, "total": 4}},
                {"fields": {"comment": {"startAt": 2, "total": 4, "comments": newest_first}}}):
        t = _text(raw)
        assert t["comments_partial"] == {"total": 4, "read": 2} and "comments_skipped" not in t, raw
    assert _text({"fields": {"comment": {"startAt": 2, "total": 4, "comments": [{"body": "c3"}, {"body": "c4"}]}}})["comments_skipped"] == 2


def test_reference_only_log_line_is_held_with_its_candidate(seed_db):
    """R3 재현(Codex reference-only): 참고 구간이라 적은 줄이 단서가 돼도 스크립트 단서는 채택하지 않는다 — 그 지점 사건
    (NETWORK-001-03)을 원인 후보로 싣고 보류. 옛 결과는 accepted NETWORK-001-03."""
    a, out = _run(seed_db, "refonly", comments=["이번 실패는 데이터 연결 실패입니다. 아래는 시험 전 참고 구간이며 이번 실패 지점이 아닙니다.\n"
                                                 + NET])
    assert _verdict(a) == ("held", None, "ineligible", "comment_unconfirmed") and _ref_cause(out) == "NETWORK-001-03"
    # 확인 리뷰 P2: 판단 줄은 그 후보를, 결론 줄도 그 후보를 한 번 적는다(1위 규칙 일치만 앞세우지 않게)
    md = (out / "report.md").read_text(encoding="utf-8").splitlines()
    # NETWORK-001-03(비행기 모드 켬)은 시드 DB에서 버그 아님 — 판단 줄 끝에 그 표시(sim1120 P2-7, decision.events[].not_a_bug)
    assert ("- 판단: 원인 보류: 코멘트에서 자동으로 찾은 지점의 원인 후보 NETWORK-001-03, 확인 필요 · 이슈 DB에서 버그 아님(시험 절차·"
            "설정 조작이 만든 동작으로 알려진 규칙)인 기준 사건 원인: NETWORK-001-03") in md
    assert next(e for e in a["decision"]["events"] if e["ref"])["not_a_bug"] is True
    concl = next(x for x in md if x.startswith("- 결론: "))
    assert concl.startswith("- 결론: 원인 보류 — 코멘트에서 자동으로 찾은 지점의 원인 후보 NETWORK-001-03, 확인 필요. 규칙 일치 1위"), concl


def test_submitter_note_is_kept_apart_from_clues(seed_db):
    """R5: 포털이 넘긴 제출자 참고 글(`fields.tt_note`)은 issue.json `text.note`·analysis.json `issue.note`(판단 근거 아님 표시)로만
    가고 단서 추출은 읽지 않는다(옛 포털은 설명 칸으로 보내 단서가 됐다 — C-3). analysis.json 칸 이름은 `submitter_note`(이슈 DB
    레코드 note와 다르게)."""
    note = "그래도 분석을 요청한 이유: VIPC_SETUP_DATA (token=0x0e1) 는 정상인데 왜 연결이 안 되는지"
    a, out = _run(seed_db, "note", fields={"summary": "데이터 연결 실패", "tt_note": note}, comments=["로그 첨부했습니다."])
    assert a["decision"]["reason"] == "no_reference", a["decision"]
    assert json.loads((out / "issue.json").read_text(encoding="utf-8"))["text"]["note"] == note
    # 200자 안 참고 글은 근거·판단 사건을 줄여서라도 남는다(긴 작업 경로에서도 — 리뷰 11/20, 포털 Jira 안내 줄이 모델에 가게)
    assert a["issue"]["submitter_note"] == "제출자 참고(판단 근거·단서 아님): " + note, a["issue"]
    a, _ = _run(seed_db, "nonote", comments=["로그 첨부했습니다."])
    assert "submitter_note" not in a["issue"]
    # 포털 NOTE_MAX(2000자)까지 잘리지 않고 issue.json에 간다. analysis.json은 4KB 맞춤 첫 단계에서 머리말 포함 200자
    long = "앞 안내. 제출자 이유: " + "x" * 1980 + " 끝"
    a, out = _run(seed_db, "longnote", fields={"summary": "데이터 연결 실패", "tt_note": long[:2000]}, comments=["로그 첨부했습니다."])
    assert json.loads((out / "issue.json").read_text(encoding="utf-8"))["text"]["note"] == long[:2000]
    from triagelib import driver
    from triagelib import report as rep
    assert a["issue"]["submitter_note"] == rep._clip(driver.NOTE_LABEL + long[:2000], rep.NOTE_FIT), a["issue"]["submitter_note"][:80]
    assert driver.NOTE_MAX == 2000       # 포털 NOTE_MAX(옛 상한 240자)


def test_fit_drops_submitter_note_before_events_and_evidence():
    """리뷰 P1(11/20 두 번): 4KB 맞춤은 제출자 참고 글을 가장 먼저 머리말 포함 200자로 줄이고(포털 맨 앞 Jira 안내 줄이 남게) 그 뒤에
    판단 사건·근거를 줄인다 — 줄여도 기준에 붙은 사건(ref)은 남는다. 다 줄여도 넘을 때만 마지막에 `issue.json text.note 참고` 표시.
    `truncated`는 넣은 뒤에도 4096B 안."""
    from triagelib import report as rep

    ev = [{"ts": f"t{i}", "tag": "T", "msg": "m" * 60} for i in range(6)]

    def result(note_len: int, warn: int = 0) -> dict:
        return {"issue": {"summary": "s", "submitter_note": "n" * note_len},
                "candidates": [{"cause": "DATA-003-01", "evidence": list(ev)}, {"cause": "NETWORK-001-03", "evidence": list(ev)}],
                "decision": {"state": "held", "reason": "ineligible", "events": [
                    {"type": "NETWORK-001", "ref": False, "cause": "NETWORK-001-03"},
                    {"type": "DATA-003", "ref": True, "cause": "DATA-003-01"},
                    {"type": "DATA-003", "ref": False, "cause": "DATA-003-01"}]},
                "files": {"report": "r"}, "must_show": [], "warnings": ["w" * warn] if warn else []}
    out = rep.fit(result(3000))
    assert len(out["issue"]["submitter_note"]) == rep.NOTE_FIT and len(out["candidates"][1]["evidence"]) == 6
    assert [e["ref"] for e in out["decision"]["events"]] == [False, True, False]     # 글을 줄이면 맞아 사건·근거는 그대로
    out = rep.fit(result(3000, warn=3000))
    assert [e["ref"] for e in out["decision"]["events"]] == [True] and len(out["candidates"][0]["evidence"]) == 6   # ref 사건은 남는다
    assert len(out["issue"]["submitter_note"]) == rep.NOTE_SHORT                     # 다른 후보 근거를 빼기 전에 80자로
    assert len(rep.dumps(out).encode("utf-8")) + 1 <= rep.ANALYSIS_MAX
    stuck = {**result(3000), "issue": {"summary": "s" * 3900, "submitter_note": "n" * 3000}}     # 줄일 수 없는 칸이 큼
    assert rep.fit(stuck)["issue"]["submitter_note"] == rep.NOTE_GONE
    # truncated 자리: 키 없이 4096B에 딱 맞는 결과도 키를 넣은 뒤 4096B를 넘지 않는다(옛 코드는 넣고 나서 넘었다)
    base = {"files": {"report": "r"}, "must_show": [], "warnings": [""]}
    tight = {**base, "warnings": ["x" * (rep.ANALYSIS_MAX - 1 - len(rep.dumps(base).encode("utf-8")))]}
    assert len(rep.dumps(tight).encode("utf-8")) + 1 == rep.ANALYSIS_MAX
    out = rep.fit(tight)
    assert len(rep.dumps(out).encode("utf-8")) + 1 <= rep.ANALYSIS_MAX and out["truncated"] is False


def test_fit_shortens_note_again_before_other_candidate_evidence_goes():
    """확인 리뷰 P2(11/20): 다른 후보 근거를 다 빼기 전에 참고 글을 머리말 포함 `NOTE_SHORT`(80)자로 한 번 더 줄인다 — 줄일 칸을
    키워 가며 참고 글이 처음 80자가 되는 자리에서 다른 후보 근거가 아직 남아 있다(단계 순서가 바뀌면 이미 비어 있다)."""
    from triagelib import report as rep

    ev = [{"ts": f"t{i}", "tag": "T", "msg": "m" * 60} for i in range(6)]
    for n in range(1500, 4000, 4):
        out = rep.fit({"issue": {"summary": "s" * n, "submitter_note": "n" * 3000},
                       "candidates": [{"cause": "DATA-003-01", "evidence": list(ev)}, {"cause": "NETWORK-001-03", "evidence": list(ev)}],
                       "decision": {"state": "held", "reason": "ineligible", "events": []},
                       "files": {"report": "r"}, "must_show": [], "warnings": []})
        if len(out["issue"]["submitter_note"]) <= rep.NOTE_SHORT:
            break
    assert len(out["issue"]["submitter_note"]) == rep.NOTE_SHORT and out["candidates"][1]["evidence"], n


@pytest.mark.parametrize("n", [150, 300])
def test_korean_note_does_not_push_out_other_candidate_evidence(seed_db, n):
    """확인 리뷰 P2(r3b_note_mid.sh 모양): 한글 참고 글 150자 이상 + 모델 단서 채택이면 4KB 맞춤이 다른 후보 근거를 다 빼기 전에
    참고 글을 80자로 줄인다(옛 순서는 근거 0줄, 글 171·200자)."""
    from triagelib import driver
    from triagelib import report as rep
    note = "가" * n
    a, _ = _run(seed_db, f"mid{n}", fields={"summary": "데이터 연결 실패", "description": "시험 중 실패했습니다.", "tt_note": note},
                comments=["로그 첨부", FAIL], problem={"symptom": {"text": "x", "types": ["DATA-003"], "not_in_db": False}, "clues": [IPC]})
    assert (a["decision"]["state"], a["decision"]["selected"]["cause"]) == ("accepted", "DATA-003-01"), a["decision"]
    others = [c for c in a["candidates"] if c["cause"] != "DATA-003-01"]
    got = a["issue"]["submitter_note"]
    assert got.startswith(driver.NOTE_LABEL) and (all(c["evidence"] for c in others) or len(got) <= rep.NOTE_SHORT), (others, len(got))


def test_script_clue_hold_line_names_the_candidate_like_the_portal():
    """리뷰 P1: 스크립트 단서 보류(comment_unconfirmed, via.origin script)의 판단 줄은 포털 카드와 같은 문구 — 후보는 ref 사건 원인."""
    from triagelib import report as rep

    dec = {"state": "held", "reason": "ineligible", "check": {"why": "comment_unconfirmed", "via": {"origin": "script"}},
           "events": [{"ref": False, "cause": "NETWORK-001-03"}, {"ref": True, "cause": "DATA-003-01"}]}
    assert rep.decision_line(dec, ["c"]) == "- 판단: 원인 보류: 코멘트에서 자동으로 찾은 지점의 원인 후보 DATA-003-01, 확인 필요"
    assert rep.decision_line({**dec, "events": []}, []) == "- 판단: 원인 보류: 코멘트에서 자동으로 찾은 지점, 확인 필요"
    model = {**dec, "check": {"why": "comment_unconfirmed", "via": {"origin": "problem"}}}      # 문제 파악 단서 + comment_adopt 끔
    assert "코멘트에 적힌 위치라" in rep.decision_line(model, [])


def test_retest_plan_sentence_is_not_a_round_boundary():
    """sim1120 P2-8(S-02·S-05·S-22): 앞으로의 계획 문장("재시험 잡겠음"·"나오면 재시험"·"다음 재시험 때"·"will retest"·"retest 예정")의
    재시험 낱말은 회차 경계가 아니다. 지난 일·결과 문장("Retest 했는데"·"재시험했고 PASS")은 그대로 경계(ponytail 휴리스틱)."""
    clue = "VIPC_SETUP_DATA (token=0x0e1) 실패"
    for plan in ("수정 빌드 나오면 10.5.1 재시험 잡겠음.", "이 이슈는 수정 빌드 나오면 재시험.", "다음 재시험 때는 APN을 원래 상태로 두고 돌리겠습니다.",
                 "We will retest on the next build.", "retest 예정"):
        clues, drop = _x([clue, plan])
        assert _keys(clues) == [(1, "ipc", "0x0e1")] and drop["old_round"] == 0, plan
    for done in ("Retest 했는데 결과 동일합니다.", "사내 기준으로 고치고 재시험했고 PASS입니다.", "수정 빌드 나오면 재시험. Retest 결과: 같은 증상"):
        clues, drop = _x([clue, done])
        assert clues == [] and drop["old_round"] == 1, done


# 리뷰(1bb528a7) 변형 14개: 계획 표시는 재시험 낱말이 든 조각(쉼표·`—`·`;`·"했는데"로도 나눈다)에서만, 결과 낱말이 있으면 경계
RETEST_VARIANTS = [
    ("수정 빌드 나오면 10.5.1 재시험 잡겠음.", False),
    ("다음 재시험 때는 APN을 원래 상태로 두고 돌리겠습니다.", False),
    ("재시험했는데 또 FAIL, 다음 빌드에서 다시 해 보겠음", True),
    ("재시험 결과 동일하게 FAIL 재현, 로그 확인 부탁드리겠습니다", True),
    ("재시험 시 detach 되면서 FAIL 재현", True),
    ("재시험 결과 FAIL. 로그 확인 부탁드리겠습니다.", True),
    ("Retested on new build, still FAIL, will check modem log", True),
    ("Retest with next build: FAIL again", True),
    ("Retest per test plan 3: FAIL", True),
    ("재시험 결과 PASS 되면 close 예정이었으나 FAIL 재현", True),
    ("재테스트 완료 — 같은 증상(attach 실패) 재현됨, 내일 모뎀 로그 받아 보겠습니다", True),
    ("재시험 필요", True),
    ("will retest tomorrow", False),
    ("retest scheduled for next week", False),
    ("다음 빌드 나오면 재시험하겠습니다", False),
    # 결과 낱말 없이 조각 나누기(쉼표)로만 경계가 되는 경우 — 나누기를 지우면 "겠" 때문에 계획으로 읽는다
    ("재시험해 봤는데 attach 안 됨, 다음 빌드에서 다시 해 보겠음", True),
]


@pytest.mark.parametrize("text,boundary", RETEST_VARIANTS)
def test_retest_plan_piece_variants(text, boundary):
    assert pb._retest(text, [w.casefold() for w in pb.RETEST_WORDS]) is boundary


def test_all_comments_skipped_is_skipped_not_partial():
    """sim1120 P1-4(D3): 포털이 긴 마지막 코멘트 때문에 코멘트를 하나도 넘기지 않으면(startAt == total, 0개) `comments_partial`이 아니라
    `comments_skipped`(전부)다. 일부만 빠진 0개(startAt < total)는 그대로 partial."""
    assert _text({"fields": {"comment": {"startAt": 5, "total": 5, "comments": []}}})["comments_skipped"] == 5
    t = _text({"fields": {"comment": {"startAt": 0, "total": 5, "comments": []}}})
    assert t["comments_partial"] == {"total": 5, "read": 0} and "comments_skipped" not in t


def _run_args(db: Path, name: str, ticket: dict, *extra) -> tuple[dict, Path]:
    out = tmp("tt-clue-") / name
    out.mkdir(parents=True)
    issue = out.parent / f"{name}.issue.yaml"
    issue.write_text(yaml.safe_dump(ticket, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return run_json("triage.py", ["run", "CLUE-1", "--offline-db", db, "--out", out, "--logs", LOG, "--issue-file", issue,
                                  "--tz", "Asia/Seoul", "--year", "2026", *extra]), out


def test_jira_time_field_is_shown_but_not_used_for_the_window(seed_db):
    """D4(sim1120): Jira 발생 시각 칸은 로그와 다른 시계(장비·PC)라 분석 구간·근접 중심에 쓰지 않는다 — 표시만("분석에 안 씀").
    사용자가 준 시각(`--answer time=`)은 지금처럼 기준 시각이다."""
    ticket = {"key": "CLUE-1", "fields": {"summary": "데이터 연결 실패", "customfield_10001": "2026-11-14T09:00:00+0900"}}
    a, out = _run_args(seed_db, "jira-time", ticket)
    assert a["issue"]["occurred_at"] == "2026-11-14T00:00:00+00:00"                 # 값은 표시용으로 남는다
    assert a["step_anchor"]["source"] == "symptom_scan" and not (a["logs"].get("window") or {}).get("start")   # 로그 전체
    assert "occurred_at" not in json.loads((out / "issue_meta.json").read_text(encoding="utf-8"))   # 매처 근접 중심 아님
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "(Jira 발생 시각 칸(분석에 안 씀) 2026-11-14T00:00:00+00:00)" in md and "Jira 발생 시각 기준" not in md
    given, out2 = _run_args(seed_db, "given-time", ticket, "--answer", "time=2026-11-14T10:02:00+09:00")
    assert given["logs"]["window"]["start"] == "2026-11-14T00:57:00.000Z"            # 준 시각 ±5분
    assert json.loads((out2 / "issue_meta.json").read_text(encoding="utf-8"))["occurred_at"] == "2026-11-14T01:02:00.000Z"


def test_no_comments_from_portal_warns_with_portal_head(seed_db):
    """D3·sim1120 항목 6: 포털이 긴 마지막 코멘트 때문에 코멘트를 하나도 넘기지 않으면(startAt == total) 경고 하나 — 포털이 머리
    "마지막 댓글이 길어"로 알아본다. 4KB 맞춤에서 먼저 남는 경고다(KEY_WARNING)."""
    ticket = {"key": "CLUE-1", "fields": {"summary": "데이터 연결 실패",
                                          "comment": {"startAt": 3, "total": 3, "comments": []}}}
    a, _ = _run_args(seed_db, "no-comments", ticket)
    warns = [w for w in a.get("warnings") or [] if w.startswith("마지막 댓글이 길어")]
    assert len(warns) == 1 and "3개" in warns[0] and "일부만 읽어" not in " ".join(a.get("warnings") or [])


def test_model_picked_look_at_is_labelled_and_never_confirmed(seed_db):
    """sim1120 항목 4: `--look-at-source model`(모델이 코멘트에서 고른 줄)이면 실패 지점 출처가 model이고 확정(confirmed)으로 올리지
    않는다. 판단은 채택될 수 있다(문제 파악 단서와 같게, Y1). 기본(user)은 지금처럼 담당자 지정."""
    ticket = {"key": "CLUE-1", "fields": {"summary": "데이터 연결 실패"}}
    line = NET[:200]      # --look-at ≤300자(앞부분만 붙여도 본문 일치로 찾는다)
    user, _ = _run_args(seed_db, "look-user", ticket, "--look-at", line)
    model, out = _run_args(seed_db, "look-model", ticket, "--look-at", line, "--look-at-source", "model")
    assert user["decision"]["location"]["source"] == "look_at"
    assert model["decision"]["location"]["source"] == "model" and model["decision"]["location"]["state"] != "confirmed"
    assert model["decision"]["state"] == user["decision"]["state"] and model["request_hash"] != user["request_hash"]
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "- 기준 줄(모델이 코멘트에서 고른 지점(담당자 지정 아님)): 로그에서 찾음" in md and "담당자가 지정한 기준 줄" not in md
