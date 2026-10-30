"""op `add-parser-rule`·`update-parser-rule`·`remove-parser-rule`: `parser-rules/*.yaml` 엔티티 단위 쓰기."""

from __future__ import annotations

from pathlib import Path

from common import yamldoc, yamlio

from ..core import HISTORY_FIELDS, RULE_KEYS, RULE_SECTIONS, Reject


class ParserRuleOps:

    def _rules(self, i: int, file: str) -> tuple[Path, dict]:
        if file not in RULE_SECTIONS:
            raise Reject("rule-file", f"규칙 파일은 {list(RULE_SECTIONS)} 중 하나입니다: {file}", i)
        path = self.tree.root / "parser-rules" / file
        if file not in self.tree.rule_docs:
            text = self.tree.read(path)
            if text is None:
                raise Reject("rule-file", f"규칙 파일이 없습니다: parser-rules/{file}", i)
            self.tree.rule_docs[file] = {"text": text, "data": yamlio.loads(text) or {}}
        return path, self.tree.rule_docs[file]

    @staticmethod
    def _rule_key(section: str, rule: dict) -> str | None:
        for field in RULE_KEYS[section]:
            if rule.get(field) is not None:
                return str(rule[field])
        return None

    def _section(self, i: int, op: dict) -> str:
        sections = RULE_SECTIONS.get(op["file"], ())
        section = op.get("section") or (sections[0] if sections else None)
        if section not in sections:
            raise Reject("rule-section", f"{op['file']}에는 {sections} 섹션만 있습니다: {section}", i)
        return section

    def _write_rules(self, path: Path, doc: dict, section: str, old: list, new: list) -> None:
        lines = doc["text"].splitlines(keepends=True)
        flow = section != "extractors"
        key_of = lambda r: self._rule_key(section, r)  # noqa: E731
        if old:
            block = yamldoc.ListSection(lines, section, old)
            text = block.render(old, new, key_of=key_of, flow=flow)
            lines = yamldoc.replace_block(lines, section, text)
        elif dict(yamldoc.top_blocks(lines)).get(section):
            lines = yamldoc.replace_block(lines, section, yamldoc.dump_key(section, new))
        else:
            lines = lines + ["\n"] + yamldoc.dump_key(section, new).splitlines(keepends=True)
        doc["text"] = "".join(lines)
        doc["data"][section] = new
        self.tree.write(path, doc["text"])

    def op_add_parser_rule(self, i, op):
        section = self._section(i, op)
        path, doc = self._rules(i, op["file"])
        rule = op["rule"]
        key = self._rule_key(section, rule)
        if key is None:
            raise Reject("rule-key", f"규칙 키({'/'.join(RULE_KEYS[section])})가 없습니다.", i)
        missing = [f for f in HISTORY_FIELDS if not rule.get(f)]
        if missing:
            raise Reject("rule-history", f"규칙 이력 필드가 없습니다: {', '.join(missing)}", i)
        old = list(doc["data"].get(section) or [])
        if any(self._rule_key(section, r) == key for r in old):
            raise Reject("rule-exists", f"parser-rules/{op['file']} {section}에 키 {key}가 이미 있습니다 "
                         "(update-parser-rule을 쓴다).", i)
        self._write_rules(path, doc, section, old, old + [rule])

    def op_update_parser_rule(self, i, op):
        section = self._section(i, op)
        path, doc = self._rules(i, op["file"])
        old = list(doc["data"].get(section) or [])
        n = next((k for k, r in enumerate(old) if self._rule_key(section, r) == op["key"]), None)
        if n is None:
            raise Reject("rule-missing", f"parser-rules/{op['file']} {section}에 키 {op['key']}가 없습니다.", i)
        missing = [f for f in ("reason", "added_on") if not op["rule"].get(f)]
        if missing:
            raise Reject("rule-history", f"update-parser-rule은 {', '.join(missing)}를 갱신해야 합니다.", i)
        merged = {k: v for k, v in old[n].items()}
        merged.update(op["rule"])
        new = list(old)
        new[n] = merged
        self._write_rules(path, doc, section, old, new)

    def op_remove_parser_rule(self, i, op):
        """placeholder·안 쓰는 규칙 삭제. 사용 여부는 정적으로 보지 않는다 — 계획 검증(R1~R5: rulediff 의존 시그니처,
        R5 이벤트 diff)과 db_lint `step-event`가 영향을 보인다. 삭제 이력은 CHANGELOG에 남지 않는다(사유는 PR 본문)."""
        path, doc = self._rules(i, op["file"])
        if op.get("section"):
            section = self._section(i, op)
        else:
            found = [s for s in RULE_SECTIONS[op["file"]]
                     if any(self._rule_key(s, r) == op["key"] for r in doc["data"].get(s) or [])]
            if len(found) > 1:
                raise Reject("rule-section", f"parser-rules/{op['file']}의 {found} 섹션에 모두 키 {op['key']}가 있습니다 "
                             "(section을 지정한다).", i)
            section = found[0] if found else RULE_SECTIONS[op["file"]][0]
        old = list(doc["data"].get(section) or [])
        n = next((k for k, r in enumerate(old) if self._rule_key(section, r) == op["key"]), None)
        if n is None:
            raise Reject("rule-missing", f"parser-rules/{op['file']} {section}에 키 {op['key']}가 없습니다.", i)
        if len(old) == 1:
            raise Reject("rule-last", f"parser-rules/{op['file']} {section}의 마지막 항목은 지울 수 없습니다 — 스키마가 "
                         "섹션마다 1개 이상을 요구한다. 같은 계획 앞쪽에 add-parser-rule로 실제 항목을 넣고 지운다.", i)
        lines = doc["text"].splitlines(keepends=True)
        text = yamldoc.ListSection(lines, section, old).remove(n)
        doc["text"] = "".join(yamldoc.replace_block(lines, section, text))
        doc["data"][section] = old[:n] + old[n + 1:]
        self.tree.write(path, doc["text"])
