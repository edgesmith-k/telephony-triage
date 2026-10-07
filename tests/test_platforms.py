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
# stepanchor의 시각 해석 함수가 logcat 스탬프를 쓴다 (시각 helper를 따로 나눌 때 없앤다).
COMMON_ALLOW = {"common/stepanchor.py": {"platforms.android.logcat"}}


def _imports(path: Path, rel: str) -> set[str]:
    """파일의 모든 import(함수 안 포함)를 절대 모듈 이름으로 푼다. `from a import b`는 `a`와 `a.b` 둘 다."""
    package = rel.removesuffix(".py").split("/")[:-1]  # `__init__.py`도 포함 패키지가 기준이다
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
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
        # `from platforms.android import logcat`은 `platforms`·`platforms.android`·`platforms.android.logcat`로 풀린다.
        # 하위 모듈 이름까지 간 것만 비교한다.
        bad = {m for m in bad if m.count(".") >= 2}
        if bad:
            actual[rel] = bad
    assert actual == COMMON_ALLOW


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
