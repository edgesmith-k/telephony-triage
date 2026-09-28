#!/usr/bin/env python3
"""합성 샘플 이슈 DB의 fixture를 시나리오에서 생성한다 (11-phases.md Phase 1).

`tests/mocks/sample_fixtures.yaml`의 표대로 `tests/mocks/logcat_gen.py`를 돌려
`tests/fixtures/issue-db-sample/<type_dir>/fixtures/`에 넣는다. 생성기는
결정적이므로 같은 시나리오는 항상 같은 파일을 낸다.

fixture 파일은 **커밋한다**(이슈 DB의 일부이므로). 이 스크립트는 다시 만들 때와
커밋된 내용이 시나리오와 맞는지 검사할 때 쓴다.

CLI:
    python3 tests/helpers/make_sample_fixtures.py [--check] [--json]

    --check  파일을 쓰지 않고 커밋된 내용과 재생성 결과를 비교한다
             (다르면 종료 코드 1).
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
TABLE = REPO / "tests" / "mocks" / "sample_fixtures.yaml"
SAMPLE_DB = REPO / "tests" / "fixtures" / "issue-db-sample"

sys.path.insert(0, str(REPO / "tests" / "mocks"))
import logcat_gen  # noqa: E402


def load_table() -> list[dict]:
    with TABLE.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    entries = data.get("fixtures") or []
    if not entries:
        raise SystemExit(f"{TABLE}: fixtures 목록이 비어 있습니다.")
    return entries


def _generate_one(entry: dict, out_dir: Path) -> list[Path]:
    scenario = SCENARIO_DIR / entry["scenario"]
    if not scenario.exists():
        raise SystemExit(f"시나리오가 없습니다: {scenario}")
    info = logcat_gen.generate(scenario, out_dir, name=entry["name"])
    paths = [Path(p) for p in info["files"]]
    if info["expect"]:
        paths.append(Path(info["expect"]))
    return paths


def run(check: bool = False) -> dict:
    entries = load_table()
    written: list[str] = []
    mismatched: list[str] = []
    missing: list[str] = []

    for entry in entries:
        dest = SAMPLE_DB / entry["type_dir"] / "fixtures"
        if check:
            tmp = Path(tempfile.mkdtemp(prefix="tt-sample-fixture-"))
            try:
                for path in _generate_one(entry, tmp):
                    target = dest / path.name
                    if not target.exists():
                        missing.append(str(target.relative_to(REPO)))
                    elif target.read_bytes() != path.read_bytes():
                        mismatched.append(str(target.relative_to(REPO)))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            for path in _generate_one(entry, dest):
                written.append(str(path.relative_to(REPO)))

    return {
        "count": len(entries),
        "written": written,
        "missing": missing,
        "mismatched": mismatched,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_sample_fixtures.py", description=__doc__)
    parser.add_argument("--check", action="store_true", help="쓰지 않고 커밋된 내용과 비교")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run(check=args.check)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.check:
            for path in result["missing"]:
                print(f"없음: {path}")
            for path in result["mismatched"]:
                print(f"다름: {path}")
            if not result["missing"] and not result["mismatched"]:
                print(f"fixture {result['count']}개가 시나리오와 일치합니다.")
        else:
            for path in result["written"]:
                print(path)
    if result["missing"] or result["mismatched"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
