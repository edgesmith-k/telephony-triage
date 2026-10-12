"""GitHub Issues 트래커 (트래커 범용화 설계 §3-2 github 열·§3-4 작업 키).

작업 키(작업 디렉토리·`issue/<KEY>` 브랜치·피드백 파일·DB 기록 파일 이름)는 `<owner>.<repo>-<N>`이고 전부 소문자다.
- GitHub owner에는 `.`가 올 수 없으므로 분해가 유일하다: 끝의 `-<N>`을 떼고 첫 `.`에서 나눈다.
- `/`·`#`·공백이 없고 `..`를 막아(`(?!.*\\.\\.)`) 디렉토리·파일 이름·git ref로 쓸 수 있다. repo 이름이 `.`로 시작하면(`.github`)
  지원하지 않는다.
- Jira 작업 키에는 `.`가 없으므로 두 형식은 겹치지 않는다.
- owner·repo는 대소문자를 구별하지 않으므로 소문자로 정규화한다(대소문자만 다른 디렉토리 중복 방지).

쓰기 도구(`add_issue_comment`)의 키 인자는 고정 `owner, repo, issue_number`(정수)다 — 설정 `key_arg`는 두지 않는다.
`key_from_args`는 입력을 검사해 작업 키를 만든 뒤 `key_args`로 다시 만들어 입력과 같을 때만(왕복) 키를 낸다. spec은 보지 않는다
(그래서 `key_from_read`는 spec 없이 `key_from_args({}, 입력)`을 부른다).

TODO(SITE:S30) 사내 GitHub(GHE) MCP 등록·도구 이름·인자·응답 형식. TODO(SITE:S31) 구조화 필드 위치(지금은 field_map이 비어
모델·SW·버전·발생 시각을 사용자에게 묻는다).
"""

from __future__ import annotations

import re
from types import MappingProxyType

from trackers.base import TrackerSpec

SAFE_KEY_RE = re.compile(r"^(?!.*\.\.)[a-z0-9][a-z0-9-]{0,38}\.[a-z0-9_][a-z0-9_.-]{0,99}-[1-9][0-9]{0,9}$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
REPO_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}$")
NUMBER_RE = re.compile(r"^[1-9][0-9]{0,9}$")
KEY_ARGS = ("owner", "repo", "issue_number")
# 사용자 입력: `owner/repo#N`, `http(s)://<host>/owner/repo/issues/N`(끝 `/`·`?…`·`#…` 허용)
_SHORT_RE = re.compile(r"^(?P<owner>[^/#\s]+)/(?P<repo>[^/#\s]+)#(?P<n>[0-9]+)$")
_URL_RE = re.compile(r"^https?://[^/\s]+/(?P<owner>[^/#?\s]+)/(?P<repo>[^/#?\s]+)/issues/(?P<n>[0-9]+)/?(?:[?#]\S*)?$")
METHODS = {"get": "get_issue", "get_comments": "get_comments"}   # issue_read method → 논리 동작


def _make(owner, repo, number) -> str | None:
    """검사한 owner·repo·번호(문자열) → 소문자 작업 키, 아니면 None."""
    if not (isinstance(owner, str) and OWNER_RE.fullmatch(owner)):
        return None
    if not (isinstance(repo, str) and REPO_RE.fullmatch(repo)) or ".." in repo:
        return None
    if not (isinstance(number, str) and NUMBER_RE.fullmatch(number)):
        return None
    key = f"{owner}.{repo}-{number}".lower()
    return key if SAFE_KEY_RE.fullmatch(key) else None


def split_key(key: str) -> tuple[str, str, int]:
    """작업 키 → (owner, repo, N). 작업 키 형식이 아니면 ValueError."""
    if not (isinstance(key, str) and SAFE_KEY_RE.fullmatch(key)):
        raise ValueError(f"GitHub 작업 키 형식이 아니다: {key!r}")
    head, _, number = key.rpartition("-")
    owner, _, repo = head.partition(".")
    return owner, repo, int(number)


def parse_key(text: str) -> str | None:
    """작업 키(대소문자 무관), `owner/repo#N`, 이슈 URL → 소문자 작업 키. 아니면 None."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    hit = _SHORT_RE.fullmatch(text) or _URL_RE.fullmatch(text)
    if hit:
        return _make(hit.group("owner"), hit.group("repo"), hit.group("n"))
    low = text.lower()
    return low if SAFE_KEY_RE.fullmatch(low) else None


def display(key: str) -> str:
    """`owner/repo#N`. 작업 키 형식이 아니면 그대로(표시만 하는 값 — db_lint가 기록 키를 따로 검사한다)."""
    try:
        owner, repo, number = split_key(key)
    except ValueError:
        return str(key)
    return f"{owner}/{repo}#{number}"


def link(base_url: str, key: str) -> str:
    """`<base_url><owner>/<repo>/issues/<N>`. 작업 키 형식이 아니면 `<base_url><key>`(Jira와 같은 모양)."""
    try:
        owner, repo, number = split_key(key)
    except ValueError:
        return f"{base_url}{key}"
    return f"{base_url}{owner}/{repo}/issues/{number}"


def spec_problems(raw: dict) -> list[str]:
    """GitHub 전용 검사: 키 인자는 고정(`owner, repo, issue_number`)이라 `key_arg`를 두지 않고, `body_arg`가 키 인자와 겹치지
    않는다. `body_arg`·`extra_args` 공통 검사(extra와 키 인자 겹침 포함)는 `common/issuepost.spec_check`가 한다."""
    if raw.get("key_arg") not in (None, ""):
        return ["add_comment.key_arg는 github 트래커에서 두지 않는다(키 인자는 owner·repo·issue_number 고정)"]
    if raw.get("body_arg") in KEY_ARGS:
        return ["add_comment.body_arg가 키 인자(owner·repo·issue_number)와 겹친다"]
    return []


def key_args(spec: dict, key: str) -> dict:
    owner, repo, number = split_key(key)
    return {"owner": owner, "repo": repo, "issue_number": number}


def key_from_args(spec: dict, tool_input) -> str | None:
    """도구 입력의 owner·repo·issue_number(1 이상 정수, bool·문자열·실수 거부) → 작업 키. 왕복 검사(키 → 인자가 입력과
    소문자 비교로 같음)를 통과할 때만. spec은 보지 않는다."""
    if not isinstance(tool_input, dict):
        return None
    owner, repo, number = (tool_input.get(k) for k in KEY_ARGS)
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        return None
    key = _make(owner, repo, str(number))
    if key is None:
        return None
    back = key_args(spec, key)
    same = back["owner"] == owner.lower() and back["repo"] == repo.lower() and back["issue_number"] == number
    return key if same else None


def arg_names(spec: dict) -> set:
    return set(KEY_ARGS)


def key_arg_id(spec: dict) -> str:
    return ",".join(KEY_ARGS)


def read_action(tool_input, mapped: set) -> str:
    """`issue_read`의 `method`: get → get_issue, get_comments → get_comments, 그 밖(get_labels 등)은 unsupported."""
    method = tool_input.get("method") if isinstance(tool_input, dict) else None
    return METHODS.get(method, "unsupported") if isinstance(method, str) else "unsupported"


def key_from_read(data, tool_input, kre: re.Pattern) -> str | None:
    """읽기 응답이 아니라 도구 입력(owner·repo·issue_number)에서 작업 키를 만들고 키 정규식으로 검사한다."""
    key = key_from_args({}, tool_input)
    return key if key is not None and kre.fullmatch(key) else None


def read_args(action: str, key: str) -> dict | None:
    """needs_input 안내: `issue_read` 인자."""
    method = next((m for m, a in METHODS.items() if a == action), None)
    return None if method is None else {"method": method, **key_args({}, key)}


def classify_extra(tool: str, actions: set) -> set:
    """`issue_read` 하나가 이슈와 코멘트를 모두 읽는다(method): get_issue 후보면 get_comments 후보에도 넣는다."""
    if str(tool).split("__")[-1].lower() == "issue_read" and "get_issue" in actions:
        return set(actions) | {"get_comments"}
    return actions


SPEC = TrackerSpec(
    name="github",
    label="GitHub",
    safe_key_re=SAFE_KEY_RE,
    default_key_regex=SAFE_KEY_RE.pattern[1:-1],
    server_words=(),            # "github"를 넣으면 설정되지 않은 모든 GitHub MCP 쓰기가 거부된다(설계 §4-3)
    formats=("markdown",),
    default_format="markdown",
    text_defaults=MappingProxyType({
        "summary": ("title",),
        "description": ("body",),
        "comments": ("comments[].body",),
    }),
    components_default="labels[].name",
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
    selftest_key="selftest.selftest-1",
)
