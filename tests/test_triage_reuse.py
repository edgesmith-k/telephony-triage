#!/usr/bin/env python3
"""RF-7 입력 해시와 분석 재사용 (contracts.md §3.2 `triage.py`, 07-workflow.md §입력 재사용).

같은 입력이면 파싱·매칭을 다시 하지 않고 `JOB/analysis-cache.json`의 core를 다시 보여 준다. 입력 부분(logs·jira·db·config·
plugin·args) 중 바뀐 것만 알려 주고, 오프라인·`--refresh`·needs_input에서는 재사용하지 않는다. 캐시·state에는 마스킹된 값만 둔다.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import make_plugin_root  # noqa: E402
from runner import SAMPLE, run_json, tmp  # noqa: E402
from workspace import Workspace  # noqa: E402

MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
SRC = REPO / "tests" / "mocks" / "src" / "android16"
KEY = "MOCK-1001"
SKIPPED_STEPS = {"3-markers", "3-parse", "4-match", "4-db", "4-hints", "5-resolve"}


def _run(ws: Workspace, *extra, logs=LOG, code="skip") -> dict:
    args = ["run", KEY, "--dry-run", "--jira-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", logs]
    args += ["--answer", "code=skip"] if code == "skip" else ["--code", code]
    done = ws.json("triage.py", [*args, *extra])
    assert done["status"] == "ok", done
    return done


def _trace(ws: Workspace) -> list[dict]:
    path = ws.job_dir(KEY) / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _since(ws: Workspace, before: int) -> list[dict]:
    return _trace(ws)[before:]


def _strip(a: dict) -> dict:
    return {k: v for k, v in a.items() if k not in ("generated_at", "reuse", "run")}


def _state(ws: Workspace) -> dict:
    return json.loads((ws.job_dir(KEY) / "triage-state.json").read_text(encoding="utf-8"))


def _reuse_note(rows: list[dict]) -> dict:
    return next(r for r in rows if r.get("step") == "reuse")


def test_same_inputs_reuse_core_without_parse_or_match():
    ws = Workspace()
    first = _run(ws)
    assert "reuse" not in first and first["run"] == 1
    job = ws.job_dir(KEY)
    report1 = (job / "report.md").read_text(encoding="utf-8")
    n = len(_trace(ws))
    second = _run(ws)
    assert second["reuse"] == {"hit": True, "run": 1} and second["run"] == 1
    assert _strip(second) == _strip(first) and second["request_hash"] == first["request_hash"]
    rows = _since(ws, n)
    assert not SKIPPED_STEPS & {r.get("step") for r in rows}
    assert _reuse_note(rows)["hit"] is True and _reuse_note(rows)["run"] == 1
    report2 = (job / "report.md").read_text(encoding="utf-8").splitlines()
    assert "- 재사용: 입력(로그·Jira·이슈 DB·설정·플러그인)이 실행 1과 같아 파싱·매칭을 다시 하지 않았다" in report2
    assert [x for x in report2 if not x.startswith("- 재사용:")] == report1.splitlines()
    assert [r["reused"] for r in _state(ws)["job"]["runs"]] == [False, True]


def test_reuse_survives_release_and_new_session():
    ws = Workspace()
    first = _run(ws)
    ws.json("triage.py", ["release", KEY])
    again = _run(ws)
    assert again["lock_owner"] != first["lock_owner"]
    assert again["reuse"] == {"hit": True, "run": 1} and _strip(again)["candidates"] == _strip(first)["candidates"]
    assert len(_state(ws)["job"]["runs"]) == 2


def test_log_content_change_invalidates_only_logs_part():
    ws = Workspace()
    log = tmp("tt-log-") / "radio.log"
    shutil.copyfile(LOG, log)
    _run(ws, logs=log)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("09-20 05:40:00.000  1000  1000 I RILJ    : 추가된 줄\n")
    n = len(_trace(ws))
    again = _run(ws, logs=log)
    assert again["reuse"]["hit"] is False and again["reuse"]["changed"] == ["logs"] and again["reuse"]["prev_run"] == 1
    assert again["run"] == 2 and "added_logs" not in again["reuse"]
    assert _reuse_note(_since(ws, n)) | {"ts": 0} == {"ts": 0, "step": "reuse", "hit": False, "changed": ["logs"]}
    assert "3-parse" in {r.get("step") for r in _since(ws, n)}
    report = (ws.job_dir(KEY) / "report.md").read_text(encoding="utf-8")
    assert "- 재분석: 실행 1 대비 바뀐 입력 [logs] — 1위 변화 없음" in report
    # 새 로그를 더하면 추가된 이름이 나온다
    other = log.with_name("extra.log")
    other.write_text(log.read_text(encoding="utf-8"), encoding="utf-8")
    more = ws.json("triage.py", ["run", KEY, "--dry-run", "--jira-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", log, other,
                                 "--answer", "code=skip"])
    assert more["reuse"]["changed"] == ["logs"] and more["reuse"]["added_logs"] == ["extra.log"]


def test_issue_db_change_invalidates_db_part():
    ws = Workspace()
    first = _run(ws)
    old = first["candidates"][0]["resolution"]
    assert "모바일 데이터 설정을 켠다" in old
    ws.json("triage.py", ["release", KEY])
    path = "data/DATA-001-no-setup-data-call/type.md"
    ws.push_main(lambda c: (c / path).write_text(
        (c / path).read_text(encoding="utf-8").replace("resolution: 모바일 데이터 설정을 켠다",
                                                       "resolution: 모바일 데이터 설정을 켜고 재부팅한다", 1), encoding="utf-8"))
    again = _run(ws)       # 새 세션: 스냅샷을 새로 만든다
    assert again["reuse"]["hit"] is False and again["reuse"]["changed"] == ["db"], again["reuse"]
    assert "재부팅한다" in again["candidates"][0]["resolution"]
    assert again["snapshot"]["sha"] != first["snapshot"]["sha"]


def test_config_change_invalidates_but_recent_code_roots_does_not():
    ws = Workspace()
    _run(ws)
    cfg = ws.home / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["recent_code_roots"] = [{"roots": {"aosp": "/tmp/somewhere"}, "used_on": "2026-10-01"}]
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert _run(ws)["reuse"] == {"hit": True, "run": 1}
    ws.json("config.py", ["set", "explore.timeline_max_lines", "100"])
    changed = _run(ws)
    assert changed["reuse"]["hit"] is False and changed["reuse"]["changed"] == ["config"]


def test_plugin_code_change_invalidates():
    root = make_plugin_root.make(with_site_backend=True)
    ws = Workspace(root=root)
    _run(ws)
    assert _run(ws)["reuse"]["hit"] is True
    with (root / "scripts" / "db_summary.py").open("a", encoding="utf-8") as fh:
        fh.write("\n# 재사용 무효화 시험\n")
    changed = _run(ws)
    assert changed["reuse"]["hit"] is False and changed["reuse"]["changed"] == ["plugin"]


def test_args_and_answers_invalidate():
    ws = Workspace()
    _run(ws)
    minutes = _run(ws, "--minutes", "10")
    assert minutes["reuse"]["hit"] is False and minutes["reuse"]["changed"] == ["args"]
    assert _run(ws, "--minutes", "10")["reuse"]["hit"] is True
    off = _run(ws, "--minutes", "10", "--answer", "anchor=off")
    assert off["reuse"]["changed"] == ["args"] and off["request_hash"] != minutes["request_hash"]
    # lock·reanalyze 같은 흐름 답은 결과와 무관하다
    assert _run(ws, "--minutes", "10", "--answer", "reanalyze=yes")["reuse"]["hit"] is True


def test_missing_events_or_match_forces_recompute():
    ws = Workspace()
    _run(ws)
    job = ws.job_dir(KEY)
    (job / "events.json").unlink()
    gone = _run(ws)
    assert gone["reuse"] == {"hit": False, "prev_run": 1, "reason": "cache-missing", "top_changed": False, "prev_top": "DATA-001-01"}
    assert (job / "events.json").is_file()
    assert "- 재분석: 실행 1 대비 저장된 분석 결과를 쓸 수 없다 — 1위 변화 없음" in (job / "report.md").read_text(encoding="utf-8")
    assert _run(ws)["reuse"]["hit"] is True
    with (job / "match.json").open("a", encoding="utf-8") as fh:      # 크기가 달라지면(손으로 고친 것) 쓰지 않는다
        fh.write(" ")
    assert _run(ws)["reuse"]["reason"] == "cache-missing"
    (job / "analysis-cache.json").unlink()
    assert _run(ws)["reuse"]["reason"] == "cache-missing"


def test_refresh_disables_reuse():
    ws = Workspace()
    _run(ws)
    again = _run(ws, "--refresh")
    assert again["reuse"]["hit"] is False and again["reuse"]["reason"] == "refresh" and "changed" not in again["reuse"]
    assert "3-parse" in {r.get("step") for r in _trace(ws)[-40:]}
    assert "--refresh로 재사용을 껐다" in (ws.job_dir(KEY) / "report.md").read_text(encoding="utf-8")


def test_moved_code_path_forces_recompute():
    ws = Workspace()
    tree = tmp("tt-src-") / "android16"
    shutil.copytree(SRC, tree)
    first = _run(ws, code=str(tree))
    assert first["code"]["resolved"], first["code"]
    assert _run(ws, code=str(tree))["reuse"]["hit"] is True
    Path(first["code"]["resolved"][0]["path"]).unlink()
    moved = _run(ws, code=str(tree))
    assert moved["reuse"]["hit"] is False and moved["reuse"]["changed"] == ["code"]
    assert all(Path(r["path"]).exists() for r in moved["code"]["resolved"])


def test_needs_input_does_not_write_cache():
    ws = Workspace()
    args = ["run", KEY, "--dry-run", "--jira-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", LOG]
    asked = ws.json("triage.py", args)
    assert asked["status"] == "needs_input"
    job = ws.job_dir(KEY)
    assert not (job / "analysis-cache.json").exists() and "cache" not in _state(ws).get("job", {})
    done = ws.json("triage.py", [*args, "--answer", "code=skip"])
    assert "reuse" not in done and (job / "analysis-cache.json").is_file()      # 첫 완료 실행: 이력이 없다
    assert _state(ws)["schema"] == 2 and [r["n"] for r in _state(ws)["job"]["runs"]] == [1]


def test_offline_has_no_reuse_key_and_output_unchanged():
    doc = yaml.safe_load((REPO / "tests" / "fixtures" / "offline-eval-sample.yaml").read_text(encoding="utf-8"))
    item = doc["items"][0]
    work = tmp("tt-off-")
    results = []
    for name in ("a", "b"):
        meta = work / f"{name}.meta.json"
        meta.write_text(json.dumps({"key": item["key"], "occurred_at": item["occurred_at"], "summary": item.get("summary", "")}),
                        encoding="utf-8")
        logs = [str((REPO / "tests" / "fixtures" / p).resolve()) for p in item["logs"]]
        results.append(run_json("triage.py", ["run", item["key"], "--offline-db", SAMPLE, "--out", work / name, "--logs", *logs,
                                              "--jira-meta", meta, "--tz", doc["tz"], "--year", doc["year"]]))
    for name, result in zip(("a", "b"), results):
        assert "reuse" not in result and "run" not in result and not (work / name / "analysis-cache.json").exists()
        text = (work / name / "report.md").read_text(encoding="utf-8")
        assert "재사용" not in text and "재분석" not in text and not (work / name / "triage-state.json").exists()
    assert {k: v for k, v in results[0].items() if k not in ("generated_at", "files")} == \
           {k: v for k, v in results[1].items() if k not in ("generated_at", "files")}


def test_state_schema_v1_file_is_treated_as_first_run():
    ws = Workspace()
    _run(ws)
    path = ws.job_dir(KEY) / "triage-state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state.pop("schema")
    state.pop("job")
    path.write_text(json.dumps(state), encoding="utf-8")     # 스키마 1 파일
    again = _run(ws)
    assert "reuse" not in again and again["run"] == 1
    assert _state(ws)["schema"] == 2 and len(_state(ws)["job"]["runs"]) == 1
    assert _run(ws)["reuse"] == {"hit": True, "run": 1}


def test_cache_and_state_hold_masked_text_only():
    ws = Workspace()
    raw = "010-1234-5678"
    done = _run(ws, "--failed-step", f"4 | 번호 {raw} 로 전화 걸기 | FAIL")
    assert "<MSISDN#" in done["jira"]["failed_step"]["text"]
    again = _run(ws, "--failed-step", f"4 | 번호 {raw} 로 전화 걸기 | FAIL")
    assert again["reuse"]["hit"] is True
    job = ws.job_dir(KEY)
    files = [p for p in job.rglob("*") if p.is_file()]
    assert {"analysis-cache.json", "triage-state.json"} <= {p.name for p in files}
    for path in files:
        assert raw not in path.read_text(encoding="utf-8", errors="replace"), path.name
        assert "1234-5678" not in path.read_text(encoding="utf-8", errors="replace"), path.name
    state = _state(ws)
    assert set(state["job"]) == {"logs", "runs", "cache"} and set(state["job"]["logs"][0]) == {"path", "name", "sha", "size"}
    assert len(state["job"]["cache"]["request_hash"]) == 16 and set(state["job"]["cache"]["parts"]) == {
        "logs", "jira", "db", "config", "plugin", "args"}


def test_runs_are_capped_and_top_change_is_reported():
    ws = Workspace()
    _run(ws)
    for _ in range(11):
        _run(ws)
    runs = _state(ws)["job"]["runs"]
    assert len(runs) == 10 and runs[-1]["n"] == 12 and runs[-1]["top"]["cause"] == "DATA-001-01"
    # 1위가 달라지면(여기서는 앵커를 꺼서 후보가 바뀌는 입력 대신 직접 이전 기록을 고쳐) 이전 1위와 함께 나온다
    state = _state(ws)
    state["job"]["runs"][-1]["top"]["cause"] = "IMS-001-01"
    (ws.job_dir(KEY) / "triage-state.json").write_text(json.dumps(state), encoding="utf-8")
    changed = _run(ws, "--minutes", "7")
    assert changed["reuse"]["top_changed"] is True and changed["reuse"]["prev_top"] == "IMS-001-01"
    assert "1위 IMS-001-01 → DATA-001-01" in (ws.job_dir(KEY) / "report.md").read_text(encoding="utf-8")


def _no_candidate_log() -> Path:
    import subprocess
    gen = tmp("tt-e004-")
    done = subprocess.run([sys.executable, str(REPO / "tests" / "mocks" / "logcat_gen.py"),
                           str(REPO / "tests" / "skill_evals" / "scenarios" / "e004-cs-call-drop.yaml"), "--out", str(gen)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return next(gen.glob("*.log"))


def test_explore_timeline_is_not_a_cache_file_and_is_reproduced_on_a_hit():
    ws = Workspace()
    log = _no_candidate_log()
    first = _run(ws, "--answer", "time=2026-09-27T18:02:03+09:00", logs=log)
    job = ws.job_dir(KEY)
    assert not first.get("candidates") and not (job / "timeline.md").exists() and (job / "explore-input.json").is_file()
    done = ws.json("triage.py", ["explore", KEY])                    # work_dir/<KEY>에서 찾는다
    assert done["timeline"] == "timeline.md" and done["lines"] == done["total"] > 0
    made = (job / "timeline.md").read_bytes()
    cache = json.loads((job / "analysis-cache.json").read_text(encoding="utf-8"))
    assert "timeline" not in cache["files"] and cache["format"] == 2 and cache["core"]["explore_input"]["limit"] == 200
    second = _run(ws, "--answer", "time=2026-09-27T18:02:03+09:00", logs=log)                                      # 타임라인을 만든 뒤에도 적중
    assert second["reuse"] == {"hit": True, "run": 1}
    assert not (job / "timeline.md").exists() and (job / "explore-input.json").is_file()   # run은 이전 타임라인을 지운다
    again = ws.json("triage.py", ["explore", KEY])
    assert again == done and (job / "timeline.md").read_bytes() == made
    assert "- 탐색 분석 (추정, timeline.md" in (job / "report.md").read_text(encoding="utf-8")
