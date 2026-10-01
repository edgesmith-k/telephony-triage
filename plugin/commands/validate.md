---
description: 이슈 DB 변경 검증 — 인자 없으면 lint·마스킹·전체 회귀·R1~R5(읽기 전용), --cause면 해결책 검증 후 PR
argument-hint: "[--cause <원인 ID> <적용 후 logcat...>] [--extra <logcat...>]"
---

`$ARGUMENTS`로 두 가지 형태를 구분한다 (`07-workflow.md §validate`, `09-commands.md` validate).
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).

## `--cause`가 있으면: 해결책 검증

먼저 `${CLAUDE_PLUGIN_ROOT}/skills/telephony-triage/reference/verify.md`를 읽고, 그 `validate --cause` 흐름(원본 `07-workflow.md §validate`)을 다음 인자로 실행한다: $ARGUMENTS
작업 키 `verify-res-<원인 ID>-<YYYYMMDD>`로 세션 lock을 잡고 끝나는 모든 경로에서 푼다. 판정이 passed일 때만
`verify-res/<원인 ID>-<YYYYMMDD>` PR을 만든다(공통 쓰기 절차, push 전 확인 화면 승인).

## 인자가 없거나 `--extra`만 있으면: 변경분 검증 (직접 편집 기여자가 push 전에 실행)

**아무것도 바꾸거나 push하지 않는다.** 세션 lock도 잡지 않는다. 각 단계는 실패해도 멈추지 않고 끝까지 돌려서 결과표로 보여준다.

1. **대상 정하기** — cwd가 이슈 DB 레포(또는 worktree) 안이면 그 트리, 아니면 사용자 config의 `issue_db.path` clone이다.
   선택한 절대 경로를 `<db>`로 고정하고 모든 Git 호출과 검사에 같은 경로를 쓴다.
   대상 경로, 현재 브랜치, base 브랜치(사용자 config의 `issue_db.base_branch`, 없으면 `main`)를 알린다.
2. **최신화** — `git -C <db> fetch origin`. 경로는 shell에 맞게 인용한다. `--changed`는 `origin/<base>`와의 **merge-base** 기준이라 뒤처진 브랜치의 변경만 검사한다.
   브랜치가 `origin/<base>`보다 뒤처졌으면 "머지 전 `sync-pr`(계획이 있는 PR) 또는 수동 재동기화가 필요하다"고 알린다.
3. **검사 실행** (`<ref>` = `origin/<base>`):
   - `db_lint.py --changed <ref> --db <db>`
   - `mask_pii.py --check --changed <ref> --db <db>`
   - `db_regress.py --all --db <db>`
   - `db_verify.py rules --changed <ref> --db <db>` (R1~R5. `--extra <logcat...>`을 받았으면 그대로 넘겨 **R6**까지)
   - `db_build.py --verify --db <db>` (생성 파일이 최신인지)
4. **결과표** — 검사별로 `통과 / 실패 / 승인 필요 / 건너뜀(사유)`를 표로 보여준다. 종료 코드 1은 실패, 3은 승인 필요다.
   - `skipped`는 **통과로 표시하지 않는다**. `fixture 없음`·`음성 fixture 없음`은 "검증 못 함 — 리뷰 대상"으로 밝힌다.
   - R6 `fail`은 진행을 막지 않는다(`blocking: false`)고 밝히고, 사용자가 진행 여부를 고른다.
   - `db_build.py --verify --db <db>`가 실패하면 "`db_build.py --write --db <db>`로 생성 파일을 다시 만든 뒤 커밋"을 안내한다(직접 편집 금지).
5. **승인 필요 항목** — `needs-approval`(예: R5 기존 이벤트 변경)이 있으면 PR 본문에 붙일 영향 표(대상 fixture, 바뀐 이벤트, 이유)를
   만들어 준다. 메인테이너 승인이 리뷰 조건이라고 알린다.
6. **다음 단계** — 실패가 없으면 커밋 → `git push --force-with-lease`(필요 시) 안내로 끝낸다. push는 하지 않는다.
   이슈 DB의 `CONTRIBUTING.md`가 push 전에 이 커맨드를 실행하도록 안내한다는 점을 상기시킨다.
