"""사용자 config와 설정 우선순위 (02-config.md §4, contracts.md §기존 자산 연결 계약).

설정 파일: `~/.telephony-triage/config.yaml` (사용자별, 커밋하지 않음). 위치는 환경변수
`TELEPHONY_TRIAGE_HOME`으로 바꿀 수 있다(테스트용).

우선순위: **사용자 config > 플러그인 `site-defaults.yaml` > 코드 내장 기본값**.
`site-defaults.yaml`이 없으면 호출자가 먼저 종료 코드 2로 멈춘다(`site_defaults.load_or_exit`).
`site-defaults.example.yaml`은 읽지 않는다.
"""

from __future__ import annotations

import copy
import os
import stat
from pathlib import Path

import yaml

from . import yamlio

HOME_ENV = "TELEPHONY_TRIAGE_HOME"
FILENAME = "config.yaml"


def home() -> Path:
    env = os.environ.get(HOME_ENV)
    return Path(env).expanduser() if env else Path.home() / ".telephony-triage"


def path() -> Path:
    return home() / FILENAME


def builtin() -> dict:
    return {
        "issue_db": {"base_branch": "main"},
        "jira": {"tools": {}, "read_tools": [], "field_map": {}},
        "logcat": {"year_source": "jira"},
        "code_profiles": [],
        "recent_code_roots": [],
        "work_dir": str(home() / "work"),
    }


def from_site_defaults(defaults: dict) -> dict:
    """site-defaults.yaml 값을 사용자 config 키 공간으로 옮긴 것."""
    out: dict = {}
    jira = defaults.get("jira") or {}
    if jira:
        out["jira"] = {k: copy.deepcopy(v) for k, v in jira.items()}
    if defaults.get("logcat"):
        out["logcat"] = copy.deepcopy(defaults["logcat"])
    if defaults.get("analyzers"):   # 분석 스킬은 site-defaults 또는 사용자 config (16-existing-assets.md §16.5)
        out["analyzers"] = copy.deepcopy(defaults["analyzers"])
    if defaults.get("explore"):     # 탐색 분석(Step 5-2) 기본값 (07-workflow.md §Step 5-2)
        out["explore"] = copy.deepcopy(defaults["explore"])
    if defaults.get("failed_step"):  # 실패 스텝 앵커 설정(마커 패턴 포함, 07-workflow.md §Step 3)
        out["failed_step"] = copy.deepcopy(defaults["failed_step"])
    ghe = defaults.get("ghe") or {}
    if ghe.get("host"):
        out.setdefault("issue_db", {})["ghe_host"] = ghe["host"]
    return out


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_user() -> dict | None:
    p = path()
    if not p.is_file():
        return None
    data = yamlio.load(p)
    return data if isinstance(data, dict) else {}


def merged(defaults: dict, user: dict | None = None) -> dict:
    user = load_user() if user is None else user
    return deep_merge(deep_merge(builtin(), from_site_defaults(defaults)), user or {})


def get(data: dict, dotted: str, default=None):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def set_value(data: dict, dotted: str, value) -> dict:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value
    return data


def ensure_private_dir(p: Path) -> Path:
    """권한 700 디렉토리 (작업 계획에 Jira 요약이 들어가므로, 02-config.md §4 setup 1)."""
    p.mkdir(parents=True, exist_ok=True)
    try:
        p.chmod(stat.S_IRWXU)
    except OSError:
        pass
    return p


def save(data: dict) -> Path:
    ensure_private_dir(home())
    p = path()
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    try:
        p.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return p


def issue_db_path(defaults: dict):
    """`dbpath.resolve`의 ③(사용자 config `issue_db.path`)."""
    user = load_user()
    if not user:
        return None
    return get(user, "issue_db.path")
