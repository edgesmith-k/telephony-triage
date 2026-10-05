# 01. 전체 구조와 플러그인 레포

> 원본 1장(이전 `CLAUDE.md §1`), 2장, 3장. CLI 옵션과 종료 코드는 `contracts.md §3.2`, `contracts.md §종료 코드`에만 있다.

---

## 1. 목적과 범위

Android Telephony 이슈 도구. Jira 이슈와 logcat을 받아 원인·해결책을 분석하고, 결과를 **카테고리 > 이슈 유형(증상) > 원인**으로 사내 GitHub 이슈 DB 레포(`telephony-issue-db`)에 누적한다. 팀원들이 같은 DB에 계속 기여하며 시그니처 품질과 해결 상태를 관리한다.
v1 범위: logcat(radio/main/system/crash, bugreport는 logcat 섹션만) · Jira **읽기 전용** · GHE 브랜치+PR(main 직접 push 금지) · CI 없음(`ci_mode: local`) · 카테고리 data/call/network/sim/sms/ims · 사용자별 한 번에 한 작업. 제외: CP 로그 파싱, Jira 쓰기, 3-way replay. 상세 표는 `GUIDE.md §1`.

---

## 2. 전체 구조

### 2.1 레포 2개

플러그인은 설치될 때 캐시 경로로 복사되므로, 그 안에서 git push를 하면 안 된다. **도구와 데이터를 분리한다.**

| 레포 | 역할 | 로컬 위치 |
|---|---|---|
| `telephony-triage-plugin` | 플러그인 코드 (스킬, 커맨드, 파서 엔진, 매처, hook, 마이그레이션) + 개발 문서 | 사내 플러그인 마켓플레이스로 설치 |
| `telephony-issue-db` | 이슈 DB (유형/원인, Jira 기록, 파서 규칙, fixture, 피드백, 생성 인덱스) | 사용자가 clone, 경로는 config에 저장 |

### 2.2 역할

| 역할 | 인원 | 책임 |
|---|---|---|
| 이슈 DB 메인테이너 | 1~2명 | `schema/`, `templates/`, `parser-rules/`, `.githooks/`, `issue-db.config.yaml`, 검증 체계(`06-collaboration.md §6.3`), 스키마 마이그레이션, 새 카테고리 승인 |
| 카테고리 오너 | 카테고리별 1~2명 | 해당 카테고리 PR 리뷰, 새 유형 승인, 월간 리뷰(`06-collaboration.md §6.6`) |
| 기여자 | 전원 | 플러그인으로 분석하고 PR 생성, 직접 편집 기여 |

역할은 `.github/CODEOWNERS`로 강제한다 (`06-collaboration.md §6.1`).

---

## 3. 플러그인 레포 구조

```
telephony-triage-plugin/                 # 개발 레포 루트
├── .claude-plugin/
│   └── marketplace.json                 # 사내 마켓플레이스 정의. 플러그인 source는 ./plugin
├── CLAUDE.md                            # 개발 컨텍스트 진입점 (배포 대상 아님, 짧게 유지)
├── SITE_PROFILE.md                      # 사내 확인값 기록 (14-site.md, 사내 전용, Phase 0 또는 S-1에서 생성)
├── SITE_PATHS                           # 사내 전용 경로 목록 (15-local-draft.md §15.6)
├── .draft-manifest.json                 # [사내 전용, SITE_PATHS] 마지막 반입 기준선 (import_draft.py가 씀)
├── .local-draft                         # [사외 PC 전용, .gitignore] 사외 초안 모드 표식 (CLAUDE.md 머리말)
├── tools/import_draft.py                # 재반입: SITE_PATHS를 보존하며 새 사외 초안 덮어쓰기 (staging → 검증 → 활성 전환, 실패 시 rollback)
├── tools/check_boundary.py             # 사외/사내 경계 검사 (사내 표식 패턴·site import·합성 fixture·SITE_PATHS 부재, 15-local-draft.md §15.6)
├── tools/boundary-allow.txt            # check_boundary 예외 (사외). 사내 패턴·예외는 docs/site/
├── tools/sync_schemas.py               # plugin/schemas/ 사본 ↔ 이슈 DB schema/ 대조
├── .github/workflows/external.yml      # 사외 CI (경계 검사·스키마 사본·fixture 생성기 --check·pytest). 사내 Actions(13-actions.md)와 별개
├── tools/make_db_skeleton.py            # 합성 샘플에서 운영용 이슈 DB 뼈대 생성 (11-phases.md Phase 1)
├── DRAFT_NOTES.md                       # 사외 초안 상태 파일(≤8KB): 진행 상태·막힌 것·활성 트랙·실험 결과 표 (15-local-draft.md)
├── docs/history/                        # 아카이브(읽지 않음): draft-notes-<날짜>.md(Phase별 상세), CHANGES.md(문서 세트 변경 이력), REVIEW-10/11.md
├── tools/list_site_todos.py             # TODO(SITE:S<n>) 목록 추출
├── tools/offline_eval.py                # 라벨셋(과거 Jira + 로그 + 정답 원인)으로 analyze --dry-run 1위 정확도·오탐률 측정 (15-local-draft.md §15.5 S-5)
├── docs/design/                         # 설계 문서 (이 파일 포함. 지도 README.md, 원칙 12-principles.md. 배포 대상 아님)
├── docs/site/                           # [사내 전용, SITE_PATHS] 확인 근거 (14-site.md §14.3)
├── tests/
│   ├── fixtures/
│   │   ├── logs/                        # 엔진 단위 테스트용 로그 (유형별 회귀 fixture는 이슈 DB에 있음)
│   │   ├── plans/                       # 손으로 쓴 plan.json (Phase 7·10 테스트, record·import·review 계획 포함)
│   │   └── issue-db-sample/             # 합성 샘플 이슈 DB 트리 (6개 유형, 테스트의 기준 데이터). 변형 issue-db-*는 커밋하지 않고 make_variant_dbs.py가 테스트 때 생성
│   ├── helpers/make_repo.py             # 샘플 트리에서 임시 git 레포와 bare 원격을 만드는 테스트 헬퍼
│   ├── helpers/make_plugin_root.py      # plugin/을 임시 디렉토리에 복사하고 example을 site-defaults.yaml로 넣은 테스트용 플러그인 루트 (15-local-draft.md §15.1)
│   ├── site/                            # [사내 전용, SITE_PATHS] 실제 로그 기반 추가 테스트, offline-eval.yaml 라벨셋 (15-local-draft.md §15.5 S-4·S-5)
│   ├── mocks/                           # 사외 초안용 모의 환경: mcp.json(mock-jira 등록), jira_mcp/, jira/, remote/, bin/gh, gh-state/, logcat_gen.py, src/android16|17/, builds.yaml, skills/data-analyzer/ (15-local-draft.md §15.2)
│   ├── golden/                          # [사내 전용, SITE_PATHS] 포팅 전 기존 파서 골든 출력 (16-existing-assets.md §16.3)
│   ├── test_golden.py                   # 골든 비교 테스트 (사외에는 모의 골든으로 틀만)
│   └── test_*.py
└── plugin/                              # 배포되는 플러그인 본체
    ├── site-defaults.example.yaml       # 모의 기본값. 코드는 읽지 않고 테스트 헬퍼가 복사해서 쓴다. 사내 S-3에서 site-defaults.yaml(SITE_PATHS)을 만들며, 없으면 모든 커맨드가 멈춘다 (15-local-draft.md §15.1)
    ├── .claude-plugin/
    │   └── plugin.json                  # name: telephony-triage, version, description
    ├── commands/                        # 09-commands.md §10 과 같은 목록 (12개)
    │   ├── setup.md                     # /telephony-triage:setup
    │   ├── analyze.md                   # /telephony-triage:analyze <JIRA-KEY> [logcat...] [--code <프로필|경로>] [--dry-run] [--jira-file <yaml>] [--analyzer | --no-analyzer] [--explore | --no-explore]
    │   ├── record.md                    # /telephony-triage:record <JIRA-KEY> [--cause <원인 ID> | --new-cause <유형 ID> | --new-type <category> | --unresolved <유형 ID>] [--fixture <logcat>] [--resolved-fixture <logcat>] [--dry-run] [--jira-file <yaml>]
    │   ├── sync.md                      # /telephony-triage:sync
    │   ├── search.md                    # /telephony-triage:search <keyword|JIRA-KEY|ID>
    │   ├── sync-pr.md                   # /telephony-triage:sync-pr [branch] (계획 재적용)
    │   ├── preview.md                   # /telephony-triage:preview
    │   ├── review.md                    # /telephony-triage:review [category]
    │   ├── validate.md                  # /telephony-triage:validate [--cause <원인 ID> <logcat...>] [--extra <logcat...>]
    │   ├── verify-fix.md                # /telephony-triage:verify-fix <원인 ID> <logcat...> [--jira <키>]
    │   ├── fix-submitted.md             # /telephony-triage:fix-submitted <원인 ID> --ref <CL> --fixed-in <branch>[:<build>]
    │   └── migrate.md                   # /telephony-triage:migrate (메인테이너용)
    ├── skills/
    │   └── telephony-triage/
    │       ├── SKILL.md                 # analyze 핵심 흐름만, 500줄 이내 (10-skill-eval.md §SKILL 구성)
    │       └── reference/
    │           ├── write-flow.md        # 공통 쓰기 절차 (Step 8 방식)
    │           ├── record.md            # 수동 기록 흐름
    │           ├── verify.md            # validate --cause, fix-submitted, verify-fix 흐름
    │           ├── explore.md           # analyze Step 5-2 탐색 분석 (후보 없음·원인 미확인일 때 Claude 가설)
    │           ├── sync-pr.md           # sync-pr 흐름
    │           ├── db-authoring.md      # 구성 목록은 10-skill-eval.md §skill-creator 입력
    │           ├── ril-requests.md      # RIL request/response/unsol 해설
    │           ├── fail-causes.md       # DataFailCause, CallFailCause, 등록 reject cause
    │           └── log-tags.md          # 태그 해설 (실제 수집 목록은 이슈 DB parser-rules/tags.yaml)
    ├── scripts/                         # 3.1 매트릭스 참고
    │   ├── common/                      # config 로드, 이슈 DB 로드, 스키마 검증, git 헬퍼, 로깅, 시그니처 컴파일, 마스킹 함수, `events.py`(파서 출력 이벤트 키 순서·`line_ref`·`validate_event`, 표준 라이브러리만)
    │   ├── config.py
    │   ├── code_roots.py
    │   ├── parse_logcat.py
    │   ├── parser_backends/             # base.py(인터페이스), reference/(공통 처리, 사외), site/(포팅한 기존 파서, 사내 전용 SITE_PATHS)
    │   ├── adapters/                    # Jira 응답 변환, 외부 파서 어댑터 (사내 것은 site_* , SITE_PATHS)
    │   ├── match_signatures.py
    │   ├── mask_pii.py
    │   ├── jira_fields.py               # Jira 응답 → field_map 추출·마스킹·UTC (Phase 13)
    │   ├── db_search.py
    │   ├── db_add.py                    # CLI만. 구현은 dbadd/
    │   ├── dbadd/                       # core(상수·계획 검사·Tree), applier(apply), ops/<묶음>.py(op 메서드 믹스인), drift, ids, similar
    │   ├── db_pr.py
    │   ├── db_build.py
    │   ├── db_lint.py
    │   ├── db_regress.py
    │   ├── db_verify.py
    │   ├── db_precommit.py
    │   ├── db_review.py
    │   ├── db_migrate.py
    │   ├── guard.py                     # Claude hook 판정기 (08-safety.md §9)
    │   ├── jira_bridge.py               # PostToolUse hook: Jira MCP 원문 → JOB/jira_raw.json, 모델에는 마스킹 요약 (08-safety.md §9)
    │   ├── triage.py                    # analyze Step 0~4 + Step 5 resolve 드라이버 (contracts.md §3.2)
    │   └── migrations/                  # 0001_xxx.py … 스키마 버전별 마이그레이션
    ├── schemas/                         # 이슈 DB schema/ 사본 (단일 원본은 이슈 DB, tools/sync_schemas.py로 대조)
    └── hooks/
        └── hooks.json                   # 08-safety.md §9
```

- 스크립트는 Python 3.10+, 표준 라이브러리 중심으로 쓴다. 외부 의존성은 `pyyaml`, `jsonschema` 정도로 최소화한다.
- **실행 환경은 Ubuntu(Linux)** 다(사외·사내 동일). `.githooks/pre-commit`은 `#!/bin/sh` 셸 스크립트, PATH 스텁·홈 경로(`~/.telephony-triage/`)·실행 비트 모두 POSIX 기준이다. 다른 OS는 v1 범위 밖이다 (`14-site.md` S15).
- SKILL.md와 커맨드는 스크립트를 **`${CLAUDE_PLUGIN_ROOT}/scripts/<이름>.py`** 로 호출한다. 설치 위치가 캐시 경로라서 상대 경로로는 동작하지 않는다. 스킬/커맨드 본문에서 `${CLAUDE_PLUGIN_ROOT}`가 실행 시 치환되는지는 S1에서 시험한다 (`14-site.md §14.2`). 치환되지 않으면 config의 `plugin.scripts_path`를 읽어 쓰는 방식으로 바꾼다.
- Jira MCP는 사내 제공 서버를 쓰므로 `.mcp.json`에 번들하지 않는다. setup에서 **존재 여부와 읽기 도구 목록만 확인**한다.
- 플러그인은 상수 두 개를 가진다: 지원하는 이슈 DB 스키마 범위 `SUPPORTED_SCHEMA = (min, max)`, 생성기 버전 `GENERATOR_VERSION` (`02-config.md §5.3`, `06-collaboration.md §6.4`).
- `marketplace.json`이 하위 폴더를 플러그인 source로 지정하는 방식은 공식 문서(사내에서 접근 불가면 빈 플러그인 실험, S1)로 확인한다. 지원하지 않으면 플러그인을 루트에 두고 개발 문서(`CLAUDE.md`, `docs/design/`)는 `docs/`로 옮긴다.
- 합성 샘플만 플러그인 레포 `tests/fixtures/issue-db-sample/`에 커밋한다. 테스트용 변형 이슈 DB(`issue-db-*`)는 `tests/helpers/make_variant_dbs.py`가 테스트 때 샘플에서 생성하며 커밋하지 않는다. 변형용 오류·케이스는 샘플 트리에 넣지 않는다. 반입·운영용 이슈 DB는 `tools/make_db_skeleton.py`로 만든 뼈대에서 시작한다(합성 샘플 없음).

### 3.1 스크립트 책임과 호출자

| 스크립트 | 책임 (이것만 한다) | 호출자 |
|---|---|---|
| `common/` | config·이슈 DB 로드, 스키마 검증, git 헬퍼, 로깅, **시그니처·extractor 컴파일 함수**(매처와 `db_build --cache-only`가 공유), **마스킹 함수**(`mask_pii`와 `parse_logcat` 공유), **이벤트 레코드 `events.py`**(파서 출력 이벤트 키 순서·`line_ref`·`validate_event`, 표준 라이브러리만), `sanitize_build`, **검사 오케스트레이션 `checks.py`**(프로필 `stage`·`precommit`·`guard`의 단계 목록과 종료 코드 집계 `aggregate`. 하위 스크립트는 같은 프로세스에서 `main(argv)`로 부른다(`run_script`, 종료 코드·stdout JSON·stderr는 subprocess와 같고 `TT_SCRIPT_SUBPROCESS=1`이면 subprocess). top-level import는 stdlib와 `common.exitcodes`뿐이다: guard가 `site-defaults.yaml` 없이도 멈추지 않아야 한다) | 모든 스크립트 |
| `config.py` | 사용자 config 로드/검증/갱신, `site-defaults.yaml` 로드(없으면 종료 코드 2), 스키마·생성기·파서 백엔드·외부 파서 버전과 gh 인증 호환성 판정(`check --for write\|dry-run`, `migrate/schema-v<N>` 브랜치는 버전 불일치 예외), **`plugin.scripts_path` 갱신**(`sync-scripts-path`) | 모든 스크립트, setup, SessionStart hook |
| `code_roots.py` | 코드 경로 후보 정렬, 경로 검증, 트리 버전 추정, `<root 키>:` 경로 변환, symbol 검색 | analyze Step 2-1, Step 5 |
| `parse_logcat.py` | logcat → 이벤트 JSON (**파서 백엔드 선택·호출**(`parser_backends/`, 포맷·연도·타임존·윈도우·RIL 페어링·`phone_id`·`coverage`·builtin 판별은 백엔드), bugreport에서 logcat 섹션만 추출(`extract-bugreport`), 외부 파서(어댑터) 실행, 백엔드·외부 파서 불일치 경고, `--mask`면 extractor 전 줄 단위 마스킹(백엔드·외부 파서 이벤트 포함), extractor 실행), **fixture 최소 구간 자르기**(`cut`, `common/` 마스킹 함수로 마스킹 후 저장) | analyze Step 3·7, `record`(`--fixture`), `verify-fix`, `validate --cause`, `db_regress` |
| `mask_pii.py` | 마스킹 치환(파일), 외부 이벤트 JSON 마스킹(`--events`), `--check` 검출. 마스킹 함수 자체는 `common/`에 있고 `parse_logcat`이 공유 | `db_add`, `db_precommit`, `db_pr stage`, guard hook 3번 |
| `jira_fields.py` | Jira 키 검사(`check-key`, `jira_key_regex`), Jira 응답(MCP `get_issue` 결과 또는 `--jira-file`)에서 `jira.field_map`으로 구조화 필드 추출, 텍스트 필드 즉시 마스킹, 발생 시각 UTC 변환·`occurred_on`·logcat 연도, `--jira-meta` 파일 생성(`extract`). 사람 이름 필드(코멘트 작성자)는 내지 않음 | analyze Step 0·2, `record`, `verify-fix --jira` |
| `match_signatures.py` | 마스킹된 이벤트 JSON × 이슈 DB → 후보 랭킹(`same_phone`·`sequence` 포함, 패턴당 타임아웃), 수정 상태 판단, related | analyze Step 4, `db_regress`, `db_verify` |
| `db_search.py` | 이슈 DB 검색 (secondary/related, 옛 ID → 새 ID 연결) | `search`, `record` 대화형 모드, Phase 11 테스트 |
| `db_add.py` | 작업 계획(`plan.json`) 적용(`source`별 op 허용 규칙, `schema_version` 검사 포함), **drift 검사**(`drift`), ID·fixture 번호 할당, 브랜치 안 renumber("내 ID"만)·check-ids, 템플릿 생성, 유사 유형 검사 | `db_pr stage`, `db_verify rules --draft`, analyze Step 7·`record` (`similar`) |
| `db_pr.py` | **이슈 DB 쓰기 오케스트레이션**: 세션 lock(`lock`), 읽기 스냅샷, 잔여 worktree·도구 브랜치(`tt/*`) 정리, 사전 점검(브랜치·열린 PR·Jira 중복), worktree 준비 + drift 검사 + apply + 검사(`stage`), 확인 화면 데이터(`summary`), lease push + PR(`publish`), 정리(`discard`), 작업 상태 파일(`state.json`) | analyze Step 0·1·8, `record`, `sync`, `sync-pr`, `verify-fix`, `validate --cause`, `fix-submitted`, import/review/move 계획 PR |
| `db_build.py` | 생성 파일(README, 카테고리 README, STATS, CHANGELOG)과 로컬 캐시 생성, 정합성 검증 | `db_pr stage`, `preview`, setup, `db_pr snapshot` 이후 캐시 갱신, `db_precommit`, guard hook 4번 |
| `db_lint.py` | 정적 검사: 스키마, ID 형식·중복, Jira 중복, 작성 규칙, 용어집, related·code_refs 형식, `fix.ref` 형식(`fix_ref_regex`), 카테고리 목록, fixture 파일명, 시그니처·extractor·`jira/*.yaml` `note`·원인 본문·`cp_evidence` 안의 원본 식별자 패턴, **정규식 안전**(중첩 수량자·무제한 역참조 거부, `04-parser-matching.md §5.8 (4)`), 시그니처 `sequence`의 id 존재·중복, `builtin.*`·`ext.*` 이벤트 참조, 옛 ID 잔존, `.expect.yaml`의 `also_allowed`(자기 원인·같은 유형 원인·없는 ID 금지), 검증 규칙(근거 없는 verified 금지: `verify-resolution`의 evidence 없이 verified 금지, evidence의 Jira 키·fixture 경로 존재), `synthetic_allowed: false`일 때 `origin: synthetic` 경고 | `db_pr stage`, `db_precommit`, Step 1 사후 lint, CI |
| `db_regress.py` | fixture 회귀: 파서 + 마스킹 + 매처로 기대 결과 확인 (회귀·검증 모드), 파서 규칙 변경 전/후 이벤트 diff | `db_pr stage`, `db_precommit`, `db_verify`, CI |
| `db_verify.py` | `05-verification.md` 검증: `rules`(R1~R6), `resolution`(해결책 적용 후 로그 판정, 새 원인은 `--plan --draft`), `fix`(verify-fix 판정) | analyze Step 7(`--draft`), `db_pr stage`, `validate`, `record`(`--resolved-fixture`), `verify-fix`, `db_precommit`, CI |
| `db_precommit.py` | **오케스트레이터만**: 변경 범위를 계산해서 호출 순서(`config.py check --for dry-run`(compat)·`.cache/` 차단(cache) 포함)는 `common/checks.py`의 PRECOMMIT 프로필이 정한다. 호출 내용: `db_lint --staged`, `mask_pii --check --staged`, `db_regress --staged`, (규칙 변경 시) `db_verify rules --staged`, `db_build --verify --staged`를 순서대로 호출 | git pre-commit hook |
| `db_review.py` | 월간 리뷰 리포트 (시그니처 없는 원인, fixture 없이 검증된 원인 포함) | `review` |
| `db_migrate.py` | 스키마 마이그레이션 실행(`--to`, 메인테이너의 `migrate/schema-v<N>` 브랜치 워킹 트리를 직접 바꿈), 옛 스키마 계획 올리기(`upgrade-plan`) | `migrate`, `sync-pr`(옛 스키마 계획) |
| `guard.py` | Claude hook 입력(도구 이름, 명령, 파일 경로)을 받아 허용/차단/ask 판정 (Bash·MCP·Write/Edit) | `hooks.json` |
| `jira_bridge.py` | 설정된 Jira `get_issue`·`get_comments` MCP 응답 원문을 `<work_dir>/<KEY>/jira_raw.json`에 쓰고 모델에 보이는 결과를 마스킹 요약으로 바꾼다(PostToolUse `updatedToolOutput`) | `hooks.json` |
| `triage.py` | **analyze 드라이버**: Step 0~4와 Step 5 `code_refs` resolve를 위 스크립트의 `main()`을 같은 프로세스에서 불러 순서대로 수행, `analysis.json`(≤4KB)·`report.md` 초안·`trace.jsonl`, 후보 없음·원인 미확인이면 Step 5-2 입력 `timeline.md`. 사용자 결정 지점은 `needs_input`. 자체 판정 로직은 없다(요약·절삭만) | analyze(SKILL.md), `tools/offline_eval.py`(`--offline-db`) |

- 검사 로직은 각 담당 스크립트에만 둔다. 다른 스크립트는 호출만 한다.
- `record`는 매처와 코드 분석을 쓰지 않지만 쓰기 경로(`db_pr stage` → `summary` → 커밋 → `publish`)와 검사는 analyze와 같다 (`07-workflow.md §record`).
- **스킬은 이슈 DB를 직접 바꾸지 않는다.** 스킬이 하는 일은 결정·초안 작성과 사용자 확인이고, 쓰기 절차(worktree, 적용, 검사, push, PR)는 `db_pr.py`가 한다. 커밋만 스킬이 `git add`와 `git commit`을 별도 Bash 호출로 실행한다 (`07-workflow.md §Step 8-6`).
- SessionStart의 `plugin.scripts_path` 갱신은 `hooks.json`이 `config.py sync-scripts-path`를 호출해서 한다.
- 사후 main ID 중복·Jira 중복은 `db_lint`가 찾아 보고만 한다. 정리는 v1에서 메인테이너가 직접 편집으로 한다 (`06-collaboration.md §6.3`, 자동화는 `99-deferred.md`).
