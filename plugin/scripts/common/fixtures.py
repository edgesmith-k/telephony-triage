"""fixture 이름과 기대값 (contracts.md §fixture).

파일 종류는 파일명 **전체**를 정규식과 fullmatch해서 판별한다. 맞지 않는 이름은
`db_lint` 오류다. 경로는 유형 디렉토리 기준 상대 경로(`fixtures/<이름>`)로 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import yamlio

TYPE_ID = r"[A-Z][A-Z0-9]*-\d{3}"
CAUSE_ID = TYPE_ID + r"-\d{2}"
BUILD = r"[A-Za-z0-9_+-][A-Za-z0-9._+-]*"
N1 = r"[1-9]\d*"
N2 = r"(?:[2-9]|[1-9]\d+)"

TYPE_ID_RE = re.compile(TYPE_ID)
CAUSE_ID_RE = re.compile(CAUSE_ID)

# 판별 순서가 중요하다: 구체적인 종류를 먼저 보고 양성은 마지막에 본다.
KINDS: list[tuple[str, re.Pattern]] = [
    ("fixed", re.compile(rf"(?P<cause>{CAUSE_ID})\.fixed\.(?P<build>{BUILD})")),
    ("recurrence", re.compile(rf"(?P<cause>{CAUSE_ID})\.recurrence\.(?P<build>{BUILD})")),
    ("resolved", re.compile(rf"(?P<cause>{CAUSE_ID})\.resolved\.(?P<n>{N1})")),
    ("extra", re.compile(rf"(?P<cause>{CAUSE_ID})\.extra\.(?P<n>{N1})")),
    ("negative", re.compile(rf"(?P<type>{TYPE_ID})\.none(?:\.(?P<n>{N2}))?")),
    ("positive", re.compile(rf"(?P<cause>{CAUSE_ID})(?:\.(?P<n>{N2}))?")),
]
SUFFIXES = (".log", ".expect.yaml")


@dataclass
class FixtureName:
    name: str           # 파일 이름
    stem: str           # .log / .expect.yaml을 뗀 부분
    kind: str
    cause: str | None
    type_id: str
    build: str | None = None
    n: int | None = None
    suffix: str = ".log"


def parse_name(name: str) -> FixtureName | None:
    """파일 이름 → FixtureName. 규칙 밖이면 None."""
    for suffix in SUFFIXES:
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    else:
        return None
    for kind, regex in KINDS:
        hit = regex.fullmatch(stem)
        if not hit:
            continue
        groups = hit.groupdict()
        cause = groups.get("cause")
        type_id = groups.get("type") or cause.rsplit("-", 1)[0]
        n = groups.get("n")
        return FixtureName(name=name, stem=stem, kind=kind, cause=cause, type_id=type_id,
                           build=groups.get("build"), n=int(n) if n else None, suffix=suffix)
    return None


@dataclass
class Expectation:
    expect_top: str | None = None        # 원인 ID | "<유형 ID>:unresolved" | "none"
    expect_not: str | None = None
    also_allowed: list[str] = field(default_factory=list)
    occurred_at: str | None = None
    origin: str | None = None
    source: str = "default"              # default | expect.yaml

    def describe(self) -> str:
        parts = []
        if self.expect_top:
            parts.append(f"expect_top: {self.expect_top}")
        if self.expect_not:
            parts.append(f"expect_not: {self.expect_not}")
        if self.also_allowed:
            parts.append(f"also_allowed: {self.also_allowed}")
        return ", ".join(parts)


def default_expectation(fx: FixtureName, pending_causes: set[str] = frozenset()) -> Expectation:
    if fx.kind in ("positive", "recurrence", "extra"):
        if fx.cause in pending_causes:
            return Expectation(expect_top=f"{fx.type_id}:unresolved")
        return Expectation(expect_top=fx.cause)
    if fx.kind in ("fixed", "resolved"):
        return Expectation(expect_not=fx.cause)
    return Expectation(expect_top="none")


def load_expectation(log_path: Path, fx: FixtureName, pending_causes: set[str] = frozenset()) -> Expectation:
    """`.expect.yaml`이 있으면 그 값으로 기본 기대값을 바꾼다."""
    exp = default_expectation(fx, pending_causes)
    path = log_path.with_name(fx.stem + ".expect.yaml")
    if not path.is_file():
        return exp
    data = yamlio.load(path) or {}
    if "expect_top" in data or "expect_not" in data:
        exp.expect_top = data.get("expect_top")
        exp.expect_not = data.get("expect_not")
        if fx.cause in pending_causes and exp.expect_top == fx.cause:
            exp.expect_top = f"{fx.type_id}:unresolved"
    exp.also_allowed = [str(c) for c in data.get("also_allowed") or []]
    exp.occurred_at = data.get("occurred_at")
    exp.origin = data.get("origin")
    exp.source = "expect.yaml"
    return exp
