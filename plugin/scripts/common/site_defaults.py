"""`plugin/site-defaults.yaml` 로드 (15-local-draft.md §15.1, 02-config.md).

런타임 코드는 "사내/사외 모드"를 판별하지 않는다. 플러그인 루트에
`site-defaults.yaml`이 있으면 쓰고, 없으면 멈춘다(종료 코드 2).
`site-defaults.example.yaml`은 **읽지 않는다** — 테스트 헬퍼
(`tests/helpers/make_plugin_root.py`)가 그것을 `site-defaults.yaml`로
복사한 임시 플러그인 루트를 만들어 `${CLAUDE_PLUGIN_ROOT}`로 준다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import yamlio
from .exitcodes import USAGE

FILENAME = "site-defaults.yaml"
EXAMPLE_FILENAME = "site-defaults.example.yaml"


class SiteDefaultsMissing(Exception):
    """`site-defaults.yaml`이 없다 (사내 S-3 미완료)."""

    def __init__(self, root: Path, has_example: bool):
        self.root = root
        self.has_example = has_example
        super().__init__(f"site-defaults not found under {root}")


def plugin_root() -> Path:
    """`${CLAUDE_PLUGIN_ROOT}`. 없으면 이 파일 위치에서 거슬러 올라간다
    (`<root>/scripts/common/site_defaults.py`)."""
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def load(root: Path | None = None) -> dict:
    """site-defaults를 읽어 dict로 준다. 없으면 SiteDefaultsMissing."""
    root = Path(root) if root is not None else plugin_root()
    path = root / FILENAME
    if not path.is_file():
        raise SiteDefaultsMissing(root, (root / EXAMPLE_FILENAME).is_file())
    with path.open(encoding="utf-8") as fh:
        data = yamlio.safe_load(fh)
    return data if isinstance(data, dict) else {}


def load_or_exit(root: Path | None = None) -> dict:
    """모든 커맨드·스크립트의 진입점에서 쓴다. 없으면 안내 후 종료 코드 2."""
    try:
        return load(root)
    except SiteDefaultsMissing as exc:
        print(explain(exc), file=sys.stderr)
        raise SystemExit(USAGE)


def explain(exc: SiteDefaultsMissing) -> str:
    lines = [
        "플러그인 관리자가 사이트 설정(site-defaults.yaml)을 아직 올리지 않았습니다. "
        "이 메시지를 관리자에게 전달하세요.",
        "  [관리자] 사내 기본값 없음 (S-3 미완료): "
        f"{exc.root / FILENAME} 이(가) 없어 실행할 수 없습니다.",
        "    - 사내: S-3에서 site-defaults.yaml을 만들어 커밋하세요 "
        "(15-local-draft.md §15.5).",
    ]
    if exc.has_example:
        lines.append(
            "    - 사외 테스트: 개발 레포의 plugin/ 을 직접 ${CLAUDE_PLUGIN_ROOT}로 주지 말고,"
        )
        lines.append(
            "      tests/helpers/make_plugin_root.py 가 만든 임시 플러그인 루트를 쓰세요 "
            "(15-local-draft.md §15.1)."
        )
    return "\n".join(lines)
