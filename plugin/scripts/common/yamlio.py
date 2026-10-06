"""YAML 읽기 (이슈 DB 파일 공통).

`date: 2026-09-15`처럼 따옴표 없이 쓴 값을 PyYAML은 `datetime.date`로 읽는다.
스키마는 **직렬화된 형태**(ISO 문자열)를 검사하므로 읽을 때 ISO 문자열로
되돌린다. 파서 규칙·유형·Jira·피드백 등 이슈 DB YAML은 모두 이 함수로 읽는다.

런타임의 YAML 읽기는 `safe_load` 한 곳을 거친다. libyaml이 있으면 C 로더
(`CSafeLoader`), 없으면 순수 파이썬 `SafeLoader`를 쓴다(결과는 같다).
- 오류 문구는 다르다(줄·열은 같다).
- libyaml은 `a:\tb`처럼 탭 구분을 받아들인다.
쓰기(dump)는 `SafeDumper`를 그대로 쓴다: `yamldoc`의 들여쓰기 재정의가 C 방출기에는 적용되지 않는다.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import yaml


LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def safe_load(stream):
    """`yaml.safe_load`와 같되 C 로더를 쓴다. 날짜 변환은 하지 않는다(`loads`/`load`가 한다)."""
    return yaml.load(stream, Loader=LOADER)


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def loads(text: str):
    return normalize(safe_load(text))


def load(path: str | Path):
    with Path(path).open(encoding="utf-8") as fh:
        return normalize(safe_load(fh))
