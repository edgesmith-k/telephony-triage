"""One immutable default plugin root per pytest session; variants stay isolated."""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest

HELPERS = Path(__file__).resolve().parent / "helpers"
sys.path.insert(0, str(HELPERS))
import runner  # noqa: E402


def pytest_sessionstart(session):
    # Collection imports some Python APIs directly. Load them from the temporary
    # plugin before older tests add the source checkout to sys.path.
    root = runner.plugin_root()
    session.config._tt_plugin_root = root
    sys.path.insert(0, str(root / "scripts"))
    for name in ("common", "parser_backends", "parse_logcat", "match_signatures", "db_pr", "db_verify"):
        importlib.import_module(name)


@pytest.fixture(scope="session", autouse=True)
def session_plugin_root(pytestconfig):
    return pytestconfig._tt_plugin_root


def pytest_collection_modifyitems(config, items):
    # Share only the read-only baseline used by the original CLI test wrappers.
    # make_plugin_root.make(), runner variants and mutated roots still get copies.
    root = config._tt_plugin_root
    for module in {item.module for item in items if hasattr(item, "module")}:
        name = module.__name__.rsplit(".", 1)[-1]
        if name in {"test_parse_logcat", "test_masking"}:
            module._ROOTS["plain"] = root
        elif name == "test_match_signatures":
            module._ROOT[:] = [root]
