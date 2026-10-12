#!/usr/bin/env python3
"""모의 GitHub Issues MCP 도구를 명령줄에서 부른다 (스킬 eval direct 모드 전용, 트래커 범용화 §6-1).

eval direct 모드에서는 MCP 도구 호출 `mcp__mock-github-issues__<tool>({...})`을 이 명령으로 대신한다.
응답은 MCP `tools/call` 결과의 `content[0].text`와 같은 JSON이고, 오류면 종료 코드 1이다.
쓰기 도구(`add_issue_comment`, `update_issue`, `create_pull_request`)를 부르면 서버와 똑같이 `MOCK_GH_ISSUES_WRITE_LOG`에 남는다.

    python3 tests/mocks/github_issues_mcp/call.py <tool 또는 mcp__mock-github-issues__<tool>> '<arguments JSON>'
    python3 tests/mocks/github_issues_mcp/call.py --list      # 도구 이름과 입력 스키마 (MCP tools/list와 같은 내용)

이슈 디렉토리는 `MOCK_GH_ISSUES_DIR`(없으면 `tests/mocks/github_issues`).
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
