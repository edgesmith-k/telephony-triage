# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안의 진행 상태·남은 일·막힌 것·결정만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 지난 이력은 `docs/history/draft-notes-2026-*.md`와 `docs/history/CHANGES.md`. 필요한 절만 읽는다.
> 이 파일은 반입 때 사내로 가고 `.local-draft`는 안 간다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (사외 전용)

- **사내(`SITE_PROFILE.md` 있음)에서는 이 절을 무시한다** — 사내 시작은 `CLAUDE.md` 머리말·`context_pack.py S-n`.
- 최신 main에서 시작하고 remote를 fetch한다(이름은 PC마다 `telephony`·`origin`).
- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 진행해"** 로 하면 모드를 묻지 않는다(`touch .local-draft`).
- 의존성: `pip install '.[test]'`(고정 버전).
- Windows: `PYTHONUTF8=1`·stdin `/dev/null`·LF·`python3` shim(환경 실패 4건은 CI 통과). 판정용 전체 pytest는 WSL.
- 테스트는 `tools/related_tests.py --run`(관련만). 전체는 도구가 full이라 할 때·반입 직전·요청 시.
- 진행 중 판단은 Fable 결정 에이전트에게(10/06 사용자). 사용자 승인 대상(이슈 DB push, main 병합·태그 등 지시 없는 외부 동작)은 사용자에게.

## 진행 상태 (11/27)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강·H 완료. 사내 마지막 반입 **import-20261117**(`46eadb4c`, 11/17). 그 뒤 묶음(1119·1123·1125 계열)은 반입 레포에만 있고, 사내는 **import-20261126을 새 계정에서 처음부터 설치**한다(11/27 예정).
- 이번 묶음(1126): 조사 결론 검사 보강(인용이 가리키는 사본 줄 시각, `찾았는데 없음`의 관측 시간, 첫 어긋남 관측 순서), 조사 모드에서 5-1 건너뜀(`run --analyzer`로 되돌림), 본 타임라인·모듈 보기 중심, 근거 인용 태그 기록(`usage_stats.py --tags`), OpenCode 설치가 permission을 에이전트 파일에도 적음.
- 모델 Sonnet 5.5 기준. `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서(`docs/book/`)는 스냅샷, 정본은 `docs/TEAM_GUIDE.md`.

## 남은 일 (사외 전용)

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ F | 다음 묶음 — 사람 확인·태그·반입은 사용자. 반입 뒤 후보: 다중 모듈 탐색, Jira 버전 문구 패턴(`99-deferred.md` H·G) | SITE_INSTALL §8·아래 재반입 노트 |
| ☐ G | 범용판 별도 레포 — **보류(10/07 사용자)** | 재개는 사용자가 정한다 |
| ☐ I | OpenCode·사내 모델판 — 사외 몫 ☑(사내 확인 남음) | `docs/RUNTIME_ADOPTION.md` |

다음 사이클 후보(11/09 사용자 목록, 확정 계획 아님)와 11/13 리뷰 뒤 미룬 것은 history 11/13.

## 사내로 넘긴 것

- **재반입 노트 (import-20261126 = 사내 마지막 반입 import-20261117 `46eadb4c` 이후 전부)**. 옛 노트(11/19)는 이 파일의 git 이력.
  - OpenCode: 반입 뒤 `gen_opencode.py install --force`(설치 permission을 에이전트 파일에 적는다 — 안 하면 `tt-oc doctor`의 `agent-permission`이 fail). 관리 설정(`/etc/opencode`)을 바꾸면 사용자마다 다시 설치. 전역 설정에 `"*": "allow"`를 넣는 조치는 필요 없다.
  - hook·guard·공통 규칙이 바뀜 → §8 규칙대로 **사내 eval 12개 전부**(`pending.json` `site`). 사외는 바뀐 흐름의 eval 20개를 다시 돌렸다(`offsite_results.json`의 note).
  - 진행 중이던 작업: `module --for explore`가 "timeline.md가 맞지 않는다"로 멈추면 `explore`를 다시(타임라인 줄 고르는 기준이 바뀜). 옛 window 구간 파일은 조사 결론 검사에서 세지 않는다 — `window`를 다시 받는다.
  - 조사 모드(1위 C=0·후보 없음)에서 5-1 출처가 모듈 문서면 5-1을 건너뛰고 5-2가 모듈 문서를 읽는다(`explore` 출력 `next`). 5-1도 하려면 `run --analyzer`. 사내 모듈 문서로 있음/없음을 한 번 비교한다. **포털 release와 같이 설치**(포털이 pin 때 이 인자를 아는지 읽는다).
  - 사내에서 볼 값(경험값): `찾았는데 없음` 10초, 첫 어긋남 관측이 앞 단계보다 1시간 넘게 앞서면 실패(`OBS_BEFORE_MAX`), 마스킹 사본을 grep 없이 통째로 읽는지, 근거 인용 태그 표(`usage_stats.py --tags`)로 tags.yaml에 더할 태그.
  - 수정 검증 작업 키에 빌드의 `+`를 받는다(`JOB_KEY_RE`) — 브랜치 이름에 `+`가 든 GHE 요청은 사외 미확인.
- 재실행할 eval 수는 재반입 노트가 정한다(`pending.json` `site`, S-2; 사내 모델이 다르면 +7). 단계별 확인 항목·반입 뒤 후보(RF·R-36~47)는 history 11/13. S-7: usage_stats format 2·`--transcripts` 허용 여부. 시그니처 필드 선언은 결정 (v)대로.
- 사내 IMS는 별도 APK(11/12): IMS 줄·규칙·문서는 AOSP 기준·소스만 — S-1에서 먼저.

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 목록(로그 문구·태그 S9, Jira 필드 S20·S22, report.html 표, `step_events`·시계, offline_eval S-5, C1~C8·D1~D15 위치)은 `docs/history/draft-notes-2026-11.md` "11/09 이동".

## 막힌 것

- 없음.

## 결정

- (w) 11/13 사용자: 첫 파일럿은 Android만. guard는 실수 방지 장치(Approve는 토큰 권한으로 닫음). 사내 마켓플레이스는 태그·SHA 고정. 전체는 history 11/13.
- (v) 11/09 사용자: DB가 쓰는 시그니처 feature는 `issue-db.config.yaml signature_features`에 선언하고, 플러그인이 모르는 feature면 분석 중단(`feature-unsupported`). 새 시그니처 필드는 S37·팀 설치본 통일 뒤에만(`mask-off` 제외). fabricated 인용이 든 가설은 시그니처 초안에 쓰지 않는다. 채점 판정이 바뀌면 GRADER_VERSION을 올린다.
- (q) 사내 S-2 축소(10/14, 사용자): 사내 대상 = `pending.json` `site`(사내 모델이 다르면 +7). 나머지는 `offsite_results.json`으로 갈음, 안전 위반은 면제 불가.
- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤 구조 변경은 버전을 올린다. 호환 변경은 올리지 않는다(`06 §6.4`). (10/04, 10/28)
- (g) eval 판정: 전·후 같은 모델, 1순위 동작, 2순위 토큰 W0 폭. (10/06)
- (b)(e)(f)(h)(i)(j)(k)(l)(m)(n)(p)(r)(s)(t)(u) → history((b)(e)(i)(p)(r)(s) 11/13, (u) 11/15, (t) `17-platforms.md` §9~11, (m) §7, (n) `18-trackers.md` §7)
- (o) 사내 트래커는 Jira(10/12, 사용자). "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다.
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`, 설정 초안은 `tools/s0_suggest.py`(사내 전용 출력).
