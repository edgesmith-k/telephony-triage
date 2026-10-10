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
- **값 앞 제외(`Rule.before`)**: 값 바로 앞 24자가 이 패턴에 맞으면 그 값은 건너뛴다
  (`version 10.0.1.2`를 IPv4로 보지 않기). `context`(줄 전체 양성 조건)와 반대 방향의 음성 조건이다.
- **게이트(`Rule.gate`)**: 키 이름 문맥 규칙은 소문자 줄에 그 키 부분문자열이 하나라도 있을 때만
  돈다. 결과는 같고 규칙당 고정비(줄마다 `finditer`)만 줄인다(08-safety.md §8 성능).
- **예외**: `issue-db.config.yaml`의 `mask.allow_patterns`에 전체가 맞는 값은 그대로 둔다.
  Android 자체 마스킹(`***`, `xxxxxx`)도 그대로 둔다.

탐지 규칙의 키 이름·형식은 일반적인 Android 로그 기준이고, 사내 로그에서 오탐·누락을
확인한다 — TODO(SITE:S13).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

Masker = Callable[[str], str]

TOKEN_RE = re.compile(r"<(?P<kind>[A-Z][A-Z0-9]*)#(?P<n>\d+)>")
KINDS = ("IMSI", "IMEI", "ICCID", "SUPI", "SUCI", "TMSI", "GUTI", "MSISDN", "IMPU", "IMPI",
         "CELL", "IP", "MAC", "EMAIL", "CRED", "EID", "GEO", "SERIAL")

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

# 키와 값 사이: `key=v`, `key: v`, JSON `"key":"v"`
_SEP = r'"?\s*[=:]\s*"?'

_NUM_END = r"(?![\w*]|\.\w)"  # 숫자 값 뒤: 단어 문자·`*`(Android 부분 마스킹)·`.<글자>`(버전·IP의 일부)가 이어지면 안 된다. 문장 끝 `.`은 된다

# 순서가 중요하다: 자격증명 → URI·이메일 → 문맥 있는 식별자 → 형식 → 문맥 없는 숫자.
RULES: tuple[Rule, ...] = (
    # --- 자격증명 ---
    Rule("CRED", re.compile(r'(?i)\b(?:response|nonce|cnonce|opaque)\s*=\s*"?(?P<v>[^",\s]+)"?'),
         context=_SIP_AUTH_CONTEXT),
    Rule("CRED", re.compile(r"\b(?:RES|AUTN|AUTS|XRES)\s*[=:]\s*(?:0x)?(?P<v>[0-9A-Fa-f]{8,})\b")),
    Rule("CRED", re.compile(r'(?i)\b(?:password|passwd|pwd|secret|token)\s*[=:]\s*"?(?P<v>[^\s",;]+)')),
    Rule("CRED", re.compile(r'(?i)\b(?:api[_-]?key|key)\s*[=:]\s*"?(?P<v>[A-Za-z0-9+/=_-]+)'),
         check=_secretish),
    # AKA 키 (대소문자 구분: 소문자 `ok=`·`ik` 섞인 문구를 피한다; Kc 64비트 = 16 hex가 하한)
    # 대문자 변형(`KI`, `OPC`)은 받고 소문자(`ki=`, `ck=`)는 받지 않는다(체크섬 등 일반 키와 겹친다)
    Rule("CRED", re.compile(r"\b(?:Ki|KI|Kc|KC|CK|IK|OPc|OPC|OP|K)" + _SEP + r"(?:0x)?(?P<v>[0-9A-Fa-f]{16,})\b")),
    # PIN/PUK는 숫자 4~8자리만 (`pin1=PINSTATE_ENABLED_NOT_VERIFIED`·`pin=disabled`는 상태값).
    # `pinState=`·`mPin1State=`·`PIN1 retry=3`은 키 바로 뒤에 `=`/`:`가 없어 맞지 않는다
    Rule("CRED", re.compile(r'(?i)\bm?(?:pin1?2?|puk1?2?|pin_?code|puk_?code)' + _SEP + r'(?P<v>\d{4,8})(?!\w)'),
         gate=("pin", "puk")),
    Rule("CRED", re.compile(r'(?i)\b(?:pass|passcode)' + _SEP + r'(?P<v>[^\s",;)\]}]+)'), check=_pass_like, gate=("pass",)),
    Rule("CRED", re.compile(r"(?i)\bBearer\s+(?P<v>[A-Za-z0-9._~+/=-]{16,})"), gate=("bearer",)),
    Rule("CRED", re.compile(r"(?<![\w.-])(?P<v>eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?)")),  # JWT
    # --- URI·주소 ---
    Rule("IMPU", re.compile(r"\bsips?:(?P<v>[^@\s;>\"<]+)@")),
    Rule("IMPI", re.compile(r'(?i)\b(?:username|impi)\s*=\s*"?(?P<v>[^@"\s,<]+)@')),
    Rule("MSISDN", re.compile(r"\btel:(?P<v>\+?[\d-]{6,})")),
    Rule("EMAIL", re.compile(r"(?<![\w.%+-])(?P<v>[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})\b")),
    Rule("SUPI", re.compile(r"\b(?P<v>imsi-\d{5,15})\b")),
    Rule("SUCI", re.compile(r"\b(?P<v>suci-[0-9A-Fa-f-]{6,})")),
    # --- 문맥 있는 식별자 ---
    Rule("IMSI", re.compile(r'(?i)\bimsi\s*[=:]\s*"?(?P<v>\d{6,15})' + _NUM_END)),
    Rule("IMEI", re.compile(r'(?i)\b(?:imei|meid|device_?id)\s*[=:]\s*"?(?P<v>[0-9A-Fa-f]{14,16})' + _NUM_END)),
    # 구분자(`-`·공백) IMEI/IMEISV, 키에 붙은 값(`IMEI4901…`). 끝 경계를 두지 않아 `…518_1`도 값 부분만 토큰
    Rule("IMEI", re.compile(r'(?i)\bm?(?:imei|imeisv|meid|device_?id)"?\s*[=:]?\s*"?(?P<v>\d(?:[ -]?\d){13,15})'),
         check=lambda v: 14 <= len(_digits(v)) <= 16, gate=("imei", "meid", "device")),
    Rule("EID", re.compile(r'(?i)\bm?eid' + _SEP + r'(?P<v>\d{32})\b'), gate=("eid",)),
    # getprop 형식 `[ro.serialno]: [R3CN30ABCDE]`도 받는다
    Rule("SERIAL", re.compile(
        r'(?i)\b(?:ro\.(?:boot\.)?serialno|serialno|serial_?(?:no|num|number))(?:' + _SEP + r'|\]:\s*\[)(?P<v>[A-Za-z0-9]{6,})\b'),
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
    Rule("GEO", re.compile(r"(?i)\b(?:gps|fused|network|passive)\s+(?P<v>[-+]?\d{1,3}\.\d{4,},[-+]?\d{1,3}\.\d{4,})"),
         gate=("gps", "fused", "network", "passive")),
    Rule("ICCID", re.compile(r'(?i)\biccid\s*[=:]\s*"?(?P<v>[0-9A-Fa-f]{18,20})' + _NUM_END)),
    Rule("TMSI", re.compile(r'(?i)\b(?:p-?tmsi|m-?tmsi|s-?tmsi|tmsi)\s*[=:]\s*"?(?P<v>(?:0x)?[0-9A-Fa-f]{4,10})\b')),
    Rule("GUTI", re.compile(r'(?i)\b(?:5g-?guti|guti)\s*[=:]\s*"?(?P<v>[0-9A-Fa-f][0-9A-Fa-f-]{7,})\b')),
    # 셀 식별자 — TODO(SITE:S13) RIL 데이터 콜 응답의 `cid`(context id)도 셀로 본다(과잉이지만 안전 쪽)
    Rule("CELL", re.compile(
        r"\b(?:mCi|mPci|mTac|mLac|mCid|mNci|mCellId|cid|ci|pci|tac|lac|nci|eci|cellId|cellIdentity)"
        r"\s*[=:]\s*(?P<v>0x[0-9A-Fa-f]+|\d+)" + _NUM_END)),
    Rule("MSISDN", re.compile(
        r'(?i)\b(?:msisdn|phone(?:number)?|dest(?:addr)?|destination|number|callee|caller)\s*[=:]\s*"?(?P<v>\+?\d{7,15})'
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
    Rule("IP", re.compile(
        r"(?<![0-9A-Fa-f:])(?P<v>(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
        r"|(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?::(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,6})?)"
        r"(?![0-9A-Fa-f:])"),
         check=lambda v: v != "::"),
    # --- 문맥 없는 15자리 ---
    Rule("IMEI", re.compile(r"(?<![\w.+-])(?P<v>\d{15})(?!\w|\.\w)"), check=_luhn),
    Rule("IMSI", re.compile(r"(?<![\w.+-])(?P<v>\d{15})(?!\w|\.\w)"), check=_valid_mcc),
    Rule("ICCID", re.compile(r"(?<![\w.+-])(?P<v>89\d{17,18})(?!\w|\.\w)")),
)


def _android_masked(value: str) -> bool:
    return bool(value) and set(value) <= set("*xX")


class AllowPatternError(ValueError):
    """`mask.allow_patterns`의 정규식이 컴파일되지 않는다."""


class Masker:
    """번호 대응표를 가진 마스커. `masker(text)`로 텍스트를, `mask_value(v)`로 필드 값을
    마스킹한다. 한 파일(분석 1회) 동안 같은 인스턴스를 쓴다."""

    def __init__(self, allow_patterns: Iterable[str] = (), existing_text: str | None = None):
        self.allow = []
        for p in allow_patterns or ():
            try:
                self.allow.append(re.compile(p))
            except (re.error, TypeError) as exc:
                raise AllowPatternError(f"mask.allow_patterns 정규식 오류 {p!r}: {exc}") from exc
        self.tables: dict[str, dict[str, int]] = {}
        self.next: dict[str, int] = {}
        self.counts: dict[str, int] = {}
        if existing_text:
            self.observe(existing_text)

    # -- 번호 -----------------------------------------------------------------

    def observe(self, text: str) -> None:
        """입력에 이미 있는 토큰의 종류별 최대 번호를 기억한다."""
        for hit in TOKEN_RE.finditer(text or ""):
            kind, n = hit.group("kind"), int(hit.group("n"))
            self.next[kind] = max(self.next.get(kind, 0), n)

    def token(self, kind: str, value: str) -> str:
        table = self.tables.setdefault(kind, {})
        key = _norm_key(kind, value)
        if key not in table:
            self.next[kind] = self.next.get(kind, 0) + 1
            table[key] = self.next[kind]
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return f"<{kind}#{table[key]}>"

    def _allowed(self, value: str) -> bool:
        return _android_masked(value) or any(p.fullmatch(value) for p in self.allow)

    # -- 텍스트 ----------------------------------------------------------------

    def __call__(self, text: str) -> str:
        return self.mask(text)

    def mask(self, text: str) -> str:
        if not text:
            return text
        spans = self._spans(text)
        out, pos = [], 0
        for start, end, kind, value in spans:  # 텍스트에 나온 순서대로 번호를 준다
            out += [text[pos:start], self.token(kind, value)]
            pos = end
        out.append(text[pos:])
        return "".join(out)

    def _spans(self, text: str) -> list[tuple[int, int, str, str]]:
        """마스킹할 구간 `[(start, end, kind, value)]` (시작 위치 순).

        기존 토큰은 그대로 둔다(멱등). 규칙은 우선순위 순서로 보고, 앞 규칙이 차지한
        구간과 기존 토큰은 경계가 되어 뒤 규칙이 다시 보지 않는다.
        """
        taken = [(m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
        found: list[tuple[int, int, str, str]] = []
        # ASCII가 아닌 줄은 게이트를 끈다: `(?i)` 정규식은 `ſ`(→s)·`İ`(→i)·`K`(켈빈)도 맞추지만
        # 부분문자열 게이트는 못 맞춘다
        gated, low = text.isascii(), text.lower()
        for rule in RULES:
            if gated and rule.gate and not any(k in low for k in rule.gate):  # 키가 없는 줄은 키 규칙을 돌리지 않는다
                continue
            if not rule.applies(text):  # 문맥 규칙은 줄 전체를 본다
                continue
            free, pos = [], 0
            for start, end in sorted(taken):
                if start > pos:
                    free.append((pos, start))
                pos = max(pos, end)
            free.append((pos, len(text)))
            for lo, hi in free:
                piece = text[lo:hi]
                for match in rule.regex.finditer(piece):
                    value = match.group("v")
                    if self._allowed(value) or (rule.check and not rule.check(value)):
                        continue
                    start, end = match.span("v")
                    if rule.before is not None and rule.before.search(text[max(0, lo + start - 24):lo + start]):
                        continue
                    found.append((lo + start, lo + end, rule.kind, value))
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
                return f"<{kind}#{table[key]}>"
        return self.mask(value)

    # -- 검사 -----------------------------------------------------------------

    def find(self, text: str) -> list[dict]:
        """마스킹되지 않은 식별자 위치 `[{kind, start, end}]` (값은 내지 않는다)."""
        return [{"kind": kind, "start": start, "end": end} for start, end, kind, _ in self._spans(text or "")]


def new_masker(existing_text: str | None = None, allow_patterns: Iterable[str] = ()) -> Masker:
    """새 마스커. `existing_text`에 이미 있는 토큰 다음 번호부터 준다."""
    return Masker(allow_patterns=allow_patterns, existing_text=existing_text)
