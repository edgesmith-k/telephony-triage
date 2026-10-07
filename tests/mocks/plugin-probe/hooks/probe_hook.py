#!/usr/bin/env python3
"""빈 플러그인 실험용 hook (14-site.md S1).

stdin으로 받은 hook 입력 JSON을 그대로 `probe-hook.log`에 한 줄씩 적고
**아무것도 막지 않는다**. 확인하려는 것:

- hook이 실제로 불리는가 (SessionStart, PreToolUse)
- matcher `Bash`와 `mcp__.*`가 걸리는가
- **MCP 도구 이름이 어떤 형식으로 오는가** (`mcp__<server>__<tool>`인지)
- 권한 결정 응답 형식(`allow`/`deny`/`ask`)이 먹히는가
  — `--decide <값>`으로 시험한다. 기본은 아무 결정도 내지 않는다.

결과는 `tests/mocks/plugin-probe/README.md`의 '사외 결과' 표에 적는다(사내는 `SITE_PROFILE.md`).
사내 버전은 다를 수 있으므로 S-2에서 다시 확인한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

LOG_NAME = "probe-hook.log"


def log_path() -> Path:
    root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    base = Path(root) if root else Path(__file__).resolve().parent.parent
    return base / LOG_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="probe_hook.py", description=__doc__)
    parser.add_argument("--event", default="unknown")
    parser.add_argument(
        "--decide",
        default=None,
        choices=["allow", "deny", "ask"],
        help="권한 결정 필드를 시험할 때만 쓴다 (기본: 결정하지 않음)",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read() if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {"_unparsed": raw[:2000]}

    record = {
        "event": args.event,
        "plugin_root_env": os.environ.get("CLAUDE_PLUGIN_ROOT"),
        "tool_name": payload.get("tool_name"),
        "keys": sorted(payload) if isinstance(payload, dict) else None,
        "payload": payload,
    }
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    if args.decide:
        # 권한 결정 필드 이름은 버전에 따라 다를 수 있다 (08-safety.md §9).
        # 실제 필드 이름은 이 실험으로 확인해서 tests/mocks/plugin-probe/README.md '사외 결과' 표에 적는다.
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": args.decide,
                        "permissionDecisionReason": "probe 실험",
                    }
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
