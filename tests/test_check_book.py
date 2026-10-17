"""tools/check_book.py: 정상 문서는 통과, 깨진 링크·외부 요청·없는 커맨드는 잡는다."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import check_book  # noqa: E402

OK = '<html><body><h2 id="a">A</h2><a href="#a">A</a><p>/telephony-triage:analyze</p></body></html>\n'


def _root(tmp_path: Path, html: str) -> Path:
    (tmp_path / "plugin" / "commands").mkdir(parents=True)
    (tmp_path / "plugin" / "commands" / "analyze.md").write_text("x", encoding="utf-8")
    (tmp_path / "doc.html").write_text(html, encoding="utf-8")
    return tmp_path


def _check(tmp_path: Path, html: str) -> list[str]:
    root = _root(tmp_path, html)
    return check_book.check([root / "doc.html"], root)


def test_ok(tmp_path):
    assert _check(tmp_path, OK) == []


def test_broken_link(tmp_path):
    out = _check(tmp_path, OK.replace('href="#a"', 'href="#nope"'))
    assert len(out) == 1 and "link" in out[0] and "doc.html:1" in out[0]


def test_external_request(tmp_path):
    out = _check(tmp_path, OK.replace("<body>", '<head><link rel="stylesheet" href="https://x.example/a.css"></head><body>'))
    assert len(out) == 1 and "external" in out[0]


def test_missing_command(tmp_path):
    out = _check(tmp_path, OK.replace(":analyze", ":nope"))
    assert len(out) == 1 and "command" in out[0] and "nope" in out[0]


def test_repo_docs_clean():
    assert check_book.check(check_book.default_targets()) == []


def test_missing_anchor_in_other_file(tmp_path):
    root = _root(tmp_path, OK.replace('href="#a"', 'href="other.html#gone"'))
    (root / "other.html").write_text('<p id="here">x</p>\n', encoding="utf-8")
    out = check_book.check([root / "doc.html"], root)
    assert len(out) == 1 and "link" in out[0] and "other.html#gone" in out[0]


def test_duplicate_id(tmp_path):
    out = _check(tmp_path, OK.replace("</body>", '<p id="a">again</p></body>'))
    assert len(out) == 1 and "dup-id" in out[0]


def test_banned_wording(tmp_path):
    out = _check(tmp_path, OK.replace("<p>", "<p>같은 로그면 누가 돌려도 같다 "))
    assert len(out) == 1 and "wording" in out[0]


def test_css_import(tmp_path):
    out = _check(tmp_path, OK.replace("<body>", "<head><style>\n@import url('https://x.example/f.css');\n</style></head><body>"))
    assert len(out) == 1 and "external" in out[0] and "x.example" in out[0] and "doc.html:2" in out[0]


def test_promo_common_sections_differ(tmp_path):
    a, b = (REPO / p for p in check_book.PROMO_PAIR)
    ca, cb = tmp_path / "02.html", tmp_path / "19.html"
    ca.write_text(a.read_text(encoding="utf-8"), encoding="utf-8")
    src = b.read_text(encoding="utf-8")
    assert check_book.check_common(ca, b) == []
    marker = '<p class="kicker">Why</p>'
    assert marker in src
    cb.write_text(src.replace(marker, marker + "!", 1), encoding="utf-8")
    out = check_book.check_common(ca, cb)
    assert len(out) == 1 and "section#why" in out[0] and "common" in out[0]


def test_promo_toc_order_differs(tmp_path):
    a, b = (REPO / p for p in check_book.PROMO_PAIR)
    cb = tmp_path / "19.html"
    src = b.read_text(encoding="utf-8")
    swapped, n = re.subn(r'(    <a href="#why">[^\n]*\n)(    <a href="#result">[^\n]*\n)', r"\2\1", src, count=1)
    assert n == 1
    cb.write_text(swapped, encoding="utf-8")
    out = check_book.check_common(a, cb)
    assert len(out) == 1 and "목차" in out[0]


def test_promo_hero_ask_may_differ(tmp_path):
    a, b = (REPO / p for p in check_book.PROMO_PAIR)
    cb = tmp_path / "19.html"
    src = b.read_text(encoding="utf-8")
    changed, n = re.subn(r'(<p class="hero-ask">)[^\n]*?(</p>)', r"\1다른 안내 한 줄\2", src, count=1)
    assert n == 1
    cb.write_text(changed, encoding="utf-8")
    assert check_book.check_common(a, cb) == []


def test_promo_hero_other_text_differs(tmp_path):
    a, b = (REPO / p for p in check_book.PROMO_PAIR)
    cb = tmp_path / "19.html"
    src = b.read_text(encoding="utf-8")
    marker = '<p class="rc-cond">'
    assert marker in src
    cb.write_text(src.replace(marker, marker + "!", 1), encoding="utf-8")
    out = check_book.check_common(a, cb)
    assert len(out) == 1 and "header1" in out[0]
