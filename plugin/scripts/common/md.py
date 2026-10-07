"""마크다운 표·한 줄 escape — 생성 파일(`db_build`), 검색·요약 렌더, `tools/gen_contracts`가 함께 쓴다."""

from __future__ import annotations


def line(value) -> str:
    """한 줄로 보여야 하는 값: 개행·연속 공백을 공백 하나로 (줄 머리에 가짜 항목을 심지 못하게)."""
    return " ".join(str("" if value is None else value).split())


def cell(value) -> str:
    """표 텍스트 셀: `line` 뒤 `\\`·`|` escape."""
    return line(value).replace("\\", "\\\\").replace("|", "\\|")


def code(value) -> str:
    """표 안 코드 스팬 내용: 개행 → 공백, `|`만 escape. 코드 스팬 안에서는 `\\` escape가 먹지 않고
    (GFM 표는 `\\|`만 처리한다) 연속 공백도 그대로 둔다 — 정규식을 복사한 독자가 같은 값을 얻는다."""
    return str("" if value is None else value).replace("\n", " ").strip().replace("|", "\\|")


def fixed_in_builds(items) -> list[str]:
    """`fixed_in`·history의 `[{branch, build}]` → 표시용 빌드 목록(빌드가 없으면 브랜치, 중복 제거)."""
    out = []
    for item in items or []:
        value = (item.get("build") or item.get("branch")) if isinstance(item, dict) else item
        if value and str(value) not in out:
            out.append(str(value))
    return out
