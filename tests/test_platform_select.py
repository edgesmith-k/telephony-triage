"""플랫폼 선택·경로 프로필·lock·불일치 거부 (17-platforms 설계 §3·§4·§7-B, 묶음 2).

- 선택 순서: `--platform` > `TT_PLATFORM` > 사용자 config `platform` > site `platform.name` > android, `enabled` 관문
- 사용자 config 프로필: 다른 플랫폼은 android 경로를 물려받지 않는다, 기본 work_dir·pending-feedback, 허용 키(RF-4)
- lock은 플랫폼(이슈 DB)별(사용자 결정 10/11): ofono lock을 잡은 채 android acquire 허용, 같은 플랫폼 두 작업은 거부
- `platform-mismatch`: config check(migrate 브랜치 포함)·parse_logcat(TT_PLATFORM)·triage(offline)·db_pr snapshot
- 이슈 DB 키: `platform` 값 검사, 지원 버전 키 두 이름 동시 오류
"""

from __future__ import annotations

import json
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
        "work_dir": "/x/work", "code_profiles": [{"name": "a16"}], "jira": {"mcp_server": "mock-jira"},
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
    assert cfg["jira"]["mcp_server"] == "mock-jira"            # Jira는 공유
    assert "platforms" not in cfg


def test_profile_helpers(home):
    assert userconfig.profile_key("android", "work_dir") == "work_dir"
    assert userconfig.profile_key("ofono", "issue_db.path") == "platforms.ofono.issue_db.path"
    with pytest.raises(ValueError):
        userconfig.profile_key("ofono", "jira.mcp_server")
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
    assert other["backend"] == {"name": "ofono_reference", "version": None} and other["external"] == {}


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
    proc = run("config.py", ["set", "--platform", "ofono", "jira.mcp_server", "x"], root=root, env=env)
    assert proc.returncode == 2 and "플랫폼 프로필 키가 아닙니다" in proc.stderr
    show = json.loads(run("config.py", ["show", "--platform", "ofono", "--keys", "work_dir,issue_db.path"],
                          root=root, env=env).stdout)
    assert show["values"] == {"work_dir": str(h / "work-ofono"), "issue_db.path": str(h / "ofono-db")}
    show = json.loads(run("config.py", ["show", "--keys", "work_dir"], root=root, env=env).stdout)
    assert show["values"] == {"work_dir": str(h / "work")}
    # 켜지 않은 설치에서 --platform ofono는 사용 오류
    proc = run("config.py", ["show", "--platform", "ofono"], env=env)
    assert proc.returncode == 2 and "켜져 있지 않습니다" in proc.stderr


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
    # DB 고정 도구(K6): ofono를 켜지 않은 설치도 ofono DB 선언을 따른다(백엔드가 아직 없어 종료 2로 "없습니다")
    db = ofono_db()
    proc = run("parse_logcat.py", ["parse", DATA_LOG, "--rules", db / "parser-rules", "--full"])
    assert proc.returncode == 2 and "ofono_reference" in proc.stderr and "켜져 있지 않습니다" not in proc.stderr


def test_triage_offline_platform_mismatch_stops():
    out = tmp("tt-triage-") / "job"
    meta = out.parent / "meta.json"
    meta.write_text(json.dumps({"key": "MOCK-1", "occurred_at": "2026-09-20T05:32:00Z", "summary": "x"}), encoding="utf-8")
    args = ["run", "MOCK-1", "--offline-db", SAMPLE, "--out", out, "--logs", DATA_LOG, "--jira-meta", meta,
            "--platform", "ofono"]
    proc = run("triage.py", args, root=_root_on(), env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})
    assert proc.returncode == 2 and "플랫폼 불일치" in proc.stderr
    assert not (out / "analysis.json").exists()
    proc = run("triage.py", args, env={"TELEPHONY_TRIAGE_HOME": tmp("tt-home-")})
    assert proc.returncode == 2 and "켜져 있지 않습니다" in proc.stderr


def test_db_pr_snapshot_platform_mismatch():
    ws = Workspace(root=_root_on(), build=False)
    cfg = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
    # 실수로 ofono 프로필이 android clone을 가리킨다
    cfg["platforms"] = {"ofono": {"issue_db": {"path": str(ws.clone)}, "work_dir": str(ws.base / "work-ofono")}}
    (ws.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    acquired = ws.db_pr("--platform", "ofono", "lock", "acquire", "OFN-9")
    proc = ws.run("db_pr.py", ["--platform", "ofono", "snapshot", "--job", "OFN-9"],
                  env={"TT_LOCK_OWNER": acquired["lock"]["owner"]})
    assert proc.returncode == 2 and "platform-mismatch" in proc.stdout and "이슈 DB는 android" in proc.stderr
    ws.db_pr("--platform", "ofono", "lock", "release", "OFN-9", "--force")


# -- 이슈 DB 키 --------------------------------------------------------------------------------


@pytest.mark.parametrize("prefix,needle", [
    ("platform: foo\n", "설치된 플랫폼이 아닙니다"),
    ("platform: Ofono\n", "플랫폼 이름"),
    ("platform_versions_supported: ['2']\n", "중 하나만 둔다"),
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
