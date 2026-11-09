#!/usr/bin/env python3
"""config.py — 사용자 config, 사내 기본값, 호환성 판정 (02-config.md §4·§5.3, contracts.md §3.2,
06-collaboration.md §6.4, 16-existing-assets.md §16.1).

설정 우선순위: 사용자 config(`~/.telephony-triage/config.yaml`) > 플러그인 `site-defaults.yaml` >
코드 내장 기본값. `site-defaults.yaml`이 없으면 모든 서브커맨드가 종료 코드 2로 멈춘다
("사내 기본값 없음"). `site-defaults.example.yaml`은 읽지 않는다.

서브커맨드
  show [--keys a,b.c]          해석된 설정 (우선순위 적용). --keys면 그 키 값만
                               `{user_config, values{키: 값}, missing[]}` (점 표기, 없는 키는 missing)
  site-defaults                site-defaults.yaml 내용
  init [--answers <json>]      config 생성 (setup 1). --answers가 없으면 stdin으로 항목별로 묻는다.
                               필수 항목도 팀 기본값이 있으면(site-defaults issue_db.remote) 비워도 된다(상속).
                               경로가 없으면 거부한다. 홈·work_dir은 권한 700.
                               답한 값만 저장(선택 항목은 팀 기본값과 다를 때만, 나머지는 site-defaults·내장 기본값 상속).
                               플랫폼은 --platform > TT_PLATFORM > site(개인 기본 `platform`은 보지 않는다).
                               기존 config에 그 플랫폼 프로필이 없으면 프로필 키만 물어 더하고, 있으면 --force로
                               다시 만든다(android는 입력한 항목만 갱신: --answers에 없는 키·Enter는 지금 값 유지,
                               빈 값·팀 기본값과 같은 답은 지워 상속, 그 밖 키는 유지). 새 config에 프로필 문제
                               (경로 규칙·겹침)·옛 설정 키·모르는 tracker.kind가 있으면 저장하지 않고 종료 2.
  set <key> <value>            값 하나 바꾸기 (경로 값은 존재 검증). module_skills.remote(https://<host>·ssh://<host>·<user>@<host>:o/r·
                               file:///절대 경로만, 자격 증명 거부)·module_skills.base_branch는 최상위 키(--platform 없이),
                               analyzers.<카테고리>.prefer(module|skill)·.skill_dir(절대 경로). 남은 모듈 스킬·분석 스킬
                               설정 문제는 module_problems와 stderr 경고 한 줄.
                               opencode.jira_read open|closed [--accept-error-bodies]: OpenCode Jira 읽기 관문(최상위 키).
                               open은 같은 OpenCode 버전·플러그인 지문·트래커/MCP 지문의 사내 확인 통과 기록(site_step.py runtime-check
                               opencode --jira)이 있을 때만, 오류 경로 행이 warn이면 --accept-error-bodies도. OpenCode 안
                               (TT_RUNTIME=opencode)에서는 거부(사용자가 터미널에서 연다)
  sync-scripts-path            plugin.scripts_path = ${CLAUDE_PLUGIN_ROOT}/scripts (setup 2, SessionStart hook)
  tracker-candidates [--mcp-config <json>...] [--opencode-config <json>...] [--tools-json <json>]
                               등록된 MCP 서버에서 tracker.tools·읽기 도구 후보 (setup 4). exclude_servers 적용.
                               stdio 서버는 하나씩 서버당 최대 10초(응답 즉시 종료·프로세스 그룹 종료). 서버마다
                               servers[].probe(stdio|tools-json|excluded|remote)·elapsed_ms·error, stderr에 진행 줄.
                               --tools-json의 서버는 이름 정규화(`jira.corp`=`jira_corp`)로 비교해 다시 띄우지 않는다.
                               OpenCode(계획 I O8): --opencode-config 또는 TT_RUNTIME=opencode면 opencode.json `mcp`(enabled·
                               command)도 읽고(OpenCode 안에서는 ~/.claude.json을 기본으로 읽지 않는다, enabled:false는
                               probe=disabled), --tools-json 이름을 `<서버>_<도구>`로 읽는다. 그 서버 항목에 source=opencode·
                               opencode_tools(세션 이름). 저장 이름은 그대로 mcp__<서버>__<도구>
  set-tracker --server <s> --get-issue <전체 이름> [--search-issues ..] [--get-comments ..] [--read-tools a,b]
                               사용자가 확인한 값을 저장. read_tools에 tracker.tools 값을 포함한다
  rename-legacy [--apply]      사용자 config.yaml의 옛 설정 키(jira:·year_source: jira·android_version)를 새 이름으로 바꾼다.
                               변경 목록만 보이고 `--apply`일 때만 쓴다. site-defaults의 옛 키는 안내만(관리자가 고친다)
  install-hooks [--db <path>]  git config core.hooksPath .githooks, 값이 정확히 .githooks인지 확인 (setup 5)
  check [--db <path>] [--for write|dry-run] [--roots]
                               호환성 판정: 플랫폼·signature_features·스키마·생성기 버전·파서 백엔드·외부 파서, (write면) gh 인증
                               → writable / push_allowed. `migrate/schema-v<N>` 브랜치는 버전을 보지 않는다.
                               warnings(없어진 키·폐지 키·설치 스킬 대신 모듈 문서·runtime.label). remote·prefer·
                               skill_dir가 있으면 deep_sources(카테고리별 5-1 출처). --roots면 read_roots[절대 경로]
  gh-status                    gh 인증 확인 (setup 9). 실패면 로그인 안내와 종료 코드 2.
                               login: site ghe.host의 로그인(setup 1 GHE 아이디 자동 감지, 그 호스트 줄이 없으면 null)
  doctor [--format json|markdown]
                               환경 점검 한 장(python·deps·config·clone·hook·guard 자가시험·Jira 매핑(tracker)·Jira 코멘트
                               도구(tracker_post)·gh·스냅샷·호환성·lock, 모듈 스킬 설정이 있을 때만 module_skills,
                               OpenCode 안(TT_RUNTIME=opencode)에서만 opencode_env(설정을 덮는 환경 변수)·jira_gate(Jira
                               읽기 관문 열림·닫힘과 마지막 사내 확인 요약, 닫힘이면 warn)). **읽기 전용**
                               (mkdir·fetch·lock·쓰기 없음). 행마다 ok|warn|fail|skip. fail이 있으면 종료 코드 1
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from common.versions import GENERATOR_VERSION, SCHEMA_VERSION  # noqa: E402

# 의존성(PyYAML 등)이 없으면 traceback 대신 안내하고 종료 2(자기 실행 불가)로 멈춘다 (`main`)
try:
    import adapters  # noqa: E402
    from common import compat, dbpath, ghcli, mcptools, session_lock, site_defaults, userconfig, yamlio  # noqa: E402
    from common import compiled as compiled_cache  # noqa: E402
    from common import issuepost  # noqa: E402
    import platforms  # noqa: E402
    from platforms import session as platform_session  # noqa: E402
    import trackers  # noqa: E402
    IMPORT_ERROR: ImportError | None = None
except ImportError as _exc:   # noqa: BLE001
    IMPORT_ERROR = _exc

SUPPORTED_SCHEMA = (SCHEMA_VERSION, SCHEMA_VERSION)  # (min, max), 06-collaboration.md §6.4
MIGRATE_BRANCH_RE = re.compile(r"^migrate/schema-v\d+$")
YEAR_SOURCES = ("tracker", "file-mtime", "ask")
TOOL_NAME_RE = re.compile(r"^mcp__(?P<server>[^_].*?)__(?P<tool>[^_].*)$")

# setup 1에서 묻는 항목: (키, 질문, 종류, 필수)
FIELDS = [
    ("user.ghe_id", "GHE 아이디", "text", True),
    ("issue_db.path", "이슈 DB 로컬 clone 경로 (없으면 만들 위치)", "clone-path", True),
    ("issue_db.remote", "이슈 DB 원격 URL", "remote", True),
    ("issue_db.base_branch", "base 브랜치", "text", False),
    ("issue_db.ghe_host", "GHE 호스트 (gh의 GH_HOST)", "text", False),
    ("tracker.timezone", "Jira 시각 타임존 (IANA)", "tz", False),
    ("logcat.timezone", "logcat 시각 타임존 (IANA)", "tz", False),
    ("logcat.year_source", "연도 결정 방식 (tracker | file-mtime | ask)", "year-source", False),
    ("log_dir", "logcat 기본 탐색 경로 (선택, 빈 값이면 건너뜀)", "dir", False),
    ("work_dir", "작업 디렉토리 (작업 계획·스냅샷·lock)", "work-dir", False),
]
PATH_KINDS = {"issue_db.path": "clone-path", "log_dir": "dir", "work_dir": "work-dir"}


class UsageError(Exception):
    pass


# -- 값 검사 ---------------------------------------------------------------------------


def validate(kind: str, value) -> str | None:
    """오류 메시지 또는 None."""
    if value in (None, ""):
        return None
    text = str(value)
    if kind in ("clone-path", "work-dir") and not os.path.isabs(os.path.expanduser(text)):   # userconfig._abs_path와 같다
        return f"절대 경로여야 합니다: {text}"
    if kind == "dir":
        return None if Path(text).expanduser().is_dir() else f"디렉토리가 없습니다: {text}"
    if kind == "clone-path":
        p = Path(text).expanduser()
        if p.exists() and not p.is_dir():
            return f"디렉토리가 아닙니다: {text}"
        if not p.exists() and not p.parent.is_dir():
            return f"상위 디렉토리가 없습니다: {p.parent}"
        return None
    if kind == "work-dir":
        p = Path(text).expanduser()
        return None if (p.is_dir() or p.parent.is_dir()) else f"상위 디렉토리가 없습니다: {p.parent}"
    if kind == "tz":
        from common import logtime

        try:
            logtime.get_tz(text)
        except ValueError as exc:
            return str(exc)
        return None
    if kind == "year-source":
        return None if text in YEAR_SOURCES else f"{' | '.join(YEAR_SOURCES)} 중 하나여야 합니다: {text}"
    if kind == "remote":     # guard 규칙 11이 대상 비교에 쓴다 — 못 풀면 규칙 11이 꺼진다
        return None if userconfig.repo_slug(text) else (
            f"owner/repo로 풀리는 원격이어야 합니다(https://<host>/<owner>/<repo>.git·git@<host>:<owner>/<repo>.git·"
            f"<SSH 별칭>:<owner>/<repo>.git): {text}")
    if kind == "module-remote":     # 전송 방식이 드러난 꼴만(B1-18). 메시지에 자격 증명을 내지 않는다
        return userconfig.module_remote_problem(value if isinstance(value, str) else text)
    if kind == "ref":
        return None if userconfig.BASE_BRANCH_RE.fullmatch(text) else f"{userconfig.BASE_BRANCH_MSG}: {text!r:.60}"
    if kind == "prefer":
        return None if text in userconfig.PREFER_VALUES else f"module 또는 skill이어야 합니다: {text}"
    if kind == "path":              # analyzers.<cat>.skill_dir (B2 §9.1)
        return userconfig.skill_dir_problem(text)
    return None


def _default_for(key: str, defaults: dict, platform: str | None = None):
    return userconfig.get(userconfig.merged(defaults, {}, platform=platform), key)


def _platform(args) -> str:
    """main이 정한 선택 플랫폼(`--platform` > TT_PLATFORM > 사용자 config > site)."""
    return getattr(args, "platform_name", None) or userconfig.TOP_PROFILE


def _other(args) -> bool:
    return _platform(args) != userconfig.TOP_PROFILE


# -- 서브커맨드 ---------------------------------------------------------------------------


def _unset(data: dict, dotted: str) -> None:
    """키를 지우고 비게 된 상위 매핑도 지운다(팀 기본값 상속)."""
    parts = dotted.split(".")
    chain = [data]
    for part in parts[:-1]:
        node = chain[-1].get(part)
        if not isinstance(node, dict):
            return
        chain.append(node)
    chain[-1].pop(parts[-1], None)
    for i in range(len(parts) - 2, -1, -1):
        if chain[i + 1] == {}:
            chain[i].pop(parts[i], None)


def cmd_init(args, defaults: dict) -> dict:
    existing = userconfig.load_user()
    if existing is not None and existing.get("platforms") is not None and not isinstance(existing["platforms"], dict):
        raise UsageError("platforms: 매핑이어야 합니다 — config.py show로 확인하고 고친다")
    platform = _platform(args)
    other = _other(args)
    has_top = existing is not None and any(k in existing for k in userconfig.PROFILE_KEYS)
    if other and existing is not None:
        # 기본 아닌 플랫폼: 기존 config에 그 플랫폼의 경로 프로필(`platforms.<p>`)만 더한다(Jira·gh 설정은 공유).
        # config가 없으면 공통 키(최상위)와 `platforms.<p>`를 함께 만든다(android 최상위 프로필 없이 — 따로 설치)
        if (existing.get("platforms") or {}).get(platform) is not None and not args.force:
            raise UsageError(f"플랫폼 {platform} 프로필이 이미 있습니다 (바꾸려면 set --platform {platform}, 다시 만들려면 --force)")
    elif has_top and not args.force:
        raise UsageError(f"config가 이미 있습니다: {userconfig.path()} (바꾸려면 set, 다시 만들려면 --force)")
    fresh = existing is None
    # 기존 config에 프로필만 더한다: 다른 플랫폼, 또는 최상위(android) 프로필이 없는 config(다른 플랫폼 먼저 설치)
    profile_only = not fresh and (other or not has_top)
    fields = [f for f in FIELDS if not profile_only or f[0].split(".")[0] in userconfig.PROFILE_KEYS]
    # 기존 프로필 위에 다시 만들 때(android 기존 config, 다른 플랫폼 --force)는 입력한 항목만 갱신한다:
    # --answers에 없는 키·Enter는 지금 값 유지, 빈 값·`-`·팀 기본값과 같은 답은 지워 상속
    old_prof = (existing.get("platforms") or {}).get(platform) if other and not fresh else None
    keep = not fresh and (not other or isinstance(old_prof, dict))
    base = (old_prof if other else existing) if keep else {}     # 입력하지 않은 키의 출처
    current = userconfig.merged(defaults, existing, platform=platform) if keep else {}

    def has(key: str) -> bool:
        return keep and userconfig.get(base, key) not in (None, "")

    answers = {}
    if args.answers:
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
        errors = []
        for key, _, kind, required in fields:
            value = answers.get(key)
            # 필수 항목도 팀 기본값(site-defaults, 예: issue_db.remote)이 있으면 비워도 된다 — 저장하지 않고 상속한다
            team_has = _default_for(key, defaults, platform) not in (None, "")
            if required and value in (None, "") and not ((key not in answers and has(key)) or team_has):
                errors.append(f"{key}: 값이 필요합니다")
            elif (msg := validate(kind, value)):
                errors.append(f"{key}: {msg}")
        if errors:
            raise UsageError("config 값이 잘못됐습니다:\n  " + "\n  ".join(errors))
    else:
        for key, question, kind, required in fields:
            team = _default_for(key, defaults, platform)
            default = userconfig.get(current, key) if keep else team
            for _attempt in range(3):
                hint = f" [{default}]" if default not in (None, "", [], {}) else ""
                if keep and not required:   # Enter = 지금 값, `-` = 팀 기본값(키 삭제)
                    shown = team if team not in (None, "", [], {}) else "없음"
                    hint += f" (Enter=지금 값 유지, -=팀 기본값 {shown})"
                print(f"{question}{hint}: ", end="", file=sys.stderr, flush=True)
                line = sys.stdin.readline()
                if not line:
                    raise UsageError(f"{key}: 입력이 끝났습니다.")
                if keep and not line.strip() and (has(key) or not required):
                    break       # Enter = 지금 값 유지(답에 넣지 않는다)
                if keep and not required and line.strip() == "-":
                    answers[key] = ""       # 팀 기본값으로(키 삭제)
                    break
                value = line.strip() or (default if default not in ([], {}) else "")
                if required and not value:
                    print("  값이 필요합니다.", file=sys.stderr)
                    continue
                msg = validate(kind, value)
                if msg:
                    print(f"  거부: {msg}", file=sys.stderr)
                    continue
                answers[key] = value
                break
            else:
                raise UsageError(f"{key}: 올바른 값을 받지 못했습니다.")

    # 기존 config·프로필을 바탕으로 입력한 키만 바꾼다(그 밖 키·tracker.tools·plugin·platform·다른 platforms는 그대로)
    data: dict = {} if other or fresh else copy.deepcopy(existing)
    profile: dict = copy.deepcopy(old_prof) if other and keep else {}
    for key, _, _kind, required in fields:
        if key not in answers:
            continue
        value = answers[key]
        target = profile if other and key.split(".")[0] in userconfig.PROFILE_KEYS else data
        if value in (None, "") or value == _default_for(key, defaults, platform):
            _unset(target, key)   # 빈 답·팀 기본값과 같은 답(필수 항목 issue_db.remote도)은 저장하지 않는다(이후 팀 기본값 변경을 상속)
            continue
        userconfig.set_value(target, key, value)
    if other and not fresh:
        data = copy.deepcopy(existing)
        data["platforms"] = {**(existing.get("platforms") or {}), platform: profile}
    elif other:
        data["platforms"] = {platform: profile}
    if not profile_only:
        data.setdefault("plugin", {})["scripts_path"] = str(_plugin_root(args) / "scripts")
    # 저장 전에 새 config를 검사한다(경로 규칙·프로필끼리 겹침·옛 설정 키). 문제가 있으면 config 파일은 그대로 둔다
    legacy = userconfig.legacy_problems(None, data)
    problems = userconfig.profile_problems(data, defaults) + legacy
    if problems:
        raise UsageError("config를 저장하지 않았습니다 — " + "; ".join(problems)
                         + (" — config.py rename-legacy로 바꾼다" if legacy else ""))
    effective = userconfig.merged(defaults, data, platform=platform)
    team_remote = _default_for("issue_db.remote", defaults, platform)
    if team_remote and userconfig.get(effective, "issue_db.remote") == team_remote and (msg := validate("remote", team_remote)):
        # 물려받은 팀 원격도 검사한다 — 풀리지 않는 원격으로 clone을 제안하지 않는다
        raise UsageError(f"config를 저장하지 않았습니다 — issue_db.remote(site-defaults 팀 기본값): {msg} {userconfig.SITE_ADMIN}")
    try:     # 모르는 트래커면 저장하지 않는다(다른 스크립트가 모두 종료 2)
        trackers.kind_of(effective)
    except trackers.TrackerConfigError as exc:
        raise UsageError(f"config를 저장하지 않았습니다 — {exc} — 사용자 config의 tracker.kind를 고치거나 지운다"
                         "(config.py set tracker.kind <값> / 직접 편집)") from exc
    if keep:     # work_dir를 바꾸면 이전 작업은 옮기지 않는다 — 알리기만 한다
        old = Path(userconfig.get(current, "work_dir")).expanduser()
        try:
            jobs = [d for d in old.iterdir() if d.is_dir() and d.name[:1] not in ("_", ".")] if old.is_dir() else []
        except OSError:
            jobs = []
        if jobs and old != Path(userconfig.get(effective, "work_dir")).expanduser():
            print(f"경고: 이전 work_dir {old}에 작업 {len(jobs)}개가 남았다(옮기지 않는다)", file=sys.stderr)
    userconfig.ensure_private_dir(userconfig.home())
    userconfig.ensure_private_dir(Path(userconfig.get(effective, "work_dir")).expanduser())
    path = userconfig.save(data)
    clone = Path(userconfig.get(effective, "issue_db.path")).expanduser()
    return {"config": str(path), "clone_exists": clone.is_dir() and (clone / ".git").exists(),
            "suggest_clone": None if (clone / ".git").exists() else
            f"git clone {userconfig.get(effective, 'issue_db.remote')} {clone}"}


def _parse_value(text: str):
    import yaml

    from common import yamlio

    try:
        return yamlio.safe_load(text)
    except yaml.YAMLError:
        return text


def _set_opencode(args, data: dict) -> dict:
    """`set opencode.jira_read open|closed [--accept-error-bodies]` — OpenCode Jira 읽기 관문(`common/oc_jira_gate.py`). 사용자가
    터미널에서만 연다: OpenCode 안(`TT_RUNTIME=opencode`)이면 거부, open은 같은 OpenCode 버전·플러그인 지문·트래커/MCP 지문
    (`tracker_fingerprint`)의 사내 확인 통과 기록이 있을 때만, 그 기록의 오류 경로 행이 warn이면 `--accept-error-bodies`도 있어야
    한다. 최상위 키다(`--platform` 없이)."""
    from common import oc_jira_gate as gate

    command = gate.open_command(gate.PLUGIN_ROOT, getattr(args, "accept_error_bodies", False))
    if os.environ.get("TT_RUNTIME") == "opencode":
        raise UsageError(f"{args.key}: OpenCode 안에서는 바꾸지 않는다. 사용자가 터미널에서 직접 실행한다: {command}")
    if args.key != gate.SETTING:
        raise UsageError(f"{args.key}: 쓸 수 있는 OpenCode 키는 {gate.SETTING}(open|closed)뿐이다"
                         f"({gate.ACCEPT_SETTING}는 --accept-error-bodies로만 쓴다).")
    if getattr(args, "platform", None):
        raise UsageError(f"{args.key}: 최상위 키다 — --platform 없이 set한다.")
    value = str(args.value).strip()
    if value not in gate.VALUES:
        raise UsageError(f"{args.key}: open 또는 closed: {args.value!r}")
    accept = bool(getattr(args, "accept_error_bodies", False))
    if accept and value != gate.OPEN:
        raise UsageError("--accept-error-bodies는 opencode.jira_read open과 함께만 쓴다.")
    record, err = gate.load_record()
    if value == gate.OPEN:
        problems = [err] if err else gate.record_problems(record)
        if problems:
            raise UsageError(f"{args.key} open 거부: " + "; ".join(problems) + f". 먼저 사내 확인을 돌린다: {gate.CHECK_COMMAND}")
        if gate.needs_accept(record) and not accept:
            row = gate.error_row(record) or "없음"
            why = ("Jira 오류 응답 본문이 모델에 갔다 — 식별자 종류·개수는 통과 기록" if row == "warn"
                   else "오류 경로를 확인하지 않았다(--missing-key 없이 돌림)")
            raise UsageError(f"{args.key} open 거부: 사내 확인의 오류 경로 행이 {row}다({why}). 받아들이면 다시 실행한다: "
                             + gate.open_command(gate.PLUGIN_ROOT, True))
    userconfig.set_value(data, gate.SETTING, value)
    if accept:
        userconfig.set_value(data, gate.ACCEPT_SETTING, True)
    elif isinstance(data.get("opencode"), dict):
        data["opencode"].pop(gate.ACCEPT_SETTING.split(".", 1)[1], None)
    userconfig.save(data)
    return {"config": str(userconfig.path()), "key": gate.SETTING, "value": value, "accepted_error_bodies": accept,
            "check": gate.summary(record), "record": str(gate.record_path())}


def cmd_set(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 setup(config.py init)을 한다.")
    if args.key.split(".")[0] == "opencode":
        return _set_opencode(args, data)
    if getattr(args, "accept_error_bodies", False):
        raise UsageError("--accept-error-bodies는 opencode.jira_read open과 함께만 쓴다.")
    value = _parse_value(args.value)
    kind = PATH_KINDS.get(args.key) or ("tz" if args.key.endswith(".timezone") else
                                        "year-source" if args.key == "logcat.year_source" else
                                        "remote" if args.key == "issue_db.remote" else
                                        "module-remote" if args.key == "module_skills.remote" else
                                        "ref" if args.key == "module_skills.base_branch" else
                                        "prefer" if re.fullmatch(r"analyzers\.[a-z0-9_]+\.prefer", args.key) else
                                        "path" if re.fullmatch(r"analyzers\.[a-z0-9_]+\.skill_dir", args.key) else "")
    msg = validate(kind, value)
    if msg:
        raise UsageError(f"{args.key}: {msg}")
    if args.key.split(".")[0] in ("platform", "platforms"):
        raise UsageError(f"{args.key}: 플랫폼 키는 set --platform <이름> <프로필 키>로 쓴다(개인 기본 플랫폼은 config.yaml의 platform).")
    if args.key.split(".")[0] == "module_skills":
        # 최상위 공통 키 — 개인 기본 플랫폼이 android가 아니어도 최상위에 쓴다. 명시한 --platform만 거부한다
        if getattr(args, "platform", None):
            raise UsageError(f"{args.key}: 최상위 키다(레포 하나 안에 <플랫폼>/이 있다) — --platform 없이 set한다.")
        key = args.key
    else:
        try:
            key = userconfig.profile_key(_platform(args), args.key)
        except ValueError as exc:
            raise UsageError(f"--platform {_platform(args)}: {exc}") from exc
    before = userconfig.merged(defaults, copy.deepcopy(data), _platform(args))
    userconfig.set_value(data, key, value)
    userconfig.save(data)
    out = {"config": str(userconfig.path()), "key": key, "value": value}
    old_clone = userconfig.get(before, "issue_db.path")
    snap = Path(str(userconfig.get(before, "work_dir") or "")).expanduser() / "_snapshot"
    if args.key == "issue_db.path" and old_clone and str(old_clone) != str(value) and snap.exists():
        # 옛 읽기 스냅샷은 옛 clone의 worktree라 다음 snapshot이 거부한다(dbpr/worktree.py). 정리 방법 한 줄 (SITE_INSTALL.md 7절)
        out["hint"] = (f"옛 읽기 스냅샷 {snap}는 옛 clone의 worktree다: "
                       f"git -C {old_clone} worktree remove --force {snap} (옛 clone이 없으면 그 폴더를 지운다)")
        print("안내: " + out["hint"], file=sys.stderr)
    problems = userconfig.profile_problems(data, defaults)
    if problems:     # 저장은 한다(고치는 중일 수 있다). 남은 문제를 보인다 — 고치기 전까지 다른 스크립트는 종료 2
        out["problems"] = problems
        print("경고: 플랫폼 프로필 문제가 남았다 — " + "; ".join(problems), file=sys.stderr)
    mprobs = userconfig.module_skills_problems(defaults, data) + userconfig.analyzer_problems(defaults, data)
    if mprobs:       # 저장은 한다. triage.py module만 막고(종료 2) run은 막지 않는다(B1-13)
        out["module_problems"] = mprobs
        print("경고: 모듈 스킬·분석 스킬 설정 문제가 남았다 — " + "; ".join(mprobs), file=sys.stderr)
    return out


def _plugin_root(args) -> Path:
    root_opt = getattr(args, "plugin_root", None)
    return Path(root_opt) if root_opt else site_defaults.plugin_root()


def cmd_sync_scripts_path(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    scripts = str(_plugin_root(args) / "scripts")
    if data is None:
        return {"config": None, "scripts_path": scripts, "note": "config가 없어 기록하지 않았습니다 (setup 전)"}
    old = userconfig.get(data, "plugin.scripts_path")
    if old != scripts:
        userconfig.set_value(data, "plugin.scripts_path", scripts)
        userconfig.save(data)
    return {"config": str(userconfig.path()), "scripts_path": scripts, "changed": old != scripts}


def cmd_tracker_candidates(args, defaults: dict) -> dict:
    merged = userconfig.merged(defaults)
    exclude = list(userconfig.get(merged, "tracker.exclude_servers", []) or [])
    servers: dict[str, list[str] | None] = {}
    errors: dict[str, str] = {}
    probes: dict[str, dict] = {}     # 서버별 진단 {probe, elapsed_ms} (내용·자격증명 없음, 사내 보고용)
    # OpenCode(계획 I O8): `--opencode-config`가 있거나 OpenCode 안(`TT_RUNTIME=opencode`)이면 opencode.json `mcp`도 읽고,
    # --tools-json의 이름을 OpenCode 세션 이름(`<서버>_<도구>`)으로 읽는다. OpenCode 안에서는 Claude Code 설정(~/.claude.json)을
    # 기본으로 읽지 않는다(--mcp-config를 주면 읽는다).
    in_opencode = os.environ.get("TT_RUNTIME") == "opencode"
    oc_mode = bool(args.opencode_config) or in_opencode
    oc_names: set[str] = set()       # OpenCode에서 온 서버(출력에 source·opencode_tools를 더한다)
    if args.tools_json:
        for name, tools in json.loads(Path(args.tools_json).read_text(encoding="utf-8")).items():
            servers[name] = [mcptools.tool_part(name, t, opencode=oc_mode) for t in tools]
            probes[name] = {"probe": "tools-json", "elapsed_ms": 0}
            if oc_mode:
                oc_names.add(name)
    given = {mcptools.server_segment(n) for n in servers}     # `jira.corp`와 세션 이름 `jira_corp`는 같은 서버
    found: list[tuple[str, dict, bool]] = []
    if args.mcp_config or not in_opencode:
        configs = [Path(p) for p in args.mcp_config] if args.mcp_config else [Path.home() / ".claude.json"]
        found += [(name, conf, False) for name, conf in mcptools.load_servers(configs).items()]
    if oc_mode:
        oc_paths = ([Path(p) for p in args.opencode_config] if args.opencode_config
                    else mcptools.opencode_config_paths(os.getcwd()))
        try:
            found += [(name, conf, True) for name, conf in mcptools.load_opencode_servers(oc_paths).items()]
        except ValueError as exc:
            raise UsageError(str(exc)) from exc
    for name, conf, from_oc in found:
        if name in servers or mcptools.server_segment(name) in given:
            continue
        if from_oc:     # Claude Code 설정에 같은(정규화) 이름이 있으면 그쪽이 먼저다
            given.add(mcptools.server_segment(name))
            oc_names.add(name)
        if any(__import__("fnmatch").fnmatch(name, p) for p in exclude):
            servers[name] = None
            probes[name] = {"probe": "excluded", "elapsed_ms": 0}
            continue
        if from_oc and not conf.get("enabled", True):
            servers[name], errors[name] = None, "disabled: opencode.json enabled:false"
            probes[name] = {"probe": "disabled", "elapsed_ms": 0}
            continue
        if not (isinstance(conf, dict) and conf.get("command")):
            servers[name], errors[name] = None, mcptools.NOT_STDIO
            probes[name] = {"probe": "remote", "elapsed_ms": 0}
            continue
        # 진행 줄: 중간에 멈춰도 어느 서버에서 멈췄는지 남는다(서버 이름·시간·결과 종류만)
        print(f"[tracker-candidates] {name} 확인 중(최대 {mcptools.PROBE_TIMEOUT:g}초)", file=sys.stderr, flush=True)
        start = time.monotonic()
        try:
            servers[name] = mcptools.list_tools(conf)
            outcome = f"도구 {len(servers[name])}개"
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            servers[name] = None
            errors[name] = str(exc) if isinstance(exc, mcptools.ProbeError) else f"start-failed: {type(exc).__name__}: {exc}"
            outcome = errors[name].split(":", 1)[0]
        probes[name] = {"probe": "stdio", "elapsed_ms": int((time.monotonic() - start) * 1000)}
        print(f"[tracker-candidates] {name} {probes[name]['elapsed_ms']}ms {outcome}", file=sys.stderr, flush=True)
    team = userconfig.get(defaults, "tracker.tools", {}) or {}
    try:     # 후보 보강은 설정 트래커 어댑터(jira는 그대로)
        adapter = trackers.of(merged)
    except trackers.TrackerConfigError as exc:
        raise UsageError(str(exc)) from exc
    result = mcptools.candidates(servers, exclude, team, errors, adapter.classify_extra)
    for entry in result:
        entry.update(probes.get(entry["server"]) or {"probe": None, "elapsed_ms": 0})
        if entry["server"] in oc_names:     # OpenCode 세션에서 보이는 이름(저장은 tools의 전체 이름 그대로)
            seg = mcptools.server_segment(entry["server"])
            entry["source"] = "opencode"
            entry["opencode_tools"] = sorted(f"{seg}_{t.split('__', 2)[-1]}" for t in entry["tools"])
    usable = [s for s in result if not s["excluded"] and s["tracker_tools"].get("get_issue")]
    return {
        "exclude_servers": exclude,
        "servers": result,
        "usable": [s["server"] for s in usable],
        "next": ("사용자에게 서버와 tracker.tools·read_tools를 확인받고 config.py set-tracker로 저장한다"
                 if usable else "Jira MCP를 찾지 못했다. 사용자 범위(user scope)로 등록하는 방법을 안내하고 중단한다"),
    }


def _tool_problems(server: str, names: list[str]) -> list[str]:
    """도구 이름이 전체 이름이고 그 서버의 것인지 검사한 문제 목록 (set-tracker·doctor 공유). 서버는 정규화 비교."""
    problems = []
    for name in names:
        hit = TOOL_NAME_RE.match(str(name))
        if not hit:
            problems.append(f"도구 이름은 전체 이름(mcp__<server>__<tool>)이어야 합니다: {name}")
        elif mcptools.server_segment(hit.group("server")) != mcptools.server_segment(server):
            problems.append(f"{name}는 서버 {server}의 도구가 아닙니다.")
    return problems


def cmd_set_tracker(args, defaults: dict) -> dict:
    data = userconfig.load_user()
    if data is None:
        raise UsageError("config가 없습니다. 먼저 config.py init을 한다.")
    tools = {"get_issue": args.get_issue, "search_issues": args.search_issues, "get_comments": args.get_comments}
    tools = {k: v for k, v in tools.items() if v}
    read_tools = [t.strip() for t in (args.read_tools or "").split(",") if t.strip()]
    problems = _tool_problems(args.server, list(tools.values()) + read_tools)
    if problems:
        raise UsageError(problems[0])
    added = [t for t in tools.values() if t not in read_tools]
    read_tools = sorted(set(read_tools) | set(tools.values()))  # read_tools는 tracker.tools 값을 포함한다
    userconfig.set_value(data, "tracker.mcp_server", args.server)
    userconfig.set_value(data, "tracker.tools", tools)
    userconfig.set_value(data, "tracker.read_tools", read_tools)
    userconfig.save(data)
    return {"mcp_server": args.server, "tools": tools, "read_tools": read_tools, "added_to_read_tools": added}


def cmd_rename_legacy(args, defaults: dict) -> dict:
    """사용자 config의 옛 설정 키를 새 이름으로(값은 그대로). `--apply`가 없으면 쓰지 않는다. site-defaults는 안내만."""
    user = userconfig.load_user()
    site = userconfig.legacy_problems(defaults, None)
    out = {"config": str(userconfig.path()) if user is not None else None, "changes": [], "applied": False,
           "site_problems": site}
    if site:
        out["site_next"] = "site-defaults의 옛 키는 관리자가 고친다(플러그인 site-defaults.yaml, 키 이름만 바꾼다)"
    if user is None:
        return out
    data, changes = userconfig.rename_legacy(user)
    out["changes"] = changes
    if changes and args.apply:
        userconfig.save(data)
        out["applied"] = True
    out["remaining"] = userconfig.legacy_problems(None, data if out["applied"] else user)
    if changes and not args.apply:
        out["next"] = "변경 목록을 사용자에게 보이고 확인받은 뒤 config.py rename-legacy --apply"
    return out


def _git_out(repo: Path, *args: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip() if proc.returncode == 0 else None


def _hooks_value(db: Path) -> str | None:
    return _git_out(db, "config", "--get", "core.hooksPath")


def _gh_auth(defaults: dict) -> tuple[str | None, bool, str]:
    """(호스트, 인증 여부, 메시지) — check·gh-status·doctor 공유."""
    host = userconfig.get(userconfig.merged(defaults), "issue_db.ghe_host")
    ok, message = ghcli.auth_status(host)
    return host, ok, message


def _db(args, defaults: dict) -> Path:
    try:
        return dbpath.resolve(args.db, user_config_path=lambda: userconfig.issue_db_path(defaults, _platform(args)))
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc


def cmd_install_hooks(args, defaults: dict) -> dict:
    db = _db(args, defaults)
    proc = subprocess.run(["git", "-C", str(db), "config", "core.hooksPath", ".githooks"],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise UsageError(f"core.hooksPath 설정 실패: {proc.stderr.strip()}")
    value = _hooks_value(db)
    if value != ".githooks":
        raise UsageError(f"core.hooksPath가 '{value}'입니다. 정확히 .githooks여야 한다 (08-safety.md §9).")
    return {"db": str(db), "core.hooksPath": value}


def check(db: Path, defaults: dict, for_: str, platform: str | None = None) -> dict:
    cfg = compat.load_db_config(db)
    if not cfg:
        raise UsageError(f"이슈 DB 설정을 읽을 수 없습니다: {db}")
    platform = platform or userconfig.TOP_PROFILE
    branch = _git_out(db, "rev-parse", "--abbrev-ref", "HEAD")
    migrate = bool(branch and MIGRATE_BRANCH_RE.match(branch))
    reasons: list[dict] = compat.check_platform(cfg, platform)     # migrate 브랜치에서도 본다
    reasons += compat.check_features(cfg)                           # 모르는 시그니처 feature (driver는 중단)
    schema = cfg.get("schema_version")
    generator = cfg.get("generator_version")
    env = compiled_cache.environment(defaults, platform)
    if not migrate:
        if not isinstance(schema, int) or schema > SUPPORTED_SCHEMA[1]:
            reasons.append({"code": "schema-too-new", "message":
                            f"이슈 DB schema_version {schema}가 플러그인 지원 범위 {SUPPORTED_SCHEMA}보다 새롭다. "
                            "플러그인을 업데이트한다 (읽기 전용 분석만)."})
        elif schema < SUPPORTED_SCHEMA[0]:
            reasons.append({"code": "schema-too-old", "message":
                            f"이슈 DB schema_version {schema}가 플러그인 지원 범위 {SUPPORTED_SCHEMA}보다 옛 버전이다. "
                            "메인테이너에게 마이그레이션이 필요하다고 알린다."})
        if cfg.get("ci_mode", "local") != "actions-build" and generator != GENERATOR_VERSION:
            if isinstance(generator, int) and not isinstance(generator, bool) and generator < GENERATOR_VERSION:
                hint = f"메인테이너: migrate/schema-v{schema} 브랜치에서 migrate --to <현재 스키마>로 맞춘다."
            else:
                hint = "플러그인을 업데이트한다."
            reasons.append({"code": "generator-mismatch", "message":
                            f"generator_version {generator} ≠ 플러그인 {GENERATOR_VERSION}. 이슈 DB 쓰기 전체를 막는다. {hint}"})
        reasons += compat.check_parser_backend(cfg, env["backend"]["name"], str(env["backend"]["version"]))
        configured = {}
        # 외부 파서는 site 기본 플랫폼만 쓴다(그 밖 플랫폼은 다음 작업, 17-platforms)
        external = (defaults.get("external_parsers") or {}) if platform == platforms.default_name(defaults) else {}
        for category, conf in external.items():
            try:
                module = adapters.load((conf or {}).get("adapter"))
                configured[category] = {"adapter": module.ADAPTER_NAME,
                                        "version": (conf or {}).get("version") or module.VERSION, "available": True}
            except adapters.AdapterError:
                configured[category] = {"adapter": (conf or {}).get("adapter"), "available": False}
        reasons += compat.check_external(cfg, configured)
    writable = not reasons
    gh = {"checked": False, "ok": None, "host": None}
    if for_ == "write":
        host, ok, message = _gh_auth(defaults)
        gh = {"checked": True, "ok": ok, "host": host}
        if not ok:
            reasons.append({"code": "gh-auth", "message": f"gh 인증 없음 ({host}): gh auth login --hostname {host}"
                                                          f" 후 다시 시도한다. {message[:120]}"})
    push_allowed = writable and for_ == "write" and bool(gh["ok"])
    return {
        "db": str(db),
        "for": for_,
        "branch": branch,
        "migrate_branch": migrate,
        "writable": writable,
        "push_allowed": push_allowed,
        "read_only": not writable,
        "versions": {"schema": {"db": schema, "supported": list(SUPPORTED_SCHEMA)},
                     "generator": {"db": generator, "plugin": GENERATOR_VERSION},
                     "backend": env["backend"]},
        "gh": gh,
        "reasons": reasons,
    }


def _removed_key_warnings(defaults: dict, user: dict | None = None) -> list[str]:
    """없어진 설정 키(`userconfig.removed_keys`, 예: `issue_db.merge`) 경고. config를 못 읽으면 빈 목록(그 오류는 다른 곳이 보인다)."""
    try:
        return userconfig.removed_keys(defaults, userconfig.load_user() if user is None else user)
    except (OSError, ValueError, yamlio.YamlFileError):
        return []


def _user_or_none() -> dict | None:
    try:
        return userconfig.load_user()
    except (OSError, ValueError, yamlio.YamlFileError):
        return None


def _deprecated_key_warnings(defaults: dict, user: dict | None = None) -> list[str]:
    """폐지 하위 키(`userconfig.deprecated_keys`, `analyzers.<cat>.inputs`·`max_tokens_hint`) 경고. config를 못 읽으면 빈 목록."""
    return userconfig.deprecated_keys(defaults, _user_or_none() if user is None else user)


def _module_warnings(defaults: dict, user: dict | None) -> list[str]:
    """remote가 있는데 `prefer` 없이 `skill`이 있는 카테고리(B1-19)와 site `runtime.label` 모양(R23). 경고만."""
    return userconfig.implicit_module_switches(defaults, user) + userconfig.runtime_problems(defaults)


def _deep_sources(cfg: dict, defaults: dict, user: dict | None) -> dict | None:
    """카테고리별 5-1 출처(`userconfig.deep_source`). remote·`prefer`·`skill_dir`·분석 스킬 설정 문제 중 하나가 있을 때만
    (없으면 None — `check` 출력이 그대로). 원격 주소는 넣지 않는다."""
    ana = cfg.get("analyzers") if isinstance(cfg.get("analyzers"), dict) else {}
    keyed = any(isinstance(e, dict) and ("prefer" in e or "skill_dir" in e) for e in ana.values())
    if not (userconfig.module_skills(cfg) or keyed or userconfig.analyzer_problems(defaults, user)):
        return None
    out = {}
    for cat in sorted(ana, key=str):
        src = userconfig.deep_source(cfg, cat)
        out[str(cat)] = {k: v for k, v in src.items() if v is not None}
    star = userconfig.deep_source(cfg, None)
    out["*"] = {k: v for k, v in star.items() if v is not None}
    return out


def cmd_check(args, defaults: dict) -> tuple[dict, int]:
    result = check(_db(args, defaults), defaults, args.for_, _platform(args))
    ok = result["push_allowed"] if args.for_ == "write" else result["writable"]
    user = _user_or_none()
    # 경고만 — writable·push_allowed·종료 코드는 그대로
    result["warnings"] = (_removed_key_warnings(defaults, user) + _deprecated_key_warnings(defaults, user)
                          + _module_warnings(defaults, user))
    for warning in result["warnings"]:
        print(f"경고: {warning}", file=sys.stderr)
    cfg = userconfig.merged(defaults, user or {}, platform=_platform(args))
    sources = _deep_sources(cfg, defaults, user)
    if sources is not None:
        result["deep_sources"] = sources
    if getattr(args, "roots", False):    # OpenCode external_directory 허용 목록(B2-21). 플래그 없으면 키도 없다
        result["read_roots"] = userconfig.read_roots(cfg, _plugin_root(args))
    return result, (OK if ok else USAGE)


def cmd_gh_status(args, defaults: dict) -> tuple[dict, int]:
    host, ok, message = _gh_auth(defaults)
    # login: site ghe.host와 같은 호스트의 로그인만(setup 1 GHE 아이디 자동 감지). 다른 호스트뿐이면 None → setup이 묻는다
    result = {"host": host, "ok": ok, "login": ghcli.login(message, host) if ok else None}
    if not ok:
        result["message"] = (f"쓰기 불가(gh 인증 없음). `gh auth login --hostname {host}`로 로그인한다. "
                             "읽기 설정은 끝났으므로 읽기 전용 분석과 --dry-run 연습은 된다.")
    return result, (OK if ok else USAGE)


# -- doctor (읽기 전용 점검) -----------------------------------------------------------------

SNAPSHOT_STALE_DAYS = 7
DETAIL_MAX = 80
MIN_PYTHON = (3, 10)   # pyproject requires-python
GUARD_SELFTEST_TIMEOUT = 20


def _row(check: str, status: str, detail: str, next_: str | None = None) -> dict:
    row = {"check": check, "status": status, "detail": detail if len(detail) <= DETAIL_MAX else detail[:DETAIL_MAX - 1] + "…"}
    if next_:
        row["next"] = next_
    return row


GUARD_NEXT = "관리자에게 알린다(guard.py 직접 실행해 stderr 확인)"


def _guard_selftest(args, clone: Path | None, cfg: dict | None = None) -> dict:
    """guard.py에 거부돼야 할 hook 입력을 주고 응답 구조·결정을 본다: (1) 이름에 jira가 든 서버의 쓰기 도구(설정과
    무관하게 deny), (2) clone이 있으면 clone 파일 Write(deny), (3) 코멘트 도구 설정(`tracker.write_tools.add_comment`)이
    유효하면 승인 기록 없는 게시(deny). `cfg`는 site-defaults와 사용자 config를 합친 값(사용자 config가 없으면 site만)."""
    root = _plugin_root(args)
    home = str(Path.home())
    # hooks.json은 `python3`(PATH)로 guard를 부른다: 같은 해석기로 시험한다(의존성이 그 해석기에 있어야 한다)
    python = shutil.which("python3")
    other = python is not None and os.path.realpath(python) != os.path.realpath(sys.executable)
    python = python or sys.executable
    events = [{"hook_event_name": "PreToolUse", "tool_name": "mcp__probe-jira__jira_add_comment", "tool_input": {},
               "cwd": home}]
    if clone is not None:
        events.append({"hook_event_name": "PreToolUse", "tool_name": "Write",
                       "tool_input": {"file_path": str(clone / "README.md")}, "cwd": home})
    spec, _err = issuepost.write_spec(cfg or {})
    if spec:
        tracker = issuepost.spec_tracker(spec)
        events.append({"hook_event_name": "PreToolUse", "tool_name": spec["tool"], "cwd": home,
                       "tool_input": {**tracker.key_args(spec, tracker.selftest_key), spec["body_arg"]: "selftest"}})
    for event in events:
        try:
            proc = subprocess.run([python, str(root / "scripts" / "guard.py"), "--plugin-root", str(root)],
                                  input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=GUARD_SELFTEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return _row("guard", "fail", f"응답 없음 ({GUARD_SELFTEST_TIMEOUT}s 초과)", GUARD_NEXT)
        try:
            out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else {}
        except (ValueError, KeyError, TypeError):
            out = {}
        if proc.returncode != 0 or not isinstance(out, dict) or out.get("hookEventName") != "PreToolUse" \
                or out.get("permissionDecision") != "deny":
            got = out.get("permissionDecision") if isinstance(out, dict) else None
            return _row("guard", "fail", f"응답 구조 불일치: {event['tool_name']} 종료 {proc.returncode}·결정 {got or '없음'}",
                        GUARD_NEXT)
        reason = str(out.get("permissionDecisionReason") or "")
        if "의존성 없음" in reason or "내부 오류" in reason:   # 판정이 아니라 degraded 거부다
            return _row("guard", "fail", f"{'hook python3' if other else 'guard'}: {reason.removeprefix('[telephony-triage] ')}",
                        f"{python}에 pyproject 의존성을 설치한다" if "의존성 없음" in reason else GUARD_NEXT)
    return _row("guard", "ok", f"deny {len(events)}/{len(events)}" + (" (hook python3≠doctor python)" if other else ""))


def _doctor_rows(args, defaults: dict) -> list[dict]:
    """점검 행. 행 단위로 예외를 흡수한다(그 행 fail). 앞선 행이 실패하면 의존 행은 skip.
    아무것도 만들거나 바꾸지 않는다 (mkdir·fetch·lock·쓰기 없음)."""
    rows: list[dict] = []
    skip = lambda name, why: rows.append(_row(name, "skip", why))  # noqa: E731

    def guarded(name: str, func) -> None:
        try:
            func()
        except Exception as exc:    # noqa: BLE001 — 한 행의 실패가 표 전체를 막지 않는다
            rows.append(_row(name, "fail", f"점검 실패: {type(exc).__name__}: {exc}"))

    # 0 python·deps (config보다 먼저: 이것이 깨지면 나머지 판정이 무의미하다)
    if sys.version_info >= MIN_PYTHON:
        rows.append(_row("python", "ok", ".".join(map(str, sys.version_info[:3]))))
    else:
        rows.append(_row("python", "fail", ".".join(map(str, sys.version_info[:3])),
                         f"Python {'.'.join(map(str, MIN_PYTHON))}+ 를 설치한다"))

    def deps():
        # PyYAML이 없으면 config.py는 import에서 종료 2로 멈춘다(여기까지 오지 않는다). jsonschema만 따로 본다.
        import yaml
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            rows.append(_row("deps", "fail", "jsonschema 없음", "pyproject 의존성을 설치한다(pip install)"))
            return
        from importlib.metadata import version
        libyaml = "libyaml" if getattr(yaml, "CSafeLoader", None) else "pure"
        rows.append(_row("deps", "ok", f"PyYAML {yaml.__version__}({libyaml})·jsonschema {version('jsonschema')}"))
    guarded("deps", deps)

    # 1 config
    user, cfg = None, None
    try:
        user = userconfig.load_user()
        if user is None:
            rows.append(_row("config", "fail", "사용자 config 없음", "/telephony-triage:setup 을 실행한다"))
        else:
            cfg = userconfig.merged(defaults, user, platform=_platform(args))
            bad = userconfig.remote_problems(defaults, user)    # 못 풀면 guard 규칙 11이 그 이슈 DB에 꺼진다
            if bad:
                rows.append(_row("config", "fail", f"{bad[0][0]}를 owner/repo로 못 풀어 guard 규칙 11이 꺼진다",
                                 f"config.py set issue_db.remote https://<host>/<owner>/<repo>.git (지금 {bad[0][1]})"))
            elif _removed_key_warnings(defaults, user):    # 없어진 키(issue_db.merge)는 무시한다 — 경고만
                rows.append(_row("config", "warn", "옛 키 issue_db.merge(+1 병합으로 없어짐 — 무시한다)",
                                 "사용자 config에서 그 줄을 지운다 · site-defaults면 관리자"))
            elif _deprecated_key_warnings(defaults, user):    # 폐지 하위 키(B1 §3.1) — 읽지 않는다, 경고만
                rows.append(_row("config", "warn", "폐지 키 analyzers.<카테고리>.inputs·max_tokens_hint(무시)",
                                 "그 줄을 지운다 · site-defaults면 관리자"))
            elif userconfig.runtime_problems(defaults):      # site 전용 runtime.label(출처 기록) — 경고만
                rows.append(_row("config", "warn", userconfig.RUNTIME_LABEL_MSG, "site-defaults runtime.label을 고친다(관리자)"))
            else:
                rows.append(_row("config", "ok", "config.yaml 있음"))
    except Exception as exc:    # noqa: BLE001 — 읽기 실패도 한 행의 fail이다
        # init --force도 기존 파일을 먼저 읽으므로 손상 파일에서는 실패한다 → 파일을 옮긴 뒤 setup
        rows.append(_row("config", "fail", f"config 읽기 실패: {exc}",
                         f"손상된 {userconfig.path()}를 다른 이름으로 옮긴 뒤 /telephony-triage:setup 을 실행한다"))
    ok_cfg = cfg is not None

    # 1b platform — 켠 플랫폼이 둘 이상이거나 선택·프로필 오류가 있을 때만(기본 설치는 표가 이전과 같다)
    def platform_row():
        error = getattr(args, "platform_error", None) or "; ".join(getattr(args, "platform_problems", None) or [])
        on = platforms.enabled(defaults)
        if error:
            rows.append(_row("platform", "fail", error, f"{userconfig.path()}의 platform·platforms.<이름>을 고친다"))
        elif len(on) > 1:
            rows.append(_row("platform", "ok", f"{_platform(args)} (켠 플랫폼: {', '.join(on)})"))
    guarded("platform", platform_row)

    # 2 scripts_path
    def scripts_path():
        have = userconfig.get(cfg, "plugin.scripts_path")
        want = str(_plugin_root(args) / "scripts")
        if have == want:
            rows.append(_row("scripts_path", "ok", "플러그인 경로와 같음"))
        else:
            rows.append(_row("scripts_path", "warn", "config의 경로가 이 플러그인과 다름" if have else "scripts_path 비어 있음",
                             "새 세션을 시작하면 자동으로 맞춘다. 계속 다르면 관리자에게 알린다"))
    guarded("scripts_path", scripts_path) if ok_cfg else skip("scripts_path", "config 없음")

    # 3 clone
    repo_box: list = []

    def clone():
        raw = userconfig.get(cfg, "issue_db.path")
        if not raw:
            rows.append(_row("clone", "fail", "issue_db.path 비어 있음", "/telephony-triage:setup 에서 이슈 DB 경로(1번)를 다시 입력한다"))
            return
        repo = Path(str(raw)).expanduser()
        if (repo / ".git").exists():
            rows.append(_row("clone", "ok", f"{repo}"))
            repo_box.append(repo)
        else:
            remote = userconfig.get(cfg, "issue_db.remote")
            rows.append(_row("clone", "fail", "이슈 DB clone 없음", f"터미널에서 git clone {remote} {repo} 실행" if remote
                                 else "/telephony-triage:setup 3번(clone)을 다시 한다"))
    guarded("clone", clone) if ok_cfg else skip("clone", "config 없음")

    # 4 hook
    def hook():
        value = _hooks_value(repo_box[0])
        if value == ".githooks":
            rows.append(_row("hook", "ok", "core.hooksPath=.githooks"))
        else:
            rows.append(_row("hook", "fail", f"core.hooksPath={value or '(없음)'}", "setup 5번(hook)만 다시 — `config.py install-hooks`"))
    guarded("hook", hook) if repo_box else skip("hook", "clone 없음")

    # 4b guard 자가시험 (읽기 전용: guard는 판정만 한다)
    guarded("guard", lambda: rows.append(_guard_selftest(args, repo_box[0] if repo_box else None,
                                                         cfg if ok_cfg else userconfig.merged(defaults, {}, platform=_platform(args)))))

    # 5 tracker (매핑만 본다). 옛 설정 키(jira: 등)가 남아 있으면 fail — guard가 모든 MCP를 거부한다
    def tracker():
        legacy = userconfig.legacy_problems(defaults, user)
        if legacy:
            site = userconfig.legacy_problems(defaults, None)
            rows.append(_row("tracker", "fail", f"옛 설정 키: {legacy[0]}",
                             "config.py rename-legacy로 확인 후 --apply" + (" · site-defaults는 관리자에게 알린다" if site else "")))
            return
        try:     # tracker.kind 오류(모르는 트래커): guard가 모든 MCP를 거부한다
            trackers.kind_of(cfg)
        except trackers.TrackerConfigError as exc:
            rows.append(_row("tracker", "fail", str(exc), f"tracker.kind를 설치된 트래커({', '.join(trackers.known())}) 중 하나로 고친다"))
            return
        server = userconfig.get(cfg, "tracker.mcp_server")
        tools = userconfig.get(cfg, "tracker.tools", {})
        read_tools = userconfig.get(cfg, "tracker.read_tools", [])
        hint = "/telephony-triage:setup 4번(Jira MCP 매핑)을 다시 한다"
        if tools is None:
            tools = {}
        if read_tools is None:
            read_tools = []
        if not isinstance(tools, dict) or not isinstance(read_tools, list):
            rows.append(_row("tracker", "fail", "tracker.tools(매핑)·read_tools(목록) 형식 오류", hint))
            return
        names = [v for v in tools.values() if v] + read_tools
        if not server:
            rows.append(_row("tracker", "fail", "tracker.mcp_server 비어 있음", hint))
        elif not tools.get("get_issue"):
            rows.append(_row("tracker", "fail", "tracker.tools.get_issue 매핑 비어 있음", hint))
        else:
            problems = _tool_problems(str(server), names)
            if problems:
                rows.append(_row("tracker", "fail", problems[0], hint))
            else:
                rows.append(_row("tracker", "ok", f"{server} / get_issue 매핑 있음"))
    guarded("tracker", tracker) if ok_cfg else skip("tracker", "config 없음")

    # 5b tracker_post (승인 코멘트 도구 설정만 본다. 호출하지 않는다)
    def tracker_post():
        spec, problems = issuepost.spec_check(cfg)
        hint = "site-defaults 또는 config.py set tracker.write_tools.add_comment.*"
        if problems:
            level, why = problems[0]
            rows.append(_row("tracker_post", level, why, "read_tools에서 코멘트 도구를 뺀다" if level == "fail" else hint))
        elif spec is None:
            rows.append(_row("tracker_post", "skip", "게시 기능 꺼짐(본문 파일만)"))
        else:
            rows.append(_row("tracker_post", "ok", f"{spec['tool']} / {spec['format']}"))
    guarded("tracker_post", tracker_post) if ok_cfg else skip("tracker_post", "config 없음")

    # 6 gh
    def gh():
        host, ok, _message = _gh_auth(defaults)
        if ok:
            rows.append(_row("gh", "ok", f"인증됨 ({host})"))
        else:
            rows.append(_row("gh", "warn", f"gh 인증 없음 ({host}) — 쓰기 불가", f"터미널에서 gh auth login -h {host} 실행"))
    guarded("gh", gh) if ok_cfg else skip("gh", "config 없음")

    # 7 snapshot
    snap_box: list = []
    work_raw = userconfig.get(cfg, "work_dir") if ok_cfg else None
    work = Path(str(work_raw)).expanduser() if work_raw else None

    def snapshot():
        snap_dir = work / session_lock.SNAPSHOT_DIR
        if not (snap_dir / ".git").exists():
            rows.append(_row("snapshot", "warn", "읽기 스냅샷 없음", "/telephony-triage:sync 를 실행한다"))
            return
        snap_box.append(snap_dir)
        meta_path = work / session_lock.SNAPSHOT_META
        if not meta_path.is_file():
            rows.append(_row("snapshot", "warn", "시각 기록 없음 (나이 불명)", "/telephony-triage:sync 를 실행한다"))
            return
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            age = session_lock.now() - session_lock.parse(meta["at"])
            sha = str(meta.get("sha") or "")[:7]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            snap_box.clear()
            rows.append(_row("snapshot", "fail", f"{session_lock.SNAPSHOT_META} 손상: {type(exc).__name__}", "/telephony-triage:sync 를 실행한다"))
            return
        days = int(age.total_seconds() // 86400)
        if age > timedelta(days=SNAPSHOT_STALE_DAYS):
            rows.append(_row("snapshot", "warn", f"{days}일 전 ({sha}, {SNAPSHOT_STALE_DAYS}일 초과)", "/telephony-triage:sync 를 실행한다"))
        else:
            rows.append(_row("snapshot", "ok", f"{days}일 전 ({sha})"))
    if not ok_cfg:
        skip("snapshot", "config 없음")
    elif work is None:
        skip("snapshot", "work_dir 없음")
    else:
        guarded("snapshot", snapshot)

    # 7b retention (site-defaults `retention_days`, 14-site S14): 팀이 보존 기간을 정했을 때만 행이 생긴다(기본 점검표·예산 불변).
    # 기한 넘은 작업 폴더 수만 센다 — 지우지 않는다(종합 리뷰 G). site-defaults에서 직접 읽는다(merged는 알려진 키만 옮긴다)
    retention_days = userconfig.get(defaults, "retention_days")

    def retention():
        days = retention_days
        if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
            rows.append(_row("retention", "fail", f"retention_days 값이 잘못됨({days!r})", "site-defaults retention_days는 양의 정수(일) — 관리자"))
            return
        limit = time.time() - days * 86400
        # 나이 = 마지막 활동(폴더 안 파일·폴더의 가장 최근 mtime, wt·draft 제외) — cleanup --older-than과 같은 정의(R4)
        old = [p.name for p in work.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))
               and session_lock.JOB_KEY_RE.fullmatch(p.name) and any((p / m).exists() for m in session_lock.JOB_MARKERS)
               and session_lock.tree_mtime(p) < limit]
        if old:
            rows.append(_row("retention", "warn", f"마지막 활동 뒤 {days}일 넘은 작업 폴더 {len(old)}개(Jira 요약·마스킹 로그가 남아 있다)",
                             f"db_pr.py cleanup --older-than {days} --dry-run 으로 확인한 뒤 --yes (미게시 계획은 따로 알린다)"))
        else:
            rows.append(_row("retention", "ok", f"마지막 활동 뒤 {days}일 넘은 작업 폴더 없음"))
    if retention_days is not None:
        if ok_cfg and work is not None and work.is_dir():
            guarded("retention", retention)
        else:
            skip("retention", "config 없음" if not ok_cfg else "work_dir 없음")

    # 8 compat (<work_dir>/_snapshot 기준)
    if not snap_box:
        skip("compat", "스냅샷 없음")
    else:
        try:
            result = check(snap_box[0], defaults, "dry-run", _platform(args))
            if result["writable"]:
                rows.append(_row("compat", "ok", "스키마·생성기·파서 호환"))
            else:
                codes = ",".join(r["code"] for r in result["reasons"])
                rows.append(_row("compat", "fail", f"쓰기 막힘: {codes}", "플러그인을 업데이트하거나 관리자에게 사유를 알린다"))
        except Exception as exc:    # noqa: BLE001
            rows.append(_row("compat", "fail", f"판정 실패: {exc}"))

    # 9 lock
    if not ok_cfg:
        skip("lock", "config 없음")
    elif work is None:
        skip("lock", "work_dir 없음")
    else:
        try:
            held = session_lock.describe(session_lock.read(work))
            if held is None:
                rows.append(_row("lock", "ok", "세션 lock 없음"))
            else:
                mins = held["age_sec"] // 60
                state = "만료" if held["expired"] else "보유 중"
                rows.append(_row("lock", "warn", f"{state}: {held['job']} ({mins}분 전)",
                                 f"그 세션이 끝났는지 확인 → 끝났으면 db_pr lock release {held['job']} --force"))
        except Exception as exc:    # noqa: BLE001 — 손상 lock 포함
            rows.append(_row("lock", "fail", str(exc) or type(exc).__name__,
                             f"lock 파일 확인: {work / session_lock.LOCK_FILE} — 그 세션이 끝났으면 "
                             "db_pr lock release <작업 키> --force(.corrupt-<ts>로 백업 후 제거)"))

    # 10 module_skills — 모듈 스킬·분석 스킬 선택 설정이 있을 때만(기본 설치는 13행 그대로, B1 §3.2·§3.3)
    if ok_cfg and _module_row_wanted(cfg, defaults, user, work):
        guarded("module_skills", lambda: rows.append(_module_skills_row(cfg, defaults, user, work)))
    # 11 OpenCode 안(`TT_RUNTIME=opencode`)에서만: 설정을 덮는 환경 변수(`oc_adapter env-check`)와 Jira 읽기 관문(계획 I O8).
    # Claude Code에서는 행이 없다(기본 13행 그대로)
    if os.environ.get("TT_RUNTIME") == "opencode":
        guarded("opencode_env", lambda: rows.append(_opencode_env_row()))
        guarded("jira_gate", lambda: rows.append(_jira_gate_row()))
    return rows


def _opencode_env_row() -> dict:
    from common import oc_adapter   # 지연 import: OpenCode 안에서만

    bad = oc_adapter.refused_env()
    if bad:
        return _row("opencode_env", "fail", "설정을 덮는 환경 변수: " + ", ".join(bad),
                    "그 변수를 지우고 다시 실행한다(있으면 guard가 모든 도구를 거부한다)")
    return _row("opencode_env", "ok", "설정을 덮는 환경 변수 없음")


def _jira_gate_row() -> dict:
    """OpenCode Jira 읽기 관문(`common/oc_jira_gate.py`): 열림·닫힘과 마지막 사내 확인 요약(내용 없음)."""
    from common import oc_adapter, oc_jira_gate as gate

    if os.environ.get(oc_adapter.JIRA_GATE_ENV) == "open":
        return _row("jira_gate", "warn", f"시험 열림({oc_adapter.JIRA_GATE_ENV}=open — 테스트·사내 확인 전용)")
    st = oc_adapter.jira_gate_files()      # 설정·통과 기록 파일로 본 상태(다음 OpenCode 시작에 적용)
    last = gate.short_summary(st.record)
    reopen = f"사용자가 터미널에서: {gate.CHECK_COMMAND} → {gate.open_command()}"
    # 이 OpenCode 세션의 판정값(tt-guard.js가 시작할 때 정해 bash 환경에도 넘긴다). 파일과 다르면 그 차이를 먼저 보인다
    session = os.environ.get(oc_adapter.JIRA_SESSION_ENV)
    if session is not None and (session == "open") != st.open:
        if st.open:
            return _row("jira_gate", "warn", f"이 세션은 닫힘(설정·기록은 시작 뒤 열림으로 바뀜) — {last}",
                        "OpenCode를 다시 시작하면 열린다(관문은 시작 때 한 번만 본다)")
        return _row("jira_gate", "warn", f"이 세션은 열림(시작 때 판정), 다음 시작부터 닫힘 — {'; '.join(st.problems)}",
                    f"{gate.summary(st.record)}. 지금 닫으려면 OpenCode를 다시 시작한다")
    if st.open:
        return _row("jira_gate", "ok", f"열림{'(오류 본문 받아들임)' if st.accepted else ''} — {last}",
                    f"{gate.summary(st.record)}. 닫기: config.py set {gate.SETTING} closed")
    if st.setting == gate.OPEN:
        return _row("jira_gate", "warn", f"닫힘 — {'; '.join(st.problems)}",
                    f"{gate.summary(st.record)}. 사내 확인을 다시 돌린 뒤 {reopen}")
    return _row("jira_gate", "warn", f"닫힘({gate.SETTING}: {st.setting}) — Jira MCP 읽기 거부 — {last}",
                f"이슈 내용은 붙여 넣거나 Claude Code에서 분석한다. 열려면 {reopen}")


MODULE_SOURCE_LABEL = {"module": "모듈 문서", "skill": "설치 스킬", "none": "없음", "error": "오류"}
MODULE_CLONE_NAME = "_module-skills"     # = moduleskills.CLONE_DIR (모듈을 안 불러도 되는 행 조건에만 쓴다, 테스트가 같은지 본다)
SKILL_DIR_NOTE = ("skill_dir가 작업 폴더 밖이면 Claude Code가 읽기를 한 번 묻는다 — 사용자가 permissions.additionalDirectories에 "
                  "더할 수 있다 · OpenCode는 config.py check --roots")


def _has_skill_dir(defaults: dict, user: dict | None) -> bool:
    for data in (defaults, user):
        blocks = [data.get("analyzers")] if isinstance(data, dict) else []
        profs = data.get("platforms") if isinstance(data, dict) else None
        blocks += [p.get("analyzers") for p in (profs.values() if isinstance(profs, dict) else ()) if isinstance(p, dict)]
        for ana in blocks:
            if any(isinstance(e, dict) and "skill_dir" in e for e in (ana.values() if isinstance(ana, dict) else ())):
                return True
    return False


def _module_row_wanted(cfg: dict, defaults: dict, user: dict | None, work: Path | None) -> bool:
    """`module_skills` 행을 보일지: remote, 모듈 스킬·분석 스킬 설정 문제, `prefer`, `skill_dir`(R39), 관리 clone 흔적 중 하나.
    설치 스킬 파일 위치는 보지 않는다(기본 환경에서 파일 찾기를 돌리지 않는다)."""
    ana = cfg.get("analyzers") if isinstance(cfg.get("analyzers"), dict) else {}
    return bool(userconfig.module_skills(cfg) or userconfig.module_skills_problems(defaults, user)
                or userconfig.analyzer_problems(defaults, user)
                or any(isinstance(e, dict) and "prefer" in e for e in ana.values())
                or _has_skill_dir(defaults, user)
                or (work is not None and os.path.lexists(work / MODULE_CLONE_NAME)))


def _source_summary(cfg: dict) -> str:
    """`5-1 설치 스킬: data · 그 밖=모듈 문서` — `그 밖` 출처와 다른 카테고리만 묶어 적는다(80자 안)."""
    rest = MODULE_SOURCE_LABEL[userconfig.deep_source(cfg, None)["source"]]
    ana = cfg.get("analyzers") if isinstance(cfg.get("analyzers"), dict) else {}
    odd: dict[str, list[str]] = {}
    for cat in sorted(ana, key=str):
        label = MODULE_SOURCE_LABEL[userconfig.deep_source(cfg, cat)["source"]]
        if label != rest:
            odd.setdefault(label, []).append(str(cat))
    parts = [f"{label}: {','.join(cats)}" for label, cats in odd.items()]
    return "5-1 " + " · ".join(parts) + (" · " if parts else "") + f"그 밖={rest}"


def _module_skills_row(cfg: dict, defaults: dict, user: dict | None, work: Path | None) -> dict:
    """설정 검사 → 5-1 출처 요약 → (remote가 있으면) git 버전 → 관리 clone 상태(읽기 전용, `moduleskills.inspect_clone`)
    → B1-19 경고. 원격 주소는 `redact_remote`로만 보인다. 받기·lock·mkdir 없음."""
    probs = userconfig.module_skills_problems(defaults, user) + userconfig.analyzer_problems(defaults, user)
    if probs:
        return _row("module_skills", "fail", probs[0],
                    "config.py set module_skills.remote <주소> · analyzers.<카테고리>.prefer 확인 (site-defaults면 관리자)")
    note = SKILL_DIR_NOTE if _has_skill_dir(defaults, user) else None
    summary = _source_summary(cfg)
    ms = userconfig.module_skills(cfg)
    if ms is None:
        return _row("module_skills", "ok", f"remote 없음 · {summary}", note)
    from common import moduleskills   # 지연 import: remote가 있을 때만

    ver = moduleskills.git_version()
    need = ".".join(map(str, moduleskills.MIN_GIT))
    if ver is None:
        return _row("module_skills", "fail", f"git 없음 — 모듈 받기에 git {need} 이상 필요", "git을 설치한다")
    if tuple(ver) < tuple(moduleskills.MIN_GIT):
        return _row("module_skills", "fail", f"git {'.'.join(map(str, ver))} — cone sparse에 {need} 이상 필요",
                    "git을 업데이트한다")
    info = moduleskills.inspect_clone(work, ms["remote"], ms["base_branch"]) if work is not None else {"state": "absent"}
    fix = (f"{work / moduleskills.CLONE_DIR if work else moduleskills.CLONE_DIR} 확인 — 고치지 못하면 사용자가 그 폴더를 지운다"
           "(다음 받기에서 다시 받는다)")
    if info.get("state") == "mismatch":
        return _row("module_skills", "fail", f"관리 clone 불일치: {info.get('problem')}", fix)
    if info.get("state") == "forced":
        return _row("module_skills", "fail", "ff-only 실패: 원격 브랜치가 강제로 바뀌었다", fix)
    switches = userconfig.implicit_module_switches(defaults, user)
    if switches:
        return _row("module_skills", "warn", switches[0],
                    "계속 쓰려면 config.py set analyzers.<카테고리>.prefer skill (플랫폼이면 --platform <p>)")
    slug = userconfig.repo_slug(ms["remote"]) if not ms["remote"].lower().startswith("file://") else None
    where = f"{slug[1]}/{slug[2]}" if slug else userconfig.redact_remote(ms["remote"])   # 80자 안: owner/repo만
    if info.get("state") == "ok":
        return _row("module_skills", "ok", f"{where} @{str(info.get('sha') or '')[:7]} · {summary}", note)
    return _row("module_skills", "ok", f"{where} 아직 받지 않음 · {summary}", note)


def _doctor_markdown(rows: list[dict], counts: dict) -> str:
    cell = lambda text: str(text).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    with_next = any(r.get("next") for r in rows)
    head = "| 점검 | 상태 | 내용 |" + (" 다음 |" if with_next else "")
    lines = [head, "|---|---|---|" + ("---|" if with_next else "")]
    for r in rows:
        line = f"| {r['check']} | {r['status']} | {cell(r['detail'])} |"
        if with_next:
            line += f" {cell(r.get('next', ''))} |"
        lines.append(line)
    lines += ["", " · ".join(f"{k} {counts[k]}" for k in ("ok", "warn", "fail", "skip"))]
    return "\n".join(lines) + "\n"


def cmd_doctor(args, defaults: dict) -> tuple[dict, int]:
    rows = _doctor_rows(args, defaults)
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("ok", "warn", "fail", "skip")}
    return {"rows": rows, "counts": counts}, (CHECK_FAILED if counts["fail"] else OK)


_MISSING = object()
LENIENT_CMDS = ("show", "set", "doctor", "rename-legacy")      # 플랫폼 키·옛 설정 키 문제가 있어도 도는 하위 명령(고치는 길)


def cmd_show(args, defaults: dict) -> dict:
    user = userconfig.load_user()
    if args.keys:
        effective = userconfig.merged(defaults, user or {}, platform=_platform(args))
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
        found = {k: userconfig.get(effective, k, _MISSING) for k in keys}
        return {"user_config": str(userconfig.path()) if user is not None else None,
                "values": {k: v for k, v in found.items() if v is not _MISSING},
                "missing": [k for k, v in found.items() if v is _MISSING]}
    return {"plugin_root": str(_plugin_root(args)), "site_defaults": str(_plugin_root(args) / site_defaults.FILENAME),
            "user_config": str(userconfig.path()) if user is not None else None,
            "effective": userconfig.merged(defaults, user or {}, platform=_platform(args))}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS, help="플러그인 루트 (기본: ${CLAUDE_PLUGIN_ROOT})")
    common.add_argument("--platform", metavar="이름", default=argparse.SUPPRESS,
                        help="플랫폼(경로 프로필·이슈 DB). 없으면 TT_PLATFORM > 사용자 config platform > site-defaults platform.name")
    parser = argparse.ArgumentParser(prog="config.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", parents=[common])
    p.add_argument("--keys", metavar="a,b.c", help="쉼표로 구분한 키(점 표기)만 보인다 (예: work_dir,tracker.tools)")
    sub.add_parser("site-defaults", parents=[common])
    p = sub.add_parser("init", parents=[common])
    p.add_argument("--answers")
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("set", parents=[common])
    p.add_argument("key")
    p.add_argument("value")
    p.add_argument("--accept-error-bodies", action="store_true",
                   help="opencode.jira_read open: 사내 확인의 오류 경로 행이 pass가 아니어도(warn 본문이 모델에 감·skip 확인 안 함) 받아들인다")
    sub.add_parser("sync-scripts-path", parents=[common])
    p = sub.add_parser("tracker-candidates", parents=[common])
    p.add_argument("--mcp-config", action="append")
    p.add_argument("--opencode-config", action="append",
                   help="OpenCode 설정(opencode.json·jsonc)의 mcp도 읽는다. OpenCode 안(TT_RUNTIME=opencode)에서는 없어도 "
                        "작업 폴더에서 OpenCode가 합치는 설정을 읽는다")
    p.add_argument("--tools-json")
    p = sub.add_parser("set-tracker", parents=[common])
    p.add_argument("--server", required=True)
    p.add_argument("--get-issue", required=True)
    p.add_argument("--search-issues")
    p.add_argument("--get-comments")
    p.add_argument("--read-tools")
    p = sub.add_parser("rename-legacy", parents=[common])
    p.add_argument("--apply", action="store_true", help="변경 목록대로 사용자 config.yaml을 쓴다(없으면 목록만)")
    p = sub.add_parser("install-hooks", parents=[common])
    p.add_argument("--db", default=None)
    p = sub.add_parser("check", parents=[common])
    p.add_argument("--db", metavar="path", default=None)
    p.add_argument("--for", dest="for_", choices=["write", "dry-run"], default="write")
    p.add_argument("--roots", action="store_true",
                   help="read_roots(플러그인 스킬 폴더·work_dir·설치 스킬 SKILL.md 폴더, 절대 경로)를 더한다(OpenCode 읽기 허용용)")
    sub.add_parser("gh-status", parents=[common])
    p = sub.add_parser("doctor", parents=[common])
    p.add_argument("--format", choices=("json", "markdown"), default="json",
                   help="markdown: 표 하나와 마지막 줄 카운트 (기본 json, --json과 함께 못 쓴다)")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    if IMPORT_ERROR is not None:
        print(f"의존성 없음: {getattr(IMPORT_ERROR, 'name', None) or IMPORT_ERROR} — pyproject 의존성(PyYAML·jsonschema)을 "
              f"설치한 뒤 다시 실행한다 ({type(IMPORT_ERROR).__name__}: {IMPORT_ERROR})", file=sys.stderr)
        return USAGE
    # 어떤 서브커맨드든 사내 기본값이 먼저다. 없으면 종료 코드 2 (example은 읽지 않는다).
    defaults = site_defaults.load_or_exit(getattr(args, "plugin_root", None))
    code = OK
    try:
        if args.cmd != "site-defaults":
            try:
                if args.cmd == "init":
                    # 개인 기본 플랫폼(config `platform`)은 보지 않는다: --platform > TT_PLATFORM > site(`init --force`가
                    # 다른 플랫폼 프로필을 덮지 않게). 기존 config 문제는 보지 않는다(다시 만들 수 있게) — 새 값은 저장 전에 검사
                    args.platform_name = platforms.select(defaults, getattr(args, "platform", None))
                elif args.cmd in LENIENT_CMDS:
                    # 사용자 config의 플랫폼 키 문제가 있어도 고칠 수 있게 돈다(경고·doctor fail 행). 그 밖은 사용 오류
                    args.platform_name, _cfg, problems = platform_session.resolve_lenient(defaults, getattr(args, "platform", None))
                    args.platform_problems = problems
                    if problems and args.cmd != "doctor":
                        print(f"경고: 사용자 config({userconfig.path()}) 플랫폼 설정 문제 — " + "; ".join(problems), file=sys.stderr)
                    legacy = userconfig.legacy_problems(defaults, userconfig.load_user())
                    if legacy and args.cmd in ("show", "set"):     # 고치는 길은 돈다. doctor는 tracker 행 fail
                        print("경고: 옛 설정 키 — " + "; ".join(legacy) + " (고치기 전까지 다른 스크립트는 종료 2, "
                              "guard는 모든 MCP 거부 — config.py rename-legacy)", file=sys.stderr)
                else:
                    args.platform_name, _cfg = platform_session.resolve(defaults, getattr(args, "platform", None))
            except platforms.PlatformConfigError as exc:
                if args.cmd != "doctor":
                    raise UsageError(str(exc)) from exc
                args.platform_name, args.platform_error = None, str(exc)    # doctor는 표의 fail 행으로 보인다
            except yamlio.YamlFileError:
                if args.cmd != "doctor":
                    raise
                args.platform_name = None       # 손상된 config는 doctor의 config 행이 보인다
        if args.cmd == "site-defaults":
            result = defaults
        elif args.cmd == "show":
            result = cmd_show(args, defaults)
        elif args.cmd == "init":
            result = cmd_init(args, defaults)
        elif args.cmd == "set":
            result = cmd_set(args, defaults)
        elif args.cmd == "sync-scripts-path":
            result = cmd_sync_scripts_path(args, defaults)
        elif args.cmd == "tracker-candidates":
            result = cmd_tracker_candidates(args, defaults)
        elif args.cmd == "set-tracker":
            result = cmd_set_tracker(args, defaults)
        elif args.cmd == "rename-legacy":
            result = cmd_rename_legacy(args, defaults)
        elif args.cmd == "install-hooks":
            result = cmd_install_hooks(args, defaults)
        elif args.cmd == "check":
            result, code = cmd_check(args, defaults)
        elif args.cmd == "doctor":
            if args.format == "markdown" and getattr(args, "json", False):
                raise UsageError("--format markdown은 --json과 함께 쓸 수 없다.")
            result, code = cmd_doctor(args, defaults)
            if args.format == "markdown":
                print(_doctor_markdown(result["rows"], result["counts"]), end="")
                return code
            print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
            return code
        else:
            result, code = cmd_gh_status(args, defaults)
    except (UsageError, yamlio.YamlFileError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for reason in (result.get("reasons") or []) if isinstance(result, dict) else []:
        print(f"{reason['code']}: {reason['message']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=args.cmd == "site-defaults"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
