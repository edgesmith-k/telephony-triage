"""플랫폼 레지스트리 (17-platforms 설계 §2-3, §7-B 레지스트리 부분).

- 이름 검증(정규식·`base`·`_x`), 설치된 플랫폼 목록(`known`), `SPEC` 타입·이름 확인(임시 패키지)
- `enabled`·`load(defaults, name)`·`others` 블록 검증, `backend_name`, `raw_line_finders`
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import platforms  # noqa: E402
from platforms import PlatformConfigError, PlatformSpec  # noqa: E402
import platforms.android as android  # noqa: E402


@pytest.fixture
def fake_platforms(tmp_path, monkeypatch):
    """`platforms.__path__`에 임시 디렉토리를 더해 가짜 플랫폼 패키지를 만든다. 끝나면 모듈·캐시를 지운다."""
    monkeypatch.setattr(platforms, "__path__", list(platforms.__path__) + [str(tmp_path)])
    made: list[str] = []

    def make(name: str, body: str, package: bool = True) -> None:
        if package:
            (tmp_path / name).mkdir()
            (tmp_path / name / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")
        else:
            (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
        made.append(name)

    yield make
    for name in made:
        sys.modules.pop(f"platforms.{name}", None)
        platforms._SPECS.pop(name, None)


# -- 이름·known ----------------------------------------------------------------------


def test_known_lists_installed_packages_only():
    names = platforms.known()
    assert "android" in names
    assert "base" not in names and all(not n.startswith("_") for n in names)
    assert names == sorted(names)


@pytest.mark.parametrize("name", ["../x", "Android", "_x", "base", "a.b", "a/b", "", None, 1, "1x"])
def test_bad_names_rejected(name):
    with pytest.raises(PlatformConfigError, match="지원 플랫폼: android"):
        platforms.get(name)


def test_unknown_name_rejected():
    with pytest.raises(PlatformConfigError, match=r"지원 플랫폼: .*'nosuch'"):
        platforms.get("nosuch")


def test_get_returns_spec_and_caches():
    spec = platforms.get("android")
    assert isinstance(spec, PlatformSpec)
    assert spec is android.SPEC is platforms.get("android")
    assert platforms.label("android") == "Android"


# -- SPEC 타입 ----------------------------------------------------------------------


def test_package_without_spec_rejected(fake_platforms):
    fake_platforms("nospec", "X = 1\n")
    assert "nospec" in platforms.known()
    with pytest.raises(PlatformConfigError, match="SPEC가 PlatformSpec이 아닙니다"):
        platforms.get("nospec")


def test_spec_of_wrong_type_rejected(fake_platforms):
    fake_platforms("wrongtype", "SPEC = {'name': 'wrongtype'}\n")
    with pytest.raises(PlatformConfigError, match="SPEC가 PlatformSpec이 아닙니다"):
        platforms.get("wrongtype")


def test_spec_name_must_match_package(fake_platforms):
    fake_platforms("renamed", """
        import dataclasses
        from platforms.android import SPEC as _A
        SPEC = dataclasses.replace(_A, name="other")
    """)
    with pytest.raises(PlatformConfigError, match="패키지 이름과 다릅니다"):
        platforms.get("renamed")


def test_plain_module_is_not_a_platform(fake_platforms):
    fake_platforms("flat", "SPEC = None\n", package=False)
    assert "flat" not in platforms.known()
    with pytest.raises(PlatformConfigError, match="지원 플랫폼"):
        platforms.get("flat")


def test_missing_dependency_inside_platform_is_not_hidden(fake_platforms):
    fake_platforms("broken", "import no_such_dependency_xyz\n")
    with pytest.raises(ModuleNotFoundError):
        platforms.get("broken")


# -- enabled·load(name)·others ----------------------------------------------------


def _second(fake_platforms, name: str = "second") -> None:
    """android SPEC을 이름만 바꾼 두 번째 플랫폼 (block_keys는 source_tree·log)."""
    fake_platforms(name, f"""
        import dataclasses
        from platforms.android import SPEC as _A
        SPEC = dataclasses.replace(_A, name={name!r}, label="Second", capture=None, protocols=(),
                                   default_backend="second_reference", block_keys=("source_tree", "log"))
    """)


def test_enabled_default_is_platform_name():
    assert platforms.enabled(None) == ["android"]
    assert platforms.enabled({"platform": {"name": "android"}}) == ["android"]


@pytest.mark.parametrize("block,path", [
    ({"enabled": "android"}, "platform.enabled"),
    ({"enabled": []}, "platform.enabled"),
    ({"enabled": ["android", "android"]}, "platform.enabled"),
    ({"enabled": ["android", "nosuch"]}, "platform.enabled[1]"),
    ({"enabled": ["Android"]}, "platform.enabled[0]"),
])
def test_enabled_invalid(block, path):
    with pytest.raises(PlatformConfigError) as info:
        platforms.load({"platform": block})
    assert f"site-defaults.yaml {path}" in str(info.value)


def test_enabled_must_include_default(fake_platforms):
    _second(fake_platforms)
    with pytest.raises(PlatformConfigError, match="기본 플랫폼"):
        platforms.enabled({"platform": {"enabled": ["second"]}})


def test_load_other_platform_uses_others_block(fake_platforms):
    _second(fake_platforms)
    defaults = {"platform": {"name": "android", "enabled": ["android", "second"],
                             "others": {"second": {"source_tree": {"required_dirs": ["src"]}}}}}
    assert platforms.load(defaults) == platforms.default()
    prof = platforms.load(defaults, "second")
    assert prof.name == "second" and prof.spec is platforms.get("second")
    assert prof.source_tree.required_dirs == ("src",)
    assert prof.ril_tags == frozenset() and prof.bugreport is None and prof.ril_vendor is None


def test_load_rejects_platform_not_enabled(fake_platforms):
    _second(fake_platforms)
    with pytest.raises(PlatformConfigError, match="켜져 있지 않습니다"):
        platforms.load(None, "second")


@pytest.mark.parametrize("others,path", [
    ({"second": {"ril": {"tags": []}}}, "platform.others.second.ril"),        # second의 block_keys 밖
    ({"second": {"source_tree": {"required_dirs": []}}}, "platform.others.second.source_tree.required_dirs"),
    ({"android": {}}, "platform.others.android"),                              # 기본 플랫폼은 others에 두지 않는다
    ({"third": {}}, "platform.others.third"),                                  # enabled 밖
    ([], "platform.others"),
])
def test_others_block_invalid(fake_platforms, others, path):
    _second(fake_platforms)
    with pytest.raises(PlatformConfigError) as info:
        platforms.load({"platform": {"enabled": ["android", "second"], "others": others}}, "second")
    assert f"site-defaults.yaml {path}" in str(info.value)


# -- backend_name·raw_line_finders ----------------------------------------------------


def test_backend_name(fake_platforms):
    _second(fake_platforms)
    defaults = {"parser": {"backend": "site"}, "platform": {"enabled": ["android", "second"]}}
    assert platforms.backend_name(defaults, "android") == "site"
    assert platforms.backend_name(defaults) == "site"
    assert platforms.backend_name(defaults, "second") == "second_reference"
    defaults["parser"]["by_platform"] = {"second": "second_site"}
    assert platforms.backend_name(defaults, "second") == "second_site"


def test_raw_line_finders_union(fake_platforms):
    _second(fake_platforms)
    one = platforms.raw_line_finders(None)
    assert one == [(android.logcat.raw_line, android.logcat.find_raw, android.bugreport.sniff_line)]
    two = platforms.raw_line_finders({"platform": {"enabled": ["android", "second"]}})
    assert len(two) == 2 and two[1][2] is None


def test_known_raw_line_finders_isolates_broken_platform(fake_platforms):
    fake_platforms("broken", "import no_such_dependency_xyz\n")
    finders, errors = platforms.known_raw_line_finders()
    assert [f[0] for f in finders] == [n for n in platforms.known() if n != "broken"]
    assert finders[0][1:] == (android.logcat.raw_line, android.logcat.find_raw, android.bugreport.sniff_line)
    assert [(n, type(e)) for n, e in errors] == [("broken", ModuleNotFoundError)]


# -- 묶음 2: K6 관문·others 전부 검증·백엔드 규칙·capture·프로토콜 태그·ril.pair 자기 주석 ---------------


def test_ofono_skeleton_is_installed():
    assert "ofono" in platforms.known()
    spec = platforms.get("ofono")
    assert spec.label == "oFono" and spec.capture is None and spec.protocols == ()
    assert spec.default_backend == "ofono_reference" and spec.primary_root == "ofono"


def test_load_require_enabled_false_for_db_tools():
    with pytest.raises(PlatformConfigError, match="켜져 있지 않습니다"):
        platforms.load(None, "ofono")
    prof = platforms.load(None, "ofono", require_enabled=False)          # DB 고정 도구(K6)
    assert prof.name == "ofono" and prof.spec is platforms.get("ofono")
    with pytest.raises(PlatformConfigError, match="지원 플랫폼"):
        platforms.load(None, "nosuch", require_enabled=False)


def test_others_blocks_are_all_validated_at_load():
    bad = {"platform": {"enabled": ["android", "ofono"],
                        "others": {"ofono": {"source_tree": {"required_dirs": ["/abs"]}}}}}
    with pytest.raises(PlatformConfigError) as info:
        platforms.load(bad)                                             # android를 불러도 ofono 블록을 본다
    assert "site-defaults.yaml platform.others.ofono.source_tree.required_dirs[0]" in str(info.value)
    # 켜지 않은 설치된 플랫폼의 상수도 둘 수 있다(DB 고정 도구가 쓴다)
    prof = platforms.load({"platform": {"others": {"ofono": {"source_tree": {"required_dirs": ["src2"]}}}}},
                          "ofono", require_enabled=False)
    assert prof.source_tree.required_dirs == ("src2",)


def test_backend_name_rules():
    assert platforms.backend_name({"parser": {"backend": "site"}}) == "site"
    assert platforms.backend_name({}) == "reference"                          # 기본 플랫폼도 SPEC 기본으로 대체
    assert platforms.backend_name({}, "ofono") == "ofono_reference"
    assert platforms.backend_name({"parser": {"by_platform": {"ofono": "ofono_site"}}}, "ofono") == "ofono_site"
    for parser, path in (({"by_platform": []}, "parser.by_platform"),
                         ({"by_platform": {"android": "x"}}, "parser.by_platform.android"),
                         ({"by_platform": {"nosuch": "x"}}, "parser.by_platform.nosuch")):
        with pytest.raises(PlatformConfigError) as info:
            platforms.backend_name({"parser": parser}, "ofono")
        assert f"site-defaults.yaml {path}" in str(info.value)


def test_capture_block_goes_through_capture_configure(fake_platforms):
    """레지스트리는 capture 규칙의 모양을 모른다: `block_key` 블록을 `configure`에 넘긴다."""
    fake_platforms("capt", """
        import dataclasses
        from platforms.android import SPEC as _A
        from platforms.base import config_error

        def _configure(rules, raw, path):
            if raw is None:
                return rules
            if not isinstance(raw, dict) or set(raw) - {"n"}:
                raise config_error(path, "n만 받는다")
            return ("rules", raw["n"])

        SPEC = dataclasses.replace(_A, name="capt", block_keys=("source_tree", "dump"),
                                   capture=dataclasses.replace(_A.capture, default_rules=("rules", 0),
                                                               block_key="dump", configure=_configure))
    """)
    on = {"name": "android", "enabled": ["android", "capt"]}
    assert platforms.load({"platform": on}, "capt").bugreport == ("rules", 0)
    prof = platforms.load({"platform": {**on, "others": {"capt": {"dump": {"n": 3}}}}}, "capt")
    assert prof.bugreport == ("rules", 3)
    with pytest.raises(PlatformConfigError, match="platform.others.capt.dump: n만 받는다"):
        platforms.load({"platform": {**on, "others": {"capt": {"dump": {"x": 1}}}}}, "capt")


def test_protocol_tags_override(fake_platforms):
    fake_platforms("proto", """
        import dataclasses
        from platforms.android import SPEC as _A
        from platforms.base import PairProtocol
        _DBUS = PairProtocol(name="dbus", default_tags=frozenset({"daemon-a"}), annotate=lambda *a: None,
                             pair=lambda records: None)
        SPEC = dataclasses.replace(_A, name="proto", capture=None, protocols=(_A.protocols[0], _DBUS),
                                   block_keys=("source_tree", "log", "ril", "protocols"))
    """)
    on = {"name": "android", "enabled": ["android", "proto"]}
    prof = platforms.load({"platform": on}, "proto")
    assert prof.protocol_tags == (("ril", frozenset({"RILJ"})), ("dbus", frozenset({"daemon-a"})))
    prof = platforms.load({"platform": {**on, "others": {"proto": {"ril": {"tags": ["VR"]},
                                                                      "protocols": {"dbus": {"tags": ["daemon-b"]}}}}}},
                          "proto")
    assert prof.protocol_tags == (("ril", frozenset({"VR"})), ("dbus", frozenset({"daemon-b"})))
    with pytest.raises(PlatformConfigError) as info:     # ril은 기존 ril 블록, protocols에는 ril 밖 이름만
        platforms.load({"platform": {**on, "others": {"proto": {"protocols": {"ril": {"tags": []}}}}}}, "proto")
    assert "platform.others.proto.protocols.ril" in str(info.value)
    assert platforms.default().protocol_tags == (("ril", frozenset({"RILJ"})),)


def test_ril_pair_ignores_other_protocol_annotations():
    """android `ril.pair`는 자기 주석만 본다: `proto`가 붙은 다른 프로토콜 주석(다른 pid)은 pid 분할·짝에 쓰지 않는다."""
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def rec(sec, pid, direction, serial, request, proto=None):
        ann = {"serial": serial, "dir": direction, "request": request, "error": None, "paired_ts": None,
               "latency_ms": None}
        if proto:
            ann["proto"] = proto
        dt = t0 + timedelta(seconds=sec)
        return {"ril": ann, "pid": pid, "phone_id": 0, "ts": dt.isoformat(), "_dt": dt}

    records = [rec(0, 100, "req", 1, "SETUP_DATA_CALL"),
               rec(1, 900, "req", 7, "Connect", proto="dbus"),       # 다른 프로토콜·다른 pid
               rec(2, 100, "resp", 1, "SETUP_DATA_CALL")]
    android.ril.pair(records)
    assert records[0]["ril"]["latency_ms"] == 2000 and records[2]["ril"]["latency_ms"] == 2000
    assert records[1]["ril"]["paired_ts"] is None and "observed_until" not in records[1]["ril"]
