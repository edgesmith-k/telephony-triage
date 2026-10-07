"""플러그인이 지원하는 이슈 DB 버전 (02-config.md §5.3, 06-collaboration.md §6.4).

- `GENERATOR_VERSION`: 생성 파일(README, STATS, CHANGELOG) 형식. 이슈 DB
  `issue-db.config.yaml`의 `generator_version`과 같아야 `db_build.py --write`를 할 수 있다.
  생성 결과가 바뀌는 플러그인 변경은 항상 이 값을 올린다.
- `SCHEMA_VERSION`: 이 플러그인이 읽고 쓰는 이슈 DB 스키마 버전 (`schema_version`).
"""

GENERATOR_VERSION = 1
SCHEMA_VERSION = 1
