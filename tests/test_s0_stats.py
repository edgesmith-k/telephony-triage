#!/usr/bin/env python3
"""tools/s0_stats.py: 사내 로그가 사외 파서 가정과 다를 때 신호가 나오는지 (docs/development/S0_PROBE_CHECKLIST.md)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, plugin_root, tmp  # noqa: E402

LOGS = REPO / "tests" / "fixtures" / "logs"


def stats(*logs: Path, expect: int = 0) -> str:
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "s0_stats.py"), *map(str, logs), "--rules",
                           str(SAMPLE / "parser-rules"), "--tz", "Asia/Seoul", "--year", "2026", "--plugin-root",
                           str(plugin_root())], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == expect, proc.stderr
    return proc.stdout


def test_matching_logs_report_full_parse_pairs_slots_and_clock_anomalies():
    out = stats(LOGS / "dual-sim-ril.log", LOGS / "clock-anomaly.log")
    assert "시각 파싱: 11/11 (100%)" in out and "RIL 짝 맞춤: 3/4 (75%)" in out
    assert "phone_id 추출: 10/11 (91%)" in out
    assert "시계 이상 2건" in out and "[합계 2개]" in out
    assert "RILJ" in out and "SETUP_DATA_CALL" not in out        # 태그 이름은 내고, 로그 문구는 내지 않는다


def test_foreign_format_shows_up_as_unparsed_lines_and_zero_ril_requests():
    log = tmp("tt-s0-") / "vendor.log"
    log.write_text("2026-09-22 12:00:00.123 +0900 I/RILJ(1234): [SUB0] request SETUP_DATA_CALL\n"
                   "2026-09-22 12:00:01.200 +0900 I/RILJ(1234): [SUB0] response ok\n"
                   "stray line without timestamp\n", encoding="utf-8")
    out = stats(log)
    assert "시각 파싱: 2/3 (67%)" in out and "RIL 짝 맞춤: 0/0 (-)" in out and "warnings 1" in out


def test_missing_site_defaults_stops_with_guidance():
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "s0_stats.py"), str(LOGS / "dual-sim-ril.log"),
                           "--rules", str(SAMPLE / "parser-rules"), "--tz", "Asia/Seoul"],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode != 0 and "make_plugin_root.py" in proc.stderr


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok   {name}")
