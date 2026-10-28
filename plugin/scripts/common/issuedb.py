"""이슈 DB 읽기 (03-issue-db.md §5.2·§5.4).

- `<db>/issue-db.config.yaml`
- 유형: `<db>/<category>/<TYPE-ID-slug>/type.md`의 YAML frontmatter
- 이슈 기록: `<유형 디렉토리>/issues/<KEY>.yaml` (원인별 건수만 쓴다)
- 피드백: `<db>/feedback/<YYYY-MM>/*.yaml`

스키마 검증은 `db_lint`(Phase 5)가 한다. 여기서는 매처가 쓰는 구조만 만든다.
시그니처 컴파일은 `common/signatures.py`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import yamlio

CONFIG = "issue-db.config.yaml"
RECORD_SCHEMA = "schema/issue.schema.json"
RECORD_JIRA_FIELDS = ("date", "model", "sw", "platform_version")   # Jira에서 오는 기록 필드(순서 = 기록 키 순서)
_PLUGIN_RECORD_SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "issue.schema.json"


def record_required(db_root) -> frozenset:
    """Jira 기록 필수 필드 = 이슈 DB `schema/issue.schema.json`의 `required`(단일 원본 — 운영 DB가 옛 스키마면 sw도 필수).
    `db_root`가 없으면 플러그인 사본. 스키마를 읽지 못하면 보수적으로 `RECORD_JIRA_FIELDS` 모두 필수."""
    path = Path(db_root) / RECORD_SCHEMA if db_root else _PLUGIN_RECORD_SCHEMA
    try:
        req = json.loads(path.read_text(encoding="utf-8")).get("required")
    except (OSError, ValueError, AttributeError):
        req = None
    return frozenset(map(str, req)) if isinstance(req, list) else frozenset(RECORD_JIRA_FIELDS)


class IssueDbError(Exception):
    pass


@dataclass
class Cause:
    id: str
    type_id: str
    status: str
    title: str
    raw: dict
    pending: bool = False

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass
class IssueType:
    id: str
    category: str
    status: str
    title: str
    path: Path
    raw: dict
    causes: list[Cause] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass
class IssueDb:
    root: Path
    config: dict
    types: list[IssueType]
    feedback: list[dict]
    jira_counts: Counter
    jira: list[dict] = field(default_factory=list)  # 기록마다 `_type`(유형 ID), `_rel`(DB 기준 경로)

    def type_by_id(self, type_id: str) -> IssueType | None:
        return next((t for t in self.types if t.id == type_id), None)

    def cause_by_id(self, cause_id: str) -> Cause | None:
        for t in self.types:
            for c in t.causes:
                if c.id == cause_id:
                    return c
        return None


def parse_frontmatter_text(text: str, label: str = "") -> dict:
    """`type.md` 등의 본문 텍스트에서 YAML frontmatter를 읽는다(`label`은 오류 메시지의 출처). 이전 커밋 내용에도 쓴다."""
    if not text.startswith("---\n"):
        raise IssueDbError(f"{label}: frontmatter가 없습니다.")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise IssueDbError(f"{label}: frontmatter 끝(---)이 없습니다.")
    try:
        data = yamlio.loads(text[4:end])
    except yaml.YAMLError as exc:
        raise IssueDbError(f"{label}: frontmatter YAML 오류: {exc}") from exc
    if not isinstance(data, dict):
        raise IssueDbError(f"{label}: frontmatter가 매핑이 아닙니다.")
    return data


def read_frontmatter(path: Path) -> dict:
    return parse_frontmatter_text(path.read_text(encoding="utf-8"), str(path))


def _yaml(path: Path, root: Path):
    try:
        return yamlio.load(path)
    except yamlio.YamlFileError as exc:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path)
        raise IssueDbError(f"{rel}{f':{exc.line}' if exc.line else ''}: YAML 문법 오류: {exc.problem}") from exc


def load_config(root: Path) -> dict:
    path = root / CONFIG
    if not path.is_file():
        raise IssueDbError(f"이슈 DB가 아닙니다(설정 파일 없음): {path}")
    data = _yaml(path, root)
    if not isinstance(data, dict):
        raise IssueDbError(f"{path}: 매핑이어야 합니다.")
    return data


# 지원 버전 키 (값은 플랫폼 버전 문자열 목록). 옛 이름 `android_versions_supported`는 읽지 않는다(원칙 d,
# 남아 있으면 db_lint `config` 오류 — `LEGACY_CONFIG_KEYS`).
SUPPORTED_VERSION_KEY = "platform_versions_supported"
# 개명 전 DB 설정 키 → 새 이름 (db_lint가 오류로 알린다. 코드는 옛 키를 읽지 않는다)
LEGACY_CONFIG_KEYS = {"android_versions_supported": SUPPORTED_VERSION_KEY, "jira_key_regex": "tracker.key_regex",
                      "jira_base_url": "tracker.base_url", "readme.jira_inline_max": "readme.issue_inline_max"}


def supported_versions(config: dict) -> tuple[str, list[str]]:
    """`(키 이름, 버전 문자열 목록)`. 키가 없거나 null이면 빈 목록."""
    return SUPPORTED_VERSION_KEY, [str(v) for v in config.get(SUPPORTED_VERSION_KEY) or []]


def type_files(root: Path, config: dict) -> list[Path]:
    files = []
    for category in config.get("categories") or []:
        key = category.get("key") if isinstance(category, dict) else None
        if key:
            files.extend(sorted((root / key).glob("*/type.md")))
    return files


def load(db_root: str | Path) -> IssueDb:
    root = Path(db_root)
    config = load_config(root)
    types: list[IssueType] = []
    jira_counts: Counter = Counter()
    jira_records: list[dict] = []
    for path in type_files(root, config):
        data = read_frontmatter(path)
        itype = IssueType(
            id=str(data.get("id")),
            category=str(data.get("category")),
            status=str(data.get("status", "active")),
            title=str(data.get("title", "")),
            path=path.parent,
            raw=data,
        )
        for raw in data.get("causes") or []:
            itype.causes.append(
                Cause(
                    id=str(raw.get("id")),
                    type_id=itype.id,
                    status=str(raw.get("status", "active")),
                    title=str(raw.get("title", "")),
                    raw=raw,
                    pending=bool(raw.get("signatures_pending")),
                )
            )
        types.append(itype)
        for jira in sorted((path.parent / "issues").glob("*.yaml")):
            record = _yaml(jira, root) or {}
            if not isinstance(record, dict):
                record = {}
            if record.get("cause"):
                jira_counts[str(record["cause"])] += 1
            jira_records.append({**record, "_type": itype.id, "_rel": jira.relative_to(root).as_posix()})
    feedback = []
    for path in sorted((root / "feedback").glob("*/*.yaml")):
        record = _yaml(path, root)
        if isinstance(record, dict):
            feedback.append(record)
    return IssueDb(root=root, config=config, types=types, feedback=feedback, jira_counts=jira_counts,
                   jira=jira_records)


def acceptance(feedback: list[dict]) -> dict[str, tuple[int, int]]:
    """시그니처 전역 키별 `(수락 건수, 1위로 제시된 건수)` (04-parser-matching.md §5.11 (2)).
    1위로 제시된 경우만 분모에 넣는다. `decision: manual`은 제시된 후보가 없으므로 뺀다."""
    stats: dict[str, list[int]] = {}
    for record in feedback:
        if record.get("decision") == "manual":
            continue
        suggested = record.get("suggested") or []
        if not suggested or not isinstance(suggested[0], dict):
            continue
        key = suggested[0].get("signature")
        if not key:
            continue
        entry = stats.setdefault(key, [0, 0])
        entry[1] += 1
        if record.get("decision") == "accepted":
            entry[0] += 1
    return {k: (v[0], v[1]) for k, v in stats.items()}
