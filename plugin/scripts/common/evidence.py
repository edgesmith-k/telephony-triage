"""근거 원문 검사(grounding)와 출력 칸 읽기 — `module_eval`(C0 채점)과 `triage.py check-output`(B2 §6)이 같이 쓴다.

`module_eval.py`에서 옮겼다(동작 그대로). `module_eval`은 같은 이름을 다시 내보낸다.
- `parse_fields`: 고정 칸(심층 6칸 `FIELDS_DEEP`, 설치 스킬 4칸 `FIELDS_SKILL`)을 순서대로 읽는다.
- `parse_explore`: 탐색 출력(`가설 n:` 블록 1~3개, 또는 `가설 없음:`).
- `source_text`·`event_rows_text`: 검사 원문(타임라인 행 문법 줄만, events.json 전체 행).
- `evidence_check`·`check_quotes`: 인용이 원문에 있는지(ok | weak | fabricated).
"""

from __future__ import annotations

import difflib
import re

FIELDS_DEEP = ("원인 층", "원인 데몬", "근거", "반대 근거", "분석 스킬 의견", "규칙 제안")
FIELDS_SKILL = ("요약", "근거", "분석 스킬 의견", "규칙 제안")
LIST_FIELDS = ("근거", "규칙 제안")
EXPLORE_FIELDS = ("가설", "로그로 확인", "코드로 추정", "반대 근거", "다음 확인")

ITEM_RX = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)$")
FENCE_RX = re.compile(r"^\s*```[^\n]*\n(.*)\n\s*```\s*$", re.DOTALL)
TAG_FIND_RX = re.compile(r"\s([A-Za-z][\w-]*)\[\d+\]:\s")
WS_RX = re.compile(r"\s+")
EVENT_SUFFIX_RX = re.compile(r"\s+⇒\s.*$")
STRIP_RX = (re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2}\s+"),          # syslog 날짜
            re.compile(r"^\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+"),       # 시각
            re.compile(r"^\S+\s+daemon\.[a-z]+\s+"),              # syslog host·facility
            re.compile(r"^(?:-|p\d+)\s+"),                        # 타임라인 슬롯
            re.compile(r"^[VDIWEF]\s+"))                          # 레벨
QUOTE_CHARS_RX = re.compile(r"[`\"“”‘’]")
QUOTE_CUT_RX = re.compile(r"\s+[—–]\s+")
ELLIPSIS_RX = re.compile(r"…|\.\.\.")
# S7 덮임 검사: 인용을 한글이 든 낱말(설명)과 화살표에서 잘라 로그 조각으로 나눈다.
RUN_SPLIT_RX = re.compile(r"(?:^|\s)\S*[가-힣]\S*(?=\s|$)|[→⇒]|\[?\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b\]?|\b\d{4}-\d{2}-\d{2}\b")
COVER_BLOCK, UNCOVERED_MAX = 4, 12
# 결정 토큰(종합 리뷰 P1): 바뀌면 텔레포니 결론이 달라지는 조각 — 슬롯(`[PHONE0]`·`phoneId=1`), 오류·원인·상태 코드(`error 2`·
# `cause=AUTH(29)`·`status=FAILED`), 성공/실패 낱말. 최장 일치·덮임 검사는 12자 미만 변조(`error 2`→`error 6`, `PHONE0`→`PHONE1`,
# `failed`→`succeeded`)를 ok로 봤다. 인용의 토큰을 뺀 가장 긴 조각(`ANCHOR_MIN`자 이상)이 든 원문 **한 줄**에 토큰이 모두 있어야 ok다.
DECISION_TOKEN_RX = re.compile(
    r"\[PHONE\d+\]|\bphone[_ ]?id\s*[=:]\s*\d+|"
    r"\b(?:error|err|errno|cause|code|reason|status|state|result|rat|fail_cause|failcause|rc|ret)\s*[=:]?\s*[-A-Za-z0-9_]+(?:\(\d+\))?|"
    r"\b(?:failed|failure|fail|succeeded|success|rejected|reject|accepted|timeout|timed out|denied|disconnected|connected)\b",
    re.IGNORECASE)
ANCHOR_MIN = 8

# 타임라인 행 문법(report.row_line·모듈 뷰): `시각 슬롯 레벨 태그 메시지`. 머리 글머리표(`- …`)와 `## ` 제목은 아니다
ROW_RX = re.compile(r"^(?!- )\S+ (?:p\d+|-) [A-Z?-] \S+ ")
SCRIPT_NOTE_RX = re.compile(r"\s*〔script[^〕]*〕")
BIG_SOURCE = 256 * 1024          # 이보다 큰 원문은 인용마다 걸러 낸 행만 본다(difflib가 수 MB에서 느리다)
PREFILTER_ROWS, PREFILTER_WORD = 300, 8
_WORD_RX = re.compile(r"\S{" + str(PREFILTER_WORD) + ",}")


def _label_rx(name: str) -> re.Pattern:
    return re.compile(r"^\s*(?:[-*]\s*)?\**\s*" + re.escape(name) + r"\s*\**\s*[:：]\s*\**\s*(.*)$")


LABEL_RX = {f: _label_rx(f) for f in dict.fromkeys(FIELDS_DEEP + FIELDS_SKILL)}
HYP_RX = re.compile(r"^\s*(?:[-*]\s*)?\**\s*가설\s*(\d+)?\s*\**\s*[:：]\s*\**\s*(.*)$")
NONE_RX = _label_rx("가설 없음")
EXPLORE_RX = {f: _label_rx(f) for f in EXPLORE_FIELDS[1:]}


def ws(text: str) -> str:
    return WS_RX.sub(" ", text).strip()


# --- 메시지 정규화 (S4·S7, C0 설계 §9.3) ------------------------------------------------------------------

def log_tags(text: str) -> list[str]:
    return sorted(set(TAG_FIND_RX.findall(text)), key=lambda t: (-len(t), t))


def tag_rx(tags: list[str]) -> re.Pattern | None:
    if not tags:
        return None
    return re.compile(r"^<?(?:" + "|".join(map(re.escape, tags)) + r")>?(?:\[\d+\])?:?\s+")


def msg_part(line: str, tags: re.Pattern | None = None) -> str:
    """줄의 메시지 부분: 공백 접기, 타임라인 이벤트 꼬리(` ⇒ …`) 빼기, 날짜·시각·host·슬롯·레벨·태그 앞머리 빼기(각각 있으면)."""
    s = EVENT_SUFFIX_RX.sub("", ws(line))
    for rx in STRIP_RX:
        s = rx.sub("", s, count=1)
    if tags is not None:
        s = tags.sub("", s, count=1)
    return s


# --- 답 칸 읽기 (C0 설계 §9.1) -------------------------------------------------------------------------

def _parse(text: str, fields: tuple[str, ...] = FIELDS_DEEP) -> tuple[dict | None, list[str], range | None]:
    m = FENCE_RX.match(text or "")
    body = m.group(1) if m else (text or "")
    lines = body.split("\n")
    rx = {f: LABEL_RX.get(f) or _label_rx(f) for f in fields}
    hits = {f: [i for i, line in enumerate(lines) if rx[f].match(line)] for f in fields}
    if not hits[fields[0]]:
        return None, lines, None
    idx = [hits[fields[0]][-1]]
    for f in fields[1:]:
        nxt = next((i for i in hits[f] if i > idx[-1]), None)
        if nxt is None:
            return None, lines, None
        idx.append(nxt)
    label_lines = sorted({i for f in fields for i in hits[f]})
    out: dict = {}
    rule_block = None
    for f, i in zip(fields, idx):
        rest = rx[f].match(lines[i]).group(1).strip()
        if f in LIST_FIELDS:
            end = next((j for j in label_lines if j > i), len(lines)) if f == "근거" else len(lines)
            block = [rest, *lines[i + 1:end]]
            out[f] = [im.group(1).strip() for line in block if (im := ITEM_RX.match(line))]
            if f == "규칙 제안":
                rule_block = range(i, end)
        else:
            out[f] = rest
    return out, lines, rule_block


def parse_fields(text: str, fields: tuple[str, ...] = FIELDS_DEEP) -> dict | None:
    """답에서 고정 칸. 마지막 첫 칸 줄부터 칸이 순서대로 있어야 한다(없으면 None). 근거·규칙 제안은 항목 목록."""
    return _parse(text, fields)[0]


def parse_explore(text: str) -> dict | None:
    """탐색 출력 → {"none": str|None, "next": str|None, "hyps": [{가설, 로그로 확인: [...], 코드로 추정, 반대 근거, 다음 확인}]}.

    `가설 n: …` 블록마다 다섯 칸이 순서대로 있어야 한다. 블록이 없으면 `가설 없음: <이유>`와 `다음 확인:`이 있어야 한다.
    어느 쪽도 아니면 None. 칸 밖 줄(빈 줄·설명)은 무시한다.
    """
    m = FENCE_RX.match(text or "")
    lines = (m.group(1) if m else (text or "")).split("\n")
    starts = [i for i, line in enumerate(lines) if HYP_RX.match(line) and not NONE_RX.match(line)]
    if not starts:
        none_at = next((i for i, line in enumerate(lines) if NONE_RX.match(line)), None)
        if none_at is None:
            return None
        nxt = next((EXPLORE_RX["다음 확인"].match(line).group(1).strip() for line in lines[none_at + 1:]
                    if EXPLORE_RX["다음 확인"].match(line)), None)
        if nxt is None:
            return None
        return {"none": NONE_RX.match(lines[none_at]).group(1).strip(), "next": nxt, "hyps": []}
    hyps = []
    for k, at in enumerate(starts):
        block = lines[at:starts[k + 1] if k + 1 < len(starts) else len(lines)]
        hyp = {"가설": HYP_RX.match(block[0]).group(2).strip()}
        pos = 1
        for f in EXPLORE_FIELDS[1:]:
            hit = next((j for j in range(pos, len(block)) if EXPLORE_RX[f].match(block[j])), None)
            if hit is None:
                return None
            rest = EXPLORE_RX[f].match(block[hit]).group(1).strip()
            if f == "로그로 확인":
                end = next((j for j in range(hit + 1, len(block))
                            if any(EXPLORE_RX[g].match(block[j]) for g in EXPLORE_FIELDS[2:])), len(block))
                items = [im.group(1).strip() for line in block[hit + 1:end] if (im := ITEM_RX.match(line))]
                hyp[f] = ([rest] if rest else []) + items
                pos = end
            else:
                hyp[f] = rest
                pos = hit + 1
        hyps.append(hyp)
    return {"none": None, "next": None, "hyps": hyps}


# --- 근거 원문 검사 ---------------------------------------------------------------------------------------

def _quote_parts(item: str, tags) -> list[str]:
    q = QUOTE_CHARS_RX.sub("", item)
    q = QUOTE_CUT_RX.split(q, maxsplit=1)[0]
    q = msg_part(q, tags)
    return [p.strip() for p in ELLIPSIS_RX.split(q) if p.strip()]


def _uncovered_run(part: str, files_text: str, tags=None) -> int:
    """로그 조각(한글 낱말·화살표로 나눈 12자 이상 덩어리)마다, 그 조각을 가장 많이 덮는 원문 **한 줄**에 덮이지 않은 가장
    긴 연속 구간의 길이(앞뒤 공백 제외). 최장 일치 하나만 보는 설계 §9.3 원안은 두 줄을 이어 붙인 줄이나 진짜 앞머리에 지어낸
    꼬리를 붙인 줄을 ok로 봤다(리뷰 P1). 덮임은 같은 줄 안에서 순서대로 맞는 4자 이상 블록만 센다."""
    lines = [line for line in files_text.split("\n") if line]
    worst = 0
    for run in (msg_part(r, tags).strip() for r in RUN_SPLIT_RX.split(part)):
        if len(run) < UNCOVERED_MAX or not lines:
            continue
        best: tuple[int, list] | None = None
        for line in lines:
            blocks = [b for b in difflib.SequenceMatcher(None, run, line, autojunk=False).get_matching_blocks()
                      if b.size >= COVER_BLOCK]
            size = sum(b.size for b in blocks)
            if best is None or size > best[0]:
                best = (size, blocks)
        covered = [False] * len(run)
        for b in best[1]:
            covered[b.a:b.a + b.size] = [True] * b.size
        gap = ""
        for ch, c in zip(run + "\0", covered + [True]):
            if c:
                worst = max(worst, len(gap.strip()))
                gap = ""
            else:
                gap += ch
    return worst


def _decision_tokens_altered(part: str, files_text: str) -> bool:
    """인용 조각의 결정 토큰(`DECISION_TOKEN_RX`)이 원문에서 바뀌었나. 토큰을 뺀 나머지 중 가장 긴 조각(앵커, `ANCHOR_MIN`자 이상)이
    든 원문 줄들 가운데 **한 줄**이 토큰을 모두(대소문자 무관) 담으면 그대로다. 앵커가 없거나 앵커를 담은 줄이 없으면 판정하지
    않는다(False — 그 경우는 최장 일치·덮임 검사가 이미 판정했다)."""
    tokens = [m.group(0) for m in DECISION_TOKEN_RX.finditer(part)]
    if not tokens:
        return False
    runs = sorted((r.strip() for r in DECISION_TOKEN_RX.sub("\0", part).split("\0")), key=len, reverse=True)
    anchor = next((r for r in runs if len(r) >= ANCHOR_MIN), None)
    if anchor is None:
        return False
    lows = [t.lower() for t in tokens]
    seen = False
    for line in files_text.split("\n"):
        if anchor not in line:
            continue
        seen = True
        low = ws(line).lower()
        if all(t in low for t in lows):
            return False
    return seen


def evidence_check(item: str, files_text: str, tags) -> tuple[str, list[tuple[str, int, int]]]:
    """근거 항목 하나의 판정: ok | weak | fabricated, 부분별 (판정, 최장 일치 길이, 길이). 결정 토큰이 바뀐 인용은 fabricated다."""
    worst, detail = "ok", []
    for part in _quote_parts(item, tags):
        n = len(part)
        if n < 12:
            verdict, m = ("ok", n) if part in files_text else ("weak", 0)
        else:
            m = difflib.SequenceMatcher(None, part, files_text, autojunk=False).find_longest_match(
                0, n, 0, len(files_text)).size
            verdict = "ok" if (m >= 20 or m >= 0.6 * n) else "weak" if m >= 12 else "fabricated"
            if verdict != "fabricated" and _uncovered_run(part, files_text, tags) >= UNCOVERED_MAX:
                verdict = "fabricated"
            if verdict != "fabricated" and _decision_tokens_altered(part, files_text):
                verdict = "fabricated"
        detail.append((verdict, m, n))
        if verdict == "fabricated" or (verdict == "weak" and worst == "ok"):
            worst = verdict
    return worst, detail


def source_text(timeline_text: str) -> tuple[str, re.Pattern | None]:
    """검사 원문: 행 문법(`ROW_RX`) 줄만(본문과 `## 다른 모듈 줄`·`## 모뎀 모듈 줄`), 꼬리 `〔script…〕` 메모는 뺀다.
    머리 글머리표(Jira 실패 스텝·모듈 신호 약함·미수집·줄 수)와 `## ` 제목은 원문이 아니다. 태그 regex는 그 행의
    넷째 칸으로만 만든다."""
    rows, tags = [], set()
    for line in (timeline_text or "").split("\n"):
        if not ROW_RX.match(line):
            continue
        line = SCRIPT_NOTE_RX.sub("", line)
        rows.append(line)
        parts = line.split(" ", 4)
        if len(parts) >= 4 and parts[3] != "-":
            tags.add(parts[3])
    return "\n".join(rows), tag_rx(sorted(tags, key=lambda t: (-len(t), t)))


def event_rows_text(events: dict) -> str:
    """events.json의 합친 행 전부(상한 없음, 메시지 자르지 않음)를 행 문법으로 — 설치 스킬 모드의 검사 원문."""
    from triagelib import report  # common → triagelib는 여기서만(지연 import)
    return "\n".join(report.row_line(row, clip=None) for row in report.merge_rows(events or {}))


def _subset(part_words: list[str], rows: list[str]) -> str:
    out = []
    for row in rows:
        if any(w in row for w in part_words):
            out.append(row)
            if len(out) >= PREFILTER_ROWS:
                break
    return "\n".join(out)


def check_quotes(items: list[str], source: str, tags, *, raw_items: frozenset[int] = frozenset()) -> dict:
    """인용 목록 판정 → {"n", "fabricated", "weak", "raw", "first"}.

    `〔script` 메모를 인용한 항목은 지어낸 것으로 센다. `raw_items`(check-output 마스킹이 바꾼 항목 = 원문 값이 든 인용,
    설치 스킬 모드만)는 `raw`로 세고 지어낸 것으로 세지 않는다. 원문이 256KB보다 크면 인용마다 8자 이상 낱말을 공유하는
    행(최대 300행)만 본다.
    """
    from common import masking
    rows = source.split("\n") if len(source) > BIG_SOURCE else None
    res = {"n": len(items), "fabricated": 0, "weak": 0, "raw": 0, "first": None}
    for i, item in enumerate(items):
        if i in raw_items:
            res["raw"] += 1
            continue
        if "〔script" in item:
            verdict = "fabricated"
        else:
            text = source
            if rows is not None:
                words = _WORD_RX.findall(" ".join(_quote_parts(item, tags)))
                text = _subset(words, rows)
            verdict = evidence_check(item, text, tags)[0]
        if verdict == "fabricated":
            res["fabricated"] += 1
            if res["first"] is None:
                res["first"] = masking.mask_brief(item, 40)
        elif verdict == "weak":
            res["weak"] += 1
    return res
