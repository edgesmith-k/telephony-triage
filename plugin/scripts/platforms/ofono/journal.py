"""형식 가정(placeholder) — 실제 로그 확보 후 바꾼다. TODO(SITE:S24)

oFono 플랫폼의 로그 줄 해석(17-platforms 설계 §5). 실제 사내 로그 형식(journald 출력 옵션·syslog 여부·레벨 표기·
타임존·연도·호스트 칸)은 아직 모른다. 아래 두 형식은 공개 도구의 기본 출력을 **가정**한 것이고 합성 로그로만 시험했다.

- (a) `journalctl -o short-iso-precise`: `2026-09-20T14:32:09.100000+09:00 host ident[pid]: msg`
  (타임존이 없으면 `tz`, 소수점 자리는 1~9, 오프셋 `Z`·`±HH:MM`·`±HHMM`. 범위 밖 오프셋 줄은 해석 못 함으로 센다).
- (b) RFC3164 syslog / `journalctl -o short`: `Sep 20 14:32:11[.ffffff] host ident[pid]: msg`.
  연도·타임존이 없으므로 `year`(없으면 `DEFAULT_YEAR`)·`tz`와 12월 → 1월 해 넘김 규칙을 쓴다(logcat과 같은 규칙,
  시각 함수는 `common.logtime`).
- 호스트 칸은 ASCII 호스트 이름(`[A-Za-z0-9][A-Za-z0-9_.-]*`), ident는 ASCII `[A-Za-z0-9_.@-]+`만 받는다 — 스탬프로
  시작하는 보통 문장(한국어 낱말이 host·ident 자리에 오는 것)을 원문 줄로 보지 않는다(guard 규칙 10·Jira 게시 검사 오탐).
- `tag = ident`, `pid`는 없으면 0, `tid = None`, `level = "I"`(short 출력에는 우선순위가 없다, TODO(SITE:S24)).
  `host`는 줄 객체에 넣지 않는다(PII일 수 있다).
- `-- `로 시작하는 journalctl 안내 줄(`-- Boot ...`, `-- No entries --` 등)은 건너뛴다(해석 못 한 줄로 세지 않는다).
  TODO(SITE:S24) 재부팅 표시로 쓸지는 실제 로그를 본 뒤 정한다.

ident 하나(`ofonod`) 안의 모듈(`src/x.c`)을 태그로 쪼갤지는 실제 로그를 받은 뒤 정한다(설계 R5).
표준 라이브러리와 `common.logtime`·`platforms.base`만 쓴다(guard가 레지스트리로 불러온다).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.logtime import DEFAULT_YEAR, UTC, get_tz, micro, open_log
from platforms.base import FileStats, LogLine

# host·ident는 ASCII 토큰만 받는다(`Sep 20 14:32:11 단말 재부팅: 확인됨` 같은 보통 문장을 원문 줄로 보지 않게).
_TAIL = (r"\s+(?P<host>[A-Za-z0-9][A-Za-z0-9_.-]*)\s+(?P<ident>[A-Za-z0-9_.@-]+)(?:\[(?P<pid>\d+)\])?:"
         r"\s?(?P<msg>.*)$")
ISO_STAMP = (
    r"(?P<year>\d{4})-(?P<mon>\d{2})-(?P<day>\d{2})T(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})"
    r"(?:\.(?P<frac>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:?\d{2})?"
)
BSD_STAMP = (
    r"(?P<bmon>[A-Z][a-z]{2})\s+(?P<day>\d{1,2})\s+(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})"
    r"(?:\.(?P<frac>\d{1,6}))?"
)
ISO_RE = re.compile(r"^" + ISO_STAMP + _TAIL)
BSD_RE = re.compile(r"^" + BSD_STAMP + _TAIL)
_STAMP_RE = re.compile(ISO_STAMP + "|" + BSD_STAMP.replace("?P<", "?P<x_"))
MONTHS = {name: i for i, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
NOTICE_PREFIX = "-- "
DEFAULT_LEVEL = "I"


def _zone(text: str) -> timezone:
    """`Z`·`+09:00`·`+0900` → timezone. 시 ≥ 24·분 ≥ 60이면 ValueError(그 줄은 해석 못 함으로 센다)."""
    if text == "Z":
        return UTC
    text = text.replace(":", "")
    hours, minutes = int(text[1:3]), int(text[3:5])
    if hours > 23 or minutes > 59:
        raise ValueError(f"타임존 오프셋 범위 밖: {text}")
    return timezone((-1 if text[0] == "-" else 1) * timedelta(hours=hours, minutes=minutes))


def _match(text: str) -> re.Match | None:
    hit = ISO_RE.match(text) or BSD_RE.match(text)
    if hit and hit.groupdict().get("bmon") is not None and hit.group("bmon") not in MONTHS:
        return None
    return hit


def read_file(path: str | Path, file_index: int, tz_name: str | None, year: int | None) -> tuple[list[LogLine], FileStats]:
    """파일 하나를 읽어 줄 목록과 통계를 준다(`LogFormat.read_file`). 줄 순서는 파일 순서 그대로다."""
    tz = get_tz(tz_name)
    stats = FileStats()
    lines: list[LogLine] = []
    base_year = current_year = year or DEFAULT_YEAR
    prev_month: int | None = None
    with open_log(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            text = raw.rstrip("\r\n")
            if not text.strip() or text.startswith(NOTICE_PREFIX):
                continue
            hit = _match(text)
            if not hit:
                stats.unparsed += 1
                continue
            groups = hit.groupdict()
            if groups.get("year"):
                use_year, month = int(groups["year"]), int(groups["mon"])
                try:
                    zone = _zone(groups["zone"]) if groups.get("zone") else None
                except ValueError:  # 이상 오프셋
                    stats.unparsed += 1
                    continue
            else:
                month = MONTHS[groups["bmon"]]
                # 해 넘김은 logcat과 같은 규칙(12월 → 1월만 센다, 재부팅으로 끼었다 돌아오면 되돌린다).
                if prev_month == 12 and month == 1:
                    current_year += 1
                elif prev_month == 1 and month == 12 and current_year > base_year:
                    current_year -= 1
                if stats.first_month is None:
                    stats.first_month = month
                stats.last_month = prev_month = month
                use_year, zone = current_year, None
                if year is None:
                    stats.missing_year = True
            if zone is None and tz_name is None:
                stats.missing_zone = True
            try:
                naive = datetime(use_year, month, int(groups["day"]), int(groups["h"]), int(groups["mi"]),
                                 int(groups["s"]), micro(groups["frac"] or "0"))
            except ValueError:  # 없는 날짜·시각
                stats.unparsed += 1
                continue
            lines.append(LogLine(
                file_index=file_index,
                line_no=line_no,
                dt=naive.replace(tzinfo=zone or tz).astimezone(UTC),
                pid=int(groups["pid"]) if groups.get("pid") else 0,
                tid=None,
                level=DEFAULT_LEVEL,
                tag=groups["ident"],
                msg=groups["msg"] or "",
            ))
            stats.lines += 1
    return lines, stats


def raw_line(line: str) -> bool:
    """줄 맨 앞이 가정 형식 (a)·(b)의 원문 줄인가 (guard 규칙 10, `LogFormat.raw_line`)."""
    return _match(line) is not None


def find_raw(text: str) -> bool:
    """문장 안 어디든 가정 형식 원문 줄이 끼었나 (issue_post fill 검사, `LogFormat.find_raw`)."""
    return any(_match(text[m.start():]) for m in _STAMP_RE.finditer(text))


def epoch_break(line: LogLine) -> bool:
    """재부팅 표시 줄 (`LogFormat.epoch_break`): 커널 부팅 배너. TODO(SITE:S24)"""
    return line.tag == "kernel" and line.msg.startswith("Linux version ")
