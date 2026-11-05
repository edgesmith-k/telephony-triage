#!/usr/bin/env python3
"""모듈 필터 fixture의 `events.json`을 결정적으로 만든다 (B2 §4.9).

`tests/fixtures/module-filter/<case>/source.log`(마스킹한 실제 발췌 또는 합성)와 `expect.yaml`의 `platform`으로
`parse_logcat.py parse --full --mask`를 돌린다. 규칙: oFono는 변형 DB `issue-db-ofono-modules`, Android는 샘플 DB.
마스킹은 저장소 로그 마스커(M1~M11 반영)다. 출력의 임시 경로는 지운다(`rules.path`·`input.files`).

CLI:
    python3 tests/helpers/make_filter_fixtures.py --write [--case NAME ...]
    python3 tests/helpers/make_filter_fixtures.py --check [--case NAME ...] [--json]

종료 코드: 0 = 완료·drift 없음, 1 = drift, 2 = 사용·환경 오류.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "plugin" / "scripts", REPO / "tests" / "mocks", REPO / "tests" / "helpers"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yaml

FIXTURES = REPO / "tests" / "fixtures" / "module-filter"
SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
OFONO_DB = "issue-db-ofono-modules"
PLATFORM = {"name": "android", "enabled": ["android", "ofono"]}
TZ, YEAR = "UTC", "2026"
OK, DRIFT, USAGE = 0, 1, 2


def case_dirs(names: list[str] | None = None) -> list[Path]:
    found = sorted(p.parent for p in FIXTURES.glob("*/expect.yaml"))
    if names:
        unknown = sorted(set(names) - {p.name for p in found})
        if unknown:
            raise ValueError(f"알 수 없는 case: {', '.join(unknown)}")
        found = [p for p in found if p.name in names]
    return found


def generate(dirs: list[Path]) -> dict[str, str]:
    """{case 이름: events.json 내용}."""
    import make_variant_dbs
    import runner

    tmp = Path(tempfile.mkdtemp(prefix="tt-filter-fixtures-"))
    try:
        dbs = {"ofono": make_variant_dbs.build(OFONO_DB, tmp / "db-ofono"), "android": SAMPLE}
        root = runner.plugin_root("ofono-on", platform=PLATFORM)
        out = {}
        for d in dirs:
            expect = yaml.safe_load((d / "expect.yaml").read_text(encoding="utf-8"))
            platform = expect["platform"]
            proc = runner.run("parse_logcat.py", ["parse", d / "source.log", "--rules", dbs[platform] / "parser-rules",
                                                  "--tz", TZ, "--year", YEAR, "--full", "--mask"], root=root)
            if proc.returncode != 0:
                raise RuntimeError(f"{d.name}: parse 종료 코드 {proc.returncode}: {proc.stderr.strip()[-300:]}")
            doc = json.loads(proc.stdout)
            doc.setdefault("rules", {})["path"] = "parser-rules"
            doc.setdefault("input", {})["files"] = ["source.log"]
            text = json.dumps(doc, ensure_ascii=False) + "\n"
            for marker in (str(tmp), str(REPO)):
                if marker in text:
                    raise RuntimeError(f"{d.name}: 절대 경로가 남았다")
            out[d.name] = text
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for path in list(runner._ROOTS.values()):
            shutil.rmtree(path, ignore_errors=True)
        runner._ROOTS.clear()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_filter_fixtures.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    parser.add_argument("--case", action="append", metavar="NAME")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        dirs = case_dirs(args.case)
        outputs = generate(dirs)
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return USAGE
    if args.write:
        for d in dirs:
            (d / "events.json").write_bytes(outputs[d.name].encode("utf-8"))
            print(f"{d.name}: events.json 씀")
        return OK
    drift = {}
    for d in dirs:
        path = d / "events.json"
        same = path.is_file() and path.read_bytes() == outputs[d.name].encode("utf-8")
        drift[d.name] = "일치" if same else ("다름" if path.is_file() else "없음")
    if args.json:
        print(json.dumps(drift, ensure_ascii=False, indent=1))
    else:
        for name, status in drift.items():
            print(f"{name}/events.json: {status}")
    return DRIFT if any(v != "일치" for v in drift.values()) else OK


if __name__ == "__main__":
    sys.exit(main())
