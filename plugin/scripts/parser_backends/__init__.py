"""파서 백엔드 선택 (contracts.md §기존 자산 연결 계약, 16-existing-assets.md §16.3).

`site-defaults.yaml`의 `parser.backend`(site | reference) 이름으로
`parser_backends.<이름>` 패키지를 불러 그 `BACKEND` 객체(`base.ParserBackend`)를 쓴다.

- `reference/`: 사외 초안의 공통 처리 구현 (builtin 판별 없음)
- `site/`: 사내에서 검증된 기존 파서를 포팅하는 자리 (SITE_PATHS, 사외 레포에는 없다)
"""

from __future__ import annotations

import importlib
import re

from .base import ParserBackend

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class BackendError(Exception):
    """백엔드를 불러올 수 없다 (이름·모듈·인터페이스 오류)."""


def load(name: str) -> ParserBackend:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise BackendError(f"파서 백엔드 이름이 잘못됐습니다: {name!r}")
    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == module_name or module_name.startswith(exc.name + ".")):
            raise BackendError(
                f"파서 백엔드 '{name}'이(가) 없습니다: scripts/parser_backends/{name}/ "
                "(사내 site 백엔드는 S-4a에서 포팅한다)"
            ) from exc
        raise
    backend = getattr(module, "BACKEND", None)
    if not isinstance(backend, ParserBackend):
        raise BackendError(f"{module_name}.BACKEND가 ParserBackend가 아닙니다.")
    return backend
