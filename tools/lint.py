#!/usr/bin/env python3
"""ruff 검사: `pyproject.toml` `[tool.ruff]` 규칙 묶음으로 plugin·tools·tests·opencode를 본다.
ruff는 선택 의존성 `lint` extra(`pip install '.[test,lint]'`)로 고정 버전을 설치한다.
끈 규칙의 사유는 pyproject 주석, 남긴 지적(PLW1510·BLE001·B023)의 검토 표는 `docs/development/LINT_REVIEW.md`.

CLI:
    python3 tools/lint.py [ruff check 옵션 ...]      예: --statistics, --select B023, --output-format json
        `--fix` 계열(`--add-noqa`, `--config fix=…` 포함)은 받지 않는다. 자동 수정은 동작을 바꿀 수 있어 `ruff check --fix --diff`로 diff를 보고
        hunk마다 검토해 사람이 적용한다(LINT_REVIEW.md).

종료 코드
    0  지적 없음
    1  지적 있음
    2  ruff 없음·버전 불일치·사용 오류
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = ("plugin", "tools", "tests", "opencode")
FIX_FLAGS = ("--fix", "--fix-only", "--unsafe-fixes", "--add-noqa", "--diff", "--watch")


def _ruff() -> list[str] | None:
    if importlib.util.find_spec("ruff"):
        return [sys.executable, "-m", "ruff"]
    exe = shutil.which("ruff")
    return [exe] if exe else None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    bad = [a for a in args if a.partition("=")[0] in FIX_FLAGS]
    # `--config fix=true`·`--config unsafe-fixes=true`도 파일을 고친다
    bad += [a for i, a in enumerate(args) if a.partition("=")[0] == "--config"
            and "fix" in (a.partition("=")[2] or (args[i + 1] if i + 1 < len(args) else ""))]
    if bad:
        print(f"{' '.join(bad)}: 받지 않는다 — 자동 수정은 동작을 바꿀 수 있어 `ruff check --fix --diff`로 diff를 보고 "
              "hunk마다 검토해 적용한다 (docs/development/LINT_REVIEW.md)", file=sys.stderr)
        return 2
    pin = re.search(r'"ruff==([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"))
    if pin is None:
        print("pyproject.toml lint 의존성에 ruff 고정 버전이 없다", file=sys.stderr)
        return 2
    ruff = _ruff()
    if ruff is None:
        print("ruff가 없다: python3 -m pip install '.[lint]' 로 고정 버전을 설치한다 (pyproject.toml)", file=sys.stderr)
        return 2
    try:
        version = subprocess.run([*ruff, "--version"], capture_output=True, text=True, check=True, cwd=REPO).stdout.split()[-1]
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        print(f"ruff 실행 실패: {exc}", file=sys.stderr)
        return 2
    if version != pin.group(1):
        print(f"ruff 버전 불일치: 설치 {version}, 고정 {pin.group(1)} — 규칙 결과가 달라지므로 고정 버전을 설치한다", file=sys.stderr)
        return 2
    return subprocess.run([*ruff, "check", *args, *TARGETS], cwd=REPO, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
