# telephony-triage 스킬 eval (Phase 13)

`evals.json`의 eval 전체(정의 근거 `docs/design/10-skill-eval.md`)와 트리거 테스트를 skill-creator 방식으로 돌리는 자료다.
스킬 본체는 `plugin/skills/telephony-triage/`.

| 파일 | 내용 |
|---|---|
| `evals.json` | eval 58개 모두 `prompt`·`setup`·`user_replies`·`assertions` 정의 완료. 1(대표 10), A(안전 10), B(analyze 11), C(수정·검증 9), D(record 5), E(10/04~05 기능 7), F(S6 2), W(W4 질문 수 줄이기 3: 55 코드 프로필 자동 선택, 56 다른 작업 잔여 알림만, 57 심층·탐색 한쪽 사전 결정), W9(58 setup 재점검의 doctor 표). eval 39는 doctor 표 단언 포함 |
| `trigger_evals.json` | description 트리거 테스트 (`10-skill-eval.md` 표 + near-miss) |
| `jira/` | eval용 모의 Jira 티켓 (`MOCK-90xx`, `tests/mocks/jira`와 같은 형식) |
| `scenarios/` | eval용 합성 logcat 시나리오 (`tests/mocks/logcat_gen.py` 형식) |
| `plans/`, `fixtures/` | 미리 올려 둔 PR(eval 16)의 계획과 fixture(`e016-apn-cut.log`, 합성) |
| `workspace/` | 실행 결과 (커밋하지 않음, `.gitignore`) |
| `run.py` | 새 격리 환경을 준비하고 Claude Code로 평가 실행(기본 `--mode plugin`: 실제 플러그인·모의 Jira MCP·hook). 기존 반복 폴더는 덮어쓰지 않음 |
| `trigger_real.py` | 실제 플러그인(`--plugin-dir`)을 불러와 `trigger_evals.json`의 트리거를 잰다. skill-creator `run_eval`(첫 도구 호출만 셈)보다 실제에 가깝다 |
| `grade.py` | 기계 채점과 수동 채점 보존. 미실행·API 오류를 통과로 세지 않음 |

**정의 완료와 행동 평가 통과는 다르다.** 실행·수동 채점 상태는 `DRAFT_NOTES.md`(상태 파일)와 `docs/history/draft-notes-2026-09.md`의 Phase 13 기록을 따른다.

## 반복 실행

```sh
# API 호출 없이 환경 생성 확인
python3 tests/skill_evals/run.py --iteration tests/skill_evals/workspace/prepare-new --eval 3 4 38 --prepare-only
# 로그인된 Claude Code의 기본 모델로 독립 세션 실행
python3 tests/skill_evals/run.py --iteration tests/skill_evals/workspace/run-new --eval 3 4 38 --execute
python3 tests/skill_evals/grade.py tests/skill_evals/workspace/run-new --eval 3 4 38 --token-budget
```

CLI는 PATH에 있어야 한다. 실행자에게 기대 답과 assertions를 전달하지 않고, 모의 Jira·Git 원격·gh 스텁만 사용한다.
`--execute`는 Claude API를 사용하며 한도·인증 오류나 시간 초과에서 배치를 멈춘다. 결과는 `execution.json`과
`events.jsonl`에 남는다. 한도를 만난 뒤 자동 반복하지 말고 사용 가능해진 뒤 **새 반복 경로**로 재개한다.
Windows 개발 PC에서는 Python과 Git Bash를 PATH에 두고 UTF-8 모드를 사용한다. 배포 대상은 Ubuntu다.

실행자 결과 파일(`transcript.md`·`commands.md`·`notes.md`)은 규칙에서 `<run>/outputs/…` 절대 경로로 알려 준다(실행자의 작업 디렉토리는 `env-N`이라 상대 경로를
잘못 쓴 적이 있다). 그래도 빠진 파일은 실행 기록(`events.jsonl`)에서 만든 대체본(첫 줄 `<!-- run.py: 실행자 미작성, events.jsonl에서 생성 -->`:
transcript = assistant 텍스트, commands = Bash 명령 표와 오류 여부, notes = 고정 문구)으로 채우고 `execution.json`의 `outputs_derived`에 이름을 남긴다.
이 경우 상태는 `error`가 아니라 `completed`다. 자식 `claude -p`는 부모 원격 세션의 정체성 환경 변수(`CLAUDE_CODE_SESSION_ID`·`CLAUDE_CODE_REMOTE*`·
`CLAUDE_CODE_CONTAINER_ID`·`TRACEPARENT` 등, `execution.json`의 `env_stripped`)를 받지 않고 `--settings`로 커밋·PR 서명(`Co-Authored-By`·세션 URL)을 끈다.

## 환경 만들기

`setup`의 선택 키는 `tests/helpers/skill_eval_env.py` 머리말에 정리돼 있다. `leftovers: [{job, branch?}]`는 다른 작업 키가 남긴
도구 worktree(`<work_dir>/<job>/wt`)와 도구 브랜치(기본 `tt/<job>`)를 사용자 clone에 만든다(eval 56). `before.json`은 그 뒤에 찍는다.

```sh
python3 tests/helpers/skill_eval_env.py <eval id> --out tests/skill_evals/workspace/iteration-<N>/env-<id>
```

eval마다 독립된 플러그인 루트(테스트 헬퍼, `site-defaults.example.yaml` 복사본), 사용자 홈·config, 모의 원격 + 사용자 clone,
gh 스텁 상태, Jira 티켓 디렉토리, 로그를 만든다. `env.sh`(export), `env.json`(경로), `before.json`(사용자 clone 상태)이 생긴다.

## 실행 모드

`run.py --mode plugin`(기본)은 `claude -p --plugin-dir <테스트 헬퍼 플러그인 루트> --plugin-dir <env>/mock-plugins/mock-analyzers
--mcp-config <env>/mcp.json`으로 **설치된 플러그인처럼** 돌린다. 사용자 요청 원문이 첫 메시지라 `/telephony-triage:…` 커맨드,
스킬 자동 선택, hook(SessionStart·guard·jira_bridge)이 실제로 동작한다. 실행자 규칙(사용자 응답 시뮬레이션·결과 파일)은
`--append-system-prompt`로만 준다. `execution.json`의 `plugin`에 로딩된 플러그인·MCP 상태·Skill/MCP 호출·hook 횟수·차단한 hook이
남는다. 플러그인이 안 붙었거나 `mock-jira`가 연결되지 않으면 행동 실패가 아니라 `error`(환경)다.

| | plugin (기본) | direct (예전) |
|---|---|---|
| 스킬 진입 | 커맨드·`Skill` 자동 선택 | 실행자가 SKILL.md 직접 Read |
| Jira | 모의 MCP 서버 `mock-jira`(비표준 도구 이름) → jira_bridge hook이 원문 격리 | `call.py`를 Bash로 |
| 분석 스킬 | 모의 플러그인 스킬 `mock-analyzers:mock-data-analyzer` | `run.py`를 Bash로 |
| guard hook | 걸린다(MCP·Bash·Write/Edit) | 안 걸린다 |
| MCP 권한 | 서버 단위 허용 — Jira 쓰기 차단은 권한 거부가 아니라 guard가 해야 통과 | — |
| Bash의 `CLAUDE_PLUGIN_ROOT` | 없음(실제 설치와 같게, `env.sh` 끝에서 unset) — 스킬·커맨드 본문의 `S/` 경로를 써야 한다 | 있음(프롬프트가 이 변수를 쓴다) |

**plugin 모드 환경 정보**: `env.json`에는 direct 모드용 키(`jira_call`·`jira_tools_list`·`analyzer_run`)를 넣지 않는다(`run.py`가
`build(direct_tools=False)`로 부른다). 3C의 e40·e41은 실행자가 `env.json`을 보고 분석 스크립트를 Bash로 직접 돌려 Skill 경로(5-1)를
실제로 시험하지 못했다. 그래서 e40·e41의 스크립트 판정(계획 항목)은 `execution.json`의 `plugin.skill_calls`(중첩된 `plugin.seen`도 허용)에
`mock-analyzers:mock-data-analyzer`가 있을 때만 통과로 센다(direct 모드·기록 없음은 이 조건 생략). 헬퍼 CLI(`skill_eval_env.py`)의 기본값은 그대로다.

**남은 차이**(두 모드 공통): 사용자 대화는 `user_replies` 규칙으로 흉내 낸다. 테스트 헬퍼 플러그인 루트는 `site-defaults.example.yaml`
(모의 Jira 도구 매핑)을 쓴다. 분석 스킬 이름은 설정의 `mock-data-analyzer`이고 실제 스킬은 플러그인 접두사가 붙는다(사내 분석 스킬도
설치 방식에 따라 같을 수 있다). 쓰기 도구 호출 여부는 `MOCK_JIRA_WRITE_LOG`로도 본다.

사내(S-2)에서 바꿀 것은 없다. CLI가 `--plugin-dir`·`stream-json` init 이벤트(`plugins`·`mcp_servers`)를 지원하지 않는 옛 버전이면
`--mode direct`로 돌리고 그 사실을 결과에 적는다.

## 채점

`python3 tests/skill_evals/grade.py <iteration 디렉토리> [--eval <id> ...]`가 기계적으로 확인할 수 있는 항목(원격 브랜치·파일,
gh PR, lock, 사용자 clone 상태, 원문 PII 노출, Jira 쓰기 도구 호출)을 채점하고, 나머지는 transcript를 읽고 채점한다.
결과는 `grading.json`(`expectations[{text, passed, evidence}]`) — skill-creator viewer 형식.
"무엇을 실행했나" 판정은 실행 기록(`events.jsonl`의 Bash 명령·MCP 도구 호출 + 드라이버 `trace.jsonl`)으로 한다. 실행자가 쓴
`commands.md`는 기록이 없는 옛 결과에서만 대신 쓴다(R13).
`Ctx.needs_input(kind)`는 `JOB/trace.jsonl`의 `needs_input` 줄로 드라이버 질문 횟수를 센다(기록 없으면 `None` → 수동 채점, 0회로 세지 않음). `Ctx.texts()`는 assistant 텍스트 조각이다(55~57).
`Ctx.invoked`는 `commands.md` 표의 설명 칸까지 섞이므로 긍정 확인(`in_cmd`)에만 쓰고, 부정 확인(e25 `no_judgement`·e26 `no_verify`)과
순서·존재 확인(e49 `paste`, e50 `both`·`order`)은 `Ctx.ran`(실행 기록)으로 판정한다 — 설명 문장 때문의 거짓 실패(3C)를 없앤다.
`grading.json`에는 채점 항목이 아닌 `tokens`(실행 기록의 토큰, 미실행이면 `null`)가 항상 붙는다("토큰 기록").
`grading.json`에는 채점 항목이 아닌 `metrics.raw_full_reads`가 붙는다: 원문 통독 의심 호출(env `logs/`·`*.log`·`*.zip`·`events.json`·
`jira_raw.json`에 대한 Bash `cat`/`head -c`/`less`/`strings`/`unzip -p`, `limit` 없는 `Read`). 실행 기록이 없으면 빈 목록이다.
`metrics.raw_reads_blocked`는 guard 규칙 10(`08-safety.md §9`)이 거부한 같은 종류의 시도다: `tool_use.id`와 짝이 되는 `tool_result`가
오류이고 `[telephony-triage]`를 담은 호출은 `raw_full_reads`에서 빼고 여기에 센다(읽지 못했으므로 통독이 아니다). 다른 오류는 그대로 센다.
e46·e47 `scope()`는 `timeline.md` 첫 열람이 `triage.py explore` Bash 호출 뒤여야 통과한다. e46 1번은 그 호출 앞 assistant 텍스트에
'탐색 분석'과 '할까요'(또는 '실행할까'·'진행할까')가 함께 있어야 통과하고, 실행 기록이 없으면 수동 채점으로 남는다.

**R4 응답 규칙(e10·e20·e21)**: 새 fixture에서 다른 유형 원인(IMS-001-01)도 걸려 시그니처 좁히기 / `allow-cause`를 물으면 실행자는
`allow-cause(허용) — 로그에 실제로 IMS 403이 있다`를 고른다. 시그니처를 좁힐지 허용할지는 사용자 선택이라(`docs/design/12-principles.md`)
규칙이 없으면 실행자가 임의로 골라 흐름이 갈린다. 세 eval의 채점은 `any()`라 추가 `allow-cause` 연산이 있어도 영향이 없다.
e41의 기본 응답 줄('아니오')은 굵은 '예' 규칙과 충돌해 지웠다.

`transcript.md`·`commands.md`가 없거나 비어 있으면 `not-run`, API 오류·시간 초과가 있으면 `incomplete`로 남기며
기대 항목을 통과로 세지 않는다. `passed: null` 항목은 대화 순서와 판정을 독립적으로 읽고 근거를 붙여 채점한다.
수동 채점(`source: manual`)은 재채점 시 보존하고, `source: script`는 현재 환경에서 다시 계산한다.
description에 대한 정적 리뷰는 실제 Claude 스킬 자동 선택 및 플러그인 로드 시험을 대신하지 않는다.

## 토큰 기록

`run.py --execute`는 stream-json `result` 이벤트에서 토큰을 읽어 `execution.json`의 `tokens`에 남긴다(기존 `usage`·`total_cost_usd`는 그대로, `model`은 `--model` 값 또는 `null`).
`prepare-only`는 `tokens`가 없다(표에서 "미실행"). 시간 초과 등 result가 없으면 값이 모두 `null`이다.

```
tokens: {input, output, cache_creation, cache_read, total,   # modelUsage 모델별 값의 합
         usage_total,                                        # result.usage 네 값의 합(비교용)
         num_turns, duration_ms, total_cost_usd,
         by_model: {<모델>: {input, output, cache_creation, cache_read, total, cost_usd}},
         source: "modelUsage" | null}
```

- **total은 modelUsage 합이다.** 서브에이전트·보조 모델 호출까지 들어가므로 상위 `usage`(주 대화만 셀 수 있다)보다 크거나 같다. 둘의 차이를 보도록 표에 `usage_total` 열을 둔다. W0 실측에서 상위 `usage`에는 주 모델(Sonnet)만 들어 있었고, 차이는 Claude Code가 부르는 보조 Haiku 호출(eval당 약 950토큰, 0.1% 이하)이었다. 보조 호출도 사용량이므로 total은 modelUsage 합을 쓴다.
  옛 `execution.json`(modelUsage 없음)은 `usage_total`만 채우고 `total`은 `null`이다. `total`을 `usage_total`로 대신하지 않는다.
- 정수가 아닌 값·빠진 키는 `null`이고 0으로 채우지 않는다. 합은 구성 값이 하나라도 `null`이면 `null`이다. 표에서 `null`은 "미기록", 실행하지 않은(없음·prepared) eval은 "미실행"이다.
- 이벤트 로그(`events.jsonl`)를 합산한 하한값은 만들지 않는다(후속).

`grade.py`는 iteration마다 eval별 표(`eval | status | input | cache_create | cache_read | output | total | usage_total | turns | cost | 상한 | 판정`)를 출력하고
같은 내용을 `<iteration>/tokens.json`(작업 폴더, 커밋 대상 아님)에 쓴다. 기준선 없음 → "기준선 없음", `--token-budget` 없음 → "-".

### 상한 판정

```sh
python3 tests/skill_evals/grade.py <iteration> --eval 1 2 45 --token-budget [PATH] [--token-margin 1.3]
```

- `--token-budget`은 `token_baseline.json`(PATH 생략 시 `tests/skill_evals/token_baseline.json`)을 읽어 eval마다 상한 = 기준선 `total` × 여유율(올림)로 판정한다. 숫자를 직접 받지 않는다. 반복 경로 뒤에 둔다.
- 기준선에 그 eval이 있으면 채점 항목 "토큰 총합 ≤ 상한(기준선 × 여유율)"(source `script`, 근거에 실제 값·상한)이 하나 늘고, 초과는 실패, `total`이 `null`이면 판정 보류(`passed: null`)다. 기준선에 없으면 항목을 만들지 않는다. 기준선에 있어도 실행하지 않은(미실행) eval에는 판정 항목을 만들지 않고 종료 코드에 영향이 없다(표에 "미실행"). 통과가 아니다. 중단(incomplete)된 run은 상한 항목만 결정되면 `summary`에 반영하고 나머지는 미결정 그대로다.
- 여유율: `--token-margin` > 기준선 파일의 `margin_default` > 코드 상수 `DEFAULT_TOKEN_MARGIN`. 지금 값은 1.3이다. 근거(W0 실측, `claude-sonnet-5-5`, 10/06): eval 1을 3회 돌려 총합 680,589~743,146(최소 대비 폭 9%, 턴 20~22). 기준선 대표값은 최댓값이므로 1.3은 관측 폭의 약 3배 여유다. eval 2·45는 1회씩이라 편차를 재지 않았다. 표본이 적어 넉넉히 잡았고, 오판정이 잦으면 run을 늘려 기준선을 다시 쓴다.
- 종료 코드: 판정 항목 가운데 초과 또는 미기록이 하나라도 있으면 1, 기준선 파일이 없거나 JSON·형식 오류이면 2(메시지 출력). `--token-budget`이 없으면 채점 결과·종료 코드가 이전과 같다.

### 기준선

```sh
python3 tests/skill_evals/grade.py <iteration>... --eval 1 2 45 --write-baseline tests/skill_evals/token_baseline.json
```

기준선은 같은 모델로 잰 `--execute` iteration(여러 개 가능)에서 만든다. eval마다 `total`이 기록된 run을 모아 `runs`에 남기고 **대표값은 `total`이 가장 큰 run**이다(상한 판정이 보수적).
모델은 `execution.json`의 `model`(`--model` 값) → `init_model`(stream-json init 이벤트) 순으로 정하고 모든 run이 같은 하나여야 한다. `by_model` 키로는 추정하지 않는다(보조 모델이 항상 섞인다). 기준선 실측은 `--model`에 전체 모델 ID(예: claude-sonnet-5-5)를 준다. 별칭이면 기록도 별칭이다.
`total`이 `null`인 run은 빠진 수를 출력하고 제외한다. 이미 있는 파일은 이번에 재지 않은 eval과 `margin_default`·`margin_basis`를 유지한다.

`--write-baseline`은 측정된 eval이 없거나, 모델을 정할 수 없거나, 기존 파일과 모델이 다르거나, 기존 파일이 깨졌으면 파일을 쓰지 않고 종료 코드 2다.

```
{"model", "date", "commit", "dirty", "margin_default", "margin_basis",
 "evals": {"<id>": {"total", "num_turns", "total_cost_usd", "runs": [{"total", "num_turns", "total_cost_usd"}, ...]}}}
```
