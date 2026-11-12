#!/usr/bin/env python3
"""Phase 6 완료 기준 확인: 설정, 코드 경로, setup (11-phases.md Phase 6).

사용자 config 위치는 `TELEPHONY_TRIAGE_HOME`으로 임시 디렉토리에 둔다(실제 홈을 건드리지 않는다).
이슈 DB는 `tests/helpers/make_repo.py`가 만든 모의 원격(bare)과 사용자 clone을 쓴다.

`pytest tests/test_config_setup.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import make_plugin_root  # noqa: E402
import make_repo  # noqa: E402
from runner import SAMPLE, edit, git, plugin_root, run, tmp  # noqa: E402

MCP_CONFIG = REPO / "tests" / "mocks" / "mcp.json"
SRC = REPO / "tests" / "mocks" / "src"
POSIX = os.name != "nt"


class Env:
    """임시 사용자 홈 하나와 그 환경에서 스크립트를 부르는 도우미."""

    def __init__(self, root: Path | None = None, **extra):
        self.base = tmp("tt-setup-")
        self.home = self.base / "home"
        self.root = root or plugin_root()
        self.extra = extra

    def run(self, script, args, **kw):
        env = {"TELEPHONY_TRIAGE_HOME": self.home, **self.extra, **kw.pop("env", {})}
        return run(script, args, root=kw.pop("root", self.root), env=env, cwd=kw.pop("cwd", REPO), **kw)

    def json(self, script, args, expect=0, **kw):
        proc = self.run(script, args, **kw)
        assert proc.returncode == expect, f"{script} {args}: {proc.returncode}\n{proc.stderr}\n{proc.stdout}"
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def config(self) -> dict:
        return yaml.safe_load((self.home / "config.yaml").read_text(encoding="utf-8"))

    def init(self, clone: Path, **over) -> dict:
        answers = {"user.ghe_id": "mock-user1", "issue_db.path": str(clone),
                   "issue_db.remote": "https://ghe.mock.invalid/mock-org/telephony-issue-db.git",
                   "work_dir": str(self.base / "work"), **over}
        path = self.base / "answers.json"
        path.write_text(json.dumps(answers), encoding="utf-8")
        return self.json("config.py", ["init", "--answers", path])


def _repo() -> dict:
    return make_repo.make(SAMPLE, tmp("tt-remote-") / "r")


# -- config 생성 ---------------------------------------------------------------------


def test_init_interactive_rejects_bad_paths():
    env = Env()
    clone = env.base / "db"
    lines = [
        "mock-user1",                          # GHE 아이디
        str(env.base / "no-parent" / "x" / "db"),  # 거부: 상위 디렉토리 없음
        str(clone),                            # 이슈 DB 경로 (아직 없음 → clone 제안)
        "https://ghe.mock.invalid/mock-org/telephony-issue-db.git",
        "",                                    # base 브랜치 → main
        "",                                    # GHE 호스트 → site-defaults 값
        "",                                    # Jira 타임존 → site-defaults 값
        "Mars/Olympus",                        # 거부: 모르는 타임존
        "UTC",
        "sometimes",                           # 거부: year_source
        "tracker",
        str(env.base / "no-logs"),             # 거부: 없는 디렉토리
        "",                                    # log_dir 건너뜀
        str(env.base / "work"),
    ]
    proc = env.run("config.py", ["init"], stdin="\n".join(lines) + "\n")
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.count("거부") == 4
    result = json.loads(proc.stdout)
    assert result["suggest_clone"].startswith("git clone https://ghe.mock.invalid/")
    cfg = env.config()
    # 팀 기본값과 같은 답(base_branch·ghe_host·tracker.timezone·year_source)은 저장하지 않고 상속한다
    assert cfg["issue_db"] == {"path": str(clone), "remote": "https://ghe.mock.invalid/mock-org/telephony-issue-db.git"}
    assert "tracker" not in cfg and cfg["logcat"] == {"timezone": "UTC"} and "log_dir" not in cfg
    eff = env.json("config.py", ["show", "--keys", "issue_db.base_branch,issue_db.ghe_host,tracker.timezone"])["values"]
    assert eff == {"issue_db.base_branch": "main", "issue_db.ghe_host": "ghe.mock.invalid", "tracker.timezone": "Asia/Seoul"}
    assert cfg["plugin"]["scripts_path"] == str(env.root / "scripts")
    assert (env.base / "work").is_dir()
    if POSIX:
        for p in (env.home, env.base / "work"):
            assert stat.S_IMODE(p.stat().st_mode) == 0o700, p

    # --answers 경로도 잘못된 경로를 거부한다
    other = Env()
    bad = other.base / "a.json"
    bad.write_text(json.dumps({"user.ghe_id": "u", "issue_db.path": str(other.base / "x/y/z"),
                               "issue_db.remote": "r", "log_dir": str(other.base / "nope")}), encoding="utf-8")
    proc = other.run("config.py", ["init", "--answers", bad])
    assert proc.returncode == 2 and "issue_db.path" in proc.stderr and "log_dir" in proc.stderr
    assert not (other.home / "config.yaml").exists()


def test_init_saves_only_answers_so_team_default_changes_flow_through():
    root = make_plugin_root.make()      # 캐시된 plugin_root()의 site-defaults를 고치지 않도록 새 루트
    env = Env(root=root)
    env.init(env.base / "db")
    assert "explore" not in env.config() and "tracker" not in env.config()
    assert env.json("config.py", ["show", "--keys", "explore.when"])["values"] == {"explore.when": "ask"}
    path = root / "site-defaults.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["explore"]["when"] = "never"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")
    assert env.json("config.py", ["show", "--keys", "explore.when"])["values"] == {"explore.when": "never"}


def test_site_issue_db_remote_is_team_default_per_platform():
    """setup 질문 10→3(코덱스 리뷰 A①): site-defaults `issue_db.remote`가 있으면 init이 원격을 묻지 않고 상속한다.
    플랫폼마다 이슈 DB가 다르므로 `platforms.<p>.issue_db.remote`가 그 플랫폼 값이고 최상위 값은 물려받지 않는다
    (merge_wait_seconds는 최상위 → platforms.<p> 순). 상속 순서를 여기서 고정한다."""
    top = "https://ghe.mock.invalid/mock-org/telephony-issue-db.git"
    ofono = "https://ghe.mock.invalid/mock-org/telephony-issue-db-ofono.git"
    on = {"name": "android", "enabled": ["android", "ofono"]}
    root = plugin_root("site-remote", issue_db={"merge_wait_seconds": 420, "remote": top}, platform=on,
                       platforms={"ofono": {"issue_db": {"remote": ofono, "merge_wait_seconds": 60}}})
    env = Env(root=root)

    def answers(name: str, **data) -> Path:
        path = env.base / f"{name}.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    # android: 원격을 답하지 않아도 되고(팀 기본값), 저장하지 않는다
    result = env.json("config.py", ["init", "--answers", answers(
        "a", **{"user.ghe_id": "mock-user1", "issue_db.path": str(env.base / "db"), "work_dir": str(env.base / "work")})])
    assert result["suggest_clone"] == f"git clone {top} {env.base / 'db'}"
    assert "remote" not in env.config()["issue_db"]
    assert env.json("config.py", ["show", "--keys", "issue_db.remote,issue_db.merge_wait_seconds"])["values"] == {
        "issue_db.remote": top, "issue_db.merge_wait_seconds": 420}
    # ofono 프로필: 그 플랫폼의 site 값. 빈 답("")도 상속이다
    env.json("config.py", ["init", "--platform", "ofono", "--answers", answers(
        "o", **{"issue_db.path": str(env.base / "db-ofono"), "issue_db.remote": "", "work_dir": str(env.base / "work-ofono")})])
    assert "remote" not in env.config()["platforms"]["ofono"]["issue_db"]
    assert env.json("config.py", ["show", "--platform", "ofono", "--keys", "issue_db.remote,issue_db.merge_wait_seconds"])["values"] == {
        "issue_db.remote": ofono, "issue_db.merge_wait_seconds": 60}

    # 상속 순서(merged): 사용자 config > site platforms.<p>.issue_db > site issue_db(remote는 제외) > 내장
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import userconfig
    site = {"issue_db": {"remote": top, "merge_wait_seconds": 30},
            "platforms": {"ofono": {"issue_db": {"remote": ofono}}, "other": {"issue_db": {"merge_wait_seconds": 60}}}}
    assert userconfig.merged(site, {})["issue_db"] == {"base_branch": "main", "remote": top, "merge_wait_seconds": 30}
    assert userconfig.merged(site, {}, platform="ofono")["issue_db"] == {"base_branch": "main", "remote": ofono, "merge_wait_seconds": 30}
    assert userconfig.merged(site, {}, platform="other")["issue_db"] == {"base_branch": "main", "merge_wait_seconds": 60}   # 최상위 remote는 안 내려간다
    user = {"issue_db": {"remote": "https://ghe.mock.invalid/me/a.git"},
            "platforms": {"ofono": {"issue_db": {"path": "/x", "remote": "https://ghe.mock.invalid/me/o.git"}}}}
    assert userconfig.merged(site, user)["issue_db"]["remote"] == "https://ghe.mock.invalid/me/a.git"
    assert userconfig.merged(site, user, platform="ofono")["issue_db"]["remote"] == "https://ghe.mock.invalid/me/o.git"

    # site에 그 플랫폼 remote가 없으면 init은 전처럼 원격을 요구한다(android 것을 쓰지 않는다)
    root2 = plugin_root("site-remote-top-only", issue_db={"merge_wait_seconds": 420, "remote": top}, platform=on)
    env2 = Env(root=root2)
    proc = env2.run("config.py", ["init", "--platform", "ofono", "--answers", answers(
        "o2", **{"user.ghe_id": "mock-user1", "issue_db.path": str(env2.base / "db-ofono"), "work_dir": str(env2.base / "work-ofono")})])
    assert proc.returncode == 2 and "issue_db.remote: 값이 필요합니다" in proc.stderr
    assert not (env2.home / "config.yaml").exists()


def test_inherited_team_remote_is_not_copied_and_counts_for_overlap():
    """리뷰 후속(코덱스 리뷰 A①② 후속): (1) 대화형 init에서 원격을 Enter(팀 기본값)로 넘기면 복사해 저장하지 않는다.
    (2) site에서 물려받은 android 원격도 프로필 원격 겹침 검사에 든다 — ofono에 같은 원격을 주면 거부한다.
    (3) 물려받을 팀 원격이 owner/repo로 풀리지 않으면 init이 clone을 제안하지 않고 관리자에게 돌린다."""
    top = "https://ghe.mock.invalid/mock-org/telephony-issue-db.git"
    on = {"name": "android", "enabled": ["android", "ofono"]}
    env = Env(root=plugin_root("site-remote-inherit", issue_db={"remote": top}, platform=on))
    lines = ["mock-user1", str(env.base / "db"), "", "", "", "", "", "", "", str(env.base / "work")]   # 원격~log_dir Enter
    proc = env.run("config.py", ["init"], stdin="\n".join(lines) + "\n")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["suggest_clone"] == f"git clone {top} {env.base / 'db'}"
    assert env.config()["issue_db"] == {"path": str(env.base / "db")}       # remote는 상속(복사하지 않음)

    answers = env.base / "o.json"
    answers.write_text(json.dumps({"issue_db.path": str(env.base / "db-ofono"), "issue_db.remote": top.upper()}), encoding="utf-8")
    proc = env.run("config.py", ["init", "--platform", "ofono", "--answers", answers])
    assert proc.returncode == 2 and "platforms.ofono.issue_db.remote: issue_db.remote(site-defaults)와 같은 원격" in proc.stderr
    assert "platforms" not in env.config()
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import userconfig
    a, o = str(env.base / "a"), str(env.base / "o")
    user = {"issue_db": {"path": a}, "platforms": {"ofono": {"issue_db": {"path": o, "remote": top}}}}
    assert userconfig.profile_problems(user) == []                          # defaults 없이는 이전과 같다
    assert userconfig.profile_problems(user, {"issue_db": {"remote": top}})
    both = {"issue_db": {"remote": top}, "platforms": {"ofono": {"issue_db": {"remote": top}}}}
    assert userconfig.profile_problems({**user, "platforms": {"ofono": {"issue_db": {"path": o}}}}, both) == []  # site 문제

    bad = Env(root=plugin_root("site-remote-bad", issue_db={"remote": "/local/db"}))
    answers = bad.base / "a.json"
    answers.write_text(json.dumps({"user.ghe_id": "mock-user1", "issue_db.path": str(bad.base / "db")}), encoding="utf-8")
    proc = bad.run("config.py", ["init", "--answers", answers])
    assert proc.returncode == 2 and "site-defaults는 관리자" in proc.stderr and not (bad.home / "config.yaml").exists()


def test_init_without_site_remote_still_requires_remote():
    """음성 경로(a): site-defaults에 issue_db.remote가 없으면(사외 초안 example 그대로) init은 전처럼 원격을 요구한다."""
    env = Env()
    path = env.base / "a.json"
    path.write_text(json.dumps({"user.ghe_id": "mock-user1", "issue_db.path": str(env.base / "db"),
                                "work_dir": str(env.base / "work")}), encoding="utf-8")
    proc = env.run("config.py", ["init", "--answers", path])
    assert proc.returncode == 2 and "issue_db.remote: 값이 필요합니다" in proc.stderr
    assert not (env.home / "config.yaml").exists()
    assert env.json("config.py", ["show", "--keys", "issue_db.remote"])["missing"] == ["issue_db.remote"]


def test_gh_status_login_is_the_site_host_login_only():
    """setup 1 GHE 아이디 자동 감지(코덱스 리뷰 A①): `gh-status`의 `login`은 site ghe.host와 같은 호스트의 로그인만이다.
    다른 호스트 로그인이 앞에 나와도(gh ≥2.40 `account` 문구) 그것을 쓰지 않고, 그 호스트 줄이 없으면 null(setup이 묻는다)."""
    env = Env()
    env.init(env.base / "db")
    one = env.json("config.py", ["gh-status"])
    assert one["ok"] is True and one["host"] == "ghe.mock.invalid" and one["login"]
    two = env.json("config.py", ["gh-status"], env={"MOCK_GH_OTHER_LOGINS": "github.com:someone-else"})
    assert two["login"] == one["login"] != "someone-else"
    unauth = env.run("config.py", ["gh-status"], unauth=True)
    assert unauth.returncode == 2 and json.loads(unauth.stdout)["login"] is None
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import ghcli
    text = "github.com\n  ✓ Logged in to github.com account someone-else (keyring)\n  - Active account: true"
    assert ghcli.login(text, "ghe.mock.invalid") is None and ghcli.login(text, "GitHub.com") == "someone-else"
    assert ghcli.login("ghe.mock.invalid\n  - Logged in to ghe.mock.invalid as me (oauth_token)", "ghe.mock.invalid") == "me"
    assert ghcli.login(text, None) is None


def test_set_and_sync_scripts_path():
    env = Env()
    env.init(env.base / "db")
    assert env.run("config.py", ["set", "log_dir", env.base / "nope"]).returncode == 2
    (env.base / "logs").mkdir()
    env.json("config.py", ["set", "log_dir", env.base / "logs"])
    env.json("config.py", ["set", "logcat.year_source", "file-mtime"])
    assert env.run("config.py", ["set", "logcat.year_source", "never"]).returncode == 2
    cfg = env.config()
    assert cfg["log_dir"] == str(env.base / "logs") and cfg["logcat"]["year_source"] == "file-mtime"
    other_root = make_plugin_root.make()
    result = env.json("config.py", ["sync-scripts-path"], root=other_root)
    assert result["changed"] is True and env.config()["plugin"]["scripts_path"] == str(other_root / "scripts")


def test_issue_db_remote_must_resolve_to_owner_repo():
    """H-A1 r6: `issue_db.remote`는 owner/repo로 풀려야 한다(`userconfig.repo_slug` — guard 규칙 11이 대상 비교에 쓴다. 못 풀면
    규칙 11이 조용히 꺼진다). init·set은 거부하고, user 없는 SCP 꼴(`<SSH 별칭>:o/r.git`)·`git@host:o/r.git`은 받는다."""
    env = Env()
    env.init(env.base / "db")
    for bad in ("/srv/git/telephony-issue-db.git", "telephony-issue-db", "file:///srv/o/r.git"):
        proc = env.run("config.py", ["set", "issue_db.remote", bad])
        assert proc.returncode == 2 and "owner/repo" in proc.stderr, bad
    for good in ("ghe-ssh:mock-org/telephony-issue-db.git", "git@ghe.mock.invalid:mock-org/telephony-issue-db.git",
                 # 숫자뿐인 owner의 SCP 꼴은 owner다(포트가 아니다 — 회귀 수정 R3). gh `-R`의 HOST:PORT/OWNER/REPO도 받는다
                 "git@ghe.mock.invalid:1234/telephony-issue-db.git", "ghe-ssh:20231234/telephony-issue-db.git",
                 "ghe.mock.invalid:8443/mock-org/telephony-issue-db"):
        env.json("config.py", ["set", "issue_db.remote", good])
        assert env.config()["issue_db"]["remote"] == good
    other = Env()
    with pytest.raises(AssertionError):
        other.init(other.base / "db", **{"issue_db.remote": "telephony-issue-db"})
    assert not (other.home / "config.yaml").exists()


def test_doctor_unresolvable_remote_fails_config_row():
    """H-A1 r6: 사용자 config를 손으로 고쳐 `issue_db.remote`가 owner/repo로 풀리지 않으면 doctor `config` 행 fail(규칙 11이 꺼진다)."""
    env, _ = _ready_env()
    cfg = env.config()
    cfg["issue_db"]["remote"] = "/srv/git/telephony-issue-db.git"
    (env.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    row = _rows(_doctor(env, expect=1))["config"]
    assert row["status"] == "fail" and "규칙 11" in row["detail"] and "config.py set issue_db.remote" in row["next"]


def test_set_issue_db_path_hints_old_snapshot_cleanup():
    """issue_db.path를 바꿨고 옛 읽기 스냅샷이 있으면 정리 방법 한 줄(hint·stderr). 없거나 같은 값이면 없다."""
    env = Env()
    env.init(env.base / "db")
    out = env.json("config.py", ["set", "issue_db.path", env.base / "db2"])
    assert "hint" not in out                                         # 스냅샷 없음
    (env.base / "work" / "_snapshot").mkdir(parents=True)
    proc = env.run("config.py", ["set", "issue_db.path", env.base / "db3"])
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and "worktree remove --force" in out["hint"] and str(env.base / "db2") in out["hint"]
    assert "안내:" in proc.stderr
    assert "hint" not in env.json("config.py", ["set", "issue_db.path", env.base / "db3"])   # 같은 값


# -- Jira MCP ------------------------------------------------------------------------


def test_jira_tools_from_nonstandard_mock_server():
    env = Env()  # 테스트 헬퍼 루트: exclude_servers: []
    env.init(env.base / "db")
    found = env.json("config.py", ["tracker-candidates", "--mcp-config", MCP_CONFIG])
    # mcp.json에는 모의 GitHub Issues 서버도 있다(표준 도구 이름이라 jira 설정에서도 읽기 후보가 잡힌다)
    assert found["usable"] == ["mock-github-issues", "mock-jira"] and found["exclude_servers"] == []
    server = next(s for s in found["servers"] if s["server"] == "mock-jira")
    assert server["suggested"] == {"get_issue": "mcp__mock-jira__jira_fetch_ticket",
                                   "search_issues": "mcp__mock-jira__jira_query_tickets",
                                   "get_comments": "mcp__mock-jira__jira_ticket_comments"}
    # 쓰기 도구는 후보가 아니다
    assert "mcp__mock-jira__jira_post_comment" in server["tools"]
    assert not any("post_comment" in t or "move_ticket" in t for t in server["read_tools"])

    # 사용자가 확인한 값을 저장한다. read_tools에는 tracker.tools 값이 들어간다(전체 이름)
    saved = env.json("config.py", ["set-tracker", "--server", "mock-jira",
                                   "--get-issue", "mcp__mock-jira__jira_fetch_ticket",
                                   "--search-issues", "mcp__mock-jira__jira_query_tickets",
                                   "--read-tools", "mcp__mock-jira__jira_ticket_comments"])
    assert saved["added_to_read_tools"] == ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets"]
    jira = env.config()["tracker"]
    assert jira["mcp_server"] == "mock-jira"
    assert jira["tools"] == {"get_issue": "mcp__mock-jira__jira_fetch_ticket",
                             "search_issues": "mcp__mock-jira__jira_query_tickets"}
    assert jira["read_tools"] == ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets",
                                  "mcp__mock-jira__jira_ticket_comments"]
    # 짧은 이름·다른 서버 도구는 거부
    assert env.run("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", "jira_fetch_ticket"]).returncode == 2
    assert env.run("config.py", ["set-tracker", "--server", "mock-jira",
                                 "--get-issue", "mcp__other__get_issue"]).returncode == 2


def test_jira_server_names_are_normalized_like_session_tool_names():
    """R-2: 세션 도구 이름은 서버 이름의 `[^A-Za-z0-9_-]`를 `_`로 쓴다(관측 기반 추정, S1 확인).
    후보는 세션 이름으로 만들고, set-tracker는 원래 서버 이름과 세션 이름을 같은 서버로 본다(저장값은 그대로)."""
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import mcptools
    assert mcptools.full_name("jira.corp", "x") == "mcp__jira_corp__x"
    assert mcptools.full_name("mock-jira", "x") == "mcp__mock-jira__x"
    once = mcptools.normalize("mcp__jira corp.v2__get_issue")
    assert once == "mcp__jira_corp_v2__get_issue" == mcptools.normalize(once)
    (entry,) = mcptools.candidates({"jira.corp": ["get_issue"]}, [], {"get_issue": "mcp__jira.corp__get_issue"})
    assert entry["tools"] == ["mcp__jira_corp__get_issue"] and entry["suggested"]["get_issue"] == "mcp__jira_corp__get_issue"

    env = Env()
    env.init(env.base / "db")
    saved = env.json("config.py", ["set-tracker", "--server", "jira.corp", "--get-issue", "mcp__jira_corp__get_issue"])
    assert saved["tools"]["get_issue"] == "mcp__jira_corp__get_issue" and env.config()["tracker"]["mcp_server"] == "jira.corp"
    assert env.run("config.py", ["set-tracker", "--server", "jira.corp",
                                 "--get-issue", "mcp__jira_other__get_issue"]).returncode == 2


def test_excluded_mock_servers():
    root = plugin_root("exclude-mock", tracker={**yaml.safe_load(
        (REPO / "plugin/site-defaults.example.yaml").read_text(encoding="utf-8"))["tracker"], "exclude_servers": ["mock-*"]})
    env = Env(root=root)
    found = env.json("config.py", ["tracker-candidates", "--mcp-config", MCP_CONFIG])
    assert found["usable"] == [] and found["servers"][0]["excluded"] is True
    assert found["servers"][0]["tools"] == [] and "중단" in found["next"]


# 가짜 stdio MCP 서버(사내 피드백 12: tracker-candidates 무응답). {mode}: answer(응답 뒤 끝나지 않음)·silent(응답 없음,
# 손자 프로세스가 stdout을 쥔다)·exit(바로 종료 3). {marker}: 띄워졌으면 만드는 파일
FAKE_MCP = '''import json, os, subprocess, sys, time
mode, marker = sys.argv[1], sys.argv[2]
open(marker, "a").close()
if mode == "exit":
    sys.exit(3)
if mode == "silent":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])   # stdout 상속(파이프를 쥔다)
    open(marker + ".pid", "w").write(str(child.pid))
    time.sleep(600)
for line in sys.stdin:
    m = json.loads(line)
    if m.get("method") == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {},
                          "serverInfo": {"name": "fake", "version": "0"}}}), flush=True)
    elif m.get("method") == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [{"name": "jira_get_issue"}]}}), flush=True)
        break
time.sleep(600)     # 응답 뒤에도(stdin EOF 뒤에도) 끝나지 않는다
'''


def _fake_mcp(base: Path, servers: dict[str, str | None]) -> Path:
    """`{서버: mode 또는 None(원격 url)}` → MCP 설정 JSON 경로. 띄워진 서버는 `<base>/<서버>.started`를 남긴다."""
    script = base / "fake_mcp.py"
    script.write_text(FAKE_MCP, encoding="utf-8")
    conf = {name: ({"command": sys.executable, "args": [str(script), mode, str(base / f"{name}.started")]} if mode
                   else {"type": "http", "url": "https://mcp.mock.invalid/x"}) for name, mode in servers.items()}
    path = base / "mcp.json"
    path.write_text(json.dumps({"mcpServers": conf}), encoding="utf-8")
    return path


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:    # 좀비(아직 거둬지지 않음)는 끝난 것으로 본다
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return True


def test_list_tools_returns_on_response_and_kills_process_group():
    """응답(`tools/list`) 뒤 끝나지 않는 서버도 바로 반환한다(이전: 타임아웃까지 기다린 뒤 오류). 응답 없는 서버는 timeout,
    손자 프로세스(stdout을 쥔다)까지 끝낸다. 바로 끝나는 서버는 exited(코드). 원격 서버는 not-stdio."""
    import time
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import mcptools
    base = tmp("tt-mcp-probe-")
    conf = json.loads(_fake_mcp(base, {"answer": "answer", "silent": "silent", "exit": "exit"})
                      .read_text(encoding="utf-8"))["mcpServers"]
    start = time.monotonic()
    assert mcptools.list_tools(conf["answer"]) == ["jira_get_issue"]
    assert time.monotonic() - start < 5, "응답을 받으면 서버가 끝나기를 기다리지 않는다"

    start = time.monotonic()
    with pytest.raises(mcptools.ProbeError) as err:
        mcptools.list_tools(conf["silent"], timeout=1.5)
    assert err.value.kind == "timeout" and str(err.value).startswith("timeout(1.5초)")
    assert time.monotonic() - start < 8, "손자가 파이프를 쥐어도 멈추지 않는다"
    if POSIX:
        pid = int((base / "silent.started.pid").read_text())
        deadline = time.monotonic() + 5
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(pid), "프로세스 그룹(손자 포함)을 끝낸다"

    with pytest.raises(mcptools.ProbeError) as err:
        mcptools.list_tools(conf["exit"])
    assert err.value.kind == "exited" and str(err.value).startswith("exited(3)")
    with pytest.raises(mcptools.ProbeError) as err:
        mcptools.list_tools({"type": "http", "url": "https://mcp.mock.invalid/x"})
    assert err.value.kind == "not-stdio"


def test_tracker_candidates_reports_probe_diagnostics():
    """servers[].{probe, elapsed_ms, error}와 stderr 진행 줄(서버 이름·시간·결과 종류만). `--tools-json`의 서버는 이름
    정규화(`jira.corp` = 세션 이름 `jira_corp`)로 비교해 다시 띄우지 않는다."""
    env = Env()  # 테스트 헬퍼 루트: exclude_servers: []
    base = tmp("tt-mcp-cand-")
    mcp = _fake_mcp(base, {"fake-jira": "answer", "fake-exit": "exit", "jira.corp": "answer", "remote-jira": None})
    tools = base / "tools.json"
    tools.write_text(json.dumps({"jira_corp": ["mcp__jira_corp__jira_get_issue"]}), encoding="utf-8")
    proc = env.run("config.py", ["tracker-candidates", "--mcp-config", mcp, "--tools-json", tools])
    assert proc.returncode == 0, proc.stderr
    found = {s["server"]: s for s in json.loads(proc.stdout)["servers"]}
    assert set(found) == {"fake-jira", "fake-exit", "jira_corp", "remote-jira"}
    assert found["fake-jira"]["probe"] == "stdio" and found["fake-jira"]["error"] is None
    assert 0 < found["fake-jira"]["elapsed_ms"] < 5000
    assert found["fake-jira"]["suggested"]["get_issue"] == "mcp__fake-jira__jira_get_issue"
    assert found["fake-exit"]["probe"] == "stdio" and found["fake-exit"]["error"].startswith("exited(3)")
    assert found["jira_corp"]["probe"] == "tools-json" and found["jira_corp"]["elapsed_ms"] == 0
    assert not (base / "jira.corp.started").exists(), "--tools-json에 있는 서버(정규화 이름)는 띄우지 않는다"
    assert found["remote-jira"]["probe"] == "remote" and found["remote-jira"]["error"].startswith("not-stdio")
    lines = [ln for ln in proc.stderr.splitlines() if ln.startswith("[tracker-candidates]")]
    assert "[tracker-candidates] fake-jira 확인 중(최대 10초)" in lines
    assert any(ln.startswith("[tracker-candidates] fake-jira ") and ln.endswith("ms 도구 1개") for ln in lines)
    assert any(ln.startswith("[tracker-candidates] fake-exit ") and ln.endswith("ms exited(3)") for ln in lines)
    assert not any(name in ln for ln in lines for name in ("remote-jira", "jira.corp", "jira_corp"))   # 띄우지 않은 서버


def test_tracker_candidates_reads_opencode_mcp():
    """계획 I O8: `--opencode-config`(또는 TT_RUNTIME=opencode면 작업 폴더에서 OpenCode가 합치는 설정)의 `mcp`도 읽는다 —
    local `command` 배열로 띄우고, `enabled:false`는 띄우지 않고(probe disabled), remote는 probe remote. 그 서버 항목에
    source=opencode·opencode_tools(세션 이름 `<서버>_<도구>`), 저장 이름(tools)은 그대로 mcp__<서버>__<도구>."""
    env = Env()  # 테스트 헬퍼 루트: exclude_servers: []
    base = tmp("tt-mcp-oc-")
    script = base / "fake_mcp.py"
    script.write_text(FAKE_MCP, encoding="utf-8")
    empty = base / "claude-mcp.json"
    empty.write_text('{"mcpServers": {}}', encoding="utf-8")
    proj = base / "proj"
    proj.mkdir()
    (proj / "opencode.jsonc").write_text("// 사용자 설정\n" + json.dumps({"mcp": {
        "oc-jira": {"type": "local", "command": [sys.executable, str(script), "answer", str(base / "oc-jira.started")]},
        "off-jira": {"type": "local", "command": [sys.executable, str(script), "answer", str(base / "off.started")],
                     "enabled": False},
        "remote-jira": {"type": "remote", "url": "https://mcp.mock.invalid/x"}}}), encoding="utf-8")
    found = env.json("config.py", ["tracker-candidates", "--mcp-config", empty, "--opencode-config", proj / "opencode.jsonc"])
    got = {s["server"]: s for s in found["servers"]}
    assert set(got) == {"oc-jira", "off-jira", "remote-jira"} and found["usable"] == ["oc-jira"]
    assert got["oc-jira"]["probe"] == "stdio" and got["oc-jira"]["tools"] == ["mcp__oc-jira__jira_get_issue"]
    assert got["oc-jira"]["source"] == "opencode" and got["oc-jira"]["opencode_tools"] == ["oc-jira_jira_get_issue"]
    assert got["off-jira"]["probe"] == "disabled" and got["off-jira"]["error"].startswith("disabled")
    assert not (base / "off.started").exists(), "enabled:false 서버는 띄우지 않는다"
    assert got["remote-jira"]["probe"] == "remote" and got["remote-jira"]["error"].startswith("not-stdio")

    # OpenCode 안: 옵션 없이 작업 폴더 설정을 읽고(~/.claude.json은 기본으로 읽지 않는다), --tools-json은 OpenCode 세션 이름
    tools = base / "tools.json"
    tools.write_text(json.dumps({"corp.jira": ["corp_jira_jira_fetch_issue", "mcp__corp_jira__jira_search"]}), encoding="utf-8")
    oc_env = {"TT_RUNTIME": "opencode", "HOME": str(base / "home"), "XDG_CONFIG_HOME": str(base / "home" / ".config")}
    found = env.json("config.py", ["tracker-candidates", "--tools-json", tools], cwd=proj, env=oc_env)
    got = {s["server"]: s for s in found["servers"]}
    assert set(got) == {"corp.jira", "oc-jira", "off-jira", "remote-jira"}
    assert got["corp.jira"]["tools"] == ["mcp__corp_jira__jira_fetch_issue", "mcp__corp_jira__jira_search"]
    assert got["corp.jira"]["opencode_tools"] == ["corp_jira_jira_fetch_issue", "corp_jira_jira_search"]
    # Claude Code(기본): OpenCode 설정을 읽지 않고 출력에 source 키가 없다
    plain = env.json("config.py", ["tracker-candidates", "--mcp-config", empty, "--tools-json", tools], cwd=proj)
    assert [s["server"] for s in plain["servers"]] == ["corp.jira"] and "source" not in plain["servers"][0]
    assert plain["servers"][0]["tools"] == ["mcp__corp_jira__corp_jira_jira_fetch_issue", "mcp__corp_jira__jira_search"]


def test_missing_site_defaults_stops_everything():
    bare = tmp("tt-bare-root-") / "root"
    make_plugin_root.make(bare)
    (bare / "site-defaults.yaml").unlink()  # example은 남아 있다 — 읽지 않아야 한다
    assert (bare / "site-defaults.example.yaml").is_file()
    env = Env(root=bare)
    for script, args in (("config.py", ["init"]), ("config.py", ["check", "--db", SAMPLE]),
                         ("config.py", ["tracker-candidates", "--mcp-config", MCP_CONFIG]), ("config.py", ["doctor"]),
                         ("db_pr.py", ["lock", "status"]), ("db_pr.py", ["my-prs"]), ("code_roots.py", ["suggest"])):
        proc = env.run(script, args, stdin="")
        assert proc.returncode == 2 and "사내 기본값 없음" in proc.stderr, (script, proc.stderr)
    assert not (env.home / "config.yaml").exists()


# -- setup 흐름 -----------------------------------------------------------------------


def _setup_read_steps(env: Env, clone: Path) -> dict:
    """setup 1~8 (읽기 설정). 결과 모음."""
    env.init(clone)
    env.json("config.py", ["sync-scripts-path"])
    hooks = env.json("config.py", ["install-hooks"])
    env.json("db_pr.py", ["lock", "acquire", "setup", "--command", "setup"])
    snap = env.json("db_pr.py", ["snapshot", "--job", "setup"])
    # 7. 쓰기가 막히는 조건이면 종료 코드 2(읽기 전용)이고 setup은 계속한다
    proc = env.run("config.py", ["check", "--db", snap["snapshot"], "--for", "dry-run"])
    assert proc.returncode in (0, 2), proc.stderr
    check = json.loads(proc.stdout)
    env.json("db_pr.py", ["lock", "release", "setup"])
    return {"hooks": hooks, "snapshot": snap, "check": check}


def test_setup_with_gh_unauth_finishes_read_setup():
    repo = _repo()
    clone = Path(repo["clone"])
    before = (git(clone, "rev-parse", "--abbrev-ref", "HEAD"), git(clone, "status", "--porcelain"),
              git(clone, "rev-parse", "HEAD"))
    env = Env()
    steps = _setup_read_steps(env, clone)
    assert steps["hooks"]["core.hooksPath"] == ".githooks"
    assert git(clone, "config", "--get", "core.hooksPath").strip() == ".githooks"
    snap = Path(steps["snapshot"]["snapshot"])
    assert steps["check"]["writable"] is True and steps["check"]["push_allowed"] is False  # dry-run
    assert steps["check"]["gh"]["checked"] is False

    # 9. gh 인증 실패 → 쓰기 불가 안내, 종료 코드 2. 1~8은 이미 끝난 상태다
    proc = env.run("config.py", ["gh-status"], unauth=True)
    assert proc.returncode == 2 and "쓰기 불가" in json.loads(proc.stdout)["message"]
    write = env.run("config.py", ["check", "--db", snap, "--for", "write"], unauth=True)
    result = json.loads(write.stdout)
    assert write.returncode == 2 and result["writable"] is True and result["push_allowed"] is False
    assert [r["code"] for r in result["reasons"]] == ["gh-auth"]
    assert (env.home / "config.yaml").is_file()
    ok = env.json("config.py", ["check", "--db", snap, "--for", "write"])
    assert ok["push_allowed"] is True

    # 사용자 clone의 브랜치·워킹 트리·HEAD가 그대로다
    after = (git(clone, "rev-parse", "--abbrev-ref", "HEAD"), git(clone, "status", "--porcelain"),
             git(clone, "rev-parse", "HEAD"))
    assert after == before and not (clone / ".cache").exists()


def test_version_check_uses_snapshot_of_origin():
    repo = _repo()
    clone = Path(repo["clone"])
    # 다른 사람이 origin에 schema_version 2를 올린다
    other = tmp("tt-other-") / "c"
    git(Path(repo["base"]), "clone", "-q", repo["remote"], str(other))
    edit(other / "issue-db.config.yaml", "schema_version: 1", "schema_version: 2")
    git(other, "commit", "-qam", "schema v2")
    git(other, "push", "-q", "origin", "main")
    # 사용자 clone은 다른 브랜치에 있어 pull되지 않는다 (옛 버전 그대로)
    git(clone, "checkout", "-q", "-b", "feature")
    env = Env()
    steps = _setup_read_steps(env, clone)
    assert steps["snapshot"]["pulled"] is False and "feature" in steps["snapshot"]["pull_skipped_reason"]
    assert steps["check"]["writable"] is False and steps["check"]["read_only"] is True
    assert [r["code"] for r in steps["check"]["reasons"]] == ["schema-too-new"]
    assert "schema_version: 1" in (clone / "issue-db.config.yaml").read_text(encoding="utf-8")
    assert env.json("config.py", ["check", "--db", clone, "--for", "dry-run"])["writable"] is True
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD").strip() == "feature"


def test_migrate_branch_skips_version_checks():
    repo = _repo()
    clone = Path(repo["clone"])
    env = Env()
    env.init(clone)
    edit(clone / "issue-db.config.yaml", "schema_version: 1", "schema_version: 2")
    edit(clone / "issue-db.config.yaml", "generator_version: 2", "generator_version: 3")
    blocked = env.run("config.py", ["check", "--db", clone, "--for", "dry-run"])
    codes = [r["code"] for r in json.loads(blocked.stdout)["reasons"]]
    assert blocked.returncode == 2 and codes == ["schema-too-new", "generator-mismatch"]
    git(clone, "checkout", "-q", "-b", "migrate/schema-v2")
    result = env.json("config.py", ["check", "--db", clone, "--for", "dry-run"])
    assert result["migrate_branch"] is True and result["writable"] is True
    proc = env.run("config.py", ["check", "--db", clone, "--for", "write"], unauth=True)
    assert proc.returncode == 2 and [r["code"] for r in json.loads(proc.stdout)["reasons"]] == ["gh-auth"]


def test_backend_and_external_pins_block_writes():
    env = Env(root=plugin_root("site-backend", parser={"backend": "site"}))
    result = env.json("config.py", ["check", "--db", SAMPLE, "--for", "dry-run"], expect=2)
    assert [r["code"] for r in result["reasons"]] == ["parser-backend-mismatch"]
    db = tmp() / "db"
    import shutil

    shutil.copytree(SAMPLE, db)
    edit(db / "issue-db.config.yaml", "external_parsers: {}",
         "external_parsers:\n  data: {adapter: site_data_existing, min_version: 1.0.0}")
    result = Env().json("config.py", ["check", "--db", db, "--for", "dry-run"], expect=2)
    assert [r["code"] for r in result["reasons"]] == ["external-parser-mismatch"]


# -- 세션 lock --------------------------------------------------------------------------


def test_session_lock_rules():
    env = Env()
    env.init(env.base / "db")
    at = lambda minutes: {"TT_NOW": f"2026-09-29T{9 + minutes // 60:02d}:{minutes % 60:02d}:00Z"}  # noqa: E731
    env.json("db_pr.py", ["lock", "acquire", "MOCK-1101", "--command", "analyze"], env=at(0))
    # 다른 작업 키 → 종료 코드 2와 보유자
    proc = env.run("db_pr.py", ["lock", "acquire", "MOCK-2101"], env=at(1))
    assert proc.returncode == 2 and json.loads(proc.stdout)["holder"]["job"] == "MOCK-1101"
    proc = env.run("db_pr.py", ["snapshot", "--job", "MOCK-2101"], env=at(1))
    assert proc.returncode == 2
    # 같은 작업 키, 10분 이내 갱신 → 다른 세션(owner 없음)은 --take-over 없이는 2, 있으면 이어받음
    # (같은 owner의 재획득은 재진입 — test_lock_recovery.py)
    other = lambda minutes: {**at(minutes), "TT_LOCK_OWNER": ""}  # noqa: E731
    assert env.run("db_pr.py", ["lock", "acquire", "MOCK-1101"], env=other(5)).returncode == 2
    taken = env.json("db_pr.py", ["lock", "acquire", "MOCK-1101", "--take-over"], env=other(5))
    assert taken["taken_over"] is True and taken["lock"]["started_at"] == "2026-09-29T09:00:00Z"
    # 10분이 넘었으면 그대로 이어받는다
    env.json("db_pr.py", ["lock", "acquire", "MOCK-1101"], env=at(16))
    # 4시간 넘게 갱신되지 않은 lock은 다른 작업이 가져온다
    status = env.json("db_pr.py", ["lock", "status"], env=at(16 + 241))
    assert status["lock"]["expired"] is True
    stolen = env.json("db_pr.py", ["lock", "acquire", "MOCK-2101"], env=at(16 + 241))
    assert stolen["lock"]["job"] == "MOCK-2101" and stolen["previous"]["job"] == "MOCK-1101"
    # 보유자가 아니면 release는 2, --force면 푼다
    assert env.run("db_pr.py", ["lock", "release", "MOCK-1101"], env=at(300)).returncode == 2
    released = env.json("db_pr.py", ["lock", "release", "MOCK-1101", "--force"], env=at(300))
    assert released["released"] is True and released["forced"] is True
    assert env.json("db_pr.py", ["lock", "status"])["held"] is False
    assert env.run("db_pr.py", ["stage", "x"]).returncode == 2  # Phase 7


# -- 코드 경로 --------------------------------------------------------------------------


def test_code_root_selector():
    env = Env()
    env.init(env.base / "db")
    cfg = env.config()
    cfg["code_profiles"] = [
        {"name": "android17-dev", "platform_version": "17",
         "roots": {"aosp": str(SRC / "android17"), "vendor_ril": str(SRC / "android17/vendor/mockril")}},
        {"name": "android16-main", "platform_version": "16",
         "roots": {"aosp": str(SRC / "android16"), "vendor_ril": str(SRC / "android16/vendor/mockril")}},
    ]
    (env.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    env.json("code_roots.py", ["remember", f"aosp={SRC / 'android17'}"])

    suggested = env.json("code_roots.py", ["suggest", "--version", "16"])["candidates"]
    assert suggested[0]["name"] == "android16-main" and suggested[0]["recommended"] is True
    assert [c["kind"] for c in suggested] == ["profile", "recent", "profile"]
    assert env.json("code_roots.py", ["suggest", "--version", "17"])["candidates"][0]["name"] == "android17-dev"

    ok = env.json("code_roots.py", ["validate", "android16-main", "--version", "16", "--db", SAMPLE])
    assert ok["valid"] and ok["estimated_version"] == "16" and ok["warnings"] == []
    warn = env.json("code_roots.py", ["validate", "android17-dev", "--version", "16", "--db", SAMPLE])
    assert warn["valid"] and "다르다" in warn["warnings"][0]
    for bad in (f"aosp={env.base / 'nope'}", f"aosp={SRC / 'android16/vendor'}",
                f"aosp={SRC / 'android16'},modem={SRC}"):
        proc = env.run("code_roots.py", ["validate", bad, "--db", SAMPLE])
        assert proc.returncode == 2 and not json.loads(proc.stdout)["valid"], bad

    # 16과 17에서 경로가 다른 파일을 find-symbol이 찾는다
    for version, rel in (("16", "frameworks/base/telephony/java/android/telephony/DataFailCause.java"),
                         ("17", "frameworks/opt/telephony/src/java/com/android/internal/telephony/data/fail/DataFailCause.java")):
        found = env.json("code_roots.py", ["find-symbol", "DataFailCause#toString", "--roots", f"android{version}-"
                                           + ("main" if version == "16" else "dev")])
        assert [m["ref"] for m in found["matches"]] == [f"aosp:{rel}"]
        resolved = env.json("code_roots.py", ["resolve", f"aosp:{rel}", "--roots", f"aosp={SRC / ('android' + version)}"])
        assert resolved["exists"] is True
    assert env.run("code_roots.py", ["resolve", "/abs/path", "--roots", f"aosp={SRC / 'android16'}"]).returncode == 2


def test_remember_with_version_saves_personal_profile():
    """07 §Step 2-1 5번: `remember --platform-version`은 개인 code_profiles에 저장(이름 겹치면 -2, 같은 roots면 안 만듦,
    최근 목록에서 뺌). 버전 없이는 지금처럼 recent_code_roots."""
    env = Env()
    env.init(env.base / "db")
    cfg = env.config()
    cfg["code_profiles"] = [{"name": "android16-android16", "platform_version": "16",
                             "roots": {"aosp": str(SRC / "android17")}}]
    (env.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    a16 = f"aosp={SRC / 'android16'}"
    env.json("code_roots.py", ["remember", a16])                              # 버전 모름 → 최근 목록
    assert env.config()["recent_code_roots"][0]["roots"] == {"aosp": str(SRC / "android16")}
    out = env.json("code_roots.py", ["remember", a16, "--platform-version", "16"])
    assert out == {"profile": "android16-android16-2", "saved": True, "platform_version": "16"}
    saved = env.config()
    assert saved["code_profiles"][-1] == {"name": "android16-android16-2", "platform_version": "16",
                                          "roots": {"aosp": str(SRC / "android16")}}
    assert saved["recent_code_roots"] == []                                   # 목록에 두 번 나오지 않는다
    again = env.json("code_roots.py", ["remember", a16, "--platform-version", "16"])
    assert again == {"profile": "android16-android16-2", "saved": False, "platform_version": "16"}
    assert len(env.config()["code_profiles"]) == 2
    names = [c["name"] for c in env.json("code_roots.py", ["suggest", "--version", "16"])["candidates"]]
    assert names[:2] == ["android16-android16", "android16-android16-2"]


def _all_tests():
    return [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]


def test_show_keys_returns_only_requested_values_and_lists_missing():
    env = Env()
    env.init(env.base / "db")
    full = env.json("config.py", ["show"])
    out = env.json("config.py", ["show", "--keys", "work_dir,tracker.tools,no.such"])
    assert set(out) == {"user_config", "values", "missing"}
    assert out["values"] == {"work_dir": full["effective"]["work_dir"], "tracker.tools": full["effective"]["tracker"]["tools"]}
    assert out["missing"] == ["no.such"] and out["user_config"] == full["user_config"]
    assert env.json("config.py", ["show"]) == full      # --keys 없으면 이전과 같다


# -- doctor (읽기 전용 점검) ---------------------------------------------------------------------


def _rows(result: dict) -> dict:
    return {r["check"]: r for r in result["rows"]}


DOCTOR_MD_MAX = 1152    # doctor markdown 바이트 상한 (tracker_post 행을 더해 1,024B에서 늘림)
DOCTOR_ROWS = ["python", "deps", "config", "scripts_path", "clone", "hook", "guard", "tracker", "tracker_post", "gh", "snapshot",
               "compat", "lock"]


def _doctor(env: Env, expect=0, at: dict | None = None, **kw) -> dict:
    result = env.json("config.py", ["doctor"], expect=expect, env=at or {}, **kw)
    assert [r["check"] for r in result["rows"]] == DOCTOR_ROWS
    assert sum(result["counts"].values()) == 13 and all(len(r["detail"]) <= 80 for r in result["rows"])
    return result


def _ready_env() -> tuple[Env, Path]:
    clone = Path(_repo()["clone"])
    env = Env()
    _setup_read_steps(env, clone)
    return env, clone


def _set_user(env: Env, **top) -> None:
    cfg = env.config()
    cfg.update(top)
    (env.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")


def _tree(*roots: Path) -> list:
    out = []
    for root in roots:
        for path in sorted(root.rglob("*")):
            st = path.stat()    # 디렉토리도 센다 (mkdir 방지)
            out.append((str(path), path.is_dir(), 0 if path.is_dir() else st.st_size, 0 if path.is_dir() else st.st_mtime_ns))
    return out


def test_doctor_all_ok_markdown_fits_budget_and_changes_nothing():
    env, clone = _ready_env()
    before = (_tree(env.base, clone), git(clone, "status", "--porcelain"), git(clone, "for-each-ref"))
    result = _doctor(env)
    assert result["counts"] == {"ok": 13, "warn": 0, "fail": 0, "skip": 0}
    proc = env.run("config.py", ["doctor", "--format", "markdown"])
    assert proc.returncode == 0 and len(proc.stdout.encode("utf-8")) <= DOCTOR_MD_MAX, len(proc.stdout.encode("utf-8"))
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0].startswith("| 점검 |") and lines[-1] == "ok 13 · warn 0 · fail 0 · skip 0"
    assert sum(1 for ln in lines if ln.startswith("| ")) == 14          # 헤더 + 13행, 표는 하나
    assert "\n  " not in json.dumps(result) and env.run("config.py", ["doctor"]).stdout.count("\n") == 1
    after = (_tree(env.base, clone), git(clone, "status", "--porcelain"), git(clone, "for-each-ref"))
    assert after == before, "doctor는 읽기 전용이다 (clone·work_dir·config 불변)"
    assert not (env.base / "work" / "session.lock").exists()


def test_doctor_opencode_rows_only_under_opencode():
    """계획 I O8: OpenCode 안(TT_RUNTIME=opencode)에서만 opencode_env(oc_adapter env-check)·jira_gate(Jira 읽기 관문) 두
    행을 끝에 더한다. 기본(Claude Code)은 13행 그대로(markdown 바이트도 같다)."""
    env, _ = _ready_env()
    plain_md = env.run("config.py", ["doctor", "--format", "markdown"]).stdout
    result = env.json("config.py", ["doctor"], env={"TT_RUNTIME": "opencode"})
    assert [r["check"] for r in result["rows"]] == DOCTOR_ROWS + ["opencode_env", "jira_gate"]
    rows = _rows(result)
    assert rows["opencode_env"] == {"check": "opencode_env", "status": "ok", "detail": "설정을 덮는 환경 변수 없음"}
    assert rows["jira_gate"]["status"] == "warn" and rows["jira_gate"]["detail"].startswith("닫힘(opencode.jira_read: closed)")
    assert "확인 기록 없음" in rows["jira_gate"]["detail"] and "runtime-check opencode" in rows["jira_gate"]["next"]
    assert result["counts"] == {"ok": 14, "warn": 1, "fail": 0, "skip": 0}
    bad = env.json("config.py", ["doctor"], expect=1, env={"TT_RUNTIME": "opencode", "OPENCODE_PERMISSION": "{}",
                                                          "TT_OC_JIRA_GATE": "open"})
    assert _rows(bad)["opencode_env"]["status"] == "fail" and "OPENCODE_PERMISSION" in _rows(bad)["opencode_env"]["detail"]
    assert _rows(bad)["jira_gate"]["detail"].startswith("시험 열림")
    assert env.run("config.py", ["doctor", "--format", "markdown"]).stdout == plain_md
    assert "opencode_env" not in plain_md and len(_doctor(env)["rows"]) == 13


def test_doctor_python_deps_and_guard_selftest_rows():
    env, _ = _ready_env()
    rows = _rows(_doctor(env))
    assert rows["python"]["status"] == "ok" and rows["deps"]["status"] == "ok" and "PyYAML" in rows["deps"]["detail"]
    assert rows["guard"] == {"check": "guard", "status": "ok", "detail": "deny 3/3"}   # 코멘트 도구 승인 없는 게시 포함
    # guard.py가 깨진 플러그인 루트: guard 행 fail, 종료 1
    import shutil
    broken = tmp("tt-broken-guard-") / "root"
    shutil.copytree(env.root, broken)
    guard_py = broken / "scripts" / "guard.py"
    text = guard_py.read_text(encoding="utf-8")
    guard_py.write_text(text.replace("from __future__ import annotations\n",
                                     "from __future__ import annotations\nraise SystemExit(1)\n", 1), encoding="utf-8")
    result = env.json("config.py", ["doctor"], expect=1, root=broken)
    guard = _rows(result)["guard"]
    assert guard["status"] == "fail" and "응답 구조 불일치" in guard["detail"] and "guard.py" in guard["next"]
    # 의존성 없음으로 degraded 거부하는 guard(결정은 deny지만 판정이 아니다): fail
    degraded = tmp("tt-degraded-guard-") / "root"
    shutil.copytree(env.root, degraded)
    guard_py = degraded / "scripts" / "guard.py"
    text = guard_py.read_text(encoding="utf-8")
    needle = "    from common import checks, mcptools, site_defaults, userconfig"
    assert needle in text
    guard_py.write_text(text.replace(needle, '    raise ImportError("시험용 의존성 없음")\n' + needle, 1), encoding="utf-8")
    guard = _rows(env.json("config.py", ["doctor"], expect=1, root=degraded))["guard"]
    assert guard["status"] == "fail" and "의존성 없음" in guard["detail"], guard


def test_config_without_pyyaml_exits_2_with_install_hint():
    env = Env()
    fake = tmp("tt-noyaml-")
    (fake / "yaml.py").write_text('raise ImportError("PyYAML 없음 (테스트)")\n', encoding="utf-8")
    proc = env.run("config.py", ["doctor"], env={"PYTHONPATH": str(fake)})
    assert proc.returncode == 2 and "의존성 없음" in proc.stderr and "Traceback" not in proc.stderr, proc.stderr


def test_doctor_without_config_fails_config_and_skips_the_rest_without_creating_anything():
    env = Env()
    result = _doctor(env, expect=1)
    assert result["counts"] == {"ok": 3, "warn": 0, "fail": 1, "skip": 9}   # skip은 ok로 세지 않는다
    rows = _rows(result)
    assert rows["config"]["status"] == "fail" and "setup" in rows["config"]["next"]
    # config 없이도 이름 기반 deny, site의 코멘트 도구는 승인 기록을 찾을 수 없어(work_dir 없음) deny
    assert rows["guard"] == {"check": "guard", "status": "ok", "detail": "deny 2/2"}
    assert all(r["status"] == "skip" for k, r in rows.items() if k not in ("config", "python", "deps", "guard"))
    assert not env.home.exists()
    assert env.run("config.py", ["doctor", "--format", "markdown", "--json"]).returncode == 2
    # 손상 config: init --force도 먼저 읽다 실패하므로 파일을 옮기고 setup하라고 안내한다
    env.home.mkdir(parents=True)
    (env.home / "config.yaml").write_text("work_dir: [깨짐\n", encoding="utf-8")
    broken = _rows(_doctor(env, expect=1))["config"]
    assert broken["status"] == "fail" and "config 읽기 실패" in broken["detail"]
    assert "옮긴 뒤" in broken["next"] and "/telephony-triage:setup" in broken["next"]


def test_doctor_empty_jira_mapping_fails_and_exits_1():
    env, _ = _ready_env()
    _set_user(env, tracker={"mcp_server": ""})
    jira = _rows(_doctor(env, expect=1))["tracker"]
    assert jira["status"] == "fail" and "mcp_server" in jira["detail"] and "setup 4" in jira["next"]
    _set_user(env, tracker={"mcp_server": "mock-jira", "tools": {"get_issue": ""}})
    assert "get_issue" in _rows(_doctor(env, expect=1))["tracker"]["detail"]
    _set_user(env, tracker={"mcp_server": "mock-jira", "tools": {"get_issue": "jira_fetch_ticket"}})
    assert "전체 이름" in _rows(_doctor(env, expect=1))["tracker"]["detail"]
    _set_user(env, tracker={"mcp_server": "other", "tools": {"get_issue": "mcp__mock-jira__jira_fetch_ticket"}})
    assert "서버 other의 도구가 아닙니다" in _rows(_doctor(env, expect=1))["tracker"]["detail"]


def test_doctor_jira_post_row_skip_ok_warn_fail():
    """승인 코멘트 도구 설정(`tracker.write_tools.add_comment`): 없으면 skip, 유효하면 ok, 서버·단어·인자 오류는 warn,
    read_tools에 있으면(승인 생략 경로) fail. 설정이 무효면 guard 자가시험은 코멘트 입력을 넣지 않는다."""
    env, _ = _ready_env()
    rows = _rows(_doctor(env))
    assert rows["tracker_post"] == {"check": "tracker_post", "status": "ok",
                                 "detail": "mcp__mock-jira__jira_ticket_add_note / jira-wiki"}
    _set_user(env, tracker={"write_tools": {"add_comment": {"tool": ""}}})     # 도구를 비우면 꺼진다
    assert _rows(_doctor(env))["tracker_post"] == {"check": "tracker_post", "status": "skip", "detail": "게시 기능 꺼짐(본문 파일만)"}
    _set_user(env, tracker={"write_tools": {"add_comment": {"tool": "mcp__other__add_note"}}})
    rows = _rows(_doctor(env))
    assert rows["tracker_post"]["status"] == "warn" and "Jira 서버" in rows["tracker_post"]["detail"]
    assert "write_tools" in rows["tracker_post"]["next"] and rows["guard"]["detail"] == "deny 2/2"
    _set_user(env, tracker={"write_tools": {"add_comment": {"tool": "mcp__mock-jira__jira_add_worklog_note"}}})
    assert "금지 단어" in _rows(_doctor(env))["tracker_post"]["detail"]
    _set_user(env, tracker={"write_tools": {"transition": {"tool": "mcp__mock-jira__jira_move_ticket"}}})
    assert "add_comment만" in _rows(_doctor(env))["tracker_post"]["detail"]
    read = ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_ticket_add_note"]
    _set_user(env, tracker={"read_tools": read})
    row = _rows(_doctor(env, expect=1))["tracker_post"]
    assert row["status"] == "fail" and "read_tools" in row["detail"] and "read_tools" in row["next"]


def test_doctor_gh_unauth_is_warn_and_exit_0():
    env, _ = _ready_env()
    result = _doctor(env, unauth=True)
    gh = _rows(result)["gh"]
    assert gh["status"] == "warn" and "gh auth login" in gh["next"]
    assert result["counts"] == {"ok": 12, "warn": 1, "fail": 0, "skip": 0}


def test_doctor_snapshot_age_missing_and_corrupt_meta():
    from datetime import datetime, timedelta, timezone

    env, _ = _ready_env()
    meta = env.base / "work" / "snapshot.json"
    assert _rows(_doctor(env))["snapshot"]["status"] == "ok"
    later = lambda days: {"TT_NOW": (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}  # noqa: E731
    assert _rows(_doctor(env, at=later(6)))["snapshot"]["status"] == "ok"
    old = _rows(_doctor(env, at=later(8)))["snapshot"]
    assert old["status"] == "warn" and "8일 전 (" in old["detail"] and "7일 초과)" in old["detail"] and "sync" in old["next"]
    meta.unlink()
    unknown = _rows(_doctor(env))["snapshot"]
    assert unknown["status"] == "warn" and "나이 불명" in unknown["detail"]
    meta.write_text("{깨짐", encoding="utf-8")
    broken = _doctor(env, expect=1)
    assert _rows(broken)["snapshot"]["status"] == "fail"
    meta.write_text(json.dumps({"sha": "abc"}), encoding="utf-8")
    assert _rows(_doctor(env, expect=1))["snapshot"]["status"] == "fail"


def test_doctor_hooks_path_and_missing_snapshot_skip_compat():
    clone = Path(_repo()["clone"])
    env = Env()
    env.init(clone)
    env.json("config.py", ["sync-scripts-path"])
    rows = _rows(_doctor(env, expect=1))
    assert rows["hook"]["status"] == "fail" and "config.py install-hooks" in rows["hook"]["next"]
    assert rows["snapshot"]["status"] == "warn" and rows["compat"]["status"] == "skip"
    env.json("config.py", ["install-hooks"])
    assert _rows(_doctor(env))["hook"]["status"] == "ok"
    git(clone, "config", "core.hooksPath", "hooks")
    assert "hooks" in _rows(_doctor(env, expect=1))["hook"]["detail"]
    # clone이 아니면 hook은 skip
    _set_user(env, issue_db={"path": str(env.base / "not-a-clone"), "remote": "r"})
    rows = _rows(_doctor(env, expect=1))
    assert rows["clone"]["status"] == "fail" and "git clone" in rows["clone"]["next"] and rows["hook"]["status"] == "skip"


def test_doctor_next_slash_commands_exist():
    """doctor "다음" 열이 안내하는 `/telephony-triage:<이름>`은 plugin/commands/<이름>.md로 실제 있어야 한다."""
    import re
    source = (REPO / "plugin" / "scripts" / "config.py").read_text(encoding="utf-8")
    names = set(re.findall(r"/telephony-triage:([a-z][a-z-]*)", source))
    assert names, "doctor 안내에 슬래시 커맨드가 없다"
    missing = sorted(n for n in names if not (REPO / "plugin" / "commands" / f"{n}.md").is_file())
    assert not missing, missing


def test_doctor_compat_is_read_only_and_reports_blocked_writes():
    env, _ = _ready_env()
    snap = env.base / "work" / "_snapshot"
    edit(snap / "issue-db.config.yaml", "schema_version: 1", "schema_version: 2")
    before = _tree(env.base / "work")
    rows = _rows(_doctor(env, expect=1))
    assert rows["compat"]["status"] == "fail" and "schema-too-new" in rows["compat"]["detail"]
    assert _tree(env.base / "work") == before


def test_doctor_lock_held_expired_and_corrupt():
    env, _ = _ready_env()
    at = lambda minutes: {"TT_NOW": f"2099-01-01T{minutes // 60:02d}:{minutes % 60:02d}:00Z"}  # noqa: E731
    env.json("db_pr.py", ["lock", "acquire", "MOCK-1101", "--command", "analyze"], env=at(0))
    held = _rows(_doctor(env, at=at(5)))["lock"]
    assert held["status"] == "warn" and "MOCK-1101" in held["detail"] and "--force" in held["next"]
    # 만료
    expired = _rows(_doctor(env, at={"TT_NOW": "2099-01-01T06:00:00Z"}))["lock"]
    assert expired["status"] == "warn" and "만료" in expired["detail"]
    lock = env.base / "work" / "session.lock"
    guard_before = (env.base / "work" / "session.guard").exists()
    lock.write_text("{손상", encoding="utf-8")
    result = _doctor(env, expect=1)
    row = _rows(result)["lock"]
    assert row["status"] == "fail" and result["counts"]["fail"] >= 1
    assert "--force" in row["next"] and "session.lock" in row["next"]
    assert (env.base / "work" / "session.guard").exists() == guard_before    # lock 파일 guard도 만들지 않는다
    # 손상 lock은 사용자가 확인한 뒤 --force로 푼다: 지우지 않고 .corrupt-<ts>로 옮긴다
    out = env.json("db_pr.py", ["lock", "release", "MOCK-1101", "--force"])
    assert out["corrupt"] is True and not lock.exists()
    assert [p.read_text(encoding="utf-8") for p in (env.base / "work").glob("session.lock.corrupt-*")] == ["{손상"]
    assert _rows(_doctor(env))["lock"]["status"] == "ok"


def test_doctor_refactored_helpers_keep_messages():
    env = Env()
    env.init(env.base / "db")
    proc = env.run("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", "jira_fetch_ticket"])
    assert proc.returncode == 2 and proc.stderr.strip() == "도구 이름은 전체 이름(mcp__<server>__<tool>)이어야 합니다: jira_fetch_ticket"
    proc = env.run("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", "mcp__other__get_issue"])
    assert proc.returncode == 2 and proc.stderr.strip() == "mcp__other__get_issue는 서버 mock-jira의 도구가 아닙니다."


def test_doctor_bad_jira_types_make_a_fail_row_not_a_traceback():
    env, _ = _ready_env()
    _set_user(env, tracker={"mcp_server": "mock-jira", "tools": ["get_issue"], "read_tools": "mcp__mock-jira__x"})
    proc = env.run("config.py", ["doctor", "--format", "markdown"])
    assert proc.returncode == 1 and "Traceback" not in proc.stderr and "| tracker | fail | " in proc.stdout
    assert "형식 오류" in proc.stdout
    _set_user(env, tracker={"mcp_server": "mock-jira", "tools": {"get_issue": "mcp__mock-jira__a"}, "read_tools": "oops"})
    assert "형식 오류" in _rows(_doctor(env, expect=1))["tracker"]["detail"]


def test_doctor_does_not_create_missing_work_dir_and_empty_work_dir_skips():
    env, _ = _ready_env()
    import shutil
    shutil.rmtree(env.base / "work")
    before = _tree(env.base)
    rows = _rows(_doctor(env))
    assert not (env.base / "work").exists() and _tree(env.base) == before
    assert rows["snapshot"]["status"] == "warn" and rows["lock"]["status"] == "ok" and rows["compat"]["status"] == "skip"
    _set_user(env, work_dir="")      # 빈 work_dir은 경로 규칙 위반(platform fail)이지만 snapshot·lock은 건너뛴다
    rows = _rows(env.json("config.py", ["doctor"], expect=1))      # platform 행이 더 붙는다(_doctor의 고정 행 목록 밖)
    assert rows["platform"]["status"] == "fail" and "work_dir" in rows["platform"]["detail"]
    assert rows["snapshot"] == {"check": "snapshot", "status": "skip", "detail": "work_dir 없음"}
    assert rows["lock"]["status"] == "skip" and rows["lock"]["detail"] == "work_dir 없음"


def test_doctor_snapshot_age_uses_exact_timedelta():
    from datetime import datetime, timedelta, timezone

    env, _ = _ready_env()
    meta = env.base / "work" / "snapshot.json"
    at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    meta.write_text(json.dumps({"sha": "abcdef0123", "base": "main", "at": at.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    now = lambda delta: {"TT_NOW": (at + delta).strftime("%Y-%m-%dT%H:%M:%SZ")}  # noqa: E731
    assert _rows(_doctor(env, at=now(timedelta(days=7))))["snapshot"]["status"] == "ok"
    over = _rows(_doctor(env, at=now(timedelta(days=7, seconds=1))))["snapshot"]
    assert over["status"] == "warn" and "7일" in over["detail"]


def test_doctor_worst_case_markdown_fits_budget():
    clone = Path(_repo()["clone"])
    env = Env()
    env.init(clone)    # hook·snapshot·jira 문제, lock 보유, gh 인증 없음
    _set_user(env, tracker={"mcp_server": "mock-jira-with-a-fairly-long-server-name", "tools": {"get_issue": ""}})
    env.json("db_pr.py", ["lock", "acquire", "MOCK-1101-long-job-key", "--command", "analyze"])
    proc = env.run("config.py", ["doctor", "--format", "markdown"], unauth=True)
    assert proc.returncode == 1
    assert proc.stdout.count("| fail |") >= 2 and proc.stdout.count("| warn |") >= 3
    assert len(proc.stdout.encode("utf-8")) <= DOCTOR_MD_MAX, len(proc.stdout.encode("utf-8"))


# -- GitHub 트래커 (트래커 범용화 묶음 3, 설계 §3-2 classify_extra·§6-2) ---------------------------------------


def test_github_tracker_candidates_set_tracker_and_doctor():
    """github 세션: `issue_read` 하나가 get_issue·get_comments 후보(어댑터 classify_extra), set-tracker가 같은 도구를 두 동작에
    저장하고, doctor의 tracker·guard 자체 시험(github 승인 코멘트 인자, selftest_key) 행이 ok다. jira 세션에서는 보강하지 않는다."""
    from runner import github_root
    env = Env(root=github_root())
    env.init(env.base / "db")
    found = env.json("config.py", ["tracker-candidates", "--mcp-config", MCP_CONFIG])
    gh = next(s for s in found["servers"] if s["server"] == "mock-github-issues")
    read = "mcp__mock-github-issues__issue_read"
    assert gh["tracker_tools"]["get_issue"] == [read] and gh["tracker_tools"]["get_comments"] == [read]
    assert gh["suggested"] == {"get_issue": read, "get_comments": read,
                               "search_issues": "mcp__mock-github-issues__search_issues"}
    assert not any(w in t for t in gh["read_tools"] for w in ("add_issue_comment", "update_issue", "create_pull_request"))
    jira_env = Env()
    jira_env.init(jira_env.base / "db")
    gh_jira = next(s for s in jira_env.json("config.py", ["tracker-candidates", "--mcp-config", MCP_CONFIG])["servers"]
                   if s["server"] == "mock-github-issues")
    assert gh_jira["tracker_tools"]["get_comments"] == []
    saved = env.json("config.py", ["set-tracker", "--server", "mock-github-issues", "--get-issue", read,
                                   "--get-comments", read, "--search-issues", "mcp__mock-github-issues__search_issues"])
    assert saved["tools"] == {"get_issue": read, "search_issues": "mcp__mock-github-issues__search_issues",
                              "get_comments": read}
    assert saved["read_tools"] == [read, "mcp__mock-github-issues__search_issues"]
    rows = {r["check"]: r for r in env.json("config.py", ["doctor", "--format", "json"], expect=1)["rows"]}
    assert rows["tracker"]["status"] == "ok", rows["tracker"]
    assert rows["guard"]["status"] == "ok" and rows["guard"]["detail"].startswith("deny 2/2"), rows["guard"]   # 이름 휴리스틱 + 승인 없는 게시


# -- 모듈 스킬 설정(module_skills·prefer·skill_dir): set·check·doctor module_skills 행 (B1 설계 §2.5·§3, B2 §9.1) -----------

MODULE_REMOTE = "https://ghe.example.invalid/tt/module-skills.git"
# 그룹 2의 `common/moduleskills.py`가 이 브랜치에 오기 전까지 doctor 행 시험은 이 대역을 플러그인 사본에 넣어 쓴다(통합 뒤에도
# 관리 clone 상태를 고정해 보는 데 쓴다). TT_MS_STUB(JSON)로 git 버전·inspect_clone 결과를 정한다.
MODULESKILLS_STUB = '''"""테스트 대역(tests/test_config_setup.py): moduleskills의 doctor용 인터페이스만."""
import json
import os

CLONE_DIR = "_module-skills"
LOCK_FILE = "_module-skills.lock"
MIN_GIT = (2, 25)


def _s():
    return json.loads(os.environ.get("TT_MS_STUB") or "{}")


def git_version():
    v = _s().get("git", [2, 43, 0])
    return tuple(v) if v else None


def norm_remote(url):
    return url


def inspect_clone(work_dir, remote, base):
    return _s().get("info", {"state": "absent", "sha": None, "problem": None})
'''


def _stub_root(root: Path) -> Path:
    import shutil

    out = tmp("tt-ms-stub-") / "root"
    shutil.copytree(root, out)
    (out / "scripts" / "common" / "moduleskills.py").write_text(MODULESKILLS_STUB, encoding="utf-8")
    return out


def _doctor_m(env: Env, extra=("module_skills",), expect=0, stub: dict | None = None, root: Path | None = None) -> dict:
    at = {"TT_MS_STUB": json.dumps(stub or {})}
    result = env.json("config.py", ["doctor"], expect=expect, env=at, root=root or env.root)
    assert [r["check"] for r in result["rows"]] == DOCTOR_ROWS + list(extra)
    assert all(len(r["detail"]) <= 80 for r in result["rows"])
    assert MODULE_REMOTE not in json.dumps(result, ensure_ascii=False)
    return result


def test_set_module_skills_and_prefer_kinds():
    root = plugin_root("ms-set", platform={"name": "android", "enabled": ["android", "ofono"]})
    env = Env(root=root)
    env.init(env.base / "db")
    out = env.json("config.py", ["set", "module_skills.remote", MODULE_REMOTE])
    assert out["key"] == "module_skills.remote" and env.config()["module_skills"]["remote"] == MODULE_REMOTE
    assert "module_problems" not in out
    for bad, needle in (("tt/module-skills", "중 하나여야 합니다"), ("http://h.invalid/o/r.git", "중 하나여야 합니다"),
                        ("https://u:secret@ghe.example.invalid/o/r.git", "자격 증명")):
        proc = env.run("config.py", ["set", "module_skills.remote", bad])
        assert proc.returncode == 2 and needle in proc.stderr and "secret" not in proc.stderr, bad
    proc = env.run("config.py", ["set", "--platform", "ofono", "module_skills.remote", MODULE_REMOTE])
    assert proc.returncode == 2 and "--platform 없이" in proc.stderr
    env.json("config.py", ["set", "module_skills.base_branch", "release/1.0"])
    assert env.run("config.py", ["set", "module_skills.base_branch", "a..b"]).returncode == 2
    assert env.run("config.py", ["set", "analyzers.data.prefer", "foo"]).returncode == 2
    proc = env.run("config.py", ["set", "analyzers.data.skill_dir", "rel/dir"])
    assert proc.returncode == 2 and "절대 경로" in proc.stderr
    proc = env.run("config.py", ["set", "analyzers.sim.prefer", "skill"])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    want = "analyzers.sim.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다 — skill을 적거나 prefer를 지운다."
    assert out["module_problems"] == [want] and "problems" not in out
    assert "경고: 모듈 스킬·분석 스킬 설정 문제가 남았다 — " in proc.stderr and "플랫폼 프로필 문제" not in proc.stderr


def test_doctor_module_row_absent_by_default_and_check_unchanged():
    env, clone = _ready_env()
    rows = _rows(_doctor(env))
    assert "module_skills" not in rows
    out = env.json("config.py", ["check", "--db", str(clone), "--for", "dry-run"])
    assert out["warnings"] == [] and "deep_sources" not in out and "read_roots" not in out


def test_doctor_module_row_without_remote_shows_sources_and_skill_dir_note():
    env, _ = _ready_env()
    _set_user(env, analyzers={"data": {"prefer": "skill"}})
    row = _rows(_doctor_m(env))["module_skills"]
    assert row == {"check": "module_skills", "status": "ok", "detail": "remote 없음 · 5-1 설치 스킬: data · 그 밖=없음"}
    _set_user(env, analyzers={"data": {"skill_dir": "/opt/skills/mock-data-analyzer"}})
    row = _rows(_doctor_m(env))["module_skills"]
    assert row["status"] == "ok" and "permissions.additionalDirectories" in row["next"] and "--roots" in row["next"]


def test_doctor_module_row_six_categories_fit():
    env, _ = _ready_env()
    cats = {c: {"skill": f"s-{c}", "prefer": "skill"} for c in ("data", "sim", "network")}
    cats.update({c: {"when": "ask", "prefer": "module"} for c in ("call", "sms", "ims")})
    _set_user(env, analyzers=cats, module_skills={"remote": MODULE_REMOTE})
    detail = _rows(_doctor_m(env, root=_stub_root(env.root)))["module_skills"]["detail"]
    assert detail.endswith("그 밖=모듈 문서") and "설치 스킬: data,network,sim" in detail and "…" not in detail


def test_doctor_module_row_remote_states():
    env, _ = _ready_env()
    root = _stub_root(env.root)
    _set_user(env, module_skills={"remote": MODULE_REMOTE})
    row = _rows(_doctor_m(env, root=root))["module_skills"]       # 예시의 analyzers.data.skill, prefer 없음: B1-19
    want = "analyzers.data: 설치 스킬 mock-data-analyzer 대신 모듈 문서를 쓴다 — 계속 쓰려면 prefer: skill"
    assert row["status"] == "warn" and row["detail"] == want and "prefer skill" in row["next"]
    _set_user(env, module_skills={"remote": MODULE_REMOTE}, analyzers={"data": {"prefer": "module"}})
    row = _rows(_doctor_m(env, root=root))["module_skills"]
    assert row == {"check": "module_skills", "status": "ok",
                   "detail": "tt/module-skills 아직 받지 않음 · 5-1 그 밖=모듈 문서"}
    row = _rows(_doctor_m(env, root=root, stub={"info": {"state": "ok", "sha": "a" * 40}}))["module_skills"]
    assert row["status"] == "ok" and "@aaaaaaa" in row["detail"]
    row = _rows(_doctor_m(env, root=root, expect=1,
                          stub={"info": {"state": "mismatch", "problem": "origin 다름"}}))["module_skills"]
    assert row["status"] == "fail" and row["detail"] == "관리 clone 불일치: origin 다름" and "_module-skills" in row["next"]
    row = _rows(_doctor_m(env, root=root, expect=1, stub={"info": {"state": "forced"}}))["module_skills"]
    assert row["status"] == "fail" and row["detail"] == "ff-only 실패: 원격 브랜치가 강제로 바뀌었다"
    row = _rows(_doctor_m(env, root=root, expect=1, stub={"git": None}))["module_skills"]
    assert row["status"] == "fail" and "git 없음" in row["detail"]
    row = _rows(_doctor_m(env, root=root, expect=1, stub={"git": [2, 20, 1]}))["module_skills"]
    assert row["status"] == "fail" and "2.25" in row["detail"] and "git 2.20.1" in row["detail"]


def test_doctor_module_row_real_moduleskills_clone_states():
    """대역 없이 진짜 `common/moduleskills.py`로: 받기 전 → 받은 뒤(@sha) → origin이 다른 clone(불일치, fail)."""
    import module_remote as mr

    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import moduleskills

    env, _ = _ready_env()
    url = mr.build(env.base / "ms-remote")
    _set_user(env, module_skills={"remote": url}, analyzers={"data": {"prefer": "module"}})
    row = _rows(_doctor_m(env))["module_skills"]
    assert row["status"] == "ok" and "아직 받지 않음" in row["detail"] and url not in row["detail"], row
    work = Path(env.config()["work_dir"]).expanduser()
    with moduleskills.clone_lock(work) as lock:
        state = moduleskills.prepare(work, url, "main", lock=lock, platform="ofono")
        moduleskills.materialise(state, purpose="deep", module="data", category="data")
    row = _rows(_doctor_m(env))["module_skills"]
    assert row["status"] == "ok" and f"@{mr.head(env.base / 'ms-remote')[:7]}" in row["detail"], row
    other = mr.build(env.base / "ms-remote2")
    _set_user(env, module_skills={"remote": other}, analyzers={"data": {"prefer": "module"}})
    row = _rows(_doctor_m(env, expect=1))["module_skills"]
    assert row["status"] == "fail" and row["detail"].startswith("관리 clone 불일치"), row


def test_doctor_module_row_config_problem_fails():
    env, _ = _ready_env()
    _set_user(env, module_skills={"remote": "tt/module-skills"})
    row = _rows(_doctor_m(env, expect=1))["module_skills"]
    assert row["status"] == "fail" and row["detail"].startswith("사용자 config module_skills.remote:")


def test_doctor_module_row_appears_for_leftover_clone_dir():
    env, _ = _ready_env()
    work = Path(env.config()["work_dir"])
    (work / "_module-skills").mkdir(parents=True)
    row = _rows(_doctor_m(env))["module_skills"]
    assert row["status"] == "ok" and row["detail"].startswith("remote 없음")


def test_doctor_clone_dir_name_matches_moduleskills():
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import config as config_mod

    try:
        from common import moduleskills
    except ImportError:
        pytest.skip("common/moduleskills.py(그룹 2)가 아직 없다")
    assert config_mod.MODULE_CLONE_NAME == moduleskills.CLONE_DIR


def test_check_module_warnings_deep_sources_and_roots():
    env, clone = _ready_env()
    _set_user(env, module_skills={"remote": MODULE_REMOTE})
    args = ["check", "--db", str(clone), "--for", "dry-run"]
    out = env.json("config.py", args)
    assert out["warnings"] == ["analyzers.data: 설치 스킬 mock-data-analyzer 대신 모듈 문서를 쓴다 — 계속 쓰려면 prefer: skill"]
    assert out["deep_sources"] == {"data": {"source": "module", "when": "ask"}, "*": {"source": "module", "when": "ask"}}
    assert "read_roots" not in out and MODULE_REMOTE not in json.dumps(out)
    _set_user(env, module_skills={"remote": MODULE_REMOTE}, analyzers={"data": {"prefer": "skill"}})
    out = env.json("config.py", args + ["--roots"])
    assert out["warnings"] == []
    assert out["deep_sources"]["data"] == {"source": "skill", "skill": "mock-data-analyzer", "when": "ask"}
    assert out["read_roots"][:2] == [str(env.root / "skills" / "telephony-triage"), env.config()["work_dir"]]
    assert all(os.path.isabs(p) for p in out["read_roots"])


def test_check_deprecated_keys_and_runtime_label_warn_only():
    env, clone = _ready_env()
    _set_user(env, analyzers={"data": {"inputs": ["x"]}})
    proc = env.run("config.py", ["check", "--db", str(clone), "--for", "dry-run"])
    out = json.loads(proc.stdout)
    assert proc.returncode == 0 and out["writable"] is True
    assert out["warnings"] == ["사용자 config: 폐지 키 `analyzers.data.inputs`는 읽지 않는다(무시) — 그 줄을 지운다"]
    root = plugin_root("ms-runtime-label", runtime={"label": 3})
    env2 = Env(root=root)
    _setup_read_steps(env2, Path(_repo()["clone"]))
    row = _rows(_doctor(env2))["config"]
    assert row["status"] == "warn" and row["detail"].startswith("runtime.label:")
    out = env2.json("config.py", ["check", "--db", env2.config()["issue_db"]["path"], "--for", "dry-run"])
    assert "runtime.label: 문자열(영숫자·._ +-, 40자 이하)이어야 합니다 — 출처 기록에서 뺀다" in out["warnings"]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)


def test_set_reviewer_ask_false_is_boolean_and_visible_to_skill():
    """02-config §4 `reviewer.ask`(종합 리뷰 A 제안): push 뒤 리뷰어 질문을 끄는 개인 설정. 불리언으로 저장되고
    `show --keys`로 스킬(write-flow.md 5번)이 읽는다. 기본은 없음(= 묻는다)."""
    env = Env()
    env.init(env.base / "db")
    before = env.json("config.py", ["show", "--keys", "reviewer.ask"])
    assert before["missing"] == ["reviewer.ask"]
    env.json("config.py", ["set", "reviewer.ask", "false"])
    assert env.config()["reviewer"]["ask"] is False
    after = env.json("config.py", ["show", "--keys", "reviewer.ask"])
    assert after["values"] == {"reviewer.ask": False} and after["missing"] == []


def test_doctor_retention_row_counts_old_job_dirs_without_deleting(tmp_path):
    """02-config `retention_days`(종합 리뷰 G, S14): 두면 `retention` 행이 생겨 기한 넘은 작업 폴더 수를 warn으로 세고 지우지 않는다.
    없으면 행 자체가 없다. 잘못된 값은 fail."""
    import time as _time
    env = Env()
    env.init(env.base / "db")
    rows = {r["check"]: r for r in json.loads(env.run("config.py", ["doctor"]).stdout)["rows"]}
    assert "retention" not in rows                                 # 기간을 정하지 않은 팀: 행 없음(점검표·예산 불변)
    work = Path(env.config()["work_dir"]).expanduser()
    old, fresh = work / "MOCK-9001", work / "MOCK-9002"
    for d in (old, fresh):
        d.mkdir(parents=True, exist_ok=True)
        (d / "plan.json").write_text("{}", encoding="utf-8")
    past = _time.time() - 40 * 86400
    os.utime(old / "plan.json", (past, past))                   # 나이 = 마지막 활동(안의 파일까지, R4)
    os.utime(old, (past, past))
    root = plugin_root("retention-30", retention_days=30)
    rows = {r["check"]: r for r in json.loads(env.run("config.py", ["doctor"], root=root).stdout)["rows"]}
    assert rows["retention"]["status"] == "warn" and "1개" in rows["retention"]["detail"]
    assert "cleanup --older-than 30" in rows["retention"]["next"]
    assert old.is_dir() and fresh.is_dir()                       # 세기만 한다
    assert "마지막 활동 뒤" in rows["retention"]["detail"]
    # 코덱스 리뷰 R4: 폴더 mtime은 40일 전이어도 안의 trace.jsonl을 방금 갱신했으면 "최근"이다 — cleanup --older-than과 같은 정의
    (old / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    os.utime(old, (past, past))
    rows = {r["check"]: r for r in json.loads(env.run("config.py", ["doctor"], root=root).stdout)["rows"]}
    assert rows["retention"]["status"] == "ok"
    from common import session_lock
    from dbpr import worktree
    assert worktree._tree_mtime(old) == session_lock.tree_mtime(old) > past + 86400
    os.utime(old / "trace.jsonl", (past, past))
    (old / "wt").mkdir()                                          # git worktree는 나이에 세지 않는다
    os.utime(old, (past, past))                                   # mkdir가 올린 폴더 mtime은 되돌린다
    rows = {r["check"]: r for r in json.loads(env.run("config.py", ["doctor"], root=root).stdout)["rows"]}
    assert rows["retention"]["status"] == "warn"
    os.utime(old, None)
    rows = {r["check"]: r for r in json.loads(env.run("config.py", ["doctor"], root=root).stdout)["rows"]}
    assert rows["retention"]["status"] == "ok"
    bad = plugin_root("retention-bad", retention_days="90일")
    rows = {r["check"]: r for r in json.loads(env.run("config.py", ["doctor"], root=bad).stdout)["rows"]}
    assert rows["retention"]["status"] == "fail"


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="P2: main() platform_session.resolve → from_site_defaults가 손상 site-defaults에서 AttributeError — 다음 정리 때 고침")
@pytest.mark.parametrize("corrupt", [{"ghe": "x"}, {"tracker": [1]}], ids=["ghe-str", "tracker-list"])
def test_check_corrupt_site_defaults_is_usage_error_not_traceback(corrupt):
    """손상된 site-defaults(매핑 자리에 문자열·목록)에서 `config.py check`는 트레이스백(종료 1)이 아니라 문제 메시지와 종료 2여야 한다.
    지금은 cmd_check 전에 main()의 platform_session.resolve → userconfig.merged(from_site_defaults)에서 AttributeError로 죽는다
    (LINT_REVIEW 미해결 P2 — cmd_check의 merged()도 같은 길)."""
    env = Env(root=plugin_root("corrupt-site-" + next(iter(corrupt)), **corrupt))
    proc = env.run("config.py", ["check", "--db", SAMPLE, "--for", "dry-run"])
    assert proc.returncode == 2 and "Traceback" not in proc.stderr and proc.stderr.strip(), proc.stderr
