#!/usr/bin/env python3
"""파일럿 운영 지표를 work_dir에서 뽑는다 (15-local-draft.md §15.5 S-7, contracts.md §3.2 작업 기록).

작업마다 `JOB/trace.jsonl`의 사건 행(triage `0-key`·`done`·`needs_input`·`error`, db_pr `stage`·`publish`·`discard`)과
파일 상태(`plan.json`·`state.json`·`triage-state.json`·`wt/`·`session.lock`, `common.jobstatus.quick_stage`)로 상태 하나를
고른다(위에서 처음 맞는 것): 손상 unknown → PR pr(`pr.number`) → push만 pushed(`pr.head_sha`) → 진행 중 in_progress(stage·
확인 화면 단계, `wt/`, 이 작업의 만료 전 lock) → 연습 practice(마지막 discard dry-run, 마지막 analyze --dry-run) → 취소
cancelled(마지막 discard cancel이고 그 뒤 analyze 없음) → 보류 held(계획 저장, 읽기 전용 계획은 held_read_only로도) →
분석만 analysis_only(분석 완료·계획 없음) → 결과 없음 no_result.
따로 세는 것: `_`·`.` 폴더와 표식(plan·state·trace·triage-state) 없는 폴더는 빼고, analyze 기록(`0-key`)이 없고 계획 source가
analyze·record가 아니면 other_flows, trace에 v≥2 행이 없으면(업데이트 전 작업) legacy(quick_stage별 건수만, 시간·취소·질문 미측정).
PR까지 = 첫 `0-key` → 첫 `publish{action: created, gh_ok: true}`, 분석까지 = 첫 `0-key` → 첫 `done`(둘 다 경과 시간, 보류 포함).
PR이 있는데 그 두 행이 없으면 pr_unmeasured(record처럼 analyze 없이 시작한 작업). 드라이버 질문 = `needs_input` 행(kind
`issue` 제외), 대화 질문(AskUserQuestion)은 스크립트 신호가 없어 세지 않는다. release(Step 7) 사유는 기록이 없어 파일 상태로만
가른다(분석 뒤 기록하지 않음 = 분석만). `cleanup --yes`로 지운 작업은 빠진다.

CLI:
    python3 <plugin.scripts_path>/usage_stats.py [--work-dir <dir> | --platform <이름>] [--json] [--plugin-root <dir>]
    (`plugin.scripts_path`는 사용자 config — setup·SessionStart가 설치본 scripts 경로로 맞춘다. 읽기 전용)
    (기본: 선택 플랫폼(`--platform` > TT_PLATFORM > 사용자 config platform > site)의 사용자 config work_dir.
    `--work-dir`와 `--platform`은 함께 쓸 수 없다. `--work-dir`면 site-defaults를 읽지 않는다)
    텍스트 9줄(첫 줄 집계 대상). `--json`이면 JSON 한 줄 `{format: 2, platform, work_dir, jobs, states{…}, held_read_only,
    analysis_only_runs, cancel_ratio, pr_minutes{n, median, mean, values}, pr_unmeasured, analysis_minutes{…},
    questions{jobs, total, per_job, by_kind}, retries{runs, errors, stages, stage_failed}, legacy{jobs, stages}, other_flows, tokens}`
    (개수·시간만 — 작업 키·trace 메시지 없음, `--work-dir`면 `platform`은 null, `tokens`는 null).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import platforms  # noqa: E402
from common import jobstatus, session_lock, site_defaults, userconfig  # noqa: E402
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
    try:
        return session_lock.parse(str(row["ts"]))
    except (KeyError, TypeError, ValueError):
        return None


def _minutes(rows: list, end) -> float | None:
    t0, t1 = _ts(next((r for r in rows if r.get("step") == "0-key"), None)), _ts(next((r for r in rows if end(r)), None))
    return (t1 - t0).total_seconds() / 60 if t0 and t1 else None


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
    last = runs[-1] if isinstance(runs, list) and runs and isinstance(runs[-1], dict) else {}
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
    elif gone.get("outcome") == "dry-run" or last.get("dry_run") is True:
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
    return {"kind": "measured", "state": state, "read_only": state == "held" and last.get("mode") == "read-only",
            "analysis_only_runs": sum(1 for r in runs or [] if isinstance(r, dict) and r.get("mode") == "analysis-only"),
            "pr_min": _minutes(rows, lambda r: r.get("step") == "publish" and r.get("action") == "created"
                               and r.get("gh_ok") is True),
            "analysis_min": _minutes(rows, lambda r: r.get("step") == "done"),
            "asked": asked, "runs": len(keys), "errors": sum(1 for r in rows if r.get("step") == "error"),
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
            "pr_minutes": _dist([j["pr_min"] for j in measured if j["pr_min"] is not None]),
            "pr_unmeasured": sum(1 for j in measured if j["state"] == "pr" and j["pr_min"] is None),
            "analysis_minutes": _dist([j["analysis_min"] for j in measured if j["analysis_min"] is not None]),
            "questions": {"jobs": len(measured), "total": len(asked),
                          "per_job": round(len(asked) / len(measured), 2) if measured else None,
                          "by_kind": {k: asked.count(k) for k in sorted(set(asked))}},
            "retries": {k: sum(j[k] for j in measured) for k in ("runs", "errors", "stages", "stage_failed")},
            "legacy": {"jobs": len(legacy), "stages": {s: sum(1 for j in legacy if j["stage"] == s)
                                                       for s in sorted({j["stage"] for j in legacy})}},
            "other_flows": sum(1 for j in jobs if j["kind"] == "other"), "tokens": None}


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
            f"재시도: analyze 실행 {r['runs']} · 오류 {r['errors']} · stage {r['stages']}(실패 {r['stage_failed']})",
            "토큰: 미측정" if s["tokens"] is None else f"토큰: 합계 {json.dumps(s['tokens']['total'], ensure_ascii=False)}"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="usage_stats.py", description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--work-dir", help="기본: 선택 플랫폼의 사용자 config work_dir")
    platform_session.add_arg(target)
    parser.add_argument("--json", action="store_true", help="집계 대상과 수치를 JSON 한 줄로(개수·시간만, 내용 없음)")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
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
    if args.json:
        print(json.dumps({"format": 2, "platform": name, "work_dir": str(work_dir), **s}, ensure_ascii=False))
        return 0
    print(f"집계 대상: {target}")
    for line in report_lines(s):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
