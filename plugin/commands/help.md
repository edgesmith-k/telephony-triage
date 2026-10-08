---
description: 커맨드 목록과 상황별 추천, 커맨드별 형식·옵션·예시 (읽기 전용, 스크립트·이슈 DB·Jira 안 씀)
argument-hint: "[커맨드]"
---

telephony-triage 커맨드 도움말을 보여준다. 인자: $ARGUMENTS

**읽기 전용이다.** Glob·Grep·Read로 이 플러그인의 파일만 읽는다. Bash와 스크립트를 실행하지 않고, 파일을 쓰지 않으며,
세션 lock을 잡지 않고, 이슈 DB·스냅샷·config·Jira(MCP)에 접근하지 않는다. 사내 기본값이 없어도(S-3 전) 동작한다.
커맨드를 대신 실행하지 않는다. 형식·옵션·동작은 읽은 파일에 있는 것만 말하고, 파일에 없으면 "커맨드 파일에 설명 없음"이라고 한다.

## 인자 없음: 목록과 추천

0. **말로 요청하기** — 먼저 이 두 줄을 그대로 보인다:
   "커맨드 없이 말로 요청해도 됩니다. 로그 분석, 비슷한 이슈 검색, 기록, 수정 CL 반영, 수정 검증, 해결책 검증, PR 재동기화는 스킬 설명 기준으로 알아서 연결됩니다.
   setup, sync, preview, review, migrate, 인자 없는 validate는 커맨드로 실행하세요."
1. **목록** — 커맨드 목록은 이 파일에 적지 않는다. `${CLAUDE_PLUGIN_ROOT}/commands/*.md`의 frontmatter에서 만든다:
   Grep으로 그 디렉토리의 `^(description|argument-hint): ` 줄을 한 번에 읽는다(본문은 읽지 않는다).
   파일 이름 순으로 한 줄에 하나씩 `/telephony-triage:<파일 이름> <argument-hint>` — `<description>`을 보인다
   (`argument-hint`가 없으면 인자 없는 커맨드다. 값은 고쳐 쓰지 않고 그대로 인용하되 바깥 따옴표만 뗀다).
2. **상황별 추천** — 아래 표를 그대로 보인다. 1번 목록에 없는 커맨드의 행은 뺀다.
3. 끝에 "자세한 형식·옵션: `/telephony-triage:help <커맨드>`" 한 줄을 붙인다.

## 상황별 추천

| 상황 | 커맨드 |
|---|---|
| 처음 설치했다, 설정·연결을 점검하고 싶다 | `setup` |
| Jira 키와 로그가 있다, 원인을 찾고 이슈 DB에 기록하고 싶다 | `analyze <JIRA-KEY> <로그 경로>` |
| 기록하지 않고 분석 결과만 보고 싶다 | `analyze <JIRA-KEY> <로그 경로> --analysis-only` |
| 이미 스스로 해결했다, 분석 없이 기록만 남기고 싶다 | `record <JIRA-KEY>` |
| 비슷한 이슈·Jira 번호부터 찾고 싶다 | `search <증상 문장 또는 키워드>` |
| 이슈 DB를 최신으로 받고, 오래된 작업과 내 열린 PR을 보고 싶다 | `sync` |
| 내 PR이 머지 대기 중인데 main이 바뀌었다 | `sync-pr [branch]` |
| 수정 CL이 머지됐다 | `fix-submitted <원인 ID> --ref <CL> --fixed-in <branch>` |
| 수정 빌드에서 재발하지 않는지 확인하고 싶다 | `verify-fix <원인 ID> <수정 빌드 logcat>` |
| 해결책이 효과가 있는지 확인하고 싶다 | `validate --cause <원인 ID> <적용 후 logcat>` |
| 이슈 DB를 직접 편집했다, push 전에 검사하고 싶다 | `validate` |
| 생성 파일(README·STATS·CHANGELOG)이 어떻게 바뀔지 보고 싶다 | `preview` |
| 카테고리 오너로 월간 리뷰를 한다 | `review [category]` |
| 메인테이너로 이슈 DB 스키마를 올린다 | `migrate --to <N>` |

## 인자 있음: 커맨드 하나

1. **이름 정하기** — `$ARGUMENTS`의 첫 단어를 쓴다. 앞의 `/`와 `telephony-triage:`는 떼고 소문자로 바꾼다.
   결과가 `[a-z-]+`에 맞지 않으면(경로 구분자·`.`·공백 등) 파일을 찾지 않고 2번(없는 커맨드)으로 간다.
2. **없는 커맨드** — `${CLAUDE_PLUGIN_ROOT}/commands/<이름>.md`가 없으면 "없는 커맨드: <이름>"이라고 말하고 위 1번 목록을 보인다.
   비슷한 이름을 골라 대신 설명하지 않는다(추측 금지).
3. **커맨드 파일 읽기** — 그 파일을 Read로 읽는다. frontmatter의 `argument-hint`가 형식이고, `description`이 한 줄 설명이다.
4. **가리키는 파일** — 본문이 스킬 본문이나 `reference/` 아래 파일을 "먼저 읽고" 또는 "…의 <커맨드>를 실행"으로 가리키면,
   그 파일에서 이 커맨드의 사용법 줄(`/telephony-triage:<이름>`이 있는 줄이나 코드 블록)과 그 절만 읽는다.
   Grep `-n`으로 줄 번호를 찾고, Read의 `offset`·`limit`(40줄 안팎)로 읽는다. 파일 전체나 다른 커맨드의 절은 읽지 않는다.
   그 파일이 다시 다른 파일을 가리켜도 따라가지 않는다.
5. **보여주기** (짧게):
   - **형식**: `/telephony-triage:<이름> <argument-hint>`. 본문이 형태를 나누면(예: 인자 없음 / 특정 옵션 있음) 형태별로 보인다.
   - **하는 일**: description과 본문의 단계 제목을 2~4줄로 정리한다.
   - **옵션**: argument-hint의 옵션마다 한 줄. 뜻은 3~4번에서 읽은 문장에서만 가져오고, 없으면 "커맨드 파일에 설명 없음"이라고 쓴다.
     다른 옵션이나 다른 모드를 설명하는 문장을 이 옵션의 뜻으로 쓰지 않는다. 예: `mode: analysis-only` 줄 끝의
     "추가 로그는 `--more-logs`"는 분석 전용 모드의 설명이지 `--more-logs`의 뜻이 아니다 → "커맨드 파일에 설명 없음".
   - **예시**: 1~3개. argument-hint 형식에 자리표시자 값(`ABC-12345`, `<로그 경로>`)을 넣어 만든다. argument-hint와 읽은 파일에 없는 옵션은 쓰지 않는다.
   - **주의**: 본문에 있는 읽기 전용 여부, lock, 사용자 확인, push 승인 지점만 한 줄씩 적는다.
