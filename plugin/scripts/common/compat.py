"""이슈 DB가 고정한 파서 백엔드·외부 파서와 현재 환경 비교
(contracts.md §기존 자산 연결 계약, 16-existing-assets.md §16.3).

- 파서 백엔드: `issue-db.config.yaml`의 `parser_backend: {name, min_version}`
- 외부 파서: `issue-db.config.yaml`의 `external_parsers: {<category>: {adapter, min_version}}`

불일치 처리는 호출자가 정한다: 분석(`parse_logcat`)은 경고 후 진행,
`config.py check`는 쓰기 불가, `db_regress`는 종료 코드 2.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

BACKEND_MISMATCH = "parser-backend-mismatch"
EXTERNAL_MISMATCH = "external-parser-mismatch"


def parse_version(value) -> tuple[int, ...]:
    """`0.1.0`, `0.0.1-mock`, `2` → 숫자 튜플. `-` 뒤(접미사)는 무시한다."""
    text = str(value if value is not None else "").split("-", 1)[0]
    return tuple(int(n) for n in re.findall(r"\d+", text)) or (0,)


def version_ge(have, need) -> bool:
    a, b = list(parse_version(have)), list(parse_version(need))
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return a >= b


def load_db_config(db_root: str | Path) -> dict:
    path = Path(db_root) / "issue-db.config.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def check_parser_backend(db_cfg: dict, name: str, version: str) -> list[dict]:
    pin = db_cfg.get("parser_backend")
    if not isinstance(pin, dict) or not pin.get("name"):
        return []
    need_name, need_ver = pin["name"], pin.get("min_version", "0")
    if name != need_name or not version_ge(version, need_ver):
        return [
            {
                "code": BACKEND_MISMATCH,
                "message": (
                    f"백엔드 불일치 — 이슈 DB는 {need_name} ≥ {need_ver}, 현재 {name} {version}. "
                    "결과가 팀 기준과 다를 수 있음"
                ),
            }
        ]
    return []


def check_external(db_cfg: dict, configured: dict[str, dict]) -> list[dict]:
    """`configured`: `{category: {adapter, version, available}}` (현재 환경).
    이슈 DB `external_parsers`에 고정된 카테고리마다 어댑터가 있고 버전이 충분한지 본다."""
    pins = db_cfg.get("external_parsers") or {}
    warnings: list[dict] = []
    for category, pin in sorted(pins.items()):
        pin = pin or {}
        have = configured.get(category)
        need = f"{pin.get('adapter')} ≥ {pin.get('min_version', '0')}"
        if not have or not have.get("available"):
            reason = "어댑터 없음"
        elif have.get("adapter") != pin.get("adapter"):
            reason = f"어댑터가 다름({have.get('adapter')})"
        elif not version_ge(have.get("version"), pin.get("min_version", "0")):
            reason = f"버전이 낮음({have.get('version')})"
        else:
            continue
        warnings.append(
            {
                "code": EXTERNAL_MISMATCH,
                "message": f"외부 파서 불일치 [{category}] — 이슈 DB는 {need}, {reason}",
            }
        )
    return warnings
