#!/usr/bin/env python3
"""핵심 자동화 4건의 제어 흐름 (11/17 2차 범위 F-AUTO·F-FIT·F-NOREPEAT·F-END). 실제 모델 없이 스크립트 출력만 본다.

- F-AUTO: 시각·기준 줄·Jira 시각이 다 없어도 묻지 않고 끝까지 간다(`step_anchor.time_candidates`, 전체 파싱 1회).
  Workspace 경로(eval 5 로그)는 `test_triage.py::test_jira_without_time_runs_whole_log_without_asking_and_keeps_time_candidates`.
- F-FIT: 1위 C=1이면 `run --explore`·`explore.when: always`일 때만 `explore.reason: fit_check`. 그 밖·두 기존 사유는 그대로.
- F-END: 적합성 확인에서 맞지 않으면 기존 `가설 없음`·`다음 확인` 형식 그대로 리포트 줄이 된다.
- F-NOREPEAT: 재실행이면 `analysis.json prior`(직전 1위·검사 통과한 이전 가설·`가설 없음` 이유·이전 기준 줄 조회), 받은 답은 남는다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, padded_log, parse_calls, plugin_root, run, run_json, tmp  # noqa: E402
from workspace import Workspace  # noqa: E402

LABELSET = REPO / "tests" / "fixtures" / "offline-eval-sample.yaml"
MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
DATA_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
ASK_NOTE = "답 전 로그 원문 grep·sed·Read 금지 — report.md를 보이고 묻는다(SKILL 5-2)"


def _doc() -> dict:
    return yaml.safe_load(LABELSET.read_text(encoding="utf-8"))


def _run(item: dict, out: Path, *extra, occurred: bool = True, root: Path | None = None) -> dict:
    doc = _doc()
    meta = out.parent / f"{out.name}.meta.json"
    meta.write_text(json.dumps({"key": item["key"], "summary": item.get("summary", ""),
                                **({"occurred_at": item["occurred_at"]} if occurred else {})}, ensure_ascii=False),
                    encoding="utf-8")
    logs = [str((LABELSET.parent / p).resolve()) for p in item["logs"]]
    return run_json("triage.py", ["run", item["key"], "--offline-db", SAMPLE, "--out", out, "--logs", *logs,
                                  "--issue-meta", meta, "--tz", doc["tz"], "--year", doc["year"], *extra],
                    **({"root": root} if root else {}))


def _confirmed() -> dict:
    return _doc()["items"][0]           # EVAL-1: 1위 DATA-001-01 C=1


def _unresolved() -> dict:
    return next(i for i in _doc()["items"] if i["expect"] == "unresolved")


def _report_line(out: Path, prefix: str) -> str:
    return next((line for line in (out / "report.md").read_text(encoding="utf-8").splitlines() if line.startswith(prefix)), None)


# -- F-AUTO -------------------------------------------------------------------------------------------------


def test_no_time_no_look_no_jira_time_finishes_with_time_candidates_and_one_parse():
    out = tmp("tt-auto-") / "x"
    analysis = _run(_confirmed(), out, "--explore", occurred=False)
    assert analysis["status"] == "ok", analysis                     # NeedsInput("time") 없이 끝까지
    anchor = analysis["step_anchor"]
    assert anchor["source"] == "symptom_scan" and anchor["time_candidates"], anchor
    assert all(set(t) == {"ts", "type"} for t in anchor["time_candidates"])
    assert [t["ts"] for t in anchor["time_candidates"]] == sorted(t["ts"] for t in anchor["time_candidates"])
    calls = parse_calls(out)
    assert len(calls) == 1 and "--full" in calls[0], calls          # occurred()의 전체 파싱을 본 분석이 다시 쓴다
    assert (out / "events.json").read_bytes() == (out / "events-full.json").read_bytes()
    assert analysis["candidates"][0]["cause"] == "DATA-001-01"
    spec = json.loads((out / "explore-input.json").read_text(encoding="utf-8"))   # 사건 후보가 탐색 입력에도 간다
    assert spec["time_candidates"] == anchor["time_candidates"] and spec["around"] is None
    assert _report_line(out, "- 기준 시각 없음").startswith(
        f"- 기준 시각 없음(시각·기준 줄 입력 없음) — 로그 전체를 봄. 증상 시각 후보 {len(anchor['time_candidates'])}개: ")
    # FR-04(P4): must_show(우선순위 3.5 — 실패 스텝 앞). 포털은 모르는 머리말을 확실한 일치에서 뺀다(fail-closed)
    assert _report_line(out, "- 기준 시각 없음")[2:] in analysis["must_show"], analysis["must_show"]
    failed = _run(_confirmed(), tmp("tt-auto-") / "f", "--failed-step", "Step 3 데이터 연결 확인", occurred=False)
    shown = [m.split(" ", 1)[0] for m in failed["must_show"]]
    assert shown.index("기준") < shown.index("실패"), failed["must_show"]


def test_given_time_still_wins_over_auto_scan():
    out = tmp("tt-auto-") / "x"
    item = _confirmed()
    analysis = _run(item, out, "--answer", f"time={item['occurred_at']}", occurred=False)
    assert analysis["status"] == "ok" and "time_candidates" not in (analysis.get("step_anchor") or {}), analysis
    assert all("--around" in c for c in parse_calls(out))


# -- F-FIT ----------------------------------------------------------------------------------------------------


def test_confirmed_top_gets_fit_check_only_with_explore_flag_or_always():
    # 11/27: "확신 일치"는 1위 C=1이 아니라 스크립트의 채택이다 — 기준 줄로 채택되게 한다(기준 없이 돈 같은 로그는 보류, 아래 끝)
    item, look = _padded(), ("--look-at", LOOK)
    plain = _run(item, tmp("tt-fit-") / "a", *look)
    assert plain["decision"]["state"] == "accepted" and "explore" not in plain          # --explore 없는 세션은 이전과 같다
    no = _run(item, tmp("tt-fit-") / "n", "--no-explore", *look)
    assert "explore" not in no
    out = tmp("tt-fit-") / "b"
    flagged = _run(item, out, "--explore", *look)
    assert flagged["explore"] == {"reason": "fit_check", "when": "ask", "note": ASK_NOTE}
    assert (out / "explore-input.json").is_file()
    assert _report_line(out, "- 탐색 분석").startswith("- 탐색 분석 (추정): 미실행")
    always = _run(item, tmp("tt-fit-") / "c", *look, root=plugin_root(explore={"when": "always"}))
    assert always["explore"] == {"reason": "fit_check", "when": "always"}
    never = _run(item, tmp("tt-fit-") / "d", "--explore", *look, root=plugin_root(explore={"when": "never"}))
    assert "explore" not in never                                       # never면 플래그가 있어도 열지 않는다
    # 1위 C=1인데 보류(기준 없음 no_reference) → 조사 모드: 기본 설정(ask)에서도 탐색을 묻는다(외부 설계 리뷰 1)
    held = _run(_confirmed(), tmp("tt-fit-") / "h")
    assert held["candidates"][0]["C"] == 1 and held["decision"]["state"] == "held"
    assert held["explore"] == {"reason": "cause_unconfirmed", "when": "ask", "note": ASK_NOTE}
    assert held["investigate"] == {"mode": True, "reason": "채택 안 함"}
    # FR-07(P5): 끄는 쪽이 이긴다 — --no-explore면 always여도 열지 않는다
    off = _run(item, tmp("tt-fit-") / "g", "--no-explore", *look, root=plugin_root(explore={"when": "always"}))
    assert "explore" not in off and not (tmp("tt-fit-") / "g" / "explore-input.json").exists()
    # 기존 두 사유는 플래그와 상관없이 그대로
    unresolved = _run(_unresolved(), tmp("tt-fit-") / "e", "--explore")
    assert unresolved["explore"] == {"reason": "no_candidate", "when": "ask", "note": ASK_NOTE}


def test_cause_unconfirmed_reason_unchanged(tmp_path):
    from types import SimpleNamespace
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import importlib
    triage = importlib.import_module("triage")
    no_note = lambda: {"at": None, "note": None}  # noqa: E731
    drv = SimpleNamespace(cfg={}, warnings=[], args=SimpleNamespace(explore=True), look_inputs=no_note)
    acc = {"state": "accepted"}         # 11/27: fit_check 경로는 채택일 때(1위 C=1이어도 보류면 조사 모드 — cause_unconfirmed)
    assert triage.Driver.explore(drv, [{"C": 0}])["reason"] == "cause_unconfirmed"
    assert triage.Driver.explore(drv, [])["reason"] == "no_candidate"
    assert triage.Driver.explore(drv, [{"C": 1}], acc)["reason"] == "fit_check"
    assert triage.Driver.explore(drv, [{"C": 1}], {"state": "held", "reason": "ambiguous"})["reason"] == "cause_unconfirmed"
    drv.args.explore = None
    assert triage.Driver.explore(drv, [{"C": 1}], acc) is None
    assert triage.Driver.explore(drv, [{"C": 1}], {"state": "held", "reason": "no_reference"})["reason"] == "cause_unconfirmed"
    always = SimpleNamespace(cfg={"explore": {"when": "always"}}, warnings=[], args=SimpleNamespace(explore=False),
                             look_inputs=no_note)
    assert triage.Driver.explore(always, [{"C": 1}], acc) is None                  # --no-explore > always (P5)
    assert triage.Driver.explore(always, [{"C": 0}])["reason"] == "cause_unconfirmed"   # 기존 두 사유는 그대로
    # 잘못된 explore.when은 C=1 경로에서도 먼저 경고하고 ask로 본다(조용히 꺼지지 않는다)
    bad = SimpleNamespace(cfg={"explore": {"when": "sometimes"}}, warnings=[], args=SimpleNamespace(explore=True),
                          look_inputs=no_note)
    assert triage.Driver.explore(bad, [{"C": 1}], acc)["reason"] == "fit_check"
    assert bad.warnings == ["explore.when 값이 잘못됐다(sometimes). ask로 본다"]
    # FR-16(P9): 확인할 내용(--look-note)이 있으면 플래그 없이도 fit_check를 연다 — never·--no-explore는 그래도 끈다
    note = lambda: {"at": None, "note": "재시도가 오는지"}  # noqa: E731
    asked = SimpleNamespace(cfg={}, warnings=[], args=SimpleNamespace(explore=None), look_inputs=note)
    assert triage.Driver.explore(asked, [{"C": 1}], acc)["reason"] == "fit_check"
    asked.args.explore = False
    assert triage.Driver.explore(asked, [{"C": 1}], acc) is None
    asked.args.explore, asked.cfg = None, {"explore": {"when": "never"}}
    assert triage.Driver.explore(asked, [{"C": 1}], acc) is None


def test_no_explore_is_in_request_hash_so_always_fit_check_is_not_reused():
    """P5: --no-explore는 입력 해시(args)에 든다 — 없으면 always 설정에서 fit_check를 연 결과가 --no-explore 실행에 재사용됐다."""
    ws = Workspace(root=plugin_root(explore={"when": "always"}))
    log = padded_log(REPO / "tests/fixtures/logs/data-roaming-disabled.log", tmp("tt-fit-hash-") / "roaming.log")    # 채택되게(11/27)
    args = ["run", "MOCK-9005", "--dry-run", "--issue-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip", "--look-at", ROAMING_LOOK]
    first = ws.json("triage.py", args)
    assert first["status"] == "ok" and first["explore"]["reason"] == "fit_check", first
    off = ws.json("triage.py", [*args, "--no-explore"])
    assert off["reuse"]["hit"] is False and "args" in off["reuse"]["changed"] and "explore" not in off, off["reuse"]
    again = ws.json("triage.py", args)                                   # 플래그 없음은 처음 해시 그대로
    assert again["explore"]["reason"] == "fit_check"
    ws.json("triage.py", ["release", "MOCK-9005"])


# MOCK-9005 실패 줄(같은 줄이 10초 간격으로 두 번 — 시각으로 한 곳을 고른다, 단계 5 §8-5). 기준 줄이 있어야 1위가 채택된다
ROAMING_LOOK = ("09-22 08:00:03.500  1234  1250 W DNC-1: Data evaluation: evaluation reason:ROAMING_ENABLED_CHANGED, "
                "Data disallowed reasons: ROAMING_DISABLED, candidate profile=null")


def test_fit_drops_prior_hyps_then_prior_when_only_top_is_left():
    sys.path.insert(0, str(plugin_root() / "scripts"))
    from triagelib import report
    result = {"prior": {"top": "DATA-001-01", "hyps": ["x"]}}
    report._drop_prior_hyps(result)
    assert "prior" not in result                      # top만 남으면 통째로 뺀다
    result = {"prior": {"top": "DATA-001-01", "hyps": ["x"], "none": "y"}}
    report._drop_prior_hyps(result)
    assert result["prior"] == {"top": "DATA-001-01", "none": "y"}


# -- F-END · F-NOREPEAT -----------------------------------------------------------------------------------------


def test_unfit_top_holds_with_reason_and_next_check_then_rerun_carries_prior():
    item, look = _padded(), ("--look-at", LOOK)        # 11/27: 적합성 확인은 채택일 때만(기준 없이 돈 C=1은 조사 모드)
    out = tmp("tt-end-") / "x"
    assert _run(item, out, "--explore", *look)["explore"]["reason"] == "fit_check"
    assert run_json("triage.py", ["explore", item["key"], "--out", out])["timeline"] == "timeline.md"
    (out / "explore-output.md").write_text("가설 없음: 1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다\n"
                                           "다음 확인: 실패 시각 앞뒤 1분 radio 로그\n", encoding="utf-8")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])
    assert "가설 없음: 1위 DATA-001-01 부적합" in checked["line"], checked
    line = _report_line(out, "- 탐색 분석")
    assert "가설 없음: 1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다" in line
    assert "다음 확인: 실패 시각 앞뒤 1분 radio 로그" in line
    # FR-02(P2): 보류면 결론·해결책 줄도 1위 확정·`검증됨`을 권하지 않는다(판정·후보 순위는 그대로)
    assert _report_line(out, "- 결론:") == ("- 결론: 채택 후보 DATA-001-01가 증상과 맞지 않아 보류(탐색 분석 참조). "
                                         "다음: Step 7에서 보류를 고르거나 근거 로그 확인")
    assert _report_line(out, "- 해결책(1위 기준, 보류됨): ").endswith("해결책 검증: 보류(1위 부적합)")
    assert "fit_hold_unwritten" not in json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]["fit_hold"] == "DATA-001-01"
    assert json.loads((out / "analysis.json").read_text(encoding="utf-8"))["candidates"][0]["C"] == 1

    again = _run(item, out, "--explore", *look)                           # 재실행(답글 턴): 이전 판단을 넘긴다
    # RP-6: 가설 없음 보류도 unfit으로 넘긴다(같은 원인이 다시 채택되면 run이 보류한다). 이 보류(held/fit_check)는 조사 모드가 아니다
    assert (again["decision"]["reason"], again["investigate"]) == ("fit_check", {"mode": False}), again["decision"]
    assert again["prior"] == {"none": "1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다",
                              "unfit": "DATA-001-01 — 1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다"}, again.get("prior")
    assert not (out / "explore-output.md").exists()                      # 추린 뒤에 지웠다(drop_stale_records)
    # CP-2: 검사 기록은 지워졌어도 부적합 표시는 `적합`이라고 다시 적을 때까지 넘긴다 — 오프라인은 state가 없어 앞 실행
    # analysis.json의 prior.unfit을 읽는다(전에는 여기서 사라져 셋째 실행이 같은 원인을 경고 없이 다시 채택할 수 있었다).
    # 가설 없음 이유(none)는 검사 기록이 있을 때만 넘긴다(그대로)
    third = _run(item, out, "--explore", *look)
    assert third["prior"] == {"unfit": again["prior"]["unfit"]}, third.get("prior")
    # 코덱스 K06: 오프라인도 로그를 바꿔 다시 돌리면 옛 로그 때의 부적합 표시를 쓰지 않는다(앞 analysis.json 입력 해시와 비교)
    src = (LABELSET.parent / item["logs"][0]).resolve()
    changed = out.parent / ("changed-" + src.name)
    changed.write_bytes(src.read_bytes() + b"\n")
    fourth = _run({**item, "logs": [str(changed), *item["logs"][1:]]}, out, "--explore", *look)
    assert "unfit" not in (fourth.get("prior") or {}), fourth.get("prior")


def test_fit_hold_is_recorded_even_when_lines_cannot_be_rewritten_and_survives_recheck():
    """리뷰 지적(P2 fail-open): ① 보류 기록(fit_hold)은 구조 감지만으로 남는다 — 결론 줄을 못 고쳐도(줄 없음) 기록·경고가 남고
    Jira 본문(계획 없음)은 보류다. ② 뒤 검사(형식 불일치 _fail)가 탐색 기록을 새로 써도 fit_hold는 이어받는다."""
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import issue_post
    item = _padded()            # 11/27: 적합성 확인은 채택일 때만 — 기준 줄로 채택되게
    out = tmp("tt-hold-") / "x"
    assert _run(item, out, "--explore", "--look-at", LOOK)["explore"]["reason"] == "fit_check"
    run_json("triage.py", ["explore", item["key"], "--out", out])
    report = out / "report.md"
    pending = _report_line(out, "- 탐색 분석")
    report.write_text("\n".join(x for x in report.read_text(encoding="utf-8").split("\n") if not x.startswith("- 결론:")),
                      encoding="utf-8")
    (out / "explore-output.md").write_text("가설 없음: 1위 DATA-001-01 부적합 — 슬롯이 다르다\n다음 확인: radio 로그\n",
                                           encoding="utf-8")
    proc = run("triage.py", ["check-output", item["key"], "--for", "explore", "--out", str(out)])
    assert proc.returncode == 0 and "경고: 1위 보류를 report.md 결론 줄에 쓰지 못했다" in proc.stderr, proc.stderr
    rec = json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert rec["fit_hold"] == "DATA-001-01" and rec["fit_hold_unwritten"] == ["결론 줄"], rec
    assert _report_line(out, "- 해결책(1위 기준, 보류됨): ").endswith("해결책 검증: 보류(1위 부적합)")     # 못 쓴 줄은 결론 줄만
    # 탐색 줄 재작성이 실패해 TODO가 남은 상황을 흉내 내고 다시 검사(형식 불일치 → _fail이 기록을 새로 쓴다)
    text = report.read_text(encoding="utf-8")
    report.write_text(text.replace(_report_line(out, "- 탐색 분석"), pending), encoding="utf-8")
    (out / "explore-output.md").write_text("가설 1: 칸이 모자란 가설\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out], expect=1)
    rec = json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert rec.get("error") and rec["fit_hold"] == "DATA-001-01", rec
    hold = issue_post.fit_hold_of(out / "check-output.json")
    analysis = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
    nxt = issue_post.classify(analysis, None, hold)["next"]
    assert hold == "DATA-001-01" and nxt[0] == "원인 미확정 — 추가 로그·재현 정보 필요", nxt
    assert analysis["decision"]["state"] == "held"          # 적합성 보류(held/fit_check)로 바뀐 판단 — 해결책을 싣지 않는다
    assert nxt == ["원인 미확정 — 추가 로그·재현 정보 필요"], nxt
    old = {k: v for k, v in analysis.items() if k != "decision"}     # decision 없는 옛 JOB은 예전처럼 보류된 해결책
    nxt = issue_post.classify(old, None, hold)["next"]
    assert any(x.startswith("해결책(1위 기준, 보류됨): ") and x.endswith("(해결책 검증: 보류(1위 부적합))") for x in nxt), nxt


# 기준 줄(글자 일치 1개) — 단계 4에서 1위를 채택하게 하는 실패 지점
LOOK = "notifyDataEnabledChanged: enabled=false"


def test_decision_state_follows_deep_counter_then_fit_hold():
    """단계 4 상태 전달(Y10 "채택을 심층이 반박" — 모델 능력 검증이 아니다): 기준 줄로 채택된 1위를 ① 심층 분석 의견이 다른
    원인 ID로 반박하면 `counter`만 붙고 채택은 그대로, ② 탐색 적합성 확인이 보류하면 held/fit_check로 내려가고 counter가
    없어진다. analysis.json(스키마 검사 통과)·report.md `- 판단:` 줄·Jira 본문 분류가 같이 바뀌고 후보 목록은 그대로다."""
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import issue_post
    item = _confirmed()       # 로그 끝에 RILJ·꼬리 줄을 붙여 증상의 '없어야 할 줄' 확인을 채운다(그래야 채택 — 단계 5-1 리뷰 P1-2)
    item = {**item, "logs": [str(padded_log((LABELSET.parent / p).resolve())) for p in item["logs"]]}
    out = tmp("tt-dec-") / "x"
    root = plugin_root(analyzers={"data": {"skill": "mock-data-analyzer", "when": "ask"}})
    done = _run(item, out, "--explore", "--look-at", LOOK, root=root)
    dec = done["decision"]
    assert dec["check"]["why"] == "same_line" and dec["events"][0]["result"] == "adopted", dec     # 기준 줄 = 실패 사건 줄
    assert {k: v for k, v in dec.items() if k in ("state", "reason", "selected", "location", "counter")} == {"state": "accepted", "reason": "anchored_top",
                   "selected": {"category": "data", "type": "DATA-001", "cause": "DATA-001-01"},
                   "location": {"state": "confirmed", "source": "look_at", "kind": "point"}}, dec     # 글자 일치지만 같은 줄 채택
    # DATA-001-01(모바일 데이터 꺼짐)은 샘플 DB에서 버그 아님 — 판단 줄 끝 표시와 해결책 앞말(sim1120 P2-7·S-25)
    assert _report_line(out, "- 판단:") == ("- 판단: 원인 채택 — DATA-001-01 (실패 지점: 담당자가 지정한 기준 줄·확인됨, "
                                          "자격 검사 통과) · 이슈 DB에서 버그 아님(시험 절차·설정 조작이 만든 동작으로 알려진 규칙)인 "
                                          "기준 사건 원인: DATA-001-01")
    assert _report_line(out, "- 해결책:").startswith("- 해결책: 시험 절차 문제면 해당 없음 — ")
    assert "(관측된 규칙 일치" not in _report_line(out, "- 분류 후보:")
    (out / "deep-output.md").write_text("요약: 사용자 설정이 아니라 망 거절로 보인다\n근거:\n"
                                        "분석 스킬 의견: DATA-001-02 — 망 거절 흔적\n규칙 제안:\n- 없음\n", encoding="utf-8")
    analysis = out / "analysis.json"

    def turn_start() -> os.stat_result:
        """포털은 턴 시작 뒤 바뀐 analysis.json만 읽는다(`read_safe(..., since)`) — 시작 시각을 1시간 앞으로 돌려 둔다."""
        old = analysis.stat()
        os.utime(analysis, ns=(old.st_atime_ns, old.st_mtime_ns - 3600 * 10**9))
        return analysis.stat()

    before = turn_start()
    run_json("triage.py", ["check-output", item["key"], "--for", "deep", "--out", out], root=root)
    after = json.loads(analysis.read_text(encoding="utf-8"))
    now = analysis.stat()
    assert now.st_mtime_ns > before.st_mtime_ns and now.st_ino != before.st_ino     # 원자적 교체(새 파일), mtime 갱신
    assert not list(out.glob(".analysis.json.tmp-*"))
    assert after["decision"] == {**dec, "counter": {"cause": "DATA-001-02"}}
    assert after["candidates"] == done["candidates"]
    assert _report_line(out, "- 판단:").endswith("기준 사건 원인: DATA-001-01 · 모델 검토 의견이 다름(DATA-001-02) — 확인 필요")
    assert issue_post.classify(after, None)["cls"].endswith("DATA-001-01 Data disabled")      # 채택은 그대로

    run_json("triage.py", ["explore", item["key"], "--out", out], root=root)
    (out / "explore-output.md").write_text("가설 없음: 1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다\n"
                                           "다음 확인: radio 로그\n", encoding="utf-8")
    before = turn_start()
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out], root=root)
    held = json.loads(analysis.read_text(encoding="utf-8"))
    now = analysis.stat()
    assert now.st_mtime_ns > before.st_mtime_ns and now.st_ino != before.st_ino
    # check-output은 상태·사유·selected·counter와 붙은 사건의 result(adopted → held)만 바꾼다 — check·events_total은 그대로
    assert held["decision"] == {**{k: v for k, v in dec.items() if k != "counter"}, "state": "held", "reason": "fit_check",
                                "selected": None,
                                "events": [{**e, "result": "held" if e["result"] == "adopted" else e["result"]}
                                           for e in dec["events"]]}
    assert held["decision"]["events"][0]["result"] == "held"
    assert held["candidates"] == done["candidates"]
    assert _report_line(out, "- 판단:") == ("- 판단: 원인 보류 — 탐색 분석 적합성 확인에서 채택 원인이 증상과 맞지 않음. 아래 규칙 "
                                          "일치는 로그에서 관측된 것이고 이 이슈의 원인으로 채택하지 않았다 · 이슈 DB에서 버그 아님"
                                          "(시험 절차·설정 조작이 만든 동작으로 알려진 규칙)인 기준 사건 원인: DATA-001-01")
    cl = issue_post.classify(held, None, issue_post.fit_hold_of(out / "check-output.json"))
    assert cl["cls"] == "data > DATA-001 > 원인 보류 — 탐색 분석 적합성 확인에서 채택 원인이 증상과 맞지 않음", cl
    assert not any("해결책" in x for x in cl["next"]), cl["next"]


def test_prior_skips_output_changed_after_check():
    """검사 뒤 explore-output.md가 바뀌면(기록 output_sha256과 다름) 그 가설은 검사 통과로 넘기지 않는다."""
    item = _confirmed()
    out = tmp("tt-sha-") / "x"
    _run(item, out, "--explore")
    run_json("triage.py", ["explore", item["key"], "--out", out])
    (out / "explore-output.md").write_text("가설 없음: 1위 부적합 — 시각이 다르다\n다음 확인: radio 로그\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])
    (out / "explore-output.md").write_text("가설 없음: 고쳐 쓴 이유\n다음 확인: radio 로그\n", encoding="utf-8")
    assert "prior" not in _run(item, out, "--explore")


def test_prior_survives_a_question_turn():
    """질문(needs_input) 턴이 이전 산출물을 지워도 검사 통과한 이전 판단은 state에 남아 답한 재실행에 넘어간다."""
    ws = Workspace()
    log = tmp("tt-prior-q-") / "roaming.log"
    log.write_bytes((REPO / "tests/fixtures/logs/data-roaming-disabled.log").read_bytes())
    args = ["run", "MOCK-9005", "--dry-run", "--issue-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip", "--explore"]
    first = ws.json("triage.py", args)
    # 기준 없이 돈 1위 C=1은 보류 → 조사 모드(11/27) — 탐색 사유는 적합성 확인이 아니라 cause_unconfirmed
    assert first["status"] == "ok" and first["explore"]["reason"] == "cause_unconfirmed", first
    job = ws.job_dir("MOCK-9005")
    ws.json("triage.py", ["explore", "MOCK-9005"])
    (job / "explore-output.md").write_text("가설 없음: 1위 부적합 — 증상 시각과 근거 시각이 다르다\n다음 확인: radio 로그\n",
                                           encoding="utf-8")
    ws.json("triage.py", ["check-output", "MOCK-9005", "--for", "explore"])
    ask = ws.json("triage.py", [*args, "--answer", "time=어제쯤"])            # 읽을 수 없는 답 → 질문 턴
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "time", ask
    assert not (job / "explore-output.md").exists() and not (job / "check-output.json").exists()
    again = ws.json("triage.py", args)                                      # 답한(여기선 다시 자동) 재실행
    assert again["status"] == "ok", again
    assert again["prior"]["none"] == "1위 부적합 — 증상 시각과 근거 시각이 다르다", again.get("prior")
    ws.json("triage.py", ["release", "MOCK-9005"])


def test_prior_keeps_checked_hypotheses_only():
    item = _unresolved()
    out = tmp("tt-prior-") / "x"
    _run(item, out)
    run_json("triage.py", ["explore", item["key"], "--out", out])
    quote = next(line for line in (out / "timeline.md").read_text(encoding="utf-8").splitlines() if line[:2].isdigit())
    (out / "explore-output.md").write_text(
        "가설 1: 캐리어 설정 뒤 데이터 평가 거부\n로그로 확인:\n- " + quote + "\n코드로 추정: 코드 근거 없음\n"
        "반대 근거: 거부 사유 줄 없음\n다음 확인: radio 버퍼\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])
    assert "fit_hold" not in json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]   # fit_check 아님
    assert _report_line(out, "- 결론:").startswith("- 결론: 아는 증상·원인과 맞는 후보 없음")
    again = _run(item, out)
    assert again["prior"] == {"hyps": ["캐리어 설정 뒤 데이터 평가 거부 — 반대: 거부 사유 줄 없음"]}, again.get("prior")
    # 검사에 실패한 출력(형식 불일치)은 넘기지 않는다
    run_json("triage.py", ["explore", item["key"], "--out", out])
    (out / "explore-output.md").write_text("가설 1: 칸이 모자란 가설\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out], expect=1)
    assert "prior" not in _run(item, out)
    # FR-10①(P8): 근거 원문 검사에서 지어낸 인용이 나온 가설은 "검사 통과한 이전 가설"로 넘기지 않는다
    run_json("triage.py", ["explore", item["key"], "--out", out])
    (out / "explore-output.md").write_text(
        "가설 1: 모뎀 펌웨어 충돌\n로그로 확인:\n- modem firmware crashed with assertion in qmi_wds handler\n"
        "코드로 추정: 코드 근거 없음\n반대 근거: 없음\n다음 확인: radio 버퍼\n", encoding="utf-8")
    assert run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])["fabricated"] == 1
    assert "prior" not in _run(item, out)
    # 검사 기록이 없으면(손으로 쓴 출력만) 넘기지 않는다
    (out / "explore-output.md").write_text("가설 없음: x\n다음 확인: y\n", encoding="utf-8")
    assert "prior" not in _run(item, out)


def test_workspace_rerun_carries_prior_top_and_look_and_keeps_answers():
    ws = Workspace()
    look = next(line for line in DATA_LOG.read_text(encoding="utf-8").splitlines() if "DNC" in line).split(": ", 1)[1]
    args = ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA / "MOCK-1001.yaml", "--logs", DATA_LOG]
    ask = ws.json("triage.py", args)
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "code", ask
    first = ws.json("triage.py", [*args, "--answer", "code=skip", "--look-at", look])
    assert first["status"] == "ok" and "prior" not in first, first
    again = ws.json("triage.py", args)                                   # 답(code=skip)은 남아 다시 묻지 않는다
    assert again["status"] == "ok", again
    top = first["candidates"][0]
    assert again["prior"]["top"] == (top["cause"] or top["type"])
    assert len(again["prior"]["looked"]) == 1, again["prior"]          # 가린 기준 줄(원문 아님)
    ws.json("triage.py", ["release", "MOCK-1001"])


def test_auto_scan_result_survives_reuse_cache_hit():
    """재사용 적중이어도 시각 후보(`core.attrs.time_candidates`)·리포트 줄이 같다."""
    ws = Workspace()
    log = tmp("tt-auto-reuse-") / "roaming.log"
    log.write_bytes((REPO / "tests/fixtures/logs/data-roaming-disabled.log").read_bytes())
    args = ["run", "MOCK-9005", "--dry-run", "--issue-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip"]
    first = ws.json("triage.py", args)
    second = ws.json("triage.py", args)
    assert second["reuse"]["hit"] is True, second["reuse"]
    assert second["step_anchor"] == first["step_anchor"] and first["step_anchor"]["time_candidates"]
    assert "증상 시각 후보" in _report_line(ws.job_dir("MOCK-9005"), "- 기준 시각 없음")
    ws.json("triage.py", ["release", "MOCK-9005"])


def test_fit_hold_rewrites_report_obligation_and_reuse_keeps_decision(monkeypatch):
    """P1-1: 작업 디렉토리 JOB에서 탐색 적합성 확인이 판단을 보류로 바꾸면, run이 남긴 리포트 표시 의무(같은 key)를 고친 줄로
    다시 남긴다 — show_guard가 옛 "원인 채택" 줄을 보이라고 하지 않는다. 캐시 적중(재사용)이면 판단·판단 줄이 같다(P2-7)."""
    sys.path.insert(0, str(plugin_root() / "scripts"))
    from common import shown
    ws = Workspace()
    log = padded_log(REPO / "tests/fixtures/logs/data-roaming-disabled.log", tmp("tt-dec-shown-") / "roaming.log")   # P1-2: 채택되게
    args = ["run", "MOCK-9005", "--dry-run", "--issue-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip", "--explore", "--look-at",
            # 실패 줄을 시각째 붙여 넣는다 — 같은 줄이 두 번(10초 간격) 있어 시각으로 한 곳을 고른다(단계 5 §8-5)
            "09-22 08:00:03.500  1234  1250 W DNC-1: Data evaluation: evaluation reason:ROAMING_ENABLED_CHANGED, "
            "Data disallowed reasons: ROAMING_DISABLED, candidate profile=null"]
    first = ws.json("triage.py", args)
    job = ws.job_dir("MOCK-9005")
    old = next(x for x in (job / "report.md").read_text(encoding="utf-8").splitlines() if x.startswith("- 판단:"))
    assert first["decision"]["state"] == "accepted" and old.startswith("- 판단: 원인 채택 — "), first["decision"]
    again = ws.json("triage.py", args)
    assert again["reuse"]["hit"] is True and again["decision"] == first["decision"]
    assert old in (job / "report.md").read_text(encoding="utf-8").splitlines()
    ws.json("triage.py", ["explore", "MOCK-9005"])
    (job / "explore-output.md").write_text("가설 없음: 1위 부적합 — 증상 시각과 근거 시각이 다르다\n다음 확인: radio 로그\n",
                                           encoding="utf-8")
    ws.json("triage.py", ["check-output", "MOCK-9005", "--for", "explore"])
    new = next(x for x in (job / "report.md").read_text(encoding="utf-8").splitlines() if x.startswith("- 판단:"))
    assert new.startswith("- 판단: 원인 보류 — 탐색 분석 적합성 확인")
    key = f"report:MOCK-9005#{again['run']}"
    recs = [json.loads(x) for x in (job.parent / ".shown" / "log.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip() and json.loads(x).get("key") == key]
    assert len(recs) >= 2 and old in recs[0]["lines"]
    ob = shown._obligation("report", key, 0, 1, recs[-1])
    gap = shown.missing(ob, [])
    assert new in gap and old not in gap
    assert not any(x.endswith(old[2:]) for x in gap)
    # run 기록·check-output 기록을 두 Bash 호출에 순서대로 고정하면 열린 리포트 의무는 하나이고, 그 줄은 새 보류 줄이다
    pair = [recs[0], recs[-1]]
    assert pair[0]["script"] == "triage" and pair[1]["script"] == "triage"
    seq = [{"kind": "tool", "name": "Bash", "id": f"b{k}", "input": {"command": cmd}, "result": "{}", "error": False}
           for k, cmd in enumerate(["python3 triage.py run MOCK-9005", "python3 triage.py check-output MOCK-9005 --for explore"])]
    monkeypatch.setattr(shown, "anchor", lambda s, r: list(enumerate(r)))
    live = [ob for ob in shown.record_obligations(seq, pair) if ob.open and ob.kind == "report"]
    assert len(live) == 1 and live[0].start == 1, [(ob.key, ob.start) for ob in live]
    assert new in live[0].lines and old not in live[0].lines
    ws.json("triage.py", ["release", "MOCK-9005"])


def test_look_at_found_only_by_word_order_is_never_confirmed():
    """sim1121 리뷰 P1-3: 사람이 대충 적은 기준 줄을 낱말 순서로만 찾았으면(찾기 방식 words) 채택이어도 실패 지점을 확정(confirmed)으로
    올리지 않는다 — 모델이 고른 줄처럼 found·near. 줄 그대로 붙인 기준 줄은 지금처럼 확정까지 간다(대조)."""
    item = _confirmed()
    item = {**item, "logs": [str(padded_log((LABELSET.parent / p).resolve())) for p in item["logs"]]}
    exact = _run(item, tmp("tt-loose-") / "exact", "--look-at", "notifyDataEnabledChanged: enabled=false")
    loose = _run(item, tmp("tt-loose-") / "loose", "--look-at", "DSMGR-0 notifyDataEnabledChanged reason=USER")
    assert exact["decision"]["location"] == {"state": "confirmed", "source": "look_at", "kind": "point"}
    assert loose["decision"]["state"] == exact["decision"]["state"] == "accepted"
    assert loose["decision"]["location"] == {"state": "found", "source": "look_at", "kind": "near"}


def _padded() -> dict:
    item = _confirmed()
    return {**item, "logs": [str(padded_log((LABELSET.parent / p).resolve())) for p in item["logs"]]}


UNFIT_ARGS = ("--explore", "--look-at", LOOK, "--look-note", "재시도가 오는지")


def _accepted_job(item: dict, name: str) -> Path:
    out = tmp(f"tt-unfit-{name}-") / "x"
    done = _run(item, out, *UNFIT_ARGS)
    assert done["decision"]["state"] == "accepted" and done["explore"]["reason"] == "fit_check", done["decision"]
    run_json("triage.py", ["explore", item["key"], "--out", out])
    return out


def _hyp_output(out: Path, tail: str) -> None:
    quote = next(line for line in (out / "timeline.md").read_text(encoding="utf-8").splitlines() if line[:2].isdigit())
    (out / "explore-output.md").write_text(
        "가설 1: 시험 장비 설정이 실패를 만들었다\n로그로 확인:\n- " + quote + "\n코드로 추정: 코드 근거 없음\n"
        "반대 근거: 장비 로그 없음\n다음 확인: 장비 담당에게 셀 설정 확인 후 같은 조건으로 재시험\n" + tail, encoding="utf-8")


def test_unfit_mark_holds_accepted_top_even_with_hypotheses_and_carries_to_next_run():
    """sim1122 F2(S-03): 기준 줄로 채택된 1위를 모델이 `1위 판단: 부적합`으로 적으면 다른 가설이 있어도 보류(held/fit_check)로
    바뀌고 결론·해결책·판단 줄이 보류에 맞는다. 표시는 다음 실행 `prior.unfit`으로 넘어간다. 칸이 없으면 채택 그대로 + 경고 줄,
    `적합`이면 채택 그대로(경고 없음). 확인할 내용 줄 꼬리는 답 자리를 가리킨다(F7)."""
    item = _padded()

    def accepted_job(name: str) -> Path:
        return _accepted_job(item, name)

    hyp_output = _hyp_output

    held = accepted_job("held")
    hyp_output(held, "\n1위 판단: 부적합 — 데이터 꺼짐은 이번 실패 시각과 맞지 않는다\n")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", held])
    assert "warning" not in checked
    analysis = json.loads((held / "analysis.json").read_text(encoding="utf-8"))
    assert (analysis["decision"]["state"], analysis["decision"]["reason"]) == ("held", "fit_check")
    assert _report_line(held, "- 판단:").startswith("- 판단: 원인 보류 — 탐색 분석 적합성 확인에서")
    assert _report_line(held, "- 결론:").startswith("- 결론: 채택 후보 DATA-001-01가 증상과 맞지 않아 보류")
    assert _report_line(held, "- 해결책(1위 기준, 보류됨): ").endswith("해결책 검증: 보류(1위 부적합)")
    assert _report_line(held, "  - 1위 판단(모델): ") == ("  - 1위 판단(모델): 부적합 — 데이터 꺼짐은 이번 실패 시각과 맞지 않는다 "
                                                      "→ 1위 DATA-001-01 채택을 보류로 바꿨다")
    assert _report_line(held, "- 확인할 내용(사용자 질문): ").endswith("— 답: 아래 탐색 분석 줄(가설 1의 로그로 확인·반대 근거)과 "
                                                                 "`- 원인:`·다음 확인 줄")
    rec = json.loads((held / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert rec["fit_hold"] == "DATA-001-01" and rec["top_fit"] == "부적합" and rec["fabricated"] == 0
    again = _run(item, held, *UNFIT_ARGS)
    assert again["prior"]["unfit"] == "DATA-001-01 — 데이터 꺼짐은 이번 실패 시각과 맞지 않는다", again["prior"]
    assert again["prior"]["hyps"] == ["시험 장비 설정이 실패를 만들었다 — 반대: 장비 로그 없음"]
    # RP-6: 같은 원인이 다시 채택되면 run이 보류한다(모델이 다시 적지 않아도) — 판단 줄·경고에 이유
    assert (again["decision"]["state"], again["decision"]["reason"], again["decision"]["selected"]) == ("held", "fit_check", None)
    assert "앞 실행에서 모델이 1위 판단 부적합으로 표시한 원인 DATA-001-01가 다시 채택돼 보류했다(prior.unfit)" in again["warnings"]
    assert _report_line(held, "- 판단:").startswith("- 판단: 원인 보류 — 탐색 분석 적합성 확인에서")
    assert again["candidates"][0]["cause"] == "DATA-001-01" and again["candidates"][0]["C"] == 1      # 판정·순위는 그대로

    # RP-1: 원인 ID를 함께 적은 형식도 부적합으로 읽는다
    for name, tail in (("id", "1위 판단: DATA-001-01 부적합 — 시각이 다르다\n"), ("paren", "1위 판단(DATA-001-01): 부적합.\n")):
        job = accepted_job(name)
        hyp_output(job, tail)
        assert "warning" not in run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", job])
        assert json.loads((job / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "held", name
    # RP-7: 부적합으로 적은 원인이 채택 원인과 다르면 보류하지 않고 경고
    other = accepted_job("other")
    hyp_output(other, "1위 판단: DATA-002-01 부적합 — 다른 원인\n")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", other])
    assert checked["warning"] == ("- 경고: 1위 판단의 부적합 원인(DATA-002-01)이 채택 원인 DATA-001-01와 맞지 않아 보류하지 않았다"
                                  "(`1위 판단: DATA-001-01 …`로 다시 확인)")
    assert json.loads((other / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "accepted"
    # 못 읽은 칸은 "칸 없음"이 아니라 "읽지 못함"
    bad = accepted_job("bad")
    hyp_output(bad, "1위 판단: 맞지 않음\n")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", bad])
    assert checked["warning"].startswith("- 경고: 1위 판단 칸을 읽지 못함 — ")
    assert json.loads((bad / "check-output.json").read_text(encoding="utf-8"))["explore"]["top_fit"] == "읽지 못함"
    # RP-15: 가설 없음 + 적합이면 보류 이유를 밝힌다
    none = accepted_job("none")
    (none / "explore-output.md").write_text("가설 없음: 근거 줄이 없다\n다음 확인: radio 로그\n1위 판단: 적합 — 아마\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", none])
    assert _report_line(none, "  - 1위 판단(모델): ") == ("  - 1위 판단(모델): 적합 — 아마 → 가설 없음이라 1위 DATA-001-01 보류"
                                                      "(1위 판단 '적합'과 맞지 않음 — 탐색 출력 확인)")

    plain = accepted_job("plain")
    hyp_output(plain, "")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", plain])
    assert checked["warning"] == "- 경고: 1위 판단 칸 없음 — 1위 DATA-001-01 채택은 그대로다(탐색 가설이 1위와 맞는지 확인)"
    assert json.loads((plain / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "accepted"
    assert _report_line(plain, "  - 경고: 1위 판단 칸 없음") is not None
    assert "fit_hold" not in json.loads((plain / "check-output.json").read_text(encoding="utf-8"))["explore"]

    fit = accepted_job("fit")
    hyp_output(fit, "1위 판단: 적합 — 데이터 꺼짐 줄이 실패 직전\n")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", fit])
    assert "warning" not in checked and _report_line(fit, "  - 경고:") is None
    assert json.loads((fit / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "accepted"
    assert _report_line(fit, "  - 1위 판단(모델): ") == "  - 1위 판단(모델): 적합 — 데이터 꺼짐 줄이 실패 직전"


def test_prior_unfit_survives_unmarked_check_until_marked_fit(tmp_path):
    """RP-6: 앞 실행의 `prior.unfit`은 뒤 검사가 1위 판단 칸 없이 끝나도 남고, `1위 판단: 적합`이라고 다시 적으면 지운다
    (오프라인 실행은 state를 쓰지 않으므로 read_prior를 직접 부른다). 같은 원인이 채택되면 run 판단이 보류로 바뀐다."""
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import hashlib

    from triagelib import report
    from triagelib.cache import State
    from triagelib.driver import Driver
    drv = Driver.__new__(Driver)
    drv.job = tmp_path
    drv.state, drv.offline = State(tmp_path / "triage-state.json"), False
    drv.state.job["prior_explore"] = {"unfit": "DATA-001-01 — 시각이 다르다"}

    def checked(text: str, top_fit: str | None) -> dict | None:
        (tmp_path / "explore-output.md").write_text(text, encoding="utf-8")
        rec = {"mode": "explore", "output_sha256": hashlib.sha256(text.encode()).hexdigest(), "source": "timeline.md",
               "fabricated": 0, **({"top_fit": top_fit} if top_fit else {})}
        (tmp_path / "check-output.json").write_text(json.dumps({"explore": rec}), encoding="utf-8")
        return drv.read_prior()

    hyp = "가설 1: x\n로그로 확인:\n- 10:00:00.000 - E t m\n코드로 추정: 없음\n반대 근거: 없음\n다음 확인: y\n"
    assert checked(hyp, None)["unfit"] == "DATA-001-01 — 시각이 다르다"             # 칸 없이 검사해도 남는다
    assert "unfit" not in (checked(hyp + "1위 판단: DATA-001-01 적합 — 맞다\n", "적합") or {})
    accepted = {"state": "accepted", "reason": "anchored_top", "selected": {"cause": "DATA-001-01"}, "counter": {"cause": "X"},
                "events": [{"result": "adopted"}, {"result": "observed"}]}
    held = report.prior_unfit_hold(accepted, {"unfit": "DATA-001-01 — 시각이 다르다"})
    assert held == {"state": "held", "reason": "fit_check", "selected": None,
                    "events": [{"result": "held"}, {"result": "observed"}]}
    assert report.prior_unfit_hold(accepted, {"unfit": "DATA-002-01 — x"}) is None
    assert report.prior_unfit_hold({**accepted, "state": "held"}, {"unfit": "DATA-001-01 — x"}) is None


def test_prior_unfit_offline_chain_until_marked_fit_by_its_id():
    """CP-2·CP-3·CP-4(실제 오프라인 경로 — 포털·모의 운용과 같다): 부적합 표시는 뒤 검사가 1위 판단 칸 없이 끝나도 셋째 실행까지
    남는다(state가 없어 앞 analysis.json의 prior.unfit을 읽는다). 다른 원인 ID에 `적합`이라고 적어도 지워지지 않는다. 그 원인에
    `적합`이라고 적으면 이번 결과는 보류 그대로라고 알리고(경고), 다음 run에서 채택된다."""
    item = _padded()
    out = _accepted_job(item, "chain")
    _hyp_output(out, "1위 판단: DATA-001-01 부적합 — 시각이 다르다\n")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])

    def rerun(tail: str | None) -> tuple[dict, dict]:
        done = _run(item, out, *UNFIT_ARGS)
        checked = {}
        if tail is not None:
            run_json("triage.py", ["explore", item["key"], "--out", out])
            _hyp_output(out, tail)
            checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])
        return done, checked

    unfit = "DATA-001-01 — 시각이 다르다"
    for tail in ("", "1위 판단: DATA-002-01 적합 — 다른 원인\n"):     # 칸 없음(CP-2) → 다른 ID 적합(CP-4)
        done, checked = rerun(tail)
        assert done["decision"]["state"] == "held" and done["prior"]["unfit"] == unfit, (tail, done["decision"], done.get("prior"))
        assert "warning" not in checked, checked
    done, checked = rerun(None)                                        # 셋째 실행 이후에도 남았다
    assert done["decision"]["state"] == "held" and done["prior"]["unfit"] == unfit
    run_json("triage.py", ["explore", item["key"], "--out", out])
    _hyp_output(out, "1위 판단: DATA-001-01 적합 — 새 근거로 맞다\n")
    checked = run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out])
    assert checked["warning"] == ("- 경고: 1위 판단 적합 — 앞 실행 부적합 원인 DATA-001-01의 보류(prior.unfit)는 이번 결과에 그대로다"
                                  "(같은 인자로 run을 다시 하면 보류가 풀린다)"), checked
    rec = json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert (rec["top_fit"], rec["top_fit_cause"]) == ("적합", "DATA-001-01")
    done, _ = rerun(None)
    assert done["decision"]["state"] == "accepted" and "unfit" not in (done.get("prior") or {}), done.get("prior")


def test_prior_unfit_dropped_when_workspace_rerun_has_new_logs():
    """CP-3: 작업 폴더 실행에서 로그를 바꿔 다시 돌리면 옛 로그 때의 부적합 표시로 보류하지 않고 state에서도 지운다.
    같은 로그로 다시 돌리면 보류한다(RP-6 그대로)."""
    ws = Workspace()
    src = REPO / "tests/fixtures/logs/data-roaming-disabled.log"
    log = padded_log(src, tmp("tt-unfit-logs-") / "roaming.log")
    look = ("09-22 08:00:03.500  1234  1250 W DNC-1: Data evaluation: evaluation reason:ROAMING_ENABLED_CHANGED, "
            "Data disallowed reasons: ROAMING_DISABLED, candidate profile=null")
    base = ["run", "MOCK-9005", "--dry-run", "--issue-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml", "--code", "skip",
            "--explore", "--look-at", look]
    first = ws.json("triage.py", [*base, "--logs", log])
    assert first["decision"]["state"] == "accepted", first["decision"]
    job = ws.job_dir("MOCK-9005")
    ws.json("triage.py", ["explore", "MOCK-9005"])
    (job / "explore-output.md").write_text("가설 없음: 1위 부적합 — 증상 시각과 근거 시각이 다르다\n다음 확인: radio 로그\n",
                                           encoding="utf-8")
    ws.json("triage.py", ["check-output", "MOCK-9005", "--for", "explore"])
    same = ws.json("triage.py", [*base, "--logs", log])
    assert same["decision"]["state"] == "held" and same["prior"]["unfit"].startswith("DATA-"), same.get("prior")
    other = log.with_name("roaming-retest.log")                         # 다시 시험한 로그(이름·내용 해시가 다르다)
    other.write_bytes(log.read_bytes())
    new = ws.json("triage.py", [*base, "--logs", other])
    assert "logs" in new["reuse"]["changed"] and new["decision"]["state"] == "accepted", (new["reuse"], new["decision"])
    assert "unfit" not in (new.get("prior") or {}) and not any("prior.unfit" in w for w in new.get("warnings") or [])
    again = ws.json("triage.py", [*base, "--logs", other])                 # state에서도 지웠다
    assert again["decision"]["state"] == "accepted" and "unfit" not in (again.get("prior") or {}), again.get("prior")
    ws.json("triage.py", ["release", "MOCK-9005"])


def _normal_output(out: Path, quote: str, tail: str = "") -> None:
    (out / "explore-output.md").write_text(
        "가설 1: 정상(설계상 정상 동작) — 실패 뒤 같은 창에 회복 줄이 있다\n원인 층: 원인 아님(정상 동작)\n로그로 확인:\n- " + quote +
        "\n코드로 추정: 코드 근거 없음\n반대 근거: 실패가 되풀이되는지는 이 구간만으로 모른다\n다음 확인: 같은 조건 재시험에서 실패가 다시 나는지\n"
        + tail, encoding="utf-8")


def test_normal_hypothesis_one_holds_fit_check_only_with_quoted_line():
    """정상 가설(explore.md 종합 판단 0): 적합성 확인에서 가설 1이 `정상`이고 `로그로 확인` 인용이 원문에 있으면 1위 채택을 보류한다
    (부적합 보류와 같은 길 — 판단 held/fit_check, 결론·해결책 줄 보류). 인용이 원문에 없으면 정상으로 보지 않고 `[정상 근거 없음]`,
    채택 그대로(1위 판단 칸 없음 경고)."""
    import issue_post

    item = _padded()
    held = _accepted_job(item, "normal")
    quote = next(line for line in (held / "timeline.md").read_text(encoding="utf-8").splitlines() if line[:2].isdigit())
    _normal_output(held, quote, "1위 판단: 적합 — 1위 문구가 보인다\n")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", held])
    analysis = json.loads((held / "analysis.json").read_text(encoding="utf-8"))
    assert (analysis["decision"]["state"], analysis["decision"]["reason"]) == ("held", "fit_check")
    assert _report_line(held, "  - 1위 판단(모델): ").endswith("→ 1번 가설이 정상(설계상 정상 동작)이라 1위 DATA-001-01 보류")
    # 리뷰 4: 정상 보류는 부적합 문구가 아니다 — 결론·해결책·Jira·다음 실행 경고 모두
    assert _report_line(held, "- 결론:") == ("- 결론: 채택 후보 DATA-001-01는 탐색 분석이 설계상 정상 동작으로 봄 — 채택 보류(탐색 분석 "
                                            "참조). 다음: Step 7에서 보류를 고르거나 근거 로그 확인")
    assert _report_line(held, "- 해결책(1위 기준, 보류됨): ").endswith("해결책 검증: 보류(탐색 분석이 설계상 정상 동작으로 봄)")
    rec = json.loads((held / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert rec["fit_hold"] == "DATA-001-01" and rec["normal"] == [1] and rec["fit_hold_reason"] == "normal"
    analysis = json.loads((held / "analysis.json").read_text(encoding="utf-8"))
    cl = issue_post.classify({**analysis, "decision": {**analysis["decision"], "state": "accepted"}}, None,
                             issue_post.fit_hold_of(held / "check-output.json"), issue_post.fit_hold_normal(held / "check-output.json"))
    assert "탐색 분석 적합성 확인: 설계상 정상 동작으로 봐 채택 보류" in cl["lines"]
    assert any(x.endswith("(해결책 검증: 보류(탐색 분석이 설계상 정상 동작으로 봄))") for x in cl["next"])
    assert _report_line(held, "- 판단:").startswith("- 판단: 원인 보류 — 탐색 분석이 채택 원인의 줄을 설계상 정상 동작으로 봄")
    cls = issue_post.classify(analysis, None, issue_post.fit_hold_of(held / "check-output.json"), True)["cls"]
    assert cls.endswith("원인 보류 — 탐색 분석이 채택 원인의 줄을 설계상 정상 동작으로 봄"), cls
    again = _run(item, held, *UNFIT_ARGS)
    assert again["prior"]["unfit"] == "DATA-001-01 — 탐색 분석이 설계상 정상 동작으로 봄"
    assert "앞 실행에서 탐색 분석이 설계상 정상 동작으로 봄 원인 DATA-001-01가 다시 채택돼 보류했다(prior.unfit)" in again["warnings"]
    # 확인 리뷰 A: 다시 run하면 check-output 기록은 지워지고 판단은 prior.unfit에서 다시 만든다 — 사유는 prior.unfit_reason 하나로
    assert again["prior"]["unfit_reason"] == "normal" and not (held / "check-output.json").exists()
    assert _report_line(held, "- 판단:").startswith("- 판단: 원인 보류 — 탐색 분석이 채택 원인의 줄을 설계상 정상 동작으로 봄")
    assert _report_line(held, "- 결론:").startswith("- 결론: 원인 보류 — 탐색 분석이 채택 원인의 줄을 설계상 정상 동작으로 봄")
    rerun = json.loads((held / "analysis.json").read_text(encoding="utf-8"))
    path = held / "check-output.json"
    assert issue_post.classify(rerun, None, issue_post.fit_hold_of(path), issue_post.fit_hold_normal(path, rerun))["cls"].endswith(
        "원인 보류 — 탐색 분석이 채택 원인의 줄을 설계상 정상 동작으로 봄")
    old = {**rerun, "prior": {k: v for k, v in rerun["prior"].items() if k != "unfit_reason"}}      # 옛 기록 = unfit
    assert issue_post.classify(old, None, None, issue_post.fit_hold_normal(path, old))["cls"].endswith(
        "탐색 분석 적합성 확인에서 채택 원인이 증상과 맞지 않음")
    bare = _accepted_job(item, "normal-bare")                 # 1위 판단 칸이 없어도 정상 보류(하위 줄로 알린다)
    _normal_output(bare, quote)
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", bare])
    assert _report_line(bare, "  - 1번 가설이 정상") == "  - 1번 가설이 정상(설계상 정상 동작, 근거 줄 원문 확인)이라 1위 DATA-001-01 채택을 보류로 바꿨다"
    fake = _accepted_job(item, "normal-fake")                 # 인용이 원문에 없음: 정상으로 보지 않는다
    _normal_output(fake, "10:00:31.000 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", fake])
    assert json.loads((fake / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "accepted"
    assert _report_line(fake, "  - 가설 1 [근거 불일치 1] [정상 근거 없음]: 정상(설계상 정상 동작)")
    assert _report_line(fake, "  - 경고: 1위 판단 칸 없음")
    assert "normal" not in json.loads((fake / "check-output.json").read_text(encoding="utf-8"))["explore"]



def test_normal_needs_ok_quote_and_follows_most_likely():
    """리뷰 2·3: 정상 근거는 원문 검사 `ok`만(원문에 없는 짧은 `LOADED`는 약함이라 정상 아님). `가장 유력: N`이면 그 가설로 보류를
    정한다 — 가설 2가 정상이면 보류, 가설 1이 정상이어도 가장 유력이 가설 2(실패)면 보류하지 않는다."""
    item = _padded()
    weak = _accepted_job(item, "normal-weak")
    _normal_output(weak, "LOADED")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", weak])
    assert json.loads((weak / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "accepted"
    assert _report_line(weak, "  - 가설 1 [정상 근거 없음]: 정상(설계상 정상 동작)")
    quote = next(line for line in (weak / "timeline.md").read_text(encoding="utf-8").splitlines() if line[:2].isdigit())
    fail = ("가설 {n}: 시험 장비 설정이 실패를 만들었다\n로그로 확인:\n- " + quote + "\n코드로 추정: 코드 근거 없음\n"
            "반대 근거: 장비 로그 없음\n다음 확인: 장비 담당에게 셀 설정 확인\n")

    def normal(n):
        return (f"가설 {n}: 정상(설계상 정상 동작) — 회복 줄이 있다\n로그로 확인:\n- " + quote + "\n코드로 추정: 코드 근거 없음\n"
                "반대 근거: 되풀이 여부 모름\n다음 확인: 재시험\n")
    two = _accepted_job(item, "normal-two")
    (two / "explore-output.md").write_text(fail.format(n=1) + normal(2) + "가장 유력: 2\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", two])
    assert json.loads((two / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "held"
    assert _report_line(two, "  - 2번 가설이 정상") == "  - 2번 가설이 정상(설계상 정상 동작, 근거 줄 원문 확인)이라 1위 DATA-001-01 채택을 보류로 바꿨다"
    bad = _accepted_job(item, "normal-badtop")              # 없는 번호: 1번 가설로 보고 경고 하위 줄(조용히 넘어가지 않는다)
    (bad / "explore-output.md").write_text(normal(1) + fail.format(n=2) + "가장 유력: 7\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", bad])
    assert json.loads((bad / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "held"
    assert _report_line(bad, "  - 경고: `가장 유력: 7`") == "  - 경고: `가장 유력: 7`을 가설 번호로 읽지 못해(없는 번호) 1번 가설로 적합성 확인을 봤다"
    one = _accepted_job(item, "normal-one")
    (one / "explore-output.md").write_text(normal(1) + fail.format(n=2) + "가장 유력: 2\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", one])
    assert json.loads((one / "analysis.json").read_text(encoding="utf-8"))["decision"]["state"] == "accepted"
    assert "fit_hold" not in json.loads((one / "check-output.json").read_text(encoding="utf-8"))["explore"]


def test_prior_unfit_not_carried_from_check_with_fabricated_quotes(tmp_path):
    """코덱스 K04: 원문에 없는 인용이 있는 검토의 1위 부적합·정상 판단은 가설처럼 다음 실행에 넘기지 않는다(그 실행의 보류는 그대로).
    인용이 0개면(가설 없음) 검사할 것이 없어 지금처럼 넘긴다."""
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import hashlib

    from triagelib.cache import State
    from triagelib.driver import Driver
    drv = Driver.__new__(Driver)
    drv.job = tmp_path
    drv.state, drv.offline = State(tmp_path / "triage-state.json"), False
    text = ("가설 1: x\n로그로 확인:\n- 10:00:00.000 - E t m\n코드로 추정: 없음\n반대 근거: 없음\n다음 확인: y\n"
            "1위 판단: DATA-001-01 부적합 — 정상 종료\n")

    def prior(fabricated: int, reason: str = "unfit") -> dict:
        (tmp_path / "explore-output.md").write_text(text, encoding="utf-8")
        rec = {"mode": "explore", "output_sha256": hashlib.sha256(text.encode()).hexdigest(), "source": "timeline.md",
               "fabricated": fabricated, "fit_hold": "DATA-001-01", "fit_hold_reason": reason, "top_fit": "부적합"}
        (tmp_path / "check-output.json").write_text(json.dumps({"explore": rec}), encoding="utf-8")
        drv.state.job.pop("prior_explore", None)
        return drv.read_prior() or {}

    assert "unfit" not in prior(1) and "unfit_reason" not in prior(1, "normal")
    assert prior(0)["unfit"] == "DATA-001-01 — 정상 종료"
    assert prior(0, "normal")["unfit_reason"] == "normal"


# -- 5-1 반증 → 5-2 적합성 확인(11/27 C23) --------------------------------------------------------------------


def test_adopted_without_flag_prepares_fit_check_only_unless_turned_off():
    """채택 + 기본 ask(플래그·확인할 내용 없음)는 5-2를 열지 않고 연다면 쓸 값만 둔다(`fit_later` — 판단은 `explore` 한 곳).
    `never`·`--no-explore`면 그것도 두지 않는다(끄는 쪽이 이긴다)."""
    from types import SimpleNamespace
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import importlib
    triage = importlib.import_module("triage")
    acc = {"state": "accepted"}
    drv = SimpleNamespace(cfg={}, warnings=[], args=SimpleNamespace(explore=None), look_inputs=lambda: {"at": None, "note": None})
    assert triage.Driver.explore(drv, [{"C": 1}], acc) is None and drv.fit_later == {"reason": "fit_check", "when": "ask",
                                                                                      "note": ASK_NOTE}
    drv.args.explore = False
    assert triage.Driver.explore(drv, [{"C": 1}], acc) is None and drv.fit_later is None
    drv.args.explore, drv.cfg = None, {"explore": {"when": "never"}}
    assert triage.Driver.explore(drv, [{"C": 1}], acc) is None and drv.fit_later is None
    drv.cfg = {}
    assert triage.Driver.explore(drv, [{"C": 0}])["reason"] == "cause_unconfirmed" and drv.fit_later is None     # 조사 모드는 대상 아님


def test_opened_fit_check_carries_deep_checks_into_timeline_and_survives_rerun():
    """채택 run은 입력만 준비하고(`triage.py explore`는 해당 없음 1), check-output이 연 뒤(analysis.json `explore` — 여는 쪽은
    test_check_output) `triage.py explore`는 5-1 후보 확인 기록을 타임라인 머리 데이터 줄로 싣는다(모듈 보기 E1 재계산도 같은 바이트).
    탐색 중 다시 한 run(`--look-at-source model`)은 적합성 확인을 이어 가고(타임라인 다시 만듦, 지워진 5-1 줄은 없음),
    `--no-explore`면 이어 가지 않는다."""
    item = _padded()
    out = tmp("tt-c23-") / "x"
    first = _run(item, out, "--look-at", LOOK)
    assert first["decision"]["state"] == "accepted" and "explore" not in first
    spec = json.loads((out / "explore-input.json").read_text(encoding="utf-8"))
    assert spec["fit_later"] == {"reason": "fit_check", "when": "ask", "note": ASK_NOTE}
    assert run("triage.py", ["explore", item["key"], "--out", out]).returncode == 1 and not (out / "timeline.md").exists()
    analysis = json.loads((out / "analysis.json").read_text(encoding="utf-8"))
    (out / "analysis.json").write_text(json.dumps({**analysis, "explore": spec["fit_later"]}, ensure_ascii=False), encoding="utf-8")
    checks = ["DATA-001-01 아님 — 찾았는데 없음: 데이터 꺼짐 줄", "DATA-001-02 모름"]
    (out / "check-output.json").write_text(json.dumps({"deep": {"mode": "module", "checks": checks}}, ensure_ascii=False),
                                           encoding="utf-8")
    assert run_json("triage.py", ["explore", item["key"], "--out", out])["timeline"] == "timeline.md"
    text = (out / "timeline.md").read_text(encoding="utf-8")
    assert "".join(f"- 심층 분석 후보 확인(데이터): {c}\n" for c in checks) in text.split("- 줄: ")[0], text[:1500]
    assert json.loads((out / "explore-input.json").read_text(encoding="utf-8"))["deep_checks"] == checks
    sys.path.insert(0, str(plugin_root() / "scripts"))
    from triagelib import modulecmd
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))
    assert modulecmd._explore_inputs(out, item["key"], events, {}, AssertionError)["flows"][-2:] == [
        f"- 심층 분석 후보 확인(데이터): {c}" for c in checks]           # E1: 같은 머리로 다시 그려 바이트가 맞는다

    again = _run(item, out, "--look-at-source", "model", "--look-at", LOOK)
    assert again["decision"]["state"] == "accepted" and again["explore"]["reason"] == "fit_check", again.get("explore")
    assert (out / "timeline.md").is_file() and "심층 분석 후보 확인" not in (out / "timeline.md").read_text(encoding="utf-8")
    assert _report_line(out, "- 탐색 분석").startswith("- 탐색 분석 (추정, timeline.md ")
    off = _run(item, out, "--look-at-source", "model", "--look-at", LOOK, "--no-explore")
    assert "explore" not in off and not (out / "timeline.md").exists() and not (out / "explore-input.json").exists()
