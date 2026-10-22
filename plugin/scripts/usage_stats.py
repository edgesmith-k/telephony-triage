#!/usr/bin/env python3
"""파일럿 운영 지표를 work_dir에서 뽑는다 (15-local-draft.md §15.5 S-7, contracts.md §3.2 작업 기록).

작업마다 `JOB/trace.jsonl`의 사건 행(triage `0-key`·`done`·`needs_input`·`error`, db_pr `stage`·`publish`·`discard`)과
파일 상태(`plan.json`·`state.json`·`triage-state.json`·`wt/`·`session.lock`, `common.jobstatus.quick_stage`)로 상태 하나를
고른다(위에서 처음 맞는 것): 손상 unknown → PR pr(`pr.number`) → push만 pushed(`pr.head_sha`) → 진행 중 in_progress(stage·
확인 화면 단계, `wt/`, 이 작업의 만료 전 lock) → 연습 practice(마지막 discard dry-run이고 그 뒤 analyze 없음, 또는 마지막 analyze --dry-run) → 취소
cancelled(마지막 discard cancel이고 그 뒤 analyze 없음) → 보류 held(계획 저장, 읽기 전용 계획은 held_read_only로도) →
분석만 analysis_only(분석 완료·계획 없음) → 결과 없음 no_result.
따로 세는 것: `_`·`.` 폴더와 표식(plan·state·trace·triage-state) 없는 폴더는 빼고, analyze 기록(`0-key`)이 없고 계획 source가
analyze·record가 아니면 other_flows, trace에 v≥2 행이 없으면(업데이트 전 작업) legacy(quick_stage별 건수만, 시간·취소·질문 미측정).
PR까지 = 첫 `0-key` → 그 뒤 첫 `publish{action: created, gh_ok: true}`(상태 pr인 작업만), 분석까지 = 첫 `0-key` → 그 뒤 첫
`done`(둘 다 경과 시간, 보류 포함). PR이 있는데 못 재면 pr_unmeasured(record처럼 analyze 없이 시작했거나 PR 뒤에 analyze한 작업).
재시도의 analyze 실행은 질문(`needs_input`) 바로 뒤의 `--answer` 재실행을 빼고 따로(answer_reruns) 센다. 시간대 없는(naive) 시각·
목록이 아닌 `job.runs` 같은 손상 값은 없는 것으로 본다. 드라이버 질문 = `needs_input` 행(kind
`issue` 제외), 대화 질문(AskUserQuestion)은 스크립트 신호가 없어 세지 않는다. release(Step 7) 사유는 기록이 없어 파일 상태로만
가른다(분석 뒤 기록하지 않음 = 분석만). `cleanup --yes`로 지운 작업은 빠진다.

`--transcripts [<dir>]`(opt-in, 기본 `$CLAUDE_CONFIG_DIR/projects` 또는 `~/.claude/projects`, 오프라인·읽기 전용): Claude Code
transcript에서 플러그인 세션(플러그인 스크립트 Bash 호출 또는 `telephony-triage` 스킬)의 usage를 응답(message.id)마다 한 번 세어
단계(basic·code·deep·explore·new_cause·write·post·other·retry·subagent, `transcripts()` 참고)로 나누고, 대화 질문(거부·입력 오류
아닌 AskUserQuestion·__ask_user)·심층 스킬 호출·show_guard 되돌림·거부·스크립트 오류(종료 1·2)·모델·Claude Code 버전을 센다.
단계 합 = 전체(자체 검사). 대상 세션이 없거나 usage가 없으면 미측정(0이 아니다). 숫자만 내고 내용·명령·경로·세션 ID는 내지 않는다.
플러그인 호출은 경로 모양(`…/scripts/<이름>.py`, `$S/<이름>.py`)만 본다. 세션 파일 하나씩(그 `subagents/` 포함) 필요한 필드만 줄여
읽고, 모양이 바뀐 줄은 `unreadable_lines`, 숫자가 아닌 usage는 `usage_missing`으로 센다.

CLI:
    python3 <plugin.scripts_path>/usage_stats.py [--work-dir <dir> | --platform <이름>] [--json] [--transcripts [<dir>]]
                                                 [--plugin-root <dir>]
    (`plugin.scripts_path`는 사용자 config — setup·SessionStart가 설치본 scripts 경로로 맞춘다. 읽기 전용)
    (기본: 선택 플랫폼(`--platform` > TT_PLATFORM > 사용자 config platform > site)의 사용자 config work_dir.
    `--work-dir`와 `--platform`은 함께 쓸 수 없다. `--work-dir`면 site-defaults를 읽지 않는다)
    텍스트 9줄(첫 줄 집계 대상). `--json`이면 JSON 한 줄 `{format: 2, platform, work_dir, jobs, states{…}, held_read_only,
    analysis_only_runs, cancel_ratio, pr_minutes{n, median, mean, values}, pr_unmeasured, analysis_minutes{…},
    questions{jobs, total, per_job, by_kind}, retries{runs, answer_reruns, errors, stages, stage_failed}, legacy{jobs, stages},
    other_flows, tokens}`
    (개수·시간만 — 작업 키·trace 메시지 없음, `--work-dir`면 `platform`은 null). `tokens`는 `--transcripts`가 없으면 null,
    있으면 `{dir, sessions, analyze_sessions, by_stage{단계: {calls, input, output, cache_read, cache_write}}, total(없으면 null),
    asks, deep_calls, show_guard{stop, deny}, script_errors, models, versions, usage_missing, unreadable_lines}`.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import platforms  # noqa: E402
from common import jobstatus, session_lock, shown, site_defaults, userconfig  # noqa: E402
from platforms import session as platform_session  # noqa: E402

MARKERS = (jobstatus.PLAN, jobstatus.STATE, jobstatus.TRACE, jobstatus.TRIAGE_STATE)
STATES = ("pr", "pushed", "in_progress", "practice", "cancelled", "held", "analysis_only", "no_result", "unknown")
STAGE_OK = ("ok", "needs-approval")


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ts(row: dict | None):
    """행 시각. 없거나 시간대가 없는(naive) 시각은 None — session_lock.read와 같은 규칙(aware 값끼리만 뺀다)."""
    try:
        t = session_lock.parse(str(row["ts"]))
    except (KeyError, TypeError, ValueError):
        return None
    return t if t.tzinfo is not None else None


def _minutes(rows: list, end) -> float | None:
    """첫 `0-key` → 그 **뒤** 처음 `end` 행까지 분. 앞에 있는 행(예: analyze 전에 record로 만든 PR)은 보지 않는다."""
    first = next((i for i, r in enumerate(rows) if r.get("step") == "0-key"), None)
    if first is None:
        return None
    t0, t1 = _ts(rows[first]), _ts(next((r for r in rows[first + 1:] if end(r)), None))
    return (t1 - t0).total_seconds() / 60 if t0 and t1 else None


def _runs(rows: list) -> tuple[int, int]:
    """(analyze 실행, 질문 답 재실행): 바로 앞 실행이 `needs_input`으로 끝난 뒤의 `0-key`는 `--answer` 재실행으로 따로 센다."""
    fresh = reruns = 0
    prev = None
    for r in rows:
        step = r.get("step")
        if step == "0-key":
            if prev == "needs_input":
                reruns += 1
            else:
                fresh += 1
            prev = None
        elif step in ("done", "needs_input", "stopped", "error"):
            prev = step
    return fresh, reruns


def _job(job: Path, lock: dict | None) -> dict:
    """작업 하나의 상태·시간·개수 (작업 키는 싣지 않는다)."""
    rows = jobstatus.trace_rows(job)
    plan, tstate = _json(job / jobstatus.PLAN), _json(job / jobstatus.TRIAGE_STATE)
    keys = [i for i, r in enumerate(rows) if r.get("step") == "0-key"]
    if not keys and plan.get("source") not in ("analyze", "record"):
        return {"kind": "other"}
    stage = jobstatus.quick_stage(job)
    if not any(isinstance(r.get("v"), int) and r["v"] >= 2 for r in rows):
        return {"kind": "legacy", "stage": stage}
    runs = (tstate.get("job") or {}).get("runs") if isinstance(tstate.get("job"), dict) else None
    runs = runs if isinstance(runs, list) else []           # 손상(목록 아님)은 실행 이력 없음으로
    last = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    pr = plan.get("pr") if isinstance(plan.get("pr"), dict) else {}
    discards = [(i, r) for i, r in enumerate(rows) if r.get("step") == "discard"]
    at, gone = discards[-1] if discards else (-1, {})
    if stage == "unknown":
        state = "unknown"
    elif pr.get("number"):
        state = "pr"
    elif pr.get("head_sha"):
        state = "pushed"
    elif stage in ("staged", "summary-shown") or (job / "wt").exists() \
            or (lock and lock.get("job") == job.name and not lock.get("expired")):
        state = "in_progress"
    elif (gone.get("outcome") == "dry-run" and not any(i > at for i in keys)) or last.get("dry_run") is True:
        state = "practice"
    elif gone.get("outcome") == "cancel" and not any(i > at for i in keys):
        state = "cancelled"
    elif stage == "plan-saved":
        state = "held"
    elif stage == "analyzed":
        state = "analysis_only"
    else:
        state = "no_result"
    asked = [str(r.get("kind")) for r in rows if r.get("step") == "needs_input" and r.get("kind") != "issue"]
    stages = [r for r in rows if r.get("step") == "stage"]
    fresh, reruns = _runs(rows)
    return {"kind": "measured", "state": state, "read_only": state == "held" and last.get("mode") == "read-only",
            "analysis_only_runs": sum(1 for r in runs if isinstance(r, dict) and r.get("mode") == "analysis-only"),
            "pr_min": _minutes(rows, lambda r: r.get("step") == "publish" and r.get("action") == "created"
                               and r.get("gh_ok") is True),
            "analysis_min": _minutes(rows, lambda r: r.get("step") == "done"),
            "asked": asked, "runs": fresh, "answer_reruns": reruns, "errors": sum(1 for r in rows if r.get("step") == "error"),
            "stages": len(stages), "stage_failed": sum(1 for r in stages if r.get("result") not in STAGE_OK)}


def _dist(values: list) -> dict:
    if not values:
        return {"n": 0, "median": None, "mean": None, "values": []}
    return {"n": len(values), "median": round(statistics.median(values), 1), "mean": round(statistics.mean(values), 1),
            "values": sorted(round(v, 1) for v in values)}


def stats(work_dir: Path) -> dict:
    try:
        lock = session_lock.describe(session_lock.read(work_dir))
    except (session_lock.LockError, KeyError, ValueError):
        lock = None
    jobs = []
    for d in sorted(work_dir.iterdir()):
        if d.name.startswith(("_", ".")) or not d.is_dir() or not any((d / m).exists() for m in MARKERS):
            continue
        jobs.append(_job(d, lock))
    measured = [j for j in jobs if j["kind"] == "measured"]
    legacy = [j for j in jobs if j["kind"] == "legacy"]
    states = {k: sum(1 for j in measured if j["state"] == k) for k in STATES}
    base = len(measured) - states["in_progress"] - states["practice"] - states["unknown"]
    asked = [k for j in measured for k in j["asked"]]
    return {"format": 2, "jobs": len(measured), "states": states,
            "held_read_only": sum(1 for j in measured if j["read_only"]),
            "analysis_only_runs": sum(j["analysis_only_runs"] for j in measured),
            "cancel_ratio": round(states["cancelled"] / base, 3) if base > 0 else None,
            "pr_minutes": _dist([j["pr_min"] for j in measured if j["state"] == "pr" and j["pr_min"] is not None]),
            "pr_unmeasured": sum(1 for j in measured if j["state"] == "pr" and j["pr_min"] is None),
            "analysis_minutes": _dist([j["analysis_min"] for j in measured if j["analysis_min"] is not None]),
            "questions": {"jobs": len(measured), "total": len(asked),
                          "per_job": round(len(asked) / len(measured), 2) if measured else None,
                          "by_kind": {k: asked.count(k) for k in sorted(set(asked))}},
            "retries": {k: sum(j[k] for j in measured) for k in ("runs", "answer_reruns", "errors", "stages", "stage_failed")},
            "legacy": {"jobs": len(legacy), "stages": {s: sum(1 for j in legacy if j["stage"] == s)
                                                       for s in sorted({j["stage"] for j in legacy})}},
            "other_flows": sum(1 for j in jobs if j["kind"] == "other"), "tokens": None}


# -- --transcripts: 질문·재시도·단계별 토큰 --------------------------------------------------------------------------
# 대상 = Claude Code transcript 줄(`sessionId`, 평문 JSONL). stream-json(`session_id`)·표시 기록 줄은 sessionId가 없어 빠진다.
# 내용·명령·경로·세션 ID는 내지 않는다: usage 숫자와 표식이 맞았는지만 센다.

# 플러그인 스크립트 경로 모양만: `…/scripts/<이름>.py` 또는 스킬이 쓰는 변수 경로 `$S/<이름>.py`(`S=<plugin>/scripts`) —
# 다른 프로젝트의 `config.py` 같은 맨 이름은 세지 않는다
PLUGIN_CALL = re.compile(r"(?:scripts[/\\]|\$\{?\w+\}?[/\\])(?:triage|db_pr|db_verify|db_add|config|issue_post|parse_logcat|"
                         r"code_roots|db_search|mask_pii|job_status)\.py\b")
CODE_EXT = (".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp", ".aidl", ".hal")
STEP_KEYS = ("basic", "code", "deep", "explore", "new_cause", "write", "post", "other", "retry", "subagent")
USAGE_KEYS = (("input", "input_tokens"), ("output", "output_tokens"), ("cache_read", "cache_read_input_tokens"),
              ("cache_write", "cache_creation_input_tokens"))
EXIT_RE = re.compile(r"Exit code (\d+)")
_ARG = r"[^\n;&|]*"     # 같은 명령 안(줄·;·&·| 전)


def _bash_marker(cmd: str) -> str | None:
    for key, pattern in (("explore", rf"\btriage\.py\b{_ARG}\bexplore\b"), ("basic", rf"\btriage\.py\b{_ARG}\brun\b"),
                         ("new_cause", rf"\bdb_verify\.py\b{_ARG}\brules\b{_ARG}--draft|\bparse_logcat\.py\b{_ARG}\bcut\b|"
                                       rf"\bdb_add\.py\b{_ARG}\bsimilar\b"),
                         ("write", rf"\bdb_pr\.py\b{_ARG}\b(?:preflight|stage|summary|publish|discard|merge|find-plan)\b"),
                         ("post", r"\bissue_post\.py\b")):
        if re.search(pattern, cmd):
            return key
    return None


def _skill(tool: dict) -> str:
    return str(tool["input"].get("skill") or "") if tool["name"] == "Skill" else ""


def _marker(tool: dict, cur: str | None) -> str | None:
    """도구 호출 하나가 정하는 다음 단계(없으면 None). ponytail: 명령 모양·경로 끝으로 가르는 근사(heredoc 글 속 명령도 걸린다)."""
    name, inp = tool["name"], tool["input"]
    if name == "Bash":
        return _bash_marker(str(inp.get("command") or ""))
    if name == "Skill":
        return None if _skill(tool).startswith("telephony-triage") else "deep"
    paths = [str(inp.get(k) or "").replace("\\", "/") for k in ("file_path", "path", "glob", "pattern")]
    if name == "Read" and paths[0].endswith("reference/db-authoring.md"):
        return "new_cause"
    if name in ("Write", "Edit"):
        return "new_cause" if "/draft/" in paths[0] else "write" if paths[0].endswith("plan.json") else None
    if cur in ("basic", "code") and name in ("Read", "Grep", "Glob"):
        return "code" if any(p.lower().rstrip("*}").endswith(CODE_EXT) for p in paths) else "basic"
    return None


def _failed(tool: dict) -> str | None:
    """실패 신호: show_guard 거부 → deny, 플러그인 스크립트 종료 1·2(3 제외) → script."""
    if shown.denied(tool):
        return "deny"
    m = EXIT_RE.search(tool["result"])
    if tool["name"] == "Bash" and tool["error"] and m and m.group(1) in ("1", "2") \
            and PLUGIN_CALL.search(str(tool["input"].get("command") or "")):
        return "script"
    return None


RESULT_MAX = 4096        # tool_result 글은 앞부분만 둔다(종료 코드·show_guard 표식은 앞에 있다)
INPUT_KEYS = ("command", "skill", "file_path", "path", "glob", "pattern")


def _text(body) -> str:
    if isinstance(body, list):
        return "\n".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
    return str(body or "")


def _usage(u) -> dict | None:
    """usage 네 필드(음이 아닌 정수). 형식이 다르면(문자열·inf·음수·소수) None — usage 없음으로 센다."""
    if not isinstance(u, dict):
        return None
    out = {}
    for k, f in USAGE_KEYS:
        v = u.get(f) or 0
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or v != int(v):
            return None
        out[k] = int(v)
    return out


def _slim(ev: dict) -> dict | None:
    """transcript 줄 하나에서 집계에 쓰는 것만(대화 글은 버린다). id는 글자로 바꾼다(목록·객체여도 안 깨진다)."""
    msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
    content = msg.get("content")
    items = [c for c in content if isinstance(c, dict)] if isinstance(content, list) else []
    if ev.get("type") == "assistant":
        tools = []
        for c in items:
            if c.get("type") == "tool_use":
                inp = c.get("input") if isinstance(c.get("input"), dict) else {}
                tools.append({"id": str(c.get("id")), "name": str(c.get("name") or ""),
                              "input": {k: str(inp[k]) for k in INPUT_KEYS if inp.get(k) is not None}})
        rid = msg.get("id") or ev.get("uuid")
        return {"type": "assistant", "id": None if rid is None else str(rid), "model": str(msg.get("model") or "?"),
                "usage": _usage(msg.get("usage")), "tools": tools}
    if ev.get("type") == "user":
        stop = isinstance(content, str) and content.lstrip().startswith("Stop hook feedback") and shown.MARKER in content
        results = [(str(c.get("tool_use_id")), _text(c.get("content"))[:RESULT_MAX], bool(c.get("is_error")))
                   for c in items if c.get("type") == "tool_result"]
        return {"type": "user", "stop": stop, "results": results} if stop or results else None
    return None


def _read(path: Path, sub: bool, groups: dict, out: dict) -> None:
    """transcript 파일 하나의 줄을 sessionId별로 줄여 담는다. 깨진 줄·sessionId 없는 줄(stream-json 등)은 건너뛰고,
    모양이 바뀌어 줄이지 못한 줄은 `unreadable_lines`로 센다."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                if not (isinstance(ev, dict) and isinstance(ev.get("sessionId"), str)):
                    continue
                side = sub or bool(ev.get("isSidechain"))
                g = groups.setdefault(ev["sessionId"], {"main": [], "sub": [], "version": None})
                if not side and g["version"] is None and ev.get("version"):
                    g["version"] = str(ev["version"])
                try:
                    slim = _slim(ev)
                except (TypeError, ValueError, AttributeError):
                    out["unreadable_lines"] += 1
                    continue
                if slim:
                    g["sub" if side else "main"].append(slim)
    except OSError:
        out["unreadable_lines"] += 1


def _sessions(root: Path, out: dict):
    """세션 파일(`subagents/` 밖의 `*.jsonl`)마다 그 파일과 `<이름>/subagents/*.jsonl`을 읽어 {sessionId: 묶음}을 하나씩 낸다 —
    한 번에 파일 하나만 메모리에 둔다. ponytail: 세션 파일 없이 남은 subagents 파일은 세지 않는다."""
    for path in sorted(root.rglob("*.jsonl")):
        if "subagents" in path.relative_to(root).parts:
            continue
        groups: dict = {}
        _read(path, False, groups, out)
        for agent in sorted((path.parent / path.stem / "subagents").glob("*.jsonl")):
            _read(agent, True, groups, out)
        yield from groups.values()


def _responses(lines: list) -> list:
    """줄인 assistant 줄을 message.id로 묶은 응답(처음 나온 순서, usage는 필드별 최댓값 — 한 응답이 여러 줄)과 Stop 되돌림 표시."""
    order, by_id, tools = [], {}, {}
    for s in lines:
        if s["type"] == "assistant":
            rid = s["id"] or f"#{len(order)}"
            r = by_id.get(rid)
            if r is None:
                r = by_id[rid] = {"usage": None, "model": s["model"], "tools": []}
                order.append(r)
            if s["usage"] is not None:
                r["usage"] = {k: max(v, (r["usage"] or {}).get(k, 0)) for k, v in s["usage"].items()}
            for raw in s["tools"]:
                t = {"kind": "tool", "name": raw["name"], "input": raw["input"], "result": "", "error": False}
                r["tools"].append(t)
                tools[raw["id"]] = t
        else:
            if s["stop"]:
                order.append({"stop": True})        # 표시 보조 hook의 Stop 되돌림
            for tid, text, err in s["results"]:
                if tid in tools:
                    tools[tid].update(result=text, error=err)
    return order


def transcripts(root: Path) -> dict:
    """`root`(Claude Code projects 폴더) 아래 플러그인 세션의 단계별 토큰·대화 질문·재시도 신호 수. 오프라인·읽기 전용.
    단계: 응답은 현재 단계에 넣고 그 응답의 도구 호출이 다음 단계를 정한다(첫 표식 전 응답은 첫 표식 단계, 표식이 없으면
    other). 실패 신호(플러그인 스크립트 종료 1·2, show_guard 거부, Stop 되돌림) 뒤 ~ 도구를 부르는 다음 응답까지는 retry."""
    zero = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    out = {"dir": str(root), "sessions": 0, "analyze_sessions": 0, "by_stage": {k: dict(zero) for k in STEP_KEYS},
           "total": None, "asks": 0, "deep_calls": 0, "show_guard": {"stop": 0, "deny": 0}, "script_errors": 0,
           "models": {}, "versions": {}, "usage_missing": 0, "unreadable_lines": 0}
    total = dict(zero)

    def add(stage: str, r: dict) -> None:
        model = str(r.get("model") or "?")
        out["models"][model] = out["models"].get(model, 0) + 1
        if r["usage"] is None:
            out["usage_missing"] += 1
            return
        out["by_stage"][stage]["calls"] += 1
        for k, _ in USAGE_KEYS:
            out["by_stage"][stage][k] += r["usage"][k]

    for sess in (_sessions(root, out) if root.is_dir() else ()):
        main = _responses(sess["main"])
        calls = [t for r in main for t in r.get("tools", ())]
        if not any(PLUGIN_CALL.search(str(t["input"].get("command") or "")) if t["name"] == "Bash"
                   else _skill(t).startswith("telephony-triage") for t in calls):
            continue
        sub = _responses(sess["sub"])
        out["sessions"] += 1
        version = sess["version"] or "?"
        out["versions"][version] = out["versions"].get(version, 0) + 1
        out["analyze_sessions"] += any(t["name"] == "Bash" and _bash_marker(str(t["input"].get("command") or "")) == "basic"
                                       for t in calls)
        for r in main + sub:        # 자체 검사용 합계(단계 나누기와 따로 센다)
            if not r.get("stop") and r["usage"] is not None:
                total["calls"] += 1
                for k, _ in USAGE_KEYS:
                    total[k] += r["usage"][k]
        cur, pending, retry = None, [], False
        for r in main:
            if r.get("stop"):
                out["show_guard"]["stop"] += 1
                retry = True
                continue
            if retry:
                add("retry", r)
            elif cur is None:
                pending.append(r)
            else:
                add(cur, r)
            nxt = None
            for t in r["tools"]:
                if shown.is_ask(t["name"]) and not shown.denied(t) \
                        and not (t["error"] and any(x in t["result"] for x in shown.ASK_REJECTED)):
                    out["asks"] += 1
                out["deep_calls"] += t["name"] == "Skill" and not _skill(t).startswith("telephony-triage")
                nxt = _marker(t, nxt or cur) or nxt
                fail = _failed(t)
                if fail == "deny":
                    out["show_guard"]["deny"] += 1
                elif fail == "script":
                    out["script_errors"] += 1
            if r["tools"]:
                retry = any(_failed(t) for t in r["tools"])
                if cur == "code" and nxt is None:       # 코드가 아닌 도구 응답이면 basic으로 돌아간다
                    nxt = "basic"
            if nxt and cur is None:
                for p in pending:
                    add(nxt, p)
                pending = []
            cur = nxt or cur
        for p in pending:
            add("other", p)
        for r in sub:
            if not r.get("stop"):
                add("subagent", r)
    staged = {k: sum(v[k] for v in out["by_stage"].values()) for k in zero}
    if staged != total:
        print(f"[telephony-triage] transcript 집계 자체 검사 불일치: 단계 합 {staged} ≠ 전체 {total}", file=sys.stderr)
    if total["calls"]:
        out["total"] = total
    return out


def report_lines(s: dict) -> list[str]:
    """텍스트 8줄(집계 대상 줄 뒤). "취소 비율" 낱말은 site_checks PILOT_FIELDS가 본다."""
    def dist(d: dict) -> str:
        return "n/a (0건)" if not d["n"] else f"중앙값 {d['median']}분 · 평균 {d['mean']}분 ({d['n']}건)"

    st, q, r = s["states"], s["questions"], s["retries"]
    base = s["jobs"] - st["in_progress"] - st["practice"] - st["unknown"]
    ratio = "n/a" if s["cancel_ratio"] is None else f"{st['cancelled']}/{base} ({s['cancel_ratio']:.0%})"
    kinds = ", ".join(f"{k} {n}" for k, n in q["by_kind"].items()) or "없음"
    per_job = "n/a" if q["per_job"] is None else q["per_job"]
    return [f"작업 {s['jobs']}건 측정 · 업데이트 전 기록(legacy) {s['legacy']['jobs']}건 · 다른 흐름 {s['other_flows']}건",
            f"상태: PR {st['pr']} · push만 {st['pushed']} · 진행 중 {st['in_progress']} · 연습 {st['practice']} · 취소 "
            f"{st['cancelled']} · 보류 {st['held']}(읽기 전용 {s['held_read_only']}) · 분석만 {st['analysis_only']}"
            f"(--analysis-only 실행 {s['analysis_only_runs']}) · 결과 없음 {st['no_result']} · 손상 {st['unknown']}",
            f"취소 비율 {ratio} (분모: 측정 작업 − 진행 중·연습·손상)",
            f"PR까지(첫 analyze → PR 생성, 경과 시간·보류 포함) {dist(s['pr_minutes'])} · 측정 불가 {s['pr_unmeasured']}건",
            f"분석까지(첫 analyze → 분석 완료) {dist(s['analysis_minutes'])}",
            f"드라이버 질문(issue 제외) 작업당 {per_job}개 (총 {q['total']}개: {kinds})",
            f"재시도: analyze 실행 {r['runs']}(질문 답 재실행 {r['answer_reruns']} 따로) · 오류 {r['errors']} · stage "
            f"{r['stages']}(실패 {r['stage_failed']})",
            _token_line(s["tokens"])]


def _token_line(t: dict | None) -> str:
    if t is None:
        return "토큰: 미측정 (--transcripts 없음)"
    if t["total"] is None:
        return f"토큰: 미측정 (transcript 대상 세션 {t['sessions']}, usage 없는 응답 {t['usage_missing']})"
    tot = t["total"]
    stages = " · ".join(f"{k} {sum(v[f] for f in ('input', 'output', 'cache_read', 'cache_write'))}"
                        for k, v in t["by_stage"].items() if v["calls"])
    return (f"토큰(transcript, 세션 {t['sessions']}·analyze {t['analyze_sessions']}): 입력 {tot['input']} · 출력 {tot['output']} · "
            f"캐시 읽기 {tot['cache_read']} · 캐시 쓰기 {tot['cache_write']} (응답 {tot['calls']}) — 단계별 {stages} — 대화 질문 "
            f"{t['asks']} · 심층 {t['deep_calls']} · 되돌림 {t['show_guard']['stop']}·거부 {t['show_guard']['deny']} · "
            f"스크립트 오류 {t['script_errors']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="usage_stats.py", description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--work-dir", help="기본: 선택 플랫폼의 사용자 config work_dir")
    platform_session.add_arg(target)
    parser.add_argument("--json", action="store_true", help="집계 대상과 수치를 JSON 한 줄로(개수·시간만, 내용 없음)")
    parser.add_argument("--transcripts", nargs="?", const="", default=None, metavar="dir",
                        help="Claude Code transcript의 단계별 토큰·대화 질문·재시도 신호도 센다(opt-in, 숫자만). "
                             "기본 $CLAUDE_CONFIG_DIR/projects 또는 ~/.claude/projects")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")    # 콘솔이 아닌 stdout(파이프)도 cp949가 아니게
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    name = None
    try:
        if args.work_dir:
            work_dir = Path(args.work_dir).expanduser()
            target = f"work_dir {work_dir} (--work-dir 지정)"
        else:
            defaults = site_defaults.load_or_exit(args.plugin_root)
            name, cfg = platform_session.resolve(defaults, args.platform)
            work_dir = Path(userconfig.get(cfg, "work_dir")).expanduser()
            target = f"플랫폼 {name} · work_dir {work_dir}"
    except platforms.PlatformConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:   # 손상된 config는 환경 오류(2)
        print(f"config를 읽지 못했다: {exc}", file=sys.stderr)
        return 2
    if not work_dir.is_dir():
        print(f"work_dir가 없다: {work_dir}", file=sys.stderr)
        return 2
    s = stats(work_dir)
    if args.transcripts is not None:
        root = Path(args.transcripts).expanduser() if args.transcripts else \
            Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser() / "projects"
        s["tokens"] = transcripts(root)
    if args.json:
        print(json.dumps({"format": 2, "platform": name, "work_dir": str(work_dir), **s}, ensure_ascii=False))
        return 0
    print(f"집계 대상: {target}")
    for line in report_lines(s):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
