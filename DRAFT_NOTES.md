# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·남은 일·막힌 것·결정만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 지난 이력은 `docs/history/draft-notes-2026-09.md`(10/07 정리 전 전문 포함)와 `docs/history/CHANGES.md`. 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (사외 전용)

- **사내(`SITE_PROFILE.md` 있음)에서는 이 절을 무시한다** — 사내 시작은 `CLAUDE.md` 머리말과 `context_pack.py S-n`.
- 최신 main에서 시작하고 remote를 fetch한다(이름은 PC마다 `telephony` 또는 `origin`).
- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 진행해"** 로 하면 모드를 묻지 않는다(`touch .local-draft`).
- 의존성: `pip install '.[test]'`(고정 버전).
- Windows: `PYTHONUTF8=1`·stdin `/dev/null`·LF·`python3` shim. 환경 실패 4건은 CI(Ubuntu)에서 통과.
- 테스트는 `tools/related_tests.py --run`(관련만). 전체는 도구가 full이라 할 때·반입 직전·요청 시.
- 진행 중 판단은 Fable 결정 에이전트에게 묻는다(10/06 사용자 지정). 원칙상 사용자 승인 대상(이슈 DB push, main 병합·태그 등 사용자가 지시하지 않은 외부 동작)은 사용자에게.

## 진행 상태 (10/13)

- 모드: **사외 초안**. Phase **D0, 1~13** 완료. 반입 전 보강 트랙(S1~S6·I1~I5·X·3C~3F)과 개선 트랙 **W0~W12**, 반입 전 리뷰(10/07) 수정 트랙 **V1~V7·V 끝**, 실제 로그 반영 트랙 **L1~L3** 완료, 반입 전 3차 검토(A1~A4·B1·B2·문서) 반영(10/08), 설명 정리(PR #31). main 병합 PR #8~#41.
- 10/11~12: Jira 결과 게시(#37), 플랫폼 분리(m), 트래커 범용화(n·o), 사내 단계 자동화 등 — 줄별 요약은 `docs/history/draft-notes-2026-10.md` "10/13 이동". 미실행 eval `tests/skill_evals/pending.json`(S-2).
- 10/13: **반입 완료** import-20261013(d6d5996)·재반입본 import-20261013b(2b08a7b, 태그 둘 다). 사내 실측으로 고친 것: 사내 설치 가이드 `docs/SITE_INSTALL.md`(#43), eval 실행기 `apiKeyHelper` 인증 전달(#43), Python 3.11.0rc1(Ubuntu 22.04 apt) tar filter 폴백(#44). 3.11.1 전체 1,751 통과. **Python 3.10 지원**(10/13, 결정 P): `requires-python >=3.10`, CI 3.10 추가, 가이드 A(`--user`)/B(venv) — 3.10 전체 1,751 통과(환경 3건은 venv PATH 조건). 반입본 import-20261013c(0365a98). 사내 S-2 실측 수정(10/14, T): eval 자식 `--permission-mode default`, e38 해결책 끝 마침표 무시, 사외 전용 검사 2건 사내 레포 skip. 반입본 import-20261014(2d544dc). 재반입 절차 `SITE_INSTALL.md` 8절(R). CRLF 검사는 git 커밋 대상만(사내 레포 안 `.venv`로 실패, 10/14). 사내 리허설(`tools/site_rehearsal.sh`, CI `site-rehearsal`: Ubuntu 22.04·일반 사용자·한국어 로케일, 설치 3방식) 추가 — 찾은 것: `--user` 설치+HOME 변경, venv 미활성 hook.
- 사내 확인 항목: `TODO(SITE)` **104곳** — `python3 tools/list_site_todos.py`. `REVIEW-OPEN.md` 0건.
- 사내 시작: **"사내 설정 시작"** → `python3 tools/site_step.py`가 `SITE_PROFILE.md`(트래커 jira)를 만들고 S-1~S-7을 한 단계씩 낸다(결정 (o)).
- 안내서(사람용 HTML): `docs/telephony-triage-guide.html` (공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG). 역할별 문서 19개: `docs/materials/00-index.html`

## 남은 일 (사외 전용)

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ G | **범용판 별도 레포** (10/07 사용자 지시) — **보류(10/07 사용자)** | 재개 시점은 사용자가 정한다. **로컬 새 레포**(원격 없음), 범위 = 도메인 중립 코어 + 최소 예제 팩 1개. 시작은 결합 지점 조사(`plugin/scripts` 약 30파일) → 분리 설계 확인 → 이전. 이 레포는 바꾸지 않는다 |

## 사내로 넘긴 것

- 행동 eval 전체(`evals.json`, S-2; 주입 eval 59·60 포함), 코드 Read line 힌트(T4, S-2 측정 뒤)·offline_eval 오류율 상한(S-1 합의, S-5)·`max_tokens_hint` 처리(S-4a)·setup Jira 없음 중단(U1, S-3), db-authoring 스키마 요약 확장(S-2, 스키마 Read 횟수로 판단), 사내 마켓플레이스 소스 유형 확인 → version 규칙(S-2·S-7, V2에서 `plugin.json` version 삭제 = 커밋 SHA 기준. 반입 직후 캐시 1회 무효화는 무해).
- 반입 뒤 후보(RF-5·6·8·9, 리뷰 후속 R-36~R-47)는 `docs/history/draft-notes-2026-10.md` "10/13 이동".

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정
- 3차 검토 사내 확인 C1~C8은 §15.5 행(S-2·S-4a·S-5·S-7)에, 파일럿 뒤 판단 D1~D6은 `docs/tasks.md` S-7 비고에 있다.

## 막힌 것

- 없음.

## 결정

- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤에는 항상 버전을 올린다(`06 §6.4`). (10/04)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- (f) 반입 전 사외에서 최대한 안정화·보완·개선한 뒤 반입한다. 사내 문자열 사람 검색은 생략(사내→사외 반출 불가). (10/05)
- (g) eval 판정 관례: 변경 전·후를 같은 모델로, 1순위 동작·형식 오류 재시도, 2순위 토큰 W0 폭(출력 9.5%·비용 15.7%), 폭 밖이면 trace(호출 수)로 원인 확인. (10/06)
- (h)·(j) W11 보류 3건(10/07)·매칭 컴파일 캐시 삭제(측정 근거) → `docs/history/draft-notes-2026-10.md`
- (i) eval은 변경과 관련된 최소만 사외에서 돌린다: 각 VP는 바꾼 스킬·흐름의 eval만, V 끝은 W 영향 미확인 목록 중 아직 관련 있는 것만 골라서. 전체 재실행은 사내 S-2. (10/07, 사용자)
- (k) 3차 검토 §8 "하지 않는다" 9건(10/08) → `docs/history/draft-notes-2026-10.md`
- (m) 플랫폼 분리 (10/11, 사용자): 동작·원인·해결책이 달라 이슈 DB를 플랫폼별로(합치기 안 안 씀), 추가는 디렉토리 + `platform.enabled`, lock은 플랫폼별("사용자·이슈 DB(플랫폼)별 한 번에 한 작업"), RF-4 유지. `17-platforms.md` §7.
- (n) 트래커 범용화 (10/11, 사용자): 설정 `tracker.kind`(jira|github)·어댑터 `trackers/`, `issues/`·`platform_version(s)` 개명은 (d)로 v1 직접 수정, 옛 키는 감지만(fail-closed), DB kind 다르면 거부. `18-trackers.md` §7.
- (o) 사내 트래커는 Jira (10/12, 사용자): 사내 설정은 `tracker.kind: jira`, S30·S31(GitHub 트래커)은 해당 없음. "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다(단계마다 완료 기준·사용자 확인은 그대로).
- (l) 4차 검토 결정(회귀 fixture S=0 실패·chose-other 제안만·`suggested` 대조·`gh` 차단 범위) → `docs/history/draft-notes-2026-10.md`
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`, 설정 초안은 `tools/s0_suggest.py`(사내 전용 출력).
