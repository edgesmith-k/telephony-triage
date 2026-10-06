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

import mock_env  # noqa: E402
from runner import SAMPLE, git_db, run_json, run, variant_db  # noqa: E402
from workspace import PLANS, Workspace, git  # noqa: E402

SIM_LOG = variant_db("issue-db-pending") / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-03.log"
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
    ws.plan("MOCK-7005", "p7-record-pending.plan.json",
            pr_notes=["drift 결정: DATA-001-02 resolution — 계획 값 유지", "연락처 010-1234-5678"])
    ws.put("MOCK-7005", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7005")
    stage = ws.stage("MOCK-7005", "issue/MOCK-7005")
    assert stage["apply"]["pending_included"] == [], "record에는 pending 피드백을 넣지 않는다"
    summary = ws.db_pr("summary", ws.wt("MOCK-7005"))
    assert summary["source_label"].startswith("수동 기록")
    assert summary["jira"]["label"] == "Jira 메타데이터: 오프라인 파일"
    notes = " / ".join(summary["notes"])
    assert "로그·코드 분석: 하지 않음" in notes and "시그니처 없음" in notes and "사용자 진술" in notes
    # 계획 pr_notes는 확인 화면·PR 본문에 들어가고 한 번 더 마스킹된다 (Phase 13)
    assert "drift 결정: DATA-001-02 resolution — 계획 값 유지" in notes and "010-1234-5678" not in notes
    assert "drift 결정" in summary["pr_body"] and "010-1234-5678" not in summary["pr_body"]
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


SUMMARY_KEYS = ["source", "source_label", "jira", "branch", "reviewers", "open_prs", "files", "ids", "fixtures",
                "drift_decisions", "readme_preview", "diff", "diff_total_lines", "diff_truncated", "checks", "verification",
                "approval_needed", "notes", "commit_message", "pr_title", "push_allowed", "push_note", "pending_included",
                "pr_body", "approved_hash"]


def test_summary_markdown_is_opt_in_and_leaves_json_and_state_files_alone():
    ws = Workspace()
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7002")
    ws.stage("MOCK-7002", "issue/MOCK-7002")
    wt, job = ws.wt("MOCK-7002"), ws.job_dir("MOCK-7002")
    default = ws.run("db_pr.py", ["summary", wt])
    files = {name: (job / name).read_bytes() for name in ("state.json", "pr.json")}
    shown = json.loads(default.stdout)
    assert default.returncode == 0 and list(shown) == SUMMARY_KEYS      # 기본 stdout 키 목록·순서 고정

    explicit = ws.run("db_pr.py", ["summary", wt, "--format", "json"])
    assert explicit.returncode == 0 and explicit.stdout == default.stdout
    md = ws.run("db_pr.py", ["summary", wt, "--format", "markdown"])
    assert md.returncode == 0 and md.stdout.startswith("## push 전 확인: MOCK-7002 → DATA-001-03 SIM 미준비\n")
    assert md.stdout.splitlines()[-1] == f"approved_hash: {shown['approved_hash']}"   # 같은 승인 해시
    assert "해결책 검증 상태: DATA-001-03 — unverified(신규 원인 (new-cause))" in md.stdout
    assert "NEW-CAUSE-1 → DATA-001-03" in md.stdout and shown["commit_message"] in md.stdout
    assert {name: (job / name).read_bytes() for name in files} == files   # state.json·pr.json 바이트 동일
    assert len(md.stdout.encode()) < len(default.stdout.encode())

    both = ws.run("db_pr.py", ["summary", wt, "--json", "--format", "markdown"])
    assert both.returncode == 2 and both.stdout == "" and "--json" in both.stderr
    assert {name: (job / name).read_bytes() for name in files} == files
    ws.db_pr("discard", wt)


def test_summary_markdown_shows_needs_approval_and_dry_run_push_note():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    ws.stage("MOCK-7001", "issue/MOCK-7001", expect=3, env={"TT_FORCE_VERIFY_EXIT": "3"})
    md = ws.run("db_pr.py", ["summary", ws.wt("MOCK-7001"), "--format", "markdown"])
    assert md.returncode == 0 and "승인 필요: " in md.stdout and "승인 필요: 없음" not in md.stdout
    assert "메인테이너 승인 필수" in md.stdout
    ws.db_pr("discard", ws.wt("MOCK-7001"))
    ws.acquire("MOCK-7001")
    ws.stage("MOCK-7001", "issue/MOCK-7001", dry_run=True, unauth=True)
    md = ws.run("db_pr.py", ["summary", ws.wt("MOCK-7001"), "--format", "markdown"], unauth=True)
    assert "push 불가: gh 인증 없음 (--dry-run)" in md.stdout and md.stdout.splitlines()[-1].startswith("approved_hash: ")
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
    assert out["drift"][0]["plan_value"] == "데이터 로밍 설정을 켜고 요금제를 확인한다"
    assert out["drift"][0]["plan_base_value"] == "데이터 로밍 설정을 켠다"
    assert out["drift"][0]["current_value"] == "데이터 로밍을 켠다 (다른 PR)"
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
    assert out["drift"][0]["plan_value"] == {"patterns": ["evaluation result:\\s*ALLOWED",
                                                          "evaluation result:\\s*PERMITTED"]}
    ws.db_pr("discard", ws.wt(job))

    # allow-cause 대상 fixture의 also_allowed를 main이 먼저 바꿈 → drift
    ws.plan(job, _review_plan([{"op": "allow-cause", "fixture": "fixtures/SIM-001-01.log", "cause": "DATA-001-01"}],
                              "review/data-2026-10"), base_sha=ws.main_sha())
    ws.push_main(lambda c: (c / "sim/SIM-001-sim-not-detected/fixtures/SIM-001-01.expect.yaml").write_text(
        "expect_top: SIM-001-01\nalso_allowed: [IMS-001-01]\norigin: synthetic\n", encoding="utf-8"))
    ws.acquire(job)
    out = ws.stage(job, "review/data-2026-10", expect=1)
    assert out["drift"][0]["op"] == "allow-cause" and out["drift"][0]["field"] == "also_allowed"
    assert out["drift"][0]["plan_value"] == "DATA-001-01" and out["drift"][0]["current_value"] == ["IMS-001-01"]
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
    assert stage["ids_at_base"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-03"}]
    assert stage["apply"]["fixtures"][0]["name"] == "DATA-001-04.log"
    summary = ws.db_pr("summary", ws.wt("MOCK-7010"))
    assert summary["pr_title"].startswith("[DATA-001-04]")
    assert summary["ids"][0]["expected_at_base"] == "DATA-001-03"
    assert "NEW-CAUSE-1 → DATA-001-04 (계획 당시 DATA-001-03)" in summary["pr_body"]
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


def _db_with_old_plan_schema():
    """`pr.ids`를 모르는 옛 plan.schema.json을 가진 이슈 DB(샘플 원본은 건드리지 않는다)."""
    from runner import copy_db
    db = copy_db()
    path = db / "schema" / "plan.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    del schema["properties"]["pr"]["properties"]["ids"]
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return db


def _ship_for_race(ws):
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.plan("MOCK-7010", radio_off_plan())
    ws.put("MOCK-7010", "fixtures/cut-1.log", radio_off_log())
    ws.ship("MOCK-7002", "issue/MOCK-7002")
    return ws.ship("MOCK-7010", "issue/MOCK-7010")


def test_publish_records_pr_ids_and_summary_shows_reassignment_against_previous_apply():
    ws = Workspace()                      # 샘플 DB 스키마가 pr.ids를 안다 — 사본 바꿔치기 없음
    out = _ship_for_race(ws)
    assert out["publish"]["pr_ids_recorded"] is True
    assert ws.read_plan("MOCK-7010")["pr"]["ids"] == {"NEW-CAUSE-1": "DATA-001-03"}      # publish가 이번 적용을 기록
    ws.merge("issue/MOCK-7002")
    found = ws.db_pr("find-plan", "--branch", "issue/MOCK-7010")
    ws.acquire(found["job"])
    ws.stage("MOCK-7010", "issue/MOCK-7010")                                           # 기록이 든 계획도 재적용된다(스키마 통과)
    summary = ws.db_pr("summary", ws.wt("MOCK-7010"))
    assert summary["ids"][0]["previous_id"] == "DATA-001-03" and summary["ids"][0]["expected_at_base"] == "DATA-001-03"
    md = ws.run("db_pr.py", ["summary", ws.wt("MOCK-7010"), "--format", "markdown"]).stdout
    assert ("- NEW-CAUSE-1 → DATA-001-04: 계획 당시 DATA-001-03 → DATA-001-04 (main에 먼저 머지된 원인); "
            "DATA-001-03 → DATA-001-04 재할당") in md
    ws.db_pr("discard", ws.wt("MOCK-7010"))


def test_publish_skips_pr_ids_when_base_schema_is_old_and_summary_says_unknown():
    ws = Workspace(src=_db_with_old_plan_schema())      # base_sha 커밋의 스키마가 pr.ids를 모른다 — 기록하면 재적용이 거부된다
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    out = ws.ship("MOCK-7002", "issue/MOCK-7002")
    assert out["publish"]["pr_ids_recorded"] is False and "ids" not in ws.read_plan("MOCK-7002")["pr"]
    ws.acquire("MOCK-7002")
    ws.stage("MOCK-7002", "issue/MOCK-7002")
    summary = ws.db_pr("summary", ws.wt("MOCK-7002"))
    assert all("previous_id" not in row for row in summary["ids"])                       # 기록 없으면 키를 넣지 않는다
    md = ws.run("db_pr.py", ["summary", ws.wt("MOCK-7002"), "--format", "markdown"]).stdout
    assert "- 재할당 내역: 확인 불가 (이전 적용 ID 기록 없음)" in md
    ws.db_pr("discard", ws.wt("MOCK-7002"))


def test_publish_checks_base_sha_schema_not_the_working_copy():
    ws = Workspace(src=_db_with_old_plan_schema())      # base_sha 커밋의 스키마는 pr.ids를 모른다
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7002")
    ws.stage("MOCK-7002", "issue/MOCK-7002")
    wt = ws.wt("MOCK-7002")
    new_schema = (REPO / "plugin" / "schemas" / "plan.schema.json").read_text(encoding="utf-8")
    (wt / "schema" / "plan.schema.json").write_text(new_schema, encoding="utf-8")       # 작업 사본만 pr.ids를 안다
    assert "ids" in json.loads(new_schema)["properties"]["pr"]["properties"]
    summary = ws.db_pr("summary", wt)
    ws.commit("MOCK-7002")
    pub = ws.db_pr("publish", wt, "--branch", "issue/MOCK-7002", "--lease", "new", "--approved", summary["approved_hash"])
    assert pub["pr_ids_recorded"] is False and "ids" not in ws.read_plan("MOCK-7002")["pr"]
    ws.db_pr("discard", wt)


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
    assert any("커밋 메시지" in p and "trailer(Co-Authored-By" in p and "commit_message 그대로" in p for p in out["problems"])
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


def test_pasted_steps_are_removed_when_job_ends():
    """붙여넣은 스텝 원문(steps-pasted.txt)은 discard·lock release(자기 작업)·cleanup이 지운다 (08-safety.md §8.1)."""
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    ws.stage("MOCK-7001", "issue/MOCK-7001")
    pasted = ws.job_dir("MOCK-7001") / "steps-pasted.txt"
    pasted.write_text("1 | 데이터 켜기 | FAIL\n", encoding="utf-8")
    ws.db_pr("discard", ws.wt("MOCK-7001"))
    assert not pasted.exists()

    # discard 없이 끝나는 경로: 자기 작업 lock release (lock이 이미 없어도)
    ws.acquire("MOCK-7002")
    pasted = ws.job_dir("MOCK-7002") / "steps-pasted.txt"
    pasted.parent.mkdir(parents=True, exist_ok=True)
    pasted.write_text("붙여넣기\n", encoding="utf-8")
    ws.db_pr("lock", "release", "MOCK-7002")
    assert not pasted.exists()
    pasted.write_text("붙여넣기\n", encoding="utf-8")
    ws.db_pr("lock", "release", "MOCK-7002")
    assert not pasted.exists()

    # --force(다른 세션의 lock)는 그 작업의 파일을 건드리지 않는다. 남은 파일은 cleanup이 지운다
    ws.acquire("MOCK-7003")
    other = ws.job_dir("MOCK-7003") / "steps-pasted.txt"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("붙여넣기\n", encoding="utf-8")
    ws.db_pr("lock", "release", "MOCK-7003", "--force")
    assert other.exists()
    dry = ws.db_pr("cleanup", "--dry-run")
    assert {"kind": "state", "job": "MOCK-7003", "path": str(other)} in dry["targets"]
    ws.db_pr("cleanup", "--yes")
    assert not other.exists()


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
    ws = Workspace(src=variant_db("issue-db-dup-id"))
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


def _op_of(plan_name: str, op: str) -> dict:
    return next(o for o in load_plan(plan_name)["operations"] if o["op"] == op)


def test_plan_format_error_names_op_missing_and_extra_fields():
    """`계획 형식 오류` 메시지가 op 이름·빠진 필수 필드·허용 밖 필드를 알려 준다(스키마의 op 하위 스키마에서 읽는다)."""
    db = git_db()
    cases = [("p7-analyze-append.plan.json", "append", "cause"),
             ("p7-analyze-new-cause.plan.json", "new-cause", "body"),
             ("p7-record-verified.plan.json", "verify-resolution", "verification")]
    for name, op, required in cases:
        for broken, expect in (("missing", f"빠진 필드 [{required}]"), ("extra", "허용 밖 필드 [foo]")):
            plan = load_plan(name)
            body = next(o for o in plan["operations"] if o["op"] == op)
            if broken == "missing":
                del body[required]
            else:
                body["foo"] = 1
            error = apply_json(db, plan, expect=2)["error"]
            assert error.startswith("계획 형식 오류 (operations/"), error
            assert f"op={op})" in error and expect in error, (op, broken, error)
    plan = load_plan("p7-analyze-append.plan.json")
    plan["operations"][0]["op"] = "no-such-op"
    error = apply_json(db, plan, expect=2)["error"]
    assert error.startswith("계획 형식 오류 (operations/0)") and "알 수 없는 op 'no-such-op'" in error
    assert "허용 op: append" in error and "new-cause" in error
    plan["operations"][0].pop("op")
    assert apply_json(db, plan, expect=2)["error"].startswith("계획 형식 오류")


def test_plan_format_error_names_nested_value_problem_missing_op_and_truncates():
    db = git_db()

    def error_of(plan):
        return apply_json(db, plan, expect=2)["error"]

    def with_cause(change):
        plan = load_plan("p7-analyze-new-cause.plan.json")
        change(plan["operations"][0]["cause"])
        return plan

    err = error_of(with_cause(lambda c: c.pop("resolution_type")))
    assert err.startswith("계획 형식 오류 (operations/0, op=new-cause)") and "resolution_type" in err
    err = error_of(with_cause(lambda c: c.update(resolution_verification={"status": "verified"})))
    assert "op=new-cause" in err and "resolution_verification/status" in err
    err = error_of(with_cause(lambda c: c["fix"].update(status="fixed")))
    assert "cause/fix/status" in err and "'fixed'" in err
    plan = load_plan("p7-record-verified.plan.json")
    body = next(o for o in plan["operations"] if o["op"] == "verify-resolution")
    body["verification"]["status"] = "verified"
    err = error_of(plan)
    assert "op=verify-resolution" in err and "verification" in err and "'status'" in err
    del body["verification"]["status"], body["verification"]["evidence"]
    assert "'evidence' is a required property" in error_of(plan)
    plan = load_plan("p7-analyze-append.plan.json")
    del plan["operations"][0]["op"]
    err = error_of(plan)
    assert err.startswith("계획 형식 오류 (operations/0)") and "op 필드가 없다; 허용 op: append" in err and "allow-cause" in err
    plan = load_plan("p7-analyze-append.plan.json")
    plan["schema_version"] = "x" * 1000
    err = error_of(plan)
    assert err.startswith("계획 형식 오류 (schema_version)") and err.endswith("…") and len(err) < 400


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


def test_apply_masks_failed_step_and_writes_it_before_note():
    db = git_db()
    plan = load_plan("p7-analyze-append.plan.json")
    plan["jira"]["failed_step"] = "고객 010-1234-5678  데이터 켜기"
    apply_json(db, plan)
    text = (db / DATA_DIR / "jira" / "MOCK-7001.yaml").read_text(encoding="utf-8")
    record = yaml.safe_load(text)
    assert "010-1234-5678" not in text and "<MSISDN#" in record["failed_step"] and "  " not in record["failed_step"]
    keys = list(record)
    assert keys.index("failed_step") == keys.index("note") - 1
    lint = run_json("db_lint.py", ["--db", db, "--all"], expect=0)
    assert lint["errors"] == []
    plain = load_plan("p7-analyze-append.plan.json")
    db2 = git_db()
    apply_json(db2, plain)
    assert "failed_step" not in yaml.safe_load((db2 / DATA_DIR / "jira" / "MOCK-7001.yaml").read_text(encoding="utf-8"))


# -- 출력 다이어트: stdout만 줄고 stage.json은 전체 -----------------------------------------------------


def _stage_file(ws: Workspace, job: str) -> dict:
    return json.loads((ws.job_dir(job) / "stage.json").read_text(encoding="utf-8"))


def _assert_stage_json_is_full(ws: Workspace, job: str, branch: str, expect: int, env: dict | None = None,
                               dry_run: bool = False) -> tuple[dict, dict]:
    """기본 stdout을 받고 stage.json이 `--verbose` stdout(변경 전 출력)과 같은지 본다. `(기본 stdout, 전체)`."""
    brief = ws.stage(job, branch, expect=expect, env=env, dry_run=dry_run)
    on_disk = _stage_file(ws, job)
    args = ["stage", ws.job_dir(job) / "plan.json", "--wt", ws.wt(job), "--branch", branch, "--verbose"]
    full = ws.db_pr(*(args + (["--dry-run"] if dry_run else [])), expect=expect, env=env)
    for doc in (on_disk, _stage_file(ws, job)):
        assert {k: v for k, v in doc.items() if k != "worktree"} == {k: v for k, v in full.items() if k != "worktree"}
    assert "folded" not in full and "detail" not in full, "--verbose는 stage.json과 같은 전체"
    assert brief["detail"] == str(ws.job_dir(job) / "stage.json")
    assert ("folded" in brief) == (full.get("stopped") != "drift")
    # 리터럴: 파일은 요약 전 모양 (folded·checks_passed 없음, apply.operations·regress results 있음)
    assert "folded" not in on_disk and "checks_passed" not in json.dumps(on_disk)
    if "apply" in on_disk:
        assert "operations" in on_disk["apply"]
        assert on_disk["checks"]["regress"]["result"]["results"]
        for row in on_disk["checks"]["verify"]["result"]["rules"]:
            assert row["id"] in ("R4", "R5", "R6") or "checks" in row
    assert brief["result"] == full["result"] if "result" in full else brief["stopped"] == full["stopped"]
    return brief, full


def test_stage_json_stays_full_on_success_and_default_stdout_is_summary():
    ws = Workspace()
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7002")
    brief, full = _assert_stage_json_is_full(ws, "MOCK-7002", "issue/MOCK-7002", 0)
    disk = _stage_file(ws, "MOCK-7002")
    # 파일: 요약 전의 모양 그대로 (operations·verify 행 checks·regress results가 있다)
    assert "operations" in disk["apply"] and "db" in disk["apply"]
    rows = {r["id"]: r for r in disk["checks"]["verify"]["result"]["rules"]}
    assert rows["R1"]["checks"] and disk["checks"]["regress"]["result"]["results"]
    assert disk["config_check"].keys() > {"for", "writable", "push_allowed", "reasons"}
    # stdout: 요약
    assert {"job", "wt", "branch", "tool_branch", "base_sha", "plan", "dry_run", "source", "drift", "ids_at_base",
            "worktree", "pending_sources", "result", "detail", "folded"} <= set(brief)
    assert set(brief["config_check"]) == {"for", "writable", "push_allowed", "reasons"}
    assert set(brief["apply"]) <= {"ids", "changed", "fixtures", "feedback", "pending_included", "rejected"}
    assert brief["apply"]["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-03"}]
    checks = brief["checks"]
    assert checks["build"] == checks["ids"] == {"code": 0}
    assert checks["lint"] == {"code": 0, "errors": 0, "warnings": 0} and checks["mask"]["code"] == 0
    assert checks["regress"]["summary"]["failed"] == 0 and "result" not in checks["regress"]
    assert checks["verify"]["code"] == 0
    assert all("checks" not in r for r in checks["verify"]["result"]["rules"] if r["status"] == "pass")
    # 이어지는 summary 화면은 같다
    assert ws.db_pr("summary", ws.wt("MOCK-7002"))["approved_hash"]
    ws.db_pr("discard", ws.wt("MOCK-7002"))


def test_stage_json_stays_full_on_failed_check_drift_and_needs_approval():
    ws = Workspace()
    job = "review-data-2026-10"
    ws.plan(job, _review_plan([{"op": "update-signature", "owner": "DATA-001-02", "kind": "cause",
                                "sig_id": "roaming-disabled",
                                "signature": {"id": "roaming-disabled", "window_sec": 60,
                                              "must_event": [{"event": "data_evaluation_rejected"}]}}],
                              "review/data-2026-10"))
    ws.acquire(job)
    brief, full = _assert_stage_json_is_full(ws, job, "review/data-2026-10", 1)
    assert brief["result"] == "check-failed"
    assert brief["checks"]["verify"] == full["checks"]["verify"] and brief["checks"]["verify"]["code"] == 1   # 비0 단계는 전체
    assert any(r["checks"] for r in full["checks"]["verify"]["result"]["rules"] if r["id"] == "R3")
    ws.db_pr("discard", ws.wt(job))

    ws.plan(job, _review_plan([{"op": "set-resolution", "cause": "DATA-001-02", "resolution": "계획 값"}],
                              "review/data-2026-10"))
    ws.push_main(lambda c: _edit(c / DATA_DIR / "type.md", "resolution: 데이터 로밍 설정을 켠다",
                                 "resolution: 데이터 로밍을 켠다 (다른 PR)"))
    ws.acquire(job)
    brief, full = _assert_stage_json_is_full(ws, job, "review/data-2026-10", 1)
    assert brief["stopped"] == "drift" and brief["drift"] == full["drift"] and brief["next"] == full["next"]
    ws.db_pr("discard", ws.wt(job))

    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    brief, full = _assert_stage_json_is_full(ws, "MOCK-7001", "issue/MOCK-7001", 3, env={"TT_FORCE_VERIFY_EXIT": "3"})
    assert brief["result"] == "needs-approval" and brief["checks"]["verify"] == full["checks"]["verify"]
    assert brief["checks"]["verify"]["code"] == 3
    assert ws.db_pr("summary", ws.wt("MOCK-7001"))["approval_needed"]
    ws.db_pr("discard", ws.wt("MOCK-7001"))


def test_stage_and_verify_stdout_halved():
    """완료 기준: MOCK-7002 new-cause 계획의 `verify --plan --draft` + `stage --dry-run` stdout 합이 기본에서 절반 이하."""
    ws = Workspace()
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.acquire("MOCK-7002")
    plan = ws.job_dir("MOCK-7002") / "plan.json"
    sizes = {}
    for label, extra in (("default", []), ("verbose", ["--verbose"])):
        draft = ws.job_dir("MOCK-7002") / "draft"
        verify = ws.run("db_verify.py", ["rules", "--plan", plan, "--draft", draft, "--db", ws.clone, *extra])
        assert verify.returncode == 0, verify.stderr[-2000:]
        stage = ws.run("db_pr.py", ["stage", plan, "--wt", ws.wt("MOCK-7002"), "--branch", "issue/MOCK-7002",
                                    "--dry-run", *extra])
        assert stage.returncode == 0, stage.stderr[-2000:]
        sizes[label] = (len(verify.stdout.encode()), len(stage.stdout.encode()))
    d, v = sum(sizes["default"]), sum(sizes["verbose"])
    print(f"\nverify+stage stdout bytes: verbose={v} (verify {sizes['verbose'][0]} + stage {sizes['verbose'][1]}) "
          f"default={d} (verify {sizes['default'][0]} + stage {sizes['default'][1]})")
    assert d * 2 <= v, sizes
    ws.db_pr("discard", ws.wt("MOCK-7002"))


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


# -- 3D-A: 계획 형식 검사·오류 표시·drift 계획 값·번호 재할당 -----------------------------------------------


def _raw_plan(ws: Workspace, job: str, plan: dict) -> None:
    path = ws.job_dir(job) / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")


def _stage_raw(ws: Workspace, job: str, branch: str):
    return ws.run("db_pr.py", ["stage", ws.job_dir(job) / "plan.json", "--wt", ws.wt(job), "--branch", branch])


def test_stage_rejects_malformed_plan_before_touching_job():
    ws = Workspace()
    job = "MOCK-7300"
    ws.acquire(job)
    # e19/e20 모양: operations 대신 ops, base_sha·schema_version·started_at 없음
    _raw_plan(ws, job, {"source": "analyze", "ops": [{"op": "append", "cause": "DATA-001-01"}]})
    proc = _stage_raw(ws, job, "issue/MOCK-7300")
    assert proc.returncode == 2
    assert proc.stderr.startswith("계획 형식 오류:"), proc.stderr
    assert "ops" in proc.stderr and "operations" in proc.stderr and "base_sha" in proc.stderr
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
    detail = json.loads(proc.stdout)
    assert "ops" in detail["unknown_keys"] and "base_sha" in detail["missing_keys"]
    assert not ws.wt(job).exists() and not (ws.job_dir(job) / "state.json").exists()

    plan = load_plan("p7-analyze-new-cause.plan.json")
    plan.pop("base_sha", None)
    _raw_plan(ws, job, plan)
    proc = _stage_raw(ws, job, "issue/MOCK-7300")
    assert proc.returncode == 2 and proc.stderr.startswith("계획 형식 오류:") and "base_sha" in proc.stderr

    (ws.job_dir(job) / "plan.json").write_text("{not json", encoding="utf-8")
    proc = _stage_raw(ws, job, "issue/MOCK-7300")
    assert proc.returncode == 2 and proc.stderr.startswith("계획 형식 오류: JSON을 읽을 수 없습니다")
    (ws.job_dir(job) / "plan.json").write_text("[1]", encoding="utf-8")
    assert _stage_raw(ws, job, "issue/MOCK-7300").returncode == 2


def test_stage_internal_error_shows_last_line_without_traceback():
    ws = Workspace()
    job = "MOCK-7301"
    plan = _review_plan([{"op": "append"}], "issue/MOCK-7301")      # cause 없음 → drift 스크립트가 KeyError
    ws.plan(job, plan, base_sha=ws.main_sha())
    ws.push_main(lambda c: (c / "NOTE.txt").write_text("main 이동\n", encoding="utf-8"))
    ws.acquire(job)
    proc = _stage_raw(ws, job, "issue/MOCK-7301")
    assert proc.returncode == 2
    assert "KeyError" in proc.stderr and "내부 오류" in proc.stderr
    assert "Traceback" not in proc.stderr and "File \"" not in proc.stderr


def test_drift_shows_plan_value_and_ids_at_base_for_new_cause_and_resolution():
    """e16 모양: 계획 당시 값·계획 값·현재 값이 다르고, main이 같은 번호를 먼저 써서 ID가 밀린다."""
    ws = Workspace()
    job = "MOCK-7302"
    plan = radio_off_plan("MOCK-7302")
    plan["operations"].append({"op": "set-resolution", "cause": "DATA-001-02", "resolution": "계획이 쓰는 해결책"})
    ws.plan(job, plan)
    ws.put(job, "fixtures/cut-1.log", radio_off_log())
    ws.plan("MOCK-7002", "p7-analyze-new-cause.plan.json")          # 다른 사람의 PR이 DATA-001-03을 먼저 쓴다
    ws.put("MOCK-7002", "fixtures/cut-1.log", SIM_LOG)
    ws.ship("MOCK-7002", "issue/MOCK-7002")
    ws.merge("issue/MOCK-7002")
    ws.push_main(lambda c: _edit(c / DATA_DIR / "type.md", "resolution: 데이터 로밍 설정을 켠다",
                                 "resolution: main이 바꾼 해결책"))
    ws.acquire(job)
    out = ws.stage(job, "issue/MOCK-7302", expect=1)
    assert out["stopped"] == "drift"
    item = next(d for d in out["drift"] if d["op"] == "set-resolution")
    assert item["plan_value"] == "계획이 쓰는 해결책"
    assert item["plan_base_value"] == "데이터 로밍 설정을 켠다" and item["current_value"] == "main이 바꾼 해결책"
    assert out["ids_at_base"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-03"}]
    assert "plan_value" in out["next"] and "current_value" in out["next"]

    plan = ws.read_plan(job)
    ws.plan(job, plan, base_sha=out["base_sha"])
    out = ws.stage(job, "issue/MOCK-7302")          # drift를 다시 돌리지 않아도 계획 당시 번호를 이어받는다
    assert out["apply"]["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04"}]
    assert out["ids_at_base"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-03"}]
    summary = ws.db_pr("summary", ws.wt(job))
    assert summary["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-04", "expected_at_base": "DATA-001-03"}]
    ws.db_pr("discard", ws.wt(job))


# -- W5: stage --then-summary · publish --commit · publish --and-discard -------------------------------------------


def _state(ws: Workspace, job: str) -> dict:
    return json.loads((ws.job_dir(job) / "state.json").read_text(encoding="utf-8"))


def _staged_job(ws: Workspace, job: str = "MOCK-7002", plan: str = "p7-analyze-new-cause.plan.json") -> Path:
    ws.plan(job, plan)
    if plan == "p7-analyze-new-cause.plan.json":
        ws.put(job, "fixtures/cut-1.log", SIM_LOG)
    ws.acquire(job)
    return ws.wt(job)


def _then_summary(ws: Workspace, job: str, branch: str, *extra, **kw):
    return ws.run("db_pr.py", ["stage", ws.job_dir(job) / "plan.json", "--wt", ws.wt(job), "--branch", branch,
                               "--then-summary", *extra], **kw)


def _publish_args(ws: Workspace, job: str, branch: str, *extra, lease: str = "new") -> list:
    return ["publish", ws.wt(job), "--branch", branch, "--lease", lease,
            "--approved", _state(ws, job)["approved_hash"], *extra]


def test_stage_then_summary_prints_same_markdown_as_summary():
    ws = Workspace()
    wt = _staged_job(ws)
    job = ws.job_dir("MOCK-7002")
    out = _then_summary(ws, "MOCK-7002", "issue/MOCK-7002")
    assert out.returncode == 0 and out.stdout.startswith("## push 전 확인: MOCK-7002 → DATA-001-03 SIM 미준비\n")
    assert not out.stdout.lstrip().startswith("{")                       # stage JSON은 stdout에 없다
    separate = ws.run("db_pr.py", ["summary", wt, "--format", "markdown"])
    assert separate.returncode == 0 and out.stdout == separate.stdout    # 같은 바이트
    state = _state(ws, "MOCK-7002")
    assert state["approved_hash"] and state["commit_message"] and out.stdout.splitlines()[-1] == \
        f"approved_hash: {state['approved_hash']}"
    assert (job / "pr.json").is_file()
    disk = json.loads((job / "stage.json").read_text(encoding="utf-8"))   # stage.json은 그대로 전체
    assert "operations" in disk["apply"] and disk["result"] == "ok"
    ws.db_pr("discard", wt)


def test_stage_then_summary_keeps_needs_approval_exit_3():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    out = _then_summary(ws, "MOCK-7001", "issue/MOCK-7001", env={"TT_FORCE_VERIFY_EXIT": "3"})
    assert out.returncode == 3 and out.stdout.startswith("## push 전 확인: ")
    assert "메인테이너 승인 필수" in out.stdout and "승인 필요: 없음" not in out.stdout
    assert _state(ws, "MOCK-7001")["approved_hash"] and (ws.job_dir("MOCK-7001") / "pr.json").is_file()
    ws.db_pr("discard", wt)


def test_stage_then_summary_skips_summary_on_drift_and_check_failure():
    ws = Workspace()
    job = "review-data-2026-10"
    ws.plan(job, _review_plan([{"op": "update-signature", "owner": "DATA-001-02", "kind": "cause",
                                "sig_id": "roaming-disabled",
                                "signature": {"id": "roaming-disabled", "window_sec": 60,
                                              "must_event": [{"event": "data_evaluation_rejected"}]}}],
                              "review/data-2026-10"))
    ws.acquire(job)
    out = _then_summary(ws, job, "review/data-2026-10")
    assert out.returncode == 1 and json.loads(out.stdout)["result"] == "check-failed"   # 기존 stage 요약 JSON
    assert _state(ws, job)["approved_hash"] is None and not (ws.job_dir(job) / "pr.json").exists()
    ws.db_pr("discard", ws.wt(job))

    ws.plan(job, _review_plan([{"op": "set-resolution", "cause": "DATA-001-02", "resolution": "계획 값"}],
                              "review/data-2026-10"))
    ws.push_main(lambda c: _edit(c / DATA_DIR / "type.md", "resolution: 데이터 로밍 설정을 켠다",
                                 "resolution: 데이터 로밍을 켠다 (다른 PR)"))
    ws.acquire(job)
    out = _then_summary(ws, job, "review/data-2026-10")
    assert out.returncode == 1 and json.loads(out.stdout)["stopped"] == "drift"
    assert _state(ws, job)["approved_hash"] is None and not (ws.job_dir(job) / "pr.json").exists()
    ws.db_pr("discard", ws.wt(job))


def test_stage_then_summary_rejects_json_and_verbose():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.acquire("MOCK-7001")
    for flag in ("--json", "--verbose"):
        out = _then_summary(ws, "MOCK-7001", "issue/MOCK-7001", flag)
        assert out.returncode == 2 and out.stdout == "" and "--then-summary" in out.stderr, flag
    assert not ws.wt("MOCK-7001").exists(), "사용 오류는 stage를 돌리기 전에 난다"
    ws.db_pr("lock", "release", "MOCK-7001")


def test_stage_then_summary_dry_run_shows_push_note():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    out = _then_summary(ws, "MOCK-7001", "issue/MOCK-7001", "--dry-run", unauth=True)
    assert out.returncode == 0 and "push 불가: gh 인증 없음 (--dry-run)" in out.stdout
    assert out.stdout.splitlines()[-1].startswith("approved_hash: ")
    ws.db_pr("discard", wt)


def test_stage_then_summary_reports_summary_failure_after_stage(tmp_path):
    ws = Workspace()
    wt = _staged_job(ws)
    shim = tmp_path / "bin"
    shim.mkdir()
    real_path = mock_env.env_with_mocks(plugin_root=ws.root)["PATH"]
    (shim / "gh").write_text('#!/bin/sh\nif [ "$1" = pr ] && [ "$2" = list ]; then echo "not json"; exit 0; fi\n'
                             f'PATH="{real_path}"; exec gh "$@"\n', encoding="utf-8")
    (shim / "gh").chmod(0o755)
    out = _then_summary(ws, "MOCK-7002", "issue/MOCK-7002", env={"PATH": f"{shim}:{real_path}"})
    assert out.returncode == 2
    assert "stage 성공, summary 실패:" in out.stderr and f"db_pr summary {wt} --format markdown만 다시 부른다" in out.stderr
    shown = json.loads(out.stdout)
    assert shown["result"] == "ok" and shown["summary_error"] and "approved_hash" not in shown
    assert (ws.job_dir("MOCK-7002") / "stage.json").is_file()
    retry = ws.run("db_pr.py", ["summary", wt, "--format", "markdown"])      # 안내대로 summary만 다시
    assert retry.returncode == 0 and retry.stdout.startswith("## push 전 확인")
    ws.db_pr("discard", wt)


def _remote_branch_appears(ws: Workspace, branch: str) -> None:
    """다른 사람이 같은 이름의 브랜치를 먼저 올렸다 → `--lease new`가 거부된다."""
    other = ws.other_clone()
    git(other, "checkout", "-q", "-b", branch, "origin/main")
    (other / "extra.txt").write_text("리뷰어\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "다른 사람의 push")
    git(other, "push", "-q", "origin", f"{branch}:refs/heads/{branch}")


def test_publish_commit_commits_approved_message_once_and_pushes():
    ws = Workspace()
    wt = _staged_job(ws)
    assert _then_summary(ws, "MOCK-7002", "issue/MOCK-7002").returncode == 0
    state = _state(ws, "MOCK-7002")
    assert git(wt, "rev-parse", "HEAD") == state["base_sha"], "summary까지는 커밋이 없다"
    out = ws.db_pr(*_publish_args(ws, "MOCK-7002", "issue/MOCK-7002", "--commit"))
    assert out["published"] is True and out["pushed"] is True
    assert out["commit"]["committed"] is True and out["commit"]["sha"] == out["head_sha"]
    assert git(wt, "log", "-1", "--format=%B").strip() == state["commit_message"].strip()
    assert git(wt, "rev-parse", "HEAD^") == state["base_sha"] and git(wt, "rev-parse", "HEAD^{tree}") == state["approved_hash"]
    assert git(ws.remote, "rev-parse", "issue/MOCK-7002") == out["head_sha"]
    assert not (ws.job_dir("MOCK-7002") / "commit-msg.txt").exists(), "메시지 임시 파일은 지운다"
    assert len(ws.prs()) == 1
    ws.db_pr("discard", wt)


def test_publish_commit_rejects_changes_after_approval_without_committing():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    args = _publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit")
    (wt / "CONTRIBUTING.md").write_text("승인 뒤 수정\n", encoding="utf-8")
    out = ws.db_pr(*args, expect=1)
    assert out["published"] is False and out["commit"] == {"committed": False}
    assert any("승인 뒤 파일이 바뀌었다" in p for p in out["problems"])
    assert git(wt, "rev-parse", "HEAD") == _state(ws, "MOCK-7001")["base_sha"], "커밋하지 않았다"
    assert git(ws.remote, "branch", "--list", "issue/MOCK-7001") == ""
    wrong = list(args)
    wrong[wrong.index("--approved") + 1] = "0" * 40                      # --approved가 다르면 역시 1
    assert ws.db_pr(*wrong, expect=1)["commit"] == {"committed": False}
    ws.db_pr("discard", wt)


def test_publish_commit_requires_githooks_hookspath():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    git(ws.clone, "config", "core.hooksPath", "hooks")
    out = ws.run("db_pr.py", _publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit"))
    assert out.returncode == 2 and "core.hooksPath" in out.stderr and ".githooks" in out.stderr
    assert git(wt, "rev-parse", "HEAD") == _state(ws, "MOCK-7001")["base_sha"]
    git(ws.clone, "config", "core.hooksPath", ".githooks")
    assert ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit"))["pushed"] is True
    ws.db_pr("discard", wt)


def test_publish_commit_message_with_shell_metacharacters_is_data():
    ws = Workspace()
    plan = load_plan("p7-analyze-append.plan.json")
    plan["commit_message"] = plan["commit_message"] + ' $(touch INJECTED) `touch INJECTED2` "q" \'s\' ; touch INJECTED3'
    ws.plan("MOCK-7001", plan)
    wt = ws.wt("MOCK-7001")
    ws.acquire("MOCK-7001")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    message = _state(ws, "MOCK-7001")["commit_message"]
    assert "$(touch INJECTED)" in message
    out = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit"))
    assert git(wt, "log", "-1", "--format=%B").strip() == message.strip()
    for name in ("INJECTED", "INJECTED2", "INJECTED3"):
        assert not list(ws.base.rglob(name)) and not (wt / name).exists() and not Path(name).exists(), name
    assert out["commit"]["committed"] is True
    ws.db_pr("discard", wt)


def test_publish_commit_is_idempotent_after_lease_rejected():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    _remote_branch_appears(ws, "issue/MOCK-7001")
    out = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit"), expect=1)
    assert out["pushed"] is False and out["commit"]["committed"] is True
    sha = git(wt, "rev-parse", "HEAD")
    remote = git(ws.remote, "rev-parse", "issue/MOCK-7001")
    again = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit", lease=remote))   # 올바른 lease로 재시도
    assert again["commit"] == {"skipped": "이미 커밋됨"} and again["published"] is True
    assert again["head_sha"] == sha == git(wt, "rev-parse", "HEAD"), "커밋을 또 만들지 않는다"
    assert git(wt, "rev-parse", "HEAD^") == _state(ws, "MOCK-7001")["base_sha"]
    ws.db_pr("discard", wt)


def test_publish_and_discard_cleans_up_after_success():
    ws = Workspace()
    wt = _staged_job(ws)
    assert _then_summary(ws, "MOCK-7002", "issue/MOCK-7002").returncode == 0
    out = ws.db_pr(*_publish_args(ws, "MOCK-7002", "issue/MOCK-7002", "--commit", "--and-discard"))
    assert out["published"] is True and out["pr"]["action"] == "created"
    assert out["discard"]["discarded"] is True and out["discard"]["deleted_branch"] == "tt/issue/MOCK-7002"
    assert not wt.exists() and not (ws.job_dir("MOCK-7002") / "state.json").exists()
    assert ws.db_pr("lock", "status")["held"] is False and (ws.job_dir("MOCK-7002") / "plan.json").is_file()
    assert git(ws.clone, "for-each-ref", "refs/heads/tt/") == ""


def test_publish_and_discard_keeps_work_on_publish_failure():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    _remote_branch_appears(ws, "issue/MOCK-7001")
    out = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit", "--and-discard"), expect=1)
    assert out["pushed"] is False
    assert out["discard"] == {"discarded": False, "skipped": "publish 실패 — worktree·lock 보존"}
    assert wt.is_dir() and (ws.job_dir("MOCK-7001") / "state.json").is_file()
    assert ws.db_pr("lock", "status")["held"] is True
    ws.db_pr("discard", wt)


def test_publish_and_discard_reports_discard_failure_exit_2():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    git(ws.clone, "worktree", "lock", str(wt))                  # worktree remove --force가 거부한다
    out = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit", "--and-discard"), expect=2)
    assert out["published"] is True and out["pr"]["url"] and len(ws.prs()) == 1
    assert out["discard"]["discarded"] is False and out["discard"]["error"]
    assert out["discard"]["next"] == f"PR은 만들어졌다. publish를 다시 하지 말고 db_pr discard {wt}만 다시 한다"
    git(ws.clone, "worktree", "unlock", str(wt))
    assert ws.db_pr("discard", wt)["discarded"] is True and not wt.exists()


def test_ship_combined_path_matches_separate_path():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    separate = ws.ship("MOCK-7001", "issue/MOCK-7001")
    ws2 = Workspace()
    ws2.plan("MOCK-7001", "p7-analyze-append.plan.json")
    combined = ws2.ship("MOCK-7001", "issue/MOCK-7001", combined=True)
    a, b = separate["publish"], combined["publish"]
    assert a["published"] is b["published"] is True and a["pr"]["action"] == b["pr"]["action"]
    assert separate["summary"]["approved_hash"] == combined["summary"]["approved_hash"]   # 같은 승인 트리
    assert b["commit"]["committed"] is True and b["discard"]["discarded"] is True
    assert ws.remote_files("issue/MOCK-7001") == ws2.remote_files("issue/MOCK-7001")
    assert git(ws.remote, "log", "-1", "--format=%B", "issue/MOCK-7001") == \
        git(ws2.remote, "log", "-1", "--format=%B", "issue/MOCK-7001")
    assert not ws2.wt("MOCK-7001").exists() and ws2.db_pr("lock", "status")["held"] is False


# -- W5 리뷰 반영: publish --commit의 guard 검사·pre-commit 실패·이미 커밋된 경로, --and-discard 분기 ------------------


def _approved_then(ws: Workspace, job: str, branch: str, change) -> Path:
    """stage → (확인 화면 전) wt를 `change`로 바꾼다 → summary로 승인 해시를 만든다. 승인 해시는 바뀐 트리를 담는다."""
    wt = _staged_job(ws, job, "p7-analyze-append.plan.json")
    ws.stage(job, branch)
    change(wt)
    ws.db_pr("summary", wt)
    return wt


def _assert_commit_refused(ws: Workspace, wt: Path, job: str, branch: str) -> dict:
    out = ws.db_pr(*_publish_args(ws, job, branch, "--commit", "--and-discard"), expect=1)
    assert out["published"] is False and out["commit"] == {"committed": False}
    assert out["discard"]["skipped"] == "publish 실패 — worktree·lock 보존"
    assert git(wt, "rev-parse", "HEAD") == _state(ws, job)["base_sha"], "커밋하지 않았다"
    assert git(ws.remote, "branch", "--list", branch) == "" and wt.is_dir()
    return out


def test_publish_commit_refuses_unmasked_pii_in_approved_tree_rule_3():
    ws = Workspace()
    jira = f"{DATA_DIR}/jira/MOCK-1101.yaml"
    wt = _approved_then(ws, "MOCK-7001", "issue/MOCK-7001", lambda w: (w / jira).write_text(
        (w / jira).read_text(encoding="utf-8").replace("접수됨", "접수됨 imei=490154203237518"), encoding="utf-8"))
    out = _assert_commit_refused(ws, wt, "MOCK-7001", "issue/MOCK-7001")
    text = "\n".join(out["problems"])
    assert "마스킹 안 된 개인정보가 있다 (규칙 3)" in text and "IMEI" in text
    assert "계획을 고쳐 3번(stage --then-summary)부터 다시 한다." in text and "직접" not in text and "add한다" not in text
    ws.db_pr("discard", wt)


def test_publish_commit_refuses_hand_edited_generated_file_rule_4():
    ws = Workspace()
    wt = _approved_then(ws, "MOCK-7001", "issue/MOCK-7001", lambda w: (w / "README.md").write_text(
        (w / "README.md").read_text(encoding="utf-8") + "\n손으로 고친 줄\n", encoding="utf-8"))
    out = _assert_commit_refused(ws, wt, "MOCK-7001", "issue/MOCK-7001")
    text = "\n".join(out["problems"])
    assert "생성 파일(README·STATS·CHANGELOG)이 원본과 맞지 않는다 (규칙 4)" in text and "README.md" in text
    assert "계획을 고쳐 3번(stage --then-summary)부터 다시 한다." in text and "db_build.py --write" not in text
    ws.db_pr("discard", wt)


def test_publish_commit_reports_precommit_failure_without_pushing():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    cfg_path = ws.home / "config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg["plugin"]["scripts_path"] = str(ws.base / "nowhere")        # pre-commit hook이 스크립트를 못 찾는다
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    out = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit", "--and-discard"), expect=1)
    assert out["published"] is False and out["commit"] == {"committed": False}
    assert any("git commit 실패" in p and "scripts_path" in p for p in out["problems"]), out["problems"]
    assert out["discard"]["discarded"] is False
    assert git(wt, "rev-parse", "HEAD") == _state(ws, "MOCK-7001")["base_sha"]
    assert git(ws.remote, "branch", "--list", "issue/MOCK-7001") == "" and not ws.prs()
    assert not (ws.job_dir("MOCK-7001") / "commit-msg.txt").exists()
    ws.db_pr("discard", wt)


def test_publish_commit_checks_tree_of_already_committed_path():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    args = _publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit")
    (wt / "CONTRIBUTING.md").write_text("승인 뒤 수정\n", encoding="utf-8")
    ws.commit("MOCK-7001")                                           # 승인 해시와 다른 트리를 이미 커밋했다
    out = ws.db_pr(*args, expect=1)
    assert out["published"] is False and out["commit"] == {"skipped": "이미 커밋됨"}
    assert any("커밋 트리가 승인 해시와 다르다" in p for p in out["problems"])
    assert git(ws.remote, "branch", "--list", "issue/MOCK-7001") == "" and not ws.prs()
    ws.db_pr("discard", wt)


def test_publish_and_discard_keeps_work_when_only_pr_creation_fails(tmp_path):
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    shim = tmp_path / "bin"
    shim.mkdir()
    real_path = mock_env.env_with_mocks(plugin_root=ws.root)["PATH"]
    (shim / "gh").write_text('#!/bin/sh\nif [ "$1" = pr ] && [ "$2" = create ]; then echo "boom" >&2; exit 1; fi\n'
                             f'PATH="{real_path}"; exec gh "$@"\n', encoding="utf-8")
    (shim / "gh").chmod(0o755)
    out = ws.db_pr(*_publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit", "--and-discard"),
                   env={"PATH": f"{shim}:{real_path}"}, expect=2)
    assert out["published"] is True and out["pushed"] is True and "gh_error" in out and not ws.prs()
    assert out["discard"]["discarded"] is False
    assert out["discard"]["skipped"] == "PR 생성 실패 — worktree·lock 보존"
    assert f"db_pr discard {wt}" in out["discard"]["next"] and "publish" in out["discard"]["next"]
    assert wt.is_dir() and (ws.job_dir("MOCK-7001") / "state.json").is_file()
    assert ws.db_pr("lock", "status")["held"] is True
    assert git(ws.remote, "branch", "--list", "issue/MOCK-7001") != ""      # push는 됐다
    ws.db_pr("discard", wt)


def test_guard_and_db_pr_share_rule_3_4_deny_messages():
    """guard.py와 db_pr publish --commit의 규칙 3·4 문구는 `checks.guard_deny_messages` 하나에서 나온다 (drift 방지)."""
    import db_pr
    from common import checks

    S = checks.StepResult
    steps = [S("mask", 1, data={"detections": [{"path": "a.yaml", "line": 3, "kind": "IMEI"}]}),
             S("cache", 1, data={"paths": [".cache/x", ".cache/y"]}),
             S("generated_staged", 1, data={"paths": ["README.md"]}),                     # script None = actions-build
             S("generated", 1, script="db_build.py", data={"problems": [{"path": "README.md", "status": "stale"}]})]
    assert checks.guard_deny_messages(steps) == [          # guard.py의 기존 문구(바이트 동일)
        "staged 변경에 마스킹 안 된 개인정보가 있다 (규칙 3): a.yaml:3 IMEI. mask_pii로 마스킹한 뒤 다시 add한다.",
        ".cache/는 커밋하지 않는다 (규칙 4): .cache/x, .cache/y",
        "ci_mode: actions-build — 생성 파일은 머지 후 봇이 만든다. staged에서 뺀다 (규칙 4): README.md",
        "생성 파일(README·STATS·CHANGELOG)이 원본과 맞지 않는다 (규칙 4): README.md (stale). "
        "직접 고치지 말고 db_build.py --write로 다시 만든 뒤 add한다."]
    tail = db_pr._GUARD_FIX_TAIL
    assert tail == "계획을 고쳐 3번(stage --then-summary)부터 다시 한다."
    swapped = checks.guard_deny_messages(steps, fix_tail=tail)
    assert [m.endswith(tail) for m in swapped] == [True, False, True, True]
    assert swapped[0].startswith("staged 변경에 마스킹 안 된 개인정보가 있다 (규칙 3): a.yaml:3 IMEI. ")
    assert swapped[1] == ".cache/는 커밋하지 않는다 (규칙 4): .cache/x, .cache/y"
    for path in (REPO / "plugin/scripts/guard.py", REPO / "plugin/scripts/db_pr.py"):   # 문구를 다시 복제하지 않았다
        src = path.read_text(encoding="utf-8")
        assert "guard_deny_messages" in src and "마스킹 안 된 개인정보" not in src and "원본과 맞지 않는다" not in src, path


def test_publish_commit_rejects_non_mapping_or_broken_issue_db_config_as_usage_error():
    ws = Workspace()
    wt = _staged_job(ws, "MOCK-7001", "p7-analyze-append.plan.json")
    assert _then_summary(ws, "MOCK-7001", "issue/MOCK-7001").returncode == 0
    for text, needle in (("- 목록\n- 이다\n", "매핑"), ("a: [unclosed\n", "YAML")):
        (wt / "issue-db.config.yaml").write_text(text, encoding="utf-8")
        state = _state(ws, "MOCK-7001")
        state["approved_hash"] = _approved_now(wt)                 # 바뀐 트리를 승인한 것으로 맞춘다 (guard 단계까지 가려고)
        (ws.job_dir("MOCK-7001") / "state.json").write_text(json.dumps(state), encoding="utf-8")
        out = ws.run("db_pr.py", _publish_args(ws, "MOCK-7001", "issue/MOCK-7001", "--commit"))
        assert out.returncode == 2 and needle in out.stderr and "Traceback" not in out.stderr, (text, out.stderr[-400:])
        assert git(wt, "rev-parse", "HEAD") == state["base_sha"]
    ws.db_pr("discard", wt)


def _approved_now(wt: Path) -> str:
    import db_pr
    return db_pr.approved_hash(wt)
