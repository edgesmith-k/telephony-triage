"""로그 시각 처리 — 플랫폼 무관 (`platforms/android/logcat.py`에서 옮김, 17-platforms 묶음 1).

- 시각: 줄에 연도가 없으면 `year`(없으면 `DEFAULT_YEAR`), 타임존이 없으면 `tz`(IANA 이름, 없으면 UTC)로
  해석해서 **UTC**로 바꾼다. 파서는 사용자 config를 읽지 않는다 (`02-config.md §4`).
- 입력 인코딩: UTF-8(BOM 허용)과 UTF-16(BOM). `open_log()`가 고른다.
- 시계 이상 기준(`BACKWARD_THRESHOLD_SEC`·`JUMP_THRESHOLD_SEC`)과 `coverage()`는 줄 형식과 무관하다
  (줄 객체의 `dt`만 본다).
- `STAMP_RE`(`[YYYY-]MM-DD HH:MM:SS.fff [+zzzz]`)는 외부 파서·시험 절차 파일 시각(`normalize_ts`)에도 쓰는 스탬프다.

`common/`은 `platforms`를 import하지 않는다. 플랫폼 모듈(`platforms/android/logcat.py`)이 이 모듈의 객체를 그대로 다시 내보낸다.
"""

from __future__ import annotations

import codecs
import re
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

STAMP = (
    r"(?:(?P<year>\d{4})-)?(?P<mon>\d{2})-(?P<day>\d{2})\s+"
    r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})\.(?P<frac>\d{3,9})"
    r"(?:\s+(?P<zone>[+-]\d{4}))?"
)
STAMP_RE = re.compile(STAMP)


def get_tz(name: str | None) -> tzinfo:
    """IANA 이름 → tzinfo. 없으면 UTC. 모르는 이름이면 ValueError."""
    if not name or name.upper() == "UTC":
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"알 수 없는 타임존: {name}") from exc


def zone_offset(zone: str) -> timezone:
    sign = -1 if zone[0] == "-" else 1
    minutes = int(zone[1:3]) * 60 + int(zone[3:5])
    return timezone(sign * timedelta(minutes=minutes))


def micro(frac: str) -> int:
    return int(frac[:6].ljust(6, "0"))


def build(match: re.Match, year: int, tz: tzinfo) -> datetime:
    """`STAMP` 그룹(mon·day·h·mi·s·frac·zone)이 있는 일치 → UTC datetime. 없는 날짜면 ValueError."""
    naive = datetime(
        year,
        int(match.group("mon")),
        int(match.group("day")),
        int(match.group("h")),
        int(match.group("mi")),
        int(match.group("s")),
        micro(match.group("frac")),
    )
    zone = match.group("zone")
    local = naive.replace(tzinfo=zone_offset(zone) if zone else tz)
    return local.astimezone(UTC)


def open_log(path: str | Path):
    """로그 텍스트 열기: UTF-16 BOM이면 utf-16, 아니면 utf-8-sig(BOM 제거)."""
    with open(path, "rb") as fh:
        head = fh.read(2)
    enc = "utf-16" if head in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE) else "utf-8-sig"
    return open(path, encoding=enc, errors="replace", newline="")


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
            return build(match, use_year, get_tz(tz_name))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_tz(tz_name))
    return dt.astimezone(UTC)


def coverage(files: list[list]) -> dict:
    """파일 시각 범위와 시계 이상. 이상 판정은 파일마다 파일 순서로 한다. 줄 객체는 `dt`(UTC)만 쓴다."""
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
