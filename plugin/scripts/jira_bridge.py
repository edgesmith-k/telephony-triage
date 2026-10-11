#!/usr/bin/env python3
"""jira_bridge.py — Jira MCP 응답 원문을 모델 대신 파일로 받는 PostToolUse hook (08-safety.md §8.1·§9 9번).

stdin: hook 입력 `{tool_name, tool_input, tool_response, ...}`. `tool_name`이 config `jira.tools.get_issue`
또는 `jira.tools.get_comments`(전체 이름, 서버 이름 정규화 비교 — `mcptools.normalize`)일 때만 동작한다. 그 밖의 도구는 아무것도 출력하지 않는다(원래 결과 그대로).

1. 응답에서 이슈 키를 찾아 `jira_key_regex`(스냅샷 또는 사용자 clone의 `issue-db.config.yaml`)로 검사한다.
2. 원문을 `<work_dir>/<KEY>/jira_raw.json`(디렉토리 권한 700)에 쓴다. `get_comments` 응답은 같은 파일의 `comments`에 합친다.
   `triage.py run`이 이 파일을 `jira_fields.py extract --consume`으로 읽고 지운다.
3. 모델에는 `hookSpecificOutput.updatedToolOutput`으로 **마스킹된 요약**(요약·설명 앞부분·코멘트 마지막 3개)만 준다.

**승인 코멘트 게시 결과**(`add_comment`): `tool_name`이 유효한 `jira.write_tools.add_comment.tool`(정규화 비교,
`common/issuepost.write_spec`)이면 `bridge_post`가 `<work_dir>/<KEY>/post.result.json`(posted|error)을 쓰고, 성공이면
`post.approved.json`에 `used_at`을 남긴다(1회용). 실패 응답(`isError` 또는 참인 `error` 값)이면 승인을 소모하지 않는다.
결과 처리 중 예외면 게시됐을 수 있으므로 `post.result.json` status unknown과 `used_at`을 남겨 재게시를 막는다. 모델에는 게시 요약만
보이고 응답 원문은 보이지 않는다. 응답 형식(comment id 위치)은 TODO(SITE:S23).

실패하면 원문을 내보내지 않고 오류 문구로 바꾼다(fail closed). 설정(`config.yaml`·`site-defaults.yaml`)을 읽지 못해
대상인지 판정할 수 없으면 모든 `mcp__` 결과를 오류 문구로 바꾼다(guard가 같은 상태에서 모든 `mcp__` 호출을 거부하는 범위와 같다).
의존성(PyYAML 등) import가 실패해도 같다(종료 1로 끝나 원문이 새지 않게). `site-defaults.yaml`이 없으면 guard처럼
사용자 config만으로 판정한다. 종료 코드는 항상 0. 출력 필드 이름은 Claude Code hooks 문서의
PostToolUse `updatedToolOutput`이다 — TODO(SITE:S1) 사내 Claude Code 버전에서 원문이 대체되는지 확인한다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

# 의존성(PyYAML 등)이 없으면 import가 터진다: 종료 1이면 원문이 그대로 모델에 가므로 받아 두고 `main`에서 막는다.
try:
    from common import compat, issuepost, masking, mcptools, site_defaults, userconfig  # noqa: E402
    import jira_fields  # noqa: E402
    IMPORT_ERROR: Exception | None = None
except ImportError as _exc:   # noqa: BLE001
    IMPORT_ERROR = _exc

BRIEF_COMMENTS = "last:3"
BRIEF_CHARS = 200
POST_ERROR_CHARS = 200
COMMENT_ID_KEYS = ("id", "commentId", "comment_id")   # TODO(SITE:S23) 응답의 comment id 위치
POST_FAILED = ("telephony-triage: Jira 코멘트 게시 결과 처리 실패 — 게시는 됐을 수 있다. "
               "Jira에서 확인하고 다시 게시하지 않는다(응답 원문은 표시하지 않는다).")


def _payload(response):
    """MCP 결과(문자열, `content[]` 블록, `structuredContent`)를 JSON 객체로 바꾼다."""
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


def _key_regex(cfg: dict) -> re.Pattern:
    work = Path(str(userconfig.get(cfg, "work_dir"))).expanduser()
    for db in (work / "_snapshot", Path(str(userconfig.get(cfg, "issue_db.path") or "")).expanduser()):
        conf = compat.load_db_config(db) if (db / "issue-db.config.yaml").is_file() else {}
        if conf.get("jira_key_regex"):
            return re.compile(str(conf["jira_key_regex"]))
    return re.compile(jira_fields.DEFAULT_KEY_RE)


def _find_key(data, tool_input: dict, kre: re.Pattern) -> str | None:
    candidates = []
    if isinstance(data, dict):
        candidates += [data.get("key"), (data.get("issue") or {}).get("key") if isinstance(data.get("issue"), dict) else None]
    candidates += [v for v in (tool_input or {}).values() if isinstance(v, str)]
    return next((str(c) for c in candidates if c and kre.fullmatch(str(c))), None)


def target(event: dict, cfg: dict) -> str | None:
    """대상 논리 동작(`get_issue`·`get_comments`·`add_comment`) 또는 None. `add_comment`는 유효한 코멘트 도구 설정만."""
    tools = (cfg.get("jira") or {}).get("tools") or {}
    tool = event.get("tool_name")
    spec, _err = issuepost.write_spec(cfg)
    if spec and spec["tool"] == mcptools.normalize(tool):
        return "add_comment"
    return next((k for k in ("get_issue", "get_comments")
                 if tools.get(k) and mcptools.normalize(tools[k]) == mcptools.normalize(tool)), None)


def _comment_id(data):
    if isinstance(data, dict):
        for node in (data, data.get("comment") if isinstance(data.get("comment"), dict) else None):
            for k in COMMENT_ID_KEYS:
                if node and isinstance(node.get(k), (str, int)) and str(node.get(k)):
                    return str(node[k])
    return None


def bridge_post(event: dict, cfg: dict) -> str:
    """승인 코멘트 게시 결과를 `post.result.json`에 기록한다. 성공이면 승인에 `used_at`을 남긴다(1회용)."""
    spec, _err = issuepost.write_spec(cfg)
    tool_input = event.get("tool_input") or {}
    key = tool_input.get(spec["key_arg"]) if isinstance(tool_input, dict) else None
    if not isinstance(key, str) or not issuepost.KEY_SAFE_RE.fullmatch(key):
        return POST_FAILED
    job = userconfig.ensure_private_dir(Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key)
    sha = issuepost.body_sha256(str(tool_input.get(spec["body_arg"]) or ""))
    approved_path = job / issuepost.APPROVED_FILE
    try:
        approved = issuepost.read_json(approved_path)
    except (OSError, ValueError):
        approved = None
    response = event.get("tool_response")
    data = _payload(response)
    at = issuepost.iso(issuepost.now())
    base = {"schema": 1, "key": key, "tool": spec["tool"], "body_sha256": sha,
            "approved_at": (approved or {}).get("approved_at")}
    # 실패: isError, 또는 응답의 error 값이 참일 때만(`"error": null`·""·false는 성공 응답의 빈 칸이다)
    failed = (isinstance(response, dict) and response.get("isError") is True) or (
        isinstance(data, dict) and bool(data.get("error")) and not data.get("ok"))
    if failed:
        detail = data.get("error") if isinstance(data, dict) and data.get("error") else data
        error = masking.new_masker().mask(json.dumps(detail, ensure_ascii=False)
                                          if not isinstance(detail, str) else detail)[:POST_ERROR_CHARS]
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
    data = _payload(event.get("tool_response"))
    kre = _key_regex(cfg)
    key = _find_key(data, event.get("tool_input") or {}, kre)
    if key is None:
        return "telephony-triage: Jira 응답에서 형식에 맞는 이슈 키를 찾지 못해 저장하지 않았다(원문은 표시하지 않는다)."
    job = userconfig.ensure_private_dir(Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key)
    raw_path = job / "jira_raw.json"
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
        comments = raw.get("comments")
        raw = dict(issue)
        if comments and not raw.get("comments"):
            raw["comments"] = comments
    else:
        comments = data.get("comments") if isinstance(data, dict) else data
        raw.setdefault("key", key)
        raw["comments"] = comments if isinstance(comments, list) else [comments]
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
    return ("telephony-triage: Jira 응답 원문은 파일로만 저장했다(모델에 보이지 않음). 아래는 마스킹된 요약이다. "
            "분석은 triage.py run이 이 파일을 읽는다.\n" + json.dumps(shown, ensure_ascii=False, indent=1))


def mark_unknown(event: dict, cfg: dict) -> None:
    """결과 처리 중 예외: 게시됐을 수 있으므로 `post.result.json` status unknown과 승인 `used_at`을 남겨 다시 게시하지
    못하게 한다(guard가 둘 다 거부한다). 이것도 실패하면 아무것도 하지 않는다(문구는 fail-closed 그대로)."""
    try:
        spec, _err = issuepost.write_spec(cfg)
        tool_input = event.get("tool_input") or {}
        key = tool_input.get(spec["key_arg"])
        if not isinstance(key, str) or not issuepost.KEY_SAFE_RE.fullmatch(key):
            return
        job = Path(str(userconfig.get(cfg, "work_dir"))).expanduser() / key
        if not job.is_dir():
            return
        at = issuepost.iso(issuepost.now())
        sha = issuepost.body_sha256(str(tool_input.get(spec["body_arg"]) or ""))
    except Exception as exc:  # noqa: BLE001
        print(f"jira_bridge: 결과 불명 기록 실패: {exc}", file=sys.stderr)
        return
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
    try:
        cfg = userconfig.merged(defaults, user)
        kind = target(event, cfg)
    except Exception as exc:  # noqa: BLE001
        kind, error = None, exc
    if kind is None:
        if error is None or not str(event.get("tool_name") or "").startswith("mcp__"):
            return 0
        print(f"jira_bridge: {error}", file=sys.stderr)
        text = (f"telephony-triage: 설정을 읽지 못해({type(error).__name__}) Jira 응답 격리 여부를 판정하지 못했다 "
                "— 원문은 표시하지 않는다.")
    else:
        try:
            text = bridge_post(event, cfg) if kind == "add_comment" else bridge(event, cfg, kind)
        except Exception as exc:  # noqa: BLE001 — 실패해도 원문을 내보내지 않는다
            print(f"jira_bridge: {exc}", file=sys.stderr)
            if kind == "add_comment":
                mark_unknown(event, cfg)
            text = POST_FAILED if kind == "add_comment" else \
                f"telephony-triage: Jira 응답 처리 실패({type(exc).__name__}) — 원문은 표시하지 않는다."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": text}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
