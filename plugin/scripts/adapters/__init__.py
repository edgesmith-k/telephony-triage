"""외부 파서 어댑터 로드 (16-existing-assets.md §16.3 "대안: 어댑터 방식").

어댑터 모듈은 `plugin/scripts/adapters/<adapter>.py`이고 계약은 `base.py`에 있다.
사내 어댑터(`site_*`)는 SITE_PATHS다.
"""

from __future__ import annotations

import importlib
import re
from types import ModuleType

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class AdapterError(Exception):
    pass


def load(name: str) -> ModuleType:
    if not isinstance(name, str) or not _NAME_RE.match(name) or name == "base":
        raise AdapterError(f"어댑터 이름이 잘못됐습니다: {name!r}")
    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            raise AdapterError(f"어댑터가 없습니다: scripts/adapters/{name}.py") from exc
        raise
    for attr in ("ADAPTER_NAME", "VERSION", "convert"):
        if not hasattr(module, attr):
            raise AdapterError(f"어댑터 {name}에 {attr}가 없습니다 (adapters/base.py 계약).")
    if module.ADAPTER_NAME != name:
        raise AdapterError(f"어댑터 {name}의 ADAPTER_NAME이 {module.ADAPTER_NAME!r}입니다.")
    if not callable(module.convert):
        raise AdapterError(f"어댑터 {name}.convert가 함수가 아닙니다.")
    return module
