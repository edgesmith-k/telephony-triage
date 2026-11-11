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
# 코덱스 리뷰 F1: ① 토큰 포함을 부분 문자열로 봐서 `status=1`이 `status=10`에 든다고 했다 → 토큰 경계(`_has_token`). ② `not` 삽입은
# 토큰이 아니라 앵커에 들어가 앵커를 담은 줄이 없어 판정을 포기했다 → 부정·참/거짓 낱말도 토큰. ③ `retry=9` 같은 임의 `키=값`은
# 토큰이 아니었다 → 인용의 모든 `키=값`·`키: 값` 조각이 토큰(값은 마스킹 토큰 `<IMSI#1>`도 받는다). 코덱스 리뷰 02e0ec2 F04: 임의
# 키 분기가 `=`만 받아 `retry: 9`를 놓쳤다 → `키: 값` 분기를 따로 둔다. 값이 완결될 때만 토큰이다 — `=` 꼴은 뒤에 값 문자·`=`가
# 안 올 때(`t=10:00:00`·`uri=sip:alice`처럼 `:`는 이어져도 된다. 뒤가 `:숫자`로 끝나는 포트 꼴 `pcscf=<IP#1>:5060`은 포트까지
# 토큰이다 — 포트 변조), `:` 꼴은 `:`도 안 올 때. 아니면
# `onSetupDataCallResult: status=0x10`의 `…Result: status`가 토큰이 돼 `status=0x1` 변조를 놓친다. 키는 글자로 시작해 시각은 아니다.
# 로그 태그 뒤 `:`(logcat 습관 `D/RILJ: …`·`→ ofonod: …` — 타임라인 행엔 없다)는 토큰이 아니다(`_decision_tokens_altered`).
NEGATION_WORDS = ("not", "no", "never", "cannot", "unable", "without")
DECISION_TOKEN_RX = re.compile(
    r"\[PHONE\d+\]|\bphone[_ ]?id\s*[=:]\s*\d+|"
    r"\b(?:error|err|errno|cause|code|reason|status|state|result|rat|fail_cause|failcause|rc|ret)\b\s*[=:]?\s*[-A-Za-z0-9_]+(?:\(\d+\))?|"
    r"\b[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?=[-A-Za-z0-9_<])[-A-Za-z0-9_.<>#]+(?:\(\d+\))?(?::\d+(?![-A-Za-z0-9_.<>#=:]))?(?![-A-Za-z0-9_.<>#=])|"
    r"\b[A-Za-z_][A-Za-z0-9_]*\s*:\s*(?=[-A-Za-z0-9_<])[-A-Za-z0-9_.<>#]+(?:\(\d+\))?(?![-A-Za-z0-9_.<>#=:])|"
    r"\b(?:failed|failure|fail|succeeded|success|rejected|reject|accepted|timeout|timed out|denied|disconnected|connected|"
    + "|".join(NEGATION_WORDS) + r"|true|false|enabled|disabled|null|none)\b",
    re.IGNORECASE)
NEGATION_RX = re.compile(r"\b(?:" + "|".join(NEGATION_WORDS) + r")\b", re.IGNORECASE)
ANCHOR_MIN = 8
_TOKEN_EDGE = r"[a-z0-9_]"
_KV_WS_RX = re.compile(r"\s*([=:])\s*")


def _low(text: str) -> str:
    """토큰 대조용 정규화: 공백 하나·소문자·`=`/`:` 둘레 공백 제거(`key = v`와 `key=v`는 같다)."""
    return _KV_WS_RX.sub(r"\1", ws(text)).lower()


def _has_token(low_line: str, low_token: str) -> bool:
    """토큰이 줄에 **경계를 두고** 있는가(`status=1`은 `status=10`에 없다). 양쪽 다 `_low` 뒤."""
    return re.search(rf"(?<!{_TOKEN_EDGE}){re.escape(low_token)}(?!{_TOKEN_EDGE})", low_line) is not None

# 타임라인 행 문법(report.row_line·모듈 뷰): `시각 슬롯 레벨 태그 메시지`. 머리 글머리표(`- …`)와 `## ` 제목은 아니다
ROW_RX = re.compile(r"^(?!- )\S+ (?:p\d+|-) [A-Z?-] \S+ ")
SCRIPT_NOTE_RX = re.compile(r"\s*〔script[^〕]*〕")
BIG_SOURCE = 256 * 1024          # 이보다 큰 원문은 인용마다 걸러 낸 행만 본다(difflib가 수 MB에서 느리다)
PREFILTER_ROWS, PREFILTER_WORD = 300, 8
_WORD_RX = re.compile(r"\S{" + str(PREFILTER_WORD) + ",}")


def _label_rx(name: str) -> re.Pattern:
    return re.compile(r"^\s*(?:[-*]\s*)?\**\s*" + re.escape(name) + r"\s*\**\s*[:：]\s*\**\s*(.*)$")


LABEL_RX = {f: _label_rx(f) for f in dict.fromkeys(FIELDS_DEEP + FIELDS_SKILL)}
# `### 가설 1:`·`가설 1 (추정):`·`**가설 1:**`도 머리로 읽는다(모듈 eval 파서와 같은 허용 — 코덱스 리뷰 F4: 두 파서가 달랐다)
HYP_RX = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?\**\s*가설\s*#?(\d+)?\s*(?:\([^)\n]{0,20}\))?\s*\**\s*[:：]\s*\**\s*(.*)$")
NONE_RX = _label_rx("가설 없음")
# 탐색 출력 계약(실사용 `explore.md`) = 가설마다 EXPLORE_FIELDS 다섯 칸. 모듈 eval은 같은 계약에 **선택 칸**을 더 쓴다 — 가설 머리와
# `로그로 확인` 사이의 `원인 층`·`원인 데몬`, 마지막 가설 뒤 꼬리 `가장 유력`·`규칙 제안`. check-output은 그 칸을 읽되 쓰지 않는다.
EXPLORE_OPTIONAL = ("원인 층", "원인 데몬")
EXPLORE_TAIL = ("가장 유력", "규칙 제안")
EXPLORE_RX = {f: _label_rx(f) for f in EXPLORE_FIELDS[1:] + EXPLORE_OPTIONAL + EXPLORE_TAIL}


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


def explore_parse(text: str) -> tuple[dict | None, str | None]:
    """탐색 출력 → ({"none", "next", "hyps": [{n, 가설, 원인 층, 원인 데몬, 로그로 확인: [...], 코드로 추정, 반대 근거, 다음 확인}],
    "top": str|None, "rules": [...]}, None) 또는 (None, 사유).

    `가설 n: …` 블록마다 다섯 칸(`EXPLORE_FIELDS`)이 순서대로 있어야 한다. `원인 층`·`원인 데몬`(가설 머리와 `로그로 확인` 사이)은
    선택이고 없으면 None, `n`은 머리의 번호(없으면 None). 마지막 가설 뒤 `가장 유력:`·`규칙 제안:`은 꼬리(선택)다. 블록이 없으면
    `가설 없음: <이유>`와 `다음 확인:`이 있어야 한다. 칸 밖 줄(빈 줄·설명)은 무시한다. 실사용 check-output과 모듈 eval이 같은 함수를 쓴다.
    """
    m = FENCE_RX.match(text or "")
    lines = (m.group(1) if m else (text or "")).split("\n")
    starts = [i for i, line in enumerate(lines) if HYP_RX.match(line) and not NONE_RX.match(line)]
    if not starts:
        none_at = next((i for i, line in enumerate(lines) if NONE_RX.match(line)), None)
        if none_at is None:
            return None, "가설 머리 없음"
        nxt = next((EXPLORE_RX["다음 확인"].match(line).group(1).strip() for line in lines[none_at + 1:]
                    if EXPLORE_RX["다음 확인"].match(line)), None)
        if nxt is None:
            return None, "가설 없음 뒤 `다음 확인` 칸 없음"
        return {"none": NONE_RX.match(lines[none_at]).group(1).strip(), "next": nxt, "hyps": [], "top": None, "rules": []}, None
    tail_at = next((i for i in range(starts[-1] + 1, len(lines)) if any(EXPLORE_RX[t].match(lines[i]) for t in EXPLORE_TAIL)),
                   len(lines))
    hyps = []
    for k, at in enumerate(starts):
        block = lines[at:starts[k + 1] if k + 1 < len(starts) else tail_at]
        hm = HYP_RX.match(block[0])
        hyp = {"n": int(hm.group(1)) if hm.group(1) else None, "가설": hm.group(2).strip(), "원인 층": None, "원인 데몬": None}
        first = next((j for j in range(1, len(block)) if EXPLORE_RX["로그로 확인"].match(block[j])), None)
        if first is None:
            return None, f"가설 {k + 1}: `로그로 확인` 칸 없음"
        for f in EXPLORE_OPTIONAL:
            j = next((j for j in range(1, first) if EXPLORE_RX[f].match(block[j])), None)
            if j is not None:
                hyp[f] = EXPLORE_RX[f].match(block[j]).group(1).strip()
        pos = first
        for f in EXPLORE_FIELDS[1:]:
            hit = next((j for j in range(pos, len(block)) if EXPLORE_RX[f].match(block[j])), None)
            if hit is None:
                return None, f"가설 {k + 1}: `{f}` 칸 없음"
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
    tail = lines[tail_at:]
    top = next((EXPLORE_RX["가장 유력"].match(line).group(1).strip() for line in tail if EXPLORE_RX["가장 유력"].match(line)), None)
    rules: list[str] = []
    r_at = next((i for i, line in enumerate(tail) if EXPLORE_RX["규칙 제안"].match(line)), None)
    if r_at is not None:
        block = [EXPLORE_RX["규칙 제안"].match(tail[r_at]).group(1).strip(), *tail[r_at + 1:]]
        rules = [im.group(1).strip() for line in block if (im := ITEM_RX.match(line))]
    return {"none": None, "next": None, "hyps": hyps, "top": top, "rules": rules}, None


def parse_explore(text: str) -> dict | None:
    """`explore_parse`의 결과만(사유 없이). check-output(`triagelib.output`)이 쓴다."""
    return explore_parse(text)[0]


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


def _reference_lines(segment: str, lines: list[str]) -> tuple[list[str], str | None]:
    """조각의 기준 줄: 토큰을 뺀 가장 긴 조각(앵커, `ANCHOR_MIN`자 이상)이 든 줄들. 앵커가 없거나 앵커를 담은 줄이 없으면
    (부정어 삭제처럼 변조가 앵커 안에 있을 때) 가장 긴 연속 일치가 `UNCOVERED_MAX`자 이상인 줄 하나로 대신한다."""
    runs = sorted((r.strip() for r in DECISION_TOKEN_RX.sub("\0", segment).split("\0")), key=len, reverse=True)
    anchor = next((r for r in runs if len(r) >= ANCHOR_MIN), None)
    if anchor is not None:
        hits = [line for line in lines if anchor in line]
        if hits:
            return hits, anchor
    best, size = None, 0
    for line in lines:
        m = difflib.SequenceMatcher(None, segment, line, autojunk=False).find_longest_match(0, len(segment), 0, len(line))
        if m.size > size:
            best, size = line, m.size
    return ([best] if best is not None and size >= UNCOVERED_MAX else []), None


def _dropped_negation(segment: str, line: str) -> bool:
    """기준 줄에는 있는데 인용에는 없는 부정어가 인용이 덮는 구간 안에 있나(`data not registered` → `data registered`).
    구간 = 인용과 줄의 4자 이상 일치 블록이 줄에서 차지하는 첫~끝 위치."""
    low_seg, low_line = _low(segment), _low(line)
    blocks = [b for b in difflib.SequenceMatcher(None, low_seg, low_line, autojunk=False).get_matching_blocks()
              if b.size >= COVER_BLOCK]
    if not blocks:
        return False
    start, end = blocks[0].b, blocks[-1].b + blocks[-1].size
    quoted = {m.group(0).lower() for m in NEGATION_RX.finditer(low_seg)}
    return any(m.group(0).lower() not in quoted for m in NEGATION_RX.finditer(low_line[start:end]))


def _decision_tokens_altered(part: str, files_text: str, tags: re.Pattern | None = None) -> bool:
    """인용 조각의 결정 토큰(`DECISION_TOKEN_RX`)이 원문에서 바뀌었나. 이어 붙인 조각마다: 기준 줄(`_reference_lines`) 가운데
    **한 줄**이 토큰을 모두(대소문자 무관, 토큰 경계 `_has_token`) 담고 인용이 빠뜨린 부정어(`_dropped_negation`)가 없으면 그대로다.
    기준 줄이 없으면 판정하지 않는다(False — 그 경우는 최장 일치·덮임 검사가 이미 판정했다). 이 검사는 인용이 원문
    줄 그대로인지만 본다 — 인과 설명이 맞는지는 보증하지 않는다. 조각마다 `msg_part`로 앞머리(시각·슬롯·레벨·태그)를 떼고,
    키가 로그 태그인 `태그: 낱말`(`D/RILJ: …`처럼 앞머리가 아닌 자리)은 토큰으로 보지 않는다(`tags`가 None이면 태그는 그대로)."""
    lines = [line for line in files_text.split("\n") if line]
    # 조각 = 인용이 허용하는 줄 잇기(화살표·한글 연결어·시각, `RUN_SPLIT_RX`)로 나눈 것 — 토큰은 조각마다 그 기준 줄에서 본다
    for segment in (msg_part(seg, tags) for seg in RUN_SPLIT_RX.split(part) if seg and seg.strip()):
        if len(segment) < ANCHOR_MIN:
            continue
        tokens = sorted({_low(m.group(0)) for m in DECISION_TOKEN_RX.finditer(segment)
                         if not (tags is not None and "=" not in m.group(0) and tags.match(m.group(0)))})   # `태그: 낱말`만 뺀다
        refs, _ = _reference_lines(segment, lines)
        if not refs:
            continue
        if not any(all(_has_token(_low(line), t) for t in tokens) and not _dropped_negation(segment, line) for line in refs):
            return True
    return False


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
            if verdict != "fabricated" and _decision_tokens_altered(part, files_text, tags):
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
    """인용 목록 판정 → {"n", "fabricated", "weak", "raw", "first", "verdicts"}. `verdicts`는 항목별 판정
    (ok | weak | fabricated | raw, 입력 순서 — check-output이 가설별로 나눈다).

    `〔script` 메모를 인용한 항목은 지어낸 것으로 센다. `raw_items`(check-output 마스킹이 바꾼 항목 = 원문 값이 든 인용,
    설치 스킬 모드만)는 `raw`로 세고 지어낸 것으로 세지 않는다. 원문이 256KB보다 크면 인용마다 8자 이상 낱말을 공유하는
    행(최대 300행)만 본다.
    """
    from common import masking
    rows = source.split("\n") if len(source) > BIG_SOURCE else None
    res = {"n": len(items), "fabricated": 0, "weak": 0, "raw": 0, "first": None, "verdicts": []}
    for i, item in enumerate(items):
        if i in raw_items:
            verdict = "raw"
        elif "〔script" in item:
            verdict = "fabricated"
        else:
            text = source
            if rows is not None:
                words = _WORD_RX.findall(" ".join(_quote_parts(item, tags)))
                text = _subset(words, rows)
            verdict = evidence_check(item, text, tags)[0]
        res["verdicts"].append(verdict)
        if verdict != "ok":
            res[verdict] += 1
        if verdict == "fabricated" and res["first"] is None:
            res["first"] = masking.mask_brief(item, 40)
    return res
