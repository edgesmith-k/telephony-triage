#!/usr/bin/env python3
"""테스트용 플러그인 루트를 만든다 (15-local-draft.md §15.1).

`plugin/`을 임시 디렉토리로 복사하고 `site-defaults.example.yaml`을
`site-defaults.yaml`로 넣는다. 모든 테스트·eval은 이 루트를
`${CLAUDE_PLUGIN_ROOT}`로 쓴다. 개발 레포의 `plugin/` 안에는
`site-defaults.yaml`을 만들지 않는다 (반입 체크리스트 §15.4).

CLI:
    python3 tests/helpers/make_plugin_root.py --out <dir> [--with-site-backend]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "plugin"
EXAMPLE = "site-defaults.example.yaml"
TARGET = "site-defaults.yaml"
MOCK_SITE_BACKEND = REPO / "tests" / "mocks" / "parser_backends" / "site"
MOCK_ADAPTERS = REPO / "tests" / "mocks" / "adapters"

# 사외 PC(Windows 등)에서 POSIX 스텁을 PATH로 부를 수 있게 하는 런타임 shim.
# 커밋하지 않는다. 실행 환경은 Ubuntu다 (01-architecture.md §3, 14-site.md S15).
_WINDOWS = os.name == "nt"


def make(out: Path | None = None, with_site_backend: bool = False) -> Path:
    """임시 플러그인 루트를 만들고 경로를 준다."""
    if out is None:
        out = Path(tempfile.mkdtemp(prefix="tt-plugin-root-"))
    else:
        out = Path(out)
        if out.exists():
            shutil.rmtree(out)
    shutil.copytree(PLUGIN, out, dirs_exist_ok=True)

    example = out / EXAMPLE
    if not example.is_file():
        raise SystemExit(f"{PLUGIN / EXAMPLE} 이(가) 없습니다.")
    shutil.copyfile(example, out / TARGET)

    if (out / TARGET).is_file() and (PLUGIN / TARGET).is_file():
        raise SystemExit(
            f"{PLUGIN / TARGET} 이(가) 개발 레포에 있습니다. "
            "site-defaults.yaml은 사내 전용입니다 (SITE_PATHS)."
        )

    if with_site_backend:
        if not MOCK_SITE_BACKEND.is_dir():
            raise SystemExit(f"{MOCK_SITE_BACKEND} 이(가) 없습니다.")
        dest = out / "scripts" / "parser_backends" / "site"
        shutil.copytree(MOCK_SITE_BACKEND, dest, dirs_exist_ok=True)
        if MOCK_ADAPTERS.is_dir():
            adapters = out / "scripts" / "adapters"
            adapters.mkdir(parents=True, exist_ok=True)
            for src in MOCK_ADAPTERS.glob("site_*.py"):
                shutil.copyfile(src, adapters / src.name)

    _restore_exec_bits(out)
    return out


def _restore_exec_bits(root: Path) -> None:
    """복사본의 실행 비트를 살린다 (Ubuntu에서 PATH 스텁·훅 실행에 필요)."""
    for path in root.rglob("*"):
        if path.is_file() and _looks_executable(path):
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _looks_executable(path: Path) -> bool:
    if path.suffix in {".sh", ".py"}:
        return True
    try:
        with path.open("rb") as fh:
            return fh.read(2) == b"#!"
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_plugin_root.py", description=__doc__)
    parser.add_argument("--out", default=None, help="만들 경로 (기본: 임시 디렉토리)")
    parser.add_argument(
        "--with-site-backend",
        action="store_true",
        help="모의 site 파서 백엔드와 site_* 어댑터를 함께 넣는다 (16-existing-assets.md §16.6)",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = make(Path(args.out) if args.out else None, args.with_site_backend)
    if args.json:
        print(json.dumps({"plugin_root": str(root), "windows_host": _WINDOWS}, ensure_ascii=False))
    else:
        print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
