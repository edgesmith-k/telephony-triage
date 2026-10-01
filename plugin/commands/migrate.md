---
description: 이슈 DB 스키마 마이그레이션 (메인테이너용) — migrate/schema-v<N> 브랜치의 워킹 트리를 직접 올린다
argument-hint: --to <N> [--dry-run]
---

이슈 DB 스키마를 v<N>으로 올린다 (`06-collaboration.md §6.4`, `09-commands.md` migrate).
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).

이 커맨드는 **메인테이너가 자기 로컬 브랜치에서 직접 편집**하는 흐름이다. 작업 계획, worktree, 세션 lock, 읽기 스냅샷을
쓰지 않고 PR 도구(`db_pr`)도 부르지 않는다. 다른 사용자의 clone이나 main은 건드리지 않는다.

인자: `$ARGUMENTS` (`--to <N>` 필수, `--dry-run` 선택)

1. **위치 확인** — cwd가 이슈 DB clone(또는 그 worktree)의 최상위여야 한다. 아니면 `--db <경로>`를 묻는다.
2. **미리보기** — 먼저 `db_migrate.py --to <N> --dry-run`을 실행해 거칠 마이그레이션(`steps`)과 바뀔 파일(`changed`)을
   보여준다. `--dry-run`을 받았으면 여기서 끝낸다. 종료 코드 2면 `error`를 그대로 보여주고 멈춘다
   (플러그인이 v<N>을 지원하지 않음, 마이그레이션 없음, 이미 그 버전 등).
3. **브랜치 준비** — 현재 브랜치가 `migrate/schema-v<N>`이 아니면 사용자에게 알리고, 동의하면 최신 main에서
   `git switch -c migrate/schema-v<N> origin/<base>`를 실행한다(워킹 트리가 깨끗해야 한다). 동의하지 않으면 멈춘다.
   다른 브랜치 이름에서는 `--to`가 종료 코드 2로 거절한다. 우회하지 않는다.
4. **사용자 확인 후 실행** — `db_migrate.py --to <N>`. 결과의 `changed`, `generator_version`(자동으로 맞춘 경우)을 보여준다.
5. **생성 파일 재생성** — `db_build.py --write --db <DB>`. README·STATS·CHANGELOG는 직접 편집하지 않는다.
6. **검증** — `validate` 커맨드(인자 없음)를 실행하고 결과표를 보여준다. 실패하면 원인을 보고하고 멈춘다.
   `config.py check --db <DB> --for write`도 함께 돌려 이 브랜치에서 버전 불일치로 막히지 않는지 확인한다.
7. **커밋·push 안내** — 변경 파일을 보여주고 **사용자 승인 후** 커밋한다(메시지 예: `schema: v<옛>→v<N> migrate`).
   push와 PR은 `git push -u origin HEAD`와 사내 PR 절차를 **안내만** 한다. 승인 없이 push하지 않는다.
   PR이 머지되면 다른 사용자는 `sync`로 새 스키마를 받고, 옛 스키마의 열린 작업 계획은 `sync-pr`가
   `db_migrate.py upgrade-plan`으로 올린다 (`upgrade_plan()`이 없는 마이그레이션이면 계획을 다시 만든다).
