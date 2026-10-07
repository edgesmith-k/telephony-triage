#!/usr/bin/env python3
"""모의 "기존 파서" (16-existing-assets.md §16.3 "대안: 어댑터 방식").

사내에서 포팅하지 않고 그대로 실행할 기존 파서를 흉내 낸다. 로그 파일 하나를
받아 자기 형식의 JSON(`{"records": [...]}`)을 stdout으로 낸다. 어댑터
`site_data_existing.py`가 이 출력을 이벤트로 바꾼다.

테스트는 이 파일을 임시 플러그인 루트의 `scripts/adapters/site_vendor/legacy_parser.py`로
복사하고 `site-defaults.yaml`의 `external_parsers.data.command`에
`${CLAUDE_PLUGIN_ROOT}`를 써서 부른다(치환 확인). 판별 문구는 placeholder다.

CLI:
    python3 legacy_data_parser.py <logcat>
"""

from __future__ import annotations

import json
import re
import sys

LINE_RE = re.compile(
    r"^(?P<time>\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+\d+\s+\d+\s+[VDIWEF]\s+(?P<tag>[^:]+?):\s(?P<msg>.*)$"
)
RULES = [
    ("DATA_SETUP_BLOCKED", re.compile(r"^DNC-(\d+)$"), re.compile(r"Data disallowed reasons:\s*(?P<reasons>[A-Z_ ]+)")),
    ("USER_DATA_OFF", re.compile(r"^DSMGR-(\d+)$"), re.compile(r"notifyDataEnabledChanged:\s*enabled=false,\s*reason=(?P<reason>\w+)")),
    ("DATA_SETTINGS_SEEN", re.compile(r"^DSMGR-(\d+)$"), re.compile(r"mIsDataEnabled=(?P<value>\w+)")),
]


def main(argv: list[str]) -> int:
    records = []
    with open(argv[1], encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            hit = LINE_RE.match(raw.rstrip("\n"))
            if not hit:
                continue
            for kind, tag_re, msg_re in RULES:
                tag_hit = tag_re.match(hit.group("tag"))
                found = msg_re.search(hit.group("msg")) if tag_hit else None
                if found:
                    records.append(
                        {
                            "time": hit.group("time"),
                            "slot": int(tag_hit.group(1)),
                            "tag": hit.group("tag"),
                            "kind": kind,
                            "line": hit.group("msg"),
                            "detail": found.groupdict(),
                        }
                    )
    json.dump({"records": records}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
