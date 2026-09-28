#!/usr/bin/env python3
"""파서 fixture(`tests/fixtures/logs/`)를 시나리오에서 생성한다 (11-phases.md Phase 2).

`tests/mocks/log_fixtures.yaml`의 표대로 `tests/mocks/logcat_gen.py`를 돌려
`tests/fixtures/logs/<name>.log`를 만든다. 로그만 만들고 `.expect.yaml`은 만들지
않는다(이슈 DB fixture가 아니다). 로그는 마스킹해서 쓴다. 생성기와 마스킹은 결정적이다.

로그 파일은 **커밋한다**. 이 스크립트는 다시 만들 때와, 커밋된 내용이 시나리오와
맞는지 검사할 때 쓴다. 이벤트 스냅샷은 `tests/test_parse_logcat.py --update`가 만든다.

CLI:
    python3 tests/helpers/make_log_fixtures.py [--check] [--json]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO / "tests" / "mocks" / "scenarios"
TABLE = REPO / "tests" / "mocks" / "log_fixtures.yaml"
LOG_DIR = REPO / "tests" / "fixtures" / "logs"

sys.path.insert(0, str(REPO / "tests" / "mocks"))
import logcat_gen  # noqa: E402

sys.path.insert(0, str(REPO / "plugin" / "scripts"))
from common import masking  # noqa: E402


def mask_log(path: Path, allow_patterns=()) -> None:
    """생성한 로그를 마스킹해서 다시 쓴다 (모든 테스트 로그는 마스킹된 fixture만 쓴다,
    CLAUDE.md §11.0). 파일마다 마스커 하나 — `mask_pii.py <file> --in-place`와 같다."""
    text = path.read_text(encoding="utf-8")
    masker = masking.new_masker(text, allow_patterns)
    path.write_text("\n".join(masker(line) for line in text.split("\n")), encoding="utf-8", newline="\n")


def sample_allow_patterns() -> list[str]:
    cfg = yaml.safe_load((REPO / "tests/fixtures/issue-db-sample/issue-db.config.yaml").read_text(encoding="utf-8"))
    return list((cfg.get("mask") or {}).get("allow_patterns") or [])


def load_table() -> list[dict]:
    with TABLE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    entries = data.get("fixtures") or []
    if not entries:
        raise SystemExit(f"{TABLE}: fixtures 목록이 비어 있습니다.")
    return entries


def _generate(entry: dict, out_dir: Path) -> Path:
    scenario = SCENARIO_DIR / entry["scenario"]
    if not scenario.exists():
        raise SystemExit(f"시나리오가 없습니다: {scenario}")
    info = logcat_gen.generate(scenario, out_dir, name=entry["name"])
    path = Path(info["files"][0])
    mask_log(path, sample_allow_patterns())
    return path


def run(check: bool = False) -> dict:
    entries = load_table()
    written, missing, mismatched = [], [], []
    tmp = Path(tempfile.mkdtemp(prefix="tt-log-fixture-"))
    try:
        for entry in entries:
            generated = _generate(entry, tmp)
            target = LOG_DIR / generated.name
            if check:
                if not target.exists():
                    missing.append(str(target.relative_to(REPO)))
                elif target.read_bytes() != generated.read_bytes():
                    mismatched.append(str(target.relative_to(REPO)))
            else:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(generated, target)
                written.append(str(target.relative_to(REPO)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {"count": len(entries), "written": written, "missing": missing, "mismatched": mismatched}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_log_fixtures.py", description=__doc__)
    parser.add_argument("--check", action="store_true", help="쓰지 않고 커밋된 내용과 비교")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run(check=args.check)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.check:
        for path in result["missing"]:
            print(f"없음: {path}")
        for path in result["mismatched"]:
            print(f"다름: {path}")
        if not result["missing"] and not result["mismatched"]:
            print(f"파서 fixture {result['count']}개가 시나리오와 일치합니다.")
    else:
        for path in result["written"]:
            print(path)
    return 1 if result["missing"] or result["mismatched"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
