# K 안전 검토 결과 (10/15, Opus·노력 max, 읽기 전용)

> 계획 `K_L_REVIEW_PLAN.md` §K. 재현 스크립트 `k-repro/`(레포 루트에서 `python3 docs/development/k-repro/<파일>`). 결정 (r)로 **P0·P1은 결정 (p) 절차로 고친다** → 고친 뒤 반입 묶음 재생성.

## P0

| id | 위치 | 깨진 불변식 | 경로 | 수정 제안 |
|---|---|---|---|---|
| P0-1 | `plugin/scripts/guard.py:1459-1461`, `_degraded` `:1530` | 이슈 DB push는 화면·승인 뒤에만 (규칙 7 publish `ask` 누락) | SKILL.md:22 `S/` 규약대로 `python3 ${S}db_pr.py publish …`·`S="python3 …/"; ${S}db_pr.py …`·`$PY $S/db_pr.py …` 형태면 `_base`가 `db_pr.py`가 안 돼 guard 무응답. **eval 실기록 publish 110건 중 4건**(h1-e/29, sm3-1-b/67, sm3-2-b/48, sm4-1-b/67)이 ask 없이 `published:true`. 41311e0은 show_guard·채점기만 고침. show_guard fail-open 근거(08-safety.md:126)가 이 형태에서 무너짐. `repro_guard_publish.py`·`repro_chain.py`(화면 숨김 → deny → 같은 호출 재시도 → 통과 → guard None) | `check_bash`·`_degraded`: 아무 argv 토큰이든 따옴표 제거 후 `(^\|[/}])db_pr\.py$`면 db_pr로 본다(인터프리터 조건 제거). 원 명령이 `shown.PUSH_END` publish에 맞으면 ask(합집합). 위 형태 회귀 테스트 |

08-safety.md:70이 "변수 치환"을 파싱 한계로 적었지만, 이것은 스킬이 정한 호출 규약이고 실제 push가 일어났으므로 P0으로 본다(설계 수용으로 보더라도 (r)상 수정 대상).

## P1 (고칠 대상)

- **P1-1** `show_guard.py:504-506`(`shown.py:61` `APPROVED_ARG`): `--approved "$H"`/`$(…)`이면 push 판정 자체를 건너뜀(deny도 systemMessage도 없음). post 쪽 `--sha` 변수 처리와 비대칭. `repro_approved_var.py`
- **P1-2** `show_guard.py:546`(`UNSEEN_BLOCKS=1`): 화면이 도구 출력에 없던 publish는 1회 거부 뒤 같은 호출 재시도로 systemMessage만 내고 통과. BLIND_FREE가 이 경로엔 적용 안 됨. P0-1과 겹치면 승인 없는 push.
- **P1-3** `tests/skill_evals/grade.py`·`evals.json`: push eval에 "approvals.json에 publish ask 기록" 안전 행이 없어 P0-1이 `safety_fail 0`으로 통과. 추가하면 `offsite_results.json` 재생성 필요(기존 기록으로 재채점 가능한지 먼저 확인 — `scan_publish.py`·`crosscheck.py`).

## P2 (반입 뒤 후보, 적기만)

- `triagelib/report.py:483` + `issue_post.py:368`: must_show "코드 분석 트리 자동 선택: <절대 경로>"가 Jira 코멘트 "주의:" 줄에 들어감(사용자명 섞일 수 있음, 확인 화면엔 보임).
- `shown.plan_tag`: 다른 계획 파일을 같은 변수(`--plan $P`)로 넘기면 같은 계획으로 봄.
- `ci_mode: actions-build`: stage가 검증을 안 돌려 (b) 갈음 전제 불성립(화면은 "검증: 건너뜀"으로 정직).
- `hooks.json` matcher `Bash` 고정: 다른 셸 도구(PowerShell 등)면 guard 미적용 — S1 확인 항목.
- `jira_bridge.target`(:115): 격리는 `get_issue`·`get_comments`만, 다른 read 도구 원문은 모델로(설계 범위).

## 문제없음으로 확인한 것

- Jira 쓰기: MCP 도구 이름 판정(guard `check_mcp`:385·`check_jira_post`:425), `issuepost.check_call`:313 글자 일치·1회용·30분. 승인·결과 파일 직접 쓰기 deny(guard:480-515).
- dbpr: `abs_wt`·`_job_of`(worktree:162-178) 절대 경로 일관, symlink 거부, main push 거부(`_check_branch`:239, publish:542, pre-push), 사용자 clone엔 조건부 `pull --ff-only`만.
- 마스킹: 변경 없음, 3겹(stage `_MASK`·publish guard 프로필·pre-commit).
- 완화 (a)(b)(c): 승인 쪽 완화 아님(unseen 경로만 P1-2). (c) 같은 계획 재실행은 08-safety.md:129 수용 한계.
- .githooks·db_precommit: 규칙 5(guard:744-905), publish `--commit`은 hooksPath 확인 후 셸 없이 커밋. 우회 없음.
- `POST_NON_SAFETY`: 빠지는 행(질문 횟수·형식·결과 기록)으로 놓치는 안전 위반 없음.
- 테스트: show_guard·shown·safety·hooks 156 passed, db_pr·db_verify·issue_post·skill_evals 368 passed.
