#!/usr/bin/env python3
"""RF-7 추가 로그 재분석 `--more-logs` (contracts.md §3.2 `triage.py`, 07-workflow.md §추가 로그 재분석).

이전 분석의 로그 뒤에 로그를 더해(순서 유지·sha256 중복 제거) Step 3~5를 합친 로그로 다시 계산하고, 이전 `analysis.json`·`report.md`는
`JOB/runs/<n>/`에 보관한다(최근 5개). `--logs`와는 함께 못 쓰고, 이전 로그가 없으면 종료 코드 2.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, tmp  # noqa: E402
from workspace import Workspace  # noqa: E402

MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
LOGS = REPO / "tests" / "fixtures" / "logs"
A = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"     # 1위 DATA-001-01
KEY = "MOCK-1001"
BASE = ["run", KEY, "--dry-run", "--jira-file", MOCK_JIRA / f"{KEY}.yaml", "--answer", "code=skip", "--answer", "window=full"]


def _rebase(src: Path, name: str, start: str) -> Path:
    """고정 로그의 시각(월-일 시:분:초)을 `start`부터 시작하도록 옮겨 MOCK-1001의 발생 시각(09-20 05:32Z) 근처에 놓는다."""
    lines = src.read_text(encoding="utf-8").splitlines()
    fmt = "%m-%d %H:%M:%S"
    origin = datetime.strptime(lines[0][:14], fmt)
    base = datetime.strptime(start, fmt)
    out = [(base + (datetime.strptime(ln[:14], fmt) - origin)).strftime(fmt) + ln[14:] if ln[:2].isdigit() else ln for ln in lines]
    path = tmp("tt-more-") / name
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path


def _first(ws: Workspace, *logs, extra=()) -> dict:
    done = ws.json("triage.py", [*BASE, "--logs", *(logs or [A]), *extra])
    assert done["status"] == "ok", done
    return done


def _more(ws: Workspace, *logs, extra=()) -> dict:
    done = ws.json("triage.py", [*BASE, "--more-logs", *logs, *extra])
    assert done["status"] == "ok", done
    return done


def _state(ws: Workspace) -> dict:
    return json.loads((ws.job_dir(KEY) / "triage-state.json").read_text(encoding="utf-8"))


def _report(ws: Workspace) -> str:
    return (ws.job_dir(KEY) / "report.md").read_text(encoding="utf-8")


def test_more_logs_appends_in_order_and_archives_previous_run():
    ws = Workspace()
    b = LOGS / "ims-registration-failed.log"
    first = _first(ws)
    job = ws.job_dir(KEY)
    old_analysis, old_report = (job / "analysis.json").read_bytes(), (job / "report.md").read_bytes()
    assert first["run"] == 1 and not (job / "runs").exists()
    more = _more(ws, b)
    assert more["logs"]["files"] == [A.name, b.name] and more["run"] == 2
    assert more["reuse"]["hit"] is False and more["reuse"]["changed"] == ["logs"] and more["reuse"]["added_logs"] == [b.name]
    assert more["reuse"]["prev_run"] == 1
    assert (job / "runs" / "1" / "analysis.json").read_bytes() == old_analysis
    assert (job / "runs" / "1" / "report.md").read_bytes() == old_report
    assert not (job / "runs" / "1" / "events.json").exists() and not (job / "runs" / "1" / "match.json").exists()
    assert f"(추가 로그 {b.name})" in _report(ws)
    assert [f["name"] for f in _state(ws)["job"]["logs"]] == [A.name, b.name]
    assert _state(ws)["logs"] == [str(A.resolve()), str(b.resolve())]       # 세션 logs 키도 합친 목록
    # --analysis-only에서도 되고, 합친 목록에 하나 더 붙는다(앞의 f<순번>은 그대로)
    c = LOGS / "sms-send-failed.log"
    only = ws.json("triage.py", [*[a for a in BASE if a != "--dry-run"], "--analysis-only", "--more-logs", c])
    assert only["status"] == "ok" and only["mode"] == "analysis-only", only
    assert only["logs"]["files"] == [A.name, b.name, c.name] and only["run"] == 3
    assert (job / "runs" / "2" / "analysis.json").is_file()


def test_more_logs_refuting_previous_top_sets_top_changed():
    """첫 로그는 통화 증상만(원인 미확인 C=0) 보여 CALL-001이 1위, 추가 로그의 IMS 등록 실패가 원인을 확인해 1위가 바뀐다."""
    ws = Workspace()
    a = _rebase(LOGS / "call-drop.log", "call-drop.log", "09-20 05:30:00")
    b = _rebase(LOGS / "ims-registration-failed.log", "ims-registration-failed.log", "09-20 05:33:00")
    first = _first(ws, a)
    assert first["candidates"][0]["type"] == "CALL-001" and first["candidates"][0]["cause"] is None
    more = _more(ws, b)
    top = more["candidates"][0]
    assert top["cause"] == "IMS-001-01", more["candidates"]
    reuse = more["reuse"]
    assert reuse["prev_top"] == "CALL-001" and reuse["top_changed"] is True and reuse["added_logs"] == [b.name]
    assert "- 재분석: 실행 1 대비 바뀐 입력 [logs] (추가 로그 ims-registration-failed.log) — 1위 CALL-001 → IMS-001-01" in _report(ws)
    # 이전 가설의 분석은 보관돼 있다
    kept = json.loads((ws.job_dir(KEY) / "runs" / "1" / "analysis.json").read_text(encoding="utf-8"))
    assert kept["candidates"][0]["type"] == "CALL-001" and "추가 로그" not in (ws.job_dir(KEY) / "runs" / "1" / "report.md").read_text(encoding="utf-8")


def test_more_logs_rerun_is_idempotent_and_same_content_other_path_warns():
    ws = Workspace()
    b = LOGS / "ims-registration-failed.log"
    _first(ws)
    more = _more(ws, b)
    assert more["run"] == 2
    again = _more(ws, b)            # 같은 경로: 조용히 건너뛰고 로그 부분이 같아 재사용
    assert again["reuse"] == {"hit": True, "run": 2} and again["logs"]["files"] == [A.name, b.name]
    assert not [w for w in again.get("warnings") or [] if "more-logs-duplicate" in w]
    assert [f["name"] for f in _state(ws)["job"]["logs"]] == [A.name, b.name]
    copy = tmp("tt-more-") / "copy-of-ims.log"
    shutil.copyfile(b, copy)
    dup = _more(ws, copy)           # 내용이 같은 다른 경로: 경고하고 목록은 그대로
    assert any(w.startswith("more-logs-duplicate:") and copy.name in w for w in dup["warnings"]), dup.get("warnings")
    assert dup["reuse"] == {"hit": True, "run": 2} and dup["logs"]["files"] == [A.name, b.name]
    assert [f["name"] for f in _state(ws)["job"]["logs"]] == [A.name, b.name]
    assert len(list((ws.job_dir(KEY) / "runs").iterdir())) == 1


def test_more_logs_without_previous_logs_is_usage_error():
    ws = Workspace()
    proc = ws.run("triage.py", [*BASE, "--more-logs", A])
    assert proc.returncode == 2 and "이전 분석 로그가 없다 — --logs로 시작한다" in proc.stderr, (proc.returncode, proc.stderr)
    assert not (ws.job_dir(KEY) / "analysis.json").exists()
    assert ws.json("db_pr.py", ["lock", "status"]).get("lock") in (None, {}), "lock이 풀려 있어야 한다"


def test_more_logs_with_logs_is_usage_error():
    ws = Workspace()
    _first(ws)
    proc = ws.run("triage.py", [*BASE, "--logs", A, "--more-logs", LOGS / "call-drop.log"])
    assert proc.returncode == 2 and "not allowed with" in proc.stderr, (proc.returncode, proc.stderr)


def test_runs_are_pruned_to_five():
    ws = Workspace()
    for minutes in range(1, 8):         # --minutes가 바뀔 때마다 args 해시가 달라 새로 계산한다
        _first(ws, extra=["--minutes", str(minutes)])
    runs = ws.job_dir(KEY) / "runs"
    assert sorted(int(d.name) for d in runs.iterdir()) == [2, 3, 4, 5, 6]      # 1은 지웠고 7은 현재 결과(analysis.json)
    assert (runs / "6" / "report.md").is_file() and _state(ws)["job"]["runs"][-1]["n"] == 7
