#!/usr/bin/env python3
"""테스트 공용: 임시 플러그인 루트에서 스크립트 실행, 이슈 DB 복사, 임시 git 레포.

Phase 5 이후 테스트가 쓴다. 플러그인 루트는 `make_plugin_root.make()`로 만들고
(`site-defaults.example.yaml` → `site-defaults.yaml`, 15-local-draft.md §15.1) 종류별로 한 번만 만든다.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_plugin_root  # noqa: E402
import mock_env  # noqa: E402

_ROOTS: dict[str, Path] = {}
_LOCK_OWNERS: dict[str, str] = {}


def plugin_root(kind: str = "plain", **defaults) -> Path:
    """kind: `plain`(reference 백엔드) 또는 이름. `defaults`는 site-defaults.yaml 덮어쓰기."""
    key = kind + json.dumps(defaults, sort_keys=True, default=str)
    if key not in _ROOTS or not _ROOTS[key].is_dir():
        root = make_plugin_root.make(with_site_backend=True)
        if defaults:
            path = root / "site-defaults.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data.update(defaults)
            path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        _ROOTS[key] = root
    return _ROOTS[key]


def versioned_root(schema: int | None = None, generator: int | None = None) -> Path:
    """`common/versions.py`의 SCHEMA_VERSION·GENERATOR_VERSION을 고친 임시 플러그인 루트 (스크립트는 서브프로세스로 돌아
    monkeypatch가 닿지 않으므로 루트 복사본을 고친다). 종류별로 한 번만 만든다."""
    key = f"versioned-{schema}-{generator}"
    if key not in _ROOTS or not _ROOTS[key].is_dir():
        root = make_plugin_root.make(with_site_backend=True)
        path = root / "scripts" / "common" / "versions.py"
        text = path.read_text(encoding="utf-8")
        for name, value in (("SCHEMA_VERSION", schema), ("GENERATOR_VERSION", generator)):
            if value is not None:
                assert f"{name} = " in text
                lines = [f"{name} = {value}" if line.startswith(f"{name} = ") else line
                         for line in text.splitlines()]
                text = "\n".join(lines) + "\n"
        path.write_text(text, encoding="utf-8")
        _ROOTS[key] = root
    return _ROOTS[key]


def run(script: str, args: list[str], root: Path | None = None, cwd=None, env: dict | None = None,
        unauth: bool = False, stdin: str | None = None) -> subprocess.CompletedProcess:
    """`env`는 더할 환경변수(예: TELEPHONY_TRIAGE_HOME), `unauth`는 gh 스텁 인증 실패."""
    root = root or plugin_root()
    full_env = mock_env.env_with_mocks(plugin_root=root, unauth=unauth)
    full_env.update({k: str(v) for k, v in (env or {}).items()})
    session = str(full_env.get("TELEPHONY_TRIAGE_HOME", ""))
    if session in _LOCK_OWNERS:
        full_env.setdefault("TT_LOCK_OWNER", _LOCK_OWNERS[session])
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / script), *map(str, args)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=full_env, cwd=cwd, input=stdin,
    )
    if script == "db_pr.py" and list(args[:2]) == ["lock", "acquire"] and result.returncode == 0:
        _LOCK_OWNERS[session] = json.loads(result.stdout)["lock"]["owner"]
    return result


_VARIANT_DIR: Path | None = None


def variant_dir() -> Path:
    """`make_variant_dbs.build_all()` 결과 디렉터리. 프로세스당 한 번 임시 디렉터리에 만들고 종료 때 지운다."""
    global _VARIANT_DIR
    if _VARIANT_DIR is None or not _VARIANT_DIR.is_dir():
        import make_variant_dbs  # 지연 import (순환 방지)

        d = tmp("tt-variants-")
        make_variant_dbs.build_all(d)
        atexit.register(shutil.rmtree, d, True)
        _VARIANT_DIR = d
    return _VARIANT_DIR


def variant_db(name: str) -> Path:
    """변형 이슈 DB(또는 `verify-logs`) 경로. 읽기 전용으로 쓴다 — 바꾸려면 `copy_db()`로 복사한다."""
    import make_variant_dbs

    if name not in make_variant_dbs.VARIANTS:
        raise KeyError(f"알 수 없는 변형: {name}")
    return variant_dir() / name


def fixture_db(name: str) -> Path:
    return SAMPLE if name == "issue-db-sample" else variant_db(name)


def fixture_path(rel: str) -> Path:
    """`tests/fixtures/<변형>/나머지` → 생성된 변형 트리 안의 경로, 그 밖은 `REPO/rel`."""
    parts = Path(rel).parts
    if len(parts) >= 3 and parts[:2] == ("tests", "fixtures"):
        import make_variant_dbs

        if parts[2] in make_variant_dbs.VARIANTS:
            return variant_db(parts[2]).joinpath(*parts[3:])
    return REPO / rel


def run_json(script: str, args: list[str], expect: int | tuple = 0, **kw) -> dict:
    proc = run(script, args, **kw)
    codes = expect if isinstance(expect, tuple) else (expect,)
    assert proc.returncode in codes, f"{script} {args}: 종료 코드 {proc.returncode}\n{proc.stderr}"
    return json.loads(proc.stdout)


_TMP_DIRS: list[Path] = []


def tmp(prefix: str = "tt-test-") -> Path:
    """임시 디렉터리. 만든 경로를 기록해 두고 pytest 세션 끝에 지운다(`conftest.pytest_sessionfinish`, `TT_KEEP_TMP=1`이면 남긴다)."""
    d = Path(tempfile.mkdtemp(prefix=prefix))
    _TMP_DIRS.append(d)
    return d


def cleanup_tmp() -> None:
    """`tmp()`가 만든 디렉터리를 모두 지운다. `TT_KEEP_TMP=1`이면 남긴다."""
    if os.environ.get("TT_KEEP_TMP") == "1":
        return
    while _TMP_DIRS:
        shutil.rmtree(_TMP_DIRS.pop(), ignore_errors=True)


def copy_db(src: Path = SAMPLE, name: str = "db") -> Path:
    dest = tmp() / name
    shutil.copytree(src, dest)
    return dest


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "-c", "user.name=tt", "-c", "user.email=tt@example.invalid",
                           *args], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def git_db(src: Path = SAMPLE) -> Path:
    """이슈 DB 복사본을 main 브랜치에 커밋한 git 레포로 만든다."""
    repo = copy_db(src)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    return repo


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path.name}: {old!r} 없음"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
