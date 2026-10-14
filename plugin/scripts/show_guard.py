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
  판정하지 않는다 — 단 그 해시의 화면이 어느 도구 출력에도 없는데 화면을 낸 호출(stage·summary / render)이 기록에 있으면 한 번
  거부하고 `summary <wt> --format markdown`(render)을 파이프 없이 다시 내게 한다. `db_pr.py stage` 앞에 열린 초안 검증표가
  보이지 않았어도 거부한다(그 창은 stage로 닫힌다).
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
QUICK_TOKENS = ("## push 전 확인:", "게시 전 확인:", "triage.py", "--draft", "db_pr.py", "issue_post.py")
KIND_NAME = {"push": "push 확인 화면", "post": "게시 확인 화면", "report": "분석 리포트", "draft": "초안 검증표"}
OBJ = {"push": "을", "post": "을", "report": "를", "draft": "를"}      # 목적격 조사
EXPLORE_Q = re.compile(r"(심층|탐색)\s*분석[^\n]*(할까요|실행할까|진행할까|\?)")
NOTE = "[telephony-triage] 표시 안내"
TRUNCATED = [False]      # 마지막 load_text가 끝부분만 읽었는가


def warn(msg: str) -> None:
    try:      # stderr의 오류 처리는 backslashreplace라 인코딩이 달라도 쓰인다
        print(f"show_guard: {msg}", file=sys.stderr)
    except Exception:   # noqa: BLE001, S110 — 경고를 못 써도 종료 0
        pass


def emit(obj) -> None:
    if obj:      # ASCII로만 쓴다: stdout 인코딩(Windows cp949·PYTHONIOENCODING=ascii)과 무관하게
        sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
        sys.stdout.flush()


# --- transcript ---------------------------------------------------------------------------------------------

def _tokens(tok: str) -> tuple[str, str]:
    return tok, json.dumps(tok)[1:-1]     # 그대로 / \uXXXX로 쓴 JSON


def load_text(path) -> str | None:
    """transcript 끝 TAIL_BYTES(첫 줄이 잘렸으면 버린다). 못 읽으면 None. 잘라 읽었으면 TRUNCATED[0]이 True."""
    TRUNCATED[0] = False
    if not path:
        return None
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > TAIL_BYTES:
                TRUNCATED[0] = True
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


def turn_start(seq) -> int | None:
    """마지막 실제 사용자 입력의 순번(tool_result·isMeta·Stop 피드백 제외). 없으면 0 — 단 transcript를 끝부분만 읽었으면
    이번 턴의 시작을 모르므로 None(판정하지 않는다)."""
    for i in range(len(seq) - 1, -1, -1):
        e = seq[i]
        if e["kind"] == "user" and not e["meta"] and not e["feedback"]:
            return i
    return None if TRUNCATED[0] else 0


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


UNSEEN_BLOCKS = 1      # 화면이 도구 결과에 없던 승인: 한 번만 막는다(다시 낸 화면은 그다음부터 보통 판정)


def unseen_reason(key: str, kind: str, cmd: str) -> str:
    """승인할 화면이 어느 도구 결과에도 없다: 화면을 다시 내는 명령을 알려 준다."""
    if kind == "push":
        m = re.search(r"(\S*db_pr\.py)[\"']?\s+(?:--\S+\s+\S+\s+)*publish\s+(\S+)", cmd)
        how = (f"`python3 {m.group(1)} summary {m.group(2)} --format markdown`" if m
               else "`python3 S/db_pr.py summary <wt> --format markdown`")
        what = "push 확인 화면"
    else:
        m = re.search(r"(\S*issue_post\.py)[\"']?\s+(?:--\S+\s+\S+\s+)*approve\s+(\S+)", cmd)
        how = (f"`python3 {m.group(1)} render {m.group(2)} --fill JOB/post.fill.json`" if m
               else "`python3 S/issue_post.py render <KEY> --fill JOB/post.fill.json`")
        what = "게시 확인 화면"
    return (f"{shown.MARKER} {key} — 승인하려는 {what}이 어느 도구 출력에도 없다(리디렉션·`head`·`grep`·파일에서 해시를 읽음). "
            "Bash 출력은 사용자에게 보이지 않고, 보지 않은 화면은 승인의 근거가 될 수 없다.\n"
            f"{how}를 파이프·리디렉션 없이 실행하고, 그 출력 전체를 글자 그대로 답에 붙인 뒤 같은 메시지 끝에 다시 승인받는다.")


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
    if ts is None:
        return None
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
    # 연이은 Stop인데 이번 턴에 표식이 하나도 기록되지 않았다: 다른 hook이 막았거나 피드백이 transcript에 남지 않는 버전 —
    # 횟수를 셀 수 없으므로 조용히 둔다(한도 안내도 내지 않는다)
    if inp.get("stop_hook_active") and not markers(seq[ts:]):
        return None
    under, over = _split(seq, found)
    if under:
        return {"decision": "block", "reason": "\n\n".join(reason(ob, miss) for ob, miss in under)}
    over = [(ob, m) for ob, m in over if ob.start >= ts]
    return {"systemMessage": capped_message([ob for ob, _ in over])} if over else None


def _deny(text: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def mode_pre_ask(inp) -> dict | None:
    if not shown.is_ask(inp.get("tool_name")):
        return None
    seq = load_seq(inp.get("transcript_path"))
    if seq is None:
        return None
    seq = trim_current(seq, inp.get("tool_use_id"))
    tool_input = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    ts = turn_start(seq)
    if ts is None:
        return None
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
    found, texts, unseen = [], [], []
    targets = []
    if pub:
        a = shown.APPROVED_ARG.search(cmd[pub[0].start():])
        if a:
            targets.append(("push", a.group(1)))
    if app:
        s = shown.SHA_ARG.search(cmd[app[0].start():])
        targets.append(("post", s.group(1) if s else None))
    for kind, h in targets:
        wins = shown.screens(seq, kind, script_only=True)
        pick = [w for w in wins if h is None or shown.digest_of(w).startswith(h) or h.startswith(shown.digest_of(w))]
        if not pick:
            # 화면이 어느 도구 결과에도 없다(리디렉션·파이프·state.json에서 해시): 그 화면을 낸 호출이 이 기록에 있으면
            # 한 번 막고 화면을 다시 내게 한다. 끝부분만 읽었거나 그런 호출이 없으면 판정하지 않는다
            makers = (shown.STAGE, shown.SUMMARY) if kind == "push" else (shown.RENDER,)
            if not TRUNCATED[0] and any(shown.bash_index(seq, m) for m in makers):
                key = f"{kind}:{h if kind == 'push' else (h or 'render')[:16]}"
                unseen.append((key, kind, cmd))
            continue
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
    seen = markers(seq)
    first = [u for u in unseen if seen.count(u[0]) < UNSEEN_BLOCKS]
    if under or first:
        return _deny("\n\n".join([fmt[id(ob)](ob, miss) for ob, miss in under] + [unseen_reason(*u) for u in first]))
    later = [u for u in unseen if u not in first]
    if over or later:
        msg = capped_message([ob for ob, _ in over]) if over else \
            f"[telephony-triage] 확인 화면을 답에 보이지 못했다{shown.CAPPED} — 승인 전에 화면을 직접 확인"
        return {"systemMessage": msg}
    return None


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
    saved = _persisted(inp.get("tool_response"), text)
    if saved is not None and not found and any(h.search(text) for h in shown.SCREEN_HEAD.values()):
        found.append(("확인 화면", "전문", "승인 질문"))      # 잘려서 해시 줄이 없는 화면
    if not found:
        return None
    if saved is not None:       # 출력이 길어 파일로 남고 모델에는 일부만 보인다: 줄 수 대신 그 파일
        where = saved or "원래 명령의 출력 파일"
        parts = [f"{NOTE} — 이 출력({name})은 잘려 보였고 사용자에게도 안 보인다. 전문은 {where}에 있다 — 그 파일을 읽어 "
                 f"{what}을 글자 그대로 다음 메시지에 붙이고, 같은 메시지 끝에 {ask}을 한다. 빠지면 hook이 되돌린다."
                 for name, what, ask in found]
    else:
        parts = [f"{NOTE} — 이 출력({name})은 사용자에게 안 보인다. 다음 메시지에 {what}을 글자 그대로 붙이고, 같은 메시지 "
                 f"끝에 {ask}을 한다. 빠지면 hook이 되돌린다." for name, what, ask in found]
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n".join(parts)}}


PERSISTED = re.compile(r"(?:Output too large|Full output)[^\n]*?saved to:?\s*(\S+)|(Output too large)")


def _persisted(resp, text: str):
    """Claude Code가 긴 출력을 파일로 남겼으면 그 경로(모르면 ""), 아니면 None. 응답의 `persist…`·`…Path` 문자열 키나
    "Output too large … saved to: <path>" 문구로 본다(형식은 버전마다 다를 수 있어 최선 노력)."""
    if isinstance(resp, dict):
        for k, v in resp.items():
            if "persist" in str(k).lower() and isinstance(v, str) and v:
                return v
            if "persist" in str(k).lower() and v is True:
                return ""
    m = PERSISTED.search(text[:2000]) or PERSISTED.search(text[-2000:])
    return None if m is None else (m.group(1) or "")


MODES = {"stop": mode_stop, "pre-ask": mode_pre_ask, "pre-bash": mode_pre_bash, "post": mode_post}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else ""
    if mode not in MODES:
        warn(f"모드를 모름: {mode!r} (stop|pre-ask|pre-bash|post) — 판정하지 않는다")
        return 0
    inp = None
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        try:
            inp = json.loads(raw)
        except ValueError:
            warn("입력이 JSON이 아니다 — 판정하지 않는다")
            return 0
        if not isinstance(inp, dict):
            warn("입력이 JSON 객체가 아니다 — 판정하지 않는다")
            return 0
        if IMPORT_ERROR is not None:
            raise RuntimeError(f"import 실패: {IMPORT_ERROR}")
        emit(MODES[mode](inp))
    except Exception as exc:   # noqa: BLE001 — 표시 보조: 내부 오류는 아무것도 막지 않는다(fail-open)
        warn(f"내부 오류({type(exc).__name__}: {exc}) — 판정하지 않는다")
        try:
            # 판정 못 함 안내는 stop에서, 이 세션 transcript에 화면·리포트 흔적이 있을 때만(매 턴 되풀이하지 않게)
            if mode == "stop" and _has_tokens(inp if isinstance(inp, dict) else {}):
                emit({"systemMessage": "[telephony-triage] show_guard 판정 못 함 — 확인 화면·리포트를 답에 그대로 보였는지 "
                                       "직접 확인"})
        except Exception:   # noqa: BLE001, S110 — 어떤 경우에도 종료 0
            pass
    return 0


def _has_tokens(inp) -> bool:
    text = load_text(inp.get("transcript_path"))
    if text is None or quick_skip(text):
        return False
    # 이번 턴(마지막 실제 사용자 입력 뒤)에 흔적이 있을 때만: 지난 턴의 화면으로 매 턴 안내하지 않는다
    lines = text.splitlines()
    start = 0
    for k in range(len(lines) - 1, -1, -1):
        try:
            ev = json.loads(lines[k])
        except ValueError:
            continue
        msg = ev.get("message") if isinstance(ev, dict) else None
        if ev.get("type") == "user" and not ev.get("isMeta") and isinstance(msg, dict) and isinstance(msg.get("content"), str):
            start = k
            break
    return not quick_skip("\n".join(lines[start:]))


if __name__ == "__main__":
    raise SystemExit(main())
