#!/usr/bin/env python3
"""어댑터 예시 (16-existing-assets.md §16.3 "대안: 어댑터 방식").

기존 파서를 **포팅하지 않고 그대로 실행**하고 출력만 이벤트 형식으로 바꾸는
방식의 예시다. 사내에서는 `plugin/scripts/adapters/site_*`(SITE_PATHS)에 둔다.
사외에서는 형식을 시험할 수 있게 모의본만 여기에 둔다.

이벤트 이름은 `ext.<category>.<이름>`, 이벤트 `source`는 `external:<adapter>`다.
이 카테고리는 이슈 DB `issue-db.config.yaml`의 `external_parsers`에 고정돼
있어야 시그니처가 `must_event: ext.data.*`로 참조할 수 있다
(`contracts.md §기존 자산 연결 계약`).

`site-defaults.yaml` 쪽 설정 형태:

```yaml
external_parsers:
  data:
    command: ["python3", "${CLAUDE_PLUGIN_ROOT}/scripts/adapters/site_vendor/legacy_parser.py", "{log}"]
    output: json
    adapter: site_data_existing
    version: "0.0.1-mock"
    mode: merge          # merge | replace
    timeout_sec: 120
```

이슈 DB 쪽 고정:

```yaml
external_parsers:
  data: {adapter: site_data_existing, min_version: "0.0.1-mock"}
```

어댑터 계약 (Phase 2에서 인터페이스 파일로 고정한다)
    ADAPTER_NAME: str
    VERSION: str
    convert(raw, meta) -> events[]
"""

from __future__ import annotations

ADAPTER_NAME = "site_data_existing"
VERSION = "0.0.1-mock"

# 기존 파서가 내는 판별 이름 → 이 설계의 이벤트 이름.
# 사내에서는 이 매핑표를 사용자 확인 후에 확정한다 (16-existing-assets.md §16.3).
EVENT_MAP = {
    "DATA_SETUP_BLOCKED": "ext.data.setup_not_allowed",
    "USER_DATA_OFF": "ext.data.user_data_disabled",
}


def convert(raw: dict, meta: dict | None = None) -> list[dict]:
    """기존 파서의 JSON 출력을 이벤트 목록으로 바꾼다.

    입력 예 (모의 기존 파서의 형식):
        {"records": [{"time": "...", "slot": 0, "kind": "USER_DATA_OFF",
                      "line": "...", "detail": {"reason": "USER"}}]}
    """
    events: list[dict] = []
    for record in raw.get("records", []):
        name = EVENT_MAP.get(record.get("kind"))
        if name is None:
            # 매핑표에 없는 판별은 버리지 않고 이름 없는 줄로 남긴다.
            # 사내에서 매핑표를 채울 때 목록으로 보고한다.
            name = None
        slot = record.get("slot")
        events.append(
            {
                "ts": record.get("time"),
                "tag": record.get("tag", "EXT"),
                "msg": record.get("line", ""),
                "event": name,
                "fields": dict(record.get("detail") or {}),
                "phone_id": None if slot is None else int(slot),
                "category_hint": "data",
                "source": f"external:{ADAPTER_NAME}",
            }
        )
    return events


def unmapped_kinds(raw: dict) -> list[str]:
    """매핑표에 없는 판별 이름 목록. 사내 포팅 때 보고용."""
    return sorted(
        {
            str(record.get("kind"))
            for record in raw.get("records", [])
            if record.get("kind") not in EVENT_MAP
        }
    )
