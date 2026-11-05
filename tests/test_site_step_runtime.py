"""tools/site_step.py runtime-check (계획 I O10, docs/development/RUNTIMES.md §6): 모델·네트워크 호출 없이 환경만 본다.

- claude-gateway: `plugin/scripts/common/claude_child.py` `gateway_profile_check` 표 그대로, missing·differs가 있으면 종료 1.
- opencode: 버전(= tt-oc PINNED, 없으면 설치 안내), 설치한 opencode.json 필수 설정(snapshot:false 등, tt-oc `config_problems`),
  opencode가 있으면 tt-oc 사전 점검 전체, 관리 설정(`gen_opencode.managed_problems`). 가짜 opencode 바이너리만 쓴다.
- 두 대상 모두 사내 확인 0의 curl 명령을 **보이기만** 한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SITE_STEP = REPO / "tools" / "site_step.py"
sys.path.insert(0, str(REPO / "tools"))
import gen_opencode  # noqa: E402

PROFILE_OK = {"ANTHROPIC_BASE_URL": "https://gw.invalid", "ANTHROPIC_AUTH_TOKEN": "tok-secret",
              "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "16000", "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "202000",
              "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1", "CLAUDE_CODE_EFFORT_LEVEL": "unset",
              "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}

# 가짜 opencode: --version·debug config만(받은 인자를 기록한다 — run이 불리지 않는지 본다)
STUB = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["STUB_LOG"], "a").write(json.dumps(args) + "\n")
if args == ["--version"]:
    print(os.environ.get("STUB_VERSION", "1.19.5")); sys.exit(0)
if args[:2] == ["debug", "config"]:
    print(open(os.environ["STUB_CONFIG"]).read()); sys.exit(0)
sys.exit(9)
'''
CONFIG_OK = {"snapshot": False, "share": "disabled", "autoupdate": False,
             "permission": {"*": "deny", "task": "deny", "bash": {"*": "deny", "python3 *": "allow"}}}


def _base_env(tmp: Path) -> dict:
    """부모 환경의 게이트웨이·OpenCode 변수를 뺀다(결과가 개발 PC 설정에 따라 바뀌지 않게)."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ANTHROPIC_", "CLAUDE_CODE_", "OPENCODE_", "TT_OC", "TT_OPENCODE"))}
    (tmp / "home").mkdir(exist_ok=True)
    env.update(HOME=str(tmp / "home"), XDG_CONFIG_HOME=str(tmp / "home" / ".config"), CLAUDE_CONFIG_DIR=str(tmp / "conf"))
    return env


def run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SITE_STEP), "runtime-check", *args], capture_output=True, text=True,
                          encoding="utf-8", stdin=subprocess.DEVNULL, env=env, timeout=120, check=False)


def rows_of(out: str) -> dict[str, tuple[str, str]]:
    found = {}
    for line in out.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if line.startswith("| ") and len(cells) == 3 and cells[0] not in ("항목",):
            found[cells[0]] = (cells[1], cells[2])
    return found


def assert_check0_printed_only(out: str) -> None:
    assert "사내 확인 0" in out and 'curl -sS -N "$GW/v1/messages"' in out and '"stream":true' in out
    assert '"type":"tool_use"' in out and "이 도구는 실행하지 않는다" in out


# -- claude-gateway ----------------------------------------------------------------------------------------------------

def test_claude_gateway_profile_ok_and_missing(tmp_path):
    """표는 claude_child.gateway_profile_check 행 그대로, 비밀 값은 적지 않는다. missing·differs → 종료 1."""
    env = _base_env(tmp_path)
    conf = tmp_path / "conf"
    conf.mkdir()
    (conf / "settings.json").write_text(json.dumps({"env": PROFILE_OK}), encoding="utf-8")
    r = run(env, "claude-gateway")
    assert r.returncode == 0, r.stdout + r.stderr
    rows = rows_of(r.stdout)
    assert rows["ANTHROPIC_BASE_URL"][0] == "ok" and rows["credential"] == ("ok", "ANTHROPIC_AUTH_TOKEN")
    assert rows["CLAUDE_CODE_MAX_OUTPUT_TOKENS"][0] == "ok" and rows["ANTHROPIC_MODEL"][0] == "info"
    assert "결과: 통과" in r.stdout and "tok-secret" not in r.stdout and "gw.invalid" not in r.stdout
    assert_check0_printed_only(r.stdout)

    (conf / "settings.json").write_text(json.dumps({"env": {**PROFILE_OK, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000",
                                                            "ANTHROPIC_AUTH_TOKEN": None}}), encoding="utf-8")
    r = run(env, "claude-gateway")
    rows = rows_of(r.stdout)
    assert r.returncode == 1 and rows["CLAUDE_CODE_MAX_OUTPUT_TOKENS"][0] == "differs" and rows["credential"][0] == "missing"
    assert "결과: 실패 2행(credential, CLAUDE_CODE_MAX_OUTPUT_TOKENS)" in r.stdout


def test_runtime_check_usage_errors(tmp_path):
    env = _base_env(tmp_path)
    assert run(env).returncode == 2 and run(env, "glm").returncode == 2
    r = subprocess.run([sys.executable, str(SITE_STEP), "check", "--project", "/x"], capture_output=True, text=True,
                       env=env, stdin=subprocess.DEVNULL, check=False)
    assert r.returncode == 2 and "--project는 runtime-check에서만" in r.stderr


# -- opencode ----------------------------------------------------------------------------------------------------------

@pytest.fixture
def oc(tmp_path):
    for d in (tmp_path, *tmp_path.parents):
        if (d / ".git").exists():
            pytest.skip(f"임시 폴더가 git 레포 안이다: {d}")
    plug, work, proj, managed = tmp_path / "plug", tmp_path / "work", tmp_path / "proj", tmp_path / "managed"
    (plug / "scripts").mkdir(parents=True)
    (plug / "scripts" / "config.py").write_text(
        "import json, sys\nif sys.argv[1:2] == ['check']:\n    print(json.dumps({'read_roots': []})); sys.exit(0)\n"
        "print(json.dumps({'counts': {'ok': 13}, 'rows': []}))\n", encoding="utf-8")
    for d in (work, managed, proj / ".opencode" / "plugins"):
        d.mkdir(parents=True)
    (proj / "opencode.json").write_text(json.dumps(CONFIG_OK), encoding="utf-8")
    (proj / ".opencode" / "plugins" / "tt-guard.js").write_text("// guard\n", encoding="utf-8")
    files = {rel: gen_opencode.hashlib.sha256((proj / rel).read_bytes()).hexdigest()
             for rel in ("opencode.json", ".opencode/plugins/tt-guard.js")}
    (proj / "tt-oc.json").write_text(json.dumps({
        "version": 1, "plugin_root": str(plug), "work_root": str(work), "model": "glm-x",
        "integrity": {"files": files, "plugin_scripts": gen_opencode.scripts_digest(plug)}}), encoding="utf-8")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    stub = bin_ / "opencode"
    stub.write_text(STUB.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1), encoding="utf-8")
    stub.chmod(0o755)
    cfg = tmp_path / "debug-config.json"
    cfg.write_text(json.dumps(CONFIG_OK), encoding="utf-8")
    env = _base_env(tmp_path)
    env.update(PATH=f"{bin_}{os.pathsep}{env['PATH']}", STUB_LOG=str(tmp_path / "log.jsonl"), STUB_CONFIG=str(cfg))
    return {"tmp": tmp_path, "proj": proj, "managed": managed, "env": env, "cfg": cfg}


def oc_run(o, *extra, env=None):
    return run({**o["env"], **(env or {})}, "opencode", "--managed-dir", str(o["managed"]), *extra)


def stub_calls(o) -> list[list[str]]:
    p = o["tmp"] / "log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_opencode_absent_gives_install_hint(oc):
    r = oc_run(oc, env={"PATH": "/nonexistent-bin", "TT_OPENCODE": "opencode"})
    rows = rows_of(r.stdout)
    assert r.returncode == 1
    assert rows["opencode-version"][0] == "fail" and "npm install -g opencode-ai" + "@" + gen_opencode.OPENCODE_VERSION in rows["opencode-version"][1]
    assert rows["project"][0] == "fail" and "gen_opencode.py install" in rows["project"][1]
    assert rows["managed-config"][0] == "warn"           # 관리 설정은 권장(다중 방어) — 없으면 막지 않는다
    assert_check0_printed_only(r.stdout)


def test_opencode_all_ok_with_project_and_managed(oc):
    (oc["managed"] / "opencode.json").write_text(gen_opencode.MANAGED_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    r = oc_run(oc, "--project", str(oc["proj"]))
    assert r.returncode == 0, r.stdout + r.stderr
    rows = rows_of(r.stdout)
    for check in ("installed-config", "env", "project-git", "integrity", "opencode-version", "opencode-config",
                  "config-doctor", "managed-config"):
        assert rows[check][0] == "ok", (check, rows.get(check))
    assert "결과: 통과" in r.stdout
    assert ["run"] not in [c[:1] for c in stub_calls(oc)], "모델 호출(opencode run)은 하지 않는다"
    assert_check0_printed_only(r.stdout)
    # TT_OC_PROJECT도 받는다(tt-oc와 같다)
    assert oc_run(oc, env={"TT_OC_PROJECT": str(oc["proj"])}).returncode == 0


def test_opencode_version_installed_config_and_managed_failures(oc):
    proj = ["--project", str(oc["proj"])]
    r = oc_run(oc, *proj, env={"STUB_VERSION": "1.20.0"})
    assert r.returncode == 1 and rows_of(r.stdout)["opencode-version"][0] == "fail" and "버전 불일치" in r.stdout
    (oc["proj"] / "opencode.json").write_text(json.dumps({**CONFIG_OK, "snapshot": True}), encoding="utf-8")
    r = oc_run(oc, *proj)
    rows = rows_of(r.stdout)
    assert r.returncode == 1 and rows["installed-config"][0] == "fail" and "snapshot=true" in rows["installed-config"][1]
    # 관리 설정: 예시의 deny 하나가 빠지면 fail(사내가 더 막는 것은 괜찮다)
    managed = json.loads(gen_opencode.MANAGED_SAMPLE.read_text(encoding="utf-8"))
    del managed["permission"]["bash"]["gh *"]
    managed["permission"]["extra_tool"] = "deny"
    (oc["managed"] / "opencode.json").write_text(json.dumps(managed), encoding="utf-8")
    r = oc_run(oc)
    assert rows_of(r.stdout)["managed-config"][0] == "fail" and "'gh *'" in r.stdout
    assert rows_of(r.stdout)["opencode-version"][0] == "ok"      # 프로젝트 없이도 버전은 본다(tt-oc version_row)
