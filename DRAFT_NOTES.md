# DRAFT_NOTES — 사외 초안 상태 파일

> **작게 유지한다(≤8KB).** 사외 초안 모드의 진행 상태·다음 할 일·막힌 것만 둔다 (`docs/design/15-local-draft.md §15.1`).
> 상세 이력(Phase별 산출물·완료 기준 결과·S1 실험 표·가정·옛 미결 목록)은 **`docs/history/draft-notes-2026-09.md`** 에 있고, 필요한 절만 찾아 읽는다.
> 이 파일은 반입 때 사내로 같이 간다. `.local-draft`는 가지 않는다. 모드 판별 규칙은 `CLAUDE.md` 머리말.

## 새 세션 시작 (다른 PC·클라우드 세션 포함)

- clone에는 `.local-draft`가 없다. 첫 메시지를 **"사외 초안 모드로 다음 단계 진행해"** 로 하면 모드를 묻지 않는다(만들어도 됨: `touch .local-draft`).
- 의존성은 고정 버전으로: `pip install '.[test]'` (데비안 패키지와 충돌하면 `pyproject.toml`의 목록을 `pip install --ignore-installed -r`로). 버전이 다르면 `test_r10_dependency_manifest_has_complete_pins`만 실패한다.
- **"다음 단계 진행"** = 아래 "다음 할 일"에서 ☐인 첫 항목을 한다. "사용자 결정"이 붙은 항목은 결정을 먼저 묻고, 결정이 없으면 건너뛰고 다음 ☐로 간다.
- 진행 방식(10/04 세션에서 쓴 방식): 계획(Plan 에이전트) → 구현(구현 에이전트) → 직접 diff 검토 → **전체 `pytest tests` 통과**(Ubuntu 약 23분) → 커밋·push. 단계마다 브랜치 `ccr-9abe96b9-ou831g`에 push하고 이 표를 갱신한다.

## 진행 상태

- 모드: **사외 초안**. 완료 Phase: **D0, 1~13**. RF-0·RF-1 완료.
- 마지막 전체 테스트: **466개 통과** (10/04, 보안 검토·R9·R11 커밋, Ubuntu·Py3.11). Windows에서는 도구 셸 stdin을 `/dev/null`로, PATH 앞에 실제 Python과 `python3` shim(Store 별칭이면 gh 스텁·git hook이 9009로 실패).
- 사내 확인 항목: `TODO(SITE)` **73곳**(S22 12곳 추가) — `python3 tools/list_site_todos.py`. `REVIEW-OPEN.md` 0건.
- 안내서(사람용 HTML, 10/04 1~6단계 반영): `docs/telephony-triage-guide.html` (공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG)

### 10/04 세션에서 끝낸 것 (모두 push, **사용자 확인 대기**)

| 항목 | 요지 | 근거 |
|---|---|---|
| 4a 탐색 분석 | 후보 없음·원인 미확인 → `timeline.md` + Claude 가설(리포트 보조) | `07 §Step 5-2`, `reference/explore.md` |
| R8 점수 포화 | 동점은 근접·키워드로 정렬, score·S/C 불변 | `04 §5.11 (2)` |
| 테스트 DB | 변형 이슈 DB는 커밋하지 않고 테스트 때 생성 | `CLAUDE.md §11.0`, `runner.variant_db` |
| 검사 통합 | `common/checks.py` 프로필(stage·precommit·guard) | `01 §3.1`, `contracts §종료 코드` |
| 4b 실패 스텝 | 선택 입력(cli > Jira 필드 > 설명 > steps-file), 기록 `failed_step`, README "자주 실패한 스텝". v1 스키마 직접 수정(반입 전 규칙 `06 §6.4`) | `07 §Step 2`, `03 §5.4` |
| 실패 스텝 기준점 | `step_order`: report.html/zip/붙여넣기 스텝 목록의 PASS 스텝을 `step_events`로 로그 흔적과 순서대로 짝지어 마지막 PASS 이후만 분석. 장비 시각은 `--clock-offset` 없이 쓰지 않음. 로그 표식(`log_marker`)은 기본 꺼짐. 스텝 기준 우선 유형(순위만 ≤0.05) | `07 §Step 3`, `02` failed_step·step_events, `14 S22` |
| 보안 검토 수정 | `steps-pasted.txt`를 discard·`lock release`(자기 작업)·cleanup이 지운다 | `08 §8.1`, `contracts §3.2` |
| R11 단정 제거 | RIL 요청 안 보임·시계 점프를 관측 사실·추론·반례로 구분 | `reference/ril-requests.md`·`log-tags.md`, `07 §Step 3` |
| R9 verify-fix 예외 | 결정 (e)로 07·reference·`CLAUDE.md §12`를 05에 맞춤(코드 변경 없음) | `05 §5.12 (2)`, `07 §verify-fix` |
| RF-2 | 반입 staging·rollback, `check_boundary`, 사외 CI | 리뷰 §U RF-2 (10/03부터 확인 대기) |

## 다음 할 일 (위에서부터)

| ☐ | 항목 | 메모 |
|---|---|---|
| ✅ 1 | **보안 검토** — 10/04 변경분(`93ef099..f91daf6`) | 10/04 완료. 고친 것: 붙여넣은 스텝 원문 `steps-pasted.txt`가 discard·release 뒤에도 남음 → `db_pr` discard·`lock release`(--force 아님)·cleanup이 지움. 문제없음: zip(메모리만, 선언·실제 크기 상한, 암호화·절대/`..` 거부, 멤버 하나), html 5 MiB, 정규식 타임아웃, 스텝 이름·zip 경로·마커 마스킹, 첨부 문장은 데이터(SKILL·explore) |
| ☐ 2 | **사용자 확인 받기** — 위 표와 RF-2 | 확인되면 표에서 "확인 대기"를 지운다 |
| ☐ 3 | **스킬 행동 평가 재실행 + 새 기능 eval 추가** (사용자 결정: 사외 vs 사내 S-2, 토큰 큼) | 탐색 분석·실패 스텝·기준점·붙여넣기 흐름, Phase 13 실패 4건 수정분. `tests/skill_evals/README.md` |
| ✅ 4 | **HTML 안내서 갱신** — 1~6단계 반영 | 10/04 완료. 이후 기능이 바뀌면 `docs/telephony-triage-guide.html`도 고친다 |
| ☐ 5 | **성능** — `db_pr` 등이 하위 스크립트를 같은 프로세스에서 호출 | PR 한 건당 수십 초 단축. 리뷰 §Q "서브프로세스 재진입". 종료 코드 계약 유지 |
| ☐ 6 | **유지보수** — `db_add.py`(1,373줄) op별 분할 | 리뷰 §Q. 동작 동일 |
| ☐ 7 | **트리거 개선** — 자연어 호출 recall 26~33% | SKILL.md 8,191/8,192바이트: description을 늘리면 본문을 줄여야 함. 지금은 슬래시 커맨드로 쓰면 문제없음 |
| ☐ 8 | **R7 근거 출처**, **R15 대용량 로그 처리** (R9·R11은 10/04 완료) | `docs/development/PLUGIN_IMPROVEMENT_HANDOFF.md`. R7은 RF-8 전제 |
| ☐ 9 | **`CLAUDE.md` 축소(≤4KB, §12 이동)** — 사용자 결정 대기 | 결정 전에는 건너뛴다 |
| ☐ 10 | **반입** — `15 §15.4` 체크리스트 재실행: `check_boundary --mode external`, `sync_schemas --check`, `make_db_skeleton.py`(새 키 `step_focus`·`step_events` 확인), `list_site_todos`, `git archive` 묶음 | `GUIDE.md` §3 "반입 전". 1~2는 반입 전에 필수, 3~9는 반입을 막지 않는다 |

반입 뒤(사외 트랙): RF-3 전에 **`common/events.py`**(RF-1에서 빠짐) → RF-3 → RF-4 → RF-5(oFono), RF-6 → RF-7 → RF-8(품질 게이트·R7 필요), RF-9. 웹 UI는 사용자 결정으로 보류(RF-6·7 뒤 후보).

## 사외에서는 못 하는 것 (사내 S-1~S-5)

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정

## 막힌 것

- 행동 eval 재실행과 트리거 recall 확인은 실제 Claude 세션이 필요하다(위 3·7).

## 결정

- (a) 사내→사외 반출은 사용자가 직접 타이핑하는 사내 정보 없는 문장뿐. 사외는 합성 데이터로만 재현한다. (10/01)
- (b) 자동 게시(RF-8)는 `confidence`가 아니라 별도 품질 게이트로만. (10/01)
- (c) 실패 스텝·Claude 가설은 판정(S/C)에 쓰지 않는다. 구간·순위·검색·리포트 보조만. (10/04)
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤에는 항상 버전을 올린다(`06 §6.4`). (10/04)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- 시작 전 remote를 fetch한다. remote 이름은 PC마다 다르다(`telephony` 또는 `origin`) — 있는 것을 쓴다.
- 사내 로그가 모의와 다를 때 가장 먼저: `docs/development/S0_PROBE_CHECKLIST.md` + `tools/s0_stats.py`.
