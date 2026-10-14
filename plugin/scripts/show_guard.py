#!/usr/bin/env python3
"""show_guard.py — 스크립트 출력을 요약하지 않고 사용자에게 보였는지 보는 **표시 보조** hook (08-safety.md "표시 보조 hook").

Bash·Read 출력은 사용자에게 보이지 않는다. push 확인 화면(`## push 전 확인:` ~ `approved_hash:`), Jira 게시 화면(`## … 게시 전
확인:` ~ `post_sha256:`), Step 6 분석 리포트(결정적 줄과 `must_show`), 초안 검증표(`db_verify rules --draft`, 규칙마다 한 행)는
모델이 글자 그대로 답에 옮겨야 한다. 판정은 eval 채점기와 같은 `common/shown.py`(빠진 줄 = 정규화 뒤 보인 글에 없는 줄)다.

    python3 show_guard.py stop|pre-ask|pre-bash|post   (stdin: hook 입력 JSON)

- `stop`(Stop): 이번 턴에 나온 열린 의무(창이 아직 닫히지 않은 화면·리포트·초안 표)마다 보인 글(의무 뒤 assistant 텍스트·질문 +
  `last_assistant_message`)에 빠진 것이 있으면 `{"decision": "block", "reason"}` — 모델은 새 메시지로 전체를 다시 보인다.
  리포트는 턴을 넘어 열려 있으면(탐색·심층 분석 질문 뒤) 계속 보되, 마지막 메시지가 그 질문이면 보지 않는다.
- `pre-ask`(PreToolUse `AskUserQuestion|mcp__.*__ask_user`): 같은 판정에 질문 문구를 더해 빠지면 질문을 거부(`deny`)한다.
  리포트는 Step 7 분류 질문(선택지 2개 이상)일 때만 본다(앞의 탐색·심층 분석 질문은 리포트 전이다).
- `pre-bash`(PreToolUse Bash): `db_pr.py publish --approved H`·`issue_post.py approve`면 해시가 같은 화면을 찾아 화면 뒤 ~ 마지막
  질문(또는 사용자 입력) 사이에 화면 전체가 보였는지 본다. 빠지면 거부(승인 질문 전에 화면을 보이지 않았다). 화면을 못 찾으면
  판정하지 않는다. `db_pr.py stage` 앞에 열린 초안 검증표가 보이지 않았어도 거부한다(그 창은 stage로 닫힌다).
- `post`(PostToolUse Bash): 결과에 화면·리포트·초안 검증 결과가 있으면 `additionalContext`로 "이 출력은 사용자에게 안 보인다,
  다음 메시지에 전문을 글자 그대로" 안내만 한다.

같은 의무 키(`push:<hash>`·`post:<sha>`·`report:<id>`·`draft:<id>`)로 막은 횟수(transcript의 표식 `[telephony-triage] show-guard
<key>`가 든 Stop 피드백·거부된 도구 결과)가 MAX_BLOCKS(2)에 이르면 더 막지 않고 `systemMessage`로 사용자에게 직접 확인을 안내한다.
Stop이 연이어 막혔는데(`stop_hook_active`) transcript에 표식이 없으면(피드백이 기록되지 않는 버전) 한도에 이른 것으로 본다.

**fail-open**: 표시 보조일 뿐 안전 관문이 아니다(실제 관문 — guard 규칙 7의 publish `ask`, 승인 해시, 규칙 2의 게시 승인 — 은 그대로).
입력·transcript를 못 읽거나 import·판정 중 예외면 판정하지 않고 stderr에 경고한다(stop은 `systemMessage`로 "판정 못 함"도 알린다).
파일을 쓰지 않는다. 종료 코드는 항상 0. transcript는 끝 16MB만 읽고, 화면·리포트·초안 표 흔적이 없으면 바로 끝낸다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

try:
    from common import shown  # noqa: E402
    IMPORT_ERROR: Exception | None = None
except Exception as _exc:   # noqa: BLE001 — 표시 보조는 import가 깨져도 아무것도 막지 않는다
    IMPORT_ERROR = _exc

MAX_BLOCKS = 2
TAIL_BYTES = 16 * 1024 * 1024
BLOCK_LIMIT = 12 * 1024
READ_LIMIT = 4 * 1024 * 1024
QUICK_TOKENS = ("## push 전 확인:", "게시 전 확인:", "triage.py", "--draft")
KIND_NAME = {"push": "push 확인 화면", "post": "게시 확인 화면", "report": "분석 리포트", "draft": "초안 검증표"}
OBJ = {"push": "을", "post": "을", "report": "를", "draft": "를"}      # 목적격 조사
EXPLORE_Q = re.compile(r"(심층|탐색)\s*분석[^\n]*(할까요|실행할까|진행할까|\?)")
NOTE = "[telephony-triage] 표시 안내"


def warn(msg: str) -> None:
    print(f"show_guard: {msg}", file=sys.stderr)


def emit(obj) -> None:
    if obj:
        print(json.dumps(obj, ensure_ascii=False))


# --- transcript ---------------------------------------------------------------------------------------------

def _tokens(tok: str) -> tuple[str, str]:
    return tok, json.dumps(tok)[1:-1]     # 그대로 / \uXXXX로 쓴 JSON


def load_text(path) -> str | None:
    """transcript 끝 TAIL_BYTES(첫 줄이 잘렸으면 버린다). 못 읽으면 None."""
    if not path:
        return None
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                data = fh.read()
                cut = data.find(b"\n")
                data = data[cut + 1:] if cut >= 0 else b""
            else:
                data = fh.read()
    except OSError as exc:
        warn(f"transcript를 읽지 못함({exc}) — 판정하지 않는다")
        return None
    return data.decode("utf-8", errors="replace")


def quick_skip(text: str) -> bool:
    return not any(t in text for tok in QUICK_TOKENS for t in _tokens(tok))


def load_seq(path):
    text = load_text(path)
    if text is None or quick_skip(text):
        return None
    return shown.parse_events(text.splitlines(), include_user=True)


def turn_start(seq) -> int:
    """마지막 실제 사용자 입력의 순번(tool_result·isMeta·Stop 피드백 제외). 없으면 0."""
    for i in range(len(seq) - 1, -1, -1):
        e = seq[i]
        if e["kind"] == "user" and not e["meta"] and not e["feedback"]:
            return i
    return 0


def trim_current(seq, tool_use_id):
    """PreToolUse 때 transcript에 이미 들어 있을 수 있는 지금 호출(과 그 뒤)을 뺀다."""
    if tool_use_id:
        for i, e in enumerate(seq):
            if e["kind"] == "tool" and e.get("id") == tool_use_id:
                return seq[:i]
    return seq


def markers(seq) -> list[str]:
    """이미 낸 표식의 키들(Stop 피드백·거부된 도구 결과)."""
    keys = []
    for e in seq:
        if e["kind"] == "user" and e["feedback"]:
            keys += shown.MARKER_RE.findall(e["text"])
        elif shown.denied(e):
            keys += shown.MARKER_RE.findall(str(e.get("result") or ""))
    return keys


def read_file(path: Path) -> str:
    try:
        if not path.is_file() or path.stat().st_size > READ_LIMIT:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _json_in(text: str):
    a, b = text.find("{"), text.rfind("}")
    if 0 <= a < b:
        try:
            doc = json.loads(text[a:b + 1])
        except ValueError:
            return None
        return doc if isinstance(doc, dict) else None
    return None


def job_dir_of(seq):
    """마지막 `triage.py run` 결과가 status ok이고 files.report가 있으면 그 디렉토리."""
    runs = shown.bash_index(seq, shown.TRIAGE_RUN)
    if not runs:
        return None
    doc = _json_in(str(seq[runs[-1]].get("result") or ""))
    if not doc or doc.get("status") != "ok":
        return None
    rep = (doc.get("files") or {}).get("report") if isinstance(doc.get("files"), dict) else None
    return Path(rep).parent if isinstance(rep, str) and rep else None


def last_text(seq, start: int) -> str:
    for e in reversed(seq[start:]):
        if e["kind"] == "text":
            return e["text"]
    return ""


# --- 문구 ---------------------------------------------------------------------------------------------------

def _examples(miss) -> str:
    return "\n".join(f"- {m[:160]}" for m in miss[:8])


def _block(ob) -> str:
    label = {"report": "붙일 리포트 줄", "draft": "붙일 표"}.get(ob.kind, "붙일 화면")
    if len(ob.block.encode("utf-8")) <= BLOCK_LIMIT:
        return f"--- {label} ---\n{ob.block}"
    where = ob.path or "앞 Bash 출력"
    return f"--- {label} ---\n(12KB를 넘어 여기 싣지 않는다 — {where}에서 처음부터 끝까지 그대로 옮긴다)"


def reason(ob, miss) -> str:
    name = KIND_NAME[ob.kind]
    unit = "규칙" if ob.kind == "draft" else "줄"
    head = (f"{shown.MARKER} {ob.key} — {name}{OBJ[ob.kind]} 요약했다(빠진 {unit} {len(miss)}/{ob.total}). "
            "Bash 출력은 사용자에게 보이지 않는다.")
    how = {"draft": "규칙마다 한 행(R1~R6 각각 상태, 통과가 아니면 사유)을 보이고 같은 메시지 끝에 질문을 다시 한다.",
           "report": "결정적 줄과 must_show를 글자 그대로(고쳐 쓰지 말고) 보이고 같은 메시지 끝에 질문을 다시 한다."}.get(
        ob.kind, "화면 **전체**를 처음부터 끝까지 글자 그대로 다시 붙이고 같은 메시지 끝에 승인 질문을 다시 한다.")
    return f"{head}\n{how}\n빠진 {unit} 예:\n{_examples(miss)}\n{_block(ob)}"


def approval_reason(ob, miss) -> str:
    return (f"{shown.MARKER} {ob.key} — 승인 질문 전에 확인 화면 전체를 보이지 않았다 — 화면을 다시 보이고 다시 승인받는다"
            f"(빠진 줄 {len(miss)}/{ob.total}). Bash 출력은 사용자에게 보이지 않는다.\n빠진 줄 예:\n{_examples(miss)}\n{_block(ob)}")


def stage_reason(ob, miss) -> str:
    return (f"{shown.MARKER} {ob.key} — 초안 검증표를 보이지 않고 stage하려 했다(빠진 규칙 {len(miss)}/{ob.total}). "
            "Bash 출력은 사용자에게 보이지 않는다.\nstage 전에 규칙마다 한 행(R1~R6 각각 상태, 통과가 아니면 사유)을 보인다.\n"
            f"빠진 규칙 예:\n{_examples(miss)}\n{_block(ob)}")


def capped_message(obs) -> str:
    where = ", ".join(sorted({ob.path or f"앞 Bash 출력({KIND_NAME[ob.kind]})" for ob in obs}))
    return f"[telephony-triage] 확인 화면 일부를 답에 보이지 못했다{shown.CAPPED} — {where}를 직접 확인"


# --- 모드 ---------------------------------------------------------------------------------------------------

def _checked(seq, obs, ts, *, report_ok=True):
    for ob in obs:
        if not ob.open:
            continue
        if ob.kind == "report":
            if report_ok:
                yield ob
        elif ob.start >= ts:
            yield ob


def _split(seq, found, prior_extra: int = 0):
    """빠진 의무를 한도 안(막는다)·한도 밖(안내만)으로 나눈다."""
    seen = markers(seq)
    under, over = [], []
    for ob, miss in found:
        (under if seen.count(ob.key) + prior_extra < MAX_BLOCKS else over).append((ob, miss))
    return under, over


def mode_stop(inp) -> dict | None:
    seq = load_seq(inp.get("transcript_path"))
    if seq is None:
        return None
    ts = turn_start(seq)
    obs = shown.obligations(seq, read_file, job_dir_of(seq))
    last = inp.get("last_assistant_message")
    final = last if isinstance(last, str) and last else last_text(seq, ts)
    found = []
    for ob in _checked(seq, obs, ts, report_ok=not EXPLORE_Q.search(final or "")):
        chunks = shown.visible_between(seq, ob.start + 1) + ([last] if isinstance(last, str) and last else [])
        miss = shown.missing(ob, chunks)
        if miss:
            found.append((ob, miss))
    if not found:
        return None
    # 연이은 Stop인데 이번 턴에 표식이 하나도 기록되지 않았다: 피드백이 transcript에 남지 않는 버전 — 한도로 본다
    unrecorded = bool(inp.get("stop_hook_active")) and not markers(seq[ts:])
    under, over = _split(seq, found, MAX_BLOCKS if unrecorded else 0)
    if under:
        return {"decision": "block", "reason": "\n\n".join(reason(ob, miss) for ob, miss in under)}
    over = [(ob, m) for ob, m in over if ob.start >= ts]
    return {"systemMessage": capped_message([ob for ob, _ in over])} if over else None


def _deny(text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def mode_pre_ask(inp) -> dict | None:
    seq = load_seq(inp.get("transcript_path"))
    if seq is None:
        return None
    seq = trim_current(seq, inp.get("tool_use_id"))
    tool_input = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    ts = turn_start(seq)
    obs = shown.obligations(seq, read_file, job_dir_of(seq))
    ask = shown.ask_text(tool_input)
    found = []
    for ob in _checked(seq, obs, ts, report_ok=shown.step7_question(tool_input)):
        miss = shown.missing(ob, shown.visible_between(seq, ob.start + 1) + [ask])
        if miss:
            found.append((ob, miss))
    under, over = _split(seq, found)
    if under:
        return _deny("\n\n".join(reason(ob, miss) for ob, miss in under))
    over = [(ob, m) for ob, m in over if ob.start >= ts]
    return {"systemMessage": capped_message([ob for ob, _ in over])} if over else None


def _approval_point(seq, start: int) -> int | None:
    """화면 뒤 마지막 질문(거부되지 않은) 또는 실제 사용자 입력의 순번."""
    for i in range(len(seq) - 1, start, -1):
        e = seq[i]
        if shown._live_ask(e) or (e["kind"] == "user" and not e["meta"] and not e["feedback"]):
            return i
    return None


def mode_pre_bash(inp) -> dict | None:
    tool_input = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    cmd = shown.command_of({"input": tool_input})
    pub = [m for m in shown.PUSH_END.finditer(cmd) if m.group(1) == "publish"]
    app = list(shown.POST_END.finditer(cmd))
    stage = shown.STAGE.search(cmd)
    if not (pub or app or stage):
        return None
    seq = load_seq(inp.get("transcript_path"))
    if seq is None:
        return None
    seq = trim_current(seq, inp.get("tool_use_id"))
    found, texts = [], []
    targets = []
    if pub:
        a = shown.APPROVED_ARG.search(cmd[pub[0].start():])
        if a:
            targets.append(("push", a.group(1)))
    if app:
        s = shown.SHA_ARG.search(cmd[app[0].start():])
        targets.append(("post", s.group(1) if s else None))
    for kind, h in targets:
        wins = shown.screens(seq, kind)
        pick = [w for w in wins if h is None or shown.digest_of(w).startswith(h) or h.startswith(shown.digest_of(w))]
        if not pick:
            continue      # 창을 못 찾음: 판정하지 않는다
        w = pick[-1]
        at = _approval_point(seq, w["start"])
        miss = shown.uncovered(w["lines"], shown.visible_between(seq, w["start"] + 1, len(seq) if at is None else at + 1))
        if miss:
            d = shown.digest_of(w)
            ob = shown.Obligation(kind, f"{kind}:{d if kind == 'push' else d[:16]}", w["start"], w["end"], w["end_kind"],
                                  lines=w["lines"], block=w["block"])
            found.append((ob, miss))
            texts.append(approval_reason)
    if stage:
        for ob in shown.obligations(seq):
            if ob.kind == "draft" and ob.open:
                miss = shown.missing(ob, shown.visible_between(seq, ob.start + 1))
                if miss:
                    found.append((ob, miss))
                    texts.append(stage_reason)
    fmt = {id(ob): f for (ob, _), f in zip(found, texts)}
    under, over = _split(seq, found)
    if under:
        return _deny("\n\n".join(fmt[id(ob)](ob, miss) for ob, miss in under))
    return {"systemMessage": capped_message([ob for ob, _ in over])} if over else None


def _response_text(resp) -> str:
    if isinstance(resp, dict):
        return "\n".join(str(resp.get(k) or "") for k in ("stdout", "stderr") if resp.get(k))
    if isinstance(resp, list):
        return "\n".join(str(b.get("text", "")) if isinstance(b, dict) else str(b) for b in resp)
    return str(resp or "")


def mode_post(inp) -> dict | None:
    if inp.get("tool_name") != "Bash":
        return None
    tool_input = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    out = _response_text(inp.get("tool_response"))
    if not out:
        return None
    cmd = shown.command_of({"input": tool_input})
    text = shown.tool_text({"name": "Bash", "result": out})
    found = []
    for kind, rx in (("push", shown.PUSH_SCREEN), ("post", shown.POST_SCREEN)):
        ms = list(rx.finditer(text))
        if ms:
            found.append((KIND_NAME[kind], f"전문({len(shown.screen_lines(ms[-1].group(0)))}줄)", "승인 질문"))
    if shown.DRAFT.search(cmd):
        rules = shown.draft_rules(out)
        if rules:
            found.append((KIND_NAME["draft"], f"규칙마다 한 행({len(rules)}행, 통과가 아니면 사유)", "질문"))
    report = text if shown.REPORT_HEAD.search(text) else ""
    must = []
    if not report and shown.TRIAGE_RUN.search(cmd):
        doc = _json_in(out)
        rep = (doc or {}).get("files", {}).get("report") if isinstance((doc or {}).get("files"), dict) else None
        if doc and doc.get("status") == "ok" and isinstance(rep, str):
            report = read_file(Path(rep))
            must = [str(m) for m in doc.get("must_show") or [] if isinstance(m, str)]
    core = shown.report_core(report) if report else []
    if core or must:
        found.append((KIND_NAME["report"], f"결정적 줄과 must_show({len(core) + len(must)}줄)", "Step 7 질문"))
    if not found:
        return None
    parts = [f"{NOTE} — 이 출력({name})은 사용자에게 안 보인다. 다음 메시지에 {what}을 글자 그대로 붙이고, 같은 메시지 끝에 "
             f"{ask}을 한다. 빠지면 hook이 되돌린다." for name, what, ask in found]
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(parts)}}


MODES = {"stop": mode_stop, "pre-ask": mode_pre_ask, "pre-bash": mode_pre_bash, "post": mode_post}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else ""
    if mode not in MODES:
        warn(f"모드를 모름: {mode!r} (stop|pre-ask|pre-bash|post) — 판정하지 않는다")
        return 0
    try:
        if IMPORT_ERROR is not None:
            raise RuntimeError(f"import 실패: {IMPORT_ERROR}")
        raw = sys.stdin.read()
        try:
            inp = json.loads(raw)
        except ValueError:
            warn("입력이 JSON이 아니다 — 판정하지 않는다")
            return 0
        if not isinstance(inp, dict):
            warn("입력이 JSON 객체가 아니다 — 판정하지 않는다")
            return 0
        emit(MODES[mode](inp))
    except Exception as exc:   # noqa: BLE001 — 표시 보조: 내부 오류는 아무것도 막지 않는다(fail-open)
        warn(f"내부 오류({type(exc).__name__}: {exc}) — 판정하지 않는다")
        if mode == "stop":
            emit({"systemMessage": "[telephony-triage] show_guard 판정 못 함 — 확인 화면·리포트를 답에 그대로 보였는지 직접 확인"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
