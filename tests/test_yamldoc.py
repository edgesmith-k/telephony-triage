#!/usr/bin/env python3
"""`common/yamldoc.py` 엔티티 단위 다시 쓰기 회귀 (사내 보고 import-20261018 1번).

같은 섹션을 다시 쓸 때마다 다음 최상위 키 앞 구분 줄(빈 줄·주석)이 두 배로 늘던 문제:
`ListSection.render`와 `replace_block`이 둘 다 마지막 항목 뒤 구분 줄을 넣었다.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, plugin_root  # noqa: E402

sys.path.insert(0, str(plugin_root() / "scripts"))

from common import yamldoc, yamlio  # noqa: E402

RIL = (SAMPLE / "parser-rules/ril.yaml").read_text(encoding="utf-8")


def _add(text: str, section: str, name: str) -> str:
    data = yamlio.loads(text)
    lines = text.splitlines(keepends=True)
    old = data[section]
    new = old + [{"name": name, "category": "data", "added_for": "DATA-001", "added_on": "2026-10-28", "reason": "r"}]
    body = yamldoc.ListSection(lines, section, old).render(old, new, key_of=lambda r: r["name"], flow=True)
    return "".join(yamldoc.replace_block(lines, section, body))


def test_rewriting_same_section_keeps_separator_between_top_keys():
    """같은 섹션을 여러 번 다시 써도 다음 최상위 키 앞 구분 줄은 한 벌만 남는다."""
    text = RIL
    for n in range(3):
        text = _add(text, "requests", f"REQ_{n}")
    assert "\n\n\nunsolicited:" not in text and "\n\nunsolicited:" in text
    once = _add(RIL, "requests", "REQ_0")
    assert len(once.splitlines()) == len(RIL.splitlines()) + 1        # 항목 한 줄만 늘어난다
    assert yamlio.loads(text)["requests"][-1]["name"] == "REQ_2"


def test_last_section_trailing_lines_not_doubled():
    """마지막 블록 뒤 빈 줄·주석도 두 번 써서 한 벌."""
    text = "a: 1\n\nitems:\n  - {k: x}\n\n# 끝 주석\n"
    data = yamlio.loads(text)
    for n in range(2):
        lines = text.splitlines(keepends=True)
        old = data["items"]
        new = old + [{"k": f"y{n}"}]
        body = yamldoc.ListSection(lines, "items", old).render(old, new, key_of=lambda r: r["k"], flow=True)
        text = "".join(yamldoc.replace_block(lines, "items", body))
        data["items"] = new
    assert text.endswith("  - {k: y1}\n\n# 끝 주석\n") and text.count("# 끝 주석") == 1


def test_unchanged_render_is_identity():
    """값이 같으면 다시 써도 바이트가 같다(구분 줄 포함)."""
    lines = RIL.splitlines(keepends=True)
    data = yamlio.loads(RIL)
    for section in ("requests", "unsolicited"):
        body = yamldoc.ListSection(lines, section, data[section]).render(
            data[section], data[section], key_of=lambda r: r["name"], flow=True)
        lines = yamldoc.replace_block(lines, section, body)
    assert "".join(lines) == RIL
