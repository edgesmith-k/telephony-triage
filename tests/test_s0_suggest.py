#!/usr/bin/env python3
"""tools/s0_suggest.py: 사내 로그에서 tags.yaml diff·슬롯·벤더 RIL 설정 초안을 제안하고, 문구는 내지 않는다."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import copy_db, plugin_root, tmp  # noqa: E402

SENTINEL, NUMBER = "SENTINEL_TEXT_XYZ", "123456789" + "012345"     # 15자리(경계 검사 회피: 리터럴로 쓰지 않는다)


def _log() -> str:
    rows = []   # (초, pid, 태그, 메시지)
    for i in range(5):
        s = 41 + i
        t = i * 4
        rows += [(t, 1000, "RILJ", f"[{s}]> SETUP_DATA_CALL apn=x [PHONE0]"),
                 (t + 0.05, 2000, "VRIL_HAL", f"req serial={s} name=SETUP {SENTINEL} {NUMBER}"),
                 (t + 0.5, 2000, "VRIL_SOCK", f"resp token={s} {SENTINEL}"),
                 (t + 0.5, 1000, "RILJ", f"[{s}]< SETUP_DATA_CALL error=NONE [PHONE0]"),
                 (t + 0.06, 2000, "VRIL_FREE", f"{SENTINEL} {'Alice Bob Carol Dave Erin'.split()[i]} sent req {s}"),
                 (t + 0.07, 2000, "VRIL_APN", f"apn=internet.example.com serial={s}")]
    for i in range(30):
        rows.append((i * 0.5, 2000, "VRIL_MODEM", f"data 0xdeadbeef{i:02x} len=12 {SENTINEL}"))
    for i in range(3):
        rows += [(i, 1000, "DSMGR-0", f"enabled=true {SENTINEL}"), (i, 1000, "DSM-C-1", "call"), (i, 1000, "DSM-I-2", "call"),
                 (i, 1000, "AirplaneModeStats", "x"), (i, 1000, "SmsStorageMonitor", "x"),
                 (i, 1000, "DNC-0", f"[SLOT1] x {SENTINEL}")]
    rows.sort(key=lambda r: r[0])
    return "".join(f"09-22 12:00:{int(t):02d}.{int(t % 1 * 1000):03d} {pid} {pid + 1} D {tag}: {msg}\n"
                   for t, pid, tag, msg in rows)


@pytest.fixture(scope="module")
def run():
    db = copy_db(name="s0s")
    tags = db / "parser-rules" / "tags.yaml"       # DSMGR·DSM 규칙을 뺀다: 미수집 태그 후보가 생긴다
    tags.write_text("".join(ln for ln in tags.read_text(encoding="utf-8").splitlines(True)
                            if "DSMGR-" not in ln and "DSM-[CI]" not in ln), encoding="utf-8", newline="\n")
    log = tmp("tt-s0s-") / "a.log"
    log.write_text(_log(), encoding="utf-8", newline="\n")

    def go(*extra: str, expect: int = 0):
        proc = subprocess.run([sys.executable, str(REPO / "tools" / "s0_suggest.py"), str(log), "--rules", str(db / "parser-rules"),
                               "--tz", "Asia/Seoul", "--year", "2026", "--plugin-root", str(plugin_root()), *extra],
                              capture_output=True, text=True, encoding="utf-8")
        assert proc.returncode == expect, proc.stderr
        return proc.stdout
    return go


def test_output_never_contains_message_text_or_raw_numbers(run):
    for out in (run(), run("--json")):
        assert SENTINEL not in out and NUMBER not in out and "SETUP_DATA_CALL" not in out


def test_tags_diff_and_zero_line_rules(run):
    out = run()
    assert r"'^DSMGR-\d+$', category: data" in out and r"'^DSM-[CI]-\d+$'" in out
    assert "tag: AirplaneModeStats, category: common" in out and "tag: SmsStorageMonitor, category: sms" in out
    assert r"^DCM-\d+$" in json.loads(run("--json"))["tags"]["zero_line_rules"]     # 합성 로그에 DCM 줄이 없다


def test_slot_form_not_matched_gets_regex_draft(run):
    out = run()
    assert "msg_prefix [SLOT#]: 현재 규칙 일치 0 / 불일치 3" in out and "msg_suffix [PHONE#]: 현재 규칙 일치 10" in out
    draft = json.loads(run("--json"))["slots"]["draft"]["msg_prefix"]
    assert re.match(draft[-1], "[SLOT1] x").group(1) == "1" and re.match(draft[0], "[SUB0] x")    # 기존 규칙도 남긴다


def test_vendor_ril_candidates_and_drafts(run):
    data = json.loads(run("--json"))
    rows = {r["tag"]: r for r in data["ril"]["tags"]}
    assert rows["VRIL_HAL"]["ratio"] == 1.0 and rows["VRIL_HAL"]["verdict"] == "후보"
    assert rows["VRIL_SOCK"]["resp_side"] > 0.5 and rows["VRIL_MODEM"]["verdict"].startswith("대량·무관")
    hal, sock = (re.compile(data["ril"]["draft_layers"][t]) for t in ("VRIL_HAL", "VRIL_SOCK"))
    assert hal.search("req serial=41 name=X").group("serial") == "41" and sock.search("resp token=42").group("token") == "42"
    assert "VRIL_MODEM" not in data["ril"]["draft_layers"]


def test_draft_has_no_free_text_and_scatter_gives_no_draft(run):
    data = json.loads(run("--json"))
    layers = data["ril"]["draft_layers"]
    rows = {r["tag"]: r for r in data["ril"]["tags"]}
    assert "VRIL_FREE" not in layers and "분산" in rows["VRIL_FREE"]["verdict"]       # 줄마다 다른 접두어는 초안을 내지 않는다
    assert "example.com" not in json.dumps(layers) and layers["VRIL_APN"] == r"^apn=\S+ serial=(?P<serial>\d+)"
    assert rows["VRIL_HAL"]["draft_matched"] == 5 and rows["VRIL_HAL"]["draft_coverage"] == 1.0
    assert SENTINEL not in json.dumps(layers)


def test_json_keys_and_shapes_off_by_default(run):
    data = json.loads(run("--json"))
    assert list(data) == ["format", "tags", "slots", "ril", "summary", "shapes"] and data["shapes"] == {}
    assert data["format"]["verdict"].startswith("threadtime(연도 없음")
    shapes = json.loads(run("--json", "--shapes", "^VRIL_MODEM$"))["shapes"]
    assert shapes["VRIL_MODEM"][0][0].startswith("data #") and "0xdeadbeef" not in json.dumps(shapes)
