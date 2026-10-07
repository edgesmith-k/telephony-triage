#!/usr/bin/env python3
"""jira_bridge.py — Jira MCP 응답 원문을 모델 대신 파일로 받는 PostToolUse hook (08-safety.md §8.1·§9 9번).

stdin: hook 입력 `{tool_name, tool_input, tool_response, ...}`. `tool_name`이 config `jira.tools.get_issue`
또는 `jira.tools.get_comments`(전체 이름, 서버 이름 정규화 비교 — `mcptools.normalize`)일 때만 동작한다. 그 밖의 도구는 아무것도 출력하지 않는다(원래 결과 그대로).

1. 응답에서 이슈 키를 찾아 `jira_key_regex`(스냅샷 또는 사용자 clone의 `issue-db.config.yaml`)로 검사한다.
2. 원문을 `<work_dir>/<KEY>/jira_raw.json`(디렉토리 권한 700)에 쓴다. `get_comments` 응답은 같은 파일의 `comments`에 합친다.
   `triage.py run`이 이 파일을 `jira_fields.py extract --consume`으로 읽고 지운다.
3. 모델에는 `hookSpecificOutput.updatedToolOutput`으로 **마스킹된 요약**(요약·설명 앞부분·코멘트 마지막 3개)만 준다.

실패하면 원문을 내보내지 않고 오류 문구로 바꾼다(fail closed). 설정(`config.yaml`·`site-defaults.yaml`)을 읽지 못해
대상인지 판정할 수 없으면 모든 `mcp__` 결과를 오류 문구로 바꾼다(guard가 같은 상태에서 모든 `mcp__` 호출을 거부하는 범위와 같다).
`site-defaults.yaml`이 없으면 guard처럼 사용자 config만으로 판정한다. 종료 코드는 항상 0. 출력 필드 이름은 Claude Code hooks 문서의
PostToolUse `updatedToolOutput`이다 — TODO(SITE:S1) 사내 Claude Code 버전에서 원문이 대체되는지 확인한다.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, mcptools, site_defaults, userconfig  # noqa: E402
import jira_fields  # noqa: E402

BRIEF_COMMENTS = "last:3"
BRIEF_CHARS = 200


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
    """대상 논리 동작(`get_issue`·`get_comments`) 또는 None."""
    tools = (cfg.get("jira") or {}).get("tools") or {}
    tool = event.get("tool_name")
    return next((k for k in ("get_issue", "get_comments")
                 if tools.get(k) and mcptools.normalize(tools[k]) == mcptools.normalize(tool)), None)


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


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
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
            text = bridge(event, cfg, kind)
        except Exception as exc:  # noqa: BLE001 — 실패해도 원문을 내보내지 않는다
            print(f"jira_bridge: {exc}", file=sys.stderr)
            text = f"telephony-triage: Jira 응답 처리 실패({type(exc).__name__}) — 원문은 표시하지 않는다."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": text}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
