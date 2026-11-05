"""OpenCode Jira 읽기 관문 e2e(실제 opencode 1.19.5 + 가짜 모델 127.0.0.1 + 가짜 stdio Jira MCP, 비용 0).
opencode 1.19.5가 없으면 건너뛴다(`ocenv.require_opencode`).

- 오류 경로: MCP `isError`·JSON-RPC 오류 응답의 본문(원문 식별자)이 모델에 가지 않는다 — tt-guard.js
  `experimental.chat.messages.transform`이 "Jira 오류(본문 숨김): <도구> <분류>"로 바꾼다(1.19.5는 오류에 after hook을 안 돌린다).
- 사내 확인: `site_step.py runtime-check opencode --project <설치 폴더> --jira <있는 키> --missing-key <없는 키>`가 통과하고 통과
  기록을 쓰며 여는 명령을 보인다(열지는 않는다). 그 뒤 사용자가 `config.py set opencode.jira_read open`으로 열면(테스트 env 스위치
  없이) 설치 설정 그대로의 실제 opencode에서 Jira 읽기가 마스킹 요약으로 된다. 확인 기록이 없으면 열 수 없다.
- 모델은 열 수 없다(배포 템플릿 권한 그대로도: 플러그인 스크립트 `--out`으로 위조 기록·설정 쓰기 거부 — 리뷰 P0 회귀):
  OpenCode 안의 bash `config.py set opencode.jira_read open`은 "직접 실행" 거부, 사용자 config·통과 기록 편집은
  보호 경로 거부, 설정 파일은 그대로.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(HERE))

import ocenv
from common import oc_adapter as oc
from runner import tmp

IMSI, PHONE, MAIL = "450081234567890", "010-1234-5678", "mock.person@corp.mock.invalid"
SERVER = "corp-jira"
GET, COMMENTS = f"mcp__{SERVER}__get_issue", f"mcp__{SERVER}__get_comments"
OC_GET, OC_COMMENTS, OC_ADD = f"{SERVER}_get_issue", f"{SERVER}_get_comments", f"{SERVER}_add_comment"
FAKE_JIRA = HERE / "fakes" / "fake_jira_mcp.py"
SECRETS = (IMSI, PHONE, MAIL)

pytestmark = pytest.mark.usefixtures("needs_opencode")


@pytest.fixture
def needs_opencode():
    ocenv.require_opencode()


def workspace():
    from workspace import Workspace
    w = Workspace()
    w.json("config.py", ["set-tracker", "--server", SERVER, "--get-issue", GET, "--get-comments", COMMENTS])
    return w


def mcp(log: Path) -> dict:
    return {SERVER: ocenv.mcp_local(sys.executable, FAKE_JIRA, log)}


def seen(r: ocenv.OcRun) -> list[str]:
    return [t for q in r.requests for t in q["tool_results"]]


def leaks(texts) -> list[str]:
    return [s for s in SECRETS for t in texts if s in t]


def test_error_bodies_hidden_from_model_iserror_and_jsonrpc():
    w = workspace()
    proj = tmp("tt-ocj-err-") / "proj"
    proj.mkdir()
    log = proj.parent / "jira-calls.jsonl"
    steps = [{"tool": OC_GET, "args": {"issue_key": "MOCK-2999"}},          # MCP isError(404 본문)
             {"tool": OC_GET, "args": {"issue_key": "RPCERR-1"}},           # JSON-RPC 오류(500 message)
             {"tool": OC_COMMENTS, "args": {"issue_key": "MOCK-2001"}},      # 성공: jira_bridge 마스킹 요약
             {"text": "FINAL"}]
    r = ocenv.run_opencode(proj, {"main": steps, "child": [{"text": "C"}]}, home=proj.parent / "home",
                           plugin_root=w.root, mcp=mcp(log), extra_env={**w.env(), oc.JIRA_GATE_ENV: "open"})
    states = r.tool_states()
    assert [s.get("status") for s in states] == ["error", "error", "completed"], r.events
    assert len(log.read_text(encoding="utf-8").splitlines()) == 3            # 셋 다 서버까지 갔다(관문 열림)
    texts = seen(r)
    assert f"{oc.JIRA_ERROR_HIDDEN}: {OC_GET} 4xx" in texts, texts
    assert f"{oc.JIRA_ERROR_HIDDEN}: {OC_GET} 5xx" in texts, texts
    assert any(t.startswith("telephony-triage: Jira 응답 원문은 파일로만") for t in texts), texts
    assert leaks(texts) == [], "모델이 받은 도구 결과에 원문 식별자"
    assert any(IMSI in str(s.get("error")) for s in states[:2])              # 사용자 터미널(이벤트)에는 원문 그대로
    hooks = [e for e in r.guard_log if e.get("hook") == "error"]
    assert hooks and all(e["replaced"] for e in hooks) and not any(IMSI in json.dumps(e) for e in r.guard_log)


def test_model_cannot_open_gate_inside_opencode():
    w = workspace()
    proj = tmp("tt-ocj-self-") / "proj"
    proj.mkdir()
    cfg = w.home / "config.yaml"
    record = w.home / "opencode-jira-check.json"
    before = cfg.read_bytes()
    steps = [{"tool": "bash", "args": {"command": f'python3 "{w.root}/scripts/config.py" set opencode.jira_read open'}},
             {"tool": "bash", "args": {"command": f"python3 {w.root}/scripts/config.py set 'open''code.jira_read' open"}},
             {"tool": "write", "args": {"filePath": str(cfg), "content": "opencode: {jira_read: open}\n"}},
             {"tool": "write", "args": {"filePath": str(record), "content": "{}"}},
             {"tool": "edit", "args": {"filePath": str(cfg), "oldString": "work_dir", "newString": "x"}},
             {"text": "FINAL"}]
    r = ocenv.run_opencode(proj, {"main": steps, "child": [{"text": "C"}]}, home=proj.parent / "home",
                           plugin_root=w.root, extra_env=w.env())
    errs = [str(s.get("error") or "") for s in r.tool_states() if s.get("status") == "error"]
    assert len(errs) == 5, r.events
    assert all(oc.ASK_PREFIX in e and "OpenCode 설정 변경" in e for e in errs[:2]), errs
    assert all("telephony-triage 사용자 설정" in e for e in errs[2:]), errs
    assert cfg.read_bytes() == before and not record.exists()


def _template_permission(w) -> dict:
    """배포 템플릿(`opencode/opencode.json.template`) 권한을 설치처럼 펼친 것(bash "*" deny + "python3 *" allow 등)."""
    sys.path.insert(0, str(REPO / "tools"))
    import gen_opencode as gx
    tpl = json.loads((REPO / "opencode" / "opencode.json.template").read_text(encoding="utf-8"))
    vals = {"@@PLUGIN_ROOT@@": str(w.root), "@@WORK_ROOT@@": str(w.work), "@@PLUGIN_ROOT_REL@@": gx._rel(str(w.root)),
            "@@WORK_ROOT_REL@@": gx._rel(str(w.work)), "@@GATEWAY_BASE_URL@@": "x", "@@MODEL_ID@@": "glm-fake"}
    return gx.render_config(tpl["permission"], vals, [])


def test_model_cannot_forge_gate_with_script_out_under_template_permission():
    """리뷰 P0 회귀: 모델이 쓴 JSON을 플러그인 스크립트 `--out`으로 사용자 config·통과 기록 위에 쓰면 관문이 열렸다(JSON은 YAML로도
    읽힌다). 배포 템플릿 권한 그대로 실제 opencode에서, 모든 꼴(`--out X`·`--out=X`·작업 폴더 기준 상대 경로)이 거부되고 파일과
    관문은 그대로다."""
    w = workspace()
    proj = tmp("tt-ocj-forge-") / "proj"
    proj.mkdir()
    cfg, record = w.home / "config.yaml", w.home / "opencode-jira-check.json"
    from common import oc_jira_gate as g
    rec = {"schema": 1, "at": "2026-11-05T10:00:00+09:00", "passed": False, "opencode_version": oc.OPENCODE_VERSION,
           "jira_server": SERVER, "tools": [OC_GET], "scripts_sha": g.scripts_digest(w.root),
           "checks": [{"check": "success-masking", "status": "fail", "detail": "x"},
                      {"check": "error-path", "status": "warn", "detail": "y"}]}
    record.write_text(json.dumps(rec), encoding="utf-8")
    import yaml
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["opencode"] = {"jira_read": "open"}
    forged = dict(rec, passed=True, checks=[{"check": "error-path", "status": "pass", "detail": "y"}])
    cfg_before, rec_before = cfg.read_bytes(), record.read_bytes()
    w.work.mkdir(parents=True, exist_ok=True)
    s = f"{w.root}/scripts"
    steps = [{"tool": "write", "args": {"filePath": str(w.work / "c.json"), "content": json.dumps(data)}},
             {"tool": "write", "args": {"filePath": str(w.work / "r.json"), "content": json.dumps(forged)}},
             {"tool": "bash", "args": {"command": f"python3 {s}/mask_pii.py --events {w.work}/c.json --out {cfg}"}},
             {"tool": "bash", "args": {"command": f"python3 {s}/mask_pii.py --events {w.work}/r.json --out={record}"}},
             {"tool": "bash", "args": {"command": f"python3 {s}/mask_pii.py --events {w.work}/r.json --out "
                                                  f"opencode-jira-check.json", "workdir": str(w.home)}},
             {"tool": "bash", "args": {"command": f"cd {w.home} && python3 {s}/parse_logcat.py bugreport "
                                                  f"{w.work}/c.json --out config.yaml"}},
             {"text": "FINAL"}]
    r = ocenv.run_opencode(proj, {"main": steps, "child": [{"text": "C"}]}, home=proj.parent / "home",
                           plugin_root=w.root, extra_env=w.env(), permission=_template_permission(w))
    states = r.tool_states()
    assert [x.get("status") for x in states] == ["completed", "completed"] + ["error"] * 4, r.events
    errs = [str(x.get("error") or "") for x in states[2:6]]
    assert all("[telephony-triage]" in e and "telephony-triage 사용자 설정" in e for e in errs), errs
    assert cfg.read_bytes() == cfg_before and record.read_bytes() == rec_before
    assert not g.state(yaml.safe_load(cfg.read_text(encoding="utf-8")), plugin_root=w.root, record_file=record).open


def _install(base: Path, w, extra: list[str] = ()) -> Path:
    dest = base / "proj"
    inst = subprocess.run([sys.executable, str(REPO / "tools" / "gen_opencode.py"), "install", "--dest", str(dest),
                           "--plugin-root", str(w.root), "--work-root", str(w.work), "--issue-db", str(w.clone),
                           "--gateway-url", f"http://{ocenv.LOOPBACK}:9/v1", "--model", "glm-fake", *extra],
                          capture_output=True, text=True, check=False, env={**os.environ, **{k: str(v) for k, v in w.env().items()}})
    if inst.returncode != 0 and "git" in inst.stdout + inst.stderr:
        pytest.skip(f"임시 폴더가 git 레포 안이다: {inst.stderr.strip()}")
    assert inst.returncode == 0, inst.stdout + inst.stderr
    return dest


def _global_mcp(home: Path, log: Path) -> None:
    """사내처럼 Jira MCP를 사용자 전역 OpenCode 설정(`~/.config/opencode/opencode.json`)에 둔다."""
    path = home / ".config" / "opencode" / "opencode.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcp": mcp(log)}), encoding="utf-8")


def test_runtime_check_records_pass_then_user_opens_and_installed_read_works():
    binary = ocenv.require_opencode()
    w = workspace()
    base = tmp("tt-ocj-rc-")
    home, log = base / "home", base / "jira-calls.jsonl"
    env = ocenv.base_env(home, {**w.env(), "TT_OPENCODE": binary, "TT_PYTHON": sys.executable})
    _global_mcp(home, log)
    dest = _install(base, w)
    raw = w.work / "MOCK-2001" / "issue_raw.json"
    record = w.home / "opencode-jira-check.json"

    def config_set(*args, extra=None):
        return subprocess.run([sys.executable, str(w.root / "scripts" / "config.py"), "set", *args],
                              env={**env, **(extra or {})}, capture_output=True, text=True, timeout=60, check=False)

    refused = config_set("opencode.jira_read", "open")                       # 확인 기록이 없으면 열 수 없다
    assert refused.returncode == 2 and "runtime-check opencode" in refused.stderr, refused.stderr

    proc = subprocess.run([sys.executable, str(REPO / "tools" / "site_step.py"), "runtime-check", "opencode",
                           "--project", str(dest), "--jira", "MOCK-2001", "--missing-key", "MOCK-2999"],
                          env=env, capture_output=True, text=True, timeout=600, check=False)
    print(proc.stdout[-4000:], proc.stderr[-2000:])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = {ln.split("|")[1].strip(): ln.split("|")[2].strip() for ln in proc.stdout.splitlines()
            if ln.startswith("| ") and ln.count("|") >= 4}
    assert {rows[k] for k in ("tools-offered", "success-isolation", "success-masking", "comments-isolation",
                              "comments-masking", "error-path")} == {"pass"}, rows
    assert rows["permission"] == "warn"                                       # 설치 설정은 아직 읽기 도구를 허용하지 않는다
    assert "본문 숨김" in proc.stdout and not leaks([proc.stdout, proc.stderr])
    assert "config.py set opencode.jira_read open" in proc.stdout and "--accept-error-bodies" not in proc.stdout
    assert not raw.exists()                                                   # 확인이 만든 원문 파일은 지웠다
    calls = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
    assert [(c["name"], c["arguments"]["issue_key"]) for c in calls] == [("get_issue", "MOCK-2001"),
                                                                         ("get_comments", "MOCK-2001"),
                                                                         ("get_issue", "MOCK-2999")]
    rec = json.loads(record.read_text(encoding="utf-8"))
    assert rec["passed"] is True and rec["opencode_version"] == oc.OPENCODE_VERSION and rec["jira_server"] == SERVER
    assert rec["tools"] == [OC_GET, OC_COMMENTS] and not leaks([json.dumps(rec, ensure_ascii=False)])

    inside = config_set("opencode.jira_read", "open", extra={"TT_RUNTIME": "opencode"})
    assert inside.returncode == 2 and "OpenCode 안에서는" in inside.stderr
    opened = config_set("opencode.jira_read", "open")
    assert opened.returncode == 0, opened.stderr

    # 사용자가 연 뒤: 설치 설정(읽기 도구 허용으로 다시 설치) 그대로의 실제 opencode, 테스트 env 스위치 없음
    dest2 = _install(tmp("tt-ocj-rc2-"), w, ["--jira-read-tool", OC_GET])
    script, req_log = base / "script.json", base / "requests.jsonl"
    script.write_text(json.dumps({"main": [{"tool": OC_GET, "args": {"issue_key": "MOCK-2001"}},
                                           {"tool": OC_ADD, "args": {"issue_key": "MOCK-2001", "body": "x"}},
                                           {"text": "FINAL"}], "child": [{"text": "C"}]}), encoding="utf-8")
    server = subprocess.Popen([sys.executable, str(ocenv.FAKES / "fake_oai.py"), str(script), str(req_log)],
                              stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    try:
        port = int(server.stdout.readline().strip())
        cfg = json.loads((dest2 / "opencode.json").read_text(encoding="utf-8"))
        cfg["provider"]["gw"]["options"]["baseURL"] = f"http://{ocenv.LOOPBACK}:{port}/v1"
        (dest2 / "opencode.json").write_text(json.dumps(cfg), encoding="utf-8")
        assert oc.JIRA_GATE_ENV not in env
        run = subprocess.run([binary, "run", "--format", "json", "--agent", "triage", "go"], cwd=dest2,
                             env={**env, "TT_GATEWAY_API_KEY": "dummy"}, stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=180, check=False)
    finally:
        server.kill()
        server.wait()
    events = [json.loads(ln) for ln in run.stdout.splitlines() if ln.startswith("{")]
    states = [e["part"]["state"] for e in events if e.get("type") == "tool_use"]
    assert states and states[0]["status"] == "completed", (events, run.stderr[-2000:])
    assert states[0]["output"].startswith("telephony-triage: Jira 응답 원문은 파일로만")
    assert states[1]["status"] == "error"                                    # 코멘트 쓰기는 늘 막힌다(설정 deny 또는 guard)
    reqs = [json.loads(ln) for ln in req_log.read_text(encoding="utf-8").splitlines()]
    assert not leaks([t for q in reqs for t in q["tool_results"]])
    assert raw.is_file() and IMSI in raw.read_text(encoding="utf-8")         # 원문은 work_dir 파일에만
    assert [json.loads(ln)["name"] for ln in log.read_text(encoding="utf-8").splitlines()][-1] == "get_issue"
