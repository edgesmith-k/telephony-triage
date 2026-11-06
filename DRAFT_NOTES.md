# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·남은 일·막힌 것·결정만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 지난 이력은 `docs/history/draft-notes-2026-09.md`(10/07 정리 전 전문 포함)와 `docs/history/CHANGES.md`. 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (사외 전용)

- **사내(`SITE_PROFILE.md` 있음)에서는 이 절을 무시한다** — 사내 시작은 `CLAUDE.md` 머리말과 `context_pack.py S-n`.
- 최신 main에서 시작하고 remote를 fetch한다(이름은 PC마다 `telephony` 또는 `origin`).
- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 진행해"** 로 하면 모드를 묻지 않는다(`touch .local-draft`).
- 의존성: `pip install '.[test]'`(고정 버전).
- Windows: `PYTHONUTF8=1`·stdin `/dev/null`·LF·`python3` shim(환경 실패 4건은 CI 통과).
- 테스트는 `tools/related_tests.py --run`(관련만). 전체는 도구가 full이라 할 때·반입 직전·요청 시.
- 진행 중 판단은 Fable 결정 에이전트에게(10/06 사용자). 사용자 승인 대상(이슈 DB push, main 병합·태그 등 지시 없는 외부 동작)은 사용자에게.

## 진행 상태 (11/06)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강 완료. 지난 묶음 **import-20261103**(main `77e2827`). 다음 묶음 **토 11/7 18:00 KST**(기준 `b4a5b42` + G).
- **H 단계 G 진행 중**: A1·A2·guard·C0·B1+B2 ☑, C1+D·보정·F·Jira 관문·C·C′(+코드 대조)·IMSI/ICCID 덤프 마스킹·후보 채점 브랜치 반영 `b4a5b42`(전체 3,855 통과). G: runtime-check opencode 확인 0을 OpenAI 호환으로, 도입·팀원 가이드 표시 정리(opencode/는 레포 읽기 전용 clone), 반입 노트(`MODULE_SKILLS_RESULT.md` "반입 노트": 75 새 eval 1회, 사내 할 일 8단계). 남은 G: 사용자 정답 표 확인 → 유료 1회차, CONCERNS HTML, 묶음.
- 모델 Sonnet 5.5 기준. `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서: `docs/book/telephony-triage-book.html`, 목록 `docs/materials/00-index.html`

## 남은 일 (사외 전용)

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ F | 묶음(11/7) — 사람 확인·태그·반입은 사용자 | SITE_INSTALL §8·반입 노트 |
| ☐ G | 범용판 별도 레포 — **보류(10/07 사용자)** | 재개는 사용자가 정한다 |
| ☐ H | 모듈 스킬 레포·+1 병합 — G만 남음 | `MODULE_SKILLS_PLAN.md §4` |
| ☐ I | OpenCode·사내 모델판 — 사외 몫 ☑(사내 확인 남음) | `docs/RUNTIME_ADOPTION.md` |

## 사내로 넘긴 것

- 사내 대상 eval 12개(`pending.json` `site`, S-2; 주입 59·60·+1 관문 75 포함, 사내 모델이 다르면 +7 — 이번 반입은 반입 노트 표로 영향 받는 것만), 코드 Read line 힌트(T4, S-2 측정 뒤)·offline_eval 오류율 상한(S-1 합의, S-5)·`max_tokens_hint` 처리(S-4a)·setup Jira 없음 중단(U1, S-3), db-authoring 스키마 요약 확장(S-2, 스키마 Read 횟수로 판단), 사내 마켓플레이스 소스 유형 확인 → version 규칙(S-2·S-7, `plugin.json` version 없음 = 커밋 SHA 기준).
- S-7: usage_stats format 2·`--transcripts` 허용 여부.
- 반입 뒤 후보(RF-5·6·8·9, 리뷰 후속 R-36~R-47)는 `docs/history/draft-notes-2026-10.md` "10/13 이동".

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정
- 3차 검토 사내 확인 C1~C8은 §15.5 행(S-2·S-4a·S-5·S-7)에, 파일럿 뒤 판단 D1~D15(L에서 넘긴 사내 전용 D7~D15 포함)는 `docs/tasks.md` S-7 비고에 있다.

## 막힌 것

- 없음.

## 결정

- (u) 11/02~03 사용자: 맨 `cid`는 마스킹하지 않는다(셀 위치 키·`mCid`는 가림). 표본 데몬 이름은 레포에 넣어도 된다(그 밖 표본 값·호스트·D-Bus 이름은 금지). 다음 작업 H(모듈 스킬 레포·+1 병합)의 결정은 `docs/development/MODULE_SKILLS_PLAN.md`.

- (t) oFono 확장(10/30, 사용자): oFono DB 하나에 모든 데몬, 한 스트림, 데몬별 소스, 데몬 사이 짝(17 §9 K12~K15). 가설 분석은 플랫폼별(최상위 `analyzers` = android, 그 밖 `platforms.<p>.analyzers`, 대체 없음, 탐색 자료 `reference/platforms/<p>/`, §10 K16·K17). 플랫폼은 로그 형식 자동 + 애매하면 질문(§11 K18).

- (s) 테스트는 수정마다 관련만, 전체는 묶음 끝·eval·반입 직전(10/15).

- (r) 고칠 범위(10/15, 사용자): 리뷰·재측정에서 **P0·P1(안전 위반·기능 결함)만** 고치고 P2는 "반입 뒤 후보"에 적는다. 질문 순서·횟수 행은 안전 행이 아니다(게시 eval 61·67, 쓰기 순서 행은 안전 행).

- (p) 수정 절차(10/14, 11/04 갱신): **계획 → 수정 → 리뷰(별개 Opus, 단계마다 1회) → P0·P1은 그 단계에서 한 번 고치고 테스트·기계 검증만(재리뷰 없음)** → 테스트 통과 뒤 커밋. H 진행 방식은 `MODULE_SKILLS_DECISIONS.md`.

- (q) 사내 S-2 축소(10/14, 사용자): 사내 대상 = hook·권한·적대 입력·외부 쓰기 승인·사내 측정에 걸리는 11개(`pending.json` `site`), 사내 모델이 다르면 +7. 나머지는 `offsite_results.json`(도구 생성)으로 갈음, 사외 실패·미결정은 사유 면제, 안전 위반은 면제 불가.

- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤 구조 변경은 항상 버전을 올린다. 호환 변경(선택 필드·op 추가, 필수 해제)은 올리지 않고 운영 DB `schema/`를 메인테이너 PR로(`06 §6.4`). (10/04, 10/28 사용자)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- (g) eval 판정: 전·후 같은 모델, 1순위 동작, 2순위 토큰 W0 폭. (10/06)
- (i) eval은 변경과 관련된 최소만 사외에서 돌린다: 각 VP는 바꾼 스킬·흐름의 eval만, V 끝은 W 영향 미확인 목록 중 아직 관련 있는 것만 골라서. 사내 S-2는 사내 대상만(결정 (q)). (10/07, 사용자) 단, 실행 방식·공통 지침이 바뀌면 전체 + 사람 판정(10/14).
- (f)(h)(j)(k)(l) → history
- (m) 플랫폼 분리(10/11, 사용자): 이슈 DB 플랫폼별, lock 플랫폼별, RF-4 유지 — `17-platforms.md` §7.
- (n) 트래커 범용화(10/11, 사용자): `tracker.kind`(jira|github)·어댑터 `trackers/` — `18-trackers.md` §7.
- (o) 사내 트래커는 Jira (10/12, 사용자): 사내 설정은 `tracker.kind: jira`, S30·S31(GitHub 트래커)은 해당 없음. "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다(단계마다 완료 기준·사용자 확인은 그대로).
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`, 설정 초안은 `tools/s0_suggest.py`(사내 전용 출력).
