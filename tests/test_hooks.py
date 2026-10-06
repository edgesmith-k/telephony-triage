#!/usr/bin/env python3
"""Phase 8 완료 기준 확인: git hooks(pre-commit·pre-push)와 Claude hooks (11-phases.md Phase 8, 08-safety.md §9).

- git hook: 작업공간(`tests/helpers/workspace.py`)의 사용자 clone은 `core.hooksPath .githooks`이고 config의
  `plugin.scripts_path`는 테스트 헬퍼 플러그인 루트의 `scripts`다. 커밋·push는 `ws.hook_env()`로 부른다
  (hook이 이 작업공간의 config를 읽게).
- Claude hook: `guard.py`에 hook 입력 JSON을 stdin으로 주고 권한 결정 JSON을 본다. 실제 Claude Code 세션에서의
  동작(도구 이름 형식, 결정 필드)은 빈 플러그인 실험(S1)으로 확인한다.

`pytest tests/test_hooks.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root, run, tmp  # noqa: E402
from workspace import GIT_ID, Workspace, git  # noqa: E402

DATA_DIR = "data/DATA-001-no-setup-data-call"
JIRA_TOOLS = ["mcp__mock-jira__jira_fetch_ticket", "mcp__mock-jira__jira_query_tickets",
              "mcp__mock-jira__jira_ticket_comments"]

_WS: Workspace | None = None


def shared() -> Workspace:
    """guard 판정만 보는 테스트가 함께 쓰는 작업공간 (clone을 바꾸지 않는 테스트만)."""
    global _WS
    if _WS is None:
        _WS = Workspace()
        _WS.json("config.py", ["set-jira", "--server", "mock-jira", "--get-issue", JIRA_TOOLS[0],
                               "--search-issues", JIRA_TOOLS[1], "--get-comments", JIRA_TOOLS[2]])
    return _WS


def gitp(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """실패를 허용하는 git 호출 (hook 거부를 본다)."""
    return subprocess.run(["git", "-C", str(repo), *GIT_ID, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)


def guard(ws: Workspace | None, tool: str, tool_input: dict, cwd: Path, env: dict | None = None) -> dict | None:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
    proc = run("guard.py", [], root=ws.root if ws else plugin_root(), cwd=cwd,
               env=env if env is not None else ws.env(), stdin=json.dumps(event))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None


def bash(ws: Workspace, command: str, cwd: Path, **kw) -> dict | None:
    return guard(ws, "Bash", {"command": command}, cwd, **kw)


def decision(out: dict | None) -> str | None:
    return out and out["permissionDecision"]


def branch_with_change(ws: Workspace, name: str, rel: str, text: str) -> None:
    """이전 변경을 버리고 origin/main에서 `name` 브랜치를 만들어 `rel` 하나만 바꿔 staged로 둔다."""
    git(ws.clone, "reset", "-q", "--hard")
    git(ws.clone, "checkout", "-q", "-B", name, "origin/main")
    path = ws.clone / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    git(ws.clone, "add", "-A")


# -- git pre-commit -----------------------------------------------------------------------------


def test_precommit_blocks_manual_readme_pii_and_bad_scripts_path():
    ws = Workspace()
    readme = (ws.clone / "README.md").read_text(encoding="utf-8")
    branch_with_change(ws, "review/data-2026-10", "README.md", readme + "\n손으로 고친 줄\n")
    proc = gitp(ws.clone, "commit", "-qm", "README 직접 수정", env=ws.hook_env())
    assert proc.returncode != 0 and "README.md" in proc.stderr and "db_build.py --write" in proc.stderr

    # PII: Jira 기록 note에 원본 IMEI
    jira = (ws.clone / DATA_DIR / "jira" / "MOCK-1101.yaml").read_text(encoding="utf-8")
    branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/jira/MOCK-1101.yaml",
                       jira.replace("접수됨", "접수됨 imei=490154203237518"))
    proc = gitp(ws.clone, "commit", "-qm", "PII", env=ws.hook_env())
    assert proc.returncode != 0 and "mask" in proc.stderr and "IMEI" in proc.stderr

    # 정상 변경은 통과한다 (마스킹된 note)
    branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/jira/MOCK-1101.yaml",
                       jira.replace("접수됨", "접수됨 (<IMEI#1>)"))
    proc = gitp(ws.clone, "commit", "-qm", "정상", env=ws.hook_env())
    assert proc.returncode == 0, proc.stderr

    # scripts_path 무효 / 없음 / config 없음 → 차단과 안내
    cfg_path = ws.home / "config.yaml"
    good = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    for mutate, needle in ((lambda c: c["plugin"].update(scripts_path=str(ws.base / "nowhere")), "무효"),
                           (lambda c: c.pop("plugin"), "plugin.scripts_path가 없다"),
                           (None, "config가 없다")):
        if mutate is None:
            cfg_path.unlink()
        else:
            bad = json.loads(json.dumps(good))
            mutate(bad)
            cfg_path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
        branch_with_change(ws, "issue/MOCK-1102", "CONTRIBUTING.md", "편집\n")
        proc = gitp(ws.clone, "commit", "-qm", "경로", env=ws.hook_env())
        assert proc.returncode != 0 and needle in proc.stderr and "/telephony-triage:setup" in proc.stderr
    cfg_path.write_text(yaml.safe_dump(good, allow_unicode=True), encoding="utf-8")


def test_precommit_in_worktree_checks_that_worktree():
    ws = Workspace()
    # 사용자 clone에는 README 직접 수정이 staged로 남아 있다
    branch_with_change(ws, "review/data-2026-10", "README.md", "망가진 README\n")
    wt = ws.work / "wt-check"
    git(ws.clone, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    (wt / "CONTRIBUTING.md").write_text("worktree 편집\n", encoding="utf-8", newline="\n")
    git(wt, "add", "-A")
    proc = gitp(wt, "commit", "-qm", "worktree 커밋", env=ws.hook_env())
    assert proc.returncode == 0, proc.stderr          # clone의 망가진 README를 보지 않는다
    (wt / "README.md").write_text("worktree에서 망가뜨림\n", encoding="utf-8", newline="\n")
    git(wt, "add", "-A")
    proc = gitp(wt, "commit", "-qm", "worktree README", env=ws.hook_env())
    assert proc.returncode != 0 and "README.md" in proc.stderr
    gitp(ws.clone, "worktree", "remove", "--force", str(wt))


def test_precommit_needs_approval_warns_and_passes():
    ws = Workspace()
    type_md = ws.clone / DATA_DIR / "type.md"
    branch_with_change(ws, "review/data-2026-10", f"{DATA_DIR}/type.md",
                       type_md.read_text(encoding="utf-8") + "\n보충 설명 한 줄.\n")
    proc = gitp(ws.clone, "commit", "-qm", "규칙 파일 변경", env=ws.hook_env(TT_FORCE_VERIFY_EXIT="3"))
    assert proc.returncode == 0, proc.stderr
    assert "승인 필요" in proc.stderr and "needs-approval" in proc.stderr


# -- git pre-push ---------------------------------------------------------------------------------


def test_prepush_token_and_base_branch():
    ws = Workspace()
    branch_with_change(ws, "review/data-2026-10", "CONTRIBUTING.md", "직접 편집\n")
    assert gitp(ws.clone, "commit", "-qm", "직접 편집", env=ws.hook_env()).returncode == 0

    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/review/data-2026-10", env=ws.hook_env())
    assert proc.returncode != 0 and "TT_PUBLISH_TOKEN이 없다" in proc.stderr
    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/review/data-2026-10",
                env=ws.hook_env(TT_PUBLISH_TOKEN="0" * 40))
    assert proc.returncode != 0 and "approved_hash" in proc.stderr
    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/main", env=ws.hook_env(TT_PUBLISH_TOKEN="manual"))
    assert proc.returncode != 0 and "base 브랜치(main)" in proc.stderr
    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/review/data-2026-10",
                env=ws.hook_env(TT_PUBLISH_TOKEN="manual"))
    assert proc.returncode == 0, proc.stderr

    # guard를 지나치는 python -c 의 main push도 pre-push가 거부한다
    code = ("import subprocess,sys; sys.exit(subprocess.run(['git','push','-q','origin',"
            "'HEAD:refs/heads/main']).returncode)")
    assert decision(bash(ws, f'python3 -c "{code}"', ws.clone)) is None
    proc = subprocess.run([sys.executable, "-c", code], cwd=ws.clone, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=ws.hook_env(TT_PUBLISH_TOKEN="manual"))
    assert proc.returncode != 0 and "base 브랜치(main)" in proc.stderr

    # db_pr publish의 push는 통과한다 (토큰 = state.json approved_hash)
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    out = ws.ship("MOCK-7001", "issue/MOCK-7001", discard=False)
    assert out["publish"]["pushed"] is True
    # 승인 해시로 다른 브랜치나 다른 트리를 올릴 수 없다
    wt = ws.wt("MOCK-7001")
    token = out["summary"]["approved_hash"]
    proc = gitp(wt, "push", "-q", "origin", "HEAD:refs/heads/issue/OTHER-1", env=ws.hook_env(TT_PUBLISH_TOKEN=token))
    assert proc.returncode != 0 and "승인된 작업의 브랜치" in proc.stderr
    proc = gitp(ws.clone, "push", "-q", "-f", "origin", "HEAD:refs/heads/issue/MOCK-7001",
                env=ws.hook_env(TT_PUBLISH_TOKEN=token))
    assert proc.returncode != 0 and "트리가 승인 해시와 다르다" in proc.stderr
    ws.db_pr("discard", wt)


# -- Claude hook: Bash ---------------------------------------------------------------------------


def test_guard_blocks_hook_bypass_and_hookspath_changes():
    ws = shared()
    c = ws.clone
    for cmd in ('git commit --no-verify -m "x"', 'git commit -n -m "x"', 'git commit -anm "x"',
                'git commit --no-veri -m x', 'git -c core.hooksPath=/dev/null commit -m x',
                'git -c CORE.HOOKSPATH= commit -m x', f'cd "{c}" && git commit --no-verify -m x',
                f'git -C "{c}" commit -n -m x', f'bash -c "cd \'{c}\' && git commit --no-verify -m x"',
                'git config core.hooksPath hooks', 'git config --unset core.hooksPath',
                'git config unset core.hooksPath', 'git config --local core.hooksPath ""',
                'git config --remove-section core', 'git push --no-verify origin HEAD:refs/heads/issue/X-1'):
        out = bash(ws, cmd, c if not cmd.startswith(("cd ", "git -C", "bash -c")) else ws.base)
        assert decision(out) == "deny", cmd
    # `-m` 값 안의 n은 no-verify가 아니다. 정확히 .githooks로 설정하는 명령은 허용(setup 재실행)
    for cmd in ('git config core.hooksPath .githooks', 'git config --get core.hooksPath',
                'git config core.hooksPath', 'git status', 'git log -n 3'):
        assert decision(bash(ws, cmd, c)) is None, cmd
    assert ws.json("config.py", ["install-hooks", "--db", c])["core.hooksPath"] == ".githooks"


def test_guard_commit_requires_exact_hookspath():
    ws = Workspace()
    branch_with_change(ws, "review/data-2026-10", "CONTRIBUTING.md", "편집\n")
    assert decision(bash(ws, 'git commit -m "ok"', ws.clone)) is None
    for value in (None, "hooks", ".githooks/"):
        if value is None:
            git(ws.clone, "config", "--unset", "core.hooksPath")
        else:
            git(ws.clone, "config", "core.hooksPath", value)
        out = bash(ws, 'git commit -m "x"', ws.clone)
        assert decision(out) == "deny" and "/telephony-triage:setup" in out["permissionDecisionReason"], value
    ws.json("config.py", ["install-hooks", "--db", ws.clone])
    # worktree도 같은 설정을 공유한다
    wt = ws.work / "wt-guard"
    git(ws.clone, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    assert decision(bash(ws, "git commit --no-verify -m x", wt)) == "deny"
    gitp(ws.clone, "worktree", "remove", "--force", str(wt))


def test_guard_commit_checks_pii_and_generated_files():
    ws = Workspace()
    jira = ws.clone / DATA_DIR / "jira" / "MOCK-1101.yaml"
    branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/jira/MOCK-1101.yaml",
                       jira.read_text(encoding="utf-8").replace("접수됨", "접수됨 imei=490154203237518"))
    out = bash(ws, 'git commit -m "x"', ws.clone)
    assert decision(out) == "deny" and "규칙 3" in out["permissionDecisionReason"]
    branch_with_change(ws, "review/data-2026-10", "README.md", "직접 수정\n")
    out = bash(ws, 'git commit -m "x"', ws.clone)
    assert decision(out) == "deny" and "규칙 4" in out["permissionDecisionReason"]
    git(ws.clone, "reset", "-q", "--hard")
    (ws.clone / ".cache").mkdir(exist_ok=True)
    (ws.clone / ".cache" / "x.json").write_text("{}\n", encoding="utf-8")
    git(ws.clone, "add", "-f", ".cache/x.json")
    out = bash(ws, 'git commit -m "x"', ws.clone)
    assert decision(out) == "deny" and ".cache/" in out["permissionDecisionReason"]
    git(ws.clone, "reset", "-q", "--hard")


def test_guard_push_rules():
    ws = shared()
    c = ws.clone
    for cmd in ("git push origin HEAD:refs/heads/main", "git push origin main", "git push origin +HEAD:main",
                "git push --all origin", "git push origin :", "git push --delete origin main",
                f'cd "{c}" && git push origin HEAD:refs/heads/main'):
        out = bash(ws, cmd, c if not cmd.startswith("cd ") else ws.base)
        assert decision(out) == "deny", cmd
    # 현재 브랜치가 main이면 refspec 없는 push도 main push다
    assert git(c, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert decision(bash(ws, "git push", c)) == "deny"
    # 그 밖의 이슈 DB push와 db_pr publish는 확인(ask)
    assert decision(bash(ws, "git push origin HEAD:refs/heads/issue/MOCK-1", c)) == "ask"
    publish = f'python3 "{ws.root}/scripts/db_pr.py" publish wt --branch issue/MOCK-1 --lease new --approved x'
    assert decision(bash(ws, publish, ws.base)) == "ask"


def test_guard_publish_with_commit_and_discard_still_asks():
    """W5: `publish --commit --and-discard`도 `publish` 토큰 때문에 ask다 (옵션 이름과 무관)."""
    ws = shared()
    db_pr = f'python3 "{ws.root}/scripts/db_pr.py"'
    base = "publish wt --branch issue/MOCK-1 --lease new --approved x"
    for tail in ("--commit", "--and-discard", "--commit --and-discard", "--and-discard --commit"):
        out = bash(ws, f"{db_pr} {base} {tail}", ws.base)
        assert decision(out) == "ask" and "publish" in out["permissionDecisionReason"], tail


def test_guard_stage_then_summary_and_discard_are_not_asked():
    """W5: `stage --then-summary`와 단독 `discard`는 판정할 것이 없다 (publish만 ask)."""
    ws = shared()
    db_pr = f'python3 "{ws.root}/scripts/db_pr.py"'
    for cmd in (f"{db_pr} stage plan.json --wt wt --branch issue/MOCK-1 --then-summary",
                f"{db_pr} summary wt --format markdown", f"{db_pr} discard wt"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd


def test_guard_ignores_other_repos_and_missing_config():
    ws = shared()
    other = tmp("tt-other-repo-") / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
    for cmd in ("git commit --no-verify -m x", "git push origin HEAD:refs/heads/main", "git push",
                "git config core.hooksPath x", "git config --unset core.hooksPath",
                "git -c core.hooksPath=/dev/null commit -m x"):
        assert decision(bash(ws, cmd, other)) is None, cmd
    # 다른 레포의 파일 쓰기도 영향 없음
    assert decision(guard(ws, "Write", {"file_path": str(other / "a.txt"), "content": "x"}, other)) is None
    # 사용자 config가 없으면 이슈 DB에서도 git 규칙을 적용하지 않는다
    empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}
    for cmd in ("git commit --no-verify -m x", "git push origin HEAD:refs/heads/main"):
        assert decision(bash(ws, cmd, ws.clone, env=empty)) is None, cmd
    assert decision(guard(ws, "Write", {"file_path": str(ws.clone / "README.md")}, ws.clone, env=empty)) is None


# -- Claude hook: Jira, 파일 도구 ----------------------------------------------------------------


def test_guard_jira_read_only_by_server():
    ws = shared()
    for tool in JIRA_TOOLS:
        assert decision(guard(ws, tool, {}, ws.base)) is None, tool
    for tool in ("mcp__mock-jira__jira_add_comment", "mcp__mock-jira__jira_transition_ticket"):
        out = guard(ws, tool, {}, ws.base)
        assert decision(out) == "deny" and "Jira 읽기 전용" in out["permissionDecisionReason"]
    # 다른 MCP 서버 도구는 영향이 없다 (쓰기처럼 보이는 이름이어도)
    for tool in ("mcp__other-server__create_issue", "mcp__mock-jira-2__jira_add_comment"):
        assert decision(guard(ws, tool, {}, ws.base)) is None, tool
    # read_tools가 비어 있으면 그 서버 도구는 모두 거부
    cfg_path = ws.home / "config.yaml"
    saved = cfg_path.read_text(encoding="utf-8")
    try:
        ws.json("config.py", ["set", "jira.read_tools", "[]"])
        assert decision(guard(ws, JIRA_TOOLS[0], {}, ws.base)) == "deny"
    finally:
        cfg_path.write_text(saved, encoding="utf-8")
    # jira.mcp_server가 비어 있으면 적용하지 않고 경고만 (setup 전)
    root = plugin_root("no-jira-server", jira={"exclude_servers": []})
    home = tmp("tt-home-")
    event = {"tool_name": "mcp__mock-jira__jira_add_comment", "tool_input": {}, "cwd": str(ws.base)}
    proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home}, stdin=json.dumps(event))
    assert proc.returncode == 0 and not proc.stdout.strip() and "jira.mcp_server" in proc.stderr


def test_guard_blocks_file_tools_in_user_clone_only():
    ws = shared()
    type_md = ws.clone / DATA_DIR / "type.md"
    for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"),
                      ("NotebookEdit", "notebook_path")):
        out = guard(ws, tool, {key: str(type_md)}, ws.base)
        assert decision(out) == "deny" and "직접 편집은 사용자가 한다" in out["permissionDecisionReason"], tool
    # 상대 경로도 cwd 기준으로 판정
    assert decision(guard(ws, "Write", {"file_path": f"{DATA_DIR}/type.md"}, ws.clone)) == "deny"
    # 작업 worktree·draft·스냅샷(<work_dir> 아래)은 허용
    for rel in (f"MOCK-7001/wt/{DATA_DIR}/type.md", "MOCK-7001/draft/README.md", "_snapshot/README.md",
                "MOCK-7001/plan.json"):
        assert decision(guard(ws, "Write", {"file_path": str(ws.work / rel)}, ws.base)) is None, rel


LOGCAT = "".join(f"10-06 12:00:{i:02d}.123  1000  1000 I RILJ    : [0001] line {i}\n" for i in range(40))


def test_guard_blocks_whole_raw_log_reads():
    ws = shared()
    d = tmp("tt-raw-")
    (d / "logs").mkdir()
    (d / "x.log").write_text(LOGCAT, encoding="utf-8")
    (d / "logs" / "a.log").write_text(LOGCAT, encoding="utf-8")
    (d / "a.txt").write_text("hello\n", encoding="utf-8")
    (d / "br.zip").write_bytes(b"PK\x03\x04" + b"\0" * 100)
    (d / "jira_raw.json").write_text("{}", encoding="utf-8")
    for name in ("timeline.md", "report.md", "commit-message.txt"):
        (d / name).write_text("text\n", encoding="utf-8")
    fx = ws.work / "JOB" / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / "X.log").write_text(LOGCAT, encoding="utf-8")
    deny = ["cat x.log", "cat a.txt x.log", "cat < x.log", 'sh -c "cat x.log"', "cat logs/*.log",
            "head -c 5000 x.log", "tail -c5000 x.log", "unzip -p br.zip", "unzip -pq br.zip", "strings br.zip",
            f"cat {d}/jira_raw.json", "echo hi && cat x.log",
            # 모든 줄에 맞는 패턴·스크립트는 통독과 같다
            'grep "" x.log', 'grep -n "" x.log', "grep -n '' x.log | head -40", "grep '.*' x.log", "grep -e '' x.log",
            "grep '^' x.log", "grep -n '$' x.log", "grep . x.log", "rg '' x.log", "grep -n '' < x.log",
            "awk '{print}' x.log", "awk 1 x.log", "awk '1' x.log", "awk '{print $0}' x.log",
            "sed -n p x.log", "sed -n 'p' x.log", "sed -n '1,$p' x.log", "sed '' x.log", "sed -e '' x.log",
            'sh -c "grep -n \'\' x.log"']
    for cmd in deny:
        out = bash(ws, cmd, d)
        assert decision(out) == "deny", cmd
        assert "규칙 10" in out["permissionDecisionReason"], cmd
    allow = ["grep -n RILJ x.log", "sed -n 1,20p x.log", "head -n 20 x.log", "wc -l x.log", "unzip -l br.zip",
             f"cat {fx}/X.log", "cat timeline.md", "cat report.md", "cat commit-message.txt",
             "cat <<EOF > x.log\nhi\nEOF", "cat nonexistent.log", "cat a.txt", "echo hi > x.log",
             # 실제 패턴·구간 제한·개수만 내는 형태는 통과
             "grep -n RILJ x.log", "grep -c '' x.log", "grep -v '^$' x.log", "grep -n '' a.txt", f"grep -n '' {fx}/X.log",
             "awk '{print $5}' x.log", "awk '/RILJ/' x.log", "sed -n 1,200p x.log", "sed -n '5,$p' x.log",
             "sed 's/a/b/' x.log", "sed -n '/RILJ/p' x.log"]
    for cmd in allow:
        assert decision(bash(ws, cmd, d)) is None, cmd
    # 사용자 config가 없어도 적용된다
    assert decision(guard(None, "Bash", {"command": "cat x.log"}, d, env={**ws.env(), "HOME": str(d)})) == "deny"


def _raw_guard(raw_read, cmd: str, cwd: Path):
    root = plugin_root(**({"guard": {"raw_read": raw_read}} if raw_read is not None else {}))
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
    proc = run("guard.py", [], root=root, cwd=cwd, env=shared().env(), stdin=json.dumps(event))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
    return decision(out), proc.stderr


def test_guard_raw_read_site_defaults_extend_builtins():
    d = tmp("tt-rawsite-")
    (d / "extra").mkdir()
    (d / "mine.dat").write_text("x", encoding="utf-8")
    (d / "extra" / "x.log").write_text(LOGCAT, encoding="utf-8")
    (d / "x.log").write_text(LOGCAT, encoding="utf-8")
    site = {"names": ["mine.dat"], "exempt_dirs": ["extra"]}
    assert _raw_guard(None, "cat mine.dat", d)[0] is None                  # 키 없음 = 내장만
    assert _raw_guard(None, "cat extra/x.log", d)[0] == "deny"
    assert _raw_guard(site, "cat mine.dat", d)[0] == "deny"                # 이름 추가
    assert _raw_guard(site, "cat extra/x.log", d)[0] is None               # 제외 디렉토리 추가
    assert _raw_guard(site, "cat x.log", d)[0] == "deny"                   # 내장 판별 유지


def test_guard_raw_read_bad_site_value_warns_and_uses_builtins():
    d = tmp("tt-rawbad-")
    (d / "x.log").write_text(LOGCAT, encoding="utf-8")
    kind, err = _raw_guard({"names": "mine.dat"}, "cat x.log", d)
    assert kind == "deny" and "guard.raw_read" in err


def test_hooks_json_has_eight_rules_wired_to_guard():
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert "sync-scripts-path" in hooks["SessionStart"][0]["hooks"][0]["command"]
    matchers = {h["matcher"]: h["hooks"][0]["command"] for h in hooks["PreToolUse"]}
    assert set(matchers) == {"mcp__.*", "Bash", "Write|Edit|MultiEdit|NotebookEdit"}
    assert all("${CLAUDE_PLUGIN_ROOT}/scripts/guard.py" in cmd for cmd in matchers.values())


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
