#!/usr/bin/env python3
"""모의 site 파서 백엔드 (15-local-draft.md §15.2, 16-existing-assets.md §16.6).

사내에서 **검증된 기존 파서를 포팅**해 넣을 자리(`plugin/scripts/parser_backends/site/`,
SITE_PATHS)를 사외에서 흉내 낸 가짜다. `builtin.data.*` 이벤트 두 개를 낸다.

- 사외 레포의 `plugin/` 안에는 두지 않는다. SITE_PATHS 경로가 비어 있어야
  반입 체크리스트(§15.4)를 통과하기 때문이다. 테스트는
  `tests/helpers/make_plugin_root.py --with-site-backend`로 임시 플러그인
  루트에 복사해서 쓴다.
- 백엔드 인터페이스 파일(`plugin/scripts/parser_backends/base.py`)과 reference
  백엔드는 **Phase 2**에서 만든다. 이 모의 백엔드는 그때 `base.py`를 상속하도록
  바꾼다. Phase D0에서는 계약(`contracts.md §기존 자산 연결 계약`)에 적힌
  함수 세 개만 같은 이름·같은 반환 형식으로 제공한다.

계약 (contracts.md §기존 자산 연결 계약)
    parse(paths, tz, year, window) -> events[]
    builtin_events() -> [이름]
    version() -> str

이벤트 형식 (16-existing-assets.md §16.3)
    {ts, tag, msg, event, fields, category_hint, source: "backend:site", phone_id}

같은 입력이면 항상 같은 출력을 낸다.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

NAME = "site"
VERSION = "0.0.1-mock"

# 이 백엔드가 코드로 판별하는 이벤트. 시그니처는 `must_event: builtin.data.<이름>`
# 으로 참조한다. 목록에 없는 `builtin.*` 참조는 db_lint 오류다.
BUILTIN_EVENTS = [
    "builtin.data.setup_not_allowed",
    "builtin.data.user_data_disabled",
]

# threadtime: "MM-DD HH:MM:SS.mmm  PID  TID L TAG: message"
LINE_RE = re.compile(
    r"^(?P<mon>\d{2})-(?P<day>\d{2})\s+"
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})\s+"
    r"(?P<pid>\d+)\s+(?P<tid>\d+)\s+(?P<level>[VDIWEF])\s+"
    r"(?P<tag>[^:]+):\s(?P<msg>.*)$"
)

# 슬롯: 태그 접미사가 먼저, 없으면 메시지 접두어 (04-parser-matching.md §5.8 (2))
TAG_PHONE_RE = re.compile(r"-(\d+)$")
MSG_PHONE_RE = re.compile(r"^\[(?:PHONE|SUB)(\d+)\]")

# 판별 규칙 — 문구는 placeholder다. TODO(SITE:S9)
DETECTORS = [
    (
        "builtin.data.setup_not_allowed",
        re.compile(r"^DNC-\d+$"),
        re.compile(r"evaluation result:\s*NOT_ALLOWED\s*reasons=\[(?P<reasons>[^\]]*)\]"),
    ),
    (
        "builtin.data.user_data_disabled",
        re.compile(r"^DSM-\d+$"),
        re.compile(r"onDataEnabledChanged:\s*enabled=(?P<enabled>false)\s*reason=(?P<reason>\w+)"),
    ),
]


def version() -> str:
    return VERSION


def builtin_events() -> list[str]:
    return list(BUILTIN_EVENTS)


def _phone_id(tag: str, msg: str) -> int | None:
    hit = TAG_PHONE_RE.search(tag)
    if hit:
        return int(hit.group(1))
    hit = MSG_PHONE_RE.match(msg)
    if hit:
        return int(hit.group(1))
    return None


def _timestamp(match: re.Match, tz: str | None, year: int | None) -> str:
    """연도 없는 threadtime 시각을 ISO 문자열로 만든다.

    `tz`/`year`는 인자로만 받는다. 파서는 사용자 config를 읽지 않는다
    (`02-config.md §4`).
    """
    use_year = year or 1900
    offset = _tz_offset(tz)
    stamp = datetime(
        use_year,
        int(match.group("mon")),
        int(match.group("day")),
        int(match.group("h")),
        int(match.group("m")),
        int(match.group("s")),
        int(match.group("ms")) * 1000,
        tzinfo=offset,
    )
    return stamp.isoformat()


def _tz_offset(tz: str | None) -> timezone:
    """모의 백엔드는 IANA 이름을 전부 풀지 않는다. 시험에 쓰는 것만 안다."""
    known = {"Asia/Seoul": 9, "UTC": 0, None: 0}
    hours = known.get(tz, 0)
    return timezone(timedelta(hours=hours))


def parse(
    paths: list[str] | list[Path],
    tz: str | None = None,
    year: int | None = None,
    window: tuple[str, str] | None = None,
) -> list[dict]:
    """로그 파일들을 읽어 이벤트 목록을 만든다.

    마스킹, `parser-rules` extractor 실행, 태그 → 카테고리 매핑은 백엔드가
    아니라 `parse_logcat.py`가 한다 (16-existing-assets.md §16.3).
    """
    events: list[dict] = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            match = LINE_RE.match(line)
            if not match:
                continue
            tag = match.group("tag").strip()
            msg = match.group("msg")
            ts = _timestamp(match, tz, year)
            if window and not (window[0] <= ts <= window[1]):
                continue
            phone_id = _phone_id(tag, msg)
            base = {
                "ts": ts,
                "tag": tag,
                "msg": msg,
                "pid": int(match.group("pid")),
                "tid": int(match.group("tid")),
                "level": match.group("level"),
                "phone_id": phone_id,
                "category_hint": "data" if tag.startswith(("DNC-", "DSM-", "DRM-", "DPM-", "DCM-", "DSRM-", "DN-")) else None,
                "source": f"backend:{NAME}",
            }
            hit = False
            for event_name, tag_re, msg_re in DETECTORS:
                if not tag_re.match(tag):
                    continue
                found = msg_re.search(msg)
                if not found:
                    continue
                item = dict(base)
                item["event"] = event_name
                item["fields"] = {k: v for k, v in found.groupdict().items() if v is not None}
                events.append(item)
                hit = True
            if not hit:
                item = dict(base)
                item["event"] = None
                item["fields"] = {}
                events.append(item)
    return events
