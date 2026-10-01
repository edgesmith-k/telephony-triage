#!/usr/bin/env python3
"""RF-1 `triage.py` 드라이버와 외부 리뷰 토큰 항목 (contracts.md §3.2 `triage.py`, 07-workflow.md §analyze).

- `--offline-db`: 라벨셋 항목마다 기존 경로(`parse_logcat parse --mask` → `match_signatures --top 3`)와 후보가 같다.
  `tools/offline_eval.py`는 이 드라이버를 쓴다(정확도 표 자체는 `test_commands.py`).
- `analysis.json` ≤ 4KB, 같은 입력이면 같은 결과(생성 시각 제외).
- 전체 경로(Workspace): needs_input(코드 경로·Jira·lock) → `--answer`로 재실행 → 후보, lock 보유, `release`로 해제.
  사용자 clone은 브랜치·워킹 트리가 그대로다.
- `jira_bridge.py`(PostToolUse): 원문은 `JOB/jira_raw.json`으로만, 모델에는 마스킹 요약만.
- `match_signatures --top`의 types·causes 절삭, `db_search`의 `code_refs`, `jira_fields --comments` 예산.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, plugin_root, run, run_json, tmp  # noqa: E402
from workspace import Workspace, git  # noqa: E402

LABELSET = REPO / "tests" / "fixtures" / "offline-eval-sample.yaml"
MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
DATA_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"


def _items() -> tuple[dict, list[dict]]:
    doc = yaml.safe_load(LABELSET.read_text(encoding="utf-8"))
    return doc, doc["items"]


def _offline(item: dict, doc: dict, out: Path) -> dict:
    meta = out.parent / f"{out.name}.meta.json"
    meta.write_text(json.dumps({"key": item["key"], "occurred_at": item["occurred_at"],
                                "summary": item.get("summary", "")}, ensure_ascii=False), encoding="utf-8")
    logs = [str((LABELSET.parent / p).resolve()) for p in item["logs"]]
    return run_json("triage.py", ["run", item["key"], "--offline-db", SAMPLE, "--out", out, "--logs", *logs,
                                  "--jira-meta", meta, "--tz", doc["tz"], "--year", doc["year"]])


def _legacy(item: dict, doc: dict, work: Path) -> list[dict]:
    """RF-1 이전 offline_eval 경로: 파서 → 매처를 따로 부른다."""
    logs = [str((LABELSET.parent / p).resolve()) for p in item["logs"]]
    events = run("parse_logcat.py", ["parse", *logs, "--around", item["occurred_at"], "--rules",
                                     SAMPLE / "parser-rules", "--mask", "--tz", doc["tz"], "--year", doc["year"]])
    assert events.returncode == 0, events.stderr
    path = work / f"{item['key']}.events.json"
    path.write_text(events.stdout, encoding="utf-8")
    meta = work / f"{item['key']}.jira.json"
    meta.write_text(json.dumps({"key": item["key"], "occurred_at": item["occurred_at"],
                                "summary": item.get("summary", "")}, ensure_ascii=False), encoding="utf-8")
    return run_json("match_signatures.py", ["--db", SAMPLE, "--events", path, "--jira-meta", meta,
                                            "--top", "3"])["candidates"]


# -- 오프라인: 기존 결과와 같음 ---------------------------------------------------------------------------


def test_offline_driver_matches_legacy_parse_and_match_for_every_labelset_item():
    doc, items = _items()
    work = tmp("tt-triage-")
    for item in items:
        analysis = _offline(item, doc, work / item["key"])
        legacy = _legacy(item, doc, work)
        assert analysis["status"] == "ok"
        got = [(c["type"], c["cause"], c["score"], c["confidence"], c["S"], c["C"])
               for c in analysis.get("candidates") or []]
        want = [(c["type"], c["cause"], c["score"], c["confidence"], c["S"], c["C"]) for c in legacy]
        assert got == want, item["key"]
        top = (analysis.get("candidates") or [None])[0]
        if top:
            assert [e["ts"] for e in top["evidence"]] == [e["ts"] for e in legacy[0]["evidence"]][:len(top["evidence"])]


def test_offline_eval_uses_triage_driver():
    text = (REPO / "tools" / "offline_eval.py").read_text(encoding="utf-8")
    assert '"triage.py"' in text and "match_signatures.py" not in text.split("def evaluate_item")[1]


def test_analysis_is_small_deterministic_and_writes_report_and_trace():
    doc, items = _items()
    work = tmp("tt-triage-")
    first = _offline(items[0], doc, work / "a")
    second = _offline(items[0], doc, work / "b")
    strip = lambda r: {k: v for k, v in r.items() if k not in ("generated_at", "files")}  # noqa: E731
    assert strip(first) == strip(second)
    raw = (work / "a" / "analysis.json").read_bytes()
    assert len(raw) <= 4096 and json.loads(raw)["candidates"][0]["cause"] == "DATA-001-01"
    report = (work / "a" / "report.md").read_text(encoding="utf-8")
    assert report.startswith(f"## {items[0]['key']} 분석") and "TODO(LLM)" in report and "DATA-001-01" in report
    trace = [json.loads(line) for line in (work / "a" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    scripts = [row.get("script") for row in trace if row.get("script")]
    assert "parse_logcat.py" in scripts and "match_signatures.py" in scripts
    assert all("exit" in row and "ms" in row for row in trace if row.get("script"))


def test_analysis_is_trimmed_to_4kb_when_evidence_is_large(tmp_path):
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import importlib
    triage = importlib.import_module("triage")
    big = {"ts": "2026-09-20T05:30:00.000Z", "tag": "DNC-0", "msg": "x" * 140, "event": "e"}
    result = {"warnings": ["w" * 120] * 10, "files": {"report": "r", "events": "e"},
              "candidates": [{"cause": f"C-{i}", "evidence": [dict(big) for _ in range(10)]} for i in range(3)]}
    out = triage.fit(result)
    assert len(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8")) <= 4096
    assert out["candidates"][0]["evidence"] and out["truncated"] is False


def test_offline_requires_out_and_meta():
    proc = run("triage.py", ["run", "EVAL-1", "--offline-db", SAMPLE, "--logs", DATA_LOG])
    assert proc.returncode == 2 and "--out" in proc.stderr


# -- 전체 경로 -------------------------------------------------------------------------------------------


def _bridge(ws: Workspace, text: str):
    return run("jira_bridge.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=text)


def _clone_state(ws: Workspace) -> tuple[str, str, str]:
    return (git(ws.clone, "rev-parse", "--abbrev-ref", "HEAD"), git(ws.clone, "status", "--porcelain"),
            git(ws.clone, "branch", "--list"))


def test_full_run_stops_for_code_choice_then_finishes_and_keeps_lock_until_release():
    ws = Workspace()
    before = _clone_state(ws)
    args = ["run", "MOCK-1001", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml", "--logs", DATA_LOG]
    first = ws.json("triage.py", args)
    assert first["status"] == "needs_input" and first["needs_input"]["kind"] == "code"
    assert any(o["value"] == "skip" for o in first["needs_input"]["options"])

    done = ws.json("triage.py", [*args, "--answer", "code=skip"])
    assert done["status"] == "ok" and done["mode"] == "write"
    assert done["candidates"][0]["cause"] == "DATA-001-01"
    assert done["candidates"][0]["resolution"] and done["code"] == {"skipped": True}
    assert done["jira"]["origin"] == "file" and done["snapshot"]["sha"]
    job = ws.job_dir("MOCK-1001")
    assert len((job / "analysis.json").read_bytes()) <= 4096 and (job / "report.md").is_file()
    status = ws.db_pr("lock", "status")
    assert status["lock"]["job"] == "MOCK-1001" and status["lock"]["owner"] == done["lock_owner"]
    assert _clone_state(ws) == before, "사용자 clone은 그대로"

    # 같은 세션 재실행은 lock을 다시 묻지 않고 같은 결과를 낸다(멱등)
    again = ws.json("triage.py", [*args, "--answer", "code=skip"])
    assert again["request_hash"] == done["request_hash"] and again["lock_owner"] == done["lock_owner"]

    released = ws.json("triage.py", ["release", "MOCK-1001"])
    assert released["released"] is True
    assert ws.db_pr("lock", "status")["held"] is False


def test_full_run_resolves_code_refs_against_the_chosen_tree():
    ws = Workspace()
    src = REPO / "tests" / "mocks" / "src" / "android16"
    done = ws.json("triage.py", ["run", "MOCK-1001", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml",
                                 "--logs", DATA_LOG, "--code", src])
    assert done["status"] == "ok", done
    code = done["code"]
    assert code["skipped"] is False and code["tree_version"] == "16"
    resolved = {Path(r["path"]).name for r in code["resolved"]}
    assert "DataSettingsManager.java" in resolved
    assert all(r["ref"].startswith("aosp:") for r in code["resolved"] + code.get("moved", []))
    report = (ws.job_dir("MOCK-1001") / "report.md").read_text(encoding="utf-8")
    assert "DataSettingsManager.java" in report and "Android 16" in report
    ws.json("triage.py", ["release", "MOCK-1001"])


def test_full_run_asks_for_jira_and_reads_what_the_bridge_saved():
    ws = Workspace()
    args = ["run", "MOCK-1001", "--logs", DATA_LOG, "--code", "skip"]
    ask = ws.json("triage.py", args)
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "jira"
    assert ask["needs_input"]["tool"] == "mcp__mock-jira__jira_fetch_ticket"

    issue = yaml.safe_load((MOCK_JIRA / "MOCK-1001.yaml").read_text(encoding="utf-8"))
    event = {"hook_event_name": "PostToolUse", "tool_name": "mcp__mock-jira__jira_fetch_ticket",
             "tool_input": {"ticket": "MOCK-1001"},
             "tool_response": {"content": [{"type": "text", "text": json.dumps(issue, ensure_ascii=False)}]}}
    proc = _bridge(ws, json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    shown = json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"]
    raw = ws.job_dir("MOCK-1001") / "jira_raw.json"
    assert raw.is_file() and "mock.reporter" not in shown and "customfield_10002" not in shown
    assert "데이터가 연결되지 않음" in shown

    done = ws.json("triage.py", args)
    assert done["status"] == "ok" and done["jira"]["origin"] == "mcp"
    assert done["candidates"][0]["cause"] == "DATA-001-01"
    assert not raw.exists(), "추출 뒤 원문은 지운다(--consume)"
    ws.json("triage.py", ["release", "MOCK-1001"])


def test_hooks_json_wires_bridge_as_post_tool_use():
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (entry,) = hooks["PostToolUse"]
    assert entry["matcher"] == "mcp__.*" and "scripts/jira_bridge.py" in entry["hooks"][0]["command"]


def test_bridge_ignores_other_tools():
    ws = Workspace(build=False)
    event = {"tool_name": "mcp__other__get_issue", "tool_input": {}, "tool_response": "secret"}
    proc = _bridge(ws, json.dumps(event))
    assert proc.returncode == 0 and proc.stdout.strip() == ""


def test_lock_held_by_other_job_is_a_question_and_release_other_continues():
    ws = Workspace()
    ws.acquire("MOCK-9999")
    args = ["run", "MOCK-1001", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml", "--logs", DATA_LOG,
            "--code", "skip"]
    ask = ws.json("triage.py", args)
    assert ask["needs_input"]["kind"] == "lock" and "MOCK-9999" in ask["needs_input"]["question"]
    done = ws.json("triage.py", [*args, "--answer", "lock=release-other"])
    assert done["status"] == "ok" and ws.db_pr("lock", "status")["lock"]["job"] == "MOCK-1001"


def test_invalid_key_is_exit_1_and_errors_after_lock_release_it():
    ws = Workspace(build=False)
    bad = ws.run("triage.py", ["run", "bad-key", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml",
                               "--logs", DATA_LOG])
    assert bad.returncode == 1 and "형식" in bad.stderr
    missing = ws.run("triage.py", ["run", "MOCK-1001", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml",
                                   "--logs", ws.base / "no-such.log", "--code", "skip"])
    assert missing.returncode == 2 and "로그 파일이 없습니다" in missing.stderr
    assert ws.db_pr("lock", "status")["held"] is False, "오류로 끝나면 lock을 푼다"


def test_jira_file_requires_dry_run():
    ws = Workspace(build=False)
    proc = ws.run("triage.py", ["run", "MOCK-1001", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml"])
    assert proc.returncode == 2 and "--dry-run" in proc.stderr


def test_skill_md_is_within_8kb_and_drives_triage():
    skill = REPO / "plugin" / "skills" / "telephony-triage" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) <= 8192
    for needle in ("triage.py run", "needs_input", "--answer", "S-3", "write-flow.md", "commit -F"):
        assert needle in text, needle
    for name in ("analyze", "record", "verify-fix", "fix-submitted"):   # 보일러플레이트 없이 한 줄로 가리킨다
        assert len((REPO / "plugin" / "commands" / f"{name}.md").read_bytes()) < 1024, name


# -- 외부 리뷰 토큰 항목 ----------------------------------------------------------------------------------


def test_match_top_trims_types_and_causes_but_top_0_keeps_everything():
    doc, items = _items()
    work = tmp("tt-triage-")
    _offline(items[0], doc, work / "a")
    events = work / "a" / "events.json"
    trimmed = run_json("match_signatures.py", ["--db", SAMPLE, "--events", events, "--top", "3"])
    full = run_json("match_signatures.py", ["--db", SAMPLE, "--events", events, "--top", "0"])
    assert all(t["S"] for t in trimmed["types"]) and all(c["C"] for c in trimmed["causes"])
    assert len(full["types"]) == len(trimmed["types"]) + trimmed["omitted"]["types"]
    assert len(full["causes"]) == len(trimmed["causes"]) + trimmed["omitted"]["causes"]
    assert "omitted" not in full and trimmed["candidates"] == full["candidates"][:3]


def test_db_search_cause_has_code_refs_projection():
    out = run_json("db_search.py", ["DATA-001-01", "--db", SAMPLE, "--limit", "3"])
    cause = next(r for r in out["results"] if r.get("id") == "DATA-001-01")
    assert cause["code_refs"] and set().union(*map(set, cause["code_refs"])) <= {"ref", "symbol", "android_versions"}
    assert cause["code_refs"][0]["ref"].startswith("aosp:")


def test_jira_fields_comment_budget():
    home = {"TELEPHONY_TRIAGE_HOME": str(tmp("tt-home-"))}
    path = MOCK_JIRA / "MOCK-1001.yaml"
    full = run_json("jira_fields.py", ["extract", path, "--origin", "file", "--db", SAMPLE], env=home)
    last = run_json("jira_fields.py", ["extract", path, "--origin", "file", "--db", SAMPLE, "--comments", "last:1",
                                       "--comment-chars", "5"], env=home)
    assert full["text"]["comments_total"] == last["text"]["comments_total"] == len(full["text"]["comments"]) == 2
    assert len(last["text"]["comments"]) == 1 and len(last["text"]["comments"][0]) <= 5
    assert last["text"]["comments"][0][:4] == full["text"]["comments"][-1][:4]
    bad = run("jira_fields.py", ["extract", path, "--origin", "file", "--db", SAMPLE, "--comments", "3"], env=home)
    assert bad.returncode == 2


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
