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
