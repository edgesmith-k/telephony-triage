"""OpenCode e2e 공용: 1.19.5 찾기, 가짜 모델 서버, 격리된 `opencode run` (계획 I O9).

- 바이너리: `TT_OPENCODE_BIN` 또는 PATH의 `opencode`. 없거나 버전이 `OPENCODE_VERSION`과 다르면 e2e는 건너뛴다
  (`TT_OPENCODE_BIN`을 명시했는데 버전이 다르면 `test_version_pinned`만 실패한다).
- 네트워크를 쓰지 않는다: 모델은 127.0.0.1의 `fakes/fake_oai.py`, 환경은 `env -i`처럼 새로 만든다(프록시 변수 없음,
  HOME·XDG는 임시 폴더, `OPENCODE_DISABLE_MODELS_FETCH=1`·`OPENCODE_DISABLE_AUTOUPDATE=1`).
- 플러그인은 레포의 `opencode/plugins/tt-guard.js`를 opencode.json `plugin`의 `file://` 경로로 싣고, `TT_PLUGIN_ROOT`는
  테스트 헬퍼 플러그인 루트(임시 복사본)를 준다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FAKES = Path(__file__).resolve().parent / "fakes"
TT_GUARD_JS = REPO / "opencode" / "plugins" / "tt-guard.js"


def _oc_version() -> str:
    import importlib.util
    spec = importlib.util.spec_from_file_location("ocenv_oc_version", REPO / "plugin" / "scripts" / "common" / "oc_version.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.OPENCODE_VERSION


OPENCODE_VERSION = _oc_version()   # 고정 버전은 plugin/scripts/common/oc_version.py 한 곳
LOOPBACK = "127.0.0.1"   # fakes/fake_oai.py가 묶는 주소


def opencode_bin() -> str | None:
    explicit = os.environ.get("TT_OPENCODE_BIN")
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    return shutil.which("opencode")


def opencode_version(binary: str) -> str:
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, env=base_env(Path(os.environ.get("TMPDIR") or "/tmp")), check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.strip()


_CHECKED: dict[str, str] = {}


def require_opencode() -> str:
    binary = opencode_bin()
    if not binary:
        pytest.skip("opencode가 없다 (TT_OPENCODE_BIN 또는 PATH)")
    if binary not in _CHECKED:
        _CHECKED[binary] = opencode_version(binary)
    if _CHECKED[binary] != OPENCODE_VERSION:
        pytest.skip(f"opencode {_CHECKED[binary] or '?'} — e2e는 {OPENCODE_VERSION} 고정")
    return binary


def base_env(home: Path, extra: dict | None = None) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home), "TMPDIR": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local" / "share"),
        "XDG_CACHE_HOME": str(home / ".cache"), "XDG_STATE_HOME": str(home / ".local" / "state"),
        "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
        "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1", "LANG": "C.UTF-8",
    }
    for key in ("PYTHONUSERBASE", "GH_HOST"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    from runner import GIT_SAFE_ENV   # tt-oc로 시작한 것처럼(없으면 어댑터가 bash의 git·플러그인 스크립트를 거부한다)
    env.update(GIT_SAFE_ENV)
    env.update({k: str(v) for k, v in (extra or {}).items()})
    return env


def write_config(project: Path, port: int, model: str = "glm-fake", mcp: dict | None = None,
                 permission: dict | None = None, plugin: bool = True) -> Path:
    cfg = {
        "model": f"gw/{model}", "small_model": f"gw/{model}",
        "autoupdate": False, "share": "disabled", "snapshot": False,
        "provider": {"gw": {"npm": "@ai-sdk/openai-compatible", "name": "fake gateway",
                            "options": {"baseURL": f"http://{LOOPBACK}:{port}/v1", "apiKey": "dummy"},
                            "models": {model: {"name": model, "limit": {"context": 202000, "output": 16000}}}}},
        "permission": permission if permission is not None else {"edit": "allow", "bash": "allow",
                                                                 "external_directory": "allow"},
        "mcp": mcp or {},
    }
    if plugin:
        cfg["plugin"] = [TT_GUARD_JS.as_uri()]
    path = project / "opencode.json"
    path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return path


@dataclass
class OcRun:
    exit: int
    events: list = field(default_factory=list)
    stderr: str = ""
    guard_log: list = field(default_factory=list)
    requests: list = field(default_factory=list)
    data_home: Path | None = None

    def tool_parts(self, tool: str | None = None) -> list[dict]:
        parts = [e.get("part", {}) for e in self.events if e.get("type") == "tool_use"]
        return [p for p in parts if tool is None or p.get("tool") == tool]

    def tool_states(self, tool: str | None = None) -> list[dict]:
        return [p.get("state", {}) for p in self.tool_parts(tool)]

    def texts(self) -> str:
        return "\n".join(str(e.get("part", {}).get("text") or "") for e in self.events if e.get("type") == "text")

    def all_text(self) -> str:
        return json.dumps(self.events, ensure_ascii=False)


def mcp_local(*command) -> dict:
    return {"type": "local", "command": [str(c) for c in command], "enabled": True}


def run_opencode(project: Path, script: dict, *, home: Path, plugin_root: Path, model: str = "glm-fake",
                 mcp: dict | None = None, permission: dict | None = None, extra_env: dict | None = None,
                 prompt: str = "go", timeout: int = 90, plugin: bool = True) -> OcRun:
    binary = require_opencode()
    home.mkdir(parents=True, exist_ok=True)
    script_path, req_log, guard_log = home / "script.json", home / "requests.jsonl", home / "guard.log"
    script_path.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    server = subprocess.Popen([sys.executable, str(FAKES / "fake_oai.py"), str(script_path), str(req_log)],
                              stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    try:
        port = int(server.stdout.readline().strip())
        write_config(project, port, model, mcp, permission, plugin)
        env = base_env(home, {"TT_PLUGIN_ROOT": plugin_root, "TT_OC_GUARD_LOG": guard_log, "TT_PYTHON": sys.executable,
                              **(extra_env or {})})
        try:
            proc = subprocess.run([binary, "run", "--format", "json", prompt], cwd=project, env=env,
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            code, out, err = -1, exc.stdout or "", f"timeout\n{exc.stderr or ''}"
            out = out.decode() if isinstance(out, bytes) else out
    finally:
        server.kill()
        server.wait()
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            events.append({"type": "raw", "text": line})

    def jsonl(path: Path) -> list:
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()] \
            if path.is_file() else []

    return OcRun(code, events, err, jsonl(guard_log), jsonl(req_log), home / ".local" / "share" / "opencode")
