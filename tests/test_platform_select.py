"""플랫폼 선택·경로 프로필·lock·불일치 거부 (17-platforms 설계 §3·§4·§7-B, 묶음 2).

- 선택 순서: `--platform` > `TT_PLATFORM` > 사용자 config `platform` > site `platform.name` > android, `enabled` 관문
- 사용자 config 프로필: 다른 플랫폼은 android 경로를 물려받지 않는다, 기본 work_dir·pending-feedback, 허용 키(RF-4)
- lock은 플랫폼(이슈 DB)별(사용자 결정 10/11): ofono lock을 잡은 채 android acquire 허용, 같은 플랫폼 두 작업은 거부
- `platform-mismatch`: config check(migrate 브랜치 포함)·parse_logcat(TT_PLATFORM)·triage(offline)·db_pr snapshot
- 이슈 DB 키: `platform` 값 검사, 지원 버전 키 두 이름 동시 오류
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_repo  # noqa: E402
from runner import SAMPLE, plugin_root, run, tmp  # noqa: E402
from workspace import Workspace, git  # noqa: E402

import platforms  # noqa: E402
from common import compiled, userconfig  # noqa: E402
from platforms import session  # noqa: E402

ON = {"name": "android", "enabled": ["android", "ofono"]}
DATA_LOG = REPO / "tests" / "fixtures" / "logs" / "data-disabled.log"


def _root_on() -> Path:
    return plugin_root("ofono-on", platform=ON)


def ofono_db(dest: Path | None = None) -> Path:
    """샘플 DB를 복사해 `platform: ofono`를 선언한 변형 (형식 검사만, 내용은 android 샘플 그대로)."""
    dest = dest or tmp("tt-ofono-db-") / "db"
    shutil.copytree(SAMPLE, dest)
    cfg = dest / "issue-db.config.yaml"
    cfg.write_text("platform: ofono\n" + cfg.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv(userconfig.HOME_ENV, str(tmp_path / "home"))
    monkeypatch.delenv(platforms.ENV, raising=False)
    return tmp_path / "home"


# -- 선택 순서·관문 ---------------------------------------------------------------------------


def test_top_profile_is_registry_default():
    assert userconfig.TOP_PROFILE == platforms.DEFAULT_NAME


@pytest.mark.parametrize("cli,env,user,site,expect", [
    ("ofono", "android", "android", "android", "ofono"),
    (None, "ofono", "android", "android", "ofono"),
    (None, None, "ofono", "android", "ofono"),
    (None, None, None, "ofono", "ofono"),
    (None, None, None, None, "android"),
])
def test_selection_order(monkeypatch, cli, env, user, site, expect):
    monkeypatch.delenv(platforms.ENV, raising=False)
    if env:
        monkeypatch.setenv(platforms.ENV, env)
    block = {"enabled": ["android", "ofono"]}
    if site:
        block["name"] = site
    assert platforms.select({"platform": block}, cli, user) == expect


def test_selection_must_be_enabled_and_installed(monkeypatch):
    monkeypatch.delenv(platforms.ENV, raising=False)
    with pytest.raises(platforms.PlatformConfigError, match="켜져 있지 않습니다"):
        platforms.select(None, "ofono")
    with pytest.raises(platforms.PlatformConfigError, match="지원 플랫폼"):
        platforms.select({"platform": ON}, "nosuch")


# -- 사용자 config 프로필 -----------------------------------------------------------------------


USER = {"issue_db": {"path": "/x/android-db", "remote": "https://ghe.mock.invalid/o/android-db.git"},
        "work_dir": "/x/work", "code_profiles": [{"name": "a16"}], "tracker": {"mcp_server": "mock-jira"},
        "platform": "android",
        "platforms": {"ofono": {"issue_db": {"path": "/x/ofono-db"}, "log_dir": "/x/logs-ofono"}}}


def test_merged_top_is_unchanged_without_platform_keys(home):
    plain = {k: v for k, v in USER.items() if k not in ("platform", "platforms")}
    defaults = {"ghe": {"host": "ghe.mock.invalid"}}
    expect = userconfig.deep_merge(userconfig.deep_merge(userconfig.builtin(), userconfig.from_site_defaults(defaults)),
                                   plain)
    assert userconfig.merged(defaults, USER) == expect == userconfig.merged(defaults, plain, platform="android")


def test_merged_other_platform_does_not_inherit_paths(home):
    cfg = userconfig.merged({"ghe": {"host": "ghe.mock.invalid"}}, USER, platform="ofono")
    assert cfg["platform"] == "ofono"
    assert cfg["issue_db"] == {"base_branch": "main", "ghe_host": "ghe.mock.invalid", "path": "/x/ofono-db"}
    assert cfg["work_dir"] == str(home / "work-ofono")
    assert cfg["code_profiles"] == [] and cfg["recent_code_roots"] == [] and cfg["log_dir"] == "/x/logs-ofono"
    assert cfg["tracker"]["mcp_server"] == "mock-jira"            # Jira는 공유
    assert "platforms" not in cfg


def test_profile_helpers(home):
    assert userconfig.profile_key("android", "work_dir") == "work_dir"
    assert userconfig.profile_key("ofono", "issue_db.path") == "platforms.ofono.issue_db.path"
    with pytest.raises(ValueError):
        userconfig.profile_key("ofono", "tracker.mcp_server")
    assert userconfig.pending_feedback_dir(userconfig.merged({}, USER)) == home / "pending-feedback"
    assert userconfig.pending_feedback_dir(userconfig.merged({}, USER, platform="ofono")) == home / "pending-feedback-ofono"
    profs = userconfig.profiles({}, USER)
    assert list(profs) == ["android", "ofono"] and profs["ofono"]["issue_db"]["path"] == "/x/ofono-db"


@pytest.mark.parametrize("user,needle", [
    ({"platforms": {"ofono": {"source_tree": {}}}}, "platforms.ofono.source_tree"),
    ({"platforms": {"android": {"work_dir": "/x"}}}, "platforms.android"),
    ({"platforms": {"Bad": {}}}, "platforms.Bad"),
    ({"platforms": []}, "platforms"),
    ({"platform": "../x"}, "platform"),
])
def test_profile_problems_rejected(home, user, needle):
    problems = userconfig.profile_problems(user)
    assert problems and any(p.startswith(needle) for p in problems)
    with pytest.raises(platforms.PlatformConfigError):
        session.resolve({"platform": ON}, None, user)


def test_compiled_environment_platform():
    defaults = yaml.safe_load((REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8"))
    assert compiled.environment(defaults) == compiled.environment(defaults, "android")
    other = compiled.environment({**defaults, "platform": ON}, "ofono")
    assert other["backend"] == {"name": "ofono_reference", "version": "0.0.1"} and other["external"] == {}   # 묶음 3 백엔드


# -- CLI: config set/show --platform ---------------------------------------------------------


def test_config_set_and_show_platform_profile():
    root = _root_on()
    h = tmp("tt-home-")
    env = {"TELEPHONY_TRIAGE_HOME": h}
    answers = h.parent / "answers.json"
    answers.write_text(json.dumps({"user.ghe_id": "u", "issue_db.path": str(h / "db"),
                                   "issue_db.remote": "https://ghe.mock.invalid/o/db.git"}), encoding="utf-8")
    assert run("config.py", ["init", "--answers", answers], root=root, env=env).returncode == 0
    proc = run("config.py", ["set", "--platform", "ofono", "issue_db.path", str(h / "ofono-db")], root=root, env=env)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["key"] == "platforms.ofono.issue_db.path"
    data = yaml.safe_load((h / "config.yaml").read_text(encoding="utf-8"))
    assert data["platforms"]["ofono"]["issue_db"]["path"] == str(h / "ofono-db")
    assert data["issue_db"]["path"] == str(h / "db")
    proc = run("config.py", ["set", "--platform", "ofono", "tracker.mcp_server", "x"], root=root, env=env)
    assert proc.returncode == 2 and "플랫폼 프로필 키가 아닙니다" in proc.stderr
    show = json.loads(run("config.py", ["show", "--platform", "ofono", "--keys", "work_dir,issue_db.path"],
                          root=root, env=env).stdout)
    assert show["values"] == {"work_dir": str(h / "work-ofono"), "issue_db.path": str(h / "ofono-db")}
    show = json.loads(run("config.py", ["show", "--keys", "work_dir"], root=root, env=env).stdout)
    assert show["values"] == {"work_dir": str(h / "work")}
    # 켜지 않은 설치에서 --platform ofono는 사용 오류
    proc = run("config.py", ["show", "--platform", "ofono"], env=env)
    assert proc.returncode == 2 and "켜져 있지 않습니다" in proc.stderr


class _Init:
    """임시 홈 하나에서 `config.py init --answers`를 부르는 도우미 (켠 플랫폼 android·ofono)."""

    def __init__(self):
        self.root = _root_on()
        self.h = tmp("tt-home-")
        self.env = {"TELEPHONY_TRIAGE_HOME": self.h}
        self.n = 0

    def run(self, answers: dict, *extra: str, env: dict | None = None):
        self.n += 1
        path = self.h.parent / f"ans-{self.n}.json"
        path.write_text(json.dumps(answers), encoding="utf-8")
        return run("config.py", ["init", "--answers", path, *extra], root=self.root, env={**self.env, **(env or {})})

    def ok(self, answers: dict, *extra: str, env: dict | None = None) -> dict:
        proc = self.run(answers, *extra, env=env)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def config(self) -> dict:
        return yaml.safe_load((self.h / "config.yaml").read_text(encoding="utf-8"))

    def write(self, data: dict) -> None:
        (self.h / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    def android(self, db="dbA", **over) -> dict:
        return {"user.ghe_id": "u", "issue_db.path": str(self.h / db),
                "issue_db.remote": f"https://ghe.mock.invalid/o/{db}.git", **over}


TOOLS = {"mcp_server": "mock-jira", "tools": {"get_issue": "mcp__mock-jira__jira_fetch_ticket"},
         "read_tools": ["mcp__mock-jira__jira_fetch_ticket"]}


def test_ofono_first_then_android_init_adds_top_profile_without_force():
    it = _Init()
    it.ok({**it.android("dbO"), "work_dir": str(it.h / "work-ofono")}, "--platform", "ofono")
    data = it.config()
    assert not any(k in data for k in userconfig.PROFILE_KEYS)       # 따로 설치: 최상위 프로필 없음
    data["tracker"] = TOOLS
    data["plugin"]["extra"] = 1
    data["platforms"]["ofono"]["code_profiles"] = [{"name": "o", "path": str(it.h / "src")}]
    it.write(data)
    it.ok({**it.android("dbA"), "user.ghe_id": "ignored"}, "--platform", "android")      # --force 없이 더한다
    after = it.config()
    assert after["issue_db"] == {"path": str(it.h / "dbA"), "remote": "https://ghe.mock.invalid/o/dbA.git"}
    assert after["user"] == data["user"] and after["tracker"] == TOOLS and after["plugin"] == data["plugin"]
    assert after["platforms"] == data["platforms"]                   # code_profiles 포함 그대로
    proc = it.run(it.android("dbA2"), "--platform", "android")       # 이제 최상위 프로필이 있다
    assert proc.returncode == 2 and "set" in proc.stderr and "--force" in proc.stderr
    assert it.config() == after


def test_android_first_then_ofono_init_keeps_top_profile():
    it = _Init()
    it.ok(it.android("dbA", **{"issue_db.base_branch": "dev"}))
    before = it.config()
    it.ok({"issue_db.path": str(it.h / "dbO"), "issue_db.remote": "https://ghe.mock.invalid/o/dbO.git"},
          "--platform", "ofono")
    after = it.config()
    assert {k: v for k, v in after.items() if k != "platforms"} == before
    assert after["platforms"]["ofono"]["issue_db"]["path"] == str(it.h / "dbO")


def test_android_reinit_requires_force_and_keeps_keys_outside_fields():
    it = _Init()
    (it.h / "logs").mkdir(parents=True)
    it.ok(it.android("dbA", **{"issue_db.base_branch": "dev", "log_dir": str(it.h / "logs")}))
    it.ok({"issue_db.path": str(it.h / "dbO"), "issue_db.remote": "https://ghe.mock.invalid/o/dbO.git"},
          "--platform", "ofono")
    data = it.config()
    data.update(platform="ofono", tracker={**TOOLS, "timezone": "UTC"})
    data["plugin"]["extra"] = 1
    it.write(data)
    proc = it.run(it.android("dbA2"))
    assert proc.returncode == 2 and "--force" in proc.stderr and it.config() == data
    # 개인 기본 platform: ofono여도 init은 android(site 기본)를 고른다 — ofono 프로필을 덮지 않는다
    it.ok(it.android("dbA2", **{"user.ghe_id": "u2"}), "--force")
    after = it.config()
    assert after["issue_db"] == {"path": str(it.h / "dbA2"), "remote": "https://ghe.mock.invalid/o/dbA2.git",
                                 "base_branch": "dev"}            # 답에 없는 키는 그대로
    assert after["log_dir"] == str(it.h / "logs") and after["user"]["ghe_id"] == "u2"
    assert after["tracker"] == {**TOOLS, "timezone": "UTC"}
    assert after["plugin"]["extra"] == 1 and after["plugin"]["scripts_path"] == str(it.root / "scripts")
    assert after["platform"] == "ofono" and after["platforms"] == data["platforms"]
    # TT_PLATFORM=ofono면 ofono 프로필을 다시 만든다(최상위는 그대로)
    it.ok({"issue_db.path": str(it.h / "dbO2"), "issue_db.remote": "https://ghe.mock.invalid/o/dbO2.git"}, "--force",
          env={"TT_PLATFORM": "ofono"})
    final = it.config()
    assert final["platforms"]["ofono"]["issue_db"]["path"] == str(it.h / "dbO2")
    assert {k: v for k, v in final.items() if k != "platforms"} == {k: v for k, v in after.items() if k != "platforms"}


def test_android_reinit_updates_only_entered_keys():
    it = _Init()
    custom = it.h / "my-work"
    it.ok(it.android("dbA", **{"logcat.timezone": "UTC", "work_dir": str(custom), "issue_db.base_branch": "dev"}))
    data = it.config()
    data["tracker"] = TOOLS
    it.write(data)
    it.ok({"user.ghe_id": "u2"}, "--force")                         # 필수 키도 기존 값이 있으면 생략 가능
    after = it.config()
    assert after["logcat"] == {"timezone": "UTC"} and after["work_dir"] == str(custom)
    assert after["issue_db"]["base_branch"] == "dev" and after["user"]["ghe_id"] == "u2" and after["tracker"] == TOOLS
    # 빈 답(선택 항목)·팀 기본값과 같은 답은 지워 상속한다
    it.ok({"logcat.timezone": "", "issue_db.base_branch": "main"}, "--force")
    after = it.config()
    assert "logcat" not in after and "base_branch" not in after["issue_db"] and after["work_dir"] == str(custom)
    proc = it.run({"issue_db.path": ""}, "--force")                 # 필수 키를 비우면 거부
    assert proc.returncode == 2 and "issue_db.path: 값이 필요합니다" in proc.stderr


def test_android_reinit_stdin_enter_keeps_current_values():
    import config as config_cli
    it = _Init()
    custom = it.h / "my-work"
    it.ok(it.android("dbA", **{"logcat.timezone": "UTC", "work_dir": str(custom)}))
    before = it.config()
    proc = run("config.py", ["init", "--force"], root=it.root, env=it.env, stdin="\n" * len(config_cli.FIELDS))
    assert proc.returncode == 0, proc.stderr
    assert f"[{custom}]" in proc.stderr and "[UTC]" in proc.stderr          # 기본값 = 지금 값
    assert it.config() == before


def test_android_reinit_stdin_dash_resets_to_team_default():
    import config as config_cli
    it = _Init()
    (it.h / "logs").mkdir(parents=True)
    it.ok(it.android("dbA", **{"logcat.timezone": "UTC", "log_dir": str(it.h / "logs")}))
    keys = [f[0] for f in config_cli.FIELDS]
    lines = ["-" if k in ("logcat.timezone", "log_dir") else "" for k in keys]
    proc = run("config.py", ["init", "--force"], root=it.root, env=it.env, stdin="\n".join(lines) + "\n")
    assert proc.returncode == 0, proc.stderr
    assert "(Enter=지금 값 유지, -=팀 기본값" in proc.stderr and "-=팀 기본값 없음)" in proc.stderr   # log_dir 팀 기본값 없음
    after = it.config()
    assert "logcat" not in after and "log_dir" not in after and after["issue_db"]["path"] == str(it.h / "dbA")


def test_other_platform_force_updates_only_entered_keys():
    it = _Init()
    it.ok(it.android("dbA"))
    custom = it.h / "wo-custom"
    it.ok({"issue_db.path": str(it.h / "dbO"), "issue_db.remote": "https://ghe.mock.invalid/o/dbO.git",
           "work_dir": str(custom)}, "--platform", "ofono")
    data = it.config()
    data["platforms"]["ofono"]["code_profiles"] = [{"name": "o", "path": str(it.h / "src")}]
    it.write(data)
    it.ok({"issue_db.path": str(it.h / "dbO2")}, "--platform", "ofono", "--force")      # 원격·work_dir 생략 = 유지
    prof = it.config()["platforms"]["ofono"]
    assert prof["issue_db"] == {"path": str(it.h / "dbO2"), "remote": "https://ghe.mock.invalid/o/dbO.git"}
    assert prof["work_dir"] == str(custom) and prof["code_profiles"] == data["platforms"]["ofono"]["code_profiles"]
    assert {k: v for k, v in it.config().items() if k != "platforms"} == {k: v for k, v in data.items() if k != "platforms"}
    it.ok({"work_dir": str(it.h / "work-ofono")}, "--platform", "ofono", "--force")    # 팀 기본값과 같은 답 = 지움
    assert "work_dir" not in it.config()["platforms"]["ofono"]
    import config as config_cli
    n = sum(f[0].split(".")[0] in userconfig.PROFILE_KEYS for f in config_cli.FIELDS)     # 프로필 항목만 묻는다
    proc = run("config.py", ["init", "--platform", "ofono", "--force"], root=it.root, env=it.env, stdin="\n" * n)
    assert proc.returncode == 0 and f"[{it.h / 'dbO2'}]" in proc.stderr          # 기본값 = 그 프로필의 지금 값
    assert it.config()["platforms"]["ofono"]["issue_db"]["path"] == str(it.h / "dbO2")


def test_android_reinit_warns_when_work_dir_with_jobs_changes():
    it = _Init()
    old = it.h / "w1"
    it.ok(it.android("dbA", work_dir=str(old)))
    (old / "MOCK-1").mkdir()
    proc = it.run({"work_dir": str(it.h / "w2")}, "--force")
    assert proc.returncode == 0 and f"이전 work_dir {old}에 작업 1개" in proc.stderr


@pytest.mark.parametrize("bad", [["ofono"], "ofono"])
def test_init_rejects_non_mapping_platforms(bad):
    it = _Init()
    it.ok(it.android("dbA"))
    data = it.config()
    data["platforms"] = bad
    it.write(data)
    before = (it.h / "config.yaml").read_bytes()
    for extra in (("--force",), ("--platform", "ofono")):
        proc = it.run(it.android("dbA2"), *extra)
        assert proc.returncode == 2 and "platforms: 매핑이어야 합니다" in proc.stderr and "Traceback" not in proc.stderr
        assert (it.h / "config.yaml").read_bytes() == before


def test_init_rejects_unknown_tracker_kind_and_legacy_keys():
    it = _Init()
    it.ok(it.android("dbA"))
    for over, needle in (({"tracker": {"kind": "nosuch"}}, "config.py set tracker.kind"), ({"jira": {"mcp_server": "x"}}, "rename-legacy로 바꾼다")):
        it.write({**it.config(), **over})
        before = (it.h / "config.yaml").read_bytes()
        proc = it.run(it.android("dbA2"), "--force")
        assert proc.returncode == 2 and needle in proc.stderr, proc.stderr
        assert (it.h / "config.yaml").read_bytes() == before
        data = it.config()
        for k in over:
            data.pop(k)
        it.write(data)


def test_init_rejects_invalid_new_config_without_touching_file():
    it = _Init()
    it.ok(it.android("dbA"))
    it.ok({"issue_db.path": str(it.h / "dbO"), "issue_db.remote": "https://ghe.mock.invalid/o/dbO.git"},
          "--platform", "ofono")
    before = (it.h / "config.yaml").read_bytes()
    (it.h / "w").mkdir()
    cases = [
        ((it.android("w/db", **{"work_dir": str(it.h / "w")}), "--force"), "clone)를 포함하거나 같습니다"),
        ((it.android("dbO"), "--force"), "같은 clone"),                                  # 남긴 ofono 프로필과 겹침
        (({"issue_db.path": str(it.h / "dbA"), "issue_db.remote": "https://ghe.mock.invalid/o/x.git"},
          "--platform", "ofono", "--force"), "같은 clone"),                               # 최상위와 겹침
        ((it.android("dbA3", **{"work_dir": "rel"}), "--force"), "절대 경로"),
    ]
    for (answers, *extra), needle in cases:
        proc = it.run(answers, *extra)
        assert proc.returncode == 2 and needle in proc.stderr, (extra, proc.stderr)
        assert (it.h / "config.yaml").read_bytes() == before


def test_init_force_rebuilds_config_with_broken_paths():
    it = _Init()
    it.write({"user": {"ghe_id": "u"}, "work_dir": "work", "issue_db": {"path": "db"}})     # 상대 경로(프로필 문제)
    assert run("config.py", ["check"], root=it.root, env=it.env).returncode == 2
    it.ok(it.android("dbA", work_dir=""), "--force")              # 빈 답은 지워 상속
    after = it.config()
    assert "work_dir" not in after and after["issue_db"]["path"] == str(it.h / "dbA")
    assert userconfig.profile_problems(after) == []


# -- lock: 플랫폼별 --------------------------------------------------------------------------


def test_lock_is_per_platform():
    ws = Workspace(root=_root_on(), build=False)
    cfg = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"] = {"ofono": {"work_dir": str(ws.base / "work-ofono")}}
    (ws.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

    ofono = ws.db_pr("--platform", "ofono", "lock", "acquire", "OFN-1")
    assert ofono["lock"]["platform"] == "ofono"
    record = json.loads((ws.base / "work-ofono" / "session.lock").read_text(encoding="utf-8"))
    assert record["platform"] == "ofono" and record["job"] == "OFN-1"
    android = ws.db_pr("lock", "acquire", "AND-1")                       # 다른 플랫폼 lock이 있어도 허용
    assert "platform" not in android["lock"]
    assert "platform" not in json.loads((ws.work / "session.lock").read_text(encoding="utf-8"))
    proc = ws.run("db_pr.py", ["--platform", "ofono", "lock", "acquire", "OFN-2"])   # 같은 플랫폼 두 작업은 거부
    assert proc.returncode == 2 and "OFN-1" in proc.stderr
    proc = ws.run("db_pr.py", ["lock", "acquire", "AND-2"])
    assert proc.returncode == 2 and "AND-1" in proc.stderr
    # touch(TT_LOCK_OWNER)는 platform을 지키고, status는 그 플랫폼 lock만 본다
    status = ws.db_pr("--platform", "ofono", "lock", "status")
    assert status["lock"]["job"] == "OFN-1"
    ws.db_pr("--platform", "ofono", "lock", "release", "OFN-1", "--force")
    ws.db_pr("lock", "release", "AND-1", "--force")


# -- platform-mismatch ------------------------------------------------------------------------


def test_config_check_platform_mismatch():
    root = _root_on()
    env = {"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")}
    proc = run("config.py", ["check", "--db", SAMPLE, "--for", "dry-run", "--platform", "ofono"], root=root, env=env)
    out = json.loads(proc.stdout)
    assert proc.returncode == 2 and [r["code"] for r in out["reasons"]][0] == "platform-mismatch"
    assert "이슈 DB는 android, 선택한 플랫폼은 ofono" in proc.stderr
    proc = run("config.py", ["check", "--db", ofono_db(), "--for", "dry-run"], root=root, env=env)
    assert proc.returncode == 2 and "이슈 DB는 ofono, 선택한 플랫폼은 android" in proc.stderr
    ok = run("config.py", ["check", "--db", SAMPLE, "--for", "dry-run"], root=root, env=env)
    assert ok.returncode == 0, ok.stderr


def test_config_check_mismatch_on_migrate_branch():
    info = make_repo.make(ofono_db(), tmp("tt-repo-") / "r")
    clone = Path(info["clone"])
    git(clone, "checkout", "-q", "-b", "migrate/schema-v1")
    proc = run("config.py", ["check", "--db", clone, "--for", "dry-run"], root=_root_on(),
               env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})
    out = json.loads(proc.stdout)
    assert proc.returncode == 2 and out["migrate_branch"] is True
    assert [r["code"] for r in out["reasons"]] == ["platform-mismatch"]


def test_parse_logcat_db_platform_vs_env():
    root = _root_on()
    args = ["parse", DATA_LOG, "--rules", SAMPLE / "parser-rules", "--full", "--tz", "UTC", "--year", "2026"]
    proc = run("parse_logcat.py", args, root=root, env={platforms.ENV: "ofono"})
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr
    same = run("parse_logcat.py", args, root=root, env={platforms.ENV: "android"})
    assert same.returncode == 0, same.stderr
    # DB 고정 도구(K6): ofono를 켜지 않은 설치도 ofono DB 선언을 따른다(ofono_reference 백엔드 → logcat 줄은 해석 못 함)
    db = ofono_db()
    proc = run("parse_logcat.py", ["parse", DATA_LOG, "--rules", db / "parser-rules", "--full"])
    assert proc.returncode == 0 and "켜져 있지 않습니다" not in proc.stderr, proc.stderr
    out = json.loads(proc.stdout)
    assert out["backend"]["name"] == "ofono_reference" and "file-unparsed" in {w["code"] for w in out["warnings"]}


def test_triage_offline_platform_mismatch_stops():
    out = tmp("tt-triage-") / "job"
    meta = out.parent / "meta.json"
    meta.write_text(json.dumps({"key": "MOCK-1", "occurred_at": "2026-09-20T05:32:00Z", "summary": "x"}), encoding="utf-8")
    args = ["run", "MOCK-1", "--offline-db", SAMPLE, "--out", out, "--logs", DATA_LOG, "--issue-meta", meta,
            "--platform", "ofono"]
    proc = run("triage.py", args, root=_root_on(), env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr
    assert not (out / "analysis.json").exists()
    proc = run("triage.py", args, env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})
    assert proc.returncode == 2 and "켜져 있지 않습니다" in proc.stderr


def test_db_pr_snapshot_platform_mismatch():
    ws = Workspace(root=_root_on(), build=False)
    other = Path(make_repo.make(SAMPLE, ws.base / "other-android")["clone"])     # 실수로 ofono 프로필이 android DB를 가리킨다
    cfg = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"] = {"ofono": {"issue_db": {"path": str(other), "remote": "https://ghe.mock.invalid/o/x.git"},
                                  "work_dir": str(ws.base / "work-ofono")}}
    (ws.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    acquired = ws.db_pr("--platform", "ofono", "lock", "acquire", "OFN-9")
    proc = ws.run("db_pr.py", ["--platform", "ofono", "snapshot", "--job", "OFN-9"],
                  env={"TT_LOCK_OWNER": acquired["lock"]["owner"]})
    assert proc.returncode == 2 and "platform-mismatch" in proc.stdout and "이슈 DB는 android" in proc.stderr
    # 원격 ref에서 먼저 대조하므로 다른 플랫폼 clone에 _snapshot worktree를 만들지 않는다
    assert not (ws.base / "work-ofono" / "_snapshot").exists()
    assert "work-ofono" not in git(other, "worktree", "list")
    ws.db_pr("--platform", "ofono", "lock", "release", "OFN-9", "--force")


def test_profile_paths_must_not_overlap(home):
    clone = str(home / "db")
    base = {"issue_db": {"path": clone, "remote": "https://ghe.mock.invalid/o/a.git"}, "work_dir": str(home / "w")}
    cases = [
        ({"ofono": {"work_dir": str(home)}}, "clone)를 포함하거나 같습니다"),            # clone 상위
        ({"ofono": {"work_dir": clone}}, "clone)를 포함하거나 같습니다"),
        ({"ofono": {"work_dir": ""}}, "절대 경로"),
        ({"ofono": {"work_dir": "work"}}, "절대 경로"),
        ({"ofono": {"work_dir": str(home / "w")}}, "같은 work_dir"),
        ({"ofono": {"issue_db": {"path": clone}}}, "같은 clone"),
        ({"ofono": {"issue_db": {"remote": "https://ghe.mock.invalid/o/A"}}}, "같은 원격"),
        ({"ofono": {"issue_db": "oops"}}, "매핑이어야"),
    ]
    for profs, needle in cases:
        problems = userconfig.profile_problems({**base, "platforms": profs})
        assert any(needle in p for p in problems), (profs, problems)
    assert userconfig.profile_problems({**base, "platforms": {"ofono": {"work_dir": str(home / "w2")}}}) == []
    assert userconfig.profile_problems(base) == []


@pytest.mark.parametrize("platforms_value", ["absent", "empty", "other"])
def test_top_profile_path_problems_same_with_or_without_platforms(home, platforms_value):
    clone = str(home / "db")
    out = home.parent / "elsewhere"          # 최상위 경로와 겹치지 않는 다른 플랫폼 프로필
    ofono = {"ofono": {"work_dir": str(out / "wo"), "issue_db": {"path": str(out / "dbo")}}}
    for top in ({"issue_db": {"path": clone}, "work_dir": "work"},
                {"issue_db": {"path": clone}, "work_dir": ""},
                {"issue_db": {"path": clone}, "work_dir": str(home)},
                {"issue_db": {"path": "db"}},
                {"issue_db": {"path": clone}, "work_dir": str(home / "w")}):
        user = dict(top)
        if platforms_value == "empty":
            user["platforms"] = {}
        elif platforms_value == "other":
            user["platforms"] = ofono
        assert userconfig.profile_problems(user) == userconfig.profile_problems(top), (platforms_value, top)


def test_config_validate_path_kinds(home, monkeypatch):
    import config as config_cli
    monkeypatch.setenv("HOME", str(home.parent))
    for kind in ("clone-path", "work-dir"):
        assert "절대 경로" in config_cli.validate(kind, "rel/x")
        assert config_cli.validate(kind, str(home.parent / "x")) is None
        assert config_cli.validate(kind, "~/x") is None
        assert config_cli.validate(kind, "") is None             # 빈 값은 선택 항목 건너뜀(필수는 init이 따로 거부)


def test_check_and_doctor_report_top_level_path_problem():
    root = _root_on()
    h = tmp("tt-home-")
    env = {"TELEPHONY_TRIAGE_HOME": h}
    (h / "config.yaml").write_text(yaml.safe_dump({"user": {"ghe_id": "u"}, "work_dir": "work",
                                                   "issue_db": {"path": str(h / "db")}}), encoding="utf-8")
    proc = run("config.py", ["check"], root=root, env=env)
    assert proc.returncode == 2 and "work_dir: 비어 있지 않은 절대 경로" in proc.stderr
    proc = run("config.py", ["doctor"], root=root, env=env)
    rows = {r["check"]: r for r in json.loads(proc.stdout)["rows"]}
    assert proc.returncode == 1 and rows["platform"]["status"] == "fail" and "work_dir" in rows["platform"]["detail"]


def test_top_profile_paths_checked_without_platforms(home):
    clone = str(home / "db")
    base = {"issue_db": {"path": clone}}
    problems = userconfig.profile_problems({**base, "work_dir": "work"})
    assert any(p.startswith("work_dir: 비어 있지 않은 절대 경로") for p in problems), problems
    problems = userconfig.profile_problems({**base, "work_dir": str(home)})          # platforms 없이도 clone 포함 검사
    assert any("clone)를 포함하거나 같습니다" in p for p in problems), problems
    with pytest.raises(platforms.PlatformConfigError):
        session.resolve({"platform": ON}, None, {"work_dir": "work"})
    _name, _cfg, problems = session.resolve_lenient({"platform": ON}, None, {"work_dir": ""})
    assert any("work_dir" in p for p in problems), problems


# -- 이슈 DB 키 --------------------------------------------------------------------------------


@pytest.mark.parametrize("prefix,needle", [
    ("platform: foo\n", "설치된 플랫폼이 아닙니다"),
    ("platform: Ofono\n", "플랫폼 이름"),
    ("android_versions_supported: ['2']\n", "옛 설정 키 android_versions_supported"),
    ("jira_key_regex: 'X-\\d+'\n", "옛 설정 키 jira_key_regex"),
    ("jira_base_url: https://x.invalid/\n", "tracker.base_url로"),
])
def test_db_lint_platform_config(prefix, needle):
    db = tmp("tt-lint-") / "db"
    shutil.copytree(SAMPLE, db)
    cfg = db / "issue-db.config.yaml"
    cfg.write_text(prefix + cfg.read_text(encoding="utf-8"), encoding="utf-8")
    proc = run("db_lint.py", ["--all", "--db", db])
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert any(e["code"] == "config" and needle in e["message"] for e in out["errors"])


def test_db_lint_ofono_declaration_passes_config_check():
    proc = run("db_lint.py", ["--all", "--db", ofono_db()])
    out = json.loads(proc.stdout)
    assert not [e for e in out["errors"] if e["code"] == "config"]


# -- 따로 설치(site 기본 ofono, android 최상위 프로필 없음) (리뷰 P1-3) ---------------------------------


def test_ofono_only_install_setup_and_tools():
    root = plugin_root("ofono-site", platform={"name": "ofono"})
    h = tmp("tt-home-")
    env = {"TELEPHONY_TRIAGE_HOME": h}
    side = tmp("tt-side-")
    info = make_repo.make(ofono_db(), side / "repo")
    clone = Path(info["clone"])
    answers = side / "ans.json"
    answers.write_text(json.dumps({"user.ghe_id": "u", "issue_db.path": str(clone),
                                   "issue_db.remote": "https://ghe.mock.invalid/o/ofono-db.git"}), encoding="utf-8")
    proc = run("config.py", ["init", "--answers", answers], root=root, env=env)
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load((h / "config.yaml").read_text(encoding="utf-8"))
    assert "issue_db" not in data and data["platforms"]["ofono"]["issue_db"]["path"] == str(clone)
    assert data["user"]["ghe_id"] == "u" and data["plugin"]["scripts_path"]
    show = json.loads(run("config.py", ["show", "--keys", "work_dir,issue_db.path"], root=root, env=env).stdout)
    assert show["values"] == {"work_dir": str(h / "work-ofono"), "issue_db.path": str(clone)}
    check = run("config.py", ["check", "--for", "dry-run"], root=root, env=env)
    assert "platform-mismatch" not in check.stdout
    doctor = json.loads(run("config.py", ["doctor"], root=root, env=env).stdout)
    rows = {r["check"]: r for r in doctor["rows"]}
    assert rows["config"]["status"] == "ok" and rows["clone"]["status"] == "ok" and "platform" not in rows
    # guard: ofono clone 보호, lock은 ofono work_dir
    event = {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": str(clone / "x.md")},
             "cwd": str(h)}
    out = run("guard.py", [], root=root, env=env, stdin=json.dumps(event))
    assert json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    lock = json.loads(run("db_pr.py", ["lock", "acquire", "OFN-1"], root=root, env=env).stdout)
    assert lock["lock"]["platform"] == "ofono" and (h / "work-ofono" / "session.lock").is_file()
    run("db_pr.py", ["lock", "release", "OFN-1", "--force"], root=root, env=env)
    # pre-push: 최상위 프로필 없이 platforms.ofono(base main)로 판정
    git(clone, "config", "core.hooksPath", ".githooks")
    (clone / "CONTRIBUTING.md").write_text("편집\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "--no-verify", "-m", "편집")
    hook_env = dict(os.environ, TELEPHONY_TRIAGE_HOME=str(h), TT_PUBLISH_TOKEN="manual")
    proc = __import__("subprocess").run(["git", "-C", str(clone), "push", "-q", "origin", "HEAD:refs/heads/main"],
                                        capture_output=True, text=True, env=hook_env)
    assert proc.returncode != 0 and "base 브랜치(main)" in proc.stderr


# -- 플랫폼 키 문제가 있어도 config show·set·doctor는 돈다 (리뷰 P2-3) ------------------------------------


def test_config_fix_path_with_profile_problems():
    root = _root_on()
    h = tmp("tt-home-")
    env = {"TELEPHONY_TRIAGE_HOME": h}
    (h / "config.yaml").write_text(yaml.safe_dump({"issue_db": {"path": str(h / "db")}, "work_dir": str(h / "w"),
                                                   "platforms": {"ofono": {"source_tree": {}, "work_dir": str(h / "w")}}}),
                                   encoding="utf-8")
    show = run("config.py", ["show", "--keys", "work_dir"], root=root, env=env)
    assert show.returncode == 0 and "platforms.ofono.source_tree" in show.stderr
    doctor = json.loads(run("config.py", ["doctor"], root=root, env=env).stdout)
    row = next(r for r in doctor["rows"] if r["check"] == "platform")
    assert row["status"] == "fail"
    out = run("config.py", ["set", "--platform", "ofono", "work_dir", str(h / "w-ofono")], root=root, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["problems"]       # source_tree는 아직 남았다
    proc = run("db_pr.py", ["lock", "status"], root=root, env=env)
    assert proc.returncode == 2 and "source_tree" in proc.stderr               # 그 밖 스크립트는 멈춘다
    check = run("config.py", ["check", "--for", "dry-run", "--db", SAMPLE], root=root, env=env)
    assert check.returncode == 2


# -- 알려진 공백: stage·publish 불일치, triage 재실행 불일치, issue_post 분석 플랫폼 ---------------------


def _ofono_ws() -> Workspace:
    ws = Workspace(root=_root_on(), build=False)
    cfg = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"] = {"ofono": {"work_dir": str(ws.base / "work-ofono")}}
    (ws.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return ws


def test_db_pr_stage_and_publish_refuse_other_platform_db():
    ws = _ofono_ws()
    owork = ws.base / "work-ofono"
    (owork / "_snapshot").mkdir(parents=True)
    shutil.copyfile(SAMPLE / "issue-db.config.yaml", owork / "_snapshot" / "issue-db.config.yaml")   # android 선언
    plan = owork / "OFN-3" / "plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text("{}", encoding="utf-8")
    proc = ws.run("db_pr.py", ["--platform", "ofono", "stage", plan, "--wt", owork / "OFN-3" / "wt", "--branch", "issue/OFN-3"])
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr and "platform-mismatch" in proc.stdout
    wt = owork / "OFN-3" / "wt"
    wt.mkdir()
    shutil.copyfile(SAMPLE / "issue-db.config.yaml", wt / "issue-db.config.yaml")
    proc = ws.run("db_pr.py", ["--platform", "ofono", "publish", wt, "--branch", "issue/OFN-3", "--lease", "new",
                               "--approved", "0" * 40])
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr


def test_triage_rerun_with_other_platform_stops():
    ws = _ofono_ws()
    job = ws.work / "MOCK-7501"
    job.mkdir(parents=True)
    (job / "triage-state.json").write_text(json.dumps({"platform": "ofono"}), encoding="utf-8")
    proc = ws.run("triage.py", ["run", "MOCK-7501", "--logs", DATA_LOG])
    assert proc.returncode == 2 and "이 작업은 ofono 플랫폼이다" in proc.stderr
    assert not (ws.work / "session.lock").exists()


def test_issue_post_refuses_analysis_of_other_platform():
    ws = _ofono_ws()
    for work, analysis in ((ws.base / "work-ofono", {"status": "ok"}), (ws.work, {"status": "ok", "platform": "ofono"})):
        (work / "MOCK-7601").mkdir(parents=True, exist_ok=True)
        (work / "MOCK-7601" / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")
    proc = ws.run("issue_post.py", ["status", "MOCK-7601", "--platform", "ofono"])
    assert proc.returncode == 2 and "이 분석은 android 플랫폼이다" in proc.stderr
    proc = ws.run("issue_post.py", ["status", "MOCK-7601"])
    assert proc.returncode == 2 and "이 분석은 ofono 플랫폼이다" in proc.stderr


def test_ref_platform_mismatch_helper():
    from dbpr.worktree import ref_platform_mismatch
    info = make_repo.make(ofono_db(), tmp("tt-repo-") / "r")
    clone = Path(info["clone"])
    assert ref_platform_mismatch(clone, "origin/main", "ofono") == []
    assert ref_platform_mismatch(clone, "origin/main", "android")[0]["code"] == "platform-mismatch"
    assert ref_platform_mismatch(clone, "origin/nosuch", "android") is None
