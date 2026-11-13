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

## 11/12 Android case 5개 추가 (#99 후속)

- 추가(explore, 에뮬레이터 17 캡처의 AOSP 층 줄, 합성): `call-mo-out-of-service`(MOCK-9823, 캡처 c09r2-mo-no-service, 정답 모뎀·망), `sim-apps-disabled-by-request`(9824, s02-sim-power, 프레임워크 또는 원인 아님), `modem-radio-off-airplane`(9825, m02-airplane-on-off, 프레임워크 또는 원인 아님 — 캡처의 DNC 줄은 샘플 DB 기존 유형에 걸려 넣지 않음), `network-oos-recover-no-reject`(9826, n09r-oos-recover, 모뎀·망), `data-profile-invalid-after-apn-change`(9827, d70a-no-apn-disabled, 프레임워크). case 수: data 6·sim 4·network 3·call 4·sms 3·ims 3·modem 4.
- 만들지 않은 것: ims(에뮬레이터에 IMS 서비스가 바인딩돼 있지 않아 AOSP 층 줄만으로 원인이 성립하는 캡처가 없음 — 사내 항목), data `d20h-nw-radio-hal-kill`(data 보기에 `has died`·`UNSOL_RIL_CONNECTED` 줄이 들어오지 않음, 같은 원인은 `modem-ril-daemon-crash`가 다룸).
- 배운 것: 모듈 보기는 샘플 DB `tags.yaml`뿐 아니라 `templates/module-skills/modules.yaml`의 보기별 tags·`ril:` 목록과 샘플 DB `ril.yaml`로도 거른다 — 다른 모듈의 RILJ 요청 줄(call 보기의 `VOICE_REGISTRATION_STATE`)이나 ril.yaml에 없는 요청(`ENABLE_UICC_APPLICATIONS`)은 timeline에서 빠진다. trap은 `label:` 키면 층·데몬 칸 어느 쪽이든 걸리고, `layer:` 키면 층 칸만 본다(network·modem 새 case에서 처음 씀).
- 독립 리뷰(Opus, 읽기 전용): P0 0, P1 4 — network 데몬·근거 regex, modem trap을 층 칸만 보게, sim source.log의 셸 조작 줄 2개 삭제 — 반영(`643f90d1`). 리뷰가 accept daemon에 `RILJ`도 받으라 했으나 넣지 않음(#99 리뷰의 "다른 층 이름을 daemon regex에 넣지 않는다"와 맞춤; 데몬 칸 RILJ는 함정도 인정도 아님). P2 후보(안 고침): call trap이 `그 층 로그 없음(모뎀·망)`도 잡음, network·data의 `원인 아님` trap이 sim·modem과 일관되지 않음, 문서 4곳(`modem/explore.md`, `network/explore.md`, `network/SKILL.md`, `network/references/NETWORK-001.md`)의 "`radioStateChanged:` 17 캡처 없음" 표기가 캡처와 어긋남, modem·call 증상 문장이 근거·정답 층을 드러냄, sim `원인 아님` daemon에 `MultiSimSettingController` 없음, call·network source.log의 에뮬레이터 기본 사업자 값.
- WSL 전체 pytest: 4147 passed, 26 skipped, 3 xfailed(`643f90d1`).
- Android 모듈 eval(11/12, claude-sonnet-5-5, restricted, 1회, 총 $3.80, 안전 위반 0): call pass(with 2·without 1), sim pass(3·2), modem pass(2·2), network **tie**(1·1, top1 with 0 < without 1), data pass(4·0). 새 case별 with/without: data O/X, sim O/O(변별 없음), call X/X, modem X/X, network X/O.
  - call with: 가장 유력을 프레임워크/SST-0으로 골라 함정. without: 내용은 맞았으나 가설 둘이 같은 층·데몬(그 층 로그 없음 / 알 수 없음)이라 형식 실패.
  - modem with: 층·데몬은 맞고 근거에 `radioStateChanged: OFF` 대신 ON 줄 인용. without: 데몬 RILJ, 응답 줄 인용.
  - network with: `그 층 로그 없음(벤더 RIL)`을 골라 모뎀·망을 배제(공통 `layers.md`의 "RILJ 요청뿐 RIL·VRIL 줄 0 → 그 층 로그 없음(벤더 RIL)"을 따른 것으로 보인다 — 문서 규칙과 case 기대값이 부딪히는 자리, 다음 문서 사이클 후보). without: 모뎀·망으로 통과.
  - 결과는 그대로 기록했고 통과를 위해 다시 돌리거나 기대값을 바꾸지 않았다(`module_offsite_results.json`).
- #98 사후 리뷰(Opus): P0·P1 없음. 반영한 P2: README "지금 기록" 줄을 실제 기록 값으로, 낡은 "eval 71 none" 문장 삭제, `test_ofono_skeleton.py`에 중간 필드 낀 vendor IPC 줄 복원, `offsite.py --merge`가 최상위 `grader_commit`을 기존 값으로 두고 채운 항목에만 붙임(커밋된 기록 파일은 소급해 고치지 않음). 남긴 것: eval 80 `few_questions` 하한·`clone_after_consent` 조건, 마스킹 되돌림(`b17742fe`) 이유 기록.

## 11/12 Android 모듈 문서 보완 (#100 eval 후속)

- 보완(#100 eval에서 문서를 읽은 쪽이 틀린 세 자리의 빈 규칙; `_common`·case·파서 규칙·테스트는 그대로):
  - network(`explore.md`·`SKILL.md`·`references/NETWORK-001.md`): 거절 아닌 미등록(`NOT_REG…`)도 RILJ 응답·NRM-C가 글자로 말한 아래 층 값 → 모뎀·망(벤더 줄이 없어도). 버퍼가 늦게 시작한 경우·무선을 끈 뒤는 기존 규칙이 먼저. "회복(`REG_HOME`)도 층을 안 바꾼다". "`radioStateChanged: OFF`(17 캡처 없음 — 사내 확인)" 표기 3곳 삭제(에뮬레이터 17 캡처 m02에서 그 줄 확인).
  - modem(`explore.md`): 비행기 모드 행 — 죽음·재시작 줄이 있으면 그 행, 없고 RILJ `RADIO_POWER on = false` 요청이 `radioStateChanged: OFF`보다 앞서면 위에서 끔 → 원인 아님, 근거는 요청·OFF 두 줄. 같은 "17 캡처 없음" 표기 삭제. "요청 없이 OFF·UNAVAILABLE → 모뎀·망" 문장은 공통 규칙을 넓혀 읽은 것이라 넣었다가 뺌(사용자 확인 11/12, 그 경우는 공통 규칙에 맡김).
  - call(`explore.md`): CSFB 행을 "CSFB·`DIAL`·INVITE 없는 발신 실패"로 넓힘 — 발신 전 SST `hasDeregistered = true`(서비스 없음) → 모뎀·망, 프레임워크는 증상. 자리 확보로 발신 실패 행의 IPC 판정을 공통 `layers.md` 참조로 바꾸고 표의 군말 몇 곳 축약.
  - 문서 여유(바이트): network explore 2698/2700·SKILL 1999/2000·NETWORK-001 1288/1300, call explore 2694/2700, modem explore 2597/2700.
- 독립 리뷰(Opus, 읽기 전용): P0·P1 없음, P2 9건 가운데 eval 전에 반영 — network "(찾는 중)" 표지 삭제·무선 끈 뒤 예외·회복 문구, modem "위 행" 모호함, call 축약으로 뜻이 바뀐 두 곳(EPS 행 "fallback", 끊김 행 "원인 코드를 전한 층") 복원·행 이름에 INVITE. 남긴 후보: network "긴 미등록"의 "긴"을 되살리지 못함(4B 부족), call에 Telecom "network not available" 표지를 넣지 못함, 새 규칙의 근거 표현이 case 정답과 닮음(과적합 기미 — eval 통과를 "빈 규칙을 채웠다"로 읽을 것), sms(서비스 없음 → 프레임워크)와 call(→ 모뎀·망) 정책이 다름 → sms를 call에 맞추는 방향으로 다음 사이클(사용자 11/12), 그때 deep case `sms-smsc-missing` 기대값부터 확인.
- WSL 전체 pytest: 4147 passed, 26 skipped, 3 xfailed(`452c057c`).
- Android 모듈 eval(문서 보완 뒤, claude-sonnet-5-5, restricted, 1회, 총 $2.01): call pass(with 3·without 2; 직전 2·1), modem pass(2·1; 직전 2·2, 기준선 arm 안전 위반 1 — `modem-restart-chain` without, 원본 .log를 `Grep '.'`로 통째 읽음), network pass(3·1; 직전 tie 1·1). 새 case with/without: `call-mo-out-of-service` O/O(직전 X/X), `network-oos-recover-no-reject` O/O(직전 X/O), `modem-radio-off-airplane` X/X(직전 X/X).
  - `modem-radio-off-airplane` with: 가설 1이 원인 아님(RADIO_POWER on = false 요청 → OFF 순서)으로 층은 맞았으나 가설 1 근거 4줄이라 출력 칸 파싱 실패(형식). without: 가장 유력이 프레임워크(요청·응답 줄 인용)이고 채점은 "맞은 후보 근거에 regex 없음"(근거에 `radioStateChanged: OFF` 줄이 없음).
  - `modem-ril-daemon-crash` with(직전에도 X): 벤더 RIL·VRIL로 층·데몬은 맞았으나 가설 1 근거 4줄(`serviceDied`·`GET_SIGNAL_STRENGTH error 1`·VRIL UNAVAILABLE·ON)이라 출력 칸 파싱 실패(형식).
  - `call-volte-sip-invite-error` with: 모뎀·망/VRIL-IMS로 층·데몬은 맞았으나 인정 후보의 근거 regex 불일치(INVITE·503 응답·onCallStartFailed 3줄 인용; 어느 regex가 빠졌는지는 grading에 안 나옴).
  - 1회 실행이라 변동이 있고 통과를 위해 다시 돌리지 않았다(`module_offsite_results.json`).
- 마스킹 되돌림(`b17742fe`, #98 사후 리뷰 P2)의 이유: 사용자 결정(11/12) "마스킹을 너무 집착할 필요 없다" — 20자리를 넘는 구분자 낀 ICCID의 꼬리 숫자 잔여는 알고 받아들인 것.

## 11/12 S-0(선행 확인)을 사내 첫 단계로

- 사용자 지시(11/12)로 S-0를 `tools/site_step.py`의 정식 첫 단계로 넣음. 순서 S-0 → S-1 → … → S-7, 새 `SITE_PROFILE.md`의 현재 단계는 S-0. 이미 S-1 이후로 진행 중인 프로필은 그대로 이어진다(회귀 테스트 있음).
- 점검 `s0.metrics`·`s0.conclusion`(`tools/site_checks.py`): 기록이 없거나 값이 숫자·`-`가 아니면 fail이 아니라 "사용자 필요" → 기존 `--done S-0 --waive 점검="사유"`로 건너뛸 수 있다(예: 반입 전에 이미 함, 실제 로그를 아직 못 구함). S-0는 측정 단계이지 관문이 아니다.
- 기록 자리: 확인값 표 새 번호 S38의 행 2개(`S-0 지표`, `S-0 결론`), 기존 `propose --set row.S38.…` 경로. `tools/s0_stats.py` 텍스트 출력 끝에 그 행에 붙여 넣을 한 줄(`tags= pair= tsfail= clock= pid=`)을 추가(파일은 쓰지 않음). 지표 5종: 수집 태그 비율·RIL 짝 맞춤 비율·시각 파싱 실패율·시계 이상 건수·phone_id 추출률(`s0_stats.py`는 "범위 밖" 비율을 내지 않는다).
- 사내 토큰: S-0 안내 묶음에서 `04-parser-matching.md §5.8` 본문을 빼고 `S0_PROBE_CHECKLIST.md`만 남김(약 30.0KB → 약 10.6KB), 테스트 상한 30,000 → 11,000. 반입 전에 파서 일부만 가져가 미리 하는 방법(`S0_PROBE_CHECKLIST.md`)은 그대로 — 그때 잰 값을 반입 뒤 S-0에서 옮겨 적는다.
- 문서 표기 수정: `15-local-draft.md`·`14-site.md`·`tasks.md`·`README`·`GUIDE.md`·`SITE_INSTALL.md`·`CLAUDE.md`(S-1~S-7 → S-0~S-7, 4,051B 그대로)·사람용 HTML의 단계 순서 문장. 사람용 HTML에 남은 옛 지표 이름("RIL 페어링" 등)은 고치지 않고 남김. `15-local-draft.md` §15.5 S-0 완료 기준은 "숫자(잴 수 없으면 `-`)"로 코드(`S0_VALUE_RE`)와 맞춤.
- `12-principles.md`에 "스킬 문서를 고쳤을 때 eval 범위" 항목 추가(사용자 확인 11/12): 판단 규칙(어느 층·유형으로 답할지, 순서, 예외·우선순위, 근거로 삼을 것)을 바꾸면 고친 스킬·모듈의 eval만(추정 비용을 보이고 승인 뒤), 문구·표기·오타만 또는 placeholder를 실제 값으로 이름만 바꿨으면 pytest로 갈음, 애매하면 돌림, 건너뛴 것은 건너뛰었다고 보고. 이슈 DB·사내 값은 eval 대상 아님, 재반입 때 사내 대상 eval 범위는 `SITE_INSTALL.md` 8절. `site_step.py` MS-2 안내에 "그 이름이 판단 조건에 쓰이면 이름만 바꾼 것이 아니다" 단서.
- 독립 리뷰(Opus, 읽기 전용): P0 없음, P1 2건(남은 "S-0(선택)" 표기, 사내 첫 방문 안내 묶음 30KB) 반영, P2 가운데 값 검사 강화·키 이름(`cov` → `clock`)·회귀 테스트·"사내 전용 파일" 문구 반영. 반영분 재리뷰 P0·P1 없음.
- WSL 전체 pytest: 4151 passed, 26 skipped, 3 xfailed(rebase 전 `6032f447` 기준, rebase 뒤 재실행은 따로).

## 11/12 밤

- #102(S-0 첫 단계·스킬 문서 eval 범위)·#103(채점기 한도) 병합.
- 채점기 한도 조사: 계약은 가설당 근거 1~5줄인데 채점기는 3줄까지만 받아 4줄 이상이면 형식 실패였다. 5로 맞추고 `GRADER_VERSION` 8. 재채점 pass1 with: sim 3→4, modem 2→4. ims·ofono는 run 폴더가 없어 못 함.
- sms 정책 변경(#104): 서비스 없음 → 프레임워크이던 것을 call에 맞춰 요청 미생성을 `SS=1·2`(모뎀·망)와 `SS=3`(끈 쪽)으로 나눔. 리뷰에서 `SS=3` 구분이 나옴. `sms-smsc-missing` case는 에뮬레이터 캡처로 다시 만들고 sms eval은 tie(with 2·without 2, 1회 그대로 기록).
- 소스 프로필 자동 저장: 직접 입력한 소스 경로를 버전과 함께 개인 `code_profiles`에 저장. 브랜치 개념 없이 도구는 가리킨 경로를 그대로 읽는다. GUIDE에 설정 절 추가.
- 미룸 H(탐색 `--also`)·I(심층 분석 단계) 추가, G에 Jira 버전 문구 패턴 보탬(`99-deferred.md`).
- 사용자 결정(11/12): 프로필 저장은 묻지 않는다. sms case는 캡처로 만든다.

## 11/13 반입 준비 (DRAFT_NOTES에서 옮김)

DRAFT_NOTES "진행 상태 (11/12)"에서 옮긴 줄(원문):
- 다음 묶음 이름은 **태그 찍는 날짜** `import-YYYYMMDD`(`import-20261109`·`b` 있음, 태그·반입은 사용자). 사내: 재반입 §8. 이번 묶음은 guard 판정이 바뀌었다(병합 계열·규칙 5 ask 전환, Approve·기각·자동 병합·보호 변경·refs 위조 deny 신설) — 반입 전 `s4a.protection_guard` 통과 전제. SITE_INSTALL §8대로 사내 대상 eval 12개(`pending.json` `site`) 전부 다시 돌린다.
- 11/10~12 병합 #85~#104: #90~#98 마스킹·Android 17 문구·관문·훑기, #99·#100 Android case 보강·추가(data 6·sim 4·network 3·call 4·sms 3·ims 3·modem 4), #101 모듈 문서 보완, #102 S-0를 `site_step.py` 첫 단계로·스킬 문서 eval 범위 원칙, #103 모듈 eval 채점기 가설당 근거 상한을 계약 1~5줄에 맞춤(`GRADER_VERSION` 8, 5개 모듈 재채점), #104 android sms(요청 미생성을 `SS=1·2` 모뎀·망/`SS=3` 끈 쪽으로 나눔, case 캡처로 재작성, eval tie). 직접 입력한 소스 경로를 버전과 함께 개인 `code_profiles`에 자동 저장.
- 재채점 못 한 모듈 eval: android ims, ofono 전부(run 폴더가 사외 PC에 없음). grader 7·3으로 남아 한 arm만 합치려면 재실행 필요.
- 11/12 가상 사용자 리허설 13건 실패 0(history).
- 템플릿·fixture는 placeholder·합성(사내 값은 SITE_PATHS, 반입 전 SITE_RESTORE ⓪), 반입은 `stable`에서 (Android eval은 arm pin 갱신으로 두 arm 함께 재실행)

DRAFT_NOTES "다음 사이클 후보 (11/09 사용자 목록, 확정 계획 아님)"(원문):
C 지표 자리 · 4-c 2차(guard 판정 축소 후속) · B 조건부 · F3 B/C(`mask_pii --check` 갈린 ICCID) · 4-c P2 6건 · D① P2 · 묶기·전구간 부정(S37 뒤 별도 설계) · 분석 전용 종료 표식 · 포트 변조 잔여(끝 `.`·`키: 값`) · A17: extractor 2·좁힌 태그·data 문서 보충·sms 문서 P2 2 · eval 42 allow-cause 경로 표시 · 11/12 리허설 P2 3 · network case(태그 추가 확인 필요) · 훑기 남은 것 · eval 형식 실패 · 그 밖 P2는 history 11/12

11/12~13 병합: #105 GUIDE 설정 절·미룸 H·I, #106 직접 입력 소스 경로를 개인 프로필로 자동 저장, #107 oFono 모듈 case·문서 placeholder 1:1 치환(1차), #108 시험 파일 실행 비트, #109 벤더 HAL serial(`ril.py`), #110 `offline_eval` 표본내 키 대조, #111 `14-site.md` S13 확인 방법, #112 PR 본문 메모 마스킹(`db_summary.py`), #113 이슈 DB 경로 방어(`dbpr/worktree.py`·`db_verify.py`). `import-20261109` 묶음은 사내에 반입되지 않아 다음 묶음 `import-20261113`의 재반입 노트는 `import-20261103` 이후 전부를 대상으로 한다. 11/13 종합 리뷰(사외 자료): 반입해 사내 보완을 이어 가도 된다, P0 0.

사용자 결정(11/13, 종합 리뷰 뒤 — DRAFT_NOTES 결정 (w)의 전체):
- D-02 재반입 때 표시 보조 글만 바뀐 경우는 영향받는 eval만 다시 돌린다(`SITE_INSTALL.md` §8). guard 고침은 다음 guard 묶음 하나로 모은다.
- D-04 oFono에 남은 규칙·DB 결합 문구와 잡음 줄은 사내에서 실제 값으로 되돌릴 때 같이 한다(지금 안 함, oFono eval 재측정 없음).
- D-05 guard는 실수 방지 장치로 본다. Approve는 토큰 권한 범위로 닫는다.
- D-07 첫 파일럿은 Android만. oFono 도구·파서 보완은 파일럿 뒤.
- D-08 안내서(book)는 스냅샷, 정본은 TEAM_GUIDE.
- D-09 사내 마켓플레이스는 태그·SHA 고정(`SITE_INSTALL.md` §8 "6. 배포").
- D-10 S1 빈 플러그인 실험에 3항목(MCP 오류 결과의 hook 경로, `onFailure: "block"`, 권한 모드별 ask 창)과 Read hook 입력(`99-deferred.md` E)을 더한다(`tests/mocks/plugin-probe/README.md` 18~21). 확인되면 guard 항목에 `onFailure: "block"`을 켠다.
- D-12 스킬 문서 바이트 한도는 흐름 합계 한도 하나 + 파일별 여유로 재설계(파일럿 뒤). D-13 출처를 댈 수 없는 주석 번호는 지운다(파일럿 뒤). D-14 OpenCode·"사내 처음부터" 모드·개발 문서 정리는 사내 확인 결과 뒤. D-15 guard 셸 문법 강화는 여기서 멈춘다, eval 건너뛰는 규칙·사내 eval 추가는 두지 않는다.
- network case용 태그 2개는 추가하지 않는다. 타임라인 200줄 상한은 파일럿에서 센다(잘림은 `timeline.md` 머리 `줄: 고른 수/전체 수`와 결과 JSON에 이미 남는다).
- 사내 점검표 파일은 레포 밖 별도 파일로 같이 가져간다(레포에 넣지 않는다).
- D-01 이슈 DB 경로 방어(#113)를 이번 묶음에 싣는다.
- D-03 거부 목록 파일은 레포 밖에 둔다. 점검표는 레포 밖 별도 파일로 같이 가져간다. 11/09 묶음은 반입되지 않았다.
- D-06 이슈 DB: 병합 때 fixed 유지와 상태 불변 `fixed_in` 추가를 둘 다 한다.
- D-11 모듈 문서·샘플 DB 사실 정정은 전부 하고 eval까지 돌린다. data의 `NOT_IN_SERVICE` 거부는 모뎀·망 층으로.

DRAFT_NOTES 결정에서 옮긴 것(원문, 사외 진행 규칙):
- (s) 테스트는 수정마다 관련만, 전체는 묶음 끝·eval·반입 직전(10/15).
- (p) 수정 절차(10/14, 11/08): 재확인·설계 = Fable 메인, 구현+시험 = Opus, 리뷰 = 별개 Opus → P0·P1은 그 단계에서 고치고 테스트 → 통과 뒤 커밋.
- (r) 고칠 범위(10/15, 사용자): 리뷰·재측정에서 **P0·P1(안전 위반·기능 결함)만** 고치고 P2는 "반입 뒤 후보"에 적는다. 질문 순서·횟수 행은 안전 행이 아니다(쓰기 순서 행은 안전 행).
- (i) eval은 변경과 관련된 최소만 사외에서 돌린다(바꾼 스킬·흐름의 eval만). 사내 S-2는 사내 대상만(결정 (q)). (10/07, 사용자) 단, 실행 방식·공통 지침이 바뀌면 전체 + 사람 판정(10/14).
