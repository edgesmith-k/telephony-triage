# 기여 방법

> 이 문서는 이슈 DB 레포의 규칙이다. 설계 원본은 플러그인 레포의
> `03-issue-db.md §5.7`, `06-collaboration.md §6.2·6.3`, `contracts.md`다.

## 0. 두 가지 기여 경로

| 경로 | 언제 | 방법 |
|---|---|---|
| **도구 경로** (권장) | 분석 결과, 수동 기록, 수정 상태·검증 반영 | Claude Code 플러그인 커맨드(`analyze`, `record`, `verify-fix`, `validate --cause`, `fix-submitted`). 도구가 **작업 계획을 최신 main 위에 적용**해서 브랜치와 PR을 만든다 |
| **직접 편집** | 월간 리뷰 정리, 유형 이동·병합, 스키마 마이그레이션, 새 카테고리, 사후 정리 | 자기 로컬 브랜치에서 편집 → `db_build --write` → `/telephony-triage:validate` → push |

- **main에 직접 push하지 않는다.** 모든 변경은 PR + CODEOWNERS 승인 1명 이상이다.
- PR 하나에는 Jira 하나(또는 리뷰 정리 한 묶음)만 넣는다. 예외: pending 피드백 파일은 analyze PR에 함께 올릴 수 있다.
- PR 제목은 `[<원인 ID 또는 유형 ID>] <요약>`이다.

## 1. 무엇을 추가할지 판단

| 상황 | 추가 대상 | 계획 op |
|---|---|---|
| 증상도 원인도 기존과 같음 | Jira 기록만 추가 | `append` |
| 증상은 같고 원인이 다름 | 기존 유형에 **새 원인** | `new-cause` |
| 증상 자체가 기존에 없음 | **새 유형** + 첫 원인 | `new-type` |
| 증상은 맞지만 원인 미확정 | `cause: unresolved`인 Jira 기록 | `unresolved` |
| 이미 있는 Jira를 다른 원인으로 | Jira 파일 이동 | `reclassify` |

- 새 유형을 만들기 전에 **전체 카테고리**에서 제목 유사도, 용어집 표준어, 증상 시그니처 중복을 확인한다. 비슷한 증상이 있으면 새 원인으로 넣는다.
- 카테고리가 애매하면 `GLOSSARY.md`의 카테고리 경계 표를 따르고, 나머지는 `secondary_categories`와 `related`로 연결한다.
- **원인이 확정되지 않았으면 원인을 만들지 않는다.** 추정만으로 원인을 만들지 말고 `unresolved`로 기록한다.

## 2. 작성 규칙

| 항목 | 규칙 | 좋은 예 | 나쁜 예 |
|---|---|---|---|
| 유형 `title` | **증상**, "~하지 않음 / ~됨" 형태, 30자 이내, GLOSSARY 표준어 | SETUP_DATA_CALL이 발생하지 않음 | DataNetworkController 버그 |
| 유형 `summary` | 증상 한 문장 | 데이터 연결이 필요한 상황인데 RIL로 SETUP_DATA_CALL 요청이 나가지 않는다 | (비워둠) |
| 원인 `title` | **원인** 명사구, 20자 이내 | Roaming disabled / IMS 미등록 | 설정 문제인 듯 |
| 원인 `description` | 왜 그 증상이 나는지 한 문장 | 로밍 중인데 데이터 로밍 설정이 꺼져 있음 | |
| `resolution` | **행동 지시 1~2문장**, "~한다"로 끝냄. 워크어라운드면 앞에 `[WA]` | 데이터 로밍 설정을 켠다 | 확인 필요 |
| `resolution_type` | `user-setting`, `carrier-config`, `framework-bug`, `vendor-ril`, `modem`, `network`, `hw` 중 하나 | | etc |
| `fix.status` | `fix-submitted`면 `ref`와 `fixed_in`(브랜치 필수, 빌드 선택) 필수. `fixed`는 `verify-fix` 통과로만 바꾼다. **새 원인은 `fixed`로 시작할 수 없다** | fix-submitted + CL + 브랜치[:빌드] | 검증 없이 fixed |
| `resolution_verification` | 새 원인과 `resolution`을 바꾼 원인은 `unverified`로 시작한다. `verified`는 evidence(다른 Jira 키 또는 `resolved` fixture) 필수 | `{status: verified, evidence: [ABC-222]}` | 근거 없이 verified |
| `recovery_signatures` | 해결되면 나타나야 하는 정상 동작. 코드·설정 수정 유형에 권장 | | 원인 시그니처의 단순 부정 |
| `scenario_signatures` | 재현 시나리오 수행 흔적. 코드·설정 수정 유형은 `fixed` 전환 전에 `scenario`나 `recovery` 중 하나가 필수 | 데이터 연결 시도 평가 로그 | 원인 시그니처 복사 |
| 시그니처 | 증상용/원인용 분리. 새 유형/원인은 판별 시그니처 필수. **마스킹된 로그 기준**으로 실제 확인한 문구만 쓴다. 원본 식별자(IMSI, 전화번호, 셀 ID) 패턴 금지 | `must_event: data_evaluation_rejected` | `.*error.*` |
| 유형 디렉토리명 | `<유형 ID>-<영문 kebab-case 요약>` | `DATA-001-no-setup-data-call` | `data이슈` |
| 로그 예시 | 마스킹 후 5~15줄, 본문 "원인별 상세"에만 | | frontmatter에 로그 원문 |
| fixture | 원인마다 양성 1개 이상, 판별에 필요한 최소 구간(20~100줄), 마스킹. 이름 규칙은 아래 4장 | `fixtures/DATA-001-02.log` | 전체 logcat |
| `code_refs` | `<root 키>:<상대 경로>` + `symbol`. 절대 경로 금지 | `aosp:frameworks/opt/telephony/.../DataNetworkController.java` | `/home/user/android16/...` |
| 본문 재현 시나리오 | 원인별 상세에 동작 순서와 조건을 적는다. `verify-fix`가 이것을 보여준다 | 로밍 SIM 삽입 → 데이터 로밍 OFF → 데이터 앱 실행 | (비워둠) |

### `signatures_pending` (원인 판별 시그니처 없이 기록하기)

수동 기록(`record`)에서 사용자가 명시할 때만 원인에 `signatures_pending: true`를 붙일 수 있다. 이때만 `signatures`를 비울 수 있다.

- **유형의 증상 시그니처는 예외 없이 필수**다 (없으면 analyze가 그 유형을 찾지 못한다).
- pending 원인은 매처가 **판별할 수 없고**, 해결책은 `unverified`로 고정되며, 월간 리뷰의 "시그니처 없는 원인"에 올라간다.
- 나중에 `update-signature`로 판별 시그니처를 넣으면 지워진다.

### `also_allowed` (다른 유형의 원인이 같이 잡혀도 되는 fixture)

같은 로그에 실제로 두 현상이 있을 때만 쓴다. fixture의 `.expect.yaml`에 적고, 추가는 `allow-cause` op로 한다.

- 대상 원인 자신, **같은 유형의 원인**, 없는 ID는 오류다 (같은 유형 안의 충돌은 시그니처 설계 문제다).
- 다른 카테고리 fixture에 추가하면 그 카테고리 오너가 리뷰어로 들어간다.
- 누적되면(한 fixture에 3개 이상, 한 원인이 5개 이상의 fixture에서 허용) 월간 리뷰가 시그니처 범위를 다시 본다.

## 3. push 전에 하는 것

- 도구 경로: 커맨드가 push 전 확인 화면(변경 파일, ID 할당, README 미리보기, diff, 검사·검증 결과, 커밋 메시지)을 보여준다. **승인 없이는 push하지 않는다.**
- 직접 편집: **`/telephony-triage:validate`를 반드시 실행한다.** 전체 회귀와 R1~R5 검증이 여기서 돈다.
- 플러그인 없이 편집하는 사람은 플러그인 레포를 clone하고 `~/.telephony-triage/config.yaml`의 `plugin.scripts_path`를 그 clone의 `plugin/scripts`로 지정한다. 그래야 git pre-commit hook이 동작한다.
- pre-commit hook을 우회하지 않는다 (`--no-verify`, `-n`, `core.hooksPath` 변경 금지). 우회한 커밋은 사후 lint가 찾아낸다.
- 직접 편집 브랜치의 push는 `TT_PUBLISH_TOKEN=manual`을 붙인다 (`.githooks/pre-push`).

## 4. fixture 이름 규칙

위치는 `<유형 디렉토리>/fixtures/`이고 구분자는 `.`이다.

| 종류 | 파일명 | 기본 기대값 |
|---|---|---|
| 양성 | `<원인 ID>.log`, `<원인 ID>.<n2>.log` | 그 원인 C=1, 다른 원인 C=0 |
| 수정 후 | `<원인 ID>.fixed.<build>.log` | 그 원인 C=0 |
| 해결책 적용 후 | `<원인 ID>.resolved.<n1>.log` | 그 원인 C=0 |
| 재발 | `<원인 ID>.recurrence.<build>.log` | 양성과 같음 |
| 음성 | `<유형 ID>.none.log`, `<유형 ID>.none.<n2>.log` | 이슈 DB 전체에서 S=1인 유형 없음 |
| 추가 표본 | `<원인 ID>.extra.<n1>.log` | 양성과 같음 |

- `resolved`와 `extra`는 첫 파일이 `.1`이고, `positive`·`negative`는 첫 파일에 번호가 없고 둘째부터 `.2`다.
- 기대값을 바꾸려면 같은 이름에서 `.log`를 `.expect.yaml`로 바꾼 파일을 둔다.
- fixture는 **항상 마스킹된 로그**만 넣는다.

## 5. 머지 전에 main이 바뀌었으면

- **도구가 만든 PR**(계획이 있는 PR): 작성자가 `/telephony-triage:sync-pr`를 실행한다. 계획을 최신 main 위에 다시 적용하므로 새 ID와 fixture 번호가 다시 할당될 수 있다. 리뷰어는 작성자에게 요청한다.
- **직접 편집한 브랜치**(계획 없음): 작성자가 직접 재동기화한다.
  1. `git fetch origin` 후 `git rebase origin/main`
  2. 충돌이 생성 파일(README, 카테고리 README, STATS, parser-rules/CHANGELOG)뿐이면 main 쪽을 받고 `db_build --write`로 다시 만든다. 다른 파일 충돌은 직접 해결한다.
  3. 새 ID가 main과 겹치면 `db_add check-ids --base origin/main`으로 확인하고 `db_add renumber <옛 ID>`로 옮긴 뒤 `db_lint --residual <옛 ID>=<새 ID>`로 잔존을 검사한다.
  4. `/telephony-triage:validate` 통과 후 `git push --force-with-lease`

## 6. 하지 않는 것

- 생성 파일(`README.md`, 카테고리 `README.md`, `STATS.md`, `parser-rules/CHANGELOG.md`)을 직접 고치지 않는다. `db_build.py`만 만든다.
- `.cache/`를 커밋하지 않는다.
- ID는 main에 들어간 뒤에는 바꾸지 않는다. 폐기·병합은 삭제가 아니라 `status`로 표시한다.
- 같은 Jira를 두 파일로 만들지 않는다 (Jira 한 건 = 파일 하나).
- 마스킹되지 않은 로그, Jira 요약·설명·코멘트 원문, 사람 이름·고객명을 넣지 않는다.
