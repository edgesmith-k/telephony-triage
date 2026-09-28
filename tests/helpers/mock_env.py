#!/usr/bin/env python3
"""모의 환경을 실행 환경에 연결하는 테스트 헬퍼 (15-local-draft.md §15.2).

- `gh_path_dir()`: `PATH` 앞에 둘 디렉토리. 기본은 `tests/mocks/bin`이다.
- `env_with_mocks()`: `PATH`에 스텁 디렉토리를 앞세운 환경 dict.

**Windows 개발 PC 전용 처리**: 실행 환경은 Ubuntu다
(`01-architecture.md §3`, `14-site.md` S15). `tests/mocks/bin/gh`는 확장자 없는
`#!/bin/sh` 스크립트라 Windows의 `subprocess`가 직접 실행하지 못한다.
그래서 Windows에서만 임시 디렉토리에 `gh.cmd` 래퍼를 **런타임에** 만들어
`PATH`에 앞세운다. 이 래퍼는 커밋하지 않으므로 반입물에는 POSIX 스텁만 남는다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MOCK_BIN = REPO / "tests" / "mocks" / "bin"
IS_WINDOWS = os.name == "nt"

_WINDOWS_SHIM_DIR: Path | None = None


def _windows_shim_dir() -> Path:
    """`gh.cmd` 래퍼를 담은 임시 디렉토리 (Windows 개발 PC 전용)."""
    global _WINDOWS_SHIM_DIR
    if _WINDOWS_SHIM_DIR is not None and _WINDOWS_SHIM_DIR.is_dir():
        return _WINDOWS_SHIM_DIR
    shim_dir = Path(tempfile.mkdtemp(prefix="tt-mock-bin-"))
    # `cmd.exe`는 배치 파일을 콘솔 코드페이지로 읽으므로 UTF-8로 쓴 비ASCII
    # 경로(예: 한글 디렉토리)가 깨진다. 스텁을 ASCII 경로인 임시 디렉토리로
    # 복사하고 `%~dp0`로 부른다. 배치 파일 안에는 ASCII만 남는다.
    shutil.copyfile(MOCK_BIN / "gh_stub.py", shim_dir / "gh_stub.py")
    (shim_dir / "gh.cmd").write_text(
        '@echo off\r\npython "%~dp0gh_stub.py" %*\r\n',
        encoding="ascii",
        newline="",  # 배치 파일은 CRLF다. 쓰기 때 다시 변환되지 않게 한다.
    )
    _WINDOWS_SHIM_DIR = shim_dir
    return shim_dir


def gh_path_dirs() -> list[Path]:
    """`PATH` 앞에 둘 디렉토리 목록."""
    dirs = [MOCK_BIN]
    if IS_WINDOWS:
        dirs.insert(0, _windows_shim_dir())
    return dirs


def env_with_mocks(
    base: dict | None = None,
    *,
    gh_state_dir: Path | str | None = None,
    gh_host: str | None = None,
    plugin_root: Path | str | None = None,
    unauth: bool = False,
) -> dict:
    """모의 스텁이 잡히는 환경 dict를 만든다."""
    env = dict(os.environ if base is None else base)
    prefix = os.pathsep.join(str(p) for p in gh_path_dirs())
    env["PATH"] = prefix + os.pathsep + env.get("PATH", "")
    if gh_state_dir is not None:
        env["MOCK_GH_STATE_DIR"] = str(gh_state_dir)
    else:
        # Windows 래퍼는 스텁 사본을 쓰므로 스텁이 자기 위치로 기본 상태
        # 디렉토리를 찾지 못한다. 문서화된 기본값을 명시한다.
        env.setdefault("MOCK_GH_STATE_DIR", str(REPO / "tests" / "mocks" / "gh-state"))
    if gh_host is not None:
        env["GH_HOST"] = gh_host
    if plugin_root is not None:
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    if unauth:
        env["MOCK_GH_UNAUTH"] = "1"
    else:
        env.pop("MOCK_GH_UNAUTH", None)
    # 스크립트 출력은 UTF-8이다. Windows 콘솔 기본 인코딩(cp949)에서 깨지지
    # 않게 한다. Ubuntu에서는 영향이 없다.
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def resolve(command: str, env: dict) -> str:
    """`env`의 `PATH`에서 실행 파일을 찾아 절대 경로로 준다.

    Ubuntu에서는 `subprocess`가 자식 환경의 `PATH`로 실행 파일을 찾으므로
    이 함수가 필요 없다. **Windows의 `CreateProcess`는 실행 파일을 찾을 때
    `lpEnvironment`가 아니라 부모 프로세스의 `PATH`를 쓴다.** 그래서 Windows
    개발 PC에서는 `env=`로 넘긴 `PATH`가 무시되고 진짜 `gh`가 잡힌다.
    테스트 코드에서만 쓰고, 플러그인 런타임 코드는 PATH의 `gh`를 그대로 쓴다
    (15-local-draft.md §15.2).
    """
    found = shutil.which(command, path=env.get("PATH"))
    return found or command


def cleanup() -> None:
    """Windows 래퍼 임시 디렉토리를 지운다."""
    global _WINDOWS_SHIM_DIR
    if _WINDOWS_SHIM_DIR is not None:
        shutil.rmtree(_WINDOWS_SHIM_DIR, ignore_errors=True)
        _WINDOWS_SHIM_DIR = None


if __name__ == "__main__":
    for path in gh_path_dirs():
        print(path)
    print(resolve("gh", env_with_mocks()))
