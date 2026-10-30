"""One immutable default plugin root per pytest session; variants stay isolated."""

from __future__ import annotations

import importlib
import os
import site
from pathlib import Path
import sys

import pytest

# 하위 프로세스의 `python3`(git hook·스크립트)가 pytest와 같은 인터프리터를 쓰게 한다.
# venv를 켜지 않고 `.venv/bin/python -m pytest`로 돌려도 PATH의 시스템 python3(의존성 없음)로 새지 않는다.
os.environ["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
# `pip install --user`로 설치했으면 의존성은 ~/.local에 있다. HOME을 임시 폴더로 바꾸는 테스트의 하위 프로세스도
# 같은 사용자 site를 보게 고정한다(사내 설치 방법 A, docs/SITE_INSTALL.md 3절).
os.environ.setdefault("PYTHONUSERBASE", site.getuserbase())

# W7: triage.py run 출력을 plugin/schemas/output/analysis.schema.json으로 검사한다(위반이면 종료 코드 2)
os.environ["TT_SCHEMA_CHECK"] = "1"

HELPERS = Path(__file__).resolve().parent / "helpers"
sys.path.insert(0, str(HELPERS))
import runner  # noqa: E402


def pytest_sessionstart(session):
    # Collection imports some Python APIs directly. Load them from the temporary
    # plugin before older tests add the source checkout to sys.path.
    # 여기서 불러 둔 `parser_backends`의 `site/`는 모의 백엔드다. 사내 실제 site 백엔드는
    # `real_site_backend` 픽스처(`runner.real_site_backend()`)로 다른 모듈 이름으로 받는다.
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


@pytest.fixture(scope="session")
def real_site_backend():
    """사내 골든 테스트(`tests/golden/test_*.py`)가 쓰는 **실제** site 백엔드. 없으면(사외) 건너뛴다.

    세션 시작 때 불러 둔 `parser_backends`는 임시 루트(모의 site 백엔드)의 것이라 `import parser_backends.site`는
    모의를 준다. 실제 백엔드는 `runner.real_site_backend()`가 `parser_backends.site_real`로 따로 불러온다."""
    backend = runner.real_site_backend()
    if backend is None:
        pytest.skip(f"실제 site 백엔드 없음: {runner.REAL_SITE_BACKEND} (사내 S-4a에서 포팅)")
    return backend


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
