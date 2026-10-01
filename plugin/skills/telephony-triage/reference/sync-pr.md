# sync-pr (머지 전 계획 재적용) — 단일 원본

```
/telephony-triage:sync-pr [branch]
```

PR을 올린 뒤 머지 전에 main이 바뀌면, 텍스트 rebase 대신 **원래 작업 계획을 최신 main 위에 다시 적용**한다
(`07-workflow.md §sync-pr`, `06-collaboration.md §6.3`). 새 ID·fixture 번호는 그때의 main 기준으로 다시 할당되고,
계획이 건드리는 대상이 main에서 바뀌었으면(drift) 사용자가 고른다. 계획은 작성자 PC에만 있으므로 sync-pr는 작성자가 실행한다.
`commands/sync-pr.md`는 이 파일을 가리키기만 한다.

SKILL.md의 "실행 규칙"을 따른다. 이슈 DB에 쓰므로 세션 lock을 잡고(`lock acquire`) **끝나는 모든 경로에서 푼다**
(`db_pr discard`가 풀고, 그 밖의 경로는 `S/db_pr.py lock release <작업 키>`). lock 획득·인계 결과의 `lock.owner`를 이후
`db_pr`·`db_verify` 호출의 `TT_LOCK_OWNER`로 넘긴다(lock 파일에서 다시 읽지 않는다). 사용자 clone의 브랜치·워킹 트리는 바꾸지 않는다.

1. **브랜치 선택**: 인자가 있으면 그 브랜치. 없으면 `WD/*/plan.json` 중 `pr.number`가 있는 것을 모아
   `GH_HOST=<ghe_host> gh pr list --state open`에 남은 것만 목록(브랜치, PR 번호, `source`)으로 보여주고 고르게 한다.
   목록이 비면 브랜치 이름을 묻는다.
2. **계획 찾기**: `S/db_pr.py find-plan --branch <br>`.
   - `found: false`(직접 편집한 브랜치, 다른 PC의 PR) → 결과의 `manual_steps`(아래 "계획이 없는 브랜치")를 안내하고
     **아무것도 바꾸지 않고** 끝낸다(lock도 잡지 않는다). 안내 끝에 "push 전 `validate`"를 붙인다.
   - `found: true` → `job`(= 작업 키), `source`, `remote_exists`, `remote_changed`. `remote_exists: false`면 중단(PR 브랜치가 원격에 없다).
3. **lock과 최신화**: `S/db_pr.py lock acquire <작업 키> --command sync-pr`(종료 코드 2면 보유자를 보여주고 묻는다: 끝난 세션이면
   `lock release <그 키> --force`, 같은 키가 10분 안이면 확인 후 `--take-over`) → `db_pr snapshot --job <작업 키>` →
   `db_pr preflight --branch <br>`: `remote_sha`를 `start_sha`로 기록 → `config.py check --db SNAP`. 쓰기 불가(스키마·생성기·
   파서 백엔드·gh 인증)면 이유를 보여주고 lock을 풀고 멈춘다.
4. **원격 변경 확인**: `start_sha`가 계획의 `pr.head_sha`와 다르면(`remote_changed`) 마지막 publish 뒤 누군가 push한 것이다.
   `remote_diff_stat`(필요하면 `git -C <issue_db.path> diff <pr.head_sha> <start_sha>`)을 보여주고 **덮어쓰기**(그 변경은 사라진다.
   필요하면 먼저 계획에 반영) / **중단**(lock 해제)을 묻는다. 자동으로 합치지 않는다.
5. **스키마 확인**: 계획의 `schema_version`이 SNAP과 다르면 `S/db_migrate.py upgrade-plan <plan> --db SNAP --write`
   (원본은 `<plan>.v<옛 버전>.bak`). 종료 코드 2(`upgrade_plan()` 없음)면 analyze/record를 다시 해서 계획을 새로 만들라고 안내하고 lock을 풀고 끝낸다.
6. **재적용**: `S/db_pr.py stage WD/<작업 키>/plan.json --wt WD/<작업 키>/wt --branch <br>`. 종료 코드 1 + `drift`면 항목별
   (`op_index`, `target`, `field`, `plan_base_value`, `current_value`)로 보여주고 **계획 값 유지 / main 값 유지(op 삭제) / 직접 입력**을
   받아 계획에 반영하고 `base_sha`를 새 기준 SHA로 바꿔 다시 stage한다. 검사 실패는 원인을 보여주고 계획을 고쳐 다시 stage한다.
7. **확인 화면**: `db_pr summary <wt>`로 `write-flow.md` 4번 형식 + **ID 재할당 내역**, **drift 결정 내역**, 계획 `source` 라벨
   (record면 "수동 기록", `jira.origin: file`이면 "Jira 메타데이터: 오프라인 파일"), 검사·검증 결과(실행/건너뜀과 사유,
   `needs-approval`은 "승인 필요"). **승인 / 수정 요청 / 전체 diff / 취소**. 승인 후 파일이 바뀌면 다시 승인받는다. 취소면 `discard`.
8. **커밋 → push**: 승인된 `commit_message`를 파일 쓰기 도구로 worktree 밖 `WD/<작업 키>/commit-message.txt`에 UTF-8 그대로 저장한다.
   메시지를 shell 명령이나 heredoc에 넣지 않는다. `git -C <wt> add -A`와 `git -C <wt> commit -F <메시지 파일>`을 **별도 Bash 호출**로
   (경로는 shell에 맞게 인용, hook을 건너뛰지 않는다) → `S/db_pr.py publish <wt> --branch <br> --lease <start_sha> --approved <approved_hash>`.
   lease가 거부되면(원격이 또 바뀜) 3번부터 다시. `publish`가 PR 제목·본문의 바뀐 ID를 `gh pr edit`으로 고치고 계획의
   `pr.head_sha`·`base_sha`를 갱신한다.
9. **정리**: `db_pr discard <wt>`(lock 해제). 사용자 로컬 `<br>`가 있으면 원격과 달라졌다고 알리고 원격 기준으로 다시 받으라고 안내한다.
   pending 피드백은 `source: analyze` 계획 PR에만 올라간다고 알린다.

## analyze Step 8-2에서 원격 브랜치가 이미 있을 때

- 원격 SHA == 계획의 `pr.head_sha` → 위 6~9번과 같은 경로("plan으로 브랜치 갱신", `--lease <원격 SHA>`).
- 다르거나 계획에 PR 기록이 없음 → 원격 변경 요약을 보여주고 덮어쓰기 / 중단.
- 도구 브랜치 `tt/issue/<KEY>`만 남아 있음 → 삭제할지 묻는다. 사용자 로컬 `issue/<KEY>`는 지우지 않는다.

## 계획이 없는 브랜치 (안내만 한다)

직접 편집한 `review/...`, `move/...`, `category/...`, `chore/...` 등은 도구가 바꾸지 않는다. 사용자에게 이 절차를 안내한다:
1. 자기 로컬 브랜치에서 `git fetch origin` → `git rebase origin/<base>`.
2. 충돌이 생성 파일(README, 카테고리 README, STATS, CHANGELOG)뿐이면 main 쪽을 받고 `db_build.py --write`로 다시 만든다. 다른 충돌은 직접 해결.
3. 새로 만든 ID가 main과 겹치면(`db_add.py check-ids --base origin/<base>`) `db_add.py renumber <옛 ID>` → `db_lint.py --residual <옛>=<새>`.
4. `/telephony-triage:validate` 통과 후 커밋하고 `git push --force-with-lease`.
