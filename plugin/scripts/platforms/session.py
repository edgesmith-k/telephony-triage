"""사용자 세션 흐름의 플랫폼 선택 (17-platforms §3-3). CLI 진입점이 쓴다.

`--platform`(CLI) > `TT_PLATFORM`(triage가 하위 스크립트에 넘긴다) > 사용자 config `platform` > site-defaults `platform.name`.
고른 플랫폼은 `platform.enabled`에 있어야 한다(`platforms.select`). 사용자 config의 플랫폼 키 오류(`platforms.<p>`에
경로 프로필 밖 키 등)도 여기서 거부한다. 결과 cfg는 `userconfig.merged(…, platform=…)`이다.

레지스트리(`platforms/__init__.py`)는 사용자 config를 모른다 — 둘을 잇는 곳은 이 모듈뿐이다.
"""

from __future__ import annotations

import argparse

from common import userconfig

from . import ENV, PlatformConfigError, select

HELP = "플랫폼(이슈 DB·파서·설정 묶음). 없으면 TT_PLATFORM > 사용자 config platform > site-defaults platform.name"


def add_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--platform", metavar="이름", default=None, help=HELP)


def resolve(defaults: dict, cli: str | None = None, user: dict | None = None) -> tuple[str, dict]:
    """`(플랫폼 이름, 그 플랫폼의 cfg)`. 오류는 `PlatformConfigError`(호출자가 종료 코드 2)."""
    given = user is not None
    user = userconfig.load_user() if user is None else user
    problems = userconfig.profile_problems(user)
    if problems:
        raise PlatformConfigError(f"사용자 config({userconfig.path()}): " + "; ".join(problems))
    name = select(defaults, cli, userconfig.selected_hint(user))
    if name == userconfig.TOP_PROFILE:      # 기본 플랫폼은 이전과 같은 호출(같은 결과)
        return name, userconfig.merged(defaults, user) if given else userconfig.merged(defaults)
    return name, userconfig.merged(defaults, user, platform=name)


def resolve_lenient(defaults: dict, cli: str | None = None, user: dict | None = None) -> tuple[str, dict, list[str]]:
    """`resolve`와 같되 사용자 config의 플랫폼 키 문제는 **경고 목록**으로 돌려준다(config.py show·set·doctor가 고칠 수
    있게). 사용자 `platform`이 켜지지 않은 이름이면 site 기본으로 대신한다. `--platform`(cli)이 잘못되면 그대로 오류다."""
    given = user is not None
    user = userconfig.load_user() if user is None else user
    problems = userconfig.profile_problems(user)
    try:
        name = select(defaults, cli, userconfig.selected_hint(user))
    except PlatformConfigError as exc:
        if cli:
            raise
        problems.append(str(exc))
        name = select(defaults, None, None)
    if name == userconfig.TOP_PROFILE:
        cfg = userconfig.merged(defaults, user) if given else userconfig.merged(defaults)
    else:
        cfg = userconfig.merged(defaults, user, platform=name)
    return name, cfg, problems


def env_name() -> str | None:
    import os

    return os.environ.get(ENV) or None
