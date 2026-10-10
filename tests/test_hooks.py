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


def test_guard_jira_named_servers_deny_writes():
    ws = shared()
    for tool in JIRA_TOOLS:
        assert decision(guard(ws, tool, {}, ws.base)) is None, tool
    for tool in ("mcp__mock-jira__jira_add_comment", "mcp__mock-jira__jira_transition_ticket"):
        out = guard(ws, tool, {}, ws.base)
        assert decision(out) == "deny" and "Jira 읽기 전용" in out["permissionDecisionReason"]
    # 다른 MCP 서버 도구는 영향이 없다 (쓰기처럼 보이는 이름이어도, 대상 레포 인자가 없으면)
    assert decision(guard(ws, "mcp__other-server__create_issue", {}, ws.base)) is None
    # 설정되지 않은 서버라도 이름에 jira/atlassian이 들면 쓰기형 도구는 거부, 읽기형은 통과
    for tool in ("mcp__jira-prod__add_comment", "mcp__atlassian__transition_issue", "mcp__mock-jira-2__jira_add_comment"):
        out = guard(ws, tool, {}, ws.base)
        assert decision(out) == "deny" and "Jira/Atlassian" in out["permissionDecisionReason"], tool
    assert decision(guard(ws, "mcp__atlassian__search_issues", {}, ws.base)) is None
    # read_tools가 비어 있으면 그 서버 도구는 모두 거부
    cfg_path = ws.home / "config.yaml"
    saved = cfg_path.read_text(encoding="utf-8")
    try:
        ws.json("config.py", ["set", "jira.read_tools", "[]"])
        assert decision(guard(ws, JIRA_TOOLS[0], {}, ws.base)) == "deny"
    finally:
        cfg_path.write_text(saved, encoding="utf-8")
    # jira.mcp_server가 비어 있어도(setup 전) 이름 기반 거부는 적용하고 경고한다
    root = plugin_root("no-jira-server", jira={"exclude_servers": []})
    home = tmp("tt-home-")
    for tool, want in (("mcp__mock-jira__jira_add_comment", "deny"), ("mcp__mock-jira__jira_fetch_ticket", None)):
        event = {"tool_name": tool, "tool_input": {}, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home}, stdin=json.dumps(event))
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert proc.returncode == 0 and decision(out) == want and "jira.mcp_server" in proc.stderr, tool


def _jira(server: str, get_issue: str) -> dict:
    """테스트 헬퍼 site-defaults의 jira 블록에서 서버·get_issue 이름만 바꾼 것."""
    base = yaml.safe_load((REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8"))["jira"]
    return {**base, "mcp_server": server, "exclude_servers": [], "tools": {"get_issue": get_issue},
            "read_tools": [get_issue]}


def test_guard_jira_server_name_is_normalized():
    """R-2: 세션 도구 이름은 서버 이름의 `[^A-Za-z0-9_-]`를 `_`로 쓴다(관측 기반 추정, S1 확인). 플러그인 번들 서버는
    `mcp__plugin_…` 접두사라 `jira.mcp_server`와 다르다 — `jira.tools` 이름의 접두사로도 판정한다."""
    home = tmp("tt-home-")

    def judge(root: Path, tool: str) -> str | None:
        event = {"tool_name": tool, "tool_input": {}, "cwd": str(home)}
        proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home}, stdin=json.dumps(event))
        assert proc.returncode == 0, proc.stderr
        return decision(json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None)

    dot = plugin_root("jira-dot", jira=_jira("jira.corp", "mcp__jira.corp__get_issue"))
    assert judge(dot, "mcp__jira_corp__create_issue") == "deny"
    assert judge(dot, "mcp__jira.corp__create_issue") == "deny"
    assert judge(dot, "mcp__jira_corp__get_issue") is None
    bundled = plugin_root("jira-bundled", jira=_jira("jira", "mcp__plugin_corp_jira__get_issue"))
    assert judge(bundled, "mcp__plugin_corp_jira__add_comment") == "deny"
    assert judge(bundled, "mcp__plugin_corp_jira__get_issue") is None
    assert judge(bundled, "mcp__jira__add_comment") == "deny"          # mcp_server 접두사도 그대로
    assert judge(bundled, "mcp__other__add_comment") is None


def test_guard_sees_through_command_wrappers():
    """R-3: 앞 래퍼(timeout·nice·stdbuf·sudo·ionice·setsid·exec -a·env -u/-S/-C·time -p)를 풀어 규칙 3~7·10을 판정한다."""
    ws = shared()
    c = ws.clone
    publish = f'python3 "{ws.root}/scripts/db_pr.py" publish wt --branch issue/MOCK-1 --lease new --approved x'
    for prefix in ("timeout 600", "nice -n 5", "nice -5", "stdbuf -oL", "stdbuf -o L", "sudo -u x",
                   "/usr/bin/timeout --signal=KILL 5", "ionice -c 2 -n 7", "setsid", "exec -a y", "time -p",
                   "env -u FOO", "FOO=1 timeout -k 5 60 nohup"):
        assert decision(bash(ws, f"{prefix} {publish}", ws.base)) == "ask", prefix
    assert decision(bash(ws, 'env -S "python3 db_pr.py publish wt"', ws.base)) == "ask"
    assert decision(bash(ws, "env --split-string='python3 db_pr.py publish wt'", ws.base)) == "ask"
    for cmd in ("time -p git commit --no-verify -m x", "env -u FOO git push origin HEAD:main",
                "timeout -k 5 60 git push origin HEAD:main", "nice git -c core.hooksPath=/dev/null commit -m x",
                'env -S "git push origin HEAD:main"', "sudo -u x git commit -n -m x",
                # 짧은 옵션 묶음 끝의 값 옵션(-Eu x)과 묶음 안의 -S
                "sudo -Eu x git commit --no-verify -m x", "sudo -Hu x git push origin HEAD:main",
                'env -vS "git push origin HEAD:main"', "env -uFOO git push origin HEAD:main"):
        assert decision(bash(ws, cmd, c)) == "deny", cmd
    assert decision(bash(ws, f"sudo -Eu x {publish}", ws.base)) == "ask"
    # env -C·sudo -D는 작업 디렉토리를 바꾼다(값이 붙은 형태 포함): 다른 곳에서 불러도 이슈 DB로 판정한다
    for cmd in (f'env -C "{c}" git push origin HEAD:main', f'sudo -D "{c}" git push origin HEAD:main',
                f'env -C"{c}" git push origin HEAD:main', f'sudo -D"{c}" git push origin HEAD:main',
                f'env --chdir="{c}" git push origin HEAD:main'):
        assert decision(bash(ws, cmd, ws.base)) == "deny", cmd
    d = tmp("tt-wrap-raw-")
    (d / "x.log").write_text(LOGCAT, encoding="utf-8")
    for cmd in ("timeout 5 cat x.log", "nice -n 1 grep '' x.log", "env -u X stdbuf -oL cat x.log"):
        out = bash(ws, cmd, d)
        assert decision(out) == "deny" and "규칙 10" in out["permissionDecisionReason"], cmd
    assert decision(bash(ws, "timeout 5 grep -n RILJ x.log", d)) is None


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
    for bad in ({"names": "mine.dat"}, {"cmds": ["view"]}, {"names": ["a/b.log"]}):
        kind, err = _raw_guard(bad, "cat x.log", d)
        assert kind == "deny" and "guard.raw_read" in err, bad


# -- Claude hook: gh·MCP 이슈 DB 쓰기 (11), clone 불변 (8), 파서 빈틈, 의존성 없음 ---------------------

DB_SLUG = "mock-org/telephony-issue-db"


def _repo_with_origin(url: str) -> Path:
    path = tmp("tt-gh-repo-") / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", url], check=True)
    return path


def test_guard_gh_write_only_for_issue_db_repo():
    ws = shared()
    c = ws.clone
    plugin_repo = _repo_with_origin("https://ghe.mock.invalid/other/repo")
    wt = ws.work / "wt-gh"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    try:
        cases = [("gh pr list --state open", c, None),
                 (f"gh pr create -R {DB_SLUG} -t x", plugin_repo, "ask"),
                 (f"gh pr create -R {DB_SLUG} -t x", ws.base, "ask"),
                 ("gh pr create -t x", plugin_repo, None),
                 ("gh pr merge 12 --admin", wt, "deny"),
                 (f"gh api -X PUT repos/{DB_SLUG}/contents/x", plugin_repo, "ask"),
                 (f"gh api repos/{DB_SLUG}/pulls", plugin_repo, None),
                 ("gh api -X PUT repos/other/repo/contents/x", c, None),
                 (f"GH_REPO=ghe.mock.invalid/{DB_SLUG} gh issue comment 1 -b hi", plugin_repo, "ask"),
                 ("gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'", c, "ask"),
                 ("gh api graphql -f query='query { viewer { login } }'", c, None),
                 ("gh pr edit 3 --add-label x", c, "ask"), ("gh pr view 3", wt, None), ("gh auth status", c, None)]
        for cmd, cwd, want in cases:
            out = bash(ws, cmd, cwd)
            assert decision(out) == want, (cmd, cwd)
            if want == "deny":
                assert "머지" in out["permissionDecisionReason"]
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_gh_env_repo_and_api_endpoint():
    ws = shared()
    plain = tmp("tt-gh-plain-")
    db_origin = _repo_with_origin(f"git@ghe.mock.invalid:{DB_SLUG}.git")   # 다른 clone: origin 슬러그로 판정
    cases = [(f"GH_REPO={DB_SLUG} gh release create v1", plain, "ask"),
             (f"env GH_REPO=https://ghe.mock.invalid/{DB_SLUG}.git gh label delete x", plain, "ask"),
             (f"gh api --method=GET repos/{DB_SLUG}/contents/x", plain, None),
             (f"gh api -F name=v repos/{DB_SLUG}/labels", plain, "ask"),
             (f"gh api --method=DELETE repos/{DB_SLUG.upper()}/git/refs/heads/x", plain, "ask"),
             (f"gh api -X POST repos/{{owner}}/{{repo}}/issues -f title=x", db_origin, "ask"),
             ("gh pr create -t x", db_origin, "ask"),
             (f"gh pr create --repo=ssh://git@ghe.mock.invalid/{DB_SLUG} -t x", plain, "ask"),
             (f"gh pr create -R other.host.invalid/{DB_SLUG} -t x", plain, None),   # host가 다르다
             (f"gh issue list -R {DB_SLUG}", plain, None), (f"gh run rerun 5 -R {DB_SLUG}", plain, "ask"),
             (f"gh repo clone {DB_SLUG}", plain, None)]
    for cmd, cwd, want in cases:
        assert decision(bash(ws, cmd, cwd)) == want, cmd
    # 사용자 config가 없으면 gh 규칙을 적용하지 않는다
    empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}
    assert decision(bash(ws, f"gh pr merge 1 -R {DB_SLUG}", plain, env=empty)) is None


def test_guard_mcp_write_tools_targeting_issue_db():
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db"}
    cases = [("mcp__github__push_files", db, "ask"), ("mcp__github__merge_pull_request", db, "deny"),
             ("mcp__github__create_or_update_file", {"owner": "other", "repo": "x"}, None),
             ("mcp__github__get_file_contents", db, None),
             ("mcp__github__update_pull_request", {"url": f"https://ghe.mock.invalid/{DB_SLUG}/pull/3"}, "ask"),
             ("mcp__github__create_repository", {"name": "telephony-issue-db"}, None)]
    for tool, tool_input, want in cases:
        assert decision(guard(ws, tool, tool_input, ws.base)) == want, tool
    # setup 전(config에 issue_db 없음)은 판정하지 않는다
    empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}
    assert decision(guard(ws, "mcp__github__push_files", db, ws.base, env=empty)) is None


def test_guard_git_dir_work_tree_and_env_forms():
    ws = shared()
    c = ws.clone
    deny = [f'git --git-dir "{c}/.git" --work-tree "{c}" commit --no-verify -m x',
            f'git --work-tree="{c}" --git-dir="{c}/.git" commit -n -m x',
            f'GIT_DIR="{c}/.git" git push origin HEAD:main',
            f'env GIT_WORK_TREE="{c}" GIT_DIR="{c}/.git" git commit --no-verify -m x',
            f'GIT_CONFIG_PARAMETERS="\'core.hooksPath=/dev/null\'" git -C "{c}" commit -m x',
            f'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=x git -C "{c}" push origin HEAD:refs/heads/a',
            f'GIT_INDEX_FILE=/tmp/idx git -C "{c}" commit -m x']
    for cmd in deny:
        assert decision(bash(ws, cmd, ws.base)) == "deny", cmd
    assert decision(bash(ws, f'GIT_DIR="{c}/.git" git push origin HEAD:refs/heads/issue/X-1', ws.base)) == "ask"
    # 다른 레포 경로면 어떤 규칙도 적용하지 않는다
    other = tmp("tt-other-gitdir-") / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
    for cmd in deny:
        assert decision(bash(ws, cmd.replace(str(c), str(other)), ws.base)) is None, cmd


def test_guard_eval_and_xargs_wrappers():
    ws = shared()
    c = ws.clone
    assert decision(bash(ws, f'eval "git -C {c} push origin HEAD:refs/heads/main"', ws.base)) == "deny"
    assert decision(bash(ws, f"xargs -n1 git -C {c} push origin HEAD:main < list", ws.base)) == "deny"
    assert decision(bash(ws, "xargs -I{} echo {} < list", ws.base)) is None
    assert decision(bash(ws, "xargs -i echo {} < list", ws.base)) is None


def test_guard_blocks_clone_mutation_from_bash():
    ws = shared()
    c = ws.clone
    wt = ws.work / "MOCK-7101" / "wt"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    try:
        for cmd, cwd in ((f'git -C "{c}" reset --hard', ws.base), (f'cd "{c}" && git checkout -- README.md', ws.base),
                         (f'git -C "{c}" switch -c feature/x origin/main', ws.base), ("git branch -D old", c),
                         ("git stash", c), ("git pull --rebase", c), ("git worktree remove x", c),
                         ("gh pr checkout 3", c)):
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
        for cmd in (f'git -C "{c}" fetch origin', f'git -C "{c}" branch -a', f'git -C "{c}" stash list',
                    f'git -C "{c}" status', f'git -C "{wt}" checkout -b tt/x', f'git -C "{wt}" reset --hard'):
            assert decision(bash(ws, cmd, ws.base)) is None, cmd
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_blocks_file_writes_into_clone_from_bash():
    ws = shared()
    c = ws.clone
    for cmd, cwd in ((f'echo x > "{c}/jira/MOCK-1.yaml"', ws.base), (f'echo x >>"{c}/README.md"', ws.base),
                     (f'echo x &> "{c}/a.txt"', ws.base), (f'echo x | tee -a "{c}/README.md"', ws.base),
                     (f'sed -i s/a/b/ "{c}/x.yaml"', ws.base), (f'perl -pi -e s/a/b/ "{c}/x.yaml"', ws.base),
                     (f'rm -rf "{c}/causes"', ws.base), (f'cp /tmp/x "{c}/README.md"', ws.base),
                     ("touch new.txt", c), (f'sort -o "{c}/x" /tmp/y', ws.base), (f'echo x > "{c}/.git/hooks/x"', ws.base)):
        out = bash(ws, cmd, cwd)
        assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
    for cmd in (f'echo x > "{ws.work}/MOCK-1/wt/jira/MOCK-1.yaml"', f'cp "{c}/README.md" /tmp/x',
                f'grep -n x "{c}/README.md" > /tmp/out 2>&1', f'sed -n 1,5p "{c}/README.md"',
                f'sed s/a/b/ "{c}/README.md" > /tmp/out', f'cat "{c}/README.md" >&2'):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd


def test_guard_migrate_branch_creation_asks():
    ws = Workspace()
    c = ws.clone
    cmd = f'git -C "{c}" switch -c migrate/schema-v3 origin/main'
    out = bash(ws, cmd, ws.base)
    assert decision(out) == "ask" and "migrate" in out["permissionDecisionReason"]
    assert decision(bash(ws, f'git -C "{c}" checkout -b migrate/schema-v3 origin/main', ws.base)) == "ask"
    (c / "dirty.txt").write_text("x\n", encoding="utf-8")
    assert decision(bash(ws, cmd, ws.base)) == "deny"
    (c / "dirty.txt").unlink()
    assert decision(bash(ws, f'git -C "{c}" switch -c feature/x origin/main', ws.base)) == "deny"


def _no_yaml_env(ws: Workspace) -> dict:
    d = tmp("tt-noyaml-")
    (d / "yaml.py").write_text('raise ImportError("PyYAML 없음 (테스트)")\n', encoding="utf-8")
    return {**ws.env(), "PYTHONPATH": str(d)}


def test_guard_without_pyyaml_denies_mcp_and_asks_risky_bash():
    ws = shared()
    env = _no_yaml_env(ws)

    def judge(tool: str, tool_input: dict):
        event = {"tool_name": tool, "tool_input": tool_input, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, cwd=ws.base, env=env, stdin=json.dumps(event))
        assert proc.returncode == 0 and "Traceback" not in proc.stderr, proc.stderr
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        return out, proc.stderr

    out, _ = judge(JIRA_TOOLS[0], {})
    assert decision(out) == "deny" and "의존성 없음" in out["permissionDecisionReason"]
    for cmd in (f'git -C "{ws.clone}" status', f"gh pr list -R {DB_SLUG}",
                f'python3 "{ws.root}/scripts/db_pr.py" publish wt --branch issue/MOCK-1'):
        out, _ = judge("Bash", {"command": cmd})
        assert decision(out) == "ask" and "레포 판별 불가" in out["permissionDecisionReason"], cmd
    out, err = judge("Bash", {"command": "echo hi"})
    assert out is None and "의존성 없음" in err
    out, _ = judge("Write", {"file_path": str(ws.base / "x.txt")})
    assert decision(out) == "ask"


def test_guard_review_followups_redirects_and_input_redirects():
    """리뷰 후속: 공백 없는 리디렉션(`>`·`>>`·`>|`)은 쓰기, 입력 리디렉션·fd 복제·따옴표 속 `>`는 쓰기가 아니다."""
    ws = shared()
    c = ws.clone
    for cmd, cwd in ((f"echo x>{c}/f", ws.base), (f"echo x>>{c}/f", ws.base), (f"echo x>|{c}/f", ws.base),
                     ("printf x>f", c), (f"echo x 2>{c}/err", ws.base)):
        out = bash(ws, cmd, cwd)
        assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
    for cmd, cwd in (('echo "a>b"', c), ("git status 2>&1", c), ("ls 2>/dev/null", c), ("echo x >&2", c),
                     (f"sort < {c}/README.md > /tmp/o", ws.base), (f"tee /tmp/o < {c}/README.md", ws.base),
                     (f"cat <<EOF > /tmp/o\n{c}/x\nEOF", ws.base), (f"wc -l <{c}/README.md", ws.base)):
        assert decision(bash(ws, cmd, cwd)) is None, cmd


def test_guard_review_followups_git_subcommands_and_perl():
    ws = shared()
    c = ws.clone
    for cmd in ("git bisect start", "git bisect good", "git symbolic-ref HEAD refs/heads/x", "git sparse-checkout set a",
                "git submodule update --init", "git filter-branch --tree-filter true HEAD", "git branch -c a b",
                "git branch --copy a b", "git clean -fd", f"perl -i.bak -pe s/a/b/ {c}/x.yaml",
                f"perl -pi -e s/a/b/ {c}/x.yaml"):
        out = bash(ws, cmd, c)
        assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
    for cmd in ("git bisect log", "git symbolic-ref HEAD", "git clean -n", "git clean --dry-run", "git clean -nd",
                "git sparse-checkout list", "git submodule status", f"perl -Mstrict -ne print {c}/README.md",
                f"perl -MFile::Basename -e 1 {c}/README.md"):
        assert decision(bash(ws, cmd, c)) is None, cmd


def test_guard_review_followups_gh_api_method_and_merge_endpoints():
    ws = shared()
    plain = tmp("tt-gh-plain-")
    cases = [(f"gh api -X GET repos/{DB_SLUG}/issues -f state=open", None),
             (f"gh api --method GET repos/{DB_SLUG}/pulls -F per_page=5", None),
             (f"gh api repos/{DB_SLUG}/issues -f title=x", "ask"),
             (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", "deny"),
             (f"gh api -X POST repos/{DB_SLUG}/merges -f base=main -f head=x", "deny"),
             (f"gh api repos/{DB_SLUG}/pulls/3/merge", None)]   # GET: 머지 가능 여부 조회
    for cmd, want in cases:
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_review_followups_mcp_verb_position():
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db"}
    for tool, want in (("mcp__github__disable_pr_auto_merge", "ask"), ("mcp__github__enable_pr_auto_merge", "ask"),
                       ("mcp__github__list_triggers", None), ("mcp__github__request_copilot_review", "ask"),
                       ("mcp__github__run_secret_scanning", "ask"), ("mcp__github__pull_request_read", None),
                       ("mcp__github__merge_pull_request", "deny")):
        assert decision(guard(ws, tool, db, ws.base)) == want, tool
    # 미설정 jira/atlassian 서버: 읽기 동사로 시작하는 도구는 접두사가 쓰기 단어처럼 보여도 통과
    for tool in ("mcp__atlassian__get_issue_links", "mcp__atlassian__list_assignees", "mcp__jira-prod__jira_get_attachments",
                 "mcp__atlassian__getJiraIssue"):
        assert decision(guard(ws, tool, {}, ws.base)) is None, tool
    for tool in ("mcp__atlassian__addCommentToJiraIssue", "mcp__jira-prod__jira_add_comment"):
        assert decision(guard(ws, tool, {}, ws.base)) == "deny", tool
    # 설정된 서버는 그대로 read_tools 허용 목록
    assert decision(guard(ws, "mcp__mock-jira__jira_get_links", {}, ws.base)) == "deny"


def test_guard_without_pyyaml_asks_file_writes():
    ws = shared()
    env = _no_yaml_env(ws)
    for cmd, want in ((f'echo x > "{ws.clone}/README.md"', "ask"), ("echo hi 2>/dev/null", None)):
        event = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, cwd=ws.base, env=env, stdin=json.dumps(event))
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert proc.returncode == 0 and decision(out) == want, cmd


def test_hooks_json_has_eight_rules_wired_to_guard():
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert "sync-scripts-path" in hooks["SessionStart"][0]["hooks"][0]["command"]
    matchers = {h["matcher"]: h["hooks"][0]["command"] for h in hooks["PreToolUse"]}
    assert set(matchers) == {"mcp__.*", "Bash", "Write|Edit|MultiEdit|NotebookEdit"}
    assert all("${CLAUDE_PLUGIN_ROOT}/scripts/guard.py" in cmd for cmd in matchers.values())


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
