"""마스킹 함수 (contracts.md §3.2 "마스킹 함수", 08-safety.md §8).

`mask_pii.py`와 `parse_logcat.py`(`parse --mask`, `cut`)가 공유한다.

- **번호 토큰**: 한 마스커(파일 하나 또는 분석 1회) 안에서 같은 원래 값은 같은
  `<종류#n>`, 다른 값은 다른 번호. 번호는 처음 나온 순서대로 매긴다. 원래 값과 번호의
  대응표는 메모리에만 있다.
- **이미 토큰이 있는 입력**: `observe()`로 입력 전체의 종류별 최대 번호를 먼저 구하고,
  새 값에는 그 다음 번호부터 준다(`<CELL#1>`이 있으면 새 셀은 `<CELL#2>`).
- **멱등**: 기존 토큰은 건드리지 않는다. 마스킹된 입력에 다시 적용해도 같다.
- **문맥 우선**: 키 이름 문맥(`imsi=`, `mCi=` 등)을 먼저 보고, 숫자 길이만으로 판정하는
  규칙(문맥 없는 15자리)은 Luhn·MCC 확인을 거친다. 빌드 번호·타임스탬프 오탐을 피하려고
  숫자 규칙은 단어 경계(`_`, `.` 포함) 안에서만 본다.
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
         "CELL", "IP", "MAC", "EMAIL", "CRED")

_SIP_AUTH_CONTEXT = re.compile(
    r"(?i)\b(?:authorization|www-authenticate|proxy-authenticate|proxy-authorization|digest)\b"
)


@dataclass(frozen=True)
class Rule:
    kind: str
    regex: re.Pattern
    check: Callable[[str], bool] | None = None      # 값 검사 (Luhn 등)
    context: re.Pattern | None = None               # 이 문맥이 있는 텍스트에서만

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
    Rule("IP", re.compile(
        r"(?<![\w.])(?P<v>(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})(?!\w|\.\w)")),
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


class Masker:
    """번호 대응표를 가진 마스커. `masker(text)`로 텍스트를, `mask_value(v)`로 필드 값을
    마스킹한다. 한 파일(분석 1회) 동안 같은 인스턴스를 쓴다."""

    def __init__(self, allow_patterns: Iterable[str] = (), existing_text: str | None = None):
        self.allow = [re.compile(p) for p in allow_patterns or ()]
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
        if value not in table:
            self.next[kind] = self.next.get(kind, 0) + 1
            table[value] = self.next[kind]
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return f"<{kind}#{table[value]}>"

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
        for rule in RULES:
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
                    found.append((lo + start, lo + end, rule.kind, value))
                    taken.append((lo + start, lo + end))
        return sorted(found)

    def mask_value(self, value: str) -> str:
        """필드 값. 이미 본 원래 값과 정확히 같으면 그 토큰으로(문맥 없는 값도 같은 번호),
        아니면 텍스트처럼 마스킹한다."""
        if not isinstance(value, str) or not value:
            return value
        for kind, table in self.tables.items():
            if value in table:
                return f"<{kind}#{table[value]}>"
        return self.mask(value)

    # -- 검사 -----------------------------------------------------------------

    def find(self, text: str) -> list[dict]:
        """마스킹되지 않은 식별자 위치 `[{kind, start, end}]` (값은 내지 않는다)."""
        return [{"kind": kind, "start": start, "end": end} for start, end, kind, _ in self._spans(text or "")]


def new_masker(existing_text: str | None = None, allow_patterns: Iterable[str] = ()) -> Masker:
    """새 마스커. `existing_text`에 이미 있는 토큰 다음 번호부터 준다."""
    return Masker(allow_patterns=allow_patterns, existing_text=existing_text)
