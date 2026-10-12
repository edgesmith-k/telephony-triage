# 트래커 범용화 인계 (2026-10-12, 완료 — 기록용)

> 10/12 완료. 설계 결과는 `docs/design/18-trackers.md`. 일회성 비교 도구 `rename_compare.py`는 지웠다(절대 경로·scratchpad 기준).

Jira 외 이슈 시스템(GitHub Issues 등)도 설정으로 쓸 수 있게 하는 작업. 사용자 요청(10/11), 추천안 승인.
새 세션은 이 파일 → `request.md`(요구·결정) → `implementation-notes.md`(묶음 1·2 실제 구현) → `design.md`(설계서 전문) 순으로 읽는다.

## 결정
- 이름: 설정 키 `tracker`, 이슈 DB 기록 폴더 `issues/`, `issue.schema.json`, 버전 필드 `platform_version(s)`.
- **스키마 v1 유지(원칙 (d))**: 버전 올림·마이그레이션 없음. 이슈 DB는 main 밖으로 나간 적 없음(사용자 확인). 옛 형식 읽기 코드 없음, 옛 키는 감지해서 fail-closed(`config.py rename-legacy`로 사용자 config 변환).
- 사람용 "Jira" 문구·스크립트 파일 이름(`jira_bridge.py` 등)·모의 Jira는 그대로(설계 §1-G).

## 진행 상태
| 묶음 | 내용 | 상태 |
|---|---|---|
| 1 | 형식 이름 변경(설계 §1·§2) + 리뷰 반영 | 완료 `7926dc8`·`49cb249` |
| 2 | `trackers/` 레지스트리·Jira 어댑터·`tracker-mismatch`·guard 규칙 2 일반화 + 리뷰 반영 | 완료 `c30a6c6`·`50124da` |
| 3 | GitHub 어댑터·모의 GitHub Issues MCP·변형 DB `issue-db-github`·eval 66·67·승인 기록 `kind`·driver 정규화 키 | **코드 작성 중 중단(WIP 커밋)** |

묶음 3 WIP 커밋 시점 확인 결과: `test_trackers`·`test_issue_post`·`test_hooks`·`test_db_lint`·`test_db_build`·`test_config_setup`·`test_mocks`·`test_platform_guard`·`test_skill_evals` 439 통과, `test_triage`·`test_jira_fields`·`test_reference_cli` 97 통과, check_boundary·gen_contracts·sync_schemas·make_variant_dbs --check 통과. **리뷰·jira 동작 불변 비교·전체 테스트는 아직 안 함.** 구현 에이전트가 보고 없이 중단돼 설계 §6-2 테스트·§6-3 eval 정의가 다 들어갔는지 확인되지 않았다.

## 다음 세션 할 일 (순서)
1. 묶음 3 남은 범위 점검: `design.md` §7 묶음 3 표와 §6-2·§6-3을 실제 diff(`git diff 50124da`)와 대조해 빠진 것 채우기 — 특히 P2-5(`post.approved.json`에 `kind`, guard가 대조), P2-9(driver가 check-key 정규화 키로 작업 디렉토리), github `key_from_read`, eval 66·67, `skill_eval_env` `tracker: github`·`gh_issues`, `make_db_skeleton --tracker`.
2. jira 동작 불변 비교: `rename_compare.py`(이 폴더, 원래 scratchpad 경로 기준으로 작성됨 — 경로 수정 필요)를 기준 `50124da` worktree와 정규화 없이(`--b2` 모드) 돌린다. 허용 차이는 승인 기록 `kind` 추가뿐.
3. 묶음 3 리뷰(보안: GitHub 작업 키 경로 안전·왕복 검사, 승인 대조, guard 규칙 2/11 순서) → 반영.
4. 문서: 새 `docs/design/18-trackers.md`(설계 §8 목차), 설계 문서·GUIDE·README·스킬·커맨드의 옛 이름, `14-site.md` S30~S32 행, DRAFT_NOTES 결정 (n).
5. HTML: `html-impacts.md`(이 폴더)의 항목을 안내서·`docs/materials/*.html`에 반영.
6. eval(Sonnet): 66·67 + 영향 eval 8·14·39·47·61·63.
7. 전체 pytest(약 25분) → DRAFT_NOTES 진행 상태 → PR → CI → main, 안내서 공유본 재게시(사용자 확인 후).
8. 끝나면 이 폴더를 지우거나 `docs/history/`로 옮긴다.

## 작업 규칙(지난 세션 관례)
- 묶음마다 설계 → 구현 → 리뷰 → 수정 → 테스트, 커밋은 메인만. 관련 테스트만 돌리고 전체는 마지막 한 번.
- Python은 고정 의존성 venv(`pip install '.[test]'`).
- 사내 정보 금지(사내 고유 구성요소·서버 이름 등). 모의 값은 `mock-org`, `ghe.mock.invalid`만.
