# CHANGES — 단일 파일 CLAUDE.md → 분리 문서 세트

기준: 이전 단일 파일 `telephony-triage-CLAUDE.md`(약 1,830행)와 재검토 결과 1~35(+🟢).
원본 절 번호(5.7, 6.3 등)는 새 파일 안에서도 그대로 유지한다. 참조는 `파일명 §절` 형식이다.

## 구조 변경 (35)

- `CLAUDE.md`는 진입점만 남김: 머리말, `@SITE_PROFILE.md` import, 1장(요약), 문서 지도, 11.0, Phase 0~14(할 일·완료 기준·**읽을 문서**), 12장.
- 설계 상세는 `docs/design/` 13개 파일로 분리. 여러 곳에서 쓰는 표(CLI, 종료 코드, op, fixture, 브랜치, renumber 참조, 상태 값)는 `contracts.md`에만 둔다.

| 원본 | 새 위치 |
|---|---|
| 2장, 3장, 3.1 | `01-architecture.md` |
| 3.2 | `contracts.md §3.2` |
| 4장, 5.3 | `02-config.md` |
| 5.1, 5.2, 5.4~5.7, 5.9, 5.10 | `03-issue-db.md` (5.4 (4) plan 형식은 `contracts.md §작업 계획`) |
| 5.8, 5.11 | `04-parser-matching.md` |
| 5.12 | `05-verification.md` |
| 6장 (6.2 브랜치 표·renumber 목록은 `contracts.md`) | `06-collaboration.md` |
| 7장 + validate/fix-submitted/verify-fix/sync-pr 사용자 흐름 | `07-workflow.md` |
| 8장, 9장 | `08-safety.md` |
| 10장 | `09-commands.md` |
| Phase 13 본문 (입력, 트리거, eval) | `10-skill-eval.md` |
| 13장 | `13-actions.md` |
| 14장 | `14-site.md` |

## 🔴 변경

1. **읽기 스냅샷**: Step 1의 `checkout <base>` 삭제. `db_pr snapshot`: fetch → `<work_dir>/_snapshot`(`worktree add --detach`, 이후 `checkout --detach origin/<base>`) → 현재 브랜치가 base이고 깨끗할 때만 `pull --ff-only`. `.cache`, 사후 lint, `parse_logcat --rules`, 매처, `db_search`, setup `--cache-only`는 모두 스냅샷을 읽음. 12장에 "사용자 clone은 브랜치도 파일도 바꾸지 않는다" 추가.
2. **`--db` 기본값**: 인자 → cwd가 이슈 DB 안이면 `git rev-parse --show-toplevel` → config. pre-commit은 `--db "$(git rev-parse --show-toplevel)"`. 쓰기 흐름은 `db_pr`가 모든 호출에 `--db <wt>`를 명시.
3. **`db_pr.py` 추가** (`snapshot`, `cleanup`, `preflight`, `stage`, `summary`, `publish`, `discard`): Step 8, sync-pr, verify-fix, validate --cause, fix-submitted, 정리/리뷰/마이그레이션/카테고리 PR이 모두 호출. 스킬은 확인과 커밋만. **`db_search.py` 추가**. 3.1에 fixture 자르기(`parse_logcat cut`), SessionStart 갱신(`config.py sync-scripts-path`), 사후 재배치(`db_add renumber --in-main`)의 소유자 명시. Phase 7은 손으로 쓴 plan.json으로 테스트.
4. **Phase 의존성**: Phase 7의 `db_verify rules`는 뼈대(R4만 실행, R1~R3·R5 `not-implemented`). Phase 11 검색 검증은 `db_search.py`로. 컴파일 함수는 Phase 3에 `common/`, 파일 캐시 테스트는 Phase 5.
5. **op 표** (`contracts.md §작업 계획`): 필수 필드·대상·적용 규칙·renumber 필드. `temp_id` 필수. 추가 op: `reclassify`, `update-signature`, `update-parser-rule`, `set-status`. fixture는 `add-fixture` 하나로 통일(`kind`, `expect`). 최상위 `pr`. `jira`에 `carrier`, `note`. replay 전용 `set-field`/`set-body`/`put-file`.
6. **replay 알고리즘** (`06-collaboration.md §6.3`): base/ours/theirs 파싱, 스키마 정렬, 엔티티 키 표, 필드 단위 3-way 표, parser-rule 이력 필드만 다르면 main 유지, 생성 파일·.cache 무시 후 재생성, `db_add extract` → plan.json → apply 재사용. plan 없는 브랜치도 같은 방식.
7. **fixture 명명·기대값** (`contracts.md §fixture`): `<원인 ID>[.<n>].log`, `.fixed.<build>`, `.resolved.<n>`, `.recurrence.<build>`, `<유형 ID>.none[.<n>]`, `.extra.<n>`. 구분자 `.`, 정규식 fullmatch 판별. 종류별 기본 기대값. 경로는 유형 디렉토리 기준.
8. **회귀·검증 모드 `--regress`**: 분석 범위 = 파일 전체, bonus 0, 피드백 가중치 끔. `.expect.yaml`에 `occurred_at`.
9. **verify-fix 조작 방지**: `scenario_signatures` 추가. 코드·설정 수정 유형은 fixed 전환 전 scenario/recovery 중 하나 필수. 판정은 흔적 충족 전제, 흔적 없으면 판단 불가. 부분 통과는 fix-submitted 유지 + partial 이력, "통과로 기록" 선택지 삭제. 템플릿·스키마 예시·5.9·6.6·Phase 10·eval 연쇄 수정.
10. **브랜치 분리**: `fix-submit/<원인 ID>`, `verify-fix/<원인 ID>-<build>`, `verify-res/<원인 ID>-<YYYYMMDD>`. 시작 전 열린 PR 표시(`gh pr list --search`). Step 8-2 로컬·원격 검사와 선택지("sync-pr" / "plan으로 브랜치 갱신 + lease push"). 8-9에서 로컬 브랜치 삭제. `worktree add --no-track`.
11. **hooksPath**: guard는 `core.hooksPath`가 정확히 `.githooks`일 때만 커밋 허용, 그 밖(unset, 다른 값, `-c core.hooksPath=`) 차단. setup, 9장, Phase 8에 반영.
12. **Jira matcher**: `mcp__.*` + guard가 서버 이름 비교. `read_tools`는 전체 도구 이름. S1·S3에 MCP 도구 이름 형식 확인 추가.
13. **`db_verify rules (--plan | --changed | --staged) [--extra]`**, R1·R2 대상은 의존 그래프 기반, R5 결과 `needs-approval` + 종료 코드 `3`(pre-commit 경고 후 통과). 종료 코드 표 갱신.
14. **commands/** 에 `validate.md`, `verify-fix.md`, `fix-submitted.md` 추가 (11개). 10장·Phase 12와 일치.

## 🟡 변경

15. 매처는 마스킹된 이벤트만 받음(`mask_pii --events`, 아니면 종료 코드 2). db_lint가 시그니처의 원본 식별자 패턴 금지.
16. Step 7 초안 검증은 `<work_dir>/<KEY>/draft` 임시 worktree에 적용 후 검사하고 버림 (`db_verify rules --plan --draft`).
17. Step 8-4에서 `db_verify rules --plan`(R6 포함) 호출 (`db_pr stage` 안).
18. generator_version 불일치: local/actions는 이슈 DB 쓰기 전체 차단, actions-build는 영향 없음.
19. 같은 Jira 동시 PR: preflight·Step 8-3에서 열린 PR 검사. 사후 정리 정책에 Jira 중복 처리(나중 머지 쪽 파일 제거, 두 작성자에게 알림).
20. 사후 ID 재배치를 12장·5.5에 유일한 예외로 명시. `renumber --in-main <ID> --owner-commit <sha>`, 소유 판별은 파일별 `git log --diff-filter=A`.
21. renumber 참조 목록 확장(verification.fixture, evidence, expect_top/expect_not, merged-into 대상, plan add-fixture·temp_id 매핑, PR 본문, none fixture 파일명). `db_lint --residual`로 옛 ID 잔존 검사.
22. `expect_top: none` = S=1인 유형 없음. 양성 기본 기대값 = 1위 + medium 이상 (R2·R4 통일).
23. validate --cause 판정: recovery 있으면 recovery 충족, 없으면 "증상 불충족 + 시나리오 흔적 충족". 둘 다 없으면 unknown.
24. `fixed_in` 빌드 선택(없으면 판단 불가). `fix-submitted` 커맨드 추가. open으로 되돌릴 때 ref/fixed_in을 history에 보존 후 비움. "이후"는 ≥.
25. `android_versions: []` = 전 버전. 지원 종료 판단에서 제외.
26. "새 원인 fixed 금지"는 base ref가 있을 때 base에 없던 원인만. 초기 커밋·migrate 예외.
27. pending 피드백: 계획 재개 시 같은 Jira pending 삭제, analyze Step 8에만 포함, push 성공 시 삭제 + `included_pending`에 PR 번호 기록.
28. `@SITE_PROFILE.md` import(없으면 Phase 0). 우선순위: 런타임 값 원본 = 이슈 DB·config, SITE_PROFILE = 초기값 근거·설계 변경, 문서 placeholder보다 SITE_PROFILE 우선. SITE_PROFILE에 "진행 상태" 절.
29. "Phase 1에서 확정" → "Phase 0에서 확인, Phase 1(또는 해당 Phase)에서 반영"으로 통일. 14.2에 반영 Phase 열.
30. 14.2에 S16(Jira 키 형식), S17(jira_base_url), S18(fix.ref 형식), S19(reviewer 형식) 추가. S4·S7에 타임존·연도 정렬. S4 "(추가)" 삭제. config에 `jira.key_regex`, `jira.timezone`, `logcat.*`, `fix_ref_regex`, `reviewers`.
31. gh 인증 실패: setup은 안내 후 중단, 쓰기 작업 불가. Phase 1에 pre-commit 스텁, Phase 8에서 교체, "setup의 hook 설치" 중복 삭제.
32. 테스트용 변형 이슈 DB는 플러그인 레포 `tests/fixtures/issue-db-*/`. 샘플 레포 오염 금지.
33. S1에 `${CLAUDE_PLUGIN_ROOT}` 치환·`@import`·MCP 이름 형식 시험. Step 8-6 `git add`/`git commit` 별도 Bash 호출. guard 명령 파싱은 최선 노력. 공식 문서 접근 불가 시 빈 플러그인 실험(머리말, 11.0, 14.1).
34. `db_lint --all | --ref | --changed | --staged`(`--main` 삭제). pre-commit은 `--staged`(mask_pii, db_regress, db_build도). parser-rules 변경 시 커밋 회귀는 전체. 5.7 (4): 직접 편집 기여자는 push 전 `validate`. 13.2 CI에 `db_verify rules --changed origin/main`.
35. 문서 분리 (위 구조 변경).

## 🟢 변경 (모두 반영)

- `review [category]` 표기 통일 (인자 없으면 오너 카테고리 질문).
- fix-submitted 원인이 C=1이면 "update-fix → open + 실패 이력" 선택지를 직접 제시 (5.9, Step 7, eval 21).
- 수락률 분모 = 1위로 제시된 경우만. 옛 ID → 새 ID 매핑 출처 = merged-into 체인 + `Renumbered:` 트레일러.
- `--jira-file <yaml>` (dry-run 전용 오프라인 입력).
- sync-pr 기본 브랜치: work_dir의 plan에 기록된 열린 PR 목록에서 선택.
- Step 0에서 잔여 worktree·브랜치 감지·정리 (`db_pr cleanup`, `git worktree prune`).

## 그 밖의 정리

- `03-issue-db.md` 템플릿 블록의 중첩 코드 펜스를 4개 백틱으로 고침 (원본에서도 안쪽 ``` 때문에 바깥 블록이 일찍 닫혔음).
- eval 22 → 29개 (23~29 추가: 부분 통과, 흔적 없음, 필수 시그니처 없음, fix-submitted, validate --cause unknown, 원격 브랜치 존재, dirty clone).
- 트리거 테스트에 fix-submitted 트리거 1개, 비트리거 1개 추가.
- Phase 14에 완료 기준 추가.
- 확인 화면 예시의 검증 점수를 회귀 모드 기준(R2 1.00, R3 최고 0.40)으로 맞춤.

## finding → 위치 체크리스트

| # | 위치 |
|---|---|
| 1 | `07-workflow.md §Step 1`, `contracts.md §3.2`(db_pr snapshot), `02-config.md §4` setup 8, `06-collaboration.md §6.3`⑤·§6.8, CLAUDE.md 12장 |
| 2 | `contracts.md §3.2` 공통 규칙, `06-collaboration.md §6.3` pre-commit |
| 3 | `01-architecture.md §3.1`, `contracts.md §3.2`(db_pr, db_search), `07-workflow.md §Step 8·공통 쓰기 절차`, CLAUDE.md Phase 7 |
| 4 | CLAUDE.md Phase 3·5·7·11, `05-verification.md §5.12 (1)` 뼈대 문단 |
| 5 | `contracts.md §작업 계획` |
| 6 | `06-collaboration.md §6.3` replay 알고리즘 |
| 7 | `contracts.md §fixture`, `03-issue-db.md §5.2·5.7` |
| 8 | `04-parser-matching.md §5.11 (4)`, `contracts.md §fixture` |
| 9 | `05-verification.md §5.12 (2)`, `03-issue-db.md §5.4·5.7·5.9`, `06-collaboration.md §6.6`, CLAUDE.md Phase 10, `10-skill-eval.md` 19·20·23~25 |
| 10 | `contracts.md §브랜치`, `07-workflow.md §Step 8-2·8-9`, `03-issue-db.md §5.9` |
| 11 | `08-safety.md §9` #5, `02-config.md §4` setup 7, `06-collaboration.md §6.3`, CLAUDE.md Phase 8 |
| 12 | `08-safety.md §9` 매처 원칙, `02-config.md §4`, `14-site.md` S1·S3 |
| 13 | `contracts.md §3.2·종료 코드`, `05-verification.md §5.12 (1)` |
| 14 | `01-architecture.md §3`, `09-commands.md §10`, CLAUDE.md Phase 12 |
| 15 | `04-parser-matching.md §5.11 (1)`, `08-safety.md §8`, `07-workflow.md §Step 3` |
| 16 | `05-verification.md §5.12 (1)` 실행 시점 표, `07-workflow.md §Step 7` |
| 17 | `07-workflow.md §Step 8` 4번, `contracts.md §3.2` db_pr stage |
| 18 | `06-collaboration.md §6.4`, `02-config.md §5.3`, `13-actions.md §13.4` |
| 19 | `06-collaboration.md §6.2·6.3`, `07-workflow.md §Step 2·Step 8` |
| 20 | CLAUDE.md 12장, `03-issue-db.md §5.5`, `06-collaboration.md §6.3`, `contracts.md §3.2` |
| 21 | `contracts.md §renumber 참조` |
| 22 | `contracts.md §fixture`, `05-verification.md §5.12 (1)` R2 |
| 23 | `05-verification.md §5.12 (1)` 해결책 검증 표, `07-workflow.md §validate` |
| 24 | `03-issue-db.md §5.9`, `07-workflow.md §fix-submitted`, `09-commands.md §10`, `contracts.md §상태 값` |
| 25 | `03-issue-db.md §5.4`, `06-collaboration.md §6.6`, `02-config.md §5.3` |
| 26 | `03-issue-db.md §5.9` "새 원인 fixed 금지" 검사 범위 |
| 27 | `03-issue-db.md §5.4 (3)`, `07-workflow.md §Step 0·Step 8`, `contracts.md §작업 계획` |
| 28 | CLAUDE.md 머리말, `14-site.md §14.1·14.3` |
| 29 | 전체 (Phase 0 확인 / 해당 Phase 반영), `14-site.md §14.2` 반영 Phase 열 |
| 30 | `14-site.md §14.2` S4·S7·S16~S19, `02-config.md` |
| 31 | `02-config.md §4` setup 5, `06-collaboration.md §6.3`, CLAUDE.md Phase 1·6·8 |
| 32 | `01-architecture.md §3`, CLAUDE.md 11.0·Phase 5·7·10·11 |
| 33 | `14-site.md` S1·§14.1, `07-workflow.md §Step 8-6`, `08-safety.md §9`, CLAUDE.md 머리말·11.0 |
| 34 | `contracts.md §3.2`, `01-architecture.md §3.1`, `03-issue-db.md §5.7 (4)`, `13-actions.md §13.2`, `07-workflow.md §validate` |
| 35 | 문서 세트 전체, CLAUDE.md 문서 지도 |

---

# 2차 변경 — 검증 리뷰 반영 + 수동 기록(record)

기준: 분리 문서 세트 검증 리뷰(🔴1~3, 🟡4~24, 🟢25~30, ⚠ 6·7·27·30·31·35)와 사용자 요청 "사용자가 이슈를 스스로 해결하고 이슈 히스토리만 업데이트".

## 🔴
1. fixture 번호: `<n1>`(1부터: resolved, extra)와 `<n2>`(2부터: positive, negative)로 분리 (`contracts.md §fixture`, §renumber 참조, `05-verification.md`).
2. replay 0단계 "내 ID 치환": ours에만 새로 생긴 유형·원인 ID를 짝짓기 전에 `temp_id`로 바꾸고, ours의 신규 fixture 번호도 비운다. 3-way 표에 "신규/신규" 행 추가 (`06-collaboration.md §6.3`).
3. 도구 브랜치 `tt/<br>`: `db_pr`는 사용자 로컬 브랜치를 만들지도, 덮어쓰지도, 지우지도 않는다. push는 `HEAD:refs/heads/<br>` + `--force-with-lease=refs/heads/<br>:<sha>`. `stage --replace` 삭제. `cleanup`은 `tt/*`만 대상. preflight가 사용자 로컬 브랜치의 `ahead_of_remote`를 알림 (`contracts.md §3.2·§브랜치`, `07-workflow.md` Step 8·sync-pr, `08-safety.md` #6).

## 🟡
4. Phase 12: 인자 없는 validate는 스크립트 래퍼로 완성.
5. Phase 10 완료 기준을 `db_verify` 판정 + 손으로 쓴 plan 적용으로 바꿈 (스킬 의존 제거).
6. `TT_FORCE_VERIFY_EXIT=3`: Phase 7 뼈대에서 종료 코드 3 경로, Phase 8에서 pre-commit 확인.
7. setup 순서: Jira·hook·스냅샷을 먼저 끝내고 gh 인증을 마지막에 확인. 실패하면 "쓰기 불가"로 종료(읽기 설정 유지).
8. `migrate`는 버전 불일치 차단에서 제외, gh 인증만 확인 (`09-commands.md`).
9. `jira.key_regex`(사용자 config) → `issue-db.config.yaml` `jira_key_regex`. `db_lint`가 검사.
10. `parse_logcat --tz/--year`: 파서는 config를 읽지 않음 (Phase 2 인자, Phase 6 연결).
11. `parse_logcat parse --mask`: extractor 실행 전 줄 단위 마스킹, 마스킹 함수는 `common/`에 두고 공유, 멱등. extractor 패턴도 원본 식별자 금지.
12. 작업 lock(`.lock`, 4시간)과 스냅샷 읽기 임대(`snapshot --lease`). cleanup은 lock이 없거나 만료된 것만.
13. pending 피드백 포함 여부는 계획 `source`(`analyze`만)로 판단.
14. fixture 번호는 apply 시점 할당(계획에 쓰지 않음).
15. replay 전용 op는 `source: replay`에서만 허용. 상태 필드를 바꾸는 `set-field`는 종료 코드 3(승인 필요).
16. `db_verify fix --plan --draft`. R1 흔적 검사: 새 scenario/recovery 시그니처는 양성 fixture에서 충족되고, 음성 fixture 전부에서 충족되면 안 됨.
17. `verify-fix` passed는 빌드 있는 `fixed_in`이 전제 (op 거부, 05·07 안내).
18. `update-fix`에 선택 필드 `history` 추가(result failed/reverted, build, jira, fixture).
19. `approved_hash` = 임시 index `write-tree`. publish는 트리 해시, 커밋 부모(1개), 메시지, 대상 브랜치를 검사.
20. `--changed <ref>`는 merge-base 기준.
21. CI에 `db_lint --changed origin/main` 추가.
22. `reviewers.format` = `{org}/{team}`, 리뷰어 계산 규칙(`02-config.md §5.3`).
23. db-authoring 구성은 `10-skill-eval.md`에만 정의, 01·CLAUDE는 참조만.
24. Phase 1·5·7(과 2·8·10·12)의 "읽을 문서" 보강.

## 🟢
25. R2 = 유일한 1위(C=1인 원인이 그것뿐), R3 = C=0 기준. 회귀 모드 동점 설명 (`04-parser-matching.md §5.11 (4)`).
26. `cut --around <시각>` 모드. resolved/fixed fixture는 흔적 시각으로 자른다.
27. `config.py check --db <스냅샷>`: 스키마 버전을 origin/<base> 기준으로 읽음 (Step 0 → Step 1 뒤로 이동).
28. 사후 재배치 때 공유 파일 참조는 추가한 커밋으로 판별하고, 모호하면 질문.
29. guard 설정 없음 처리(git 규칙 통과, `mcp_server`가 비면 경고, `read_tools`가 비면 전부 거부).
30. `preflight --branch` 누락 수정, argument-hint에 `--jira-file`·`--extra`, `sanitize_build` 통일, 세션은 플러그인 레포 루트에서 열기(11.0).

## ⚠ 행
- 6·7: 🔴2·🔴1로 해결.
- 27: `db_pr stage`가 `source`로 pending 포함 여부 판단.
- 30: `jira_key_regex` 위치 통일(S16 반영 위치 수정), `reviewers` 사용법 정의.
- 31: gh 실패 시 setup 순서 변경(🟡7).
- 35: 읽을 문서 보강(🟡24), db-authoring 단일 정의(🟡23), `§Step 8-N` 표기 규칙을 문서 지도에 추가.

## 새 기능: 수동 기록 `/telephony-triage:record`
- 커맨드: `record <JIRA-KEY> [--cause | --new-cause <유형 ID> | --new-type <category> | --unresolved <유형 ID>] [--fixture <logcat>] [--resolved-fixture <logcat>] [--dry-run] [--jira-file <yaml>]`. 옵션이 없으면 `db_search`·`db_add similar`로 후보를 보여주는 대화형.
- 계획 `source: record`, 피드백 `decision: manual`(`suggested: []`, 수락률·1위 정확도 통계 제외).
- 쓰기 경로는 analyze Step 8과 같음(`db_pr stage` → `summary` → 커밋 → `publish`). 확인 화면·PR에 "수동 기록"과 실행/건너뛴 검증 표시.
- 검증 표: `05-verification.md §5.12 (1)` "수동 기록 검증". 항상 lint·Jira 중복·check-ids·마스킹·생성 파일·R4. 새 원인/유형은 판별 시그니처 필수, 사용자가 명시하면 `signatures_pending: true`(경고, 매칭 불가, 해결책 unverified 고정, 월간 리뷰 "시그니처 없는 원인"). fixture가 없으면 R1·R2 `skipped: fixture 없음`(통과 아님, 리뷰 대상). `fixed` 불가(`fix-submitted`까지). 해결책은 근거(Jira 키, resolved fixture)가 있을 때만 verified.
- 반영 위치: `contracts.md`(CLI 명시 규칙, `source`, op 규칙, `signatures_pending`, `decision: manual`, R 상태 사유), `01`(트리, 3.1), `02`(setup, generator 차단 목록), `03`(5.4 (1)(3), 5.7, 5.9), `04`(pending 매칭 제외, 수락률), `05`(검증 표), `06`(①, 6.5, 6.6 리뷰 항목 2개, 6.7, 6.9), `07 §record`, `08`(record도 같은 hook, 새 hook 없음), `09`(12개), `10`(트리거 2개, eval 30~35 → 35개), `CLAUDE.md`(문서 지도, 11.0 구현 위치, Phase 1·3·5·7·10·11·12·13, 12장).
- 구현: 별도 Phase 없음. Phase 7(record 계획 경로) → 10(검증 상태) → 11(리뷰) → 12(커맨드 틀) → 13(대화형 흐름·eval).
- 개수: 커맨드 11 → 12, eval 29 → 35, 트리거(돼야 함) 10 → 12, (안 됨) 5 → 7. hook 7종, 검증 단계 5단계는 그대로.

## 3차 변경 (사용자 결정 반영)

- record `--jira-file`: 실제 PR에서도 허용 유지 (PR에 "오프라인 파일" 표시).
- 도구 브랜치 접두어 `tt/`, lock·읽기 임대 만료 4시간: 유지.
- 취소한 record의 manual 피드백: **보관하지 않고 버림** (`07-workflow.md §record`, `03-issue-db.md §5.4 (3)`).
- 시그니처 보류(`signatures_pending`): **원인에만 허용, 새 유형은 증상 시그니처 필수** (`contracts.md` new-type·상태 값, `03 §5.4·5.7`, `04 §5.11`, `05`, `06 §6.6`, `07 §record`, CLAUDE.md Phase 1). eval 36 추가 (총 36개).

## 4차 변경 — 검증 리뷰 반영

기준: 3차 이후 검증 리뷰(🔴1~3, 🟡4~19, 🟢). 반영하지 않은 항목은 `REVIEW-OPEN.md`(O1~O14)로 옮겨 Phase 0에서 처리한다.

### 🔴
1. **replay의 pending 이어받기**: `signatures_pending` 새 원인은 `source: record`, 또는 `source: replay`이면서 브랜치에 이미 pending으로 있던 원인에서만 허용한다 (pending 원인이 든 record PR도 `sync-pr` 가능). `contracts.md` op 표 `new-cause`·`new-type`·상태 값, `03 §5.4 (1)`·§5.7, `06 §6.3` 3-way 표·plan 내보내기, CLAUDE.md Phase 7.
2. **재적용 초기화**: `db_pr stage`가 기준 SHA를 기록하고, 재적용 때 `checkout -f -B tt/<br> <기준 SHA>` → `reset --hard` → `clean -fd`로 이전 적용분을 지운다. `publish`는 기록된 기준 SHA를 부모로 검사한다. `contracts.md §3.2`, `07 §Step 8-5`, CLAUDE.md Phase 7 완료 기준, eval 38.
3. **새 원인의 해결책 검증**: `db_verify resolution [--plan --draft]`(`--cause`에 `temp_id` 가능). op는 순서대로 적용하고, `new-cause` 뒤의 `verify-resolution`만 새 원인을 `verified`로 만든다. lint 규칙은 "`verify-resolution` evidence 없는 verified 금지". `contracts.md` CLI·세부·op 표, `03 §5.7` 표·체크리스트, `05` 수동 기록 검증·해결책 검증, `07 §record`, `01 §3.1`, CLAUDE.md Phase 1·5·7·10, eval 38.

### 🟡 / 🟢
4. `contracts.md` `update-signature`의 pending 해제를 "원인 + `kind: cause`"로, 상태 값 표의 "원인이면" 삭제.
5. CLAUDE.md 11.0의 eval 범위를 30~38로 고침 (3차의 30~35 잔여 포함).
6. `01-architecture.md §3` `record.md` 인자에 `--resolved-fixture` 추가.
8. `--dry-run`은 pending 피드백을 만들지 않는다 (`03 §5.4 (3)`, `06 §6.9`, `07 §Step 8-5`).
13. hook #5는 정확히 `core.hooksPath .githooks`로 설정하는 명령을 허용 (`08 §9`). CLAUDE.md Phase 8 완료 기준에 "hooks 설치 후 setup 재실행 통과".
15. record에서 기록 대상 Jira 자신은 해결책 근거가 될 수 없다(`verify-resolution` 거부). 사용자가 계속 주장하면 `unverified` + "근거: 사용자 진술"(새 원인 `method`, 기존 원인 Jira `note`), 확인 화면·PR에 "카테고리 오너 리뷰 필요", 월간 리뷰 항목 "사용자 진술만 있는 해결책" (`contracts.md`, `03`, `05`, `06 §6.6`, `07 §record`, CLAUDE.md Phase 11). eval 37.
17. pending 원인의 양성 fixture는 회귀에 남고 기본 기대값은 `"<유형 ID>:unresolved"` (`contracts.md §fixture`, `03 §5.4`, `04 §5.11 (4)`, `05`, `07 §record`, CLAUDE.md Phase 5). `05` 수동 기록 검증 표에 "새 유형 + 첫 원인 pending" 행 추가.
- 🟢 CLAUDE.md Phase 5 lint 오류 주입 목록에 유형의 `signatures_pending`, 빈 `symptom_signatures`, evidence 없는 verified 추가.

### 문서 구조
- `REVIEW-OPEN.md`(레포 루트) 추가: 미반영 🟡 9개(7·9·10·11·12·14·16·18·19)와 🟢 5개. CLAUDE.md 문서 지도·Phase 0, `14-site.md §14.4` 1번·완료 기준·§14.5에 반영.
- 개수: eval 36 → 38 (37: 기록 대상 Jira 자기 근거 거부, 38: record 새 원인 해결책 draft 판정 + 재적용 무중복). 커맨드 12, hook 7, 검증 단계 5, 트리거 12/7은 그대로.

## 5차 변경 (사외 초안 → 사내 보완 모드)

- `docs/design/15-local-draft.md` 신설: 사외 PC에서 모의 환경으로 초안을 만들고 사내에서는 적은 토큰으로 보완만 한다.
  - 모의 환경(Phase D0): 모의 Jira MCP, 로컬 bare 원격 + `gh` 스텁, 합성 logcat 생성기, 모의 소스 트리, 가상 빌드명.
  - 사내 값 분리: 코드 기본값은 `plugin/site-defaults.yaml`(사내 전용)에서 읽고 사외에는 `site-defaults.example.yaml`만. 반입 시 덮어써도 사내 값 유지.
  - `TODO(SITE:S<n>)` 표시와 `DRAFT_NOTES.md`, 반입 체크리스트.
  - 사내 보완 Phase S(S-1~S-6)와 사내 토큰 절약 규칙. 사내에서 Phase 1~13을 다시 하지 않는다.
- `CLAUDE.md`: 머리말에 작업 모드 판별(사외 초안 / 사내 보완 / 사내 처음부터), Phase D0 추가, 문서 지도에 15 추가.
- `01-architecture.md` 트리: `DRAFT_NOTES.md`, `.mcp.json`(개발용), `tools/list_site_todos.py`, `tests/mocks/`, `site-defaults.example.yaml`.
- `14-site.md §14.4`: 사외 초안이 있으면 S-1 축약판을 쓰도록 안내.

## 6차 변경 (기존 사내 자산 활용)

- `docs/design/16-existing-assets.md` 신설.
  - 이미 등록된 Jira MCP 재사용: 사용자 범위 등록 확인, 논리 동작 → 실제 도구 매핑 `jira.tools`, 응답 차이는 `field_map` 경로·어댑터로 흡수.
  - 기존 data 자산: (C) 외부 파서 어댑터 `external_parsers.data`(결정성 확인, 버전 고정, merge/replace), (A) 기존 분류 가져오기 `source: import` 계획(시그니처 필수, PR당 유형 10개 이하, `import/` 브랜치), (B) 분석 스킬 연결 `analyzers.data`(리포트 보조, 분류·검증에 사용 안 함, `--no-analyzer`).
- `contracts.md`: `source: import`, `jira.tools`, `external_parsers`, `analyzers`, 외부 이벤트 이름 규칙, `--no-external`, `--no-analyzer`.
- `02-config.md`: `jira.tools`, setup 5번에 기존 MCP 탐색·매핑 확인.
- `14-site.md` S3 보강, `15-local-draft.md`에 S-4a와 D0 추가분, `CLAUDE.md` 문서 지도·Phase D0.

## 7차 변경 (기존 파서를 본체로 포팅, 총정리 가이드)

- `16-existing-assets.md §16.3`: 기존 검증된 로그 파서를 **파서 백엔드(본체)로 포팅**하는 방식으로 변경. 백엔드 인터페이스(`parse`, `builtin_events`, `version`), `site`/`reference` 백엔드, `builtin.<category>.*` 이벤트, 새 유형은 `parser-rules`로 확장, **포팅 전 골든 출력 저장과 골든 테스트**. 어댑터 방식은 대안으로 유지.
- 사외 초안의 Phase 2는 인터페이스 + 최소 reference 백엔드만 (`15-local-draft.md`, `CLAUDE.md` Phase 2·D0). 사내 S-4a에 포팅·골든 테스트 절차.
- `contracts.md`: 백엔드 인터페이스와 이벤트 이름 규칙.
- `GUIDE.md` 신설: 사외에서 만들기, 사내에서 보완하기, 설치·사용법·시나리오·팀 운영 총정리 (사람용).

## 8차 변경 (5~7차 재검토 반영)

- 🔴 모드 판별: 사용자 지시 > `SITE_PROFILE.md`(사내) > `DRAFT_NOTES.md`만 있으면 질문 > 둘 다 없으면 질문. 모드 표(시작점·진행 상태 파일·하지 않는 것). 머리말·11.0·Phase 0을 모드에 맞춤 (사내 보완에서 Phase 0·문서 전체 읽기 금지).
- 🔴 재반입: `SITE_PATHS` 목록 파일과 `tools/import_draft.py`, `draft-import/<날짜>` 브랜치 절차 (`15-local-draft.md §15.6`). 통째로 교체 금지.
- 🔴 마스킹: 번호 토큰(`<CELL#n>`, 파일 안 같은 값 = 같은 번호)으로 값 비교 관계 보존 (`08-safety.md §8`). 포팅 골든에 원본/마스킹 판별 일치 확인.
- 🔴 파서 백엔드 고정: `issue-db.config.yaml`의 `parser_backend {name, min_version}`, `builtin_events()` 존재 lint, 캐시 해시에 백엔드 버전.
- 🟡 07(Step 2 `jira.tools`, Step 3 백엔드·`source`, Step 5-1 심층 분석), 04(이벤트 이름 공간), 09(`--no-analyzer`), 10(db-authoring, eval 39~41 → 41개), 01(트리: `parser_backends/`, `adapters/`, `tests/golden/`, `SITE_PATHS`), 02(설정 우선순위, `mock-` 제외), contracts(`import/` 브랜치, 백엔드·이벤트·마스킹·우선순위 계약), 06(캐시 해시), CLAUDE Phase D0·2·4·5·6·13 완료 기준.
- 🟡 reference 백엔드 = 공통 처리 제품 수준. 모의 Jira `mock-jira`·비표준 도구 이름·`tests/mocks/mcp.json`. 운영 이슈 DB 합성 샘플 0건(S-6). import의 Jira 기록은 선택. 분석 스킬 출력 마스킹, 스킬 의견만으로 원인 생성 금지. 어댑터 파서 경로는 플러그인 안.
- 🟢 GUIDE 표현(fast-forward), 재반입 절차, 첫 사내 세션 모드 선택 안내, S-3 `jira.tools`, `SITE_PROFILE.md` 짧게 유지(근거는 `docs/site/evidence.md`).

---

# 9차 변경 — REVIEW-OPEN(O1~O14) 전부 + 8차 이후 검토(P1~P22) 반영, v1 범위 축소

기준: 8차 문서 세트, 4차 검토의 미반영 항목 O1~O14(`REVIEW-OPEN.md` 8차판), 8차 이후 사외 검토 P1~P22(🔴3, 🟡7, 🟢12).
사용자 결정: **P10 v1 범위 축소 반영**, **P9 어댑터는 유지하고 이슈 DB에 고정**, **P21 분석 스킬 기본값 `ask`**.

## 구조
- `CLAUDE.md`를 진입점(모드 판별, 1장, 문서 지도, 11.0, 12장)으로 줄이고 Phase D0~14 상세는 **`docs/design/11-phases.md`** 로 옮김 (P3a). 사내 보완 모드는 `11-phases.md`를 읽지 않는다. `CLAUDE.md` 약 25.7k자 → 약 8k자(매 세션 로드분 약 70% 감소).
- **`docs/design/99-deferred.md`** 신설: v1에서 뺀 설계(3-way replay, 사후 ID 재배치 자동화, 스냅샷 읽기 임대)와 되살릴 때 바꿀 곳. 어느 Phase에서도 읽지 않는다 (P10).
- `REVIEW-OPEN.md` 정의 변경: **사내 정보가 있어야 판단할 수 있는 항목만** 둔다. 현재 0건. 처리 시점은 S-1(사내 보완) / Phase 0(사내 처음부터) (P1).
- 설계 문서 17개(`01`~`10`, `11`, `13`~`16`, `99`, `contracts`). 커맨드 12, hook 7, 검증 단계 5, eval 41, 트리거 12/7은 그대로.

## 🔴
- **P1** REVIEW-OPEN O1~O14를 사외에서 반영하고 처리 경로를 바꿈 → `REVIEW-OPEN.md`, `CLAUDE.md` 문서 지도, `14-site.md §14.4`, `15-local-draft.md §15.5` S-1·S-6.
- **P2** 원인 평가 범위를 모드별로 정의: 분석 모드는 2단계(S=1 유형의 원인만), 회귀·검증 모드는 모든 active 원인의 C를 독립 평가 → `04-parser-matching.md §5.11 (1)·(4)`, `07-workflow.md §Step 4`, `05-verification.md §5.12 (1)`, `contracts.md §3.2`(`match_signatures`)·§fixture, `11-phases.md` Phase 3 완료 기준.
- **P3** 사내 토큰: (a) CLAUDE.md 분리(위 구조), (b) SKILL.md 본체는 analyze 핵심 흐름만 500줄 이내, 흐름별 `reference/`(write-flow, record, verify, sync-pr) → `10-skill-eval.md §SKILL 구성`(신설), `01-architecture.md §3` 트리, `07-workflow.md` 머리말, `11-phases.md` Phase 13.

## 🟡
- **P4** R3에 증상 시그니처 음성 검사(모든 음성 fixture에서 S=0) 추가, `expect_top: none`은 전역임을 명시, `db_regress`가 음성 실패 시 잡은 유형·시그니처 출력 → `05-verification.md`, `contracts.md §fixture`·§3.2, `11-phases.md` Phase 5·10.
- **P5** Jira 기록에 `occurred_on`(발생 날짜) 추가. 통계 최근 N일·급증은 `occurred_on`(없으면 `date`) → `03-issue-db.md §5.4 (2)`·템플릿, `contracts.md §작업 계획`, `06-collaboration.md §6.6·6.7`, `07-workflow.md §Step 2·record`, `11-phases.md` Phase 1·5·11.
- **P6** 마스킹: 이미 토큰이 있는 입력은 종류별 최대 번호 다음부터. 백엔드·외부 파서 이벤트도 같은 대응으로 마스킹 → `08-safety.md §8`, `contracts.md §3.2`, `11-phases.md` Phase 4.
- **P7** 재반입 기준선 `.draft-manifest.json`(SITE_PATHS): 사내에서 고친 사외 파일이면 멈춤, 사외에서 지운 파일은 삭제, 사내 신규 파일은 지우지 않고 보고 → `15-local-draft.md §15.6`, `01-architecture.md §3`, `11-phases.md` Phase D0.
- **P8** 합성 샘플은 `tests/fixtures/issue-db-sample/`(테스트 전용), 운영·반입용 이슈 DB는 `tools/make_db_skeleton.py` 뼈대. S-4는 쓸 샘플 유형을 실제 fixture와 함께 `import` PR로 넣고, S-6의 샘플 이동 작업 삭제 → `CLAUDE.md` 11.0, `11-phases.md` Phase 1·5, `15-local-draft.md §15.2~15.5`, `01-architecture.md §3`.
- **P9** 어댑터(외부 파서) 유지 + 이슈 DB 고정 `external_parsers: {<category>: {adapter, min_version}}`. 없거나 낮으면 백엔드 불일치와 같이 처리(쓰기 불가, 회귀 종료 코드 2). `ext.*` 참조는 고정된 카테고리만. `skipped: 외부 파서 없음` 삭제, `--no-external`은 분석 디버그용 → `contracts.md §기존 자산 연결 계약`, `02-config.md §5.3`, `04-parser-matching.md §5.8`, `16-existing-assets.md §16.3`, `11-phases.md` Phase 2·5.
- **P10** v1 범위 축소:
  - `sync-pr` = **원래 작업 계획을 최신 main에 재적용**(작성자가 실행). 원격이 마지막 publish 이후 바뀌었으면 덮어쓰기/중단 질문. 계획 없는 브랜치는 수동 절차 안내만.
  - **drift 검사** 신설: 계획의 `base_sha` 이후 main에서 계획 대상이 바뀌면 `db_pr stage`가 적용 전에 종료 코드 1로 알리고 항목별 결정을 받음. 계획에 `base_sha`, `schema_version` 추가, `db_add drift` CLI.
  - 옛 스키마 계획은 `db_migrate upgrade-plan`(마이그레이션의 `upgrade_plan()`)으로 올림.
  - replay 전용 op(`set-field`, `set-body`, `put-file`), `source: replay`, `db_add extract/replay`, `renumber --in-main` 삭제. `db_add renumber`는 직접 편집 브랜치의 "내 ID"만.
  - 사후 lint는 ID 중복·Jira 중복을 **보고만** 하고 메인테이너가 수동 정리.
  - 스냅샷 읽기 임대·작업별 lock → **세션 lock**(사용자별 한 번에 한 작업) `db_pr lock acquire|release|status`, 모든 종료 경로에서 해제.
  - 반영 위치: `contracts.md`(CLI, `db_pr` 세부, 종료 코드, 작업 계획, op 표, drift, renumber 참조, 상태 값), `06-collaboration.md §6.2·6.3·6.4·6.8`, `07-workflow.md` Step 0·1·8·공통 쓰기 절차·record·validate·fix-submitted·verify-fix·sync-pr, `03-issue-db.md §5.4·5.5·5.7`, `01-architecture.md §3.1`, `09-commands.md`, `13-actions.md`, `10-skill-eval.md` eval 16·28, `11-phases.md` Phase 6·7·9, `99-deferred.md`.

## 🟢
- **P11** `01-architecture.md` `analyze.md` 인자에 `--analyzer | --no-analyzer`.
- **P12** `contracts.md` 목차에 기존 자산 연결 계약, `parse_logcat` CLI에 `--no-external`.
- **P13** `${PLUGIN_ROOT}` → `${CLAUDE_PLUGIN_ROOT}`, `parse_logcat.py`가 치환 (`16-existing-assets.md §16.3`, `contracts.md`).
- **P14** `--db`는 서브커맨드 앞뒤 모두 허용, 예시는 뒤로 통일 (`contracts.md §3.2`, `13-actions.md`).
- **P15** `sanitize_build`: 연속 `.`, 끝 `.`, `.lock` 처리 + `git check-ref-format --branch` 검사 (`contracts.md §3.2`, Phase 2).
- **P16** Jira 키 검사를 Step 0 맨 앞으로 (경로·브랜치로 쓰기 전) (`07-workflow.md §Step 0·record`, `contracts.md §3.2`).
- **P17** 파서는 사용자 config를 읽지 않고 `site-defaults.yaml`의 백엔드·외부 파서 설정만 읽음 (`02-config.md §4`, `contracts.md §3.2`, Phase 2).
- **P18** 사외 모드 표식 `.local-draft`(사외 PC 전용, 반입 제외) → 매 세션 모드 질문 없음 (`CLAUDE.md` 머리말, `15-local-draft.md §15.2`).
- **P19** `--dry-run`은 gh 인증 없이 확인 화면까지 (`config.py check --for dry-run`, `push_allowed: false`) (`contracts.md`, `02-config.md` setup, `06-collaboration.md §6.9`, `07-workflow.md`, `09-commands.md`).
- **P20** GUIDE `validate`에 `--extra`.
- **P21** 분석 스킬 `when` 기본값 `ask`, `--analyzer`(묻지 않고 호출)/`--no-analyzer` (`16-existing-assets.md §16.5`, `contracts.md`, `07-workflow.md §Step 5-1`, `09-commands.md`, `10-skill-eval.md` eval 40·41).
- **P22** (검토 제안 수정) lock 만료를 프로세스 생존(PID)으로 판단하자는 제안은 스크립트가 호출마다 끝나는 구조라 쓸 수 없어 바꿈: **명시 해제 + 4시간 만료 + 사용자 확인 후 `release --force`** (`contracts.md §3.2` 세션 lock).

## REVIEW-OPEN O1~O14 (4차 미반영분)
| # | 처리 | 위치 |
|---|---|---|
| O1 | 계획 `jira.origin: mcp \| file`, summary 라벨, 실제 analyze가 file 계획을 이어받으면 MCP로 다시 읽음 | `contracts.md §작업 계획`·§3.2 summary, `06 §6.9`, `07 §Step 0·2·8` |
| O2 | 기존 계획과 `source`가 다르면 "새로 시작"만, record 계획 생성 시 같은 Jira pending 삭제 | `contracts.md §작업 계획`, `03 §5.4 (3)`, `07 §Step 0·record` |
| O3 | 임대 대신 세션 lock, `db_pr lock release`를 discard 없는 모든 종료 경로에서 호출 | `contracts.md §3.2`, `07` 전반, `09` |
| O4 | 세션 lock으로 동시 진입 자체를 막음, sync-pr 작업 키 = 계획 디렉토리, `stage`는 다른 worktree의 `tt/<br>`면 종료 코드 2 | `contracts.md §3.2`·§작업 계획, `11-phases.md` Phase 7 |
| O5 | `source: migrate`면 `config.py check --for migrate` | `contracts.md §3.2`, `06 §6.4`, `09`, Phase 7·9 |
| O6 | replay 삭제로 해소: sync-pr가 원래 계획을 재적용하므로 `source`·`jira.origin` 라벨 유지 | `contracts.md §작업 계획`, `06 §6.9`, `07 §sync-pr` |
| O7 | record 새 원인·유형 fixture는 `cut --around <시각>`, 새 시그니처 충족은 draft 초안 검증(R1·R2)이 확인 | `07 §record` 5번 |
| O8 | db-authoring 구성에 `06 §6.5·6.9` 추가 | `10-skill-eval.md` |
| O9 | setup 버전 확인을 스냅샷 뒤로 이동(`--db <snapshot>`) | `02-config.md §4` setup 6~7, Phase 6 |
| O10 | `<work_dir>/<작업 키>/state.json` = `{base_sha, branch, approved_hash, commit_message, staged_at}` | `contracts.md §3.2` |
| O11 | `cleanup (--dry-run \| --yes)`, 스킬이 확인 후 `--yes`, 현재 작업 키 제외, `--draft`도 lock 확인 | `contracts.md §3.2`, `07 §Step 0`, Phase 7 |
| O12 | 음성 fixture 0개면 R1 흔적 검사 `skipped: 음성 fixture 없음`(`review_required`) | `05 §5.12 (1)`, `contracts.md §상태 값`, Phase 10 |
| O13 | op별 규칙: `append`·`unresolved`는 main에 있으면 중단, `reclassify`는 main에 있어야 진행 | `contracts.md` op 표, `07 §Step 8-3`, Phase 7 |
| O14 | `db_lint`에 `fix.ref` 형식(`fix_ref_regex`) 검사 추가 | `01 §3.1`, `03 §5.7 (4)`, `contracts.md §상태 값`, Phase 5 |

---

# 10차 변경 — 9차 검토(Q1~Q10) 반영

기준: 9차 문서 세트 사외 검토 Q1~Q10(🔴2, 🟡8, 🟢9).
사용자 결정: **Q1 런타임 모드 판별 삭제(사내 전용, `site-defaults.yaml` 필수)**, **Q2 (b) migrate·category·cleanup은 직접 편집 브랜치**, **Q4 DB 전체 배타 유지 + `also_allowed`**, **Q7 대상 OS = Ubuntu**.
개수: 계획 `source` 값 12 → **9**(`migrate`·`category`·`cleanup` 삭제), eval 41 → **42**(42: `allow-cause`), `schema/` 5 → 6종(`expect.schema.json`). 커맨드 12, hook 7, 검증 단계 5, 트리거 12/7은 그대로.

## 🔴
- **Q1** 런타임 코드는 사내/사외 모드를 판별하지 않는다. `plugin/site-defaults.yaml`이 없으면 setup·모든 커맨드·스크립트가 종료 코드 2("사내 기본값 없음(S-3 미완료)"). `site-defaults.example.yaml`은 코드가 읽지 않고, 사외 테스트·eval은 `tests/helpers/make_plugin_root.py`가 example을 복사한 임시 플러그인 루트를 `${CLAUDE_PLUGIN_ROOT}`로 쓴다. `site-defaults.yaml`에 `jira.exclude_servers`(기본 `['mock-*']`), `synthetic_allowed`(기본 `false`) 추가 → `15-local-draft.md §15.1·15.2`, `contracts.md §3.2`·§기존 자산 연결 계약, `02-config.md` 우선순위·setup 4번, `01-architecture.md §3` 트리(`make_plugin_root.py`, `docs/site/`, `tests/site/`)·§3.1 `config.py`·`db_lint`, `09-commands.md`, `11-phases.md` D0·Phase 6, `16-existing-assets.md §16.6`, `CLAUDE.md` 12장, `GUIDE.md §2`.
- **Q2** `source: migrate|category|cleanup` 삭제. 마이그레이션·새 카테고리·사후 정리는 메인테이너의 직접 편집 브랜치(`06 §6.3` "계획이 없는 브랜치"). `migrate --to <N>`은 cwd가 clone이고 현재 브랜치가 `migrate/schema-v<N>`이며 깨끗할 때 그 워킹 트리를 직접 바꾼다(lock·계획·PR 없음). "사용자 clone은 바꾸지 않는다" 원칙의 유일한 명시적 예외로 12장에 기록. `config.py check --for migrate` 삭제 → `migrate/schema-v<N>` 브랜치(이름 판별)에서는 `config.py check`·pre-commit·`validate`·hook 4가 버전 불일치를 차단하지 않고 gh 인증만 본다 → `contracts.md §3.2`(config.py, db_migrate, stage 5번, lock 흐름)·§브랜치·§상태 값, `06 §6.3 ①·6.4·6.10`, `07` 공통 쓰기 절차, `08 §9` 4번, `09`, `02 §5.3`, `01 §3.1`, `11-phases.md` Phase 7·9, `13 §13.5`, `99-deferred.md`, `CLAUDE.md` 12장, `GUIDE.md`.

## 🟡
- **Q3** D0를 두 모드 공통으로: 사내 처음부터 모드는 "Phase 0 → D0 → 1~14" → `CLAUDE.md` 모드 표, `11-phases.md` D0·Phase 0, `15 §15.3`.
- **Q4** 양성 fixture 기대값을 "대상 원인 C=1, `also_allowed`를 제외한 다른 모든 active 원인 C=0"(DB 전체)으로 통일. `.expect.yaml`에 `also_allowed: [<원인 ID>...]`(다른 유형 원인만), 계획 op `allow-cause {fixture, cause}`, drift 행, renumber 참조, 리뷰어 계산(대상 fixture 카테고리 오너 추가), `db_regress`·R3·R4가 다른 유형 양성 fixture에서 걸리면 `allow-cause` 초안 제시, Step 7·record 7번에서 "좁히기/허용" 질문, 월간 리뷰 "`also_allowed` 누적", lint(자기 원인·같은 유형·없는 ID), eval 42 → `contracts.md §작업 계획·§fixture·§renumber 참조`, `04 §5.11 (1)·(4)`, `05` R2·R3·R4, `07 §Step 7·8-5·record`, `02 §5.3`, `03 §5.2·5.7 (4)`, `06 §6.6`, `01 §3.1`, `11-phases.md` Phase 1·5·7·10·11·13, `10-skill-eval.md`, `CLAUDE.md` 12장, `GUIDE.md`.
- **Q5** 회귀·검증 모드 판정은 S/C 불리언만 쓰고 점수·신뢰도는 참고 값 → `contracts.md §fixture`, `04 §5.11 (4)`, `05` R2·R3, `07 §Step 8-5` 예시, `11-phases.md` Phase 3·10.
- **Q6** review/move 계획 PR은 커맨드 없이 Claude와 함께 계획 파일을 작성해 공통 쓰기 절차로 올린다. `move` op 조합 명시 → `06 §6.6`, `07` 공통 쓰기 절차, `11-phases.md` Phase 1(review-guide).
- **Q7** 대상 OS Ubuntu 명시, 다른 OS는 v1 범위 밖 → `01 §3`, `14-site.md` S15, `15 §15.2`, `11-phases.md` D0 완료 기준(hook 실행 비트), `CLAUDE.md` 머리말, `GUIDE.md §2·4`.
- **Q8** 사내 보완 모드에 S-7(= Phase 14 배포·파일럿) 추가 → `15 §15.5`, `CLAUDE.md` 모드 표·문서 지도, `11-phases.md` Phase 14, `GUIDE.md §2·4`.
- **Q9** 같은 Jira의 계획을 만들거나 재개하면(새로 시작 포함) pending 피드백 삭제. 같은 작업 키 lock이 10분 이내 갱신됐으면 확인 후 `acquire --take-over` → `contracts.md §3.2·§작업 계획`, `03 §5.4 (3)`, `07 §Step 0·record`, `11-phases.md` Phase 6.
- **Q10** `verify-fix partial`은 `fixed` 재검증에서 `fixed` 유지 + 이력. `fix-submitted` 커맨드는 `wont-fix`·`not-a-bug`에서 확인 후 진행. `update-fix`는 `fixed` → `fix-submitted` 거부(record에서 이미 `fixed`면 안내만). `verify-resolution` evidence의 Jira 키·fixture 경로 존재 검사 → `contracts.md` op 표, `05 (2)`, `07 §record·fix-submitted`, `03 §5.7 (4)`, `01 §3.1`, `11-phases.md` Phase 5·7·10.

## 🟢
- a. `07 §Step 8-3` worktree 기준을 `<기준 SHA>`로. b. `CLAUDE.md 11.0` 읽을 문서 규칙을 모드별로 분리. c. `01 §3` 트리에 `docs/site/`·`tests/site/`, `discard --keep-branch` 삭제. d. `sync` 작업 키 `sync`. e. 피드백 `date`·파일명 timestamp = 계획 `feedback.date`(재적용해도 불변). f. R1 흔적 검사 음성 범위 "그 카테고리"로 통일(Phase 10). g. `contracts.md §브랜치` `import/` 행 정리. h. `@SITE_PROFILE.md` 없는 파일 import 실험을 D0에 추가. i. 데이터 스택 태그에 `DSM-`, `DCM-`, `DSRM-` 추가(`04 §5.8`, `07 §Step 3` 목록은 `04` 참조, `14` S8, `CLAUDE.md` 머리말).

# 11차 변경 — 10차 문서 세트 동작 검토(U1~U17) 반영

기준: 10차 문서 세트 동작 검토 U1~U17(🔴5, 🟡12). 관점: 분석 정확도(텔레포니 특성), 운영 부담, 보안(저장되는 정보와 실행 경로). 사내 정보가 필요한 항목 없음(`REVIEW-OPEN.md` 0건 유지). 상세는 `docs/history/REVIEW-11.md`.
개수: hook 7 → **8**(Write/Edit 차단), eval 42 → **45**, placeholder 레지스트리 S19 → **S21**(S20 슬롯 표기, S21 bugreport 구조), git hook 1 → **2**(`pre-push`). 커맨드 12, 검증 단계 6, 계획 `source` 9는 그대로.

## 🔴
- **U1** Jira 텍스트 마스킹과 최소 저장: Jira에서 읽은 텍스트는 즉시 `mask_pii`, 이슈 DB·PR 본문·계획에는 구조화 필드와 사용자가 확인한 `note` 한 줄만(원문 저장 금지, 사람 이름 제외). `db_lint`가 `note`·본문·`cp_evidence`의 식별자 패턴 검사 → `08 §8.1`(신설), `07 §Step 2·8-7`, `03 §5.4 (2)`, `contracts.md §작업 계획`, `01 §3.1`, `11-phases.md` Phase 4, eval 43.
- **U2** hook 8: `Write|Edit|MultiEdit|NotebookEdit`로 사용자 clone(`issue_db.path`) 안 파일 쓰기 거부(`<work_dir>` 제외) → `08 §9`, `11-phases.md` Phase 8, `GUIDE.md §7`.
- **U3** `.githooks/pre-push`(base 브랜치 대상 거부, `TT_PUBLISH_TOKEN`이 `state.json`의 `approved_hash` 또는 `manual`이 아니면 거부. `db_pr publish`가 토큰을 넣음)와 **서버 측 강제 전제** 명시(브랜치 보호·CODEOWNERS 필수 리뷰 없이는 `.githooks/`가 코드 실행 경로) → `03 §5.2`, `06 §6.1`, `08 §9`, `contracts.md §3.2` publish, `11-phases.md` Phase 1·8·D0, `14-site.md` S5.
- **U4** 슬롯 구분: 이벤트 `phone_id`(태그 접미사·메시지 접두어, 없으면 `null`), 시그니처 `same_phone`(기본 true, `null`은 와일드카드, DDS 전환은 false), RIL 페어링 키 `(pid, phone_id, serial)`, 리포트에 슬롯 표시, 교차 슬롯 음성 fixture `DATA-001.none.2.log` → `04 §5.8 (2)·5.11 (1)`, `07 §Step 3·4·6`, `03 §5.4 (1)`, `contracts.md §3.2`, `14-site.md` S20, `11-phases.md` Phase 1·2·3, eval 44.
- **U5** 시그니처 `sequence`(조건 id 순서대로 첫 충족 시각 단조 증가, 선택, 호환) → `04 §5.11 (1)`, `03 §5.4 (1)` 예시, `01 §3.1` lint, `11-phases.md` Phase 1·3·5.

## 🟡
- **U6** `parse_logcat` 출력 `coverage`(파일 시각 범위, `window_in_range`, `clock_anomalies`). 범위 밖은 "매칭 없음"과 구분해 보고하고 `--full` 재파싱 제안, 시계 이상은 증상 스캔 제안 → `contracts.md §3.2`, `07 §Step 3·6`, `11-phases.md` Phase 2.
- **U7** 후보 없음 폴백: 설명 기반 유사 후보(`db_search`) + 타임라인 요약의 오류·거부 이벤트 + 범위·시계 판정. 점수·검증·자동 op 없음, Step 7은 "새 유형/원인 미확정/기록하지 않음"만 → `07 §Step 4·6·7`, eval 45.
- **U8** 발생 시각 없으면 `parse --full` + `--regress` 매칭으로 증상 시각 후보 3개를 먼저 제시, 없을 때만 묻는다 → `07 §Step 2`, eval 5.
- **U9** bugreport 입력(범위 변경): `parse_logcat extract-bugreport`가 logcat 섹션과 `build.json`만 추출, dumpsys 등은 읽지 않음. analyze·record·verify-fix가 자동 추출, fingerprint를 Step 2-1·verify-fix 빌드 확인에 사용 → `CLAUDE.md` 1장 범위표, `contracts.md §3.2`, `07 §Step 2·2-1·3·verify-fix 3번`, `09-commands.md`, `14-site.md` S21, `11-phases.md` Phase 2.
- **U10** 원인 필드 `cp_evidence`(선택, CP 근거 요약, 매칭·검증 미사용, 마스킹·lint 대상, README 표시) → `03 §5.4 (1)·5.7 (3)`, `01 §3.1`.
- **U11** 정규식 안전: `db_lint`가 중첩 수량자·무제한 역참조 거부, `matcher.pattern_timeout_ms`(기본 2000, 초과 시 `error`로 표시하고 계속) → `02 §5.3`, `04 §5.8 (4)`, `01 §3.1`, `11-phases.md` Phase 3·5.
- **U12** 마스킹 표에 자격증명 성격 값 `<CRED#n>`(SIP Digest `response=`·`nonce=`, AKA `RES`/`AUTN`, `password`/`token` 문맥) → `08 §8`, `11-phases.md` Phase 4.
- **U13** `work_dir`·`~/.telephony-triage/` 권한 700(setup), `db_pr cleanup --older-than`(닫힌 PR의 오래된 작업 디렉토리, `sync` 끝에 확인 후 삭제) → `02 §4`, `contracts.md §3.2`, `09-commands.md`, `11-phases.md` Phase 12.
- **U14** 사내 **S-0(선택)** 선행 확인: 사외 Phase 3 이후 reference 파서·매처만 실제 로그에 Python으로 돌려 수치는 `SITE_PROFILE.md`에만, 사외로는 정성 결론만 → `15 §15.3·15.5`, `11-phases.md` Phase 3 비고, `GUIDE.md §4`.
- **U15** 파일럿 전 오프라인 재현 평가 게이트: 과거 해결 Jira 20~30건 라벨셋(`tests/site/offline-eval.yaml`) + `tools/offline_eval.py`(1위 정확도·상위 3 포함률·오탐률), 기준은 S-1에서 합의 → `15 §15.5` S-5, `11-phases.md` Phase 12·14, `01 §3`, `GUIDE.md §4`.
- **U16** S-4 완료 기준에 카테고리별 시드 5~10개(`source: import`), 파일럿 지표에 PR 소요 시간·중도 취소 비율 → `15 §15.5` S-4·S-7, `11-phases.md` Phase 14, `GUIDE.md §4`.
- **U17** 개수·트리 정합: hook 8종, eval 45, S21, `tools/offline_eval.py`, `.githooks/pre-push`, `tests/site/offline-eval.yaml` → `01 §3`, `03 §5.2`, `15 §15.4`, `CLAUDE.md` 문서 지도, `GUIDE.md`.

## 🟢
- `GUIDE.md §6` 시나리오 1에 마스킹·시각 후보·범위 밖·bugreport·슬롯·후보 없음 한 줄씩, `§7`에 Write/Edit 차단·pre-push·서버 강제 전제, `§8`에 `docs/history/REVIEW-11.md`.

## 사외 초안 중 계약 보완 (Phase 7 대조, 2026-09-29)

`contracts.md §3.2`만 바뀌었다. 근거는 `DRAFT_NOTES.md` "Phase 7 대조 후 보완".
- `--db` 기본값 규칙의 예외에 `db_pr.py` 추가(오케스트레이터, 항상 config의 `issue_db.path`).
- 세션 lock: `snapshot`·`stage`·`summary`·`publish`·`discard`·`db_verify --draft`의 lock 확인은 **만료 여부를 보지 않는다**(같은 작업 키면 이어간다).
- `stage` 7번에 `db_add check-ids` 추가(`mask_pii` 뒤).
- `publish`의 "커밋 1개" 검사에 `HEAD^2` 없음(머지 커밋 아님) 명시.

## 사외 초안 중 계약 보완 (Phase 8, 2026-09-29)

근거는 `DRAFT_NOTES.md` "Phase 8 구현에서 정한 세부". 사용자 확인 후 반영.
- `guard.py`는 `site-defaults.yaml`이 없어도 종료 코드 2로 멈추지 않고 경고 후 사용자 config로 판정한다 → `contracts.md §3.2` 설정 읽기, `08-safety.md §9`.
- `pre-push` 토큰 검사 강화: `<work_dir>/*/state.json`에서 토큰을 찾고, push 커밋 트리 = 토큰, 대상 브랜치 = 그 `state.json`의 `branch`, 원격 ref 삭제 불가. `base_branch`·`work_dir`는 사용자 config(없으면 기본값). 플러그인 스크립트 없이 동작 → `08-safety.md §9`, `contracts.md §3.2` publish.

## 사외 초안 중 계약 보완 (Phase 9, 2026-09-29)

근거는 `DRAFT_NOTES.md` "Phase 9 구현에서 정한 세부".
- `db_migrate --to`: 플러그인 `SCHEMA_VERSION` 초과 거절, `--dry-run`은 브랜치 검사 없음, 메모리에서 모두 적용 후 한 번에 쓰기, `generator_version`(`actions-build` 제외) 자동 동기화, 마이그레이션 모듈 계약(`FROM_VERSION`·`TO_VERSION`·`migrate(tree)`·`upgrade_plan(plan)`), `upgrade-plan --write`의 `.bak` → `contracts.md §3.2`.
- `06-collaboration.md §6.4`의 "직접 편집한 브랜치에서 `db_migrate --to <N>`" 안내를 "자기 변경분을 새 스키마 형식으로 직접 고친다"로 고침. `--to`는 `migrate/schema-v<N>` 브랜치에서만 돌므로 그 안내가 계약과 어긋났다.

## 사외 초안 중 계약 보완 (Phase 10, 2026-09-29)

근거는 `DRAFT_NOTES.md` "Phase 10 구현에서 정한 세부".
- `db_verify rules`: 기준 트리(`--plan`은 대상 트리 `HEAD`, `--changed`는 merge-base, `--staged`는 `HEAD`)와의 **의미 비교**로 대상을 정한다. 의존 그래프의 tags·ril 규칙, R1 파서 검사의 정의, R3 원인 대상 fixture 목록, 항목 모으기 순서, `checks[]`·`changes` 출력 → `contracts.md §3.2` `db_verify.py` 세부.
- R6: `--extra-normal <logcat...>`(정상 표본) 추가, R6 `fail`은 종료 코드에 넣지 않음(`blocking: false`) → `contracts.md §3.2`, `05-verification.md §5.12 (1)`.
- `db_verify resolution`·`fix` 출력 필드(`suggested_ops`, `build_check`, `other_candidates`, `withheld`), `fix` 중단 조건, `failed`를 흔적 검사보다 먼저 판정 → `contracts.md §3.2`.
- `db_regress --events-diff <ref>` 출력 형식과 이벤트 식별 `(ts, phone_id, tag, event)` → `contracts.md §3.2`.
- `verify-fix` op의 `verification.fixture`는 `passed`만 필수(`failed`의 recurrence fixture, `partial`은 선택. 05 §5.12 (2) "넣을지 묻는다"와 맞춤) → `contracts.md §작업 계획` op 표, 이슈 DB `schema/plan.schema.json`.
- `not-implemented`는 Phase 7~9 뼈대에서만 썼다 → `contracts.md §상태 값`, `05-verification.md §5.12 (1)`, `03-issue-db.md §5.7 (4)`.
- recovery 시그니처 예시를 "이 원인에 특정한 정상 흐름"(계기 이벤트 → 정상 동작 `sequence`)으로 고침. 정상 로그 어디에나 맞는 `SETUP_DATA_CALL` 요청만의 예는 R1 흔적 검사(카테고리 음성 fixture 전부에서 충족 금지)를 통과할 수 없다. 사용자 결정 (a) → `03-issue-db.md §5.4 (1)`·`§5.7 (2)`.

## 사외 초안 중 계약 보완 (Phase 11, 2026-09-29)

근거는 `DRAFT_NOTES.md` "Phase 11 구현에서 정한 세부".
- `db_review.py`: `--as-of`·`--json` 추가, 출력 형식, 기준일은 실행일, 방치 기간은 git 이력(없으면 "기간 확인 불가"), 중복 후보·수정 필요 누적·`also_allowed` 누적의 판정, 카테고리 범위 → `contracts.md §3.2` `db_review.py` 세부.
- `db_search.py` 출력 형식(`kind`, `results[]`, `links[]`, `current`·`merged_from`) → `contracts.md §3.2`.
- op 표 `set-status`: `id`·`merged-into:` 대상에 같은 계획의 temp_id 허용(이슈 DB `schema/plan.schema.json`도). op 표의 "ID 참조 필드"와 스키마가 어긋나 병합 계획이 거부됐다 → `contracts.md §작업 계획`.
- op 표 `add-fixture`: `path`에 이슈 DB 기준 상대 경로 허용(병합 계획이 옛 fixture를 복사) → `contracts.md §작업 계획`.
- op 표 `reclassify`: `to: <유형 ID>:unresolved`로 원인 미확정 Jira를 다른 유형으로 옮긴다(유형 병합에서 옛 유형의 원인 미확정 Jira가 남던 문제, 사용자 결정 (a)) → `contracts.md §작업 계획`, `06-collaboration.md §6.6`, 이슈 DB `schema/plan.schema.json`.
- `GENERATOR_VERSION`·`SCHEMA_VERSION` 증가 규칙은 첫 배포(S-7 파일럿)부터 적용한다. 그 전의 생성 결과 변경은 v1에 포함한다(사용자 결정, `DRAFT_NOTES.md`).
- STATS "fixture 없는 원인"은 pending 원인을 뺀다(`06-collaboration.md §6.6` 정의·`db_lint`와 같게). 유형별 건수 표 추가(§6.7).

## 사외 초안 중 계약 보완 (Phase 13, 2026-09-29)

근거는 `DRAFT_NOTES.md` "Phase 13 구현에서 정한 세부".

- **`jira_fields.py` 추가**: Jira 키 검사(`check-key`)와 Jira 응답 → `field_map` 추출·텍스트 즉시 마스킹·발생 시각 UTC 변환·`--jira-meta` 생성(`extract`). 스킬이 매번 손으로 하던 일을 결정적 스크립트로 옮김 → `contracts.md §3.2` 표, `01-architecture.md §3`·§3.1.
- **`db_pr.py`·`code_roots.py`**: `--json`·`--plugin-root`를 서브커맨드 앞뒤 어디서나 받는다(`contracts.md §3.2` 공통 규칙과 맞춤).
- **계획 `pr_notes`(선택)**: 확인 화면·PR 본문에 붙는 흐름별 설명(drift 결정, verify-fix 근거, allow-cause 사유). 이슈 DB `schema/plan.schema.json`에 선택 필드 추가, `db_pr summary`가 마스킹해 넣는다. 스키마 버전은 그대로(선택 필드).
- **`config.py show` effective에 `analyzers`** 포함(site-defaults → 사용자 config 병합).

## Phase 13 평가 재개 중 보완 (2026-09-30)

- `schema/plan.schema.json`의 시그니처 `must_match`에 문자열 외에 `{id, pattern}` 조건도 허용한다. 유형 스키마와 공통 계약은 이미 이 형식을 지원했지만 계획 스키마가 거부하여, 정규식 조건을 포함한 `sequence`를 새 원인 계획에 넣을 수 없었다. 샘플·변형 DB 7곳에 반영했고, 기존 문자열 호환·잘못된 객체 거절·해결책 draft 검증과 stage를 회귀 테스트한다. 배포 전 v1 보완이므로 기존 버전 유지 규칙을 따른다.
- 스킬 eval 45개 입력 정의를 완성했다. `run.py`로 새 격리 환경을 준비·실행하며, 채점기는 실행 기록 없음과 API 중단을 통과로 세지 않는다. 대화 판단은 수동 채점으로 남긴다.
- 트리거 입력 2개에 Telephony 이슈 DB 맥락을 명시했다. 독립 정적 리뷰와 실제 Claude 자동 선택 검증을 구분한다. 실제 행동 평가·런타임 시험은 Claude Code 주간 한도(429)로 미완료다.
- 스킬 description의 분류 구분 기호를 바꿔 skill-creator frontmatter 검증을 통과하도록 했다. 흐름과 분류 의미는 같다.

## 사내 토큰 절약 (2026-10-01)

- `15-local-draft.md §15.5` S-1 "읽을 것": `DRAFT_NOTES.md`는 "진행 상태" 절만, TODO(SITE) 목록은 `tools/list_site_todos.py` 출력으로 대체. 사내 첫 세션의 고정 읽기를 약 4만 토큰 줄인다(`docs/development/ARCHITECTURE_REVIEW_2026-10.md` P2의 즉시 적용분).
- `15-local-draft.md §15.5` S-0: 체크리스트(`docs/development/S0_PROBE_CHECKLIST.md`)와 지표 도구(`tools/s0_stats.py`, 테스트 3개) 연결. S-0가 S-3보다 앞이라 `site-defaults.yaml`이 없어 파서가 멈추는 점을 임시 플러그인 루트로 우회하는 절차를 명시.
- 문서 정리(2026-10-01): `docs/history/REVIEW-10.md`·`docs/history/REVIEW-11.md` → `docs/history/`(참조 갱신). `EXTENSION_IDEAS.md`는 `ARCHITECTURE_REVIEW_2026-10.md` §X 부록으로 합치고 삭제. `CHANGES.md`·`DRAFT_NOTES.md` 이동은 RF-1에서.
- 문서 정리 2단계(2026-10-01): `CHANGES.md` → `docs/history/`(이 파일), `DRAFT_NOTES.md`는 이름을 유지한 채 ≤6KB 상태 파일로 축소하고 본문을 `docs/history/draft-notes-2026-09.md`로. `14-site.md §14.5` 반입 문서 세트에 `docs/history/CHANGES.md`·`DRAFT_NOTES.md` 명시, `15-local-draft.md §15.1·15.4·15.5` 문구 갱신, `01-architecture.md §3` 트리에 `docs/history/`. `CLAUDE.md` §1·문서 지도 압축(원칙 §11.0·§12 불변).
- 외부 리뷰 반영(2026-10-01): 결정 (a) 사내→사외 반출은 사용자 타이핑 문장만 — `15-local-draft.md §15.6`, `GUIDE.md` "막혔을 때", `tools/import_draft.py` 안내 문구, `S0_PROBE_CHECKLIST.md` 갱신. 리뷰 문서에 "외부 리뷰 결과" 절, RF-2에서 `export_external.py` 제외하고 반입 staging/rollback 추가, RF-0·RF-1 범위 확장(DRAFT_NOTES 표).

## RF-2 반입 도구·경계 (2026-10-03)

- `tools/check_boundary.py` 추가: 사내 표식 패턴(비밀 키·토큰·공인 IP·15자리 숫자·허용 목록 밖 이메일/URL 호스트 + 사내 `docs/site/boundary-patterns.txt`), `plugin/scripts/**`의 SITE_PATHS 모듈 정적 import, 합성 표시 없는 로그 fixture, `--mode external`에서 SITE_PATHS 경로 존재. 예외 `tools/boundary-allow.txt` → `15-local-draft.md §15.4·§15.6`, `GUIDE.md §3·§4`, `01-architecture.md §3`.
- `tools/import_draft.py`: staging(해시 대조) → `--check-boundary` 검증 → 활성 전환(`os.replace`) → 해시 재대조, 실패 시 rollback. `SITE_PATHS` 파일은 기준선에서 뺀다(반입마다 기준선 동일). `export_external.py`는 만들지 않는다(결정 a).
- `plugin/schemas/`(이슈 DB 스키마 사본)와 `tools/sync_schemas.py --check|--write`. 사외 CI `.github/workflows/external.yml`.
- Phase 13 실패 후속: `triage.py`는 `year_source: jira`인데 Jira 발생 시각이 없으면 연도를 묻지 않고 로그 파일 시각 연도를 임시로 쓰고 경고한 뒤 시각 후보로 간다(`ask`면 선택지 제공) → `07-workflow.md` Step 3 입력 포맷. eval 22 로그를 CALL-001-01 양성 fixture로, eval 29·44 assertion을 현재 SKILL 규칙·`10-skill-eval.md` 설계에 맞춤.


## R8 점수 포화 동점 정렬 (2026-10-04)

- `match_signatures.py`: 후보 정렬 키를 `(-score, -(근접+키워드 bonus), 유형, 원인)`으로 바꿨다(`_rank_key`). S=C=1에서 score가 1.0으로 포화해도 발생 시각에 가까운 원인이 앞선다. score·confidence·bonus 값·회귀 모드(bonus 0, ID 순)는 불변. `04-parser-matching.md §5.11 (2)·(4)`, `contracts.md §3.2` 동기화.
- `triage.py` 리포트: "신뢰도" → "일치 수준 … — 진단 확신도 아님", 1위와 동점인 후보가 있으면 "순위 참고" 줄, 기타 후보는 `(규칙 일치 점수 N)`. `analysis.json` 필드는 불변. `07-workflow.md` Step 4·6 예시, `reference/db-authoring.md` 한 줄.
- 테스트: `test_full_match_ties_are_ordered_by_proximity`, `test_regress_order_unchanged_by_tiebreak`, `test_triage.py` 리포트 문구.

## 실패 스텝(선택 입력) (2026-10-04)

- 시험 절차·실패 스텝을 선택 입력으로 추가했다. 우선순위 `--failed-step` > Jira 필드 > 설명 > 시험 절차 텍스트(`jira.failed_step_patterns`) > `--steps-file`(txt/csv). 없거나 읽지 못해도 출력은 이전과 같다(질문·중단·새 키 없음). 점수·분류·회귀·검증에는 쓰지 않는 보조 정보다.
- 입력: `common/failedstep.py`, `jira_fields.py extract --failed-step/--steps-file`, `site-defaults`의 `field_map.test_steps/failed_step`·`failed_step_patterns`, 레지스트리 S22(S1~S22).
- 분석 보조: `triage.py`(같은 프로세스에서 마스킹, trace·state에 원문 없음, report·timeline 머리·후보 없음 힌트·request_hash), `match_signatures` 키워드 보너스 입력, `offline_eval` 라벨셋 `failed_step`.
- 누적: Jira 기록 `failed_step`(≤200자, v1 스키마에 직접 추가 — 반입 전이라 버전을 올리지 않음, `06 §6.4`), `db_add`·`db_lint`·`db_search`, 카테고리 README "자주 실패한 스텝".
- 테스트: `tests/test_failed_step.py`, `test_jira_fields.py`, `test_triage.py`, `test_match_signatures.py`, `test_db_build.py`, `test_db_lint.py`, `test_db_search.py`, `test_db_pr.py`.

## 실패 스텝 기준 원인 파악 (2026-10-04)

- 실패 스텝을 분석의 앵커로 쓴다: **어디를(시간 범위)·무엇을(우선 유형)** 정하고, **왜(S/C)** 는 로그 시그니처가 그대로 정한다. 모두 선택이며 쓰지 않으면 출력은 이전과 바이트 단위로 같다(trace.jsonl에 `3-markers` 한 줄이 더해질 수 있다).
- 구간: `parse_logcat.py markers`(스텝 마커 줄을 마스킹해서 수집, 패턴은 `site-defaults.yaml` `failed_step.marker_patterns`에서만)와 `parse --between`. `common/stepanchor.py`(FAIL 선택·시작 대체·창·clamp·steps-file 시각), `failedstep.find_line/group_key`. `triage.py` `step_anchor`: 앵커 우선순위 `anchor=off` > 로그 마커 > steps-file > Jira 시각 > 증상 시각 스캔, 로그 범위 밖이면 폐기하고 다음 출처로, Jira 시각과 `disagree_minutes` 넘게 다르면 경고, 근접 중심은 `JOB/match_meta.json`(`jira_meta.json`은 그대로), `analysis.step_anchor`·report·timeline·`request_hash`.
- 순위: `match_signatures` 스텝 기준 우선 유형(`bonus.step`, `step_focus`). 같은 스텝 Jira 기록이 `step_focus.min_records`건 이상이거나 `step_focus.map`에 맞으면 순위 키에만 `step_focus_bonus_max`(기본 0.05)를 더한다. score·confidence·S·C·회귀·검증은 불변. `issue-db.config.yaml`에 `scoring.step_focus_bonus_max`·`step_focus`(v1 직접 추가 — 반입 전이라 버전을 올리지 않음, `06 §6.4`), `db_lint` 검사.
- 테스트: `tests/test_step_anchor.py`, 합성 시나리오 `step-anchor`, 변형 DB `issue-db-step-focus`, `test_db_lint.py`.

## 스텝 순서로 실패 구간 정렬 (2026-10-04)

- **버그 수정**: `triage.py`가 steps-file(시험 장비) 시각을 단말 logcat 시각으로 그대로 써서, 시계 차가 있으면 로그 범위 안의 엉뚱한 구간이 조용히 잡혔다. 이제 시계 차(`--clock-offset`·`failed_step.clock_offset`)가 있을 때만 장비 시각을 쓰고, 모르면 경고(`장비 시각 미사용: 시계 정렬 불가(시계 차 모름)`)하고 쓰지 않는다. `stepanchor.parse_offset`, `step_anchor.clock {mode: manual|none}`. Jira 시각 불일치 경고는 구간을 바꾸지 않는다(steps_file·step_order에는 시계 차 힌트가 붙는다).
- 앵커 우선순위: `anchor=off` > `log_marker`(기본 꺼짐: `marker_patterns: []`, 실제 logcat에는 마커가 없다) > `steps_file`(수동 시계 차 필요) > **`step_order`(신규, 기본)** > `jira` > `symptom_scan`. 실패 스텝 문구는 모든 경우에 우선 유형·키워드·힌트에 쓴다.
- **스텝 목록 읽기**: `failedstep.read_source`(txt/csv/tsv·html·zip), `parse_steps`·`read_steps`·`label`. zip은 메모리에서만 읽고 후보 하나(`report.html` > 다른 html > csv/tsv/txt)만 고른다(절대·`..`·암호화·5 MiB 초과 거부). 시험은 첫 FAIL에서 멈추므로 첫 FAIL 행이 실패 스텝이다. **`resolve()` 변경**: `failed_step_patterns`가 먼저 맞고, 맞는 줄이 없으면 표의 FAIL 행(`번호 | 이름`, 출처 `steps_file`)으로 대신한다(표 머리가 있으면 그 앞의 요약 표는 패턴 검색에서 뺀다). `site-defaults`의 `failed_step`에 `clock_offset`·`steps_status`·`steps_columns`·`order` 추가(YAML `no`는 따옴표).
- **스텝 순서 정렬**: 이슈 DB `issue-db.config.yaml`의 `step_events`(메인테이너 관리, 순서 있는 규칙 목록: `event`·`ril`·`match`·`observable: false`)와 `db_lint` 새 코드 `step-event`. `parse_logcat.py markers --step-events`(규칙별 흔적, 라벨만, 스텝 이름은 인자로 안 받음), `stepanchor.order_walk`(가장 이른 흔적·커서 전진, 관측 불가·놓침, 반복 실행·상한 시 앵커 없음). 못 정하면 경고 `스텝 순서 정렬 안 함: <사유> — Jira 발생 시각 기준으로 분석했다`.
- 커맨드 `analyze`·`record`에 붙여넣기 안내(`WD/<KEY>/steps-pasted.txt` → `--steps-file`)와 `--clock-offset`.
- 테스트: `tests/test_step_order.py`, `test_step_anchor.py`(장비 시계 어긋남), `test_failed_step.py`(html·zip·붙여넣기), `test_db_lint.py`(`step-event`), 합성 시나리오 `step-order`, 변형 DB `issue-db-step-events`.
- 미룸: 시계 차 자동 추정, 중첩 zip, MCP 첨부 가져오기(`99-deferred.md`).

## 하위 스크립트 같은 프로세스 호출 (2026-10-04)

- `common/checks.run_script`(`db_pr`·`db_precommit`·`guard`가 쓰는 검사 단계)와 `db_verify._script`가 하위 스크립트를 subprocess 대신 같은 프로세스에서 `main(argv)`로 부른다(`run_in_process`). 계약은 같다: 반환값이 종료 코드, `SystemExit`는 그 코드(None은 0, 문자열은 stderr + 1), 그 밖의 예외(import 오류 포함)는 traceback을 stderr에 쓰고 1. stdout은 JSON으로 파싱한다. `env`를 주거나 `TT_SCRIPT_SUBPROCESS=1`이면 예전처럼 subprocess. `checks.py`의 top-level import는 그대로 stdlib와 `common.exitcodes`뿐이다(guard).
- `common/patterns.py`: 정규식 시간 상한용 작업 프로세스를 runner마다 spawn하지 않고 프로세스 안에서 공유한다. 본문은 runner가 처음 패턴을 돌릴 때 보내고, 다른 runner가 끼어들면 다시 보낸다. 시간 초과면 그 프로세스를 끝내고 다음 패턴에서 새로 띄운다(상한·`PatternTimeout` 동작 불변).
- 효과(이 컨테이너, 합성 샘플 DB): `stage` 한 번 6.9~10.8초 → 1.5~2.1초, `pytest tests/test_db_pr.py tests/test_checks.py` 418s → 138s.
- 테스트: `tests/test_inprocess.py`(종료 코드 계약, subprocess와 결과 일치, 작업 프로세스 재사용·본문 교체·시간 초과 후 재기동).

## db_add.py 분할 (2026-10-05)

- 동작·CLI·출력 동일. `db_add.py`(1,377줄)는 CLI만(112줄) 두고 구현을 `plugin/scripts/dbadd/`로 옮겼다: `core`(상수·오류·계획 읽기·검사·`Tree`), `applier`(`Applier`·`cmd_apply`, 임시 ID·fixture 이름·피드백), `ops/`의 op 메서드 믹스인 7개(`jira`·`entities`·`fix`·`resolution`·`signature`·`fixture`·`parser_rules`), `drift`, `ids`(check-ids·renumber), `similar`. 함수 본문은 그대로 옮겼고 바뀐 참조는 drift의 `Applier._rule_key` → `ParserRuleOps._rule_key` 하나다. `db_review`가 쓰는 `db_add.similarity`는 그대로 import된다.

## R7 근거 출처·R15 대용량 측정 (2026-10-05)

- **R7 `line_ref`/`event_index`** (`04-parser-matching.md §5.8 (6)`): 모든 이벤트의 마지막 키 `line_ref: {file_index, line_no}`(입력 로그 목록 순번, 1부터 센 물리 줄; 줄 위치를 모르면 `null`). 줄 레코드는 reference 백엔드가 채우고 builtin·파생(`source: rules`) 이벤트는 기준 줄의 값을 이어받는다. 외부 파서 이벤트는 `{file_index, line_no: null}`. site 백엔드가 키를 안 내도 `postprocess`가 `null`로 채운다. 정수뿐이다(경로·본문 없음, 이슈 DB에 안 감).
- 매처 근거에 `line_ref`와 `event_index`(입력 `events[]` 순번, `_range`가 안정 정렬 순열을 `ids`로 `Evaluator`에 넘김) 추가. `report.md` 근거 줄 끝에 ` (f<순번>:L<줄>)`. `analysis.json`은 그대로(근거 키 `{ts, tag, msg, event}`, `_ref`는 리포트 작성 뒤 지움).
- **`cut --evidence` 동작 변경**: 근거의 `line_ref`가 가리키는 줄이 입력에 있고 (시각, 태그)가 같으면 그 줄만 앵커로 삼는다. 그래서 같은 시각·태그의 다른 줄은 더 이상 앵커가 아니다(예전에는 모두 앵커). 못 쓰면 그 근거만 예전처럼 `(ts, tag)`로 찾고 경고 `evidence-ref-mismatch`(종료 코드 그대로, `parse`와 같은 로그를 같은 순서로 줘야 한다). 출력 `anchors_by: {line_ref, ts_tag}`. **버그 수정**: raw 줄을 `str.splitlines()`로 읽어 `\x0b \x0c \x1c-\x1e \x85` 등이 든 줄 뒤에서 원문이 어긋났다 → `read_file`과 같은 방식(`newline=""`, `rstrip("\r\n")`)으로 센다.
- 바뀌는 출력: 이벤트(`events.json`·스냅샷 `tests/fixtures/logs/*.events.json` 14개: `line_ref`만 추가), `match.json` 근거(+`line_ref`·`event_index`), `cut` JSON(+`anchors_by`, 경고), `report.md` 근거 줄. **바뀌지 않는 것**: 골든 JSON(`VOLATILE_FIELDS = ("line_ref",)`로 비교에서 제외, 키 유무는 `test_backend_emits_line_ref`), `analysis.json`, score·S/C·정렬, 회귀·검증 결과, 종료 코드. 합성 로그 34개(`tests/fixtures/logs`·샘플 DB fixture)의 `parse --full --mask`·`match --regress`·분석 모드·`cut --evidence` 출력을 변경 전후로 비교해 새 키(`line_ref`·`event_index`·`anchors_by`)를 빼면 같음을 확인했다.
- **R15 측정** `tools/bench_scale.py`(커밋, pytest가 모으지 않음): 합성 로그 10k·50k·200k줄(단일)·50k(2파일), 단계별 시간·최대 RSS·events.json 크기, `_search_window`·`find-symbol` 마이크로. 임계값을 넘은 것만 적용했다.

| 항목 (이 컨테이너, 합성 로그) | 전 | 후 | 적용 |
|---|---|---|---|
| O1 `_search_window` K=8000 evaluate / evaluate_all (K=2000 → 8000 증가 배율 16배) | 23.2 s / 23.7 s | 0.17 s / 0.30 s | 적용 (> 1.0 s, 배율 > 6) |
| 200k줄 `match --regress` | 3.9 s | 2.3 s | O1 효과 |
| O2 200k coverage / parse_e2e | 1.82 s / 20.96 s (8.7%) | — | 미적용 (< 15%) |
| O3 200k masker_init / 최대 RSS(parse 직후) | 0.04 s (0.2%) / 390 MB (입력의 26배) | (줄 단위 observe 시험: 0.09 s / 424 MB) | 미적용 — RSS 규칙(> 10배)은 넘었지만 RSS는 이벤트 dict가 지배하고 줄 단위 observe는 줄이지 못했다(masker_init은 약간 느림). 시험 뒤 되돌림 |
| O4 `find-symbol` 20k 파일 `Foo#bar` / `bar` | 3.13 s / 3.80 s | 0.81 s / 0.67 s | 적용 (> 3 s) |
| R7 오버헤드: 200k parse_e2e / events.json | 20.96 s / 61.8 MB | 21.42 s (+2%) / 75.4 MB (+22%) | 기준 이내 (≤10%, ≤25%) |

- 테스트(+12, 전체 489개): `test_parse_logcat`(`line_ref` 줄 일치·다중 파일 순번·외부/builtin), `test_match_signatures`(`event_index`·섞인 입력·같은 시각·태그), `test_signatures_window`(예전 구현 사본과 무작위 300건 비교·구간 경계), `test_masking`(cut 줄 위치 앵커·불일치 대체·`\x0c` 정렬), `test_golden`, `test_triage`, `test_code_roots`(예전 구현과 비교).
- 미룸: 파생 이벤트 `msg` 복사 제거, `common/events.py`(`line_ref` 포함해야 함), `analysis.json`에 줄 위치, 백엔드가 주는 줄 번호, find-symbol 범위 제한·색인, GB급 스트리밍·`events.json` 크기, `cut --events`, 사내 임계값 재보정(S-5), `db_regress.compare_events`의 `line_ref`.

## CLAUDE.md 축소 (2026-10-05)

- `CLAUDE.md` 13,640 → 3,613바이트(≤4KB, 매 세션 로드). 남긴 것: `@SITE_PROFILE.md` import, 목적 한 줄, 머리말(모드 판별 5규칙·번호 유지, 모드 표, import 대체), 작업 방식 요약, "항상 지킬 것" 7줄. 내용은 지우지 않고 옮겼다:

| 이전 `CLAUDE.md` | 새 위치 |
|---|---|
| §12 원칙 | `docs/design/12-principles.md` (원본 12장, 새 파일) |
| 문서 지도, "진입점·짧게 유지" 문단 | `docs/design/README.md` (새 파일) |
| §11.0 작업 방식, 머리말의 플러그인 규격 확인 문단 | `11-phases.md §11.0` ("테스트용 이슈 DB" 문단은 기존 절에 합침) |
| §1 목적과 범위 | `01-architecture.md §1` |
| 머리말의 "사내 자료 없이 작성", placeholder·데이터 스택·Ubuntu 문단 | `14-site.md §14.1` |

- 참조 갱신: `CLAUDE.md §12`/`12장` → `12-principles.md`(07·10·11 Phase 13·AGENTS·GUIDE·HTML 안내서·리뷰 문서), `CLAUDE.md §11.0` → `11-phases.md §11.0`(테스트 헬퍼), 문서 지도 → `docs/design/README.md`(14 §14.4). S-1 "읽을 것"에 `12-principles.md` 추가. `CLAUDE.md` 머리말을 가리키는 참조는 그대로 유효. `docs/history/`의 옛 참조는 고치지 않는다(이 표로 찾는다).

## 트리거 측정 (2026-10-05)

- skill-creator `run_loop`(질문 24개, train 15·test 9, 3회, 5반복): 현재 description과 개선안 모두 recall 0~20%, precision 100%. 원인은 측정기다: `run_eval`은 스킬을 임시 커맨드로 넣고 **첫 도구 호출**만 세는데, 로그 분석 요청에서 Claude는 먼저 `ls`로 로그를 찾는다.
- 실제 플러그인 측정 `tests/skill_evals/trigger_real.py`(`claude -p --plugin-dir plugin`, 처음 4번의 도구 호출 안에 `Skill`): 현재 description과 개선안 모두 recall 100%(14/14)·precision 100%(오트리거 0/10), 질문당 2회. **description은 바꾸지 않았다**(`SKILL.md` 8,191바이트 그대로). 이전 기록의 recall 26~33%는 같은 측정기 결과다.
- `10-skill-eval.md` 트리거 절에 측정 방법을 적었다.

## 스킬 eval 보강·마찰 수정 (2026-10-05)

- eval 46~50 추가(batch E, 총 50개): 46 후보 없음 탐색 분석(`timeline.md`만 읽음), 47 `--explore` 원인 미확인 보류(슬롯 차이 반대 근거), 48 Jira 실패 스텝 필드 → `jira.failed_step`·README "자주 실패한 스텝 (3건)", 49 붙여넣은 스텝 목록 → `steps-pasted.txt` → `step_order`, 50 두 버퍼 로그 → 근거 줄 `(f<n>:L<m>)`·`cut --evidence` 같은 순서. 채점(`grade.py`)에 `tool_uses`·`opened`(Read·Bash 읽기로 연 파일) 추가. 환경 빌더에 `split_buffers: true`(`<as>.main.log`·`<as>.radio.log`).
- eval 7: 근거 줄(DATA-001-02 거부 줄)에 IMSI·전화번호를 넣어 리포트 근거의 `<IMSI#n>`·`<MSISDN#n>` 토큰 표기를 확인한다. 탐색 분석 질문에 '아니오'로 답하는 규칙을 eval 2·3·4·44·45에 추가.
- `allow_cause_drafts`: `type_dir` 제거(plan 스키마 `additionalProperties: false`), `--draft`/`judge --plan --draft`에서는 새 원인을 계획 `temp_id`로 낸다(`_retemp_drafts`) — 초안을 그대로 계획에 붙인다. `reasons`의 문자열 메시지는 실제 ID 그대로.
- `verify-resolution`: op의 `verification`에는 `status`를 넣지 않는다(스키마가 거부, 적용 결과가 `verified`). `db-authoring.md`·`record.md`·`verify.md`·`contracts.md` 수정.
- SKILL.md 붙여넣기 줄: `--steps-file <path|붙인 목록→JOB/steps-pasted.txt>`. 같은 크기를 맞추려 문구 두 곳을 줄였다(skill-creator 소유 파일, 최소 수정).
- 시각 질문(`time`)에 시계 이상(역행·점프) 경고를 덧붙인다(Jira 발생 시각 없음 경로, `coverage.clock_anomalies`).
- DRAFT_NOTES ✅1 상세(10/04 보안 검토): 10/04 완료. 고친 것: 붙여넣은 스텝 원문 `steps-pasted.txt`가 discard·release 뒤에도 남음 → `db_pr` discard·`lock release`(--force 아님)·cleanup이 지움. 문제없음: zip(메모리만, 선언·실제 크기 상한, 암호화·절대/`..` 거부, 멤버 하나), html 5 MiB, 정규식 타임아웃, 스텝 이름·zip 경로·마커 마스킹, 첨부 문장은 데이터(SKILL·explore)
- B 실행 결과: (검토자가 채움)

## 실패 스텝 표기 통일 (2026-10-05)

- `failedstep.from_text`(Jira 설명·시험 절차·steps-file 패턴 검색): 패턴이 이름만 뽑아도 맞은 줄이 스텝 번호로 시작하면(`Step 7 …`·`7 | …`·`7. …`) `7 | 이름`으로 낸다. 전에는 붙여넣은 목록·설명에서는 `데이터 연결 확인`, Jira 필드·report.html 표에서는 `7 | 데이터 연결 확인`이라 README "자주 실패한 스텝"이 두 줄로 갈렸다. 번호 없는 줄(`실패 스텝: X`)은 그대로. `find_line`(스텝 기준점 쪽)은 바꾸지 않았다. 판정(S/C)·회귀·검증에는 영향 없음.
- 테스트 `test_failed_step.py` 기대값을 새 표기로, `test_numbered_label_matches_table_and_field` 추가. eval 49 기대값 `7 | 데이터 연결 확인`.
