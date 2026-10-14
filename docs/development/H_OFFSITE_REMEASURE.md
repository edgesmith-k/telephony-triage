# H — 사외 재측정과 `offsite_results.json` 재생성 (실행 절차)

> 사외 초안 전용. 10/14 사용자가 범위를 승인했다("클리어 후 전부 진행"). 새 세션은 이 문서대로 H → I → F 준비까지 진행한다.
> 비용 승인: H 실행 ≈$24(Sonnet). 그 밖 eval 추가 실행은 $3 이내에서만, 넘으면 사용자에게 묻는다.

## 0. 시작 점검

- 브랜치 `ccr-d022623a-2f4vdx`, `git fetch` 후 최신. `pip install '.[test]'`(모듈 없으면).
- hook 반영 커밋 위에서 돈다(c4aa820 이후). `claude -p` 동작 확인: `timeout 60 claude -p "say ok" --model claude-sonnet-5-5 </dev/null`.

## 1. 실행 범위 (승인됨)

- 제외 13개: 사내 대상 11개(1, 2, 8, 9, 39, 45, 58, 59, 60, 61, 62 — 사내 S-2에서 다시 돈다), 검색 흐름 53·54(실패 이력 없음, hook 검사 대상 출력 없음).
- 실행 57개 ×1 + 68·70 한 번 더(사외 기록이 아직 없다). 결정 (i) 단서: hook은 공통 실행 방식 변경이라 이전 결과로 갈음하지 않는다.
- 5묶음 병렬(묶음당 ≈12개, 40~50분):

```
W=tests/skill_evals/workspace; L=$W/h-logs; mkdir -p $L
run() { nohup python3 tests/skill_evals/run.py --iteration $W/$1 --eval ${@:2} --execute --model claude-sonnet-5-5 </dev/null >$L/$1.log 2>&1 & }
run h1-a 3 10 15 20 25 30 35 41 47 52 64 69
run h1-b 4 11 16 21 26 31 36 42 48 55 65 70
run h1-c 5 12 17 22 27 32 37 43 49 56 66
run h1-d 6 13 18 23 28 33 38 44 50 57 67
run h1-e 7 14 19 24 29 34 40 46 51 63 68
run h2-u 68 70
```

- 기다리기: `run_in_background` 대기 명령은 중간에 끊길 수 있다. 끊기면 `grep -c '^eval [0-9]*:' $L/*.log`로 진행을 보고 다시 건다. sleep 연쇄 금지.
- 각 실행은 `session.jsonl`을 남긴다(`execution.json` `session_transcript`). null이면 show_guard가 판정하지 못한 실행이다 — 원인부터 본다.

## 2. 채점

```
python3 tests/skill_evals/grade.py $W/h1-a $W/h1-b $W/h1-c $W/h1-d $W/h1-e $W/h2-u > $L/grade.txt
```

- 실패 행은 근거(evidence)로 분류: 화면 요약(빠진 줄·보인 행 없음) / hook 때문에 바뀐 흐름(eval 31 같은 새 질문) / 기능 결함 / 채점기 오판.
- `metrics.show_guard`(blocks·denies·capped) 합계를 본다. 의심스러운 차단은 그 실행의 `session.jsonl`에 hook을 다시 돌려 정당/오탐을 가린다(10/14 저녁 방식, history).
- 결함·오탐을 고칠 때는 결정 (p): 계획 → 수정 → 리뷰(P0·P1이면 다시) → 테스트 뒤 커밋. 고친 eval만 다시 돌린다($3 이내).

## 3. 수동 채점 (미결정 행)

- `passed: null` 행은 transcript(`events.jsonl`·`session.jsonl`)를 읽고 `grading.json`의 그 행에 `passed`·`evidence`·`"source": "manual"`을 쓴다(재채점해도 보존된다, README "수동 채점").
- 대상: 이번 실행분 전부. 실행하지 않은 53·54는 기존 최신 실행(full-g5)의 미결정 행을 같은 방식으로 채점해도 된다.
- 판단이 애매한 행은 통과로 두지 않고 미결정으로 남긴다(원칙: 건너뛴 검증을 통과로 표시하지 않는다).

## 4. 기록 재생성

```
python3 tests/skill_evals/offsite.py $W/<사외 iteration 전부: full-g1..g7 re-* re2-* sm* sm3-* sm4-* h1-* h2-u> \
  --out tests/skill_evals/offsite_results.json --note "hook(show_guard) 반영 재측정 10/1x"
```

- 판정은 iteration마다 가장 새 커밋의 실행들 중 최악이라, 옛 실행을 함께 넣어도 새 실행이 판정을 정한다. 한 모델(sonnet-5-5)만 넣는다(섞이면 종료 2).
- 확인: `s2.safety`(eval 37 표시 행 실패가 사라졌는지), `s2.offsite`의 실패·미결정 목록. 남는 실패는 원인을 DRAFT_NOTES에 적는다.
- `python3 tools/related_tests.py --run`(`test_offsite`의 재계산 테스트 포함) 통과 뒤 커밋·push.

## 5. 이어서

- I(show_guard 남은 P2 4건, history "10/14 저녁") — 결정 (p) 절차.
- DRAFT_NOTES 갱신(H·I ☑, 결과 한 줄, 상세는 history).
- F 준비: main 병합 PR을 만든다(PR 템플릿 확인). **병합·반입 묶음(`make_bundle.py`)은 사용자 확인 뒤**.
