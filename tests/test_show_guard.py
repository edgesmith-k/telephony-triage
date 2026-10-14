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
DRAFT_OUT = json.dumps({"rules": [{"id": "R1", "status": "pass", "reason": "대상 1개 통과"},
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
    assert r.startswith(shown.MARKER + " push:abc1234def — push 확인 화면을 요약했다(빠진 줄 ")
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
    short = REPORT.replace(" (f0:L6)", "") + "\n" + MUST
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
    assert out["hookSpecificOutput"]["permissionDecisionReason"].startswith(shown.MARKER + " push:abc1234def")


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
    table = "| R1 | 통과 | 대상 1개 통과 |\n| R5 | 건너뜀 | 해당 없음 |\n진행할까요?"
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
    key = shown.MARKER + " push:abc1234def — 승인 질문 전에"
    capped = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), prompt("승인"),
                   call("x1", "Bash", {"command": PUBLISH_CMD}, key, True),
                   call("x2", "Bash", {"command": PUBLISH_CMD}, key, True), name="cap.jsonl")
    out = pre("pre-bash", capped, "Bash", {"command": PUBLISH_CMD})
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]


def test_pre_bash_stage_after_unshown_draft(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증을 통과했습니다."))
    out = pre("pre-bash", path, "Bash", {"command": STAGE_CMD})
    assert decision(out) == "deny" and "초안 검증표를 보이지 않고 stage" in out["hookSpecificOutput"]["permissionDecisionReason"]
    ok = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("| R1 | pass | 대상 1개 통과 |\n| R5 | skipped | 해당 없음 |"),
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
    assert "규칙마다 한 행(2행" in out["hookSpecificOutput"]["additionalContext"]
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
    out = pre("pre-bash", again, "Bash", {"command": PUBLISH_CMD})       # 한 번만 막는다
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]
    nostage = write(tmp_path, prompt("승인해줘"), say("네"), name="nostage.jsonl")
    assert pre("pre-bash", nostage, "Bash", {"command": PUBLISH_CMD}) is None   # 화면을 낸 호출이 없다: 판정하지 않는다
    render = "python3 /p/scripts/issue_post.py render MOCK-1 --fill /w/MOCK-1/post.fill.json --json"
    approve = "python3 /p/scripts/issue_post.py approve MOCK-1 --sha " + "c" * 64
    post = write(tmp_path, prompt("p"), bash("r", render + " | tail -1", '"post_sha256": "' + "c" * 64 + '"'), prompt("게시"),
                 name="post.jsonl")
    out = pre("pre-bash", post, "Bash", {"command": approve})
    r = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert decision(out) == "deny" and "post:cccccccccccccccc" in r and "issue_post.py render MOCK-1 --fill" in r


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


# --- sm4 재측정 반영: transcript 비동기 기록, 초안 키, stage 거부 문구 ------------------------------------------------

def test_waits_until_current_call_is_recorded(tmp_path):
    """sm4 거짓 거부 8건: 화면 전문을 쓴 텍스트 블록과 질문이 한 응답인데 PreToolUse 때 transcript에 텍스트가 아직 없었다.
    hook은 지금 호출(tool_use_id)이 기록될 때까지 기다린다."""
    import threading
    path = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN))
    ask = {"question": "승인할까요?"}

    def later():
        time.sleep(0.6)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(say(SCREEN)[0], ensure_ascii=False) + "\n")
            fh.write(json.dumps(call("q1", ASK, ask)[0], ensure_ascii=False) + "\n")
    t = threading.Thread(target=later)
    t.start()
    out = pre("pre-ask", path, ASK, ask, "q1", record=False)
    t.join()
    assert out is None
    # 끝내 기록되지 않으면(형식이 다른 버전) 거부하지 않는다(fail-open, 경고)
    lost = write(tmp_path, prompt("p"), bash("s", STAGE_CMD, SCREEN), say(SUMMARY), name="lost.jsonl")
    t0 = time.time()
    out, err = hook("pre-ask", {"transcript_path": str(lost), "tool_name": ASK, "tool_input": ask, "tool_use_id": "zz"})
    assert out is None and "기록되지 않아" in err and time.time() - t0 < 15
    assert decision(pre("pre-ask", lost, ASK, ask, "zz")) == "deny"          # 기록되면 판정한다


def test_draft_rerun_with_same_result_shares_key_and_cap(tmp_path):
    out1 = shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d1", DRAFT_CMD, DRAFT_OUT)]))
    out2 = shown.obligations(shown.parse_events([json.dumps(r, ensure_ascii=False) for r in bash("d2", DRAFT_CMD, DRAFT_OUT)]))
    assert out1[0].key == out2[0].key and out1[0].key.startswith("draft:")
    key = out1[0].key
    deny = shown.MARKER + " " + key + " — 초안 검증표를 요약했다"
    path = write(tmp_path, prompt("p"), bash("d1", DRAFT_CMD, DRAFT_OUT), call("a1", ASK, {"question": "진행?"}, deny, True),
                 call("a2", ASK, {"question": "진행?"}, deny, True), bash("d2", DRAFT_CMD, DRAFT_OUT))
    out = pre("pre-ask", path, ASK, {"question": "note를 승인할까요?"})
    assert decision(out) is None and shown.CAPPED in out["systemMessage"]      # 다시 돌려도 한도는 그대로


def test_stage_deny_does_not_invite_a_new_question(tmp_path):
    path = write(tmp_path, prompt("p"), bash("d", DRAFT_CMD, DRAFT_OUT), say("초안 검증 통과."))
    r = pre("pre-bash", path, "Bash", {"command": STAGE_CMD})["hookSpecificOutput"]["permissionDecisionReason"]
    assert "같은 stage 명령을 다시 실행한다" in r and "새 질문을 만들지 않는다" in r
