#!/usr/bin/env python3
"""Android 시작 유형 묶음(이슈 DB 시드) 시험 — `templates/issue-db-seeds/android/<카테고리>/plan.json`.

- `add-fixture`의 `expect.origin: synthetic`이 `.expect.yaml`에 남고, 다른 값은 거부된다.
- 계획 모양: `source: import`, Jira 기록 없음, 새 유형 10개 이하, fixture는 모두 계획 옆 `fixtures/`의 합성 표시 로그,
  카테고리마다 음성 fixture, 벤더 층 placeholder 이름 없음.
- 계획마다 새 뼈대(`make_db_skeleton.py`)에 적용해 초안 검증 R1~R5 통과(리뷰 필요한 건너뜀도 실패로 본다).
- 모든 계획을 한 뼈대에 차례로 병합해 가며 적용해도 통과(교차 카테고리 R2~R4).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import tmp  # noqa: E402
from workspace import Workspace  # noqa: E402

SEEDS = REPO / "templates" / "issue-db-seeds" / "android"
PLANS = sorted(SEEDS.glob("*/plan.json"))
VENDOR = re.compile(r"VIPC_|VRIL|IpcCtx_|vrild|Example[A-Z]\w")
SYNTHETIC = {"origin": "synthetic"}


def skeleton() -> Path:
    out = tmp("tt-seed-") / "db"
    subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out)], check=True,
                   capture_output=True)
    return out


def load(plan: Path) -> dict:
    return json.loads(plan.read_text(encoding="utf-8"))


def verify(ws: Workspace, job: str, plan: Path) -> None:
    """계획을 작업 디렉토리에 놓고 초안 검증. R1~R4는 pass, R5는 pass 또는 해당 없음이어야 한다."""
    shutil.copytree(plan.parent / "fixtures", ws.job_dir(job) / "fixtures")
    path = ws.plan(job, load(plan))
    ws.acquire(job)
    proc = ws.run("db_verify.py", ["rules", "--plan", path, "--draft", ws.job_dir(job) / "draft", "--db", ws.clone])
    assert proc.returncode == 0, f"{plan.parent.name}: 종료 코드 {proc.returncode}\n{proc.stdout[-6000:]}\n{proc.stderr[-2000:]}"
    rows = {r["id"]: r for r in json.loads(proc.stdout)["rules"]}
    # R5는 파서 규칙을 안 바꾸면 "해당 없음"으로 건너뛴다. R6(추가 표본)은 시드에 없다
    allowed = {rid: ("pass", "skipped") if rid == "R5" else ("pass",) for rid in ("R1", "R2", "R3", "R4", "R5")}
    bad = {rid: (rows[rid]["status"], rows[rid].get("reason")) for rid, ok in allowed.items()
           if rows[rid]["review_required"] or rows[rid]["status"] not in ok}
    assert not bad, f"{plan.parent.name}: {bad}\n{proc.stdout[-6000:]}"


def new_type_plan(origin: str) -> dict:
    cause = {"title": "원인", "description": "설명", "resolution": "해결", "resolution_type": "user-setting",
             "signatures": [{"id": "c", "must_match": ["seed origin probe .*why=x"], "window_sec": 60}],
             "fix": {"status": "not-a-bug", "ref": None, "fixed_in": []}}
    return {"source": "import", "schema_version": 1, "started_at": "2026-11-14T22:00+09:00", "base_sha": "0" * 40,
            "issue": None, "feedback": None, "included_pending": [],
            "commit_message": "[NEW-TYPE-1] import data-1: 시험", "pr": {"number": None, "branch": "import/data-1", "head_sha": None},
            "operations": [
                {"op": "new-type", "temp_id": "NEW-TYPE-1", "category": "data", "dir_slug": "seed-origin-probe",
                 "type": {"title": "시험 연결이 끊김", "summary": "시험", "tags": [],
                          "symptom_signatures": [{"id": "s", "must_match": ["seed origin probe"], "window_sec": 60}]},
                 "first_cause": {"temp_id": "NEW-CAUSE-1", "cause": cause, "body": "- **확인 방법**: 시험\n"},
                 "body": "## 증상\n\n시험.\n"},
                {"op": "add-fixture", "for": "NEW-CAUSE-1", "kind": "positive", "path": "fixtures/pos.log",
                 "expect": {"origin": origin}},
                {"op": "add-fixture", "for": "NEW-TYPE-1", "kind": "negative", "path": "fixtures/neg.log",
                 "expect": {"origin": origin}}]}


def test_add_fixture_keeps_synthetic_origin_and_rejects_other_values():
    ws = Workspace(src=skeleton())
    line = "11-14 22:00:0{n}.000  1000  1234  1234 D DNC-0   : {msg}\n"
    for job, origin in (("seed-ok", "synthetic"), ("seed-bad", "real")):
        ws.put(job, "fixtures/pos.log", line.format(n=1, msg="seed origin probe why=x"))
        ws.put(job, "fixtures/neg.log", line.format(n=2, msg="nothing here"))
        ws.plan(job, new_type_plan(origin))
        ws.acquire(job)
        if origin != "synthetic":
            proc = ws.run("db_pr.py", ["stage", ws.job_dir(job) / "plan.json", "--wt", ws.wt(job), "--branch", "import/data-2"])
            assert proc.returncode != 0 and "expect.origin" in proc.stdout + proc.stderr
            continue
        ws.stage(job, "import/data-1")
        marks = sorted(ws.wt(job).glob("data/*/fixtures/*.expect.yaml"))
        assert len(marks) == 2 and all(yaml.safe_load(p.read_text(encoding="utf-8")) == SYNTHETIC for p in marks), marks
        ws.db_pr("discard", ws.wt(job))


def test_seed_plans_exist():
    """시드가 통째로 빠지면 아래 계획별 시험이 조용히 0건이 된다."""
    assert PLANS, f"{SEEDS}에 <카테고리>/plan.json이 없다"


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.parent.name)
def test_seed_plan_shape(plan):
    data, cat = load(plan), plan.parent.name
    ops = data["operations"]
    assert data["source"] == "import" and data["issue"] is None
    assert not [op["op"] for op in ops if op["op"] in ("append", "unresolved", "reclassify")], "Jira 기록은 넣지 않는다"
    types = [op for op in ops if op["op"] == "new-type"]
    assert 0 < len(types) <= 10 and {op["category"] for op in types} == {cat}
    fixtures = [op for op in ops if op["op"] == "add-fixture"]
    assert any(op["kind"] == "negative" for op in fixtures), "카테고리마다 음성 fixture"
    assert all(op.get("expect", {}).get("origin") == "synthetic" for op in fixtures), "fixture마다 expect.origin: synthetic"
    listed = {op["path"] for op in fixtures}
    on_disk = {f"fixtures/{p.name}" for p in (plan.parent / "fixtures").iterdir()}
    assert listed == on_disk, f"계획과 fixtures/ 차이: {sorted(listed ^ on_disk)}"
    for path in (plan, *sorted((plan.parent / "fixtures").iterdir())):
        hit = VENDOR.search(path.read_text(encoding="utf-8"))
        assert not hit, f"{path.name}: 벤더 층 placeholder 이름 {hit.group(0)!r}"


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.parent.name)
def test_seed_plan_passes_draft_verification_on_fresh_skeleton(plan):
    verify(Workspace(src=skeleton()), f"seed-{plan.parent.name}", plan)


def test_all_seed_plans_apply_in_sequence_on_one_skeleton():
    """앞 카테고리가 main에 들어간 뒤 다음 카테고리를 검증한다 — 다른 카테고리 fixture에서 걸리는 시그니처를 잡는다."""
    ws = Workspace(src=skeleton())
    for plan in PLANS:
        cat = plan.parent.name
        job, branch = f"seed-{cat}", f"import/{cat}-1"
        verify(ws, job, plan)
        ws.ship(job, branch)
        ws.merge(branch)
