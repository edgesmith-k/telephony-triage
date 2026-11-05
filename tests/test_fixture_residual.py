#!/usr/bin/env python3
"""`tools/fixture_residual.py` (B2 §4.8): 남은 식별자 종류별 지적, `--against` 거부 목록, 값 미출력, 종료 코드,
저장소 fixture·case 파일이 깨끗한지."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "fixture_residual.py"
sys.path.insert(0, str(REPO / "tools"))

import fixture_residual

IMSI = "45005" + "1234567890"
SECRETS = (IMSI, "mockhost", "apn.mock-carrier.example", "MOCK-CARRIER", "A0000000871002FFAA", "/dev/mock_ipc0")


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True, encoding="utf-8")


def test_residual_kinds_and_host(tmp_path):
    f = tmp_path / "source.log"
    f.write_text("\n".join([
        f"Sep 20 15:10:00.000 dut daemon.info ofonod[1]: imsi={IMSI}",
        "Sep 20 15:10:01.000 mockhost daemon.info ofonod[1]: hello",
        "Sep 20 15:10:02.000 host2 daemon.info ofonod[1]: x: 0a 1b 2c 3d 4e",
        "Sep 20 15:10:03.000 (none) daemon.info ofonod[1]: clean <IMSI#1> <HEXDUMP 4B>",
    ]) + "\n", encoding="utf-8")
    proc = _run(f, "--json")
    assert proc.returncode == 1
    found = json.loads(proc.stdout)["findings"]
    assert sorted((x["line"], x["kind"]) for x in found) == [(1, "IMSI"), (2, "HOST"), (2, "host"), (3, "HEXDUMP")]
    out = proc.stdout + _run(f).stdout
    assert not any(s in out for s in SECRETS)


def test_against_deny_list(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "orig.txt").write_text("\n".join([
        "Sep 20 15:10:00.000 mockhost daemon.info ofonod[1]: apn=apn.mock-carrier.example ok",
        "Sep 20 15:10:01.000 mockhost daemon.info ofonod[1]: mOperatorAlphaLong=MOCK-CARRIER numeric=45005",
        "Sep 20 15:10:02.000 mockhost daemon.info ofonod[1]: select aid A0000000871002FFAA on /dev/mock_ipc0",
    ]) + "\n", encoding="utf-8")
    fix = tmp_path / "fixture"
    fix.mkdir()
    (fix / "source.log").write_text("\n".join([
        "Sep 20 15:10:00.000 host1 daemon.info ofonod[1]: apn=apn.mock-carrier.example ok",
        "Sep 20 15:10:01.000 host1 daemon.info ofonod[1]: name MOCK-CARRIER plmn 45005",
        "Sep 20 15:10:02.000 host1 daemon.info ofonod[1]: select aid A0000000871002FFAA on /dev/mock_ipc0 /dev/null",
        "Sep 20 15:10:03.000 host1 daemon.info ofonod[1]: mockhost restarted",
    ]) + "\n", encoding="utf-8")
    proc = _run(fix, "--against", raw, "--json")
    assert proc.returncode == 1
    doc = json.loads(proc.stdout)
    kinds = sorted((x["line"], x["kind"]) for x in doc["findings"])
    assert kinds == [(1, "apn"), (2, "carrier"), (2, "plmn"), (3, "aid"), (3, "device_node"), (4, "host")]
    assert all("raw_line" in x for x in doc["findings"])
    assert not any(s in proc.stdout for s in SECRETS)
    assert _run(fix / "source.log").returncode == 0           # 원본 없이는 마스킹된 줄로 보인다


def test_exit_codes(tmp_path):
    assert _run(tmp_path / "missing.log").returncode == 2
    clean = tmp_path / "ok.log"
    clean.write_text("Sep 20 15:10:00.000 dut daemon.info ofonod[1]: hello\n", encoding="utf-8")
    assert _run(clean).returncode == 0
    assert _run(clean, "--against", tmp_path / "nope").returncode == 2


def test_repo_fixtures_and_cases_clean():
    paths = fixture_residual._files([str(REPO / "tests" / "fixtures" / "module-filter")])
    paths += [p for p in sorted((REPO / "templates" / "module-skills").glob("*/*/evals/*/files/*")) if p.is_file()]
    assert paths and fixture_residual.check(paths) == []
