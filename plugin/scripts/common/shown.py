"""'사용자에게 보였다' 판정 — 확인 화면·리포트·초안 검증표 (08-safety.md "표시 보조 hook", tests/skill_evals/README.md).

eval 채점기(`tests/skill_evals/grade.py`)와 표시 보조 hook(`show_guard.py`)이 같은 판정을 쓰도록 한곳에 둔다. 표준 라이브러리만
쓴다(hook은 의존성 없이 돌아야 한다).

보인 글 = assistant 텍스트 + 질문 도구(`AskUserQuestion`, 모의 `mcp__<server>__ask_user`)의 질문 문구. Bash·Read 출력은 사용자에게
보이지 않는다. 스크립트 출력(확인 화면·리포트·초안 검증 결과)의 줄마다 정규화(`norm_line`)한 뒤, 보인 글을 같은 방식으로 정규화한
것의 부분 문자열이면 보인 줄이다. 요약·재서술은 빠진 줄로 남는다. show_guard가 거부한 질문(`denied`)은 사용자에게 가지 않았으므로
보인 글도 질문도 아니다.

입력 seq(`parse_events`): `{kind: "text", text}` | `{kind: "tool", id, name, input, result, error}` | (include_user)
`{kind: "user", text, feedback, meta}`. stream-json 실행 기록(eval `events.jsonl`)과 Claude Code transcript JSONL(블록마다 한 항목,
실제 사용자 입력은 문자열 content, Stop hook 피드백은 `isMeta`)을 모두 읽는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MARKER = "[telephony-triage] show-guard"
MARKER_RE = re.compile(re.escape(MARKER) + r" (\S+)")

_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?^\s*\2\s*$", re.DOTALL | re.MULTILINE)


def strip_heredocs(cmd: str) -> str:
    """heredoc 본문(실행자가 transcript·commands.md를 쓰는 글)은 실행한 명령이 아니다."""
    return _HEREDOC_RE.sub("<<heredoc", cmd)


PUSH_SCREEN = re.compile(r"^## push 전 확인:.*?^approved_hash: [0-9a-f]{7,64}[ \t]*$", re.DOTALL | re.MULTILINE)
POST_SCREEN = re.compile(r"^## \S+ 게시 전 확인:.*?^post_sha256: [0-9a-f]{64}[ \t]*$", re.DOTALL | re.MULTILINE)
SCREEN_HEAD = {"push": re.compile(r"^## push 전 확인:", re.MULTILINE), "post": re.compile(r"^## \S+ 게시 전 확인:", re.MULTILINE)}
# 실행한 호출만 센다: 스크립트 경로가 명령어 자리(줄·`;`·`&`·`|`·`(`·`$(` 뒤, 앞의 `VAR=값` 허용, 또는 `python3 [-옵션]` 뒤)에
# 있어야 한다. 앞 경로는 `/`나 `}`로 끝나야 한다(`${S}db_pr.py` — `S="python3 /…/scripts/"`로 묶은 호출, E67).
# `grep -n "db_pr.py publish" write-flow.md`처럼 인자·인용 글 안의 이름은 호출이 아니다(`command_of`가 공백이 든
# 인용 글을 미리 지운다). 하위 명령은 스크립트 바로 뒤(앞 전역 옵션 `--plugin-root X`·`--platform X`·`--x`는 건너뜀)만 본다:
# `…; cat $W/stage.json`·`> discard-preview.md`는 하위 명령이 아니다. 인용 밖 줄 이음(`\` + 줄바꿈)은 공백으로 본다(`strip_quoted`).
CMDWORD = (r"(?:(?:^|[;&|(`\n]|\$\()\s*(?:\w+=\S*\s+)*|\bpython3?(?:\.\d+)?(?:\s+-[^\s-]\S*)*\s+)"
           r"[\"']?(?:[^\s\"';&|()`]*[/}])?")
SUB = r"[\"']?\s+(?:--(?:plugin-root|platform|db)\s+\S+\s+|--\S+\s+)*"


def script_rx(script: str, tail: str) -> re.Pattern:
    """`script`(파일 이름)를 실행하고 하위 명령이 tail인 호출."""
    return re.compile(CMDWORD + re.escape(script) + SUB + tail, re.MULTILINE)


PUSH_END = script_rx("db_pr.py", r"(publish|discard)\b")   # `publish … --and-discard`는 publish다
POST_END = script_rx("issue_post.py", r"(approve)\b")
STAGE = script_rx("db_pr.py", r"stage\b")
RENDER = script_rx("issue_post.py", r"render\b")
SUMMARY = script_rx("db_pr.py", r"summary\b")
TRIAGE_RUN = script_rx("triage.py", r"run\b")
JOB_END = script_rx("db_pr.py", r"(?:discard|lock\s+(?:acquire|release))\b")   # 작업 경계(초안 표 창, `draft_end`)
DRAFT = script_rx("db_verify.py", r"rules\b[^|\n;&]*--draft\b")
APPROVED_ARG = re.compile(r"--approved[= ]\s*[\"']?([0-9a-f]{7,64})\b")
SHA_ARG = re.compile(r"--sha[=\s]+[\"']?([0-9a-f]{64})")
STEP7_OPTS = ("기록하지 않음", "원인 미확정", "새 원인", "새 유형", "다른 기존 원인")
REPORT_CORE = re.compile(r"^- (분류 후보|근거 로그|로그 범위|오류·거부·타임아웃|실패 스텝|분석 전용|재분석|설명 기반)")
REPORT_HEAD = re.compile(r"^## \S+ 분석$", re.MULTILINE)
STATUS_TOKENS = {"pass": r"pass|통과|✅", "fail": r"fail|실패|❌", "skipped": r"skipped|건너뜀|해당 없음|생략",
                 "needs-approval": r"needs-approval|승인 필요"}
SEE_ABOVE = re.compile(r"위\s*(출력|확인 화면|화면|본문)")


def command_of(e) -> str:
    """seq 도구 항목의 Bash 명령(비교용): heredoc 본문을 빼고 공백이 든 인용 글을 `""`로 지운다(`strip_quoted`, 줄 이음도
    거기서 공백으로 바꾼다). 결과는 항목에 `_cmd`로 기억한다(창마다 다시 계산하지 않게)."""
    if "_cmd" not in e:
        e["_cmd"] = strip_quoted(strip_heredocs(str((e.get("input") or {}).get("command", ""))))
    return e["_cmd"]


def strip_quoted(cmd: str) -> str:
    """공백이 든 인용 글(`"…"`·`'…'`)을 `""`로 바꾼다: `grep -n "db_pr.py publish"`·`echo "…; db_pr.py publish"`의 글은
    실행한 명령이 아니다. 공백 없는 인용(`"$S/db_pr.py"`)은 경로이므로 둔다. 따옴표는 왼쪽부터 짝짓고, `"…"` 안 `\\"`는 건너뛴다.

    실제로 실행되는 인용 안 명령은 살린다: `"…"` 안의 `$(…)`·`` `…` `` 본문은 (재귀로 지운 뒤) 그 줄 끝 다음 줄로 옮겨
    명령어 자리에 두고(`R="$(python3 $S/db_pr.py publish …)"`), `sh -c`·`bash -c` 바로 뒤 인용 본문은 지우지 않고 새 줄로
    펼친다(`bash -lc`·`sh -ec`처럼 `c`로 끝나는 묶은 옵션 포함, `./run.sh -c`는 아님). 인용 밖에서 단어 첫머리의
    `#`(줄 처음·공백·`;`·`&`·`|`·`(` 뒤)부터 줄 끝까지는 주석이라 따옴표를 짝짓지 않고 `#`만 남긴다(`# user's approval` 뒤
    줄의 호출이 인용으로 먹히지 않게, 주석 안 `python3 db_pr.py publish`가 호출로 세지 않게). 인용 밖 줄 이음(`\\` +
    줄바꿈)은 공백으로 바꾸되 주석은 원래 줄바꿈에서 끝난다(`echo x # 메모 \\` 다음 줄의 호출은 실행된다).

    한계(고치지 않음, 오판 가능): `$PY $S/db_pr.py publish`처럼 변수로 든 인터프리터 뒤 호출, 하위 명령 앞 짧은 옵션
    (`db_pr.py -v publish`), 공백이 든 인용 경로(`python3 "/a b/db_pr.py" publish`)는 놓친다. 인용 없는
    `echo run python3 db_pr.py publish`는 호출로 센다(과대 일치). `$(case a in a) …;; esac)`처럼 짝 없는 `)`가 든 명령
    치환은 그 `)`에서 끝난 것으로 본다(뒷부분은 인용 글로 지워질 수 있다)."""
    out, extra, i, n = [], [], 0, len(cmd)

    def flush():
        out.extend("\n" + x for x in extra)
        extra.clear()

    while i < n:
        q = cmd[i]
        if q == "\n":
            flush()
            out.append(q)
            i += 1
            continue
        if q == "#" and (i == 0 or cmd[i - 1].isspace() or cmd[i - 1] in ";&|("):   # 주석: 줄 끝까지 건너뛴다(`#`만 남김)
            j = cmd.find("\n", i)
            i = n if j < 0 else j
            out.append("#")
            continue
        if q not in "\"'":
            k = 2 if q == "\\" else 1      # 인용 밖 `\"`·`\'`는 글자다
            out.append(" " if cmd[i:i + 2] == "\\\n" else cmd[i:i + k])   # 줄 이음은 공백
            i += k
            continue
        j = i + 1
        while j < n and cmd[j] != q:
            j += 2 if q == '"' and cmd[j] == "\\" else 1
        if j >= n:                      # 닫히지 않은 따옴표: 그대로 둔다
            out.append(cmd[i:])
            break
        body = cmd[i + 1:j]
        if not re.search(r"\s", body):
            out.append(cmd[i:j + 1])
        elif SH_C.search(_tail(out)):   # `bash -c '…'`: 본문이 명령이다
            out.append("\n" + strip_quoted(body))
        else:
            out.append('""')
            if q == '"':
                extra.extend(strip_quoted(x) for x in _subst_spans(body))
        i = j + 1
    flush()
    return "".join(out)


SH_C = re.compile(r"(?<![\w./-])(?:ba)?sh\s+-[a-zA-Z]*c\s+$")   # `bash -c`·`bash -lc`·`sh -ec` (`./run.sh -c` 아님)


def _tail(out: list[str], k: int = 64) -> str:
    """out을 이은 글의 끝 k글자(인용마다 전체를 다시 잇지 않게)."""
    s = ""
    for p in reversed(out):
        s = p + s
        if len(s) >= k:
            break
    return s[-k:]


def _subst_spans(body: str) -> list[str]:
    """`"…"` 본문 안 명령 치환(`$(…)`·`` `…` ``)의 본문들. `$(…)`는 괄호 짝을 세고 그 안 인용 글은 건너뛴다."""
    spans, i, n = [], 0, len(body)
    while i < n:
        if body[i] == "\\":
            i += 2
        elif body.startswith("$(", i):
            j, depth = i + 2, 1
            while j < n and depth:
                c = body[j]
                if c == "\\":
                    j += 1
                elif c in "\"'":
                    k = body.find(c, j + 1)
                    j = n - 1 if k < 0 else k
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                j += 1
            spans.append(body[i + 2:j - 1 if not depth else j])
            i = j
        elif body[i] == "`":
            k = body.find("`", i + 1)
            if k < 0:
                break
            spans.append(body[i + 1:k])
            i = k + 1
        else:
            i += 1
    return spans


def after_last(rx, cmd: str) -> str:
    """cmd에서 rx의 마지막 일치 뒤 부분(일치가 없으면 cmd 전체): 화면을 낸 호출 앞의 명령은 그 화면의 창 밖이다."""
    ms = list(rx.finditer(cmd))
    return cmd[ms[-1].end():] if ms else cmd


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


def draft_json(result: str):
    """초안 검증 결과를 JSON으로 읽는다: 첫 `{`~마지막 `}`가 결과 dict면 그것, 아니면 줄 첫머리 `{`에서 시작하는 JSON 객체들
    중 규칙 행(`{"id": "R4", "status": …}`, 예: 결과를 `python3 -c`로 행마다 찍은 출력)을 {"rules": […]}로. 못 읽으면 None.
    줄 첫머리만 보는 것은 잘린 결과(`| head -60`) 안의 들여쓴 규칙 행을 전체 결과로 잘못 읽지 않기 위해서다."""
    a, b = result.find("{"), result.rfind("}")
    if a >= 0 and b > a:
        try:
            doc = json.loads(result[a:b + 1])
        except ValueError:
            doc = None
        if isinstance(doc, dict) and isinstance(doc.get("rules"), list):
            return doc
    rows, pos, dec = [], 0, json.JSONDecoder()
    for m in re.finditer(r"^\{", result, re.MULTILINE):
        if m.start() < pos:
            continue
        try:
            obj, pos = dec.raw_decode(result, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("rules"), list):
            return obj
        if isinstance(obj, dict) and re.fullmatch(r"R\d", str(obj.get("id"))) and obj.get("status"):
            rows.append(obj)
    return {"rules": rows} if rows else None


def draft_doc(result: str):
    """초안 검증 결과: JSON(`draft_json`)이면 dict, 아니면 `R1 pass …`·`R4 fail: …` 줄 목록을 {"rules": […]}로. 못 읽으면 None."""
    doc = draft_json(result)
    if doc is not None:
        return doc
    rows = []
    # 요약·행마다 찍은 줄(`R4 fail: 사유`)과, 모델이 결과를 표로 찍은 줄(`| R4 | fail | 사유 |`, h5-18b eval 18)
    found = sorted(list(re.finditer(r"^(R\d)\s+(pass|fail|skipped|needs-approval):?\s*(.*)$", result, re.MULTILINE))
                   + list(re.finditer(r"^\|\s*(R\d)\s*\|\s*(pass|fail|skipped|needs-approval)\s*\|\s*(.*?)\s*\|\s*$",
                                      result, re.MULTILINE)), key=lambda m: m.start())
    for m in found:
        # 행마다 찍은 출력의 끝 `review_required= False`(또는 값만 `True`)는 사유가 아니다 — 값은 review_required로 둔다
        tail = re.search(r"\s+(?:review_required=\s*)?(True|False|None)$", m.group(3).strip())
        reason = m.group(3).strip()[:tail.start()] if tail else m.group(3).strip()
        row = {"id": m.group(1), "status": m.group(2), "reason": reason}
        if tail and "review_required" in tail.group(0):
            row["review_required"] = tail.group(1) == "True"
        rows.append(row)
    return {"rules": rows} if rows else None


def draft_rules(result: str) -> list[dict] | None:
    doc = draft_doc(result)
    return None if doc is None else [r for r in doc["rules"] if isinstance(r, dict) and r.get("id")]


def tool_text(e) -> str:
    """도구 결과 본문: Read는 줄 번호 접두(`  12\\t`·`  12→`)를 떼고, `{"screen": …}` JSON(render --json)이면 screen."""
    res = str(e.get("result") or "")
    if e.get("name") == "Read":
        res = re.sub(r"^\s*\d+(?:\t|→)", "", res, flags=re.MULTILINE)
    if '"screen"' in res:
        a, b = res.find("{"), res.rfind("}")
        try:
            doc = json.loads(res[a:b + 1]) if 0 <= a < b else None
        except ValueError:
            doc = None
        if isinstance(doc, dict) and isinstance(doc.get("screen"), str):
            return doc["screen"]
    return res


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
                     "result": "", "error": False}
                if not isinstance(e["input"], dict):
                    e["input"] = {}
                out.append(e)
                if e["id"]:
                    by_id[e["id"]] = e
            elif typ == "assistant" and c.get("type") == "text":
                out.append({"kind": "text", "text": str(c.get("text") or "")})
            elif typ == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                by_id[c["tool_use_id"]].update(result=_block_text(c.get("content")), error=bool(c.get("is_error")))
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


def not_run(e) -> bool:
    """hook이 거부해 실행되지 않은 도구 호출(show_guard·guard 등, 결과가 `PreToolUse:…`인 오류). 창을 닫지도 열지도 않는다."""
    if e.get("kind") != "tool":
        return False
    return denied(e) or (bool(e.get("error")) and str(e.get("result") or "").lstrip().startswith("PreToolUse:"))


def _live_ask(e) -> bool:
    return e.get("kind") == "tool" and is_ask(e.get("name")) and not denied(e)


def visible_between(seq, start: int = 0, end: int | None = None) -> list[str]:
    """seq[start:end]에서 사용자에게 보인 글(assistant 텍스트·질문 문구, 거부된 질문 제외)을 순서대로."""
    out = []
    for e in seq[max(start, 0):len(seq) if end is None else end]:
        if e["kind"] == "text":
            out.append(e["text"])
        elif _live_ask(e):
            out.append(ask_text(e["input"]))
    return out


def asks(seq, start: int, end: int) -> list[int]:
    """seq[start:end] 안 질문(거부된 것 제외)의 순번."""
    return [i for i in range(max(start, 0), min(end, len(seq))) if _live_ask(seq[i])]


def bash_index(seq, rx, start: int = 0, end: int | None = None) -> list[int]:
    """rx에 맞는 명령을 실행한 Bash 호출의 순번(hook이 거부해 실행되지 않은 호출 `not_run`은 뺀다)."""
    return [i for i in range(start, len(seq) if end is None else end) if seq[i]["kind"] == "tool"
            and seq[i]["name"] == "Bash" and not not_run(seq[i]) and rx.search(command_of(seq[i]))]


def step7_question(tool_input) -> bool:
    """Step 7 분류 질문: 선택지 중 2개 이상이 든 질문."""
    opts = tool_input.get("options") if isinstance(tool_input, dict) else None
    q = ask_text(tool_input) + " " + " ".join(map(str, opts if isinstance(opts, list) else []))
    return sum(o in q for o in STEP7_OPTS) >= 2


def step7_index(seq) -> int | None:
    """Step 7 분류 질문(거부되지 않은)의 seq 순번."""
    for i, e in enumerate(seq):
        if _live_ask(e) and step7_question(e["input"]):
            return i
    return None


# --- 창(확인 화면·리포트·초안 검증표) ------------------------------------------------------------------------

def screens(seq, kind: str, *, script_only: bool = False) -> list[dict]:
    """확인 화면 창(kind push|post) `[{start, end, end_kind, hash, block, approved_arg, asked, see_above, lines, missing}]`.
    화면 = Bash·Read 결과 안의 스크립트 화면(머리 줄 ~ 해시 줄). 해시가 같은 다음 결과(다시 `cat`)는 같은 창이다.
    창 끝 = 뒤의 publish·discard(push)·issue_post approve(post) Bash, 해시가 다른 화면(다시 stage·render), 기록 끝 중 먼저.
    화면이 나온 호출 자체도 본다(그 안의 stage·render 뒤 부분): `stage …; publish …`·`render …; approve …`를 한 Bash로
    부르면 end = start라 보인 글도 질문도 없다.
    asked = 창 안의 마지막 질문. missing = 화면 뒤 ~ asked(질문 포함), 질문이 없으면 창 끝까지 보인 글에 없는 줄.
    hook이 거부해 실행되지 않은 호출(`not_run`)은 화면을 열지도(거부 문구에 화면이 실려 있다) 창을 닫지도 않는다.
    script_only(show_guard): 화면을 낸 스크립트 호출(Bash의 `db_pr.py stage`·`summary`, `issue_post.py render`)과, 그 호출이
    리디렉션으로 쓴 파일(이름 비교)을 다시 읽은 결과만 화면으로 본다 — 문서·fixture를 `cat`·Read한 결과의 화면 모양 글은 의무가
    아니다(채점기는 Read로 연 화면을 모두 센다)."""
    rx, end_rx, gen_rx = ((PUSH_SCREEN, PUSH_END, STAGE) if kind == "push" else (POST_SCREEN, POST_END, RENDER))
    makers = (STAGE, SUMMARY) if kind == "push" else (RENDER,)
    saved: set[str] = set()       # script_only: 화면을 낸 호출이 리디렉션으로 쓴 파일 이름(`stage … > $JOB/stage_out.md`)
    hits = []
    for i, e in enumerate(seq):
        if e["kind"] != "tool" or e["name"] not in ("Bash", "Read") or not_run(e):
            continue
        if script_only:
            cmd = command_of(e) if e["name"] == "Bash" else ""
            if any(m.search(cmd) for m in makers):
                saved.update(redirect_targets(cmd))
            elif not saved or not _reads_saved(e, saved):
                continue
        found = list(rx.finditer(tool_text(e)))
        if found:
            block = found[-1].group(0)
            heads = [m.start() for m in SCREEN_HEAD[kind].finditer(block)]
            block = block[heads[-1]:]
            hits.append((i, block, block.rstrip().splitlines()[-1].strip()))
    wins = []
    for i, block, digest in hits:
        if wins and wins[-1]["hash"] == digest:
            continue
        wins.append({"start": i, "hash": digest, "block": block, "approved_arg": None, "sha_arg": None})
    for k, w in enumerate(wins):
        nxt = wins[k + 1]["start"] if k + 1 < len(wins) else len(seq)
        w["end"], w["end_kind"] = nxt, "restage" if k + 1 < len(wins) else "end"
        for j in range(w["start"], nxt):     # 화면이 나온 호출부터: `stage …; publish …` 한 호출이면 end = start
            e = seq[j]
            cmd = command_of(e) if e["kind"] == "tool" and e["name"] == "Bash" and not not_run(e) else ""
            if j == w["start"]:
                cmd = after_last(gen_rx, cmd)
            m = end_rx.search(cmd)
            if m:
                w["end"], w["end_kind"] = j, m.group(1)
                a = APPROVED_ARG.search(cmd) if m.group(1) == "publish" else None
                w["approved_arg"] = a.group(1) if a else None
                s = SHA_ARG.search(cmd) if m.group(1) == "approve" else None
                w["sha_arg"] = s.group(1) if s else None
                break
        found = asks(seq, w["start"] + 1, w["end"])
        w["asked"] = found[-1] if found else None
        w["see_above"] = any(SEE_ABOVE.search(ask_text(seq[a]["input"])) for a in found)
        chunks = visible_between(seq, w["start"] + 1, (w["asked"] + 1) if w["asked"] is not None else w["end"])
        w["lines"] = screen_lines(w["block"])
        w["missing"] = uncovered(w["lines"], chunks)
    return wins


REDIRECT = re.compile(r"(?:^|[^0-9>&])(?:&|1)?>>?\s*([^\s;&|<>]+)")


def redirect_targets(cmd: str) -> set[str]:
    """명령의 stdout 리디렉션 대상(`>`·`>>`·`1>`·`&>`·`&>>`, `2>`·`>&1`·`/dev/*` 제외). 절대 경로(변수 없음)는 경로 그대로,
    상대·`$VAR`·`~` 경로는 파일 이름만(`name:` 접두) — 다시 읽을 때 같은 규칙으로 비교한다(`_reads_saved`)."""
    out = set()
    for t in REDIRECT.findall(cmd):
        t = t.strip("\"'")
        if not t or t.startswith("/dev/"):
            continue
        out.add(t if t.startswith("/") and "$" not in t else "name:" + Path(t).name)
    return out


def _reads_saved(e, saved: set[str]) -> bool:
    """Read·Bash가 화면 출력 파일(`redirect_targets`) 중 하나를 읽었다: 절대 경로는 경로 전체, 그 밖은 파일 이름으로 비교."""
    if e["name"] == "Read":
        fp = str((e.get("input") or {}).get("file_path", ""))
        return fp in saved or "name:" + Path(fp).name in saved
    cmd = command_of(e)
    for t in saved:
        target = t.removeprefix("name:")
        if target and re.search(r"(?<![\w.-])" + re.escape(target) + r"(?![\w.-])", cmd):
            return True
    return False


def digest_of(w) -> str:
    """창 해시 줄(`approved_hash: <h>`·`post_sha256: <h>`)의 값."""
    return str(w["hash"]).split(":")[-1].strip()


def _read_text(read_file, path) -> str:
    if read_file is None or path is None:
        return ""
    try:
        return read_file(Path(path)) or ""
    except (OSError, ValueError, UnicodeError):
        return ""


def report_window(seq, end: int | None = None, read_file=None, job_dir=None, *, latest: bool = False) -> dict:
    """Step 6 리포트 창: 마지막 triage run ~ end(기본: Step 7 질문(포함)·첫 stage·기록 끝). 리포트 = 창 안 Bash·Read 결과의
    `## <KEY> 분석` 중 가장 긴 것(head·grep 일부 재열람은 기준이 아니다), 없으면 job_dir/report.md(read_file로 읽는다).
    → {start, end, run, source, where, core, must}. must = job_dir/analysis.json의 must_show.
    latest(show_guard): 기록 전체의 마지막 triage run부터 그 뒤 Step 7 질문·stage까지(분석을 여러 번 하면 마지막 분석의
    리포트). 이때 리포트 원문은 job_dir/report.md를 먼저 보고, 창 안 결과는 명령·경로에 `report.md`가 든 것만 본다(문서 열람 제외)."""
    if latest:
        runs = bash_index(seq, TRIAGE_RUN)
        start = runs[-1] if runs else 0
        if end is None:
            s7 = next((i for i in range(start, len(seq)) if _live_ask(seq[i]) and step7_question(seq[i]["input"])), None)
            stage = bash_index(seq, STAGE, start)
            end = s7 + 1 if s7 is not None else stage[0] if stage else len(seq)
    else:
        if end is None:
            s7 = step7_index(seq)
            stage = bash_index(seq, STAGE)
            end = s7 + 1 if s7 is not None else stage[0] if stage else len(seq)
        runs = bash_index(seq, TRIAGE_RUN, 0, end)
        start = runs[-1] if runs else 0
    source, where = None, ""
    if latest and job_dir is not None:
        text = _read_text(read_file, Path(job_dir) / "report.md")
        if text:
            source, where = text, "JOB/report.md"
    for i in range(start, end) if source is None else ():
        e = seq[i]
        if e["kind"] == "tool" and e["name"] in ("Bash", "Read") and not not_run(e):
            if latest and "report.md" not in json.dumps(e.get("input") or {}, ensure_ascii=False):
                continue
            t = tool_text(e)
            if REPORT_HEAD.search(t) and (source is None or len(t) > len(source)):
                source, where = t, f"seq {i} 결과"
    if source is None:
        source, where = _read_text(read_file, None if job_dir is None else Path(job_dir) / "report.md"), "JOB/report.md"
    must = []
    raw = _read_text(read_file, None if job_dir is None else Path(job_dir) / "analysis.json")
    if raw:
        try:
            doc = json.loads(raw)
        except ValueError:
            doc = {}
        must = [str(m) for m in (doc.get("must_show") or [] if isinstance(doc, dict) else [])]
    return {"start": start, "end": end, "run": runs[-1] if runs else None, "source": source, "where": where,
            "core": report_core(source), "must": must}


PLAN_ARG = re.compile(r"--plan[= ]\s*(\"[^\"]*\"|'[^']*'|\S+)")     # 값: 따옴표 경로(공백 포함) 또는 공백 없는 글


def plan_tag(e) -> str:
    """draft 호출의 `--plan` 경로 끝 두 마디(<KEY>/plan.json). 따옴표·구분자·빈 마디 표기 차이는 같은 계획이다. 없으면 "".
    공백 든 따옴표 경로도 통째로 읽으려 원 명령(heredoc 제외)에서 찾되, db_verify rules 호출부터만 본다(`&&` 앞 명령·echo의
    `--plan`을 잡지 않게)."""
    raw = strip_heredocs(str((e.get("input") or {}).get("command", "")))
    m = DRAFT.search(raw)
    plan = PLAN_ARG.search(raw[m.start():] if m else raw)
    parts = plan.group(1).rstrip(";&|)").strip("\"'").replace("\\", "/").split("/") if plan else []
    return "/".join([p for p in parts if p not in ("", ".")][-2:])


def _norm_path(path: str) -> str:
    """경로 비교용: `\\`→`/`, 빈 마디·`.` 마디를 뺀다(`//`·`/./`)."""
    return "/".join(p for p in str(path).replace("\\", "/").split("/") if p not in ("", "."))


def _touches(e, tag: str, own: bool) -> bool:
    """도구 호출 e가 계획 파일(끝 두 마디 tag)을 건드릴 수 있는가. 경로 표기(`$J/plan.json`·절대 경로·`//`)가 달라도 같은 파일일
    수 있으므로 파일 이름(`plan.json`)으로 본다: Write·Edit 대상의 이름이 같거나, Bash 명령이 그 이름을 말한다. own(다시 돌린 draft
    호출 자신)이면 `--plan` 인자(공백 든 따옴표 경로 포함)로 쓴 것은 뺀다. 읽기만 해도 건드린 것으로 본다(모르면 끊는 쪽)."""
    if e.get("kind") != "tool" or not tag:
        return False
    name = tag.rsplit("/", 1)[-1]
    inp = e.get("input") if isinstance(e.get("input"), dict) else {}
    if e.get("name") in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return _norm_path(inp.get("file_path") or inp.get("notebook_path") or "").rsplit("/", 1)[-1] == name
    if e.get("name") != "Bash":
        return False
    cmd = str(inp.get("command", "")).replace("\\", "/")
    word = re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])")
    allowed = sum(len(word.findall(m.group(1))) for m in PLAN_ARG.finditer(cmd)) if own else 0
    return len(word.findall(cmd)) > allowed


def same_plan_rerun(seq, i: int, c: int) -> bool:
    """draft 호출 c가 i와 같은 계획(plan_tag)을 고치지 않고 다시 돌린 것인가: i 뒤 ~ c(포함)에 그 계획을 건드린 호출이 없다.
    사이에 같은 계획을 `--plan`으로 준 호출(실패한 재실행 등)은 그 인자를 빼고 본다(h6-18b eval 18)."""
    tag = plan_tag(seq[i])
    return bool(tag) and plan_tag(seq[c]) == tag and not any(
        _touches(seq[k], tag, k == c or (bool(DRAFT.search(command_of(seq[k]))) and plan_tag(seq[k]) == tag))
        for k in range(i + 1, c + 1))


def _cut_reason(reason) -> str:
    """잘린 사유 비교용: 정규화하고 끝의 말줄임(`…`·`...`)을 뗀다."""
    return re.sub(r"(?:…|\.\.\.)+$", "", norm_line(str(reason or ""))).rstrip()


def weaker_copy(full, part) -> bool:
    """part가 full의 덜 보인 사본인가: 같은 규칙은 상태가 같고 part의 사유가 full 사유의 앞부분(모델이 `[:150]`·`cut`으로
    자른 출력)이며, part에만 있는 규칙은 접힌 통과 행(pass·`해당 없음`)뿐이고, 사유가 실제로 잘렸거나 full의 규칙이 빠졌다.
    같은 결과를 덜 보이게 다시 찍어 표시 의무를 줄이지 못하게 한다(h5-18b eval 18: 경로 목록이 든 R3 사유를 150자로 잘라
    다시 돌린 뒤 잘린 행만 보였는데 hook은 통과시키고 채점기는 처음 결과로 실패시켰다)."""
    f = {str(r.get("id")): r for r in full or [] if isinstance(r, dict)}
    p = {str(r.get("id")): r for r in part or [] if isinstance(r, dict)}
    common = f.keys() & p.keys()
    if not common:
        return False
    shorter = False
    for rid in common:
        if f[rid].get("status") != p[rid].get("status"):
            return False
        a, b = norm_line(str(f[rid].get("reason") or "")), _cut_reason(p[rid].get("reason"))
        if not a.startswith(b):
            return False
        shorter = shorter or len(b) < len(a)
    extra = [p[rid] for rid in p.keys() - f.keys()]
    if extra and not draft_all_clear(extra):
        return False
    return shorter or bool(f.keys() - p.keys())


def weaker_rerun(seq, i: int, c: int) -> bool:
    """draft 호출 c가 i와 같은 계획을 고치지 않고 다시 돌려, 읽은 결과가 i 결과의 덜 보인 사본(`weaker_copy`)이다.
    그런 c는 i의 창을 닫지 않고 따로 의무가 되지도 않는다 — i의 표를 그대로 보여야 한다."""
    if not same_plan_rerun(seq, i, c):
        return False
    full, part = draft_rules(tool_text(seq[i])), draft_rules(tool_text(seq[c]))
    return bool(full) and bool(part) and weaker_copy(full, part)


def covering_draft(seq, c: int, calls, stage) -> int:
    """draft 결과 c를 덮는 앞 결과: c가 그 덜 보인 사본이고 그 창이 c를 넘는 가장 앞 draft 호출. 없으면 c."""
    for i in calls:
        if i >= c:
            break
        if draft_end(seq, i, calls, stage) > c and weaker_rerun(seq, i, c):
            return i
    return c


# 통과가 아닐 수 있는 출력: 낱말 `fail`·`needs-approval`(앞뒤가 글자·`-`가 아님 — `fail-case.log`·`failed`는 아니다)
_NOT_PASS = re.compile(r"(?<![\w-])(?:fail|needs-approval)(?![\w-])", re.IGNORECASE)


def draft_end(seq, i: int, calls, stage) -> int:
    """draft 결과 i의 표시 창 끝(배타): 다음 draft 호출·stage·기록 끝. 채점기(`draft_window`)와 hook(`obligations`)이 같이 쓴다.
    같은 계획을 고치지 않고 다시 돌렸는데 결과를 못 읽었고 출력에 fail·needs-approval 글이 없는 호출(`| sed -n 80,200p` 등)은
    창을 끊지 않는다: 그 뒤에 보인 표는 읽은 결과의 것으로 본다 (sm4-1-b eval 42). 다른 결과일 수 있으면 끊는다.
    전부 통과가 아닌 결과(`draft_all_clear` 아님 — fail·needs-approval·review_required 등)는 **다른 계획**(`plan_tag`가 다르다)의
    draft 호출로 끊지 않는다: 좁힌 안을 다른 파일(`plan-narrow.json`)로 돌려 통과해도 처음 실패 표(걸린 fixture·시그니처 키)를
    보이고 사용자가 고르게 해야 한다(h3-d eval 18). 그 창은 stage·같은 계획의 재실행(위 규칙)·작업 경계(`triage.py run`,
    `db_pr.py discard`·`lock acquire|release`)에서 닫힌다.
    남는 추정(고치지 않음): 계획이 그대로여도 draft 트리·fixture·이슈 DB 스냅샷이 바뀌면 다시 돌린 결과가 다를 수 있고, 계획을
    파일 이름(`plan.json`)을 말하지 않는 방법(변수에 든 경로를 `sed -i "$P"`)으로 고치면 건드림을 보지 못한다(`_touches`)."""
    rules = draft_rules(tool_text(seq[i]))
    sticky = bool(rules) and not draft_all_clear(rules)
    later = [c for c in calls if c > i] + [s for s in stage if s > i]
    if sticky:
        tag = plan_tag(seq[i])
        later = [c for c in later if c in stage or plan_tag(seq[c]) == tag]
        later += bash_index(seq, JOB_END, i + 1) + bash_index(seq, TRIAGE_RUN, i + 1)
    for c in sorted(set(later)):
        if c not in calls and c not in stage:
            return c        # 작업 경계
        if c not in stage and weaker_rerun(seq, i, c):
            continue        # 같은 결과를 덜 보이게 다시 찍었다(`weaker_copy`): i의 표가 그대로 의무다
        text = tool_text(seq[c])
        if (c in stage or draft_doc(text) is not None or _NOT_PASS.search(text)
                or not same_plan_rerun(seq, i, c)):
            return c
    return len(seq)


def draft_window(seq, pick: str = "last") -> dict | None:
    """초안 검증표 창: 고른 draft 호출 ~ 다음 draft 호출·stage·기록 끝. pick=last: 첫 stage 전 마지막으로 읽을 수 있는
    결과. pick=first_fail: fail 행이 든 첫 결과(stage 전 우선, 없으면 last와 같다). 그것이 잘린 출력의 `R4 fail: …` 요약
    줄만 읽은 결과면 계획을 고치지 않고 다시 돌려 JSON으로 읽은 fail 결과(그 규칙을 모두 덮는 것)를 본다(h1-b eval 42:
    `| head -60`). 창 끝은 `draft_end`.
    → {i, end, rules, doc, calls, parsed, first_stage}. 호출이 없으면 None. 결과를 하나도 못 읽으면 rules·doc이 None."""
    calls = bash_index(seq, DRAFT)
    if not calls:
        return None
    parsed = [(i, draft_doc(tool_text(seq[i]))) for i in calls]
    parsed = [(i, d) for i, d in parsed if d is not None]
    stage = bash_index(seq, STAGE)
    first_stage = stage[0] if stage else len(seq)
    if not parsed:
        return {"i": None, "end": None, "doc": None, "rules": None, "calls": calls, "parsed": [], "first_stage": first_stage}
    before = [p for p in parsed if p[0] < first_stage] or parsed
    i, doc = before[-1]
    if pick == "first_fail":
        failed = [p for p in parsed if any(isinstance(r, dict) and r.get("status") == "fail" for r in p[1]["rules"])]
        failed = [p for p in failed if p[0] < first_stage] or failed
        if failed:
            i, doc = failed[0]
            # 요약 줄만 읽은 결과면, 계획을 고치지 않고 같은 계획을 다시 돌려 읽은 결과(JSON 또는 규칙마다 찍은 행)가 그 규칙을
            # 모두 같은 상태로 덮을 때만 그것으로 바꾼다(다른 계획의 결과나 일부 행만 고른 출력으로 이 결과의 의무를 버리지
            # 않는다. h6-18b eval 18: 요약 줄 뒤 `print(r['id'], r['status'], r['reason'])`로 6행을 다시 찍었다)
            # 사유도 줄지 않아야 한다(`r['reason'][:150]`처럼 자른 재실행으로 처음 사유를 버리지 않게)
            st = {r.get("id"): (r.get("status"), _cut_reason(r.get("reason"))) for r in doc["rules"] if isinstance(r, dict)}

            def keeps(d):
                got = {r.get("id"): r for r in d["rules"] if isinstance(r, dict)}
                return len(got) > len(st) and all(
                    k in got and got[k].get("status") == v and norm_line(str(got[k].get("reason") or "")).startswith(why)
                    for k, (v, why) in st.items())
            if draft_json(tool_text(seq[i])) is None:
                i, doc = next(((c, d) for c, d in failed if c > i and same_plan_rerun(seq, i, c) and keeps(d)), (i, doc))
    j = covering_draft(seq, i, calls, stage)      # 덜 보인 사본이면 덮는 앞 결과의 창(hook `obligations`와 같다)
    if j != i:
        i, doc = j, draft_doc(tool_text(seq[j]))
    end = draft_end(seq, i, calls, stage)
    return {"i": i, "end": end, "doc": doc, "rules": [r for r in doc["rules"] if isinstance(r, dict) and r.get("id")],
            "calls": calls, "parsed": parsed, "first_stage": first_stage}


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
    """사용자에게 보여야 할 스크립트 출력 하나. kind push|post|report|draft, key push:<hash>|post:<sha 앞 16자>|report:<id>|
    draft:<결과 해시>(id = 그 호출의 tool_use id 끝 12자, 없으면 seq 순번; 초안은 규칙·상태·사유의 sha1 앞 12자). start = 출력이 나온 seq 순번, end = 창 끝(배타),
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


def _id_tag(e, i: int) -> str:
    tid = str(e.get("id") or "")
    return tid[-12:] if tid else str(i)


def obligations(seq, read_file=None, job_dir=None, *, script_only: bool = True) -> list[Obligation]:
    """seq의 표시 의무(show_guard): push·post 확인 화면 창 전부(`screens`, script_only면 화면을 낸 스크립트 호출만), 리포트
    (triage run이 있고 리포트를 찾았을 때 — 마지막 run의 창, `report_window(latest=True)`), 결과를 읽을 수 있는 초안 검증 호출마다
    하나(창 = 그 호출 ~ 다음 draft 호출·stage·기록 끝, 전부 통과가 아닌 결과는 다른 계획의 draft로 닫히지 않는다 — `draft_end`).

    창 닫힘: 화면 = publish·discard(push)·approve(post)·해시가 다른 다음 화면, 리포트 = Step 7 분류 질문·stage, 초안 표 =
    다음 초안 검증(전부 통과가 아니면 같은 계획만)·작업 경계·stage(`--dry-run`도 — dry-run 흐름의 stage도 worktree를 만들고 확인 화면을 낸다). hook이 거부해 실행되지
    않은 호출은 닫지 않는다."""
    out = []
    for kind in ("push", "post"):
        for w in screens(seq, kind, script_only=script_only):
            d = digest_of(w)
            out.append(Obligation(kind, f"{kind}:{d if kind == 'push' else d[:16]}", w["start"], w["end"], w["end_kind"],
                                  lines=w["lines"], block=w["block"], extra=w))
    rep = report_window(seq, read_file=read_file, job_dir=job_dir, latest=True)
    if rep["run"] is not None and rep["source"] and (rep["core"] or rep["must"]):
        end = rep["end"]
        close = ("end" if end >= len(seq) else "step7" if end - 1 < len(seq) and _live_ask(seq[end - 1]) else "stage")
        tag = _id_tag(seq[rep["run"]], rep["run"]) if rep["run"] is not None else "0"
        block = "\n".join(rep["core"] + [m for m in rep["must"] if m not in rep["core"]])
        out.append(Obligation("report", f"report:{tag}", rep["start"], rep["end"], close, lines=rep["core"],
                              must_show=rep["must"], block=block,
                              path=None if job_dir is None else str(Path(job_dir) / "report.md"), extra=rep))
    calls = bash_index(seq, DRAFT)
    stage = bash_index(seq, STAGE)
    runs = bash_index(seq, TRIAGE_RUN)
    first_of: dict[tuple, int] = {}       # (작업 경계, 키) → 같은 결과가 처음 나온 초안 호출
    for i in calls:
        rules = draft_rules(tool_text(seq[i]))
        if not rules or covering_draft(seq, i, calls, stage) != i:
            continue        # 결과를 못 읽었거나, 앞 결과의 덜 보인 사본(그 앞 결과가 의무다)
        end = draft_end(seq, i, calls, stage)
        close = "end" if end >= len(seq) else ("draft" if end in calls else "stage" if end in stage else "job")
        block = "\n".join(f"| {r['id']} | {r.get('status')} | {norm_line(str(r.get('reason') or ''))} |" for r in rules)
        # 키는 계획 경로 인자와 결과 내용(규칙·상태·사유): 같은 작업에서 같은 결과로 다시 돌려도 같은 의무라 막는 횟수 한도를
        # 함께 쓴다. 다른 작업과 키가 같아도(`$J/plan.json`·전부 통과) 횟수는 작업 경계(마지막 triage run) 뒤에서만 센다.
        # 경로는 뒤 셸 구분자·따옴표를 벗기고 빈·`.` 마디를 뺀 끝 두 마디(<KEY>/plan.json)만 쓴다: 표기만 바꿔 다시 돌려
        # 한도를 새로 얻지 못하게(plan_tag)
        tag = plan_tag(seq[i])
        digest = hashlib.sha1(json.dumps([tag] + [[r.get("id"), r.get("status"), r.get("reason")]
                                                  for r in rules],
                                         ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        boundary = max([r for r in runs if r < i], default=-1)
        count_from = first_of.setdefault((boundary, digest), i)
        out.append(Obligation("draft", f"draft:{digest}", i, end, close, rules=rules, block=block,
                              extra={"count_from": count_from}))
    return out


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


def missing(ob: Obligation, chunks) -> list[str]:
    """ob의 빠진 것: 화면 줄 / 리포트 결정적 줄(글머리·굵게 무시) + 글자 그대로 없는 must_show / 보인 행이 없는 규칙."""
    if ob.kind == "draft":
        return draft_rows_missing(ob.rules, visible_lines(chunks))
    if ob.kind == "report":
        raw = "\n".join(str(c) for c in chunks)
        return report_uncovered(ob.lines, chunks, ob.must_show) + [m for m in ob.must_show if m not in raw]
    return uncovered(ob.lines, chunks)


CAPPED = "(재시도 한도)"


def guard_counts(lines) -> dict:
    """show_guard 동작 횟수(eval 지표 `metrics.show_guard`): blocks = 표식이 든 Stop hook 피드백, denies = 표식이 든 거부된 도구
    결과, capped = 재시도 한도 안내(`[telephony-triage]` + `(재시도 한도)`)가 든 assistant 밖 항목(systemMessage가 기록되는 자리는
    버전마다 다를 수 있어 최선 노력)."""
    lines = list(lines)
    seq = parse_events(lines, include_user=True, skip_sidechain=True)
    blocks = sum(1 for e in seq if e["kind"] == "user" and e["feedback"] and MARKER in e["text"])
    denies = sum(1 for e in seq if denied(e))
    capped = 0
    for raw in lines:
        s = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        if CAPPED in s and "[telephony-triage]" in s:
            try:
                ev = json.loads(s)
            except ValueError:
                continue
            if isinstance(ev, dict) and ev.get("type") != "assistant":
                capped += 1
    return {"blocks": blocks, "denies": denies, "capped": capped}
