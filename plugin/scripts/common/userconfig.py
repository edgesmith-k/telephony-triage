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

플랫폼마다 따로인 사용자 수준 키(`PLATFORM_SCOPED_KEYS`, 지금 `analyzers` — 17-platforms §10): 최상위 키는 기본 플랫폼 것이고,
그 밖 플랫폼은 site-defaults `platforms.<p>.<키>` 위에 사용자 config `platforms.<p>.<키>`를 얹은 것만 쓴다(기본 플랫폼 값을
**물려받지 않는다** — 다른 플랫폼에 Android 분석 스킬을 제안하지 않게).
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
PLATFORM_ENV = "TT_PLATFORM"   # = `platforms.ENV` (common은 platforms를 import하지 않는다, 테스트가 같은지 본다)
FILENAME = "config.yaml"
# 최상위 키 = 이 플랫폼의 프로필 (`platforms.DEFAULT_NAME`과 같아야 한다, 테스트로 확인)
TOP_PROFILE = "android"
# 플랫폼별 경로 프로필 키. `platforms.<p>`에는 이 키만 둘 수 있다
PROFILE_KEYS = ("issue_db", "work_dir", "log_dir", "code_profiles", "recent_code_roots")
# 플랫폼마다 따로 두고 기본 플랫폼 값을 물려받지 않는 사용자 수준 키(경로 프로필이 아니다). site-defaults `platforms.<p>`와
# 사용자 config `platforms.<p>`에 둘 수 있다. `PROFILE_KEYS`에 넣지 않는다 — 최상위 `PROFILE_KEYS`는 "기본 플랫폼 프로필이 있다"는
# 뜻이다(`_raw_profiles`·config init). 기본값으로 대신하는(override-with-fallback) 키가 생기면 다른 튜플로 둔다(17 §8 tracker)
PLATFORM_SCOPED_KEYS = ("analyzers",)
_PLATFORM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def home() -> Path:
    env = os.environ.get(HOME_ENV)
    return Path(env).expanduser() if env else Path.home() / ".telephony-triage"


def path() -> Path:
    return home() / FILENAME


def builtin() -> dict:
    return {
        "issue_db": {"base_branch": "main"},
        "tracker": {"tools": {}, "read_tools": [], "field_map": {}},
        "logcat": {"year_source": "tracker"},
        "code_profiles": [],
        "recent_code_roots": [],
        "work_dir": str(home() / "work"),
    }


def from_site_defaults(defaults: dict) -> dict:
    """site-defaults.yaml 값을 사용자 config 키 공간으로 옮긴 것.

    `issue_db.merge_wait_seconds`(`db_pr merge` 검사 대기 기본값)는 옮긴다. 없어진 `issue_db.merge`는 옮기지 않는다(`removed_keys`가
    경고). issue_db.base_branch·work_dir는 옮기지 않는다 — 이슈 DB `.githooks/pre-push`가 사용자 config에서 이 두 값을 직접 읽고
    (기본 main·<home>/work) site-defaults를 보지 않으므로, 팀 기본값으로 지원하려면 pre-push도 같이 바꾼다."""
    out: dict = {}
    tracker = defaults.get("tracker") or {}
    if tracker:
        out["tracker"] = {k: copy.deepcopy(v) for k, v in tracker.items()}
    if defaults.get("logcat"):
        out["logcat"] = copy.deepcopy(defaults["logcat"])
    if defaults.get("analyzers"):   # 분석 스킬은 site-defaults 또는 사용자 config (16-existing-assets.md §16.5)
        out["analyzers"] = copy.deepcopy(defaults["analyzers"])
    if defaults.get("explore"):     # 탐색 분석(Step 5-2) 기본값 (07-workflow.md §Step 5-2)
        out["explore"] = copy.deepcopy(defaults["explore"])
    if defaults.get("failed_step"):  # 실패 스텝 앵커 설정(마커 패턴 포함, 07-workflow.md §Step 3)
        out["failed_step"] = copy.deepcopy(defaults["failed_step"])
    if defaults.get("module_skills"):   # 모듈 스킬 레포 (MODULE_SKILLS_PLAN_IMPL §2.1). 최상위 공통 키
        out["module_skills"] = copy.deepcopy(defaults["module_skills"])
    ghe = defaults.get("ghe") or {}
    if ghe.get("host"):
        out.setdefault("issue_db", {})["ghe_host"] = ghe["host"]
    site_db = site_issue_db(defaults)
    if site_db:   # db_pr merge 검사 대기 기본값(merge_wait_seconds, 06-collaboration.md §6.1). 사용자 config가 덮는다
        out.setdefault("issue_db", {}).update(site_db)
    return out


SITE_ISSUE_DB_KEYS = ("merge_wait_seconds", "remote")
# 플랫폼마다 다른 키(플랫폼마다 이슈 DB가 다르다): 기본 아닌 플랫폼은 최상위(android) 값을 물려받지 않고
# site `platforms.<p>.issue_db`에서만 받는다. 그 밖 키(merge_wait_seconds)는 최상위 → platforms.<p> 순으로 덮는다
SITE_ISSUE_DB_PLATFORM_ONLY = ("remote",)
SITE_ADMIN = "(site-defaults는 관리자)"
# 없어진 키(+1 병합, H A2). 읽지 않고 config.py check·doctor가 경고만 한다 — legacy_problems(fail-closed)에는 넣지 않는다
REMOVED_ISSUE_DB_KEYS = ("merge",)


def site_issue_db(defaults: dict, platform: str | None = None) -> dict:
    """site-defaults `issue_db`의 `SITE_ISSUE_DB_KEYS`(있는 것만). 기본 아닌 `platform`이면 `SITE_ISSUE_DB_PLATFORM_ONLY`는
    최상위 것을 버리고 `platforms.<p>.issue_db`의 값으로 덮는다. 값 검사는 쓰는 쪽(`dbpr.merge`·`remote_problems`)이 한다."""
    db = defaults.get("issue_db") if isinstance(defaults.get("issue_db"), dict) else {}
    out = {k: db[k] for k in SITE_ISSUE_DB_KEYS if db.get(k) is not None}
    if platform and platform != TOP_PROFILE:
        for k in SITE_ISSUE_DB_PLATFORM_ONLY:
            out.pop(k, None)
        out.update(_site_platform_issue_db(defaults, platform))
    return out


def _site_platform_issue_db(defaults: dict, platform: str) -> dict:
    """site-defaults `platforms.<p>.issue_db`의 `SITE_ISSUE_DB_KEYS`(있는 것만). 모양이 틀리면 빈 dict(검사는 `site_platform_problems`)."""
    block = defaults.get("platforms") if isinstance(defaults, dict) else None
    block = block.get(platform) if isinstance(block, dict) else None
    db = block.get("issue_db") if isinstance(block, dict) else None
    return {k: db[k] for k in SITE_ISSUE_DB_KEYS if db.get(k) is not None} if isinstance(db, dict) else {}


def removed_keys(defaults: dict | None, user: dict | None) -> list[str]:
    """없어진 설정 키 경고: site-defaults `issue_db.merge`, 사용자 config 최상위 `issue_db.merge`와 `platforms.<p>.issue_db.merge`.
    값은 무시한다(동작에 영향 없음). 예외를 내지 않는다."""
    out: list[str] = []
    blocks: list[tuple[str, str, object]] = [
        ("site-defaults", "", defaults.get("issue_db") if isinstance(defaults, dict) else None)]
    if isinstance(user, dict):
        blocks.append(("사용자 config", "", user.get("issue_db")))
        profs = user.get("platforms") if isinstance(user.get("platforms"), dict) else {}
        blocks += [("사용자 config", f"platforms.{name}.", prof.get("issue_db"))
                   for name, prof in profs.items() if isinstance(prof, dict)]
    for where, at, block in blocks:
        for key in REMOVED_ISSUE_DB_KEYS:
            if isinstance(block, dict) and key in block:
                out.append(f"{where}: 옛 키 `{at}issue_db.{key}`는 +1 병합으로 없어졌다(무시한다) — 그 줄을 지운다"
                           + (" (관리자)" if where == "site-defaults" else ""))
    return out


def legacy_problems(defaults: dict | None, user: dict | None) -> list[str]:
    """옛 설정 키(jira → tracker 개명 전 형식). 자동 변환하지 않고 감지만 한다 — 옛 `jira:`를 조용히 무시하면 guard 규칙 2의
    설정 서버가 비어 이름 휴리스틱 밖 서버의 쓰기가 열리므로, 하나라도 있으면 호출자가 fail-closed로 멈춘다."""
    out: list[str] = []
    for where, data in (("site-defaults", defaults), ("사용자 config", user)):
        if not isinstance(data, dict):
            continue
        if "jira" in data:
            out.append(f"{where}: 옛 키 `jira:` → `tracker:`로 바꾼다 (+ `kind: jira`).")
        logcat = data.get("logcat")
        if isinstance(logcat, dict) and logcat.get("year_source") == "jira":
            out.append(f"{where}: `logcat.year_source: jira` → `tracker`로 바꾼다.")
        fmap = data.get("tracker", {}).get("field_map") if isinstance(data.get("tracker"), dict) else None
        if isinstance(fmap, dict) and "android_version" in fmap:
            out.append(f"{where}: `tracker.field_map.android_version` → `platform_version`로 바꾼다.")
        if where == "사용자 config":
            for _name, at, prof in _raw_profiles(data):
                items = prof.get("code_profiles")
                for i, item in enumerate(items if isinstance(items, list) else []):
                    if isinstance(item, dict) and "android_version" in item:
                        out.append(f"{where}: `{at}code_profiles[{i}].android_version` → `platform_version`로 바꾼다.")
    return out


def _rename_key(data: dict, old: str, new: str, value) -> dict:
    """`old` 자리에 `new`(값 `value`)를 넣은 새 dict(순서 유지, 기존 `new` 키는 뺀다)."""
    return {(new if k == old else k): (value if k == old else v) for k, v in data.items() if k != new}


def rename_legacy(user: dict | None) -> tuple[dict, list[str]]:
    """사용자 config의 옛 설정 키를 새 이름으로 바꾼 사본과 변경 목록 (`config.py rename-legacy`). 값은 그대로 둔다.
    `jira:` → `tracker:`(+`kind: jira`, `tracker:`가 이미 있으면 합치고 그 값이 우선), `logcat.year_source: jira` → `tracker`,
    `tracker.field_map.android_version` → `platform_version`, 프로필마다 `code_profiles[].android_version` → `platform_version`."""
    data = copy.deepcopy(user or {})
    changes: list[str] = []
    if "jira" in data:
        old = data["jira"] if isinstance(data["jira"], dict) else {}
        cur = data.get("tracker") if isinstance(data.get("tracker"), dict) else {}
        merged = {**old, **cur}
        merged = {"kind": merged.pop("kind", "jira"), **merged}
        data = _rename_key(data, "jira", "tracker", merged)
        changes.append("jira: → tracker: (+ kind: jira)" + (" — 기존 tracker: 값과 합침(tracker 값 우선)" if cur else ""))
    logcat = data.get("logcat")
    if isinstance(logcat, dict) and logcat.get("year_source") == "jira":
        logcat["year_source"] = "tracker"
        changes.append("logcat.year_source: jira → tracker")
    tracker = data.get("tracker")
    fmap = tracker.get("field_map") if isinstance(tracker, dict) else None
    if isinstance(fmap, dict) and "android_version" in fmap:
        value = fmap["android_version"]
        tracker["field_map"] = _rename_key(fmap, "android_version", "platform_version", fmap.get("platform_version", value))
        changes.append("tracker.field_map.android_version → platform_version")
    for _name, at, prof in _raw_profiles(data):
        items = prof.get("code_profiles")      # 같은 목록 객체(최상위 프로필은 얕은 사본)라 제자리에서 바꾼다
        for i, item in enumerate(items if isinstance(items, list) else []):
            if isinstance(item, dict) and "android_version" in item:
                items[i] = _rename_key(item, "android_version", "platform_version",
                                       item.get("platform_version", item["android_version"]))
                changes.append(f"{at}code_profiles[{i}].android_version → platform_version")
    return data, changes


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


def _site_platform(defaults: dict, platform: str) -> dict:
    """site-defaults `platforms.<p>` 중 `PLATFORM_SCOPED_KEYS`의 매핑 값(사본). 모양이 틀리면 빈 dict(검사는
    `site_platform_problems`)."""
    block = defaults.get("platforms") if isinstance(defaults, dict) else None
    block = block.get(platform) if isinstance(block, dict) else None
    if not isinstance(block, dict):
        return {}
    return {k: copy.deepcopy(block[k]) for k in PLATFORM_SCOPED_KEYS if isinstance(block.get(k), dict)}


def _with_profile(out: dict, defaults: dict, platform: str, prof) -> dict:
    """공통 키만 남긴 `out`에 플랫폼 경로 프로필(`prof`, `PROFILE_KEYS`만)과 그 기본값, 플랫폼 키(`PLATFORM_SCOPED_KEYS`:
    site `platforms.<p>` 위에 `prof`의 것)를 얹는다. 기본 플랫폼(최상위)의 플랫폼 키는 버린다."""
    for key in PROFILE_KEYS + PLATFORM_SCOPED_KEYS:
        out.pop(key, None)
    issue_db = {"base_branch": "main"}
    ghe = (defaults.get("ghe") or {}).get("host")
    if ghe:
        issue_db["ghe_host"] = ghe
    issue_db.update(site_issue_db(defaults, platform))
    out.update({"issue_db": issue_db, "work_dir": str(home() / f"work-{platform}"), "code_profiles": [],
                "recent_code_roots": []})
    out.update(_site_platform(defaults, platform))
    own = PROFILE_KEYS + PLATFORM_SCOPED_KEYS
    out = deep_merge(out, {k: v for k, v in (prof or {}).items() if k in own} if isinstance(prof, dict) else {})
    out["platform"] = platform
    return out


def selected_hint(user: dict | None) -> str | None:
    """사용자 config의 개인 기본 플랫폼(`platform`). 검증은 `platforms.select`."""
    value = (user or {}).get("platform")
    return value if isinstance(value, str) and value else None


def _scoped_problems(at: str, block: dict) -> list[str]:
    """`platforms.<p>`의 `PLATFORM_SCOPED_KEYS` 값 모양: `analyzers`는 `{카테고리: 매핑}`."""
    out = []
    for key in PLATFORM_SCOPED_KEYS:
        if key not in block:
            continue
        value = block[key]
        if not isinstance(value, dict):
            out.append(f"{at}.{key}: 매핑이어야 합니다({{카테고리: {{skill, when, source}}}}).")
            continue
        for cat, entry in value.items():
            if not isinstance(entry, dict):
                out.append(f"{at}.{key}.{cat}: 매핑이어야 합니다({{skill, when, source}}).")
    return out


def site_platform_problems(defaults: dict | None) -> list[str]:
    """site-defaults `platforms:`(기본 아닌 플랫폼의 사용자 수준 팀 기본값, 17-platforms §10) 오류: 매핑이 아님, 이름 형식,
    `TOP_PROFILE`(기본 플랫폼 것은 최상위 키), `PLATFORM_SCOPED_KEYS` 밖 키, 값 모양. 팀 원격(최상위 `issue_db.remote`·
    `platforms.<p>.issue_db.remote`)은 owner/repo로 풀려야 하고 서로 같으면 안 된다. 예외를 내지 않는다(guard 경로)."""
    if not isinstance(defaults, dict):
        return []
    out: list[str] = []
    remotes: list[tuple[str, str]] = []

    def take_remote(key: str, value) -> None:
        if value in (None, ""):
            return
        if repo_slug(value) is None:
            out.append(f"{key}: owner/repo로 풀리는 원격이어야 합니다: {value} {SITE_ADMIN}")
        remotes.append((key, _norm_remote(value)))

    take_remote("site-defaults issue_db.remote", site_issue_db(defaults).get("remote"))
    block = defaults.get("platforms")
    if not isinstance(block, dict):
        return out + (["site-defaults platforms: 매핑이어야 합니다."] if block is not None else [])
    allowed = PLATFORM_SCOPED_KEYS + ("issue_db",)
    for name, entry in block.items():
        at = f"site-defaults platforms.{name}"
        if not isinstance(name, str) or not _PLATFORM_NAME_RE.fullmatch(name):
            out.append(f"{at}: 플랫폼 이름이 아닙니다(소문자·숫자·_).")
        elif name == TOP_PROFILE:
            out.append(f"{at}: {TOP_PROFILE} 값은 최상위 키({', '.join(allowed)})에 둔다.")
        elif not isinstance(entry, dict):
            out.append(f"{at}: 매핑이어야 합니다.")
        else:
            out += [f"{at}.{key}: {MODULE_SKILLS_TOP_MSG}" if key == "module_skills" else
                    f"{at}.{key}: 둘 수 없는 키입니다 (허용: {', '.join(allowed)}. 플랫폼 상수는 "
                    f"platform.others.{name})." for key in entry if key not in allowed]
            out += _scoped_problems(at, entry)
            db = entry.get("issue_db", None)
            if db is not None and not isinstance(db, dict):
                out.append(f"{at}.issue_db: 매핑이어야 합니다({{{', '.join(SITE_ISSUE_DB_KEYS)}}}).")
            elif isinstance(db, dict):
                out += [f"{at}.issue_db.{k}: 둘 수 없는 키입니다 (허용: {', '.join(SITE_ISSUE_DB_KEYS)}. 경로는 사용자 config)."
                        for k in db if k not in SITE_ISSUE_DB_KEYS]
                take_remote(f"{at}.issue_db.remote", db.get("remote"))
    for i, (ka, va) in enumerate(remotes):
        out += [f"{kb}: {ka}와 같은 원격입니다(플랫폼마다 이슈 DB를 따로 둔다) {SITE_ADMIN}" for kb, vb in remotes[i + 1:] if va == vb]
    return out


def analyzer_sources(defaults: dict | None, user: dict | None) -> list[str]:
    """guard 규칙 12 보호 대상: site-defaults·사용자 config의 최상위 `analyzers`와 **모든** `platforms.<p>.analyzers`
    (이름이 잘못된 것도 — 보호는 넓을수록 안전)의 `source` 원본 문자열. 경로 검사·정규화는 호출자. 예외를 내지 않는다."""
    out: list[str] = []

    def take(analyzers) -> None:
        for entry in analyzers.values() if isinstance(analyzers, dict) else ():
            src = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(src, str) and src.strip():
                out.append(src)

    for data in (defaults, user):
        if not isinstance(data, dict):
            continue
        take(data.get("analyzers"))
        profs = data.get("platforms")
        for prof in profs.values() if isinstance(profs, dict) else ():
            if isinstance(prof, dict):
                take(prof.get("analyzers"))
    return out


def profile_problems(user: dict | None, defaults: dict | None = None) -> list[str]:
    """사용자 config의 플랫폼 키 오류: `platform`이 이름 형식이 아님, `platforms`가 매핑이 아님, 이름 형식·`TOP_PROFILE`,
    `platforms.<p>`에 `PROFILE_KEYS`·`PLATFORM_SCOPED_KEYS` 밖 키(RF-4), 플랫폼 키 값 모양, `path_problems`(`defaults`는
    물려받는 원격 겹침 비교용)."""
    user = user or {}
    out = []
    if "platform" in user and (not isinstance(user["platform"], str) or not _PLATFORM_NAME_RE.fullmatch(user["platform"])):
        out.append(f"platform: 플랫폼 이름이 아닙니다: {user['platform']!r}")
    profs = user.get("platforms")
    if profs is None:
        return out + path_problems(user, defaults)
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
                if key == "module_skills":
                    out.append(f"platforms.{name}.module_skills: {MODULE_SKILLS_TOP_MSG}")
                elif key not in PROFILE_KEYS + PLATFORM_SCOPED_KEYS:
                    out.append(f"platforms.{name}.{key}: 플랫폼 프로필에 둘 수 없는 키입니다 "
                               f"(허용: {', '.join(PROFILE_KEYS + PLATFORM_SCOPED_KEYS)}. "
                               "플랫폼 상수는 site-defaults에서만 바꾼다).")
            out += _scoped_problems(f"platforms.{name}", prof)
    return out + path_problems(user, defaults)


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


def repo_slug(value) -> tuple[str | None, str, str] | None:
    """원격 URL·레포 값을 `(host|None, owner, repo)`로(소문자, `.git` 제거). 꼴: `https://<host>/o/r(.git)`,
    `ssh://[<user>@]<host>[:port]/o/r`, git SCP 꼴 `[<user>@]<host>:o/r(.git)`(`://`가 없고 첫 `/` 앞에 `:`가 있다 — SSH 별칭
    host·숫자뿐인 owner(`ghe-ssh:1234/r.git`) 포함. `C:\\`·`C:/` 드라이브는 아니다), gh `-R`의 `HOST:PORT/OWNER/REPO`(user가 없고
    콜론 뒤가 숫자 칸 + 경로 칸 둘 이상일 때만 — 회귀 수정 R3: 숫자 owner의 SCP 꼴을 포트로 읽던 부류), `host/o/r`, `o/r`.
    로컬 경로·`file://`·형식 밖이거나 owner·repo에 `:`가 남으면 None. guard 규칙 11(이슈 DB 대상 비교)과 config 검사
    (`issue_db.remote`)가 같이 쓴다."""
    v = str(value).strip().rstrip("/")
    host = None
    colon, slash = v.find(":"), v.find("/")
    if "://" in v:
        scheme, _, rest = v.partition("://")
        if scheme.lower() == "file":
            return None
        netloc, _, path = rest.partition("/")
        host = netloc.rsplit("@", 1)[-1].split(":", 1)[0]
        parts = [p for p in path.split("/") if p]
    elif (colon > 0 and (slash < 0 or colon < slash) and not re.match(r"^[A-Za-z]:[\\/]", v) and "\\" not in v
          and ("@" in v[:colon] or not re.match(r"^\d+/[^/]+/[^/]", v[colon + 1:]))):
        # git SCP 꼴(git·gh 모두 `host:o/r`을 ssh로 읽는다 — `host:1234/r`의 1234는 owner다). user 없는 `host:8443/o/r`만 gh
        # `-R`의 `HOST:PORT/OWNER/REPO`(포트) 꼴로 아래에서 읽는다
        host = v[:colon].rsplit("@", 1)[-1]
        parts = [p for p in v[colon + 1:].split("/") if p]
    else:
        if v.startswith(("/", ".", "~")) or "\\" in v or re.match(r"^[A-Za-z]:", v):
            return None
        parts = [p for p in v.split("/") if p]
        if len(parts) >= 3:
            host, parts = parts[0], parts[1:]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or ":" in owner or ":" in repo:
        return None
    return (host.lower() if host else None, owner.lower(), repo.lower())


def remote_problems(defaults: dict | None, user: dict | None) -> list[tuple[str, str]]:
    """`issue_db.remote`가 owner/repo로 풀리지 않는(`repo_slug`) 프로필의 `(키, 값)`. 안 풀리면 guard 규칙 11(이슈 DB 원격 쓰기
    확인)이 그 프로필에 대해 조용히 꺼진다 — config 검사·doctor `config` 행·guard 경고가 쓴다."""
    out = []
    for name, cfg in (profiles(defaults or {}, user, invalid_names=True) if user else {}).items():
        remote = get(cfg, "issue_db.remote")
        if remote not in (None, "") and repo_slug(remote) is None:
            out.append(("issue_db.remote" if name == TOP_PROFILE else f"platforms.{name}.issue_db.remote", str(remote)))
    return out


def _norm_remote(value) -> str:
    """원격 겹침 비교용(`path_problems`·`site_platform_problems`): 공백·끝 `/`·`.git` 제거, 소문자."""
    return str(value).strip().rstrip("/").lower().removesuffix(".git")


SITE_REMOTE_TAG = "(site-defaults)"


def path_problems(user: dict | None, defaults: dict | None = None) -> list[str]:
    """프로필 경로 값 검사(guard 규칙 8의 제외 근거가 되므로): `work_dir`·`issue_db.path`는 비어 있지 않은 절대 경로(`~` 허용),
    어떤 work_dir도 어떤 clone을 포함하거나 같으면 안 된다, 프로필끼리 work_dir·clone·원격(`issue_db.remote`)이 겹치면 안 된다.
    `defaults`가 있으면 원격이 없는 프로필은 site-defaults에서 물려받는 원격(`site_issue_db`)으로 비교한다. 둘 다 물려받은
    원격끼리의 겹침은 site 문제라 여기서 내지 않는다(`site_platform_problems`)."""
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
            remotes.append((at + "issue_db.remote", _norm_remote(db["remote"])))
        elif isinstance(defaults, dict) and (team := site_issue_db(defaults, name).get("remote")):
            remotes.append((at + "issue_db.remote" + SITE_REMOTE_TAG, _norm_remote(team)))
    for kind, items in (("work_dir", works), ("clone", clones), ("원격", remotes)):
        for i, (ka, va) in enumerate(items):
            for kb, vb in items[i + 1:]:
                if va == vb and not (ka.endswith(SITE_REMOTE_TAG) and kb.endswith(SITE_REMOTE_TAG)):
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
    """사용자 config에 쓸 키 경로: 기본 플랫폼이면 `key`, 그 밖이면 `platforms.<p>.<key>`. `PROFILE_KEYS`·`PLATFORM_SCOPED_KEYS`
    밖이면 ValueError."""
    if not platform or platform == TOP_PROFILE:
        return key
    allowed = PROFILE_KEYS + PLATFORM_SCOPED_KEYS
    if key.split(".", maxsplit=1)[0] not in allowed:
        raise ValueError(f"{key}는 플랫폼 프로필 키가 아닙니다 (허용: {', '.join(allowed)}).")
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


def selected_name(defaults: dict | None, user: dict | None) -> str:
    """선택 플랫폼 **이름만**: `TT_PLATFORM` > 사용자 config `platform` > site-defaults `platform.name` > 기본.
    `--platform`(CLI)과 `platform.enabled` 검증은 호출부(`platforms.session`)가 한다 — `common`은 `platforms`를 모른다."""
    site = (defaults or {}).get("platform")
    site_name = site.get("name") if isinstance(site, dict) else None
    return os.environ.get(PLATFORM_ENV) or selected_hint(user) or (site_name if isinstance(site_name, str) and site_name
                                                                     else None) or TOP_PROFILE


def issue_db_path(defaults: dict, platform: str | None = None):
    """`dbpath.resolve`의 ③(사용자 config `issue_db.path`, 선택 플랫폼 프로필의 값). `platform`이 없으면
    `selected_name`(TT_PLATFORM > 사용자 config `platform` > site `platform.name`)의 프로필이다 — 비기본 플랫폼을 고른
    상태에서 android 프로필의 DB를 조용히 읽지 않게."""
    user = load_user()
    if not user:
        return None
    return get(user, profile_key(platform or selected_name(defaults, user), "issue_db.path"))


# ── 모듈 스킬 레포·분석 스킬 선택 (MODULE_SKILLS_PLAN_IMPL §2.1, B1 설계 §2·B2 설계 §9.1) ──────────────────────────────────
# `module_skills`는 최상위 공통 키(플랫폼별이 아니다 — 레포 하나 안에 <플랫폼>/이 있다). `builtin()`에 넣지 않는다(remote가 없으면
# `config.py show`가 그대로). `prefer`·`skill_dir`는 `analyzers.<cat>` 안(플랫폼별 그대로). 아래 함수는 guard 경로에서도 불리므로
# 잘못된 입력에 예외를 내지 않는다.
MODULE_SKILLS_KEYS = ("remote", "base_branch")
DEPRECATED_ANALYZER_KEYS = ("inputs", "max_tokens_hint")      # E가 skill_patch --apply를 없앨 때 "source"를 더한다
PREFER_VALUES = ("module", "skill")
MODULE_SKILLS_TOP_MSG = "최상위 키입니다(레포 하나 안에 <플랫폼>/이 있다) — platforms 밖 module_skills에 둔다."
REMOTE_FORM = ("https://<host>/<owner>/<repo>.git·ssh://[<user>@]<host>/<owner>/<repo>·<user>@<host>:<owner>/<repo>.git·"
               "file:///<절대 경로>")
BASE_BRANCH_RE = re.compile(r"^(?!-)(?!/)(?!.*\.\.)(?!.*//)(?!.*\.lock$)(?!.*/$)[A-Za-z0-9._/-]{1,100}$")
BASE_BRANCH_MSG = "브랜치 이름이어야 합니다(영문·숫자·._/-, '-'·'/'로 시작하지 않고 '..'·'//'·'.lock' 끝 없음)"
SKILL_DIR_MAX = 300
RUNTIME_LABEL_RE = re.compile(r"[A-Za-z0-9._ +-]{1,40}")
RUNTIME_LABEL_MSG = "runtime.label: 문자열(영숫자·._ +-, 40자 이하)이어야 합니다 — 출처 기록에서 뺀다"
_LAYERS = ("site-defaults", "사용자 config")


def module_skills(cfg: dict) -> dict | None:
    """`{"remote", "base_branch"}`(remote가 비어 있지 않을 때) 또는 None. 검사하지 않는다 — 호출자가 `module_skills_problems`를
    먼저 본다. base_branch 기본값 main은 여기에만 있다."""
    ms = cfg.get("module_skills") if isinstance(cfg, dict) else None
    if not isinstance(ms, dict):
        return None
    remote = ms.get("remote")
    if not isinstance(remote, str) or not remote.strip():
        return None
    base = ms.get("base_branch")
    return {"remote": remote.strip(), "base_branch": base.strip() if isinstance(base, str) and base.strip() else "main"}


def redact_remote(value) -> str:
    """원격 값을 보일 수 있는 꼴로: `host/owner/repo`(host가 없으면 `owner/repo`), `file://…/<마지막 조각>`, 그 밖은 userinfo를
    지우고 60자. 사용자 이름·비밀번호를 내지 않는다. 예외 없음."""
    try:
        v = str(value).strip()
        if v.lower().startswith("file://"):
            return "file://…/" + v.rstrip("/").rsplit("/", 1)[-1]
        slug = repo_slug(v)
        if slug:
            host, owner, repo = slug
            return f"{host}/{owner}/{repo}" if host else f"{owner}/{repo}"
        from . import masking   # 지연 import: guard가 userconfig를 매 hook마다 import한다
        return masking.URL_USERINFO.sub("://<CRED>@", re.sub(r"^[^@/:\s]+(:[^@/\s]*)?@", "<CRED>@", v))[:60]
    except Exception:
        return "<원격>"


def module_remote_problem(value) -> str | None:
    """원격 값 하나의 문제(설명 문구) 또는 None. 전송 방식이 드러난 꼴만 받는다(B1-18): `https://`·`ssh://`·SCP
    `[user@]host:o/r`·`file:///절대 경로`. 맨 `o/r`·`host/o/r`·상대·로컬 경로는 git이 로컬 경로로 읽으므로 오류."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return "문자열이어야 합니다."
    v = value.strip()
    r = redact_remote(value)
    form = f"{REMOTE_FORM} 중 하나여야 합니다: {r}"
    if not v or v.startswith("-") or re.search(r"[\s\x00-\x1f\x7f]", v):
        return form
    if "://" in v:
        scheme, _, rest = v.partition("://")
        scheme = scheme.lower()
        if scheme not in ("https", "ssh", "file"):
            return form
        if scheme == "file":
            return None if rest.startswith("/") else f"file:// 뒤는 절대 경로여야 합니다: {r}"
        netloc = rest.split("/", 1)[0]
        userinfo = netloc.rsplit("@", 1)[0] if "@" in netloc else ""
        if ":" in userinfo or (scheme == "https" and "@" in netloc):
            return f"주소에 자격 증명(user:token@)을 넣지 않는다 — git credential helper를 쓴다: {r}"
        slug = repo_slug(v)
        return None if slug and slug[0] else form
    colon, slash = v.find(":"), v.find("/")
    slug = repo_slug(v)
    if slug and slug[0] and colon > 0 and (slash < 0 or colon < slash) and "\\" not in v:
        return None
    return form


def _layer_blocks(defaults, user) -> list[tuple[str, str, str, object]]:
    """`(where, at, platform, analyzers)`: 두 층의 최상위와 **모든** `platforms.<p>.analyzers`(이름이 잘못된 것 포함)."""
    out: list[tuple[str, str, str, object]] = []
    for where, data in zip(_LAYERS, (defaults, user)):
        if not isinstance(data, dict):
            continue
        out.append((where, "", TOP_PROFILE, data.get("analyzers")))
        profs = data.get("platforms")
        for name, prof in profs.items() if isinstance(profs, dict) else ():
            if isinstance(prof, dict):
                out.append((where, f"platforms.{name}.", str(name), prof.get("analyzers")))
    return out


def _platform_names(defaults, user) -> list[str]:
    """`TOP_PROFILE` + 두 층의 `platforms`에 있는 올바른 이름(android 제외), 순서 유지."""
    names = [TOP_PROFILE]
    for data in (defaults, user):
        profs = data.get("platforms") if isinstance(data, dict) else None
        for name in profs if isinstance(profs, dict) else ():
            if isinstance(name, str) and _PLATFORM_NAME_RE.fullmatch(name) and name != TOP_PROFILE and name not in names:
                names.append(name)
    return names


def _merged_each(defaults, user):
    """`(platform, at, merged cfg)` — merged가 실패한 플랫폼은 건너뛴다."""
    d = defaults if isinstance(defaults, dict) else {}
    u = user if isinstance(user, dict) else {}
    for name in _platform_names(d, u):
        try:
            cfg = merged(d, u, platform=None if name == TOP_PROFILE else name)
        except Exception:
            continue
        yield name, ("" if name == TOP_PROFILE else f"platforms.{name}."), cfg


def module_skills_problems(defaults: dict | None, user: dict | None) -> list[str]:
    """`module_skills` 오류(층마다 + 합친 뒤 이슈 DB와 같은 레포). `platforms.<p>.module_skills`는 `profile_problems`·
    `site_platform_problems`가 따로 거부한다. 예외 없음."""
    out: list[str] = []
    try:
        for where, data in zip(_LAYERS, (defaults, user)):
            if not isinstance(data, dict) or data.get("module_skills") is None:
                continue
            ms = data["module_skills"]
            if not isinstance(ms, dict):
                out.append(f"{where} module_skills: 매핑이어야 합니다({{remote, base_branch}}).")
                continue
            out += [f"{where} module_skills.{k}: 모르는 키입니다 (허용: remote, base_branch)."
                    for k in ms if k not in MODULE_SKILLS_KEYS]
            prob = module_remote_problem(ms.get("remote"))
            if prob:
                out.append(f"{where} module_skills.remote: {prob}")
            b = ms.get("base_branch")
            if b is not None and (not isinstance(b, str) or not BASE_BRANCH_RE.fullmatch(b)):
                out.append(f"{where} module_skills.base_branch: {BASE_BRANCH_MSG}: {b!r:.60}")
        d = defaults if isinstance(defaults, dict) else {}
        u = user if isinstance(user, dict) else {}
        ms = module_skills(merged(d, u))
        mslug = repo_slug(ms["remote"]) if ms and not ms["remote"].lower().startswith("file://") else None
        if mslug:
            for cfg in profiles(d, u, invalid_names=True).values():
                r = get(cfg, "issue_db.remote")
                s = repo_slug(r) if isinstance(r, str) and r.strip() else None
                if s and s[1:] == mslug[1:]:
                    out.append(f"module_skills.remote: 이슈 DB 레포와 같다 — 모듈 스킬 레포는 따로 둔다: "
                               f"{redact_remote(ms['remote'])}")
                    break
    except Exception:
        pass
    return list(dict.fromkeys(out))


def skill_dir_problem(value) -> str | None:
    """`analyzers.<cat>.skill_dir` 값 하나의 문제(`config.py set` kind `path`와 같은 규칙) 또는 None. `~`는 허용."""
    ok = isinstance(value, str) and bool(value.strip()) and len(value) <= SKILL_DIR_MAX
    p = os.path.expanduser(value) if ok else ""
    if not ok or not os.path.isabs(p) or ".." in Path(p).parts:
        return f"설치 스킬 폴더의 절대 경로여야 합니다: {value!r:.60}"
    return None


def analyzer_problems(defaults: dict | None, user: dict | None, platform: str | None = None) -> list[str]:
    """`analyzers.<cat>`의 `prefer`·`skill_dir` 오류. 층마다: `prefer` 값, `skill_dir` 모양. 합친 뒤(플랫폼마다): `prefer: skill`
    인데 `skill`이 없음, `skill_dir`인데 `skill`이 없음. `platform`을 주면 그 플랫폼 블록 것만(`triage.py module`). 예외 없음."""
    found: list[tuple[str, str]] = []
    try:
        for where, at, pname, ana in _layer_blocks(defaults, user):
            for cat, entry in ana.items() if isinstance(ana, dict) else ():
                if not isinstance(entry, dict):
                    continue
                if "prefer" in entry and entry["prefer"] not in PREFER_VALUES:
                    found.append((pname, f"{where} {at}analyzers.{cat}.prefer: module 또는 skill이어야 합니다: "
                                         f"{entry['prefer']!r:.40}"))
                prob = skill_dir_problem(entry["skill_dir"]) if entry.get("skill_dir") is not None else None
                if prob:
                    found.append((pname, f"{where} {at}analyzers.{cat}.skill_dir: {prob}"))
        for pname, at, cfg in _merged_each(defaults, user):
            ana = cfg.get("analyzers") if isinstance(cfg.get("analyzers"), dict) else {}
            for cat, entry in ana.items():
                if not isinstance(entry, dict):
                    continue
                has_skill = isinstance(entry.get("skill"), str) and bool(entry["skill"].strip())
                if entry.get("prefer") == "skill" and not has_skill:
                    found.append((pname, f"{at}analyzers.{cat}.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다 — "
                                         "skill을 적거나 prefer를 지운다."))
                if entry.get("skill_dir") not in (None, "") and not has_skill:
                    found.append((pname, f"{at}analyzers.{cat}.skill_dir: skill(설치 스킬 이름)과 함께 쓴다."))
    except Exception:
        pass
    want = (platform or TOP_PROFILE) if platform is not None else None
    return list(dict.fromkeys(m for p, m in found if want is None or p == want))


def implicit_module_switches(defaults: dict | None, user: dict | None) -> list[str]:
    """B1-19 경고: 모듈 스킬 레포가 있고 어떤 카테고리에 `skill`이 있는데 `prefer`를 안 적었으면, 그 카테고리 5-1이 모듈
    문서로 바뀐다는 알림. 아무것도 막지 않는다. 예외 없음."""
    out: list[str] = []
    try:
        d = defaults if isinstance(defaults, dict) else {}
        u = user if isinstance(user, dict) else {}
        if not module_skills(merged(d, u)):
            return []
        for _p, at, cfg in _merged_each(d, u):
            ana = cfg.get("analyzers") if isinstance(cfg.get("analyzers"), dict) else {}
            for cat, entry in ana.items():
                skill = entry.get("skill") if isinstance(entry, dict) else None
                if isinstance(skill, str) and skill.strip() and "prefer" not in entry:
                    out.append(f"{at}analyzers.{cat}: 설치 스킬 {skill:.30} 대신 모듈 문서를 쓴다 — 계속 쓰려면 prefer: skill")
    except Exception:
        pass
    return list(dict.fromkeys(out))


def _analyzer_entry(cfg, category) -> dict:
    ana = cfg.get("analyzers") if isinstance(cfg, dict) and isinstance(cfg.get("analyzers"), dict) else {}
    conf = ana.get(category or "")
    return conf if isinstance(conf, dict) else {}


def deep_source(cfg: dict, category: str | None) -> dict:
    """Step 5-1 출처(Q2 바꿈, 11/05)의 유일한 구현. `cfg`는 그 플랫폼의 merged config.
    `{"source": "module"|"skill"|"none"|"error", "skill": str|None, "when": str}`. `when`은 보고만 한다."""
    conf = _analyzer_entry(cfg, category)
    skill = conf.get("skill") if isinstance(conf.get("skill"), str) and conf["skill"].strip() else None
    prefer, when = conf.get("prefer"), conf.get("when", "ask")
    if prefer is not None and prefer not in PREFER_VALUES:
        return {"source": "error", "skill": skill, "when": when}
    if prefer == "skill":
        return {"source": "skill" if skill else "error", "skill": skill, "when": when}
    if module_skills(cfg):
        return {"source": "module", "skill": None, "when": when}
    if skill:
        return {"source": "skill", "skill": skill, "when": when}   # 예전 Q2(remote 없음)
    return {"source": "none", "skill": None, "when": when}


def deep_source_problem(cfg: dict, category: str | None) -> str | None:
    """`deep_source(...)["source"] == "error"`의 사유(merged cfg만 보고). 그 밖이면 None. 예외 없음."""
    try:
        if deep_source(cfg, category)["source"] != "error":
            return None
        prefer = _analyzer_entry(cfg, category).get("prefer")
        if prefer not in PREFER_VALUES:
            return f"analyzers.{category}.prefer: module 또는 skill이어야 합니다: {prefer!r:.40}"
        return f"analyzers.{category}.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다"
    except Exception:
        return None


def module_remotes(defaults: dict | None, user: dict | None) -> list[str]:
    """guard 규칙 11 대상: 두 층의 최상위 `module_skills.remote`와 (잘못 둔) `platforms.<p>.module_skills.remote` 문자열.
    `""`·문자열 아님은 건너뛴다. 예외 없음."""
    out: list[str] = []
    for data in (defaults, user):
        if not isinstance(data, dict):
            continue
        profs = data.get("platforms")
        blocks = [data.get("module_skills")] + [p.get("module_skills") for p in
                                                 (profs.values() if isinstance(profs, dict) else ()) if isinstance(p, dict)]
        for ms in blocks:
            r = ms.get("remote") if isinstance(ms, dict) else None
            if isinstance(r, str) and r.strip():
                out.append(r)
    return out


def deprecated_keys(defaults: dict | None, user: dict | None) -> list[str]:
    """폐지 하위 키 경고(`analyzers.<cat>.inputs`·`max_tokens_hint`, 읽지 않는다). `legacy_problems`(fail-closed)에는 넣지
    않는다. 예외 없음."""
    out: list[str] = []
    for where, at, _p, ana in _layer_blocks(defaults, user):
        for cat, entry in ana.items() if isinstance(ana, dict) else ():
            for key in DEPRECATED_ANALYZER_KEYS:
                if isinstance(entry, dict) and key in entry:
                    out.append(f"{where}: 폐지 키 `{at}analyzers.{cat}.{key}`는 읽지 않는다(무시) — 그 줄을 지운다"
                               + (" (관리자)" if where == "site-defaults" else ""))
    return out


def runtime_problems(defaults: dict | None) -> list[str]:
    """site-defaults 전용 키 `runtime.label`(출처 기록, B2 §9.3) 경고. 오류가 아니다(그 값을 출처 기록에서 뺄 뿐). 예외 없음."""
    rt = defaults.get("runtime") if isinstance(defaults, dict) else None
    if rt is None:
        return []
    label = rt.get("label") if isinstance(rt, dict) else 0
    if label is None or (isinstance(label, str) and RUNTIME_LABEL_RE.fullmatch(label)):
        return []
    return [RUNTIME_LABEL_MSG]


def read_roots(cfg: dict, plugin_root: Path) -> list[str]:
    """OpenCode `external_directory` 허용 목록(B2-21): 플러그인 스킬 폴더, `work_dir`, 풀린 설치 스킬 `SKILL.md`의 폴더마다.
    순서 유지·중복 제거. 예외 없음."""
    out: list[str] = []
    try:
        out.append(os.path.abspath(str(Path(plugin_root) / "skills" / "telephony-triage")))
        work = cfg.get("work_dir") if isinstance(cfg, dict) else None
        if isinstance(work, str) and work.strip():
            out.append(os.path.abspath(os.path.expanduser(work)))
        from . import skillpath   # 지연 import: guard가 userconfig를 매 hook마다 import한다
        ana = cfg.get("analyzers") if isinstance(cfg, dict) and isinstance(cfg.get("analyzers"), dict) else {}
        for cat, entry in ana.items():
            if isinstance(entry, dict) and isinstance(entry.get("skill"), str) and entry["skill"].strip():
                base = skillpath.resolve(cfg, cat).get("base")
                if base:
                    out.append(str(base))
    except Exception:
        pass
    return list(dict.fromkeys(out))
