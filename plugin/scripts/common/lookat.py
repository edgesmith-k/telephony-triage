"""기준 줄(`triage.py run --look-at`) 찾기 — 순수 함수, 표준 라이브러리만 (11/16 설계 §2·v2, VERIFY P2 21~23).

사용자가 붙인 로그 줄이나 `<IPC 이름> (token=0x…)`을 로그에서 찾아 그 줄의 로그 시각을 분석 구간의 중심으로 쓴다.
찾는 순서: ① IPC 이름과 token이 같은 레코드(`common.ipcseq`) ② 이름 없이 token만 주면 token이 같은 레코드 ③ 그 밖은 정리한 글을
로그 줄(`태그: 메시지`)에 부분 일치(대소문자 무시, 8자 미만이거나 마스킹 토큰 밖 조각이 4자 미만이면 찾지 않음). 비교 전에 양쪽 마스킹 토큰(`<IP#7>`)을 번호 없이
접는다(`modulefilter._TOKEN_FOLD`와 같은 식) — 입력과 로그를 다른 마스커가 가려 번호가 달라도 맞게. 후보가 여럿이면 기준 시각(Jira 발생
시각)에 가장 가까운 것, 기준 시각이 없으면 마지막 것(시험은 FAIL에서 멈추므로 실패는 보통 로그 끝쪽)을 고르고 고른 방식을 남긴다.
"""

from __future__ import annotations

import re
from datetime import datetime


PRE_SEC, POST_SEC = 30, 300      # 분석 구간 = 기준 줄 시각 −30초 ~ +300초 (설정 키 대신 상수, VERIFY P2 20)
TEXT_MAX = 300                   # --look-at·--look-note 글자 수 상한
TEXT_MIN = 8                     # 부분 일치로 찾는 최소 글자 수(접은 뒤)
AT_MAX = 8                       # 보이는 일치 시각 수(token은 다시 쓰일 수 있어 모든 위치를 보인다)
PIECE_MIN = 4                    # 부분 일치 사전 필터: 마스킹 토큰 밖 조각 중 가장 긴 것이 이보다 짧으면 찾지 않는다

# 앞의 logcat 머리: `[YYYY-]MM-DD HH:MM:SS.mmm [uid] pid tid L Tag:`(threadtime) 또는 `… L/Tag( pid):`(time)
_HEAD = re.compile(r"^\s*(?:\d{4}-)?\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s*(?:Z|[+-]\d{2}:?\d{2}))?"
                   r"(?:\s+(?:[A-Za-z0-9_.]+\s+)?\d+\s+\d+\s+[VDIWEFA]\s+(?:[^:]|::)+?\s*:(?=\s|$)"
                   r"|\s+[VDIWEFA]/[^(]+?\(\s*\d+\):)?")
# 대괄호는 시각 모양만 뗀다(`[TX]`·`[IpcCtx_0]`는 IPC 정규식이 쓴다, P2 21): `[  12.345]`·`[14:32:11.001]`
_BRACKET_TS = re.compile(r"\[\s*\d+\.\d+\s*\]|\[\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\]")
_TOKEN = re.compile(r"(?i)\btoken\s*[=:(]\s*(0x[0-9A-Fa-f]{1,8}|\d{1,10})\b")   # 괄호 없이·`Token(0x2FE)`도 읽는다(P2 22, 단계 3)
_BARE_TOKEN = re.compile(r"0[xX][0-9A-Fa-f]{1,8}|\d{1,10}")    # 글 전체가 token 값(16진 또는 10진 숫자만)
# `common.modulefilter._TOKEN_FOLD`의 사본 — run·explore 경로는 modulefilter를 import하지 않는다(test_modulefilter). 바꾸면 둘 다
_TOKEN_FOLD = re.compile(r"<[A-Z][A-Z0-9_]*#\d+>|<HEXDUMP \d+B>|<REDACTED:[A-Z0-9]+>")


def clean(text) -> str:
    """앞의 logcat 머리·대괄호 시각을 떼고 공백을 한 칸으로. ponytail: syslog(oFono) 머리는 떼지 않는다 — 메시지 부분을 붙이면 찾는다."""
    text = _HEAD.sub("", str(text or ""), count=1)
    return " ".join(_BRACKET_TS.sub(" ", text).split())


def fold(text) -> str:
    """비교용: 마스킹 토큰을 번호 없이 접고 공백 정리·대소문자 무시."""
    return " ".join(_TOKEN_FOLD.sub("<M>", str(text or "")).split()).casefold()


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


def text_hits(needle_text: str, texts: list[str], masked=None) -> list[int] | None:
    """`needle_text`(접은 글)가 든 줄의 위치. 먼저 가장 긴 마스킹 밖 조각으로 원 줄을 거르고, 걸린 줄만 `masked(i)`(그 줄을
    가린 글, 없으면 원 줄)로 접어 확인한다 — 원문 사본 줄의 값도 입력처럼 가려 비교한다. 그 조각이 `PIECE_MIN`자보다 짧으면
    (값이 거의 다 가려진 글) 엉뚱한 줄에 붙지 않게 찾지 않고 None."""
    piece = max(needle_text.split("<m>"), key=len).strip()
    if len(piece) < PIECE_MIN:
        return None
    out = []
    for i, text in enumerate(texts):
        if piece in " ".join(text.split()).casefold() and needle_text in fold(masked(i) if masked else text):
            out.append(i)
    return out


def pick(times: list[datetime], ref: datetime | None) -> tuple[int, str]:
    """후보 시각 → (고른 위치, 방식 `only`|`nearest`|`last`). 기준 시각이 있으면 가장 가까운 것(같으면 앞), 없으면 마지막."""
    if len(times) == 1:
        return 0, "only"
    if ref is not None:
        return min(range(len(times)), key=lambda k: (abs((times[k] - ref).total_seconds()), k)), "nearest"
    return len(times) - 1, "last"
