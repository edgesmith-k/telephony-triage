#!/usr/bin/env python3
"""tags.yaml 태그 속성 `level: unreliable`·`ipc: vendor` (04-parser-matching §5.8 (2), C1+D 보정 항목 6).

- 키마다 DB가 하나도 선언하지 않으면 백엔드 기본(oFono: site-defaults 구성요소 `level_unreliable`·`vendor_ipc`의 ident,
  설정이 없으면 없음 / Android: level 없음·ipc {RIL}), 하나라도 선언하면 DB만 본다.
- 선언이 없거나 기본과 같은 집합을 선언하면 출력이 바이트 같다.
- 잘못된 값은 `parser_rules.load`의 스키마 검사(RulesError)와 `db_lint --all` 오류로 막힌다.
- `rulediff`: `ipc`가 바뀐 tags 항목은 벤더 IPC builtin을 쓰는 시그니처를 대상에 넣는다.

샘플 DB는 속성을 선언하지 않는다(C-F2) — Android 선언 경로는 tmp 사본으로만 본다.
`pytest tests/test_tag_attrs.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, copy_db, plugin_root, run, variant_db  # noqa: E402

import platforms  # noqa: E402
from common import parser_rules, rulediff, vendor_ipc  # noqa: E402
from platforms.android import backend as aback  # noqa: E402
from platforms.ofono import backend as oback  # noqa: E402

FILTER = REPO / "tests" / "fixtures" / "module-filter"
OFONO_LOGS = sorted(p for p in FILTER.glob("*/source.log") if not p.parent.name.startswith("a-"))
ANDROID_LOGS = sorted(FILTER.glob("a-*/source.log")) + sorted(
    (REPO / "templates" / "module-skills" / "android").glob("*/evals/*/files/source.log"))[:6]
ATTR_RX = re.compile(r",\s*(?:level: unreliable|ipc: vendor)")
ON = {"name": "android", "enabled": ["android", "ofono"]}


def _dump(records: list[dict]) -> str:
    return json.dumps(records, ensure_ascii=False, sort_keys=True)


def _declared(rules: parser_rules.Rules, key: str, value: str) -> list[str]:
    """DB가 `key: value`로 선언한 정확한 태그 이름(이름을 시험에 적지 않고 DB에서 읽는다)."""
    return sorted(t for t in rules.tag_exact if rules.tag_attr(t, key) == value)


def _platform(level=(), ipc=()) -> dict:
    """site-defaults `platform` 블록: SPEC 기본 구성요소(`ofonod`) + `level_unreliable`·`vendor_ipc` 구성요소."""
    comps = {"ofono": {"idents": ["ofonod"], "root_key": "ofono", "msg_format": "file_func"}}
    if level:
        comps["unreliable"] = {"idents": list(level), "level_unreliable": True}
    if ipc:
        comps["vendor"] = {"idents": list(ipc), "vendor_ipc": True}
    return {**ON, "others": {"ofono": {"components": comps}}}


def _ofono(level=(), ipc=()) -> oback.OfonoReferenceBackend:
    return oback.BACKEND.configure(platforms.load({"platform": _platform(level, ipc)}, "ofono"))


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
    """1: 속성 없는 DB(샘플·변형 issue-db-ofono) → 두 백엔드 출력이 백엔드 기본과 바이트 같다."""
    assert OFONO_LOGS and ANDROID_LOGS
    sample = parser_rules.load(SAMPLE / "parser-rules")
    ofono = parser_rules.load(variant_db("issue-db-ofono") / "parser-rules")
    assert not any(r.declares(k) for r in (sample, ofono) for k in parser_rules.TAG_ATTRS)
    base = oback.BACKEND.parse(OFONO_LOGS, "UTC", 2026, None)
    assert _dump(oback.BACKEND.apply_rules(ofono).parse(OFONO_LOGS, "UTC", 2026, None)) == _dump(base)
    base = aback.BACKEND.parse(ANDROID_LOGS, "UTC", 2026, None)
    assert _dump(aback.BACKEND.apply_rules(sample).parse(ANDROID_LOGS, "UTC", 2026, None)) == _dump(base)


def test_declared_same_set_is_byte_identical():
    """2: 변형 oFono DB가 선언한 속성 = 같은 이름의 구성요소 설정 → DB 경로와 설정 경로의 출력이 바이트 같다(설정이
    있어도 DB가 선언한 키는 DB만). Android는 샘플 tmp 사본에 `{tag: RIL, ipc: vendor}`를 따로 둔다."""
    modules = parser_rules.load(variant_db("issue-db-ofono-modules") / "parser-rules")
    assert modules.declares("level") and modules.declares("ipc")
    level, ipc = _declared(modules, "level", "unreliable"), _declared(modules, "ipc", "vendor")
    assert level and ipc
    configured = _ofono(level, ipc)
    base = configured.parse(OFONO_LOGS, "UTC", 2026, None)
    for backend in (oback.BACKEND, configured, _ofono(ipc=level)):                # DB가 선언하면 설정은 보지 않는다
        assert _dump(backend.apply_rules(modules).parse(OFONO_LOGS, "UTC", 2026, None)) == _dump(base)
    assert any((r["event"] or "").startswith("builtin.") for r in base)            # 판별이 실제로 돈 입력이다
    assert _dump(oback.BACKEND.parse(OFONO_LOGS, "UTC", 2026, None)) != _dump(base)   # 설정도 선언도 없으면 보정·판별 없음

    text = _tags(SAMPLE)
    old = "'^(RIL|VRIL|VRIL-SVC)$', category: common,"
    assert old in text
    text = text.replace(old, "'^(VRIL|VRIL-SVC)$', category: common,")
    text += "  - {tag: RIL, category: common, ipc: vendor, added_for: '-', added_on: 2026-11-06, reason: 시험}\n"
    rules = _rules_copy(SAMPLE, text)
    assert rules.declares("ipc") and not rules.declares("level")
    base = aback.BACKEND.parse(ANDROID_LOGS, "UTC", 2026, None)
    assert _dump(aback.BACKEND.apply_rules(rules).parse(ANDROID_LOGS, "UTC", 2026, None)) == _dump(base)


def test_parse_logcat_wires_rules(tmp_path):
    """parse_logcat `parse` 경로(site-defaults → `configure`, 규칙 → `apply_rules`): 속성을 선언한 DB와, 속성을 지운
    사본 + 같은 이름의 구성요소 설정(`level_unreliable`·`vendor_ipc`)의 출력이 같다."""
    src = variant_db("issue-db-ofono-modules")
    log = next(p for p in OFONO_LOGS if p.parent.name == "ofono-sim-io-failure")
    stripped = copy_db(src, "stripped")
    (stripped / "parser-rules" / "tags.yaml").write_text(ATTR_RX.sub("", _tags(src)), encoding="utf-8")
    rules = parser_rules.load(src / "parser-rules")
    root = plugin_root("tag-attrs", platform=_platform(_declared(rules, "level", "unreliable"),
                                                       _declared(rules, "ipc", "vendor")))

    def parse(db: Path) -> str:
        proc = run("parse_logcat.py", ["parse", log, "--rules", db / "parser-rules", "--full", "--mask",
                                       "--tz", "UTC", "--year", "2026"], root=root)
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        data["rules"].pop("path", None)                                      # tmp 경로만 다르다
        return _dump([data])

    assert parse(src) == parse(stripped)


# 3·4 -------------------------------------------------------------------------------------------------------


def _with_attr(src: Path, attrs: dict[str, str]) -> parser_rules.Rules:
    """변형 issue-db-ofono 사본: `{태그: "level: unreliable" 같은 속성}`을 그 태그 항목에 더한다."""
    text = _tags(src)
    for tag, attr in attrs.items():
        old = f"{{tag: {tag}, "
        assert old in text, tag
        text = text.replace(old, f"{{tag: {tag}, {attr}, ")
    return _rules_copy(src, text)


def test_declared_level_ignores_component_setting(tmp_path):
    """3: DB가 `level`을 선언하면 구성요소 설정은 보지 않는다 — 설정만 있는 daemon-a warn 줄은 W, DB가 선언한 daemon-b는 I."""
    rules = _with_attr(variant_db("issue-db-ofono"), {"daemon-b": "level: unreliable"})
    assert rules.declares("level") and rules.tag_attr("daemon-a", "level") is None
    path = _write(tmp_path, [
        "Sep 20 14:32:11.001 dut local0.warn daemon-a[13]: ok",
        "Sep 20 14:32:11.002 dut daemon.crit daemon-b[10]: netlink dump",
    ])
    configured = _ofono(level=["daemon-a", "daemon-b"])

    def levels(backend):
        return [r["level"] for r in backend.parse([path], "UTC", 2026, None)]

    assert levels(configured.apply_rules(rules)) == levels(oback.BACKEND.apply_rules(rules)) == ["W", "I"]
    assert levels(configured) == ["I", "I"]                                   # 선언 없음: 구성요소 설정
    assert levels(oback.BACKEND) == ["W", "F"]                                # 설정도 선언도 없음: 보정 없음


def test_old_and_new_daemon_names(tmp_path):
    """4: 옛·새 이름(`daemon-a`·`daemon-b`) 둘 다 `ipc: vendor` → 두 ident 줄 모두에서 builtin.
    선언이 없으면 구성요소 `vendor_ipc` 설정의 ident만, 설정도 없으면 판별 없음."""
    src = variant_db("issue-db-ofono")
    rules = _with_attr(src, {"daemon-a": "ipc: vendor", "daemon-b": "ipc: vendor"})
    line = "[IpcCtx_0] OnIpcComplete Request ID=10, result=2"
    path = _write(tmp_path, [f"Sep 20 14:32:11.001 dut daemon.debug daemon-a[7]: {line}",
                             f"Sep 20 14:32:11.002 dut daemon.debug daemon-b[8]: {line}"])

    def failed(backend):
        return [r["tag"] for r in backend.parse([path], "UTC", 2026, None) if r["event"] == vendor_ipc.REQUEST_FAILED]

    assert failed(oback.BACKEND.apply_rules(rules)) == ["daemon-a", "daemon-b"]
    assert failed(_ofono(ipc=["daemon-a"])) == ["daemon-a"]
    assert failed(_ofono(ipc=["daemon-a"]).apply_rules(parser_rules.load(src / "parser-rules"))) == ["daemon-a"]
    assert failed(oback.BACKEND) == []


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
    entry = {"tag": "daemon-b", "category": "common", "added_for": "-", "added_on": "2026-11-06", "reason": "r"}
    base = _state([entry])
    diff = rulediff.compute(base, _state([{**entry, "ipc": "vendor"}]))
    assert diff.rules == [{"section": "tags", "key": "daemon-b", "change": "changed"}]
    assert sorted(k[2] for k in diff.sigs) == ["s1"]
    assert diff.sigs[("X-001-a", "cause", "s1")].why == ["depends:tags:daemon-b"]
    diff = rulediff.compute(base, _state([{**entry, "level": "unreliable"}]))
    assert diff.rules and not diff.sigs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
