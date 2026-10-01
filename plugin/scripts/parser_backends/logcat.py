"""logcat 줄 해석과 시각 처리 (reference 백엔드의 공통 처리, 16-existing-assets.md §16.3).

- 형식: `threadtime`(기본), 연도 포함(`-v year`), `-v uid`, `-v zone`, `time`.
  `--------- beginning of <buffer>` 줄은 건너뛴다.
- 시각: 줄에 연도가 없으면 `year`(없으면 `DEFAULT_YEAR`), 타임존이 없으면
  `tz`(IANA 이름, 없으면 UTC)로 해석해서 **UTC**로 바꾼다. 파서는 사용자
  config를 읽지 않는다 (`02-config.md §4`). 연도 없는 로그가 12월 → 1월로
  넘어가면 연도를 하나 올린다(`year`는 첫 줄의 연도다).
- 슬롯(`phone_id`): 태그 접미사(`DNC-1`) → 메시지 접두어(`[PHONE1]`, `[SUB1]`)
  → 메시지 끝(`[PHONE1]`, AOSP RILJ 형식) 순서. 없으면 `None`
  (`04-parser-matching.md §5.8 (2)`).

로그 형식 변형과 슬롯 표기는 placeholder다 — TODO(SITE:S7) TODO(SITE:S20).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc

# `--year`가 없고 줄에도 연도가 없을 때 쓰는 연도. 결과가 실행 날짜에 따라
# 달라지지 않게 고정값을 쓴다(윤년이라 02-29도 해석된다). 경고를 함께 낸다.
DEFAULT_YEAR = 2000

# 시계 이상 판정 (coverage.clock_anomalies). 한 파일 안에서 앞 줄보다
# BACKWARD_THRESHOLD_SEC 넘게 이르면 역행, JUMP_THRESHOLD_SEC 이상 늦으면 점프.
# 조용한 구간과 시계 점프는 로그만으로 구분할 수 없으므로 점프 기준은 크게 잡았다.
# TODO(SITE:S7) 사내 로그(NITZ 전·재부팅 직후)로 기준을 확인한다.
BACKWARD_THRESHOLD_SEC = 1.0
JUMP_THRESHOLD_SEC = 3600.0

_STAMP = (
    r"(?:(?P<year>\d{4})-)?(?P<mon>\d{2})-(?P<day>\d{2})\s+"
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})\.(?P<frac>\d{3,9})"
    r"(?:\s+(?P<zone>[+-]\d{4}))?"
)
STAMP_RE = re.compile(_STAMP)

# threadtime (+ year / zone / uid): "MM-DD HH:MM:SS.mmm [UID] PID TID L TAG: msg"
THREADTIME_RE = re.compile(
    r"^" + _STAMP
    + r"\s+(?:(?P<uid>[A-Za-z0-9_.]+)\s+)?(?P<pid>\d+)\s+(?P<tid>\d+)"
    r"\s+(?P<level>[VDIWEFA])\s+(?P<tag>[^:]+?)\s*:(?: (?P<msg>.*))?$"
)
# time: "MM-DD HH:MM:SS.mmm L/TAG( PID): msg"
TIME_RE = re.compile(
    r"^" + _STAMP
    + r"\s+(?P<level>[VDIWEFA])/(?P<tag>[^(]+?)\(\s*(?P<pid>\d+)\):(?: (?P<msg>.*))?$"
)
BEGINNING_PREFIX = "--------- "

# 슬롯 — TODO(SITE:S20) 사내 실제 표기로 확인한다.
# 태그 접미사는 "이름-숫자" 한 마디만 본다(DN-17-C 같은 DataNetwork 태그는 슬롯이 아니다).
TAG_PHONE_RE = re.compile(r"^[A-Za-z]+-(\d+)$")
MSG_PHONE_PREFIX_RE = re.compile(r"^\[(?:PHONE|SUB)(\d+)\]\s?")
MSG_PHONE_SUFFIX_RE = re.compile(r"\s?\[PHONE(\d+)\]$")


@dataclass(frozen=True)
class LogLine:
    file_index: int
    line_no: int
    dt: datetime  # UTC
    pid: int
    tid: int | None
    level: str
    tag: str
    msg: str
    buffer: str | None = None


@dataclass
class FileStats:
    lines: int = 0
    unparsed: int = 0
    missing_year: bool = False
    missing_zone: bool = False


def get_tz(name: str | None) -> tzinfo:
    """IANA 이름 → tzinfo. 없으면 UTC. 모르는 이름이면 ValueError."""
    if not name or name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"알 수 없는 타임존: {name}") from exc


def _zone_offset(zone: str) -> timezone:
    sign = -1 if zone[0] == "-" else 1
    minutes = int(zone[1:3]) * 60 + int(zone[3:5])
    return timezone(sign * timedelta(minutes=minutes))


def _micro(frac: str) -> int:
    return int(frac[:6].ljust(6, "0"))


def _build(match: re.Match, year: int, tz: tzinfo) -> datetime:
    naive = datetime(
        year,
        int(match.group("mon")),
        int(match.group("day")),
        int(match.group("h")),
        int(match.group("mi")),
        int(match.group("s")),
        _micro(match.group("frac")),
    )
    zone = match.group("zone")
    local = naive.replace(tzinfo=_zone_offset(zone) if zone else tz)
    return local.astimezone(UTC)


def read_file(
    path: str | Path, file_index: int, tz_name: str | None, year: int | None
) -> tuple[list[LogLine], FileStats]:
    """파일 하나를 읽어 줄 목록과 통계를 준다. 줄 순서는 파일 순서 그대로다."""
    tz = get_tz(tz_name)
    stats = FileStats()
    lines: list[LogLine] = []
    current_year = year or DEFAULT_YEAR
    prev_month: int | None = None
    buffer = None
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        for line_no, raw in enumerate(fh, 1):
            text = raw.rstrip("\r\n")
            if text.startswith("--------- beginning of "):
                buffer = text.removeprefix("--------- beginning of ").strip()
            if not text.strip() or text.startswith(BEGINNING_PREFIX):
                continue
            match = THREADTIME_RE.match(text) or TIME_RE.match(text)
            if not match:
                stats.unparsed += 1
                continue
            if match.group("year"):
                use_year = int(match.group("year"))
            else:
                month = int(match.group("mon"))
                # 12월 → 1월: 해가 넘어갔다 (월이 6 넘게 줄면 해가 넘어간 것으로 본다).
                if prev_month is not None and prev_month - month >= 6:
                    current_year += 1
                prev_month = month
                use_year = current_year
                if year is None:
                    stats.missing_year = True
            if not match.group("zone") and tz_name is None:
                stats.missing_zone = True
            try:
                dt = _build(match, use_year, tz)
            except ValueError:  # 존재하지 않는 날짜 (예: 평년의 02-29)
                stats.unparsed += 1
                continue
            tid = match.groupdict().get("tid")
            lines.append(
                LogLine(
                    file_index=file_index,
                    line_no=line_no,
                    dt=dt,
                    pid=int(match.group("pid")),
                    tid=int(tid) if tid is not None else None,
                    level=match.group("level"),
                    tag=match.group("tag").strip(),
                    msg=match.group("msg") or "",
                    buffer=buffer,
                )
            )
            stats.lines += 1
    return lines, stats


def format_ts(dt: datetime) -> str:
    """UTC ISO 문자열 (밀리초, `Z`). 같은 형식끼리는 문자열 비교가 시각 비교와 같다."""
    dt = dt.astimezone(UTC)
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def parse_ts(value: str) -> datetime:
    """오프셋 있는 ISO 시각(`Z` 포함) → UTC datetime. 오프셋이 없으면 ValueError."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"타임존 없는 시각: {value}")
    return dt.astimezone(UTC)


def normalize_ts(value, tz_name: str | None, year: int | None) -> datetime | None:
    """외부 파서가 준 시각을 UTC로 바꾼다. ISO(오프셋 있거나 없음) 또는
    logcat 스탬프(`MM-DD HH:MM:SS.mmm`, 연도 포함 가능)를 받는다. 모르면 None."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=get_tz(tz_name))
        return dt.astimezone(UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = STAMP_RE.fullmatch(text)
        if not match:
            return None
        use_year = int(match.group("year")) if match.group("year") else (year or DEFAULT_YEAR)
        try:
            return _build(match, use_year, get_tz(tz_name))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_tz(tz_name))
    return dt.astimezone(UTC)


def coverage(files: list[list[LogLine]]) -> dict:
    """파일 시각 범위와 시계 이상. 이상 판정은 파일마다 파일 순서로 한다."""
    first = last = None
    anomalies: list[dict] = []
    for lines in files:
        prev = None
        for line in lines:
            if first is None or line.dt < first:
                first = line.dt
            if last is None or line.dt > last:
                last = line.dt
            if prev is not None:
                delta = (line.dt - prev).total_seconds()
                kind = None
                if delta < -BACKWARD_THRESHOLD_SEC:
                    kind = "backward"
                elif delta >= JUMP_THRESHOLD_SEC:
                    kind = "jump"
                if kind:
                    anomalies.append(
                        {"ts": format_ts(line.dt), "kind": kind, "delta_sec": round(delta, 3)}
                    )
            prev = line.dt
    return {
        "first_ts": format_ts(first) if first else None,
        "last_ts": format_ts(last) if last else None,
        "clock_anomalies": anomalies,
    }


def phone_id(tag: str, msg: str) -> int | None:
    hit = TAG_PHONE_RE.match(tag)
    if hit:
        return int(hit.group(1))
    hit = MSG_PHONE_PREFIX_RE.match(msg)
    if hit:
        return int(hit.group(1))
    hit = MSG_PHONE_SUFFIX_RE.search(msg)
    if hit:
        return int(hit.group(1))
    return None


def strip_phone(msg: str) -> str:
    """슬롯 표기를 뗀 메시지 (RIL 줄 해석용. 이벤트의 `msg`는 원문 그대로 둔다)."""
    msg = MSG_PHONE_PREFIX_RE.sub("", msg, count=1)
    return MSG_PHONE_SUFFIX_RE.sub("", msg, count=1)
