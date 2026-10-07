#!/usr/bin/env python3
"""Phase 3 완료 기준 확인: 매처 (11-phases.md Phase 3).

테스트 입력 이벤트는 `parse_logcat.py parse` 출력에 `masked: true`를 붙인 테스트
데이터다(마스킹 연결은 Phase 4). 이슈 DB 변형은 합성 샘플을 임시 디렉토리로 복사해
고친다(샘플 트리는 건드리지 않는다).

`pytest tests/test_match_signatures.py`로도, 그냥 실행해도 돈다.
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

SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
DATA_DIR = SAMPLE / "data" / "DATA-001-no-setup-data-call"
CALL_DIR = SAMPLE / "call" / "CALL-001-volte-not-working"
TZ, YEAR = "Asia/Seoul", "2026"

_ROOT: list[Path] = []


def _root() -> Path:
    if not _ROOT or not _ROOT[0].is_dir():
        _ROOT[:] = [make_plugin_root.make()]
    return _ROOT[0]


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="tt-match-"))


def _script(name: str, args: list[str]) -> subprocess.CompletedProcess:
    root = _root()
    return subprocess.run(
        [sys.executable, str(root / "scripts" / name), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=mock_env.env_with_mocks(plugin_root=root),
    )


def _events(log: Path, db: Path = SAMPLE, around: str | None = None, masked: bool = True) -> Path:
    """parse 결과에 masked: true를 붙인 테스트 이벤트 파일."""
    args = ["parse", str(log), "--rules", str(db / "parser-rules"), "--tz", TZ, "--year", YEAR]
    args += ["--around", around] if around else ["--full"]
    proc = _script("parse_logcat.py", args)
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    doc["masked"] = masked
    out = _tmp() / "events.json"
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return out


def _match(events: Path, db: Path = SAMPLE, *extra: str, jira: dict | None = None, expect_code: int = 0):
    args = ["--db", str(db), "--events", str(events), "--top", "0", *extra]
    if jira is not None:
        path = _tmp() / "jira.json"
        path.write_text(json.dumps(jira, ensure_ascii=False), encoding="utf-8")
        args += ["--jira-meta", str(path)]
    proc = _script("match_signatures.py", args)
    assert proc.returncode == expect_code, proc.stderr
    return json.loads(proc.stdout) if proc.returncode == 0 else proc.stderr


def _copy_db() -> Path:
    db = _tmp() / "db"
    shutil.copytree(SAMPLE, db)
    return db


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path.name}: {old!r} 없음"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def _write_log(lines: list[str]) -> Path:
    path = _tmp() / "custom.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def _S(result, type_id):
    return next(t["S"] for t in result["types"] if t["type"] == type_id)


def _C(result, cause_id):
    return next((c["C"] for c in result["causes"] if c["cause"] == cause_id), None)


def _line(time: str, level: str, tag: str, msg: str, phone: int = 0) -> str:
    return f"09-20 {time}  1234  1244 {level} {tag}: [PHONE{phone}] {msg}"


OFF = "notifyDataEnabledChanged: enabled=false, reason=USER, callingPackage=com.android.settings"
REJECTED = "Data evaluation: evaluation reason:DATA_ENABLED_CHANGED, Data disallowed reasons: DATA_DISABLED, candidate profile=null"


def test_aosp_format_lines_match_data_disabled():
    # AOSP 형식(접두어 없음): DSMGR 태그 접미사로 슬롯, 평가는 `Data disallowed reasons:` 한 줄
    stamp = "09-20 14:30:0{}  1234  1244 {} {}: {}"
    log = _write_log([
        stamp.format("0.000", "D", "DSMGR-0", OFF),
        stamp.format("1.000", "W", "DNC-0", REJECTED),
    ])
    events = _events(log)
    parsed = json.loads(events.read_text(encoding="utf-8"))["events"]
    assert [e["fields"] for e in parsed if e["event"] == "data_setting_changed"] == [
        {"enabled": "false", "reason": "USER"}]
    assert [e["fields"]["reasons"] for e in parsed if e["event"] == "data_evaluation_rejected"] == ["DATA_DISABLED"]
    result = _match(events)
    assert _S(result, "DATA-001") == 1 and _C(result, "DATA-001-01") == 1


def test_apm_fixture_is_data_002_not_data_001_01():
    # 교차 확인: 비행기 모드 흔적은 DATA-002-01만 충족하고, 설정 OFF 이벤트가 없어 DATA-001-01은 C=0
    apm = SAMPLE / "data/DATA-002-data-teardown-by-user-action/fixtures/DATA-002-01.log"
    result = _match(_events(apm), SAMPLE, "--regress")
    assert _S(result, "DATA-002") == 1 and _C(result, "DATA-002-01") == 1
    assert _C(result, "DATA-001-01") in (0, None)
    # 반대로 사용자 데이터 OFF 중 연결 해제 표본은 DATA-002 증상 시그니처의 must_not_match로 S=0
    off = DATA_DIR / "fixtures/DATA-001-01.extra.1.log"
    result = _match(_events(off), SAMPLE, "--regress")
    assert _S(result, "DATA-002") == 0 and _C(result, "DATA-002-01") == 0
    assert _C(result, "DATA-001-01") == 1


# -- 분석 모드 -----------------------------------------------------------------


def test_data_disabled_is_top_candidate():
    events = _events(DATA_DIR / "fixtures/DATA-001-01.log", around="2026-09-20T14:32:10+09:00")
    result = _match(events, jira={"key": "MOCK-1101", "occurred_at": "2026-09-20T14:32:10+09:00",
                                  "sw": "MOCKA56_U1_20260915", "summary": "Data disabled 상태에서 인터넷 안 됨"})
    assert result["mode"] == "analysis"
    top = result["candidates"][0]
    assert (top["type"], top["cause"]) == ("DATA-001", "DATA-001-01")
    assert top["S"] == 1 and top["C"] == 1
    assert top["confidence"] in ("medium", "high")
    assert top["signature"] == "DATA-001-01/data-disabled"
    assert {e["signature"] for e in top["evidence"]} == {
        "DATA-001-01/data-disabled", "DATA-001/no-setup-data-call-request"}
    assert top["bonus"]["keyword"] > 0 and top["bonus"]["proximity"] > 0
    # not-a-bug 원인은 수정 판단 대상이 아니다
    assert top["fix_judgement"]["status"] == "not-a-bug" and top["fix_judgement"]["judgement"] is None
    assert all(c["cause"] != "DATA-001-02" for c in result["candidates"])


def test_cause_log_removed_gives_unresolved_type():
    lines = (DATA_DIR / "fixtures/DATA-001-01.log").read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if "notifyDataEnabledChanged" not in line]
    assert len(kept) < len(lines)
    result = _match(_events(_write_log(kept)))
    top = result["candidates"][0]
    assert top["type"] == "DATA-001" and top["cause"] is None
    assert top["S"] == 1 and top["C"] == 0
    assert "원인 미확인" in top["title"]
    assert round(top["score"], 4) == 0.4 + round(top["bonus"]["keyword"] + top["bonus"]["proximity"], 4)


def test_negative_fixtures_have_no_symptom():
    negatives = sorted(SAMPLE.glob("*/*/fixtures/*.none*.log"))
    assert len(negatives) >= 6
    for log in negatives:
        for mode in ([], ["--regress"]):
            result = _match(_events(log), SAMPLE, *mode)
            assert not [t["type"] for t in result["types"] if t["S"]], f"{log.name} {mode}"


def test_cause_without_symptom_only_in_regress():
    # 원인 시그니처(설정 OFF → 거부)는 충족되지만 같은 윈도우에 SETUP_DATA_CALL이 있어 증상은 없다.
    log = _write_log([
        _line("14:30:00.000", "D", "DSMGR-0", OFF),
        _line("14:30:01.000", "W", "DNC-0", REJECTED),
        _line("14:30:02.000", "D", "RILJ", "[0041]> SETUP_DATA_CALL apn=default"),
        _line("14:30:03.000", "D", "RILJ", "[0041]< SETUP_DATA_CALL error=NONE cid=1"),
    ])
    events = _events(log)
    analysis = _match(events)
    assert _S(analysis, "DATA-001") == 0
    assert not any(c["cause"] == "DATA-001-01" for c in analysis["candidates"])
    assert _C(analysis, "DATA-001-01") is None  # 분석 모드는 S=0 유형의 원인을 평가하지 않는다

    regress = _match(events, SAMPLE, "--regress")
    assert _S(regress, "DATA-001") == 0 and _C(regress, "DATA-001-01") == 1
    (cand,) = [c for c in regress["candidates"] if c["cause"] == "DATA-001-01"]
    assert cand["score"] == 0.6  # 참고 값

    db = _copy_db()
    _edit(db / "issue-db.config.yaml", "cause_weight: 0.6", "cause_weight: 0.5")
    changed = _match(events, db, "--regress")
    strip = lambda r: ([(t["type"], t["S"]) for t in r["types"]],  # noqa: E731
                       [(c["cause"], c["S"], c["C"]) for c in r["causes"]])
    assert strip(changed) == strip(regress)
    (cand,) = [c for c in changed["candidates"] if c["cause"] == "DATA-001-01"]
    assert cand["score"] == 0.5


def test_fix_judgement_against_fixed_in():
    events = _events(CALL_DIR / "fixtures/CALL-001-01.log")
    expected = {
        "MOCKB77_U2_20260910": "already-fixed",          # fixed_in 이전
        "MOCKB77_U2_20260920": "regression-suspected",   # 같은 빌드 (≥)
        "MOCKB77_U2_20260925": "regression-suspected",   # 이후
        "MOCKA56_U1_20260920": "undetermined",           # 다른 브랜치 규칙
        None: "undetermined",                            # 빌드 없음
    }
    for sw, judgement in expected.items():
        result = _match(events, jira={"key": "MOCK-2101", "sw": sw})
        (cand,) = [c for c in result["candidates"] if c["cause"] == "CALL-001-01"]
        assert cand["fix_judgement"]["judgement"] == judgement, (sw, cand["fix_judgement"])
        assert [r["cause"] for r in cand["related"]] == ["IMS-001-01"]
    # open 원인은 미수정 + 기존 Jira 건수
    (ims,) = [c for c in result["candidates"] if c["cause"] == "IMS-001-01"]
    assert ims["fix_judgement"]["judgement"] == "unfixed" and "1건" in ims["fix_judgement"]["message"]


def test_fix_submitted_judgement():
    from common.issuedb import Cause

    import match_signatures

    rules = yaml.safe_load((SAMPLE / "issue-db.config.yaml").read_text(encoding="utf-8"))["build_compare"]
    cause = Cause(id="X-001-01", type_id="X-001", status="active", title="t", raw={"fix": {
        "status": "fix-submitted", "ref": "MOCKCL-1",
        "fixed_in": [{"branch": "MOCKA56_U1", "build": "MOCKA56_U1_20260920"}]}})
    judge = lambda sw: match_signatures.fix_judgement(cause, sw, rules, 0)["judgement"]  # noqa: E731
    assert judge("MOCKA56_U1_20260915") == "fix-pending-build"
    assert judge("MOCKA56_U1_20260920") == "fix-insufficient"
    no_build = Cause(id="X-001-01", type_id="X-001", status="active", title="t", raw={"fix": {
        "status": "fixed", "fixed_in": [{"branch": "MOCKA56_U1"}]}})
    assert match_signatures.fix_judgement(no_build, "MOCKA56_U1_20260920", rules, 0)["judgement"] == "undetermined"


def test_status_filter_and_pending_causes():
    db = _copy_db()
    type_md = db / "data/DATA-001-no-setup-data-call/type.md"
    _edit(type_md, "  - id: DATA-001-01\n    status: active", "  - id: DATA-001-01\n    status: deprecated")
    _edit(type_md, "tags: [data-evaluation]", """  - id: DATA-001-03
    status: active
    title: 원인 미정 (수동 기록)
    description: 수동 기록으로 추가한 원인
    signatures: []
    signatures_pending: true
    recovery_signatures: []
    scenario_signatures: []
    resolution: 확인 중
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    android_versions: []
    code_refs: []
tags: [data-evaluation]""")
    for mode in ([], ["--regress"]):
        result = _match(_events(DATA_DIR / "fixtures/DATA-001-01.log", db), db, *mode)
        assert not any(c["cause"] == "DATA-001-01" for c in result["candidates"]), mode
        assert _C(result, "DATA-001-01") is None
        assert _C(result, "DATA-001-03") is None
        assert result["pending_causes"] == [
            {"type": "DATA-001", "cause": "DATA-001-03", "title": "원인 미정 (수동 기록)"}]
        assert result["candidates"][0]["cause"] is None  # 남은 원인 없음 → 원인 미확인


# -- 회귀·검증 모드 --------------------------------------------------------------


def test_regress_mode_disables_bonus_and_feedback():
    db = _copy_db()
    _edit(db / "issue-db.config.yaml", "min_samples: 5", "min_samples: 1")
    events = _events(DATA_DIR / "fixtures/DATA-001-01.log", db, around="2026-09-20T14:32:10+09:00")
    jira = {"occurred_at": "2026-09-20T14:30:05+09:00", "summary": "Data disabled"}

    analysis = _match(events, db, jira=jira)
    top = analysis["candidates"][0]
    assert analysis["feedback_weight"] is True and analysis["bonus"] is True
    # MOCK-1104: DATA-001-01/data-disabled가 1위로 제시됐고 unresolved → 수락률 0/1 → × 0.5
    assert top["feedback"] == {"accepted": 0, "total": 1, "rate": 0.0, "applied": True}
    assert top["score"] == 0.5
    assert analysis["range"]["start"].startswith("2026-09-20T05:27:10")

    off = _match(events, db, "--no-feedback-weight", jira=jira)
    assert off["feedback_weight"] is False and off["candidates"][0]["score"] == 1.0

    regress = _match(events, db, "--regress", jira=jira)
    top = regress["candidates"][0]
    assert regress["mode"] == "regress" and regress["bonus"] is False and regress["feedback_weight"] is False
    assert top["bonus"] == {"proximity": 0.0, "keyword": 0.0} and top["feedback"]["applied"] is False
    assert top["score"] == 1.0 and top["fix_judgement"] is None
    doc = json.loads(events.read_text(encoding="utf-8"))
    assert regress["range"]["start"].startswith(doc["coverage"]["first_ts"][:19])  # 파일 전체
    assert regress["range"]["end"].startswith(doc["coverage"]["last_ts"][:19])


def test_manual_feedback_is_not_counted():
    from common import issuedb

    stats = issuedb.acceptance(issuedb.load(SAMPLE).feedback)
    assert stats == {"DATA-001-02/roaming-disabled": (1, 1), "DATA-001-01/data-disabled": (0, 1)}


# -- 슬롯·순서·타임아웃 ------------------------------------------------------------


def test_cross_slot_same_phone():
    log = DATA_DIR / "fixtures/DATA-001.none.2.log"
    analysis = _match(_events(log))
    assert _S(analysis, "DATA-001") == 0 and not analysis["candidates"]
    assert _C(_match(_events(log), SAMPLE, "--regress"), "DATA-001-01") == 0

    db = _copy_db()
    _edit(db / "data/DATA-001-no-setup-data-call/type.md",
          "        sequence: [setting-off, rejected]\n        same_phone: true",
          "        sequence: [setting-off, rejected]\n        same_phone: false")
    assert _C(_match(_events(log, db), db, "--regress"), "DATA-001-01") == 1


def test_symptom_must_not_match_is_per_slot():
    # 슬롯 1의 SETUP_DATA_CALL은 슬롯 0의 증상을 깨지 않는다 (same_phone 기본 true).
    log = _write_log([
        _line("14:30:00.000", "D", "DSMGR-0", OFF),
        _line("14:30:01.000", "W", "DNC-0", REJECTED),
        _line("14:30:02.000", "D", "RILJ", "[0041]> SETUP_DATA_CALL apn=default", phone=1),
    ])
    result = _match(_events(log))
    assert _S(result, "DATA-001") == 1 and result["candidates"][0]["cause"] == "DATA-001-01"


def test_sequence_order_matters():
    in_order = _write_log([
        _line("14:30:00.000", "D", "DSMGR-0", OFF),
        _line("14:30:02.000", "W", "DNC-0", REJECTED),
    ])
    reversed_ = _write_log([
        _line("14:30:00.000", "W", "DNC-0", REJECTED),
        _line("14:30:02.000", "W", "DNC-0", REJECTED),
        _line("14:30:05.000", "D", "DSMGR-0", OFF),
    ])
    assert _C(_match(_events(in_order)), "DATA-001-01") == 1
    result = _match(_events(reversed_))
    assert _S(result, "DATA-001") == 1 and _C(result, "DATA-001-01") == 0
    assert result["candidates"][0]["cause"] is None


def test_window_sec_limits_span():
    far = _write_log([
        _line("14:30:00.000", "D", "DSMGR-0", OFF),
        _line("14:31:30.000", "W", "DNC-0", REJECTED),  # 90초 뒤 > window_sec 60
    ])
    assert _C(_match(_events(far), SAMPLE, "--regress"), "DATA-001-01") == 0


def test_slow_regex_times_out_and_others_continue():
    db = _copy_db()
    _edit(db / "issue-db.config.yaml", "pattern_timeout_ms: 2000", "pattern_timeout_ms: 300")
    _edit(db / "data/DATA-001-no-setup-data-call/type.md",
          "      - id: roaming-disabled\n",
          "      - id: slow\n        must_match: ['(a+)+$']\n        window_sec: 60\n"
          "      - id: roaming-disabled\n")
    lines = (DATA_DIR / "fixtures/DATA-001-01.log").read_text(encoding="utf-8").splitlines()
    lines.append("09-20 14:30:40.000  1234  1244 D DNC-0: " + "a" * 40 + "!")
    events = _events(_write_log(lines), db)
    for mode in ([], ["--regress"]):
        result = _match(events, db, *mode)
        assert [e["signature"] for e in result["errors"]] == ["DATA-001-02/slow"], result["errors"]
        assert "timeout" in result["errors"][0]["error"]
        assert result["candidates"][0]["cause"] == "DATA-001-01"


# -- 입력 검사 ------------------------------------------------------------------


def test_unmasked_input_is_rejected():
    events = _events(DATA_DIR / "fixtures/DATA-001-01.log", masked=False)
    err = _match(events, expect_code=2)
    assert "masked" in err


def test_db_path_is_required():
    events = _events(DATA_DIR / "fixtures/DATA-001-01.log")
    proc = subprocess.run(
        [sys.executable, str(_root() / "scripts" / "match_signatures.py"), "--events", str(events)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=mock_env.env_with_mocks(plugin_root=_root()), cwd=_tmp(),
    )
    assert proc.returncode == 2 and "--db" in proc.stderr


def test_bad_signature_is_usage_error():
    db = _copy_db()
    _edit(db / "data/DATA-001-no-setup-data-call/type.md",
          "sequence: [setting-off, rejected]", "sequence: [setting-off, nope]")
    err = _match(_events(DATA_DIR / "fixtures/DATA-001-01.log"), db, "--regress", expect_code=2)
    assert "sequence" in err


# -- 동점 정렬 (R8) --------------------------------------------------------------


def _two_cluster_log() -> Path:
    """60초(window_sec)보다 떨어진 두 군집: A(14:30) DATA-001-01, B(14:33) DATA-001-02. SETUP_DATA_CALL 없음."""
    return _write_log([
        _line("14:30:03.000", "D", "DSMGR-0", OFF),
        _line("14:30:04.900", "W", "DNC-0", REJECTED),
        _line("14:33:00.000", "D", "SST-0", "onRoamingOn: roaming=true"),
        _line("14:33:02.700", "W", "DNC-0", "Data evaluation: evaluation reason:ROAMING_ENABLED_CHANGED, Data disallowed reasons: ROAMING_DISABLED, candidate profile=null"),
    ])


def _jira_at(occurred_at: str) -> dict:
    return {"key": "MOCK-R8", "occurred_at": occurred_at, "sw": "MOCKA56_U1_20260915", "summary": ""}


def test_full_match_ties_are_ordered_by_proximity():
    events = _events(_two_cluster_log(), around="2026-09-20T14:31:30+09:00")
    near = {}
    for name, at in (("B", "2026-09-20T14:33:02+09:00"), ("A", "2026-09-20T14:30:05+09:00")):
        result = _match(events, SAMPLE, "--no-feedback-weight", jira=_jira_at(at))
        cands = [c for c in result["candidates"] if c["cause"] in ("DATA-001-01", "DATA-001-02")]
        assert len(cands) == 2
        assert all(c["S"] == 1 and c["C"] == 1 and c["score"] == 1.0 for c in cands)
        near[name] = cands
    assert [c["cause"] for c in near["B"]] == ["DATA-001-02", "DATA-001-01"]
    assert [c["cause"] for c in near["A"]] == ["DATA-001-01", "DATA-001-02"]
    for cands in near.values():
        assert cands[0]["bonus"]["proximity"] > cands[1]["bonus"]["proximity"]


def test_regress_order_unchanged_by_tiebreak():
    events = _events(_two_cluster_log(), around="2026-09-20T14:31:30+09:00")
    results = [_match(events, SAMPLE, "--regress", jira=_jira_at(at))
               for at in ("2026-09-20T14:33:02+09:00", "2026-09-20T14:30:05+09:00")]
    for result in results:
        cands = result["candidates"]
        assert cands and all(c["bonus"] == {"proximity": 0.0, "keyword": 0.0} for c in cands)
        assert cands == sorted(cands, key=lambda c: (-c["score"], c["type"], c["cause"] or ""))
    for key in ("candidates", "types", "causes"):
        assert json.dumps(results[0][key], sort_keys=True) == json.dumps(results[1][key], sort_keys=True)


def _tie_cands(result: dict) -> list[dict]:
    return [c for c in result["candidates"] if c["cause"] in ("DATA-001-01", "DATA-001-02")]


def test_failed_step_feeds_keyword_bonus_only_in_analysis_mode():
    events = _events(_two_cluster_log(), around="2026-09-20T14:31:30+09:00")
    base = {"key": "MOCK-R8", "sw": "MOCKA56_U1_20260915", "summary": ""}       # occurred_at 없음 → 근접 0
    plain = _tie_cands(_match(events, SAMPLE, "--no-feedback-weight", jira=base))
    assert [c["cause"] for c in plain] == ["DATA-001-01", "DATA-001-02"]
    withstep = _tie_cands(_match(events, SAMPLE, "--no-feedback-weight",
                                 jira={**base, "failed_step": "3 | Enable roaming data"}))
    assert [c["cause"] for c in withstep] == ["DATA-001-02", "DATA-001-01"]
    assert withstep[0]["bonus"]["keyword"] > withstep[1]["bonus"]["keyword"]
    reg = _tie_cands(_match(events, SAMPLE, "--regress", jira={**base, "failed_step": "3 | Enable roaming data"}))
    assert [c["cause"] for c in reg] == ["DATA-001-01", "DATA-001-02"]
    assert all(c["bonus"] == {"proximity": 0.0, "keyword": 0.0} for c in reg)


def test_version_match_is_display_only():
    events = _events(_two_cluster_log(), around="2026-09-20T14:31:30+09:00")
    base = {"key": "MOCK-V1", "sw": "MOCKA56_U1_20260915", "summary": ""}

    def run(**extra):
        return {c["cause"]: c for c in _tie_cands(_match(events, SAMPLE, "--no-feedback-weight", jira={**base, **extra}))}
    none, same, other, dotted = (run(), run(android_version="16"), run(android_version="15"), run(android_version="16.0"))
    assert none["DATA-001-01"]["version_match"] is None and none["DATA-001-01"]["android_versions"] == ["16", "17"]
    assert same["DATA-001-01"]["version_match"] is True and dotted["DATA-001-01"]["version_match"] is True
    assert other["DATA-001-01"]["version_match"] is False
    assert other["DATA-001-02"]["version_match"] is None and other["DATA-001-02"]["android_versions"] == []   # 전 버전
    for odd in ("Android 16", "Baklava", "17 QPR1", "16 (B)"):   # 정수·정수.정수 꼴이 아니면 비교하지 않는다
        assert run(android_version=odd)["DATA-001-01"]["version_match"] is None
    for r in (same, other):   # 순위·score·S·C 불변
        key = lambda x: [(k, c["score"], c["bonus"], c["S"], c["C"]) for k, c in x.items()]  # noqa: E731
        assert key(r) == key(none)


# -- 근거 출처 (line_ref, event_index) ----------------------------------------------


def _all_evidence(result: dict) -> list[dict]:
    out = [e for c in result["candidates"] for e in c["evidence"]]
    return out + [e for t in result["types"] for e in t["evidence"]]


def _check_provenance(result: dict, doc: dict) -> int:
    """모든 근거의 `event_index`가 입력 문서의 같은 이벤트를 가리킨다."""
    evidence = _all_evidence(result)
    for e in evidence:
        src = doc["events"][e["event_index"]]
        assert (src["ts"], src["tag"], src["event"], src["line_ref"]) == (e["ts"], e["tag"], e["event"], e["line_ref"])
    return len(evidence)


def test_evidence_has_line_ref_and_event_index():
    events = _events(DATA_DIR / "fixtures/DATA-001-01.log")
    doc = json.loads(events.read_text(encoding="utf-8"))
    result = _match(events)
    assert _check_provenance(result, doc) >= 2
    raw = (DATA_DIR / "fixtures/DATA-001-01.log").read_text(encoding="utf-8").split("\n")
    for e in _all_evidence(result):
        assert e["line_ref"]["file_index"] == 0
        assert e["tag"] in raw[e["line_ref"]["line_no"] - 1]


def test_event_index_with_unsorted_input():
    import random

    events = _events(DATA_DIR / "fixtures/DATA-001-01.log")
    doc = json.loads(events.read_text(encoding="utf-8"))
    base = _match(events)
    shuffled = dict(doc, events=random.Random(7).sample(doc["events"], len(doc["events"])))
    assert shuffled["events"] != doc["events"]
    path = _tmp() / "events.json"
    path.write_text(json.dumps(shuffled, ensure_ascii=False), encoding="utf-8")
    result = _match(path)
    assert _check_provenance(result, shuffled) >= 2  # 입력 문서 순서 기준 순번이다 (정렬된 사본의 순번이 아니다)
    key = lambda r: ([(t["type"], t["S"]) for t in r["types"]],  # noqa: E731
                     [(c["cause"], c["S"], c["C"]) for c in r["causes"]],
                     [(c["cause"], c["score"]) for c in r["candidates"]])
    assert key(result) == key(base)


def test_duplicate_ts_tag_evidence_is_distinguished():
    # 같은 시각·태그의 줄이 둘 있고 시그니처에 맞는 것은 둘째 줄뿐이다. 근거의 줄 위치가 그 줄을 가리킨다.
    log = _write_log([
        _line("14:30:00.000", "D", "DSMGR-0", "mIsDataEnabled=true, prevDataEnabled=false"),
        _line("14:30:00.000", "D", "DSMGR-0", OFF),
        _line("14:30:02.000", "W", "DNC-0", REJECTED),
    ])
    events = _events(log)
    result = _match(events)
    assert _C(result, "DATA-001-01") == 1
    (off,) = [e for e in result["candidates"][0]["evidence"] if e["tag"] == "DSMGR-0"]
    assert off["line_ref"] == {"file_index": 0, "line_no": 2}
    assert _check_provenance(result, json.loads(events.read_text(encoding="utf-8"))) >= 2


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
