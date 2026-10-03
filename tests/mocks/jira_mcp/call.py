#!/usr/bin/env python3
"""모의 Jira MCP 도구를 명령줄에서 부른다 (스킬 eval 전용).

스킬 eval은 서브에이전트가 돌리는데, 서브에이전트 세션에는 `mock-jira` MCP 서버가 등록돼 있지 않다.
그래서 eval 환경에서만 MCP 도구 호출 `mcp__mock-jira__<tool>({...})`을 이 명령으로 대신한다.
응답은 MCP `tools/call` 결과의 `content[0].text`와 같은 JSON이고, 오류면 종료 코드 1이다.
쓰기 도구(`jira_post_comment`, `jira_move_ticket`)를 부르면 서버와 똑같이 `MOCK_JIRA_WRITE_LOG`에 남는다
(eval 채점이 "쓰기 도구를 부르지 않았다"를 이 파일로 확인한다).

    python3 tests/mocks/jira_mcp/call.py <tool 또는 mcp__mock-jira__<tool>> '<arguments JSON>'
    python3 tests/mocks/jira_mcp/call.py --list      # 도구 이름과 입력 스키마 (MCP tools/list와 같은 내용)

티켓 디렉토리는 `MOCK_JIRA_DIR`(없으면 `tests/mocks/jira`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    if argv[0] == "--list":
        print(json.dumps([{"name": f"mcp__{server.SERVER_NAME}__{t['name']}", "description": t["description"],
                           "inputSchema": t["inputSchema"]} for t in server.TOOLS], ensure_ascii=False, indent=2))
        return 0
    name = argv[0].split("__")[-1]
    args = json.loads(argv[1]) if len(argv) > 1 else {}
    result, is_error = server.call_tool(name, args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if is_error else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
