# 14. 사내 환경 적용 (사내 Claude Code가 먼저 읽을 것)

> 원본 14장. Phase 0의 절차가 이 파일에 있다.

### 14.1 배경과 원칙

- 이 문서 세트(`CLAUDE.md` + `docs/design/*.md`)는 **사외에서, 사내 로그·Jira MCP·GHE·소스 트리에 접근하지 못한 상태로** 작성됐다. 구조와 절차는 확정이지만, 사내 환경에 따라 달라지는 **값·문구·형식**은 추정(placeholder)이다. 사내에서는 모드에 따라 **사내 보완이면 S-1**(`15-local-draft.md §15.5`), **사내 처음부터면 Phase 0**(14.4)으로 사내 환경을 먼저 확인한다.
- 이 문서 세트에 나오는 logcat 태그, 로그 문구, RIL 요청 이름, 코드 심볼, 서버·팀 이름은 **예시(placeholder)** 다. 사내에서(S-1~S-4 또는 Phase 0) 실제 Android 16/17 logcat·소스·사내 환경으로 확인하고 반영한다. 단, 데이터 스택 태그는 Android 13+ 형식(`DNC-<n>`, `DN-…`, `DPM-<n>`, `DRM-<n>`, `DSM-<n>`, `DCM-<n>`, `DSRM-<n>`)으로 확정이며, 레거시 데이터 스택(DcTracker/DCT 등)은 고려하지 않는다. 실행 환경은 **Ubuntu**다(`01-architecture.md §3`).
- 사내 자료는 밖으로 가져갈 수 없으므로, 사외에서 문서를 계속 다듬고 사내에서 보완하는 일이 반복된다. 그래서 **사내 확인값은 이 문서 세트에 쓰지 않고 `SITE_PROFILE.md`에 따로 둔다.**
  - 사외에서 새 버전의 문서 세트를 가져와 통째로 덮어써도 사내 확인값이 사라지지 않는다.
  - `CLAUDE.md` 맨 위의 `@SITE_PROFILE.md` import로 매 세션 자동으로 읽힌다. import 동작은 S1에서 확인하고, 동작하지 않으면 세션 시작 시 `SITE_PROFILE.md`를 먼저 읽도록 `CLAUDE.md` 머리말 규칙으로 대신한다.
- **값의 우선순위**
  1. **런타임 값의 원본은 이슈 DB(`issue-db.config.yaml`, `parser-rules/`, type.md)와 사용자 config**다. 코드는 사내 값을 하드코딩하지 않고 여기서 읽는다.
  2. `SITE_PROFILE.md`는 그 **초기값을 정한 근거**와 **설계 변경 기록**이다. 런타임 값과 SITE_PROFILE이 다르면(누가 이슈 DB PR로 바꾼 경우) 런타임 값이 맞고, SITE_PROFILE에 변경 이력을 추가한다.
  3. 문서 세트의 placeholder·예시와 `SITE_PROFILE.md`가 다르면 **`SITE_PROFILE.md`가 우선**이다.
- `SITE_PROFILE.md`는 플러그인 레포(사내 전용) 루트에 둔다. 사내 서버 주소, 도구 이름, 로그 문구 등 사내 정보가 들어가므로 사외로 반출하지 않는다.
- 사내 확인 결과 **설계 자체를 바꿔야 하면**(예: Jira MCP가 발생 시각을 주지 않음, 사내 Claude Code가 플러그인 hook을 지원하지 않음, git worktree 사용 불가) 임의로 바꾸지 말고 대안을 제시해서 사용자 결정을 받는다. 결정은 `SITE_PROFILE.md`의 "설계 변경" 절에 기록한다. 사외 문서에 반영할 필요가 있으면 사내 정보를 뺀 일반화된 문장으로 사용자에게 요약해준다 (사용자가 사외로 옮길 수 있게).
- 플러그인 규격·hooks 스키마 등은 공식 문서로 확인한다. **사내에서 외부 공식 문서에 접근할 수 없으면 빈 플러그인 실험(S1)으로 대체**하고, 실험 결과를 근거로 기록한다.

### 14.2 확인 대상 목록 (placeholder 레지스트리)

| # | 항목 | 문서 위치 | 사내에서 확인하는 방법 | 반영 위치 (반영 Phase) |
|---|---|---|---|---|
| S1 | 사내 Claude Code 버전과 지원 기능: 플러그인, 마켓플레이스 하위 폴더 source, 커맨드/스킬 관계, hooks(PreToolUse, SessionStart), 권한 결정 필드(`allow`/`deny`/`ask`), **스킬/커맨드 본문 실행 시 `${CLAUDE_PLUGIN_ROOT}` 치환 여부**, **플러그인 hook에 전달되는 MCP 도구 이름 형식**(`mcp__<server>__<tool>`), hook matcher 정규식(`mcp__.*`) 지원, **`CLAUDE.md`의 `@파일` import 동작**, **커맨드 frontmatter `model` 지원 여부**(verify-fix·explore를 특정 모델로 고정; 확인 전엔 사용자가 `/model`로 고른다), **PreToolUse `Read` matcher**(로그 원문 읽기 차단, `99-deferred.md` E) | `01-architecture.md §3`, `08-safety.md §9`, `09-commands.md §10`, `CLAUDE.md` 머리말 | 사내 Claude Code 문서/버전 확인. 외부 공식 문서에 접근할 수 없으면 **빈 플러그인 실험**: 스킬·커맨드·hook 하나씩 가진 최소 플러그인을 로컬 로드해서 각 항목을 시험하고 결과를 기록 | 플러그인 구조, `hooks.json`, 스크립트 호출 방식 (Phase 1, 8, 12) |
| S2 | 플러그인 배포 방식: 사내 마켓플레이스 유무, 등록 절차 | `01-architecture.md §3`, Phase 14 | 사내 가이드 확인, 담당 부서 문의 | `marketplace.json`, getting-started (Phase 14) |
| S3 | Jira MCP: 서버 이름, 도구 목록, 읽기 도구, **논리 동작 매핑(`jira.tools`)**, 사용자 범위 등록 여부, 팀별 MCP 구현 차이, **플러그인 hook에서 보이는 도구 이름 형식** | `02-config.md §4`, `08-safety.md §9` | MCP 도구 목록 조회, S1의 실험 플러그인 hook으로 실제 전달되는 도구 이름 기록 | config `jira.*` 기본값 (Phase 6), `guard.py` (Phase 8) |
| S4 | Jira 필드 매핑: 발생 시각, 모델, SW, Android 버전, 캐리어가 어느 필드(커스텀 필드 포함)에 있는지. **발생 시각의 형식과 타임존** | `02-config.md §4`, `07-workflow.md §Step 2` | 사용자가 고른 샘플 Jira 2~3건을 읽기 도구로 조회 | config `jira.field_map`, `jira.timezone` (Phase 6) |
| S5 | GHE: 호스트, org, 팀 이름, `gh` 사용 가능 여부, **브랜치 보호 설정 가능 여부와 권한**(직접 push 금지·CODEOWNERS 필수 리뷰를 서버에서 강제할 수 있는지. 불가하면 `.githooks/` 채택을 재결정, `06-collaboration.md §6.1`) | `02-config.md §4`, `06-collaboration.md §6.1` | `gh auth status`, 조직 설정 확인 | config, CODEOWNERS (Phase 1, 6) |
| S6 | GHE Actions와 runner 유무 | `13-actions.md` | `13-actions.md §13.1` 절차 | `ci_mode` (Phase 1, 전환 시) |
| S7 | logcat 수집 형식: 포맷(threadtime/연도/uid), 버퍼 분리(radio/main 파일), 로테이션 파일명, 인코딩, **시각의 연도 유무와 타임존**(단말 로컬 시각인지, Jira 시각과 같은 기준인지) | `07-workflow.md §Step 3` | 사용자가 준 샘플 logcat과 같은 이슈의 Jira 발생 시각 비교 | `platforms/android/logcat.py` 포맷 목록, config `logcat.*` (Phase 2, 6) |
| S8 | 카테고리별 로그 태그 (데이터 스택은 확정: `DNC-<n>`, `DN-…`, `DPM-<n>`, `DRM-<n>`, `DSM-<n>`, `DCM-<n>`, `DSRM-<n>`) | `04-parser-matching.md §5.8`, `07-workflow.md §Step 3` | 샘플 logcat에서 카테고리별 태그 빈도 집계 | `parser-rules/tags.yaml` (Phase 1) |
| S9 | 로그 문구 형식: RILJ 요청/응답, 데이터 평가 거부 사유, LAST_CALL_FAIL_CAUSE, IMS 등록(벤더 ImsService), SMS 송수신 | `03-issue-db.md §5.4`, `04-parser-matching.md §5.8` | 샘플 logcat에서 해당 구간 추출 | `extractors.yaml`, 샘플 시그니처 (Phase 1, 2) |
| S10 | 벤더 RIL/IMS 로그 태그와 소스 구조 | `02-config.md §4`, `04-parser-matching.md §5.8` | 소스 트리와 로그 확인 | `code_root_keys`, `tags.yaml` (Phase 1), site-defaults `platform.ril.tags` |
| S11 | 소스 트리: Android 16/17 경로, 트리 버전을 알 수 있는 파일, 주요 심볼 위치 | `07-workflow.md §Step 2-1`, `§Step 5` | 사용자가 알려준 트리에서 확인 | `code_roots.py`, site-defaults `platform.source_tree.*`, 샘플 `code_refs` (Phase 1, 6) |
| S12 | 빌드명 체계: 브랜치 식별, 버전 비교 가능한 부분, 브랜치 이름·fixture 파일명에 쓸 수 없는 문자(`sanitize_build`가 충분한지) | `02-config.md §5.3` `build_compare`, `03-issue-db.md §5.9`, `contracts.md §fixture`·`§브랜치` | Jira의 SW 값과 빌드 서버 명명 규칙 | `build_compare` (Phase 1, 3) |
| S13 | 마스킹: 사내 로그에 나오는 식별자 형식, 오탐 패턴(사내 빌드 번호 등) | `08-safety.md §8` | 샘플 logcat에 `mask_pii --check` 실행 후 검토 | `mask_pii.py`, `mask.allow_patterns` (Phase 4) |
| S14 | 보안 규정: 이슈 DB에 올릴 수 있는 로그 범위, 벤더 코드 인용 허용 여부, 이슈 DB 레포 공개 범위 | `03-issue-db.md §5.7`, `08-safety.md §8` | 사내 규정 확인, 사용자 확인 | 5.7 작성 규칙 보완(SITE_PROFILE) (Phase 1) |
| S15 | 개발 환경: **Ubuntu 버전**(다른 OS는 v1 범위 밖, `01-architecture.md §3`), `python3` 버전(3.10+), pip/사내 미러, git 버전(worktree, `worktree add --no-track`, `push --force-with-lease=<ref>:<sha>` 지원) | `01-architecture.md §3` | 명령으로 확인 | 3장 의존성 (Phase 1) |
| S16 | Jira 키 형식 (프로젝트 키 규칙) | `02-config.md §5.3` `jira_key_regex`, `03-issue-db.md §5.4 (2)` | 샘플 Jira 키, 사내 Jira 프로젝트 목록 | `issue-db.config.yaml` `jira_key_regex` (Phase 1), `db_lint` 검사 (Phase 5) |
| S17 | `jira_base_url` 형식 (이슈 링크 URL) | `02-config.md §5.3` | 브라우저에서 샘플 Jira를 열어 URL 확인 | `issue-db.config.yaml` (Phase 1) |
| S18 | `fix.ref` 형식: Gerrit CL 번호/URL 또는 커밋 해시 표기 | `02-config.md §5.3` `fix_ref_regex`, `03-issue-db.md §5.4` | 사내 Gerrit CL 링크 예시 | `issue-db.config.yaml` `fix_ref_regex` (Phase 1) |
| S19 | CODEOWNERS 팀을 `gh pr create --reviewer`에 넘기는 형식 (`{org}/{team}` 등) | `02-config.md §5.3` `reviewers`·리뷰어 계산, `06-collaboration.md §6.1` | GHE 샌드박스 레포에서 `gh pr create --reviewer` 시험 | `issue-db.config.yaml` `reviewers` (Phase 1 초기값, Phase 7 사용) |
| S20 | 슬롯(phoneId) 표기: 태그 접미사(`DNC-<n>`)와 메시지 접두어(`[PHONE<n>]`, `[SUB<n>]` 등)의 실제 형식, RILJ 요청·응답에 슬롯이 어떻게 붙는지, Jira에 SIM 슬롯 필드가 있는지 | `04-parser-matching.md §5.8 (2)` 슬롯, `07-workflow.md §Step 3` | 듀얼 SIM 단말 샘플 logcat에서 두 슬롯의 데이터·RIL 로그 비교 | 파서 `phone_id` 추출 규칙(site-defaults `platform.log.phone_id`), `jira.field_map.sim_slot` (Phase 2, 6) |
| S21 | bugreport 구조: 첨부 형식(zip/txt), logcat 섹션 헤더(`------ SYSTEM LOG`, `RADIO LOG` 등)의 실제 문자열, 헤더의 `Build fingerprint`·`Build` 줄 형식 | `contracts.md §3.2` `extract-bugreport`, `07-workflow.md §Step 3` | 샘플 Jira 첨부 bugreport 1~2개의 섹션 헤더 확인 | `platforms/android/bugreport.py`(`parse_logcat.py extract-bugreport`) 섹션 목록(site-defaults `platform.bugreport.*`) (Phase 2) |
| S22 | 시험 절차·실패 스텝 표기: Jira 필드 유무, 설명·첨부의 표기, 첨부 형식(txt/csv/xlsx) | `02-config.md` `jira.field_map`·`jira.failed_step_patterns`, `07-workflow.md §Step 2` | 샘플 Jira 3~5건에서 시험 절차와 실패 스텝이 어디에 어떻게 적히는지 확인(없으면 선택 값이므로 비워 둔다). **스텝 마커 형식**: 시험 자동화가 logcat에 남기는 스텝 시작·통과·실패 줄의 태그와 문구(예: `TestRunner: Step 5 FAIL`)를 실제 로그에서 확인한다(없으면 `marker_patterns`를 비운다). **steps-file 시각 열**: 시험 절차 첨부(csv 등)에 스텝 시작·실패 시각이 있는지, 형식(ISO·오프셋 유무·`MM-DD HH:MM:SS`·시각만)과 타임존을 확인한다. **시험 장비 시계 vs 단말 logcat 시계**: 둘이 같은지(다르면 보통 얼마나 어긋나는지), Jira `occurred_at`이 어느 시계(장비·단말)인지 확인한다(실제 logcat에는 스텝 마커가 없고 장비 시각은 단말과 다를 수 있어 시계 차를 모르면 steps-file 시각을 쓰지 않는다. 안정적으로 알면 `failed_step.clock_offset`). **report.html 배치**: 표 머리 열 이름(번호·스텝·결과·시작·종료)과 상태 낱말(PASS/FAIL 외 `통과`·`NG` 등)을 확인하고 `steps_columns`·`steps_status`를 맞춘다. Jira 첨부가 zip이면 안의 `report.html` 위치. **`step_events` 내용**: 시험 스텝(CP 동작 포함)이 AP radio 버퍼·main 로그에 남기는 흔적(RIL 요청·unsol, 프레임워크 로그, extractor 이벤트)을 실제 로그로 확인해 스텝 → 흔적 규칙을 `issue-db.config.yaml`에 적고, 흔적이 없는 CP 스텝은 `observable: false`로 둔다 | `jira.field_map.test_steps`·`failed_step`, `jira.failed_step_patterns`, `failed_step.marker_patterns`(기본 `[]`)·`marker_status`·`steps_file_tz`·`clock_offset`·`steps_status`·`steps_columns`·`order` (`site-defaults.yaml`), `step_events` (`issue-db.config.yaml`) |

### 14.3 `SITE_PROFILE.md` 형식

```markdown
# SITE_PROFILE (사내 전용, 반출 금지)

## 진행 상태
- 모드: <사내 보완 | 사내 처음부터>
- 현재 Phase: 3
- 완료 Phase: 0 (2026-10-01), 1 (2026-10-03), 2 (2026-10-06)
- 기준 문서 세트: <docs/history/CHANGES.md의 버전 또는 날짜>

## 확인값
| # | 항목 | 확인값 | 근거 | 확인일 | 확인자 | 상태 |
|---|---|---|---|---|---|---|
| S3 | Jira MCP 서버 이름 | <값> | MCP 도구 목록 | 2026-10-01 | <아이디> | 확인 |
| S9 | 데이터 평가 거부 로그 문구 | <정규식> | 샘플 로그 <파일명> 1234행 | ... | ... | 확인 |
| S12 | 빌드명 체계 | <설명> | — | ... | ... | 미확인 (대안: 비교 불가 시 사용자 판단) |

## 설계 변경
- (날짜) <변경 내용> — 사유, 사용자 결정

## 사외 문서와의 차이
- (문서 세트 버전) <파일 §절> : <사내에서 다르게 적용한 점>

## 런타임 값 변경 이력
- (날짜) <항목> : <초기값> → <현재 값> (이슈 DB PR 링크)
```

- `SITE_PROFILE.md`는 `CLAUDE.md`가 **매 세션 import**하므로 짧게 유지한다(진행 상태, 확인값 요약, 설계 변경 요약). 확인 근거(로그 파일·행 번호, 긴 설명)는 import하지 않는 `docs/site/evidence.md`(사내 전용)에 둔다.
- "진행 상태"는 Phase가 끝나고 사용자 확인을 받을 때마다 갱신한다. 새 세션은 이 절을 보고 어디서 이어갈지 정한다.

### 14.4 Phase 0: 사내 환경 확인 (Phase 1보다 먼저)

> 사외 초안이 이미 있으면(사내 보완 모드) 이 절 대신 `15-local-draft.md §15.5`의 **S-1(축약판)** 을 한다. 이 절 전체는 사내에서 처음부터 만들 때만 쓴다.

사내 Claude Code가 이 순서로 진행하고, 각 단계 끝에 사용자 확인을 받는다.

1. `CLAUDE.md`, `docs/design/` 전체(`99-deferred.md` 제외), 레포 루트의 `REVIEW-OPEN.md`를 끝까지 읽고 14.2 표와 본문의 `<...>`, "placeholder", "확인 필요", "Phase 0에서 확인" 항목을 모아 **확인 목록**을 만들어 보여준다.
   - 같은 읽기에서 **문서 정합성 검토**도 한다. 이 문서 세트는 여러 번 부분 수정됐고 여러 파일로 나뉘어 있으므로 다음을 찾는다:
     - 파일 간 참조(`파일명 §절`)가 실제 절을 가리키는지, 문서 지도(`docs/design/README.md`)와 각 Phase의 "읽을 문서"가 실제 파일과 맞는지
     - `contracts.md`의 표(CLI, 종료 코드, op, fixture, 브랜치, renumber 참조, 상태 값)를 다른 파일이 **복사해서 다르게** 쓴 곳
     - 스크립트/커맨드/옵션 이름이 `01-architecture.md`(3장·3.1), `contracts.md §3.2`, `07-workflow.md`, `08-safety.md`, `09-commands.md`, `11-phases.md` 사이에서 다른 곳
     - 개수 불일치: 검증 체계 단계(5), hook 종류(7), 커맨드 수(12), eval 수(42), 트리거 테스트(돼야 함 12, 안 됨 7), 계획 `source` 값(9)
     - 스키마 필드가 템플릿·예시·검증 규칙·op 표 사이에서 다른 곳
     - 서로 모순되는 규칙
   - **`REVIEW-OPEN.md`의 항목을 모두 이 검토에 포함한다** (사내 정보가 있어야 판단할 수 있는 항목만 들어 있다). 각 항목은 (a) 수정안(또는 사내 대안)대로 처리 방식을 정하거나, (b) 사유와 함께 명시적으로 보류하고, 결과를 `SITE_PROFILE.md`의 "사외 문서와의 차이"(처리) 또는 "설계 변경"(보류 사유)에 항목 번호와 함께 기록한다.
   - 특히 **`05-verification.md`(수동 기록 검증 포함), `06-collaboration.md §6.3`(sync-pr 계획 재적용·사후 정리), `contracts.md §작업 계획` drift, `07-workflow.md` Step 1·8, 공통 쓰기 절차, record, `contracts.md`** 를 중점으로 본다.
   - 결과를 🔴 구현 전에 고쳐야 함 / 🟡 구현하면서 정리 / 🟢 참고로 나눠 보여준다. 🔴는 사용자 승인 후 `SITE_PROFILE.md`의 "사외 문서와의 차이"에 사내 적용 방식을 기록하고, 사외 문서에 반영할 수 있게 사내 정보를 뺀 요약도 함께 준다.
2. 사용자에게 필요한 자료를 요청한다. 권한 범위 안에서 받을 수 있는 것만 받는다.
   - 샘플 Jira 키 2~3개 (카테고리가 다른 것)
   - 샘플 logcat: 카테고리별 문제 로그 1개씩 + 정상 로그 1~2개 (Android 16/17 각각 있으면 좋음)
   - 소스 트리 경로 (16/17)
   - 빌드명 예시 몇 개, Gerrit CL 링크 예시 1~2개
3. S1(사내 Claude Code 기능)과 S15(개발 환경)를 먼저 확인한다. 외부 공식 문서에 접근할 수 없으면 빈 플러그인 실험으로 확인한다. 설계의 전제가 무너지면 여기서 멈추고 14.1 원칙대로 대안을 제시한다.
4. 나머지 항목을 조사해서 `SITE_PROFILE.md`에 기록한다. 로그 문구는 **실제 로그 행을 근거로** 정규식을 만들고, 근거 파일과 행 번호를 적는다. 확인 못 한 항목은 "미확인"과 임시 대안을 적는다.
5. 확인값을 반영할 위치(config 기본값, `issue-db.config.yaml`, `parser-rules/`, 샘플 type.md)를 목록으로 보여주고 승인받는다. 실제 반영은 14.2 표의 "반영 Phase"에서 한다.
6. 샘플 logcat은 Phase 1 fixture의 원본이 된다. fixture로 만들 때 반드시 마스킹한다.
7. `SITE_PROFILE.md`의 "진행 상태"에 Phase 0 완료를 기록한다.

완료 기준: 문서 정합성 검토 결과의 🔴 항목이 모두 처리 방식까지 정해졌고, `REVIEW-OPEN.md`의 모든 항목이 처리 방식이 정해졌거나 사유와 함께 보류로 `SITE_PROFILE.md`에 기록됐고, S1~S22이 모두 "확인" 또는 "미확인 + 대안"으로 기록되고, 설계 변경이 필요한 항목은 사용자 결정이 기록돼 있다.

### 14.5 사외 문서 업데이트를 사내에 반영할 때

1. 새 문서 세트(`CLAUDE.md`, `GUIDE.md`, `docs/design/`, `docs/history/CHANGES.md`, `REVIEW-OPEN.md`, `DRAFT_NOTES.md`)로 교체한다 (사내 값이 없으므로 그대로 덮어써도 된다). `SITE_PROFILE.md`는 건드리지 않는다. 코드까지 함께 바뀐 사외 초안을 반입할 때는 문서만 교체하지 말고 `15-local-draft.md §15.6` 재반입 절차(`tools/import_draft.py`)를 쓴다.
2. 사내 Claude Code에 "새 문서 세트의 `docs/history/CHANGES.md`와 `SITE_PROFILE.md`를 비교해서 영향받는 항목을 알려줘"라고 요청한다. 새로 생긴 placeholder(14.2의 새 S 번호 포함)는 14.4 방식으로 확인한다. 바뀐 파일에 대해서는 14.4 1번의 문서 정합성 검토를 다시 한다.
3. 설계가 바뀐 부분은 이미 구현된 코드와 이슈 DB에 미치는 영향(스키마 변경 → 마이그레이션 필요 여부 포함)을 정리해서 Phase 단위로 반영한다. "진행 상태"의 완료 Phase 중 영향받는 것을 표시한다.
