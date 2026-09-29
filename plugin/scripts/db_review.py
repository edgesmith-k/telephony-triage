#!/usr/bin/env python3
"""db_review.py — 월간 리뷰 리포트 (06-collaboration.md §6.6, contracts.md §3.2).

    db_review.py [--db <path>] [category] [--out <file>] [--as-of <YYYY-MM-DD>] [--json]

읽기 전용이다. 이슈 DB를 바꾸지 않고, 세션 lock을 잡지 않으며 스냅샷을 옮기지 않는다
(`review` 커맨드가 부른다). 카테고리를 주면 그 카테고리만, 없으면 전체를 본다.

- 기준일은 실행일이다. `--as-of`로 바꿀 수 있다(시험·재현용). STATS의 기준일(가장 최근 Jira `date`)과
  다른 이유: 리뷰는 "지금 방치된 것"을 찾는 보고서이고 생성 파일이 아니라 결정성 규칙(§5.2) 대상이 아니다.
- 항목 기준은 `issue-db.config.yaml`의 `quality`와 `android_versions_supported`다. STATS와 같은 판정은
  `common/quality.py`를 함께 쓴다.
- 방치 기간(해결책 미검증, 수정 검증 대기, Jira 없는 원인의 나이)은 git 이력(`common/history.py`)으로 구한다.
  이력이 없으면 그 원인은 "기간 확인 불가"로 따로 보인다.
- 중복 후보는 active 유형의 양성·`recurrence`·`extra` fixture를 회귀·검증 모드로 매칭해서 **다른 유형의 증상
  시그니처가 함께 S=1**인 쌍과, 같은 카테고리에서 제목 유사도가 높은(`TITLE_SIMILARITY` 이상) 쌍이다.
  원인끼리 `related`로 이어졌거나 그 fixture의 `also_allowed`에 상대 유형 원인이 있는 동시 매칭은 이미 알려진
  연관이므로 뺀다.
- 수락률은 `issuedb.acceptance()`(1위로 제시된 피드백만 분모, `decision: manual` 제외, §6.5).

출력: 기본은 Markdown 리포트(stdout). `--out`이면 그 파일에 Markdown을 쓴다. `--json`이면 stdout에 JSON
`{db, head, as_of, category, owners, thresholds, feedback, items[{key, title, criterion, action, count, entries[],
undetermined[]}]}`. 종료 코드: 0(리포트), 2(사용·환경 오류).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import db_regress  # noqa: E402
import match_signatures  # noqa: E402
import parse_logcat  # noqa: E402
from common import dbpath, history, issuedb, quality, site_defaults, userconfig  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402

TITLE_SIMILARITY = 0.8
COMATCH_KINDS = ("positive", "recurrence", "extra")
ALSO_ALLOWED_PER_FIXTURE = 3
ALSO_ALLOWED_PER_CAUSE = 5
DEFAULTS = {"min_samples": 5, "low_acceptance_rate": 0.7, "stale_months": 12, "unresolved_max_days": 30,
            "unverified_max_days": 60, "fix_submitted_max_days": 30, "surge_ratio": 2.0}


class UsageError(Exception):
    pass


# -- 보조 ---------------------------------------------------------------------------


def _months_before(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + (day.month - 1) - months, 12)
    m += 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(y, m, d)
        except ValueError:
            continue
    return date(y, m, 28)


def _owners(root: Path, categories: list[str]) -> dict[str, list[str]]:
    path = root / ".github" / "CODEOWNERS"
    out: dict[str, list[str]] = {c: [] for c in categories}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) < 2:
            continue
        key = parts[0].strip("/")
        if key in out:
            out[key] = parts[1:]  # 마지막으로 맞는 규칙이 이긴다
    return out


def _similarity(a: str, b: str) -> float:
    import db_add  # noqa: WPS433 — `db_add similar`와 같은 유사도

    return db_add.similarity(a, b)


class Review:
    def __init__(self, db: issuedb.IssueDb, category: str | None, as_of: date, plugin_root: Path, defaults: dict):
        self.db = db
        self.category = category
        self.as_of = as_of
        self.plugin_root = plugin_root
        self.defaults = defaults
        self.q = {**DEFAULTS, **(db.config.get("quality") or {})}
        self.supported = [str(v) for v in db.config.get("android_versions_supported") or []]
        self.types = sorted(db.types, key=lambda t: t.id)
        self.type_by_id = {t.id: t for t in self.types}
        self.causes = [c for t in self.types if t.active for c in t.causes if c.active]
        self.history = history.History(db.root)
        self.items: list[dict] = []

    # 범위 --------------------------------------------------------------------------

    def cat_of(self, ident: str) -> str | None:
        type_id = "-".join(str(ident).split("/", 1)[0].split("-")[:2])
        itype = self.type_by_id.get(type_id)
        return itype.category if itype else None

    def in_scope(self, *idents: str) -> bool:
        return self.category is None or any(self.cat_of(i) == self.category for i in idents)

    def scoped_causes(self) -> list[issuedb.Cause]:
        return [c for c in self.causes if self.in_scope(c.id)]

    def jira_of(self, cause_id: str) -> list[dict]:
        return [r for r in self.db.jira if str(r.get("cause")) == cause_id]

    def type_md(self, cause: issuedb.Cause) -> str:
        return (self.type_by_id[cause.type_id].path / "type.md").relative_to(self.db.root).as_posix()

    def add(self, key: str, title: str, criterion: str, action: str, entries: list[dict],
            undetermined: list[dict] | None = None) -> None:
        self.items.append({"key": key, "title": title, "criterion": criterion, "action": action,
                           "count": len(entries), "entries": entries, "undetermined": undetermined or []})

    # 항목 --------------------------------------------------------------------------

    def run(self) -> list[dict]:
        causes = self.scoped_causes()
        have = quality.positive_fixture_causes(self.db)
        q = self.q

        self.add("pending-signatures", "시그니처 없는 원인", "`signatures_pending: true`인 원인 (원인 판별 불가)",
                 "판별 시그니처 추가(`update-signature`, R1~R5 통과 필요)",
                 [{"cause": c.id, "title": c.title, "text": f"{c.id} {c.title}"} for c in causes if c.pending])

        self.add("no-fixture", "fixture 없는 원인", "양성 fixture가 없어 R1·R2가 `skipped: fixture 없음`인 원인",
                 "로그를 받아 fixture 추가",
                 [{"cause": c.id, "title": c.title, "text": f"{c.id} {c.title}"}
                  for c in causes if quality.no_fixture(c, have)])

        stale_unresolved = []
        for r in sorted(self.db.jira, key=lambda r: (str(r.get("date")), str(r.get("key")))):
            if str(r.get("cause")) != "unresolved" or not self.in_scope(r["_type"]):
                continue
            age = quality.days_ago(r, self.as_of, "date")
            if age is not None and age > int(q["unresolved_max_days"]):
                stale_unresolved.append({"jira": r.get("key"), "type": r["_type"], "date": str(r.get("date")),
                                         "days": age,
                                         "text": f"{r.get('key')} ({r['_type']}, 기록 {r.get('date')}, {age}일)"})
        self.add("stale-unresolved", "오래된 원인 미확정",
                 f"`unresolved`가 `quality.unresolved_max_days`({q['unresolved_max_days']}일) 초과 (Jira 기록 `date` 기준)",
                 "원인 확정 또는 담당자 지정", stale_unresolved)

        low = []
        for key, (acc, total) in sorted(issuedb.acceptance(self.db.feedback).items()):
            if not self.in_scope(key) or total < int(q["min_samples"]):
                continue
            rate = acc / total
            if rate < float(q["low_acceptance_rate"]):
                low.append({"signature": key, "accepted": acc, "total": total, "rate": f"{rate:.2f}",
                            "text": f"`{key}` 수락률 {rate:.2f} ({acc}/{total})"})
        low.sort(key=lambda e: (float(e["rate"]), e["signature"]))
        self.add("low-acceptance", "품질 낮은 시그니처",
                 f"수락률 < `quality.low_acceptance_rate`({q['low_acceptance_rate']}), 1위 제시 {q['min_samples']}건 이상. "
                 "`decision: manual`(수동 기록)은 빼고 센다",
                 "시그니처 좁히기 또는 삭제", low)

        self.add("duplicate-candidates", "중복 후보",
                 "서로 다른 유형의 증상 시그니처가 같은 fixture에 동시 매칭(이미 `related`·`also_allowed`로 이어진 것 "
                 f"제외), 또는 같은 카테고리에서 제목 유사도 {TITLE_SIMILARITY} 이상",
                 "`merged-into`로 병합(`move/...` 계획, `docs/review-guide.md` §4)", self.duplicates())

        stale, stale_unknown = [], []
        threshold = _months_before(self.as_of, int(q["stale_months"]))
        for c in causes:
            records = self.jira_of(c.id)
            if records:
                last = max((quality.occurred(r) for r in records if quality.occurred(r)), default=None)
                if last and last < threshold:
                    stale.append({"cause": c.id, "last": last.isoformat(),
                                  "text": f"{c.id} {c.title} (마지막 발생 {last.isoformat()})"})
                continue
            since, source = self.history.since(self.type_md(c), c.id, lambda _c: True)
            if since is None:
                stale_unknown.append({"cause": c.id, "reason": source,
                                      "text": f"{c.id} {c.title} (Jira 없음, 추가 시점 확인 불가: {source})"})
            elif since < threshold:
                stale.append({"cause": c.id, "last": None, "since": since.isoformat(),
                              "text": f"{c.id} {c.title} (Jira 없음, {since.isoformat()} 추가)"})
        self.add("stale-causes", "오래 안 쓰인 원인",
                 f"`quality.stale_months`({q['stale_months']}개월, {threshold.isoformat()} 이전) 동안 Jira 발생 없음",
                 "유지 또는 원인 `status: deprecated`", stale, stale_unknown)

        self.add("unsupported-versions", "지원 종료 버전",
                 f"원인의 `android_versions`가 비어 있지 않고 모두 `android_versions_supported`({', '.join(self.supported)}) "
                 "밖 (빈 목록 = 전 버전이므로 제외)",
                 "원인 `status: deprecated`",
                 [{"cause": c.id, "versions": [str(v) for v in c.raw.get("android_versions") or []],
                   "text": f"{c.id} {c.title} (android_versions: "
                           f"{', '.join(str(v) for v in c.raw.get('android_versions') or [])})"}
                  for c in causes if quality.unsupported_versions(c, self.supported)])

        open_rows = sorted(((c, len(self.jira_of(c.id))) for c in causes
                            if quality.fix_of(c).get("status") == "open"), key=lambda x: (-x[1], x[0].id))
        self.add("open-with-jira", "수정 필요 누적", "`fix.status: open`이면서 Jira가 있는 원인 (Jira 건수 순)",
                 "근본 수정 우선순위 제안",
                 [{"cause": c.id, "jira": n, "text": f"{c.id} {c.title} (Jira {n}건)"} for c, n in open_rows if n])

        self.add("fix-fields-missing", "수정 상태 누락",
                 "`fix-submitted`인데 `ref`/`fixed_in`(브랜치) 없음, `fixed`인데 `verification`/`fixed_in` 빌드 없음",
                 "보완",
                 [{"cause": c.id, "status": quality.fix_of(c).get("status"), "missing": quality.fix_fields_missing(c),
                   "text": f"{c.id} {quality.fix_of(c).get('status')}: {', '.join(quality.fix_fields_missing(c))} 없음"}
                  for c in causes if quality.fix_fields_missing(c)])

        self.add("no-trace-signatures", "fixed 전환 불가",
                 "코드·설정 수정 유형인데 `scenario_signatures`와 `recovery_signatures`가 모두 없음 "
                 "(`fix-submitted`면 verify-fix 불가)", "시그니처 추가",
                 [{"cause": c.id, "resolution_type": c.raw.get("resolution_type"),
                   "fix_status": quality.fix_of(c).get("status"),
                   "text": f"{c.id} {c.title} ({c.raw.get('resolution_type')}, fix {quality.fix_of(c).get('status')})"}
                  for c in causes if quality.no_trace(c)])

        self.add("fix-submitted-no-build", "빌드 없는 fix-submitted",
                 "`fixed_in`에 빌드가 없어 `03-issue-db.md §5.9` 판정 불가", "`fix-submitted` 커맨드로 빌드 추가",
                 [{"cause": c.id, "text": f"{c.id} {c.title}"} for c in causes if quality.fix_submitted_without_build(c)])

        self.add(*self.stale_state(
            causes, "unverified-stale", "해결책 미검증 방치", "unverified_max_days",
            "`resolution_verification: unverified`", "검증 담당자 지정",
            lambda c: quality.resolution_status(c) == "unverified" and not c.pending,
            lambda cur: (lambda old: str((old.get("resolution_verification") or {}).get("status", "unverified"))
                         == "unverified" and old.get("resolution") == cur.raw.get("resolution"))))

        self.add("user-statement-only", "사용자 진술만 있는 해결책",
                 f"`resolution_verification: unverified`이고 `method` 또는 소속 Jira `note`에 \"{quality.USER_STATEMENT}\"",
                 "근거(다른 Jira, `resolved` fixture)를 받아 `verify-resolution` 또는 유지 판단",
                 [{"cause": c.id, "sources": quality.user_statement_sources(c, self.db.jira),
                   "text": f"{c.id} {c.title} ({', '.join(quality.user_statement_sources(c, self.db.jira))})"}
                  for c in causes if quality.user_statement_sources(c, self.db.jira)])

        self.add(*self.stale_state(
            causes, "fix-submitted-stale", "수정 검증 대기 방치", "fix_submitted_max_days",
            "`fix-submitted`", "`verify-fix` 요청",
            lambda c: quality.fix_of(c).get("status") == "fix-submitted",
            lambda cur: (lambda old: (old.get("fix") or {}).get("status") == "fix-submitted")))

        self.add("verification-failures", "수정 검증 실패·부분 통과 이력",
                 "`verification_history`에 `failed` 또는 `partial`이 있는 원인", "근본 원인 재검토, 남은 증상 분석",
                 [{"cause": c.id, "results": [h.get("result") for h in quality.verification_problems(c)],
                   "text": f"{c.id} {c.title} (" + ", ".join(
                       f"{h.get('result')} {h.get('build') or ''}".strip() for h in quality.verification_problems(c))
                           + ")"}
                  for c in causes if quality.verification_problems(c)])

        self.add("also-allowed-accumulated", "`also_allowed` 누적",
                 f"한 fixture의 `also_allowed`에 {ALSO_ALLOWED_PER_FIXTURE}개 이상, 또는 한 원인이 "
                 f"{ALSO_ALLOWED_PER_CAUSE}개 이상의 다른 유형 fixture에서 허용됨",
                 "그 원인의 시그니처가 너무 넓은지, fixture 구간이 너무 긴지 검토", self.also_allowed())

        surges = []
        for c in causes:
            hit = quality.surge(self.jira_of(c.id), self.as_of, float(q["surge_ratio"]))
            if hit:
                surges.append({"cause": c.id, **hit,
                               "text": f"{c.id} {c.title} (최근 30일 {hit['recent']}건, 이전 90일 월평균 "
                                       f"{hit['monthly']:.2f})"})
        self.add("surge", "급증",
                 f"최근 30일 발생이 이전 90일 월평균 × `quality.surge_ratio`({q['surge_ratio']}) 이상이고 2건 이상 "
                 "(발생일은 `occurred_on`, 없으면 `date`)", "원인 조사", surges)
        return self.items

    def stale_state(self, causes, key, title, limit_key, state_text, action, now_pred, old_pred_for):
        limit = int(self.q[limit_key])
        entries, unknown = [], []
        for c in causes:
            if not now_pred(c):
                continue
            since, source = self.history.since(self.type_md(c), c.id, old_pred_for(c))
            if since is None:
                unknown.append({"cause": c.id, "reason": source, "text": f"{c.id} {c.title} (기간 확인 불가: {source})"})
                continue
            days = (self.as_of - since).days
            if days > limit:
                entries.append({"cause": c.id, "since": since.isoformat(), "days": days,
                                "text": f"{c.id} {c.title} ({since.isoformat()}부터 {days}일)"})
        criterion = f"{state_text}가 `quality.{limit_key}`({limit}일) 초과 (그 상태가 된 날은 git 이력 기준)"
        return key, title, criterion, action, entries, unknown

    # 중복 후보 -----------------------------------------------------------------------

    def _linked(self, own: str, other: str, allowed: set[str]) -> bool:
        """이미 알려진 연관: 두 유형의 원인이 `related`로 이어졌거나, fixture가 상대 유형 원인을 `also_allowed`로 허용."""
        own_causes = {c.id for c in self.type_by_id[own].causes}
        other_causes = {c.id for c in self.type_by_id[other].causes}
        for mine, theirs in ((self.type_by_id[own], other_causes), (self.type_by_id[other], own_causes)):
            if any(set(map(str, c.raw.get("related") or [])) & theirs for c in mine.causes):
                return True
        return bool(allowed & other_causes)

    def duplicates(self) -> list[dict]:
        pairs: dict[tuple[str, str], dict] = {}

        def pair(a: str, b: str) -> dict:
            key = tuple(sorted((a, b)))
            return pairs.setdefault(key, {"types": list(key), "fixtures": [], "title_similarity": None})

        compiled = db_regress.prepare(self.db, self.defaults)
        for item in db_regress.collect(self.db):
            if item["fx"].kind not in COMATCH_KINDS:
                continue
            try:
                events = db_regress.parse_logs([item["path"]], self.db.root / "parser-rules", self.plugin_root,
                                               self.defaults)
            except parse_logcat.UsageError as exc:
                raise UsageError(f"{item['rel']}: {exc}") from exc
            result = match_signatures.match(events, self.db, compiled, regress=True)
            own = item["type"].id
            allowed = set(item["expect"].also_allowed)
            for t in result["types"]:
                other = t["type"]
                if other == own or not t["S"] or self._linked(own, other, allowed):
                    continue
                pair(own, other)["fixtures"].append(item["rel"])

        active = [t for t in self.types if t.active]
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                if a.category != b.category:
                    continue
                sim = _similarity(a.title, b.title)
                if sim >= TITLE_SIMILARITY:
                    pair(a.id, b.id)["title_similarity"] = sim

        out = []
        for (a, b), entry in sorted(pairs.items()):
            if not self.in_scope(a, b):
                continue
            reasons = []
            if entry["fixtures"]:
                reasons.append(f"동시 매칭 {len(entry['fixtures'])}개 fixture ({', '.join(entry['fixtures'])})")
            if entry["title_similarity"] is not None:
                reasons.append(f"제목 유사도 {entry['title_similarity']:.2f}")
            entry["text"] = (f"{a} {self.type_by_id[a].title} ↔ {b} {self.type_by_id[b].title}: "
                             + "; ".join(reasons))
            out.append(entry)
        return out

    # also_allowed --------------------------------------------------------------------

    def also_allowed(self) -> list[dict]:
        expects = quality.fixture_expectations(self.db)
        out = []
        for e in expects:
            if len(e["also_allowed"]) >= ALSO_ALLOWED_PER_FIXTURE and self.in_scope(e["type"], *e["also_allowed"]):
                out.append({"kind": "fixture", "fixture": e["rel"], "causes": e["also_allowed"],
                            "text": f"fixture {e['rel']}: also_allowed {len(e['also_allowed'])}개 "
                                    f"({', '.join(e['also_allowed'])})"})
        by_cause: dict[str, list[str]] = {}
        for e in expects:
            for cause in e["also_allowed"]:
                if cause.rsplit("-", 1)[0] != e["type"]:
                    by_cause.setdefault(cause, []).append(e["rel"])
        for cause, fixtures in sorted(by_cause.items()):
            if len(fixtures) >= ALSO_ALLOWED_PER_CAUSE and self.in_scope(cause):
                out.append({"kind": "cause", "cause": cause, "fixtures": fixtures,
                            "text": f"원인 {cause}: 다른 유형 fixture {len(fixtures)}개에서 허용"})
        return out


# -- 출력 ---------------------------------------------------------------------------


def render(report: dict) -> str:
    scope = report["category"] or "전체"
    out = [f"# 월간 리뷰 리포트 — {scope} ({report['as_of']})", "",
           f"> 이슈 DB: `{report['db']}`" + (f" @ `{report['head'][:12]}`" if report.get("head") else "")
           + f" · 기준일 {report['as_of']} · 로컬 리포트(push 안 함)",
           f"> 피드백 {report['feedback']['total']}건 중 수동 기록(`decision: manual`) {report['feedback']['manual']}건은 "
           "수락률에서 뺐다.", ""]
    if report["category"]:
        owners = report["owners"].get(report["category"]) or []
        out += [f"오너: {', '.join(owners) if owners else '(CODEOWNERS에 없음)'}", ""]
    out += ["## 요약", "", "| 항목 | 건수 |", "|---|---|"]
    for item in report["items"]:
        extra = f" (+확인 불가 {len(item['undetermined'])})" if item["undetermined"] else ""
        out.append(f"| {item['title']} | {item['count']}{extra} |")
    for item in report["items"]:
        out += ["", f"## {item['title']}", "", f"- 기준: {item['criterion']}", f"- 조치: {item['action']}", ""]
        if item["entries"]:
            out += [f"- {e['text']}" for e in item["entries"]]
        else:
            out.append("없음")
        if item["undetermined"]:
            out += ["", "기간 확인 불가 (git 이력 없음 또는 커밋 전):", ""]
            out += [f"- {e['text']}" for e in item["undetermined"]]
    out += ["", "---", "",
            "정리는 `review/<category>-<YYYY-MM>` PR로 올린다: (a) 직접 편집 후 `validate`, (b) `source: review` 계획 "
            "(병합은 `move/...`, `source: move`). 절차는 이슈 DB `docs/review-guide.md`."]
    return "\n".join(out) + "\n"


def run(args, defaults: dict, plugin_root: Path) -> dict:
    try:
        root = dbpath.resolve(args.db, user_config_path=lambda: userconfig.issue_db_path(defaults))
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc
    try:
        db = issuedb.load(root)
    except issuedb.IssueDbError as exc:
        raise UsageError(str(exc)) from exc
    keys = [c.get("key") for c in db.config.get("categories") or [] if isinstance(c, dict)]
    if args.category and args.category not in keys:
        raise UsageError(f"카테고리 {args.category}가 issue-db.config.yaml categories에 없습니다 ({', '.join(keys)}).")
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    except ValueError as exc:
        raise UsageError(f"--as-of는 YYYY-MM-DD 형식이어야 합니다: {args.as_of}") from exc
    try:
        items = Review(db, args.category, as_of, plugin_root, defaults).run()
    except db_regress.UsageError as exc:
        raise UsageError(str(exc)) from exc
    head = history._git(Path(root), "rev-parse", "HEAD") if history.is_repo(Path(root)) else None
    manual = sum(1 for f in db.feedback if f.get("decision") == "manual")
    return {
        "db": str(root),
        "head": head.strip() if head else None,
        "as_of": as_of.isoformat(),
        "category": args.category,
        "owners": _owners(Path(root), keys),
        "thresholds": {**DEFAULTS, **(db.config.get("quality") or {}),
                       "android_versions_supported": db.config.get("android_versions_supported") or []},
        "feedback": {"total": len(db.feedback), "manual": manual, "used_for_acceptance": len(db.feedback) - manual},
        "summary": {i["key"]: i["count"] for i in items},
        "items": items,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db_review.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("category", nargs="?", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--out", default=None, help="Markdown 리포트를 쓸 파일")
    parser.add_argument("--as-of", default=None, help="기준일 (기본: 오늘)")
    parser.add_argument("--json", action="store_true", help="stdout에 JSON")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    plugin_root = Path(args.plugin_root) if args.plugin_root else site_defaults.plugin_root()
    try:
        report = run(args, defaults, plugin_root)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    text = render(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        report["out"] = str(out)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    elif not args.out:
        print(text, end="")
    else:
        print(json.dumps({"out": str(args.out), "summary": report["summary"]}, ensure_ascii=False))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
