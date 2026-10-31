#!/usr/bin/env python3
"""Jira 기록 `sw` 선택화 (item 17, 03-issue-db.md §5.4 (2)·§5.9, 06-collaboration.md §6.4 호환 변경).

- Jira에 빌드 정보가 없으면 계획 `issue`에 `sw`를 두지 않고, 적용·stage 검사(lint)를 지나 기록에 `sw` 키가 없다.
- 필수 여부는 대상 이슈 DB `schema/issue.schema.json` `required`가 정한다: 옛 운영 DB 스키마(sw 필수)면 `issue-fields`로
  거부하고 메인테이너 PR이 필요하다고 알린다.
- STATS SW 분포에서 `sw` 없는 기록은 "(없음)"으로 센다.

`pytest tests/test_record_optional_sw.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import copy_db, run_json, tmp  # noqa: E402
from workspace import PLANS, Workspace  # noqa: E402

DATA_DIR = "data/DATA-001-no-setup-data-call"


def _plan_without_sw() -> dict:
    plan = json.loads((PLANS / "p7-analyze-append.plan.json").read_text(encoding="utf-8"))
    del plan["issue"]["sw"]
    return plan


def _require_sw(root: Path) -> None:
    path = root / "schema" / "issue.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["required"].insert(4, "sw")
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_record_without_sw_reaches_pr():
    ws = Workspace()
    ws.plan("MOCK-7001", _plan_without_sw())
    ws.ship("MOCK-7001", "issue/MOCK-7001")      # stage 검사(lint 포함)를 지나 PR까지
    record = yaml.safe_load(ws.remote_file("issue/MOCK-7001", f"{DATA_DIR}/issues/MOCK-7001.yaml"))
    assert "sw" not in record and record["model"] == "MOCK-A56" and record["platform_version"] == "16"
    assert list(record)[:5] == ["key", "cause", "date", "occurred_on", "model"]


def test_old_db_schema_still_requires_sw():
    ws = Workspace()
    ws.push_main(_require_sw, "옛 운영 DB 스키마(sw 필수)")
    ws.plan("MOCK-7001", _plan_without_sw())
    ws.acquire("MOCK-7001")
    out = ws.stage("MOCK-7001", "issue/MOCK-7001", expect=1)
    rejected = out["apply"]["rejected"][0]
    assert rejected["code"] == "issue-fields", rejected
    assert "sw" in rejected["message"] and "schema/issue.schema.json" in rejected["message"]
    assert "메인테이너 PR" in rejected["message"]
    ws.db_pr("discard", ws.wt("MOCK-7001"))


def test_stats_count_missing_sw_as_none():
    db = copy_db()
    jira_dir = db / "network/NETWORK-001-no-service/issues"
    (jira_dir / "MOCK-3199.yaml").write_text(
        "key: MOCK-3199\ncause: NETWORK-001-01\ndate: 2026-09-27\n"
        "model: MOCK-A56\nplatform_version: \"16\"\nanalyzed_by: mock-user1\n", encoding="utf-8")
    out = tmp("tt-preview-")
    run_json("db_build.py", ["--db", db, "--preview", out])
    sw = (out / "STATS.md").read_text(encoding="utf-8").split("### SW", 1)[1].split("\n### ", 1)[0]
    assert "| (없음) | 1 |" in sw


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
