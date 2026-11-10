"""마스킹 함수 (contracts.md §3.2 "마스킹 함수", 08-safety.md §8).

`mask_pii.py`와 `parse_logcat.py`(`parse --mask`, `cut`)가 공유한다.

- **번호 토큰**: 한 마스커(파일 하나 또는 분석 1회) 안에서 같은 원래 값은 같은
  `<종류#n>`, 다른 값은 다른 번호. 번호는 처음 나온 순서대로 매긴다. 원래 값과 번호의
  대응표는 메모리에만 있다. IMEI는 표기 변형(공백·대시)을 지운 값으로 같은지 본다.
- **이미 토큰이 있는 입력**: `observe()`로 입력 전체의 종류별 최대 번호를 먼저 구하고,
  새 값에는 그 다음 번호부터 준다(`<CELL#1>`이 있으면 새 셀은 `<CELL#2>`).
- **멱등**: 기존 토큰은 건드리지 않는다. 마스킹된 입력에 다시 적용해도 같다.
- **문맥 우선**: 키 이름 문맥(`imsi=`, `mCi=` 등)을 먼저 보고, 숫자 길이만으로 판정하는
  규칙(문맥 없는 15자리)은 Luhn·MCC 확인을 거친다. 빌드 번호·타임스탬프 오탐을 피하려고
  숫자 규칙은 단어 경계(`_`, `.` 포함) 안에서만 본다.
- **ASCII 경계**: 규칙의 낱말·경계·숫자 클래스와 `(?i)`는 ASCII다(`Rule`이 `re.ASCII`로 컴파일). 값 앞뒤에 붙은 한글
  (`010-1234-5678로`, `IMSI <15자리>에서`)은 경계다. 키·값 사이 공백과 값 끝은 `(?u:…)`로 유니코드 공백도 받는다.
- **값 앞 제외(`Rule.before`)**: 값 바로 앞 24자가 이 패턴에 맞으면 그 값은 건너뛴다
  (`version 10.0.1.2`를 IPv4로 보지 않기). `context`(줄 전체 양성 조건)와 반대 방향의 음성 조건이다.
- **게이트(`Rule.gate`)**: 키 이름 문맥 규칙은 소문자 줄에 그 키 부분문자열이 하나라도 있을 때만
  돈다. 결과는 같고 규칙당 고정비(줄마다 `finditer`)만 줄인다(08-safety.md §8 성능).
- **예외**: `issue-db.config.yaml`의 `mask.allow_patterns`에 전체가 맞는 값은 그대로 둔다.
  Android 자체 마스킹(`***`, `xxxxxx`)도 그대로 둔다.

- **로그 줄 전용 규칙(`Rule.log_only`, M1~M11)**: 합성 fixture로 고정한 로그 줄 규칙(B2 §3.2) 중 모양만 보는 것(hex 덤프·base64·빌드/제품 코드·15~20자리
  숫자·syslog 호스트 칸)은 `log_lines=True`로 만든 마스커(로그 마스킹: parse·cut·`mask_pii` 치환/이벤트·보기·점검
  도구)에서만 돈다. `db_lint`·`mask_pii --check`·`issue_post`는 기본값(`False`)이라 그 종류의 결과가 전과 같다.
  실제 식별자 규칙(M2a·M3·M4·M5·M7·M8 payload/salt·M9·뒤집힌 ICCID)은 어디서나 돈다.
- **토큰 모양(`Rule.fmt`)**: 기본 `<종류#n>`. M1 덤프 줄은 `<HEXDUMP nB>`(번호 없음), M8 payload는 `<APDU#n>[nB]`,
  M11 호스트는 `host<n>`(journal 형식 정규식의 호스트 칸에 그대로 맞아 마스킹한 줄도 해석된다).
- **남은 식별자(`residual`)·가리기(`redact`)**: 로그 마스커의 `find()` 그대로(다른 탐지기 없음), 줄 단위.
  그래서 `residual(mask(x)) == {}`가 구조상 성립한다.
- **갈린 덤프 조각(`SPLIT_KINDS`)**: oFono 덤프 함수(site-defaults `dump_func`, `<이름>() ` 뒤가 조각)가 IMSI·ICCID 값을 두 줄에 가르면(`common.dumpjoin`으로 묶음)
  키 있는 IMSI·ICCID 규칙만 이은 글에 돌려 조각 경계를 넘는 맞음을 줄별 강제 구간(`forced`)으로 되돌린다. 토큰은 전체
  값으로 한 번 만들고(개수 1회) 조각마다 같은 토큰을 쓰며, 조각 글자도 번호 표에 그 토큰으로 넣는다(`mask_value`).
  `mask_lines`·`mask_records`가 이 경로이고 `residual`·`redact`도 같은 맞음을 센다/가린다. 키 없는 규칙(15자리·`89…`·
  뒤집힌 ICCID)은 이은 글에 쓰지 않는다(조각 경계를 넘는 숫자열 오탐 방지).

탐지 규칙의 키 이름·형식은 일반적인 Android 로그 기준이고, 사내 로그에서 오탐·누락을
확인한다 — TODO(SITE:S13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Callable, Iterable

from . import dumpjoin

Masker = Callable[[str], str]

TOKEN_RE = re.compile(r"<(?P<kind>[A-Z][A-Z0-9]*)#(?P<n>\d+)>")
KINDS = ("IMSI", "IMEI", "ICCID", "SUPI", "SUCI", "TMSI", "GUTI", "MSISDN", "IMPU", "IMPI",
         "CELL", "IP", "MAC", "EMAIL", "CRED", "EID", "GEO", "SERIAL")
PIECE_MIN_TABLE = 6   # 갈린 조각 글자를 값 표에 넣는 최소 길이(짧으면 같은 글자의 다른 필드까지 토큰이 된다)

_SIP_AUTH_CONTEXT = re.compile(
    r"(?i)\b(?:authorization|www-authenticate|proxy-authenticate|proxy-authorization|digest)\b"
)


@dataclass(frozen=True)
class Rule:
    kind: str
    regex: re.Pattern
    check: Callable[[str], bool] | None = None      # 값 검사 (Luhn 등)
    context: re.Pattern | None = None               # 이 문맥이 있는 텍스트에서만
    before: re.Pattern | None = None                # 값 앞 24자가 이 패턴에 맞으면 건너뛴다
    gate: tuple[str, ...] = ()                      # 소문자 줄에 이 중 하나가 있을 때만 (비면 항상)
    log_only: bool = False                          # 로그 마스커(`log_lines=True`)에서만 (M1~M11 모양 규칙)
    fmt: str | None = None                          # 토큰 모양. `{n}` 번호, `{b}` 덤프 바이트 수, `{h}` hex 길이/2
    per_line: bool = False                          # 여러 줄 글에서 문맥을 값이 있는 그 줄에서만 본다

    def __post_init__(self):
        # 낱말·경계·숫자(`\w`·`\b`·`\d`)는 ASCII다: 값 옆의 한글 조사(`010-1234-5678로`)·가나도 경계가 된다.
        # 키·값 사이 공백과 값 끝은 규칙이 `(?u:\s)`로 따로 유니코드 공백(NBSP·U+3000)을 받는다
        for name in ("regex", "context", "before"):
            pat = getattr(self, name)
            if pat is not None and not pat.flags & re.ASCII:
                object.__setattr__(self, name, re.compile(pat.pattern, (pat.flags & ~re.UNICODE) | re.ASCII))

    def applies(self, text: str) -> bool:
        return self.context is None or bool(self.context.search(text))


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _valid_mcc(digits: str) -> bool:
    return 200 <= int(digits[:3]) <= 799


def _secretish(value: str) -> bool:
    """`key=` 문맥의 값이 비밀값처럼 보이는가 (설정 키 이름 같은 값은 제외)."""
    return len(value) >= 16 and any(c.isdigit() for c in value)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


_STATE_WORDS = frozenset(("null", "none", "true", "false", "unknown", "n/a", "yes", "no", "on", "off",
                          "enabled", "disabled", "ready", "ok", "pass", "passed", "fail", "failed",
                          "success", "skipped", "valid", "invalid"))


def _pass_like(value: str) -> bool:
    """`pass=` 값이 비밀값처럼 보이는가. 상태 낱말·대문자 열거형(`PASSED`)·짧은 횟수·토큰 조각·정규식 묶음은 제외."""
    if value.lower() in _STATE_WORDS or value.startswith("<") or re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
        return False
    if value.startswith("(?") or (value.startswith("(") and "|" in value):  # 정규식 선택 묶음(db_lint가 패턴을 검사할 때)
        return False
    return not value.isdigit() or len(value) >= 4


def _norm_key(kind: str, value: str) -> str:
    """번호 대응표의 키. IMEI는 표기 변형(공백·대시·대소문자)이 같은 값이면 같은 번호가 되도록 정규화한다."""
    return value.replace(" ", "").replace("-", "").upper() if kind == "IMEI" else value


def _alnum_mixed(value: str) -> bool:
    return any(c.isdigit() for c in value) and any(c.isalpha() for c in value)


# IPv4 값 바로 앞이 버전 문맥이면 IP가 아니다 (`RIL version 10.1.2.3`, `app version=10.4.5.6`)
_VERSION_BEFORE = re.compile(r"(?i)\b(?:ver(?:sion)?|build|release|rev|fw|sw|baseband|kernel|v)\s*[=:]?\s*$")

# 키와 값 사이: `key=v`, `key: v`, JSON `"key":"v"` (공백은 유니코드 — Jira 글의 NBSP)
_SEP = r'"?(?u:\s)*[=:](?u:\s)*"?'

_NUM_END = r"(?![\w*]|\.\w)"  # 숫자 값 뒤: 단어 문자·`*`(Android 부분 마스킹)·`.<글자>`(버전·IP의 일부)가 이어지면 안 된다. 문장 끝 `.`은 된다

# IPv6 조각. `_V6_FULL|_V6_COMP`는 문맥 없는 IPv6 규칙(형식) 그대로, `_V6_PART`는 `::` 없이 끝이 `:`일 수 있는 잘린 표기
_HEX4 = r"[0-9A-Fa-f]{1,4}"
_V6_FULL = r"(?:" + _HEX4 + r":){7}" + _HEX4
_V6_COMP = r"(?:" + _HEX4 + r"(?::" + _HEX4 + r"){0,6})?::(?:" + _HEX4 + r"(?::" + _HEX4 + r"){0,6})?"
_V6_PART = r"(?:" + _HEX4 + r":){3,7}(?:" + _HEX4 + r")?"
_MAC_SHAPE = re.compile(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")
_SHORT_NUM = re.compile(r"\d{1,10}|0[xX][0-9A-Fa-f]{1,8}")


def _v6_like(value: str, min_groups: int) -> bool:
    """`::` 없는 콜론 묶음이 IPv6(조각)처럼 보이는가. `::`가 있으면 `::` 하나만 아니면 된다. 없으면 8묶음이거나,
    묶음 `min_groups`개 이상이고 3~4자리 묶음이 둘 이상이며 MAC 모양(2자리 6묶음)이 아니다 — 시각(`12:34:56`)·
    날짜(`2026:11:02:07:21:33`)·`1:2:3:4:5:6:7`은 빠진다."""
    if "::" in value:
        return value != "::"
    groups = [g for g in value.split(":") if g]
    if len(groups) == 8:
        return True
    return (len(groups) >= min_groups and sum(len(g) >= 3 for g in groups) >= 2
            and not _MAC_SHAPE.fullmatch(value.rstrip(":")))


def _token_secret(value: str) -> bool:
    """`token=` 값이 비밀값인가. 짧은 숫자(10진 10자리 이하, `0x`+16진 8자리 이하 — RIL 요청 token 등)는 아니다."""
    return not _SHORT_NUM.fullmatch(value.rstrip(")]}>"))

# --- M1~M11: 합성 fixture로 고정한 로그 줄 규칙 (B2 §3.2) -----------------------------------------------
# 줄 단위로 본다(`^`는 줄 처음).

def _not_null(value: str) -> bool:
    """M3 위치 인자: 빈 값·`null`은 그대로 둔다(토큰은 이미 차지한 구간이라 여기 오지 않는다)."""
    return bool(value.strip()) and value.strip().lower() not in ("null", "(null)")


def _b64_ish(value: str) -> bool:
    """M2a: 문맥 뒤 값이 낱말(글자뿐)이 아니다."""
    return not value.isalpha()


# M2b 경로 모양 낱말: 소문자 낱말 또는 CamelCase (`com/example/telephony/DataNetwork`)
_PATH_PART = re.compile(r"(?:[a-z][a-z0-9_]*|[A-Z]?[a-z0-9_]+(?:[A-Z][a-z0-9_]+)*)")


def _b64_shape(value: str) -> bool:
    """M2b (`mask3.py:97-101`): 대·소문자·숫자가 다 있고 hex만이 아니며 (`+`/`/`나 `=` 끝 또는 40자 이상), `Lambda` 없음.
    더한 것: `+`·`=` 끝이 없고 `/`가 있으며 `/` 조각이 모두 경로 낱말이면 경로라 제외한다."""
    if not (re.search(r"[A-Z]", value) and re.search(r"[a-z]", value) and re.search(r"[0-9]", value)):
        return False
    if re.fullmatch(r"[0-9A-Fa-f]+", value) or "Lambda" in value:
        return False
    if not (re.search(r"[+/]", value) or value.endswith("=") or len(value) >= 40):
        return False
    if "+" not in value and not value.endswith("=") and "/" in value:
        if all(_PATH_PART.fullmatch(p) for p in value.split("/") if p):
            return False
    return True


_HOST_KEEP = re.compile(r"\(none\)|localhost|dut|host\d+")


def _host_value(value: str) -> bool:
    """M11: 그대로 두는 호스트 칸 값(`(none)`·`localhost`·`dut`·이미 바꾼 `host<n>`)이 아니다."""
    return not _HOST_KEEP.fullmatch(value)


def _v6_after_key(value: str) -> bool:
    return value != "::" and len([g for g in value.split(":") if g]) >= 2


_HEXBYTE = re.compile(r"[0-9A-Fa-f]{2}")


def _dump_bytes(value: str) -> int:
    """`<HEXDUMP nB>`의 n: 앞에서부터 이어진 2자리 hex 낱말 수(ASCII 칸 앞까지)."""
    n = 0
    for part in value.split():
        if not _HEXBYTE.fullmatch(part):
            break
        n += 1
    return n


_DUMP_FMT = " <HEXDUMP {b}B>"
# M1 바이트 뒤 짧은 꼬리: 잘림 표시(`...`·`…`), 길이(`(len 10)`·`(length=10)`), 태그(`[SUB0]`)
_DUMP_TAIL = r"(?:\s+(?:\.{2,}|\u2026|\((?:len|length|size)\s*[:=]?\s*\d+\)|\[[A-Za-z0-9_]{1,16}\]))"
_PAYLOAD_FMT = "<{kind}#{n}>[{h}B]"
_M11_STAMPS = (
    r"\w{3} [ \d]\d \d\d:\d\d:\d\d(?:\.\d+)?",                                            # mask2.py:63 (RFC3164·BusyBox)
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?",          # journal.py ISO
)

# 맨 앞: M11 호스트 칸(줄 처음 고정이라 다른 규칙이 구간을 나누기 전에) → M1 덤프 줄(한 줄이 토큰 하나)
_M_FIRST: tuple[Rule, ...] = (
    Rule("HOST", re.compile(r"^(?:" + "|".join(_M11_STAMPS) + r") (?P<v>\S+) "), check=_host_value,
         log_only=True, fmt="host{n}"),
    # M1 gril `Device|IMSD n:` 줄(hex + ASCII 칸, mask3.py:26)
    Rule("HEXDUMP", re.compile(
        r"^.*?\b(?:Device|IMSD) \d+:(?:\s+[<>])?(?P<v>\s+(?:[0-9a-fA-F]{2}(?:\s+|$)){1,16}.*)$"),
         gate=("device", "imsd"), log_only=True, fmt=_DUMP_FMT),
    # M1 `:` 뒤가 hex 바이트 4개 이상인 줄(ASCII 칸 허용, mask3.py:27 + mask2.py:84). 상태 없음(B2-11)
    # 더한 것: 바이트 뒤 짧은 꼬리(` ...`·`…`·`(len 10)`·`[SUB0]`)도 덤프 줄이다 — "모든 덤프 줄"(B2 §3.2 M1)
    Rule("HEXDUMP", re.compile(r"^.*?:(?P<v>(?:\s+[0-9a-fA-F]{2}){4,}(?:\s{2,}.*|" + _DUMP_TAIL + r"*\s*))$"),
         context=re.compile(r"(?:\s[0-9a-fA-F]{2}){4}"), log_only=True, fmt=_DUMP_FMT),
    # M1 더한 것: `:` 바로 뒤가 아닌 덤프(`[SLOT_1][V] 0123 1 <바이트>`·`sendRequest] <바이트>`) — 공백으로 나뉜
    # hex 바이트 8개 이상 연속은 앞뒤 문맥과 상관없이 그 바이트 부분만 `<HEXDUMP nB>`로 바꾼다
    Rule("HEXDUMP", re.compile(r"(?<![\w:.<>#-])(?P<v>(?:[0-9a-fA-F]{2}[ \t]+){7,}[0-9a-fA-F]{2})(?![\w:.-])"),
         context=re.compile(r"(?:[0-9a-fA-F]{2}[ \t]+){7}[0-9a-fA-F]{2}"), log_only=True, fmt="<HEXDUMP {b}B>"),
    # M3 위치 인자 SETUP_DATA_CALL (tech,profile,apn,user,password,…) — 4·5번째 (mask3.py:30)
    Rule("CRED", re.compile(r"SETUP_DATA_CALL \([^,()]*,[^,()]*,[^,()]*,(?P<v>[^,()]*),(?P<v2>[^,()]*)(?=[,)])"),
         check=_not_null, gate=("setup_data_call",)),
    # M4 GVariant·Go map·ofono dict의 APN 비밀번호 (mask2.py:72). 사용자 이름은 이메일 규칙 뒤(_M_LATE)
    Rule("CRED", re.compile(r"""(?i)(?:password'?:?\s*<'|password:"|password",\s*variant\(")(?P<v>[^'"<>]+)(?=['"])"""),
         gate=("password",)),
)

# 기존 규칙 뒤: 나머지 M 규칙 (측정 마스커에서 1차 저장소 마스커 뒤에 돈 순서 그대로)
_M_LATE: tuple[Rule, ...] = (
    # M5 주소·DNS·게이트웨이·P-CSCF 키 아래 숫자 배열 (mask3.py:35)
    Rule("IP", re.compile(r'"[a-z0-9_]*(?:addr|address|dns|gateway|pcscf)[a-z0-9_]*"\s*:\s*\[(?P<v>[-0-9, ]{3,})\]'),
         gate=("addr", "dns", "gateway", "pcscf")),
    # M6 빌드·제품 코드 (mask3.py:31-34, mask2.py:94-100)
    Rule("BUILD", re.compile(r"Build Info\s*:\s*(?!<)(?P<v>\S+)"), gate=("build info",), log_only=True),
    Rule("BUILD", re.compile(r"commit ID:\s*(?P<v>[0-9a-fA-F]{6,})"), gate=("commit id",), log_only=True),
    Rule("PRODUCT", re.compile(r"(?<![\w])(?P<v>[A-Z]\d{4}[A-Z0-9]{2,})(?![\w])"),
         context=re.compile(r" [VDIWEF] (?:synaptics_ts|sec_input|kernel)\b"), log_only=True),
    Rule("PRODUCT", re.compile(r'(?i)"(?:Revision|Model|Manufacturer|SoftwareVersion)",\s*variant\("(?P<v>[^"]+)"'),
         gate=("variant",), log_only=True),
    # `ro.product.*`·`ro.build.*` 값. 키와 값 사이 구분(`]: [`·`=`·`:`·공백)을 요구한다 — 원본은 값이 없으면 키 끝 글자를 값으로 잡았다
    Rule("PRODUCT", re.compile(r"(?i)\bro\.(?:product|build)\.[\w.]+?(?:\]?:\s*\[?|\]\s*\[|\s*=\s*|\s+)(?P<v>[^\[\]\s=]+)"),
         gate=("ro.product.", "ro.build."), log_only=True),
    Rule("PRODUCT", re.compile(r"(?i)fingerprint\s*[=:]\s*(?P<v>\S+)"), gate=("fingerprint",), log_only=True),
    Rule("PRODUCT", re.compile(r'(?:^|(?<=[\s:]))v?a?r?i?ant\("(?P<v>[A-Z]{2,}\d{3,}[A-Z0-9]*-\d+_[A-Z0-9]+)"'),
         gate=("ant(",), log_only=True),
    Rule("PRODUCT", re.compile(r"\[CP_UART\] (?P<v>[A-Z]+\d{3,}[A-Z0-9]*) EVT"), gate=("cp_uart",), log_only=True),
    # M7 SMSC 번호·NAI 속 IMSI (mask2.py:68,70)
    Rule("MSISDN", re.compile(r'(?i)(?:smsc\s*[=:,]\s*|ServiceCenterAddress"?,?\s*variant\("|rAddress:"|sms\.sim\d\.smsc,)'
                              r"(?P<v>\+?\d{6,15})"), gate=("smsc", "servicecenteraddress", "raddress")),
    Rule("IMSI", re.compile(r"(?i)(?<![\w])0?(?P<v>\d{15})(?=(?:%40|@)(?:nai|wlan|ims|epc)\.)"),
         gate=("nai.", "wlan.", "ims.", "epc.")),
    # M4 APN 사용자 이름 (mask2.py:73) — 이메일 규칙 뒤라 `user@realm`은 통째로 EMAIL로 남는다(측정 순서)
    Rule("CRED", re.compile(r"""(?i)(?:username'?:?\s*<'|username:"|username",\s*variant\(")(?P<v>[^'"<>@]+)(?=['"@])"""),
         gate=("username",)),
    # M8 SIM_IO·APDU payload (mask2.py:76-80), salt·eng 사용자·git 해시 (mask2.py:103-105)
    Rule("APDU", re.compile(r"Payload: (?P<v>[0-9A-Fa-f]{8,})"), gate=("payload",), fmt=_PAYLOAD_FMT),
    Rule("APDU", re.compile(r"Response:\[\(\d+\)(?P<v>[0-9A-Fa-f]{8,})"), gate=("response",), fmt=_PAYLOAD_FMT),
    Rule("APDU", re.compile(r"(?:Received|Sent) : (?P<v>[0-9A-Fa-f]{8,})"), gate=("received", "sent"), fmt=_PAYLOAD_FMT),
    Rule("APDU", re.compile(r"pRespons\w*\s*[:=]\s*(?P<v>[0-9A-Fa-f]{8,})"), gate=("prespons",), fmt=_PAYLOAD_FMT),
    Rule("HEXBLOB", re.compile(r"(?:apdu|APDU|data|Data|cmd|resp|rsp)\s*[:=]\s*\[?(?P<v>[0-9A-Fa-f]{24,})"),
         gate=("apdu", "data", "cmd", "resp", "rsp"), fmt=_PAYLOAD_FMT),
    Rule("SALT", re.compile(r"(?i)\bsalt\s*[=:]\s*(?P<v>[0-9A-Fa-f]{16,})"), gate=("salt",)),
    Rule("BUILD", re.compile(r"\beng\.(?P<v>[a-z][\w-]*)"), gate=("eng.",), log_only=True),
    Rule("HASH", re.compile(r"(?i)(?:git hash:\s*|revision number\s*=\s*)(?P<v>[0-9a-f]{7,40})"),
         gate=("git hash", "revision number"), log_only=True),
    # M9 `<낱말>:`·`<낱말>=` 바로 뒤 IPv6 (mask2.py:108, `dnses:<v6>`)
    Rule("IP", re.compile(r"(?<=[A-Za-z_\]][:=])(?P<v>" + _V6_FULL + "|" + _V6_COMP + r")(?![0-9A-Fa-f:])"),
         check=_v6_after_key),
    # M10 nibble 뒤집힌 ICCID (mask2.py:111). 더한 것: 19자리 ICCID는 EF_ICCID에 채움 nibble `F`가 마지막 숫자
    # 앞에 온다(`…54F6`) — 측정 마스커는 이 모양을 놓쳤다
    Rule("ICCID", re.compile(r"(?<![0-9A-Fa-f])(?P<v>98[0-9]{16,18}(?:[Ff][0-9]|[0-9Ff])?)(?![0-9A-Fa-f])")),
    # M2a 인증 응답 문맥의 base64 (LM §5.3 M2) — 키 문맥 자격증명(`AUTN=<hex>` → CRED)·M8 payload(`Payload: <hex>` → APDU) 뒤, M2b 앞
    Rule("B64", re.compile(r"(?i)(?:\bresp:|\bresponse\s*:|\bpayload:|\bchallenge|\brand|\bautn)\s*[=:]?\s*\"?"
                           r"(?P<v>[A-Za-z0-9+/]{16,}={0,2})(?![A-Za-z0-9+/=])"),
         check=_b64_ish, gate=("resp", "payload", "challenge", "rand", "autn")),
    Rule("B64", re.compile(r"(?<![A-Za-z0-9+/=<#])(?P<v>[A-Za-z0-9+/]{16,}={0,2})(?![A-Za-z0-9+/=])"),
         check=_b64_ish, context=re.compile(r"SIM_AUTHENTICATION"), gate=("sim_authentication",), per_line=True),
    # M2b 모양만 보는 base64 (mask3.py:36, 97-101) + 경로 제외
    Rule("B64", re.compile(r"(?<![A-Za-z0-9+/=<#])(?P<v>[A-Za-z0-9+/]{24,}={0,2})(?![A-Za-z0-9+/=])"),
         check=_b64_shape, log_only=True),
    # 모뎀 모델 코드 `m<4자리>`: 문맥은 줄 어디든 ` <소문자 낱말>:`(커널/벤더 태그 꼴)이 있으면 — 벤더 태그 이름을 두지 않는다(과마스킹 허용).
    # 문맥이 넓어 값 규칙(ro.*·fingerprint·variant·username 등) 뒤에 둔다 — 앞에 두면 값 한가운데를 먼저 차지해 값이 쪼개진다
    Rule("PRODUCT", re.compile(r"(?<![\w])(?P<v>m\d{4})(?=[^\w]|$)"), context=re.compile(r" [a-z][a-z0-9_]*\s*:"),
         log_only=True),
    # M2b 다시: 제품 코드가 끊어 놓은 나머지(`…/m1234/<base64>`)도 모양만 보는 base64로 — 위 M2b는 끊기 전 글을 봤다
    Rule("B64", re.compile(r"(?<![A-Za-z0-9+/=<#])(?P<v>[A-Za-z0-9+/]{24,}={0,2})(?![A-Za-z0-9+/=])"),
         check=_b64_shape, log_only=True),
    # M10 남은 15~20자리 숫자 — 맨 끝(IMEI·IMSI·ICCID 검증 규칙이 먼저 제 종류로 가린다, mask2.py:110).
    # 더한 것: `0x` 16진 값(`0x0000000801234567` 주소)과 16진 낱말의 일부는 숫자 값이 아니라 제외한다(B2 §3.4 음성 사례)
    Rule("NUM", re.compile(r"(?<![0-9])(?<!0[xX])(?P<v>\d{15,20})(?![0-9A-Fa-f])"), log_only=True),
)

# 순서가 중요하다: M11·M1·M3·M4 → 자격증명 → URI·이메일 → 문맥 있는 식별자 → 형식 → 문맥 없는 숫자 → 나머지 M.
_BASE_RULES: tuple[Rule, ...] = (
    # --- 자격증명 ---
    Rule("CRED", re.compile(r'(?i)\b(?:response|nonce|cnonce|opaque)(?u:\s)*=(?u:\s)*"?(?P<v>(?u:[^",\s])+)"?'),
         context=_SIP_AUTH_CONTEXT),
    Rule("CRED", re.compile(r"\b(?:RES|AUTN|AUTS|XRES)" + _SEP + r"(?:0x)?(?P<v>[0-9A-Fa-f]{8,})\b")),
    Rule("CRED", re.compile(r'(?i)\b(?:password|passwd|pwd|secret)' + _SEP + r'(?P<v>(?u:[^\s",;])+)')),
    # `token`은 짧은 숫자 값(RIL 요청 token `token=612`·`token: 0042`, `0x29`)을 빼고 본다. 긴 인증 토큰은 그대로
    Rule("CRED", re.compile(r'(?i)\btoken' + _SEP + r'(?P<v>(?u:[^\s",;])+)'), check=_token_secret, gate=("token",)),
    Rule("CRED", re.compile(r'(?i)\b(?:api[_-]?key|key)' + _SEP + r'(?P<v>[A-Za-z0-9+/=_-]+)'),
         check=_secretish),
    # AKA 키 (대소문자 구분: 소문자 `ok=`·`ik` 섞인 문구를 피한다; Kc 64비트 = 16 hex가 하한)
    # 대문자 변형(`KI`, `OPC`)은 받고 소문자(`ki=`, `ck=`)는 받지 않는다(체크섬 등 일반 키와 겹친다)
    Rule("CRED", re.compile(r"\b(?:Ki|KI|Kc|KC|CK|IK|OPc|OPC|OP|K)" + _SEP + r"(?:0x)?(?P<v>[0-9A-Fa-f]{16,})\b")),
    # PIN/PUK는 숫자 4~8자리만 (`pin1=PINSTATE_ENABLED_NOT_VERIFIED`·`pin=disabled`는 상태값).
    # `pinState=`·`mPin1State=`·`PIN1 retry=3`은 키 바로 뒤에 `=`/`:`가 없어 맞지 않는다
    Rule("CRED", re.compile(r'(?i)\bm?(?:pin1?2?|puk1?2?|pin_?code|puk_?code)' + _SEP + r'(?P<v>\d{4,8})(?!\w)'),
         gate=("pin", "puk")),
    Rule("CRED", re.compile(r'(?i)\b(?:pass|passcode)' + _SEP + r'(?P<v>(?u:[^\s",;)\]}])+)'), check=_pass_like, gate=("pass",)),
    Rule("CRED", re.compile(r"(?i)\bBearer(?u:\s)+(?P<v>[A-Za-z0-9._~+/=-]{16,})"), gate=("bearer",)),
    Rule("CRED", re.compile(r"(?<![\w.-])(?P<v>eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?)")),  # JWT
    # --- URI·주소 ---
    Rule("IMPU", re.compile(r"\bsips?:(?P<v>(?u:[^@\s;>\"<])+)@")),
    Rule("IMPI", re.compile(r'(?i)\b(?:username|impi)(?:(?u:\s)*=|"(?u:\s)*:)(?u:\s)*"?(?P<v>(?u:[^@"\s,<])+)@')),
    Rule("MSISDN", re.compile(r"\btel:(?P<v>\+?[\d-]{6,})")),
    Rule("EMAIL", re.compile(r"(?<![\w.%+-])(?P<v>[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")),
    Rule("SUPI", re.compile(r"\b(?P<v>imsi-\d{5,15})\b")),
    Rule("SUCI", re.compile(r"\b(?P<v>suci-[0-9A-Fa-f-]{6,})")),
    # --- 문맥 있는 식별자 ---
    Rule("IMSI", re.compile(r'(?i)\bimsi' + _SEP + r'(?P<v>\d{6,15})' + _NUM_END)),
    Rule("IMEI", re.compile(r'(?i)\b(?:imei|meid|device_?id)' + _SEP + r'(?P<v>[0-9A-Fa-f]{14,16})' + _NUM_END)),
    # 구분자(`-`·공백) IMEI/IMEISV, 키에 붙은 값(`IMEI4901…`). 끝 경계를 두지 않아 `…518_1`도 값 부분만 토큰
    Rule("IMEI", re.compile(r'(?i)\bm?(?:imei|imeisv|meid|device_?id)"?(?u:\s)*[=:]?(?u:\s)*"?(?P<v>\d(?:[ -]?\d){13,15})'),
         check=lambda v: 14 <= len(_digits(v)) <= 16, gate=("imei", "meid", "device")),
    Rule("EID", re.compile(r'(?i)\bm?eid' + _SEP + r'(?P<v>\d{32})\b'), gate=("eid",)),
    # getprop 형식 `[ro.serialno]: [R3CN30ABCDE]`도 받는다
    Rule("SERIAL", re.compile(
        r'(?i)\b(?:ro\.(?:boot\.)?serialno|serialno|serial_?(?:no|num|number))(?:' + _SEP + r'|\]:(?u:\s)*\[)(?P<v>[A-Za-z0-9]{6,})\b'),
         gate=("serial",)),
    # `sn`·`serial`·`mSerial`은 시퀀스 번호(`SN=12345678 PDCP`)·RIL serial(`serial=0041`, `mSerial=41`)과
    # 겹치므로 영문+숫자 혼합만 (`sn` 6자, `serial` 8자 이상)
    Rule("SERIAL", re.compile(r'(?i)\bsn' + _SEP + r'(?P<v>[A-Za-z0-9]{6,})\b'), check=_alnum_mixed, gate=("sn",)),
    Rule("SERIAL", re.compile(r'(?i)\bm?serial' + _SEP + r'(?P<v>[A-Za-z0-9]{8,})\b'), check=_alnum_mixed, gate=("serial",)),
    # `wifiMacAddress=`처럼 앞에 낱말이 붙은 키는 `macaddr(ess)`만 받는다(`together=` 같은 낱말 끝을 피한다)
    Rule("MAC", re.compile(r'(?i)(?:\b(?:mac(?:_?addr(?:ess)?)?|bssid|hwaddr|ether|bd_?addr)|(?<=[a-z])mac_?addr(?:ess)?)'
                           + _SEP + r'(?P<v>[0-9A-F]{12})\b'),
         gate=("mac", "bssid", "hwaddr", "ether", "bd_addr", "bdaddr")),
    Rule("GEO", re.compile(r"(?i)\b(?:m?lat(?:itude)?|m?lon(?:g(?:itude)?)?|lng|altitude)" + _SEP + r"(?P<v>[-+]?\d{1,3}\.\d{3,})"),
         gate=("lat", "lon", "lng", "altitude")),
    Rule("GEO", re.compile(r"(?i)\b(?:gps|fused|network|passive)(?u:\s)+(?P<v>[-+]?\d{1,3}\.\d{4,},[-+]?\d{1,3}\.\d{4,})"),
         gate=("gps", "fused", "network", "passive")),
    # `iccid=`·`"iccid":` 외에 `ICCID(<값>)`·`iccid[<값>]`도(벤더 데몬 표기)
    Rule("ICCID", re.compile(r'(?i)\biccid(?:' + _SEP + r'|(?u:\s)*[(\[](?u:\s)*)(?P<v>[0-9A-Fa-f]{18,20})' + _NUM_END)),
    Rule("TMSI", re.compile(r'(?i)\b(?:p-?tmsi|m-?tmsi|s-?tmsi|tmsi)' + _SEP + r'(?P<v>(?:0x)?[0-9A-Fa-f]{4,10})\b')),
    Rule("GUTI", re.compile(r'(?i)\b(?:5g-?guti|guti)' + _SEP + r'(?P<v>[0-9A-Fa-f][0-9A-Fa-f-]{7,})\b')),
    # 셀 위치 키 (`mCid`·`CellIdentity*`의 키는 항상). 맨 `cid`는 키로 두지 않는다 — 데이터 콜 context id
    # (`DataCallResponse`·`SetupDataCallResult`·벤더 `VendorDataCall{` 등)라 분석에 쓰므로 객체 안·밖 어디서나 그대로 둔다
    # (11/02 사용자 결정). `mCid`는 CellIdentity의 셀 ID 필드라 계속 가린다
    Rule("CELL", re.compile(
        r"\b(?:mCi|mPci|mTac|mLac|mCid|mNci|mCellId|ci|pci|tac|lac|nci|eci|cellId|cellIdentity)"
        + _SEP + r"(?P<v>0x[0-9A-Fa-f]+|\d+)" + _NUM_END)),
    Rule("MSISDN", re.compile(
        r'(?i)\b(?:msisdn|phone(?:number)?|dest(?:addr)?|destination|number|callee|caller)' + _SEP + r'(?P<v>\+?\d{7,15})'
        + _NUM_END)),
    # --- 형식 ---
    Rule("MSISDN", re.compile(r"(?<![\w+.])(?P<v>\+\d{1,3}[- ]?\d{1,4}[- ]?\d{3,4}[- ]?\d{4})(?!\w|\.\w)")),
    Rule("MSISDN", re.compile(r"(?<![\w.])(?P<v>01[016789][- ]?\d{3,4}[- ]?\d{4})(?!\w|\.\w)")),
    Rule("MAC", re.compile(r"(?<![0-9A-Fa-f:])(?P<v>(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?![0-9A-Fa-f:])")),
    Rule("MAC", re.compile(r"(?<![0-9A-Fa-f-])(?P<v>(?:[0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2})(?![0-9A-Fa-f-])"),
         check=lambda v: not v.replace("-", "").isdigit()),  # 숫자뿐인 대시 조각(날짜·번호)은 제외
    Rule("IMEI", re.compile(r"(?<![\w.+-])(?P<v>\d{2}-\d{6}-\d{6}-\d)(?![\w-]|\.\w)"),
         check=lambda v: _luhn(_digits(v))),  # TAC-SNR-CD
    Rule("IP", re.compile(
        r"(?<![\w.])(?P<v>(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})(?!\w|\.\w)"),
         before=_VERSION_BEFORE),
    # M12 앞뒤 경계에 낱말 문자 전부(`[0-9A-Za-z_:]`): C++ 범위 `DemoService_0::OnHandle`·`V2_4::RadioDataProxy`는 IP가 아니다
    Rule("IP", re.compile(r"(?<![0-9A-Za-z_:])(?P<v>" + _V6_FULL + "|" + _V6_COMP + r")(?![0-9A-Za-z_:])"),
         check=lambda v: v != "::"),
    # 위 규칙의 앞 경계(`:` 금지)에 막히는 주소 키 바로 뒤(`addr:<v6>`, `ipv6address:<v6>/64`)와 끝이 `:`인 잘린 표기
    Rule("IP", re.compile(r'(?i)(?:addr(?:ess)?|\bip(?:v6)?|\bgw|gateway|\bdns\d?)(?u:\s)*[=:](?u:\s)*"?(?P<v>' + _V6_FULL + "|"
                          + _V6_COMP + "|" + _V6_PART + r")(?![0-9A-Fa-f:])"),
         check=lambda v: _v6_like(v, 4), gate=("addr", "ip", "gw", "gateway", "dns")),
    # 줄 경계에서 쪼개진 주소 조각(`::` 없음, 6묶음 이상 — 시각·버전·MAC 모양은 `_v6_like`가 뺀다)
    Rule("IP", re.compile(r"(?<![\w:.])(?P<v>(?:" + _HEX4 + r":){5,7}(?:" + _HEX4 + r")?)(?![0-9A-Fa-f:])"),
         check=lambda v: "::" not in v and _v6_like(v, 6)),
    # --- 문맥 없는 15자리 ---
    Rule("IMEI", re.compile(r"(?<![\w.+-])(?P<v>\d{15})(?!\w|\.\w)"), check=_luhn),
    Rule("IMSI", re.compile(r"(?<![\w.+-])(?P<v>\d{15})(?!\w|\.\w)"), check=_valid_mcc),
    Rule("ICCID", re.compile(r"(?<![\w.+-])(?P<v>89\d{17,18})(?!\w|\.\w)")),
)

RULES: tuple[Rule, ...] = _M_FIRST + _BASE_RULES + _M_LATE

# 다른 규칙이 다시 보지 않는 구간: 번호 토큰, M1 덤프 토큰, `redact()`가 넣은 가림 표시
_PROTECTED = re.compile(TOKEN_RE.pattern + r"|<HEXDUMP \d+B>|<REDACTED:[A-Z][A-Z0-9]*>")
_HOST_TOKEN = re.compile(r"(?<![A-Za-z0-9_.-])host(\d+)(?![A-Za-z0-9_.-])")


def _android_masked(value: str) -> bool:
    return bool(value) and set(value) <= set("*xX")


class AllowPatternError(ValueError):
    """`mask.allow_patterns`의 정규식이 컴파일되지 않는다."""


class Masker:  # noqa: F811  # 위의 타입 별칭 Masker를 이 클래스가 대신한다
    """번호 대응표를 가진 마스커. `masker(text)`로 텍스트를, `mask_value(v)`로 필드 값을
    마스킹한다. 한 파일(분석 1회) 동안 같은 인스턴스를 쓴다."""

    def __init__(self, allow_patterns: Iterable[str] = (), existing_text: str | None = None, *,
                 log_lines: bool = False):
        self.log_lines = bool(log_lines)       # False면 `log_only` 규칙을 mask()·_spans()·find()에서 건너뛴다
        self.allow = []
        for p in allow_patterns or ():
            try:
                self.allow.append(re.compile(p))
            except (re.error, TypeError) as exc:
                raise AllowPatternError(f"mask.allow_patterns 정규식 오류 {p!r}: {exc}") from exc
        self.tables: dict[str, dict[str, int]] = {}
        self.next: dict[str, int] = {}
        self.counts: dict[str, int] = {}
        self.fmts: dict[str, str] = {}          # 번호 토큰 모양이 기본과 다른 종류(`HOST` → `host{n}`)
        if existing_text:
            self.observe(existing_text)

    # -- 번호 -----------------------------------------------------------------

    def observe(self, text: str) -> None:
        """입력에 이미 있는 토큰의 종류별 최대 번호를 기억한다."""
        for hit in TOKEN_RE.finditer(text or ""):
            kind, n = hit.group("kind"), int(hit.group("n"))
            self.next[kind] = max(self.next.get(kind, 0), n)
        if self.log_lines:
            for hit in _HOST_TOKEN.finditer(text or ""):      # M11 `host<n>`도 다음 번호부터
                self.next["HOST"] = max(self.next.get("HOST", 0), int(hit.group(1)))

    def token(self, kind: str, value: str, fmt: str | None = None) -> str:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if fmt is not None and "{n}" not in fmt:               # 번호 없는 모양(`<HEXDUMP nB>`)
            return _render(fmt, kind, 0, value)
        table = self.tables.setdefault(kind, {})
        key = _norm_key(kind, value)
        if key not in table:
            self.next[kind] = self.next.get(kind, 0) + 1
            table[key] = self.next[kind]
        if fmt is None:
            return f"<{kind}#{table[key]}>"
        self.fmts[kind] = fmt
        return _render(fmt, kind, table[key], value)

    def _allowed(self, value: str) -> bool:
        return _android_masked(value) or any(p.fullmatch(value) for p in self.allow)

    # -- 텍스트 ----------------------------------------------------------------

    def __call__(self, text: str) -> str:
        return self.mask(text)

    def mask(self, text: str, forced=None) -> str:
        """`forced`: 갈린 덤프 조각 구간 `[(start, end, kind, 전체 값, 첫 조각?)]`(`forced_lines`·`forced_records`).
        먼저 놓고, 겹치는 일반 규칙 구간은 보지 않는다."""
        if not text:
            return text
        fixed = [f for f in (forced or ()) if 0 <= f[0] < f[1] <= len(text)]
        spans = [(*sp, None) for sp in self._spans_fmt(text, [(f[0], f[1]) for f in fixed])]
        spans += [(a, b, kind, value, None, first) for a, b, kind, value, first in fixed]
        out, pos = [], 0
        for start, end, kind, value, fmt, first in sorted(spans, key=lambda sp: sp[0]):  # 나온 순서대로 번호를 준다
            tok = (self.token(kind, value, fmt) if first is None
                   else self._piece_token(kind, value, first, text[start:end]))
            out += [text[pos:start], tok]
            pos = end
        out.append(text[pos:])
        return "".join(out)

    def _piece_token(self, kind: str, value: str, first: bool, piece: str) -> str:
        """갈린 조각: 전체 값의 토큰(첫 조각이거나 처음 보는 값일 때만 센다). 조각 글자도 그 번호로 표에 넣는다."""
        table = self.tables.setdefault(kind, {})
        key = _norm_key(kind, value)
        tok = self.token(kind, value) if first or key not in table else f"<{kind}#{table[key]}>"
        if len(piece) >= PIECE_MIN_TABLE:   # 짧은 조각("0"·"450")을 넣으면 같은 글자의 이벤트 필드가 토큰이 된다
            table.setdefault(_norm_key(kind, piece), table[key])
        return tok

    def _spans(self, text: str) -> list[tuple[int, int, str, str]]:
        """마스킹할 구간 `[(start, end, kind, value)]` (시작 위치 순).

        기존 토큰은 그대로 둔다(멱등). 규칙은 우선순위 순서로 보고, 앞 규칙이 차지한
        구간과 기존 토큰은 경계가 되어 뒤 규칙이 다시 보지 않는다.
        """
        return [span[:4] for span in self._spans_fmt(text)]

    def _spans_fmt(self, text: str, reserved=()) -> list[tuple[int, int, str, str, str | None]]:
        """`_spans`에 규칙의 토큰 모양(`Rule.fmt`)을 붙인 것. `reserved` 구간(갈린 조각)은 규칙이 보지 않는다."""
        taken = [(m.start(), m.end()) for m in _PROTECTED.finditer(text)] + list(reserved)
        found: list[tuple[int, int, str, str, str | None]] = []
        # 규칙이 ASCII(`re.ASCII`)라 `(?i)`도 ASCII 글자만 접는다 — 한글 줄에서도 게이트가 결과를 바꾸지 않는다
        low = text.lower()
        log_lines = self.log_lines
        for rule in RULES:
            if rule.log_only and not log_lines:
                continue
            if rule.gate and not any(k in low for k in rule.gate):  # 키가 없는 줄은 키 규칙을 돌리지 않는다
                continue
            if not rule.applies(text):  # 문맥 규칙은 줄 전체를 본다
                continue
            ctx_lines = None            # per_line 규칙만: 여러 줄 글이면 문맥은 값이 있는 그 줄에서만 본다(H C1: 보기 머리의
            if rule.per_line and rule.context is not None and "\n" in text:  # 이름 목록 오탐). SIP Digest는 접힌 줄 때문에 글 전체
                ctx_lines = [(m.start(), m.end()) for m in re.finditer(r"[^\n]*", text)
                             if m.end() > m.start() and rule.context.search(m.group(0))]
            free, pos = [], 0
            for start, end in sorted(taken):
                if start > pos:
                    free.append((pos, start))
                pos = max(pos, end)
            free.append((pos, len(text)))
            for lo, hi in free:
                piece = text[lo:hi]
                groups = ("v", "v2") if "v2" in rule.regex.groupindex else ("v",)
                for match in rule.regex.finditer(piece):
                    for group in groups:
                        value = match.group(group)
                        if value is None or self._allowed(value) or (rule.check and not rule.check(value)):
                            continue
                        start, end = match.span(group)
                        if ctx_lines is not None and not any(a <= lo + start < b for a, b in ctx_lines):
                            continue
                        if rule.before is not None and rule.before.search(text[max(0, lo + start - 24):lo + start]):
                            continue
                        found.append((lo + start, lo + end, rule.kind, value, rule.fmt))
                        taken.append((lo + start, lo + end))
        return sorted(found)

    def mask_value(self, value: str) -> str:
        """필드 값. 이미 본 원래 값과 정확히 같으면 그 토큰으로(문맥 없는 값도 같은 번호),
        아니면 텍스트처럼 마스킹한다."""
        if not isinstance(value, str) or not value:
            return value
        for kind, table in self.tables.items():
            key = _norm_key(kind, value)
            if key in table:
                fmt = self.fmts.get(kind)
                return f"<{kind}#{table[key]}>" if fmt is None else _render(fmt, kind, table[key], value)
        return self.mask(value)

    # -- 검사 -----------------------------------------------------------------

    def find(self, text: str, reserved=()) -> list[dict]:
        """마스킹되지 않은 식별자 위치 `[{kind, start, end}]` (값은 내지 않는다). `reserved` 구간은 보지 않는다."""
        return [{"kind": kind, "start": start, "end": end}
                for start, end, kind, *_ in self._spans_fmt(text or "", reserved)]


def _render(fmt: str, kind: str, n: int, value: str) -> str:
    return fmt.format(kind=kind, n=n, b=_dump_bytes(value), h=len(value) // 2)


def new_masker(existing_text: str | None = None, allow_patterns: Iterable[str] = (), *,
               log_lines: bool = False) -> Masker:
    """새 마스커. `existing_text`에 이미 있는 토큰 다음 번호부터 준다. 로그 줄을 가릴 때는 `log_lines=True`."""
    return Masker(allow_patterns=allow_patterns, existing_text=existing_text, log_lines=log_lines)


# --- 갈린 덤프 조각 (oFono 덤프 함수, 표식 `common.dumpjoin.mark()`) -----------------------------------

SPLIT_KINDS = ("IMSI", "ICCID")


def _split_rule(kind: str, head: str) -> Rule:
    return next(r for r in RULES if r.kind == kind and r.regex.pattern.startswith(head))


# 키 있는 규칙만: NAI 속 IMSI(`…@nai.`), `imsi=`, `iccid=`·`ICCID(`. 키 없는 15자리·`89…`·뒤집힌 ICCID(`98…`)는 뺀다.
_SPLIT_RULES = (_split_rule("IMSI", r"(?i)(?<![\w])0?(?P<v>\d{15})(?="), _split_rule("IMSI", r"(?i)\bimsi"),
                _split_rule("ICCID", r"(?i)\biccid"))


def _split_spans(texts: list, groups, masker=None) -> dict[int, list[tuple[int, int, str, str, bool]]]:
    """조각 경계를 넘는 키 있는 IMSI·ICCID 맞음 → `{순번: [(start, end, kind, 전체 값, 첫 조각?)]}`."""
    if not groups:
        return {}
    rules = [(r.kind, r.regex) for r in _SPLIT_RULES]
    texts = [t.rstrip("\r") if isinstance(t, str) else "" for t in texts]
    out: dict[int, list] = {}
    used: list[tuple[int, int, int]] = []
    for kind, value, pieces in dumpjoin.cross_hits(texts, rules, groups):
        if (masker is not None and masker._allowed(value)) or _android_masked(value):
            continue
        if any(i == j and s < f and t < e for i, s, e in pieces for j, t, f in used):
            continue                                   # 같은 값을 두 규칙이 맞힘
        used += pieces
        for n, (i, s, e) in enumerate(pieces):
            out.setdefault(i, []).append((s, e, kind, value, n == 0))
    return {i: sorted(v) for i, v in out.items()}


def forced_lines(masker, lines: list[str]) -> dict[int, list]:
    """원 줄 목록 전체에서 한 번: 갈린 조각 강제 구간 `{줄 순번: [...]}`(`Masker.mask(line, forced=...)`)."""
    return _split_spans(lines, dumpjoin.groups_from_lines([ln.rstrip("\r") for ln in lines]), masker)


def forced_records(masker, recs: list[dict]) -> dict[int, list]:
    """파서 레코드 목록 전체에서 한 번: `msg` 안 강제 구간 `{레코드 순번: [...]}`."""
    return _split_spans([r.get("msg") if isinstance(r, dict) else None for r in recs],
                        dumpjoin.groups_from_records(recs), masker)


def mask_lines(masker, lines: list[str]) -> list[str]:
    """줄 목록 마스킹(갈린 덤프 조각 포함). `masker`가 `Masker`가 아니면 줄마다 부른다."""
    if not isinstance(masker, Masker):
        return [masker(line) for line in lines]
    forced = forced_lines(masker, lines)
    return [masker.mask(line, forced.get(i)) for i, line in enumerate(lines)]


def mask_records(masker, recs: list[dict]) -> list[dict]:
    """레코드 목록의 `msg` 마스킹(갈린 덤프 조각 포함, tag·pid·ts로 묶음). 다른 칸은 그대로다."""
    forced = forced_records(masker, recs) if isinstance(masker, Masker) else {}
    out = []
    for i, rec in enumerate(recs):
        if isinstance(rec, dict) and isinstance(rec.get("msg"), str):
            msg = masker.mask(rec["msg"], forced.get(i)) if forced else masker(rec["msg"])
            rec = dict(rec, msg=msg)
        out.append(rec)
    return out


def residual(text: str, allow_patterns: Iterable[str] = (), *, log_lines: bool = True) -> dict[str, int]:
    """남은 식별자 `{종류: 개수}`: 그 마스커의 `find()`를 줄마다 센 것 그대로(다른 탐지기 없음). 값은 내지 않는다.

    마스커가 줄 단위로 일하므로(`^` 규칙) 줄마다 본다. 그래서 `residual(mask(line)) == {}`가 구조상 성립한다.
    갈린 덤프 조각의 키 있는 IMSI·ICCID는 이은 값 하나로 센다(그 조각 구간은 줄 단위로 다시 세지 않는다)."""
    masker = new_masker(allow_patterns=allow_patterns, log_lines=log_lines)
    lines = (text or "").split("\n")
    forced = forced_lines(masker, lines)
    counts: dict[str, int] = {}
    for i, line in enumerate(lines):
        pieces = forced.get(i, ())
        for hit in masker.find(line, [(p[0], p[1]) for p in pieces]):
            counts[hit["kind"]] = counts.get(hit["kind"], 0) + 1
        for p in pieces:
            if p[4]:
                counts[p[2]] = counts.get(p[2], 0) + 1
    return dict(sorted(counts.items()))


def redact(text: str, allow_patterns: Iterable[str] = (), *, log_lines: bool = True) -> tuple[str, dict[str, int]]:
    """`find()` 구간마다 `<REDACTED:종류>`로 바꾼다(보기·explore 타임라인, B2-25). `(text, counts)`.
    갈린 덤프 조각은 조각마다 가리고 값 하나로 센다. 걸린 것이 없으면 같은 객체를 그대로 돌려준다."""
    masker = new_masker(allow_patterns=allow_patterns, log_lines=log_lines)
    lines = (text or "").split("\n")
    forced = forced_lines(masker, lines)
    counts: dict[str, int] = {}
    out, changed = [], False
    for i, line in enumerate(lines):
        pieces = forced.get(i, ())
        hits = [(h["start"], h["end"], h["kind"], True) for h in masker.find(line, [(p[0], p[1]) for p in pieces])]
        hits += [(p[0], p[1], p[2], p[4]) for p in pieces]
        if hits:
            changed = True
            parts, pos = [], 0
            for start, end, kind, count in sorted(hits):
                parts += [line[pos:start], f"<REDACTED:{kind}>"]
                pos = end
                if count:
                    counts[kind] = counts.get(kind, 0) + 1
            parts.append(line[pos:])
            line = "".join(parts)
        out.append(line)
    if not changed:
        return text, {}
    return "\n".join(out), dict(sorted(counts.items()))


URL_USERINFO = re.compile(r"://[^/@\s]+@")


def mask_brief(text, limit: int = 120) -> str:
    """사람·관리자에게 보이는 짧은 진단 글(오류 메시지·doctor 내용): URL 자격증명(`://user:token@` → `://<CRED>@`)을 먼저
    가리고 마스킹한 뒤 공백을 접어 `limit`자로 자른다(`db_pr` stage 기록, `job_status --doctor`)."""
    text = " ".join(new_masker().mask(URL_USERINFO.sub("://<CRED>@", str(text or ""))).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
