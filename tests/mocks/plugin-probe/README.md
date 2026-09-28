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
   버전에서 확인해서 `DRAFT_NOTES.md`에 적는다):

   ```sh
   claude --mcp-config tests/mocks/mcp.json
   ```

2. 이 디렉토리를 로컬 플러그인으로 등록한다 (`/plugin`).
3. `/probe:ping`을 실행한다.
4. `tests/mocks/plugin-probe/probe-hook.log`를 본다.
5. 결과를 `DRAFT_NOTES.md`의 "사외 Claude Code 실험 결과" 표에 적는다.

## 주의

- 여기서 얻은 결과는 **사외 Claude Code 버전 기준**이다. 사내 버전은 다를 수
  있으므로 S-2(사내 보완) 또는 Phase 0에서 다시 확인한다
  (`15-local-draft.md §15.5` S-2).
- `probe-hook.log`는 커밋하지 않는다 (`.gitignore`).
