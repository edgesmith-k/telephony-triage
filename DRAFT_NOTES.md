# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·다음 할 일·막힌 것만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 상세 이력(Phase별 산출물·완료 기준 결과·S1 실험 표·가정·옛 미결 목록)은 **`docs/history/draft-notes-2026-09.md`** 에 있고, 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (다른 PC·클라우드 세션 포함)

- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 다음 단계 진행해"** 로 하면 모드를 묻지 않는다(만들어도 됨: `touch .local-draft`).
- 의존성은 고정 버전으로: `pip install '.[test]'` (데비안 패키지와 충돌하면 `pyproject.toml`의 목록을 `pip install --ignore-installed -r`로). 버전이 다르면 `test_r10_dependency_manifest_has_complete_pins`만 실패한다.
- **"다음 단계 진행"** = 아래 **"반입 전 보강 트랙"**에서 ☐인 첫 항목을 한다(2·3C·10은 트랙 Z 때). "묻는다"가 붙은 항목은 결정을 먼저 묻는다.
- 진행 방식(10/05, 사용자 지정): 계획 Opus(Plan 에이전트) → 구현 Sonnet → 메인이 diff 검토·판단 → 관련 테스트(코드 변경이면 전체 `pytest tests`, 약 9분; 문서만이면 관련 테스트) → 커밋·push. 세션에 지정된 브랜치에 push하고 이 표를 갱신한다. 10/05 작업(S2b~S4·결정 포함)은 모두 main에 병합됐다. 새 세션은 최신 main에서 시작한다. 순서: S5→I1~I5→X(RF-7)→3C→Z.

## 진행 상태

- 모드: **사외 초안**. 완료 Phase: **D0, 1~13**. RF-0·RF-1 완료.
- 마지막 전체 테스트: **563개 통과** (10/05, I1, Ubuntu·Py3.11, 8분). Windows에서는 도구 셸 stdin을 `/dev/null`로, PATH 앞에 실제 Python과 `python3` shim(Store 별칭이면 gh 스텁·git hook이 9009로 실패).
- 사내 확인 항목: `TODO(SITE)` **73곳**(S22 12곳 추가) — `python3 tools/list_site_todos.py`. `REVIEW-OPEN.md` 0건.
- 안내서(사람용 HTML): `docs/telephony-triage-guide.html` (공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG)

### 10/04 세션에서 끝낸 것 (모두 push, **사용자 확인 대기**)

| 항목 | 요지 | 근거 |
|---|---|---|
| 4a 탐색 분석 | 후보 없음·원인 미확인 → `timeline.md` + Claude 가설(리포트 보조) | `07 §Step 5-2`, `reference/explore.md` |
| R8 점수 포화 | 동점은 근접·키워드로 정렬, score·S/C 불변 | `04 §5.11 (2)` |
| 테스트 DB | 변형 이슈 DB는 커밋하지 않고 테스트 때 생성 | `11 §11.0`, `runner.variant_db` |
| 검사 통합 | `common/checks.py` 프로필(stage·precommit·guard) | `01 §3.1`, `contracts §종료 코드` |
| 4b 실패 스텝 | 선택 입력(cli > Jira 필드 > 설명 > steps-file), 기록 `failed_step`, README "자주 실패한 스텝". v1 스키마 직접 수정(반입 전 규칙 `06 §6.4`) | `07 §Step 2`, `03 §5.4` |
| 실패 스텝 기준점 | `step_order`: report.html/zip/붙여넣기 스텝 목록의 PASS 스텝을 `step_events`로 로그 흔적과 순서대로 짝지어 마지막 PASS 이후만 분석. 장비 시각은 `--clock-offset` 없이 쓰지 않음. 로그 표식(`log_marker`)은 기본 꺼짐. 스텝 기준 우선 유형(순위만 ≤0.05) | `07 §Step 3`, `02` failed_step·step_events, `14 S22` |
| 보안 검토 수정 | `steps-pasted.txt`를 discard·`lock release`(자기 작업)·cleanup이 지운다 | `08 §8.1`, `contracts §3.2` |
| R11 단정 제거 | RIL 요청 안 보임·시계 점프를 관측 사실·추론·반례로 구분 | `reference/ril-requests.md`·`log-tags.md`, `07 §Step 3` |
| R9 verify-fix 예외 | 결정 (e)로 07·reference·`12-principles.md`를 05에 맞춤(코드 변경 없음) | `05 §5.12 (2)`, `07 §verify-fix` |
| RF-2 | 반입 staging·rollback, `check_boundary`, 사외 CI | 리뷰 §U RF-2 (10/03부터 확인 대기) |

## 다음 할 일

10/04~05 지시 순서(5→6→8→9→10→7→3→2) 중 **1·3~9 완료**(상세 `docs/history/CHANGES.md` 10/04~05 절). 남은 것:

| ☐ | 항목 | 메모 |
|---|---|---|
| ☐ 2 | **사용자 확인** — 위 표, RF-2, 10/05 작업 전체 | 반입 직전에 한꺼번에 |
| ☐ 3C | **행동 eval 전체(50개)** — **사외에서 실행**(사용자 결정 10/05), I1~I5 뒤·Z 전 | 1개 $0.1~0.6. 사내 S-2에서도 한 번 더 |
| ◐ 10 | **반입** | main `7b69cb5` 묶음은 낡음 → 아래 보강 뒤 다시 만든다. 태그 push는 사용자(세션 권한 밖) |

**반입 전 보강 트랙**(사용자 결정 10/05: 시간 여유, 사외에서 최대한 안정화·보완 뒤 반입). 위에서부터 ☐ 첫 항목을 한다. 단계마다 결과 요약 → 사용자 확인.

| ☐ | 항목 | 메모 |
|---|---|---|
| ✅ S1 | 실패 스텝 표기 `번호 \| 이름` 통일 | 10/05 |
| ✅ S2 | 10/04~05 코드 리뷰·eval 발견 수정 | 10/05, `CHANGES.md` |
| ✅ S2b | `stepanchor.step_number`가 줄 앞 날짜를 스텝 번호로 읽음 | 10/05, 날짜 칸은 이름에서도 뺌, `CHANGES.md` |
| ✅ S3 | R12 문서 중복(record·verify·sync-pr) 정리 | 10/05, lock 처리 단일 원본은 write-flow 1번, `CHANGES.md` |
| ✅ S4 | R13 eval 실행기를 `--plugin-dir` 실제 플러그인으로 | 10/05, 기본 `--mode plugin`, eval 7개 실행·결함 2건 수정, `CHANGES.md` |
| ✅ S5 | `check_boundary`에 비밀값 패턴 | 10/05, `CHANGES.md` |
| ✅ I1 | `common/events.py`(`line_ref` 포함) | 10/05, 출력 동일, `CHANGES.md` |
| ☐ I2 | RF-3 `platforms/android/` 이동(출력 동일, shim) | 리뷰 RF-3 |
| ☐ I3 | RF-4 일부: 경로·태그 상수 → 설정 | 리뷰 RF-4 |
| ☐ I4 | YAML C 로더(`CSafeLoader`, 없으면 SafeLoader) | 파싱 시간 대부분이 YAML |
| ☐ I5 | `db_pr` summary/pr_body → `db_summary.py` | 리뷰 §Q |
| ☐ X | **RF-7만**(분석 전용·추가 로그 재분석·입력 해시 재사용) — 사용자 결정 10/05. RF-5·6·8은 반입 뒤 | 리뷰 RF-7 |
| ☐ Z | 마무리: main 병합 → `15 §15.4` 재실행 → 새 묶음·sha256 → 사용자 태그 → 2 | |

RF-5(oFono)·RF-6(커넥터)·RF-8(자동화)은 사내 환경을 알아야 의미가 있어 반입 뒤. RF-9·웹 UI(보류)는 그 뒤 후보. RF 상세는 `docs/development/ARCHITECTURE_REVIEW_2026-10.md` §U.

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정

## 막힌 것

- 행동 eval 전체 재실행은 사내 S-2(위 3C).

## 결정

- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤에는 항상 버전을 올린다(`06 §6.4`). (10/04)
- (f) 반입 전 사외에서 최대한 안정화·보완·개선한 뒤 반입한다. 사내 문자열 사람 검색은 생략(사내→사외 반출 불가). (10/05)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- 시작 전 remote를 fetch한다. remote 이름은 PC마다 다르다(`telephony` 또는 `origin`) — 있는 것을 쓴다.
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`.
