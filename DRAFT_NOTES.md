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

## 진행 상태 (11/13)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강·H 완료. 사내 마지막 반입 **import-20261103**(`77e2827`). 태그 `import-20261109`·`b`는 반입되지 않았다.
- 다음 묶음 **import-20261113**(태그·반입은 사용자, 사내 §8). 11/13 종합 리뷰: 반입해 사내 보완을 이어 가도 된다(P0 0).
- 모델 Sonnet 5.5 기준. `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서(`docs/book/`)는 스냅샷, 정본은 `docs/TEAM_GUIDE.md`.

## 남은 일 (사외 전용)

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ F | 다음 묶음 — 사람 확인·태그·반입은 사용자. 반입 뒤 후보: 탐색 `--also`, 심층 분석 단계, Jira 버전 문구 패턴(`99-deferred.md` H·I·G) | SITE_INSTALL §8·아래 재반입 노트 |
| ☐ M | 반입 전 병합 대기: 백엔드 버전 올림, 이슈 DB `fixed_in`(병합 때 fixed 유지 포함), 모듈 문서 사실 정정 | 병합되면 재반입 노트에 한 줄씩 |
| ☐ G | 범용판 별도 레포 — **보류(10/07 사용자)** | 재개는 사용자가 정한다 |
| ☐ I | OpenCode·사내 모델판 — 사외 몫 ☑(사내 확인 남음) | `docs/RUNTIME_ADOPTION.md` |

다음 사이클 후보(11/09 사용자 목록, 확정 계획 아님)와 11/13 리뷰 뒤 미룬 것은 history 11/13.

## 사내로 넘긴 것

- **재반입 노트 (import-20261113 = import-20261103(`77e2827`) 이후 전부)**
  - guard 판정이 바뀌었다(`08-safety.md §9`): base push·병합 계열(규칙 6·11)과 규칙 5(`ci_mode: actions`)는 거부→ask, Claude의 Approve·리뷰 기각·자동 병합 켜기·보호 변경·`refs/remotes` 위조는 새로 거부. 팀 배포 전에 `site_step.py check S-4a`의 `s4a.protection_guard` 통과. §8대로 사내 대상 eval 12개 모두 다시.
  - S1 확인 전인데 site-defaults `tracker.isolation_confirmed: true`면 `false`로.
  - S13을 했어도 `14-site.md` S13의 새 확인 방법으로 다시. 확인 전에는 사내 로그를 fixture·이슈 DB에 넣지 않는다.
  - S-5 `offline_eval`은 이슈 DB에 이미 있는 키도 표본내로 뺀다.
  - 옛 판으로 `summary`까지 한 대기 작업은 PR 본문에 메모 원문이 남는다 → `summary` 다시 또는 `discard`.
  - `issue_db.path`가 이슈 DB clone이 아니면(빈 값·상대 경로·`issue-db.config.yaml` 없음) `db_pr`·`db_verify`가 git 전에 종료 2. #112·#113의 바뀐 줄은 표시 기록 블록(`render_markdown`·`shown.record`)에 닿지 않는다.
  - `platform.ril.vendor`를 두었으면 벤더 HAL 짝(`hal`)이 바뀔 수 있다 → `db_regress`로 확인(#109).
  - S-0이 `site_step` 첫 단계(#102). 직접 입력한 소스 경로는 개인 `code_profiles`에 자동 저장(#106).
  - 그 밖(#80 모듈 스킬 레포·+1 병합, #85 스냅샷 overlay, #86 Android 17 태그·RIL·슬롯, #87 OpenCode, #90·#95·#98 마스킹): 파일별 영향과 관리자 할 일(`site-defaults.yaml`의 `analyzers.*.inputs`·`max_tokens_hint`·`issue_db.merge` 지우기)은 `MODULE_SKILLS_RESULT.md` "반입 노트"(#80까지).
  - 사내 읽기(import-20261103 대비, KB): S-0 −18.6·S-1 +7.8·S-2 +5.8·S-3 +11.8·S-4 +7.3·S-4a +1.2·S-5 +0.3·S-6 0·S-7 +2.0.
- 재실행할 eval 수는 재반입 노트가 정한다(`pending.json` `site`, S-2; 사내 모델이 다르면 +7). T4 Read line 힌트(S-2)·offline_eval 오류율 상한(S-5)·`max_tokens_hint`(S-4a)·U1 setup Jira 없음 중단(S-3)·db-authoring 요약 확장(S-2)·마켓플레이스 소스 유형 → version 규칙(S-2·S-7).
- S-7: usage_stats format 2·`--transcripts` 허용 여부. S37 결과·팀 설치본 통일 뒤에만 `signature_features`를 DB에 선언(결정 (v)).
- 사내 IMS는 별도 APK(11/12): IMS 줄·규칙·문서는 AOSP 기준·소스만 — S-1에서 먼저.
- 반입 뒤 후보(RF-5·6·8·9, R-36~R-47)는 `docs/history/draft-notes-2026-10.md` "10/13 이동".

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 목록(로그 문구·태그 S9, Jira 필드 S20·S22, report.html 표, `step_events`·시계, offline_eval S-5, C1~C8·D1~D15 위치)은 `docs/history/draft-notes-2026-11.md` "11/09 이동".

## 막힌 것

- 없음.

## 결정

- (w) 11/13 사용자: 첫 파일럿은 Android만. guard는 실수 방지 장치(Approve는 토큰 권한으로 닫음). 사내 마켓플레이스는 태그·SHA 고정. 전체는 history 11/13.
- (v) 11/09 사용자: DB가 쓰는 시그니처 feature는 `issue-db.config.yaml signature_features`에 선언하고, 플러그인이 모르는 feature면 분석 중단(`feature-unsupported`). 새 필드는 S37·팀 설치본 통일 뒤에만. fabricated 인용이 든 가설은 시그니처 초안에 쓰지 않는다. 채점 판정이 바뀌면 GRADER_VERSION을 올린다.
- (u) 11/02~03 사용자: 맨 `cid`는 마스킹하지 않는다(셀 위치 키·`mCid`는 가림). 데몬 이름은 카테고리별 placeholder(11/09 D10).
- (q) 사내 S-2 축소(10/14, 사용자): 사내 대상 = `pending.json` `site`(사내 모델이 다르면 +7). 나머지는 `offsite_results.json`으로 갈음, 안전 위반은 면제 불가.
- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤 구조 변경은 버전을 올린다. 호환 변경은 올리지 않는다(`06 §6.4`). (10/04, 10/28)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형에 흔적 시그니처가 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04)
- (g) eval 판정: 전·후 같은 모델, 1순위 동작, 2순위 토큰 W0 폭. (10/06)
- (f)(h)(i)(j)(k)(l)(m)(n)(p)(r)(s)(t) → history((i)(p)(r)(s) 11/13, (t) `17-platforms.md` §9~11, (m) §7, (n) `18-trackers.md` §7)
- (o) 사내 트래커는 Jira(10/12, 사용자). "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다.
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`, 설정 초안은 `tools/s0_suggest.py`(사내 전용 출력).
