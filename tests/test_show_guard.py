"""표시 보조 hook show_guard.py (08-safety.md "표시 보조 hook", contracts.md §3.2).

실제 Claude Code transcript 형식(블록마다 한 항목, 사용자 입력은 문자열 content, tool_result는 user 항목, Stop 피드백은 isMeta)으로
만든 JSONL을 transcript_path로 주고 subprocess로 부른다. 항상 종료 0이고, 판정할 수 없으면 아무 결정도 내지 않는다(fail-open)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "plugin" / "scripts" / "show_guard.py"
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
from common import shown  # noqa: E402

ASK = "mcp__eval-approver__ask_user"
STAGE_CMD = "python3 /p/scripts/db_pr.py stage /w/MOCK-1/plan.json --then-summary"
PUBLISH_CMD = "python3 /p/scripts/db_pr.py publish /w/MOCK-1/wt --approved abc1234def --commit --and-discard"
DRAFT_CMD = "python3 /p/scripts/db_verify.py rules --plan /w/MOCK-1/plan.json --draft /w/MOCK-1/draft --json"
SCREEN = """## push 전 확인: MOCK-1 → DATA-001-01 Data disabled
구분: 분석 (analyze)
리뷰어: mock-org/telephony-data-owners

### 변경 파일

| 구분 | 파일 | 변경 |
|---|---|---|
| Jira 기록 | data/DATA-001-x/issues/MOCK-1.yaml | 신규 |
| 생성 파일 | README.md | 수정 |

### 주요 diff

```diff
+key: MOCK-1
+cause: DATA-001-01
```

approved_hash: abc1234def
"""
SUMMARY = "변경 파일 2개(Jira 기록·README), 검증 통과입니다."
REPORT = """## MOCK-1 분석

- 분류 후보: data > DATA-001 > DATA-001-01 Data disabled (규칙 일치 점수 1.0)
- 근거 로그 (마스킹, 슬롯 phone 0):
  - 2026-09-20T05:30:03.000Z DSMGR-0 notifyDataEnabledChanged: enabled=false (f0:L2)
  - 2026-09-20T05:30:04.900Z DNC-0 Data evaluation: Data disallowed reasons: DATA_DISABLED (f0:L6)
- 원인: TODO(LLM)
"""
MUST = "로그 범위: 2026-09-20T05:30:00.000Z ~ 2026-09-20T05:30:29.900Z (일부만 포함), 시계 이상 없음"
STEP7 = ["DATA-001-01로 기록", "다른 기존 원인", "새 원인", "기록하지 않음"]
# 전부 통과가 아닌 표(R2 `fixture 없음`): stage 전에 보여야 한다. 전부 통과한 표(DRAFT_CLEAR)는 push 확인 화면으로 갈음한다
DRAFT_OUT = json.dumps({"rules": [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
                                  {"id": "R2", "status": "skipped", "reason": "fixture 없음", "review_required": True},
                                  {"id": "R5", "status": "skipped", "reason": "해당 없음"}]}, ensure_ascii=False)
DRAFT_CLEAR = json.dumps({"rules": [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
                                    {"id": "R5", "status": "skipped", "reason": "해당 없음"}]}, ensure_ascii=False)


# --- transcript 만들기(실제 형식) -----------------------------------------------------------------------------

def prompt(text):
    return [{"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}},
            {"type": "last-prompt", "lastPrompt": text}]


def say(text):
    return [{"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}]


def call(tid, name, inp, result=None, error=False):
    rows = [{"type": "assistant", "isSidechain": False,
             "message": {"role": "assistant", "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}}]
    if result is not None:
        rows.append({"type": "user", "isSidechain": False, "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": result, "is_error": error}]}})
        rows.append({"type": "attachment", "attachment": {"type": "hook_success"}})
    return rows


def bash(tid, cmd, out):
    return call(tid, "Bash", {"command": cmd}, out)


def feedback(reason):
    return [{"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback:\n" + reason}}]


def write(tmp_path, *parts, name="t.jsonl") -> Path:
    rows = [{"type": "system", "subtype": "init"}, {"type": "ai-title", "title": "x"}]
    for p in parts:
        rows += p
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def hook(mode, event, script=SCRIPT) -> tuple[dict | None, str]:
    proc = subprocess.run([sys.executable, str(script), mode], input=event if isinstance(event, str) else json.dumps(event),
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    return (json.loads(proc.stdout) if proc.stdout.strip() else None), proc.stderr


def stop(path, last=None, active=False):
    event = {"hook_event_name": "Stop", "transcript_path": str(path), "stop_hook_active": active, "session_id": "s"}
    if last is not None:
        event["last_assistant_message"] = last
    return hook("stop", event)[0]


def pre(mode, path, name, inp, tid="now", record=True):
    """PreToolUse 입력. record면 실제처럼 지금 호출(tool_use)을 transcript 끝에 기록해 둔다(hook은 그것이 기록될 때까지
    기다린 뒤 판정한다 — transcript는 비동기로 쓰인다)."""
    path = Path(path)
    if record and tid and path.is_file() and tid not in path.read_text(encoding="utf-8"):
        copy = path.with_name(path.stem + f".{tid}.pre.jsonl")      # 원본은 그대로(뒤의 Stop 판정이 같은 파일을 쓴다)
        copy.write_text(path.read_text(encoding="utf-8") + json.dumps(call(tid, name, inp)[0], ensure_ascii=False) + "\n",
                        encoding="utf-8")
        path = copy
    return hook(mode, {"hook_event_name": "PreToolUse", "transcript_path": str(path), "tool_name": name,
                       "tool_input": inp, "tool_use_id": tid})[0]


def decision(out):
    return ((out or {}).get("hookSpecificOutput") or {}).get("permissionDecision")


# --- 판정하지 않는 경우 ---------------------------------------------------------------------------------------

def test_silent_and_fail_open(tmp_path):
    out, err = hook("stop", "not json")
    assert out is None and "JSON" in err
    out, err = hook("bogus", {})
    assert out is None and "모드" in err
    out, err = hook("stop", {"transcript_path": str(tmp_path / "missing.jsonl")})
    assert out is None and "transcript" in err
    assert hook("pre-ask", {"tool_name": ASK, "tool_input": {"question": "?"}})[0] is None    # transcript_path 없음
    plain = write(tmp_path, prompt("안녕"), say("안녕하세요"))                                 # 화면 흔적 없음: 바로 끝
    assert stop(plain, "안녕하세요") is None
    assert hook("post", {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_response": {"stdout": "a"}})[0] is None
    assert pre("pre-bash", plain, "Bash", {"command": "ls"}) is None


def test_import_failure_is_fail_open(tmp_path):
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(SCRIPT, lone / "show_guard.py")                      # common/ 없음 → import 실패
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY))
    out, err = hook("stop", {"transcript_path": str(path)}, script=lone / "show_guard.py")
    assert out == {"systemMessage": out["systemMessage"]} and "판정 못 함" in out["systemMessage"] and "import" in err
    out, err = hook("pre-ask", {"transcript_path": str(path), "tool_input": {"question": "?"}}, script=lone / "show_guard.py")
    assert out is None and "import" in err


# --- Stop -------------------------------------------------------------------------------------------------------

def test_stop_full_screen_passes_and_summary_blocks(tmp_path):
    path = write(tmp_path, prompt("MOCK-1 분석해줘"), bash("s", STAGE_CMD, SCREEN), say(SCREEN + "\n승인할까요?"))
    assert stop(path, SCREEN + "\n승인할까요?") is None
    path = write(tmp_path, prompt("MOCK-1 분석해줘"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY + " 승인할까요?"))
    out = stop(path, SUMMARY + " 승인할까요?")
    assert out["decision"] == "block"
    r = out["reason"]
    assert r.startswith(shown.MARKER + " push:abc1234def — 되돌림(오류 아님): push 확인 화면을 요약했다(빠진 줄 ")
    assert "생성 파일|README.md|수정" in r and "--- 붙일 화면 ---\n" + SCREEN.rstrip() in r
    # 한 줄만 빠져도 막는다
    partial = SCREEN.replace("| 생성 파일 | README.md | 수정 |\n", "")
    out = stop(write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(partial)), partial)
    assert out["decision"] == "block" and "빠진 줄 1/" in out["reason"]


def test_stop_cap_after_two_markers(tmp_path):
    key = shown.MARKER + " push:abc1234def — push 확인 화면을 요약했다"
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), feedback(key), say(SUMMARY),
                 feedback(key), say(SUMMARY))
    out = stop(path, SUMMARY, active=True)
    assert set(out) == {"systemMessage"} and shown.CAPPED in out["systemMessage"]
    one = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), feedback(key), say(SUMMARY), name="one.jsonl")
    assert stop(one, SUMMARY, active=True)["decision"] == "block"
    # 연이은 Stop인데 이번 턴에 표식이 없다(다른 hook이 막았거나 피드백이 기록 안 되는 버전): 셀 수 없으니 조용히 둔다
    bare = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), name="bare.jsonl")
    assert stop(bare, SUMMARY, active=True) is None


def test_stop_without_last_message_uses_transcript_text(tmp_path):
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SCREEN), say("승인할까요?"))
    assert stop(path) is None
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY))
    assert stop(path)["decision"] == "block"


def test_stop_ignores_closed_or_earlier_turn_screens(tmp_path):
    published = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), prompt("승인"),
                      bash("p", PUBLISH_CMD, "PR #1"), say("PR을 만들었습니다"))
    assert stop(published, "PR을 만들었습니다") is None
    later = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), prompt("잠깐, 질문 하나"),
                  say("네"), name="later.jsonl")
    assert stop(later, "네") is None                                   # 지난 턴의 화면은 그 턴에서 끝났다


def _job(tmp_path):
    job = tmp_path / "work" / "MOCK-1"
    job.mkdir(parents=True)
    (job / "report.md").write_text(REPORT, encoding="utf-8")
    (job / "analysis.json").write_text(json.dumps({"must_show": [MUST]}, ensure_ascii=False), encoding="utf-8")
    run = json.dumps({"status": "ok", "key": "MOCK-1", "files": {"report": str(job / "report.md")}, "must_show": [MUST]})
    return bash("t", "python3 /p/scripts/triage.py run MOCK-1 --logs logs/a.log", "EXIT 0\n" + run)


def test_stop_report_missing_evidence_or_must_show_blocks(tmp_path):
    run = _job(tmp_path)
    full = REPORT + "\n" + MUST + "\n어떻게 기록할까요?"
    assert stop(write(tmp_path, prompt("p"), run, say(full)), full) is None
    short = REPORT.replace("reasons: DATA_DISABLED", "reasons: 데이터 꺼짐") + "\n" + MUST
    noref = REPORT.replace(" (f0:L6)", "").replace("enabled=false", "`enabled=false`") + "\n" + MUST   # 줄 끝 참조·백틱은 봐준다
    assert stop(write(tmp_path, prompt("p"), run, say(noref), name="noref.jsonl"), noref) is None
    out = stop(write(tmp_path, prompt("p"), run, say(short)), short)
    assert out["decision"] == "block" and "분석 리포트를 요약했다(빠진 줄 1/5)" in out["reason"] and "must_show" in out["reason"]
    nomust = REPORT
    out = stop(write(tmp_path, prompt("p"), run, say(nomust)), nomust)
    assert out["decision"] == "block" and MUST in out["reason"]
    explore = "토큰이 추가로 듭니다. 탐색 분석을 할까요?"               # 리포트 전 질문(Step 5-2)은 막지 않는다
    assert stop(write(tmp_path, prompt("p"), run, say(explore)), explore) is None


# --- PreToolUse 질문 ---------------------------------------------------------------------------------------------

def test_pre_ask_allow_and_deny_shape(tmp_path):
    # 같은 응답의 앞 텍스트 블록은 PreToolUse 때 transcript에 이미 있다
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SCREEN), call("now", ASK, {"question": "승인할까요?"}))
    assert pre("pre-ask", path, ASK, {"question": "승인할까요?"}) is None
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN))
    assert pre("pre-ask", path, ASK, {"question": SCREEN + "\n승인할까요?"}) is None    # 질문 안에 화면 전체
    out = pre("pre-ask", path, "AskUserQuestion",
              {"questions": [{"question": SUMMARY + " 승인할까요?", "header": "push", "options": [{"label": "승인"}]}]})
    assert decision(out) == "deny" and out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert r.startswith(shown.MARKER + " push:abc1234def — 거부됨(오류·일시 장애 아님). 이 호출은 실행되지 않았다.")
    assert shown.MARKER_RE.findall(r) == ["push:abc1234def"]            # 표식+키는 첫 줄 맨 앞, 한 번
    lines = r.splitlines()
    assert lines[1].startswith("까닭: push 확인 화면을 요약했다(빠진 줄 ") and "이 거부 문구는 사용자에게 안 보인다" in lines[1]
    assert lines[2].startswith("할 일: ") and "질문 본문 앞(또는 질문 바로 앞 글)" in lines[2]
    assert "방금 거부된 것과 똑같은 호출" not in r


def test_pre_ask_report_only_for_step7(tmp_path):
    path = write(tmp_path, prompt("p"), _job(tmp_path))
    assert pre("pre-ask", path, ASK, {"question": "심층 분석을 실행할까요?"}) is None
    out = pre("pre-ask", path, ASK, {"question": "어떻게 기록할까요?", "options": STEP7})
    assert decision(out) == "deny" and "report:" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert pre("pre-ask", path, ASK, {"question": REPORT + MUST + "\n어떻게 기록할까요?", "options": STEP7}) is None


def test_pre_ask_draft_table(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT))
    out = pre("pre-ask", path, ASK, {"question": "초안 검증 R1~R5 통과. 진행할까요?"})
    assert decision(out) == "deny" and "규칙마다 한 행" in out["hookSpecificOutput"]["permissionDecisionReason"]
    table = "| R1 | 통과 | 대상 1개 통과 |\n| R2 | 건너뜀 | fixture 없음 |\n| R5 | 건너뜀 | 해당 없음 |\n진행할까요?"
    assert pre("pre-ask", path, ASK, {"question": table}) is None


# --- PreToolUse Bash(G3) ---------------------------------------------------------------------------------------

def test_pre_bash_publish_requires_screen_before_approval(tmp_path):
    shown_ok = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SCREEN + "\n승인할까요?"), prompt("승인"),
                     call("now", "Bash", {"command": PUBLISH_CMD}))
    assert pre("pre-bash", shown_ok, "Bash", {"command": PUBLISH_CMD}) is None
    summarized = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY + " 승인할까요?"), prompt("승인"),
                       say(SCREEN), name="sum.jsonl")                 # 승인 뒤에 보인 화면은 늦었다
    out = pre("pre-bash", summarized, "Bash", {"command": PUBLISH_CMD})
    assert decision(out) == "deny"
    assert "승인 질문 전에 확인 화면 전체를 보이지 않았다 — 화면을 다시 보이고 다시 승인받는다" in \
        out["hookSpecificOutput"]["permissionDecisionReason"]
    other = PUBLISH_CMD.replace("abc1234def", "0123456789")           # 그 해시의 화면이 도구 출력에 없다: 다시 내게 한다
    out = pre("pre-bash", summarized, "Bash", {"command": other})
    assert decision(out) == "deny" and "push:0123456789" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert pre("pre-bash", summarized, "Bash", {"command": 'grep -n "db_pr.py publish --approved abc1234def" a'}) is None
    braced = 'S="python3 /p/scripts/"; ${S}db_pr.py publish /w/MOCK-1/wt --approved abc1234def --commit'   # E67
    assert decision(pre("pre-bash", summarized, "Bash", {"command": braced})) == "deny"
    key = shown.MARKER + " push:abc1234def — 승인 질문 전에"
    capped = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), prompt("승인"),
                   call("x1", "Bash", {"command": PUBLISH_CMD}, key, True), say(SUMMARY),       # 글을 쓰고 다시 시도
                   call("x2", "Bash", {"command": PUBLISH_CMD}, key, True), name="cap.jsonl")
    out = pre("pre-bash", capped, "Bash", {"command": PUBLISH_CMD})
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]


def test_pre_bash_stage_after_unshown_draft(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증을 통과했습니다."))
    out = pre("pre-bash", path, "Bash", {"command": STAGE_CMD})
    assert decision(out) == "deny" and "초안 검증표를 보이지 않고 stage" in out["hookSpecificOutput"]["permissionDecisionReason"]
    ok = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("| R1 | pass | 대상 1개 통과 |\n| R2 | skipped | fixture 없음 |\n| R5 | skipped | 해당 없음 |"),
               name="ok.jsonl")
    assert pre("pre-bash", ok, "Bash", {"command": STAGE_CMD}) is None


# --- PostToolUse ----------------------------------------------------------------------------------------------

def test_post_reminds_full_output(tmp_path):
    out, _ = hook("post", {"tool_name": "Bash", "tool_input": {"command": STAGE_CMD},
                           "tool_response": {"stdout": "EXIT 0\n" + SCREEN, "stderr": "", "interrupted": False,
                                             "isImage": False, "noOutputExpected": False}})
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "PostToolUse" and "사용자에게 안 보인다" in ctx["additionalContext"]
    assert f"전문({len(shown.screen_lines(SCREEN))}줄)" in ctx["additionalContext"]
    assert shown.MARKER not in ctx["additionalContext"]               # 막은 횟수 표식과 섞이지 않는다
    out, _ = hook("post", {"tool_name": "Bash", "tool_input": {"command": DRAFT_CMD}, "tool_response": {"stdout": DRAFT_OUT}})
    assert "규칙마다 한 행(3행" in out["hookSpecificOutput"]["additionalContext"]
    run = _job(tmp_path)[1]["message"]["content"][0]["content"]
    out, _ = hook("post", {"tool_name": "Bash", "tool_input": {"command": "python3 /p/scripts/triage.py run MOCK-1"},
                           "tool_response": {"stdout": run}})
    assert "결정적 줄과 must_show(5줄)" in out["hookSpecificOutput"]["additionalContext"]


# --- 성능 -------------------------------------------------------------------------------------------------------

def test_large_transcript_is_fast(tmp_path):
    filler = "x" * 4000
    parts = [prompt("p")]
    for i in range(5200):                                              # 약 21MB
        parts.append(bash(f"f{i}", f"echo {i}", filler))
    path = write(tmp_path, *parts, prompt("올려줘"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY))
    assert path.stat().st_size > 20 * 1024 * 1024
    t0 = time.time()
    out = stop(path, SUMMARY)
    assert out["decision"] == "block"
    assert time.time() - t0 < 15
    # 끝 16MB 안에 사용자 입력이 없다: 이번 턴의 시작을 모르므로 판정하지 않는다
    blind = write(tmp_path, *parts, bash("s", STAGE_CMD, SCREEN), say(SUMMARY), name="blind.jsonl")
    assert stop(blind, SUMMARY) is None


@pytest.mark.parametrize("mode", ["stop", "pre-ask", "pre-bash", "post"])
def test_every_mode_exits_zero_on_garbage(mode, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"\xff\xfe garbage\n{\"type\": \"assistant\", \"message\": 5}\n" + "## push 전 확인:".encode())
    out, _ = hook(mode, {"transcript_path": str(bad), "tool_name": "Bash", "tool_input": {"command": PUBLISH_CMD},
                         "tool_response": 7})
    assert out is None


# --- 리뷰 반영: 거부된 호출·문서 열람·인코딩·dry-run -------------------------------------------------------------

def _denied(tid, cmd, reason):
    return call(tid, "Bash", {"command": cmd}, "PreToolUse:Bash hook error: " + reason, True)


def test_denied_stage_or_publish_does_not_close_window(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."))
    out = pre("pre-bash", path, "Bash", {"command": STAGE_CMD})
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    retry = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."), _denied("s1", STAGE_CMD, reason),
                  name="retry.jsonl")
    assert decision(pre("pre-bash", retry, "Bash", {"command": STAGE_CMD})) == "deny"    # 다시 시도해도 창은 열려 있다
    assert stop(retry, "초안 검증 통과.")["decision"] == "block"                        # Stop도 계속 본다
    pub = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY),
                _denied("p1", PUBLISH_CMD, shown.MARKER + " push:abc1234def — 승인 질문 전에 …\n--- 붙일 화면 ---\n" + SCREEN),
                say(SUMMARY), name="pub.jsonl")
    assert stop(pub, SUMMARY)["decision"] == "block"            # 거부된 publish는 창을 닫지 않고, 거부 문구 속 화면도 화면이 아니다


def test_reading_docs_or_fixtures_is_not_an_obligation(tmp_path):
    doc = write(tmp_path, prompt("설계 문서 보여줘"), bash("c", "cat docs/design/07-workflow.md", "예시:\n" + REPORT + MUST),
                say("문서 요약입니다."))
    assert stop(doc, "문서 요약입니다.") is None                    # triage run이 없으면 리포트 의무도 없다
    fx = write(tmp_path, prompt("fixture 봐줘"), bash("c", "cat tests/fixtures/render/checks-skipped.md", SCREEN),
               call("r", "Read", {"file_path": "/repo/tests/fixtures/render/a.md"}, SCREEN.replace("abc1234def", "fff1234def")),
               say("fixture 요약입니다."), name="fx.jsonl")
    assert stop(fx, "fixture 요약입니다.") is None                  # 화면을 낸 스크립트 호출이 아니다


def test_ascii_stdio_encoding(tmp_path):
    path = write(tmp_path, prompt("분석"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY))
    event = json.dumps({"transcript_path": str(path), "last_assistant_message": SUMMARY}, ensure_ascii=False)
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    proc = subprocess.run([sys.executable, str(SCRIPT), "stop"], input=event.encode("utf-8"), capture_output=True, env=env,
                          check=False)
    assert proc.returncode == 0
    proc.stdout.decode("ascii")                                         # ASCII만 쓴다
    assert json.loads(proc.stdout)["decision"] == "block"
    bad = subprocess.run([sys.executable, str(SCRIPT), "stop"], input=b"\xff\xfe{", capture_output=True, env=env, check=False)
    assert bad.returncode == 0 and bad.stdout == b""


def test_dry_run_stage_closes_draft_window_and_non_ask_tool(tmp_path):
    """dry-run 흐름의 `stage --dry-run`도 worktree를 만들고 확인 화면을 낸다(write-flow §3): 실제 stage와 같이 본다."""
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."))
    assert decision(pre("pre-bash", path, "Bash", {"command": STAGE_CMD.replace("--then-summary", "--dry-run")})) == "deny"
    dry = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), bash("s", STAGE_CMD + " --dry-run", "{}"),
                say("통과."), name="dry.jsonl")
    assert stop(dry, "통과.") is None                                    # 창은 stage로 닫혔다(그 결과는 pre-bash가 막는다)
    assert pre("pre-ask", path, "Bash", {"question": "진행할까요?"}) is None   # 질문 도구가 아니다


REL_DRAFT = "cd /w/MOCK-1; python3 /p/scripts/db_verify.py rules --plan {plan} --draft {draft} 2>&1 | head -80"
FAIL_SUMMARY = ("R3 fail: DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log\n"
                "R4 fail: 기대값이 깨진 fixture 5개\n{")
NARROW_PASS = json.dumps({"rules": [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
                                    {"id": "R3", "status": "pass", "reason": "대상 1개 통과"},
                                    {"id": "R5", "status": "skipped", "reason": "해당 없음"}]}, ensure_ascii=False)
FAIL_TABLE = ("| R3 | fail | DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log |\n"
              "| R4 | fail | 기대값이 깨진 fixture 5개 |")
NARROW_Q = {"question": "fixture 6개에도 걸립니다(R3·R4 실패). 좁힌 안은 통과합니다. 좁히기/허용?", "options": ["좁히기", "허용"]}


def _narrowed_first(*extra):
    """h3-d eval 18: 처음 시그니처(plan.json)의 실패 표를 보이기 전에 좁힌 안(plan-narrow.json)을 돌려 통과했다."""
    return (prompt("p"), bash("d1", REL_DRAFT.format(plan="plan.json", draft="draft"), FAIL_SUMMARY),
            bash("d2", REL_DRAFT.format(plan="plan-narrow.json", draft="draft2"), NARROW_PASS), *extra)


def test_failed_draft_before_other_plan_still_enforced(tmp_path):
    """실패 결과의 표시 의무는 다른 계획의 draft 호출로 닫히지 않는다: 질문·stage 모두 처음 실패 표를 요구한다."""
    path = write(tmp_path, *_narrowed_first())
    key = next(o for o in shown.obligations(shown.parse_events(path.read_text(encoding="utf-8").splitlines()))
               if o.kind == "draft").key
    out = pre("pre-ask", path, ASK, NARROW_Q)
    assert decision(out) == "deny"
    why = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert key in why and "DATA-001-03/any" in why                 # 붙일 표에 걸린 키·fixture가 든 사유 행
    assert pre("pre-ask", path, ASK, dict(NARROW_Q, question=FAIL_TABLE + "\n" + NARROW_Q["question"])) is None
    assert decision(pre("pre-bash", path, "Bash", {"command": STAGE_CMD})) == "deny"
    ok = write(tmp_path, *_narrowed_first(say(FAIL_TABLE)), name="ok.jsonl")
    assert pre("pre-bash", ok, "Bash", {"command": STAGE_CMD}) is None
    # 한도: 같은 키로 두 번 막았으면(사이에 글을 썼다) 더 막지 않고 안내만 한다
    deny = shown.MARKER + " " + key + " — 거부됨"
    capped = write(tmp_path, *_narrowed_first(call("a1", ASK, NARROW_Q, deny, True), say("다시 묻습니다."),
                                              call("a2", ASK, NARROW_Q, deny, True), say("다시.")), name="cap.jsonl")
    out = pre("pre-ask", capped, ASK, NARROW_Q)
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]


def test_report_follows_latest_analysis(tmp_path):
    run = _job(tmp_path)
    q7 = {"question": REPORT + MUST + "\n어떻게 기록할까요?", "options": STEP7}
    second = bash("t2", "python3 /p/scripts/triage.py run MOCK-1 --logs logs/b.log", run[1]["message"]["content"][0]["content"])
    path = write(tmp_path, prompt("p"), run, call("q", ASK, q7, "예"), prompt("다른 로그로 다시"), second, say("다시 분석했습니다."))
    out = stop(path, "다시 분석했습니다.")
    assert out["decision"] == "block" and "report:t2" in out["reason"]


def test_post_mentions_persisted_file():
    saved = "Output too large (40KB). Full output saved to: /tmp/x/tool-results/abc.txt\n\nPreview:\n" + SCREEN[:80]
    out, _ = hook("post", {"tool_name": "Bash", "tool_input": {"command": STAGE_CMD}, "tool_response": {"stdout": saved}})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "/tmp/x/tool-results/abc.txt" in ctx and "잘려" in ctx


def test_redirected_stage_output_read_back_is_a_screen(tmp_path):
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + ' > "$JOB/stage_out.md"; echo EXIT $?', "EXIT 0"),
                 call("r", "Read", {"file_path": "/w/MOCK-1/stage_out.md"}, SCREEN), say(SUMMARY))
    assert stop(path, SUMMARY)["decision"] == "block"


def test_publish_or_approve_of_screen_never_in_output(tmp_path):
    hidden = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + ' > "$JOB/stage_out.md"; echo EXIT $?', "EXIT 0"),
                   bash("h", 'grep approved_hash "$JOB/stage_out.md"', "approved_hash: abc1234def"), say("승인할까요?"),
                   prompt("승인"))
    out = pre("pre-bash", hidden, "Bash", {"command": PUBLISH_CMD})
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and r.startswith(shown.MARKER + " push:abc1234def")
    assert "`python3 /p/scripts/db_pr.py summary /w/MOCK-1/wt --format markdown`" in r
    again = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + " > /w/o.md", "EXIT 0"), prompt("승인"),
                  call("x", "Bash", {"command": PUBLISH_CMD}, "PreToolUse:Bash hook error: " + r, True), name="again.jsonl")
    out = pre("pre-bash", again, "Bash", {"command": PUBLISH_CMD})       # push는 화면이 나올 때까지 4번 막는다(K P1-2)
    assert decision(out) == "deny" and "다시 불러도 거부된다" in out["hookSpecificOutput"]["permissionDecisionReason"]
    nostage = write(tmp_path, prompt("승인해줘"), say("네"), name="nostage.jsonl")
    assert pre("pre-bash", nostage, "Bash", {"command": PUBLISH_CMD}) is None   # 화면을 낸 호출이 없다: 판정하지 않는다
    render = "python3 /p/scripts/issue_post.py render MOCK-1 --fill /w/MOCK-1/post.fill.json --json"
    approve = "python3 /p/scripts/issue_post.py approve MOCK-1 --sha " + "c" * 64
    post = write(tmp_path, prompt("p"), bash("r", render + " | tail -1", '"post_sha256": "' + "c" * 64 + '"'), prompt("게시"),
                 name="post.jsonl")
    out = pre("pre-bash", post, "Bash", {"command": approve})
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and "post:cccccccccccccccc" in r and "issue_post.py render MOCK-1 --fill" in r
    again = write(tmp_path, prompt("p"), bash("r", render + " | tail -1", '"post_sha256": "' + "c" * 64 + '"'), prompt("게시"),
                  _denied("x", approve, r), name="post-again.jsonl")
    out = pre("pre-bash", again, "Bash", {"command": approve})             # post는 한 번만 막는다(그대로)
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]


PUB_BRANCH = "python3 /p/scripts/db_pr.py publish /w/MOCK-1/wt --branch issue/MOCK-1 --lease new --approved {h} --commit --and-discard"


def test_publish_with_variable_approved_is_checked(tmp_path):
    """K P1-1: `--approved "$H"`·`$H`·`H=$(…)`처럼 해시가 변수여도 판정한다(마지막 화면, post의 변수 `--sha`와 같게)."""
    summarized = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY + " 승인할까요?"), prompt("승인"))
    full = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SCREEN + "\n승인할까요?"), prompt("승인"),
                 name="full.jsonl")
    for cmd in (PUB_BRANCH.format(h='"$H"'), PUB_BRANCH.format(h="$H"),
                "H=$(jq -r .approved_hash /w/MOCK-1/state.json); " + PUB_BRANCH.format(h='"$H"')):
        out = pre("pre-bash", summarized, "Bash", {"command": cmd})
        r = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert decision(out) == "deny" and r.startswith(shown.MARKER + " push:abc1234def"), cmd
        assert pre("pre-bash", full, "Bash", {"command": cmd}) is None, cmd


def test_publish_with_variable_approved_and_hidden_screen(tmp_path):
    """K P1-1: 화면을 숨기고(리디렉션) 해시도 변수면 push 대상 브랜치 키로 막고 summary로 화면을 다시 내게 한다."""
    hidden = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + " > /w/MOCK-1/screen.md", ""), say("stage 완료."))
    out = pre("pre-bash", hidden, "Bash", {"command": PUB_BRANCH.format(h='"$H"')})
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and r.startswith(shown.MARKER + " push:var:issue/MOCK-1 ")
    assert "db_pr.py summary /w/MOCK-1/wt --format markdown" in r
    out = pre("pre-bash", hidden, "Bash", {"command": PUB_BRANCH.format(h='"$H"').replace("issue/MOCK-1", "$B")})
    assert out["hookSpecificOutput"]["permissionDecisionReason"].startswith(shown.MARKER + " push:var:? ")


def test_unseen_publish_keeps_denying_until_screen_appears(tmp_path):
    """K P1-2: 화면이 어느 도구 출력에도 없던 publish는 다시 불러도 키마다 4번(`UNSEEN_BLOCKS`)까지 거부한다. 그 뒤는
    systemMessage만(큰 출력이 파일로 돌려져 화면이 끝내 안 나와도 막혀 버리지 않게 — fail-open, 최종 관문은 guard 규칙 7 ask).
    summary로 화면을 내고 전체를 보인 뒤 승인받으면 통과."""
    base = [prompt("p"), bash("s", STAGE_CMD + " > /w/MOCK-1/screen.md", ""), say("승인할까요?"), prompt("승인")]
    r = pre("pre-bash", write(tmp_path, *base), "Bash", {"command": PUBLISH_CMD})["hookSpecificOutput"]["permissionDecisionReason"]
    assert "다시 불러도 거부된다" not in r
    for n in (1, 2, 3):
        path = write(tmp_path, *base, *[_denied(f"x{k}", PUBLISH_CMD, r) for k in range(n)], name=f"n{n}.jsonl")
        out = pre("pre-bash", path, "Bash", {"command": PUBLISH_CMD})
        assert decision(out) == "deny" and "다시 불러도 거부된다(키마다 4번)" in out["hookSpecificOutput"]["permissionDecisionReason"], n
    capped = write(tmp_path, *base, *[_denied(f"x{k}", PUBLISH_CMD, r) for k in range(4)], name="n4.jsonl")
    out = pre("pre-bash", capped, "Bash", {"command": PUBLISH_CMD})       # 4번 거부한 뒤: 막지 않고 사용자 직접 확인 안내
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]
    summary = "python3 /p/scripts/db_pr.py summary /w/MOCK-1/wt --format markdown"
    ok = write(tmp_path, *base, *[_denied(f"x{k}", PUBLISH_CMD, r) for k in range(3)], bash("m", summary, SCREEN),
               say(SCREEN + "\n승인할까요?"), prompt("승인"), name="ok.jsonl")
    assert pre("pre-bash", ok, "Bash", {"command": PUBLISH_CMD}) is None


def test_chain_hidden_screen_variable_s_publish(tmp_path):
    """K repro_chain: `S="python3 …/"` + `${S}db_pr.py`로 화면을 숨기고 publish를 같은 호출로 다시 해도 두 번째도 거부한다."""
    s = 'S="python3 /p/scripts/"\n'
    stage = s + "${S}db_pr.py stage /w/MOCK-1/plan.json --wt /w/MOCK-1/wt --branch issue/MOCK-1 --then-summary > /w/MOCK-1/screen.md"
    pub = s + "${S}db_pr.py publish /w/MOCK-1/wt --branch issue/MOCK-1 --lease new --approved abc1234def --commit --and-discard --json"
    base = [prompt("MOCK-1 분석하고 push까지 해줘"), bash("s1", stage, ""), say("stage 완료. 올리겠습니다.")]
    out = pre("pre-bash", write(tmp_path, *base), "Bash", {"command": pub}, tid="x1")
    assert decision(out) == "deny"
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    out = pre("pre-bash", write(tmp_path, *base, _denied("x1", pub, r), name="2.jsonl"), "Bash", {"command": pub}, tid="x2")
    assert decision(out) == "deny" and "다시 불러도 거부된다" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_variable_approved_ignores_screen_before_hidden_restage(tmp_path):
    """K 2차 R4: 해시가 변수(`--approved "$H"`)면 마지막 stage·summary 호출 뒤 화면만 본다. 첫 화면을 다 보이고 승인받은 뒤
    고쳐 달라는 말에 다시 stage하면서 화면을 숨기면(리디렉션) 앞 화면으로 통과하지 않는다 — 화면 없음으로 막는다."""
    first = [prompt("p"), bash("s1", STAGE_CMD, SCREEN), say(SCREEN + "\n승인할까요?"), prompt("README 문구를 바꿔줘")]
    restage = STAGE_CMD + " > /w/MOCK-1/screen.md"
    hidden = write(tmp_path, *first, bash("s2", restage, ""), say("다시 stage했습니다. 승인할까요?"), prompt("승인"))
    out = pre("pre-bash", hidden, "Bash", {"command": PUB_BRANCH.format(h='"$H"')})
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and r.startswith(shown.MARKER + " push:var:issue/MOCK-1 ")
    screen2 = SCREEN.replace("abc1234def", "fed4321cba")
    shown2 = write(tmp_path, *first, bash("s2", STAGE_CMD, screen2), say(screen2 + "\n승인할까요?"), prompt("승인"),
                   name="shown2.jsonl")
    assert pre("pre-bash", shown2, "Bash", {"command": PUB_BRANCH.format(h='"$H"')}) is None



def test_variable_approved_after_summary_rerun_passes(tmp_path):
    """K 3차 P1-a: summary는 화면·해시를 바꾸지 않는다 — stage 화면 뒤 `summary --format markdown`으로 같은 해시 화면을 다시 내
    전체를 보이거나, `summary --format json`으로 해시를 읽고 변수로 publish해도 통과(기준은 마지막 stage)."""
    summary_md = "python3 /p/scripts/db_pr.py summary /w/MOCK-1/wt --format markdown"
    summary_json = "python3 /p/scripts/db_pr.py summary /w/MOCK-1/wt --format json"
    rerun = write(tmp_path, prompt("p"), bash("s1", STAGE_CMD, SCREEN), say("stage 완료."), bash("m", summary_md, SCREEN),
                  say(SCREEN + "\n승인할까요?"), prompt("승인"), name="rerun.jsonl")
    assert pre("pre-bash", rerun, "Bash", {"command": PUB_BRANCH.format(h='"$H"')}) is None
    as_json = write(tmp_path, prompt("p"), bash("s1", STAGE_CMD, SCREEN), say(SCREEN + "\n승인할까요?"), prompt("승인"),
                    bash("j", summary_json, '{"approved_hash": "abc1234def"}'), name="json.jsonl")
    assert pre("pre-bash", as_json, "Bash", {"command": PUB_BRANCH.format(h='"$H"')}) is None


def test_redirect_targets_and_read_back_rules(tmp_path):
    assert shown.redirect_targets('db_pr.py stage p > "$JOB/s.md" 2>&1') == {"name:s.md"}
    assert shown.redirect_targets("db_pr.py stage p &> /tmp/a/s.md") == {"/tmp/a/s.md"}
    assert shown.redirect_targets("db_pr.py stage p >/dev/null 2>/dev/null") == set()
    assert shown.redirect_targets("db_pr.py stage p 2> err.txt >> out/o.md") == {"name:o.md"}
    # 절대 경로로 쓴 파일: 같은 이름의 다른 경로(fixture)는 화면이 아니다
    other = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + " &> /w/MOCK-1/stage_out.md", "EXIT 0"),
                  call("r", "Read", {"file_path": "/repo/tests/fixtures/stage_out.md"}, SCREEN), say(SUMMARY))
    assert stop(other, SUMMARY) is None
    same = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + " &> /w/MOCK-1/stage_out.md", "EXIT 0"),
                 bash("c", "cat /w/MOCK-1/stage_out.md", SCREEN), say(SUMMARY), name="same.jsonl")
    assert stop(same, SUMMARY)["decision"] == "block"
    devnull = write(tmp_path, prompt("p"), bash("s", STAGE_CMD + " > /dev/null", "EXIT 0"),
                    bash("c", "cat /dev/null tests/fixtures/x.md", SCREEN), say(SUMMARY), name="dev.jsonl")
    assert stop(devnull, SUMMARY) is None


# --- 실제 eval 자식 transcript(모의 로그, 줄인 사본): 10/14 sm3에서 hook이 판정하지 못한 원인 회귀 ---------------------

REAL = REPO / "tests" / "fixtures" / "show_guard"


def test_real_child_transcript_format(tmp_path):
    """eval 2 자식 세션 transcript(plugin 모드, run.py가 세션을 남겨 옮긴 것)를 push 확인 화면 승인 질문 직전에서 자른 사본.
    블록마다 한 항목·hook attachment·Skill 주입 user 항목 그대로. 화면 전체를 담은 실제 질문은 통과, 요약하면 거부·Stop block."""
    path = tmp_path / "s.jsonl"
    shutil.copy(REAL / "eval2-session.jsonl", path)
    ask = json.loads((REAL / "eval2-ask.json").read_text(encoding="utf-8"))
    seq = shown.parse_events(path.read_text(encoding="utf-8").splitlines(), include_user=True)
    obs = {ob.kind: ob for ob in shown.obligations(seq)}
    assert set(obs) == {"push", "report", "draft"} and obs["push"].open
    assert obs["report"].close_kind == "step7" and obs["draft"].close_kind == "stage"
    assert pre("pre-ask", path, ASK, ask["tool_input"], ask["tool_use_id"]) is None
    out = pre("pre-ask", path, ASK, {"question": "변경 파일 5개, 검증 통과입니다. 승인할까요?"}, ask["tool_use_id"])
    assert decision(out) == "deny" and obs["push"].key in out["hookSpecificOutput"]["permissionDecisionReason"]
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(say("변경 파일 5개입니다. 승인할까요?")[0], ensure_ascii=False) + "\n")
    assert stop(path, "변경 파일 5개입니다. 승인할까요?")["decision"] == "block"
    # 세션을 남기지 않은 실행(--no-session-persistence): transcript 파일이 없다 → 판정 없음(fail-open, 경고만)
    out, err = hook("stop", {"transcript_path": str(tmp_path / "missing.jsonl"), "last_assistant_message": "승인할까요?"})
    assert out is None and "transcript" in err


def test_hook_replay_counts_without_content(tmp_path, monkeypatch):
    """M-3: tools/hook_replay.py가 기록된 세션의 결정 지점마다 guard·show_guard를 다시 판정하고 키·결정·빠진 줄 수만 낸다."""
    sys.path.insert(0, str(REPO / "tools"))
    import hook_replay
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path / "home"))     # 이 PC의 사용자 config에 기대지 않는다
    lines = (REAL / "eval2-session.jsonl").read_text(encoding="utf-8").splitlines()
    ask = json.loads((REAL / "eval2-ask.json").read_text(encoding="utf-8"))
    as_line = lambda inp: json.dumps(call(ask["tool_use_id"], ASK, inp)[0], ensure_ascii=False)  # noqa: E731
    out = hook_replay.replay([lines + [as_line({"question": "변경 파일 5개, 검증 통과입니다. 승인할까요?"})]])
    pts = out["points"]
    assert [sum(p["hook"] == h for p in pts) for h in ("guard", "pre-bash", "pre-ask")] == [25, 16, 7]
    last = pts[-1]
    assert (last["hook"], last["decision"], last["recorded"]) == ("pre-ask", "deny", None)
    assert last["keys"][0].startswith("push:") and last["missing"][0][0] > 0
    assert out["summary"]["mismatch"] == 2        # 기록상 guard 규칙 10 거부 2건: 원문 파일이 지금 없어 allow (한계)
    text = json.dumps(out, ensure_ascii=False)
    assert "MOCK-" not in text and "push 전 확인" not in text and "db_pr" not in text
    assert hook_replay.replay([lines + [as_line(ask["tool_input"])]])["points"][-1]["decision"] == "allow"
    stop_lines = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY)).read_text(encoding="utf-8").splitlines()
    end = [p for p in hook_replay.replay([stop_lines])["points"] if p["hook"] == "stop"]
    assert [(p["decision"], p["recorded"]) for p in end] == [("block", "ran")] and end[0]["keys"][0].startswith("push:")


# --- sm4 재측정 반영: transcript 비동기 기록, 초안 키, stage 거부 문구 ------------------------------------------------

def _late(path, delay, *rows):
    import threading

    def later():
        time.sleep(delay)
        with path.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    t = threading.Thread(target=later)
    t.start()
    return t


def test_waits_until_current_call_is_recorded(tmp_path):
    """sm4 거짓 거부 8건: 화면 전문을 쓴 텍스트 블록과 질문이 한 응답인데 PreToolUse 때 transcript에 텍스트가 아직 없었다.
    hook은 지금 호출(tool_use_id)이 기록될 때까지(상한 WAIT_SECONDS) 기다린다."""
    import show_guard
    ask = {"question": "승인할까요?"}
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN))
    t = _late(path, 0.5, say(SCREEN)[0], call("q1", ASK, ask)[0])
    t0 = time.time()
    out, err = hook("pre-ask", {"transcript_path": str(path), "tool_name": ASK, "tool_input": ask, "tool_use_id": "q1"})
    t.join()
    assert out is None and "기록되지 않아" not in err
    assert time.time() - t0 < show_guard.WAIT_SECONDS + 1.5
    # 늦게 기록된 글이 화면을 다 담지 않으면 여전히 거부한다
    short = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), name="short.jsonl")
    t = _late(short, 0.3, say(SUMMARY)[0], call("q2", ASK, ask)[0])
    out, err = hook("pre-ask", {"transcript_path": str(short), "tool_name": ASK, "tool_input": ask, "tool_use_id": "q2"})
    t.join()
    assert decision(out) == "deny" and "기록되지 않아" not in err


def test_never_recorded_or_missing_id(tmp_path, monkeypatch, capsys):
    import show_guard
    monkeypatch.setattr(show_guard, "WAIT_SECONDS", 0.3)
    ask = {"question": "승인할까요?"}
    lost = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY))
    t0 = time.time()
    out = show_guard.mode_pre_ask({"transcript_path": str(lost), "tool_name": ASK, "tool_input": ask, "tool_use_id": "zz"})
    assert out is None and "기록되지 않아" in capsys.readouterr().err and time.time() - t0 < 2   # 거부하지 않는다
    # tool_use_id가 없으면 기다리지 않고 바로 판정한다(이전 동작)
    out = show_guard.mode_pre_ask({"transcript_path": str(lost), "tool_name": ASK, "tool_input": ask})
    assert decision(out) == "deny" and "tool_use_id가 없어" in capsys.readouterr().err
    assert decision(pre("pre-ask", lost, ASK, ask, "zz")) == "deny"          # 기록되면 판정한다


def test_draft_key_count_is_per_job(tmp_path):
    """전부 통과한 초안 표는 작업이 달라도 결과가 같다: 앞 작업에서 낸 표식으로 뒤 작업이 한도에 걸리지 않는다."""
    cmd = "python3 /p/scripts/db_verify.py rules --plan $J/plan.json --draft $J/draft --json"
    key = shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d1", cmd, DRAFT_OUT)]))[0].key
    deny = shown.MARKER + " " + key + " — 초안 검증표를 요약했다"
    run2 = "python3 /p/scripts/triage.py run MOCK-2 --logs logs/b.log"
    path = write(tmp_path, prompt("p"), bash("d1", cmd, DRAFT_OUT), call("a1", ASK, {"question": "진행?"}, deny, True),
                 call("a2", ASK, {"question": "진행?"}, deny, True), bash("s1", STAGE_CMD, SCREEN), say(SCREEN),
                 prompt("다음 건 MOCK-2"), bash("t2", run2, "{}"), bash("d2", cmd, DRAFT_OUT))
    ob = [o for o in shown.obligations(shown.parse_events(path.read_text(encoding="utf-8").splitlines())) if o.start > 0][-1]
    assert ob.key == key
    assert decision(pre("pre-ask", path, ASK, {"question": "note를 승인할까요?"})) == "deny"     # 새 작업: 다시 막는다


def test_draft_rerun_with_same_result_shares_key_and_cap(tmp_path):
    out1 = shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d1", DRAFT_CMD, DRAFT_OUT)]))
    out2 = shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d2", DRAFT_CMD, DRAFT_OUT)]))
    assert out1[0].key == out2[0].key and out1[0].key.startswith("draft:")
    key = out1[0].key
    deny = shown.MARKER + " " + key + " — 초안 검증표를 요약했다"
    path = write(tmp_path, prompt("p"), bash("d1", DRAFT_CMD, DRAFT_OUT), call("a1", ASK, {"question": "진행?"}, deny, True),
                 say("초안 검증 통과."), call("a2", ASK, {"question": "진행?"}, deny, True), bash("d2", DRAFT_CMD, DRAFT_OUT))
    out = pre("pre-ask", path, ASK, {"question": "note를 승인할까요?"})
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]      # 다시 돌려도 한도는 그대로



def test_draft_key_ignores_plan_notation(tmp_path):
    """같은 계획 파일을 따옴표·변수·절대/상대 경로로 바꿔 써도 같은 키다: 표기만 바꿔 다시 돌려 한도를 새로 얻지 못한다."""
    def draft(plan):
        return f"python3 /p/scripts/db_verify.py rules --plan {plan} --draft /w/MOCK-9002/draft --json"

    def key(cmd):
        return shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d", cmd, DRAFT_OUT)]))[0].key

    plans = ["$W/MOCK-9002/plan.json", '"$W/MOCK-9002/plan.json"', "/abs/MOCK-9002/plan.json", "MOCK-9002/plan.json"]
    keys = {key(draft(p)) for p in plans}
    assert len(keys) == 1
    k = keys.pop()
    assert key(draft("/w/MOCK-2/plan.json")) != k                       # 다른 작업의 계획은 다른 키
    deny = shown.MARKER + " " + k + " — 초안 검증표를 요약했다"
    path = write(tmp_path, prompt("p"), bash("d1", draft(plans[0]), DRAFT_OUT), call("a1", ASK, {"question": "진행?"}, deny, True),
                 say("초안 검증 통과."), call("a2", ASK, {"question": "진행?"}, deny, True), bash("d2", draft(plans[1]), DRAFT_OUT))
    out = pre("pre-ask", path, ASK, {"question": "note를 승인할까요?"})
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]      # 표기를 바꿔 다시 돌려도 한도는 그대로


def test_post_render_key_is_per_issue(tmp_path):
    """`--sha`가 변수면 화면을 못 고른다: 키는 게시 대상별(`post:render:<KEY>`)이라 앞 이슈의 표식으로 뒤 이슈가 한도에 걸리지 않는다."""
    def render(k):
        return bash("r" + k, f"python3 /p/scripts/issue_post.py render {k} --fill /w/{k}/post.fill.json --json | tail -1",
                    '"post_sha256": "' + "c" * 64 + '"')

    def approve(k):
        return f'python3 /p/scripts/issue_post.py approve {k} --sha "$SHA" --json'

    one = write(tmp_path, prompt("p"), render("MOCK-1"), prompt("게시"))
    out = pre("pre-bash", one, "Bash", {"command": approve("MOCK-1")})
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and shown.MARKER + " post:render:MOCK-1" in r
    two = write(tmp_path, prompt("p"), render("MOCK-1"), prompt("게시"), _denied("x1", approve("MOCK-1"), r),
                prompt("다음 건"), render("MOCK-2"), prompt("게시"), name="two.jsonl")
    assert decision(pre("pre-bash", two, "Bash", {"command": approve("MOCK-2")})) == "deny"     # 다른 이슈: 다시 막는다
    out = pre("pre-bash", two, "Bash", {"command": approve("MOCK-1")}, tid="now1")
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]                     # 같은 이슈: 한 번만


def test_draft_tag_path_spellings():
    """`//`·`./`·공백 든 따옴표 경로·Windows 경로·뒤 셸 구분자도 같은 계획이면 같은 키다."""
    def key(plan):
        cmd = f"python3 /p/scripts/db_verify.py rules --draft /w/D/draft --json --plan {plan}"     # 뒤 구분자를 시험하게 끝에
        return shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d", cmd, DRAFT_OUT)]))[0].key

    base = key("/w/MOCK-9002/plan.json")
    for plan in ["/w//MOCK-9002//plan.json", "./MOCK-9002/./plan.json", '"/my work/MOCK-9002/plan.json"',
                 "'/my work/MOCK-9002/plan.json'", r"C:\w\MOCK-9002\plan.json", '"$W/MOCK-9002/plan.json");']:
        assert key(plan) == base, plan


def test_post_render_key_skips_flags_before_issue_key(tmp_path):
    """argparse는 KEY 앞의 옵션도 받는다: 키는 옵션을 건너뛴 첫 인자(뒤 셸 구분자는 벗김), 다시 낼 render 명령도 그 키다."""
    path = write(tmp_path, prompt("p"), bash("r", "python3 /p/scripts/issue_post.py render MOCK-1 --fill f.json --json | tail -1",
                                              '"post_sha256": "' + "c" * 64 + '"'), prompt("게시"))
    s = "python3 /p/scripts/issue_post.py approve "
    for cmd, want in [(s + '--sha "$SHA" MOCK-1', "MOCK-1"), (s + "--sha=$SHA MOCK-1", "MOCK-1"),
                      (s + '--json MOCK-2 --sha "$SHA"', "MOCK-2"), (s + '--platform android --sha "$SHA" MOCK-2', "MOCK-2"),
                      (s + 'MOCK-1 --sha "$SHA";', "MOCK-1"), ('(' + s + '--sha "$SHA" MOCK-2)', "MOCK-2")]:
        r = pre("pre-bash", path, "Bash", {"command": cmd})["hookSpecificOutput"]["permissionDecisionReason"]
        assert r.startswith(shown.MARKER + " post:render:" + want + " "), (cmd, r)
        assert f"issue_post.py render {want} --fill" in r, cmd
    r = pre("pre-bash", path, "Bash", {"command": s + '"$K" --sha "$SHA"'})["hookSpecificOutput"]["permissionDecisionReason"]
    assert r.startswith(shown.MARKER + " post:render ") and "render <KEY> --fill" in r      # 키도 변수: 고정 키

def test_stage_deny_does_not_invite_a_new_question(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."))
    r = pre("pre-bash", path, "Bash", {"command": STAGE_CMD})["hookSpecificOutput"]["permissionDecisionReason"]
    assert "같은 stage 명령을 다시 실행한다" in r and "새 질문을 만들지 않는다" in r
    lines = r.splitlines()
    assert lines[0].startswith(shown.MARKER + " draft:") and "거부됨(오류·일시 장애 아님)" in lines[0]
    assert lines[1].startswith("까닭: 초안 검증표를 보이지 않고 stage하려 했다(빠진 규칙 ")
    assert lines[2].startswith("할 일: 먼저 답(글)에 아래 표를 그대로 쓰고, 그 글 뒤에(같은 응답에서) 같은 stage 명령을")


# --- 보지 않고 다시 한 거부(10/14: 거부를 transcript 지연으로 읽고 `sleep 3` 뒤 같은 호출) --------------------------------

def _ask_deny(tid, question, reason):
    return call(tid, ASK, {"question": question}, "PreToolUse:" + ASK + " hook error: " + reason, True)


def test_blind_identical_retry_gets_one_more_deny(tmp_path):
    q = SUMMARY + " 승인할까요?"
    base = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN))
    r = pre("pre-ask", base, ASK, {"question": q})["hookSpecificOutput"]["permissionDecisionReason"]
    assert shown.MARKER + " push:abc1234def" in r and RETRY not in r
    two = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), _ask_deny("a1", q, r), _ask_deny("a2", q, r),
                name="two.jsonl")
    out = pre("pre-ask", two, ASK, {"question": q})                     # 세 번째 똑같은 질문: 한 번 더 막고 그렇다고 알린다
    assert decision(out) == "deny" and RETRY in out["hookSpecificOutput"]["permissionDecisionReason"]
    three = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), _ask_deny("a1", q, r), _ask_deny("a2", q, r),
                  _ask_deny("a3", q, r), name="three.jsonl")
    out = pre("pre-ask", three, ASK, {"question": q})                   # 네 번째: 한도(키마다 거부 최대 3번)
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]
    five = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), *[_ask_deny(f"a{k}", q, r) for k in range(5)],
                 name="five.jsonl")
    out = pre("pre-ask", five, ASK, {"question": q})                    # 몇 번을 되풀이해도 한 번만 덜 센다
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]


def test_retry_after_text_counts_but_tool_calls_in_between_do_not(tmp_path):
    q = SUMMARY + " 승인할까요?"
    r = pre("pre-ask", write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN)), ASK,
            {"question": q})["hookSpecificOutput"]["permissionDecisionReason"]
    said = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), _ask_deny("a1", q, r), say(SUMMARY),
                 _ask_deny("a2", q, r), name="said.jsonl")
    out = pre("pre-ask", said, ASK, {"question": q})                    # 사이에 글을 썼다: 보통대로 두 번에서 한도
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]
    slept = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), _ask_deny("a1", q, r), bash("z", "sleep 3", ""),
                  _ask_deny("a2", q, r), name="slept.jsonl")
    out = pre("pre-ask", slept, ASK, {"question": q})                   # `sleep 3`만 했다: 보지 않고 다시 한 것
    assert decision(out) == "deny" and RETRY in out["hookSpecificOutput"]["permissionDecisionReason"]
    other = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), _ask_deny("a1", q, r), _ask_deny("a2", "승인?", r),
                  name="other.jsonl")
    out = pre("pre-ask", other, ASK, {"question": q})                   # 질문을 바꿨다: 똑같은 호출이 아니다
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]


def test_blind_retry_ignores_description_and_marks_stage_retry(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."))
    r = pre("pre-bash", path, "Bash", {"command": STAGE_CMD})["hookSpecificOutput"]["permissionDecisionReason"]
    once = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."),
                 call("s1", "Bash", {"command": STAGE_CMD, "description": "stage"}, "PreToolUse:Bash hook error: " + r, True),
                 name="once.jsonl")
    out = pre("pre-bash", once, "Bash", {"command": STAGE_CMD, "description": "다시 stage"})
    assert decision(out) == "deny" and RETRY in out["hookSpecificOutput"]["permissionDecisionReason"]
    twice = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."),
                  _denied("s1", STAGE_CMD, r), _denied("s2", STAGE_CMD, r), name="twice.jsonl")
    assert decision(pre("pre-bash", twice, "Bash", {"command": STAGE_CMD})) == "deny"     # 세 번째까지 막는다


RETRY = "방금 거부된 것과 똑같은 호출이다"


# --- 전부 통과한 초안 표: push 확인 화면의 "검증 결과"로 갈음한다(10/14 사용자) ------------------------------------------

def test_all_clear_draft_needs_no_table_before_stage(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_CLEAR), say("초안 검증을 통과했습니다."))
    assert pre("pre-bash", path, "Bash", {"command": STAGE_CMD}) is None          # stage를 막지 않는다
    assert pre("pre-ask", path, ASK, {"question": "진행할까요?"}) is None           # 질문도 막지 않는다
    assert stop(path, "초안 검증을 통과했습니다.") is None
    out, _ = hook("post", {"tool_name": "Bash", "tool_input": {"command": DRAFT_CMD}, "tool_response": {"stdout": DRAFT_CLEAR}})
    assert out is None                                                             # 표를 붙이라는 안내도 없다
    # push 확인 화면은 그대로 본다: 승인 전에 화면(검증 결과 포함)을 보이지 않았으면 publish를 막는다
    pub = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_CLEAR), say("통과."), bash("s", STAGE_CMD, SCREEN),
                say(SUMMARY + " 승인할까요?"), prompt("승인"), name="pub.jsonl")
    assert decision(pre("pre-bash", pub, "Bash", {"command": PUBLISH_CMD})) == "deny"


def test_draft_all_clear_rule():
    ok = [{"id": "R1", "status": "pass"}, {"id": "R5", "status": "skipped", "reason": "해당 없음"}]
    assert shown.draft_all_clear(ok)
    assert not shown.draft_all_clear([])
    for bad in ({"id": "R4", "status": "fail", "reason": "다른 유형"},
                {"id": "R2", "status": "skipped", "reason": "fixture 없음"},
                {"id": "R3", "status": "skipped", "reason": "시그니처 없음(pending)"},
                {"id": "R5", "status": "needs-approval", "reason": "이벤트 변경"},
                {"id": "R1", "status": "pass", "review_required": True},
                {"id": "R4", "status": "pass", "allow_cause_drafts": [{"op": "allow-cause"}]}):
        assert not shown.draft_all_clear(ok + [bad]), bad


def test_cut_rerun_of_same_plan_does_not_shrink_obligation(tmp_path):
    """h5-18b eval 18: 같은 계획을 고치지 않고 다시 돌려 긴 R3 사유를 150자로 잘라 찍은 뒤 잘린 행을 질문에 넣었다 — 잘린
    결과가 의무를 대신해 통과됐다. 덜 보인 사본은 앞(전체) 결과의 의무를 닫지 않는다."""
    long_r3 = ("DATA-001-03: C=1 (DATA-001-03/any) — data/DATA-001-x/fixtures/DATA-001-01.log, "
               "data/DATA-001-x/fixtures/DATA-001-02.log")
    first = bash("d1", REL_DRAFT.format(plan="plan.json", draft="draft"),
                 f"R3 fail: {long_r3}\nR4 fail: 기대값이 깨진 fixture 5개\n{{")
    cut = bash("d2", REL_DRAFT.format(plan="plan.json", draft="draft") + " | python3 -c 'print(r[:60])'",
               f"R1 pass 대상 1개 통과\nR3 fail {long_r3[:60]}\nR4 fail 기대값이 깨진 fixture 5개\nR5 skipped 해당 없음")
    path = write(tmp_path, prompt("p"), first, cut)
    cut_q = dict(NARROW_Q, question=f"| R3 | fail | {long_r3[:60]} |\n| R4 | fail | 기대값이 깨진 fixture 5개 |\n"
                 + NARROW_Q["question"])
    out = pre("pre-ask", path, ASK, cut_q)
    assert decision(out) == "deny" and long_r3 in out["hookSpecificOutput"]["permissionDecisionReason"]
    full_q = dict(NARROW_Q, question=f"| R3 | fail | {long_r3} |\n| R4 | fail | 기대값이 깨진 fixture 5개 |\n"
                  + NARROW_Q["question"])
    assert pre("pre-ask", path, ASK, full_q) is None
