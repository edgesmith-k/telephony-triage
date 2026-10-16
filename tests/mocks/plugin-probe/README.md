# 빈 플러그인 실험 (probe)

`14-site.md` S1이 말하는 **빈 플러그인 실험**을 사외에서 미리 해 보는 최소
플러그인이다 (`11-phases.md` Phase D0, `15-local-draft.md §15.2` "사내 Claude
Code 기능" 행). 배포 대상(`plugin/`)이 아니다.

## 확인할 것

| # | 항목 | 확인 방법 |
|---|---|---|
| 1 | 플러그인 로드 | 이 디렉토리를 로컬 플러그인으로 등록하고 `/probe:ping`이 보이는지 |
| 2 | 커맨드와 스킬의 관계 | `/probe:ping` 실행 시 `skills/probe/SKILL.md`가 함께 쓰이는지 |
| 3 | `${CLAUDE_PLUGIN_ROOT}` 치환 | `/probe:ping`이 부르는 `scripts/probe.py`가 실제로 실행되는지 (치환 안 되면 경로 오류) |
| 4 | hooks (PreToolUse) | Bash 도구를 쓰면 `hooks/probe_hook.py`가 `probe-hook.log`에 입력 JSON을 남기는지 |
| 5 | **MCP 도구 이름 형식** | 모의 Jira MCP 도구를 부른 뒤 `probe-hook.log`에서 `tool_name` 값이 `mcp__mock-jira__jira_fetch_ticket` 형식인지 |
| 6 | hook matcher 정규식 | `hooks.json`의 `mcp__.*` matcher가 실제로 MCP 도구에 걸리는지 |
| 7 | 권한 결정 필드 | hook이 `allow`/`deny`/`ask`를 냈을 때 세션이 그대로 따르는지 |
| 8 | **`@SITE_PROFILE.md` import** | 레포 루트 `CLAUDE.md`의 첫 줄 `@SITE_PROFILE.md`가 **파일이 없을 때** 오류인지 경고인지 조용한지 |
| 9 | hook 종료 코드 1·2 동작 | PreToolUse hook이 종료 1(비차단 오류)·2(차단)로 끝날 때 도구가 실행되는지·stderr가 어디 보이는지. guard·jira_bridge가 의존성 import 실패에도 종료 0 + 결정 JSON을 내는 근거다 (`08-safety.md §9` 의존성 없음). **사내 S1에서 확인** (사외 결과 없음) |
| 10 | **Stop hook** (표시 보조 `show_guard.py stop`, `08-safety.md §9.1`) | Stop hook 입력에 `last_assistant_message`·`stop_hook_active`·`transcript_path`가 있는지, `{"decision": "block", "reason"}`이면 모델이 reason을 받고 **새 메시지**로 이어 쓰는지(앞 메시지는 남는지), 두 번째 Stop의 `stop_hook_active`가 true인지, 피드백이 transcript에 `isMeta` user 항목("Stop hook feedback:\n<reason>")으로 남는지, 연속 계속 한도 |
| 11 | PreToolUse 때 transcript (show_guard `pre-ask`·`pre-bash`) | 같은 응답에서 도구 호출 앞에 쓴 텍스트 블록이 PreToolUse 시점의 `transcript_path`에 이미 있는지(화면을 붙이고 바로 질문하는 경우), 입력에 `tool_use_id`가 있는지, `AskUserQuestion`의 `tool_input` 모양(`questions[].question`·`header`·`options[].label`) |
| 12 | 여러 matcher 그룹·hook | 한 도구에 두 그룹(`mcp__.*`와 `mcp__.*__ask_user`)·한 그룹의 두 hook(Bash: guard + show_guard)이 걸리면 모두 실행되고 하나라도 `deny`면 거부되는지, 거부된 tool_result 문구(`PreToolUse:<tool> hook error: <reason>`, `is_error`) |
| 13 | transcript 블록 기록 순서 (show_guard pre-ask·pre-bash의 기다림 전제) | 한 응답(같은 `message.id`)의 텍스트 블록이 그 tool_use 항목보다 **먼저** transcript에 붙는지, PreToolUse 시점에 지금 tool_use가 얼마 만에 기록되는지 |
| 14 | **AskUserQuestion 선택지 상한** | 질문당 선택지 수 상한(그리고 질문 수 상한), 넘을 때 동작(오류·잘림·거부), "Other"(자유 입력)가 자동으로 붙는지. Step 7 첫 질문(후보 ≤3 + 새 원인·새 유형·원인 미확정·기록하지 않음)과 거부 뒤 질문이 상한을 넘는지 판단 근거(L U-4) |
| 15 | **transcript 시각으로 스크립트 기록 고정** (show_guard의 의무 = 스크립트 표시 기록, `08-safety.md §9.1`, L R) | Bash 호출마다 tool_use 줄 `timestamp` − 2초 ≤ 스크립트가 `<work_dir>/.shown/log.jsonl`에 쓴 기록 시각(`at`) ≤ tool_result 줄 `timestamp`인지(transcript 시각이 스크립트 실행을 감싸는지 — 시계가 다른 실행 환경·원격 Bash면 깨진다). 확인: 쓰기 흐름(analyze → push 확인 화면)을 한 번 돌린 세션 transcript로 `python3 tools/hook_replay.py <세션.jsonl>`의 `summary.records`가 `{anchored: n>0, unanchored: 0}`(null이면 확인하지 못한 것) 한계: 자동 백그라운드 전환: 120초를 넘긴 Bash 호출은 Claude Code가 백그라운드로 돌려 tool_result가 먼저 기록되므로, 그 뒤에 쓴 기록(긴 `stage`)은 `at > rts`라 고정되지 않아 판정하지 않는다(옛 transcript 판정은 화면 없음으로 거부했다) |
| 16 | **PowerShell 도구와 hook matcher** | 사내 Claude Code가 PowerShell 도구를 노출하는지(Windows), 노출하면 그 호출이 `hooks.json`의 `Bash` matcher에 걸리는지. 걸리지 않으면 guard 규칙 3~8·10·11과 show_guard가 보지 못하므로 matcher를 더하거나 PowerShell 도구를 deny한다(`08-safety.md §9.1` 한계, L_RESULT ②b P1 후보) |

## 실행 절차

1. 모의 MCP를 함께 붙여 새 세션을 연다 (불러오는 방법은 사외 Claude Code
   버전에서 확인해서 아래 '사외 결과' 표에 적는다):

   ```sh
   claude --mcp-config tests/mocks/mcp.json
   ```

2. 이 디렉토리를 로컬 플러그인으로 등록한다 (`/plugin`).
3. `/probe:ping`을 실행한다.
4. `tests/mocks/plugin-probe/probe-hook.log`를 본다.
5. 결과를 아래 '사외 결과' 표에 적는다 (사내는 `SITE_PROFILE.md`).

## 사외 결과 (S1 예비, 2026-10-01)

2026-10-01, Claude Code 2.1.286(Windows), 헤드리스 `claude -p --plugin-dir <dir> --mcp-config tests/mocks/mcp.json`으로 확인.

| # | 항목 | 사외 결과 | 비고 |
|---|---|---|---|
| 1 | 플러그인 로컬 로드 | ✅ `--plugin-dir`로 로드 | init에 `probe@inline`, 슬래시 목록에 `probe:ping`·`probe:probe` |
| 2 | 커맨드 ↔ 스킬 관계 | ✅ 따로 | 커맨드도 `<plugin>:<name>` 스킬 목록에 같이 뜬다. `/probe:probe`는 스킬 본문만 쓰고 커맨드를 부르지 않는다 |
| 3 | `${CLAUDE_PLUGIN_ROOT}` 치환 | ✅ 커맨드·스킬 본문, hooks.json 모두 치환 | **Bash 도구 프로세스에는 환경 변수 `CLAUDE_PLUGIN_ROOT`가 없다**(hook 프로세스에는 있음). 본문 치환 경로만 쓴다 |
| 4 | hooks (SessionStart / PreToolUse / PostToolUse) | ✅ | 실제 `plugin/hooks/hooks.json`: SessionStart가 `scripts_path` 갱신, PostToolUse `jira_bridge.py`가 MCP 결과를 마스킹 요약으로 교체 |
| 5 | MCP 도구 이름 형식 | ✅ `mcp__mock-jira__jira_fetch_ticket` | hook 입력에 `mcp_server {name, source}` 필드도 있다 |
| 6 | hook matcher `mcp__.*` | ✅ | guard 규칙 2(쓰기 도구 거부) 동작 |
| 7 | 권한 결정 필드 | ✅ `hookSpecificOutput.permissionDecision` | `deny` → 실행 안 됨(`PreToolUse:<tool> hook error: <reason>`), `allow` → allowedTools에 없어도 실행, `ask` → allowedTools에 있어도 확인 요구(헤드리스는 거부). guard 규칙 6·8 deny 확인 |
| 8 | `@SITE_PROFILE.md` import (파일 없음) | ✅ 경고·오류 없음 | 조용히 무시 |
| — | 모의 MCP 붙이기 | ✅ `--mcp-config tests/mocks/mcp.json` | 레포 루트에서 실행(상대 경로). source `dynamic` |
| 10~12 | Stop hook·PreToolUse transcript·여러 그룹 (2026-10-14 예비, 이 개발 환경의 Claude Code 2.1.299 — 사외 확인) | ✅ | `claude -p --plugin-dir`, stream-json. Stop 입력 키 `last_assistant_message`·`stop_hook_active`·`transcript_path` 등, block → user 역할 "Stop hook feedback:\n<reason>" 뒤 새 메시지, 두 번째 Stop은 `stop_hook_active: true`, 연속 계속 한도 8. PreToolUse 때 transcript에 같은 응답의 앞 텍스트 블록이 이미 있음 — **항상은 아니다**: 비동기 기록이라 sm4 eval에서 없던 경우 8건, probe에서 지금 호출(tool_use)은 0.25초 안에 기록됨 → show_guard는 그것이 기록될 때까지 기다린다. 여러 그룹·hook 모두 실행, `deny` 하나면 거부 — 12번 확인: 거부된 tool_result는 `"is_error": true`, content `PreToolUse:Bash hook error: <reason>`(probe transcript). `AskUserQuestion` 입력 모양은 대화형에서만 확인 가능 — 미확인(show_guard는 관대하게 읽는다) |
| 13 | transcript 블록 기록 순서 (2026-10-14) | ✅ | eval 자식 transcript(sm4, 54개 세션) 300개 응답에서 텍스트가 tool_use보다 앞(예외 0). haiku probe: PreToolUse 시점에 지금 tool_use는 아직 없고 0.25초 안에 기록됨 |
| 14 | AskUserQuestion 선택지 상한 (2026-10-15 예비) | — 미확인(대화형에서만) | 이 개발 환경의 도구 정의: 질문당 선택지 2~4개, "Other" 자유 입력. 넘칠 때 실제 동작은 사내 S1에서 대화형으로 확인 |
| 15 | transcript 시각으로 기록 고정 (2026-10-16) | ✅ 사외(사내 S-2 재확인) | 이 PC 개발 세션 1건(2026-10-15) + L2 파일럿 eval 2·18·30·67 세션 `records`(anchored/unanchored): 실측 7/1·7/0·4/0·7/1(via 이전 f08119b 기록 — eval 2·67은 `triage.py run`이 같은 프로세스에서 부른 `db_pr lock` 기록 1건씩이 고정되지 않음) / via 주입 재생 8/0·7/0·4/0·8/0. ②b(3492514)로 eval 2·67 재실행 실측 7/0·8/0(10/16). 한계: 자동 백그라운드 전환: 120초를 넘긴 Bash 호출은 Claude Code가 백그라운드로 돌려 tool_result가 먼저 기록되므로, 그 뒤에 쓴 기록(긴 `stage`)은 `at > rts`라 고정되지 않아 판정하지 않는다(옛 transcript 판정은 화면 없음으로 거부했다). Claude Code 2.1.300 |
| 16 | PowerShell 도구 (2026-10-16 ②b 리뷰) | — 미확인(사내) | 이 PC(Windows) Claude Code에 PowerShell 도구가 있고 `Bash` matcher에 걸리지 않는다. 사내 S-1/S-2에서 노출 여부 확인 |

## 주의

- 여기서 얻은 결과는 **사외 Claude Code 버전 기준**이다. 사내 버전은 다를 수
  있으므로 S-2(사내 보완) 또는 Phase 0에서 다시 확인한다
  (`15-local-draft.md §15.5` S-2).
- `probe-hook.log`는 커밋하지 않는다 (`.gitignore`).
