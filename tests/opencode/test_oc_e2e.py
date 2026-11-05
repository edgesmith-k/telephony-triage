"""OpenCode 1.19.5 e2e: 가짜 모델(127.0.0.1) + 실제 `opencode run` + tt-guard.js + 바뀌지 않은 guard.py·jira_bridge.py
(계획 I O9). opencode 1.19.5가 없으면 건너뛴다(`ocenv.require_opencode`). 네트워크·실제 모델은 쓰지 않는다.

설정된 guard 작업공간(이슈 DB clone + 로컬 bare 원격, tracker = mock-jira)에서:
- bash `workdir`로 clone을 가리킨 base push → 거부, 이슈 DB push(ask) → 거부 + 정확한 명령, 원격은 그대로
- 상대 경로 write·apply_patch(gpt 모델 ID일 때 OpenCode가 주는 도구)로 clone 편집 → 거부, 파일 그대로
- 로그 원문 통독(규칙 10) 거부, 평범한 bash는 실행
- 설정을 덮는 환경변수(`OPENCODE_PERMISSION`) → 모든 도구 거부, task → 거부
- Jira: 관문 닫힘 → 읽기 거부 / 관문 열림(`TT_OC_JIRA_GATE=open`) → 마스킹 요약만 모델에, 원문은 work_dir 파일에만,
  get_comments 합치기, MCP 오류 경로(본문 숨김 — test_oc_jira.py에 더 있다), 코멘트 도구 늘 거부, snapshot 폴더 없음
- 가짜 GLM 변형(조각난 인자·한 턴 두 호출·reasoning_content·JSON 아닌 인자·stop+tool_calls·글로 쓴 호출·빈 마지막 글):
  OpenCode 동작을 기록하고, 실행된 bash는 모두 guard를 거쳤는지 본다
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
from runner import plugin_root, tmp

IMSI = "450081234567890"
JIRA = ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets", "mcp__mock-jira__jira_ticket_comments"]
JIRA_SERVER = REPO / "tests" / "mocks" / "jira_mcp" / "server.py"

pytestmark = pytest.mark.usefixtures("needs_opencode")


@pytest.fixture
def needs_opencode():
    ocenv.require_opencode()


def test_version_pinned():
    binary = ocenv.opencode_bin()
    if not binary:
        pytest.skip("opencode가 없다")
    version = ocenv.opencode_version(binary)
    if version != ocenv.OPENCODE_VERSION and not os.environ.get("TT_OPENCODE_BIN"):
        pytest.skip(f"PATH의 opencode {version} — 고정 버전 확인은 TT_OPENCODE_BIN으로 지정할 때만")
    assert version == ocenv.OPENCODE_VERSION == oc.OPENCODE_VERSION


_WS = None


def ws():
    global _WS
    if _WS is None:
        from workspace import Workspace
        _WS = Workspace()
        _WS.json("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA[0],
                               "--search-issues", JIRA[1], "--get-comments", JIRA[2]])
    return _WS


def project(name: str) -> Path:
    d = tmp(f"tt-oce-{name}-") / "proj"
    d.mkdir()
    return d


def run(name: str, steps: list, *, configured: bool = True, **kw) -> ocenv.OcRun:
    w = ws() if configured else None
    proj = kw.pop("proj", None) or project(name)
    extra = {**(w.env() if w else {}), **kw.pop("extra_env", {})}
    return ocenv.run_opencode(proj, {"main": steps, "child": [{"text": "CHILD DONE"}]}, home=proj.parent / "home",
                              plugin_root=w.root if w else plugin_root(), extra_env=extra, **kw)


def errors(r: ocenv.OcRun, tool: str | None = None) -> list[str]:
    return [str(s.get("error") or "") for s in r.tool_states(tool) if s.get("status") == "error"]


def ran(r: ocenv.OcRun, marker: str) -> list[dict]:
    """완료된 bash 중 출력에 marker가 있는 것(= OpenCode가 실제로 돌린 것)."""
    return [s for s in r.tool_states("bash") if s.get("status") == "completed" and marker in str(s.get("output") or "")]


def remote_refs(w) -> str:
    return subprocess.run(["git", "--git-dir", str(w.remote), "for-each-ref", "--format=%(refname)"],
                          capture_output=True, text=True, check=False).stdout


# -- guard ---------------------------------------------------------------------------------------------


def test_push_by_workdir_denied_and_ask_prints_command():
    w = ws()
    before = remote_refs(w)
    r = run("push", [{"tool": "bash", "args": {"command": "git push origin HEAD:main", "workdir": str(w.clone)}},
                     {"tool": "bash", "args": {"command": "git push origin HEAD:refs/heads/oc-e2e", "workdir": str(w.clone)}},
                     {"text": "FINAL"}])
    errs = errors(r, "bash")
    assert r.exit == 0 and len(errs) == 2, (r.exit, r.events, r.stderr[-2000:])
    assert "telephony-triage" in errs[0]
    assert errs[1].endswith(f"{oc.ASK_PREFIX}cd {w.clone.resolve()} && git push origin HEAD:refs/heads/oc-e2e"), errs[1]
    assert remote_refs(w) == before and "oc-e2e" not in before
    assert [e["decision"] for e in r.guard_log if e["hook"] == "before"] == ["deny", "deny"]


def test_relative_write_into_clone_denied():
    w = ws()
    proj = project("write")
    target = w.clone / "README.md"
    original = target.read_bytes()
    rel = os.path.relpath(target, proj)
    r = run("write", [{"tool": "write", "args": {"filePath": rel, "content": "x"}},
                      {"tool": "edit", "args": {"filePath": rel, "oldString": "a", "newString": "b"}},
                      {"tool": "write", "args": {"filePath": "notes.txt", "content": "ok"}}, {"text": "FINAL"}], proj=proj)
    assert all("규칙 8" in e for e in errors(r, "write")[:1] + errors(r, "edit")), r.events
    assert target.read_bytes() == original
    assert (proj / "notes.txt").read_text(encoding="utf-8") == "ok"


def test_apply_patch_into_clone_denied():
    """x5: gpt 모델 ID면 OpenCode는 edit/write 대신 apply_patch를 준다. 시제품은 `mcp__apply__patch`로 바꿔 통과시켰다."""
    w = ws()
    proj = project("patch")
    rel = os.path.relpath(w.clone / "oc-patch.txt", proj)
    r = run("patch", [{"tool": "apply_patch", "args": {"patchText": f"*** Begin Patch\n*** Add File: {rel}\n+x\n*** End Patch"}},
                      {"tool": "apply_patch", "args": {"patchText": "*** Begin Patch\n*** Add File: sub/new.txt\n+y\n*** End Patch"}},
                      {"text": "FINAL"}], proj=proj, model="gpt-5-fake")
    offered = r.requests[-1]["tools"] if r.requests else []
    assert "apply_patch" in offered, offered
    assert "규칙 8" in errors(r, "apply_patch")[0]
    assert not (w.clone / "oc-patch.txt").exists()
    assert (proj / "sub" / "new.txt").read_text(encoding="utf-8").strip() == "y"


def test_raw_read_denied_and_plain_bash_runs():
    proj = project("raw")
    (proj / "job").mkdir()
    (proj / "job" / "issue_raw.json").write_text("{}", encoding="utf-8")
    r = run("raw", [{"tool": "bash", "args": {"command": "echo MARK_RAN"}},
                    {"tool": "bash", "args": {"command": "cat job/issue_raw.json"}}, {"text": "FINAL"}],
            configured=False, proj=proj)
    assert ran(r, "MARK_RAN"), r.events
    assert "규칙 10" in errors(r, "bash")[0]


def test_env_override_refused():
    proj = project("env")
    r = run("env", [{"tool": "bash", "args": {"command": "echo MARK_RAN"}}, {"text": "FINAL"}], configured=False,
            proj=proj, extra_env={"OPENCODE_PERMISSION": '{"bash":"allow"}'})
    assert not ran(r, "MARK_RAN")
    assert "OPENCODE_PERMISSION" in errors(r, "bash")[0]


def test_task_denied():
    r = run("task", [{"tool": "task", "args": {"description": "d", "prompt": "CHILDTASK", "subagent_type": "general"}},
                     {"text": "FINAL"}], configured=False)
    assert "전역 거부" in errors(r, "task")[0]
    assert not any(q["child"] for q in r.requests)


# -- Jira ----------------------------------------------------------------------------------------------


def _jira(tmpdir: Path) -> tuple[dict, dict]:
    tickets = tmpdir / "tickets"
    tickets.mkdir(exist_ok=True)
    (tickets / "MOCK-1001.yaml").write_text(
        "key: MOCK-1001\nfields:\n  summary: 데이터 끊김 e2e\n"
        f"  description: \"imsi={IMSI} 재부팅하면 잠시 됨\"\n  status: {{name: Open}}\n"
        f"comments:\n  - {{author: mock.dev, created: '2026-09-21T09:10:00+0900', body: 'imsi {IMSI} 확인'}}\n",
        encoding="utf-8")
    env = {"MOCK_JIRA_DIR": str(tickets), "MOCK_JIRA_WRITE_LOG": str(tmpdir / "writes.json")}
    mcp = {"mock-jira": {**ocenv.mcp_local(sys.executable, JIRA_SERVER), "environment": env}}
    return mcp, env


def test_jira_gate_closed_denies_reads():
    proj = project("jgate")
    mcp, env = _jira(proj.parent)
    r = run("jgate", [{"tool": "mock-jira_jira_fetch_ticket", "args": {"ticket": "MOCK-1001"}}, {"text": "FINAL"}],
            proj=proj, mcp=mcp, extra_env=env)
    assert "mock-jira_jira_fetch_ticket" in r.requests[-1]["tools"]
    assert "관문이 닫혀" in errors(r)[0]
    assert IMSI not in r.all_text() and "데이터 끊김" not in r.all_text()


def test_jira_masked_read_comments_merge_error_and_comment_denied():
    w = ws()
    proj = project("jread")
    mcp, env = _jira(proj.parent)
    raw = w.work / "MOCK-1001" / "issue_raw.json"
    raw.unlink(missing_ok=True)
    r = run("jread", [{"tool": "mock-jira_jira_fetch_ticket", "args": {"ticket": "MOCK-1001"}},
                      {"tool": "mock-jira_jira_ticket_comments", "args": {"ticket": "MOCK-1001"}},
                      {"tool": "mock-jira_jira_fetch_ticket", "args": {"ticket": "MOCK-9999"}},
                      {"tool": "mock-jira_jira_ticket_add_note", "args": {"ticket": "MOCK-1001", "text": "x"}},
                      {"text": "FINAL"}], proj=proj, mcp=mcp, extra_env={**env, oc.JIRA_GATE_ENV: "open"})
    states = r.tool_states()
    assert len(states) == 4, r.events
    fetch, comments, missing, note = states
    assert fetch["status"] == "completed" and "데이터 끊김 e2e" in fetch["output"], fetch
    assert comments["status"] == "completed"
    assert missing["status"] == "error"                      # MCP isError: 1.19.5는 after hook을 돌리지 않는다
    seen = [t for q in r.requests for t in q["tool_results"]]
    assert any(t == "Jira 오류(본문 숨김): mock-jira_jira_fetch_ticket not-found" for t in seen), seen   # transform hook
    assert not any("MOCK-9999" in t for t in seen)
    assert note["status"] == "error" and "코멘트 게시는 OpenCode v1" in note["error"]
    # 모델이 받은 것(가짜 서버 요청의 tool 메시지)과 이벤트 어디에도 원문 IMSI가 없다
    assert IMSI not in r.all_text()
    assert not any(IMSI in t for q in r.requests for t in q["tool_results"])
    saved = json.loads(raw.read_text(encoding="utf-8"))
    assert IMSI in json.dumps(saved, ensure_ascii=False) and saved.get("comments"), saved
    assert not Path(env["MOCK_JIRA_WRITE_LOG"]).exists()                       # 코멘트는 서버까지 가지 않았다
    assert r.data_home.is_dir() and not (r.data_home / "snapshot").exists()   # snapshot:false (계획 I x4)
    print("MCP error path:", missing.get("status"), (missing.get("output") or missing.get("error") or "")[:200])


# -- 가짜 GLM 변형 ----------------------------------------------------------------------------------------

VARIANTS = {
    "chunked": [{"tool": "bash", "args": {"command": "echo M_chunked"}, "chunked": True}],
    "two_calls": [{"tools": [{"tool": "bash", "args": {"command": "echo M_two_a"}},
                             {"tool": "bash", "args": {"command": "cat job/issue_raw.json > M_two_leak"}}]}],
    "reasoning": [{"tool": "bash", "args": {"command": "echo M_reasoning"}, "reasoning": "생각 중"}],
    "invalid_json": [{"tool": "bash", "args": {}, "raw_args": "{\"command\": \"echo M_invalid"}],
    "stop_with_calls": [{"tool": "bash", "args": {"command": "echo M_stop"}, "finish": "stop"}],
    "text_call": [{"content": "<tool_call>bash\n{\"command\": \"echo M_text\"}</tool_call>"}],
    "empty_final": [{"tool": "bash", "args": {"command": "echo M_empty"}}, {"empty": True}],
}


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_glm_variant_every_executed_bash_was_guarded(name):
    proj = project(name)
    (proj / "job").mkdir()
    (proj / "job" / "issue_raw.json").write_text("{}", encoding="utf-8")
    steps = VARIANTS[name] + ([{"text": "FINAL"}] if name != "empty_final" else [])
    r = run(name, steps, configured=False, proj=proj, timeout=60)
    made = sorted({w for s in ran(r, "M_") for w in str(s.get("output")).split() if w.startswith("M_")})
    guarded = [e for e in r.guard_log if e["hook"] == "before" and e["tool"] == "bash"]
    allowed = sum(1 for e in guarded if e["decision"] == "allow")
    print(f"variant {name}: exit={r.exit} tools={[(p.get('tool'), p.get('state', {}).get('status')) for p in r.tool_parts()]} "
          f"made={made} guard={[e['decision'] for e in guarded]}")
    assert r.exit in (0, 1), r.stderr[-2000:]
    assert len(made) <= allowed, (made, guarded)               # guard가 허용한 것보다 많이 실행되지 않았다
    assert "M_two_leak" not in made and not (proj / "M_two_leak").exists()


# -- installed layout (gen_opencode install) -------------------------------------------------------------


def test_installed_project_loads_guard_without_plugin_root_env():
    """`tools/gen_opencode.py install`이 쓴 프로젝트 폴더 그대로(opencode.json에 `plugin` 항목 없음, TT_PLUGIN_ROOT 없음):
    1.19.5가 `.opencode/plugins/tt-guard.js`를 자동으로 싣고, 설치 때 써 넣은 플러그인 루트의 어댑터·guard를 부른다
    (tt-oc를 거치지 않는 TUI 실행과 같은 조건). 설정 허용 목록과 guard가 함께 걸린다."""
    binary = ocenv.require_opencode()
    base = tmp("tt-oce-inst-")
    plug, work, dest, home = plugin_root(), base / "work", base / "proj", base / "home"
    (work / "job").mkdir(parents=True)
    (work / "job" / "issue_raw.json").write_text("{}", encoding="utf-8")
    steps = [{"tool": "bash", "args": {"command": "echo MARK_RAN"}},
             {"tool": "bash", "args": {"command": f"cat {work}/job/issue_raw.json"}},
             {"tool": "task", "args": {"description": "d", "prompt": "CHILDTASK", "subagent_type": "general"}},
             {"text": "FINAL"}]
    home.mkdir()
    script_path, req_log, guard_log = home / "script.json", home / "requests.jsonl", home / "guard.log"
    script_path.write_text(json.dumps({"main": steps, "child": [{"text": "CHILD DONE"}]}), encoding="utf-8")
    server = subprocess.Popen([sys.executable, str(ocenv.FAKES / "fake_oai.py"), str(script_path), str(req_log)],
                              stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    try:
        port = int(server.stdout.readline().strip())
        inst = subprocess.run([sys.executable, str(REPO / "tools" / "gen_opencode.py"), "install", "--dest", str(dest),
                               "--plugin-root", str(plug), "--work-root", str(work), "--gateway-url",
                               f"http://{ocenv.LOOPBACK}:{port}/v1", "--model", "glm-fake"],
                              capture_output=True, text=True, check=False)
        if inst.returncode != 0 and "git" in inst.stdout + inst.stderr:
            pytest.skip(f"임시 폴더가 git 레포 안이다: {inst.stderr.strip()}")
        assert inst.returncode == 0, inst.stdout + inst.stderr
        cfg = json.loads((dest / "opencode.json").read_text(encoding="utf-8"))
        assert "plugin" not in cfg and (dest / ".opencode" / "plugins" / "tt-guard.js").is_file()
        env = ocenv.base_env(home, {"TT_OC_GUARD_LOG": guard_log, "TT_PYTHON": sys.executable,
                                    "TT_GATEWAY_API_KEY": "dummy"})
        assert "TT_PLUGIN_ROOT" not in env
        proc = subprocess.run([binary, "run", "--format", "json", "--agent", "triage", "go"], cwd=dest, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120, check=False)
    finally:
        server.kill()
        server.wait()
    events = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.startswith("{")]
    r = ocenv.OcRun(proc.returncode, events, proc.stderr)
    assert ran(r, "MARK_RAN"), (r.events, r.stderr[-2000:])
    assert "규칙 10" in errors(r, "bash")[0], r.events
    assert not [s for s in r.tool_states("task") if s.get("status") != "error"], r.events
    logged = [json.loads(ln) for ln in guard_log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    bash = [e["decision"] for e in logged if e["hook"] == "before" and e.get("tool") == "bash"]
    assert bash == ["allow", "deny"], logged


def installed_run(base: Path, steps: list, *, plug: Path, work: Path, model: str = "glm-fake", issue_dbs=(),
                  extra_env: dict | None = None) -> tuple[ocenv.OcRun, Path, list]:
    """`gen_opencode.py install`한 프로젝트 폴더에서 `opencode run --agent triage`(TT_PLUGIN_ROOT 없음). (결과, dest, guard 로그)."""
    binary = ocenv.require_opencode()
    dest, home = base / "proj", base / "home"
    home.mkdir(parents=True)
    script_path, req_log, guard_log = home / "script.json", home / "requests.jsonl", home / "guard.log"
    script_path.write_text(json.dumps({"main": steps, "child": [{"text": "CHILD DONE"}]}), encoding="utf-8")
    server = subprocess.Popen([sys.executable, str(ocenv.FAKES / "fake_oai.py"), str(script_path), str(req_log)],
                              stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    try:
        port = int(server.stdout.readline().strip())
        dbs = [a for c in issue_dbs for a in ("--issue-db", str(c))]
        inst = subprocess.run([sys.executable, str(REPO / "tools" / "gen_opencode.py"), "install", "--dest", str(dest),
                               "--plugin-root", str(plug), "--work-root", str(work), *dbs, "--gateway-url",
                               f"http://{ocenv.LOOPBACK}:{port}/v1", "--model", model],
                              capture_output=True, text=True, check=False)
        if inst.returncode != 0 and "git" in inst.stdout + inst.stderr:
            pytest.skip(f"임시 폴더가 git 레포 안이다: {inst.stderr.strip()}")
        assert inst.returncode == 0, inst.stdout + inst.stderr
        env = ocenv.base_env(home, {"TT_OC_GUARD_LOG": guard_log, "TT_PYTHON": sys.executable,
                                    "TT_GATEWAY_API_KEY": "dummy", **(extra_env or {})})
        proc = subprocess.run([binary, "run", "--format", "json", "--agent", "triage", "go"], cwd=dest, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180, check=False)
    finally:
        server.kill()
        server.wait()
    events = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.startswith("{")]
    logged = [json.loads(ln) for ln in guard_log.read_text(encoding="utf-8").splitlines() if ln.strip()] \
        if guard_log.is_file() else []
    reqs = [json.loads(ln) for ln in req_log.read_text(encoding="utf-8").splitlines() if ln.strip()] \
        if req_log.is_file() else []
    return ocenv.OcRun(proc.returncode, events, proc.stderr, logged, reqs), dest, logged


def _sha(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_installed_blocks_indirect_push_tamper_nested_and_bom_patch():
    """계획 I 2단계 리뷰 재현(실제 1.19.5, 설치한 템플릿 그대로, 설정된 guard):
    P0 스크립트 파일·python 하위 프로세스 push(원격에 via-script가 생겼다), P1 guard 플러그인 삭제·adapter 수정,
    P1 중첩 `opencode run --pure`(LEAK.txt), P1 apply_patch BOM 경로(work 루트의 승인 기록). 모두 막히고, tt-oc는
    이 실행을 막힌 호출(종료 코드 3)로 판정한다."""
    w = ws()
    base = tmp("tt-oce-rv-")
    clone, adapter = w.clone.resolve(), w.root / "scripts" / "common" / "oc_adapter.py"
    adapter_sha = _sha(adapter)
    (w.work / "K-1").mkdir(parents=True, exist_ok=True)
    (w.work / "job").mkdir(parents=True, exist_ok=True)
    (w.work / "job" / "issue_raw.json").write_text(json.dumps({"imsi": IMSI}), encoding="utf-8")
    approved = w.work / "K-1" / "post.approved.json"
    approved.unlink(missing_ok=True)
    before = remote_refs(w)
    oc_bin = ocenv.require_opencode()
    steps = [
        {"tool": "bash", "args": {"command": f"printf 'TT_PUBLISH_TOKEN=manual git -C {clone} push origin "
                                             f"HEAD:refs/heads/via-script' > p.sh && sh p.sh"}},
        {"tool": "bash", "args": {"command": f"python3 -c \"import subprocess; subprocess.run(['git', '-C', '{clone}', "
                                             f"'push', '--no-verify', 'origin', 'HEAD:refs/heads/via-python'])\""}},
        {"tool": "bash", "args": {"command": "rm -f .opencode/plugins/tt-guard.js"}},
        {"tool": "bash", "args": {"command": f"sed -i 's/deny/allow/' {adapter}"}},
        {"tool": "bash", "args": {"command": f"OPENCODE_PERMISSION='{{\"*\":\"allow\"}}' {oc_bin} run --pure "
                                             f"'cat {w.work}/job/issue_raw.json' > LEAK.txt"}},
        {"tool": "apply_patch", "args": {"patchText": f"*** Begin Patch\n*** Add File: \ufeff{approved}\n+{{}}\n"
                                                      "*** End Patch"}},
        {"tool": "bash", "args": {"command": "echo MARK_RAN"}},
        {"tool": "bash", "args": {"command": f'python3 "{w.root}/scripts/config.py" --help 2>&1 | head -3'}},
        {"text": "FINAL"},
    ]
    r, dest, logged = installed_run(base, steps, plug=w.root, work=w.work, model="gpt-5-fake", issue_dbs=[w.clone],
                                    extra_env=w.env())
    errs = errors(r)
    print("blocked:", [e[:120] for e in errs])
    assert len(errs) == 6 and all("[telephony-triage]" in e or "prevents you from using" in e for e in errs), r.events
    assert ran(r, "MARK_RAN"), r.events                          # 허용 목록 안의 평범한 명령은 돈다
    assert ran(r, "usage"), r.events                             # 분석 스크립트 호출(파이프·2>&1)은 설정 허용 목록도 넘는다
    after = remote_refs(w)
    assert after == before and "via-script" not in after and "via-python" not in after
    assert (dest / ".opencode" / "plugins" / "tt-guard.js").is_file() and _sha(adapter) == adapter_sha
    assert not (dest / "LEAK.txt").exists() and not (dest / "p.sh").exists() and not approved.exists()
    assert IMSI not in r.all_text()
    # tt-oc 판정: 모두 막힌 호출(전문), 종료 코드 3
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("tt_oc_e2e", str(REPO / "opencode" / "bin" / "tt-oc"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("tt_oc_e2e", loader))
    loader.exec_module(mod)
    res = mod.judge(r.events, r.exit)
    assert res["outcome"] == "blocked" and mod.EXIT[res["outcome"]] == 3, res
    assert len(res["blocked"]) == 6 and res["errors"] == [], res
    assert sorted({e.get("tool") for e in logged if e.get("hook") == "before"}) == ["apply_patch", "bash"]


def test_tt_oc_real_run_exit_code_and_single_prompt():
    """실제 1.19.5 + tt-oc: 막힌 호출이 있으면 종료 코드 3(리뷰 P1: 0으로 끝났다), 모델 요청에 ~/.claude/CLAUDE.md가 붙지 않는다
    (리뷰 P1: 사용자 결정 ⑤ 프롬프트 하나), 위 폴더 AGENTS.md가 있으면 doctor가 시작하지 않는다."""
    binary = ocenv.require_opencode()
    w = ws()
    base = tmp("tt-oce-ttoc-")
    (w.work / "job").mkdir(parents=True, exist_ok=True)
    (w.work / "job" / "issue_raw.json").write_text("{}", encoding="utf-8")
    steps = [{"tool": "bash", "args": {"command": f"cat {w.work}/job/issue_raw.json"}}, {"text": "FINAL"}]
    dest, home = base / "proj", base / "home"
    home.mkdir()
    (home / ".claude").mkdir()
    (home / ".claude" / "CLAUDE.md").write_text("MARKER_GLOBAL_CLAUDE_MD\n", encoding="utf-8")
    script_path, req_log = home / "script.json", home / "requests.jsonl"
    script_path.write_text(json.dumps({"main": steps, "child": [{"text": "CHILD DONE"}]}), encoding="utf-8")
    server = subprocess.Popen([sys.executable, str(ocenv.FAKES / "fake_oai.py"), str(script_path), str(req_log)],
                              stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True)
    try:
        port = int(server.stdout.readline().strip())
        inst = subprocess.run([sys.executable, str(REPO / "tools" / "gen_opencode.py"), "install", "--dest", str(dest),
                               "--plugin-root", str(w.root), "--work-root", str(w.work), "--issue-db", str(w.clone),
                               "--gateway-url", f"http://{ocenv.LOOPBACK}:{port}/v1", "--model", "glm-fake"],
                              capture_output=True, text=True, check=False)
        if inst.returncode != 0 and "git" in inst.stdout + inst.stderr:
            pytest.skip(f"임시 폴더가 git 레포 안이다: {inst.stderr.strip()}")
        assert inst.returncode == 0, inst.stdout + inst.stderr
        env = ocenv.base_env(home, {"TT_OC_GUARD_LOG": home / "guard.log", "TT_PYTHON": sys.executable,
                                    "TT_GATEWAY_API_KEY": "dummy", **w.env()})
        ttoc = [sys.executable, str(REPO / "opencode" / "bin" / "tt-oc"), "--opencode", binary, "--project", str(dest)]
        doctor = subprocess.run([*ttoc, "doctor", "--json"], env=env, capture_output=True, text=True, timeout=300,
                                check=False)
        rows = {x["check"]: x for x in json.loads(doctor.stdout)["rows"]}
        if rows["config-doctor"]["status"] != "ok":
            pytest.skip(f"테스트 작업공간의 config.py doctor가 통과하지 않는다: {rows['config-doctor']['detail']}")
        assert doctor.returncode == 0, rows
        proc = subprocess.run([*ttoc, "--json", "--timeout", "120", "--", "go"], env=env, capture_output=True, text=True,
                              timeout=300, check=False)
        out = json.loads(proc.stdout)
        assert proc.returncode == 3 and out["outcome"] == "blocked", (proc.returncode, out)
        assert "규칙 10" in out["blocked"][0]["message"]
        reqs = req_log.read_text(encoding="utf-8")
        assert reqs and "MARKER_GLOBAL_CLAUDE_MD" not in reqs
        (base / "AGENTS.md").write_text("MARKER_PARENT_AGENTS\n", encoding="utf-8")   # dest의 위 폴더
        again = subprocess.run([*ttoc, "--", "go"], env=env, capture_output=True, text=True, timeout=300, check=False)
        assert again.returncode == 2 and "instructions: fail" in again.stdout and "MARKER_PARENT_AGENTS" not in \
            req_log.read_text(encoding="utf-8")
    finally:
        server.kill()
        server.wait()
