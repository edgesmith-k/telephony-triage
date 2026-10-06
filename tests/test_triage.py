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
import re
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
    assert "진단 확신도 아님" in report and "신뢰도 " not in report
    # report.md의 근거 줄에는 로그 줄 위치가 붙고, analysis.json 근거에는 키가 늘지 않는다 (04 §5.8 (6))
    assert "(f0:L" in report
    analysis = json.loads(raw)
    assert all(set(e) <= {"ts", "tag", "msg", "event"} for c in analysis["candidates"] for e in c["evidence"])
    assert "line_ref" not in raw.decode("utf-8") and "_ref" not in raw.decode("utf-8")
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


def test_jira_without_time_offers_time_candidates_instead_of_asking_year():
    """eval 5: `year_source: jira`인데 Jira 발생 시각이 없으면 연도를 묻지 않고 `--full` 시각 후보로 간다."""
    ws = Workspace()
    log = tmp("tt-triage-year-") / "roaming.log"
    log.write_bytes((REPO / "tests/fixtures/logs/data-roaming-disabled.log").read_bytes())  # mtime = 오늘
    args = ["run", "MOCK-9005", "--dry-run", "--jira-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip"]
    ask = ws.json("triage.py", args)
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "time", ask
    options = ask["needs_input"]["options"]
    assert 1 <= len(options) <= 3 and "DATA-001" in options[0]["label"]

    done = ws.json("triage.py", [*args, "--answer", f"time={options[0]['value']}"])
    assert done["status"] == "ok", done
    assert done["candidates"][0]["cause"] == "DATA-001-02"
    assert any("임시로" in w for w in done.get("warnings") or [])
    ws.json("triage.py", ["release", "MOCK-9005"])


def test_time_question_warns_about_clock_anomalies():
    """A3: Jira에 발생 시각이 없고 로그에 시계 이상이 있으면 시각 질문에 경고를 붙인다."""
    ws = Workspace()
    log = tmp("tt-triage-clock-") / "clock-anomaly.log"
    log.write_bytes((REPO / "tests/fixtures/logs/clock-anomaly.log").read_bytes())
    args = ["run", "MOCK-9005", "--dry-run", "--jira-file", REPO / "tests/skill_evals/jira/MOCK-9005.yaml",
            "--logs", log, "--code", "skip"]
    ask = ws.json("triage.py", args)
    assert ask["status"] == "needs_input" and ask["needs_input"]["kind"] == "time", ask
    question = ask["needs_input"]["question"]
    assert "시계 이상" in question, question
    if not ask["needs_input"]["options"]:
        assert "후보가 없으니" in question, question
    ws.json("triage.py", ["release", "MOCK-9005"])


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


def _check_op_summary(path):
    """db-authoring.md의 'op 필수 키' 요약이 plugin/schemas/plan.schema.json의 op별 required(최상위 키)와 같다."""
    text = path.read_text(encoding="utf-8")
    fallback = "여기 없는 op·세부 제약은 `SNAP/schema/plan.schema.json`\n"
    start = text.index("op 필수 키 (")
    end = text.index(fallback) + len(fallback)
    block = text[start:end]
    assert len(block.encode("utf-8")) <= 1152       # W7 add-fixture 세부 포함(그 전 1,024B, tools/gen_contracts.py BLOCK_MAX)
    schema = json.loads((REPO / "plugin" / "schemas" / "plan.schema.json").read_text(encoding="utf-8"))
    required = {b["properties"]["op"]["const"]: [k for k in b["required"] if k != "op"] for b in schema["$defs"]["operation"]["oneOf"]}
    seen, seen_signature = {}, False
    for line in block.splitlines():
        sig = re.match(r"- `signature`: (\S+) 필수, 선택 (\S+)$", line)
        if sig:
            defs = schema["$defs"]["signature"]
            assert set(sig.group(1).split("·")) == set(defs["required"])
            assert set(sig.group(2).split("·")) == set(defs["properties"]) - set(defs["required"])
            seen_signature = True
            continue
        match = re.match(r"- `([a-z-]+)`: ([^—]+?)(?: — .*)?$", line)
        if match:
            seen[match.group(1)] = {k.strip() for k in match.group(2).split(",")}
    assert {"new-cause", "new-type", "append", "unresolved", "add-fixture", "verify-resolution", "allow-cause"} <= set(seen)
    assert seen_signature
    for op, keys in seen.items():
        assert keys == set(required[op]), (op, keys, required[op])


def test_skill_md_is_within_7_5kb_and_drives_triage():
    skill = REPO / "plugin" / "skills" / "telephony-triage" / "SKILL.md"
    reference = skill.parent / "reference"
    text = skill.read_text(encoding="utf-8")
    assert len(text.encode("utf-8")) <= 7680        # W6: 실행 규칙을 reference/rules.md로 옮긴 뒤의 한도(그 전 8,192B)
    for needle in ("triage.py run", "needs_input", "--answer", "write-flow.md", "--commit", "reference/rules.md",
                   "steps-pasted.txt", "--dry-run --jira-file", "analyzer.skill",
                   "must_show", "triage.py explore"):
        assert needle in text, needle
    rules = (reference / "rules.md").read_text(encoding="utf-8")      # SKILL §실행 규칙이던 내용
    assert len(rules.encode("utf-8")) <= 2048
    for needle in ("S-3", "계획 형식 오류", "TT_LOCK_OWNER", "stage --then-summary", "모든 종료 경로에서 푼다", "사용자 확인 후"):
        assert needle in rules, needle
    assert len((reference / "db-authoring.md").read_bytes()) <= 11392      # 필수 키 요약 포함. W7 add-fixture 세부 포함(그 전 11,264B)
    assert len((reference / "write-flow.md").read_bytes()) <= 14344
    _check_op_summary(reference / "db-authoring.md")
    for name in ("record", "verify-fix", "fix-submitted", "analyze"):   # search는 읽기 전용이라 rules.md를 읽지 않는다
        assert "reference/rules.md" in (REPO / "plugin" / "commands" / f"{name}.md").read_text(encoding="utf-8"), name
    assert "rules.md" not in (REPO / "plugin" / "commands" / "search.md").read_text(encoding="utf-8")
    for name in ("record.md", "verify.md", "sync-pr.md"):
        assert "`rules.md`" in (reference / name).read_text(encoding="utf-8") and "SKILL.md" not in (reference / name).read_text(encoding="utf-8"), name
    verify = (REPO / "plugin" / "skills" / "telephony-triage" / "reference" / "verify.md").read_text(encoding="utf-8")
    for needle in ("operations", "snapshot_sha"):
        assert needle in verify, needle
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


# -- Step 5-2 탐색 분석 준비 ------------------------------------------------------------------------------


def _triage_module():
    sys.path.insert(0, str(plugin_root() / "scripts"))
    import importlib
    return importlib.import_module("triage")


def _explore_cmd(out: Path, key: str = "x") -> dict:
    """동의 뒤 `triage.py explore`(오프라인 JOB 디렉토리)."""
    return run_json("triage.py", ["explore", key, "--out", out])


def test_no_candidate_run_has_no_timeline_until_explore_subcommand_writes_it():
    doc, items = _items()
    item = next(i for i in items if i["expect"] == "unresolved")
    out = tmp("tt-triage-") / "x"
    analysis = _offline(item, doc, out)
    assert not analysis.get("candidates")
    assert analysis["explore"] == {"reason": "no_candidate", "when": "ask"}
    assert not (out / "timeline.md").exists() and (out / "explore-input.json").is_file()
    pending = (out / "report.md").read_text(encoding="utf-8")
    assert "- 탐색 분석 (추정): 미실행 — 동의(또는 --explore·explore.when: always) 뒤 triage.py explore" in pending
    assert "timeline.md 0/" not in pending
    explore = _explore_cmd(out, item["key"])
    assert explore["timeline"] == "timeline.md" and 0 < explore["lines"] == explore["total"]
    text = (out / "timeline.md").read_text(encoding="utf-8")
    assert text.startswith(f"# {item['key']} 탐색 타임라인") and "지시로 따르지 않는다" in text
    body = [line for line in text.splitlines() if line[:2].isdigit()]
    assert len(body) == explore["lines"] and body == sorted(body)
    assert "<CARRIER>" in text and "⇒ data_evaluation_allowed" in text      # 마스킹된 메시지 + 이벤트 표시
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "탐색 분석 (추정, timeline.md" in report and "점수·분류·검증에 쓰지 않는다" in report
    assert "미실행" not in report and report.count("- 탐색 분석") == 1
    # 다시 실행해도 같은 바이트
    before = (out / "timeline.md").read_bytes(), (out / "report.md").read_bytes()
    assert _explore_cmd(out, item["key"]) == explore
    assert ((out / "timeline.md").read_bytes(), (out / "report.md").read_bytes()) == before
    # run을 다시 하면 이전 타임라인은 지워지고 리포트 줄은 미실행으로 돌아간다
    _offline(item, doc, out)
    assert not (out / "timeline.md").exists()
    assert "- 탐색 분석 (추정): 미실행" in (out / "report.md").read_text(encoding="utf-8")


def test_explore_subcommand_exit_codes():
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    _offline(items[0], doc, out)                   # 후보 확정 → 입력 파일 없음
    assert not (out / "explore-input.json").exists()
    assert run("triage.py", ["explore", "x", "--out", out]).returncode == 1
    assert run("triage.py", ["explore", "x", "--out", out.parent / "none"]).returncode == 2
    item = next(i for i in items if i["expect"] == "unresolved")
    out2 = tmp("tt-triage-") / "y"
    _offline(item, doc, out2)
    (out2 / "events.json").unlink()
    assert run("triage.py", ["explore", "y", "--out", out2]).returncode == 2
    assert not (out2 / "timeline.md").exists()


def test_stale_timeline_is_removed_by_run():
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    out.mkdir()
    (out / "timeline.md").write_text("old\n", encoding="utf-8")
    (out / "explore-input.json").write_text("{}", encoding="utf-8")
    _offline(items[0], doc, out)                   # 후보 확정이라 탐색 대상이 아니다
    assert not (out / "timeline.md").exists() and not (out / "explore-input.json").exists()


def test_confirmed_cause_has_no_explore_and_no_timeline():
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    analysis = _offline(items[0], doc, out)
    assert analysis["candidates"][0]["C"] == 1
    assert "explore" not in analysis and not (out / "timeline.md").exists() and not (out / "explore-input.json").exists()
    assert "탐색 분석" not in (out / "report.md").read_text(encoding="utf-8")


def test_explore_never_skips_timeline_but_says_so():
    doc, items = _items()
    item = next(i for i in items if i["expect"] == "unresolved")
    out = tmp("tt-triage-") / "x"
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": item["key"], "occurred_at": item["occurred_at"]}), encoding="utf-8")
    logs = [str((LABELSET.parent / p).resolve()) for p in item["logs"]]
    analysis = run_json("triage.py", ["run", item["key"], "--offline-db", SAMPLE, "--out", out, "--logs", *logs,
                                      "--jira-meta", meta, "--tz", doc["tz"], "--year", doc["year"]],
                        root=plugin_root(explore={"when": "never"}))
    assert analysis["explore"] == {"reason": "no_candidate", "when": "never"}
    assert not (out / "timeline.md").exists() and not (out / "explore-input.json").exists()
    assert "탐색 분석: 생략 (explore.when: never)" in (out / "report.md").read_text(encoding="utf-8")


def test_explore_marks_cause_unconfirmed_and_rejects_bad_settings(tmp_path):
    from types import SimpleNamespace
    triage = _triage_module()
    drv = SimpleNamespace(cfg={"explore": {"when": "sometimes", "timeline_max_lines": 5}}, warnings=[], job=tmp_path, key="K-1",
                          failed_step={"text": "4 | x | FAIL", "source": "cli"})
    got = triage.Driver.explore(drv, [{"C": 0}])
    assert got == {"reason": "cause_unconfirmed", "when": "ask"}
    spec = triage.Driver.explore_input(drv, "2026-09-20T05:30:00Z", None)
    assert spec == {"around": "2026-09-20T05:30:00Z", "failed_step": "4 | x | FAIL", "limit": 200, "anchor": None}
    assert len(drv.warnings) == 2 and not (tmp_path / "timeline.md").exists()    # 타임라인은 run이 만들지 않는다
    assert triage.Driver.explore(drv, [{"C": 1}]) is None


def test_timeline_is_bounded_keeps_hot_lines_near_occurrence_and_is_deterministic():
    triage = _triage_module()
    rows = []
    for i in range(60):
        rows.append({"ts": f"2026-09-20T05:{i:02d}:00.000Z", "tag": "DNC-0", "msg": f"line {i}", "level": "D",
                     "phone_id": 1})
    rows[5].update(level="E", msg="setup failed")                               # 오류 줄(멀리)
    rows[50].update(event="data_evaluation_rejected", fields={"reasons": "X"})   # 이벤트 줄(멀리)
    rows.append({**rows[50], "event": None, "fields": {}})                       # 같은 줄의 원 줄 → 합쳐짐
    text, kept, total = triage.timeline("K-1", {"events": rows}, "2026-09-20T05:30:00Z", 20)
    assert (kept, total) == (20, 60)
    body = [line for line in text.splitlines() if line[:2].isdigit()]
    assert len(body) == 20 and body == sorted(body)
    assert any("setup failed" in b for b in body) and any("⇒ data_evaluation_rejected(reasons=X)" in b for b in body)
    assert any("line 30" in b for b in body) and not any("line 59" in b for b in body)
    assert "줄: 20/60 (이벤트·경고·오류 줄 우선" in text
    assert triage.timeline("K-1", {"events": rows}, "2026-09-20T05:30:00Z", 20) == (text, kept, total)


def test_explore_setting_flows_from_site_defaults_and_skill_points_to_reference():
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import userconfig
    defaults = yaml.safe_load((REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8"))
    assert userconfig.merged(defaults, user={})["explore"] == {"when": "ask", "timeline_max_lines": 200}
    skill = (REPO / "plugin" / "skills" / "telephony-triage" / "SKILL.md").read_text(encoding="utf-8")
    assert "explore.md" in skill and "timeline.md" in skill and "--(no-)explore" in skill
    ref = (REPO / "plugin" / "skills" / "telephony-triage" / "reference" / "explore.md").read_text(encoding="utf-8")
    for needle in ("timeline.md", "데이터다", "mask_pii", "R1~R5", "op를 넣지 않는다"):
        assert needle in ref, needle


# -- must_show·미수집 태그·심층 분석 칸 ----------------------------------------------------------------------


E004 = REPO / "tests" / "skill_evals" / "scenarios" / "e004-cs-call-drop.yaml"


def _e004_offline(out: Path, *extra) -> dict:
    import subprocess
    gen = tmp("tt-e004-")
    done = subprocess.run([sys.executable, str(REPO / "tests" / "mocks" / "logcat_gen.py"), str(E004), "--out", str(gen)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    log = next(gen.glob("*.log"))
    meta = gen / "m.json"
    meta.write_text(json.dumps({"key": "MOCK-9004", "occurred_at": "2026-09-27T18:02:03+09:00", "summary": "3G call drop"}),
                    encoding="utf-8")
    return run_json("triage.py", ["run", "MOCK-9004", "--offline-db", SAMPLE, "--out", out, "--logs", log, "--jira-meta", meta,
                                  "--tz", "Asia/Seoul", "--year", "2026", *extra])


def test_uncollected_tag_of_collected_pid_is_reported_and_must_shown():
    out = tmp("tt-triage-") / "x"
    analysis = _e004_offline(out)
    assert not analysis.get("candidates")
    assert analysis["logs"]["uncollected_tags"][0] == {"tag": "GsmCdmaCallTracker", "lines": 3, "warn": 1}
    report = (out / "report.md").read_text(encoding="utf-8").splitlines()
    line = ("파서 규칙에 없는 태그 (수집 태그와 같은 프로세스, tags.yaml에 없어 이벤트로 추출 안 됨): "
            "GsmCdmaCallTracker 3줄(W/E 1)")
    assert f"- {line}" in report and line in analysis["must_show"]
    # 후보 없음: 로그 범위 줄도 must_show에 있다(시계 이상 없음)
    assert any(m.startswith("로그 범위:") and "시계 이상 없음" in m for m in analysis["must_show"])
    assert analysis["must_show"][-1] == line      # 우선순위 순: 로그 범위(6) 뒤에 미수집 태그(8)
    assert len((out / "analysis.json").read_bytes()) <= 4096 and analysis["truncated"] is False


def test_confirmed_top_has_no_uncollected_tags_and_no_range_must_show():
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    analysis = _offline(items[0], doc, out)
    assert "uncollected_tags" not in analysis["logs"]
    assert not any(m.startswith("파서 규칙에 없는 태그") for m in analysis.get("must_show") or [])


def test_analysis_only_report_line_is_first_must_show():
    ws = Workspace()
    done = ws.json("triage.py", ["run", "MOCK-1001", "--analysis-only", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml",
                                 "--logs", DATA_LOG, "--answer", "code=skip"])
    report = (ws.job_dir("MOCK-1001") / "report.md").read_text(encoding="utf-8").splitlines()
    assert done["must_show"][0].startswith("분석 전용:") and f"- {done['must_show'][0]}" in report
    assert report[2] == f"- {done['must_show'][0]}"


def test_fit_keeps_first_must_show_and_stays_within_4kb():
    triage = _triage_module()
    big = {"ts": "2026-09-20T05:30:00.000Z", "tag": "DNC-0", "msg": "x" * 140, "event": "e"}
    must = ["분석 전용: " + "가" * 300, "읽기 전용: " + "나" * 300, "재분석: " + "다" * 300, "실패 스텝 " + "라" * 300,
            "장비 시각 미사용: " + "마" * 300, "로그 범위: " + "바" * 300]
    result = {"warnings": ["w" * 120] * 10, "files": {"report": "r", "events": "e"}, "read_only_hint": "힌트" * 80,
              "must_show": must, "candidates": [{"cause": f"C-{i}", "evidence": [dict(big) for _ in range(10)]} for i in range(3)]}
    out = triage.fit(result)
    assert len(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8")) <= 4096 and out["truncated"] is False
    assert out["must_show"][0].startswith("분석 전용:")
    # must_show만 커서 다른 줄임으로 부족하면 마지막에 줄당 160자로 자르고 앞 4개만 남긴다
    clipped = triage.fit({"files": {"report": "r"}, "must_show": must})
    assert len(clipped["must_show"]) == 6 and all(len(m) <= 160 for m in clipped["must_show"])
    only = triage.fit({"files": {"report": "r"}, "notes": ["n" * 300] * 5, "must_show": must})
    assert len(only["must_show"]) == 4 and all(len(m) <= 160 for m in only["must_show"])
    assert only["must_show"][0].startswith("분석 전용:") and only["truncated"] is False
    # 읽기 전용 줄이 must_show에 있으면 넘칠 때 read_only_hint를 먼저 뺀다
    small = {"read_only_hint": "힌트" * 500, "must_show": ["읽기 전용: " + "힌트" * 500], "files": {"report": "r"}}
    assert "read_only_hint" not in triage.fit(small)


def _analyzer_report(cfg: dict) -> str:
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    meta = out.parent / "m.json"
    meta.write_text(json.dumps({"key": items[0]["key"], "occurred_at": items[0]["occurred_at"]}), encoding="utf-8")
    logs = [str((LABELSET.parent / p).resolve()) for p in items[0]["logs"]]
    run_json("triage.py", ["run", items[0]["key"], "--offline-db", SAMPLE, "--out", out, "--logs", *logs,
                           "--jira-meta", meta, "--tz", doc["tz"], "--year", doc["year"]], root=plugin_root(**cfg))
    return (out / "report.md").read_text(encoding="utf-8")


def test_deep_analysis_slot_depends_on_analyzer_setting():
    ask = _analyzer_report({"analyzers": {"data": {"skill": "mock-data-analyzer", "when": "ask"}}})
    assert ("- 심층 분석 (mock-data-analyzer): TODO(LLM) 결과 요약 / 분석 스킬 의견: <원인 ID — 근거 | 1위와 같음>. "
            "실행 안 함·실패면 이 줄을 \"심층 분석 생략: <사유>\"로") in ask
    never = _analyzer_report({"analyzers": {"data": {"skill": "mock-data-analyzer", "when": "never"}}})
    assert "- 심층 분석 생략: analyzers.data.when: never" in never
    none = _analyzer_report({"analyzers": {"other": {"skill": "x", "when": "ask"}}})
    assert "- 심층 분석: 해당 없음(1위 카테고리에 분석 스킬 설정 없음)" in none


# -- 실패 스텝(선택 입력, 보조 정보) ---------------------------------------------------------------------


def _offline_with(item: dict, doc: dict, out: Path, *extra, meta_extra: dict | None = None) -> dict:
    meta = out.parent / f"{out.name}.meta.json"
    meta.write_text(json.dumps({"key": item["key"], "occurred_at": item["occurred_at"],
                                "summary": item.get("summary", ""), **(meta_extra or {})}, ensure_ascii=False),
                    encoding="utf-8")
    logs = [str((LABELSET.parent / p).resolve()) for p in item["logs"]]
    return run_json("triage.py", ["run", item["key"], "--offline-db", SAMPLE, "--out", out, "--logs", *logs,
                                  "--jira-meta", meta, "--tz", doc["tz"], "--year", doc["year"], *extra])


def test_absent_failed_step_is_byte_identical_even_with_steps_file_without_fail_line():
    doc, items = _items()
    steps = tmp("tt-steps-") / "steps.txt"
    steps.write_text("1. 전원 켜기\n2. 설정 열기\n", encoding="utf-8")
    for item in (items[0], next(i for i in items if i["expect"] == "unresolved")):
        work = tmp("tt-triage-")
        plain = _offline_with(item, doc, work / "a")
        withfile = _offline_with(item, doc, work / "b", "--steps-file", steps)
        strip = lambda r: {k: v for k, v in r.items() if k not in ("generated_at", "files")}  # noqa: E731
        assert strip(plain) == strip(withfile)
        assert "failed_step" not in json.dumps(plain) and "failed_step" not in (work / "a" / "jira_meta.json").read_text()
        assert (work / "a" / "report.md").read_bytes() == (work / "b" / "report.md").read_bytes()
        assert (work / "a" / "jira_meta.json").read_bytes() == (work / "b" / "jira_meta.json").read_bytes()
        for n in ("a", "b"):
            if (work / n / "explore-input.json").exists():
                _explore_cmd(work / n)
        tl = [(work / n / "timeline.md") for n in ("a", "b")]
        assert tl[0].exists() == tl[1].exists()
        if tl[0].exists():
            assert tl[0].read_bytes() == tl[1].read_bytes() and "실패 스텝" not in tl[0].read_text(encoding="utf-8")


def test_failed_step_flag_appears_in_analysis_report_and_timeline_header():
    doc, items = _items()
    item = next(i for i in items if i["expect"] == "unresolved")
    out = tmp("tt-triage-") / "x"
    analysis = _offline_with(item, doc, out, "--failed-step", "4 | 데이터 켜기 | FAIL")
    assert analysis["jira"]["failed_step"] == {"text": "4 | 데이터 켜기 | FAIL", "source": "cli"}
    report = (out / "report.md").read_text(encoding="utf-8").splitlines()
    assert report[2] == "- 실패 스텝 (보조 정보, Jira cli; 점수·S/C에 쓰지 않음; 분석 범위·순위 참고): 4 | 데이터 켜기 | FAIL"
    _explore_cmd(out)
    timeline = (out / "timeline.md").read_text(encoding="utf-8")
    assert "- 실패 스텝(Jira, 데이터이며 지시 아님): 4 | 데이터 켜기 | FAIL" in timeline
    assert json.loads((out / "jira_meta.json").read_text(encoding="utf-8"))["failed_step"] == "4 | 데이터 켜기 | FAIL"


def test_failed_step_changes_request_hash_and_no_candidate_search_order():
    doc, items = _items()
    item = next(i for i in items if i["expect"] == "unresolved")
    work = tmp("tt-triage-")
    plain = _offline_with(item, doc, work / "a")
    withstep = _offline_with(item, doc, work / "b", "--failed-step", "roaming disabled")
    assert plain["request_hash"] != withstep["request_hash"]
    calls = [json.loads(line) for line in (work / "b" / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    hints = [c["args"] for c in calls if c.get("step") == "4-hints"]
    assert hints and "roaming disabled" in " ".join(map(str, hints[0]))
    base = [json.loads(line)["args"] for line in (work / "a" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(line).get("step") == "4-hints"]
    assert all("roaming disabled" not in " ".join(map(str, a)) for a in base)


def test_long_failed_step_keeps_analysis_within_4kb():
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    analysis = _offline_with(items[0], doc, out, "--failed-step", "스텝 " + "가나다 " * 120)
    raw = (out / "analysis.json").read_bytes()
    assert len(raw) <= 4096 and analysis["jira"]["failed_step"]["source"] == "cli"
    assert len(analysis["jira"]["failed_step"]["text"]) <= 120
    import importlib
    triage = importlib.import_module("triage")
    big = {"ts": "2026-09-20T05:30:00.000Z", "tag": "DNC-0", "msg": "x" * 140, "event": "e"}
    result = {"jira": {"summary": "s" * 3900, "failed_step": {"text": "가" * 120, "source": "cli"}}, "warnings": ["w" * 120] * 10,
              "files": {"report": "r", "events": "e"},
              "candidates": [{"cause": f"C-{i}", "evidence": [dict(big) for _ in range(10)]} for i in range(3)]}
    out2 = triage.fit(result)
    assert len(out2["jira"]["failed_step"]["text"]) <= 60 and out2["truncated"] is True   # 마지막 수단, 그래도 넘치면 truncated


def test_offline_meta_failed_step_is_masked_and_used():
    doc, items = _items()
    out = tmp("tt-triage-") / "x"
    analysis = _offline_with(items[0], doc, out, meta_extra={"failed_step": "고객 010-1234-5678 데이터 켜기"})
    assert "010-1234-5678" not in json.dumps(analysis, ensure_ascii=False)
    assert "010-1234-5678" not in (out / "report.md").read_text(encoding="utf-8")
    assert analysis["jira"]["failed_step"]["source"] == "field"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


def test_unique_evidence_drops_same_event_from_symptom_and_cause():
    import triage
    ev = [{"event_index": 5, "ts": "t", "tag": "DNC-1", "msg": "m", "signature": "DATA-001-02/x"},
          {"event_index": 5, "ts": "t", "tag": "DNC-1", "msg": "m", "signature": "DATA-001/y"},
          {"event_index": 7, "ts": "t2", "tag": "DNC-1", "msg": "m2"},
          {"ts": "t3", "tag": "A", "msg": "x"}, {"ts": "t3", "tag": "A", "msg": "x"}]
    out = triage._unique_evidence(ev)
    assert [e.get("event_index") for e in out] == [5, 7, None]
    assert out[0]["signature"] == "DATA-001-02/x"     # 처음 것(원인 근거)을 남긴다


def test_unique_evidence_keys_on_line_ref_first():
    import triage
    ref = {"file_index": 0, "line_no": 12}
    ev = [{"event_index": 5, "line_ref": ref, "ts": "t", "tag": "A", "msg": "m", "signature": "S1"},
          {"event_index": 6, "line_ref": dict(ref), "ts": "t", "tag": "A", "msg": "m", "signature": "S2"},   # 파생 이벤트: 같은 줄
          {"event_index": 7, "line_ref": {"file_index": 1, "line_no": 12}, "ts": "t", "tag": "A", "msg": "m"},   # 다른 파일
          {"event_index": 8, "line_ref": {"file_index": 0, "line_no": None}, "ts": "t", "tag": "A", "msg": "m"},   # 줄 번호 모름 → event_index
          {"event_index": 8, "ts": "t", "tag": "A", "msg": "m"}]
    out = triage._unique_evidence(ev)
    assert [e["event_index"] for e in out] == [5, 7, 8]
    assert out[0]["signature"] == "S1"


# -- 3D-A: 후보 없음 오류 이벤트 상세·읽기 전용 안내 -------------------------------------------------------------


def test_no_candidate_error_events_carry_request_and_error_and_report_lists_them():
    log = tmp("tt-ril-") / "ril.log"
    log.write_text("09-22 12:00:00.000  1234  1244 D RILJ: [PHONE1] [0041]> SETUP_DATA_CALL apn=ims\n"
                   "09-22 12:00:01.000  1234  1244 D RILJ: [PHONE1] [0041]< SETUP_DATA_CALL error=INSUFFICIENT_RESOURCES\n",
                   encoding="utf-8")
    out = tmp("tt-triage-") / "x"
    meta = out.parent / "x.meta.json"
    meta.write_text(json.dumps({"key": "MOCK-7400", "occurred_at": "2026-09-22T12:00:01.000Z", "summary": ""}),
                    encoding="utf-8")
    analysis = run_json("triage.py", ["run", "MOCK-7400", "--offline-db", SAMPLE, "--out", out, "--logs", log,
                                      "--jira-meta", meta, "--tz", "UTC", "--year", 2026])
    assert not analysis.get("candidates")
    rows = analysis["no_candidate"]["error_events"]
    assert rows[0]["event"] == "ril_error" and rows[0]["request"] == "SETUP_DATA_CALL"
    assert rows[0]["error"] == "INSUFFICIENT_RESOURCES" and rows[0]["phone"] == 1
    assert len((out / "analysis.json").read_bytes()) <= 4096
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "- 오류·거부·타임아웃 이벤트: 1건" in report
    assert "  - 2026-09-22T12:00:01.000Z RILJ ril_error request=SETUP_DATA_CALL error=INSUFFICIENT_RESOURCES (phone 1)" in report


def test_read_only_mode_shows_update_hint_in_analysis_and_report():
    ws = Workspace()
    ws.push_main(lambda c: (c / "issue-db.config.yaml").write_text(
        (c / "issue-db.config.yaml").read_text(encoding="utf-8").replace("schema_version: 1", "schema_version: 99"),
        encoding="utf-8", newline="\n"))
    args = ["run", "MOCK-1001", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml", "--logs", DATA_LOG,
            "--answer", "code=skip"]
    done = ws.json("triage.py", args)
    assert done["status"] == "ok" and done["mode"] == "read-only"
    assert "schema-too-new" in done["read_only_reasons"]
    assert "플러그인을 업데이트" in done["read_only_hint"] and len(done["read_only_hint"].encode("utf-8")) <= 200
    job = ws.job_dir("MOCK-1001")
    assert len((job / "analysis.json").read_bytes()) <= 4096
    assert "- 읽기 전용: " in (job / "report.md").read_text(encoding="utf-8")
    assert "플러그인을 업데이트" in (job / "report.md").read_text(encoding="utf-8")


# -- W4 질문 수 줄이기: 코드 경로 자동 선택·잔여물 알림 (07-workflow.md §Step 0·§Step 2-1, 02-config.md, contracts.md) -------------
# 표의 각 행은 문서 출처(`07 §…`, `02 §…`, `contracts §…`)를 적는다.

SRC = REPO / "tests" / "mocks" / "src"
W4_KEY = "MOCK-1001"      # Jira Android 16
W4_DOCS = REPO / "docs" / "design"


def _profile(name: str, version: str, tree: Path | str | None = None) -> dict:
    tree = str(tree or SRC / f"android{version}")
    return {"name": name, "android_version": version, "roots": {"aosp": tree, "vendor_ril": tree}}


def _w4_config(ws: Workspace, **extra) -> None:
    path = ws.home / "config.yaml"
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg.update(extra)
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


def _w4_run(ws: Workspace, *extra, jira: Path | None = None) -> dict:
    mode = [] if "--analysis-only" in extra else ["--dry-run"]
    args = ["run", W4_KEY, *mode, "--jira-file", jira or MOCK_JIRA / f"{W4_KEY}.yaml", "--logs", DATA_LOG, *extra]
    return ws.json("triage.py", args)


def _w4_trace(ws: Workspace) -> list[dict]:
    path = ws.job_dir(W4_KEY) / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _suggest_calls(ws: Workspace) -> int:
    return sum(1 for r in _w4_trace(ws) if r.get("script") == "code_roots.py" and (r.get("args") or [""])[0] == "suggest")


def _w4_state(ws: Workspace) -> dict:
    return json.loads((ws.job_dir(W4_KEY) / "triage-state.json").read_text(encoding="utf-8"))


def _no_version_jira(tmp_path: Path) -> Path:
    text = (MOCK_JIRA / f"{W4_KEY}.yaml").read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if "# Android 버전" not in line]
    out = tmp_path / "no-version.yaml"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _asked_code(done: dict) -> None:
    assert done["status"] == "needs_input" and done["needs_input"]["kind"] == "code", done


def test_code_auto_select_table():
    """07 §Step 2-1 3번(자동 선택 조건) · 02-config code.auto_select(우선순위 사용자 config > site-defaults > true)."""
    p16, p16b, p17 = _profile("android16-main", "16"), _profile("android16-alt", "16"), _profile("android17-dev", "17")
    site_false = plugin_root("w4-site-false", code={"auto_select": False})
    rows = [  # (이름, 프로필, 사용자 config code, 플러그인 루트, 기대: 자동 선택 여부)
        ("일치 0개", [p17], None, None, False),
        ("일치 1개", [p16, p17], None, None, True),
        ("일치 2개 이상", [p16, p16b, p17], None, None, False),
        ("user auto_select false", [p16], {"auto_select": False}, None, False),
        ("site-defaults auto_select false", [p16], None, site_false, False),
        ("user true가 site false보다 우선", [p16], {"auto_select": True}, site_false, True),
    ]
    for name, profiles, user_code, root, expect_auto in rows:
        ws = Workspace(root=root) if root else Workspace()
        _w4_config(ws, code_profiles=profiles, **({"code": user_code} if user_code is not None else {}))
        saved = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
        assert ("code" in saved) == (user_code is not None), name     # setup이 site-defaults의 code를 사용자 config에 복사하지 않는다
        done = _w4_run(ws)
        if expect_auto:
            assert done["status"] == "ok" and done["code"]["auto"] is True and done["code"]["roots"] == "android16-main", name
            report = (ws.job_dir(W4_KEY) / "report.md").read_text(encoding="utf-8")
            assert "(자동 선택: code.auto_select)" in report and "분석 트리: android16-main" in report, name
            assert _w4_state(ws)["code_auto"] == "android16-main" and "code" not in _w4_state(ws)["answers"], name
            assert not [w for w in done.get("warnings", []) if "code.auto_select" in w], name     # 키 없음·유효 값은 경고 없음
        else:
            _asked_code(done)
            assert "잘못돼" not in done["needs_input"]["question"], name
            assert "code_auto" not in _w4_state(ws), name
            assert any(o["value"] == "skip" for o in done["needs_input"]["options"]), name
        ws.json("triage.py", ["release", W4_KEY])


def test_invalid_auto_select_values_ask_and_warn():
    """02 §4 code.auto_select: 유효 값은 불리언뿐. 문자열·0/1·null은 explore.when처럼 warnings(ok 출력)에 남기고 묻는다(질문 문구에도 표시)."""
    for value in ("false", "true", 0, 1, None):
        ws = Workspace()
        _w4_config(ws, code_profiles=[_profile("android16-main", "16")], code={"auto_select": value})
        asked = _w4_run(ws)
        _asked_code(asked)
        assert asked["needs_input"]["question"].endswith("(code.auto_select 값이 잘못돼 묻기로 본다)"), value
        done = _w4_run(ws, "--answer", "code=skip")      # 답이 있어도 점검해 경고가 ok 출력에 남는다
        assert done["status"] == "ok" and f"code.auto_select 값이 잘못됐다({value}). 묻기로 본다" in done["warnings"], value
        ws.json("triage.py", ["release", W4_KEY])


def test_code_flag_and_answer_win_over_auto_select():
    """07 §Step 2-1 2번·3번: --code·사용자 답이 자동 선택보다 우선, 자동 선택 표시 없음."""
    ws = Workspace()
    _w4_config(ws, code_profiles=[_profile("android16-main", "16")])
    skipped = _w4_run(ws, "--code", "skip")
    assert skipped["status"] == "ok" and skipped["code"] == {"skipped": True} and "code_auto" not in _w4_state(ws)
    answered = _w4_run(ws, "--answer", f"code={SRC / 'android16'}")
    assert answered["status"] == "ok" and "auto" not in answered["code"] and "code_auto" not in _w4_state(ws)
    assert "자동 선택" not in (ws.job_dir(W4_KEY) / "report.md").read_text(encoding="utf-8")
    ws.json("triage.py", ["release", W4_KEY])


def test_code_without_jira_version_still_asks(tmp_path):
    """07 §Step 2-1 3번: Jira 버전이 없으면(대체 출처는 쓰지 않는다) 자동 선택하지 않는다."""
    ws = Workspace()
    _w4_config(ws, code_profiles=[_profile("android16-main", "16")])
    done = _w4_run(ws, jira=_no_version_jira(tmp_path))
    _asked_code(done)
    ws.json("triage.py", ["release", W4_KEY])


def test_code_recent_only_match_is_not_auto_selected():
    """07 §Step 2-1 3번: 최근 사용 경로만 일치하면 자동 선택하지 않는다."""
    ws = Workspace()
    _w4_config(ws, code_profiles=[_profile("android17-dev", "17")],
               recent_code_roots=[{"roots": {"aosp": str(SRC / "android16")}, "used_on": "2026-09-25"}])
    _asked_code(_w4_run(ws))
    ws.json("triage.py", ["release", W4_KEY])


def test_invalid_auto_path_asks_full_choices_and_records_nothing():
    """07 §Step 2-1 3번: 자동 선택 경로가 무효면 전체 선택지로 묻고 `code_auto`를 기록하지 않는다(재실행도 다시 묻는다)."""
    ws = Workspace()
    gone = tmp("tt-gone-") / "missing"
    _w4_config(ws, code_profiles=[_profile("android16-main", "16", gone), _profile("android17-dev", "17")])
    for _ in range(2):
        done = _w4_run(ws)
        _asked_code(done)
        values = [o["value"] for o in done["needs_input"]["options"]]
        assert "android16-main" in values and "android17-dev" in values and "skip" in values
        assert any(v.startswith("<경로") for v in values) and "유효하지 않다" in done["needs_input"]["question"]
        assert "code_auto" not in _w4_state(ws)
    ws.json("triage.py", ["release", W4_KEY])


def test_auto_selected_tree_version_mismatch_uses_code_confirm():
    """07 §Step 2-1 4번: 트리 버전이 다르면 기존 `code_confirm`(자동 선택해도 같다)."""
    ws = Workspace()
    _w4_config(ws, code_profiles=[_profile("android16-main", "16", SRC / "android17")])
    done = _w4_run(ws)
    assert done["status"] == "needs_input" and done["needs_input"]["kind"] == "code_confirm", done
    again = _w4_run(ws, "--answer", "code_confirm=yes")
    assert again["status"] == "ok" and again["code"]["auto"] is True
    ws.json("triage.py", ["release", W4_KEY])


def test_auto_select_is_idempotent_within_a_session_and_rejudged_for_a_new_owner():
    """07 §Step 2-1 3번(code_auto): 같은 owner 재실행은 다시 고르지 않고 request_hash 동일, 새 owner는 다시 판단한다."""
    ws = Workspace()
    _w4_config(ws, code_profiles=[_profile("android16-main", "16")])
    first = _w4_run(ws)
    calls = _suggest_calls(ws)
    assert first["code"]["auto"] is True and calls == 1
    second = _w4_run(ws)
    assert second["request_hash"] == first["request_hash"] and second["code"]["auto"] is True
    assert _suggest_calls(ws) == calls, "재실행은 다시 고르지 않고 code_auto를 쓴다"
    ws.json("triage.py", ["release", W4_KEY])
    _w4_config(ws, code_profiles=[_profile("android16-main", "16"), _profile("android16-alt", "16")])
    _asked_code(_w4_run(ws))        # 새 owner: 상태가 초기화돼 일치 2개를 다시 판단한다
    assert "code_auto" not in _w4_state(ws)
    ws.json("triage.py", ["release", W4_KEY])


def _leftover(ws: Workspace, job: str = "MOCK-8800") -> Path:
    wt = ws.wt(job)
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(ws.clone, "worktree", "add", "--no-track", "-B", f"tt/{job}", str(wt), "origin/main")
    return wt


def test_other_job_leftovers_are_noted_never_asked_or_deleted():
    """07 §Step 0 cleanup 항목: 묻지 않고 지우지 않으며 notes로 알린다(`cleanup=yes`도 무시), `cleanup_targets`가 있으면 매번 알린다."""
    ws = Workspace()
    wt = _leftover(ws)
    before = _clone_state(ws)
    branches = git(ws.clone, "branch", "--list", "tt/*")
    note = "잔여 worktree·도구 브랜치 2개(붙여넣은 스텝 원문이 남아 있을 수 있음) — `/telephony-triage:sync`에서 정리"
    first = _w4_run(ws)                                   # 코드 질문 앞에서 멈춰도 cleanup은 묻지 않는다
    _asked_code(first)
    assert _w4_state(ws)["cleanup_targets"] == 2 and _w4_state(ws)["cleanup_done"] is True   # worktree 1 + 도구 브랜치 1
    done = _w4_run(ws, "--answer", "code=skip", "--answer", "cleanup=yes")     # NI 뒤 ok 출력에도 note가 있다
    assert done["status"] == "ok" and done["notes"] == [note]
    again = _w4_run(ws, "--answer", "code=skip")           # cleanup_done이 있어도 매 실행 note
    assert again["notes"] == [note]
    assert wt.is_dir() and git(ws.clone, "branch", "--list", "tt/*") == branches, "아무것도 지우지 않는다"
    assert not [r for r in _w4_trace(ws) if r.get("script") == "db_pr.py" and "--yes" in (r.get("args") or [])]
    assert _clone_state(ws)[:2] == before[:2] and "tt/MOCK-8800" in git(ws.clone, "branch", "--list")
    ws.json("triage.py", ["release", W4_KEY])


def test_no_leftovers_means_no_note_and_analysis_only_does_not_look():
    """07 §Step 0·§분석 전용: 대상이 없으면 note 없음, 분석 전용은 cleanup을 보지도 알리지도 않는다(0-cleanup trace 없음)."""
    ws = Workspace()
    done = _w4_run(ws, "--answer", "code=skip")
    assert "notes" not in done and "cleanup_targets" not in _w4_state(ws)
    ws.json("triage.py", ["release", W4_KEY])
    ws2 = Workspace()
    _leftover(ws2)
    only = _w4_run(ws2, "--analysis-only", "--answer", "code=skip")
    assert only["status"] == "ok" and "notes" not in only
    assert not [r for r in _w4_trace(ws2) if r.get("step") == "0-cleanup"]


def test_step8_current_key_tool_branch_still_asks_and_stops_when_declined():
    """07 §Step 8 2번(그대로): 현재 키 `tt/issue/<KEY>`만 있으면 삭제를 묻고 안 지우면 중단 — 질문은 스킬이 preflight 결과로 한다
    (`tool_branch`, triage.py kind 아님). analyze Step 0은 이 브랜치도 `cleanup --dry-run` 목록으로 알리기만 한다."""
    ws = Workspace()
    git(ws.clone, "branch", f"tt/issue/{W4_KEY}", "origin/main")
    done = _w4_run(ws, "--answer", "code=skip")
    assert done["status"] == "ok" and len(done["notes"]) == 1 and "브랜치 1개" in done["notes"][0]   # 알리기만 한다
    assert git(ws.clone, "branch", "--list", f"tt/issue/{W4_KEY}"), "지우지 않는다"
    pre = ws.db_pr("preflight", "--branch", f"issue/{W4_KEY}", "--search", W4_KEY, "--jira", W4_KEY)
    assert pre["tool_branch"]["exists"] is True and not pre["tool_branch"].get("worktree")
    step8 = (W4_DOCS / "07-workflow.md").read_text(encoding="utf-8")
    assert "이전 작업의 잔여물이다. 삭제할지 묻는다 (`db_pr cleanup`). 삭제하지 않으면 중단한다." in step8
    flow = (REPO / "plugin/skills/telephony-triage/reference/write-flow.md").read_text(encoding="utf-8")
    assert "이전 작업 잔여물. 삭제할지 묻는다" in flow and "거절하면 중단" in flow
    ws.json("triage.py", ["release", W4_KEY])


def test_w4_docs_match_the_implementation():
    """문서 문구 대조: 07 Step 0·2-1·5-1/5-2, 02-config 우선순위, contracts kind 목록·code.auto·notes, sync.md, SKILL 합친 질문."""
    wf = (W4_DOCS / "07-workflow.md").read_text(encoding="utf-8")
    step0 = wf[wf.index("### Step 0."):wf.index("### Step 1.")]
    assert "/telephony-triage:sync" in step0 and "`--yes`를 부르지 않고" in step0 and "cleanup_targets" in step0
    step21 = wf[wf.index("### Step 2-1."):wf.index("### Step 3.")]
    assert "code.auto_select" in step21 and "정확히 1개" in step21 and "(자동 선택: code.auto_select)" in step21
    step5 = wf[wf.index("### Step 5-1."):wf.index("### Step 6.")]
    assert "심층 분석과 탐색 분석을 할까요?" in step5 and "선택지 4개" in step5 and "선택지 2개" in step5
    cfg = (W4_DOCS / "02-config.md").read_text(encoding="utf-8")
    assert "사용자 config > `site-defaults.yaml` > 내장 기본값 `true`" in cfg
    contracts = "\n".join((W4_DOCS / name).read_text(encoding="utf-8")         # W7: analysis 키 트리는 생성 파일로
                           for name in ("contracts.md", "contracts-cli.md"))
    assert "(kind: `lock`·`plan`·`jira`" in contracts and "`cleanup`·`plan`" not in contracts
    assert "auto?(`true`: `code.auto_select`" in contracts and "cleanup_targets" in contracts and "notes?(" in contracts
    sync = (REPO / "plugin/commands/sync.md").read_text(encoding="utf-8")
    assert "analyze가 알린 잔여물" in sync
    skill = (REPO / "plugin/skills/telephony-triage/SKILL.md").read_text(encoding="utf-8")
    assert "심층 분석과 탐색 분석을 할까요?" in skill and "`notes`는 항상 알린다" in skill and "`--code`로 변경 가능" in skill
    doc = (REPO / "plugin/scripts/triage.py").read_text(encoding="utf-8").split('"""')[1]
    assert "`cleanup`(yes|no)" not in doc and "`code`(프로필|경로|skip)" in doc
