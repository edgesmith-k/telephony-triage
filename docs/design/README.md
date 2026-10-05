# 설계 문서 지도

> 이전 `CLAUDE.md`의 "문서 지도". `CLAUDE.md`(루트)는 진입점이다. 플러그인 개발 레포 루트에 둔다(배포되는 `plugin/` 폴더 밖). 매 세션 로드되므로 ≤4KB로 짧게 유지한다. Phase 상세는 `11-phases.md`에만 둔다.

설계 문서는 `docs/design/`에 있고 `파일명 §절`로 참조한다. **표·정의가 다르면 `contracts.md`가 맞다**(다른 파일에 표를 복사하지 않는다). 각 Phase가 읽을 문서는 `11-phases.md`가 지정하므로 아래는 찾아갈 때만 쓴다.

| 파일 | 내용 |
|---|---|
| `contracts.md` | **공통 계약 단일 원본**: 스크립트 CLI·`--db`·lock·종료 코드·작업 계획/op/drift·fixture·브랜치·renumber·상태 값·기존 자산 연결 |
| `01-architecture.md` | §1 목적과 범위, 레포 2개, 플러그인 레포 구조, 스크립트 책임 매트릭스 |
| `02-config.md` | 사용자 config·setup, `issue-db.config.yaml` |
| `03-issue-db.md` | 분류·카테고리 경계, 디렉토리·파일 형식·규칙·README·해결 상태·연관 |
| `04-parser-matching.md` | 파서 규칙, 매칭 점수·회귀 모드 |
| `05-verification.md` | 검증 R1~R6, 수동 기록·해결책·verify-fix 검증 |
| `06-collaboration.md` | CODEOWNERS, PR 규칙, 검증 체계·sync-pr·사후 정리, 스키마 버전, 피드백·리뷰·통계·용어집·새 카테고리 |
| `07-workflow.md` | analyze Step 0~8, 공통 쓰기 절차, record/validate/fix-submitted/verify-fix/sync-pr |
| `08-safety.md` | 마스킹, Hooks 9종 |
| `09-commands.md` | 커맨드 12개 |
| `10-skill-eval.md` | SKILL.md 구성, 트리거 테스트, eval 54개 |
| `11-phases.md` | **Phase D0~14** 할 일·완료 기준·읽을 문서 (사외 초안·사내 처음부터 모드만) + **§11.0 작업 방식** |
| `12-principles.md` | 원본 12장 **원칙**: 사용자 확인, push 전 승인, 작업 계획·drift, 사용자 clone 불변, lock, 생성 파일, ID, 마스킹, 검증 표시, 판정 기준, 우회 금지 |
| `13-actions.md` | GHE Actions 전환 |
| `14-site.md` | 사내 적용: placeholder 레지스트리 S1~S22, `SITE_PROFILE.md` 형식, Phase 0, 사외 문서 반영 |
| `15-local-draft.md` | 사외 초안↔사내 보완: 모의 환경, 반입 체크리스트, **S-1~S-7**, `site-defaults.yaml` 필수, 재반입 |
| `16-existing-assets.md` | 기존 Jira MCP 재사용, 기존 파서 포팅(골든), 기존 분류 import, 분석 스킬 연결 |
| `99-deferred.md` | v1에서 뺀 설계. **어느 Phase에서도 읽지 않는다** |
| `CLAUDE.md` (루트) | 진입점: 모드 판별(머리말), 작업 방식 요약, 항상 지킬 것 |
| `GUIDE.md` (루트) | 사람용 총정리 |
| `REVIEW-OPEN.md` (루트) | 사내 정보가 있어야 판단할 미해결 항목 (S-1 / Phase 0에서 처리) |
| `DRAFT_NOTES.md` (루트) | 사외 초안 **상태 파일(≤8KB)**: 진행 상태·막힌 것·활성 트랙. 상세 이력은 `docs/history/`(읽지 않는다) |
| `docs/development/` | 리뷰·인계 문서(`ARCHITECTURE_REVIEW_2026-10.md` RF 계획, `PLUGIN_IMPROVEMENT_HANDOFF.md`, `S0_PROBE_CHECKLIST.md`) |

- `07-workflow.md §Step 8-5`는 "Step 8의 5번 항목". `§record`처럼 워크플로우 이름은 `07-workflow.md`의 `##` 절.
- 변경 이력은 `docs/history/CHANGES.md`.
