#!/usr/bin/env python3
"""show_guard.py — 스크립트 출력을 요약하지 않고 사용자에게 보였는지 보는 **표시 보조** hook (08-safety.md "표시 보조 hook").

Bash·Read 출력은 사용자에게 보이지 않는다. push 확인 화면, 게시 확인 화면, Step 6 분석 리포트(결정적 줄과 `must_show`),
초안 검증표(규칙마다 한 행), 스킬 제안 patch 안내 줄(`skill_patch.py`, 안내 줄과 파일별 줄 수 또는 메모)은 모델이 글자 그대로
답에 옮겨야 한다.

**무엇이 의무인가 — 스크립트 기록**(L R): `db_pr summary`·`issue_post render`·`triage run`·`db_verify rules --draft`·
`skill_patch`가 낸 출력과
`stage`·`publish`·`discard`·`lock`·`approve`가 실행된 사실을 스크립트가 `<work_dir>/.shown/log.jsonl`에 직접 남긴다
(`common/shown.py` `record`, contracts.md "표시 기록"). hook은 사용자 config의 모든 프로필 work_dir에서 이 세션의 기록을 읽어
transcript의 Bash 호출에 시각으로 고정하고(`shown.anchor`: tool_use 시각 − 2초 ≤ 기록 시각 ≤ tool_result 시각, 명령에 기록의
스크립트 이름) 창을 계산한다(`shown.record_obligations`). 도구 출력·명령 모양으로 화면이 나왔는지 추론하지 않는다(그 추론은 eval
채점기 전용 `tests/skill_evals/shown_infer.py`). **보였는가**는 transcript로 본다: 의무 뒤 assistant 텍스트·거부되지 않은 질문
문구에 정규화한 줄이 다 있는가(`shown.missing`).

    python3 show_guard.py stop|pre-ask|pre-bash|post   (stdin: hook 입력 JSON)

- `stop`(Stop): 이번 턴에 열린 의무(리포트는 턴을 넘어 열려 있어도, 단 마지막 메시지가 탐색·심층 분석 질문이면 리포트는 보지
  않는다)마다 보인 글 + `last_assistant_message`에 빠진 것이 있으면 `{"decision": "block", "reason"}`.
- `pre-ask`(PreToolUse `AskUserQuestion|mcp__.*__ask_user`): 같은 판정에 질문 문구를 더해 빠지면 질문을 거부한다. 리포트는
  Step 7 분류 질문일 때만 본다.
- `pre-bash`(PreToolUse Bash): 명령이 `db_pr`·`publish`(`guard.word_net`, 규칙 7과 같은 낱말 그물)면 해시가 같은 push 의무(해시가
  변수 — `--approved "$H"` — 면 마지막 stage 실행 뒤에 기록된 push 의무)를, `issue_post`·`approve`면 post 의무를 골라 의무 뒤 ~
  마지막 질문(또는 사용자 입력) 사이에 화면 전체가 보였는지 본다. 맞는 의무가 없으면 판정하지 않는다(스크립트의 해시 대조와 규칙 7
  ask가 관문). `db_pr`·`stage`면 열린 초안 검증표(전부 통과 표 `shown.draft_all_clear` 제외 — push 확인 화면의 "검증 결과"로
  갈음)가 보였는지 본다. 거부 문구에는 붙일 화면 전문(12KB 이하)이 실린다.
- `post`(PostToolUse Bash): 명령에 기록 스크립트 이름이 있고 60초 안에 그 스크립트의 의무 기록이 있으면 `additionalContext`로
  "이 출력은 사용자에게 안 보인다, 다음 메시지에 전문을 글자 그대로" 안내만 한다.

같은 의무 키(`push:<hash>`·`post:<sha 앞 16자>`·`report:<KEY>#<run>`·`draft:<sha1 12자>`·`patch:<KEY>/<스킬 이름>`·`apply:<KEY>/<스킬 이름>`)로 막은 횟수(transcript의 표식
`[telephony-triage] show-guard <key>`가 든 Stop 피드백·거부된 도구 결과, 그 의무가 생긴 뒤)가 MAX_BLOCKS(2)에 이르면 더 막지
않고 `systemMessage`로 사용자에게 직접 확인을 안내한다. 거부된 호출을 똑같이(`description` 제외) 사이 글·질문·사용자 입력 없이
다시 한 거부는 키마다 BLIND_FREE(1)번까지 세지 않는다 — 그 거부 문구에는 RETRY_NOTE를 붙인다. Stop이 연이어 막혔는데
(`stop_hook_active`) 이번 턴 transcript에 표식이 없으면 아무것도 내지 않는다.

**fail-open**: 표시 보조일 뿐 안전 관문이 아니다(실제 관문 — guard 규칙 7의 publish `ask`, 승인 해시·pre-push, 규칙 2의 게시
승인 — 은 그대로). 입력·transcript·config·기록을 못 읽거나 import·판정 중 예외면 판정하지 않고 stderr에 경고한다(stop은 이번 턴에
화면·리포트 흔적이 있으면 `systemMessage`로 "판정 못 함"도 알린다). hook은 파일을 쓰지 않는다. 종료 코드는 항상 0. 이 세션의
기록이 없으면 transcript를 읽지 않고 끝낸다. transcript는 끝 16MB만 읽는다.
"""

from __future__ import annotations

import json
import re
import sys
import time
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
HEAD_BYTES = 64 * 1024
BLOCK_LIMIT = 12 * 1024
# ponytail: post 안내는 지금 호출이 남긴 기록을 시각으로만 고른다(60초). 같은 스크립트를 60초 안에 두 번 부르면 앞 기록도 안내한다
POST_WINDOW = 60.0
RECORD_SCRIPTS = ("db_pr", "issue_post", "db_verify", "triage", "skill_patch")
QUICK_TOKENS = ("## push 전 확인:", "게시 전 확인:", "triage.py", "--draft", "db_pr.py", "issue_post.py", "skill_patch.py")
KIND_NAME = {"push": "push 확인 화면", "post": "게시 확인 화면", "report": "분석 리포트", "draft": "초안 검증표",
             "patch": "스킬 제안 patch 안내"}
OBJ = {"push": "을", "post": "을", "report": "를", "draft": "를", "patch": "를"}      # 목적격 조사
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


# --- 기록 ---------------------------------------------------------------------------------------------------

def work_dirs() -> list[Path]:
    """사용자 config의 모든 프로필 work_dir(TT_PLATFORM과 무관 — guard처럼). PyYAML이 필요해 지연 import한다."""
    from common import userconfig
    out = []
    for cfg in userconfig.profiles({}).values():
        w = userconfig.get(cfg, "work_dir")
        if w:
            out.append(Path(str(w)).expanduser())
    return list(dict.fromkeys(out))


def session_start(path) -> float | None:
    """transcript 앞부분(HEAD_BYTES)의 첫 `timestamp`. 없으면 None(시각이 없는 transcript는 기록을 고정할 수 없다)."""
    try:
        with Path(path).open("rb") as fh:
            head = fh.read(HEAD_BYTES).decode("utf-8", errors="replace")
    except OSError as exc:
        warn(f"transcript를 읽지 못함({exc}) — 판정하지 않는다")
        return None
    for line in head.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = shown._epoch(ev.get("timestamp")) if isinstance(ev, dict) else None
        if t is not None:
            return t
    return None


def load_records(path) -> list[dict]:
    """이 세션의 기록: 세션 첫 시각(− ANCHOR_SLACK)보다 이른 기록은 버린다. 비면 transcript를 읽지 않고 끝낸다."""
    if not path:
        return []
    t0 = session_start(path)
    if t0 is None:
        return []
    return [r for r in shown.read_records(work_dirs())
            if (shown._epoch(r.get("at")) or 0) >= t0 - shown.ANCHOR_SLACK]


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
    return None if text is None else shown.parse_events(text.splitlines(), include_user=True)


def turn_start(seq) -> int | None:
    """마지막 실제 사용자 입력의 순번(tool_result·isMeta·Stop 피드백 제외). 없으면 0 — 단 transcript를 끝부분만 읽었으면
    이번 턴의 시작을 모르므로 None(판정하지 않는다)."""
    for i in range(len(seq) - 1, -1, -1):
        e = seq[i]
        if e["kind"] == "user" and not e["meta"] and not e["feedback"]:
            return i
    return None if TRUNCATED[0] else 0


WAIT_SECONDS = 2.0       # PreToolUse 때 transcript에 지금 호출이 기록될 때까지 기다리는 상한
WAIT_STEP = 0.05


def _wait_recorded(path, tool_use_id) -> bool:
    """transcript에 tool_use_id가 나타날 때까지 새로 붙은 바이트만 본다(WAIT_SECONDS 상한). 나타났으면 True."""
    needle = tool_use_id.encode("utf-8")
    deadline = time.monotonic() + WAIT_SECONDS
    pos, tail = 0, b""
    try:
        with Path(path).open("rb") as fh:
            size = fh.seek(0, 2)
            pos = max(0, size - TAIL_BYTES)
            while True:
                fh.seek(pos)
                chunk = fh.read()
                pos += len(chunk)
                if needle in tail + chunk:
                    return True
                tail = (tail + chunk)[-len(needle):]
                if time.monotonic() >= deadline:
                    return False
                time.sleep(WAIT_STEP)
    except OSError:
        return False


def load_seq_for_call(path, tool_use_id):
    """PreToolUse: transcript는 비동기로 쓰여 같은 응답의 앞 텍스트 블록이 아직 없을 수 있다(10/14 sm4: 화면 전문을 쓴 직후의
    질문이 거부됨). 한 응답의 블록은 텍스트가 tool_use보다 먼저 기록되므로(sm4 transcript 300개 응답에서 예외 없음, probe 13번)
    지금 호출(tool_use_id)이 기록되면 앞 블록도 다 기록된 것이다 — 그때까지 기다린 뒤(WAIT_SECONDS 상한, 새 바이트만 확인)
    한 번 읽는다. → (seq, 판정 가능 여부). 기록되지 않으면 False — 거부하지 않는다(fail-open). 입력에 tool_use_id가 없으면
    기다릴 수 없으니 바로 판정한다(이전 동작, 경고)."""
    if not tool_use_id:
        warn("입력에 tool_use_id가 없어 transcript 기록을 기다리지 않고 판정한다")
        return load_seq(path), True
    recorded = _wait_recorded(path, str(tool_use_id)) if path else False
    return load_seq(path), recorded


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


def last_text(seq, start: int) -> str:
    for e in reversed(seq[start:]):
        if e["kind"] == "text":
            return e["text"]
    return ""


# --- 문구 ---------------------------------------------------------------------------------------------------

def _examples(miss) -> str:
    return "\n".join(f"- {m[:160]}" for m in miss[:8])


def _block(ob) -> str:
    label = {"report": "붙일 리포트 줄", "draft": "붙일 표", "patch": "붙일 줄"}.get(ob.kind, "붙일 화면")
    if len(ob.block.encode("utf-8")) <= BLOCK_LIMIT:
        return f"--- {label} ---\n{ob.block}"
    where = ob.path or "앞 Bash 출력"
    return f"--- {label} ---\n(12KB를 넘어 여기 싣지 않는다 — {where}에서 처음부터 끝까지 그대로 옮긴다)"


# 거부·되돌림 문구 첫 줄(표식 + 키가 맨 앞 — contracts.md "reason 첫 줄 표식"). 모델이 거부를 일시 오류로 읽고 같은 호출을
# 기다렸다 다시 하거나(`sleep 3`), Bash 출력·거부 문구가 사용자에게 보인다고 믿은 일(10/14)이 있어 그렇지 않다고 밝힌다
DENY_LEAD = "— 거부됨(오류·일시 장애 아님). 이 호출은 실행되지 않았다. 기다리거나 같은 호출을 그대로 다시 하면 또 거부된다."
STOP_LEAD = "— 되돌림(오류 아님):"
UNSEEN_NOTE = "Bash 출력과 이 거부 문구는 사용자에게 안 보인다."
RETRY_NOTE = "방금 거부된 것과 똑같은 호출이다(사이에 쓴 글 없음). 다시 불러도 사용자에게 보인 것은 그대로다 — 글을 먼저 쓴다."


def _deny_text(ob, why: str, todo: str, miss, retry: bool, unit: str = "줄") -> str:
    lines = [f"{shown.MARKER} {ob.key} {DENY_LEAD}", f"까닭: {why} {UNSEEN_NOTE}", f"할 일: {todo}"]
    if retry:
        lines.append(RETRY_NOTE)
    return "\n".join(lines + [f"빠진 {unit} 예:\n{_examples(miss)}", _block(ob)])


def reason(ob, miss, *, deny: bool = False, retry: bool = False) -> str:
    """Stop 되돌림(deny=False)·질문 거부(deny=True) 문구."""
    name = KIND_NAME[ob.kind]
    unit = "규칙" if ob.kind == "draft" else "줄"
    why = f"{name}{OBJ[ob.kind]} 요약했다(빠진 {unit} {len(miss)}/{ob.total})."
    if deny:
        what = {"draft": "규칙마다 한 행(R1~R6 각각 상태, 통과가 아니면 사유)을",
                "report": "아래 결정적 줄과 must_show를 글자 그대로(고쳐 쓰지 말고)",
                "patch": "아래 줄을 모두 글자 그대로(고쳐 쓰지 말고)"}.get(
            ob.kind, "아래 화면 **전체**를 처음부터 끝까지 글자 그대로")
        todo = f"{what} 질문 본문 앞(또는 질문 바로 앞 글)에 넣고 질문을 다시 부른다."
        return _deny_text(ob, why, todo, miss, retry, unit)
    head = f"{shown.MARKER} {ob.key} {STOP_LEAD} {why} Bash 출력은 사용자에게 보이지 않는다."
    how = {"draft": "규칙마다 한 행(R1~R6 각각 상태, 통과가 아니면 사유)을 보이고 같은 메시지 끝에 질문을 다시 한다.",
           "report": "결정적 줄과 must_show를 글자 그대로(고쳐 쓰지 말고) 보이고 같은 메시지 끝에 질문을 다시 한다.",
           "patch": "아래 줄을 모두 글자 그대로(고쳐 쓰지 말고) 보인다 — 질문이 있었으면 같은 메시지 끝에 다시 한다."}.get(
        ob.kind, "화면 **전체**를 처음부터 끝까지 글자 그대로 다시 붙이고 같은 메시지 끝에 승인 질문을 다시 한다.")
    return f"{head}\n{how}\n빠진 {unit} 예:\n{_examples(miss)}\n{_block(ob)}"


def approval_reason(ob, miss, retry: bool = False) -> str:
    return _deny_text(ob, f"승인 질문 전에 확인 화면 전체를 보이지 않았다 — 화면을 다시 보이고 다시 승인받는다"
                          f"(빠진 줄 {len(miss)}/{ob.total}).",
                      "아래 화면 전체를 글자 그대로 답에 붙이고 같은 메시지 끝에 승인 질문을 다시 한 뒤, 승인받으면 같은 명령을 "
                      "실행한다.", miss, retry)


def stage_reason(ob, miss, retry: bool = False) -> str:
    return _deny_text(ob, f"초안 검증표를 보이지 않고 stage하려 했다(빠진 규칙 {len(miss)}/{ob.total}).",
                      "먼저 답(글)에 아래 표를 그대로 쓰고, 그 글 뒤에(같은 응답에서) 같은 stage 명령을 다시 실행한다 — 진행 "
                      "여부를 묻는 새 질문을 만들지 않는다.", miss, retry, "규칙")


def capped_message(obs) -> str:
    where = ", ".join(sorted({ob.path or f"앞 Bash 출력({KIND_NAME[ob.kind]})" for ob in obs}))
    return f"[telephony-triage] 확인 화면 일부를 답에 보이지 못했다{shown.CAPPED} — {where}에서 직접 확인"


# --- 모드 ---------------------------------------------------------------------------------------------------

def obligations(seq, recs):
    """`shown.record_obligations`에서 전부 통과한 초안 표(`shown.draft_all_clear`)를 뺀 것: 그 표는 push 확인 화면의 "검증
    결과"로 갈음한다(승인 전 표시는 pre-bash·Stop이 화면으로 본다, 10/14 사용자 결정). fail·`fixture 없음` 등이 든 표는 그대로."""
    return [ob for ob in shown.record_obligations(seq, recs)
            if not (ob.kind == "draft" and shown.draft_all_clear(ob.rules))]


def _checked(seq, obs, ts, *, report_ok=True):
    for ob in obs:
        if not ob.open:
            continue
        if ob.kind == "report":
            if report_ok:
                yield ob
        elif ob.start >= ts:
            yield ob


BLIND_FREE = 1      # 키마다 세지 않는 "보지 않고 다시 한" 거부의 상한 → 같은 키 거부는 최대 MAX_BLOCKS + BLIND_FREE번


def _sig(name, tool_input) -> str:
    """같은 호출 비교용: 도구 이름 + 입력(`description` 제외)."""
    inp = {k: v for k, v in (tool_input if isinstance(tool_input, dict) else {}).items() if k != "description"}
    return json.dumps([str(name or ""), inp], ensure_ascii=False, sort_keys=True)


def _quiet(seq, a: int, b: int) -> bool:
    """seq[a:b]에 사용자에게 보인 글(assistant 텍스트·거부되지 않은 질문)도 사용자 입력·Stop 피드백도 없다(다른 도구 호출은
    상관없다 — `sleep 3`)."""
    for e in seq[max(a, 0):b]:
        if e["kind"] == "text" or shown._live_ask(e) or (e["kind"] == "user" and (e["feedback"] or not e["meta"])):
            return False
    return True


def _denies_of(seq, key: str, start: int = 0) -> list[int]:
    return [i for i in range(max(start, 0), len(seq)) if shown.denied(seq[i])
            and key in shown.MARKER_RE.findall(str(seq[i].get("result") or ""))]


def blind_retries(seq, key: str, start: int = 0) -> int:
    """seq[start:]의 key 거부 중 바로 앞 같은 키 거부와 똑같은 호출을 그 사이에 글·질문·사용자 입력 없이 다시 한 것의 수.
    거부를 일시 오류로 읽고 기다렸다 되풀이한 호출(10/14)은 표를 보일 기회를 쓴 것이 아니다."""
    ds = _denies_of(seq, key, start)
    return sum(1 for a, b in zip(ds, ds[1:])
               if _sig(seq[a]["name"], seq[a]["input"]) == _sig(seq[b]["name"], seq[b]["input"]) and _quiet(seq, a + 1, b))


def block_count(seq, key: str, start: int = 0) -> int:
    """seq[start:]에서 key로 막은 횟수(표식이 든 Stop 피드백·거부된 도구 결과). 보지 않고 다시 한 거부는 BLIND_FREE번까지 빼고
    센다(Stop 피드백은 빼지 않는다)."""
    return markers(seq[start:]).count(key) - min(BLIND_FREE, blind_retries(seq, key, start))


def is_retry(seq, key: str, name, tool_input, start: int = 0) -> bool:
    """지금 호출이 마지막 key 거부와 똑같고, 그 뒤 글·질문·사용자 입력이 없다."""
    ds = _denies_of(seq, key, start)
    return bool(ds) and _sig(seq[ds[-1]]["name"], seq[ds[-1]]["input"]) == _sig(name, tool_input) \
        and _quiet(seq, ds[-1] + 1, len(seq))


def _split(seq, found):
    """빠진 의무를 한도 안(막는다)·한도 밖(안내만)으로 나눈다. 막은 횟수는 그 의무가 생긴 뒤의 표식만 센다 — 다른 작업의 같은
    키 표식은 세지 않는다(같은 key는 하나의 의무라 첫 기록이 곧 셈 시작). 보지 않고 똑같이 다시 한 거부는 BLIND_FREE번까지
    세지 않는다(`block_count`)."""
    under, over = [], []
    for ob, miss in found:
        (under if block_count(seq, ob.key, ob.start) < MAX_BLOCKS else over).append((ob, miss))
    return under, over


def mode_stop(inp) -> dict | None:
    recs = load_records(inp.get("transcript_path"))
    if not recs:
        return None
    seq = load_seq(inp.get("transcript_path"))
    if seq is None:
        return None
    ts = turn_start(seq)
    if ts is None:
        return None
    obs = obligations(seq, recs)
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
    recs = load_records(inp.get("transcript_path"))
    if not recs:
        return None
    seq, recorded = load_seq_for_call(inp.get("transcript_path"), inp.get("tool_use_id"))
    if seq is None:
        return None
    seq = trim_current(seq, inp.get("tool_use_id"))
    tool_input = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    ts = turn_start(seq)
    if ts is None:
        return None
    obs = obligations(seq, recs)
    ask = shown.ask_text(tool_input)
    found = []
    for ob in _checked(seq, obs, ts, report_ok=shown.step7_question(tool_input)):
        miss = shown.missing(ob, shown.visible_between(seq, ob.start + 1) + [ask])
        if miss:
            found.append((ob, miss))
    under, over = _split(seq, found)
    if under and not recorded:
        warn("transcript에 지금 질문이 기록되지 않아(같은 응답의 앞 글이 빠졌을 수 있다) 거부하지 않는다")
        return None
    if under:
        name = inp.get("tool_name")
        return _deny("\n\n".join(reason(ob, miss, deny=True, retry=is_retry(seq, ob.key, name, tool_input, ob.start))
                                  for ob, miss in under))
    over = [(ob, m) for ob, m in over if ob.start >= ts]
    return {"systemMessage": capped_message([ob for ob, _ in over])} if over else None


def _approval_point(seq, start: int) -> int | None:
    """화면 뒤 마지막 질문(거부되지 않은) 또는 실제 사용자 입력의 순번."""
    for i in range(len(seq) - 1, start, -1):
        e = seq[i]
        if shown._live_ask(e) or (e["kind"] == "user" and not e["meta"] and not e["feedback"]):
            return i
    return None


def _pick(seq, recs, obs, kind: str, h: str | None):
    """승인할 의무: 해시(앞부분)가 맞는 것, 해시가 변수면 push는 마지막 stage 실행 뒤에 기록된(같은 key 다시 기록 포함) 것 중
    마지막(stage가 approved_hash를 비우므로 그 앞 화면은 승인 근거가 아니다), post는 마지막. 없으면 None."""
    cands = [ob for ob in obs if ob.kind == kind]
    if h:
        cands = [ob for ob in cands if ob.key.split(":", 1)[1].startswith(h) or h.startswith(ob.key.split(":", 1)[1])]
    elif kind == "push":
        staged = max((r["at"] for _, r in shown.anchor(seq, recs) if r.get("kind") == "close" and r.get("by") == "stage"),
                     default="")
        cands = [ob for ob in cands if ob.extra.get("last_at", "") > staged]
    return cands[-1] if cands else None


def mode_pre_bash(inp) -> dict | None:
    tool_input = inp.get("tool_input") if isinstance(inp.get("tool_input"), dict) else {}
    cmd = str(tool_input.get("command") or "")
    if "db_pr" not in cmd and "issue_post" not in cmd:
        return None
    import guard   # 규칙 7과 같은 낱말 그물(① M-2) — 표준 라이브러리 부분만 쓴다
    pub, app, stage = (guard.word_net(cmd), guard.word_net(cmd, "issue_post", "approve"),
                       guard.word_net(cmd, "db_pr", "stage"))
    if not (pub or app or stage):
        return None
    recs = load_records(inp.get("transcript_path"))
    if not recs:
        return None
    seq, recorded = load_seq_for_call(inp.get("transcript_path"), inp.get("tool_use_id"))
    if seq is None:
        return None
    seq = trim_current(seq, inp.get("tool_use_id"))
    every = shown.record_obligations(seq, recs)
    found, texts = [], []
    targets = []
    if pub:
        a = shown.APPROVED_ARG.search(cmd)
        targets.append(("push", a.group(1) if a else None))
    if app:
        s = shown.SHA_ARG.search(cmd)
        targets.append(("post", s.group(1) if s else None))
    for kind, h in targets:
        ob = _pick(seq, recs, every, kind, h)
        if ob is None:
            continue     # 기록에 맞는 화면이 없다: 스크립트의 해시 대조와 규칙 7 ask가 관문
        at = _approval_point(seq, ob.start)
        miss = shown.uncovered(ob.lines, shown.visible_between(seq, ob.start + 1, len(seq) if at is None else at + 1))
        if miss:
            found.append((ob, miss))
            texts.append(approval_reason)
    if stage:
        for ob in every:
            if ob.kind == "draft" and ob.open and not shown.draft_all_clear(ob.rules):
                miss = shown.missing(ob, shown.visible_between(seq, ob.start + 1))
                if miss:
                    found.append((ob, miss))
                    texts.append(stage_reason)
    fmt = {id(ob): f for (ob, _), f in zip(found, texts)}
    under, over = _split(seq, found)
    if under and not recorded:
        warn("transcript에 지금 명령이 기록되지 않아(같은 응답의 앞 글이 빠졌을 수 있다) 거부하지 않는다")
        return None
    if under:
        return _deny("\n\n".join(fmt[id(ob)](ob, miss, is_retry(seq, ob.key, "Bash", tool_input, ob.start))
                                 for ob, miss in under))
    if over:
        return {"systemMessage": capped_message([ob for ob, _ in over])}
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
    cmd = str(tool_input.get("command") or "")
    names = {n for n in RECORD_SCRIPTS if re.search(rf"(?<![\w-]){n}(?![\w-])", cmd)}
    if not names:
        return None
    now = time.time()
    found: dict[str, tuple] = {}
    for r in shown.read_records(work_dirs()):
        t = shown._epoch(r.get("at"))
        if t is None or now - t > POST_WINDOW or not ({r.get("script"), r.get("via")} & names):
            continue
        kind = r.get("kind")
        if kind in ("push", "post"):
            found[kind] = (KIND_NAME[kind], f"전문({len(shown.screen_lines(str(r.get('block') or '')))}줄)", "승인 질문")
        elif kind == "draft" and r.get("rules") and not shown.draft_all_clear(r["rules"]):  # 전부 통과 표는 화면으로 갈음
            found[kind] = (KIND_NAME[kind], f"규칙마다 한 행({len(r['rules'])}행, 통과가 아니면 사유)", "질문")
        elif kind == "report" and (r.get("lines") or r.get("must_show")):
            n = len(r.get("lines") or []) + len(r.get("must_show") or [])
            found[kind] = (KIND_NAME[kind], f"결정적 줄과 must_show({n}줄)", "Step 7 질문")
        elif kind == "patch" and r.get("lines"):
            found[kind] = (KIND_NAME[kind], f"출력 줄 전부({len(r['lines'])}줄)", "다음 질문")
    if not found:
        return None
    saved = _persisted(inp.get("tool_response"), _response_text(inp.get("tool_response")))
    if saved is not None:       # 출력이 길어 파일로 남고 모델에는 일부만 보인다: 줄 수 대신 그 파일
        where = saved or "원래 명령의 출력 파일"
        parts = [f"{NOTE} — 이 출력({name})은 잘려 보였고 사용자에게도 안 보인다. 전문은 {where}에 있다 — 그 파일을 읽어 "
                 f"{what}을 글자 그대로 다음 메시지에 붙이고, 같은 메시지 끝에 {ask}을 한다. 빠지면 hook이 되돌린다."
                 for name, what, ask in found.values()]
    else:
        parts = [f"{NOTE} — 이 출력({name})은 사용자에게 안 보인다. 다음 메시지에 {what}을 글자 그대로 붙이고, 같은 메시지 "
                 f"끝에 {ask}을 한다. 빠지면 hook이 되돌린다." for name, what, ask in found.values()]
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
