#!/usr/bin/env python3
"""Phase 4 완료 기준 확인: 마스킹 (11-phases.md Phase 4, 08-safety.md §8).

- 항목별 누락/과잉 (자격증명 `<CRED#n>`: SIP Digest `response=`·`nonce=`, AKA `RES`, `password=`)
- 번호 토큰(같은 값 = 같은 번호, 기존 토큰 다음 번호), 결정성, 멱등, `allow_patterns`
- Jira 응답 JSON 텍스트 → `mask_pii --events` → 전화번호·IMEI 토큰 (§8.1)
- `mask_pii` 치환·`--check`(파일, `--staged`, `--changed`)
- `parse --mask` → 매처 결과가 Phase 3와 같음, extractor가 마스킹된 값을 추출,
  모의 site 백엔드의 builtin 필드도 마스킹, `cut` 결과에 원본 식별자 없음

`pytest tests/test_masking.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_plugin_root  # noqa: E402
import mock_env  # noqa: E402
from common import masking  # noqa: E402

SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
RULES = SAMPLE / "parser-rules"
TZ, YEAR = "Asia/Seoul", "2026"
_ROOTS: dict[str, Path] = {}


def _root(kind: str = "plain") -> Path:
    if kind not in _ROOTS or not _ROOTS[kind].is_dir():
        root = make_plugin_root.make(with_site_backend=(kind == "site"))
        if kind == "site":
            path = root / "site-defaults.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["parser"] = {"backend": "site"}
            path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        _ROOTS[kind] = root
    return _ROOTS[kind]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="tt-mask-"))


def _run(script: str, args: list[str], root: Path | None = None, cwd=None) -> subprocess.CompletedProcess:
    root = root or _root()
    return subprocess.run(
        [sys.executable, str(root / "scripts" / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=mock_env.env_with_mocks(plugin_root=root), cwd=cwd,
    )


def _write(lines: list[str], name: str = "raw.log") -> Path:
    path = _tmp() / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def _parse(log: Path, *extra: str, rules: Path = RULES, root: Path | None = None) -> dict:
    proc = _run("parse_logcat.py", ["parse", str(log), "--full", "--rules", str(rules),
                                    "--tz", TZ, "--year", YEAR, *extra], root)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# -- 항목별 누락/과잉 -----------------------------------------------------------

# (입력, 종류, 원본 값) — 각 원본 값이 사라지고 그 종류의 토큰이 생겨야 한다.
DETECT = [
    ("imsi=450081234567890", "IMSI", "450081234567890"),
    ("IMSI: 450081234567890 attach", "IMSI", "450081234567890"),
    ("no context 450081234567891 here", "IMSI", "450081234567891"),       # MCC 450, Luhn 아님
    ("imei=490154203237518", "IMEI", "490154203237518"),
    ("device 490154203237518 boot", "IMEI", "490154203237518"),            # Luhn
    ("iccid=8982300123456789012", "ICCID", "8982300123456789012"),
    ("card 89823001234567890123 inserted", "ICCID", "89823001234567890123"),
    ("SUPI imsi-450081234567890", "SUPI", "imsi-450081234567890"),
    ("SUCI suci-0-450-08-0-0-0-a1b2c3", "SUCI", "suci-0-450-08-0-0-0-a1b2c3"),
    ("tmsi=0x1a2b3c4d", "TMSI", "0x1a2b3c4d"),
    ("5g-guti=45008c1d2e3f4a5b", "GUTI", "45008c1d2e3f4a5b"),
    ("dial +82-10-1234-5678", "MSISDN", "+82-10-1234-5678"),
    ("dial 010-9876-5432", "MSISDN", "010-9876-5432"),
    ("tel:+821012345678", "MSISDN", "+821012345678"),
    ("sendText: dest=01098765432 parts=1", "MSISDN", "01098765432"),
    ("REGISTER sip:+821012345678@ims.mnc008.mcc450.3gppnetwork.org", "IMPU", "+821012345678"),
    ('Authorization: Digest username="450081234567890@ims.example.org"', "IMPI", "450081234567890"),
    ("CellIdentityLte:{ mCi=12345678 mPci=301 mTac=4660 }", "CELL", "12345678"),
    ("cellId=987654 lac=4321", "CELL", "987654"),
    ("ip=10.23.45.67", "IP", "10.23.45.67"),
    ("dns 2001:4860:4860::8888", "IP", "2001:4860:4860::8888"),
    ("gw fe80::1", "IP", "fe80::1"),
    ("wlan mac aa:bb:cc:dd:ee:ff", "MAC", "aa:bb:cc:dd:ee:ff"),
    ("mail tester@example.com", "EMAIL", "tester@example.com"),
    # 자격증명 (IMS REGISTER 로그가 fixture에 들어가므로)
    ('Authorization: Digest nonce="abcDEF123==", response="0123456789abcdef0123456789abcdef"', "CRED",
     "0123456789abcdef0123456789abcdef"),
    ('WWW-Authenticate: Digest realm="ims", nonce="Zm9vYmFyYmF6"', "CRED", "Zm9vYmFyYmF6"),
    ("AKA RES=a1b2c3d4e5f60718", "CRED", "a1b2c3d4e5f60718"),
    ("AKA AUTN=00112233445566778899aabbccddeeff", "CRED", "00112233445566778899aabbccddeeff"),
    ("wifi password=hunter2", "CRED", "hunter2"),
    ("oauth token: eyJhbGciOiJIUzI1NiJ9", "CRED", "eyJhbGciOiJIUzI1NiJ9"),
]

# 바뀌면 안 되는 줄 (빌드 번호·타임스탬프·일반 숫자·설정 키·Android 자체 마스킹)
KEEP = [
    "09-20 14:30:00.000  1234  1244 D DNC-0: [PHONE0] evaluation result: NOT_ALLOWED reasons=[DATA_DISABLED]",
    "2026-09-20 14:30:00.123 +0900  1234  1244 D RILJ: [0041]> SETUP_DATA_CALL apn=default",
    "Build: MOCKA56_U1_20260915",
    "Build fingerprint: 'mock/mocka56/a56:16/MOCKBUILD/MOCKA56_U1_20260915:user/release-keys'",
    "occurred 2026-09-20T14:32:10+0900 created 2026-09-20T15:02:00+09:00",
    "time=1695187800123 serial=0041 latency_ms=12000 timeout_ms=30000 version 16.0.1",
    "registration rejected: cause=13 domain=PS mEarfcn=1850",
    "carrier config key=KEY_CARRIER_VOLTE_AVAILABLE_BOOL",
    "onResponse response=OK code=200",                 # SIP 인증 헤더 문맥이 아님
    "imsi=310260xxxxxxxxx iccid=89************ ***",   # Android 자체 마스킹
    "RIL version 1.6 uptime 12:34:56 build 20260915",
    "carrierId=1839 mccmnc=45008 subId=2 slot=1",
]


def test_each_kind_is_masked():
    for text, kind, raw in DETECT:
        out = masking.new_masker()(text)
        assert raw not in out, f"누락: {text!r} → {out!r}"
        assert f"<{kind}#1>" in out, f"{kind} 토큰 없음: {text!r} → {out!r}"


def test_no_over_masking():
    masker = masking.new_masker()
    for text in KEEP:
        assert masker(text) == text, f"과잉: {text!r} → {masker(text)!r}"


def test_numbered_tokens_and_existing_tokens():
    masker = masking.new_masker()
    out = masker("mCi=111 mCi=222 mCi=111")
    assert out == "mCi=<CELL#1> mCi=<CELL#2> mCi=<CELL#1>"
    # 같은 마스커(한 파일) 안에서는 줄이 달라도 같은 값 = 같은 번호
    assert masker("cellId=222") == "cellId=<CELL#2>"
    # 번호는 처음 나온 순서 (규칙 순서가 아니다)
    assert masking.new_masker()("a 010-1111-2222 b tel:+821033334444") == "a <MSISDN#1> b tel:<MSISDN#2>"

    text = "cellId=<CELL#1> mCi=555"
    out = masking.new_masker(text)(text)
    assert out == "cellId=<CELL#1> mCi=<CELL#2>", out  # 기존 토큰과 겹치지 않음


def test_deterministic_and_idempotent():
    lines = [t for t, _, _ in DETECT] + KEEP
    first = [masking.new_masker()(t) for t in lines]
    assert first == [masking.new_masker()(t) for t in lines]
    for once in first:
        assert masking.new_masker(once)(once) == once, f"멱등 아님: {once!r}"


def test_allow_patterns():
    text = "ip=10.0.0.1 ip=10.0.0.2"
    out = masking.new_masker(allow_patterns=[r"^10\.0\.0\.1$"])(text)
    assert out == "ip=10.0.0.1 ip=<IP#1>"


def test_find_reports_kinds_without_values():
    found = masking.new_masker().find("imsi=450081234567890 ok ip=1.2.3.4 <CELL#1>")
    assert [f["kind"] for f in found] == ["IMSI", "IP"]
    assert all(set(f) == {"kind", "start", "end"} for f in found)


# -- mask_pii.py ------------------------------------------------------------------


def test_mask_pii_jira_json_via_events():
    jira = {
        "key": "MOCK-1101",
        "fields": {
            "summary": "고객 010-1234-5678 데이터 안 됨",
            "description": "단말 IMEI 490154203237518, 발신번호 +82-10-9999-8888\n재부팅 후 재현",
            "customfield_10001": "2026-09-20T14:32:10+0900",
            "customfield_10003": "MOCKA56_U1_20260915",
        },
        "comments": [{"author": "mock.reporter", "body": "다시 010-1234-5678 로 연락 바랍니다"}],
    }
    src = _tmp() / "jira.json"
    src.write_text(json.dumps(jira, ensure_ascii=False), encoding="utf-8")
    out = src.with_name("jira.masked.json")
    proc = _run("mask_pii.py", ["--events", str(src), "--out", str(out), "--db", str(SAMPLE)])
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    text = json.dumps(doc, ensure_ascii=False)
    for raw in ("010-1234-5678", "490154203237518", "+82-10-9999-8888"):
        assert raw not in text, raw
    assert doc["fields"]["summary"] == "고객 <MSISDN#1> 데이터 안 됨"
    assert "<IMEI#1>" in doc["fields"]["description"]
    assert doc["comments"][0]["body"] == "다시 <MSISDN#1> 로 연락 바랍니다"  # 같은 번호 = 같은 토큰
    assert doc["fields"]["customfield_10001"] == "2026-09-20T14:32:10+0900"
    assert doc["fields"]["customfield_10003"] == "MOCKA56_U1_20260915"
    assert doc["masked"] is True


def test_mask_pii_events_document():
    src = _tmp() / "events.json"
    src.write_text(json.dumps({"masked": False, "events": [
        {"ts": "2026-09-20T05:30:00.000Z", "tag": "EXT", "msg": "cellId=4321 ip=10.1.2.3",
         "event": "ext.data.x", "fields": {"cell": "4321", "note": "ip=10.1.2.3"}},
    ]}), encoding="utf-8")
    out = src.with_name("out.json")
    proc = _run("mask_pii.py", ["--events", str(src), "--out", str(out)], cwd=_tmp())
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    (event,) = doc["events"]
    assert doc["masked"] is True
    assert event["msg"] == "cellId=<CELL#1> ip=<IP#1>"
    assert event["fields"] == {"cell": "<CELL#1>", "note": "ip=<IP#1>"}  # 문맥 없는 값도 같은 번호


def test_mask_pii_replace_and_check_files():
    raw = _write(["09-20 14:30:00.000  1234  1244 D SST-0: [PHONE0] cellId=123456 ip=10.9.8.7",
                  "09-20 14:30:01.000  1234  1244 D SST-0: [PHONE0] cellId=123456"])
    proc = _run("mask_pii.py", [str(raw), "--check"], cwd=_tmp())
    assert proc.returncode == 1
    result = json.loads(proc.stdout)
    assert [(d["line"], d["kind"]) for d in result["detections"]] == [(1, "CELL"), (1, "IP"), (2, "CELL")]
    assert "123456" not in proc.stdout + proc.stderr  # 검사 결과에 값을 내지 않는다

    proc = _run("mask_pii.py", [str(raw)], cwd=_tmp())
    assert proc.returncode == 0
    assert proc.stdout.splitlines()[1].endswith("cellId=<CELL#1>")

    proc = _run("mask_pii.py", [str(raw), "--in-place"], cwd=_tmp())
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["files"][0]["replacements"] == {"CELL": 2, "IP": 1}
    assert _run("mask_pii.py", [str(raw), "--check"], cwd=_tmp()).returncode == 0


def test_sample_db_fixtures_are_masked():
    logs = sorted(SAMPLE.glob("*/*/fixtures/*.log")) + sorted((REPO / "tests/fixtures/logs").glob("*.log"))
    proc = _run("mask_pii.py", [*map(str, logs), "--check", "--db", str(SAMPLE)])
    assert proc.returncode == 0, proc.stdout


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_mask_pii_check_staged_and_changed():
    repo = _tmp() / "db"
    shutil.copytree(SAMPLE, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    note = repo / "data/DATA-001-no-setup-data-call/jira/MOCK-1101.yaml"
    original = note.read_text(encoding="utf-8")
    note.write_text(original + "# 고객 010-1234-5678\n", encoding="utf-8")

    # 워킹 트리만 바뀜: --staged는 통과, --changed는 걸린다
    assert _run("mask_pii.py", ["--check", "--staged", "--db", str(repo)]).returncode == 0
    proc = _run("mask_pii.py", ["--check", "--changed", "main", "--db", str(repo)])
    assert proc.returncode == 1, proc.stderr
    assert json.loads(proc.stdout)["detections"][0]["path"].endswith("MOCK-1101.yaml")

    _git(repo, "add", "-A")
    assert _run("mask_pii.py", ["--check", "--staged", "--db", str(repo)]).returncode == 1
    # index는 그대로 두고 워킹 트리만 고치면 --staged는 여전히 걸린다 (index 기준)
    note.write_text(original, encoding="utf-8")
    assert _run("mask_pii.py", ["--check", "--staged", "--db", str(repo)]).returncode == 1


def test_mask_pii_check_does_not_skip_nul_files():
    """R-5: NUL이 든 파일(잘린 logcat·UTF-16)도 건너뛰지 않는다 — NUL을 지우고 검사하고 `checked`에 센다."""
    repo = _tmp() / "db"
    shutil.copytree(SAMPLE, repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    fixtures = repo / "data/DATA-001-no-setup-data-call/fixtures"
    (fixtures / "x.log").write_bytes(b"imsi=450081234567890\0tail\n")                 # 잘린 줄 뒤 NUL
    (fixtures / "y.log").write_bytes("imsi=450081234567890\n".encode("utf-16-le"))      # UTF-16
    _git(repo, "add", "-A")
    for scope in (["--staged"], ["--changed", "main"]):
        proc = _run("mask_pii.py", ["--check", *scope, "--db", str(repo)])
        assert proc.returncode == 1, (scope, proc.stdout, proc.stderr)
        result = json.loads(proc.stdout)
        assert result["checked"] == 2, scope
        assert sorted(Path(d["path"]).name for d in result["detections"]) == ["x.log", "y.log"], scope


def test_mask_pii_bad_allow_pattern_is_usage_error():
    """R-6: 컴파일되지 않는 `mask.allow_patterns`는 traceback이 아니라 종료 코드 2와 원인 문구."""
    repo = _tmp() / "db"
    shutil.copytree(SAMPLE, repo)
    cfg = repo / "issue-db.config.yaml"
    allow = r"    - '^MOCK[AB]\d{2}_U\d+_\d{8}$'"
    text = cfg.read_text(encoding="utf-8")
    assert allow in text
    cfg.write_text(text.replace(allow, "    - '('"), encoding="utf-8", newline="\n")
    raw = _write(["ip=10.9.8.7"])
    proc = _run("mask_pii.py", [str(raw), "--check", "--db", str(repo)], cwd=_tmp())
    assert proc.returncode == 2 and "allow_patterns" in proc.stderr and "Traceback" not in proc.stderr, proc.stderr
    try:
        masking.new_masker(allow_patterns=["("])
    except masking.AllowPatternError as exc:
        assert "allow_patterns" in str(exc)
    else:
        raise AssertionError("AllowPatternError가 나야 한다")


# -- parse --mask와 매처 --------------------------------------------------------------


def _match(events_doc: dict, *extra: str) -> dict:
    path = _tmp() / "events.json"
    path.write_text(json.dumps(events_doc, ensure_ascii=False), encoding="utf-8")
    proc = _run("match_signatures.py", ["--db", str(SAMPLE), "--events", str(path), "--top", "0", *extra])
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _sc(result: dict):
    return ([(t["type"], t["S"]) for t in result["types"]],
            [(c["cause"], c["S"], c["C"]) for c in result["causes"]],
            [(c["type"], c["cause"], c["score"]) for c in result["candidates"]])


def test_parse_mask_pipeline_matches_phase3():
    logs = sorted(SAMPLE.glob("*/*/fixtures/*.log"))
    assert len(logs) >= 18
    for log in logs:
        masked = _parse(log, "--mask")
        assert masked["masked"] is True
        plain = _parse(log)
        # fixture는 이미 마스킹돼 있으므로 --mask는 텍스트를 바꾸지 않는다(멱등)
        assert [e["msg"] for e in masked["events"]] == [e["msg"] for e in plain["events"]], log.name
        plain["masked"] = True  # Phase 3 테스트 입력과 같은 방식
        assert _sc(_match(masked, "--regress")) == _sc(_match(plain, "--regress")), log.name


def test_extractor_reads_masked_values():
    tmp = _tmp()
    db = tmp / "db"
    for part in ("parser-rules", "schema"):
        shutil.copytree(SAMPLE / part, db / part)
    shutil.copyfile(SAMPLE / "issue-db.config.yaml", db / "issue-db.config.yaml")
    path = db / "parser-rules" / "extractors.yaml"
    path.write_text(path.read_text(encoding="utf-8")
                    + "\n  - id: serving-cell\n    added_for: NETWORK-001\n    added_on: 2026-09-29\n"
                    "    reason: 시험용\n    tag_regex: '^(SST|ServiceStateTracker)(-\\d+)?$'\n"
                    "    patterns: ['cellId=(?P<cell><CELL#\\d+>)']\n    event: serving_cell\n    fields: [cell]\n",
                    encoding="utf-8")
    log = _write([
        "09-24 10:11:00.000  1234  1260 I SST-0: [PHONE0] onServiceStateChanged: regState=HOME cellId=123456",
        "09-24 10:11:05.000  1234  1260 I SST-0: [PHONE0] onServiceStateChanged: regState=HOME cellId=654321",
        "09-24 10:11:09.000  1234  1260 I SST-0: [PHONE0] onServiceStateChanged: regState=HOME cellId=123456",
    ])
    data = _parse(log, "--mask", rules=db / "parser-rules")
    cells = [e["fields"]["cell"] for e in data["events"] if e["event"] == "serving_cell"]
    assert cells == ["<CELL#1>", "<CELL#2>", "<CELL#1>"]  # 셀이 바뀌었다가 돌아온 관계가 보존된다
    dump = json.dumps(data, ensure_ascii=False)
    assert "123456" not in dump and "654321" not in dump
    # 마스킹하지 않으면 extractor 패턴(마스킹 이후 텍스트 기준)이 맞지 않는다
    assert not [e for e in _parse(log, rules=db / "parser-rules")["events"] if e["event"] == "serving_cell"]


def test_existing_tokens_continue_numbering_in_parse():
    log = _write([
        "09-24 10:11:00.000  1234  1260 I SST-0: [PHONE0] onServiceStateChanged: regState=HOME cellId=<CELL#1>",
        "09-24 10:11:05.000  1234  1260 I SST-0: [PHONE0] onServiceStateChanged: regState=HOME cellId=777",
    ])
    msgs = [e["msg"] for e in _parse(log, "--mask")["events"] if e["event"] is None]
    assert msgs[0].endswith("cellId=<CELL#1>") and msgs[1].endswith("cellId=<CELL#2>")


def test_site_backend_builtin_fields_are_masked():
    log = _write([
        "09-23 09:00:00.000  1234  1244 I DN-default-1: [PHONE0] onConnected: state=CONNECTED ip=10.23.45.67",
    ])
    data = _parse(log, "--mask", root=_root("site"))
    (builtin,) = [e for e in data["events"] if e["event"] == "builtin.data.ip_assigned"]
    assert builtin["fields"] == {"ip": "<IP#1>"} and builtin["source"] == "backend:site"
    assert "10.23.45.67" not in json.dumps(data)
    # 마스킹하지 않으면 원본 값 그대로 (백엔드가 원본 값을 낸다는 전제 확인)
    plain = _parse(log, root=_root("site"))
    assert [e for e in plain["events"] if e["event"] == "builtin.data.ip_assigned"][0]["fields"]["ip"] == "10.23.45.67"


# -- cut ------------------------------------------------------------------------------


def _raw_data_disabled_log() -> Path:
    """DATA-001-01 fixture에 원본 식별자가 든 줄을 섞은 로그 (fixture를 새로 뜨는 상황)."""
    lines = (SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log").read_text(
        encoding="utf-8").splitlines()
    lines.insert(1, "09-20 14:30:01.000  1234  1244 D DCM-0: [PHONE0] subscriber imsi=450081234567890 iccid=8982300123456789012")
    lines.insert(3, "09-20 14:30:03.200  1234  1244 D DSM-0: [PHONE0] data profile ip=10.23.45.67 mCi=12345678")
    return _write(lines)


def test_cut_writes_only_masked_lines():
    log = _raw_data_disabled_log()
    # 1) 지정 시각
    out = _tmp() / "cut.log"
    proc = _run("parse_logcat.py", ["cut", str(log), "--around", "2026-09-20T14:30:03+09:00",
                                    "--seconds", "2", "--context", "1", "--out", str(out),
                                    "--tz", TZ, "--year", YEAR, "--rules", str(RULES)])
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout)
    text = out.read_text(encoding="utf-8")
    assert info["masked"] is True and info["lines"] == len(text.splitlines())
    for raw in ("450081234567890", "8982300123456789012", "10.23.45.67", "12345678"):
        assert raw not in text, raw
    assert masking.new_masker().find(text) == []

    # 2) 매처 근거: 이 로그를 파싱·매칭한 1위 근거 주변을 잘라 fixture를 만들고, 그 fixture가 같은 원인을 준다
    match = _match(_parse(log, "--mask"))
    assert match["candidates"][0]["cause"] == "DATA-001-01"
    evidence = _tmp() / "match.json"
    evidence.write_text(json.dumps(match, ensure_ascii=False), encoding="utf-8")
    fixture = _tmp() / "DATA-001-01.2.log"
    proc = _run("parse_logcat.py", ["cut", str(log), "--evidence", str(evidence), "--context", "3",
                                    "--max-lines", "40", "--out", str(fixture), "--tz", TZ, "--year", YEAR])
    assert proc.returncode == 0, proc.stderr
    text = fixture.read_text(encoding="utf-8")
    assert masking.new_masker().find(text) == [] and "450081234567890" not in text
    again = _match(_parse(fixture, "--mask"), "--regress")
    assert [c["cause"] for c in again["causes"] if c["C"]] == ["DATA-001-01"]

    # 3) --max-lines: 앵커만으로 넘으면 종료 코드 2
    proc = _run("parse_logcat.py", ["cut", str(log), "--evidence", str(evidence), "--max-lines", "1",
                                    "--out", str(_tmp() / "x.log"), "--tz", TZ, "--year", YEAR])
    assert proc.returncode == 2 and "max-lines" in proc.stderr


def _line_at(sec: int, tag: str, msg: str, ms: int = 0) -> str:
    return f"09-20 14:30:{sec:02d}.{ms:03d}  1234  1244 D {tag}: [PHONE0] {msg}"


def _evidence_json(refs: list[dict | None], ts: str = "2026-09-20T05:30:10.000Z") -> Path:
    """`match.json` 모양의 최소 입력 (1위 후보의 근거만)."""
    evidence = [{"ts": ts, "tag": "DSM-0", "msg": "x", "event": None, "line_ref": ref} for ref in refs]
    path = _tmp() / "match.json"
    path.write_text(json.dumps({"candidates": [{"evidence": evidence}]}), encoding="utf-8")
    return path


def _cut(logs: list[Path], evidence: Path, *extra: str):
    out = _tmp() / "cut.log"
    proc = _run("parse_logcat.py", ["cut", *map(str, logs), "--evidence", str(evidence), "--out", str(out),
                                    "--tz", TZ, "--year", YEAR, *extra])
    return proc, out


def _dup_ts_tag_log() -> Path:
    """10번째 줄이 근거이고, 60번째 줄은 같은 시각·태그의 다른 줄이다."""
    lines = [_line_at(n, "DSM-0", f"tick {n}") for n in range(1, 60)]
    lines[9] = _line_at(10, "DSM-0", "evidence line imsi=450081234567890")
    lines.append(_line_at(10, "DSM-0", "duplicate ts tag"))
    return _write(lines)


def test_cut_evidence_line_ref_excludes_duplicate_ts_tag():
    log = _dup_ts_tag_log()
    proc, out = _cut([log], _evidence_json([{"file_index": 0, "line_no": 10}]), "--context", "2")
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout)
    text = out.read_text(encoding="utf-8")
    assert info["anchors"] == 1 and info["anchors_by"] == {"line_ref": 1, "ts_tag": 0}
    assert info["warnings"] == [] and "경고[" not in proc.stderr
    assert "evidence line" in text and "duplicate ts tag" not in text
    assert "450081234567890" not in text and masking.new_masker().find(text) == []
    assert info["lines"] == 5  # 8~12번째 줄 (앵커 앞뒤 2줄)

    # line_ref가 없는 예전 match.json은 (ts, tag)가 같은 줄을 모두 앵커로 삼는다
    proc, out = _cut([log], _evidence_json([None]), "--context", "0")
    info = json.loads(proc.stdout)
    assert proc.returncode == 0 and info["anchors"] == 2 and info["anchors_by"] == {"line_ref": 0, "ts_tag": 1}
    assert info["warnings"] == [] and "duplicate ts tag" in out.read_text(encoding="utf-8")


def test_cut_evidence_ref_mismatch_falls_back():
    log = _dup_ts_tag_log()
    short = _write([_line_at(n, "DSM-0", f"other {n}") for n in range(1, 4)])
    # parse 때와 다른 순서로 로그를 주면 (0, 10)이 입력에 없다: (ts, tag)로 앵커를 찾고 경고한다 (종료 코드 0)
    proc, out = _cut([short, log], _evidence_json([{"file_index": 0, "line_no": 10}]), "--context", "0")
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout)
    assert info["anchors_by"]["line_ref"] == 0 and info["anchors_by"]["ts_tag"] > 0 and info["anchors"] == 2
    assert [w["code"] for w in info["warnings"]] == ["evidence-ref-mismatch"]
    assert "경고[evidence-ref-mismatch]" in proc.stderr
    # 줄은 있어도 시각·태그가 근거와 다르면 그 줄을 앵커로 삼지 않는다
    proc, _ = _cut([log], _evidence_json([{"file_index": 0, "line_no": 3}]), "--context", "0")
    info = json.loads(proc.stdout)
    assert info["anchors_by"] == {"line_ref": 0, "ts_tag": 1}
    assert [w["code"] for w in info["warnings"]] == ["evidence-ref-mismatch"]


def test_cut_raw_alignment_with_form_feed():
    # str.splitlines는 \x0c에서도 줄을 끊어 raw 줄 번호가 어긋난다 (read_file의 줄 번호와 같아야 한다)
    lines = [_line_at(1, "DSM-0", "first"), _line_at(2, "DSM-0", "page\x0cbreak and\x1dmore"),
             _line_at(10, "DSM-0", "evidence after control chars")]
    log = _write(lines)
    proc, out = _cut([log], _evidence_json([{"file_index": 0, "line_no": 3}]), "--context", "0")
    assert proc.returncode == 0, proc.stderr
    assert out.read_text(encoding="utf-8").strip().endswith("evidence after control chars")
    assert json.loads(proc.stdout)["lines"] == 1


def _all_tests():
    return [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]


if __name__ == "__main__":
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
