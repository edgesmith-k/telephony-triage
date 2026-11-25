"""근거 원문 검사(grounding)와 출력 칸 읽기 — `module_eval`(C0 채점)과 `triage.py check-output`(B2 §6)이 같이 쓴다.

`module_eval.py`에서 옮겼다(동작 그대로). `module_eval`은 같은 이름을 다시 내보낸다.
- `parse_fields`: 고정 칸(심층 6칸 `FIELDS_DEEP`, 설치 스킬 4칸 `FIELDS_SKILL`)을 순서대로 읽는다. 심층 다섯째 칸 `후보 확인:`(후보마다
  `- <원인 ID>: 맞음|아님|모름 — <근거>`)은 옛 한 줄 `분석 스킬 의견:`(사내 모듈 레포 옛 형식)도 받는다 — 둘 다 `분석 스킬 의견` 값을 낸다.
- `parse_explore`: 탐색 출력(`가설 n:` 블록 1~3개, 또는 `가설 없음:`).
- `source_text`·`event_rows_text`: 검사 원문(타임라인 행 문법 줄만, events.json 전체 행).
- `evidence_check`·`check_quotes`: 인용이 원문에 있는지(ok | weak | fabricated).
"""

from __future__ import annotations

import difflib
import re

from .fixtures import CAUSE_ID, TYPE_ID

FIELDS_DEEP = ("원인 층", "원인 데몬", "근거", "반대 근거", "후보 확인", "규칙 제안")
CHECK_FIELD, OPINION_FIELD = "후보 확인", "분석 스킬 의견"
# `- DATA-001-01: 맞음 — <근거>`(백틱·굵게·괄호로 감싸도, 원인 미확인 후보는 유형 ID). 앞의 순위(`1위 `·`1.`·`#1`), ID 뒤 괄호
# 설명(`(1위)`), 구분자 `:`·`—`·`=`·`→`·`-`, 판정 뒤 한글 어미·문장부호(`맞음입니다`·`맞음!`)도 받는다. 판정 뒤 설명은 대시·쌍점 뒤 전부
CHECK_ITEM_RX = re.compile(r"^[`*\[(<]*(?:(?:\d+\s*위|#\d+|\d+[.)])\s*[:.)]?\s*[`*\[(<]*)?(" + TYPE_ID + r"(?:-\d{2})?)(?!\d)"
                           r"[`*\])>]*\s*(?:\([^)]{0,40}\))?\s*[:：—–=→-]?\s*\**\s*(맞음|아님|모름)[가-힣]*\**[.!?。]*"
                           r"(?=$|[\s—–:,.(])\s*(?:[—–:-]\s*)?(.*)$")
CHECK_NEW_RX = re.compile(r"^\s*(?:[-*]\s*)?\**\s*후보\s*확인\s*\**\s*[:：]")
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
    # 코덱스 K07: 단위가 붙은 숫자(재시도 간격·제한 시간·신호 세기 — `5000ms`→`9999ms` 변조). 띄어쓰기까지 원문 그대로여야 한다
    r"\b\d+(?:\.\d+)?\s?(?:ms|msec|millis|s|sec|secs|seconds?|min|mins|minutes?|dbm|db)(?![A-Za-z0-9_])|"
    r"\b(?:failed|failure|fail|succeeded|success|rejected|reject|accepted|timeout|timed out|denied|disconnected|connected|"
    + "|".join(NEGATION_WORDS) + r"|true|false|enabled|disabled|null|none)\b",
    re.IGNORECASE)
NEGATION_RX = re.compile(r"\b(?:" + "|".join(NEGATION_WORDS) + r")\b", re.IGNORECASE)
ANCHOR_MIN = 8
_TOKEN_EDGE = r"[a-z0-9_]"
_KV_WS_RX = re.compile(r"\s*([=:])\s*")


def _low(text: str) -> str:
    """토큰 대조용 정규화: 공백 하나·소문자·`=`/`:` 둘레 공백 제거(`key = v`와 `key=v`는 같다)."""
    return _low_folded(ws(text))


def _low_folded(folded: str) -> str:
    """`_low`에서 공백 접기(`ws`)를 뺀 것 — 이미 `ws`를 거친 글(큰 원문은 행마다 한 번만 접는다)."""
    return _KV_WS_RX.sub(r"\1", folded).lower()


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
LABEL_RX[CHECK_FIELD] = re.compile(r"^\s*(?:[-*]\s*)?\**\s*(?:후보\s*확인|분석\s*스킬\s*의견)\s*\**\s*[:：]\s*\**\s*(.*)$")
# `### 가설 1:`·`가설 1 (추정):`·`**가설 1:**`도 머리로 읽는다(모듈 eval 파서와 같은 허용 — 코덱스 리뷰 F4: 두 파서가 달랐다)
HYP_RX = re.compile(r"^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?\**\s*가설\s*#?(\d+)?\s*(?:\([^)\n]{0,20}\))?\s*\**\s*[:：]\s*\**\s*(.*)$")
NONE_RX = _label_rx("가설 없음")
# 탐색 출력 계약(실사용 `explore.md`) = 가설마다 EXPLORE_FIELDS 다섯 칸. 모듈 eval은 같은 계약에 **선택 칸**을 더 쓴다 — 가설 머리와
# `로그로 확인` 사이의 `원인 층`·`원인 데몬`, 마지막 가설 뒤 꼬리 `가장 유력`·`규칙 제안`. check-output은 그 칸을 읽되 쓰지 않는다.
EXPLORE_OPTIONAL = ("원인 층", "원인 데몬")
EXPLORE_TAIL = ("가장 유력", "규칙 제안")
EXPLORE_RX = {f: _label_rx(f) for f in EXPLORE_FIELDS[1:] + EXPLORE_OPTIONAL + EXPLORE_TAIL}
# 11/25 기대 체인(explore.md 쓰는 것): 가설 블록 안 어디에 있어도 읽는 선택 칸. `기대 체인:` 뒤 표 행(`| 단계 | 기대 | 기대 근거 |
# 관측 줄 | 일치 |`), `찾았는데 없음:` 뒤 목록, 나머지는 한 줄. 없으면 None. 형식 실패로 만들지 않는다(check-output이 경고만 낸다)
CHAIN_LABELS = ("기대 체인", "첫 갈라짐", "찾았는데 없음", "메커니즘 재계산", "책임 경계")
CHAIN_RX = {f: _label_rx(f) for f in CHAIN_LABELS}
STEP_NUM_RX = re.compile(r"(\d+)")
# 일치 칸: 앞부분만 본다(`false — 재요청 없음`·`**불일치**.`). 불일치를 일치보다 먼저. 기호 ❌✗ = false, ✅✓ = true
_VERDICT_RX = re.compile(r"^(불일치|거짓|false|일치|참|true)", re.IGNORECASE)
_VERDICT = {"불일치": "false", "거짓": "false", "false": "false", "일치": "true", "참": "true", "true": "true"}
# 관측 칸이 인용인가: 따옴표·앞뒤 `(window-n)`·`[…]` 표시를 뗀 뒤 시각(`HH:MM:SS`, logcat `MM-DD HH:MM:SS`, ISO 날짜+시각)으로 시작할 때만.
# `없음(찾은 곳 …)`·`찾지 못함`·`—`·`N/A`·`미관측`처럼 시각이 없는 칸은 인용이 아니다(원문에 없음·약함으로 세지 않는다)
_OBS_TAG_RX = re.compile(r"^\s*[(\[][^()\[\]]{0,40}[)\]]\s*|\s*[(\[]window-\d+(?:\.md)?[)\]]\s*$", re.IGNORECASE)
_OBS_TIME_RX = re.compile(r"^(?:\d{4}-\d{2}-\d{2}[T ]|\d{2}-\d{2}\s+)?\d{2}:\d{2}:\d{2}")
# sim1122 F2: `1위 판단: <원인 ID> 적합|부적합|모름 — <이유>`(채택 원인이 이번 실패를 설명하는지, 선택 칸, 출력 어디에 있어도 첫
# `1위 판단` 줄). ID는 값 앞·머리 괄호(`1위 판단(<ID>):`)·없음(옛 형식) 모두 읽고, 값 뒤 문장부호도 받는다. 형식 실패로 만들지 않는다
TOP_FIT_HEAD_RX = re.compile(r"^\s*(?:[-*]\s*)?\**\s*1위\s*판단")
_ID = r"[`*\[(<]*(" + CAUSE_ID + r")(?!\d)[`*\])>]*"
TOP_FIT_RX = re.compile(r"^\s*(?:[-*]\s*)?\**\s*1위\s*판단\s*(?:" + _ID + r")?\s*\**\s*[:：]\s*\**\s*(?:" + _ID + r"\s*[:：]?\s*)?"
                        r"(부적합|적합|모름)(?=$|[\s—–:,.(*!])\**[.!]?\s*(?:[—–:-]\s*)?(.*)$")


def top_fit(lines: list[str]) -> dict | None:
    """`1위 판단` 칸 → {"fit": 적합|부적합|모름, "cause": 원인 ID | None, "why": 이유} | 줄은 있는데 못 읽으면 {"fit": None, …} | None."""
    head = next((line for line in lines if TOP_FIT_HEAD_RX.match(line)), None)
    if head is None:
        return None
    m = TOP_FIT_RX.match(head)
    if not m:
        return {"fit": None, "cause": None, "why": ws(head)[:120]}
    return {"fit": m.group(3), "cause": m.group(1) or m.group(2), "why": m.group(4).strip()}


def _top_fit_key(lines: list[str]) -> dict:
    got = top_fit(lines)
    return {"top_fit": got} if got else {}


def ws(text: str) -> str:
    return WS_RX.sub(" ", text).strip()


# --- 메시지 정규화 (S4·S7, C0 설계 §9.3) ------------------------------------------------------------------

def log_tags(text: str) -> list[str]:
    return sorted(set(TAG_FIND_RX.findall(text)), key=lambda t: (-len(t), t))


def tag_rx(tags: list[str]) -> re.Pattern | None:
    if not tags:
        return None
    return re.compile(r"^<?(" + "|".join(map(re.escape, tags)) + r")>?(?:\[\d+\])?:?\s+")      # group(1) = 태그 이름(`_quote_head`)


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
        later = [i for i in hits[f] if i > idx[-1]]
        if not later:
            return None, lines, None
        nxt = later[0]
        if f == CHECK_FIELD and fields is FIELDS_DEEP:     # `분석 스킬 의견:`과 `후보 확인:`이 다 있으면 새 블록(규칙 제안 앞)
            rule = next((i for i in hits[fields[-1]] if i > idx[-1]), None)
            nxt = next((i for i in later if CHECK_NEW_RX.match(lines[i]) and (rule is None or i < rule)), nxt)
        idx.append(nxt)
    label_lines = sorted({i for f in fields for i in hits[f]})
    out: dict = {}
    rule_block = None
    for f, i in zip(fields, idx):
        rest = rx[f].match(lines[i]).group(1).strip()
        if f == CHECK_FIELD and fields is FIELDS_DEEP:
            end = next((j for j in label_lines if j > i), len(lines))
            items = [im.group(1).strip() if (im := ITEM_RX.match(line)) else line.strip()      # 글머리표 없는 줄도
                     for line in lines[i + 1:end] if line.strip() and not line.strip().startswith("```")]
            if not items and rest and CHECK_ITEM_RX.match(rest):      # 라벨 줄에 판정을 같이 쓴 꼴(`후보 확인: X: 아님 — …`)
                items = [rest]
            out[f] = _checks(items)
            read = [c for c in out[f] if c["verdict"] != "?"]
            out[OPINION_FIELD] = _opinion(read) if read else rest
        elif f in LIST_FIELDS:
            end = next((j for j in label_lines if j > i), len(lines)) if f == "근거" else len(lines)
            block = [rest, *lines[i + 1:end]]
            out[f] = [im.group(1).strip() for line in block if (im := ITEM_RX.match(line))]
            if f == "규칙 제안":
                out[f] = _same_line_rule(rest) + out[f]
                rule_block = range(i, end)
        else:
            out[f] = rest
    return out, lines, rule_block


def _checks(items: list[str]) -> list[dict]:
    """`후보 확인` 목록 줄 → [{cause, verdict, why}]. 읽지 못한 줄은 `{cause: None, verdict: "?", why: <원문>}`으로 남긴다
    (check-output이 report에 그대로 싣고 경고한다 — 빈 의견이 조용히 남지 않게)."""
    out = []
    for item in items:
        m = CHECK_ITEM_RX.match(item)
        out.append({"cause": m.group(1), "verdict": m.group(2), "why": m.group(3).strip()} if m
                   else {"cause": None, "verdict": "?", "why": item})
    return out


def _opinion(checks: list[dict]) -> str:
    """후보 확인 → 옛 `분석 스킬 의견` 값: 첫 `맞음` 후보 `<ID> — <근거>`(check-output이 채택 원인과 다르면 counter로 남긴다),
    맞음이 없으면 `맞는 후보 없음 — <ID 판정; …>`(ID로 시작하지 않는다)."""
    hit = next((c for c in checks if c["verdict"] == "맞음"), None)
    if hit:
        return f"{hit['cause']} — {hit['why']}".rstrip(" —")
    return "맞는 후보 없음 — " + "; ".join(f"{c['cause']} {c['verdict']}" for c in checks)


RULE_NONE_RX = re.compile(r"^[\s*`]*(?:해당\s*)?없음")     # `없음`·`해당 없음`(뒤 설명 무엇이든) = 제안 아님


def _same_line_rule(rest: str) -> list[str]:
    """`규칙 제안: [이슈 DB] …`처럼 칸 이름 줄에 바로 쓴 제안 하나(목록 기호 없이). 비었거나 `없음`·`해당 없음`이거나 목록 줄이면 []."""
    rest = (rest or "").strip()
    return [] if not rest or ITEM_RX.match(rest) or RULE_NONE_RX.match(rest) else [rest]


def parse_fields(text: str, fields: tuple[str, ...] = FIELDS_DEEP) -> dict | None:
    """답에서 고정 칸. 마지막 첫 칸 줄부터 칸이 순서대로 있어야 한다(없으면 None). 근거·규칙 제안은 항목 목록."""
    return _parse(text, fields)[0]


def explore_parse(text: str) -> tuple[dict | None, str | None]:
    """탐색 출력 → ({"none", "next", "hyps": [{n, 가설, 원인 층, 원인 데몬, 로그로 확인: [...], 코드로 추정, 반대 근거, 다음 확인}],
    "top": str|None, "rules": [...], "top_fit"?: {fit, why}(칸이 있을 때만)}, None) 또는 (None, 사유).

    `가설 n: …` 블록마다 다섯 칸(`EXPLORE_FIELDS`)이 순서대로 있어야 한다. `원인 층`·`원인 데몬`(가설 머리와 `로그로 확인` 사이)은
    선택이고 없으면 None, `n`은 머리의 번호(없으면 None). 가설마다 `chain_fields`(기대 체인 칸, 블록 어디든)를 더한다. 마지막 가설 뒤 `가장 유력:`·`규칙 제안:`은 꼬리(선택)다. 블록이 없으면
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
        return ({"none": NONE_RX.match(lines[none_at]).group(1).strip(), "next": nxt, "hyps": [], "top": None, "rules": [],
                 **_top_fit_key(lines)}, None)
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
                            if any(EXPLORE_RX[g].match(block[j]) for g in EXPLORE_FIELDS[2:])
                            or any(rx.match(block[j]) for rx in CHAIN_RX.values())), len(block))
                items = [im.group(1).strip() for line in block[hit + 1:end] if (im := ITEM_RX.match(line))]
                hyp[f] = ([rest] if rest else []) + items
                pos = end
            else:
                hyp[f] = rest
                pos = hit + 1
        hyps.append({**hyp, **chain_fields(block)})
    tail = lines[tail_at:]
    top = next((EXPLORE_RX["가장 유력"].match(line).group(1).strip() for line in tail if EXPLORE_RX["가장 유력"].match(line)), None)
    rules: list[str] = []
    r_at = next((i for i, line in enumerate(tail) if EXPLORE_RX["규칙 제안"].match(line)), None)
    if r_at is not None:
        block = [EXPLORE_RX["규칙 제안"].match(tail[r_at]).group(1).strip(), *tail[r_at + 1:]]
        rules = _same_line_rule(block[0]) + [im.group(1).strip() for line in block if (im := ITEM_RX.match(line))]
    return {"none": None, "next": None, "hyps": hyps, "top": top, "rules": rules, **_top_fit_key(lines)}, None


def _cells(line: str) -> list[str] | None:
    s = line.strip().replace("｜", "|")       # 전각 세로줄도 칸 구분
    if not s.startswith("|"):
        return None
    s = s[1:-1] if s.endswith("|") and len(s) > 1 else s[1:]
    return [c.strip() for c in s.split("|")]


def _verdict(cell: str) -> str:
    s = cell.strip().strip("`*_ ").strip()
    if s.startswith(("❌", "✗")):
        return "false"
    if s.startswith(("✅", "✓")):
        return "true"
    m = _VERDICT_RX.match(s)
    return _VERDICT[m.group(1).lower()] if m else "모름"


def _chain_row(cells: list[str], cols: dict | None) -> dict | None:
    """표 행 → {단계, 기대, 근거, 관측, 일치}. 첫 칸에서 단계 번호를 못 읽으면(머리·구분 행 `| **단계** |`·`| # |`·`|-|-|`) None.
    머리 행에서 찾은 열 위치(`cols`)가 있고 칸 수가 같으면 그 위치로, 아니면 5열 자리(관측 칸의 `|`는 가운데 칸을 이어 붙인다)."""
    m = STEP_NUM_RX.search(cells[0])
    if not m:
        return None
    if cols and len(cells) == cols["n"]:
        pick = {k: cells[i] if i is not None else "" for k, i in cols.items() if k != "n"}
    elif len(cells) >= 5:
        pick = {"기대": cells[1], "근거": cells[2], "관측": "|".join(cells[3:-1]).strip(), "일치": cells[-1]}
    else:
        return None
    return {"단계": int(m.group(1)), "기대": pick["기대"], "근거": pick["근거"], "관측": pick["관측"], "일치": _verdict(pick["일치"])}


def _header_cols(cells: list[str]) -> dict | None:
    """머리 행이면 열 이름 → 위치(`관측`·`일치`가 있어야 머리로 본다), 아니면 None."""
    names = [c.strip("`*_ ") for c in cells]
    find = lambda pred: next((i for i, c in enumerate(names) if pred(c)), None)      # noqa: E731
    obs, match = find(lambda c: "관측" in c), find(lambda c: "일치" in c)
    if obs is None or match is None:
        return None
    return {"n": len(cells), "기대": find(lambda c: c == "기대"), "근거": find(lambda c: "근거" in c), "관측": obs, "일치": match}


def chain_fields(block: list[str]) -> dict:
    """가설 블록의 `CHAIN_LABELS` 칸(각 첫 줄만). `기대 체인` = [{단계: int, 기대, 근거, 관측, 일치: true|false|모름}]
    (`_chain_row` — 단계 번호 없는 행은 건너뛴다. 표 중간 빈 줄은 다음 줄이 `|`면 이어 읽는다), `찾았는데 없음` = 항목 목록."""
    out: dict = dict.fromkeys(CHAIN_LABELS)
    for i, line in enumerate(block):
        f = next((f for f in CHAIN_LABELS if CHAIN_RX[f].match(line)), None)
        if f is None or out[f] is not None:
            continue
        rest = CHAIN_RX[f].match(line).group(1).strip()
        if f in ("기대 체인", "찾았는데 없음"):
            got: list = [] if f == "기대 체인" or not rest or RULE_NONE_RX.match(rest) else [rest]
            cols, seen = None, False
            for j in range(i + 1, len(block)):
                nxt = block[j]
                if not nxt.strip():
                    following = next((x for x in block[j + 1:] if x.strip()), "")
                    if seen and not (f == "기대 체인" and following.strip().startswith(("|", "｜"))):
                        break
                    continue
                cells = _cells(nxt) if f == "기대 체인" else None
                im = ITEM_RX.match(nxt) if f == "찾았는데 없음" else None
                if f == "기대 체인" and cells is not None:
                    seen = True
                    row = _chain_row(cells, cols)
                    if row is not None:
                        got.append(row)
                    elif cols is None:
                        cols = _header_cols(cells)
                elif im:
                    seen = True
                    got.append(im.group(1).strip())
                else:
                    break
            out[f] = got
        else:
            out[f] = rest
    return out


def _obs_quote(obs: str) -> str | None:
    """관측 칸 → 인용(따옴표·앞뒤 표시를 뗀 글)이면 그 글, 시각으로 시작하지 않으면 None."""
    s = QUOTE_CHARS_RX.sub("", obs).strip()
    for _ in range(2):
        s = _OBS_TAG_RX.sub("", s).strip()
    return s if _OBS_TIME_RX.match(s) else None


def chain_quotes(hyp: dict) -> list[str]:
    """`기대 체인` 관측 칸 중 인용(`_obs_quote`) — check-output이 `로그로 확인`과 같은 근거 원문 검사를 한다."""
    return [q for r in hyp.get("기대 체인") or [] if (q := _obs_quote(r["관측"])) is not None]


def parse_explore(text: str) -> dict | None:
    """`explore_parse`의 결과만(사유 없이). check-output(`triagelib.output`)이 쓴다."""
    return explore_parse(text)[0]


# --- 근거 원문 검사 ---------------------------------------------------------------------------------------

def _quote_parts(item: str, tags) -> list[str]:
    q = QUOTE_CHARS_RX.sub("", item)
    q = QUOTE_CUT_RX.split(q, maxsplit=1)[0]
    q = msg_part(q, tags)
    return [p.strip() for p in ELLIPSIS_RX.split(q) if p.strip()]


_HEAD_FIELDS = (None, "time", None, "slot", "level")          # STRIP_RX 순서: 날짜·시각·host·슬롯·레벨
_HEAD_TAG_RX = re.compile(r"^<?([^\s<>\[\]:]+)>?(?:\[\d+\])?:?\s+")


def _quote_head(item: str, tags) -> dict[str, str]:
    """인용 앞머리(F-A01-min): `msg_part`가 떼는 시각·슬롯·레벨·태그 가운데 인용에 있는 것. 시각이나 슬롯이 있을 때만 머리다 —
    레벨·태그만 있는 앞머리는 메시지 첫 글자(`E auth vector …`)일 수 있어 보지 않는다(빈 dict). 레벨까지 적었으면 다음 낱말은
    원문에 없는 태그라도 태그 자리다(행 문법 `시각 슬롯 레벨 태그 메시지`) — 지어낸 태그도 대조에 걸리게."""
    s = ws(QUOTE_CUT_RX.split(QUOTE_CHARS_RX.sub("", item), maxsplit=1)[0])
    head: dict[str, str] = {}
    for name, rx in zip(_HEAD_FIELDS, STRIP_RX):
        if m := rx.match(s):
            if name:
                head[name] = m.group(0).strip()
            s = s[m.end():]
    if "time" not in head and "slot" not in head:
        return {}
    m = tags.match(s) if tags is not None else None
    if m is None and "level" in head:
        m = _HEAD_TAG_RX.match(s)
    if m is not None:
        head["tag"] = m.group(1)
    return head


def _row_head_ok(row: str, head: dict[str, str]) -> bool:
    """행(`시각 슬롯 레벨 태그 메시지`)의 머리가 인용 머리와 맞나. 시각은 짧은 쪽이 긴 쪽의 앞부분이면 맞다(모델이 ms를 줄이거나
    원본 로그의 µs까지 적는 정상 사례), 슬롯·레벨은 정확히. 태그는 같거나 행 메시지의 첫 낱말이 그 태그(`<t>`·`t[12]`·`t:` 꼴
    포함)이면 맞다(메시지 첫 낱말이 다른 행의 태그 이름일 때 태그로 잘못 읽은 경우). 앞부분만 같은 낱말(`SET`·`SETUP_…`)은 아니다."""
    cols = row.split(" ", 4)
    if len(cols) < 5:
        return False
    clock, slot, level, tag, msg = cols
    t, want = head.get("time"), head.get("tag")
    return ((t is None or clock.startswith(t) or t.startswith(clock)) and head.get("slot", slot) == slot
            and head.get("level", level) == level
            and (want is None or want == tag or re.match(rf"<?{re.escape(want)}>?(?:\[\d+\])?:?(?:\s|$)", msg) is not None))


def _head_ok(head: dict[str, str], parts: list[str], rows: list[str], ws_text: str, tags) -> bool:
    """머리(`_quote_head`)를 적은 인용이면, 머리가 맞는 행에 인용 첫 조각(첫 `…`·화살표·한글 낱말 앞 메시지)이 있나. 머리 없는
    인용은 True(동작 불변). `rows`는 원문 전체 행, `ws_text`는 그 행마다 공백을 접어 이은 글, `parts`는 `_quote_parts` 결과.
    ① 머리 맞는 행에 조각이 그대로(공백 차이만) 있으면 True. ② 조각이 원문 어딘가에 그대로 있는데 ①이 아니면 머리를 바꿔 적은
    것 — False. ③ 조각 자체가 그대로는 없으면(표기 차이) 머리 맞는 행만 놓고 `evidence_check`. 머리 행은 늘 원문 전체에서
    찾는다(머리 칸 비교뿐이라 싸다) — 큰 원문 축소 검색 300행 안에서만 찾으면 선검사·전체 경로와 판정이 갈렸다."""
    seg = next((s.strip() for s in RUN_SPLIT_RX.split(parts[0]) if s.strip()), "") if parts else ""
    if not head or not seg:
        return True
    hrows = [ws(r) for r in rows if _row_head_ok(r, head)]      # 행 머리 칸은 홑 공백(`ROW_RX`) — 걸러 낸 행만 접는다
    if any(seg in r for r in hrows):
        return True
    if seg in ws_text:
        return False
    if len(hrows) > PREFILTER_ROWS:
        # ponytail: 머리 맞는 행이 많으면(슬롯만 적은 인용) difflib 비용 때문에 8자 이상 낱말 공유 첫 300행만 — 그 밖의 줄이면 weak 오탐
        hrows = [r for r in _subset(_WORD_RX.findall(seg), hrows).split("\n") if r]
    return bool(hrows) and evidence_check(seg, "\n".join(hrows), tags)[0] == "ok"


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
    files_text = QUOTE_CHARS_RX.sub("", files_text)      # 인용 쪽(`_quote_parts`)과 같이 따옴표를 뗀다 — `a:"State"` 줄을 그대로 인용해도 지어낸 것이 되던 것
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
    if not detail:      # 따옴표·생략표만 남은 인용(`...`·`""`·시각과 `...`)은 확인한 것이 없다 — ok가 아니다(코덱스 K03, 정상 근거로 안 쓴다)
        worst = "weak"
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


# 원문 줄 정규식(파서와 같은 것 — Android threadtime·time, oFono ISO·BSD·BusyBox)과 등급→레벨 표. common은 플랫폼을 import하지
# 않으므로(17-platforms §1-2) 위층(`triagelib.output`)이 `platforms.raw_line_patterns()`를 넣어 준다. 넣기 전에는 원문 모양을 읽지 않는다
_RAW_RXS: tuple[tuple, dict] = ((), {})


def set_raw_patterns(patterns: tuple[tuple, dict]) -> None:
    global _RAW_RXS
    _RAW_RXS = patterns


def raw_patterns_set() -> bool:
    return bool(_RAW_RXS[0])


def _raw_rxs() -> tuple[tuple, dict]:
    return _RAW_RXS


def _raw_fields(line: str) -> dict | None:
    """원문 모양 한 줄 → {time, level, tag, msg}(시각은 로그에 적힌 그대로, 레벨 없는 syslog는 `-`). 모양이 다르면 None."""
    s = ws(QUOTE_CHARS_RX.sub("", line or ""))
    rxs, sev = _raw_rxs()
    for rx in rxs:
        m = rx.match(s)
        if not m:
            continue
        g = m.groupdict()
        level = g.get("level") or sev.get(g.get("sev") or "", "-")
        return {"time": f"{g['h']}:{g['mi']}:{g['s']}" + (f".{g['frac']}" if g.get("frac") else ""), "level": level,
                "tag": (g.get("tag") or g.get("ident") or "").strip(), "msg": g.get("msg") or ""}
    return None


def raw_row(line: str) -> str | None:
    """사본 한 줄(또는 그 모양으로 적은 인용) → 행 문법 `시각 - 레벨 태그 메시지`(시각은 로그에 적힌 그대로, 슬롯 `-`).
    모양이 다르면 None. 사본 줄과 원문 모양 인용을 같은 식으로 바꿔 머리(시각·레벨·태그) 대조가 같은 칸끼리 되게 한다."""
    f = _raw_fields(line)
    return f"{f['time']} - {f['level']} {f['tag']} {f['msg']}".rstrip() if f else None


COPY_ROWS_PER_QUOTE = 50    # 인용마다 사본에서 낱말을 많이 함께 가진 줄
COPY_ROWS_EXACT_MAX = 200   # 인용 메시지 조각이 그대로 든 줄(위 상한 밖에 늘 더한다, 이만큼까지)


def _copy_want(q: str) -> tuple[set, list[str], str | None]:
    """인용 하나 → (찾을 낱말, 그대로 찾을 메시지 조각, 인용 시각)."""
    f = _raw_fields(q)
    if f:
        parts, qt = [p.strip() for p in ELLIPSIS_RX.split(ws(f["msg"])) if p.strip()], f["time"]
    else:
        parts, head = _quote_parts(q, None), _quote_head(q, None)
        qt, tag = head.get("time"), head.get("tag")
        if tag and parts and parts[0].startswith(tag + " "):      # 행 모양 인용의 태그 칸은 원문 줄에 `태그:`로 있다
            parts[0] = parts[0][len(tag) + 1:]
    keys = set()
    for part in parts:
        words = _WORD_RX.findall(part)
        keys.update(words or ([part] if len(part) >= 4 else []))
    return keys, [p for p in parts if len(p) >= 8], qt


def copy_rows(texts: list[str], quotes: list[str]) -> str:
    """마스킹 사본 글(`texts`)에서 인용마다 고른 줄을 `raw_row`로 바꾼 행들:
    - 인용 메시지 조각(8자 이상)이 그대로 든 줄은 늘(`COPY_ROWS_EXACT_MAX`줄까지),
    - 그 밖에 인용의 8자 이상 낱말(없으면 4자 이상 조각)을 가장 많이 함께 가진 줄 `COPY_ROWS_PER_QUOTE`줄.
    둘 다 같은 순위면 인용과 시각이 같은 줄, 그다음 앞 줄. 후보 줄은 낱말 정규식 한 번으로 찾고(큰 사본에서도 인용 수만큼만),
    줄마다 낱말은 하나씩 `in`으로 센다(겹치는 낱말도). 고른 줄과 인용의 대조(값 바꿈·지어냄)는 `check_quotes`가 한다."""
    want = [_copy_want(q) for q in quotes]
    every = set().union(*(k for k, _f, _t in want)) if want else set()
    if not every:
        return ""
    rx = re.compile("|".join(map(re.escape, sorted(every, key=len, reverse=True))))
    lines: dict[tuple[int, int], str] = {}          # (사본 순번, 줄 시작) → 줄(낱말이 하나라도 든 줄만)
    for k, text in enumerate(texts):
        for m in rx.finditer(text):
            a = text.rfind("\n", 0, m.start()) + 1
            if (k, a) not in lines:
                b = text.find("\n", a)
                lines[(k, a)] = text[a:b if b >= 0 else len(text)]
    out: dict[str, None] = {}
    for keys, frags, qt in want:
        exact, scored = [], []
        for pos, line in lines.items():
            other = not qt or qt not in line[:48]       # 시각이 인용과 다른 줄은 같은 순위에서 뒤로
            if frags and all(f in line for f in frags):
                exact.append((other, pos))
            elif n := sum(1 for w in keys if w in line):
                scored.append((-n, other, pos))
        picked = [x[-1] for x in sorted(exact)[:COPY_ROWS_EXACT_MAX]] + [x[-1] for x in sorted(scored)[:COPY_ROWS_PER_QUOTE]]
        for pos in picked:
            row = raw_row(lines[pos])
            if row:
                out[row] = None
    return "\n".join(out)


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


def _part_rows(parts: list[str], rows: list[str], ws_rows: list[str]) -> list[str]:
    """조각이 든 행(`ws_rows` = 행마다 공백 접은 글, 조각마다 첫 `PREFILTER_ROWS`행까지, 원문 순서) — 경계만 틀린 줄(`status=10`)도
    대조에 들게. 행은 한 번만 훑는다(행마다 아직 상한이 안 찬 조각을 본다)."""
    left = dict.fromkeys(parts, PREFILTER_ROWS)
    out = []
    for row, w in zip(rows, ws_rows):
        hit = [p for p in left if p in w]
        if hit:
            out.append(row)
            for p in hit:
                left[p] -= 1
                if not left[p]:
                    del left[p]
            if not left:
                break
    return out


def check_quotes(items: list[str], source: str, tags, *, raw_items: frozenset[int] = frozenset(),
                 alts: list[str | None] | None = None) -> dict:
    """인용 목록 판정 → {"n", "fabricated", "weak", "raw", "first", "verdicts"}. `verdicts`는 항목별 판정
    (ok | weak | fabricated | raw, 입력 순서 — check-output이 가설별로 나눈다).

    `〔script…〕` 메모만 인용한 항목은 지어낸 것으로 센다(줄 끝 메모까지 복사한 인용은 메모를 떼고 본다). `raw_items`(check-output 마스킹이 바꾼 항목 = 원문 값이 든 인용,
    설치 스킬 모드만)는 `raw`로 세고 지어낸 것으로 세지 않는다. 원문이 256KB보다 크면 먼저 인용 조각마다 원문 한 줄 안에
    **토큰 경계를 두고**(`_has_token`, 행마다 `_low` — 공백·대소문자·`=`/`:` 둘레 차이만 허용) 있는지 보고, 모두 있으면 ok다
    (FR-01: 부분 문자열만 보면 `status=10`→`status=1`·`disconnected`→`connected` 같은 변조를 ok로 봤다). 아니면 조각이 든
    행(조각마다 최대 300행)과 8자 이상 낱말을 공유하는 행(최대 300행)으로 `evidence_check`를 돈다.
    ok인 인용이 시각이나 슬롯 머리(레벨·태그는 그와 함께 적었을 때만)를 적었으면 머리까지 맞는 행이 원문 전체에 있어야 ok,
    없으면 weak다(`_head_ok`, F-A01-min). `alts[i]`(있으면, 탐색의 원문 모양 인용을 `raw_row`로 바꾼 것)는 인용이 ok가 아닐 때
    한 번 더 판정해 나은 쪽(ok > weak > fabricated)을 쓴다.
    """
    from common import masking
    source = QUOTE_CHARS_RX.sub("", source)      # 인용 쪽과 같이 따옴표를 뗀다(행 찾기·머리 대조·`evidence_check`가 같은 글을 본다)
    big = len(source) > BIG_SOURCE
    rows = source.split("\n")
    ws_rows = [ws(row) for row in rows]
    ws_lines = "\n".join(ws_rows)                  # 줄마다 공백 접기(`WS_RX`가 개행도 접으므로)
    # 행마다 `_low` 뒤 잇기 — 통째로 하면 `=`/`:` 둘레 공백 제거가 개행을 넘는다. 조각·토큰엔 개행이 없어 일치는 한 줄 안이다
    low_lines = "\n".join(_low_folded(w) for w in ws_rows) if big else ""
    res = {"n": len(items), "fabricated": 0, "weak": 0, "raw": 0, "first": None, "verdicts": []}

    def judge(item: str) -> str:
        parts = _quote_parts(item, tags)
        if big and parts and all(_has_token(low_lines, _low(p)) for p in parts):
            verdict = "ok"
        else:
            # ponytail: 공백 말고도 표기가 다른 인용은 축소 검색(조각이 든 행 + 8자 이상 낱말 공유 첫 300행)에 기대므로, 그 밖의 줄을 인용하면 여전히 fabricated 오탐
            text = source if not big else "\n".join(dict.fromkeys(
                _part_rows(parts, rows, ws_rows) + _subset(_WORD_RX.findall(" ".join(parts)), rows).split("\n")))
            verdict = evidence_check(item, text, tags)[0]
        # F-A01-min: 메시지는 맞는데 적은 머리(시각·슬롯·태그)가 맞는 행이 없으면 약함(fabricated는 정밀도만 다른 정상 시각에서 오탐)
        if verdict == "ok" and not _head_ok(_quote_head(item, tags), parts, rows, ws_lines, tags):
            verdict = "weak"
        return verdict

    rank = {"ok": 0, "weak": 1, "fabricated": 2}
    for i, item in enumerate(items):
        if i in raw_items:
            verdict = "raw"
        elif "〔script" in SCRIPT_NOTE_RX.sub("", item) or not SCRIPT_NOTE_RX.sub("", item).strip():
            verdict = "fabricated"          # 메모만(또는 닫히지 않은 메모를) 인용했다
        else:
            item = SCRIPT_NOTE_RX.sub("", item).rstrip()      # 줄 끝 메모까지 복사한 인용은 본 줄로 판정한다(sim1122 RP-13)
            verdict = judge(item)
            alt = SCRIPT_NOTE_RX.sub("", (alts[i] if alts and i < len(alts) else None) or "").rstrip()
            if verdict != "ok" and alt and alt != item:
                verdict = min(verdict, judge(alt), key=rank.__getitem__)
        res["verdicts"].append(verdict)
        if verdict != "ok":
            res[verdict] += 1
        if verdict == "fabricated" and res["first"] is None:
            res["first"] = masking.mask_brief(item, 40)
    return res
