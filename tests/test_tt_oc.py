"""`opencode/bin/tt-oc` 래퍼 검사 — 가짜 opencode 바이너리로(실제 opencode·네트워크 없이) (계획 I 2단계 O7).

가짜 바이너리는 `--version`·`debug config`·`run`·`session delete`만 흉내 낸다: 받은 인자·stdin·환경을 기록하고, `run`이면
STUB_EVENTS 파일의 JSON 이벤트를 그대로 내보낸다(STUB_SHOWN이면 그 work_dir에 표시 기록 한 줄을 남긴다 — 스크립트가 쓴 것처럼).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TTOC = REPO / "opencode" / "bin" / "tt-oc"

STUB = r'''#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
log = os.environ["STUB_LOG"]
with open(log, "a") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "stdin_null": os.path.realpath("/proc/self/fd/0") == "/dev/null",
                        "env": {k: os.environ.get(k) for k in ("TT_RUNTIME", "CLAUDE_PLUGIN_ROOT", "TT_MODEL",
                                                               "OPENCODE_DISABLE_AUTOUPDATE", "OPENCODE_DISABLE_MODELS_FETCH",
                                                               "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT")}}) + "\n")
if args == ["--version"]:
    print(os.environ.get("STUB_VERSION", "1.19.5")); sys.exit(0)
if args[:2] == ["debug", "config"]:
    print(open(os.environ["STUB_CONFIG"]).read()); sys.exit(0)
if args[:2] == ["session", "delete"]:
    sys.exit(0)
if args[:1] == ["run"]:
    if os.environ.get("STUB_SHOWN"):
        from datetime import datetime, timezone
        w = os.environ["STUB_SHOWN"]; os.makedirs(w + "/.shown", exist_ok=True)
        at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        rec = {"v": 1, "at": at, "script": "triage", "kind": "report", "job": "ABC-1", "lines": ["- 분류 후보: C-1"],
               "must_show": ["- 분석 전용: 기록하지 않음"]}
        open(w + "/.shown/log.jsonl", "a").write("\n" + json.dumps(rec, ensure_ascii=False) + "\n")
    time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
    sys.stdout.write(open(os.environ["STUB_EVENTS"]).read()); sys.stdout.flush()
    print("stub stderr line", file=sys.stderr)
    sys.exit(int(os.environ.get("STUB_EXIT", "0")))
sys.exit(9)
'''

CONFIG_OK = {"snapshot": False, "share": "disabled", "autoupdate": False,
             "permission": {"*": "deny", "task": "deny", "bash": {"*": "deny", "python3 *": "allow"}}}


def ev(typ, **part):
    return {"type": typ, "sessionID": "ses_TEST", "part": part}


def step(reason="stop", inp=100, out=10):
    return ev("step_finish", reason=reason, tokens={"input": inp, "output": out, "reasoning": 0}, cost=0)


def tool(name, status="completed", **state):
    return ev("tool_use", tool=name, state={"status": status, **state})


def final(text="끝"):
    return [ev("step_start"), ev("text", text=text), step()]


@pytest.fixture
def env(tmp_path):
    for d in (tmp_path, *tmp_path.parents):
        if (d / ".git").exists():
            pytest.skip(f"임시 폴더가 git 레포 안이다: {d}")
    plug, work, proj = tmp_path / "plug", tmp_path / "work", tmp_path / "proj"
    (plug / "scripts").mkdir(parents=True)
    work.mkdir()
    proj.mkdir()
    (plug / "scripts" / "config.py").write_text(
        "import json, os, sys\nprint(json.dumps({'counts': {'ok': 1}}))\nsys.exit(int(os.environ.get('STUB_DOCTOR_EXIT', '0')))\n",
        encoding="utf-8")
    (proj / "opencode.json").write_text("{}", encoding="utf-8")
    (proj / ".opencode" / "plugins").mkdir(parents=True)
    (proj / ".opencode" / "plugins" / "tt-guard.js").write_text("// guard\n", encoding="utf-8")
    write_meta(proj, plug, work)
    stub = tmp_path / "opencode"
    stub.write_text(STUB.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1), encoding="utf-8")
    stub.chmod(0o755)
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(CONFIG_OK), encoding="utf-8")
    base = {k: v for k, v in os.environ.items() if not k.startswith("OPENCODE_")}
    (tmp_path / "home").mkdir()
    base.update({"HOME": str(tmp_path / "home"), "XDG_CONFIG_HOME": str(tmp_path / "home" / ".config"),"STUB_LOG": str(tmp_path / "log.jsonl"), "STUB_CONFIG": str(cfg), "STUB_EVENTS": str(tmp_path / "ev.jsonl")})
    return {"tmp": tmp_path, "plug": plug, "work": work, "proj": proj, "stub": stub, "cfg": cfg, "env": base}


def write_meta(proj, plug, work, **extra):
    """gen_opencode install처럼 설치 지문(integrity)을 남긴다."""
    gen = _load("gen_opencode", REPO / "tools" / "gen_opencode.py")
    files = {rel: gen.hashlib.sha256((proj / rel).read_bytes()).hexdigest()
             for rel in ("opencode.json", ".opencode/plugins/tt-guard.js")}
    meta = {"version": 1, "plugin_root": str(plug), "work_root": str(work), "model": "glm-x",
            "integrity": {"files": files, "plugin_scripts": gen.scripts_digest(plug)}, **extra}
    (proj / "tt-oc.json").write_text(json.dumps(meta), encoding="utf-8")


def _load(name, path):
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def events(e, evs):
    Path(e["env"]["STUB_EVENTS"]).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in evs), encoding="utf-8")


def tt(e, *args, extra_env=None, timeout=60):
    env = {**e["env"], **(extra_env or {})}
    return subprocess.run([sys.executable, str(TTOC), "--opencode", str(e["stub"]), "--project", str(e["proj"]), *args],
                          env=env, capture_output=True, text=True, timeout=timeout, check=False)


def calls(e):
    p = e["tmp"] / "log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def run_calls(e):
    return [c for c in calls(e) if c["args"][:1] == ["run"]]


# -- 거부 ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["--pure", "--auto", "--attach=http://localhost:1", "-i", "--agent", "--model"])
def test_refuses_dangerous_flags(env, flag):
    events(env, final())
    r = tt(env, flag, "--", "hi")
    assert r.returncode == 2 and "거부" in r.stderr
    assert calls(env) == []


def test_flag_text_after_double_dash_is_message(env):
    events(env, final())
    r = tt(env, "--", "--auto", "--pure", "분석")
    assert r.returncode == 0, r.stdout + r.stderr
    (c,) = run_calls(env)
    assert c["args"][-4:] == ["--", "--auto", "--pure", "분석"]


@pytest.mark.parametrize("var", ["OPENCODE_PERMISSION", "OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR",
                                 "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_PURE", "OPENCODE_EXPERIMENTAL_PLAN_MODE"])
def test_refuses_override_env(env, var):
    events(env, final())
    r = tt(env, "--", "hi", extra_env={var: '{"bash":"allow"}'})
    assert r.returncode == 2 and var in r.stdout
    assert run_calls(env) == []


def test_preflight_version_snapshot_and_doctor(env):
    events(env, final())
    r = tt(env, "--", "hi", extra_env={"STUB_VERSION": "1.20.0"})
    assert r.returncode == 2 and "버전 불일치" in r.stdout
    env["cfg"].write_text(json.dumps({**CONFIG_OK, "snapshot": True}), encoding="utf-8")
    r = tt(env, "--", "hi")
    assert r.returncode == 2 and "snapshot=true" in r.stdout
    env["cfg"].write_text(json.dumps({**CONFIG_OK, "permission": {"*": "allow", "task": "deny"}}), encoding="utf-8")
    r = tt(env, "--", "hi")
    assert r.returncode == 2 and 'permission["*"]' in r.stdout
    env["cfg"].write_text(json.dumps(CONFIG_OK), encoding="utf-8")
    r = tt(env, "--", "hi", extra_env={"STUB_DOCTOR_EXIT": "1"})
    assert r.returncode == 2 and "config-doctor: fail" in r.stdout
    assert run_calls(env) == []


DOCTOR_ROWS = r'''import json, os, sys
if sys.argv[1:2] == ["check"]:
    print(json.dumps({"read_roots": json.loads(os.environ.get("STUB_ROOTS", "[]"))})); sys.exit(0)
rows = json.loads(os.environ["STUB_DOCTOR_ROWS"])
fail = sum(r["status"] == "fail" for r in rows)
print(json.dumps({"counts": {"ok": len(rows) - fail, "fail": fail}, "rows": rows}))
sys.exit(1 if fail else 0)
'''


def _doctor_stub(e):
    (e["plug"] / "scripts" / "config.py").write_text(DOCTOR_ROWS, encoding="utf-8")
    write_meta(e["proj"], e["plug"], e["work"])        # 플러그인 스크립트 지문을 다시 남긴다


def _with(e, **extra):
    return {**e, "env": {**e["env"], **extra}}


def test_preflight_module_skills_fail_is_warning(env):
    """B2 R22: doctor의 fail이 `module_skills` 행뿐이면 시작한다(모듈 문서 받기만 실패할 수 있다). 다른 fail이 있으면 막는다."""
    _doctor_stub(env)
    events(env, final())
    only = [{"check": "config", "status": "ok", "detail": "x"},
            {"check": "module_skills", "status": "fail", "detail": "사용자 config analyzers.data.prefer: module 또는 skill이어야 합니다"}]
    r = tt(env, "--", "hi", extra_env={"STUB_DOCTOR_ROWS": json.dumps(only)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "module-skills: warn — 모듈 문서 받기는 실패할 수 있음" in r.stderr and len(run_calls(env)) == 1
    code, rows = _doctor_rows(_with(env, STUB_DOCTOR_ROWS=json.dumps(only)))
    assert code == 0 and rows["config-doctor"]["status"] == "ok" and rows["module-skills"]["status"] == "warn"
    both = only + [{"check": "gh", "status": "fail", "detail": "인증 없음"}]
    r = tt(env, "--", "hi", extra_env={"STUB_DOCTOR_ROWS": json.dumps(both)})
    assert r.returncode == 2 and "config-doctor: fail" in r.stdout and len(run_calls(env)) == 1


def test_doctor_warns_read_roots_outside_install(env):
    """B2 R21: 풀린 설치 스킬 폴더가 설치한 external_directory 허용 밖이면 경고 행(막지 않는다)."""
    _doctor_stub(env)
    (env["proj"] / "opencode.json").write_text(json.dumps({"permission": {"external_directory": {
        "*": "deny", f"{env['plug']}/**": "allow", f"{env['work']}/**": "allow"}}}), encoding="utf-8")
    write_meta(env["proj"], env["plug"], env["work"])
    ok_rows = json.dumps([{"check": "config", "status": "ok", "detail": "x"}])
    inside = json.dumps([str(env["plug"] / "skills" / "telephony-triage"), str(env["work"])])
    code, rows = _doctor_rows(_with(env, STUB_DOCTOR_ROWS=ok_rows, STUB_ROOTS=inside))
    assert code == 0 and "read-roots" not in rows
    outside = json.dumps([str(env["work"]), "/elsewhere/skills/mock"])
    code, rows = _doctor_rows(_with(env, STUB_DOCTOR_ROWS=ok_rows, STUB_ROOTS=outside))
    warn = rows["read-roots"]
    assert code == 0 and warn["status"] == "warn" and "/elsewhere/skills/mock" in warn["detail"]


def test_preflight_refuses_project_in_git(env):
    (env["tmp"] / ".git").mkdir()
    events(env, final())
    r = tt(env, "--", "hi")
    assert r.returncode == 2 and "project-git: fail" in r.stdout


def test_missing_project_files(env):
    (env["proj"] / "tt-oc.json").unlink()
    r = tt(env, "--", "hi")
    assert r.returncode == 2 and "tt-oc.json" in r.stderr


def test_doctor_subcommand(env):
    r = tt(env, "doctor", "--json")
    assert r.returncode == 0, r.stdout
    rows = json.loads(r.stdout)["rows"]
    assert [x["check"] for x in rows] == ["env", "project-git", "instructions", "integrity", "opencode-version",
                                          "opencode-config", "config-doctor"]
    assert all(x["status"] == "ok" for x in rows)


def test_command_name_and_message_required(env):
    assert tt(env, "--command", "init").returncode == 2
    assert tt(env).returncode == 2
    events(env, final())
    assert tt(env, "--command", "tt-status", "--", "ABC-1").returncode == 0
    (c,) = run_calls(env)
    assert c["args"] == ["run", "--format", "json", "--agent", "triage", "--command", "tt-status", "--", "ABC-1"]


# -- 실행·판정 ----------------------------------------------------------------------------------------------------------

def test_ok_run_invocation_and_output(env):
    events(env, [ev("step_start"), tool("bash", output="x"), step("tool-calls", 50, 5), *final("분석 결과입니다")])
    r = tt(env, "-s", "ses_PREV", "--", "분석", "ABC-1")
    assert r.returncode == 0, r.stdout + r.stderr
    (c,) = run_calls(env)
    assert c["args"] == ["run", "--format", "json", "--agent", "triage", "--session", "ses_PREV", "--", "분석", "ABC-1"]
    assert c["stdin_null"] is True and c["cwd"] == str(env["proj"])
    assert c["env"] == {"TT_RUNTIME": "opencode", "CLAUDE_PLUGIN_ROOT": str(env["plug"]), "TT_MODEL": "glm-x",
                        "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_MODELS_FETCH": "1",
                        "OPENCODE_DISABLE_CLAUDE_CODE_PROMPT": "1"}
    assert r.stdout.startswith("분석 결과입니다\n")
    assert "outcome: ok · session: ses_TEST · steps: 2 · tokens in/out/reasoning: 150/15/0 · cost: 미상" in r.stdout
    assert "이어서: tt-oc --project" in r.stdout and "-s ses_TEST" in r.stdout


def test_guard_ask_message_prints_exact_command(env):
    msg = ("[telephony-triage] 이슈 DB push·PR(db_pr publish)는 OpenCode v1(분석 전용)에서 돌리지 않는다. "
           "OpenCode v1 does not run this; run this exact command yourself: "
           "python3 /p/scripts/db_pr.py publish --job ABC-1 --commit")
    events(env, [ev("step_start"), tool("bash", "error", input={"command": "python3 /p/scripts/db_pr.py publish"}, error=msg),
                 step("tool-calls"), *final("직접 실행하세요")])
    r = tt(env, "--", "x")
    assert r.returncode == 3
    assert "막힌 호출(메시지 전문)" in r.stdout and msg in r.stdout
    tail = r.stdout.split("직접 실행 ----\n", 1)[1]
    assert tail.startswith("python3 /p/scripts/db_pr.py publish --job ABC-1 --commit\n")


def test_config_deny_write_command_with_workdir(env):
    deny = "The user has specified a rule which prevents you from using this specific tool call. ..."
    events(env, [ev("step_start"),
                 tool("bash", "error", input={"command": "git push origin HEAD", "workdir": "/w/clone dir"}, error=deny),
                 tool("bash", "error", input={"command": "cat job/issue_raw.json"}, error=deny),
                 step("tool-calls"), *final()])
    r = tt(env, "--json", "--", "x")
    out = json.loads(r.stdout)
    assert r.returncode == 3 and out["outcome"] == "blocked" and len(out["blocked"]) == 2
    assert out["user_commands"] == ["cd '/w/clone dir' && git push origin HEAD"]   # 로그 원문 읽기는 권하지 않는다


# 리뷰 P1: 실제 tt-guard.js·oc_adapter.py 거부 문구(모두 `[telephony-triage]`로 시작)는 막힌 호출(종료 코드 3)이고 전문을 보인다
REAL_DENIES = [
    ("bash", "[telephony-triage] 로그 원문 통독 금지 (규칙 10): job/issue_raw.json은 스크립트가 읽는다. " + "가" * 400),
    ("task", "[telephony-triage] task: task(하위 에이전트)는 전역 거부다(사용자 결정 ⑧). 같은 세션에서 직접 한다."),
    ("mock-jira_jira_ticket_add_note", ("[telephony-triage] Jira 코멘트 게시는 OpenCode v1에서 하지 않는다. "
                                        "issue_post.py render → approve → 게시는 Claude Code에서 한다.")),
    ("bash", "[telephony-triage] 이슈 DB clone push 금지 (규칙 6): main으로 직접 push하지 않는다."),
    ("bash", "[telephony-triage] bash 허용 목록: `sh`는 허용 목록 밖이다. OpenCode v1(분석 전용) bash는 …"),
    ("bash", "[telephony-triage] tt-guard blocked bash: adapter timed out"),
]


@pytest.mark.parametrize("name,msg", REAL_DENIES)
def test_real_deny_reasons_are_blocked_with_full_message(env, name, msg):
    events(env, [ev("step_start"), tool(name, "error", input={"command": "x"}, error=msg), step("tool-calls"), *final()])
    r = tt(env, "--json", "--", "x")
    out = json.loads(r.stdout)
    assert r.returncode == 3 and out["outcome"] == "blocked", out
    assert out["blocked"] == [{"tool": name, "message": msg}] and out["errors"] == []
    r = tt(env, "--", "x")
    assert r.returncode == 3 and f"[{name}] {msg}" in r.stdout and "outcome: blocked" in r.stdout


def test_guard_warning_is_not_a_block(env):
    warn = "[telephony-triage] guard warning (shown once per session; read it, then retry the same call):\nsite defaults"
    events(env, [ev("step_start"), tool("bash", "error", error=warn), tool("bash", output="ok"), step("tool-calls"),
                 *final()])
    r = tt(env, "--json", "--", "x")
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["outcome"] == "ok" and out["blocked"] == []
    assert out["guard_warnings"] == [f"bash: {warn}"]


def test_plain_tool_error_kept_in_full(env):
    msg = "File not found: " + "x" * 600
    events(env, [ev("step_start"), tool("read", "error", error=msg), step("tool-calls"), *final()])
    out = json.loads(tt(env, "--json", "--", "x").stdout)
    assert out["outcome"] == "ok" and out["errors"] == [f"read: {msg}"]


# -- 사전 점검: 설치 지문·지시 파일(리뷰 P1) ------------------------------------------------------------------------------

def _doctor_rows(e):
    r = tt(e, "doctor", "--json")
    return r.returncode, {x["check"]: x for x in json.loads(r.stdout)["rows"]}


def test_doctor_detects_removed_or_changed_guard_plugin(env):
    (env["proj"] / ".opencode" / "plugins" / "tt-guard.js").unlink()           # 모델이 bash rm으로 지운 경우
    code, rows = _doctor_rows(env)
    assert code == 2 and rows["integrity"]["status"] == "fail" and "tt-guard.js(없음)" in rows["integrity"]["detail"]
    (env["proj"] / ".opencode" / "plugins" / "tt-guard.js").write_text("// edited\n", encoding="utf-8")
    code, rows = _doctor_rows(env)
    assert code == 2 and ".opencode/plugins/tt-guard.js" in rows["integrity"]["detail"]
    events(env, final())
    assert tt(env, "--", "hi").returncode == 2 and run_calls(env) == []


def test_doctor_detects_changed_plugin_scripts_and_old_install(env):
    (env["plug"] / "scripts" / "common").mkdir()
    (env["plug"] / "scripts" / "common" / "oc_adapter.py").write_text("# sed -i\n", encoding="utf-8")
    code, rows = _doctor_rows(env)
    assert code == 2 and "scripts/**/*.py" in rows["integrity"]["detail"]
    write_meta(env["proj"], env["plug"], env["work"])
    assert _doctor_rows(env)[0] == 0
    meta = json.loads((env["proj"] / "tt-oc.json").read_text())
    del meta["integrity"]
    (env["proj"] / "tt-oc.json").write_text(json.dumps(meta), encoding="utf-8")
    code, rows = _doctor_rows(env)
    assert code == 2 and "옛 설치" in rows["integrity"]["detail"]


def test_gen_and_wrapper_scripts_digest_agree(env):
    (env["plug"] / "scripts" / "sub").mkdir()
    (env["plug"] / "scripts" / "sub" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (env["plug"] / "scripts" / "__pycache__").mkdir()
    (env["plug"] / "scripts" / "__pycache__" / "b.py").write_text("ignored\n", encoding="utf-8")
    gen, wrap = _load("gen_opencode", REPO / "tools" / "gen_opencode.py"), _load("tt_oc", TTOC)
    assert gen.scripts_digest(env["plug"]) == wrap.scripts_digest(env["plug"])


@pytest.mark.parametrize("where", ["parent", "project", "global"])
def test_doctor_refuses_auto_loaded_instruction_files(env, where):
    target = {"parent": env["tmp"] / "AGENTS.md", "project": env["proj"] / "CONTEXT.md",
              "global": env["tmp"] / "home" / ".config" / "opencode" / "AGENTS.md"}[where]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("MARKER\n", encoding="utf-8")
    code, rows = _doctor_rows(env)
    assert code == 2 and rows["instructions"]["status"] == "fail" and str(target) in rows["instructions"]["detail"]


def test_doctor_global_claude_md_is_disabled_not_refused(env):
    (env["tmp"] / "home" / ".claude").mkdir()
    (env["tmp"] / "home" / ".claude" / "CLAUDE.md").write_text("MARKER\n", encoding="utf-8")
    assert _doctor_rows(env)[0] == 0                    # OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1로 싣지 않는다
    events(env, final())
    tt(env, "--", "x")
    (c,) = run_calls(env)
    assert c["env"]["OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"] == "1"


def test_preflight_requires_bash_allow_list(env):
    env["cfg"].write_text(json.dumps({**CONFIG_OK, "permission": {"*": "deny", "task": "deny", "bash": "allow"}}),
                          encoding="utf-8")
    code, rows = _doctor_rows(env)
    assert code == 2 and 'permission.bash["*"]' in rows["opencode-config"]["detail"]


@pytest.mark.parametrize("evs,code,outcome", [
    ([ev("step_start"), tool("bash"), step("tool-calls")], 0, "no-final-text"),
    ([ev("step_start"), ev("text", text="   "), step()], 0, "no-final-text"),
    ([*final(), {"type": "error", "sessionID": "ses_TEST", "error": {"name": "APIError", "data": {"message": "boom"}}}], 0, "error"),
    (final(), 1, "error"),
    ([ev("step_start"), tool("jira_get_issue", "error", error="Model tried to call unavailable tool 'invalid'."),
      step("tool-calls"), *final()], 0, "ok"),
])
def test_outcomes(env, evs, code, outcome):
    events(env, evs)
    r = tt(env, "--json", "--", "x", extra_env={"STUB_EXIT": str(code)})
    out = json.loads(r.stdout)
    assert out["outcome"] == outcome
    assert r.returncode == {"ok": 0, "error": 1, "no-final-text": 1}[outcome]
    if outcome != "ok":
        assert "stub stderr line" in out["stderr_tail"]


def test_timeout_kills_and_reports(env):
    events(env, final())
    t0 = time.monotonic()
    r = tt(env, "--timeout", "1", "--json", "--", "x", extra_env={"STUB_SLEEP": "30"})
    assert time.monotonic() - t0 < 20
    assert r.returncode == 124 and json.loads(r.stdout)["outcome"] == "timeout"


def test_prints_screens_from_job_files_since_start(env):
    old = {"v": 1, "at": "2020-01-01T00:00:00.000Z", "script": "triage", "kind": "report", "job": "OLD-1",
           "lines": ["- 옛 리포트 줄"], "must_show": []}
    plat = env["work"] / "android"
    (plat / ".shown").mkdir(parents=True)
    (plat / ".shown" / "log.jsonl").write_text(json.dumps(old, ensure_ascii=False) + "\nnot json\n", encoding="utf-8")
    events(env, final("모델 요약"))
    r = tt(env, "--", "x", extra_env={"STUB_SHOWN": str(plat)})
    assert r.returncode == 0, r.stdout + r.stderr
    screens = r.stdout.split("모델을 거치지 않음) ----\n", 1)[1]
    assert screens.startswith("[report] ABC-1 (triage)\n- 분류 후보: C-1\nmust_show:\n- 분석 전용: 기록하지 않음\n")
    assert "옛 리포트 줄" not in r.stdout


def test_prints_evidence_screen(env):
    """B2 R19: check-output의 근거 원문 검사 기록(kind evidence)도 모델을 거치지 않고 줄 그대로 보인다."""
    import sys as _sys
    _sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import shown

    assert "evidence" in shown.LINE_KINDS and set(shown.LINE_KINDS) <= set(_load("tt_oc", TTOC).SHOWN_KINDS)
    plat = env["work"] / "ofono"
    (plat / ".shown").mkdir(parents=True)
    rec = {"v": 1, "at": "2999-01-01T00:00:00.000Z", "script": "triage", "kind": "evidence", "job": "ABC-2",
           "key": "evidence:ABC-2/deep", "lines": ["- 근거 원문 검사: 원문에 없음 1 — 근거 2"], "must_show": []}
    (plat / ".shown" / "log.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    events(env, final("모델 요약"))
    r = tt(env, "--", "x", extra_env={"STUB_SHOWN": str(plat)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[evidence] ABC-2 (triage)\n- 근거 원문 검사: 원문에 없음 1 — 근거 2" in r.stdout


def test_delete_session(env):
    events(env, final())
    r = tt(env, "--delete-session", "--", "x")
    assert r.returncode == 0 and "세션 삭제: 됨" in r.stdout and "이어서:" not in r.stdout
    assert [c["args"] for c in calls(env) if c["args"][:1] == ["session"]] == [["session", "delete", "ses_TEST"]]


def test_render_record_kinds():
    mod = _load("tt_oc", TTOC)
    assert mod.render_record({"kind": "push", "job": "J", "script": "db_pr", "block": "## 화면\n| a | b |\n"}) == \
        "[push] J (db_pr)\n## 화면\n| a | b |"
    assert mod.render_record({"kind": "draft", "job": "J", "script": "db_verify",
                              "rules": [{"id": "R1", "status": "pass", "reason": ""}]}) == "[draft] J (db_verify)\nR1 | pass | "
    now = datetime.now(timezone.utc).timestamp()
    assert mod._epoch("2026-11-05T00:00:00.000Z") < now
    assert mod.refused_env({"OPENCODE_EXPERIMENTAL_X": "1", "OPENCODE_PERMISSION": "", "OPENCODE_LOG_LEVEL": "INFO"}) == \
        ["OPENCODE_EXPERIMENTAL_X"]
