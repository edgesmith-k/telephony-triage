#!/usr/bin/env python3
"""Phase 10 완료 기준 확인: 검증 (11-phases.md Phase 10, 05-verification.md §5.12).

- 규칙 검증(R1~R6)은 샘플 이슈 DB를 git 레포로 만든 뒤 워킹 트리를 고치고 `db_verify rules --changed HEAD`로
  돌린다(계획을 적용한 트리와 같은 의미 비교를 쓴다). 계획 경로(`--plan --draft`, `db_pr stage`)는 `Workspace`로 본다.
- 코드 수정 검증은 `issue-db-verify`(CALL-001-01 fix-submitted)와 입력 로그
  `verify-logs`(`tests/helpers/make_variant_dbs.py`가 테스트 때 만든다, `runner.variant_db()`)를 쓴다.

`pytest tests/test_db_verify.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import yaml
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, copy_db, edit, git, git_db, run, run_json, variant_db  # noqa: E402
from workspace import PLANS, Workspace  # noqa: E402

VERIFY_DB = variant_db("issue-db-verify")
LOGS = variant_db("verify-logs")
PENDING_DB = variant_db("issue-db-pending")
CALL = "call/CALL-001-volte-not-working"
DATA = "data/DATA-001-no-setup-data-call"
IMS = "ims/IMS-001-ims-registration-failed"
SIM_LOG = PENDING_DB / DATA / "fixtures/DATA-001-03.log"
NORMAL_LOG = SAMPLE / DATA / "fixtures/DATA-001.none.log"
BUILD = "MOCKB77_U2_20260925"

CALL_CAUSE_SIG = ("        must_event:\n          - {id: regfail, event: ims_registration_failed}\n"
                  "          - {id: dial, event: ims_dial_attempt, fields: {registered: 'false'}}\n"
                  "        sequence: [regfail, dial]\n        window_sec: 300\n")
RESOLVED_LOG = """09-27 10:00:00.000  1234  1244 I UiccController: [PHONE0] SIM state changed: LOADED
09-27 10:00:01.000  1234  1244 I DNC-0: [PHONE0] onEvaluateNetworkRequests: reason=SIM_LOADED
09-27 10:00:01.200  1234  1244 I DNC-0: [PHONE0] evaluation result: ALLOWED reasons=[]
09-27 10:00:01.500  1234  1244 D RILJ: [PHONE0] [0051]> SETUP_DATA_CALL apn=default
09-27 10:00:02.400  1234  1244 D RILJ: [PHONE0] [0051]< SETUP_DATA_CALL error=NONE cid=<CELL#1>
"""
SIM_RECOVERY = [{"id": "sim-loaded-then-allowed",
                 "must_event": [{"id": "loaded", "event": "sim_state_changed", "fields": {"state": "LOADED"}},
                                {"id": "allowed", "event": "data_evaluation_allowed"}],
                 "sequence": ["loaded", "allowed"], "window_sec": 60}]


def rules(db: Path, *extra, expect=(0, 1, 3)) -> tuple[int, dict, dict]:
    proc = run("db_verify.py", ["rules", "--changed", "HEAD", "--db", db, *extra])
    assert proc.returncode in (expect if isinstance(expect, tuple) else (expect,)), proc.stderr[-2000:]
    out = json.loads(proc.stdout)
    return proc.returncode, {r["id"]: r for r in out["rules"]}, out


def front(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n")[1])


def cause_of(type_md: Path, cause_id: str) -> dict:
    return next(c for c in front(type_md)["causes"] if c["id"] == cause_id)


def verify_fix(db: Path, log: str, build: str | None = BUILD, cause: str = "CALL-001-01", expect=0) -> dict:
    args = ["fix", "--cause", cause, LOGS / log, "--db", db] + (["--build", build] if build else [])
    return run_json("db_verify.py", args, expect=expect) if expect == 0 else run("db_verify.py", args)


def apply_plan(db: Path, operations: list[dict], source: str = "verify-fix", expect=0) -> dict:
    plan = {"source": source, "schema_version": 1, "started_at": "2026-09-29T10:00+09:00",
            "base_sha": "0" * 40, "jira": None, "operations": operations,
            "commit_message": "[CALL-001-01] verify-fix", "pr": {"number": None, "branch": "x", "head_sha": None},
            "included_pending": []}
    path = db.parent / "job" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return run_json("db_add.py", ["apply", path, "--db", db, "--user", "mock-user1"], expect=expect)


def fix_plan(ops: list[dict], branch: str) -> dict:
    return {"source": "verify-fix", "schema_version": 1, "started_at": "2026-09-29T10:00+09:00", "jira": None,
            "operations": ops, "commit_message": f"[CALL-001-01] verify-fix: {branch}",
            "pr": {"number": None, "branch": branch, "head_sha": None}, "included_pending": []}


# -- R1~R6 ---------------------------------------------------------------------------------


def test_broad_cause_signature_and_widened_fixed_cause_are_blocked():
    """너무 넓은 원인 시그니처: 음성 fixture·수정 후 fixture에서 C=1 → R3·R4 차단.
    같은 카테고리 다른 유형의 양성 fixture에서 C=1 → R3 차단과 allow-cause 초안."""
    db = git_db()
    edit(db / CALL / "type.md", CALL_CAUSE_SIG, "        must_event:\n          - {event: ims_dial_attempt}\n"
                                                "        window_sec: 300\n")
    code, rows, out = rules(db)
    assert code == 1
    assert [c["key"] for c in out["changes"]["signatures"]] == ["CALL-001-01/ims-not-registered-on-dial"]
    assert rows["R1"]["status"] == "pass" and rows["R2"]["status"] == "pass"
    hits = {h["fixture"] for c in rows["R3"]["checks"] for h in c.get("hits", [])}
    assert rows["R3"]["status"] == "fail"
    assert f"{CALL}/fixtures/CALL-001.none.log" in hits
    assert f"{CALL}/fixtures/CALL-001-01.fixed.MOCKB77_U2_20260920.log" in hits      # 수정 후 감시
    assert f"{CALL}/fixtures/CALL-001-01.fixed.MOCKB77_U2_20260920.log" in rows["R4"]["targets"]

    db = git_db()
    new = db / "data/DATA-002-sim-rejected"
    (new / "fixtures").mkdir(parents=True)
    (new / "type.md").write_text(DATA_002, encoding="utf-8", newline="\n")
    shutil.copyfile(SIM_LOG, new / "fixtures/DATA-002-01.log")
    code, rows, _ = rules(db)
    assert code == 1 and rows["R3"]["status"] == "fail"
    check = next(c for c in rows["R3"]["checks"] if c["target"] == "DATA-002-01")
    assert f"{DATA}/fixtures/DATA-001-01.log" in {h["fixture"] for h in check["hits"]}
    assert {"op": "allow-cause", "fixture": "fixtures/DATA-001-01.log", "cause": "DATA-002-01"} in check["allow_cause_drafts"]


def test_cross_category_hit_needs_also_allowed_and_scoring_does_not_matter():
    """다른 카테고리 양성 fixture에서 C=1 → R4 실패 + allow-cause 초안. also_allowed에 넣으면 R2·R3·R4 통과,
    also_allowed에 없는 fixture는 여전히 실패. scoring 값을 바꿔도 R2·R3·R4·db_regress 결과가 같다."""
    db = git_db()
    edit(db / CALL / "type.md", CALL_CAUSE_SIG, "        must_event:\n          - {event: ims_registration_failed}\n"
                                                "        window_sec: 300\n")
    code, rows, _ = rules(db)
    assert code == 1 and rows["R4"]["status"] == "fail"
    positive = f"{IMS}/fixtures/IMS-001-01.log"
    recurrence = f"{IMS}/fixtures/IMS-001-01.recurrence.MOCKB77_U2_20260920.log"
    assert set(rows["R4"]["targets"]) == {positive, recurrence}
    drafts = [d for f in rows["R4"]["failures"] for d in f["allow_cause_drafts"]]
    draft = {"op": "allow-cause", "fixture": "fixtures/IMS-001-01.log", "cause": "CALL-001-01"}
    assert draft in drafts
    plan = {"source": "analyze", "schema_version": 1, "started_at": "2026-10-05T10:00+09:00",
            "base_sha": "0123456", "operations": [dict(draft)]}
    from dbadd.core import validate_plan      # 초안은 그대로 계획에 붙일 수 있어야 한다 (additionalProperties: false)
    validate_plan(plan, SAMPLE)

    def view(rows_):
        return {k: (rows_[k]["status"], rows_[k]["targets"]) for k in ("R2", "R3", "R4")}

    def regress():
        out = run_json("db_regress.py", ["--all", "--db", db], expect=(0, 1))
        return [(r["fixture"], r["status"], r["C"], r["S"]) for r in out["results"]]

    before, before_regress = view(rows), regress()
    edit(db / "issue-db.config.yaml", "  cause_weight: 0.6", "  cause_weight: 0.5")
    edit(db / "issue-db.config.yaml", "confidence: {high: 0.9, medium: 0.6}", "confidence: {high: 0.9, medium: 0.7}")
    _, rows, _ = rules(db)
    assert view(rows) == before and regress() == before_regress

    expect = db / IMS / "fixtures/IMS-001-01.expect.yaml"
    expect.write_text(expect.read_text(encoding="utf-8") + "also_allowed: [CALL-001-01]\n", encoding="utf-8")
    code, rows, _ = rules(db)
    assert code == 1 and rows["R4"]["targets"] == [recurrence]      # also_allowed에 없는 fixture는 여전히 실패
    rexpect = db / IMS / "fixtures/IMS-001-01.recurrence.MOCKB77_U2_20260920.expect.yaml"
    text = rexpect.read_text(encoding="utf-8") if rexpect.is_file() else ""
    rexpect.write_text(text + "also_allowed: [CALL-001-01]\n", encoding="utf-8")
    code, rows, _ = rules(db)
    assert code == 0, rows
    assert [rows[k]["status"] for k in ("R2", "R3", "R4")] == ["pass", "pass", "pass"]


def test_retemp_drafts_maps_real_ids_back_to_plan_temp_ids():
    from db_verify import _retemp_drafts
    tree = {"rules": [{"checks": [{"allow_cause_drafts": [{"op": "allow-cause", "fixture": "fixtures/a.log",
                                                           "cause": "DATA-001-03"}],
                                   "hits": [{"allow_cause_draft": {"op": "allow-cause", "fixture": "fixtures/b.log",
                                                                   "cause": "DATA-001-03"}},
                                            {"allow_cause_draft": None}]}]}],
            "reasons": [{"cause": "DATA-001-03", "message": "DATA-001-03도 C=1이다"}],
            "other": {"op": "allow-cause", "fixture": "fixtures/c.log", "cause": "CALL-001-01"}}
    _retemp_drafts(tree, {"DATA-001-03": "NEW-CAUSE-1"})
    check = tree["rules"][0]["checks"][0]
    assert check["allow_cause_drafts"][0]["cause"] == "NEW-CAUSE-1"
    assert check["hits"][0]["allow_cause_draft"]["cause"] == "NEW-CAUSE-1"
    assert tree["reasons"][0]["cause"] == "DATA-001-03"             # allow-cause 초안이 아닌 항목은 그대로
    assert tree["other"]["cause"] == "CALL-001-01"                   # 매핑에 없는 ID는 그대로


def test_retemp_drafts_covers_all_op_id_keys():
    from db_verify import _retemp_drafts
    back = {"DATA-001-03": "NEW-CAUSE-1", "DATA-002-01": "NEW-CAUSE-2"}
    ops = [{"op": "add-fixture", "for": "DATA-001-03", "kind": "fixed", "path": "p"},
           {"op": "verify-fix", "cause": "DATA-001-03", "result": "passed", "verification": {"note": "DATA-001-03"}},
           {"op": "merge", "a": "DATA-001-03", "b": "DATA-002-01", "id": "DATA-002-01", "owner": "DATA-001-03"},
           {"op": "verify-fix", "cause": "CALL-001-01"}]
    tree = {"suggested_ops": ops, "cause": "DATA-001-03", "reason": "DATA-001-03 충족", "for": "DATA-001-03"}
    _retemp_drafts(tree, back)
    assert ops[0]["for"] == "NEW-CAUSE-1" and ops[1]["cause"] == "NEW-CAUSE-1"
    assert (ops[2]["a"], ops[2]["b"], ops[2]["id"], ops[2]["owner"]) == ("NEW-CAUSE-1", "NEW-CAUSE-2", "NEW-CAUSE-2", "NEW-CAUSE-1")
    assert ops[3]["cause"] == "CALL-001-01"                         # 매핑에 없는 ID
    assert ops[1]["verification"]["note"] == "DATA-001-03"          # 설명 문자열은 그대로
    assert tree["cause"] == "DATA-001-03" and tree["reason"] == "DATA-001-03 충족" and tree["for"] == "DATA-001-03"   # op가 아닌 dict


def test_script_honours_subprocess_env(monkeypatch):
    import db_verify
    from common import checks
    calls = []
    monkeypatch.setattr(checks, "_run_subprocess", lambda name, argv, env: calls.append((name, argv, env)) or (0, "{}", ""))
    monkeypatch.setattr(checks, "run_in_process", lambda name, argv: calls.append(("inproc", name)) or (0, "{}", ""))
    monkeypatch.setenv("TT_SCRIPT_SUBPROCESS", "1")
    proc = db_verify._script("db_add.py", ["apply", "p"], "/root")
    assert calls == [("db_add.py", ["apply", "p", "--plugin-root", "/root"], None)] and proc.returncode == 0 and proc.stdout == "{}"
    monkeypatch.delenv("TT_SCRIPT_SUBPROCESS")
    calls.clear()
    db_verify._script("db_add.py", ["apply", "p"], None)
    assert calls == [("inproc", "db_add.py")]


def test_new_type_symptom_hitting_other_negative_fails_r3():
    db = git_db()
    new = db / "call/CALL-002-dial-seen"
    new.mkdir(parents=True)
    (new / "type.md").write_text(CALL_002, encoding="utf-8", newline="\n")
    code, rows, _ = rules(db)
    assert code == 1 and rows["R3"]["status"] == "fail"
    check = next(c for c in rows["R3"]["checks"] if c["target"] == "CALL-002")
    assert check["kind"] == "symptom" and check["signatures"] == ["CALL-002/dial-seen"]
    assert f"{CALL}/fixtures/CALL-001.none.log" in {h["fixture"] for h in check["hits"]}
    assert rows["R1"]["status"] == "skipped" and rows["R1"]["review_required"]      # 새 유형에 양성 fixture 없음


def test_extractor_change_selects_dependents_and_event_change_needs_approval():
    """extractor만 바꿔도 참조하는 시그니처가 R1·R2 대상. 기존 이벤트를 바꾸는 수정은 R5 needs-approval(3)."""
    db = git_db()
    rules_file = db / "parser-rules/extractors.yaml"
    edit(rules_file, "      - 'dial:\\s*isVolteEnabled=(?P<volte>true|false)\\s+imsRegistered=(?P<registered>true|false)'\n",
         "      - 'dial:\\s*isVolteEnabled=(?P<volte>true|false)\\s+imsRegistered=(?P<registered>true|false)'\n"
         "      - 'dial\\(\\):\\s*volte=(?P<volte>true|false)\\s+registered=(?P<registered>true|false)'\n")
    code, rows, out = rules(db)
    assert code == 0, rows
    why = {c["key"]: c["why"] for c in out["changes"]["signatures"]}
    assert why["CALL-001-01/ims-not-registered-on-dial"] == ["depends:extractors:ims-dial-attempt"]
    assert "CALL-001/volte-call-not-established" in why
    assert "CALL-001-01/ims-not-registered-on-dial" in rows["R1"]["targets"]
    assert "CALL-001-01" in rows["R2"]["targets"] and rows["R2"]["status"] == "pass"
    assert rows["R5"]["status"] == "pass"

    db = git_db()
    edit(db / "parser-rules/extractors.yaml", "    event: ims_registered\n    fields: [transport]",
         "    event: ims_registered\n    fields: []")
    code, rows, _ = rules(db)
    assert code == 3, rows
    assert rows["R4"]["status"] == "pass" and rows["R5"]["status"] == "needs-approval"
    assert f"{CALL}/fixtures/CALL-001.none.log" in rows["R5"]["targets"]
    diff = run_json("db_regress.py", ["--events-diff", "HEAD", "--db", db])
    assert diff["summary"]["existing_changed"] and diff["summary"]["changed"] > 0
    changed = next(r for r in diff["fixtures"] if r["fixture"] == f"{CALL}/fixtures/CALL-001.none.log")["changed"][0]
    assert changed["event"] == "ims_registered" and changed["fields_before"] == {"transport": "LTE"}
    assert changed["fields_after"] == {}


def test_trace_signature_matching_every_negative_fails_r1():
    """모든 음성 fixture에 맞는 scenario는 R1 흔적 검사 실패. 음성 fixture가 없으면 skipped(리뷰 대상), pass 아님."""
    broad = ("    scenario_signatures:\n      - id: any-ims-line\n        must_match: ['Ims']\n        window_sec: 600\n"
             "      - id: volte-dial-attempt")
    db = git_db()
    edit(db / CALL / "type.md", "    scenario_signatures:\n      - id: volte-dial-attempt", broad)
    code, rows, _ = rules(db)
    assert code == 1 and rows["R1"]["status"] == "fail"
    check = next(c for c in rows["R1"]["checks"] if c["target"] == "CALL-001-01/any-ims-line")
    assert check["part"] == "trace" and "음성 fixture 2개 전부" in check["reason"]

    db = git_db()
    for path in (db / CALL / "fixtures").glob("CALL-001.none*"):
        path.unlink()
    git(db, "add", "-A")
    git(db, "commit", "-qm", "call 음성 fixture 없음")
    edit(db / CALL / "type.md", "    scenario_signatures:\n      - id: volte-dial-attempt", broad)
    code, rows, _ = rules(db)
    assert rows["R1"]["status"] == "skipped" and rows["R1"]["reason"] == "음성 fixture 없음"
    assert rows["R1"]["review_required"] is True and code == 0


def test_new_cause_without_fixture_and_pending_cause_are_skipped_not_passed():
    db = git_db()
    edit(db / DATA / "type.md", "tags: [data-evaluation]\n---", DATA_001_03 + "tags: [data-evaluation]\n---")
    _, rows, out = rules(db)
    assert out["changes"]["new_causes"] == ["DATA-001-03"]
    for rid in ("R1", "R2"):
        assert rows[rid]["status"] == "skipped" and rows[rid]["reason"] == "fixture 없음"
        assert rows[rid]["review_required"] is True
    assert rows["R3"]["status"] == "pass"

    db = git_db()
    shutil.copyfile(PENDING_DB / DATA / "type.md", db / DATA / "type.md")
    shutil.copyfile(SIM_LOG, db / DATA / "fixtures/DATA-001-03.log")
    code, rows, _ = rules(db)
    assert code == 0
    for rid in ("R1", "R2", "R3"):
        assert rows[rid]["status"] == "skipped" and rows[rid]["reason"] == "시그니처 없음(pending)", rows[rid]
        assert rows[rid]["review_required"] is False
    assert rows["R4"]["status"] == "pass"


# -- 코드 수정 검증 ---------------------------------------------------------------------------


def test_fix_judgements_on_fix_submitted_cause():
    fixed = verify_fix(VERIFY_DB, "call-fixed.log")
    assert fixed["judgement"] == "passed" and fixed["build_check"]["status"] == "after"
    assert fixed["trace"]["signature"] == "CALL-001-01/volte-dial-attempt"
    assert [op["op"] for op in fixed["suggested_ops"]] == ["add-fixture", "verify-fix"]
    failed = verify_fix(VERIFY_DB, "call-recurrence.log")
    assert failed["judgement"] == "failed" and failed["C"] == 1
    partial = verify_fix(VERIFY_DB, "call-partial.log")
    assert partial["judgement"] == "partial" and partial["C"] == 0 and partial["S"] == 1
    assert [o["cause"] for o in partial["other_candidates"]] == ["CALL-001-02"]
    unknown = verify_fix(VERIFY_DB, "call-noscenario.log")
    assert unknown["judgement"] == "unknown" and "시나리오 흔적 없음" in unknown["reason"]
    assert unknown["suggested_ops"] == []

    early = verify_fix(VERIFY_DB, "call-fixed.log", build="MOCKB77_U2_20260910", expect=2)
    assert early.returncode == 2 and "이전" in early.stderr
    undetermined = verify_fix(VERIFY_DB, "call-fixed.log", build="OTHER_BUILD_1")
    assert undetermined["build_check"]["status"] == "undetermined"

    res = run_json("db_verify.py", ["resolution", "--cause", "CALL-001-02", LOGS / "call-noscenario.log",
                                    "--db", VERIFY_DB])
    assert res["judgement"] == "unknown" and "시나리오 흔적 없음" in res["reason"]      # recovery 없음 + 흔적 없음
    res = run_json("db_verify.py", ["resolution", "--cause", "CALL-001-01", LOGS / "call-fixed.log", "--db", VERIFY_DB])
    assert res["judgement"] == "passed"


def test_fix_stops_without_build_or_required_signatures_and_lint_rules():
    db = copy_db(VERIFY_DB)
    type_md = db / CALL / "type.md"
    edit(type_md, "        - {branch: MOCKB77_U2, build: MOCKB77_U2_20260920}", "        - {branch: MOCKB77_U2}")
    proc = verify_fix(db, "call-fixed.log", expect=2)
    assert proc.returncode == 2 and "빌드가 있는 항목이 없습니다" in proc.stderr
    shutil.copyfile(LOGS / "call-fixed.log", db.parent / "cut.log")
    out = apply_plan(db, [{"op": "add-fixture", "for": "CALL-001-01", "kind": "fixed", "build": BUILD,
                           "path": str(db.parent / "cut.log")},
                          {"op": "verify-fix", "cause": "CALL-001-01", "result": "passed",
                           "verification": {"build": BUILD, "date": "2026-09-29", "by": "mock-user1",
                                            "fixture": str(db.parent / "cut.log")}}], expect=1)
    assert out["rejected"][0]["code"] == "fixed-in-build-missing"

    db = copy_db(VERIFY_DB)
    type_md = db / CALL / "type.md"
    text = type_md.read_text(encoding="utf-8")
    start = text.index("    recovery_signatures:\n      - id: ims-registered-call-active")
    end = text.index("    resolution: 캐리어 설정의 VoLTE")
    type_md.write_text(text[:start] + "    recovery_signatures: []\n    scenario_signatures: []\n" + text[end:],
                       encoding="utf-8", newline="\n")
    out = verify_fix(db, "call-fixed.log")
    assert out["judgement"] == "unknown" and "필수 시그니처 없음" in out["reason"] and "C" not in out

    edit(type_md, "      status: fix-submitted\n", "      status: fixed\n")
    lint = run_json("db_lint.py", ["--all", "--db", db], expect=1)
    codes = {e["code"] for e in lint["errors"]}
    assert {"fixed-without-verification", "fixed-without-trace"} <= codes


def test_verify_fix_plans_reach_stage():
    """손으로 쓴 verify-fix 계획(passed·failed·partial)을 db_pr stage에 넣는다."""
    ws = Workspace(src=VERIFY_DB)
    cases = {
        "passed": [{"op": "add-fixture", "for": "CALL-001-01", "kind": "fixed", "build": BUILD, "path": "fixtures/cut.log"},
                   {"op": "verify-fix", "cause": "CALL-001-01", "result": "passed",
                    "verification": {"build": BUILD, "date": "2026-09-29", "by": "mock-user1",
                                     "fixture": "fixtures/cut.log", "scenario_evidence": "CALL-001-01/volte-dial-attempt"}}],
        "failed": [{"op": "add-fixture", "for": "CALL-001-01", "kind": "recurrence", "build": BUILD,
                    "path": "fixtures/rec.log", "expect": {"also_allowed": ["IMS-001-01"]}},
                   {"op": "verify-fix", "cause": "CALL-001-01", "result": "failed",
                    "verification": {"build": BUILD, "date": "2026-09-29", "by": "mock-user1",
                                     "fixture": "fixtures/rec.log", "note": "원인 시그니처 충족"}}],
        "partial": [{"op": "verify-fix", "cause": "CALL-001-01", "result": "partial",
                     "verification": {"build": BUILD, "date": "2026-09-29", "by": "mock-user1",
                                      "note": "증상 남음. 다른 원인 후보: CALL-001-02"}}],
    }
    for name, ops in cases.items():
        job = f"verify-fix-CALL-001-01-{name}"
        branch = f"verify-fix/CALL-001-01-{name}"
        ws.put(job, "fixtures/cut.log", LOGS / "call-fixed.log")
        ws.put(job, "fixtures/rec.log", LOGS / "call-recurrence.log")
        ws.plan(job, fix_plan(ops, branch))
        ws.acquire(job)
        stage = ws.stage(job, branch)
        assert stage["result"] == "ok", json.dumps(stage.get("checks"), ensure_ascii=False)[:3000]
        type_md = ws.wt(job) / CALL / "type.md"
        fix = cause_of(type_md, "CALL-001-01")["fix"]
        if name == "passed":
            assert fix["status"] == "fixed"
            assert fix["verification"]["fixture"] == f"fixtures/CALL-001-01.fixed.{BUILD}.log"
            assert (ws.wt(job) / CALL / "fixtures" / f"CALL-001-01.fixed.{BUILD}.log").is_file()
        elif name == "failed":
            assert fix["status"] == "open" and fix["ref"] is None and fix["fixed_in"] == []
            top = fix["verification_history"][0]
            assert top["result"] == "failed" and top["ref"] == "MOCKCL-12345"
            assert top["fixed_in"] == [{"branch": "MOCKB77_U2", "build": "MOCKB77_U2_20260920"}]
            assert top["fixture"] == f"fixtures/CALL-001-01.recurrence.{BUILD}.log"
        else:
            assert fix["status"] == "fix-submitted" and fix["ref"] == "MOCKCL-12345"
            assert fix["verification_history"][0]["result"] == "partial"
        ws.db_pr("discard", ws.wt(job))


def test_recheck_of_fixed_cause_partial_keeps_fixed():
    out = verify_fix(SAMPLE, "call-partial.log")
    assert out["fix_status"] == "fixed" and out["judgement"] == "partial"
    db = copy_db(SAMPLE)
    apply_plan(db, [{"op": "verify-fix", "cause": "CALL-001-01", "result": "partial",
                     "verification": {"build": BUILD, "date": "2026-09-29", "by": "mock-user1", "note": "증상 남음"}}])
    fix = cause_of(db / CALL / "type.md", "CALL-001-01")["fix"]
    assert fix["status"] == "fixed" and fix["verification"]["result"] == "passed"
    assert [h["result"] for h in fix["verification_history"]] == ["partial", "partial"]


# -- 수동 기록 + 해결책 검증 --------------------------------------------------------------------


@pytest.mark.parametrize("loaded_condition", ["event", "pattern"])
def test_record_new_cause_resolution_draft_then_verified_stage(loaded_condition):
    ws = Workspace()
    job = "MOCK-7006"
    ws.put(job, "fixtures/cut-1.log", SIM_LOG)
    resolved = ws.put(job, "fixtures/resolved-1.log", RESOLVED_LOG)
    full = json.loads((PLANS / "p7-record-verified.plan.json").read_text(encoding="utf-8"))
    recovery = json.loads(json.dumps(SIM_RECOVERY))
    if loaded_condition == "pattern":
        recovery[0]["must_event"].pop(0)
        recovery[0]["must_match"] = [{"id": "loaded", "pattern": "SIM state changed: LOADED"}]
    full["operations"][0]["cause"]["recovery_signatures"] = recovery
    draft_plan = json.loads(json.dumps(full))
    draft_plan["operations"] = [op for op in draft_plan["operations"]
                                if op["op"] != "verify-resolution" and op.get("kind") != "resolved"]
    plan_path = ws.plan(job, draft_plan)
    ws.acquire(job)
    draft = ws.job_dir(job) / "draft"

    out = ws.json("db_verify.py", ["resolution", "--cause", "NEW-CAUSE-1", resolved, "--plan", plan_path,
                                   "--draft", draft])
    assert out["judgement"] == "passed", out
    assert out["cause"] == "DATA-001-03" and out["requested"] == "NEW-CAUSE-1"
    assert out["satisfied_traces"][0]["signature"] == "DATA-001-03/sim-loaded-then-allowed"
    assert [op["op"] for op in out["suggested_ops"]] == ["add-fixture", "verify-resolution"]
    # draft 모드의 초안 op는 계획의 temp_id를 쓴다 (실제 ID는 reason 같은 설명에만 남는다)
    assert [op.get("for") or op.get("cause") for op in out["suggested_ops"]] == ["NEW-CAUSE-1", "NEW-CAUSE-1"]
    r1 = next(r for r in out["rules"]["rules"] if r["id"] == "R1")
    assert r1["status"] == "pass" and not out.get("withheld")
    assert not draft.exists()

    draft.mkdir()       # 실행자가 draft 경로를 미리 만들어도(빈 디렉토리) 도구가 다시 만든다 (S4 plugin eval 18)
    proc = ws.run("db_verify.py", ["rules", "--plan", plan_path, "--draft", draft, "--extra", SIM_LOG,
                                   "--extra-normal", NORMAL_LOG, SIM_LOG])
    assert proc.returncode == 0, proc.stderr
    rows = {r["id"]: r for r in json.loads(proc.stdout)["rules"]}
    assert [rows[k]["status"] for k in ("R1", "R2", "R3", "R4")] == ["pass"] * 4
    assert rows["R6"]["status"] == "fail" and rows["R6"]["blocking"] is False
    assert rows["R6"]["targets"] == [str(SIM_LOG)]       # 정상 표본으로 준 SIM 로그만 기대와 다름

    draft.mkdir()
    (draft / "note.txt").write_text("x", encoding="utf-8")   # 도구가 만들지 않은 파일은 지우지 않고 멈춘다
    proc = ws.run("db_verify.py", ["rules", "--plan", plan_path, "--draft", draft])
    assert proc.returncode == 2 and "도구가 만들지 않은 파일" in proc.stderr and (draft / "note.txt").is_file()
    shutil.rmtree(draft)

    ws.plan(job, full)
    stage = ws.stage(job, "issue/MOCK-7006")
    assert stage["result"] == "ok", json.dumps(stage.get("checks"), ensure_ascii=False)[:3000]
    assert stage["checks"]["lint"]["code"] == 0
    verification = cause_of(ws.wt(job) / DATA / "type.md", "DATA-001-03")["resolution_verification"]
    assert verification["status"] == "verified"
    assert verification["evidence"] == ["fixtures/DATA-001-03.resolved.1.log"]
    ws.db_pr("discard", ws.wt(job))


DATA_001_03 = """  - id: DATA-001-03
    status: active
    title: SIM 미준비
    description: SIM 초기화 전에 평가가 거부됨
    signatures:
      - id: sim-not-ready
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*SIM_NOT_READY.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: SIM 로딩 뒤 데이터 평가를 다시 요청하도록 고친다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
"""

_CAUSE_TAIL = """    recovery_signatures: []
    scenario_signatures: []
    resolution: 시험용이다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: []
---

## 증상

검증 시험용.
"""

DATA_002 = """---
id: DATA-002
category: data
secondary_categories: []
title: SIM 때문에 평가가 거부됨
summary: 검증 시험용 유형
status: active
symptom_signatures:
  - id: sim-not-ready-rejected
    must_event:
      - {event: data_evaluation_rejected, fields: {reasons: '.*SIM_NOT_READY.*'}}
    window_sec: 60
causes:
  - id: DATA-002-01
    status: active
    title: 넓은 원인
    description: 거부 사유를 보지 않는 원인 시그니처
    signatures:
      - id: any-rejection
        must_event:
          - {event: data_evaluation_rejected}
        window_sec: 60
""" + _CAUSE_TAIL

CALL_002 = """---
id: CALL-002
category: call
secondary_categories: []
title: 발신 시도가 보임
summary: 검증 시험용 유형
status: active
symptom_signatures:
  - id: dial-seen
    must_event:
      - {event: ims_dial_attempt}
    window_sec: 60
causes:
  - id: CALL-002-01
    status: active
    title: 없는 실패 코드
    description: 어떤 fixture에도 없는 실패 코드
    signatures:
      - id: cause-99
        must_event:
          - {event: call_fail_cause, fields: {cause: '99'}}
        window_sec: 60
""" + _CAUSE_TAIL


# -- 출력 다이어트: 기본은 통과한 행만 접는다 ----------------------------------------------------------


def _extractor_db() -> Path:
    db = git_db()
    edit(db / "parser-rules/extractors.yaml", "    event: ims_registered\n    fields: [transport]",
         "    event: ims_registered\n    fields: []")
    return db


def _rows(out: dict) -> dict:
    return {r["id"]: r for r in out["rules"]}


def _default_vs_verbose(db: Path) -> tuple[int, dict, dict]:
    code, _, brief = rules(db)
    proc = run("db_verify.py", ["rules", "--changed", "HEAD", "--db", db, "--verbose"])
    assert proc.returncode == code
    return code, brief, json.loads(proc.stdout)


def test_default_output_folds_only_passed_rows_and_keeps_status():
    """pass 행만 checks를 건수로 접고, 행 6개·status·reason·종료 코드는 --verbose와 같다."""
    db = git_db()
    edit(db / CALL / "type.md", CALL_CAUSE_SIG, "        must_event:\n          - {event: ims_dial_attempt}\n"
                                                "        window_sec: 300\n")
    code, brief, full = _default_vs_verbose(db)
    assert code == 1
    assert [r["id"] for r in brief["rules"]] == [r["id"] for r in full["rules"]] == [f"R{i}" for i in range(1, 7)]
    for b, f in zip(brief["rules"], full["rules"]):
        assert (b["status"], b["reason"], b["targets"]) == (f["status"], f["reason"], f["targets"])
    b, f = _rows(brief), _rows(full)
    assert b["R1"]["status"] == "pass" and "checks" not in b["R1"]
    assert b["R1"]["checks_passed"] == len(f["R1"]["checks"]) and set(b["R1"]) <= {
        "id", "status", "reason", "targets", "review_required", "checks_passed"}
    assert b["R3"] == f["R3"] and b["R4"] == f["R4"]           # fail 행은 그대로
    assert b["R5"]["status"] == f["R5"]["status"] == "skipped" and b["R6"]["blocking"] is False
    assert "folded" in brief and "--verbose" in brief["folded"] and "folded" not in full
    assert {k: v for k, v in brief.items() if k not in ("rules", "folded")} == {
        k: v for k, v in full.items() if k != "rules"}


def test_default_output_keeps_allow_cause_drafts_and_review_required_rows():
    db = git_db()
    new = db / "data/DATA-002-sim-rejected"
    (new / "fixtures").mkdir(parents=True)
    (new / "type.md").write_text(DATA_002, encoding="utf-8", newline="\n")
    shutil.copyfile(SIM_LOG, new / "fixtures/DATA-002-01.log")
    code, brief, full = _default_vs_verbose(db)
    assert code == 1 and _rows(brief)["R3"] == _rows(full)["R3"]
    check = next(c for c in _rows(brief)["R3"]["checks"] if c["target"] == "DATA-002-01")
    assert check["allow_cause_drafts"]

    db = git_db()
    edit(db / DATA / "type.md", "tags: [data-evaluation]\n---", DATA_001_03 + "tags: [data-evaluation]\n---")
    _, brief, full = _default_vs_verbose(db)
    for rid in ("R1", "R2"):      # review_required skipped는 세부 전부
        assert _rows(brief)[rid] == _rows(full)[rid] and _rows(brief)[rid]["review_required"] is True


def test_brief_row_keeps_skipped_check_inside_pass_row():
    from db_verify import brief_row
    row = {"id": "R2", "status": "pass", "reason": "대상 2개 통과", "targets": ["A", "B"], "review_required": False,
           "checks": [{"target": "A", "status": "pass", "reason": "ok", "review_required": False},
                      {"target": "B", "status": "skipped", "reason": "시그니처 없음(pending)", "review_required": False}]}
    out = brief_row(row)
    assert out["checks_passed"] == 1 and out["checks"] == [row["checks"][1]]
    assert brief_row({**row, "checks": [row["checks"][0]]}).get("checks") is None


def test_default_output_keeps_needs_approval_row_in_full():
    code, brief, full = _default_vs_verbose(_extractor_db())
    assert code == 3
    assert _rows(brief)["R5"] == _rows(full)["R5"] and _rows(brief)["R5"]["status"] == "needs-approval"
    assert _rows(brief)["R5"]["impact"]
    assert _rows(brief)["R4"]["status"] == "pass"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
