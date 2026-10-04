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


# -- 스텝 목록: html·zip·붙여넣기 ----------------------------------------------------------------------

REPORT_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Report</title>
<style>td { color: red; }</style><script>var rows = "9 | 가짜 스텝 | FAIL";</script></head><body>
<h1>시험 결과</h1>
<table><tr><th>Item</th><th>Value</th></tr><tr><td>Passed</td><td>6</td></tr><tr><td>Overall result</td><td>FAIL</td></tr></table>
<table>
<tr><th>No</th><th>Step</th><th>Result</th><th>Comment</th></tr>
<tr><td>1</td><td>비행기 모드 켜기</td><td>PASS</td><td></td></tr>
<tr><td>2</td><td>비행기 모드 끄기</td><td>PASS</td><td></td></tr>
<tr><td>3</td><td>IMS<br>등록 확인</td><td>PASS</td><td></td></tr>
<tr><td>4</td><td>망 등록 확인</td><td>PASS</td><td>ok &amp; fine</td></tr>
<tr><td>5</td><td>CP 파라미터 설정</td><td>PASS</td><td></td></tr>
<tr><td>6</td><td>모바일 데이터 켜기</td><td>PASS</td><td></td></tr>
<tr><td>7</td><td>데이터 연결 확인</td><td>FAIL</td><td>응답 없음</td></tr>
<tr><td>8</td><td>정리</td><td>FAIL</td><td></td></tr>
</table></body></html>"""
PASTE = """Step 1: 비행기 모드 켜기 PASS
Step 2: 비행기 모드 끄기 PASS
3\tIMS 등록 확인\tPASS
4  망 등록 확인  PASS
5. CP 파라미터 설정 - PASS
Step 6: 모바일 데이터 켜기 PASS
Step 7: 데이터 연결 확인 FAIL
Step 8: 정리 PASS
"""


def _zip(path: Path, members: dict, flag_encrypted: bool = False) -> Path:
    import zipfile
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    if flag_encrypted:       # 중앙 디렉터리의 일반 목적 비트 0(암호화)을 켠다(첫 항목)
        raw = bytearray(path.read_bytes())
        raw[raw.find(b"PK\x01\x02") + 8] |= 1
        path.write_bytes(bytes(raw))
    return path


def _expected_steps(rows):
    return [(r["number"], r["name_raw"], r["status"]) for r in rows]


SEVEN = [(1, "비행기 모드 켜기", "pass"), (2, "비행기 모드 끄기", "pass"), (3, "IMS 등록 확인", "pass"),
         (4, "망 등록 확인", "pass"), (5, "CP 파라미터 설정", "pass"), (6, "모바일 데이터 켜기", "pass"),
         (7, "데이터 연결 확인", "fail")]


def test_html_report_table_gives_steps_with_fail_last():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "report.html"
    path.write_text(REPORT_HTML, encoding="utf-8")
    text, why, member = failedstep.read_source(path)
    assert why is None and member is None
    assert "var rows" not in text and "color: red" not in text            # script·style은 버린다
    assert "4 | 망 등록 확인 | PASS | ok & fine" in text and "3 | IMS 등록 확인 | PASS" in text
    steps, failed, warnings, member = failedstep.read_steps(path)
    assert _expected_steps(steps) == SEVEN and failed == 6 and member is None        # 첫 FAIL(7)에서 끊는다
    assert [r["index"] for r in steps] == list(range(7))
    assert len(warnings) == 1 and "FAIL 스텝이 2개" in warnings[0]                     # 8번도 FAIL
    assert failedstep.label(steps[6], _masker()) == "7 | 데이터 연결 확인"
    # 요약 표(Passed·Overall result)는 스텝이 아니다
    assert not any(r["name_raw"] in ("6", "Overall result") for r in steps)


def test_text_paste_format_gives_same_steps():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "steps-pasted.txt"
    path.write_text(PASTE, encoding="utf-8")
    steps, failed, warnings, member = failedstep.read_steps(path)
    assert _expected_steps(steps) == SEVEN and failed == 6 and warnings == [] and member is None


def test_parse_steps_time_status_words_and_limits():
    rows = failedstep.parse_steps("no,action,result,start,end\n".replace(",", " | ") +
                                  "1 | 켜기 | OK | 14:30:10 | 14:30:20\n2 | 확인 | 실패 | 14:30:30\n")
    assert [(r["status"], r["time_raw"]) for r in rows] == [("pass", "14:30:10 14:30:20"), ("fail", "14:30:30")]
    assert failedstep.parse_steps("상태 없는 줄\n다른 줄 | 값\n") == []
    custom = {"steps_status": {"pass": ["합격"], "fail": ["불합격"]}}
    assert [r["status"] for r in failedstep.parse_steps("1 | 켜기 | 합격\n2 | 끄기 | 불합격", custom)] == ["pass", "fail"]
    many = "\n".join(f"{i} | 스텝 {i} | PASS" for i in range(1, 700))
    assert len(failedstep.parse_steps(many)) == 500


def test_zip_member_priority_and_in_memory_read():
    tmp = Path(tempfile.mkdtemp())
    decoy = "<table><tr><th>No</th><th>Step</th><th>Result</th></tr><tr><td>1</td><td>가짜</td><td>FAIL</td></tr></table>"
    path = _zip(tmp / "att.zip", {"index.html": decoy, "notes.txt": "1 | 메모 | FAIL\n", "run_01/report.html": REPORT_HTML,
                                  "run_01/shot.png": b"\x89PNG", "a/b/c/Report.HTML": decoy})
    steps, failed, warnings, member = failedstep.read_steps(path)
    assert member == "run_01/report.html" and _expected_steps(steps) == SEVEN
    assert sorted(p.name for p in tmp.iterdir()) == ["att.zip"]                  # 풀지 않는다
    # report.html이 없으면 다른 html > csv/txt, 같은 단계에서는 얕은 경로 > 이름 순
    path = _zip(tmp / "b.zip", {"z/deep/x.csv": "1,켜기,FAIL\n", "m/a.htm": decoy, "b.html": decoy.replace("가짜", "둘째"),
                                "a.html": decoy.replace("가짜", "첫째")})
    steps, failed, _, member = failedstep.read_steps(path)
    assert member == "a.html" and steps[0]["name_raw"] == "첫째"
    path = _zip(tmp / "c.zip", {"notes.txt": "Step 3: 켜기 FAIL\n", "dir/steps.csv": "1,켜기,FAIL\n"})
    assert failedstep.read_steps(path)[3] == "notes.txt"
    assert failedstep.read_source(path)[2] == "notes.txt"
    assert failedstep.read_lines(path)[0].startswith("Step 3")


def test_zip_oversize_corrupt_encrypted_and_unsafe_members():
    tmp = Path(tempfile.mkdtemp())
    big = _zip(tmp / "big.zip", {"report.html": "<tr><td>1</td><td>x</td><td>FAIL</td></tr>" + " " * (6 * 1024 * 1024)})
    steps, failed, warnings, member = failedstep.read_steps(big)
    assert steps == [] and failed is None and member is None
    assert len(warnings) == 1 and warnings[0].startswith("steps-file을 읽지 못했다(5 MiB 초과)")
    bad = tmp / "bad.zip"
    bad.write_bytes(b"PK\x03\x04junk")
    steps, failed, warnings, member = failedstep.read_steps(bad)
    assert steps == [] and len(warnings) == 1 and "zip" in warnings[0]
    enc = _zip(tmp / "enc.zip", {"report.html": REPORT_HTML, "other.txt": "1 | 켜기 | FAIL\n"}, flag_encrypted=True)
    steps, failed, warnings, member = failedstep.read_steps(enc)
    assert steps == [] and member is None and len(warnings) == 1 and "암호화" in warnings[0]    # 낮은 단계 후보로 넘어가지 않는다
    unsafe = _zip(tmp / "unsafe.zip", {"../x.html": REPORT_HTML, "/abs/report.html": REPORT_HTML,
                                       "ok/steps.csv": "1,켜기,PASS\n2,확인,FAIL\n"})
    steps, failed, warnings, member = failedstep.read_steps(unsafe)
    assert member == "ok/steps.csv" and failed == 1 and steps[1]["name_raw"] == "확인"
    only_unsafe = _zip(tmp / "only.zip", {"../x.html": REPORT_HTML})
    assert failedstep.read_steps(only_unsafe)[0] == []
    # 해당 파일 없음
    none = _zip(tmp / "none.zip", {"shot.png": b"x"})
    assert failedstep.read_steps(none)[2][0].startswith("steps-file을 읽지 못했다(")
    res, warns = failedstep.resolve(None, None, bad, [], _masker())
    assert res is None and len(warns) == 1


def test_resolve_falls_back_to_fail_row_after_patterns():
    tmp = Path(tempfile.mkdtemp())
    html = tmp / "report.html"
    html.write_text(REPORT_HTML, encoding="utf-8")
    res, warns = failedstep.resolve(None, None, html, [], _masker())                 # 패턴 없음 → 표의 FAIL 스텝
    assert res == {"text": "7 | 데이터 연결 확인", "source": "steps_file"} and warns == []
    # 패턴이 맞으면 패턴이 먼저다(옛 동작)
    res, _ = failedstep.resolve(None, None, html, [r"(?i)^\d+\s*\|\s*(?P<step>.+?)\s*\|\s*FAIL"], _masker())
    assert res == {"text": "데이터 연결 확인", "source": "steps_file"}
    paste = tmp / "p.txt"
    paste.write_text(PASTE, encoding="utf-8")
    assert failedstep.resolve(None, None, paste, [], _masker())[0]["text"] == "7 | 데이터 연결 확인"
    assert failedstep.resolve("직접", None, html, [], _masker())[0]["source"] == "cli"      # 우선순위는 그대로
    # extract는 site-defaults의 failed_step_patterns가 먼저다(붙여넣기 줄 "Step 7: … FAIL"에 맞는다)
    out = _extract(_raw(tmp), "--steps-file", paste)
    assert out["failed_step"] == {"text": "데이터 연결 확인", "source": "steps_file"}
    # html의 요약 표("Overall result | FAIL")는 표 머리 앞이라 패턴이 먼저 잡지 않는다
    out = _extract(_raw(tmp), "--steps-file", html)
    assert out["failed_step"] == {"text": "7 | 데이터 연결 확인", "source": "steps_file"}


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
