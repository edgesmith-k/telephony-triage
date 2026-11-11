#!/usr/bin/env python3
"""OpenCode Jira 읽기 관문(`common/oc_jira_gate.py`, MODULE_SKILLS_DECISIONS "OpenCode Jira 읽기(11/05)") — opencode 없이 도는 테스트.

- 관문 상태: 사용자 설정 `opencode.jira_read: open` + 통과 기록(성공 경로 통과·같은 OpenCode 버전·같은 플러그인 스크립트 지문·
  같은 트래커·MCP 지문), 오류 경로 행이 pass가 아니면(warn·skip) `--accept-error-bodies`도. 하나라도 어긋나면 닫힘 — 확인 뒤
  MCP 서버 이름·도구 매핑이 바뀌었거나 지문 없는 옛 기록도.
- `config.py set opencode.jira_read open`: 기록이 없거나 어긋나면 거부(runtime-check 명령 안내), OpenCode 안(`TT_RUNTIME=opencode`)이면
  거부, warn·skip 기록은 `--accept-error-bodies`가 있어야. closed는 늘 된다. doctor `jira_gate` 행(OpenCode 안에서만).
- 어댑터: 모델이 OpenCode 안에서 `config.py set opencode.*`를 돌리면 "직접 실행" 거부, 사용자 config·통과 기록 편집은 보호 경로,
  닫힌 관문은 Jira 읽기 거부·열린 관문(설정+기록, env 스위치 없음)은 guard로, 오류 글(`error` 모드)은 본문 숨김.
- 사내 확인 도우미(`tools/oc_jira_check.py`)의 순수 함수: 키 인자 고르기, 권한 마지막 규칙, 도구 이름 대응, 판정 행, 기록 지문 ==
  관문 쪽 지문.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "tools"))

from common import oc_adapter as oc  # noqa: E402
from common import oc_jira_gate as gate  # noqa: E402
from runner import run  # noqa: E402

JIRA = ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets", "mcp__mock-jira__jira_ticket_comments"]
SET_TRACKER = ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA[0], "--search-issues", JIRA[1],
               "--get-comments", JIRA[2]]
FINGERPRINT_CHANGED = "트래커·MCP 설정이 확인 뒤 바뀌었다"


def record(root: Path, *, passed=True, version=None, digest=None, error="pass", w=None, project=None) -> dict:
    """통과 기록. 트래커·MCP 지문은 그 시점 환경으로 계산한다(`gate.current_fingerprint`). `w`면 그 작업공간 스크립트가 보는
    환경 — 플러그인 `w.root`(site-defaults)·사용자 홈 `w.home`·설치 폴더 `project`(기본 `w.base`) — 에서 하위 프로세스로(이 테스트
    프로세스의 `common`은 다른 플러그인 루트일 수 있다)."""
    checks = [{"check": "success-isolation", "status": "pass" if passed else "fail", "detail": "x"}]
    if error:
        checks.append({"check": gate.ERROR_ROW, "status": error, "detail": "x"})
    rec = {"schema": gate.RECORD_SCHEMA, "at": "2026-11-05T10:00:00+09:00", "passed": passed,
           "opencode_version": version or oc.OPENCODE_VERSION, "jira_server": "mock-jira",
           "tools": ["mock-jira_jira_fetch_ticket"], "checks": checks,
           "scripts_sha": digest or gate.scripts_digest(root), "plugin_root": str(root)}
    if w is None:
        rec["tracker_fingerprint"] = gate.current_fingerprint(rec)
        return rec
    rec["project"] = str(project or w.base)
    rec["tracker_fingerprint"] = gate_fingerprint(w, rec)
    return rec


def gate_fingerprint(w, rec: dict) -> str:
    """관문 쪽 지문: 작업공간 스크립트처럼 플러그인 `w.root`·`w.env()`의 하위 프로세스에서 `gate.current_fingerprint(rec)`."""
    code = ("import json, sys; sys.path.insert(0, sys.argv[1]); from common import oc_jira_gate as g; "
            "print(g.current_fingerprint(json.loads(sys.argv[2])))")
    proc = subprocess.run([sys.executable, "-c", code, str(w.root / "scripts"), json.dumps(rec)], cwd=w.base,
                          env={**os.environ, **{k: str(v) for k, v in w.env().items()}}, capture_output=True, text=True,
                          check=False)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


_WS = None


def ws():
    global _WS
    if _WS is None:
        from workspace import Workspace
        _WS = Workspace()
        _WS.json("config.py", SET_TRACKER)
    return _WS


@pytest.fixture
def w():
    """공용 작업공간에서 관문 설정·통과 기록을 매번 지운다."""
    w = ws()
    (w.home / gate.RECORD_NAME).unlink(missing_ok=True)
    import yaml
    data = user_config(w)
    if data.pop("opencode", None) is not None:
        (w.home / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return w


def user_config(w) -> dict:
    import yaml
    return yaml.safe_load((w.home / "config.yaml").read_text(encoding="utf-8")) or {}


def write_record(w, rec: dict) -> None:
    (w.home / gate.RECORD_NAME).write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")


def cset(w, *args, env=None):
    return w.run("config.py", ["set", *args], env=env)


# -- 순수 관문 판정 ---------------------------------------------------------------------------------------------------


def test_state_requires_setting_record_version_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path))
    root = gate.PLUGIN_ROOT
    st = gate.state({})
    assert not st.open and st.setting == gate.CLOSED
    st = gate.state({"opencode": {"jira_read": "open"}})
    assert not st.open and st.problems == ["사내 확인 통과 기록이 없다"]
    gate.write_record(record(root))
    assert gate.state({"opencode": {"jira_read": "open"}}).open
    assert not gate.state({"opencode": {"jira_read": "closed"}}).open
    assert not gate.state({"opencode": {"jira_read": True}}).open                   # 문자열 open만
    gate.write_record(record(root, version="1.20.0"))
    assert any("OpenCode 버전" in p for p in gate.state({"opencode": {"jira_read": "open"}}).problems)
    gate.write_record(record(root, digest="0" * 64))
    assert any("지문" in p for p in gate.state({"opencode": {"jira_read": "open"}}).problems)
    gate.write_record(record(root, passed=False))
    assert any("통과하지 않았다" in p for p in gate.state({"opencode": {"jira_read": "open"}}).problems)
    for row in ("warn", "skip", None):
        gate.write_record(record(root, error=row))
        assert not gate.state({"opencode": {"jira_read": "open"}}).open, row
        assert gate.state({"opencode": {"jira_read": "open", "jira_read_accept_error_bodies": True}}).open, row
    (tmp_path / gate.RECORD_NAME).write_text("{not json", encoding="utf-8")
    st = gate.state({"opencode": {"jira_read": "open"}})
    assert not st.open and "읽지 못함" in st.problems[0]


def test_record_file_is_private_and_summaries_have_no_content(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path / "h"))
    path = gate.write_record(record(gate.PLUGIN_ROOT, error="warn"))
    assert path == tmp_path / "h" / gate.RECORD_NAME and (path.stat().st_mode & 0o777) == 0o600
    rec, err = gate.load_record()
    assert err is None and gate.error_row(rec) == "warn" and gate.needs_accept(rec)
    assert gate.short_summary(rec) == "확인 2026-11-05 10:00 통과, 오류 경로 warn" and len(gate.short_summary(rec)) < 60
    assert gate.short_summary(None) == "확인 기록 없음"
    assert "서버 mock-jira" in gate.summary(rec) and "error-path warn" in gate.summary(rec)


def test_scripts_digest_same_as_installer_and_wrapper():
    import gen_opencode
    from importlib.machinery import SourceFileLoader
    import importlib.util
    loader = SourceFileLoader("tt_oc_gate", str(REPO / "opencode" / "bin" / "tt-oc"))
    tt = importlib.util.module_from_spec(importlib.util.spec_from_loader("tt_oc_gate", loader))
    loader.exec_module(tt)
    root = REPO / "plugin"
    assert gate.scripts_digest(root) == gen_opencode.scripts_digest(root) == tt.scripts_digest(root)


def test_no_code_constant_gate_and_env_switch_still_opens():
    assert not hasattr(oc, "JIRA_READ_RELEASED")
    assert oc.jira_gate_state({oc.JIRA_GATE_ENV: "open"}).open
    assert oc.jira_gate_state({oc.JIRA_GATE_ENV: "open"}).setting == "env"


# -- config.py set / doctor --------------------------------------------------------------------------------------------


def test_config_set_open_needs_matching_record(w):
    r = cset(w, "opencode.jira_read", "open")
    assert r.returncode == 2 and "통과 기록이 없다" in r.stderr and "runtime-check opencode" in r.stderr
    write_record(w, record(w.root, w=w, version="9.9.9"))
    r = cset(w, "opencode.jira_read", "open")
    assert r.returncode == 2 and "OpenCode 버전" in r.stderr
    write_record(w, record(w.root, w=w, digest="f" * 64))
    assert cset(w, "opencode.jira_read", "open").returncode == 2
    write_record(w, record(w.root, w=w))
    r = cset(w, "opencode.jira_read", "open")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["value"] == "open" and out["accepted_error_bodies"] is False and "통과" in out["check"]
    assert user_config(w)["opencode"] == {"jira_read": "open"}
    assert cset(w, "opencode.jira_read", "closed").returncode == 0
    assert user_config(w)["opencode"] == {"jira_read": "closed"}


def test_config_set_warn_or_skip_record_needs_accept_flag(w):
    for row in ("warn", "skip"):
        write_record(w, record(w.root, w=w, error=row))
        r = cset(w, "opencode.jira_read", "open")
        assert r.returncode == 2 and "--accept-error-bodies" in r.stderr and f"행이 {row}" in r.stderr, r.stderr
        r = cset(w, "opencode.jira_read", "open", "--accept-error-bodies")
        assert r.returncode == 0, r.stderr
        assert user_config(w)["opencode"] == {"jira_read": "open", "jira_read_accept_error_bodies": True}
        assert cset(w, "opencode.jira_read", "closed").returncode == 0
        assert user_config(w)["opencode"] == {"jira_read": "closed"}                  # 받아들임도 함께 지운다


def test_config_set_refusals(w):
    write_record(w, record(w.root, w=w))
    r = cset(w, "opencode.jira_read", "open", env={"TT_RUNTIME": "opencode"})
    assert r.returncode == 2 and "OpenCode 안에서는 바꾸지 않는다" in r.stderr and "config.py set opencode.jira_read open" in r.stderr
    assert cset(w, "opencode.jira_read_accept_error_bodies", "true").returncode == 2
    assert cset(w, "opencode.other", "x").returncode == 2
    assert cset(w, "opencode.jira_read", "yes").returncode == 2
    assert cset(w, "opencode.jira_read", "closed", "--accept-error-bodies").returncode == 2
    assert cset(w, "logcat.year_source", "tracker", "--accept-error-bodies").returncode == 2
    assert cset(w, "--platform", "android", "opencode.jira_read", "closed").returncode == 2
    assert "opencode" not in user_config(w)


def _gate_row(w, env=None) -> dict:
    proc = w.run("config.py", ["doctor"], env={"TT_RUNTIME": "opencode", **(env or {})})
    return next(r for r in json.loads(proc.stdout)["rows"] if r["check"] == "jira_gate")


def test_doctor_jira_gate_row_open_closed_and_last_check(w):
    row = _gate_row(w)
    assert row["status"] == "warn" and row["detail"].startswith("닫힘(opencode.jira_read: closed)")
    assert "확인 기록 없음" in row["detail"] and "runtime-check opencode" in row["next"]
    write_record(w, record(w.root, w=w))
    assert cset(w, "opencode.jira_read", "open").returncode == 0
    row = _gate_row(w)
    assert row["status"] == "ok" and row["detail"] == "열림 — 확인 2026-11-05 10:00 통과, 오류 경로 pass", row
    write_record(w, record(w.root, w=w, digest="e" * 64))                         # 플러그인이 바뀌면 닫힌다
    row = _gate_row(w)
    assert row["status"] == "warn" and row["detail"].startswith("닫힘 — ") and "지문" in row["detail"]
    assert _gate_row(w, {oc.JIRA_GATE_ENV: "open"})["detail"].startswith("시험 열림")


# -- 어댑터: 관문·모델이 열지 못함·오류 글 --------------------------------------------------------------------------------


def adapter(w, mode: str, payload: dict, env: dict | None = None) -> dict:
    proc = run("common/oc_adapter.py", [mode], root=w.root, env={**w.env(), **(env or {})}, cwd=w.base,
               stdin=json.dumps(payload, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _jira_dir(w) -> Path:
    d = w.base / "ocproj"
    d.mkdir(exist_ok=True)
    (d / "opencode.json").write_text(json.dumps({"mcp": {"mock-jira": {"type": "local", "command": ["x"]}}}),
                                     encoding="utf-8")
    return d


def gate_out(w) -> dict:
    """tt-guard.js가 플러그인을 실을 때 하는 판정(`oc_adapter gate`)의 출력 `{open, problems}`."""
    proc = run("common/oc_adapter.py", ["gate"], root=w.root, env=w.env(), cwd=w.base, stdin="")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def gate_at_start(w) -> dict:
    """시작 때 판정(`gate_out`) → 이후 adapter 호출 환경(`JIRA_SESSION_ENV`)."""
    return {oc.JIRA_SESSION_ENV: "open" if gate_out(w)["open"] is True else "closed"}


def _opened(w, rec: dict) -> None:
    """통과 기록을 쓰고 사용자가 연 상태(시작 판정 열림)를 만든다."""
    write_record(w, rec)
    assert cset(w, "opencode.jira_read", "open").returncode == 0
    assert gate_out(w) == {"open": True, "problems": []}


def test_gate_closes_when_mcp_server_names_change(w):
    """F03: 확인 뒤 설치 폴더(기록의 project) opencode.json의 MCP 서버 이름이 바뀌면 닫힌다."""
    d = _jira_dir(w)
    _opened(w, record(w.root, w=w, project=d))
    try:
        (d / "opencode.json").write_text(json.dumps({"mcp": {"mock-jira2": {"type": "local", "command": ["x"]}}}),
                                         encoding="utf-8")
        out = gate_out(w)
        assert out["open"] is False and any(FINGERPRINT_CHANGED in p for p in out["problems"]), out
    finally:
        _jira_dir(w)
    assert gate_out(w)["open"] is True                                           # 되돌리면 다시 맞는다


@pytest.mark.parametrize("change", [
    ["--get-issue", "mcp__mock-jira__jira_fetch_other", "--search-issues", JIRA[1], "--get-comments", JIRA[2]],
    [*SET_TRACKER[3:], "--read-tools", "mcp__mock-jira__jira_other_read"],     # guard 규칙 2의 허용 목록만
], ids=["get_issue", "read_tools"])
def test_gate_closes_when_tracker_mapping_changes(w, change):
    """F03: 확인 뒤 `config.py set-tracker`로 도구 매핑(같은 서버, 다른 get_issue)이나 읽기 허용 목록(`tracker.read_tools`)만
    바꿔도 닫힌다."""
    _opened(w, record(w.root, w=w))
    try:
        w.json("config.py", ["set-tracker", "--server", "mock-jira", *change])
        out = gate_out(w)
        assert out["open"] is False and any(FINGERPRINT_CHANGED in p for p in out["problems"]), out
    finally:
        w.json("config.py", SET_TRACKER)
    assert gate_out(w)["open"] is True


def test_tracker_view_reads_mapping_shaped_read_tools_like_guard():
    """손으로 고친 매핑 꼴 `tracker.read_tools`: guard 규칙 2는 키를 허용 이름으로 읽으므로 지문 재료에도 그 이름이 든다."""
    base = {"tracker": {"mcp_server": "mock-jira", "tools": {"get_issue": JIRA[0]}, "read_tools": [JIRA[0]]}}
    edited = {"tracker": {**base["tracker"], "read_tools": {JIRA[0]: True, JIRA[1]: True}}}
    assert oc.tracker_view(base).read_tools == (JIRA[0],)
    assert oc.tracker_view(edited).read_tools == (JIRA[0], JIRA[1])


def test_gate_closes_for_old_record_without_fingerprint(w):
    """F03: 지문(`tracker_fingerprint`) 없는 옛 기록은 닫힘이고, 그 기록으로는 열 수 없다."""
    _opened(w, record(w.root, w=w))
    old = record(w.root, w=w)
    del old["tracker_fingerprint"]
    write_record(w, old)
    out = gate_out(w)
    assert out["open"] is False and out["problems"] == [f"{FINGERPRINT_CHANGED}(또는 지문 없는 옛 기록) — runtime-check "
                                                        "opencode --jira 재실행"], out
    r = cset(w, "opencode.jira_read", "open")
    assert r.returncode == 2 and "지문 없는 옛 기록" in r.stderr, r.stderr


def test_gate_opened_by_setting_and_record_without_env_switch(w):
    d = _jira_dir(w)
    payload = {"tool": "mock-jira_jira_fetch_ticket", "args": {"ticket": "MOCK-1001"}, "directory": str(d)}
    out = adapter(w, "before", payload, gate_at_start(w))
    assert out["decision"] == "deny" and "관문이 닫혀" in out["reason"]
    write_record(w, record(w.root, w=w))
    assert cset(w, "opencode.jira_read", "open").returncode == 0
    session = gate_at_start(w)
    assert session == {oc.JIRA_SESSION_ENV: "open"}
    assert adapter(w, "before", payload, session)["decision"] == "allow"
    note = {"tool": "mock-jira_jira_ticket_add_note", "args": {"ticket": "MOCK-1001", "text": "x"}, "directory": str(d)}
    assert "코멘트 게시는 OpenCode v1" in adapter(w, "before", note, session)["reason"]   # 열려도 코멘트는 늘 거부
    write_record(w, record(w.root, w=w, version="1.19.6"))
    out = adapter(w, "before", payload, gate_at_start(w))
    assert out["decision"] == "deny" and "OpenCode 버전" in out["reason"]


def test_gate_is_decided_at_start_not_from_files_written_in_session(w):
    """리뷰 P0: 관문을 세션 중 파일로 열지 않는다. 시작 때 닫힘이면 그 뒤 설정·기록이 열림이 돼도 닫힘(다시 시작 안내),
    시작 판정이 없으면(tt-guard.js 밖) 파일이 열림이어도 닫힘."""
    d = _jira_dir(w)
    payload = {"tool": "mock-jira_jira_fetch_ticket", "args": {"ticket": "MOCK-1001"}, "directory": str(d)}
    closed_at_start = gate_at_start(w)
    write_record(w, record(w.root, w=w))
    assert cset(w, "opencode.jira_read", "open").returncode == 0                  # 세션 중에 열림으로 바뀜
    out = adapter(w, "before", payload, closed_at_start)
    assert out["decision"] == "deny" and "다시 시작" in out["reason"], out
    out = adapter(w, "before", payload)                                          # 시작 판정 없음
    assert out["decision"] == "deny" and "시작 때의 관문 판정이 없다" in out["reason"], out
    assert adapter(w, "before", payload, {oc.JIRA_SESSION_ENV: "yes"})["decision"] == "deny"
    js = (REPO / "opencode" / "plugins" / "tt-guard.js").read_text(encoding="utf-8")
    assert f'const JIRA_SESSION_ENV = "{oc.JIRA_SESSION_ENV}"' in js and 'runAdapter("gate"' in js
    assert "env: adapterEnv()" in js and "env: process.env" not in js


def test_doctor_row_shows_session_gate_difference(w):
    write_record(w, record(w.root, w=w))
    assert cset(w, "opencode.jira_read", "open").returncode == 0
    row = _gate_row(w, {oc.JIRA_SESSION_ENV: "closed"})
    assert row["status"] == "warn" and row["detail"].startswith("이 세션은 닫힘") and "다시 시작" in row["next"]
    assert _gate_row(w, {oc.JIRA_SESSION_ENV: "open"})["status"] == "ok"
    assert cset(w, "opencode.jira_read", "closed").returncode == 0
    assert _gate_row(w, {oc.JIRA_SESSION_ENV: "open"})["detail"].startswith("이 세션은 열림")


def _forge_cmds(s: str, home: Path, base: Path, root: Path) -> list[tuple[str, str]]:
    """(명령, workdir): 플러그인 스크립트가 인자로 받은 경로에 쓰는 모든 꼴."""
    out = []
    targets = [home / "config.yaml", home / gate.RECORD_NAME, base / "opencode.json", base / ".opencode" / "x.json",
               root / "hooks" / "hooks.json", base / "AGENTS.md"]
    for t in targets:
        out += [(f"python3 {s}/mask_pii.py --events /tmp/a.json --out {t}", ""),
                (f"python3 {s}/mask_pii.py --events /tmp/a.json --out={t}", ""),
                (f"python3 {s}/parse_logcat.py bugreport /tmp/a.txt --out {t}", ""),
                (f"python3 {s}/mask_pii.py --events /tmp/a.json --out {t.name}", str(t.parent)),
                (f"cd {t.parent} && python3 {s}/mask_pii.py --events /tmp/a.json --out {t.name}", ""),
                (f"cd /nonexistent || cd {t.parent} ; python3 {s}/mask_pii.py --events a.json --out {t.name}", "")]
    out.append((f"python3 {s}/mask_pii.py --events /tmp/a.json -o{home / 'config.yaml'}", ""))
    return out


def test_script_args_cannot_target_protected_files(w):
    """리뷰 P0: `bash_allowlist`는 스크립트 경로만 보고 인자는 안 봤다 — `mask_pii --out`·`parse_logcat bugreport --out`으로 사용자
    config·통과 기록·opencode.json·.opencode/·hooks.json·AGENTS.md를 덮을 수 있었다."""
    s = f"{w.root}/scripts"
    (w.base / ".opencode").mkdir(exist_ok=True)
    for cmd, workdir in _forge_cmds(s, w.home, w.base, w.root):
        args = {"command": cmd, **({"workdir": workdir} if workdir else {})}
        out = adapter(w, "before", {"tool": "bash", "args": args, "directory": str(w.base)})
        assert out["decision"] == "deny" and "스크립트 인자" in out["reason"], (cmd, out)
    w.work.mkdir(parents=True, exist_ok=True)
    ok = f"python3 {s}/mask_pii.py --events {w.work}/a.json --out {w.work}/K-1/masked.json"
    out = adapter(w, "before", {"tool": "bash", "args": {"command": ok}, "directory": str(w.base)})
    assert out["decision"] == "allow", out
    out = adapter(w, "before", {"tool": "bash", "args": {"command": f"cd - && python3 {s}/config.py doctor"},
                                "directory": str(w.base)})
    assert out["decision"] == "deny" and "cd" in out["reason"]


def test_bash_allowlist_symlink_dotdot_physical_path(tmp_path):
    home = tmp_path / ".telephony-triage"
    (home / "sub").mkdir(parents=True)
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "lnk").symlink_to(home / "sub")
    env = {"HOME": str(tmp_path)}
    cmd = f"python3 {oc.SCRIPTS}/mask_pii.py --out lnk/../config.yaml"
    v = oc.bash_allowlist(cmd, str(tmp_path / "w"), str(tmp_path / "w"), env)
    assert v.deny and "사용자 설정" in v.deny
    assert oc.bash_allowlist(cmd.replace("config.yaml", "out.json"), str(tmp_path / "w"), str(tmp_path / "w"), env).deny is None


@pytest.mark.parametrize("command", [
    "python3 /p/scripts/config.py set opencode.jira_read open",
    "python3 /p/scripts/config.py set opencode.jira_read open --accept-error-bodies",
    "python3 /p/scripts/config.py set 'open''code.jira_read' open",
    "python3 /p/scripts/config.py set \"opencode\".jira_read open",
    "python3 /p/scripts/config.py --platform android set OPENCODE.jira_read open",
])
def test_model_config_set_opencode_is_run_yourself(command):
    assert oc.v1_write_flow(command).startswith("OpenCode 설정 변경")


@pytest.mark.parametrize("command", ["python3 /p/scripts/config.py set logcat.year_source tracker",
                                     "python3 /p/scripts/config.py doctor", "cat opencode.json",
                                     "python3 /p/scripts/config.py set-tracker --server opencode-x --get-issue y"])
def test_other_commands_not_config_flow(command):
    assert oc.v1_write_flow(command) is None


def test_before_denies_config_set_opencode_with_exact_command(w):
    cmd = f'python3 "{w.root}/scripts/config.py" set opencode.jira_read open'
    out = adapter(w, "before", {"tool": "bash", "args": {"command": cmd}, "directory": str(w.base)})
    assert out["decision"] == "deny" and out["reason"].endswith(oc.ASK_PREFIX + cmd) and "OpenCode 설정 변경" in out["reason"]


def test_user_config_and_record_are_protected_targets(tmp_path):
    env = {"TELEPHONY_TRIAGE_HOME": str(tmp_path / "tth"), "HOME": str(tmp_path)}
    (tmp_path / "tth" / "work").mkdir(parents=True)
    for name in ("config.yaml", "opencode-jira-check.json", "opencode-jira-check.json.tmp", "config.yaml.bak"):
        assert "사용자 설정" in oc.protected_target(str(tmp_path / "tth" / name), str(tmp_path), env), name
    assert oc.protected_target(str(tmp_path / "tth" / "work" / "K-1" / "notes.md"), str(tmp_path), env) is None
    assert oc.protected_target(str(tmp_path / "tth" / "work" / "config.yaml"), str(tmp_path), env) is None
    default = {"HOME": str(tmp_path)}                                          # 기본 위치 ~/.telephony-triage
    assert oc.protected_target(str(tmp_path / ".telephony-triage" / "config.yaml"), str(tmp_path), default)


@pytest.mark.parametrize("text, cls", [
    ('{"status": 404, "errorMessages": ["Issue X does not exist"]}', "4xx"),
    ("upstream HTTP 500 for X", "5xx"), ("HTTP/1.1 503 Service Unavailable", "5xx"),
    ("Issue does not exist or you do not have permission", "not-found"), ("request timed out", "timeout"),
    ("Unauthorized", "auth"), ("The user has specified a rule which prevents you from using this specific tool call",
                               "permission-denied"),
    ("imsi 450081234567890 at 2026-11-05 12:30", "error"),
])
def test_error_class_fixed_words_only(text, cls):
    assert oc.error_class(text) == cls
    assert oc.hidden_error("srv_get", text) == f"Jira 오류(본문 숨김): srv_get {cls}"


def test_error_mode_hides_jira_bodies_only(w):
    d = _jira_dir(w)
    (d / "opencode.json").write_text(json.dumps({"mcp": {"mock-jira": {}, "docs": {}}}), encoding="utf-8")
    body = '{"status": 404, "errorMessages": ["MOCK-9 없음 imsi 450081234567890 mock.person@corp.mock.invalid"]}'
    base = {"directory": str(d), "sessionID": "s", "callID": "c", "args": {"ticket": "MOCK-9"}}
    out = adapter(w, "error", {**base, "tool": "mock-jira_jira_fetch_ticket", "error": body, "allowed": True})
    assert out["replace"] == "Jira 오류(본문 숨김): mock-jira_jira_fetch_ticket 4xx"
    # before가 허용하지 않은 우리 거부 문구는 그대로(식별자만 가린다), 허용한 호출인데 MARK로 시작하면 숨긴다
    ours = "[telephony-triage] Jira MCP 도구(x)는 OpenCode Jira 읽기 관문이 닫혀 있어 쓰지 않는다"
    assert adapter(w, "error", {**base, "tool": "mock-jira_jira_fetch_ticket", "error": ours})["replace"] is None
    spoof = "[telephony-triage] imsi 450081234567890"
    red = adapter(w, "error", {**base, "tool": "mock-jira_jira_fetch_ticket", "error": spoof})["replace"]
    assert red and "450081234567890" not in red
    assert adapter(w, "error", {**base, "tool": "mock-jira_jira_fetch_ticket", "error": spoof,
                                "allowed": True})["replace"].startswith("Jira 오류(본문 숨김)")
    assert adapter(w, "error", {**base, "tool": "docs_search", "error": body, "allowed": True})["replace"] is None
    assert adapter(w, "error", {**base, "tool": "bash", "error": body})["replace"] is None
    assert adapter(w, "error", {**base, "tool": "nosrv_x", "error": body})["replace"].startswith("Jira 오류(본문 숨김)")
    proc = run("common/oc_adapter.py", ["error"], root=w.root, env=w.env(), stdin="[1]")
    assert json.loads(proc.stdout)["replace"].startswith("Jira 오류(본문 숨김)")      # 입력 오류: 숨김(닫힘)


def test_js_transform_hook_present_and_fail_closed():
    js = (REPO / "opencode" / "plugins" / "tt-guard.js").read_text(encoding="utf-8")
    assert '"experimental.chat.messages.transform"' in js and 'runAdapter("error"' in js
    assert f'const ERROR_HIDDEN = "{oc.JIRA_ERROR_HIDDEN}"' in js
    assert "allowedCalls.add(input.callID)" in js


# -- 사내 확인 도우미 순수 함수 ---------------------------------------------------------------------------------------------


def test_check_helper_pure_functions():
    import oc_jira_check as cj
    assert cj.key_arg({"properties": {"fields": {"type": "string"}, "issue_key": {"type": "string"}},
                       "required": ["issue_key"]}) == "issue_key"
    assert cj.key_arg({"properties": {"ticket": {"type": "string"}}}) == "ticket"
    assert cj.key_arg({"properties": {"issueIdOrKey": {"type": "string"}}}) == "issueIdOrKey"
    assert cj.key_arg({"properties": {"q": {"type": "string"}}, "required": ["q"]}) == "q"
    assert cj.key_arg({}) == "key"
    cfg = {"permission": {"*": "deny", "jira_*": "deny", "jira_get_issue": "allow", "bash": {"*": "deny"}}}
    assert cj.permission_action(cfg, "jira_get_issue") == "allow"
    assert cj.permission_action(cfg, "jira_get_comments") == "deny"
    assert cj.permission_action({"permission": {"jira_get_issue": "allow", "jira_*": "deny"}}, "jira_get_issue") == "deny"
    assert cj.permission_action({}, "x") == "allow"
    names, seg, problem = cj.oc_names({"get_issue": "mcp__jira.corp__get_issue", "get_comments": "mcp__jira_corp__cmts"},
                                      ["jira.corp"])
    assert (names, seg, problem) == ({"get_issue": "jira_corp_get_issue", "get_comments": "jira_corp_cmts"}, "jira_corp", None)
    assert "없다" in cj.oc_names({"get_issue": "mcp__a__x"}, ["b"])[2]
    assert "get_issue" in cj.oc_names({"get_comments": "mcp__a__x"}, ["a"])[2]
    assert "둘" in cj.oc_names({"get_issue": "mcp__a__x", "get_comments": "mcp__b__y"}, ["a", "b"])[2]


def test_check_helper_record_fingerprint_matches_gate(w):
    """F03: 사내 확인이 기록에 쓰는 지문(`record_fingerprint` — 설치 플러그인 `config.py show` + 설치 폴더 MCP 서버)이 관문 쪽
    `gate.current_fingerprint(기록)`(설치 플러그인 하위 프로세스, 다른 cwd)과 같다. opencode 없이."""
    import oc_jira_check as cj
    proj = _jira_dir(w)
    child = {**os.environ, **{k: str(v) for k, v in w.env().items()}, "TT_RUNTIME": "opencode"}
    names, segment, problem = cj.oc_names({"get_issue": JIRA[0], "get_comments": JIRA[2]}, oc.mcp_servers(str(proj))[0])
    assert problem is None, problem
    fp = cj.record_fingerprint(w.root, proj, child, segment, names)
    rec = {"jira_server": segment, "tools": list(dict.fromkeys(names.values())), "project": str(proj)}
    assert len(fp) == 12 and fp == gate_fingerprint(w, rec)
    assert fp != gate_fingerprint(w, {**rec, "tools": [names["get_issue"]]})          # 기록의 도구 이름도 지문에 든다


def test_check_helper_error_row_reports_kinds_not_text():
    import oc_jira_check as cj
    hidden = cj.error_row("Jira 오류(본문 숨김): s_get 4xx", {"status": "error"})
    assert hidden["status"] == "pass" and "본문 숨김" in hidden["detail"]
    assert cj.error_row("telephony-triage: Jira 응답에서 형식에 맞는 이슈 키를 찾지 못해", {})["status"] == "pass"
    leak = cj.error_row('{"error": "MOCK-9 imsi 450081234567890"}', {"status": "error"})
    assert leak["status"] == "warn" and "450081234567890" not in leak["detail"] and "MOCK-9" not in leak["detail"]
    assert "마스킹 안 된 식별자" in leak["detail"]
    assert cj.error_row(None, None)["status"] == "warn"
    assert "내용 숨김" in cj._first_line("raw body imsi 450081234567890") and "4500" not in cj._first_line("x 4500812345")


def test_check_run_session_matches_tt_oc_run_opencode(tmp_path, monkeypatch):
    """런타임 리뷰 2차 P1: tt-oc `run_opencode`의 반환 모양이 바뀌어도(f21af21에서 4 → 5) 사내 확인 실행이 깨지지 않는다.
    실제 opencode 없이: 실제 tt-oc 모듈로 JSON 한 줄을 내는 작은 명령을 돌리고, 바꿔 끼운 run_opencode로 시간 초과도 본다."""
    import oc_jira_check as cj
    import site_step

    tt = site_step._load_tt_oc()
    ev = {"type": "step_start", "sessionID": "ses_X", "part": {}}
    cmd = [sys.executable, "-c", f"print({json.dumps(json.dumps(ev))})"]
    events, code = cj.run_session(tt, cmd, tmp_path, dict(os.environ))
    assert events == [ev] and code == 0 and cj._session_ids(events) == ["ses_X"]
    seen = {}
    monkeypatch.setattr(tt, "run_opencode", lambda *a, **k: (seen.update(k), ([], [], None, "tail", True))[1])
    assert cj.run_session(tt, ["x"], tmp_path, {}) == ([], None)
    # 3차 R2-P3-3: 첫 응답 시한은 끈다 — 멈춤은 RUN_TIMEOUT 하나라 행의 "시간 초과(…초)"가 실제 멈춘 시한이다
    assert seen["first_timeout"] == 0 and seen["timeout"] == cj.RUN_TIMEOUT
