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
- `--mask`·`cut`은 Phase 4 (종료 코드 2), 마스킹 자리가 extractor보다 앞
- `site-defaults.yaml` 없으면 종료 코드 2

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
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "tests" / "mocks"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import logcat_gen  # noqa: E402
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
    assert by_tag["DNC-0"] == {0} and by_tag["DSM-1"] == {1} and by_tag["DSM-0"] == {0}
    assert {e["phone_id"] for e in lines if e["tag"] == "RILJ"} == {0}  # 메시지 접두어

    data = _parse([LOG_DIR / "dual-sim-ril.log"])
    (uicc,) = _events(data, tag="UiccController", event=None)
    assert uicc["phone_id"] is None  # 접미사·접두어 없는 태그


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


# -- 백엔드와 외부 파서 ------------------------------------------------------------


def test_site_backend_builtin_events_with_extractors():
    data = _parse([LOG_DIR / "data-disabled.log"], root=_root("site"))
    assert data["backend"]["name"] == "site"
    builtin = [e for e in data["events"] if (e["event"] or "").startswith("builtin.")]
    names = {e["event"] for e in builtin}
    assert names == {"builtin.data.setup_not_allowed", "builtin.data.user_data_disabled"}
    assert all(e["source"] == "backend:site" and e["category_hint"] == "data" for e in builtin)
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


def test_mask_and_cut_are_phase4():
    code, _, err = _run(["parse", str(LOG_DIR / "data-connected.log"), "--full",
                         "--rules", str(RULES), "--mask"])
    assert code == 2 and "Phase 4" in err
    code, _, err = _run(["cut", str(LOG_DIR / "data-connected.log"), "--around",
                         "2026-09-23T09:00:01+09:00", "--out", str(_tmp() / "cut.log")])
    assert code == 2 and "Phase 4" in err


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


def test_site_defaults_required():
    code, _, err = _run(["parse", str(LOG_DIR / "data-connected.log"), "--full", "--rules", str(RULES)],
                        root=REPO / "plugin")
    assert code == 2 and "사내 기본값 없음" in err


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
