"""매칭 컴파일 캐시 `.cache/compiled.json` (06-collaboration.md §6.8, 04 §5.11 (3)).

`db_build.py`(`--write`, `--cache-only`)가 쓰고 `match_signatures.py`가 읽는다.
캐시에는 모든 active 시그니처(원문), extractor, 원인 메타(`fix`, `related`, `status`),
시그니처 수락률과 **소스 해시**를 넣는다. 해시는 이슈 DB의 소스 파일(설정, `type.md`,
`jira/`, `feedback/`, `parser-rules/`)과 **파서 백엔드·외부 파서 이름·버전**으로 만든다.
매처는 해시가 현재 이슈 DB·환경과 같으면 캐시를 쓰고, 다르면 메모리에서 다시 컴파일한다.
캐시는 커밋하지 않는다(`.gitignore`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import issuedb
from .signatures import compile_list

CACHE_REL = Path(".cache") / "compiled.json"
CACHE_FORMAT = 1


def environment(defaults: dict) -> dict:
    """현재 플러그인 환경의 파서 백엔드·외부 파서 `{backend: {name, version}, external: {...}}`."""
    import parser_backends

    name = (defaults.get("parser") or {}).get("backend")
    try:
        version = parser_backends.load(name).version()
    except parser_backends.BackendError:
        version = None
    external = {}
    for category, conf in sorted((defaults.get("external_parsers") or {}).items()):
        conf = conf or {}
        external[category] = {"adapter": conf.get("adapter"), "version": conf.get("version")}
    return {"backend": {"name": name, "version": version}, "external": external}


def source_files(root: Path, config: dict) -> list[Path]:
    files = [root / issuedb.CONFIG]
    for type_md in issuedb.type_files(root, config):
        files.append(type_md)
        files += sorted((type_md.parent / "jira").glob("*.yaml"))
    files += sorted((root / "feedback").glob("*/*.yaml"))
    files += sorted((root / "parser-rules").glob("*.yaml"))
    return files


def source_hash(root: Path, config: dict, env: dict) -> str:
    digest = hashlib.sha256()
    for path in source_files(root, config):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    digest.update(json.dumps(env, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def build(db: issuedb.IssueDb, env: dict, generator_version: int) -> dict:
    """캐시 내용 (결정적: 키 정렬, 시각 없음)."""
    signatures: dict[str, list] = {}
    causes: dict[str, dict] = {}
    for itype in db.types:
        if itype.active:
            signatures[itype.id] = list(itype.raw.get("symptom_signatures") or [])
        for cause in itype.causes:
            causes[cause.id] = {
                "type": itype.id,
                "status": cause.status,
                "pending": cause.pending,
                "fix": cause.raw.get("fix"),
                "related": list(cause.raw.get("related") or []),
            }
            if itype.active and cause.active and not cause.pending:
                signatures[cause.id] = list(cause.raw.get("signatures") or [])
    extractors = []
    rules_file = db.root / "parser-rules" / "extractors.yaml"
    if rules_file.is_file():
        from . import yamlio

        extractors = (yamlio.load(rules_file) or {}).get("extractors") or []
    acceptance = {k: list(v) for k, v in sorted(issuedb.acceptance(db.feedback).items())}
    return {
        "format": CACHE_FORMAT,
        "generator_version": generator_version,
        "hash": source_hash(db.root, db.config, env),
        "environment": env,
        "signatures": dict(sorted(signatures.items())),
        "causes": dict(sorted(causes.items())),
        "extractors": extractors,
        "acceptance": acceptance,
    }


def write(db: issuedb.IssueDb, env: dict, generator_version: int) -> Path:
    path = db.root / CACHE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    data = build(db, env, generator_version)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def load(db: issuedb.IssueDb, env: dict) -> tuple[dict | None, str]:
    """캐시를 읽는다. `(캐시, 상태)` — 상태는 `hit`(해시 같음) / `miss`(다름·깨짐) / `none`(없음)."""
    path = db.root / CACHE_REL
    if not path.is_file():
        return None, "none"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "miss"
    if data.get("format") != CACHE_FORMAT or data.get("hash") != source_hash(db.root, db.config, env):
        return None, "miss"
    return data, "hit"


def compile_signatures(db: issuedb.IssueDb, cache: dict | None) -> dict[str, list]:
    """소유자(유형·원인 ID)별 컴파일된 시그니처. 캐시가 있으면 캐시의 원문을 쓴다."""
    compiled: dict[str, list] = {}
    if cache is not None:
        for owner, raws in cache["signatures"].items():
            compiled[owner] = compile_list(raws, owner)
        return compiled
    for itype in db.types:
        if not itype.active:
            continue
        compiled[itype.id] = compile_list(itype.raw.get("symptom_signatures"), itype.id)
        for cause in itype.causes:
            if cause.active and not cause.pending:
                compiled[cause.id] = compile_list(cause.raw.get("signatures"), cause.id)
    return compiled
