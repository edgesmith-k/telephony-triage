"""시그니처 컴파일과 이슈 DB 소스 해시·파서 환경 (06-collaboration.md §6.8, 04 §5.11 (3)).

매처는 매번 `--db`(스냅샷)에서 메모리로 컴파일한다. 파일 캐시는 없다(06 §6.8).
해시는 이슈 DB의 소스 파일(설정, `type.md`, `jira/`, `feedback/`, `parser-rules/`)과
**파서 백엔드·외부 파서 이름·버전**으로 만들고, 분석 재사용(`triagelib/cache.py`)이 쓴다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import issuedb
from .signatures import compile_list


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


def compile_signatures(db: issuedb.IssueDb) -> dict[str, list]:
    """소유자(유형·원인 ID)별 컴파일된 시그니처 (active 유형, active·pending 아닌 원인)."""
    compiled: dict[str, list] = {}
    for itype in db.types:
        if not itype.active:
            continue
        compiled[itype.id] = compile_list(itype.raw.get("symptom_signatures"), itype.id)
        for cause in itype.causes:
            if cause.active and not cause.pending:
                compiled[cause.id] = compile_list(cause.raw.get("signatures"), cause.id)
    return compiled
