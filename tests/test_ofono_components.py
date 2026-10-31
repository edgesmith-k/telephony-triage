"""oFono 다중 구성요소(데몬) 틀 (17-platforms §9). **합성·형식 가정·placeholder**만 쓴다(`daemon-a`·`daemon-b`).

- 레지스트리: `components`(기본·덮어쓰기·오류), android는 `components`를 받지 않음, 설정 정의 짝 규칙(`kind: regex`)
- `regex` kind: 데몬 사이(다른 pid·tag) 짝, `observed_until` = 수집 구간 끝, 이름 채우기, 나중 요청이 대신함
- `msg_format`: 앞머리를 뗀 본문으로 짝 규칙을 본다(이벤트 `msg`는 원문), `split_tag` → tag `ident/subtag`
- `parse_logcat parse`(issue-db-ofono): `proto`·지연·파생 `ril_error`·`ril_timeout`·`ril_no_response`
- 기본 설정 출력 불변(구성요소 블록을 명시해도, 짝 규칙이 없으면 이전과 같다)
"""

from __future__ import annotations

import json
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(SCRIPTS))

from runner import copy_db, plugin_root, run, variant_db  # noqa: E402

import platforms  # noqa: E402
from common import events, masking  # noqa: E402
from platforms import Component, MsgView, PlatformConfigError, SourceTree  # noqa: E402
from platforms.ofono import msgformat, pairing  # noqa: E402

LOGS = REPO / "tests" / "fixtures" / "logs" / "ofono"
MULTI_LOG = LOGS / "journal-multi.log"
ISO_LOG = LOGS / "journal-iso.log"
ON = {"name": "android", "enabled": ["android", "ofono"]}

COMPONENTS = {
    "ofono": {"idents": ["ofonod"], "root_key": "ofono", "msg_format": "file_func"},
    "daemon-a": {"idents": ["daemon-a"], "root_key": "daemon_a",
                 "source_tree": {"required_dirs": ["src"],
                                 "version_sources": [{"file": "VERSION", "regex": r"^(\d+)"}]}},
    "daemon-b": {"idents": ["daemon-b"], "root_key": "daemon_b"},
}
IPC = {"kind": "regex", "tags": ["ofonod", "daemon-a", "daemon-b"],
       "request": r"^ipc call (?P<serial>\d+) (?P<name>[A-Z_]+)$",
       "response": r"^ipc reply (?P<serial>\d+)(?: error=(?P<error>\S+))?$"}


def _defaults(**ofono) -> dict:
    return {"platform": {**ON, "others": {"ofono": ofono}}}


def _load(**ofono):
    return platforms.load(_defaults(**ofono), "ofono")


def _error(**ofono) -> str:
    with pytest.raises(PlatformConfigError) as info:
        _load(**ofono)
    return str(info.value)


# -- 계약·레지스트리: components ------------------------------------------------------------------


def test_spec_default_component_and_hooks():
    spec = platforms.get("ofono")
    assert spec.components == (Component("ofono", ("ofonod",), root_key="ofono", msg_format="file_func"),)
    assert dict(spec.msg_formats) == {"file_func": msgformat.file_func}
    assert dict(spec.protocol_kinds) == {"regex": pairing.build}
    assert "components" in spec.block_keys and spec.protocols == ()
    prof = platforms.load(None, "ofono", require_enabled=False)
    assert prof.components == spec.components and prof.protocols == () and prof.protocol_tags == ()
    assert platforms.default("ofono").components == spec.components


def test_android_unchanged_and_rejects_components():
    android = platforms.get("android")
    assert (android.components, android.msg_formats, android.protocol_kinds) == ((), (), ())
    assert "components" not in android.block_keys
    prof = platforms.default("android")
    assert prof.components == () and prof.protocols == android.protocols
    assert platforms.load({}) == prof
    with pytest.raises(PlatformConfigError, match="platform.components: 알 수 없는 키"):
        platforms.load({"platform": {"components": {}}})


def test_components_override_replaces_entirely():
    prof = _load(components=COMPONENTS)
    assert [c.name for c in prof.components] == ["ofono", "daemon-a", "daemon-b"]
    a = prof.components[1]
    assert (a.idents, a.root_key, a.msg_format, a.split_tag) == (("daemon-a",), "daemon_a", None, False)
    assert a.source_tree.required_dirs == ("src",) and a.source_tree.version_sources[0][0] == "VERSION"
    assert prof.components[2].source_tree is None
    only_b = _load(components={"daemon-b": {"idents": ["daemon-b"]}})
    assert [c.name for c in only_b.components] == ["daemon-b"]              # 기본 ofono 구성요소도 빠진다
    assert _load(components={}).components == ()
    assert _load(components=None).components == platforms.get("ofono").components   # null = 생략(기본 유지)
    split = _load(components={"ofono": {"idents": ["ofonod"], "msg_format": "file_func", "split_tag": True}})
    assert split.components[0].split_tag is True and split.components[0].root_key is None


@pytest.mark.parametrize("components,path,why", [
    ([], "components", "매핑"),
    ({"Daemon": {"idents": ["x"]}}, "components.Daemon", "구성요소 이름"),
    ({"a": {"root_key": "a"}}, "components.a", "'idents'가 필요"),
    ({"a": {"idents": []}}, "components.a.idents", "비어 있으면"),
    ({"a": {"idents": [""]}}, "components.a.idents[0]", "비어 있지 않은"),
    ({"a": {"idents": ["x"]}, "b": {"idents": ["y", "x"]}}, "components.b.idents[1]", "겹칩니다"),
    ({"a": {"idents": ["x"], "root_key": "daemon-a"}}, "components.a.root_key", "^[a-z]"),
    ({"a": {"idents": ["x"], "root_key": "r"}, "b": {"idents": ["y"], "root_key": "r"}}, "components.b.root_key", "겹칩니다"),
    ({"a": {"idents": ["x"], "source_tree": {"required_dirs": ["src"]}}}, "components.a.source_tree", "root_key"),
    ({"a": {"idents": ["x"], "root_key": "ofono", "source_tree": {"required_dirs": ["src"]}}},
     "components.a.source_tree", "주 소스 루트"),
    ({"a": {"idents": ["x"], "root_key": "r", "source_tree": {"required_dirs": ["/abs"]}}},
     "components.a.source_tree.required_dirs[0]", "상대 경로"),
    ({"a": {"idents": ["x"], "msg_format": "nosuch"}}, "components.a.msg_format", "알 수 없는 형식"),
    ({"a": {"idents": ["x"], "split_tag": True}}, "components.a.split_tag", "msg_format"),
    ({"a": {"idents": ["x"], "msg_format": "file_func", "split_tag": "yes"}}, "components.a.split_tag", "true/false"),
    ({"a": {"idents": ["x"], "category": "data"}}, "components.a.category", "알 수 없는 키"),
])
def test_component_errors(components, path, why):
    msg = _error(components=components)
    assert f"site-defaults.yaml platform.others.ofono.{path}" in msg and why in msg, msg


def test_component_errors_checked_even_when_loading_android():
    with pytest.raises(PlatformConfigError, match="platform.others.ofono.components.a.idents"):
        platforms.load(_defaults(components={"a": {"idents": []}}))


# -- 계약·레지스트리: 설정 정의 짝 규칙 (protocol kinds) ------------------------------------------------


def test_regex_protocol_from_config():
    prof = _load(protocols={"ipc": IPC, "other": {**IPC, "tags": ["daemon-b"]}})
    assert [p.name for p in prof.protocols] == ["ipc", "other"]
    assert prof.protocol_tags == (("ipc", frozenset({"ofonod", "daemon-a", "daemon-b"})), ("other", frozenset({"daemon-b"})))
    assert prof.protocols[1].default_tags == frozenset({"daemon-b"})


@pytest.mark.parametrize("protocols,path,why", [
    ({"ril": IPC}, "protocols.ril", "ril이 아니어야"),
    ({"Bad-Name": IPC}, "protocols.Bad-Name", "^[a-z]"),
    ({"ipc": {k: v for k, v in IPC.items() if k != "kind"}}, "protocols.ipc.kind", "허용: regex"),
    ({"ipc": {**IPC, "kind": "nosuch"}}, "protocols.ipc.kind", "허용: regex"),
    ({"ipc": {k: v for k, v in IPC.items() if k != "kind"}}, "protocols.ipc.kind", "필요한 키"),
    ({"ipc": {**IPC, "kind": "nosuch"}}, "protocols.ipc.kind", "알 수 없는 kind"),
    ({"ipc": {**IPC, "kind": ["regex"]}}, "protocols.ipc.kind", "알 수 없는 kind"),   # 해시 불가 값도 TypeError가 아니라 오류
    ({"ipc": {**IPC, "kind": {}}}, "protocols.ipc.kind", "알 수 없는 kind"),
    ({"ipc": {**IPC, "kind": None}}, "protocols.ipc.kind", "알 수 없는 kind"),
    ({"ipc": [1]}, "protocols.ipc", "매핑"),
    ({"ipc": {**IPC, "conv": "x"}}, "protocols.ipc.conv", "알 수 없는 키"),
    ({"ipc": {k: v for k, v in IPC.items() if k != "tags"}}, "protocols.ipc", "'tags'가 필요"),
    ({"ipc": {**IPC, "tags": []}}, "protocols.ipc.tags", "비어 있으면"),
    ({"ipc": {**IPC, "tags": [""]}}, "protocols.ipc.tags[0]", "비어 있지 않은"),
    ({"ipc": {k: v for k, v in IPC.items() if k != "response"}}, "protocols.ipc", "'response'가 필요"),
    ({"ipc": {**IPC, "request": r"call (\d+)"}}, "protocols.ipc.request", "(?P<serial>"),
    ({"ipc": {**IPC, "response": "reply ("}}, "protocols.ipc.response", "정규식 오류"),
])
def test_regex_protocol_errors(protocols, path, why):
    msg = _error(protocols=protocols)
    assert f"site-defaults.yaml platform.others.ofono.{path}" in msg and why in msg, msg


@pytest.fixture
def fake_platforms(tmp_path, monkeypatch):
    monkeypatch.setattr(platforms, "__path__", list(platforms.__path__) + [str(tmp_path)])
    made: list[str] = []

    def make(name: str, body: str) -> None:
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")
        made.append(name)

    yield make
    for name in made:
        sys.modules.pop(f"platforms.{name}", None)
        platforms._SPECS.pop(name, None)


def test_fixed_spec_protocol_still_tags_only_with_kinds(fake_platforms):
    """kind가 있는 플랫폼에서도 SPEC 고정 이름은 `tags`만 받고, 설정 정의 프로토콜은 SPEC 것 뒤에 붙는다."""
    fake_platforms("kinds", """
        import dataclasses
        from platforms.ofono import SPEC as _O
        from platforms.base import PairProtocol
        _DBUS = PairProtocol(name="dbus", default_tags=frozenset({"daemon-a"}), annotate=lambda *a: None,
                             pair=lambda records: None)
        SPEC = dataclasses.replace(_O, name="kinds", protocols=(_DBUS,))
    """)
    on = {"name": "android", "enabled": ["android", "kinds"]}
    prof = platforms.load({"platform": {**on, "others": {"kinds": {"protocols": {
        "ipc": IPC, "dbus": {"tags": ["daemon-b"]}}}}}}, "kinds")
    assert [p.name for p in prof.protocols] == ["dbus", "ipc"]
    assert [n for n, _ in prof.protocol_tags] == ["dbus", "ipc"] and dict(prof.protocol_tags)["dbus"] == {"daemon-b"}
    with pytest.raises(PlatformConfigError, match="platform.others.kinds.protocols.dbus.kind: 알 수 없는 키"):
        platforms.load({"platform": {**on, "others": {"kinds": {"protocols": {"dbus": {"kind": "regex"}}}}}}, "kinds")


# -- msgformat·pairing 단위 -------------------------------------------------------------------------


def test_file_func_format():
    assert msgformat.file_func("src/example.c:example_cb() ipc call 5 X") == MsgView("ipc call 5 X", "example")
    assert msgformat.file_func("plugins/sub/mod.c:fn()") == MsgView("", "mod")
    assert msgformat.file_func("ipc call 5 X") is None and msgformat.file_func("src/x.h:fn() y") is None


def test_regex_annotate_rules():
    proto = pairing.build("ipc", dict(IPC), "p")
    tags = frozenset(IPC["tags"])
    ann = proto.annotate("daemon-a", "ipc call 7 PLACEHOLDER_CALL", tags, None)
    assert ann == {"serial": 7, "dir": "req", "request": "PLACEHOLDER_CALL", "error": None, "paired_ts": None,
                   "latency_ms": None}
    assert list(ann) == list(events.RIL_KEYS)
    assert proto.annotate("daemon-b", "ipc reply 7 error=NONE", tags, None)["error"] == "NONE"
    assert proto.annotate("other", "ipc call 7 PLACEHOLDER_CALL", tags, None) is None        # tags 밖
    free = pairing.build("ipc", {**IPC, "response": r"^ipc reply (?P<serial>\S+)(?: error=(?P<error>.+))?$"}, "p")
    assert free.annotate("daemon-b", "ipc reply x7", tags, None) is None                     # 10진 아님
    assert free.annotate("daemon-b", "ipc reply 7 error=phone 010 fail", tags, None) is None  # 자유 문장 값은 싣지 않는다


PII = ("01012345678", "310150123456789", "10.20.30.40", "aa:bb:cc:dd:ee:ff")
LOOSE = {**IPC, "request": r"^ipc call (?P<serial>\d+) (?P<name>\S+)$",
         "response": r"^ipc reply (?P<serial>\d+)(?: error=(?P<error>\S+))?$"}


@pytest.mark.parametrize("value", PII)
def test_regex_annotate_refuses_pii_like_values(value):
    """전화번호·IMSI·IP(숫자로 시작)·MAC(`:`)은 식별자 모양이 아니다 — 주석에 싣지 않는다."""
    proto = pairing.build("ipc", dict(LOOSE), "p")
    tags = frozenset(IPC["tags"])
    assert proto.annotate("daemon-a", f"ipc call 7 {value}", tags, None) is None
    assert proto.annotate("daemon-b", f"ipc reply 7 error={value}", tags, None) is None
    for ok in ("PLACEHOLDER_CALL", "GetProperties", "org.ofono.Error.Failed", "NONE"):
        assert proto.annotate("daemon-b", f"ipc reply 7 error={ok}", tags, None)["error"] == ok


def test_mask_record_masks_proto_annotation_values():
    """`--mask`의 두 번째 방어: `proto` 주석의 request·error를 마스킹하고 파생 `ril_error` 필드도 그 값이다.
    android 주석(`proto` 없음)은 그대로(같은 객체)."""
    import parse_logcat

    masker = masking.new_masker()
    for ok in ("PLACEHOLDER_CALL", "GetProperties", "org.ofono.Error.Failed", "NONE"):
        assert masker.mask_value(ok) == ok
    rules = type("Rules", (), {"requests": {"PLACEHOLDER_CALL": {"timeout_ms": 1000}}})()
    for value in PII:
        masker = masking.new_masker()
        line = {**_rec(0, None), "msg": f"ipc reply 7 error={value}", "event": None, "fields": {},
                "pid": 1, "tid": 1, "level": "I", "phone_id": None, "source": "backend:x", "line_ref": None}
        line.pop("_dt")
        for request, error in (("PLACEHOLDER_CALL", value), (value, "NONE")):
            ann = {**_ann("resp", 7, request), "error": error}
            out = parse_logcat._mask_record({**line, "ril": ann}, masker)
            assert value not in json.dumps(out), out
            assert out["msg"] == "ipc reply 7 error=" + out["ril"]["error" if error == value else "request"]
            assert ann["request"] == request and ann["error"] == error      # 입력 레코드는 바꾸지 않는다
            derived = parse_logcat._ril_events(out, rules, None)
            assert value not in json.dumps(derived), derived
            if request == "PLACEHOLDER_CALL":
                assert derived[0]["fields"]["error"] == out["ril"]["error"] and out["ril"]["error"].startswith("<")
    android = {k: v for k, v in _ann("resp", 7, "SETUP_DATA_CALL").items() if k != "proto"}
    rec = {**_rec(0, android), "msg": "x", "fields": {}}
    assert parse_logcat._mask_record(rec, masking.new_masker())["ril"] is android


def _journal(tmp_path: Path, values) -> Path:
    lines = ["2026-09-20T14:40:00.000000+09:00 dut daemon-a[901]: ipc call 8 PLACEHOLDER_CALL"]
    for i, value in enumerate(values):
        ms = 100 + i * 100
        lines += [f"2026-09-20T14:40:00.{ms:03d}000+09:00 dut daemon-a[901]: ipc call {10 + i} {value}",
                  f"2026-09-20T14:40:00.{ms + 50:03d}000+09:00 dut daemon-b[902]: ipc reply 8 error={value}"]
    lines.append("2026-09-20T14:40:04.000000+09:00 dut daemon-b[902]: status: placeholder")
    path = tmp_path / "journal.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("mask", [False, True])
def test_parse_pii_values_never_reach_annotations(tmp_path, mask):
    """원문·`--mask` 두 경로 모두 PII 모양 값은 `ril`·파생 필드에 실리지 않는다(`--mask`면 출력 어디에도 없다)."""
    log = _journal(tmp_path, PII)
    root = plugin_root("ofono-multi", platform={**ON, "others": {"ofono": {"components": COMPONENTS,
                                                                            "protocols": {"ipc": LOOSE}}}})
    args = ["parse", log, "--rules", variant_db("issue-db-ofono") / "parser-rules", "--full"] + (["--mask"] if mask else [])
    proc = run("parse_logcat.py", args, root=root)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    anns = [e["ril"] for e in out["events"] if e["ril"]]
    assert [(a["dir"], a["serial"], a["request"]) for a in anns] == [("req", 8, "PLACEHOLDER_CALL")]
    picked = json.dumps([(e["ril"], e["fields"]) for e in out["events"]])
    assert not any(v in picked for v in PII), picked
    if mask:
        assert not any(v in proc.stdout for v in PII)


def test_split_tag_requires_identifier_subtag():
    """이벤트 tag는 마스킹되지 않는다 — 식별자 모양이 아닌 subtag는 tag를 나누지 않는다."""
    import dataclasses

    from platforms.ofono.backend import BACKEND, SUBTAG_RE

    split = {"ofono": {"idents": ["ofonod"], "msg_format": "file_func", "split_tag": True}}
    prof = _load(components=split)
    for subtag, want in (("example", "ofonod/example"), ("gprs-context", "ofonod/gprs-context"),
                         ("01012345678", "ofonod"), ("a b", "ofonod"), ("x/y", "ofonod"), ("aa:bb", "ofonod"),
                         ("", "ofonod"), (None, "ofonod")):
        spec = dataclasses.replace(prof.spec, msg_formats=(("file_func", lambda m, s=subtag: MsgView(m, s)),))
        backend = BACKEND.configure(dataclasses.replace(prof, spec=spec))
        tags = {e["tag"] for e in backend.parse([MULTI_LOG], None, None, None) if e["msg"].startswith("src/")}
        assert tags == {want}, (subtag, tags)
    assert not SUBTAG_RE.fullmatch("1abc")


def _rec(sec: float, ann: dict | None, tag: str = "daemon-a") -> dict:
    from datetime import datetime, timedelta, timezone

    dt = datetime(2026, 9, 20, tzinfo=timezone.utc) + timedelta(seconds=sec)
    return {"ts": dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "_dt": dt, "tag": tag, "ril": ann}


def _ann(direction, serial, request=None, proto="ipc"):
    return {"serial": serial, "dir": direction, "request": request, "error": None, "paired_ts": None,
            "latency_ms": None, "proto": proto}


def test_regex_pair_rules():
    proto = pairing.build("ipc", dict(IPC), "p")
    records = [_rec(0, _ann("req", 1, "OLD")), _rec(1, _ann("req", 1, "NEW")),              # 나중 요청이 대신한다
               _rec(1.5, _ann("req", 2, None)), _rec(2, _ann("resp", 1)),
               _rec(2.5, _ann("resp", 2, "NAMED")), _rec(3, _ann("req", 4, "X", proto="dbus")),   # 다른 프로토콜
               _rec(9, None, tag="daemon-b")]
    proto.pair(records)
    old, new, unnamed, resp1, resp2, other = (r["ril"] for r in records[:6])
    assert (new["latency_ms"], resp1["latency_ms"], resp1["request"]) == (1000, 1000, "NEW")      # 응답 이름 채움
    assert (unnamed["request"], resp2["latency_ms"]) == ("NAMED", 1000)                            # 요청 이름 채움
    assert old["paired_ts"] is None and "observed_until" not in old           # 밀려난 요청은 응답 없음으로 단정하지 않는다
    assert "observed_until" not in new and "observed_until" not in other and other["paired_ts"] is None
    lone = [_rec(0, _ann("req", 1, "A")), _rec(0.5, _ann("req", 1, "B")), _rec(1, _ann("req", 2, "C")),
            _rec(9, None, tag="daemon-b"), _rec(8.9, None, tag="daemon-a")]               # 파일 순서 끝이 조금 뒤로 감김
    proto.pair(lone)
    a, b, c = (r["ril"] for r in lone[:3])
    assert "observed_until" not in a                                              # 밀려남
    assert b["observed_until"] == c["observed_until"] == lone[3]["ts"]            # 구간의 가장 늦은 시각(태그 무관)
    assert list(c)[-2:] == ["proto", "observed_until"]


# -- 백엔드: 한 스트림 안 데몬 사이 짝 ------------------------------------------------------------------


def _backend(**ofono):
    from platforms.ofono.backend import BACKEND

    return BACKEND.configure(_load(**ofono))


def _anns(out) -> dict:
    return {(e["tag"], e["ril"]["dir"], e["ril"]["serial"]): e["ril"] for e in out if e["ril"]}


def test_backend_cross_daemon_pairing():
    out = _backend(components=COMPONENTS, protocols={"ipc": IPC}).parse([MULTI_LOG], None, None, None)
    anns = _anns(out)
    assert set(anns) == {("ofonod", "req", 5), ("ofonod", "resp", 5), ("daemon-a", "req", 7), ("daemon-b", "resp", 7),
                         ("daemon-b", "resp", 3), ("daemon-a", "req", 8), ("daemon-b", "resp", 8), ("daemon-a", "req", 9)}
    assert all(a["proto"] == "ipc" for a in anns.values())
    assert (anns[("daemon-a", "req", 7)]["latency_ms"], anns[("daemon-b", "resp", 7)]["request"]) == (150, "PLACEHOLDER_CALL")
    assert anns[("ofonod", "resp", 5)]["latency_ms"] == 500                     # DBG 앞머리를 뗀 본문으로 짝
    assert (anns[("daemon-b", "resp", 8)]["latency_ms"], anns[("daemon-b", "resp", 8)]["error"]) == (1500, "PLACEHOLDER_ERROR")
    assert anns[("daemon-b", "resp", 3)]["paired_ts"] is None and "observed_until" not in anns[("daemon-b", "resp", 3)]
    assert anns[("daemon-a", "req", 9)]["observed_until"] == "2026-09-20T05:40:04.000Z"
    ofonod = [e for e in out if e["tag"] == "ofonod"]
    assert ofonod[0]["msg"].startswith("src/example.c:example_cb() ipc call 5")  # 이벤트 msg는 원문
    assert events.validate_events(out) == []


def test_backend_without_msg_format_misses_prefixed_lines():
    plain = {**COMPONENTS, "ofono": {"idents": ["ofonod"], "root_key": "ofono"}}
    anns = _anns(_backend(components=plain, protocols={"ipc": IPC}).parse([MULTI_LOG], None, None, None))
    assert ("ofonod", "req", 5) not in anns and ("daemon-a", "req", 7) in anns


def test_backend_split_tag():
    split = {**COMPONENTS, "ofono": {"idents": ["ofonod"], "msg_format": "file_func", "split_tag": True}}
    out = _backend(components=split).parse([MULTI_LOG], None, None, None)
    assert {e["tag"] for e in out} == {"ofonod/example", "daemon-a", "daemon-b"}
    assert all(e["ril"] is None for e in out)                                   # 짝 규칙 없음
    default = _backend().parse([MULTI_LOG], None, None, None)
    assert {e["tag"] for e in default} == {"ofonod", "daemon-a", "daemon-b"}


def test_backend_default_output_unchanged():
    from platforms.ofono.backend import BACKEND

    base = BACKEND.parse([ISO_LOG, MULTI_LOG], None, None, None)
    for ofono in ({}, {"components": COMPONENTS}, {"components": {}}):
        assert _backend(**ofono).parse([ISO_LOG, MULTI_LOG], None, None, None) == base, ofono
    assert all(e["ril"] is None for e in base)


# -- parse_logcat: 이슈 DB 규칙·파생 이벤트 -------------------------------------------------------------


def _parse(log: Path, rules: Path, ofono: dict | None) -> dict:
    root = plugin_root("ofono-multi", platform={**ON, "others": {"ofono": ofono}}) if ofono is not None else None
    kw = {"root": root} if root else {}
    proc = run("parse_logcat.py", ["parse", log, "--rules", rules, "--full", "--mask"], **kw)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_parse_cross_daemon_derived_events():
    out = _parse(MULTI_LOG, variant_db("issue-db-ofono") / "parser-rules", {"components": COMPONENTS, "protocols": {"ipc": IPC}})
    assert out["backend"] == {"name": "ofono_reference", "version": "0.0.2"}
    assert out["errors"] == [] and events.validate_events(out["events"]) == []
    derived = [(e["event"], e["tag"], e["fields"]) for e in out["events"] if e["source"] == "rules"]
    assert derived == [                                       # 응답 줄 바로 뒤(ril_error → ril_timeout), 그다음 응답 없음
        ("ril_error", "daemon-b", {"request": "PLACEHOLDER_CALL", "serial": "8", "error": "PLACEHOLDER_ERROR"}),
        ("ril_timeout", "daemon-b", {"request": "PLACEHOLDER_CALL", "serial": "8", "latency_ms": "1500", "timeout_ms": "1000"}),
        ("ril_no_response", "daemon-a", {"request": "PLACEHOLDER_CALL", "serial": "9", "timeout_ms": "1000"}),
    ]
    lines = [e for e in out["events"] if e["event"] is None]
    req7 = next(e for e in lines if e["ril"] and e["ril"]["serial"] == 7 and e["ril"]["dir"] == "req")
    assert req7["tag"] == "daemon-a" and req7["category_hint"] == "call"        # ril.yaml 요청 카테고리
    assert req7["ril"]["proto"] == "ipc" and req7["ril"]["latency_ms"] == 150


def test_parse_default_config_unchanged():
    rules = variant_db("issue-db-ofono") / "parser-rules"
    base = _parse(MULTI_LOG, rules, None)
    assert [e for e in base["events"] if e["source"] == "rules" or e["ril"]] == []
    assert _parse(MULTI_LOG, rules, {"components": COMPONENTS}) == base


def test_parse_split_tag_with_tag_regex():
    db = copy_db(variant_db("issue-db-ofono"), "ofono-split")
    tags = db / "parser-rules" / "tags.yaml"
    tags.write_text(tags.read_text(encoding="utf-8").replace(
        "  - {tag: ofonod,   category: common,",
        "  - {tag_regex: '^ofonod/example$', category: network, added_for: '-', added_on: 2026-10-30, reason: placeholder}\n"
        "  - {tag: ofonod,   category: common,"), encoding="utf-8")
    split = {**COMPONENTS, "ofono": {"idents": ["ofonod"], "msg_format": "file_func", "split_tag": True}}
    out = _parse(MULTI_LOG, db / "parser-rules", {"components": split})
    cats = {e["tag"]: e["category_hint"] for e in out["events"] if e["event"] is None}
    assert cats == {"ofonod/example": "network", "daemon-a": "data", "daemon-b": "call"}
    shutil.rmtree(db, ignore_errors=True)


def test_multi_fixture_is_masked_already():
    text = MULTI_LOG.read_text(encoding="utf-8")
    masker = masking.new_masker(text, ())
    assert "\n".join(masker(line) for line in text.split("\n")) == text


def test_source_tree_type_reexported():
    assert platforms.SourceTree is SourceTree and platforms.Component is Component
