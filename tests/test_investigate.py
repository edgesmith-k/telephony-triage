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
    assert rows[0].startswith("- 조사 결론 (LLM, 검증 통과): vrild가 SETUP_DATA_CALL을 인증 실패로 끝냄 / 첫 어긋남: 단계 2")
    assert "책임 층: CP 내부 / 근거 줄: identified" in rows[0] and rows[2:] == CAUSE_HEAD[1:]     # 기존 칸·순서 그대로
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
    assert _failed(inv) == ["외부 근거"] and "CP 태그 줄 없음" in inv["gate"][5]["why"]
    _data, inv = _run(_job(tmp_path / "b", cp_mark=False), _out(), capsys)      # tags.yaml에 CP 표시가 없다
    assert _failed(inv) == ["외부 근거"] and inv["gate"][5]["why"] == "tags.yaml에 CP/망 표시 없음"


def test_window_after_reference_counts_as_looking_after(tmp_path, capsys):
    job = _job(tmp_path / "a")
    _window(job, rows=("15:10:01.900 p0 E hiddend carrier link lost", "15:10:05.000 p0 I hiddend carrier link back"))
    _data, inv = _run(job, _out(quotes=(Q1,)), capsys)
    assert _failed(inv) == []


def test_window_counts_only_when_a_line_after_reference_exists(tmp_path, capsys):
    """리뷰 L4: 구간 기록의 중심(`at`)이 기준 뒤여도 실제 줄이 기준 뒤에 없으면(마지막 줄이 기준과 같은 시각 포함) 인정하지 않는다."""
    for name, last in (("before", "15:10:01.900"), ("same", "15:10:02.000")):
        job = _job(tmp_path / name)
        _window(job, rows=(f"{last} p0 E hiddend carrier link lost",))
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
    assert rows[0].startswith("- 조사 결론 (LLM, 검증 통과)")


def test_rule_top_c0_differs_moves_under_as_observed_match(tmp_path, capsys):
    top = {**OK_KEYS["candidates"][0], "cause": None, "C": 0}
    job = _job(tmp_path, cands=[top])
    _data, inv = _run(job, _out(), capsys)
    assert json.loads((job / "analysis.json").read_text(encoding="utf-8"))["investigate"] == {"mode": True, "reason": "1위 C=0"}
    assert _cause_rows(job)[1] == ("  - 관측된 규칙 일치: data > DATA-001 > 원인 미확인 — 규칙 1위(원인 일치 없음), 조사 결론과 다름")


def test_jira_cause_has_investigation_on_top_or_below(tmp_path, capsys):
    job = _job(tmp_path)
    _run(job, _out(), capsys)
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    cause = [i["text"] for i in issue_post.build(fake, a, None, None, set())[0]["CAUSE"]]
    assert cause[0].startswith("조사 결론 (LLM, 검증 통과): ") and cause[2].startswith("분류: 후보 없음")
    assert not any("Step 7" in t for t in cause) and "규칙 판정은 보류, 조사 결론은 검증 통과" in cause[1]     # 리뷰 L6
    a["investigation"] = {**a["investigation"], "status": "insufficient_evidence",
                          "gate": [{**g, "ok": g["name"] != "책임 층"} for g in a["investigation"]["gate"]]}
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
    assert (after["layer_correct"], after["cause_cited"], after["identified_correct"], after["identified_wrong"],
            after["insufficient"]) == ("2/2", "2/2", "1/2", "0/2", "1/2")
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
    """리뷰 M1: analysis.json investigation의 explore_sha가 지금 탐색 검사 기록과 다르면 Jira 본문에 싣지 않는다."""
    job = _job(tmp_path)
    _run(job, _out(), capsys)
    fake = types.SimpleNamespace(path=lambda n: job / n, tracker=trackers.get("jira"), key="MOCK-9076", db_cfg={})
    a = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    a["investigation"]["explore_sha"] = "0" * 64
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
    assert shown.REPORT_CORE.match("- 조사 결론 (LLM, 검증 통과): x")
