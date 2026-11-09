# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·남은 일·막힌 것·결정만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 지난 이력은 `docs/history/draft-notes-2026-*.md`와 `docs/history/CHANGES.md`. 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (사외 전용)

- **사내(`SITE_PROFILE.md` 있음)에서는 이 절을 무시한다** — 사내 시작은 `CLAUDE.md` 머리말과 `context_pack.py S-n`.
- 최신 main에서 시작하고 remote를 fetch한다(이름은 PC마다 `telephony` 또는 `origin`).
- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 진행해"** 로 하면 모드를 묻지 않는다(`touch .local-draft`).
- 의존성: `pip install '.[test]'`(고정 버전).
- Windows: `PYTHONUTF8=1`·stdin `/dev/null`·LF·`python3` shim(환경 실패 4건은 CI 통과). 판정용 전체 pytest는 WSL.
- 테스트는 `tools/related_tests.py --run`(관련만). 전체는 도구가 full이라 할 때·반입 직전·요청 시.
- 진행 중 판단은 Fable 결정 에이전트에게(10/06 사용자). 사용자 승인 대상(이슈 DB push, main 병합·태그 등 지시 없는 외부 동작)은 사용자에게.

## 진행 상태 (11/09)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강·H 완료. 지난 묶음 **import-20261103**(main `77e2827`).
- **코덱스 종합 리뷰 반영 완료**(`58ae770`·`1554dc0`, GRADER_VERSION 5). WSL 전체 pytest 통과, hook_probes 176개 판정 동일. 상세는 `docs/history/draft-notes-2026-11.md`.
- 다음 묶음 **import-20261109**(태그·반입은 사용자). 사내: 재반입 §8. 이번 묶음은 guard 판정이 바뀌었다(4-c 병합 계열·규칙 5 ask 전환, Approve·기각·자동 병합·보호 변경·refs 위조 deny 신설) — 반입 전 `s4a.protection_guard` 통과 전제. SITE_INSTALL §8대로 사내 대상 eval 12개(`pending.json` `site`) 전부 다시 돌린다.
- 11/09 표본 제거 PR-1(출처 메타·흔적 문구 제거, journal 상수 → components 설정 키, make_bundle deny-file, boundary trace-wording) 진행 — PR-2(합성 대역 로그·슬롯·복구 도구) 남음, 반입은 `stable` 브랜치에서.
- 모델 Sonnet 5.5 기준. `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서: `docs/book/telephony-triage-book.html`

## 남은 일 (사외 전용)

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ F | 묶음 import-20261109 — 사람 확인·태그·반입은 사용자 | SITE_INSTALL §8·반입 노트(`MODULE_SKILLS_RESULT.md`) |
| ☐ G | 범용판 별도 레포 — **보류(10/07 사용자)** | 재개는 사용자가 정한다 |
| ☐ I | OpenCode·사내 모델판 — 사외 몫 ☑(사내 확인 남음) | `docs/RUNTIME_ADOPTION.md` |

## 다음 사이클 후보 (11/09 사용자 목록, 확정 계획 아님)

C 지표 자리 · 4-c 2차(guard 판정 축소 후속) · B 조건부 · F3 B/C(`mask_pii --check` 갈린 ICCID) · 4-c P2 6건 · D① P2 · 묶기·전구간 부정(S37 뒤 별도 설계) · 분석 전용 종료 표식 · 포트 변조 P3(ok로 통과 — `=` 값 뒤 `:숫자` 포트 꼴 미포함) · `tracker.read_tools` dict일 때 관문 지문 미반영(손편집만).

## 사내로 넘긴 것

- 사내 대상 eval 12개(`pending.json` `site`, S-2; 사내 모델이 다르면 +7 — 반입마다 `MODULE_SKILLS_RESULT.md` "반입 노트" 표로 영향 받는 것만, 11/05 결정), T4 Read line 힌트(S-2)·offline_eval 오류율 상한(S-5)·`max_tokens_hint`(S-4a)·U1 setup Jira 없음 중단(S-3)·db-authoring 요약 확장(S-2)·마켓플레이스 소스 유형 → version 규칙(S-2·S-7).
- S-7: usage_stats format 2·`--transcripts` 허용 여부. S37 결과·팀 설치본 통일 뒤에만 `signature_features`를 DB에 선언(결정 (v)).
- 반입 뒤 후보(RF-5·6·8·9, R-36~R-47)는 `docs/history/draft-notes-2026-10.md` "10/13 이동".

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 목록(로그 문구·태그 S9, Jira 필드 S20·S22, report.html 표, `step_events`·시계, offline_eval S-5, C1~C8·D1~D15 위치)은 `docs/history/draft-notes-2026-11.md` "11/09 이동".

## 막힌 것

- 없음.

## 결정

- (v) 11/09 사용자(코덱스 02e0ec2): **F01 보강** — DB가 쓰는 시그니처 feature는 `issue-db.config.yaml signature_features`에 선언, 플러그인이 모르는 feature면 **분석 중단**(읽기 전용 아님, `feature-unsupported`); 새 필드는 S37 결과·팀 설치본 통일 뒤에만. **Q01 채택 관문** — 가설 줄 `[근거 불일치 N]`, fabricated 인용이 든 가설은 시그니처 초안에 쓰지 않고 사용자가 재확인한 인용만(종료 0 유지). 채점 판정(S 행 어느 것이든)이 바뀌면 GRADER_VERSION을 올린다.
- (u) 11/02~03 사용자: 맨 `cid`는 마스킹하지 않는다(셀 위치 키·`mCid`는 가림). 표본 데몬 이름은 레포에 넣어도 된다(그 밖 표본 값·호스트·D-Bus 이름은 금지).
- (t) oFono 확장(10/30, 사용자): `17-platforms.md` §9~11. 원문은 `docs/history/draft-notes-2026-11.md`.
- (s) 테스트는 수정마다 관련만, 전체는 묶음 끝·eval·반입 직전(10/15).
- (r) 고칠 범위(10/15, 사용자): 리뷰·재측정에서 **P0·P1(안전 위반·기능 결함)만** 고치고 P2는 "반입 뒤 후보"에 적는다. 질문 순서·횟수 행은 안전 행이 아니다(쓰기 순서 행은 안전 행).
- (p) 수정 절차(10/14, 11/08 역할): **재확인·설계 = Fable 메인, 구현+시험 = Opus, 리뷰 = 별개 Opus(설계자 아님) → P0·P1은 그 단계에서 고치고 테스트·기계 검증** → 통과 뒤 커밋. H 진행 방식은 `MODULE_SKILLS_DECISIONS.md`.
- (q) 사내 S-2 축소(10/14, 사용자): 사내 대상 = `pending.json` `site` 11개(hook·권한·적대 입력·외부 쓰기·사내 측정), 사내 모델이 다르면 +7. 나머지는 `offsite_results.json`(도구 생성)으로 갈음, 사외 실패·미결정은 사유 면제, 안전 위반은 면제 불가.
- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤 구조 변경은 항상 버전을 올린다. 호환 변경은 올리지 않고 운영 DB `schema/`를 메인테이너 PR로(`06 §6.4`). (10/04, 10/28 사용자)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- (g) eval 판정: 전·후 같은 모델, 1순위 동작, 2순위 토큰 W0 폭. (10/06)
- (i) eval은 변경과 관련된 최소만 사외에서 돌린다(바꾼 스킬·흐름의 eval만). 사내 S-2는 사내 대상만(결정 (q)). (10/07, 사용자) 단, 실행 방식·공통 지침이 바뀌면 전체 + 사람 판정(10/14).
- (f)(h)(j)(k)(l) → history
- (m) 플랫폼 분리(10/11, 사용자): 이슈 DB 플랫폼별, lock 플랫폼별, RF-4 유지 — `17-platforms.md` §7.
- (n) 트래커 범용화(10/11, 사용자): `tracker.kind`(jira|github)·어댑터 `trackers/` — `18-trackers.md` §7.
- (o) 사내 트래커는 Jira (10/12, 사용자): 사내 설정은 `tracker.kind: jira`, S30·S31(GitHub 트래커)은 해당 없음. "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다(완료 기준·사용자 확인은 그대로).
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`, 설정 초안은 `tools/s0_suggest.py`(사내 전용 출력).
