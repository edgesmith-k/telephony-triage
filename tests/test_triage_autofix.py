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
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, plugin_root, run_json, tmp  # noqa: E402
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


def _parse_calls(job: Path) -> list[list]:
    rows = [json.loads(line) for line in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    return [r["args"] for r in rows if r.get("script") == "parse_logcat.py" and (r.get("args") or [None])[0] == "parse"]


def _report_line(out: Path, prefix: str) -> str:
    return next(line for line in (out / "report.md").read_text(encoding="utf-8").splitlines() if line.startswith(prefix))


# -- F-AUTO -------------------------------------------------------------------------------------------------


def test_no_time_no_look_no_jira_time_finishes_with_time_candidates_and_one_parse():
    out = tmp("tt-auto-") / "x"
    analysis = _run(_confirmed(), out, "--explore", occurred=False)
    assert analysis["status"] == "ok", analysis                     # NeedsInput("time") 없이 끝까지
    anchor = analysis["step_anchor"]
    assert anchor["source"] == "symptom_scan" and anchor["time_candidates"], anchor
    assert all(set(t) == {"ts", "type"} for t in anchor["time_candidates"])
    assert [t["ts"] for t in anchor["time_candidates"]] == sorted(t["ts"] for t in anchor["time_candidates"])
    calls = _parse_calls(out)
    assert len(calls) == 1 and "--full" in calls[0], calls          # occurred()의 전체 파싱을 본 분석이 다시 쓴다
    assert (out / "events.json").read_bytes() == (out / "events-full.json").read_bytes()
    assert analysis["candidates"][0]["cause"] == "DATA-001-01"
    spec = json.loads((out / "explore-input.json").read_text(encoding="utf-8"))   # 사건 후보가 탐색 입력에도 간다
    assert spec["time_candidates"] == anchor["time_candidates"] and spec["around"] is None
    assert _report_line(out, "- 기준 시각 없음").startswith(
        f"- 기준 시각 없음(시각·기준 줄 입력 없음) — 로그 전체를 봄. 증상 시각 후보 {len(anchor['time_candidates'])}개: ")


def test_given_time_still_wins_over_auto_scan():
    out = tmp("tt-auto-") / "x"
    item = _confirmed()
    analysis = _run(item, out, "--answer", f"time={item['occurred_at']}", occurred=False)
    assert analysis["status"] == "ok" and "time_candidates" not in (analysis.get("step_anchor") or {}), analysis
    assert all("--around" in c for c in _parse_calls(out))


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
    # 기존 두 사유는 플래그와 상관없이 그대로
    unresolved = _run(_unresolved(), tmp("tt-fit-") / "e", "--explore")
    assert unresolved["explore"] == {"reason": "no_candidate", "when": "ask", "note": ASK_NOTE}


def test_cause_unconfirmed_reason_unchanged(tmp_path):
    from types import SimpleNamespace
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import importlib
    triage = importlib.import_module("triage")
    drv = SimpleNamespace(cfg={}, warnings=[], args=SimpleNamespace(explore=True))
    assert triage.Driver.explore(drv, [{"C": 0}])["reason"] == "cause_unconfirmed"
    assert triage.Driver.explore(drv, [])["reason"] == "no_candidate"
    assert triage.Driver.explore(drv, [{"C": 1}])["reason"] == "fit_check"
    drv.args.explore = None
    assert triage.Driver.explore(drv, [{"C": 1}]) is None


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

    again = _run(item, out, "--explore")                                  # 재실행(답글 턴): 이전 판단을 넘긴다
    assert again["prior"] == {"none": "1위 DATA-001-01 부적합 — 증상 시각과 근거 시각이 다르다"}, again.get("prior")
    assert not (out / "explore-output.md").exists()                      # 추린 뒤에 지웠다(drop_stale_records)
    third = _run(item, out, "--explore")                                  # 검사 기록도 지워졌으니 다시 넘기지 않는다
    assert "prior" not in third


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
    again = _run(item, out)
    assert again["prior"] == {"hyps": ["캐리어 설정 뒤 데이터 평가 거부 — 반대: 거부 사유 줄 없음"]}, again.get("prior")
    # 검사에 실패한 출력(형식 불일치)은 넘기지 않는다
    run_json("triage.py", ["explore", item["key"], "--out", out])
    (out / "explore-output.md").write_text("가설 1: 칸이 모자란 가설\n", encoding="utf-8")
    run_json("triage.py", ["check-output", item["key"], "--for", "explore", "--out", out], expect=1)
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
