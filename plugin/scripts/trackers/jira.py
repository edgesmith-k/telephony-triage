"""Jira 트래커 (트래커 범용화 설계 §3-2 jira 열). 이전 동작 그대로다 — 값은 옮기기 전 위치를 주석에 적는다.

TODO(SITE:S16) 사내 Jira 키 형식. TODO(SITE:S23) 사내 Jira MCP 코멘트 도구의 인자 이름.
"""

from __future__ import annotations

import re
from types import MappingProxyType

from trackers.base import TrackerSpec

# 경로 안전 키 형식 (옛 `issuepost.KEY_SAFE_RE`). DB `tracker.key_regex`보다 먼저 본다(작업 디렉토리 이름이 된다)
SAFE_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*-\d+$")
DEFAULT_KEY_REGEX = r"[A-Z][A-Z0-9]+-\d+"     # 옛 jira_fields·issue_post·db_search·dbadd.applier 4곳 중복 기본값


def _safe(value) -> str | None:
    return value if isinstance(value, str) and SAFE_KEY_RE.fullmatch(value) else None


def parse_key(text: str) -> str | None:
    """Jira 키는 입력 그대로가 작업 키다(경로 안전 형식일 때만)."""
    return _safe(text)


def display(key: str) -> str:
    return key


def link(base_url: str, key: str) -> str:
    return f"{base_url}{key}"


def spec_problems(raw: dict) -> list[str]:
    """`key_arg`(이슈 키 인자 이름)·`body_arg`는 서로 다른 비어 있지 않은 문자열, `extra_args`는 둘과 겹치지 않는 객체."""
    key_arg, body_arg = raw.get("key_arg"), raw.get("body_arg")
    extra = raw.get("extra_args") if raw.get("extra_args") is not None else {}
    if not (isinstance(key_arg, str) and key_arg and isinstance(body_arg, str) and body_arg) or key_arg == body_arg:
        return ["add_comment.key_arg·body_arg는 서로 다른 비어 있지 않은 문자열이다"]
    if not isinstance(extra, dict) or {key_arg, body_arg} & set(extra):
        return ["add_comment.extra_args는 객체이고 key_arg·body_arg와 겹치지 않는다"]
    return []


def key_args(spec: dict, key: str) -> dict:
    return {spec["key_arg"]: key}


def key_from_args(spec: dict, tool_input) -> str | None:
    return _safe(tool_input.get(spec["key_arg"])) if isinstance(tool_input, dict) else None


def arg_names(spec: dict) -> set:
    return {spec["key_arg"]}


def key_arg_id(spec: dict) -> str:
    return spec["key_arg"]


def read_action(tool_input, mapped: set) -> str | None:
    """이 도구가 매핑된 논리 동작. 둘 다면 get_issue."""
    return next((k for k in ("get_issue", "get_comments") if k in mapped), None)


def key_from_read(data, tool_input, kre: re.Pattern) -> str | None:
    """응답의 `key`·`issue.key`, 다음으로 도구 입력의 문자열 값 중 키 정규식에 맞고 경로 안전한 첫 값."""
    candidates = []
    if isinstance(data, dict):
        candidates += [data.get("key"), (data.get("issue") or {}).get("key") if isinstance(data.get("issue"), dict) else None]
    candidates += [v for v in (tool_input if isinstance(tool_input, dict) else {}).values() if isinstance(v, str)]
    return next((str(c) for c in candidates if c and kre.fullmatch(str(c)) and SAFE_KEY_RE.fullmatch(str(c))), None)


def read_args(action: str, key: str) -> dict | None:
    return None      # Jira 읽기 도구 인자는 스킬이 매핑에서 정한다(needs_input 출력 불변)


def classify_extra(tool: str, actions: set) -> set:
    return actions


SPEC = TrackerSpec(
    name="jira",
    label="Jira",
    safe_key_re=SAFE_KEY_RE,
    default_key_regex=DEFAULT_KEY_REGEX,
    server_words=("jira", "atlassian"),
    formats=("jira-wiki", "markdown"),
    default_format="jira-wiki",
    text_defaults=MappingProxyType({                  # 옛 jira_fields.TEXT_DEFAULTS
        "summary": ("fields.summary", "summary"),
        "description": ("fields.description", "description"),
        "comments": ("comments[].body", "fields.comment.comments[].body"),
    }),
    components_default="fields.components[].name",
    parse_key=parse_key,
    display=display,
    link=link,
    spec_problems=spec_problems,
    key_args=key_args,
    key_from_args=key_from_args,
    arg_names=arg_names,
    key_arg_id=key_arg_id,
    read_action=read_action,
    key_from_read=key_from_read,
    read_args=read_args,
    classify_extra=classify_extra,
)
