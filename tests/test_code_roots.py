#!/usr/bin/env python3
"""`code_roots.py`
- find-symbol: os.walk + 바이트 사전 필터 구현이 예전 구현(`rglob` 전체 읽기)과 같은 결과를 내는지 (R15, O4).
- validate: 플랫폼 구성요소(데몬) 루트의 필수 디렉토리·버전 추정(`component_versions`, 17-platforms §9 K15),
  구성요소 없는 플랫폼(android)은 출력 불변. 뼈대 DB의 `code_root_keys` 주석.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root, run, run_json, tmp  # noqa: E402

ROOT = plugin_root()
sys.path.insert(0, str(ROOT / "scripts"))

import code_roots  # noqa: E402
import platforms  # noqa: E402


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


# -- validate: 구성요소(데몬) 루트 (17-platforms §9 K15). 이름·키·파일은 placeholder --------------------------------

COMPONENTS = {
    "ofono": {"idents": ["ofonod"], "root_key": "ofono"},
    "daemon-a": {"idents": ["daemon-a"], "root_key": "daemon_a",
                 "source_tree": {"required_dirs": ["src"],
                                 "version_sources": [{"file": "VERSION", "regex": "^version=(\\S+)"}]}},
    "daemon-b": {"idents": ["daemon-b"], "root_key": "daemon_b"},
}
ON = {"name": "android", "enabled": ["android", "ofono"]}


def _trees(base: Path) -> dict[str, Path]:
    ofono, a, b = base / "ofono", base / "daemon-a", base / "daemon-b"
    (ofono / "src").mkdir(parents=True)
    (ofono / "configure.ac").write_text("AC_INIT([ofono], [2])\n", encoding="utf-8")
    (a / "src").mkdir(parents=True)
    (a / "VERSION").write_text("version=1.4\n", encoding="utf-8")
    b.mkdir()
    return {"ofono": ofono, "daemon_a": a, "daemon_b": b}


def _validate(root: Path, roots: dict, expect=0) -> dict:
    text = ",".join(f"{k}={v}" for k, v in roots.items())
    return run_json("code_roots.py", ["validate", text, "--platform", "ofono"], expect=expect, root=root,
                    env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})


def test_validate_component_roots():
    root = plugin_root("ofono-components", platform={**ON, "others": {"ofono": {"components": COMPONENTS}}})
    trees = _trees(tmp("tt-comp-"))
    out = _validate(root, trees)     # DB 없음 → 루트 키 = 기본 키 + 구성요소 루트 키
    assert out["valid"] and out["errors"] == [], out
    assert out["estimated_version"] == "2"
    assert out["component_versions"] == {"daemon_a": "1.4", "daemon_b": None}    # source_tree 없는 구성요소는 None
    assert out["warnings"] == []                                                  # 참고용, --version과 비교하지 않음
    assert _validate(root, {"ofono": trees["ofono"]})["component_versions"] == {}  # 구성요소 루트는 선택

    (trees["daemon_a"] / "src").rmdir()
    bad = _validate(root, trees, expect=2)
    assert not bad["valid"] and bad["errors"] == [f"daemon_a 루트에 src가 없습니다: {trees['daemon_a']}"]
    assert bad["component_versions"] == {"daemon_a": "1.4", "daemon_b": None}

    nokey = _validate(root, {**trees, "daemon_c": trees["daemon_b"]}, expect=2)  # 구성요소에 없는 키는 그대로 거부
    assert any("daemon_c" in e for e in nokey["errors"])
    assert "ofono 루트가 필요합니다." in _validate(root, {"daemon_a": trees["daemon_a"]}, expect=2)["errors"]  # 주 루트 필수(K15)


def test_validate_default_ofono_components_and_android_unchanged():
    trees = _trees(tmp("tt-comp-"))
    out = _validate(plugin_root("ofono-on", platform=ON), {"ofono": trees["ofono"]})
    assert out["component_versions"] == {}     # 기본 구성요소(ofonod)의 루트는 주 루트 → 위 estimated_version
    # android: 구성요소 없음 → 키 없음(바이트 동일)
    assert platforms.load({}, "android").components == ()
    aosp = REPO / "tests" / "mocks" / "src" / "android16"
    result = code_roots.validate({"aosp": str(aosp)}, ["aosp"], "16")
    assert list(result) == ["roots", "valid", "errors", "warnings", "estimated_version", "version"]
    proc = run("code_roots.py", ["validate", f"aosp={aosp}", "--version", "16"],
               env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})
    assert proc.returncode == 0, proc.stderr
    assert "component_versions" not in json.loads(proc.stdout)


def test_skeleton_root_keys_todo():
    out = tmp("tt-ofono-skel-") / "db"
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out), "--platform", "ofono"],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    cfg = (out / "issue-db.config.yaml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^code_root_keys: \[ofono\]   # TODO\(SITE:S27\) 구성요소\(데몬\)마다 소스 루트 키", cfg)
    assert "구성요소(데몬)가 여럿이면 ident마다 한 줄" in (out / "parser-rules" / "tags.yaml").read_text(encoding="utf-8")
