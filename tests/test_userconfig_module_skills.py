"""모듈 스킬 레포 설정(`module_skills`)과 분석 스킬 선택(`prefer`·`skill_dir`)의 userconfig 도우미 (B1 설계 §2·§10.4, B2 §9.1·§12.1).

- `module_skills`는 최상위 공통 키(플랫폼별이 아니다). `builtin()`에 없다 — remote가 없으면 merged 결과가 그대로.
- 원격 값은 전송 방식이 드러난 꼴만(B1-18). 자격 증명은 메시지에 나오지 않는다.
- `deep_source`가 5-1 출처의 유일한 구현(B1 §2.4 표, Q2 바꿈 11/05).
- 어느 도우미도 잘못된 입력에 예외를 내지 않는다(guard 경로).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import userconfig as uc  # noqa: E402

EXAMPLE = yaml.safe_load((REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8"))
REMOTE = "https://ghe.example.invalid/tt/module-skills.git"
GARBAGE = (None, [], 1, "x", {"module_skills": []}, {"module_skills": {"remote": 3}}, {"analyzers": []},
           {"analyzers": {"data": []}}, {"platforms": []}, {"platforms": {"ofono": []}},
           {"platforms": {"ofono": {"analyzers": {"data": {"prefer": object()}}}}})


def _d(**over) -> dict:
    data = copy.deepcopy(EXAMPLE)
    data.update(over)
    return data


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv(uc.HOME_ENV, str(tmp_path / "tt-home"))


# -- from_site_defaults / merged ------------------------------------------------------------------------


def test_example_has_no_module_skills_and_no_deprecated_keys():
    cfg = uc.merged(EXAMPLE, {})
    assert "module_skills" not in cfg
    assert not {"inputs", "max_tokens_hint"} & set(cfg["analyzers"]["data"])
    assert uc.deprecated_keys(EXAMPLE, {}) == []
    assert uc.runtime_problems(EXAMPLE) == []


@pytest.mark.parametrize("block", [{}, None])
def test_empty_or_absent_block_leaves_merged_unchanged(block):
    base = uc.merged(EXAMPLE, {})
    d = _d() if block is None else _d(module_skills=block)
    assert uc.merged(d, {}) == base


def test_site_block_copied_and_user_overrides_remote_keeping_base():
    d = _d(module_skills={"remote": REMOTE, "base_branch": "release/1"})
    assert uc.merged(d, {})["module_skills"] == {"remote": REMOTE, "base_branch": "release/1"}
    user = {"module_skills": {"remote": "git@ghe.example.invalid:tt/other.git"}}
    ms = uc.module_skills(uc.merged(d, user))
    assert ms == {"remote": "git@ghe.example.invalid:tt/other.git", "base_branch": "release/1"}


def test_platform_merge_keeps_top_level_module_skills():
    d = _d(module_skills={"remote": REMOTE})
    cfg = uc.merged(d, {"platforms": {"ofono": {"work_dir": "/w/o"}}}, platform="ofono")
    assert uc.module_skills(cfg) == {"remote": REMOTE, "base_branch": "main"}


@pytest.mark.parametrize("remote", [None, "", "   "])
def test_module_skills_none_for_blank(remote):
    assert uc.module_skills({"module_skills": {"remote": remote}}) is None
    assert uc.module_skills({}) is None
    assert uc.module_skills({"module_skills": {"remote": REMOTE, "base_branch": " "}})["base_branch"] == "main"


# -- module_skills_problems -----------------------------------------------------------------------------


@pytest.mark.parametrize("remote", [REMOTE, "ssh://git@ghe.example.invalid/o/r", "git@ghe.example.invalid:o/r.git",
                                    "ghe-ssh:o/r.git", "file:///abs/r.git"])
def test_remote_ok(remote):
    assert uc.module_remote_problem(remote) is None
    assert uc.module_skills_problems({}, {"module_skills": {"remote": remote}}) == []


@pytest.mark.parametrize("remote", ["tt/module-skills", "ghe.example.invalid/tt/r", "./x", "/abs/r.git",
                                    "http://ghe.example.invalid/o/r.git", "git://h.invalid/o/r", "ssh://u:pw@h.invalid/o/r",
                                    "file://rel", "-x", "a b", "https://u:secret@ghe.example.invalid/o/r.git"])
def test_remote_errors(remote):
    probs = uc.module_skills_problems({}, {"module_skills": {"remote": remote}})
    assert len(probs) == 1 and probs[0].startswith("사용자 config module_skills.remote: ")
    assert "pw" not in probs[0] and "secret" not in probs[0]


def test_credentials_message():
    p = uc.module_remote_problem("https://u:secret@ghe.example.invalid/o/r.git")
    assert p.startswith("주소에 자격 증명(user:token@)을 넣지 않는다") and "ghe.example.invalid/o/r" in p
    assert "secret" not in p and "u:" not in p
    assert uc.module_remote_problem("file://rel").startswith("file:// 뒤는 절대 경로여야 합니다")


def test_shape_and_unknown_key_and_int_remote():
    assert uc.module_skills_problems({"module_skills": "x"}, None) == [
        "site-defaults module_skills: 매핑이어야 합니다({remote, base_branch})."]
    probs = uc.module_skills_problems({}, {"module_skills": {"remote": 3, "branch": "main"}})
    assert "사용자 config module_skills.branch: 모르는 키입니다 (허용: remote, base_branch)." in probs
    assert "사용자 config module_skills.remote: 문자열이어야 합니다." in probs


def test_same_repo_as_issue_db():
    user = {"issue_db": {"remote": "https://ghe.example.invalid/tt/r.git", "path": "/x/db"},
            "module_skills": {"remote": "git@ghe.example.invalid:tt/r.git"}}
    probs = uc.module_skills_problems(EXAMPLE, user)
    assert probs == ["module_skills.remote: 이슈 DB 레포와 같다 — 모듈 스킬 레포는 따로 둔다: ghe.example.invalid/tt/r"]
    user["platforms"] = {"ofono": {"issue_db": {"remote": "https://ghe.example.invalid/tt/o.git", "path": "/x/o"}}}
    user["module_skills"]["remote"] = "ssh://git@ghe.example.invalid/tt/o"
    assert any("이슈 DB 레포와 같다" in p for p in uc.module_skills_problems(EXAMPLE, user))


@pytest.mark.parametrize("base,ok", [("-x", False), ("a..b", False), ("x.lock", False), ("a//b", False), ("/a", False),
                                     ("a/", False), (3, False), ("release/1.0", True), ("main", True)])
def test_base_branch(base, ok):
    probs = uc.module_skills_problems({}, {"module_skills": {"remote": REMOTE, "base_branch": base}})
    assert (probs == []) is ok
    if not ok:
        assert probs[0].startswith("사용자 config module_skills.base_branch: 브랜치 이름이어야 합니다")


@pytest.mark.parametrize("bad", GARBAGE)
def test_helpers_never_raise(bad):
    for fn in (uc.module_skills_problems, uc.analyzer_problems, uc.implicit_module_switches, uc.module_remotes,
               uc.deprecated_keys):
        fn(bad, bad)
        fn(EXAMPLE, bad)
    uc.analyzer_problems(bad, bad, platform="ofono")
    uc.module_skills(bad)
    uc.deep_source(bad if isinstance(bad, dict) else {}, "data")
    uc.deep_source_problem(bad if isinstance(bad, dict) else {}, "data")
    uc.redact_remote(bad)
    uc.module_remote_problem(bad)
    uc.runtime_problems(bad)
    uc.read_roots(bad, Path("/p"))


def test_platform_module_skills_messages():
    probs = uc.profile_problems({"platforms": {"ofono": {"module_skills": {"remote": REMOTE}}}})
    assert any(p.startswith("platforms.ofono.module_skills: 최상위 키입니다") for p in probs)
    probs = uc.site_platform_problems({"platforms": {"ofono": {"module_skills": {"remote": REMOTE}}}})
    assert any(p.startswith("site-defaults platforms.ofono.module_skills: 최상위 키입니다") for p in probs)


# -- analyzer_problems ----------------------------------------------------------------------------------


def test_prefer_bad_value():
    probs = uc.analyzer_problems(EXAMPLE, {"analyzers": {"data": {"prefer": "x"}}})
    assert probs == ["사용자 config analyzers.data.prefer: module 또는 skill이어야 합니다: 'x'"]


def test_prefer_skill_without_skill_top_and_platform():
    probs = uc.analyzer_problems({}, {"analyzers": {"sim": {"prefer": "skill"}}})
    assert probs == ["analyzers.sim.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다 — skill을 적거나 prefer를 지운다."]
    probs = uc.analyzer_problems({}, {"platforms": {"ofono": {"analyzers": {"data": {"prefer": "skill"}}}}})
    assert probs == ["platforms.ofono.analyzers.data.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다 — "
                     "skill을 적거나 prefer를 지운다."]


def test_site_skill_plus_user_prefer_ok_and_user_module_overrides_site_skill():
    assert uc.analyzer_problems(EXAMPLE, {"analyzers": {"data": {"prefer": "skill"}}}) == []
    d = _d(analyzers={"data": {"prefer": "skill"}})
    assert uc.analyzer_problems(d, {"analyzers": {"data": {"prefer": "module"}}}) == []


def test_platform_filter():
    user = {"analyzers": {"sim": {"prefer": "skill"}},
            "platforms": {"ofono": {"analyzers": {"data": {"prefer": "skill"}}}}}
    assert len(uc.analyzer_problems({}, user)) == 2
    a = uc.analyzer_problems({}, user, platform="android")
    o = uc.analyzer_problems({}, user, platform="ofono")
    assert len(a) == 1 and a[0].startswith("analyzers.sim.")
    assert len(o) == 1 and o[0].startswith("platforms.ofono.")


@pytest.mark.parametrize("value", ["rel/dir", "/a/../b", 3, "/" + "x" * 300, ""])
def test_skill_dir_bad(value):
    probs = uc.analyzer_problems(EXAMPLE, {"analyzers": {"data": {"skill_dir": value}}})
    assert any("analyzers.data.skill_dir: 설치 스킬 폴더의 절대 경로여야 합니다" in p for p in probs)


def test_skill_dir_without_skill_and_platform_scoped():
    probs = uc.analyzer_problems({}, {"analyzers": {"sim": {"skill_dir": "/opt/s"}}})
    assert probs == ["analyzers.sim.skill_dir: skill(설치 스킬 이름)과 함께 쓴다."]
    assert uc.analyzer_problems(EXAMPLE, {"analyzers": {"data": {"skill_dir": "/opt/s"}}}) == []
    assert uc.analyzer_problems(EXAMPLE, {"analyzers": {"data": {"skill_dir": "~/s"}}}) == []
    probs = uc.analyzer_problems({}, {"platforms": {"ofono": {"analyzers": {"data": {"skill_dir": "x"}}}}})
    assert "사용자 config platforms.ofono.analyzers.data.skill_dir: 설치 스킬 폴더의 절대 경로여야 합니다: 'x'" in probs


# -- implicit_module_switches (B1-19) -------------------------------------------------------------------


def test_implicit_switches():
    assert uc.implicit_module_switches(EXAMPLE, {}) == []
    user = {"module_skills": {"remote": REMOTE}}
    assert uc.implicit_module_switches(EXAMPLE, user) == [
        "analyzers.data: 설치 스킬 mock-data-analyzer 대신 모듈 문서를 쓴다 — 계속 쓰려면 prefer: skill"]
    for prefer in ("module", "skill"):
        assert uc.implicit_module_switches(EXAMPLE, {**user, "analyzers": {"data": {"prefer": prefer}}}) == []
    user["platforms"] = {"ofono": {"analyzers": {"data": {"skill": "o"}}}}
    assert "platforms.ofono.analyzers.data: 설치 스킬 o 대신 모듈 문서를 쓴다 — 계속 쓰려면 prefer: skill" in \
        uc.implicit_module_switches(EXAMPLE, user)


# -- deep_source (B1 §2.4 표) ---------------------------------------------------------------------------

MS = {"module_skills": {"remote": REMOTE}}
ROWS = [  # (analyzers.data 항목, remote 있음, 기대 source)
    ({"skill": "s", "prefer": "skill"}, True, "skill"),
    ({"skill": "s", "prefer": "skill"}, False, "skill"),
    ({"prefer": "skill"}, True, "error"),
    ({"prefer": "skill"}, False, "error"),
    ({"skill": "s", "prefer": "module"}, True, "module"),
    ({"prefer": "module"}, True, "module"),
    ({"skill": "s"}, True, "module"),
    ({}, True, "module"),
    ({"skill": "s"}, False, "skill"),
    ({"skill": "s", "prefer": "module"}, False, "skill"),
    ({}, False, "none"),
    ({"prefer": "module"}, False, "none"),
    ({"skill": "s", "prefer": "x"}, True, "error"),
    ({"prefer": 3}, False, "error"),
]


@pytest.mark.parametrize("entry,remote,want", ROWS)
@pytest.mark.parametrize("platform", ["android", "ofono"])
def test_deep_source_matrix(entry, remote, want, platform):
    d = _d(analyzers={}, **(MS if remote else {}))
    user = ({"analyzers": {"data": {"when": "ask", **entry}}} if platform == "android" else
            {"platforms": {"ofono": {"analyzers": {"data": {"when": "ask", **entry}}}}})
    cfg = uc.merged(d, user, platform=platform)
    got = uc.deep_source(cfg, "data")
    assert got["source"] == want
    assert got["when"] == "ask"
    assert got["skill"] == (None if want in ("module", "none") else entry.get("skill"))
    assert (uc.deep_source_problem(cfg, "data") is None) is (want != "error")


def test_deep_source_ofono_does_not_inherit_android_skill():
    d = _d(**MS)
    cfg = uc.merged(d, {"analyzers": {"data": {"skill": "a", "prefer": "skill"}}}, platform="ofono")
    assert uc.deep_source(cfg, "data")["source"] == "module"
    assert uc.deep_source(uc.merged(_d(), {}, platform="ofono"), "data")["source"] == "none"
    assert uc.deep_source({}, None) == {"source": "none", "skill": None, "when": "ask"}


def test_deep_source_problem_texts():
    assert uc.deep_source_problem({"analyzers": {"data": {"prefer": "x"}}}, "data") == \
        "analyzers.data.prefer: module 또는 skill이어야 합니다: 'x'"
    assert uc.deep_source_problem({"analyzers": {"data": {"prefer": "skill"}}}, "data") == \
        "analyzers.data.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다"


# -- deprecated_keys / module_remotes / redact_remote / runtime -----------------------------------------


def test_deprecated_keys_texts():
    d = _d(analyzers={"data": {"skill": "s", "inputs": [], "max_tokens_hint": "m", "source": "/x"}})
    user = {"analyzers": {"sim": {"inputs": ["a"]}}, "platforms": {"ofono": {"analyzers": {"data": {"max_tokens_hint": 1}}}}}
    assert uc.deprecated_keys(d, user) == [
        "site-defaults: 폐지 키 `analyzers.data.inputs`는 읽지 않는다(무시) — 그 줄을 지운다 (관리자)",
        "site-defaults: 폐지 키 `analyzers.data.max_tokens_hint`는 읽지 않는다(무시) — 그 줄을 지운다 (관리자)",
        "사용자 config: 폐지 키 `analyzers.sim.inputs`는 읽지 않는다(무시) — 그 줄을 지운다",
        "사용자 config: 폐지 키 `platforms.ofono.analyzers.data.max_tokens_hint`는 읽지 않는다(무시) — 그 줄을 지운다"]
    assert uc.legacy_problems(d, user) == []


def test_module_remotes():
    d = {"module_skills": {"remote": REMOTE}, "platforms": {"ofono": {"module_skills": {"remote": "x:o/r"}}}}
    u = {"module_skills": {"remote": ""}, "platforms": {"oFono": {"module_skills": {"remote": "y:o/r"}},
                                                        "sim": {"module_skills": {"remote": 3}}}}
    assert uc.module_remotes(d, u) == [REMOTE, "x:o/r", "y:o/r"]


@pytest.mark.parametrize("value,want", [("https://u:t@ghe.example.invalid/o/r.git", "ghe.example.invalid/o/r"),
                                        ("git@host:o/r.git", "host/o/r"),
                                        ("file:///a/b/r.git", "file://…/r.git"),
                                        ("ssh://git:pw@host.invalid/o/r", "host.invalid/o/r")])
def test_redact_remote(value, want):
    assert uc.redact_remote(value) == want


def test_redact_remote_unresolvable_has_no_userinfo():
    out = uc.redact_remote("http://user:secret@x.invalid")
    assert "secret" not in out and "user" not in out


@pytest.mark.parametrize("rt,warn", [({"label": "cc-internal"}, False), ({"label": "a b+c.d_e-1"}, False),
                                     ({"label": "x" * 41}, True), ({"label": "한글"}, True), ({"label": 3}, True),
                                     ("x", True), ({}, False), (None, False)])
def test_runtime_label(rt, warn):
    assert uc.runtime_problems({"runtime": rt}) == ([uc.RUNTIME_LABEL_MSG] if warn else [])
    assert "runtime" not in uc.merged({"runtime": rt}, {})       # site 전용 키: merged cfg에 옮기지 않는다


# -- read_roots (B2-21) ---------------------------------------------------------------------------------


def test_read_roots_order_and_dedup(tmp_path):
    skill = tmp_path / "skills" / "my-an"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: my-an\n---\nx\n", encoding="utf-8")
    cfg = {"work_dir": str(tmp_path / "work"),
           "analyzers": {"data": {"skill": "my-an", "skill_dir": str(skill)},
                         "sim": {"skill": "my-an", "skill_dir": str(skill)},
                         "call": {"skill": "missing", "skill_dir": str(tmp_path / "nope")},
                         "sms": {"when": "never"}}}
    roots = uc.read_roots(cfg, tmp_path / "plugin")
    assert roots == [str(tmp_path / "plugin" / "skills" / "telephony-triage"), str(tmp_path / "work"), str(skill)]
    assert uc.read_roots({}, tmp_path / "plugin") == [str(tmp_path / "plugin" / "skills" / "telephony-triage")]
