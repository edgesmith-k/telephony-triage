#!/usr/bin/env python3
"""`code_roots.py find-symbol`: os.walk + 바이트 사전 필터 구현이 예전 구현(`rglob` 전체 읽기)과 같은 결과를 내는지 (R15, O4)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root  # noqa: E402

ROOT = plugin_root()
sys.path.insert(0, str(ROOT / "scripts"))

import code_roots  # noqa: E402


def _legacy_find_symbol(root: Path, key: str, symbol: str) -> list[dict]:
    """사전 필터 도입 전 구현 (그대로 복사, 루트 하나). 비교 기준이다."""
    cls, sep, member = symbol.partition("#")
    name_re = re.compile(rf"\b(?:class|interface|enum|object)\s+{re.escape(cls)}\b") if sep else None
    member_re = re.compile(rf"\b{re.escape(member if sep else cls)}\s*\(")
    matches = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in code_roots.SOURCE_SUFFIXES or not path.is_file():
            continue
        if sep and path.stem != cls:
            text = path.read_text(encoding="utf-8", errors="replace")
            if not name_re.search(text):
                continue
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(root).as_posix()
        for line_no, line in enumerate(text.splitlines(), 1):
            if member_re.search(line):
                matches.append({"ref": f"{key}:{rel}", "line": line_no, "kind": "method" if sep else "function"})
                break
        else:
            if sep:
                matches.append({"ref": f"{key}:{rel}", "line": None, "kind": "class"})
    return matches


def _find(tree: Path, symbol: str) -> list[dict]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = code_roots.main(["find-symbol", symbol, "--roots", f"aosp={tree}", "--plugin-root", str(ROOT)])
    assert code == 0
    return json.loads(out.getvalue())["matches"]


def _tree(tmp: Path) -> Path:
    files = {
        "a.b/X.java": "package a.b;\nclass X {\n    void m(int v) {}\n}\n",
        "a/b.java": "void m(int v) {}\n",
        "a/Y.java": "class Y {\n}\n",
        "a/Z.java": "interface Z {\n    int m();\n}\n",
        "z/Foo.java": "// 이 파일에는 파일 이름이 없다\n",
        "k/Q.kt": "object X { fun m() {} }\n",
        "k/n.txt": "m( X\n",
        "h/x.hpp": "class X;\nint m (int);\n",
    }
    for rel, text in files.items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (tmp / "a" / "bin.java").write_bytes(b"\xff\xfe class X { void m(\n")
    (tmp / "a" / "dir.java").mkdir()
    (tmp / "a" / "dir.java" / "inner.java").write_text("void m(){}\n", encoding="utf-8")
    try:
        os.symlink(tmp / "a.b", tmp / "link", target_is_directory=True)
        os.symlink(tmp / "a" / "b.java", tmp / "filelink.java")
        os.symlink(tmp / "nothing", tmp / "broken.java")
    except OSError:  # 링크를 못 만드는 환경
        pass
    return tmp


def test_find_symbol_matches_legacy(tmp_path):
    tree = _tree(tmp_path)
    for symbol in ("X#m", "Y#m", "Z#m", "Foo#m", "Nope#m", "m", "X", "nothing"):
        want = _legacy_find_symbol(tree, "aosp", symbol)
        assert _find(tree, symbol) == want, symbol
    assert _find(tree, "Foo#m") == [{"ref": "aosp:z/Foo.java", "line": None, "kind": "class"}]
    assert {m["ref"] for m in _find(tree, "X#m")} >= {"aosp:a.b/X.java", "aosp:k/Q.kt", "aosp:a/bin.java"}
