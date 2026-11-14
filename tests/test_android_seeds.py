#!/usr/bin/env python3
"""Android 시작 유형 묶음(이슈 DB 시드) 시험 — `templates/issue-db-seeds/android/<카테고리>/plan.json`.

- `add-fixture`의 `expect.origin: synthetic`이 `.expect.yaml`에 남고, 다른 값은 거부된다.
- 계획 모양: `source: import`, Jira 기록 없음, 새 유형 10개 이하, fixture는 모두 계획 옆 `fixtures/`의 합성 표시 로그,
  카테고리마다 음성 fixture, 벤더 층 placeholder 이름 없음.
- 계획마다 새 뼈대(`make_db_skeleton.py`)에 적용해 초안 검증 R1~R5 통과(리뷰 필요한 건너뜀도 실패로 본다).
- 모든 계획을 한 뼈대에 차례로 병합해 가며 적용해도 통과(교차 카테고리 R2~R4).
- 다 넣은 DB에서 fixture마다 앞뒤 20분에 무관한 줄을 붙여도 맞는 원인이 같다(창보다 긴 로그에서 `must_not_match`가
  창을 옮겨 피해지거나, 긴 창이 무관한 줄로 막히는 시그니처를 잡는다 — 합성 fixture는 짧아서 R1~R4가 못 본다).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
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
VENDOR_TAG = re.compile(r"(?m)^\d\d-\d\d \S+\s+\d+\s+\d+ [VDIWEF] (?:RIL|RilRequest)\s*:")   # 벤더 RIL 데몬 줄
STAMP = re.compile(r"\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}")
HEAD = "-- [합성]"
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


def padded(text: str) -> str:
    """fixture 첫 줄 20분 앞과 끝 줄 20분 뒤에 어느 시그니처와도 무관한 줄을 하나씩 붙인다."""
    lines = text.splitlines()
    at = [i for i, line in enumerate(lines) if STAMP.match(line)]

    def pad(i: int, minutes: int) -> str:
        when = datetime.strptime("2026-" + STAMP.match(lines[i]).group(0), "%Y-%m-%d %H:%M:%S.%f") + timedelta(minutes=minutes)
        return f"{when.strftime('%m-%d %H:%M:%S.%f')[:-3]}  1000  1000 D RILJ    : seed padding line"
    return "\n".join([*lines[:at[0]], pad(at[0], -20), *lines[at[0]:], pad(at[-1], 20)]) + "\n"


def matched_causes(db_dir: Path, root: Path, logs: list[Path]) -> dict[str, set[str]]:
    """회귀 모드(파일 전체)로 로그마다 충족된 원인 ID."""
    import db_regress
    import match_signatures
    from common import issuedb, site_defaults
    defaults = site_defaults.load_or_exit(str(root))
    db = issuedb.load(db_dir)
    compiled = db_regress.prepare(db, defaults)
    out = {}
    for log in logs:
        events = db_regress.parse_logs([log], db_dir / "parser-rules", root, defaults)
        result = db_regress.match_errors(match_signatures.match(events, db, compiled, regress=True), events)
        assert not result["errors"], f"{log.name}: {result['errors'][:3]}"
        out[log.name] = {c["cause"] for c in result["causes"] if c["C"]}
    return out


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
    # 근거가 Android 17 소스·캡처뿐이다: 원인과 code_refs 항목에 버전을 적는다(빈 목록은 "전 버전"이라 쓰지 않는다)
    causes = [op["first_cause"]["cause"] for op in types] + [op["cause"] for op in ops if op["op"] == "new-cause"]
    versions = [c.get("platform_versions") for c in causes] + [r.get("platform_versions") for c in causes for r in c.get("code_refs", [])]
    assert all(v == ["17"] for v in versions), "원인·code_refs의 platform_versions는 [\"17\"]"
    fixtures = [op for op in ops if op["op"] == "add-fixture"]
    assert any(op["kind"] == "negative" for op in fixtures), "카테고리마다 음성 fixture"
    assert all(op.get("expect", {}).get("origin") == "synthetic" for op in fixtures), "fixture마다 expect.origin: synthetic"
    listed = {op["path"] for op in fixtures}
    on_disk = {f"fixtures/{p.name}" for p in (plan.parent / "fixtures").iterdir()}
    assert listed == on_disk, f"계획과 fixtures/ 차이: {sorted(listed ^ on_disk)}"
    for path in (plan, SEEDS / "README.md", *sorted((plan.parent / "fixtures").iterdir())):
        text = path.read_text(encoding="utf-8")
        hit = VENDOR.search(text) or VENDOR_TAG.search(text)
        assert not hit, f"{path.name}: 벤더 층 이름·벤더 RIL 데몬 줄 {hit.group(0)!r}"
        # 합성 머리줄: 사내 점검(site_checks s4.seed·s6.synthetic)이 origin 표시가 지워진 합성 로그를 이것으로 센다
        assert path.suffix != ".log" or text.startswith(HEAD), f"{path.name}: 1줄이 {HEAD!r}로 시작하지 않는다"


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
    db = ws.other_clone()
    logs = sorted(db.glob("*/*/fixtures/*.log"))
    long_dir = tmp("tt-seed-long-")
    for log in logs:
        (long_dir / log.name).write_text(padded(log.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    short, long = matched_causes(db, ws.root, logs), matched_causes(db, ws.root, sorted(long_dir.iterdir()))
    assert len(short) == len(long) == len(logs) > 0
    diff = {name: {"그대로": sorted(short[name]), "앞뒤 20분": sorted(long[name])} for name in short if short[name] != long[name]}
    assert not diff, f"로그가 길어지면 맞는 원인이 달라진다: {json.dumps(diff, ensure_ascii=False, indent=1)}"
