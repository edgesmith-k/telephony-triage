#!/usr/bin/env python3
"""Phase 2 완료 기준 확인: logcat 파서 엔진 (11-phases.md Phase 2).

확인하는 것
- fixture별 이벤트 JSON 스냅샷 (`tests/fixtures/logs/<name>.events.json`)
- 연도 없는 threadtime + `--tz`/`--year` → UTC, 형식 변형(연도·uid·zone·time)
- 듀얼 SIM `phone_id`(태그 접미사·메시지 접두어, 없으면 null)
- 같은 serial을 두 슬롯이 쓰는 로그의 슬롯별 RIL 페어링, 지연·무응답·에러, pid 키
- `coverage.window_in_range`(true/partial/false), `clock_anomalies`
- `extract-bugreport`(zip·txt): logcat 섹션만, dumpsys 문자열 없음, build.json fingerprint
- `parser-rules/`만 바꿔도 결과가 바뀜, 규칙 스키마 검증, builtin./ext. 접두어 거부
- 모의 site 백엔드: `builtin.data.*`가 extractor 이벤트와 함께(source 구분)
- 백엔드·외부 파서 불일치 경고, 외부 파서(어댑터) 실행과 `${CLAUDE_PLUGIN_ROOT}` 치환, `--no-external`
- `sanitize_build`(`A..B`, `X.lock`, 끝 `.`)와 브랜치 이름 검사
- 마스킹 자리가 extractor보다 앞 (`--mask`·`cut` 자체는 `tests/test_masking.py`)
- `site-defaults.yaml` 없으면 종료 코드 2
- 벤더 RIL 층 연결(`platform.ril.vendor`): `hal` 4값·창·coverage_tags·RILJ 짝 유지(설정 없으면 필드 없음)

스냅샷 갱신: `python3 tests/test_parse_logcat.py --update`
`pytest tests/test_parse_logcat.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "tests" / "mocks"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import logcat_gen  # noqa: E402
from common import events  # noqa: E402
import make_log_fixtures  # noqa: E402
import make_plugin_root  # noqa: E402
import mock_env  # noqa: E402

LOG_DIR = REPO / "tests" / "fixtures" / "logs"
SAMPLE_DB = REPO / "tests" / "fixtures" / "issue-db-sample"
RULES = SAMPLE_DB / "parser-rules"
SCENARIOS = REPO / "tests" / "mocks" / "scenarios"
TZ, YEAR = "Asia/Seoul", "2026"

_ROOTS: dict[str, Path] = {}


def _root(kind: str = "plain") -> Path:
    """임시 플러그인 루트 (plain: reference 백엔드 / site: 모의 site 백엔드)."""
    if kind not in _ROOTS or not _ROOTS[kind].is_dir():
        root = make_plugin_root.make(with_site_backend=(kind == "site"))
        if kind == "site":
            _set_defaults(root, parser={"backend": "site"})
        _ROOTS[kind] = root
    return _ROOTS[kind]


def _set_defaults(root: Path, **updates) -> None:
    path = root / "site-defaults.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(updates)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _run(args: list[str], root: Path | None = None) -> tuple[int, dict | None, str]:
    root = root or _root()
    env = mock_env.env_with_mocks(plugin_root=root)
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "parse_logcat.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    data = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else None
    return proc.returncode, data, proc.stderr


def _parse(logs, *extra, rules: Path = RULES, root: Path | None = None, tz=TZ, year=YEAR):
    args = ["parse", *[str(p) for p in logs], "--rules", str(rules)]
    if tz:
        args += ["--tz", tz]
    if year:
        args += ["--year", str(year)]
    args += list(extra) or ["--full"]
    code, data, err = _run(args, root)
    assert code == 0, f"parse 실패({code}): {err}"
    return data


def _snapshot_view(data: dict) -> dict:
    return {"coverage": data["coverage"], "warnings": data["warnings"], "events": data["events"]}


def _events(data, **match):
    return [e for e in data["events"] if all(e.get(k) == v for k, v in match.items())]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="tt-parse-"))


def _copy_db(dest: Path) -> Path:
    """규칙·스키마·설정만 담은 이슈 DB 복사본 (규칙 변경 시험용)."""
    db = dest / "db"
    shutil.copytree(RULES, db / "parser-rules")
    shutil.copytree(SAMPLE_DB / "schema", db / "schema")
    shutil.copyfile(SAMPLE_DB / "issue-db.config.yaml", db / "issue-db.config.yaml")
    return db


# -- fixture와 스냅샷 -------------------------------------------------------


def test_log_fixtures_match_scenarios():
    result = make_log_fixtures.run(check=True)
    assert not result["missing"] and not result["mismatched"], result


def _fixture_names() -> list[str]:
    return [entry["name"] for entry in make_log_fixtures.load_table()]


def test_event_snapshots():
    for name in _fixture_names():
        data = _parse([LOG_DIR / f"{name}.log"])
        snap = LOG_DIR / f"{name}.events.json"
        assert snap.exists(), f"{snap.name} 없음 — python3 tests/test_parse_logcat.py --update"
        expected = json.loads(snap.read_text(encoding="utf-8"))
        assert _snapshot_view(data) == expected, f"{name}: 이벤트가 스냅샷과 다릅니다."
        assert events.validate_events(data["events"]) == [], name
        assert data["schema"] == events.SCHEMA_VERSION


def update_snapshots() -> list[Path]:
    written = []
    for name in _fixture_names():
        data = _parse([LOG_DIR / f"{name}.log"])
        path = LOG_DIR / f"{name}.events.json"
        path.write_text(
            json.dumps(_snapshot_view(data), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written.append(path)
    return written


# -- 시각 ------------------------------------------------------------------


def test_threadtime_without_year_converts_to_utc():
    data = _parse([LOG_DIR / "data-disabled.log"])
    first = data["events"][0]
    # 시나리오 시작 2026-09-20T14:30:00+09:00 (파일에는 연도·타임존이 없다)
    assert first["ts"] == "2026-09-20T05:30:00.000Z"
    assert data["coverage"]["first_ts"] == "2026-09-20T05:30:00.000Z"
    assert data["warnings"] == []

    # --tz 없음 → UTC로 해석하고 경고, --year 없음 → 고정 연도와 경고
    data = _parse([LOG_DIR / "data-disabled.log"], tz=None, year=None)
    codes = {w["code"] for w in data["warnings"]}
    assert {"tz_assumed_utc", "year_assumed"} <= codes
    assert data["events"][0]["ts"] == "2000-09-20T14:30:00.000Z"


def test_format_variants():
    tmp = _tmp()
    variants = {
        "year": "2026-09-20 14:30:00.123  1234  1244 D RILJ: [PHONE0] [0001]> DIAL\n",
        "uid": "09-20 14:30:00.123  radio  1234  1244 D RILJ: [PHONE0] [0001]> DIAL\n",
        "zone": "09-20 14:30:00.123 +0000  1234  1244 D RILJ: [PHONE0] [0001]> DIAL\n",
        "time": "09-20 14:30:00.123 D/RILJ( 1234): [PHONE0] [0001]> DIAL\n",
    }
    for name, line in variants.items():
        path = tmp / f"{name}.log"
        path.write_text("--------- beginning of radio\n" + line, encoding="utf-8", newline="\n")
        data = _parse([path])
        (event,) = data["events"]
        expected = "2026-09-20T14:30:00.123Z" if name == "zone" else "2026-09-20T05:30:00.123Z"
        assert event["ts"] == expected, (name, event["ts"])
        assert event["pid"] == 1234 and event["tag"] == "RILJ" and event["phone_id"] == 0, name
        assert event["ril"]["request"] == "DIAL" and event["ril"]["dir"] == "req", name
        assert event["tid"] == (None if name == "time" else 1244), name

    # 연도 없는 로그의 12월 → 1월 넘김
    path = tmp / "newyear.log"
    path.write_text(
        "12-31 23:59:59.000  1234  1244 D RILJ: a\n01-01 00:00:01.000  1234  1244 D RILJ: b\n",
        encoding="utf-8",
        newline="\n",
    )
    data = _parse([path], tz="UTC", year=2026)
    assert [e["ts"] for e in data["events"]] == [
        "2026-12-31T23:59:59.000Z",
        "2027-01-01T00:00:01.000Z",
    ]
    assert data["coverage"]["clock_anomalies"] == []


# -- 슬롯과 RIL ---------------------------------------------------------------


def test_phone_id_per_slot():
    data = _parse([LOG_DIR / "dual-sim-cross-slot.log"])
    lines = [e for e in data["events"] if e["event"] is None]
    by_tag = {}
    for e in lines:
        by_tag.setdefault(e["tag"], set()).add(e["phone_id"])
    assert by_tag["DNC-0"] == {0} and by_tag["DSMGR-1"] == {1} and by_tag["DSMGR-0"] == {0}
    assert {e["phone_id"] for e in lines if e["tag"] == "RILJ"} == {0}  # 메시지 접두어

    data = _parse([LOG_DIR / "dual-sim-ril.log"])
    (uicc,) = _events(data, tag="UiccController", event=None)
    assert uicc["phone_id"] is None  # 접미사·접두어 없는 태그


def test_phone_id_data_service_tag_and_ril_suffix():
    # DSM-C-<n>(DataServiceManager)은 슬롯이 뒤에 오고, DN-<id>-C는 슬롯이 아니다.
    path = _tmp() / "phone-tags.log"
    path.write_text(
        "09-20 14:30:00.000  1234  1244 D DSM-C-0: x\n"
        "09-20 14:30:00.100  1234  1244 D DN-17-C: y\n"
        "09-20 14:30:00.200  1234  1244 D RILJ: [0041]> SETUP_DATA_CALL apn=default [PHONE1]\n",
        encoding="utf-8", newline="\n")
    data = _parse([path])
    by_tag = {e["tag"]: e["phone_id"] for e in data["events"] if e["event"] is None}
    assert by_tag["DSM-C-0"] == 0 and by_tag["DN-17-C"] is None and by_tag["RILJ"] == 1


def test_ril_pairing_same_serial_two_slots():
    data = _parse([LOG_DIR / "dual-sim-ril.log"])
    reqs = {e["phone_id"]: e for e in data["events"]
            if e["event"] is None and e["ril"] and e["ril"]["dir"] == "req" and e["ril"]["serial"] == 41}
    resps = {e["phone_id"]: e for e in data["events"]
             if e["event"] is None and e["ril"] and e["ril"]["dir"] == "resp" and e["ril"]["serial"] == 41}
    assert set(reqs) == {0, 1} and set(resps) == {0, 1}
    for slot in (0, 1):
        assert reqs[slot]["ril"]["paired_ts"] == resps[slot]["ts"]
        assert resps[slot]["ril"]["paired_ts"] == reqs[slot]["ts"]
    assert resps[1]["ril"]["error"] == "INSUFFICIENT_RESOURCES"
    assert resps[0]["ril"]["error"] == "NONE"

    (err,) = _events(data, event="ril_error")
    assert err["phone_id"] == 1 and err["fields"]["error"] == "INSUFFICIENT_RESOURCES"
    (slow,) = _events(data, event="ril_timeout")
    assert slow["fields"] == {"request": "DEACTIVATE_DATA_CALL", "serial": "42",
                              "latency_ms": "12000", "timeout_ms": "10000"}
    (none,) = _events(data, event="ril_no_response")
    assert none["fields"]["request"] == "SEND_SMS" and none["phone_id"] == 1
    # 다른 pid의 같은 serial 응답은 짝지어지지 않는다
    (late,) = [e for e in data["events"]
               if e["event"] is None and e["ril"] and e["ril"]["serial"] == 43 and e["ril"]["dir"] == "resp"]
    assert late["pid"] == 2345 and late["ril"]["paired_ts"] is None
    assert all(e["source"] == "rules" for e in data["events"] if e["event"])


def test_no_response_needs_enough_log_after_request():
    tmp = _tmp()
    path = tmp / "short.log"
    path.write_text(
        "09-22 12:00:00.000  1234  1244 D RILJ: [PHONE0] [0043]> SEND_SMS\n"
        "09-22 12:00:05.000  1234  1244 D RILJ: [PHONE0] [UNSL]< UNSOL_RESPONSE_NEW_SMS\n",
        encoding="utf-8",
        newline="\n",
    )
    data = _parse([path])
    assert not _events(data, event="ril_no_response"), "파일이 timeout 전에 끝나면 응답 없음이 아니다"


# -- 벤더 RIL 층 연결 (선택 platform.ril.vendor, 04 §5.8 (2)) ---------------------
# placeholder 태그 VRIL_HAL·VRIL_SOCK·VRIL_MODEM과 합성 문구만 쓴다.

VENDOR = {"layers": [{"tag": "VRIL_HAL", "patterns": [r"^req serial=(?P<serial>\d+)(?: name=(?P<request>\w+))?"]},
                     {"tag": "VRIL_SOCK", "patterns": [r"^resp token=(?P<token>\d+)"]}]}
REQ41 = (0, 1234, "RILJ", "[PHONE0] [0041]> SETUP_DATA_CALL")
ERR41 = (0.5, 1234, "RILJ", "[PHONE0] [0041]< SETUP_DATA_CALL error=INSUFFICIENT_RESOURCES")
HAL41 = (0.005, 900, "VRIL_HAL", "req serial=41 name=SETUP_DATA_CALL")
_VROOTS: dict[str, Path] = {}


def _vendor_parse(rows, vendor=VENDOR) -> dict:
    """rows: (초, pid, 태그, 메시지). 40초 뒤 꼬리 줄을 붙여 응답 없음(timeout 30s)을 판정할 수 있게 한다."""
    key = json.dumps(vendor, sort_keys=True)
    if key not in _VROOTS:
        root = make_plugin_root.make()
        if vendor is not None:
            _set_defaults(root, platform={"name": "android", "ril": {"vendor": vendor}})
        _VROOTS[key] = root
    base = datetime(2026, 9, 22, 12, 5)
    lines = []
    for t, pid, tag, msg in sorted([*rows, (40, 1234, "Foo", "tail")], key=lambda r: r[0]):
        at = base + timedelta(seconds=t)
        lines.append(f"{at:%m-%d %H:%M:%S}.{at.microsecond // 1000:03d}  {pid}  {pid} D {tag}: {msg}\n")
    path = _tmp() / "v.log"
    path.write_text("".join(lines), encoding="utf-8", newline="\n")
    return _parse([path], root=_VROOTS[key])


def _hal(data, event: str):
    (e,) = _events(data, event=event)
    return e["fields"].get("hal")


def test_vendor_hal_reached_not_reached_unknown():
    assert _hal(_vendor_parse([REQ41, HAL41]), "ril_no_response") == "reached"
    other = (0.003, 900, "VRIL_HAL", "req serial=40 name=DIAL")
    assert _hal(_vendor_parse([REQ41, other]), "ril_no_response") == "not_reached"
    data = _vendor_parse([REQ41])
    assert _hal(data, "ril_no_response") == "unknown"
    (req,) = [e for e in data["events"] if e["event"] is None and e["ril"]]
    assert list(req["ril"])[-2:] == ["observed_until", "hal"] and events.validate_events(data["events"]) == []


def test_vendor_hal_link_window():
    late = (2.5, 900, "VRIL_HAL", "req serial=41")         # link_ms 2000 밖
    early = (-0.4, 900, "VRIL_HAL", "req serial=41")       # 앞 500ms 안
    assert _hal(_vendor_parse([REQ41, late]), "ril_no_response") == "not_reached"
    assert _hal(_vendor_parse([REQ41, early]), "ril_no_response") == "reached"


def test_vendor_token_without_rilj_response_is_responded():
    """소켓 층 응답 토큰은 있는데 RILJ 응답이 없다 → AP 쪽 유실 근거."""
    tok = (0.4, 900, "VRIL_SOCK", "resp token=41")
    assert _hal(_vendor_parse([REQ41, HAL41, tok]), "ril_no_response") == "responded"


def test_vendor_token_after_rilj_response_within_1s():
    in_1s = (1.2, 900, "VRIL_SOCK", "resp token=41")       # RILJ 응답(0.5s) + 0.7s
    past = (1.6, 900, "VRIL_SOCK", "resp token=41")        # + 1.1s
    data = _vendor_parse([REQ41, HAL41, ERR41, in_1s])
    assert _hal(data, "ril_error") == "responded"
    req, resp = [e for e in data["events"] if e["event"] is None and e["ril"]]
    assert req["ril"]["hal"] == resp["ril"]["hal"] == "responded"
    assert _hal(_vendor_parse([REQ41, HAL41, ERR41, past]), "ril_error") == "reached"


def test_vendor_non_decimal_group_value_is_ignored():
    """단어 문자 token 그룹에 `0x29` 같은 값이 와도 parse가 죽지 않고 그 줄만 무시한다."""
    vendor = {"layers": [*VENDOR["layers"][:1], {"tag": "VRIL_SOCK", "patterns": [r"^resp token=(?P<token>\w+)"]}]}
    rows = [REQ41, HAL41, (0.3, 900, "VRIL_SOCK", "resp token=0x29"), (0.4, 900, "VRIL_SOCK", "resp token=٤١")]
    assert _hal(_vendor_parse(rows, vendor), "ril_no_response") == "reached"


def test_vendor_paired_hal_window_extends_to_response():
    """짝 있는 요청은 HAL 창 끝이 max(t + link_ms, 응답 + 1s) — 늦은 HAL 줄도 응답 전이면 reached."""
    late_hal = (3.0, 900, "VRIL_HAL", "req serial=41")
    late_err = (3.5, 1234, "RILJ", "[PHONE0] [0041]< SETUP_DATA_CALL error=INSUFFICIENT_RESOURCES")
    assert _hal(_vendor_parse([REQ41, late_hal, late_err]), "ril_error") == "reached"
    assert _hal(_vendor_parse([REQ41, late_hal]), "ril_no_response") == "not_reached"   # 짝 없으면 link_ms 그대로


def test_vendor_lines_do_not_split_rilj_pairing():
    """벤더 줄(다른 pid)이 요청·응답 사이에 있어도 RILJ 짝이 유지된다(pid 분할 회귀 방지)."""
    data = _vendor_parse([REQ41, HAL41, (0.2, 900, "VRIL_SOCK", "resp token=41"), ERR41])
    req, resp = [e for e in data["events"] if e["event"] is None and e["ril"]]
    assert req["ril"]["latency_ms"] == 500 and resp["ril"]["paired_ts"] == req["ts"]
    assert all(e["ril"] is None for e in data["events"] if e["tag"].startswith("VRIL_"))
    assert _events(data, event="ril_error") and not _events(data, event="ril_no_response")


def test_vendor_unconfigured_modem_lines_change_nothing():
    modem = [(-60 + i * 0.008, 901, "VRIL_MODEM", f"frame {i}") for i in range(12000)]
    base = _vendor_parse([REQ41])
    data = _vendor_parse([REQ41, *modem])
    assert _hal(data, "ril_no_response") == "unknown"
    def view(d):  # line_ref는 끼운 줄만큼 밀린다
        return [{**e, "line_ref": None} for e in d["events"] if e["ril"] or e["event"]]
    assert view(data) == view(base)


def test_vendor_coverage_tags_turn_idle_unknown_into_not_reached():
    """HAL·소켓 층은 한가할 때 오래 조용하다 → coverage_tags 줄로 수집이 살아 있음을 안다."""
    rows = [REQ41, (-100, 900, "VRIL_HAL", "req serial=40"), (-1, 901, "VRIL_MODEM", "frame"), (1, 901, "VRIL_MODEM", "frame")]
    assert _hal(_vendor_parse(rows), "ril_no_response") == "unknown"
    assert _hal(_vendor_parse(rows, {**VENDOR, "coverage_tags": ["VRIL_MODEM"]}), "ril_no_response") == "not_reached"


def test_vendor_unset_has_no_hal():
    data = _vendor_parse([REQ41, HAL41], vendor=None)
    assert "hal" not in _events(data, event="ril_no_response")[0]["fields"]
    assert all("hal" not in e["ril"] for e in data["events"] if e["ril"])


# -- 범위와 시계 -------------------------------------------------------------


def test_window_in_range_values():
    log = LOG_DIR / "data-disabled.log"  # 2026-09-20 14:30:00 ~ 14:30:29.9 (KST)
    data = _parse([log], "--around", "2026-09-21T00:00:00+09:00")
    assert data["coverage"]["window_in_range"] is False
    assert data["events"] == []
    assert data["coverage"]["first_ts"] == "2026-09-20T05:30:00.000Z"

    data = _parse([log], "--around", "2026-09-20T14:30:15+09:00", "--minutes", "0.1")
    assert data["coverage"]["window_in_range"] is True
    assert data["events"] and all(
        "2026-09-20T05:30:09" <= e["ts"] <= "2026-09-20T05:30:21" for e in data["events"]
    )

    data = _parse([log], "--around", "2026-09-20T14:32:00+09:00")
    assert data["coverage"]["window_in_range"] == "partial"
    assert data["input"]["window"] == {"start": "2026-09-20T05:27:00.000Z", "end": "2026-09-20T05:37:00.000Z"}

    data = _parse([log])
    assert data["coverage"]["window_in_range"] is True and data["input"]["mode"] == "full"

    code, _, err = _run(["parse", str(log), "--rules", str(RULES), "--around", "2026-09-20T14:32:00"])
    assert code == 2 and "타임존" in err


def test_ril_pairing_crosses_window_edge():
    log = LOG_DIR / "dual-sim-ril.log"
    # 12:00:14.4의 DEACTIVATE 응답만 윈도우 안. 요청(12:00:02.4)은 밖이지만 짝은 찾는다.
    data = _parse([log], "--around", "2026-09-22T12:00:14.400+09:00", "--minutes", "0.01")
    (resp,) = [e for e in data["events"] if e["event"] is None]
    assert resp["ril"]["paired_ts"] == "2026-09-22T03:00:02.400Z"
    assert _events(data, event="ril_timeout")


def test_clock_anomalies():
    data = _parse([LOG_DIR / "clock-anomaly.log"])
    kinds = [(a["kind"], a["delta_sec"]) for a in data["coverage"]["clock_anomalies"]]
    assert kinds == [("backward", -7.0), ("jump", 7201.0)], kinds
    data = _parse([LOG_DIR / "data-disabled.log"])
    assert data["coverage"]["clock_anomalies"] == []


# -- bugreport ---------------------------------------------------------------


def test_extract_bugreport_txt_and_zip():
    tmp = _tmp()
    for kind in ("txt", "zip"):
        info = logcat_gen.generate(SCENARIOS / "bugreport-wrap.yaml", tmp / kind, bugreport=kind)
        src = Path(info["files"][0])
        out = tmp / f"out-{kind}"
        code, data, err = _run(["extract-bugreport", str(src), "--out", str(out)])
        assert code == 0, err
        buffers = {f["buffer"] for f in data["files"]}
        assert buffers == {"system", "radio", "main"}, buffers
        produced = sorted(p.name for p in out.iterdir())
        assert produced == ["build.json", "logcat-main.txt", "logcat-radio.txt", "logcat-system.txt"]
        for path in out.glob("logcat-*.txt"):
            text = path.read_text(encoding="utf-8")
            assert "DUMP OF SERVICE" not in text and "모의 dumpsys" not in text, path.name
            assert "------" not in text and "Build fingerprint" not in text, path.name
        build = json.loads((out / "build.json").read_text(encoding="utf-8"))
        assert build["fingerprint"] == "mock/mocka56/a56:16/MOCKBUILD/MOCKA56_U1_20260915:user/release-keys"
        assert build["build"] == "MOCKA56_U1_20260915"
        # 꺼낸 radio 로그는 그대로 parse 할 수 있다
        parsed = _parse([out / "logcat-radio.txt"])
        assert _events(parsed, event="data_evaluation_rejected")
        # bugreport를 parse에 바로 넣으면 안내하고 멈춘다
        code, _, err = _run(["parse", str(src), "--full", "--rules", str(RULES)])
        assert code == 2 and "extract-bugreport" in err

    empty = tmp / "not-bugreport.txt"
    empty.write_text("== dumpstate: x\nnothing\n", encoding="utf-8")
    code, _, err = _run(["extract-bugreport", str(empty), "--out", str(tmp / "e")])
    assert code == 2 and "S21" in err


# -- 규칙 ----------------------------------------------------------------------


def test_rules_change_changes_output_without_code_change():
    tmp = _tmp()
    db = _copy_db(tmp)
    log = LOG_DIR / "data-connected.log"
    before = _parse([log], rules=db / "parser-rules")
    assert not _events(before, event="data_network_connected")

    path = db / "parser-rules" / "extractors.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n  - id: data-network-connected\n"
        "    added_for: DATA-001\n    added_on: 2026-09-29\n    reason: 시험용\n"
        "    tag_regex: '^DN-.+$'\n    patterns: ['onConnected:\\s*state=(?P<state>\\w+)']\n"
        "    event: data_network_connected\n    fields: [state]\n",
        encoding="utf-8",
    )
    after = _parse([log], rules=db / "parser-rules")
    (hit,) = _events(after, event="data_network_connected")
    assert hit["fields"] == {"state": "CONNECTED"} and hit["source"] == "rules"

    # 태그를 목록에서 빼면 그 줄이 사라진다
    tags = db / "parser-rules" / "tags.yaml"
    tags.write_text(
        "\n".join(l for l in tags.read_text(encoding="utf-8").splitlines() if "'^DCM-" not in l) + "\n",
        encoding="utf-8",
    )
    trimmed = _parse([log], rules=db / "parser-rules")
    assert any(e["tag"] == "DCM-0" for e in before["events"])
    assert not any(e["tag"] == "DCM-0" for e in trimmed["events"])


def _expect_rules_error(mutate, needle: str):
    tmp = _tmp()
    db = _copy_db(tmp)
    mutate(db / "parser-rules")
    code, _, err = _run(["parse", str(LOG_DIR / "data-connected.log"), "--full",
                         "--rules", str(db / "parser-rules")])
    assert code == 2, err
    assert needle in err, err


def test_rules_are_validated():
    def prefix(rules: Path, event="builtin.data.fake"):
        path = rules / "extractors.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("event: data_evaluation_allowed", f"event: {event}"),
            encoding="utf-8",
        )

    _expect_rules_error(prefix, "builtin./ext.")
    _expect_rules_error(lambda r: prefix(r, "ext.data.fake"), "builtin./ext.")
    _expect_rules_error(lambda r: prefix(r, "ril_timeout"), "예약")

    def no_reason(rules: Path):
        path = rules / "ril.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(", reason: 초기}", "}", 1), encoding="utf-8"
        )

    _expect_rules_error(no_reason, "스키마 오류")

    def bad_regex(rules: Path):
        path = rules / "tags.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace("'^DNC-\\d+$'", "'^DNC-(\\d+$'", 1),
            encoding="utf-8",
        )

    _expect_rules_error(bad_regex, "정규식 오류")
    _expect_rules_error(lambda r: (r / "ril.yaml").unlink(), "규칙 파일이 없습니다")


def test_slow_extractor_times_out_and_others_continue():
    """패턴당 시간 상한(matcher.pattern_timeout_ms)을 넘긴 extractor는 error로 남고
    분석은 계속한다 (04-parser-matching.md §5.8 (4))."""
    tmp = _tmp()
    db = _copy_db(tmp)
    cfg = db / "issue-db.config.yaml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace("pattern_timeout_ms: 2000", "pattern_timeout_ms: 300"),
        encoding="utf-8",
    )
    path = db / "parser-rules" / "extractors.yaml"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\n  - id: slow-one\n    added_for: DATA-001\n    added_on: 2026-09-29\n    reason: 시험용\n"
        "    tag_regex: '^DNC-\\d+$'\n    patterns: ['(?P<x>(a+)+)$']\n    event: slow_one\n    fields: [x]\n",
        encoding="utf-8",
    )
    log = tmp / "slow.log"
    log.write_text(
        (LOG_DIR / "data-disabled.log").read_text(encoding="utf-8")
        + "09-20 14:30:40.000  1234  1244 D DNC-0: " + "a" * 40 + "!\n",
        encoding="utf-8",
        newline="\n",
    )
    data = _parse([log], rules=db / "parser-rules")
    assert [e["extractor"] for e in data["errors"]] == ["slow-one"]
    assert "pattern-timeout" in [w["code"] for w in data["warnings"]]
    assert not _events(data, event="slow_one")
    assert _events(data, event="data_evaluation_rejected"), "다른 extractor는 그대로 돈다"


# -- 백엔드와 외부 파서 ------------------------------------------------------------


def test_site_backend_builtin_events_with_extractors():
    data = _parse([LOG_DIR / "data-disabled.log"], root=_root("site"))
    assert data["backend"]["name"] == "site"
    builtin = [e for e in data["events"] if (e["event"] or "").startswith("builtin.")]
    names = {e["event"] for e in builtin}
    assert names == {"builtin.data.setup_not_allowed", "builtin.data.user_data_disabled"}
    assert all(e["source"] == "backend:site" and e["category_hint"] == "data" for e in builtin)
    # builtin 레코드는 그 줄 레코드의 line_ref를 그대로 가진다
    lines_by_ref = {json.dumps(e["line_ref"], sort_keys=True): e for e in data["events"] if e["event"] is None}
    for e in builtin:
        base = lines_by_ref[json.dumps(e["line_ref"], sort_keys=True)]
        assert (base["ts"], base["tag"], base["msg"]) == (e["ts"], e["tag"], e["msg"])
    rules = _events(data, event="data_evaluation_rejected")
    assert rules and all(e["source"] == "rules" for e in rules)
    # 같은 줄에서 builtin 판별과 extractor가 둘 다 나온다
    assert {e["ts"] for e in rules} <= {e["ts"] for e in builtin}
    # 샘플 이슈 DB는 reference ≥ 0.1.0을 고정한다 → 경고
    assert [w["code"] for w in data["warnings"]] == ["parser-backend-mismatch"]


def test_backend_version_mismatch_warns():
    tmp = _tmp()
    db = _copy_db(tmp)
    cfg = db / "issue-db.config.yaml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace("min_version: 0.1.0", "min_version: 9.0.0"),
        encoding="utf-8",
    )
    data = _parse([LOG_DIR / "data-connected.log"], rules=db / "parser-rules")
    assert [w["code"] for w in data["warnings"]] == ["parser-backend-mismatch"]
    assert "9.0.0" in data["warnings"][0]["message"]


def _external_root(version: str = "1.2.0") -> Path:
    root = make_plugin_root.make(with_site_backend=True)
    vendor = root / "scripts" / "adapters" / "site_vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / "tests/mocks/adapters/legacy_data_parser.py", vendor / "legacy_parser.py")
    _set_defaults(
        root,
        external_parsers={
            "data": {
                "command": [sys.executable, "${CLAUDE_PLUGIN_ROOT}/scripts/adapters/site_vendor/legacy_parser.py", "{log}"],
                "output": "json",
                "adapter": "site_data_existing",
                "version": version,
                "mode": "merge",
                "timeout_sec": 60,
            }
        },
    )
    return root


def test_external_parser_merge_and_no_external():
    root = _external_root()
    data = _parse([LOG_DIR / "data-disabled.log"], root=root)
    ext = [e for e in data["events"] if e["source"].startswith("external:")]
    assert {e["event"] for e in ext} == {"ext.data.setup_not_allowed", "ext.data.user_data_disabled"}
    assert all(e["source"] == "external:site_data_existing" and e["category_hint"] == "data" for e in ext)
    # 외부 파서 시각도 UTC로 바뀐다 (logcat 스탬프 + --tz/--year)
    first = min(e["ts"] for e in ext if e["event"] == "ext.data.user_data_disabled")
    assert first == "2026-09-20T05:30:03.000Z"
    # 외부 파서 이벤트는 파일 순번만 안다 (줄 번호 없음)
    assert all(e["line_ref"] == {"file_index": 0, "line_no": None} for e in ext)
    assert events.validate_events(data["events"]) == []
    assert data["external"] == [
        {"category": "data", "adapter": "site_data_existing", "version": "1.2.0", "mode": "merge"}
    ]
    assert _events(data, event="data_evaluation_rejected"), "merge면 백엔드·extractor 이벤트가 남는다"
    assert data["events"] == sorted(data["events"], key=lambda e: e["ts"])

    off = _parse([LOG_DIR / "data-disabled.log"], "--full", "--no-external", root=root)
    assert off["external_disabled"] is True and off["external"] == []
    assert not [e for e in off["events"] if e["source"].startswith("external:")]


def test_external_parser_replace_mode():
    root = _external_root()
    path = root / "site-defaults.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["external_parsers"]["data"]["mode"] = "replace"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    out = _parse([LOG_DIR / "data-disabled.log"], root=root)
    data_backend = [e for e in out["events"] if e["category_hint"] == "data" and e["source"].startswith("backend:")]
    assert not data_backend, "replace면 백엔드의 data 레코드를 뺀다"
    assert any(e["event"] is None and e["source"].startswith("external:") for e in out["events"])


def test_external_parser_pin_mismatch_warns():
    tmp = _tmp()
    db = _copy_db(tmp)
    cfg = db / "issue-db.config.yaml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            "external_parsers: {}", "external_parsers:\n  data: {adapter: site_data_existing, min_version: 2.0.0}"
        ),
        encoding="utf-8",
    )
    # 어댑터 없음 (사외 기본 site-defaults는 external_parsers가 비어 있다)
    data = _parse([LOG_DIR / "data-connected.log"], rules=db / "parser-rules")
    assert [w["code"] for w in data["warnings"]] == ["external-parser-mismatch"]
    assert "어댑터 없음" in data["warnings"][0]["message"]
    # 버전이 낮음
    data = _parse([LOG_DIR / "data-connected.log"], rules=db / "parser-rules", root=_external_root("1.2.0"))
    codes = [w["code"] for w in data["warnings"]]
    assert "external-parser-mismatch" in codes and "버전이 낮음" in json.dumps(data["warnings"], ensure_ascii=False)
    # 버전이 충분
    data = _parse([LOG_DIR / "data-connected.log"], rules=db / "parser-rules", root=_external_root("2.1.0"))
    assert "external-parser-mismatch" not in [w["code"] for w in data["warnings"]]


def test_unknown_backend_is_usage_error():
    root = make_plugin_root.make()
    _set_defaults(root, parser={"backend": "site"})  # site 백엔드가 없는 루트
    code, _, err = _run(["parse", str(LOG_DIR / "data-connected.log"), "--full", "--rules", str(RULES)], root)
    assert code == 2 and "parser.backend" in err


# -- 기타 ------------------------------------------------------------------------


def test_sanitize_build_and_branch_names():
    from common.buildname import is_valid_branch_name, sanitize_build

    cases = {"A..B": "A_B", "X.lock": "X_lock", "abc.": "abc_", "a b/c": "a_b_c",
             "MOCKA56_U1_20260915": "MOCKA56_U1_20260915"}
    for raw, expected in cases.items():
        assert sanitize_build(raw) == expected, raw
        assert is_valid_branch_name(f"fix/DATA-001-01-{sanitize_build(raw)}"), raw
    assert not is_valid_branch_name("fix/A..B")
    assert not is_valid_branch_name("fix/X.lock")
    assert not is_valid_branch_name("fix/abc.")


def test_masking_runs_before_extractors():
    """마스킹 자리: 줄은 extractor보다 먼저 마스킹된다 (contracts.md §3.2 parse --mask)."""
    import parse_logcat
    from common import parser_rules
    from parser_backends import reference

    rules = parser_rules.load(RULES)
    events = reference.BACKEND.parse([LOG_DIR / "no-service.log"], TZ, 2026, None)
    seen = []

    def fake_masker(text: str) -> str:
        seen.append(text)
        return text.replace("cause=13", "cause=99")

    out = parse_logcat.postprocess(events, rules, masker=fake_masker)
    rejected = [e for e in out if e["event"] == "network_registration_rejected"]
    assert rejected and all(e["fields"]["cause"] == "99" for e in rejected)
    assert all("cause=13" not in e["msg"] for e in out)
    assert seen, "마스커가 불리지 않았다"


def _raw_lines(path: Path) -> list[str]:
    with open(path, encoding="utf-8", newline="") as fh:
        return [line.rstrip("\r\n") for line in fh]


def test_line_ref_points_to_raw_line():
    log = LOG_DIR / "data-setup-error.log"
    data = _parse([log])
    raw = _raw_lines(log)
    previous = None
    for e in data["events"]:
        assert list(e)[-1] == "line_ref"
        ref = e["line_ref"]
        assert ref["file_index"] == 0 and ref["line_no"] >= 1
        if e["event"] is None:
            text = raw[ref["line_no"] - 1]
            assert e["tag"] in text and e["msg"] in text, (ref, text)
            previous = e
        elif e["source"] == "rules":
            # 파생 이벤트는 그 줄 레코드의 줄 위치를 그대로 가진다
            assert e["line_ref"] == previous["line_ref"] and e["ts"] == previous["ts"]
    assert any(e["source"] == "rules" for e in data["events"])


def test_line_ref_multi_file_index():
    first, second = LOG_DIR / "data-connected.log", LOG_DIR / "data-disabled.log"
    data = _parse([first, second])
    tags = {0: {e["tag"] for e in _events(_parse([first]), event=None)},
            1: {e["tag"] for e in _events(_parse([second]), event=None)}}
    refs = {e["line_ref"]["file_index"] for e in data["events"]}
    assert refs == {0, 1}
    for e in data["events"]:
        if e["event"] is None:
            i = e["line_ref"]["file_index"]
            assert e["tag"] in tags[i]
            assert e["tag"] in _raw_lines([first, second][i])[e["line_ref"]["line_no"] - 1]
    swapped = _parse([second, first])
    assert {e["line_ref"]["file_index"] for e in _events(swapped, ts="2026-09-20T05:30:00.000Z")} == {0}


def test_site_defaults_required():
    code, _, err = _run(["parse", str(LOG_DIR / "data-connected.log"), "--full", "--rules", str(RULES)],
                        root=REPO / "plugin")
    assert code == 2 and "사내 기본값 없음" in err


def test_uncollected_tags_counts_dropped_tags_of_collected_pids_only():
    """tags.yaml에 없어 버려진 줄의 태그는, 수집된 줄과 같은 pid일 때만 `uncollected_tags`(최상위)에 나온다."""
    log = _tmp() / "u.log"
    log.write_text("\n".join([
        "09-27 18:00:00.000  1300  1320 D RILJ: [PHONE0] [0095]> LAST_CALL_FAIL_CAUSE",
        "09-27 18:00:01.000  1300  1320 I GsmCdmaCallTracker: [PHONE0] call state changed: ACTIVE",
        "09-27 18:00:02.000  1300  1320 W GsmCdmaCallTracker: [PHONE0] handlePollCalls: call dropped",
        "09-27 18:00:02.500  1300  1320 D OtherTag: [PHONE0] noise",
        "09-27 18:00:03.000  4242  4242 E ForeignTag: 다른 프로세스",
        "09-27 18:00:03.100  4242  4242 E ForeignTag: 다른 프로세스",
    ]) + "\n", encoding="utf-8")
    data = _parse([log], "--full", "--mask")
    assert data["uncollected_tags"] == [{"tag": "GsmCdmaCallTracker", "lines": 2, "warn": 1},
                                        {"tag": "OtherTag", "lines": 1, "warn": 0}]
    assert "ForeignTag" not in json.dumps(data["uncollected_tags"])
    # 없으면 키가 없다(기존 출력 불변)
    assert "uncollected_tags" not in _parse([LOG_DIR / "data-connected.log"], "--full", "--mask")


def _lines(name: str, *stamps: str) -> Path:
    path = _tmp() / name
    path.write_text("".join(f"{s}  1234  1244 D RILJ: x\n" for s in stamps), encoding="utf-8", newline="\n")
    return path


def test_reboot_new_year_line_does_not_shift_later_lines():
    """재부팅 직후 시계가 01-01이어도 해 넘김이 아니다 (월이 줄었다 늘어도 연도는 그대로)."""
    log = _lines("reboot.log", "09-22 12:00:00.000", "01-01 00:00:05.000", "09-22 12:05:00.000")
    data = _parse([log], "--around", "2026-09-22T12:05:00+09:00", "--minutes", "1", tz="Asia/Seoul")
    assert [e["ts"] for e in data["events"]] == ["2026-09-22T03:05:00.000Z"]
    assert data["coverage"]["window_in_range"] is not False     # 이전: 범위가 2027까지 늘어 events 0
    # 12월 중 재부팅: 01-01이 해를 올렸다가 12월로 돌아오면 되돌린다
    log = _lines("reboot-dec.log", "12-20 10:00:00.000", "01-01 00:00:05.000", "12-20 10:05:00.000")
    data = _parse([log], tz="UTC")
    assert [e["ts"][:10] for e in data["events"]] == ["2026-12-20", "2026-12-20", "2027-01-01"]   # 이벤트는 시각순


def test_multi_file_year_rollover_warns():
    one, two = _lines("a.log", "12-31 23:59:00.000"), _lines("b.log", "01-01 00:01:00.000")
    codes = [w["code"] for w in _parse([one, two], tz="UTC")["warnings"]]
    assert "year_rollover_ambiguous" in codes
    assert "year_rollover_ambiguous" not in [w["code"] for w in _parse([one], tz="UTC")["warnings"]]


def test_utf16_and_bom_logs_parse_like_utf8():
    src = LOG_DIR / "dual-sim-ril.log"
    text = src.read_text(encoding="utf-8")
    want = [(e["ts"], e["tag"]) for e in _parse([src])["events"] if e["event"] is None]
    assert want
    tmp = _tmp()
    (tmp / "u16.log").write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
    (tmp / "u8bom.log").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    for name in ("u16.log", "u8bom.log"):
        got = [(e["ts"], e["tag"]) for e in _parse([tmp / name])["events"] if e["event"] is None]
        assert got == want, name


def test_zero_lines_is_not_out_of_range():
    log = _tmp() / "junk.log"
    log.write_text("not a log line\nanother one\n", encoding="utf-8", newline="\n")
    data = _parse([log], "--around", "2026-09-22T12:05:00+09:00")
    assert data["coverage"]["window_in_range"] is None and data["complete"] is False
    assert {"no-lines-parsed", "file-unparsed"} <= {w["code"] for w in data["warnings"]}
    assert _parse([log], "--full")["coverage"]["window_in_range"] is None     # window와 무관


def test_single_file_and_empty_file_warning_wording():
    one = _lines("c.log", "01-01 00:00:05.000", "12-31 23:59:00.000")      # 재부팅이 낀 한 파일
    assert "year_rollover_ambiguous" not in [w["code"] for w in _parse([one], tz="UTC")["warnings"]]
    empty = _tmp() / "empty.log"
    empty.write_text("", encoding="utf-8")
    msgs = [w["message"] for w in _parse([empty], tz="UTC")["warnings"] if w["code"] == "file-unparsed"]
    assert len(msgs) == 1 and "빈 파일" in msgs[0]


def _all_tests():
    return [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]


if __name__ == "__main__":
    if "--update" in sys.argv:
        for path in update_snapshots():
            print(path)
        raise SystemExit(0)
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
