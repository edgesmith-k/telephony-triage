"""'사용자에게 보였다' 공용 판정(plugin/scripts/common/shown.py): 정규화, 실행 기록 읽기(stream-json·transcript), 표시 의무,
초안 검증표 규칙별 행, show_guard가 거부한 질문 제외 (08-safety.md "표시 보조 hook", tests/skill_evals/README.md)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import shown  # noqa: E402

STAGE_CMD = "python3 /p/scripts/db_pr.py stage /w/MOCK-1/plan.json --then-summary"
PUBLISH_CMD = "python3 /p/scripts/db_pr.py publish /w/MOCK-1/wt --approved abc1234def --commit"
TRIAGE_CMD = "python3 /p/scripts/triage.py run MOCK-1 --logs logs/a.log"
DRAFT_CMD = "python3 /p/scripts/db_verify.py rules --plan /w/MOCK-1/plan.json --draft /w/MOCK-1/draft --json"
ASK = "mcp__eval-approver__ask_user"
SCREEN = """## push 전 확인: MOCK-1 → DATA-001-01 Data disabled
구분: 분석 (analyze)

| 구분 | 파일 | 변경 |
|---|---|---|
| 생성 파일 | README.md | 수정 |

```diff
+key: MOCK-1
```

approved_hash: abc1234def
"""
REPORT = """## MOCK-1 분석

- 분류 후보: data > DATA-001 > DATA-001-01 Data disabled (규칙 일치 점수 1.0)
- 근거 로그 (마스킹, 슬롯 phone 0):
  - 2026-09-20T05:30:03.000Z DSMGR-0 notifyDataEnabledChanged: enabled=false (f0:L2)
- 원인: TODO(LLM) — 나눠 쓴다
"""
MUST = "로그 범위: 2026-09-20T05:30:00.000Z ~ 2026-09-20T05:30:29.900Z (일부만 포함)"
RULES = [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
         {"id": "R3", "status": "fail", "reason": "C=1 — R4 fixture"},
         {"id": "R5", "status": "skipped", "reason": "해당 없음"}]


def tool(tid, name, inp, result="", error=False):
    return {"kind": "tool", "id": tid, "name": name, "input": inp, "result": result, "error": error}


def bash(tid, cmd, out):
    return tool(tid, "Bash", {"command": cmd}, out)


def text(t):
    return {"kind": "text", "text": t}


def test_norm_line_tables_quotes_bullets():
    assert shown.norm_line("> |  생성 파일 |README.md|  수정 |") == "생성 파일|README.md|수정"
    assert shown.norm_line("- **분류 후보**: x", bullets=True) == "분류 후보: x"
    assert shown.norm_line("a   b\t c") == "a b c"
    assert shown.screen_lines(SCREEN) == ["## push 전 확인: MOCK-1 → DATA-001-01 Data disabled", "구분: 분석 (analyze)",
                                          "구분|파일|변경", "생성 파일|README.md|수정", "+key: MOCK-1",
                                          "approved_hash: abc1234def"]
    assert shown.uncovered(["abc", "생성 파일|README.md|수정"], ["xabcx\n| 생성 파일 | README.md | 수정 |"]) == ["abc"]


def test_parse_events_stream_json_and_transcript_formats():
    stream = [{"type": "user", "message": {"content": [{"type": "text", "text": "요청"}]}},
              {"type": "assistant", "message": {"content": [{"type": "text", "text": "a"},
                                                            {"type": "tool_use", "id": "t1", "name": "Bash",
                                                             "input": {"command": "ls"}}]}},
              {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                                        "content": [{"type": "text", "text": "out"}], "is_error": True}]}},
              {"type": "assistant", "parent_tool_use_id": "x", "message": {"content": [{"type": "text", "text": "sub"}]}}]
    seq = shown.parse_events([json.dumps(e) for e in stream])
    assert [e["kind"] for e in seq] == ["text", "tool"] and seq[1]["result"] == "out" and seq[1]["error"] is True
    assert shown.parse_events(stream, include_user=True)[0] == {"kind": "user", "text": "요청", "meta": False,
                                                                 "feedback": False}
    transcript = [{"type": "user", "message": {"role": "user", "content": "분석해줘"}},
                  {"type": "attachment", "attachment": {}}, {"type": "system", "content": "x"},
                  {"type": "assistant", "message": {"content": [{"type": "text", "text": "a"}]}},
                  {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                                                 "input": {"command": "ls"}}]}},
                  {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "o"}]}},
                  {"type": "user", "isMeta": True, "message": {"content": "Stop hook feedback:\n[telephony-triage] x"}},
                  {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "sub"}]}},
                  "not json"]
    seq = shown.parse_events([json.dumps(e) if isinstance(e, dict) else e for e in transcript], include_user=True)
    assert [e["kind"] for e in seq] == ["user", "text", "tool", "user"]
    assert seq[0]["feedback"] is False and seq[3]["feedback"] is True and seq[3]["meta"] is True
    assert seq[2]["result"] == "o"


def test_ask_text_mock_and_ask_user_question():
    assert shown.ask_text({"question": "승인할까요?", "options": ["예"]}) == "승인할까요?"
    q = {"questions": [{"header": "확인", "question": "승인할까요?", "multiSelect": False,
                        "options": [{"label": "승인", "description": "push한다"}, {"label": "취소"}]}]}
    assert shown.ask_text(q).splitlines() == ["확인", "승인할까요?", "승인", "push한다", "취소"]
    assert shown.ask_text({"prompt": "뭐?"}) == "뭐?"            # 모르는 모양: 문자열 값
    assert shown.is_ask("AskUserQuestion") and shown.is_ask(ASK) and not shown.is_ask("mcp__x__ask")


def test_denied_asks_are_not_visible_or_asked():
    deny = "PreToolUse:" + ASK + " hook error: " + shown.MARKER + " push:abc1234def — …"
    seq = [bash("s", STAGE_CMD, SCREEN), tool("q1", ASK, {"question": SCREEN + "\n승인할까요?"}, deny, True),
           tool("q2", ASK, {"question": "승인할까요?"}, "예")]
    assert shown.denied(seq[1]) and not shown.denied(seq[2])
    assert shown.visible_between(seq, 1) == ["승인할까요?"]
    w = shown.screens(seq, "push")[0]
    assert w["asked"] == 2 and w["missing"]                      # 거부된 질문의 화면은 보인 것이 아니다
    assert shown.guard_counts([]) == {"blocks": 0, "denies": 0, "capped": 0}


def test_obligations_from_synthetic_seq():
    seq = [bash("t", TRIAGE_CMD, "{}"), bash("r", "cat /w/MOCK-1/report.md", REPORT),
           text(REPORT), tool("q7", ASK, {"question": "기록할까요?", "options": ["DATA-001-01", "새 원인", "기록하지 않음"]}),
           bash("d", DRAFT_CMD, json.dumps({"rules": RULES})), bash("s", STAGE_CMD, SCREEN), text("승인할까요?")]
    obs = {ob.kind: ob for ob in shown.obligations(seq)}
    assert set(obs) == {"push", "report", "draft"}
    rep = obs["report"]
    assert (rep.start, rep.end, rep.close_kind, rep.key) == (0, 4, "step7", "report:t")
    assert shown.missing(rep, shown.visible_between(seq, rep.start + 1, rep.end)) == []
    assert obs["draft"].close_kind == "stage" and obs["draft"].total == 3
    assert obs["push"].open and obs["push"].key == "push:abc1234def"
    assert len(shown.missing(obs["push"], shown.visible_between(seq, obs["push"].start + 1))) == 6


def test_report_obligation_reads_job_files(tmp_path):
    job = tmp_path / "MOCK-1"
    job.mkdir()
    (job / "report.md").write_text(REPORT, encoding="utf-8")
    (job / "analysis.json").write_text(json.dumps({"must_show": [MUST]}, ensure_ascii=False), encoding="utf-8")
    seq = [bash("t", TRIAGE_CMD, "{}"), text(REPORT)]
    def read(p):
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    (rep,) = shown.obligations(seq, read, job)
    assert rep.must_show == [MUST] and rep.open and rep.path.endswith("report.md")
    assert shown.missing(rep, [REPORT]) == [MUST]
    assert shown.missing(rep, [REPORT, MUST]) == []
    assert shown.obligations(seq) == []                           # 리포트 원문을 못 찾으면 의무도 없다


def test_draft_rows_missing_rejects_grouped_and_wrong_marks():
    table = ["| R1 | ✅ 통과 | 대상 1개 통과 |", "| R3 | ❌ 실패 | C=1 — R4 fixture |", "| R5 | 건너뜀 | 해당 없음 |"]
    assert shown.draft_rows_missing(RULES, shown.visible_lines(table)) == []
    assert shown.draft_rows_missing(RULES, shown.visible_lines(["R1~R4 통과, R5 건너뜀"])) == [
        "R1(pass)", "R3(fail: C=1 — R4 fixture)", "R5(skipped: 해당 없음)"]
    assert shown.draft_rows_missing(RULES, shown.visible_lines(["R1 R2 R3 R4 통과"])) != []
    bad = [table[0], table[1].replace("❌", "✅"), table[2]]
    assert shown.draft_rows_missing(RULES, shown.visible_lines(bad)) == ["R3(fail: C=1 — R4 fixture)"]


def test_command_recognition_and_approval_window():
    assert shown.PUSH_END.search(shown.command_of({"input": {"command": PUBLISH_CMD}})).group(1) == "publish"
    assert not shown.PUSH_END.search(shown.command_of({"input": {"command": 'grep -n "db_pr.py publish" a.md'}}))
    seq = [bash("s", STAGE_CMD, SCREEN), tool("q", ASK, {"question": SCREEN + "\n승인할까요?"}, "예"), bash("p", PUBLISH_CMD, "ok")]
    (w,) = shown.screens(seq, "push")
    assert (w["end_kind"], w["approved_arg"], shown.digest_of(w), w["missing"]) == ("publish", "abc1234def", "abc1234def", [])
