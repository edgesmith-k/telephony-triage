#!/usr/bin/env python3
"""db_lint.py — 이슈 DB 정적 검사 (01-architecture.md §3.1, 03-issue-db.md §5.7 (4)).

    db_lint.py [--db <path>] (--all | --ref <ref> | --changed <ref> | --staged)
               [--residual <옛 ID>=<새 ID> ...]

검사 (코드 — 수준)
- `schema` 오류: 유형 frontmatter·Jira·피드백·`.expect.yaml`을 이슈 DB `schema/`로 검사
- `category`·`id-format`·`id-prefix`·`type-dir` 오류: 카테고리 목록, ID 형식·접두어, 유형 디렉토리 이름
- `duplicate-id`·`duplicate-jira` 오류: ID 중복, 같은 Jira 키가 둘 이상
- `jira-key`·`jira-cause` 오류: `jira_key_regex`, 파일 이름, `cause`가 그 유형의 원인인지
- `glossary`·`title-length` 경고: 금지 동의어(GLOSSARY.md), 제목 길이 (§5.7 (2))
- `related` 오류: 없는 원인, 한쪽만 있는 related
- `code-ref` 오류: `<root 키>:<상대 경로>` 형식, 절대 경로, `code_root_keys`
- `fix-ref` 오류: `fix.ref`가 `fix_ref_regex`에 맞지 않음
- `fixture-name`·`fixture-owner`·`fixture-orphan` 오류: fixture 파일 이름 규칙(contracts.md §fixture)
- `fixture-missing` 경고: active 원인에 양성 fixture 없음
- `raw-identifier` 오류: 시그니처·extractor 패턴, Jira `note`, 원인 `cp_evidence`, 유형 본문의 원본 식별자
- `fixed-token` 경고: 시그니처·extractor가 특정 마스킹 번호(`<CELL#1>`)를 고정
- `regex-unsafe` 오류: 중첩 수량자·겹치는 선택지 반복·역참조 (04 §5.8 (4), 정적·보수적)
- `mask-allow-too-broad` 오류: `mask.allow_patterns` 패턴이 합성 PII 표본(IMSI·IMEI·IP·MAC·EMAIL·MSISDN) 하나에
  통째로 맞음. 같은 목록의 정규식 오류·형식 오류는 `schema`, 안전성은 `regex-unsafe`
- `step-event` 오류: `issue-db.config.yaml`의 `step_events` 규칙(스텝 → 로그 흔적, 02-config.md §5.3): 대상(`event`·`ril`·`match`)이
  정확히 하나가 아님(`observable: false`면 없어야 함), 없는 `event`(extractor 이벤트·예약 이벤트·`builtin.*`가 아님)·`ext.*`(미지원),
  없는 `ril` 이름, 잘못된 `dir`, `event` 없는 `fields`. 목록·`pattern`·정규식 형식 오류는 `schema`, 패턴 안전성은
  `raw-identifier`·`fixed-token`·`regex-unsafe`
- `sequence`·`signature` 오류: sequence의 없는 id·중복 id·must_not_match 참조, 시그니처 형식
- `symptom-missing`·`signatures-missing` 오류, `signatures-pending` 경고, `pending-on-type`·`pending-verified` 오류
- `builtin-event`·`ext-event` 오류: 현재 백엔드 `builtin_events()`에 없는 `builtin.*`, 이슈 DB `external_parsers`에
  없는 카테고리의 `ext.*`
- `verified-without-evidence`·`evidence-missing` 오류: 근거 없는 verified, 없는 Jira 키·fixture 경로
- `new-cause-fixed` 오류: base에 없던 원인이 `fixed` (`--changed`·`--staged`에서만)
- `fixed-without-verification` 오류: `fixed`인데 `fix.verification.result: passed`가 없음 (검증 없는 fixed 금지)
- `fixed-without-trace` 오류: 코드·설정 수정 유형(`framework-bug`·`vendor-ril`·`modem`·`carrier-config`)이 `fixed`인데
  `scenario_signatures`·`recovery_signatures`가 모두 없음 (05-verification.md §5.12 (2) 전제)
- `also-allowed` 오류: 자기 원인·같은 유형 원인·없는 ID
- `merged-into` 오류: 없는 병합 대상
- `parser-rules` 오류: 규칙 파일 로드·스키마
- `synthetic` 경고: `synthetic_allowed: false`인 플러그인에서 `origin: synthetic` fixture
- `residual-id` 오류: `--residual`로 준 옛 ID가 남아 있음

범위: `--all`은 워킹 트리 전체, `--ref`는 그 커밋의 트리, `--changed <ref>`는 merge-base 이후 바뀐
파일, `--staged`는 index 내용(바뀐 파일만 보고). 전역 검사(중복 등)는 전체를 보고, 결과 중
바뀐 파일이 관련된 것만 낸다. 종료 코드: 오류가 있으면 1, 경고만 있으면 0.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import parser_backends  # noqa: E402
from common import dbpath, gitscope, issuedb, masking, parser_rules, site_defaults, yamlio  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from common.fixtures import CAUSE_ID_RE, TYPE_ID_RE, parse_name  # noqa: E402
from common.signatures import SignatureError, compile_signature  # noqa: E402

TOKEN_FIXED_RE = re.compile(r"<[A-Z][A-Z0-9]*#\d+>")
KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SIG_KINDS = ("symptom_signatures", "signatures", "recovery_signatures", "scenario_signatures")
TYPE_TITLE_MAX, CAUSE_TITLE_MAX = 30, 20
CODE_FIX_TYPES = ("framework-bug", "vendor-ril", "modem", "carrier-config")
# mask.allow_patterns 넓이 검사용 합성 PII 표본 (IP는 TEST-NET: 사설 대역 한정 예외는 통과시킨다)
PII_PROBES = {"IMSI": "450081234567890", "IMEI": "356938035643809", "IP": "203.0.113.7",
              "MAC": "02:00:00:aa:bb:cc", "EMAIL": "user@example.com", "MSISDN": "010-1234-5678"}


class UsageError(Exception):
    pass


# -- 패턴 검사 --------------------------------------------------------------------


def raw_identifier_in_pattern(pattern: str) -> str | None:
    """정규식이 원본 식별자를 겨냥하는지 (보수적). 이유 문자열 또는 None."""
    for hit in re.finditer(r"(?:\\d|\[0-9\])\{(\d+)", pattern):
        if int(hit.group(1)) >= 10:
            return f"숫자 {hit.group(1)}자리 이상 패턴"
    if re.search(r"(?<![\\{,])\d{10,}", pattern):
        return "10자리 이상 숫자"
    if re.search(r"(?<!\d)01[016789](?:-|\\d|\[|\d)|01\[[016789]+\]|\\\+82|(?<!\\)\+82", pattern):
        return "전화번호 형식"
    literal = re.sub(r"\\(.)", r"\1", pattern)
    found = masking.new_masker().find(literal)
    if found:
        return f"원본 식별자({found[0]['kind']})"
    return None


def _parser_mod():
    try:
        from re import _constants as const
        from re import _parser as parse_mod
    except ImportError:  # 3.10 이하
        import sre_constants as const
        import sre_parse as parse_mod
    return parse_mod, const


def unsafe_regex(pattern: str) -> str | None:
    """중첩 수량자, 반복 안의 겹치는 선택지, 역참조를 찾는다 (정적·보수적)."""
    parse_mod, c = _parser_mod()
    try:
        tree = parse_mod.parse(pattern)
    except Exception:  # noqa: BLE001 — 컴파일 오류는 다른 검사가 낸다
        return None
    repeats = {c.MAX_REPEAT, c.MIN_REPEAT}
    if hasattr(c, "POSSESSIVE_REPEAT"):
        repeats.add(c.POSSESSIVE_REPEAT)

    def first(items):
        items = list(items)
        return (items[0][0], str(items[0][1])) if items else None

    def walk(items, in_repeat: bool) -> str | None:
        for op, av in items:
            if op in repeats:
                lo, hi, sub = av
                many = hi > 1
                if many and in_repeat:
                    return "중첩 수량자"
                found = walk(sub, in_repeat or many)
                if found:
                    return found
            elif op == c.SUBPATTERN:
                found = walk(av[-1], in_repeat)
                if found:
                    return found
            elif op == c.BRANCH:
                branches = av[1]
                if in_repeat:
                    heads = [first(b) for b in branches]
                    if len(set(heads)) < len(heads):
                        return "반복 안의 겹치는 선택지"
                for branch in branches:
                    found = walk(branch, in_repeat)
                    if found:
                        return found
            elif op in (c.GROUPREF, getattr(c, "GROUPREF_EXISTS", None)):
                return "역참조"
            elif op in (c.ASSERT, c.ASSERT_NOT):
                found = walk(av[1], in_repeat)
                if found:
                    return found
        return None

    return walk(tree, False)


# -- 린터 --------------------------------------------------------------------------


class Linter:
    def __init__(self, root: Path, defaults: dict, base_causes: set[str] | None = None,
                 residual: list[tuple[str, str]] | None = None, scope: set[str] | None = None):
        self.root = root
        self.defaults = defaults
        self.base_causes = base_causes
        self.residual = residual or []
        self.scope = scope
        self.findings: list[dict] = []
        self.checked = 0

    # 기록 -----------------------------------------------------------------------

    def add(self, level: str, code: str, files, message: str) -> None:
        files = [files] if isinstance(files, (str, Path)) else list(files)
        rels = [f if isinstance(f, str) else f.relative_to(self.root).as_posix() for f in files]
        self.findings.append({"level": level, "code": code, "file": rels[0] if rels else None,
                              "files": rels, "message": message})

    def err(self, code, files, message):
        self.add("error", code, files, message)

    def warn(self, code, files, message):
        self.add("warning", code, files, message)

    # 실행 -----------------------------------------------------------------------

    def run(self) -> dict:
        try:
            self.config = issuedb.load_config(self.root)
        except issuedb.IssueDbError as exc:
            self.err("schema", issuedb.CONFIG, str(exc))
            return self.result()
        cats = [c for c in self.config.get("categories") or [] if isinstance(c, dict)]
        self.categories = {c["key"]: c for c in cats if c.get("key")}
        self.key_re = self._compile_cfg("jira_key_regex")
        self.fix_ref_re = self._compile_cfg("fix_ref_regex")
        self._check_mask_allow()
        self.root_keys = set(self.config.get("code_root_keys") or [])
        self.external_cats = set((self.config.get("external_parsers") or {}).keys())
        self.builtin_events = self._builtin_events()
        self.validators = self._validators()
        self.glossary = self._glossary()

        self.types = []  # (path, data)
        for key in self.categories:
            for type_md in sorted((self.root / key).glob("*/type.md")):
                self.checked += 1
                try:
                    data = issuedb.read_frontmatter(type_md)
                except issuedb.IssueDbError as exc:
                    self.err("schema", type_md, str(exc))
                    continue
                self.types.append((type_md, data))
        self._stray_types()
        self.cause_owner = {}
        for type_md, data in self.types:
            for cause in data.get("causes") or []:
                if isinstance(cause, dict) and cause.get("id"):
                    self.cause_owner.setdefault(str(cause["id"]), (type_md, data))

        self._check_ids()
        self._check_step_focus()
        self._check_step_events()
        for type_md, data in self.types:
            self._check_type(type_md, data)
        self._check_jira()
        self._check_feedback()
        self._check_rules()
        self._check_residual()
        return self.result()

    def result(self) -> dict:
        findings = self.findings
        if self.scope is not None:
            findings = [f for f in findings if any(p in self.scope for p in f["files"])]
        errors = [f for f in findings if f["level"] == "error"]
        warnings = [f for f in findings if f["level"] == "warning"]
        return {"errors": errors, "warnings": warnings,
                "summary": {"errors": len(errors), "warnings": len(warnings), "types": self.checked}}

    # 준비 -----------------------------------------------------------------------

    def _compile_cfg(self, key: str):
        value = self.config.get(key)
        if not value:
            return None
        try:
            return re.compile(value)
        except re.error as exc:
            self.err("schema", issuedb.CONFIG, f"{key} 정규식 오류: {exc}")
            return None

    def _check_mask_allow(self) -> None:
        """`mask.allow_patterns`: 목록·정규식·안전성, 그리고 PII 표본 전체에 맞는 넓은 예외 거부 (08-safety.md §8)."""
        cfg = issuedb.CONFIG
        mask = self.config.get("mask")
        pats = mask.get("allow_patterns") if isinstance(mask, dict) else None
        if pats is None:
            return
        if not isinstance(pats, list) or not all(isinstance(p, str) for p in pats):
            self.err("schema", cfg, "mask.allow_patterns는 문자열 목록이어야 합니다.")
            return
        for pat in pats:
            try:
                compiled = re.compile(pat)
            except re.error as exc:
                self.err("schema", cfg, f"mask.allow_patterns 정규식 오류 {pat!r}: {exc}")
                continue
            unsafe = unsafe_regex(pat)
            if unsafe:
                self.err("regex-unsafe", cfg, f"mask.allow_patterns {pat!r}: {unsafe}")
                continue
            kind = next((k for k, v in PII_PROBES.items() if compiled.fullmatch(v)), None)
            if kind:
                self.err("mask-allow-too-broad", cfg,
                         f"mask.allow_patterns {pat!r}가 {kind} 표본 전체에 맞는다. 마스킹 예외는 좁게 쓴다.")

    def _check_step_focus(self) -> None:
        """`scoring.step_focus_bonus_max`(0~0.1)와 `step_focus`(`min_records` ≥ 1, `map[{pattern, types[], categories[]}]`).
        값 오류는 `schema`, 안전하지 않은 패턴은 `regex-unsafe`(issue-db.config.yaml)."""
        cfg = issuedb.CONFIG
        bonus = (self.config.get("scoring") or {}).get("step_focus_bonus_max")
        if bonus is not None and (isinstance(bonus, bool) or not isinstance(bonus, (int, float)) or not 0 <= bonus <= 0.1):
            self.err("schema", cfg, f"scoring.step_focus_bonus_max는 0~0.1 숫자여야 합니다: {bonus!r}")
        focus = self.config.get("step_focus")
        if focus is None:
            return
        if not isinstance(focus, dict):
            self.err("schema", cfg, "step_focus는 매핑이어야 합니다.")
            return
        minimum = focus.get("min_records")
        if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1):
            self.err("schema", cfg, f"step_focus.min_records는 1 이상의 정수여야 합니다: {minimum!r}")
        entries = focus.get("map")
        if entries is None:
            return
        if not isinstance(entries, list):
            self.err("schema", cfg, "step_focus.map은 목록이어야 합니다.")
            return
        type_ids = {str(data.get("id")) for _, data in self.types if data.get("id")}
        for i, item in enumerate(entries):
            where = f"step_focus.map[{i}]"
            if not isinstance(item, dict) or not isinstance(item.get("pattern"), str) or not item["pattern"]:
                self.err("schema", cfg, f"{where}는 pattern(문자열)이 있는 매핑이어야 합니다.")
                continue
            try:
                re.compile(item["pattern"])
            except re.error as exc:
                self.err("schema", cfg, f"{where}.pattern 정규식 오류: {exc}")
            else:
                unsafe = unsafe_regex(item["pattern"])
                if unsafe:
                    self.err("regex-unsafe", cfg, f"{where}.pattern {item['pattern']!r}에 {unsafe}이(가) 있습니다.")
            for name, known, label in (("types", type_ids, "유형"), ("categories", set(self.categories), "카테고리")):
                values = item.get(name) or []
                if not isinstance(values, list):
                    self.err("schema", cfg, f"{where}.{name}는 목록이어야 합니다.")
                    continue
                for value in values:
                    if str(value) not in known:
                        self.err("schema", cfg, f"{where}.{name}: 없는 {label} {value!r}")

    def _rule_names(self) -> tuple[set[str], set[str]]:
        """`parser-rules/`의 extractor 이벤트 이름과 RIL 요청·unsol 이름(읽지 못하면 빈 집합 — 규칙 오류는 `_check_rules`가 낸다)."""
        events: set[str] = set()
        names: set[str] = set()
        try:
            data = yamlio.load(self.root / "parser-rules" / "extractors.yaml") or {}
            events = {str(i["event"]) for i in data.get("extractors") or [] if isinstance(i, dict) and i.get("event")}
            ril = yamlio.load(self.root / "parser-rules" / "ril.yaml") or {}
            for section in ("requests", "unsolicited"):
                names |= {str(i["name"]) for i in ril.get(section) or [] if isinstance(i, dict) and i.get("name")}
        except Exception:    # noqa: BLE001 — 읽기·YAML 오류는 parser-rules 검사가 보고한다
            pass
        return events, names

    def _check_step_events(self) -> None:
        """`step_events`(02-config.md §5.3): 순서 있는 목록 `[{pattern, event|ril|match, fields?, dir?, observable?}]`.
        형식 오류는 `schema`, 대상·이름 오류는 `step-event`, 패턴 안전성은 `_check_pattern`."""
        cfg = issuedb.CONFIG
        rules = self.config.get("step_events")
        if rules is None:
            return
        if not isinstance(rules, list):
            self.err("schema", cfg, "step_events는 목록이어야 합니다.")
            return
        events, ril_names = self._rule_names()
        known_events = events | set(parser_rules.RESERVED_EVENTS) | set(self.builtin_events)

        def regex(where: str, value) -> bool:
            if not isinstance(value, str) or not value:
                self.err("schema", cfg, f"{where}는 비어 있지 않은 문자열이어야 합니다.")
                return False
            try:
                re.compile(value)
            except re.error as exc:
                self.err("schema", cfg, f"{where} 정규식 오류: {exc}")
                return False
            self._check_pattern(cfg, where, value)
            return True

        for i, item in enumerate(rules):
            where = f"step_events[{i}]"
            if not isinstance(item, dict) or not isinstance(item.get("pattern"), str) or not item["pattern"]:
                self.err("schema", cfg, f"{where}는 pattern(문자열)이 있는 매핑이어야 합니다.")
                continue
            regex(f"{where}.pattern", item["pattern"])
            observable = item.get("observable", True)
            if not isinstance(observable, bool):
                self.err("schema", cfg, f"{where}.observable은 true/false여야 합니다: {observable!r}")
                observable = True
            targets = [k for k in ("event", "ril", "match") if k in item]
            if not observable and targets:
                self.err("step-event", cfg, f"{where}: observable: false인 규칙에는 대상({', '.join(targets)})이 없어야 합니다.")
            elif observable and len(targets) != 1:
                self.err("step-event", cfg, f"{where}: event·ril·match 중 정확히 하나가 필요합니다"
                                            f"(observable: false이면 대상 없음): {', '.join(targets) or '없음'}")
            if "fields" in item:
                fields = item["fields"]
                if "event" not in item:
                    self.err("step-event", cfg, f"{where}: fields는 event 규칙에서만 씁니다.")
                if not isinstance(fields, dict) or not all(isinstance(k, str) for k in fields):
                    self.err("schema", cfg, f"{where}.fields는 {{필드 이름: 정규식}} 매핑이어야 합니다.")
                else:
                    for name, value in fields.items():
                        regex(f"{where}.fields.{name}", value)
            if "match" in item:
                regex(f"{where}.match", item["match"])
            if "event" in item:
                name = item["event"]
                if not isinstance(name, str) or not name:
                    self.err("schema", cfg, f"{where}.event는 문자열이어야 합니다.")
                elif name.startswith("ext."):
                    self.err("step-event", cfg, f"{where}.event: {name} — ext.* 이벤트는 step_events에서 지원하지 않습니다.")
                elif name not in known_events:
                    self.err("step-event", cfg, f"{where}.event: 없는 이벤트 {name!r} (extractor 이벤트·ril_* 예약 이벤트·builtin.*)")
            if "ril" in item:
                name = item["ril"]
                if not isinstance(name, str) or not name:
                    self.err("schema", cfg, f"{where}.ril은 문자열이어야 합니다.")
                elif name not in ril_names:
                    self.err("step-event", cfg, f"{where}.ril: ril.yaml에 없는 이름 {name!r}")
            if "dir" in item and item["dir"] not in ("req", "resp", "unsol"):
                self.err("step-event", cfg, f"{where}.dir은 req|resp|unsol이어야 합니다: {item['dir']!r}")

    def _builtin_events(self) -> set[str]:
        name = (self.defaults.get("parser") or {}).get("backend")
        try:
            return set(parser_backends.load(name).builtin_events())
        except parser_backends.BackendError:
            return set()

    def _validators(self) -> dict:
        import jsonschema

        out = {}
        for name in ("type", "jira", "feedback", "expect"):
            path = self.root / "schema" / f"{name}.schema.json"
            if path.is_file():
                out[name] = jsonschema.Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
            else:
                self.err("schema", f"schema/{name}.schema.json", "스키마 파일이 없습니다.")
        return out

    def _validate(self, kind: str, data, path) -> bool:
        validator = self.validators.get(kind)
        if validator is None:
            return True
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
        for error in errors[:3]:
            where = "/".join(str(p) for p in error.absolute_path) or "(최상위)"
            self.err("schema", path, f"{kind} 스키마: {where}: {error.message}")
        return not errors

    def _glossary(self) -> list[tuple[str, str]]:
        path = self.root / "GLOSSARY.md"
        if not path.is_file():
            return []
        pairs, in_section = [], False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                in_section = line.strip() == "## 표준 용어"
                continue
            if not in_section or not line.startswith("|") or set(line) <= set("|-: "):
                continue
            cols = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cols) < 3 or cols[0] == "표준어":
                continue
            pairs += [(bad.strip(), cols[0]) for bad in cols[2].split(",") if bad.strip()]
        return pairs

    # 유형 -----------------------------------------------------------------------

    def _stray_types(self) -> None:
        for path in sorted(self.root.glob("*/*/type.md")):
            if path.parent.parent.name not in self.categories and not path.parent.parent.name.startswith("."):
                self.err("category", path, f"카테고리 '{path.parent.parent.name}'이(가) categories에 없습니다.")

    def _check_ids(self) -> None:
        seen: dict[str, Path] = {}
        for type_md, data in self.types:
            ids = [str(data.get("id"))] + [str(c.get("id")) for c in data.get("causes") or [] if isinstance(c, dict)]
            for ident in ids:
                # 같은 type.md 안의 중복도 잡는다(두 PR이 같은 원인 번호를 추가한 채 차례로 머지된 경우)
                if ident in seen:
                    files = [type_md] if seen[ident] == type_md else [type_md, seen[ident]]
                    self.err("duplicate-id", files, f"ID {ident}가 두 번 정의돼 있습니다.")
                seen.setdefault(ident, type_md)

    def _check_type(self, type_md: Path, data: dict) -> None:
        self._validate("type", data, type_md)
        type_id = str(data.get("id"))
        cat_key = type_md.parent.parent.name
        category = self.categories.get(cat_key)
        if data.get("category") != cat_key:
            self.err("category", type_md, f"category '{data.get('category')}'가 디렉토리 '{cat_key}'와 다릅니다.")
        if not TYPE_ID_RE.fullmatch(type_id):
            self.err("id-format", type_md, f"유형 ID 형식이 아닙니다: {type_id}")
        elif category and type_id.split("-")[0] != category.get("id_prefix"):
            self.err("id-prefix", type_md,
                     f"{type_id}의 접두어가 카테고리 {cat_key}의 id_prefix '{category.get('id_prefix')}'와 다릅니다.")
        dirname = type_md.parent.name
        if not dirname.startswith(type_id + "-") or not KEBAB_RE.match(dirname[len(type_id) + 1:]):
            self.err("type-dir", type_md, f"유형 디렉토리 이름은 '{type_id}-<영문 kebab-case>'여야 합니다: {dirname}")
        if "signatures_pending" in data:
            self.err("pending-on-type", type_md, "signatures_pending은 원인에만 둔다. 유형의 증상 시그니처는 필수다.")
        if not data.get("symptom_signatures"):
            self.err("symptom-missing", type_md, f"{type_id}: 증상 시그니처(symptom_signatures)가 없습니다.")
        self._merged(type_md, data.get("status"), type_id)
        self._title(type_md, type_id, data.get("title"), TYPE_TITLE_MAX)
        body = type_md.read_text(encoding="utf-8").split("\n---\n", 1)
        if len(body) == 2:
            for hit in masking.new_masker().find(body[1]):
                self.err("raw-identifier", type_md, f"본문에 마스킹되지 않은 {hit['kind']}가 있습니다.")
                break
        for kind in SIG_KINDS[:1]:
            for sig in data.get(kind) or []:
                self._check_signature(type_md, type_id, sig)

        causes = [c for c in data.get("causes") or [] if isinstance(c, dict)]
        positives = self._check_fixtures(type_md, type_id, {str(c.get("id")) for c in causes})
        for cause in causes:
            self._check_cause(type_md, type_id, cause, positives)

    def _title(self, path, ident, title, limit) -> None:
        title = str(title or "")
        if len(title) > limit:
            self.warn("title-length", path, f"{ident} 제목이 {limit}자를 넘습니다({len(title)}자).")
        for bad, good in self.glossary:
            if bad in title:
                self.warn("glossary", path, f"{ident} 제목의 '{bad}' 대신 표준어 '{good}'를 쓴다 (GLOSSARY.md).")

    def _merged(self, path, status, ident) -> None:
        status = str(status or "")
        if status.startswith("merged-into:"):
            target = status.split(":", 1)[1]
            known = {str(d.get("id")) for _, d in self.types} | set(self.cause_owner)
            if target not in known:
                self.err("merged-into", path, f"{ident}의 병합 대상 {target}가 없습니다.")

    def _check_cause(self, type_md: Path, type_id: str, cause: dict, positives: set[str]) -> None:
        cid = str(cause.get("id"))
        if not CAUSE_ID_RE.fullmatch(cid):
            self.err("id-format", type_md, f"원인 ID 형식이 아닙니다: {cid}")
        elif not cid.startswith(type_id + "-"):
            self.err("id-prefix", type_md, f"원인 {cid}는 유형 {type_id}로 시작해야 합니다.")
        self._merged(type_md, cause.get("status"), cid)
        self._title(type_md, cid, cause.get("title"), CAUSE_TITLE_MAX)
        pending = bool(cause.get("signatures_pending"))
        if not cause.get("signatures"):
            if pending:
                self.warn("signatures-pending", type_md, f"{cid}: 판별 시그니처가 없습니다(signatures_pending).")
            else:
                self.err("signatures-missing", type_md,
                         f"{cid}: 판별 시그니처가 없습니다. 수동 기록이면 signatures_pending: true가 있어야 한다.")
        verification = cause.get("resolution_verification") or {}
        if pending and verification.get("status") != "unverified":
            self.err("pending-verified", type_md, f"{cid}: signatures_pending 원인의 해결책은 unverified로 둔다.")
        for kind in SIG_KINDS[1:]:
            for sig in cause.get(kind) or []:
                self._check_signature(type_md, cid, sig)
        for rid in cause.get("related") or []:
            rid = str(rid)
            owner = self.cause_owner.get(rid)
            if owner is None:
                self.err("related", type_md, f"{cid}의 related {rid}가 없습니다.")
                continue
            other = next((c for c in owner[1].get("causes") or [] if str(c.get("id")) == rid), {})
            if cid not in [str(x) for x in other.get("related") or []]:
                self.err("related", [type_md, owner[0]], f"{cid} → {rid} related가 한쪽에만 있습니다(양방향이어야 한다).")
        for ref in cause.get("code_refs") or []:
            self._check_code_ref(type_md, cid, ref)
        fix = cause.get("fix") or {}
        if fix.get("ref") and self.fix_ref_re and not self.fix_ref_re.fullmatch(str(fix["ref"])):
            self.err("fix-ref", type_md, f"{cid}: fix.ref '{fix['ref']}'가 fix_ref_regex에 맞지 않습니다.")
        if verification.get("status") == "verified":
            evidence = verification.get("evidence") or []
            if not evidence:
                self.err("verified-without-evidence", type_md, f"{cid}: 근거(evidence) 없이 verified입니다.")
            for item in evidence:
                self._check_evidence(type_md, cid, str(item))
        if fix.get("status") == "fixed":
            if (fix.get("verification") or {}).get("result") != "passed":
                self.err("fixed-without-verification", type_md,
                         f"{cid}: fixed인데 verification(result: passed)이 없다 (verify-fix로만 fixed가 된다).")
            if (cause.get("resolution_type") in CODE_FIX_TYPES
                    and not (cause.get("scenario_signatures") or cause.get("recovery_signatures"))):
                self.err("fixed-without-trace", type_md,
                         f"{cid}: 코드·설정 수정 유형({cause.get('resolution_type')})의 fixed에는 scenario_signatures 또는 "
                         "recovery_signatures가 있어야 한다.")
        fixture = (fix.get("verification") or {}).get("fixture")
        if fixture and not (type_md.parent / fixture).is_file():
            self.err("evidence-missing", type_md, f"{cid}: fix.verification.fixture {fixture}가 없습니다.")
        if cause.get("cp_evidence"):
            for hit in masking.new_masker().find(str(cause["cp_evidence"])):
                self.err("raw-identifier", type_md, f"{cid}: cp_evidence에 마스킹되지 않은 {hit['kind']}가 있습니다.")
                break
        if cause.get("status") == "active" and not pending and cid not in positives:
            self.warn("fixture-missing", type_md, f"{cid}: 양성 fixture가 없습니다 (R1·R2 skipped, 리뷰 대상).")
        if (self.base_causes is not None and cid not in self.base_causes
                and fix.get("status") == "fixed"):
            self.err("new-cause-fixed", type_md, f"{cid}: 새 원인은 fixed로 시작할 수 없다 (verify-fix를 거친다).")

    def _check_code_ref(self, type_md, cid, ref) -> None:
        text = str((ref or {}).get("ref") if isinstance(ref, dict) else ref)
        key, sep, rel = text.partition(":")
        if (not sep or not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", text)
                or text.startswith("/") or ".." in Path(rel).parts):
            self.err("code-ref", type_md, f"{cid}: code_refs '{text}'는 '<root 키>:<루트 기준 상대 경로>'여야 합니다(절대 경로 금지).")
        elif self.root_keys and key not in self.root_keys:
            self.err("code-ref", type_md, f"{cid}: code_refs root 키 '{key}'가 code_root_keys에 없습니다.")

    def _check_evidence(self, type_md, cid, item) -> None:
        if item.startswith("fixtures/"):
            if not (type_md.parent / item).is_file():
                self.err("evidence-missing", type_md, f"{cid}: evidence fixture {item}가 없습니다.")
            return
        if self.key_re and self.key_re.fullmatch(item):
            path = type_md.parent / "jira" / f"{item}.yaml"
            record = yamlio.load(path) if path.is_file() else None
            if not record or str(record.get("cause")) != cid:
                self.err("evidence-missing", type_md, f"{cid}: evidence Jira {item}가 이 원인의 Jira 기록으로 없습니다.")
            return
        self.err("evidence-missing", type_md, f"{cid}: evidence '{item}'는 Jira 키나 fixtures/ 경로가 아닙니다.")

    # 시그니처 --------------------------------------------------------------------

    def _check_signature(self, type_md, owner, sig) -> None:
        if not isinstance(sig, dict):
            self.err("signature", type_md, f"{owner}: 시그니처 형식이 아닙니다.")
            return
        key = f"{owner}/{sig.get('id')}"
        positives = [c for c in (sig.get("must_match") or []) if isinstance(c, dict)] + \
            [c for c in (sig.get("must_event") or []) if isinstance(c, dict)]
        ids = [str(c["id"]) for c in positives if c.get("id")]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            self.err("sequence", type_md, f"{key}: 조건 id가 겹칩니다: {dupes}")
        not_ids = {str(c.get("id")) for c in sig.get("must_not_match") or [] if isinstance(c, dict)}
        for item in sig.get("sequence") or []:
            if str(item) in not_ids:
                self.err("sequence", type_md, f"{key}: sequence가 must_not_match 조건 '{item}'을 참조합니다.")
            elif str(item) not in ids:
                self.err("sequence", type_md, f"{key}: sequence의 id '{item}'가 조건에 없습니다.")
        if not dupes and not any(str(s) not in ids for s in sig.get("sequence") or []):
            try:
                compile_signature(sig, owner)
            except SignatureError as exc:
                self.err("signature", type_md, str(exc))
        patterns = []
        for item in sig.get("must_match") or []:
            patterns.append(item.get("pattern") if isinstance(item, dict) else item)
        for item in sig.get("must_not_match") or []:
            patterns.append(item.get("pattern") if isinstance(item, dict) else item)
        for item in sig.get("must_event") or []:
            if not isinstance(item, dict):
                continue
            patterns += [str(v) for v in (item.get("fields") or {}).values()]
            self._check_event_name(type_md, key, str(item.get("event", "")))
        for pattern in patterns:
            self._check_pattern(type_md, key, str(pattern))

    def _check_event_name(self, type_md, key, name) -> None:
        if name.startswith("builtin.") and name not in self.builtin_events:
            self.err("builtin-event", type_md, f"{key}: {name}가 현재 파서 백엔드의 builtin_events()에 없습니다.")
        elif name.startswith("ext."):
            category = name.split(".")[1] if name.count(".") >= 2 else ""
            if category not in self.external_cats:
                self.err("ext-event", type_md,
                         f"{key}: {name} — 카테고리 '{category}'가 이슈 DB external_parsers에 없습니다.")

    def _check_pattern(self, path, key, pattern) -> None:
        reason = raw_identifier_in_pattern(pattern)
        if reason:
            self.err("raw-identifier", path, f"{key}: 패턴 {pattern!r}에 {reason} — 마스킹된 로그 기준으로 쓴다.")
        if TOKEN_FIXED_RE.search(pattern):
            self.warn("fixed-token", path, f"{key}: 패턴 {pattern!r}이 특정 마스킹 번호를 고정합니다. "
                                           "<CELL#\\d+>처럼 종류로 쓴다.")
        unsafe = unsafe_regex(pattern)
        if unsafe:
            self.err("regex-unsafe", path, f"{key}: 패턴 {pattern!r}에 {unsafe}이(가) 있습니다.")

    # fixture ---------------------------------------------------------------------

    def _check_fixtures(self, type_md, type_id, cause_ids: set[str]) -> set[str]:
        positives: set[str] = set()
        fixture_dir = type_md.parent / "fixtures"
        if not fixture_dir.is_dir():
            return positives
        synthetic_ok = bool(self.defaults.get("synthetic_allowed", False))
        for path in sorted(p for p in fixture_dir.iterdir() if p.is_file()):
            fx = parse_name(path.name)
            if fx is None:
                self.err("fixture-name", path, f"fixture 이름이 규칙 밖입니다: {path.name} (contracts.md §fixture)")
                continue
            if fx.type_id != type_id or (fx.cause and fx.cause not in cause_ids):
                self.err("fixture-owner", path, f"{path.name}가 가리키는 유형·원인이 {type_id}에 없습니다.")
                continue
            if fx.suffix == ".log":
                if fx.kind == "positive" and fx.cause:
                    positives.add(fx.cause)
                continue
            if not path.with_name(fx.stem + ".log").is_file():
                self.err("fixture-orphan", path, f"{path.name}에 맞는 .log가 없습니다.")
            data = yamlio.load(path) or {}
            if not self._validate("expect", data, path):
                continue
            target = data.get("expect_top") or fx.cause
            for other in data.get("also_allowed") or []:
                other = str(other)
                if other == target or other == fx.cause:
                    self.err("also-allowed", path, f"also_allowed에 대상 원인 자신({other})이 있습니다.")
                elif other.startswith(type_id + "-"):
                    self.err("also-allowed", path, f"also_allowed에 같은 유형의 원인({other})이 있습니다.")
                elif other not in self.cause_owner:
                    self.err("also-allowed", path, f"also_allowed의 {other}가 없습니다.")
            if data.get("origin") == "synthetic" and not synthetic_ok:
                self.warn("synthetic", path, "합성 fixture(origin: synthetic)가 있습니다 (synthetic_allowed: false).")
        return positives

    # Jira·피드백·규칙 --------------------------------------------------------------

    def _check_jira(self) -> None:
        seen: dict[str, Path] = {}
        for type_md, data in self.types:
            type_id = str(data.get("id"))
            causes = {str(c.get("id")) for c in data.get("causes") or [] if isinstance(c, dict)}
            for path in sorted((type_md.parent / "jira").glob("*.yaml")):
                record = yamlio.load(path)
                if not isinstance(record, dict):
                    self.err("schema", path, "Jira 기록이 매핑이 아닙니다.")
                    continue
                self._validate("jira", record, path)
                key = str(record.get("key"))
                if self.key_re and not self.key_re.fullmatch(key):
                    self.err("jira-key", path, f"Jira 키 {key}가 jira_key_regex에 맞지 않습니다.")
                if path.stem != key:
                    self.err("jira-key", path, f"파일 이름({path.name})이 키({key})와 다릅니다.")
                if key in seen:
                    self.err("duplicate-jira", [path, seen[key]], f"Jira {key}가 두 곳에 있습니다.")
                seen.setdefault(key, path)
                cause = str(record.get("cause"))
                if cause != "unresolved" and cause not in causes:
                    self.err("jira-cause", path, f"cause {cause}가 유형 {type_id}의 원인이 아닙니다.")
                for field in ("note", "failed_step"):
                    if record.get(field):
                        for hit in masking.new_masker().find(str(record[field])):
                            self.err("raw-identifier", path, f"{field}에 마스킹되지 않은 {hit['kind']}가 있습니다.")
                            break

    def _check_feedback(self) -> None:
        for path in sorted((self.root / "feedback").glob("*/*.yaml")):
            record = yamlio.load(path)
            self._validate("feedback", record if record is not None else {}, path)

    def _check_rules(self) -> None:
        rules_dir = self.root / "parser-rules"
        if not rules_dir.is_dir():
            self.err("parser-rules", "parser-rules", "parser-rules/가 없습니다.")
            return
        try:
            parser_rules.load(rules_dir)
        except parser_rules.RulesError as exc:
            self.err("parser-rules", "parser-rules/extractors.yaml", str(exc))
        path = rules_dir / "extractors.yaml"
        data = yamlio.load(path) if path.is_file() else {}
        for item in (data or {}).get("extractors") or []:
            if isinstance(item, dict):
                for pattern in item.get("patterns") or []:
                    self._check_pattern(path, f"extractor {item.get('id')}", str(pattern))
        path = rules_dir / "tags.yaml"
        data = yamlio.load(path) if path.is_file() else {}
        for item in (data or {}).get("tags") or []:
            if isinstance(item, dict) and item.get("tag_regex"):
                unsafe = unsafe_regex(str(item["tag_regex"]))
                if unsafe:
                    self.err("regex-unsafe", path, f"tag_regex {item['tag_regex']!r}에 {unsafe}이(가) 있습니다.")

    def _check_residual(self) -> None:
        if not self.residual:
            return
        files = sorted(p for p in self.root.rglob("*") if p.is_file() and ".git" not in p.parts
                       and ".cache" not in p.parts)
        for old, new in self.residual:
            pattern = re.compile(rf"(?<![\w-]){re.escape(old)}(?![0-9A-Za-z_])")
            for path in files:
                rel = path.relative_to(self.root).as_posix()
                if self.scope is not None and rel not in self.scope:
                    continue
                hit_name = pattern.search(rel)
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                if pattern.search(text) or hit_name:
                    self.err("residual-id", path, f"옛 ID {old}가 남아 있습니다 (→ {new}).")


# -- 실행 -----------------------------------------------------------------------------


def _base_causes(root: Path) -> set[str] | None:
    try:
        db = issuedb.load(root)
    except issuedb.IssueDbError:
        return None
    return {c.id for t in db.types for c in t.causes}


def run(args, defaults: dict) -> tuple[dict, int]:
    try:
        repo = dbpath.resolve(args.db)
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc
    residual = []
    for item in args.residual or []:
        old, sep, new = item.partition("=")
        if not sep or not old or not new:
            raise UsageError(f"--residual은 <옛 ID>=<새 ID> 형식이다: {item}")
        residual.append((old, new))

    temp = Path(tempfile.mkdtemp(prefix="tt-lint-"))
    try:
        root, scope, base = repo, None, None
        try:
            if args.ref:
                root = gitscope.materialize_ref(repo, args.ref, temp / "ref")
            elif args.staged:
                scope = set(gitscope.staged_files(repo))
                root = gitscope.materialize_index(repo, temp / "index")
                if gitscope.has_ref(repo, "HEAD"):
                    base = _base_causes(gitscope.materialize_ref(repo, "HEAD", temp / "base"))
            elif args.changed:
                scope = set(gitscope.changed_files(repo, args.changed))
                base = _base_causes(gitscope.materialize_ref(repo, gitscope.merge_base(repo, args.changed),
                                                             temp / "base"))
        except gitscope.GitError as exc:
            raise UsageError(str(exc)) from exc
        result = Linter(root, defaults, base_causes=base, residual=residual, scope=scope).run()
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    result["summary"]["scope"] = ("ref:" + args.ref if args.ref else "staged" if args.staged
                                  else "changed:" + args.changed if args.changed else "all")
    return result, (CHECK_FAILED if result["errors"] else OK)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db_lint.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true")
    scope.add_argument("--ref", metavar="ref")
    scope.add_argument("--changed", metavar="ref")
    scope.add_argument("--staged", action="store_true")
    parser.add_argument("--residual", action="append", metavar="옛 ID=새 ID")
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
        result, code = run(args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for f in result["errors"] + result["warnings"]:
        print(f"{'오류' if f['level'] == 'error' else '경고'}[{f['code']}] {f['file']}: {f['message']}",
              file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
