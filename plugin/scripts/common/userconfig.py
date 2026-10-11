"""사용자 config와 설정 우선순위 (02-config.md §4, contracts.md §기존 자산 연결 계약).

설정 파일: `~/.telephony-triage/config.yaml` (사용자별, 커밋하지 않음). 위치는 환경변수
`TELEPHONY_TRIAGE_HOME`으로 바꿀 수 있다(테스트용).

우선순위: **사용자 config > 플러그인 `site-defaults.yaml` > 코드 내장 기본값**.
`site-defaults.yaml`이 없으면 호출자가 먼저 종료 코드 2로 멈춘다(`site_defaults.load_or_exit`).
`site-defaults.example.yaml`은 읽지 않는다.

플랫폼 프로필(17-platforms §3): 최상위 경로 키(`PROFILE_KEYS`)는 기본 플랫폼(`TOP_PROFILE`, android) 프로필이고, 그 밖 플랫폼은
`platforms.<이름>:` 아래에 같은 키만 둔다(그 밖 키는 거부, RF-4 — 플랫폼 상수는 site-defaults에서만). `merged(…, platform=p)`가
그 플랫폼의 실제 config를 준다. 다른 플랫폼은 기본 플랫폼 경로를 **물려받지 않는다**(ofono가 android clone을 가리키지 않게).
플랫폼 이름 검증·`enabled` 관문은 `platforms.select`가 한다(`common/`은 `platforms`를 import하지 않는다).
"""

from __future__ import annotations

import copy
import os
import re
import stat
from pathlib import Path

import yaml

from . import yamlio

HOME_ENV = "TELEPHONY_TRIAGE_HOME"
FILENAME = "config.yaml"
# 최상위 키 = 이 플랫폼의 프로필 (`platforms.DEFAULT_NAME`과 같아야 한다, 테스트로 확인)
TOP_PROFILE = "android"
# 플랫폼별 경로 프로필 키. `platforms.<p>`에는 이 키만 둘 수 있다
PROFILE_KEYS = ("issue_db", "work_dir", "log_dir", "code_profiles", "recent_code_roots")
_PLATFORM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


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
    """site-defaults.yaml 값을 사용자 config 키 공간으로 옮긴 것.

    issue_db.base_branch·work_dir는 옮기지 않는다 — 이슈 DB `.githooks/pre-push`가 사용자 config에서 이 두 값을 직접 읽고
    (기본 main·<home>/work) site-defaults를 보지 않으므로, 팀 기본값으로 지원하려면 pre-push도 같이 바꾼다."""
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


def merged(defaults: dict, user: dict | None = None, platform: str | None = None) -> dict:
    """실제로 쓰는 config. `platform`이 없거나 `TOP_PROFILE`이면 이전과 같은 dict(사용자 `platform`·`platforms` 키만 뺀다).
    그 밖이면 경로 프로필을 그 플랫폼 것으로 바꾸고 `platform: <이름>`을 넣는다."""
    user = load_user() if user is None else user
    user = user or {}
    base_user = {k: v for k, v in user.items() if k not in ("platform", "platforms")}
    out = deep_merge(deep_merge(builtin(), from_site_defaults(defaults)), base_user)
    if not platform or platform == TOP_PROFILE:
        return out
    prof = (user.get("platforms") or {}).get(platform) if isinstance(user.get("platforms"), dict) else None
    return _with_profile(out, defaults, platform, prof)


def _with_profile(out: dict, defaults: dict, platform: str, prof) -> dict:
    """공통 키만 남긴 `out`에 플랫폼 경로 프로필(`prof`, `PROFILE_KEYS`만)과 그 기본값을 얹는다."""
    for key in PROFILE_KEYS:
        out.pop(key, None)
    issue_db = {"base_branch": "main"}
    ghe = (defaults.get("ghe") or {}).get("host")
    if ghe:
        issue_db["ghe_host"] = ghe
    out.update({"issue_db": issue_db, "work_dir": str(home() / f"work-{platform}"), "code_profiles": [],
                "recent_code_roots": []})
    out = deep_merge(out, {k: v for k, v in (prof or {}).items() if k in PROFILE_KEYS} if isinstance(prof, dict) else {})
    out["platform"] = platform
    return out


def selected_hint(user: dict | None) -> str | None:
    """사용자 config의 개인 기본 플랫폼(`platform`). 검증은 `platforms.select`."""
    value = (user or {}).get("platform")
    return value if isinstance(value, str) and value else None


def profile_problems(user: dict | None) -> list[str]:
    """사용자 config의 플랫폼 키 오류: `platform`이 이름 형식이 아님, `platforms`가 매핑이 아님, 이름 형식·`TOP_PROFILE`,
    `platforms.<p>`에 `PROFILE_KEYS` 밖 키(RF-4)."""
    user = user or {}
    out = []
    if "platform" in user and (not isinstance(user["platform"], str) or not _PLATFORM_NAME_RE.fullmatch(user["platform"])):
        out.append(f"platform: 플랫폼 이름이 아닙니다: {user['platform']!r}")
    profs = user.get("platforms")
    if profs is None:
        return out
    if not isinstance(profs, dict):
        return out + ["platforms: 매핑이어야 합니다."]
    for name, prof in profs.items():
        if not isinstance(name, str) or not _PLATFORM_NAME_RE.fullmatch(name):
            out.append(f"platforms.{name}: 플랫폼 이름이 아닙니다(소문자·숫자·_).")
        elif name == TOP_PROFILE:
            out.append(f"platforms.{name}: {TOP_PROFILE} 프로필은 최상위 키에 둔다.")
        elif not isinstance(prof, dict):
            out.append(f"platforms.{name}: 매핑이어야 합니다.")
        else:
            for key in prof:
                if key not in PROFILE_KEYS:
                    out.append(f"platforms.{name}.{key}: 플랫폼 프로필에 둘 수 없는 키입니다 "
                               f"(허용: {', '.join(PROFILE_KEYS)}. 플랫폼 상수는 site-defaults에서만 바꾼다).")
    return out + path_problems(user)


def _abs_path(value) -> str | None:
    """비어 있지 않은 절대 경로(`~` 허용)면 정규화한 문자열, 아니면 None."""
    if not isinstance(value, str) or not value.strip():
        return None
    p = os.path.expanduser(value)
    return os.path.normpath(p) if os.path.isabs(p) else None


def _within(outer: str, inner: str) -> bool:
    return inner == outer or inner.startswith(outer.rstrip(os.sep) + os.sep)


def _raw_profiles(user: dict) -> list[tuple[str, str, dict]]:
    """`(이름, 키 경로 접두사, 프로필 원본)`. 최상위는 경로 키가 있거나 `platforms`가 없을 때만 있는 것으로 본다."""
    out = []
    profs = user.get("platforms") if isinstance(user.get("platforms"), dict) else {}
    if any(k in user for k in PROFILE_KEYS) or not profs:
        out.append((TOP_PROFILE, "", {k: user[k] for k in PROFILE_KEYS if k in user}))
    for name, prof in profs.items():
        if isinstance(prof, dict):
            out.append((str(name), f"platforms.{name}.", prof))
    return out


def path_problems(user: dict | None) -> list[str]:
    """프로필 경로 값 검사(guard 규칙 8의 제외 근거가 되므로): `work_dir`·`issue_db.path`는 비어 있지 않은 절대 경로(`~` 허용),
    어떤 work_dir도 어떤 clone을 포함하거나 같으면 안 된다, 프로필끼리 work_dir·clone·원격(`issue_db.remote`)이 겹치면 안 된다."""
    user = user or {}
    out: list[str] = []
    works, clones, remotes = [], [], []
    for name, at, prof in _raw_profiles(user):
        if "work_dir" in prof:
            work = _abs_path(prof["work_dir"])
            if work is None:
                out.append(f"{at}work_dir: 비어 있지 않은 절대 경로여야 합니다: {prof['work_dir']!r}")
        else:
            work = os.path.normpath(str(home() / ("work" if name == TOP_PROFILE else f"work-{name}")))
        if work:
            works.append((at + "work_dir", work))
        db = prof.get("issue_db")
        if db is not None and not isinstance(db, dict):
            out.append(f"{at}issue_db: 매핑이어야 합니다.")
            continue
        if isinstance(db, dict) and "path" in db:
            clone = _abs_path(db["path"])
            if clone is None:
                out.append(f"{at}issue_db.path: 비어 있지 않은 절대 경로여야 합니다: {db['path']!r}")
            else:
                clones.append((at + "issue_db.path", clone))
        if isinstance(db, dict) and db.get("remote"):
            remotes.append((at + "issue_db.remote", str(db["remote"]).strip().rstrip("/").removesuffix(".git").lower()))
    for kind, items in (("work_dir", works), ("clone", clones), ("원격", remotes)):
        for i, (ka, va) in enumerate(items):
            for kb, vb in items[i + 1:]:
                if va == vb:
                    out.append(f"{kb}: {ka}와 같은 {kind}입니다(플랫폼마다 따로 둔다).")
    for kw, work in works:
        for kc, clone in clones:
            if _within(work, clone):
                out.append(f"{kw}: {kc}(clone)를 포함하거나 같습니다 — work_dir은 clone 밖에 둔다.")
    return out


def profiles(defaults: dict, user: dict | None = None, *, invalid_names: bool = False) -> dict[str, dict]:
    """사용자 config에 있는 **모든** 프로필의 실제 config `{이름: cfg}`(`TOP_PROFILE` 먼저). `enabled`와 무관하다 —
    guard·pre-push가 어느 플랫폼의 clone·work_dir이든 보호하도록. `invalid_names`면 이름이 잘못된 프로필
    (`platforms.oFono`·`platforms.android` 등)도 `"platforms.<이름>"` 키로 넣는다(guard: 보호는 넓을수록 안전)."""
    user = load_user() if user is None else user
    out = {TOP_PROFILE: merged(defaults, user)}
    profs = (user or {}).get("platforms")
    if isinstance(profs, dict):
        for name, prof in profs.items():
            if not isinstance(prof, dict):
                continue
            if isinstance(name, str) and _PLATFORM_NAME_RE.fullmatch(name) and name != TOP_PROFILE:
                out[name] = merged(defaults, user, platform=name)
            elif invalid_names:
                key = f"platforms.{name}"
                out[key] = _with_profile(merged(defaults, user), defaults, re.sub(r"[^A-Za-z0-9_-]", "_", str(name)), prof)
    return out


def profile_key(platform: str | None, key: str) -> str:
    """사용자 config에 쓸 키 경로: 기본 플랫폼이면 `key`, 그 밖이면 `platforms.<p>.<key>`. `PROFILE_KEYS` 밖이면 ValueError."""
    if not platform or platform == TOP_PROFILE:
        return key
    if key.split(".")[0] not in PROFILE_KEYS:
        raise ValueError(f"{key}는 플랫폼 프로필 키가 아닙니다 (허용: {', '.join(PROFILE_KEYS)}).")
    return f"platforms.{platform}.{key}"


def platform_of(cfg: dict) -> str:
    """`merged()` 결과의 플랫폼 이름."""
    return cfg.get("platform") or TOP_PROFILE


def pending_feedback_dir(cfg: dict) -> Path:
    """보류 피드백 폴더: 기본 플랫폼은 `<home>/pending-feedback`, 그 밖은 `<home>/pending-feedback-<p>`
    (다른 플랫폼 피드백이 다른 이슈 DB로 올라가지 않게)."""
    p = platform_of(cfg)
    return home() / ("pending-feedback" if p == TOP_PROFILE else f"pending-feedback-{p}")


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


def issue_db_path(defaults: dict, platform: str | None = None):
    """`dbpath.resolve`의 ③(사용자 config `issue_db.path`, 선택 플랫폼 프로필의 값)."""
    user = load_user()
    if not user:
        return None
    return get(user, profile_key(platform, "issue_db.path"))
