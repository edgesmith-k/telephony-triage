"""GLOSSARY.md 표 읽기 (06-collaboration.md §6.9).

용어집은 메인테이너 소유다. 여기서는 읽기만 한다: 섹션(`## <제목>`) 아래의 마크다운 표 행을 셀 목록으로 돌려준다.
"""

from __future__ import annotations

from pathlib import Path

SEARCH_ALIAS_HEADING = "검색 별칭"


def table(root: Path, heading: str) -> list[list[str]]:
    """`## <heading>` 섹션의 표 데이터 행(머리글·구분선 제외)의 셀 목록. 파일·섹션이 없으면 빈 목록."""
    path = Path(root) / "GLOSSARY.md"
    if not path.is_file():
        return []
    rows: list[list[str]] = []
    in_section, header_seen = False, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section, header_seen = line[3:].strip() == heading, False
            continue
        if not in_section or not line.startswith("|") or set(line) <= set("|-: "):
            continue
        if not header_seen:          # 첫 표 행은 머리글
            header_seen = True
            continue
        rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def search_aliases(root: Path) -> list[tuple[list[str], list[str]]]:
    """`## 검색 별칭` 표: `(질의 단어 앞부분 목록, 함께 찾을 말 목록)` (소문자). search 전용이며 분류·매칭에는 쓰지 않는다."""
    out = []
    for cols in table(root, SEARCH_ALIAS_HEADING):
        if len(cols) < 2:
            continue
        keys = [k.strip().lower() for k in cols[0].split(",") if k.strip()]
        values = [v.strip().lower() for v in cols[1].split(",") if v.strip()]
        if keys and values:
            out.append((keys, values))
    return out
