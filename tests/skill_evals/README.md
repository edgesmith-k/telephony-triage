# telephony-triage 스킬 eval (Phase 13)

`docs/design/10-skill-eval.md`의 eval 45개와 트리거 테스트를 skill-creator 방식으로 돌리는 자료다.
스킬 본체는 `plugin/skills/telephony-triage/`.

| 파일 | 내용 |
|---|---|
| `evals.json` | eval 45개 모두 `prompt`·`setup`·`user_replies`·`assertions` 정의 완료. 1(대표 10), A(안전 10), B(analyze 11), C(수정·검증 9), D(record 5) |
| `trigger_evals.json` | description 트리거 테스트 (`10-skill-eval.md` 표 + near-miss) |
| `jira/` | eval용 모의 Jira 티켓 (`MOCK-90xx`, `tests/mocks/jira`와 같은 형식) |
| `scenarios/` | eval용 합성 logcat 시나리오 (`tests/mocks/logcat_gen.py` 형식) |
| `plans/`, `fixtures/` | 미리 올려 둔 PR(eval 16)의 계획과 fixture(`e016-apn-cut.log`, 합성) |
| `workspace/` | 실행 결과 (커밋하지 않음, `.gitignore`) |
| `run.py` | 새 격리 환경을 준비하고 Claude Code로 평가 실행. 기존 반복 폴더는 덮어쓰지 않음 |
| `trigger_real.py` | 실제 플러그인(`--plugin-dir`)을 불러와 `trigger_evals.json`의 트리거를 잰다. skill-creator `run_eval`(첫 도구 호출만 셈)보다 실제에 가깝다 |
| `grade.py` | 기계 채점과 수동 채점 보존. 미실행·API 오류를 통과로 세지 않음 |

**정의 완료와 행동 평가 통과는 다르다.** 실행·수동 채점 상태는 `DRAFT_NOTES.md`(상태 파일)와 `docs/history/draft-notes-2026-09.md`의 Phase 13 기록을 따른다.

## 반복 실행

```sh
# API 호출 없이 환경 생성 확인
python3 tests/skill_evals/run.py --iteration tests/skill_evals/workspace/prepare-new --eval 3 4 38 --prepare-only
# 로그인된 Claude Code의 기본 모델로 독립 세션 실행
python3 tests/skill_evals/run.py --iteration tests/skill_evals/workspace/run-new --eval 3 4 38 --execute
python3 tests/skill_evals/grade.py tests/skill_evals/workspace/run-new --eval 3 4 38
```

CLI는 PATH에 있어야 한다. 실행자에게 기대 답과 assertions를 전달하지 않고, 모의 Jira·Git 원격·gh 스텁만 사용한다.
`--execute`는 Claude API를 사용하며 한도·인증 오류나 시간 초과에서 배치를 멈춘다. 결과는 `execution.json`과
`events.jsonl`에 남는다. 한도를 만난 뒤 자동 반복하지 말고 사용 가능해진 뒤 **새 반복 경로**로 재개한다.
Windows 개발 PC에서는 Python과 Git Bash를 PATH에 두고 UTF-8 모드를 사용한다. 배포 대상은 Ubuntu다.

## 환경 만들기

```sh
python3 tests/helpers/skill_eval_env.py <eval id> --out tests/skill_evals/workspace/iteration-<N>/env-<id>
```

eval마다 독립된 플러그인 루트(테스트 헬퍼, `site-defaults.example.yaml` 복사본), 사용자 홈·config, 모의 원격 + 사용자 clone,
gh 스텁 상태, Jira 티켓 디렉토리, 로그를 만든다. `env.sh`(export), `env.json`(경로), `before.json`(사용자 clone 상태)이 생긴다.

## 평가 환경의 제약 (실제와 다른 점)

- 서브에이전트 세션에는 모의 Jira MCP가 등록돼 있지 않다. 그래서 `mcp__mock-jira__<tool>` 호출을
  `python3 tests/mocks/jira_mcp/call.py <tool> '<JSON>'`으로 대신한다. `jira.tools` 매핑을 거쳐 도구 이름을 고르는 것은 같다.
- 분석 스킬 `mock-data-analyzer`는 스킬로 부르지 않고 `python3 tests/mocks/skills/data-analyzer/run.py --input <json>`으로 부른다.
- 사용자 대화는 `user_replies` 규칙으로 흉내 낸다. 실제 사용자 확인 대기는 없다.
- guard hook(PreToolUse)은 서브에이전트에 걸리지 않는다. 쓰기 도구 호출 여부는 `MOCK_JIRA_WRITE_LOG` 파일로 본다.

## 서브에이전트 실행 프롬프트 (with-skill)

```
너는 telephony-triage 스킬을 시험하는 평가 실행자다. 실제 사용자는 없다.

- 스킬: <env.json의 skill>/SKILL.md 를 먼저 읽고 그대로 따른다(필요한 reference만 읽는다).
- 환경: <env 디렉토리>/env.json 을 읽는다. Bash 호출마다 맨 앞에 `source '<env 디렉토리>/env.sh' && cd '<env 디렉토리>' && `를 붙인다
  (셸 상태가 유지되지 않는다). 스크립트는 "$CLAUDE_PLUGIN_ROOT/scripts/<이름>.py"로 부른다. 로그 경로 logs/…는 env 디렉토리 기준이다.
- Jira MCP 대신: env.json의 jira_call 명령. 분석 스킬 대신: env.json의 analyzer_run 명령.
- 사용자 요청(첫 메시지): <prompt>
- 시뮬레이션 사용자 응답 규칙: <user_replies>
- 레포 파일(plugin/, docs/, tests/ 등)을 고치지 않는다. env 디렉토리 밖에 쓰지 않는다.
- 산출물(<run 디렉토리>/outputs/):
  - transcript.md: 사용자에게 보여준 모든 메시지(리포트, 질문, 확인 화면)와 시뮬레이션 사용자 응답을 순서대로 **그대로** 적는다.
  - commands.md: 실행한 모든 명령(순서대로, 종료 코드와 한 줄 요약).
  - notes.md: 스킬 지시가 모호하거나 막힌 곳, 스킬에 없어서 스스로 정한 것.
  - 작업 계획이 생겼으면 plan.json 사본.
```

## 채점

`python3 tests/skill_evals/grade.py <iteration 디렉토리> [--eval <id> ...]`가 기계적으로 확인할 수 있는 항목(원격 브랜치·파일,
gh PR, lock, 사용자 clone 상태, 원문 PII 노출, Jira 쓰기 도구 호출)을 채점하고, 나머지는 transcript를 읽고 채점한다.
결과는 `grading.json`(`expectations[{text, passed, evidence}]`) — skill-creator viewer 형식.

`transcript.md`·`commands.md`가 없거나 비어 있으면 `not-run`, API 오류·시간 초과가 있으면 `incomplete`로 남기며
기대 항목을 통과로 세지 않는다. `passed: null` 항목은 대화 순서와 판정을 독립적으로 읽고 근거를 붙여 채점한다.
수동 채점(`source: manual`)은 재채점 시 보존하고, `source: script`는 현재 환경에서 다시 계산한다.
description에 대한 정적 리뷰는 실제 Claude 스킬 자동 선택 및 플러그인 로드 시험을 대신하지 않는다.
