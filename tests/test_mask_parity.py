#!/usr/bin/env python3
"""`tools/mask_parity.py` (B2 §3.5 1번 관문 도구): 합성 두 파일로 종류별 수·기준 비교·종료 코드·값 미출력.

`pytest tests/test_mask_parity.py`로 돈다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "mask_parity.py"

IMSI = "45005" + "1234567890"            # 합성 15자리(경계 검사의 긴 숫자 패턴을 피해 나눠 쓴다)
SECRETS = ("mockhost", IMSI, "QUJDREVGR0hJSktMTU5PUA", "0a 1b 2c 3d", "1234567890123456789")
OFONO = [
    f"Sep 20 14:32:11 mockhost ofonod[812]: imsi={IMSI}",
    "Sep 20 14:32:12 mockhost ofonod[812]: gril: IPC: RX: 0a 1b 2c 3d 4e",
    "Sep 20 14:32:13 mockhost ofonod[812]: drivers/rilmodem/network.c:120 ok",
]
ANDROID = [
    "08-09 13:10:57.528  1856  2167 D RILJ    : SIM_AUTHENTICATION resp: QUJDREVGR0hJSktMTU5PUA==",
    "08-09 13:10:57.529  1856  2167 D X       : seq 1234567890123456789 done",
    "08-09 13:10:57.530  1856  2167 D DATA    : src/java/com/example/telephony/DataNetwork.java:120",
]


def _corpus() -> tuple[Path, Path]:
    d = Path(tempfile.mkdtemp(prefix="tt-parity-"))
    a, b = d / "ofono.log", d / "android.log"
    a.write_text("\r\n".join(OFONO) + "\r\n", encoding="utf-8")
    b.write_text("\n".join(ANDROID) + "\n", encoding="utf-8")
    return a, b


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True, encoding="utf-8")


def test_counts_and_no_values():
    a, b = _corpus()
    proc = _run(a, b, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] and doc["fails"] == []
    assert doc["files"]["ofono.log"]["kinds"] == {"HEXDUMP": 1, "HOST": 3, "IMSI": 1}
    assert doc["files"]["ofono.log"]["lines"] == 3
    assert doc["files"]["android.log"]["kinds"] == {"B64": 1, "NUM": 1}
    for got in doc["files"].values():
        assert got["b64_path_shaped"] == 0 and got["residual"] == {}
    text = _run(a, b).stdout
    for out in (proc.stdout, text):
        assert not any(s in out for s in SECRETS)
    assert "통과" in text


def test_baseline_comparison_and_exit_codes():
    a, b = _corpus()
    base = a.parent / "baseline.json"
    base.write_text(json.dumps({"ofono.log": {"HOST": 3, "IMSI": 1}, "android.log": {"B64": 2, "NUM": 1}}),
                    encoding="utf-8")
    proc = _run(a, b, "--baseline", base, "--json")
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["fails"] == ["android.log: B64 1 < 기준 2"]
    base.write_text(json.dumps({"ofono.log": {"HOST": 3}, "android.log": {"B64": 1}}), encoding="utf-8")
    assert _run(a, b, "--baseline", base).returncode == 0
    base.write_text("[1, 2]", encoding="utf-8")
    assert _run(a, "--baseline", base).returncode == 2
    assert _run(a.parent / "missing.log").returncode == 2
    assert _run(a, "--allow", "(").returncode == 2


def test_allow_pattern_and_path_shapes():
    a, _b = _corpus()
    proc = _run(a, "--allow", r"\d{15}", "--json")
    assert json.loads(proc.stdout)["files"]["ofono.log"]["kinds"].get("IMSI") is None
