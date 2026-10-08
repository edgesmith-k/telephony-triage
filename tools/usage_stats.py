#!/usr/bin/env python3
"""파일럿 지표 3개를 work_dir에서 뽑는다 (15-local-draft.md §15.5 S-7).

PR까지 걸린 평균 시간, 중도 취소 비율, 작업당 저장된 답 수(질문 수 근사)를 줄 글로 낸다.
PR 완료는 `plan.json`의 `pr.number`가 있을 때만 세고, push 기록 있음·PR 연결 미확인(`pr.head_sha`만 있음)은 따로 센다.

CLI:
    python3 tools/usage_stats.py [--work-dir <dir>]    (기본: 사용자 config의 work_dir)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "scripts"))
from common import session_lock, userconfig  # noqa: E402


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def stats(work_dir: Path) -> dict:
    pr_secs, questions, started, cancelled, pushed = [], [], 0, 0, 0
    for job in sorted(p for p in work_dir.iterdir() if p.is_dir() and p.name != session_lock.SNAPSHOT_DIR):
        answers = _json(job / "triage-state.json").get("answers")
        if isinstance(answers, dict):
            questions.append(len([k for k in answers if k != "anchor"]))
        plan = _json(job / "plan.json")
        if not plan.get("started_at"):
            continue
        started += 1
        pr = plan.get("pr") or {}
        if pr.get("number"):
            # ponytail: mtime≈마지막 쓰기(재승인·sync-pr마다 갱신), 정확히 하려면 gh createdAt
            t0 = session_lock.parse(plan["started_at"])
            end = datetime.fromtimestamp((job / "plan.json").stat().st_mtime, t0.tzinfo)
            pr_secs.append((end - t0).total_seconds())
        elif pr.get("head_sha"):
            pushed += 1          # push 기록 있음·PR 연결 미확인 (gh 실패 또는 URL에서 번호를 못 뽑음, publish.py:505-516)
        elif not (job / "state.json").exists() and not (job / "wt").exists():
            cancelled += 1
    return {"pr_minutes": sum(pr_secs) / len(pr_secs) / 60 if pr_secs else None, "pr_jobs": len(pr_secs),
            "pushed_no_pr": pushed, "cancelled": cancelled, "started": started,
            "questions": sum(questions) / len(questions) if questions else None, "q_jobs": len(questions)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="usage_stats.py", description=__doc__)
    parser.add_argument("--work-dir", help="기본: 사용자 config의 work_dir")
    args = parser.parse_args(argv)
    try:
        work_dir = Path(args.work_dir or userconfig.get(userconfig.load_user() or {}, "work_dir")
                        or userconfig.builtin()["work_dir"]).expanduser()
    except Exception as exc:   # 손상된 config는 환경 오류(2)
        print(f"config를 읽지 못했다: {exc}", file=sys.stderr)
        return 2
    if not work_dir.is_dir():
        print(f"work_dir가 없다: {work_dir}", file=sys.stderr)
        return 2
    s = stats(work_dir)

    def num(v, unit):
        return "n/a" if v is None else f"{v:.1f}{unit}"

    print(f"PR까지 평균 {num(s['pr_minutes'], '분')} (PR 작업 {s['pr_jobs']}건)")
    print(f"push 기록 있음·PR 연결 미확인 {s['pushed_no_pr']}건")
    ratio = f" ({s['cancelled'] / s['started']:.0%})" if s["started"] else ""
    print(f"중도 취소 {s['cancelled']}/{s['started']}{ratio}")
    print(f"작업당 평균 저장된 답 수(질문 수 근사) {num(s['questions'], '개')} (작업 {s['q_jobs']}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
