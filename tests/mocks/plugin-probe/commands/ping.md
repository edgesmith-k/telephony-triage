---
description: 플러그인 로드와 ${CLAUDE_PLUGIN_ROOT} 치환을 확인한다
---

아래를 순서대로 하고 결과만 보고해라.

1. Bash로 다음을 실행한다 (hook이 걸리는지도 함께 본다):

   ```sh
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/probe.py"
   ```

   - 명령이 그대로 실행됐으면 `${CLAUDE_PLUGIN_ROOT}`가 **치환된다**.
   - `${CLAUDE_PLUGIN_ROOT}`라는 문자열 그대로 경로 오류가 나면 **치환되지 않는다**.
     이때는 config의 `plugin.scripts_path`를 읽어 쓰는 방식으로 바꿔야 한다
     (`01-architecture.md §3`).

2. 모의 Jira MCP가 붙어 있으면 `jira_fetch_ticket`(티켓 `MOCK-1001`)을 한 번 부른다.
   붙어 있지 않으면 "MCP 없음"이라고만 적는다.

3. `${CLAUDE_PLUGIN_ROOT}/probe-hook.log`를 읽어서 각 항목의 `tool_name` 값을 그대로 보고한다.
   MCP 도구 이름이 `mcp__<server>__<tool>` 형식인지 확인한다.

4. 이 세션에서 `CLAUDE.md`의 `@SITE_PROFILE.md` import에 대한 오류·경고를 본 적이 있는지 적는다.
