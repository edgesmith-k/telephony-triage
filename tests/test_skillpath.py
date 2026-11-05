"""설치 분석 스킬 `SKILL.md` 풀기(`common/skillpath.py`, B2-1·B2-2)와 출처 기록(`common/provenance.py`, B2-7).

`installed_plugins.json` 모양은 Claude Code 2.1.318에서 빈 플러그인을 로컬 디렉토리 marketplace로 임시 `CLAUDE_CONFIG_DIR`에
설치해 확인했다(모델 호출 없음, 11/05 — MODULE_SKILLS_RESULT B2 노트). `R9_INSTALLED`가 그때 나온 파일 그대로다(경로만 바꿈):
`{"version": 2, "plugins": {"<plugin>@<marketplace>": [{"scope", "installPath", "version", "installedAt", "lastUpdated"}]}}`,
`installPath` = `<config>/plugins/cache/<marketplace>/<plugin>/<version>`, 그 아래 `skills/<이름>/SKILL.md`.
모든 테스트는 임시 HOME·CLAUDE_CONFIG_DIR·XDG_CONFIG_HOME을 쓴다(실제 설치에 기대지 않는다).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import provenance, skillpath  # noqa: E402

R9_INSTALLED = {
    "version": 2,
    "plugins": {
        "emptyp@localmkt": [
            {"scope": "user", "installPath": "<CFG>/plugins/cache/localmkt/emptyp/0.1.0", "version": "0.1.0",
             "installedAt": "2026-11-05T05:01:06.287Z", "lastUpdated": "2026-11-05T05:01:06.287Z"}
        ]
    },
}


def _skill(d: Path, name: str | None = "hello", body: str = "x\n") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    front = f"---\nname: {name}\ndescription: d\n---\n" if name else ""
    (d / "SKILL.md").write_text(front + body, encoding="utf-8")
    return d / "SKILL.md"


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return {"HOME": str(home), "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg"), "XDG_CONFIG_HOME": str(tmp_path / "xdg")}


def _installed(env: dict, data=None) -> Path:
    cfg = Path(env["CLAUDE_CONFIG_DIR"])
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    text = json.dumps(data if data is not None else R9_INSTALLED).replace("<CFG>", str(cfg))
    (cfg / "plugins" / "installed_plugins.json").write_text(text, encoding="utf-8")
    return cfg / "plugins" / "cache" / "localmkt" / "emptyp" / "0.1.0"


def _cfg(skill: str, **extra) -> dict:
    return {"analyzers": {"data": {"skill": skill, "when": "ask", **extra}}}


def _res(cfg, env):
    return skillpath.resolve(cfg, "data", environ=env, home=env["HOME"])


# -- skill_dir ------------------------------------------------------------------------------------------


def test_skill_dir_hit(tmp_path, env):
    f = _skill(tmp_path / "s")
    assert _res(_cfg("hello", skill_dir=str(tmp_path / "s")), env) == {
        "path": str(f), "base": str(tmp_path / "s"), "why": "skill_dir"}


def test_skill_dir_tilde(env):
    f = _skill(Path(env["HOME"]) / "sk")
    assert _res(_cfg("hello", skill_dir="~/sk"), env)["path"] == str(f)


def test_skill_dir_miss_has_no_search_fallback(tmp_path, env):
    _skill(_installed(env) / "skills" / "hello")
    got = _res(_cfg("hello", skill_dir=str(tmp_path / "none")), env)
    assert got["path"] is None and got["why"].startswith("skill_dir에 맞는 SKILL.md가 없다: ")


def test_skill_dir_name_mismatch(tmp_path, env):
    _skill(tmp_path / "s", name="other")
    assert _res(_cfg("hello", skill_dir=str(tmp_path / "s")), env)["path"] is None


def test_frontmatter_without_name_is_accepted(tmp_path, env):
    _skill(tmp_path / "s", name=None)
    assert _res(_cfg("hello", skill_dir=str(tmp_path / "s")), env)["path"]


def test_oversized_refused(tmp_path, env):
    _skill(tmp_path / "s", body="x" * (skillpath.SKILL_MAX + 1))
    assert _res(_cfg("hello", skill_dir=str(tmp_path / "s")), env)["path"] is None


# -- search ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["hello", "emptyp:hello"])
def test_installed_plugins_hit(env, name):
    f = _skill(_installed(env) / "skills" / "hello")
    got = _res(_cfg(name), env)
    assert got == {"path": str(f), "base": str(f.parent), "why": "installed_plugins.json"}


def test_plugin_prefix_filters_other_plugins(env):
    _skill(_installed(env) / "skills" / "hello")
    assert _res(_cfg("otherp:hello"), env)["path"] is None


@pytest.mark.parametrize("text", ["{not json", "[]", '{"plugins": []}', '{"plugins": {"emptyp@localmkt": "x"}}'])
def test_malformed_installed_plugins_no_hit(env, text):
    _installed(env)
    (Path(env["CLAUDE_CONFIG_DIR"]) / "plugins" / "installed_plugins.json").write_text(text, encoding="utf-8")
    got = _res(_cfg("hello"), env)
    assert got["path"] is None and got["why"] == "설치 위치에서 찾지 못했다 — analyzers.data.skill_dir를 적는다"


def test_claude_skills_and_opencode_skills(env):
    f = _skill(Path(env["CLAUDE_CONFIG_DIR"]) / "skills" / "hello")
    assert _res(_cfg("hello"), env)["path"] == str(f)
    f.unlink()
    g = _skill(Path(env["XDG_CONFIG_HOME"]) / "opencode" / "skills" / "hello")
    assert _res(_cfg("hello"), env)["path"] == str(g)


def test_default_config_dirs_under_home(env):
    e = {"HOME": env["HOME"]}
    f = _skill(Path(env["HOME"]) / ".claude" / "skills" / "hello")
    assert skillpath.resolve(_cfg("hello"), "data", environ=e, home=env["HOME"])["path"] == str(f)


def test_two_hits_ambiguous(env):
    _skill(_installed(env) / "skills" / "hello")
    _skill(Path(env["XDG_CONFIG_HOME"]) / "opencode" / "skills" / "hello")
    got = _res(_cfg("hello"), env)
    assert got["path"] is None and got["why"] == "2곳에서 찾았다 — analyzers.data.skill_dir로 고른다"


def test_same_file_twice_is_one_hit(env):
    f = _skill(Path(env["CLAUDE_CONFIG_DIR"]) / "skills" / "hello")
    (Path(env["XDG_CONFIG_HOME"]) / "opencode" / "skills").mkdir(parents=True)
    (Path(env["XDG_CONFIG_HOME"]) / "opencode" / "skills" / "hello").symlink_to(f.parent)
    assert _res(_cfg("hello"), env)["path"]


@pytest.mark.parametrize("cfg", [{}, {"analyzers": {"data": {"when": "ask"}}}, _cfg("../x"), _cfg("a/b"), None, []])
def test_no_skill_or_bad_name_never_raises(env, cfg):
    got = skillpath.resolve(cfg, "data", environ=env, home=env["HOME"])
    assert got["path"] is None and got["base"] is None and got["why"]


# -- provenance.env_info ---------------------------------------------------------------------------------

GW = "http://user:tok@gw.example.invalid:8080/v1"


@pytest.mark.parametrize("environ,want", [
    ({"TT_RUNTIME": "opencode", "TT_MODEL": "glm-5.3", "CLAUDECODE": "1", "ANTHROPIC_MODEL": "x"},
     {"runtime": "opencode", "model": "glm-5.3", "gateway": "none"}),
    ({"CLAUDECODE": "1"}, {"runtime": "claude-code", "model": "모름", "gateway": "none"}),
    ({"CLAUDECODE": "1", "ANTHROPIC_BASE_URL": GW, "ANTHROPIC_DEFAULT_SONNET_MODEL": "example-internal"},
     {"runtime": "claude-code", "model": "모름", "gateway": "other", "model_defaults": {"sonnet": "example-internal"}}),
    ({"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}, {"runtime": "모름", "gateway": "anthropic"}),
    ({"ANTHROPIC_BASE_URL": "https://" "evilanthropic.com"}, {"gateway": "other"}),   # 합성 호스트: 끝만 같은 이름은 anthropic 아님
    ({}, {"runtime": "모름", "model": "모름", "model_defaults": {}, "gateway": "none", "label": None}),
])
def test_env_matrix(environ, want):
    got = provenance.env_info(environ)
    assert set(got) == {"runtime", "model", "model_defaults", "gateway", "label"}
    for k, v in want.items():
        assert got[k] == v
    assert "gw.example" not in json.dumps(got) and "tok" not in json.dumps(got)


def test_defaults_all_and_clipping():
    env = {"ANTHROPIC_DEFAULT_OPUS_MODEL": "o", "ANTHROPIC_DEFAULT_HAIKU_MODEL": "h", "ANTHROPIC_SMALL_FAST_MODEL": "s",
           "ANTHROPIC_MODEL": "m" * 100 + " $(x)"}
    got = provenance.env_info(env)
    assert got["model_defaults"] == {"opus": "o", "haiku": "h", "small": "s"}
    assert got["model"] == "m" * 60


@pytest.mark.parametrize("cfg,label", [({"runtime": {"label": "cc-internal-glm"}}, "cc-internal-glm"),
                                       ({"runtime": {"label": "x" * 41}}, None), ({"runtime": {"label": 3}}, None),
                                       ({"runtime": "x"}, None), (None, None), ([], None)])
def test_label(cfg, label):
    assert provenance.env_info({}, cfg)["label"] == label


def test_non_str_values_never_raise():
    class Weird:
        def get(self, _k):
            raise RuntimeError

    assert provenance.env_info(Weird())["runtime"] == "모름"
    assert provenance.env_info({"TT_RUNTIME": 3, "ANTHROPIC_BASE_URL": 5})["runtime"] == "3"
