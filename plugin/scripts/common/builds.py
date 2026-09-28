"""빌드 비교 (03-issue-db.md §5.9, `issue-db.config.yaml`의 `build_compare`).

규칙 `{branch_regex, version_regex}`: 두 빌드가 **같은 규칙의** `branch_regex`에
맞고, 그 규칙의 `version_regex` 이름 있는 그룹(정의 순서)을 차례로 비교한다.
숫자로만 된 그룹은 정수로 비교한다. 같은 규칙에 함께 맞지 않거나 파싱할 수 없으면
비교하지 않는다(`None` = 판단 불가).

`branch_regex`가 브랜치를 가르므로 브랜치 이름이 다르면(예: `..._U1_`과 `..._U2_`가
같은 규칙이라도) 같은 브랜치로 보지 않는다: 두 빌드에서 `branch_regex`가 맞은
부분(브랜치 접두어)이 같아야 비교한다.
"""

from __future__ import annotations

import re


def _key(build: str, rule: dict):
    branch = re.match(rule["branch_regex"], build)
    if not branch:
        return None
    version = re.match(rule["version_regex"], build)
    if not version:
        return None
    names = sorted(version.re.groupindex, key=version.re.groupindex.get)
    parts = []
    for name in names:
        value = version.group(name)
        if value is None:
            return None
        parts.append((0, int(value)) if value.isdigit() else (1, value))
    return branch.group(0), tuple(parts)


def compare(a: str | None, b: str | None, rules: list[dict] | None) -> int | None:
    """a < b → -1, a == b → 0, a > b → 1, 판단 불가 → None."""
    if not a or not b:
        return None
    for rule in rules or []:
        ka, kb = _key(a, rule), _key(b, rule)
        if ka is None or kb is None:
            continue
        if ka[0] != kb[0]:
            return None  # 같은 규칙이지만 브랜치가 다르다
        return (ka[1] > kb[1]) - (ka[1] < kb[1])
    return None
