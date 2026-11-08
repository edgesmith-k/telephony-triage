#!/usr/bin/env python3
"""실제 플러그인을 불러온 상태의 description 트리거 측정 (10-skill-eval.md "description 트리거 테스트").

skill-creator `run_eval`은 스킬을 임시 커맨드로 넣고 **첫 도구 호출**이 그 스킬일 때만 트리거로 센다.
로그 분석 요청에서 Claude는 먼저 `ls`로 로그를 찾는 일이 많아, 실제로는 스킬을 부르는데도 미트리거로 잡힌다.
이 스크립트는 `claude -p --plugin-dir <plugin>`로 실제 플러그인을 불러오고, 처음 `--within`번의 도구 호출 안에
`Skill`(telephony-triage)이 있으면 트리거로 센다. 질문마다 빈 임시 디렉토리에서 돈다.

    python3 tests/skill_evals/trigger_real.py [--plugin-dir plugin] [--evals tests/skill_evals/trigger_evals.json]
        [--runs 2] [--within 4] [--workers 6] [--model <id>] [--out <결과 JSON>]

질문의 트리거 비율이 0.5 이상이면 트리거로 판정한다. 결과 JSON에 질문별 횟수와 처음 도구 두 개를 남긴다.
Skill 호출이 안 보인 실행 중 claude 실행 실패(시간 초과·실행 불가·비정상 종료·`result` 이벤트 없음·`is_error`)는
"트리거 없음"이 아니라 오류(미실행)로 따로 센다. `--max-turns`에 닿아 멈춘 `error_max_turns`는 정상 종료(트리거 없음)이고,
그 횟수는 정보로만 summary·행 `max_turns`와 표의 트리거 없음 옆 괄호에 보인다(판정은 그대로 음성).
오류가 한 번이라도 난 질문은 판정하지 않는다(tp·fn·fp·tn 어디에도 넣지 않고 summary `error`에 센다) — 실패를 음성으로 세지 않는다.
Claude API를 쓴다(질문 수 × runs 회). pytest가 모으지 않는다(이름이 `test_*`가 아니다).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILL = "telephony-triage"


def run_one(query: str, plugin: Path, within: int, model: str | None, timeout: int) -> tuple[str, list]:
    """한 번 실행해 `(status, 처음 도구 두 개)`. status: yes(Skill 호출 봄)·no(정상 종료, 호출 없음)·error(미실행)."""
    work = tempfile.mkdtemp(prefix="tt-trig-")
    cmd = ["claude", "-p", query, "--plugin-dir", str(plugin), "--output-format", "stream-json", "--verbose",
           "--max-turns", str(within)]
    if model:
        cmd += ["--model", model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}   # 세션 안에서 claude -p 중첩 허용
    returncode = None   # None = 끝까지 돌지 못함(시간 초과)
    try:
        try:
            proc = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=timeout)
            out, returncode = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        except OSError as exc:
            return "error", [["claude 실행 불가", str(exc)[:100]]]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    tools, result = [], None
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            result = event
        if event.get("type") != "assistant":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                tools.append([block["name"], json.dumps(block.get("input"), ensure_ascii=False)[:100]])
    if any(name == "Skill" and SKILL in args for name, args in tools[:within]):
        return "yes", tools[:2]   # 부른 것을 본 기록은 그 뒤 실패해도 트리거다
    # 호출 없음은 끝까지 돈 실행에서만 음성이다. --max-turns에 닿아 멈춘 것(error_max_turns)은 정상 종료로 본다
    if returncode is None:
        return "error", [["오류", "시간 초과"], *tools[:2]]
    if result is None:
        return "error", [["오류", f"종료 {returncode}, result 이벤트 없음"], *tools[:2]]
    if result.get("subtype") != "error_max_turns" and (returncode != 0 or result.get("is_error")):
        return "error", [["오류", f"종료 {returncode}, result {result.get('subtype')}"], *tools[:2]]
    return ("max_turns" if result.get("subtype") == "error_max_turns" else "no"), tools[:2]   # max_turns도 음성


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plugin-dir", default=str(REPO / "plugin"))
    ap.add_argument("--evals", default=str(HERE / "trigger_evals.json"))
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--within", type=int, default=4, help="이 횟수 안의 도구 호출에서 Skill을 찾는다")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--timeout", type=int, default=240)
    ap.add_argument("--model")
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    if shutil.which("claude") is None:
        print("claude CLI가 PATH에 없습니다.", file=sys.stderr)
        return 2
    queries = json.loads(Path(args.evals).read_text(encoding="utf-8"))
    plugin = Path(args.plugin_dir).resolve()
    results: dict[int, list] = {}
    with cf.ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(run_one, q["query"], plugin, args.within, args.model, args.timeout): i
                   for i, q in enumerate(queries) for _ in range(args.runs)}
        for future in cf.as_completed(futures):
            results.setdefault(futures[future], []).append(future.result())
    rows, tp, fn, fp, tn, error, max_turns = [], 0, 0, 0, 0, 0, 0
    for i, q in enumerate(queries):
        hits = sum(status == "yes" for status, _ in results[i])
        errors = sum(status == "error" for status, _ in results[i])
        turns = sum(status == "max_turns" for status, _ in results[i])
        max_turns += turns
        triggered = hits / args.runs >= 0.5
        if errors:
            error += 1
        elif q["should_trigger"]:
            tp, fn = tp + triggered, fn + (not triggered)
        else:
            fp, tn = fp + triggered, tn + (not triggered)
        rows.append({"query": q["query"], "should_trigger": q["should_trigger"], "hits": hits, "errors": errors,
                     "max_turns": turns, "runs": args.runs, "first_tools": [tools for _, tools in results[i]]})
    summary = {"recall": tp / (tp + fn) if tp + fn else None, "precision": tp / (tp + fp) if tp + fp else None,
               "tp": tp, "fn": fn, "fp": fp, "tn": tn, "error": error, "max_turns": max_turns,
               "runs": args.runs, "within": args.within}
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    print("기대 트리거/실행 트리거 없음(max_turns 도달) 오류(미실행) 질문")   # 오류가 하나라도 있는 질문은 판정에서 뺀다(summary error)
    for row in rows:
        mark = "+" if row["should_trigger"] else "-"
        no = row["runs"] - row["hits"] - row["errors"]
        turns = f" (max_turns {row['max_turns']})" if row["max_turns"] else ""
        print(f"{mark} {row['hits']}/{row['runs']}  {no}{turns}  {row['errors']}  {row['query']}")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
