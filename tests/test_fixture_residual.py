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


DUMP = "Sep 20 15:10:05.000 host1 daemon.info ofonod[1]: src/dbus.c:example_dump() "


def test_dump_split_chunks_and_shape(tmp_path):
    """C1+D 보정 §1.2: 덤프 함수(`<함수>()`) 조각에 갈린 사업자 이름(거부 목록)과 MCC·MNC(모양 규칙)를 걸친 줄마다 지적.
    모양 규칙은 `--against` 없이도 본다. 한 줄 안의 모양 값도 지적, 앞머리(시각)가 다른 줄은 잇지 않는다."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "orig.txt").write_text("\n".join([
        DUMP.replace("host1", "mockhost") + 'method return - a:array[dict{"Name", variant("MOCK',
        DUMP.replace("host1", "mockhost") + '-CARRIER")}]',
    ]) + "\n", encoding="utf-8")
    deny = fixture_residual.deny_list(raw)
    assert deny.get("MOCK-CARRIER", ("",))[0] == "carrier"                 # 갈린 값도 거부 목록에 든다
    fix = tmp_path / "fixture"
    fix.mkdir()
    (fix / "source.log").write_text("\n".join([
        DUMP + 'method return - a:array[dict{"Name", variant("MOCK',
        DUMP + '-CARRIER")}, dict{"MobileCountryCode", variant("45',
        DUMP + '0")}, dict{"MobileNet',
        DUMP + 'workCode", variant("05")}]',
        "Sep 20 15:10:06.000 host1 daemon.info ofonod[1]: src/dbus.c:example_dump() "
        'a:[dict{"MobileCountryCode", variant("450")}]',
        "Sep 20 15:10:07.000 host1 daemon.info ofonod[1]: src/dbus.c:example_dump() "
        'dict{"MobileCountryCode", variant("<PLMN#1>")}]',
    ]) + "\n", encoding="utf-8")
    proc = _run(fix, "--against", raw, "--json")
    assert proc.returncode == 1
    kinds = sorted((x["line"], x["kind"]) for x in json.loads(proc.stdout)["findings"])
    assert kinds == [(1, "carrier"), (2, "carrier"), (2, "plmn"), (3, "plmn"), (4, "plmn"), (5, "plmn")], kinds
    assert not any(s in proc.stdout for s in SECRETS) and '"45' not in proc.stdout
    proc = _run(fix, "--json")                                             # 원본 없이: 모양 규칙만
    kinds = sorted((x["line"], x["kind"]) for x in json.loads(proc.stdout)["findings"])
    assert kinds == [(2, "plmn"), (3, "plmn"), (4, "plmn"), (5, "plmn")], kinds


def test_dump_chunks_interleaved_and_ms(tmp_path):
    """C-F1: 실제 로그는 조각 사이에 다른 줄이 끼고 ms가 바뀐다. 시각을 뺀 앞머리가 같고 1초 안이면 잇고, 순번은 원래 줄이다."""
    other = "Sep 20 15:10:05.003 host1 daemon.info ofonod[1]: src/network.c:other() x"
    lines = [
        DUMP.replace(".000", ".001") + 'dict{"MobileCountryCode", variant("4',
        other,
        DUMP.replace(".000", ".004").replace("[1]", "[2]") + "other pid",
        DUMP.replace(".000", ".007") + '50")}]',
        DUMP.replace("05.000", "07.000") + "late chunk",
    ]
    assert fixture_residual.dump_groups(lines) == [[(0, len(DUMP)), (3, len(DUMP))]]
    hits = fixture_residual.cross_hits(lines, fixture_residual.SHAPE_RX)
    assert [(k, [i for i, _a, _b in pieces]) for k, _v, pieces in hits] == [("plmn", [0, 3])]
    fix = tmp_path / "source.log"
    fix.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc = _run(fix, "--json")
    assert sorted((x["line"], x["kind"]) for x in json.loads(proc.stdout)["findings"]) == [(1, "plmn"), (4, "plmn")]


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
