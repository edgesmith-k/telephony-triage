"""플랫폼 레지스트리 (RF-3, 17-platforms 설계 §2). 핵심(common·매처·db_*)은 플랫폼을 모른다.

플랫폼 하나 = `platforms/<name>/` 패키지 하나와 그 `SPEC: base.PlatformSpec`이다. 이 모듈은 플랫폼 이름을
모른다 — 이름으로 동적 import한다(`parser_backends.load`와 같은 방식, 이름은 `NAME_RE`). 기본 이름(`DEFAULT_NAME`)은
site-defaults에 `platform.name`이 없을 때만 쓴다.

- `get(name)`: 계약 `SPEC`. `known()`: 설치된 플랫폼 이름. `label(name)`: 출력 라벨.
- `enabled(defaults)`: site-defaults `platform.enabled`(이 설치에서 켠 플랫폼, 없으면 `[platform.name]`).
- `load(defaults, name=None)`: `site-defaults.yaml`의 `platform:` 블록(경로·태그·섹션 헤더 상수, RF-4,
  `02-config.md`)을 검증해 `PlatformProfile`로 준다. 기본 플랫폼은 `platform:` 블록 자체, 그 밖 플랫폼은
  `platform.others.<name>` 블록이다. 받는 상수 키는 `SPEC.block_keys`다.
- `backend_name(defaults, name)`: 그 플랫폼의 파서 백엔드 이름. `raw_line_finders(defaults)`: 켠 플랫폼의 원문 줄 판별.

파일 I/O도 전역 상태도 없다(불변 `SPEC` 캐시만) — 호출한 쪽이 값을 들고 다니며(`ParserBackend.configure`,
`code_roots` 인자 등) 같은 프로세스에서 다른 설정으로 여러 번 불러도 서로 섞이지 않는다. 생략한 키는 `SPEC`의
기본값이고 그때 출력은 이전과 같다. 사용자 config로는 바꿀 수 없다 (`userconfig`를 거치지 않는다).
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from platforms.base import (  # noqa: F401  (계약 타입을 `platforms.X`로도 쓴다)
    DEFAULT_LINK_MS,
    CaptureSpec,
    LogFormat,
    PairProtocol,
    PhoneIdRules,
    PlatformSpec,
    SourceTree,
    VendorRules,
)

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DEFAULT_NAME = "android"
_NOT_PLATFORMS = {"base"}
_FILE = "site-defaults.yaml"
_SPECS: dict[str, PlatformSpec] = {}


class PlatformConfigError(Exception):
    """`platform:` 블록이 잘못됐거나 플랫폼을 불러올 수 없다. 메시지에 키 경로가 들어 있다."""


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    source_tree: SourceTree
    phone: PhoneIdRules
    ril_tags: frozenset
    bugreport: object | None                   # `SPEC.capture.default_rules` 형식 (capture 없는 플랫폼은 None)
    ril_vendor: VendorRules | None = None      # 선택 `platform.ril.vendor`. None이면 출력이 이전과 같다
    spec: PlatformSpec | None = None           # 레지스트리가 항상 채운다


# -- 레지스트리 --------------------------------------------------------------------


def known() -> list[str]:
    """설치된 플랫폼 이름(`platforms/` 아래 패키지, 정렬). 메시지 "지원 플랫폼: …"에 쓴다."""
    return sorted(
        info.name for info in pkgutil.iter_modules(__path__)
        if info.ispkg and info.name not in _NOT_PLATFORMS and NAME_RE.match(info.name)
    )


def _unsupported(name) -> str:
    return f"지원 플랫폼: {', '.join(known())} ({name!r})"


def get(name: str) -> PlatformSpec:
    """이름 → `SPEC`. 이름 검증 → `platforms.<name>` 패키지 import → `SPEC` 타입·이름 확인. 오류는 `PlatformConfigError`."""
    if not isinstance(name, str) or not NAME_RE.match(name) or name in _NOT_PLATFORMS:
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


def _err(path: str, why: str) -> PlatformConfigError:
    return PlatformConfigError(f"{_FILE} {path}: {why}")


def _mapping(value, path: str, allowed: tuple[str, ...]) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _err(path, "매핑이어야 합니다.")
    for key in value:
        if key not in allowed:
            raise _err(f"{path}.{key}", f"알 수 없는 키입니다 (허용: {', '.join(allowed)}).")
    return value


def _mapping_any(value, path: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _err(path, "매핑이어야 합니다.")
    return value


def _list(value, path: str, *, non_empty: bool) -> list:
    if not isinstance(value, list):
        raise _err(path, "목록이어야 합니다.")
    if non_empty and not value:
        raise _err(path, "비어 있으면 안 됩니다.")
    return value


def _rel_path(value, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _err(path, "비어 있지 않은 문자열이어야 합니다.")
    if value.startswith(("/", "\\")) or PureWindowsPath(value).drive:
        raise _err(path, f"루트 기준 상대 경로여야 합니다: {value}")
    if ".." in PurePosixPath(value).parts or ".." in PureWindowsPath(value).parts:
        raise _err(path, f"'..'를 쓸 수 없습니다: {value}")
    return value


def _compile(value, path: str, flags: int = 0, *, groups: int = 1) -> re.Pattern:
    if not isinstance(value, str) or not value:
        raise _err(path, "비어 있지 않은 정규식 문자열이어야 합니다.")
    try:
        pattern = re.compile(value, flags)
    except re.error as exc:
        raise _err(path, f"정규식 오류: {exc}") from exc
    if pattern.groups < groups:
        raise _err(path, "캡처 그룹이 하나 이상 있어야 합니다 (그룹 1 = 값).")
    return pattern


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


def _bugreport(raw, base: str, rules):
    """묶음 입력 블록(`bugreport`). `rules`(`SPEC.capture.default_rules`)를 덮어쓴 복사본을 준다."""
    node = _mapping(raw, base, ("wanted_buffers", "section_regex", "boundary_regex"))
    section, boundary, wanted = rules.section_re, rules.boundary_re, rules.wanted_buffers
    if "wanted_buffers" in node:
        path = f"{base}.wanted_buffers"
        items = _list(node["wanted_buffers"], path, non_empty=True)
        for i, name in enumerate(items):
            if not isinstance(name, str) or not re.fullmatch(r"[a-z]+", name):
                raise _err(f"{path}[{i}]", f"소문자 영문 버퍼 이름이어야 합니다: {name!r}")
        if len(set(items)) != len(items):
            raise _err(path, "중복이 있습니다.")
        wanted = tuple(items)
    if "section_regex" in node:
        path = f"{base}.section_regex"
        section = _compile(node["section_regex"], path, groups=0)
        if "cmd" not in section.groupindex:
            raise _err(path, "이름 그룹 (?P<cmd>...)가 필요합니다.")
    if "boundary_regex" in node:
        boundary = _compile(node["boundary_regex"], f"{base}.boundary_regex", groups=0)
    return dataclasses.replace(rules, section_re=section, boundary_re=boundary, wanted_buffers=wanted)


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


def default(name: str = DEFAULT_NAME) -> PlatformProfile:
    """코드 기본값 프로파일. 패턴은 `SPEC`의 객체 그대로다."""
    spec = get(name)
    return PlatformProfile(
        name=name,
        source_tree=spec.source_tree,
        phone=spec.phone,
        ril_tags=_default_ril_tags(spec),
        bugreport=spec.capture.default_rules if spec.capture else None,
        spec=spec,
    )


def load(defaults: dict | None, name: str | None = None) -> PlatformProfile:
    """site-defaults dict(없으면 None)의 `platform:`을 검증해 `name`(없으면 기본 플랫폼)의 프로파일로 준다.

    오류는 `PlatformConfigError`. 기본 플랫폼의 상수는 `platform:` 블록, 그 밖은 `platform.others.<name>`이다.
    `name`은 `enabled(defaults)`에 있어야 한다."""
    node = _block(defaults)
    base_name = node.get("name", DEFAULT_NAME)
    base_spec = _spec_at(base_name, "platform.name")
    _mapping(node, "platform", ("name",) + base_spec.block_keys + ("enabled", "others"))
    on = enabled(defaults)
    others = _mapping_any(node.get("others"), "platform.others")
    for key in others:
        if key == base_name or key not in on:
            raise _err(f"platform.others.{key}", "platform.enabled에 있는 기본 아닌 플랫폼이어야 합니다.")
    name = base_name if name is None else name
    if name not in on:
        raise PlatformConfigError(f"플랫폼 '{name}'이(가) 켜져 있지 않습니다 (platform.enabled: {', '.join(on)}).")
    if name == base_name:
        spec, block, base = base_spec, node, "platform"
    else:
        spec, base = get(name), f"platform.others.{name}"
        block = _mapping(others.get(name), base, spec.block_keys)
    ril_tags = _ril_tags(block.get("ril"), f"{base}.ril", _default_ril_tags(spec))
    return PlatformProfile(
        name=name,
        source_tree=_source_tree(block.get("source_tree"), f"{base}.source_tree", spec.source_tree),
        phone=_phone_rules(block.get("log"), f"{base}.log", spec.phone),
        ril_tags=ril_tags,
        bugreport=_bugreport(block.get("bugreport"), f"{base}.bugreport", spec.capture.default_rules) if spec.capture else None,
        ril_vendor=_ril_vendor(block.get("ril"), f"{base}.ril", ril_tags),
        spec=spec,
    )


def backend_name(defaults: dict | None, name: str | None = None):
    """플랫폼의 파서 백엔드 이름. 기본 플랫폼은 `parser.backend`(값 그대로, 검증은 `parser_backends.load`),
    그 밖은 `parser.by_platform.<name>`, 없으면 `SPEC.default_backend`."""
    parser = (defaults or {}).get("parser") or {}
    if name is None or name == default_name(defaults):
        return parser.get("backend")
    by = parser.get("by_platform")
    if isinstance(by, dict) and by.get(name):
        return by[name]
    return get(name).default_backend


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
