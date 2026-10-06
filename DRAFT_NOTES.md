# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·다음 할 일·막힌 것만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 상세 이력(Phase별 산출물·완료 기준 결과·S1 실험 표·가정·옛 미결 목록)은 **`docs/history/draft-notes-2026-09.md`** 에 있고, 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (다른 PC·클라우드 세션 포함)

- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 다음 단계 진행해"** 로 하면 모드를 묻지 않는다(만들어도 됨: `touch .local-draft`).
- 의존성은 고정 버전으로: `pip install '.[test]'` (데비안 패키지와 충돌하면 `pyproject.toml`의 목록을 `pip install --ignore-installed -r`로). 버전이 다르면 `test_r10_dependency_manifest_has_complete_pins`만 실패한다.
- **"다음 단계 진행"** = 아래 **"반입 전 보강 트랙"**에서 ☐인 첫 항목을 한다(2·10은 트랙 Z 때). "묻는다"가 붙은 항목은 결정을 먼저 묻는다.
- **"개선안 진행"** = `docs/development/IMPROVEMENT_PLAN_2026-10.md` §7의 ☐ 첫 WP를 §8 절차(계획 Opus → 실행 Sonnet/Opus → 리뷰 Opus → 테스트 Haiku, 관련 테스트만)로 한다. 트랙 W는 3F 뒤·Z 앞이다.
- 진행 방식(10/05, 사용자 지정): 계획 Opus(Plan 에이전트) → 구현 Sonnet → 메인이 diff 검토·판단 → `tools/related_tests.py --run`(관련 테스트+경계 검사; 전체는 도구가 full이라 할 때·Z 직전·요청 시만) → 커밋·push. 세션에 지정된 브랜치에 push하고 이 표를 갱신한다. 10/05 작업(S2b~S4·결정 포함)은 모두 main에 병합됐다. 새 세션은 최신 main에서 시작한다. 순서: S5→I1~I5→X→3C→3D→S6→3E→3F→W→Z.

## 진행 상태

- 모드: **사외 초안**. 완료 Phase: **D0, 1~13**. RF-0·RF-1 완료.
- 마지막 전체 테스트: **738개 통과** (10/06, 3F, Ubuntu·Py3.11, 8분). Windows에서는 도구 셸 stdin을 `/dev/null`로, PATH 앞에 실제 Python과 `python3` shim(Store 별칭이면 gh 스텁·git hook이 9009로 실패).
- 사내 확인 항목: `TODO(SITE)` **73곳**(S22 12곳 추가) — `python3 tools/list_site_todos.py`. `REVIEW-OPEN.md` 0건.
- 안내서(사람용 HTML): `docs/telephony-triage-guide.html` (공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG)

10/04 결과(4a·R8·테스트 DB·검사 통합·4b·step_order·보안·R11·R9·RF-2)는 `docs/history/CHANGES.md` 10/04 절 — 사용자 확인 대기(☐2).

## 다음 할 일

10/04~05 지시 순서(5→6→8→9→10→7→3→2) 중 **1·3~9 완료**(상세 `docs/history/CHANGES.md` 10/04~05 절). 남은 것:

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ 2 | **사용자 확인** — 위 표, RF-2, 10/05 작업 전체 | 반입 직전에 한꺼번에 |
| ✅ 3C | 행동 eval — 사외 실행 완료 → 보강 트랙 3C·3D·3E | 사내 S-2에서 54개 다시 |
| ◐ 10 | **반입** | main `7b69cb5` 묶음은 낡음 → 아래 보강 뒤 다시 만든다. 태그 push는 사용자(세션 권한 밖) |

**반입 전 보강 트랙**(사용자 결정 10/05: 시간 여유, 사외에서 최대한 안정화·보완 뒤 반입). 위에서부터 ☐ 첫 항목을 한다. 단계마다 결과 요약 → 사용자 확인.

| ☐ | 항목 | 메모 |
|---|---|---|
| ✅ S1~S6·I1~I5·X | 반입 전 보강(실패 스텝 표기·리뷰 수정·비밀값 패턴·events·platforms·platform 설정·YAML C 로더·db_summary·RF-7·증상 검색) | 10/05, `CHANGES.md` |
| ✅ 3C | 행동 eval 52개(Sonnet 36/52, 안전 위반 0) | 10/05, `history/eval-3c` |
| ✅ 3D | 3C 발견 수정, 재실행 18/26 | 10/05, `history/eval-3d` |
| ✅ 3E | 결정적 줄 구조화·guard 10 — 행동 16/17, 안전 0 | 10/06, `history/eval-3e` |
| ✅ 3F | 채점 오판정·guard grep 통독 차단 | 10/06, `CHANGES.md` |
| ◐ W | **개선 트랙**(토큰·편의·유지·보완, WP 0~12) — `docs/development/IMPROVEMENT_PLAN_2026-10.md` §7 진행 표 | **W0~W3 ✅**(10/06; W0 토큰 기준선·여유율 1.3, W1 stdout 33%·record verify `--verbose`, W2 확인 화면 markdown·`pr.ids` 조건부·search JSON 유지, W3 verify-fix 흔적 없으면 종료 2·eval 25 Sonnet 3/3, W4 code 자동 선택·잔여물 알림만·합친 질문). 다음 W5. W2 사내 잔여: 운영 DB 스키마 `pr.ids` PR. 확인 필요: eval 18에서 `cat <로그>` 통독을 guard가 안 막음 — W4 eval 46(`sed -n 1,20p`)·40(`cat -n`)에서도 재현(cat/sed 구간 읽기, `99-deferred §E` 관찰). "개선안 진행"으로 계속 |
| ◐ Z | 마무리: main 병합(PR #5) → `15 §15.4` 재실행 → 새 묶음·sha256 → 사용자 태그 → 2 | 10/06 브랜치 3f1fba9에서 §15.4 9항목 통과(테스트 738·regress 20·offline_eval·eval 54 준비·경계·스키마·뼈대·TODO 73). PR 병합 뒤 main에서 묶음 재생성 |

RF-5(oFono)·RF-6(커넥터)·RF-8(자동화)은 사내 환경을 알아야 의미가 있어 반입 뒤. RF-9·웹 UI(보류)는 그 뒤 후보. RF 상세는 `docs/development/ARCHITECTURE_REVIEW_2026-10.md` §U.

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정

## 막힌 것

- 없음 — 행동 eval은 사내 S-2에서 54개 다시.

## 결정

- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤에는 항상 버전을 올린다(`06 §6.4`). (10/04)
- (f) 반입 전 사외에서 최대한 안정화·보완·개선한 뒤 반입한다. 사내 문자열 사람 검색은 생략(사내→사외 반출 불가). (10/05)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- 시작 전 remote를 fetch한다. remote 이름은 PC마다 다르다(`telephony` 또는 `origin`) — 있는 것을 쓴다.
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`.
