"""벤더 IPC 메시지 줄 → 레코드 (순수 함수, 표준 라이브러리만 — 11/16 설계 §1).

레코드: `{i, ts, dir: req|rsp|ind|None, name, token: int|None, result: str|None, line_ref, phone_id: int|None}`. 읽는 줄은 기존 벤더 IPC
배선과 같은 태그(백엔드 `is_vendor_ipc(tag)`: Android `VENDOR_IPC_TAGS`·tags.yaml `ipc: vendor`, oFono `vendor_ipc: true`
ident)의 줄이고, 줄을 고르고 마스킹하는 일은 `parse_logcat.py ipc`가 한다(이 모듈은 정규식·값 해석만).

정규식은 site-defaults `platform[.others.<p>].vendor_ipc.trace`(선택, 목록)에서 오고, 없으면 아래 placeholder 둘이다. 이름 그룹:
`name`(필수), `token`·`dir`·`kind`·`result`(선택). 정규식 안의 `{prefix}`·`{error_prefix}`는 `vendor_ipc.request_prefix`·
`error_prefix`를 `re.escape`해 채운다(사내 접두어는 site-defaults에만, TODO(SITE:S9)). 실제 벤더 형식은 레포에 쓰지 않는다.

token: `0x` 16진·10진 모두 int. 숫자는 끝까지 잡고(자르지 않는다) 16진 8자리·10진 10자리를 넘으면 None, 마스킹이 바꾼 값
(`<CRED#n>`)도 None이다. 짧은 token(10진 10자리·16진 8자리 이하)은 마스커가 두므로
(`masking._token_secret`) 값이 남는다. 마스커는 `token=`·`token:` 표기만 보고 괄호 표기(`Token(…)`)는 가리지 않는다. `platforms.android.ril.link_vendor`의 10진 전용 동작과는 무관하다(그대로 둔다).
"""

from __future__ import annotations

import re

from . import vendor_ipc

RECORD_MAX = 20000
GROUPS = ("name", "token", "dir", "kind", "result")   # 허용 이름 그룹(`name` 필수)
TRACE_MAX = 8                                         # 정규식 수 상한
TRACE_LEN = 400                                       # 정규식 하나의 글자 수 상한
# placeholder 기본 정규식 둘(합성 `VIPC_` 꼴): `[TX] <이름>, REQ, … token=… <낱말>(<결과>)`와 `<이름> (token=0x0de)`.
# token 구분은 `=`·`:`·`(`이고 `token`은 대소문자를 가리지 않는다(이름 `name`은 가린다).
# 결과는 괄호 안이 오류 접두어인 `<낱말>(…)`이다. 한 줄에 여럿이면 `Error(…)`가 먼저(`vendor_ipc.detect`와 같은 값), 없으면 첫 것.
# 단 token 뒤의 결과만 읽는다 — token 앞의 `Error(`는 기록 결과에 안 잡힌다(성공 여부는 detect 기준).
# 뒤쪽 `Error(` 확인(부정 전방탐색)은 결과 후보(`<낱말>(<오류 접두어>`) 앞에서만 돈다 — 낱말마다 돌면 줄 길이의 제곱 시간
DEFAULT_TRACE = (
    r"\[(?P<dir>TX|RX)\]\s*(?P<name>{prefix}[A-Z0-9_]+)\s*,\s*(?P<kind>REQ|RSP|IND)\b"
    r"(?:.*?\b(?i:token)\s*[=:(]\s*(?P<token>(?:0x[0-9A-Fa-f]+|\d+)\b))?"
    r"(?:.*?\b(?:Error|[A-Za-z]+(?=\(\s*{error_prefix})(?!.*\bError\(\s*{error_prefix}[A-Z0-9_]+\s*\)))"
    r"\(\s*(?P<result>{error_prefix}[A-Z0-9_]+)\s*\))?",
    # 마스커는 `token=`·`token:` 뒤 긴 값(10진 11자리 이상·16진 9자리 이상, `masking._SHORT_NUM`을 넘는 값)을 `<CRED#n>`으로
    # 바꾸며 닫는 `)`까지 먹는다 — `)`는 선택, 그 값은 token None. 괄호 표기(`Token(…)`)는 마스커가 가리지 않는다
    r"\b(?P<name>{prefix}[A-Z0-9_]+)\s*\(\s*(?i:token)\s*[=:(]\s*(?P<token>(?:0x[0-9A-Fa-f]+|\d+)\b|<[A-Z]+#\d+>)\s*\)?",
)
_DIR = {"REQ": "req", "RSP": "rsp", "IND": "ind", "TX": "req", "RX": "rsp"}
_TOKEN_VALUE = re.compile(r"0[xX][0-9A-Fa-f]{1,8}|\d{1,10}")


def fill(pattern: str, spec: vendor_ipc.Spec = vendor_ipc.DEFAULT) -> str:
    """`{prefix}`·`{error_prefix}` 자리표시를 그 spec의 접두어(`re.escape`)로 채운다. 정규식 수량자 `{1,8}`은 건드리지 않는다."""
    return pattern.replace("{prefix}", re.escape(spec.request_prefix)).replace("{error_prefix}", re.escape(spec.error_prefix))


def check(pattern) -> str | None:
    """사이트 정규식 하나의 문제(없으면 None): 글·길이·컴파일·`name` 그룹 필수·허용 그룹만."""
    if not isinstance(pattern, str) or not pattern or len(pattern) > TRACE_LEN:
        return f"비어 있지 않은 {TRACE_LEN}자 이하 정규식 문자열이어야 합니다."
    try:
        rx = re.compile(fill(pattern))
    except re.error as exc:
        return f"정규식 오류: {exc}"
    names = set(rx.groupindex)
    if "name" not in names:
        return "이름 그룹 (?P<name>…)이 있어야 합니다."
    if names - set(GROUPS):
        return f"허용 이름 그룹은 {', '.join(GROUPS)}입니다(그 밖: {', '.join(sorted(names - set(GROUPS)))})."
    return None


def check_slot(pattern) -> str | None:
    """IPC 줄 슬롯 정규식(`vendor_ipc.slot`) 하나의 문제(없으면 None): 글·길이·자리표시 없음·컴파일·그룹 1(= 슬롯 번호) 필수.
    slot에는 `{prefix}`·`{error_prefix}`를 채우지 않으므로 그대로 두면 조용히 0건이 된다 — 거부한다."""
    if not isinstance(pattern, str) or not pattern or len(pattern) > TRACE_LEN:
        return f"비어 있지 않은 {TRACE_LEN}자 이하 정규식 문자열이어야 합니다."
    if "{prefix}" in pattern or "{error_prefix}" in pattern:
        return "slot에는 {prefix}·{error_prefix} 자리표시를 쓸 수 없습니다(채우지 않습니다). 접두어를 글자 그대로 적으세요."
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return f"정규식 오류: {exc}"
    return None if rx.groups >= 1 else "그룹 1(슬롯 번호)이 있어야 합니다."


def slot_value(m: re.Match) -> int | None:
    """슬롯 정규식 맞음 → 그룹 1의 정수(10진 숫자가 아니면 None — 위첨자 같은 `isdigit` 글자에서 멈추지 않게)."""
    text = (m.group(1) or "").strip()
    return int(text) if text.isdecimal() else None


def patterns(spec: vendor_ipc.Spec = vendor_ipc.DEFAULT) -> list[str]:
    """쓸 정규식(접두어를 채운 글): site-defaults `trace`가 있으면 그것, 없으면 placeholder 기본 둘."""
    return [fill(p, spec) for p in (spec.trace or DEFAULT_TRACE)]


def token_value(text) -> int | None:
    """`0x0de`·`222` → int. 마스킹 토큰·그 밖은 None."""
    text = str(text or "").strip()
    if not _TOKEN_VALUE.fullmatch(text):
        return None
    return int(text, 16) if text[:2].lower() == "0x" else int(text)


def record(m: re.Match, i: int, ts, line_ref=None, phone_id=None) -> dict:
    """정규식 맞음 하나 → 레코드. `dir`: `kind`(REQ/RSP/IND)가 먼저, 없으면 `dir`(TX→req·RX→rsp), 둘 다 없으면 None.
    `phone_id`(SIM 슬롯)는 부른 쪽이 정한다(`vendor_ipc.slot`이 맞으면 그 값, 아니면 줄 레코드의 `phone_id`)."""
    groups = m.groupdict()
    kind = (groups.get("kind") or "").upper()
    way = (groups.get("dir") or "").upper()
    return {"i": i, "ts": ts, "dir": _DIR.get(kind) or _DIR.get(way), "name": groups["name"],
            "token": token_value(groups.get("token")), "result": groups.get("result") or None, "line_ref": line_ref,
            "phone_id": phone_id}
