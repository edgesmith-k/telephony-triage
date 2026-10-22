"""'사용자에게 보였다' 판정 — 확인 화면·리포트·초안 검증표 (08-safety.md "표시 보조 hook", tests/skill_evals/README.md).

런타임(표시 보조 hook `show_guard.py`·기록을 쓰는 스크립트·`tools/hook_replay.py`)이 쓰는 것만 둔다: "보였다" 비교, 표시 기록
`<work_dir>/.shown/log.jsonl`의 쓰기·읽기(`record`·`read_records`), 기록을 transcript의 Bash 호출에 시각으로 고정(`anchor`)해
의무를 만드는 `record_obligations`. hook은 도구 출력·명령 모양으로 "화면이 나왔다"를 추론하지 않는다(L R). 그 추론은 eval 채점기
전용 `tests/skill_evals/shown_infer.py`로 옮겼다 — hook = 기록, 채점기 = 추론, 독립된 두 판정. 표준 라이브러리만 쓴다(hook은
의존성 없이 돌아야 한다).

보인 글 = assistant 텍스트 + 질문 도구(`AskUserQuestion`, 모의 `mcp__<server>__ask_user`)의 질문 문구. Bash·Read 출력은 사용자에게
보이지 않는다. 스크립트 출력(확인 화면·리포트·초안 검증 결과)의 줄마다 정규화(`norm_line`)한 뒤, 보인 글을 같은 방식으로 정규화한
것의 부분 문자열이면 보인 줄이다. 요약·재서술은 빠진 줄로 남는다. show_guard가 거부한 질문(`denied`)은 사용자에게 가지 않았으므로
보인 글도 질문도 아니다.

입력 seq(`parse_events`): `{kind: "text", text}` | `{kind: "tool", id, name, input, result, error, ts, rts}`(ts·rts = tool_use·tool_result 줄의 transcript `timestamp`, stream-json은 None) | (include_user)
`{kind: "user", text, feedback, meta}`. stream-json 실행 기록(eval `events.jsonl`)과 Claude Code transcript JSONL(블록마다 한 항목,
실제 사용자 입력은 문자열 content, Stop hook 피드백은 `isMeta`)을 모두 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MARKER = "[telephony-triage] show-guard"
MARKER_RE = re.compile(re.escape(MARKER) + r" (\S+)")
APPROVED_ARG = re.compile(r"--approved[= ]\s*[\"']?([0-9a-f]{7,64})\b")
SHA_ARG = re.compile(r"--sha[=\s]+[\"']?([0-9a-f]{64})")
STEP7_OPTS = ("기록하지 않음", "원인 미확정", "새 원인", "새 유형", "다른 기존 원인")
REPORT_CORE = re.compile(r"^- (분류 후보|근거 로그|로그 범위|오류·거부·타임아웃|실패 스텝|분석 전용|재분석|설명 기반)")
STATUS_TOKENS = {"pass": r"pass|통과|✅", "fail": r"fail|실패|❌", "skipped": r"skipped|건너뜀|해당 없음|생략",
                 "needs-approval": r"needs-approval|승인 필요"}


def norm_line(line: str, *, bullets: bool = False) -> str:
    """비교용 한 줄: 앞뒤 공백·인용 표시(>)를 떼고, `|`가 2개 이상이면 칸마다 공백을 떼어 `|`로 잇고(바깥 `|`는 버림),
    공백을 하나로 줄인다. bullets면 앞의 `- `·`* `와 굵게(`**`)도 뗀다(리포트 줄)."""
    s = re.sub(r"^(?:>\s*)+", "", line.strip())
    if s.count("|") >= 2:
        s = s.removeprefix("|").removesuffix("|")
        s = "|".join(c.strip() for c in s.split("|"))
    if bullets:
        s = re.sub(r"^[-*]\s+", "", s).replace("**", "")
    return re.sub(r"\s+", " ", s).strip()


def screen_lines(block: str) -> list[str]:
    """확인 화면의 비교할 줄: 빈 줄·코드 울타리(```)·표 구분선·`---`를 뺀 정규화 줄."""
    out = []
    for line in block.splitlines():
        n = norm_line(line)
        if n and not re.fullmatch(r"`{3,}\S*", n) and not re.fullmatch(r"[-|: ]+", n):
            out.append(n)
    return out


def uncovered(lines, chunks, *, bullets: bool = False) -> list[str]:
    """보인 글(chunks)에 없는 줄(정규화 후 부분 문자열 비교). 3글자 이하 줄은 보인 줄 하나와 통째로 같아야 한다."""
    shown = [norm_line(ln, bullets=bullets) for c in chunks for ln in str(c).splitlines()]
    hay, whole = "\n".join(shown), set(shown)

    def seen(line):
        n = norm_line(line, bullets=bullets)
        return n in whole if len(n) <= 3 else n in hay
    return [ln for ln in lines if not seen(ln)]


def report_core(text: str) -> list[str]:
    """리포트의 결정적 줄: `REPORT_CORE` 최상위 줄과 그 아래 `  - ` 하위 줄. TODO(LLM)이 든 줄은 뺀다."""
    out, keep = [], False
    for line in text.splitlines():
        if REPORT_CORE.match(line):
            keep = "TODO(LLM)" not in line
            out += [line] if keep else []
        elif keep and line.startswith("  - "):
            out += [line] if "TODO(LLM)" not in line else []
        else:
            keep = False
    return out


# --- 실행 기록 읽기 ---------------------------------------------------------------------------------------

def _block_text(body) -> str:
    if isinstance(body, list):
        return "\n".join(str(b.get("text", "")) for b in body if isinstance(b, dict))
    return str(body or "")


def parse_events(lines, include_user: bool = False, skip_sidechain: bool = True) -> list[dict]:
    """실행 기록 줄(JSON 문자열 또는 dict)을 순서대로 seq로. tool_use는 id가 같은 tool_result와 짝지어 result·error를 채운다.
    include_user면 사용자 입력도 `{kind: "user", text, feedback, meta}`로 넣는다(tool_result가 아닌 user 항목: 문자열 content
    또는 text 블록). feedback = Stop hook 피드백(`Stop hook feedback:`로 시작), meta = `isMeta`(스킬 본문 주입·피드백 등).
    skip_sidechain이면 하위 에이전트 항목(`isSidechain`, stream-json `parent_tool_use_id`)을 뺀다."""
    out, by_id = [], {}
    for raw in lines:
        if isinstance(raw, dict):
            ev = raw
        else:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
        if not isinstance(ev, dict):
            continue
        if skip_sidechain and (ev.get("isSidechain") or ev.get("parent_tool_use_id")):
            continue
        typ = ev.get("type")
        msg = ev.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if typ == "user" and include_user and isinstance(content, str):
            out.append({"kind": "user", "text": content, "meta": bool(ev.get("isMeta")),
                        "feedback": content.lstrip().startswith("Stop hook feedback")})
            continue
        if not isinstance(content, list):
            continue
        user_text = []
        for c in content:
            if not isinstance(c, dict):
                continue
            if typ == "assistant" and c.get("type") == "tool_use":
                e = {"kind": "tool", "id": c.get("id"), "name": c.get("name") or "", "input": c.get("input") or {},
                     "result": "", "error": False, "ts": ev.get("timestamp"), "rts": None}
                if not isinstance(e["input"], dict):
                    e["input"] = {}
                out.append(e)
                if e["id"]:
                    by_id[e["id"]] = e
            elif typ == "assistant" and c.get("type") == "text":
                out.append({"kind": "text", "text": str(c.get("text") or "")})
            elif typ == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                by_id[c["tool_use_id"]].update(result=_block_text(c.get("content")), error=bool(c.get("is_error")),
                                               rts=ev.get("timestamp"))
            elif typ == "user" and c.get("type") == "text":
                user_text.append(str(c.get("text") or ""))
        if include_user and user_text:
            text = "\n".join(user_text)
            out.append({"kind": "user", "text": text, "meta": bool(ev.get("isMeta")),
                        "feedback": text.lstrip().startswith("Stop hook feedback")})
    return out


def is_ask(name) -> bool:
    """사용자에게 묻는 도구: Claude Code `AskUserQuestion`, 모의 `mcp__<server>__ask_user`(eval)."""
    name = str(name or "")
    return name == "AskUserQuestion" or name.endswith("__ask_user")


def ask_text(tool_input) -> str:
    """질문 도구 입력에서 사용자에게 보이는 글. 모의 ask_user는 `question`, AskUserQuestion은 `questions[]`의
    header·question·options[].label·description(형식은 대화형에서만 확인 가능 — 모르는 모양은 문자열 값만 모은다)."""
    if not isinstance(tool_input, dict):
        return str(tool_input or "")
    if isinstance(tool_input.get("question"), str):
        return tool_input["question"]
    parts = []
    qs = tool_input.get("questions")
    for q in qs if isinstance(qs, list) else []:
        if isinstance(q, str):
            parts.append(q)
            continue
        if not isinstance(q, dict):
            continue
        for k in ("header", "question"):
            if isinstance(q.get(k), str):
                parts.append(q[k])
        for o in q.get("options") or [] if isinstance(q.get("options"), list) else []:
            if isinstance(o, str):
                parts.append(o)
            elif isinstance(o, dict):
                parts += [str(o[k]) for k in ("label", "description") if isinstance(o.get(k), str)]
    if not parts:
        parts = [v for v in tool_input.values() if isinstance(v, str)]
    return "\n".join(parts)


def denied(e) -> bool:
    """show_guard가 거부한 도구 호출(결과에 표식이 있고, 오류이거나 `PreToolUse:`로 시작 — 거부 결과는
    `PreToolUse:<tool> hook error: <reason>`, is_error): 사용자에게 가지 않았다."""
    if e.get("kind") != "tool":
        return False
    res = str(e.get("result") or "")
    return MARKER in res and (bool(e.get("error")) or res.lstrip().startswith("PreToolUse:"))


# 질문이 사용자에게 가지 않은 오류 결과: 모의 ask_user의 선택지 상한 거부, 실제 AskUserQuestion의 입력 스키마 오류(선택지 5개 이상 등)
ASK_REJECTED = ("선택지는 질문당 4개까지", "InputValidationError")


def _live_ask(e) -> bool:
    """사용자에게 간 질문: show_guard가 거부하지 않았고, 선택지 상한·스키마 오류로 거부되지도 않았다."""
    if not (e.get("kind") == "tool" and is_ask(e.get("name"))) or denied(e):
        return False
    res = str(e.get("result") or "")
    return not (e.get("error") and any(t in res for t in ASK_REJECTED))


def visible_between(seq, start: int = 0, end: int | None = None) -> list[str]:
    """seq[start:end]에서 사용자에게 보인 글(assistant 텍스트·질문 문구, 거부된 질문 제외)을 순서대로."""
    out = []
    for e in seq[max(start, 0):len(seq) if end is None else end]:
        if e["kind"] == "text":
            out.append(e["text"])
        elif _live_ask(e):
            out.append(ask_text(e["input"]))
    return out


def step7_question(tool_input) -> bool:
    """Step 7 분류 질문: 선택지 중 2개 이상이 든 질문."""
    opts = tool_input.get("options") if isinstance(tool_input, dict) else None
    q = ask_text(tool_input) + " " + " ".join(map(str, opts if isinstance(opts, list) else []))
    return sum(o in q for o in STEP7_OPTS) >= 2


def draft_rows_missing(rules, visible_lines) -> list[str]:
    """규칙마다 보인 행이 있는가: 그 규칙 ID만 든 줄(사유 글을 뺀 뒤)에 상태 표시가 있고, 통과가 아니면 사유도 있고 ✅가 없다.
    "R1~R4 통과"처럼 여러 규칙을 묶은 줄은 인정하지 않는다. visible_lines는 `norm_line`한 줄. → 빠진 규칙 `R3(fail: 사유)`."""
    bad = []
    for r in rules:
        rid, status = str(r["id"]), str(r.get("status"))
        token = STATUS_TOKENS.get(status, re.escape(status))
        reason = norm_line(str(r.get("reason") or ""))

        def good(line, rid=rid, status=status, token=token, reason=reason):
            rest = line.replace(reason, " ") if reason else line     # 사유가 다른 규칙 ID를 말해도 된다
            if set(re.findall(r"\bR\d\b", rest)) != {rid} or not re.search(token, line):
                return False
            return status == "pass" or ((not reason or reason in line) and "✅" not in line)
        if not any(good(ln) for ln in visible_lines):
            bad.append(f"{rid}({status}{': ' + reason[:40] if status != 'pass' and reason else ''})")
    return bad


ALL_CLEAR_SKIP = "해당 없음"


def draft_all_clear(rules) -> bool:
    """초안 검증 결과가 전부 통과다: 규칙 행이 있고, 모두 pass이거나 사유가 정확히 "해당 없음"인 skipped이며, review_required·
    allow-cause 초안이 없다(fail·needs-approval·`fixture 없음`·pending 등은 아니다). 이런 표는 stage 전에 보이지 않아도 push 확인
    화면의 "검증 결과"(승인 전 표시를 hook이 본다)로 갈음한다(10/14 사용자 결정)."""
    rows = [r for r in rules or [] if isinstance(r, dict)]
    if not rows:
        return False
    for r in rows:
        status = r.get("status")
        if r.get("review_required") or any(r.get(k) for k in r if "allow_cause" in str(k)):
            return False
        if not (status == "pass" or (status == "skipped" and str(r.get("reason") or "").strip() == ALL_CLEAR_SKIP)):
            return False
    return True


def visible_lines(chunks) -> list[str]:
    return [norm_line(ln) for c in chunks for ln in str(c).splitlines()]


# --- 표시 의무 ---------------------------------------------------------------------------------------------

@dataclass
class Obligation:
    """사용자에게 보여야 할 스크립트 출력 하나. kind push|post|report|draft|patch, key push:<hash>|post:<sha 앞 16자>|report:<id>|
    draft:<결과 해시>|patch:<KEY>/<스킬 이름>(id = 그 호출의 tool_use id 끝 12자, 없으면 seq 순번; 초안은 규칙·상태·사유의 sha1 앞
    12자). start = 출력이 나온 seq 순번, end = 창 끝(배타),
    close_kind = 창을 닫은 것(publish·discard·approve·restage·step7·stage·draft·job·end — end면 아직 열려 있다)."""
    kind: str
    key: str
    start: int
    end: int
    close_kind: str
    lines: list = field(default_factory=list)
    must_show: list = field(default_factory=list)
    rules: list = field(default_factory=list)
    block: str = ""
    path: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.close_kind == "end"

    @property
    def total(self) -> int:
        return len(self.rules) if self.kind == "draft" else len(self.lines) + len(self.must_show)


REF_TAIL = re.compile(r"\s*\(f\d+:L\d+(?:[,\s]+f\d+:L\d+)*\)\s*$")
CLOCK_EVIDENCE = "시계 이상 구간의 근거"


def _relax(line: str) -> str:
    """리포트 줄 비교용: 백틱과 줄 끝 로그 위치 참조(` (f0:L2)`·` (f0:L2, f1:L9)`)를 뗀다."""
    return REF_TAIL.sub("", str(line).replace("`", ""))


def report_uncovered(core, chunks, must_show=()) -> list[str]:
    """리포트 결정적 줄 중 보인 글에 없는 것(글머리·굵게 무시, `uncovered`). 백틱과 줄 끝 `(fN:Ln)` 참조는 양쪽에서 떼고 비교한다 —
    단 must_show에 시계 이상 구간의 근거 줄이 있으면(재정렬 기준이라 어느 줄인지가 근거다) 참조까지 그대로 본다."""
    if any(CLOCK_EVIDENCE in str(m) for m in must_show or ()):
        return uncovered(core, chunks, bullets=True)
    relaxed = ["\n".join(_relax(ln) for ln in str(c).splitlines()) for c in chunks]
    return [ln for ln in core if uncovered([_relax(ln)], relaxed, bullets=True)]


PATCH_LIST = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


def _patch_norm(line: str) -> str:
    """patch 안내 줄 비교용: 백틱·굵게를 떼고 표 칸 `|`는 공백으로, U+2212 `−`는 `-`로, 줄 앞 글머리·번호(`- `·`1. `)를 뗀 뒤
    공백을 하나로."""
    s = re.sub(r"^(?:>\s*)+", "", str(line).strip()).replace("`", "").replace("**", "").replace("|", " ").replace("\u2212", "-")
    return re.sub(r"\s+", " ", PATCH_LIST.sub("", s.strip())).strip()


def patch_uncovered(lines, chunks) -> list[str]:
    """스킬 제안 patch 안내 줄(`skill_patch.py`) 중 보인 글에 없는 것: 양쪽을 `_patch_norm`한 부분 문자열 비교(경로를 코드
    표시로 감싸도, 줄 수를 표 행·번호 목록·글머리 없이·ASCII `-`로 써도 같은 줄) — 그 밖은 글자 그대로."""
    hay = "\n".join(_patch_norm(ln) for c in chunks for ln in str(c).splitlines())
    return [ln for ln in lines if _patch_norm(ln) not in hay]


def missing(ob: Obligation, chunks) -> list[str]:
    """ob의 빠진 것: 화면 줄 / 리포트 결정적 줄(글머리·굵게 무시) + 글자 그대로 없는 must_show / 보인 행이 없는 규칙 /
    patch 안내 줄(글머리·굵게·백틱 무시)."""
    if ob.kind == "draft":
        return draft_rows_missing(ob.rules, visible_lines(chunks))
    if ob.kind == "patch":
        return patch_uncovered(ob.lines, chunks)
    if ob.kind == "report":
        raw = "\n".join(str(c) for c in chunks)
        return report_uncovered(ob.lines, chunks, ob.must_show) + [m for m in ob.must_show if m not in raw]
    return uncovered(ob.lines, chunks)


CAPPED = "(재시도 한도)"


# -- 표시 기록 (L R, `<work_dir>/.shown/log.jsonl`) ---------------------------------------------------------------------
# 스크립트(db_pr summary·stage·publish·discard·lock, issue_post render·approve, db_verify rules --draft, triage run, skill_patch)가 사용자에게
# 보여야 할 출력(의무)과 창을 닫는 사실(close)을 한 줄씩 남긴다. hook은 이 기록을 transcript의 Bash 호출에 시각으로 고정한다
# (`anchor`). 기록 실패는 본 작업을 막지 않는다(stderr 경고만). 형식은 contracts.md "표시 기록".

SHOWN_DIR = ".shown"
LOG_NAME = "log.jsonl"
LOCK_NAME = "log.lock"     # 회전하지 않는 잠금 파일(쓰기·회전을 한 프로세스씩)
# ponytail: 한 세대 회전(log.jsonl.1), 최대 ≈8MB. 긴 세션이 회전을 넘으면 그 앞 의무는 판정하지 않는다 — 필요하면 세대 수를 늘린다
LOG_MAX = 4 << 20
READ_TAIL = 2 << 20
# ponytail: probe 13 — PreToolUse 시점에 지금 tool_use 줄은 아직 없고 0.25초 안에 기록된다. 사내 probe 15로 조정할 손잡이
ANCHOR_SLACK = 2.0


def now_iso() -> str:
    """UTC 밀리초, transcript `timestamp`와 같은 모양(`2026-10-16T03:12:45.123Z`)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _epoch(s) -> float | None:
    """ISO 시각 → epoch 초. `Z`는 3.10 `fromisoformat`이 못 읽어 바꾼다. 못 읽으면 None."""
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).timestamp()


def draft_key(tag: str, rules) -> str:
    """초안 검증 의무 키: 계획 태그(<plan 부모 폴더>/<plan 파일>)와 규칙·상태·사유의 sha1 앞 12자."""
    return "draft:" + hashlib.sha1(json.dumps([tag] + [[r.get("id"), r.get("status"), r.get("reason")] for r in rules],
                                              ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


@contextmanager
def _locked(path: Path, wait: float = 10.0):
    """`path`의 첫 바이트에 배타 잠금(`dbpr/lock.py` guard와 같은 방식: Windows `msvcrt.locking`, POSIX `fcntl.lockf` — NFS에서도
    POSIX 잠금). 잡힐 때까지 0.02초마다 다시, `wait`초가 지나면 OSError."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.02)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.lockf(fd, fcntl.LOCK_UN, 1, 0)
    finally:
        os.close(fd)


def record(work_dir, script: str, kind: str, job: str, **fields) -> bool:
    """`<work_dir>/.shown/log.jsonl`에 기록 하나를 append(폴더 0o700, 4MB 넘으면 한 세대 회전). 실패하면 stderr 경고만 하고
    False — 종료 코드·stdout은 호출한 스크립트 그대로.

    close 기록을 잃으면 hook이 닫힌 창을 열린 것으로 보고 거짓 거부한다(②b). 그래서: 회전 확인과 쓰기를 `.shown/log.lock`
    배타 잠금 안에서 한다(Windows의 `O_APPEND`는 CRT가 끝으로 옮긴 뒤 쓰는 흉내라 프로세스 사이에 원자적이지 않다, NFS도 같다).
    `O_APPEND` fd에 `os.write` 한 번(기록마다 한 호출, 재시도 없음, 짧게 쓰이면 실패)으로 쓰고, 앞에 줄바꿈을 붙여
    (`"\\n" + line + "\\n"`) 앞 기록의 찢긴 끝 줄(중단)에 붙지 않게 한다 — 읽는 쪽은 빈 줄·깨진 줄을 건너뛴다. 회전 실패(Windows
    공유 위반 등)는 무시하고 지금 파일에 쓴다. 잠금을 10초 안에 못 잡으면 경고만 한다."""
    try:
        d = Path(work_dir) / SHOWN_DIR
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
        log = d / LOG_NAME
        # via = 이 프로세스를 띄운 스크립트(`triage.py run`이 db_pr lock을 in-process로 부르면 script는 db_pr, via는 triage):
        # hook은 via 이름이 든 Bash 호출에도 고정한다(파일럿 eval 2·67의 close by lock)
        entry = Path(sys.argv[0]).stem if sys.argv and str(sys.argv[0]).endswith(".py") else ""
        via = {"via": entry} if entry and entry != script else {}
        data = ("\n" + json.dumps({"v": 1, "at": now_iso(), "script": script, "kind": kind, "job": job, **via, **fields},
                                  ensure_ascii=False) + "\n").encode("utf-8")
        with _locked(d / LOCK_NAME):
            try:
                if log.stat().st_size > LOG_MAX:
                    os.replace(log, d / (LOG_NAME + ".1"))
            except OSError:
                pass
            fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
            try:
                if os.write(fd, data) != len(data):
                    raise OSError("short write")
            finally:
                os.close(fd)
        return True
    except (OSError, TypeError, ValueError) as exc:
        print(f"[telephony-triage] 표시 기록을 쓰지 못함({kind}: {type(exc).__name__}) — 표시 보조 hook이 이 출력을 보지 않는다",
              file=sys.stderr)
        return False


def _tail_lines(path: Path, budget: int) -> list[str]:
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - budget))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").split("\n")
    return lines[1:] if size > budget else lines     # 잘린 첫 줄은 버린다


def read_records(work_dirs) -> list[dict]:
    """work_dir마다 기록 끝 `READ_TAIL`(지금 파일이 작으면 남은 만큼 회전된 `.1`의 끝까지)을 읽어 `at` 순으로. JSON이 아닌
    줄(동시 append로 섞인 줄)은 건너뛴다."""
    out = []
    for w in dict.fromkeys(str(w) for w in work_dirs):
        d = Path(w) / SHOWN_DIR
        cur = d / LOG_NAME
        try:
            size = cur.stat().st_size if cur.is_file() else 0
        except OSError:
            size = 0
        lines = _tail_lines(d / (LOG_NAME + ".1"), READ_TAIL - size) if size < READ_TAIL else []
        lines += _tail_lines(cur, READ_TAIL) if size else []
        for raw in lines:
            try:
                r = json.loads(raw)
            except ValueError:
                continue
            if isinstance(r, dict) and isinstance(r.get("at"), str):
                out.append(r)
    return sorted(out, key=lambda r: r["at"])


def anchor(seq, recs) -> list[tuple[int, dict]]:
    """기록마다, 명령에 기록의 `script`나 `via`(그 스크립트를 in-process로 부른 스크립트) 이름(앞뒤가 글자·`-`가 아님 —
    `telephony-triage/`는 triage가 아니다)이 든 끝난 Bash
    호출 중 `ts − ANCHOR_SLACK ≤ at ≤ rts`인 것에서 `rts`가 가장 이른 것의 seq 순번. 고정된 (순번, 기록)만 (순번, at) 순으로 —
    못 고정한 기록(다른 세션·하위 에이전트·아직 끝나지 않은 호출·백그라운드 실행·시각 없는 기록)은 뺀다."""
    calls = []
    for i, e in enumerate(seq):
        if e.get("kind") == "tool" and e.get("name") == "Bash":
            ts, rts = _epoch(e.get("ts")), _epoch(e.get("rts"))
            if ts is not None and rts is not None:
                calls.append((i, ts, rts, str((e.get("input") or {}).get("command", ""))))
    out = []
    for r in recs:
        at, names = _epoch(r.get("at")), [str(n) for n in (r.get("script"), r.get("via")) if n]
        if at is None or not names:
            continue
        name = re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, names)) + r")(?![\w-])")
        best = min(((rts, i) for i, ts, rts, cmd in calls if ts - ANCHOR_SLACK <= at <= rts and name.search(cmd)),
                   default=None)
        if best is not None:
            out.append((best[1], r))
    return sorted(out, key=lambda x: (x[0], x[1]["at"]))


def _content(kind, r):
    """의무 내용(같은 key라도 다르면 다른 화면): push·post = 화면 전문, report = 결정적 줄·must_show, draft = 규칙(key에 든다),
    patch = 안내 줄."""
    if kind == "report":
        return r.get("lines"), r.get("must_show")
    if kind == "patch":
        return r.get("lines")
    return r.get("rules") if kind == "draft" else screen_lines(str(r.get("block") or ""))   # 줄 끝·빈 줄 차이는 같은 화면


def _obligation(kind, key, i, n, r):
    """기록 하나의 의무(start i, 열린 창 끝 n). 보일 줄이 없는 리포트면 None."""
    extra = {"last_at": r["at"], "job": r.get("job"), "plan": r.get("plan"), "rec": r}
    if kind in ("push", "post"):
        block = str(r.get("block") or "")
        return Obligation(kind, key, i, n, "end", lines=screen_lines(block), block=block, extra=extra)
    if kind == "patch":
        lines = [str(x) for x in r.get("lines") or [] if str(x).strip()]
        return Obligation(kind, key, i, n, "end", lines=lines, block="\n".join(lines), path=r.get("path"),
                          extra=extra) if lines else None
    if kind == "report":
        lines, must = [str(x) for x in r.get("lines") or []], [str(x) for x in r.get("must_show") or []]
        if not (lines or must):
            return None
        return Obligation(kind, key, i, n, "end", lines=lines, must_show=must,
                          block="\n".join(lines + [m for m in must if m not in lines]), path=r.get("path"), extra=extra)
    rules = [x for x in r.get("rules") or [] if isinstance(x, dict) and x.get("id")]
    return Obligation(kind, key, i, n, "end", rules=rules, block=_draft_block(rules), extra=extra)


def _draft_block(rules) -> str:
    return "\n".join(f"| {r.get('id')} | {r.get('status')} | {norm_line(str(r.get('reason') or ''))} |" for r in rules)


def record_obligations(seq, recs) -> list[Obligation]:
    """표시 의무(show_guard): 기록을 고정(`anchor`)한 순서로 창을 연다. 작업 키와 무관하게 순서로만 닫는다. start = 기록을 쓴
    Bash 호출의 순번, end = 닫은 기록의 고정 순번(Step 7 질문이면 질문 다음), 열려 있으면 len(seq)·`end`.

    | 의무 | 닫힘 |
    | push | key가 다른 push(restage) · close publish·discard |
    | post | key가 다른 post(restage) · close approve |
    | report(lines·must_show가 있을 때) | 다른 report(restage) · close stage · 고정 뒤 거부되지 않은 Step 7 질문(step7) |
    | draft | 같은 job·plan의 key가 다른 draft(draft — 전부 통과 표는 어느 draft로도) · close stage(stage)·discard·lock·report 기록(job) |
    | patch(lines가 있을 때) | 같은 key(작업·스킬 이름)의 내용이 다른 기록만(새 의무) — 다른 key·close로 닫히지 않는다(턴이 끝나면 Stop·질문이 보지 않는다) |

    같은 key의 뒤 기록은 새 의무가 아니다: 첫 기록의 창을 그대로 쓴다(열려 있으면 열린 채, 닫혔으면 닫힌 채) — `extra["last_at"]`만
    뒤 기록 시각으로. 단 열린 창의 내용(화면 전문·리포트 줄)이 바뀌었거나 그 창이 다른 화면·초안에 밀려 닫혔었으면 앞 의무를
    버리고 새 의무를 연다(같은 트리 해시, 다른 커밋 메시지 / A→B→A). publish·stage 등으로 닫힌 창에 내용이 다른 같은 key가 오면
    닫힌 채 두되 내용·start를 새 기록으로 바꾼다(pre-bash 승인 판정은 새 화면으로). 기록에 규칙 전체가 있으므로 같은 계획을 덜 보이게 다시 돌린 출력은 따질 것이 없다. close 기록은 스크립트가
    실제로 실행됐을 때만 남으므로 hook이 거부한(사용자가 거절한) 호출은 창을 닫지 않는다."""
    out: list[Obligation] = []
    by_key: dict[str, Obligation] = {}

    def shut(ob, i, why):
        ob.end, ob.close_kind = i, why

    for i, r in anchor(seq, recs):
        kind, live = r.get("kind"), [ob for ob in out if ob.open]
        if kind == "close":
            by = r.get("by")
            for ob in live:
                if (ob.kind == "push" and by in ("publish", "discard")) or (ob.kind == "post" and by == "approve"):
                    shut(ob, i, by)
                elif ob.kind == "report" and by == "stage":
                    shut(ob, i, "stage")
                elif ob.kind == "draft" and by in ("stage", "discard", "lock"):
                    shut(ob, i, "stage" if by == "stage" else "job")
            continue
        key = str(r.get("key") or "")
        if kind not in ("push", "post", "report", "draft", "patch") or not key:
            continue
        old = by_key.get(key)
        if old is not None:
            # 같은 key는 첫 창 그대로(열린 채, publish·stage 등으로 닫혔으면 닫힌 채 — J-d·J-e). 단 다른 화면에 밀려 닫혔다가
            # 돌아왔거나(A→B→A — 사용자가 마지막에 본 것은 B) 열린 창의 내용이 바뀌었으면(push key는 트리 해시라 커밋 메시지·
            # PR 제목·리뷰어가 달라도 같다) 새 의무다: 새 화면을 그 기록 뒤에 다 보여야 한다
            pushed_out = old.close_kind in ("restage", "draft")
            same = _content(kind, r) == _content(old.kind, old.extra["rec"])
            if not pushed_out and (same or not old.open):
                old.extra["last_at"] = r["at"]
                new = None if same else _obligation(kind, key, i, len(seq), r)
                if new is not None:    # publish·stage 등으로 닫힌 창(J-e): 닫힌 채(Stop은 안 본다) 두되 승인 판정(pre-bash)은
                    # 새 화면으로, 그 기록 뒤부터 본다(같은 트리를 다른 커밋 메시지로 다시 stage한 뒤 publish)
                    new.end, new.close_kind = i, old.close_kind
                    out.remove(old)
                    out.append(new)
                    by_key[key] = new
                continue
            out.remove(old)
            live = [ob for ob in out if ob.open]
        for ob in live:
            if ob.kind == kind and kind not in ("draft", "patch"):
                shut(ob, i, "restage")
            elif kind == "draft" and ob.kind == "draft" and (
                    draft_all_clear(ob.rules) or (ob.extra.get("job"), ob.extra.get("plan")) == (r.get("job"), r.get("plan"))):
                shut(ob, i, "draft")
            elif kind == "report" and ob.kind == "draft":
                shut(ob, i, "job")
        ob = _obligation(kind, key, i, len(seq), r)
        if ob is None:      # 보일 줄이 없는 리포트·patch: 의무는 없고 앞 의무를 닫기만 한다
            continue
        by_key[key] = ob
        out.append(ob)
    for ob in out:
        if ob.kind == "report":
            j = next((j for j in range(ob.start + 1, ob.end if not ob.open else len(seq))
                      if _live_ask(seq[j]) and step7_question(seq[j]["input"])), None)
            if j is not None:
                shut(ob, j + 1, "step7")
    return out
