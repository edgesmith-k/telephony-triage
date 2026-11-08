#!/usr/bin/env python3
"""팀 운영 지표 표 — 팀원마다 뽑은 `usage_stats.py --json`(`format: 2`) 파일을 모아 한 표로 (15-local-draft.md §15.5 S-7).

    python3 tools/team_stats.py <user-a.json> <user-b.json> ... [--json]

입력 파일 하나 = 사용자 한 명(라벨은 파일 이름의 stem — 파일 안에 이름·세션 ID는 없다). 집계는 개수·시간·비율뿐이고 작업 키·
내용은 들어 있지 않다(`usage_stats`가 내지 않는다). `format`이 2가 아닌 파일은 건너뛰고 `skipped`에 적는다.

표 열: 작업(측정 대상 jobs) · PR(states.pr) · 분석만(states.analysis_only) · 취소율(취소 / (작업 − 진행 중 − 연습 − 손상), usage_stats와 같은
정의) · PR까지 중앙값(분) · 스크립트 분석까지 중앙값(분)(`analysis_minutes` — 드라이버 done까지, 탐색·심층 분석·사용자 확인 제외) ·
질문/작업(questions.per_job) · 재시도(retries.runs) · 토큰(tokens.total의 입력+출력+
캐시 읽기+캐시 쓰기 — 응답 수 calls는 더하지 않는다, 미측정(`tokens` 또는 `total`이 null)이면 -).
합계 행: 작업·PR·분석만·재시도·토큰은 합, 취소율은 취소 건수 합 / 분모 합(반올림된 개인 비율을 가중하지 않는다 — 코덱스 리뷰 N2),
질문/작업은 전체 가중, 중앙값은 모든 사용자의 `values`를 합쳐 다시 센다. 토큰 합은 네 종류를 모두 더한 수이지 금전 비용이 아니다
(캐시 읽기는 단가가 다르다). JSON에는 네 종류를 따로 둔다(`tokens_detail`).

종료 코드: 0 = 표를 냈다(사용자 1명 이상), 1 = 읽을 수 있는 파일 없음, 2 = 사용 오류. 모델·네트워크 호출 없음.
이 표는 기준선(도입 전 사람 분석 시간)과 사후 오분류율을 담지 않는다 — 파일럿 보고에는 그 둘을 따로 적는다(종합 리뷰 C).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

FORMAT = 2
COLUMNS = ("사용자", "작업", "PR", "분석만", "취소율", "PR까지 중앙값(분)", "스크립트 분석까지 중앙값(분)", "질문/작업", "재시도", "토큰")


def _num(value) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _values(block) -> list[float]:
    vals = (block or {}).get("values") if isinstance(block, dict) else None
    return [v for v in (vals or []) if _num(v) is not None]


TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write")


def _tokens(block) -> dict | None:
    """생산자 `tokens.total`({calls, input, output, cache_read, cache_write})에서 네 토큰 종류(음이 아닌 수)만. `tokens`가 null(미측정)·
    `total`이 null(대상 세션·usage 없음)·숫자가 아니면 None — 미측정은 0과 다르다(코덱스 리뷰 N1: 전에는 total을 숫자로 기대해 실제
    생산자 출력이 늘 미측정으로 읽혔다)."""
    total = block.get("total") if isinstance(block, dict) else None
    if not isinstance(total, dict):
        return None
    out = {}
    for k in TOKEN_FIELDS:
        v = _num(total.get(k))
        if v is None or v < 0:
            return None
        out[k] = int(v)
    return out


def _cancel(doc: dict, states: dict) -> tuple[int | None, int | None]:
    """(취소 건수, 분모) — usage_stats와 같은 정의: 분모 = jobs − in_progress − practice − unknown. 네 상태 가운데 하나라도 없으면
    (옛 형식) 둘 다 None(팀 비율에서 제외)."""
    jobs = _num(doc.get("jobs"))
    parts = [_num(states.get(k)) for k in ("cancelled", "in_progress", "practice", "unknown")]
    if jobs is None or any(v is None for v in parts):
        return None, None
    cancelled, in_progress, practice, unknown = (int(v) for v in parts)
    return cancelled, max(int(jobs) - in_progress - practice - unknown, 0)


def read_one(path: Path) -> tuple[dict | None, str | None]:
    """파일 하나 → (사용자 행, 건너뛴 사유)."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name}: 읽을 수 없음 ({type(exc).__name__})"
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        return None, f"{path.name}: usage_stats --json(format {FORMAT}) 출력이 아님"
    return read_one_doc(doc, path.stem), None


def read_one_doc(doc: dict, user: str) -> dict:
    """usage_stats --json 문서 하나 → 사용자 행."""
    states = doc.get("states") if isinstance(doc.get("states"), dict) else {}
    questions = doc.get("questions") if isinstance(doc.get("questions"), dict) else {}
    retries = doc.get("retries") if isinstance(doc.get("retries"), dict) else {}
    tokens = _tokens(doc.get("tokens"))
    cancelled, cancel_base = _cancel(doc, states)
    row = {
        "user": user,
        "platform": doc.get("platform"),
        "jobs": int(_num(doc.get("jobs")) or 0),
        "pr": int(_num(states.get("pr")) or 0),
        "analysis_only": int(_num(states.get("analysis_only")) or 0),
        "cancelled": cancelled, "cancel_base": cancel_base,
        "cancel_ratio": _ratio(cancelled, cancel_base) if cancelled is not None else _num(doc.get("cancel_ratio")),
        "pr_minutes": _values(doc.get("pr_minutes")),
        "analysis_minutes": _values(doc.get("analysis_minutes")),
        "question_jobs": int(_num(questions.get("jobs")) or 0),
        "question_total": int(_num(questions.get("total")) or 0),
        "retries": int(_num(retries.get("runs")) or 0),
        "tokens": sum(tokens.values()) if tokens else None,
        "tokens_detail": tokens,
    }
    return row


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 3) if den else None


def summarize(rows: list[dict]) -> dict:
    pooled_pr = [v for r in rows for v in r["pr_minutes"]]
    pooled_an = [v for r in rows for v in r["analysis_minutes"]]
    jobs = sum(r["jobs"] for r in rows)
    # 취소율 = 취소 건수 합 / 같은 정의의 분모 합(usage_stats: 작업 − 진행 중 − 연습 − 손상). 건수가 없는 옛 형식 파일은 제외
    with_cancel = [r for r in rows if r.get("cancelled") is not None and r.get("cancel_base") is not None]
    cancelled, cancel_base = sum(r["cancelled"] for r in with_cancel), sum(r["cancel_base"] for r in with_cancel)
    q_jobs = sum(r["question_jobs"] for r in rows)
    with_tokens = [r for r in rows if r.get("tokens_detail") is not None]
    detail = {k: sum(r["tokens_detail"][k] for r in with_tokens) for k in TOKEN_FIELDS} if with_tokens else None
    return {
        "users": len(rows), "jobs": jobs, "pr": sum(r["pr"] for r in rows),
        "analysis_only": sum(r["analysis_only"] for r in rows),
        "cancel_ratio": _ratio(cancelled, cancel_base), "cancelled": cancelled, "cancel_base": cancel_base,
        "cancel_users": len(with_cancel),
        "pr_median": _median(pooled_pr), "pr_n": len(pooled_pr),
        "analysis_median": _median(pooled_an), "analysis_n": len(pooled_an),
        "questions_per_job": _ratio(sum(r["question_total"] for r in rows), q_jobs),
        "retries": sum(r["retries"] for r in rows),
        "tokens": sum(detail.values()) if detail else None, "tokens_detail": detail, "tokens_users": len(with_tokens),
    }


def _cell(value, pct: bool = False) -> str:
    if value is None:
        return "-"
    if pct:
        return f"{value * 100:.0f}%"
    return f"{value:,}" if isinstance(value, int) else f"{value:g}"


def render(rows: list[dict], total: dict, skipped: list[str]) -> str:
    table = [COLUMNS]
    for r in rows:
        table.append((r["user"], _cell(r["jobs"]), _cell(r["pr"]), _cell(r["analysis_only"]), _cell(r["cancel_ratio"], True),
                      _cell(_median(r["pr_minutes"])), _cell(_median(r["analysis_minutes"])),
                      _cell(_ratio(r["question_total"], r["question_jobs"])), _cell(r["retries"]),
                      _cell(int(r["tokens"]) if r["tokens"] is not None else None)))
    table.append(("합계", _cell(total["jobs"]), _cell(total["pr"]), _cell(total["analysis_only"]), _cell(total["cancel_ratio"], True),
                  _cell(total["pr_median"]), _cell(total["analysis_median"]), _cell(total["questions_per_job"]),
                  _cell(total["retries"]), _cell(int(total["tokens"]) if total["tokens"] is not None else None)))
    widths = [max(len(row[i]) for row in table) for i in range(len(COLUMNS))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in table]
    lines.insert(1, "  ".join("-" * w for w in widths))
    lines.insert(0, f"팀 지표: 사용자 {total['users']}명 · PR까지 중앙값은 측정 {total['pr_n']}건 · 스크립트 분석까지 {total['analysis_n']}건"
                    f" · 취소율 {total['cancelled']}/{total['cancel_base']}({total['cancel_users']}명 합산)"
                    f" · 토큰(입력+출력+캐시 읽기+캐시 쓰기, 비용 아님)은 {total['tokens_users']}명만 측정")
    lines += [f"건너뜀: {s}" for s in skipped]
    lines.append("기준선(도입 전 사람 분석 시간)·사후 오분류율은 이 표에 없다 — 파일럿 보고에 따로 적는다.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="팀 운영 지표 표 (usage_stats --json 파일 모음)")
    parser.add_argument("files", nargs="+", metavar="json", help="팀원마다 뽑은 usage_stats.py --json 파일")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args(argv)
    rows, skipped = [], []
    for name in args.files:
        row, why = read_one(Path(name))
        if row is None:
            skipped.append(why)
        else:
            rows.append(row)
    if not rows:
        print("읽을 수 있는 usage_stats --json 파일이 없다: " + "; ".join(skipped), file=sys.stderr)
        return 1
    total = summarize(rows)
    if args.json:
        print(json.dumps({"format": 1, "users": rows, "total": total, "skipped": skipped}, ensure_ascii=False))
    else:
        print(render(rows, total, skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
