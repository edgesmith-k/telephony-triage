#!/usr/bin/env python3
"""db_add.py — 작업 계획 적용·drift 검사·ID 도구 (contracts.md §작업 계획, §renumber 참조, 01-architecture.md §3.1).

    db_add.py apply <plan.json> [--db <path>] [--pending <file>...] [--user <GHE 아이디>]
    db_add.py drift <plan.json> --onto <ref> [--db <path>]
    db_add.py renumber <옛 ID> [--base <ref>] [--db <path>]
    db_add.py check-ids [--base <ref>] [--db <path>]
    db_add.py similar <title> [--category <key>] [--symptom-json <file>] [--db <path>]

`apply` (db_pr stage가 `<wt>`에서 부른다)
- 계획 형식은 이슈 DB `schema/plan.schema.json`으로 검사한다. `source`가 허용 값 밖이면 거부(종료 코드 2).
  `schema_version`이 이슈 DB와 다르면 종료 코드 2 (`db_migrate upgrade-plan` 안내).
- 임시 ID(`NEW-TYPE-<n>`, `NEW-CAUSE-<n>`)는 **적용 대상 트리 기준 다음 번호**(최댓값 + 1)로 할당하고, 계획 안의
  모든 참조(op 필드, fixture 경로, 피드백, 커밋 메시지)를 치환한다. fixture 번호도 적용 시점에 정한다.
- 계획에서 fixture를 가리키는 값(`verify-resolution`의 evidence, `verify-fix`·`update-fix` history의 fixture,
  `allow-cause`의 fixture)이 같은 계획 `add-fixture`의 `path`와 같으면 할당된 `fixtures/<이름>`으로 바꾼다.
- op는 순서대로 메모리에서 적용하고, 거부가 없을 때만 파일에 쓴다. 거부는 종료 코드 1과 `rejected`.
- type.md와 parser-rules는 엔티티 단위로 다시 쓴다(`common/typedoc.py`, `common/yamldoc.py`).
- fixture와 Jira `note`는 마스킹 함수를 거쳐 쓴다(멱등).
- 피드백은 계획 `feedback`으로 `feedback/<YYYY-MM>/<KEY>-<YYYYMMDDTHHMM>.yaml`(시각은 `feedback.date`).
  `--pending`(pending 피드백)은 `source: analyze`일 때만 받는다.

`drift`: 계획의 `base_sha` 트리와 `<ref>` 트리를 비교해 계획 대상이 바뀐 목록을 낸다(contracts.md §작업 계획
drift 표). 아무것도 바꾸지 않는다. drift가 있으면 종료 코드 1.

`renumber`: 직접 편집한 브랜치에서 "내 ID"(merge-base에 없던 ID)만 다음 빈 번호로 옮긴다(§renumber 참조).
`check-ids`: 트리 안 ID 중복과, `--base`면 내 ID가 그 ref에 이미 있는지. 있으면 종료 코드 1.
`similar`: 전체 카테고리에서 제목·증상 시그니처가 비슷한 유형 상위 3개.

사용자 아이디(`analyzed_by`, `by`)는 `--user` 또는 사용자 config `user.ghe_id`.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import jsonschema  # noqa: E402

from common import dbpath, gitscope, issuedb, masking, site_defaults, userconfig, yamldoc, yamlio  # noqa: E402
from common.buildname import sanitize_build  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from common.fixtures import parse_name  # noqa: E402
from common.typedoc import TypeDoc, TypeDocError, id_key  # noqa: E402

TEMP_RE = re.compile(r"NEW-(?:CAUSE|TYPE)-\d+(?!\d)")
TYPE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d{3}$")
CAUSE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d{3}-\d{2}$")
RULE_SECTIONS = {"tags.yaml": ("tags",), "ril.yaml": ("requests", "unsolicited"), "extractors.yaml": ("extractors",)}
RULE_KEYS = {"tags": ("tag", "tag_regex"), "requests": ("name",), "unsolicited": ("name",), "extractors": ("id",)}
HISTORY_FIELDS = ("added_for", "added_on", "reason")
SIG_LISTS = {"symptom": "symptom_signatures", "cause": "signatures", "recovery": "recovery_signatures",
             "scenario": "scenario_signatures"}
CAUSE_KEYS_DEFAULT = ["id", "status", "title", "description", "signatures", "recovery_signatures",
                      "scenario_signatures", "resolution", "resolution_type", "resolution_verification", "fix",
                      "related", "android_versions", "code_refs"]
TYPE_KEYS = ["id", "category", "secondary_categories", "title", "summary", "status", "symptom_signatures",
             "causes", "tags"]
FIXTURE_REF_KINDS = ("positive", "recurrence", "extra")
GENERATED = ("README.md", "STATS.md", "parser-rules/CHANGELOG.md")


class UsageError(Exception):
    pass


class Reject(Exception):
    def __init__(self, code: str, message: str, op_index: int | None = None, **detail):
        super().__init__(message)
        self.code, self.message, self.op_index, self.detail = code, message, op_index, detail

    def as_dict(self) -> dict:
        return {"code": self.code, "op_index": self.op_index, "message": self.message, **self.detail}


# -- 공통 -----------------------------------------------------------------------------


def load_plan(path: Path) -> dict:
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"계획을 읽을 수 없습니다: {path}: {exc}") from exc
    if not isinstance(plan, dict):
        raise UsageError(f"계획이 JSON 객체가 아닙니다: {path}")
    return plan


def validate_plan(plan: dict, db: Path) -> None:
    schema_path = db / "schema" / "plan.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"계획 스키마를 읽을 수 없습니다: {schema_path}: {exc}") from exc
    allowed = schema.get("properties", {}).get("source", {}).get("enum") or []
    if plan.get("source") not in allowed:
        raise UsageError(f"계획 source '{plan.get('source')}'는 허용 값이 아닙니다 ({', '.join(allowed)}). "
                         "마이그레이션·새 카테고리·사후 정리는 계획이 아니라 직접 편집 브랜치다 (contracts.md §브랜치).")
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(plan), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "(최상위)"
        raise UsageError(f"계획 형식 오류 ({where}): {first.message[:300]}")


def user_id(arg: str | None, defaults: dict) -> str:
    value = arg or userconfig.get(userconfig.merged(defaults), "user.ghe_id")
    if not value:
        raise UsageError("사용자 아이디가 없습니다 (--user 또는 config user.ghe_id, setup 1).")
    return str(value)


def plan_day(plan: dict) -> str:
    jira = plan.get("jira") or {}
    return str(jira.get("date") or str(plan.get("started_at", ""))[:10])


def _category_prefix(config: dict) -> dict[str, str]:
    return {c["key"]: c["id_prefix"] for c in config.get("categories") or [] if isinstance(c, dict)}


def _num(ident: str) -> int:
    return int(ident.rsplit("-", 1)[1])


# -- 트리 (적용 대상, 메모리) ----------------------------------------------------------


class Tree:
    """적용 대상 이슈 DB. 유형 문서는 `TypeDoc`, 그 밖의 쓰기는 `writes`/`deletes`에 모았다가 `flush()`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        try:
            self.config = issuedb.load_config(self.root)
        except issuedb.IssueDbError as exc:
            raise UsageError(str(exc)) from exc
        self.docs: dict[str, TypeDoc] = {}
        self.categories = _category_prefix(self.config)
        for path in issuedb.type_files(self.root, self.config):
            try:
                doc = TypeDoc(path)
            except TypeDocError as exc:
                raise UsageError(f"{path}: {exc}") from exc
            self.docs[doc.id] = doc
        self.writes: dict[Path, str] = {}
        self.deletes: set[Path] = set()
        self.base_jira = {p.stem: p for p in self.root.glob("*/*/jira/*.yaml")}
        self.rule_docs: dict[str, dict] = {}

    # 조회
    def type_dir(self, type_id: str) -> Path:
        return self.docs[type_id].path.parent

    def cause(self, cause_id: str) -> tuple[TypeDoc, dict] | tuple[None, None]:
        type_id = cause_id.rsplit("-", 1)[0]
        doc = self.docs.get(type_id)
        if doc is None:
            return None, None
        return doc, doc.cause(cause_id)

    def exists(self, path: Path) -> bool:
        if path in self.deletes:
            return False
        return path in self.writes or path.is_file()

    def read(self, path: Path) -> str | None:
        if path in self.deletes:
            return None
        if path in self.writes:
            return self.writes[path]
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def jira_files(self) -> dict[str, Path]:
        found = {p.stem: p for p in self.root.glob("*/*/jira/*.yaml") if p not in self.deletes}
        for p in self.writes:
            if p.parent.name == "jira" and p.suffix == ".yaml":
                found[p.stem] = p
        return found

    def write(self, path: Path, text: str) -> None:
        self.deletes.discard(path)
        self.writes[path] = text

    def delete(self, path: Path) -> None:
        self.writes.pop(path, None)
        self.deletes.add(path)

    def rel(self, path: Path) -> str:
        return Path(path).relative_to(self.root).as_posix()

    def flush(self) -> list[dict]:
        changes = []
        for path in sorted(self.deletes):
            if path.is_file():
                path.unlink()
                changes.append({"path": self.rel(path), "change": "deleted"})
        for path, text in sorted(self.writes.items()):
            existed = path.is_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            changes.append({"path": self.rel(path), "change": "modified" if existed else "new"})
        for doc in self.docs.values():
            existed = doc.path.is_file()
            if doc.save():
                changes.append({"path": self.rel(doc.path), "change": "modified" if existed else "new"})
        return sorted(changes, key=lambda c: c["path"])


# -- apply ----------------------------------------------------------------------------


class Applier:
    def __init__(self, tree: Tree, plan: dict, plan_path: Path, user: str, defaults: dict):
        self.tree = tree
        self.plan = plan
        self.plan_dir = Path(plan_path).resolve().parent
        self.user = user
        self.defaults = defaults
        self.source = plan["source"]
        self.config = tree.config
        self.day = plan_day(plan)
        self.mapping: dict[str, str] = {}
        self.fixture_names: dict[int, tuple[str, str]] = {}   # op index → (유형 ID, 이름)
        self.fixture_paths: dict[str, str] = {}               # 계획 path → fixtures/<이름>
        self.created: set[str] = set()                         # 이 계획이 만든 원인·유형 (적용된 것)
        self.new_ids: set[str] = set()                         # 이 계획이 만들 원인·유형 (전체)
        self.jira_checks: list[tuple[int, str, str]] = []      # (op, cause, Jira 키) 적용 후 확인
        self.warnings: list[str] = []
        self.allow = [str(p) for p in ((self.config.get("mask") or {}).get("allow_patterns") or [])]
        self.key_re = re.compile(str(self.config.get("jira_key_regex") or r"[A-Z][A-Z0-9]+-\d+"))
        ref_re = self.config.get("fix_ref_regex")
        self.fix_ref_re = re.compile(str(ref_re)) if ref_re else None

    # 임시 ID ---------------------------------------------------------------------------

    def assign_ids(self) -> list[dict]:
        next_type: dict[str, int] = {}
        for doc in self.tree.docs.values():
            cat = str(doc.data.get("category"))
            next_type[cat] = max(next_type.get(cat, 0), _num(doc.id))
        next_cause = {tid: max(doc.cause_numbers() or [0]) for tid, doc in self.tree.docs.items()}
        out = []
        for i, op in enumerate(self.plan["operations"]):
            if op["op"] == "new-type":
                cat = op["category"]
                if cat not in self.tree.categories:
                    raise Reject("category", f"카테고리 {cat}가 issue-db.config.yaml categories에 없습니다.", i)
                n = next_type.get(cat, 0) + 1
                next_type[cat] = n
                tid = f"{self.tree.categories[cat]}-{n:03d}"
                self._map(op["temp_id"], tid, i, out)
                self._map(op["first_cause"]["temp_id"], f"{tid}-01", i, out)
                next_cause[tid] = 1
            elif op["op"] == "new-cause":
                tid = self.mapping.get(op["type"], op["type"])
                if tid not in next_cause:
                    raise Reject("unknown-type", f"유형 {op['type']}가 없습니다.", i)
                n = next_cause[tid] + 1
                if n > 99:
                    raise Reject("id-overflow", f"유형 {tid}의 원인 번호가 99를 넘습니다.", i)
                next_cause[tid] = n
                self._map(op["temp_id"], f"{tid}-{n:02d}", i, out)
        self.new_ids = set(self.mapping.values())
        return out

    def _map(self, temp: str, real: str, i: int, out: list) -> None:
        if temp in self.mapping:
            raise Reject("duplicate-temp-id", f"임시 ID {temp}가 두 번 정의됐습니다.", i)
        self.mapping[temp] = real
        out.append({"temp_id": temp, "id": real})

    def substitute(self, value):
        if isinstance(value, str):
            def repl(m):
                if m.group(0) not in self.mapping:
                    raise Reject("unknown-temp-id", f"정의되지 않은 임시 ID {m.group(0)}를 참조합니다.")
                return self.mapping[m.group(0)]
            return TEMP_RE.sub(repl, value)
        if isinstance(value, list):
            return [self.substitute(v) for v in value]
        if isinstance(value, dict):
            return {k: self.substitute(v) for k, v in value.items()}
        return value

    # fixture 이름 --------------------------------------------------------------------

    def assign_fixtures(self, ops: list[dict]) -> list[dict]:
        taken: dict[Path, set[str]] = {}
        out = []
        for i, op in enumerate(ops):
            if op["op"] != "add-fixture":
                continue
            kind, target = op["kind"], op["for"]
            if kind == "negative":
                if not TYPE_ID_RE.match(target):
                    raise Reject("fixture-for", f"negative fixture의 for는 유형 ID여야 합니다: {target}", i)
                type_id = target
            else:
                if not CAUSE_ID_RE.match(target):
                    raise Reject("fixture-for", f"{kind} fixture의 for는 원인 ID여야 합니다: {target}", i)
                type_id = target.rsplit("-", 1)[0]
            if type_id not in self.tree.docs and type_id not in self.new_ids:
                raise Reject("unknown-type", f"fixture 대상 유형 {type_id}가 없습니다.", i)
            fdir = self._fixture_dir(type_id, ops)
            names = taken.setdefault(fdir, {p.name for p in fdir.glob("*")} if fdir.is_dir() else set())
            name = self._fixture_name(kind, target, op.get("build"), names, i)
            names.add(name)
            self.fixture_names[i] = (type_id, name)
            self.fixture_paths[op["path"]] = f"fixtures/{name}"
            out.append({"op_index": i, "for": target, "kind": kind, "name": name, "path": f"fixtures/{name}"})
        return out

    def _fixture_dir(self, type_id: str, ops: list[dict]) -> Path:
        if type_id in self.tree.docs:
            return self.tree.type_dir(type_id) / "fixtures"
        for op in ops:
            if op["op"] == "new-type" and self.mapping.get(op["temp_id"]) == type_id:
                return self.tree.root / op["category"] / f"{type_id}-{op['dir_slug']}" / "fixtures"
            if op["op"] == "new-type" and op["temp_id"] == type_id:
                return self.tree.root / op["category"] / f"{type_id}-{op['dir_slug']}" / "fixtures"
        raise Reject("unknown-type", f"fixture 대상 유형 {type_id}가 없습니다.")

    @staticmethod
    def _fixture_name(kind: str, target: str, build: str | None, names: set[str], i: int) -> str:
        def free(stem: str) -> bool:
            return f"{stem}.log" not in names

        if kind in ("fixed", "recurrence"):
            if not build:
                raise Reject("fixture-build", f"{kind} fixture에는 build가 필요합니다.", i)
            stem = f"{target}.{kind}.{sanitize_build(build)}"
            if not free(stem):
                raise Reject("fixture-exists", f"같은 이름의 fixture가 이미 있습니다: {stem}.log", i)
            return f"{stem}.log"
        if kind in ("resolved", "extra"):
            n = 1
            while not free(f"{target}.{kind}.{n}"):
                n += 1
            return f"{target}.{kind}.{n}.log"
        base = f"{target}.none" if kind == "negative" else target
        if free(base):
            return f"{base}.log"
        n = 2
        while not free(f"{base}.{n}"):
            n += 1
        return f"{base}.{n}.log"

    def fixture_ref(self, value: str) -> str:
        return self.fixture_paths.get(value, value)

    # 실행 ------------------------------------------------------------------------------

    def run(self, pending: list[Path]) -> dict:
        plan = self.plan
        if plan.get("schema_version") != self.config.get("schema_version"):
            raise UsageError(
                f"계획 schema_version {plan.get('schema_version')}이 이슈 DB {self.config.get('schema_version')}와 "
                "다릅니다. 해당 마이그레이션이 upgrade_plan()을 제공하면 `db_migrate upgrade-plan`으로 계획을 먼저 "
                "올리고, 아니면 계획을 다시 만든다 (06-collaboration.md §6.4).")
        if pending and self.source != "analyze":
            raise UsageError(f"pending 피드백은 source: analyze 계획에만 넣는다 (지금 source: {self.source}).")
        if self.source == "import":
            count = sum(1 for op in plan["operations"] if op["op"] == "new-type")
            if count > 10:
                raise Reject("import-too-many", f"import 계획은 PR당 새 유형 10개 이하입니다 ({count}개).")
        ids = self.assign_ids()
        ops = [self.substitute(op) for op in plan["operations"]]
        feedback = self.substitute(plan.get("feedback")) if plan.get("feedback") else None
        commit = self.substitute(plan.get("commit_message") or "")
        fixtures = self.assign_fixtures(ops)
        self.ops = ops
        for i, op in enumerate(ops):
            try:
                getattr(self, "op_" + op["op"].replace("-", "_"))(i, op)
            except Reject as exc:
                if exc.op_index is None:
                    exc.op_index = i
                raise
        self._post_checks()
        fb_path = self._feedback(feedback)
        included = [self._pending(p) for p in pending]
        return {"ids": ids, "fixtures": fixtures, "commit_message": commit, "feedback": fb_path,
                "pending_included": [p for p in included if p], "operations": ops}

    # Jira ------------------------------------------------------------------------------

    def _jira_record(self, i: int, cause: str, type_id: str) -> None:
        jira = self.plan.get("jira")
        if not jira:
            raise Reject("jira-missing", "계획에 jira가 없습니다 (append·unresolved에는 필요).", i)
        key = jira["key"]
        if not self.key_re.fullmatch(key):
            raise Reject("jira-key", f"Jira 키 {key}가 jira_key_regex에 맞지 않습니다.", i)
        existing = self.tree.jira_files().get(key)
        if existing is not None:
            record = yamlio.loads(self.tree.read(existing) or "") or {}
            raise Reject("jira-exists", f"Jira {key}가 이미 이슈 DB에 있습니다 ({self.tree.rel(existing)}). "
                         "기존 분류를 유지하거나 reclassify로 바꾼다.", i,
                         existing={"path": self.tree.rel(existing), "cause": record.get("cause")})
        missing = [f for f in ("date", "model", "sw", "android_version") if not jira.get(f)]
        if missing:
            raise Reject("jira-fields", f"Jira 기록 필수 필드가 없습니다: {', '.join(missing)}", i)
        record = {"key": key, "cause": cause, "date": jira["date"]}
        if jira.get("occurred_on"):
            record["occurred_on"] = jira["occurred_on"]
        record.update(model=jira["model"], sw=jira["sw"], android_version=str(jira["android_version"]))
        if jira.get("carrier"):
            record["carrier"] = jira["carrier"]
        record["analyzed_by"] = self.user
        if jira.get("note"):
            record["note"] = masking.new_masker(allow_patterns=self.allow).mask(str(jira["note"]))
        path = self.tree.type_dir(type_id) / "jira" / f"{key}.yaml"
        self.tree.write(path, yamldoc.dump_doc(record))

    def op_append(self, i, op):
        doc, cause = self.tree.cause(op["cause"])
        if cause is None:
            raise Reject("unknown-cause", f"원인 {op['cause']}가 없습니다.", i)
        self._jira_record(i, op["cause"], doc.id)

    def op_unresolved(self, i, op):
        if op["type"] not in self.tree.docs:
            raise Reject("unknown-type", f"유형 {op['type']}가 없습니다.", i)
        self._jira_record(i, "unresolved", op["type"])

    def op_reclassify(self, i, op):
        key = op["jira"]
        path = self.tree.base_jira.get(key)
        if path is None or not self.tree.exists(path):
            raise Reject("reclassify-missing", f"Jira {key}가 기준 트리(main)에 없습니다. reclassify는 main에 있는 "
                         "Jira만 옮길 수 있다 (새 Jira는 append·unresolved).", i)
        record = yamlio.loads(self.tree.read(path)) or {}
        if str(record.get("cause")) != op["from"]:
            raise Reject("reclassify-from", f"Jira {key}의 현재 원인은 {record.get('cause')}입니다 (계획 from: "
                         f"{op['from']}).", i, current=record.get("cause"))
        doc, cause = self.tree.cause(op["to"])
        if cause is None:
            raise Reject("unknown-cause", f"원인 {op['to']}가 없습니다.", i)
        record["cause"] = op["to"]
        note = f"reclassified from {op['from']}"
        record["note"] = f"{record['note']}; {note}" if record.get("note") else note
        dest = self.tree.type_dir(doc.id) / "jira" / f"{key}.yaml"
        if dest != path:
            self.tree.delete(path)
        self.tree.write(dest, yamldoc.dump_doc(record))

    # 원인·유형 ------------------------------------------------------------------------

    def _cause_keys(self) -> list[str]:
        path = self.tree.root / "templates" / "cause.yaml"
        keys = []
        if path.is_file():
            keys = re.findall(r"^\s*(?:-\s+)?([a-z_]+):", path.read_text(encoding="utf-8"), flags=re.M)
        return keys or CAUSE_KEYS_DEFAULT

    def _build_cause(self, i: int, cause_id: str, body: dict) -> dict:
        signatures = body.get("signatures") or []
        pending = not signatures
        if pending:
            if not body.get("signatures_pending"):
                raise Reject("signatures-missing", f"새 원인 {cause_id}에 판별 시그니처가 없습니다 "
                             "(signatures_pending은 record에서 사용자가 명시할 때만).", i)
            if self.source != "record":
                raise Reject("pending-not-allowed", f"signatures_pending 원인은 source: record 계획에서만 만들 수 "
                             f"있습니다 (지금 source: {self.source}).", i)
        fix = {"status": "open", "ref": None, "fixed_in": [], "verification": None, "verification_history": []}
        fix.update({k: v for k, v in (body.get("fix") or {}).items() if k in ("status", "ref", "fixed_in")})
        if fix["status"] == "fixed":
            raise Reject("new-cause-fixed", "새 원인은 fixed로 시작할 수 없습니다 (verify-fix로만).", i)
        self._check_fix_ref(i, fix.get("ref"))
        if fix["status"] == "fix-submitted" and (not fix.get("ref") or not fix.get("fixed_in")):
            raise Reject("fix-fields", "fix-submitted에는 ref와 fixed_in이 필요합니다.", i)
        rv = {"status": "unverified"}
        method = (body.get("resolution_verification") or {}).get("method")
        if method:
            rv["method"] = method
        values = {
            "id": cause_id, "status": "active", "title": body["title"], "description": body["description"],
            "signatures": signatures, "recovery_signatures": body.get("recovery_signatures") or [],
            "scenario_signatures": body.get("scenario_signatures") or [], "resolution": body["resolution"],
            "resolution_type": body["resolution_type"], "resolution_verification": rv, "fix": fix,
            "related": [], "android_versions": body.get("android_versions") or [],
            "code_refs": body.get("code_refs") or [],
        }
        for ref in values["code_refs"]:
            self._check_code_ref(i, ref)
        out = {}
        for key in self._cause_keys():
            if key in values:
                out[key] = values.pop(key)
            if key == "signatures" and pending:
                out["signatures_pending"] = True
            if key == "related" and body.get("cp_evidence"):
                out["cp_evidence"] = masking.new_masker(allow_patterns=self.allow).mask(str(body["cp_evidence"]))
        out.update(values)
        return out

    def _link_related(self, i: int, cause_id: str, related: list[str]) -> None:
        for other in related or []:
            self._add_related(i, cause_id, other)

    def op_new_cause(self, i, op):
        type_id = op["type"]
        doc = self.tree.docs.get(type_id)
        if doc is None:
            raise Reject("unknown-type", f"유형 {type_id}가 없습니다.", i)
        cause_id = op["temp_id"]
        cause = self._build_cause(i, cause_id, op["cause"])
        doc.add_cause(cause, cause["title"], op["body"])
        self.created.add(cause_id)
        self._link_related(i, cause_id, op["cause"].get("related"))

    def op_new_type(self, i, op):
        type_id = op["temp_id"]
        spec = op["type"]
        if not spec.get("symptom_signatures"):
            raise Reject("symptom-missing", "새 유형에는 증상 시그니처가 필수입니다 (모든 source).", i)
        cat = op["category"]
        tdir = self.tree.root / cat / f"{type_id}-{op['dir_slug']}"
        if tdir.exists():
            raise Reject("type-dir-exists", f"유형 디렉토리가 이미 있습니다: {self.tree.rel(tdir)}", i)
        first = op["first_cause"]
        cause_id = first["temp_id"]
        cause = self._build_cause(i, cause_id, first["cause"])
        values = {"id": type_id, "category": cat, "secondary_categories": spec.get("secondary_categories") or [],
                  "title": spec["title"], "summary": spec["summary"], "status": "active",
                  "symptom_signatures": spec["symptom_signatures"], "causes": [cause], "tags": spec.get("tags") or []}
        front = {k: values[k] for k in TYPE_KEYS}
        body = op["body"].strip()
        if not body.startswith("## "):
            body = "## 증상\n\n" + body
        text = f"\n{body}\n\n## 원인별 상세\n\n### {cause_id} {cause['title']}\n\n{first['body'].rstrip()}\n"
        doc = TypeDoc.new(tdir / "type.md", front, text)
        self.tree.docs[type_id] = doc
        self.created.update({type_id, cause_id})
        self._link_related(i, cause_id, first["cause"].get("related"))

    def _cause_or_reject(self, i: int, cause_id: str) -> tuple[TypeDoc, dict]:
        doc, cause = self.tree.cause(cause_id)
        if cause is None:
            if cause_id in self.new_ids:
                raise Reject("order", f"원인 {cause_id}는 이 op보다 뒤에서 만들어집니다 (op 순서를 바꾼다).", i)
            raise Reject("unknown-cause", f"원인 {cause_id}가 없습니다.", i)
        return doc, cause

    def _add_related(self, i: int, a: str, b: str) -> None:
        if a == b:
            raise Reject("related-self", f"원인 {a}를 자기 자신과 연결할 수 없습니다.", i)
        _, ca = self._cause_or_reject(i, a)
        _, cb = self._cause_or_reject(i, b)
        for cause, other in ((ca, b), (cb, a)):
            related = list(cause.get("related") or [])
            if other not in related:
                related.append(other)
                cause["related"] = related

    def op_add_related(self, i, op):
        self._add_related(i, op["a"], op["b"])

    def _check_code_ref(self, i: int, ref: dict) -> None:
        value = str(ref.get("ref", ""))
        root_key, _, rel = value.partition(":")
        keys = [str(k) for k in self.config.get("code_root_keys") or []]
        if not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", rel) or root_key not in keys:
            raise Reject("code-ref", f"code_ref는 <root 키>:<상대 경로>이고 root 키는 {keys} 중 하나여야 합니다: "
                         f"{value}", i)

    def op_add_code_ref(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        self._check_code_ref(i, op["code_ref"])
        refs = list(cause.get("code_refs") or [])
        if op["code_ref"] not in refs:
            refs.append(op["code_ref"])
            cause["code_refs"] = refs

    # 수정 상태 ------------------------------------------------------------------------

    def _check_fix_ref(self, i: int, ref) -> None:
        if ref is not None and self.fix_ref_re is not None and not self.fix_ref_re.fullmatch(str(ref)):
            raise Reject("fix-ref", f"fix.ref {ref}가 fix_ref_regex에 맞지 않습니다.", i)

    def _history_item(self, result: str, fix: dict, extra: dict, keep_fix: bool) -> dict:
        item = {"result": result}
        if extra.get("build"):
            item["build"] = extra["build"]
        item.update(date=extra.get("date") or self.day, by=extra.get("by") or self.user)
        if extra.get("jira"):
            item["jira"] = extra["jira"]
        if extra.get("fixture"):
            item["fixture"] = self.fixture_ref(extra["fixture"])
        if keep_fix:
            item["ref"] = fix.get("ref")
            item["fixed_in"] = copy.deepcopy(fix.get("fixed_in") or [])
        if extra.get("note"):
            item["note"] = extra["note"]
        return item

    def _reopen(self, fix: dict, result: str, extra: dict) -> None:
        history = list(fix.get("verification_history") or [])
        history.insert(0, self._history_item(result, fix, extra, keep_fix=True))
        fix.update(status="open", verification=None, ref=None, fixed_in=[], verification_history=history)

    def op_update_fix(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        fix = cause["fix"] = copy.deepcopy(cause.get("fix") or {})
        for key, default in (("ref", None), ("fixed_in", []), ("verification", None), ("verification_history", [])):
            fix.setdefault(key, default)
        new = op["fix"]
        status = new.get("status", fix.get("status"))
        if fix.get("status") == "fixed" and status == "fix-submitted":
            raise Reject("fixed-to-fix-submitted", "fixed 원인을 fix-submitted로 바꿀 수 없습니다. 먼저 verify-fix 실패나 "
                         "회귀 의심으로 open으로 되돌린다.", i)
        if status == "fixed":
            raise Reject("update-fix-fixed", "fixed로 바꾸는 것은 verify-fix op만 할 수 있습니다.", i)
        if status == "open" and fix.get("status") != "open":
            history = op.get("history") or {}
            result = history.get("result") or ("passed" if fix.get("verification") else "reverted")
            self._reopen(fix, result, history)
            return
        if "ref" in new:
            self._check_fix_ref(i, new["ref"])
            fix["ref"] = new["ref"]
        if "fixed_in" in new:
            merged = list(fix.get("fixed_in") or [])
            for entry in new["fixed_in"]:
                same = next((e for e in merged if e.get("branch") == entry.get("branch")), None)
                if same is None:
                    merged.append(dict(entry))
                else:
                    same.update(entry)
            fix["fixed_in"] = merged
        fix["status"] = status
        if status == "fix-submitted" and (not fix.get("ref") or not fix.get("fixed_in")):
            raise Reject("fix-fields", "fix-submitted에는 ref와 fixed_in이 필요합니다.", i)
        if status != "fixed":
            fix["verification"] = None

    def op_verify_fix(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        fix = cause["fix"] = copy.deepcopy(cause.get("fix") or {})
        v = dict(op["verification"])
        v["fixture"] = self.fixture_ref(v["fixture"])
        self._require_fixture(i, op["cause"].rsplit("-", 1)[0], v["fixture"])
        if op["result"] == "passed":
            if fix.get("status") not in ("fix-submitted", "fixed"):
                raise Reject("verify-fix-status", f"verify-fix 통과는 fix-submitted(재검증이면 fixed) 원인만 됩니다 "
                             f"(지금 {fix.get('status')}).", i)
            if not any(e.get("build") for e in fix.get("fixed_in") or []):
                raise Reject("fixed-in-build-missing", "fixed_in에 빌드가 있는 항목이 없습니다. 먼저 fix-submitted로 "
                             "빌드를 추가한다.", i)
            record = {"result": "passed", "build": v["build"], "date": v["date"], "by": v["by"]}
            for key in ("jira", "fixture", "scenario_evidence", "note"):
                if v.get(key):
                    record[key] = v[key]
            fix.update(status="fixed", verification=record)
        elif op["result"] == "failed":
            self._reopen(fix, "failed", v)
        else:
            history = list(fix.get("verification_history") or [])
            history.insert(0, self._history_item("partial", fix, v, keep_fix=False))
            fix["verification_history"] = history

    # 해결책 --------------------------------------------------------------------------

    def op_set_resolution(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        cause["resolution"] = op["resolution"]
        if op.get("resolution_type"):
            cause["resolution_type"] = op["resolution_type"]
        cause["resolution_verification"] = {"status": "unverified"}

    def op_verify_resolution(self, i, op):
        cause_id = op["cause"]
        doc, cause = self._cause_or_reject(i, cause_id)
        later = [j for j, o in enumerate(self.ops) if j > i and o["op"] == "set-resolution" and o["cause"] == cause_id]
        if later:
            raise Reject("order", f"verify-resolution은 같은 원인의 set-resolution(op {later[0]})보다 뒤에 와야 "
                         "합니다.", i)
        if cause.get("signatures_pending"):
            raise Reject("pending-verified", f"원인 {cause_id}는 signatures_pending이라 해결책을 verified로 할 수 "
                         "없습니다.", i)
        v = dict(op["verification"])
        evidence = []
        own = ((self.plan.get("jira") or {}).get("key")) if self.source == "record" else None
        for item in v["evidence"]:
            item = self.fixture_ref(item)
            if self.key_re.fullmatch(item):
                if own and item == own:
                    raise Reject("self-evidence", f"record 계획에서는 기록 대상 Jira {own} 자신을 해결책 근거로 쓸 수 "
                                 "없습니다 (사용자 진술이다).", i)
                self.jira_checks.append((i, cause_id, item))
            else:
                self._require_fixture(i, doc.id, item, evidence=True)
            evidence.append(item)
        rv = {"status": "verified"}
        if v.get("method"):
            rv["method"] = v["method"]
        rv.update(evidence=evidence, by=v["by"], date=v["date"])
        cause["resolution_verification"] = rv

    def _require_fixture(self, i: int, type_id: str, rel: str, evidence: bool = False) -> None:
        tdir = self._type_dir_any(type_id)
        if not rel.startswith("fixtures/") or not self.tree.exists(tdir / rel):
            planned = any(self.fixture_names.get(j) == (type_id, rel.split("/", 1)[-1]) for j in self.fixture_names)
            if not planned:
                raise Reject("evidence-missing" if evidence else "fixture-missing",
                             f"fixture {rel}가 {type_id}에 없습니다.", i)

    def _type_dir_any(self, type_id: str) -> Path:
        return self.tree.type_dir(type_id) if type_id in self.tree.docs else self._fixture_dir(type_id, self.ops).parent

    def _post_checks(self) -> None:
        jira = self.tree.jira_files()
        for i, cause_id, key in self.jira_checks:
            path = jira.get(key)
            record = yamlio.loads(self.tree.read(path) or "") if path else None
            if not record or str(record.get("cause")) != cause_id:
                raise Reject("evidence-missing", f"근거 Jira {key}가 원인 {cause_id}의 Jira 기록으로 없습니다.", i)

    # 시그니처·상태 -------------------------------------------------------------------

    def op_update_signature(self, i, op):
        owner, kind = op["owner"], op["kind"]
        if kind == "symptom":
            if not TYPE_ID_RE.match(owner) or owner not in self.tree.docs:
                raise Reject("signature-owner", f"증상 시그니처의 owner는 있는 유형 ID여야 합니다: {owner}", i)
            target = self.tree.docs[owner].data
        else:
            if not CAUSE_ID_RE.match(owner):
                raise Reject("signature-owner", f"{kind} 시그니처의 owner는 원인 ID여야 합니다: {owner}", i)
            _, target = self._cause_or_reject(i, owner)
        key = SIG_LISTS[kind]
        sigs = copy.deepcopy(target.get(key) or [])
        sig = op["signature"]
        if op.get("sig_id"):
            n = next((k for k, s in enumerate(sigs) if s.get("id") == op["sig_id"]), None)
            if n is None:
                raise Reject("signature-missing", f"{owner}에 {kind} 시그니처 {op['sig_id']}가 없습니다.", i)
            sigs[n] = sig
        else:
            if any(s.get("id") == sig["id"] for s in sigs):
                raise Reject("signature-exists", f"{owner}에 {kind} 시그니처 {sig['id']}가 이미 있습니다 "
                             "(교체하려면 sig_id).", i)
            sigs.append(sig)
        target[key] = sigs
        if kind == "cause" and target.get("signatures_pending"):
            del target["signatures_pending"]

    def op_set_status(self, i, op):
        ident, status = op["id"], op["status"]
        if TYPE_ID_RE.match(ident):
            if ident not in self.tree.docs:
                raise Reject("unknown-type", f"유형 {ident}가 없습니다.", i)
            target = self.tree.docs[ident].data
            pattern = TYPE_ID_RE
        else:
            _, target = self._cause_or_reject(i, ident)
            pattern = CAUSE_ID_RE
        if status.startswith("merged-into:"):
            dest = status.split(":", 1)[1]
            exists = dest in self.tree.docs if pattern is TYPE_ID_RE else self.tree.cause(dest)[1] is not None
            if not pattern.match(dest) or not exists or dest == ident:
                raise Reject("merged-into", f"병합 대상 {dest}가 없거나 종류가 다릅니다.", i)
        target["status"] = status

    # fixture ---------------------------------------------------------------------------

    def _pending_causes(self) -> set[str]:
        return {c["id"] for d in self.tree.docs.values() for c in d.data.get("causes") or []
                if c.get("signatures_pending")}

    def op_add_fixture(self, i, op):
        type_id, name = self.fixture_names[i]
        src = Path(op["path"])
        if not src.is_absolute():
            src = self.plan_dir / src
        if not src.is_file():
            raise Reject("fixture-source", f"fixture 원본이 없습니다: {op['path']}", i)
        if op["kind"] != "negative":
            self._cause_or_reject(i, op["for"])
        text = src.read_text(encoding="utf-8")
        masked = masking.new_masker(existing_text=text, allow_patterns=self.allow).mask(text)
        fdir = self._type_dir_any(type_id) / "fixtures"
        self.tree.write(fdir / name, masked)
        fx = parse_name(name)
        expect = {}
        default = {"positive": "expect_top", "recurrence": "expect_top", "extra": "expect_top",
                   "negative": "expect_top", "fixed": "expect_not", "resolved": "expect_not"}
        for key, value in (op.get("expect") or {}).items():
            if key not in ("expect_top", "expect_not", "also_allowed"):
                raise Reject("fixture-expect", f"expect에 쓸 수 없는 필드: {key}", i)
            expect[key] = value
        if expect:
            base_key = default[fx.kind]
            base_value = "none" if fx.kind == "negative" else fx.cause
            if set(expect) == {base_key} and expect[base_key] == base_value:
                expect = {}
        if op.get("occurred_at"):
            expect["occurred_at"] = op["occurred_at"]
        if expect:
            self.tree.write(fdir / f"{fx.stem}.expect.yaml", yamldoc.dump_doc(expect))

    def op_allow_cause(self, i, op):
        rel = self.fixture_ref(op["fixture"])
        name = rel.split("/", 1)[1] if rel.startswith("fixtures/") else rel
        fx = parse_name(name)
        if fx is None or fx.suffix != ".log":
            raise Reject("allow-cause-fixture", f"fixture 이름이 규칙에 맞지 않습니다: {rel}", i)
        tdir = self._type_dir_any(fx.type_id)
        log = tdir / "fixtures" / name
        if not self.tree.exists(log):
            raise Reject("allow-cause-fixture", f"fixture가 없습니다: {fx.type_id}/fixtures/{name}", i)
        cause = op["cause"]
        self._cause_or_reject(i, cause)
        if cause == fx.cause or cause.rsplit("-", 1)[0] == fx.type_id:
            raise Reject("allow-cause-same", f"also_allowed에는 다른 유형의 원인만 넣을 수 있습니다 ({cause}, fixture "
                         f"{name}). 같은 유형 안의 충돌은 시그니처 설계 문제다.", i)
        expect_path = tdir / "fixtures" / f"{fx.stem}.expect.yaml"
        current = self.tree.read(expect_path)
        data = (yamlio.loads(current) or {}) if current else {}
        pending = self._pending_causes()
        if not data or not ("expect_top" in data or "expect_not" in data):
            if fx.kind not in FIXTURE_REF_KINDS:
                raise Reject("allow-cause-kind", f"also_allowed는 양성·recurrence·extra fixture에만 둡니다: {name}", i)
            top = f"{fx.type_id}:unresolved" if fx.cause in pending else fx.cause
            data = {"expect_top": top, **data}
        top = str(data.get("expect_top") or "")
        if not (fx.kind in FIXTURE_REF_KINDS and top) and not top.endswith(":unresolved"):
            raise Reject("allow-cause-kind", f"also_allowed는 양성·recurrence·extra 또는 unresolved 기대값 fixture에만 "
                         f"둡니다: {name}", i)
        allowed = list(data.get("also_allowed") or [])
        if cause not in allowed:
            allowed.append(cause)
        ordered = {k: data[k] for k in ("expect_top", "expect_not") if k in data}
        ordered["also_allowed"] = allowed
        ordered.update({k: v for k, v in data.items() if k not in ordered})
        self.tree.write(expect_path, yamldoc.dump_doc(ordered))

    # parser-rules ----------------------------------------------------------------------

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

    # 피드백 ------------------------------------------------------------------------------

    def _feedback(self, feedback: dict | None) -> str | None:
        if not feedback:
            return None
        jira = self.plan.get("jira")
        if not jira:
            self.warnings.append("jira가 없는 계획이라 피드백을 쓰지 않았다.")
            return None
        if self.source == "import":
            self.warnings.append("import 계획은 피드백을 기록하지 않는다 (16-existing-assets.md §16.4).")
            return None
        stamp = datetime.fromisoformat(str(feedback["date"]).replace("Z", "+00:00"))
        record = {"jira": jira["key"], "date": feedback["date"], "by": self.user,
                  "suggested": feedback.get("suggested") or [], "decision": feedback["decision"],
                  "final": feedback["final"]}
        path = self.tree.root / "feedback" / f"{stamp:%Y-%m}" / f"{jira['key']}-{stamp:%Y%m%dT%H%M}.yaml"
        self.tree.write(path, yamldoc.dump_doc(record))
        return self.tree.rel(path)

    def _pending(self, src: Path) -> str | None:
        text = Path(src).read_text(encoding="utf-8")
        record = yamlio.loads(text) or {}
        stamp = datetime.fromisoformat(str(record.get("date")).replace("Z", "+00:00"))
        path = self.tree.root / "feedback" / f"{stamp:%Y-%m}" / Path(src).name
        if self.tree.exists(path):
            self.warnings.append(f"pending 피드백 {Path(src).name}은 이미 이슈 DB에 있어 건너뛰었다.")
            return None
        self.tree.write(path, text)
        return self.tree.rel(path)


def cmd_apply(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    plan = load_plan(Path(args.plan))
    validate_plan(plan, db)
    tree = Tree(db)
    applier = Applier(tree, plan, Path(args.plan), user_id(args.user, defaults), defaults)
    try:
        result = applier.run([Path(p) for p in args.pending or []])
    except Reject as exc:
        return {"applied": False, "source": plan["source"], "rejected": [exc.as_dict()]}, CHECK_FAILED
    changes = tree.flush()
    return {"applied": True, "db": str(db), "source": plan["source"], "changed": changes,
            "ids": result["ids"], "fixtures": result["fixtures"], "commit_message": result["commit_message"],
            "feedback": result["feedback"], "pending_included": result["pending_included"],
            "operations": result["operations"], "warnings": applier.warnings}, OK


# -- drift --------------------------------------------------------------------------------


class Snapshot:
    """ref 하나의 트리(임시 디렉토리로 꺼낸 것)에서 drift 비교에 쓰는 값."""

    def __init__(self, root: Path):
        self.root = root
        self.db = issuedb.load(root)
        self.rules = {f: (yamlio.load(root / "parser-rules" / f) or {}) if (root / "parser-rules" / f).is_file()
                      else {} for f in RULE_SECTIONS}

    def cause(self, cid: str) -> dict | None:
        c = self.db.cause_by_id(cid)
        return c.raw if c else None

    def type(self, tid: str) -> dict | None:
        t = self.db.type_by_id(tid)
        return t.raw if t else None

    def status(self, ident: str) -> str | None:
        raw = self.type(ident) if TYPE_ID_RE.match(ident) else self.cause(ident)
        return str(raw.get("status", "active")) if raw else None

    def jira(self, key: str) -> dict | None:
        rec = next((r for r in self.db.jira if r.get("key") == key), None)
        return rec

    def expect(self, rel: str) -> tuple[bool, dict]:
        name = rel.split("/", 1)[-1]
        fx = parse_name(name)
        if fx is None:
            return False, {}
        t = self.db.type_by_id(fx.type_id)
        if t is None:
            return False, {}
        log = t.path / "fixtures" / name
        exp = t.path / "fixtures" / f"{fx.stem}.expect.yaml"
        data = (yamlio.load(exp) or {}) if exp.is_file() else {}
        return log.is_file(), data


def _functional(rule: dict) -> dict:
    return {k: v for k, v in (rule or {}).items() if k not in HISTORY_FIELDS}


def drift_items(plan: dict, base: Snapshot, onto: Snapshot) -> list[dict]:
    out = []
    ops = plan.get("operations") or []
    planned_fixtures = {op["path"] for op in ops if op.get("op") == "add-fixture"}

    def add(i, op, target, field, a, b):
        out.append({"op_index": i, "op": op["op"], "target": target, "field": field,
                    "plan_base_value": a, "current_value": b})

    def check_active(i, op, ident):
        if TEMP_RE.fullmatch(ident or ""):
            return
        a, b = base.status(ident), onto.status(ident)
        if a != b and b != "active":
            add(i, op, ident, "status", a, b)

    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind in ("append", "add-code-ref"):
            check_active(i, op, op["cause"])
        elif kind == "unresolved":
            check_active(i, op, op["type"])
        elif kind == "new-cause":
            check_active(i, op, op["type"])
        elif kind == "add-related":
            check_active(i, op, op["a"])
            check_active(i, op, op["b"])
        elif kind == "add-fixture":
            check_active(i, op, op["for"])
        elif kind == "new-type":
            spec = op["type"]
            for t in onto.db.types:
                if t.category != op["category"] or base.type(t.id) is not None:
                    continue
                if t.title == spec["title"] or t.raw.get("symptom_signatures") == spec["symptom_signatures"]:
                    add(i, op, t.id, "similar-type", None, {"id": t.id, "title": t.title})
        elif kind == "reclassify":
            a, b = base.jira(op["jira"]), onto.jira(op["jira"])
            if b is None or str(b.get("cause")) != op["from"]:
                add(i, op, op["jira"], "cause", a.get("cause") if a else None, b.get("cause") if b else None)
        elif kind in ("update-fix", "verify-fix"):
            if TEMP_RE.fullmatch(op["cause"]):
                continue
            a, b = (base.cause(op["cause"]) or {}).get("fix"), (onto.cause(op["cause"]) or {}).get("fix")
            if a != b:
                add(i, op, op["cause"], "fix", a, b)
        elif kind in ("set-resolution", "verify-resolution"):
            if TEMP_RE.fullmatch(op["cause"]):
                continue
            ca, cb = base.cause(op["cause"]) or {}, onto.cause(op["cause"]) or {}
            for field in ("resolution", "resolution_verification"):
                if ca.get(field) != cb.get(field):
                    add(i, op, op["cause"], field, ca.get(field), cb.get(field))
        elif kind == "update-signature":
            owner = op["owner"]
            if TEMP_RE.fullmatch(owner):
                continue
            key = SIG_LISTS[op["kind"]]
            ta = (base.type(owner) if op["kind"] == "symptom" else base.cause(owner)) or {}
            tb = (onto.type(owner) if op["kind"] == "symptom" else onto.cause(owner)) or {}
            if op.get("sig_id"):
                sa = next((s for s in ta.get(key) or [] if s.get("id") == op["sig_id"]), None)
                sb = next((s for s in tb.get(key) or [] if s.get("id") == op["sig_id"]), None)
                if sa != sb:
                    add(i, op, f"{owner}/{op['sig_id']}", key, sa, sb)
            else:
                sid = op["signature"]["id"]
                sb = next((s for s in tb.get(key) or [] if s.get("id") == sid), None)
                sa = next((s for s in ta.get(key) or [] if s.get("id") == sid), None)
                if sb is not None and sa is None:
                    add(i, op, f"{owner}/{sid}", key, None, sb)
        elif kind in ("add-parser-rule", "update-parser-rule"):
            sections = RULE_SECTIONS.get(op["file"], ())
            section = op.get("section") or (sections[0] if sections else None)
            if section is None:
                continue
            key = op.get("key") or Applier._rule_key(section, op["rule"])
            find = lambda snap: next((r for r in snap.rules.get(op["file"], {}).get(section) or []  # noqa: E731
                                      if Applier._rule_key(section, r) == key), None)
            ra, rb = find(base), find(onto)
            if kind == "add-parser-rule":
                if rb is not None and ra is None:
                    add(i, op, f"{op['file']}:{key}", section, None, rb)
            elif rb is None or _functional(ra) != _functional(rb):
                add(i, op, f"{op['file']}:{key}", section, _functional(ra) if ra else None,
                    _functional(rb) if rb else None)
        elif kind == "set-status":
            a, b = base.status(op["id"]), onto.status(op["id"])
            if a != b:
                add(i, op, op["id"], "status", a, b)
        elif kind == "allow-cause":
            if op["fixture"] in planned_fixtures or TEMP_RE.search(op["fixture"]):
                continue
            ea, da = base.expect(op["fixture"])
            eb, db_ = onto.expect(op["fixture"])
            if not eb:
                add(i, op, op["fixture"], "fixture", ea, eb)
                continue
            for field in ("also_allowed", "expect_top"):
                if da.get(field) != db_.get(field):
                    add(i, op, op["fixture"], field, da.get(field), db_.get(field))
    return out


def cmd_drift(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    plan = load_plan(Path(args.plan))
    base_sha = plan.get("base_sha")
    temp = Path(tempfile.mkdtemp(prefix="tt-drift-"))
    try:
        try:
            onto_sha = gitscope.git(db, "rev-parse", f"{args.onto}^{{commit}}").strip()
            base_root = gitscope.materialize_ref(db, base_sha, temp / "base")
            onto_root = gitscope.materialize_ref(db, onto_sha, temp / "onto")
        except gitscope.GitError as exc:
            raise UsageError(f"drift 비교용 트리를 꺼낼 수 없습니다 (base_sha {base_sha}가 이 레포에 있는지 확인): {exc}") \
                from exc
        try:
            items = drift_items(plan, Snapshot(base_root), Snapshot(onto_root))
        except issuedb.IssueDbError as exc:
            raise UsageError(str(exc)) from exc
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return {"base_sha": base_sha, "onto": args.onto, "onto_sha": onto_sha, "drift": items}, \
        (CHECK_FAILED if items else OK)


# -- ID 도구 ------------------------------------------------------------------------------


def collect_ids(root: Path) -> dict[str, list[str]]:
    """ID → 정의 위치(유형 디렉토리 기준 type.md 경로) 목록."""
    config = issuedb.load_config(root)
    found: dict[str, list[str]] = {}
    for path in issuedb.type_files(root, config):
        data = issuedb.read_frontmatter(path)
        rel = path.relative_to(root).as_posix()
        found.setdefault(str(data.get("id")), []).append(rel)
        for c in data.get("causes") or []:
            found.setdefault(str(c.get("id")), []).append(rel)
    return found


def _base_trees(db: Path, base: str, temp: Path) -> tuple[dict, dict]:
    try:
        mb = gitscope.merge_base(db, base)
        mine_root = gitscope.materialize_ref(db, mb, temp / "merge-base")
        base_root = gitscope.materialize_ref(db, base, temp / "base")
    except gitscope.GitError as exc:
        raise UsageError(str(exc)) from exc
    return collect_ids(mine_root), collect_ids(base_root)


def cmd_check_ids(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    current = collect_ids(db)
    duplicates = [{"id": k, "files": v} for k, v in sorted(current.items()) if len(v) > 1]
    conflicts, mine = [], []
    if args.base:
        temp = Path(tempfile.mkdtemp(prefix="tt-ids-"))
        try:
            merge_ids, base_ids = _base_trees(db, args.base, temp)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
        mine = sorted(k for k in current if k not in merge_ids)
        conflicts = [{"id": k, "mine": current[k], "base": base_ids[k]} for k in mine if k in base_ids]
    result = {"db": str(db), "duplicates": duplicates, "mine": mine, "conflicts": conflicts}
    return result, (CHECK_FAILED if duplicates or conflicts else OK)


def _next_id(old: str, pools: list[dict]) -> str:
    if CAUSE_ID_RE.match(old):
        prefix = old.rsplit("-", 1)[0]
        nums = [_num(k) for pool in pools for k in pool if CAUSE_ID_RE.match(k) and k.rsplit("-", 1)[0] == prefix]
        return f"{prefix}-{max(nums or [0]) + 1:02d}"
    prefix = old.split("-")[0]
    nums = [_num(k) for pool in pools for k in pool if TYPE_ID_RE.match(k) and k.split("-")[0] == prefix]
    return f"{prefix}-{max(nums or [0]) + 1:03d}"


def cmd_renumber(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    old = args.old_id
    if not (CAUSE_ID_RE.match(old) or TYPE_ID_RE.match(old)):
        raise UsageError(f"유형·원인 ID 형식이 아닙니다: {old}")
    current = collect_ids(db)
    if old not in current:
        raise UsageError(f"{old}가 이 트리에 없습니다.")
    temp = Path(tempfile.mkdtemp(prefix="tt-renumber-"))
    try:
        merge_ids, base_ids = _base_trees(db, args.base, temp)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    if old in merge_ids:
        raise UsageError(f"{old}는 merge-base(main)에 이미 있는 ID입니다. main에 들어간 ID는 바꾸지 않는다 "
                         "(사후 정리는 메인테이너 수동, 06-collaboration.md §6.3).")
    new = _next_id(old, [current, base_ids])
    token = re.compile(rf"(?<![A-Za-z0-9]){re.escape(old)}(?![0-9])")
    files, renamed = [], []
    tracked = gitscope.git(db, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    for rel in sorted(filter(None, set(tracked))):
        path = db / rel
        if not path.is_file() or rel in GENERATED or rel.endswith("/README.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if token.search(text):
            path.write_text(token.sub(new, text), encoding="utf-8", newline="\n")
            files.append(rel)
    for path in sorted(db.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if ".git" in path.parts or not token.search(path.name):
            continue
        dest = path.with_name(token.sub(new, path.name))
        path.rename(dest)
        renamed.append({"from": path.relative_to(db).as_posix(), "to": dest.relative_to(db).as_posix()})
    return {"old": old, "new": new, "files": files, "renamed": renamed,
            "next": f"db_lint.py --changed {args.base} --residual {old}={new}"}, OK


# -- similar -------------------------------------------------------------------------------


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z0-9_]{2,}|[가-힣]{2,}", text or "")}


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    ratio = difflib.SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()
    return round(max(jac, ratio), 3)


def cmd_similar(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    try:
        idb = issuedb.load(db)
    except issuedb.IssueDbError as exc:
        raise UsageError(str(exc)) from exc
    symptoms = None
    if args.symptom_json:
        symptoms = json.loads(Path(args.symptom_json).read_text(encoding="utf-8"))
    rows = []
    for t in idb.types:
        same = symptoms is not None and t.raw.get("symptom_signatures") == symptoms
        score = similarity(args.title, t.title)
        rows.append({"type": t.id, "title": t.title, "category": t.category, "status": t.status,
                     "score": 1.0 if same else score, "same_symptom": same,
                     "same_category": args.category is not None and t.category == args.category})
    rows.sort(key=lambda r: (-r["score"], id_key(r["type"])))
    return {"title": args.title, "top": rows[:3]}, OK


# -- main ----------------------------------------------------------------------------------


def _db(args) -> Path:
    try:
        return dbpath.resolve(args.db, user_config_path=lambda: userconfig.issue_db_path({}))
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="db_add.py", description=__doc__, parents=[common],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("apply", parents=[common])
    p.add_argument("plan")
    p.add_argument("--pending", action="append", metavar="FILE")
    p.add_argument("--user")
    p = sub.add_parser("drift", parents=[common])
    p.add_argument("plan")
    p.add_argument("--onto", required=True)
    p = sub.add_parser("renumber", parents=[common])
    p.add_argument("old_id")
    p.add_argument("--base", default="origin/main")
    p = sub.add_parser("check-ids", parents=[common])
    p.add_argument("--base")
    p = sub.add_parser("similar", parents=[common])
    p.add_argument("title")
    p.add_argument("--category")
    p.add_argument("--symptom-json")
    return parser


COMMANDS = {"apply": cmd_apply, "drift": cmd_drift, "renumber": cmd_renumber, "check-ids": cmd_check_ids,
            "similar": cmd_similar}


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    for name, default in (("db", None), ("plugin_root", None)):
        if not hasattr(args, name):
            setattr(args, name, default)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    try:
        result, code = COMMANDS[args.cmd](args, defaults)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=1))
        return USAGE
    for item in result.get("rejected") or []:
        print(f"거부[{item['code']}] op {item['op_index']}: {item['message']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
