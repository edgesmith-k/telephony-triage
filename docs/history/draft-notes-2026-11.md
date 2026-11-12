# DRAFT_NOTES 이력 (2026-11)

`DRAFT_NOTES.md`에서 옮긴 원문. 필요한 절만 찾아 읽는다.

## 11/03 진행 상태 원문 (H 시작 전)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강 완료. 최신 묶음 **import-20261103**(main `77e2827`, 1102 대신). main 병합 PR #8~#79.
- 11/02~03 재리뷰 완료(#79, `REVIEW_1102_HANDOFF.md` 머리, 1102 §6). **다음: H — `MODULE_SKILLS_PLAN.md` 머리 "새 세션에서 이어 하기"**.
- 모델 Sonnet 5.5 기준(Opus 5.5 11개 실패 0). `TODO(SITE)`: `tools/list_site_todos.py`. REVIEW-OPEN 0. 사내 시작 **"사내 설정 시작"**(결정 (o)).
- 안내서: `docs/book/telephony-triage-book.html`(공유본 https://claude.ai/artifact/1jov1Et4dQUMauFr6aoxWG), 목록 `docs/materials/00-index.html`

## 11/03 이동: 결정 (m)·(n) 원문

- (m) 플랫폼 분리 (10/11, 사용자): 동작·원인·해결책이 달라 이슈 DB를 플랫폼별로(합치기 안 안 씀), 추가는 디렉토리 + `platform.enabled`, lock은 플랫폼별("사용자·이슈 DB(플랫폼)별 한 번에 한 작업"), RF-4 유지. `17-platforms.md` §7.
- (n) 트래커 범용화 (10/11, 사용자): 설정 `tracker.kind`(jira|github)·어댑터 `trackers/`, `issues/`·`platform_version(s)` 개명은 (d)로 v1 직접 수정, 옛 키는 감지만(fail-closed), DB kind 다르면 거부. `18-trackers.md` §7.

## 11/09 이동: 11/06 진행 상태 원문 (코덱스 02e0ec2 반영 전)

- 모드: **사외 초안**. Phase D0·1~13·반입 전 보강 완료. 지난 묶음 **import-20261103**(main `77e2827`). 다음 묶음 **토 11/7 18:00 KST**.
- **H 단계 G 마무리**: A1·A2·guard·C0·B1+B2 ☑. C1+D·보정·F·Jira 관문·C·C′·덤프 마스킹·후보 채점, Codex 리뷰 P1 6건, 모듈 eval(25→27/42, `_common` 근거 규칙)·Haiku 비교, G 재측정 67개(offsite pass 65·fail 5), 반입 노트(`b4a5b42` 이후 표) 브랜치 반영. 남은 것: 묶음(사용자 태그·반입), 단계 확인. 결과는 `MODULE_SKILLS_RESULT.md`.
- 남은 일 H 행: 모듈 스킬 레포·+1 병합 — G만 남음(`MODULE_SKILLS_PLAN.md §4`) → 11/09 완료 처리.

## 11/09 이동: 사외에서는 못 하는 것 (사내 S-1~S-5) 원문

- 실제 로그 문구와 태그 확인 (S9 등), 실제 Jira 필드 이름 (S20·S22)
- report.html의 실제 표 구조, PASS/FAIL 표기 (S22)
- 스텝 → 로그 흔적 대응표(`step_events`) 내용, 장비와 단말의 시계 관계, Jira 발생 시각의 기준 시계 (S22)
- 정확도 평가: 과거 해결 Jira 20~30건 라벨셋으로 `tools/offline_eval.py` (S-5), 기준점 구간 기본값 조정
- 3차 검토 사내 확인 C1~C8은 §15.5 행(S-2·S-4a·S-5·S-7)에, 파일럿 뒤 판단 D1~D15(L에서 넘긴 사내 전용 D7~D15 포함)는 `docs/tasks.md` S-7 비고에 있다.

## 11/09 이동: 결정 (t) 원문

- (t) oFono 확장(10/30, 사용자): oFono DB 하나에 모든 데몬, 한 스트림, 데몬별 소스, 데몬 사이 짝(17 §9 K12~K15). 가설 분석은 플랫폼별(최상위 `analyzers` = android, 그 밖 `platforms.<p>.analyzers`, 대체 없음, 탐색 자료 `reference/platforms/<p>/`, §10 K16·K17). 플랫폼은 로그 형식 자동 + 애매하면 질문(§11 K18).

## 11/09 코덱스 종합 리뷰(02e0ec2) 반영 기록

- 커밋 `58ae770`(F01 보강·F02·F03·F04·F05·F06·Q01, 41 파일 +604/−122)·`1554dc0`(GRADER_VERSION 4→5). 절차: 항목마다 재확인(코드로 재현)·설계 한 줄(Fable) → Opus 구현 4명(파일 분리) → 별개 Opus 리뷰 2라운드(1라운드 7건: F04 회귀 2·F03 보완 2·문서 3, 2라운드 2건: db-authoring 상한·태그 제외 범위) → WSL 전체 pytest 4,001·lint·hook_probes 176 동일.
- 설계에서 벗어난 점: F02 두 번째 낡음 시험은 `--arms without`; F03 지문에 `tracker.read_tools ∪ tracker.tools`와 계산 폴더 순서 `directory` > 기록 `project` > cwd, `tracker_view(cfg)`; F04 regex는 `=` 꼴·`:` 꼴 분리 + 꼬리 lookahead + 조각마다 `msg_part`·태그 키 `:` 토큰 제외; explore.md 상한 7,580·db-authoring 12,600·템플릿 call 2,700·data 2,900(run 예산 8,777 ≤ 8,800).
- 확인: pytest 수는 브리프 3,986(02e0ec2)이 맞고 3,966은 90de0f6 값. "setup 10→3"은 개인 입력 항목 3개(브리프 §1-b 문구를 "config 질문(개인 입력 항목) 10→3"으로).

## 11/12 이동: 결정 (m)(n)(t) 줄

- (m) 플랫폼 분리(10/11, 사용자): 이슈 DB 플랫폼별, lock 플랫폼별, RF-4 유지 — `17-platforms.md` §7.
- (n) 트래커 범용화(10/11, 사용자): `tracker.kind`(jira|github)·어댑터 `trackers/` — `18-trackers.md` §7.
- (t) oFono 확장(10/30, 사용자): `17-platforms.md` §9~11. 원문은 `docs/history/draft-notes-2026-11.md`.

## 11/12 다음 사이클 후보 상세 (#89~#92 리뷰·eval에서 남긴 것)

DRAFT_NOTES 후보 줄의 풀이와, 상한 때문에 거기 못 넣은 P2다. 고칠 범위는 결정 (r).

- **sim fail 채점 기준**: Android 모듈 eval `sim-slow-recognition`(#91 때는 `network-reg-reject`도)에서 기준선(without) arm이 로그 줄이 아니라 이벤트 표기(`⇒ ril_timeout(latency_ms=…)`, `network_registration_rejected(cause=13,domain=PS)`)를 근거로 인용했고 채점기가 `지어낸 근거`로 셌다. with arm은 위반 0인데 관문이 두 arm 모두 0을 요구해 fail. 이벤트 표기 인용을 지어낸 근거로 볼지 정한다(판정이 바뀌면 GRADER_VERSION).
- **sms 문서 P2 2**: `sms/SKILL.md` 1번 규칙에 `SS=1~3` 조건이 붙어 `SS=0`인데 `SEND_SMS`가 없는 경우의 규칙이 없다. `explore.md` "SMSC" 행의 조건이 SMSC가 아니라 서비스 없음 조건이다. 풀어 쓴 문구는 with arm이 `SS=` 줄을 인용하지 않아 eval fail(0/0)이라 되돌렸다(#92).
- **`sms-ims-local-reject` 기대**: 두 arm 모두 `맞은 후보 근거에 regex 없음`으로 실패(이전 기록부터). 입력이 17 이전 문구인지, 기대 근거가 과한지 재검토.
- **eval 42 allow-cause 경로 표시**: 모델이 `allow_cause_drafts`의 fixture를 `fixtures/` 경로 없이 파일 이름만 보임 — 2회 중 1회 실패(Sonnet 5.5). 스킬 문구(`db-authoring.md` "op 그대로")를 더 분명히 할지. `tests/test_skill_evals.py`의 eval 42 시험 자료도 경로 없는 꼴이다.
- **Android 17**: SMS-001-01(`sendSms … SS=[1-3]`)이 5G SA의 `SS≠0` RIL 발신에도 맞을 수 있음(17 소스 미확인). CALL-001 `volte-dial-attempt`가 CS 발신에도 맞음. case 이름 `sms-smsc-missing`이 내용(서비스 없음)과 다름. `network/explore.md` 밖의 17 문구 점검은 #92에서 ims·call·network만 함.
- **마스킹(#90)**: 한글만으로 된 `token=` 값 미마스킹(설계)과 contracts "값 무관" 문구 불일치. `iccid=8982` 뒤 US 구분자 꼴은 앞 4자리가 남음(이전부터). `fold_ascii`가 masking·check_boundary에 중복 정의, `isascii()` 빠른 경로 없음. 갈린 조각 표 키가 IMSI·ICCID는 접지 않은 원문. check_boundary: 예외 처리된 접은 글 match가 뒤 값을 삼키면 접은 글에서만 보이는 위반이 빠질 수 있음.
- **사내**: IMS는 별도 APK라 IMS 줄·규칙·ims·call 모듈 문서는 S-1에서 먼저 맞춘다(확인 항목은 레포 밖 사내 확인 목록).
- 기록이 없어 내용 확인이 필요한 후보: C 지표 자리, 4-c 2차, B 조건부, 4-c P2 6건, D① P2 잔여, F3의 B/C, 분석 전용 종료 표식, 포트 변조 잔여(끝 `.`·`키: 값`).
