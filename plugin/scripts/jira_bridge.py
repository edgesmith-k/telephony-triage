#!/usr/bin/env python3
"""jira_bridge.py — Jira MCP 응답 원문을 모델 대신 파일로 받는 PostToolUse hook (08-safety.md §8.1·§9 9번).

stdin: hook 입력 `{tool_name, tool_input, tool_response, ...}`. `tool_name`이 config `tracker.tools.get_issue`
또는 `tracker.tools.get_comments`(전체 이름, 서버 이름 정규화 비교 — `mcptools.normalize`)일 때만 동작한다. 그 밖의 도구는 아무것도 출력하지 않는다(원래 결과 그대로).

1. 응답에서 이슈 키를 찾아 `tracker.key_regex`(스냅샷 또는 사용자 clone의 `issue-db.config.yaml`, 없으면 그 DB 트래커의
   기본 정규식)와 트래커 경로 안전 형식으로 검사한다(트래커 어댑터 `key_from_read`). 대상 판별은 어댑터 `read_action`이고,
   매핑된 도구인데 어댑터가 지원하지 않는 읽기(`unsupported`)면 원문을 대체한다(fail-closed).
2. 원문을 `<work_dir>/<KEY>/issue_raw.json`(디렉토리 권한 700)에 쓴다. `get_comments` 응답은 같은 파일의 `comments`에 합친다.
   `triage.py run`이 이 파일을 `jira_fields.py extract --consume`으로 읽고 지운다. 응답 형식은 `_payload` 순서
   (structuredContent → 텍스트 블록마다 JSON → 전체 JSON → JSONL → `key`·`fields`·`comments` 키가 있는 YAML 객체 → 텍스트)로
   읽는다. 텍스트(자유 문장)면 `get_comments`는 한 덩어리를 코멘트 1건(`comments_format: text`)으로 저장하고,
   `get_issue`는 저장하지 않고 응답 모양(형식·블록 수·글자 수 — 내용 없음)만 알린다(사내 응답 모양은 S23에서 확인).
3. 모델에는 `hookSpecificOutput.updatedToolOutput`으로 **마스킹된 요약**(요약·설명 앞부분·코멘트 마지막 3개)만 준다.

**승인 코멘트 게시 결과**(`add_comment`): `tool_name`이 유효한 `tracker.write_tools.add_comment.tool`(정규화 비교,
`common/issuepost.write_spec`)이면 `bridge_post`가 `<work_dir>/<KEY>/post.result.json`(posted|error)을 쓰고, 성공이면
`post.approved.json`에 `used_at`을 남긴다(1회용). 실패 응답(`isError` 또는 참인 `error` 값)이면 승인을 소모하지 않는다.
응답은 `isError`면 `_payload`(읽기 순서), 아니면 `_post_payload`(JSON, 아니면 YAML)로 읽는다(structuredContent가 먼저).
`_post_payload`의 YAML 오류 등 읽다 난 예외는 처리 중 예외다.
결과 처리 중 예외면 게시됐을 수 있으므로 `post.result.json` status unknown과 `used_at`을 남겨 재게시를 막는다. 모델에는 게시 요약만
보이고 응답 원문은 보이지 않는다. 응답 형식(comment id 위치)은 TODO(SITE:S23).

실패하면 원문을 내보내지 않고 오류 문구로 바꾼다(fail closed). 설정(`config.yaml`·`site-defaults.yaml`)을 읽지 못해
대상인지 판정할 수 없으면 모든 `mcp__` 결과를 오류 문구로 바꾼다(guard가 같은 상태에서 모든 `mcp__` 호출을 거부하는 범위와 같다).
옛 설정 키(`userconfig.legacy_problems`)·`tracker.kind` 오류(모르는 트래커)도 같다.
의존성(PyYAML 등) import가 실패해도 같다(종료 1로 끝나 원문이 새지 않게). `site-defaults.yaml`이 없으면 guard처럼
사용자 config만으로 판정한다. 종료 코드는 항상 0. 출력 필드 이름은 Claude Code hooks 문서의
PostToolUse `updatedToolOutput`이다 — TODO(SITE:S1) 사내 Claude Code 버전에서 원문이 대체되는지 확인한다.

**플랫폼**(17-platforms): hook에는 `--platform`이 없다.
- Jira 읽기 결과는 **선택 플랫폼** 프로필의 work_dir에 둔다(TT_PLATFORM > 사용자 config `platform` > site-defaults). 스킬이
  triage보다 먼저 Jira를 읽어도 선택 플랫폼으로 간다. 키 정규식도 그 프로필의 이슈 DB에서 읽는다.
- 게시 결과는 **게시 본문 sha256이 승인 기록과 같은 프로필**(guard와 같은 기준)에 기록한다. 맞는 프로필이 없으면 fail-closed:
  그 KEY 승인이 있는 모든 프로필에 `used_at`과 결과 불명(unknown)을 남긴다. 결과 처리 중 예외(mark_unknown)도 같다.
프로필이 하나면 이전과 같다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

# 의존성(PyYAML 등)이 없으면 import가 터진다: 종료 1이면 원문이 그대로 모델에 가므로 받아 두고 `main`에서 막는다.
try:
    from common import compat, issuepost, masking, mcptools, site_defaults, userconfig  # noqa: E402
    import jira_fields  # noqa: E402
    import platforms  # noqa: E402
    import trackers  # noqa: E402
    IMPORT_ERROR: Exception | None = None
except ImportError as _exc:   # noqa: BLE001
    IMPORT_ERROR = _exc

BRIEF_COMMENTS = "last:3"
BRIEF_CHARS = 200
POST_ERROR_CHARS = 200
COMMENT_ID_KEYS = ("id", "commentId", "comment_id")   # TODO(SITE:S23) 응답의 comment id 위치
POST_FAILED = ("telephony-triage: Jira 코멘트 게시 결과 처리 실패 — 게시는 됐을 수 있다. "
               "Jira에서 확인하고 다시 게시하지 않는다(응답 원문은 표시하지 않는다).")


YAML_KEYS = ("key", "fields", "comments")     # YAML로 받는 응답: 이 키가 있는 객체만(그 밖 텍스트는 YAML로 읽지 않는다)


def _json_value(text: str):
    """JSON 객체·배열이면 그 값, 아니면 None (스칼라·형식 오류는 JSON 응답으로 보지 않는다)."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, (dict, list)) else None


def _payload(response) -> tuple[object, str]:
    """MCP 결과(문자열, `content[]` 블록, `structuredContent`)를 `(값, 형식)`으로 바꾼다. 형식 오류로 예외를 내지 않는다.

    순서: `structuredContent`(structured) → 텍스트 블록마다 JSON(하나면 json, 여럿이면 목록 json-blocks — 배열 블록은
    펼친다) → 블록을 이은 문자열 전체 JSON(json) → 줄마다 JSON(jsonl, 2줄 이상) → YAML(`key`·`fields`·`comments` 키가
    있는 객체만, yaml) → 나머지는 `{"text": 원문}`(text). 코멘트 본문 같은 자유 텍스트(`a: b: c`·탭·`@`·`%` 등)를
    YAML로 읽다 ScannerError가 나지 않게 한다."""
    if isinstance(response, dict) and isinstance(response.get("structuredContent"), (dict, list)):
        return response["structuredContent"], "structured"
    blocks = response.get("content") if isinstance(response, dict) else response
    texts = None
    if isinstance(blocks, list) and all(isinstance(b, dict) and "type" in b for b in blocks):
        texts = [str(b.get("text") or "") for b in blocks if b.get("type") == "text"]
        parts = [t for t in texts if t.strip()]
        values = [_json_value(t) for t in parts]
        if len(parts) > 1 and all(v is not None for v in values):
            merged: list = []
            for v in values:
                if isinstance(v, list):
                    merged.extend(v)
                else:
                    merged.append(v)
            return merged, f"json-blocks×{len(parts)}"
        response = "".join(texts)          # 큰 JSON을 블록 여러 개로 나눠 보내는 서버(이전 동작)
    if not isinstance(response, str):
        return response, "object"
    whole = _json_value(response)
    if whole is not None:
        return whole, "json"
    text = "\n".join(texts) if texts else response
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1:
        values = [_json_value(ln) for ln in lines]
        if all(v is not None for v in values):
            return values, "jsonl"
    try:
        from common import yamlio
        data = yamlio.safe_load(text)
    except Exception:  # noqa: BLE001 — yaml.YAMLError(ScannerError 등)·그 밖 로더 오류: 텍스트로 받는다
        data = None
    if isinstance(data, dict) and any(k in data for k in YAML_KEYS):
        return data, "yaml"
    return {"text": text}, "text"


def _shape_note(response, shape: str | None = None) -> str:
    """응답 형식 진단(내용 없음): 형식, structuredContent 유무, 텍스트 블록 수, 첫 글자 종류, 글자 수. 사내 보고용."""
    try:
        shape = shape or _payload(response)[1]
        blocks = response.get("content") if isinstance(response, dict) else response
        if isinstance(blocks, list):
            texts = [str(b.get("text") or "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        else:
            texts = [response] if isinstance(response, str) else []
        text = "".join(texts).lstrip()
        first = text[:1]
        kind = ("없음" if not first else first if first in "{[\"" else "글자" if first.isalpha()
                else "숫자" if first.isdigit() else "기호")
        sc = "있음" if isinstance(response, dict) and "structuredContent" in response else "없음"
        return f"형식: {shape}, structuredContent {sc}, 텍스트 블록 {len(texts)}, 첫 글자 {kind}, {len(text)}자"
    except Exception:  # noqa: BLE001 — 진단 실패는 형식만
        return f"형식: {shape or '?'}"


_PROFILES: dict[str, dict] = {}     # main이 채운다: 사용자 config의 모든 플랫폼 프로필 cfg


def _approved_cfgs(cfg: dict, key: str) -> list[tuple[dict, dict | None]]:
    """그 KEY 승인 기록이 있는 프로필 `[(cfg, 승인 기록 또는 None(손상))]`. 프로필 목록이 비면 `cfg` 하나만 본다."""
    out = []
    for c in (_PROFILES.values() or [cfg]):
        path = Path(str(userconfig.get(c, "work_dir"))).expanduser() / key / issuepost.APPROVED_FILE
        if path.is_file():
            try:
                out.append((c, issuepost.read_json(path)))
            except (OSError, ValueError):
                out.append((c, None))
    return out


def _post_cfg(cfg: dict, key: str, sha: str) -> dict | None:
    """게시 본문 sha256이 승인 기록과 같은 프로필의 cfg(여럿이면 첫 프로필 순서). 없으면 None."""
    return next((c for c, rec in _approved_cfgs(cfg, key) if rec and rec.get("body_sha256") == sha), None)


def _key_regex(cfg: dict) -> re.Pattern:
    """스냅샷 > 사용자 clone의 `tracker.key_regex`. 없으면 처음 찾은 DB 설정의 트래커(없으면 세션 트래커) 기본 정규식."""
    work = Path(str(userconfig.get(cfg, "work_dir"))).expanduser()
    declared = None
    for db in (work / "_snapshot", Path(str(userconfig.get(cfg, "issue_db.path") or "")).expanduser()):
        conf = compat.load_db_config(db) if (db / "issue-db.config.yaml").is_file() else {}
        declared = conf if declared is None and conf else declared
        tracker = conf.get("tracker") if isinstance(conf.get("tracker"), dict) else {}
        if tracker.get("key_regex"):
            return re.compile(str(tracker["key_regex"]))
    return re.compile((trackers.of_db(declared) if declared else trackers.of(cfg)).default_key_regex)


def target(event: dict, cfg: dict) -> str | None:
    """대상 논리 동작(`get_issue`·`get_comments`·`add_comment`), 매핑된 도구인데 트래커가 지원하지 않는 읽기면
    `"unsupported"`, 대상이 아니면 None. `add_comment`는 유효한 코멘트 도구 설정만."""
    tools = (cfg.get("tracker") or {}).get("tools") or {}
    tool = event.get("tool_name")
    spec, _err = issuepost.write_spec(cfg)
    if spec and spec["tool"] == mcptools.normalize(tool):
        return "add_comment"
    mapped = {k for k in ("get_issue", "get_comments")
              if tools.get(k) and mcptools.normalize(tools[k]) == mcptools.normalize(tool)}
    if not mapped:
        return None
    adapter = trackers.of(cfg)
    try:
        action = adapter.read_action(event.get("tool_input"), set(mapped))
    except Exception:  # noqa: BLE001 — 어댑터 오류도 원문을 숨긴다
        return "unsupported"
    # 매핑된 읽기 도구다: 어댑터가 mapped 밖의 값(None·add_comment 등)을 내도 원문을 통과시키지 않는다(fail-closed)
    return action if isinstance(action, str) and action in mapped else "unsupported"


def _post_payload(response):
    """게시 결과(`add_comment`) 응답을 값으로 바꾼다. 읽기용 `_payload`의 형식 순서를 쓰지 않는다: 블록을 이은 문자열이
    JSON이 아니면 YAML로 읽고(`error: …` 객체는 실패, `id: …`는 comment id), 객체·목록이 아니면 `{"text": 원문}`.
    YAML 오류는 올린다 — `main`이 결과 불명(unknown)과 `used_at`을 남긴다(게시됐을 수 있다)."""
    if isinstance(response, dict) and isinstance(response.get("structuredContent"), (dict, list)):
        return response["structuredContent"]
    blocks = response.get("content") if isinstance(response, dict) else response
    if isinstance(blocks, list) and all(isinstance(b, dict) and "type" in b for b in blocks):
        response = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
    if isinstance(response, str):
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            from common import yamlio
            data = yamlio.safe_load(response)
            return data if isinstance(data, (dict, list)) else {"text": response}
    return response


def _comment_id(data):
    if isinstance(data, dict):
        for node in (data, data.get("comment") if isinstance(data.get("comment"), dict) else None):
            for k in COMMENT_ID_KEYS:
                if node and isinstance(node.get(k), (str, int)) and str(node.get(k)):
                    return str(node[k])
    return None


_JSON_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|.)')   # json.dumps 이스케이프 하나씩 왼쪽부터(`\\` 뒤 `n`은 줄바꿈이 아니다)
_ESCAPE_TO = {"\\\\": "\\\\", '\\"': '"'}                  # 역슬래시는 그대로, 따옴표는 풀고, 그 밖(제어 문자)은 `|`


def _mask_detail(detail) -> str:
    """실패 기록 `error`(마스킹 ≤200자). 객체는 json.dumps한 글 하나를 마스킹한다(키 문맥 `"token": "…"` 유지). 그 전에 제어 문자
    이스케이프(줄바꿈·탭 등)는 `|`로, 이스케이프한 따옴표는 따옴표로 바꾼다 — 이스케이프 글자가 단어 경계를 가려 뒤 식별자를 놓치지
    않게(`|`는 공백이 아니라 자격증명 값 앞에 와도 값이 끊기지 않는다)."""
    if not isinstance(detail, str):
        detail = _JSON_ESCAPE.sub(lambda m: _ESCAPE_TO.get(m.group(0), "|"), json.dumps(detail, ensure_ascii=False))
    return masking.new_masker().mask(detail)[:POST_ERROR_CHARS]


def bridge_post(event: dict, cfg: dict) -> str:
    """승인 코멘트 게시 결과를 `post.result.json`에 기록한다. 성공이면 승인에 `used_at`을 남긴다(1회용)."""
    spec, _err = issuepost.write_spec(cfg)
    tool_input = event.get("tool_input") or {}
    key = issuepost.spec_tracker(spec).key_from_args(spec, tool_input)     # 경로 안전 작업 키 또는 None
    if not isinstance(key, str) or not issuepost.spec_tracker(spec).safe_key_re.fullmatch(key):
        return POST_FAILED
    sha = issuepost.body_sha256(str(tool_input.get(spec["body_arg"]) or ""))
    if len(_PROFILES) > 1:
        chosen = _post_cfg(cfg, key, sha)
        if chosen is None:      # 어느 승인과도 맞지 않는다: 재게시를 막고(fail-closed) 결과 불명으로 남긴다
            mark_unknown(event, cfg)
            return POST_FAILED
        cfg = chosen
    job = userconfig.ensure_private_dir(Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key)
    approved_path = job / issuepost.APPROVED_FILE
    try:
        approved = issuepost.read_json(approved_path)
    except (OSError, ValueError):
        approved = None
    response = event.get("tool_response")
    # isError면 읽기 순서(`_payload`, YAML 오류는 텍스트로)로 읽어 실패로 남긴다. 아니면 `_post_payload`(YAML 오류는 처리 중 예외)
    data = _payload(response)[0] if isinstance(response, dict) and response.get("isError") is True \
        else _post_payload(response)
    at = issuepost.iso(issuepost.now())
    base = {"schema": 1, "key": key, "tool": spec["tool"], "body_sha256": sha,
            "approved_at": (approved or {}).get("approved_at")}
    # 실패: isError, 또는 응답의 error 값이 참일 때만(`"error": null`·""·false는 성공 응답의 빈 칸이다)
    failed = (isinstance(response, dict) and response.get("isError") is True) or (
        isinstance(data, dict) and bool(data.get("error")) and not data.get("ok"))
    if failed:
        detail = data.get("error") if isinstance(data, dict) and data.get("error") else data
        error = _mask_detail(detail)
        issuepost.write_private_json(job / issuepost.RESULT_FILE, {**base, "status": "error", "at": at, "error": error})
        return (f"telephony-triage: Jira 코멘트 게시 실패({key}) — 승인은 소모하지 않았다(응답 원문은 표시하지 않는다). "
                f"기록: {job / issuepost.RESULT_FILE}")
    comment_id = _comment_id(data)
    issuepost.write_private_json(job / issuepost.RESULT_FILE,
                                 {**base, "status": "posted", "at": at, "posted_at": at, "comment_id": comment_id})
    if approved is not None and approved.get("body_sha256") == sha:
        approved["used_at"] = at
        issuepost.write_private_json(approved_path, approved)
    return (f"telephony-triage: Jira 코멘트를 게시했다 ({key}, comment {comment_id or '?'}). 응답 원문은 표시하지 않는다. "
            f"기록: {job / issuepost.RESULT_FILE}")


def bridge(event: dict, cfg: dict, kind: str) -> str:
    response = event.get("tool_response")
    data, shape = _payload(response)
    if kind == "get_issue" and shape == "text":     # 자유 텍스트 이슈 응답: 필드를 읽을 수 없다(원문은 보이지 않는다)
        return (f"telephony-triage: Jira 응답이 JSON이 아니라 저장하지 않았다({_shape_note(response, shape)}) "
                "— tracker.tools.get_issue가 JSON을 내는 도구인지 확인한다(원문은 표시하지 않는다).")
    kre = _key_regex(cfg)
    key = trackers.of(cfg).key_from_read(data, event.get("tool_input") or {}, kre)
    if key is None:
        return "telephony-triage: Jira 응답에서 형식에 맞는 이슈 키를 찾지 못해 저장하지 않았다(원문은 표시하지 않는다)."
    job = userconfig.ensure_private_dir(Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key)
    raw_path = job / "issue_raw.json"
    raw = {}
    if raw_path.is_file():
        try:
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
    if kind == "get_issue":
        issue = data.get("issue") if isinstance(data, dict) and isinstance(data.get("issue"), dict) else data
        if not isinstance(issue, dict):
            return "telephony-triage: Jira 응답이 객체가 아니라 저장하지 않았다(원문은 표시하지 않는다)."
        comments, comments_format = raw.get("comments"), raw.get("comments_format")
        raw = dict(issue)
        raw.setdefault("key", key)      # 키가 응답 밖(도구 입력)에서 온 트래커도 extract가 같은 키를 본다
        if comments and not raw.get("comments"):
            raw["comments"] = comments
            if comments_format:
                raw["comments_format"] = comments_format
    elif shape == "text":       # 자유 텍스트 코멘트 응답: 한 덩어리를 코멘트 1건으로(extract가 마스킹한다)
        raw.setdefault("key", key)
        raw["comments"] = [{"body": data["text"]}]
        raw["comments_format"] = "text"
    else:
        comments = data.get("comments") if isinstance(data, dict) else data
        raw.setdefault("key", key)
        raw["comments"] = comments if isinstance(comments, list) else [comments]
        raw.pop("comments_format", None)
    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8", newline="\n")
    try:
        raw_path.chmod(0o600)
    except OSError:
        pass
    brief = jira_fields.extract(raw, cfg, None, "mcp", jira_fields.comment_budget(BRIEF_COMMENTS), BRIEF_CHARS)
    text = brief["text"]
    shown = {"key": key, "saved_to": str(raw_path), "occurred_at": brief["occurred_at"], "missing": brief["missing"],
             "summary": text["summary"][:BRIEF_CHARS], "description": text["description"][:BRIEF_CHARS * 2],
             "comments_total": text["comments_total"], "last_comments": text["comments"]}
    note = ""
    if kind == "get_comments" and shape == "text":
        note = (f"코멘트 응답이 JSON이 아니라 텍스트 한 덩어리를 코멘트 1건으로 저장했다"
                f"(형식: text, {len(data['text'])}자). ")
    return ("telephony-triage: Jira 응답 원문은 파일로만 저장했다(모델에 보이지 않음). " + note + "아래는 마스킹된 요약이다. "
            "분석은 triage.py run이 이 파일을 읽는다.\n" + json.dumps(shown, ensure_ascii=False, indent=1))


def mark_unknown(event: dict, cfg: dict) -> None:
    """결과 처리 중 예외: 게시됐을 수 있으므로 `post.result.json` status unknown과 승인 `used_at`을 남겨 다시 게시하지
    못하게 한다(guard가 둘 다 거부한다). 이것도 실패하면 아무것도 하지 않는다(문구는 fail-closed 그대로)."""
    try:
        spec, _err = issuepost.write_spec(cfg)
        tool_input = event.get("tool_input") or {}
        key = issuepost.spec_tracker(spec).key_from_args(spec, tool_input)
        if not isinstance(key, str) or not issuepost.spec_tracker(spec).safe_key_re.fullmatch(key):
            return
        # 그 KEY 승인이 있는 모든 프로필(어느 것으로 게시됐는지 모르므로 fail-closed). 승인이 없으면 선택 프로필의 작업 디렉토리
        cfgs = [c for c, _rec in _approved_cfgs(cfg, key)] or [cfg]
        at = issuepost.iso(issuepost.now())
        sha = issuepost.body_sha256(str(tool_input.get(spec["body_arg"]) or ""))
    except Exception as exc:  # noqa: BLE001
        print(f"jira_bridge: 결과 불명 기록 실패: {exc}", file=sys.stderr)
        return
    for c in cfgs:
        job = Path(str(userconfig.get(c, "work_dir"))).expanduser() / key
        if job.is_dir():
            _mark_unknown_job(job, key, spec, sha, at)


def _mark_unknown_job(job: Path, key: str, spec: dict, sha: str, at: str) -> None:
    try:     # 1회용 표시를 먼저: 결과 파일을 못 써도 재게시는 막는다
        approved_path = job / issuepost.APPROVED_FILE
        approved = issuepost.read_json(approved_path)
        if approved is not None and not approved.get("used_at"):
            approved["used_at"] = at
            issuepost.write_private_json(approved_path, approved)
    except Exception as exc:  # noqa: BLE001
        print(f"jira_bridge: used_at 기록 실패: {exc}", file=sys.stderr)
    try:
        issuepost.write_private_json(job / issuepost.RESULT_FILE, {"schema": 1, "status": "unknown", "key": key,
                                                                    "tool": spec["tool"], "body_sha256": sha, "at": at})
    except Exception as exc:  # noqa: BLE001
        print(f"jira_bridge: 결과 불명 기록 실패: {exc}", file=sys.stderr)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):   # hook 입력 형식이 아니다: 도구 이름을 모른다
        return 0
    if IMPORT_ERROR is not None:      # 대상 판정 불가: guard와 같은 범위(모든 mcp__)의 원문을 숨긴다
        if not str(event.get("tool_name") or "").startswith("mcp__"):
            return 0
        print(f"jira_bridge: {IMPORT_ERROR}", file=sys.stderr)
        text = (f"telephony-triage: 의존성 없음({type(IMPORT_ERROR).__name__}: {IMPORT_ERROR})으로 Jira 응답 격리 여부를 "
                "판정하지 못했다 — 원문은 표시하지 않는다. pyproject 의존성 설치 후 config.py doctor로 확인한다.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": text}},
                         ensure_ascii=False))
        return 0
    error = None
    try:
        defaults = site_defaults.load()
    except site_defaults.SiteDefaultsMissing:
        defaults = {}    # guard와 같게: 사용자 config만으로 판정한다
    except Exception as exc:  # noqa: BLE001
        defaults, error = {}, exc
    try:
        user = userconfig.load_user() or {}
    except Exception as exc:  # noqa: BLE001
        user, error = {}, exc
    legacy = userconfig.legacy_problems(defaults, user) if error is None else []
    if legacy:      # 옛 설정 키: 설정 오류와 같은 범위(모든 mcp__)의 원문을 숨긴다(guard는 모든 MCP를 거부한다)
        if not str(event.get("tool_name") or "").startswith("mcp__"):
            return 0
        print(f"jira_bridge: 옛 설정 키 {legacy}", file=sys.stderr)
        text = ("telephony-triage: 옛 설정 키(" + "; ".join(legacy) + ")가 남아 Jira 응답 격리 여부를 판정하지 못했다 "
                "— 원문은 표시하지 않는다. config.py rename-legacy로 바꾼 뒤 config.py doctor로 확인한다.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": text}},
                         ensure_ascii=False))
        return 0
    tracker_error = None
    if error is None:
        try:
            trackers.kind_of(userconfig.merged(defaults, user))
        except trackers.TrackerConfigError as exc:
            tracker_error = str(exc)
        except Exception as exc:  # noqa: BLE001 — 아래 설정 오류 경로가 대체한다
            error = exc
    if tracker_error:   # tracker.kind 오류: 옛 설정 키와 같은 범위(모든 mcp__)의 원문을 숨긴다(guard는 모든 MCP를 거부한다)
        if not str(event.get("tool_name") or "").startswith("mcp__"):
            return 0
        print(f"jira_bridge: 트래커 설정 오류 {tracker_error}", file=sys.stderr)
        text = (f"telephony-triage: 트래커 설정 오류({tracker_error})로 Jira 응답 격리 여부를 판정하지 못했다 "
                "— 원문은 표시하지 않는다. tracker.kind를 고친 뒤 config.py doctor로 확인한다.")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": text}},
                         ensure_ascii=False))
        return 0
    try:
        _PROFILES.clear()
        _PROFILES.update(userconfig.profiles(defaults, user))
        cfg = _PROFILES[userconfig.TOP_PROFILE]
        if len(_PROFILES) > 1 or os.environ.get(platforms.ENV) or userconfig.selected_hint(user) \
                or platforms.default_name(defaults) != userconfig.TOP_PROFILE:
            # 선택 플랫폼(TT_PLATFORM > 사용자 config platform > site). 잘못되면 기본 프로필(읽기 결과 위치만 정한다)
            try:
                chosen = platforms.select(defaults, None, userconfig.selected_hint(user))
            except platforms.PlatformConfigError:
                chosen = userconfig.TOP_PROFILE
            cfg = _PROFILES.get(chosen) or (cfg if chosen == userconfig.TOP_PROFILE
                                            else userconfig.merged(defaults, user, platform=chosen))
        kind = target(event, cfg)
    except Exception as exc:  # noqa: BLE001
        kind, error = None, exc
    if kind is None:
        if error is None or not str(event.get("tool_name") or "").startswith("mcp__"):
            return 0
        print(f"jira_bridge: {error}", file=sys.stderr)
        text = (f"telephony-triage: 설정을 읽지 못해({type(error).__name__}) Jira 응답 격리 여부를 판정하지 못했다 "
                "— 원문은 표시하지 않는다.")
    elif kind == "unsupported":     # 매핑된 읽기 도구인데 트래커가 지원하지 않는 호출(예: 다른 method): 원문을 숨긴다
        text = ("telephony-triage: 이 트래커가 지원하지 않는 읽기 호출이라 응답을 저장하지 않았다 — 원문은 표시하지 않는다. "
                "tracker.tools 매핑과 호출 인자를 확인한다.")
    else:
        try:
            text = bridge_post(event, cfg) if kind == "add_comment" else bridge(event, cfg, kind)
        except Exception as exc:  # noqa: BLE001 — 실패해도 원문을 내보내지 않는다
            print(f"jira_bridge: {type(exc).__name__}", file=sys.stderr)    # 예외 문구에 응답 조각이 있을 수 있다
            if kind == "add_comment":
                mark_unknown(event, cfg)
            text = POST_FAILED if kind == "add_comment" else \
                (f"telephony-triage: Jira 응답 처리 실패({type(exc).__name__}) — 원문은 표시하지 않는다"
                 f"({_shape_note(event.get('tool_response'))}).")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": text}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
