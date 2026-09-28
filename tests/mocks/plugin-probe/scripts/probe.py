#!/usr/bin/env python3
"""`${CLAUDE_PLUGIN_ROOT}` 치환 확인용 스크립트 (14-site.md S1).

커맨드·스킬 본문에서 `${CLAUDE_PLUGIN_ROOT}/scripts/probe.py`로 불린다.
이 스크립트가 실행됐다는 것 자체가 치환이 된다는 뜻이다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

print(
    json.dumps(
        {
            "ok": True,
            "argv0": sys.argv[0],
            "resolved_self": str(Path(__file__).resolve()),
            "CLAUDE_PLUGIN_ROOT": os.environ.get("CLAUDE_PLUGIN_ROOT"),
            "cwd": os.getcwd(),
            "note": "argv0에 ${CLAUDE_PLUGIN_ROOT} 문자열이 그대로 있으면 치환이 안 된 것이다.",
        },
        ensure_ascii=False,
        indent=2,
    )
)
