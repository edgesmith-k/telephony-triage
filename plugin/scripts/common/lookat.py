"""기준 줄(`triage.py run --look-at`) 찾기 — 순수 함수, 표준 라이브러리만 (11/16 설계 §2·v2, VERIFY P2 21~23).

사용자가 붙인 로그 줄이나 `<IPC 이름> (token=0x…)`을 로그에서 찾아 그 줄의 로그 시각을 분석 구간의 중심으로 쓴다.
찾는 순서: ① IPC 이름과 token이 같은 레코드(`common.ipcseq`) ② 이름 없이 token만 주면 token이 같은 레코드 ③ 그 밖은 정리한 글을
로그 줄(`태그: 메시지`)에 부분 일치(대소문자 무시, 8자 미만이거나 마스킹 토큰 밖 조각이 4자 미만이면 찾지 않음). 비교 전에 양쪽 마스킹 토큰(`<IP#7>`)을 번호 없이
접는다(`modulefilter._TOKEN_FOLD`와 같은 식) — 입력과 로그를 다른 마스커가 가려 번호가 달라도 맞게. 후보가 여럿이면 기준 시각(Jira 발생
시각)에 가장 가까운 것, 기준 시각이 없으면 마지막 것(시험은 FAIL에서 멈추므로 실패는 보통 로그 끝쪽)을 고르고 고른 방식을 남긴다.

자격 검사(단계 5)용: 일치 줄을 같은 요청끼리 묶어(`group_places` — IPC REQ→RSP, RIL serial 짝) "몇 곳"인지 센다. 붙여 넣은 줄에
logcat 시각이 있으면(`stamp`) 그 시각과 같은 곳을 먼저 고른다(`parse_logcat ipc --find`, 같은 단말 로그 시계라 유효).
"""

from __future__ import annotations

import re
from datetime import datetime

from common import logtime


PRE_SEC, POST_SEC = 30, 300      # 분석 구간 = 기준 줄 시각 −30초 ~ +300초 (설정 키 대신 상수, VERIFY P2 20)
TEXT_MAX = 300                   # --look-at·--look-note 글자 수 상한
TEXT_MIN = 8                     # 부분 일치로 찾는 최소 글자 수(접은 뒤)
AT_MAX = 8                       # 보이는 일치 시각 수(token은 다시 쓰일 수 있어 모든 위치를 보인다)
PIECE_MIN = 4                    # 부분 일치 사전 필터: 마스킹 토큰 밖 조각 중 가장 긴 것이 이보다 짧으면 찾지 않는다

# 앞의 logcat 머리: `[YYYY-]MM-DD HH:MM:SS.mmm [uid] pid tid L Tag:`(threadtime) 또는 `… L/Tag( pid):`(time)
_HEAD = re.compile(r"^\s*(?:\d{4}-)?\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*(?:Z|[+-]\d{2}:?\d{2}))?"
                   r"(?:\s+(?:[A-Za-z0-9_.]+\s+)?\d+\s+\d+\s+[VDIWEFA]\s+(?:[^:]|::)+?\s*:(?=\s|$)"
                   r"|\s+[VDIWEFA]/[^(]+?\(\s*\d+\):)?")
# 시각 없이 붙인 줄의 머리: `[uid] pid tid L ` 또는 `L `(로그 레벨 한 글자) 뒤에 `태그 :`가 오는 모양(`D RILJ    : …`, sim1120 S-11).
# 레벨까지만 떼고 `태그 :`는 남긴다 — 비교 글이 `태그: 메시지`라 태그도 본문의 일부다(`Phone-0 : …`는 그대로 찾는다, S-39)
_LEVEL_HEAD = re.compile(r"^\s*(?:(?:[A-Za-z0-9_.]+\s+)?\d+\s+\d+\s+)?[VDIWEFA]\s+(?=[^\s:]+\s*:(?:\s|$))")
# 태그와 `:` 사이 공백(logcat threadtime은 태그를 공백으로 채운다 — `RILJ    : `). 비교 전에 양쪽에서 접는다
_COLON_GAP = re.compile(r"\s+:")
# 대괄호는 시각 모양만 뗀다(`[TX]`·`[IpcCtx_0]`는 IPC 정규식이 쓴다, P2 21): `[  12.345]`·`[14:32:11.001]`
_BRACKET_TS = re.compile(r"\[\s*\d+\.\d+\s*\]|\[\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\]")
_TOKEN = re.compile(r"(?i)\btoken\s*[=:(]\s*(0x[0-9A-Fa-f]{1,8}|\d{1,10})\b")   # 괄호 없이·`Token(0x2FE)`도 읽는다(P2 22, 단계 3)
_STAMP = re.compile(r"^\s*((?:\d{4}-)?\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d{3,9})")    # = logtime.STAMP(연도·시각 부분)
# 날짜 없이 앞에 적은 시각(`22:18:58.695 pcscf=[]`, sim1121) — 떼어 같은 시각 줄 고르기에만 쓴다(`clock`·`same_clock`)
_CLOCK = re.compile(r"^\s*\[?(\d{1,2}:\d{2}:\d{2}(?:\.\d{1,9})?)\]?(?=\s|$)")
CLOCK_ONLY = re.compile(r"\d{1,2}:\d{2}:\d{2}(?:\.\d{1,9})?")
# 사람이 중간을 줄여 적은 표시(`< SETUP_DATA_CALL ... retry=-1`) — 이 앞뒤 조각을 순서대로 찾는다
_ELLIPSIS = re.compile(r"…|\.{3,}")
_BARE_TOKEN = re.compile(r"0[xX][0-9A-Fa-f]{1,8}|\d{1,10}")    # 글 전체가 token 값(16진 또는 10진 숫자만)
# `common.modulefilter._TOKEN_FOLD`의 사본 — run·explore 경로는 modulefilter를 import하지 않는다(test_modulefilter). 바꾸면 둘 다
_TOKEN_FOLD = re.compile(r"<[A-Z][A-Z0-9_]*#\d+>|<HEXDUMP \d+B>|<REDACTED:[A-Z0-9]+>")


def clean(text) -> str:
    """앞의 logcat 머리(시각 없이 붙인 레벨 머리 포함)·대괄호 시각을 떼고 공백을 한 칸으로. ponytail: syslog(oFono) 머리는 떼지
    않는다 — 메시지 부분을 붙이면 찾는다."""
    raw = str(text or "")
    text = _HEAD.sub("", raw, count=1)
    if text == raw:
        raw = text = _CLOCK.sub("", raw, count=1)
    if text == raw:      # 시각 머리를 뗐으면 남은 것은 메시지다 — 메시지 앞 `E radio: …`를 레벨로 떼지 않는다
        text = _LEVEL_HEAD.sub("", text, count=1)
    return " ".join(_BRACKET_TS.sub(" ", text).split())


def stamp(text) -> str | None:
    """붙여 넣은 줄 앞의 logcat 시각(`[YYYY-]MM-DD HH:MM:SS.mmm`) 글. 없으면 None — `clean`이 떼기 전에 부른다."""
    m = _STAMP.match(str(text or ""))
    return m.group(1) if m else None


def clock(text) -> str | None:
    """붙여 넣은 줄 앞의 날짜 없는 시각(`HH:MM:SS(.mmm)`) 글. 날짜가 붙은 logcat 시각이면 None(`stamp`가 읽는다)."""
    raw = str(text or "")
    if _STAMP.match(raw):
        return None
    m = _CLOCK.match(raw)
    return m.group(1) if m else None


def same_clock(clock_text: str, line_clock: str) -> bool:
    """날짜 없는 시각 `clock_text`가 로그 줄에 찍힌 시각 글 `line_clock`(`HH:MM:SS(.fff)`, 시간대를 바꾸지 않은 그대로)과 같은가 —
    적은 자리수까지만 비교한다(`16:50:42`는 그 1초 전체)."""
    def split(t):
        hms, _, frac = t.partition(".")
        return tuple(int(x) for x in hms.split(":")), frac
    (want, frac), (got, got_frac) = split(clock_text), split(line_clock)
    return want == got and got_frac.ljust(len(frac), "0").startswith(frac)


def fold(text) -> str:
    """비교용: 마스킹 토큰을 번호 없이 접고 공백 정리(`태그 :`의 `:` 앞 공백은 뺀다)·대소문자 무시."""
    return _COLON_GAP.sub(":", " ".join(_TOKEN_FOLD.sub("<M>", str(text or "")).split())).casefold()


def query(text, prefix: str = "VIPC_") -> dict:
    """입력 → `{text(정리한 글), name, token(int|None)}`. 이름은 접두어+단어 문자, token은 `token=`·`token:`·`token(`(대소문자 무시)·
    글 전체가 `0x…`이거나 10진 숫자만."""
    body = clean(text)
    m = re.search(r"\b(" + re.escape(prefix) + r"\w+)", body)     # = modulefilter.ipc_re_for(prefix)
    t = _TOKEN.search(body)
    raw = t.group(1) if t else (body if _BARE_TOKEN.fullmatch(body) else None)
    token = None if raw is None else (int(raw, 16) if raw[:2].lower() == "0x" else int(raw))
    return {"text": body, "name": m.group(1) if m else None, "token": token}


def ipc_hits(q: dict, records: list[dict], slot: int | None = None) -> list[int]:
    """token이 있을 때: 이름도 있으면 이름과 token이 같은 레코드, 이름이 없으면 token이 같은 레코드의 위치.
    `slot`(요청 SIM 슬롯)이 있으면 `phone_id`가 그 슬롯이거나 None(슬롯 모름)인 레코드만. 없으면 슬롯을 가리지 않고 모두 —
    두 슬롯에 다 맞아도 고르지 않는다(모호 처리는 뒤 단계)."""
    if q.get("token") is None:
        return []
    return [n for n, r in enumerate(records)
            if r.get("token") == q["token"] and (q.get("name") is None or r.get("name") == q["name"])
            and (slot is None or r.get("phone_id") in (slot, None))]


def needle(q: dict) -> str | None:
    """부분 일치에 쓸 접은 글. 8자 미만이면 None(찾지 않는다)."""
    text = fold(q.get("text"))
    return text if len(text) >= TEXT_MIN else None


def _in_order(parts: list[str], hay: str) -> bool:
    pos = 0
    for part in parts:
        k = hay.find(part, pos)
        if k < 0:
            return False
        pos = k + len(part)
    return True


def _tagless(hay: str) -> str:
    """`태그: 메시지` → `태그 메시지`(사람이 태그 뒤 `:`를 빼고 적은 줄 `DNC-0 onDataStall…`, sim1121)."""
    return hay.replace(": ", " ", 1)


def text_hits(needle_text: str, texts: list[str], masked=None, loose: bool = True) -> list[int] | None:
    """`text_find`의 위치만."""
    return text_find(needle_text, texts, masked, loose)[0]


def text_find(needle_text: str, texts: list[str], masked=None, loose: bool = True) -> tuple[list[int] | None, str]:
    """`needle_text`(접은 글)가 든 줄의 위치. 먼저 가장 긴 마스킹 밖 조각으로 원 줄을 거르고, 걸린 줄만 `masked(i)`(그 줄을
    가린 글, 없으면 원 줄)로 접어 확인한다 — 원문 사본 줄의 값도 입력처럼 가려 비교한다. 그 조각이 `PIECE_MIN`자보다 짧으면
    (값이 거의 다 가려진 글) 엉뚱한 줄에 붙지 않게 찾지 않고 None.

    사람이 대충 적은 줄도 찾는다(sim1121): 태그 뒤 `:`를 뺀 `태그 메시지`, 중간을 `...`·`…`로 줄인 글(앞뒤 조각을 순서대로).
    그래도 없을 때만(`loose`) 낱말이 줄 안에 순서대로 다 있는 줄(낱말은 낱말 경계에서 시작해야 한다 — `setup`이 `onDataSetup`에
    붙지 않게) — 찾기 방식 `words`로 따로 알린다(확정으로 올리지 않는다). 여러 줄이 맞으면 고르기·모호 표시는 호출자(`pick`·
    `group_places`)가 한다. → `(위치 | None, "text" | "words")`."""
    parts = [p.strip() for p in _ELLIPSIS.split(needle_text) if p.strip()]
    piece = max((s.strip() for p in parts for s in p.split("<m>")), key=len, default="")
    if len(piece) < PIECE_MIN:
        return None, "text"
    key = max((s for p in parts for w in p.split() for s in w.split("<m>")), key=len)     # 모든 방식이 꼭 담는 조각(사전 거르기)
    words = [re.compile(r"(?<![0-9a-z])" + re.escape(w)) for p in parts for w in p.split()]
    out, by_words = [], []
    for i, text in enumerate(texts):
        if key not in _COLON_GAP.sub(":", " ".join(text.split())).casefold():
            continue
        hay = fold(masked(i) if masked else text)
        if _in_order(parts, hay) or _in_order(parts, _tagless(hay)):
            out.append(i)
        elif loose and len(words) > 1 and not out and _words_in_order(words, hay):
            by_words.append(i)
    return (out, "text") if out or not by_words else (by_words, "words")


def _words_in_order(words: list[re.Pattern], hay: str) -> bool:
    pos = 0
    for w in words:
        m = w.search(hay, pos)
        if m is None:
            return False
        pos = m.end()
    return True


def pick(times: list[datetime], ref: datetime | None) -> tuple[int, str]:
    """후보 시각 → (고른 위치, 방식 `only`|`nearest`|`last`). 기준 시각이 있으면 가장 가까운 것(같으면 앞), 없으면 마지막."""
    if len(times) == 1:
        return 0, "only"
    if ref is not None:
        return min(range(len(times)), key=lambda k: (abs((times[k] - ref).total_seconds()), k)), "nearest"
    return len(times) - 1, "last"


PAIR_MS = 2000      # IPC REQ→RSP 짝 상한 기본값(= platforms.base.DEFAULT_LINK_MS, 사내는 `platform.ril.vendor.link_ms`)


def group_places(hits: list[dict], link_ms: int = PAIR_MS) -> list[list[dict]]:
    """일치 줄(`{ts, phone, ipc?: {dir, name, token}, ril?: {serial, pid, paired_ts}}`, 시각 순)을 같은 요청끼리 묶는다(H13):
    IPC = 같은 name·token·슬롯의 REQ와 그 뒤 `link_ms` 안 첫 RSP(token이 돌아 다시 쓰여도 먼 RSP와 묶지 않게), RIL = 같은
    pid·슬롯·serial이고 짝 시각(`paired_ts`)이 이어지는 줄. 나머지는 줄 하나가 한 곳."""
    groups: list[list[dict]] = []
    open_ipc: dict = {}
    ril_last: dict = {}
    for h in sorted(hits, key=lambda x: x["ts"]):
        ipc, ril = h.get("ipc"), h.get("ril")
        if ipc:
            key = (ipc.get("name"), ipc.get("token"), h.get("phone"))
            req = open_ipc.pop(key, None) if ipc.get("dir") == "rsp" else None
            if req and (logtime.parse_ts(h["ts"]) - logtime.parse_ts(req[0]["ts"])).total_seconds() * 1000 <= link_ms:
                req.append(h)
                continue
            groups.append([h])
            if ipc.get("dir") == "req":
                open_ipc[key] = groups[-1]
        elif ril:
            key = (ril.get("serial"), ril.get("pid"), h.get("phone"))
            prev = ril_last.get(key)
            if prev and ({prev[-1]["ts"], prev[-1]["ril"].get("paired_ts")} & {h["ts"], ril.get("paired_ts")}) - {None}:
                prev.append(h)
                continue
            groups.append([h])
            ril_last[key] = groups[-1]
        else:
            groups.append([h])
    return groups
