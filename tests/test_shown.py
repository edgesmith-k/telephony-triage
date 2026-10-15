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


def test_draft_doc_text_colon_and_per_row_json():
    # 요약 줄 `R4 fail: 사유`의 `:`는 사유가 아니다 (h1-b eval 42)
    assert shown.draft_doc("R4 fail: 기대값이 깨진 fixture 1개\nR5 skipped 해당 없음")["rules"] == [
        {"id": "R4", "status": "fail", "reason": "기대값이 깨진 fixture 1개"},
        {"id": "R5", "status": "skipped", "reason": "해당 없음"}]
    # 규칙 행을 하나씩 찍은 JSON(줄 첫머리 `{`)은 JSON으로 읽는다. 뒤의 python dict 줄은 건너뛴다
    rows = "\n".join(json.dumps(r, ensure_ascii=False, indent=1) for r in RULES[1:]) + "\n{'scope': 'plan:draft'}"
    assert shown.draft_json(rows) == {"rules": RULES[1:]}
    # 잘린 결과(`| head`) 안의 들여쓴 규칙 행은 JSON 행으로 읽지 않고, 요약 줄로 읽는다
    cut = "R3 fail: C=1 — R4 fixture\n" + json.dumps({"rules": RULES}, ensure_ascii=False, indent=1)[:-40]
    assert shown.draft_json(cut) is None
    assert shown.draft_doc(cut)["rules"] == [{"id": "R3", "status": "fail", "reason": "C=1 — R4 fixture"}]


def test_draft_window_first_fail_prefers_json_rerun():
    """잘린 첫 결과(요약 줄만)보다 같은 계획을 다시 돌려 JSON으로 읽은 결과의 창을 본다 (h1-b eval 42)."""
    cut = "R3 fail: C=1 — R4 fixture\n" + json.dumps({"rules": RULES}, ensure_ascii=False, indent=1)[:-40]
    rerun = "\n".join(json.dumps(r, ensure_ascii=False, indent=1) for r in RULES[1:])
    seq = [bash("d1", DRAFT_CMD + " | head -60", cut), bash("d2", DRAFT_CMD + " | python3 -c ''", rerun),
           tool("q", ASK, {"question": "| R3 | 실패 | C=1 — R4 fixture |\n| R5 | 건너뜀 | 해당 없음 |"}),
           bash("s", STAGE_CMD, SCREEN)]
    w = shown.draft_window(seq, "first_fail")
    assert (w["i"], w["end"], [r["id"] for r in w["rules"]]) == (1, 3, ["R3", "R5"])
    assert shown.draft_rows_missing(w["rules"], shown.visible_lines(shown.visible_between(seq, w["i"] + 1, w["end"]))) == []
    assert shown.draft_window(seq[:1] + seq[2:], "first_fail")["i"] == 0       # JSON 결과가 없으면 요약 줄 결과
    # 같은 계획을 다시 돌렸지만 결과를 못 읽은 호출은 창을 끊지 않는다(그 뒤 보인 표까지 본다, sm4-1-b eval 42)
    unread = bash("d2", DRAFT_CMD.replace("/w/", "$W/") + " | sed -n 80,200p", '    "id": "R5",\n    "status": "skipped",')
    w = shown.draft_window([seq[0], unread, *seq[2:]], "first_fail")
    assert (w["i"], w["end"]) == (0, 3)
    other = bash("d2", DRAFT_CMD.replace("MOCK-1", "MOCK-2") + " | sed -n 80,200p", "")
    # 실패 결과는 다른 계획의 draft로 끊지 않는다(h3-d eval 18) — 작업 경계(lock acquire)가 있으면 끊는다
    assert shown.draft_window([seq[0], other, *seq[2:]], "first_fail")["end"] == 3
    lock = bash("l", "python3 /p/scripts/db_pr.py lock acquire MOCK-2 --command record --json", "{}")
    assert shown.draft_window([seq[0], lock, other, *seq[2:]], "first_fail")["end"] == 1
    # hook 표시 의무도 같은 창 끝을 쓴다
    (ob,) = [o for o in shown.obligations([seq[0], unread, *seq[2:]]) if o.kind == "draft"]
    assert (ob.start, ob.end, ob.close_kind) == (0, 3, "stage")


def test_draft_window_does_not_skip_rerun_that_may_differ():
    """못 읽은 재실행이라도 결과가 다를 수 있으면(fail 글, 그사이 계획 수정) 창을 끊는다."""
    passing = [dict(r, status="pass") for r in RULES]
    table = "\n".join(f"| {r['id']} | 통과 | {r['reason']} |" for r in passing)
    first = bash("d1", DRAFT_CMD, json.dumps({"rules": passing}, ensure_ascii=False, indent=1))
    ask, stage = tool("q", ASK, {"question": table}), bash("s", STAGE_CMD, SCREEN)
    fail_rows = bash("d2", DRAFT_CMD + " | sed -n 2,20p", '  {\n   "id": "R3",\n   "status": "fail",')
    assert shown.draft_window([first, fail_rows, ask, stage])["end"] == 1
    silent = bash("d2", DRAFT_CMD + " | sed -n 2,4p", '  {\n   "id": "R1",')
    assert shown.draft_window([first, silent, ask, stage])["end"] == 3
    edit = tool("e", "Edit", {"file_path": "/w/MOCK-1/plan.json"}, "ok")
    assert shown.draft_window([first, edit, silent, ask, stage])["end"] == 2           # 그사이 계획을 고쳤다
    edit_in_cmd = bash("d2", "python3 - <<'E'\nopen('/w/MOCK-1/plan.json','w')\nE\n" + DRAFT_CMD + " | sed -n 2,4p",
                       '  {\n   "id": "R1",')
    assert shown.draft_window([first, edit_in_cmd, ask, stage])["end"] == 1            # 같은 명령 안에서 고쳤다


def test_draft_window_first_fail_keeps_plan_and_rule_coverage():
    """요약 줄 fail 결과를 다른 계획의 JSON 결과나 일부 행만 고른 출력으로 바꾸지 않는다."""
    text_fail = bash("d1", DRAFT_CMD + " | head -3", "R3 fail: C=1 — R4 fixture\nR5 skipped 해당 없음")
    other = bash("d2", DRAFT_CMD.replace("MOCK-1", "MOCK-2"), json.dumps({"rules": RULES}, ensure_ascii=False))
    assert shown.draft_window([text_fail, other], "first_fail")["i"] == 0
    subset = bash("d2", DRAFT_CMD + " | jq '.rules[] | select(.status==\"fail\")'",
                  json.dumps(RULES[1], ensure_ascii=False, indent=1))
    assert shown.draft_window([text_fail, subset], "first_fail")["i"] == 0             # R5를 덮지 않는다
    full = bash("d2", DRAFT_CMD, json.dumps({"rules": RULES}, ensure_ascii=False))
    assert shown.draft_window([text_fail, full], "first_fail")["i"] == 1


def test_draft_command_with_global_db_option():
    """하위 명령 앞 전역 옵션 `--db X`도 건너뛴다 (h1-a eval 3: `db_verify.py --db X rules --plan … --draft …`)."""
    cmd = "python3 $S/db_verify.py --db /w/_snapshot rules --plan /w/MOCK-1/plan.json --draft /w/MOCK-1/draft"
    assert shown.DRAFT.search(shown.command_of({"input": {"command": cmd}}))
    seq = [bash("d", cmd, json.dumps({"rules": RULES}))]
    assert shown.bash_index(seq, shown.DRAFT) == [0]
    assert [ob.kind for ob in shown.obligations(seq)] == ["draft"]          # show_guard 표시 의무도 생긴다


def test_command_recognition_and_approval_window():
    assert shown.PUSH_END.search(shown.command_of({"input": {"command": PUBLISH_CMD}})).group(1) == "publish"
    assert not shown.PUSH_END.search(shown.command_of({"input": {"command": 'grep -n "db_pr.py publish" a.md'}}))
    seq = [bash("s", STAGE_CMD, SCREEN), tool("q", ASK, {"question": SCREEN + "\n승인할까요?"}, "예"), bash("p", PUBLISH_CMD, "ok")]
    (w,) = shown.screens(seq, "push")
    assert (w["end_kind"], w["approved_arg"], shown.digest_of(w), w["missing"]) == ("publish", "abc1234def", "abc1234def", [])


def test_command_through_braced_variable_prefix():
    """E67: `S="python3 /…/scripts/"; ${S}db_pr.py publish …`도 publish 호출이다(경로가 `}`로 끝남). 인자 자리는 아니다."""
    def end(cmd):
        m = shown.PUSH_END.search(shown.command_of({"input": {"command": cmd}}))
        return m and m.group(1)
    assert end('S="python3 /p/scripts/"; ${S}db_pr.py publish /w/MOCK-1/wt --approved abc1234def --commit') == "publish"
    assert end("python3 ${S}db_pr.py publish /w/MOCK-1/wt --approved abc1234def") == "publish"
    assert end("${S}db_pr.py discard /w/MOCK-1/wt") == "discard"
    assert not end("echo ${S}db_pr.py publish /w/MOCK-1/wt")
    assert shown.STAGE.search(shown.command_of({"input": {"command": "${S}db_pr.py stage /w/MOCK-1/plan.json"}}))


def test_denied_accepts_pretooluse_content_and_not_run_skips_calls():
    hook_text = "PreToolUse:Bash hook error: " + shown.MARKER + " draft:x — …"
    assert shown.denied(tool("a", "Bash", {}, hook_text, False))       # 오류 표시가 없어도 거부 문구면 거부
    assert not shown.denied(tool("b", "Bash", {}, shown.MARKER + " 인용", False))
    guard = tool("g", "Bash", {"command": STAGE_CMD}, "PreToolUse:Bash hook error: 이 플러그인은 …", True)
    assert shown.not_run(guard) and not shown.denied(guard)
    seq = [bash("s", STAGE_CMD, SCREEN), tool("p", "Bash", {"command": PUBLISH_CMD}, hook_text, True)]
    assert shown.bash_index(seq, shown.PUSH_END) == [] and shown.screens(seq, "push")[0]["end_kind"] == "end"


def test_report_uncovered_relaxes_refs_and_backticks_unless_clock_evidence():
    core = ["- 근거 로그 (마스킹, 슬롯 phone 0):",
            "  - 2026-09-20T05:30:03.000Z DSMGR-0 notifyDataEnabledChanged: enabled=false (f0:L2, f1:L7)"]
    shown_text = "- 근거 로그 (마스킹, 슬롯 phone 0):\n  - 2026-09-20T05:30:03.000Z DSMGR-0 `notifyDataEnabledChanged: enabled=false`"
    assert shown.report_uncovered(core, [shown_text]) == []
    assert shown.report_uncovered(core, [shown_text.replace("enabled=false", "꺼짐")]) == [core[1]]
    assert shown.report_uncovered(core, [shown_text.replace("- 근거 로그 (마스킹, 슬롯 phone 0):\n", "")]) == [core[0]]  # 머리 줄은 그대로
    clock = ["시계 이상 구간의 근거: 1위의 순서·시간창 판정은 시각 재정렬 기준"]
    assert shown.report_uncovered(core, [shown_text], clock) == [core[1]]          # 시계 이상 근거면 참조까지 본다
    ob = shown.Obligation("report", "report:x", 0, 1, "end", lines=core, must_show=[])
    assert shown.missing(ob, [shown_text]) == []


def test_plan_tag_anchors_at_draft_call():
    """`--plan`은 db_verify rules 호출부터 찾는다: 앞 `&&` 명령이나 echo 글 안의 `--plan`은 태그가 아니다."""
    def tag(cmd):
        return shown.plan_tag({"input": {"command": cmd}})
    assert tag(DRAFT_CMD) == "MOCK-1/plan.json"
    assert tag("python3 /p/x.py check --plan /w/OTHER/plan.json && " + DRAFT_CMD) == "MOCK-1/plan.json"
    assert tag('echo "다시 --plan /w/OTHER/plan.json 로" && ' + DRAFT_CMD) == "MOCK-1/plan.json"
    assert tag(DRAFT_CMD + ' && echo "--plan /w/OTHER/plan.json"') == "MOCK-1/plan.json"


def test_plan_touch_by_file_name_across_notations():
    """`--plan $J/plan.json`과 Edit `/w/MOCK-1/plan.json`처럼 표기가 달라도 같은 계획일 수 있다: 파일 이름으로 건드림을 본다."""
    passing = [dict(r, status="pass") for r in RULES]
    table = "\n".join(f"| {r['id']} | 통과 | {r['reason']} |" for r in passing)
    var_cmd = "python3 /p/scripts/db_verify.py rules --plan $J/plan.json --draft $J/draft --json"
    first = bash("d1", var_cmd, json.dumps({"rules": passing}, ensure_ascii=False))
    rerun = bash("d2", var_cmd + " > /tmp/o.json; echo done", "done")
    ask, stage = tool("q", ASK, {"question": table}), bash("s", STAGE_CMD, SCREEN)
    assert shown.draft_window([first, rerun, ask, stage])["end"] == 3                   # 고치지 않은 재실행: 끊지 않는다
    for path in ("/w/MOCK-1/plan.json", "/w//MOCK-1/./plan.json"):
        edit = tool("e", "Edit", {"file_path": path}, "ok")
        assert shown.draft_window([first, edit, rerun, ask, stage])["end"] == 2, path  # 다른 표기로 고쳤다: 끊는다
    other = tool("e", "Edit", {"file_path": "/w/MOCK-1/draft_plan.json.txt"}, "ok")
    assert shown.draft_window([first, other, rerun, ask, stage])["end"] == 4          # 다른 파일
    sed = bash("x", "sed -i 's/a/b/' /w/MOCK-1//plan.json", "")
    assert shown.draft_window([first, sed, rerun, ask, stage])["end"] == 2


def test_own_rerun_quoted_plan_with_spaces_is_not_a_touch():
    passing = [dict(r, status="pass") for r in RULES]
    cmd = "python3 /p/scripts/db_verify.py rules --plan \"/my work/MOCK-1/plan.json\" --draft /w/MOCK-1/draft --json"
    first = bash("d1", cmd, json.dumps({"rules": passing}, ensure_ascii=False))
    rerun = bash("d2", cmd + " | sed -n 2,4p", '  {\n   "id": "R1",')
    stage = bash("s", STAGE_CMD, SCREEN)
    assert shown.draft_window([first, rerun, stage])["end"] == 2                         # 자기 --plan 인자는 건드림이 아니다


def test_not_pass_word_ignores_file_names():
    passing = [dict(r, status="pass") for r in RULES]
    first = bash("d1", DRAFT_CMD, json.dumps({"rules": passing}, ensure_ascii=False))
    stage = bash("s", STAGE_CMD, SCREEN)
    for out, end in (("fixtures/fail-case.log OK", 2), ("3 failed checks", 2), ('"status": "fail"', 1), ("요약 — fail 1건", 1),
                     ("| R4 | fail |", 1), ("NEEDS-APPROVAL", 1)):
        rerun = bash("d2", DRAFT_CMD + " | grep -v x", out)
        assert shown.draft_window([first, rerun, stage])["end"] == end, out


def test_draft_doc_row_print_with_review_required_tail():
    """행마다 `python3 -c`로 찍은 출력(`R6 skipped 해당 없음 review_required= False`, h1-b eval 4): 끝 값은 사유가 아니다."""
    out = "R1 pass 대상 2개 통과 review_required= False\nR2 skipped fixture 없음 review_required= True\nR6 skipped 해당 없음 False"
    rules = shown.draft_rules(out)
    assert [(r["reason"], r.get("review_required")) for r in rules] == [("대상 2개 통과", False), ("fixture 없음", True),
                                                                         ("해당 없음", None)]
    assert not shown.draft_all_clear(rules) and shown.draft_all_clear([rules[0], rules[2]])


# h3-d eval 18: 처음 시그니처의 실패 결과를 보이기 전에 좁힌 안을 다른 계획 파일로 돌려 통과했다
REL_DRAFT = "cd /w/MOCK-1; python3 /p/scripts/db_verify.py rules --plan {plan} --draft {draft} 2>&1 | head -80"
FAIL_SUMMARY = ("R3 fail: DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log\n"
                "R4 fail: 기대값이 깨진 fixture 5개\n{")
NARROW_PASS = json.dumps({"rules": [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
                                    {"id": "R3", "status": "pass", "reason": "대상 1개 통과"},
                                    {"id": "R4", "status": "pass", "reason": "전체 fixture 24개 기대값 유지"},
                                    {"id": "R5", "status": "skipped", "reason": "해당 없음"}]}, ensure_ascii=False)
FAIL_TABLE = ("| R3 | fail | DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log |\n"
              "| R4 | fail | 기대값이 깨진 fixture 5개 |")


def _h3d(*between):
    first = bash("d1", REL_DRAFT.format(plan="plan.json", draft="draft"), FAIL_SUMMARY)
    narrow = bash("d2", REL_DRAFT.format(plan="plan-narrow.json", draft="draft2"), NARROW_PASS)
    return [first, *between, narrow, tool("q", ASK, {"question": "fixture 6개에도 걸립니다(R3·R4 실패). 좁히기/허용?"}),
            bash("s", STAGE_CMD, SCREEN)]


def test_failed_draft_stays_open_past_other_plan():
    """전부 통과가 아닌 결과는 다른 계획(`plan-narrow.json`)의 draft로 닫히지 않는다: stage까지 열려 있다(h3-d eval 18)."""
    seq = _h3d()
    first, narrow = [o for o in shown.obligations(seq) if o.kind == "draft"]
    assert (first.start, first.end, first.close_kind) == (0, 3, "stage")
    assert (narrow.start, narrow.end, narrow.close_kind) == (1, 3, "stage")
    assert shown.missing(first, shown.visible_between(seq, 1, 3)) == [
        "R3(fail: DATA-001-03: C=1 (DATA-001-03/any) — dat)", "R4(fail: 기대값이 깨진 fixture 5개)"]
    w = shown.draft_window(seq, "first_fail")                       # 채점기도 같은 창
    assert (w["i"], w["end"]) == (0, 3)
    shown_seq = seq[:2] + [text(FAIL_TABLE)] + seq[2:]
    (ob,) = [o for o in shown.obligations(shown_seq) if o.kind == "draft" and o.start == 0]
    assert shown.missing(ob, shown.visible_between(shown_seq, 1, ob.end)) == []
    # 전부 통과한 결과는 지금처럼 다음 draft(다른 계획)로 닫힌다
    clear = [seq[1], bash("d3", REL_DRAFT.format(plan="plan.json", draft="draft"), FAIL_SUMMARY), seq[-1]]
    assert [(o.start, o.end, o.close_kind) for o in shown.obligations(clear) if o.kind == "draft"] == \
        [(0, 1, "draft"), (1, 2, "stage")]


def test_failed_draft_closes_on_same_plan_rerun_and_job_boundary():
    """같은 계획을 고쳐 다시 돌린 읽을 수 있는 결과는 앞 결과를 대신한다(지금과 같다). 작업 경계(triage run·discard·lock)도 닫는다."""
    first = bash("d1", REL_DRAFT.format(plan="plan.json", draft="draft"), FAIL_SUMMARY)
    edit = tool("e", "Edit", {"file_path": "/w/MOCK-1/plan.json"}, "ok")
    rerun = bash("d2", REL_DRAFT.format(plan="plan.json", draft="draft"), NARROW_PASS)
    ob = next(o for o in shown.obligations([first, edit, rerun, bash("s", STAGE_CMD, SCREEN)]) if o.kind == "draft")
    assert (ob.end, ob.close_kind) == (2, "draft")
    for cmd in (TRIAGE_CMD, "python3 /p/scripts/db_pr.py discard /w/MOCK-1/wt --json",
                "python3 /p/scripts/db_pr.py lock release MOCK-1 --json",
                "python3 /p/scripts/db_pr.py --platform android lock acquire MOCK-2 --command record"):
        seq = _h3d(bash("j", cmd, "{}"))
        ob = next(o for o in shown.obligations(seq) if o.kind == "draft")
        assert (ob.end, ob.close_kind) == (1, "job"), cmd
    # lock status는 경계가 아니다
    seq = _h3d(bash("j", "python3 /p/scripts/db_pr.py lock status --json", "{}"))
    assert next(o for o in shown.obligations(seq) if o.kind == "draft").close_kind == "stage"


def test_two_failed_plans_are_both_satisfiable():
    """다른 계획의 실패 결과 둘이 함께 열려 있어도 두 표를 보이면 둘 다 채워진다(같은 키 중복 의무 없음)."""
    other = FAIL_SUMMARY.replace("DATA-001-03/any", "DATA-001-03/narrow").replace("fixture 5개", "fixture 1개")
    seq = [bash("d1", REL_DRAFT.format(plan="plan.json", draft="draft"), FAIL_SUMMARY),
           bash("d2", REL_DRAFT.format(plan="plan-b.json", draft="draft2"), other),
           text(FAIL_TABLE + "\n" + FAIL_TABLE.replace("DATA-001-03/any", "DATA-001-03/narrow")
                .replace("fixture 5개", "fixture 1개")), bash("s", STAGE_CMD, SCREEN)]
    obs = [o for o in shown.obligations(seq) if o.kind == "draft"]
    assert len({o.key for o in obs}) == 2 and all(o.end == 3 for o in obs)
    assert all(shown.missing(o, shown.visible_between(seq, o.start + 1, o.end)) == [] for o in obs)


# h5-18b eval 18: 경로 목록이 든 R3 사유를 같은 계획 재실행에서 `[:150]`으로 잘라 찍고, 잘린 행만 보였다 — hook은 잘린 결과를
# 의무로 삼아 통과시켰고 채점기는 처음 결과로 실패시켰다. 덜 보인 사본은 앞 결과의 창을 닫지 않고 의무도 되지 않는다
LONG_R3 = "DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log, data/DATA-001-x/fixtures/DATA-001-02.log"
CUT_RERUN = ("R1 pass 대상 1개 통과\nR3 fail " + LONG_R3[:70] + "\nR4 fail 기대값이 깨진 fixture 5개\nR5 skipped 해당 없음\n"
             '{"id": "R4", "status": "fail", "reason": "기대값이')


def _cut_rerun(*between):
    first = bash("d1", REL_DRAFT.format(plan="plan.json", draft="draft"),
                 f"R3 fail: {LONG_R3}\nR4 fail: 기대값이 깨진 fixture 5개\n{{")
    rerun = bash("d2", REL_DRAFT.format(plan="plan.json", draft="draft") + " | python3 -c 'print(r[:150])'", CUT_RERUN)
    return [first, rerun, *between, bash("s", STAGE_CMD, SCREEN)]


def test_weaker_copy():
    full = [{"id": "R3", "status": "fail", "reason": LONG_R3}, {"id": "R4", "status": "fail", "reason": "x 5개"}]
    cut = [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"}, dict(full[0], reason=LONG_R3[:50] + "…"), full[1]]
    assert shown.weaker_copy(full, cut)                                      # 잘린 사유 + 접힌 통과 행
    assert shown.weaker_copy(full, [full[1]])                                # 규칙이 빠졌다
    assert shown.weaker_copy(full, [dict(full[0], reason=""), full[1]])      # 사유 없이 상태만
    assert not shown.weaker_copy(full, full)                                 # 같은 결과: 지금처럼 대신한다
    assert not shown.weaker_copy(full, [dict(full[0], reason=LONG_R3 + " 더"), full[1]])        # 다른 사유
    assert not shown.weaker_copy(full, [dict(full[0], status="pass", reason="")])              # 다른 상태
    assert not shown.weaker_copy(full, [full[0], {"id": "R2", "status": "fail", "reason": "y"}])   # 새 실패 행


def test_cut_rerun_keeps_first_result_obligation():
    seq = _cut_rerun()
    (ob,) = [o for o in shown.obligations(seq) if o.kind == "draft"]
    assert (ob.start, ob.end, ob.close_kind) == (0, 2, "stage")
    assert [r["reason"] for r in ob.rules if r["id"] == "R3"] == [LONG_R3]
    cut_table = "| R3 | fail | " + LONG_R3[:70] + " |\n| R4 | fail | 기대값이 깨진 fixture 5개 |"
    shown_cut = _cut_rerun(text(cut_table))
    (ob,) = [o for o in shown.obligations(shown_cut) if o.kind == "draft"]
    assert [m[:3] for m in shown.missing(ob, shown.visible_between(shown_cut, 1, ob.end))] == ["R3("]
    w = shown.draft_window(shown_cut, "first_fail")                     # 채점기도 같은 결과·창
    assert (w["i"], w["end"]) == (0, 3) and shown.draft_window(shown_cut)["i"] == 0
    full = _cut_rerun(text(FAIL_TABLE.replace("DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log",
                                              LONG_R3)))
    (ob,) = [o for o in shown.obligations(full) if o.kind == "draft"]
    assert shown.missing(ob, shown.visible_between(full, 1, ob.end)) == []
    # 계획을 고쳐 다시 돌렸으면 지금처럼 새 결과가 대신한다
    edit = tool("e", "Edit", {"file_path": "/w/MOCK-1/plan.json"}, "ok")
    seq = _cut_rerun()
    seq = [seq[0], edit, *seq[1:]]
    assert [(o.start, o.end) for o in shown.obligations(seq) if o.kind == "draft"] == [(0, 2), (2, 3)]


def test_draft_doc_reads_printed_table_rows():
    """모델이 결과를 `| R1 | pass | 사유 |`로 찍은 출력도 읽는다(h5-18b eval 18: 좁힌 계획의 통과 결과를 못 읽어 채점기가
    앞 실패 결과를 마지막 결과로 봤다)."""
    out = "| R1 | pass | 대상 1개 통과 |\n| R3 | fail | C=1 — x |\n| R5 | skipped | 해당 없음 |"
    assert shown.draft_doc(out)["rules"] == [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
                                              {"id": "R3", "status": "fail", "reason": "C=1 — x"},
                                              {"id": "R5", "status": "skipped", "reason": "해당 없음"}]
    assert shown.draft_doc("| 규칙 | 상태 |\n|---|---|") is None
