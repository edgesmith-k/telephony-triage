#!/usr/bin/env python3
"""I4: YAML 읽기 단일 입구 `common/yamlio.py` (libyaml `CSafeLoader`, 없으면 `SafeLoader`).

- LOADER 선택과 순수 파이썬 폴백
- 샘플 DB의 모든 YAML·frontmatter에서 C 로더와 SafeLoader 결과가 같고, 실패하면 같은 줄·열
- 날짜는 `safe_load`가 그대로, `loads`가 ISO 문자열로
- 깨진 frontmatter는 `IssueDbError`(줄 번호 포함), `db_build --preview` 바이트 동일
- 런타임에 `yaml.safe_load(`/`yaml.load(` 직접 호출 금지(yamlio 제외)
"""

from __future__ import annotations

import datetime
import hashlib
import importlib
import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, copy_db, plugin_root, tmp  # noqa: E402

ROOT = plugin_root()
sys.path.insert(0, str(ROOT / "scripts"))

from common import issuedb, yamlio  # noqa: E402

HAS_LIBYAML = bool(getattr(yaml, "__with_libyaml__", False))


def _yaml_texts():
    for p in sorted(SAMPLE.rglob("*")):
        if p.suffix == ".yaml":
            yield p, p.read_text(encoding="utf-8")
        elif p.suffix == ".md":
            m = re.match(r"---\n(.*?)\n---\n", p.read_text(encoding="utf-8"), re.S)
            if m:
                yield p, m.group(1)


def test_loader_selection():
    assert yamlio.LOADER is (yaml.CSafeLoader if HAS_LIBYAML else yaml.SafeLoader)


def test_fallback_to_safe_loader(monkeypatch):
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    try:
        mod = importlib.reload(yamlio)
        assert mod.LOADER is yaml.SafeLoader
        assert mod.loads("d: 2026-09-15") == {"d": "2026-09-15"}
    finally:
        monkeypatch.undo()
        importlib.reload(yamlio)
    assert yamlio.LOADER is (yaml.CSafeLoader if HAS_LIBYAML else yaml.SafeLoader)


def test_same_result_as_safe_loader_on_sample_db():
    texts = list(_yaml_texts())
    assert texts
    for path, text in texts:
        try:
            want = yaml.load(text, Loader=yaml.SafeLoader)
        except yaml.YAMLError as exc:
            with pytest.raises(yaml.YAMLError) as info:
                yamlio.safe_load(text)
            a, b = exc.problem_mark, info.value.problem_mark
            assert (a.line, a.column) == (b.line, b.column), path
        else:
            assert yamlio.safe_load(text) == want, path


def test_safe_load_keeps_date_and_loads_normalizes():
    assert yamlio.safe_load("d: 2026-09-15") == {"d": datetime.date(2026, 9, 15)}
    assert yamlio.loads("d: [2026-09-15]") == {"d": ["2026-09-15"]}


def test_broken_frontmatter_raises_issuedb_error(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\na: [1, 2\nb: 3\n---\n본문\n", encoding="utf-8")
    with pytest.raises(issuedb.IssueDbError) as info:
        issuedb.read_frontmatter(p)
    assert "line" in str(info.value)


@pytest.mark.skipif(not HAS_LIBYAML, reason="libyaml 없음")
def test_db_build_preview_identical_for_both_loaders(monkeypatch, capsys):
    import db_build

    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(ROOT))

    def build(loader):
        monkeypatch.setattr(yamlio, "LOADER", loader)
        out = tmp("tt-yamlio-")
        db_build.main(["--db", str(SAMPLE), "--preview", str(out)])
        capsys.readouterr()
        return {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(out.rglob("*")) if p.is_file()}

    pure = build(yaml.SafeLoader)
    fast = build(yaml.CSafeLoader)
    assert pure and pure == fast


def test_no_direct_yaml_load_in_runtime():
    bad = []
    for p in (ROOT / "scripts").rglob("*.py"):
        if p.name == "yamlio.py" and p.parent.name == "common":
            continue
        if re.search(r"\byaml\.(safe_load|load)\(", p.read_text(encoding="utf-8")):
            bad.append(str(p.relative_to(ROOT)))
    assert not bad, f"yamlio.safe_load를 쓸 것: {bad}"


@pytest.mark.parametrize("loader", [yaml.SafeLoader, getattr(yaml, "CSafeLoader", yaml.SafeLoader)])
def test_load_syntax_error_names_file_and_line(monkeypatch, loader):
    monkeypatch.setattr(yamlio, "LOADER", loader)
    p = tmp("tt-yamlio-") / "broken.yaml"
    p.write_text("a: 1\nb: [x\n", encoding="utf-8", newline="\n")
    with pytest.raises(yamlio.YamlFileError) as info:
        yamlio.load(p)
    assert isinstance(info.value, yaml.YAMLError) and info.value.line == 3
    assert "broken.yaml:3: YAML 문법 오류" in str(info.value)
    db = copy_db()
    jira = db / "call/CALL-001-volte-not-working/jira/MOCK-2101.yaml"
    jira.write_text(jira.read_text(encoding="utf-8") + "x: [unclosed\n", encoding="utf-8", newline="\n")
    with pytest.raises(issuedb.IssueDbError) as info:
        issuedb.load(db)
    assert str(info.value).startswith("call/CALL-001-volte-not-working/jira/MOCK-2101.yaml:")
