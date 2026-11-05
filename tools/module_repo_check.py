#!/usr/bin/env python3
"""모듈 스킬 레포 체크아웃의 토큰 없는 점검(GHE 웹 PR 병합 전, amendments R10).

    python3 tools/module_repo_check.py <clone 또는 템플릿 디렉토리>

`triage.py module`이 받을 때 하는 것과 같은 규칙을 디렉토리에 건다:
- `skillcheck.check_worktree`(트리 규칙 + 모든 위험 지시, `raw-read` 포함),
- `modules.yaml`: `load_modules_yaml` + `validate_modules(strict=True)`(모르는 키도 오류).

출력은 `경로[:줄] 점검` 줄만(파일 내용·정규식 값은 내지 않는다). 종료 코드 0 = 깨끗함, 1 = 찾음, 2 = 사용 오류.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for cand in (HERE.parent / "plugin" / "scripts", HERE.parent / "scripts"):
    if (cand / "common" / "skillcheck.py").is_file():
        sys.path.insert(0, str(cand))
        break

from common import skillcheck


def findings(root: Path) -> list[str]:
    out = []
    for f in skillcheck.check_worktree(root):
        where = f"{f['path']}:{f['line']}" if "line" in f else f["path"]
        out.append(f"{where} {f['check']}")
    path = root / "modules.yaml"
    if not path.is_file() or path.is_symlink():
        out.append("modules.yaml modules.yaml 없음")
        return out
    try:
        doc = skillcheck.load_modules_yaml(path.read_bytes())
    except Exception as exc:  # noqa: BLE001 — ValueError·UnicodeDecodeError·yaml.YAMLError
        reason = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeDecodeError) else type(exc).__name__
        out.append(f"modules.yaml modules.yaml({reason})")
        return out
    for err in skillcheck.validate_modules(doc, strict=True):
        out.append(f"modules.yaml modules.yaml({err})")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="module_repo_check.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("checkout")
    args = parser.parse_args(argv)
    root = Path(args.checkout)
    if not root.is_dir():
        print(f"디렉토리가 아니다: {args.checkout}", file=sys.stderr)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    lines = findings(root)
    for line in lines:
        print(line)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
