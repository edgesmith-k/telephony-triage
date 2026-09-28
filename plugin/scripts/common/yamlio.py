"""YAML 읽기 (이슈 DB 파일 공통).

`date: 2026-09-15`처럼 따옴표 없이 쓴 값을 PyYAML은 `datetime.date`로 읽는다.
스키마는 **직렬화된 형태**(ISO 문자열)를 검사하므로 읽을 때 ISO 문자열로
되돌린다. 파서 규칙·유형·Jira·피드백 등 이슈 DB YAML은 모두 이 함수로 읽는다.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import yaml


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def loads(text: str):
    return normalize(yaml.safe_load(text))


def load(path: str | Path):
    with Path(path).open(encoding="utf-8") as fh:
        return normalize(yaml.safe_load(fh))
