#!/usr/bin/env python3
"""config.py — 사용자 config와 사내 기본값 (02-config.md, contracts.md §3.2).

Phase D0 범위: `site-defaults.yaml` 로드와 "사내 기본값 없음" 종료 코드 2 경로만.
`check`(스키마·생성기·파서 백엔드·gh 인증 호환성 판정), `set`,
`sync-scripts-path`는 Phase 6에서 구현한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import site_defaults  # noqa: E402
from common.exitcodes import OK, USAGE  # noqa: E402

PHASE6 = {"check", "set", "sync-scripts-path"}


def main(argv: list[str] | None = None) -> int:
    # 공통 옵션은 부모 파서에 둔다 (contracts.md §3.2 "--db 위치"와 같은 이유:
    # 서브커맨드 앞뒤 어디에 줘도 동작해야 한다).
    common = argparse.ArgumentParser(add_help=False)
    # default=SUPPRESS: 서브커맨드 파서가 부모에서 받은 값을 덮어쓰지 않게 한다.
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="JSON으로 출력",
    )
    common.add_argument(
        "--plugin-root",
        default=argparse.SUPPRESS,
        help="플러그인 루트 (기본: ${CLAUDE_PLUGIN_ROOT})",
    )

    parser = argparse.ArgumentParser(
        prog="config.py", description=__doc__, parents=[common]
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (
        ("show", "해석된 설정을 보여준다"),
        ("site-defaults", "site-defaults.yaml 내용을 JSON으로 낸다"),
        ("check", "[Phase 6] 호환성 판정"),
        ("set", "[Phase 6] 설정값 변경"),
        ("sync-scripts-path", "[Phase 6] plugin.scripts_path 갱신"),
    ):
        sub.add_parser(name, help=help_text, parents=[common])
    args = parser.parse_args(argv)
    use_json = getattr(args, "json", False)
    root_opt = getattr(args, "plugin_root", None)

    # 어떤 서브커맨드든 사내 기본값이 먼저다. 없으면 종료 코드 2.
    defaults = site_defaults.load_or_exit(root_opt)

    if args.cmd in PHASE6:
        print(
            f"'{args.cmd}'는 Phase 6에서 구현한다 (02-config.md §4). "
            "Phase D0에서는 site-defaults 로드만 한다.",
            file=sys.stderr,
        )
        return USAGE

    if args.cmd == "site-defaults":
        print(json.dumps(defaults, ensure_ascii=False, indent=2, sort_keys=True))
        return OK

    root = site_defaults.plugin_root() if root_opt is None else Path(root_opt)
    payload = {
        "plugin_root": str(root),
        "site_defaults": str(root / site_defaults.FILENAME),
        "user_config": "Phase 6에서 구현",
        "site_defaults_keys": sorted(defaults),
    }
    if use_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
