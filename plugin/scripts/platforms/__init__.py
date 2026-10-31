"""플랫폼 레지스트리 (RF-3, 17-platforms 설계 §2). 핵심(common·매처·db_*)은 플랫폼을 모른다.

플랫폼 하나 = `platforms/<name>/` 패키지 하나와 그 `SPEC: base.PlatformSpec`이다. 이 모듈은 플랫폼 이름을
모른다 — 이름으로 동적 import한다(`parser_backends.load`와 같은 방식, 이름은 `NAME_RE`). 기본 이름(`DEFAULT_NAME`)은
site-defaults에 `platform.name`이 없을 때만 쓴다.

- `get(name)`: 계약 `SPEC`. `known()`: 설치된 플랫폼 이름. `label(name)`: 출력 라벨.
- `enabled(defaults)`: site-defaults `platform.enabled`(이 설치에서 켠 플랫폼, 없으면 `[platform.name]`).
- `load(defaults, name=None)`: `site-defaults.yaml`의 `platform:` 블록(경로·태그·섹션 헤더 상수, RF-4,
  `02-config.md`)을 검증해 `PlatformProfile`로 준다. 기본 플랫폼은 `platform:` 블록 자체, 그 밖 플랫폼은
  `platform.others.<name>` 블록이다. 받는 상수 키는 `SPEC.block_keys`다. `components`(구성요소, 통째로 바뀜)와
  `protocols.<이름>: {kind, ...}`(설정 정의 짝 규칙, `SPEC.protocol_kinds`)는 `PlatformProfile.components`·`protocols`.
- `backend_name(defaults, name)`: 그 플랫폼의 파서 백엔드 이름. `raw_line_finders(defaults)`: 켠 플랫폼의 원문 줄 판별.

파일 I/O도 전역 상태도 없다(불변 `SPEC` 캐시만) — 호출한 쪽이 값을 들고 다니며(`ParserBackend.configure`,
`code_roots` 인자 등) 같은 프로세스에서 다른 설정으로 여러 번 불러도 서로 섞이지 않는다. 생략한 키는 `SPEC`의
기본값이고 그때 출력은 이전과 같다. 사용자 config로는 바꿀 수 없다 (`userconfig`를 거치지 않는다).
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from platforms.base import (  # noqa: F401  (계약 타입을 `platforms.X`로도 쓴다)
    DEFAULT_LINK_MS,
    CaptureSpec,
    Component,
    LogFormat,
    MsgView,
    PairProtocol,
    PhoneIdRules,
    PlatformConfigError,
    PlatformSpec,
    SourceTree,
    VendorRules,
    cfg_compile as _compile,
    cfg_list as _list,
    cfg_mapping,
    config_error as _err,
)

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
COMPONENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")   # 구성요소 이름 (placeholder `daemon-a`)
ROOT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")          # 소스 루트 키 = code_ref 키 형식 (plan.schema.json)
COMPONENT_KEYS = ("idents", "root_key", "source_tree", "msg_format", "split_tag")
DEFAULT_NAME = "android"
ENV = "TT_PLATFORM"            # 프로세스 간 선택 전달(triage → 하위 스크립트). 사람이 직접 쓰지 않는다
_NOT_PLATFORMS = {"base"}
_SPECS: dict[str, PlatformSpec] = {}


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    source_tree: SourceTree
    phone: PhoneIdRules
    ril_tags: frozenset
    bugreport: object | None                   # `SPEC.capture.default_rules` 형식 (capture 없는 플랫폼은 None)
    ril_vendor: VendorRules | None = None      # 선택 `platform.ril.vendor`. None이면 출력이 이전과 같다
    spec: PlatformSpec | None = None           # 레지스트리가 항상 채운다
    protocol_tags: tuple = ()                  # `((프로토콜 이름, frozenset 태그), ...)` — `protocols` 순서, ril은 `ril_tags`
    components: tuple = ()                     # `(Component, ...)` — `<블록>.components`(없으면 `SPEC.components`)
    protocols: tuple = ()                      # `(PairProtocol, ...)` — `SPEC.protocols` 다음 설정 정의(`kind`) 순서


# -- 레지스트리 --------------------------------------------------------------------


def known() -> list[str]:
    """설치된 플랫폼 이름(`platforms/` 아래 패키지, 정렬). 메시지 "지원 플랫폼: …"에 쓴다."""
    return sorted(
        info.name for info in pkgutil.iter_modules(__path__)
        if info.ispkg and info.name not in _NOT_PLATFORMS and NAME_RE.fullmatch(info.name)
    )


def _unsupported(name) -> str:
    return f"지원 플랫폼: {', '.join(known())} ({name!r})"


def get(name: str) -> PlatformSpec:
    """이름 → `SPEC`. 이름 검증 → `platforms.<name>` 패키지 import → `SPEC` 타입·이름 확인. 오류는 `PlatformConfigError`."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or name in _NOT_PLATFORMS:
        raise PlatformConfigError(_unsupported(name))
    if name in _SPECS:
        return _SPECS[name]
    module_name = f"{__name__}.{name}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == module_name or module_name.startswith(exc.name + ".")):
            raise PlatformConfigError(_unsupported(name)) from exc
        raise  # 플랫폼 모듈 안의 하위 의존성 누락은 그대로 올린다
    if not hasattr(module, "__path__"):
        raise PlatformConfigError(_unsupported(name))
    spec = getattr(module, "SPEC", None)
    if not isinstance(spec, PlatformSpec):
        raise PlatformConfigError(f"{module_name}.SPEC가 PlatformSpec이 아닙니다.")
    if spec.name != name:
        raise PlatformConfigError(f"{module_name}.SPEC.name이 패키지 이름과 다릅니다: {spec.name!r}")
    _SPECS[name] = spec
    return spec


def label(name: str) -> str:
    """출력 라벨 ("Android")."""
    return get(name).label


def _mapping(value, path: str, allowed: tuple[str, ...]) -> dict:
    return cfg_mapping(value, path, allowed)


def _mapping_any(value, path: str) -> dict:
    return cfg_mapping(value, path)


def _rel_path(value, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _err(path, "비어 있지 않은 문자열이어야 합니다.")
    if value.startswith(("/", "\\")) or PureWindowsPath(value).drive:
        raise _err(path, f"루트 기준 상대 경로여야 합니다: {value}")
    if ".." in PurePosixPath(value).parts or ".." in PureWindowsPath(value).parts:
        raise _err(path, f"'..'를 쓸 수 없습니다: {value}")
    return value


def _source_tree(raw, base: str, tree: SourceTree) -> SourceTree:
    node = _mapping(raw, base, ("required_dirs", "version_sources"))
    dirs, sources = tree.required_dirs, tree.version_sources
    if "required_dirs" in node:
        path = f"{base}.required_dirs"
        dirs = tuple(_rel_path(d, f"{path}[{i}]") for i, d in enumerate(_list(node["required_dirs"], path, non_empty=True)))
    if "version_sources" in node:
        path = f"{base}.version_sources"
        built = []
        for i, item in enumerate(_list(node["version_sources"], path, non_empty=True)):
            at = f"{path}[{i}]"
            item = _mapping(item, at, ("file", "regex"))
            for key in ("file", "regex"):
                if key not in item:
                    raise _err(at, f"'{key}'가 필요합니다.")
            built.append((_rel_path(item["file"], f"{at}.file"), _compile(item["regex"], f"{at}.regex", re.M)))
        sources = tuple(built)
    return SourceTree(dirs, sources)


def _phone_rules(raw, base: str, rules: PhoneIdRules) -> PhoneIdRules:
    node = _mapping(raw, base, ("phone_id",))
    if "phone_id" not in node:
        return rules
    at = f"{base}.phone_id"
    spec = _mapping(node["phone_id"], at, ("tag", "msg_prefix", "msg_suffix"))
    fields = {"tag": rules.tag, "msg_prefix": rules.prefix, "msg_suffix": rules.suffix}
    for key in spec:
        path = f"{at}.{key}"
        fields[key] = tuple(_compile(p, f"{path}[{i}]") for i, p in enumerate(_list(spec[key], path, non_empty=False)))
    return PhoneIdRules(fields["tag"], fields["msg_prefix"], fields["msg_suffix"])


def _tag(value, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _err(path, "비어 있지 않은 문자열이어야 합니다.")
    return value


def _ril_tags(raw, base: str, default_tags: frozenset) -> frozenset:
    node = _mapping(raw, base, ("tags", "vendor"))
    if "tags" not in node:
        return default_tags
    path = f"{base}.tags"
    return frozenset(_tag(t, f"{path}[{i}]") for i, t in enumerate(_list(node["tags"], path, non_empty=False)))


def _no_ril_tag(tag: str, path: str, ril_tags: frozenset) -> str:
    # 벤더 줄이 RIL로 해석되면 pair()의 pid 분할이 RILJ 짝을 깬다.
    if tag in ril_tags:
        raise _err(path, f"platform.ril.tags와 겹칩니다: {tag}")
    return tag


def _ril_vendor(raw, base: str, ril_tags: frozenset) -> VendorRules | None:
    """`platform.ril.vendor`: `layers`(필수)·`link_ms`(기본 2000)·`coverage_tags`(기본 없음)."""
    node = _mapping(raw, base, ("tags", "vendor"))
    if node.get("vendor") is None:
        return None
    at = f"{base}.vendor"
    spec = _mapping(node["vendor"], at, ("link_ms", "layers", "coverage_tags"))
    if "layers" not in spec:
        raise _err(at, "'layers'가 필요합니다.")
    link = spec.get("link_ms", DEFAULT_LINK_MS)
    if not isinstance(link, int) or isinstance(link, bool) or link <= 0:
        raise _err(f"{at}.link_ms", f"양의 정수(ms)여야 합니다: {link!r}")
    path, layers = f"{at}.layers", {}
    for i, item in enumerate(_list(spec["layers"], path, non_empty=True)):
        li = f"{path}[{i}]"
        item = _mapping(item, li, ("tag", "patterns"))
        for key in ("tag", "patterns"):
            if key not in item:
                raise _err(li, f"'{key}'가 필요합니다.")
        tag = _no_ril_tag(_tag(item["tag"], f"{li}.tag"), f"{li}.tag", ril_tags)
        if tag in layers:
            raise _err(f"{li}.tag", f"중복 태그입니다: {tag}")
        pats = []
        for j, raw_pat in enumerate(_list(item["patterns"], f"{li}.patterns", non_empty=True)):
            pp = f"{li}.patterns[{j}]"
            pat = _compile(raw_pat, pp, groups=0)
            # 그 밖 이름 그룹은 무시한다(나중에 그룹을 더해도 설정 호환).
            if ("serial" in pat.groupindex) == ("token" in pat.groupindex):
                raise _err(pp, "이름 그룹 (?P<serial>...)·(?P<token>...) 중 정확히 하나가 필요합니다.")
            pats.append(pat)
        layers[tag] = tuple(pats)
    cpath = f"{at}.coverage_tags"
    coverage = frozenset(_no_ril_tag(_tag(t, f"{cpath}[{i}]"), f"{cpath}[{i}]", ril_tags) for i, t in enumerate(_list(spec.get("coverage_tags", []), cpath, non_empty=False)))
    return VendorRules(tuple(layers.items()), link, coverage)


def _block(defaults: dict | None) -> dict:
    return _mapping_any((defaults or {}).get("platform"), "platform")


def default_name(defaults: dict | None) -> str:
    """site-defaults `platform.name`(없으면 `DEFAULT_NAME`). 검증하지 않는다 — `get`·`load`가 한다."""
    return _block(defaults).get("name", DEFAULT_NAME)


def _spec_at(name, path: str) -> PlatformSpec:
    try:
        return get(name)
    except PlatformConfigError as exc:
        raise _err(path, str(exc)) from exc


def enabled(defaults: dict | None) -> list[str]:
    """이 설치에서 켠 플랫폼. `platform.enabled`(목록, 중복 없음, 기본 이름 포함, 모두 설치돼 있어야 함), 없으면 `[platform.name]`."""
    node = _block(defaults)
    base = default_name(defaults)
    raw = node.get("enabled")
    if raw is None:
        return [base]
    path = "platform.enabled"
    items = _list(raw, path, non_empty=True)
    for i, name in enumerate(items):
        _spec_at(name, f"{path}[{i}]")
    if len(set(items)) != len(items):
        raise _err(path, "중복이 있습니다.")
    if base not in items:
        raise _err(path, f"기본 플랫폼(platform.name: {base})이 들어 있어야 합니다.")
    return list(items)


def _default_ril_tags(spec: PlatformSpec) -> frozenset:
    proto = next((p for p in spec.protocols if p.name == "ril"), None)
    return frozenset(proto.default_tags) if proto else frozenset()


def _protocols(spec: PlatformSpec, block: dict, base: str, ril_tags: frozenset) -> tuple[tuple, tuple]:
    """`((이름, 태그), ...)`와 `(PairProtocol, ...)`. SPEC 프로토콜: ril은 `ril_tags`(`<블록>.ril.tags`), 그 밖은
    `<블록>.protocols.<이름>.tags`(없으면 기본, `tags` 밖 키 거부). `SPEC.protocol_kinds`가 있으면 `protocols`의 다른
    키는 site가 이름 지은 짝 규칙(`{kind: <kind>, ...}`)이고 `kind` factory가 나머지 키를 검증한다. 순서는 SPEC 다음 설정."""
    fixed = tuple(p.name for p in spec.protocols)
    kinds = dict(spec.protocol_kinds)
    path = f"{base}.protocols"
    node = _mapping(block.get("protocols"), path, None if kinds else tuple(n for n in fixed if n != "ril"))
    tags_out, protos = [], list(spec.protocols)
    for proto in spec.protocols:
        if proto.name == "ril":
            tags_out.append((proto.name, ril_tags))
            continue
        at = f"{path}.{proto.name}"
        conf = _mapping(node.get(proto.name), at, ("tags",))
        if "tags" in conf:
            tpath = f"{at}.tags"
            tags = frozenset(_tag(t, f"{tpath}[{i}]") for i, t in enumerate(_list(conf["tags"], tpath, non_empty=False)))
        else:
            tags = frozenset(proto.default_tags)
        tags_out.append((proto.name, tags))
    for key, raw in node.items():
        if key in fixed and key != "ril":
            continue
        at = f"{path}.{key}"
        if key == "ril" or not isinstance(key, str) or not NAME_RE.fullmatch(key):
            raise _err(at, "짝 규칙 이름은 ^[a-z][a-z0-9_]*$이고 ril이 아니어야 합니다 (ril 태그는 <블록>.ril.tags).")
        conf = _mapping_any(raw, at)
        allowed = ", ".join(kinds)
        if "kind" not in conf:
            raise _err(f"{at}.kind", f"필요한 키입니다 (허용: {allowed}).")
        kind = conf["kind"]
        if not isinstance(kind, str) or kind not in kinds:
            raise _err(f"{at}.kind", f"알 수 없는 kind입니다 (허용: {allowed}): {kind!r}")
        proto = kinds[kind](key, conf, at)
        if not isinstance(proto, PairProtocol) or proto.name != key:
            raise _err(at, f"kind {kind}의 factory가 이름 {key!r}의 PairProtocol을 주지 않았습니다.")
        tags_out.append((key, frozenset(proto.default_tags)))
        protos.append(proto)
    return tuple(tags_out), tuple(protos)


def _components(raw, base: str, spec: PlatformSpec) -> tuple:
    """`<블록>.components.<이름>: {idents, root_key, source_tree, msg_format, split_tag}` → `(Component, ...)`.
    키를 쓰면 SPEC 기본 목록이 통째로 바뀐다(빈 매핑 = 구성요소 없음). `null`은 다른 블록 키처럼 생략과 같다(기본 유지)."""
    node = _mapping_any(raw, base)
    formats = dict(spec.msg_formats)
    seen_idents: dict[str, str] = {}
    seen_roots: dict[str, str] = {}
    out = []
    for name, item in node.items():
        at = f"{base}.{name}"
        if not isinstance(name, str) or not COMPONENT_NAME_RE.fullmatch(name):
            raise _err(at, "구성요소 이름은 ^[a-z][a-z0-9_-]*$여야 합니다.")
        item = _mapping(item, at, COMPONENT_KEYS)
        if "idents" not in item:
            raise _err(at, "'idents'가 필요합니다.")
        ipath = f"{at}.idents"
        idents = []
        for i, ident in enumerate(_list(item["idents"], ipath, non_empty=True)):
            ident = _tag(ident, f"{ipath}[{i}]")
            if ident in seen_idents:
                raise _err(f"{ipath}[{i}]", f"다른 구성요소({seen_idents[ident]})와 겹칩니다: {ident}")
            seen_idents[ident] = name
            idents.append(ident)
        root_key = item.get("root_key")
        if root_key is not None:
            if not isinstance(root_key, str) or not ROOT_KEY_RE.fullmatch(root_key):
                raise _err(f"{at}.root_key", f"^[a-z][a-z0-9_]*$여야 합니다: {root_key!r}")
            if root_key in seen_roots:
                raise _err(f"{at}.root_key", f"다른 구성요소({seen_roots[root_key]})와 겹칩니다: {root_key}")
            seen_roots[root_key] = name
        tree = None
        if "source_tree" in item:
            if root_key is None:
                raise _err(f"{at}.source_tree", "root_key가 있어야 합니다.")
            if root_key == spec.primary_root:
                raise _err(f"{at}.source_tree", f"주 소스 루트({root_key})는 <블록>.source_tree에 둡니다.")
            tree = _source_tree(item["source_tree"], f"{at}.source_tree", SourceTree((), ()))
        msg_format = item.get("msg_format")
        if msg_format is not None and (not isinstance(msg_format, str) or msg_format not in formats):
            raise _err(f"{at}.msg_format", f"알 수 없는 형식입니다 (허용: {', '.join(formats) or '없음'}): {msg_format!r}")
        split = item.get("split_tag", False)
        if not isinstance(split, bool):
            raise _err(f"{at}.split_tag", f"true/false여야 합니다: {split!r}")
        if split and msg_format is None:
            raise _err(f"{at}.split_tag", "msg_format이 있어야 합니다.")
        out.append(Component(name, tuple(idents), root_key, tree, msg_format, split))
    return tuple(out)


def default(name: str = DEFAULT_NAME) -> PlatformProfile:
    """코드 기본값 프로파일. 패턴은 `SPEC`의 객체 그대로다."""
    spec = get(name)
    ril_tags = _default_ril_tags(spec)
    return PlatformProfile(
        name=name,
        source_tree=spec.source_tree,
        phone=spec.phone,
        ril_tags=ril_tags,
        bugreport=spec.capture.default_rules if spec.capture else None,
        spec=spec,
        protocol_tags=tuple((p.name, ril_tags if p.name == "ril" else frozenset(p.default_tags)) for p in spec.protocols),
        components=spec.components,
        protocols=spec.protocols,
    )


def _build(spec: PlatformSpec, name: str, block: dict, base: str) -> PlatformProfile:
    ril_tags = _ril_tags(block.get("ril"), f"{base}.ril", _default_ril_tags(spec))
    capture = spec.capture
    rules = None
    if capture is not None:
        rules = capture.default_rules
        if capture.block_key and capture.configure is not None:
            rules = capture.configure(rules, block.get(capture.block_key), f"{base}.{capture.block_key}")
    protocol_tags, protocols = _protocols(spec, block, base, ril_tags)
    components = spec.components
    if "components" in spec.block_keys and block.get("components") is not None:   # null = 생략(기본 유지)
        components = _components(block["components"], f"{base}.components", spec)
    return PlatformProfile(
        name=name,
        source_tree=_source_tree(block.get("source_tree"), f"{base}.source_tree", spec.source_tree),
        phone=_phone_rules(block.get("log"), f"{base}.log", spec.phone),
        ril_tags=ril_tags,
        bugreport=rules,
        ril_vendor=_ril_vendor(block.get("ril"), f"{base}.ril", ril_tags),
        spec=spec,
        protocol_tags=protocol_tags,
        components=components,
        protocols=protocols,
    )


def _others(node: dict, base_name: str) -> dict:
    """`platform.others`: 키는 설치된 기본 아닌 플랫폼, 값은 그 플랫폼 `block_keys`만 받는 블록. 내용까지 모두 검증한다."""
    others = _mapping_any(node.get("others"), "platform.others")
    for key, block in others.items():
        at = f"platform.others.{key}"
        if key == base_name:
            raise _err(at, "기본 플랫폼(platform.name)의 상수는 platform: 블록에 둔다.")
        spec = _spec_at(key, at)
        _build(spec, key, _mapping(block, at, spec.block_keys), at)
    return others


def load(defaults: dict | None, name: str | None = None, *, require_enabled: bool = True) -> PlatformProfile:
    """site-defaults dict(없으면 None)의 `platform:`을 검증해 `name`(없으면 기본 플랫폼)의 프로파일로 준다.

    오류는 `PlatformConfigError`. 기본 플랫폼의 상수는 `platform:` 블록, 그 밖은 `platform.others.<name>`이다.
    `platform.others`는 요청한 플랫폼과 상관없이 모두 검증한다.
    `require_enabled`(사용자 세션 흐름, 기본)면 `name`이 `enabled(defaults)`에 있어야 한다. 이슈 DB에 고정된 도구
    (db_regress·db_lint·`parse_logcat --rules`, 17-platforms K6)는 False로 불러 DB가 선언한 플랫폼이 설치돼 있기만 하면 쓴다."""
    node = _block(defaults)
    base_name = node.get("name", DEFAULT_NAME)
    base_spec = _spec_at(base_name, "platform.name")
    _mapping(node, "platform", ("name",) + base_spec.block_keys + ("enabled", "others", "detect"))
    on = enabled(defaults)
    detect_rules(defaults)
    others = _others(node, base_name)
    name = base_name if name is None else name
    if require_enabled and name not in on:
        raise PlatformConfigError(f"플랫폼 '{name}'이(가) 켜져 있지 않습니다 (platform.enabled: {', '.join(on)}).")
    if name == base_name:
        return _build(base_spec, name, node, "platform")
    spec = get(name)
    base = f"platform.others.{name}"
    return _build(spec, name, _mapping(others.get(name), base, spec.block_keys), base)


def backend_name(defaults: dict | None, name: str | None = None) -> str:
    """플랫폼의 파서 백엔드 이름. 모든 플랫폼이 같은 규칙이다: 지정값이 있으면 그것, 없으면 `SPEC.default_backend`.
    지정값은 기본 플랫폼이면 `parser.backend`, 그 밖은 `parser.by_platform.<name>`. 이름 검증은 `parser_backends.load`.
    `parser.by_platform`은 매핑이어야 하고 키는 설치된 기본 아닌 플랫폼이어야 한다(아니면 `PlatformConfigError`)."""
    parser = (defaults or {}).get("parser") or {}
    base_name = default_name(defaults)
    by = cfg_mapping(parser.get("by_platform"), "parser.by_platform")
    for key in by:
        if key == base_name:
            raise _err(f"parser.by_platform.{key}", "기본 플랫폼의 백엔드는 parser.backend에 둔다.")
        _spec_at(key, f"parser.by_platform.{key}")
    name = base_name if name is None else name
    chosen = parser.get("backend") if name == base_name else by.get(name)
    return chosen if chosen else get(name).default_backend


DETECT_KEYS = ("tracker_field",)


def detect_rules(defaults: dict | None) -> dict | None:
    """site-defaults `platform.detect.tracker_field {path, values}`(17-platforms §11-4, 기본 꺼짐, TODO(SITE:S28·S32)):
    트래커 필드 값 → 켠 플랫폼 이름. 없으면 None. `path`는 jira_fields field_map 경로 표기(비지 않은 문자열),
    `values`는 `{트래커 값: 플랫폼}`(값은 `enabled` 안 이름). 플랫폼 선택 규칙이라 사용자 config로는 바꿀 수 없다(K7).
    오류는 `PlatformConfigError`(호출자 종료 코드 2)."""
    node = _block(defaults)
    if node.get("detect") is None:
        return None
    detect = _mapping(node["detect"], "platform.detect", DETECT_KEYS)
    if detect.get("tracker_field") is None:
        return None
    at = "platform.detect.tracker_field"
    field = _mapping(detect["tracker_field"], at, ("path", "values"))
    path = field.get("path")
    if not isinstance(path, str) or not path.strip():
        raise _err(f"{at}.path", "비어 있지 않은 문자열이어야 합니다.")
    values = _mapping_any(field.get("values"), f"{at}.values")
    if not values:
        raise _err(f"{at}.values", "트래커 값 → 플랫폼 매핑이 1개 이상 있어야 합니다.")
    on = enabled(defaults)
    out = {}
    for key, name in values.items():
        if not isinstance(key, (str, int)) or isinstance(key, bool) or str(key) == "":
            raise _err(f"{at}.values", f"트래커 값은 비어 있지 않은 문자열이어야 합니다: {key!r}")
        if name not in on:
            raise _err(f"{at}.values.{key}", f"켠 플랫폼 이름이어야 합니다 (platform.enabled: {', '.join(on)}): {name!r}")
        out[str(key)] = name
    return {"path": path, "values": out}


def select(defaults: dict | None, cli: str | None = None, user: str | None = None) -> str:
    """사용자 세션 흐름의 플랫폼 선택(17-platforms K3): `--platform`(cli) > 환경변수 `TT_PLATFORM` > 사용자 config
    `platform`(user) > site-defaults `platform.name` > `DEFAULT_NAME`. 고른 이름은 `platform.enabled`에 있어야 하고
    불러올 수 있어야 한다(아니면 `PlatformConfigError`, 호출자가 종료 코드 2)."""
    for where, value in (("--platform", cli), (ENV, os.environ.get(ENV)), ("사용자 config platform", user)):
        if value:
            name, source = value, where
            break
    else:
        name, source = default_name(defaults), "site-defaults platform.name"
    try:
        get(name)
    except PlatformConfigError as exc:
        raise PlatformConfigError(f"{source}: {exc}") from exc
    on = enabled(defaults)
    if name not in on:
        raise PlatformConfigError(f"{source}: 플랫폼 '{name}'이(가) 켜져 있지 않습니다 (platform.enabled: {', '.join(on)}).")
    return name


def known_raw_line_finders() -> tuple[list[tuple], list[tuple[str, Exception]]]:
    """설치된 플랫폼 **전부**(`known()`, 켠 것과 무관)의 `(name, raw_line, find_raw, sniff_line | None)`과
    불러오지 못한 플랫폼 `(name, 예외)` 목록. 원문 로그 차단(guard 규칙 10·issue_post fill 검사)용 — 판별은 넓을수록
    안전하므로 설정(`platform.enabled`)을 보지 않고, 플랫폼마다 따로 불러와 하나가 깨져도 나머지는 쓴다."""
    finders, errors = [], []
    for name in known():
        try:
            spec = get(name)
            finders.append((name, spec.log.raw_line, spec.log.find_raw, spec.capture.sniff_line if spec.capture else None))
        except Exception as exc:  # noqa: BLE001 — 하위 의존성 누락·SPEC 오류 모두 그 플랫폼만 뺀다
            errors.append((name, exc))
    return finders, errors


def raw_line_finders(defaults: dict | None) -> list[tuple]:
    """켠 플랫폼마다 `(raw_line, find_raw, sniff_line | None)`. 원문 로그 판별(guard 규칙 10·issue_post fill 검사)은 합집합으로 본다."""
    out = []
    for name in enabled(defaults):
        spec = get(name)
        out.append((spec.log.raw_line, spec.log.find_raw, spec.capture.sniff_line if spec.capture else None))
    return out
