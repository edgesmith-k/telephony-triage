"""이슈 DB `parser-rules/` 로드와 검증 (04-parser-matching.md §5.8).

규칙은 항상 `--rules <db>/parser-rules`에서 읽는다(코드에 하드코딩하지 않는다).
스키마는 같은 이슈 DB의 `schema/parser-rules.schema.json`이다.

검사 (하나라도 걸리면 `RulesError`, 스크립트는 종료 코드 2)
- 파일 세 개(`tags.yaml`, `ril.yaml`, `extractors.yaml`)가 있고 YAML로 읽힌다.
- extractor가 `builtin.`/`ext.` 접두어 이벤트를 만들려 하지 않는다
  (백엔드·어댑터 이름 공간, `contracts.md §기존 자산 연결 계약`).
- extractor가 엔진 예약 이벤트(`RESERVED_EVENTS`)를 만들려 하지 않는다.
- JSON 스키마를 통과한다.
- 키가 겹치지 않는다(tags: tag/tag_regex, ril: name, extractors: id).
- 정규식이 컴파일되고, extractor `fields`가 패턴의 이름 있는 그룹에 있다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import yamlio

FILES = ("tags.yaml", "ril.yaml", "extractors.yaml")
SCHEMA_REL = Path("schema") / "parser-rules.schema.json"

# parse_logcat.py가 ril.yaml로 만드는 이벤트. extractor는 이 이름을 쓸 수 없다.
RESERVED_EVENTS = ("ril_error", "ril_timeout", "ril_no_response")
RESERVED_PREFIXES = ("builtin.", "ext.")


class RulesError(Exception):
    pass


@dataclass
class Extractor:
    id: str
    tag: str | None
    tag_regex: re.Pattern | None
    patterns: list[re.Pattern]
    event: str
    fields: list[str]

    def tag_matches(self, tag: str) -> bool:
        if self.tag is not None:
            return tag == self.tag
        return bool(self.tag_regex.search(tag))


@dataclass
class Rules:
    path: Path
    tag_exact: dict[str, str] = field(default_factory=dict)
    tag_regexes: list[tuple[re.Pattern, str]] = field(default_factory=list)
    requests: dict[str, dict] = field(default_factory=dict)
    unsolicited: dict[str, dict] = field(default_factory=dict)
    extractors: list[Extractor] = field(default_factory=list)

    def tag_category(self, tag: str) -> str | None:
        """수집 대상 태그면 카테고리, 아니면 None(그 줄은 버린다)."""
        if tag in self.tag_exact:
            return self.tag_exact[tag]
        for pattern, category in self.tag_regexes:
            if pattern.search(tag):
                return category
        return None

    def ril_category(self, name: str) -> str | None:
        rule = self.requests.get(name) or self.unsolicited.get(name)
        return rule["category"] if rule else None

    def summary(self) -> dict:
        return {
            "tags": len(self.tag_exact) + len(self.tag_regexes),
            "requests": len(self.requests),
            "unsolicited": len(self.unsolicited),
            "extractors": len(self.extractors),
        }


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise RulesError(f"규칙 파일이 없습니다: {path}")
    try:
        data = yamlio.load(path)
    except yaml.YAMLError as exc:
        raise RulesError(f"{path.name}: YAML 오류: {exc}") from exc
    if not isinstance(data, dict):
        raise RulesError(f"{path.name}: 최상위가 매핑이어야 합니다.")
    return data


def _compile(text: str, where: str) -> re.Pattern:
    try:
        return re.compile(text)
    except re.error as exc:
        raise RulesError(f"{where}: 정규식 오류 {text!r}: {exc}") from exc


def _validator(schema_path: Path):
    import jsonschema

    if not schema_path.is_file():
        raise RulesError(f"규칙 스키마가 없습니다: {schema_path}")
    with schema_path.open(encoding="utf-8") as fh:
        schema = json.load(fh)
    return jsonschema.Draft202012Validator(schema)


def _check_extractor_names(data: dict) -> None:
    for item in data.get("extractors") or []:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event", ""))
        ident = item.get("id", "?")
        if event.startswith(RESERVED_PREFIXES):
            raise RulesError(
                f"extractors.yaml: '{ident}'의 이벤트 '{event}' — extractor는 "
                "builtin./ext. 접두어 이벤트를 만들 수 없습니다 "
                "(백엔드·어댑터 이름 공간, 04-parser-matching.md §5.8 (2))."
            )
        if event in RESERVED_EVENTS:
            raise RulesError(
                f"extractors.yaml: '{ident}'의 이벤트 '{event}'는 엔진 예약 이름입니다 "
                f"({', '.join(RESERVED_EVENTS)})."
            )


def load(rules_dir: str | Path, schema_path: str | Path | None = None) -> Rules:
    rules_dir = Path(rules_dir)
    if not rules_dir.is_dir():
        raise RulesError(f"규칙 디렉토리가 없습니다: {rules_dir}")
    schema_path = Path(schema_path) if schema_path else rules_dir.parent / SCHEMA_REL
    validator = _validator(schema_path)

    docs = {name: _read_yaml(rules_dir / name) for name in FILES}
    _check_extractor_names(docs["extractors.yaml"])
    for name, data in docs.items():
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        if errors:
            first = errors[0]
            where = "/".join(str(p) for p in first.absolute_path) or "(최상위)"
            raise RulesError(f"{name}: 스키마 오류 ({len(errors)}건) — {where}: {first.message}")

    rules = Rules(path=rules_dir)

    seen: set[str] = set()
    for item in docs["tags.yaml"].get("tags") or []:
        key = item.get("tag") or item.get("tag_regex")
        if key in seen:
            raise RulesError(f"tags.yaml: 키가 겹칩니다: {key}")
        seen.add(key)
        if "tag" in item:
            rules.tag_exact[item["tag"]] = item["category"]
        else:
            rules.tag_regexes.append((_compile(item["tag_regex"], "tags.yaml"), item["category"]))

    ril_doc = docs["ril.yaml"]
    for section, target in (("requests", rules.requests), ("unsolicited", rules.unsolicited)):
        for item in ril_doc.get(section) or []:
            if item["name"] in rules.requests or item["name"] in rules.unsolicited:
                raise RulesError(f"ril.yaml: 이름이 겹칩니다: {item['name']}")
            target[item["name"]] = item

    ids: set[str] = set()
    for item in docs["extractors.yaml"].get("extractors") or []:
        ident = item["id"]
        if ident in ids:
            raise RulesError(f"extractors.yaml: id가 겹칩니다: {ident}")
        ids.add(ident)
        where = f"extractors.yaml:{ident}"
        patterns = [_compile(p, where) for p in item["patterns"]]
        groups = set().union(*(p.groupindex for p in patterns))
        missing = [f for f in item["fields"] if f not in groups]
        if missing:
            raise RulesError(f"{where}: fields {missing}가 패턴의 이름 있는 그룹에 없습니다.")
        rules.extractors.append(
            Extractor(
                id=ident,
                tag=item.get("tag"),
                tag_regex=_compile(item["tag_regex"], where) if "tag_regex" in item else None,
                patterns=patterns,
                event=item["event"],
                fields=list(item["fields"]),
            )
        )
    return rules
