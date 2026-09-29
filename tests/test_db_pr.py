#!/usr/bin/env python3
"""Phase 7 완료 기준 확인: 이슈 DB 반영, PR, sync-pr (11-phases.md Phase 7).

Step 8과 공통 쓰기 절차를 **스킬 없이** 돌린다: 손으로 쓴 계획(`tests/fixtures/plans/p7-*.plan.json`)을
`<work_dir>/<작업 키>/plan.json`에 놓고 `db_pr stage → summary → git add/commit(별도 호출) → publish → discard`를
직접 부른다. 원격은 `make_repo`의 bare 레포, PR은 `gh` 스텁(`tests/helpers/workspace.py`).

`pytest tests/test_db_pr.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, git_db, run_json, run  # noqa: E402
from workspace import PLANS, Workspace, git  # noqa: E402

FIX = REPO / "tests" / "fixtures"
SIM_LOG = FIX / "issue-db-pending/data/DATA-001-no-setup-data-call/fixtures/DATA-001-03.log"
NORMAL_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001.none.log"
DATA_DIR = "data/DATA-001-no-setup-data-call"
CSFB_LOG = """09-28 11:00:00.000  1234  1250 I SST-0: [PHONE0] pollState: voice=IN_SERVICE data=IN_SERVICE
09-28 11:00:02.000  1234  1250 W SST-0: [PHONE0] csfb fallback loop detected count=3 timer=0
09-28 11:00:04.000  1234  1250 W SST-0: [PHONE0] csfb fallback loop detected count=4 timer=0
"""


def load_plan(name: str) -> dict:
    return json.loads((PLANS / name).read_text(encoding="utf-8"))


def radio_off_plan(key: str = "MOCK-7010") -> dict:
    """p7-analyze-new-cause와 같은 유형·번호 자리에 다른 원인(RADIO_POWER_OFF)을 넣는 계획."""
    plan = load_plan("p7-analyze-new-cause.plan.json")
    plan["jira"]["key"] = key
    cause = plan["operations"][0]["cause"]
    cause["title"] = "무선 꺼짐"
    cause["description"] = "무선이 꺼진 상태에서 데이터 평가가 거부됨"
    cause["signatures"][0]["id"] = "radio-off"
    cause["signatures"][0]["must_event"][0]["fields"]["reasons"] = ".*RADIO_POWER_OFF.*"
    plan["commit_message"] = f"[NEW-CAUSE-1] add {key}: 무선 꺼짐으로 평가 거부"
    plan["pr"]["branch"] = f"issue/{key}"
    return plan


def radio_off_log() -> str:
    return SIM_LOG.read_text(encoding="utf-8").replace("SIM_NOT_READY", "RADIO_POWER_OFF")


def front(text: str) -> dict:
    return yaml.safe_load(text.split("---\n")[1])


def cause_of(type_md: str, cause_id: str) -> dict | None:
    return next((c for c in front(type_md)["causes"] if c["id"] == cause_id), None)


def pending_feedback(ws: Workspace, key: str = "MOCK-1199") -> Path:
    path = ws.home / "pending-feedback" / f"{key}-20260928T0900.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"jira: {key}\ndate: 2026-09-28T09:00+09:00\nby: mock-user1\nsuggested: []\n"
                    "decision: unresolved\nfinal: unresolved\n", encoding="utf-8")
    return path


def apply_json(db: Path, plan: dict, expect=0) -> dict:
    """db_add apply만 (stage 없이) — 적용 규칙 검사용. 계획의 상대 경로는 `<db 상위>/job` 기준."""
    plan_dir = db.parent / "job"
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return run_json("db_add.py", ["apply", path, "--db", db, "--user", "mock-user1"], expect=expect)


# -- op별 PR 생성 ----------------------------------------------------------------------------


def test_each_op_reaches_pr():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")
    jira = yaml.safe_load(ws.remote_file("issue/MOCK-7001", f"{DATA_DIR}/jira/MOCK-7001.yaml"))
    assert jira["cause"] == "DATA-001-02" and jira["analyzed_by"] == "mock-user1"

    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    out = ws.ship("MOCK-7002", "issue/MOCK-7002")
    assert out["stage"]["apply"]["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-03"}]
    type_md = ws.remote_file("issue/MOCK-7002", f"{DATA_DIR}/type.md")
    new = cause_of(type_md, "DATA-001-03")
    assert list(new)[:3] == ["id", "status", "title"], "템플릿 cause.yaml 키 순서"
    assert new["resolution_verification"] == {"status": "unverified"}
    assert "### DATA-001-03 SIM 미준비" in type_md
    assert ws.remote_file("issue/MOCK-7002", f"{DATA_DIR}/fixtures/DATA-001-03.log") is not None
    assert "DATA-001-03" in ws.remote_file("issue/MOCK-7002", "README.md")

    ws.plan("MOCK-7003", "p7-analyze-new-type.plan.json")
    ws.put("MOCK-7003", "fixtures/cut-1.log", CSFB_LOG)
    out = ws.ship("MOCK-7003", "issue/MOCK-7003")
    assert {i["id"] for i in out["stage"]["apply"]["ids"]} == {"NETWORK-002", "NETWORK-002-01"}
    type_md = ws.remote_file("issue/MOCK-7003", "network/NETWORK-002-csfb-fallback-loop/type.md")
    assert front(type_md)["symptom_signatures"][0]["id"] == "csfb-fallback-loop"
    assert "### NETWORK-002-01 폴백 타이머 0" in type_md

    ws.plan("MOCK-7004", "p7-analyze-unresolved.plan.json")
    ws.ship("MOCK-7004", "issue/MOCK-7004")
    assert yaml.safe_load(ws.remote_file("issue/MOCK-7004", f"{DATA_DIR}/jira/MOCK-7004.yaml"))["cause"] == \
        "unresolved"

    ws.plan("review-data-2026-10", "p7-review-reclassify.plan.json")
    ws.ship("review-data-2026-10", "review/data-2026-10")
    moved = yaml.safe_load(ws.remote_file("review/data-2026-10", f"{DATA_DIR}/jira/MOCK-1104.yaml"))
    assert moved["cause"] == "DATA-001-01" and "reclassified from unresolved" in moved["note"]

    titles = {p["branch"]: p["title"] for p in ws.prs()}
    assert titles["issue/MOCK-7002"].startswith("[DATA-001-03]")
    assert titles["issue/MOCK-7003"].startswith("[NETWORK-002]")
    assert len(titles) == 5
    for job in ("MOCK-7001", "MOCK-7002", "MOCK-7003", "MOCK-7004", "review-data-2026-10"):
        plan = ws.read_plan(job)
        assert plan["pr"]["number"] and plan["pr"]["head_sha"], job


def test_reclassify_needs_jira_in_main_and_append_stops_on_existing():
    ws = Workspace()
    plan = load_plan("p7-review-reclassify.plan.json")
    plan["operations"][0]["jira"] = "MOCK-9999"
    ws.plan("review-x", plan)
    ws.acquire("review-x")
    out = ws.stage("review-x", "review/x", expect=1)
    assert out["apply"]["rejected"][0]["code"] == "reclassify-missing"
    ws.db_pr("discard", ws.wt("review-x"))

    plan = load_plan("p7-analyze-append.plan.json")
    plan["jira"]["key"] = "MOCK-1101"
    ws.plan("MOCK-1101", plan)
    ws.acquire("MOCK-1101")
    out = ws.stage("MOCK-1101", "issue/MOCK-1101", expect=1)
    rejected = out["apply"]["rejected"][0]
    assert rejected["code"] == "jira-exists" and rejected["existing"]["cause"] == "DATA-001-01"
    pre = ws.db_pr("preflight", "--branch", "issue/MOCK-1101", "--search", "MOCK-1101", "--jira", "MOCK-1101")
    assert pre["jira_in_main"]["cause"] == "DATA-001-01"
    ws.db_pr("discard", ws.wt("MOCK-1101"))


# -- record, source 규칙 --------------------------------------------------------------------


def test_record_labels_pending_rules_and_sync_keeps_pending():
    ws = Workspace()
    pending = pending_feedback(ws)
    ws.plan("MOCK-7005", "p7-record-pending.plan.json")
    ws.put("MOCK-7005", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7005")
    stage = ws.stage("MOCK-7005", "issue/MOCK-7005")
    assert stage["apply"]["pending_included"] == [], "record에는 pending 피드백을 넣지 않는다"
    summary = ws.db_pr("summary", ws.wt("MOCK-7005"))
    assert summary["source_label"].startswith("수동 기록")
    assert summary["jira"]["label"] == "Jira 메타데이터: 오프라인 파일"
    notes = " / ".join(summary["notes"])
    assert "로그·코드 분석: 하지 않음" in notes and "시그니처 없음" in notes and "사용자 진술" in notes
    assert {r["id"] for r in summary["verification"]} == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert "수동 기록" in summary["pr_body"] and "| R4 | 통과 |" in summary["pr_body"]
    ws.commit("MOCK-7005")
    pub = ws.db_pr("publish", ws.wt("MOCK-7005"), "--branch", "issue/MOCK-7005", "--lease", "new",
                   "--approved", summary["approved_hash"])
    ws.db_pr("discard", ws.wt("MOCK-7005"))
    assert "수동 기록" in ws.prs()[0]["body"]
    assert pending.is_file(), "record는 pending 피드백을 옮기지 않는다"

    # 다른 PR이 main에 들어온 뒤 sync-pr(계획 재적용): pending 원인이 그대로 올라간다
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")
    ws.merge("issue/MOCK-7001")
    found = ws.db_pr("find-plan", "--branch", "issue/MOCK-7005")
    assert found["found"] and found["job"] == "MOCK-7005" and not found["remote_changed"]
    ws.acquire("MOCK-7005")
    stage = ws.stage("MOCK-7005", "issue/MOCK-7005")
    assert stage["drift"] == []
    summary = ws.db_pr("summary", ws.wt("MOCK-7005"))
    ws.commit("MOCK-7005")
    ws.db_pr("publish", ws.wt("MOCK-7005"), "--branch", "issue/MOCK-7005", "--lease", found["remote_sha"],
             "--approved", summary["approved_hash"])
    ws.db_pr("discard", ws.wt("MOCK-7005"))
    type_md = ws.remote_file("issue/MOCK-7005", f"{DATA_DIR}/type.md")
    assert cause_of(type_md, "DATA-001-03")["signatures_pending"] is True
    assert ws.remote_file("issue/MOCK-7005", f"{DATA_DIR}/jira/MOCK-7001.yaml") is not None, "최신 main 위"
    assert pub["pr"]["number"] == ws.read_plan("MOCK-7005")["pr"]["number"]


def test_pending_only_in_record_and_pending_feedback_only_in_analyze():
    db = git_db()
    plan = load_plan("p7-record-pending.plan.json")
    plan["source"] = "analyze"
    plan["jira"]["origin"] = "mcp"
    job = db.parent / "job"
    (job / "fixtures").mkdir(parents=True, exist_ok=True)
    (job / "fixtures" / "cut-1.log").write_text(SIM_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    out = apply_json(db, plan, expect=1)
    assert out["rejected"][0]["code"] == "pending-not-allowed"
    plan["source"] = "import"
    assert apply_json(db, plan, expect=1)["rejected"][0]["code"] == "pending-not-allowed"

    ws = Workspace()
    pending = pending_feedback(ws)
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    out = ws.ship("MOCK-7001", "issue/MOCK-7001")
    assert out["stage"]["apply"]["pending_included"] == ["feedback/2026-09/MOCK-1199-20260928T0900.yaml"]
    assert not pending.exists()
    assert (ws.job_dir("MOCK-7001") / "included_pending" / pending.name).is_file()
    plan = ws.read_plan("MOCK-7001")
    assert plan["included_pending"] == [{"file": pending.name, "pr": plan["pr"]["number"]}]

    # sync-pr 재적용 때 이전에 올린 pending이 다시 포함된다
    ws.push_main(lambda c: (c / "CONTRIBUTING.md").write_text("바뀜\n", encoding="utf-8"))
    ws.acquire("MOCK-7001")
    stage = ws.stage("MOCK-7001", "issue/MOCK-7001")
    assert stage["apply"]["pending_included"] == ["feedback/2026-09/MOCK-1199-20260928T0900.yaml"]
    ws.db_pr("discard", ws.wt("MOCK-7001"))


def test_verify_resolution_and_update_fix_rules():
    ws = Workspace()
    ws.plan("MOCK-7006", "p7-record-verified.plan.json")
    ws.put("MOCK-7006", "fixtures/cut-1.log", SIM_LOG)
    ws.put("MOCK-7006", "fixtures/resolved-1.log", NORMAL_LOG)
    ws.acquire("MOCK-7006")
    stage = ws.stage("MOCK-7006", "issue/MOCK-7006")
    type_md = (ws.wt("MOCK-7006") / DATA_DIR / "type.md").read_text(encoding="utf-8")
    rv = cause_of(type_md, "DATA-001-03")["resolution_verification"]
    assert rv["status"] == "verified" and rv["evidence"] == ["fixtures/DATA-001-03.resolved.1.log"]
    assert stage["result"] == "ok"
    ws.db_pr("discard", ws.wt("MOCK-7006"))

    db = git_db()
    job = db.parent / "job"
    (job / "fixtures").mkdir(parents=True)
    (job / "fixtures" / "cut-1.log").write_text(SIM_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    (job / "fixtures" / "resolved-1.log").write_text(NORMAL_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    base = load_plan("p7-record-verified.plan.json")

    reverse = json.loads(json.dumps(base))
    ops = reverse["operations"]
    ops.insert(0, ops.pop(3))          # verify-resolution을 new-cause 앞으로
    assert apply_json(db, reverse, expect=1)["rejected"][0]["code"] == "order"

    self_ev = json.loads(json.dumps(base))
    self_ev["operations"][3]["verification"]["evidence"] = ["MOCK-7006"]
    assert apply_json(db, self_ev, expect=1)["rejected"][0]["code"] == "self-evidence"

    for evidence in (["MOCK-9999"], ["fixtures/DATA-001-03.resolved.9.log"]):
        bad = json.loads(json.dumps(base))
        bad["operations"][3]["verification"]["evidence"] = evidence
        assert apply_json(db, bad, expect=1)["rejected"][0]["code"] == "evidence-missing", evidence

    later_set = json.loads(json.dumps(base))
    later_set["operations"].append({"op": "set-resolution", "cause": "NEW-CAUSE-1", "resolution": "다시 쓴다"})
    assert apply_json(db, later_set, expect=1)["rejected"][0]["code"] == "order"

    fix_plan = {"source": "fix-submitted", "schema_version": 1, "started_at": "2026-09-29T10:00+09:00",
                "base_sha": "0" * 40, "jira": None, "commit_message": "[X] fix-submitted",
                "operations": [{"op": "update-fix", "cause": "CALL-001-01",
                                "fix": {"status": "fix-submitted", "ref": "MOCKCL-2", "fixed_in": [
                                    {"branch": "MOCKB77_U2", "build": "MOCKB77_U2_20261001"}]}}]}
    assert apply_json(db, fix_plan, expect=1)["rejected"][0]["code"] == "fixed-to-fix-submitted"
    fix_plan["operations"][0]["cause"] = "DATA-001-01"   # not-a-bug → fix-submitted는 허용
    out = apply_json(db, fix_plan)
    assert out["applied"]
    fix = cause_of((db / DATA_DIR / "type.md").read_text(encoding="utf-8"), "DATA-001-01")["fix"]
    assert fix["status"] == "fix-submitted" and fix["ref"] == "MOCKCL-2"


def test_source_outside_values_dry_run_and_forced_exit_3():
    db = git_db()
    plan = load_plan("p7-analyze-append.plan.json")
    plan["source"] = "migrate"
    out = apply_json(db, plan, expect=2)
    assert "허용 값" in out["error"]

    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    stage = ws.stage("MOCK-7001", "issue/MOCK-7001", dry_run=True, unauth=True)
    assert stage["result"] == "ok" and stage["config_check"]["push_allowed"] is False
    summary = ws.db_pr("summary", ws.wt("MOCK-7001"), unauth=True)
    assert summary["push_allowed"] is False and "gh 인증 없음" in summary["push_note"]
    ws.db_pr("discard", ws.wt("MOCK-7001"))
    assert not list((ws.home / "pending-feedback").glob("*")) if (ws.home / "pending-feedback").exists() else True

    ws.acquire("MOCK-7001")
    stage = ws.stage("MOCK-7001", "issue/MOCK-7001", expect=3, env={"TT_FORCE_VERIFY_EXIT": "3"})
    assert stage["result"] == "needs-approval"
    summary = ws.db_pr("summary", ws.wt("MOCK-7001"))
    assert summary["approval_needed"], "확인 화면에 승인 필요 표시"
    assert "메인테이너 승인 필수" in summary["pr_body"]
    ws.db_pr("discard", ws.wt("MOCK-7001"))


# -- 재적용·사용자 clone 보호 ---------------------------------------------------------------


def _wt_snapshot(wt: Path) -> dict:
    status = git(wt, "status", "--porcelain", "-uall")
    files = {}
    for line in status.splitlines():
        rel = line[3:]
        path = wt / rel
        files[rel] = path.read_bytes() if path.is_file() else None
    return {"status": status, "diff": git(wt, "diff"), "files": files}


def test_restage_is_byte_identical_and_feedback_stable():
    ws = Workspace()
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7002")
    first = ws.stage("MOCK-7002", "issue/MOCK-7002")
    snap1 = _wt_snapshot(ws.wt("MOCK-7002"))
    (ws.wt("MOCK-7002") / "stray.txt").write_text("이전 적용분\n", encoding="utf-8")
    second = ws.stage("MOCK-7002", "issue/MOCK-7002")
    assert second["worktree"] == "reapplied"
    assert _wt_snapshot(ws.wt("MOCK-7002")) == snap1
    assert first["apply"]["feedback"] == second["apply"]["feedback"] == \
        "feedback/2026-09/MOCK-7002-20260929T1130.yaml"
    fb = yaml.safe_load((ws.wt("MOCK-7002") / first["apply"]["feedback"]).read_text(encoding="utf-8"))
    assert str(fb["date"]).startswith("2026-09-29") and fb["final"] == "DATA-001-03"
    ws.db_pr("discard", ws.wt("MOCK-7002"))


def test_user_clone_is_untouched_and_discard_cleans_up():
    ws = Workspace()
    clone = ws.clone
    git(clone, "checkout", "-q", "-b", "issue/MOCK-7001")
    (clone / "note.txt").write_text("사용자 로컬 커밋\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "-m", "사용자 로컬 작업", env=ws.hook_env())
    (clone / "wip.txt").write_text("커밋 안 한 작업\n", encoding="utf-8")
    before = {"head": git(clone, "rev-parse", "HEAD"), "branch": git(clone, "rev-parse", "--abbrev-ref", "HEAD"),
              "status": git(clone, "status", "--porcelain"), "user": git(clone, "rev-parse", "issue/MOCK-7001")}

    pre = ws.db_pr("preflight", "--branch", "issue/MOCK-7001", "--search", "MOCK-7001")
    assert pre["user_branch"]["exists"] and pre["user_branch"]["ahead_of_remote"] >= 1
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")

    after = {"head": git(clone, "rev-parse", "HEAD"), "branch": git(clone, "rev-parse", "--abbrev-ref", "HEAD"),
             "status": git(clone, "status", "--porcelain"), "user": git(clone, "rev-parse", "issue/MOCK-7001")}
    assert after == before
    assert not ws.wt("MOCK-7001").exists()
    assert git(clone, "for-each-ref", "refs/heads/tt/") == ""
    assert not (ws.job_dir("MOCK-7001") / "state.json").exists()
    assert ws.db_pr("lock", "status")["held"] is False
    assert (ws.job_dir("MOCK-7001") / "plan.json").is_file()


def test_tool_branch_in_other_worktree_stops_stage():
    ws = Workspace()
    other = ws.base / "elsewhere"
    git(ws.clone, "worktree", "add", "-q", "-b", "tt/issue/MOCK-7001", str(other), "origin/main")
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    proc = ws.run("db_pr.py", ["stage", ws.job_dir("MOCK-7001") / "plan.json", "--wt", ws.wt("MOCK-7001"),
                               "--branch", "issue/MOCK-7001"])
    assert proc.returncode == 2 and "다른 worktree" in proc.stderr


def test_step8_2_branch_states():
    ws = Workspace()
    # 도구 브랜치 잔여물 (worktree 없음)
    git(ws.clone, "branch", "tt/issue/MOCK-7001", "origin/main")
    pre = ws.db_pr("preflight", "--branch", "issue/MOCK-7001")
    assert pre["tool_branch"]["residual"] is True
    dry = ws.db_pr("cleanup", "--dry-run")
    assert {"kind": "branch", "name": "tt/issue/MOCK-7001"} in dry["targets"]
    assert git(ws.clone, "for-each-ref", "refs/heads/tt/"), "--dry-run은 지우지 않는다"
    ws.db_pr("cleanup", "--yes")
    assert git(ws.clone, "for-each-ref", "refs/heads/tt/") == ""

    # 원격에 있고 내가 마지막으로 올린 상태 → plan으로 브랜치 갱신 (lease push)
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    first = ws.ship("MOCK-7001", "issue/MOCK-7001")
    pre = ws.db_pr("preflight", "--branch", "issue/MOCK-7001")
    assert pre["remote_sha"] == ws.read_plan("MOCK-7001")["pr"]["head_sha"] == first["publish"]["head_sha"]
    ws.push_main(lambda c: (c / "CONTRIBUTING.md").write_text("바뀜\n", encoding="utf-8"))
    second = ws.ship("MOCK-7001", "issue/MOCK-7001", lease=pre["remote_sha"])
    assert second["publish"]["pr"]["action"] == "edited"
    assert len(ws.prs()) == 1

    # 원격이 다른 사람에 의해 바뀜 → 옛 lease로는 push 거부
    stale = second["publish"]["head_sha"]
    ws.push_branch("issue/MOCK-7001", lambda c: (c / "extra.txt").write_text("리뷰어\n", encoding="utf-8"))
    found = ws.db_pr("find-plan", "--branch", "issue/MOCK-7001")
    assert found["remote_changed"] is True and "extra.txt" in found["remote_diff_stat"]
    ws.acquire("MOCK-7001")
    ws.stage("MOCK-7001", "issue/MOCK-7001")
    summary = ws.db_pr("summary", ws.wt("MOCK-7001"))
    ws.commit("MOCK-7001")
    out = ws.db_pr("publish", ws.wt("MOCK-7001"), "--branch", "issue/MOCK-7001", "--lease", stale,
                   "--approved", summary["approved_hash"], expect=1)
    assert out["pushed"] is False
    out = ws.db_pr("publish", ws.wt("MOCK-7001"), "--branch", "issue/MOCK-7001", "--lease", "new",
                   "--approved", summary["approved_hash"], expect=1)
    assert out["pushed"] is False, "--lease new는 원격에 브랜치가 없어야 한다"
    ws.db_pr("discard", ws.wt("MOCK-7001"))


# -- drift --------------------------------------------------------------------------------------


def _review_plan(ops: list[dict], branch: str) -> dict:
    return {"source": "review", "schema_version": 1, "started_at": "2026-10-01T10:00+09:00", "base_sha": "0" * 40,
            "jira": None, "operations": ops, "feedback": None, "commit_message": f"[DATA-001] review: {branch}",
            "pr": {"number": None, "branch": branch, "head_sha": None}, "included_pending": []}


def test_drift_resolution_parser_rule_and_allow_cause():
    ws = Workspace()
    job = "review-data-2026-10"
    base = ws.main_sha()
    ws.plan(job, _review_plan([{"op": "set-resolution", "cause": "DATA-001-02",
                                "resolution": "데이터 로밍 설정을 켜고 요금제를 확인한다"}], "review/data-2026-10"))
    ws.push_main(lambda c: _edit(c / DATA_DIR / "type.md", "resolution: 데이터 로밍 설정을 켠다",
                                 "resolution: 데이터 로밍을 켠다 (다른 PR)"))
    ws.acquire(job)
    out = ws.stage(job, "review/data-2026-10", expect=1)
    assert out["stopped"] == "drift"
    assert [(d["op"], d["target"], d["field"]) for d in out["drift"]] == [("set-resolution", "DATA-001-02",
                                                                            "resolution")]
    plan = ws.read_plan(job)
    plan["base_sha"] = out["base_sha"]            # 사용자 결정(계획 값 유지)을 반영
    ws.plan(job, plan, base_sha=out["base_sha"])
    assert ws.stage(job, "review/data-2026-10")["result"] == "ok"
    ws.db_pr("discard", ws.wt(job))

    # parser-rules: 이력 필드만 바뀌면 drift 아님, 기능 필드가 바뀌면 drift
    rule_op = {"op": "update-parser-rule", "file": "extractors.yaml", "key": "data-evaluation-allowed",
               "rule": {"patterns": ["evaluation result:\\s*ALLOWED", "evaluation result:\\s*PERMITTED"],
                        "reason": "문구 변형 추가", "added_on": "2026-10-01"}}
    ws.plan(job, _review_plan([rule_op], "review/data-2026-10"), base_sha=ws.main_sha())
    ws.push_main(lambda c: _edit(c / "parser-rules/extractors.yaml", "reason: 정상 동작(해결 후) 판별용",
                                 "reason: 정상 동작(해결 후) 판별용 (설명 보강)"))
    ws.acquire(job)
    assert ws.stage(job, "review/data-2026-10")["drift"] == []
    ws.db_pr("discard", ws.wt(job))
    ws.push_main(lambda c: _edit(c / "parser-rules/extractors.yaml", "'evaluation result:\\s*ALLOWED'",
                                 "'evaluation result:\\s*ALLOWED\\b'"))
    ws.acquire(job)
    out = ws.stage(job, "review/data-2026-10", expect=1)
    assert out["drift"][0]["op"] == "update-parser-rule"
    ws.db_pr("discard", ws.wt(job))

    # allow-cause 대상 fixture의 also_allowed를 main이 먼저 바꿈 → drift
    ws.plan(job, _review_plan([{"op": "allow-cause", "fixture": "fixtures/SIM-001-01.log", "cause": "DATA-001-01"}],
                              "review/data-2026-10"), base_sha=ws.main_sha())
    ws.push_main(lambda c: (c / "sim/SIM-001-sim-not-detected/fixtures/SIM-001-01.expect.yaml").write_text(
        "expect_top: SIM-001-01\nalso_allowed: [IMS-001-01]\norigin: synthetic\n", encoding="utf-8"))
    ws.acquire(job)
    out = ws.stage(job, "review/data-2026-10", expect=1)
    assert out["drift"][0]["op"] == "allow-cause" and out["drift"][0]["field"] == "also_allowed"
    ws.db_pr("discard", ws.wt(job))
    assert base != ws.main_sha()


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path.name}: {old!r} 없음"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


# -- allow-cause ------------------------------------------------------------------------------


def test_allow_cause_creates_or_extends_expect_and_adds_reviewer():
    ws = Workspace()
    job = "review-sim-2026-10"
    ws.plan(job, _review_plan([{"op": "allow-cause", "fixture": "fixtures/SIM-001-01.log", "cause": "DATA-001-01"}],
                              "review/sim-2026-10"))
    ws.acquire(job)
    ws.stage(job, "review/sim-2026-10")
    exp = yaml.safe_load((ws.wt(job) / "sim/SIM-001-sim-not-detected/fixtures/SIM-001-01.expect.yaml")
                         .read_text(encoding="utf-8"))
    assert exp["expect_top"] == "SIM-001-01" and exp["also_allowed"] == ["DATA-001-01"]
    assert exp["origin"] == "synthetic", "기존 필드 유지"
    summary = ws.db_pr("summary", ws.wt(job))
    assert "mock-org/telephony-sim-owners" in summary["reviewers"]
    ws.db_pr("discard", ws.wt(job))

    # .expect.yaml이 없는 양성 fixture(같은 계획의 add-fixture) → 기본 기대값 + also_allowed로 만든다
    plan = load_plan("p7-analyze-new-cause.plan.json")
    plan["operations"][1].pop("occurred_at")
    plan["operations"].append({"op": "allow-cause", "fixture": "fixtures/cut-1.log", "cause": "IMS-001-01"})
    ws.plan("MOCK-7002", plan)
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7002")
    ws.stage("MOCK-7002", "issue/MOCK-7002")
    exp = yaml.safe_load((ws.wt("MOCK-7002") / DATA_DIR / "fixtures/DATA-001-03.expect.yaml").read_text(
        encoding="utf-8"))
    assert exp == {"expect_top": "DATA-001-03", "also_allowed": ["IMS-001-01"]}
    summary = ws.db_pr("summary", ws.wt("MOCK-7002"))
    assert "mock-org/telephony-data-owners" in summary["reviewers"]
    ws.db_pr("discard", ws.wt("MOCK-7002"))

    db = git_db()
    out = apply_json(db, _review_plan([{"op": "allow-cause", "fixture": "fixtures/SIM-001-01.log",
                                        "cause": "SIM-001-01"}], "review/x"), expect=1)
    assert out["rejected"][0]["code"] == "allow-cause-same", "자기 원인"
    out = apply_json(db, _review_plan([{"op": "allow-cause", "fixture": "fixtures/DATA-001-02.log",
                                        "cause": "DATA-001-01"}], "review/x"), expect=1)
    assert out["rejected"][0]["code"] == "allow-cause-same", "같은 유형의 원인"


# -- sync-pr ------------------------------------------------------------------------------------


def test_same_number_race_resolved_by_sync_pr():
    ws = Workspace()
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.plan("MOCK-7010", radio_off_plan())
    ws.put("MOCK-7010", "fixtures/cut-1.log", radio_off_log())
    a = ws.ship("MOCK-7002", "issue/MOCK-7002")
    b = ws.ship("MOCK-7010", "issue/MOCK-7010")
    assert a["stage"]["apply"]["ids"][0]["id"] == b["stage"]["apply"]["ids"][0]["id"] == "DATA-001-03"
    assert b["stage"]["apply"]["fixtures"][0]["name"] == "DATA-001-03.log"
    ws.merge("issue/MOCK-7002")

    found = ws.db_pr("find-plan", "--branch", "issue/MOCK-7010")
    ws.acquire(found["job"])
    stage = ws.stage("MOCK-7010", "issue/MOCK-7010")
    assert stage["apply"]["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}]
    assert stage["apply"]["fixtures"][0]["name"] == "DATA-001-04.log"
    summary = ws.db_pr("summary", ws.wt("MOCK-7010"))
    assert summary["pr_title"].startswith("[DATA-001-04]")
    ws.commit("MOCK-7010")
    ws.db_pr("publish", ws.wt("MOCK-7010"), "--branch", "issue/MOCK-7010", "--lease", found["remote_sha"],
             "--approved", summary["approved_hash"])
    ws.db_pr("discard", ws.wt("MOCK-7010"))

    pr = next(p for p in ws.prs() if p["branch"] == "issue/MOCK-7010")
    assert pr["title"].startswith("[DATA-001-04]") and "DATA-001-04" in pr["body"]
    type_md = ws.remote_file("issue/MOCK-7010", f"{DATA_DIR}/type.md")
    ids = [c["id"] for c in front(type_md)["causes"]]
    assert ids == ["DATA-001-01", "DATA-001-02", "DATA-001-03", "DATA-001-04"]
    assert cause_of(type_md, "DATA-001-03")["title"] == "SIM 미준비"
    assert cause_of(type_md, "DATA-001-04")["title"] == "무선 꺼짐"
    ws.merge("issue/MOCK-7010")                      # 텍스트 충돌 없이 머지된다
    files = ws.remote_files("main")
    assert f"{DATA_DIR}/fixtures/DATA-001-03.log" in files and f"{DATA_DIR}/fixtures/DATA-001-04.log" in files


def test_sync_pr_without_plan_only_guides():
    ws = Workspace()
    other = ws.other_clone()
    git(other, "checkout", "-q", "-b", "review/manual-1")
    (other / "CONTRIBUTING.md").write_text("직접 편집\n", encoding="utf-8")
    git(other, "commit", "-qam", "직접 편집")
    git(other, "push", "-q", "origin", "review/manual-1")
    refs_before = git(ws.clone, "for-each-ref", "refs/heads/")
    out = ws.db_pr("find-plan", "--branch", "review/manual-1")
    assert out["found"] is False and len(out["manual_steps"]) == 4
    assert "rebase origin/main" in out["manual_steps"][0]
    assert git(ws.clone, "for-each-ref", "refs/heads/") == refs_before
    assert not ws.work.exists() or not any(ws.work.glob("*/wt"))


# -- publish 보호 ---------------------------------------------------------------------------------


def test_publish_rejects_changes_after_approval():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    ws.stage("MOCK-7001", "issue/MOCK-7001")
    summary = ws.db_pr("summary", ws.wt("MOCK-7001"))
    wt = ws.wt("MOCK-7001")
    publish = ["publish", wt, "--branch", "issue/MOCK-7001", "--lease", "new", "--approved", summary["approved_hash"]]

    (wt / "CONTRIBUTING.md").write_text("승인 뒤 수정\n", encoding="utf-8")
    ws.commit("MOCK-7001")
    out = ws.db_pr(*publish, expect=1)
    assert any("승인 해시" in p for p in out["problems"])

    git(wt, "reset", "-q", "--soft", "HEAD^")          # 승인받은 상태로 되돌려 다시 커밋
    git(wt, "checkout", "HEAD", "--", "CONTRIBUTING.md")
    ws.commit("MOCK-7001")
    (wt / "x.txt").write_text("둘째 커밋\n", encoding="utf-8")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "둘째", env=ws.hook_env())
    out = ws.db_pr(*publish, expect=1)
    assert any("커밋 하나" in p for p in out["problems"])

    git(wt, "reset", "-q", "--hard", "HEAD^")
    message = json.loads((ws.job_dir("MOCK-7001") / "state.json").read_text(encoding="utf-8"))["commit_message"]
    git(wt, "commit", "-q", "--amend", "-m", "다른 메시지", env=ws.hook_env())
    out = ws.db_pr(*publish, expect=1)
    assert any("커밋 메시지" in p for p in out["problems"])
    git(wt, "commit", "-q", "--amend", "-m", message, env=ws.hook_env())
    bad_branch = list(publish)
    bad_branch[3] = "issue/OTHER-1"
    out = ws.db_pr(*bad_branch, expect=1)
    assert any("브랜치" in p for p in out["problems"])
    # 첫 부모가 기준 SHA인 머지 커밋도 "커밋 하나"가 아니다 (HEAD^2 검사)
    good = git(wt, "rev-parse", "HEAD")
    git(wt, "checkout", "-q", "--detach", "HEAD^")
    (wt / "side.txt").write_text("옆 가지\n", encoding="utf-8")
    git(wt, "add", "-A")
    git(wt, "commit", "-qm", "옆 가지", env=ws.hook_env())
    side = git(wt, "rev-parse", "HEAD")
    git(wt, "checkout", "-q", "tt/issue/MOCK-7001")
    git(wt, "reset", "-q", "--hard", "HEAD^")
    git(wt, "merge", "-q", "--no-ff", "-m", message, side, env=ws.hook_env())
    git(wt, "rm", "-q", "--cached", "side.txt")
    git(wt, "commit", "-q", "--amend", "--no-edit", env=ws.hook_env())   # 트리는 승인 트리와 같게, 부모만 둘
    out = ws.db_pr(*publish, expect=1)
    assert any("머지 커밋" in p for p in out["problems"])
    git(wt, "reset", "-q", "--hard", good)
    assert ws.db_pr(*publish)["pushed"] is True
    ws.db_pr("discard", wt)


def test_expired_own_lock_does_not_block_publish_or_discard():
    """확인 화면에서 4시간 넘게 기다린 뒤에도 같은 작업의 publish·discard는 그대로 진행하고 lock을 푼다
    (contracts.md §3.2: 만료는 다른 작업이 `acquire`로 가져갈 수 있다는 뜻일 뿐이다)."""
    ws = Workspace()
    at = lambda hours: {"TT_NOW": f"2026-09-29T{hours:02d}:00:00Z"}  # noqa: E731
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.db_pr("lock", "acquire", "MOCK-7001", "--take-over", env=at(9))
    ws.stage("MOCK-7001", "issue/MOCK-7001", env=at(9))
    summary = ws.db_pr("summary", ws.wt("MOCK-7001"), env=at(9))
    ws.commit("MOCK-7001")
    assert ws.db_pr("lock", "status", env=at(14))["lock"]["expired"] is True
    out = ws.db_pr("publish", ws.wt("MOCK-7001"), "--branch", "issue/MOCK-7001", "--lease", "new",
                   "--approved", summary["approved_hash"], env=at(14))
    assert out["pushed"] is True
    assert ws.db_pr("lock", "status", env=at(14))["lock"]["expired"] is False   # publish가 갱신했다
    done = ws.db_pr("discard", ws.wt("MOCK-7001"), env=at(19))                     # 또 5시간 뒤
    assert done["lock"]["released"] is True
    assert ws.db_pr("lock", "status")["held"] is False


# -- cleanup·lock ------------------------------------------------------------------------------------


def test_cleanup_skips_lock_holder_and_needs_yes():
    ws = Workspace()
    ws.plan("MOCK-7004", "p7-analyze-unresolved.plan.json")
    ws.acquire("MOCK-7004")
    ws.stage("MOCK-7004", "issue/MOCK-7004")
    ws.db_pr("lock", "release", "MOCK-7004")          # discard 없이 끝남 (비정상 종료 흉내)
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    assert ws.acquire("MOCK-7001")["acquired"], "release 뒤 다음 작업이 바로 lock을 잡는다"
    ws.stage("MOCK-7001", "issue/MOCK-7001")

    dry = ws.db_pr("cleanup", "--dry-run")
    paths = {t.get("path") for t in dry["targets"]}
    assert str(ws.wt("MOCK-7004")) in paths and str(ws.wt("MOCK-7001")) not in paths
    assert ws.wt("MOCK-7004").exists() and dry["removed"] == []
    done = ws.db_pr("cleanup", "--yes")
    assert not ws.wt("MOCK-7004").exists() and ws.wt("MOCK-7001").exists()
    assert "tt/issue/MOCK-7004" in {t.get("name") for t in done["targets"]}
    assert git(ws.clone, "for-each-ref", "--format=%(refname:short)", "refs/heads/tt/") == "tt/issue/MOCK-7001"
    ws.db_pr("discard", ws.wt("MOCK-7001"))


# -- 사후 lint, R4 ------------------------------------------------------------------------------------


def test_post_lint_reports_duplicates_without_changes():
    ws = Workspace(src=FIX / "issue-db-dup-id")
    head = git(ws.clone, "rev-parse", "HEAD")
    ws.acquire("sync")
    out = ws.db_pr("snapshot", "--job", "sync")
    codes = {d["code"] for d in out["post_lint"]["duplicates"]}
    assert codes == {"duplicate-id", "duplicate-jira"}
    assert "메인테이너" in out["post_lint"]["notice"]
    assert git(ws.clone, "rev-parse", "HEAD") == head and git(ws.clone, "status", "--porcelain") == ""
    ws.db_pr("lock", "release", "sync")


def test_rule_that_changes_existing_fixture_is_blocked_by_r4():
    ws = Workspace()
    job = "review-data-2026-10"
    ws.plan(job, _review_plan([{"op": "update-signature", "owner": "DATA-001-02", "kind": "cause",
                                "sig_id": "roaming-disabled",
                                "signature": {"id": "roaming-disabled", "window_sec": 60,
                                              "must_event": [{"event": "data_evaluation_rejected"}]}}],
                              "review/data-2026-10"))
    ws.acquire(job)
    out = ws.stage(job, "review/data-2026-10", expect=1)
    r4 = next(r for r in out["checks"]["verify"]["result"]["rules"] if r["id"] == "R4")
    assert r4["status"] == "fail" and any("DATA-001-01.log" in t for t in r4["targets"])
    rows = {r["id"]: r for r in out["checks"]["verify"]["result"]["rules"]}   # Phase 10: R1~R5 실제 판정
    assert rows["R3"]["status"] == "fail" and rows["R3"]["targets"] == ["DATA-001-02"]
    assert rows["R1"]["status"] == "pass" and rows["R5"]["status"] == "skipped"
    ws.db_pr("discard", ws.wt(job))


# -- db_add 도구 --------------------------------------------------------------------------------------


def test_import_rules_and_new_type_needs_symptom():
    db = git_db()
    out = apply_json(db, load_plan("p7-import.plan.json"))
    assert out["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "SMS-001-02"}] and out["feedback"] is None
    plan = load_plan("p7-analyze-new-type.plan.json")
    plan["operations"][0]["type"]["symptom_signatures"] = []
    assert apply_json(db, plan, expect=2)["error"].startswith("계획 형식 오류")


def test_check_ids_renumber_and_similar():
    db = git_db()
    git(db, "checkout", "-q", "-b", "feature")
    job = db.parent / "job"
    (job / "fixtures").mkdir(parents=True)
    (job / "fixtures" / "cut-1.log").write_text(SIM_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    apply_json(db, load_plan("p7-analyze-new-cause.plan.json"))
    git(db, "add", "-A")
    git(db, "commit", "-qm", "직접 편집으로 DATA-001-03 추가")
    # 그사이 main에도 DATA-001-03이 들어왔다
    git(db, "checkout", "-q", "main")
    (job / "fixtures" / "cut-1.log").write_text(radio_off_log(), encoding="utf-8")
    apply_json(db, radio_off_plan())
    git(db, "add", "-A")
    git(db, "commit", "-qm", "main의 DATA-001-03")
    git(db, "checkout", "-q", "feature")

    ids = run_json("db_add.py", ["check-ids", "--base", "main", "--db", db], expect=1)
    assert [c["id"] for c in ids["conflicts"]] == ["DATA-001-03"]
    proc = run("db_add.py", ["renumber", "DATA-001-01", "--base", "main", "--db", db])
    assert proc.returncode == 2 and "main에 들어간 ID" in proc.stderr
    out = run_json("db_add.py", ["renumber", "DATA-001-03", "--base", "main", "--db", db])
    assert out["new"] == "DATA-001-04"
    assert {"from": f"{DATA_DIR}/fixtures/DATA-001-03.log", "to": f"{DATA_DIR}/fixtures/DATA-001-04.log"} in \
        out["renamed"]
    type_md = (db / DATA_DIR / "type.md").read_text(encoding="utf-8")
    assert "### DATA-001-04 SIM 미준비" in type_md and "DATA-001-03" not in type_md
    lint = run_json("db_lint.py", ["--changed", "main", "--residual", "DATA-001-03=DATA-001-04", "--db", db],
                    expect=(0, 1))
    assert not [e for e in lint["errors"] if e["code"] == "residual-id"]

    sim = run_json("db_add.py", ["similar", "SETUP_DATA_CALL이 나가지 않음", "--db", db])
    assert sim["top"][0]["type"] == "DATA-001" and len(sim["top"]) == 3


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
