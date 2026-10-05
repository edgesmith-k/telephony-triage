#!/usr/bin/env python3
"""실제 플러그인을 불러온 상태의 description 트리거 측정 (10-skill-eval.md "description 트리거 테스트").

skill-creator `run_eval`은 스킬을 임시 커맨드로 넣고 **첫 도구 호출**이 그 스킬일 때만 트리거로 센다.
로그 분석 요청에서 Claude는 먼저 `ls`로 로그를 찾는 일이 많아, 실제로는 스킬을 부르는데도 미트리거로 잡힌다.
이 스크립트는 `claude -p --plugin-dir <plugin>`로 실제 플러그인을 불러오고, 처음 `--within`번의 도구 호출 안에
`Skill`(telephony-triage)이 있으면 트리거로 센다. 질문마다 빈 임시 디렉토리에서 돈다.

    python3 tests/skill_evals/trigger_real.py [--plugin-dir plugin] [--evals tests/skill_evals/trigger_evals.json]
        [--runs 2] [--within 4] [--workers 6] [--model <id>] [--out <결과 JSON>]

질문의 트리거 비율이 0.5 이상이면 트리거로 판정한다. 결과 JSON에 질문별 횟수와 처음 도구 두 개를 남긴다.
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


def run_one(query: str, plugin: Path, within: int, model: str | None, timeout: int) -> tuple[bool, list]:
    work = tempfile.mkdtemp(prefix="tt-trig-")
    cmd = ["claude", "-p", query, "--plugin-dir", str(plugin), "--output-format", "stream-json", "--verbose",
           "--max-turns", str(within)]
    if model:
        cmd += ["--model", model]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}   # 세션 안에서 claude -p 중첩 허용
    try:
        try:
            out = subprocess.run(cmd, cwd=work, env=env, capture_output=True, text=True, timeout=timeout).stdout
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    tools = []
    for line in out.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "assistant":
            continue
        for block in event["message"].get("content") or []:
            if block.get("type") == "tool_use":
                tools.append([block["name"], json.dumps(block.get("input"), ensure_ascii=False)[:100]])
    hit = any(name == "Skill" and SKILL in args for name, args in tools[:within])
    return hit, tools[:2]


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
    rows, tp, fn, fp, tn = [], 0, 0, 0, 0
    for i, q in enumerate(queries):
        hits = sum(hit for hit, _ in results[i])
        triggered = hits / args.runs >= 0.5
        if q["should_trigger"]:
            tp, fn = tp + triggered, fn + (not triggered)
        else:
            fp, tn = fp + triggered, tn + (not triggered)
        rows.append({"query": q["query"], "should_trigger": q["should_trigger"], "hits": hits, "runs": args.runs,
                     "first_tools": [tools for _, tools in results[i]]})
    summary = {"recall": tp / (tp + fn) if tp + fn else None, "precision": tp / (tp + fp) if tp + fp else None,
               "tp": tp, "fn": fn, "fp": fp, "tn": tn, "runs": args.runs, "within": args.within}
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    for row in rows:
        mark = "+" if row["should_trigger"] else "-"
        print(f"{mark} {row['hits']}/{row['runs']}  {row['query']}")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
