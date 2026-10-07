#!/usr/bin/env python3
"""match_signatures.py — 시그니처 매처 (contracts.md §3.2, 04-parser-matching.md §5.11,
03-issue-db.md §5.9).

    match_signatures.py [--db <path>] --events <json> [--jira-meta <json>]
                        [--regress] [--no-feedback-weight] [--top 3]

입력 이벤트는 `parse_logcat.py parse --mask` 출력이다. `masked: true`가 아니면
종료 코드 2.

모드
- 분석 모드(기본): 모든 active 유형의 S를 구하고, **S=1인 유형의 원인만** C를 평가한다.
  분석 범위 = 입력의 `input.window`(없으면 파일 범위). bonus(근접·키워드)와 피드백
  가중치를 쓴다. 후보마다 수정 상태 판단(`fix_judgement`)과 related를 붙인다.
- 회귀·검증 모드(`--regress`): 모든 active 원인의 C를 **S와 무관하게** 독립 평가한다.
  분석 범위 = 파일 전체, bonus 0, 피드백 가중치 끔. 판정은 S/C 값만 쓰고 점수는
  참고 값이다. 시간 상한을 넘긴 시그니처(`errors`)는 호출자(`db_regress`·`db_verify`)가
  실패로 본다.
- 후보 정렬: 같은 score 후보는 bonus 합(근접+키워드) 내림차순, 다음 ID 순. 회귀 모드는 bonus가 0이라 ID 순.
- 스텝 기준 우선 유형(분석 모드, `--jira-meta`에 `failed_step`이 있을 때만): 같은 스텝이 이 유형의 기존 Jira 기록에 `step_focus.min_records`
  건 이상 있거나(스텝 이름 비교) `issue-db.config.yaml`의 `step_focus.map`에 맞으면 그 유형은 **순위 키에만**
  `scoring.step_focus_bonus_max`(기본 0.05)를 더해 정렬한다. score·confidence·S·C는 바뀌지 않는다. 우선 유형이 있을 때만
  후보 `bonus.step`과 최상위 `step_focus: {types[], by{유형: ["records:N" | "map"]}}`를 낸다.

`--jira-meta` (분석 모드, 선택): `{key, occurred_at, sw, summary, description, failed_step?}` (`failed_step`은 있을 때만, 키워드 보너스 입력).
`occurred_at`은 타임존 있는 ISO 시각, 텍스트 필드는 마스킹된 것이어야 한다.

컴파일: 시그니처는 매번 `--db`에서 메모리로 컴파일한다 (06-collaboration.md §6.8).

출력(JSON, stdout): `{mode, candidates[], pending_causes[], types[], causes[], errors[],
warnings[], ...}`. 후보 = `{type, cause, title, score, confidence, S, C, signature,
evidence[], bonus, feedback, fix_judgement, related[]}`. 근거 = `{signature, condition, ts, tag, msg, event, fields,
phone_id, line_ref, event_index}` (`line_ref`: 이벤트의 로그 줄 위치 `{file_index, line_no}` 또는 null, `event_index`: 입력
`events[]` 안의 순번 — 입력 문서 순서 기준이다. 점수·판정에는 쓰지 않는다, 04-parser-matching.md §5.8 (6)). 원인 미확인 후보는 `cause: null`.
`--top N`(기본 3)은 후보 N개와 함께 `types[]`는 S=1, `causes[]`는 C=1인 것만, `pending_causes[]`는 N개만 내고
뺀 개수를 `omitted`에 적는다. 판정 목록 전체가 필요하면 `--top 0`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import builds, compat, dbpath, issuedb, site_defaults, stepanchor  # noqa: E402
from common import compiled as compiled_cache  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from common.patterns import DEFAULT_TIMEOUT_MS  # noqa: E402
from common.signatures import Evaluator, SignatureError  # noqa: E402

OUTPUT_SCHEMA = 1
DEFAULT_SCORING = {
    "symptom_weight": 0.4,
    "cause_weight": 0.6,
    "proximity_bonus_max": 0.1,
    "keyword_bonus_max": 0.05,
    "step_focus_bonus_max": 0.05,
    "feedback_weight": True,
    "confidence": {"high": 0.9, "medium": 0.6},
}
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣_]{2,}")
DEFAULT_STEP_FOCUS_MIN_RECORDS = 2


class UsageError(Exception):
    pass


def _parse_iso(value: str, what: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise UsageError(f"{what}: ISO 시각이 아닙니다: {value}") from exc
    if dt.tzinfo is None:
        raise UsageError(f"{what}: 타임존이 있는 시각이어야 합니다: {value}")
    return dt


def _load_json(path: str, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"{what}을(를) 읽을 수 없습니다: {path}: {exc}") from exc


def _scoring(config: dict) -> dict:
    scoring = dict(DEFAULT_SCORING)
    scoring.update(config.get("scoring") or {})
    scoring["confidence"] = {**DEFAULT_SCORING["confidence"], **(scoring.get("confidence") or {})}
    return scoring


def _confidence(score: float, scoring: dict) -> str:
    conf = scoring["confidence"]
    if score >= conf["high"]:
        return "high"
    if score >= conf["medium"]:
        return "medium"
    return "low"


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _keyword_ratio(jira: dict, itype: issuedb.IssueType, cause: issuedb.Cause | None) -> float:
    jira_tokens = _tokens(" ".join(str(jira.get(k) or "") for k in ("summary", "description", "failed_step")))
    if not jira_tokens:
        return 0.0
    words = " ".join([cause.title if cause else itype.title, *map(str, itype.raw.get("tags") or [])])
    target = _tokens(words)
    return len(target & jira_tokens) / len(target) if target else 0.0


def _num(value, default: float, lo: float, hi: float) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and lo <= value <= hi
    return float(value) if ok else default


def _step_focus(db: issuedb.IssueDb, jira: dict, scoring: dict) -> dict[str, list[str]]:
    """실패 스텝 → 우선 유형 `{유형 ID: ["records:N", "map"]}` (순위 참고만, 점수·S/C 불변).

    (i) 유형의 Jira 기록 중 `failed_step`이 같은 스텝(이름 비교)인 것이 `step_focus.min_records`건 이상,
    (ii) `step_focus.map[{pattern, types[], categories[]}]`의 `pattern`이 마스킹된 스텝에 맞으면 그 유형과 그 카테고리의
    active 유형 전부. 정규식·값 오류는 그 항목만 건너뛴다(`db_lint`가 잡는다)."""
    step = " ".join(str(jira.get("failed_step") or "").split())
    if not step or not scoring.get("step_focus_bonus_max"):
        return {}
    cfg = db.config.get("step_focus")
    cfg = cfg if isinstance(cfg, dict) else {}
    minimum = cfg.get("min_records", DEFAULT_STEP_FOCUS_MIN_RECORDS)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        minimum = DEFAULT_STEP_FOCUS_MIN_RECORDS
    active = {t.id: t for t in db.types if t.active}
    by: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for record in db.jira:
        recorded = record.get("failed_step")
        if recorded and stepanchor.same_step(recorded, step, names_only=True):
            counts[record["_type"]] = counts.get(record["_type"], 0) + 1
    for type_id in sorted(counts):
        if counts[type_id] >= minimum and type_id in active:
            by.setdefault(type_id, []).append(f"records:{counts[type_id]}")
    for item in cfg.get("map") or []:
        if not isinstance(item, dict) or not isinstance(item.get("pattern"), str):
            continue
        try:
            hit = re.search(item["pattern"], step)
        except re.error:
            continue
        if not hit:
            continue
        types = {str(t) for t in item.get("types") or []}
        categories = {str(c) for c in item.get("categories") or []}
        for type_id, itype in active.items():
            if (type_id in types or itype.category in categories) and "map" not in by.get(type_id, []):
                by.setdefault(type_id, []).append("map")
    return {type_id: by[type_id] for type_id in sorted(by)}


def _proximity(evidence: list[dict], occurred: datetime | None, half_sec: float | None) -> float:
    if occurred is None or not half_sec or not evidence:
        return 0.0
    gap = min(abs((_parse_iso(e["ts"], "evidence") - occurred).total_seconds()) for e in evidence)
    return max(0.0, 1.0 - gap / half_sec)


# -- 수정 상태 판단 (03-issue-db.md §5.9) ----------------------------------------


def fix_judgement(cause: issuedb.Cause, sw: str | None, rules: list[dict], jira_count: int) -> dict:
    fix = cause.raw.get("fix") or {}
    status = fix.get("status")
    fixed_in = [f for f in fix.get("fixed_in") or [] if isinstance(f, dict)]
    result = {"status": status, "judgement": None, "message": None, "sw": sw, "fixed_in": fixed_in}
    if status == "open":
        result.update(judgement="unfixed", message=f"미수정 원인. 기존 Jira {jira_count}건")
        return result
    if status not in ("fixed", "fix-submitted"):
        return result  # wont-fix / not-a-bug: 수정 판단 대상이 아니다
    comparisons = []
    for item in fixed_in:
        if item.get("build"):
            cmp = builds.compare(sw, item["build"], rules)
            if cmp is not None:
                comparisons.append((cmp, item["build"]))
    if not comparisons:
        builds_text = ", ".join(f.get("build") or f"{f.get('branch')}(빌드 없음)" for f in fixed_in) or "없음"
        result.update(
            judgement="undetermined",
            message=f"판단 불가 — Jira SW {sw or '없음'}, fixed_in {builds_text}. 사용자가 판단한다",
        )
        return result
    newer = [b for c, b in comparisons if c >= 0]  # "이후"는 같은 빌드를 포함한다 (≥)
    if status == "fixed":
        if newer:
            result.update(judgement="regression-suspected",
                          message=f"수정 빌드({newer[0]}) 이후(같은 빌드 포함)에서 재발. 회귀 가능성")
        else:
            build = comparisons[0][1]
            result.update(judgement="already-fixed",
                          message=f"{build}에서 수정됨. 빌드 업데이트 후 재확인 권고")
    else:
        if newer:
            result.update(judgement="fix-insufficient",
                          message="수정 반영 빌드에서 발생. verify-fix 실패 가능성")
        else:
            result.update(judgement="fix-pending-build",
                          message="수정 CL 반영 전 빌드. 업데이트 후 verify-fix 권고")
    return result


# -- 매칭 ----------------------------------------------------------------------


def _related(db: issuedb.IssueDb, cause: issuedb.Cause | None) -> list[dict]:
    if cause is None:
        return []
    out = []
    for rid in cause.raw.get("related") or []:
        other = db.cause_by_id(str(rid))
        out.append({
            "cause": str(rid),
            "type": other.type_id if other else None,
            "title": other.title if other else None,
            "status": other.status if other else None,
        })
    return out


def _first_satisfied(evaluator: Evaluator, sigs, occurred, errors: list[dict]):
    """시그니처 목록(OR)에서 처음 충족한 것. 시간 상한 오류는 `errors`에 쌓는다."""
    satisfied = None
    for sig in sigs:
        result = evaluator.evaluate(sig, occurred)
        if result.error:
            errors.append({"signature": sig.key, "error": result.error})
            continue
        if result.satisfied and satisfied is None:
            satisfied = result
    return satisfied


def _all_satisfied(evaluator: Evaluator, sigs, occurred, errors: list[dict]):
    matches = []
    for sig in sigs:
        for result in evaluator.evaluate_all(sig, occurred):
            if result.error:
                errors.append({"signature": sig.key, "error": result.error})
            elif result.satisfied:
                matches.append(result)
    return matches


def _compatible(sym, cause) -> bool:
    if sym.same_phone and cause.same_phone:
        left = {e["phone_id"] for e in sym.evidence if e.get("phone_id") is not None}
        right = {e["phone_id"] for e in cause.evidence if e.get("phone_id") is not None}
        if left and right and left.isdisjoint(right):
            return False
    times = [_parse_iso(e["ts"], "evidence") for e in sym.evidence + cause.evidence]
    return (max(times) - min(times)).total_seconds() <= max(sym.window_sec, cause.window_sec)


def run(args) -> dict:
    events_doc = _load_json(args.events, "--events")
    if not isinstance(events_doc, dict) or events_doc.get("masked") is not True:
        raise UsageError(
            "마스킹되지 않은 이벤트는 받지 않습니다 (masked: true가 아님). "
            "parse_logcat.py parse --mask 출력을 주세요 (04-parser-matching.md §5.11 (1))."
        )
    try:
        root = dbpath.resolve(args.db)
        db = issuedb.load(root)
    except (dbpath.DbPathError, issuedb.IssueDbError) as exc:
        raise UsageError(str(exc)) from exc

    jira = _load_json(args.jira_meta, "--jira-meta") if args.jira_meta else {}
    if not isinstance(jira, dict):
        raise UsageError("--jira-meta는 JSON 객체여야 합니다.")
    try:
        compiled = compiled_cache.compile_signatures(db)
    except SignatureError as exc:
        raise UsageError(f"시그니처 오류: {exc}") from exc
    return match(events_doc, db, compiled, regress=bool(args.regress), jira=jira,
                 no_feedback_weight=args.no_feedback_weight, top=args.top)


def _range(events_doc: dict, regress: bool):
    """(정렬된 이벤트, 범위 시작, 끝, 분석 창, 정렬된 이벤트의 입력 순번). 회귀·검증 모드는 파일 전체다."""
    raw = events_doc.get("events") or []
    order = sorted(range(len(raw)), key=lambda k: raw[k]["ts"])  # 안정 정렬: 같은 시각이면 입력 순서
    events = [raw[k] for k in order]
    coverage = events_doc.get("coverage") or {}
    window = (events_doc.get("input") or {}).get("window")
    if regress or not window:
        lo, hi = coverage.get("first_ts"), coverage.get("last_ts")
    else:
        lo, hi = window["start"], window["end"]
    lo = _parse_iso(lo, "범위") if lo else None
    hi = _parse_iso(hi, "범위") if hi else None
    return events, lo, hi, window, order


def evaluator_for(events_doc: dict, db: issuedb.IssueDb) -> Evaluator:
    """회귀·검증 모드 평가기 (파일 전체 범위, 이슈 DB의 패턴 시간 상한). 호출자가 닫는다."""
    events, lo, hi, _, ids = _range(events_doc, True)
    timeout_ms = int((db.config.get("matcher") or {}).get("pattern_timeout_ms", DEFAULT_TIMEOUT_MS))
    return Evaluator(events, lo, hi, timeout_ms, ids)


def match(events_doc: dict, db: issuedb.IssueDb, compiled: dict, *, regress: bool, jira: dict | None = None,
          no_feedback_weight: bool = False, top: int = 0, acceptance: dict | None = None,
          evaluator: Evaluator | None = None) -> dict:
    """마스킹된 이벤트 문서 하나를 이슈 DB에 매칭한다 (`db_regress`·`db_verify`가 직접 부른다).
    `compiled`는 `common/compiled.py`의 `compile_signatures()` 결과. `evaluator`를 주면(회귀·검증 모드에서
    같은 이벤트로 다른 시그니처도 평가할 때, `evaluator_for()`) 그것을 쓰고 닫지 않는다."""
    jira = jira or {}
    occurred = None
    if jira.get("occurred_at") and not regress:
        occurred = _parse_iso(jira["occurred_at"], "--jira-meta occurred_at")

    events, lo, hi, window, ids = _range(events_doc, regress)
    half = (hi - lo).total_seconds() / 2 if (lo and hi and window and not regress) else None

    scoring = _scoring(db.config)
    use_bonus = not regress
    focus_map = _step_focus(db, jira, scoring) if use_bonus and jira.get("failed_step") else {}
    focus_max = _num(scoring.get("step_focus_bonus_max"), DEFAULT_SCORING["step_focus_bonus_max"], 0.0, 0.1)
    use_feedback = bool(scoring.get("feedback_weight")) and not regress and not no_feedback_weight
    min_samples = int((db.config.get("quality") or {}).get("min_samples", 5))
    if acceptance is None:
        acceptance = issuedb.acceptance(db.feedback)
    stats = acceptance if use_feedback else {}
    timeout_ms = int((db.config.get("matcher") or {}).get("pattern_timeout_ms", DEFAULT_TIMEOUT_MS))
    rules = db.config.get("build_compare") or []

    warnings = []
    backend = events_doc.get("backend") or {}
    if backend.get("name"):
        warnings += compat.check_parser_backend(db.config, backend["name"], str(backend.get("version")))

    errors: list[dict] = []
    types_out, causes_out, candidates, pending = [], [], [], []
    own = evaluator is None
    if own:
        evaluator = Evaluator(events, lo, hi, timeout_ms, ids)
    try:
        for itype in db.types:
            if not itype.active:
                continue
            symptoms = [] if regress else _all_satisfied(evaluator, compiled[itype.id], occurred, errors)
            sym = (_first_satisfied(evaluator, compiled[itype.id], occurred, errors) if regress
                   else next(iter(symptoms), None))
            S = 1 if sym else 0
            types_out.append({
                "type": itype.id, "S": S,
                "signature": sym.key if sym else None,
                "evidence": sym.evidence if sym else [],
            })
            if S:
                pending += [{"type": itype.id, "cause": c.id, "title": c.title}
                            for c in itype.causes if c.active and c.pending]
            if not S and not regress:
                continue
            any_cause = False
            for cause in itype.causes:
                if not cause.active or cause.pending:
                    continue
                candidate_sym = sym
                if regress:
                    res = _first_satisfied(evaluator, compiled[cause.id], occurred, errors)
                else:
                    matches = _all_satisfied(evaluator, compiled[cause.id], occurred, errors)
                    pair = next(((s, c) for c in matches for s in symptoms if _compatible(s, c)), None)
                    candidate_sym, res = pair if pair else (sym, None)
                C = 1 if res else 0
                causes_out.append({"type": itype.id, "cause": cause.id, "S": S, "C": C,
                                   "signature": res.key if res else None})
                if not C:
                    continue
                any_cause = True
                candidates.append(_candidate(db, itype, cause, S, C, candidate_sym, res, jira, occurred, half,
                                             scoring, use_bonus, stats, min_samples, rules, use_feedback,
                                             focus_max if itype.id in focus_map else 0.0))
            if S and not any_cause:
                candidates.append(_candidate(db, itype, None, S, 0, sym, None, jira, occurred, half,
                                             scoring, use_bonus, stats, min_samples, rules, use_feedback,
                                             focus_max if itype.id in focus_map else 0.0))
    finally:
        if own:
            evaluator.close()

    candidates.sort(key=_rank_key)
    omitted = None
    if top:   # --top N: 후보 N개, 유형·원인은 충족된 것만, pending 원인 N개 (판정 목록 전체는 --top 0)
        kept_types = [t for t in types_out if t["S"]]
        kept_causes = [c for c in causes_out if c["C"]]
        omitted = {"types": len(types_out) - len(kept_types), "causes": len(causes_out) - len(kept_causes),
                   "pending_causes": max(0, len(pending) - top), "candidates": max(0, len(candidates) - top)}
        types_out, causes_out, pending = kept_types, kept_causes, pending[:top]
    result = {
        "schema": OUTPUT_SCHEMA,
        "mode": "regress" if regress else "analysis",
        "db": str(db.root),
        "range": {"start": lo.isoformat() if lo else None, "end": hi.isoformat() if hi else None},
        "bonus": use_bonus,
        "feedback_weight": use_feedback,
        "jira": {k: jira.get(k) for k in ("key", "occurred_at", "sw") if k in jira},
        "candidates": candidates[:top] if top else candidates,
        "pending_causes": pending,
        "types": types_out,
        "causes": causes_out,
        "errors": errors,
        "warnings": warnings,
    }
    if focus_map:
        result["step_focus"] = {"types": list(focus_map), "by": focus_map}
    if omitted is not None:
        result["omitted"] = omitted
    return result


def _rank_key(c: dict) -> tuple:
    """(-(score+step), -(근접+키워드+step), 유형, 원인): 점수 동점은 근접+키워드 근거로 정렬한다.

    `step`은 스텝 기준 우선 유형의 순위 가산(`bonus.step`, 없으면 0)이다. 정렬에만 쓰고 `score`는 바꾸지 않는다.
    우선 유형이 없으면 키가 `(-score, -(근접+키워드), 유형, 원인)`으로 이전과 같다."""
    b = c["bonus"]
    focus = b.get("step", 0)
    return (-round(c["score"] + focus, 4), -round(b["proximity"] + b["keyword"] + focus, 4), c["type"], c["cause"] or "")


def _candidate(db, itype, cause, S, C, sym, res, jira, occurred, half, scoring, use_bonus,
               stats, min_samples, rules, use_feedback, step_bonus: float = 0.0) -> dict:
    evidence = (res.evidence if res else []) + (sym.evidence if sym else [])
    base = scoring["symptom_weight"] * S + scoring["cause_weight"] * C
    proximity = keyword = 0.0
    if use_bonus:
        proximity = scoring["proximity_bonus_max"] * _proximity(evidence, occurred, half)
        keyword = scoring["keyword_bonus_max"] * _keyword_ratio(jira, itype, cause)
    score = min(1.0, base + proximity + keyword)
    signature = res.key if res else (sym.key if sym else None)
    feedback = {"accepted": 0, "total": 0, "rate": None, "applied": False}
    if use_feedback and signature in stats:
        accepted, total = stats[signature]
        feedback.update(accepted=accepted, total=total, rate=round(accepted / total, 3))
        if total >= min_samples:
            score *= 0.5 + 0.5 * accepted / total
            feedback["applied"] = True
    score = round(score, 4)
    judgement = None
    if cause is not None and use_bonus:  # 분석 모드에서만 (회귀·검증 모드는 Jira가 없다)
        judgement = fix_judgement(cause, jira.get("sw"), rules, db.jira_counts.get(cause.id, 0))
    bonus = {"proximity": round(proximity, 4), "keyword": round(keyword, 4)}
    if step_bonus > 0:
        bonus["step"] = round(step_bonus, 4)
    return {
        "type": itype.id,
        "cause": cause.id if cause else None,
        "title": cause.title if cause else f"{itype.title} (원인 미확인)",
        "category": itype.category,
        "secondary_categories": list(itype.raw.get("secondary_categories") or []),
        "score": score,
        "confidence": _confidence(score, scoring),
        "S": S,
        "C": C,
        "signature": signature,
        "evidence": evidence,
        "bonus": bonus,
        "feedback": feedback,
        "fix_judgement": judgement,
        "related": _related(db, cause),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="match_signatures.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None)
    parser.add_argument("--events", metavar="json", required=True)
    parser.add_argument("--jira-meta", metavar="json", default=None)
    parser.add_argument("--regress", action="store_true")
    parser.add_argument("--no-feedback-weight", action="store_true")
    parser.add_argument("--top", type=int, default=3,
                        help="후보 수. types·causes는 충족된 것만, pending은 N개 (0이면 전부)")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    args.defaults = site_defaults.load_or_exit(args.plugin_root)
    try:
        result = run(args)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for warning in result["warnings"]:
        print(f"경고[{warning['code']}]: {warning['message']}", file=sys.stderr)
    for error in result["errors"]:
        print(f"오류[{error['signature']}]: {error['error']}", file=sys.stderr)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
