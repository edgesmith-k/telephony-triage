"""tests/skill_evals/run.py `-j N` (F, G의 81개 재측정용): 자식 `claude -p`만 병렬, 준비·채점·summary는 메인 스레드.

유료 호출은 없다. `build`·`prepare_plugin_mode`·`grade`는 가짜로 바꾸고, `execute`는 eval별로 잠깐 자고 정한 상태를 돌려주는
가짜를 쓴다. 마지막 테스트만 진짜 `execute`에 tmp_path의 가짜 `claude`(stream-json init·result를 내는 파이썬)를 붙인다.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "skill_evals"))       # run.py가 import하는 grade
spec = importlib.util.spec_from_file_location("skill_eval_run_parallel", REPO / "tests" / "skill_evals" / "run.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)

ENTRIES = [e for e in json.loads((REPO / "tests" / "skill_evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
           if all(e.get(k) for k in ("prompt", "setup", "user_replies", "assertions"))]
IDS = [e["id"] for e in ENTRIES[:5]]


def _fake_info(env_dir: Path, shared_home: Path | None = None) -> dict:
    home = shared_home or env_dir / "home"
    return {"env": {"TELEPHONY_TRIAGE_HOME": str(home), "MOCK_GH_STATE_DIR": str(env_dir / "gh"),
                    "MOCK_JIRA_DIR": str(env_dir / "jira"), "MOCK_JIRA_WRITE_LOG": str(env_dir / "jira-writes.json")},
            "path_prefix": [], "plugin_root": str(env_dir.parent / "plugin-root"), "skill": str(env_dir / "skill"),
            "issue_db_clone": str(env_dir / "ws" / "db" / "clone"), "work_dir": str(env_dir / "ws" / "work")}


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """가짜 준비·채점·실행. `state["plan"][eid] = (잠 초, 상태)`; 기록: 실행 순서·스레드."""
    state = {"plan": {}, "started": [], "threads": {"grade": set(), "summary": set(), "build": set(), "execute": set()},
             "shared_home": None, "live": 0, "max_live": 0}
    lock = threading.Lock()
    monkeypatch.setattr(evaluation.shutil, "which", lambda name, path=None: str(tmp_path / "claude-not-run"))
    monkeypatch.setattr(evaluation, "child_python_problem", lambda: None)

    def build(entry, env_dir, direct_tools=True):
        state["threads"]["build"].add(threading.get_ident())
        env_dir.mkdir(parents=True)
        (env_dir / "env.sh").write_text("# fake\n", encoding="utf-8")
        return _fake_info(env_dir, state["shared_home"])

    def prepare_plugin_mode(entry, info, env_dir):
        return {"plugin_dirs": [], "mcp_config": str(env_dir / "mcp.json"), "mcp_servers": []}

    def execute(entry, info, env_dir, run_dir, claude, timeout, plugin=None, model=None):
        eid = entry["id"]
        with lock:
            state["started"].append(eid)
            state["live"] += 1
            state["max_live"] = max(state["max_live"], state["live"])
        state["threads"]["execute"].add(threading.get_ident())
        sleep, status = state["plan"].get(eid, (0.01, "completed"))
        time.sleep(sleep)
        (env_dir / "bin").mkdir()
        outcome = {"status": status, "reason": f"가짜 {status}", "exit_code": 0, "tokens": {"total": 100 + eid},
                   "total_cost_usd": 0.01, "model": model}
        evaluation.dump(run_dir / "execution.json", outcome)
        with lock:
            state["live"] -= 1
        return outcome

    def grade(eid, run_dir, env_dir, assertions, *a, **k):
        state["threads"]["grade"].add(threading.get_ident())
        return {"status": "graded", "expectations": [{"passed": True}, {"passed": None}]}

    real_summary = evaluation.write_summary

    def write_summary(iteration, eid, batch, result):
        state["threads"]["summary"].add(threading.get_ident())
        return real_summary(iteration, eid, batch, result)

    for name, fn in (("build", build), ("prepare_plugin_mode", prepare_plugin_mode), ("execute", execute),
                     ("grade", grade), ("write_summary", write_summary)):
        monkeypatch.setattr(evaluation, name, fn)
    return state


def _tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def _run(tmp_path: Path, name: str, *extra: str, ids=None) -> tuple[int, Path]:
    it = tmp_path / name
    code = evaluation.main(["--iteration", str(it), "--eval", *map(str, ids or IDS), "--execute", *extra])
    return code, it


def test_parallel_layout_and_summary_equal_serial(tmp_path, fakes, capsys):
    """eval별 잠을 거꾸로 줘서 끝나는 순서가 섞여도 디렉토리 배치·summary.json·execution.json이 순차와 같다."""
    fakes["plan"] = {eid: (0.05 * (len(IDS) - i), "completed") for i, eid in enumerate(IDS)}
    code1, serial = _run(tmp_path, "serial")
    out1 = capsys.readouterr().out
    code3, par = _run(tmp_path, "par", "-j", "3")
    out3 = capsys.readouterr().out
    assert code1 == code3 == 0
    assert _tree(serial) == _tree(par)
    assert (serial / "summary.json").read_text(encoding="utf-8") == (par / "summary.json").read_text(encoding="utf-8")
    assert list(json.loads((par / "summary.json").read_text(encoding="utf-8"))) == [str(i) for i in sorted(IDS)]
    for eid in IDS:
        rel = f"eval-{eid}/with_skill/execution.json"
        assert (serial / rel).read_text(encoding="utf-8") == (par / rel).read_text(encoding="utf-8")
    assert sorted(ln for ln in out1.splitlines() if ln.startswith("eval ")) == \
        sorted(ln for ln in out3.splitlines() if ln.startswith("eval "))
    assert f"병렬 -j 3: 끝남 {len(IDS)} · 멈춤 0 · 실행 안 함 0" in out3
    assert fakes["max_live"] >= 2


@pytest.mark.parametrize("bad", ["blocked", "error", "timeout"])
def test_parallel_stop_on_non_completed_no_new_evals(tmp_path, fakes, capsys, bad):
    """첫 eval이 한도·인증(blocked)·error·timeout이면 새 eval을 시작하지 않는다. 이미 도는 eval은 끝까지 채점한다."""
    first, second, *rest = IDS
    fakes["plan"] = {first: (0.02, bad), second: (0.3, "completed")}
    code, it = _run(tmp_path, f"stop-{bad}", "-j", "2")
    out = capsys.readouterr().out
    assert code == 1
    assert fakes["started"] == [first, second]
    assert sorted(json.loads((it / "summary.json").read_text(encoding="utf-8"))) == sorted(map(str, [first, second]))
    for eid in rest:
        assert not (it / f"eval-{eid}").exists() and not (it / f"env-{eid}").exists()
    assert f"멈춤: eval {first} {bad} — 실행 안 함: {rest}" in out
    assert f"실행 안 함 {len(rest)}" in out


def test_jobs_1_never_creates_executor(tmp_path, fakes, monkeypatch):
    monkeypatch.setattr(evaluation.concurrent.futures, "ThreadPoolExecutor",
                        lambda *a, **k: pytest.fail("-j 1에서 스레드 풀을 만들었다"))
    code, it = _run(tmp_path, "one", "-j", "1")
    assert code == 0 and fakes["max_live"] == 1
    code, _ = _run(tmp_path, "default")
    assert code == 0


@pytest.mark.parametrize("jobs", ["0", "9", "-1"])
def test_jobs_validation(tmp_path, fakes, jobs):
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, "bad", "-j", jobs)
    assert exc.value.code == 2
    assert not (tmp_path / "bad").exists()


def test_prepare_only_accepts_jobs_and_runs_serially(tmp_path, fakes, capsys, monkeypatch):
    monkeypatch.setattr(evaluation.concurrent.futures, "ThreadPoolExecutor",
                        lambda *a, **k: pytest.fail("--prepare-only는 병렬로 돌지 않는다"))
    it = tmp_path / "prep"
    assert evaluation.main(["--iteration", str(it), "--eval", *map(str, IDS[:2]), "--prepare-only", "-j", "4"]) == 0
    out = capsys.readouterr().out
    assert "-j 4: --prepare-only는 순차로" in out and fakes["started"] == []
    assert all(json.loads((it / f"eval-{e}/with_skill/execution.json").read_text())["status"] == "prepared" for e in IDS[:2])


def test_isolation_guard_rejects_shared_home(tmp_path, fakes, capsys):
    """동시에 도는 두 eval이 같은 사용자 홈(TELEPHONY_TRIAGE_HOME)을 쓰면 둘째를 시작하지 않고 종료 2."""
    fakes["shared_home"] = tmp_path / "same-home"
    fakes["plan"] = {IDS[0]: (0.2, "completed")}
    code, it = _run(tmp_path, "clash", "-j", "2")
    err = capsys.readouterr().err
    assert code == 2
    assert fakes["started"] == [IDS[0]]
    assert "격리 실패" in err and "TELEPHONY_TRIAGE_HOME" in err
    assert not (it / f"eval-{IDS[2]}").exists()


def test_isolation_problem_unit(tmp_path):
    a = evaluation._isolation_paths(tmp_path / "it/eval-1/with_skill", tmp_path / "it/env-1", _fake_info(tmp_path / "it/env-1"))
    b = evaluation._isolation_paths(tmp_path / "it/eval-2/with_skill", tmp_path / "it/env-2", _fake_info(tmp_path / "it/env-2"))
    assert evaluation._isolation_problem([(1, a), (2, b)]) is None
    c = dict(b, MOCK_JIRA_DIR=a["MOCK_JIRA_DIR"])
    assert "MOCK_JIRA_DIR" in evaluation._isolation_problem([(1, a), (2, c)])


def test_main_thread_only_prepares_grades_and_writes_summary(tmp_path, fakes):
    main = threading.get_ident()
    code, _ = _run(tmp_path, "threads", "-j", "3")
    assert code == 0
    assert fakes["threads"]["build"] == {main}
    assert fakes["threads"]["grade"] == {main} and fakes["threads"]["summary"] == {main}
    assert main not in fakes["threads"]["execute"]


def test_duplicate_eval_ids_rejected(tmp_path, fakes):
    with pytest.raises(SystemExit) as exc:
        evaluation.main(["--iteration", str(tmp_path / "dup"), "--eval", str(IDS[0]), str(IDS[0]), "--execute", "-j", "2"])
    assert exc.value.code == 2


@pytest.mark.skipif(sys.platform == "win32", reason="가짜 claude는 shebang 실행 파일")
def test_real_execute_with_fake_claude_script(tmp_path, monkeypatch, capsys):
    """진짜 `execute`(direct 모드) + 가짜 claude: 두 eval이 동시에 돌아 둘 다 completed, 토큰 기록, env 디렉토리는 따로."""
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    init = {"type": "system", "subtype": "init", "session_id": "s", "model": "fake-model"}
    result = {"type": "result", "subtype": "success", "is_error": False, "result": "ok", "num_turns": 1,
              "total_cost_usd": 0.25, "usage": {"input_tokens": 10, "output_tokens": 90, "cache_read_input_tokens": 0,
                                                "cache_creation_input_tokens": 0}}
    fake.write_text(f"#!{sys.executable}\nimport sys, time\nsys.stdin.read()\ntime.sleep(0.3)\n"
                    f"print({json.dumps(init)!r})\nprint({json.dumps(result)!r})\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(evaluation.shutil, "which", lambda name, path=None: str(fake))
    monkeypatch.setattr(evaluation, "child_python_problem", lambda: None)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(evaluation, "repo_state", lambda *a, **k: (None, None))

    def build(entry, env_dir, direct_tools=True):
        env_dir.mkdir(parents=True)
        (env_dir / "env.sh").write_text("# fake\n", encoding="utf-8")
        return _fake_info(env_dir)

    monkeypatch.setattr(evaluation, "build", build)
    monkeypatch.setattr(evaluation, "grade", lambda *a, **k: {"status": "graded", "expectations": [{"passed": True}]})
    it = tmp_path / "real"
    start = time.monotonic()
    code = evaluation.main(["--iteration", str(it), "--eval", *map(str, IDS[:2]), "--execute", "--mode", "direct", "-j", "2"])
    elapsed = time.monotonic() - start
    assert code == 0, capsys.readouterr()
    for eid in IDS[:2]:
        saved = json.loads((it / f"eval-{eid}/with_skill/execution.json").read_text(encoding="utf-8"))
        assert saved["status"] == "completed" and saved["init_model"] == "fake-model"
        assert saved["tokens"]["usage_total"] == 100 and saved["total_cost_usd"] == 0.25
        assert (it / f"env-{eid}" / "bin" / "python3").is_file()
    assert os.path.realpath(it / f"env-{IDS[0]}") != os.path.realpath(it / f"env-{IDS[1]}")
    assert elapsed < 5
    assert evaluation._LIVE == set()
