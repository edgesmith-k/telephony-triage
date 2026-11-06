"""common/claude_child.py — 계획 I C2i·C3i: 게이트웨이(사내 모델) 프로필 env 이어받기, 비용 미상(costBasis unknown),
읽기 전용 자식의 `--bare`와 인증 실패 시 자동 대체, 프로필 점검(`gateway_profile_check`).

유료 호출은 없다. 기본 테스트의 자식은 tmp_path에 쓴 가짜 claude(파이썬)다. 진짜 CLI + 가짜 Anthropic 서버(127.0.0.1)
테스트는 `TT_CLAUDE_FAKE_SERVER=1`일 때만 돈다(사내 PC의 관리 설정이 주소·키를 덮으면 진짜 모델로 갈 수 있어 기본으로 끈다).
result 모양은 CLI 2.1.318을 가짜 서버로 돌린 실제 출력(scratchpad planI/cc_gw/out-*.jsonl)에서 땄다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
from common import claude_child as cc

# CLI 2.1.318이 모르는 모델 ID(사내 게이트웨이 모델)에 낸 result(가짜 서버 실험 out-bash2.jsonl, 줄임)
GATEWAY_RESULT = {
    "type": "result", "subtype": "success", "is_error": False, "num_turns": 2, "duration_ms": 371, "result": "FAKE-OK",
    "total_cost_usd": 0.045288, "api_error_status": None,
    "usage": {"input_tokens": 11252, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 14},
    "modelUsage": {"glm-5.2": {"inputTokens": 11252, "outputTokens": 14, "cacheReadInputTokens": 0,
                               "cacheCreationInputTokens": 0, "webSearchRequests": 0, "costUSD": 0.045288,
                               "contextWindow": 200000, "maxOutputTokens": 32000, "canonicalModel": "glm-5.2",
                               "provider": "firstParty", "costBasis": "unknown"}}}
# `--bare`에 키가 없을 때(요청 없이 끝난다, 실험 bare_none)
NOT_LOGGED_IN = {"type": "result", "subtype": "success", "is_error": True, "num_turns": 1, "result":
                 "Not logged in · Please run /login", "total_cost_usd": 0, "api_error_status": None, "modelUsage": {}}
INIT = {"type": "system", "subtype": "init", "session_id": "s-1", "model": "glm-5.2", "tools": ["Read", "Glob", "Grep"],
        "mcp_servers": [], "plugins": [{"name": "cc-plugin-privacy", "path": "builtin",
                                        "source": "cc-plugin-privacy@builtin"}], "permissionMode": "default"}


def _settings(conf: Path, data: dict) -> None:
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "settings.json").write_text(json.dumps(data), encoding="utf-8")


# --- C2i: 게이트웨이 env 이어받기 ------------------------------------------------------------------------

def test_gateway_profile_env_is_carried_from_settings(tmp_path):
    conf = tmp_path / "conf"
    _settings(conf, {"apiKeyHelper": "/opt/helper", "env": {
        "ANTHROPIC_BASE_URL": "https://gw.invalid", "ANTHROPIC_AUTH_TOKEN": "tok-secret", "ANTHROPIC_MODEL": "glm-5.2",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1", "CLAUDE_CODE_EFFORT_LEVEL": "unset",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "CLAUDE_CODE_DISABLE_THINKING": "1",
        "CLAUDE_CODE_SUBAGENT_MODEL": "glm-5.2", "API_TIMEOUT_MS": "600000",
        "UNRELATED_SECRET": "x", "CLAUDE_CODE_ENABLE_TELEMETRY": "1"}})
    env, settings_json, _, keys = cc.prepare_env({"PATH": "/bin", "CLAUDE_CONFIG_DIR": str(conf),
                                                  "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000"})
    for k in ("CLAUDE_CODE_MAX_CONTEXT_TOKENS", "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "CLAUDE_CODE_EFFORT_LEVEL",
              "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_DISABLE_THINKING", "CLAUDE_CODE_SUBAGENT_MODEL",
              "API_TIMEOUT_MS", "ANTHROPIC_MODEL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        assert f"env.{k}" in keys and k in env, k
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "16000"      # settings.json이 프로세스 환경보다 앞선다(CLI와 같게)
    assert "UNRELATED_SECRET" not in env and "CLAUDE_CODE_ENABLE_TELEMETRY" not in env
    assert json.loads(settings_json)["apiKeyHelper"] == "/opt/helper" and "apiKeyHelper" in keys
    argv = cc.build_command(cc.CliInfo("claude", None, frozenset()), cc.ChildSpec("p", tmp_path), settings_json)
    joined = " ".join(argv)
    assert "tok-secret" not in joined and "gw.invalid" not in joined and "16000" not in joined


def test_gateway_profile_check_rows(tmp_path):
    conf = tmp_path / "conf"
    _settings(conf, {"env": {"ANTHROPIC_BASE_URL": "https://gw.invalid", "ANTHROPIC_AUTH_TOKEN": "tok-secret",
                             "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000"}})
    rows = {r["key"]: r for r in cc.gateway_profile_check({"CLAUDE_CONFIG_DIR": str(conf),
                                                          "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"})}
    assert rows["ANTHROPIC_BASE_URL"]["status"] == "ok" and "gw.invalid" not in rows["ANTHROPIC_BASE_URL"]["detail"]
    assert rows["credential"] == {"key": "credential", "status": "ok", "detail": "ANTHROPIC_AUTH_TOKEN"}
    assert rows["ANTHROPIC_MODEL"]["status"] == "info"
    assert rows["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]["status"] == "differs"
    assert rows["CLAUDE_CODE_MAX_CONTEXT_TOKENS"]["status"] == "ok"
    assert rows["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"]["status"] == "ok"      # 프로세스 환경도 본다
    assert rows["CLAUDE_CODE_EFFORT_LEVEL"]["status"] == "ok"           # 권장 unset: 변수 없음도 맞다(F)
    assert rows["CLAUDE_CODE_DISABLE_THINKING"]["status"] == "info"
    assert "tok-secret" not in json.dumps(list(rows.values()))
    empty = {r["key"]: r["status"] for r in cc.gateway_profile_check({"CLAUDE_CONFIG_DIR": str(tmp_path / "none")})}
    assert empty["ANTHROPIC_BASE_URL"] == "missing" and empty["credential"] == "missing"


def test_gateway_profile_unset_accepts_absent(tmp_path):
    """권장 값이 unset인 키(CLAUDE_CODE_EFFORT_LEVEL)는 변수 없음·빈 값·글자 그대로 unset이 ok, 다른 값은 differs.
    다른 키의 없음은 그대로 missing이다(O10 거짓 실패 고침, F)."""
    conf = str(tmp_path / "none")
    for env in ({}, {"CLAUDE_CODE_EFFORT_LEVEL": ""}, {"CLAUDE_CODE_EFFORT_LEVEL": "unset"}):
        rows = {r["key"]: r for r in cc.gateway_profile_check({"CLAUDE_CONFIG_DIR": conf, **env})}
        assert rows["CLAUDE_CODE_EFFORT_LEVEL"]["status"] == "ok", env
        assert rows["CLAUDE_CODE_MAX_OUTPUT_TOKENS"]["status"] == "missing"
    absent = {r["key"]: r for r in cc.gateway_profile_check({"CLAUDE_CONFIG_DIR": conf})}
    assert absent["CLAUDE_CODE_EFFORT_LEVEL"]["detail"] == "없음 (권장 unset — 두지 않아도 된다)"
    high = {r["key"]: r for r in cc.gateway_profile_check({"CLAUDE_CONFIG_DIR": conf, "CLAUDE_CODE_EFFORT_LEVEL": "high"})}
    assert high["CLAUDE_CODE_EFFORT_LEVEL"] == {"key": "CLAUDE_CODE_EFFORT_LEVEL", "status": "differs",
                                                "detail": "high (권장 unset)"}


def test_runtime_check_passes_without_effort_var(tmp_path):
    """`site_step.py runtime-check claude-gateway`: 권장 프로필에서 CLAUDE_CODE_EFFORT_LEVEL만 없으면 통과(종료 0)."""
    sys.path.insert(0, str(REPO / "tools"))
    import site_step

    conf = tmp_path / "conf"
    profile = {"ANTHROPIC_BASE_URL": "https://gw.invalid", "ANTHROPIC_AUTH_TOKEN": "tok-secret",
               "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000",
               "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    _settings(conf, {"env": profile})
    out, code = site_step.runtime_claude_gateway({"CLAUDE_CONFIG_DIR": str(conf)})
    assert code == 0, out
    assert "| CLAUDE_CODE_EFFORT_LEVEL | ok |" in out and "tok-secret" not in out


# --- C2i: 비용 미상 --------------------------------------------------------------------------------------

def test_cost_unknown_is_null_but_tokens_are_kept():
    assert cc.cost_basis(GATEWAY_RESULT) == "unknown" and cc.result_cost(GATEWAY_RESULT) is None
    t = cc.token_record(GATEWAY_RESULT)
    assert t["total_cost_usd"] is None and t["cost_basis"] == "unknown"
    assert t["total"] == 11266 and t["input"] == 11252 and t["output"] == 14
    assert t["by_model"]["glm-5.2"]["cost_usd"] is None and t["by_model"]["glm-5.2"]["cost_basis"] == "unknown"
    # 하나라도 unknown이면 전체가 미상(보조 모델이 Claude여도 합계는 자리 표시 단가를 섞는다)
    mixed = json.loads(json.dumps(GATEWAY_RESULT))
    mixed["modelUsage"]["claude-haiku"] = {"inputTokens": 1, "outputTokens": 1, "cacheReadInputTokens": 0,
                                           "cacheCreationInputTokens": 0, "costUSD": 0.001}
    assert cc.result_cost(mixed) is None and cc.token_record(mixed)["by_model"]["claude-haiku"]["cost_usd"] == 0.001


def test_cost_known_unchanged():
    known = json.loads(json.dumps(GATEWAY_RESULT))
    del known["modelUsage"]["glm-5.2"]["costBasis"]
    assert cc.cost_basis(known) is None and cc.result_cost(known) == 0.045288
    t = cc.token_record(known)
    assert t["total_cost_usd"] == 0.045288 and t["cost_basis"] is None and "cost_basis" not in t["by_model"]["glm-5.2"]
    known["modelUsage"]["glm-5.2"]["costBasis"] = "list"
    assert cc.cost_basis(known) == "list" and cc.result_cost(known) == 0.045288
    assert cc.cost_basis(None) is None and cc.result_cost(None) is None


# --- C3i: --bare ------------------------------------------------------------------------------------------

def test_build_command_bare_only_when_requested_and_supported():
    spec = cc.ChildSpec("p", Path("."), model="m", bare=True)
    with_flag = cc.build_command(cc.CliInfo("claude", None, frozenset({"--bare"})), spec, "{}")
    assert with_flag[-1] == "--bare"
    assert "--bare" not in cc.build_command(cc.CliInfo("claude", None, frozenset()), spec, "{}")
    assert "--bare" not in cc.build_command(cc.CliInfo("claude", None, frozenset({"--bare"})),
                                            cc.ChildSpec("p", Path(".")), "{}")


def test_bare_auth_failure_shapes():
    assert cc.bare_auth_failure([INIT], NOT_LOGGED_IN).startswith("Not logged in")
    assert cc.bare_auth_failure([INIT], {**NOT_LOGGED_IN, "result": "", "api_error_status": 401}) == "api_error_status 401"
    assert cc.bare_auth_failure([INIT], {**NOT_LOGGED_IN, "result": "overloaded"}) is None
    assert cc.bare_auth_failure([INIT], GATEWAY_RESULT) is None
    assert cc.bare_auth_failure([INIT], None) is None
    used_tool = [INIT, {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/x"}}]}}]
    assert cc.bare_auth_failure(used_tool, NOT_LOGGED_IN) is None      # 모델까지 갔으면 다시 돌리지 않는다


def _fake_claude(tmp: Path, bare_result: dict, flags=("--bare",)) -> Path:
    """--bare가 있으면 bare_result, 없으면 정상(비용 미상) stream을 내는 가짜 claude. argv를 FAKE_LOG에 남긴다."""
    path = tmp / "bin" / "claude"
    path.parent.mkdir(parents=True, exist_ok=True)
    good = [INIT, GATEWAY_RESULT]
    bad = [INIT, bare_result]
    help_text = "Usage: claude\n" + "\n".join(f"  {f}  x" for f in flags)
    path.write_text(f"""#!{sys.executable}
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--help"]:
    print({help_text!r}); sys.exit(0)
if args[:1] == ["--version"]:
    print("2.1.318 (Claude Code)"); sys.exit(0)
sys.stdin.read()
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\\n")
for ev in ({bad!r} if "--bare" in args else {good!r}):
    print(json.dumps(ev, ensure_ascii=False))
""", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "argv.log"))
    return tmp_path


def _argvs(tmp: Path) -> list[list[str]]:
    return [json.loads(x) for x in (tmp / "argv.log").read_text(encoding="utf-8").splitlines()]


def test_run_child_bare_falls_back_once_on_auth_failure(fake_env):
    cli = cc.detect_cli(str(_fake_claude(fake_env, NOT_LOGGED_IN)))
    assert "--bare" in cli.flags
    run_dir = fake_env / "run"
    res = cc.run_child(cc.ChildSpec("p", fake_env, model="glm-5.2", bare=True), run_dir, cli)
    argvs = _argvs(fake_env)
    assert len(argvs) == 2 and "--bare" in argvs[0] and "--bare" not in argvs[1]
    assert res.bare.startswith("fallback: Not logged in") and res.status == "completed"
    assert res.cost_usd is None and res.cost_basis == "unknown" and res.tokens["total"] == 11266
    assert (run_dir / "bare-attempt" / "events.jsonl").is_file() and (run_dir / "events.jsonl").is_file()
    assert "Not logged in" in (run_dir / "bare-attempt" / "events.jsonl").read_text(encoding="utf-8")


def test_run_child_bare_used_or_unsupported_or_off(fake_env):
    ok = cc.detect_cli(str(_fake_claude(fake_env, GATEWAY_RESULT)))
    res = cc.run_child(cc.ChildSpec("p", fake_env, bare=True), fake_env / "r1", ok)
    assert res.bare == "used" and len(_argvs(fake_env)) == 1 and not (fake_env / "r1" / "bare-attempt").exists()
    old = cc.detect_cli(str(_fake_claude(fake_env / "old", NOT_LOGGED_IN, flags=())))
    res = cc.run_child(cc.ChildSpec("p", fake_env, bare=True), fake_env / "r2", old)
    assert res.bare == "unsupported" and "--bare" not in _argvs(fake_env)[-1] and res.status == "completed"
    res = cc.run_child(cc.ChildSpec("p", fake_env), fake_env / "r3", ok)
    assert res.bare is None and "--bare" not in _argvs(fake_env)[-1]
    # 다른 오류(인증 아님)는 다시 돌리지 않는다
    other = cc.detect_cli(str(_fake_claude(fake_env / "other", {**NOT_LOGGED_IN, "result": "API Error: 500"})))
    n = len(_argvs(fake_env))
    res = cc.run_child(cc.ChildSpec("p", fake_env, bare=True), fake_env / "r4", other)
    assert res.bare == "used" and res.status == "error" and len(_argvs(fake_env)) == n + 1


# --- 선택: 진짜 CLI + 가짜 Anthropic 서버 -----------------------------------------------------------------

REAL = os.environ.get("TT_CLAUDE_FAKE_SERVER") == "1" and shutil.which("claude")


@pytest.fixture
def fake_server(tmp_path):
    port_file, log = tmp_path / "port", tmp_path / "req.jsonl"
    proc = subprocess.Popen([sys.executable, "-I", str(REPO / "tests" / "helpers" / "fake_anthropic.py"),
                             str(port_file), str(log)], env={**os.environ, "READFILE": str(tmp_path / "w" / "a.txt")})
    for _ in range(100):
        if port_file.is_file():
            break
        time.sleep(0.05)
    try:
        yield int(port_file.read_text(encoding="utf-8")), log
    finally:
        proc.kill()
        proc.wait()


def _isolate(monkeypatch, tmp_path, port, settings: dict) -> None:
    for k in list(os.environ):
        if k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "AWS_", "VERTEX_")) or k in ("CLAUDECODE",):
            monkeypatch.delenv(k, raising=False)
    conf = tmp_path / "home" / ".claude"
    _settings(conf, settings)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(conf))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")


@pytest.mark.skipif(not REAL, reason="TT_CLAUDE_FAKE_SERVER=1과 claude CLI가 있을 때만(가짜 서버, 비용 0)")
def test_real_cli_gateway_profile_bare_and_unknown_cost(tmp_path, monkeypatch, fake_server):
    port, log = fake_server
    work = tmp_path / "w"
    work.mkdir()
    (work / "a.txt").write_text("hi\n", encoding="utf-8")
    _isolate(monkeypatch, tmp_path, port, {"env": {"ANTHROPIC_AUTH_TOKEN": "tok-dummy",
                                                   "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000",
                                                   "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"}})
    cli = cc.detect_cli(shutil.which("claude"))
    res = cc.run_child(cc.ChildSpec("READTEST", work, model="internal-glm-test", timeout=90, bare=True),
                       tmp_path / "run", cli)
    reqs = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert res.status == "completed", res.reason
    assert res.bare == "used" and res.cost_usd is None and res.cost_basis == "unknown" and res.tokens["total"]
    assert reqs and all(r["max_tokens"] == 16000 and r["model"] == "internal-glm-test" for r in reqs)
    assert [c["tool"] for c in res.calls] == ["read"] and "env.CLAUDE_CODE_MAX_OUTPUT_TOKENS" in res.auth_keys


@pytest.mark.skipif(not REAL, reason="TT_CLAUDE_FAKE_SERVER=1과 claude CLI가 있을 때만(가짜 서버, 비용 0)")
def test_real_cli_bare_without_credentials_falls_back(tmp_path, monkeypatch, fake_server):
    port, log = fake_server
    work = tmp_path / "w"
    work.mkdir()
    _isolate(monkeypatch, tmp_path, port, {})
    cli = cc.detect_cli(shutil.which("claude"))
    res = cc.run_child(cc.ChildSpec("hello", work, model="internal-glm-test", timeout=90, bare=True),
                       tmp_path / "run", cli)
    assert res.bare.startswith("fallback: Not logged in")
    attempt = (tmp_path / "run" / "bare-attempt" / "events.jsonl").read_text(encoding="utf-8")
    assert "Not logged in" in attempt
    # 대체 실행(--bare 없음)은 환경에 따라 다른 인증 경로(원격 세션의 토큰 파일 등)로 가짜 서버에 갈 수 있다 — 그 결과는 묻지 않는다.
    # 가는 곳은 늘 가짜 서버다(ANTHROPIC_BASE_URL을 이 테스트가 정했다)
    for line in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
        assert json.loads(line)["path"].startswith("/v1/")


def test_gateway_site_rows_report_cli_hooks_and_s1_without_blocking(tmp_path, monkeypatch):
    """종합 리뷰 F: runtime-check claude-gateway가 환경 변수 비교만 하던 것에 토큰 0 행 3개(claude_cli·plugin_hooks·
    isolation_confirmed). 전부 ok·warn·info라 종료 코드는 그대로다."""
    sys.path.insert(0, str(REPO / "tools"))
    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    import site_step
    from runner import plugin_root
    home = tmp_path / "tt-home"
    home.mkdir()
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(home))
    bare = tmp_path / "bin"
    bare.mkdir()
    rows = {r["key"]: r for r in site_step.gateway_site_rows({"PATH": str(bare)})}
    assert rows["claude_cli"]["status"] == "warn" and "PATH에 claude 없음" in rows["claude_cli"]["detail"]
    assert rows["plugin_hooks"]["status"] == "warn" and "setup" in rows["plugin_hooks"]["detail"]
    assert rows["isolation_confirmed"]["status"] == "info"
    assert all(r["status"] not in site_step.RUNTIME_FAIL for r in rows.values())
    fake = bare / "claude"
    fake.write_text("#!/bin/sh\necho '9.9.9 (Claude Code)'\n", encoding="utf-8")
    fake.chmod(0o755)
    root = plugin_root()
    (home / "config.yaml").write_text(f"plugin:\n  scripts_path: {root / 'scripts'}\n", encoding="utf-8")
    rows = {r["key"]: r for r in site_step.gateway_site_rows({"PATH": str(bare), "HOME": str(tmp_path)})}
    assert rows["claude_cli"]["status"] == "ok" and rows["claude_cli"]["detail"].startswith("9.9.9")
    assert rows["plugin_hooks"]["status"] == "ok" and "PreToolUse" in rows["plugin_hooks"]["detail"] and "matcher 8개" in rows["plugin_hooks"]["detail"]
    out, code = site_step.runtime_claude_gateway({"CLAUDE_CONFIG_DIR": str(tmp_path / "none"), "PATH": str(bare)})
    assert code == 1 and "| claude_cli | ok |" in out and "재는 것:" in out and "안 재는 것:" in out
