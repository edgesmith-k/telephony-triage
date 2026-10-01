#!/usr/bin/env python3
"""db_search.py — 이슈 DB 검색 (contracts.md §3.2, §renumber 참조, 03-issue-db.md §5.5).

    db_search.py [--db <path>] <keyword|JIRA-KEY|ID> [--limit 20]

읽기 전용이다. 질의 종류는 모양으로 정한다.

- 유형 ID(`DATA-001`)·원인 ID(`DATA-001-01`): 그 엔티티. 없는 ID여도 옛 ID 연결을 찾는다.
- Jira 키(`jira_key_regex`): 그 Jira 기록과 소속 원인(또는 유형).
- 그 밖: 키워드. 유형(제목·요약·태그), 원인(제목·설명·해결책), Jira(`note`)에서 대소문자 무시 부분 일치.

**옛 ID → 새 ID 연결** (`contracts.md §renumber 참조`)
- `merged-into:` 체인: 병합된 유형·원인은 삭제하지 않고 `status: merged-into:<ID>`를 남긴다. 체인을 끝(active 등)까지
  따라가 `current`로 보여준다. 거꾸로 이 ID로 병합된 엔티티는 `merged_from`.
- `Renumbered: <옛 ID> -> <새 ID>` 트레일러(사후 정리 커밋, 이슈 DB git 이력): 옛 ID는 원래 주인이 계속 쓰므로
  옛 ID 엔티티도 그대로 보이고, 옮겨간 엔티티를 `renumbered[]`와 결과에 함께 보인다. 새 ID로 찾으면
  어디서 옮겨왔는지 보인다.

출력(JSON): `{query, kind: type-id|cause-id|jira|keyword, results[], links[], git_history}`.
`results[]` 항목은 `kind: type|cause|jira`와 유형·원인·해결책·수정 상태·Jira 요약이다. 원인 항목에는
`code_refs[{ref, symbol, android_versions}]`(Step 5 resolve 입력)가 붙는다. 스킬·드라이버는 `--limit 3`으로 부른다.
`links[]`는 `{from, to, via: merged-into|renumbered, commit?, date?}`. 결과가 없어도 종료 코드 0이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import dbpath, history, issuedb, quality, site_defaults, userconfig  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402
from common.fixtures import CAUSE_ID_RE, TYPE_ID_RE  # noqa: E402

JIRA_SHOWN = 5
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
        return {
            "kind": "type", "id": itype.id, "category": itype.category, "title": itype.title,
            "status": itype.status, "current": current, "chain": chain, "merged_from": self.merged_from(itype.id),
            "secondary_categories": list(itype.raw.get("secondary_categories") or []),
            "causes": [{"id": c.id, "title": c.title, "status": c.status} for c in itype.causes],
            "unresolved": sorted(str(r.get("key")) for r in records if str(r.get("cause")) == "unresolved"),
            "jira_count": len(records),
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
            "path": (itype.path / "type.md").relative_to(self.db.root).as_posix(),
        }

    def jira_entry(self, record: dict) -> dict:
        return {"kind": "jira", "key": record.get("key"), "cause": record.get("cause"), "type": record["_type"],
                "date": str(record.get("date", "")), "occurred_on": str(record.get("occurred_on") or "") or None,
                "note": record.get("note"), "path": record["_rel"]}

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
            results = self.keyword(query)
        results = results[: self.limit]
        return {"query": query, "kind": kind, "results": results,
                "links": self.links_for(results) + renumbered, "git_history": self.history.enabled}

    def keyword(self, query: str) -> list[dict]:
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
            if hit(record.get("note")):
                scored.append((3, str(record.get("key")), self.jira_entry(record)))
        scored.sort(key=lambda s: (s[0], s[1]))
        return [s[2] for s in scored]


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
        result = run(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
