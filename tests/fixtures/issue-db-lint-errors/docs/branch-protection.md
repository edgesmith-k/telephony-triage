# 브랜치 보호 설정 기록

> 메인테이너가 GHE에서 설정하고 **여기에 기록한다** (`06-collaboration.md §6.1`).
> 아래 값은 사외 초안의 모의 기록이다 — TODO(SITE:S5). 사내에서 실제 설정 후 갱신한다.

## 왜 서버 측 강제가 전제인가

플러그인의 Claude hook과 이 레포의 git hook(`pre-commit`, `pre-push`)은 **모두 로컬 장치**라 우회할 수 있다(명령 파싱은 최선 노력이고, `core.hooksPath`는 바꿀 수 있다).

그리고 `core.hooksPath=.githooks`는 main에 커밋된 스크립트를 **모든 기여자 PC에서 실행**한다. 그래서 브랜치 보호와 CODEOWNERS 필수 리뷰가 서버에서 강제되지 않으면 **main 쓰기 권한이 곧 팀 전체 PC의 코드 실행 권한**이 된다.

브랜치 보호를 설정할 수 없는 GHE 환경이면 `.githooks/` 채택 여부를 다시 결정한다.

## main 브랜치 보호 (설정할 것)

| 항목 | 값 | 설정일 | 확인자 |
|---|---|---|---|
| PR 필수 (직접 push 금지) | 켬 | TODO(SITE) | TODO(SITE) |
| CODEOWNERS 승인 필수 | 1명 이상 | TODO(SITE) | TODO(SITE) |
| force push 금지 | 켬 | TODO(SITE) | TODO(SITE) |
| 브랜치 삭제 금지 | 켬 | TODO(SITE) | TODO(SITE) |
| 관리자에게도 적용 | 켬 | TODO(SITE) | TODO(SITE) |

- Actions를 쓰게 되면 필수 상태 체크를 추가한다 (`13-actions.md`).

## 로컬 hook (보조 장치)

| hook | 하는 일 |
|---|---|
| `.githooks/pre-commit` | `db_precommit.py` 호출: lint, 마스킹 검사, 변경분 회귀, 규칙 변경 시 검증, 생성 파일 정합성 |
| `.githooks/pre-push` | (a) 대상 ref가 `refs/heads/main`이면 거부, (b) `TT_PUBLISH_TOKEN`이 작업 상태 파일의 `approved_hash`(또는 직접 편집 기여자의 `manual`)와 다르면 거부 |

- 설치는 `setup` 커맨드가 한다: `git config core.hooksPath .githooks`.
- 목적은 **도구 경로 밖의 실수 방지**이지 권한 통제가 아니다.

## 머지 규칙

- 머지는 **한 번에 하나씩** 한다. 여러 PR이 대기 중이면 하나를 머지한 뒤 다음 PR 작성자에게 `sync-pr`를 요청한다.
- 동시 기여자가 많아져 이 단계가 병목이 되면 Actions 전환을 검토한다.
