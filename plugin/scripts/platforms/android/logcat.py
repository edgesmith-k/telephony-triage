"""logcat 줄 해석과 시각 처리 (reference 백엔드의 공통 처리, 16-existing-assets.md §16.3).

- 형식: `threadtime`(기본), 연도 포함(`-v year`), `-v uid`, `-v zone`, `time`.
  `--------- beginning of <buffer>` 줄은 건너뛴다. **버퍼 경계로 쓰지 않는다** —
  병합 logcat에서 이 줄은 그 버퍼의 첫 줄이 나온 자리일 뿐이다.
- 시각: 줄에 연도가 없으면 `year`(없으면 `DEFAULT_YEAR`), 타임존이 없으면
  `tz`(IANA 이름, 없으면 UTC)로 해석해서 **UTC**로 바꾼다. 파서는 사용자
  config를 읽지 않는다 (`02-config.md §4`). 연도 없는 로그가 12월 → 1월로
  넘어가면 연도를 하나 올린다(`year`는 첫 줄의 연도다). 재부팅으로 시계가
  `01-01`로 갔다가 돌아오는 것은 해 넘김이 아니다(12월 → 1월만 센다).
- 입력 인코딩: UTF-8(BOM 허용)과 UTF-16(BOM). `open_log()`가 고른다.
- 슬롯(`phone_id`): 태그 접미사(`DNC-1`) → 메시지 접두어(`[PHONE1]`, `[SUB1]`)
  → 메시지 끝(`[PHONE1]`, AOSP RILJ 형식) 순서. 없으면 `None`
  (`04-parser-matching.md §5.8 (2)`).

로그 형식 변형은 placeholder다 — TODO(SITE:S7). 슬롯 표기는 `site-defaults.yaml`의 `platform.log.phone_id`로 바꾼다.
"""

from __future__ import annotations

import re
from pathlib import Path

# 시각 처리는 플랫폼 무관(`common/logtime.py`), 줄·통계·슬롯 타입은 계약(`platforms/base.py`)이다.
# 기존 import 경로(`platforms.android.logcat.X`)가 같은 객체를 쓰도록 다시 내보낸다.
from common.logtime import (  # noqa: F401
    BACKWARD_THRESHOLD_SEC,
    DEFAULT_YEAR,
    JUMP_THRESHOLD_SEC,
    STAMP_RE,
    UTC,
    coverage,
    format_ts,
    get_tz,
    normalize_ts,
    open_log,
    parse_ts,
)
from common.logtime import STAMP as _STAMP
from common.logtime import build as _build
from common.logtime import micro as _micro  # noqa: F401
from common.logtime import zone_offset as _zone_offset  # noqa: F401
from platforms.base import FileStats, LogLine, PhoneIdRules

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

# 슬롯 기본 표기. 사내 값은 `platform.log.phone_id`로 덮어쓴다 (`platforms.load()`, 02-config.md).
# 태그 접미사는 "이름-숫자" 한 마디만 본다(DN-17-C 같은 DataNetwork 태그는 슬롯이 아니다).
TAG_PHONE_RE = re.compile(r"^[A-Za-z]+(?:-[CI])?-(\d+)$")
MSG_PHONE_PREFIX_RE = re.compile(r"^\[(?:PHONE|SUB)(\d+)\]\s?")
MSG_PHONE_SUFFIX_RE = re.compile(r"\s?\[PHONE(\d+)\]$")


def read_file(
    path: str | Path, file_index: int, tz_name: str | None, year: int | None
) -> tuple[list[LogLine], FileStats]:
    """파일 하나를 읽어 줄 목록과 통계를 준다. 줄 순서는 파일 순서 그대로다."""
    tz = get_tz(tz_name)
    stats = FileStats()
    lines: list[LogLine] = []
    base_year = current_year = year or DEFAULT_YEAR
    prev_month: int | None = None
    with open_log(path) as fh:
        for line_no, raw in enumerate(fh, 1):
            text = raw.rstrip("\r\n")
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
                # 알려진 한계: 11월 → 1월처럼 12월 줄이 없으면 해 넘김을 알 수 없다(월 감소는 재부팅과 구분 불가).
                # 12월 → 1월: 해가 넘어갔다. 재부팅으로 01-01이 끼었다가 12월로 돌아오면 되돌린다.
                if prev_month == 12 and month == 1:
                    current_year += 1
                elif prev_month == 1 and month == 12 and current_year > base_year:
                    current_year -= 1
                if stats.first_month is None:
                    stats.first_month = month
                stats.last_month = prev_month = month
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
                )
            )
            stats.lines += 1
    return lines, stats


def raw_line(line: str) -> bool:
    """줄 맨 앞이 logcat 원문 줄인가 (guard 규칙 10 머리 판별, `LogFormat.raw_line`)."""
    return bool(THREADTIME_RE.match(line) or TIME_RE.match(line))


def find_raw(text: str) -> bool:
    """문장 안 어디든 logcat 원문 줄 모양이 끼었나 (issue_post fill 검사, `LogFormat.find_raw`)."""
    for m in STAMP_RE.finditer(text):
        sub = text[m.start():]
        if THREADTIME_RE.match(sub) or TIME_RE.match(sub):
            return True
    return False


def epoch_break(line: LogLine) -> bool:
    """재부팅 표시 줄 (`LogFormat.epoch_break`). 시계 역행·점프는 백엔드가 따로 본다."""
    return line.tag == "boot_progress_start" or (line.tag.lower() == "kernel" and line.msg.startswith("Linux version "))


DEFAULT_PHONE_RULES = PhoneIdRules((TAG_PHONE_RE,), (MSG_PHONE_PREFIX_RE,), (MSG_PHONE_SUFFIX_RE,))
