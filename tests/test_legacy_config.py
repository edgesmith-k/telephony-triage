"""옛 설정 키(jira → tracker 개명 전 형식) 감지와 fail-closed 관문, `config.py rename-legacy`.

자동 변환은 하지 않는다(사용자가 `rename-legacy --apply`로 확인 후 바꾼다). 옛 키가 하나라도 남아 있으면:
- guard: 모든 `mcp__` 호출 거부(옛 `jira:`를 무시하면 규칙 2의 설정 서버가 비어 쓰기가 열리므로)
- jira_bridge: 모든 `mcp__` 결과를 오류 문구로 대체(원문 미노출)
- `platforms.session.resolve`를 거치는 스크립트(triage·db_search 등)·`jira_fields`: 종료 2
- `config.py doctor`: `tracker` 행 fail(hint에 rename-legacy), `show`·`set`·`rename-legacy`는 돈다
site-defaults의 옛 키는 관리자가 고친다(`rename-legacy`는 안내만).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from runner import SAMPLE, plugin_root, run  # noqa: E402
from workspace import Workspace  # noqa: E402

from common import userconfig  # noqa: E402

KEY = "MOCK-1001"
MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
LOG = REPO / "tests" / "fixtures" / "logs" / "data-disabled.log"
READ = "mcp__mock-jira__jira_fetch_ticket"
SECRET = "데이터 안 됨 imsi=450081234567890"

# 사용자 config에 더할 옛 키 (이름 → 덮어쓸 최상위 값)
USER_LEGACY = {
    "user_jira_block": {"jira": {"mcp_server": "mock-jira"}},
    "user_year_source": {"logcat": {"year_source": "jira"}},
    "user_code_profile": {"code_profiles": [{"name": "a16", "android_version": "16", "roots": {}}]},
    "user_profile_code_profile": {"platforms": {"ofono": {"code_profiles": [{"name": "o2", "android_version": "2"}]}}},
    "user_field_map": {"tracker": {"field_map": {"android_version": "fields.customfield_10004"}}},
}

_WS: Workspace | None = None
_SAVED = ""


def ws() -> Workspace:
    global _WS, _SAVED
    if _WS is None:
        _WS = Workspace()
        _SAVED = (_WS.home / "config.yaml").read_text(encoding="utf-8")
    (_WS.home / "config.yaml").write_text(_SAVED, encoding="utf-8")
    return _WS


def set_user(w: Workspace, extra: dict) -> None:
    data = yaml.safe_load(_SAVED)
    for key, value in extra.items():
        data[key] = userconfig.deep_merge(data.get(key) or {}, value) if isinstance(value, dict) and \
            isinstance(data.get(key), dict) else value
    (w.home / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def guard(w: Workspace, tool: str, tool_input: dict, root: Path | None = None) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(w.base)}
    proc = run("guard.py", [], root=root or w.root, cwd=w.base, env=w.env(), stdin=json.dumps(event))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else {}


def bridge(w: Workspace, root: Path | None = None) -> str:
    issue = {"key": KEY, "fields": {"summary": SECRET, "description": "재현"}}
    event = {"hook_event_name": "PostToolUse", "tool_name": READ, "tool_input": {"ticket": KEY},
             "tool_response": json.dumps(issue, ensure_ascii=False)}
    proc = run("jira_bridge.py", [], root=root or w.root, cwd=w.base, env=w.env(), stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"] if proc.stdout.strip() else ""


# -- legacy_problems 조합 -------------------------------------------------------------------------


@pytest.mark.parametrize("site,user,expect", [
    ({}, {}, []),
    ({"tracker": {"kind": "jira"}}, {"tracker": {"mcp_server": "x"}}, []),
    ({"jira": {"mcp_server": "x"}}, {}, ["site-defaults: 옛 키 `jira:`"]),                       # site만
    ({"tracker": {}, "jira": {}}, {}, ["site-defaults: 옛 키 `jira:`"]),                         # 새 블록이 함께 있어도
    ({}, {"jira": {"mcp_server": "x"}}, ["사용자 config: 옛 키 `jira:`"]),                         # 사용자만
    ({"jira": {}}, {"jira": {}}, ["site-defaults: 옛 키 `jira:`", "사용자 config: 옛 키 `jira:`"]),  # 둘 다
    ({"logcat": {"year_source": "jira"}}, {}, ["site-defaults: `logcat.year_source: jira`"]),
    ({}, {"logcat": {"year_source": "jira"}}, ["사용자 config: `logcat.year_source: jira`"]),
    ({}, {"code_profiles": [{"name": "a", "android_version": "16"}]}, ["`code_profiles[0].android_version`"]),
    ({}, {"platforms": {"ofono": {"code_profiles": [{"android_version": "2"}]}}},
     ["`platforms.ofono.code_profiles[0].android_version`"]),
    ({"tracker": {"field_map": {"android_version": "f"}}}, {}, ["site-defaults: `tracker.field_map.android_version`"]),
    ({}, {"tracker": {"field_map": {"android_version": "f"}}}, ["사용자 config: `tracker.field_map.android_version`"]),
])
def test_legacy_problems_combinations(site, user, expect):
    got = userconfig.legacy_problems(site, user)
    assert len(got) == len(expect), got
    for needle, line in zip(expect, got):
        assert needle in line, (needle, line)


def test_rename_legacy_converts_every_key_and_keeps_values():
    user = {"user": {"ghe_id": "u"},
            "jira": {"mcp_server": "m", "field_map": {"android_version": "f4", "sw": "f3"}},
            "logcat": {"year_source": "jira", "timezone": "UTC"},
            "code_profiles": [{"name": "a", "android_version": "16", "roots": {"aosp": "/x"}}],
            "platforms": {"ofono": {"code_profiles": [{"name": "o", "android_version": "2"}]}}}
    new, changes = userconfig.rename_legacy(user)
    assert list(new) == ["user", "tracker", "logcat", "code_profiles", "platforms"]       # 자리 유지
    assert new["tracker"] == {"kind": "jira", "mcp_server": "m", "field_map": {"platform_version": "f4", "sw": "f3"}}
    assert new["logcat"] == {"year_source": "tracker", "timezone": "UTC"}
    assert new["code_profiles"] == [{"name": "a", "platform_version": "16", "roots": {"aosp": "/x"}}]
    assert new["platforms"]["ofono"]["code_profiles"] == [{"name": "o", "platform_version": "2"}]
    assert len(changes) == 5 and userconfig.legacy_problems({}, new) == []
    assert user["jira"]["mcp_server"] == "m" and "tracker" not in user                    # 원본은 그대로
    assert userconfig.rename_legacy(new) == (new, [])                                     # 멱등


def test_rename_legacy_merges_existing_tracker_block_with_tracker_values_winning():
    new, changes = userconfig.rename_legacy({"jira": {"mcp_server": "old", "timezone": "UTC"},
                                             "tracker": {"mcp_server": "new"}})
    assert new == {"tracker": {"kind": "jira", "mcp_server": "new", "timezone": "UTC"}}
    assert "합침" in changes[0]


# -- 관문 -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(USER_LEGACY))
def test_user_legacy_keys_close_every_gate(name):
    w = ws()
    set_user(w, USER_LEGACY[name])
    for tool, tool_input in ((READ, {"ticket": KEY}),                                  # 설정 서버 읽기도
                             ("mcp__corp-x__update_issue", {"key": KEY}),               # 이름 휴리스틱 밖 쓰기
                             ("mcp__github__get_file_contents", {"owner": "a", "repo": "b"})):
        out = guard(w, tool, tool_input)
        assert out.get("permissionDecision") == "deny" and "옛 설정 키" in out["permissionDecisionReason"], (name, tool)
        assert "rename-legacy" in out["permissionDecisionReason"]
    text = bridge(w)
    assert "옛 설정 키" in text and SECRET not in text and "imsi" not in text, name
    for script, args in (("triage.py", ["run", KEY, "--dry-run", "--issue-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", LOG]),
                         ("db_search.py", [KEY]),
                         ("jira_fields.py", ["check-key", KEY, "--db", SAMPLE])):
        proc = w.run(script, args)
        assert proc.returncode == 2 and "옛 설정 키" in proc.stderr and "rename-legacy" in proc.stderr, (name, script)
    rows = {r["check"]: r for r in w.json("config.py", ["doctor", "--format", "json"], expect=1)["rows"]}
    assert rows["tracker"]["status"] == "fail" and "rename-legacy" in rows["tracker"]["next"], name
    shown = w.run("config.py", ["show", "--keys", "work_dir"])
    assert shown.returncode == 0 and "rename-legacy" in shown.stderr
    assert w.run("config.py", ["set", "tracker.timezone", "UTC"]).returncode == 0
    assert w.run("config.py", ["check", "--for", "dry-run"]).returncode == 2


def test_site_legacy_block_closes_guard_and_bridge_even_with_new_block():
    w = ws()
    root = plugin_root("legacy-site", jira={"mcp_server": "mock-jira"})       # tracker: 블록과 함께 옛 jira:
    out = guard(w, READ, {"ticket": KEY}, root=root)
    assert out.get("permissionDecision") == "deny" and "site-defaults" in out["permissionDecisionReason"]
    assert "옛 설정 키" in bridge(w, root=root)
    proc = run("config.py", ["rename-legacy"], root=root, env=w.env(), cwd=w.base)
    doc = json.loads(proc.stdout)
    assert proc.returncode == 0 and doc["site_problems"] and doc["changes"] == [] and "관리자" in doc["site_next"]


def test_clean_config_passes_gates():
    w = ws()
    assert guard(w, READ, {"ticket": KEY}).get("permissionDecision") is None       # 허용 목록 읽기는 판정 없음(allow)
    assert "옛 설정 키" not in bridge(w)
    assert w.run("jira_fields.py", ["check-key", KEY, "--db", SAMPLE]).returncode == 0
    assert w.json("config.py", ["rename-legacy"])["changes"] == []


# -- config.py rename-legacy ------------------------------------------------------------------------


def test_rename_legacy_lists_changes_and_writes_only_with_apply():
    w = ws()
    set_user(w, {**USER_LEGACY["user_jira_block"], **USER_LEGACY["user_year_source"],
                 **USER_LEGACY["user_profile_code_profile"]})
    path = w.home / "config.yaml"
    before = path.read_text(encoding="utf-8")
    dry = w.json("config.py", ["rename-legacy"])
    assert dry["applied"] is False and path.read_text(encoding="utf-8") == before
    assert dry["changes"] == ["jira: → tracker: (+ kind: jira)", "logcat.year_source: jira → tracker",
                              "platforms.ofono.code_profiles[0].android_version → platform_version"]
    assert dry["remaining"] and "--apply" in dry["next"]
    done = w.json("config.py", ["rename-legacy", "--apply"])
    assert done["applied"] is True and done["remaining"] == []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "jira" not in data and data["tracker"]["kind"] == "jira" and data["tracker"]["mcp_server"] == "mock-jira"
    assert data["platforms"]["ofono"]["code_profiles"][0] == {"name": "o2", "platform_version": "2"}
    assert data["issue_db"] == yaml.safe_load(before)["issue_db"]                    # 다른 키는 그대로
    rows = {r["check"]: r for r in w.json("config.py", ["doctor", "--format", "json"], expect=(0, 1))["rows"]}
    assert rows["tracker"]["status"] == "ok"
    assert w.run("jira_fields.py", ["check-key", KEY, "--db", SAMPLE]).returncode == 0
    assert w.json("config.py", ["rename-legacy", "--apply"])["changes"] == []          # 다시 해도 바꿀 것 없음


def test_rename_legacy_apply_refuses_write_like_tracker_tools():
    """옛 `jira.read_tools`는 set 검사를 안 거친다 — 쓰기형 이름이면 `--apply`가 종료 2·config 바이트 그대로(규칙 2)."""
    w = ws()
    path = w.home / "config.yaml"
    set_user(w, {"jira": {"mcp_server": "mock-jira", "read_tools": [READ, "mcp__mock-jira__jira_update_issue"]}})
    before = path.read_bytes()
    proc = w.run("config.py", ["rename-legacy", "--apply"])
    assert proc.returncode == 2 and "jira_update_issue" in proc.stderr, proc.stdout + proc.stderr
    assert path.read_bytes() == before
    set_user(w, {"jira": {"mcp_server": "mock-jira", "read_tools": [READ]}})
    assert w.json("config.py", ["rename-legacy", "--apply"])["applied"] is True
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["tracker"]["read_tools"] == [READ]


# -- 없어진 키 issue_db.merge (+1 병합, H A2 — 경고만, fail-closed 아님) -------------------------------------

REMOVED_USER = {
    "user_top": {"issue_db": {"merge": "review"}},
    "user_profile": {"platforms": {"ofono": {"issue_db": {"merge": "self"}}}},
}


def _check(w: Workspace, root: Path | None = None):
    proc = run("config.py", ["check", "--for", "dry-run"], root=root or w.root, env=w.env(), cwd=w.base)
    return proc, json.loads(proc.stdout)


@pytest.mark.parametrize("name", sorted(REMOVED_USER))
def test_removed_merge_key_in_user_config_only_warns(name):
    w = ws()
    base_proc, base = _check(w)
    assert base["warnings"] == [] and "issue_db.merge" not in base_proc.stderr
    set_user(w, REMOVED_USER[name])
    data = yaml.safe_load((w.home / "config.yaml").read_text(encoding="utf-8"))
    proc, doc = _check(w)
    assert proc.returncode == base_proc.returncode and doc["writable"] == base["writable"], name     # 종료 코드·writable 그대로
    assert doc["push_allowed"] == base["push_allowed"] and len(doc["warnings"]) == 1, name
    at = "platforms.ofono.issue_db.merge" if name == "user_profile" else "`issue_db.merge`"
    assert at in doc["warnings"][0] and doc["warnings"][0].startswith("사용자 config: ") and at in proc.stderr, name
    assert userconfig.legacy_problems({}, data) == [], name                     # fail-closed 관문에는 넣지 않는다
    rows = {r["check"]: r for r in w.json("config.py", ["doctor", "--format", "json"], expect=(0, 1))["rows"]}
    assert rows["config"]["status"] == "warn" and "issue_db.merge" in rows["config"]["detail"], name
    assert rows["tracker"]["status"] == "ok", name
    assert guard(w, READ, {"ticket": KEY}).get("permissionDecision") is None, name    # guard는 닫히지 않는다


def test_removed_merge_key_in_site_defaults_only_warns_and_wait_seconds_still_flows():
    w = ws()
    root = plugin_root("removed-merge-site", issue_db={"merge": "self", "merge_wait_seconds": 30})
    proc, doc = _check(w, root)
    base_proc, base = _check(w)
    assert proc.returncode == base_proc.returncode and doc["writable"] == base["writable"]
    assert len(doc["warnings"]) == 1 and doc["warnings"][0].startswith("site-defaults: ") and "관리자" in doc["warnings"][0]
    assert guard(w, READ, {"ticket": KEY}, root=root).get("permissionDecision") is None
    doctor = run("config.py", ["doctor", "--format", "json"], root=root, env=w.env(), cwd=w.base)
    rows = {r["check"]: r for r in json.loads(doctor.stdout)["rows"]}
    assert rows["config"]["status"] == "warn" and "관리자" in rows["config"]["next"]
    defaults = {"issue_db": {"merge": "self", "merge_wait_seconds": 30}}
    assert userconfig.legacy_problems(defaults, None) == []
    top = userconfig.merged(defaults, {})
    assert "merge" not in top["issue_db"] and top["issue_db"]["merge_wait_seconds"] == 30      # 대기 기본값은 그대로 흐른다
    prof = userconfig.merged(defaults, {"platforms": {"ofono": {"issue_db": {"path": "/x"}}}}, platform="ofono")
    assert "merge" not in prof["issue_db"] and prof["issue_db"]["merge_wait_seconds"] == 30
    assert userconfig.SITE_ISSUE_DB_KEYS == ("merge_wait_seconds", "remote")
    assert userconfig.removed_keys(None, None) == [] and userconfig.removed_keys({"issue_db": "x"}, {"platforms": 1}) == []


# -- 폐지 하위 키 analyzers.<cat>.inputs·max_tokens_hint (B1 설계 §2.3·§3.1·§9.1 예외 2 — 경고만, fail-closed 아님) ---------

DEPRECATED_USER = {
    "user_top": {"analyzers": {"data": {"inputs": ["events_json"]}}},
    "user_profile": {"platforms": {"ofono": {"analyzers": {"data": {"max_tokens_hint": "medium"}}}}},
}


@pytest.mark.parametrize("name", sorted(DEPRECATED_USER))
def test_deprecated_analyzer_keys_in_user_config_only_warn(name):
    w = ws()
    base_proc, base = _check(w)
    set_user(w, DEPRECATED_USER[name])
    data = yaml.safe_load((w.home / "config.yaml").read_text(encoding="utf-8"))
    proc, doc = _check(w)
    assert proc.returncode == base_proc.returncode and doc["writable"] == base["writable"], name
    assert len(doc["warnings"]) == 1 and doc["warnings"][0].startswith("사용자 config: 폐지 키 `"), name
    assert userconfig.legacy_problems({}, data) == [], name
    rows = {r["check"]: r for r in w.json("config.py", ["doctor", "--format", "json"], expect=(0, 1))["rows"]}
    assert rows["config"]["status"] == "warn" and "max_tokens_hint" in rows["config"]["detail"], name
    assert guard(w, READ, {"ticket": KEY}).get("permissionDecision") is None, name


def test_old_example_deprecated_warning_pinned():
    """의도한 변경(B1 설계 §9.1 예외 2): 옛 예시(analyzers.data에 inputs·max_tokens_hint)를 복사한 사내 site-defaults는 remote가
    없어도 check 경고 두 줄과 doctor `config` 행 warn을 받는다. 관리자가 두 줄을 지우면 사라진다."""
    w = ws()
    old = {"data": {"skill": "mock-data-analyzer", "when": "ask",
                    "inputs": ["events_json", "log_paths", "top_candidates", "issue_summary"], "max_tokens_hint": "medium"}}
    root = plugin_root("old-example-analyzers", analyzers=old)
    _proc, doc = _check(w, root)
    assert doc["warnings"] == [
        "site-defaults: 폐지 키 `analyzers.data.inputs`는 읽지 않는다(무시) — 그 줄을 지운다 (관리자)",
        "site-defaults: 폐지 키 `analyzers.data.max_tokens_hint`는 읽지 않는다(무시) — 그 줄을 지운다 (관리자)"]
    doctor = run("config.py", ["doctor", "--format", "json"], root=root, env=w.env(), cwd=w.base)
    rows = {r["check"]: r for r in json.loads(doctor.stdout)["rows"]}
    assert rows["config"] == {"check": "config", "status": "warn",
                              "detail": "폐지 키 analyzers.<카테고리>.inputs·max_tokens_hint(무시)",
                              "next": "그 줄을 지운다 · site-defaults면 관리자"}
    assert "module_skills" not in rows
