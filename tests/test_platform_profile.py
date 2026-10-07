"""RF-4(I3): site-defaults `platform:` → `platforms.load()` / `PlatformProfile`.

- 기본값 동일성(모듈 상수 객체 그대로), example YAML의 주석 값 = 기본값
- 검증 오류(키 경로 포함)와 CLI 종료 코드 2 (parse·extract-bugreport·code_roots validate)
- 덮어쓰기 효과: 슬롯 표기·RIL 태그·bugreport 섹션·소스 트리
- 격리: configure()는 새 객체, 싱글톤 불변, 전역 상태 없음
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "tests" / "mocks"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_plugin_root  # noqa: E402
import mock_env  # noqa: E402
import parser_backends  # noqa: E402
import platforms  # noqa: E402
from platforms import PlatformConfigError  # noqa: E402
from platforms.android import REQUIRED_DIRS, VERSION_SOURCES, backend, bugreport, logcat, ril  # noqa: E402

EXAMPLE = REPO / "plugin" / "site-defaults.example.yaml"
RULES = REPO / "tests" / "fixtures" / "issue-db-sample" / "parser-rules"
SRC16, SRC17 = REPO / "tests" / "mocks" / "src" / "android16", REPO / "tests" / "mocks" / "src" / "android17"


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="tt-platform-"))


def _root(platform=None, backend_kind: str = "reference") -> Path:
    """임시 플러그인 루트 (캐시하지 않는다 — platform 블록을 바꾸므로)."""
    root = make_plugin_root.make(with_site_backend=True)
    path = root / "site-defaults.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if platform is not None:
        data["platform"] = platform
    data["parser"] = {"backend": backend_kind}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return root


def _script(root: Path, name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(root / "scripts" / name), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=mock_env.env_with_mocks(plugin_root=root),
    )


def _example_platform_uncommented() -> dict:
    """example의 `platform:` 블록에서 주석 값을 풀어 읽는다."""
    lines, inside = [], False
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("platform:"):
            inside = True
        elif inside and line and not line.startswith(" "):
            if not line.startswith("#"):
                break
            continue  # 블록 밖 설명 주석
        if inside:
            m = re.match(r"^(\s*)# (.*)$", line)
            lines.append(f"{m.group(1)}{m.group(2)}" if m else line)
    return yaml.safe_load("\n".join(lines))["platform"]


# -- 1. 기본값 ---------------------------------------------------------------------


@pytest.mark.parametrize("defaults", [None, {}, {"platform": None}, {"platform": {"name": "android"}}])
def test_load_defaults_equal_default(defaults):
    assert platforms.load(defaults) == platforms.default()


def test_default_uses_module_objects():
    prof = platforms.default()
    assert prof.source_tree.version_sources == tuple(VERSION_SOURCES)
    assert all(a[1] is b[1] for a, b in zip(prof.source_tree.version_sources, VERSION_SOURCES))
    assert prof.source_tree.required_dirs == REQUIRED_DIRS
    assert prof.phone is logcat.DEFAULT_PHONE_RULES
    assert prof.phone.tag[0] is logcat.TAG_PHONE_RE
    assert prof.phone.prefix[0] is logcat.MSG_PHONE_PREFIX_RE
    assert prof.phone.suffix[0] is logcat.MSG_PHONE_SUFFIX_RE
    assert prof.ril_tags == frozenset(ril.RIL_TAGS)
    assert prof.bugreport is bugreport.DEFAULT_RULES
    assert prof.bugreport.section_re is bugreport.SECTION_RE
    assert prof.bugreport.wanted_buffers is bugreport.WANTED_BUFFERS


def test_example_commented_values_equal_defaults():
    block = _example_platform_uncommented()
    assert set(block) == {"name", "source_tree", "log", "ril", "bugreport"}
    prof = platforms.load({"platform": block})
    default = platforms.default()
    assert prof.source_tree.required_dirs == default.source_tree.required_dirs
    # 플래그는 비교하지 않는다: 설정값은 항상 re.M이고, 기본 첫 항목은 앵커(^·$)가 없어 re.M 유무가 결과를 바꾸지 않는다.
    assert [(f, p.pattern) for f, p in prof.source_tree.version_sources] == [
        (f, p.pattern) for f, p in default.source_tree.version_sources]
    assert [p.pattern for p in prof.phone.tag] == [p.pattern for p in default.phone.tag]
    assert [p.pattern for p in prof.phone.prefix] == [p.pattern for p in default.phone.prefix]
    assert [p.pattern for p in prof.phone.suffix] == [p.pattern for p in default.phone.suffix]
    assert prof.ril_tags == default.ril_tags
    assert prof.bugreport.section_re.pattern == default.bugreport.section_re.pattern
    assert prof.bugreport.boundary_re.pattern == default.bugreport.boundary_re.pattern
    assert prof.bugreport.wanted_buffers == default.bugreport.wanted_buffers


def test_example_yaml_block_is_loaded_by_test_root():
    root = _root()
    data = yaml.safe_load((root / "site-defaults.yaml").read_text(encoding="utf-8"))
    assert data["platform"] == {"name": "android"}


# -- 2. 검증 오류 --------------------------------------------------------------------

BAD = [
    ({"platform": []}, "platform"),
    ({"platform": {"name": "generic"}}, "platform.name"),
    ({"platform": {"nmae": "android"}}, "platform.nmae"),
    ({"platform": {"log": {"phone_ids": {}}}}, "platform.log.phone_ids"),
    ({"platform": {"source_tree": {"required_dirs": []}}}, "platform.source_tree.required_dirs"),
    ({"platform": {"source_tree": {"required_dirs": ["/abs"]}}}, "platform.source_tree.required_dirs[0]"),
    ({"platform": {"source_tree": {"required_dirs": ["a", "../x"]}}}, "platform.source_tree.required_dirs[1]"),
    ({"platform": {"source_tree": {"version_sources": []}}}, "platform.source_tree.version_sources"),
    ({"platform": {"source_tree": {"version_sources": [{"file": "a"}]}}}, "platform.source_tree.version_sources[0]"),
    ({"platform": {"source_tree": {"version_sources": [{"file": "/a", "regex": "(x)"}]}}},
     "platform.source_tree.version_sources[0].file"),
    ({"platform": {"source_tree": {"version_sources": [{"file": "a", "regex": "x"}]}}},
     "platform.source_tree.version_sources[0].regex"),
    ({"platform": {"source_tree": {"version_sources": [{"file": "a", "regex": "(x"}]}}},
     "platform.source_tree.version_sources[0].regex"),
    ({"platform": {"log": {"phone_id": {"tag": ["["]}}}}, "platform.log.phone_id.tag[0]"),
    ({"platform": {"log": {"phone_id": {"msg_prefix": ["^x"]}}}}, "platform.log.phone_id.msg_prefix[0]"),
    ({"platform": {"log": {"phone_id": {"msg_suffix": "x(\\d)"}}}}, "platform.log.phone_id.msg_suffix"),
    ({"platform": {"ril": {"tags": [""]}}}, "platform.ril.tags[0]"),
    ({"platform": {"ril": {"tags": "RILJ"}}}, "platform.ril.tags"),
    ({"platform": {"bugreport": {"wanted_buffers": []}}}, "platform.bugreport.wanted_buffers"),
    ({"platform": {"bugreport": {"wanted_buffers": ["Radio"]}}}, "platform.bugreport.wanted_buffers[0]"),
    ({"platform": {"bugreport": {"wanted_buffers": ["../x"]}}}, "platform.bugreport.wanted_buffers[0]"),
    ({"platform": {"bugreport": {"wanted_buffers": ["radio", "radio"]}}}, "platform.bugreport.wanted_buffers"),
    ({"platform": {"bugreport": {"section_regex": "^(x)$"}}}, "platform.bugreport.section_regex"),
    ({"platform": {"bugreport": {"boundary_regex": "("}}}, "platform.bugreport.boundary_regex"),
]


@pytest.mark.parametrize("defaults,path", BAD)
def test_invalid_platform_block(defaults, path):
    with pytest.raises(PlatformConfigError) as info:
        platforms.load(defaults)
    assert f"site-defaults.yaml {path}" in str(info.value)


def test_generic_name_message():
    with pytest.raises(PlatformConfigError, match="지원 플랫폼: android"):
        platforms.load({"platform": {"name": "generic"}})
    with pytest.raises(PlatformConfigError, match="지원 플랫폼: android"):
        platforms.default("generic")


def test_empty_lists_allowed_for_phone_and_ril():
    prof = platforms.load({"platform": {"log": {"phone_id": {"tag": [], "msg_prefix": [], "msg_suffix": []}},
                                        "ril": {"tags": []}}})
    assert prof.phone.tag == prof.phone.prefix == prof.phone.suffix == ()
    assert prof.ril_tags == frozenset()


def test_omitted_key_keeps_default():
    prof = platforms.load({"platform": {"log": {"phone_id": {"msg_prefix": []}}}})
    assert prof.phone.tag == logcat.DEFAULT_PHONE_RULES.tag
    assert prof.phone.suffix == logcat.DEFAULT_PHONE_RULES.suffix
    assert prof.phone.prefix == ()


def test_load_does_not_mutate_input():
    defaults = {"platform": {"ril": {"tags": ["RILJ", "VRIL"]}}}
    before = json.dumps(defaults)
    platforms.load(defaults)
    assert json.dumps(defaults) == before


# -- 3. CLI 종료 코드 2 -----------------------------------------------------------------

BAD_BLOCK = {"name": "generic"}


def test_cli_parse_bad_platform_exits_2():
    root = _root(BAD_BLOCK)
    log = _tmp() / "a.log"
    log.write_text("10-05 12:00:00.000  1  1 D Foo: x\n", encoding="utf-8")
    proc = _script(root, "parse_logcat.py", "parse", str(log), "--rules", str(RULES), "--full")
    assert proc.returncode == 2
    assert "platform.name" in proc.stderr and "지원 플랫폼: android" in proc.stderr


def test_cli_extract_bugreport_bad_platform_exits_2():
    root = _root({"bugreport": {"wanted_buffers": ["Radio"]}})
    src = _tmp() / "b.txt"
    src.write_text("== dumpstate: x\n", encoding="utf-8")
    proc = _script(root, "parse_logcat.py", "extract-bugreport", str(src), "--out", str(_tmp() / "o"))
    assert proc.returncode == 2
    assert "platform.bugreport.wanted_buffers[0]" in proc.stderr


def test_cli_code_roots_validate_bad_platform_exits_2():
    root = _root({"source_tree": {"required_dirs": ["../x"]}})
    proc = _script(root, "code_roots.py", "validate", str(SRC16), "--version", "16")
    assert proc.returncode == 2
    assert "platform.source_tree.required_dirs[0]" in proc.stderr


# -- 4. 슬롯 표기 · RIL 태그 --------------------------------------------------------------

SLOT_LOG = """\
10-05 12:00:00.000  100  100 D RILJ    : {SLOT1}[7]> SETUP_DATA_CALL
10-05 12:00:00.500  100  100 D RILJ    : {SLOT1}[7]< SETUP_DATA_CALL error=NONE
10-05 12:00:01.000  100  100 D RILJ    : [PHONE1][8]> DIAL
10-05 12:00:01.200  100  100 D RILJ    : [PHONE1][8]< DIAL error=NONE
10-05 12:00:02.000  100  100 D VRIL    : [9]> GET_SIM_STATUS
10-05 12:00:02.100  100  100 D VRIL    : [9]< GET_SIM_STATUS error=NONE
"""


def _parse_events(profile_block, text: str = SLOT_LOG, backend_name: str = "reference") -> list[dict]:
    path = _tmp() / "x.log"
    path.write_text(text, encoding="utf-8")
    prof = platforms.load({"platform": profile_block} if profile_block is not None else None)
    return parser_backends.load(backend_name).configure(prof).parse([path], "UTC", 2026, None)


def _view(events: list[dict]):
    return [(e["msg"].split(" ")[0], e["phone_id"], (e["ril"] or {}).get("dir")) for e in events]


def test_default_profile_output_equals_unconfigured_backend():
    path = _tmp() / "x.log"
    path.write_text(SLOT_LOG, encoding="utf-8")
    plain = parser_backends.load("reference").parse([path], "UTC", 2026, None)
    configured = parser_backends.load("reference").configure(platforms.default()).parse([path], "UTC", 2026, None)
    assert plain == configured
    # 기본 표기: [PHONE1]은 슬롯 1 + RIL 해석, {SLOT1}은 슬롯도 RIL도 없다, VRIL은 RIL 태그가 아니다
    assert [(e["phone_id"], (e["ril"] or {}).get("dir")) for e in plain] == [
        (None, None), (None, None), (1, "req"), (1, "resp"), (None, None), (None, None)]


def test_msg_prefix_override_changes_phone_id_and_ril_pairing():
    events = _parse_events({"log": {"phone_id": {"msg_prefix": [r"^\{SLOT(\d+)\}"]}}})
    assert [(e["phone_id"], (e["ril"] or {}).get("dir")) for e in events] == [
        (1, "req"), (1, "resp"), (None, None), (None, None), (None, None), (None, None)]
    assert events[0]["ril"]["latency_ms"] == 500 and events[1]["ril"]["latency_ms"] == 500


def test_msg_prefix_empty_list_drops_phone1_lines():
    events = _parse_events({"log": {"phone_id": {"msg_prefix": []}}})
    assert all(e["phone_id"] is None for e in events)
    assert all(e["ril"] is None for e in events)  # 접두어를 못 떼므로 RIL 해석도 안 된다


def test_ril_tags_override():
    events = _parse_events({"ril": {"tags": ["RILJ", "VRIL"]}})
    assert [(e["ril"] or {}).get("request") for e in events] == [
        None, None, "DIAL", "DIAL", "GET_SIM_STATUS", "GET_SIM_STATUS"]
    events = _parse_events({"ril": {"tags": []}})
    assert all(e["ril"] is None for e in events)


def test_phone_id_first_match_and_suffix_rules():
    rules = platforms.load({"platform": {"log": {"phone_id": {
        "tag": [r"^X(\d)$", r"^[A-Za-z]+-(\d+)$"], "msg_suffix": [r"\s?<s(\d+)>$"]}}}}).phone
    assert rules.phone_id("X2", "m") == 2
    assert rules.phone_id("DNC-1", "m") == 1
    assert rules.phone_id("T", "hello <s3>") == 3
    assert rules.strip("hello <s3>") == "hello"
    assert rules.phone_id("T", "[PHONE1] a") == 1  # 기본 접두어 유지
    # 모듈 함수는 기본 규칙 그대로
    default = logcat.DEFAULT_PHONE_RULES
    assert default.phone_id("DNC-1", "m") == 1 and default.strip("[SUB2] x [PHONE1]") == "x"


# -- 5. 격리 ------------------------------------------------------------------------------


def test_configure_returns_new_object_and_leaves_singleton():
    ref = parser_backends.load("reference")
    prof = platforms.load({"platform": {"ril": {"tags": ["VRIL"]}}})
    other = ref.configure(prof)
    assert other is not ref and other.name == "reference" and other.version() == ref.version()
    assert parser_backends.load("reference") is ref is backend.BACKEND
    assert ref._ril_tags is ril.RIL_TAGS and ref._phone is logcat.DEFAULT_PHONE_RULES
    assert other._ril_tags == frozenset({"VRIL"})
    # 두 프로파일을 번갈아 써도 섞이지 않는다
    a = _parse_events({"ril": {"tags": ["VRIL"]}})
    b = _parse_events(None)
    c = _parse_events({"ril": {"tags": ["VRIL"]}})
    assert a == c and a != b


def test_base_configure_is_noop():
    from parser_backends.base import ParserBackend

    class Dummy(backend.ReferenceBackend):
        configure = ParserBackend.configure

    d = Dummy()
    assert d.configure(platforms.default()) is d


def test_mock_site_backend_follows_override():
    root = _root(backend_kind="site")
    sys.path.insert(0, str(root / "scripts"))
    try:
        for mod in [m for m in sys.modules if m == "parser_backends.site" or m.startswith("parser_backends.site.")]:
            sys.modules.pop(mod)
        site = parser_backends.load("site")
        assert isinstance(site, backend.ReferenceBackend)
        cfg = site.configure(platforms.load({"platform": {"ril": {"tags": []}}}))
        assert type(cfg) is type(site) and cfg is not site
        path = _tmp() / "x.log"
        path.write_text(SLOT_LOG, encoding="utf-8")
        assert any(e["ril"] for e in site.parse([path], "UTC", 2026, None))
        assert not any(e["ril"] for e in cfg.parse([path], "UTC", 2026, None))
    finally:
        sys.path.remove(str(root / "scripts"))
        for mod in [m for m in sys.modules if m == "parser_backends.site" or m.startswith("parser_backends.site.")]:
            sys.modules.pop(mod)


def test_parse_cli_applies_platform_block():
    root = _root({"log": {"phone_id": {"msg_prefix": [r"^\{SLOT(\d+)\}"]}}})
    log = _tmp() / "x.log"
    log.write_text(SLOT_LOG, encoding="utf-8")
    proc = _script(root, "parse_logcat.py", "parse", str(log), "--rules", str(RULES), "--full",
                   "--tz", "UTC", "--year", "2026")
    assert proc.returncode == 0, proc.stderr
    reqs = {e["ril"]["request"] for e in json.loads(proc.stdout)["events"] if e.get("ril")}
    assert reqs == {"SETUP_DATA_CALL"}  # 기본 표기였다면 {"DIAL"}


# -- 6. bugreport ----------------------------------------------------------------------------

BUGREPORT = """\
== dumpstate: 2026-10-05
Build: B1
Build fingerprint: 'fp/1'

------ SYSTEM LOG (logcat -b system -v threadtime -d *:v) ------
10-05 12:00:00.000  1  1 I Sys: s
------ RADIO LOG (logcat -b radio -v threadtime -d *:v) ------
10-05 12:00:00.000  1  1 I Rad: r
------ MAIN LOG (logcat -b main -v threadtime -d *:v) ------
10-05 12:00:00.000  1  1 I Main: m
------ DUMPSYS (dumpsys) ------
nothing
"""

CUSTOM_BUGREPORT = """\
== dumpstate: x
Build: B2
Build fingerprint: 'fp/2'

=== LOGCAT radio [cmd: logcat -b radio -d] ===
10-05 12:00:00.000  1  1 I Rad: r
=== LOGCAT main [cmd: logcat -b main -d] ===
10-05 12:00:00.000  1  1 I Main: m
=== OTHER ===
x
"""


def _extract(profile_block, text: str, name: str = "bugreport-a.txt") -> dict:
    src = _tmp() / name
    src.write_text(text, encoding="utf-8")
    prof = platforms.load({"platform": profile_block} if profile_block is not None else None)
    out = _tmp() / "out"
    result = bugreport.extract(src, out, prof.bugreport)
    result["_out"] = out
    return result


# AOSP dumpstate 형식 추정(TODO S21): SYSTEM LOG 헤더에 -b가 없다
AOSP_BUGREPORT = """\
== dumpstate: 2026-09-22 12:10:00
Build fingerprint: 'fp/3'

------ SYSTEM LOG (logcat -v threadtime -v printable -d *:v) ------
09-22 12:00:00.000  1  1 I Sys: s
------ EVENT LOG (logcat -b events -v threadtime -d *:v) ------
09-22 12:00:00.000  1  1 I Ev: e
------ RADIO LOG (logcat -b radio -v threadtime -d *:v) ------
09-22 12:00:00.000  1  1 I Rad: r
------ LAST LOGCAT (logcat -L -b all -v threadtime -d *:v) ------
09-22 12:00:00.000  1  1 I Last: l
"""


def test_aosp_system_log_without_b_goes_to_default_buffer():
    result = _extract(None, AOSP_BUGREPORT)
    assert [(f["buffer"], f["lines"]) for f in result["files"]] == [("radio", 1), ("main", 1)]
    skipped = [w for w in result["warnings"] if w["code"] == "skipped-logcat-sections"]
    assert len(skipped) == 1 and "EVENT LOG" in skipped[0]["message"]
    assert "LAST LOGCAT" in skipped[0]["message"]
    no_b = AOSP_BUGREPORT.replace("-L -b all", "-L")          # -b 없는 -L도 main에 합치지 않는다
    assert [(f["buffer"], f["lines"]) for f in _extract(None, no_b)["files"]] == [("radio", 1), ("main", 1)]
    build = json.loads((result["_out"] / "build.json").read_text(encoding="utf-8"))
    assert build["dumpstate_at"] == "2026-09-22 12:10:00"


def test_wanted_buffers_radio_only():
    result = _extract({"bugreport": {"wanted_buffers": ["radio"]}}, BUGREPORT)
    assert [f["buffer"] for f in result["files"]] == ["radio"]
    assert sorted(p.name for p in result["_out"].iterdir()) == ["build.json", "logcat-radio.txt"]


def test_wanted_buffers_order_follows_config():
    result = _extract({"bugreport": {"wanted_buffers": ["main", "radio"]}}, BUGREPORT)
    assert [f["buffer"] for f in result["files"]] == ["main", "radio"]


def test_default_rules_same_as_none():
    default = _extract(None, BUGREPORT)
    assert [f["buffer"] for f in default["files"]] == ["system", "radio", "main"]
    src = _tmp() / "bugreport-a.txt"
    src.write_text(BUGREPORT, encoding="utf-8")
    again = bugreport.extract(src, _tmp() / "o")
    assert [(f["buffer"], f["lines"]) for f in again["files"]] == [(f["buffer"], f["lines"]) for f in default["files"]]


def test_custom_section_and_boundary_regex():
    block = {"bugreport": {"section_regex": r"^=== LOGCAT (?P<title>\w+) \[cmd: (?P<cmd>[^\]]*)\] ===$",
                           "boundary_regex": r"^=== .* ===$"}}
    result = _extract(block, CUSTOM_BUGREPORT)
    assert [(f["buffer"], f["lines"]) for f in result["files"]] == [("radio", 1), ("main", 1)]
    # 기본 규칙으로는 못 찾는다 (메시지는 wanted_buffers를 따른다)
    with pytest.raises(bugreport.BugreportError, match=r"logcat 섹션\(system/radio/main\)"):
        _extract(None, CUSTOM_BUGREPORT)
    with pytest.raises(bugreport.BugreportError, match=r"logcat 섹션\(radio\)"):
        _extract({"bugreport": {"wanted_buffers": ["radio"]}}, "== dumpstate\nBuild: x\n")


def test_zip_bugreport_with_override(tmp_path):
    zpath = tmp_path / "bugreport-a.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("bugreport-a.txt", BUGREPORT)
    prof = platforms.load({"platform": {"bugreport": {"wanted_buffers": ["system"]}}})
    result = bugreport.extract(zpath, tmp_path / "o", prof.bugreport)
    assert [f["buffer"] for f in result["files"]] == ["system"]


# -- 7. 소스 트리 ----------------------------------------------------------------------------------


def _validate(profile_block, aosp: Path, version: str | None = None):
    import code_roots

    tree = platforms.load({"platform": profile_block} if profile_block is not None else None).source_tree
    return code_roots.validate({"aosp": str(aosp)}, ["aosp", "vendor_ril"], version, tree)


def test_validate_default_matches_old_behavior():
    import code_roots

    ok = _validate(None, SRC16, "16")
    assert ok["valid"] and ok["estimated_version"] == "16" and ok["warnings"] == []
    assert code_roots.validate({"aosp": str(SRC16)}, ["aosp"], "16") == ok
    empty = _tmp()
    bad = code_roots.validate({"aosp": str(empty)}, ["aosp"], None)
    assert bad["errors"] == [f"aosp 루트에 frameworks/opt/telephony가 없습니다: {empty}"]


def test_required_dirs_override():
    assert _validate({"source_tree": {"required_dirs": ["vendor/mockril"]}}, SRC17)["valid"]
    bad = _validate({"source_tree": {"required_dirs": ["frameworks/opt/telephony", "vendor/none", "out/none"]}}, SRC17)
    assert not bad["valid"]
    assert [e.split(" 없습니다")[0] for e in bad["errors"]] == ["aosp 루트에 vendor/none가", "aosp 루트에 out/none가"]


def test_version_sources_override():
    block = {"source_tree": {"version_sources": [
        {"file": "vendor/mockril/libril/mock_ril.c", "regex": r"NOPE(\d+)"},
        {"file": "build/make/core/version_defaults.mk", "regex": r"^\s*PLATFORM_VERSION\s*:?=\s*(\d+)"}]}}
    assert _validate(block, SRC17)["estimated_version"] == "17"
    miss = {"source_tree": {"version_sources": [{"file": "no/such/file", "regex": r"(\d+)"}]}}
    res = _validate(miss, SRC17)
    assert res["estimated_version"] is None and res["valid"]


def test_code_roots_cli_uses_platform_block():
    root = _root({"source_tree": {"required_dirs": ["vendor/none"]}})
    proc = _script(root, "code_roots.py", "validate", str(SRC17))
    assert proc.returncode == 2
    assert f"aosp 루트에 vendor/none가 없습니다: {SRC17}" in proc.stderr
    root = _root({"source_tree": {"required_dirs": ["vendor/mockril"]}})
    proc = _script(root, "code_roots.py", "validate", str(SRC17), "--version", "17")
    assert proc.returncode == 0, proc.stderr
