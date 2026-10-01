# Telephony Plugin Improvement Handoff

## Status

- **RF-0 완료, RF-1(I3) 코드·문서 완료** — 2026-10-01. RF-1 행동 평가·토큰 실측은 10/11 Phase 13.
- 검토 기준 commit: `47ba4c9602a6c6ba5c7022816dd9d3d220a44acf` (Phase 13 평가 정의·계획 스키마 수정).
- 기존 개발 Phase D0, 1~12 완료; **Phase 13 진행 중**. 아래 개선 단계 I0~I6는 기존 Phase 번호와 별개다.
- 이번 허용 범위: DRAFT_NOTES 표 2번 RF-1(driver·SKILL ≤8KB·커맨드·외부 리뷰 토큰 항목), 전체 테스트 통과 후 push. 개발 Phase·행동 평가(`run.py --execute`)·`CLAUDE.md` ≤4KB는 하지 않는다.
- Claude 행동 평가: 최신 재개에서 0건 실행. 이전 일부 평가 결과만 존재한다. 429 사용량 제한 기록은 `DRAFT_NOTES.md`(막힌 것)과 `docs/history/draft-notes-2026-09.md`의 Phase 13 절에 있다. 한도 해제 시각 기록을 현재 사용 가능 여부로 간주하지 않는다.

## Purpose

이 문서는 plugin 개선/refactoring 작업 중 **cross-agent/cross-machine handoff를 위한 임시 문서**다. 개선 작업 완료 후 삭제 여부를 검토해야 한다. 진행 상태·미해결 문제·수정 순서만 관리하며 영구 architecture/spec의 canonical source가 아니다.

기존 리뷰를 다시 수행하지 말고 아래 근거와 다음 미완료 단계에서 이어간다. 이슈 번호 R1~R15는 리뷰와 연결하는 안정적인 식별자다. 행 번호는 기준 commit의 탐색 힌트이며 symbol을 우선한다.

### Source of truth / clone 시 주의

- 리뷰의 요구사항 기준은 원본 `telephony-triage-docs-v11/telephony-triage-docs/`였다. **그 폴더와 ZIP은 `.gitignore` 대상이므로 clone에 없다.** 필수 인계 근거는 이 문서에 남겼다. 원본을 임의로 복원하거나 다운로드할 필요는 없다.
- 유지보수할 canonical 문서는 `docs/design/`이며 공유 계약은 `docs/design/contracts.md`가 우선한다. 원본과 현재 설계의 차이를 새 결함으로 오인하지 않는다. 결정 이력은 `CHANGES.md`, `DRAFT_NOTES.md`, `docs/history/REVIEW-10.md`, `docs/history/REVIEW-11.md`에 있다.
- 현재 설계의 의도된 보완: Jira 추출용 `jira_fields.py`, 원인에 특정한 recovery 예시, 직접 편집 migration 안내, publish/pre-push 검사 강화. 원본과 달라졌다는 이유로 되돌리지 않는다.
- `DRAFT_NOTES.md`는 기존 Phase 진행 상태, 이 문서는 개선 단계 상태를 관리한다. 사내 모드의 상태·값은 `SITE_PROFILE.md`와 `SITE_PATHS`를 따른다. `.local-draft`도 clone에 없으므로 새 PC에서는 `CLAUDE.md`의 모드 판별 절차를 따른다.
- `tests/skill_evals/workspace/`는 비추적이다. 새 PC에서 기존 실행 산출물이 있다고 가정하지 않는다. 추적된 runner/fixture로 새 iteration을 만든다.

## Current Architecture

12개 command → 단일 `plugin/skills/telephony-triage/SKILL.md` 또는 흐름별 reference → Python CLI → 분석 보고 → 사용자 확인 → plan/stage/summary/commit/publish. 별도 agent 구현은 없다. 선택적 category analyzer는 보조 의견만 제공한다.

분석은 Jira 추출·마스킹 → logcat backend/규칙/extractor → S(증상)/C(원인) 매칭 → 선택적 소스 확인 순서다. plugin과 운영 이슈 DB는 별도 저장소이며, 분석은 snapshot, 변경은 도구 worktree를 사용한다. `db_verify`는 R1~R6와 fix/resolution 판정, `db_pr`는 쓰기 절차를 소유한다.

설계 지도: `01-architecture.md`(책임), `02-config.md`(설정), `03-issue-db.md`(지식 DB), `04-parser-matching.md`(분석), `05-verification.md`(검증), `07-workflow.md`(대화), `08-safety.md`(안전), `10-skill-eval.md`(평가), `16-existing-assets.md`(사내 자산). 모두 `docs/design/` 아래다.

평가 결론: DB 기록·검증 구조는 재사용 가치가 높다. 정확성·관측 완전성·쓰기 경계 문제를 먼저 고쳐야 한다. **oFono, CP 원본 로그 파싱은 v11 요구사항이 아니며**, 사내 parser/실제 로그 미연결은 계획된 후속 단계다. Ubuntu가 배포 대상이며 Windows 개발 테스트만으로 운영 적합성을 선언하지 않는다.

## Key Root Problems

경로 약어: `S/` = `plugin/scripts/`, `K/` = `plugin/skills/telephony-triage/`, `C/` = `plugin/commands/`, `D/` = `docs/design/`.

| ID / 분류 | Problem / Cause | Impact | Target solution / 근거 위치 |
|---|---|---|---|
| R1 High, 구현·계약 보완 | `same_phone`가 각 signature 내부에만 적용되고 S와 C는 전체 이벤트에서 독립 선택된다. | SIM0 증상과 SIM1 원인이 높은 점수로 결합된다. | `S/match_signatures.py::match`(283/299), `S/common/signatures.py::Evaluator.evaluate`에 match 슬롯·구간 보존 및 분석 후보 결합 조건. 회귀 모드의 독립 C 평가는 유지. `D/04` §5.11, `docs/history/REVIEW-11.md` U4, eval 44의 의도. |
| R2 High, 구현 결함 | `Lock.acquire`가 read→일반 write이며 원자적 상호 배제가 없다. JSON 읽기 실패도 부재로 취급한다. | 두 작업이 동시에 lock을 얻고 snapshot·cleanup·상태가 경쟁한다. | `S/db_pr.py::Lock`(100), `S/db_verify.py::_check_lock`: 짧은 OS lock 안에서 read/update/release, lease atomic write, owner 식별자. atomic replace만으로 acquire 경합은 해결되지 않음. `D/contracts` §3.2 lock. |
| R3 High, 구현 결함 | 작업 키를 경로 부모 이름에서 얻고 work_dir 경계를 강제하지 않는다. Git worktree 삭제 실패 뒤에도 rmtree한다. | 잘못 준 경로에서 reset/clean/삭제로 사용자 데이터 손실 가능. | `S/db_pr.py::_job_of/_prepare_worktree/_remove_worktree/discard`(264/382/875), `S/db_verify.py::make_draft/remove_draft`: 정확한 작업 경로, symlink 경계, 소속 repo·도구 worktree 검증. `D/contracts` stage/discard, `D/07` Step 8. |
| R4 High, 구현 결함 | RIL pairing은 파일별인데 무응답 deadline에는 전체 입력 last_ts를 쓴다. | 회전 파일의 정상 응답을 놓치거나 다른 버퍼의 긴 coverage로 무응답을 생성한다. | `S/parser_backends/reference/__init__.py::parse`, `ril.py::pair`, `S/parse_logcat.py::_ril_events/run_parse`: 같은 capture의 회전 파일 연결, 스트림별 coverage, 부팅/장치 경계. `D/07` Step 3, `D/16` §16.3. |
| R5 High, 구현 결함 | 외부 parser 실패는 warning만 되며 replace는 실패 시에도 backend 이벤트를 제거한다. 검증은 이 warning을 오류로 보지 않는다. | 관측 실패를 C=0으로 해석해 recovery만 남으면 passed 가능. | `S/parse_logcat.py::_run_external/run_parse`, `S/db_regress.py::match_errors`(278), `S/db_verify.py::judge_resolution/judge_fix`(686/717): 필요한 parser의 completeness 확인, 실패는 unknown/환경 오류. `D/05` §5.12, `D/16` §16.3. |
| R6 High, spec·prompt 결함 | 승인 메시지를 `commit -m`의 큰따옴표 안에 그대로 삽입하도록 지시한다. 외부 텍스트의 instruction 경계도 명시하지 않는다. | 메시지의 shell 메타문자가 코드로 평가될 위험. PII 마스킹·승인 해시로 해결되지 않음. | `K/reference/write-flow.md:103`, `C/sync-pr.md:40`, `D/07` Step 8-6: 메시지 파일 + commit -F 또는 argv helper. add/commit 별도 호출·git hook 유지. Jira/log/source는 데이터로만 취급. |
| R7 Medium, spec 공백 | backend의 `_file/_line`을 버리고 evidence가 시각·태그 중심이다. cut도 `(ts, tag)`로 앵커를 재탐색한다. | 중복 시각·태그에서 원본 근거 식별과 fixture 선택이 불명확. | backend→derived event→Evaluator→report→`S/parse_logcat.py::_cut_anchors`에 input ID/원본 행/event ID 유지. `D/04` 이벤트 계약, `D/07` Step 6 보완. |
| R8 Medium, spec 결함 | 기본 S=C=1이면 base=1.0, 보너스는 min(1.0)에서 포화된다. 피드백이 없으면 여러 원인이 ID 순 동점이며 이를 신뢰도로 표시한다. | 시간 근접성이 순위에 반영되지 않고 규칙 일치가 원인 확정처럼 보인다. | `S/match_signatures.py::_candidate`, `K/SKILL.md` Step 6: 규칙 일치 점수와 진단 신뢰도 분리. ranking 변경은 합의 후 `D/04` §5.11 동기화. |
| R9 Medium, spec 모호성 | command/reference는 흔적 없으면 중단, Python과 reference의 다른 줄은 비코드 원인에 user_confirmation_required 예외를 허용한다. | 동일 입력에서 서로 다른 안내·불필요한 차단. | `C/verify-fix.md`, `K/reference/verify.md:91~93`, `S/db_verify.py::judge_fix`; `D/05` §5.12와 `D/07` verify-fix의 충돌을 유형별 분기로 먼저 정리. |
| R10 Medium, prompt 결함 | validate는 config clone을 선택한 뒤 경로 없는 git fetch를 지시하고 base_branch 설정 위치도 잘못 적는다. | cwd가 plugin repo면 다른 remote를 fetch, DB의 오래된 ref/잘못된 base 검사. | `C/validate.md:20~22`: resolved DB로 git -C/--db 통일, 사용자 config의 issue_db.base_branch 사용. `D/contracts` §3.2. |
| R11 Medium, 지식 결함 | RIL 요청 부재=DNC 차단, 시계 점프=재부팅/NITZ로 단정한다. | 누락·필터·시간 공백을 원인 증거로 오해. | `K/reference/ril-requests.md:41`, `log-tags.md:62`: 관측 사실·추론·전제·반례 구분. `D/07` Step 3/5/6. |
| R12 Medium, context 결함 | record는 analyze를 읽지 말라면서 SKILL Step 0/2를 참조하고 sync-pr 절차는 command/reference에 중복된다. | 불필요한 로드, 예외 규칙 drift. | `C/record.md`, `K/reference/record.md/verify.md/sync-pr.md`, `C/sync-pr.md`: 작은 공통 실행 규칙, 흐름별 단일 원본. `D/10` SKILL 구성. |
| R13 Medium, 검증 공백 | runner는 SKILL 직접 Read, mock CLI, 빈 MCP; plugin-dir/실제 Skill/guard 연결이 없다. 일부 채점은 모델 작성 commands.md 문자열을 본다. | workflow eval 통과를 실제 plugin 작동 통과로 오해할 수 있음. | `tests/skill_evals/run.py::evaluation_prompt/execute`, `grade.py`: 실제 tool trace 채점 + 별도 설치 통합 평가. README의 한계를 유지. `D/10`, `D/11` Phase 13, `D/14` S1. |
| R14 Medium, 제품 범위 공백 | Jira/DB 중심 진입, analyzer는 1위 카테고리 의존, plan 재개만 있고 입력 hash·가설 수정 상태는 없다. | 후보 없는 신규 문제·추가 로그·부분 재분석 UX가 약함. | `C/analyze.md`, `K/SKILL.md` Step 0/2/5-1: 합의 후 분석 전용 경로·analysis manifest. Jira는 기록 시 필수로 분리하는 안. v11 위반으로 취급하지 않음. |
| R15 Medium, 규모 위험 | 전체 파일 결합·coverage·parse 중복 적재, window 후보마다 hit 순회, symbol 전체 트리 검색. | 대용량 메모리/시간 비용, window 탐색은 많은 hit에서 이차 비용 가능. | `S/parse_logcat.py::_read_texts`, backend coverage/parse, `Evaluator._search_window`, `S/code_roots.py::cmd_find_symbol`: 대표 크기 측정 후 결과 재사용·sliding window·검색 범위 제한. GB급 장애는 미측정. |

### Evidence already obtained

- 이전 리뷰에서 전체 `python -X utf8 -m pytest -q -p no:cacheprovider tests`: **226 passed in 999.42s**, Windows/Python 3.14. `PYTHONDONTWRITEBYTECODE=1` 사용. 이번 문서 커밋에서는 runtime을 변경하지 않았으며 이 결과를 새 테스트 실행으로 표기하지 않는다.
- R1: 같은 60초 구간의 SYM(phone 0)와 CAUSE(phone 1), 각각 단일 조건 signature를 기본 same_phone=true로 평가 → S=1/C=1/score=1.0/high. 기존 eval 44는 한 원인 signature 내부 조건을 슬롯별로 나눠 이 결합 결함을 놓친다.
- R2: 임시 디렉터리에서 두 Lock 인스턴스의 read 완료를 barrier로 맞춘 두 스레드 → 서로 다른 job 모두 acquired=true. 실제 다중 프로세스 부하 시험은 아직 아니다.
- R4: 첫 파일 SEND_SMS request, 두 번째 파일 같은 pid/phone/serial의 1초 뒤 정상 response와 60초 뒤 줄 → ReferenceBackend.parse의 paired_ts=null, `_ril_events`에서 ril_no_response 생성.
- R5: parse 결과에 external-parser-failed warning과 남은 recovery event를 주입하고 C=S=0·recovery hit인 검증 함수 → passed. `_traces`를 대체한 함수 수준 실험이며 실제 외부 프로세스 실패 통합 재현은 I0/I2에서 추가한다.
- 위 실험은 임시·메모리 실험이며 재현 스크립트는 커밋되지 않았다. R3 삭제·R6 shell 공격은 실행하지 않고 코드로 확인했다. 나머지는 정적 분석이며 실제 Claude 행동을 관찰했다고 주장하지 않는다.
- 사내 실제 로그·MCP·GHE·Ubuntu 배포 검증은 미실행. 과거 eval 일부 통과와 최신 미실행 상태의 상세는 `docs/history/draft-notes-2026-09.md` Phase 13, 평가 방식은 `tests/skill_evals/README.md` 참조.

## Priority

### P0

R1~R6. 잘못된 원인/검증 통과와 사용자 파일·동시 작업·shell 안전성을 먼저 해결한다. 쓰기 경계(I1)를 먼저 고친 뒤 분석 정확성(I2)을 수정한다. 이 기간에는 실제 사용자 clone이나 운영 DB로 파괴적 재현을 하지 않는다.

### P1

R7~R13. 근거 추적·신뢰도·모호한 지시·검증 대상·context·실제 plugin 평가를 보완한다. spec 결정이 필요한 R8/R9는 제안이 이미 승인됐다고 간주하지 않는다.

### P2

R14~R15. 반복 분석·자연어 진입·대용량 비용을 측정하고 단계적으로 개선한다. 현재 엔진을 재사용하며 제품 범위 확대는 먼저 합의한다.

### P3

실제 수요가 확인된 뒤 oFono/추가 vendor/platform, 더 강한 episode/state 모델을 검토한다. `D/99-deferred.md`의 3-way replay·동시 읽기 임대는 지금 필수로 복원하지 않는다. cleanup은 모든 단계에서 후보만 관리하고 실제 삭제는 I6에서 별도 허용 범위 확인 후 한다.

## Implementation Phases

각 단계는 Goal/Tasks/Target/Dependency/Validation/Exit를 아래에 요약한다. 구현·테스트·필요한 canonical 문서 동기화를 같은 단계에서 수행한다.

| Phase | Goal / Tasks | Target files/components | Dependency | Validation / Exit criteria |
|---|---|---|---|---|
| I0 Baseline | 기준 commit 이후 변경 확인, R1~R6 최소 재현을 합성 regression으로 고정, 명세 결정 분리 | `tests/test_match_signatures.py`, `test_db_pr.py`, `test_parse_logcat.py`, `test_db_verify.py`, prompt 관련 tests | 해당 개선 작업의 구현 허용 범위 확인 | 기존 suite 통과와 새 결함 재현을 구분. 의도된 실패 test는 고치는 Phase와 함께 commit하거나 격리 관리하여 main을 깨뜨리지 않음. R5 실제 실패 경로·R3 안전한 임시 디렉터리 사례 포함 |
| I1 Write safety | R2 lock 원자성/owner, R3 경로 제한, R6 데이터로 커밋 메시지 전달 | `S/db_pr.py`, `S/db_verify.py`, write-flow/sync-pr, `D/contracts`, `D/07`, safety tests | I0 | 동시 acquire 하나만 성공, stale owner가 새 lock 해제 불가, 범위 밖 경로는 아무 변경 없이 거부, shell 메타문자 메시지 literal 보존, 승인/lease/hook 회귀 통과 |
| I2 Analysis correctness | R1 슬롯/구간 결합, R4 capture pairing/coverage, R5 실패 전파, R7 provenance 계약 | matcher/signatures, backend/ril, parse_logcat, regress/verify, `D/04/05/16/contracts` | I0, I1 | cross-slot 오탐 없음·명시적 교차 슬롯 사례 유지, 회전 정상 응답에서 무응답 없음, parser 실패에서 passed 없음, evidence→원본 행/cut 재현. 독립 C 회귀 의미 유지 |
| I3 Prompt/report/context | R8 점수 의미, R9 예외 분기, R10 validate 대상, R11 단정 제거, R12 중복 정리 | `K/`, `C/`, matcher(합의된 ranking 변경만), `D/04/05/07/10` | I2; R8/R9 명세 결정 | command별 자기 흐름 로드, 비코드/코드 검증 분기, DB 밖 cwd·비main base 검사, 보고서의 사실/가설/반대 근거/다음 action. 스킬 변경은 skill-creator 지침·eval 적용 |
| I4 Product/scale | 합의된 R14 분석 전용·재사용 상태, R15 측정과 필요한 최적화 | analyze, 분석 manifest, parser/window 검색, code_roots, 사용법 | I3, 제품 범위 합의 | 기존 Jira 기록 흐름 유지, 입력/규칙/source 변경 시 cache 무효화, 추가 로그가 기존 가설을 반박하는 testcase, 대표 크기 성능 결과. 불필요한 framework 도입 없음 |
| I5 Runtime qualification | R13 tool trace 기반 채점, 45개 실제 행동·trigger·설치 통합 검증 | `tests/skill_evals/`, `tests/test_skill_evals.py`, `DRAFT_NOTES.md`, 사내 S 단계 산출물 | I3, 포함하기로 한 I4 완료; 실제 Claude 사용 가능 환경 | batch 1 수정 확인 + 남은 B/C/D, 전체 결과의 현재 버전 유효성 확인. plugin-dir command/Skill/hook/MCP 연결은 별도 검증. quota/미실행/수동 미채점은 통과 금지. 기존 Phase 13 종료 조건 충족 전 완료 표시 금지 |
| I6 Final cleanup | 최종 architecture·canonical 문서·삭제 후보·인계 필요성 검토 | `D/`, GUIDE/README, 아래 cleanup 목록, 이 문서·DRAFT 링크 | 채택한 I0~I5 exit 충족 | 최종 suite·관련 eval 통과, Ubuntu/사내 미검증 범위 명시, 링크·참조 점검, 승인된 후보만 삭제. Handoff 내용 이관 후 자체 삭제 여부 결정 |

## Current Progress

- [x] 구조·v11 대조 리뷰 및 핵심 root cause 분석 완료
- [x] 기존 자동 suite 226개 통과, R1/R2/R4/R5 소규모 재현 기록
- [x] 임시 Handoff·우선순위·개선 단계·cleanup 조건 작성
- [x] I0: RF-0 baseline 및 `tests/test_safety.py`의 결함별 수정 전 fail → 수정 후 pass
- [x] I1: 쓰기·lock owner·경로·shell 안전성
- [x] I2: RF-0 범위의 슬롯/시간 결합·capture 관측·파서 실패 전파; 독립 C 회귀 보존 (원본 행 provenance는 후속 범위)
- [x] I3: prompt·보고서·context 정리 — RF-1: `triage.py` driver(needs_input), `jira_bridge.py`(MCP 원문 격리), SKILL 8.1KB, 커맨드 보일러플레이트 제거·sync-pr 단일 원본(R12), 리포트 사실/추정/반대 근거 규칙. R8 점수 의미는 리포트 문구만(랭킹 변경 없음), R9·R11·R7은 미완
- [ ] I4: 합의된 UX·반복 분석·규모 개선
- [ ] I5: 실제 Claude 행동·trigger·plugin 통합 평가
- [ ] I6: 최종 regression·canonical 동기화·cleanup·Handoff 삭제 검토

Completed: RF-0 R1~R11 결함별 수정·커밋 및 session 임시 플러그인 루트 적용(남은 격리 테스트는 RF-1 커밋에서 해제). RF-1(I3) driver·SKILL·커맨드·외부 리뷰 토큰 항목. 이 문서 원래 R7~R11과 외부 리뷰의 RF-0 R7~R11은 번호 체계가 다르다. 원본 행 provenance 등 RF-0에 포함되지 않은 요구는 완료로 간주하지 않는다.

Remaining (이 문서 원래 번호): R7 provenance, R8 점수/신뢰도, R9 verify-fix 예외, R11 지식 단정, R12 context 중복, R13 실제 통합 평가, R14 UX, R15 규모 개선. 원래 R10(validate 대상)은 RF-0 R11로 수정했다.

## Next Actions

> 2026-10-01 갱신. 순서의 단일 원본은 `DRAFT_NOTES.md` "활성 트랙과 순서" 표다. I0~I2는 리뷰 문서의 **RF-0**에 흡수됐고, 외부 리뷰가 찾은 R7~R11이 추가됐다(리뷰 문서 머리 "외부 리뷰 결과").

1. **2026-10-11 Phase 13** (I5): 새 SKILL(8.1KB)로 새 iteration에서 행동 평가 45개·트리거 시험. 같은 날 S1 빈 플러그인 실험으로 PostToolUse `updatedToolOutput`(원문 대체)과 eval 1건 usage(analyze Bash 호출 수·토큰)를 실측해 RF-1 추정치와 비교한다. 한도·인증 오류에서 자동 반복하지 않는다.
2. **RF-1 후속**(Phase 13 결과에 따라): R7 provenance(`line_ref`, `common/events.py`), `config.py show --keys`, R9 verify-fix 예외·R11 지식 단정, `CLAUDE.md` ≤4KB(§12 이동 사용자 결정 후).
3. **RF-2**: Phase 13 뒤 반입 staging·crash 복구·경계 검사·사외 CI. 이번 apply 예외 rollback을 전체 트랜잭션 내구성으로 간주하지 않는다.

## Regression Requirements

- `python3 -m pytest -q tests`가 전체 기준. 변경 중에는 해당 `test_<component>.py`를 우선 실행하고 최종 통합 시 전체를 실행한다. Python/의존성은 repo 문서에 맞춘다. 과거 Windows 통과와 Ubuntu 검증을 구분한다.
- 마스킹 멱등성·기존 토큰 번호 회피·동일 값 관계·credential 처리, backend/external event masking, raw 입력 matcher 거부를 보존한다. 원본 식별자·사내 로그를 테스트/commit에 넣지 않는다.
- signature의 sequence/동일 시각 순서/null phone wildcard/명시적 same_phone=false를 보호한다. cross-slot 완전 S/C, 같은 SIM 복수 call, IMS+default, 부팅·pid·serial 재사용, 회전 파일·tail 누락을 추가한다.
- 회귀는 모든 active 원인의 C 독립 평가, score/feedback 비의존, `also_allowed` 계약, pending/unresolved 기대값을 유지한다. 분석 후보 결합을 고치면서 회귀 의미를 바꾸지 않는다.
- 외부 parser timeout/nonzero/변환 오류/일부 파일 실패/replace에서 필요한 관측이 없으면 검증 passed 금지. fix/resolution의 unknown/partial/failed, 빌드 비교, scenario/recovery와 비코드 예외를 검사한다.
- 사용자 clone·로컬 브랜치 불변, drift 재확인, ID/fixture 재할당, plan 재적용 무중복, 승인 hash/메시지/단일 commit 검사, lease push, git hooks, Jira read-only, 종료 경로 lock 해제를 유지한다.
- 경로 밖/symlink/다른 repo/일반 디렉터리 입력은 안전하게 거부하고 실패 뒤 삭제하지 않는다. 모든 삭제 재현은 전용 임시 경로에서만 수행한다.
- semantic eval은 필수 event/error/layer/evidence와 금지 결론·불확실성을 채점한다. 외부 텍스트의 지시 무시, 새 근거에 따른 가설 변경, 필요한 다음 action을 포함한다. `commands.md` 자기보고만으로 실행을 증명하지 않는다.
- parser 포팅 골든·실제 마스킹 라벨셋은 `SITE_PATHS` 규칙을 지킨다. 파일럿 정확도 기준은 사내 S 단계에서 합의하며 합성 테스트 통과로 대체하지 않는다.

## Repository Cleanup

**후보 등록은 삭제 승인이 아니다. 이번 단계에서는 아무 파일도 삭제하지 않는다.** obsolete implementation/unused prompt·skill·agent는 현재 확인된 삭제 대상이 없다. agents 디렉터리 부재는 미구현 결함이 아니다.

### Archive Candidates

| Path | Reason | Confidence | Delete-after condition |
|---|---|---|---|
| `docs/history/REVIEW-10.md`, `docs/history/REVIEW-11.md` (2026-10-01 이동 완료) | 과거 설계 변경안; 활성 지침과 혼동 방지 위해 역사 자료 위치 검토 | Medium | 결정이 canonical/CHANGES와 연결됨을 확인 후 archive 우선. 일괄 삭제 금지 |
| `telephony-triage-docs-v11/`, `telephony-triage-docs-v11.zip` (비추적) | 비교에 사용한 원본 사본·압축본 | Low | 원본 보존 위치와 비교 근거 확보, 개선 완료 후 로컬 보관 검토. 리뷰 중 source of truth를 제거하지 않음 |

### Delete Candidates

| Path | Reason | Confidence | Delete-after condition |
|---|---|---|---|
| `docs/development/PLUGIN_IMPROVEMENT_HANDOFF.md` — **DELETE CANDIDATE — AFTER IMPROVEMENT COMPLETE** | 임시 cross-agent 인계 | High, 조건부 | 모든 채택 improvement Phase 완료 + regression 통과 + 최종 architecture 확정 + 필요한 내용 canonical 반영 + 더 이상 cross-agent migration 필요 없음. DRAFT_NOTES 링크도 함께 정리 |
| `tests/skill_evals/workspace/<old-iteration>/` (비추적) | 로컬 평가 중간 산출물·중복 환경 | Medium | 필요한 평가 근거·실패 분석·비교 결과 보존, 해당 iteration 재사용 불필요 확인 후 로컬 정리. 실행 중/미분석 실패 자료 보존 |
| `.pytest_cache/`, `**/__pycache__/` (비추적) | 재생성 가능한 캐시 | High | 활성 실행 종료·필요한 진단 정보 없음 확인 후 로컬 정리 |

`K/reference/sync-pr.md` 등 중복 파일은 아직 삭제 후보로 확정하지 않는다. I3에서 canonical 실행 경로를 선택하고 모든 caller·tests를 옮긴 뒤 사용하지 않는 쪽만 등록한다. generated DB README/STATS/CHANGELOG, migrations, SITE_PATHS 자료는 단순 미사용처럼 보여도 임의 삭제하지 않는다.

## Temporary Development Artifacts

| File | Purpose | Delete when |
|---|---|---|
| `docs/development/PLUGIN_IMPROVEMENT_HANDOFF.md` | 개선 상태·근거·계획의 cross-agent 인계 | 위 DELETE AFTER IMPROVEMENT COMPLETE 조건 전체 충족 후 검토 |
| `tests/skill_evals/workspace/` (비추적) | iteration 환경·trace·채점 근거 | 필요한 근거를 안전하게 보존하고 평가 종료 후 iteration별 검토 |
| 원본 v11 폴더/ZIP (비추적, 위 경로) | 이전 spec 비교 자료 | 근거 보존·개선 종료 후 archive/delete 여부 검토 |

향후 임시 분석·migration note·중간 report·backup을 만들면 이 표에 목적과 종료 조건을 추가한다. 영구 regression fixture는 임시 artifact로 분류하지 않는다. `DRAFT_NOTES.md`는 기존 사외→사내 인계 역할이 있으므로 이 개선 종료만으로 삭제하지 않는다.

## Target Architecture

현재 12개 command·단일 coordinator skill·Python 엔진·분리된 운영 DB·plan 기반 쓰기를 유지한다. command는 얇게, 공통 실행 규칙은 한 곳에, domain/platform/version 지식은 필요할 때만 로드한다. 파서는 provenance·관측 범위·실패 상태를 내고 matcher/verifier가 이를 소비한다. LLM은 근거 기반 가설·반대 근거·다음 action을 설명하며 결정적 점수/검증을 임의 수정하지 않는다. 합의된 분석 상태 기능은 기존 쓰기 plan과 구분한다.

## Maintenance Rules

- 새 knowledge/failure pattern은 가능한 한 DB 규칙·signature·fixture로 추가한다. stable reasoning과 Android/vendor 로그 문구를 같은 prompt에 복사하지 않는다.
- agent/skill은 실제 독립 책임·context 절감 효과가 입증될 때만 추가한다. 지금 agent 증가나 범용 framework rewrite는 목표가 아니다.
- version/vendor 변경은 적용 범위·backend 버전·규칙 hash·소스 revision·골든을 함께 관리한다. `min_version` 통과만으로 동일 출력이라고 가정하지 않는다.
- prompt/skill 수정은 `CLAUDE.md`의 skill-creator 사용 원칙과 `tests/skill_evals/README.md`를 따른다. 실제 plugin 규격 변경 시 최신 공식 문서 또는 S1 실험으로 확인한다.
- 테스트는 behavioral/semantic assertion을 우선하고 snapshot 변경 이유를 검토한다. 미실행·skipped·quota 차단을 통과로 기록하지 않는다.
- deprecated 파일은 caller·문서 링크·migration/호환 책임을 확인한 뒤 archive/delete 후보로 등록한다. 삭제는 별도 허용 범위와 조건을 확인한다.
- 단계마다 허용된 범위에서 `Handoff → Phase 수정 → validation → progress 갱신 → diff 검토 → commit → configured upstream push`를 따른다. 사용자 무관 변경은 stage하지 않는다. force push·새 remote 생성·원격 history 변경 금지. push 실패 시 commit/branch/remote/원인/다음 조치를 보고한다.

## Handoff Instructions for Next Agent

1. 저장소 지침과 이 문서를 먼저 읽는다. 사용자 최신 지시가 우선이다.
2. 완료된 분석/Phase를 통째로 반복하지 않는다. 기준 commit 이후 변화와 해당 수정 근거만 확인한다.
3. `Current Progress`의 다음 미완료 Phase를 찾는다.
4. 그 Phase의 허용된 범위만 수정한다. 현재 문서 작성 요청을 runtime 수정 승인으로 해석하지 않는다.
5. 관련 regression을 실행하고 결과·환경·미실행 범위를 구분한다.
6. exit criteria를 충족하면 progress와 필요한 canonical 문서를 갱신한다. 완료 요약은 1~3줄로 유지한다.
7. 새 중요 문제는 Root Problems 또는 해당 Phase에 반영한다. 긴 조사 일지는 누적하지 않는다.
8. `Next Actions`를 최대 3개로 교체해 다음 agent가 바로 이어받게 한다.
9. 한 번에 여러 Phase를 무리하게 수행하지 않는다. 기존 `CLAUDE.md`의 Phase 확인 절차와 세션에서 받은 권한을 따른다.
10. 전체 개선 종료 시 canonical 이관·최종 regression·cleanup 조건을 확인하고 이 Handoff 자체의 삭제 여부를 검토한다. 상세 이력은 Git에 맡긴다.
