"""리뷰·통계가 함께 쓰는 품질 판정 (06-collaboration.md §6.5·§6.6·§6.7).

`db_build.py`의 STATS와 `db_review.py`의 월간 리뷰가 같은 기준으로 세도록 판정을 여기에 둔다.
기준일(`ref_day`)은 호출하는 쪽이 정한다: STATS는 가장 최근 Jira `date`(결정성, 03-issue-db.md §5.2),
리뷰는 실행일(또는 `--as-of`).

- 발생일은 Jira `occurred_on`, 없으면 `date`. "최근 N일"은 기준일 포함 N일(경과 일수 0~N-1).
- 급증: 최근 30일 ≥ 2건이고 최근 30일 ≥ (그 앞 90일 건수 / 3) × `surge_ratio`.
- fixture 없는 원인: active이고 `signatures_pending`이 아닌데 양성 fixture가 없는 원인
  (R1·R2 `skipped: fixture 없음`과 같은 기준. pending 원인은 "시그니처 없는 원인"으로 센다).
- fixed 전환 불가: 코드·설정 수정 유형인데 `scenario_signatures`·`recovery_signatures`가 모두 없음.
"""

from __future__ import annotations

from datetime import date
from . import issuedb, yamlio
from .fixtures import parse_name

CODE_FIX_TYPES = {"framework-bug", "vendor-ril", "modem", "carrier-config"}
USER_STATEMENT = "근거: 사용자 진술"


def day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def occurred(record: dict) -> date | None:
    return day(record.get("occurred_on")) or day(record.get("date"))


def days_ago(record: dict, ref_day: date | None, field: str | None = None) -> int | None:
    when = day(record.get(field)) if field else occurred(record)
    return (ref_day - when).days if (when and ref_day) else None


def count_window(records: list[dict], ref_day: date | None, lo: int, hi: int) -> int:
    """발생일 경과 일수가 `lo` 이상 `hi` 미만인 건수."""
    n = 0
    for r in records:
        ago = days_ago(r, ref_day)
        if ago is not None and lo <= ago < hi:
            n += 1
    return n


def surge(records: list[dict], ref_day: date | None, ratio: float) -> dict | None:
    """급증이면 `{recent, monthly}`, 아니면 None."""
    recent = count_window(records, ref_day, 0, 30)
    monthly = count_window(records, ref_day, 30, 120) / 3
    if recent >= 2 and recent >= monthly * ratio:
        return {"recent": recent, "monthly": round(monthly, 2)}
    return None


def positive_fixture_causes(db: issuedb.IssueDb) -> set[str]:
    have = set()
    for itype in db.types:
        for path in (itype.path / "fixtures").glob("*.log"):
            fx = parse_name(path.name)
            if fx and fx.kind == "positive" and fx.cause:
                have.add(fx.cause)
    return have


def fixture_expectations(db: issuedb.IssueDb) -> list[dict]:
    """모든 유형의 `.expect.yaml` `[{type, fixture, rel, also_allowed}]` (유형 ID·이름 순)."""
    out = []
    for itype in sorted(db.types, key=lambda t: t.id):
        for path in sorted((itype.path / "fixtures").glob("*.expect.yaml")):
            data = yamlio.load(path) or {}
            if not isinstance(data, dict):
                continue
            out.append({"type": itype.id, "fixture": path.name.replace(".expect.yaml", ".log"),
                        "rel": path.relative_to(db.root).as_posix().replace(".expect.yaml", ".log"),
                        "also_allowed": [str(c) for c in data.get("also_allowed") or []]})
    return out


def no_fixture(cause: issuedb.Cause, have: set[str]) -> bool:
    return cause.active and not cause.pending and cause.id not in have


def no_trace(cause: issuedb.Cause) -> bool:
    raw = cause.raw
    return (raw.get("resolution_type") in CODE_FIX_TYPES
            and not raw.get("scenario_signatures") and not raw.get("recovery_signatures"))


def fix_of(cause: issuedb.Cause) -> dict:
    fix = cause.raw.get("fix")
    return fix if isinstance(fix, dict) else {}


def _fixed_in(fix: dict) -> list[dict]:
    return [f for f in fix.get("fixed_in") or [] if isinstance(f, dict)]


def fix_fields_missing(cause: issuedb.Cause) -> list[str]:
    """수정 상태 누락 항목 (§6.6): fix-submitted인데 ref/fixed_in(브랜치) 없음, fixed인데 verification/빌드 없음."""
    fix = fix_of(cause)
    status = fix.get("status")
    missing = []
    if status == "fix-submitted":
        if not fix.get("ref"):
            missing.append("ref")
        if not any(f.get("branch") for f in _fixed_in(fix)):
            missing.append("fixed_in")
    elif status == "fixed":
        if not fix.get("verification"):
            missing.append("verification")
        if not any(f.get("build") for f in _fixed_in(fix)):
            missing.append("fixed_in.build")
    return missing


def fix_submitted_without_build(cause: issuedb.Cause) -> bool:
    """`fixed_in`(브랜치)은 있는데 빌드가 하나도 없어 §5.9 판정·verify-fix가 불가."""
    fix = fix_of(cause)
    entries = _fixed_in(fix)
    return fix.get("status") == "fix-submitted" and bool(entries) and not any(f.get("build") for f in entries)


def verification_problems(cause: issuedb.Cause) -> list[dict]:
    return [h for h in fix_of(cause).get("verification_history") or []
            if isinstance(h, dict) and h.get("result") in ("failed", "partial")]


def resolution_status(cause: issuedb.Cause) -> str:
    rv = cause.raw.get("resolution_verification")
    return str(rv.get("status")) if isinstance(rv, dict) else "unverified"


def user_statement_sources(cause: issuedb.Cause, jira: list[dict]) -> list[str]:
    """해결책 근거가 사용자 진술뿐인 표시가 있는 곳 (`method`, 소속 Jira `note`). unverified 원인만."""
    if resolution_status(cause) != "unverified":
        return []
    out = []
    rv = cause.raw.get("resolution_verification")
    if isinstance(rv, dict) and USER_STATEMENT in str(rv.get("method") or ""):
        out.append("method")
    for record in jira:
        if str(record.get("cause")) == cause.id and USER_STATEMENT in str(record.get("note") or ""):
            out.append(f"jira:{record.get('key')}")
    return out


def unsupported_versions(cause: issuedb.Cause, supported: list[str]) -> bool:
    """`android_versions`가 비어 있지 않고 모두 지원 목록 밖. 빈 목록은 전 버전이라 제외."""
    versions = [str(v) for v in cause.raw.get("android_versions") or []]
    return bool(versions) and not (set(versions) & {str(v) for v in supported})
