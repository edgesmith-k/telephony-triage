"""예시 마이그레이션 v1 → v2: Jira 파일에 선택 필드 `tags`(문자열 목록)를 더한다 (06-collaboration.md §6.4).

실제 스키마 변경이 아니라 마이그레이션 계약(`db_migrate.py` docstring)을 보여주고 시험하는 예시다.
테스트 fixture다. 배포 플러그인에는 없고, `tests/helpers/runner.py:versioned_root(schema≥2)`가 임시 플러그인 루트의
`scripts/migrations/`로 복사한다(실제 첫 마이그레이션과 `FROM_VERSION`이 겹치지 않게).

`tags`는 선택 필드라 `db_add`(Jira 파일을 만드는 쪽)는 바뀌지 않고, 작업 계획의 op 형식도 그대로다.
그래서 `upgrade_plan()`은 계획을 그대로 돌려준다 (`schema_version`은 db_migrate가 올린다).
op 형식이 바뀌는 마이그레이션은 여기서 계획의 op를 새 형식으로 바꾼다.
"""

FROM_VERSION = 1
TO_VERSION = 2
DESCRIPTION = "Jira 스키마에 선택 필드 tags 추가, 기존 Jira 파일에 tags: [] 채움"

_SCHEMA = "schema/jira.schema.json"
_ANCHOR = '    "carrier": {"type": "string", "minLength": 1},\n'
_TAGS = '    "tags": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": true},\n'


def migrate(tree):
    schema = tree.read(_SCHEMA)
    if schema is None:
        raise RuntimeError(f"{_SCHEMA}가 없습니다.")
    if '"tags"' not in schema:
        if _ANCHOR not in schema:
            raise RuntimeError(f"{_SCHEMA}에서 carrier 항목을 찾지 못했습니다.")
        tree.write(_SCHEMA, schema.replace(_ANCHOR, _ANCHOR + _TAGS, 1))
    for rel in tree.glob("*/*/jira/*.yaml"):
        text = tree.read(rel)
        if any(line.startswith("tags:") for line in text.splitlines()):
            continue
        tree.write(rel, (text if text.endswith("\n") else text + "\n") + "tags: []\n")


def upgrade_plan(plan):
    return plan
