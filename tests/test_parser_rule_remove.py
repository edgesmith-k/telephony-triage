#!/usr/bin/env python3
"""op `remove-parser-rule` (사내 보고 import-20261018 9번 — placeholder 규칙을 계획으로 지울 수 없었다).

- `ListSection.remove`: 지운 항목만 빠지고 다음 묶음 머리 주석(`# --- sms ---`)·나머지 바이트는 그대로
- `db_add apply`: 섹션 자동 판별, `rule-missing`·`rule-last` 거부, 추가 뒤 삭제는 원래 바이트, 형식 오류(reason 없음)
- drift: 지우려던 항목을 main이 바꾸거나 이미 지웠으면 drift(계획 값 null)
- 초안 검증 지문(작성 op)에 들어가고, 이벤트를 내던 extractor를 지우면 R5 needs-approval
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, copy_db, git_db, plugin_root, run, run_json  # noqa: E402

sys.path.insert(0, str(plugin_root() / "scripts"))

from common import draftcheck, yamldoc, yamlio  # noqa: E402
from dbadd import drift  # noqa: E402

RULES = SAMPLE / "parser-rules"


def _plan(ops: list[dict]) -> dict:
    return {"source": "review", "schema_version": 1, "started_at": "2026-10-28T10:00+09:00", "base_sha": "0" * 40,
            "issue": None, "operations": ops, "feedback": None, "commit_message": "[DATA-001] review: 규칙 정리",
            "pr": {"number": None, "branch": "review/x", "head_sha": None}, "included_pending": []}


def _apply(db: Path, ops: list[dict], expect=0) -> dict:
    path = db.parent / "job" / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plan(ops), ensure_ascii=False), encoding="utf-8")
    return run_json("db_add.py", ["apply", path, "--db", db, "--user", "mock-user1"], expect=expect)


def _rm(file: str, key: str, **extra) -> dict:
    return {"op": "remove-parser-rule", "file": file, "key": key, "reason": "placeholder — 실제 로그에 없음", **extra}


def _without(text: str, *needles: str) -> str:
    """원래 텍스트에서 `needles`가 든 줄만 뺀 것."""
    return "".join(line for line in text.splitlines(keepends=True) if not any(n in line for n in needles))


def _remove(text: str, section: str, key_field: str, key: str) -> str:
    data = yamlio.loads(text)[section]
    lines = text.splitlines(keepends=True)
    n = next(k for k, r in enumerate(data) if r.get(key_field) == key)
    return "".join(yamldoc.replace_block(lines, section, yamldoc.ListSection(lines, section, data).remove(n)))


# -- yamldoc -----------------------------------------------------------------------------------------------


def test_remove_keeps_next_group_header_and_other_bytes():
    tags = (RULES / "tags.yaml").read_text(encoding="utf-8")
    # 묶음의 마지막 항목(sim의 SMSVC): 뒤에 있던 `# --- sms ---` 머리 주석이 남는다
    out = _remove(tags, "tags", "tag_regex", "^(SMSVC|SubscriptionManagerService)$")
    assert out == _without(tags, "SMSVC") and "  # --- sms --- TODO(SITE:S9)\n" in out
    # 파일 마지막 항목·섹션 첫 항목
    assert _remove(tags, "tags", "tag", "InboundSmsHandler") == _without(tags, "InboundSmsHandler")
    assert _remove(tags, "tags", "tag_regex", r"^DNC-\d+$") == _without(tags, "'^DNC-")
    # 묶음의 유일한 항목: 앞뒤 머리 주석은 둘 다 남고 빈 줄은 하나씩
    out = _remove(tags, "tags", "tag_regex", "^(SST|ServiceStateTracker)(-\\d+)?$")
    assert out == _without(tags, "ServiceStateTracker") and "\n\n\n" not in out


def test_remove_block_item_with_blank_gaps_and_ril_section():
    ex = (RULES / "extractors.yaml").read_text(encoding="utf-8")
    out = _remove(ex, "extractors", "id", "data-evaluation-allowed")
    assert "data-evaluation-allowed" not in out and "\n\n\n" not in out
    assert yamlio.loads(out)["extractors"] == [e for e in yamlio.loads(ex)["extractors"]
                                               if e["id"] != "data-evaluation-allowed"]
    assert out.count("\n") == ex.count("\n") - 10                       # 항목 9줄 + 구분 빈 줄 1
    ril = (RULES / "ril.yaml").read_text(encoding="utf-8")
    assert _remove(ril, "unsolicited", "name", "UNSOL_SIM_STATUS_CHANGED") == _without(ril, "UNSOL_SIM_STATUS_CHANGED")
    assert _remove(ril, "requests", "name", "GET_SIM_STATUS") == _without(ril, "GET_SIM_STATUS")


# -- db_add apply ------------------------------------------------------------------------------------------


def test_apply_remove_detects_section_and_rejects_missing_or_last():
    db = copy_db()
    ril = (db / "parser-rules/ril.yaml").read_text(encoding="utf-8")
    _apply(db, [_rm("ril.yaml", "UNSOL_SIM_STATUS_CHANGED"), _rm("tags.yaml", "InboundSmsHandler")])
    assert (db / "parser-rules/ril.yaml").read_text(encoding="utf-8") == _without(ril, "UNSOL_SIM_STATUS_CHANGED")
    assert "InboundSmsHandler" not in (db / "parser-rules/tags.yaml").read_text(encoding="utf-8")

    db = copy_db()
    rej = _apply(db, [_rm("ril.yaml", "NO_SUCH")], expect=1)["rejected"][0]
    assert rej["code"] == "rule-missing" and "NO_SUCH" in rej["message"], rej
    assert _apply(db, [_rm("ril.yaml", "DIAL", section="unsolicited")], expect=1)["rejected"][0]["code"] == "rule-missing"
    names = [r["name"] for r in yamlio.loads(ril)["requests"]]
    rej = _apply(db, [_rm("ril.yaml", n) for n in names], expect=1)["rejected"][0]
    assert rej["code"] == "rule-last" and rej["op_index"] == len(names) - 1, rej


def test_apply_add_then_remove_restores_bytes_and_reason_required():
    db = copy_db()
    before = {f: (db / "parser-rules" / f).read_bytes() for f in ("tags.yaml", "extractors.yaml")}
    tag = {"tag": "MockTag", "category": "sms", "added_for": "SMS-001", "added_on": "2026-10-28", "reason": "시험"}
    ext = {"id": "mock-extractor", "added_for": "SMS-001", "added_on": "2026-10-28", "reason": "시험",
           "tag": "MockTag", "patterns": ["mock (?P<x>\\d+)"], "event": "mock_event", "fields": ["x"]}
    _apply(db, [{"op": "add-parser-rule", "file": "tags.yaml", "rule": tag},
                {"op": "add-parser-rule", "file": "extractors.yaml", "rule": ext},
                _rm("extractors.yaml", "mock-extractor"), _rm("tags.yaml", "MockTag")])
    assert {f: (db / "parser-rules" / f).read_bytes() for f in before} == before
    op = _rm("tags.yaml", "InboundSmsHandler")
    del op["reason"]
    error = _apply(db, [op], expect=2)["error"]
    assert "op=remove-parser-rule)" in error and "빠진 필드 [reason]" in error, error


# -- drift·초안 검증·R5 -------------------------------------------------------------------------------------


def _edited(tmp_path: Path, name: str, change) -> drift.Snapshot:
    root = tmp_path / name
    shutil.copytree(SAMPLE, root)
    change(root / "parser-rules")
    return drift.Snapshot(root)


def test_drift_when_main_changed_or_removed_target(tmp_path):
    base = drift.Snapshot(SAMPLE)
    plan = _plan([_rm("ril.yaml", "UNSOL_SIM_STATUS_CHANGED")])
    hist = _edited(tmp_path, "hist", lambda d: (d / "ril.yaml").write_text(
        (d / "ril.yaml").read_text(encoding="utf-8").replace("added_for: SIM-001, added_on: 2026-09-28, reason: 초기}",
                                                             "added_for: SIM-001, added_on: 2026-10-01, reason: 보강}"),
        encoding="utf-8"))
    assert drift.drift_items(plan, base, hist) == []                    # 이력 필드만 바뀜
    gone = _edited(tmp_path, "gone", lambda d: (d / "ril.yaml").write_text(
        _without((d / "ril.yaml").read_text(encoding="utf-8"), "UNSOL_SIM_STATUS_CHANGED"), encoding="utf-8"))
    items = drift.drift_items(plan, base, gone)
    assert [(d["op"], d["target"], d["field"], d["plan_value"], d["current_value"]) for d in items] == [
        ("remove-parser-rule", "ril.yaml:UNSOL_SIM_STATUS_CHANGED", "unsolicited", None, None)]
    changed = _edited(tmp_path, "changed", lambda d: (d / "ril.yaml").write_text(
        (d / "ril.yaml").read_text(encoding="utf-8").replace("{name: UNSOL_SIM_STATUS_CHANGED,          category: sim",
                                                             "{name: UNSOL_SIM_STATUS_CHANGED, category: data"),
        encoding="utf-8"))
    assert drift.drift_items(plan, base, changed)[0]["current_value"]["category"] == "data"


def test_remove_is_authoring_op_and_r5_needs_approval():
    assert draftcheck.fingerprint(_plan([_rm("tags.yaml", "InboundSmsHandler")])) is not None
    db = git_db()
    _apply(db, [_rm("extractors.yaml", "data-evaluation-allowed")])     # 시그니처가 안 쓰지만 fixture에 이벤트가 있다
    proc = run("db_verify.py", ["rules", "--changed", "HEAD", "--db", db])
    rows = {r["id"]: r for r in json.loads(proc.stdout)["rules"]}
    assert proc.returncode == 3 and rows["R5"]["status"] == "needs-approval", proc.stdout[-2000:]


def test_contracts_draft_gate_lists_every_authoring_op():
    """contracts.md `db_pr stage` 초안 검증 게이트의 작성 op 목록(`작성 op(` ~ 닫는 `)`, `add-fixture` 빼고)이
    `draftcheck.AUTHORING_OPS`와 같다(remove-parser-rule 포함)."""
    text = (REPO / "docs/design/contracts.md").read_text(encoding="utf-8")
    gate = text.split("**초안 검증 게이트**: 작성 op(", 1)[1].split(")", 1)[0]
    assert set(re.findall(r"`([^`]+)`", gate)) - {"add-fixture"} == set(draftcheck.AUTHORING_OPS), gate
