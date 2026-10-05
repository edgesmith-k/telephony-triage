# telephony-triage — Architecture / Token / 확장성 리뷰와 Refactoring Plan

- 작성일: 2026-10-01. 기준 commit: `088d083` (`origin/main`, Phase 13 진행 중 + `PLUGIN_IMPROVEMENT_HANDOFF.md`).
- 목적: 코드를 고치기 전에 **현재 상태 → 문제 → 근본 원인 → 목표 구조 → Phase별 수정 순서**를 한 문서로 고정한다. 새 Codex/Claude agent가 레포를 처음 보더라도 이 문서와 `docs/design/contracts.md`만으로 Phase 구현을 시작할 수 있게 쓴다.
- 이 문서는 **분석과 계획**이다. 코드는 바꾸지 않았다. 삭제 후보도 삭제하지 않았다.
- 번호 규칙: 이 문서의 리팩터링 단계는 **`RF-0`~`RF-9`** 다. 프로젝트 개발 Phase(D0~14, `docs/design/11-phases.md`)와 `PLUGIN_IMPROVEMENT_HANDOFF.md`의 I0~I6과 다른 번호 체계이며, 본문의 "Phase 13"은 개발 Phase를 가리킨다.
- 경로 약어: `S/` = `plugin/scripts/`, `K/` = `plugin/skills/telephony-triage/`, `C/` = `plugin/commands/`, `D/` = `docs/design/`, `T/` = `tests/`.
- 기존 임시 인계 문서 `PLUGIN_IMPROVEMENT_HANDOFF.md`(R1~R15, I0~I6)와의 관계: 그 문서는 **정확성·안전성 결함**(lock 원자성, 경로 안전, shell 인용, 교차 슬롯 결합 등)을 다룬다. 이 문서는 **구조·token·경계·확장성**을 다룬다. 두 계획은 §U에서 하나의 순서로 합친다. 서로 반복하지 않는다.

---

## 외부 리뷰 결과 (2026-10-01, 다른 에이전트가 ZIP 스냅샷 기준으로 작성 — 원문은 사용자 보관)

**총평**: 결론 방향(엔진 유지, 모델 표현과 사내 경계 먼저 분리, 범용 프레임워크로 다시 쓰지 말 것)은 이 문서와 같다. 근거 수준을 스스로 제한(토큰 실측 아님, pytest 미실행, git 이력 없음)했다. 아래는 코드로 대조한 결과.

**이 문서·HANDOFF에 없던 결함 — 현재 main에서 확인함** → RF-0에 추가:
- `tools/import_draft.py`: (1) 첫 반입(기준선 없음)은 같은 경로의 사내 파일이 달라도 경고 없이 덮어씀(재현함. 설계상 빈 레포에 반입하므로 실전 위험은 낮음) (2) 기준선에 없는 사내 새 파일이 사외 새 파일과 이름이 같으면 덮어씀 (3) `SITE_PATHS` 파일 자체가 보호 대상이 아님 (4) `apply()`는 순차 copy/delete, 롤백 없음.
- `db_pr.py`·`common/ghcli.py`: git/gh subprocess에 timeout 없음(자동화 전 필수).
- `code_roots.py::cmd_resolve`: `Path(root)/rel` 그대로, `..`·symlink containment 검사 없음.
- 의존성 매니페스트 없음(`pyproject.toml`/lock). 새 PC마다 손 설치.
- `commands/validate.md`: `git fetch origin`에 `-C <db>` 없음; `base_branch` 위치를 `issue-db.config.yaml`로 적었으나 실제는 사용자 config `issue_db.base_branch`.

**토큰 관련 — 확인함** → RF-1에 추가:
- **MCP 원문이 마스킹 전에 모델 컨텍스트에 들어간다**(Claude가 응답을 받아 `jira_raw.json`으로 저장하는 설계). 후처리 마스킹은 이미 쓴 토큰·노출을 못 줄인다. → raw를 모델이 보지 않는 브리지로 저장하고 masked brief만 모델에.
- `match_signatures --top`은 `candidates`에만 적용, `types`·`causes`·`pending_causes`는 전체 출력. `db_search --limit` 기본 20(SKILL은 상위 3). `cause_entry()`에 `code_refs` 없음. `jira_fields extract`가 코멘트 전부 출력(예산 없음).
- 점수 포화: `base = 0.4·S + 0.6·C`, `min(1.0, …)` → S=C=1이면 bonus가 순위를 못 바꿈(HANDOFF R8). **`confidence=high`를 자동 게시 근거로 쓰지 않는다** — 별도 품질 게이트(사내 held-out 검증·오탐 기준) 필요.

**현재와 다른 것(ZIP 시점)**: REVIEW-10/11·CHANGES는 `docs/history/`로 이동 완료, DRAFT_NOTES는 6KB 상태 파일로 축소 완료, `CURRENT_STATUS.md` 제안은 DRAFT_NOTES 축소로 대체, `git archive` 묶음이면 `.gitignore` 파일 혼입 지적은 해당 없음.

**동의하지 않는 것**: 새 Phase 번호(0~8) — 내용이 RF와 거의 1:1이라 RF에 흡수하고 번호 체계를 늘리지 않는다. release descriptor·`contracts/`·SQLite state·outbox는 두 번째 구현(RF-5)·자동화(RF-8) 전엔 만들지 않는다(리뷰 자신의 원칙과 같음). `code_refs` projection은 P1보다 P2.

**사용자 결정 (2026-10-01)**:
- (a) **사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐.** 파일·마스킹 로그·diff·요약 파일은 나가지 않는다. 따라서 `export_external.py`는 만들지 않고(RF-2 재편), `import_draft.py`·`15 §15.6`·GUIDE의 "사외로 옮길 요약" 안내를 바꿨다. 한계: 사내에서 실패한 사례를 사외에서 확정 진단할 수 없다 — 사외는 합성 데이터로만 재현한다.
- (b) 자동 게시 단계(RF-8)는 `confidence`가 아니라 별도 품질 게이트를 통과할 때만 채택한다.

---

## A. Executive Summary

**이 프로젝트가 지금 가진 것 (강점)**

1. "LLM은 결정하지 않는다"가 이미 원칙이다. 분류·회귀·검증의 기준은 `parse_logcat.py → match_signatures.py → db_verify.py`의 결정적 출력이고, LLM(Claude Code 세션)은 **오케스트레이션·설명·초안·사용자 확인**만 한다 (`D/12-principles.md`, `D/16 §16.2`).
2. 지식(태그·문구·시그니처·fixture)은 코드가 아니라 **이슈 DB 데이터**(`parser-rules/`, `type.md`)에 있다. Android 버전이 바뀌어도 플러그인 재배포 없이 이슈 DB PR로 대응하는 구조가 이미 있다 (`D/04 §5.8 (1)`).
3. 사외/사내 경계가 **설계 수준에서** 이미 있다: `SITE_PATHS` 허용 목록, `tools/import_draft.py`, `site-defaults.yaml` 부재 시 종료 코드 2, 합성 fixture 전용(`origin: synthetic`), 모의 Jira MCP·gh 스텁·소스 트리.
4. 파서 백엔드 인터페이스(`S/parser_backends/base.py`), 어댑터 계약(`S/adapters/base.py`), 이벤트 스키마가 **사실상의 NormalizedLogEvent 계약**이다. 플랫폼 확장의 seam이 이미 코드에 있다.

**핵심 문제 (중요도 순)**

| # | 문제 | 근거 | 영향 |
|---|---|---|---|
| P1 | **LLM이 15~20개의 CLI 호출을 직접 순서대로 실행하는 오케스트레이터**다. analyze 한 건 = Bash 왕복 15회 이상, 호출마다 JSON stdout·stderr가 컨텍스트에 쌓인다 | `K/SKILL.md` Step 0~8 (267줄), eval 실측 **건당 6.4만~14.4만 token** (`DRAFT_NOTES.md` "Phase 13 반복 1·2") | 사내 token 소진의 1순위. 결정적 단계(Step 0~4)를 LLM이 "실행"하고 있다 |
| P2 | **개발 세션 고정 컨텍스트가 크다**: `CLAUDE.md` 15KB + `@SITE_PROFILE.md` 매 세션 import, S-1 "읽을 것"에 `DRAFT_NOTES.md` **136KB(≈45K token)** | `CLAUDE.md` 머리말, `D/15 §15.5` S-1 행, `DRAFT_NOTES.md` 1,160줄 | 사내 AI가 "코드 한 줄 보기 전에" 5만 token을 쓴다 |
| P3 | 사외→사내 **반입 도구는 있지만 사내→사외 반출(export) 도구와 경계 검사기가 없다**. 경계는 `SITE_PATHS` 목록 파일 + 사람의 주의에 의존한다 | `tools/import_draft.py`만 존재. `T/test_mocks.py::test_site_paths_are_absent_in_draft`는 경로 "부재"만 검사 | 사내에서 고친 사외 파일에 사내 문구가 섞여 반출될 수 있다 |
| P4 | Android 특정 지식이 코드 4곳에 **상수로** 박혀 있다 (`code_roots.py` 트리 검증·버전 파일, `parser_backends/logcat.py` 포맷·슬롯 regex, `ril.py` RILJ, `parse_logcat.py` bugreport 헤더) | §E 표 | 작은 양이지만 "플랫폼 어댑터"라는 이름의 디렉토리가 없어 oFono 등을 넣을 자리가 보이지 않는다 |
| P5 | 문서 중복·누적: `D/` 406KB, `DRAFT_NOTES` 136KB, `CHANGES` 57KB, `REVIEW-10/11` 41KB, `HANDOFF` 27KB, `GUIDE` 17KB. op 표가 `contracts.md`와 `K/reference/db-authoring.md`에 두 번, sync-pr 절차가 `C/sync-pr.md`와 `K/reference/sync-pr.md`에 두 번 | §C, §Q | 새 agent가 "무엇을 읽어야 하는지" 정하는 데 token을 쓴다 |
| P6 | `HANDOFF` R1~R6(lock 비원자, 경로 삭제 안전, `commit -m` 인용, 교차 슬롯 S/C 결합, 회전 파일 RIL, 외부 파서 실패 전파)는 **자동화(스케줄러)로 가기 전에 반드시** 고쳐야 한다 | `docs/development/PLUGIN_IMPROVEMENT_HANDOFF.md` | 사람이 없는 실행에서 잘못된 결론·파일 손실 가능 |

**가장 중요한 개선 방향 (한 줄씩)**

1. **결정적 파이프라인을 한 개의 driver(`triage.py`)로 묶고, LLM은 결과 하나만 읽게 한다.** (P1)
2. **고정 컨텍스트를 다이어트한다**: `CLAUDE.md` ≤ 4KB, `DRAFT_NOTES.md` → 3KB 상태 파일 + 이력 아카이브, 커맨드 보일러플레이트 제거. (P2) — *`CLAUDE.md`는 완료(2026-10-05)*
3. **경계를 도구로 강제한다**: `tools/check_boundary.py`(스캐너) + pre-commit/CI + 반입 staging/rollback. ~~`export_external.py`~~ 는 2026-10-01 결정(사내→사외는 사용자 타이핑만)으로 제외. (P3)
4. **플랫폼 seam을 이름 있는 디렉토리로 올린다**: `S/platforms/android/`에 4곳의 상수를 모으고, `site-defaults.yaml`에 `platform:` 키를 둔다. 동작 변경 없음. (P4)
5. HANDOFF I0~I1을 먼저 끝낸다. (P6)

---

## B. Current Architecture (실제 코드 기준)

### B.1 레포와 역할

| 레포 | 내용 | 비고 |
|---|---|---|
| 이 레포 (`telephony-triage`, 플러그인 개발 레포) | `plugin/`(배포 본체), `docs/design/`(설계), `tests/`(모의 환경·fixture·eval), `tools/`(반입·뼈대·평가) | 사외 초안. `.local-draft`로 모드 판별 |
| `telephony-issue-db` (별도, 사내) | 유형·원인·시그니처·parser-rules·fixture·Jira 기록·피드백 | `tools/make_db_skeleton.py`가 뼈대 생성. 테스트는 `T/fixtures/issue-db-sample/` 합성본 |
| 사용자 홈 `~/.telephony-triage/` | `config.yaml`, `work/<작업 키>/{plan.json,state.json,wt/,draft/}`, `work/_snapshot`, `session.lock`, `pending-feedback/` | `S/common/userconfig.py`, `S/db_pr.py` |

### B.2 디렉토리·파일 구조 (LOC)

```
plugin/                                  # 배포 본체 (${CLAUDE_PLUGIN_ROOT})
├── .claude-plugin/plugin.json
├── commands/*.md (12)           ~ 30KB   # 얇은 진입점. 각각 SKILL.md 또는 reference 하나를 가리킨다
├── hooks/hooks.json                      # SessionStart → config.py sync-scripts-path, PreToolUse(Bash|mcp__.*|Write…) → guard.py
├── skills/telephony-triage/
│   ├── SKILL.md                 25.6KB   # analyze Step 0~8 + 실행 규칙 (267줄)
│   └── reference/ (8)           72KB     # write-flow 10K, record 10K, verify 10K, sync-pr 4K, db-authoring 27K, log-tags 4K, ril-requests 3K, fail-causes 3K
├── site-defaults.example.yaml            # 코드가 읽지 않음. 테스트 헬퍼가 site-defaults.yaml로 복사
└── scripts/ (12,932 LOC)
    ├── common/ (2,600 LOC)               # site_defaults, userconfig, issuedb, signatures, patterns, masking, compiled, parser_rules, builds, buildname, compat, dbpath, fixtures, gitscope, ghcli, mcptools, history, quality, rulediff, typedoc, yamldoc, yamlio, versions, exitcodes
    ├── parser_backends/ base.py(77) __init__(40) reference/(91) logcat.py(257) ril.py(89)
    ├── adapters/ base.py(31) __init__(37)        # site_* 는 SITE_PATHS (사내 전용)
    ├── migrations/0001_example_jira_tags.py
    ├── config.py 436 · code_roots.py 273 · jira_fields.py 278 · parse_logcat.py 743 · mask_pii.py 222 · match_signatures.py 409
    ├── db_add.py 1373 · db_pr.py 1109 · db_verify.py 910 · db_lint.py 698 · db_build.py 616 · db_review.py 484
    ├── db_regress.py 384 · db_migrate.py 382 · db_search.py 270 · db_precommit.py 201 · guard.py 601
tests/ (10,727 LOC + fixture 트리 7개 ≈ 3.6MB + mocks 652KB + skill_evals 472KB)
tools/ (919 LOC): import_draft, make_db_skeleton, offline_eval, list_site_todos, fix_exec_bits
docs/design/ (17 files, 406KB) · DRAFT_NOTES.md 136KB · CHANGES.md 57KB · GUIDE.md 17KB · REVIEW-10/11.md 41KB · PLUGIN_IMPROVEMENT_HANDOFF.md 27KB
CLAUDE.md 15KB · AGENTS.md 3KB · SITE_PATHS · README.md(빈 파일)
```

### B.3 User Request → 결과까지의 실제 흐름 (analyze 기준)

| 단계 | 실제 파일·함수 | 누가 실행 | 입력 → 출력 |
|---|---|---|---|
| User Request | `/telephony-triage:analyze <KEY> <logs> [--code] [--dry-run]` → `C/analyze.md` | Claude Code | `$ARGUMENTS` |
| Task/Intent 판단 | `K/SKILL.md` frontmatter `description`(트리거) + 커맨드가 가리키는 흐름 | LLM | 12개 커맨드 중 하나. 자연어 진입은 description 트리거 (`T/skill_evals/trigger_evals.json`) |
| Plugin/Tool 선택 | **없음(정적)**. SKILL.md의 "언제 → 읽을 파일" 표가 reference 8개 중 필요한 것을 LLM이 고르게 한다 | LLM | 커맨드 md → SKILL.md 전체 → reference 1~3개 |
| Context 생성 | Step 0: `config.py show`, `jira_fields.py check-key`, `db_pr.py lock acquire`, `db_pr.py cleanup --dry-run` / Step 1: `db_pr.py snapshot`(`snapshot()` → `git fetch`, worktree, `post_lint()` = `db_lint --all`), `config.py check`, `db_build.py --cache-only` | LLM이 Bash로 5~7회 호출 | 각 호출의 JSON 전체가 컨텍스트에 들어간다 |
| Source/Data 검색 | Step 2: Jira MCP(`jira.tools.get_issue` 매핑, `S/common/mcptools.py`) → `jira_fields.py extract --consume`(`extract()`: field_map, 마스킹) / Step 2-1: `code_roots.py suggest/validate`(`cmd_suggest`, `validate`, `estimate_version`) / Step 3: `parse_logcat.py parse --mask`(`run_parse` → `parser_backends.load` → `ReferenceBackend.parse` → `postprocess`: 태그 매핑→마스킹→RIL 파생→extractor→외부 파서) / Step 4: `match_signatures.py`(`match()`: S→C 2단계, `fix_judgement`, `_related`) / Step 5: `code_roots.py resolve/find-symbol`(`cmd_find_symbol`: 트리 전체 rglob) | LLM이 Bash로 4~6회 호출 | `JOB/jira_meta.json`, `JOB/events.json`(원 로그의 ~25배 크기, §C), `JOB/match.json` |
| LLM/Codex 전달 | 위 JSON들을 LLM이 읽음. Step 5-1 선택적 `analyzers.<category>` 스킬(`D/16 §16.5`) | LLM | 리포트 초안 |
| 분석 | 결정적: S/C·점수·`fix_judgement`는 `match_signatures.py`. LLM: 리포트 작문, 사실/추정 구분, 새 원인 초안(`K/reference/db-authoring.md`) | 둘 다 | Step 6 리포트 |
| 결과 생성 | Step 7: `plan.json` 작성(LLM) → `db_verify.py rules --plan --draft`(`make_draft`→`db_add apply`→R1~R6) / Step 8: `db_pr.py preflight → stage(drift→apply→build→lint→mask→check-ids→regress→verify) → summary → (LLM) git add/commit → publish(push --force-with-lease, gh pr create) → discard` | `db_pr.py`가 하위 스크립트를 subprocess로 호출(`run_script`) | PR |

- **LLM 호출 구조**: Python 코드는 어떤 LLM API도 부르지 않는다 (`grep` 결과: 외부 의존성은 `pyyaml`, `jsonschema`, `pytest`뿐). LLM은 오직 Claude Code 세션(스킬) 자체이고, 선택적 "분석 스킬"도 Claude Code 스킬 호출이다. `tools/offline_eval.py`는 같은 파이프라인(파서→매처)을 **LLM 없이** 돈다 — 이것이 "headless 실행이 이미 가능하다"는 증거다.
- **외부 시스템 통합**: Jira(MCP, 읽기 전용, `guard.py` 규칙 2로 차단), GHE(`gh` CLI, `S/common/ghcli.py`, `db_pr.publish`), git(worktree·lease push), 소스 트리(로컬 경로, `code_roots.py`). FTP/SFTP·스케줄러·Jira 쓰기는 **없다**.
- **설정 구조**: 사용자 config > `plugin/site-defaults.yaml` > 내장(`S/common/userconfig.py::merged`). 이슈 DB 쪽 고정값은 `issue-db.config.yaml`(`S/common/compat.py`).
- **테스트·빌드**: `pytest tests`(226개, 사외 Windows 999s; 이 컨테이너에서는 600s 안에 끝나지 않음 — 느린 이유는 §Q). 빌드 단계 없음. CI 없음(`ci_mode: local`). **이 컨테이너(Ubuntu, Python 3.11) 기준선: `pytest tests` 226 passed, 779s.** 스킬 eval은 `T/skill_evals/run.py`(`claude -p` 서브에이전트, 429 한도로 미실행).

### B.4 모듈 의존 (실측)

- 모든 스크립트 → `common.site_defaults.load_or_exit`(진입점에서 필수) → `common.*`.
- in-process import: `db_verify`·`db_regress`·`db_review` → `parse_logcat`, `match_signatures`; `db_review` → `db_add.similarity`.
- subprocess: `db_pr` → `db_lint/db_add/config/db_build/mask_pii/db_regress/db_verify`; `db_precommit` → `config/db_lint/mask_pii/db_regress/db_verify/db_build`; `guard` → `mask_pii/db_build`; `db_verify.make_draft` → `db_add apply`.
- 순환 의존은 없다. 다만 `db_pr`·`db_precommit`·`guard`가 같은 검사를 각자 조립한다(검사 오케스트레이션이 3곳 → **완료 (2026-10-04, common/checks.py)**).

---

## C. Token Usage Analysis

측정 근거: 사외 eval 실측(`DRAFT_NOTES.md` Phase 13 반복 1: 건당 8.4만~14.4만, 평균 11만; 반복 2: 6.4만~13.5만). 아래 분해는 파일 크기(bytes ÷ ~3.5 ≈ token, 한국어 섞임)와 호출 횟수에서 추정한 것이며, 실측 분해는 §U RF-1에서 `claude -p --output-format json`의 usage로 한다.

| 영향 | 어디서 | 근거 (파일·함수) | 추정 token / 건 | 왜 낭비인가 | 제안 |
|---|---|---|---|---|---|
| **High** | LLM이 Step 0~4의 CLI 15~20회를 직접 호출하고 각 JSON stdout(들여쓰기 `indent=1`)과 stderr 경고를 읽는다 | `K/SKILL.md` Step 0(7개 항목)·1(4)·2(6)·2-1(5)·3·4; 각 스크립트 `main()`의 `json.dump(..., indent=1)` | 3만~6만 | 결정적 순서를 LLM이 "기억하고 실행"한다. 호출마다 추론 토큰 + 출력 토큰 + 재시도(반복 1에서 10개 eval 모두 `--json` 위치 오류로 종료 코드 2를 1회씩 받음) | **`triage.py run`** 하나가 Step 0~4(+5의 resolve)를 수행하고 `analysis.json`(≤ 4KB) + `report.md` 초안만 낸다 (§U RF-1) |
| **High** | `SKILL.md` 25.6KB를 analyze마다 전부 로드 | `C/analyze.md` → `K/SKILL.md` | ≈ 8K | Step 0~4의 절차 서술(≈ 60%)은 driver로 옮기면 사라진다. 남는 것은 사용자 확인·분류 결정·Step 7·8 규칙 | SKILL.md를 **결정 규칙 + driver 호출** 중심 ≤ 8KB로 |
| **High** (사내 개발 세션) | `CLAUDE.md` 15KB 매 세션 + `@SITE_PROFILE.md` import + S-1 "읽을 것"에 `DRAFT_NOTES.md` 136KB | `CLAUDE.md` 머리말, `D/15 §15.5` S-1 행 | 세션당 ≈ 5K 고정 + 45K(DRAFT_NOTES를 읽는 세션) | 모드 판별표·문서 지도·원칙 12개가 매 세션 들어간다. DRAFT_NOTES는 Phase별 산출물 표·테스트 결과·가정 19개·TODO 57곳이 한 파일 | `CLAUDE.md` ≤ 4KB(모드 판별 3줄 + 읽을 파일 지시) [`CLAUDE.md`는 2026-10-05 완료], `DRAFT_NOTES.md` → `HANDOFF_STATE.md`(≤ 3KB: 모드·완료 Phase·다음 할 일·막힌 것) + `docs/history/draft-notes-2026-09.md`(아카이브, 읽지 않음) |
| **High** | `parse_logcat parse` 출력이 원 로그의 ~25배 | `T/fixtures/logs/data-disabled.log` 8줄 → `.events.json` 188줄·3.6KB; `dual-sim-ril.log` 11줄 → 304줄 | 로그 1,000줄(±5분 radio)이면 **수십만 바이트** — LLM이 `cat`하면 치명적 | 줄 레코드(`event: None`)마다 `msg` 원문 + 파생 이벤트에 **같은 `msg` 재복사**(`_derived()`), `indent=1` | events.json은 **LLM이 읽지 않는 파일**로 못 박고(이미 SKILL 규칙), driver가 `evidence`(근거 3~10줄)만 analysis.json에 넣는다. 파생 이벤트는 `line_ref`(파일·행)만 갖고 `msg` 복사 제거 (HANDOFF R7 provenance와 같은 수정) — *(2026-10-05: `line_ref` 추가 완료, 파생 이벤트의 `msg` 복사 제거는 아직 열림)* |
| Medium | Step 1 `db_lint --all --db SNAP` 매 analyze | `K/SKILL.md` Step 1-3, `S/db_pr.py::post_lint` (snapshot이 이미 수행) | 1K~5K (DB가 커질수록) | `sync`가 이미 하고, `snapshot()`도 `post_lint`를 돌린다 → **두 번** | snapshot 결과의 `post_lint` 요약(건수만)만 쓴다. SKILL Step 1-3 삭제 |
| Medium | `config.py show`가 `effective` 전체(field_map, analyzers, code_profiles, read_tools…)를 출력 | `S/config.py::cmd_show` | 1K~2K | Step 0에서 필요한 것은 `user_config` 유무, `work_dir`, `jira.tools.get_issue` 뿐 | `config.py show --keys work_dir,jira.tools` 또는 driver가 내부에서 읽음 |
| Medium | `db_pr summary` 확인 화면(README 미리보기 + 주요 diff + 검사표) + `pr_body` | `S/db_pr.py::summary/_readme_preview/_main_diff` | 2K~6K | 필요하다(승인 화면). 다만 diff 50줄 제한은 있고 README 미리보기는 카테고리 README 전체가 바뀌는 구조(기준일) 때문에 소음 | "기준일" 결정성 규칙 재검토(`DRAFT_NOTES` Phase 13 사용자 판단 항목) — README 머리의 기준일을 `STATS.md`로만 옮기면 카테고리 README diff 소음이 사라진다 |
| Medium | reference 중복: op 표가 `D/contracts.md`와 `K/reference/db-authoring.md §4`에 두 번, drift 표도 두 번; sync-pr 절차가 `C/sync-pr.md`(4.9KB)와 `K/reference/sync-pr.md`(4KB)에 두 번 | 파일 비교 | 새 원인 생성 시 +8K | 같은 표를 두 곳에서 유지 | db-authoring을 "작성 규칙 + 예시"만 남기고 op 표는 driver의 `plan validate` 오류 메시지가 대신 설명 (스키마가 source of truth) |
| Medium | 12개 커맨드 md에 같은 보일러플레이트 4줄("스크립트는 `python3 …`로 호출", "종료 코드 2와 사내 기본값 없음이면 멈춤" 등) | `C/*.md` | 건당 0.3K | 중복 | 공통 실행 규칙을 SKILL.md 상단 한 곳 또는 driver 오류 메시지로 |
| Low | `guard.py`가 Bash·MCP·Write마다 python 기동 + yaml 로드, `git commit`이면 `mask_pii --check --staged` + `db_build --verify --staged` 서브프로세스 | `hooks.json`, `S/guard.py::check_commit` | token 아님(지연 1~10초) | 올바른 안전장치. 다만 사내 자동화(스케줄러)에서는 hook이 없다 | 자동화 경로에는 같은 규칙을 **driver 내부 함수**로 호출 (§N) |
| Low | `jira_fields extract` 출력에 마스킹된 요약·설명·**코멘트 전체**가 들어간다 | `S/jira_fields.py::extract` `text.comments` | 0.5K~5K (코멘트 수에 비례) | 분석에 쓰는 것은 요약·설명 키워드와 발생 시각. 코멘트는 "발생 시각 후보" 정도 | `--comments last:3` 같은 결정적 절삭. 코멘트는 `JOB/jira_text.json`에 두고 LLM은 필요할 때만 |
| Low | 도구 schema 노출: 플러그인은 MCP 서버를 번들하지 않으므로 LLM에 노출되는 "도구"는 12개 커맨드 + 스킬 1개뿐 | `plugin/.claude-plugin`, `hooks.json` | 작음 | 문제 없음. Jira MCP 서버의 도구 수는 사내 서버에 달렸다(`jira.read_tools` 허용 목록으로 사용은 제한하지만 노출은 제한 못 함) | 변경 불필요 |

**결론**: 사내 token의 가장 큰 두 소비처는 (1) analyze 실행에서 LLM이 수행하는 CLI 오케스트레이션(건당 수만 token)과 (2) 개발 세션의 고정 컨텍스트(`CLAUDE.md`+`DRAFT_NOTES.md`)다. 둘 다 **구조 변경 없이 큰 재작성 없이** 줄일 수 있다.

---

## D. Data Reduction Plan

이 레포에서 "SIM/carrier/APN/operator Data"에 해당하는 것은 (a) 이슈 DB의 `sim` 카테고리 유형·fixture, (b) Jira `field_map`의 `carrier`·`sim_slot`, (c) 참고 문서 `fail-causes.md`·`log-tags.md`·`ril-requests.md`, (d) 이슈 DB config의 `android_versions_supported`·`build_compare`다. **SIM 전용 데이터셋은 core context에 없다.** 카테고리 지식은 이슈 DB(데이터)에 있고 스크립트가 읽으며, LLM 컨텍스트에는 매칭 결과만 들어간다. 그래서 "삭제"가 아니라 "로드 시점"의 문제다.

| Data | 현재 위치 | 로드 시점 | 분류 | 조치 |
|---|---|---|---|---|
| 이슈 DB 유형·원인·시그니처(전 카테고리) | 이슈 DB `*/type.md`, `.cache/compiled.json` | 스크립트만 읽음. LLM은 `match.json` 후보 ≤ 3개 + `db_search` 결과 | **C** (retrieval) | 유지. driver가 `analysis.json`에 후보·근거만 넣는다 |
| `parser-rules/` (tags/ril/extractors) | 이슈 DB | 스크립트만 | **C** | 유지 |
| fixture (양성/음성 로그) | 이슈 DB | `db_regress`·`db_verify`만 | **C** | 유지. LLM이 fixture를 읽는 경로는 없다 |
| `K/reference/fail-causes.md` (DataFailCause 등 코드표 3.3KB) | 플러그인 | "로그 해석이 필요할 때" LLM 선택 | **B/E** | 유지하되, 코드→이름 변환은 extractor `fields`로 이미 가능. 장기적으로 이슈 DB `docs/`나 `parser-rules/codes.yaml`(데이터)로 이동 후 `db_search`가 답하게 |
| `K/reference/log-tags.md`, `ril-requests.md` (7KB) | 플러그인 | 선택 | **B/E** | 같다. 실제 태그 목록은 `tags.yaml`이므로 문서는 "해석 안내"만 |
| Jira `field_map.carrier`, `sim_slot` | `site-defaults.yaml`, `jira_fields.py` | 매 analyze (작음) | **A**(carrier는 Jira 기록 필수 필드) / **B**(sim_slot: 듀얼 SIM 교차 검증에만) | 유지 |
| `android_versions_supported`, `build_compare`, `code_root_keys` | `issue-db.config.yaml` | 스크립트만 | **B** | 유지. §F에서 `platform:` 아래로 묶는다 |
| `code_profiles`, `recent_code_roots` | 사용자 config | Step 2-1에서 `code_roots suggest` 출력 | **B** (코드 분석을 건너뛰면 불필요) | driver가 `--code skip`이면 호출하지 않음 |
| `config.py show`의 `effective` 전체 | 사용자 config+site-defaults | Step 0 매번 | **D** (대부분 불필요) | §C 제안대로 키 지정 |
| `DRAFT_NOTES.md` TODO(SITE) 57곳 목록, Phase별 산출물 표 | 레포 루트 | S-1 세션 | **E** (반입 직후 1회만 필요) | `tools/list_site_todos.py` 출력으로 대체(이미 있음). 문서에서 제거 |
| `REVIEW-10.md`, `REVIEW-11.md` | ~~레포 루트~~ → `docs/history/` (2026-10-01 이동 완료) | 아무도 읽지 않아야 함 | **E→F** | `docs/history/`로 이동 (HANDOFF도 같은 제안) |
| `tests/fixtures/issue-db-*` 7개 트리의 `docs/`·`schema/`·`templates/` 사본 (각 ~80KB) | 테스트 | 테스트만 | **B** (변형 생성기가 재생성 가능) | `make_variant_dbs.py`가 이미 결정적으로 만든다 → 커밋 대신 생성으로 바꾸는 것은 §R에서 F 후보(테스트 속도·diff 소음과 교환) |

**SIM 데이터를 core context에서 얼마나 제거할 수 있는가**: 이미 0에 가깝다. 제거 대상이 아니라 **"LLM이 `events.json`·`type.md`·fixture를 직접 읽지 못하게 하는 규칙"을 driver 출력 형식으로 강제**하는 것이 실질적 조치다.

---

## E. Android Version Compatibility

Android 버전 변화에 **코드가** 반응해야 하는 지점(상수)과 **데이터가** 반응하는 지점을 나눈다.

| 지점 | 파일·심볼 | 결합 강도 | 버전 업 시 깨지는 조건 | 대응 |
|---|---|---|---|---|
| 소스 트리 검증 | `S/code_roots.py` `TELEPHONY_DIR = "frameworks/opt/telephony"`, `validate()` | 중 | AOSP가 telephony 디렉토리를 옮기면 모든 트리가 "aosp 루트 아님"으로 거부 | `platform.source_tree.required_dirs: [...]`(site-defaults 또는 이슈 DB config)로 이동 |
| 트리 버전 추정 | `S/code_roots.py` `VERSION_SOURCES` (3개 파일·regex) | 중 | release config 위치/형식 변경(S11에서도 미확인) | `platform.source_tree.version_sources: [{file, regex}]` 데이터로. 모두 실패 시 사용자 입력 신뢰(이미 그렇게 동작) |
| `code_refs` 경로 | 이슈 DB `type.md` `code_refs[{ref, symbol, android_versions}]`, `code_roots.py resolve/find-symbol` | 약 | 파일 이동 시 `resolve`가 `exists: false` → `find-symbol`로 재탐색 → `add-code-ref` op (이미 설계됨, `D/07 Step 5`) | 유지. 이것이 "버전 어댑터"의 올바른 형태(데이터 + 재탐색) |
| logcat 포맷 | `S/parser_backends/logcat.py` `THREADTIME_RE`, `TIME_RE`, `_STAMP` | 약 | logcat 출력 형식은 수년간 안정 | 백엔드 안에 두되 `platforms/android/`로 이동 |
| 슬롯 표기 | `logcat.py` `TAG_PHONE_RE`, `MSG_PHONE_PREFIX_RE`, `MSG_PHONE_SUFFIX_RE` | 중 | 벤더·버전마다 `[PHONE1]`/`[SUB1]` 표기 다름 (S20) | **데이터로**: `parser-rules/tags.yaml`에 `phone_id_patterns:` 섹션 추가(스키마 선택 필드, 없으면 코드 기본값) |
| RIL 태그·형식 | `S/parser_backends/ril.py` `RIL_TAGS={"RILJ"}`, `REQUEST_RE`… | 중 | 벤더 RIL 로그 태그(S10), RILJ 출력 변경 | `ril.yaml`에 `tags:`와 `formats:` 선택 섹션. 코드 기본값 유지 |
| bugreport 섹션 헤더 | `S/parse_logcat.py` `SECTION_RE`, `WANTED_BUFFERS` | 중 | dumpstate 헤더 문자열 변경(S21) | `platform.bugreport.section_regex` 설정 |
| 데이터 스택 태그 `DNC-/DN-/DPM-…` | 이슈 DB `tags.yaml` (데이터) | — | Android 13+ 확정. 코드에는 없음(`patterns.py` docstring 예시만) | 유지 |
| 실패 코드 해설 | `K/reference/fail-causes.md` | 약 | 열거 이름 변경 | §D: 데이터로 이동 |
| 스키마 `android_versions`, `android_versions_supported` | `type.schema.json`, `issue-db.config.yaml`, `db_review`(지원 종료 판단) | 약 | 새 버전 문자열 추가만 | 유지. 다른 플랫폼은 §G의 `platform_versions` 별칭으로 |
| 마스킹 규칙 | `S/common/masking.py` (IMSI/IMEI/ICCID/셀/IP/SIP 자격증명) | 약 | 통신 표준 식별자. 플랫폼 무관 | 유지 (generic telephony) |

**판정**: Android 버전 업에 **코드 수정이 필요한 곳은 `code_roots.py`의 상수 2개와 파서 백엔드의 regex 몇 개**뿐이고, 나머지는 이슈 DB 데이터(`parser-rules`, `code_refs`+`android_versions`)로 흡수된다. 설계는 이미 "Core ↓ Platform Interface ↓ Android Common ↓ Version Adapter(데이터) ↓ Vendor Adapter(site 백엔드·어댑터)"에 가깝다. 부족한 것은 **그 상수들을 설정/데이터로 빼고 디렉토리 이름으로 보이게 하는 것**이다. 자동 detection은 `estimate_version()` + bugreport `build.json` fingerprint + Jira `android_version` 3단 fallback이 이미 있다(`K/SKILL.md` Step 2-1).

---

## F. Platform Abstraction (Android-specific logic 분리)

현재 혼재 상태와 분리안. **새 추상 클래스는 만들지 않는다** — 이미 있는 `ParserBackend`를 그대로 "Platform Adapter"로 쓴다.

```
[generic core — 플랫폼 무관]        S/common/{signatures,patterns,compiled,issuedb,masking,fixtures,builds,…}
                                     S/match_signatures.py, S/db_*.py, S/jira_fields.py, S/config.py(대부분)
[platform interface]                 S/parser_backends/base.py  (ParserBackend.parse/coverage/builtin_events/version)
                                     S/adapters/base.py          (외부 파서 → ext.* 이벤트)
                                     이벤트 스키마 {ts,pid,tid,level,tag,msg,phone_id,category_hint,ril,event,fields,source}
[android common]  ← 지금 흩어짐      S/parser_backends/logcat.py, ril.py, reference/__init__.py,
                                     S/parse_logcat.py::extract-bugreport, S/code_roots.py 상수
[android version adapter — 데이터]   이슈 DB parser-rules/*, code_refs.android_versions, issue-db.config.yaml
[vendor/internal adapter — 사내]     S/parser_backends/site/ (SITE_PATHS), S/adapters/site_*.py, site-defaults.yaml
```

**제안 디렉토리 (이동만, 동작 동일)**

```
plugin/scripts/
├── platforms/
│   ├── __init__.py                 # load(name) → PlatformProfile {backend, bugreport, source_tree}
│   ├── android/
│   │   ├── __init__.py             # PROFILE: required_dirs, version_sources 기본값, bugreport section regex
│   │   ├── logcat.py               # ← parser_backends/logcat.py
│   │   ├── ril.py                  # ← parser_backends/ril.py
│   │   ├── bugreport.py            # ← parse_logcat.py의 extract-bugreport 부분
│   │   └── backend.py              # ← parser_backends/reference/__init__.py (ReferenceBackend)
│   └── generic/                    # §G: 태그 없는 "timestamp + message" 텍스트 로그 백엔드 (oFono/journal/syslog 공통 기반)
├── parser_backends/
│   ├── base.py                     # 그대로 (계약)
│   ├── __init__.py                 # load(name): "reference"→platforms.android.backend, "site"→parser_backends.site (사내)
│   └── site/                       # 사내 (SITE_PATHS) — 변경 없음
```

- `site-defaults.yaml`에 `platform: android`(기본) 추가. `parser.backend`는 그대로. `code_roots.py`는 `platforms.load(platform).source_tree`에서 `required_dirs`·`version_sources`를 읽는다.
- 호환: `parser_backends.load("reference")`가 계속 동작하도록 shim을 둔다(사내 `site` 백엔드가 `from ..reference import ReferenceBackend`를 import하므로 **re-export 유지** — `T/mocks/parser_backends/site/__init__.py` 참고).
- SKILL.md Step 2-1·5의 "Android 버전" 문구는 "플랫폼 버전"으로 일반화하되, 사용자 대화는 그대로 "Android 16"이라고 말해도 된다.

---

## G. Multi-platform Architecture (oFono / Linux / Yocto)

**최소 추상화 원칙**: 이슈 DB·매처·검증·PR 흐름은 이미 플랫폼 무관(이벤트 기반)이다. 플랫폼마다 필요한 것은 딱 셋이다.

| 필요 | Android (현재) | oFono / Linux / Yocto (추가 시) |
|---|---|---|
| ① 로그 → 이벤트 백엔드 | `ReferenceBackend` (threadtime, RILJ 페어링, `phone_id`) | `platforms/generic/backend.py`: `journalctl -o short-iso`/syslog/`ofonod -d` 텍스트 → `{ts, tag=unit|process, msg}`. `phone_id`는 modem path(`/ril_0`, `/hfp/…`)에서 추출하는 선택 regex. RIL 페어링 대신 **D-Bus method call/return 페어링**(선택, `pair_strategy: dbus`) |
| ② 규칙 데이터 | 이슈 DB `parser-rules/`(tags/ril/extractors) + 카테고리 6개 | **같은 파일 형식**. 카테고리는 `issue-db.config.yaml categories`(데이터)라 oFono용 이슈 DB는 `{data, call, network, sim, sms, ims}` 그대로 쓰거나 `voicecall, netreg, gprs, sim-manager…`로 바꿔도 코드 변경 없음. `ril.yaml`은 선택(없으면 RIL 파생 이벤트 없음) |
| ③ 소스 트리 프로필 | `required_dirs: [frameworks/opt/telephony]`, `version_sources` | `required_dirs: [src/, drivers/]`, `version_sources: [{file: configure.ac, regex: AC_INIT…}]`, Yocto면 `meta-*/recipes-connectivity/ofono/ofono_%.bb`의 PV |

- **플랫폼별 이슈 DB는 별도 레포**(또는 같은 레포의 `platform:` 키)로 두는 것이 간단하다. `issue-db.config.yaml`에 `platform: ofono`를 추가하면 `config.py check`가 플러그인의 `platform`과 대조한다(현재 `parser_backend` 대조와 같은 메커니즘, `S/common/compat.py::check_parser_backend`).
- 스키마의 `android_versions`는 이름을 바꾸지 않는다(마이그레이션 비용). oFono DB에서는 `android_versions: []`(전 버전)로 두고, 필요하면 schema v2에서 `platform_versions`로 별칭. **지금 하지 않는다.**
- 마스킹(`masking.py`)은 통신 식별자 중심이라 그대로 쓴다. Linux 로그에 흔한 호스트명·사용자명은 `mask.extra_rules`(이슈 DB config) 선택 항목으로.
- **Over-engineering 금지**: `connectors/`, `analyzers/`, `workflows/` 같은 디렉토리는 실제 두 번째 구현(§N 자동화)이 생길 때 만든다. 지금은 `platforms/`만 만든다.

---

## H. Confidentiality Boundary

### H.1 분류 (디렉토리·파일 단위)

| 분류 | 경로 | 비고 |
|---|---|---|
| **PUBLIC / EXTERNAL-SAFE** | `plugin/scripts/**` (단, `parser_backends/site/`, `adapters/site_*` 제외), `plugin/commands/`, `plugin/hooks/`, `plugin/skills/`, `plugin/site-defaults.example.yaml`, `plugin/.claude-plugin/`, `docs/design/`, `docs/development/`, `tests/**` (단, `tests/golden/`, `tests/site/` 제외), `tools/`, `CLAUDE.md`, `AGENTS.md`, `GUIDE.md`, `CHANGES.md`, `SITE_PATHS`, `.gitattributes`, `.gitignore` | 전부 모의 값·placeholder. `grep`으로 사내 문자열이 없음을 확인함(`mock-org`, `MOCK-*`, `ghe.mock.invalid`만 존재) |
| **INTERNAL-IMPLEMENTATION** | `plugin/scripts/parser_backends/site/` (포팅한 검증 파서), `plugin/scripts/adapters/site_*.py` (기존 파서 어댑터), `tests/golden/*.orig.json` (실 로그 골든), `tests/site/` (실 로그 테스트·`offline-eval.yaml` 라벨셋) | 사내 소스·로그를 알아야 쓸 수 있는 코드·데이터. 전부 `SITE_PATHS`에 이미 등록됨 |
| **INTERNAL-DATA-ONLY** | `plugin/site-defaults.yaml` (Jira 서버·도구 이름·field_map·GHE host·external_parsers 명령), `SITE_PROFILE.md`, `docs/site/`, `.draft-manifest.json`, 운영 이슈 DB 레포 전체(`issue-db.config.yaml`의 `jira_base_url`·`jira_key_regex`·`fix_ref_regex`·`build_compare`·CODEOWNERS 팀, `parser-rules/` 실제 문구, 마스킹 fixture) | generic 코드는 사외, 값만 사내. 이슈 DB는 "마스킹된 로그 + 사내 로그 문구"라 **반출 불가** |
| **SECRET** | 사용자 홈 `~/.telephony-triage/config.yaml`(GHE id, 경로), `gh` 인증, Jira MCP 서버의 자격증명(플러그인 밖), `TT_PUBLISH_TOKEN`(승인 해시, 비밀은 아님) | 레포에 없음. `work_dir`은 700 권한(`userconfig.ensure_private_dir`). 레포 안에 토큰·비밀번호 문자열 없음(grep 결과는 마스킹 규칙 `CRED` 정의와 문서 언급뿐) |

### H.2 경계 다이어그램

```
EXTERNAL-SAFE (이 레포 그대로; 외부 Codex가 자유롭게 개발·테스트)
┌──────────────────────────────────────────────────────────────────────────┐
│ plugin/scripts/{common,parser_backends/base.py,platforms/android,…}      │
│ plugin/{commands,skills,hooks}  docs/design  tests/{mocks,fixtures,…}    │
│ tools/{import_draft,check_boundary*,offline_eval,…}                      │
│                                                                          │
│   Stable contracts: ParserBackend · Adapter(convert) · 이벤트 스키마 ·    │
│   jira_fields 출력(NormalizedIssue) · plan.json(op 표) · analysis.json*  │
└───────────────────────────────┬──────────────────────────────────────────┘
================================ SECURITY BOUNDARY (SITE_PATHS allowlist + export tool + scanner) ================================
┌───────────────────────────────┴──────────────────────────────────────────┐
│ INTERNAL-ONLY (사내 레포에만 존재. 반출 도구가 절대 포함하지 않음)          │
│ plugin/site-defaults.yaml        ← Jira/GHE/외부 파서 명령 값               │
│ plugin/scripts/parser_backends/site/   ← 검증된 사내 파서 포팅             │
│ plugin/scripts/adapters/site_*.py      ← 기존 파서 어댑터                  │
│ tests/golden/ · tests/site/ · docs/site/ · SITE_PROFILE.md · .draft-manifest.json │
│ 운영 이슈 DB 레포(실 로그 문구·마스킹 fixture·Jira 기록)                    │
│ 사용자 홈 config · 실 logcat · Jira 원문 · 소스 트리                       │
└──────────────────────────────────────────────────────────────────────────┘
(*: 이 문서가 추가를 제안하는 것)
```

### H.3 현재 경계 장치의 평가

| 장치 | 있음? | 평가 |
|---|---|---|
| allowlist 목록 (`SITE_PATHS`) | ✅ | 좋다. 사내 전용 경로를 **목록으로** 관리 |
| 반입(사외→사내) 도구 `import_draft.py` | ✅ | 기준선 해시로 "사내에서 고친 사외 파일"을 멈춘다 — 이것이 사내 코드가 사외 파일에 스며드는 것을 막는 유일한 장치 |
| **반출(사내→사외) 도구** | ❌ | 없다. 사내에서 사외 요약을 "사람이 만들어" 옮긴다 (`D/15 §15.6`) |
| 비-SITE_PATHS 파일의 사내 문자열 검사 | ❌ | 없다. `test_site_paths_are_absent_in_draft`는 경로 부재만 |
| secret 스캔 | ❌ (마스킹 검사는 이슈 DB 전용) | 플러그인 레포에는 없다 |
| 모의 값 표식 | ✅ | `mock-*`, `MOCK-*`, `*.mock.invalid`, `TODO(SITE:S<n>)` 관례 |
| 런타임 모드 판별 없음 | ✅ | `site-defaults.yaml` 없으면 멈춤. 사외 코드가 사내 값을 하드코딩할 유인이 없다 |

---

## I. Internal AI Token Optimization (사내 Claude Code)

사내 AI가 해야 하는 일은 다섯 가지뿐이어야 한다: ① S-1~S-3 값 입력, ② site 백엔드 포팅/어댑터, ③ 실 로그로 `parser-rules` 보정, ④ 실 Jira/로그로 dry-run 검증, ⑤ 사외 반입 후 테스트. 각각에 필요한 컨텍스트를 **task context pack**으로 고정한다.

| 사내 작업 | 읽어야 하는 것 (전부) | 대략 크기 | 지금과의 차이 |
|---|---|---|---|
| S-1 값 조사 | `HANDOFF_STATE.md`(≤3KB), `tools/list_site_todos.py` 출력, `D/14 §14.2` 표 | ≈ 8KB | 지금: `DRAFT_NOTES.md` 136KB + `REVIEW-OPEN.md` + `CLAUDE.md` 15KB |
| site 백엔드 포팅 | `S/parser_backends/base.py`(77줄), `platforms/android/backend.py`(91), `logcat.py`(257), `ril.py`(89), `T/mocks/parser_backends/site/__init__.py`(74, 예시), `T/test_golden.py` 사용법 절 | ≈ 600줄 ≈ 6K token | 설계 문서를 읽을 필요 없음. 이미 이 정도이지만 "읽을 것" 목록이 문서에 없어 agent가 탐색한다 |
| 어댑터 | `S/adapters/base.py`(31), `T/mocks/adapters/site_data_existing.py`(92) | ≈ 1.5K | 같음 |
| parser-rules 보정 | `D/04 §5.8 (2)`만, `parser-rules.schema.json`, 실패한 `db_regress` 출력 | ≈ 5K + 로그 발췌 | `parse_logcat cut`으로 구간만 |
| RIL/IMS 실 로그 분석 (분석 사용) | driver의 `analysis.json` + 근거 로그 10줄 + 해당 원인 `db_search` 결과 | ≈ 2~4K | 지금: SKILL.md 8K + 호출 15회 |

구체 장치:

1. **`tools/context_pack.py <task>`**: `docs/tasks/<task>.yaml`에 적힌 파일 목록을 한 번에 이어 붙여 stdout(또는 `--list`). agent는 "pack을 읽는다" 한 문장으로 끝난다. 결정적이고 token 0.
2. **`HANDOFF_STATE.md`** (루트, ≤ 3KB) — *구현(2026-10-01)은 새 파일 대신 `DRAFT_NOTES.md` 자체를 ≤8KB 상태 파일로 축소하는 것으로 대체했다*: 모드, 완료 Phase, 다음 할 일 3개, 막힌 것, 마지막 테스트 결과 한 줄. `DRAFT_NOTES.md`·`SITE_PROFILE.md`의 "진행 상태" 절을 여기로 **이동**(둘 다 이 파일을 가리킴). `CLAUDE.md`는 "`HANDOFF_STATE.md`를 읽고 그 Phase의 pack을 읽어라"만 남긴다.
3. **`docs/ARCHITECTURE.md`** (1페이지, ≤ 6KB): B.3 흐름표 + 계약 목록 + 디렉토리 → 어떤 agent든 레포 전체를 다시 분석하지 않게.
4. **driver 출력 계약**: LLM이 읽는 파일은 `analysis.json`(≤ 4KB)·`report.md`·`summary.json`(확인 화면)뿐. `events.json`·`match.json`·`type.md`·fixture는 "읽지 않는 파일" 목록으로 SKILL.md에 명시(이미 부분적으로 있음).
5. **캐시·재사용**: `<work_dir>/<KEY>/analysis.json`에 입력 해시(로그 파일 sha256, `parser-rules` 해시, 스냅샷 SHA)를 넣어 같은 입력이면 driver가 재계산을 건너뛴다(HANDOFF R14의 "분석 manifest"와 같은 것).
6. **symbol-level retrieval**: `code_roots.py find-symbol`은 트리 전체 `rglob`(HANDOFF R15). `--index`(한 번 만든 `symbols.json`: `Class#method → file:line`)를 두면 Step 5가 1회 호출·수십 바이트 출력이 된다. 사내 소스 트리 색인은 사내에만 남는 데이터다.

---

## J. Contract / Domain Model

이미 있는 계약을 **이름 붙여 고정**하고, 없는 것 중 꼭 필요한 둘만 추가한다.

| 모델 | 지금 어디에 (사실상 존재) | 상태 | 조치 |
|---|---|---|---|
| **NormalizedLogEvent** | 파서 이벤트 `{ts(UTC ISO), pid, tid, level, tag, msg, phone_id, category_hint, ril{serial,dir,request,error,paired_ts,latency_ms}, event, fields{str}, source}` (`S/parser_backends/base.py` docstring, `D/07 Step 3`) | 안정. 문서로만 정의 | `S/common/events.py`에 `TypedDict` + `validate_event()` + `schema_version`. 파생 이벤트의 `msg` 복사 대신 `line_ref: {file_index, line_no}` 추가 (HANDOFF R7) — *(2026-10-05: `line_ref`는 추가됨(`D/04 §5.8 (6)`), `msg` 복사 제거는 열림. `common/events.py`는 `line_ref`를 포함해야 한다)* |
| **ParserBackend** | `base.py` `parse(paths, tz, year, window)`, `coverage()`, `builtin_events()`, `version()` | 안정 | 그대로. `name`·`platform` 속성 추가 |
| **ExternalParserAdapter** | `adapters/base.py` `ADAPTER_NAME, VERSION, convert(raw, meta)` | 안정 | 그대로 |
| **NormalizedIssue** | `jira_fields.py extract` 출력 `{key, jira{model,sw,android_version,carrier,occurred_on}, occurred_at, text{summary,description,comments[]}, sim_slot, components[], missing[]}` | 안정 | 이름만 붙이고(`S/common/issue.py`), **Jira 외 소스**(파일, 다른 트래커)도 같은 형식을 내게. `comments`에 `created`·`index`를 넣어 선택 절삭 가능하게 |
| **AnalysisRequest / AnalysisResult** *(신규)* | 없음. `tools/offline_eval.py::evaluate_item`가 비공식 request(`{key, logs, occurred_at, sw, summary, description, expect}`)고, `match.json`이 비공식 result | 신규 | `triage.py run` 입출력. Result = `{request_hash, snapshot_sha, coverage, candidates[≤3]{type,cause,score,confidence,S,C,evidence[≤10 line_ref+masked text],fix_judgement,related}, pending_causes, no_candidate_hints{search_hits, error_events}, code{roots, resolved[], moved[]}, warnings}` ≤ 4KB |
| **WorkPlan** | `plan.json` (`D/contracts §작업 계획`, `schema/plan.schema.json`) | 안정 | 그대로 |
| **NormalizedSourceReference** | `code_refs {ref: "<root>:<rel>", symbol, android_versions}` + `code_roots resolve` | 안정 | 그대로 |
| NormalizedComment / StackTrace / Change | — | **만들지 않는다** | 필요가 생기면(§S 사용 사례) 그때 |
| **LogSourceRef** *(§N에서만)* | 없음 | 자동화 때 | `{kind: local|ftp|sftp|jira-attachment, uri, sha256}` → 로컬 경로 |

계약 보관 위치: `docs/design/contracts.md`(산문)와 **코드의 `TypedDict`/JSON Schema**를 함께 둔다. 현재 `plan.schema.json`은 이슈 DB 레포에 있는데, **플러그인 레포에도 사본**(`plugin/schemas/`)을 두어 사외 테스트가 이슈 DB 없이도 스키마 검증을 하게 한다(현재는 fixture DB 7벌에 복사되어 있음).

---

## K. Parser Architecture

```
raw log ──▶ [platform backend: 포맷·시각·슬롯·페어링] ──▶ line events
                 │  (android/reference, android/site(사내), generic/…)
                 ▼
          [parse_logcat.postprocess — 플랫폼 무관]
            태그→카테고리(tags.yaml) → 마스킹(--mask) → RIL 파생(ril.yaml) → extractor(extractors.yaml) → 외부 파서 merge/replace
                 ▼
          NormalizedLogEvent[] (masked: true) ──▶ match_signatures / db_regress / db_verify
```

- **Generic framework** (사외): `parse_logcat.py`의 `postprocess()`·`_run_extractors()`·`_run_external()`, `common/parser_rules.py`, `common/patterns.py`(정규식 시간 상한), `common/masking.py`.
- **Parser interface** (사외): `ParserBackend`, `Adapter`.
- **Internal implementation** (사내, 작게): `parser_backends/site/`가 `ReferenceBackend`를 상속해 `detect()`만 구현(`T/mocks/parser_backends/site/__init__.py` 74줄이 모범). 또는 어댑터 `site_*.py` 100줄 내외. 골든 테스트 `T/test_golden.py`(사외) + `tests/golden/*.orig.json`(사내).
- 이 구조는 이미 요구한 모양이다. 남은 수정은 (1) §F의 디렉토리 이동, (2) §E의 regex 데이터화(선택), (3) HANDOFF R4(회전 파일 페어링)·R5(외부 파서 실패 전파), (4) ~~`line_ref` provenance~~(2026-10-05 완료).
- **proprietary RIL/IMS 파서**: 사외 코드는 `RILJ` AOSP 형식만 안다. 벤더 RIL/IMS 로그는 사내 `site` 백엔드의 `detect()`가 `builtin.<cat>.*`로 내거나 `ril.yaml`/`extractors.yaml`(데이터)로 표현한다. 사외 매처는 이벤트 이름만 본다 → **외부 analyzer가 원시 포맷을 알 필요 없음**이 이미 성립.

---

## L. Synthetic / Mock Test Strategy

이미 갖춰진 것 (전부 사외, 실 데이터 0):

| 모의 대상 | 구현 | 상태 |
|---|---|---|
| Jira | `T/mocks/jira_mcp/server.py` (stdio MCP, 비표준 도구 이름, 쓰기 도구 포함), `T/mocks/jira/*.yaml`, `call.py` | ✅ |
| GHE | `T/helpers/make_repo.py` bare 원격 + `T/mocks/bin/gh` 스텁(상태 `gh-state/`) | ✅ |
| logcat | `T/mocks/logcat_gen.py` + `scenarios/*.yaml` (슬롯·시계 이상·bugreport 래핑) | ✅ |
| 소스 트리 | `T/mocks/src/android16|17` (심볼 스텁, 16/17 경로 차이) | ✅ |
| 사내 파서/어댑터/분석 스킬 | `T/mocks/parser_backends/site`, `adapters/`, `skills/data-analyzer` | ✅ |
| 이슈 DB | `T/fixtures/issue-db-sample` + 변형 6개 (`make_variant_dbs.py`) | ✅ |
| 플러그인 루트 | `T/helpers/make_plugin_root.py` (example → site-defaults.yaml) | ✅ |
| 빈 플러그인 실험 | `T/mocks/plugin-probe/` | ✅ (실행 미확인) |

추가로 필요한 것:

1. **synthetic RIL-like / IMS-like source**: `T/mocks/src/android16/vendor/mockril/libril/mock_ril.c`(3줄)가 유일. §S의 "소스↔로그 상관" 사용 사례를 위해 로그 문구를 출력하는 함수가 있는 스텁 5~10개(합성)로 확장 — 사내 소스를 흉내 내지 않고 **형태만**.
2. **fake FTP/SFTP**: §N 커넥터 테스트용. `pyftpdlib`/`paramiko` 의존을 피하려면 `LogSource` 추상 위에 `LocalDirSource`를 두고 FTP 구현은 사내에서 (또는 `tests/mocks/ftp_stub.py`로 "URI→로컬 복사" 가짜).
3. **generic/oFono 합성 로그**: `T/mocks/ofono_gen.py` + 시나리오 3개(등록, 데이터 컨텍스트 실패, SIM 미인식) — RF-5에서.
4. **external-only CI**: `.github/workflows/external.yml`(이 레포는 GitHub) — `pytest -x -q`, `tools/check_boundary.py`, `make_sample_fixtures.py --check`, `make_variant_dbs.py --check`. 사내 GHE Actions 유무(S6)와 무관하게 **사외 CI는 지금 만들 수 있다**.
5. 테스트 속도: 현재 전체 10분+. 원인은 테스트마다 `make_plugin_root.make()`(plugin/ 전체 복사) + 임시 git 레포 생성 + 서브프로세스. `session` 범위 fixture로 플러그인 루트를 1회 복사하고, 서브프로세스 대신 `main(argv)` 직접 호출을 기본으로 → 외부 CI 비용과 사내 검증 시간 모두 절감 (§Q).

핵심 원칙 준수: 실제 사내 데이터의 익명화 반출은 어디에도 전제하지 않는다(`D/15 §15.5` S-0도 "정성 결론만").

---

## M. Repository Strategy

| 기준 | Option A: Monorepo (한 레포, 디렉토리 경계) | Option B: `project-core` + `project-internal` 분리 | **권장: A′ = 사외 레포(core) + 사내 레포(= core 전체 + SITE_PATHS overlay)** |
|---|---|---|---|
| 보안·accidental leakage | 사람이 사내 파일을 사외 경로에 넣을 수 있음 | 레포 자체가 경계. 가장 안전 | 사내 레포는 사외와 **같은 트리 + overlay**. 반출 도구는 없다(결정 a: 사용자 타이핑만). 반입 충돌·staging·rollback으로 B 수준 안전, A 수준 편의 |
| 개발 편의 | 최고 | import 경로·설치 경로가 두 레포에 걸침 | 사내에서 `import_draft.py` 한 번, 사외로는 사용자가 문장으로 전달 |
| 플러그인 설치 | `${CLAUDE_PLUGIN_ROOT}` 한 트리 | 설치 전 **compose 단계** 필요(`parser_backends.site`는 패키지 안에 있어야 import됨) | 한 트리 |
| CI | 하나 | 둘 + 통합 | 사외 CI(합성) + 사내 테스트(골든) |
| interface 호환 | 같은 커밋 | 버전 핀 필요 | `.draft-manifest.json` label이 사실상 버전 |
| 버전 관리 | 단순 | core 버전과 internal 버전 매트릭스 | 사내 레포 커밋이 "core label + overlay" |
| 테스트 | 한 suite | core suite + internal suite | 사외 suite(합성) + `tests/site`·`tests/golden`(사내) |
| 외부 Codex 활용 | 사내 레포는 못 줌 | core 레포 그대로 | 사외 레포 그대로 |
| 사내 token | 사내 AI가 레포 전체를 봄 | 내부 레포만 보면 됨 (작음) | 사내 레포에서 pack만 읽음(§I). overlay 디렉토리가 작아서 B와 같은 효과 |
| 현재 코드와의 거리 | 현재 상태 | 큰 재구성(패키징·네임스페이스) | **현재 설계 그대로** + 도구 2개 |

**결론**: 현재의 `SITE_PATHS` + `import_draft.py` 설계는 이미 A′다. 분리 레포(B)로 가면 `parser_backends/site`·`adapters/site_*`를 플러그인 트리에 합치는 compose/빌드 단계가 필요해지는데, 그 compose가 바로 "overlay"이고 지금 디렉토리 규칙이 그것을 git으로 해결하고 있다. 따라서 **레포를 나누지 않고 반출 도구와 검사기를 추가**하는 것이 가장 작은 변경으로 가장 큰 안전을 준다. 사내 overlay가 커져서(예: 사내 파서가 수천 줄) 사외 코드와의 비율이 뒤집히면 그때 B를 다시 검토한다.

---

## N. Automation Architecture (Jira → FTP → Log → Source → LLM → Jira)

```
[scheduler: cron/Routine]                                      사내
   │  (deterministic)                                           ─────────────────────────────────
   ▼
jira_poll  ──(JiraReader.search since=last_run, assignee/team)──▶ NormalizedIssue[]        ← 사내 JiraReader(MCP 또는 REST) 구현; 인터페이스·필터·상태 저장은 사외
   │ filter: 변경됨 && (첨부/로그 위치 있음) && (아직 미분석 or 입력 해시 변경)
   ▼
log_fetch  ──(LogSource.fetch(LogSourceRef))──▶ 로컬 파일                                  ← 사내 FTP/SFTP 구현; LocalDir 구현은 사외
   │ parse_logcat extract-bugreport / parse --mask (±5분 또는 --full 스캔)
   ▼
triage.py run  ──▶ analysis.json (후보 ≤3, 근거, 범위, fix_judgement) + report.md 초안      ← 전부 사외 (지금의 Step 0~4 = offline_eval 경로)
   │
   ├─ 후보 있음 & high confidence  ──▶ comment_draft.md (템플릿: 분류·근거 로그 10줄·해결책·검증 상태)   (LLM 불필요)
   ├─ 후보 없음 / low / 다중 후보   ──▶ LLM 1회: analysis.json + 근거 + db_search 상위 3 → 가설·반대 근거·추가 확인 요청 초안
   ▼
state.json (issue → {input_hash, result_hash, status: analyzed|drafted|approved|posted})
   ▼
approval gate (mode: analysis-only | draft | approve-then-post | auto-post)                 ← 사외(인터페이스·상태 머신), 기본 analysis-only
   ▼
JiraWriter.post_comment  (guard 규칙 2는 Claude 세션 전용이므로, 자동화에는 writer 자체에 allowlist·mode 검사)   ← 사내 구현
```

- **분리**: Scheduler(사외: `tools/triage_batch.py --since`; 실제 cron은 사내), Jira connector(인터페이스 사외 / 구현 사내), FTP connector(동일), Log collector(사외: 다운로드→로컬 경로→해시), Log parser(사외+site), Source analyzer(사외 `code_roots` + 사내 트리), LLM reasoning(사외 프롬프트 템플릿: `triage_prompt.md`; 실행은 사내 Claude), Context builder(사외: `analysis.json` 조립), Report/comment generator(사외 템플릿), Jira writer(인터페이스 사외/구현 사내), State storage(사외: `<work_dir>/batch/state.json`), Permission layer(사외: mode 상태 머신 + 사내 allowlist).
- **외부에서 개발·테스트 가능한 비율**: 위 10개 구성요소 중 8개는 전부 사외, 2개(Jira 구현, FTP 구현)는 인터페이스만 사외. 모의 Jira MCP와 `LocalDirSource`로 end-to-end가 사외에서 돈다.
- **LLM 사용 최소화**: 후보가 high confidence로 하나면 LLM을 부르지 않는다(결정적 템플릿). LLM은 "후보 없음"(초기 DB에서 흔함)과 "다중 후보"에서만, 입력은 `analysis.json` ≤ 4KB + 근거 ≤ 10줄.
- **현재 architecture 위에서 구현 가능한가**: 가능하다. `tools/offline_eval.py::evaluate_item`이 이미 "Jira 메타 + 로그 → parse → match"를 LLM 없이 한다. 부족한 것은 Jira 검색(`jira.tools.search_issues`가 선택 매핑으로 이미 있음), 상태 저장, writer, 승인 모드다. **선행 조건**: HANDOFF R2(lock)·R3(경로)·R5(외부 파서 실패 전파) — 사람이 없는 실행에서 치명적.
- **Human approval 모드**: `site-defaults.yaml`/사용자 config `automation.mode: analysis-only|draft|approve|auto`(기본 `analysis-only`). `approve`는 `<work_dir>/batch/<KEY>/comment_draft.md`에 사람이 `approved: true` 프런트매터를 붙여야 post. `auto`는 `confidence: high` + `resolution_verification: verified`일 때만.

---

## O. Plugin / Tool Loading Strategy

현재 LLM에 노출되는 것: 커맨드 12개(각 1~5KB, 호출 시에만 본문 로드), 스킬 1개(description만 상시, 본문은 트리거 시), hooks 3개(토큰 아님), Jira MCP 도구(사내 서버가 노출하는 전부). "불필요한 tool/schema" 노출은 사실상 없다. 개선은 **커맨드 안에서 무엇을 로드하느냐**다.

| 지금 | 제안 |
|---|---|
| `C/analyze.md` → `K/SKILL.md` 전체(Step 0~8) → 상황에 따라 reference | `C/analyze.md` → `K/SKILL.md`(결정 규칙 ≤ 8KB) → `triage.py run`이 analysis.json을 냄 → Step 7·8 때만 `reference/write-flow.md` |
| `record`·`verify-fix`·`fix-submitted`·`validate`는 자기 reference를 읽고 SKILL.md는 읽지 않음 (좋음) | 유지. 단 `K/reference/record.md`가 SKILL Step 0/2를 다시 참조하는 중복 제거(HANDOFF R12) |
| 새 원인 작성 시 `db-authoring.md` 27KB | "작성 규칙(§2)·파일 형식(§3)·점검표(§6 표)"만 남긴 ≤ 10KB. op 표·drift 표·fixture 표·R1~R6 표·상태 값·브랜치는 **스키마와 driver 오류 메시지**가 안내 (`db_add apply`의 `Reject` 메시지가 이미 상세함) |
| 분석 스킬(`analyzers.<category>`)은 1위 카테고리가 맞을 때만 `ask` | 유지. 이것이 "capability selection"의 올바른 예 |
| 로그 해석 reference 3개(10KB) | 유지(선택 로드). 장기적으로 이슈 DB 데이터 |

"Intent → Capability Selection"은 커맨드 체계가 이미 그 역할이다. 별도 라우터·레지스트리는 **만들지 않는다**. 자연어 진입(HANDOFF R14)은 description 트리거로 충분하다.

---

## P. Deterministic vs LLM Processing

| 작업 | 지금 | 목표 | 비고 |
|---|---|---|---|
| Jira 키 검사, lock, 스냅샷, 호환성 검사, 캐시 | 결정적(스크립트) — **LLM이 순서대로 호출** | 결정적 — driver 내부 | Step 0·1 |
| Jira 읽기·field_map·마스킹 | 결정적(`jira_fields`) — MCP 호출은 LLM | MCP 호출만 LLM(또는 사내 reader), 나머지 driver | MCP 도구는 Claude 세션에서만 부를 수 있으므로 `triage.py run --jira-raw JOB/jira_raw.json` 형태로 LLM이 먼저 저장 |
| 발생 시각 없을 때 증상 시각 후보 | 결정적(`parse --full` + `--regress`) — LLM이 호출·제시 | driver가 후보 3개를 analysis.json에 | 사용자 선택만 LLM |
| 코드 경로 후보·검증·버전 추정 | 결정적(`code_roots`) | driver | 선택만 LLM |
| 파싱·마스킹·매칭·fix 판단·related | 결정적 | 동일 | 핵심은 이미 올바름 |
| `code_refs` 해석·심볼 재탐색 | 결정적(`resolve`, `find-symbol`) | driver + 색인 | |
| 로그 문구로 코드 역검색·분기 조건 추적 | **LLM** (`grep`/Read) | LLM, 단 `find-symbol --index`·`grep -n` 결과 상위 N줄만 | 소스 읽기는 필요한 함수만 |
| 리포트 작문 | LLM | 템플릿(driver)이 뼈대, LLM은 "원인 설명·사실/추정 구분·다음 확인" 문단만 | high confidence 단일 후보는 LLM 없이도 완성 가능 |
| 분류 확정·새 원인/유형 초안·시그니처 초안 | LLM + 사용자 | 동일 | 창의적 부분. 유지 |
| 초안 검증 R1~R6, stage·summary·publish | 결정적 | 동일 | |
| drift·allow-cause 결정 | 사용자 | 동일 | |
| 복합 원인 추론, 미지 패턴 해석, 여러 근거 상관 | LLM | 동일 | 유일하게 LLM이 가치를 내는 곳 |

---

## Q. Maintainability Issues

| 항목 | 근거 | 영향 | 조치 |
|---|---|---|---|
| 큰 모듈 | `db_add.py` 1373줄(`Applier` 클래스가 op 16개 처리), `db_pr.py` 1109, `db_verify.py` 910 | 수정 시 넓은 컨텍스트 필요 | `db_add`를 `ops/<op>.py`로 분할(계약은 동일) — **완료 (2026-10-05)**: `db_add.py`는 CLI(112줄), 구현은 `dbadd/`(op 묶음별 믹스인 7개). `db_pr`의 `summary/pr_body`를 `db_summary.py`로(미완) |
| 검사 오케스트레이션 3곳 | `db_pr.stage`, `db_precommit`, `guard.check_commit`가 각자 lint/mask/build/regress/verify 호출 순서를 가짐 | 규칙 drift | **완료 (2026-10-04, common/checks.py)**: `run_checks(profile, ctx)`와 프로필 stage/precommit/guard, `aggregate` |
| 서브프로세스 재진입 | `db_pr` → 7개 스크립트 subprocess, 각 스크립트가 `site_defaults.load_or_exit` + 이슈 DB 전체 로드 | 느림(stage 수십 초), 테스트 10분+ | **완료 (2026-10-04)**: `checks.run_script`가 같은 프로세스에서 `main(argv)` 호출(종료 코드 계약 유지, `TT_SCRIPT_SUBPROCESS=1`이면 subprocess) + 정규식 작업 프로세스를 runner마다 띄우지 않고 프로세스 안에서 공유(`common/patterns.py`). `test_db_pr`+`test_checks` 418s → 138s |
| HANDOFF R1~R15 | lock 비원자(R2), 경로 삭제 안전(R3), `commit -m "<msg>"` 인용(R6), 교차 슬롯 S/C(R1), 회전 파일 RIL(R4), 외부 파서 실패 전파(R5), provenance(R7), 점수 포화(R8) | 정확성·안전 | 그 문서의 I0~I2 (R7 완료·R15 부분 완료 2026-10-05) |
| 중복 문서 | §C 표. 추가로 `CLAUDE.md` 문서 지도(2026-10-05 `D/README.md`로 이동) ↔ `D/01 §3` 트리 ↔ `AGENTS.md` 구조 절 | 세 곳 유지 | `docs/ARCHITECTURE.md` 하나 + 나머지는 링크 |
| 임시·이력 파일이 루트에 | `DRAFT_NOTES.md`, `REVIEW-10.md`, `REVIEW-11.md`, `CHANGES.md`(57KB) | 새 agent가 모두 열어봄 | `docs/history/`로 이동, 루트에는 `HANDOFF_STATE.md`만 |
| Windows 전용 보정 | `tools/fix_exec_bits.py`, `T/helpers/mock_env.py`의 `.cmd` shim, `encoding="utf-8"` 산재 | 배포 대상은 Ubuntu | 유지(해롭지 않음). CI는 Ubuntu |
| 테스트 fixture DB 7벌 커밋 (**완료 2026-10-04: 샘플 1벌 커밋, 변형은 테스트 때 생성**) | `T/fixtures/issue-db-*` 3.6MB, 각자 `docs/schema/templates` 사본 | 스키마 한 줄 바꾸면 7곳(실제로 Phase 13에서 발생) | `make_variant_dbs.py`가 결정적이므로 **sample 1벌만 커밋 + 변형은 세션 fixture로 생성** (F 후보, §R) |
| 하드코딩 | `S/code_roots.py` 상수, `logcat.py`/`ril.py` regex, `parse_logcat.py` bugreport 헤더, `mcptools.py` `WRITE_WORDS/READ_WORDS` 휴리스틱 | §E | 설정/데이터로 |
| 관측성 | 스크립트는 stderr 경고 + JSON `warnings[]`. 실행 로그 파일 없음 | 자동화에서 추적 불가 | driver가 `<work_dir>/<KEY>/trace.jsonl`(단계·소요·종료 코드) |
| 재시도·멱등 | `db_pr` lease push·승인 해시로 멱등. git fetch 실패는 보고만 | 자동화에서는 재시도 정책 필요 | §N state.json + 입력 해시 |
| 커넥터 장애 격리 | 외부 파서 실패는 warning(R5), MCP 부재는 중단 | 자동화에서 한 이슈 실패가 배치를 멈추면 안 됨 | 이슈 단위 `status: error` 기록 후 계속 |
| 의존성 | `pyyaml`, `jsonschema`, `pytest`만 | 좋음 | 유지. `regex` 모듈 도입은 사내 승인 뒤(가정 18) |
| 자격증명 | 레포에 없음. `work_dir` 700 | 좋음 | `check_boundary.py`에 secret 패턴 추가 — **완료 (2026-10-05, S5)** |

---

## R. File Cleanup Candidates

**삭제하지 않았다.** 각 항목의 의존과 영향을 적는다.

| 분류 | 경로 | 의존·영향 | 조치 |
|---|---|---|---|
| **A 유지** | `plugin/**`, `docs/design/**`, `tests/**`(아래 제외), `tools/{import_draft,make_db_skeleton,offline_eval,list_site_todos}.py`, `SITE_PATHS`, `.gitattributes`, `.gitignore`, `GUIDE.md`, `AGENTS.md` | 핵심 | — |
| **B 유지·정리** | `CLAUDE.md` (15KB → ≤4KB) — **완료(2026-10-05)**: 13,640 → 3,613바이트. §12 → `D/12-principles.md`, 문서 지도 → `D/README.md`, §11.0 → `D/11 §11.0`, §1 → `D/01 §1`, placeholder 문단 → `D/14 §14.1` | 매 세션 로드 | RF-1 |
| B | `DRAFT_NOTES.md` — **완료(2026-10-01)**: 파일 이름은 유지하고 ≤8KB 상태 파일로 축소, 본문은 `docs/history/draft-notes-2026-09.md`. `HANDOFF_STATE.md`는 만들지 않았다(이름 유지가 설계 변경을 줄임) | `D/15`·`CLAUDE.md`·`GUIDE.md`·HANDOFF가 참조 | 진행 상태 절 → `HANDOFF_STATE.md`, 나머지 → `docs/history/draft-notes-2026-09.md`. 참조 4곳 갱신 |
| B | `CHANGES.md` (57KB, 문서 세트 1~11차 변경 이력) — **`docs/history/`로 이동 완료(2026-10-01)** | `CLAUDE.md` 문서 지도, `D/14 §14.5` | `docs/history/`로. "기준 문서 세트 버전"만 `HANDOFF_STATE.md`에 |
| B | `K/reference/db-authoring.md` (27KB) | `C/analyze.md`, `C/record.md`, SKILL Step 7 | op·drift·fixture·R1~R6·상태 표를 걷어내고 ≤ 10KB |
| B | `C/sync-pr.md` ↔ `K/reference/sync-pr.md` | 둘 다 절차 전체 | reference를 단일 원본으로, 커맨드는 5줄 (HANDOFF R12) |
| B | `plugin/.claude-plugin/plugin.json` description "(개발 중, 사외 초안)" | 배포 시 노출 | 사내 S-7에서 |
| **C 생성·캐시·임시** | `.pytest_cache/`, `**/__pycache__/`, `tests/mocks/gh-state/*.json`, `tests/mocks/remote/`, `tests/skill_evals/workspace/`, `tests/mocks/plugin-probe/probe-hook.log` | 모두 `.gitignore` | 유지(비추적) |
| **D 현재 기능에 불필요** | `REVIEW-10.md`, `REVIEW-11.md` (41KB, 과거 검토 Q1~Q10·U1~U17) — **`docs/history/`로 이동 완료(2026-10-01)** | `REVIEW-OPEN.md` 이력 절과 `CHANGES.md`가 참조 | `docs/history/`로 이동(링크 갱신). HANDOFF도 archive 제안 |
| D | `README.md` (0바이트) | 없음 | `docs/ARCHITECTURE.md` 요약 + 링크로 채움(삭제 아님) |
| **E 삭제 후보** | `docs/development/PLUGIN_IMPROVEMENT_HANDOFF.md` | 자기 자신이 "개선 완료 후 삭제 검토"로 표시. `DRAFT_NOTES.md` 19행이 링크 | I0~I6 완료 후. 그 전에는 유지. 이 문서(§U)가 그 계획을 흡수하면 R 표만 남기고 축소 |
| E (**완료 2026-10-04: 샘플 1벌 커밋, 변형은 테스트 때 생성**) | `tests/fixtures/issue-db-{dup-id,empty-category,lint-errors,pending,review,verify}/` (6벌, ~3.1MB) | `T/helpers/make_variant_dbs.py --check`가 재생성·검증. `tests/test_db_lint.py` 등이 경로를 직접 참조 | 커밋 제거 + conftest에서 생성으로 전환. 테스트 경로 상수 수정 필요. **스키마 변경 시 7곳 수정 문제 해소**. 단 diff로 변형 내용을 리뷰하던 가치는 줄어든다 — 사용자 판단 |
| E | `tools/fix_exec_bits.py` | Windows 개발 PC에서만 의미. `DRAFT_NOTES` "개발 환경과 설계의 차이" | Ubuntu 전용으로 가면 삭제 가능. 사외 개발 PC가 Windows인 동안 유지 |
| E | `plugin/scripts/migrations/0001_example_jira_tags.py` | `test_db_migrate.py`가 사용 | 테스트 fixture로 이동(`tests/mocks/migrations/`) 가능. 운영 플러그인에 "example" 마이그레이션이 배포되는 것은 혼란 |
| **F 추가 확인 필요** | `tests/mocks/plugin-probe/` | S1 실험용. 실험 결과 미기록(⏳ 8항목) | 실험 완료·결과 기록 후 유지/삭제 결정 |
| F | `K/reference/{fail-causes,log-tags,ril-requests}.md` | 로그 해석 보조. HANDOFF R11(단정 문구) | 데이터(이슈 DB docs)로 옮길지 결정 후 |
| F | `tests/fixtures/offline-eval-sample.yaml`, `tests/fixtures/verify-logs/` | `tools/offline_eval.py`, `test_db_verify.py` | 유지 추정. `logs/`와 통합 가능 |

---

## S. Future Use Cases (현재 component 재사용 가치 순)

| # | Use case | 기존 재사용 component | 새 component | 경계 | 난이도 | Token 비용 | 자동화 수준 | 승인 |
|---|---|---|---|---|---|---|---|---|
| 1 | **배치 사전 triage** (Jira 변경분 → 로그 → 후보·근거 리포트) | `offline_eval.evaluate_item` 경로 전부, `jira_fields`, `match_signatures`, `db_search` | `triage.py`, `triage_batch.py`, JiraReader/LogSource 인터페이스, state.json | 엔진·상태·템플릿 사외 / Jira·FTP 구현 사내 | 중 | **0** (high 단일 후보) ~ 4K/건 (LLM 호출 시) | 분석·초안까지 자동 | 코멘트 post는 승인 |
| 2 | **수정 빌드 회귀 감시** (nightly 로그로 `fix-submitted`/`fixed` 원인 재발 검사) | `db_verify fix`, scenario/recovery 시그니처, `build_compare`, `verification_history` | nightly 로그 수집(LogSource) + 결과 집계 | 사외 | 낮음 | 0 (결정적) | 전자동(판정) | `verify-fix` PR은 사람 |
| 3 | **Android 버전 마이그레이션 보조** (새 트리에서 `code_refs` 이동·소실 검출 → `add-code-ref` 계획 초안) | `code_roots resolve/find-symbol`, `add-code-ref` op, `android_versions` | `tools/migrate_code_refs.py` (전 원인 순회), 심볼 색인 | 사외(도구) / 사내(트리) | 낮음 | 0 | 전자동 초안 | PR 승인 |
| 4 | **source ↔ log correlation** (시그니처의 로그 문구 → 출력 코드 위치 자동 제안) | `find-symbol`, extractor 패턴, `code_refs` | 문구 역검색 색인(`grep -rn` 결과 캐시) | 사외 도구 / 사내 트리 | 중 | 0~2K | 반자동 | 사람 확인 |
| 5 | **반복 실패 패턴 감지 / 급증 알림** | `db_build stats`(급증 비율), `db_review`(월간 리뷰 항목), `occurred_on` | 스케줄 실행 + 알림 템플릿 | 사외 | 낮음 | 0 | 전자동 | 없음(읽기) |
| 6 | **테스트 케이스 생성** (원인별 재현 시나리오 → 합성 로그 → 회귀 fixture 제안) | `logcat_gen.py` 시나리오 형식, `cut`, R1~R6 | 시나리오 초안 LLM 템플릿 | 사외 | 중 | 2~5K/건 | 반자동 | fixture PR 승인 |
| 7 | 커밋/패치 영향 분석 (변경 파일 → 영향받는 원인 `code_refs` 역색인) | `code_refs` | `tools/impact.py` (git diff 파일 ↔ code_refs 교차) | 사외 | 낮음 | 0 | 전자동 | 없음 |
| 8 | Draft Jira 코멘트 | #1 결과 + 템플릿 | writer 인터페이스 | 템플릿 사외 / writer 사내 | 낮음 | 0~2K | 초안 자동 | **필수** |
| — | 코드 리뷰, 빌드 실패 분석, crash/stack trace 분석 | 거의 없음(스택 트레이스 파서·빌드 로그 백엔드 없음) | 새 백엔드·새 도메인 모델 | — | 높음 | — | — | 후순위. 재사용 가치 낮음 |

---

## T. Target Architecture

```
telephony-triage/  (EXTERNAL-SAFE 레포 = canonical)
├── HANDOFF_STATE.md                 ≤3KB: 모드·완료 Phase·다음 3개·막힌 것·마지막 테스트       [B 정리]
├── CLAUDE.md                        ≤4KB: "HANDOFF_STATE.md → 해당 pack을 읽어라" + 금지 규칙 5개 [B 정리] [완료 2026-10-05: 상태 파일은 `DRAFT_NOTES.md`, 원칙은 `D/12-principles.md`]
├── AGENTS.md · GUIDE.md · SITE_PATHS · README.md(요약+링크)
├── docs/
│   ├── ARCHITECTURE.md              1페이지: 흐름표·계약 목록·디렉토리·경계                      [신규]
│   ├── design/                      그대로 (contracts.md가 산문 계약의 단일 원본)
│   ├── tasks/<task>.yaml            context pack 정의 (site-backend-port, parser-rules-tune, s1-values, …)  [신규]
│   ├── development/                 ARCHITECTURE_REVIEW_2026-10.md(이 문서), HANDOFF(완료 후 삭제)
│   └── history/                     draft-notes-2026-09.md, CHANGES.md, REVIEW-10/11.md            [이동]
├── plugin/
│   ├── commands/*.md                12개, 각 ≤ 1.5KB (보일러플레이트 제거)
│   ├── skills/telephony-triage/SKILL.md     ≤ 8KB: 결정 규칙 + driver 호출 + 확인 지점
│   ├── skills/telephony-triage/reference/   write-flow, record, verify, sync-pr(단일 원본), db-authoring(≤10KB), 해석 3개
│   ├── schemas/                     plan.schema.json 등 이슈 DB 스키마 사본 (사외 테스트용)         [신규]
│   ├── hooks/hooks.json
│   ├── site-defaults.example.yaml   (+ platform: android, automation.mode: analysis-only)
│   └── scripts/
│       ├── triage.py                ★ driver: run / batch / report (Step 0~4 + 5 resolve, analysis.json)   [신규]
│       ├── common/                  + events.py(NormalizedLogEvent), issue.py(NormalizedIssue), checks.py(검사 오케스트레이션 1곳)
│       ├── platforms/               android/{logcat,ril,bugreport,backend,PROFILE}, generic/              [이동+신규]
│       ├── parser_backends/         base.py, __init__.py(shim), site/ (SITE_PATHS)
│       ├── adapters/                base.py, __init__.py, site_*.py (SITE_PATHS)
│       ├── connectors/              jira.py(JiraReader/Writer 인터페이스 + MCP-file 구현), logsource.py(LocalDir)   [RF-6]
│       ├── config.py · code_roots.py(+--index) · jira_fields.py · parse_logcat.py · mask_pii.py · match_signatures.py
│       ├── db_add.py(→ ops/ 분할) · db_pr.py · db_verify.py · db_lint.py · db_build.py · db_regress.py · db_review.py · db_search.py · db_migrate.py · db_precommit.py · guard.py
│       └── migrations/
├── tests/
│   ├── conftest.py                  session 플러그인 루트 1회, 변형 DB 생성 fixture                    [신규]
│   ├── fixtures/issue-db-sample/    (변형 6벌은 생성으로 — 사용자 판단)
│   ├── mocks/                       + ofono_gen.py(RF-5), ftp_stub.py(RF-6), 합성 RIL-like 소스 확장
│   ├── skill_evals/                 그대로
│   └── test_*.py (+ test_boundary.py, test_triage.py, test_platforms.py)
├── tools/
│   ├── import_draft.py              (사외→사내) 그대로
│   ├── check_boundary.py            ★ 비-SITE_PATHS 파일의 사내 문자열·secret·사내 import 검사            [신규]
│   ├── context_pack.py              docs/tasks/<task>.yaml → 파일 묶음                                   [신규]
│   ├── offline_eval.py · make_db_skeleton.py · list_site_todos.py · fix_exec_bits.py
│   └── triage_batch.py              스케줄러가 부르는 배치 (RF-8)
└── .github/workflows/external.yml   pytest + check_boundary + fixture --check                           [신규]

================================ SECURITY BOUNDARY ================================
사내 레포 = 위 트리 전체(import_draft로 반입) + overlay:
    plugin/site-defaults.yaml · plugin/scripts/parser_backends/site/ · plugin/scripts/adapters/site_*.py
    plugin/scripts/connectors/site_jira.py · site_ftp.py (RF-6 이후)
    tests/golden/ · tests/site/ · docs/site/ · SITE_PROFILE.md · .draft-manifest.json
    (+ 사내 소스 트리 색인 symbols.json, 운영 이슈 DB 레포)
```

**의존 방향** (허용되는 import만):
`commands/skills` → `triage.py`·`db_*` → `common/*`, `platforms/*`, `parser_backends/base`, `adapters/base`, `connectors/*` → 표준 라이브러리·pyyaml·jsonschema.
사내 overlay(`site/`, `site_*`) → 사외 모듈을 import **가능**. 사외 모듈 → `site*`를 import **금지**(이름 문자열로 `importlib`만, 이미 그렇게 되어 있음). `check_boundary.py`가 이 방향을 정적으로 검사한다.

**LLM 처리 흐름 평가**: "Raw Internal Data → Internal Deterministic Parser → Relevant Information Extraction → Normalized Representation → Minimal Context → LLM Reasoning"은 이 레포에 **거의 그대로 존재**한다 (site 백엔드 → `postprocess` → `match_signatures`(근거 추출) → 이벤트/후보 JSON → (빠진 고리: Minimal Context 조립을 LLM이 함) → LLM). 빠진 고리 하나를 `triage.py`가 채운다. 구조를 바꿀 필요는 없다.

---

## U. Step-by-Step Refactoring Plan

순서 원칙: (1) 안전·기준선 → (2) token(측정 가능, 즉시 효과) → (3) 경계(도구화) → (4) 플랫폼 seam(이동만) → (5) 버전 어댑터(데이터화) → (6) 다중 플랫폼(두 번째 구현) → (7) 커넥터 → (8) 워크플로/자동화 → (9) 정리. HANDOFF의 I0~I2는 RF-0에, I3는 RF-1에, I4~I6는 RF-7~9에 흡수한다. 각 Phase는 독립 PR 1~3개 크기다.

### RF-0 — Baseline & Write-safety (HANDOFF I0 + I1 + I2 핵심)

- **Goal**: 이후 모든 리팩터링이 깨뜨리지 않을 기준선과, 자동화 전 필수 안전 결함 수정.
- **Current Problem**: 전체 suite가 13분(이 컨테이너 Ubuntu 779s, 사외 Windows 999s)이라 반복이 느리다. R2 lock 비원자, R3 경로 밖 삭제, R6 `commit -m` 인용, R1 교차 슬롯 S/C 결합, R4 회전 파일, R5 외부 파서 실패 전파.
- **Root Cause**: 테스트마다 `make_plugin_root.make()`로 `plugin/` 복사 + git 레포 생성 + 서브프로세스. 결함은 HANDOFF에 근거 있음.
- **Target State**: `pytest -x` 3분 이내(목표), 결함 6개에 회귀 테스트, token 측정 스크립트.
- **Files to Modify**: `tests/conftest.py`(신규, session 플러그인 루트), `tests/helpers/runner.py`(in-process 호출 옵션), `S/db_pr.py::Lock`, `_job_of`, `_remove_worktree`, `S/db_verify.py::_check_lock/make_draft/remove_draft`, `K/reference/write-flow.md`·`C/sync-pr.md`(`git commit -F <file>`), `S/match_signatures.py::match`, `S/common/signatures.py::Evaluator`, `S/parser_backends/reference/__init__.py::parse`, `S/parse_logcat.py::_ril_events/_run_external`, `S/db_regress.py::match_errors`.
- **Files to Add**: `tests/test_safety.py`(R2/R3/R6 재현), `tools/measure_tokens.py`(eval 1건의 `claude -p --output-format json` usage 집계 — 429 해제 후).
- **Files to Remove**: 없음.
- **Dependencies**: 없음.
- **Token Impact**: 직접 없음. 측정 기준선 확보.
- **Security Impact**: R3(경로)·R6(shell) — 자동화 전 필수.
- **Risk**: 매처 R1 수정은 회귀 모드 의미(독립 C)를 바꾸면 안 됨 — `db_regress` 전체 통과로 확인.
- **Test**: `pytest tests`, `db_regress --all`(샘플), 새 재현 테스트가 수정 전 fail/후 pass.
- **Completion Criteria**: 전체 suite 통과 + 6개 재현 테스트 통과 + 실행 시간 기록.

### RF-1 — Token / Context Optimization

- **Goal**: analyze 건당 token −50% 이상(목표), 개발 세션 고정 컨텍스트 −80%.
- **Current Problem**: §C High 항목 4개.
- **Root Cause**: 설계가 "스킬이 스크립트를 순서대로 부른다"(`D/07`)로 쓰였고 driver가 없었다. 진행 기록이 한 파일에 누적됐다.
- **Target State**:
  - `S/triage.py run <KEY> --logs … [--jira-raw JOB/jira_raw.json | --jira-file …] [--code <roots>|skip] [--dry-run]` → Step 0~4 + Step 5 resolve를 수행, `JOB/analysis.json`(≤4KB) + `JOB/report.md`(템플릿) + `JOB/trace.jsonl`. 종료 코드 계약 유지. 사용자 입력이 필요한 지점(코드 경로 선택, 시각 후보 선택, lock 보유자 확인)은 `needs_input: {kind, options}`로 멈추고 LLM이 사용자에게 물은 뒤 `--answer kind=value`로 재실행(멱등: 입력 해시 캐시).
  - `K/SKILL.md` ≤ 8KB: 실행 규칙(10줄) + `triage.py run` 호출 + `needs_input` 처리 + Step 6 리포트 완성 규칙 + Step 7 결정표 + Step 8은 write-flow.
  - `CLAUDE.md` ≤ 4KB(**완료 2026-10-05**), `HANDOFF_STATE.md` 신설, `DRAFT_NOTES.md`·`CHANGES.md`·`REVIEW-10/11.md` → `docs/history/`.
  - `C/*.md` 보일러플레이트 제거(각 ≤ 1.5KB). `K/reference/sync-pr.md` 단일 원본. `db-authoring.md` ≤ 10KB.
  - `parse_logcat` 파생 이벤트 `msg` 복사 제거 + ~~`line_ref`(R7)~~(`line_ref`는 2026-10-05 완료, `msg` 복사 제거는 열림). `config.py show --keys`.
- **Files to Modify**: `K/SKILL.md`, `C/*.md`(12), `K/reference/{db-authoring,sync-pr,record}.md`, `CLAUDE.md`, `D/07-workflow.md`(driver 반영), `D/contracts.md §3.2`(triage.py 행 추가), `S/parse_logcat.py::_derived`, `S/config.py::cmd_show`, `D/15 §15.5` S-1 "읽을 것".
- **Files to Add**: `S/triage.py`, `S/common/events.py`, `docs/ARCHITECTURE.md`, `HANDOFF_STATE.md`, `docs/tasks/*.yaml`, `tools/context_pack.py`, `tests/test_triage.py`(offline_eval 라벨셋으로 analysis.json 결정성 검증).
- **Files to Remove**: 없음(이동만: `docs/history/`).
- **Dependencies**: RF-0 (R7 provenance는 driver evidence 형식의 전제 — R7 완료 2026-10-05).
- **Token Impact**: analyze 건당 Bash 왕복 15~20 → 3~5; SKILL 8K → 2.5K; 사내 개발 세션 고정 50K → 3K(추정, RF-0의 측정 도구로 확인).
- **Security Impact**: 없음. driver는 기존 스크립트를 in-process로 묶을 뿐.
- **Risk**: 스킬 eval 45개의 기대가 "스크립트 호출 순서"를 보는 항목이 있으면 조정 필요(`T/skill_evals/grade.py`는 결과물 중심이라 영향 적음).
- **Test**: `tools/offline_eval.py`가 `triage.py run`을 쓰도록 바꾸고 결과 동일; eval batch 1 재실행(한도 해제 후) usage 비교.
- **Completion Criteria**: analysis.json 결정성 테스트 통과, eval 1건 측정값 기록, `CLAUDE.md` ≤ 4KB(**완료 2026-10-05**), 루트에 이력 파일 없음.

### RF-2 — External / Internal Boundary

> **구현 (2026-10-03)**: `tools/check_boundary.py`(규칙 a~d, 예외 `tools/boundary-allow.txt`), `import_draft.py` staging → `--check-boundary` → 활성 전환 → rollback(충돌 검사·SITE_PATHS 보호는 RF-0 R7), `plugin/schemas/` + `tools/sync_schemas.py`, `.github/workflows/external.yml`, `tests/test_boundary.py`. pre-commit 연결은 하지 않았다(선택 항목). 사외 CI 첫 실행 결과는 push 뒤 확인.

> **2026-10-01 외부 리뷰 반영**: `export_external.py`는 **만들지 않는다**(사내→사외는 사용자 타이핑만). 대신 반입 도구를 강화한다 — 첫 반입 충돌 검사(기존 트리 위 반입 거부 또는 충돌 목록), 기준선에 없는 사내 새 파일과 사외 새 파일의 이름 충돌 검사, `SITE_PATHS` 자체 보호, `apply()` staging 디렉토리 → 검증 → 활성 전환 → 실패 시 rollback. `check_boundary.py`·사외 CI·`plugin/schemas/`는 그대로.

- **Goal**: 사내 자료 반출 방지를 **도구와 CI**로 강제. 사내에서 사외로 코드를 보내는 절차를 자동화.
- **Current Problem**: §H.3 — 반출 도구·스캐너·secret 스캔 없음. 사외 CI 없음.
- **Root Cause**: 사외 초안 단계라 "사내→사외" 방향이 아직 필요 없었다.
- **Target State**:
  - `tools/export_external.py <dest>`: `SITE_PATHS`를 **배제**(allowlist = 전체 − SITE_PATHS − `.gitignore` − `.git`), 결과에 `check_boundary.py`를 돌려 실패 시 패키지를 만들지 않음. `.draft-manifest.json` label을 패키지 이름에.
  - `tools/check_boundary.py`: (a) 비-SITE_PATHS 파일에서 사내 표식 패턴 검사 — 패턴 목록은 사내가 `docs/site/boundary-patterns.txt`(SITE_PATHS)에 두고 사외는 기본 목록(`@<실제 org>` 금지, `*.invalid`·`mock-` 외 호스트명, 15자리 숫자, IP, `BEGIN PRIVATE KEY`, `token=`…); (b) `plugin/scripts/**`에서 `site`·`site_*` 모듈을 정적 import하는지; (c) `tests/fixtures/**/*.log`에 `origin: synthetic` 없는 fixture; (d) `plugin/site-defaults.yaml` 존재. 종료 코드 1이면 커밋·반출 차단.
  - 이 레포의 pre-commit(선택)과 `.github/workflows/external.yml`에서 실행.
  - `import_draft.py`에 `--check-boundary` 옵션(반입 직후 사내 레포에서 비-SITE_PATHS 변경을 재검사).
  - `plugin/schemas/`에 이슈 DB 스키마 사본(사외 테스트가 DB 없이 plan 검증) — 단일 원본은 이슈 DB 레포, `tools/sync_schemas.py --check`로 동기화 검사.
- **Files to Modify**: `tools/import_draft.py`, `SITE_PATHS`(`docs/site/boundary-patterns.txt`, `plugin/scripts/connectors/site_*` 추가), `D/15 §15.6`(반출 절차), `GUIDE.md §4`.
- **Files to Add**: ~~`tools/export_external.py`~~(제외, 결정 a), `tools/check_boundary.py`, 반입 staging/rollback(`tools/import_draft.py` 확장), `tests/test_boundary.py`, `.github/workflows/external.yml`, `plugin/schemas/`, `tools/sync_schemas.py`.
- **Files to Remove**: 없음.
- **Dependencies**: RF-1(문서 이동이 끝나야 allowlist가 안정).
- **Token Impact**: 사내 AI가 "사외 요약"을 손으로 만들던 작업 제거.
- **Security Impact**: 핵심. blocklist(패턴)는 보조이고 **allowlist(SITE_PATHS 역방향)** 가 1차 장치.
- **Risk**: 스캐너 오탐(모의 값·15자리 숫자). `allow_patterns`와 같은 예외 파일 필요.
- **Test**: 가짜 사내 레포(`tmp`)에 SITE_PATHS 파일 + 사외 파일에 일부러 넣은 사내 문자열 → export 거부; 깨끗하면 패키지 생성 + 두 번째 `import_draft` 왕복이 동일 해시.
- **Completion Criteria**: "실제 사내 데이터 없이 external 레포에서 build/test/refactor가 된다"는 이미 성립(합성 fixture 226 테스트). 추가로 export→import 왕복 테스트와 CI 통과.

### RF-3 — Core / Platform Separation (이동만)

- **Goal**: §F 디렉토리. 동작·출력 바이트 동일.
- **Files to Modify**: `S/parser_backends/__init__.py`(shim: `reference` → `platforms.android.backend`), `S/parse_logcat.py`(bugreport 부분 import), `S/code_roots.py`(상수 → `platforms.load().source_tree`), `S/config.py`(`platform` 키 노출), `plugin/site-defaults.example.yaml`(`platform: android`), `T/mocks/parser_backends/site/__init__.py`(import 경로 — 사내 site 백엔드도 같은 변경이 필요하므로 **re-export shim을 유지**해 사내 수정 0으로).
- **Files to Add**: `S/platforms/__init__.py`, `S/platforms/android/{__init__,logcat,ril,bugreport,backend}.py`, `tests/test_platforms.py`.
- **Files to Remove**: `S/parser_backends/{logcat,ril}.py`, `reference/`(shim 모듈만 남김).
- **Dependencies**: RF-1(events.py).
- **Token Impact**: 사내 포팅 pack이 `platforms/android/`로 명확해짐.
- **Security Impact**: 없음. `check_boundary`의 import 방향 규칙에 `platforms/*` 포함.
- **Risk**: `T/fixtures/logs/*.events.json` 스냅샷은 바이트 동일해야 함.
- **Test**: 기존 파서·골든 테스트 무수정 통과.
- **Completion Criteria**: `git mv` 중심 diff, 스냅샷 동일.

### RF-4 — Android Version Adapter (데이터화)

- **Goal**: §E의 상수를 설정/데이터로. 새 Android 버전 = 설정 한 줄 + 이슈 DB 규칙 PR.
- **Files to Modify**: `S/platforms/android/__init__.py`(PROFILE 기본값), `S/code_roots.py`(`required_dirs`, `version_sources` 설정 우선), `S/platforms/android/logcat.py`(`phone_id_patterns` 선택 규칙), `ril.py`(`ril.yaml` `tags:` 선택), `S/common/parser_rules.py`(스키마 선택 필드), 이슈 DB `schema/parser-rules.schema.json`(선택 필드 — schema_version 유지), `D/04 §5.8`, `D/14` S7·S11·S20·S21 반영 위치.
- **Files to Add**: `tools/migrate_code_refs.py`(§S #3: 새 트리에서 전 원인 `code_refs` 점검 → `add-code-ref` 계획 초안), `S/code_roots.py --index` + `symbols.json`.
- **Dependencies**: RF-3.
- **Token Impact**: Step 5 심볼 탐색이 색인 조회로.
- **Security Impact**: `symbols.json`은 사내 트리 파생물 → `work_dir` 또는 `docs/site/`(SITE_PATHS).
- **Risk**: 설정 우선순위 혼동 — 코드 기본값 ⊂ site-defaults ⊂ 이슈 DB 규칙 순서를 contracts에 명시.
- **Test**: 모의 트리 16/17에서 `required_dirs`를 바꿔도 validate 통과; `phone_id_patterns` 추가 시 슬롯 추출 변화 테스트.
- **Completion Criteria**: `grep -rn 'frameworks/opt/telephony\|RILJ\|\[PHONE' plugin/scripts` 결과가 `platforms/android/` 기본값 1곳씩.

### RF-5 — Multi-platform Support (두 번째 구현으로 seam 검증)

- **Goal**: `platforms/generic/` 백엔드 + oFono 합성 시나리오로 이슈 DB·매처·검증이 플랫폼 무관임을 **실행으로** 증명.
- **Files to Add**: `S/platforms/generic/{__init__,backend}.py`(`short-iso`/syslog/`ofonod -d` 줄 해석, 선택 `phone_id_regex`, 선택 `pair_strategy: dbus`), `T/mocks/ofono_gen.py`, `T/mocks/scenarios/ofono-*.yaml`(3개), `T/fixtures/issue-db-ofono-sample/`(카테고리 3개, 유형 3개, 생성 스크립트), `tests/test_platform_generic.py`.
- **Files to Modify**: `S/parser_backends/__init__.py`(platform별 기본 백엔드), `S/common/compat.py`(이슈 DB `platform` 대조), `D/16`에 "플랫폼 추가 절차" 1절.
- **Dependencies**: RF-3·4.
- **Token Impact**: 없음.
- **Security Impact**: 없음(전부 합성).
- **Risk**: 스키마 `android_versions` 이름을 바꾸고 싶어질 수 있음 — 바꾸지 않는다.
- **Test**: oFono 샘플 DB로 `db_regress --all`, `db_verify rules`, `offline_eval` 통과.
- **Completion Criteria**: "새 플랫폼 = 백엔드 1파일 + 합성 시나리오 + 이슈 DB"로 끝났음을 PR diff가 보여줌.

### RF-6 — Connector Architecture

- **Goal**: Jira·로그 소스를 인터페이스 뒤로. 구현은 사외 `MCP-file`/`LocalDir`, 사내 `site_jira`/`site_ftp`.
- **Files to Add**: `S/connectors/{__init__,jira,logsource}.py`(`JiraReader.get_issue/search/get_comments → NormalizedIssue`, `JiraWriter.post_comment(mode 검사)`, `LogSource.fetch(LogSourceRef) → paths`), `T/mocks/ftp_stub.py`, `tests/test_connectors.py`.
- **Files to Modify**: `S/jira_fields.py`(NormalizedIssue 생성을 `connectors.jira`로 위임, CLI 유지), `S/triage.py`(`--jira-source mcp-file|file|<site>`), `S/guard.py`(변경 없음 — Claude 세션 전용), `site-defaults.example.yaml`(`connectors:` 블록), `SITE_PATHS`.
- **Dependencies**: RF-1·2.
- **Token Impact**: 없음.
- **Security Impact**: writer는 `automation.mode`와 `jira.write_tools` allowlist(신규, 기본 비어 있음)를 코드로 검사. 사내 구현만 SITE_PATHS.
- **Risk**: MCP는 Claude 세션 밖에서 호출 불가 → 자동화용 사내 JiraReader는 REST일 가능성. 인터페이스는 둘 다 수용.
- **Test**: 모의 Jira MCP(`call.py`)와 파일 소스로 `triage.py run` end-to-end.
- **Completion Criteria**: `jira_fields`·`triage` 테스트가 connector 경유로 동일 결과.

### RF-7 — Workflow Engine (분석 전용 흐름 + 재사용 상태)

- **Goal**: "Jira 기록 없이 분석만", "추가 로그로 재분석", 입력 해시 캐시 (HANDOFF I4의 합의 부분).
- **Files to Modify**: `S/triage.py`(`analyze-only`, `--more-logs`, `analysis.json.request_hash`), `C/analyze.md`(옵션), `K/SKILL.md`.
- **Files to Add**: `tests/test_triage_reuse.py`.
- **Dependencies**: RF-1·6.
- **Token Impact**: 같은 이슈 재분석 시 driver 재계산 0.
- **Completion Criteria**: 입력 변경 시에만 재계산되는 테스트.

### RF-8 — Automation (Scheduler + Jira monitoring + draft comment + approval)

- **Goal**: §N 흐름을 `analysis-only` 모드로 가동, 이후 `draft` → `approve` 승격.
- **Files to Add**: `tools/triage_batch.py --since --assignee --mode`, `S/connectors/state.py`, `S/triage.py report --template comment`, `plugin/templates/comment.md`, `tests/test_batch.py`(모의 Jira 검색·LocalDir).
- **Files to Modify**: `site-defaults.example.yaml`(`automation:`), `D/`에 `17-automation.md`(신규 설계 절), `GUIDE.md`.
- **Dependencies**: RF-0(R2/R3/R5), 6, 7.
- **Token Impact**: 건당 0~4K(§N).
- **Security Impact**: post는 모드·allowlist·사람 승인 3중. 사내 cron 설정은 `docs/site/`.
- **Risk**: 배치가 `work_dir` lock과 충돌 → 배치는 자기 `work_dir/batch/` 네임스페이스와 별도 lock.
- **Completion Criteria**: 모의 환경에서 10건 배치 → 10개 analysis.json + 상태 파일, LLM 호출 0으로 완료.

### RF-9 — Cleanup / Documentation

- **Goal**: §R의 E 후보 처리(사용자 승인), HANDOFF 삭제 검토, `docs/ARCHITECTURE.md` 최종화, `README.md` 채움, `plugin.json` 설명.
- **Dependencies**: 전부.
- **Completion Criteria**: 새 agent가 `HANDOFF_STATE.md` + `docs/ARCHITECTURE.md` + pack 1개만으로 Phase 작업을 시작하는 리허설(실제로 새 세션에서 수행하고 token을 기록).

---

## V. Recommended First Implementation (지금 시작할 3~5개)

| 순위 | 변경 | 왜 먼저 | 예상 token 절감 | architecture 영향 | 사외 개발 | 사내 작업량 | risk | 수정 범위 |
|---|---|---|---|---|---|---|---|---|
| 1 | **`S/triage.py run` driver + SKILL.md 축소** (RF-1 핵심) | 가장 큰 token 소비처(건당 수만)가 LLM 오케스트레이션. 기존 스크립트를 in-process로 묶기만 하므로 로직 변경이 없다 | analyze 건당 **−40~60%** (추정; 측정으로 확정) | "Minimal Context" 고리 추가. 나머지 계층 불변 | 전부 사외 | 0 (반입 후 `pytest`) | 중: SKILL 재작성 → eval 재실행 필요 | `triage.py` ~400줄, `SKILL.md`, `offline_eval.py`, `D/07` |
| 2 | **고정 컨텍스트 다이어트** (`CLAUDE.md` ≤4KB, `HANDOFF_STATE.md`, 이력 → `docs/history/`, 커맨드 보일러플레이트, sync-pr 단일 원본) | 사내 개발 세션마다 5만 token을 쓰는 구조. 코드 변경 0 | 사내 세션 고정분 **−80~90%** | 없음 | 사외 | 0 | 낮음(링크 깨짐만) | 문서 10여 개 |
| 3 | **반입 도구 강화(충돌·staging·rollback) + `tools/check_boundary.py` + 사외 CI** (RF-2, `export_external.py`는 제외) | 지금은 사람의 주의가 경계. 자동화·반복 반입 전에 도구화해야 한다 | 사내 AI의 "사외 요약" 작업 제거 | SECURITY BOUNDARY를 코드로 | 사외(패턴 목록만 사내) | 패턴 파일 1개 | 낮음(오탐 조정) | 스크립트 2개 + 테스트 + workflow |
| 4 | **HANDOFF R2·R3·R6 안전 수정** (RF-0 일부) | 작고 명확하며, 자동화(RF-8)와 사람이 없는 배치 실행의 전제 | 없음 | 없음 | 사외 | 0 | 낮음 | `db_pr.py::Lock/_job_of/_remove_worktree`, `write-flow.md`, 테스트 |
| 5 | **`platforms/android/` 이동 + `platform:` 키** (RF-3) | 이름이 생기면 사내 포팅 pack이 명확해지고 oFono 자리가 보인다. `git mv` 중심이라 위험이 낮다 | 사내 포팅 세션 탐색 토큰 감소 | Core/Platform 경계 가시화 | 사외 | 0 (shim 유지) | 낮음 | 5파일 이동 + shim |

큰 rewrite 없음. 1·2·4는 한 주 안에 사외에서 끝낼 수 있는 크기다.

---

## W. 핵심 질문 20개에 대한 답

1. **token이 가장 많이 낭비되는 곳**: (a) analyze에서 LLM이 15~20회 CLI를 직접 호출하며 JSON을 읽는 오케스트레이션(건당 6.4만~14.4만 실측의 대부분), (b) 사내 개발 세션의 `CLAUDE.md` 15KB + `DRAFT_NOTES.md` 136KB, (c) `events.json`(원 로그 ~25배)을 LLM이 열어볼 가능성.
2. **SIM/Data를 core context에서 얼마나 제거**: 이미 0에 가깝다 — 카테고리 지식은 이슈 DB 데이터이고 LLM은 매칭 결과만 본다. 제거보다 "LLM이 읽지 않는 파일" 규칙을 driver 출력으로 강제하는 것이 조치다. `fail-causes.md`류 10KB는 선택 로드이며 장기적으로 데이터로.
3. **가장 효과 큰 절감**: `triage.py` driver(건당) + 컨텍스트 다이어트(세션당).
4. **Android 버전 업 유지 가능?**: 그렇다. 버전별 문구·경로는 이슈 DB 데이터(`parser-rules`, `code_refs.android_versions`)이고, 코드 상수는 `code_roots.py` 2개와 파서 regex 몇 개뿐(§E).
5. **version-specific 코드를 adapter로?**: 코드가 아니라 **데이터**(이슈 DB 규칙 + 설정 `version_sources`/`phone_id_patterns`)가 어댑터다. RF-4에서 남은 상수를 데이터화.
6. **oFono/Linux/Yocto 확장 가능?**: 가능. 백엔드 1개(`platforms/generic`) + 합성 시나리오 + 플랫폼용 이슈 DB로 끝난다(§G). 매처·검증·PR 흐름은 이벤트 기반이라 변경 없음.
7. **external-safe core 비율**: 현재 레포는 **100% external-safe**(사내 파일 0). 사내 overlay는 `site-defaults.yaml`, `parser_backends/site/`, `adapters/site_*`, 골든, `tests/site`, `SITE_PROFILE.md` — 코드 기준 수백 줄.
8. **반드시 사내 유지 코드**: 검증된 사내 파서 포팅(`site` 백엔드 `detect()`), 기존 파서 어댑터 `convert()`, (RF-6 이후) 사내 Jira/FTP 커넥터 구현, 경계 패턴 목록. 값: `site-defaults.yaml`, 이슈 DB 레포.
9. **RIL/IMS/vendor/Jira/log parser 격리 가능?**: 이미 격리됨. 사외 코드는 `builtin.*`/`ext.*` 이벤트 **이름**만 안다. Jira는 `field_map` + (RF-6) `JiraReader`.
10. **사내 Claude가 전체 레포를 읽지 않고 개발?**: 가능. §I의 pack(포팅 pack ≈ 600줄) + `HANDOFF_STATE.md`. 지금은 "읽을 것" 목록이 문서에 흩어져 있어 agent가 탐색한다 → `docs/tasks/*.yaml`로 고정.
11. **사내 token을 가장 크게 줄이는 architecture 변경**: 결정적 driver(`triage.py`)로 LLM의 역할을 "결과 해석·결정·초안"으로 축소하는 것.
12. **외부 Codex에서 어디까지?**: 지금도 전부(226 테스트, 모의 Jira/GHE/로그/소스). 남는 사내 작업은 값 입력·포팅·실 로그 보정·실전 검증.
13. **External Core ↔ Internal Extension interface**: §J — `ParserBackend`, `Adapter.convert`, `NormalizedLogEvent`, `NormalizedIssue`, `AnalysisResult`(신규), `plan.json`, `site-defaults.yaml` 키. 산문은 `contracts.md`, 코드는 `TypedDict`/JSON Schema.
14. **실 데이터 없는 external CI**: `.github/workflows/external.yml` — `pytest`, `check_boundary`, fixture `--check`. 합성 생성기가 모두 결정적이므로 가능(§L).
15. **Monorepo vs 분리**: A′(사외 canonical + 사내 overlay) 유지, 반출 도구·스캐너 추가(§M). 플러그인이 한 트리로 설치되어야 하므로 분리 레포는 compose 비용만 더한다.
16. **사내 자료 유출 기술적 차단**: allowlist 역방향 export(`SITE_PATHS` 배제) → 스캐너(사내 패턴·secret·import 방향·`origin: synthetic`) → CI/pre-commit → 패키지. 사람의 주의는 마지막 줄이 아니라 첫 줄이 된다(§H.3, RF-2).
17. **Jira→FTP→Log→Source→Analysis→Jira 가능?**: 가능. `offline_eval.py`가 이미 LLM 없는 파이프라인. 부족한 것은 커넥터 인터페이스·상태 저장·writer·승인 모드(RF-6~8). 선행: R2/R3/R5.
18. **그 중 external-safe 개발 범위**: 스케줄 루프, 필터, 상태, 파서, 매처, 리포트/코멘트 템플릿, 승인 상태 머신, 모의 커넥터 — 10개 중 8개 전부 + 2개의 인터페이스.
19. **LLM → deterministic 이전 가능 작업**: Step 0~4 전체 오케스트레이션, 시각 후보 제시, 코드 경로 후보, `code_refs` 해석·심볼 재탐색, high-confidence 단일 후보의 리포트·코멘트 초안(템플릿), 입력 해시 캐시 판단(§P).
20. **지금 가장 먼저 고칠 architecture 문제**: "LLM이 오케스트레이터"라는 점. 해결은 `triage.py` 하나.

---

## X. 부록 — 확장 아이디어 백로그

> 2026-10-01에 별도 파일(`EXTENSION_IDEAS.md`)로 썼다가 §S와 겹쳐서 여기로 합쳤다. 목록만이고 우선순위는 미정. 특히 **X.9 파서 변경 검증**은 현재 장치(R1~R6·골든·스냅샷·버전 핀)와 빈틈을 정리한 절이다.

- 작성일: 2026-10-01. 기준 commit: `5d2b34b`. 이 문서 §S(사용 사례 8개)를 전제로 그 바깥까지 넓힌 목록이다.
- 이 문서는 **아이디어 목록**이다. 우선순위·일정은 정하지 않았다. 구현은 RF-0~RF-2(안전·token·경계)가 끝난 뒤 사용자가 고른다.
- 읽는 사람: 이 도구를 어느 정도 알지만 내부까지는 모르는 사람. 그래서 1절에 부품 설명을 둔다.

---

### 1. 이 도구의 다섯 부품 (확장은 전부 이 조합이다)

비유: **"증상 → 병명 사전을 가진 자동 진단기"**.

| 부품 | 쉽게 말하면 | 지금 하는 일 | 코드 |
|---|---|---|---|
| ① 로그 읽기 | 수만 줄 로그를 "언제 무슨 일이 있었나"라는 **사건 목록**으로 바꿈 | logcat → "11:00:02 데이터 연결 거부, 이유 SIM 미준비" | `parse_logcat.py`, `parser_backends/` |
| ② 패턴 대조 | 사건 목록을 **알려진 증상 패턴**과 맞춰 봄 | "이 조합은 원인 DATA-001-02와 92% 일치" | `match_signatures.py` |
| ③ 지식 사전 | 증상·원인·해결책·증거 로그를 모은 **팀 공용 노트**(git 레포) | 카테고리 > 증상 유형 > 원인. 누구나 PR로 추가 | 이슈 DB 레포 |
| ④ 검증기 | 새 패턴이 **엉뚱한 로그에도 걸리지 않는지**, 고쳤다는 버그가 **정말 고쳐졌는지** 확인 | 양성/음성 샘플 로그로 회귀, R1~R6 | `db_verify.py`, `db_regress.py` |
| ⑤ 안전한 기록 | AI가 사전을 고칠 때 **사람 승인 → PR**을 강제 | main 직접 수정 불가, 승인한 내용 그대로만 push | `db_pr.py`, `guard.py`, git hooks |

설계 원칙: **판정은 스크립트(①②④)가 하고 AI는 설명·초안·질문만 한다.** 그래서 결과가 재현되고 token이 적게 든다.
①(읽는 법)과 ③(사전 내용)만 바꾸면 ②④⑤는 다른 분야에 그대로 쓸 수 있다. 아래 아이디어는 전부 이 사실에서 나온다.

---

### 2. 같은 분야(폰 통신)에서 바로 할 수 있는 것

| # | 아이디어 | 쓰는 부품 | 더할 것 | 비고 |
|---|---|---|---|---|
| 2-1 | **빌드 품질 검사(릴리스 게이트)**: 빌드마다 테스트 폰 로그를 모아 ②를 돌려 알려진 원인이 걸리면 빨간불 | ②④ | 로그 수집 + 집계 1장 | LLM 불필요 |
| 2-2 | **재발 감시**: `fixed` 원인의 패턴을 매일 최신 로그에 돌려 재발 시 `verification_history`에 `reverted` | ④ `verify-fix` | 스케줄 + 알림 | §S #2 |
| 2-3 | **대량 스크리닝**: 고객 bugreport 수백 개를 ①②만으로 돌려 "기존 원인 분포 + 미분류 묶음" | `offline_eval` 경로 | 배치 러너 | 비용 ≈ 0 |
| 2-4 | **미분류 → 새 증상 후보 제안**: 분류 안 된 로그를 사건 순서(n-gram)로 묶어 "이 12건은 같은 증상"을 제시, 승인 시 `record --new-type` 초안 | ① 이벤트, `db_add similar` | 결정적 클러스터러 | 사전이 스스로 자람 |
| 2-5 | **사전 건강 상태판**: 원인별 fixture 수, 오탐 신고 수, 마지막 검증 시각을 `STATS.md`에 | `db_build stats`, 피드백 | 생성기 절 1개 | |
| 2-6 | **교육용 재현 로그**: 원인 fixture에서 `logcat_gen` 시나리오를 역생성 | `logcat_gen.py` | 역변환기 | 신입 교육·테스트 입력 |
| 2-7 | **CP(모뎀) 로그 연동**: DM 로그 파서를 어댑터(`ext.*`)로 붙여 AP·CP 타임라인 상관 | 어댑터 계약 | 사내 어댑터 1개 | 지금은 `cp_evidence` 요약만 |
| 2-8 | **듀얼 SIM 전용 유형군**: `phone_id`·`same_phone: false` 기반 교차 슬롯 시그니처 모음 | ①② | 데이터만 | |
| 2-9 | **파서 변경 그림자 비교** (아래 5절) | `db_regress --events-diff` | 입력을 실제 로그 디렉토리로 확장 | 현재 빈틈 |

---

### 3. 분야를 바꾼다 — 가장 큰 확장

①(백엔드 1개)과 ③(이슈 DB 1벌)만 새로 만들면 된다. 나머지는 안 건드린다.

| 새 분야 | 난이도 | 이유 |
|---|---|---|
| **Wi-Fi / 블루투스 / NFC** | 가장 쉬움(설정만) | 같은 Android logcat. `tags.yaml`·카테고리 추가, 카테고리 경계 규칙(`03 §5.1`)만 새로 |
| **ANR / 크래시** | 중간 | tombstone·`am_anr` 파서 백엔드. "스택 프레임 순서"는 시그니처 `sequence`로 이미 표현 가능 |
| **oFono / 차량 IVI / IoT 모뎀** | 중간 | "시각+메시지" 텍스트 공통 백엔드(`platforms/generic`, §G) |
| **빌드 실패 로그** | 중간 | 사건 = 컴파일러 메시지, 원인 = 깨진 의존성 → "빌드 실패 사전" |
| **서버 장애(SRE)** | 중간 | journald/syslog/k8s 이벤트 → 알려진 장애 패턴. 입력은 Jira 대신 알림 |

→ 이 도구는 "통신 이슈 도구"가 아니라 **"로그가 있는 모든 분야용 증상 사전 엔진"** 이다. 첫 실험은 Wi-Fi/BT(코드 변경 0)가 가장 싸다.

---

### 4. 소스 코드와 연결

| # | 아이디어 | 설명 |
|---|---|---|
| 4-1 | **로그 문구 ↔ 코드 위치 역색인** | 시그니처 문구를 소스에서 찾아 `code_refs` 자동 제안. 한 번 색인하면 token 0 (§S #4) |
| 4-2 | **코드 변경 영향 알림** | PR이 건드린 파일 ↔ `code_refs` 교차로 "이 CL은 원인 X와 관련, 과거 재발 2회" 리뷰 코멘트. 읽기 전용 (§S #7) |
| 4-3 | **Android 버전 마이그레이션 보조** | 새 트리에서 `code_refs` 소실·이동 검출 → `add-code-ref` 계획 초안 (§S #3) |
| 4-4 | **수정 → 검증 자동 루프** | CL 머지 → 다음 빌드 로그 → `verify-fix` 자동 판정 → Jira 상태 제안. 사람은 승인만 |

---

### 5. 이슈 관리 업무 자동화

| # | 아이디어 | 설명 |
|---|---|---|
| 5-1 | **Jira 사전 분류 배치** | 새 티켓 → 로그 → 후보 ≤3 + 근거 → 코멘트 초안. `analysis-only → draft → approve → auto` 단계 승격. 확신 높은 단일 후보면 LLM 호출 0 (§N, RF-8) |
| 5-2 | **중복 티켓 탐지** | 같은 원인으로 분류된 열린 Jira 묶음 알림. `jira/` 기록이 원인별로 쌓이므로 쿼리만 |
| 5-3 | **담당자 라우팅** | 1위 카테고리/원인의 CODEOWNERS 팀 제안 |
| 5-4 | **주간/월간 리포트** | `db_review` + 급증 비율 → "이번 주 급증 TOP5, 미검증 해결책 N건" |
| 5-5 | **통신사·모델별 뷰** | `carrier`·`model` 교차 집계 |
| 5-6 | **온보딩 봇** | Jira 키 → 유사 과거 이슈·원인·해결책·관련 코드 한 장 (`db_search`, LLM 불필요) |

---

### 6. 데이터가 쌓이면 가능한 것 (결정적 기준 유지)

| # | 아이디어 | 설명 |
|---|---|---|
| 6-1 | **시그니처 자동 제안** | 양성 n개·음성 fixture로 구분력 있는 이벤트 조합 탐색(결정적 특징 선택). 사람이 승인하면 `add-signature`. R3가 그대로 검증기 |
| 6-2 | **점수 보정** | 피드백 `decision` vs `suggested`로 S/C 가중치 오프라인 튜닝. 매처는 결정적 유지, 파라미터만 갱신 |
| 6-3 | **정확도 벤치마크** | `tests/site/offline-eval.yaml` 라벨셋으로 규칙·프롬프트 변경의 1위 정답률 추적. RF-1 token 측정과 합쳐 두 축 대시보드 |
| 6-4 | **합성 로그 증강** | `logcat_gen` 변주(노이즈·슬롯·시계 이상)로 음성 fixture 대량 생성 → 오탐률 추정 |
| 6-5 | **임베딩 검색(선택, 사내)** | `db_search` 폴백 품질 개선. 분류 확정에는 쓰지 않음 |

---

### 7. 제품 형태 / 배포

| # | 아이디어 | 설명 |
|---|---|---|
| 7-1 | **Claude Code 외 런타임** | 판정부는 LLM 무관 → `triage.py`(RF-1)만 있으면 CLI·웹 API·Jenkins·VS Code 확장에서 같은 엔진. 스킬은 "대화형 UI" |
| 7-2 | **MCP 서버로 노출** | `triage analyze`·`db_search`·`verify-fix`를 MCP 도구로. 다른 에이전트(Codex, 사내 챗봇)가 호출 |
| 7-3 | **GHE App / Actions** | PR 이벤트로 `sync-pr`·`validate` 자동 (`13-actions.md` 연장) |
| 7-4 | **웹 지식 베이스** | README/STATS는 생성 파일 → 정적 사이트(mkdocs)로 검색 가능 위키 |
| 7-5 | **멀티 이슈 DB** | 플랫폼·제품별 DB를 `platform:` 키로 선택 |

---

### 8. 방법론 자체의 재사용 (가장 가치 큰 부분)

도메인과 무관하게 다른 사내 프로젝트에 옮길 수 있는 틀. **별도 템플릿/사내 가이드로 뽑아내는 것** 자체가 하나의 확장이다.

1. **"AI는 결정하지 않는다"** — 스크립트 판정, AI는 설명·초안·질문.
2. **AI가 공유 레포에 안전하게 쓰는 절차** — 계획 파일 → 최신 main 위 재적용 → 승인 해시 → lease push.
3. **사외 초안 → 사내 보완** — `SITE_PATHS` overlay, import/export, placeholder 레지스트리 S1~S21.
4. **AI 세션 안전장치** — `guard.py` + git hook 이중(Jira 읽기 전용, main 보호, clone 불변).
5. **AI 스킬을 테스트 가능한 소프트웨어로** — eval 45개, 트리거 테스트, token 측정.

---

### 9. 파서 변경 검증 — 지금 있는 것과 빈틈

사내에서 새 이슈 유형 때문에 파서가 바뀔 때 "바뀐 파서가 잘 도는가"를 어떻게 확인하는지, 그리고 무엇이 없는지.

> **먼저 오해 하나를 풀어 둔다.** 아래의 "차단"은 **금지가 아니라 통과 조건**이다. 검사를 통과하면 들어간다. 그리고 **새 이슈 유형이 생겨도 파서 코드는 보통 바뀌지 않는다.** 파서는 두 층이다 — 로그 한 줄의 *형식*(시각·태그·메시지·슬롯)을 읽는 **코드**(플러그인 `parser_backends/`)와, 그 메시지에서 *무엇을 뽑아 어떤 이벤트 이름으로 부를지* 정하는 **규칙 데이터**(이슈 DB `parser-rules/tags.yaml`·`extractors.yaml`·`ril.yaml`). 새 유형은 규칙 데이터 + `type.md` 시그니처 + fixture를 **이슈 DB PR 하나**로 넣으면 끝나고(`add-parser-rule`/`update-parser-rule` op), 플러그인 재배포가 없다(`04-parser-matching.md §5.8 (1)`). 파서 **코드**를 고치는 때는 로그 *형식 자체*가 달라질 때뿐이다(새 벤더 포맷, 다른 플랫폼, 슬롯 표기 변경). 사람 승인 없이는 못 들어가는 유일한 경우는 R5(기존에 뽑히던 이벤트가 사라지거나 바뀜)인데, 다른 원인들의 판정이 바뀔 수 있어서다.

#### 9.1 변경의 두 종류

| 종류 | 예 | 빈도 |
|---|---|---|
| **A. 규칙(데이터)** | `parser-rules/` 태그·추출 규칙, `type.md` 시그니처 | 대부분. 이슈 DB PR |
| **B. 파서 코드** | 백엔드 수정, 사내 파서 포팅, 외부 파서 어댑터 | 드묾. 플러그인 레포 |

#### 9.2 "기억" (비교 대상)

| 기억 | 어디 | 용도 |
|---|---|---|
| fixture + `.expect.yaml` | 이슈 DB 각 유형 `fixtures/` (양성·음성) | 모든 규칙·파서 변경을 전체 fixture로 재검사 |
| 골든 출력 | `tests/golden/*.orig.json` (사내, SITE_PATHS) | 사내 파서 포팅 전후 비교 (`tests/test_golden.py`) |
| 이벤트 스냅샷 | `tests/fixtures/logs/*.events.json` | 플러그인 파서 단위 테스트 |
| 버전 핀 | 이슈 DB `parser_backend{name,min_version}`, `external_parsers` | 다른 파서로 돌리면 종료 코드 2 (`common/compat.py`) |

#### 9.3 A(규칙)에서 자동으로 도는 검사 — `db_verify rules` (stage·pre-commit)

| 검사 | 묻는 것 | 통과 못 하면 |
|---|---|---|
| R1 추출 | 자기 양성 로그에서 의도한 이벤트가 나오는가 | 차단 |
| R2 매칭 | 그 이벤트로 자기 원인이 1위인가 | 차단 |
| R3 음성 | 모든 음성 로그에서 안 걸리는가 | 차단 |
| R4 회귀 | 기존 다른 원인 fixture 결과가 그대로인가 | 차단. 다른 유형에 걸리면 좁힐지/`allow-cause`할지 **사용자 결정** |
| R5 이벤트 변화 | 규칙 변경 시 전체 fixture를 옛/새 규칙으로 파싱해 비교. 기존 이벤트가 사라지거나 바뀌면 | **승인 필요(3)** → 메인테이너 승인이 머지 조건 |
| R6 추가 표본 | `--extra`로 준 실제 로그에서도 기대대로인가 | 차단 |

- `parser-rules/`가 바뀌면 검사 범위가 **fixture 전부**로 자동 확장된다. 바뀐 추출 규칙에 의존하는 다른 원인도 의존 그래프로 따라간다.
- 건너뛴 검사(`skipped`, fixture 없음)는 통과로 치지 않고 "리뷰 대상"으로 PR에 표시한다.

#### 9.4 B(코드)에서

- 플러그인 테스트의 이벤트 스냅샷 비교.
- 골든 테스트: 포팅 전 출력 저장 → 변환 규칙 사용자 확인 → 포팅 후 비교 → 의도적 차이는 **사용자 승인 후에만** 골든 갱신, 이유를 `SITE_PROFILE.md`에.
- 백엔드 버전을 올리면 이슈 DB 핀과 어긋나 멈추므로, 핀을 올리는 PR에서 `db_regress --all` 전체 회귀가 강제된다.

#### 9.5 빈틈 (확장 항목)

| # | 빈틈 | 제안 |
|---|---|---|
| 9-1 | **fixture에 없는 것은 못 잡는다.** 커버리지는 운영 규율 | 월간 리뷰의 "fixture 없는 원인" 항목 유지 + 2-5 상태판에 fixture 수 노출 |
| 9-2 | **실제 운영 로그 그림자 비교가 없다.** "최근 실제 로그 N개를 옛/새 파서로 돌려 분류 결과가 몇 % 바뀌었나" | `db_regress --events-diff`의 입력을 fixture에서 **실제 로그 디렉토리**(사내, 마스킹 후)로 넓힌 `shadow-diff` 모드. 2-1·2-3과 같은 수집 경로를 쓴다. 출력: 이벤트 추가/삭제 수, 1위 원인이 바뀐 로그 목록. 기준 초과 시 승인 필요(3) |
| 9-3 | HANDOFF R4(회전 로그 파일의 RIL 짝 맞추기)·R5(외부 파서 실패가 조용히 묻힘) 미수정 | RF-0에서 처리 |

---

### 10. 추천 순서

RF-0~RF-2 뒤, 싼 순으로:
1. **Wi-Fi/BT 카테고리 추가**(3절, 데이터만) — 분야 독립성의 가장 작은 증명.
2. **빌드 품질 검사 + 재발 감시 + 그림자 비교**(2-1, 2-2, 9-2) — 같은 로그 수집 경로를 공유.
3. **Jira 사전 분류 analysis-only**(5-1) — 사람 시간이 가장 많이 줄어드는 곳.
4. **MCP 서버 노출**(7-2) — 다른 팀·에이전트가 쓰기 시작하면 사전이 빨리 자란다.

---

## 최종 한 문장

**"현재 레포는 이미 100% 사외 안전하고 지식이 데이터(이슈 DB)에 있으므로 레포를 나누거나 다시 쓰지 말고, (1) Step 0~4를 묶는 결정적 driver `triage.py`를 넣어 LLM이 `analysis.json` 하나만 읽게 하고, (2) `CLAUDE.md`·`DRAFT_NOTES.md`를 3~4KB 상태 파일과 task별 context pack으로 바꿔 사내 세션 고정 컨텍스트를 없애며, (3) 반입 도구의 충돌 검사·staging·rollback과 `check_boundary.py`를 CI에 걸어 사외→사내 반입을 도구로 강제하고(사내→사외는 사용자 타이핑만), (4) Android 상수 4곳을 `platforms/android/`와 설정으로 옮겨 oFono 등을 같은 `ParserBackend` seam에 붙일 수 있게 하면 — 사내에는 `site` 백엔드·어댑터·커넥터 구현·값 파일만 남고, 나머지 전부는 합성 데이터만으로 외부 Codex에서 지속적으로 개발·테스트·유지보수된다."**
