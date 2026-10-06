# sync-pr (머지 전 계획 재적용) — 단일 원본

```
/telephony-triage:sync-pr [branch]
```

PR을 올린 뒤 머지 전에 main이 바뀌면, 텍스트 rebase 대신 **원래 작업 계획을 최신 main 위에 다시 적용**한다
(`07-workflow.md §sync-pr`, `06-collaboration.md §6.3`). 새 ID·fixture 번호는 그때의 main 기준으로 다시 할당되고,
계획이 건드리는 대상이 main에서 바뀌었으면(drift) 사용자가 고른다. 계획은 작성자 PC에만 있으므로 sync-pr는 작성자가 실행한다.
`commands/sync-pr.md`는 이 파일을 가리키기만 한다.

SKILL.md의 "실행 규칙"을 따른다. 이슈 DB에 쓰므로 세션 lock을 잡고 **끝나는 모든 경로에서 푼다**(`db_pr discard`가 풀고,
그 밖의 경로는 `S/db_pr.py lock release <작업 키>`). 재적용 이후(stage·확인 화면·커밋·publish·discard)는 `write-flow.md` 3~6번
그대로이고, 아래는 sync-pr만의 차이다.

1. **브랜치 선택**: 인자가 있으면 그 브랜치. 없으면 `WD/*/plan.json` 중 `pr.number`가 있는 것을 모아
   `GH_HOST=<ghe_host> gh pr list --state open`에 남은 것만 목록(브랜치, PR 번호, `source`)으로 보여주고 고르게 한다.
   목록이 비면 브랜치 이름을 묻는다.
2. **계획 찾기**: `S/db_pr.py find-plan --branch <br>`.
   - `found: false`(직접 편집한 브랜치, 다른 PC의 PR) → 결과의 `manual_steps`(아래 "계획이 없는 브랜치")를 안내하고
     **아무것도 바꾸지 않고** 끝낸다(lock도 잡지 않는다). 안내 끝에 "push 전 `validate`"를 붙인다.
   - `found: true` → `job`(= 작업 키), `source`, `remote_exists`, `remote_changed`. `remote_exists: false`면 중단(PR 브랜치가 원격에 없다).
3. **lock과 최신화**: `S/db_pr.py lock acquire <작업 키> --command sync-pr`(보유 중이면 `write-flow.md` 1번) →
   `db_pr snapshot --job <작업 키>` → `db_pr preflight --branch <br>`: `remote_sha`를 `start_sha`로 기록 → `config.py check --db SNAP`.
   쓰기 불가(스키마·생성기·파서 백엔드·gh 인증)면 이유를 보여주고 lock을 풀고 멈춘다.
4. **원격 변경 확인**: `start_sha`가 계획의 `pr.head_sha`와 다르면(`remote_changed`) 마지막 publish 뒤 누군가 push한 것이다.
   `write-flow.md` 2번처럼 `remote_diff_stat`(필요하면 `git -C <issue_db.path> diff <pr.head_sha> <start_sha>`)을 보여주고
   **덮어쓰기 / 중단**(lock 해제)을 묻는다.
5. **스키마 확인**: 계획의 `schema_version`이 SNAP과 다르면 `S/db_migrate.py upgrade-plan <plan> --db SNAP --write`
   (원본은 `<plan>.v<옛 버전>.bak`). 종료 코드 2(`upgrade_plan()` 없음)면 analyze/record를 다시 해서 계획을 새로 만들라고 안내하고 lock을 풀고 끝낸다.
6. **재적용 → 확인 → 커밋 → push → 정리**: `write-flow.md` 3~6번을 `WD/<작업 키>/plan.json`, `--wt WD/<작업 키>/wt`, `--branch <br>`로.
   sync-pr만의 차이:
   - 확인 화면에 **ID 재할당 내역**과 **drift 결정 내역**을 반드시 넣는다(`db_pr summary`가 준다).
   - publish는 `--lease <start_sha> --commit --and-discard`. lease가 거부되면(원격이 또 바뀜) 3번부터 다시. `publish`가 PR 제목·본문의 바뀐 ID를
     `gh pr edit`으로 고치고 계획의 `pr.head_sha`·`base_sha`를 갱신한다.
   - 정리 뒤 사용자 로컬 `<br>`가 있으면 원격 기준으로 다시 받으라고 안내하고, pending 피드백은 `source: analyze` 계획 PR에만
     올라간다고 알린다.

analyze Step 8에서 원격 브랜치가 이미 있을 때의 "plan으로 브랜치 갱신"도 이 6번과 같은 경로다(판단 기준은 `write-flow.md` 2번).

## 계획이 없는 브랜치 (안내만 한다)

직접 편집한 `review/...`, `move/...`, `category/...`, `chore/...` 등은 도구가 바꾸지 않는다. 사용자에게 이 절차를 안내한다:
1. 자기 로컬 브랜치에서 `git fetch origin` → `git rebase origin/<base>`.
2. 충돌이 생성 파일(README, 카테고리 README, STATS, CHANGELOG)뿐이면 main 쪽을 받고 `db_build.py --write`로 다시 만든다. 다른 충돌은 직접 해결.
3. 새로 만든 ID가 main과 겹치면(`db_add.py check-ids --base origin/<base>`) `db_add.py renumber <옛 ID>` → `db_lint.py --residual <옛>=<새>`.
4. `/telephony-triage:validate` 통과 후 커밋하고 `git push --force-with-lease`.
