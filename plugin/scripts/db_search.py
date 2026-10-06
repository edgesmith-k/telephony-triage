#!/usr/bin/env python3
"""db_search.py — 이슈 DB 검색 (contracts.md §3.2, §renumber 참조, 03-issue-db.md §5.5).

    db_search.py [--db <path>] <keyword|JIRA-KEY|ID> [--limit 20] [--brief] [--format json|markdown]

읽기 전용이다. 질의 종류는 모양으로 정한다.

- 유형 ID(`DATA-001`)·원인 ID(`DATA-001-01`): 그 엔티티. 없는 ID여도 옛 ID 연결을 찾는다.
- Jira 키(`jira_key_regex`): 그 Jira 기록과 소속 원인(또는 유형).
- 그 밖: 키워드 또는 증상 문장. 유형(제목·요약·태그), 원인(제목·설명·해결책), Jira(`note`)에서 대소문자 무시 부분 일치.
  질의 전체의 부분 일치 결과가 먼저(옛 순서 그대로, `phrase: true`), 이어서 **단어별 검색**이 덧붙는다: 질의를 단어로 쪼개
  불용어(`이런 이슈 있었어?`)·조사·부정 접두(`안붙어`)를 떼고, 이슈 DB `GLOSSARY.md`의 `## 검색 별칭`으로 별칭을 더해
  단어마다 위치별 가중치(ID·제목·태그 3 > 요약·원인 설명·해결책 2 > 증상 본문·상위 유형·Jira 1)로 점수를 낸다.
  맞은 단어 수(`matched`)가 최대치의 절반 이상인 것만 남기고(Jira는 최대치만), 맞은 수 > 점수 순으로 보인다.
  이 순위는 검색용이다. 분류·매칭에는 쓰지 않는다.

**옛 ID → 새 ID 연결** (`contracts.md §renumber 참조`)
- `merged-into:` 체인: 병합된 유형·원인은 삭제하지 않고 `status: merged-into:<ID>`를 남긴다. 체인을 끝(active 등)까지
  따라가 `current`로 보여준다. 거꾸로 이 ID로 병합된 엔티티는 `merged_from`.
- `Renumbered: <옛 ID> -> <새 ID>` 트레일러(사후 정리 커밋, 이슈 DB git 이력): 옛 ID는 원래 주인이 계속 쓰므로
  옛 ID 엔티티도 그대로 보이고, 옮겨간 엔티티를 `renumbered[]`와 결과에 함께 보인다. 새 ID로 찾으면
  어디서 옮겨왔는지 보인다.

출력(JSON): `{query, kind: type-id|cause-id|jira|keyword, results[], links[], git_history}`. keyword면 `terms[{term, aliases[]}]`가
더해지고 `results[]` 항목에 `matched[]`, `score`, `phrase`가 붙는다.
`results[]` 항목은 `kind: type|cause|jira`와 유형·원인·해결책·수정 상태·Jira 요약이다. 원인 항목에는
`code_refs[{ref, symbol, android_versions}]`(Step 5 resolve 입력)가 붙는다. 스킬·드라이버는 `--limit 3`으로 부른다.
`links[]`는 `{from, to, via: merged-into|renumbered, commit?, date?}`. 결과가 없어도 종료 코드 0이다.
`--brief`(opt-in, 기본 출력은 그대로): 항목에서 `path`·`chain`·`merged_from`·`code_refs`·`resolution_type`·`signatures_pending`·
`type_title`·`category`와 빈 값·id와 같은 `current`, 최상위 `db`를 뺀다. `links[]`는 그대로. 후보를 훑어볼 때만 쓰고,
`code_refs`나 병합 체인이 필요한 호출(Step 5 resolve 입력 등)에는 붙이지 않는다.
`--format markdown`(opt-in, 기본 `json`)은 `search.md §3` 보여주기 규칙대로 마크다운으로 낸다(전체 결과에서 렌더, `--brief`는 무시,
`--json`과 함께 쓰면 종료 코드 2).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import dbpath, glossary, history, issuedb, quality, site_defaults, typedoc, userconfig  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from common.fixtures import CAUSE_ID_RE, TYPE_ID_RE  # noqa: E402

JIRA_SHOWN = 5
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*|[가-힣]+")
PARTICLES = sorted("에서는 에서 에는 으로 이랑 하고 까지 부터 처럼 이나 은 는 이 가 을 를 에 도 로 의 와 과 랑 만".split(),
                   key=len, reverse=True)
STOPWORDS = frozenset("""안 못 안돼 안됨 안되 안돼요 안되요 안되는 돼 됨 되 돼요 됐어 되나 되는 되요 않 않아 않음 않는 이런 저런 그런 이 그 저
이거 그거 저거 거 것 게 이슈 이슈번호 번호 번호들 지라 jira 티켓 있었어 있었나 있었니 있어 있나 있니 있나요 있었나요 있어요 있을까
있을까요 있는지 있었는지 없었어 알려줘 알려 알려주세요 줘 주세요 부탁 부탁해 확인 찾아줘 찾아 찾아봐 봐줘 봐 해줘 비슷한 비슷하게 유사한
같은 관련 관련된 혹시 좀 전에 예전에 과거 과거에 뭐 뭐야 어떤 케이스 사례 문제 현상 증상 경우 때 건 the a an any is are was were be
issue issues ticket tickets similar there have has had did does do we not no number numbers""".split())
WEIGHT_STRONG, WEIGHT_MID, WEIGHT_WEAK = 3, 2, 1
KIND_ORDER = {"type": 0, "cause": 1, "jira": 2}
SYMPTOM_RE = re.compile(r"^## 증상\n(.*?)(?=^## |\Z)", re.M | re.S)
CODE_REF_FIELDS = ("ref", "symbol", "android_versions")   # Step 5 resolve에 필요한 것만 (contracts.md §3.2)


class UsageError(Exception):
    pass


def _jira_key(record: dict):
    return (str(record.get("date", "")), str(record.get("key", "")))


class Searcher:
    def __init__(self, db: issuedb.IssueDb, limit: int):
        self.db = db
        self.limit = limit
        self.types = {t.id: t for t in sorted(db.types, key=lambda t: t.id)}
        self.causes = {c.id: c for t in self.types.values() for c in t.causes}
        self.jira_by_key = {str(r.get("key")): r for r in db.jira}
        self.history = history.History(db.root)
        self.renumbers = self.history.renumbered()
        self._aliases = None
        self._symptom: dict[str, str] = {}

    # 엔티티 요약 ---------------------------------------------------------------------

    def jira_of(self, cause_id: str) -> list[dict]:
        return sorted((r for r in self.db.jira if str(r.get("cause")) == cause_id), key=_jira_key, reverse=True)

    def status_target(self, status: str) -> str | None:
        return status.split(":", 1)[1] if status.startswith("merged-into:") else None

    def chain(self, ident: str) -> tuple[list[str], str]:
        """`merged-into` 체인 `[ident, ..., 끝]`과 끝 ID."""
        seen = [ident]
        while True:
            entity = self.types.get(seen[-1]) or self.causes.get(seen[-1])
            target = self.status_target(entity.status) if entity else None
            if not target or target in seen:
                return seen, seen[-1]
            seen.append(target)

    def merged_from(self, ident: str) -> list[str]:
        out = [t.id for t in self.types.values() if self.status_target(t.status) == ident]
        out += [c.id for c in self.causes.values() if self.status_target(c.status) == ident]
        return sorted(out)

    def type_entry(self, itype: issuedb.IssueType) -> dict:
        chain, current = self.chain(itype.id)
        records = [r for r in self.db.jira if r["_type"] == itype.id]
        newest = sorted(records, key=_jira_key, reverse=True)
        return {
            "kind": "type", "id": itype.id, "category": itype.category, "title": itype.title,
            "status": itype.status, "current": current, "chain": chain, "merged_from": self.merged_from(itype.id),
            "secondary_categories": list(itype.raw.get("secondary_categories") or []),
            "causes": [{"id": c.id, "title": c.title, "status": c.status} for c in itype.causes],
            "unresolved": sorted(str(r.get("key")) for r in records if str(r.get("cause")) == "unresolved"),
            "jira_count": len(records),
            "jira": [str(r.get("key")) for r in newest[:JIRA_SHOWN]],
            "jira_latest": str(newest[0].get("date", "")) if newest else None,
            "path": (itype.path / "type.md").relative_to(self.db.root).as_posix(),
        }

    def cause_entry(self, cause: issuedb.Cause) -> dict:
        chain, current = self.chain(cause.id)
        itype = self.types[cause.type_id]
        fix = quality.fix_of(cause)
        records = self.jira_of(cause.id)
        rv = cause.raw.get("resolution_verification")
        return {
            "kind": "cause", "id": cause.id, "type": cause.type_id, "type_title": itype.title,
            "category": itype.category, "title": cause.title, "status": cause.status,
            "current": current, "chain": chain, "merged_from": self.merged_from(cause.id),
            "signatures_pending": cause.pending,
            "resolution": cause.raw.get("resolution"), "resolution_type": cause.raw.get("resolution_type"),
            "resolution_verification": rv.get("status") if isinstance(rv, dict) else None,
            "fix": {"status": fix.get("status"), "ref": fix.get("ref"), "fixed_in": fix.get("fixed_in") or []},
            "related": [str(r) for r in cause.raw.get("related") or []],
            "secondary_categories": list(itype.raw.get("secondary_categories") or []),
            "code_refs": [{k: ref.get(k) for k in CODE_REF_FIELDS if ref.get(k) not in (None, "", [])}
                          for ref in cause.raw.get("code_refs") or [] if isinstance(ref, dict)],
            "jira": [str(r.get("key")) for r in records[:JIRA_SHOWN]],
            "jira_count": len(records),
            "jira_latest": str(records[0].get("date", "")) if records else None,
            "path": (itype.path / "type.md").relative_to(self.db.root).as_posix(),
        }

    def jira_entry(self, record: dict) -> dict:
        entry = {"kind": "jira", "key": record.get("key"), "cause": record.get("cause"), "type": record["_type"],
                 "date": str(record.get("date", "")), "occurred_on": str(record.get("occurred_on") or "") or None,
                 "note": record.get("note"), "path": record["_rel"]}
        if record.get("failed_step"):
            entry["failed_step"] = record["failed_step"]
        return entry

    def entity_entry(self, ident: str) -> dict | None:
        if ident in self.causes:
            return self.cause_entry(self.causes[ident])
        if ident in self.types:
            return self.type_entry(self.types[ident])
        return None

    # 질의 --------------------------------------------------------------------------

    def links_for(self, entries: list[dict]) -> list[dict]:
        links, seen = [], set()

        def add(link: dict) -> None:
            key = (link["from"], link["to"], link["via"], link.get("commit"))
            if key not in seen:
                seen.add(key)
                links.append(link)

        for entry in entries:
            for a, b in zip(entry.get("chain", []), entry.get("chain", [])[1:]):
                add({"from": a, "to": b, "via": "merged-into"})
            for src in entry.get("merged_from", []):
                add({"from": src, "to": entry["id"], "via": "merged-into"})
        return links

    def renumber_links(self, ident: str) -> list[dict]:
        """`ident`가 옛 ID나 새 ID인 트레일러. 유형 ID면 그 유형 소속 원인 ID의 트레일러도 포함."""
        out = []
        for r in self.renumbers:
            for side in ("from", "to"):
                value = r[side]
                if value == ident or (TYPE_ID_RE.fullmatch(ident) and value.startswith(ident + "-")):
                    out.append({"from": r["from"], "to": r["to"], "via": "renumbered", "commit": r["commit"],
                                "date": r["date"]})
                    break
        return out

    def search(self, query: str) -> dict:
        key_re = re.compile(str(self.db.config.get("jira_key_regex") or r"[A-Z][A-Z0-9]+-\d+"))
        results: list[dict] = []
        renumbered: list[dict] = []
        if CAUSE_ID_RE.fullmatch(query) or TYPE_ID_RE.fullmatch(query):
            kind = "cause-id" if CAUSE_ID_RE.fullmatch(query) else "type-id"
            entry = self.entity_entry(query)
            if entry:
                results.append(entry)
                if entry["current"] != query:
                    target = self.entity_entry(entry["current"])
                    if target:
                        results.append(target)
            renumbered = self.renumber_links(query)
            for link in renumbered:
                other = link["to"] if link["from"] == query else link["from"]
                if other != query and not any(r.get("id") == other for r in results):
                    target = self.entity_entry(other)
                    if target:
                        results.append(target)
            if kind == "type-id" and entry:
                results += [self.cause_entry(self.causes[c["id"]]) for c in entry["causes"]]
        elif key_re.fullmatch(query):
            kind = "jira"
            record = self.jira_by_key.get(query)
            if record:
                results.append(self.jira_entry(record))
                owner = str(record.get("cause"))
                target = self.entity_entry(owner if owner != "unresolved" else record["_type"])
                if target:
                    results.append(target)
                    if target["current"] != target["id"]:
                        final = self.entity_entry(target["current"])
                        if final:
                            results.append(final)
        else:
            kind = "keyword"
            results, terms = self.keyword(query)
        results = results[: self.limit]
        out = {"query": query, "kind": kind}
        if kind == "keyword":
            out["terms"] = [{"term": term, "aliases": aliases} for term, aliases in terms]
        return {**out, "results": results, "links": self.links_for(results) + renumbered,
                "git_history": self.history.enabled}

    def keyword(self, query: str) -> tuple[list[dict], list[tuple[str, list[str]]]]:
        """질의 전체의 부분 일치(옛 동작, 순서 그대로) 뒤에 단어별 검색 결과를 덧붙인다."""
        phrase = self.phrase_pass(query)
        terms = self.tokenize(query)
        seen = {(e["kind"], e.get("id") or e.get("key")) for e in phrase}
        scored = self.term_pass(terms, phrase)
        for entry in phrase:
            entry["phrase"] = True
        extra = [x for x in scored if (x[2]["kind"], x[2].get("id") or x[2].get("key")) not in seen]
        m_max = max([m for m, _, _ in scored] or [0])
        keep = max(1, math.ceil(m_max / 2))
        extra = [x for x in extra if x[0] >= keep and (x[2]["kind"] != "jira" or x[0] == m_max)]
        extra.sort(key=lambda x: (-x[0], -x[1], KIND_ORDER[x[2]["kind"]], str(x[2].get("id") or x[2].get("key"))))
        for _, _, entry in extra:
            entry["phrase"] = False
        return phrase + [e for _, _, e in extra], terms

    def phrase_pass(self, query: str) -> list[dict]:
        needle = query.lower()

        def hit(*values) -> bool:
            return any(needle in str(v).lower() for v in values if v)

        scored: list[tuple[int, str, dict]] = []
        for itype in self.types.values():
            if hit(itype.id, itype.title):
                scored.append((0, itype.id, self.type_entry(itype)))
            elif hit(itype.raw.get("summary"), " ".join(map(str, itype.raw.get("tags") or []))):
                scored.append((2, itype.id, self.type_entry(itype)))
        for cause in self.causes.values():
            if hit(cause.id, cause.title):
                scored.append((1, cause.id, self.cause_entry(cause)))
            elif hit(cause.raw.get("description"), cause.raw.get("resolution")):
                scored.append((2, cause.id, self.cause_entry(cause)))
        for record in sorted(self.db.jira, key=_jira_key, reverse=True):
            if hit(record.get("note"), record.get("failed_step")):
                scored.append((3, str(record.get("key")), self.jira_entry(record)))
        scored.sort(key=lambda s: (s[0], s[1]))
        return [s[2] for s in scored]

    # 단어별 검색 --------------------------------------------------------------------

    def alias_rows(self) -> list[tuple[list[str], list[str]]]:
        if self._aliases is None:
            self._aliases = glossary.search_aliases(self.db.root)
        return self._aliases

    def aliases_of(self, term: str) -> list[str]:
        out: list[str] = []
        for keys, values in self.alias_rows():
            if any(term.startswith(k) for k in keys):
                out += [v for v in values if v != term and v not in out]
        return out

    def tokenize(self, query: str) -> list[tuple[str, list[str]]]:
        """`[(단어, 별칭[])]`. 불용어·조사·부정 접두를 떼고 중복을 버린다. 1글자는 별칭 키와 맞는 한글만 남긴다."""
        keys = [k for ks, _ in self.alias_rows() for k in ks]
        out: list[tuple[str, list[str]]] = []
        for raw in TOKEN_RE.findall(query.lower()):
            tok = raw.rstrip(".+-")
            if not tok or tok in STOPWORDS:
                continue
            if re.fullmatch(r"[가-힣]+", tok):
                if len(tok) >= 3 and tok[0] in "안못" and not any(tok.startswith(k) for k in keys):
                    tok = tok[1:]
                for particle in PARTICLES:
                    if tok.endswith(particle) and len(tok) - len(particle) >= 2:
                        tok = tok[: -len(particle)]
                        break
                if tok in STOPWORDS:
                    continue
            if any(tok == t for t, _ in out):
                continue
            aliases = self.aliases_of(tok)
            if len(tok) < 2 and not (re.fullmatch(r"[가-힣]", tok) and aliases
                                     and any(k == tok or k.startswith(tok) for k in keys)):
                continue
            out.append((tok, aliases))
        return out

    def symptom_body(self, itype: issuedb.IssueType) -> str:
        if itype.id not in self._symptom:
            try:
                body = typedoc.split((itype.path / "type.md").read_text(encoding="utf-8"))[1]
            except (OSError, typedoc.TypeDocError):
                body = ""
            found = SYMPTOM_RE.search(body)
            self._symptom[itype.id] = found.group(1) if found else ""
        return self._symptom[itype.id]

    def term_pass(self, terms: list[tuple[str, list[str]]], phrase: list[dict]) -> list[tuple[int, int, dict]]:
        """`[(맞은 단어 수, 점수, 엔트리)]` (맞은 것만). 엔트리에 `matched`·`score`를 채우고 phrase 엔트리에도 옮긴다."""
        groups = []
        for term, aliases in terms:
            variants = aliases if len(term) < 2 else [term, *aliases]
            groups.append((term, [v.lower() for v in variants]))

        def evaluate(entry: dict, fields: list[tuple[int, object]]) -> tuple[int, int]:
            matched, score = [], 0
            low = [(w, str(v).lower()) for w, v in fields if v]
            for term, variants in groups:
                best = max((w for w, text in low if any(v in text for v in variants)), default=0)
                if best:
                    matched.append(term)
                    score += best
            entry["matched"], entry["score"] = matched, score
            return len(matched), score

        def parent_fields(itype: issuedb.IssueType, strong: int, mid: int) -> list[tuple[int, object]]:
            return [(strong, itype.title), (strong, " ".join(map(str, itype.raw.get("tags") or []))),
                    (mid, itype.raw.get("summary")), (WEIGHT_WEAK, self.symptom_body(itype))]

        out: list[tuple[int, int, dict]] = []
        for itype in self.types.values():
            entry = self.type_entry(itype)
            m, s = evaluate(entry, [(WEIGHT_STRONG, itype.id), *parent_fields(itype, WEIGHT_STRONG, WEIGHT_MID)])
            out.append((m, s, entry))
        for cause in self.causes.values():
            entry = self.cause_entry(cause)
            fields = [(WEIGHT_STRONG, cause.id), (WEIGHT_STRONG, cause.title),
                      (WEIGHT_MID, cause.raw.get("description")), (WEIGHT_MID, cause.raw.get("resolution")),
                      *parent_fields(self.types[cause.type_id], WEIGHT_WEAK, WEIGHT_WEAK)]
            m, s = evaluate(entry, fields)
            out.append((m, s, entry))
        for record in sorted(self.db.jira, key=_jira_key, reverse=True):
            entry = self.jira_entry(record)
            m, s = evaluate(entry, [(WEIGHT_WEAK, record.get("note")), (WEIGHT_WEAK, record.get("failed_step"))])
            out.append((m, s, entry))
        by_id = {(e["kind"], e.get("id") or e.get("key")): e for _, _, e in out}
        for entry in phrase:
            src = by_id[(entry["kind"], entry.get("id") or entry.get("key"))]
            entry["matched"], entry["score"] = src["matched"], src["score"]
        return [x for x in out if x[0] > 0]


BRIEF_DROP = ("path", "chain", "merged_from", "code_refs", "resolution_type", "signatures_pending", "type_title",
              "category")


def brief(result: dict) -> dict:
    """`--brief` 출력: 후보를 훑는 데 필요 없는 키와 빈 값을 뺀다 (`links`·`git_history`는 그대로)."""
    def slim(entry: dict) -> dict:
        out = {}
        for key, value in entry.items():
            if key in BRIEF_DROP or (key == "current" and value == entry.get("id")):
                continue
            if isinstance(value, dict):
                value = {k: v for k, v in value.items() if v not in (None, "", [], {})}
            if value in (None, "", [], {}):
                continue
            out[key] = value
        return out
    return {**{k: v for k, v in result.items() if k not in ("db", "results")},
            "results": [slim(e) for e in result["results"]]}


def _line(value) -> str:
    return " ".join(str("" if value is None else value).split())


def _cell(value) -> str:
    return _line(value).replace("\\", "\\\\").replace("|", "\\|")


def _builds(fixed_in) -> list[str]:
    out = []
    for item in fixed_in or []:
        value = (item.get("build") or item.get("branch")) if isinstance(item, dict) else item
        if value and str(value) not in out:
            out.append(str(value))
    return out


def render_markdown(result: dict) -> str:
    """`search.md §3` 보여주기 규칙: 이슈 번호 줄 → 표(결과 순서 그대로, Jira 항목도 같은 표) → 연관·다른 카테고리 → 옛 ID 연결
    → 꼬리 문장. 문구가 `search.md`에 없는 값은 원값(`current`, `phrase` 등)을 그대로 보인다."""
    kind, terms = result.get("kind"), result.get("terms")
    words = [t["term"] for t in terms or []]
    head = f'검색: "{_line(result["query"])}" ({kind}' + (f", 단어: {', '.join(words)}" if words else "") + ")"
    entries = result.get("results") or []
    out = [head, ""]
    if not entries:
        out.append("일치 없음 — 검색 단어: " + ", ".join(words) if words else
                   ("일치 없음 — 검색 단어(terms): 없음 (불용어뿐)" if kind == "keyword" else f"일치 없음 — {kind} 질의"))
    groups = [e for e in entries if e["kind"] in ("type", "cause")]
    keys: list[str] = []
    for e in groups:
        keys += [k for k in e.get("jira") or [] if k not in keys]
    if keys:
        latest = max((e.get("jira_latest") or "" for e in groups), default="")
        out.append(f"이슈 번호: {', '.join(keys)}" + (f" (jira_latest {latest})" if latest else ""))
        capped = [f"{e['id']} jira_count {e['jira_count']} / 표시 {len(e['jira'])}" for e in groups
                  if (e.get("jira_count") or 0) > len(e.get("jira") or [])]
        if capped:
            out.append("최근 5건만 표시: " + ", ".join(capped))
        out.append("")
    if entries:
        out += ["| 유형 > 원인 | 해결책 | 수정 상태 | 최근 Jira | 맞은 단어 |", "|---|---|---|---|---|"]
    for e in entries:
        if e["kind"] == "cause":
            name = f"{e['type_title']} > {e['id']} {e['title']}"
            rv = e.get("resolution_verification")
            state = "미검증" if rv in (None, "unverified") else str(rv)
            res = f"{e.get('resolution') or '—'} ({state})"
            fix = e.get("fix") or {}
            builds = _builds(fix.get("fixed_in"))
            status = f"{fix.get('status')}" + (f" (fixed_in {', '.join(builds)})" if builds else "")
            recent = f"{e.get('jira_latest') or '—'} ({e.get('jira_count', 0)}건)"
        elif e["kind"] == "type":
            name, res, status = f"{e['id']} {e['title']} (type)", "—", e.get("status")
            recent = f"{e.get('jira_latest') or '—'} ({e.get('jira_count', 0)}건)"
        else:
            name = f"Jira {e['key']} (원인 {e.get('cause')}, 유형 {e.get('type')})"
            res, status, recent = f"note: {e.get('note') or ''}", "—", e.get("date") or "—"
        if "matched" not in e:
            hit = "—"
        else:
            hit = ", ".join(e["matched"]) + (" (phrase: true)" if e.get("phrase") else "")
            if not e.get("phrase") and len(e["matched"]) < len(words):
                hit += " (부분 일치)"
        out.append(f"| {_cell(name)} | {_cell(res)} | {_cell(status)} | {_cell(recent)} | {_cell(hit)} |")
    if entries:
        out.append("")
    for e in groups:
        extra = []
        if e.get("related"):
            extra.append("연관 " + ", ".join(e["related"]))
        if e.get("secondary_categories"):
            extra.append("다른 카테고리 " + ", ".join(e["secondary_categories"]))
        if e.get("current") not in (None, e["id"]):
            extra.append(f"current: {e['current']}")
        if extra:
            out.append(f"- {e['id']}: " + " / ".join(extra))
    if result.get("links"):
        via = {"merged-into": "병합 (merged-into)", "renumbered": "사후 정리 (renumbered)"}
        out += ["", "옛 ID → 새 ID"]
        for l in result["links"]:
            detail = ", ".join(str(x) for x in (via.get(l.get("via"), l.get("via")), l.get("commit"), l.get("date")) if x)
            out.append(f"- {l['from']} → {l['to']} ({detail})")
    if entries:
        out += ["", "이 순위는 검색용이다. 분류를 확정하거나 원인을 단정하는 근거로 쓰지 않는다."]
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text) + "\n"


def run(args, defaults: dict) -> dict:
    try:
        root = dbpath.resolve(args.db, user_config_path=lambda: userconfig.issue_db_path(defaults))
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc
    try:
        db = issuedb.load(root)
    except issuedb.IssueDbError as exc:
        raise UsageError(str(exc)) from exc
    if args.limit < 1:
        raise UsageError("--limit은 1 이상이어야 합니다.")
    query = args.query.strip()
    if not query:
        raise UsageError("검색어가 비었습니다.")
    return {"db": str(root), **Searcher(db, args.limit).search(query)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db_search.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--db", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--brief", action="store_true", help="훑어보기용 요약 출력 (path·chain·code_refs·빈 값 등을 뺀다)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json",
                        help="markdown: search.md §3 보여주기 규칙대로 (기본 json, --json·--brief와 함께 못 쓴다/무시)")
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
        if args.format == "markdown" and args.json:
            raise UsageError("--format markdown은 --json과 함께 쓸 수 없다.")
        result = run(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    if args.format == "markdown":
        print(render_markdown(result), end="")
        return OK
    if args.brief:
        result = brief(result)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
