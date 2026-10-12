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
                                "platform_version": "3"}), encoding="utf-8")
    base = ["run", "MOCK-9001", "--offline-db", variant_db("issue-db-ofono"), "--logs", ISO_LOG, "--issue-meta", meta]
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


# -- 리뷰 3 반영: 오프셋 이상값·오탐/미탐·guard·issue_post -----------------------------------------------


def test_bad_zone_offsets_are_unparsed(tmp_path):
    path = _write(tmp_path, "zone.log", [
        "2026-09-20T14:32:09+24:00 dut daemon-a[1]: offset 24h",          # 해석 못 함 (예외로 멈추지 않는다)
        "2026-09-20T14:32:09+09:75 dut daemon-a[1]: offset 75 min",       # 해석 못 함
        "2026-09-20T14:32:09+0900 dut daemon-a[1]: no colon",
        "2026-09-20T14:32:09-03:30 dut daemon-a[1]: negative",
    ])
    lines, stats = journal.read_file(path, 0, "America/New_York", None)   # 줄의 오프셋이 --tz보다 우선
    assert (stats.lines, stats.unparsed) == (2, 2)
    assert lines[0].dt == datetime(2026, 9, 20, 5, 32, 9, tzinfo=UTC)
    assert lines[1].dt == datetime(2026, 9, 20, 18, 2, 9, tzinfo=UTC)


RAW_LINES = [
    "2026-09-20T14:32:09.100000+09:00 dut ofonod[812]: src/example.c:example_cb() /modem_0 x",
    "2026-09-20T14:32:09Z dut kernel: Linux version 0.0.0-placeholder",
    "Sep 20 14:32:11 dut daemon-b[902]: call setup failed: cause=PLACEHOLDER",
    "Sep  2 04:00:00 dut-01.lab systemd[1]: Started placeholder.",
    "Sep 20 14:32:11 dut kernel: [  12.3] placeholder",
]
SENTENCES = [
    "Sep 20 14:32:11 단말 재부팅: 확인됨",
    "2026-09-20T14:32:09 단말 상태: 정상",
    "2026-09-20T14:32:09+09:00 기준 modem 상태: OOS",
    "Sep 20 14:32:11 에 data connect 실패",
    "14:32:11 data connect failed",
    "Sept 20 14:32:11 a b: c",
]


@pytest.mark.parametrize("line", RAW_LINES)
def test_raw_line_detects_assumed_formats(line):
    assert journal.raw_line(line) and journal.find_raw(f"근거: {line}")


@pytest.mark.parametrize("text", SENTENCES)
def test_plain_sentences_are_not_raw(text):
    assert not journal.raw_line(text) and not journal.find_raw(f"원인은 {text}")
    assert not journal.find_raw("원인은 Oct 10 09:00:00 회의 결과: 미정")


def _guard(path: Path):
    import guard

    out, _ = guard.judge({"tool_name": "Bash", "tool_input": {"command": f"cat {path}"}, "cwd": str(path.parent)},
                         str(REPO / "plugin"))
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")


def test_guard_rule10_journald_vs_sentences(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path / "home"))
    for i, line in enumerate(RAW_LINES):
        assert _guard(_write(tmp_path, f"raw{i}.txt", ["메모", line])) == "deny", line
    assert _guard(_write(tmp_path, "notes.txt", SENTENCES)) is None


def test_issue_post_fill_journald_vs_sentences():
    import issue_post

    def problems(text):
        masker = masking.new_masker(existing_text="", allow_patterns=[])
        raw = {"problem": "증상 한 줄", "cause": [{"basis": "log", "text": text}], "next": [], "code_location": None}
        return [p for p in issue_post.check_fill(raw, True, True, masker, [], None)[1] if "로그 원문 줄 모양" in p]

    for line in RAW_LINES:
        assert problems("근거 " + line), line
    for text in SENTENCES:
        assert not problems(text), text


# -- 백엔드: 커널 배너 에포크·회전 파일 잇기 --------------------------------------------------------------


def _dbus_backend():
    from platforms.ofono.backend import BACKEND

    spec = platforms.get("ofono")
    proto = platforms.PairProtocol(name="dbus", default_tags=frozenset({"dbus-mon"}), annotate=_fake_dbus_annotate,
                                   pair=_fake_dbus_pair)
    profile = platforms.PlatformProfile(name="ofono", source_tree=spec.source_tree, phone=spec.phone,
                                        ril_tags=frozenset(), bugreport=None,
                                        spec=dataclasses.replace(spec, protocols=(proto,)),
                                        protocol_tags=(("dbus", frozenset({"dbus-mon"})),))
    return BACKEND.configure(profile)


def _paired(out) -> list:
    return [e["ril"]["latency_ms"] for e in out if e["ril"]]


def test_kernel_banner_splits_epoch(tmp_path):
    call = "2026-09-20T05:00:00.000Z dut dbus-mon[200]: call 1 Activate"
    reply = "2026-09-20T05:00:00.500Z dut dbus-mon[200]: reply 1 Activate"
    banner = "2026-09-20T05:00:00.200Z dut kernel: Linux version 0.0.0-placeholder"
    backend = _dbus_backend()
    assert _paired(backend.parse([_write(tmp_path, "a.log", [call, reply])], None, None, None)) == [500, 500]
    out = backend.parse([_write(tmp_path, "b.log", [call, banner, reply])], None, None, None)
    assert _paired(out) == [None, None] and len(out) == 3                  # 재부팅 너머로 짝짓지 않는다


def test_rotated_files_are_joined(tmp_path):
    call = "2026-09-20T05:00:00.000Z dut dbus-mon[200]: call 1 Activate"
    reply = "2026-09-20T05:00:00.500Z dut dbus-mon[200]: reply 1 Activate"
    backend = _dbus_backend()
    rot = tmp_path / "rot"
    rot.mkdir()
    older, newer = _write(rot, "syslog.1", [call]), _write(rot, "syslog", [reply])
    assert _paired(backend.parse([newer, older], None, None, None)) == [500, 500]     # 같은 수집(회전 이름)은 잇는다
    other = tmp_path / "other"
    other.mkdir()
    a, b = _write(other, "first.log", [call]), _write(other, "second.log", [reply])
    assert _paired(backend.parse([a, b], None, None, None)) == [None, None]           # 다른 수집은 잇지 않는다


# -- 리뷰 3 반영: DB를 읽는 스크립트의 플랫폼 선택·대조 ---------------------------------------------------

NINE = {"triage", "config", "db_pr", "db_verify", "issue_post", "code_roots", "db_add", "db_search", "db_review",
        "job_status"}      # 이름은 그대로(9개 시절), job_status(읽기 전용 상태 화면) 포함 10개


def test_platform_option_scripts():
    """`--platform`을 받는 스크립트는 이 10개다. 스킬·커맨드 본문에서 `S/<script>.py … --platform`으로 나오는 스크립트는
    그 부분집합이어야 한다(문서가 실제로 없는 옵션을 붙이라고 하지 않게)."""
    import re

    have = {p.stem for p in SCRIPTS.glob("*.py")
            if re.search(r'"--platform"|session\.add_arg\(', p.read_text(encoding="utf-8"))}
    assert have == NINE
    docs = [*(REPO / "plugin" / "skills").rglob("*.md"), *(REPO / "plugin" / "commands").rglob("*.md")]
    named = {m.group(1) for d in docs for line in d.read_text(encoding="utf-8").splitlines() if "--platform" in line
             for m in re.finditer(r"S/([a-z_]+)\.py", line)}
    assert named <= NINE, named - NINE


def test_issue_db_path_follows_selected_platform(tmp_path, monkeypatch):
    from common import userconfig

    assert userconfig.PLATFORM_ENV == platforms.ENV
    monkeypatch.setenv(userconfig.HOME_ENV, str(tmp_path / "home"))
    monkeypatch.delenv(platforms.ENV, raising=False)
    user = {"issue_db": {"path": "/a"}, "platforms": {"ofono": {"issue_db": {"path": "/o"}}}}
    userconfig.save(user)
    assert userconfig.issue_db_path({}) == "/a"
    assert userconfig.issue_db_path({"platform": {"name": "ofono"}}) == "/o"            # site 기본
    monkeypatch.setenv(platforms.ENV, "ofono")
    assert userconfig.issue_db_path({}) == "/o"                                          # TT_PLATFORM
    assert userconfig.issue_db_path({}, "android") == "/a"                               # 명시가 우선
    monkeypatch.delenv(platforms.ENV)
    userconfig.save({**user, "platform": "ofono"})
    assert userconfig.issue_db_path({}) == "/o"                                          # 사용자 config platform


def _db_cmds(db) -> list[tuple[str, list]]:
    return [("db_search.py", ["DATA-001", "--db", db]), ("db_review.py", ["--db", db, "--json"]),
            ("db_add.py", ["similar", "데이터", "--db", db])]


def test_db_reading_scripts_check_platform():
    on = plugin_root("ofono-on", platform=ON)
    env = {"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")}
    ofono_db = variant_db("issue-db-ofono")
    for script, args in _db_cmds(ofono_db):
        proc = run(script, args, env=env)                                   # 선택 android(기본) ↔ DB ofono
        assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr, (script, proc.stderr)
        ok = run(script, [*args, "--platform", "ofono"], root=on, env=env)
        assert ok.returncode == 0, (script, ok.stderr)
        envd = run(script, args, root=on, env={**env, platforms.ENV: "ofono"})
        assert envd.returncode == 0, (script, envd.stderr)
    for script, args in _db_cmds(SAMPLE):
        proc = run(script, [*args, "--platform", "ofono"], root=on, env=env)
        assert proc.returncode == 2 and "이슈 DB는 android, 선택한 플랫폼은 ofono" in proc.stderr, script
        assert run(script, args, env=env).returncode == 0, script        # android 그대로


def test_db_add_db_fixed_subcommands_follow_db():
    """apply·drift·renumber·check-ids는 DB 고정: 선택 플랫폼과 무관하게 DB 선언을 따르고 --platform·TT_PLATFORM이 있을 때만 대조."""
    env = {"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")}
    ofono_db = variant_db("issue-db-ofono")
    assert run("db_add.py", ["check-ids", "--db", ofono_db], env=env).returncode == 0
    proc = run("db_add.py", ["check-ids", "--db", ofono_db, "--platform", "android"], env=env)
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr
    proc = run("db_add.py", ["check-ids", "--db", SAMPLE], env={**env, platforms.ENV: "ofono"})
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr


def test_db_search_fallback_uses_selected_profile():
    """`--db` 없이(cwd가 이슈 DB 아님) 사용자 config `platform: ofono`면 ofono 프로필의 DB를 읽는다(android DB를 조용히 읽지 않는다)."""
    import yaml

    on = plugin_root("ofono-on", platform=ON)
    home = tmp("tt-home-")
    work = tmp("tt-cwd-")
    ofono_db = variant_db("issue-db-ofono")
    cfg = {"issue_db": {"path": str(SAMPLE)}, "platform": "ofono",
           "platforms": {"ofono": {"issue_db": {"path": str(ofono_db)}, "work_dir": str(home / "work-ofono")}}}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    result = run_json("db_search.py", ["DATA-001"], root=on, env={"TELEPHONY_TRIAGE_HOME": home}, cwd=work)
    assert result["db"] == str(ofono_db)
    result = run_json("db_search.py", ["DATA-001", "--platform", "android"], root=on,
                      env={"TELEPHONY_TRIAGE_HOME": home}, cwd=work)
    assert result["db"] == str(SAMPLE)
