#!/usr/bin/env python3
"""모듈 스킬 레포 체크아웃의 토큰 없는 점검(GHE 웹 PR 병합 전, amendments R10).

    python3 tools/module_repo_check.py [--template] <clone 또는 템플릿 디렉토리>

`triage.py module`이 받을 때 하는 것과 같은 규칙을 디렉토리에 건다:
- `skillcheck.check_worktree`(트리 규칙 + 모든 위험 지시, `raw-read` 포함),
- `modules.yaml`: `load_modules_yaml` + `validate_modules(strict=True)`(모르는 키도 오류).

`--template`(저장소 템플릿 트리, H C1+D R41): 위에 `skillcheck.template_findings`(case 출처 표시·`files/` 모양·플랫폼
섞임·oFono 데몬 표·oFono 문서 D-Bus 이름)를 더한다.
받을 때 아직 하지 않는 점검(`moduleskills.CHECKS_SKIPPED`)은 stderr에 `건너뜀(E): <점검>`으로 알린다(종료 코드는 그대로).

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

import platforms
from common import skillcheck


def findings(root: Path, template: bool = False) -> list[str]:
    out = []
    if template:
        for f in skillcheck.template_findings(root, platforms.template_metas()):
            where = f"{f['path']}:{f['line']}" if "line" in f else f["path"]
            out.append(f"{where} {f['check']}" + (f"({f['rule']})" if f.get("rule") else ""))
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
    parser.add_argument("--template", action="store_true", help="저장소 템플릿 트리 점검(template_findings)도 한다")
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
    lines = findings(root, template=args.template)
    for line in lines:
        print(line)
    try:
        from common import moduleskills
        skipped = list(moduleskills.CHECKS_SKIPPED)
    except ImportError:          # 독립 사본(scripts/ 없음): 건너뛴 점검 목록을 알 수 없다
        skipped = ["받을 때 점검 목록(moduleskills 없음)"]
    for name in skipped:
        print(f"건너뜀(E): {name}", file=sys.stderr)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
