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
    item = _confirmed()
    plain = _run(item, tmp("tt-fit-") / "a")
    assert plain["candidates"][0]["C"] == 1 and "explore" not in plain          # --explore 없는 세션은 이전과 같다
    no = _run(item, tmp("tt-fit-") / "n", "--no-explore")
    assert "explore" not in no
    out = tmp("tt-fit-") / "b"
    flagged = _run(item, out, "--explore")
    assert flagged["explore"] == {"reason": "fit_check", "when": "ask", "note": ASK_NOTE}
    assert (out / "explore-input.json").is_file()
    assert _report_line(out, "- 탐색 분석").startswith("- 탐색 분석 (추정): 미실행")
    always = _run(item, tmp("tt-fit-") / "c", root=plugin_root(explore={"when": "always"}))
    assert always["explore"] == {"reason": "fit_check", "when": "always"}
    never = _run(item, tmp("tt-fit-") / "d", "--explore", root=plugin_root(explore={"when": "never"}))
    assert "explore" not in never                                       # never면 플래그가 있어도 열지 않는다
    # FR-07(P5): 끄는 쪽이 이긴다 — --no-explore면 always여도 열지 않는다
    off = _run(item, tmp("tt-fit-") / "g", "--no-explore", root=plugin_root(explore={"when": "always"}))
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
    assert triage.Driver.explore(drv, [{"C": 0}])["reason"] == "cause_unconfirmed"
    assert triage.Driver.explore(drv, [])["reason"] == "no_candidate"
    assert triage.Driver.explore(drv, [{"C": 1}])["reason"] == "fit_check"
    drv.args.explore = None
    assert triage.Driver.explore(drv, [{"C": 1}]) is None
    always = SimpleNamespace(cfg={"explore": {"when": "always"}}, warnings=[], args=SimpleNamespace(explore=False),
                             look_inputs=no_note)
    assert triage.Driver.explore(always, [{"C": 1}]) is None                       # --no-explore > always (P5)
    assert triage.Driver.explore(always, [{"C": 0}])["reason"] == "cause_unconfirmed"   # 기존 두 사유는 그대로
    # 잘못된 explore.when은 C=1 경로에서도 먼저 경고하고 ask로 본다(조용히 꺼지지 않는다)
    bad = SimpleNamespace(cfg={"explore": {"when": "sometimes"}}, warnings=[], args=SimpleNamespace(explore=True),
                          look_inputs=no_note)
    assert triage.Driver.explore(bad, [{"C": 1}])["reason"] == "fit_check"
    assert bad.warnings == ["explore.when 값이 잘못됐다(sometimes). ask로 본다"]
    # FR-16(P9): 확인할 내용(--look-note)이 있으면 플래그 없이도 fit_check를 연다 — never·--no-explore는 그래도 끈다
    note = lambda: {"at": None, "note": "재시도가 오는지"}  # noqa: E731
    asked = SimpleNamespace(cfg={}, warnings=[], args=SimpleNamespace(explore=None), look_inputs=note)
    assert triage.Driver.explore(asked, [{"C": 1}])["reason"] == "fit_check"
    asked.args.explore = False
    assert triage.Driver.explore(asked, [{"C": 1}]) is None
    asked.args.explore, asked.cfg = None, {"explore": {"when": "never"}}
    assert triage.Driver.explore(asked, [{"C": 1}]) is None


def test_no_explore_is_in_request_hash_so_always_fit_check_is_not_reused():
    """P5: --no-explore는 입력 해시(args)에 든다 — 없으면 always 설정에서 fit_check를 연 결과가 --no-explore 실행에 재사용됐다."""
    ws = Workspace(root=plugin_root(explore={"when": "always"}))
    log = tmp("tt-fit-hash-") / "roaming.log"
    log.write_bytes((REPO / "tests/fixtures/logs/data-roaming-disabled.log").read_bytes())
    args = ["run", "MOCK-9005", "--dry-run", "--issue-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip"]
    first = ws.json("triage.py", args)
    assert first["status"] == "ok" and first["explore"]["reason"] == "fit_check", first
    off = ws.json("triage.py", [*args, "--no-explore"])
    assert off["reuse"]["hit"] is False and "args" in off["reuse"]["changed"] and "explore" not in off, off["reuse"]
    again = ws.json("triage.py", args)                                   # 플래그 없음은 처음 해시 그대로
    assert again["explore"]["reason"] == "fit_check"
    ws.json("triage.py", ["release", "MOCK-9005"])


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
    item = _confirmed()
    out = tmp("tt-end-") / "x"
    _run(item, out, "--explore")
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
    # 발생 시각만이라 run이 이미 보류(실패 지점 없음) — 보류면 해결책 줄 자체가 없고, 없는 것은 못 고친 것이 아니다
    assert _report_line(out, "- 해결책") is None
    assert "fit_hold_unwritten" not in json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]
    assert json.loads((out / "check-output.json").read_text(encoding="utf-8"))["explore"]["fit_hold"] == "DATA-001-01"
    assert json.loads((out / "analysis.json").read_text(encoding="utf-8"))["candidates"][0]["C"] == 1

    again = _run(item, out, "--explore")                                  # 재실행(답글 턴): 이전 판단을 넘긴다
    assert again["prior"] == {"none": "1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다"}, again.get("prior")
    assert not (out / "explore-output.md").exists()                      # 추린 뒤에 지웠다(drop_stale_records)
    third = _run(item, out, "--explore")                                  # 검사 기록도 지워졌으니 다시 넘기지 않는다
    assert "prior" not in third


def test_fit_hold_is_recorded_even_when_lines_cannot_be_rewritten_and_survives_recheck():
    """리뷰 지적(P2 fail-open): ① 보류 기록(fit_hold)은 구조 감지만으로 남는다 — 결론 줄을 못 고쳐도(줄 없음) 기록·경고가 남고
    Jira 본문(계획 없음)은 보류다. ② 뒤 검사(형식 불일치 _fail)가 탐색 기록을 새로 써도 fit_hold는 이어받는다."""
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import issue_post
    item = _confirmed()
    out = tmp("tt-hold-") / "x"
    _run(item, out, "--explore")
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
    assert _report_line(out, "- 해결책") is None       # 판단이 이미 보류라 해결책 줄이 없다(못 쓴 줄은 결론 줄만)
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
    assert analysis["decision"]["state"] == "held"          # 단계 4: 기준 없이 돈 새 JOB은 이미 보류 — 해결책을 싣지 않는다
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
    assert first["status"] == "ok" and first["explore"]["reason"] == "fit_check", first
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
