---
description: 월간 리뷰 리포트 (카테고리 오너) — 이슈 DB 품질·해결 상태를 점검한다. 읽기 전용, push 안 함
argument-hint: "[category]"
---

카테고리 오너의 월간 리뷰 리포트를 만든다 (`06-collaboration.md §6.6`, `09-commands.md` review).
스크립트: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py"`(결과 JSON). 종료 코드 2면 메시지를 그대로 보이고 멈춘다(예: 사내 기본값 없음 S-3).

이 커맨드는 **읽기 전용**이다. 세션 lock을 잡지 않고, 읽기 스냅샷을 옮기지 않으며, 이슈 DB를 바꾸거나 push하지 않는다.

인자: `$ARGUMENTS` (카테고리 키, 선택)

1. **카테고리 정하기** — 인자가 있으면 그 카테고리. 없으면 `db_review.py --json`을 먼저 한 번 돌려 `owners`
   (CODEOWNERS의 카테고리별 오너)를 보여주고, 사용자가 오너인 카테고리를 **묻는다**(전체를 볼 수도 있다).
   종료 코드 2(없는 카테고리 등)면 메시지를 보여주고 다시 묻는다.
2. **리포트 만들기** — `db_review.py <category> --out <work_dir>/review-<category>-<YYYY-MM>/report.md`
   (`work_dir`는 `config.py show --keys work_dir`의 값, `<YYYY-MM>`은 오늘). `--db`는 주지 않는다(기본값: cwd의 이슈 DB 또는 config의
   `issue_db.path`). 리포트 머리의 이슈 DB 경로·커밋·브랜치를 보여준다. 브랜치가 base 브랜치(`config.py show --keys issue_db.base_branch`)가
   아니거나 '커밋 안 된 변경 포함'이면, 리포트에 base 브랜치에 병합되지 않은 변경이 들어갔을 수 있다고 알린다. 확정 base 기준이
   필요하면 ① `sync`로 스냅샷을 최신화하고 결과의 `fetched`(true)와 `snapshot_sha`를 확인한 뒤 ② `db_review.py <category> --db <work_dir>/_snapshot …`로
   그 스냅샷을 읽는다(`_snapshot` 지정만으로 최신 main이 보장되지는 않는다; `sync`만으로는 사용자 clone의 브랜치·변경이 정리되지 않는다).
   `--db <work_dir>/_snapshot`이면 detached가 정상이다(`worktree add --detach`): 리포트 `head`가 sync의 `snapshot_sha`와 같고 `fetched`가
   true면 base 기준으로 본다. 입력을 바꾸지는 않는다(읽기 전용).
3. **보여주기** — 요약 표(항목별 건수)와 건수가 있는 항목의 목록·조치를 보여준다. "기간 확인 불가"(git 이력 없음)가
   있으면 그렇다고 밝힌다. 리포트 파일 경로를 알려준다.
4. **정리 방법 안내** — 정리는 `review/<category>-<YYYY-MM>` PR로 올린다 (이슈 DB `docs/review-guide.md`):
   - (a) 직접 편집 → `db_build.py --write` → `validate` → 커밋 → push.
   - (b) 조치를 **작업 계획**(`source: review`, op: `set-status`·`update-signature`·`reclassify`·`set-resolution`·
     `allow-cause`·`add-fixture`)으로 `<work_dir>/review-<category>-<YYYY-MM>/plan.json`에 사용자와 함께 쓰고
     공통 쓰기 절차(`07-workflow.md`, `db_pr stage --then-summary → 승인 → publish --commit --and-discard`)로 올린다. 별도 커맨드는 없다.
   - **중복 후보 병합**은 `move/<옛 ID>-to-<새 ID>` 브랜치와 `source: move` 계획이다. op 순서: `new-cause`(옛 원인 내용
     복사, `temp_id`) → `add-fixture`(`path`에 옛 fixture의 **이슈 DB 기준 경로**, 새 원인 이름으로 복사) →
     `set-status`(옛 원인 `merged-into:<temp_id>`, 유형 병합이면 옛 유형 `merged-into:<유형 ID>`) → `reclassify`(옛 원인의
     Jira 각각, `to: <temp_id>`. 옛 유형의 원인 미확정 Jira는 `from: unresolved`, `to: <흡수하는 유형 ID>:unresolved`). 삭제하지 않는다.
   - 계획 작성·적용은 사용자가 원할 때만 시작한다. 분류·상태 변경은 **항상 사용자 확인 후**, push 전 확인 화면 승인 후에만 한다.
