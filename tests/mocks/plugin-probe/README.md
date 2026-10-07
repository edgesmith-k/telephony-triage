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

## 주의

- 여기서 얻은 결과는 **사외 Claude Code 버전 기준**이다. 사내 버전은 다를 수
  있으므로 S-2(사내 보완) 또는 Phase 0에서 다시 확인한다
  (`15-local-draft.md §15.5` S-2).
- `probe-hook.log`는 커밋하지 않는다 (`.gitignore`).
