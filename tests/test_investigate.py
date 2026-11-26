"""조사 모드(11/25 A635): run의 `investigate` 판정, check-output 탐색 검증 게이트 6개 → analysis.json·기록 `investigation`,
report.md CAUSE 칸 조사 결론 줄, Jira 본문(issue_post) CAUSE 줄. 합성 JOB만(모델 실행 없음, 공개 근거)."""

from __future__ import annotations

import json
import shutil
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import issue_post  # noqa: E402
import trackers  # noqa: E402
from common import issuepost  # noqa: E402
from tests.test_check_output import EXPLORE_PENDING, OK_KEYS, Q1, _sha, _window, check, make_job  # noqa: E402
from triagelib import driver, report  # noqa: E402

SAMPLE_DB = REPO / "tests" / "fixtures" / "issue-db-sample"
Q0 = "15:10:00.100 p0 I ofonod src/gprs.c:gprs_attach() attach requested apn=internet"
Q_W = "15:10:02.300 p0 W ofonod drivers/rilmodem/gprs-context.c:setup_cb() activation failed"
Q_AFTER = "15:10:03.400 p0 I datad network manager daemon state=disconnected reason=pdn_reject"     # 기준(15:10:02) 뒤
HELD = {"state": "held", "reason": "no_candidate", "selected": None, "location": driver.NO_LOCATION,
        "check": {"why": None, "checked": 0, "total": 0}, "events": [], "events_total": 0}
CAUSE_HEAD = ["### CAUSE", report.decision_line(HELD, []), report.CONCLUSION_PREFIX + "아는 증상·원인과 맞는 후보 없음.",
              "- 분류 후보: **후보 없음** (증상 시그니처에 맞는 유형 없음)"]


def _rules(base: Path, cp_mark: bool = True) -> Path:
    """이슈 DB 사본의 parser-rules(스키마 포함). cp_mark면 vrild 태그에 `ipc: vendor`(CP 쪽 표시)를 더한다."""
    db = base / "db"
    shutil.copytree(SAMPLE_DB / "parser-rules", db / "parser-rules")
    shutil.copytree(SAMPLE_DB / "schema", db / "schema")
    if cp_mark:
        tags = db / "parser-rules" / "tags.yaml"
        tags.write_text(tags.read_text(encoding="utf-8") + "  - {tag: vrild, category: common, ipc: vendor, added_for: '-', "
                        "added_on: 2026-11-25, reason: 시험 (벤더 RIL 데몬)}\n", encoding="utf-8")
    return db / "parser-rules"


def _job(base: Path, mode: bool = True, cp_mark: bool = True, cands=(), rows=None, platform: str = "ofono") -> Path:
    """조사 모드 JOB: 스키마 `ok`를 갖춘 analysis.json(후보 없음 판단), CAUSE 칸이 있는 report.md, events.json에 규칙 경로."""
    job = make_job(base, "explore", "plain", **({"rows": rows} if rows else {}))
    ev = json.loads((job / "events.json").read_text(encoding="utf-8"))
    ev["rules"] = {"path": str(_rules(base, cp_mark))}
    (job / "events.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    analysis.update(OK_KEYS, candidates=list(cands), decision=HELD, analyzer=None, platform=platform,
                    investigate=issuepost.investigate_mode({"candidates": list(cands)}) if mode else {"mode": False})
    (job / "analysis.json").write_text(json.dumps({k: v for k, v in analysis.items() if v is not None}, ensure_ascii=False),
                                       encoding="utf-8")
    (job / "report.md").write_text("\n".join(["## MOCK-9076 분석", "", "### PROBLEM", "- 이슈: x", "", *CAUSE_HEAD, "",
                                              "### ANALYSIS", EXPLORE_PENDING, ""]), encoding="utf-8")
    return job


def _out(layer="CP 내부", quotes=(Q1, Q_AFTER), table="| 단계 | 기대 | 기대 주체 | 기대 근거 | 관측 줄 | 일치 |", rows=None,
         claim="단계 2 — CP가 인증 실패로 응답", head="vrild가 SETUP_DATA_CALL을 인증 실패로 끝냄", extra=()) -> str:
    rows = rows if rows is not None else ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
                                          "| 2 | SETUP 응답이 성공 | CP 내부 | spec:3GPP 24.301 | " + Q1 + " | false |"]
    return "\n".join([f"가설 1: {head}", f"책임 경계: {layer}", "로그로 확인:", *[f"- {q}" for q in quotes],
                      "코드로 추정: 코드 근거 없음", "반대 근거: 없음", "다음 확인: 모뎀 로그 15:10:01 구간, CP 담당",
                      "기대 체인:", table, "|---|---|---|---|---|---|", *rows, f"첫 갈라짐: {claim}", *extra, ""])


def _run(job: Path, text: str, capsys):
    (job / "explore-output.md").write_text(text, encoding="utf-8")
    code, data, err = check(job, "explore", capsys=capsys)
    assert code == 0, (data, err)
    inv = json.loads((job / "analysis.json").read_text(encoding="utf-8")).get("investigation")
    return data, inv


def _failed(inv: dict) -> list[str]:
    return [g["name"] for g in inv["gate"] if not g["ok"]]


def _cause_rows(job: Path) -> list[str]:
    rows = (job / "report.md").read_text(encoding="utf-8").split("\n")
    at = rows.index("### CAUSE")
    return rows[at + 1:rows.index("", at)]


# --- 조사 모드 판정 -------------------------------------------------------------------------------------------

def test_investigate_mode_is_decided_once_from_candidates():
    assert issuepost.investigate_mode({"candidates": []}) == {"mode": True, "reason": "후보 없음"}
    assert issuepost.investigate_mode({"candidates": [{"cause": None, "C": 0}]}) == {"mode": True, "reason": "1위 C=0"}
    assert issuepost.investigate_mode({"candidates": [{"cause": "X-001-01", "C": None}]})["mode"] is True     # 판정 불가
    assert issuepost.investigate_mode({"candidates": [{"cause": "X-001-01", "C": 1}]}) == {"mode": False}
    assert issuepost.investigate_mode({"candidates": [{"C": 0}, {"C": 1}], "decision": {"state": "accepted"}}) == {"mode": False}


# --- 양성 ------------------------------------------------------------------------------------------------------

def test_all_gates_pass_is_identified_on_top_of_cause(tmp_path, capsys):
    job = _job(tmp_path)
    data, inv = _run(job, _out(), capsys)
    assert data["investigation"] == "identified" and _failed(inv) == []
    assert inv["status"] == "identified" and inv["layer"] == "CP 내부" and inv["hyp"] == 1
    assert inv["first_divergence"] == {"step": 2, "expect": "SETUP 응답이 성공"}
    assert [g["name"] for g in inv["gate"]] == ["인용 원문", "첫 어긋남", "책임 층", "실패 뒤 흔적", "숫자 메커니즘", "외부 근거"]
    assert inv["explore_sha"] == _sha(job / "explore-output.md")
    rows = _cause_rows(job)
    assert rows[0].startswith("- 조사 결론 (LLM, 인용·형식 확인): vrild가 SETUP_DATA_CALL을 인증 실패로 끝냄 / 첫 어긋남: 단계 2")
    assert rows[0].endswith("책임 층: CP 내부") and rows[3:] == CAUSE_HEAD[1:]     # 설명·보류 하위 줄 뒤 기존 칸·순서 그대로
    rec = json.loads((job / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert rec["investigation"] == inv
    assert report.schema_violation(json.loads((job / "analysis.json").read_text(encoding="utf-8"))) is None


# --- 음성(필수 2건) -------------------------------------------------------------------------------------------

def test_conclusion_without_looking_after_failure_is_insufficient(tmp_path, capsys):
    """① 기준 시각(15:10:02) 뒤 줄 인용도 window 구간도 없다 → 게이트 4 실패, 결론 줄 아래 근거 부족."""
    job = _job(tmp_path)
    data, inv = _run(job, _out(quotes=(Q1,)), capsys)
    assert inv["status"] == "insufficient_evidence" and _failed(inv) == ["실패 뒤 흔적"]
    rows = _cause_rows(job)
    assert rows[:3] == CAUSE_HEAD[1:3] + [rows[2]] and rows[2].startswith("- 조사 결론 (LLM, 근거 부족): ")
    assert "실패한 검증: 실패 뒤 흔적" in rows[2] and rows[3].startswith("  - 실패 이유: 실패 뒤 흔적 — 기준 시각 뒤")


def test_layer_not_matching_expected_actor_is_insufficient(tmp_path, capsys):
    """② 책임 경계 AP 내부인데 첫 갈라짐 단계의 기대 주체는 CP 내부 → 게이트 3 실패."""
    job = _job(tmp_path)
    _data, inv = _run(job, _out(layer="AP 내부"), capsys)
    assert inv["status"] == "insufficient_evidence" and _failed(inv) == ["책임 층"]
    assert "책임 경계 AP 내부 ≠ 단계 2 기대 주체 CP 내부" in inv["gate"][2]["why"]


# --- 그 밖 -----------------------------------------------------------------------------------------------------

def test_claimed_divergence_not_earliest_false_fails_gate_2(tmp_path, capsys):
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | false |",
            "| 2 | SETUP 응답이 성공 | CP 내부 | spec:x | " + Q1 + " | false |"]
    _data, inv = _run(_job(tmp_path), _out(rows=rows), capsys)
    assert "첫 어긋남" in _failed(inv) and inv["first_divergence"]["step"] == 1


def test_numeric_expectation_needs_mechanism_recompute(tmp_path, capsys):
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | 5초 안에 응답이 성공 | CP 내부 | spec:x | " + Q1 + " | false |"]
    _data, inv = _run(_job(tmp_path / "a"), _out(rows=rows), capsys)
    assert _failed(inv) == ["숫자 메커니즘"]
    _data, inv = _run(_job(tmp_path / "b"), _out(rows=rows, extra=("메커니즘 재계산: 01.2-00.1 = 1.1초 → 고치면 결과가 뒤집히나: 예",)),
                      capsys)
    assert _failed(inv) == []
    _data, inv = _run(_job(tmp_path / "c"), _out(rows=rows, extra=("메커니즘 재계산: 1.1초 → 고치면 결과가 뒤집히나: 아니오",)), capsys)
    assert _failed(inv) == ["숫자 메커니즘"]


def test_cp_conclusion_without_cp_tag_quote_fails_gate_6(tmp_path, capsys):
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | SETUP 응답이 성공 | CP 내부 | spec:x | " + Q_W + " | false |"]
    _data, inv = _run(_job(tmp_path / "a"), _out(quotes=(Q_W, Q_AFTER), rows=rows), capsys)
    assert _failed(inv) == ["외부 근거"] and inv["gate"][5]["why"] == "결론 쪽(CP) 태그 줄 인용 없음"
    _data, inv = _run(_job(tmp_path / "b", cp_mark=False), _out(), capsys)      # tags.yaml에 CP 표시가 없다
    assert _failed(inv) == ["외부 근거"] and inv["gate"][5]["why"] == "사내 태그 설정에 CP/망 표시 없음(설정 전)"


def test_window_after_reference_counts_as_looking_after(tmp_path, capsys):
    job = _job(tmp_path / "a")
    _window(job, rows=("15:10:01.900 p0 E hiddend carrier link lost", "15:10:05.000 p0 I hiddend carrier link back"),
            last="2026-09-20T15:10:05.000Z")
    _data, inv = _run(job, _out(quotes=(Q1,)), capsys)
    assert _failed(inv) == []


def test_window_counts_only_when_a_line_after_reference_exists(tmp_path, capsys):
    """리뷰 L4: 구간 기록의 중심(`at`)이 기준 뒤여도 실제 줄이 기준 뒤에 없으면(마지막 줄이 기준과 같은 시각 포함) 인정하지 않는다."""
    for name, last in (("before", "15:10:01.900"), ("same", "15:10:02.000")):
        job = _job(tmp_path / name)
        _window(job, rows=(f"{last} p0 E hiddend carrier link lost",), last=f"2026-09-20T{last}Z")
        rec = json.loads((job / "windows.json").read_text(encoding="utf-8"))
        rec["windows"][0]["at"] = "2026-09-20T15:10:05.000Z"
        (job / "windows.json").write_text(json.dumps(rec), encoding="utf-8")
        _data, inv = _run(job, _out(quotes=(Q1,)), capsys)
        assert _failed(inv) == ["실패 뒤 흔적"], name


def test_old_five_column_table_is_gate_3_failure_not_format_error(tmp_path, capsys):
    rows = ["| 1 | SETUP 요청이 나간다 | log:15:10:00 | " + Q0 + " | true |", "| 2 | SETUP 응답이 성공 | spec:x | " + Q1 + " | false |"]
    _data, inv = _run(_job(tmp_path), _out(table="| 단계 | 기대 | 기대 근거 | 관측 줄 | 일치 |", rows=rows), capsys)
    assert _failed(inv) == ["책임 층"] and inv["gate"][2]["why"] == "기대 주체 칸 없음(옛 형식 표)"


def test_not_investigate_mode_leaves_report_and_analysis_bytes(tmp_path, capsys):
    """1위 C=1(조사 모드 아님): 리포트·analysis.json은 조사 모드가 없던 때와 같은 바이트다."""
    a, b = _job(tmp_path / "a", mode=False), _job(tmp_path / "b", mode=False)
    raw = json.loads((b / "analysis.json").read_text(encoding="utf-8"))
    raw.pop("investigate")
    (b / "analysis.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    before = (a / "analysis.json").read_bytes()
    data, inv = _run(a, _out(), capsys)
    _run(b, _out(), capsys)
    assert inv is None and "investigation" not in data and (a / "analysis.json").read_bytes() == before
    assert (a / "report.md").read_bytes() == (b / "report.md").read_bytes()
    assert "investigation" not in json.loads((a / "check-output.json").read_text(encoding="utf-8"))["explore"]


def test_recheck_replaces_the_investigation_line(tmp_path, capsys):
    job = _job(tmp_path)
    _run(job, _out(quotes=(Q1,)), capsys)
    rec = json.loads((job / "check-output.json").read_text(encoding="utf-8"))
    rec["explore"]["format_warnings"] = ["x"]          # 형식 경고 뒤 다시 검사 한 번
    (job / "check-output.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    _data, inv = _run(job, _out(), capsys)
    rows = _cause_rows(job)
    assert inv["status"] == "identified" and sum(r.startswith(issuepost.INVESTIGATION_PREFIX) for r in rows) == 1
    assert rows[0].startswith("- 조사 결론 (LLM, 인용·형식 확인)")


def test_rule_top_c0_differs_moves_under_as_observed_match(tmp_path, capsys):
    top = {**OK_KEYS["candidates"][0], "cause": None, "C": 0}
    job = _job(tmp_path, cands=[top])
    _data, inv = _run(job, _out(), capsys)
    assert json.loads((job / "analysis.json").read_text(encoding="utf-8"))["investigate"] == {"mode": True, "reason": "1위 C=0"}
    assert _cause_rows(job)[2] == ("  - 관측된 규칙 일치: data > DATA-001 > 원인 미확인 — 규칙 1위(원인 일치 없음), 조사 결론과 같다고 "
                                   "확인되지 않음")


def test_jira_cause_has_investigation_on_top_or_below(tmp_path, capsys):
    job = _job(tmp_path)
    _run(job, _out(), capsys)
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    cause = [i["text"] for i in issue_post.build(fake, a, None, None, set())[0]["CAUSE"]]
    assert cause[0].startswith("조사 결론 (LLM, 인용·형식 확인): ") and cause[3].startswith("분류: 후보 없음")
    assert cause[1] == issuepost.INVESTIGATION_NOTE.lstrip(" -")
    assert not any("Step 7" in t for t in cause) and cause[2].startswith("규칙 판정은 보류 — ")     # 리뷰 L6
    path = job / "check-output.json"           # R-11: Jira는 check-output 기록의 investigation을 읽는다
    rec = json.loads(path.read_text(encoding="utf-8"))
    inv = rec["explore"]["investigation"]
    rec["explore"]["investigation"] = {**inv, "status": "insufficient_evidence",
                                       "gate": [{**g, "ok": g["name"] != "책임 층"} for g in inv["gate"]]}
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    cause = [i["text"] for i in issue_post.build(fake, a, None, None, set())[0]["CAUSE"]]
    assert cause[0].startswith("분류: 후보 없음")
    inv_at = next(i for i, t in enumerate(cause) if t.startswith("조사 결론 (LLM, 근거 부족): "))
    assert "실패한 검증: 책임 층" in cause[inv_at] and not any(t.startswith("실패 이유") for t in cause)     # Jira는 이름만


def test_compare_eval_scores_recorded_outputs_only():
    """비교 eval 틀(모델 실행 없음): 합성 case 2개로 변경 전·뒤 층 정답률·원인 줄 인용률·근거 부족 비율을 센다."""
    sys.path.insert(0, str(REPO / "tools"))
    import investigate_eval
    res = investigate_eval.run(REPO / "tests" / "fixtures" / "investigate-eval", ["before", "after"])
    assert res["n"] == 2 and res["arms"]["before"]["insufficient"] == "2/2" and res["arms"]["before"]["layer_correct"] == "0/2"
    after = res["arms"]["after"]
    assert (after["layer_correct"], after["cause_cited"], after["identified_correct"], after["identified_layer_only"],
            after["identified_wrong"], after["insufficient"]) == ("2/2", "2/2", "1/2", "0/2", "0/2", "1/2")
    assert all(c["synthetic"] for c in res["cases"])


# --- 독립 리뷰 반영(M1~M4, L1·L2·L4·L6) ------------------------------------------------------------------------

def test_skipped_or_failed_explore_clears_old_investigation(tmp_path, capsys):
    """리뷰 M1: 탐색 생략·형식 실패(다시 검사 아님)면 앞 조사 결론 줄과 analysis.json investigation을 지운다."""
    for name in ("skipped", "failed"):
        job = _job(tmp_path / name)
        _run(job, _out(), capsys)
        rows = (job / "report.md").read_text(encoding="utf-8").split("\n")
        at = next(i for i, r in enumerate(rows) if r.startswith("- 탐색 분석"))
        end = next(i for i in range(at + 1, len(rows)) if not rows[i].startswith("  - "))
        (job / "report.md").write_text("\n".join(rows[:at] + [EXPLORE_PENDING] + rows[end:]), encoding="utf-8")   # 다시 TODO 줄
        assert any(r.startswith(issuepost.INVESTIGATION_PREFIX) for r in rows)
        if name == "skipped":
            check(job, "explore", skipped="안 함", capsys=capsys)
        else:
            (job / "explore-output.md").write_text("형식 없음\n", encoding="utf-8")
            check(job, "explore", capsys=capsys)
        assert issuepost.INVESTIGATION_PREFIX not in (job / "report.md").read_text(encoding="utf-8"), name
        assert "investigation" not in json.loads((job / "analysis.json").read_text(encoding="utf-8")), name


def test_jira_ignores_investigation_of_another_explore_output(tmp_path, capsys):
    """리뷰 M1: 기록 investigation의 explore_sha가 지금 탐색 검사 기록(output_sha256)과 다르면 Jira 본문에 싣지 않는다."""
    job = _job(tmp_path)
    _run(job, _out(), capsys)
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    path = job / "check-output.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["explore"]["investigation"]["explore_sha"] = "0" * 64
    path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    cause = [i["text"] for i in issue_post.build(fake, a, None, None, set())[0]["CAUSE"]]
    assert not any(t.startswith("조사 결론") for t in cause)


def test_cp_side_defaults_to_backend_vendor_ipc_tags(tmp_path, capsys):
    """리뷰 M2: tags.yaml이 `ipc`를 선언하지 않으면 CP 쪽은 백엔드 기본(Android `VENDOR_IPC_TAGS` = RIL)으로 본다. `CP-망 경계`도 CP
    태그 하나면 통과."""
    from tests.test_check_output import ROWS
    rows = [(ts, "RIL" if tag == "vrild" else tag, lv, msg) for ts, tag, lv, msg in ROWS]
    q1 = Q1.replace(" vrild ", " RIL ")
    chain = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
             "| 2 | SETUP 응답이 성공 | {layer} | spec:x | " + q1 + " | false |"]
    for layer in ("CP 내부", "CP-망 경계"):
        job = _job(tmp_path / layer.replace(" ", "_"), cp_mark=False, rows=rows, platform="android")
        _data, inv = _run(job, _out(layer=layer, quotes=(q1, Q_AFTER), rows=[c.format(layer=layer) for c in chain]), capsys)
        assert _failed(inv) == [], (layer, inv["gate"])


def test_chain_row_with_pipe_in_observed_cell_keeps_header_positions():
    """리뷰 M3: 머리 행이 있고 칸이 더 많으면(관측 칸 안의 `|`) 남는 칸을 관측 칸에 붙이고 머리 위치로 읽는다."""
    from common import evidence
    text = _out(rows=["| 1 | SETUP 응답이 성공 | CP 내부 | spec:x | 15:10:01.200 p0 E vrild a | b | false |"])
    row = evidence.parse_explore(text)["hyps"][0]["기대 체인"][0]
    assert (row["주체"], row["근거"], row["관측"], row["일치"]) == ("CP 내부", "spec:x", "15:10:01.200 p0 E vrild a | b", "false")


def test_fit_trims_investigation_before_evidence_and_must_show():
    """리뷰 M4: 4KB를 넘으면 조사 결론(통과한 게이트 why·원인·기대)을 근거 줄·must_show보다 먼저 줄인다."""
    big = {"ts": "2026-09-20T05:30:00.000Z", "tag": "DNC-0", "msg": "x" * 100, "event": "e"}
    inv = {"status": "identified", "hyp": 1, "cause": "가" * 120, "layer": "CP 내부",
           "first_divergence": {"step": 2, "expect": "나" * 80},
           "gate": [{"name": f"g{i}", "ok": True, "why": "다" * 80} for i in range(6)], "explore_sha": "0" * 64}
    result = {"files": {"report": "r"}, "must_show": ["로그 범위: " + "라" * 150], "investigation": inv,
              "candidates": [{"cause": "C-0", "evidence": [dict(big) for _ in range(6)]}]}
    while len(report.dumps(result).encode("utf-8")) < 4096:
        result["candidates"][0]["evidence"].append(dict(big))
    n = len(result["candidates"][0]["evidence"])
    out = report.fit(json.loads(json.dumps(result)))
    assert all(g["why"] == "" for g in out["investigation"]["gate"]) and len(out["investigation"]["cause"]) <= 60
    assert len(out["candidates"][0]["evidence"]) == n and out["must_show"] == result["must_show"]


def test_number_unit_and_explore_question_and_report_core_patterns():
    """리뷰 L1(`번` 빼고 영어 단위), L2(조사 질문은 질문 전체로), L6(조사 결론 줄은 리포트 표시 의무)."""
    import show_guard
    from common import shown
    from triagelib import output
    rx = output.NUM_UNIT_RX
    assert not rx.search("2번 단계에서 응답") and not rx.search("5 sets") and not rx.search("3 secondary")
    assert all(rx.search(t) for t in ("5 sec 뒤", "10 seconds", "3 times", "5s", "300ms", "2 min", "5초", "3회"))
    assert show_guard.EXPLORE_Q.search("조사할까요? (심층 분석 뒤 탐색 분석, 토큰 추가 사용)")
    assert not show_guard.EXPLORE_Q.search("다른 원인을 더 조사할까요?")
    # R-33: SKILL.md의 짧은 문구 `조사할까요?`(줄 머리·꾸밈 뒤)와 후보 없음 문구도 Step 5 질문이다. 앞 낱말에 붙은 질문은 아니다
    for q in ("조사할까요?", "**조사할까요?**", "- 조사할까요? (예/아니오)", "조사할까요? (탐색 분석, 토큰 추가 사용)",
              "원인을 조사할까요? (심층 분석 뒤 탐색 분석, 토큰 추가 사용)"):
        assert show_guard.EXPLORE_Q.search(q), q
    for q in ("이 원인으로 더 조사할까요? (Step 7)", "원인을조사할까요?"):
        assert not show_guard.EXPLORE_Q.search(q), q
    assert shown.REPORT_CORE.match("- 조사 결론 (LLM, 인용·형식 확인): x")


# --- 11/25 리뷰 고침(조각 ② 판정, R-02~R-27) ---------------------------------------------------------------------
# 틀린 결론이 통과하던 입력과, 지침대로 쓴 맞는 결론이 떨어지던 입력(사내 모델이 흔히 쓰는 모양)을 남긴다

def _copy(job: Path, lines) -> None:
    """마스킹 사본(`logs-masked/radio.log`)과 analysis.json `logs.masked` 기록."""
    (job / "logs-masked").mkdir(exist_ok=True)
    (job / "logs-masked" / "radio.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    a["logs"] = {**a["logs"], "masked": {"dir": "logs-masked", "files": ["radio.log"], "skipped": []}}
    (job / "analysis.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")


def _rec(job: Path) -> dict:
    return json.loads((job / "check-output.json").read_text(encoding="utf-8"))["explore"]


ABSENT_ROWS = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
               "| 2 | 인증 실패 뒤 SETUP을 다시 보낸다 | CP 내부 | spec:x | 없음(찾은 곳: logs-masked 15:10:02 뒤) | false |"]
ABSENT = ("찾았는데 없음:", "- `SETUP_DATA_CALL` 재요청 — logs-masked 15:10:02 뒤 grep")
ISO_Q1 = "2026-09-20T15:10:01.200Z host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"
TAIL = "2026-09-20T15:16:00.000Z host datad[9]: heartbeat"     # 사본이 실패 뒤 몇 분을 담게(지적 2: 짧은 로그의 '없음'은 미관측)


def test_r02_unrelated_true_quotes_and_absent_observation_is_not_identified(tmp_path, capsys):
    """R-02: "달이 파랗다" 가설 + 무관한 진짜 인용 2줄 + 관측 `없음` → 통과하던 것. 가장 이른 false 단계의 관측이 원문 확인 인용도
    셀 수 있는 `찾았는데 없음`도 아니면 첫 어긋남 실패, 형식 경고가 그 칸을 가리킨다."""
    rows = ["| 1 | 달이 파랗게 빛난다 | AP 내부 | spec:x | 없음 | false |"]
    data, inv = _run(_job(tmp_path), _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=rows, claim="단계 1 — 달이 파랗지 않음",
                                          head="달이 파랗다"), capsys)
    assert inv["status"] == "insufficient_evidence" and _failed(inv) == ["첫 어긋남"], inv["gate"]
    assert any("단계 1" in w and "관측" in w and "찾았는데 없음" in w for w in data["format_warnings"]), data


def test_r02_absence_counted_zero_after_reference_passes_and_found_word_fails(tmp_path, capsys):
    """R-02 (나): 관측 `없음` + `찾았는데 없음` 낱말이 사본에서 기준 시각 뒤 0건이면 통과(기준 앞 줄은 세지 않는다), 있으면 실패하고 건수."""
    job = _job(tmp_path / "zero")
    _copy(job, [ISO_Q1, TAIL])                                # 낱말은 기준(15:10:02) 앞 줄만
    _data, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    assert inv["status"] == "identified", inv["gate"]
    job = _job(tmp_path / "found")
    _copy(job, [ISO_Q1, "2026-09-20T15:10:05.000Z host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL retry 1"])
    _data, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "1건" in inv["gate"][1]["why"], inv["gate"]
    job = _job(tmp_path / "nocopy")         # 사본 없음: 고른 타임라인으로 대신 세지 않는다(지적 2 (a), 전에는 identified)
    _data, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "사본이 없어" in inv["gate"][1]["why"], inv["gate"]


def test_r03_fabricated_quote_in_first_check_blocks_identified_on_recheck(tmp_path, capsys):
    """R-03: 첫 검사에 지어낸 인용(+형식 경고) → 그 줄만 빼고 다시 검사해도 통과 못 한다."""
    from tests.test_check_output import FAKE
    job = _job(tmp_path)
    data, _inv = _run(job, _out(quotes=(Q1, "15:10:09.000 p0 E ofonod " + FAKE, Q_AFTER), claim="단계 3 — x"), capsys)
    assert data["fabricated"] == 1 and data["format_warnings"]
    _data, inv = _run(job, _out(), capsys)
    assert _failed(inv) == ["인용 원문"] and inv["gate"][0]["why"].startswith("앞 검사에 원문에 없는 인용 1"), inv["gate"]


def test_r03_cause_layer_field_is_optional_no_warning():
    """R-03: `원인 층`은 선택 칸이고 기대는 게이트가 없다 — 없다고 경고하지 않는다(다시 검사가 늘 열리던 것)."""
    from common import evidence
    from triagelib import output
    fields = evidence.parse_explore(_out())
    assert fields["hyps"][0]["원인 층"] is None and output._chain_warnings(fields, True) == []


def test_r04_bsd_syslog_and_zoneless_iso_quotes_count_for_gates_4_and_6(tmp_path, capsys):
    """R-04: oFono BSD syslog·BusyBox·시간대 없는 ISO 모양 인용의 시각·태그를 게이트 4·6이 읽고, 관측 칸의 그 모양 줄도 인용으로 센다."""
    shapes = {"bsd": ("Sep 20 15:10:01.200 host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM",
                      "Sep 20 15:10:03.400 host datad[9]: network manager daemon state=disconnected reason=pdn_reject"),
              "busybox": ("Sep 20 15:10:01.200 host daemon.err vrild[7]: RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM",
                          "Sep 20 15:10:03.400 host daemon.info datad[9]: network manager daemon state=disconnected reason=pdn_reject"),
              "iso": ("2026-09-20T15:10:01.200 host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM",
                      "2026-09-20T15:10:03.400 host datad[9]: network manager daemon state=disconnected reason=pdn_reject")}
    for name, (q1, q_after) in shapes.items():
        job = _job(tmp_path / name)
        _copy(job, [q1, q_after])
        rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
                "| 2 | SETUP 응답이 성공 | CP 내부 | spec:3GPP 24.301 | " + q1 + " | false |"]
        data, inv = _run(job, _out(quotes=(q1, q_after), rows=rows), capsys)
        assert data["fabricated"] == 0 and data["quotes"] == 4, (name, data)          # 관측 칸 2줄도 인용
        assert inv["status"] == "identified", (name, inv["gate"])


def test_r05_quote_over_field_limit_is_clipped_not_dropped(tmp_path, capsys):
    """R-05: 768바이트 넘는 사본 줄을 그대로 인용해도 출력 전체를 버리지 않는다 — 앞부분 + `…`로 대조, 리포트 줄도 앞부분만."""
    long_line = "2026-09-20T15:10:03.500Z host datad[9]: dump " + " ".join(f"apn{i}=internet.example" for i in range(60))
    job = _job(tmp_path)
    _copy(job, [long_line])
    data, inv = _run(job, _out(quotes=(Q1, long_line)), capsys)
    assert data["fabricated"] == 0 and inv["status"] == "identified", (data, inv["gate"])
    line = next(r for r in (job / "report.md").read_text(encoding="utf-8").split("\n") if r.startswith("  - 가설 1"))
    assert " …" in line and long_line not in line


def test_r06_rule_and_module_basis_found_only_in_masked_copy(tmp_path, capsys):
    """R-06: 규칙 제안·[모듈] 줄의 근거가 사본에만 있어도(타임라인 밖) 사본 대조로 확인돼 실린다."""
    basis = "policy table refreshed for interface rmnet_data9 entries=12"
    job = _job(tmp_path)
    _copy(job, [ISO_Q1, f"2026-09-20T15:10:04.000Z host datad[9]: {basis}"])
    extra = ("규칙 제안:", f"- [이슈 DB] add-parser-rule file=tags.yaml rule={{tag: datad}} — 근거: {basis}",
             f"- [모듈] android/data 층 경로 — 정책 표 갱신 줄부터 본다 — 근거: {basis}")
    _run(job, _out(extra=extra), capsys)
    rec = _rec(job)
    assert rec["rules"] == 2 and rec["module_lines"] == [1] and "rules_dropped" not in rec, rec


def test_r07_o_x_verdicts_and_cp_abbreviation_read_as_list_values(tmp_path, capsys):
    """R-07: 일치 칸 O/X, 기대 주체 `CP`·`AP`(뜻이 하나인 줄임)를 읽는다."""
    rows = ["| 1 | SETUP 요청이 나간다 | AP | log:15:10:00 | " + Q0 + " | O |",
            "| 2 | SETUP 응답이 성공 | CP | spec:x | " + Q1 + " | X |"]
    data, inv = _run(_job(tmp_path), _out(rows=rows), capsys)
    assert inv["status"] == "identified" and "format_warnings" not in data, (inv["gate"], data)
    from common import evidence
    assert [evidence._verdict(v) for v in ("○", "×", "아니오", "아니요 — 재요청 없음", "ok?")] == ["true", "false", "false", "false", "?"]


def test_r07_unreadable_subject_or_verdict_warning_points_at_the_cell(tmp_path, capsys):
    """R-07: 기대 주체가 목록 밖(`모뎀(CP)` — 모호한 줄임은 읽지 않는다)·머리 행 없음·일치 칸 못 읽음 → 형식 경고가 그 칸을 가리킨다."""
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | SETUP 응답이 성공 | 모뎀(CP) | spec:x | " + Q1 + " | false |"]
    data, inv = _run(_job(tmp_path / "a"), _out(rows=rows), capsys)
    assert _failed(inv) == ["책임 층"] and any("단계 2" in w and "`모뎀(CP)`" in w for w in data["format_warnings"]), data
    data, inv = _run(_job(tmp_path / "b"), _out(table=""), capsys)               # 머리 행 없음(6열 자료 행)
    assert any("단계 2" in w and "`기대 주체`" in w for w in data["format_warnings"]), data
    rows[1] = rows[1].replace("모뎀(CP)", "CP 내부").replace("| false |", "| 아님 |")
    data, inv = _run(_job(tmp_path / "c"), _out(rows=rows), capsys)
    assert any("단계 2" in w and "`일치`" in w for w in data["format_warnings"]), data


def test_r08_outer_gate_reasons_split_marker_missing_vs_quote_missing(tmp_path, capsys):
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | SETUP 응답이 성공 | CP 내부 | spec:x | " + Q_W + " | false |"]
    _data, inv = _run(_job(tmp_path / "a"), _out(quotes=(Q_W, Q_AFTER), rows=rows), capsys)
    assert _failed(inv) == ["외부 근거"] and inv["gate"][5]["why"] == "결론 쪽(CP) 태그 줄 인용 없음"
    _data, inv = _run(_job(tmp_path / "b", cp_mark=False), _out(), capsys)
    assert _failed(inv) == ["외부 근거"] and inv["gate"][5]["why"] == "사내 태그 설정에 CP/망 표시 없음(설정 전)"


def test_r09_identified_investigation_accepts_first_check_and_trap_lines(tmp_path, capsys):
    """R-09 결정 2: 판단은 보류(조사 모드)여도 이번 조사 결론이 identified면 첫 점검·함정 줄을 받는다. 아니면 빼고 이유는 원인 미확정."""
    rules = [f"[모듈] android/data {slot} — 한 줄 — 근거: {Q_AFTER}" for slot in ("첫 점검", "함정", "층 경로")]
    ok = _job(tmp_path / "ok")
    _run(ok, _out(extra=("규칙 제안:", *[f"- {r}" for r in rules])), capsys)
    assert _rec(ok)["investigation"]["status"] == "identified" and _rec(ok)["module_lines"] == [1, 2, 3]
    low = _job(tmp_path / "low")
    _run(low, _out(quotes=(Q1,), extra=("규칙 제안:", *[f"- {r}" for r in rules], "- [모듈] 형식 틀림")), capsys)
    rec = _rec(low)
    assert rec["module_lines"] == [3] and rec["rules_dropped"] == 3 and rec["rules_dropped_why"] == {"형식": 1, "원인 미확정": 2}
    text = (low / "report.md").read_text(encoding="utf-8")
    assert "  - 탐색 출력의 제안 3개를 뺐다 — 형식 1 · 원인 미확정(첫 점검·함정) 2" in text


def test_r11_jira_reads_investigation_from_check_output_record_not_analysis(tmp_path, capsys):
    """R-11: analysis.json은 모델이 고쳐 쓸 수 있다 — Jira 본문은 check-output 기록의 investigation을 쓴다."""
    job = _job(tmp_path)
    _run(job, _out(quotes=(Q1,)), capsys)                    # 근거 부족
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    a["investigation"] = {**a["investigation"], "status": "identified", "gate": [{**g, "ok": True} for g in a["investigation"]["gate"]]}
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    cause = [i["text"] for i in issue_post.build(fake, a, None, None, set())[0]["CAUSE"]]
    assert cause[0].startswith("분류: 후보 없음") and any(t.startswith("조사 결론 (LLM, 근거 부족): ") for t in cause)


def test_r15_no_confirmed_reference_uses_earliest_quote_not_pass(tmp_path, capsys):
    """R-15: 확정 기준 시각이 없으면 "해당 없음" 통과가 아니라 가장 이른 원문 확인 인용 시각 뒤 줄·구간이 있어야 한다."""
    rows = ["| 1 | SETUP 응답이 성공 | CP 내부 | spec:x | " + Q1 + " | false |"]
    for name, quotes, want in (("one", (Q1,), ["실패 뒤 흔적"]), ("two", (Q1, Q_AFTER), [])):
        job = _job(tmp_path / name)
        (job / "explore-input.json").write_text(json.dumps({"limit": 200}), encoding="utf-8")
        _data, inv = _run(job, _out(quotes=quotes, rows=rows, claim="단계 1 — CP 인증 실패"), capsys)
        assert _failed(inv) == want, (name, inv["gate"])


def test_r16_normal_conclusion_is_marked_not_asked_for_more_logs(tmp_path, capsys):
    """R-16: 가장 유력이 정상이고 정상 근거 줄이 원문 확인이면 investigation.normal, 문구는 "정상 동작으로 보임"(로그 더 확인 안내 없음)."""
    rows = ["| 1 | 재시도 뒤 연결된다 | AP 내부 | log:15:10:03 | " + Q_AFTER + " | true |"]
    job = _job(tmp_path)
    _data, inv = _run(job, _out(head="정상(설계상 정상 동작) — 거절 뒤 망 관리자가 상태를 정리", quotes=(Q_AFTER,), rows=rows, claim="없음"),
                      capsys)
    assert inv["normal"] is True and inv["status"] == "insufficient_evidence"
    text = "\n".join(_cause_rows(job))
    assert "- 조사 결론 (LLM, 정상 동작으로 보임): " in text and "원인 조사 대상 아님" in text and "로그를 더 확인" not in text
    _data, inv = _run(_job(tmp_path / "plain"), _out(), capsys)
    assert "normal" not in inv


def test_r17_elapsed_time_in_hypothesis_head_alone_needs_no_recompute(tmp_path, capsys):
    """R-17: 숫자 메커니즘 대상은 가장 이른 false 단계의 `기대` 칸뿐 — 가설 머리의 "40초 뒤"만으로 실패하지 않는다."""
    _data, inv = _run(_job(tmp_path), _out(head="vrild가 attach 40초 뒤 SETUP_DATA_CALL을 인증 실패로 끝냄"), capsys)
    assert inv["status"] == "identified" and inv["gate"][4]["why"].startswith("해당 없음"), inv["gate"]


def test_r24_same_as_rule_top_only_when_candidate_check_says_match(tmp_path, capsys):
    """R-24: 원인 글에 ID가 들었다는 것만으로 "규칙 1위와 같음"이 아니다 — `후보 확인`에서 그 ID가 `맞음`일 때만."""
    top = {**OK_KEYS["candidates"][0], "C": 0}
    head = "DATA-001-01이 아니라 vrild가 SETUP_DATA_CALL을 인증 실패로 끝냄"
    job = _job(tmp_path / "a", cands=[top])
    _run(job, _out(head=head), capsys)
    rows = _cause_rows(job)
    assert "같음" not in rows[0] and any(r.startswith("  - 관측된 규칙 일치: data > DATA-001 > DATA-001-01") for r in rows)
    job = _job(tmp_path / "b", cands=[top])
    _run(job, _out(head=head, extra=("후보 확인:", f"- DATA-001-01: 맞음 — {Q1}")), capsys)
    assert _cause_rows(job)[0].endswith("(규칙 1위 DATA-001-01와 같음)")


def test_r27_unreadable_top_pick_in_investigate_mode_is_a_format_warning(tmp_path, capsys):
    data, _inv = _run(_job(tmp_path), _out(extra=("가장 유력: 둘째 가설",)), capsys)
    assert any("가장 유력" in w for w in data["format_warnings"]), data


def test_r02_label_says_quotes_and_format_checked_with_one_note(tmp_path, capsys):
    """R-02 결정 1: 표시 `인용·형식 확인` + 설명 한 문장(바로 아래 한 번). 사람이 보는 글에 status 값(identified)을 쓰지 않는다."""
    job = _job(tmp_path)
    _run(job, _out(), capsys)
    rows = _cause_rows(job)
    assert rows[0].startswith("- 조사 결론 (LLM, 인용·형식 확인): ") and "identified" not in rows[0]
    assert rows[1] == ("  - 스크립트가 확인한 것은 인용한 로그 줄이 실제로 있는지와 단계표가 맞는지다. 원인이 맞는지는 사람이 확인한다.")
    assert sum(issuepost.INVESTIGATION_NOTE.strip() in r for r in rows) == 1


# --- 11/25 확인 리뷰 고침(C-1·C-2·C-3b·C-7·C-10) -------------------------------------------------------------------
# 지침 예시대로 쓴 맞는 결론이 떨어지던 입력과, 지어낸 낱말로 통과하던 입력

FAIL_ROWS = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
             "| 2 | CP가 인증 실패로 응답한다 | CP 내부 | log:15:10:01 | " + Q1 + " | true |",
             "| 3 | 인증 실패 뒤 SETUP을 다시 보낸다 | CP 내부 | spec:x | 없음(찾은 곳: logs-masked 15:10:01 뒤) | false |"]


def test_c01_absent_word_counts_only_after_sec_window(tmp_path, capsys):
    """C-1 (가): 기준(15:10:02) 뒤 5초 안 재요청 없음이 맞는데 30분 뒤 다른 요청 한 줄 때문에 떨어지던 것 — 세는 구간은
    [아래 끝, 아래 끝 + explore.after_sec(600)]. 구간 안 줄은 그대로 실패하고 이유에 센 구간을 적는다."""
    job = _job(tmp_path / "far")
    _copy(job, [ISO_Q1, "2026-09-20T15:40:00.000Z host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL apn=internet"])
    _data, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    assert inv["status"] == "identified", inv["gate"]
    assert "15:10:02.000~15:20:02.000" in inv["gate"][1]["why"] and "0건" in inv["gate"][1]["why"], inv["gate"]
    job = _job(tmp_path / "near")
    _copy(job, [ISO_Q1, "2026-09-20T15:19:00.000Z host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL apn=internet"])
    _data, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    # 센 구간은 사본 끝(15:19:00)에서 잘린 끝까지 적는다(지적 2 (c))
    assert _failed(inv) == ["첫 어긋남"] and "15:10:02.000~15:19:00.000" in inv["gate"][1]["why"], inv["gate"]
    assert "1건" in inv["gate"][1]["why"] and "15:10:02.000~15:19:00.000" in "\n".join(_cause_rows(job))


def test_c01_coarse_occurrence_time_uses_latest_prior_step_quote(tmp_path, capsys):
    """C-1 (나): 확정 기준이 발생 시각(15:09:30)뿐이고 실패 줄(15:10:01.2)보다 앞이면 실패 줄 자체가 세지던 것 — 아래 끝은
    가장 이른 false 단계 앞 단계들의 원문 확인 관측 줄 가운데 가장 늦은 시각(그 줄 자체는 세지 않는다). 백틱 없는 낱말·oFono 모양도."""
    for name, extra, q1 in (("tick", ABSENT, Q1), ("bare", ("찾았는데 없음:", "- SETUP_DATA_CALL 재요청 — logs-masked 15:10:01 뒤"), Q1),
                            ("bsd", ABSENT, "Sep 20 15:10:01.200 host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM")):
        job = _job(tmp_path / name)
        (job / "explore-input.json").write_text(json.dumps({"limit": 200, "around": "2026-09-20T15:09:30Z"}), encoding="utf-8")
        _copy(job, [ISO_Q1 if q1 == Q1 else q1, TAIL])
        rows = [r.replace(Q1, q1) for r in FAIL_ROWS]
        _d, inv = _run(job, _out(rows=rows, claim="단계 3 — CP가 재요청하지 않음", extra=extra), capsys)
        assert inv["status"] == "identified", (name, inv["gate"])
        assert "15:10:01.200~15:16:00.000" in inv["gate"][1]["why"], (name, inv["gate"])      # 끝은 사본 끝(TAIL)에서 잘림


def test_c02_made_up_absent_word_is_not_counted_as_absence(tmp_path, capsys):
    """C-2: 로그 어디에도 없는 낱말은 늘 0건이다 — `찾았는데 없음` 낱말은 사본이나 파서 규칙에 있어야 한다."""
    rows = ["| 1 | 달이 파랗게 빛난다 | AP 내부 | spec:x | 없음 | false |"]
    job = _job(tmp_path / "moon")
    _copy(job, [ISO_Q1, TAIL])
    data, inv = _run(job, _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=rows, claim="단계 1 — 달이 파랗지 않음",
                               head="달이 파랗다", extra=("찾았는데 없음:", "- `blue_moon_glow` — 사본 전체 grep")), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "`blue_moon_glow`은 로그·파서 규칙 어디에도 없는 낱말" in inv["gate"][1]["why"], inv["gate"]
    assert any("단계 1" in w for w in data["format_warnings"]), data
    job = _job(tmp_path / "rule")        # 로그엔 없지만 파서 규칙(ril.yaml)에 있는 낱말은 실제 낱말이다
    _copy(job, [ISO_Q1, TAIL])
    _d, inv = _run(job, _out(rows=ABSENT_ROWS, extra=("찾았는데 없음:", "- `DEACTIVATE_DATA_CALL` 요청 — logs-masked 15:10:02 뒤")),
                   capsys)
    assert inv["status"] == "identified", inv["gate"]


def test_c03b_type_only_top_matches_its_cause_in_candidate_check(tmp_path, capsys):
    """C-3b: 1위가 유형만(원인 없음, C=0)이면 그 유형의 원인 ID가 `후보 확인`에서 맞음일 때 규칙 1위와 같음 — 줄에는 그 원인 ID."""
    top = {**OK_KEYS["candidates"][0], "cause": None, "C": 0}
    job = _job(tmp_path / "a", cands=[top])
    _run(job, _out(extra=("후보 확인:", f"- DATA-001-01: 맞음 — {Q1}")), capsys)
    rows = _cause_rows(job)
    assert rows[0].endswith("(규칙 1위 DATA-001-01와 같음)") and not any("관측된 규칙 일치" in r for r in rows), rows
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    assert issue_post.build(fake, a, None, None, set())[0]["CAUSE"][0]["text"].endswith("(규칙 1위 DATA-001-01와 같음)")
    job = _job(tmp_path / "other", cands=[top])            # 다른 유형의 원인은 아니다
    _run(job, _out(extra=("후보 확인:", f"- DATA-0010-01: 맞음 — {Q1}")), capsys)
    assert "같음" not in _cause_rows(job)[0]


def test_c07_quoted_cp_line_without_site_mark_says_check_tag_config(tmp_path, capsys):
    """C-7: Android 기본 벤더 IPC 태그(placeholder `RIL`)만 있고 사내 tags.yaml에 표시가 없는데 실제 CP 줄(vrild)을 인용하면
    "인용 없음"이 아니라 태그 설정을 보라고 적는다. 판정은 그대로(실패)."""
    _data, inv = _run(_job(tmp_path, cp_mark=False, platform="android"), _out(), capsys)
    assert _failed(inv) == ["외부 근거"] and inv["gate"][5]["why"] == "인용한 줄의 태그가 CP 쪽으로 표시돼 있지 않음 — 사내 태그 설정 확인"


def test_c10_jira_skips_investigation_when_explore_output_changed(tmp_path, capsys):
    """C-10: 검사 뒤 explore-output.md가 바뀌면(기록을 손대지 않아도) Jira 본문에 조사 결론을 싣지 않는다."""
    job = _job(tmp_path)
    _run(job, _out(), capsys)
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    assert issue_post.build(fake, a, None, None, set())[0]["CAUSE"][0]["text"].startswith("조사 결론")
    with (job / "explore-output.md").open("a", encoding="utf-8") as f:
        f.write("가설 2: 나중에 손으로 더한 가설\n")
    cause = [i["text"] for i in issue_post.build(fake, a, None, None, set())[0]["CAUSE"]]
    assert not any(t.startswith("조사 결론") for t in cause)


# --- 외부 리뷰 1125(코덱스): 틀린 결론을 통과시키던 빈틈 3건과 eval 지표 --------------------------------------------------
# 리뷰어 각본을 그대로 둔다(고치기 전 코드에서 identified가 나오던 입력). 맞는 결론이 여전히 통과하는 쌍도 둔다.

# 실패(15:10:02) 앞 줄 — 날짜·시간대를 바꿔 적으면 기준 시각 뒤 줄처럼 읽힌다
EARLY = {"iso": "2026-09-20T15:09:50.000Z host datad[9]: link monitor lost carrier on rmnet_data0",
         "logcat": "09-20 15:09:50.000  1000  1001 I datad: link monitor lost carrier on rmnet_data0",
         "logcat_zone": "09-20 15:09:50.000 +0000  1000  1001 I datad: link monitor lost carrier on rmnet_data0",
         "bsd": "Sep 20 15:09:50.000 host datad[9]: link monitor lost carrier on rmnet_data0",
         "busybox": "Sep 20 15:09:50.000 host daemon.info datad[9]: link monitor lost carrier on rmnet_data0"}
FORGED = {"iso": [("2026-09-20T", "2026-09-21T"), ("000Z", "000-09:00")],
          "logcat": [("09-20 ", "09-21 ")], "logcat_zone": [("09-20 ", "09-21 "), ("+0000", "-0900")],
          "bsd": [("Sep 20", "Sep 21")], "busybox": [("Sep 20", "Sep 21")]}


def test_x1_quote_with_changed_date_or_zone_is_not_source_confirmed(tmp_path, capsys):
    """지적 1: 사본 줄의 날짜를 다음 날로, 시간대를 `-09:00`으로 바꿔 인용하면 원문 확인(ok)이었고 실패 앞 줄이 '기준 시각 뒤 줄'로
    세져 identified였다. 날짜·시간대가 맞춘 사본 줄과 다르면 시각을 바꿔 적은 인용과 같은 등급(weak)이고 게이트 4가 떨어진다.
    날짜·시간대까지 사본 줄 그대로 적은 인용은 그대로 ok."""
    for name, line in EARLY.items():
        for k, (old, new) in enumerate(FORGED[name]):
            job = _job(tmp_path / f"{name}{k}")
            _copy(job, [ISO_Q1, line])
            forged = line.replace(old, new)
            assert forged != line
            data, inv = _run(job, _out(quotes=(Q1, forged)), capsys)
            assert data["fabricated"] == 0 and data["weak"] >= 1, (name, forged, data)
            assert inv["status"] == "insufficient_evidence" and "실패 뒤 흔적" in _failed(inv), (name, forged, inv["gate"])
        job = _job(tmp_path / f"{name}-exact")          # 그대로 적은 인용: 원문 확인, 실패 앞 줄이라 게이트 4만 떨어진다
        _copy(job, [ISO_Q1, line])
        data, inv = _run(job, _out(quotes=(Q1, line)), capsys)
        assert data["weak"] == 0 and data["fabricated"] == 0, (name, data)
        assert _failed(inv) == ["실패 뒤 흔적"], (name, inv["gate"])


def test_x1_quote_with_exact_date_after_failure_still_passes(tmp_path, capsys):
    """지적 1 양성: 기준 뒤 사본 줄을 날짜·시간대까지 그대로 인용하면 identified 그대로(logcat·oFono 모양)."""
    after = {"iso": "2026-09-20T15:10:05.000Z host datad[9]: link monitor lost carrier on rmnet_data0",
             "logcat": "09-20 15:10:05.000  1000  1001 I datad: link monitor lost carrier on rmnet_data0",
             "bsd": "Sep 20 15:10:05.000 host datad[9]: link monitor lost carrier on rmnet_data0"}
    for name, line in after.items():
        job = _job(tmp_path / name)
        _copy(job, [ISO_Q1, line])
        data, inv = _run(job, _out(quotes=(Q1, line)), capsys)
        assert data["weak"] == 0 and inv["status"] == "identified", (name, data, inv["gate"])


def test_x1_logcat_quote_with_changed_clock_is_weak_too(tmp_path, capsys):
    """지적 1 곁: logcat 모양 인용은 시분초를 바꿔 적어도 ok였다(앞머리를 행 머리로 읽지 못해 시각 대조를 건너뜀) — 이제 weak."""
    job = _job(tmp_path)
    _copy(job, [ISO_Q1, EARLY["logcat"]])
    data, inv = _run(job, _out(quotes=(Q1, EARLY["logcat"].replace("15:09:50", "15:19:50"))), capsys)
    assert data["weak"] == 1 and "실패 뒤 흔적" in _failed(inv), (data, inv["gate"])


# 지적 2: 300초 뒤 재시도를 기대 — 아래 끝(15:10:02) 뒤 사본이 얼마나 있느냐
RETRY_ROWS = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
              "| 2 | 인증 실패 뒤 300초(299999ms) 뒤 SETUP을 다시 보낸다 | CP 내부 | spec:x | 없음(찾은 곳: logs-masked 15:10:02 뒤) "
              "| false |"]
RETRY_MECH = "메커니즘 재계산: 15:10:02 + 299999ms = 15:15:02 → 고치면 결과가 뒤집히나: 예"


def test_x2_absence_needs_log_covering_expected_time(tmp_path, capsys):
    """지적 2 (b): 약 3초 분량 사본에 "300초 뒤 재시도가 없다"를 넣으면 0건이라 통과했다 — 로그가 아래 끝 + 필요 시간(300초)을
    담지 않으면 미관측으로 실패. 로그가 그 뒤까지 있고 낱말이 없으면 통과하고 why에 센 구간(로그 끝에서 잘린 끝)을 적는다."""
    short = ["2026-09-20T15:10:00.100Z host ofonod[3]: attach requested", ISO_Q1,
             "2026-09-20T15:10:03.400Z host datad[9]: state=disconnected"]
    job = _job(tmp_path / "short")
    _copy(job, short)
    _d, inv = _run(job, _out(rows=RETRY_ROWS, extra=(*ABSENT, RETRY_MECH)), capsys)
    assert _failed(inv) == ["첫 어긋남"], inv["gate"]
    assert "미관측" in inv["gate"][1]["why"] and "1.4초" in inv["gate"][1]["why"], inv["gate"]
    job = _job(tmp_path / "long")
    _copy(job, [*short, "2026-09-20T15:16:00.000Z host datad[9]: heartbeat"])
    _d, inv = _run(job, _out(rows=RETRY_ROWS, extra=(*ABSENT, RETRY_MECH)), capsys)
    assert inv["status"] == "identified", inv["gate"]
    assert "15:10:02.000~15:16:00.000" in inv["gate"][1]["why"] and "0건" in inv["gate"][1]["why"], inv["gate"]


def test_x2_absence_window_grows_to_expected_time(tmp_path, capsys):
    """지적 2 (b): 기대가 900초면 세는 구간도 900초(after_sec 600으로 자르지 않는다) — 700초 뒤 재요청이 있으면 실패."""
    rows = [r.replace("300초(299999ms)", "900초") for r in RETRY_ROWS]
    mech = "메커니즘 재계산: 15:10:02 + 900초 = 15:25:02 → 고치면 결과가 뒤집히나: 예"
    job = _job(tmp_path)
    _copy(job, [ISO_Q1, "2026-09-20T15:21:42.000Z host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL apn=internet",
                "2026-09-20T15:30:00.000Z host datad[9]: heartbeat"])
    _d, inv = _run(job, _out(rows=rows, extra=(*ABSENT, mech)), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "15:10:02.000~15:25:02.000" in inv["gate"][1]["why"], inv["gate"]
    assert "1건" in inv["gate"][1]["why"], inv["gate"]


def test_x2_absence_without_masked_copy_is_not_counted(tmp_path, capsys):
    """지적 2 (a): 사본이 없으면 고른 타임라인 행에서 0건을 셌다 — 이제 '없음'을 셀 수 없어 실패(건너뛴 검사를 통과로 두지 않음)."""
    _d, inv = _run(_job(tmp_path), _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "사본이 없어" in inv["gate"][1]["why"], inv["gate"]


def test_x2_no_number_expectation_needs_ten_seconds_of_log(tmp_path, capsys):
    """지적 2 (b): 기대 칸에 시간 숫자가 없으면 아래 끝 뒤 10초(경험값)는 로그가 있어야 한다."""
    for end, ok in (("15:10:09.000", False), ("15:10:12.500", True)):
        job = _job(tmp_path / end.replace(":", ""))
        _copy(job, [ISO_Q1, f"2026-09-20T{end}Z host datad[9]: heartbeat"])
        _d, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
        assert (inv["status"] == "identified") is ok, (end, inv["gate"])


def test_x3_numeric_expectation_needs_numbers_and_explicit_yes(tmp_path, capsys):
    """지적 3: 숫자 기대에 '계산할 자료 없음'(답 없음)이 통과했다 → 답 없음 실패, 숫자 없는 계산 + 예도 실패, 숫자 + 예는 통과."""
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | 5초 안에 응답이 성공 | CP 내부 | spec:x | " + Q1 + " | false |"]
    cases = (("메커니즘 재계산: 계산할 자료 없음", "재계산 답 없음(예/아니오)"),
             ("메커니즘 재계산: 계산할 자료 없음 → 고치면 결과가 뒤집히나: 예", "재계산에 계산 내용(숫자) 없음"),
             ("메커니즘 재계산: 01.2-00.1 = 1.1초 → 고치면 결과가 뒤집히나: 예", None))
    for k, (mech, why) in enumerate(cases):
        _d, inv = _run(_job(tmp_path / str(k)), _out(rows=rows, extra=(mech,)), capsys)
        assert _failed(inv) == ([] if why is None else ["숫자 메커니즘"]), (mech, inv["gate"])
        assert why is None or inv["gate"][4]["why"] == why, (mech, inv["gate"])


def test_x3_explicit_no_fails_even_without_numeric_expectation(tmp_path, capsys):
    """지적 3: 기대 칸에 숫자가 없어도 '고쳐도 안 뒤집힌다: 아니오'를 적으면 그 가설은 원인이 아니다 — 실패. 답 없으면 해당 없음 통과."""
    _d, inv = _run(_job(tmp_path / "no"), _out(extra=("메커니즘 재계산: 재시도 간격 그대로 → 고치면 결과가 뒤집히나: 아니오",)), capsys)
    assert _failed(inv) == ["숫자 메커니즘"] and inv["gate"][4]["why"] == "재계산 답이 아니오(고쳐도 안 뒤집힘)", inv["gate"]
    _d, inv = _run(_job(tmp_path / "none"), _out(), capsys)
    assert _failed(inv) == [] and inv["gate"][4]["why"] == "해당 없음(숫자 기대 없음)", inv["gate"]


def test_x4_identified_correct_needs_cause_line_cited():
    """지적 4: 층만 맞고 원인 줄을 인용하지 않은 통과는 identified_correct가 아니라 identified_layer_only."""
    sys.path.insert(0, str(REPO / "tools"))
    import investigate_eval
    case = {"layer": "CP 내부", "cause_line": "RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"}
    analysis = {"investigation": {"status": "identified", "layer": "CP 내부"}}
    cited = investigate_eval.score_case(case, _out(), analysis)
    assert cited["identified_correct"] and not cited["identified_layer_only"]
    rows = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | SETUP 응답이 성공 | CP 내부 | spec:x | " + Q_W + " | false |"]
    bare = investigate_eval.score_case(case, _out(quotes=(Q0, Q_AFTER), rows=rows), analysis)
    assert not bare["cause_cited"] and not bare["identified_correct"] and bare["identified_layer_only"], bare


# --- 확인 리뷰 1125(C-1~C-4, 꼬리 한 줄): 고치기 전 코드에서 통과하던 틀린 결론 ------------------------------------------

NUM_ROWS = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | 5초 안에 응답이 성공 | CP 내부 | spec:x | " + Q1 + " | false |"]


def test_c1_yes_followed_by_hangul_is_not_an_answer(tmp_path, capsys):
    """C-1: `예상하기 어려움`의 `예`를 답 `예`로 읽어 숫자 기대 재계산이 통과했다. `예.`·`예,`·`예(…)`·`예 —`·줄 끝 `예`는 답이다."""
    bad = "메커니즘 재계산: 15:10:01 한 줄 → 고치면 결과가 뒤집히나: 예상하기 어려움(15:10:01 한 줄뿐)"
    _d, inv = _run(_job(tmp_path / "bad"), _out(rows=NUM_ROWS, extra=(bad,)), capsys)
    assert _failed(inv) == ["숫자 메커니즘"] and inv["gate"][4]["why"] == "재계산 답 없음(예/아니오)", inv["gate"]
    for k, tail in enumerate(("예.", "예, 1.1초면 맞음", "예(1.1초)", "예 — 1.1초", "예")):
        mech = f"메커니즘 재계산: 01.2-00.1 = 1.1초 → 고치면 결과가 뒤집히나: {tail}"
        _d, inv = _run(_job(tmp_path / f"ok{k}"), _out(rows=NUM_ROWS, extra=(mech,)), capsys)
        assert _failed(inv) == [], (tail, inv["gate"])


def test_c2_hour_and_millisecond_units(tmp_path, capsys):
    """C-2: `1시간`은 시간 단위가 아니라 필요 시간이 10초였다 — 실패 뒤 15초 사본으로 '1시간 안에 재요청 없음'이 통과. 이제 3600초."""
    from triagelib import output
    rows = [r.replace("인증 실패 뒤 SETUP을 다시 보낸다", "1시간 안에 SETUP 재요청") for r in ABSENT_ROWS]
    mech = "메커니즘 재계산: 15:10:02 + 1시간 = 16:10:02 → 고치면 결과가 뒤집히나: 예"
    job = _job(tmp_path)
    _copy(job, [ISO_Q1, "2026-09-20T15:10:17.000Z host datad[9]: heartbeat"])
    _d, inv = _run(job, _out(rows=rows, extra=(*ABSENT, mech)), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "필요 3600초" in inv["gate"][1]["why"], inv["gate"]
    want = {"1시간": 3600, "2 hours": 7200, "1.5h": 5400, "3 hrs": 10800, "500 milliseconds": 0.5, "250밀리초": 0.25,
            "10 s1 뒤": output.ABSENT_MIN_SEC, "2h1": output.ABSENT_MIN_SEC, "5 m 거리": output.ABSENT_MIN_SEC}
    assert {k: output._need_sec(k) for k in want} == want
    rx = output.NUM_UNIT_RX
    assert all(rx.search(t) for t in ("1시간", "2 hours", "1.5h", "3 hrs", "500 milliseconds", "250밀리초"))
    assert not any(rx.search(t) for t in ("10 s1", "2h1", "5 m 거리"))


def test_c3_no_lower_end_still_needs_log_long_enough(tmp_path, capsys):
    """C-3: 기준 시각도 앞 단계 인용도 없으면(첫 false가 단계 1) 분석 범위 전체를 세는데, 3초 분량 사본으로 '300초 안에 DEACTIVATE
    없음'이 통과했다 — 사본 길이가 필요 시간보다 짧으면 미관측. 길면 그대로 통과."""
    rows = ["| 1 | 300초 안에 DEACTIVATE를 보낸다 | AP 내부 | spec:x | 없음(찾은 곳: logs-masked 전체) | false |"]
    extra = ("찾았는데 없음:", "- `DEACTIVATE_DATA_CALL` 요청 — logs-masked 전체 grep",
             "메커니즘 재계산: 300초 타이머 = 300000ms → 고치면 결과가 뒤집히나: 예")
    for name, lines, ok in (("short", ["2026-09-20T15:10:00.100Z host ofonod[3]: attach requested", ISO_Q1,
                                       "2026-09-20T15:10:03.400Z host datad[9]: state=disconnected"], False),
                            ("long", ["2026-09-20T15:10:00.100Z host ofonod[3]: attach requested", ISO_Q1, TAIL], True)):
        job = _job(tmp_path / name)
        (job / "explore-input.json").write_text(json.dumps({"limit": 200}), encoding="utf-8")      # 확정 기준 없음
        _copy(job, lines)
        _d, inv = _run(job, _out(layer="AP 내부", rows=rows, claim="단계 1 — DEACTIVATE 안 보냄", extra=extra), capsys)
        assert ("첫 어긋남" not in _failed(inv)) is ok, (name, inv["gate"])
        assert ok or ("3.3초 분량뿐" in inv["gate"][1]["why"] and "필요 300초" in inv["gate"][1]["why"]), inv["gate"]


def test_tail_newline_is_not_counted_as_a_line(tmp_path, capsys):
    """꼬리 한 줄: 파일 끝 개행을 한 줄로 세어, 시각 줄 뒤 시각 없는 줄 1999줄이면 끝 시각을 못 읽었다."""
    job = _job(tmp_path)
    _copy(job, [ISO_Q1, TAIL, *(f"    dump word{i}" for i in range(1999))])
    _d, inv = _run(job, _out(rows=ABSENT_ROWS, extra=ABSENT), capsys)
    assert inv["status"] == "identified", inv["gate"]


DAY_BEFORE = "2026-09-19T15:10:30.000Z host datad[9]: link monitor lost carrier on rmnet_data0"
ROW_Q = "15:10:30.000 - - datad link monitor lost carrier on rmnet_data0"


def test_c4_row_quote_of_another_day_line_is_not_after_failure(tmp_path, capsys):
    """C-4: 행 모양 인용은 시각만 있어 전날 사본 줄도 실패 당일 시각으로 읽혀 '실패 뒤 흔적'이 통과했다 — 머리·메시지가 맞는 사본
    줄이 있는데 같은 초인 줄이 없으면 그 시각을 쓰지 않는다. A5부터 그 인용은 약함(전에는 ok 그대로). 같은 메시지가 당일 그 초에도 있으면 통과."""
    job = _job(tmp_path / "other")
    _copy(job, [ISO_Q1, DAY_BEFORE])
    data, inv = _run(job, _out(quotes=(Q1, ROW_Q)), capsys)
    assert data["weak"] == 1 and data["fabricated"] == 0, data
    assert _failed(inv) == ["실패 뒤 흔적"], inv["gate"]
    job = _job(tmp_path / "same")
    _copy(job, [ISO_Q1, DAY_BEFORE, DAY_BEFORE.replace("09-19", "09-20")])
    _d, inv = _run(job, _out(quotes=(Q1, ROW_Q)), capsys)
    assert inv["status"] == "identified", inv["gate"]


def test_c4_row_time_matches_copy_line_across_timezone():
    """C-4: 행(UTC) 시각과 사본 줄(현지 시각, 작업 tz로 환산)이 같은 순간이면 그대로 쓴다 — 다른 날 줄만 있으면 None."""
    from triagelib import output
    output._raw_ready()
    ev = {"input": {"tz": "Asia/Seoul", "window": {"start": "2026-09-20T15:00:00Z", "end": "2026-09-20T15:30:00Z"}}}
    q = "15:10:30.000 p0 I datad link monitor lost carrier on rmnet_data0"
    line = "{} 00:10:30.000  1000  1001 I datad: link monitor lost carrier on rmnet_data0\n"
    assert output._quote_at(q, ev, [line.format("09-21")])[0] == output._quote_ts(q, ev) is not None
    assert output._quote_at(q, ev, [line.format("09-20")])[0] is None
    assert output._quote_at(q, ev, ["unrelated line\n"]) == (output._quote_ts(q, ev), None)        # 맞는 줄 없음: 그대로


# --- 반입 8 외부 리뷰(8d82caee 재현): 다른 날 관측 줄(A5)·다른 사본 끝(A4) — 짝은 날짜·파일만 정상으로 바꾼 같은 입력 -----------------

def _copies(job: Path, files: dict) -> None:
    """마스킹 사본 여러 개(`{이름: 줄들}`)와 analysis.json `logs.masked` 기록."""
    (job / "logs-masked").mkdir(exist_ok=True)
    for name, lines in files.items():
        (job / "logs-masked" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    a["logs"] = {**a["logs"], "masked": {"dir": "logs-masked", "files": list(files), "skipped": []}}
    (job / "analysis.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")


DAY_ROWS = ["| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | " + Q0 + " | true |",
            "| 2 | 링크가 유지된다 | AP 내부 | spec:x | " + ROW_Q + " | false |"]


def test_a5_failing_step_observation_from_another_day_is_not_a_divergence(tmp_path, capsys):
    """A5: 가장 이른 false 단계 관측에 전날 줄을 행 모양(`15:10:30 …`)으로 넣고 당일 후속 줄을 함께 인용하면 모든 게이트를 통과했다
    — 그 관측은 사본에서 다른 날에만 있어 원문 확인(ok)이 아니고(약함) 게이트 2가 그 이유로 실패. 같은 줄이 당일에 있으면 통과."""
    out = _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=DAY_ROWS, claim="단계 2 — 링크가 끊김", head="링크가 끊겨 연결 실패")
    job = _job(tmp_path / "other")
    _copy(job, [ISO_Q1, DAY_BEFORE])
    data, inv = _run(job, out, capsys)
    assert data["weak"] == 1 and _failed(inv) == ["첫 어긋남"], (data, inv["gate"])
    assert "단계 2: 관측 줄이 사본에서는 다른 시각(다른 날)에만 있음" in inv["gate"][1]["why"], inv["gate"]
    job = _job(tmp_path / "same")
    _copy(job, [ISO_Q1, DAY_BEFORE.replace("09-19", "09-20")])
    data, inv = _run(job, out, capsys)
    assert data["weak"] == 0 and inv["status"] == "identified", (data, inv["gate"])


RADIO = ["2026-09-20T15:10:00.100Z host ofonod[3]: attach requested", ISO_Q1,
         "2026-09-20T15:10:03.400Z host datad[9]: state=disconnected"]


def test_a4_absence_end_is_measured_in_copies_where_the_word_appears(tmp_path, capsys):
    """A4: 낱말(SETUP_DATA_CALL)이 나오는 radio 사본은 실패 뒤 1.4초에서 끝나는데 다른 사본(main)이 길어 '300초 뒤 재요청 없음'이
    통과했다 — 끝은 낱말(또는 그 줄의 태그)이 나오는 사본으로 잰다. radio가 길면(또는 같은 태그 사본이 길면) 통과."""
    extra = (*ABSENT, RETRY_MECH)
    for name, files, ok in (("main-long", {"radio.log": RADIO, "main.log": [TAIL]}, False),
                            ("radio-long", {"radio.log": [*RADIO, TAIL.replace("datad[9]", "vrild[7]")], "main.log": [TAIL]}, True),
                            ("same-tag", {"radio.log": RADIO, "radio2.log": ["2026-09-20T15:16:00.000Z host vrild[7]: heartbeat"]},
                             True)):
        job = _job(tmp_path / name)
        _copies(job, files)
        _d, inv = _run(job, _out(rows=RETRY_ROWS, extra=extra), capsys)
        assert (inv["status"] == "identified") is ok, (name, inv["gate"])
        assert ok or "미관측" in inv["gate"][1]["why"], (name, inv["gate"])


def test_a4_word_only_in_rules_uses_all_copies_and_says_so(tmp_path, capsys):
    """A4: 낱말이 어느 사본에도 없고 파서 규칙에만 있으면(아래 끝 줄의 사본도 모름) 지금처럼 모든 사본으로 재고 이유 글에 적는다."""
    job = _job(tmp_path)
    _copies(job, {"radio.log": [ISO_Q1], "main.log": [TAIL]})
    _d, inv = _run(job, _out(rows=ABSENT_ROWS, extra=("찾았는데 없음:", "- `DEACTIVATE_DATA_CALL` 요청 — logs-masked 15:10:02 뒤")),
                   capsys)
    assert inv["status"] == "identified" and "전체 사본" in inv["gate"][1]["why"], inv["gate"]


# --- 반입 8 A1~A3: 구간 파일 날짜·규칙 1위와 같음·`예입니다` --------------------------------------------------------------

def test_g2_window_end_time_comes_from_the_file_head_not_a_guess(tmp_path, capsys):
    """G-2(A1을 바꿈): 구간 파일 줄은 날짜가 없다 — 날짜를 추측(분석 범위 날짜·중심에 가까운 날)하지 않고 window가 구간 파일 머리에
    적은 날짜 포함 끝 시각만 쓴다. `--grep` 구간처럼 중심과 12시간 넘게 떨어진 전날 줄이 끝이면 실패, 당일이면 통과, 머리가 없는 옛
    구간 파일은 시각을 몰라 세지 않는다."""
    rows = ("15:10:01.900 p0 E hiddend carrier link lost", "23:50:05.000 p0 I hiddend carrier link back")
    for name, last, want in (("day-before", "2026-09-19T23:50:05.000Z", ["실패 뒤 흔적"]),
                             ("same-day", "2026-09-20T23:50:05.000Z", []), ("old", None, ["실패 뒤 흔적"])):
        job = _job(tmp_path / name)
        _window(job, rows=rows, last=last)
        _data, inv = _run(job, _out(quotes=(Q1,)), capsys)
        assert _failed(inv) == want, (name, inv["gate"])
        assert name != "old" or "옛 구간 파일 — window를 다시 받으면 됨" in inv["gate"][3]["why"], inv["gate"]


def test_a2_same_as_rule_top_needs_source_confirmed_basis(tmp_path, capsys):
    """A2: `후보 확인`의 근거가 `찾았는데 없음`뿐이거나 약한(weak) 인용이어도 "규칙 1위와 같음"이 붙었다 — 근거 인용이 원문 확인(ok)일
    때만. 같은 항목에 ok 인용이면 붙는다."""
    top = {**OK_KEYS["candidates"][0], "C": 0}
    weak = Q1.replace("15:10:01.200", "15:10:01.900")         # 메시지는 맞고 시각이 다른 행(머리 불일치 → 약함)
    for name, why, same in (("absent", "찾았는데 없음: `SETUP_DATA_CALL` 재요청 — logs-masked 15:10:02 뒤", False),
                            ("weak", weak, False), ("ok", Q1, True)):
        job = _job(tmp_path / name, cands=[top])
        data, inv = _run(job, _out(extra=("후보 확인:", f"- DATA-001-01: 맞음 — {why}")), capsys)
        assert inv["status"] == "identified" and data["weak"] == (name == "weak"), (name, data, inv["gate"])
        assert ("top_match" in inv) is same and _cause_rows(job)[0].endswith("(규칙 1위 DATA-001-01와 같음)") is same, (name, data)


def test_a3_yes_answer_forms_with_copula(tmp_path, capsys):
    """A3: `예입니다`·`예이다`·`예임`·`예요`·`예 입니다`는 답 `예`다. `예상`·`예외`·`예정`·`예시`는 계속 답이 아니다."""
    from triagelib import output
    for tail in ("예입니다", "예이다.", "예임", "예요", "예 입니다", "**예입니다**"):
        mech = f"메커니즘 재계산: 01.2-00.1 = 1.1초 → 고치면 결과가 뒤집히나: {tail}"
        assert output.FLIP_RX.search(mech).group(1) == "예", tail
        assert output.FLIP_TAIL_RX.search(f"재계산: 1.1초 — {tail}").group(1) == "예", tail
    for tail in ("예상하기 어려움", "예외 발생", "예정", "예시: 1초"):
        assert not output.FLIP_RX.search(f"고치면 결과가 뒤집히나: {tail}"), tail
        assert not output.FLIP_TAIL_RX.search(f"재계산: 1.1초 — {tail}"), tail
    _d, inv = _run(_job(tmp_path), _out(rows=NUM_ROWS, extra=("메커니즘 재계산: 01.2-00.1 = 1.1초 → 고치면 결과가 뒤집히나: 예입니다",)),
                   capsys)
    assert _failed(inv) == [], inv["gate"]


HID = "2026-09-20T15:10:03.500Z host hiddend[5]: carrier link lost on rmnet_data3"     # 사본에만 있는 줄(tags.yaml 밖 태그)


def test_b1_cited_tags_missing_from_tags_yaml_are_recorded_and_reported(tmp_path, capsys):
    """반입 8 B1: 원문 확인(ok) 인용 줄의 태그 중 tags.yaml에 없고 파서가 읽지도 않는 것(hiddend)을 check-output 기록
    `parser_unknown_tags`에 남기고 리포트에 한 줄. tags.yaml엔 없어도 events.json에 레코드가 있는 태그(datad·ofonod — 백엔드 기본
    벤더 IPC `RIL`·builtin처럼 파서가 이미 읽는 태그, 확인 리뷰 의심)는 빼고, 지어낸 인용의 태그도 넣지 않는다. 판정·점수는 그대로."""
    from tests.test_check_output import FAKE
    job = _job(tmp_path)
    _copy(job, [ISO_Q1, HID])
    _data, inv = _run(job, _out(quotes=(Q1, Q_AFTER, HID, "15:10:09.000 p0 E fakedaemon " + FAKE)), capsys)
    rec = _rec(job)
    assert rec["parser_unknown_tags"] == ["hiddend"], rec
    line = "  - 파서 설정에 없는 태그가 근거 인용에 쓰임(탐색): hiddend — tags.yaml 추가 검토(사람이 판단, 자동으로 더하지 않음)"
    assert line in (job / "report.md").read_text(encoding="utf-8").split("\n")
    job = _job(tmp_path / "known")
    _copy(job, [ISO_Q1, HID])
    tags = (job.parent / "db" / "parser-rules" / "tags.yaml")
    tags.write_text(tags.read_text(encoding="utf-8") + "  - {tag: hiddend, category: data, added_for: '-', added_on: 2026-11-26, "
                    "reason: 시험}\n", encoding="utf-8")
    _run(job, _out(quotes=(Q1, Q_AFTER, HID)), capsys)
    assert "parser_unknown_tags" not in _rec(job) and "파서 설정에 없는 태그" not in (job / "report.md").read_text(encoding="utf-8")


def test_b1_deep_output_tags_are_marked_as_deep(tmp_path, capsys):
    """반입 8 B1: 5-1(심층) 인용도 같은 기록·줄 — 줄에 `(심층)`. 구간 파일 줄(hiddend)만 남고 events.json에 있는 vrild는 빠진다."""
    from tests.test_check_output import WIN_ROW, Q2, _deep_out, _window, check, make_job
    job = make_job(tmp_path, "deep", "module")
    ev = json.loads((job / "events.json").read_text(encoding="utf-8"))
    ev["rules"] = {"path": str(_rules(tmp_path, cp_mark=False))}
    (job / "events.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    msj = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    msj["deep"]["inputs"]["events.json"] = _sha(job / "events.json")      # 규칙 경로를 넣은 events.json으로 기록을 맞춘다
    (job / "module-skill.json").write_text(json.dumps(msj, ensure_ascii=False), encoding="utf-8")
    _window(job)
    (job / "deep-output.md").write_text(_deep_out([Q1, WIN_ROW, Q2]), encoding="utf-8")
    assert check(job, "deep", capsys=capsys)[0] == 0
    rec = json.loads((job / "check-output.json").read_text(encoding="utf-8"))["deep"]
    assert rec.get("parser_unknown_tags") == ["hiddend"], rec
    assert "  - 파서 설정에 없는 태그가 근거 인용에 쓰임(심층): hiddend — " in (job / "report.md").read_text(encoding="utf-8")


# --- 별개 리뷰 1126(G-1·G-3·G-5·G-7·G-8): 입력 모양을 바꾸면 다시 통과하던 길과 반대 방향 짝 ------------------------------------

ROW_Q_ELL = "15:10:30.000 - - datad link … lost carrier on rmnet_data0"     # 첫 조각(`link`)이 8자 미만


def test_g1_short_first_fragment_still_checks_the_copy_date(tmp_path, capsys):
    """G-1: 생략표로 첫 조각을 8자 미만으로 만들면 사본 줄 날짜 대조를 건너뛰어 전날 관측이 통과했다 — 8자 이상인 가장 긴 조각으로
    찾고 모든 조각이 같은 줄에 순서대로 있는지 본다. `로그로 확인`에 넣어도(게이트 4) 같다. 당일 줄이면 그대로 통과."""
    rows = [r.replace(ROW_Q, ROW_Q_ELL) for r in DAY_ROWS]
    out = _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=rows, claim="단계 2 — 링크가 끊김", head="링크가 끊겨 연결 실패")
    for name, line, ok in (("other", DAY_BEFORE, False), ("same", DAY_BEFORE.replace("09-19", "09-20"), True)):
        job = _job(tmp_path / name)
        _copy(job, [ISO_Q1, line])
        data, inv = _run(job, out, capsys)
        assert (inv["status"] == "identified") is ok and data["weak"] == (not ok), (name, data, inv["gate"])
    job = _job(tmp_path / "after")
    _copy(job, [ISO_Q1, DAY_BEFORE])
    _data, inv = _run(job, _out(quotes=(Q1, ROW_Q_ELL)), capsys)
    assert _failed(inv) == ["실패 뒤 흔적"], inv["gate"]


def test_g3_absent_words_in_one_item_are_each_counted(tmp_path, capsys):
    """G-3(N-2로 바꿈): `찾았는데 없음` 항목에 백틱 낱말이 둘이면 사본 고르기는 하나라도 든 사본, 세기는 모두 든 줄이라 늘 0건·긴
    사본으로 통과했다 — 낱말마다 따로 세고(`heartbeat`가 구간에 있어 실패), 끝도 낱말마다 그 낱말이 든 사본으로 잰다."""
    two = ("찾았는데 없음:", "- `SETUP_DATA_CALL` `heartbeat` 재요청 — logs-masked 15:10:02 뒤 grep")
    job = _job(tmp_path / "apart")
    _copies(job, {"radio.log": RADIO, "main.log": [TAIL]})
    _d, inv = _run(job, _out(rows=RETRY_ROWS, extra=(*two, RETRY_MECH)), capsys)
    assert _failed(inv) == ["첫 어긋남"] and "`heartbeat` 줄이" in inv["gate"][1]["why"], inv["gate"]      # N-2 전: 함께 든 줄 없음
    together = ("찾았는데 없음:", "- `SETUP_DATA_CALL` `AUTH_FAILURE_ON_EMM` 재요청 — logs-masked 15:10:02 뒤 grep")
    for name, radio, ok in (("short", RADIO, False), ("long", [*RADIO, TAIL.replace("datad[9]", "vrild[7]")], True)):
        job = _job(tmp_path / name)
        _copies(job, {"radio.log": radio, "main.log": [TAIL]})
        _d, inv = _run(job, _out(rows=RETRY_ROWS, extra=(*together, RETRY_MECH)), capsys)
        assert (inv["status"] == "identified") is ok, (name, inv["gate"])


def test_g5_yearless_copy_line_matches_across_new_year():
    """G-5: 연도 없는 사본 줄(logcat)은 분석 범위 시작의 연도로 읽혀 해를 넘는 로그에서 맞는 행 인용이 다른 날로(약함) 떨어졌다 —
    사본 줄에 연도가 없으면 ±1년도 맞춰 본다. 다른 날 줄은 그대로 None."""
    from triagelib import output
    output._raw_ready()
    ev = {"input": {"tz": "UTC", "window": {"start": "2026-12-31T23:55:00Z", "end": "2027-01-01T00:05:00Z"}}}
    q = "00:00:30.000 p0 I datad link monitor lost carrier on rmnet_data0"
    line = "{} 00:00:30.000  1000  1001 I datad: link monitor lost carrier on rmnet_data0\n"
    assert output._quote_at(q, ev, [line.format("01-01")]) == (output._quote_ts(q, ev), 0)
    assert output._quote_at(q, ev, [line.format("01-02")])[0] is None


def test_g7_rules_only_word_measures_the_copy_of_the_lower_end_line(tmp_path, capsys):
    """G-7: 낱말이 파서 규칙에만 있으면 끝은 아래 끝을 준 앞 단계 인용 줄의 사본으로 잰다 — 그 사본(radio)이 짧으면 다른 사본(main)이
    길어도 미관측. radio가 길면 통과."""
    rows = [FAIL_ROWS[0], FAIL_ROWS[1].replace(Q1, ISO_Q1),
            "| 3 | 인증 실패 뒤 DEACTIVATE를 보낸다 | CP 내부 | spec:x | 없음(찾은 곳: logs-masked 15:10:01 뒤) | false |"]
    extra = ("찾았는데 없음:", "- `DEACTIVATE_DATA_CALL` 요청 — logs-masked 15:10:01 뒤")
    for name, radio, ok in (("short", RADIO, False), ("long", [*RADIO, TAIL], True)):
        job = _job(tmp_path / name)
        (job / "explore-input.json").write_text(json.dumps({"limit": 200, "around": "2026-09-20T15:09:30Z"}), encoding="utf-8")
        _copies(job, {"radio.log": radio, "main.log": ["2026-09-20T15:30:00.000Z host other[2]: heartbeat"]})
        _d, inv = _run(job, _out(rows=rows, claim="단계 3 — CP가 DEACTIVATE를 안 보냄", extra=extra), capsys)
        assert (inv["status"] == "identified") is ok, (name, inv["gate"])
        assert ok or "미관측" in inv["gate"][1]["why"], (name, inv["gate"])


def test_g8_raw_shape_quote_is_never_other_day_without_rescan(monkeypatch):
    """G-8: 원문 모양 인용은 `stamp_matches`가 이미 날짜까지 맞췄다 — `_other_day`가 사본을 다시 훑지 않고 False."""
    from triagelib import output
    output._raw_ready()
    monkeypatch.setattr(output, "_quote_at", lambda *a: (_ for _ in ()).throw(AssertionError("사본을 다시 훑음")))
    assert output._other_day(ISO_Q1, {"input": {"tz": "UTC"}}, [ISO_Q1]) is False


# --- 확인 리뷰 1126(N-1~N-4, G-4): f075592b가 연 길과 시험 빈틈 ------------------------------------------------------------

N1_SHAPES = {"swapped": "15:10:30.000 - - datad on rmnet_data0 … link monitor lost carrier",          # 조각 순서 뒤바꿈
             "foreign": "15:10:30.000 - - datad link monitor lost carrier on rmnet_data0 … pdn_reject",  # 다른 줄 조각 덧붙임
             "joined": "15:10:30.000 - - datad link monitor lost carrier on rmnet_data0 … heartbeat",     # 이웃 두 줄 이음
             "short": "15:10:30.000 - - datad link … lost … carrier"}                                    # N-3: 8자 조각 없음


def test_n1_n3_row_quote_shapes_still_check_the_copy_date(tmp_path, capsys):
    """N-1·N-3: 조각 순서를 바꾸거나 다른 줄 조각을 덧붙이거나 이웃 두 줄을 이으면(f075592b의 순서 조건이 맞는 줄을 세지 않아) 또
    조각이 모두 8자 미만이거나 `[…]`면 전날 관측이 통과했다 — 가장 긴 조각(괄호 뗌, 8자 없으면 4자 이상) + 태그가 맞는 사본 줄이면
    세고 날짜를 본다. 같은 줄이 당일이면 그대로 통과(짝)."""
    tail = "2026-09-19T15:10:31.000Z host datad[9]: heartbeat"
    bad = []
    for name, q in N1_SHAPES.items():
        rows = [r.replace(ROW_Q, q) for r in DAY_ROWS]
        out = _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=rows, claim="단계 2 — 링크가 끊김", head="링크가 끊겨 연결 실패")
        for day, ok in (("19", False), ("20", True)):
            job = _job(tmp_path / f"{name}{day}")
            _copy(job, [ISO_Q1, DAY_BEFORE.replace("09-19", f"09-{day}"), tail.replace("09-19", f"09-{day}")])
            data, inv = _run(job, out, capsys)
            if data["fabricated"] or (inv["status"] == "identified") is not ok:
                bad.append((name, day, data["fabricated"], data["weak"], [g["name"] for g in inv["gate"] if not g["ok"]]))
    assert not bad, bad
    from triagelib import output        # N-3: `[…]` 조각은 괄호를 떼고 찾는다(인용 판정은 `[`가 남아 약함이라 게이트 대신 직접)
    ev = json.loads((job / "events.json").read_text(encoding="utf-8"))
    q = "15:10:30.000 - - datad lost […] on rmnet_data0"
    assert output._quote_at(q, ev, [DAY_BEFORE]) == (None, None)
    assert output._quote_at(q, ev, [DAY_BEFORE.replace("09-19", "09-20")]) == (output._quote_ts(q, ev), 0)


def test_n2_each_absent_word_is_counted_on_its_own(tmp_path, capsys):
    """N-2: 낱말 여럿인 `찾았는데 없음`은 모두 든 줄만 세어, 실패 줄에 함께 든 두 낱말을 고르면 실제 재요청 줄이 있어도 0건이었다
    (백틱 없이도) — 낱말마다 따로 센다(하나라도 있으면 실패, 이유에 그 낱말과 건수). 재요청 줄이 없으면 통과."""
    retry = "2026-09-20T15:10:05.000Z host vrild[7]: RIL_REQUEST_SETUP_DATA_CALL apn=internet"
    for name, item in (("tick", "- `SETUP_DATA_CALL` `AUTH_FAILURE_ON_EMM` 재요청 — logs-masked 15:10:02 뒤"),
                       ("bare", "- SETUP_DATA_CALL AUTH_FAILURE_ON_EMM 재요청 — logs-masked 15:10:02 뒤")):
        for case, lines, ok in (("retry", [ISO_Q1, retry, TAIL], False), ("none", [ISO_Q1, TAIL], True)):
            job = _job(tmp_path / f"{name}-{case}")
            _copy(job, lines)
            _d, inv = _run(job, _out(rows=ABSENT_ROWS, extra=("찾았는데 없음:", item)), capsys)
            assert (inv["status"] == "identified") is ok, (name, case, inv["gate"])
            assert ok or ("`SETUP_DATA_CALL` 줄이" in inv["gate"][1]["why"] and "1건" in inv["gate"][1]["why"]), inv["gate"]


def test_n4_gate_4_reads_the_end_time_of_the_window_head(tmp_path, capsys):
    """N-4: 처음·끝 시각이 다른 구간 파일 — 게이트 4는 머리의 **끝** 시각으로 판정한다(처음은 기준 앞, 끝은 뒤 → 통과)."""
    job = _job(tmp_path)
    _window(job, rows=("15:10:01.900 p0 E hiddend carrier link lost", "15:10:05.000 p0 I hiddend carrier link back"),
            first="2026-09-20T15:10:01.900Z", last="2026-09-20T15:10:05.000Z")
    _data, inv = _run(job, _out(quotes=(Q1,)), capsys)
    assert _failed(inv) == [], inv["gate"]


def test_g4_divergence_observation_far_before_prior_step_fails(tmp_path, capsys):
    """G-4: 날짜를 그대로 적은 전날 줄(`2026-09-19T15:10:30.000Z …`)을 첫 어긋남 관측으로 넣으면 통과했다 — 앞 단계 원문 확인 관측
    (단계 1, 15:10:00)보다 1시간(`OBS_BEFORE_MAX`) 넘게 앞서면 실패. 당일 줄이면 통과."""
    out = lambda line: _out(layer="AP 내부", quotes=(Q0, Q_AFTER), claim="단계 2 — 링크가 끊김", head="링크가 끊겨 연결 실패",
                            rows=[DAY_ROWS[0], DAY_ROWS[1].replace(ROW_Q, line)])
    for name, line, ok in (("other", DAY_BEFORE, False), ("same", DAY_BEFORE.replace("09-19", "09-20"), True)):
        job = _job(tmp_path / name)
        _copy(job, [ISO_Q1, line])
        _d, inv = _run(job, out(line), capsys)
        assert (inv["status"] == "identified") is ok, (name, inv["gate"])
        assert ok or "단계 2: 관측이 앞 단계 관측보다 24시간 앞섬" in inv["gate"][1]["why"], inv["gate"]


def test_g4_step_one_observation_far_from_reference_is_shown_not_failed(tmp_path, capsys):
    """G-4 ②: 앞 단계에 시각 있는 원문 확인 관측이 없으면(여기선 가장 이른 false가 단계 1) 실패시키지 않고, 관측이 기준 시각과 1시간 넘게 떨어졌으면 리포트 조사
    결론 하위 줄에 드러낸다(Jira 본문엔 없음). 당일이면 줄 없음."""
    for name, line, far in (("other", DAY_BEFORE, True), ("same", DAY_BEFORE.replace("09-19", "09-20"), False)):
        job = _job(tmp_path / name)
        _copy(job, [ISO_Q1, line])
        rows = [f"| 1 | 링크가 유지된다 | AP 내부 | spec:x | {line} | false |"]
        _d, inv = _run(job, _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=rows, claim="단계 1 — 링크가 끊김"), capsys)
        assert inv["status"] == "identified" and ("obs_far_h" in inv) is far, (name, inv)
        text = "\n".join(_cause_rows(job))
        assert ("  - 관측이 기준 시각과 24시간 떨어짐 — 같은 시험의 줄인지 확인" in text) is far, text
        assert "관측이 기준 시각과" not in "\n".join(issuepost.investigation_lines(inv, None, why=False))


# --- 반입 8 전체 확인 리뷰(C-2·C-3·C-4) --------------------------------------------------------------------------------

def test_c2_added_word_does_not_widen_the_absence_end(tmp_path, capsys):
    """C-2: 낱말을 하나씩 펼친 뒤 사본을 합쳐 끝을 재서, 낱말 하나(`heartbeat` — main에만, 기준 앞)를 덧붙이면 긴 main 사본이
    '없음'의 끝을 늘렸다(A4 우회) — 낱말마다 끝을 따로 재고 가장 좁은 범위를 쓴다. radio도 길면 통과(짝)."""
    two = ("찾았는데 없음:", "- `SETUP_DATA_CALL` `heartbeat` 재요청 — logs-masked 15:10:02 뒤 grep")
    main = ["2026-09-20T15:09:00.000Z host datad[9]: heartbeat", "2026-09-20T15:25:00.000Z host other[2]: tail"]
    for name, radio, ok in (("short", RADIO, False), ("long", [*RADIO, "2026-09-20T15:16:00.000Z host vrild[7]: idle"], True)):
        job = _job(tmp_path / name)
        _copies(job, {"radio.log": radio, "main.log": main})
        _d, inv = _run(job, _out(rows=RETRY_ROWS, extra=(*two, RETRY_MECH)), capsys)
        assert (inv["status"] == "identified") is ok, (name, inv["gate"])
        assert ok or "미관측" in inv["gate"][1]["why"], (name, inv["gate"])


def test_c3_changed_tag_of_row_quote_still_checks_the_copy_date(tmp_path, capsys):
    """C-3: 행 모양 인용의 태그만 바꾸면(근거 원문 검사는 행 인용의 태그를 보지 않아 ok) 사본 줄을 세지 않아 전날 관측이 날짜 대조를
    피했다 — 세는 조건에서 태그를 뺀다. 당일 줄이면 통과(짝)."""
    bad = []
    for tag in ("linkd", "-", "datad[9]", "datad:"):
        q = ROW_Q.replace(" datad ", f" {tag} ")
        rows = [r.replace(ROW_Q, q) for r in DAY_ROWS]
        out = _out(layer="AP 내부", quotes=(Q0, Q_AFTER), rows=rows, claim="단계 2 — 링크가 끊김", head="링크가 끊겨 연결 실패")
        for day, ok in (("19", False), ("20", True)):
            job = _job(tmp_path / f"{tag.strip(':[]9')}{len(tag)}{day}")
            _copy(job, [ISO_Q1, DAY_BEFORE.replace("09-19", f"09-{day}")])
            data, inv = _run(job, out, capsys)
            if data["fabricated"] or (inv["status"] == "identified") is not ok:
                bad.append((tag, day, data["weak"], [g["name"] for g in inv["gate"] if not g["ok"]]))
    assert not bad, bad


def test_c4_yearless_lines_across_new_year_keep_a_correct_conclusion(tmp_path, capsys):
    """C-4: 연도 없는 줄(logcat)은 범위 시작의 연도로 읽어, 해를 넘는 로그에서 첫 어긋남 `01-01 00:00:10`이 앞 단계 `12-31 23:59:50`
    보다 1년 앞선 것으로 읽혀 맞는 결론이 떨어졌다(G-4, 실패 뒤 흔적도) — 연도 없는 줄은 분석 범위(없으면 로그 범위)에 가장 가까운
    해로 읽는다. 게이트 전체를 돈다. 같은 줄이 정말 1년 전이면(연도를 적은 원문) 그대로 실패."""
    prev = "12-31 23:59:50.000  1000  1001 I datad: link up on rmnet_data0"
    lost = "01-01 00:00:10.000  1000  1001 E datad: link monitor lost carrier on rmnet_data0"
    job = _job(tmp_path)
    ev = json.loads((job / "events.json").read_text(encoding="utf-8"))
    ev["input"] = {"tz": "UTC", "window": {"start": "2026-12-31T23:50:00Z", "end": "2027-01-01T00:10:00Z"}}
    (job / "events.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    (job / "explore-input.json").write_text(json.dumps({"limit": 200, "around": "2026-12-31T23:59:55Z"}), encoding="utf-8")
    _copy(job, [prev, lost])
    rows = [f"| 1 | 링크가 올라온다 | AP 내부 | log:23:59:50 | {prev} | true |",
            f"| 2 | 링크가 유지된다 | AP 내부 | spec:x | {lost} | false |"]
    data, inv = _run(job, _out(layer="AP 내부", quotes=(prev, lost), rows=rows, claim="단계 2 — 링크가 끊김"), capsys)
    assert data["weak"] == 0 and inv["status"] == "identified", (data, inv["gate"])
    from triagelib import output
    assert output._quote_ts(lost, ev).isoformat().startswith("2027-01-01T00:00:10")
    assert output._quote_ts("2026-01-01T00:00:10.000Z host datad[9]: x", ev).isoformat().startswith("2026-01-01")   # 연도 적힌 줄은 그대로


# --- eval 46(반입 8): 재계산 '아니오'를 적었다가 그 줄만 지우고 다시 검사 --------------------------------------------------------

NO_MECH = "메커니즘 재계산: 재시도 간격 그대로 → 고치면 결과가 뒤집히나: 아니오"


def test_e46_deleting_a_no_recompute_line_does_not_turn_into_identified(tmp_path, capsys):
    """eval 46: 기대 칸에 숫자가 없으면 재계산 줄은 필수가 아니라, '아니오'(근거 부족)를 받은 뒤 그 줄만 지우고 같은 가설로 다시
    검사하면 identified가 됐다 — 앞 검사에서 같은 가설의 재계산 답이 '아니오'였는데 이번 출력에 재계산이 없으면 그 실패를 이어받는다
    (기록 `mech_no`). 가설을 바꾸면(머리가 다름) 이어받지 않는다. 숫자 기대면 원래도 막힌다(재계산 없음)."""
    job = _job(tmp_path / "plain")
    _d, inv = _run(job, _out(extra=(NO_MECH,)), capsys)
    assert _failed(inv) == ["숫자 메커니즘"], inv["gate"]
    _d, inv = _run(job, _out(), capsys)                                         # 그 줄만 지움
    assert _failed(inv) == ["숫자 메커니즘"] and "앞 검사" in inv["gate"][4]["why"], inv["gate"]
    assert _rec(job)["mech_no"] == inv["cause"]
    job = _job(tmp_path / "changed")                                             # 가설(머리)을 바꾸면 이어받지 않는다
    _run(job, _out(extra=(NO_MECH,)), capsys)
    _d, inv = _run(job, _out(head="APN 프로필이 없어 SETUP_DATA_CALL이 거절됨"), capsys)
    assert inv["status"] == "identified", inv["gate"]
    job = _job(tmp_path / "numeric")                                             # 숫자 기대: 지우면 재계산 없음으로 실패
    _run(job, _out(rows=NUM_ROWS, extra=(NO_MECH,)), capsys)
    _d, inv = _run(job, _out(rows=NUM_ROWS), capsys)
    assert _failed(inv) == ["숫자 메커니즘"], inv["gate"]
    _d, inv = _run(_job(tmp_path / "fresh"), _out(), capsys)                   # 처음부터 재계산 없이 쓴 같은 가설은 그대로 통과
    assert inv["status"] == "identified", inv["gate"]


def test_e77_rewriting_a_no_recompute_as_not_applicable_keeps_the_failure(tmp_path, capsys):
    """eval 77: 재계산 '아니오'를 받은 같은 가설이 줄을 지우지 않고 `해당 없음 — …`으로 바꿔 쓰면 게이트 5를 통과했다 — `mech_no`가
    남은 같은 머리는 답이 `예`(와 계산 숫자)일 때만 새로 판정하고 그 밖(없음·해당 없음·빈 답·틀)은 실패를 이어받는다. `예`와 숫자로
    다시 쓰면 통과. 처음 검사에서 숫자 기대에 `해당 없음`만 쓰면 원래도 막힌다."""
    for name, mech in (("na", "메커니즘 재계산: 해당 없음 — 원인이 타이머·임계값이 아니다"),
                       ("blank", "메커니즘 재계산: 계산할 자료 없음 → 고치면 결과가 뒤집히나: 예|아니오")):
        job = _job(tmp_path / name)
        _run(job, _out(extra=(NO_MECH,)), capsys)
        _d, inv = _run(job, _out(extra=(mech,)), capsys)
        assert _failed(inv) == ["숫자 메커니즘"] and inv["gate"][4]["why"].startswith("앞 검사에서 이 가설"), (name, inv["gate"])
    job = _job(tmp_path / "yes")
    _run(job, _out(extra=(NO_MECH,)), capsys)
    _d, inv = _run(job, _out(extra=("메커니즘 재계산: 01.2-00.1 = 1.1초 → 고치면 결과가 뒤집히나: 예",)), capsys)
    assert inv["status"] == "identified", inv["gate"]
    _d, inv = _run(_job(tmp_path / "first"), _out(rows=NUM_ROWS, extra=("메커니즘 재계산: 해당 없음 — 원인이 타이머가 아니다",)), capsys)
    assert _failed(inv) == ["숫자 메커니즘"] and inv["gate"][4]["why"] == "재계산 답 없음(예/아니오)", inv["gate"]
