"""플랫폼별 코드 (RF-3). 현재는 `android/`뿐이다. 핵심(common·매처·db_*)은 플랫폼을 모른다.

`load(defaults)`가 `site-defaults.yaml`의 `platform:` 블록(경로·태그·섹션 헤더 상수, RF-4,
`02-config.md`)을 검증해 `PlatformProfile`로 준다. 파일 I/O도 전역 상태도 없다 — 호출한 쪽이
값을 들고 다니며(`ParserBackend.configure`, `code_roots` 인자 등) 같은 프로세스에서 다른 설정으로
여러 번 불러도 서로 섞이지 않는다. 생략한 키는 코드 기본값(`platforms/android/*`)이고 그때 출력은 이전과 같다.
사용자 config로는 바꿀 수 없다 (`userconfig`를 거치지 않는다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

from platforms.android import REQUIRED_DIRS, VERSION_SOURCES
from platforms.android import bugreport, logcat, ril

SUPPORTED = ("android",)
_FILE = "site-defaults.yaml"


class PlatformConfigError(Exception):
    """`platform:` 블록이 잘못됐다. 메시지에 키 경로가 들어 있다."""


@dataclass(frozen=True)
class SourceTree:
    required_dirs: tuple[str, ...]
    version_sources: tuple[tuple[str, re.Pattern], ...]


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    source_tree: SourceTree
    phone: logcat.PhoneIdRules
    ril_tags: frozenset
    bugreport: bugreport.BugreportRules


def default(name: str = "android") -> PlatformProfile:
    """코드 기본값 프로파일. 패턴은 기존 모듈 상수 객체 그대로다."""
    if name not in SUPPORTED:
        raise PlatformConfigError(f"지원 플랫폼: {', '.join(SUPPORTED)} ({name!r})")
    return PlatformProfile(
        name=name,
        source_tree=SourceTree(tuple(REQUIRED_DIRS), tuple(VERSION_SOURCES)),
        phone=logcat.DEFAULT_PHONE_RULES,
        ril_tags=frozenset(ril.RIL_TAGS),
        bugreport=bugreport.DEFAULT_RULES,
    )


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


def _source_tree(raw, base: str) -> SourceTree:
    node = _mapping(raw, base, ("required_dirs", "version_sources"))
    tree = default().source_tree
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


def _phone_rules(raw, base: str) -> logcat.PhoneIdRules:
    node = _mapping(raw, base, ("phone_id",))
    rules = logcat.DEFAULT_PHONE_RULES
    if "phone_id" not in node:
        return rules
    at = f"{base}.phone_id"
    spec = _mapping(node["phone_id"], at, ("tag", "msg_prefix", "msg_suffix"))
    fields = {"tag": rules.tag, "msg_prefix": rules.prefix, "msg_suffix": rules.suffix}
    for key in spec:
        path = f"{at}.{key}"
        fields[key] = tuple(_compile(p, f"{path}[{i}]") for i, p in enumerate(_list(spec[key], path, non_empty=False)))
    return logcat.PhoneIdRules(fields["tag"], fields["msg_prefix"], fields["msg_suffix"])


def _ril_tags(raw, base: str) -> frozenset:
    node = _mapping(raw, base, ("tags",))
    if "tags" not in node:
        return frozenset(ril.RIL_TAGS)
    path = f"{base}.tags"
    tags = []
    for i, tag in enumerate(_list(node["tags"], path, non_empty=False)):
        if not isinstance(tag, str) or not tag.strip():
            raise _err(f"{path}[{i}]", "비어 있지 않은 문자열이어야 합니다.")
        tags.append(tag)
    return frozenset(tags)


def _bugreport(raw, base: str) -> bugreport.BugreportRules:
    node = _mapping(raw, base, ("wanted_buffers", "section_regex", "boundary_regex"))
    rules = bugreport.DEFAULT_RULES
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
    return bugreport.BugreportRules(section, boundary, wanted)


def load(defaults: dict | None) -> PlatformProfile:
    """site-defaults dict(없으면 None)의 `platform:`을 검증해 프로파일로 준다. 오류는 `PlatformConfigError`."""
    raw = (defaults or {}).get("platform")
    node = _mapping(raw, "platform", ("name", "source_tree", "log", "ril", "bugreport"))
    name = node.get("name", "android")
    if name not in SUPPORTED:
        raise _err("platform.name", f"지원 플랫폼: {', '.join(SUPPORTED)} ({name!r})")
    return PlatformProfile(
        name=name,
        source_tree=_source_tree(node.get("source_tree"), "platform.source_tree"),
        phone=_phone_rules(node.get("log"), "platform.log"),
        ril_tags=_ril_tags(node.get("ril"), "platform.ril"),
        bugreport=_bugreport(node.get("bugreport"), "platform.bugreport"),
    )
