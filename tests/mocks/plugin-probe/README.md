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

## 주의

- 여기서 얻은 결과는 **사외 Claude Code 버전 기준**이다. 사내 버전은 다를 수
  있으므로 S-2(사내 보완) 또는 Phase 0에서 다시 확인한다
  (`15-local-draft.md §15.5` S-2).
- `probe-hook.log`는 커밋하지 않는다 (`.gitignore`).
