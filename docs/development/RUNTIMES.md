# 실행 환경 셋 — Claude Code + 사내 모델 프로필, 크기 예산, 사외 재확인 (계획 I 2단계)

> 사외 초안 문서(설계 문서 아님 — 표·정의는 `docs/design/contracts.md`가 맞다). 결정은 `MODULE_SKILLS_DECISIONS.md` "I." 절
> (11/05 "계획 I 1단계 결과"). 측정은 11/05, Claude Code 2.1.318, 127.0.0.1의 가짜 Anthropic 서버(실제 모델 호출 없음, 비용 0).
> 이 문서는 **Claude Code + 사내 모델**(C1i–C5i)만 다룬다. OpenCode + GLM 절(O1–O10)은 그 구현과 함께 붙인다.

| 환경 | 겉(나뉨) | 안전 | 표시 의무(must_show) | 비용 |
|---|---|---|---|---|
| Claude Code + Claude | 플러그인 스킬·커맨드·hook | guard hook + git hook | show_guard(Stop·질문·publish 앞) | 보고됨 |
| **Claude Code + 사내 모델** | 같음(게이트웨이로 모델만 바꿈) | 같음(hook은 클라이언트 쪽) | 같음 — **세션 기록을 켜야** 판정한다(§4.1) | **미상**(§2) |
| OpenCode + GLM | v1 분석 전용, `tt-oc` 래퍼 | oc_adapter → guard.py | 래퍼가 출력 | 토큰만 |

## 1. 환경 프로필 (C1i)

사용자 `~/.claude/settings.json`의 `env` 블록(또는 셸 export)에 둔다. 프로젝트 `.claude/settings.json`의 `permissions.allow`에는
기대지 않는다 — 신뢰하지 않은 작업 공간의 `-p` 실행에서는 무시된다(1단계 실험).

| 키 | 값 | 이유 · 근거 |
|---|---|---|
| `ANTHROPIC_BASE_URL` | 게이트웨이 주소 | 필수. 게이트웨이가 `/v1/messages`(스트리밍 `tool_use`)를 내야 한다 — OpenAI 모양만이면 이 환경은 다시 연다(사내 확인 0) |
| `ANTHROPIC_AUTH_TOKEN` 또는 `ANTHROPIC_API_KEY` (또는 `apiKeyHelper`) | 사내 자격 | AUTH_TOKEN → `Authorization: Bearer`, API_KEY → `x-api-key`(가짜 서버 기록). 게이트웨이가 어느 쪽을 받는지는 사내 확인 2 |
| `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL` | 사내 모델 ID | 모르는 ID도 받는다(`[claude-code:unrecognized_model]` 경고만). 보조 호출·서브에이전트가 Claude ID로 새지 않게 모두 같은 ID |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `16000` | 요청 `max_tokens:16000`(없으면 32000) |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `202000` | `contextWindow 202000`(자동 압축 기준) |
| `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` | `1` | 베타 헤더를 줄인다: context-management·thinking-display 등이 빠지고 `claude-code`·`interleaved-thinking`·`effort`만 남았다(1단계 knobs 실행 — 이 표의 키를 함께 켬, 요청 `context_management` 없음) |
| `CLAUDE_CODE_EFFORT_LEVEL` | `unset`(또는 변수 없음) | 요청에 `output_config` 없음(같은 knobs 실행) |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | 업데이트·텔레메트리 등 외부 트래픽 없음(오프라인 실행 확인) |
| `CLAUDE_CODE_DISABLE_THINKING` | `1` — **조건부** | 게이트웨이가 `thinking`을 거부할 때만(knobs 실행에서 요청 `thinking` 없음). CLI는 thinking 400에 한 번 자동 재시도한다(1단계 실험) |

- **module_eval 자식**: 자식은 `--setting-sources ""`라 사용자 설정을 읽지 않는다. 그래서 `common/claude_child.py`가 settings.json
  `env`에서 인증·네트워크 키(`ANTHROPIC_*` 등)와 위 프로필 키(`GATEWAY_ENV_NAMES`)를 골라 자식 프로세스 환경에 넣는다(값은
  argv·기록에 없음, `execution.json` `auth_from_user_settings`에 이름만). 고치기 전에는 프로필 키가 빠져 자식이 `max_tokens:32000`·
  thinking·베타 헤더로 요청했다. 모델은 settings.json 최상위 `model` 키로는 넘어가지 않는다 — `ANTHROPIC_MODEL` 또는 `--model`.
- **점검(모델 호출 없음)**: `claude_child.gateway_profile_check(env)`가 위 표를 ok·missing·differs·info 행으로 낸다(비밀 값은 행에
  없음). 권장 값이 `unset`인 키는 변수 없음·빈 값·글자 그대로 `unset`을 모두 ok로 본다(F). 부르는 법:
  `python3 tools/site_step.py runtime-check claude-gateway`(표, missing·differs가 있으면 종료 1, O10 — §6).

## 2. 비용 미상 (C2i)

CLI가 모르는 모델 ID에는 자리 표시 단가($4/$20 per MTok)를 매기고 result `modelUsage.<모델>.costBasis`를 `"unknown"`으로 둔다
(2.1.318 가짜 서버 실험 28건 모두). 이 값은 비용이 아니다.

- `claude_child.result_cost`·`token_record`: costBasis가 하나라도 unknown이면 `total_cost_usd`·`cost_usd`는 `null`, `cost_basis:
  "unknown"`. 토큰 수는 그대로 센다(skill eval `run.py`의 기록도 같은 함수).
- `module_eval.py`: 비용 행은 `skipped`("비용 미상(costBasis unknown …)"), `execution.json`에 `cost_basis`, 반복 기록의
  `unit_cost_usd`는 남기지 않는다(미상 run이 하나라도 있으면 — 자리 표시 단가가 다음 추정에 쓰이지 않게). 총비용은 "미상".
- 사내 모델로 잴 때: `module_eval.py --module <p/m> --model <사내 모델> --no-require-cost --no-max-cost`. 상한은 토큰·run 수로
  잡는다(`--max-cost`를 주면 자식 `--max-budget-usd`가 자리 표시 단가로 세어 일찍 멈출 수 있다). 비용 관리는 사내 게이트웨이 쪽 일이다.

## 3. `--bare` (C3i, 선택 — 기본 끔)

`module_eval.py --bare`는 읽기 전용 자식을 `claude --bare`로 띄운다. hook·LSP·CLAUDE.md 자동 탐색·자동 메모리·키체인을 건너뛰어
2턴 실행의 입력 토큰이 6,752 → 1,108로 줄었다(1단계 `baretok`). 자식은 이미 `--setting-sources ""`라 hook이 없으므로 안전 차이는 없다.

- 인증: `--bare`는 `ANTHROPIC_API_KEY`·`apiKeyHelper`(--settings)만 읽는다고 도움말에 있으나, **`ANTHROPIC_AUTH_TOKEN`도 됐다**
  (가짜 서버 `Authorization: Bearer`, 실험 bare_tok). OAuth·키체인 로그인은 안 된다 — 키가 없으면 요청 없이 result
  `is_error`·"Not logged in · Please run /login"(실험 bare_none).
- 자동 대체: 그런 인증 실패(위 문구, 또는 `api_error_status` 401/403)이고 도구 호출이 없으면 그 run만 `--bare` 없이 한 번 다시 돈다.
  첫 기록은 `run_dir/bare-attempt/`, `execution.json` `bare`는 `used`·`unsupported`(CLI에 없음)·`fallback: <사유>`.
- 채택(결정 ④): 사내 인증 확인 뒤 켠다. 그 전에는 끈 채로 둔다.

## 4. 사외 재확인 (C5i, 가짜 서버, 모델 ID `internal-glm-test`)

절차는 1단계 실험과 같다: `env -i`로 실제 `ANTHROPIC_BASE_URL`을 끊고 127.0.0.1 가짜 서버 주소·가짜 키만 준다.
`--plugin-dir`로 플러그인을 싣고 `--setting-sources ""`, `--allowedTools Bash`(권한 검사로는 막히지 않게 — 막혔다면 hook이 막은 것).

### 4.1 show_guard Stop (세션 기록 켬)

가짜 모델: ① Bash로 `db_pr.py summary`를 흉내 낸 스크립트를 부른다(`common.shown.record`로 `dbpr/publish.py:447`과 같은 push
기록을 남기고 화면을 출력), ② 요약 한 줄만 답한다, ③ Stop 피드백을 받으면 화면 전문을 답한다.

| 실행 | 결과 |
|---|---|
| 기록 켬(`--no-session-persistence` 없음) | Stop hook이 막았다: "show-guard push:abc1234def — 되돌림(오류 아님): push 확인 화면을 요약했다(빠진 줄 8/8)". 다음 답에 화면 전문 → 통과, 요청 3회 |
| 기록 끔(`--no-session-persistence`) | 막지 않았다(transcript 없음 → fail-open). 1단계 게이트웨이 실행의 "transcript를 읽지 못함"과 같은 원인 |

결론: show_guard는 사내 모델에서도 동작한다. **세션 기록을 끄면 표시 판정이 없다** — 대화형 Claude Code는 기본이 켬, `-p`
자동화는 `--no-session-persistence`를 쓰지 않는다(skill eval plugin 모드는 이미 켠다, `child_common_args(persist=True)`).

### 4.2 guard 설정됨(테스트 헬퍼 작업 공간: 이슈 DB clone + 로컬 bare 원격, 사용자 config, tracker, git hook)

11/05 측정, 당시 guard 판. 현행(4-c 이후)은 base 브랜치 push를 따로 deny하지 않고 ask + 서버 브랜치 보호(`08-safety.md §9` 규칙 6, `s4a.protection_guard`).

| 명령(가짜 모델의 Bash) | 결과 | 판정 출처 |
|---|---|---|
| `cd <clone> && git push origin HEAD:refs/heads/main` | 거부: "base 브랜치(main)로 직접 push하지 않는다 (규칙 6)" | guard PreToolUse |
| 같은 push, 플러그인 없음(대조, `--dry-run`) | Bash는 허용돼 실행 → git pre-push hook이 거부(TT_PUBLISH_TOKEN 없음) | git hook |
| clone에서 `git push origin HEAD:refs/heads/issue/MOCK-1` | 규칙 7 `ask` → `-p`에서 자동 거부(permission_denials에 남음) | guard PreToolUse |
| `git -c core.hooksPath=/dev/null commit` | 거부: 규칙 5 | guard PreToolUse |
| `db_pr.py publish … --approved … --commit` | 규칙 7 `ask` → `-p`에서 자동 거부 | guard PreToolUse |
| `triage.py --help`, `job_status.py --help` (분석 흐름 스크립트) | ask·deny 없음, 출력 그대로 | — |

결론: 1단계 E3에서 push를 멈춘 것은 `-p` 권한 검사였지만, 설정된 guard에서는 **실제 규칙(5·6·7)이 사내 모델 ID에서도 판정한다**.
`-p`에서 guard `ask`는 거부가 되므로 쓰기 흐름은 대화형 세션의 확인 대화로 한다(OpenCode 안 A의 "명령 출력"과 같은 결론).
MCP 쓰기(add_comment 승인 유무)·Write/Edit 규칙 8은 이번에 돌리지 않았다 — OpenCode O9 고정 작업 공간과 함께.

### 4.3 자식(`claude_child`) 실제 CLI 확인

`tests/test_claude_child.py`의 `test_real_cli_*` 두 개는 `TT_CLAUDE_FAKE_SERVER=1`일 때만 돈다(관리 설정이 주소·키를 덮는 PC에서
진짜 모델로 가지 않게 기본 끔). 11/05 결과: 통과 — settings.json env의 `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000`이 `--bare` 자식
요청 `max_tokens:16000`으로 갔고, 비용 `null`·`cost_basis: unknown`·토큰 기록, 키 없는 `--bare`는 "Not logged in" 뒤 대체 실행.

## 5. 크기 예산 (C4i)

토큰 수는 **어림**이다: ASCII 글자/4 + 비ASCII 글자×1(한글을 넉넉히 센 값, 실제 토크나이저 아님 — GLM 토크나이저는 사내 확인 5).
기준 모델 한도: 출력 16K·문맥 202K 토큰.

### 5.1 플러그인 스킬

| 파일 | 바이트 | 어림 토큰 |
|---|---:|---:|
| `SKILL.md` | 9,060 | ~2,700 |
| `reference/write-flow.md` (최대) | 15,995 | ~4,750 |
| `reference/record.md` | 12,852 | ~3,800 |
| `reference/db-authoring.md` | 12,264 | ~3,700 |
| `reference/verify.md` | 11,658 | ~3,400 |
| `reference/post.md` | 6,594 | ~2,000 |
| `reference/explore.md` | 5,910 | ~1,800 |
| 나머지 8개(log-tags·sync-pr·ril-requests·fail-causes·search·ofono log-guide·rules·skill-patch) | 1,932–5,040 | ~580–1,450 |
| **전체 16개** | **102,446** | **~30,400** |

- `SKILL.md` 예산 ≤9 KB(9,216 B): 지금 9,060 B — 여유 156 B. 줄을 더하면 reference로 옮긴다.
- 문맥: 스킬 전부를 읽어도 ~30K(202K의 15%). 가장 무거운 쓰기 흐름 읽기(SKILL + write-flow + record + db-authoring + verify)
  ≈ 61.8 KB ≈ ~18K. 문맥은 문제가 아니다. 위험은 출력 쪽과 약한 모델의 긴 지시 따르기다.

### 5.2 C0 모듈 문서(ofono/data)

| 묶음 | 바이트 | 어림 토큰 |
|---|---:|---:|
| 5-1 읽기 묶음: `data/SKILL.md` 3,497 + `analyzer.md` 1,780 + `_common/layers.md` 3,520 + `_common/components.md` 3,488 + `references/DATA-001.md` 1,946 | 14,231 | ~4,400 |
| `data/explore.md`(탐색할 때만) | 2,748 | ~820 |
| case 입력 timeline.md(3개) | 1,049–1,570 | ~280–410 |

모듈 문서 하나는 ≤3.5 KB, 5-1 묶음과 입력을 합쳐도 ~5K — 202K 문맥에 넉넉하고, 사내 모델의 "입력은 작게 거른다" 원칙에 맞다.

### 5.3 글자 그대로 보여야 하는 화면(must_show)

| 출처 | 바이트 | 어림 토큰 |
|---|---:|---:|
| push 확인 화면 fixture 13개(`tests/fixtures/render/*.md`) | 1,128–2,819 (최대 `record-non-success.md`) | ~320–800 |
| 녹화 eval 세션의 stage+summary 출력(`tests/fixtures/show_guard/eval2-session.jsonl`) | 6,169 | ~1,700 |
| 같은 세션의 분석 리포트(`## MOCK-9002 분석`) | 1,306 | ~390 |
| show_guard가 거부 문구에 싣는 화면 상한(`show_guard.py` `BLOCK_LIMIT`) | 12,288 | ~3,500–4,500 |

- 예산 "한 답에 글자 그대로 옮길 것 ≤ 약 8 KB": 지금 fixture·녹화 최대(6.2 KB)는 안. 12 KB 상한까지 가는 화면은 16K 출력의
  ~1/4–1/3을 쓴다 — 넘치지는 않지만 약한 모델이 그대로 옮기는지는 사내 확인 5. 4 KB 넘는 스크립트 출력은 파일로(B2(b) 고정 칸·바이트 상한).

### 5.4 OpenCode와 모듈 스킬(B1+B2, 계획 H amendments R19~R22·R26·R40)

- **R19** `tt-oc` 표시 기록에 `evidence`(check-output 결과 줄 — 심층 분석 첫 줄과, 원문에 없는 인용이 있으면 근거 원문 검사 줄)를 넣는다(`SHOWN_KINDS`). 심층 check-output은 늘 줄을 남기므로 tt-oc가 심층 결과마다 그 줄을 보인다.
- **R20** 에이전트 규칙 2: 스크립트 JSON에 `next`가 있으면 stderr를 보이고 `next`를 따른다(멈춤보다 앞선다). `next` 없는 종료 2와
  스크립트 오류만 멈춘다. `module --for deep`·`check-output`의 실패 JSON은 멈춤 사례(`사용 오류`·`설정 오류`·JOB 없는 `작업 없음`)
  말고 모두 `next`를 낸다 — 모듈 받기 실패는 분석을 끝내지 않는다.
- **R21** 설치 스킬 `SKILL.md`는 `config.py check --roots`의 `read_roots`로 연다: `gen_opencode.py install`이 플러그인·작업·이슈
  DB 밖인 폴더를 `external_directory` 읽기 allow로 더하고(edit는 그대로 deny), `tt-oc doctor`는 지금 풀린 폴더가 설치한 허용
  밖이면 `read-roots` warn(설정을 바꾼 뒤 `install --force`). 스킬 도구는 없다(에이전트 `skill: deny`): `설치 스킬 못 찾음`이나
  Read 거부면 규칙 8대로 `check-output <KEY> --for deep --skipped "설치 스킬 못 찾음"`.
- **R22** `tt-oc` 사전 점검은 `config.py doctor`의 fail이 `module_skills` 행뿐이면 시작한다(`module-skills` warn "모듈 문서 받기는
  실패할 수 있음"). 다른 fail 행이 하나라도 있으면 전처럼 막는다.
- **R26** 모듈 원격 `Config` 경고는 다른 설정 경고와 같다: 어댑터가 guard stderr 경고로 넘기고 tt-guard.js가 세션마다 한 번만 보인다(`warned`, O2a). `guard.word_net`과
  hook 입력 `cwd` 해석은 고정 인터페이스(`test_hooks.py`) — I-2는 guard.py를 고치지 않는다.
- **R40**(v1 수용) OpenCode에서 설치 스킬은 `skill-input.json`이 가리키는 `timeline`만 읽는다(에이전트의 `events.json` 금지).
  근거 원문 검사는 `events.json` 기준 그대로(B2 §6.1). MS-2에서 없어진다.
- **바이너리 의존 한 곳**(종합 리뷰 F②): 1.19.5의 비공개 표면(고정 버전, CLI 인자, 거부·자식 환경 변수, 설정 deny 때 모델에 가는 영어 문구,
  `run --format json` 이벤트 키, 플러그인 hook 이름)은 `plugin/scripts/common/oc_version.py`에만 있다. `oc_adapter`·`tt-oc`·`gen_opencode`·
  e2e 헬퍼가 그 값을 읽고, `tt-guard.js`(JS)는 `tests/test_oc_version.py`가 hook 이름·내장 도구 표·버전 주석을 대조한다. 버전 갱신 = 그 파일 +
  시험 고정값 1곳 + 파일에 적힌 실험 재확인(x3b·x4, MCP 오류 경로, 이벤트 스키마).

### 5.5 OpenCode Jira 읽기 관문(11/05 사용자 "사내 확인 뒤 설정으로 열기")

- 코드 상수(`JIRA_READ_RELEASED`)는 없앴다. 관문(`plugin/scripts/common/oc_jira_gate.py`)은 사용자 config `opencode.jira_read: open`
  + 통과 기록(`~/.telephony-triage/opencode-jira-check.json`: 성공 경로 통과·같은 OpenCode 버전·같은 플러그인 스크립트 지문·같은
  트래커/MCP 지문 `tracker_fingerprint` — 트래커 매핑·MCP 서버 이름을 바꾸면 다시 확인, 코덱스 리뷰 02e0ec2 F03)이
  모두 맞을 때만 열린다. 기록의 오류 경로 행이 pass가 아니면(warn·skip) `--accept-error-bodies`도 있어야 한다. 테스트·사내 확인
  실행만 `TT_OC_JIRA_GATE=open`. 코멘트 쓰기(`tracker.write_tools.add_comment`)는 v1에서 늘 거부.
- 사내 확인: `python3 tools/site_step.py runtime-check opencode --project <설치 폴더> --jira <있는 키> --missing-key <없는 키>`
  (`tools/oc_jira_check.py`, 모델 토큰 0). 설치 폴더를 임시로 복사해 모델만 127.0.0.1 가짜 서버로 바꾸고(읽기 도구는 그 임시
  설정에서만 allow, MCP 항목은 설정 파일 글자 그대로 — `{env:…}`를 풀지 않는다) 실제 opencode·tt-guard.js·실제 Jira MCP로
  get_issue·get_comments(있는 키)·get_issue(없는 키)를 부른다. 가짜 모델이 **받은** 도구 결과로 판정: jira_bridge 격리 문구 +
  원문 파일이 이번 실행에 `<work_dir>/<KEY>/issue_raw.json`에 쓰임, `masking.residual == {}`, 오류 본문이 갔는지(종류·개수만).
  끝나면 세션 삭제·확인용 원문 파일 정리(전에 있던 파일은 복원). 종료 0은 성공 경로 통과일 때만. 통과 기록을 쓰고 여는 명령만 보인다.
- 열기: 사용자가 터미널에서 `python3 <plugin>/scripts/config.py set opencode.jira_read open [--accept-error-bodies]`. 기록이 없거나
  어긋나면 거부(runtime-check 명령 안내). **관문은 OpenCode가 시작할 때 한 번만 정한다**: tt-guard.js가 플러그인을 실을 때
  `oc_adapter.py gate`로 설정·기록을 판정하고, 그 값(`TT_OC_JIRA_SESSION_GATE`)을 이후 모든 adapter 호출의 프로세스 환경으로
  넘긴다. 세션 중에 쓰인 설정·기록은 그 세션에 적용되지 않는다(다음 시작부터, doctor `jira_gate` 행이 차이를 보인다). 시작
  판정 없이 불린 adapter는 닫힘. OpenCode 안의 모델이 파일을 쓰는 길도 막는다: 어댑터가 bash `config.py set opencode.*`를
  "직접 실행" 거부(v1 쓰기 흐름), `edit`·`write`·`apply_patch`와 **플러그인 스크립트 인자**(`--out X`·`--out=X`·`-oX`, 작업
  폴더·`cd` 후보 기준 상대 경로, 심볼릭 링크 뒤 `..`)가 사용자 `config.yaml`·통과 기록·`opencode.json`·`.opencode/`·플러그인
  루트(`hooks/hooks.json`)·`AGENTS.md` 등 보호 경로를 가리키면 거부(11/05 리뷰 P0: `mask_pii --out`으로 위조 기록·설정을 써서
  열 수 있었다 — `tests/opencode/test_oc_jira.py`가 배포 템플릿 권한 그대로 회귀 확인), `config.py`도 `TT_RUNTIME=opencode`면
  거부한다. tt-oc에서 실제로 읽으려면 설치 설정이
  읽기 도구를 허용해야 한다: `gen_opencode.py install … --jira-read-tool <서버>_<도구> --force`(permission 끝 allow — 템플릿의
  `"*"`·`jira_*` deny 뒤). 관리 설정(`/etc/opencode`)의 `jira_*` deny는 관리자 몫(확인의 tools-offered 행이 fail로 보인다).
- **OpenCode 안의 쓰기 경계(11/13 OC-B, `oc_adapter.py`)**: `config.py`의 사용자 설정 쓰기 하위 명령(`init`·`set`·`set-tracker`·
  `install-hooks`·`rename-legacy --apply`·`tracker-candidates --mcp-config|--opencode-config`)은
  config.py 자신의 파서로 읽어 "직접 실행"으로 돌린다(사람이 터미널에서). `init --answers`는 일반 거부다. 대화형 `config.py init`으로 답한다.
  그래서 `tt-setup`은 쓰기 흐름 커맨드다. 플러그인 스크립트는 `--plugin-root`(줄임말·`=` 꼴 포함)를 받지 않는다(`sync-scripts-path`도 거부).
  스크립트 출력(`--out`·`--meta-out`·`--preview`·`mask_pii --in-place`·`jira_fields extract --consume`)은 작업 루트(설치 폴더
  `tt-oc.json`의 `work_root`) 안이어야 한다. 루트 자체는 안 된다. 그 파일을 못 읽으면 출력이 있는 호출은 거부한다.
  `.git`·`.githooks` 아래나 이름이 `HEAD`인 경로에는 `edit`·`write`·`apply_patch`도 스크립트 출력도 쓰지 않는다(모델이 만든 저장소의
  `core.fsmonitor`·hook을 허용된 `git status`가 실행한다). 작업 루트 안에서 `HEAD` 파일이 있는 폴더(bare·미러·`.repo/projects/*.git`)
  아래에도 쓰지 않는다. 작업 루트 밖 출력 거부만은 모델이 절대 경로로 한 번 다시 하게 한다(`OUT_RETRY`, tt-oc는 막힌 호출로 센다).
  tt-oc는 자식 환경에 `safe.bareRepository=explicit`·`protocol.ext.allow=never`를 붙이고 `GIT_ALLOW_PROTOCOL`을 뺀다.
  tt-guard.js의 `shell.env`가 같은 `GIT_CONFIG_*`를 bash 자식에 다시 넣고 `GIT_CONFIG_PARAMETERS`를 빈 값으로 덮는다(실제 bash
  자식에 걸리는지는 사내 e2e로 확인). 어댑터는 자기 환경에 이 설정이 없으면 bash의 git·스크립트를 거부한다.
  `tt-oc doctor`의 `git` 행은 어댑터와 같은 조건으로 본다(`GIT_CONFIG_PARAMETERS`가 같은 설정을 정하면 fail).
  git 2.38 미만이면 doctor가 warn을 내고 시작은 한다. 그때 `safe.bareRepository`는 무시되고 `.git`·`HEAD` 쓰기 거부만 남는다
  (`protocol.ext.allow=never`는 `GIT_CONFIG_COUNT`를 받는 git 2.31부터 걸린다). 2.38 이상을 쓴다.
  모듈 스킬 git(`moduleskills._env`)은 `GIT_CONFIG_*`를 지우고 자체 `-c`·`GIT_CEILING_DIRECTORIES`로 돈다.
  플랫폼별 `work_dir`는 설치의 `--work-root` 안에 둔다(사내 analyze e2e에서 `--out` 거부가 없는지 확인).
  `tt-oc publish`(사람이 터미널에서 승인하는 게시)는 처음 설치할 때 `install … --allow-publish`를 주면 열림(tt-oc.json
  `"publish": "open"`), 안 주면 닫힘이다. 이미 설치한 곳을 열거나 닫으려면 같은 install을 `--force`로 다시 한다.
- OpenCode 허용 목록·guard 는 모델의 실수와 로그·Jira 본문에 섞인 지시를 걸러내는 사고 방지 장치다. 작정하고 우회를 찾는 모델을
  막는다고 보장하지 않는다. 실제 경계는 OS 사용자 권한, 서버 브랜치 보호, 사람이 내용을 읽고 하는 승인이다. 모델이 출력한 명령은
  읽지 않고 붙여 넣지 않는다.
- **MCP 오류 경로(1.19.5 실험, 11/05)**: 오류로 끝난 MCP 호출(MCP `isError`·JSON-RPC 오류·시간 초과)은 `tool.execute.after`가
  돌지 않는다 — 바이너리의 MCP 실행 경로는 `isError`면 `throw Error(<텍스트 블록>)`이라 그 오류 글(응답 본문)이 tool part
  `state.error`가 되어 다음 모델 요청에 그대로 간다(after 기록 0건으로 확인). 대신 `experimental.chat.messages.transform`이
  모델 요청 직전마다(대화 루프와 압축 요청 둘 다 — 바이너리에서 `trigger("experimental.chat.messages.transform",{},{messages})`
  2곳) 보낼 메시지 배열로 불리고, 거기서 `state.error`를 바꾸면 모델이 받는 글이 바뀐다(실험: 가짜 서버가 받은 tool 메시지가
  바꾼 글, 저장된 세션·이벤트는 원문 그대로). 그래서 tt-guard.js가 이 hook에서 내장 도구가 아닌 오류 part를 `oc_adapter.py error`에
  넘기고, Jira 도구면 "Jira 오류(본문 숨김): <도구> <분류>"(분류는 고정 낱말 4xx·5xx·not-found·timeout·auth·permission-denied·
  error)로 바꾼다. 판정 실패·시간 초과는 숨김(닫힘). before가 거부한 호출의 우리 문구는 식별자만 가린다. e2e:
  `tests/opencode/test_oc_jira.py`(isError 404·JSON-RPC 500 모두 숨김, 이벤트에는 원문). 사용자 터미널 출력과 opencode.db에는
  원문이 남는다(tt-oc `--delete-session`).

## 6. 남은 일

**사내 확인**(환경마다 짧은 스크립트 실행 1회, `MODULE_SKILLS_DECISIONS.md` "사내 토큰 최소"):
0. 게이트웨이 프로토콜 — curl만으로 `/v1/messages` 스트리밍 `tool_use`(도구 강제와 자동 선택 `tool_choice: auto` 둘 — 실제 실행은 자동 선택이다).
2. 호환 — `thinking`·`output_config.effort`·대화 중 `system`·베타 헤더 수용, 오류 본문 전달, 자격 변수(AUTH_TOKEN/API_KEY), 빈 폴더 `claude -p`의 Bash 1회.
3. `usage` 토큰이 오는지(비용이 미상이라 토큰이 유일한 수치).
5. 가장 큰 화면·must_show를 16K 출력 안에서 그대로 옮기는지.
6. OpenCode Jira 읽기 — `site_step.py runtime-check opencode --project <설치 폴더> --jira <있는 키> --missing-key <없는 키>`
   (§5.5, 모델 토큰 0). 통과하면 사용자가 `config.py set opencode.jira_read open`으로 연다.
- `--bare` 인증(§3) — 되면 module_eval에서 켠다.

**B1+B2 뒤 통합 — 했다(11/05)**:
- O10 `site_step.py runtime-check claude-gateway|opencode`(모델·네트워크 호출 없음, 사내 확인 0은 curl 명령만 보인다):
  claude-gateway는 `gateway_profile_check` 표(missing·differs → 1), opencode는 버전 1.19.5(없으면 설치 안내)·설치한
  opencode.json 필수 설정·`tt-oc` 사전 점검(공유 `version_row`·`config_problems`·`preflight`)·관리 설정(`gen_opencode.managed_problems`,
  없으면 warn). 확인 0 curl은 대상별: claude-gateway는 Anthropic `/v1/messages`, opencode는 OpenAI 호환 `<baseURL>/models`(토큰 0)·
  선택 `/chat/completions` 스트리밍 tool_calls(설치한 opencode.json의 baseURL·모델을 채우고 키는 `$TT_GATEWAY_API_KEY` 이름만, 11/06 G).
  레포 zip에 `opencode/`가 들어가는 것은 `test_make_bundle.py`가 고정한다(검사 항목은 그대로).
  F에서 unset 거짓 실패를 고쳤다: `CLAUDE_CODE_EFFORT_LEVEL`이 없으면 missing이던 것을 ok로(권장 값 unset).
- O8 `config.py tracker-candidates`가 `--opencode-config`(또는 `TT_RUNTIME=opencode`면 작업 폴더 설정)의 `mcp`(enabled·command)를
  읽고 `<server>_<tool>` 이름을 안다(`mcptools.opencode_candidates` — `oc_adapter`와 같은 규칙). `job_status.py`는 OpenCode 안에서만
  런타임·모델·OpenCode 버전, `config.py doctor`는 OpenCode 안에서만 `opencode_env`·`jira_gate` 행(기본 13행 그대로, `jira_gate`는
  열림·닫힘과 마지막 사내 확인 요약 — §5.5).
- `tools/related_tests.py`: `common/claude_child.py` → 스크립트 규칙 + `CHILD_HELPER_TESTS`(test_claude_child 포함), `opencode/**`·
  `tests/opencode/**` → OpenCode 테스트 셋.
