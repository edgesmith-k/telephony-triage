#!/usr/bin/env python3
"""조사 모드(11/25 A635) 비교 eval 틀 — 기록된 출력을 채점만 한다(모델을 돌리지 않는다, 비용 0).

    python3 tools/investigate_eval.py <cases 디렉토리> [--arms before,after] [--json]

case 하나 = 디렉토리 하나:
- `case.json`: `{"reason": "후보 없음"|"1위 C=0", "layer": <정답 책임 층>, "cause_line": <원인 줄의 고정 조각>, "synthetic": bool}`
- `<arm>/explore-output.md`: 그 arm에서 모델이 쓴 탐색 출력(마스킹된 것), `<arm>/analysis.json`: 그 뒤 analysis.json(조사 모드
  check-output이 쓴 `investigation`이 있으면 그것 — 변경 전 arm은 보통 없다).

arm마다 센다(분모 = case 수):
- `layer_correct`: 가장 유력(없으면 가설 1)의 `책임 경계`가 정답 층 — 모델의 층 판단
- `cause_cited`: 그 가설의 `로그로 확인`·기대 체인 관측 인용에 원인 줄 조각이 있음 — 원인 줄 인용률
- `identified`·`identified_correct`(통과했고 층도 정답)·`identified_wrong`(통과했는데 층이 틀림 — 잘못된 확정)·`insufficient`
  (`investigation`이 없거나 근거 부족 — 결론 보류)
사외는 합성 case 2~3개로 틀만 시험한다(`tests/fixtures/investigate-eval/`). 사내는 실제 5~10건(마스킹, SITE_PATHS)으로 돌린다.

종료 코드: 0 채점함, 2 사용 오류(디렉토리·case.json 없음, arm 출력 없음).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugin" / "scripts"))

from common import evidence  # noqa: E402

METRICS = ("layer_correct", "cause_cited", "identified", "identified_correct", "identified_wrong", "insufficient")


def _layer(value) -> str | None:
    from triagelib.output import _layer as layer      # check-output 게이트와 같은 읽기
    return layer(value)


def score_case(case: dict, out_text: str, analysis: dict) -> dict:
    fields = evidence.parse_explore(out_text) or {"hyps": []}
    hyps = fields.get("hyps") or []
    from triagelib.output import _picked
    h = hyps[_picked(fields)] if hyps else {}
    quotes = (h.get("로그로 확인") or []) + (evidence.chain_quotes(h) if h else [])
    inv = analysis.get("investigation") if isinstance(analysis, dict) else None
    identified = isinstance(inv, dict) and inv.get("status") == "identified"
    right = _layer(h.get("책임 경계")) == case["layer"]
    return {"layer_correct": right, "cause_cited": any(case["cause_line"] in q for q in quotes),
            "identified": identified, "identified_correct": identified and inv.get("layer") == case["layer"],
            "identified_wrong": identified and inv.get("layer") != case["layer"], "insufficient": not identified}


def run(cases_dir: Path, arms: list[str]) -> dict:
    cases = sorted(p for p in cases_dir.iterdir() if (p / "case.json").is_file()) if cases_dir.is_dir() else []
    if not cases:
        raise SystemExit(f"case가 없다: {cases_dir}")
    rows, totals = [], {a: dict.fromkeys(METRICS, 0) for a in arms}
    for path in cases:
        case = json.loads((path / "case.json").read_text(encoding="utf-8"))
        row = {"case": path.name, "reason": case.get("reason"), "synthetic": case.get("synthetic")}
        for arm in arms:
            out = path / arm / "explore-output.md"
            if not out.is_file():
                raise SystemExit(f"{path.name}: {arm}/explore-output.md가 없다")
            ana = path / arm / "analysis.json"
            got = score_case(case, out.read_text(encoding="utf-8"),
                             json.loads(ana.read_text(encoding="utf-8")) if ana.is_file() else {})
            row[arm] = got
            for k in METRICS:
                totals[arm][k] += bool(got[k])
        rows.append(row)
    n = len(rows)
    return {"n": n, "arms": {a: {**{k: f"{v}/{n}" for k, v in t.items()}, "rate": {k: round(v / n, 3) for k, v in t.items()}}
                             for a, t in totals.items()}, "cases": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="조사 모드 비교 eval(기록된 출력 채점만)")
    ap.add_argument("cases", type=Path)
    ap.add_argument("--arms", default="before,after")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        res = run(args.cases, [a for a in args.arms.split(",") if a])
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        for arm, t in res["arms"].items():
            print(f"{arm}: " + ", ".join(f"{k} {t[k]}" for k in METRICS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
