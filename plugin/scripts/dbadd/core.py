"""db_add 공통: 상수, 오류, 계획 읽기·검사, 적용 대상 트리 (`Tree`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema

from common import dbpath, issuedb, userconfig
from common.typedoc import TypeDoc, TypeDocError


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


def _db(args) -> Path:
    try:
        return dbpath.resolve(args.db, user_config_path=lambda: userconfig.issue_db_path({}))
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc


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
