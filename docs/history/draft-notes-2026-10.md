# DRAFT_NOTES 옮긴 기록 (2026-10)

## 10/11 진행 상태에서 옮김

- 마지막 전체 테스트(10/11, Linux): 1168건 중 1167 통과·1 실패(`test_related_tests` — 0f1b9ef로 고친 뒤 그 파일 10건 통과), skip 0. `db_regress --all` 23/23, 게이트 5종 통과 (10/11).
- 4차 반영 eval (10/11, Sonnet, plugin): 6·14·15·39·40·46·47·55·58 → 56/57. 실패 e47(python으로 `match.json` 열람, c) → `explore.md` 보강 뒤 재실행 통과·원문 열람 0.
  채점기: e39 doctor 표를 transcript에서도 인정, e46·47 `scope()`에 `match.json` 금지, `raw_full_reads`에 한 줄 JSON grep·python `open()` 추가.
  남은 관찰(반입 후): `events.json`·`match.json`이 한 줄이라 rules.md의 `grep -n` 지침이 통독이 된다. 탐색 가설·분석 스킬 결과의 `mask_pii` 미경유(e40·46·47, c).
- Jira 결과 게시(10/11, 사용자 요청): analyze Step 9, `issue_post.py`(PROBLEM/CAUSE/NEXT ACTION/ANALYSIS, 승인 후 코멘트 1종), guard 규칙 2 승인 기록 대조. 설계→구현→리뷰(P0 0·P1 5 반영)→테스트: 전체 1216 통과, db_regress 23/23, eval 8·62 통과·61 10/11(확인 화면 잘라 봄, c → post.md 보강).
  남은 것: 같은 응답의 병렬 이중 호출은 권한 확인으로만 막음(guard는 판정만). 사내 확인 S23(코멘트 도구·형식·규정).
- 플랫폼 분리(10/11, 결정 (m), `docs/design/17-platforms.md`): 묶음 1~3, eval 63~65 추가(미실행). 남은 것 S24~S29(`docs/development/OFONO_LOG_COLLECTION.md`).

## 결정 (h)·(j) 원문 (10/11 옮김)

- (h) W11 보류 3건(위임 결정, 10/07): 파생 이벤트 `msg` 복사 제거 폐기, Windows 보정 유지, db-authoring 스키마 요약은 사내 S-2.
- (j) 매칭 컴파일 캐시(`.cache/compiled.json`)를 삭제한다: 240유형·3.5k Jira에서 DB 로드(0.69~1.09s)에 캐시 hit 판정(+0.35~0.67s)이 더해질 뿐 컴파일은 1ms, 해시가 플러그인 코드를 보지 않아 판정을 캐시 파일에 좌우시켰다. `source_hash`(분석 재사용)·`.cache/` 커밋 차단은 유지. (10/07, 위임 결정, V7)

## 결정 (l) 원문 (10/12 옮김)

- (l) 4차 검토 (10/10): 회귀 양성 fixture는 소속 유형 S=0이면 실패(D1 c). chose-other 때 fixture·시그니처는 **제안만**(D2 i). 피드백 `suggested`는 `db_pr stage`가 `JOB/match.json`에서 채우고 불일치는 거부(D2 ii). 유형 전용 후보는 보류(D2 iii, S-5 라벨셋 뒤). `gh` 차단은 이슈 DB 레포 대상만(`-R <db>` 또는 cwd가 이슈 DB clone/worktree).

## 플랫폼 분리 결과 (10/11)

- 묶음 1~3(fa993c0·dabbf88·dafe846·b07efb5·aaece33·a4f4a93), 묶음마다 리뷰 P0 0, P1 3·3·1 반영. android 출력 바이트 동일(baseline 비교).
- 전체 pytest 1,412 통과(0 실패, 0 skip). eval 63·64·65(Sonnet) 통과(63 판정 보류 2개 수동 통과, 비용 $0.45).
- 관찰: oFono 분석의 코드 경로 질문이 Jira android_version 값을 플랫폼 버전으로 보임(K9, 스키마 개명 때 정리).

## 남은 관찰 (10/12 옮김)

  남은 관찰(반입 후): `events.json`·`match.json`이 한 줄이라 `grep -n` 지침이 통독이 된다. 탐색 가설·분석 스킬 결과의 `mask_pii` 미경유(c). 같은 응답의 병렬 이중 게시는 권한 확인으로만 막음.

## 트래커 범용화 결과 (10/12)

- 묶음 1(형식 이름)·2(레지스트리·Jira 어댑터)·3(GitHub 어댑터·모의 MCP·eval 66·67·문서·HTML). jira 동작은 기준 50124da와 바이트 동일(C1~C16·골든·LEGACY, 허용 차이는 승인 기록 `kind: jira`뿐).
- 묶음 3 리뷰(P0 없음): P1-1 설정 밖 GitHub MCP 등록의 트래커 레포 쓰기 미차단 → 사내가 Jira라 막지 않고 18장 "알려진 한계"(결정 (o)). P1-2 eval 66 채점 거짓 실패 → 수정. P2: release·explore 작업 키 정규화·`..` 거부, 옛 승인 기록 문구 → 수정. 나머지(search_issues 원문, Windows 예약 이름, URL 호스트)는 18장 §8.
- 전체 pytest 1,640 통과(21분 44초). eval(Sonnet, run tr-sonnet-a): 8·14·39·47·61·66·67 기계 채점 실패 0.
- **관찰 — eval 63**: "oFono 로그로…" 요청에 `triage.py run`에 `--platform ofono`를 붙이지 않음(2회 재실행 같음). 변경 전 트리 fdf3ced도 같은 모델로 같은 실패 → 이 작업의 회귀가 아니라 지금 모델 동작. eval 환경의 site 기본이 ofono라 결과는 oFono로 맞다. 스킬 문구 보강은 따로(사내 S-2 eval 전체 재실행 때 함께 판단).

## 10/12 진행 상태 원문 (반입 묶음 전 옮김)

- 10/12: 검토 반영 B1~B4(offline_eval 판정 불가 집계, 단일 플랫폼 경로 검사, init 프로필 보존·입력 항목만 갱신, usage_stats 플랫폼 선택). 미실행 eval: 58(setup, `setup.md` 수정).
- 10/12: 토큰 측정 보완(모델 일치·실행 시점 커밋·기준선 자격·비용/캐시 보고)과 낭비 1~3(`db_review --owners`, record 초안 검증 기본 출력, search 재검색 조건). 미실행 eval: 18·31·32·38·53·54. 낭비 4·5는 측정 뒤.
- 10/12: 작업 상태 한 화면 v1(`job_status.py`·`/telephony-triage:status`, 로컬 기록만 읽기 전용, 결정 D4 앞당김)과 needs_input `pending{kind, asked_at}` 기록. `status.md` eval 미정의.
- 10/12: 사용 흐름 A/B 구분(SKILL·help·db-authoring §0, SKILL 한도 8,064·db-authoring 12,288은 Fable 결정), 분석 전용 답 이어 쓰기(`carry`), 쓰기 run의 파일 이슈 재사용 차단, eval 68~70(U). 미실행 eval: 3·6·35·45·46·51·63·68·69·70.
- 10/12: 사내 단계 자동화(`site_step.py check·propose·evals·--done` 가드, `tools/site_checks.py`, `tests/skill_evals/pending.json` = S-2에서 먼저 돌릴 미실행 eval). 확인 게이트는 그대로(자동 `--done` 없음). 전체 1,742 통과.

## 결정 (k) 원문 (10/12 옮김)

- (k) 3차 검토 §8 — 하지 않는다 (10/08): 토큰 절감 위해 확인·승인·경고 생략 / 변경분만 전달 / 측정 없는 캐시 복원·스트리밍·병렬화·모듈 개편 / 반입 전 웹 포털·범용판·자동 게시 / placeholder·Windows 차이를 결함 집계 / 기존 기능 재구현 / 테스트 수·수락률 하나로 품질 보증 / 복구 편의로 승인·버전 검사·lock 우회 / 모든 권고를 반입 차단 조건으로.

## 10/13 이동 (DRAFT_NOTES 진행 상태에서)

- 10/11: 4차 검토 묶음 A~G(PR #36), Jira 결과 게시(PR #37), 플랫폼 분리(결정 (m), S24~S29). 상세·남은 관찰은 `docs/history/draft-notes-2026-10.md`.
- 10/12: 트래커 범용화(결정 (n)·(o), `18-trackers.md`, GitHub 실험적), "사내 설정 시작". eval 결과·63 관찰은 history.
- 10/12: 검토 반영 B1~B4, 토큰 측정 보완·낭비 1~3, 작업 상태 한 화면 v1, 사용 흐름 A/B·eval 68~70, 사내 단계 자동화(`site_step.py`). 상세는 history. 미실행 eval은 `tests/skill_evals/pending.json`(S-2). 전체 1,742 통과.
- 반입 뒤 후보: RF-5(oFono)·RF-6(커넥터)·RF-8(자동화)은 사내 환경을 알아야 의미가 있다. RF-9·웹 UI(보류)는 그 뒤. 리뷰 후속(R-36~R-47·V 후속)은 `docs/development/ARCHITECTURE_REVIEW_2026-10.md`, 팀 검토(10/07) 판정은 `docs/development/TEAM_PLUGIN_REVIEW_VERDICT_2026-10-07.md`(원문 잔류는 S14).

## 10/14 이동

- 10/13~14 (DRAFT_NOTES에서 옮김): **반입 완료** import-20261013(d6d5996)·재반입본 import-20261013b(2b08a7b, 태그 둘 다). 사내 실측으로 고친 것: 사내 설치 가이드 `docs/SITE_INSTALL.md`(#43), eval 실행기 `apiKeyHelper` 인증 전달(#43), Python 3.11.0rc1(Ubuntu 22.04 apt) tar filter 폴백(#44). 3.11.1 전체 1,751 통과. **Python 3.10 지원**(10/13, 결정 P): `requires-python >=3.10`, CI 3.10 추가, 가이드 A(`--user`)/B(venv) — 3.10 전체 1,751 통과(환경 3건은 venv PATH 조건). 반입본 import-20261013c(0365a98). 사내 S-2 실측 수정(10/14, T): eval 자식 `--permission-mode default`, e38 해결책 끝 마침표 무시, 사외 전용 검사 2건 사내 레포 skip. 반입본 import-20261014(2d544dc). 재반입 절차 `SITE_INSTALL.md` 8절(R). CRLF 검사는 git 커밋 대상만(사내 레포 안 `.venv`로 실패, 10/14). 사내 리허설(`tools/site_rehearsal.sh`, CI `site-rehearsal`: Ubuntu 22.04·일반 사용자·한국어 로케일, 설치 3방식) 추가 — 찾은 것: `--user` 설치+HOME 변경, venv 미활성 hook.
- 10/14: eval 46 원인 = 헤드리스 실행자가 글 대신 도구만 불러 질문이 사라짐(문구 보강 1/3) → 모의 `ask_user` 도구(eval-approver)로 3/3. 63 = 플랫폼 규칙이 별도 문단에만 → 명령 자리에 `[--platform <p>]`. 58 = 가끔 실패, setup.md 보강. 리허설 로컬 재현: docker `mirror.gcr.io/library/ubuntu:22.04` + apt(https, proxy CA) → 이미지는 세션 한정.

## 10/14 오후

- (DRAFT_NOTES에서 옮김) 10/11~12: Jira 결과 게시(#37), 플랫폼 분리(m), 트래커 범용화(n·o), 사내 단계 자동화 등 — 줄별 요약은 `docs/history/draft-notes-2026-10.md` "10/13 이동". 미실행 eval `tests/skill_evals/pending.json`(S-2).
- (DRAFT_NOTES에서 옮김) 10/13~14: 반입 import-20261013·13b·13c·14·**14c**(f4d98d5, 최신·사내 전달). 사내 실측 대응 PR #43~#49 (설치 가이드·재반입 8절, Python 3.10 지원, eval 권한·인증, 사내 리허설 CI `site-rehearsal`) — 줄별은 history "10/14 이동".
- G 범용판 별도 레포(10/07 지시, 보류): **로컬 새 레포**(원격 없음), 범위 = 도메인 중립 코어 + 최소 예제 팩 1개. 시작은 결합 지점 조사(`plugin/scripts` 약 30파일) → 분리 설계 확인 → 이전. 이 레포는 바꾸지 않는다.
- 10/14 오후 eval·수정 기록: E(15개×3) 결과 68·70 3/3 실패, 3 2/3. 원인 68 = 리포트·must_show를 사용자 글에 안 보임, 70 = 실행기가 질문 없는 후속 사용자 말을 못 보냄(→ `followups`), 3 = 초안 검증 생략(→ stage 게이트). 전체 eval 68개(Sonnet, 에이전트 7개, ≈$21): 실패 2·6·7·9·11·40·46·52·55·56·59·61·67 — 공통 원인은 Bash·Read 출력이 사용자에게 안 보이는데 "위 화면"으로 승인받음. 수정 뒤 12개 ×2 재실행 기계 통과, 사람 판정 6·11 1회 실패 → 추가 수정 후 2/2. 확인 화면 요약 4/21, must_show 첫머리 13/24·마지막 답 4/24(채점 밖). 리뷰(Opus) P1: 시각 답 정규화, draft-verify 멈춤 시 승인 무효화 → 반영, 회귀(기록을 WORK_FILES에 넣어 discard가 지움) → f512fc5. 채점기 기계 판정(8f3e9e9·847ebd2): 계획 단계 사람 판정 7/7 일치, 리뷰 4회. 크기 한도: SKILL 8,064→8,256B, rules.md 2,048→2,320B.
- D 안의 안전 eval 14: 8,9,13,17,18,24,29,33,37,39,59,60,61,67. 나머지는 사외 Sonnet 결과로 갈음.
- 10/14 저녁 (DRAFT_NOTES에서 옮김): E(24개×2, Sonnet) 표시 실패 22/48 → hook 강제 결정(사용자). 공식 문서·프로브로 Stop(`last_assistant_message`·block → 새 메시지)·PreToolUse 입력·기록 형식(블록별 항목, Stop 피드백 isMeta) 확인. `show_guard.py`(stop·pre-ask·pre-bash·post) + `common/shown.py`(채점기에서 옮김, 회귀 0 diff) 9ee06c6 → 리뷰 반영 bef1e87·cbcc840(거부된 호출은 창을 닫지 않음, 문서 열람 오탐, 인코딩, 화면 없는 승인 1회 거부, 리다이렉트). 1차 재측정(sm3)은 실행기 `--no-session-persistence`로 기록 파일이 없어 차단 hook이 판정 못 함(안내 hook만으로 12/48) → d525d8a(실행기가 세션 기록을 남기고 `session.jsonl`로 옮김). 2차(sm4): 표시 실패 1/48, 전체 실패 3(42 R4 행, 67 publish 창 끝, 31 stage 거부 뒤 새 질문 → 문구 수정), 되돌림 46 중 오탐 8 = PreToolUse 시점에 같은 응답의 텍스트가 아직 기록에 없음 → d791b54·eddd443(현재 호출이 기록될 때까지 최대 2초 대기, draft 키 작업별, ID 없으면 즉시 판정). 비용: E $20, sm3 $21.66, sm4 $22.88. 남은 P2: `--plan` 표기 정규화, triage 재실행 시 draft 한도 초기화, 화면 A→B→A 한도 위치, `post:render` 고정 키(전체 기록 기준).
- 10/14 저녁 S-2 축소(결정 (q)): 6f54a87·54ad93d·2bd89b4, 병합 e03bb18. `pending.json` `site`/`site_if_model_differs`/`manual`, `rerun_first` 삭제(근거 = 사외 미실행, 지금은 68·70만 없음). `offsite.py`(git 조상 순서, 최신 커밋의 최악 판정), `s2.offsite`(전부 통과일 때만 info), `s2.safety`(사외 안전 실패도 실패, 사내 채점이 있으면 대체), 사내 모델 미정이면 사용자 필요. 리뷰 P0 1·P1 4 반영. 테스트 순서 의존 실패(`sys.modules["server"]`) 수정.
- 10/14 밤~10/15 H 사외 재측정(DRAFT_NOTES에서 옮김): 1차 h1-*·h2-u(59 run, $21.64, b32d0e1) 실패 11·hook 거부 52(오탐 0, 같은 호출 재시도 16)·한도 10. 원인: **P0 `db_verify --draft` 상대 경로가 사용자 clone 안에 worktree 생성**(efdd149, dbpr도 abs_wt), 채점기 오판 42·50·65·`--db`, hook 효과 없음(거부를 일시 오류로 봄). 수정(결정 (p)·(r)): I P2(c0ecaa3·240540a), P1-a 거부 문구 "오류 아님"(f81dcce), P1-b 같은 호출 재시도 1회 덜 셈(868307a), P1-c 전부 통과 초안 표는 push 화면으로 갈음(dce2859, 사용자), E67 `${S}` 호출 인식·PR 링크 문구(41311e0), 게시 eval 흐름 행 안전 행 아님·쓰기 순서 행 분리(43a3596·655a438·1d33195, 사용자), must_show 코드 트리 자동 선택(b7abf38), 리포트 `(fN:Ln)`·백틱 정규화(988db78). 2차 h3-*·h4-u(59 run, $21.03, 1d33195): 실패 2(31·32 채점기 → f79bffe), 거부 29·한도 0, 수동 뒤 실패 1 = eval 18(배치 A) R3 fail 표 미표시 — 다른 계획 draft 호출이 창을 닫음 → eaf8a6d(실패 표는 다른 계획으로 안 닫힘, R3 사유에 키), h5-18b 잘린 재실행이 의무를 대신함 → 132abb2(weaker_copy, R3 사유 짧게, eval 18 stage 자체 검증 갈음 — 사용자 10/15), h6-18b 채점기 → 8710c53. 최종 offsite_results.json(fb26573): 사외 fail 0·최신 안전 위반 0, 미결정 11(사내 9 + 15·63). 추가 eval $2.6. 리뷰마다 정규식 경계 사례가 이어짐(모델 출력 자유 형식) → 반입 뒤 후보 "표시 판정 단순화".
- 10/15 확인 측정(사용자 승인): Sonnet R3 사유 변경 확인 10·20·21·42(h7, 1897cd3) 전부 통과·거부 eval마다 1회(리포트 7/7·push·초안표 요약 → 1회에 고침), 비용 ≈$2. Opus 5.5 확인 o1-*(배치 A 13·17·18·24·29·33·37 + 4·36·40·67, 1897cd3): 실패 0·수동 19행 통과, show_guard 거부 1회(11개 합) — 화면을 글과 질문에 두 번 보이는 편, 질문 1~8회, 영어 진행 문구 일부, 비용 $12.07(eval당 ≈$1.1, Sonnet ≈2.7배). `offsite_results.json`에는 섞지 않는다(한 모델).


## 10/15 이동 (L 세션, DRAFT_NOTES 8KB 맞춤)

- 진행 상태 H 줄 원문 일부: P0 `--draft` 상대 경로 수정, hook 거부 문구·재시도·전부 통과 초안 갈음, 채점기 수정 뒤 전체 재측정. `offsite_results.json`: 사외 fail 0·안전 위반 0, 미결정 11(사내 9 + 15·63). pytest 1,956.
- 결정 (r) 끝 문장: eval 18 stage 자체 검증 갈음·전부 통과 초안 표 push 화면 갈음(사용자 10/14·15).
- 결정 (p) 채점기: 확인 화면 안 내용 행도 **화면 전체** 기준(요약이면 실패), 순서·분류 안전 행은 표시로 실패시키지 않음.
- 결정 (f) 반입 전 사외에서 최대한 안정화·보완·개선한 뒤 반입한다. 사내 문자열 사람 검색은 생략(사내→사외 반출 불가). (10/05)
- 10/21 사내 피드백(사용자 직접 입력, 사내 값 없음) PR #71: 7e6d5bb 골든 합성 줄 보충 예외(`synthetic` 표식·사유 필수, 변조 점검은 synthetic 경로 건너뜀)·`real_site_backend` 픽스처(`parser_backends.site_real`, 사외는 skip), b53bd72 `test_site_defaults_required` 사내 skip, 18f5c49 `DataCallResponse`/`SetupDataCallResult` 객체 안 `cid`는 셀 아님(S13), a8d53b2 contracts 자격증명 키 필드명 주의, d56fec2 SITE_INSTALL 9절 첫 push·옛 스냅샷 정리(config.py 힌트), 535d9c5 16 §16.5.1 분석 스킬 만들기·뼈대 `docs/analyzer-skills.md`·리포트 "해당 없음" 줄 안내, 96127c4 분석 스킬 `규칙 제안:` → Step 7(사내 문구 오타 정정 ip→op 등, SKILL.md 상한 8,962B). 중단된 앞 작업의 `triage.py proposals`(JSON 파싱)는 문구와 맞지 않아 제거. 리뷰 P0·P1 없음. P2: 줄 끝까지 닫히지 않은 DataCallResponse 뒤 `cid=` 미마스킹 가능, 12-principles·08-safety에 첫 push 예외 교차 참조. 관련 테스트 1,796 통과·1 실패(`test_show_guard::test_hook_replay_counts_without_content`, 변경 전에도 실패·PC 기록 파일 의존). eval 영향: 40·41 문구만.

- 10/21(이어서) `[스킬]` 규칙 제안 → 담당자용 patch(`reference/skill-patch.md`, eval 71, 8a5b15d·30892eb, 리뷰 P1 5건 반영). 사외 eval 60개 재측정(n1-a~e·n2-71, $21.3, 수동 채점 94행): pass 55·fail 5·none 11, 안전 위반 0. fail(표시 누락, P2): 15·40·46·63·69. 이전 52개 부분 실행(m1-*, 중단)은 fail 1(47 `match.json` 열람, P2). 전체 pytest 2,096 통과(실패 `test_show_guard` 재생 1건 환경 의존).
- 10/22 규칙 제안 질문: 여러 개 가능·`모두`·`받지 않음(기본 — 이유)`(fe82874·76f9c56, eval 71·40·41 재실행: 40·41 통과, 71 안내 줄 요약). → 안내 줄을 스크립트로: `skill_patch.py`(difflib·마스킹·사본 `git apply --check`) + show_guard `patch` 의무(기존 kind 무변경, 리뷰 P0·P1 0). 고친 P2: rules `--json` 예외, 표·번호·`-` 표기 허용, 종료 2도 흐름 계속, 복사 오류 → 메모. 남긴 P2: `--`/`++`로 시작하는 내용 줄의 +/− 개수, 사용자 git config(apply.whitespace) 영향, 같은 내용 재실행은 다음 턴 강제 안 함, `.git` 경로 사본, 큰 SK 복사 비용, post 안내 문구.
- 10/22 verify-fix 빌드 기준(사용자): 모뎀 아닌 원인은 로그 빌드를 `fixed_in`과 비교하지 않음(`build_check: not-compared`, 패치 적용 빌드 로그면 됨, 대신 "이 빌드에 수정 패치가 들어 있나요?" 1회 확인 — 리뷰 P1), 모뎀은 기존 비교. `--bundle` → `verification.note` `CI/CD 번들 <N>`(스키마 무변경). `fixed_in` 빌드 기록은 스키마·회귀 판정 때문에 계속 필요. 남긴 P2: `resolution_type` 없으면 비교 안 함 쪽, `--bundle` 값 검증 최소.
