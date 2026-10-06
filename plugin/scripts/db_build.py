#!/usr/bin/env python3
"""db_build.py — 생성 파일과 로컬 캐시 (03-issue-db.md §5.2·§5.6, 06-collaboration.md §6.5·§6.7·§6.8).

    db_build.py [--db <path>] (--write | --verify [--staged] | --preview <out_dir> | --cache-only)

생성 파일 (사람이 고치지 않는다)
- `README.md`: 전체 인덱스 (§5.6)
- `<category>/README.md`: 카테고리 상세판 (증상 시그니처 요약, `code_refs`, `android_versions`)
- `STATS.md`: 통계 (§6.7, 수락률은 §6.5대로 `decision: manual` 제외)
- `parser-rules/CHANGELOG.md`: 규칙 항목의 이력 필드(`added_for`, `added_on`, `reason`)
- `.cache/compiled.json`: 매칭 캐시 (§6.8, 커밋하지 않는다)

결정성 (§5.2): 현재 시각을 쓰지 않는다. 기준일은 이슈 DB 안의 가장 최근 Jira `date`다.
정렬은 카테고리 `categories` 순서, 유형·원인은 ID 순, Jira는 `date` 내림차순 후 키 오름차순.
비율은 소수 둘째 자리 문자열, 줄 끝 LF, 파일 끝 개행 1개, UTF-8. 발생일은 `occurred_on`
(없으면 `date`)이라 과거 이슈를 한꺼번에 기록해도 최근 건수·급증에 몰리지 않는다.

모드
- `--write`: 생성 파일과 캐시를 쓴다. `generator_version`이 플러그인 `GENERATOR_VERSION`과
  다르면 종료 코드 2.
- `--verify [--staged]`: 생성 결과가 워킹 트리(`--staged`면 index)의 파일과 같은지 본다.
  다르면 목록과 종료 코드 1.
- `--preview <out_dir>`: 생성 파일을 `<out_dir>`에 쓴다. 워킹 트리는 바꾸지 않는다.
- `--cache-only`: 캐시만 쓴다. 다른 파일은 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import dbpath, failedstep, gitscope, issuedb, quality, site_defaults, yamlio  # noqa: E402
from common import compiled as compiled_cache  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from common.versions import GENERATOR_VERSION  # noqa: E402

HEADER = "> 자동 생성 파일입니다. 직접 수정하지 마세요. (`db_build.py`, generator v{g})"
EMPTY_CATEGORY = "아직 등록된 이슈가 없습니다."
FAILED_STEP_TOP = 3          # 카테고리 README "자주 실패한 스텝" 줄에 보이는 개수
FAILED_STEP_CLIP = 80
RULE_FILES = (("tags.yaml", "tags"), ("ril.yaml", "requests"), ("ril.yaml", "unsolicited"),
              ("extractors.yaml", "extractors"))


class UsageError(Exception):
    pass


# -- 공통 -------------------------------------------------------------------------


def _cell(text) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ").strip()


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.2f}" if den else "-"


def _jira_sort_key(record: dict):
    key = str(record.get("key", ""))
    match = re.match(r"^(.*?)(\d+)$", key)
    natural = (match.group(1), int(match.group(2))) if match else (key, 0)
    return (_neg_date(str(record.get("date", ""))), natural)


def _neg_date(value: str):
    try:
        return -date.fromisoformat(value[:10]).toordinal()
    except ValueError:
        return 0


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class Context:
    """생성에 필요한 값을 한 번만 계산한다."""

    def __init__(self, db: issuedb.IssueDb):
        self.db = db
        self.config = db.config
        self.categories = [c for c in self.config.get("categories") or [] if isinstance(c, dict)]
        self.base_url = str(self.config.get("jira_base_url") or "")
        self.inline_max = int((self.config.get("readme") or {}).get("jira_inline_max", 3))
        self.jira = sorted(db.jira, key=_jira_sort_key)
        dates = [d for d in (_day(r.get("date")) for r in self.jira) if d]
        self.base = max(dates) if dates else None
        self.types = sorted(db.types, key=lambda t: t.id)
        self.causes = {c.id: c for t in self.types for c in t.causes}

    @property
    def base_text(self) -> str:
        return self.base.isoformat() if self.base else "-"

    def header(self) -> list[str]:
        return [HEADER.format(g=GENERATOR_VERSION)]

    def link(self, key: str) -> str:
        return f"[{key}]({self.base_url}{key})" if self.base_url else key

    def type_rel(self, itype: issuedb.IssueType) -> str:
        return itype.path.relative_to(self.db.root).as_posix()

    def types_of(self, category: str, active: bool = True) -> list[issuedb.IssueType]:
        return [t for t in self.types if t.category == category and (t.active or not active)]

    def jira_of(self, cause_id: str) -> list[dict]:
        return [r for r in self.jira if str(r.get("cause")) == cause_id]

    def unresolved_of(self, itype: issuedb.IssueType) -> list[dict]:
        return [r for r in self.jira if r["_type"] == itype.id and str(r.get("cause")) == "unresolved"]



# -- README 셀 --------------------------------------------------------------------


def _cause_cell(ctx: Context, cause: issuedb.Cause) -> str:
    text = _cell(cause.title)
    related = [str(r) for r in cause.raw.get("related") or []]
    if related:
        text += " ↔ " + ", ".join(related)
    if cause.raw.get("cp_evidence"):
        text += " · CP 근거"
    if cause.pending:
        text += " · 시그니처 없음"
    return text


def _resolution_cell(cause: issuedb.Cause) -> str:
    text = _cell(cause.raw.get("resolution"))
    if (cause.raw.get("resolution_verification") or {}).get("status") != "verified":
        text += " ⚠ 미검증"
    return text


def _fix_cell(cause: issuedb.Cause) -> str:
    fix = cause.raw.get("fix") or {}
    status = fix.get("status") or "-"
    if status == "fix-submitted":
        items = [f"{f.get('branch')}" + (f":{f['build']}" if f.get("build") else "")
                 for f in fix.get("fixed_in") or [] if isinstance(f, dict)]
        return f"fix-submitted ⏳ {', '.join(items)}".strip()
    if status == "fixed":
        build = (fix.get("verification") or {}).get("build") or "-"
        return f"fixed ✅ {build} 검증"
    return status


def _jira_cell(ctx: Context, records: list[dict], itype: issuedb.IssueType, base_rel: str) -> str:
    if not records:
        return "0건"
    shown = ", ".join(ctx.link(str(r["key"])) for r in records[: ctx.inline_max])
    text = f"{len(records)}건: {shown}"
    if len(records) > ctx.inline_max:
        text += f", … [전체]({base_rel}jira/)"
    return text


def _unresolved_line(ctx: Context, itype: issuedb.IssueType) -> list[str]:
    records = ctx.unresolved_of(itype)
    if not records:
        return []
    return ["", "원인 미확정: " + ", ".join(ctx.link(str(r["key"])) for r in records)]


def _failed_steps_line(ctx: Context, itype: issuedb.IssueType) -> list[str]:
    """유형 Jira 기록의 `failed_step`(선택)을 공백·대소문자 무시로 묶어 자주 나온 순으로 보여준다.
    하나도 없으면 아무것도 내지 않는다(기존 README가 바뀌지 않는다). 결정적이다(03-issue-db.md §5.2)."""
    groups: dict[str, list[str]] = {}
    for r in ctx.jira:
        step = r.get("failed_step")
        if r["_type"] == itype.id and step and str(step).strip():
            groups.setdefault(failedstep.group_key(step), []).append(str(step))
    if not groups:
        return []
    top = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:FAILED_STEP_TOP]
    cells = []
    for _, originals in top:
        shown = " ".join(min(originals).split())
        if len(shown) > FAILED_STEP_CLIP:
            shown = shown[: FAILED_STEP_CLIP - 1] + "…"
        cells.append(f"{_cell(shown)} ({len(originals)}건)")
    return ["", "- 자주 실패한 스텝: " + "; ".join(cells)]


def _signature_summary(sig: dict) -> str:
    parts = []
    for item in sig.get("must_event") or []:
        fields = item.get("fields") or {}
        text = f"event `{item.get('event')}`"
        if fields:
            text += " (" + ", ".join(f"{k}=`{v}`" for k, v in sorted(fields.items())) + ")"
        parts.append(text)
    for item in sig.get("must_match") or []:
        pattern = item.get("pattern") if isinstance(item, dict) else item
        parts.append(f"match `{_cell(pattern)}`")
    for pattern in sig.get("must_not_match") or []:
        parts.append(f"not `{_cell(pattern)}`")
    extra = [f"window {sig.get('window_sec')}s"]
    if sig.get("sequence"):
        extra.append("sequence " + " → ".join(sig["sequence"]))
    if sig.get("same_phone") is False:
        extra.append("슬롯 무관")
    return f"`{sig.get('id')}`: " + "; ".join(parts) + " — " + ", ".join(extra)


def _versions(values) -> str:
    return ", ".join(str(v) for v in values) if values else "전 버전"


def _code_cell(cause: issuedb.Cause) -> str:
    refs = []
    for ref in cause.raw.get("code_refs") or []:
        if not isinstance(ref, dict):
            continue
        text = f"`{_cell(ref.get('ref'))}`"
        if ref.get("symbol"):
            text += f" `{_cell(ref['symbol'])}`"
        if ref.get("android_versions"):
            text += f" ({_versions(ref['android_versions'])})"
        refs.append(text)
    return "<br>".join(refs) if refs else "-"


# -- README ---------------------------------------------------------------------


def readme(ctx: Context) -> str:
    schema = ctx.config.get("schema_version", "-")
    out = ["# Telephony Issue DB", "", *ctx.header(),
           f"> 기준일: {ctx.base_text} · schema v{schema} · [통계](STATS.md) · "
           "[시작하기](docs/getting-started.md) · [기여 방법](CONTRIBUTING.md)", "",
           "## 요약", "",
           "| 카테고리 | 이슈 유형 | 원인 | Jira | 수정 필요(open) |", "|---|---|---|---|---|"]
    for cat in ctx.categories:
        types = ctx.types_of(cat["key"])
        causes = [c for t in types for c in t.causes if c.active]
        jira = [r for r in ctx.jira if r["_type"] in {t.id for t in ctx.types if t.category == cat["key"]}]
        open_ = [c for c in causes if (c.raw.get("fix") or {}).get("status") == "open"]
        out.append(f"| [{cat['name']}](#{str(cat['name']).lower()}) | {len(types)} | {len(causes)} | "
                   f"{len(jira)} | {len(open_)} |")

    recent = ctx.jira[:10]
    out += ["", f"## 최근 추가 ({len(recent)}건)", ""]
    if recent:
        out += ["| 날짜 | Jira | 분류 |", "|---|---|---|"]
        for r in recent:
            cause = ctx.causes.get(str(r.get("cause")))
            label = f"{cause.id} {_cell(cause.title)}" if cause else f"{r['_type']} 원인 미확정"
            out.append(f"| {r.get('date')} | {ctx.link(str(r['key']))} | {label} |")
    else:
        out.append("아직 기록된 Jira가 없습니다.")
    out += ["", "---"]

    for cat in ctx.categories:
        out += ["", f"## {cat['name']}", ""]
        types = ctx.types_of(cat["key"])
        if not types:
            out.append(EMPTY_CATEGORY)
            continue
        for i, itype in enumerate(types, 1):
            rel = ctx.type_rel(itype)
            out += [f"### {i}. [{_cell(itype.title)}]({rel}/type.md) `{itype.id}`", "",
                    _cell(itype.raw.get("summary")), "",
                    "| # | 원인 | 해결책 | 유형 | 수정 상태 | Jira |", "|---|---|---|---|---|---|"]
            for j, cause in enumerate([c for c in itype.causes if c.active], 1):
                out.append(f"| {i}-{j} | {_cause_cell(ctx, cause)} | {_resolution_cell(cause)} | "
                           f"{_cell(cause.raw.get('resolution_type'))} | {_fix_cell(cause)} | "
                           f"{_jira_cell(ctx, ctx.jira_of(cause.id), itype, rel + '/')} |")
            out += _unresolved_line(ctx, itype)
            out.append("")
        if out[-1] == "":
            out.pop()

    out += ["", "## 보관", ""]
    archived = []
    for itype in ctx.types:
        if not itype.active:
            archived.append((itype.id, itype.title, itype.status))
        for cause in itype.causes:
            if not cause.active:
                archived.append((cause.id, cause.title, cause.status))
    if archived:
        out += ["| ID | 제목 | 상태 | 새 ID |", "|---|---|---|---|"]
        for ident, title, status in sorted(archived):
            new = status.split(":", 1)[1] if status.startswith("merged-into:") else "-"
            out.append(f"| {ident} | {_cell(title)} | {status.split(':', 1)[0]} | {new} |")
    else:
        out.append("없음")
    return "\n".join(out) + "\n"


def category_readme(ctx: Context, cat: dict) -> str:
    out = [f"# {cat['name']}", "", *ctx.header(),
           f"> 기준일: {ctx.base_text} · [전체 인덱스](../README.md)", ""]
    types = ctx.types_of(cat["key"])
    if not types:
        out.append(EMPTY_CATEGORY)
        return "\n".join(out) + "\n"
    for i, itype in enumerate(types, 1):
        rel = itype.path.name
        out += [f"## {i}. [{_cell(itype.title)}]({rel}/type.md) `{itype.id}`", "",
                _cell(itype.raw.get("summary")), ""]
        if itype.raw.get("secondary_categories"):
            out += [f"- 부 카테고리: {', '.join(itype.raw['secondary_categories'])}"]
        out += ["- 증상 시그니처:"]
        out += [f"  - {_signature_summary(sig)}" for sig in itype.raw.get("symptom_signatures") or []]
        out += ["", "| # | 원인 | 해결책 | 유형 | 수정 상태 | Jira | Android | 코드 |",
                "|---|---|---|---|---|---|---|---|"]
        for j, cause in enumerate([c for c in itype.causes if c.active], 1):
            out.append(f"| {i}-{j} | {_cause_cell(ctx, cause)} | {_resolution_cell(cause)} | "
                       f"{_cell(cause.raw.get('resolution_type'))} | {_fix_cell(cause)} | "
                       f"{_jira_cell(ctx, ctx.jira_of(cause.id), itype, rel + '/')} | "
                       f"{_versions(cause.raw.get('android_versions'))} | {_code_cell(cause)} |")
        out += _unresolved_line(ctx, itype)
        out += _failed_steps_line(ctx, itype)
        out.append("")
    if out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


# -- STATS ------------------------------------------------------------------------


def _count_window(ctx: Context, records: list[dict], lo: int, hi: int) -> int:
    return quality.count_window(records, ctx.base, lo, hi)


def stats(ctx: Context) -> str:
    qcfg = ctx.config.get("quality") or {}
    min_samples = int(qcfg.get("min_samples", 5))
    surge_ratio = float(qcfg.get("surge_ratio", 2.0))
    active_causes = [c for t in ctx.types if t.active for c in t.causes if c.active]
    out = ["# 통계", "", *ctx.header(),
           f"> 기준일: {ctx.base_text} (가장 최근 Jira 기록의 `date`). 발생일은 `occurred_on`, 없으면 `date`.",
           "", "## 건수", "",
           "| 카테고리 | 유형 | 원인 | 누적 | 최근 30일 | 최근 90일 |", "|---|---|---|---|---|---|"]
    total = [0, 0, 0, 0, 0]
    for cat in ctx.categories:
        types = ctx.types_of(cat["key"])
        ids = {t.id for t in ctx.types if t.category == cat["key"]}
        records = [r for r in ctx.jira if r["_type"] in ids]
        row = [len(types), sum(1 for t in types for c in t.causes if c.active), len(records),
               _count_window(ctx, records, 0, 30), _count_window(ctx, records, 0, 90)]
        total = [a + b for a, b in zip(total, row)]
        out.append(f"| {cat['name']} | " + " | ".join(map(str, row)) + " |")
    out.append("| **합계** | " + " | ".join(f"**{n}**" for n in total) + " |")

    out += ["", "### 유형별", "", "| 유형 | 제목 | 누적 | 최근 30일 | 최근 90일 |", "|---|---|---|---|---|"]
    for itype in ctx.types:
        if itype.active:
            records = [r for r in ctx.jira if r["_type"] == itype.id]
            out.append(f"| {itype.id} | {_cell(itype.title)} | {len(records)} | "
                       f"{_count_window(ctx, records, 0, 30)} | {_count_window(ctx, records, 0, 90)} |")

    out += ["", "### 원인별", "", "| 원인 | 제목 | 누적 | 최근 30일 | 최근 90일 |", "|---|---|---|---|---|"]
    rows = []
    for itype in ctx.types:
        if not itype.active:
            continue
        for cause in itype.causes:
            if cause.active:
                records = ctx.jira_of(cause.id)
                rows.append((cause.id, cause.title, records))
        unresolved = ctx.unresolved_of(itype)
        if unresolved:
            rows.append((f"{itype.id}:unresolved", "원인 미확정", unresolved))
    for ident, title, records in rows:
        out.append(f"| {ident} | {_cell(title)} | {len(records)} | {_count_window(ctx, records, 0, 30)} | "
                   f"{_count_window(ctx, records, 0, 90)} |")

    top = sorted(((c.id, c.title, _count_window(ctx, ctx.jira_of(c.id), 0, 90)) for c in active_causes),
                 key=lambda x: (-x[2], x[0]))
    top = [t for t in top if t[2] > 0][:10]
    out += ["", "## Top 10 원인 (최근 90일)", ""]
    if top:
        out += ["| 순위 | 원인 | 제목 | 최근 90일 |", "|---|---|---|---|"]
        out += [f"| {i} | {ident} | {_cell(title)} | {n} |" for i, (ident, title, n) in enumerate(top, 1)]
    else:
        out.append("없음")

    out += ["", "## 분포"]
    for field_name, label in (("model", "모델"), ("sw", "SW"), ("android_version", "Android 버전"),
                              ("carrier", "캐리어")):
        counts = Counter(str(r.get(field_name)) if r.get(field_name) not in (None, "") else "(없음)"
                         for r in ctx.jira)
        out += ["", f"### {label}", ""]
        if counts:
            out += ["| 값 | 건수 |", "|---|---|"]
            out += [f"| {_cell(k)} | {v} |" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        else:
            out.append("없음")

    open_causes = sorted(((c, len(ctx.jira_of(c.id))) for c in active_causes
                          if (c.raw.get("fix") or {}).get("status") == "open"), key=lambda x: (-x[1], x[0].id))
    out += ["", "## 수정 상태", "", "open 원인 (Jira 건수 순, 근본 수정 후보):", ""]
    if open_causes:
        out += ["| 원인 | 제목 | Jira |", "|---|---|---|"]
        out += [f"| {c.id} | {_cell(c.title)} | {n} |" for c, n in open_causes]
    else:
        out.append("없음")

    out += ["", "## 급증 원인", "",
            f"최근 30일 발생이 이전 90일 월평균 × {surge_ratio:g} 이상이고 2건 이상인 원인 (06-collaboration.md §6.6).", ""]
    surges = []
    for cause in active_causes:
        hit = quality.surge(ctx.jira_of(cause.id), ctx.base, surge_ratio)
        if hit:
            surges.append((cause.id, hit["recent"], hit["monthly"]))
    if surges:
        out += ["| 원인 | 최근 30일 | 이전 90일 월평균 |", "|---|---|---|"]
        out += [f"| {ident} | {n} | {m:.2f} |" for ident, n, m in sorted(surges)]
    else:
        out.append("없음")

    acceptance = issuedb.acceptance(ctx.db.feedback)
    quality_rows = sorted(((k, a, t) for k, (a, t) in acceptance.items()), key=lambda x: (x[1] / x[2], x[0]))[:10]
    out += ["", "## 시그니처 품질 (수락률 하위 10개)", "",
            "수락률 = 1위로 제시된 피드백 중 `decision: accepted` 비율. 수동 기록(`decision: manual`)은 뺀다.", ""]
    if quality_rows:
        out += ["| 시그니처 | 1위 제시 | 수락 | 수락률 | 표본 충분 |", "|---|---|---|---|---|"]
        out += [f"| `{k}` | {t} | {a} | {_ratio(a, t)} | {'예' if t >= min_samples else '아니오'} |"
                for k, a, t in quality_rows]
    else:
        out.append("없음")

    verified = sum(1 for c in active_causes
                   if (c.raw.get("resolution_verification") or {}).get("status") == "verified")
    waiting = sorted(c.id for c in active_causes if (c.raw.get("fix") or {}).get("status") == "fix-submitted")
    results = Counter()
    for cause in active_causes:
        fix = cause.raw.get("fix") or {}
        if (fix.get("verification") or {}).get("result"):
            results[fix["verification"]["result"]] += 1
        for item in fix.get("verification_history") or []:
            if isinstance(item, dict) and item.get("result"):
                results[item["result"]] += 1
    out += ["", "## 검증 현황", "",
            f"- 해결책 검증률: {_ratio(verified, len(active_causes))} ({verified}/{len(active_causes)})",
            f"- fix-submitted 대기: {', '.join(waiting) if waiting else '없음'}",
            f"- verify-fix 기록: 통과 {results['passed']} · 부분 통과 {results['partial']} · 실패 {results['failed']}"
            f" · 되돌림 {results['reverted']}"]

    months: dict[str, list[int]] = {}
    for record in ctx.db.feedback:
        month = str(record.get("date", ""))[:7]
        if not month:
            continue
        entry = months.setdefault(month, [0, 0])
        entry[1 if record.get("decision") == "manual" else 0] += 1
    people = {str(r.get("analyzed_by")) for r in ctx.jira if r.get("analyzed_by")}
    people |= {str(f.get("by")) for f in ctx.db.feedback if f.get("by")}
    out += ["", "## 기여 현황", ""]
    if months:
        out += ["| 월 | 분석 | 수동 기록 |", "|---|---|---|"]
        out += [f"| {m} | {a} | {r} |" for m, (a, r) in sorted(months.items(), reverse=True)]
        out.append("")
    out.append(f"기여자 수: {len(people)}")

    pending = sorted(c.id for c in active_causes if c.pending)
    have_fixture = quality.positive_fixture_causes(ctx.db)
    no_fixture = sorted(c.id for c in active_causes if quality.no_fixture(c, have_fixture))
    no_trace = sorted(c.id for c in active_causes if quality.no_trace(c))
    out += ["", "## 품질 점검", "",
            f"- 시그니처 없는 원인: {len(pending)}" + (f" ({', '.join(pending)})" if pending else ""),
            f"- fixture 없는 원인: {len(no_fixture)}" + (f" ({', '.join(no_fixture)})" if no_fixture else ""),
            f"- fixed 전환 불가(흔적 시그니처 없음): {len(no_trace)}" + (f" ({', '.join(no_trace)})" if no_trace else "")]
    return "\n".join(out) + "\n"


# -- CHANGELOG ----------------------------------------------------------------------


def changelog(ctx: Context) -> str:
    rows = []
    order = {name: i for i, (name, _) in enumerate(RULE_FILES)}
    for file_name, section in RULE_FILES:
        path = ctx.db.root / "parser-rules" / file_name
        if not path.is_file():
            continue
        for item in (yamlio.load(path) or {}).get(section) or []:
            if not isinstance(item, dict):
                continue
            key = item.get("id") or item.get("name") or item.get("tag") or item.get("tag_regex")
            label = f"{file_name} `{section}`" if file_name == "ril.yaml" else file_name
            rows.append((str(item.get("added_on", "")), order[file_name], section, str(key),
                         label, str(item.get("added_for", "")), str(item.get("reason", ""))))
    rows.sort(key=lambda r: (_neg_date(r[0]), r[1], r[2], r[3]))
    out = ["# parser-rules 변경 이력", "", *ctx.header(),
           "> 규칙 항목의 이력 필드(`added_for`, `added_on`, `reason`)에서 만든다 (04-parser-matching.md §5.8 (2)).",
           "", "| 날짜 | 파일 | 항목 | 추가 대상 | 사유 |", "|---|---|---|---|---|"]
    out += [f"| {r[0]} | {r[4]} | `{_cell(r[3])}` | {_cell(r[5])} | {_cell(r[6])} |" for r in rows]
    return "\n".join(out) + "\n"


# -- 모드 -------------------------------------------------------------------------


def generate(db: issuedb.IssueDb) -> dict[str, str]:
    """생성 파일 `{DB 기준 상대 경로: 내용}`."""
    ctx = Context(db)
    files = {"README.md": readme(ctx), "STATS.md": stats(ctx), "parser-rules/CHANGELOG.md": changelog(ctx)}
    for cat in ctx.categories:
        files[f"{cat['key']}/README.md"] = category_readme(ctx, cat)
    return files


def _check_generator(db: issuedb.IssueDb) -> None:
    have = db.config.get("generator_version")
    if have != GENERATOR_VERSION:
        raise UsageError(
            f"생성기 버전이 다릅니다: 이슈 DB generator_version={have}, 플러그인 {GENERATOR_VERSION}. "
            "플러그인을 업데이트하거나 메인테이너가 버전을 올리는 PR을 만든다 (06-collaboration.md §6.4)."
        )


def _load(root: Path) -> issuedb.IssueDb:
    try:
        return issuedb.load(root)
    except issuedb.IssueDbError as exc:
        raise UsageError(str(exc)) from exc


def run(args, defaults: dict) -> tuple[dict, int]:
    try:
        repo = dbpath.resolve(args.db)
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc

    if args.cache_only:
        db = _load(repo)
        path = compiled_cache.write(db, compiled_cache.environment(defaults), GENERATOR_VERSION)
        return {"mode": "cache-only", "cache": str(path)}, OK

    if args.preview:
        db = _load(repo)
        out_dir = Path(args.preview)
        files = generate(db)
        for rel, text in files.items():
            target = out_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
        return {"mode": "preview", "out": str(out_dir), "files": sorted(files)}, OK

    if args.verify:
        workdir = None
        try:
            if args.staged:
                workdir = Path(tempfile.mkdtemp(prefix="tt-build-index-"))
                root = gitscope.materialize_index(repo, workdir / "db")
            else:
                root = repo
            db = _load(root)
            _check_generator(db)
            files = generate(db)
            report = []
            for rel, text in sorted(files.items()):
                path = root / rel
                if not path.is_file():
                    report.append({"path": rel, "status": "missing"})
                elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
                    report.append({"path": rel, "status": "different"})
        except gitscope.GitError as exc:
            raise UsageError(str(exc)) from exc
        finally:
            if workdir is not None:
                shutil.rmtree(workdir, ignore_errors=True)
        return ({"mode": "verify", "staged": bool(args.staged), "problems": report,
                 "files": sorted(files)}, CHECK_FAILED if report else OK)

    db = _load(repo)
    _check_generator(db)
    files = generate(db)
    written = []
    for rel, text in sorted(files.items()):
        path = repo / rel
        old = path.read_text(encoding="utf-8") if path.is_file() else None
        if old != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            written.append(rel)
    cache = compiled_cache.write(db, compiled_cache.environment(defaults), GENERATOR_VERSION)
    return {"mode": "write", "files": sorted(files), "changed": written, "cache": str(cache)}, OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db_build.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--preview", metavar="out_dir")
    mode.add_argument("--cache-only", action="store_true")
    parser.add_argument("--staged", action="store_true", help="--verify와 함께: index 기준")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    try:
        if args.staged and not args.verify:
            raise UsageError("--staged는 --verify와 함께 쓴다.")
        result, code = run(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for problem in result.get("problems") or []:
        print(f"생성 파일이 다름: {problem['path']} ({problem['status']}) — db_build.py --write", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
