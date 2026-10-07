---
description: 이슈 DB 읽기 스냅샷 최신화 (사후 lint, 오래된 작업 디렉토리 정리 후보)
---

analyze Step 1만 수행한다 (`07-workflow.md §Step 1`, `09-commands.md` sync).
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).

**사용자 clone의 브랜치와 워킹 트리는 바꾸지 않는다.** 1~4번 중 어디서 멈추든 lock을 잡았다면 반드시 푼다(5번은 lock이 필요 없다).

1. **세션 lock** — `db_pr.py lock acquire sync --command sync`. 종료 코드 2면 `holder`(작업 키, 명령, 마지막 갱신)를
   보여주고 그 세션이 끝났는지 묻는다. 끝났으면 `db_pr.py lock release <보유자 작업 키> --force` 후 다시 잡는다.
   작업 키가 `sync`인 lock이 10분 이내에 갱신됐으면 사용자 확인 후 `--take-over`로 이어받는다.
2. **스냅샷** — `db_pr.py snapshot --job sync`. 결과의 `snapshot_sha`, `pulled`, `pull_skipped_reason`(있으면 그대로)을 알린다.
   `base_sha_changed`로 base 변경을 한 줄로 알린다: true면 `base 변경 <previous_sha 앞 7자>→<snapshot_sha 앞 7자>`,
   false면 `변경 없음`, null(첫 실행)이면 말하지 않는다.
   `post_lint`에 ID 중복·Jira 중복이 있으면 보여주고 "메인테이너 정리가 필요하다(도구가 정리 PR을 만들지 않는다)"고 알린다.
   `config.py check --db <work_dir>/_snapshot --for dry-run`으로 버전 호환성도 확인하고 `writable: false`면 `reasons`를 보여준다.
3. **lock 해제** — `db_pr.py lock release sync`.
4. **오래된 작업 디렉토리 후보** — `db_pr.py cleanup --dry-run --older-than` (기본 90일).
   `targets`에서 닫힌·머지된 PR의 오래된 작업 디렉토리와 계획 없이 원문만 남은 중단 작업(`kind: job-dir`, `pr`(없으면 null), `pr_state`)과 남은 worktree·도구 브랜치를
   목록으로 보여준다. `retained`(계획 폴더: 경과 일수·경로·원문 잔류 여부·`state`)는 지우지 않고 `note`를 그대로 알린다 — `unpublished`는 "미게시 계획 보존 — 재개 또는 명시적 폐기 필요", `pushed-no-pr`는 "push 기록 있음, PR 연결 미확인 — 원격 브랜치·열린 PR을 확인한 뒤 publish 재시도(열린 PR이 있으면 그 PR을 고친다) 또는 `sync-pr <브랜치>`로 복구"(PR 생성 실패로 단정하지 않는다. discard는 복구가 아니라 중단·로컬 정리). 목록이 비면 "정리할 것 없음"으로 끝낸다. 있으면 지울지 **묻고**, 사용자가 동의한 경우에만
   `db_pr.py cleanup --yes --older-than`을 실행한다. 확인 전에는 아무것도 지우지 않는다.
   analyze가 알린 잔여물(`notes`의 "잔여 worktree·도구 브랜치 n개")도 이 목록에 있으니 여기서 정리한다.
   (4번은 lock을 잡지 않은 채 실행하므로, 다른 세션이 작업 중이면 그 작업 키의 것은 대상에서 빠진다.)
5. **내 열린 PR** — `db_pr.py my-prs` (읽기 전용, lock 밖). `prs`가 `null`이면 `warnings`를 그대로 보이고 넘어간다.
   PR마다 한 줄로 `#번호 제목 — base 이동 | 이동 없음 | 확인 불가(null)`을 보여준다. `base_moved`는 fetch 없이 로컬 원격 ref
   기준이다(이 sync의 2번 fetch가 방금 갱신했다. `null`은 그 브랜치를 fetch하지 않은 것). `base_moved: true`인 PR에는
   `/telephony-triage:sync-pr <브랜치>`를 **안내만** 하고 실행하지 않는다. 목록이 비면 "열린 PR 없음".
   (sync의 결과와 멈춤 조건은 5번이 바꾸지 않는다: 5번이 실패해도 sync는 끝난 것이다.)

lock 획득·인계 결과의 `lock.owner`를 보관하고 이후 `db_pr`·`db_verify` 호출마다 `TT_LOCK_OWNER`로 전달한다. 현재 lock 파일에서 토큰을 다시 읽어 쓰지 않는다.
