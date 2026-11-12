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

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강·H 완료. 사내 마지막 반입 **import-20261103**. 태그 `import-20261109`·`b`는 반입되지 않았다.
- 다음 묶음 **import-20261113**(태그·반입은 사용자, 사내 §8). 11/13 종합 리뷰: 반입해 사내 보완을 이어 가도 된다(P0 0).
- 모델 Sonnet 5.5 기준. `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서(`docs/book/`)는 스냅샷, 정본은 `docs/TEAM_GUIDE.md`.

## 남은 일 (사외 전용)

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ F | 다음 묶음 — 사람 확인·태그·반입은 사용자. 반입 뒤 후보: 탐색 `--also`, 심층 분석 단계, Jira 버전 문구 패턴(`99-deferred.md` H·I·G) | SITE_INSTALL §8·아래 재반입 노트 |
| ☐ G | 범용판 별도 레포 — **보류(10/07 사용자)** | 재개는 사용자가 정한다 |
| ☐ I | OpenCode·사내 모델판 — 사외 몫 ☑(사내 확인 남음) | `docs/RUNTIME_ADOPTION.md` |

다음 사이클 후보(11/09 사용자 목록, 확정 계획 아님)와 11/13 리뷰 뒤 미룬 것은 history 11/13.

## 사내로 넘긴 것

- **재반입 노트 (import-20261113 = import-20261103 이후 전부)**
  - guard 판정이 바뀌었다(4-c) — 반입 전 `s4a.protection_guard` 통과 전제. §8대로 사내 대상 eval 12개 모두 다시.
  - S1 확인 전인데 site-defaults `tracker.isolation_confirmed: true`면 `false`로.
  - S13을 했어도 `14-site.md` S13의 새 확인 방법으로 다시. 확인 전에는 사내 로그를 fixture·이슈 DB에 넣지 않는다.
  - S-5 `offline_eval`은 이슈 DB에 이미 있는 키도 표본내로 뺀다.
  - 옛 판으로 `summary`까지 한 대기 작업은 PR 본문에 메모 원문이 남는다 → `summary` 다시 또는 `discard`.
  - `issue_db.path`가 이슈 DB clone이 아니면 `db_pr`·`db_verify`가 git 전에 종료 2. `dbpr/worktree.py`·`db_verify.py`·`db_summary.py`는 §8의 기록 부분이 아니다.
  - 사내 읽기 증가: S-1 +397B, S-5 약 +300B.
- 사내 대상 eval 12개(`pending.json` `site`, S-2; 사내 모델이 다르면 +7 — 반입마다 `MODULE_SKILLS_RESULT.md` "반입 노트" 표로 영향 받는 것만), T4 Read line 힌트(S-2)·offline_eval 오류율 상한(S-5)·`max_tokens_hint`(S-4a)·U1 setup Jira 없음 중단(S-3)·db-authoring 요약 확장(S-2)·마켓플레이스 소스 유형 → version 규칙(S-2·S-7).
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
- (s) 테스트는 수정마다 관련만, 전체는 묶음 끝·eval·반입 직전(10/15).
- (r) 고칠 범위(10/15, 사용자): 리뷰·재측정에서 **P0·P1(안전 위반·기능 결함)만** 고치고 P2는 "반입 뒤 후보"에 적는다. 질문 순서·횟수 행은 안전 행이 아니다(쓰기 순서 행은 안전 행).
- (p) 수정 절차(10/14, 11/08): 재확인·설계 = Fable 메인, 구현+시험 = Opus, 리뷰 = 별개 Opus → P0·P1은 그 단계에서 고치고 테스트 → 통과 뒤 커밋.
- (q) 사내 S-2 축소(10/14, 사용자): 사내 대상 = `pending.json` `site`(사내 모델이 다르면 +7). 나머지는 `offsite_results.json`으로 갈음, 안전 위반은 면제 불가.
- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤 구조 변경은 버전을 올린다. 호환 변경은 올리지 않는다(`06 §6.4`). (10/04, 10/28)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형에 흔적 시그니처가 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04)
- (g) eval 판정: 전·후 같은 모델, 1순위 동작, 2순위 토큰 W0 폭. (10/06)
- (i) eval은 변경과 관련된 최소만 사외에서 돌린다(바꾼 스킬·흐름의 eval만). 사내 S-2는 사내 대상만(결정 (q)). (10/07, 사용자) 단, 실행 방식·공통 지침이 바뀌면 전체 + 사람 판정(10/14).
- (f)(h)(j)(k)(l)(m)(n)(t) → history((t) `17-platforms.md` §9~11, (m) §7, (n) `18-trackers.md` §7)
- (o) 사내 트래커는 Jira(10/12, 사용자). "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다.
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`, 설정 초안은 `tools/s0_suggest.py`(사내 전용 출력).
