#!/usr/bin/env python3
"""성공 흐름 작성·검증 (04-parser-matching.md §5.13 (4), contracts.md §작업 계획 put-flow):
계획 op `put-flow`(추가·교체·거부, fixture 3단 마스킹), `new-cause`·`new-type`의 `flow_step` 옮김, drift(추가인데 생김·교체인데
바뀜), 초안 검증 지문, `db_lint` 흐름 검사, `db_regress`의 흐름 fixture 판정·범위, `db_verify rules` R4, pre-commit(흐름만 바뀐 커밋).
흐름 정의는 시드 계획(`templates/issue-db-seeds/android/data/plan.json`)의 put-flow 한 벌을 쓴다. 로그는 합성(마스킹 토큰·TEST-NET IP)."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import draftcheck  # noqa: E402
from runner import copy_db, edit, git, git_db, run, run_json, tmp  # noqa: E402

SEEDS = REPO / "templates" / "issue-db-seeds" / "android"
D = "data/DATA-001-no-setup-data-call"
FLOW_DIR = "data/flows"


def _seed_op(cat: str = "data") -> dict:
    plan = json.loads((SEEDS / cat / "plan.json").read_text(encoding="utf-8"))
    return next(op for op in plan["operations"] if op["op"] == "put-flow")


FLOW = _seed_op()["flow"]
NORMAL = (SEEDS / "data" / "flows" / "fixtures" / "data-setup.normal.1.log").read_text(encoding="utf-8")
RAW = NORMAL.replace("<IP#1>", "192.0.2.15").replace("<IP#2>", "192.0.2.3").replace("<IP#3>", "192.0.2.2")


def _plan(*ops) -> dict:
    return {"source": "review", "schema_version": 1, "started_at": "2026-11-15T10:00+09:00", "base_sha": "0" * 40,
            "issue": None, "feedback": None, "included_pending": [], "commit_message": "[flow] data/data-setup",
            "pr": {"number": None, "branch": "review/flow-1", "head_sha": None}, "operations": list(ops)}


def _put(flow=None, fixtures=("normal.log",), ref="data/data-setup") -> dict:
    op = {"op": "put-flow", "ref": ref, "flow": copy.deepcopy(flow or FLOW)}
    if fixtures:
        op["fixtures"] = [{"path": f, "origin": "synthetic"} for f in fixtures]
    return op


def _apply(db: Path, *ops, logs: dict | None = None, expect=0) -> dict:
    job = tmp("tt-flowop-")
    for name, text in (logs if logs is not None else {"normal.log": RAW}).items():
        (job / name).write_text(text, encoding="utf-8", newline="\n")
    (job / "plan.json").write_text(json.dumps(_plan(*ops), ensure_ascii=False), encoding="utf-8")
    return run_json("db_add.py", ["apply", job / "plan.json", "--db", db, "--user", "tester"], expect=expect)


def _rejected(out: dict) -> str:
    assert out["applied"] is False, out
    return out["rejected"][0]["code"]


def _with_flow(db: Path) -> Path:
    _apply(db, _put())
    return db


def _set_flow_step(db: Path, value: str, cause: str = "DATA-001-01") -> None:
    [type_md] = (db / "data").glob(f"{cause[:-3]}-*/type.md")
    edit(type_md, f"  - id: {cause}\n", f"  - id: {cause}\n    flow_step: {value}\n")


def _lint(db: Path) -> dict[str, list[str]]:
    out = run_json("db_lint.py", ["--db", db, "--all"], expect=(0, 1))
    found: dict[str, list[str]] = {}
    for item in out["errors"] + out["warnings"]:
        found.setdefault(item["code"], []).append(f"{item['level']}:{item['message']}")
    return found


# -- put-flow ---------------------------------------------------------------------------------------


def test_put_flow_adds_flow_and_masked_fixture_then_replaces_with_next_number():
    db = copy_db()
    out = _apply(db, _put())
    assert out["applied"] and {c["path"] for c in out["changed"]} == {
        f"{FLOW_DIR}/data-setup.yaml", f"{FLOW_DIR}/fixtures/data-setup.normal.1.log"}
    assert yaml.safe_load((db / FLOW_DIR / "data-setup.yaml").read_text(encoding="utf-8")) == FLOW
    log = (db / FLOW_DIR / "fixtures" / "data-setup.normal.1.log").read_text(encoding="utf-8")
    assert "192.0.2." not in log and "addresses=[<IP#" in log, "add-fixture와 같은 3단 마스킹"
    # 교체: 내용은 통째로 바뀌고 fixture는 다음 빈 번호. 이번 op에 fixture가 없어도 트리에 있으면 된다
    changed = {**copy.deepcopy(FLOW), "title": "데이터 연결 2"}
    _apply(db, _put(changed))
    _apply(db, _put(changed, fixtures=()))
    assert yaml.safe_load((db / FLOW_DIR / "data-setup.yaml").read_text(encoding="utf-8"))["title"] == "데이터 연결 2"
    assert sorted(p.name for p in (db / FLOW_DIR / "fixtures").iterdir()) == ["data-setup.normal.1.log", "data-setup.normal.2.log"]
    assert not {k for k in _lint(db) if k.startswith("flow")}


def test_put_flow_rejections():
    db = copy_db()
    assert _rejected(_apply(db, _put(fixtures=()), expect=1)) == "flow-fixture-missing"
    assert _rejected(_apply(db, _put({**FLOW, "id": "other"}), expect=1)) == "flow-id"
    broken = {k: v for k, v in FLOW.items() if k != "steps"}
    out = _apply(db, _put(broken), expect=1)
    assert _rejected(out) == "flow-schema" and "steps" in out["rejected"][0]["message"]
    assert _rejected(_apply(db, _put(ref="nocat/data-setup"), expect=1)) == "category"
    assert not (db / FLOW_DIR).exists(), "거부되면 아무것도 쓰지 않는다"
    # 바꿀 때 없어지는 단계를 원인 flow_step이 가리키면 거부, 남는 단계면 통과
    _with_flow(db)
    _set_flow_step(db, "data/data-setup/validated")
    fewer = {**copy.deepcopy(FLOW), "steps": FLOW["steps"][:3]}
    out = _apply(db, _put(fewer, fixtures=()), expect=1)
    assert _rejected(out) == "flow-step-in-use" and "DATA-001-01" in out["rejected"][0]["message"]
    assert "그 단계 id를 남긴다" in out["rejected"][0]["message"], "지금 할 수 있는 행동만 안내한다(F-15)"
    _apply(db, _put({**copy.deepcopy(FLOW), "title": "바뀐 제목"}, fixtures=()))


def test_plan_schema_rejects_bad_put_flow_and_flow_step_shape():
    db = copy_db()
    job = tmp("tt-flowop-")
    bad = _put()
    bad["path"] = "flow.yaml"           # 흐름은 경로가 아니라 op 안의 객체로만 싣는다(V-6)
    (job / "plan.json").write_text(json.dumps(_plan(bad), ensure_ascii=False), encoding="utf-8")
    proc = run("db_add.py", ["apply", job / "plan.json", "--db", db, "--user", "tester"])
    assert proc.returncode == 2 and "put-flow" in proc.stderr and "path" in proc.stderr


NEW_CAUSE = {"title": "시험 원인", "description": "설명", "resolution": "해결", "resolution_type": "user-setting",
             "signatures": [{"id": "c", "must_match": ["flow op probe .*why=x"], "window_sec": 60}],
             "fix": {"status": "not-a-bug", "ref": None, "fixed_in": []}}


def test_new_cause_and_new_type_carry_flow_step():
    db = copy_db()
    first = {**NEW_CAUSE, "flow_step": "data/data-setup/connected"}
    ops = [_put(),
           {"op": "new-cause", "temp_id": "NEW-CAUSE-1", "type": "DATA-001",
            "cause": {**NEW_CAUSE, "flow_step": "data/data-setup/response"}, "body": "- **확인 방법**: 시험\n"},
           {"op": "new-type", "temp_id": "NEW-TYPE-1", "category": "data", "dir_slug": "flow-op-probe",
            "type": {"title": "시험 연결이 끊김", "summary": "시험", "tags": [],
                     "symptom_signatures": [{"id": "s", "must_match": ["flow op probe"], "window_sec": 60}]},
            "first_cause": {"temp_id": "NEW-CAUSE-2", "cause": first, "body": "- **확인 방법**: 시험\n"},
            "body": "## 증상\n\n시험.\n"}]
    out = _apply(db, *ops)
    ids = {i["temp_id"]: i["id"] for i in out["ids"]}
    causes = {}
    for type_md in (db / "data").glob("*/type.md"):
        front = yaml.safe_load(type_md.read_text(encoding="utf-8").split("---\n")[1])
        causes.update({c["id"]: c for c in front["causes"]})
    assert causes[ids["NEW-CAUSE-1"]]["flow_step"] == "data/data-setup/response"
    assert causes[ids["NEW-CAUSE-2"]]["flow_step"] == "data/data-setup/connected"
    assert "flow_step" not in causes["DATA-001-01"], "선택 칸: 없는 원인에는 쓰지 않는다"
    assert "flow-step" not in _lint(db)


# -- 초안 검증 지문·drift -------------------------------------------------------------------------------


def test_draft_fingerprint_sees_flow_content():
    plan = _plan(_put())
    before = draftcheck.fingerprint(plan)
    assert before is not None, "put-flow는 작성 op — 초안 검증 대상"
    plan["operations"][0]["flow"]["steps"][0]["patterns"].append("onSetupResponse2:")
    assert draftcheck.fingerprint(plan) != before


def _drift(repo: Path, op: dict, base: str) -> list[dict]:
    job = tmp("tt-flowdrift-")
    plan = _plan(op)
    plan["base_sha"] = base
    (job / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return run_json("db_add.py", ["drift", job / "plan.json", "--onto", "main", "--db", repo], expect=(0, 1))["drift"]


def test_drift_add_when_flow_appeared_and_replace_when_flow_changed():
    repo = git_db()
    base = git(repo, "rev-parse", "HEAD").strip()
    assert _drift(repo, _put(), base) == []
    _with_flow(repo)                                   # 그사이 main에 같은 흐름이 들어옴
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "flow")
    [item] = _drift(repo, _put(), base)
    assert (item["op"], item["target"], item["field"], item["plan_base_value"]) == ("put-flow", "data/data-setup", "flow", None)
    assert item["current_value"].startswith("id: data-setup") and item["plan_value"] == FLOW
    base = git(repo, "rev-parse", "HEAD").strip()     # 교체 계획: 그 뒤 main의 흐름 파일이 바뀌면 drift
    assert _drift(repo, _put(), base) == []
    edit(repo / FLOW_DIR / "data-setup.yaml", "title: 데이터 연결", "title: 데이터 연결(main)")
    git(repo, "commit", "-qam", "flow title")
    [item] = _drift(repo, _put(), base)
    assert "데이터 연결(main)" in item["current_value"] and "데이터 연결(main)" not in item["plan_base_value"]


# -- db_lint -----------------------------------------------------------------------------------------


def _flow_db() -> Path:
    return _with_flow(copy_db())


def _write_flow(db: Path, name: str, data: dict, cat: str = "data") -> None:
    (db / cat / "flows").mkdir(parents=True, exist_ok=True)
    (db / cat / "flows" / f"{name}.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_lint_flow_file_checks():
    db = _flow_db()
    assert not {k for k in _lint(db) if k.startswith("flow")}
    steps = copy.deepcopy(FLOW["steps"])
    steps[1]["id"] = steps[0]["id"]
    steps[0]["patterns"] = ["(a+)+x", "ConnectingState: onSetupResponse: imsi=450081234567890"]
    steps[2]["patterns"] = ["network connected(", "<IP#1> up"]
    _write_flow(db, "data-setup", {**FLOW, "steps": steps, "then": "missing-flow"})
    found = _lint(db)
    assert "단계 id가 겹칩니다" in found["flow-step-id"][0]
    assert "중첩 수량자" in " ".join(found["regex-unsafe"]) and "raw-identifier" in found
    assert "정규식 오류" in found["flow-regex"][0] and "fixed-token" in found
    assert "<IP#1> up" in found["flow-token"][0]      # 흐름은 가리지 않은 글에서 찾는다 — 마스킹 토큰 금지
    assert found["flow-then"][0].startswith("warning:") and "data/missing-flow" in found["flow-then"][0]
    # 파일 이름 ≠ id, 스키마 오류, start가 같은 흐름 둘
    db = _flow_db()
    _write_flow(db, "renamed", FLOW)
    _write_flow(db, "no-steps", {k: v for k, v in {**FLOW, "id": "no-steps"}.items() if k != "steps"})
    _write_flow(db, "twin", {**FLOW, "id": "twin"})
    found = _lint(db)
    assert "renamed.yaml" in found["flow-id"][0] and any("steps" in m for m in found["schema"])
    assert "data/twin" in found["flow-start"][0]


def test_lint_name_templates_escaped_tokens_and_log_end_sec():
    """F-5: name_template도 정규식·안전성 검사(`{key}` → X), end·notes의 named는 name_template 필수. F-13: 이스케이프한 토큰.
    F-14: flows.log_end_sec가 양수 숫자가 아니면 오류."""
    db = _flow_db()
    flow = copy.deepcopy(FLOW)
    flow["steps"][3]["name_template"] = "DataNetwork: {key}(("
    flow["end"].append({"scope": "named", "name_template": "(a+)+{key}", "pattern": "x", "label": "y"})
    flow["notes"].append({"scope": "own", "pattern": r"addresses=\[\<IP\#1\>"})
    _write_flow(db, "data-setup", flow)
    config = db / "issue-db.config.yaml"
    config.write_text(config.read_text(encoding="utf-8") + "flows:\n  log_end_sec: 0\n", encoding="utf-8")
    found = _lint(db)
    assert "steps[3].name_template" in found["flow-regex"][0] and "정규식 오류" in found["flow-regex"][0]
    assert "end[1].name_template" in " ".join(found["regex-unsafe"])
    assert "notes[1]" in found["flow-token"][0]
    assert any("flows.log_end_sec" in m for m in found["schema"])
    flow = copy.deepcopy(FLOW)
    flow["notes"] = [{"scope": "named", "pattern": "x"}]        # named인데 name_template 없음 → 스키마 오류
    _write_flow(db, "data-setup", flow)
    assert any("name_template" in m for m in _lint(db)["schema"])


def test_lint_flow_fixtures_and_flow_step():
    db = _flow_db()
    fixtures = db / FLOW_DIR / "fixtures"
    (fixtures / "data-setup.normal.1.log").rename(fixtures / "data-setup.ok.log")
    (fixtures / "ghost.normal.1.log").write_text(NORMAL, encoding="utf-8")
    found = _lint(db)
    assert "data-setup.ok.log" in found["fixture-name"][0] and "data/ghost" in found["fixture-owner"][0]
    assert "data/data-setup" in found["flow-fixture-missing"][0]
    db = _flow_db()
    _set_flow_step(db, "data/data-setup/no-such-step")
    _set_flow_step(db, "network/radio-on/decide", "DATA-001-02")      # 다른 카테고리 흐름은 걸지 않는다(V-8)
    _set_flow_step(db, "data/other-flow/response", "DATA-002-01")
    msgs = " | ".join(_lint(db)["flow-step"])
    assert "단계 no-such-step" in msgs and "다른 카테고리" in msgs and "흐름 data/other-flow가 없습니다" in msgs


# -- db_regress·db_verify·pre-commit -------------------------------------------------------------------


def _break_fixture(db: Path) -> None:
    edit(db / FLOW_DIR / "fixtures" / "data-setup.normal.1.log", "validation status=VALID", "validation status=INVALID")


def test_regress_judges_flow_fixtures_separately():
    db = _flow_db()
    out = run_json("db_regress.py", ["--db", db, "--all"])
    assert out["flows"] == {"total": 1, "passed": 1, "failed": 0, "skipped": [],
                            "results": [{"fixture": f"{FLOW_DIR}/fixtures/data-setup.normal.1.log", "flow": "data/data-setup",
                                         "status": "pass", "reasons": []}]}
    assert all("flow" not in r for r in out["results"]), "유형 fixture 결과와 섞지 않는다"
    _break_fixture(db)
    proc = run("db_regress.py", ["--db", db, "--all"])
    assert proc.returncode == 1 and "data-setup.normal.1.log" in proc.stderr
    [row] = json.loads(proc.stdout)["flows"]["results"]
    assert row["status"] == "fail" and row["reasons"][0].endswith("validated 로그끝"), "끝 단계가 ok가 아니면 실패(판정 불가 포함)"
    # 시작 줄이 없으면(인스턴스 0) 통과가 아니다
    (db / FLOW_DIR / "fixtures" / "data-setup.normal.1.log").write_text("-- [합성]\n", encoding="utf-8")
    [row] = run_json("db_regress.py", ["--db", db, "--all"], expect=1)["flows"]["results"]
    assert "인스턴스가 없다" in row["reasons"][-1]


def test_regress_flow_scope_by_changed_paths():
    repo = git_db()
    _with_flow(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "flow")
    edit(repo / FLOW_DIR / "data-setup.yaml", "title: 데이터 연결", "title: 데이터 연결 2")
    git(repo, "commit", "-qam", "flow only")
    out = run_json("db_regress.py", ["--db", repo, "--changed", "HEAD~1"])
    assert out["summary"]["total"] == 0 and out["flows"]["total"] == 1
    edit(repo / D / "type.md", "Data disabled", "Data disabled.")
    git(repo, "commit", "-qam", "type only")
    out = run_json("db_regress.py", ["--db", repo, "--changed", "HEAD~1"])
    assert out["summary"]["total"] > 0 and out["flows"]["total"] == 0
    edit(repo / "issue-db.config.yaml", "\n", "\n# flows\n")
    git(repo, "commit", "-qam", "config")
    assert run_json("db_regress.py", ["--db", repo, "--changed", "HEAD~1"])["flows"]["total"] == 1


def test_verify_rules_r4_includes_flow_fixtures():
    repo = git_db()
    _with_flow(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "flow")
    rows = {r["id"]: r for r in run_json("db_verify.py", ["rules", "--changed", "HEAD~1", "--db", repo, "--verbose"],
                                         expect=(0, 3))["rules"]}
    assert rows["R4"]["status"] == "pass" and rows["R4"]["reason"].endswith("흐름 fixture 1개 끝까지 ok")
    _break_fixture(repo)
    git(repo, "commit", "-qam", "broken flow fixture")
    rows = {r["id"]: r for r in run_json("db_verify.py", ["rules", "--changed", "HEAD~1", "--db", repo, "--verbose"],
                                         expect=1)["rules"]}
    assert rows["R4"]["status"] == "fail" and rows["R4"]["targets"] == [f"{FLOW_DIR}/fixtures/data-setup.normal.1.log"]
    assert rows["R4"]["review_required"] is False
    # 정상 fixture가 없어 건너뛴 흐름: 통과로 세지 않는다(F-8) — R4 review_required, db_regress stderr 한 줄
    (repo / FLOW_DIR / "fixtures" / "data-setup.normal.1.log").unlink()
    git(repo, "commit", "-qam", "no flow fixture")
    rows = {r["id"]: r for r in run_json("db_verify.py", ["rules", "--changed", "HEAD~1", "--db", repo, "--verbose"],
                                         expect=(0, 3))["rules"]}
    assert rows["R4"]["status"] == "pass" and rows["R4"]["review_required"] is True
    assert "정상 fixture 없어 건너뜀: data/data-setup" in rows["R4"]["reason"]
    proc = run("db_regress.py", ["--db", repo, "--all"])
    assert proc.returncode == 0 and "건너뜀: 흐름 data/data-setup (정상 fixture 없음)" in proc.stderr


def test_precommit_flow_only_change_runs_flow_fixtures():
    repo = git_db()
    _with_flow(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "flow")
    edit(repo / FLOW_DIR / "data-setup.yaml", "title: 데이터 연결", "title: 데이터 연결 2")
    git(repo, "add", "-A")
    proc = run("db_precommit.py", ["--db", repo])
    regress = next(c for c in json.loads(proc.stdout)["checks"] if c["check"] == "regress")
    assert regress["code"] == 0 and regress["note"].endswith("흐름 fixture 1개 통과"), regress
    _break_fixture(repo)
    git(repo, "add", "-A")
    proc = run("db_precommit.py", ["--db", repo])
    regress = next(c for c in json.loads(proc.stdout)["checks"] if c["check"] == "regress")
    assert proc.returncode == 1 and regress["code"] == 1 and "data-setup.normal.1.log" in regress["reason"]
