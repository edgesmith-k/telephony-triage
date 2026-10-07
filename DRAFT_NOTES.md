# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·남은 일·막힌 것·결정만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 지난 이력은 `docs/history/draft-notes-2026-09.md`(10/07 정리 전 전문 포함)와 `docs/history/CHANGES.md`. 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작

- **사내(`SITE_PROFILE.md` 있음)에서는 이 절을 무시한다** — 사내 시작은 `CLAUDE.md` 머리말과 `context_pack.py S-n`.
- 최신 main에서 시작하고 remote를 fetch한다(이름은 PC마다 `telephony` 또는 `origin`).
- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 진행해"** 로 하면 모드를 묻지 않는다(`touch .local-draft`).
- 의존성: `pip install '.[test]'`(고정 버전, 다르면 `test_r10_dependency_manifest_has_complete_pins`만 실패).
- Windows: `PYTHONUTF8=1`, stdin `/dev/null`, PATH 앞에 실제 Python과 `python3` shim, 파일은 LF(`test_repo_text_files_use_lf`). Windows에서만 실패하는 환경 테스트 4건(gh 토큰·파일명 `:`·zip 모드·백슬래시 경로)은 CI(Ubuntu)에서 통과한다.
- 테스트는 `tools/related_tests.py --run`(관련만). 전체는 도구가 full이라 할 때·반입 직전·요청 시.
- 진행 중 판단은 Fable 결정 에이전트에게 묻는다(10/06 사용자 지정). 원칙상 사용자 승인 대상(이슈 DB push, main 병합·태그 등 사용자가 지시하지 않은 외부 동작)은 사용자에게.

## 진행 상태 (10/07)

- 모드: **사외 초안**. Phase **D0, 1~13** 완료. 반입 전 보강 트랙(S1~S6·I1~I5·X·3C~3F)과 개선 트랙 **W0~W12**, 반입 전 리뷰(10/07) 수정 트랙 **V1~V7·V 끝** 완료, main 병합(PR #8·#9·#11~#19).
- 마지막 전체 테스트: 1045 통과(Windows, 환경 실패 4), `db_regress --all` 20/20, CI Ubuntu Py3.11·3.14 통과 (10/07, V 끝).
- 사내 확인 항목: `TODO(SITE)` **73곳** — `python3 tools/list_site_todos.py`. `REVIEW-OPEN.md` 0건.
- 사내 S 단계 시작: `python3 tools/context_pack.py S-n`(표 `docs/tasks.md`).
- 안내서(사람용 HTML): `docs/telephony-triage-guide.html` (공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG)

## 남은 일

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ L | **실제 로그 반영 트랙 L1~L3** (10/07 사용자 승인: 샘플 DB 규칙·fixture 정정, 스냅샷 재생성, data on/off·APM 원인·유형 추가) | 자료는 **레포 밖** `%LOCALAPPDATA%/tt-ltrack/`(findings·plan·decisions·r-results·deny.txt — 벤더 문구 있음, 레포 금지). R1~R4 완료. 다음: L1 AOSP 형식 정정(DSMGR·DSM-C/I, DNC 문구, APM 유형 DATA-002) → L3 `tools/s0_suggest.py` → L2 벤더 RIL serial 연결(token=serial 100% 확인). 커밋 전마다 `git diff main... \| grep -iFf deny.txt` 0줄. 사용자 확인 대기: DATA-002 이름·정의, 새 extractor 2건, 14-site §14.1 정정 |
| ☐ Z | **반입 묶음** | 최신 main에서 **Ubuntu로** 먼저 `plugin.json` description에서 "사외 초안"을 빼는 커밋(도구가 첫 검사로 막는다) → `python3 tools/make_bundle.py --label <이름>`(정상 종료 3) → 사람 확인 3건(§15.4: 회사명 검색·TODO 목록·이 파일 최신) → 도구가 출력한 명령으로 사용자가 태그 push. Windows는 환경 실패로 자동 검사가 실패한다 |
| ☐ R | **사용자 선택** — `12-principles.md` "사용자 clone 예외는 migrate뿐" vs renumber(06 §6.3) 어긋남: (a) 예외에 renumber 추가(추천) / (a') 원칙을 도구 자동 쓰기로 한정 / (b) 06 안내 수정. 코드 변경 없음(V6이 renumber에 브랜치·깨끗함 검사 추가) | 반입 직전 |
| ☐ 2 | **사용자 확인** — 10/04~05 작업(4a·R8·테스트 DB·검사 통합·4b·step_order·보안·R11·R9·RF-2, `CHANGES.md` 10/04~05 절) | 반입 직전에 한꺼번에 |

반입 뒤 후보: RF-5(oFono)·RF-6(커넥터)·RF-8(자동화)은 사내 환경을 알아야 의미가 있다. RF-9·웹 UI(보류)는 그 뒤. 10/07 리뷰의 R-36~R-47·V 후속도 같은 색인 `docs/development/ARCHITECTURE_REVIEW_2026-10.md`.
사내로 넘긴 것: 행동 eval 전체(`evals.json`, S-2), db-authoring 스키마 요약 확장(S-2, 스키마 Read 횟수로 판단), 운영 DB 스키마 `pr.ids` 반영(S-3, 뼈대에서), 사내 마켓플레이스 소스 유형 확인 → version 규칙(S-2·S-7, V2에서 `plugin.json` version 삭제 = 커밋 SHA 기준. 반입 직후 캐시 1회 무효화는 무해).

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정

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
- (h) W11 보류 3건(위임 결정, 10/07): 파생 이벤트 `msg` 복사 제거 폐기, Windows 보정 유지, db-authoring 스키마 요약은 사내 S-2.
- (i) eval은 변경과 관련된 최소만 사외에서 돌린다: 각 VP는 바꾼 스킬·흐름의 eval만, V 끝은 W 영향 미확인 목록 중 아직 관련 있는 것만 골라서. 전체 재실행은 사내 S-2. (10/07, 사용자)
- (j) 매칭 컴파일 캐시(`.cache/compiled.json`)를 삭제한다: 240유형·3.5k Jira에서 DB 로드(0.69~1.09s)에 캐시 hit 판정(+0.35~0.67s)이 더해질 뿐 컴파일은 1ms, 해시가 플러그인 코드를 보지 않아 판정을 캐시 파일에 좌우시켰다. `source_hash`(분석 재사용)·`.cache/` 커밋 차단은 유지. (10/07, 위임 결정, V7)
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`.
