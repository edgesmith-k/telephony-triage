"""YAML 읽기 (이슈 DB 파일 공통).

`date: 2026-09-15`처럼 따옴표 없이 쓴 값을 PyYAML은 `datetime.date`로 읽는다.
스키마는 **직렬화된 형태**(ISO 문자열)를 검사하므로 읽을 때 ISO 문자열로
되돌린다. 파서 규칙·유형·Jira·피드백 등 이슈 DB YAML은 모두 이 함수로 읽는다.

런타임의 YAML 읽기는 `safe_load` 한 곳을 거친다. libyaml이 있으면 C 로더
(`CSafeLoader`), 없으면 순수 파이썬 `SafeLoader`를 쓴다(결과는 같다).
- 오류 문구는 다르다(줄·열은 같다).
- libyaml은 `a:\tb`처럼 탭 구분을 받아들인다.
쓰기(dump)는 `SafeDumper`를 그대로 쓴다: `yamldoc`의 들여쓰기 재정의가 C 방출기에는 적용되지 않는다.
`load`(파일)는 문법 오류를 `YamlFileError`(경로·줄 포함, `yaml.YAMLError` 하위)로 올린다.
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


def _db_relative(path: Path) -> str:
    """이슈 DB 루트(`issue-db.config.yaml`이 있는 가장 가까운 상위)가 보이면 그 기준 상대 경로, 아니면 그대로."""
    for parent in path.parents:
        if (parent / "issue-db.config.yaml").is_file():
            return path.relative_to(parent).as_posix()
    return str(path)


class YamlFileError(yaml.YAMLError):
    """파일의 YAML 문법 오류. 기존 `except yaml.YAMLError`도 그대로 잡는다."""

    def __init__(self, path, line, problem):
        self.path, self.line, self.problem = Path(path), line, problem
        super().__init__(f"{_db_relative(self.path)}{f':{line}' if line else ''}: YAML 문법 오류: {problem}")


def load(path: str | Path):
    with Path(path).open(encoding="utf-8") as fh:
        try:
            return normalize(safe_load(fh))
        except UnicodeDecodeError as exc:
            raise YamlFileError(path, None, "UTF-8이 아니다 — UTF-8로 다시 저장한다") from exc
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            raise YamlFileError(path, mark.line + 1 if mark else None,
                                getattr(exc, "problem", None) or str(exc)) from exc
