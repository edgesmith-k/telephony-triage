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

## 11/12 이동: 줄인 줄의 원문 (진행 상태 1줄, 결정 (v)(p)(q)(d)(e)(o))

- **코덱스 종합 리뷰 반영 완료**(`58ae770`·`1554dc0`, GRADER_VERSION 5). WSL 전체 pytest 통과, hook_probes 176개 판정 동일. 상세는 `docs/history/draft-notes-2026-11.md`.
- (v) 11/09 사용자(코덱스 02e0ec2): **F01 보강** — DB가 쓰는 시그니처 feature는 `issue-db.config.yaml signature_features`에 선언, 플러그인이 모르는 feature면 **분석 중단**(읽기 전용 아님, `feature-unsupported`); 새 필드는 S37 결과·팀 설치본 통일 뒤에만. **Q01 채택 관문** — 가설 줄 `[근거 불일치 N]`, fabricated 인용이 든 가설은 시그니처 초안에 쓰지 않고 사용자가 재확인한 인용만(종료 0 유지). 채점 판정(S 행 어느 것이든)이 바뀌면 GRADER_VERSION을 올린다.
- (p) 수정 절차(10/14, 11/08 역할): **재확인·설계 = Fable 메인, 구현+시험 = Opus, 리뷰 = 별개 Opus(설계자 아님) → P0·P1은 그 단계에서 고치고 테스트·기계 검증** → 통과 뒤 커밋. H 진행 방식은 `MODULE_SKILLS_DECISIONS.md`.
- (q) 사내 S-2 축소(10/14, 사용자): 사내 대상 = `pending.json` `site` 11개(hook·권한·적대 입력·외부 쓰기·사내 측정), 사내 모델이 다르면 +7. 나머지는 `offsite_results.json`(도구 생성)으로 갈음, 사외 실패·미결정은 사유 면제, 안전 위반은 면제 불가.
- (d) 반입 전에는 v1 스키마를 직접 고치고, 배포 뒤 구조 변경은 항상 버전을 올린다. 호환 변경은 올리지 않고 운영 DB `schema/`를 메인테이너 PR로(`06 §6.4`). (10/04, 10/28 사용자)
- (e) verify-fix 흔적: 코드·설정 수정 유형은 흔적 필수. 비코드 유형(user-setting·network·hw)에 흔적 시그니처가 둘 다 없을 때만 사용자 확인으로 판정하고 `verification.note`에 남긴다. (10/04, R9)
- (o) 사내 트래커는 Jira (10/12, 사용자): 사내 설정은 `tracker.kind: jira`, S30·S31(GitHub 트래커)은 해당 없음. "사내 설정 시작" 한마디로 `tools/site_step.py`가 단계를 이어 낸다(완료 기준·사용자 확인은 그대로).

## 11/12 가상 사용자 리허설 (태그 전, main `6f7bffc1`)

- 방법: main을 묶음처럼 풀고 임시 마켓플레이스 정의(`source: ./plugin`)와 `site-defaults.yaml`(예시 복사)을 붙여 격리 프로필에서 Claude Code 2.1.322로 `plugin validate`·`marketplace add`·`install`. 사용은 `tests/skill_evals/run.py`(plugin 모드, 모의 Jira·원격·gh, Sonnet 5.5).
- 설치: 성공. 하위 폴더 source 동작(S1 사외 확인 — 사내 CLI 버전에서 다시), 버전 = 커밋 SHA, 스킬 15·hook 4종. 경고는 `version` 없음(의도)·README 설치 줄 없음(조언).
- 처음 setup(config·clone 없음 — 기존 eval에 없어 리허설 사본에만 추가): doctor 13항목 ok. 원격을 로컬 경로로 답하면 `config.py init`이 거부하고 멈춘다(의도대로).
- 사용 13건(eval 1·2·3·12·17·19·31·46·51·53·54·61·72): 기계 채점 실패 0, 수동 17행 pass(별개 에이전트, eval 12 "유지/재분류" 행은 "재분석/그만둔다"로만 물어 단서). guard가 막은 쓰기 0. setup 재점검(58)은 채점 안 함.
- P2(반입 뒤 후보): ① verify-fix 확인 화면 "열린 PR: 확인 못 함" — PR 검색어(Jira 키·새 ID)가 없어 검색을 안 한 것인데 gh 실패와 같은 문구(`dbpr/publish.py` open_prs, `db_summary.py`). ② `--analysis-only` 리포트를 되돌려 다시 보일 때 "분석 전용…"·"로그 범위…" 줄이 리포트 본문과 must_show 양쪽에 있어 두 번 나온다.
- 사내 S-2에서 같이 볼 것: eval 1·46에서 publish·release 뒤 `issue_post.py status`와 Jira 게시 질문이 빠졌다(실행자가 "규칙에 없는 질문"이라 생략 — 모의 영향 가능, 미확정).
- 설계대로라 고치지 않는 것: verify-fix 시각 연도 2000(`verify.md` 시각 기준), 스냅샷 없을 때 검색 `--db` 생략, `report.md` 원인 칸 `TODO(LLM)`.
- 거슬린 점(미처리): 새 원인 질문 8개(분류 3단계)·Jira 코멘트 9개, 리뷰어 질문 선택지가 "지정 안 함" 하나, show-guard 되돌림으로 질문 재시도(1·2·46), 게시 본문에 `[placeholder 규칙 결과]` 노출.

## 11/12 작은 P2 묶음·훑기 1단계 (#98)

- 리허설 P2 하나 더: 처음 setup에서 묻지 않은 팀 기본값을 한 줄씩이 아니라 한 문장으로 묶어 보였다(이제 어떤 채점 행도 보지 않는다 — eval 80은 사내 대상에서 뺐고 수동 행을 없앴다).
- oFono 설정 반영 확인(합성 로그, 코드 수정 없음): site-defaults `platform.others.ofono`의 `components`(idents·msg_format·split_tag)·`protocols.<이름>.tags`·`log.phone_id`를 바꾸면 `parse_logcat parse` 출력이 따라 바뀐다. 알아 둘 것 셋은 `site-defaults.example.yaml` 주석에 적었다(새 ident는 이슈 DB tags.yaml에도, `log.phone_id`는 원문 기준, `msg_format` 불일치는 경고 없음).
- O 단계 pack 크기: O-1 13.3KB, O-2 45.3→24.6KB, O-3 10.7KB, O-4 37.4→8.3KB(`02-config.md` §4.1).
- 훑기(읽기 전용, Android·oFono 모듈 문서·case·fixture): 실제 칩셋·제조사 이름은 없다. 1단계로 고친 것 — oFono 모듈 문서에서 합성 로그에 없는 이름·문구, case 주석 2개, oFono 테스트 합성 줄.
- 훑기에서 남긴 것(후보): Android `_common/components.md`의 벤더 층 서술에 "가정" 표시(공통 문서 상한 여유 39B, 바꾸면 7개 모듈 eval), case 로그의 벤더 층 줄을 더 밋밋한 값으로(기대값·생성물이 따라 바뀜 — 범위는 사용자), 벤더 줄이 있는 case 머리 주석에 "가정" 표시, 벤더 IPC 줄 뼈대는 `common/vendor_ipc.py` 정규식이라 규칙 변경. 둘은 같은 eval 재실행이 필요하므로 함께 한다.
- oFono 모듈 eval(문서 정리 뒤 1회, claude-sonnet-5-5): data fail(with 3·without 3, with arm 안전 위반 2 — `dbus_trace` 줄 인용 뒤에 설명을 붙여 원문과 어긋남, `data-route-fail`은 출력 칸 누락), ims pass, network pass(11/08 fail), modem tie. data의 실패 행은 고친 문구와 무관한 인용·출력 형식이다. 다시 돌리지 않았다.

## 11/12 Android case 보강 (#99)

- 추가: `sms-mt-delivered-to-app`(explore, MOCK-9822) — Android 17 에뮬레이터 캡처에서 고른 AOSP 층 줄, 수신·ACK·앱 전달·raw 삭제까지 정상이라 정답은 `원인 아님(정상 동작)`(또는 곁가지). android case는 data 5·sim 3·network 2·call 3·sms 3·ims 3·modem 3.
- 뺀 것: network case "허용 망 종류를 좁힘"(정답 프레임워크). 원인 줄의 태그 `PhoneInterfaceManager`·`Phone-0`이 샘플 DB tags.yaml에 없어 모듈 타임라인에 요청·응답 4줄만 남고, 그 근거로는 정답이 서지 않는다(별개 리뷰 P1 — 규칙을 지킨 `그 층 로그 없음` 답을 떨어뜨린다). 태그 추가는 파서 규칙 변경이라 사용자 확인 뒤에. case를 설계할 때는 `--write` 뒤 timeline.md에 근거 줄이 있는지 먼저 본다.
- `_common/components.md` 벤더 층 서술 3곳에 "(가정)". 리뷰 P2(후보): 정의 없는 새 표기라 placeholder·TODO(SITE)와 통일할지, 제목에서 "벤더 IPC 결과"가 빠진 것, `layers.md`·`network/explore.md`는 같은 내용(AT 중계 = 곁가지)을 단정으로 쓴다. 공통 문서 합 5956B — `data/explore.md`와 묶인 explore run 예산(8800B) 때문에 5B만 남는다.
- Android 모듈 eval(claude-sonnet-5-5, 1회): data·network·call·sms·ims·modem pass, sim fail(with arm이 이벤트 주석 `ril_timeout(…)`을 근거 줄로 인용 — 안전 위반 1). network·sms는 case를 고친 뒤 다시 돌린 결과다(첫 실행은 network pass·sms tie).
- eval 형식 실패 후보(11/12 하루에 본 것, 문구와 무관하게 관문을 뒤집는다): 근거 줄 뒤에 설명을 붙여 원문과 어긋남, 이벤트 주석을 근거 줄로 인용, 가설 하나에 근거 4줄, `코드로 추정` 칸 누락. sms/explore.md에는 "수신·전달 성공인데 앱에 안 보임" 행이 없다.
