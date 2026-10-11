# 06. 협업 운영

> 원본 6장. 브랜치 표, renumber 참조 목록, op 표는 `contracts.md`에만 있다. 사용자 흐름은 `07-workflow.md`.

---

### 6.1 소유권 (CODEOWNERS)

`.github/CODEOWNERS`:

```
# 카테고리
/data/                  @<org>/telephony-data-owners
/call/                  @<org>/telephony-call-owners
/network/               @<org>/telephony-network-owners
/sim/                   @<org>/telephony-sim-owners
/sms/                   @<org>/telephony-sms-owners
/ims/                   @<org>/telephony-ims-owners

# 공통 (모든 카테고리와 모든 기여자 PC에 영향)
/parser-rules/          @<org>/telephony-issue-db-maintainers
/schema/                @<org>/telephony-issue-db-maintainers
/templates/             @<org>/telephony-issue-db-maintainers
/.githooks/             @<org>/telephony-issue-db-maintainers
/issue-db.config.yaml   @<org>/telephony-issue-db-maintainers
/GLOSSARY.md            @<org>/telephony-issue-db-maintainers
/CONTRIBUTING.md        @<org>/telephony-issue-db-maintainers
/docs/                  @<org>/telephony-issue-db-maintainers
/.gitattributes         @<org>/telephony-issue-db-maintainers
/.github/               @<org>/telephony-issue-db-maintainers

# 피드백 기록은 리뷰 불필요 (자동 기록)
/feedback/
```

- 팀 이름 형식과 `gh pr create --reviewer`에 넘기는 형식은 Phase 0에서 확인한다 (`14-site.md` S5, S19).

main 브랜치 보호 설정 (메인테이너가 GHE에서 설정하고 `docs/branch-protection.md`에 기록):
- PR 필수, CODEOWNERS 승인 1명 이상 필수
- 직접 push 금지
- (Actions를 쓰게 되면 `13-actions.md`의 추가 설정을 적용한다)

**서버 측 강제가 전제다.** 플러그인의 Claude hook과 이슈 DB의 git hook(`pre-commit`, `pre-push`)은 모두 로컬 장치라 우회할 수 있다(최선 노력 명령 파싱, `core.hooksPath` 변경). 그리고 `core.hooksPath=.githooks`는 main에 커밋된 스크립트를 **모든 기여자 PC에서 실행**하므로, 브랜치 보호와 CODEOWNERS 필수 리뷰가 서버에서 강제되지 않으면 main 쓰기 권한이 곧 팀 전체 PC의 코드 실행 권한이 된다. 브랜치 보호를 설정할 수 없는 GHE 환경이면 `.githooks/` 채택 여부를 다시 결정한다 (`14-site.md` S5, `08-safety.md §9`).

### 6.2 PR 규칙과 충돌 방지 (로컬 모드)

핵심 원리: **도구가 만드는 변경은 항상 "최신 main 위에 작업 계획을 다시 적용"하는 방식으로 만든다.** 텍스트 rebase를 하지 않으므로 생성 파일, type.md 원인 추가, parser-rules 추가에서 텍스트 충돌이 생기지 않는다. 계획이 건드리는 대상이 main에서 먼저 바뀐 경우만 drift로 사용자에게 묻는다 (`contracts.md §작업 계획` drift). 직접 편집한 브랜치는 사용자가 재동기화한다 (6.3).

| 충돌 원인 | 대책 |
|---|---|
| README/STATS/CHANGELOG 동시 수정 | 적용할 때마다 최신 main 기준으로 **항상 재생성**한다. rebase로 병합하지 않는다. |
| 같은 원인에 Jira 동시 추가 | Jira 한 건 = 파일 하나. 서로 다른 파일이라 충돌하지 않는다. |
| 같은 유형에 새 원인 동시 추가 (type.md) | `db_add.py`가 type.md를 파싱해서 엔티티 단위로 다시 쓴다. 최신 main 위에 내 원인을 추가하므로 텍스트 충돌이 없다. |
| 새 유형/원인 ID 동시 할당 | ID는 **적용 시점에 최신 main 기준으로** 할당한다 (Step 8). push 후 main이 바뀌면 `sync-pr`가 계획을 다시 적용하면서 다시 할당한다. |
| parser-rules 동시 추가 | 규칙 항목은 키로 식별하고 계획의 op(`add-parser-rule`/`update-parser-rule`)로 최신 main 위에 항목 단위로 넣는다. 같은 키를 main이 먼저 추가했거나 기능 필드를 바꿨으면 drift로 사용자에게 묻는다. 이력 필드만 바뀐 것은 drift가 아니다. |
| 같은 Jira를 두 명이 분류 | 시작 시(`db_pr preflight`)와 Step 8-3에서 **origin/main의 같은 Jira 파일**과 **열린 PR**을 검사한다. main에 있으면 중단하고 기존 분류를 보여준 뒤 유지/재분류(`reclassify`)를 묻는다. 열린 PR이 있으면 링크를 보여주고 계속할지 묻는다. 그래도 둘 다 머지되면 사후 lint가 찾아서 알리고 메인테이너가 정리한다 (6.3). |
| 같은 엔티티의 같은 필드를 양쪽이 수정 | (예: 같은 원인의 resolution을 둘 다 고침) 자동 해결하지 않는다. 계획 기반이면 drift로 양쪽 값을 보여주고 고르게 한다. 직접 편집한 브랜치는 rebase할 때 git 충돌로 드러난다 (6.3). |
| **push 이후 ~ 머지 사이에 main이 바뀜** | 6.3의 `sync-pr`, 리뷰어 머지 체크리스트, 사후 lint로 막는다. |

**ID가 바뀔 때 갱신하는 참조**: `contracts.md §renumber 참조`에만 있다. 직접 편집 브랜치의 `db_add renumber`와 메인테이너의 사후 정리가 같은 목록을 쓰고, 치환 후 `db_lint --residual`로 옛 ID 잔존을 검사한다. 도구가 만든 PR은 적용 시점 할당이라 renumber가 필요 없다.

**브랜치 규칙**: `contracts.md §브랜치`에만 있다.

- PR 제목: `[<원인 ID 또는 유형 ID>] <요약>`.
- PR 하나에는 Jira 하나(또는 리뷰 정리 한 묶음)만 넣는다. 예외: pending 피드백 파일(`03-issue-db.md §5.4 (3)`)은 analyze PR에 함께 올릴 수 있다.

### 6.3 검증 체계 (로컬 모드, 현재 기본)

CI 대신 아래 **5단계**로 검증한다. `issue-db.config.yaml`의 `ci_mode: local`일 때 동작한다.

| 단계 | 시점 | 수단 | 하는 일 |
|---|---|---|---|
| ① 적용 시 | Step 8, `record`, `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, import/review/move 계획 PR | `db_pr stage` | drift 검사, `db_add apply` 후 `03-issue-db.md §5.7 (4)` 체크리스트 전부, 생성 파일 재생성, `db_verify rules --plan` |
| ② 커밋 시 | `git commit` | **git pre-commit hook** (`.githooks/pre-commit` → `db_precommit.py --db "$(git rev-parse --show-toplevel)"`) + Claude hook | `db_lint --staged`, `mask_pii --check --staged`, `db_regress --staged`(parser-rules 변경 시 전체), 규칙 변경 시 `db_verify rules --staged`, `db_build --verify --staged` |
| ③ push 직전 | 위 모든 쓰기 흐름 | `db_pr summary` + 사용자 확인 + `db_pr publish` | 최신 main 위 계획 적용(drift 결정 포함), `check-ids`, Jira 중복·열린 PR, `db_regress --all`, `05-verification.md` 검증, 확인 화면 승인, 승인 해시·커밋 부모·커밋 메시지 일치 확인 |
| ④ 머지 직전 | 리뷰어 | PR 템플릿 체크리스트 + `sync-pr` | main이 PR 마지막 push 이후 바뀌었으면 작성자가 `sync-pr` 실행 후 머지 |
| ⑤ 사후 | 모든 커맨드의 이슈 DB 최신화 직후 (`db_pr snapshot`) | `db_lint --all --db <work_dir>/_snapshot` | main 스냅샷 전체 검사. 문제를 발견하면 알리고 메인테이너 정리를 안내한다 (아래, v1은 수동) |

- `db_verify rules`가 `needs-approval`(종료 코드 `3`)을 내면 ②는 경고 후 통과하고, ①③은 확인 화면과 PR 본문에 "승인 필요"로 표시한다 (`contracts.md §종료 코드`).

**git pre-commit hook**
- `setup` 커맨드가 이슈 DB 레포에 `git config core.hooksPath .githooks`를 설정한다. worktree도 같은 설정을 공유한다.
- `.githooks/pre-commit`은 `~/.telephony-triage/config.yaml`의 `plugin.scripts_path`에서 `db_precommit.py`를 찾아 `--db "$(git rev-parse --show-toplevel)"`로 실행한다 (worktree에서도 그 worktree를 검사하게). 이 값은 setup과 SessionStart hook이 `${CLAUDE_PLUGIN_ROOT}/scripts`로 갱신한다.
- 플러그인 없이 직접 편집하는 사람은 `CONTRIBUTING.md`에 따라 플러그인 레포를 clone하고 `plugin.scripts_path`를 그 clone의 `plugin/scripts`로 지정한다. push 전에는 `/telephony-triage:validate`(또는 같은 스크립트)를 실행한다.
- **경로가 없거나 무효하면 hook은 커밋을 차단하고 설정 방법을 안내한다** (조용히 통과시키지 않는다).
- Phase 1에서는 경고만 출력하는 스텁을 두고, Phase 8에서 실제 hook으로 교체한다.
- 우회(`--no-verify`, `-n`, `core.hooksPath` 재지정·해제)는 금지 규칙으로 명시하고, Claude hook이 차단한다. guard는 `core.hooksPath` 값이 **정확히 `.githooks`** 일 때만 이슈 DB 커밋을 허용한다 (`08-safety.md §9`). 사람이 터미널에서 우회한 커밋은 ⑤ 사후 lint가 잡는다.

**`/telephony-triage:sync-pr [branch]`** — 계획 재적용

사용자 흐름(브랜치 선택, 확인 화면)은 `07-workflow.md §sync-pr`. 여기서는 절차를 정의한다. v1은 **원래 작업 계획을 최신 main 위에 다시 적용**한다. 도구가 만든 PR(analyze, record, verify-fix, validate --cause, fix-submitted)은 모두 계획이 있으므로 이 방식으로 올린다. 계획 없는 브랜치를 자동으로 합치는 3-way replay는 v1에서 빼고 `99-deferred.md`에 남겼다.

1. **계획 찾기**: `<work_dir>/*/plan.json` 중 `pr.branch`가 `<br>`인 것. 그 디렉토리 이름이 작업 키다. 없으면 아래 "계획이 없는 브랜치"로 간다.
2. `db_pr lock acquire <작업 키>` → `db_pr snapshot --job <작업 키>` → `db_pr preflight --branch <br>`: 원격 SHA를 `<start_sha>`로 기록한다. 원격 브랜치가 없으면 중단한다.
3. **원격 변경 확인**: `<start_sha>`가 계획의 `pr.head_sha`와 다르면 마지막 publish 뒤 다른 사람(리뷰어 등)이 브랜치에 push한 것이다. `git diff <pr.head_sha> <start_sha>` 요약을 보여주고 **덮어쓰기**(그 변경은 사라진다. 필요하면 먼저 계획에 반영한다) / **중단** 중에서 고르게 한다.
4. **스키마 확인**: 계획의 `schema_version`이 main과 다르면 `db_migrate upgrade-plan`으로 계획을 올린다. 마이그레이션이 `upgrade_plan()`을 제공하지 않으면 중단하고 계획을 다시 만들라고 안내한다 (6.4).
5. `db_pr stage <plan.json> --wt <work_dir>/<작업 키>/wt --branch <br>`: 최신 origin/<base>에서 drift 검사 → 적용 → 생성 파일 재생성 → 모든 검사. 새 ID와 fixture 번호는 적용 시점에 다시 할당된다. drift가 있으면 사용자 결정을 계획에 반영하고 `base_sha`를 바꾼 뒤 다시 `stage`한다 (`contracts.md §작업 계획` drift).
6. `db_pr stage --then-summary`의 출력으로 Step 8-5와 같은 **push 전 확인 화면**(ID 재할당 내역, drift 결정 내역 포함)을 보여주고 승인받는다 → `db_pr publish --lease <start_sha> --commit --and-discard`(커밋은 `--commit`이 한다). 원격이 그 사이 바뀌었으면 push가 거부되고 2번부터 다시 한다. 커밋 메시지나 PR 제목·본문에 바뀐 ID가 있으면 `publish`가 `gh pr edit`으로 고친다.
7. `db_pr discard` (lock 해제).

- 계획은 작성자 PC에만 있으므로 **sync-pr는 작성자가 실행한다.** 리뷰어는 작성자에게 요청한다. 작성자가 없으면 리뷰어가 아래 "계획이 없는 브랜치" 절차로 할 수 있다. GHE에 "마지막 push한 사람이 아닌 사람의 승인" 규칙이 있어도 작성자가 실행하므로 문제가 없다.
- `sync-pr` 뒤 사용자 로컬 `<br>`가 있으면 원격과 달라진다. `db_pr preflight`가 이것을 알려주고, 로컬에 push하지 않은 커밋이 있으면(`ahead_of_remote`) 먼저 경고한다. 작성자는 로컬 브랜치를 원격 기준으로 다시 받는다 (`docs/`에 안내).

**계획이 없는 브랜치** (직접 편집한 `review/...`, `move/...`, `category/...`, `chore/...` 등)

v1에서 도구는 이런 브랜치를 바꾸지 않는다. `sync-pr`는 아래 절차를 안내하고 끝낸다 (`CONTRIBUTING.md`에도 둔다).
1. 자기 로컬 브랜치에서 `git fetch origin` 후 `git rebase origin/<base>`.
2. 충돌이 생성 파일(README, 카테고리 README, STATS, CHANGELOG)뿐이면 main 쪽을 받고 `db_build --write`로 다시 만든다. 다른 파일 충돌은 직접 해결한다.
3. 2번을 마쳐(리베이스 완료·생성 파일 커밋) 트리가 깨끗하고 현재 브랜치가 base·`tt/*`·detached가 아닌 상태에서만 renumber한다. 새로 만든 유형·원인 ID가 main과 겹치면(`db_add check-ids --base origin/<base>`) `db_add renumber <옛 ID>`로 다음 빈 번호로 옮기고 `db_lint --residual <옛 ID>=<새 ID>`로 확인한다.
4. `/telephony-triage:validate` 통과 후 커밋하고 `git push --force-with-lease`로 올린다.

**사후 lint(⑤)의 정리 정책** (v1: 도구는 찾아서 알리기만 하고, 정리는 메인테이너가 한다)
- 사후 lint가 문제를 찾으면 문제 종류, 관련 파일, 관련 커밋(어느 PR들이 머지됐는지)을 보여주고 메인테이너에게 알리라고 안내한다. 도구가 정리 PR을 만들지 않는다.
- **main에 같은 ID가 두 번** 들어왔으면: 적용 시점 할당과 "머지는 한 번에 하나씩" 규칙 때문에 정상 흐름에서는 생기지 않는다. 터미널에서 직접 편집한 커밋이나 `sync-pr` 없이 머지한 경우에만 생긴다. 메인테이너가 main 커밋 기록의 머지 순서로 **먼저 머지된 쪽을 소유자**로 정하고, 나중 쪽 엔티티를 `chore/fix-db-<문제 ID>` 브랜치에서 다음 빈 ID로 직접 옮긴다. 옮길 참조는 `contracts.md §renumber 참조` 목록이다. 여러 엔티티가 공유하는 파일 안의 참조(다른 원인의 `related`, 피드백 `final`·`suggested`, parser-rules `added_for`)는 나중 PR이 추가한 것만 옮긴다(`git blame`으로 확인, 모호하면 두 작성자에게 묻는다). `db_lint --all`, 옮긴 파일에 대한 `db_lint --residual <옛 ID>=<새 ID>`, `validate`를 통과한 뒤 커밋 메시지에 `Renumbered: <옛 ID> -> <새 ID>` 트레일러를 남긴다. 옛 ID는 원래 주인이 계속 쓰므로 `merged-into`를 남기지 않는다. 이것이 "main에 들어간 ID는 바꾸지 않는다" 규칙의 유일한 예외다 (`03-issue-db.md §5.5`).
- **Jira 중복**(같은 Jira 파일이 두 유형 디렉토리에 있음): 메인테이너가 나중에 머지된 쪽 파일을 지우고, 두 분류(원인 ID, 작성자, PR 링크)를 두 작성자에게 알린다 (PR 본문에 멘션). 어느 분류가 맞는지는 작성자와 카테고리 오너가 정하고, 필요하면 별도 PR로 `reclassify`한다.
- 그 밖의 규칙 위반(생성 파일 불일치, 없는 related 등)은 해당 파일만 고친다.
- 정리 PR을 만들기 전에 `db_pr preflight --branch chore/fix-db-<문제 ID>`로 원격에 같은 브랜치나 같은 제목의 열린 PR이 있는지 확인하고, 있으면 만들지 않고 링크만 보여준다.
- 정리 자동화(소유자 판별, 공유 파일 참조 판별, `renumber --in-main`, 정리 PR 초안 생성)는 `99-deferred.md`에 있다. 파일럿에서 자주 생기면 도입한다.

**`.github/pull_request_template.md`** (리뷰어 머지 체크리스트)
```markdown
## 분석 요약
(자동 작성)

## 검증 결과
(자동 작성. "승인 필요" 항목이 있으면 메인테이너 승인 필수)

## 리뷰어 머지 전 체크리스트
- [ ] GHE에 충돌 표시가 없다
- [ ] 이 PR의 마지막 push 이후 main에 다른 PR이 머지되지 않았다
      (머지됐다면 작성자에게 `/telephony-triage:sync-pr` 요청)
- [ ] 새 유형/원인의 제목·해결책이 작성 규칙(CONTRIBUTING.md)에 맞다
- [ ] parser-rules 변경이나 "승인 필요" 검증 결과가 있으면 메인테이너가 승인했다
```

- 머지는 **한 번에 하나씩** 한다. 여러 PR이 대기 중이면 하나를 머지한 뒤 다음 PR의 작성자에게 `sync-pr`를 요청한다.
- 동시 기여자가 많아져서 ④가 병목이 되면 `13-actions.md`(Actions 전환)를 검토한다.

### 6.4 스키마 버전과 마이그레이션

- `issue-db.config.yaml`의 `schema_version`은 이슈 DB 파일 구조가 바뀔 때만 올린다. 필드 추가도 필수 필드면 올린다.
- 첫 배포(반입) 전에는 v1 정의를 직접 고치고(예: Jira 기록의 선택 필드 `failed_step`), 배포 뒤에는 항상 버전을 올린다.
- 플러그인은 `SUPPORTED_SCHEMA = (min, max)`를 가진다.

| 이슈 DB 버전 | 플러그인 동작 |
|---|---|
| 지원 범위 안 | 정상 |
| 플러그인 max보다 새 버전 | **읽기 전용 분석만** 하고 이슈 DB 쓰기 전체를 막는다. 플러그인 업데이트를 안내한다. |
| 플러그인 min보다 옛 버전 | **쓰기를 막고**, 메인테이너에게 마이그레이션이 필요하다고 안내한다. 분석은 가능하다. |
| `generator_version` 불일치, `ci_mode: local`/`actions` | **이슈 DB 쓰기 전체를 막는다** (읽기 전용 분석). 생성 파일이 PR에 들어가므로 다른 버전으로 만들면 정합성 검사가 깨지기 때문이다. 업데이트를 안내한다. 플러그인만 올라갔으면 메인테이너가 아래 "버전 올림 순서" 대로 `migrate --to <현재 스키마>`로 맞춘다. |
| `generator_version` 불일치, `ci_mode: actions-build` | 영향 없음 (생성 파일은 머지 후 봇이 만든다) |

- "이슈 DB 쓰기 전체" = analyze Step 8, `record`, `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, import/review/move 계획 PR, 직접 편집 브랜치의 pre-commit·`validate`. 판정은 `config.py check --db <스냅샷 또는 wt>`가 한다(오래된 사용자 clone이 아니라 origin/<base> 기준 버전을 읽는다). `db_pr stage`가 시작 시 다시 확인한다. **예외는 `migrate/schema-v<N>` 브랜치뿐이다**: 메인테이너가 버전을 올리는 브랜치이므로 그 브랜치에서는 `config.py check`·pre-commit·`validate`가 스키마·생성기 버전 불일치를 차단하지 않고 gh 인증만 본다(브랜치 이름으로 판별).
- 마이그레이션은 플러그인 `scripts/migrations/NNNN_<설명>.py`로 작성한다. 절차는 **직접 편집 브랜치**다(계획 op로 표현할 수 없는 변경이므로, 6.3 "계획이 없는 브랜치"): 메인테이너가 자기 clone에서 `git switch -c migrate/schema-v<N>` → `/telephony-triage:migrate --to <N>`(그 브랜치의 워킹 트리를 직접 바꾼다) → `db_build --write` → `/telephony-triage:validate` → 커밋 → push → PR. op 형식이 바뀌는 마이그레이션은 옛 계획을 새 형식으로 바꾸는 `upgrade_plan()`을 함께 제공한다.
- 마이그레이션 PR을 머지하기 전에 열린 PR을 가능한 한 머지하거나 닫고, 머지되는 동안 다른 PR 머지를 멈춘다 (공지). 머지 후 남은 PR은 이렇게 올린다:
  - 계획이 있는 PR: 작업 계획의 `schema_version`이 다르므로 `db_add apply`가 거부한다. `sync-pr`가 `db_migrate upgrade-plan`으로 계획을 올린 뒤 재적용한다. `upgrade_plan()`이 없으면 analyze/record를 다시 해서 계획을 새로 만든다.
  - 직접 편집한 브랜치: 작성자가 rebase한 뒤 자기 변경분(새로 만든 파일)을 새 스키마 형식으로 직접 고치고 `validate` 후 push한다. `db_migrate --to`는 `migrate/schema-v<N>` 브랜치에서만 실행되고 main이 이미 v<N>이면 바꿀 것이 없으므로 쓰지 않는다.
- **버전 올림 순서와 되돌리기** (스키마 또는 생성기 버전이 바뀌는 플러그인 배포):
  1. **공지·병합 중지**: 이슈 DB PR 병합을 멈춘다(열린 PR은 가능한 한 먼저 머지하거나 닫는다).
  2. **플러그인 먼저**: `SCHEMA_VERSION`/`GENERATOR_VERSION`과 `migrations/NNNN_*.py`가 든 플러그인을 병합·배포한다. 이때부터 3이 끝날 때까지 팀원은 옛 DB에 새 플러그인이라 `schema-too-old`(지원 범위 min이 N이면) 또는 `generator-mismatch`로 쓰기가 막히는 **읽기 전용 기간이 생길 수 있다**. 공지에 적는다. 순서를 바꿔 DB를 먼저 올리면 옛 플러그인이 `schema-too-new`로 전원 읽기 전용이 되고, 새 플러그인 없이는 `migrate` 자체가 거부된다(`--to`가 플러그인 `SCHEMA_VERSION`보다 크면 종료 2).
  3. **migrate PR**: 메인테이너가 `migrate/schema-v<N>`에서 `migrate --dry-run` → `--to N` → `db_build --write` → `validate` → 커밋 → PR → 머지. 스키마는 그대로이고 생성기만 바뀌었으면 같은 브랜치 이름(`migrate/schema-v<현재>`)에서 `--to <현재>`가 `generator_version`만 맞춘다(`ci_mode: actions-build`는 맞추지 않는다).
  4. **재개**: 공지를 푼다. 남은 PR은 위 항목대로 올린다(`sync-pr`의 `upgrade-plan` / 직접 편집 브랜치 rebase).
  - **되돌리기**: `db_migrate`에 다운그레이드는 없다. (a) migrate PR 머지 전 → 브랜치를 버리고 플러그인을 이전 SHA로 되돌린다(S2 절차, `SITE_PROFILE.md`). (b) 머지 후 → 다시 병합 중지 → 이슈 DB에서 migrate 커밋을 `git revert`하는 PR(그 사이 머지된 새 형식 PR이 있으면 함께 revert하거나 작성자가 옛 형식으로 다시 올린다) → 머지 → 플러그인을 이전 SHA로 → 이전 플러그인으로 `db_build --write`를 다시 돌린다(생성기 버전이 되돌아가므로) → 재개. 어느 경우든 `validate`와 `config.py check --for write`가 통과한 뒤에만 재개한다.
  - 배포 전에 샌드박스 이슈 DB에서 1~4와 (b)를 한 번 돌린다(S-7 파일럿의 되돌리기 복구 시험). 2·3의 차단/통과는 `tests/test_db_migrate.py`가 고정한다.
- 플러그인 릴리스 노트에 지원 스키마 범위와 생성기 버전을 적는다.

### 6.5 시그니처 품질 피드백

- 모든 analyze와 record는 `03-issue-db.md §5.4 (3)` 피드백 기록을 남긴다. record는 `decision: manual`, `suggested: []`다. `suggested`는 `match_signatures.py` 출력 그대로(원인 ID, 전역 시그니처 키, 점수 — `db_pr stage`가 `JOB/match.json`에서 채운다), `decision`과 `final`은 Step 7 결정에서 온다. 작업 계획의 `feedback`에 담겨서 Step 8에서 파일로 쓰인다.
- `db_build.py`는 피드백을 집계해서 시그니처(전역 키)별 제안 횟수, 수락률, 1위 제안 정확도를 STATS.md에 넣는다.
  - 수락률의 분모는 그 시그니처가 **1위로 제시된** 피드백만이다 (`04-parser-matching.md §5.11 (2)`). 이 "1위"는 스텝 기준 우선 유형 가산이 반영된 순위다(실패 스텝을 준 분석은 같은 로그라도 1위가 달라질 수 있다).
  - `decision: manual`(수동 기록) 피드백은 제시된 후보가 없으므로 수락률·1위 정확도 집계에서 **제외**한다. 분석 건수와 기여 현황에는 "수동 기록"으로 따로 센다.
  - 옛 ID → 새 ID 매핑은 `merged-into:` 체인과 사후 재배치 커밋의 `Renumbered:` 트레일러로 만든다. 머지 전 renumber는 main에 옛 ID가 없으므로 매핑이 필요 없다 (`contracts.md §renumber 참조`).
- 매처는 점수를 매길 때 수락률을 가중치로 쓴다 (`04-parser-matching.md §5.11 (2)`). 표본이 `min_samples` 미만이면 쓰지 않는다. 회귀·검증 모드에서는 쓰지 않는다.
- 수락률이 `low_acceptance_rate` 미만(표본 `min_samples` 이상)인 시그니처는 리뷰 대상으로 표시한다.

### 6.6 정기 리뷰 (월 1회, 카테고리 오너)

`/telephony-triage:review [category]`가 로컬에서 리뷰 리포트를 만든다 (push 안 함). 인자가 없으면 사용자가 오너인 카테고리(CODEOWNERS 기준)를 묻는다. 오너는 리포트를 보고 필요한 수정을 `review/<category>-<YYYY-MM>` PR로 올린다. 두 가지 방법이 있다: (a) 직접 편집 후 `validate` → push, (b) 리포트의 조치를 **계획 파일**(`source: review`, op: `set-status`·`update-signature`·`reclassify`·`set-resolution`·`allow-cause`·`add-fixture`)로 적어 공통 쓰기 절차(`07-workflow.md`)로 올린다. 계획 작성은 Claude Code가 돕고(`<work_dir>/review-<category>-<YYYY-MM>/plan.json`), **별도 커맨드는 없다**. 절차는 `docs/review-guide.md`에 적는다.

| 리포트 항목 | 기준 (`issue-db.config.yaml`) | 조치 |
|---|---|---|
| 시그니처 없는 원인 | `signatures_pending: true`인 원인 (원인 판별 불가) | 판별 시그니처 추가(`update-signature`, R1~R5 통과 필요) |
| fixture 없는 원인 | 양성 fixture가 없어 R1·R2가 `skipped: fixture 없음`인 원인 | 로그를 받아 fixture 추가 |
| 오래된 원인 미확정 | `unresolved`가 `quality.unresolved_max_days` 초과 | 원인 확정 또는 담당자 지정 |
| 품질 낮은 시그니처 | 수락률 < `quality.low_acceptance_rate` | 시그니처 좁히기 또는 삭제 |
| 중복 후보 | 서로 다른 유형의 증상 시그니처가 같은 fixture에 동시 매칭, 제목 유사도 높음 | `merged-into`로 병합 |
| 오래 안 쓰인 원인 | `quality.stale_months` 동안 Jira 없음 | 유지 또는 원인 `status: deprecated` |
| 지원 종료 버전 | 원인의 `android_versions`가 **비어 있지 않고** 모두 `android_versions_supported` 밖 (빈 목록 = 전 버전이므로 제외) | 원인 `status: deprecated` |
| 수정 필요 누적 | `fix.status: open`이면서 Jira가 많은 원인 | 근본 수정 우선순위 제안 |
| 수정 상태 누락 | `fix-submitted`인데 `ref`/`fixed_in`(브랜치) 없음, `fixed`인데 `verification`/`fixed_in` 빌드 없음 | 보완 |
| fixed 전환 불가 | 코드·설정 수정 유형인데 `scenario_signatures`와 `recovery_signatures`가 모두 없음 (`fix-submitted`면 verify-fix 불가) | 시그니처 추가 |
| 빌드 없는 fix-submitted | `fixed_in`에 빌드가 없어 `03-issue-db.md §5.9` 판정 불가 | `fix-submitted` 커맨드로 빌드 추가 |
| 해결책 미검증 방치 | `resolution_verification: unverified`가 `quality.unverified_max_days` 초과 | 검증 담당자 지정 (기록자 표시: 아래) |
| 사용자 진술만 있는 해결책 | `resolution_verification: unverified`이고 `method` 또는 소속 Jira 기록 `note`에 "근거: 사용자 진술"이 있는 원인 (`record`에서 근거 없이 "효과 있었다"고 한 경우) | 카테고리 오너가 근거(다른 Jira, `resolved` fixture)를 받아 `verify-resolution` 또는 유지 판단 |
| 수정 검증 대기 방치 | `fix-submitted`가 `quality.fix_submitted_max_days` 초과 | 기록자에게 `verify-fix` 요청 (기록자 표시: 아래) |
| 수정 검증 실패·부분 통과 이력 | `verification_history`에 `failed` 또는 `partial`이 있는 원인 | 근본 원인 재검토, 남은 증상 분석 |
| `also_allowed` 누적 | 한 fixture의 `also_allowed`에 3개 이상, 또는 한 원인이 5개 이상의 다른 유형 fixture에서 허용됨 (`contracts.md §fixture`) | 그 원인의 시그니처가 너무 넓은지, 또는 fixture 구간이 너무 긴지 검토 |
| 급증 | 최근 30일 발생이 이전 90일 월평균 × `quality.surge_ratio` 이상 (발생 기준일은 Jira 기록의 `occurred_on`, 없으면 `date`) | 원인 조사 |

- **방치 기간과 기록자**: 두 "방치" 항목의 기간은 그 상태가 된 날부터 센다. 이슈 DB 파일에는 상태 전환 날짜·기록자 필드가 없으므로 git 이력(`common/history.py`)으로 구한다: 그 상태가 계속 참인 가장 오래된 `type.md` 커밋의 날짜와 **작성자 이름**(git author, 이메일은 내지 않음). 리포트 항목에 `by`와 "기록: <이름>"으로 보인다. 도구 경로의 커밋은 기록한 사용자의 git 신원으로 만들어지고 PR 머지 뒤에도 작성자가 유지되므로 그 사람이 검증 요청 대상이다. 커밋 전 상태나 이력이 없으면 "기간 확인 불가"로 따로 낸다.
- **유형 병합**: 흡수되는 유형의 `status`를 `merged-into:<유형 ID>`로 바꾸고, 그 원인들은 흡수하는 유형의 원인으로 새 ID를 받아 옮긴다. 옛 원인에는 `status: merged-into:<새 원인 ID>`를 남기고 삭제하지 않는다. Jira 파일은 새 유형 디렉토리로 이동하고 `cause`를 새 ID로 바꾼다 (`reclassify`). 브랜치는 `move/...`, 계획 `source: move`, op 조합: `new-cause`(옛 원인 내용 복사, `temp_id`) → `add-fixture`(옛 fixture 파일 경로를 `path`로, 새 원인 이름으로 복사) → `set-status merged-into`(옛 원인·옛 유형) → `reclassify`(Jira 각각. 원인 미확정 Jira는 `to: <흡수하는 유형 ID>:unresolved`).
- **원인 병합**: 옛 원인 `status: merged-into:<원인 ID>` (`set-status`), Jira `cause` 갱신 (`reclassify`). 같은 `source: move` 계획.

### 6.7 통계 (`STATS.md`, 생성 파일)

- 카테고리, 유형, 원인별 누적 건수와 최근 30/90일 건수. 각 Jira의 발생일은 `occurred_on`(없으면 `date`)이고, "최근"의 기준일은 `03-issue-db.md §5.2` 결정성 규칙을 따른다. 과거 이슈를 한꺼번에 기록해도 최근 건수에 몰리지 않는다
- Top 10 원인 (최근 90일)
- 모델별, SW별, Android 버전별, 캐리어별 분포
- 수정 상태 요약: open 원인 목록을 Jira 건수 순으로 정렬 (근본 수정 후보)
- 급증 원인 (6.6 기준)
- 시그니처 품질: 수락률 하위 10개 (수락률 정의는 6.5, `decision: manual` 제외)
- 검증 현황: 해결책 검증률, fix-submitted 대기 목록, verify-fix 통과/부분 통과/실패 건수
- 기여 현황: 월별 분석 건수(analyze / 수동 기록 구분), 기여자 수
- 시그니처 없는 원인 수, fixture 없는 원인 수 (6.6 기준)

### 6.8 매칭 성능

- 매처는 매번 이슈 DB(`--db`, analyze는 스냅샷)에서 시그니처를 메모리로 컴파일한다. 컴파일 함수는 `common/compiled.py`에 있다. **파일 캐시는 두지 않는다**: 측정 결과 컴파일 캐시는 이득이 없었다(hit 판정 비용이 컴파일보다 크다). YAML 로드가 병목으로 측정되면 그때 DB 로드 전 캐시를 둔다.
- 이슈 DB 소스 해시(소스 파일 + **파서 백엔드·외부 파서 이름·버전**, `16-existing-assets.md §16.3`)는 분석 재사용(`07-workflow.md` 입력 재사용)이 계속 쓴다.
- 읽기 스냅샷은 세션 lock을 가진 작업만 옮긴다 (`db_pr snapshot --job <작업 키>`, `contracts.md §3.2` `db_pr.py` 세부). v1은 사용자별로 한 번에 한 작업이므로 분석 도중 다른 세션이 스냅샷을 옮기지 않는다. 읽기 전용 커맨드(`search`, `review`, `preview`)는 스냅샷을 옮기지 않고 읽기만 한다.
- 유형 수백 개, fixture 수천 개 규모를 목표로 한다. 커밋 시(②)에는 변경된 유형과 그 `related`, 같은 카테고리의 fixture만 돌리고(parser-rules 변경이면 전체), push 직전(③)에 전체를 돌린다.
- `.cache/`는 커밋하지 않는다 (`.gitignore`, guard 규칙 4·pre-commit이 막는다).

### 6.9 용어집과 온보딩

`GLOSSARY.md`:
- 카테고리별 표준 용어와 금지 동의어를 둔다. 예: "call drop"(통화 중 끊김)과 "call fail"(연결 실패)을 구분하고, "콜 끊김/통화 단절"은 "콜이 끊김"으로 통일한다.
- `03-issue-db.md §5.1` 카테고리 경계 표를 그대로 둔다.
- `db_lint.py`는 제목에 금지 동의어가 있으면 표준어를 제안한다 (경고).
- 새 용어는 메인테이너 리뷰로 추가한다.
- `## 검색 별칭` 표(`질의 단어(앞부분)` \| `함께 찾을 말`)는 `search`(증상 문장 검색) 전용이다. 질의 단어가 왼쪽 단어로 시작하면 오른쪽 말도 함께 찾는다. 분류·매칭·`db_lint`에는 쓰지 않으며, 새 줄은 메인테이너 리뷰로 추가한다(CODEOWNERS).

`docs/getting-started.md` (10분 목표):
1. 플러그인 설치
2. `/telephony-triage:setup`
3. 샘플 Jira와 fixture로 `/telephony-triage:analyze --dry-run` 연습 (Jira MCP 없이 연습하려면 `--jira-file <yaml>`로 샘플 Jira 요약을 준다). 스스로 해결한 이슈를 남기는 `/telephony-triage:record --dry-run`도 함께 연습한다
4. 실제 이슈로 첫 PR
5. README, STATS 보는 법

`--dry-run`은 Step 8을 임시 worktree에서 확인 화면까지만 진행하고, 끝나면 worktree와 임시 브랜치를 지운다(`db_pr discard`). 사용자의 이슈 DB 워킹 트리와 브랜치는 바뀌지 않는다. **pending 피드백을 만들지 않는다** (`03-issue-db.md §5.4 (3)`). **gh 인증이 없어도 된다**(`config.py check --for dry-run`, 확인 화면에 "push 불가: gh 인증 없음"만 표시). 그래서 setup의 gh 로그인 전에도 연습할 수 있다. 작업 계획은 남겨두므로 같은 Jira를 다시 analyze하면 이어서 할 수 있다.

`--jira-file <yaml>`: Jira MCP 대신 파일에서 Jira 요약(`key`, `summary`, `description`, `field_map` 항목 값)을 읽는다. 계획에는 `jira.origin: file`로 남는다 (`contracts.md §작업 계획`).
- analyze는 `--dry-run`과 함께일 때만 허용한다. 실제 PR은 Jira MCP로 읽은 값으로만 만든다: `--dry-run --jira-file`로 만든 계획을 실제 analyze가 이어받으면 Step 8 전에 Jira MCP로 다시 읽어 `jira`를 덮고 `origin: mcp`로 바꾼다.
- record는 `--dry-run` 없이도 허용하되, 확인 화면과 PR 본문에 "Jira 메타데이터: 오프라인 파일"로 표시한다 (사용자가 직접 기록하는 흐름이므로). `sync-pr`로 재적용해도 계획의 `origin`이 유지되므로 라벨이 남는다.

### 6.10 새 카테고리 추가

현재 카테고리 어디에도 맞지 않는 이슈가 반복되면 새 카테고리를 만든다. 예: 긴급 통화, eSIM 프로비저닝, 위성 통신.

- **먼저 기존 카테고리로 해결되는지 확인한다.** 한두 건이면 `03-issue-db.md §5.1` 경계 표에 따라 가장 가까운 카테고리에 넣고 `tags`로 표시한다. 같은 성격의 유형이 3개 이상 쌓이거나 담당 조직이 따로 있을 때 새 카테고리를 검토한다.
- `analyze` Step 7에서 사용자가 "기존 카테고리에 안 맞음"을 고르면, 가장 가까운 카테고리에 넣는 안과 **새 카테고리 제안 초안**을 함께 보여준다. 새 카테고리는 기여자가 혼자 만들지 않고, 메인테이너 승인 PR로만 만든다.
- 새 카테고리 PR은 **메인테이너의 직접 편집 브랜치** `category/<key>`다(계획 op로 표현할 수 없는 변경이므로, 6.3 "계획이 없는 브랜치" 절차: 편집 → `db_build --write` → `validate` → push). 들어갈 것:
  1. `issue-db.config.yaml`의 `categories`에 `{key, name, id_prefix}` 추가
  2. 카테고리 디렉토리 생성
  3. `.github/CODEOWNERS`에 오너 팀 추가
  4. `GLOSSARY.md`와 경계 표에 범위, 예시, 기존 카테고리와의 경계 추가
  5. `parser-rules/tags.yaml`, `ril.yaml`에 새 카테고리 태그와 RIL 요청 추가
  6. 첫 유형과 원인, fixture (선택. 보통 이 PR 뒤에 첫 이슈 PR을 올린다)
  7. 기존 유형 중 옮길 것이 있으면 목록만 적고, 이동은 별도 `move/...` PR로 한다 (새 ID로 옮긴 뒤 옛 유형은 `merged-into`)
- 스키마 변경은 필요 없다. 카테고리 목록 검증은 `db_lint.py`가 config를 읽어서 한다.
