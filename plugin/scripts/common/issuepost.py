"""Jira 결과 게시(코멘트 1건)의 공용 규칙: 본문 정규화·해시, 형식 렌더러, 도구 설정·인자 매핑, 승인 대조
(07-workflow.md §Step 9, 08-safety.md §9 규칙 2).

guard.py(PreToolUse)·jira_bridge.py(PostToolUse)·issue_post.py가 같이 쓴다. guard가 import하므로 표준 라이브러리와
`mcptools`·`trackers`(표준 라이브러리만, 계층 규칙)만 쓴다(PyYAML 없음).

- 본문 중간 표현(`sections`)은 트래커 중립이다: `{"PROBLEM": [Item], "CAUSE": …, "NEXT ACTION": …, "ANALYSIS": …}`,
  `Item = {"kind": "line"|"code", "text": str|[str]}`. 형식 문자열은 `RENDERERS`가 만든다(새 형식은 함수만 더한다).
- 도구 설정 출처는 `write_spec`(경로 `SPEC_PATH`) 한 곳이고, 인자 매핑(`call_arguments`)과 승인 대조(`check_call`)는
  spec(`kind`·`key_arg`·`body_arg`·`extra_args`)만 본다. 키 인자 모양(이름·검사·작업 키 복원)과 본문 형식 목록은 트래커
  어댑터(`trackers.get(spec["kind"])`의 `key_args`·`key_from_args`·`arg_names`·`key_arg_id`·`spec_problems`·`formats`)가 정한다.
- 승인 장치(본문 sha256·이슈 키·도구·30분 만료·1회용, 그리고 guard의 ask)는 설정으로 끌 수 없다. 설정이 바꿀 수 있는
  것은 "어느 도구가 코멘트 도구인가"뿐이고 `write_spec` 조건으로 좁힌다.

TODO(SITE:S23) 사내 Jira MCP 코멘트 도구의 이름·인자·본문 형식(wiki/markdown/ADF)·길이 상한·응답 형식을 확인하고
아래 단어·길이 상수를 맞춘다.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import trackers

from . import mcptools

SPEC_PATH = ("tracker", "write_tools", "add_comment")
SPEC_KEYS = {"tool", "key_arg", "body_arg", "extra_args", "format"}
WRITE_TOOL_KINDS = {"add_comment"}          # write_tools에 허용하는 키는 이것 하나다
APPROVAL_TTL_MIN = 30                       # 승인 유효 시간(분). 설정 키는 두지 않는다
# 도구 이름 단어 조건: 코멘트 단어가 있어야 하고 금지 단어가 없어야 한다 (TODO(SITE:S23))
COMMENT_WORDS = {"comment", "comments", "note", "notes"}
FORBIDDEN_WORDS = {"delete", "remove", "transition", "assign", "update", "edit", "attach", "upload", "link", "move",
                   "close", "reopen", "worklog", "set", "resolve"}

SECTIONS = ("PROBLEM", "CAUSE", "NEXT ACTION", "ANALYSIS")
SECTION_MAX = {"PROBLEM": 600, "CAUSE": 1000, "NEXT ACTION": 800, "ANALYSIS": 1600}
BODY_MAX = 4000

POST_FILE = "post.md"
FILL_FILE = "post.fill.json"
RENDER_FILE = "post.render.json"
APPROVED_FILE = "post.approved.json"
RESULT_FILE = "post.result.json"


# -- 정규화·해시 -----------------------------------------------------------------------------


def normalize_body(text: str) -> str:
    """NFC, CRLF/CR→LF, 줄 끝 공백·탭 제거, 앞뒤 빈 줄 제거. 승인 해시와 게시 본문 대조의 기준이다."""
    text = unicodedata.normalize("NFC", str(text)).replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip(" \t") for ln in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def body_sha256(text: str) -> str:
    return sha256(normalize_body(text).encode("utf-8")).hexdigest()


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value) -> datetime:
    dt = datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def expires(approved_at: datetime) -> datetime:
    return approved_at + timedelta(minutes=APPROVAL_TTL_MIN)


# -- 형식 렌더러 -----------------------------------------------------------------------------

_WIKI_SPECIAL = re.compile(r"([\\{}\[\]|!])")
_WIKI_LINE_HEAD = re.compile(r"^(\s*)([*#-]|h[1-6]\.|bq\.)", re.M)
_NOFORMAT = re.compile(r"(?i)\{noformat[^}]*\}")
_MD_LINE_HEAD = re.compile(r"^(\s*)([#>*+\-=|<]|\d+[.)])", re.M)
_MD_FENCES = ("```", "~~~")
_FENCE = "```"
# 한 줄로 접을 때 공백으로 바꾸는 글자: 줄바꿈·탭·제어 문자와 제로폭 문자(칸 머리 위조·숨은 마크업 방지)
_BREAKERS = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029\u200b-\u200f\u2060-\u2064\ufeff\u00ad]")


def one_line(text) -> str:
    """값 하나를 한 줄로: 줄바꿈·CR·탭·제로폭 문자 → 공백, 연속 공백 하나로. 줄 항목은 모두 이것을 거친다."""
    return " ".join(_BREAKERS.sub(" ", str(text)).split())


def _until_stable(text: str, func) -> str:
    """중첩 문자열(`{nof{noformat}ormat}`)이 지운 뒤 다시 생기지 않게 바뀌지 않을 때까지 반복한다."""
    while True:
        new = func(text)
        if new == text:
            return text
        text = new


def _strip_noformat(text: str) -> str:
    return _until_stable(str(text), lambda t: _NOFORMAT.sub("", t))


def _strip_fences(text: str) -> str:
    def once(t: str) -> str:
        for f in _MD_FENCES:
            t = t.replace(f, "")
        return t
    return _until_stable(str(text), once)


def _wiki_text(text: str) -> str:
    text = _strip_noformat(one_line(text))
    text = _WIKI_SPECIAL.sub(r"\\\1", text)
    return _WIKI_LINE_HEAD.sub(lambda m: m.group(1) + "\\" + m.group(2), text)


def _md_text(text: str) -> str:
    text = _strip_fences(one_line(text))
    return _MD_LINE_HEAD.sub(lambda m: m.group(1) + "\\" + m.group(2), text)


def render_jira_wiki(sections: dict, tail: str | None = None) -> str:
    out: list[str] = []
    for name in SECTIONS:
        out.append(f"h3. {name}")
        for item in sections.get(name) or []:
            if item["kind"] == "code":
                lines = [_strip_noformat(one_line(t)) for t in item["text"]]
                out += ["{noformat}", *lines, "{noformat}"]
            else:
                out.append("* " + _wiki_text(item["text"]))
        out.append("")
    if tail:
        out += ["----", "_" + _wiki_text(tail) + "_"]
    return normalize_body("\n".join(out))


def render_markdown(sections: dict, tail: str | None = None) -> str:
    out: list[str] = []
    for name in SECTIONS:
        out.append(f"### {name}")
        for item in sections.get(name) or []:
            if item["kind"] == "code":
                lines = [_strip_fences(one_line(t)) for t in item["text"]]
                out += [_FENCE, *lines, _FENCE]
            else:
                out.append("- " + _md_text(item["text"]))
        out.append("")
    if tail:
        out += ["---", "*" + _md_text(tail).replace("*", "") + "*"]
    return normalize_body("\n".join(out))


RENDERERS = {"jira-wiki": render_jira_wiki, "markdown": render_markdown}   # 트래커가 쓸 수 있는 형식은 `TrackerSpec.formats`


def section_text(items: list) -> str:
    """칸 길이 계산용 평문 (렌더러 기호 제외)."""
    parts = []
    for item in items or []:
        parts += [str(t) for t in item["text"]] if item["kind"] == "code" else [str(item["text"])]
    return "\n".join(parts)


# -- 도구 설정 -------------------------------------------------------------------------------


def spec_tracker(spec: dict) -> trackers.TrackerSpec:
    """검증된 코멘트 도구 spec(`spec_check` 결과, `kind` 필수)의 트래커 어댑터. 설정에서는 `trackers.of(cfg)`를 쓴다."""
    return trackers.get(spec["kind"])


def _get(cfg: dict, path: tuple):
    node = cfg
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def jira_prefixes(cfg: dict) -> set[str]:
    """Jira 서버 접두사 = `tracker.mcp_server` ∪ `tracker.tools` 도구 이름의 서버 (guard 규칙 2와 같은 집합)."""
    server = _get(cfg, ("tracker", "mcp_server"))
    tools = _get(cfg, ("tracker", "tools"))
    prefixes = {mcptools.full_name(str(server), "")} if server else set()
    prefixes |= {mcptools.server_prefix(v) for v in (tools.values() if isinstance(tools, dict) else [])
                 if mcptools.server_prefix(v)}
    return prefixes


def raw_tool(cfg: dict) -> str | None:
    """설정된 코멘트 도구의 정규화 전체 이름(유효성과 무관). 없으면 None."""
    tool = _get(cfg, SPEC_PATH + ("tool",))
    return mcptools.normalize(tool) if isinstance(tool, str) and tool.strip() else None


def spec_check(cfg: dict, prefixes: set[str] | None = None) -> tuple[dict | None, list[tuple[str, str]]]:
    """`tracker.write_tools.add_comment` → (spec 또는 None, 문제 [(warn|fail, 사유)]).
    설정이 없거나 `tool`이 비어 있으면 (None, []) — 게시 기능 꺼짐. 문제가 하나라도 있으면 spec은 None이다(무효).
    fail은 승인 생략 경로(도구가 read_tools에 있음)다."""
    prefixes = jira_prefixes(cfg) if prefixes is None else prefixes
    wt = _get(cfg, ("tracker", "write_tools"))
    try:
        tracker = trackers.of(cfg)
    except trackers.TrackerConfigError as exc:   # kind 오류: 게시 경로 전체가 무효(guard·bridge는 앞에서 모든 MCP를 막는다)
        return None, ([("warn", str(exc))] if wt not in (None, {}) else [])
    if wt in (None, {}):
        return None, []
    if not isinstance(wt, dict):
        return None, [("warn", "tracker.write_tools가 객체가 아니다")]
    problems: list[tuple[str, str]] = []
    extra_kinds = sorted(set(wt) - WRITE_TOOL_KINDS)
    if extra_kinds:
        problems.append(("warn", f"tracker.write_tools에는 add_comment만 둔다({', '.join(map(str, extra_kinds))} 불가)"))
    raw = wt.get("add_comment")
    if raw is None and not problems:
        return None, []
    if not isinstance(raw, dict):
        return None, problems + [("warn", "tracker.write_tools.add_comment가 객체가 아니다")]
    tool = raw.get("tool")
    if tool is None or tool == "":      # 도구를 비우면 꺼진다(사용자 config에서 끄는 방법, deep_merge라 {}로는 못 끈다)
        return None, problems
    if not (isinstance(tool, str) and tool.strip()):
        return None, problems + [("warn", "add_comment.tool이 문자열이 아니다")]
    unknown = sorted(set(raw) - SPEC_KEYS)
    if unknown:
        problems.append(("warn", f"add_comment에 모르는 키: {', '.join(map(str, unknown))}"))
    hit = mcptools.NAME_RE.match(tool)
    name = mcptools.normalize(tool)
    if not hit:
        problems.append(("warn", f"add_comment.tool이 전체 이름(mcp__<server>__<tool>)이 아니다: {tool}"))
    else:
        if mcptools.server_prefix(name) not in prefixes:
            problems.append(("warn", f"{tool}의 서버가 Jira 서버(tracker.mcp_server·tracker.tools)가 아니다"))
        words = set(mcptools._words(hit.group(2)))
        if not words & COMMENT_WORDS:
            problems.append(("warn", f"{tool} 이름에 comment·note 단어가 없다"))
        bad = sorted(words & FORBIDDEN_WORDS)
        if bad:
            problems.append(("warn", f"{tool} 이름에 금지 단어가 있다({', '.join(bad)})"))
    key_arg, body_arg = raw.get("key_arg"), raw.get("body_arg")
    extra = raw.get("extra_args") if raw.get("extra_args") is not None else {}
    key_problems = tracker.spec_problems(raw)          # 트래커 전용: 키 인자(jira는 key_arg 필수)
    if key_problems:
        problems += [("warn", why) for why in key_problems]
    elif not (isinstance(body_arg, str) and body_arg):  # 공통: 본문 인자, 고정 인자는 객체이고 키·본문 인자와 겹치지 않는다
        problems.append(("warn", "add_comment.key_arg·body_arg는 서로 다른 비어 있지 않은 문자열이다"))
    elif not isinstance(extra, dict) or ((tracker.arg_names(raw) | {body_arg}) & set(extra)):
        problems.append(("warn", "add_comment.extra_args는 객체이고 key_arg·body_arg와 겹치지 않는다"))
    fmt = raw.get("format") or tracker.default_format
    if fmt not in tracker.formats:
        problems.append(("warn", f"add_comment.format은 {'|'.join(tracker.formats)} 중 하나다: {fmt}"))
    read_tools = _get(cfg, ("tracker", "read_tools")) or []
    if isinstance(read_tools, list) and name in {mcptools.normalize(str(t)) for t in read_tools}:
        problems.insert(0, ("fail", f"{tool}이(가) tracker.read_tools에 있다(승인 생략 경로)"))
    if problems:
        return None, problems
    return {"tool": name, "key_arg": key_arg, "body_arg": body_arg, "extra_args": dict(extra), "format": fmt,
            "kind": tracker.name}, []


def write_spec(cfg: dict, prefixes: set[str] | None = None) -> tuple[dict | None, str | None]:
    """(spec 또는 None, 첫 문제 또는 None). 둘 다 None이면 설정 없음."""
    spec, problems = spec_check(cfg, prefixes)
    return spec, (problems[0][1] if problems else None)


def call_arguments(spec: dict, key: str, body: str) -> dict:
    """approve가 내는 MCP 도구 인자 (도구 인자 매핑은 이 함수와 `check_call`만 안다)."""
    return {**spec_tracker(spec).key_args(spec, key), spec["body_arg"]: normalize_body(body), **spec.get("extra_args", {})}


# -- 승인 기록 -------------------------------------------------------------------------------


def write_private_json(path: Path, data: dict) -> None:
    """권한 600 JSON 파일 (원자적 교체)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    """JSON 객체. 파일이 없으면 None, 손상이면 ValueError."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}이(가) 객체가 아니다")
    return data


def check_call(tool: str, tool_input, spec: dict, work_dir: Path | None, at: datetime | None = None) -> str | None:
    """코멘트 도구 호출을 승인 기록과 대조한다 → 문제 문자열 또는 None(승인과 일치). 승인 기록의 `key`·`tool`·`key_arg`·
    `kind`(트래커)가 지금 설정과 같아야 한다.
    본문은 정규화 sha256이 승인과 같고, 정규화 전 입력이 `post.md`와 글자 그대로 같아야 한다(LF/CRLF·끝 줄바꿈 하나만 허용).
    같은 본문의 posted 이력은 승인 기록의 `again: true`(render --again)일 때만 건너뛴다. 결과 불명(unknown)은 늘 거부.
    guard는 판정만 한다(파일을 쓰지 않는다). 1회용 표시(`used_at`)는 PostToolUse(jira_bridge)가 한다."""
    at = at or now()
    tracker = spec_tracker(spec)
    key_arg, body_arg, extra = tracker.key_arg_id(spec), spec["body_arg"], spec.get("extra_args") or {}
    if not isinstance(tool_input, dict):
        return "도구 입력이 객체가 아니다"
    unknown = sorted(set(tool_input) - (tracker.arg_names(spec) | {body_arg} | set(extra)))
    if unknown:
        return f"승인 범위 밖 인자: {', '.join(map(str, unknown))}"
    for k, v in extra.items():
        if tool_input.get(k) != v:
            return f"고정 인자 {k} 값이 설정과 다르다"
    key = tracker.key_from_args(spec, tool_input)
    if not isinstance(key, str) or not tracker.safe_key_re.fullmatch(key):
        return f"이슈 키 형식 불일치({key_arg})"
    body = tool_input.get(body_arg)
    if not isinstance(body, str) or not body.strip():
        return f"본문({body_arg})이 비어 있다"
    if work_dir is None:
        return "사용자 config 없음 — 승인 기록을 찾을 수 없다"
    job = Path(work_dir) / key
    try:
        record = read_json(job / APPROVED_FILE)
    except (OSError, ValueError) as exc:
        return f"승인 기록 손상({type(exc).__name__})"
    if record is None:
        return f"승인 기록 없음({key})"
    if record.get("schema") != 1:
        return "승인 기록 형식이 다르다(schema)"
    if record.get("key") != key:
        return f"승인한 이슈 키({record.get('key')})와 다르다"
    if record.get("tool") != mcptools.normalize(tool):
        return "승인한 도구와 다르다"
    if record.get("key_arg") != key_arg:
        return "승인 기록의 키 인자가 설정과 다르다"
    if record.get("kind") != spec["kind"]:
        return "승인 기록의 트래커(kind)가 설정과 다르다"
    if record.get("used_at"):
        return "이미 게시한 승인이다(1회용)"
    try:
        result = read_json(job / RESULT_FILE)
    except (OSError, ValueError) as exc:
        return f"게시 결과 기록 손상({type(exc).__name__})"
    if result and result.get("body_sha256") == record.get("body_sha256"):
        if result.get("status") == "unknown":    # 결과 처리 실패: 게시됐을 수 있다
            return "이전 게시 결과가 불명이다(게시됐을 수 있다) — Jira에서 확인한다"
        if result.get("status") == "posted" and record.get("again") is not True:   # --again 승인만 다시 올린다
            return "이미 게시됨(같은 본문)"
    try:
        deadline = parse_iso(record.get("expires_at"))
    except (TypeError, ValueError):
        return "승인 기록의 만료 시각이 잘못됐다"
    if at > deadline:
        return f"승인 만료({APPROVAL_TTL_MIN}분) — render부터 다시"
    if body_sha256(body) != record.get("body_sha256"):
        return "본문이 승인한 본문과 다르다(sha256 불일치)"
    # 실제로 올라가는 것은 정규화 전 입력이다: post.md와 글자 그대로(줄바꿈 LF/CRLF 차이와 끝 줄바꿈 하나만 허용) 같아야 한다
    try:
        post = (job / POST_FILE).read_text(encoding="utf-8")
    except OSError:
        return "본문 파일(post.md)이 없다"
    sent, want = body.replace("\r\n", "\n"), post.replace("\r\n", "\n")
    if sent not in (want, want.removesuffix("\n")):
        return "본문이 post.md와 글자 그대로 같지 않다(공백·줄 끝·유니코드 형태 차이)"
    return None
