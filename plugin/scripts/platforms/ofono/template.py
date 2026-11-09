"""oFono 모듈 스킬 템플릿의 고유 문서 규칙(`TemplateMeta.doc_checks`, H C1+D R23·R41): D-Bus 이름 허용 목록과 데몬 역할 표.

표준 라이브러리만 쓴다(`platforms/ofono/__init__`이 불러온다 — 17-platforms §1-2). 점검은 `(점검 이름, 루트 상대 경로, 줄, rule)`
튜플만 돌려주고 파일 내용은 담지 않는다(`skillcheck.template_findings`가 finding으로 바꾼다).
"""

from __future__ import annotations

import re
from pathlib import Path

DBUS_BASE = ("org.ofono", "org.freedesktop.DBus")
DBUS_RX = re.compile(r"\b(?:org|com|net|fi|de)\.[A-Za-z0-9_]+\.[A-Za-z0-9_.]+")
COMPONENTS_DOC = "_common/components.md"     # 역할 표(C1D 보정 §3.1): `| 역할 | 지금 이름 | 구 이름 | 층 | 비고 |`


def dbus_allowed(block) -> frozenset[str]:
    """허용 D-Bus 이름: `org.ofono`·`org.freedesktop.DBus`와 modules.yaml `platforms.ofono.modules.*.dbus` 합집합.
    이름은 원소와 같거나 `원소 + "."`으로 시작하면 허용이다(`dbus_violations`). `block`은 그 플랫폼 블록(없으면 None)."""
    names = set(DBUS_BASE)
    mods = block.get("modules") if isinstance(block, dict) else None
    for mb in (mods.values() if isinstance(mods, dict) else ()):
        if isinstance(mb, dict) and isinstance(mb.get("dbus"), list):
            names.update(v for v in mb["dbus"] if isinstance(v, str) and v)
    return frozenset(names)


def dbus_violations(text: str, allowed) -> list[tuple[int, str]]:
    """허용 밖 D-Bus 이름 `(줄 번호, 이름)` 목록. 문장 끝 `.`은 이름에서 뺀다."""
    out = []
    for no, line in enumerate(text.split("\n"), 1):
        for m in DBUS_RX.finditer(line):
            name = m.group(0).rstrip(".")
            if not any(name == a or name.startswith(a + ".") for a in allowed):
                out.append((no, name))
    return out


def _docs(root: Path) -> list[Path]:
    base = root / "ofono"
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.md") if "evals" not in p.relative_to(base).parts)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def daemon_table_check(root: Path, block) -> list[tuple[str, str, int | None, str | None]]:
    """`데몬 표`: modules.yaml 블록의 daemons 값마다 `ofono/_common/components.md` 역할 표의 지금·구 이름 칸에 그 이름(rule = 이름)."""
    if not isinstance(block, dict):
        return []
    daemons = list((block.get("common") or {}).get("daemons") or [])
    for mb in (block.get("modules") or {}).values():
        if isinstance(mb, dict):
            daemons.extend(mb.get("daemons") or [])
    comp = root / "ofono" / COMPONENTS_DOC
    table = _read(comp) if comp.is_file() else ""
    listed = set()          # 둘째·셋째 칸, `, `로 나눔
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        for cell in cells[1:3]:
            listed |= {n.strip().strip("`") for n in cell.split(", ")}
    return [("데몬 표", "ofono/" + COMPONENTS_DOC, None, name)
            for name in dict.fromkeys(d for d in daemons if isinstance(d, str)) if name not in listed]


def dbus_check(root: Path, block) -> list[tuple[str, str, int | None, str | None]]:
    """`D-Bus 이름`: oFono 문서의 허용 밖 이름(`dbus_violations`, rule = 이름)."""
    if not isinstance(block, dict):
        return []
    allowed = dbus_allowed(block)
    out = []
    for path in _docs(root):
        rel = path.relative_to(root).as_posix()
        out += [("D-Bus 이름", rel, no, name) for no, name in dbus_violations(_read(path), allowed)]
    return out
