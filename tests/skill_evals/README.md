# telephony-triage 스킬 eval (Phase 13)

`docs/design/10-skill-eval.md`의 eval 54개와 트리거 테스트를 skill-creator 방식으로 돌리는 자료다.
스킬 본체는 `plugin/skills/telephony-triage/`.

| 파일 | 내용 |
|---|---|
| `evals.json` | eval 54개 모두 `prompt`·`setup`·`user_replies`·`assertions` 정의 완료. 1(대표 10), A(안전 10), B(analyze 11), C(수정·검증 9), D(record 5), E(10/04~05 기능 7), F(S6 2) |
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
`Ctx.invoked`는 `commands.md` 표의 설명 칸까지 섞이므로 긍정 확인(`in_cmd`)에만 쓰고, 부정 확인(e25 `no_judgement`·e26 `no_verify`)과
순서·존재 확인(e49 `paste`, e50 `both`·`order`)은 `Ctx.ran`(실행 기록)으로 판정한다 — 설명 문장 때문의 거짓 실패(3C)를 없앤다.
`grading.json`에는 채점 항목이 아닌 `metrics.raw_full_reads`가 붙는다: 원문 통독 의심 호출(env `logs/`·`*.log`·`*.zip`·`events.json`·
`jira_raw.json`에 대한 Bash `cat`/`head -c`/`less`/`strings`/`unzip -p`, `limit` 없는 `Read`). 실행 기록이 없으면 빈 목록이다.

**R4 응답 규칙(e10·e20·e21)**: 새 fixture에서 다른 유형 원인(IMS-001-01)도 걸려 시그니처 좁히기 / `allow-cause`를 물으면 실행자는
`allow-cause(허용) — 로그에 실제로 IMS 403이 있다`를 고른다. 시그니처를 좁힐지 허용할지는 사용자 선택이라(`docs/design/12-principles.md`)
규칙이 없으면 실행자가 임의로 골라 흐름이 갈린다. 세 eval의 채점은 `any()`라 추가 `allow-cause` 연산이 있어도 영향이 없다.
e41의 기본 응답 줄('아니오')은 굵은 '예' 규칙과 충돌해 지웠다.

`transcript.md`·`commands.md`가 없거나 비어 있으면 `not-run`, API 오류·시간 초과가 있으면 `incomplete`로 남기며
기대 항목을 통과로 세지 않는다. `passed: null` 항목은 대화 순서와 판정을 독립적으로 읽고 근거를 붙여 채점한다.
수동 채점(`source: manual`)은 재채점 시 보존하고, `source: script`는 현재 환경에서 다시 계산한다.
description에 대한 정적 리뷰는 실제 Claude 스킬 자동 선택 및 플러그인 로드 시험을 대신하지 않는다.
