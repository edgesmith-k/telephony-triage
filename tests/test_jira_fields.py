#!/usr/bin/env python3
"""Phase 13 보조 스크립트 `jira_fields.py` (07-workflow.md §Step 0·2, 16-existing-assets.md §16.1, 08-safety.md §8.1).

- `check-key`: 이슈 DB `jira_key_regex`로 키 검사(맞지 않으면 1).
- `extract`: 모의 Jira(비표준 커스텀 필드)를 `field_map`으로 읽고, 텍스트는 마스킹, 발생 시각은 UTC로,
  `occurred_on`은 Jira 타임존 날짜로, logcat 연도는 발생 연도로 낸다. 코멘트 작성자는 내지 않는다.

`pytest tests/test_jira_fields.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, run, run_json  # noqa: E402

MOCK_JIRA = REPO / "tests" / "mocks" / "jira"


def _home() -> dict:
    return {"TELEPHONY_TRIAGE_HOME": tempfile.mkdtemp(prefix="tt-home-")}


def test_check_key_uses_db_regex():
    ok = run_json("jira_fields.py", ["check-key", "MOCK-1001", "--db", SAMPLE], env=_home())
    assert ok["valid"] is True
    bad = run("jira_fields.py", ["check-key", "../etc", "--db", SAMPLE], env=_home())
    assert bad.returncode == 1 and json.loads(bad.stdout)["valid"] is False


def test_extract_maps_masks_and_converts_time():
    tmp = Path(tempfile.mkdtemp())
    raw = tmp / "raw.yaml"
    text = (MOCK_JIRA / "MOCK-1001.yaml").read_text(encoding="utf-8")
    text = text.replace("재부팅하면", "테스터 010-1234-5678 IMEI 356938035643809 재부팅하면")
    raw.write_text(text, encoding="utf-8")
    meta = tmp / "meta.json"
    out = run_json("jira_fields.py", ["extract", raw, "--origin", "file", "--db", SAMPLE,
                                      "--meta-out", meta, "--consume"], env=_home())
    assert out["key"] == "MOCK-1001" and out["key_valid"]
    assert out["jira"] == {"key": "MOCK-1001", "origin": "file", "model": "MOCK-A56",
                           "sw": "MOCKA56_U1_20260915", "android_version": "16",
                           "carrier": "MockTel KR", "occurred_on": "2026-09-20"}
    assert out["occurred_at"] == "2026-09-20T05:32:10+00:00"
    assert out["logcat"]["year"] == 2026 and out["sim_slot"] == "0"
    assert out["missing"] == []
    desc = out["text"]["description"]
    assert "010-1234-5678" not in desc and "356938035643809" not in desc
    assert "<MSISDN#" in desc and "<IMEI#" in desc
    blob = json.dumps(out, ensure_ascii=False)
    assert "mock.reporter" not in blob and "mock.dev" not in blob     # 코멘트 작성자(사람 이름)는 내지 않는다
    assert len(out["text"]["comments"]) == 2
    assert not raw.exists()                                           # --consume
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m["occurred_at"] == out["occurred_at"] and m["sw"] == "MOCKA56_U1_20260915"
    assert "010-1234-5678" not in json.dumps(m, ensure_ascii=False)


def test_extract_reports_missing_fields():
    tmp = Path(tempfile.mkdtemp())
    raw = tmp / "raw.json"
    raw.write_text(json.dumps({"key": "MOCK-9", "fields": {"summary": "x"}}), encoding="utf-8")
    out = run_json("jira_fields.py", ["extract", raw, "--db", SAMPLE], env=_home())
    assert out["occurred_at"] is None and "occurred_at" in out["missing"]
    assert {"model", "sw", "android_version"} <= set(out["missing"])
    assert "occurred_on" not in out["jira"] and out["logcat"]["year"] is None


def test_extract_without_failed_step_fields_adds_no_keys():
    tmp = Path(tempfile.mkdtemp())
    raw = tmp / "raw.yaml"
    raw.write_text((MOCK_JIRA / "MOCK-1001.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    meta = tmp / "meta.json"
    out = run_json("jira_fields.py", ["extract", raw, "--origin", "file", "--db", SAMPLE,
                                      "--meta-out", meta], env=_home())
    assert not {"failed_step", "failed_step_auto", "warnings"} & set(out)
    assert "failed_step" not in out["jira"] and "test_steps" not in out["text"]
    assert set(json.loads(meta.read_text(encoding="utf-8"))) == {"key", "sw", "summary", "description", "occurred_at",
                                                                  "android_version"}   # MOCK-1001은 Android 버전이 있다


def test_meta_out_android_version_only_when_present():
    tmp = Path(tempfile.mkdtemp())
    text = (MOCK_JIRA / "MOCK-1001.yaml").read_text(encoding="utf-8")
    metas = []
    for name, body in (("with", text), ("without", re.sub(r"(?m)^.*customfield_10004.*\n", "", text))):
        raw = tmp / f"{name}.yaml"
        raw.write_text(body, encoding="utf-8")
        meta = tmp / f"{name}.json"
        run_json("jira_fields.py", ["extract", raw, "--origin", "file", "--db", SAMPLE, "--meta-out", meta], env=_home())
        metas.append(json.loads(meta.read_text(encoding="utf-8")))
    assert metas[0]["android_version"] == "16" and "android_version" not in metas[1]


def test_extract_failed_step_field_is_masked_and_not_missing():
    import yaml
    tmp = Path(tempfile.mkdtemp())
    data = yaml.safe_load((MOCK_JIRA / "MOCK-1001.yaml").read_text(encoding="utf-8"))
    data["fields"]["customfield_10008"] = "고객 010-1234-5678 데이터 켜기"
    raw = tmp / "raw.yaml"
    raw.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    meta = tmp / "meta.json"
    out = run_json("jira_fields.py", ["extract", raw, "--origin", "file", "--db", SAMPLE,
                                      "--meta-out", meta], env=_home())
    assert "010-1234-5678" not in json.dumps(out, ensure_ascii=False)
    assert "<MSISDN#" in out["jira"]["failed_step"] and out["failed_step"]["source"] == "field"
    assert out["missing"] == [] and "warnings" not in out
    assert json.loads(meta.read_text(encoding="utf-8"))["failed_step"] == out["jira"]["failed_step"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
