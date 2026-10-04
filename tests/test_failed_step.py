#!/usr/bin/env python3
"""실패 스텝(선택 입력) — `common/failedstep.py`와 `jira_fields.py extract` (07-workflow.md §Step 2).

- 우선순위: cli > 필드 > 설명 > 시험 절차 텍스트 > steps-file.
- steps-file: CSV 셀 합치기, cp949, 읽지 못하면 경고 하나와 None.
- 모든 값은 마스킹 후 정규화(≤200자). 잘못된 정규식은 경고.

`pytest tests/test_failed_step.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import failedstep, masking  # noqa: E402
from runner import SAMPLE, run_json  # noqa: E402

MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
PATTERNS = [
    r"(?i)^\s*(?:step|스텝|단계)\s*\d+\s*[.):-]?\s*(?P<step>.+?)\s*[-:|]?\s*(?:fail(?:ed)?|ng|실패)\s*$",
    r"(?i)^\s*(?:failed step|실패\s*(?:스텝|단계))\s*[:：]\s*(?P<step>.+)$",
    r"(?i)^(?P<step>.+?)\s*\|\s*(?:fail(?:ed)?|ng|실패)\s*(?:\|.*)?$",
]


def _home() -> dict:
    return {"TELEPHONY_TRIAGE_HOME": tempfile.mkdtemp(prefix="tt-home-")}


def _masker():
    return masking.new_masker()


def _raw(tmp: Path, field=None, description=None, test_steps=None) -> Path:
    data = yaml.safe_load((MOCK_JIRA / "MOCK-1001.yaml").read_text(encoding="utf-8"))
    if field:
        data["fields"]["customfield_10008"] = field
    if description:
        data["fields"]["description"] += description
    if test_steps:
        data["fields"]["customfield_10007"] = test_steps
    path = tmp / "raw.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _extract(raw: Path, *extra) -> dict:
    return run_json("jira_fields.py", ["extract", raw, "--origin", "file", "--db", SAMPLE, *extra], env=_home())


def test_precedence_cli_field_description_test_steps_file():
    tmp = Path(tempfile.mkdtemp())
    steps = tmp / "steps.txt"
    steps.write_text("Step 9: 파일 스텝 FAIL\n", encoding="utf-8")
    full = _raw(tmp, field="필드 스텝", description="\nStep 2: 설명 스텝 FAIL\n",
                test_steps="Step 1: 절차 스텝 NG\n")
    out = _extract(full, "--failed-step", "CLI 스텝", "--steps-file", steps)
    assert out["failed_step"] == {"text": "CLI 스텝", "source": "cli"}
    assert out["failed_step_auto"]["source"] == "field"
    out = _extract(full, "--steps-file", steps)
    assert out["failed_step"] == {"text": "필드 스텝", "source": "field"}
    assert out["jira"]["failed_step"] == "필드 스텝"
    raw = _raw(tmp, description="\nStep 2: 설명 스텝 FAIL\n", test_steps="Step 1: 절차 스텝 NG\n")
    out = _extract(raw, "--steps-file", steps)
    assert out["failed_step"] == {"text": "설명 스텝", "source": "description"}
    raw = _raw(tmp, test_steps="Step 1: 절차 스텝 NG\n")
    out = _extract(raw, "--steps-file", steps)
    assert out["failed_step"] == {"text": "절차 스텝", "source": "test_steps"}
    assert out["text"]["test_steps"].startswith("Step 1")
    out = _extract(_raw(tmp), "--steps-file", steps)
    assert out["failed_step"] == {"text": "파일 스텝", "source": "steps_file"}
    assert "failed_step_auto" not in out


def test_resolve_precedence_unit():
    m = _masker()
    auto = {"text": "자동", "source": "description"}
    assert failedstep.resolve("직접", auto, None, PATTERNS, m)[0]["source"] == "cli"
    assert failedstep.resolve(None, auto, None, PATTERNS, m)[0] == auto
    assert failedstep.resolve(None, None, None, PATTERNS, m) == (None, [])


def test_csv_row_and_cp949_and_utf8_bom(tmp_path=None):
    tmp = Path(tmp_path or tempfile.mkdtemp())
    csv_file = tmp / "steps.csv"
    csv_file.write_text("no,action,result\n1,Power on,PASS\n3,Enable data,FAIL\n", encoding="utf-8-sig")
    step, warn = failedstep.read_steps_file(csv_file, PATTERNS)
    assert step == "3 | Enable data" and warn is None
    kr = tmp / "steps.txt"
    kr.write_bytes("단계 4: 데이터 켜기 실패\n".encode("cp949"))
    assert failedstep.read_steps_file(kr, PATTERNS) == ("데이터 켜기", None)
    assert csv_file.exists() and kr.exists()          # 복사·삭제하지 않는다


def test_unreadable_steps_file_gives_none_and_one_warning():
    tmp = Path(tempfile.mkdtemp())
    step, warn = failedstep.read_steps_file(tmp / "없음.txt", PATTERNS)
    assert step is None and warn.startswith("steps-file을 읽지 못했다(") and warn.endswith("실패 스텝 없이 진행")
    binary = tmp / "x.bin"
    binary.write_bytes(b"\x00\xff\xfe\x80\x81" * 50)
    step, warn = failedstep.read_steps_file(binary, PATTERNS)
    assert step is None and warn
    res, warnings = failedstep.resolve(None, None, tmp / "없음.txt", PATTERNS, _masker())
    assert res is None and len(warnings) == 1
    big = tmp / "big.txt"
    big.write_bytes(b"a" * (failedstep.MAX_FILE_BYTES + 1))
    assert failedstep.read_steps_file(big, PATTERNS)[0] is None
    # 읽지 못해도 extract는 실패 스텝 키 없이 경고만 낸다
    out = _extract(_raw(tmp), "--steps-file", tmp / "없음.txt")
    assert "failed_step" not in out and len(out["warnings"]) == 1


def test_bad_regex_is_warning_not_error():
    step, warns = failedstep.from_text("Step 1: x FAIL", ["(", *PATTERNS])
    assert step == "x" and len(warns) == 1 and "정규식" in warns[0]
    assert failedstep.from_text("아무 줄", ["("])[0] is None


def test_masking_and_length_limit():
    res, _ = failedstep.resolve("고객 010-1234-5678 데이터 켜기 FAIL " + "가" * 400, None, None, [], _masker())
    assert "010-1234-5678" not in res["text"] and "<MSISDN#" in res["text"]
    assert len(res["text"]) <= failedstep.FAILED_STEP_MAX and res["text"].endswith("…")
    assert failedstep.normalize("a \n  b\t c") == "a b c"


def test_default_patterns_empty_means_no_auto():
    assert failedstep.auto_from(None, "Step 1: x FAIL", "Step 2: y FAIL", [], _masker()) == (None, [])


def test_raw_cli_text_never_reaches_any_job_file():
    from workspace import Workspace
    ws = Workspace()
    raw = "고객 010-1234-5678 데이터 켜기 FAIL"
    args = ["run", "MOCK-1001", "--dry-run", "--jira-file", MOCK_JIRA / "MOCK-1001.yaml",
            "--logs", SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log",
            "--failed-step", raw, "--answer", "code=skip"]
    done = ws.json("triage.py", args)
    assert done["status"] == "ok" and done["jira"]["failed_step"]["source"] == "cli"
    job = ws.job_dir("MOCK-1001")
    files = [p for p in job.rglob("*") if p.is_file()]
    names = {p.name for p in files}
    assert {"trace.jsonl", "triage-state.json", "jira.json", "jira_meta.json", "analysis.json", "report.md"} <= names
    for path in files:
        assert "010-1234-5678" not in path.read_text(encoding="utf-8", errors="replace"), path.name
    jira = json.loads((job / "jira.json").read_text(encoding="utf-8"))
    assert "<MSISDN#" in jira["failed_step"]["text"] and jira["jira"]["failed_step"] == jira["failed_step"]["text"]
    assert "<MSISDN#" in json.loads((job / "jira_meta.json").read_text(encoding="utf-8"))["failed_step"]
    # 같은 명령을 다시 돌려도(멱등) 같은 결과
    again = ws.json("triage.py", args)
    assert again["request_hash"] == done["request_hash"]
    # 플래그 없이 다시 돌리면 자동 추출분만 남는다(이 Jira에는 없음) → 키가 사라진다
    plain = ws.json("triage.py", args[:-4] + ["--answer", "code=skip"])
    assert "failed_step" not in plain["jira"]
    assert "failed_step" not in json.loads((job / "jira.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
