"""op `add-parser-rule`·`update-parser-rule`: `parser-rules/*.yaml` 엔티티 단위 쓰기."""

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
