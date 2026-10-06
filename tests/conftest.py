"""One immutable default plugin root per pytest session; variants stay isolated."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

import pytest

# W7: triage.py run 출력을 plugin/schemas/output/analysis.schema.json으로 검사한다(위반이면 종료 코드 2)
os.environ["TT_SCHEMA_CHECK"] = "1"

HELPERS = Path(__file__).resolve().parent / "helpers"
sys.path.insert(0, str(HELPERS))
import runner  # noqa: E402


def pytest_sessionstart(session):
    # Collection imports some Python APIs directly. Load them from the temporary
    # plugin before older tests add the source checkout to sys.path.
    root = runner.plugin_root()
    runner.variant_dir()  # 변형 이슈 DB를 미리 만든다 (프로세스당 한 번)
    session.config._tt_plugin_root = root
    sys.path.insert(0, str(root / "scripts"))
    for name in ("common", "parser_backends", "parse_logcat", "match_signatures", "db_pr", "db_verify"):
        importlib.import_module(name)


def pytest_sessionfinish(session, exitstatus):
    try:
        _check_shared_variants(session)
    finally:
        runner.cleanup_tmp()  # runner.tmp()가 만든 임시 디렉터리 (TT_KEEP_TMP=1이면 남긴다)


def _check_shared_variants(session):
    # 공유 변형 트리를 제자리에서 바꾼 테스트가 있으면 새로 만든 것과 달라진다.
    if runner._VARIANT_DIR is None or not runner._VARIANT_DIR.is_dir():
        return
    import shutil
    import make_variant_dbs

    fresh = runner.tmp("tt-variants-fresh-")
    try:
        make_variant_dbs.build_all(fresh)
        bad = {n: d for n in make_variant_dbs.VARIANTS
               if (d := make_variant_dbs._diff(runner._VARIANT_DIR / n, fresh / n))}
    finally:
        shutil.rmtree(fresh, ignore_errors=True)
    if bad:
        print("\n공유 변형 이슈 DB가 테스트 중에 바뀌었습니다 (copy_db()로 복사해서 쓰세요):")
        for n, d in bad.items():
            print(f"  {n}: {', '.join(d)}")
        session.exitstatus = 1


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
