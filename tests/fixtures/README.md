# 테스트 fixture

| 경로 | 내용 |
|---|---|
| `issue-db-sample/` | **합성 샘플 이슈 DB** (Phase 1). 테스트는 `tests/helpers/make_repo.py`로 이 트리에서 임시 git 레포와 bare 원격을 만들어 쓴다 |
| `plans/` | 샘플 작업 계획 (`contracts.md §작업 계획`). `schema/plan.schema.json` 검사에 쓴다. 실제 계획은 `<work_dir>`에만 있고 커밋하지 않는다 |
| `issue-db-lint-errors/` | 린터가 잡아야 할 오류를 일부러 넣은 변형 (Phase 5). 목록은 `tests/test_db_lint.py`의 `EXPECTED` |
| `issue-db-empty-category/` | sms·ims 유형을 뺀 변형. README의 0건 카테고리 표시 (Phase 5) |
| `issue-db-pending/` | `signatures_pending` 원인 DATA-001-03과 그 양성 fixture. 회귀 기대값 `DATA-001:unresolved` (Phase 5) |
| `logs/` | **파서 fixture** (Phase 2). `<name>.log`는 `tests/mocks/log_fixtures.yaml`의 시나리오에서 `tests/helpers/make_log_fixtures.py`가 만들고(`--check`로 검사), `<name>.events.json`은 `parse --full --tz Asia/Seoul --year 2026` 결과 스냅샷이다(`python3 tests/test_parse_logcat.py --update`로 갱신). 이슈 DB 안의 fixture와 섞지 않는다 |

- 변형 트리(오류 주입, 0건 카테고리, 리뷰 케이스 등)는 `issue-db-*`로 따로 두고 샘플 트리를 오염시키지 않는다 (`11-phases.md`).
  Phase 5의 변형 3개는 `tests/helpers/make_variant_dbs.py`가 샘플에서 결정적으로 만든다(`--check`로 검사). 샘플을 바꾸면 다시 만든다.
- `issue-db-sample/`은 **운영 이슈 DB와 같은 모양**이다. 그래서 개발 안내를 그 안에 두지 않는다. 생성 파일(`README.md`, 카테고리 `README.md`, `STATS.md`, `parser-rules/CHANGELOG.md`)은 `db_build.py`(Phase 5)가 만들기 전까지 **없는 것이 정상**이다(`tests/test_sample_db.py`가 검사한다).

## 합성 샘플 이슈 DB (`issue-db-sample/`)

- 카테고리 6개에 유형 1개씩, 원인 7개(DATA-001만 2개), Jira 기록 9건, 피드백 3건.
- fixture는 모두 **합성**이다(`origin: synthetic`). `tests/mocks/scenarios/`의 시나리오에서
  `tests/helpers/make_sample_fixtures.py`가 만들고, **마스킹 함수를 거친 뒤** 쓴다(Phase 4). 목록은 `tests/mocks/sample_fixtures.yaml`.
  - 다시 만들기: `python3 tests/helpers/make_sample_fixtures.py`
  - 커밋된 내용과 시나리오가 맞는지: `python3 tests/helpers/make_sample_fixtures.py --check`
- 사내 값(Jira 키 형식, GHE org/팀, 빌드명, 로그 문구)은 모의 값이고 `TODO(SITE:...)`로 표시돼 있다.
  목록은 `python3 tools/list_site_todos.py`로 뽑는다.
- `.githooks/pre-commit`·`pre-push`는 경고만 내는 **스텁**이다. Phase 8에서 실제 hook으로 바꾼다.

운영·반입용 뼈대(유형·Jira·fixture·피드백 없음)는 이 트리에서 `tools/make_db_skeleton.py`가 만든다.
