# 사내 도입 가이드: 실행 환경 셋 (Claude Code + Claude / Claude Code + 사내 모델 / OpenCode + 사내 모델)

대상: 묶음을 반입하고 팀원에게 어느 환경을 언제 열지 정하는 **도입 담당자**. 기준 `b4a5b42`(11/07 반입 묶음), 근거 `docs/development/RUNTIMES.md`·`opencode/README.md`·`docs/SITE_INSTALL.md`.

- 이 문서의 기능은 모두 이번 묶음에 들어 있다(11/06 G 확인). 이름·옵션이 다르면 `--help`가 맞다.
- `<GHE 호스트>`·`<게이트웨이 URL>`·`<사내 모델 이름>`·`<Jira MCP 서버 이름>`은 사내 값으로 바꾸고 `SITE_PROFILE.md`·`SITE_PATHS` 경로에만 적는다.
- 사내 단계는 **스크립트(토큰 0)가 먼저**. 모델 호출은 환경마다 짧은 확인과 상한을 둔 측정뿐이다.

## 0. 한눈에

| | Claude Code + Claude | Claude Code + 사내 모델 | OpenCode 1.19.5 + 사내 모델 |
|---|---|---|---|
| 겉모습 | `/telephony-triage:*`, 말로 요청 | 같음(모델만 게이트웨이로) | `tt-oc` 래퍼 + `/tt-*` |
| 분석 | 됨 | 됨 | 됨 — v1은 **분석 전용** |
| 쓰기(push·PR·`db_pr merge`·Jira 코멘트) | 확인 화면 → 승인 뒤 | 같음 | **안 함.** 명령을 출력 → 사용자가 터미널·Claude Code에서 실행 |
| Jira 읽기 | Jira MCP | 같음 | **닫힘이 기본.** 사용자마다 사내 확인 뒤 직접 연다(3.4). 코멘트는 늘 막힘 |
| 안전 장치 | guard·git hook·show_guard | 같음 | `tt-guard.js` → `oc_adapter` → 같은 `guard.py` + 허용 목록 |
| 확인 화면·must_show | show_guard 판정 | 같음 — **세션 기록을 켜야** 판정 | 래퍼가 모델을 거치지 않고 출력(TUI는 보장 없음) |
| 설치 스킬·module_eval | 됨 | 됨(`--no-require-cost`) | 스킬만 됨 |
| 비용 | 보고됨 | **미상**(토큰만) | 토큰만(`cost:0`≠0원) |

## 1. 전제

1. `SITE_INSTALL.md` 1~5절이 끝났고 S 단계(`python3 tools/site_step.py`)를 진행 중이거나 마쳤다. S 단계와 정기 점검 리뷰는 **Claude Code + Claude**로 한다.
2. `claude`·`opencode`가 부르는 `python3`가 3.10+이고 PyYAML·jsonschema를 import한다(`SITE_INSTALL.md` 5·6절).
3. 도입 담당자 계정으로 `<게이트웨이 URL>`의 `<사내 모델 이름>`을 부를 수 있다. Claude Code는 게이트웨이가 Anthropic 모양 `/v1/messages`(스트리밍 `tool_use`)를 내야 된다(사내 확인 0). OpenCode는 같은 게이트웨이의 OpenAI 호환(`…/v1`) 엔드포인트가 필요하다.
4. OpenCode 1.19.5 배포와 `/etc/opencode/` 관리 설정(관리자). 다른 버전이면 `tt-oc`가 시작하지 않는다.
5. **OpenCode 파일은 `plugin/` 밖이다**(`opencode/`, `tools/`) — 마켓플레이스 설치에 없다. 배포는 **레포 읽기 전용 clone 하나**로 한다(3.1 0). 반입 묶음의 레포 zip에도 `opencode/`가 들어 있다(`test_make_bundle.py`가 고정).
6. 확인 실행에는 **마스킹된 로그만** 쓴다(site eval 로그나 `SITE_PATHS`의 마스킹본).

## 2. Claude Code + 사내 모델

플러그인·hook·guard는 그대로다. 한도(출력 16K·문맥 202K)와 약한 모델 위험은 OpenCode와 같고, 안전은 스크립트가 지킨다.

### 2.1 환경 프로필 — 어디에 무엇을

**사용자 `~/.claude/settings.json`의 `env` 블록**에 둔다. 셸 export도 자식에 그대로 간다. `module_eval` 자식은 `--setting-sources ""`로 떠서 settings.json을 읽지 않지만, settings.json `env`에 두면 `common/claude_child.py`가 골라 넘긴다. 팀 안내는 한 곳(settings.json)으로 통일한다.

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "<게이트웨이 URL(/v1 앞까지)>",
    "ANTHROPIC_MODEL": "<사내 모델 이름>",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "<사내 모델 이름>",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "<사내 모델 이름>",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "<사내 모델 이름>",
    "CLAUDE_CODE_SUBAGENT_MODEL": "<사내 모델 이름>",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
    "CLAUDE_CODE_EFFORT_LEVEL": "unset",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  }
}
```

- 자격: `ANTHROPIC_AUTH_TOKEN`(Bearer)·`ANTHROPIC_API_KEY`(`x-api-key`)·`apiKeyHelper` 중 하나(사내 확인 2). 키 값은 공유 파일·문서에 적지 않는다.
- `CLAUDE_CODE_DISABLE_THINKING=1`은 게이트웨이가 `thinking`을 거부할 때만. 모델 ID는 모두 같게(보조 호출이 새지 않게).
- 관리 설정으로 팀에 깔 수 있는지는 사내 Claude Code 공식 문서로.

### 2.2 프로필 점검 (토큰 0)

```sh
python3 tools/site_step.py runtime-check claude-gateway
```

- 판정은 `claude_child.gateway_profile_check`(비밀 값은 표에 없음). missing·differs면 종료 1. 프로세스 환경·사용자 settings.json·관리 설정(`managed-settings.json`과 `managed-settings.d/*.json`)의 `env`를 본다(본 곳은 `env_sources` 행 — 레지스트리·MDM·서버 관리 설정은 안 본다. 관리 설정 폴더는 `TT_CLAUDE_MANAGED_DIR`로 바꿀 수 있다 — 시험이 개발 PC의 관리 설정을 읽지 않게 쓴다). `ANTHROPIC_MODEL`이 있으면 `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`·`CLAUDE_CODE_SUBAGENT_MODEL`이 그 값과 같아야 한다(없으면 missing, 다르면 differs — 보조 호출이 `claude-*` ID로 간다). `ANTHROPIC_BASE_URL` 끝이 `/v1`이면 differs(`/v1/v1/messages`가 된다). 끝에 사내 확인 0 curl을 보인다(실행 안 함).
- 토큰 0 추가 행(`site_step.gateway_site_rows`, 종료 코드 무관): `claude_cli`(`claude --version` — 시험한 판 `claude_child.CLAUDE_CLI_TESTED`(2.1.318)과 다르면 warn, 사내 확인 5로 hook·show_guard를 다시 본다), `plugin_hooks`(사용자 config `plugin.scripts_path`의 설치본 `hooks/hooks.json`과 matcher 수 — 실제 로드는 사내 확인 5), `isolation_confirmed`(site-defaults `tracker.isolation_confirmed`, S1 기록). 이 점검이 **안 재는 것**: 게이트웨이 프로토콜·모델 응답·hook 동작·must_show — 아래 사내 확인이 확정한다.
- 자격(`ANTHROPIC_AUTH_TOKEN` 또는 `ANTHROPIC_API_KEY`, 또는 `apiKeyHelper`)이 없으면 `credential` 행이 missing이다. 위 예시에 자격을 더한다.
- `CLAUDE_CODE_EFFORT_LEVEL`은 없거나 비었거나 `"unset"`이면 ok(권장 값이 "두지 않음").

### 2.3 사내 확인 (번호는 `RUNTIMES.md §6`, 남은 것 0·2·3·5)

결과(첫 오류 줄, 키 빼고)는 `SITE_PROFILE.md`에.

| 번호 | 무엇 | 실행 | 통과 |
|---|---|---|---|
| 0 | 프로토콜 | 2.2 출력의 curl 둘(`max_tokens:128`, 도구 강제·자동 선택) | 둘 다 `content_block_start`에 `"type":"tool_use"` → `input_json_delta` → `message_stop`. 자동 선택에서 도구 호출이 글로만 나오면 실패(에이전트가 스크립트를 못 돌린다) |
| 2 | 호환 | 아래 curl 넷 + `claude -p` 1회(Bash 1회 강제) | 자격 헤더 하나 이상 200, `thinking` 수용(거부면 `DISABLE_THINKING=1`), 틀린 요청에 JSON 오류, CLI가 400 없이 끝나고 `result`에 `tt-check`·`num_turns` 2 이상(도구를 실제로 불렀다) |
| 3 | `usage` 토큰 | 같은 `claude -p` 출력 | 입력·출력 토큰 > 0. `costBasis: "unknown"`은 정상 |
| 5 | 큰 화면 그대로 | 대화형 `--dry-run` 1건 | 리포트·must_show 줄이 글자 그대로(되돌리면 다음 답에서 전문) |

```bash
GW=<게이트웨이 URL(/v1 앞까지)>; MODEL=<사내 모델 이름>; read -rs KEY   # 키는 입력만(셸 기록에 안 남음)
c() { curl -sS "$GW/v1/messages" -H "content-type: application/json" -H "anthropic-version: 2023-06-01" "$@" | head -c 400; echo; }
XK=(-H "x-api-key: $KEY"); BR=(-H "authorization: Bearer $KEY")
B='{"model":"'"$MODEL"'","max_tokens":16,"messages":[{"role":"user","content":"ok"}]}'
c "${XK[@]}" -d "$B"; c "${BR[@]}" -d "$B"   # 자격 헤더 둘
c "${XK[@]}" "${BR[@]}" -d '{"model":"'"$MODEL"'","max_tokens":2048,"thinking":{"type":"enabled","budget_tokens":1024},"messages":[{"role":"user","content":"ok"}]}'
c "${XK[@]}" "${BR[@]}" -d '{"model":"'"$MODEL"'","messages":[]}'   # 일부러 틀린 요청
(cd "$(mktemp -d)" && claude -p 'Bash 도구로 echo tt-check를 한 번 실행하고 그 출력만 답해' \
   --allowedTools 'Bash(echo:*)' --permission-mode default --output-format json)   # 빈 폴더: 레포 CLAUDE.md를 싣지 않음. 도구 호출 1회. 권한 모드를 명시(사내 기본 auto면 분류기가 허용 목록 Bash도 막는다 — claude_child.CHILD_PERMISSION_MODE)
```

사내 확인 5는 대화형 `claude`(세션 기록 켬)에서 `> /telephony-triage:analyze <KEY> <마스킹된 로그> --dry-run`(아무것도 올리지 않음). `-p`에 `--no-session-persistence`를 쓰면 show_guard가 판정하지 못한다.

### 2.4 모듈 문서를 이 모델로 재기 (상한 있음)

**터미널**에서, 비용 대신 run 수로 상한을 둔다. `--max-cost`는 주지 않는다(자리 표시 단가로 일찍 멈춤). `--record`도 쓰지 않는다 — 사외 `tests/skill_evals/module_offsite_results.json`을 고쳐 다음 재반입을 막는다. 사내 run을 지금 채점기로 다시 채점하는 `--regrade <반복 디렉토리>`는 자식을 띄우지 않아 $0이고 써도 된다(이때도 `--record`는 붙이지 않는다). 사내에서 고친 팀 모듈은 `--templates <모듈 레포 clone>`을 붙여 잰다(없으면 사외 판본).

```sh
python3 plugin/scripts/module_eval.py --module ofono/data --model <사내 모델 이름> --no-require-cost --no-max-cost --dry-run
python3 plugin/scripts/module_eval.py --module ofono/data --case data-apn-auth-reject \
    --model <사내 모델 이름> --no-require-cost --no-max-cost --json   # 1 case × 2 arm = 2 run
```

- 1줄째는 계획만(토큰 0). 2줄째가 통과하면 남은 case. `--bare`(입력 토큰 감소)는 `execution.json` `bare`가 `used`면 계속 쓴다.
- 판정은 스크립트다: with 1순위 통과 수 ≥ without, 안전 위반 0. 비용 행 `skipped`("비용 미상")는 통과가 아니다.
- 모듈은 oFono·Android 각 7개(data·sim·network·call·sms·ims·modem). 모듈 문서는 증상별 첫 점검 표·대체 근거(핵심 줄이 없을 때 볼 다른 층 줄)를 갖고, 데몬은 역할로 부른다(이름은 `_common/components.md` 역할 표 한 곳). 사내 모델로는 팀이 많이 쓰는 모듈 1~2개만 잰다.
- 탐색(explore) 사례는 후보 채점이다: 후보 1~3개 + `가장 유력`, 인정 후보가 목록에 있고 함정이 가장 유력이 아니면 통과(1순위 적중은 기록만). 심층(deep)은 결론 1개 그대로.

### 2.5 go / no-go

| go | no-go |
|---|---|
| `runtime-check claude-gateway` 종료 0 — **환경 변수·자격 이름·claude CLI·설치본 hooks·S1 기록만 잰다**(모델 응답·프로토콜·hook 실제 동작은 아래 사내 확인) | missing·differs 남음 |
| 사내 확인 0·2·3 통과 | OpenAI 모양만(0 실패) → 이 환경 보류 |
| 사내 확인 5에서 must_show 그대로 | 되돌림 뒤에도 요약 |
| 고른 모듈 with ≥ without, 안전 위반 0 | 안전 위반 1건이라도 |

go여도 쓰기 승인은 사람이 한다.

## 3. OpenCode + 같은 모델

v1은 분석 전용이다. 확인 화면·must_show가 있는 흐름은 **`tt-oc`로만** 돌린다.

### 3.1 설치

0. 레포 사본(도입 담당자가 한 번 정하고 팀에 공지): 사내 GHE의 telephony-triage 레포를 **마켓플레이스 플러그인과 같은 반입 태그**로 읽기 전용 clone — `git clone --depth 1 --branch <반입 태그> <사내 tt 레포> <사본>`. 같은 판 확인: `diff -rq -x __pycache__ <사본>/plugin/scripts <설치된 plugin>/scripts`가 빈 출력. 갱신은 `git fetch --depth 1 origin tag <새 태그> && git checkout <새 태그>` 뒤 3.5. 사본은 고치지 않는다(`install`이 커맨드·`tt-guard.js`를 여기서 복사하고 `tt-oc`도 여기서 돈다).
1. OpenCode 1.19.5 — 사내 경로가 없으면 npm 패키지 `opencode-ai` 버전 1.19.5를 전역 설치(`npm install -g`에 패키지 이름과 버전을 `이름@버전`으로).
2. 관리 설정(관리자) — `opencode/managed.json.sample`을 `/etc/opencode/opencode.json`으로. 더 막는 키는 더해도 된다.
3. 사용자별 설치 폴더 — git 레포·플러그인·이슈 DB clone 밖. setup(config)이 먼저다(`install`이 `config.py check --roots`로 읽기 폴더를 정한다).

```sh
python3 tools/gen_opencode.py install --dest <git 밖 폴더> --plugin-root <설치된 plugin/> \
    --work-root <작업 루트> --issue-db <이슈 DB clone> --gateway-url <게이트웨이 URL(/v1까지)> --model <사내 모델 이름>
export TT_GATEWAY_API_KEY=<게이트웨이 키>   # 설정 파일에는 쓰지 않는다
```

- 템플릿이 `snapshot:false`·`autoupdate:false`·`share:"disabled"`·한도·허용 목록(`"*":"deny"`)을 넣는다.
- `install`은 지문을 `tt-oc.json`에 남긴다. **설치 폴더 파일을 손으로 고치지 않는다**(시작 안 함).
- `<dest>`와 그 위 폴더(`/`까지)의 `AGENTS.md`·`CONTEXT.md`, 또는 `~/.config/opencode/AGENTS.md`가 있으면 시작하지 않는다.

### 3.2 점검 (토큰 0)

```sh
opencode/bin/tt-oc --project <dest> doctor
python3 tools/site_step.py runtime-check opencode --project <dest>
```

- 프록시·사내 CA: `tt-oc`는 환경을 지우지 않고 opencode에 넘긴다(`HTTPS_PROXY`·`NO_PROXY`·`NODE_EXTRA_CA_CERTS` 등, 거부하는 것은 `OPENCODE_*` 설정 덮기뿐). curl과 같은 셸에서 실행한다 — opencode가 그 변수로 게이트웨이에 닿는지는 3.3 첫 실행에서 본다(닿지 않으면 `no-response`).
- `tt-oc doctor` 행: `env`·`project-git`·`instructions`·`integrity`·`opencode-version`·`opencode-config`·`config-doctor`(개수만), warn `module-skills`·`read-roots`·`gateway-key`(opencode.json `apiKey`의 `{env:…}` 변수가 없거나 빔)·`gateway-url`(baseURL이 `…/v1`로 끝나지 않음, 게이트웨이 경로가 원래 다르면 무시)·`first-timeout`(`TT_OC_FIRST_TIMEOUT`이 0 이상의 유한한 초가 아님 — 실행은 종료 2). fail이면 종료 2.
- `runtime-check opencode`: 위 + 관리 설정(없으면 warn) + OpenCode용 사내 확인 0 curl(실행 안 함). fail이면 종료 1.
- 사내 확인 0(OpenCode)은 OpenAI 호환 모양이다: (a) 토큰 0 `GET <baseURL>/models`에 모델 ID가 있는지(정보 — 게이트웨이가 목록을 안 주면 404여도 된다. 설치 설정은 모델 ID를 `opencode.json` `models`에 고정한다), (b) 선택 `POST <baseURL>/chat/completions` 스트리밍 `tool_calls`(도구 강제), (c) 같은 요청의 자동 선택(`tool_choice: "auto"` — 실제 실행 모양, 도구 호출이 `content` 글로만 나오면 실패). 설치한 `opencode.json`의 baseURL·모델을 채워 보이고 키는 `$TT_GATEWAY_API_KEY` 이름만 쓴다.

### 3.3 에이전트 규칙 확인 (짧은 실행 1~2회)

3.4로 열기 전에는 Jira MCP가 막혀 있다(설정 `opencode.jira_read` 기본 closed, 템플릿 `"jira_*": "deny"`). 이슈 본문은 `--issue-file`로 준다(`--dry-run`·`--analysis-only`에서만).

```sh
opencode/bin/tt-oc --project <dest> --command tt-analyze -- <KEY> <마스킹된 로그> --issue-file <이슈 yaml> --dry-run
opencode/bin/tt-oc --project <dest> --command tt-analyze -- <KEY> <마스킹된 로그> --issue-file <이슈 yaml> --analysis-only   # 선택
```

- `--dry-run` 한 번으로 리포트와 확인 화면을 다 본다. lock owner는 환경 변수로 줄 수 없어(허용 목록이 대입을 거부) analyze 작업의 `db_pr`·`db_verify`가 작업 상태(`triage-state.json`)에서 읽는다. analyze 밖의 쓰기 흐름(`tt-record` 등)은 OpenCode에서 lock(`lock owner 불일치`)에서 멈춘다 — Claude Code에서 한다. tt-oc 옵션(`--delete-session`·`-s` 등)은 **`--` 앞에** 둔다 — 뒤에 두면 모델에게 가는 메시지가 된다.

- 종료 0(끝남)이나 3(막힌 호출 — 사용자 차례). 1·2·124면 그대로 보고한다. `tt-analyze`·`tt-record`가 스크립트를 한 번도 돌리지 않고(화면 기록도 없이) 끝나면 `outcome: no-script-output`·종료 1이다 — 도구 호출을 글로 내는 게이트웨이를 의심하고 3.2 사내 확인 0 (c)를 본다. 결과 줄의 `finish`가 `length`면 `outcome: length`(출력 한도 16000에서 잘림), 에이전트 `steps` 한도(50)에 닿으면 `step-limit` — 둘 다 종료 1. 토큰이 0이면 `주의:` 줄(사내 확인 3).
- 래퍼가 표시 기록(report·must_show·근거 검사 줄)을 그대로 출력한다.
- 막힌 호출은 `[telephony-triage]`·"run this exact command yourself: …"가 그대로 나오고, 모델이 다른 모양으로 재시도하지 않는다. 터미널로 넘기는 `db_pr`·`db_verify` 명령에는 tt-oc가 그 작업의 `triage-state.json` owner를 `TT_LOCK_OWNER=…`로 채운다(터미널에는 OpenCode 안의 작업 상태 대체가 없다. 모델이 돌리는 명령에는 넣지 않는다). 그 owner가 지금 그 작업이 쥔 `session.lock` owner와 같고, owner를 보는 하위 명령이며, 한 명령일 때만 채우고 줄 끝에 작업 키를 적는다. 아니면 `주의:` 줄로 owner 위치를 알린다.
- 질문은 번호 선택지로 끝난다 → `tt-oc --project <dest> -s <세션> -- <번호>`. 마지막 이어가기에 붙인다: `tt-oc --project <dest> -s <세션> --delete-session -- <번호>`(이어가기가 없으면 첫 실행의 `--` 앞에).

### 3.4 Jira 읽기 관문 열기

기본은 닫힘. "사내 확인 + 사용자 설정"으로 연다(결정 11/05). 확인은 사용자마다 한다 — 기록이 그 사용자 홈에 있고 MCP 설정도 사용자별이라서다.

1. 확인 실행 — **열려는 사람이 자기 PC에서**(레포 사본 `tools/` 필요). 기록은 그 사용자의 `~/.telephony-triage/opencode-jira-check.json`이고 `config.py set`은 그것만 본다. 모델 토큰 0: 가짜 모델 서버로 실제 opencode·`<Jira MCP 서버 이름>`을 거쳐 있는·없는 티켓을 읽고 원문 격리·마스킹·오류 경로를 본다.
   ```sh
   python3 tools/site_step.py runtime-check opencode --project <dest> --jira <있는 티켓 키> --missing-key <없는 티켓 키>
   ```
   전제: (a) 사용자 config에 `tracker.tools`(get_issue), (b) `<Jira MCP 서버 이름>`이 OpenCode가 합치는 설정의 `mcp`에(보통 `~/.config/opencode/opencode.json`. `<dest>/opencode.json`은 지문 대상이라 고치지 않는다).
2. 통과하면 **사용자가 터미널에서** 연다(OpenCode 안의 모델은 못 연다):
   ```sh
   python3 <설치된 plugin>/scripts/config.py set opencode.jira_read open
   python3 <설치된 plugin>/scripts/config.py set opencode.jira_read open --accept-error-bodies   # error-path가 pass가 아닐 때
   ```
   보내기 직전에 Jira 오류 본문을 숨긴다(`Jira 오류(본문 숨김)`, tt-guard.js transform). 확인의 `error-path` 행이 그것을 본다. pass가 아니면(warn, 또는 `--missing-key` 없이 돌려 skip) 열 때 `--accept-error-bodies`가 필요하다 — 허용 여부는 도입 담당자가 정해 `SITE_PROFILE.md`에.
3. 통과 기록은 OpenCode 버전·플러그인 지문·트래커/MCP 설정 지문(Jira 도구 매핑·읽기 도구 목록·opencode.json MCP 서버 이름)에 묶인다. 플러그인을 갱신하거나 그 설정을 바꾸면 각자 1부터 다시. 닫기: `config.py set opencode.jira_read closed`. 상태는 `jira_gate` 행(6절).
4. tt-oc에서 실제로 읽으려면 `gen_opencode.py install … --jira-read-tool <서버>_<도구> --force`(읽기 도구만 허용). `/etc/opencode`의 `"jira_*": "deny"`(`managed.json.sample`)는 관리자가 푼다 — 관리 설정이 마지막에 합쳐져 이긴다.

### 3.5 재설치

플러그인 스크립트가 바뀌면 `tt-oc`가 시작하지 않는다. 3.1과 같은 인자에 `--force`(Jira를 열었으면 3.4의 4도). 레포 사본도 같은 판으로 맞춘다. 11/07 묶음은 `oc_adapter.py`·`tt-guard.js`가 바뀌므로 **기존 OpenCode 설치는 모두 `install --force`**(반입 노트). 플러그인 경로가 바뀌면 `--plugin-root`도.

### 3.6 go / no-go

| go | no-go |
|---|---|
| `tt-oc doctor`·`runtime-check opencode` 종료 0(관리 설정 warn은 사유 기록) | 버전 불일치·설정 우회 — 보고 |
| 3.3 실행에서 규칙 지킴 | 막힌 호출 재시도, 화면 요약 |
| 사내 확인 0(OpenCode, OpenAI 호환 (a)·(b)) 통과, 3.3 실행이 실제 확인 | (b)·(c)에서 tool_calls 안 나옴(글로만), 모델 ID 거부. `/models` 404만으로는 no-go가 아니다 |
| Jira가 필요하면 3.4 통과, 아니면 "닫힘 — 이슈 본문은 `--issue-file`" 안내 | 오류 본문 위험 수용 여부 미정 |

## 4. 공통

### 4.1 모듈 스킬 레포 (MS-1)

**주소를 넣기 전에** 설치 스킬을 쓸 카테고리를 정한다(4.2).

```sh
python3 tools/make_module_repo.py <out>   # 템플릿 → <out>에 새 git 레포·첫 커밋(원격·push 없음). <out>은 비어 있고 레포 밖
# 사내 스냅샷 얹기: ... <out> --site-overlay docs/site/module-skills   # 사내 스냅샷을 같은 경로로 덮어씀(evals 거부, placeholder 남으면 종료 1, docs/SITE_RESTORE.md)
# GHE 빈 레포 만들기·push는 stderr 안내대로 사람이
# GHE 브랜치 보호(IMPL §4.5) → site-defaults module_skills.remote(관리자)
python3 tools/site_step.py modules   # MS 트랙 시작(S-3 완료 뒤)
python3 tools/site_step.py modules check   # remote·push 권한·트리·데몬 ⊆ tags.yaml·prefer
python3 tools/site_step.py modules coverage --out docs/site/module-coverage.diff   # 사내 로그 → 모듈별 줄 수·빈 이름
```

- 태그 속성: 이슈 DB `parser-rules/tags.yaml` 항목에 `level: unreliable`(그 줄 레벨은 심각도 아님)·`ipc: vendor`(벤더 IPC 결과 판별). 0.0.5부터 oFono는 site-defaults 구성요소 플래그(`level_unreliable`·`vendor_ipc`)나 tags.yaml 선언이 없으면 레벨 보정·벤더 IPC builtin이 없다(사내 반입 때 설정 필요, TODO(SITE:S25)). 키마다 하나라도 선언하면 DB만 보므로 그 키의 이름을 모두(데몬이 바뀌면 옛·새 이름 둘 다) 같은 PR에. 운영 DB `schema/parser-rules.schema.json`에 두 키를 먼저 넣는다(메인테이너, 한 PR).
- `coverage`는 토큰 0, `modules.yaml` `daemons` 추가 diff만 제안한다(지우는 제안 없음). 사용자 clone에서 적용해 **모듈 레포 PR(+1)** 로. tags.yaml에 없는 태그는 이슈 DB 계획 op PR(사용자 확인).
- 중첩 `claude -p` 점검은 명령만 출력한다. 출력된 `module_eval.py … --probe-restricted --json`(자식 1회)을 Claude Code 세션의 Bash에서 한 번 돌리고 `--done MS-1 --waive ms1.nested_claude="<결과>"`(fail `ms1.prefer`는 출력대로 고친다).

### 4.2 설치 스킬 선택 (`prefer: skill`, HEAD)

remote가 있으면 5-1이 모듈 문서로 바뀐다. 기존 사내 스킬을 계속 쓸 카테고리는:

```sh
python3 plugin/scripts/config.py set analyzers.<카테고리>.prefer skill [--platform <플랫폼>]
```

팀 기본은 site-defaults `analyzers.<카테고리>.prefer: skill`(관리자). 안 적고 레포에 그 모듈이 없으면 5-1이 종료 1로 멈춘다(`modules check`는 fail). OpenCode는 스크립트가 푼 `SKILL.md`를 읽는다 — 폴더를 바꿨으면 `install --force`.

### 4.3 사내 모델 기록의 품질

| 장치 | 무엇 | 상태 |
|---|---|---|
| 출처 기록 | 커밋 끝 `Triage-Env: runtime=…; model=…; gateway=…; label=…`(주소 없음). 확인 화면에 보인다. `runtime.label`로 팀 표식 | HEAD |
| 근거 원문 검사 | `triage.py check-output`이 5-1·5-2 근거 줄이 입력에 있는지 표시 | HEAD |
| 정기 점검 | 사내 모델·출처 모름 기록만 토큰 0 검사(lint·regress·겹침·중복·마스킹·근거) → 걸린 것·바뀐 모듈만 사내 Claude로 | HEAD |
| 시그니처 소실(drift) | 이전에 3회 이상 맞던 원인 시그니처가 새 빌드 기록 2건 이상에서 0회 → `audit.<레포>.drift` 사용자 필요(기준은 사내 측정 뒤 조정). 첫 점검은 최근 14일 | HEAD |
| 부분 일치(C′) | 후보 없음·1위 S=1·C=0이면 report.md `규칙 제안 (부분 일치):`(마스킹된 로그 줄로만). 코드 루트가 있으면 `code_roots.py find-text`로 없는 조건 문구를 코드와 대조(same·reworded·not-found …). 받아들이면 update-signature PR(+1) | HEAD |
| 마스킹 | oFono 덤프 함수 조각으로 갈린 IMSI/ICCID 값도 실행 중 가린다 | HEAD |

```sh
python3 tools/site_step.py audit --inhouse-model '<사내 모델 이름 정규식>'   # 토큰 0. docs/site/audit/에 계획·review.md
# → <날짜>-review.md를 Claude Code + Claude 세션에서 리뷰(파일 쓰기·push 없음)
python3 tools/site_step.py audit --notify  # 걸린 항목(P0·P1·실패 검사)을 이슈 DB 레포 Issue로 — 보기만. 확인 뒤 --create
python3 tools/site_step.py audit --record   # 기준점 기록, 넘친 항목은 다음 회차
```

**매주, 상한 300,000 토큰/회**(`--cap-tokens`). 넘치면 P0(근거 조작·회귀·마스킹) → P1 → 모듈 → P2 순으로 다음 회차에. 고칠 것은 계획 op PR + 사용자 확인으로만.

### 4.4 site eval은 영향 받는 것만

1. 반입 노트(`MODULE_SKILLS_RESULT.md`)의 **토큰 0 점검** 먼저: `tools/hook_replay.py <세션 .jsonl>`·`triage.py run … --offline-db` 전후, `db_lint --all`·`mask_pii --check`(새 지적이 있으면 반입을 멈춘다). 반입 뒤 5-1 점검: `config.py check --roots --json`, `triage.py module <KEY> --for deep`.
2. 깨끗하면 "영향 없음"으로 기록. 다르면 그 eval만 — `python3 tools/site_step.py evals`가 배치 명령·추정 비용을 낸다(실행 안 함).
3. SITE_INSTALL §8의 '12개 모두' 규칙은 이번 묶음에서는 반입 노트 표로 대신한다(`guard.py`·`show_guard.py`가 바뀌어도). 재생·전후 비교가 다를 때만 해당 eval을 돌린다. 평소 모델이 사외 결과와 다르면 `site_if_model_differs` 7개도.
4. 병렬 `tests/skill_evals/run.py -j N`(최대 8). 멈춤 규칙은 직렬과 같다.

## 5. 팀원에게 열기 전 체크리스트

- **공통**: [ ] S-7 끝, 재반입이면 §8 테스트 통과 · [ ] **반입 전**(IMPL §4.8 1·2): 운영 이슈 DB 브랜치 보호를 IMPL §4.5로, `docs/site/boundary-allow.txt`에 데몬 이름 줄(반입 뒤면 `--check-boundary`가 막음) · [ ] 모듈 레포면 `modules check` 통과·`prefer: skill` 결정 · [ ] 사내 모델을 열면 정기 점검 담당·요일
- **Claude Code + 사내 모델**: [ ] `runtime-check claude-gateway` 0 · [ ] 사내 확인 0·2·3·5를 `SITE_PROFILE.md`에 · [ ] 고른 모듈 안전 위반 0 · [ ] 팀원용 `env` 예시(키 없이) · [ ] `runtime.label`
- **OpenCode + 사내 모델**: [ ] 1.19.5·`/etc/opencode` 배포(또는 warn 사유) · [ ] 레포 사본 clone 주소·반입 태그 공지(3.1 0) · [ ] `tt-oc doctor`·`runtime-check opencode` 0, 3.3 통과 · [ ] Jira: 사용자별 3.4 절차와 `--accept-error-bodies` 여부 공지, 또는 "닫힘" 안내 · [ ] 갱신 절차 공지(`TEAM_GUIDE.md` 8절)

**팀원이 처음 한 번** (`SITE_INSTALL.md` §7에 더해, 전문은 `TEAM_GUIDE.md`)

| 환경 | 처음 한 번 | 평소 |
|---|---|---|
| Claude Code + Claude | 마켓플레이스 설치 → `/telephony-triage:setup` | `/telephony-triage:analyze <KEY> <로그>` |
| Claude Code + 사내 모델 | 위 + settings.json `env`(2.1) → `/telephony-triage:status --doctor` | 같음 |
| OpenCode + 사내 모델 | setup 먼저(필수. tt-oc는 `config.py doctor`에 fail이 하나라도 있으면 시작하지 않는다. config가 없으면 `config` 행이 fail) → `gen_opencode.py install` → `tt-oc doctor` | `tt-oc … --command tt-analyze -- <KEY> <로그> --analysis-only` |

이슈 DB push는 diff·검증 결과·커밋 메시지를 보고 승인한 뒤에만, main 직접 push 없음, 병합은 +1 뒤 `db_pr merge`로만. Jira는 읽기와 승인한 코멘트만.

## 6. 문제 생겼을 때

| 증상 | 확인 | 조치 |
|---|---|---|
| `runtime-check claude-gateway` 종료 1 | missing·differs 행 | settings.json `env` 고치고 재실행. `EFFORT_LEVEL`만이면 `"unset"` |
| Claude Code 400(thinking·beta) | 사내 확인 2 | `DISABLE_THINKING=1`·`DISABLE_EXPERIMENTAL_BETAS=1`, 그래도면 보고 |
| 확인 화면을 요약만 | 세션 기록, show_guard 되돌림 문구 | 대화형으로 다시. 반복되면 확인 5 실패로 보류 |
| `tt-oc` 종료 2 | `tt-oc doctor`의 fail 행 | `integrity` → 3.5 · `instructions` → 지시 파일 치움 · `env` → `OPENCODE_*` 뺌 · 버전 → 1.19.5(우회 금지) |
| `tt-oc` 종료 124 `no-response` | 첫 응답 120초(`FIRST_RESPONSE_TIMEOUT`, `--first-timeout <초>`·`TT_OC_FIRST_TIMEOUT`, 0 = 끔) 없음 | `tt-oc doctor`의 `gateway-key`·`gateway-url`, 3.2 사내 확인 0 curl(키·주소·프록시). 게이트웨이가 정상인데 긴 세션 이어가기·첫 MCP 시작이 느리면 `--first-timeout`을 늘린다. 이벤트 전에 멈춰 세션은 지우지 못한다(`opencode session list`) |
| `tt-oc` 종료 3 | "run this exact command yourself: …" | 명령을 읽고 사용자가 터미널·Claude Code에서 실행 |
| OpenCode에서 Jira 거부 | `TT_RUNTIME=opencode python3 <plugin>/scripts/config.py doctor`의 `jira_gate` | 3.4. 갱신 뒤면 확인부터 |
| `설치 스킬 못 찾음` | `config.py check --roots`, `read-roots` 행 | `prefer`·`skill_dir` 확인 뒤 `install --force` |
| git 충돌·인증 실패·MCP 없음·버전 불일치 | 해당 출력 | 우회 말고 보고 |
