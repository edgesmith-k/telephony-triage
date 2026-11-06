"""설치된 분석 스킬의 `SKILL.md` 경로 풀기 (B2-1·B2-2, MODULE_SKILLS_DECISIONS 계획 I ②).

`triage.py module --for deep`이 5-1 출처가 설치 스킬(`userconfig.deep_source` = skill)일 때 쓴다. 모든 런타임에서 그 파일을
Read로 읽게 경로와 폴더(`base`)를 준다. 못 찾거나 둘 이상이면 None — 호출자가 종료 1 `설치 스킬 못 찾음`으로 알리고, 스킬을
부르는 도구가 있는 런타임만 예전처럼 그 스킬을 부른다.

순서: ① `analyzers.<cat>.skill_dir`(있으면 그것만, 찾기로 넘어가지 않는다) ② 찾기 — Claude Code 설치 플러그인
(`$CLAUDE_CONFIG_DIR` 또는 `~/.claude`의 `plugins/installed_plugins.json` `installPath` + `skills/<이름>/SKILL.md`), 같은 설정
폴더의 `skills/<이름>/SKILL.md`, `${XDG_CONFIG_HOME:-~/.config}/opencode/skills/<이름>/SKILL.md`. 찾은 것마다 정규 파일·크기
상한·frontmatter `name:`을 본다. `installed_plugins.json` 모양(`{"version": 2, "plugins": {"<p>@<m>": [{"installPath", "version",
…}]}}`)은 Claude Code 2.1.318에서 로컬 marketplace 설치로 확인했다(MODULE_SKILLS_RESULT B2 노트). 읽기 오류는 "찾지 못함"으로
본다. 예외를 내지 않는다.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

SKILL_MAX = 65536
INSTALLED_MAX = 1 << 20
_NAME_RX = re.compile(r"^name:\s*(.*?)\s*$")


def _front_name(text: str) -> str | None:
    """frontmatter(`---`로 시작해 `---`로 닫힘)의 `name:` 값(따옴표 없앰) 또는 None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        m = _NAME_RX.match(line)
        if m:
            return m.group(1).strip("'\"")
    return None


def _ok(path: Path, bare: str) -> bool:
    """정규 파일(링크도 따라가 정규 파일이면 된다), ≤ SKILL_MAX, frontmatter `name:`이 있으면 `bare`와 같다."""
    try:
        if not path.is_file() or path.stat().st_size > SKILL_MAX:
            return False
        name = _front_name(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    return name is None or name == bare


def _show(p: Path, home: Path) -> str:
    """홈 아래면 `~/…`로 줄인 경로(출력용, 60자)."""
    s = str(p)
    h = str(home)
    if h and (s == h or s.startswith(h.rstrip(os.sep) + os.sep)):
        s = "~" + s[len(h.rstrip(os.sep)):]
    return s[-60:]


def _install_paths(cfg_dir: Path, plugin: str | None) -> list[Path]:
    """`installed_plugins.json`의 `installPath`들(`plugin`이 있으면 `<plugin>@` 키만)."""
    f = cfg_dir / "plugins" / "installed_plugins.json"
    try:
        if not f.is_file() or f.stat().st_size > INSTALLED_MAX:
            return []
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    plugins = data.get("plugins") if isinstance(data, dict) else None
    out: list[Path] = []
    for key, entries in plugins.items() if isinstance(plugins, dict) else ():
        if plugin and not str(key).startswith(plugin + "@"):
            continue
        for e in entries if isinstance(entries, list) else [entries]:
            p = e.get("installPath") if isinstance(e, dict) else None
            if isinstance(p, str) and p.strip() and os.path.isabs(p):
                out.append(Path(p))
    return out


def resolve(cfg: dict, category: str | None, *, environ=None, home=None) -> dict:
    """`{"path": 절대 SKILL.md | None, "base": 그 폴더 | None, "why": str}`."""
    try:
        env = os.environ if environ is None else environ
        home_p = Path(home) if home is not None else Path(env.get("HOME") or Path.home())
        ana = cfg.get("analyzers") if isinstance(cfg, dict) and isinstance(cfg.get("analyzers"), dict) else {}
        conf = ana.get(category or "")
        conf = conf if isinstance(conf, dict) else {}
        name = conf.get("skill")
        at = f"analyzers.{category}"
        if not isinstance(name, str) or not name.strip():
            return {"path": None, "base": None, "why": f"{at}.skill이 없다"}
        name = name.strip()
        bare = name.split(":")[-1]
        plugin = name.split(":")[0] if ":" in name else None
        if not bare or "/" in bare or "\\" in bare or bare in (".", ".."):
            return {"path": None, "base": None, "why": f"{at}.skill이 스킬 이름이 아니다"}
        sd = conf.get("skill_dir")
        if isinstance(sd, str) and sd.strip():
            sd = sd.strip()
            d = Path(str(home_p) + sd[1:] if sd == "~" or sd.startswith("~/") else sd)
            cand = d / "SKILL.md"
            if d.is_absolute() and _ok(cand, bare):
                p = Path(os.path.abspath(cand))
                return {"path": str(p), "base": str(p.parent), "why": "skill_dir"}
            return {"path": None, "base": None, "why": f"skill_dir에 맞는 SKILL.md가 없다: {_show(d, home_p)}"}
        cfg_dir = Path(env.get("CLAUDE_CONFIG_DIR") or home_p / ".claude")
        xdg = Path(env.get("XDG_CONFIG_HOME") or home_p / ".config")
        cands = [(ip / "skills" / bare / "SKILL.md", "installed_plugins.json") for ip in _install_paths(cfg_dir, plugin)]
        cands += [(cfg_dir / "skills" / bare / "SKILL.md", "claude skills"),
                  (xdg / "opencode" / "skills" / bare / "SKILL.md", "opencode skills")]
        hits: dict[str, tuple[Path, str]] = {}
        for c, why in cands:
            if _ok(c, bare):
                hits.setdefault(os.path.realpath(c), (Path(os.path.abspath(c)), why))
        if len(hits) == 1:
            p, why = next(iter(hits.values()))
            return {"path": str(p), "base": str(p.parent), "why": why}
        if not hits:
            return {"path": None, "base": None, "why": f"설치 위치에서 찾지 못했다 — {at}.skill_dir를 적는다"}
        return {"path": None, "base": None, "why": f"{len(hits)}곳에서 찾았다 — {at}.skill_dir로 고른다"}
    except Exception:
        return {"path": None, "base": None, "why": "설치 스킬을 찾다가 오류가 났다"}
