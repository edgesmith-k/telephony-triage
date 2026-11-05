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
| `CLAUDE_CODE_EFFORT_LEVEL` | `unset` | 요청에 `output_config` 없음(같은 knobs 실행) |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | 업데이트·텔레메트리 등 외부 트래픽 없음(오프라인 실행 확인) |
| `CLAUDE_CODE_DISABLE_THINKING` | `1` — **조건부** | 게이트웨이가 `thinking`을 거부할 때만(knobs 실행에서 요청 `thinking` 없음). CLI는 thinking 400에 한 번 자동 재시도한다(1단계 실험) |

- **module_eval 자식**: 자식은 `--setting-sources ""`라 사용자 설정을 읽지 않는다. 그래서 `common/claude_child.py`가 settings.json
  `env`에서 인증·네트워크 키(`ANTHROPIC_*` 등)와 위 프로필 키(`GATEWAY_ENV_NAMES`)를 골라 자식 프로세스 환경에 넣는다(값은
  argv·기록에 없음, `execution.json` `auth_from_user_settings`에 이름만). 고치기 전에는 프로필 키가 빠져 자식이 `max_tokens:32000`·
  thinking·베타 헤더로 요청했다. 모델은 settings.json 최상위 `model` 키로는 넘어가지 않는다 — `ANTHROPIC_MODEL` 또는 `--model`.
- **점검(모델 호출 없음)**: `claude_child.gateway_profile_check(env)`가 위 표를 ok·missing·differs·info 행으로 낸다(비밀 값은 행에
  없음). 지금 부르는 법:
  `python3 -c "import os,sys,json; sys.path.insert(0,'plugin/scripts'); from common import claude_child as c; print(json.dumps(c.gateway_profile_check(dict(os.environ)), ensure_ascii=False, indent=1))"`
  — `site_step.py`의 런타임 점검 명령으로 묶는 것은 O10(B1+B2 뒤 통합)에서 한다(§6).

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

## 6. 남은 일

**사내 확인**(환경마다 짧은 스크립트 실행 1회, `MODULE_SKILLS_DECISIONS.md` "사내 토큰 최소"):
0. 게이트웨이 프로토콜 — curl만으로 `/v1/messages` 스트리밍 `tool_use`.
2. 호환 — `thinking`·`output_config.effort`·대화 중 `system`·베타 헤더 수용, 오류 본문 전달, 자격 변수(AUTH_TOKEN/API_KEY).
3. `usage` 토큰이 오는지(비용이 미상이라 토큰이 유일한 수치).
5. 가장 큰 화면·must_show를 16K 출력 안에서 그대로 옮기는지.
- `--bare` 인증(§3) — 되면 module_eval에서 켠다.

**B1+B2 뒤 통합(이 단계에서 하지 않음 — 파일 소유가 다른 구현에 있다)**:
- O10 `site_step.py runtime-check claude-gateway`: `claude_child.gateway_profile_check`를 불러 표를 보이고, missing·differs가
  있으면 실패(모델 호출 없음). 같은 명령에 OpenCode 점검(버전 1.19.5, `snapshot:false`, managed 설정)과 사내 확인 0의 curl 단계를 둔다.
- O8 `common/mcptools.py`·`config.py setup`이 opencode.json `mcp`와 `<server>_<tool>` 이름을 읽고, `job_status.py`가
  런타임(`TT_RUNTIME`)·모델·OpenCode 버전을 보인다.
- `tools/related_tests.py` 대응: `common/claude_child.py`를 바꾸면 `tests/test_claude_child.py`도 고른다(`CHILD_HELPER_TESTS`에 추가).
