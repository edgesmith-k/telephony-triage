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
        "jira",
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
    assert cfg["issue_db"]["path"] == str(clone) and cfg["issue_db"]["base_branch"] == "main"
    assert cfg["issue_db"]["ghe_host"] == "ghe.mock.invalid"
    assert cfg["jira"]["timezone"] == "Asia/Seoul" and cfg["logcat"]["timezone"] == "UTC"
    assert "log_dir" not in cfg
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


# -- Jira MCP ------------------------------------------------------------------------


def test_jira_tools_from_nonstandard_mock_server():
    env = Env()  # 테스트 헬퍼 루트: exclude_servers: []
    env.init(env.base / "db")
    found = env.json("config.py", ["jira-candidates", "--mcp-config", MCP_CONFIG])
    assert found["usable"] == ["mock-jira"] and found["exclude_servers"] == []
    (server,) = found["servers"]
    assert server["suggested"] == {"get_issue": "mcp__mock-jira__jira_fetch_ticket",
                                   "search_issues": "mcp__mock-jira__jira_query_tickets",
                                   "get_comments": "mcp__mock-jira__jira_ticket_comments"}
    # 쓰기 도구는 후보가 아니다
    assert "mcp__mock-jira__jira_post_comment" in server["tools"]
    assert not any("post_comment" in t or "move_ticket" in t for t in server["read_tools"])

    # 사용자가 확인한 값을 저장한다. read_tools에는 jira.tools 값이 들어간다(전체 이름)
    saved = env.json("config.py", ["set-jira", "--server", "mock-jira",
                                   "--get-issue", "mcp__mock-jira__jira_fetch_ticket",
                                   "--search-issues", "mcp__mock-jira__jira_query_tickets",
                                   "--read-tools", "mcp__mock-jira__jira_ticket_comments"])
    assert saved["added_to_read_tools"] == ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets"]
    jira = env.config()["jira"]
    assert jira["mcp_server"] == "mock-jira"
    assert jira["tools"] == {"get_issue": "mcp__mock-jira__jira_fetch_ticket",
                             "search_issues": "mcp__mock-jira__jira_query_tickets"}
    assert jira["read_tools"] == ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets",
                                  "mcp__mock-jira__jira_ticket_comments"]
    # 짧은 이름·다른 서버 도구는 거부
    assert env.run("config.py", ["set-jira", "--server", "mock-jira", "--get-issue", "jira_fetch_ticket"]).returncode == 2
    assert env.run("config.py", ["set-jira", "--server", "mock-jira",
                                 "--get-issue", "mcp__other__get_issue"]).returncode == 2


def test_jira_server_names_are_normalized_like_session_tool_names():
    """R-2: 세션 도구 이름은 서버 이름의 `[^A-Za-z0-9_-]`를 `_`로 쓴다(관측 기반 추정, S1 확인).
    후보는 세션 이름으로 만들고, set-jira는 원래 서버 이름과 세션 이름을 같은 서버로 본다(저장값은 그대로)."""
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
    saved = env.json("config.py", ["set-jira", "--server", "jira.corp", "--get-issue", "mcp__jira_corp__get_issue"])
    assert saved["tools"]["get_issue"] == "mcp__jira_corp__get_issue" and env.config()["jira"]["mcp_server"] == "jira.corp"
    assert env.run("config.py", ["set-jira", "--server", "jira.corp",
                                 "--get-issue", "mcp__jira_other__get_issue"]).returncode == 2


def test_excluded_mock_servers():
    root = plugin_root("exclude-mock", jira={**yaml.safe_load(
        (REPO / "plugin/site-defaults.example.yaml").read_text(encoding="utf-8"))["jira"], "exclude_servers": ["mock-*"]})
    env = Env(root=root)
    found = env.json("config.py", ["jira-candidates", "--mcp-config", MCP_CONFIG])
    assert found["usable"] == [] and found["servers"][0]["excluded"] is True
    assert found["servers"][0]["tools"] == [] and "중단" in found["next"]


def test_missing_site_defaults_stops_everything():
    bare = tmp("tt-bare-root-") / "root"
    make_plugin_root.make(bare)
    (bare / "site-defaults.yaml").unlink()  # example은 남아 있다 — 읽지 않아야 한다
    assert (bare / "site-defaults.example.yaml").is_file()
    env = Env(root=bare)
    for script, args in (("config.py", ["init"]), ("config.py", ["check", "--db", SAMPLE]),
                         ("config.py", ["jira-candidates", "--mcp-config", MCP_CONFIG]), ("config.py", ["doctor"]),
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
    env.json("db_build.py", ["--cache-only", "--db", snap["snapshot"]])
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
    assert (snap / ".cache/compiled.json").is_file()
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

    # 사용자 clone의 브랜치·워킹 트리·HEAD가 그대로다 (캐시는 스냅샷에만)
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
    edit(clone / "issue-db.config.yaml", "generator_version: 1", "generator_version: 2")
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
    # 같은 작업 키, 10분 이내 갱신 → --take-over 없이는 2, 있으면 이어받음
    assert env.run("db_pr.py", ["lock", "acquire", "MOCK-1101"], env=at(5)).returncode == 2
    taken = env.json("db_pr.py", ["lock", "acquire", "MOCK-1101", "--take-over"], env=at(5))
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
        {"name": "android17-dev", "android_version": "17",
         "roots": {"aosp": str(SRC / "android17"), "vendor_ril": str(SRC / "android17/vendor/mockril")}},
        {"name": "android16-main", "android_version": "16",
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


def _all_tests():
    return [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]


def test_show_keys_returns_only_requested_values_and_lists_missing():
    env = Env()
    env.init(env.base / "db")
    full = env.json("config.py", ["show"])
    out = env.json("config.py", ["show", "--keys", "work_dir,jira.tools,no.such"])
    assert set(out) == {"user_config", "values", "missing"}
    assert out["values"] == {"work_dir": full["effective"]["work_dir"], "jira.tools": full["effective"]["jira"]["tools"]}
    assert out["missing"] == ["no.such"] and out["user_config"] == full["user_config"]
    assert env.json("config.py", ["show"]) == full      # --keys 없으면 이전과 같다


# -- doctor (읽기 전용 점검) ---------------------------------------------------------------------


def _rows(result: dict) -> dict:
    return {r["check"]: r for r in result["rows"]}


def _doctor(env: Env, expect=0, at: dict | None = None, **kw) -> dict:
    result = env.json("config.py", ["doctor"], expect=expect, env=at or {}, **kw)
    assert [r["check"] for r in result["rows"]] == ["config", "scripts_path", "clone", "hook", "jira", "gh",
                                                    "snapshot", "compat", "lock"]
    assert sum(result["counts"].values()) == 9 and all(len(r["detail"]) <= 80 for r in result["rows"])
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


def test_doctor_all_ok_markdown_fits_1kb_and_changes_nothing():
    env, clone = _ready_env()
    before = (_tree(env.base, clone), git(clone, "status", "--porcelain"), git(clone, "for-each-ref"))
    result = _doctor(env)
    assert result["counts"] == {"ok": 9, "warn": 0, "fail": 0, "skip": 0}
    proc = env.run("config.py", ["doctor", "--format", "markdown"])
    assert proc.returncode == 0 and len(proc.stdout.encode("utf-8")) <= 1024, len(proc.stdout.encode("utf-8"))
    lines = proc.stdout.rstrip("\n").splitlines()
    assert lines[0].startswith("| 점검 |") and lines[-1] == "ok 9 · warn 0 · fail 0 · skip 0"
    assert sum(1 for ln in lines if ln.startswith("| ")) == 10          # 헤더 + 9행, 표는 하나
    assert "\n  " not in json.dumps(result) and env.run("config.py", ["doctor"]).stdout.count("\n") == 1
    after = (_tree(env.base, clone), git(clone, "status", "--porcelain"), git(clone, "for-each-ref"))
    assert after == before, "doctor는 읽기 전용이다 (clone·work_dir·config 불변)"
    assert not (env.base / "work" / "session.lock").exists()


def test_doctor_without_config_fails_config_and_skips_the_rest_without_creating_anything():
    env = Env()
    result = _doctor(env, expect=1)
    assert result["counts"] == {"ok": 0, "warn": 0, "fail": 1, "skip": 8}   # skip은 ok로 세지 않는다
    rows = _rows(result)
    assert rows["config"]["status"] == "fail" and "setup" in rows["config"]["next"]
    assert all(r["status"] == "skip" for k, r in rows.items() if k != "config")
    assert not env.home.exists()
    assert env.run("config.py", ["doctor", "--format", "markdown", "--json"]).returncode == 2


def test_doctor_empty_jira_mapping_fails_and_exits_1():
    env, _ = _ready_env()
    _set_user(env, jira={"mcp_server": ""})
    jira = _rows(_doctor(env, expect=1))["jira"]
    assert jira["status"] == "fail" and "mcp_server" in jira["detail"] and "setup 4" in jira["next"]
    _set_user(env, jira={"mcp_server": "mock-jira", "tools": {"get_issue": ""}})
    assert "get_issue" in _rows(_doctor(env, expect=1))["jira"]["detail"]
    _set_user(env, jira={"mcp_server": "mock-jira", "tools": {"get_issue": "jira_fetch_ticket"}})
    assert "전체 이름" in _rows(_doctor(env, expect=1))["jira"]["detail"]
    _set_user(env, jira={"mcp_server": "other", "tools": {"get_issue": "mcp__mock-jira__jira_fetch_ticket"}})
    assert "서버 other의 도구가 아닙니다" in _rows(_doctor(env, expect=1))["jira"]["detail"]


def test_doctor_gh_unauth_is_warn_and_exit_0():
    env, _ = _ready_env()
    result = _doctor(env, unauth=True)
    gh = _rows(result)["gh"]
    assert gh["status"] == "warn" and "gh auth login" in gh["next"]
    assert result["counts"] == {"ok": 8, "warn": 1, "fail": 0, "skip": 0}


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
    assert rows["hook"]["status"] == "fail" and "install-hooks" in rows["hook"]["next"]
    assert rows["snapshot"]["status"] == "warn" and rows["compat"]["status"] == "skip"
    env.json("config.py", ["install-hooks"])
    assert _rows(_doctor(env))["hook"]["status"] == "ok"
    git(clone, "config", "core.hooksPath", "hooks")
    assert "hooks" in _rows(_doctor(env, expect=1))["hook"]["detail"]
    # clone이 아니면 hook은 skip
    _set_user(env, issue_db={"path": str(env.base / "not-a-clone"), "remote": "r"})
    rows = _rows(_doctor(env, expect=1))
    assert rows["clone"]["status"] == "fail" and "git clone" in rows["clone"]["next"] and rows["hook"]["status"] == "skip"


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
    assert _rows(result)["lock"]["status"] == "fail" and result["counts"]["fail"] >= 1
    assert (env.base / "work" / "session.guard").exists() == guard_before    # lock 파일 guard도 만들지 않는다
    lock.unlink()    # 손상 lock은 도구가 풀지 못한다: 사용자가 파일을 확인하고 지운다
    assert _rows(_doctor(env))["lock"]["status"] == "ok"


def test_doctor_refactored_helpers_keep_messages():
    env = Env()
    env.init(env.base / "db")
    proc = env.run("config.py", ["set-jira", "--server", "mock-jira", "--get-issue", "jira_fetch_ticket"])
    assert proc.returncode == 2 and proc.stderr.strip() == "도구 이름은 전체 이름(mcp__<server>__<tool>)이어야 합니다: jira_fetch_ticket"
    proc = env.run("config.py", ["set-jira", "--server", "mock-jira", "--get-issue", "mcp__other__get_issue"])
    assert proc.returncode == 2 and proc.stderr.strip() == "mcp__other__get_issue는 서버 mock-jira의 도구가 아닙니다."


def test_doctor_bad_jira_types_make_a_fail_row_not_a_traceback():
    env, _ = _ready_env()
    _set_user(env, jira={"mcp_server": "mock-jira", "tools": ["get_issue"], "read_tools": "mcp__mock-jira__x"})
    proc = env.run("config.py", ["doctor", "--format", "markdown"])
    assert proc.returncode == 1 and "Traceback" not in proc.stderr and "| jira | fail | " in proc.stdout
    assert "형식 오류" in proc.stdout
    _set_user(env, jira={"mcp_server": "mock-jira", "tools": {"get_issue": "mcp__mock-jira__a"}, "read_tools": "oops"})
    assert "형식 오류" in _rows(_doctor(env, expect=1))["jira"]["detail"]


def test_doctor_does_not_create_missing_work_dir_and_empty_work_dir_skips():
    env, _ = _ready_env()
    import shutil
    shutil.rmtree(env.base / "work")
    before = _tree(env.base)
    rows = _rows(_doctor(env))
    assert not (env.base / "work").exists() and _tree(env.base) == before
    assert rows["snapshot"]["status"] == "warn" and rows["lock"]["status"] == "ok" and rows["compat"]["status"] == "skip"
    _set_user(env, work_dir="")
    rows = _rows(_doctor(env))
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


def test_doctor_worst_case_markdown_fits_1kb():
    clone = Path(_repo()["clone"])
    env = Env()
    env.init(clone)    # hook·snapshot·jira 문제, lock 보유, gh 인증 없음
    _set_user(env, jira={"mcp_server": "mock-jira-with-a-fairly-long-server-name", "tools": {"get_issue": ""}})
    env.json("db_pr.py", ["lock", "acquire", "MOCK-1101-long-job-key", "--command", "analyze"])
    proc = env.run("config.py", ["doctor", "--format", "markdown"], unauth=True)
    assert proc.returncode == 1
    assert proc.stdout.count("| fail |") >= 2 and proc.stdout.count("| warn |") >= 3
    assert len(proc.stdout.encode("utf-8")) <= 1024, len(proc.stdout.encode("utf-8"))


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
