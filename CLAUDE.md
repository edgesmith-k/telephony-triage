@SITE_PROFILE.md

# Telephony Triage Plugin — 개발 컨텍스트

> **작업 모드를 먼저 판별한다** (`docs/design/15-local-draft.md`). 아래 순서로 처음 맞는 것을 쓴다:
> 1. **사용자가 모드를 말하면** 그 모드. ("사외 초안", "사내 보완", "사내 처음부터")
> 2. **`SITE_PROFILE.md`가 있으면 사내 모드.** 그 파일의 "진행 상태"에 적힌 모드(사내 보완 / 사내 처음부터)와 단계에서 이어간다.
> 3. **`.local-draft`가 있으면 사외 초안 모드.** 사외 PC에만 두는 표식 파일이다(`.gitignore`에 등록, 반입하지 않음, `15-local-draft.md §15.2`). `DRAFT_NOTES.md`의 "진행 상태"에서 이어간다.
> 4. **`DRAFT_NOTES.md`만 있으면 묻는다**: "사외 초안을 계속할까요, 사내 보완(S-1)을 시작할까요?" (`DRAFT_NOTES.md`는 반입 때 사내로 같이 가므로 이것만으로 판별하지 않는다.) 사외 초안을 고르면 `.local-draft`를 만든다. 사내 보완을 고르면 S-1에서 `SITE_PROFILE.md`를 만들고 진행 상태에 "모드: 사내 보완"을 적는다.
> 5. **모두 없으면 묻는다**: 사외 초안(Phase D0, 시작할 때 `.local-draft`를 만든다) / 사내 처음부터(Phase 0).
>
> | 모드 | 시작 | 읽을 것 | 진행 상태 기록 | 하지 않는 것 |
> |---|---|---|---|---|
> | 사외 초안 | Phase D0 → 1~13 | `docs/design/11-phases.md`의 **그 Phase 절**과 그 Phase의 "읽을 문서" | `DRAFT_NOTES.md` | Phase 0, 14 |
> | 사내 보완 | S-1~S-7 (`15-local-draft.md §15.5`. S-7 = 배포·파일럿) | `15-local-draft.md §15.5`의 단계별 "읽을 것"만 | `SITE_PROFILE.md` | **Phase 0, D0, Phase 1~13 재실행, `11-phases.md`·문서 전체 읽기** |
> | 사내 처음부터 | Phase 0 → D0 → 1~14 | `11-phases.md`의 그 Phase 절과 "읽을 문서" | `SITE_PROFILE.md` | — |
>
> - 위 import가 동작하지 않는 환경이면(S1) 세션 시작 시 `SITE_PROFILE.md`를 먼저 읽는다.
> - 이 파일은 진입점이다. 설계 상세는 `docs/design/`에 있다. 플러그인 개발 레포 루트에 `CLAUDE.md`로 둔다 (배포되는 `plugin/` 폴더 밖). 매 세션 로드되므로 짧게 유지한다. Phase 상세는 `11-phases.md`에만 둔다.
> - **이 문서 세트는 사외에서 사내 자료 없이 작성됐다.** 사내에서는 모드에 따라 **사내 보완이면 S-1**(`15-local-draft.md §15.5`), **사내 처음부터면 Phase 0**(`14-site.md`)으로 사내 환경을 먼저 확인한다.
> - 이 문서에 나오는 logcat 태그, 로그 문구, RIL 요청 이름, 코드 심볼, 서버·팀 이름은 **예시(placeholder)** 다. 사내에서(S-1~S-4 또는 Phase 0) 실제 Android 16/17 logcat·소스·사내 환경으로 확인하고 반영한다. 단, 데이터 스택 태그는 Android 13+ 형식(`DNC-<n>`, `DN-…`, `DPM-<n>`, `DRM-<n>`, `DSM-<n>`, `DCM-<n>`, `DSRM-<n>`)으로 확정이며, 레거시 데이터 스택(DcTracker/DCT 등)은 고려하지 않는다. 실행 환경은 **Ubuntu**다(`01-architecture.md §3`).
> - Claude Code 플러그인 규격(디렉토리 구조, `plugin.json`/`marketplace.json` 필드, hooks 스키마와 권한 결정 필드, 커맨드와 스킬의 관계, `${CLAUDE_PLUGIN_ROOT}` 치환, MCP 도구 이름 형식, 로컬 플러그인 로드 방법)과 GHE Actions 문법은 버전에 따라 바뀔 수 있다. **구현 전에 최신 공식 문서로 확인하고, 사내에서 공식 문서에 접근할 수 없으면 빈 플러그인 실험(S1)으로 확인한다.** 이 문서와 다르면 확인 결과를 따르고 차이를 사용자에게 보고한다.

---

## 1. 목적과 범위

Android Telephony 이슈 도구. Jira 이슈와 logcat을 받아 원인·해결책을 분석하고, 결과를 **카테고리 > 이슈 유형(증상) > 원인**으로 사내 GitHub 이슈 DB 레포(`telephony-issue-db`)에 누적한다. 팀원들이 같은 DB에 계속 기여하며 시그니처 품질과 해결 상태를 관리한다.
v1 범위: logcat(radio/main/system/crash, bugreport는 logcat 섹션만) · Jira **읽기 전용** · GHE 브랜치+PR(main 직접 push 금지) · CI 없음(`ci_mode: local`) · 카테고리 data/call/network/sim/sms/ims · 사용자별 한 번에 한 작업. 제외: CP 로그 파싱, Jira 쓰기, 3-way replay. 상세 표는 `GUIDE.md §1`.

---

## 문서 지도

설계 문서는 `docs/design/`에 있고 `파일명 §절`로 참조한다. **표·정의가 다르면 `contracts.md`가 맞다**(다른 파일에 표를 복사하지 않는다). 각 Phase가 읽을 문서는 `11-phases.md`가 지정하므로 아래는 찾아갈 때만 쓴다.

| 파일 | 내용 |
|---|---|
| `contracts.md` | **공통 계약 단일 원본**: 스크립트 CLI·`--db`·lock·종료 코드·작업 계획/op/drift·fixture·브랜치·renumber·상태 값·기존 자산 연결 |
| `01-architecture.md` | 레포 2개, 플러그인 레포 구조, 스크립트 책임 매트릭스 |
| `02-config.md` | 사용자 config·setup, `issue-db.config.yaml` |
| `03-issue-db.md` | 분류·카테고리 경계, 디렉토리·파일 형식·규칙·README·해결 상태·연관 |
| `04-parser-matching.md` | 파서 규칙, 매칭 점수·회귀 모드 |
| `05-verification.md` | 검증 R1~R6, 수동 기록·해결책·verify-fix 검증 |
| `06-collaboration.md` | CODEOWNERS, PR 규칙, 검증 체계·sync-pr·사후 정리, 스키마 버전, 피드백·리뷰·통계·용어집·새 카테고리 |
| `07-workflow.md` | analyze Step 0~8, 공통 쓰기 절차, record/validate/fix-submitted/verify-fix/sync-pr |
| `08-safety.md` | 마스킹, Hooks 8종 |
| `09-commands.md` | 커맨드 12개 |
| `10-skill-eval.md` | SKILL.md 구성, 트리거 테스트, eval 45개 |
| `11-phases.md` | **Phase D0~14** 할 일·완료 기준·읽을 문서 (사외 초안·사내 처음부터 모드만) |
| `13-actions.md` | GHE Actions 전환 |
| `14-site.md` | 사내 적용: placeholder 레지스트리 S1~S21, `SITE_PROFILE.md` 형식, Phase 0, 사외 문서 반영 |
| `15-local-draft.md` | 사외 초안↔사내 보완: 모의 환경, 반입 체크리스트, **S-1~S-7**, `site-defaults.yaml` 필수, 재반입 |
| `16-existing-assets.md` | 기존 Jira MCP 재사용, 기존 파서 포팅(골든), 기존 분류 import, 분석 스킬 연결 |
| `99-deferred.md` | v1에서 뺀 설계. **어느 Phase에서도 읽지 않는다** |
| `GUIDE.md` (루트) | 사람용 총정리 |
| `REVIEW-OPEN.md` (루트) | 사내 정보가 있어야 판단할 미해결 항목 (S-1 / Phase 0에서 처리) |
| `DRAFT_NOTES.md` (루트) | 사외 초안 **상태 파일(≤8KB)**: 진행 상태·막힌 것·활성 트랙. 상세 이력은 `docs/history/`(읽지 않는다) |
| `docs/development/` | 리뷰·인계 문서(`ARCHITECTURE_REVIEW_2026-10.md` RF 계획, `PLUGIN_IMPROVEMENT_HANDOFF.md`, `S0_PROBE_CHECKLIST.md`) |

- `07-workflow.md §Step 8-5`는 "Step 8의 5번 항목". `§record`처럼 워크플로우 이름은 `07-workflow.md`의 `##` 절.
- 변경 이력은 `docs/history/CHANGES.md`.

---

## 11.0 작업 방식 (Claude Code가 지킬 것)

- **머리말의 모드 표에 따른 시작점부터** Phase(또는 S 단계) 단위로 진행한다. 사외 초안·사내 처음부터 모드에서는 각 Phase를 시작할 때 `11-phases.md`의 그 Phase 절과 "읽을 문서"를 읽는다 (항상 `contracts.md` 포함). 사내 보완 모드(S 단계)에서는 `15-local-draft.md §15.5`의 그 단계 "읽을 것"만 읽는다. Phase(단계)가 끝날 때마다 완료 기준을 점검하고 결과를 요약한 뒤 사용자 확인을 받는다. 확인을 받아야 다음으로 넘어가고, 모드에 맞는 파일(사외 초안 `DRAFT_NOTES.md`, 사내 `SITE_PROFILE.md`)의 "진행 상태"를 갱신한다.
- 각 Phase의 완료 기준은 **그 시점까지 만든 것만으로** 확인할 수 있게 짜여 있다. 뒤 Phase의 기능이 필요하면 멈추고 보고한다.
- 역할 분담:
  - 플러그인 뼈대, 스크립트, 커맨드, Claude hooks, git hooks: Claude Code가 직접 구현한다.
  - `skills/telephony-triage/SKILL.md`와 `reference/`: **skill-creator 스킬**로 작성하고 eval로 검증한다 (Phase 13, 모든 스크립트가 끝난 뒤).
- 플러그인 규격, hooks 스키마, GHE Actions 문법은 구현 전에 최신 공식 문서로 확인한다. 사내에서 외부 공식 문서에 접근할 수 없으면 **빈 플러그인 실험(S1)** 으로 대체하고 결과를 `SITE_PROFILE.md`에 기록한다.
- 사내 확인값은 `SITE_PROFILE.md`에만 쓴다. 이 문서 세트에는 쓰지 않는다 (`14-site.md §14.1`).
- 모든 테스트 로그는 마스킹된 fixture만 쓴다.
- Claude Code 세션은 **플러그인 레포 루트에서 연다** (이 `CLAUDE.md`가 로드되도록). 이슈 DB 레포는 절대 경로로 다룬다.
- 테스트용 이슈 DB(합성 샘플 `tests/fixtures/issue-db-sample/`, 오류 주입·0건 카테고리·리뷰 케이스 등 변형)는 모두 플러그인 레포 `tests/fixtures/issue-db-*/`에 둔다. 반입·운영용 이슈 DB는 샘플 없는 **뼈대**만 `tools/make_db_skeleton.py`로 만든다 (`11-phases.md` Phase 1).

---

## 12. 원칙

- 분류 확정, 새 유형/원인 생성, 시그니처와 파서 규칙 추가, 수정 상태 변경은 **항상 사용자 확인 후** 진행한다.
- GitHub push 전에는 **변경 파일, ID 할당, README 미리보기, diff, 검사·검증 결과(실행/건너뜀과 사유), 커밋 메시지를 보여주고 승인받는다** (`07-workflow.md §Step 8`의 5번). 승인 없이는 push하지 않고, 승인 후 파일이 바뀌면 다시 승인받는다.
- 도구가 만드는 이슈 DB 변경은 **작업 계획을 최신 main 위에 적용**하는 방식으로만 만들고, 절차는 `db_pr.py`가 한다. 텍스트 rebase로 병합하지 않는다. 계획이 건드리는 대상이 그사이 main에서 바뀌었으면(drift) 자동으로 덮지 않고 사용자에게 묻는다 (`contracts.md §작업 계획`). 예외: 스키마 마이그레이션·새 카테고리·사후 정리는 계획 op로 표현할 수 없으므로 메인테이너가 자기 로컬 브랜치에서 직접 편집한다 (`06-collaboration.md §6.3·6.4·6.10`).
- **사용자의 이슈 DB clone은 브랜치도 파일도 바꾸지 않는다.** 분석은 읽기 스냅샷(`<work_dir>/_snapshot`), 쓰기는 작업 worktree와 도구 브랜치(`tt/*`)를 쓴다. 사용자 clone에는 fetch와 조건부 `pull --ff-only`만 한다. 유일한 명시적 예외는 메인테이너가 `migrate/schema-v<N>` 브랜치에서 실행하는 `migrate` 커맨드다(그 브랜치의 워킹 트리를 바꾼다).
- 다른 유형의 fixture에서 새 시그니처가 걸리면(R3·R4) 시그니처를 좁힐지 `also_allowed`로 허용할지 **사용자가 고른다**. 몰래 좁히거나 몰래 허용하지 않는다 (`contracts.md §fixture`).
- 사용자별로 **한 번에 한 작업**만 스냅샷을 옮기거나 worktree를 만든다(세션 lock). 작업이 끝나는 모든 경로에서 lock을 푼다 (`contracts.md §3.2` `db_pr.py` 세부).
- 생성 파일(README, STATS, CHANGELOG)은 `db_build.py`로만 만들고 직접 편집하지 않는다. 캐시는 커밋하지 않는다. Jira 한 건은 파일 하나다.
- 머지 전 main이 바뀌었으면 `sync-pr`로 다시 맞춘다 (계획이 있는 PR은 계획 재적용, 직접 편집한 브랜치는 사용자가 재동기화, `06-collaboration.md §6.3`).
- ID는 main에 들어간 뒤에는 바꾸지 않는다. **유일한 예외**는 머지 간격으로 main에 같은 ID가 두 번 들어온 경우의 사후 정리(메인테이너, `06-collaboration.md §6.3`)다. 병합·폐기는 `status`로 처리하고 삭제하지 않는다.
- Jira는 허용된 읽기 도구만 쓴다.
- 로그 원문은 필요한 구간만 읽는다. 매칭과 이슈 DB에는 마스킹된 텍스트만 쓴다. 이슈 DB에는 마스킹된 최소 예시와 fixture만 남긴다.
- 분석 리포트에서 로그로 확인한 사실과 코드 기반 추정을 구분한다. placeholder 규칙으로 얻은 결과는 그렇다고 밝힌다.
- 수동 기록(`record`)은 로그·코드 분석과 매칭만 건너뛰고, 쓰기 경로와 검증은 analyze와 같다. 확인 화면과 PR에 "수동 기록"을 밝힌다.
- 규칙·해결책 변경은 `05-verification.md §5.12 (1)` 검증을 통과해야 올린다. 건너뛴 검증(`skipped`)은 통과로 표시하지 않는다. `fixed`는 시나리오 흔적이 있는 `verify-fix` 통과로만 기록한다. 검증되지 않은 해결책은 미검증으로 표시한다.
- 분류·회귀·검증의 기준은 결정적인 스크립트 출력(파서 이벤트, 시그니처 매칭)이다. 카테고리 분석 스킬(LLM)의 결과는 리포트 보조 정보로만 쓴다.
- 사내 코드와 값은 `SITE_PATHS` 경로에만 두고, 재반입은 `tools/import_draft.py`로 한다 (통째로 교체하지 않는다). 런타임 코드는 사내/사외 모드를 판별하지 않는다: `plugin/site-defaults.yaml`이 없으면 멈추고, example은 테스트 헬퍼만 쓴다 (`15-local-draft.md §15.1`).
- git 충돌, 인증 실패, MCP 부재, 스키마·생성기·파서 백엔드·외부 파서 버전 불일치는 자동으로 우회하지 않고 사용자에게 보고한다.
