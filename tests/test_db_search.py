#!/usr/bin/env python3
"""Phase 11 완료 기준 확인: 병합(`move/...`) 절차와 `db_search.py`의 옛 ID → 새 ID 연결
(11-phases.md Phase 11, 06-collaboration.md §6.6, contracts.md §renumber 참조).

- 병합: 샘플에 중복 유형 DATA-002(원인 DATA-002-01, 양성 fixture, Jira MOCK-1201)를 둔 main에서
  `source: move` 계획(`new-cause` → `add-fixture`(옛 fixture를 이슈 DB 경로로) → `set-status merged-into` →
  `reclassify`(원인 미확정 Jira는 `<유형 ID>:unresolved`))을 `db_pr stage`로 PR까지 올리고 머지한다. 그 뒤 `db_search`가 옛 ID를 새 ID로 잇는다.
- 사후 재배치: main에 같은 원인 ID가 두 번 들어온 트리(`issue-db-dup-id`)에서 나중 쪽을 옮긴 커밋에
  `Renumbered:` 트레일러를 남기면 `db_search`가 옛 ID와 새 ID를 서로 잇는다.

`pytest tests/test_db_search.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, copy_db, edit, git, run, run_json, variant_db  # noqa: E402
from workspace import Workspace  # noqa: E402

DATA = "data/DATA-001-no-setup-data-call"
DATA2 = "data/DATA-002-sim-not-ready"
SIM_LOG = variant_db("issue-db-pending") / DATA / "fixtures/DATA-001-03.log"

DATA_002 = """---
id: DATA-002
category: data
secondary_categories: []
title: SIM 준비 전 데이터 평가 거부
summary: SIM이 준비되기 전에 데이터 평가가 거부된다 (DATA-001과 같은 현상, 병합 시험용)
status: active
symptom_signatures:
  - id: sim-not-ready-rejected
    must_event:
      - {event: data_evaluation_rejected, fields: {reasons: '.*SIM_NOT_READY.*'}}
    window_sec: 60
causes:
  - id: DATA-002-01
    status: active
    title: SIM 미준비
    description: SIM 로딩 전에 평가가 거부됨
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
tags: [data-evaluation]
---

## 증상

SIM 로딩 전 데이터 평가 거부.

## 증상 판별 방법

`DNC-<slot>` 평가가 `SIM_NOT_READY`로 거부된다.

## 원인별 상세

### DATA-002-01 SIM 미준비

- 병합 시험용.
"""

JIRA_1201 = """key: MOCK-1201
cause: DATA-002-01
date: 2026-09-26
occurred_on: 2026-09-26
model: MOCK-A56
sw: MOCKA56_U1_20260920
android_version: "16"
carrier: MockTel KR
analyzed_by: mock-user1
note: 부팅 직후 데이터 안 됨
"""


def _source_db() -> Path:
    """샘플 + 중복 유형 DATA-002 (운영 이슈 DB처럼 lint·회귀를 통과하는 트리)."""
    db = copy_db(SAMPLE, "src")
    (db / DATA2 / "jira").mkdir(parents=True)
    (db / DATA2 / "fixtures").mkdir()
    (db / DATA2 / "type.md").write_text(DATA_002, encoding="utf-8", newline="\n")
    (db / DATA2 / "jira/MOCK-1201.yaml").write_text(JIRA_1201, encoding="utf-8", newline="\n")
    unresolved = JIRA_1201.replace("MOCK-1201", "MOCK-1202").replace("cause: DATA-002-01", "cause: unresolved")
    (db / DATA2 / "jira/MOCK-1202.yaml").write_text(unresolved, encoding="utf-8", newline="\n")
    shutil.copyfile(SIM_LOG, db / DATA2 / "fixtures/DATA-002-01.log")
    return db


def _cause(type_md: str, cause_id: str) -> dict:
    front = yaml.safe_load(type_md.split("---\n", 2)[1])
    return next(c for c in front["causes"] if c["id"] == cause_id)


def _move_plan(old_cause: dict) -> dict:
    body = {k: old_cause[k] for k in ("title", "description", "signatures", "recovery_signatures",
                                      "scenario_signatures", "resolution", "resolution_type", "android_versions",
                                      "code_refs")}
    return {
        "source": "move", "schema_version": 1, "started_at": "2026-10-20T10:00+09:00",
        "base_sha": None, "jira": None,
        "operations": [
            {"op": "new-cause", "temp_id": "NEW-CAUSE-1", "type": "DATA-001", "cause": body,
             "body": "- DATA-002-01에서 옮겨 옴 (병합)."},
            {"op": "add-fixture", "for": "NEW-CAUSE-1", "kind": "positive",
             "path": f"{DATA2}/fixtures/DATA-002-01.log"},
            {"op": "set-status", "id": "DATA-002-01", "status": "merged-into:NEW-CAUSE-1"},
            {"op": "set-status", "id": "DATA-002", "status": "merged-into:DATA-001"},
            {"op": "reclassify", "jira": "MOCK-1201", "from": "DATA-002-01", "to": "NEW-CAUSE-1"},
            # 원인 미확정 Jira도 흡수하는 유형으로 옮긴다
            {"op": "reclassify", "jira": "MOCK-1202", "from": "unresolved", "to": "DATA-001:unresolved"},
        ],
        "feedback": None,
        "commit_message": "[DATA-002] move DATA-002 into DATA-001 (NEW-CAUSE-1)",
        "pr": {"number": None, "branch": "move/DATA-002-to-DATA-001", "head_sha": None},
        "included_pending": [],
    }


def test_move_merges_type_and_search_follows_old_ids():
    ws = Workspace(src=_source_db())
    old = _cause((ws.clone / DATA2 / "type.md").read_text(encoding="utf-8"), "DATA-002-01")
    job, branch = "move-DATA-002-to-DATA-001", "move/DATA-002-to-DATA-001"
    ws.plan(job, _move_plan(old))
    out = ws.ship(job, branch)
    stage = out["stage"]
    assert stage["apply"]["ids"] == [{"temp_id": "NEW-CAUSE-1", "id": "DATA-001-03"}]
    assert [f["name"] for f in stage["apply"]["fixtures"]] == ["DATA-001-03.log"]
    # stage의 검사(lint, 회귀, R1~R6)가 모두 통과해야 PR까지 간다
    assert out["publish"]["pr"]["number"]

    new_md = ws.remote_file(branch, f"{DATA}/type.md")
    moved = _cause(new_md, "DATA-001-03")
    assert moved["signatures"] == old["signatures"] and moved["status"] == "active"
    old_md = ws.remote_file(branch, f"{DATA2}/type.md")
    assert "status: merged-into:DATA-001\n" in old_md
    assert _cause(old_md, "DATA-002-01")["status"] == "merged-into:DATA-001-03"
    # 삭제하지 않는다: 옛 fixture와 유형 파일은 남고, Jira는 새 유형 디렉토리로 옮겨진다
    files = ws.remote_files(branch)
    assert f"{DATA2}/fixtures/DATA-002-01.log" in files and f"{DATA}/fixtures/DATA-001-03.log" in files
    assert f"{DATA2}/jira/MOCK-1201.yaml" not in files
    jira = yaml.safe_load(ws.remote_file(branch, f"{DATA}/jira/MOCK-1201.yaml"))
    assert jira["cause"] == "DATA-001-03" and "reclassified from DATA-002-01" in jira["note"]
    assert f"{DATA2}/jira/MOCK-1202.yaml" not in files
    unresolved = yaml.safe_load(ws.remote_file(branch, f"{DATA}/jira/MOCK-1202.yaml"))
    assert unresolved["cause"] == "unresolved" and "reclassified from DATA-002:unresolved" in unresolved["note"]
    data_section = ws.remote_file(branch, "README.md").split("## Data", 1)[1].split("## Call", 1)[0]
    assert "MOCK-1202" in data_section
    assert "DATA-002" in ws.remote_file(branch, "README.md").split("## 보관", 1)[1]

    ws.merge(branch)
    git(ws.clone, "pull", "-q", "--ff-only")
    found = run_json("db_search.py", ["--db", ws.clone, "DATA-002-01"])
    assert found["kind"] == "cause-id"
    assert [r["id"] for r in found["results"]] == ["DATA-002-01", "DATA-001-03"]
    assert found["results"][0]["current"] == "DATA-001-03" and found["results"][0]["status"] == \
        "merged-into:DATA-001-03"
    assert {"from": "DATA-002-01", "to": "DATA-001-03", "via": "merged-into"} in found["links"]
    new = found["results"][1]
    assert new["merged_from"] == ["DATA-002-01"] and new["jira"] == ["MOCK-1201"]
    # 유형 ID로 찾아도 병합 대상 유형으로 이어진다
    by_type = run_json("db_search.py", ["--db", ws.clone, "DATA-002"])
    assert by_type["results"][0]["current"] == "DATA-001"
    assert {"from": "DATA-002", "to": "DATA-001", "via": "merged-into"} in by_type["links"]
    # Jira 키로 찾으면 옮겨진 기록과 새 원인
    by_jira = run_json("db_search.py", ["--db", ws.clone, "MOCK-1201"])
    assert by_jira["kind"] == "jira"
    assert [(r["kind"], r.get("id") or r.get("key")) for r in by_jira["results"]] == [
        ("jira", "MOCK-1201"), ("cause", "DATA-001-03")]


def test_renumbered_trailer_links_old_and_new_id():
    db = copy_db(variant_db("issue-db-dup-id"))
    git(db, "init", "-q", "-b", "main")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "merge two PRs")
    # 메인테이너 사후 정리: 나중에 머지된 DATA-001-03(무선 꺼짐)을 DATA-001-04로 옮긴다 (06-collaboration.md §6.3)
    type_md = db / DATA / "type.md"
    edit(type_md, "  - id: DATA-001-03\n    status: active\n    title: 무선 꺼짐",
         "  - id: DATA-001-04\n    status: active\n    title: 무선 꺼짐")
    git(db, "add", "-A")
    git(db, "commit", "-qm", "chore: fix duplicated DATA-001-03\n\nRenumbered: DATA-001-03 -> DATA-001-04")

    found = run_json("db_search.py", ["--db", db, "DATA-001-03"])
    ids = [r["id"] for r in found["results"]]
    # 옛 ID는 원래 주인(SIM 미준비)이 계속 쓰고, 옮겨간 엔티티도 함께 보인다
    assert ids == ["DATA-001-03", "DATA-001-04"]
    assert found["results"][0]["title"] == "SIM 미준비" and found["results"][1]["title"] == "무선 꺼짐"
    link = next(l for l in found["links"] if l["via"] == "renumbered")
    assert (link["from"], link["to"]) == ("DATA-001-03", "DATA-001-04") and link["commit"]
    back = run_json("db_search.py", ["--db", db, "DATA-001-04"])
    assert [r["id"] for r in back["results"]] == ["DATA-001-04", "DATA-001-03"]
    assert any(l["via"] == "renumbered" for l in back["links"])
    # 유형 ID로 찾으면 소속 원인의 재배치도 보인다
    by_type = run_json("db_search.py", ["--db", db, "DATA-001"])
    assert any(l["via"] == "renumbered" for l in by_type["links"])


def test_keyword_and_jira_search_on_sample():
    found = run_json("db_search.py", ["--db", SAMPLE, "로밍"])
    assert found["kind"] == "keyword"
    first = found["results"][0]
    assert (first["kind"], first["id"]) == ("cause", "DATA-001-02")
    assert first["resolution"] == "데이터 로밍 설정을 켠다" and first["fix"]["status"] == "not-a-bug"
    assert first["jira"] == ["MOCK-1103"] and found["git_history"] is False
    assert any(r["kind"] == "jira" and r["key"] == "MOCK-1103" for r in found["results"])
    limited = run_json("db_search.py", ["--db", SAMPLE, "않음", "--limit", "2"])
    assert len(limited["results"]) == 2
    jira = run_json("db_search.py", ["--db", SAMPLE, "MOCK-1104"])
    assert [(r["kind"], r.get("id") or r.get("key")) for r in jira["results"]] == [
        ("jira", "MOCK-1104"), ("type", "DATA-001")]
    call = run_json("db_search.py", ["--db", SAMPLE, "CALL-001-01"])
    assert call["results"][0]["related"] == ["IMS-001-01"]
    assert call["results"][0]["secondary_categories"] == ["ims"]
    none = run_json("db_search.py", ["--db", SAMPLE, "NOPE-009-01"])
    assert none["results"] == [] and none["links"] == []
    assert run("db_search.py", ["--db", SAMPLE, "x", "--limit", "0"]).returncode == 2


def test_failed_step_is_searchable_and_shown_only_when_present():
    from runner import copy_db
    db = copy_db()
    edit(db / "data/DATA-001-no-setup-data-call/jira/MOCK-1101.yaml", "note: 모바일", "failed_step: 3 | Enable data\nnote: 모바일")
    found = run_json("db_search.py", ["--db", db, "enable data"])
    jira = [r for r in found["results"] if r["kind"] == "jira"]
    assert [r["key"] for r in jira] == ["MOCK-1101"] and jira[0]["failed_step"] == "3 | Enable data"
    other = run_json("db_search.py", ["--db", db, "MOCK-1102"])
    assert "failed_step" not in other["results"][0]
    assert found["results"][0].get("failed_step") in (None, "3 | Enable data")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
