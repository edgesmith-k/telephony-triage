"""`opencode/plugins/tt-guard.js` 닫힘 실패 (계획 I O2a) — node만 있으면 돈다(opencode 불필요, 없으면 건너뜀).

가짜 플러그인 루트의 `scripts/common/oc_adapter.py`를 스텁으로 바꿔 플러그인 hook을 node에서 직접 부른다(계획 I shim harness).
시제품의 결함(죽은 guard → 허용)을 막는지, 시간 초과·종료 코드≠0·JSON 아님·모르는 결정이 모두 거부인지, after 실패가 오류 문구로
대체되는지, 경고가 세션마다 한 번만 막는지, `shell.env`가 런타임 표식을 넣는지 본다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLUGIN = REPO / "opencode" / "plugins" / "tt-guard.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node가 없다")

STUB = r'''
import json, os, signal, sys, time
mode, stub = sys.argv[1], os.environ.get("STUB", "allow")
data = sys.stdin.read()
if mode == "gate":       # 플러그인을 실을 때 한 번(Jira 읽기 관문): STUB_GATE=open|kill|… (기본 닫힘), 호출 기록에는 안 남긴다
    gate = os.environ.get("STUB_GATE", "closed")
    if gate == "kill":
        os.kill(os.getpid(), signal.SIGKILL)
    print(json.dumps({"open": gate == "open", "problems": []}) if gate != "garbage" else "not json")
    sys.exit(0)
with open(os.environ["STUB_LOG"] + ".gate", "a", encoding="utf-8") as fh:   # adapter가 받은 관문 판정값
    fh.write(os.environ.get("TT_OC_JIRA_SESSION_GATE", "<none>") + "\n")
with open(os.environ["STUB_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"mode": mode, "payload": json.loads(data)}) + "\n")
if stub == "kill":
    os.kill(os.getpid(), signal.SIGKILL)
if stub == "exit1":
    sys.exit(1)
if stub == "garbage":
    print("not json")
elif stub == "sleep":
    time.sleep(10)
elif stub == "empty":
    pass
elif stub == "allow_exit1":
    print(json.dumps({"decision": "allow", "warnings": []}))
    sys.exit(1)
elif stub == "allow":
    print(json.dumps({"decision": "allow", "warnings": []} if mode == "before" else {"replace": None}))
elif stub == "warn":
    print(json.dumps({"decision": "allow", "warnings": ["W-ONE"]}))
elif stub == "deny":
    print(json.dumps({"decision": "deny", "reason": "R-DENY"}))
elif stub == "maybe":
    print(json.dumps({"decision": "maybe"}))
elif stub == "replace":
    print(json.dumps({"replace": "MASKED"}))
elif stub == "badreplace":
    print(json.dumps({"replace": 5}))
'''

HARNESS = r'''
import { pathToFileURL } from "node:url"
const [plugin, casesJson] = process.argv.slice(2)
const cases = JSON.parse(casesJson)
const mod = await import(pathToFileURL(plugin).href)
let hooks = null
const out = []
for (const c of cases) {
  if (!hooks || !c.same) hooks = await mod.TtGuard({ directory: "/proj" })
  process.env.STUB = c.stub || "allow"
  if (c.timeout) process.env.TT_OC_TEST_TIMEOUT_MS = String(c.timeout); else delete process.env.TT_OC_TEST_TIMEOUT_MS
  const input = { tool: c.tool, sessionID: c.session || "s1", callID: c.call || "c1" }
  try {
    if (c.hook === "after") {
      const output = { content: [{ type: "text", text: "RAW imsi=450081234567890" }] }
      await hooks["tool.execute.after"](input, output)
      out.push({ result: "AFTER", content: output.content })
    } else if (c.hook === "env") {
      const output = { env: {} }
      await hooks["shell.env"]({ cwd: "/proj" }, output)
      out.push({ result: "ENV", env: output.env })
    } else {
      await hooks["tool.execute.before"](input, { args: c.args || { command: "git push" } })
      out.push({ result: "ALLOWED" })
    }
  } catch (e) {
    out.push({ result: "THROW", message: String(e.message) })
  }
}
console.log(JSON.stringify(out))
'''


def _root(base: Path) -> Path:
    root = base / "plugin"
    (root / "scripts" / "common").mkdir(parents=True)
    (root / "scripts" / "common" / "oc_adapter.py").write_text(STUB, encoding="utf-8")
    return root


def harness(cases: list[dict], root: Path | None = None, base: Path | None = None, plugin: Path = PLUGIN,
            root_env: bool = True, extra_env: dict | None = None) -> tuple[list[dict], list[dict]]:
    base = base or Path(tempfile.mkdtemp(prefix="tt-ocjs-"))
    try:
        root = root or _root(base)
        script = base / "h.mjs"
        script.write_text(HARNESS, encoding="utf-8")
        log = base / "stub.log"
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(base),
               "TT_PYTHON": sys.executable, "STUB_LOG": str(log), "TT_OC_GUARD_LOG": str(base / "guard.log")}
        if root_env:
            env["TT_PLUGIN_ROOT"] = str(root)
        env.update(extra_env or {})
        proc = subprocess.run([NODE, str(script), str(plugin), json.dumps(cases)], capture_output=True, text=True,
                              env=env, timeout=120, check=False)
        assert proc.returncode == 0, proc.stderr
        calls = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
        guard_log = (base / "guard.log").read_text(encoding="utf-8") if (base / "guard.log").is_file() else ""
        gates = Path(str(log) + ".gate")
        seen = gates.read_text(encoding="utf-8").split() if gates.is_file() else []
        return json.loads(proc.stdout), calls + [{"guard_log": guard_log, "gate_env": seen}]
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.mark.parametrize("stub,timeout", [("kill", None), ("exit1", None), ("garbage", None), ("empty", None),
                                          ("allow_exit1", None), ("deny", None), ("maybe", None), ("sleep", 800)])
@pytest.mark.parametrize("tool", ["bash", "apply_patch", "corp_jira_update_issue"])
def test_before_fails_closed(stub, timeout, tool):
    (got,), _ = harness([{"stub": stub, "tool": tool, "timeout": timeout}])
    assert got["result"] == "THROW", (stub, tool, got)
    if stub == "deny":
        assert got["message"] == "[telephony-triage] R-DENY"     # tt-oc가 막힘으로 알아보는 표시(리뷰 P1)
    else:
        assert got["message"].startswith("[telephony-triage] ")


def test_before_allow_passes_payload_shape():
    (got,), calls = harness([{"stub": "allow", "tool": "bash", "args": {"command": "ls", "workdir": "sub"},
                              "session": "S9", "call": "C9"}])
    assert got["result"] == "ALLOWED"
    assert calls[0] == {"mode": "before", "payload": {"tool": "bash", "args": {"command": "ls", "workdir": "sub"},
                                                      "directory": "/proj", "sessionID": "S9", "callID": "C9"}}
    assert '"decision":"allow"' in calls[-1]["guard_log"]


def test_warning_blocks_once_per_session():
    got, _ = harness([{"stub": "warn", "tool": "bash", "session": "A"}, {"stub": "warn", "tool": "bash", "session": "A", "same": True},
                      {"stub": "warn", "tool": "bash", "session": "B", "same": True}])
    assert [g["result"] for g in got] == ["THROW", "ALLOWED", "THROW"]
    assert "W-ONE" in got[0]["message"]


@pytest.mark.parametrize("stub,want", [("allow", "RAW imsi=450081234567890"), ("replace", "MASKED"),
                                       ("kill", "jira_bridge 처리 실패"), ("exit1", "jira_bridge 처리 실패"),
                                       ("garbage", "jira_bridge 처리 실패"), ("empty", "jira_bridge 처리 실패"),
                                       ("badreplace", "jira_bridge 처리 실패")])
def test_after_replaces_or_fails_closed(stub, want):
    (got,), calls = harness([{"stub": stub, "tool": "mock-jira_jira_fetch_ticket", "hook": "after"}])
    assert got["result"] == "AFTER" and want in got["content"][0]["text"], got
    assert calls[0]["payload"]["content"] == [{"type": "text", "text": "RAW imsi=450081234567890"}]


def test_after_timeout_and_builtin_skip():
    (got,), _ = harness([{"stub": "sleep", "timeout": 800, "tool": "x_y", "hook": "after"}])
    assert "jira_bridge 처리 실패" in got["content"][0]["text"]
    (got,), calls = harness([{"stub": "garbage", "tool": "bash", "hook": "after"}])
    assert got["content"][0]["text"].startswith("RAW") and len(calls) == 1 and calls[0]["gate_env"] == []  # 내장 도구는 부르지 않는다
    assert '"hook":"after"' not in calls[0]["guard_log"]


def test_after_uses_args_seen_before():
    _got, calls = harness([{"stub": "allow", "tool": "srv_t", "args": {"key": "K-1"}, "call": "C1"},
                           {"stub": "allow", "tool": "srv_t", "hook": "after", "call": "C1", "same": True}])
    assert calls[1]["mode"] == "after" and calls[1]["payload"]["args"] == {"key": "K-1"}


def test_missing_adapter_denies_everything():
    base = Path(tempfile.mkdtemp(prefix="tt-ocjs-"))
    got, _ = harness([{"tool": "read"}, {"tool": "x_y", "hook": "after", "same": True}], root=base / "nowhere", base=base)
    assert got[0]["result"] == "THROW" and "not found" in got[0]["message"]
    assert "jira_bridge 처리 실패" in got[1]["content"][0]["text"]


def test_installed_copy_uses_written_plugin_root():
    """`gen_opencode.py install`이 <dest>/.opencode/plugins/에 복사하며 `@@PLUGIN_ROOT@@`를 바꾸면 TT_PLUGIN_ROOT 없이도
    그 루트의 어댑터를 부른다(TUI처럼 tt-oc를 거치지 않는 실행). 바꾸지 않은 레포 사본은 ../../plugin으로 간다."""
    base = Path(tempfile.mkdtemp(prefix="tt-ocjs-"))
    root = _root(base)
    inst = base / "dest" / ".opencode" / "plugins" / "tt-guard.js"
    inst.parent.mkdir(parents=True)
    text = PLUGIN.read_text(encoding="utf-8")
    assert text.count("@@PLUGIN_ROOT@@") == 1
    inst.write_text(text.replace("@@PLUGIN_ROOT@@", str(root)), encoding="utf-8")
    (got,), calls = harness([{"stub": "allow", "tool": "bash"}], root=root, base=base, plugin=inst, root_env=False)
    assert got["result"] == "ALLOWED" and calls[0]["mode"] == "before"
    # 자리 표시를 그대로 둔 사본은 <파일>/../../plugin(여기서는 없는 경로) → 어댑터가 없어 거부
    base2 = Path(tempfile.mkdtemp(prefix="tt-ocjs-"))
    raw = base2 / "dest" / ".opencode" / "plugins" / "tt-guard.js"
    raw.parent.mkdir(parents=True)
    raw.write_text(text, encoding="utf-8")
    (got,), _ = harness([{"stub": "allow", "tool": "bash"}], base=base2, plugin=raw, root_env=False)
    assert got["result"] == "THROW"


def test_shell_env_marks_runtime():
    (got,), _ = harness([{"hook": "env"}])
    assert got["env"]["TT_RUNTIME"] == "opencode" and got["env"]["CLAUDE_PLUGIN_ROOT"].endswith("plugin")
    # 리뷰 9 R2: tt-oc가 준 GIT_CONFIG_*는 bash 자식에 그대로 다시 넣고, `git -c` 값(GIT_CONFIG_PARAMETERS)은 빈 값으로 덮는다
    git = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "safe.bareRepository", "GIT_CONFIG_VALUE_0": "explicit",
           "GIT_CONFIG_KEY_1": "protocol.ext.allow", "GIT_CONFIG_VALUE_1": "never"}
    (got,), _ = harness([{"hook": "env"}], extra_env={**git, "GIT_CONFIG_PARAMETERS": "'safe.bareRepository'='all'"})
    assert {k: got["env"].get(k) for k in git} == git and got["env"]["GIT_CONFIG_PARAMETERS"] == ""
    assert "GIT_ALLOW_PROTOCOL" not in got["env"]


def test_plugin_uses_node_imports_only():
    text = PLUGIN.read_text(encoding="utf-8")
    imports = [ln for ln in text.splitlines() if ln.startswith("import ")]
    assert imports and all('from "node:' in ln for ln in imports), imports
    assert not (REPO / "opencode" / "package.json").exists() and not (REPO / "opencode" / "plugins" / "package.json").exists()


@pytest.mark.parametrize("gate,want", [("open", "open"), ("closed", "closed"), ("kill", "closed"), ("garbage", "closed")])
def test_jira_gate_decided_once_at_load_and_passed_to_every_adapter_call(gate, want):
    """리뷰 P0: 관문은 플러그인을 실을 때 한 번 정하고(`gate`), 이후 adapter 호출 환경에 넣는다. 실패는 닫힘. 바깥 환경의 같은
    이름 변수는 덮인다(모델·사용자 env로 세션 판정을 바꾸지 못한다)."""
    got, calls = harness([{"stub": "allow", "tool": "bash"}, {"stub": "allow", "tool": "bash", "same": True},
                          {"hook": "env", "same": True}],
                         extra_env={"STUB_GATE": gate, "TT_OC_JIRA_SESSION_GATE": "open" if want == "closed" else "x"})
    assert [g["result"] for g in got] == ["ALLOWED", "ALLOWED", "ENV"]
    assert calls[-1]["gate_env"] == [want, want]
    assert got[2]["env"]["TT_OC_JIRA_SESSION_GATE"] == want
    assert f'"jira":"{want}"' in calls[-1]["guard_log"]
