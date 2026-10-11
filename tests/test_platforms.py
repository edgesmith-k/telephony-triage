"""RF-3(I2): `platforms/android/` 이동 — reference 백엔드·계층 가드·bugreport 래퍼."""

from __future__ import annotations

import ast
import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
MOCK_SITE_DIR = REPO / "tests" / "mocks" / "parser_backends" / "site"
sys.path.insert(0, str(SCRIPTS))

# -- 1. reference 백엔드 ---------------------------------------------------------


def test_reference_backend_identity():
    import parser_backends
    from platforms.android import backend

    assert parser_backends.load("reference") is backend.BACKEND
    assert backend.BACKEND.name == "reference"
    assert backend.BACKEND.version() == backend.VERSION == "0.1.0"


def test_old_backend_shims_removed():
    """R-33: 옛 경로 shim(`sys.modules` 바꿔치기)은 없다. reference 패키지는 BACKEND만 다시 내보낸다."""
    assert not (SCRIPTS / "parser_backends" / "logcat.py").exists()
    assert not (SCRIPTS / "parser_backends" / "ril.py").exists()
    assert "sys.modules" not in (SCRIPTS / "parser_backends" / "reference" / "__init__.py").read_text(encoding="utf-8")


# -- 2. 모의 site 백엔드 ----------------------------------------------------------


def _load_mock_site():
    name = "parser_backends.site"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, MOCK_SITE_DIR / "__init__.py", submodule_search_locations=[str(MOCK_SITE_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_mock_site_backend_extends_reference():
    from platforms.android import backend

    site = _load_mock_site()
    assert isinstance(site.BACKEND, backend.ReferenceBackend)


# -- 3. 계층 가드 ----------------------------------------------------------------

# common → platforms 허용 목록. 정확히 이것만 허용하고 현실과 다르면 실패한다.
# 시각 helper는 `common/logtime.py`로 나눴다(17-platforms 묶음 1). common은 platforms를 import하지 않는다.
COMMON_ALLOW = {}


_DYNAMIC_IMPORTS = {"import_module", "__import__"}


def _imports(path: Path, rel: str) -> set[str]:
    """파일의 모든 import(함수 안 포함)를 절대 모듈 이름으로 푼다. `from a import b`는 `a`와 `a.b` 둘 다.
    `importlib.import_module("x")`·`__import__("x")`처럼 첫 인자가 문자열 상수인 동적 import도 넣는다."""
    package = rel.removesuffix(".py").split("/")[:-1]  # `__init__.py`도 포함 패키지가 기준이다
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str):
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
            if fname in _DYNAMIC_IMPORTS:
                found.add(node.args[0].value)
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def _py_files(sub: str = ""):
    for path in sorted((SCRIPTS / sub).rglob("*.py")):
        yield path, path.relative_to(SCRIPTS).as_posix()


def test_common_does_not_import_platforms():
    actual: dict[str, set[str]] = {}
    for path, rel in _py_files("common"):
        bad = {
            m for m in _imports(path, rel)
            if m == "platforms" or m.startswith("platforms.")
        }
        if bad:
            actual[rel] = bad
    assert actual == COMMON_ALLOW


@pytest.mark.parametrize("src", [
    "import platforms\n",
    "from platforms import load\n",
    "import platforms.android\n",
    "from platforms import android\n",
    "from platforms.android import logcat\n",
    "def f():\n    import importlib\n    return importlib.import_module('platforms.android')\n",
    "from importlib import import_module\nimport_module('platforms')\n",
    "__import__('platforms.base')\n",
])
def test_import_scan_catches_every_form(tmp_path, src):
    """계층 검사(`_imports`)가 모든 import 형식을 잡는다 — 필터로 빠지는 형식이 없다."""
    path = tmp_path / "x.py"
    path.write_text(src, encoding="utf-8")
    assert any(m == "platforms" or m.startswith("platforms.") for m in _imports(path, "common/x.py"))


def _platform_names() -> list[str]:
    import platforms

    return platforms.known()


@pytest.mark.parametrize("name", _platform_names())
def test_platform_does_not_import_other_platforms(name):
    """`platforms/<a>`는 `platforms/<b>`를 import하지 않는다(17-platforms §2-5). 공용은 `platforms.base`와 레지스트리 밖 모듈."""
    others = set(_platform_names()) - {name}
    offenders = {}
    for path, rel in _py_files(f"platforms/{name}"):
        bad = {m for m in _imports(path, rel)
               if m.startswith("platforms.") and m.split(".")[1] in others}
        if bad:
            offenders[rel] = bad
    assert offenders == {}


@pytest.mark.parametrize("name", _platform_names())
def test_platform_init_imports_are_light(name):
    """`platforms/<p>/__init__.py`는 표준 라이브러리, 같은 패키지 하위 모듈, `platforms.base`, `common.logtime`·`common.events`만
    import한다(guard 규칙 10이 레지스트리로 불러오므로 가벼워야 한다, 17-platforms §2-5)."""
    path = SCRIPTS / "platforms" / name / "__init__.py"
    rel = f"platforms/{name}/__init__.py"
    allowed_prefix = (f"platforms.{name}", "platforms.base", "common.logtime", "common.events")
    bad = set()
    for module in _imports(path, rel):
        top = module.split(".")[0]
        if top in sys.stdlib_module_names or top == "__future__":
            continue
        if module in ("platforms", "common"):           # `from platforms.base import X`·`from common import logtime`의 부모
            continue
        if any(module == p or module.startswith(p + ".") for p in allowed_prefix):
            continue
        if module.startswith("common.") and module.split(".")[1] in ("logtime", "events"):
            continue
        bad.add(module)
    assert bad == set()


def test_platforms_do_not_import_core():
    banned = {"parse_logcat", "triage", "config", "code_roots"}
    offenders = {}
    for path, rel in _py_files("platforms"):
        bad = set()
        for module in _imports(path, rel):
            top = module.split(".")[0]
            if top in banned or top.startswith("db_") or module.startswith("parser_backends.site"):
                bad.add(module)
        if bad:
            offenders[rel] = bad
    assert offenders == {}


# -- 4. bugreport 래퍼 ------------------------------------------------------------


def test_parse_logcat_bugreport_wrapper():
    import parse_logcat
    from platforms.android import bugreport

    assert parse_logcat._looks_like_bugreport is bugreport.looks_like_bugreport


def test_extract_bugreport_missing_file_exits_2(tmp_path):
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    from runner import plugin_root  # noqa: E402

    root = plugin_root()
    import os

    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "parse_logcat.py"), "extract-bugreport",
         str(tmp_path / "none.txt"), "--out", str(tmp_path / "o")],
        capture_output=True, text=True, env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(root)},
    )
    assert proc.returncode == 2
    assert f"bugreport 파일이 없습니다: {tmp_path / 'none.txt'}" in proc.stderr


# -- 5. code_roots 상수 ------------------------------------------------------------


def test_code_roots_constants_come_from_platform():
    import code_roots
    import platforms.android as android

    assert code_roots.TELEPHONY_DIR is android.TELEPHONY_DIR
    assert code_roots.VERSION_SOURCES is android.VERSION_SOURCES
