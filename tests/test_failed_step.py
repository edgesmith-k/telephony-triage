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
    assert out["issue"]["failed_step"] == "필드 스텝"
    raw = _raw(tmp, description="\nStep 2: 설명 스텝 FAIL\n", test_steps="Step 1: 절차 스텝 NG\n")
    out = _extract(raw, "--steps-file", steps)
    assert out["failed_step"] == {"text": "2 | 설명 스텝", "source": "description"}
    raw = _raw(tmp, test_steps="Step 1: 절차 스텝 NG\n")
    out = _extract(raw, "--steps-file", steps)
    assert out["failed_step"] == {"text": "1 | 절차 스텝", "source": "test_steps"}
    assert out["text"]["test_steps"].startswith("Step 1")
    out = _extract(_raw(tmp), "--steps-file", steps)
    assert out["failed_step"] == {"text": "9 | 파일 스텝", "source": "steps_file"}
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
    assert failedstep.read_steps_file(kr, PATTERNS) == ("4 | 데이터 켜기", None)
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


def test_numbered_label_matches_table_and_field():
    # 패턴이 이름만 뽑아도 줄이 스텝 번호로 시작하면 `번호 | 이름`(표의 FAIL 행·Jira 필드와 같은 표기)
    assert failedstep.from_text("Step 7: 데이터 연결 확인 FAIL", PATTERNS)[0] == "7 | 데이터 연결 확인"
    assert failedstep.from_text("실패 스텝: 데이터 켜기", PATTERNS)[0] == "데이터 켜기"     # 번호가 없으면 그대로
    assert failedstep.from_text("5 | 데이터 켜기 | FAIL", PATTERNS)[0] == "5 | 데이터 켜기"  # 이미 번호가 있으면 그대로
    assert failedstep.from_text("3G 데이터 실패", [r"(?P<step>.+?)\s*실패$"])[0] == "3G 데이터"   # 숫자+구분자가 아니면 번호 아님


def test_numbered_ignores_timestamps_and_dates():
    for line in ("12:03:44 FAIL step=Attach", "2026.09.21 Attach FAIL", "2026-09-21 Attach FAIL", "2026. 09. 21 Attach FAIL",
                 "3G 데이터 실패", "10.5 Attach FAIL"):
        assert failedstep.numbered("Attach", line) == "Attach", line
    assert failedstep.numbered("Attach", "7. Attach FAIL") == "7 | Attach"
    assert failedstep.numbered("Attach", "7) Attach FAIL") == "7 | Attach"
    assert failedstep.numbered("Attach", "7 | Attach | FAIL") == "7 | Attach"


def test_numbered_strips_number_already_in_step():
    for step in ("7. Attach PDN", "Step 7 Attach PDN", "7) Attach PDN", "스텝 7: Attach PDN"):
        assert failedstep.numbered(step, step + " FAIL") == "7 | Attach PDN", step
    assert failedstep.numbered("7 | Attach PDN", "x") == "7 | Attach PDN"
    assert failedstep.numbered(None, "7. x") is None


def test_bad_regex_is_warning_not_error():
    step, warns = failedstep.from_text("Step 1: x FAIL", ["(", *PATTERNS])
    assert step == "1 | x" and len(warns) == 1 and "정규식" in warns[0]
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
    assert res == {"text": "7 | 데이터 연결 확인", "source": "steps_file"}
    paste = tmp / "p.txt"
    paste.write_text(PASTE, encoding="utf-8")
    assert failedstep.resolve(None, None, paste, [], _masker())[0]["text"] == "7 | 데이터 연결 확인"
    assert failedstep.resolve("직접", None, html, [], _masker())[0]["source"] == "cli"      # 우선순위는 그대로
    # extract는 site-defaults의 failed_step_patterns가 먼저다(붙여넣기 줄 "Step 7: … FAIL"에 맞는다)
    out = _extract(_raw(tmp), "--steps-file", paste)
    assert out["failed_step"] == {"text": "7 | 데이터 연결 확인", "source": "steps_file"}
    # html의 요약 표("Overall result | FAIL")는 표 머리 앞이라 패턴이 먼저 잡지 않는다
    out = _extract(_raw(tmp), "--steps-file", html)
    assert out["failed_step"] == {"text": "7 | 데이터 연결 확인", "source": "steps_file"}


def test_raw_cli_text_never_reaches_any_job_file():
    from workspace import Workspace
    ws = Workspace()
    raw = "고객 010-1234-5678 데이터 켜기 FAIL"
    args = ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA / "MOCK-1001.yaml",
            "--logs", SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log",
            "--failed-step", raw, "--answer", "code=skip"]
    done = ws.json("triage.py", args)
    assert done["status"] == "ok" and done["issue"]["failed_step"]["source"] == "cli"
    job = ws.job_dir("MOCK-1001")
    files = [p for p in job.rglob("*") if p.is_file()]
    names = {p.name for p in files}
    assert {"trace.jsonl", "triage-state.json", "issue.json", "issue_meta.json", "analysis.json", "report.md"} <= names
    for path in files:
        assert "010-1234-5678" not in path.read_text(encoding="utf-8", errors="replace"), path.name
    jira = json.loads((job / "issue.json").read_text(encoding="utf-8"))
    assert "<MSISDN#" in jira["failed_step"]["text"] and jira["issue"]["failed_step"] == jira["failed_step"]["text"]
    assert "<MSISDN#" in json.loads((job / "issue_meta.json").read_text(encoding="utf-8"))["failed_step"]
    # 같은 명령을 다시 돌려도(멱등) 같은 결과
    again = ws.json("triage.py", args)
    assert again["request_hash"] == done["request_hash"]
    # 플래그 없이 다시 돌리면 자동 추출분만 남는다(이 Jira에는 없음) → 키가 사라진다
    plain = ws.json("triage.py", args[:-4] + ["--answer", "code=skip"])
    assert "failed_step" not in plain["issue"]
    assert "failed_step" not in json.loads((job / "issue.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_parse_steps_date_cell_is_not_step_number():
    """표 행 앞 날짜 칸은 스텝 번호도 이름도 아니다(S2b)."""
    rows = failedstep.parse_steps("2026.09.21 10:00:01 | Attach PDN | PASS\n2026-09-21 10:00:09 | Data call | FAIL\n")
    assert [(r["number"], r["name_raw"], r["time_raw"]) for r in rows] == \
        [(None, "Attach PDN", "10:00:01"), (None, "Data call", "2026-09-21 10:00:09")]
    assert [(r["number"], r["name_raw"]) for r in failedstep.parse_steps("2026-09-21 | 3 | Attach | FAIL\n")] == [(3, "Attach")]


def test_parse_steps_reads_verdict_with_reason():
    """판정 칸 뒤에 사유가 붙어도(`Fail (사유)`·`FAIL: 사유`·`Fail - 사유`·`Fail [코드]`, `Pass (retry 1)`) 판정으로 읽는다.
    사유는 스텝 이름에 섞이지 않는다(사유는 problem의 "TC의 Fail 줄" 절이 싣는다)."""
    want = [(1, "Attach", "pass"), (2, "데이터 켜기", "fail")]
    for cell in ("Fail (timeout)", "FAIL: no response", "Fail - 응답 없음", "Fail [E12]", "Failed(timeout)"):
        for head in ("No | Step | Result\n", ""):          # 표 머리가 있을 때(판정 열)와 없을 때(오른쪽부터 훑기)
            rows = failedstep.parse_steps(f"{head}1 | Attach | Pass (retry 1)\n2 | 데이터 켜기 | {cell}\n")
            assert _expected_steps(rows) == want, (head, cell)
    # 칸이 나뉘지 않은 한 줄(번호가 있을 때)
    rows = failedstep.parse_steps("Step 1: Attach Pass (retry 1)\nStep 2: 데이터 켜기 Fail (timeout)\n")
    assert _expected_steps(rows) == want
    # 설정의 여러 단어 판정어도 같은 규칙
    custom = {"steps_status": {"pass": ["ok"], "fail": ["not ok"]}}
    assert _expected_steps(failedstep.parse_steps("1 | Attach | ok\n2 | 데이터 켜기 | Not OK (timeout)\n", custom)) == want
    # steps-file로 실패 스텝을 고를 때도(run --steps-file 경로)
    path = Path(tempfile.mkdtemp()) / "steps.txt"
    path.write_text("No | Step | Result\n1 | Attach | Pass\n2 | 데이터 켜기 | Fail (No response)\n3 | 정리 | Fail (skipped)\n", encoding="utf-8")
    steps, failed, warnings, _ = failedstep.read_steps(path)
    assert failed == 1 and _expected_steps(steps) == want and "FAIL 스텝이 2개" in warnings[0]
    assert failedstep.resolve(None, None, path, [], _masker())[0] == {"text": "2 | 데이터 켜기", "source": "steps_file"}


def test_parse_steps_step_names_like_verdict_are_not_verdicts():
    """`Fail-safe check`·`Failover test`·`Passive scan`은 스텝 이름이다. 이름 칸이 사유 붙은 판정 모양이어도 판정 칸의 전체 일치가 먼저,
    판정 열을 아는 표에서는 다른 칸의 사유 붙은 모양을 판정으로 보지 않는다."""
    rows = failedstep.parse_steps("1 | Fail-safe check | Pass\n2 | Failover test | PASS\n3 | Passive scan | FAIL\n"
                                  "4 | Fail (timeout) 재현 | PASS\n")
    assert _expected_steps(rows) == [(1, "Fail-safe check", "pass"), (2, "Failover test", "pass"), (3, "Passive scan", "fail"),
                                     (4, "Fail (timeout) 재현", "pass")]
    assert failedstep.parse_steps("No | Step | Result\n5 | NG (no grant) 확인 | Skip\n") == []
    # 괄호 사유는 칸(한 줄 형식은 줄) 끝에서 닫혀야 판정이다
    assert failedstep.parse_steps("Step 4: Press OK (popup) button\nStep 5: NG (no grant) 확인\nStep 6: Fail (timeout) 재현\n") == []
    assert failedstep.parse_steps("5 | 확인 | NG (no grant) 확인\n") == []
    # 표 머리가 없으면 이름 자리(번호 다음 칸, 번호가 없으면 첫 칸)는 사유 붙은 판정으로 보지 않는다
    assert failedstep.parse_steps("3 | 실패 (재시도 포함) | Skip\n3 | NG: 거절 확인 | N/A\n") == []
    assert _expected_steps(failedstep.parse_steps("3 | 데이터 켜기 | Fail (timeout)\n데이터 켜기 | Fail (timeout)\n")) == \
        [(3, "데이터 켜기", "fail"), (None, "데이터 켜기", "fail")]


def test_summary_row_is_not_failed_step():
    """번호 없이 이름이 합계 단어 그대로인 줄(`Overall result | FAIL`·`Total | FAIL`·`합계 | FAIL`)은 스텝이 아니다."""
    text = "Overall result | FAIL\n1 | Attach | PASS\n2 | 데이터 켜기 | Fail (timeout)\nTotal | FAIL\n합계: | FAIL\n"
    assert _expected_steps(failedstep.parse_steps(text)) == [(1, "Attach", "pass"), (2, "데이터 켜기", "fail")]
    path = Path(tempfile.mkdtemp()) / "steps.txt"
    path.write_text(text, encoding="utf-8")
    steps, failed, warnings, _ = failedstep.read_steps(path)
    assert failed == 1 and warnings == []


def test_failure_detail_line_with_same_step_number_is_not_a_second_step():
    """sim1120 P2-2: 결과 HTML 끝 `Failure detail`의 "Step 2: … Preliminary verdict: FAIL"은 같은 번호·판정의 요약이라 스텝으로 세지
    않는다 — "FAIL 스텝 2개" 경고가 없다. 번호가 같아도 판정이 다르면(PASS 뒤 재시도 FAIL) 둘 다 스텝이다."""
    text = "\n".join(["No | Time | Message | Description | Verdict", "1 | 06:42:42.000 | - | Apply profile | PASS",
                      "2 | 06:42:51.000 | - | ICMP echo to UE x10 | FAIL",
                      "Step 2: ICMP echo 10 sent, 0 replied within 2 s timeout. Preliminary verdict: FAIL"])
    rows = failedstep.parse_steps(text)
    assert [(r["number"], r["status"]) for r in rows] == [(1, "pass"), (2, "fail")]
    retry = failedstep.parse_steps("\n".join(["1 | attach | PASS", "2 | data on | PASS", "2 | data on (retry) | FAIL"]))
    assert [(r["number"], r["status"]) for r in retry] == [(1, "pass"), (2, "pass"), (2, "fail")]
    # 바로 앞 스텝과만 비교한다 — 떨어져 다시 나온 같은 번호(재시도 회차)는 스텝이다(리뷰 1bb528a7)
    head = "No | Message | Verdict\n"
    rerun = failedstep.parse_steps(head + "1 | on | PASS\n2 | attach | PASS\n1 | on | PASS\n2 | attach | FAIL\n")
    assert [(r["number"], r["status"]) for r in rerun] == [(1, "pass"), (2, "pass"), (1, "pass"), (2, "fail")]
    twice = failedstep.parse_steps(head + "1 | on | PASS\n2 | attach | FAIL\n1 | on | PASS\n2 | attach | FAIL\n")
    assert [(r["number"], r["status"]) for r in twice] == [(1, "pass"), (2, "fail"), (1, "pass"), (2, "fail")]


# -- sim1121 TC 결과 HTML(합성 장비 보고서 모양) -------------------------------------------------------

TC_HTML = REPO / "tests" / "fixtures" / "tc-html"


def test_sim1121_tc_html_fail_step_number_name_and_time():
    """sim1121 P0: 열 이름 `Message / Action`(낱말 포함)·번호 열 `Step`·빈 `<td>`·INCONC. 요약 표 `Verdict | FAIL`이 스텝 표 앞에
    있어도 스텝 표의 FAIL 줄을 번호·이름·장비 시각으로 읽는다. 한 줄 표와 줄마다 나눈 표 둘 다."""
    want = {"sim-oneline-fail.html": (4, "RRCConnectionSetupComplete / ATTACH REQUEST / PDN CONNECTIVITY REQUEST", "00:08:22.164"),
            "sim-multiline-fail.html": (8, "PDU SESSION ESTABLISHMENT REQUEST", "17:21:00.360"),
            "sim-inconc.html": (2, "Wait SIP REGISTER on PSI=2", "17:47:25.100")}       # INCONC도 시험이 멈춘 자리
    for name, (number, step, clock) in want.items():
        rows, failed, warnings, _ = failedstep.read_steps(TC_HTML / name)
        assert failed is not None, (name, warnings)
        row = rows[failed]
        assert (row["number"], row["name_raw"], row["time_raw"]) == (number, step, clock), name
        assert not any(w.startswith(failedstep.NOT_FOUND) for w in warnings), name
        assert failedstep.read_steps_file(TC_HTML / name, PATTERNS)[0].startswith(f"{number} | "), name
    rows, failed, _, _ = failedstep.read_steps(TC_HTML / "sim-oneline-fail.html")
    assert [(r["number"], r["status"]) for r in rows] == [(4, "fail")]      # P·PA·`-` 줄은 스텝 판정이 아니다(PASS는 FAIL 뒤)


def test_not_found_always_warns_with_header_read():
    """FAIL 스텝을 못 찾으면 늘 경고한다 — PASS 줄이 하나도 없어도(전에는 조용히 0). 읽은 표 머리를 남겨 양식 차이를 볼 수 있게."""
    _, failed, warnings, _ = failedstep.read_steps(TC_HTML / "sim-pass.html")
    assert failed is None and warnings == [
        "steps-file에서 FAIL 스텝을 찾지 못했다 — 읽은 표의 첫 줄(열 이름): Step | Time | Dir | Message / Action | Key IEs / Note | "
        "Verdict, 판정을 읽은 스텝 3줄"]
    path = Path(tempfile.mkdtemp()) / "odd.html"
    path.write_text("<table><tr><th>Seq</th><th>Event</th><th>Outcome</th></tr><tr><td>1</td><td>x</td><td>bad</td></tr>"
                    "</table>", encoding="utf-8")
    _, failed, warnings, _ = failedstep.read_steps(path)
    assert failed is None and warnings == [f"{failedstep.NOT_FOUND} — 열 이름 줄(번호·이름·판정 열)을 찾지 못함, 판정을 읽은 스텝 0줄"]


def test_empty_cells_keep_column_positions():
    """빈 `<td>`·빈 CSV 칸을 버리면 칸 수가 머리와 달라 열 위치를 못 쓰고 이름에 다른 열(`Dir`)이 섞인다 — 자리로 남긴다."""
    html = ("<table><tr><th>No</th><th>Time</th><th>Dir</th><th>Step</th><th>Note</th><th>Result</th></tr>"
            "<tr><td>1</td><td>10:00:01.000</td><td>UE-&gt;SS</td><td>Attach</td><td>ok</td><td>PASS</td></tr>"
            "<tr><td>2</td><td>10:00:09.500</td><td>UE-&gt;SS</td><td>Data call</td><td></td><td>FAIL</td></tr></table>")
    assert [(r["number"], r["name_raw"], r["status"], r["time_raw"]) for r in failedstep.parse_steps(failedstep.html_to_lines(
        html.encode())[0])] == [(1, "Attach", "pass", "10:00:01.000"), (2, "Data call", "fail", "10:00:09.500")]
    path = Path(tempfile.mkdtemp()) / "steps.csv"
    path.write_text("No,Time,Dir,Step,Note,Result\n1,10:00:01,UE->SS,Attach,ok,PASS\n2,10:00:09,UE->SS,Data call,,FAIL\n",
                    encoding="utf-8")
    rows, failed, _, _ = failedstep.read_steps(path)
    assert (rows[failed]["number"], rows[failed]["name_raw"]) == (2, "Data call")


def test_header_word_match_does_not_turn_data_rows_into_header():
    """낱말 포함 비교는 숫자 없는 짧은 칸만 — 머리 없는 줄 `Step 3 | Verify result | PASS`가 표 머리로 잡히지 않는다. 이름 열이 따로
    없는 `Step | Result`는 전처럼 `Step`이 이름 열이다."""
    rows = failedstep.parse_steps("Step 1 | Attach | PASS\nStep 2 | Verify result | PASS\nStep 3 | Data call | FAIL\n")
    assert _expected_steps(rows) == [(1, "Attach", "pass"), (2, "Verify result", "pass"), (3, "Data call", "fail")]
    assert _expected_steps(failedstep.parse_steps("Step | Result\n1. Attach | PASS\n데이터 켜기 | FAIL\n")) == \
        [(1, "Attach", "pass"), (None, "데이터 켜기", "fail")]


# -- sim1121 리뷰: 열 이름 고르는 순서·옛 양식·INCONC -------------------------------------------------------


def _fail_of(text):
    rows = failedstep.parse_steps(text)
    idx, _ = failedstep._pick_failed(rows)
    return (rows[idx]["number"], rows[idx]["name_raw"]) if idx is not None else None


def test_exact_column_name_wins_over_contained_one():
    """리뷰 P0-1: 한 줄 안에서 칸 전체가 열 이름인 칸(`Result`·`결과`·`Verdict`)을 먼저 정하고, 낱말 포함(`Expected Result`·
    `기대 결과`·`Expected Verdict`)은 못 정한 열에만 — 기대값 칸이 판정 열이 되어 FAIL을 놓치거나 기대값 NG 줄을 고르지 않게."""
    assert _fail_of("No | Step | Expected Result | Result\n1 | Power | OK | PASS\n2 | Attach | OK | FAIL\n3 | Detach | OK | PASS\n") \
        == (2, "Attach")
    assert _fail_of("No | Step | Expected Result | Result\n1 | Power | OK | PASS\n2 | Bad APN | NG | PASS\n3 | Attach | OK | FAIL\n") \
        == (3, "Attach")
    assert _fail_of("번호 | 절차 | 기대 결과 | 결과\n1 | 전원 | 성공 | 통과\n2 | 데이터 | 성공 | 실패\n") == (2, "데이터")
    assert _fail_of("Step | Action | Expected Verdict | Verdict\n1 | Power | PASS | PASS\n2 | Attach | PASS | FAIL\n") == (2, "Attach")


def test_old_forms_still_read():
    """리뷰 P1-4: 옛 양식 — `Step` 열에 이름(Init·Attach)이 든 표, 한 줄 요약 표 `Failed Step | Step 3 | Verdict | FAIL`이 스텝 표
    앞에 있는 HTML, Jira 위키 표 `||No||Step||…||`(머리와 줄의 빈 칸 수가 다르다), 열 순서가 바뀐 `Step | No | Result`,
    번호 열이 첫 칸이 아닌 `Time | No | Step | Result`."""
    assert _fail_of("Step | Description | Result\nAttach | UE sends attach | PASS\nPDN connect | UE sends PDN | FAIL\n") \
        == (None, "PDN connect")
    assert _fail_of("Step | Action | Result\nInit | Power | PASS\nAttach | Send | FAIL\n") == (None, "Attach")
    html = ("<table><tr><td>Failed Step</td><td>Step 3</td><td>Verdict</td><td>FAIL</td></tr></table><table>"
            "<tr><td>No</td><td>Step</td><td>Time</td><td>Result</td></tr>"
            "<tr><td>1</td><td>Power</td><td>10:00:00.000</td><td>PASS</td></tr>"
            "<tr><td>3</td><td>PDN</td><td>10:00:02.000</td><td>FAIL</td></tr></table>")
    rows = failedstep.parse_steps(failedstep.html_to_lines(html.encode())[0])
    assert [(r["number"], r["name_raw"], r["status"], r["time_raw"]) for r in rows] == \
        [(1, "Power", "pass", "10:00:00.000"), (3, "PDN", "fail", "10:00:02.000")]
    summary = html.replace("<td>Failed Step</td><td>Step 3</td><td>Verdict</td><td>FAIL</td>",      # 요약 칸 순서가 달라도
                           "<td>Verdict</td><td>FAIL</td><td>Failed Step</td><td>Step 3</td>")
    assert _fail_of(failedstep.html_to_lines(summary.encode())[0]) == (3, "PDN")
    assert _fail_of("||No||Step||Expected||Result||\n|1|Power on|UE on|PASS|\n|2|Attach|Accept|FAIL|\n") == (2, "Attach")
    assert _fail_of("Step | No | Result\nPower | 1 | PASS\nAttach | 2 | FAIL\n") == (2, "Attach")
    rows = failedstep.parse_steps("Time | No | Step | Result\n10:00:00.000 | 1 | Power | PASS\n10:00:05.000 | 2 | Attach | FAIL\n")
    assert [(r["number"], r["name_raw"], r["time_raw"]) for r in rows] == \
        [(1, "Power", "10:00:00.000"), (2, "Attach", "10:00:05.000")]


def test_long_row_keeps_verdict_cell_past_500_chars():
    """긴 IE 칸(500자 넘는 줄) 뒤의 판정 칸이 잘리지 않는다(칸 나누기 줄 상한 4000자)."""
    rows = failedstep.parse_steps("No | Step | Note | Result\n1 | Power | ok | PASS\n2 | Attach | " + "x" * 600 + " | FAIL\n")
    assert [(r["number"], r["status"]) for r in rows] == [(1, "pass"), (2, "fail")]


def test_inconc_only_when_no_fail():
    """리뷰 P1-2: FAIL이 있으면 첫 FAIL(앞의 INCONC는 경고만), FAIL이 없을 때만 첫 INCONC를 실패 스텝으로 쓰고 그렇다고 경고한다.
    "N개 있다" 경고는 고른 판정의 수만 센다."""
    path = Path(tempfile.mkdtemp()) / "steps.txt"
    path.write_text("No | Step | Result\n1 | Power | PASS\n2 | Optional | INCONC\n3 | Attach | FAIL\n", encoding="utf-8")
    rows, failed, warnings, _ = failedstep.read_steps(path)
    assert (rows[failed]["number"], rows[failed]["status"]) == (3, "fail")
    assert warnings == ["steps-file의 첫 FAIL 앞에 INCONC 스텝이 있다 — 첫 FAIL을 실패 스텝으로 썼다"]
    path.write_text("No | Step | Result\n1 | Power | PASS\n2 | Register | INCONC\n3 | Retry | INCONC\n", encoding="utf-8")
    rows, failed, warnings, _ = failedstep.read_steps(path)
    assert (rows[failed]["number"], rows[failed]["status"]) == (2, "inconc")
    assert warnings == [failedstep.INCONC_USED, "steps-file에 INCONC 스텝이 2개 있다 — 첫 번째를 실패 스텝으로 썼다"]
    assert failedstep.read_steps_file(path, [])[0] == "2 | Register"
    _, failed, warnings, _ = failedstep.read_steps(TC_HTML / "sim-inconc.html")
    assert failed is not None and warnings == [failedstep.INCONC_USED]


def test_sim1121_tc_html_with_site_columns_written_before_step_number():
    """사내 site-defaults.yaml이 옛 열 이름(`step`이 이름 쪽에만, 판정 단어에 inconc 키 없음)이어도 장비 결과 HTML을 읽는다 — 이름
    열로 본 `Step` 칸이 번호뿐이면 번호 열로 보고 이름 열(`Message / Action`)을 다시 찾는다."""
    old = {"steps_status": {"pass": ["pass", "passed", "ok", "성공", "통과"], "fail": ["fail", "failed", "ng", "실패"]},
           "steps_columns": {"number": ["no", "#", "step no", "번호"], "name": ["step", "action", "name", "description", "절차", "내용", "항목"],
                             "status": ["result", "status", "verdict", "결과", "판정"], "start": ["start", "start time", "시작"],
                             "end": ["end", "end time", "종료", "time", "시각"]}}
    for name, want in (("sim-oneline-fail.html", (4, "00:08:22.164")), ("sim-inconc.html", (2, "17:47:25.100"))):
        rows, failed, _, _ = failedstep.read_steps(TC_HTML / name, old)
        assert failed is not None and (rows[failed]["number"], rows[failed]["time_raw"]) == want, name
        assert not rows[failed]["name_raw"].isdigit(), name
