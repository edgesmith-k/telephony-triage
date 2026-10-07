"""규칙 변경 계산과 의존 그래프 (05-verification.md §5.12 (1) "검사 대상 계산", contracts.md §3.2 `db_verify.py` 세부).

기준 트리(base)와 현재 트리를 **의미 단위로** 비교한다. 텍스트 diff가 아니라 시그니처(소유자·종류·id)와
parser-rules 항목(키)의 기능 필드를 비교하므로 `--plan`(계획을 적용한 트리), `--changed`, `--staged`가 같은
방법으로 대상을 정한다.

- 바뀐 시그니처: 현재 트리에 있고 base에 없거나 내용이 다른 시그니처. 새 원인·유형의 시그니처는 전부 바뀐 것이다.
  지운 시그니처는 대상이 아니다(좁히는 변경은 R4가 본다).
- 바뀐 parser-rules 항목: 키별 기능 필드(이력 필드 `added_for`·`added_on`·`reason` 제외)가 다르거나 추가·삭제된 항목.
- 의존 그래프(보수적): 시그니처 `must_event` → 그 이벤트를 만드는 extractor, extractor `tag`/`tag_regex` → tags 항목,
  `must_match`의 RIL 요청 이름·태그 문자열 → ril·tags 항목. 바뀐 항목에 닿는 시그니처는 내용이 같아도 바뀐 것으로 본다.
  - tags 항목 변경: 그 태그를 쓰는 extractor의 이벤트, 패턴에 그 태그 이름이 들어 있는 `must_match`,
    `tag_regex` 항목이면 같은 카테고리 소유자의 `must_match` 전부.
  - ril 항목 변경: 패턴에 그 이름이 들어 있는 `must_match`, 엔진이 ril.yaml로 만드는 이벤트(`ril_error` 등)를 쓰는
    `must_event` 전부.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import issuedb, yamlio
from .parser_rules import RESERVED_EVENTS

HISTORY_FIELDS = ("added_for", "added_on", "reason")
SIG_KINDS = {"symptom": "symptom_signatures", "cause": "signatures", "recovery": "recovery_signatures",
             "scenario": "scenario_signatures"}
RULE_SECTIONS = {"tags": ("tags.yaml", "tags", ("tag", "tag_regex")),
                 "requests": ("ril.yaml", "requests", ("name",)),
                 "unsolicited": ("ril.yaml", "unsolicited", ("name",)),
                 "extractors": ("extractors.yaml", "extractors", ("id",))}


def _canon(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _functional(rule: dict) -> dict:
    return {k: v for k, v in rule.items() if k not in HISTORY_FIELDS}


@dataclass
class SigRef:
    owner: str          # 유형 ID(symptom) 또는 원인 ID
    kind: str           # symptom | cause | recovery | scenario
    id: str
    raw: dict
    type_id: str
    category: str

    @property
    def key(self) -> str:
        return f"{self.owner}/{self.id}"


@dataclass
class State:
    sigs: dict[tuple[str, str, str], SigRef] = field(default_factory=dict)   # (owner, kind, id)
    rules: dict[tuple[str, str], dict] = field(default_factory=dict)          # (section, key) → 항목
    resolutions: dict[str, str] = field(default_factory=dict)                 # 원인 ID → resolution
    causes: dict[str, bool] = field(default_factory=dict)                     # 원인 ID → signatures_pending
    present: bool = True


def _rules_state(root: Path) -> dict[tuple[str, str], dict]:
    out = {}
    for section, (fname, top, keys) in RULE_SECTIONS.items():
        path = root / "parser-rules" / fname
        if not path.is_file():
            continue
        try:
            doc = yamlio.load(path) or {}
        except Exception:  # noqa: BLE001 — 깨진 규칙은 parser_rules.load가 보고한다
            continue
        for item in doc.get(top) or []:
            if not isinstance(item, dict):
                continue
            key = next((str(item[k]) for k in keys if item.get(k) is not None), None)
            if key is not None:
                out[(section, key)] = item
    return out


def load_state(root: Path | None) -> State:
    """트리 하나의 시그니처·규칙·해결책. `root`가 없거나 이슈 DB가 아니면 빈 상태(전부 새것으로 본다)."""
    if root is None or not (root / issuedb.CONFIG).is_file():
        return State(present=False)
    db = issuedb.load(root)
    state = State(rules=_rules_state(root))
    for itype in db.types:
        for raw in itype.raw.get("symptom_signatures") or []:
            if isinstance(raw, dict) and raw.get("id"):
                ref = SigRef(itype.id, "symptom", str(raw["id"]), raw, itype.id, itype.category)
                state.sigs[(ref.owner, ref.kind, ref.id)] = ref
        for cause in itype.causes:
            state.resolutions[cause.id] = str(cause.raw.get("resolution") or "")
            state.causes[cause.id] = cause.pending
            for kind in ("cause", "recovery", "scenario"):
                for raw in cause.raw.get(SIG_KINDS[kind]) or []:
                    if isinstance(raw, dict) and raw.get("id"):
                        ref = SigRef(cause.id, kind, str(raw["id"]), raw, itype.id, itype.category)
                        state.sigs[(ref.owner, ref.kind, ref.id)] = ref
    return state


@dataclass
class Change:
    sig: SigRef
    why: list[str]      # "new" | "changed" | "depends:<section>:<key>"


@dataclass
class Diff:
    sigs: dict[tuple[str, str, str], Change] = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)       # [{section, key, change: added|removed|changed}]
    resolutions: list[str] = field(default_factory=list)  # resolution이 바뀐 기존 원인

    @property
    def rules_changed(self) -> bool:
        return bool(self.rules)


def _tag_names(rule: dict) -> tuple[str | None, str | None]:
    return rule.get("tag"), rule.get("tag_regex")


def _extractor_uses_tag(extractor: dict, tag_rule: dict) -> bool:
    etag, eregex = _tag_names(extractor)
    ttag, tregex = _tag_names(tag_rule)
    if etag and ttag:
        return etag == ttag
    if etag and tregex:
        try:
            return bool(re.search(tregex, etag))
        except re.error:
            return True
    if eregex and tregex:
        return eregex == tregex
    if eregex and ttag:
        try:
            return bool(re.search(eregex, ttag))
        except re.error:
            return True
    return False


def _must_match_texts(raw: dict) -> list[str]:
    out = []
    for item in raw.get("must_match") or []:
        out.append(item if isinstance(item, str) else str((item or {}).get("pattern") or ""))
    return out


def _events(raw: dict) -> set[str]:
    return {str(item.get("event")) for item in raw.get("must_event") or [] if isinstance(item, dict)}


def compute(base: State, cur: State) -> Diff:
    diff = Diff()
    for k, ref in cur.sigs.items():
        old = base.sigs.get(k)
        if old is None:
            diff.sigs[k] = Change(ref, ["new"])
        elif _canon(old.raw) != _canon(ref.raw):
            diff.sigs[k] = Change(ref, ["changed"])
    for cid, text in cur.resolutions.items():
        if cid in base.resolutions and base.resolutions[cid] != text:
            diff.resolutions.append(cid)

    changed_rules: dict[tuple[str, str], list[dict]] = {}
    for key in sorted(set(base.rules) | set(cur.rules)):
        a, b = base.rules.get(key), cur.rules.get(key)
        if a is None:
            change = "added"
        elif b is None:
            change = "removed"
        elif _canon(_functional(a)) != _canon(_functional(b)):
            change = "changed"
        else:
            continue
        diff.rules.append({"section": key[0], "key": key[1], "change": change})
        changed_rules[key] = [r for r in (a, b) if r is not None]

    # 의존 그래프 ------------------------------------------------------------------------
    events: dict[str, str] = {}          # 영향 받는 이벤트 → 사유
    match_literals: dict[str, str] = {}  # must_match 패턴에 들어 있으면 영향 → 사유
    match_categories: dict[str, str] = {}
    ril_events = False
    extractors_now = [r for (s, _), r in cur.rules.items() if s == "extractors"]
    for (section, key), versions in changed_rules.items():
        why = f"depends:{section}:{key}"
        if section == "extractors":
            for rule in versions:
                if rule.get("event"):
                    events.setdefault(str(rule["event"]), why)
        elif section == "tags":
            for rule in versions:
                for ext in extractors_now:
                    if ext.get("event") and _extractor_uses_tag(ext, rule):
                        events.setdefault(str(ext["event"]), why)
                if rule.get("tag"):
                    match_literals.setdefault(str(rule["tag"]), why)
                elif rule.get("category"):
                    match_categories.setdefault(str(rule["category"]), why)
        else:  # ril requests / unsolicited
            match_literals.setdefault(key, why)
            ril_events = True
    ril_why = next((f"depends:{s}:{k}" for (s, k) in changed_rules if s in ("requests", "unsolicited")), None)

    for k, ref in cur.sigs.items():
        reasons = []
        for event in sorted(_events(ref.raw)):
            if event in events:
                reasons.append(events[event])
            if ril_events and event in RESERVED_EVENTS:
                reasons.append(ril_why)
        texts = _must_match_texts(ref.raw)
        for literal, why in match_literals.items():
            if any(literal in t for t in texts):
                reasons.append(why)
        if texts and ref.category in match_categories:
            reasons.append(match_categories[ref.category])
        reasons = sorted(set(filter(None, reasons)))
        if not reasons:
            continue
        if k in diff.sigs:
            diff.sigs[k].why += [r for r in reasons if r not in diff.sigs[k].why]
        else:
            diff.sigs[k] = Change(ref, reasons)
    return diff
