#!/usr/bin/env python3
"""tags.yaml 태그 속성 `level: unreliable`·`ipc: vendor` (04-parser-matching §5.8 (2), C1+D 보정 항목 6).

- 키마다 DB가 하나도 선언하지 않으면 백엔드 기본 상수(oFono level {DITD,RFSD,DMD,MOSE}·ipc {exynos-ril},
  Android level 없음·ipc {RIL}), 하나라도 선언하면 DB만 본다.
- 선언이 없거나 상수와 같은 집합을 선언하면 출력이 바이트 같다.
- 잘못된 값은 `parser_rules.load`의 스키마 검사(RulesError)와 `db_lint --all` 오류로 막힌다.
- `rulediff`: `ipc`가 바뀐 tags 항목은 벤더 IPC builtin을 쓰는 시그니처를 대상에 넣는다.

샘플 DB는 속성을 선언하지 않는다(C-F2) — Android 선언 경로는 tmp 사본으로만 본다.
`pytest tests/test_tag_attrs.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, copy_db, run, variant_db  # noqa: E402

from common import parser_rules, rulediff, vendor_ipc  # noqa: E402
from platforms.android import backend as aback  # noqa: E402
from platforms.ofono import backend as oback  # noqa: E402

FILTER = REPO / "tests" / "fixtures" / "module-filter"
OFONO_LOGS = sorted(p for p in FILTER.glob("*/source.log") if not p.parent.name.startswith("a-"))
ANDROID_LOGS = sorted(FILTER.glob("a-*/source.log")) + sorted(
    (REPO / "templates" / "module-skills" / "android").glob("*/evals/*/files/source.log"))[:6]
ATTR_RX = re.compile(r",\s*(?:level: unreliable|ipc: vendor)")


def _dump(records: list[dict]) -> str:
    return json.dumps(records, ensure_ascii=False, sort_keys=True)


def _rules_copy(src: Path, tags_text: str) -> parser_rules.Rules:
    db = copy_db(src, "attrdb")
    (db / "parser-rules" / "tags.yaml").write_text(tags_text, encoding="utf-8", newline="\n")
    return parser_rules.load(db / "parser-rules")


def _tags(src: Path) -> str:
    return (src / "parser-rules" / "tags.yaml").read_text(encoding="utf-8")


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "x.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# 1·2 -------------------------------------------------------------------------------------------------------


def test_no_declaration_is_byte_identical():
    """1: 속성 없는 DB(샘플·변형 issue-db-ofono) → 두 백엔드 출력이 상수 기본과 바이트 같다."""
    assert OFONO_LOGS and ANDROID_LOGS
    sample = parser_rules.load(SAMPLE / "parser-rules")
    ofono = parser_rules.load(variant_db("issue-db-ofono") / "parser-rules")
    assert not any(r.declares(k) for r in (sample, ofono) for k in parser_rules.TAG_ATTRS)
    base = oback.BACKEND.parse(OFONO_LOGS, "UTC", 2026, None)
    assert _dump(oback.BACKEND.apply_rules(ofono).parse(OFONO_LOGS, "UTC", 2026, None)) == _dump(base)
    base = aback.BACKEND.parse(ANDROID_LOGS, "UTC", 2026, None)
    assert _dump(aback.BACKEND.apply_rules(sample).parse(ANDROID_LOGS, "UTC", 2026, None)) == _dump(base)


def test_declared_same_set_is_byte_identical():
    """2: 변형 oFono DB(상수와 같은 속성) → 1과 같다. Android는 샘플 tmp 사본에 `{tag: RIL, ipc: vendor}`를 따로 둔다."""
    modules = parser_rules.load(variant_db("issue-db-ofono-modules") / "parser-rules")
    assert modules.declares("level") and modules.declares("ipc")
    base = oback.BACKEND.parse(OFONO_LOGS, "UTC", 2026, None)
    out = oback.BACKEND.apply_rules(modules).parse(OFONO_LOGS, "UTC", 2026, None)
    assert _dump(out) == _dump(base)
    assert any((r["event"] or "").startswith("builtin.") for r in base)            # 판별이 실제로 돈 입력이다

    text = _tags(SAMPLE)
    old = "'^(RIL|RILC|RILC-AIDL_SERVICE|RIL_EXTERNAL)$', category: common,"
    assert old in text
    text = text.replace(old, "'^(RILC|RILC-AIDL_SERVICE|RIL_EXTERNAL)$', category: common,")
    text += "  - {tag: RIL, category: common, ipc: vendor, added_for: '-', added_on: 2026-11-06, reason: 시험}\n"
    rules = _rules_copy(SAMPLE, text)
    assert rules.declares("ipc") and not rules.declares("level")
    base = aback.BACKEND.parse(ANDROID_LOGS, "UTC", 2026, None)
    assert _dump(aback.BACKEND.apply_rules(rules).parse(ANDROID_LOGS, "UTC", 2026, None)) == _dump(base)


def test_parse_logcat_wires_rules(tmp_path):
    """parse_logcat `parse` 경로(규칙 → `apply_rules`): 상수와 같은 속성을 선언한 DB와 속성을 지운 사본의 출력이 같다."""
    src = variant_db("issue-db-ofono-modules")
    log = next(p for p in OFONO_LOGS if p.parent.name == "e4-sim-io")
    stripped = copy_db(src, "stripped")
    (stripped / "parser-rules" / "tags.yaml").write_text(ATTR_RX.sub("", _tags(src)), encoding="utf-8")

    def parse(db: Path) -> str:
        proc = run("parse_logcat.py", ["parse", log, "--rules", db / "parser-rules", "--full", "--mask",
                                       "--tz", "UTC", "--year", "2026"])
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        data["rules"].pop("path", None)                                      # tmp 경로만 다르다
        return _dump([data])

    assert parse(src) == parse(stripped)


# 3·4 -------------------------------------------------------------------------------------------------------


def test_declared_level_ignores_constants(tmp_path):
    """3: DB가 `level`을 선언하고 MOSE를 빼면 MOSE warn 줄은 W로 남는다(상수 무시)."""
    src = variant_db("issue-db-ofono-modules")
    text = _tags(src).replace("{tag: MOSE,       category: common,  level: unreliable,", "{tag: MOSE, category: common,")
    rules = _rules_copy(src, text)
    assert rules.declares("level") and rules.tag_attr("MOSE", "level") is None
    path = _write(tmp_path, [
        "Sep 20 14:32:11.001 dut local0.warn MOSE[13]: ok",
        "Sep 20 14:32:11.002 dut daemon.crit DITD[10]: netlink dump",
    ])
    levels = [r["level"] for r in oback.BACKEND.apply_rules(rules).parse([path], "UTC", 2026, None)]
    assert levels == ["W", "I"]
    assert [r["level"] for r in oback.BACKEND.parse([path], "UTC", 2026, None)] == ["I", "I"]


def test_old_and_new_daemon_names(tmp_path):
    """4: 옛·새 이름(`exynos-ril`·`vendor-ril`) 둘 다 `ipc: vendor` → 두 ident 줄 모두에서 builtin."""
    src = variant_db("issue-db-ofono-modules")
    text = _tags(src) + ("  - {tag: vendor-ril, category: common, ipc: vendor, added_for: '-', added_on: 2026-11-06,"
                         " reason: 시험}\n")
    rules = _rules_copy(src, text)
    line = "[RilContext_0] OnRequestComplete Request ID=10, result=2"
    path = _write(tmp_path, [f"Sep 20 14:32:11.001 dut daemon.debug exynos-ril[7]: {line}",
                             f"Sep 20 14:32:11.002 dut daemon.debug vendor-ril[8]: {line}"])
    out = oback.BACKEND.apply_rules(rules).parse([path], "UTC", 2026, None)
    assert [r["tag"] for r in out if r["event"] == vendor_ipc.REQUEST_FAILED] == ["exynos-ril", "vendor-ril"]
    out = oback.BACKEND.parse([path], "UTC", 2026, None)                     # 기본 상수: exynos-ril만
    assert [r["tag"] for r in out if r["event"] == vendor_ipc.REQUEST_FAILED] == ["exynos-ril"]


# 5·6 -------------------------------------------------------------------------------------------------------


def test_exact_entry_wins_over_regex():
    """5: 정확한 이름 항목이 있으면 그 항목만 본다(값이 없어도 regex를 보지 않는다). 없으면 처음 맞는 regex."""
    text = _tags(SAMPLE) + (
        "  - {tag_regex: '^Vnd', category: common, ipc: vendor, added_for: '-', added_on: 2026-11-06, reason: 시험}\n"
        "  - {tag: VndExact, category: common, added_for: '-', added_on: 2026-11-06, reason: 시험}\n")
    rules = _rules_copy(SAMPLE, text)
    assert rules.tag_attr("VndOther", "ipc") == "vendor"
    assert rules.tag_attr("VndExact", "ipc") is None
    assert rules.tag_attr("Nothing", "ipc") is None


def test_invalid_value_is_rules_error_and_lint_error():
    """6: `level: maybe` → parser_rules.load RulesError, db_lint --all 종료 코드 1."""
    db = copy_db(SAMPLE, "badattr")
    path = db / "parser-rules" / "tags.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "{tag: UiccController, category: sim,", "{tag: UiccController, category: sim, level: maybe,"), encoding="utf-8")
    with pytest.raises(parser_rules.RulesError, match="스키마 오류"):
        parser_rules.load(db / "parser-rules")
    proc = run("db_lint.py", ["--db", db, "--all"])
    assert proc.returncode == 1, proc.stderr[-800:]
    errors = json.loads(proc.stdout)["errors"]
    assert any("level" in e.get("message", "") or "maybe" in e.get("message", "") for e in errors), errors


# 7·8 -------------------------------------------------------------------------------------------------------


def test_site_mock_backend_runs_with_rules():
    """7: site 모의 백엔드(`ReferenceBackend` 상속 → `apply_rules`가 있다)는 규칙을 받아도 그대로 돈다."""
    import importlib.util

    name = "parser_backends.site"
    module = sys.modules.get(name)
    if module is None:
        site_dir = REPO / "tests" / "mocks" / "parser_backends" / "site"
        spec = importlib.util.spec_from_file_location(name, site_dir / "__init__.py",
                                                      submodule_search_locations=[str(site_dir)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    site = module.BACKEND
    rules = parser_rules.load(SAMPLE / "parser-rules")
    logs = sorted((REPO / "tests" / "fixtures" / "logs").glob("data-*.log"))[:3]
    assert logs
    assert _dump(site.apply_rules(rules).parse(logs, "UTC", 2026, None)) == _dump(site.parse(logs, "UTC", 2026, None))


def _state(tags: list[dict]) -> rulediff.State:
    st = rulediff.State()
    for t in tags:
        st.rules[("tags", t.get("tag") or t["tag_regex"])] = t
    raw = {"id": "s1", "must_event": [{"event": vendor_ipc.IPC_ERROR}]}
    st.sigs[("X-001-a", "cause", "s1")] = rulediff.SigRef("X-001-a", "cause", "s1", raw, "X-001", "common")
    raw = {"id": "s2", "must_event": [{"event": "data_connect_failed"}]}
    st.sigs[("X-001-a", "cause", "s2")] = rulediff.SigRef("X-001-a", "cause", "s2", raw, "X-001", "common")
    return st


def test_rulediff_ipc_change_targets_vendor_signatures():
    """8: tags 항목에 `ipc`가 생기면 벤더 IPC builtin을 쓰는 시그니처가 대상. `level`만 바뀌면 대상 없음."""
    entry = {"tag": "exynos-ril", "category": "common", "added_for": "-", "added_on": "2026-11-06", "reason": "r"}
    base = _state([entry])
    diff = rulediff.compute(base, _state([{**entry, "ipc": "vendor"}]))
    assert diff.rules == [{"section": "tags", "key": "exynos-ril", "change": "changed"}]
    assert sorted(k[2] for k in diff.sigs) == ["s1"]
    assert diff.sigs[("X-001-a", "cause", "s1")].why == ["depends:tags:exynos-ril"]
    diff = rulediff.compute(base, _state([{**entry, "level": "unreliable"}]))
    assert diff.rules and not diff.sigs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
