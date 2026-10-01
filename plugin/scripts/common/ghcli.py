"""gh CLI 호출 (contracts.md §3.2, 02-config.md §4 setup 9).

`gh`는 PATH에서 찾는다(`shutil.which`). Windows 개발 PC에서는 `subprocess`가 실행 파일을
부모 PATH·`.exe`로만 찾아 테스트 스텁(`gh.cmd`)을 못 찾으므로 `shutil.which`로 경로를 먼저
구한다. Ubuntu에서는 PATH의 `gh`와 같다.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def executable() -> str:
    return shutil.which("gh") or "gh"


def run(args: list[str], host: str | None = None, **kwargs) -> subprocess.CompletedProcess:
    env = dict(kwargs.pop("env", None) or os.environ)
    if host:
        env["GH_HOST"] = host
    kwargs.setdefault("timeout", 120)
    try:
        return subprocess.run([executable(), *args], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, **kwargs)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([executable(), *args], 124, "", "gh 시간 초과. 원격 상태를 확인한 뒤 재개한다.")
    except OSError as exc:
        return subprocess.CompletedProcess([executable(), *args], 127, "", f"gh를 실행할 수 없습니다: {exc}")


def auth_status(host: str | None) -> tuple[bool, str]:
    args = ["auth", "status"] + (["--hostname", host] if host else [])
    proc = run(args, host=host)
    return proc.returncode == 0, (proc.stderr or proc.stdout).strip()
