# 개선 트랙 W — 계획과 실행 틀 (2026-10-06)

- 범위: 토큰 절약, 사용자 편의성, 장기 유지·관리, 기타 보완. 반입 전 사외에서 끝내고, 사내에는 **사내 환경·로그에 맞추는 일만** 남긴다.
- 위치: `DRAFT_NOTES.md` "반입 전 보강 트랙"의 3F 뒤, Z(반입) 앞에 **W**로 넣는다. 각 작업 묶음(WP)이 끝날 때마다 사용자 확인을 받고 표를 갱신한다.
- 원칙은 그대로다: `CLAUDE.md`·`12-principles.md`. 판정은 스크립트 출력, 스킬은 설명·확인만. 설계 문서(`contracts.md`·`07`·`10` 등)와 코드가 함께 바뀐다.
- 근거: 세션 분석(구조 → 3축 검토 → 토큰 검토). 이미 RF 계획에 있던 항목은 "RF-n"으로 표시한다.
- **시작 문구**: 사용자가 "**개선안 진행**"이라고 하면 §7 진행 표의 ☐ 첫 WP를 §8 절차대로 한다. 묻지 않고 시작하되, WP 계획 확인과 완료 확인 두 지점에서는 멈춘다.

## 1. 역할과 모델

| 역할 | 모델 | 하는 일 | 하지 않는 일 |
|---|---|---|---|
| **오케스트레이터** (메인 세션) | Opus 5.5 | WP 순서 결정, 에이전트 호출, 리뷰·테스트 결과 종합, 사용자 확인 요청, 커밋·push, `DRAFT_NOTES.md`·`CHANGES.md` 갱신 | 직접 코드 작성(작은 문서 수정 제외) |
| **계획** | Opus 5.5 (`Plan` 에이전트) | WP 하나의 구현 계획: 바꿀 파일·함수, 문서 동기화 목록, 완료 기준, 관련 테스트 목록, 위험 | 코드 수정 |
| **실행** | Sonnet 5.5 (구조 변경 WP는 Opus 5.5) | 계획대로 구현 + 새 테스트 작성 + 문서 동기화. `tools/related_tests.py`(실행 없이)로 영향 범위 확인 | 계획 밖 변경, 전체 테스트 실행 |
| **리뷰** | Opus 5.5 (실행과 다른 모델) | diff를 적대적으로 검토: 계약 위반, 종료 코드, 마스킹·경계, 문서 불일치, 토큰 증가 여부. 결과는 "차단 / 권고 / 통과" | 수정(발견만 보고, 수정은 실행 에이전트가) |
| **테스트** | Haiku 4.5 | `python3 tools/related_tests.py --run` 실행, 실패를 파일·테스트·원인 한 줄로 보고. 도구가 `full: true`면 보고만 하고 전체 실행은 오케스트레이터가 결정 | 테스트 수정, 원인 추측 서술 |

- 구조 변경 WP(`triage.py`·`db_pr.py` 분할, 계약 생성기)는 실행도 Opus 5.5로 올린다.
- 리뷰가 "차단"이면 실행으로 되돌리고, 같은 WP에서 두 번 차단되면 계획으로 되돌린다.

## 2. WP 한 건의 순서

```
오케스트레이터: WP 선택, 입력 묶음 준비(이 문서의 WP 절 + 근거 문서 절 경로만)
  → [계획] Opus: plan.md 초안 (scratchpad) ─→ 오케스트레이터 검토 → 사용자 확인(계획)
  → [실행] Sonnet/Opus: 브랜치에서 구현·테스트 작성·문서 동기화
  → [리뷰] Opus: diff 검토 → 차단이면 실행으로
  → [테스트] Haiku: related_tests.py --run (+ check_boundary) → 실패면 실행으로
  → 오케스트레이터: 결과 요약(바뀐 파일, 테스트 수, 리뷰 권고 처리) → 사용자 확인(완료)
  → 커밋·push, DRAFT_NOTES 표 갱신, CHANGES.md 한 줄
```

- 테스트는 **바뀐 부분 관련만** 돈다. 전체 `pytest tests`는 도구가 `full`을 요구할 때, W 트랙 끝(Z 직전), 사용자 요청 시만.
- 에이전트 입력은 파일 경로 목록으로 준다. 설계 문서 통째 읽기 금지, 해당 절만. `docs/history/`는 읽지 않는다.
- 스킬·reference를 바꾼 WP는 완료 기준에 "해당 eval 번호 재실행(사외, Sonnet)"을 넣는다. eval 전체 재실행은 W 끝에 한 번.

## 3. 작업 묶음 (순서대로)

표기: 축 = T 토큰 / U 편의 / M 유지 / X 기타. "사내 잔여"는 반입 뒤 사내에서만 할 수 있는 부분.

### W0. 토큰 측정 (T) — 가장 먼저
- 목표: eval 1건의 입력·출력 토큰을 기록해 이후 WP의 효과를 증명한다.
- 변경: `tests/skill_evals/run.py`(stream-json result 이벤트의 usage·modelUsage → `execution.json`), `grade.py`(eval별 토큰 표, 상한 초과를 실패로 세는 `--token-budget`), `README.md` 절 추가.
- 완료: 대표 eval 3개(1·2·45) 실행 결과에 토큰이 기록된다.
- 테스트: `tests/test_skill_evals.py`. 사내 잔여: 없음(사내 S-2 재실행 때 같은 표가 나온다).

### W1. 출력 다이어트 (T)
- 목표: LLM이 읽는 스크립트 출력에서 불필요한 부분을 뺀다.
- 변경: `db_pr stage` 성공 시 checks 요약만(실패 항목만 상세), `db_verify rules` 기본 출력은 항목 상태·실패·리뷰 대상만(`--verbose`로 전체), `db_search --brief`, `config.py show --keys`(HANDOFF 잔여). `contracts.md §3.2` 해당 행 갱신.
- 완료: 샘플 DB로 analyze dry-run 1건의 stage·verify 출력 바이트가 절반 이하.
- 테스트: `test_db_pr`, `test_db_verify`, `test_db_search`, `test_config_setup`. 사내 잔여: 없음.

### W2. 결정적 렌더링 (T·U)
- 목표: 확인 화면과 검색 결과를 스크립트가 마크다운으로 낸다. LLM은 붙여 넣기만 한다.
- 변경: `db_summary.py`에 `render_markdown()`(`write-flow.md §4` 형식 그대로), `db_pr summary --format markdown`, `db_search --format markdown`. `write-flow.md §4`·`search.md §3`은 "출력을 그대로 보인다"로 축소. `07-workflow.md Step 8-5`·`contracts.md` 갱신.
- 완료: eval 1·30·53 통과, 확인 화면 토큰(W0 측정)이 이전보다 감소.
- 테스트: `test_db_pr`(summary 스냅샷), `test_db_search`, `test_commands`. 사내 잔여: 운영 이슈 DB `schema/plan.schema.json`에 `pr.ids` 추가 PR(없으면 publish가 기록하지 않고 재할당 줄은 "확인 불가").

### W3. verify-fix 전제의 스크립트 강제 (U) — `99-deferred.md §F` 방안 1
- 목표: 코드·설정 수정 유형에 scenario·recovery 시그니처가 없으면 `db_verify fix`가 종료 코드 2와 다음 할 일을 낸다. 문구 의존 제거.
- 변경: `db_verify.py::judge_fix`·`_check_fix_target`, `db_search` 원인 출력에 `verify_fix_blocked`, `verify.md` 3번 간소화, `05-verification.md §5.12 (2)`·`contracts.md`·`99-deferred.md §F`(완료 표시). `GUIDE.md`의 "verify-fix는 Opus 권장" 재검토는 eval 25 결과로.
- 완료: eval 25 Sonnet 3/3 통과.
- 테스트: `test_db_verify`, `test_db_search`. 사내 잔여: 없음.

### W4. 질문 수 줄이기 (U·T)
- 목표: analyze 첫 실행의 `needs_input` 횟수를 줄인다.
- 변경: `triage.py` — Jira Android 버전과 일치하는 `code_profiles`가 하나면 `code` 질문 생략(사용자 config `code.auto_select`, 기본 true), cleanup 질문은 analyze에서 빼고 `sync`로(잔여물은 알리기만), 분석 스킬·탐색 분석이 둘 다 해당하면 한 질문으로. `07-workflow.md Step 0·2-1·5-1·5-2`, `SKILL.md`, `02-config.md` 갱신.
- 완료: eval 1·14·40·46에서 질문 횟수가 기존보다 적고 동작 동일. `test_triage` 질문 순서 테스트 갱신.
- 테스트: `test_triage`, `test_triage_analysis_only`, `test_commands`. 사내 잔여: 없음.

### W5. 쓰기 흐름 왕복 축소 (T·U)
- 목표: Step 8의 Bash 왕복을 줄인다.
- 변경: `db_pr stage --then-summary`(성공 시 summary까지 한 호출), `db_pr publish --and-discard`. `write-flow.md` 표, `contracts.md §3.2` `db_pr` 세부.
- 완료: eval 1 기준 Step 8 Bash 호출이 3회 이상 감소.
- 테스트: `test_db_pr`, `test_hooks`(guard가 `publish`를 여전히 `ask`로). 사내 잔여: 없음.

### W6. reference 축소와 실행 규칙 분리 (T·M)
- 목표: `db-authoring.md` 27KB → 10KB 이하(op·drift·fixture·R 표 제거, 스키마·오류 메시지가 대신). `SKILL.md`의 실행 규칙을 `reference/rules.md`로 떼어 record·verify·sync-pr가 그 파일만 읽게(search 제외: 읽기 전용, Read 1회·1.5KB 절약).
- 변경: `plugin/skills/telephony-triage/{SKILL.md, reference/*}`, `commands/*.md`의 "그 절만 읽는다" 문구 정리, `10-skill-eval.md §SKILL 구성`.
- 완료: 파일 크기 기준 충족, eval 2·3·4·31(새 원인·유형 작성) 통과.
- 테스트: `test_commands`, `test_skill_evals`(파일 존재·크기 검사 추가). 사내 잔여: 없음.

### W7. 계약 문서 생성과 drift 테스트 (M·T)
- 목표: `contracts.md §3.2`의 CLI 표를 코드에서 생성하고, reference 안의 스크립트 호출이 실제 argparse와 맞는지 테스트한다.
- 변경: `plugin/schemas/analysis.schema.json`(신규, `triage.py`가 출력 검증), `tools/gen_contracts.py`(각 스크립트 `build_parser()` + 출력 스키마 → `docs/design/contracts-cli.md` 생성, `--check`), `contracts.md §3.2`는 생성 파일을 가리키는 짧은 절로. `tests/test_reference_cli.py`(reference·SKILL·commands에서 `S/<이름>.py …` 토큰 추출 → 파서로 파싱). 사외 CI에 `gen_contracts.py --check` 추가.
- 완료: 생성 결과가 현재 표와 의미상 같음(사용자 검토), drift 테스트 통과.
- 실행 모델: Opus. 테스트: 신규 테스트, `test_triage`, `test_boundary`. 사내 잔여: 없음.

### W8. 반입 묶음 도구 (M)
- 목표: `15-local-draft.md §15.4` 체크 9항목과 `GUIDE.md §3` 묶음 생성을 `tools/make_bundle.py` 하나로.
- 변경: `tools/make_bundle.py`(검사 순서대로 실행 → 실패 시 중단 → `git archive` + 뼈대 zip + sha256 + 결과 JSON), `GUIDE.md §3`, `15-local-draft.md §15.4`("도구로 실행"), `DRAFT_NOTES.md` Z 행.
- 완료: 현재 트리에서 도구가 끝까지 돌고 묶음·해시가 나온다(태그 push는 사용자).
- 테스트: `tests/test_make_bundle.py`(신규, 임시 레포). 사내 잔여: 없음.

### W9. 진단·상태 커맨드 (U)
- 목표: `config.py doctor`(gh 인증·Jira 매핑·hook 경로·스냅샷 나이·호환성·lock 상태를 읽기 전용 표로), `sync` 끝에 내 열린 PR과 base 변경 여부 표시.
- 변경: `config.py`, `db_pr.py`(열린 PR 조회 재사용), `commands/sync.md`, `commands/setup.md`(마지막 단계에 doctor), `02-config.md §4`, `09-commands.md`.
- 완료: eval 39(매핑 없음)와 setup 흐름에서 doctor 출력이 쓰인다.
- 테스트: `test_config_setup`, `test_db_pr`, `test_commands`. 사내 잔여: 사내 gh·MCP 실제 출력 형식 확인(S-2).

### W10. 큰 모듈 분할 (M) — 동작 동일
- 목표: `triage.py`를 `triage/`(driver·anchor·cache·report)로, `db_pr.py`를 lock·worktree·publish로 나눈다. CLI·출력 바이트 동일.
- 변경: 위 파일, `01-architecture.md §3`. 옛 경로 import는 shim.
- 완료: `tests/fixtures/logs/*.events.json`·`test_triage` 스냅샷 무수정 통과, `related_tests.py`가 `full`을 요구하면 전체 1회.
- 실행 모델: Opus. 테스트: `test_triage*`, `test_db_pr`, `test_safety`. 사내 잔여: 없음.

### W11. 기타 보완 묶음 (X)
- `README.md` 채우기(요약 + 링크), `plugin.json` description 정리를 반입 체크리스트에 추가, 파생 이벤트 `msg` 복사 제거(`parse_logcat.py::_derived`, `line_ref` 기준; 이벤트 스냅샷 재생성은 사용자 승인), guard 규칙 10의 명령·파일 목록을 `site-defaults.yaml` 선택 키로(`platform`과 같은 방식, 기본값 동일), Windows 보정 잔존물 삭제 여부 사용자 결정, `tools/usage_stats.py`(work_dir에서 PR 소요 시간·취소 비율·질문 횟수 집계, S-7 지표).
- 각 항목은 작아서 한 WP로 묶되 커밋은 항목별로.
- 테스트: `test_parse_logcat`(스냅샷), `test_hooks`, 신규 `test_usage_stats`. 사내 잔여: guard 예외 값·usage 기준치는 사내.

### W12. 문서 정리 (M·T)
- `ARCHITECTURE_REVIEW_2026-10.md`·`PLUGIN_IMPROVEMENT_HANDOFF.md`를 "남은 항목 3KB 절 + 본문은 `docs/history/`"로, `tools/context_pack.py` + `docs/tasks/*.yaml`(사내 S-1~S-5 단계별·사외 WP별 읽을 파일), `11-phases.md §11.0`과 `15-local-draft.md §15.5`의 "읽을 것"을 pack 이름으로 통일, `pytest` 기본 `--tb=short`(`pyproject.toml`).
- 완료: 새 세션이 pack 하나로 W 또는 S 단계를 시작하는 리허설 1회(토큰 기록).
- 테스트: `test_boundary`(문서 이동 뒤 참조), 신규 `test_context_pack`. 사내 잔여: 사내 pack(`docs/site/tasks/`)은 S-1에서.

### W 끝
- 전체 `pytest tests`, `db_regress --all`, eval 54개 Sonnet 재실행(W0 토큰 표 포함), `check_boundary`, `sync_schemas --check` → Z(반입)로. `make_bundle.py`(W8)가 이 절차의 실행기다.

## 4. 사내에 남기는 것 (반입 뒤, S 단계)

| 단계 | 남는 일 | 사외에서 미리 해 둔 것 |
|---|---|---|
| S-1 | 사내 값 조사, `SITE_PROFILE.md` | context pack(W12), `list_site_todos.py` |
| S-2 | Claude Code 기능 확인, eval 54 재실행 | 토큰 표(W0), doctor 출력 형식(W9) |
| S-3 | `site-defaults.yaml`·이슈 DB config, 이슈 DB `schema/plan.schema.json`에 `pr.ids` 추가 PR(W2) | guard 규칙 10 예외 키(W11), `platform` 키(RF-4 완료분), `pr.ids` 조건부 기록(W2) |
| S-4a·S-4 | 파서 포팅·골든, 규칙·시드 유형, `parser-rules` 이슈 DB 층(`phone_id_patterns`·`ril.yaml tags`, RF-4 잔여) | 설정 층 순서는 `contracts.md`에 명시됨. 이슈 DB 층 구현은 사외에서 W 뒤에 할 수 있으나 실제 값은 사내 |
| S-5 | 오프라인 평가, 샌드박스 PR, 토큰 기준치 | `offline_eval.py`, `usage_stats.py`(W11) |
| S-7 | 배포·파일럿 지표 | `usage_stats.py`, `plugin.json` 정리 항목 |

사내에서 사외 코드를 고치게 되면 `15-local-draft.md §15.6`대로 요지를 타이핑해 사외로 보내고, 다음 W 또는 재반입에서 반영한다.

## 5. 미루는 것 (W 범위 밖)
- RF-5 oFono, RF-6 커넥터, RF-8 자동화: 사내 수요 확인 뒤.
- `99-deferred.md §E` Read 도구 차단: 사내 S1 확인 뒤.
- 설정 3층의 마지막(이슈 DB 규칙 층) 구현: S-4 값이 정해진 뒤 사외에서.

## 6. 예상 규모와 시간

코드 줄 수는 추가·수정 합계, 시간은 계획→실행→리뷰→테스트 한 바퀴의 에이전트 작업 시간이다. 사용자 확인 대기와 eval 재실행(Sonnet, 건당 5~10분)은 별도.

| WP | 코드 변경 | 파일 | 테스트 | 시간 | 위험 |
|---|---|---|---|---|---|
| W0 | 150~200줄 | 3 | 기존 2~3 수정 | 2~3h | 낮음. `claude -p` usage 형식이 버전마다 다를 수 있음 |
| W1 | 200~300줄 | 5 | 기존 8~10 수정 | 3~4h | 중간. 스킬이 사라진 키를 참조하는지 전수 확인 |
| W2 | 250~350줄 | 4 | 신규 스냅샷 3~4 | 4~5h | 중간. eval 1·30·53 재실행 필수 |
| W3 | 80~120줄 | 3 | 신규 3~4 | 2~3h | 낮음 |
| W4 | 150~250줄 | 3 | 기존 6~8 수정, 신규 3 | 4~6h | 높음. 질문 순서·멱등 재실행 상태 전이 테스트 재작성 |
| W5 | 100~150줄 | 3 | 기존 4 수정, 신규 2 | 2~3h | 낮음. guard `publish` ask 유지 확인 |
| W6 | 코드 0, 문서 −17KB | 12 | 크기 검사 1~2 | 3~4h + eval 4건 | 중간. op 표 없이 모델이 맞게 쓰는지는 eval로만 확인 |
| W7 | 400~600줄 | 6 | 신규 ~10 | 1~1.5일 | 높음. 산문 설명과 생성 가능 부분을 가르는 설계 결정. "옵션·출력 키만 생성, 동작 설명은 유지"로 좁힌다 |
| W8 | 200~300줄 | 3 | 신규 5~6 | 3~4h | 낮음 |
| W9 | 200~300줄 | 5 | 기존 4 수정, 신규 5 | 4~5h | 중간. gh 스텁에 `pr list --author` 확장 |
| W10 | 이동 3,000줄 + 신규 100줄 | 10~12 | 수정 0 목표, 전체 1회 | 1~1.5일 | 중간. import shim 누락 시 사내 site 백엔드가 깨짐 |
| W11 | 300~400줄 | 8~10 | 신규 8, 스냅샷 재생성 | 1일 | 중간. `msg` 복사 제거는 `events.json` 스냅샷 전부 재생성(사용자 승인) |
| W12 | 150~200줄 | 문서 6, 코드 2 | 신규 3 | 4~6h | 낮음. 참조 링크 |
| W 끝 | 0 | — | 전체 8분 + eval 54 | 3~4h | 한도(429)면 분할 실행 |

합계: 코드 2,500~3,300줄(이동 3,000줄 별도), 신규 테스트 40~50개, 에이전트 7~9 작업일, 달력 2~3주.

**의존과 병렬**
- 의존 없음: W0, W3, W8, W9 → worktree를 나눠 동시에 가능.
- W1 → W2 → W5 → W7 (CLI 출력이 안정된 뒤 생성기).
- W4 → W10 (둘 다 `triage.py`; 같이 하지 않는다).
- W6는 W2·W3 뒤. W12는 마지막.
- eval 재실행은 WP별로 한다(W0 토큰 표로 회귀 WP를 가린다).

## 7. 진행 표 (오케스트레이터가 갱신)

| ☐ | WP | 상태 | 브랜치·커밋 | 비고 |
|---|---|---|---|---|
| ✅ | W0 | ✅ 완료(10/06) | ccr-2495ec74-xn15cn · 커밋 `W0: 토큰 측정…` | 기준선 `token_baseline.json`, 여유율 1.3 |
| ✅ | W1 | ✅ 완료(10/06) | ccr-2495ec74-xn15cn · 커밋 `W1: 출력 다이어트…` | stdout 33%, record verify는 `--verbose`(eval 18 회귀) |
| ✅ | W2 | ✅ 완료(10/06) | ccr-2495ec74-xn15cn · 커밋 `W2: 결정적 렌더링…` | W2 영향 미확인: eval 9·18·20~23·26·31·54. W2 보류: 검색 전용 문구(search.md는 `--brief` JSON 유지, eval 53) |
| ✅ | W3 | ✅ 완료(10/06) | ccr-2495ec74-xn15cn · 커밋 `W3: verify-fix…` | eval 25 Sonnet 3/3, verify-fix Sonnet 기본. W3 영향 미확인: eval 21·22·26·27·33 |
| ✅ | W4 | ✅ 완료(10/06) | ccr-2495ec74-xn15cn · 커밋 `W4: 질문 수 줄이기…` | eval 55·56 질문 1→0. 영향 미확인: eval 42·45 등 explore 사용 eval |
| ✅ | W5 | ✅ 완료(10/06) | ccr-2495ec74-xn15cn · 커밋 `W5: 쓰기 흐름 왕복 축소…` | eval 1 Step 8 Bash 6→2, 토큰 699k→386k. 커밋은 `publish --commit`(계약 반전, 사용자 승인). write-flow +348B는 W6에서. 테스트 임시 디렉토리 누수는 별도 chore 커밋으로 정리 |
| ☐ | W6 | 실행 중 | ccr-2495ec74-xn15cn | W2·W3 뒤. search 제외: 읽기 전용, Read 1회·1.5KB 절약 |
| ☐ | W7 | 대기 | | W5 뒤, 실행 Opus |
| ☐ | W8 | 대기 | | 독립 |
| ☐ | W9 | 대기 | | 독립 |
| ☐ | W10 | 대기 | | W4 뒤, 실행 Opus |
| ☐ | W11 | 대기 | | 항목별 커밋 |
| ☐ | W12 | 대기 | | 마지막 |
| ☐ | W 끝 | 대기 | | 전체 테스트·eval 54·`make_bundle.py` |

상태 값: 대기 / 계획 확인 중 / 실행 중 / 리뷰·테스트 중 / 완료 확인 중 / ✅ 완료(날짜). 독립 WP를 병렬로 돌리면 "실행 중 — 브랜치 X"로 적는다.

## 8. "개선안 진행" 절차 (오케스트레이터)

전제: 세션은 레포 루트, 최신 main(또는 지정 브랜치)에서 시작. 의존성은 `pip install '.[test]'`.

1. **선택**: §7에서 ☐ 첫 WP(의존 WP가 ✅인 것). 상태를 "계획 확인 중"으로.
2. **계획** — `Agent(subagent_type="Plan", model="opus")`. 입력: 이 문서의 그 WP 절, §1·§2, `CLAUDE.md`, `docs/design/12-principles.md`, WP 절이 가리키는 설계 문서 **절** 경로, 바꿀 파일 경로. 출력: 바꿀 파일·함수, 동기화 문서 목록, 신규·수정 테스트 목록, 완료 기준 재확인, 위험. 오케스트레이터가 검토해 요약하고 **사용자 확인**을 받는다.
3. **실행** — `Agent(model="sonnet")`(W7·W10은 `"opus"`). 입력: 확정 계획, 원칙 파일, 대상 파일. 지시: 계획 밖 변경 금지, 테스트·문서 동기화 포함, `python3 tools/related_tests.py`(실행 없이)로 영향 범위를 보고. 끝나면 변경 파일 목록과 요약을 돌려준다.
4. **리뷰** — `Agent(model="opus")`. 입력: `git diff`, 계획, `contracts.md` 관련 절, `12-principles.md`. 출력: 차단 / 권고 / 통과와 근거. 차단이면 3번으로(같은 WP 두 번 차단이면 2번으로).
5. **테스트** — `Agent(model="haiku")`. 지시: `python3 tools/related_tests.py --run` 실행, 결과를 파일·테스트·원인 한 줄 표로. `full: true`면 보고만. 실패면 3번으로. 오케스트레이터는 도구가 full을 요구하면 전체 `pytest -q --tb=short tests`를 직접 돌린다.
6. **종합** — 바뀐 파일, 테스트 수(신규·수정·통과), 리뷰 권고 처리, 완료 기준 대조를 요약해 **사용자 확인**. 상태 "완료 확인 중".
7. **마무리** — 커밋(WP 번호를 제목 앞에: `W3: …`), `git push -u origin <브랜치>`, §7 표 ✅(날짜·커밋), `docs/history/CHANGES.md`에 WP 절 한 단락, `DRAFT_NOTES.md` W 행 갱신. 다음 WP는 사용자가 다시 "개선안 진행"이라고 할 때.
8. **병렬**: 사용자가 "W3·W8 같이"처럼 지정하면 `EnterWorktree`로 분리해 각각 2~7을 돌린다.

에이전트에 주는 공통 금지: `docs/history/` 읽지 않기, 설계 문서 통째 읽지 않기, 로그 원문·`events.json` 통독 금지, 이슈 DB 샘플(`tests/fixtures/issue-db-sample/`) 직접 수정 시 `make_sample_fixtures.py --check` 통과, 생성 파일은 `db_build.py`로만.
