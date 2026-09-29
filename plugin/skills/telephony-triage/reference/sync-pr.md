# sync-pr (머지 전 계획 재적용)

```
/telephony-triage:sync-pr [branch]
```

PR을 올린 뒤 머지 전에 main이 바뀌면, 텍스트 rebase 대신 **원래 작업 계획을 최신 main 위에 다시 적용**한다.
새 ID·fixture 번호는 그때의 main 기준으로 다시 할당되고, 계획이 건드리는 대상이 main에서 바뀌었으면(drift) 사용자가 고른다.
계획은 작성자 PC에만 있으므로 sync-pr는 작성자가 실행한다. 커맨드 파일(`commands/sync-pr.md`)에 같은 절차가 자기완결로 있다.

1. **브랜치 선택**: 인자가 없으면 `WD/*/plan.json` 중 `pr.number`가 있고 `gh pr list --state open`에 남은 것을 목록으로 보여주고
   고르게 한다. 목록이 비면 브랜치 이름을 묻는다.
2. **계획 찾기**: `S/db_pr.py find-plan --branch <br>`. 작업 키는 그 계획의 디렉토리 이름이다. **계획이 없으면**(직접 편집한 브랜치, 다른 PC의 PR)
   아래 "계획이 없는 브랜치" 절차를 안내하고 **아무것도 바꾸지 않고** 끝낸다.
3. `db_pr lock acquire <작업 키> --command sync-pr` → `db_pr snapshot --job <작업 키>` → `config.py check --db SNAP` →
   `db_pr preflight --branch <br>`. 원격 SHA를 `start_sha`로 기록한다. 원격 브랜치가 없으면 중단(lock 해제).
4. **원격 변경 확인**: `start_sha`가 계획의 `pr.head_sha`와 다르면 마지막 publish 뒤 누군가 push한 것이다.
   `git -C <issue_db.path> diff <pr.head_sha> <start_sha> --stat`(과 필요한 부분)을 보여주고 **덮어쓰기**(그 변경은 사라진다.
   필요하면 먼저 계획에 반영) / **중단**을 묻는다. 자동으로 합치지 않는다.
5. **스키마 확인**: 계획의 `schema_version`이 SNAP의 것과 다르면 `S/db_migrate.py upgrade-plan <plan> --db SNAP --write`.
   종료 코드 2(올릴 수 없음)면 analyze/record를 다시 해서 계획을 새로 만들라고 안내하고 lock을 풀고 끝낸다.
6. `db_pr stage <plan> --wt WD/<작업 키>/wt --branch <br>` — drift면 항목마다 계획 값 유지 / main 값 유지(op 삭제) / 직접 입력을
   받아 계획에 반영하고 `base_sha`를 바꿔 다시 stage.
7. 확인 화면(`write-flow.md` 4번 형식 + **ID 재할당 내역**, **drift 결정 내역**, 계획 `source` 라벨 — record면 "수동 기록",
   `jira.origin: file`이면 "오프라인 파일") → 승인 → 커밋(별도 Bash 호출) → `db_pr publish … --lease <start_sha>`.
   lease가 거부되면(원격이 또 바뀜) 3번부터 다시.
8. 바뀐 ID가 PR 제목·본문에 있으면 `publish`가 `gh pr edit`으로 고친다. `db_pr discard`로 정리(lock 해제).
   사용자 로컬 `<br>`가 있으면 원격과 달라졌다고 알리고, 원격 기준으로 다시 받으라고 안내한다.

## analyze Step 8-2에서 원격 브랜치가 이미 있을 때

- 원격 SHA == 계획의 `pr.head_sha` → 위 6~8번과 같은 경로("plan으로 브랜치 갱신", `--lease <원격 SHA>`).
- 다르거나 계획에 PR 기록이 없음 → 원격 변경 요약을 보여주고 덮어쓰기 / 중단.
- 도구 브랜치 `tt/issue/<KEY>`만 남아 있음 → 삭제할지 묻는다. 사용자 로컬 `issue/<KEY>`는 지우지 않는다.

## 계획이 없는 브랜치 (안내만 한다)

직접 편집한 `review/...`, `move/...`, `category/...`, `chore/...` 등은 도구가 바꾸지 않는다. 사용자에게 이 절차를 안내한다:
1. 자기 로컬 브랜치에서 `git fetch origin` → `git rebase origin/<base>`.
2. 충돌이 생성 파일(README, 카테고리 README, STATS, CHANGELOG)뿐이면 main 쪽을 받고 `db_build.py --write`로 다시 만든다. 다른 충돌은 직접 해결.
3. 새로 만든 ID가 main과 겹치면(`db_add.py check-ids --base origin/<base>`) `db_add.py renumber <옛 ID>` → `db_lint.py --residual <옛>=<새>`.
4. `/telephony-triage:validate` 통과 후 커밋하고 `git push --force-with-lease`.
