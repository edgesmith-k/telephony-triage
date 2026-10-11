"""oFono 뼈대 전환 검증 (17-platforms 설계 §5·§7-C, 묶음 3). **형식 가정(placeholder)·합성 로그**만 쓴다.

- `platforms/ofono/journal.py`: 가정 형식 (a) ISO·(b) BSD syslog 해석, 연도·타임존 없는 줄은 `--year`/`--tz`, 해석 못 한 줄 수
- `parse_logcat parse --rules <issue-db-ofono>`: `ofono_reference` 백엔드·태그 카테고리·extractor 이벤트·마스킹
- 형식이 실제로 갈린다: ofono 로그 + android DB, logcat + ofono DB 모두 `file-unparsed`
- `db_regress` ofono 1/1, `triage.py run --offline-db <issue-db-ofono> --platform ofono` 1위 DATA-001·라벨 oFono /
  `--platform android`는 플랫폼 불일치 종료 2
- 다중 프로토콜: `configure`로 받은 짝 규칙(ril·dbus)이 각자 짝을 맺고 `proto`는 ril 아닌 것에만
- 계층(ofono가 android를 import하지 않음), `make_db_skeleton.py --platform ofono` → db_lint 통과, check_boundary
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(SCRIPTS))

from runner import SAMPLE, plugin_root, run, run_json, tmp, variant_db  # noqa: E402

import platforms  # noqa: E402
from common import events, logtime, masking  # noqa: E402
from platforms.ofono import journal  # noqa: E402

LOGS = REPO / "tests" / "fixtures" / "logs" / "ofono"
ISO_LOG = LOGS / "journal-iso.log"
BSD_LOG = LOGS / "syslog-bsd.log"
LOGCAT = REPO / "tests" / "fixtures" / "logs" / "data-disabled.log"
ON = {"name": "android", "enabled": ["android", "ofono"]}
UTC = timezone.utc


def _write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# -- journal.py: 가정 형식 ------------------------------------------------------------------------


def test_format_a_iso():
    lines, stats = journal.read_file(ISO_LOG, 0, None, None)
    assert (stats.lines, stats.unparsed, stats.missing_year, stats.missing_zone) == (4, 0, False, False)
    first = lines[0]
    assert first.dt == datetime(2026, 9, 20, 5, 32, 9, 100000, tzinfo=UTC)
    assert (first.pid, first.tid, first.level, first.tag) == (812, None, "I", "ofonod")
    assert first.msg.startswith("src/example.c:example_cb() /modem_0")
    assert [ln.tag for ln in lines] == ["ofonod", "daemon-a", "daemon-a", "ofonod"]
    assert all("dut" not in ln.msg for ln in lines)                     # host 칸은 줄 객체에 없다


def test_format_b_bsd_needs_year_and_tz():
    lines, stats = journal.read_file(BSD_LOG, 0, None, None)
    assert (stats.lines, stats.unparsed, stats.missing_year, stats.missing_zone) == (3, 0, True, True)
    assert lines[0].dt == datetime(logtime.DEFAULT_YEAR, 9, 20, 14, 32, 8, tzinfo=UTC)
    lines, stats = journal.read_file(BSD_LOG, 0, "Asia/Seoul", 2026)
    assert (stats.missing_year, stats.missing_zone, stats.first_month, stats.last_month) == (False, False, 9, 9)
    assert lines[0].dt == datetime(2026, 9, 20, 5, 32, 8, tzinfo=UTC)
    assert lines[2].dt == datetime(2026, 9, 20, 5, 32, 11, 250000, tzinfo=UTC)
    assert [(ln.tag, ln.pid) for ln in lines] == [("ofonod", 812), ("daemon-b", 902), ("daemon-b", 902)]


def test_unparsed_lines_rollover_zone_and_notices(tmp_path):
    path = _write(tmp_path, "mixed.log", [
        "-- Boot 0123456789abcdef --",                                     # journalctl 안내 줄: 건너뜀(세지 않음)
        "Dec 31 23:59:59 dut daemon-a: no pid line",
        "Jan  1 10:00:01 dut daemon-a[7]: after new year",
        "Foo  1 00:00:02 dut daemon-a[7]: bad month",                      # 해석 못 함
        "2026-01-01T00:00:03.123456789Z dut kernel: Linux version 0.0.0-placeholder",
        "2026-01-01T09:00:04 dut daemon-b[8]: no zone, no fraction",
        "2026-02-30T00:00:00Z dut daemon-b[8]: no such date",              # 해석 못 함
        "09-20 14:30:03.000  1234  1244 D DSMGR-0: logcat line",            # 해석 못 함 (다른 플랫폼 형식)
        "free text",                                                       # 해석 못 함
    ])
    lines, stats = journal.read_file(path, 3, "Asia/Seoul", 2025)
    assert (stats.lines, stats.unparsed) == (4, 4)
    assert [ln.line_no for ln in lines] == [2, 3, 5, 6] and {ln.file_index for ln in lines} == {3}
    assert lines[0].pid == 0 and lines[0].dt.year == 2025 and lines[1].dt.year == 2026      # 12월 → 1월 해 넘김
    assert lines[2].dt == datetime(2026, 1, 1, 0, 0, 3, 123456, tzinfo=UTC)                  # Z, 9자리 소수
    assert lines[3].dt == datetime(2026, 1, 1, 0, 0, 4, tzinfo=UTC)                           # 타임존 없음 → tz
    assert journal.epoch_break(lines[2]) and not journal.epoch_break(lines[3])


def test_raw_line_and_find_raw_are_format_specific():
    iso = ISO_LOG.read_text(encoding="utf-8").splitlines()[1]
    bsd = BSD_LOG.read_text(encoding="utf-8").splitlines()[1]
    logcat_line = LOGCAT.read_text(encoding="utf-8").splitlines()[0]
    assert journal.raw_line(iso) and journal.raw_line(bsd)
    assert not journal.raw_line(logcat_line) and not journal.raw_line("데이터 연결이 실패했다")
    assert journal.find_raw(f"근거: {iso}") and journal.find_raw(f"보기 {bsd} 끝")
    assert not journal.find_raw("2026-09-20T14:32:10 에 실패했다") and not journal.find_raw(logcat_line)
    android = platforms.get("android").log
    assert not android.raw_line(iso) and not android.raw_line(bsd)
    spec = platforms.get("ofono")
    assert spec.log.read_file is journal.read_file and spec.log.raw_line is journal.raw_line
    assert spec.log.find_raw is journal.find_raw and spec.log.epoch_break is journal.epoch_break


def test_fixture_logs_are_masked_already():
    for path in (ISO_LOG, BSD_LOG):
        text = path.read_text(encoding="utf-8")
        masker = masking.new_masker(text, ())
        assert "\n".join(masker(line) for line in text.split("\n")) == text, path.name


# -- 파서 전환 --------------------------------------------------------------------------------------


def _parse(log: Path, rules: Path, *extra: str) -> dict:
    proc = run("parse_logcat.py", ["parse", log, "--rules", rules, "--full", "--mask", *extra])
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_parse_with_ofono_db():
    out = _parse(ISO_LOG, variant_db("issue-db-ofono") / "parser-rules")
    assert out["backend"] == {"name": "ofono_reference", "version": "0.0.1"}
    assert out["masked"] is True and out["warnings"] == [] and out["errors"] == []
    lines = [e for e in out["events"] if e["event"] is None]
    assert {e["tag"]: e["category_hint"] for e in lines} == {"ofonod": "common", "daemon-a": "data"}
    assert all(e["source"] == "backend:ofono_reference" and e["ril"] is None for e in lines)
    hits = [e for e in out["events"] if e["event"] == "data_connect_failed"]
    assert len(hits) == 1 and hits[0]["fields"] == {"reason": "PLACEHOLDER_REASON"} and hits[0]["tag"] == "daemon-a"
    assert events.validate_events(out["events"]) == []


@pytest.mark.parametrize("log,rules,backend", [
    (ISO_LOG, SAMPLE / "parser-rules", "reference"),                                   # ofono 로그 → android DB
    (LOGCAT, None, "ofono_reference"),                                                 # logcat → ofono DB
])
def test_cross_format_is_file_unparsed(log, rules, backend):
    rules = rules or variant_db("issue-db-ofono") / "parser-rules"
    out = _parse(log, rules, "--tz", "UTC", "--year", "2026")
    assert out["backend"]["name"] == backend
    assert "file-unparsed" in {w["code"] for w in out["warnings"]}
    assert [e for e in out["events"] if e["event"] is None] == []


def test_db_regress_ofono():
    result = run_json("db_regress.py", ["--db", variant_db("issue-db-ofono"), "--all"])
    assert (result["summary"]["total"], result["summary"]["passed"]) == (1, 1)
    assert result["results"][0]["C"] == ["DATA-001-01"]


def test_triage_offline_switches_platform():
    root = plugin_root("ofono-on", platform=ON)
    work = tmp("tt-ofono-triage-")
    meta = work / "meta.json"
    meta.write_text(json.dumps({"key": "MOCK-9001", "occurred_at": "2026-09-20T05:32:10Z", "summary": "x",
                                "android_version": "3"}), encoding="utf-8")
    base = ["run", "MOCK-9001", "--offline-db", variant_db("issue-db-ofono"), "--logs", ISO_LOG, "--jira-meta", meta]
    env = {"TELEPHONY_TRIAGE_HOME": work / "home"}
    result = run_json("triage.py", [*base, "--out", work / "job", "--platform", "ofono"], root=root, env=env)
    assert result["platform"] == "ofono" and result["candidates"][0]["type"] == "DATA-001"
    analysis = json.loads((work / "job" / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["platform"] == "ofono" and analysis["candidates"][0]["cause"] == "DATA-001-01"
    report = (work / "job" / "report.md").read_text(encoding="utf-8")
    assert "다른 버전 원인 (oFono 2)" in report and "Android" not in report
    proc = run("triage.py", [*base, "--out", work / "job2", "--platform", "android"], root=root, env=env)
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr
    assert not (work / "job2" / "analysis.json").exists()


# -- 다중 프로토콜 -------------------------------------------------------------------------------------


def _fake_dbus_annotate(tag, msg, tags, phone):
    if tag not in tags:
        return None
    kind, serial, name = msg.split()
    return {"serial": int(serial), "dir": "req" if kind == "call" else "resp", "request": name,
            "error": None if kind == "call" else "NONE", "paired_ts": None, "latency_ms": None}


def _fake_dbus_pair(records):
    pending = {}
    for rec in records:
        ann = rec.get("ril")
        if not ann or ann.get("proto") != "dbus":                         # 자기 주석만
            continue
        if ann["dir"] == "req":
            pending[ann["serial"]] = rec
        elif ann["serial"] in pending:
            req = pending.pop(ann["serial"])
            latency = round((rec["_dt"] - req["_dt"]).total_seconds() * 1000)
            req["ril"].update(paired_ts=rec["ts"], latency_ms=latency)
            ann.update(paired_ts=req["ts"], latency_ms=latency)


def test_multi_protocol_pairs_independently(tmp_path):
    from platforms.android import ril                                     # 테스트만 android 짝 규칙을 빌려 쓴다
    from platforms.ofono.backend import BACKEND

    log = _write(tmp_path, "multi.log", [
        "2026-09-20T05:00:00.000Z dut RILJ[100]: [1]> SETUP_DATA_CALL",
        "2026-09-20T05:00:00.100Z dut dbus-mon[200]: call 1 Activate",     # 다른 pid·같은 serial
        "2026-09-20T05:00:00.300Z dut dbus-mon[200]: reply 1 Activate",
        "2026-09-20T05:00:00.500Z dut RILJ[100]: [1]< SETUP_DATA_CALL",
        "2026-09-20T05:00:00.600Z dut daemon-a[300]: unrelated",
    ])
    spec = platforms.get("ofono")
    protocols = (
        platforms.PairProtocol(name="ril", default_tags=frozenset({"RILJ"}), annotate=ril.parse, pair=ril.pair),
        platforms.PairProtocol(name="dbus", default_tags=frozenset({"dbus-mon"}), annotate=_fake_dbus_annotate,
                               pair=_fake_dbus_pair),
    )
    profile = platforms.PlatformProfile(
        name="ofono", source_tree=spec.source_tree, phone=spec.phone, ril_tags=frozenset({"RILJ"}), bugreport=None,
        spec=dataclasses.replace(spec, protocols=protocols),
        protocol_tags=(("ril", frozenset({"RILJ"})), ("dbus", frozenset({"dbus-mon"}))))
    out = BACKEND.configure(profile).parse([log], None, None, None)
    ann = [e["ril"] for e in out]
    assert "proto" not in ann[0] and "proto" not in ann[3] and ann[4] is None
    assert ann[1]["proto"] == ann[2]["proto"] == "dbus"
    assert (ann[0]["paired_ts"], ann[0]["latency_ms"], ann[3]["latency_ms"]) == ("2026-09-20T05:00:00.500Z", 500, 500)
    assert (ann[1]["paired_ts"], ann[1]["latency_ms"], ann[2]["latency_ms"]) == ("2026-09-20T05:00:00.300Z", 200, 200)
    assert "observed_until" not in ann[0]                                  # dbus 줄이 ril pid 분할을 일으키지 않았다
    assert events.validate_events(out) == []
    # 원본(싱글톤)은 바뀌지 않는다: 짝 규칙 없음
    assert all(e["ril"] is None for e in BACKEND.parse([log], None, None, None))


def test_event_validator_accepts_proto_key_order():
    base = {"serial": 1, "dir": "req", "request": "X", "error": None, "paired_ts": None, "latency_ms": None}
    def check(ann):
        return events.validate_event(events.make_event(ts="2026-09-20T05:00:00.000Z", source="backend:x", ril=ann))
    assert check({**base, "proto": "dbus"}) == [] and check({**base, "proto": "dbus", "observed_until": "t"}) == []
    assert check({**base, "observed_until": "t", "proto": "dbus"}) != []


# -- 계층·백엔드 등록 ----------------------------------------------------------------------------------


def test_ofono_does_not_import_android():
    sys.path.insert(0, str(REPO / "tests"))
    from test_platforms import _imports                                    # 같은 import 스캐너

    files = [*(SCRIPTS / "platforms" / "ofono").rglob("*.py"), *(SCRIPTS / "parser_backends" / "ofono_reference").rglob("*.py")]
    assert len(files) >= 4
    for path in files:
        rel = path.relative_to(SCRIPTS).as_posix()
        assert not {m for m in _imports(path, rel) if m == "platforms.android" or m.startswith("platforms.android.")}, rel


def test_backend_registration():
    import parser_backends
    from platforms.ofono import backend

    loaded = parser_backends.load("ofono_reference")
    assert loaded is backend.BACKEND and loaded.platform == "ofono" and loaded.name == "ofono_reference"
    assert loaded.version() == backend.VERSION == "0.0.1" and loaded.builtin_events() == []
    assert loaded.log_format() is platforms.get("ofono").log


# -- 뼈대 DB·경계 ------------------------------------------------------------------------------------


def test_make_db_skeleton_platform_ofono_passes_lint():
    out = tmp("tt-ofono-skel-") / "db"
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out), "--platform", "ofono",
                           "--json"], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["platform"] == "ofono"
    cfg = (out / "issue-db.config.yaml").read_text(encoding="utf-8")
    assert "platform: ofono" in cfg and "name: ofono_reference" in cfg and "code_root_keys: [ofono]" in cfg
    assert "DNC-" not in (out / "parser-rules" / "tags.yaml").read_text(encoding="utf-8")
    lint = run_json("db_lint.py", ["--db", out, "--all"])
    assert lint["summary"]["errors"] == 0 and lint["summary"]["warnings"] == 0
    bad = subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out.parent / "x"),
                          "--platform", "nosuch"], capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode != 0 and "지원 플랫폼" in bad.stderr


def test_check_boundary_external():
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "check_boundary.py"), "--mode", "external"],
                          capture_output=True, text=True, encoding="utf-8", cwd=REPO)
    assert proc.returncode == 0, proc.stdout + proc.stderr
