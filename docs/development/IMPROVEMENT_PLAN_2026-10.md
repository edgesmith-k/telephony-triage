# 개선 트랙 W — 계획과 실행 틀 (2026-10-06)

- 범위: 토큰 절약, 사용자 편의성, 장기 유지·관리, 기타 보완. 반입 전 사외에서 끝내고, 사내에는 **사내 환경·로그에 맞추는 일만** 남긴다.
- 위치: `DRAFT_NOTES.md` "반입 전 보강 트랙"의 3F 뒤, Z(반입) 앞에 **W**로 넣는다. 각 작업 묶음(WP)이 끝날 때마다 사용자 확인을 받고 표를 갱신한다.
- 원칙은 그대로다: `CLAUDE.md`·`12-principles.md`. 판정은 스크립트 출력, 스킬은 설명·확인만. 설계 문서(`contracts.md`·`07`·`10` 등)와 코드가 함께 바뀐다.
- 근거: 세션 분석(구조 → 3축 검토 → 토큰 검토). 이미 RF 계획에 있던 항목은 "RF-n"으로 표시한다.

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
- 변경: `tests/skill_evals/run.py`(`claude -p --output-format json` usage → `execution.json`), `grade.py`(eval별 토큰 표, 상한 초과를 실패로 세는 `--token-budget`), `README.md` 절 추가.
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
- 테스트: `test_db_pr`(summary 스냅샷), `test_db_search`, `test_commands`. 사내 잔여: 없음.

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
- 목표: `db-authoring.md` 27KB → 10KB 이하(op·drift·fixture·R 표 제거, 스키마·오류 메시지가 대신). `SKILL.md`의 실행 규칙을 `reference/rules.md`로 떼어 record·verify·sync-pr·search가 그 파일만 읽게.
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
| S-3 | `site-defaults.yaml`·이슈 DB config | guard 규칙 10 예외 키(W11), `platform` 키(RF-4 완료분) |
| S-4a·S-4 | 파서 포팅·골든, 규칙·시드 유형, `parser-rules` 이슈 DB 층(`phone_id_patterns`·`ril.yaml tags`, RF-4 잔여) | 설정 층 순서는 `contracts.md`에 명시됨. 이슈 DB 층 구현은 사외에서 W 뒤에 할 수 있으나 실제 값은 사내 |
| S-5 | 오프라인 평가, 샌드박스 PR, 토큰 기준치 | `offline_eval.py`, `usage_stats.py`(W11) |
| S-7 | 배포·파일럿 지표 | `usage_stats.py`, `plugin.json` 정리 항목 |

사내에서 사외 코드를 고치게 되면 `15-local-draft.md §15.6`대로 요지를 타이핑해 사외로 보내고, 다음 W 또는 재반입에서 반영한다.

## 5. 미루는 것 (W 범위 밖)
- RF-5 oFono, RF-6 커넥터, RF-8 자동화: 사내 수요 확인 뒤.
- `99-deferred.md §E` Read 도구 차단: 사내 S1 확인 뒤.
- 설정 3층의 마지막(이슈 DB 규칙 층) 구현: S-4 값이 정해진 뒤 사외에서.
