# 13. 부록: 사내 GHE Actions를 쓸 수 있게 되면

> 원본 13장.

현재는 Actions가 없다는 가정(`ci_mode: local`)으로 만든다. 나중에 Actions를 쓸 수 있게 되면 아래 순서로 전환한다. **로컬 모드의 도구(`db_lint`, `db_build`, `db_regress`, `db_verify`, `mask_pii`)를 그대로 CI에서 재사용**하므로 새로 짜는 코드는 워크플로우 파일 정도다.

### 13.1 사용 가능 여부 확인

1. 사내 GHE 레포 상단에 **Actions** 탭이 있는지 확인한다.
2. 조직에 **self-hosted runner**가 등록돼 있는지 확인한다. 다른 팀 레포의 Actions 실행 기록이 있으면 있는 것이다. runner에 Python 3.11+와 `pyyaml`, `jsonschema`를 설치할 수 있어야 한다.
3. runner가 사내 GHE의 플러그인 레포를 checkout할 수 있는지 확인한다.
4. (2단계 전환 시) main에 커밋할 수 있는 **봇 계정 또는 GitHub App**을 만들 수 있는지 확인한다.

확인이 안 되면 사내 DevOps/인프라 부서에 위 네 가지를 문의한다.

### 13.2 1단계 전환: PR 검증만 CI로 (권장 시작점)

생성 파일 정책은 **로컬 모드와 동일하게 PR에 포함**한다. CI는 검증만 한다. 변경이 가장 작고, 로컬 모드의 약점인 "강제력"과 "머지 직전 검사"를 해결한다.

추가 파일: `.github/workflows/db-check.yml`

| 단계 | 내용 |
|---|---|
| 트리거 | `pull_request` (대상: main) |
| runner | self-hosted (사내 runner 라벨) |
| checkout | 이슈 DB 레포 + 플러그인 레포 (`schema_version`과 `generator_version`을 지원하는 플러그인 태그) |
| 검사 | `db_lint.py --all`, `db_lint.py --changed origin/main`(base ref가 필요한 규칙: 새 원인 fixed 금지 등), `mask_pii.py --check --changed origin/main`, `db_regress.py --all`, `db_verify.py rules --changed origin/main`, `db_build.py --verify` |
| 결과 | 종료 코드 1·2면 PR 체크 실패. `db_verify`가 3(`needs-approval`)이면 체크는 통과하고 결과를 PR 코멘트로 남긴다(메인테이너 승인은 리뷰로). `db_build.py --preview` 요약을 PR 코멘트로 첨부(선택) |

워크플로우 골격 (문법은 사내 GHE 버전 문서로 확인):

```yaml
name: db-check
on:
  pull_request:
    branches: [main]
jobs:
  check:
    runs-on: [self-hosted, <사내 runner 라벨>]
    steps:
      - uses: actions/checkout@<사내 허용 버전>
        with: { fetch-depth: 0 }
      - uses: actions/checkout@<사내 허용 버전>
        with:
          repository: <org>/telephony-triage-plugin
          ref: <schema_version·generator_version에 맞는 태그>
          path: .plugin
      - run: pip install pyyaml jsonschema
      - run: python .plugin/plugin/scripts/db_lint.py --db . --all
      - run: python .plugin/plugin/scripts/db_lint.py --db . --changed origin/main
      - run: python .plugin/plugin/scripts/mask_pii.py --db . --check --changed origin/main
      - run: python .plugin/plugin/scripts/db_regress.py --db . --all
      - run: |
          python .plugin/plugin/scripts/db_verify.py rules --db . --changed origin/main || rc=$?
          # 3 = needs-approval: 실패로 보지 않는다
          if [ "${rc:-0}" -ne 0 ] && [ "${rc:-0}" -ne 3 ]; then exit "$rc"; fi
      - run: python .plugin/plugin/scripts/db_build.py --db . --verify
```

브랜치 보호 설정 추가:
- **Require status checks to pass**: `db-check`
- **Require branches to be up to date before merging**: 켠다. main이 바뀐 PR은 머지 전에 업데이트가 필요해지므로, `06-collaboration.md §6.3` ④의 리뷰어 수동 체크를 대신한다. 업데이트는 GHE의 "Update branch" 버튼이 아니라 **`sync-pr`로 한다** (계획 재적용, 생성 파일 재생성, ID 재할당이 필요하므로). 계획이 없는 브랜치는 `06-collaboration.md §6.3`의 수동 절차로 한다.

플러그인/이슈 DB 변경:
- `issue-db.config.yaml`: `ci_mode: actions`
- `pull_request_template.md`: "마지막 push 이후 main 변경 없음" 항목 제거 (브랜치 보호가 대신함)
- `06-collaboration.md §6.3` ⑤ 사후 lint는 유지한다 (비용이 낮고 이중 안전장치).
- pre-commit hook은 유지한다 (CI 전에 빨리 실패하게).

### 13.3 2단계 전환 (선택): 생성 파일을 봇이 관리

동시 PR이 많아져서 `sync-pr`가 자주 필요해지면 적용한다. **PR에서 생성 파일을 빼고, main 머지 후 봇이 만든다.** 생성 파일 때문에 생기는 재동기화가 사라진다.

추가 파일: `.github/workflows/db-build.yml`

| 단계 | 내용 |
|---|---|
| 트리거 | `push` (main), 봇 커밋에는 재실행 안 함 |
| 작업 | `db_build.py --write`로 README, 카테고리 README, STATS, CHANGELOG 생성 |
| 커밋 | 변경이 있으면 봇 계정으로 `chore: rebuild generated files` 커밋 후 main에 push |

설정 변경:
- 브랜치 보호에서 **봇 계정만** main 직접 push 예외로 둔다.
- `issue-db.config.yaml`: `ci_mode: actions-build`
- `db-check.yml`: `db_build --verify` 대신 "**PR에 생성 파일이 없는지**" 검사로 바꾼다.
- Claude hook(`08-safety.md §9` "생성 파일 정합성")과 `db_precommit`: `ci_mode: actions-build`면 생성 파일이 staged에 있을 때 차단한다.
- Step 8(`db_pr stage`): 생성 파일은 `db_build.py --preview`로 확인 화면에만 보여주고 커밋하지 않는다.
- `sync-pr`: 계획 재적용과 ID/Jira 재검사만 한다 (생성 파일 재생성 없음).
- `generator_version` 불일치는 쓰기를 막지 않는다 (`06-collaboration.md §6.4`).
- README 머리말을 "main 머지 후 CI가 갱신합니다"로 바꾼다.

### 13.4 모드별 동작 요약

| 항목 | `local` (현재) | `actions` (1단계) | `actions-build` (2단계) |
|---|---|---|---|
| 생성 파일 | PR에 포함, 적용·재적용 때마다 재생성 | PR에 포함, CI가 정합성 검증 | PR에서 제외, 머지 후 봇이 생성 |
| 강제 검증 | pre-commit hook + Claude hook (터미널 우회는 사후 lint로 보완) | CI 필수 체크 | CI 필수 체크 |
| 머지 직전 최신 여부 | 리뷰어 체크리스트 + `sync-pr` | 브랜치 보호 "up to date" + `sync-pr` | 브랜치 보호 "up to date" + `sync-pr` |
| ID 동시 할당 | 적용 시점 할당 + sync-pr 계획 재적용 + 사후 lint(보고, 메인테이너 정리) | + CI 검사 | + CI 검사 |
| `generator_version` 불일치 | 이슈 DB 쓰기 전체 차단 | 이슈 DB 쓰기 전체 차단 | 영향 없음 |
| 필요 조건 | 없음 | Actions + runner | Actions + runner + 봇 계정 |

### 13.5 전환 절차

1. 메인테이너가 13.1 확인
2. `migrate/ci-<mode>` 브랜치(직접 편집, 계획 없음)로 워크플로우, `issue-db.config.yaml`, PR 템플릿 변경을 올린다 (`validate` 통과 후 push, `06-collaboration.md §6.3` "계획이 없는 브랜치")
3. 머지 후 브랜치 보호 설정을 바꾸고 `docs/branch-protection.md`를 갱신한다
4. 테스트 PR 1건으로 체크가 동작하는지 확인
5. `docs/getting-started.md`와 `CONTRIBUTING.md`의 절차 문구를 모드에 맞게 갱신하고 팀에 공지
