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
import os
import re
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
        _WS.json("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA_TOOLS[0],
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
    jira = (ws.clone / DATA_DIR / "issues" / "MOCK-1101.yaml").read_text(encoding="utf-8")
    branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/issues/MOCK-1101.yaml",
                       jira.replace("접수됨", "접수됨 imei=490154203237518"))
    proc = gitp(ws.clone, "commit", "-qm", "PII", env=ws.hook_env())
    assert proc.returncode != 0 and "mask" in proc.stderr and "IMEI" in proc.stderr

    # 정상 변경은 통과한다 (마스킹된 note)
    branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/issues/MOCK-1101.yaml",
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


def test_git_hooks_name_missing_pyyaml_instead_of_misleading_errors():
    """PATH의 python3에 PyYAML이 없으면(의존성은 venv에만, venv를 안 켬) 그렇다고 알리고 막는다.
    pre-commit은 'scripts_path가 없다'로, pre-push는 기본값 판정으로 새지 않는다."""
    ws = Workspace()
    shim = ws.base / "no-yaml-bin"
    shim.mkdir()
    (shim / "python3").write_text(f"#!/bin/sh\nexec '{sys.executable}' -S \"$@\"\n", encoding="utf-8")
    (shim / "python3").chmod(0o755)
    env = ws.hook_env()
    env["PATH"] = os.pathsep.join([str(shim), env.get("PATH", os.environ["PATH"])])
    branch_with_change(ws, "review/data-2026-10", "CONTRIBUTING.md", "직접 편집\n")
    proc = gitp(ws.clone, "commit", "-qm", "직접 편집", env=env)
    assert proc.returncode != 0 and "PyYAML이 없다" in proc.stderr and "plugin.scripts_path가 없다" not in proc.stderr
    assert gitp(ws.clone, "commit", "-qm", "직접 편집", env=ws.hook_env()).returncode == 0
    env["TT_PUBLISH_TOKEN"] = "manual"
    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/review/data-2026-10", env=env)
    assert proc.returncode != 0 and "PyYAML이 없어" in proc.stderr


def test_git_hooks_do_not_import_modules_from_the_work_tree():
    """hook의 inline python(`python3 - <<EOF`)은 cwd(작업 트리 top)를 import 경로에 두지 않는다 — 작업 트리에 심은 무시된 가짜
    `yaml/`(진짜를 다시 내보내 판정은 그대로)이 커밋·push 때 돌지 않는다 (리뷰 6 F-P0 고침 2)."""
    ws = Workspace()
    marker = ws.base / "PWNED"
    branch_with_change(ws, "review/data-2026-10", "CONTRIBUTING.md", "직접 편집\n")
    fake = ws.clone / "yaml"
    fake.mkdir()
    (fake / ".gitignore").write_text("*\n", encoding="utf-8")
    (fake / "__init__.py").write_text(
        f"import os, sys\nopen({str(marker)!r}, 'a').close()\n"
        "here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
        "sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]\n"
        "del sys.modules[__name__]\nimport yaml\n", encoding="utf-8")
    proc = gitp(ws.clone, "commit", "-qm", "직접 편집", env=ws.hook_env())
    assert proc.returncode == 0 and not marker.exists(), proc.stderr
    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/review/data-2026-10",
                env=ws.hook_env(TT_PUBLISH_TOKEN="manual"))
    assert proc.returncode == 0 and not marker.exists(), proc.stderr


def test_git_hooks_drop_pythonpath_that_links_to_the_work_tree():
    """재리뷰 RR-4: 링크로 cwd(작업 트리 top)를 가리키는 `PYTHONPATH`도 hook의 inline python(`python3 -`) import 경로에서 뺀다.
    cwd 아래 venv류 폴더(site-packages)는 cwd가 아니니 그대로 쓴다. 가짜 `yaml`은 inline python(argv[0] `-`)에서만 표시를 남긴다."""
    ws = Workspace()
    branch_with_change(ws, "review/data-2026-10", "CONTRIBUTING.md", "직접 편집\n")
    link = ws.base / "clone-link"
    try:
        link.symlink_to(ws.clone, target_is_directory=True)
    except (OSError, NotImplementedError):
        import pytest
        pytest.skip("심볼릭 링크를 만들 수 없다")
    site = ws.clone / "venv" / "site-packages"
    marks = {}
    for name, where in (("link", ws.clone), ("venv", site)):
        marks[name] = ws.base / f"IMPORTED-{name}"
        (where / "yaml").mkdir(parents=True)
        (where / "yaml" / ".gitignore").write_text("*\n", encoding="utf-8")
        (where / "yaml" / "__init__.py").write_text(
            f"import os, sys\nif sys.argv[0] == '-':\n    open({str(marks[name])!r}, 'a').close()\n"
            "here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))\n"
            "sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.curdir) != here]\n"
            "del sys.modules[__name__]\nimport yaml\n", encoding="utf-8")
    (ws.clone / "venv" / ".gitignore").write_text("*\n", encoding="utf-8")
    proc = gitp(ws.clone, "commit", "-qm", "직접 편집", env={**ws.hook_env(), "PYTHONPATH": str(link)})
    assert proc.returncode == 0 and not marks["link"].exists(), proc.stderr
    proc = gitp(ws.clone, "push", "-q", "origin", "HEAD:refs/heads/review/data-2026-10",
                env={**ws.hook_env(TT_PUBLISH_TOKEN="manual"), "PYTHONPATH": str(site)})
    assert proc.returncode == 0 and marks["venv"].exists(), proc.stderr


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
        assert decision(out) == "deny" and "config.py install-hooks" in out["permissionDecisionReason"], value
    ws.json("config.py", ["install-hooks", "--db", ws.clone])
    # worktree도 같은 설정을 공유한다
    wt = ws.work / "wt-guard"
    git(ws.clone, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    assert decision(bash(ws, "git commit --no-verify -m x", wt)) == "deny"
    gitp(ws.clone, "worktree", "remove", "--force", str(wt))


def test_guard_commit_checks_pii_and_generated_files():
    ws = Workspace()
    jira = ws.clone / DATA_DIR / "issues" / "MOCK-1101.yaml"
    branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/issues/MOCK-1101.yaml",
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


# 규칙 5(hook 우회) 꼴: 커밋 `--no-verify`·`-n`, `-c core.hooksPath=…`, hooksPath를 바꾸는 `git config`, push `--no-verify`,
# `GIT_CONFIG_*`가 붙은 push(`GIT_INDEX_FILE` 커밋은 ci_mode와 무관하게 거부 — 아래)
RULE5_FORMS = ('git commit --no-verify -m x', 'git commit -n -m x', 'git -c core.hooksPath=/dev/null commit -m x',
               'git config core.hooksPath hooks', 'git config --unset core.hooksPath', 'git config --remove-section core',
               'git push --no-verify origin HEAD:refs/heads/issue/X-1',
               'GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=x git push origin HEAD:refs/heads/a')
_CI_WS: list = []


def _ci_mode_ws(mode: str | None = None, text: str | None = None, delete: bool = False, wt_mode: str | None = None) -> Workspace:
    """이 시험들만 쓰는 작업공간. clone의 `refs/remotes/origin/main`을 처음 커밋으로 되돌린 뒤, `issue-db.config.yaml`만 바꾼
    커밋으로 옮긴다 — `ci_mode` 줄을 `mode`로, 파일을 `text`로, 지움(`delete`). guard의 규칙 5 완화는 이 ref의 파일만 본다
    (`_ci_actions` — 작업 트리는 Claude가 고칠 수 있다). `wt_mode`는 작업 트리 파일만 그 값으로 바꾼다(믿지 않는지 본다)."""
    if not _CI_WS:
        w = Workspace()
        _CI_WS.extend([w, git(w.clone, "rev-parse", "refs/remotes/origin/main")])
    ws, orig = _CI_WS
    c, name = ws.clone, "issue-db.config.yaml"
    git(c, "checkout", "-q", "--", name)
    git(c, "update-ref", "refs/remotes/origin/main", orig)
    original = git(c, "show", f"{orig}:{name}")

    def with_mode(value: str) -> str:
        return re.sub(r"(?m)^ci_mode:.*$", f"ci_mode: {value}", original)
    if wt_mode is not None:
        (c / name).write_text(with_mode(wt_mode), encoding="utf-8", newline="\n")
    if mode is None and text is None and not delete:
        return ws
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp("tt-idx-") / "index")}
    git(c, "read-tree", orig, env=env)
    if delete:
        git(c, "update-index", "--force-remove", name, env=env)
    else:
        blob = subprocess.run(["git", "-C", str(c), "hash-object", "-w", "--stdin"], input=text if mode is None else with_mode(mode),
                              capture_output=True, text=True, check=True).stdout.strip()
        git(c, "update-index", "--add", "--cacheinfo", f"100644,{blob},{name}", env=env)
    tree = git(c, "write-tree", env=env)
    git(c, "update-ref", "refs/remotes/origin/main", git(c, "commit-tree", tree, "-p", orig, "-m", "ci_mode 시험"))
    return ws


def test_guard_rule5_asks_when_ci_mode_actions():
    """4-c: 그 clone `origin/<base>`의 `ci_mode`가 `actions`로 확인되면(서버 CI `db-check`가 마스킹·생성 파일 검사를 다시 한다)
    규칙 5는 거부 대신 ask이고 사유에 그 근거를 붙인다. 커밋 검사(규칙 3)는 그대로 돈다 — `--no-verify` 커밋이라도 staged PII는
    거부. `GIT_INDEX_FILE` 커밋은 커밋 검사가 그 index를 보지 못하므로 actions여도 거부."""
    ws = _ci_mode_ws("actions")
    try:
        for cmd in RULE5_FORMS:
            out = bash(ws, cmd, ws.clone)
            assert decision(out) == "ask", cmd
            assert "규칙 5" in out["permissionDecisionReason"] and "ci_mode: actions" in out["permissionDecisionReason"], cmd
        for cmd in ('git config core.hooksPath .githooks', 'git status'):     # 규칙 5가 아닌 것은 그대로
            assert decision(bash(ws, cmd, ws.clone)) is None, cmd
        out = bash(ws, "GIT_INDEX_FILE=/tmp/idx git commit -m x", ws.clone)
        assert decision(out) == "deny" and "GIT_INDEX_FILE 커밋" in out["permissionDecisionReason"]
        jira = ws.clone / DATA_DIR / "issues" / "MOCK-1101.yaml"
        branch_with_change(ws, "issue/MOCK-1101", f"{DATA_DIR}/issues/MOCK-1101.yaml",
                           jira.read_text(encoding="utf-8").replace("접수됨", "접수됨 imei=490154203237518"))
        out = bash(ws, 'git commit --no-verify -m "x"', ws.clone)
        assert decision(out) == "deny" and "규칙 3" in out["permissionDecisionReason"]
    finally:
        git(ws.clone, "reset", "-q", "--hard")
        git(ws.clone, "checkout", "-q", "main")
        _ci_mode_ws()


def test_guard_rule5_denies_when_ci_mode_local():
    """4-c: `origin/<base>`의 `ci_mode: local`(서버 CI가 다시 검사하지 않는다)이면 규칙 5는 그대로 거부. 작업 트리 파일을
    `actions`로 고쳐도(Claude가 고칠 수 있다 — 4-c 리뷰 P1) 믿지 않는다."""
    for ws in (_ci_mode_ws("local"), _ci_mode_ws(wt_mode="actions")):
        for cmd in (*RULE5_FORMS, "GIT_INDEX_FILE=/tmp/idx git commit -m x"):
            out = bash(ws, cmd, ws.clone)
            assert decision(out) == "deny" and "규칙 5" in out["permissionDecisionReason"], cmd
            assert "ci_mode: actions" not in out["permissionDecisionReason"], cmd
    _ci_mode_ws()


def test_guard_rule5_denies_when_ci_mode_missing_or_unreadable():
    """4-c: 닫힌 쪽 — `origin/<base>`에 `issue-db.config.yaml`이 없거나, YAML로 못 읽거나, 객체가 아니거나, `ci_mode`가 없거나
    `actions`가 아닌 값(`actions-build`·대소문자 다름)이면 규칙 5는 거부."""
    cases = [{"delete": True}, {"text": "ci_mode: [\n"}, {"text": "- ci_mode: actions\n"}, {"text": "schema_version: 1\n"},
             {"mode": "actions-build"}, {"mode": "Actions"}]
    try:
        for case in cases:
            ws = _ci_mode_ws(**case)
            for cmd in RULE5_FORMS:
                out = bash(ws, cmd, ws.clone)
                assert decision(out) == "deny" and "규칙 5" in out["permissionDecisionReason"], (case, cmd)
    finally:
        _ci_mode_ws()


# 규칙 5 근거 ref(origin/<base>)를 바꿀 수 있는 git(4-c 정한 범위): 도구 worktree에서 본다 — clone 본체는 규칙 8도 거부한다
REMOTE_FORGE_FORMS = (
    "git update-ref refs/remotes/origin/main HEAD", "git update-ref --stdin", "git update-ref -d refs/remotes/origin/main",
    "git update-ref remotes/origin/main HEAD", "git symbolic-ref refs/remotes/origin/main refs/heads/main",
    "git symbolic-ref -d refs/remotes/origin/HEAD",
    "git fetch origin x:refs/remotes/origin/main", "git fetch origin '+refs/heads/*:refs/remotes/origin/*'",
    "git fetch origin +x:remotes/origin/main", "git fetch origin main --refmap=+refs/heads/x:refs/remotes/origin/main",
    "git fetch origin main --refmap +refs/heads/x:refs/remotes/origin/main", "git pull origin x:refs/remotes/origin/main",
    "git fetch .", "git fetch . HEAD:refs/remotes/origin/main", "git fetch /tmp/x", "git fetch https://example.com/x.git",
    "git fetch upstream", "git pull upstream main", "git pull /tmp/x main", "git fetch --all", "git fetch --multiple origin up",
    "git fetch --stdin origin", "git remote update",
    "git remote set-url origin /tmp/x", "git remote set-url --add origin /tmp/x", "git remote add origin /tmp/x",
    "git remote rename origin old", "git remote remove origin", "git remote rm origin",
    "git -c remote.origin.fetch=+refs/heads/x:refs/remotes/origin/main fetch origin", "git -c remote.origin.url=/tmp/x fetch",
    "git -c remote.origin.url=/tmp/x pull", "git -c url./tmp/x.insteadOf=file:// fetch origin",
    "git --config-env=remote.origin.url=U fetch origin",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=remote.origin.url GIT_CONFIG_VALUE_0=/tmp/x git fetch origin",
    "git config remote.origin.url /tmp/x", "git config remote.origin.fetch +refs/heads/x:refs/remotes/origin/main",
    "git config --unset remote.origin.fetch", "git config --add remote.origin.fetch +x:refs/remotes/origin/main",
    "git config set url./tmp/x.insteadOf file://", "git config --rename-section remote.origin remote.old",
    "git config remote.origin.pushurl /tmp/x", "git -c remote.origin.url=. -c remote.origin.fetch=+x:refs/remotes/origin/main fetch origin",
    "git fetch --refmap=+refs/heads/x:refs/remotes/origin/main . refs/heads/x", "git fetch origin --refmap=x:refs/remotes/up/main",
    # `git replace`(근거 커밋을 바꿔 끼운다 — `_ci_actions`는 `--no-replace-objects`로도 막는다)·자기 자신으로 원격 추적 ref push
    "git replace HEAD~0 HEAD", "git replace -f abc def", "git replace --graft HEAD", "git update-ref refs/replace/abc HEAD",
    "git push . HEAD:refs/remotes/origin/main", "git push origin +HEAD:refs/remotes/origin/main", "git push . HEAD:refs/heads/x")
# 그대로 허용(Step 1·db_pr stage가 쓴다 — 4-c 전후 None). `git pull`은 clone 본체에서는 규칙 8 거부 그대로다
REMOTE_FETCH_OK = ("git fetch", "git fetch origin", "git fetch origin main", "git pull", "git pull origin",
                   "git fetch --prune origin", "git fetch -q origin main", "git fetch --depth 1 origin main",
                   "git pull --ff-only", "git pull --rebase origin main", "git fetch origin -- main")


def test_guard_remote_ref_forgery_denied_and_fetch_forms_allowed():
    """규칙 5(4-c): ci_mode 완화의 근거 ref(`refs/remotes/origin/<base>`)를 바꿀 수 있는 git은 이슈 DB 레포(본체·worktree,
    `-C`·`--git-dir`)에서 거부(`REMOTE_FORGE_FORMS`), `.git/**`·worktree `.git` 연결 파일 쓰기도 거부. 평소 받기
    (`REMOTE_FETCH_OK`)·읽기(`symbolic-ref` 한 인자·`config --get`·`remote -v`)는 그대로 허용. 이슈 DB 밖 레포는 보지 않는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    other = _repo_with_origin("https://example.com/o/other.git")
    wt = ws.work / "wt-forge"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    W, C = wt.as_posix(), c.as_posix()
    try:
        for cmd in REMOTE_FORGE_FORMS:
            out = bash(ws, cmd, wt)
            assert decision(out) == "deny" and "원격 추적 ref" in out["permissionDecisionReason"], cmd
        for cmd, cwd in ((f"git -C {W} update-ref refs/remotes/origin/main HEAD", plain), (f"git -C {W} fetch .", plain),
                         (f"git --git-dir={C}/.git fetch .", plain), (f"git --git-dir {C}/.git remote set-url origin /x", plain),
                         ("git fetch .", c), ("git fetch origin x:refs/remotes/origin/main", c),
                         # 다른 레포에서 경로로 이슈 DB에 push(그 자리에서 origin 추적 ref를 덮는다)
                         (f"git push {C} HEAD:refs/remotes/origin/main", other), (f"git push --mirror {C}", other),
                         (f"git push file://{C} x:refs/heads/x", other), (f"git -C {other.as_posix()} push {W} HEAD:x", plain)):
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and "원격 추적 ref" in out["permissionDecisionReason"], cmd
        for cmd, cwd in ((f"echo gitdir: /tmp/x > {W}/.git", plain), (f"rm {W}/.git", plain), (f"mv {W}/.git /tmp/x", plain),
                         ("echo gitdir: /tmp/x > .git", wt)):
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and "git 메타데이터" in out["permissionDecisionReason"], cmd
        for path in (f"{W}/.git", f"{C}/.git/refs/remotes/origin/main", f"{C}/.git/packed-refs", f"{C}/.git/config"):
            assert decision(guard(ws, "Write", {"file_path": path, "content": "x"}, plain)) == "deny", path
        for cmd in (f"echo x > {C}/.git/packed-refs", f"echo x > {C}/.git/config"):     # 본체는 규칙 8
            out = bash(ws, cmd, plain)
            assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
        for cmd in (*REMOTE_FETCH_OK, "git symbolic-ref refs/remotes/origin/HEAD", "git symbolic-ref --short HEAD",
                    "git config --get remote.origin.url", "git config remote.origin.url", "git remote -v",
                    "git remote get-url origin", "git remote show origin", "git update-ref refs/heads/x HEAD",
                    "git remote update origin", "git config user.name x", "git replace -l", "git replace"):
            assert decision(bash(ws, cmd, wt)) is None, cmd
        for cmd in ("git push origin HEAD:refs/heads/issue/X-1", "git push -u origin HEAD"):    # 평소 push는 규칙 7 ask 그대로
            assert decision(bash(ws, cmd, wt)) == "ask", cmd
        for cmd in REMOTE_FETCH_OK:
            if not cmd.startswith("git pull"):
                assert decision(bash(ws, cmd, c)) is None, cmd
        for cmd in ("git fetch .", "git remote set-url origin /tmp/x", "git update-ref refs/remotes/origin/main HEAD",
                    "git replace HEAD~0 HEAD", "git push . HEAD:refs/remotes/origin/main", "git push /tmp/x HEAD"):
            assert decision(bash(ws, cmd, other)) is None, cmd                  # 이슈 DB 밖
        assert decision(guard(ws, "Write", {"file_path": f"{other.as_posix()}/.git/config", "content": "x"}, plain)) is None
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_push_rules():
    """4-c: base 브랜치 push(규칙 6)는 따로 거부하지 않고 모든 이슈 DB push와 같이 ask다 — main 직접 push·force push·삭제는
    서버 브랜치 보호가 막는다(전제 site_checks `s4a.protection_guard`)."""
    ws = shared()
    c = ws.clone
    for cmd in ("git push origin HEAD:refs/heads/main", "git push origin main", "git push origin +HEAD:main",
                "git push --all origin", "git push origin :", "git push --delete origin main",
                f'cd "{c}" && git push origin HEAD:refs/heads/main'):
        out = bash(ws, cmd, c if not cmd.startswith("cd ") else ws.base)
        assert decision(out) == "ask" and "이슈 DB push" in out["permissionDecisionReason"], cmd
    # 현재 브랜치가 main이어도 refspec 없는 push는 같은 ask다
    assert git(c, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert decision(bash(ws, "git push", c)) == "ask"
    # 그 밖의 이슈 DB push와 db_pr publish는 확인(ask)
    assert decision(bash(ws, "git push origin HEAD:refs/heads/issue/MOCK-1", c)) == "ask"
    publish = f'python3 "{ws.root}/scripts/db_pr.py" publish wt --branch issue/MOCK-1 --lease new --approved x'
    assert decision(bash(ws, publish, ws.base)) == "ask"


def test_guard_comment_does_not_swallow_next_line():
    """K 3차 P1-b: 주석 뒤 줄의 명령은 따로 본다(shlex 기본 commenters가 주석과 줄바꿈을 함께 먹어 다음 줄이 앞 argv에 붙던 우회).
    `$#`·`${#x}`·`a#b`·인용 안 `#`은 주석이 아니다."""
    ws = shared()
    c = ws.clone
    assert decision(bash(ws, "echo x # note\ngit push --no-verify origin HEAD:main", c)) == "deny"
    assert decision(bash(ws, "echo s # c\ngit commit --no-verify -m x", c)) == "deny"
    assert decision(bash(ws, "true # main 아님\ngit push origin HEAD:refs/heads/issue/MOCK-1", c)) == "ask"
    for cmd in ('echo $# ${#x} a#b "q # git push origin main"', "git status # git push origin main"):
        assert decision(bash(ws, cmd, c)) is None, cmd


def test_guard_publish_with_commit_and_discard_still_asks():
    """W5: `publish --commit --and-discard`도 `publish` 토큰 때문에 ask다 (옵션 이름과 무관)."""
    ws = shared()
    db_pr = f'python3 "{ws.root}/scripts/db_pr.py"'
    base = "publish wt --branch issue/MOCK-1 --lease new --approved x"
    for tail in ("--commit", "--and-discard", "--commit --and-discard", "--and-discard --commit"):
        out = bash(ws, f"{db_pr} {base} {tail}", ws.base)
        assert decision(out) == "ask" and "publish" in out["permissionDecisionReason"], tail


def test_guard_merge_and_skill_apply_ask_direct_gh_merge_asks():
    """+1 병합: `db_pr.py merge`는 ask(사용자가 병합을 요청한 뒤, 스크립트가 +1·승인 커밋·검사 대조), gh로 직접 머지는 거부.
    리뷰어 요청: `db_pr.py request-review`는 매번 ask(push 뒤 리뷰어 질문에서 고른 뒤, 규칙 7).
    분석 스킬 소스 적용: `skill_patch.py --apply`는 ask(규칙 12). patch 만들기·my-prs는 판정할 것이 없다."""
    ws = shared()
    S = f'python3 "{ws.root}/scripts/'
    out = bash(ws, f'{S}db_pr.py" merge --job MOCK-1 --approved {"a" * 40} --json', ws.base)
    assert decision(out) == "ask" and "db_pr.py merge" in out["permissionDecisionReason"]
    assert "병합을 요청한 뒤" in out["permissionDecisionReason"] and "바로 병합" not in out["permissionDecisionReason"]
    out = bash(ws, f'{S}db_pr.py" merge --job MOCK-1 --json', ws.base)                  # --approved 생략(Q8)도 같다
    assert decision(out) == "ask" and "db_pr.py merge" in out["permissionDecisionReason"]
    out = bash(ws, f"gh pr merge 3 --merge -R {DB_SLUG}", ws.base)       # 병합 계열은 ask(4-c — 서버 브랜치 보호가 막는다)
    assert decision(out) == "ask" and "db_pr.py merge" in out["permissionDecisionReason"]
    for cmd in (f'{S}db_pr.py" request-review --job MOCK-1 --reviewer a,b --json',
                f'S={ws.root}/scripts; python3 "$S/db_pr.py" request-review --job MOCK-1 --reviewer=@a'):
        out = bash(ws, cmd, ws.base)
        reason = out["permissionDecisionReason"]
        assert decision(out) == "ask" and "request-review" in reason and "규칙 7" in reason, cmd
        assert "db_pr.py merge는" not in reason and "publish는" not in reason, cmd     # 다른 ask와 섞이지 않는다
    out = bash(ws, f'{S}skill_patch.py" MOCK-1 --name mock-data-analyzer --apply --sha {"b" * 64}', ws.base)
    assert decision(out) == "ask" and "규칙 12" in out["permissionDecisionReason"]
    for cmd in (f'{S}skill_patch.py" MOCK-1 --skill-dir /x --name mock-data-analyzer', f'{S}db_pr.py" my-prs',
                f'{S}db_pr.py" summary wt --format markdown', f'{S}db_pr.py" find-plan --branch review/x'):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd
    # 없어진 publish --and-merge(옛 스킬): argparse가 거부하지만 guard는 그대로 ask(publish·merge 사유 둘 다 — 닫힌 쪽)
    out = bash(ws, f'{S}db_pr.py" publish wt --branch issue/MOCK-1 --lease new --approved x --commit --and-discard '
                   f'--and-merge --json', ws.base)
    assert decision(out) == "ask" and "publish" in out["permissionDecisionReason"] and \
        "db_pr.py merge" in out["permissionDecisionReason"]
    # 스크립트만 쓰는 기록: 병합 기록·스킬 제안 patch·meta는 직접 쓰거나 지우면 거부, 사본 폴더는 통과
    job = ws.work / "MOCK-1"
    for target in (job / "merge-offer.json", job / "skill-suggestions" / "a.patch", job / "skill-suggestions" / "a.meta.json"):
        out = guard(ws, "Write", {"file_path": str(target), "content": "{}"}, ws.base)
        assert decision(out) == "deny" and "만 쓴다" in out["permissionDecisionReason"], target
        assert decision(bash(ws, f"echo x > {target}", ws.base)) == "deny", target
        assert decision(bash(ws, f"rm -f {target}", ws.base)) == "deny", target
    copy = job / "skill-suggestions" / "a" / "references" / "x.patch"
    assert decision(guard(ws, "Write", {"file_path": str(copy), "content": "x"}, ws.base)) is None


def test_guard_module_eval_asks():
    """모듈 eval: `module_eval.py`는 자식 `claude -p`를 띄워 비용이 든다 — `--dry-run`·`--probe-restricted`까지 모든 호출이
    ask(낱말 그물: 이름 `module_eval` + 낱말 `module`, 규칙 7). `--module`이 없는 `--help`는 판정할 것이 없다."""
    ws = shared()
    S = f'python3 "{ws.root}/scripts/module_eval.py"'
    for tail in ("--module ofono/data --dry-run", "--module ofono/data --dry-run --json",
                 "--module ofono/data --probe-restricted", "--module ofono/data --model sonnet --record",
                 "--module=ofono/data --child-mode restricted"):
        out = bash(ws, f"{S} {tail}", ws.base)
        reason = out["permissionDecisionReason"]
        assert decision(out) == "ask" and "module_eval.py" in reason and "규칙 7" in reason, tail
        assert "publish는" not in reason and "db_pr.py merge는" not in reason, tail
    assert decision(bash(ws, f"{S} --help", ws.base)) is None
    for cmd in ("python3 tests/test_module_eval.py", "ls templates/module-skills", "echo module_eval.py --module x"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd


def test_guard_skill_source_writes_ask():
    """규칙 12: config `analyzers.<카테고리>.source` 안을 파일 도구·Bash 쓰기·파일을 바꾸는 git으로 바꾸면 ask, 읽기는 통과."""
    ws = Workspace()
    src = tmp("tt-skill-src-") / "skill"
    (src / "references").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    cfg = ws.home / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["analyzers"] = {"data": {"skill": "mock-data-analyzer", "source": str(src)}}
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    target = str(src / "references" / "DATA-001.md")
    out = guard(ws, "Write", {"file_path": target, "content": "x"}, ws.base)
    assert decision(out) == "ask" and "skill_patch.py --apply로만" in out["permissionDecisionReason"]
    assert decision(guard(ws, "Edit", {"file_path": str(ws.base / "x.md"), "old_string": "a", "new_string": "b"},
                          ws.base)) is None
    for cmd, want in ((f"echo x > {target}", "ask"), (f"git -C {src} apply /tmp/p.patch", "ask"),
                      ("git apply /tmp/p.patch", "ask"), (f"git -C {src} commit -m x", "ask"),
                      (f"git -C {src} status --porcelain", None), (f"grep -n x {target}", None)):
        cwd = src if not cmd.startswith(("echo", "grep")) and "-C" not in cmd else ws.base
        assert decision(bash(ws, cmd, cwd)) == want, cmd


def test_guard_skill_source_of_every_platform_asks():
    """규칙 12(17-platforms §10): site-defaults `platforms.<p>.analyzers`(사용자 config에 그 플랫폼 프로필이 없어도)와
    사용자 config `platforms.<p>.analyzers`의 `source`도 보호한다. 읽기는 통과, android 최상위 것은 그대로."""
    base = tmp("tt-skill-src-")
    srcs = {k: base / k for k in ("site-ofono", "user-ofono", "android")}
    for d in srcs.values():
        (d / "references").mkdir(parents=True)
    root = plugin_root("skill-src-platforms", platform={"name": "android", "enabled": ["android", "ofono"]},
                       platforms={"ofono": {"analyzers": {"data": {"skill": "o", "source": str(srcs["site-ofono"])}}}})
    ws = Workspace(root=root, build=False)
    cfg = ws.home / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data["analyzers"] = {"data": {"skill": "mock-data-analyzer", "source": str(srcs["android"])}}
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    plain = str(srcs["user-ofono"] / "references" / "x.md")       # 아직 어디에도 설정 안 됨
    assert decision(guard(ws, "Write", {"file_path": plain, "content": "x"}, ws.base)) is None
    for name in ("site-ofono", "android"):
        target = str(srcs[name] / "references" / "DATA-001.md")
        out = guard(ws, "Write", {"file_path": target, "content": "x"}, ws.base)
        assert decision(out) == "ask" and "skill_patch.py --apply로만" in out["permissionDecisionReason"], name
        if name == "site-ofono":     # 사용자 config에 ofono 프로필이 없어도 site 것은 보호
            assert "platforms" not in data
        assert decision(bash(ws, f"echo x > {target}", ws.base)) == "ask", name
        assert decision(bash(ws, f"grep -n x {target}", ws.base)) is None, name
    data["platforms"] = {"ofono": {"analyzers": {"data": {"source": str(srcs["user-ofono"])}}}}
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert decision(guard(ws, "Write", {"file_path": plain, "content": "x"}, ws.base)) == "ask"
    assert decision(bash(ws, f"git -C {srcs['user-ofono']} apply /tmp/p.patch", ws.base)) == "ask"
    assert decision(guard(ws, "Write", {"file_path": str(ws.base / "x.md"), "content": "x"}, ws.base)) is None


def test_guard_stage_then_summary_and_discard_are_not_asked():
    """W5: `stage --then-summary`와 단독 `discard`는 판정할 것이 없다 (publish만 ask)."""
    ws = shared()
    db_pr = f'python3 "{ws.root}/scripts/db_pr.py"'
    for cmd in (f"{db_pr} stage plan.json --wt wt --branch issue/MOCK-1 --then-summary",
                f"{db_pr} summary wt --format markdown", f"{db_pr} discard wt"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd


def test_guard_publish_any_interpreter_or_substitution_asks():
    """K P0-1: SKILL.md `S/` 규약(`${S}db_pr.py`)·변수 인터프리터·`py -3`·`./db_pr.py`·명령 치환·백틱 안 publish도 규칙 7 ask다.
    stage·summary·discard와 db_pr.py를 인자로 읽는 명령은 판정할 것이 없다. git push 규칙은 그대로."""
    ws = shared()
    root = ws.root / "scripts"
    tail = "publish wt --branch issue/MOCK-1 --lease new --approved x --commit --and-discard --json"
    for cmd in (f'S="{root}/"; python3 ${{S}}db_pr.py {tail}', f'S="python3 {root}/"\n${{S}}db_pr.py {tail}',
                f"PY=python3; S={root}; $PY $S/db_pr.py {tail}", '"${PY:-python3}" "${S}db_pr.py" publish wt',
                f"py -3 {root}/db_pr.py publish wt", 'R="$(python3 $S/db_pr.py publish wt --json)"',
                "R=`python3 $S/db_pr.py publish wt --json`", f"cd {root} && ./db_pr.py {tail}"):
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "ask" and "규칙 7" in out["permissionDecisionReason"], cmd
    # K 2차: 인용 경로가 든 명령 치환 대입(R1), 쪼갠 이름 `"$S"db_pr.py`·`$S"db_pr.py"`(R2), 셸이 읽는 heredoc·heredoc 안
    # subprocess(R3)
    for cmd in (f'R="$(python3 "{root}/db_pr.py" publish /w/wt --branch issue/MOCK-1 --approved abc1234 --commit --json)"; echo "$R"',
                'R="$(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/db_pr.py" publish wt)"',
                'python3 "$S"db_pr.py publish wt --json', 'python3 $S"db_pr.py" publish wt --json',
                f"bash <<'EOF'\nset -e\npython3 {root}/db_pr.py publish wt --json\nEOF",
                f"python3 - <<'EOF'\nimport subprocess\nsubprocess.run(['python3', '{root}/db_pr.py', 'publish', 'wt'])\nEOF",
                # K 3차: 셸로 넘기는 글, `python3 -c` 본문
                f'echo "python3 {root}/db_pr.py publish wt" | bash', "printf '%s\\n' 'python3 $S/db_pr.py publish wt' | sh",
                f"python3 -c \"import subprocess; subprocess.run(['python3', '{root}/db_pr.py', 'publish', 'wt'])\""):
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "ask" and "규칙 7" in out["permissionDecisionReason"], cmd
    for cmd in ("${S}db_pr.py stage plan.json --wt wt --branch issue/MOCK-1 --then-summary",
                "$PY $S/db_pr.py summary wt --format markdown", "${S}db_pr.py discard wt",
                f"grep -n publish {root}/db_pr.py", 'grep -n "db_pr.py publish" x.md', "cat $S/db_pr.py | grep publish",
                'rg "publish" db_pr.py', "python3 -m pytest tests/test_db_pr.py -k publish", "ls # db_pr.py publish wt"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd
    out = bash(ws, "git push origin HEAD:refs/heads/main x/db_pr.py publish", ws.clone)
    assert decision(out) == "ask" and "이슈 DB push" in out["permissionDecisionReason"]
    empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}     # 사용자 config 없음: 이슈 DB가 없으므로 묻지 않는다
    assert decision(bash(ws, "${S}db_pr.py publish wt", ws.base, env=empty)) is None


def test_guard_publish_word_net_closes_limits_and_skips_text():
    """L M-2: 낱말 그물(`word_net`)은 옛 한계(`python3 -m`·변수에 담은 하위 명령·`${P:-publish}`·`$C`·별칭·줄 이음)를 ask로
    닫고, `cat >` heredoc·`publish.json`·`publish-preview`·`dbpr/publish.py`는 판정하지 않는다. git·gh 줄은 글로 빼지
    않는다(리뷰 2차 P0-2). 남는 한계(스크립트 파일 안, 변수로 만든 낱말)는 08-safety와 같게 고정한다. 인용 안 `<<EOF`는
    heredoc이 아니다(H-A1 r6 `_heredoc_scan` — 옛 한계 "가짜 heredoc"을 닫는다)."""
    ws = shared()
    r = ws.root / "scripts"
    for cmd in ("python3 -m db_pr publish wt", "SUB=publish; python3 $S/db_pr.py $SUB wt",
                "python3 $S/db_pr.py ${P:-publish} wt", f'C="python3 {r}/db_pr.py publish"; $C wt',
                f"alias p='python3 {r}/db_pr.py publish'; p wt", f"S={r}/\npython3 ${{S}}db_pr.py \\\n  publish wt",
                # 인용·`\`·ANSI-C로 쪼갠 낱말(리뷰 P0)
                'python3 $S/db_pr.py pub"lish" wt', "python3 $S/db_pr.py publ\\ish wt", 'python3 $S/d""b_pr.py publish wt',
                'python3 $S/db"_"pr.py publish wt', "python3 $S/db\\_pr.py publish wt", "python3 $S/db_pr.py pub$'l'ish wt",
                # 리뷰 2차 P0-1: 본문 끝 줄의 `\`가 heredoc 끝 표시를 삼키지 않는다
                "cat > n.md <<'EOF'\nC:\\work\\\nEOF\npython3 $S/db_pr.py publish wt",
                "git commit -F - <<'EOF'\nC:\\work\\\nEOF\npython3 $S/db_pr.py publish wt",
                "tee n.md <<'EOF'\nC:\\work\\\nEOF\npython3 $S/db_pr.py publish wt",
                # P0-2: git·gh는 글 명령이 아니다(별칭·pager·ssh 명령으로 실행)
                "git -c alias.p='!python3 $S/db_pr.py publish wt #' p",
                "git -c core.pager='python3 $S/db_pr.py publish wt #' log",
                "GIT_SSH_COMMAND='python3 $S/db_pr.py publish wt #' git fetch",
                "git -c alias.x='!sh' x <<'EOF'\npython3 $S/db_pr.py publish wt\nEOF",
                # 그래서 git·gh 글(커밋 메시지·PR 본문)도 ask다(오판, 싸다)
                'git commit -m "db_pr.py publish 고침"', "git commit -F - <<'EOF'\nfix db_pr.py publish\nEOF",
                'gh pr create --title t --body "python3 db_pr.py publish 결과"',
                # P0-3: 인용·`\` 바로 앞의 `$S`
                'S=/p/; python3 "$S"d""b_pr.py publish wt', 'python3 $S"d"b_pr.py publish wt',
                'python3 "$S"db\\_pr.py publish wt', "python3 \"$S\"$'d'b_pr.py publish wt", "python3 $S'd'b_pr.py publish wt",
                # P1: 낱말 안의 줄 이음(bash는 빈 글로 잇는다)
                "python3 $S/db_pr.py pub\\\nlish wt", "python3 $S/db\\\n_pr.py publish wt",
                # H-A1 r6: 인용·주석 안 `<<EOF`는 heredoc이 아니다(옛 한계 — 가짜 heredoc)
                "echo \"<<EOF\"\npython3 $S/db_pr.py publish wt\nEOF", "ls # <<EOF\npython3 $S/db_pr.py publish wt\nEOF"):
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "ask" and "규칙 7" in out["permissionDecisionReason"], cmd
    for cmd in ("cat > notes.md <<'EOF'\npython3 db_pr.py publish wt\nEOF", "cat /w/MOCK-1/publish.json",
                f"python3 {r}/db_pr.py summary wt > /w/MOCK-1/publish-preview.md",
                f"sed -n 1,20p {r}/db_pr.py {r}/dbpr/publish.py",
                # 남는 한계
                "bash /w/push.sh", f"P=pub; python3 {r}/db_pr.py ${{P}}lish wt", f"X=db; python3 {r}/${{X}}_pr.py publish wt"):
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
    # 다른 MCP 서버의 쓰기형 도구는 규칙 2가 아니라 규칙 11 ask다(4-c — 대상 레포를 보지 않는다), 읽기형은 통과
    out = guard(ws, "mcp__other-server__create_issue", {}, ws.base)
    assert decision(out) == "ask" and "규칙 7·11" in out["permissionDecisionReason"]
    assert decision(guard(ws, "mcp__other-server__get_issue", {}, ws.base)) is None
    # 설정되지 않은 서버라도 이름에 jira/atlassian이 들면 쓰기형 도구는 거부, 읽기형은 통과
    for tool in ("mcp__jira-prod__add_comment", "mcp__atlassian__transition_issue", "mcp__mock-jira-2__jira_add_comment"):
        out = guard(ws, tool, {}, ws.base)
        assert decision(out) == "deny" and "Jira/Atlassian" in out["permissionDecisionReason"], tool
    assert decision(guard(ws, "mcp__atlassian__search_issues", {}, ws.base)) is None
    # read_tools가 비어 있으면 그 서버 도구는 모두 거부
    cfg_path = ws.home / "config.yaml"
    saved = cfg_path.read_text(encoding="utf-8")
    try:
        ws.json("config.py", ["set", "tracker.read_tools", "[]"])
        assert decision(guard(ws, JIRA_TOOLS[0], {}, ws.base)) == "deny"
    finally:
        cfg_path.write_text(saved, encoding="utf-8")
    # tracker.mcp_server가 비어 있어도(setup 전) 이름 기반 거부는 적용하고 경고한다
    root = plugin_root("no-jira-server", tracker={"exclude_servers": []})
    home = tmp("tt-home-")
    for tool, want in (("mcp__mock-jira__jira_add_comment", "deny"), ("mcp__mock-jira__jira_fetch_ticket", None)):
        event = {"tool_name": tool, "tool_input": {}, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home}, stdin=json.dumps(event))
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert proc.returncode == 0 and decision(out) == want and "tracker.mcp_server" in proc.stderr, tool


def _jira(server: str, get_issue: str) -> dict:
    """테스트 헬퍼 site-defaults의 jira 블록에서 서버·get_issue 이름만 바꾼 것."""
    base = yaml.safe_load((REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8"))["tracker"]
    return {**base, "mcp_server": server, "exclude_servers": [], "tools": {"get_issue": get_issue},
            "read_tools": [get_issue], "isolation_confirmed": True}


def test_guard_jira_server_name_is_normalized():
    """R-2: 세션 도구 이름은 서버 이름의 `[^A-Za-z0-9_-]`를 `_`로 쓴다(관측 기반 추정, S1 확인). 플러그인 번들 서버는
    `mcp__plugin_…` 접두사라 `tracker.mcp_server`와 다르다 — `tracker.tools` 이름의 접두사로도 판정한다."""
    home = tmp("tt-home-")

    def judge(root: Path, tool: str) -> str | None:
        event = {"tool_name": tool, "tool_input": {}, "cwd": str(home)}
        proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home}, stdin=json.dumps(event))
        assert proc.returncode == 0, proc.stderr
        return decision(json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None)

    dot = plugin_root("jira-dot", tracker=_jira("jira.corp", "mcp__jira.corp__get_issue"))
    assert judge(dot, "mcp__jira_corp__create_issue") == "deny"
    assert judge(dot, "mcp__jira.corp__create_issue") == "deny"
    assert judge(dot, "mcp__jira_corp__get_issue") is None
    bundled = plugin_root("jira-bundled", tracker=_jira("jira", "mcp__plugin_corp_jira__get_issue"))
    assert judge(bundled, "mcp__plugin_corp_jira__add_comment") == "deny"
    assert judge(bundled, "mcp__plugin_corp_jira__get_issue") is None
    assert judge(bundled, "mcp__jira__add_comment") == "deny"          # mcp_server 접두사도 그대로
    assert judge(bundled, "mcp__other__add_comment") is None


NOTE_TOOL = "mcp__mock-jira__jira_ticket_add_note"     # site-defaults(example) jira.write_tools.add_comment


def _approve(ws: Workspace, job_key: str, body: str, **over) -> Path:
    """`issue_post.py approve`가 쓰는 승인 기록을 직접 만든다(guard 판정만 본다)."""
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import issuepost
    at = issuepost.now()
    record = {"schema": 1, "key": job_key, "tool": NOTE_TOOL, "key_arg": "ticket", "kind": "jira",
              "body_sha256": issuepost.body_sha256(body),
              "format": "jira-wiki", "request_hash": "0" * 16, "approved_at": issuepost.iso(at),
              "expires_at": issuepost.iso(issuepost.expires(at)), "used_at": None, **over}
    job = ws.job_dir(job_key)
    job.mkdir(parents=True, exist_ok=True)
    (job / "post.approved.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (job / "post.md").write_text(issuepost.normalize_body(body) + "\n", encoding="utf-8")
    (job / "post.result.json").unlink(missing_ok=True)
    return job


def test_guard_jira_post_requires_approval():
    """규칙 2 예외: 설정된 코멘트 도구는 승인 기록(인자 집합·키·도구·정규화 본문 sha256·30분·1회용)과 맞을 때만 ask,
    그 밖에는 deny. 다른 Jira 쓰기 도구는 승인 기록이 있어도 deny(읽기 전용)."""
    ws = shared()
    body = "h3. PROBLEM\n* Jira: MOCK-7101\n\nh3. CAUSE\n* 분류: 후보 없음"
    _approve(ws, "MOCK-7101", body)

    def post(tool_input: dict, tool: str = NOTE_TOOL, **kw) -> dict | None:
        return guard(ws, tool, tool_input, ws.base, **kw)

    ok = post({"ticket": "MOCK-7101", "text": body})                                       # (j) 정상 → ask
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import issuepost
    assert decision(ok) == "ask" and "MOCK-7101" in ok["permissionDecisionReason"]
    assert issuepost.body_sha256(body)[:12] in ok["permissionDecisionReason"]
    assert decision(post({"ticket": "MOCK-7101", "text": body.replace("\n", "\r\n")})) == "ask"     # (c) CRLF만 다름
    assert decision(post({"ticket": "MOCK-7101", "text": body + "\n"})) == "ask"                 # 끝 줄바꿈 하나
    # 정규화 sha는 같아도 실제로 올라가는 글자가 post.md와 다르면 거부(줄 끝 공백·앞뒤 빈 줄·NFD)
    import unicodedata
    for variant in (body.replace("\n", "  \n"), "\n" + body + "\n\n", unicodedata.normalize("NFD", body)):
        out = post({"ticket": "MOCK-7101", "text": variant})
        assert decision(out) == "deny" and "글자 그대로" in out["permissionDecisionReason"], repr(variant[:20])
    assert decision(post({"ticket": "MOCK-7199", "text": body})) == "deny"                # (a) 승인 기록 없음
    out = post({"ticket": "MOCK-7101", "text": body + "!"})                               # (b) 본문 다름
    assert decision(out) == "deny" and "sha256" in out["permissionDecisionReason"]
    _approve(ws, "MOCK-7102", body, key="MOCK-7101")                                      # (d) 기록의 키가 다름
    assert decision(post({"ticket": "MOCK-7102", "text": body})) == "deny"
    for tool in ("mcp__mock-jira__jira_post_comment", "mcp__mock-jira__jira_move_ticket",
                 "mcp__mock-jira__jira_add_comment"):                                    # (e) 다른 쓰기 도구
        out = post({"ticket": "MOCK-7101", "body": body}, tool=tool)
        assert decision(out) == "deny" and "Jira 읽기 전용" in out["permissionDecisionReason"], tool
    assert decision(post({"ticket": "MOCK-7101", "text": body, "status": "Resolved"})) == "deny"   # (f) 모르는 인자
    _approve(ws, "MOCK-7103", body, expires_at="2000-01-01T00:00:00+00:00")             # (g) 만료
    out = post({"ticket": "MOCK-7103", "text": body})
    assert decision(out) == "deny" and "만료" in out["permissionDecisionReason"]
    _approve(ws, "MOCK-7104", body, used_at="2026-01-01T00:00:00+00:00")                # (h) 1회용
    assert decision(post({"ticket": "MOCK-7104", "text": body})) == "deny"
    job = _approve(ws, "MOCK-7105", body)
    (job / "post.result.json").write_text(json.dumps({"status": "posted", "body_sha256": issuepost.body_sha256(body)}),
                                          encoding="utf-8")
    out = post({"ticket": "MOCK-7105", "text": body})
    assert decision(out) == "deny" and "이미 게시" in out["permissionDecisionReason"]
    job = _approve(ws, "MOCK-7107", body)                                               # 결과 불명은 늘 거부
    (job / "post.result.json").write_text(json.dumps({"status": "unknown", "body_sha256": issuepost.body_sha256(body)}),
                                          encoding="utf-8")
    assert "불명" in post({"ticket": "MOCK-7107", "text": body})["permissionDecisionReason"]
    # --again 승인(again: true)이면 같은 본문의 posted 이력을 건너뛴다(만료·used_at은 그대로)
    job = _approve(ws, "MOCK-7108", body, again=True)
    (job / "post.result.json").write_text(json.dumps({"status": "posted", "body_sha256": issuepost.body_sha256(body)}),
                                          encoding="utf-8")
    assert decision(post({"ticket": "MOCK-7108", "text": body})) == "ask"
    job = _approve(ws, "MOCK-7108", body, again=True, used_at="2026-01-01T00:00:00+00:00")
    assert decision(post({"ticket": "MOCK-7108", "text": body})) == "deny"
    (job / "post.md").unlink()                                                          # post.md 없음
    _approve(ws, "MOCK-7109", body)
    (ws.job_dir("MOCK-7109") / "post.md").unlink()
    assert "post.md" in post({"ticket": "MOCK-7109", "text": body})["permissionDecisionReason"]
    job = _approve(ws, "MOCK-7106", body)
    (job / "post.approved.json").write_text("{깨짐", encoding="utf-8")                   # (i) 손상
    out = post({"ticket": "MOCK-7106", "text": body})
    assert decision(out) == "deny" and "내부 오류" not in out["permissionDecisionReason"]
    for key in ("../MOCK-7101", "MOCK-7101/../MOCK-7101", 7101):                         # (n) 경로 탈출·형식
        assert decision(post({"ticket": key, "text": body})) == "deny", key
    # (m) 사용자 config 없음: 승인 기록을 찾을 수 없다
    out = post({"ticket": "MOCK-7101", "text": body}, env={"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")})
    assert decision(out) == "deny" and "사용자 config 없음" in out["permissionDecisionReason"]
    # (k) 코멘트 도구를 read_tools에 넣어도 승인을 건너뛸 수 없다(설정 오류로 거부)
    cfg_path = ws.home / "config.yaml"
    saved = cfg_path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(saved)                       # config.py set은 쓰기형 이름을 거부하므로 손으로 넣는다
        data["tracker"]["read_tools"] = [*JIRA_TOOLS, NOTE_TOOL]
        cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        out = post({"ticket": "MOCK-7101", "text": body})
        assert decision(out) == "deny" and "설정 오류" in out["permissionDecisionReason"]
        cfg_path.write_text(saved, encoding="utf-8")
        ws.json("config.py", ["set", "tracker.write_tools.add_comment.extra_args", '{"visibility": "internal"}'])
        assert decision(post({"ticket": "MOCK-7101", "text": body, "visibility": "internal"})) == "ask"
        assert decision(post({"ticket": "MOCK-7101", "text": body, "visibility": "public"})) == "deny"   # (f) 고정 값
        assert decision(post({"ticket": "MOCK-7101", "text": body})) == "deny"
    finally:
        cfg_path.write_text(saved, encoding="utf-8")
    # (l) 코멘트 도구 서버가 Jira 서버가 아니면 무효: 그 도구 호출은 거부
    home = tmp("tt-home-")
    root = plugin_root("jira-dot", tracker=_jira("jira.corp", "mcp__jira.corp__get_issue"))
    event = {"tool_name": NOTE_TOOL, "tool_input": {"ticket": "MOCK-7101", "text": body}, "cwd": str(home)}
    proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home}, stdin=json.dumps(event))
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert decision(out) == "deny" and "Jira 서버" in out["permissionDecisionReason"]


def test_guard_denies_direct_writes_to_post_records():
    """승인·결과 기록(`<work_dir>/<KEY>/post.approved.json`·`post.result.json`)은 approve·jira_bridge만 쓴다:
    파일 도구와 Bash 파일 쓰기(규칙 8과 같은 판별)는 거부. 같은 JOB의 다른 파일(post.fill.json)은 그대로."""
    ws = shared()
    job = ws.job_dir("MOCK-7201")
    job.mkdir(parents=True, exist_ok=True)
    for name in ("post.approved.json", "post.result.json"):
        for tool in ("Write", "Edit", "MultiEdit"):
            out = guard(ws, tool, {"file_path": str(job / name), "content": "{}"}, ws.base)
            assert decision(out) == "deny" and "approve" in out["permissionDecisionReason"], (tool, name)
        for cmd in (f"echo '{{}}' > {job / name}", f"rm -f {job / name}", f"cp /tmp/x {job / name}",
                    f"cd {job} && tee {name} < /dev/null", f"sed -i s/a/b/ {job / name}"):
            assert decision(bash(ws, cmd, ws.base)) == "deny", cmd
    assert decision(guard(ws, "Write", {"file_path": str(job / "post.fill.json"), "content": "{}"}, ws.base)) is None
    assert decision(bash(ws, f"cat {job / 'post.approved.json'}", ws.base)) is None
    assert decision(bash(ws, f"echo x > {job / 'post.fill.json'}", ws.base)) is None


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
    for cmd in ("time -p git commit --no-verify -m x", "env -u FOO git push --no-verify origin HEAD:main",
                "timeout -k 5 60 git push --no-verify origin HEAD:main", "nice git -c core.hooksPath=/dev/null commit -m x",
                'env -S "git push --no-verify origin HEAD:main"', "sudo -u x git commit -n -m x",
                # 짧은 옵션 묶음 끝의 값 옵션(-Eu x)과 묶음 안의 -S
                "sudo -Eu x git commit --no-verify -m x", "sudo -Hu x git push --no-verify origin HEAD:main",
                'env -vS "git push --no-verify origin HEAD:main"', "env -uFOO git push --no-verify origin HEAD:main"):
        assert decision(bash(ws, cmd, c)) == "deny", cmd
    assert decision(bash(ws, f"sudo -Eu x {publish}", ws.base)) == "ask"
    # env -C·sudo -D는 작업 디렉토리를 바꾼다(값이 붙은 형태 포함): 다른 곳에서 불러도 이슈 DB로 판정한다
    for cmd in (f'env -C "{c}" git push --no-verify origin HEAD:main', f'sudo -D "{c}" git push --no-verify origin HEAD:main',
                f'env -C"{c}" git push --no-verify origin HEAD:main', f'sudo -D"{c}" git push --no-verify origin HEAD:main',
                f'env --chdir="{c}" git push --no-verify origin HEAD:main'):
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
    (d / "issue_raw.json").write_text("{}", encoding="utf-8")
    for legacy in ("jira_raw.json", "jira.json", "jira_meta.json"):      # 개명 전 원문 파일도 막는다(방어 목록), 마스킹본은 허용
        (d / legacy).write_text("{}", encoding="utf-8")
    for name in ("timeline.md", "report.md", "commit-message.txt"):
        (d / name).write_text("text\n", encoding="utf-8")
    fx = ws.work / "JOB" / "fixtures"
    fx.mkdir(parents=True, exist_ok=True)
    (fx / "X.log").write_text(LOGCAT, encoding="utf-8")
    deny = ["cat x.log", "cat a.txt x.log", "cat < x.log", 'sh -c "cat x.log"', "cat logs/*.log",
            "head -c 5000 x.log", "tail -c5000 x.log", "unzip -p br.zip", "unzip -pq br.zip", "strings br.zip",
            f"cat {d}/issue_raw.json", f"cat {d}/jira_raw.json",
            "echo hi && cat x.log",
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
        assert "logs-masked/<이름>" in out["permissionDecisionReason"], cmd      # 종합 리뷰 G①: 원문 대신 마스킹 사본을 안내
    allow = [f"cat {d}/jira.json", f"less {d}/jira_meta.json", "grep -n RILJ x.log", "sed -n 1,20p x.log", "head -n 20 x.log", "wc -l x.log", "unzip -l br.zip",
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


RAW_WAIT = "탐색·심층 분석을 묻기 전·답 대기 중·탐색 중이면 grep·sed·Read로도 원문을 보지 않는다(SKILL 5-2·explore.md)."


def test_guard_raw_log_deny_text_names_ask_wait_but_grants_nothing_new():
    """규칙 10 거부 문구는 5-1·5-2 답 전 원문 열람 금지를 알린다(안내만 — 막는 규칙은 그대로라 동의 뒤·거절 뒤 구간 읽기는 통과)."""
    ws = shared()
    d = tmp("tt-raw-")
    (d / "x.log").write_text(LOGCAT, encoding="utf-8")
    for cmd in ("cat x.log", "head -c 5000 x.log", "grep -n '' x.log"):
        out = bash(ws, cmd, d)
        assert decision(out) == "deny" and RAW_WAIT in out["permissionDecisionReason"], cmd
        assert "동의 뒤" not in out["permissionDecisionReason"]          # 동의 뒤 grep을 허락하는 말은 없다
    for cmd in ("grep -n RILJ x.log", "sed -n 10,40p x.log", "head -n 20 x.log", "wc -l x.log",
                f"python3 {plugin_root()}/scripts/parse_logcat.py cut x.log --around 2026-10-06T12:00:05+09:00 --out cut.log"):
        assert decision(bash(ws, cmd, d)) is None, cmd


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


_B64 = "bXV0YXRpb24ge2FkZFB1bGxSZXF1ZXN0UmV2aWV3KGlucHV0OntwdWxsUmVxdWVzdElkOiJ4IixldmVudDpBUFBST1ZFfSl7Y2xpZW50TXV0YXRpb25JZH19"
_DECOY = "cat <<'EOF' >/dev/null\nx\nEOF\n"
_PRE = f"Q=$(echo {_B64} | base64 -d); "
_CONT = chr(92) + "\n"          # 인용하지 않은 heredoc 본문의 줄 이음(bash가 줄을 잇는다)
# 읽은 본문으로 보면 안 되는 heredoc·stdin(4-c 4회차 리뷰): 미끼 heredoc + 끝 표시 접두(`EOF-`·`'EOF'X`·`EOF.x`), `bash -c` 문자열
# 안 heredoc, 파이프·`<<<`·`<` stdin, 그 호출의 heredoc 뒤 `<`, 줄 이음 — 기본(ask)
HEREDOC_UNREAD = (
    _PRE + _DECOY + 'gh api graphql -f query="$(cat <<EOF-\n$Q\nEOF-\n)"',
    _PRE + _DECOY + "gh api graphql -f query=\"$(cat <<'EOF'X\n$Q\nEOFX\n)\"",
    _PRE + _DECOY + 'gh api graphql -f query="$(cat <<EOF.x\n$Q\nEOF.x\n)"',
    _PRE + _DECOY + "bash -c 'gh api graphql -f query=\"$(cat <<EOF\n$Q\nEOF\n)\"'",
    _DECOY + f"echo {_B64} | base64 -d | gh api graphql -F query=@-",
    f"cat <<'EOF' | base64 -d | gh api graphql -F query=@-\n{_B64}\nEOF",
    _PRE + _DECOY + 'gh api graphql -F query=@- <<<"$Q"',
    _DECOY + "gh api graphql -F query=@- < x.graphql",
    "gh api graphql -F query=@- <<'EOF' < x.graphql\nquery{viewer{login}}\nEOF",
    "gh api graphql -F query=@- <<EOF\nmut" + _CONT + "ation{addPullRequestRev" + _CONT
    + 'iew(input:{pullRequestId:"x",event:APPR' + _CONT + "OVE}){__typename}}\nEOF",
    'gh api graphql -f query="$(cat <<EOF\nmut' + _CONT + "ation{addPullRequestRev" + _CONT
    + 'iew(input:{pullRequestId:\\"x\\",event:APPR' + _CONT + 'OVE}){__typename}}\nEOF\n)"')


def test_guard_gh_coarse_judgment_ignores_target_repo():
    """규칙 11(4-c 거친 판정): 대상 레포(`-R`·`GH_REPO`·URL·엔드포인트·cwd 원격)를 풀지 않는다 — gh 쓰기·모르는 그룹은 이슈 DB가
    아닌 레포에서도 ask(병합 계열은 병합 사유), 읽기는 판정하지 않는다. 사용자 config(issue_db.remote)가 없으면 보지 않는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    plugin_repo = _repo_with_origin("https://ghe.mock.invalid/other/repo")
    wt = ws.work / "wt-gh"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    try:
        cases = [("gh pr list --state open", c, None), ("gh pr view 3", wt, None), ("gh auth status", c, None),
                 ("gh issue list -R other/x", plain, None), ("gh repo clone other/x", plain, None),
                 (f"gh api repos/{DB_SLUG}/pulls", plugin_repo, None), ("gh api --method=GET repos/o/r/contents/x", plain, None),
                 ("gh api graphql -f query='query { viewer { login } }'", c, None), ("gh", plain, None),
                 (f"gh pr create -R {DB_SLUG} -t x", plugin_repo, "ask"), ("gh pr create -t x", plugin_repo, "ask"),
                 ("gh pr edit 3 --add-label x", c, "ask"), ("gh api -X PUT repos/other/repo/contents/x", c, "ask"),
                 ("gh api -F name=v repos/o/r/labels", plain, "ask"), ("gh issue comment 1 -b hi", plain, "ask"),
                 ("gh release create v1", plain, "ask"), ("gh run rerun 5", plain, "ask"), ("gh repo edit --description y", plain, "ask"),
                 ("gh alias list", plain, None), ("gh alias delete m", plain, "ask"),
                 ("gh foo bar", plain, "ask"), ("gh lgtm 3", plain, "ask")]                # 모르는 그룹(별칭 실행 포함)
        for cmd in ("gh pr checkout 3", "gh co 3", "gh 2>/dev/null pr checkout 3", "gh -R other/x pr checkout 3"):
            out = bash(ws, cmd, c)                                              # clone 본체의 브랜치를 바꾼다(규칙 8)
            assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
        assert decision(bash(ws, "gh pr checkout 3", plain)) is None
        for cmd, cwd, want in cases:
            out = bash(ws, cmd, cwd)
            assert decision(out) == want, (cmd, cwd)
            if want:
                assert "대상 레포를 보지 않는다" in out["permissionDecisionReason"] and "머지" not in out["permissionDecisionReason"]
        # 글자를 알 수 있는 셸 본문(heredoc·있는 파일)은 읽는다 — 읽기 GraphQL은 셸 값 변수가 있어도 판정하지 않는다. 못 읽은
        # `query`는 쓰기(ask)
        (plain / "q.graphql").write_text("query { viewer { login } }", encoding="utf-8")
        hd = "gh api graphql -f query=\"$(cat <<'EOF'\n{q}\nEOF\n)\""
        for cmd, cwd, want in ((hd.format(q="query { viewer { login } }"), c, None),
                               ('gh api graphql -f query="$(cat q.graphql)"', plain, None),
                               ("gh api graphql -f query='query($o:String!){ repository(owner:$o, name:\"x\"){ id } }' "
                                "-f o=\"$OWNER\"", plain, None),
                               ("gh api graphql -fquery='query($o:String!){ repository(owner:$o, name:\"x\"){ id } }' -f o=x",
                                plain, None),
                               ('gh api "$EP"', plain, None), ('gh pr view "$N" --json state', c, None),
                               ('gh api graphql -f query="$(cat none.graphql)"', plain, "ask"),
                               ('gh api graphql -f query="$Q"', plain, "ask"),
                               ('gh api graphql -f query="$(cat <<EOF\n$(echo bXV0YXRpb24ge2FkZFB1bGxSZXF1ZXN0UmV2aWV3KGlucHV0OntwdWxsUmVxdWVzdElkOiJ4IixldmVudDpBUFBST1ZFfSl7Y2xpZW50TXV0YXRpb25JZH19 | base64 -d)\nEOF\n)"', plain, "ask"),
                               ('gh api graphql -f query="$(cat <<EOF\n$Q\nEOF\n)"', plain, "ask"),
                               ('gh api graphql -f query="$(cat <<EOF\n`echo bXV0YXRpb24ge2FkZFB1bGxSZXF1ZXN0UmV2aWV3KGlucHV0OntwdWxsUmVxdWVzdElkOiJ4IixldmVudDpBUFBST1ZFfSl7Y2xpZW50TXV0YXRpb25JZH19 | base64 -d`\nEOF\n)"', plain, "ask"),
                               ('gh api graphql -F query=@- <<EOF\n$(echo bXV0YXRpb24ge2FkZFB1bGxSZXF1ZXN0UmV2aWV3KGlucHV0OntwdWxsUmVxdWVzdElkOiJ4IixldmVudDpBUFBST1ZFfSl7Y2xpZW50TXV0YXRpb25JZH19 | base64 -d)\nEOF', plain, "ask"),
                               ("gh api graphql -f query=\"$(cat <<'EOF'\n$Q\nEOF\n)\"", plain, None),     # 인용: 글자 그대로
                               ('gh api graphql -f query="$(cat <<\\EOF\n$Q\nEOF\n)"', plain, None),
                               ('gh api graphql -f query="$(cat <<"EOF"\n$Q\nEOF\n)"', plain, None),
                               ("gh api graphql -F query=@- <<'EOF'\nquery { viewer { login } } $Q\nEOF", plain, None),
                               ('gh api graphql -f query="$(cat <<EOF\nquery { viewer { login } } ${Q}\nEOF\n)"', plain, "ask"),
                               ('Q=$(echo bXV0YXRpb24ge2FkZFB1bGxSZXF1ZXN0UmV2aWV3KGlucHV0OntwdWxsUmVxdWVzdElkOiJ4IixldmVudDpBUFBST1ZFfSl7Y2xpZW50TXV0YXRpb25JZH19 | base64 -d); gh api graphql -f query="$Q"', plain, "ask"),
                               ('gh api graphql -f query="$(cat <<EOF\nquery { viewer { login } }\nEOF\n)"', plain, None),
                               ("cat x.graphql | gh api graphql -F query=@-", plain, "ask"),
                               *((cmd, plain, "ask") for cmd in HEREDOC_UNREAD)):
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
        for cmd, cwd in (("gh pr merge 12 --admin", wt), ("gh pr merge 3 --squash", plugin_repo), ("gh pr merge 3", plain),
                         ("gh api -X PUT repos/other/repo/pulls/3/merge", plain),
                         ("gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'", c)):
            out = bash(ws, cmd, cwd)
            assert decision(out) == "ask" and "머지" in out["permissionDecisionReason"], (cmd, cwd)
            assert "다른 레포여도 묻는다" in out["permissionDecisionReason"], cmd
        # 사용자 config가 없으면 gh 규칙을 적용하지 않는다
        empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}
        assert decision(bash(ws, f"gh pr merge 1 -R {DB_SLUG}", plain, env=empty)) is None
        assert decision(bash(ws, "gh pr create -t x", plain, env=empty)) is None
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_mcp_coarse_judgment_ignores_target_repo():
    """규칙 11 MCP(4-c 거친 판정): 대상 레포 인자를 풀지 않는다. Approve·기각은 이름 단어나 동작 칸(`event`·`action`·`method`·
    `*event`, 정규화 키·중첩)으로 거부, 병합·자동 병합은 ask, 그 밖 쓰기형 도구는 ask(이슈 DB가 아니어도), 읽기형은 판정하지
    않는다. setup 전(config에 issue_db 없음)은 판정하지 않는다."""
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db"}
    merge = "mcp__github__merge_pull_request"
    review = "mcp__github__pull_request_review_write"
    rows = [("mcp__github__push_files", db, "ask"), ("mcp__github__create_or_update_file", {"owner": "other", "repo": "x"}, "ask"),
            ("mcp__github__update_pull_request", {"url": f"https://ghe.mock.invalid/{DB_SLUG}/pull/3"}, "ask"),
            ("mcp__github__create_repository", {"name": "x"}, "ask"), ("mcp__gdrive__create_file", {"name": "x"}, "ask"),
            ("mcp__github__push_files", {"repository_id": 42}, "ask"),
            ("mcp__github__get_file_contents", db, None), ("mcp__github__get_file_contents", {"repo_full_name": "$R"}, None),
            ("mcp__github__list_pull_requests", {}, None),
            (merge, {"repository_full_name": DB_SLUG}, "ask"), (merge, {"url": "https://ghe.mock.invalid/other/x/pull/3"}, "ask"),
            (merge, {"pull_number": 3}, "ask"), ("mcp__github__pr_write", {"repo_full_name": DB_SLUG, "action": "merge"}, "ask"),
            (review, {**db, "method": "create", "event": "APPROVE"}, "deny"),
            (review, {"repo_full_name": DB_SLUG, "review_event": "APPROVE"}, "deny"),
            (review, {"repo_full_name": DB_SLUG, "action": "APPROVE"}, "deny"),
            (review, {"pr": {"repository": "other/x", "reviewEvent": "approve"}}, "deny"),      # 중첩·정규화 키
            (review, {"owner": "other", "repo": "x", "action": "dismiss"}, "deny")]
    for tool, tool_input, want in rows:
        out = guard(ws, tool, tool_input, ws.base)
        assert decision(out) == want, (tool, tool_input)
        if want == "ask":
            assert ("머지" in out["permissionDecisionReason"]) == ("merge" in tool or "merge" in str(tool_input)), tool
    empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}
    assert decision(guard(ws, "mcp__github__push_files", db, ws.base, env=empty)) is None
    assert decision(guard(ws, review, {**db, "event": "APPROVE"}, ws.base, env=empty)) is None


def test_guard_git_dir_work_tree_and_env_forms():
    ws = shared()
    c = ws.clone
    deny = [f'git --git-dir "{c}/.git" --work-tree "{c}" commit --no-verify -m x',
            f'git --work-tree="{c}" --git-dir="{c}/.git" commit -n -m x',
            f'GIT_DIR="{c}/.git" git push --no-verify origin HEAD:main',
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


def test_guard_git_common_dir_with_git_dir():
    """`GIT_DIR`와 `GIT_COMMON_DIR`가 둘 다 있으면 git은 config·객체를 `GIT_COMMON_DIR`에서 쓴다 — 둘 중 하나라도 이슈 DB면 이슈 DB."""
    ws = shared()
    C = ws.clone.as_posix()
    fake = tmp("tt-fake-gitdir-")
    (fake / "HEAD").write_text("ref: refs/heads/main\n")
    F, plain = fake.as_posix(), tmp("tt-gcd-plain-")
    for cmd, want in ((f"GIT_DIR={F} GIT_COMMON_DIR={C}/.git git push origin HEAD:main", "ask"),
                      (f"GIT_DIR={F} GIT_COMMON_DIR={C}/.git git update-ref refs/remotes/origin/main HEAD", "deny"),
                      (f"GIT_DIR={C}/.git GIT_COMMON_DIR={F} git update-ref refs/remotes/origin/main HEAD", "deny")):
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_git_dir_forms_under_safe_bare_repository_explicit():
    """git 2.38~2.44 + `safe.bareRepository=explicit`면 `.git` 안에서 부른 rev-parse가 128 — guard는 `.git` 앞 폴더에서
    다시 물어 이슈 DB로 본다(2.45+는 이 설정에서도 처음 호출이 된다). 링크 `S -> <clone>/.git`는 실제 경로로 본다."""
    ws = shared()
    c, C = ws.clone, ws.clone.as_posix()
    explicit = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.bareRepository", "GIT_CONFIG_VALUE_0": "explicit"}
    probe = subprocess.run(["git", "-C", str(c / ".git"), "rev-parse", "--git-dir"], capture_output=True, text=True,
                           env={**os.environ, **explicit})
    if probe.returncode == 0:
        import pytest
        ver =subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
        pytest.skip(f"{ver}: explicit에서도 `.git` 안의 rev-parse가 된다(2.38 미만·2.45+) — 재질문 경로를 시험할 수 없다")
    env = ws.env(**explicit)
    plain = tmp("tt-gh-plain-")
    rows = [(f"git --git-dir={C}/.git push origin HEAD:main", plain, "ask"),
            (f"git --git-dir={C}/.git update-ref refs/remotes/origin/main HEAD", plain, "deny"),
            (f'GIT_DIR="{C}/.git" git push --no-verify origin HEAD:main', plain, "deny"),
            ("git update-ref refs/remotes/origin/main HEAD", c / ".git", "deny")]
    try:
        (plain / "S").symlink_to(c / ".git", target_is_directory=True)
        S = (plain / "S").as_posix()
        rows += [(f"GIT_DIR={S} git push origin HEAD:main", plain, "ask"),
                 (f"git -C {S} update-ref refs/remotes/origin/main HEAD", plain, "deny")]
    except OSError:
        pass    # 심볼릭 링크를 못 만드는 환경(Windows 권한 등)은 링크 꼴만 건너뛴다
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd, env=env)) == want, cmd


def test_guard_rev_parse_retries_outside_dot_git_without_host_git(monkeypatch):
    """위 시험의 재질문 경로(`guard._rev_parse`)를 호스트 git 버전과 무관하게 지킨다(위 시험은 git 2.38~2.44에서만 돈다):
    가짜 `_git`은 실제 경로에 `.git` 조각이 있으면 128 — 재질문·realpath·`.git` 조각 범위 중 하나라도 빠지면 None이 된다."""
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import guard as g

    def fake_git(d, *args):
        bad = ".git" in Path(os.path.realpath(d)).parts
        return subprocess.CompletedProcess([], 128 if bad else 0, "" if bad else f"{d}/.git\n", "")

    monkeypatch.setattr(g, "_git", fake_git)
    base = tmp("tt-gh-rp-")
    clone = base / "c"
    (clone / ".git" / "refs").mkdir(parents=True)
    cwds = [clone / ".git", clone / ".git" / "refs"]
    try:
        (base / "S").symlink_to(clone / ".git", target_is_directory=True)
        cwds.append(base / "S")
    except OSError:
        pass    # 심볼릭 링크를 못 만드는 환경(Windows 권한 등)은 링크 꼴만 건너뛴다
    for cwd in cwds:
        assert g._rev_parse(cwd, "--absolute-git-dir") == g._norm(f"{os.path.realpath(clone)}/.git"), cwd


def test_guard_eval_and_xargs_wrappers():
    ws = shared()
    c = ws.clone
    assert decision(bash(ws, f'eval "git -C {c} push --no-verify origin HEAD:refs/heads/main"', ws.base)) == "deny"
    assert decision(bash(ws, f"xargs -n1 git -C {c} push --no-verify origin HEAD:main < list", ws.base)) == "deny"
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
    for cmd, cwd in ((f'echo x > "{c}/issues/MOCK-1.yaml"', ws.base), (f'echo x >>"{c}/README.md"', ws.base),
                     (f'echo x &> "{c}/a.txt"', ws.base), (f'echo x | tee -a "{c}/README.md"', ws.base),
                     (f'sed -i s/a/b/ "{c}/x.yaml"', ws.base), (f'perl -pi -e s/a/b/ "{c}/x.yaml"', ws.base),
                     (f'rm -rf "{c}/causes"', ws.base), (f'cp /tmp/x "{c}/README.md"', ws.base),
                     ("touch new.txt", c), (f'sort -o "{c}/x" /tmp/y', ws.base), (f'echo x > "{c}/.git/hooks/x"', ws.base)):
        out = bash(ws, cmd, cwd)
        assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
    for cmd in (f'echo x > "{ws.work}/MOCK-1/wt/issues/MOCK-1.yaml"', f'cp "{c}/README.md" /tmp/x',
                f'grep -n x "{c}/README.md" > /tmp/out 2>&1', f'sed -n 1,5p "{c}/README.md"',
                f'sed s/a/b/ "{c}/README.md" > /tmp/out', f'cat "{c}/README.md" >&2'):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd



def test_guard_blocks_plugin_script_outputs_into_clone():
    """규칙 8(F2): 플러그인 스크립트의 출력 인자(`--out`·`--preview`·`--meta-out`, `--in-place`·`--consume`의 위치 인자)가
    clone 안이면 거부. `db_build.py --write`가 clone을 고치면 ask. work dir·/tmp·검사 모드는 판정 없음."""
    ws = shared()
    c, w = ws.clone, ws.work
    P = plugin_root() / "scripts"
    deny = [f"python3 {P}/mask_pii.py safe.txt --out {c}/CONTRIBUTING.md", f"python3 {P}/mask_pii.py a --out={c}/b.md",
            f"python3 {P}/mask_pii.py a --ou {c}/b.md", f"python3 {P}/mask_pii.py --in-place {c}/a.md",
            f"python3 -u {P}/parse_logcat.py cut a.log --around T --out {c}/c.log",
            f"python3 {P}/parse_logcat.py extract-bugreport b.zip --out {c}/bug",
            f"python3 {P}/db_review.py --out {c}/r.md", f"python3 {P}/triage.py run K --offline-db d --out {c}/job",
            f"python3 {P}/db_build.py --preview {c}/p", f"python3 {P}/jira_fields.py extract j.json --meta-out {c}/m.json",
            f"python3 {P}/jira_fields.py extract {c}/raw.json --consume",
            f"env A=1 timeout 5 python3 {P}/mask_pii.py a --out {c}/b.md",
            # F2 r2: 3자 이상 접두사는 유일성과 무관하게 출력 옵션(하위 명령마다 argparse 옵션 집합이 다르다)
            f"python3 {P}/triage.py explore K --o {c}/x", f"python3 {P}/triage.py module K --o={c}/x"]
    # F3 r2: `-m`·`-c`·`-`가 아닌 단일 대시 인터프리터 옵션은 플래그로 보고 스크립트를 찾는다
    deny += [f"python3 {f} {P}/mask_pii.py a --out {c}/b" for f in ("-q", "-P", "-bb", "-d", "-v", "-x", "-R", "-u",
                                                                    "-X dev", "-Wignore", "-uW ignore")]
    for cmd in deny:
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "deny" and "규칙 8" in out["permissionDecisionReason"], cmd
    out = bash(ws, f"python3 {P}/mask_pii.py a --out {w}/MOCK-1/post.approved.json", ws.base)
    assert decision(out) == "deny" and "규칙 2" in out["permissionDecisionReason"]
    assert decision(bash(ws, f"python3 {P}/db_build.py --write --db {c}", ws.base)) == "ask"
    assert decision(bash(ws, f"python3 {P}/db_build.py --write", c)) == "ask"
    for cmd in (f"python3 {P}/mask_pii.py a --out {ws.base}/o", f"python3 {P}/mask_pii.py a --out {w}/MOCK-1/o.txt",
                f"python3 {P}/mask_pii.py {c}/a.md", f"python3 {P}/mask_pii.py --check {c}/a.md",
                f"python3 {P}/mask_pii.py --check --in-place {c}/a", f"python3 {P}/mask_pii.py --events e --in-place {c}/a",
                f"python3 {P}/db_build.py --write --db {w}/wt"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd
    for o in (f"{c}/x", f"{w}/MOCK-1/x"):           # 탐색 `--with`는 `--module` 명령과 같은 판정
        cmd = f"python3 {P}/triage.py module K --for explore --module ofono/data --out {o}"
        assert decision(bash(ws, cmd.replace(" --out", " --with sim --out"), ws.base)) == decision(bash(ws, cmd, ws.base))
    for cmd in (f"python3 -c pass {P}/mask_pii.py a --out {c}/b", f"python3 -uc pass {P}/mask_pii.py a --out {c}/b"):
        out = bash(ws, cmd, ws.base)
        assert decision(out) != "deny" or "규칙 8" not in out["permissionDecisionReason"], cmd

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
                f'python3 "{ws.root}/scripts/db_pr.py" publish wt --branch issue/MOCK-1',
                f'S="python3 {ws.root}/scripts/"; ${{S}}db_pr.py publish wt', "$PY $S/db_pr.py publish wt",
                f'python3 "{ws.root}/scripts/db_pr.py" merge --job MOCK-1',
                f'python3 "{ws.root}/scripts/db_pr.py" request-review --job MOCK-1 --reviewer a,b',
                f'python3 "{ws.root}/scripts/module_eval.py" --module ofono/data --dry-run'):
        out, _ = judge("Bash", {"command": cmd})
        assert decision(out) == "ask" and "레포 판별 불가" in out["permissionDecisionReason"], cmd
    out, err = judge("Bash", {"command": "echo hi"})
    assert out is None and "의존성 없음" in err
    out, _ = judge("Write", {"file_path": str(ws.base / "x.txt")})
    assert decision(out) == "ask"
    # Approve·리뷰 기각 낱말은 대상 레포를 몰라도 거부(내부 오류를 입력으로 일으킬 수 있다 — 회귀 수정 R2). 병합 계열은 4-c부터
    # 다른 gh 쓰기와 같은 ask(서버 브랜치 보호가 막는다)
    b, q, rs = ws.base / "deg-approve.json", ws.base / "deg-review.graphql", ws.base / "deg-ruleset.json"
    rs.write_text('{"name":"x","enforcement":"disabled"}', encoding="utf-8")
    deep = ws.base / "deg-deep.json"
    deep.write_text('{"event":"COMMENT","x":' + "[" * 25000 + "]" * 25000 + "}", encoding="utf-8")
    b.write_text('{"event":"APPROVE"}', encoding="utf-8")
    q.write_text(APPROVE_MUTATION, encoding="utf-8")
    gql_var = ("gh api graphql -f query='mutation($id:ID!,$e:PullRequestReviewEvent!){addPullRequestReview(input:"
               "{pullRequestId:$id,event:$e}){clientMutationId}}' -f id=x -f e=\"$E\"")
    for cmd, want, why in (("gh pr review 3 --approve", "deny", "Approve"),
                           ("gh api -X PUT repos/o/r/pulls/3/reviews/9/dismissals", "deny", "기각"),
                           ("gh -b LGTM pr review 3 --approve", "deny", "Approve"),        # 앞 옵션도 모든 읽기를 본다(H-A1 r4)
                           ("gh -X PUT api repos/o/r/pulls/3/reviews/9/dismissals", "deny", "기각"),
                           # 셸이 정한 동작·엔드포인트·event, 파일 본문의 APPROVE(4-c 리뷰 P1 — `_gh_judged_deny`)
                           ("gh pr $ACT 3", "deny", "셸이 푸는 값"), ('gh "$G" merge 3', "deny", "셸이 푸는 값"),
                           ('gh api -X PUT "$EP"', "deny", "셸이 푸는 값"),
                           ('gh api repos/o/r/pulls/3/reviews -f event="$E"', "deny", "Approve"), (gql_var, "deny", "Approve"),
                           (f"gh api repos/o/r/pulls/3/reviews --input {b.as_posix()}", "deny", "Approve"),
                           (f"gh api graphql -F query=@{q.as_posix()}", "deny", "Approve"),
                           # 보호·ruleset 바꾸기·자동 병합 켜기(사용자 결정)
                           ("gh api -X DELETE repos/o/r/branches/main/protection", "deny", "브랜치 보호"),
                           (f"gh api repos/o/r/rulesets --input {rs.as_posix()}", "deny", "브랜치 보호"),
                           ("gh repo edit --enable-auto-merge", "deny", "브랜치 보호"),
                           (f"gh api repos/o/r/pulls/3/reviews --input {deep.as_posix()}", "deny", "Approve"),  # 깊은 JSON = 못 읽은 본문
                           ("gh api -X PATCH repos/o/r -F delete_branch_on_merge=true", "deny", "브랜치 보호"),
                           ('gh alias set x "$(echo cHIgcmV2aWV3IC1h | base64 -d)"', "deny", "별칭"),
                           ('gh pr review 3 -b "$B" --comment', "ask", None),     # `_gh_kind`가 판정했다 — 낱말 수준은 안 쓴다
                           ("if true; then gh pr review 3 --approve; fi", "deny", "Approve"),   # 예약어 뒤도 본다(H-A1 r5)
                           ('gh pr review 3 "$OPT"', "deny", "Approve"),                         # 셸 값 옵션은 Approve일 수 있다
                           ("gh pr review 3 -a", "deny", "Approve"),
                           ("gh pr merge 3", "ask", None), ("gh pr merge 3 --auto --squash", "deny", "자동 병합"),
                           ("gh -b x pr merge 3", "ask", None), ("gh api -X PUT repos/o/r/pulls/3/merge", "ask", None),
                           (f"gh api graphql -f query='{MERGE_MUTATION}'", "ask", None),
                           ("gh alias set m 'pr merge --admin'", "ask", None),
                           ("gh pr review 3 --comment -b x", "ask", None), ("gh pr create -t x -b y", "ask", None)):
        out, _ = judge("Bash", {"command": cmd})
        assert decision(out) == want and "의존성 없음" in out["permissionDecisionReason"], cmd
        assert why is None or why in out["permissionDecisionReason"], cmd


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
             (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", "ask"),        # 병합 계열은 ask(4-c)
             (f"gh api -X POST repos/{DB_SLUG}/merges -f base=main -f head=x", "ask"),
             (f"gh api repos/{DB_SLUG}/pulls/3/merge", None)]   # GET: 머지 가능 여부 조회
    for cmd, want in cases:
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_review_followups_mcp_verb_position():
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db"}
    # 병합은 병합 계열 — ask(4-c, 서버 브랜치 보호가 승인 1을 강제한다). 자동 병합 켜기는 거부(원칙 12), 끄기는 ask
    for tool, want in (("mcp__github__disable_pr_auto_merge", "ask"), ("mcp__github__enable_pr_auto_merge", "deny"),
                       ("mcp__github__list_triggers", None), ("mcp__github__request_copilot_review", "ask"),
                       ("mcp__github__run_secret_scanning", "ask"), ("mcp__github__pull_request_read", None),
                       ("mcp__github__merge_pull_request", "ask")):
        assert decision(guard(ws, tool, db, ws.base)) == want, tool
    # 미설정 jira/atlassian 서버: 읽기 동사로 시작하는 도구는 접두사가 쓰기 단어처럼 보여도 통과
    for tool in ("mcp__atlassian__get_issue_links", "mcp__atlassian__list_assignees", "mcp__jira-prod__jira_get_attachments",
                 "mcp__atlassian__getJiraIssue"):
        assert decision(guard(ws, tool, {}, ws.base)) is None, tool
    for tool in ("mcp__atlassian__addCommentToJiraIssue", "mcp__jira-prod__jira_add_comment"):
        assert decision(guard(ws, tool, {}, ws.base)) == "deny", tool
    # 설정된 서버는 그대로 read_tools 허용 목록
    assert decision(guard(ws, "mcp__mock-jira__jira_get_links", {}, ws.base)) == "deny"


APPROVE_MUTATION = 'mutation { addPullRequestReview(input: {pullRequestId: "x", event: APPROVE}) { clientMutationId } }'
MERGE_MUTATION = 'mutation { mergePullRequest(input: {pullRequestId: "x"}) { clientMutationId } }'


def test_guard_denies_claude_approve_dismiss_and_asks_merges():
    """규칙 11(H A1·4-c): Claude의 Approve·리뷰 기각(gh 옵션, REST `event=APPROVE` — `-f`·`-F`·`--input` 파일·`@파일`, GraphQL
    mutation — 인라인·`@파일`·`--input`·stdin heredoc, MCP 단어·동작 칸)과 리뷰 별칭·못 읽은 별칭 파일은 대상 레포와 무관하게
    거부(서버가 막지 못한다). 병합 계열(gh·REST·GraphQL 병합·자동 병합·병합 별칭, MCP 자동 병합)은 ask(서버 브랜치 보호가
    막는다). 변경 요청·코멘트 리뷰는 ask로 남는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    url = f"https://ghe.mock.invalid/{DB_SLUG}/pull/3"
    files = {"r.json": '{"event": "APPROVE", "body": "x"}', "c.json": '{"event": "COMMENT", "body": "x"}', "e.txt": "APPROVE",
             "q.graphql": APPROVE_MUTATION, "m.graphql": MERGE_MUTATION, "viewer.graphql": "query { viewer { login } }",
             "v.graphql": ("mutation($e: PullRequestReviewEvent!) { addPullRequestReview(input: {pullRequestId: \"x\", "
                           "event: $e}) { clientMutationId } }"),
             "q.json": json.dumps({"query": APPROVE_MUTATION.replace("addPullRequestReview", "submitPullRequestReview")}),
             "a.yml": "m: pr merge\n", "co.yml": "co: pr checkout\n", "rv.yml": "rv: pr review\n"}
    for name, text in files.items():
        (plain / name).write_text(text, encoding="utf-8")
    wt = ws.work / "wt-approve"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    db = {"owner": "mock-org", "repo": "telephony-issue-db", "pullNumber": 3}
    try:
        approve = [(f"gh pr review 3 --approve -R {DB_SLUG}", plain), ("gh pr review --approve", wt),
                   (f"gh -R {DB_SLUG} pr review 3 -a", plain), (f"gh pr review 3 -ab LGTM -R {DB_SLUG}", plain),
                   (f"gh pr review 3 -ra -R {DB_SLUG}", plain),
                   (f"gh pr review 3 --approve=true -R {DB_SLUG}", plain), (f"gh pr review 3 -a=true -R {DB_SLUG}", plain),
                   (f"gh pr review 3 -a=1 -R {DB_SLUG}", plain), (f"GH_REPO={DB_SLUG} gh pr review 3 --approve", plain),
                   (f"env GH_HOST=ghe.mock.invalid gh pr review 3 --approve -R {DB_SLUG}", plain),
                   (f'bash -c "gh pr review 3 -a -R {DB_SLUG}"', plain), (f"gh pr review {url} --approve", plain),
                   ('gh pr review 3 "$FLAG"', plain), ("gh pr review 3 -b $B", plain),     # 셸 값 옵션은 Approve일 수 있다
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -F event=approve", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --raw-field event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --field=event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -fevent=APPROVE", plain),
                   (f"gh api -X POST repos/{DB_SLUG}/pulls/3/reviews/77/events -f event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input r.json", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input -", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -F event=@e.txt", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=\"$E\"", plain),
                   (f"gh api graphql -f query='{APPROVE_MUTATION}'", plain), ("gh api graphql -F query=@q.graphql", plain),
                   ("gh api graphql -F query=@v.graphql -f e=APPROVE", plain), ("gh api graphql --input q.json", plain),
                   (f"gh api graphql -F query=@- <<'EOF'\n{APPROVE_MUTATION}\nEOF", plain),
                   ('gh api graphql -F query=@v.graphql -f e="$E"', plain),
                   # 대상 레포를 보지 않는다: 이슈 DB가 아닌 레포의 Approve도 거부(4-c)
                   ("gh pr review 3 --approve -R other/repo", plain), ("gh pr review 3 -a", plain)]
        for cmd, cwd in approve:
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and "Approve하지 않는다" in out["permissionDecisionReason"], cmd
        # 병합 계열: ask(4-c — 대상 레포와 무관, 이슈 DB가 아닌 레포도)
        merge = [(f"gh pr merge {url} --merge", plain),
                 ("gh pr merge https://ghe.mock.invalid/other/repo/pull/3", plain),
                 (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", plain),
                 (f"gh api -X POST repos/{DB_SLUG}/merges -f base=main -f head=x", plain),
                 ("gh api graphql -F query=@m.graphql", plain),
                 (f"gh api graphql -F query=@- <<'EOF'\n{MERGE_MUTATION}\nEOF", plain),
                 ("gh api graphql -f query='mutation { enqueuePullRequest(input: {}) { clientMutationId } }'", plain),
                 ("gh alias import a.yml", plain),
                 ("gh alias import - <<'EOF'\nm: pr merge\nEOF", plain)]
        for cmd, cwd in merge:
            out = bash(ws, cmd, cwd)
            assert decision(out) == "ask" and "머지" in out["permissionDecisionReason"], cmd
        for cmd in (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/reviews/9/dismissals -f message=x",
                    "gh api graphql -f query='mutation { dismissPullRequestReview(input: {}) { clientMutationId } }'"):
            out = bash(ws, cmd, plain)
            assert decision(out) == "deny" and "기각" in out["permissionDecisionReason"], cmd
        # 리뷰 별칭(`gh rv 3 -a`를 보지 못한다)과 못 읽은 별칭 파일은 거부
        for cmd in ("gh alias set lgtm 'pr review --approve'", "gh alias set rv 'pr review'", "gh alias import rv.yml",
                    "cat a.yml | gh alias import -", "gh alias import none.yml"):
            out = bash(ws, cmd, plain)
            assert decision(out) == "deny" and "별칭" in out["permissionDecisionReason"], cmd
        mcp = [("mcp__github__pull_request_review_write", {**db, "method": "create", "event": "APPROVE"}, "Approve하지 않는다"),
               ("mcp__github__pull_request_review_write", {**db, "method": "submit_pending", "event": "approve"},
                "Approve하지 않는다"),
               ("mcp__github__create_pull_request_review", {**db, "event": "APPROVE"}, "Approve하지 않는다"),
               ("mcp__x__approve_pull_request", db, "Approve하지 않는다"),
               ("mcp__x__dismiss_pull_request_review", db, "기각"),
               ("mcp__github__pull_request_review_write", {"owner": "other", "repo": "x", "pullNumber": 3, "event": "APPROVE"},
                "Approve하지 않는다")]      # 대상 레포를 보지 않는다(4-c)
        for tool, tool_input, why in mcp:
            out = guard(ws, tool, tool_input, ws.base)
            assert decision(out) == "deny" and why in out["permissionDecisionReason"], tool
        out = guard(ws, "mcp__github__enable_pr_auto_merge", db, ws.base)
        assert decision(out) == "deny" and "자동 병합을 Claude가 켜지 않는다" in out["permissionDecisionReason"]
        asks = [(f"gh pr review 3 --request-changes -b x -R {DB_SLUG}", plain),
                (f"gh pr review 3 --comment -b x -R {DB_SLUG}", plain), ('gh pr review 3 -b "$B"', plain),
                (f"gh pr review 3 -a=false -R {DB_SLUG}", plain), (f"gh pr review 3 --approve=0 -R {DB_SLUG}", plain),
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=COMMENT -f body=x", plain),
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=REQUEST_CHANGES", plain),
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f body=x", plain),       # event 없음: PENDING 리뷰 만들기
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input c.json", plain),
                ("gh api graphql -f query='mutation { addPullRequestReview(input: {event: COMMENT}) { clientMutationId } }'", c),
                ("gh api graphql -F query=@none.graphql", c),                   # 읽지 못한 본문은 쓰기
                ("cat x.graphql | gh api graphql -F query=@-", c),                # stdin이 heredoc이 아니면 모르는 본문
                ("gh lgtm 3", plain)]                                            # 모르는 그룹(이미 만든 별칭 실행 포함)은 쓰기
        for cmd, cwd in asks:
            out = bash(ws, cmd, cwd)
            assert decision(out) == "ask" and "머지" not in out["permissionDecisionReason"], cmd
        for tool, tool_input in (("mcp__github__pull_request_review_write", {**db, "method": "create", "event": "COMMENT"}),
                                 ("mcp__github__pull_request_review_write", {**db, "method": "create"}),
                                 ("mcp__github__disable_pr_auto_merge", db)):
            assert decision(guard(ws, tool, tool_input, ws.base)) == "ask", (tool, tool_input)
        nothing = [(f"gh api -X GET repos/{DB_SLUG}/pulls/3/reviews", plain), (f"gh api repos/{DB_SLUG}/pulls/3/reviews", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/merge", plain),                # GET: 머지 가능 여부 조회
                   ("gh api graphql -F query=@viewer.graphql", plain),
                   ("gh api graphql -F query=@- <<'EOF'\nquery { viewer { login } }\nEOF", plain),
                   ("gh pr list --search review:approved", plain),                   # 상태 값 APPROVED는 Approve가 아니다
                   ("gh pr view 3 --json reviews -q '.reviews[] | select(.state == \"APPROVED\")'", plain),
                   ("gh alias set co 'pr checkout'", plain), ("gh alias import co.yml", plain)]
        for cmd, cwd in nothing:
            assert decision(bash(ws, cmd, cwd)) is None, cmd
        empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}      # 사용자 config 없음: 규칙 11 없음
        assert decision(bash(ws, f"gh pr review 3 --approve -R {DB_SLUG}", plain, env=empty)) is None
        assert decision(bash(ws, f"gh api graphql -f query='{MERGE_MUTATION}'", plain, env=empty)) is None
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_approve_dismiss_and_shell_decided_forms_denied_anywhere():
    """규칙 11(4-c): 대상 레포 해석 시험(URL 선택자·`-R` 꼴·pflag 묶음·앞 옵션·자리표시·퍼센트 인코딩·SCP·cwd 원격)을 지우면서 그
    안의 Approve·리뷰 기각·셸이 정한 동작 거부 줄을 모았다 — 대상과 cwd에 무관하게 거부가 남는다. 같은 시험에 있던 규칙 8 줄(`gh co`·
    `pr co`, `cd -`로 돌아온 clone의 checkout)도 그대로 둔다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-forms"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    same = _repo_with_origin("https://ghe.mock.invalid/mock-org/telephony-triage")    # 같은 owner의 다른 레포
    h = "https://ghe.mock.invalid"
    other, db, url, rid = f"{h}/other/repo", f"ghe.mock.invalid/{DB_SLUG}", f"{h}/{DB_SLUG}/pull/3", "repositories/123456/pulls/3"
    hd = "gh api graphql -f query=\"$(cat <<'EOF'\n{q}\nEOF\n)\""
    approve, dismiss, dyn = "Approve하지 않는다", "기각", "셸이 푸는 값"
    rows = [
        # URL·옵션 값(옛 test_guard_gh_url_selector_option_values_api_clusters_and_graphql_url)
        (f"gh pr review 3 --approve -b {other}/pull/9", c, approve),
        (f"gh api repos/{DB_SLUG}/pulls/3/reviews -if event=APPROVE", plain, approve),
        (f"gh api -iX PUT repos/{DB_SLUG}/pulls/3/reviews/9/dismissals -f message=x", plain, dismiss),
        (f"gh api {h}/api/graphql -f query='{APPROVE_MUTATION}'", plain, approve),
        # 값 자리의 `-R` 꼴(옛 test_guard_gh_repo_flag_in_option_value_keeps_cwd_target)
        ("gh pr review 3 --approve -b -Rother/x", c, approve), ("gh pr review 3 --approve --body '-R other/x'", wt, approve),
        ("gh pr review 3 --approve -b -R other/x", c, approve), ("gh pr review 3 --approve -R other/x", wt, approve),
        ("gh api 'repos/{owner}/{repo}/pulls/3/reviews' -f event=APPROVE -t -Rother/x", c, approve),
        ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/reviews/9/dismissals' -f message=x -f -Rother/x", wt, dismiss),
        # 스킴 대소문자·레포 ID·`#` 조각(옛 test_guard_gh_url_scheme_case_repo_id_endpoint_and_fragment)
        (f"gh pr review HTTPS://{db}/pull/3 --approve", plain, approve), (f"gh pr review Https://{db}/pull/3 -a", plain, approve),
        (f"gh api {rid}/reviews -f event=APPROVE", plain, approve),
        (f"gh api -X PUT {rid}/reviews/9/dismissals -f message=x", plain, dismiss),
        (f"gh api 'repos/{DB_SLUG}/pulls/3/reviews#x' -f event=APPROVE", plain, approve),
        (f"gh api -X PUT 'repos/{DB_SLUG}/pulls/3/reviews/9/dismissals#x' -f message=x", plain, dismiss),
        # 앞 옵션·host·퍼센트·셸 값 대상·GH_REPO·자리표시(옛 test_guard_gh_leading_options_target_resolution_and_placeholders_…)
        ("gh pr -b LGTM review 3 --approve", c, approve), ("gh -b LGTM pr review 3 --approve", wt, approve),
        (f"gh -f event=APPROVE api repos/{DB_SLUG}/pulls/3/reviews", plain, approve),
        (f"gh -X PUT api repos/{DB_SLUG}/pulls/3/reviews/5/dismissals", plain, dismiss),
        (f"gh -f query='{APPROVE_MUTATION}' api graphql", plain, approve),
        ("gh -f query='mutation { dismissPullRequestReview(input: {}) { clientMutationId } }' api graphql", plain, dismiss),
        (f"gh pr review https://www.ghe.mock.invalid/{DB_SLUG}/pull/3 --approve", wt, approve),
        (f"gh pr review {h}/mock-org/telephony%2Dissue-db/pull/3 --approve", wt, approve),
        (f"gh pr review {h}/{DB_SLUG}$NOPE/pull/3 --approve", wt, approve),
        (f"export GH_REPO={DB_SLUG} && gh pr review 3 --approve", plain, approve),
        ("gh api repos/mock-org/telephony%2Dissue-db/pulls/3/reviews -f event=APPROVE", plain, approve),
        ("gh api 'repos/{owner}/telephony-issue-db/pulls/3/reviews' -f event=APPROVE", same, approve),
        ("gh api -X POST 'repos/{owner}/telephony-issue-db/pulls/3/reviews/9/dismissals' -f message=x", same, dismiss),
        ("gh api 'repos/{owner}/telephony-issue-db/pulls/3/reviews/9/events' -f event=APPROVE", same, approve),
        ("gh pr review 3 --approve", plain, approve),                      # 옛 판정: cwd가 이슈 DB가 아니면 통과
        # SSH 별칭 원격(옛 test_guard_gh_ssh_alias_remote_and_unknown_value_options_keep_cwd)
        (f"gh pr review {url} --approve", c, approve), (f"gh pr review {url} -a", wt, approve),
        # 셸이 정하는 본문·엔드포인트·동작·옵션(옛 test_guard_gh_shell_expanded_operations_are_closed)
        (hd.format(q=APPROVE_MUTATION), plain, approve),
        (("gh api graphql -f query='mutation($id:ID!,$e:PullRequestReviewEvent!){addPullRequestReview(input:"
          "{pullRequestId:$id,event:$e}){clientMutationId}}' -f id=x -f e=\"$E\""), plain, approve),
        (f"EP=repos/{DB_SLUG}/pulls/3/merge; gh api -X PUT \"$EP\"", plain, dyn),
        ('gh api -X POST "$EP" -f event=APPROVE', plain, approve), ('gh api "$URL/reviews" -f event=APPROVE', plain, approve),
        ('gh api -X PUT "repos/other/x/pulls/3/$A"', c, dyn), ('gh api -X PUT "repos/other/x/pulls/3/$A"', plain, dyn),
        (f'gh api repos/{DB_SLUG}/pulls/3/reviews -f event="$E"', plain, approve),
        ("gh pr $ACT 3", c, dyn), ("gh pr $ACT 3", plain, dyn), (f'gh pr "$ACT" 3 -R {DB_SLUG}', plain, dyn),
        ('gh "$G" merge 3', c, dyn), (f'gh "$G" -X PUT repos/{DB_SLUG}/pulls/3/merge', plain, dyn),
        ('gh pr review 3 "$OPT"', c, approve), (f"gh pr review 3 $OPT -R {DB_SLUG}", plain, approve),
        ("gh pr review 3 --comment -b $B", c, approve),
        # cwd 원격·앞 대입 GIT_DIR(옛 test_guard_gh_cwd_resolution_remotes_gitdir_and_unknown_dirs)
        (f"GIT_DIR={c}/.git gh pr review 3 --approve", plain, approve),
        # JSON 본문의 이스케이프(`\u0041PPROVE` — gh는 그대로 보낸다)도 푼 글로 본다(4-c 리뷰 P1)
        (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input esc.json", plain, approve),
        ("gh api graphql --input esc.graphql.json", plain, approve),
        # 깊은 중첩 JSON(`GH_JSON_DEPTH_MAX` 초과)은 못 읽은 본문 — 리뷰 엔드포인트면 Approve 거부. 예전엔 `json.loads`의
        # RecursionError(판정 예외 → `guard 내부 오류`)에 기댔는데 Python 3.14는 25,000단도 그냥 읽어 ask가 됐다(PR #82 CI)
        (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input deep.json", plain, "Approve"),
        (f"gh api -X POST repos/{DB_SLUG}/pulls/3/reviews/9/events --input deep.json", plain, "Approve"),
        # 셸 값이 든 별칭 정의는 내용을 모른다
        ('gh alias set x "$(echo cHIgcmV2aWV3IC1h | base64 -d)"', plain, "별칭"), ("gh alias set x `cat a`", plain, "별칭"),
        # 자리 표시·셸 별칭은 실행 때 동작이 정해진다, 줄 이음·파이프로 받은 별칭 파일은 못 읽은 본문(4-c 4회차)
        ("gh alias set x 'pr $1 3 -$2'", plain, "별칭"), ("gh alias set x 'pr \"$@\"'", plain, "별칭"),
        ("gh alias set --shell x 'gh pr \"$@\"'", plain, "별칭"), ("gh alias set -s x 'echo hi'", plain, "별칭"),
        ("gh alias set x '!gh pr view'", plain, "별칭"), ("gh alias set p '!python3 $S/db_pr.py publish wt'; gh p", plain, "별칭"),
        ('''gh alias set m '!gh pr merge "$1"' ''', plain, "별칭"),
        ("gh alias import - <<EOF\nx: pr rev" + chr(92) + "\niew\nEOF", plain, "별칭"),
        ("cat <<'EOF' | base64 -d | gh alias import -\neDogcHIgcmV2aWV3Cg==\nEOF", plain, "별칭")]
    bs = chr(92)
    (plain / "esc.json").write_text('{"event":"' + bs + 'u0041PPROVE"}', encoding="utf-8")
    (plain / "deep.json").write_text('{"event":"COMMENT","x":' + "[" * 25000 + "]" * 25000 + "}", encoding="utf-8")
    (plain / "esc.graphql.json").write_text(json.dumps({"query": APPROVE_MUTATION}).replace("APPROVE", bs + "u0041PPROVE"),
                                            encoding="utf-8")
    try:
        for cmd, cwd, why in rows:
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and why in out["permissionDecisionReason"], (cmd, cwd)
        # 규칙 8(그대로): gh 기본 별칭 `co`·동작 별칭 `pr co`는 clone 본체에서 거부, `cd -`로 돌아온 clone의 checkout도. 동작
        # 자리만 본다 — `--search checkout`은 판정하지 않는다(base와 같다)
        for cmd, cwd, want in (("gh pr co 3", c, "deny"), ("gh co 3", c, "deny"), ("gh pr checkout 3", c, "deny"),
                               ("gh pr co 3", plain, None), (f"cd {c}; cd /tmp; cd -; git checkout main", plain, "deny"),
                               ("gh pr list --search checkout", c, None), ("gh pr checkout 3 >/dev/null", c, "deny"),
                               ("gh pr checkout 3 2>&1 | tail -1", c, "deny"), ("gh --repo o/r pr co 3", c, "deny"),
                               ("GH_REPO=o/r gh co 3", c, "deny"), ("gh pr checkout --force 3", c, "deny"),
                               ("gh pr -b x -b y checkout 3", c, "deny"), ("gh -b x -c y co 3", c, "deny"),
                               ("gh -R o/r pr checkout 3", c, "deny")):
            out = bash(ws, cmd, cwd)
            assert decision(out) == want, (cmd, cwd)
            assert want is None or "규칙 8" in out["permissionDecisionReason"], cmd
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_denies_branch_protection_ruleset_and_auto_merge_changes():
    """규칙 11(4-c 사용자 결정): 서버 브랜치 보호가 4-c 뒤 유일한 병합 장치라 그것을 끄거나 바꾸는 gh 호출은 Approve와 같은 급으로
    거부 — `…/branches/<b>/protection…`의 DELETE·PUT·PATCH·POST(필드·`--input` 포함, 브랜치에 `/`), `…/rulesets`의 쓰기,
    GraphQL 보호·ruleset mutation, 레포 설정(REST `repos/<o>/<r>`·`repositories/<id>`)의 `allow_auto_merge`·
    `delete_branch_on_merge` 켜기(`true`·`1`·`True`, `-f`·`-F`·`--input`·JSON 이스케이프), `gh repo edit --enable-auto-merge`·
    `--delete-branch-on-merge`. 읽기(GET)·거짓 값(`false`·`=false`)은 그대로다."""
    ws = shared()
    plain = tmp("tt-gh-plain-")
    (plain / "rs.json").write_text('{"name":"x","enforcement":"disabled"}', encoding="utf-8")
    bs = chr(92)
    for name, body in (("dbm.json", '{"delete_branch_on_merge": true}'), ("aam.json", '{"allow_auto_merge": 1}'),
                       ("dbme.json", '{"delete_branch_on_m' + bs + 'u0065rge": true}'),
                       ("aame.json", '{"allow_auto_m' + bs + 'u0065rge": "True"}'), ("off.json", '{"allow_auto_merge": false}')):
        (plain / name).write_text(body, encoding="utf-8")
    why = "브랜치 보호"
    for cmd in (f"gh api -X DELETE repos/{DB_SLUG}/branches/main/protection",
                f"gh api -X PATCH repos/{DB_SLUG}/branches/main/protection/required_pull_request_reviews "
                "-F required_approving_review_count=0",
                f"gh api --method PUT repos/{DB_SLUG}/branches/main/protection --input rs.json",
                f"gh api -X DELETE repos/{DB_SLUG}/branches/main/protection/enforce_admins",
                f"gh api repos/{DB_SLUG}/rulesets --input rs.json", f"gh api -X PUT repos/{DB_SLUG}/rulesets/7 -f enforcement=disabled",
                "gh api -X DELETE orgs/mock-org/rulesets/7",
                "gh repo edit --enable-auto-merge", f"gh repo edit {DB_SLUG} --enable-auto-merge=true",
                f"gh api -X DELETE repos/{DB_SLUG}/branches/release/v1/protection",
                f"gh api -X PATCH repos/{DB_SLUG} -F allow_auto_merge=true",
                f"gh api -X PATCH repos/{DB_SLUG} -f allow_auto_merge=1", f"gh api -X PATCH repos/{DB_SLUG} -F allow_auto_merge=True",
                "gh api -X PATCH repositories/123 -F allow_auto_merge=true", "gh api repositories/123 -F delete_branch_on_merge=1",
                f"gh api -X PATCH repos/{DB_SLUG} -F delete_branch_on_merge=true",
                f"gh api -X PATCH repos/{DB_SLUG} -f delete_branch_on_merge=1",
                f"gh api -X PATCH repos/{DB_SLUG} -F delete_branch_on_merge=True",
                *(f"gh api -X PATCH repos/{DB_SLUG} --input {n}" for n in ("dbm.json", "aam.json", "dbme.json", "aame.json")),
                "gh repo edit --delete-branch-on-merge", f"gh repo edit {DB_SLUG} --delete-branch-on-merge=true",
                "gh api graphql -f query='mutation { deleteBranchProtectionRule(input: {branchProtectionRuleId: \"x\"}) "
                "{ clientMutationId } }'",
                "gh api graphql -f query='mutation { updateBranchProtectionRule(input: {branchProtectionRuleId: \"x\"}) "
                "{ clientMutationId } }'",
                "gh api graphql -f query='mutation { createBranchProtectionRule(input: {}) { clientMutationId } }'",
                "gh api graphql -f query='mutation { createRepositoryRuleset(input: {}) { clientMutationId } }'",
                "gh api graphql -f query='mutation { updateRepositoryRuleset(input: {}) { clientMutationId } }'",
                "gh api graphql -f query='mutation { deleteRepositoryRuleset(input: {}) { clientMutationId } }'",
                "gh api graphql -f query=\"$(cat <<'EOF'\nmutation { deleteBranchProtectionRule(input: {}) { clientMutationId } }"
                "\nEOF\n)\""):
        out = bash(ws, cmd, plain)
        assert decision(out) == "deny" and why in out["permissionDecisionReason"], cmd
    for cmd, want in ((f"gh api repos/{DB_SLUG}/branches/main/protection", None), (f"gh api repos/{DB_SLUG}/rulesets", None),
                      ("gh repo edit --enable-auto-merge=false", "ask"), ("gh repo edit --description x", "ask"),
                      (f"gh api -X PATCH repos/{DB_SLUG} -F allow_auto_merge=false", "ask"),
                      (f"gh api -X PATCH repos/{DB_SLUG} -F delete_branch_on_merge=false", "ask"),
                      (f"gh api -X PATCH repos/{DB_SLUG} --input off.json", "ask"),
                      ("gh repo edit --delete-branch-on-merge=false", "ask")):
        assert decision(bash(ws, cmd, plain)) == want, cmd
    # 낱말 수준 Approve 거부에는 오탐 안내가 붙는다(사용자 결정 — 본문·검색어라도 거부)
    out = bash(ws, "gh pr comment 3 -b 'please approve'", plain)
    assert decision(out) == "deny" and "코멘트 본문에 그 낱말을 쓰지 않는다" in out["permissionDecisionReason"]


def test_guard_auto_merge_denied_principle_12():
    """규칙 11·원칙 12(4-c 사용자 결정): PR 자동 병합 켜기는 거부 — 자동 병합은 +1이 붙는 즉시 db_pr merge의 확인(승인 SHA 대조·
    메인테이너 경로 PR 거부) 없이 병합한다. `gh pr merge --auto`(다른 병합 옵션과 함께·선택자 뒤 따옴표 밖 셸 값), GraphQL
    `enablePullRequestAutoMerge`, `--auto` 병합 별칭, MCP 자동 병합 켜기. 사유는 보호 바꾸기(`PROTECTION_DENY`)가 아니다.
    `--auto` 없는 병합(gh·REST·GraphQL)·`--auto=false`·자동 병합 끄기는 ask 그대로. 의존성 없음 판정도 같다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    db = {"owner": "mock-org", "repo": "telephony-issue-db", "pullNumber": 3}
    why = "자동 병합을 Claude가 켜지 않는다"
    deny = ("gh pr merge 3 --auto", "gh pr merge 3 --auto --squash", "gh pr merge --auto 3", "gh pr merge 3 --squash --auto=true",
            "gh pr merge 3 --merge --auto --delete-branch", "gh pr merge 3 $OPTS", "gh -R o/r pr merge 3 --auto",
            "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {pullRequestId: \"x\"}) { clientMutationId } }'",
            "gh alias set am 'pr merge --auto --squash'")
    for cmd in deny:
        for cwd in (plain, c):
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and why in out["permissionDecisionReason"], (cmd, cwd)
            assert "브랜치 보호" not in out["permissionDecisionReason"], cmd
    for tool in ("mcp__github__enable_pr_auto_merge", "mcp__ghe__automerge_pr"):
        out = guard(ws, tool, db, ws.base)
        assert decision(out) == "deny" and why in out["permissionDecisionReason"], tool
    for cmd in ("gh pr merge 3", "gh pr merge 3 --squash", 'gh pr merge "$PR" --squash', "gh pr merge $PR",
                "gh pr merge 3 --auto=false", f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge",
                f"gh api graphql -f query='{MERGE_MUTATION}'", "gh alias set m 'pr merge --squash'"):
        out = bash(ws, cmd, plain)
        assert decision(out) == "ask" and "머지" in out["permissionDecisionReason"], cmd
    assert decision(guard(ws, "mcp__github__disable_pr_auto_merge", db, ws.base)) == "ask"
    env = _no_yaml_env(ws)
    for cmd in ("gh pr merge 3 --auto", "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { x } }'"):
        out = bash(ws, cmd, plain, env=env)
        assert decision(out) == "deny" and why in out["permissionDecisionReason"], cmd
    assert decision(bash(ws, "gh pr merge 3", plain, env=env)) == "ask"


def test_guard_gh_pr_read_list_and_action_aliases():
    """규칙 11(H-A1 r5·4-c): `pr`은 읽기 목록(list·view·status·checks·diff)만 읽기다(`revert`·`update-branch`·모르는 동작은 쓰기 —
    ask). 동작 별칭(`new`·`ls`·`co`)을 풀어 본다. `repo`·`issue transfer` 쓰기는 대상 레포와 무관하게 ask."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [(f"gh pr revert 3 -R {DB_SLUG}", plain, "ask"), ("gh pr revert 3", c, "ask"),
            (f"gh pr new -R {DB_SLUG} -t x -b y", plain, "ask"), (f"gh pr update-branch 3 -R {DB_SLUG}", plain, "ask"),
            (f"gh repo edit {DB_SLUG} --default-branch dev", plain, "ask"),
            (f"gh repo edit {DB_SLUG} --enable-auto-merge", plain, "deny"),     # 자동 병합 켜기는 보호 바꾸기(사용자 결정)
            (f"gh repo delete {DB_SLUG} --yes", plain, "ask"), (f"gh repo archive {DB_SLUG} -y", plain, "ask"),
            (f"gh repo sync {DB_SLUG} --source mock-org/other --branch main --force", plain, "ask"),
            (f"gh issue transfer 5 {DB_SLUG}", plain, "ask"), ("gh issue transfer 5 other/x", plain, "ask"),
            ("gh repo edit other/x --description y", c, "ask"), ("gh repo create acme/new --private", c, "ask"),
            ("gh repo rename newname", plain, "ask"),
            # 읽기
            (f"gh pr ls -R {DB_SLUG}", plain, None), (f"gh issue ls -R {DB_SLUG}", plain, None),
            (f"gh release ls -R {DB_SLUG}", plain, None), (f"gh pr checks 3 -R {DB_SLUG}", plain, None),
            (f"gh repo view {DB_SLUG}", plain, None), (f"gh repo clone {DB_SLUG}", plain, None),
            ("gh pr status", c, None), ("gh pr diff 3", c, None), ("gh --version", c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_reserved_words_redirections_and_line_continuations_find_commands():
    """명령 낱말 찾기(H-A1 r5, 부류로 닫기): 셸 예약어(`if`·`then`·`do`·`{`·`!`·`function NAME`·`coproc`)와 앞 리디렉션
    (`>/dev/null`·`2>&1`·`</dev/null`·`&>`)은 명령 낱말이 아니다. 작은따옴표 밖 줄 이음(`\\` + 줄바꿈)은 bash처럼 지우고
    (`gh api \\⏎ --method PUT …` — GitHub 문서 꼴), `$'…'`은 풀어 읽는다. 규칙 11(gh)·6(push)·8(clone git) 모두 같다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    forms = ["if true; then {x}; fi", "for n in 3; do {x}; done", "while true; do {x} && break; done", "{{ {x}; }}", "! {x}",
             "function f {{ {x}; }}", "f() {{ {x}; }}; f", ">/dev/null {x}", "2>&1 {x}", "</dev/null {x}", "&>/dev/null {x}",
             "if ! {x}; then echo no; fi", "nohup >/dev/null 2>&1 {x}", "coproc {x}", "time ! {x}"]
    # 병합 계열은 ask(4-c), 나머지는 거부 — 어느 쪽이든 명령을 찾았다는 뜻이다(못 찾으면 판정 없음)
    cmds = [("gh pr merge 3 --squash", "ask", "머지"), ("gh pr review 3 --approve", "deny", "Approve하지 않는다"),
            (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", "ask", "머지"),
            ("git push --no-verify origin HEAD:main", "deny", "규칙 5"), ("git checkout main", "deny", "규칙 8")]
    for form in forms:
        for x, want, why in cmds:
            out = bash(ws, form.format(x=x), c)
            assert decision(out) == want and why in out["permissionDecisionReason"], form.format(x=x)
    nl = "\\\n  "
    rows = [(f"if true; then gh pr comment 3 -b hi -R {DB_SLUG}; fi", plain, "ask"),
            (f'm() {{ gh pr merge "$@" -R {DB_SLUG}; }}; m 3', plain, "ask"),
            ("gh 2>/dev/null pr merge 3", c, "ask"), ("git 2>&1 push --no-verify origin HEAD:main", c, "deny"),
            # 줄 이음(GitHub REST 문서 꼴)
            ((f'gh api {nl}--method PUT {nl}-H "Accept: application/vnd.github+json" {nl}/repos/{DB_SLUG}/pulls/3/merge '
              f'{nl}-f "merge_method=squash"'), plain, "ask"),
            (f'gh api {nl}--method POST {nl}/repos/{DB_SLUG}/pulls/3/reviews {nl}-f "event=APPROVE"', plain, "deny"),
            (f"gh api {nl}--method PUT {nl}/repos/{DB_SLUG}/pulls/3/reviews/9/dismissals {nl}-f message=x", plain, "deny"),
            (f"gh api {nl}graphql {nl}-f query='{MERGE_MUTATION}'", plain, "ask"),
            (f"gh api {nl}-X POST {nl}repos/{DB_SLUG}/issues/3/comments {nl}-f body=hi", plain, "ask"),
            (f"gh {nl}pr merge 3 --squash", c, "ask"), (f"gh pr {nl}merge 3", c, "ask"),
            (f"git {nl}push --no-verify origin HEAD:main", c, "deny"),
            (f"gh api {nl}-X PUT {nl}'repos/{{owner}}/{{repo}}/pulls/3/merge'", c, "ask"),
            ("echo x # 메모 \\\ngh pr merge 3", c, "ask"),             # 주석 끝 `\`는 줄을 잇지 않는다
            ("gh api graphql -f query='query { viewer \\\n { login } }'", plain, None),   # 작은따옴표 안 줄 이음은 글자
            # `$'…'`
            ("echo $'it\\'s'; gh pr merge 3 --squash", c, "ask"), ("gh pr $'merge' 3", c, "ask"),
            (f"gh api -X PUT $'repos/{DB_SLUG}/pulls/3/merge'", plain, "ask"),
            # 오탐 방지: 글 명령 안의 낱말, 이슈 DB 읽기
            (f"echo then gh pr merge 3 -R {DB_SLUG}", plain, None), ("grep -n 'do gh pr merge' notes.md", plain, None),
            ("if true; then gh pr view 3; fi", c, None), ("for n in 3 4; do gh pr view $n --json state; done", c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_cd_scope_follows_bash_subshells_pipes_and_branches():
    """명령 파싱(H-A1 r6): cd·pushd·popd는 bash 범위대로 따라간다(`_Walk`). 서브셸(`( … )`·`$( … )`·`<( … )`)·파이프 요소·`&`
    백그라운드 목록의 cd는 밖에 남지 않는다(`{ …; } | cat`·`… | while …; done` 같은 복합 명령 요소도). `&&`·`||` 뒤·분기·루프 안
    cd는 돌지 않았을 수 있어 전후 cwd를 모두 본다. 함수 본문의 cd는 정의할 때 돌지 않는다(뒤에서 부를 수 있어 모르는 cwd도 본다).
    `eval`·`{ …; }`·`builtin cd`의 cd는 남는다. `source`·`.`·셸 값 `eval`과 명령 글의 `CDPATH`는 모르는 cwd를 더한다. 셸이
    읽는 heredoc 본문은 그 글에서 거친 모든 cwd로 본다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    other = _repo_with_origin("https://ghe.mock.invalid/other/repo")
    wt = ws.work / "wt-cdscope"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    p = "git push --no-verify origin HEAD:main"     # cwd 탐침(규칙 5 — ci_mode local이라 거부). gh 규칙 11은 cwd를 보지 않는다(4-c)
    rows = [
        # 서브셸·치환·파이프·백그라운드 안의 cd는 이슈 DB worktree·clone을 가리지 않는다
        (f"(cd /tmp && ls) ; {p}", wt, "deny"),
        (f"(cd /tmp && ls) && {p}", wt, "deny"),
        (f"(cd {other} && git log -1) && gh pr review 3 --approve", wt, "deny"),
        (f"(cd {other}) ; {p}", c, "deny"),
        (f"cd {other} | cat; {p}", c, "deny"),
        (f"cat /dev/null | cd {other}; {p}", c, "deny"),
        (f"echo $(cd {other} && pwd); {p}", c, "deny"),
        (f"diff <(cd {other}; ls) x; {p}", c, "deny"),
        (f"cd {other} && ls & {p}", c, "deny"),
        (f"{{ cd {other}; }} | cat; {p}", c, "deny"),
        (f"ls | while read l; do cd {other}; done; {p}", c, "deny"),
        (f"for d in a; do cd {other}; done | cat; gh pr review 3 --approve", c, "deny"),
        (f"(cd {other} && ls) ; gh pr create -t x -b y", wt, "ask"),
        # 조건부·분기·함수 본문: 돌지 않았을 수 있다 — 전 cwd도 본다
        (f"false && cd {other}; {p}", c, "deny"),
        (f"if test -d x; then cd {other}; fi; {p}", c, "deny"),
        (f"case $X in a) cd {other};; esac; {p}", c, "deny"),
        (f"f() {{ cd {other}; }}; {p}", c, "deny"),
        (f"cd {c} && bash <<'EOF'\n{p}\nEOF", plain, "deny"),
        # 다른 레포에서 서브셸로 이슈 DB에 들어갔다 나오면 대상이 아니다
        (f"(cd {wt} && ls) ; {p}", other, None),
        (f"echo $(cd {c} && pwd); {p}", plain, None),
        (f"cd {c} | cat; {p}", plain, None),
        # bash처럼 남는 cd는 그대로 따라간다
        (f"cd {other} && ls ; {p}", c, None),
        (f"{{ cd {other}; }} ; {p}", c, None),
        (f"cd {other} && {p}", wt, None),
        (f"eval 'cd {c}'; {p}", plain, "deny"),
        (f"builtin cd {c}; {p}", plain, "deny"),
        (f"cd {c}; ({p})", plain, "deny"),
        (f"(cd {other} && ls); {p}", c, "deny"),
        (f"git -C {other} log | cd {other}; {p}", c, "deny")]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_cwd_moves_that_can_fail_keep_previous_candidates():
    """명령 파싱(회귀 수정 R1): 실패할 수 있거나 대상을 모르는 이동은 이전 cwd 후보를 버리지 않는다. 모르는 디렉토리는 git 규칙(3~8·12)에선
    판정하지 못하는 후보라(규칙 11은 4-c부터 cwd를 보지 않는다), 이전 후보를 버리면 이슈 DB clone·worktree에서 도는
    명령을 놓친다. Claude Code는 Bash 호출마다 새 셸이라 앞 호출의 pushd 스택은 없다 — 빈 스택 popd는 실패하고 cwd는 그대로다.
    `popd -n`·`popd +N`(N≥1)·`pushd -n`은 cwd를 바꾸지 않는다(스택만). 분기를 합쳐 스택이 달라지면 뒤 popd는 스택 칸 모두·이전
    후보·모르는 디렉토리로 본다. 없는 경로·셸이 풀 경로로의 cd도 실패할 수 있다(바로 뒤가 `&&`면 뒤 명령은 돌지 않는다)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-cdfail"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [
        # 빈 스택 popd: 실패 — cwd 그대로
        ("popd; git push --no-verify origin HEAD:main", c, "deny"), ("popd; git push --no-verify origin HEAD:main", wt, "deny"),
        ("popd 2>/dev/null; git checkout -b x", c, "deny"), ("popd; git reset --hard origin/main", c, "deny"),
        ("popd; echo x > notes.txt", c, "deny"), ("popd; git commit --no-verify -m x", c, "deny"),
        ("popd; git commit --no-verify -m x", wt, "deny"), ("popd; git push --no-verify origin HEAD:issue/x", wt, "deny"),
        ("popd; gh pr merge 3", plain, "ask"),                       # 규칙 11은 cwd를 보지 않는다(4-c) — 명령을 찾았다
        # popd -n·+N(N≥1)·pushd -n: cwd를 바꾸지 않는다
        (f"pushd {c} >/dev/null; popd -n; git push --no-verify origin HEAD:main", plain, "deny"),
        (f"pushd {c} >/dev/null; popd -n; gh pr merge 3", plain, "ask"),
        (f"pushd {c} >/dev/null; popd +1; git push --no-verify origin HEAD:main", plain, "deny"),
        ("pushd -n /tmp; git push --no-verify origin HEAD:main", c, "deny"),
        (f"pushd -n {c}; popd; git push --no-verify origin HEAD:main", plain, "deny"),   # -n으로 넣은 칸으로 popd
        # 인자 없는 pushd·pushd ±N·이전 디렉토리를 모르는 cd -·cd ±N: 실패하거나 모르는 칸
        ("pushd; git push --no-verify origin HEAD:main", c, "deny"), ("pushd +1; git push --no-verify origin HEAD:main", c, "deny"),
        ("cd -; git push --no-verify origin HEAD:main", c, "deny"), ("cd -1; git push --no-verify origin HEAD:main", c, "deny"),
        ("popd -0; git push --no-verify origin HEAD:main", c, "deny"),
        # 분기로 스택을 모르게 되면 뒤 popd는 스택 칸·이전 후보 모두
        ("if test -d x; then pushd /tmp; fi; popd; git push --no-verify origin HEAD:main", c, "deny"),
        (f"pushd {c} && pushd /tmp; popd; git push --no-verify origin HEAD:main", plain, "deny"),
        # 없는 경로·셸이 풀 경로: cd가 실패하면 cwd 그대로(`||` 뒤는 실패한 경우다)
        (f"cd {plain}/nope; git push --no-verify origin HEAD:main", c, "deny"),
        ('cd "$D"; git checkout -b x', c, "deny"),
        (f"cd {plain}/nope || git push --no-verify origin HEAD:main", c, "deny"),
        (f"cd {plain}/nope && ls || git push --no-verify origin HEAD:main", c, "deny"),
        # 오탐 방지: 따라갈 수 있는 스택은 그대로 따라간다, `&&` 뒤는 cd가 성공한 경우뿐이다
        (f"pushd {plain} >/dev/null; popd; git push --no-verify origin HEAD:main", c, "deny"),
        (f"pushd {plain} >/dev/null; popd -n; git push --no-verify origin HEAD:main", c, None),
        (f"pushd {plain} >/dev/null; popd +0; git push --no-verify origin HEAD:main", c, "deny"),
        (f"pushd {plain} >/dev/null; pushd; git push --no-verify origin HEAD:main", c, "deny"),
        (f"pushd {c} >/dev/null; pushd; git push --no-verify origin HEAD:main", plain, None),
        (f"cd {plain}; popd -n; git push --no-verify origin HEAD:main", c, None),
        (f"cd {plain}/nope && git push --no-verify origin HEAD:main", c, None),
        (f"pushd {c} >/dev/null; popd +0; git push --no-verify origin HEAD:main", plain, None),
        (f"pushd {c} && popd && git push --no-verify origin HEAD:main", plain, None),
        (f"cd {c} && cd {plain} && git push --no-verify origin HEAD:main", plain, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_cwd_candidate_overflow_keeps_first_and_latest():
    """명령 파싱(회귀 수정 R4): cwd 후보가 상한(`CWD_CAP`)을 넘으면 처음 후보와 가장 최근 후보들을 남기고 가운데를 모르는
    디렉토리로 접는다 — 넘침이 마지막 cd 대상(이슈 DB clone)을 버리지 않는다. 접힌 후보는 모르는 디렉토리로 남는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    subs = [plain / f"d{i}" for i in range(9)]
    for d in subs:
        d.mkdir()
    chain = "; ".join(f"true && cd {d}" for d in subs[:7])
    arms = " ".join(f"{chr(97 + i)}) cd {d};;" for i, d in enumerate(subs[:7]))
    rows = [(f"{chain}; true && cd {c}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"case $X in {arms} h) cd {c};; esac; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"{chain}; true && cd {subs[7]}; true && cd {subs[8]}; git push --no-verify origin HEAD:main", c, "deny"),   # 처음 cwd
            (f"{chain}; true && cd {subs[7]}; true && cd {subs[8]}; gh pr merge 3", plain, "ask"),          # 접힌 후보
            (f"{chain}; true && cd {c}; git push origin HEAD:issue/x", plain, "ask")]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def _raising_realpath_env(ws: Workspace) -> dict:
    """guard 하위 프로세스에서 `RAISEMARK`가 든 경로의 `os.path.realpath`가 ValueError를 내게 한다(`sitecustomize` — 경로 연산
    예외가 판정 전체를 무너뜨리지 않는지 본다)."""
    d = tmp("tt-raise-")
    (d / "sitecustomize.py").write_text(
        "import os.path as _p\n_real = _p.realpath\n\n\n"
        "def realpath(path, *a, **k):\n"
        "    if 'RAISEMARK' in str(path):\n        raise ValueError('test: 경로 연산 예외')\n"
        "    return _real(path, *a, **k)\n\n\n_p.realpath = realpath\n", encoding="utf-8")
    return {**ws.env(), "PYTHONPATH": str(d)}


def test_guard_ansi_c_nul_surrogates_and_path_errors_do_not_degrade():
    """명령 파싱(회귀 수정 R2): `$'…'`의 NUL(`\\0`·`\\x00`·`\\000`·`\\u0000`·`\\c@`)은 bash처럼 그 인용의 나머지를 버리고(`$'a\\0b'c`
    = `ac`), 서로게이트(`\\ud800`)는 U+FFFD다. 명령 글의 날 NUL은 빼고 짝 없는 서로게이트는 U+FFFD다(이 글자들이 예외를 내지
    않는다). 경로 연산이 그래도 예외를 내면 그 호출은 거부(사유 `guard 내부 오류`, 4-c)하고 다른 검사는 사유를 남기도록 이어 간다.
    출력은 ASCII JSON이라 사유에 인코딩할 수 없는 글자가 들어도 종료 0이다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-ansic"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [("cat $'\\x00x'; gh pr merge 3 --squash", c, "ask", "머지"),
            ("cat $'\\0'; git push --no-verify origin HEAD:main", wt, "deny", "규칙 5"),
            ("cat $'\\ud800'; gh pr merge 3", wt, "ask", "머지"),
            ("echo hi > $'\\0x'; gh pr merge 3", wt, "ask", "머지"),
            ("cat $'\\0'; git commit --no-verify -m x", c, "deny", "규칙 5"),
            ("cat $'\\c@'; git push --no-verify origin HEAD:main", c, "deny", "규칙 5"),
            ("cat $'\\u0000'; git push --no-verify origin HEAD:main", c, "deny", "규칙 5"),
            ("cat $'\\000'; git push --no-verify origin HEAD:main", c, "deny", "규칙 5"),
            ("git config core.hooksPath $'\\ud800'", c, "deny", "규칙 5"),
            # bash는 NUL 뒤를 버린다: 낱말이 그 앞까지다
            ("git $'push\\0junk' --no-verify origin HEAD:main", c, "deny", "규칙 5"),
            ("gh pr $'merge\\x00x' 3", c, "ask", "머지"), ("git push --no-verify origin $'HEAD:main\\0x'", c, "deny", "규칙 5"),
            # 명령 글의 날 NUL·짝 없는 서로게이트(hook 입력 JSON의 \u0000·\ud800)
            ("cat \x00x; gh pr merge 3", c, "ask", "머지"), ("git config core.hooksPath \ud800", c, "deny", "규칙 5"),
            ("echo hi > x\x00y; git push --no-verify origin HEAD:main", c, "deny", "규칙 5"),
            ("cat $'\\x00x'", plain, None, None)]
    try:
        for cmd, cwd, want, why in rows:
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
            proc = run("guard.py", [], root=ws.root, cwd=cwd, env=ws.env(), stdin=json.dumps(event))
            assert proc.returncode == 0 and "내부 오류" not in proc.stderr, (cmd, proc.stderr)
            assert proc.stdout.isascii(), cmd
            out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
            assert decision(out) == want, (cmd, cwd)
            assert why is None or why in out["permissionDecisionReason"], (cmd, out)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))
    # 경로 연산 예외(여기선 sitecustomize로 일으킨다): 그 호출은 거부(guard 내부 오류), 같은 명령의 다른 검사 사유도 남는다
    env = _raising_realpath_env(ws)
    for cmd, cwd, why in [("echo x > RAISEMARK; gh pr merge 3", c, "규칙 8"),       # 병합 ask는 거부 사유에 들지 않는다
                          ("echo x > RAISEMARK; git push --no-verify origin HEAD:main", c, "규칙 5"),
                          ("echo x > RAISEMARK; git commit --no-verify -m x", c, "규칙 5"),
                          ("echo x > RAISEMARK", plain, "규칙 8")]:
        out = bash(ws, cmd, cwd, env=env)
        assert decision(out) == "deny" and "guard 내부 오류" in out["permissionDecisionReason"], (cmd, out)
        assert why in out["permissionDecisionReason"], (cmd, out)


def test_guard_ansi_c_closing_quote_found_like_bash():
    """명령 파싱(재리뷰 P0, e8f3342 회귀): `$'…'`의 닫는 `'`는 bash 어휘 분석처럼 먼저 찾고(`\\` 뒤 한 글자는 건너뛴다) 풀이는 그
    안에서만 한다. 예전에는 인용 끝의 `\\c`가 닫는 `'`를 제어 문자 재료로 먹어 명령 글 끝까지를 한 인용으로 삼켰고, 그 뒤의 main
    push·병합·--no-verify·clone 쓰기·로그 통독이 판정 밖으로 빠졌다(bash는 `$'\\c'`를 `\\c` 글자로 두고 다음 명령을 돈다)."""
    import guard
    assert guard._ansi_c("$'\\c'; x", 2) == ("\\c", 5)
    assert guard._ansi_c("$'\\c\\\\'; x", 2) == ("\x1c", 7)            # `\c\\` = 제어-\ (두 `\`를 함께)
    assert guard._ansi_c("$'\\c\\''; x", 2) == ("\x1c'", 7)            # `\'`는 어휘 분석에서 인용을 닫지 않는다
    assert guard._ansi_c("$'a\\cAb\\c?'", 2) == ("a\x01b\x7f", 11)
    assert guard._ansi_c("$'\\x4'1", 2) == ("\x04", 6)                  # 16진 풀이가 닫는 `'` 뒤로 넘지 않는다
    assert guard._ansi_c("$'ab\\", 2) == ("ab\\", 5)                    # 닫히지 않으면 끝까지
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    (plain / "x.log").write_text(LOGCAT, encoding="utf-8")             # 규칙 10: logcat 원문
    wt = ws.work / "wt-ansic-c"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [("echo $'\\c'; git push --no-verify origin HEAD:main", c, "deny"), ("echo $'\\c'; gh pr merge 3", c, "ask"),
            ("echo $'\\c'; git commit --no-verify -m x", c, "deny"), ("echo $'\\c'; echo x > notes.txt", c, "deny"),
            ("echo $'\\c'; git checkout -b x", c, "deny"), ("echo $'\\c'; git push --no-verify origin HEAD:main", wt, "deny"),
            ("echo $'\\c\\\\'; git push --no-verify origin HEAD:main", c, "deny"),
            ("echo $'\\c\\''; git push --no-verify origin HEAD:main", c, "deny"),
            ("printf %s $'x\\c' && git push --no-verify origin HEAD:main", c, "deny"),
            ("echo $'\\c'\ngit push --no-verify origin HEAD:main", c, "deny"),
            ("echo $'\\c'; gh api -X PUT repos/mock-org/telephony-issue-db/pulls/3/merge", plain, "ask"),
            ("echo $'\\c'; cat x.log", plain, "deny"),
            ("echo $'\\c'", c, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_long_cwd_candidates_stay_in_worktree_and_job_dir():
    """명령 파싱(재리뷰 P1): `LONG_CWD`보다 긴 cwd 후보(상대 cd가 길게 이어진 것)는 bash 논리 cd처럼 `..`을 접고, 그래도 길면 상한
    안의 조상으로 자른다 — 같은 worktree·작업 폴더 안에 남는다. 예전에는 보호 뿌리(work_dir)로 접어 worktree의 main push·
    --no-verify와 작업 폴더의 승인·병합 제안 기록 쓰기가 판정 밖으로 빠졌다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-longcwd"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    (wt / "data").mkdir(exist_ok=True)
    job = ws.job_dir("MOCK-7202")
    (job / "s").mkdir(parents=True, exist_ok=True)
    deep = plain / "/".join(["d" * 60] * 20)                           # `..` 없이 1024자를 넘는 깊은 경로
    deep.mkdir(parents=True)
    hops, shops = "data/../" * 150, "s/../" * 220                     # `.`은 pathlib이 접는다 — `..` 사슬로
    # 심볼릭 링크를 지나는 긴 사슬: 실제 경로(cd -P·글자 경로가 없을 때의 기본 cd)로도 본다
    (plain / "Lc").symlink_to(c / ".git")                              # Lc/.. = clone (clone은 바꾸지 않는다)
    (plain / "Lwt").symlink_to(wt / "data")
    (plain / "Ljob").symlink_to(job / "s")
    (deep / "Lc").symlink_to(c)
    # 1024자보다 깊은 실제 디렉토리: 뒤 상대 `..`는 실제 깊이에서 올라간다
    dd = "/".join(["e" * 60] * 20)
    (wt / "data" / dd).mkdir(parents=True)
    (job / "s" / dd).mkdir(parents=True)
    rows = [(f"cd {hops}data; git push --no-verify origin HEAD:main", wt, "deny"),
            (f"cd {hops}data && git commit --no-verify -m x", wt, "deny"),
            (f"cd {wt}/{hops}; git push --no-verify origin HEAD:main", plain, "deny"),
            ("cd data; ls; cd ..; " * 120 + "git push --no-verify origin HEAD:main", wt, "deny"),
            (f"cd {shops}; echo x > post.approved.json", job, "deny"),
            (f"cd {shops}; echo x > merge-offer.json", job, "deny"),
            (f"cd {shops}; rm -f post.result.json", job, "deny"),
            (f"cd {hops}; git push --no-verify origin HEAD:main", c, "deny"),
            (f"cd -P Lc/../{hops}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"cd -P Lc/..; cd {hops}; git commit --no-verify -m x", plain, "deny"),
            (f"cd Lc/../{hops}; git push --no-verify origin HEAD:main", plain, "deny"),     # 글자 경로 plain/data가 없다: bash는 실제 경로로
            (f"cd -P Lwt/../{hops}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"cd -P Ljob/../{shops}; echo x > post.approved.json", plain, "deny"),
            (f"cd {deep}/Lc; git push --no-verify origin HEAD:main", plain, "deny"),
            ("git push --no-verify origin HEAD:main", deep / "Lc", "deny"),                # hook cwd 자체가 긴 링크 경로
            (f"cd data/{dd}; cd {'../' * 20}; git push --no-verify origin HEAD:main", wt, "deny"),
            (f"cd data/{dd} && cd {'../' * 20} && git commit --no-verify -m x", wt, "deny"),
            (f"cd s/{dd}; cd {'../' * 21}; echo x > merge-offer.json", job, "deny"),
            (f"cd {'../' * 20}; git push --no-verify origin HEAD:main", wt / "data" / dd, "deny"),
            # 오탐 방지: 길어도 이슈 DB 밖이면 그대로
            (f"cd {deep}; git push --no-verify origin HEAD:main", plain, None),
            (f"cd {'x/../' * 300}; git push --no-verify origin HEAD:main", plain, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd[:80], cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_overflow_folds_into_repo_or_job_dir():
    """명령 파싱(재리뷰): 보호 뿌리 안 cwd 후보가 상한을 넘으면 오래된 것은 그 후보가 든 레포 꼭대기(`.git`이 있는 곳)나 작업 폴더로
    접는다. 예전에는 보호 뿌리 자체(work_dir)로 접어 worktree·작업 폴더 후보를 잃었다 — 실패하는 cd가 여럿 이어진 뒤(bash는 처음
    들어간 worktree·작업 폴더에 남는다)의 main push·--no-verify·승인 기록 쓰기가 판정 밖으로 빠졌다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-fold"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    job = ws.job_dir("MOCK-7203")
    job.mkdir(parents=True, exist_ok=True)
    fails = "; ".join(f"cd {job}/nosuch{i}" for i in range(10))
    wt_fails = "; ".join(f"cd {wt}/nosuch{i}" for i in range(10))
    rows = [(f"true && cd {wt}; {fails}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"true && cd {wt}; {fails}; git commit --no-verify -m x", plain, "deny"),
            (f"true && cd {c}; {fails}; echo x > notes.txt", plain, "deny"),
            (f"true && cd {job}; {wt_fails}; echo x > post.approved.json", plain, "deny"),
            (f"{fails}; git push --no-verify origin HEAD:main", plain, None)]                     # 오탐 방지: 레포에 들어간 적 없음
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd[:80], cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_unknown_stack_keeps_latest_push_and_deep_dirs():
    """명령 파싱(마지막 리뷰 P0): 칸을 모르게 된 pushd 스택을 하나로 합칠 때 bash처럼 마지막에 넣은 칸이 이긴다 — 다시 넣은 칸을
    첫 자리로 두면 넘침 때 최근 칸(bash가 popd로 돌아갈 곳)을 접었다. 4096자(PATH_MAX)보다 깊은 실제 디렉토리는 자르지 않는다 —
    bash는 상대 cd로 들어갈 수 있고 잘린 조상에서 뒤 `..`가 작업 폴더·clone 밖으로 올라갔다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-stackorder"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    (wt / "data" / "w0").mkdir(parents=True)
    jobs = [ws.job_dir(f"MOCK-74{i:02d}") for i in range(10)]
    for j in jobs:
        j.mkdir(parents=True, exist_ok=True)
    for i in range(8):
        (plain / f"p{i}").mkdir()
    (plain / "p0" / "x.log").write_text(LOGCAT, encoding="utf-8")            # 규칙 10: logcat 원문
    w0 = wt / "data" / "w0"
    seq = (f'pushd "$D"; pushd {w0}; ' + "; ".join(f"pushd {j}" for j in jobs[1:5]) + f"; pushd {w0}; "
           + "; ".join(f"pushd {j}" for j in jobs[5:10]) + "; popd; popd; popd; popd; popd")
    raw = (f"pushd /nonexist; pushd {plain}/p0; " + "; ".join(f"pushd {plain}/p{i}" for i in range(1, 6))
           + f"; pushd {plain}/p0; pushd {plain}/p6; pushd {plain}/p7; popd; popd; cat x.log")
    # 4096자보다 깊은 실제 디렉토리(긴 경로는 한 번에 못 만든다 — dir_fd로 한 칸씩)
    job = jobs[0]
    (job / "s" / "H").mkdir(parents=True)
    comp = "h" * 200
    fd = os.open(job / "s" / "H", os.O_RDONLY)
    try:
        for _ in range(22):
            os.mkdir(comp, dir_fd=fd)
            nfd = os.open(comp, os.O_RDONLY, dir_fd=fd)
            os.close(fd)
            fd = nfd
    finally:
        os.close(fd)
    h11 = "/".join([comp] * 11)
    rows = [(seq + "; git push --no-verify origin HEAD:main", plain, "deny"),
            (seq + "; git commit --no-verify -m x", plain, "deny"),
            (raw, plain, "deny"),
            (f"cd s/H/{h11}; cd {h11}; cd {'../' * 24}; echo x > merge-offer.json", job, "deny"),
            (f"cd s/H/{h11} && cd {h11} && cd {'../' * 24} && rm -f post.result.json", job, "deny")]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd[:80], cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_pushd_popd_chains_stay_fast():
    """명령 파싱(재리뷰 P1 성능): 실패할 수 있는 pushd(없는 경로)가 스택을 '모름'으로 만든 뒤에도 칸을 하나로 합쳐 상한 안에 둔다.
    예전에는 칸이 pushd마다 쌓이고 popd마다 모두 다시 봐서 pushd 1000개 + popd 1000개가 hook 시간 한도(180초)를 넘겼다 — Claude
    Code는 시간 초과를 막지 않는다(fail-open). 긴 상대 경로 후보는 한 번 줄인 꼴을 다시 풀지 않는다."""
    import time
    ws = shared()
    c = ws.clone
    wt = ws.work / "wt-pushd-perf"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    pd = "\n".join(f"pushd x{i}" for i in range(1000)) + "\n" + "\n".join("popd" for _ in range(1000))
    plain = tmp("tt-gh-plain-")
    arms = " ".join(f"a{i}) cd {plain};;" for i in range(7))
    sticky = f"source /dev/null; case $X in {arms} esac; " + "pushd .; " * 1000 + "popd; " * 1000   # sticky(마지막 리뷰 P1)
    # 깊은 실제 디렉토리(약 3.9K자)에서 `..` 사슬: `..`마다 realpath를 처음부터 하면 cd 1000개가 한도를 넘겼다(마지막 리뷰 P1)
    deep = wt / "data" / "M" / "/".join(["m"] * 1900)
    subprocess.run(["mkdir", "-p", str(deep)], check=True)          # pathlib mkdir(parents)는 1900단계에서 재귀 한도
    dots = "\n".join(f"cd x{i}/.. || cd y{i}/.." for i in range(300))
    try:
        for cmd, cwd in ((pd, wt), (pd, c), (sticky, c), (dots, deep)):
            t0 = time.monotonic()
            assert decision(bash(ws, cmd + "\ngit push --no-verify origin HEAD:main", cwd)) == "deny", cwd
            assert time.monotonic() - t0 < 30, (cmd[:40], time.monotonic() - t0)     # 이 PC 3~6초, 예전 115~250초
    finally:
        # 1900단계 디렉토리는 `rm -rf`로 먼저 지운다: 남으면 세션 끝 `shutil.rmtree`가 Python 3.11 이하에서 재귀 한도에 걸린다
        subprocess.run(["rm", "-rf", str(wt / "data" / "M")], check=False)
        gitp(c, "worktree", "remove", "--force", str(wt))


def _site_env(ws: Workspace, code: str, no_yaml: bool = False) -> dict:
    """guard 하위 프로세스에 `sitecustomize`(`code`)를 얹는다. `no_yaml`이면 PyYAML import도 실패하게 한다(의존성 없음 판정)."""
    d = tmp("tt-site-")
    (d / "sitecustomize.py").write_text(code, encoding="utf-8")
    if no_yaml:
        (d / "yaml.py").write_text('raise ImportError("PyYAML 없음 (테스트)")\n', encoding="utf-8")
    return {**ws.env(), "PYTHONPATH": str(d)}


# `EACCESMARK`가 든 경로의 stat이 PermissionError — 남의 홈·/root 아래처럼 들어갈 수 없는 경로(root가 아닌 사용자)를 흉내 낸다.
# Python 3.13의 `Path.is_dir`은 ENOENT·ENOTDIR·EBADF·ELOOP 밖의 OSError를 그대로 올린다
# 바꿔 끼운 stat은 `__get__` 없는 호출 객체다: Python 3.10 pathlib `_NormalAccessor.stat = os.stat`이 함수를 메서드로 묶어
# 경로 자리에 accessor가 들어가는 일을 막는다(3.11부터는 accessor가 없다)
EACCES_SITE = ("import errno, os\n_stat = os.stat\n\n\n"
               "class _Stat:\n"
               "    def __call__(self, path, *a, **k):\n"
               "        if not isinstance(path, int) and 'EACCESMARK' in os.fsdecode(path):\n"
               "            raise PermissionError(errno.EACCES, 'Permission denied (test)', os.fsdecode(path))\n"
               "        return _stat(path, *a, **k)\n\n\nos.stat = _Stat()\n")
# `WALKRAISE`가 든 글의 `os.path.expandvars`가 RuntimeError — guard의 명령 걷기(`invocations`)가 예외로 끝나게 한다
WALK_SITE = ("import posixpath\n_ev = posixpath.expandvars\n\n\n"
             "def expandvars(p):\n"
             "    if 'WALKRAISE' in str(p):\n        raise RuntimeError('test: 걷기 예외')\n"
             "    return _ev(p)\n\n\nposixpath.expandvars = expandvars\n")


def test_guard_unreachable_cd_targets_do_not_degrade():
    """명령 파싱(재리뷰 P0): 들어갈 수 없는 cd 대상(경로 칸이 255바이트를 넘는 이름 — ENAMETOOLONG, 남의 홈·/root 아래 — EACCES)은
    실패할 수 있는 이동이다: 이전 cwd 후보를 남기고 판정을 이어 간다. 예전에는 stat 예외가 명령 걷기 밖으로 새어 판정 전체가 내부
    오류(ask)로 무너졌고, 같은 명령 어디에든 `; cd <그런 경로>`를 붙이면 병합·Approve·main push·--no-verify·clone 쓰기가
    deny에서 ask로 약해졌다(`_degraded`의 걷기도 같은 예외를 내 병합 거부가 돌지 않았다)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-unreach"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    long_abs, long_rel, long_in = "/tmp/" + "b" * 300, "c" * 300, f"{c}/" + "e" * 300
    rows = [(f"gh pr merge 3 --squash; cd {long_abs}", wt, "ask"), (f"git push --no-verify origin HEAD:main; cd {long_abs}", c, "deny"),
            (f"git commit --no-verify -m x; pushd {long_abs}", c, "deny"),
            (f"cd {long_abs}; cd {c}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"cd {long_abs} 2>/dev/null; cd {c} && gh pr merge 3 --squash", plain, "ask"),
            (f"cd {long_abs} 2>/dev/null; cd {c}; echo x > notes.txt", plain, "deny"),
            (f"cd {long_abs} 2>/dev/null; cd {c}; git checkout -b x", plain, "deny"),
            (f"true && cd {long_abs}; cd {c}; git push --no-verify origin HEAD:main", wt, "deny"),
            (f"(cd {long_abs}); cd {c}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"pushd -n {long_abs}; cd {c}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"cd {long_abs}; gh pr review 3 --approve", plain, "deny"), (f"cd {long_abs}; gh pr review 3 --approve", c, "deny"),
            (f"echo x > notes.txt; cd {long_abs} || true", c, "deny"),
            (f"git push --no-verify origin HEAD:main; cd {long_rel}", c, "deny"), (f"git push --no-verify origin HEAD:main; cd {long_in}", c, "deny"),
            (f"cd {long_in}; git push --no-verify origin HEAD:main", c, "deny"),         # cd가 실패하면 clone 그대로
            (f"cd {long_abs} 2>/dev/null; ls", plain, None)]
    eacces = _site_env(ws, EACCES_SITE)
    other = "/home/EACCESMARK/proj"
    erows = [(f"gh pr merge 3; cd {other}", wt, "ask"), (f"cd {other}; gh pr review 3 --approve", plain, "deny"),
             (f"echo x > notes.txt; cd {other} || true", c, "deny"), (f"cd {other}; gh pr merge 3", wt, "ask"),
             (f"cd {other} 2>/dev/null; cd {c}; git push --no-verify origin HEAD:main", plain, "deny"),
             (f"pushd {other} >/dev/null 2>&1; cd {c} && gh pr merge 3 --squash", plain, "ask"),
             (f"cd {other}; git push --no-verify origin HEAD:main", c, "deny"), (f"cd {other}; ls", plain, None)]
    try:
        for (cmd, cwd, want), env in [*((r, None) for r in rows), *((r, eacces) for r in erows)]:
            event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
            proc = run("guard.py", [], root=ws.root, cwd=cwd, env=env or ws.env(), stdin=json.dumps(event))
            assert proc.returncode == 0 and "내부 오류" not in proc.stderr, (cmd[:80], proc.stderr)
            out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
            assert decision(out) == want, (cmd[:80], cwd, out)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_walk_errors_fall_back_closed():
    """명령 파싱(4-c): 명령 걷기(`invocations`) 자체가 예외로 끝나면 그 호출은 거부(사유 `guard 내부 오류` — 명령 파싱)하고, cd를
    따라가지 않는 대체 목록(처음 cwd·cd 절대 대상·모르는 디렉토리)으로 다른 검사를 이어 가 그 사유도 남긴다. 의존성 없음
    판정(`_degraded`)은 그대로 — 걷기가 예외면 낱말 수준으로 Approve·보호 바꾸기를 거부한다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    env = _site_env(ws, WALK_SITE)
    for cmd, cwd, why in [("env -C WALKRAISE true; gh pr merge 3", plain, "명령 파싱"),
                          ("env -C WALKRAISE true; gh pr review 3 --approve", plain, "Approve"),
                          ("env -C WALKRAISE true; git push --no-verify origin HEAD:main", c, "규칙 5"),
                          ("env -C WALKRAISE true; git commit --no-verify -m x", c, "규칙 5"),
                          (f"env -C WALKRAISE true; cd {c}; git push --no-verify origin HEAD:main", plain, "규칙 5"),
                          ("env -C WALKRAISE true; ls", plain, "명령 파싱"),
                          ("env -C WALKRAISE true; gh pr view 3", plain, "명령 파싱")]:
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
        proc = run("guard.py", [], root=ws.root, cwd=cwd, env=env, stdin=json.dumps(event))
        assert proc.returncode == 0 and "Traceback" not in proc.stderr, (cmd, proc.stderr)
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        reason = out["permissionDecisionReason"]
        assert decision(out) == "deny" and "guard 내부 오류" in reason and why in reason, (cmd, out)
    env = _site_env(ws, WALK_SITE, no_yaml=True)
    for cmd, want in [("env -C WALKRAISE true; gh pr merge 3", "ask"), ("env -C WALKRAISE true; gh pr review 3 -a", "deny"),
                      ("env -C WALKRAISE true; gh api -X PATCH repos/o/r -F delete_branch_on_merge=true", "deny"),
                      ("env -C WALKRAISE true; gh pr view 3", "ask"), ("env -C WALKRAISE true; echo hi", None)]:
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(plain)}
        proc = run("guard.py", [], root=ws.root, cwd=plain, env=env, stdin=json.dumps(event))
        assert proc.returncode == 0 and "Traceback" not in proc.stderr, (cmd, proc.stderr)
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert decision(out) == want, (cmd, out)
        assert want is None or "의존성 없음" in out["permissionDecisionReason"], (cmd, out)


def test_guard_broken_config_is_degraded_not_denied():
    """4-c 리뷰: 설정 읽기 오류(사용자 config.yaml YAML 오류)는 판정 예외가 아니다 — 의존성 없음과 같은 판정(MCP 거부, git·gh·파일
    도구 ask, 그 밖 Bash 통과 + 경고)이라 그 config를 고치는 Write·`ls`·doctor는 막히지 않는다. 판정 중 예외(아래 시험)는 거부."""
    ws = shared()
    home = tmp("tt-badcfg-")
    cfg = home / "config.yaml"
    cfg.write_text("plugin: [깨진\n", encoding="utf-8")
    env = {**ws.env(), "TELEPHONY_TRIAGE_HOME": str(home)}
    plain = tmp("tt-gh-plain-")
    out = guard(ws, "Write", {"file_path": str(cfg), "content": "plugin: {}\n"}, plain, env=env)
    assert decision(out) == "ask" and "설정 읽기 오류" in out["permissionDecisionReason"], out
    assert "내부 오류" not in out["permissionDecisionReason"]
    # 사용자 안내 문구(11/08): 제한 모드임과 config.yaml을 고치면 풀린다는 것이 거부·질문 문구에 보인다
    assert "설정 파일을 읽지 못해 제한 모드입니다" in out["permissionDecisionReason"]
    assert "config.yaml" in out["permissionDecisionReason"] and "고치면 풀립니다" in out["permissionDecisionReason"]
    assert bash(ws, "ls", plain, env=env) is None
    status = bash(ws, "git status", plain, env=env)
    assert decision(status) == "ask" and "제한 모드" in status["permissionDecisionReason"]
    assert decision(guard(ws, JIRA_TOOLS[0], {"issue_key": "MOCK-1"}, plain, env=env)) == "deny"


def test_guard_judgment_exceptions_deny(monkeypatch, capsys):
    """4-c: 판정 중 예외(검사 함수 — `_checked`, `_gh_kind`·`_json_obj`, 명령 걷기, `judge` 자체 — `RecursionError` 포함)는 그
    호출을 거부하고 사유에 `guard 내부 오류`가 든다(ask·통과로 떨어지지 않는다). 다른 검사의 거부 사유도 남는다. 예외가 없으면
    마스킹 로그 읽기는 그대로 통과."""
    import io

    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import guard as g
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    (plain / "logs-masked").mkdir()
    (plain / "logs-masked" / "x.txt").write_text("<IMEI#1> 마스킹한 줄\n", encoding="utf-8")
    (plain / "c.json").write_text('{"event":"COMMENT"}', encoding="utf-8")
    for k, v in ws.env().items():
        monkeypatch.setenv(k, str(v))

    def judge(cmd: str, cwd: Path = plain):
        out, _ = g.judge({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}, str(ws.root))
        return out and out["hookSpecificOutput"]

    def boom(*_a, **_k):
        raise RecursionError("test: 판정 예외")

    assert judge("cat logs-masked/x.txt") is None
    for name, cmd, cwd, rule in (("check_raw_read", "cat logs-masked/x.txt", plain, "규칙 10"),
                                 ("_gh_kind", "gh pr view 3", plain, "규칙 11"),
                                 ("_json_obj", f"gh api repos/{DB_SLUG}/pulls/3/reviews --input c.json", plain, "규칙 11"),
                                 ("invocations", "ls", plain, "명령 파싱"),
                                 ("check_git", "git status", c, "규칙 3~8")):
        with monkeypatch.context() as m:
            m.setattr(g, name, boom)
            out = judge(cmd, cwd)
        reason = out["permissionDecisionReason"] if out else ""
        assert decision(out) == "deny" and "guard 내부 오류(RecursionError)" in reason and rule in reason, (name, out)
    with monkeypatch.context() as m:        # 다른 검사의 거부 사유도 남는다(같은 명령의 --no-verify)
        m.setattr(g, "check_raw_read", boom)
        reason = judge("cat logs-masked/x.txt; git commit --no-verify -m x", c)["permissionDecisionReason"]
    assert "guard 내부 오류" in reason and "규칙 5" in reason, reason
    assert judge("cat logs-masked/x.txt") is None
    with monkeypatch.context() as m:        # judge 자체 — main이 거부를 낸다(종료 0)
        m.setattr(g, "judge", boom)
        m.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"},
                                                         "cwd": str(plain)})))
        assert g.main([]) == 0
    got = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert got["permissionDecision"] == "deny" and "guard 내부 오류(RecursionError)" in got["permissionDecisionReason"]


def test_guard_cd_odd_options_dirs_and_negation_keep_previous_candidates():
    """명령 파싱(재리뷰 P1 — 회귀 수정 R1 부류): bash가 거절하거나 다른 셸에선 뜻이 다른 cd 꼴(cd의 `-L`·`-P`·`-e`·`-@` 밖 옵션,
    pushd·popd의 `-n` 밖 옵션 — zsh `popd -q`, 남는 인자 — zsh `cd a b`)은 실패할 수 있는 이동이라 이전 후보를 남기고 스택을 모른다고
    본다. `dirs`에 인자가 있거나(`dirs -c`는 스택을 비운다 — 뒤 popd는 실패한다) `DIRSTACK`이 나오면 스택 칸을 모른다. `!`로 부정한
    cd 뒤 `&&`는 cd가 실패했을 때만 돌므로 이동 전 cwd도 후보다(`&&` 미루기를 뒤집지 않는다)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-oddcd"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [(f"pushd {c} >/dev/null; dirs -c; popd; gh pr merge 3", plain, "ask"),
            (f"pushd {c} >/dev/null; dirs -c; popd; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"pushd {c} >/dev/null; dirs -c 2>/dev/null; popd; git commit --no-verify -m x", plain, "deny"),
            (f"pushd {c} >/dev/null; popd -q; gh pr merge 3", plain, "ask"),
            (f"pushd {c}; popd -x; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"pushd {c} >/dev/null; popd -q; echo x > notes.txt", plain, "deny"),
            (f"pushd {c} >/dev/null; DIRSTACK=(); popd; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"pushd {c} >/dev/null; pushd -q; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"pushd -q {c}; git push --no-verify origin HEAD:main", plain, "deny"),
            ("cd -Q /tmp; git push --no-verify origin HEAD:main", c, "deny"), ("cd /tmp /usr; git push --no-verify origin HEAD:main", c, "deny"),
            ("cd -x /tmp && git push --no-verify origin HEAD:main", c, "deny"), ("pushd -q /tmp; git push --no-verify origin HEAD:main", c, "deny"),
            ("pushd /tmp /usr; git push --no-verify origin HEAD:main", c, "deny"),
            # `!` 부정: 뒤 `&&`는 cd가 실패했을 때 돈다
            ("! popd && git push --no-verify origin HEAD:main", c, "deny"), ("! popd && git commit --no-verify -m x", c, "deny"),
            ("! cd /nonexist && git push --no-verify origin HEAD:main", c, "deny"),
            ("! cd nosub 2>/dev/null && git push --no-verify origin HEAD:main", c, "deny"),
            ('! cd "$D" && git checkout -b x', c, "deny"), ("! pushd /nonexist && git reset --hard origin/main", c, "deny"),
            ("time ! cd /nonexist && git push --no-verify origin HEAD:main", c, "deny"), ("! cd - && git push --no-verify origin HEAD:main", c, "deny"),
            ("! cd /nonexist && echo x > notes.txt", c, "deny"), ("! cd /nonexist && git push --no-verify origin HEAD:main", wt, "deny"),
            ("if ! cd /nonexist && git push --no-verify origin HEAD:main; then :; fi", c, "deny"),
            # 오탐 방지: bash cd 옵션(-L·-P·-e·-@·--)과 인자 없는 dirs는 그대로 따라간다, 부정 없는 `&&` 뒤는 cd가 성공한 경우뿐이다
            ("cd -P /tmp; git push --no-verify origin HEAD:main", c, None), ("cd -LP /tmp; git push --no-verify origin HEAD:main", c, None),
            ("cd -e -P /tmp; git push --no-verify origin HEAD:main", c, None), ("cd -- /tmp; git push --no-verify origin HEAD:main", c, None),
            (f"pushd {c} >/dev/null; dirs; popd; git push --no-verify origin HEAD:main", plain, None),
            (f"pushd {plain} >/dev/null; dirs -v; popd -n; git push --no-verify origin HEAD:main", c, None),     # -n: cwd 그대로
            ("cd /nonexist && git push --no-verify origin HEAD:main", c, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_andor_skipped_states_and_overflow_keep_clone_candidates():
    """명령 파싱(재리뷰 — bash를 판정 기준으로 한 퍼징에서 나온 부류): and-or 목록에서 건너뛴 명령의 상태도 뒤 명령의 cwd 후보다.
    `A || B && C`의 C는 A가 성공해 B를 건너뛴 상태에서도 돌고, `A && B || C`의 C는 A가 실패해 B를 건너뛴 상태에서도 돈다. `if`
    조건의 cd도 돌았으므로 `else`·`fi` 뒤는 조건의 끝 상태에서도 돈다(`if ! cd X; then …; else …`의 else는 X에서 돈다). cwd 후보가
    상한을 넘어 접힐 때도 보호 뿌리(이슈 DB clone·work_dir·스킬 소스) 안의 후보는 접지 않는다 — 처음에 들어간 clone이 뒤의 조건부
    cd 여럿에 밀려 모르는 디렉토리로 접히지 않게(e8f3342는 거부했고 회귀 수정 R4의 접기는 놓쳤다)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    subs = [plain / f"d{i}" for i in range(9)]
    for d in subs:
        d.mkdir()
    after = "; ".join(f"true && cd {d}" for d in subs)
    arms = " ".join(f"{i + 1}) cd {d};;" for i, d in enumerate(subs[:8]))
    rows = [(f"cd {c} || cd /tmp && git push --no-verify origin HEAD:main", plain, "deny"),
            ("false && cd /tmp || git push --no-verify origin HEAD:main", c, "deny"),
            ("test -d x && cd /tmp || git push --no-verify origin HEAD:main", c, "deny"),
            ("cd .. || pushd -q && cd -\ngit push --no-verify origin HEAD:main", c, "deny"),
            ("cd /tmp || cd /usr && cd - && git push --no-verify origin HEAD:main", c, "deny"),
            (f"cd {c} || pushd /tmp && gh pr merge 3", plain, "ask"),
            (f"cd {c} || cd /tmp && echo x > notes.txt", plain, "deny"),
            # if 조건의 cd도 돌았다: else·fi 뒤는 조건의 끝 상태에서도 돈다
            (f"if ! cd {c}; then cd /usr; else true; fi; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"if ! cd {c}; then cd /usr; fi; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"if cd {c}; false; then cd /usr; else git push --no-verify origin HEAD:main; fi", plain, "deny"),
            (f"if false; then :; elif cd {c}; false; then cd /usr; else git push --no-verify origin HEAD:main; fi", plain, "deny"),
            # 넘침: 처음에 들어간 clone을 접지 않는다
            (f"true && cd {c}; {after}; git push --no-verify origin HEAD:main", plain, "deny"),
            (f"case $X in 0) cd {c};; {arms} esac; git push --no-verify origin HEAD:main", plain, "deny"),
            (f'cd "$D" .. && cd -P nosub; {after}; git push --no-verify origin HEAD:main', c, "deny"),
            # 오탐 방지: 건너뛸 수 없는 경우는 그대로
            ("cd /tmp && git push --no-verify origin HEAD:main || true", c, None),
            ("cd /tmp && ls || ls && git push --no-verify origin HEAD:main", c, None),
            ("cd /nonexist && git push --no-verify origin HEAD:main", c, None),
            ("if test -d x; then cd /usr; else cd /tmp; fi; git push --no-verify origin HEAD:main", plain, None),
            (f"{after}; git push --no-verify origin HEAD:main", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_shell_heredoc_bodies_walk_once_per_operator():
    """명령 파싱(재리뷰 P1): 셸이 읽는 heredoc 본문은 연산자가 든 명령의 cwd 후보로 한 번, 이 글에서 거친 나머지 후보(상한 안)로 한 번
    걷는다. 예전에는 거친 cwd마다 본문을 다시 걸어(실패하는 cd마다 후보가 늘고 중첩 heredoc에서 곱으로 커진다) 1KB 미만 명령이 hook
    시간 한도(180초)를 넘겼다 — Claude Code는 시간 초과를 막지 않는다(fail-open). 연산자 뒤에 cd가 많아도 연산자 자리의 cwd(이슈 DB
    clone)는 버리지 않는다."""
    import time
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")

    def cds(prefix: str, n: int) -> str:
        return "\n".join(f"cd {prefix}{i}" for i in range(n))
    body = cds("m", 60) + "\ngit status"
    nested = f"{cds('n', 8)}\nbash <<EOF\n{body}\nbash <<EOG\n{body}\nEOG\nEOF\ngit push --no-verify origin HEAD:main"
    first = f"git push --no-verify origin HEAD:main\n{cds('n', 8)}\nbash <<EOF\n{body}\nbash <<EOG\n{body}\nEOG\nEOF"
    level3 = (f"{cds('n', 8)}\nbash <<EOF\n{cds('m', 60)}\nbash <<EOG\n{cds('q', 60)}\nbash <<EOH\n{cds('p', 60)}\ngit status\n"
              "EOH\nEOG\nEOF\ngit push --no-verify origin HEAD:main")
    for cmd in (nested, first, level3):
        start = time.monotonic()
        assert decision(bash(ws, cmd, c)) == "deny", cmd[:60]
        assert time.monotonic() - start < 5, (cmd[:60], time.monotonic() - start)     # 예전: 수백 초
    after = "; ".join(f"cd {d}" for d in ("/usr", "/tmp", "/var", "/etc", "/opt", "/srv", "/home", "/usr/bin"))
    rows = [(f"cd {c}; bash <<EOF\ngit push --no-verify origin HEAD:main\nEOF\n{after}", plain, "deny"),   # 연산자 뒤 cd 8개
            (f"cd {c} && bash <<EOF\ncd sub 2>/dev/null\ngit push --no-verify origin HEAD:main\nEOF", plain, "deny"),
            (f"(cd {c}; bash <<EOF\ngit push --no-verify origin HEAD:main\nEOF\n)", plain, "deny"),
            (f"bash <<A; cd {c}; bash <<B\ngit status\nA\ngit push --no-verify origin HEAD:main\nB", plain, "deny"),
            (f"cd {c}; bash <<EOF\nbash <<EOG\ngit push --no-verify origin HEAD:main\nEOG\nEOF", plain, "deny"),
            (f"cd {c}; cat <<EOF | sh\necho x > notes.txt\nEOF", plain, "deny"),
            (f"cd {c}; bash <<EOF\ngh pr merge 3\nEOF", plain, "ask"),
            ("echo ; bash <<EOF\ngit push --no-verify origin HEAD:main\nEOF", c, "deny"),   # 표시 글자가 이미 든 글
            ("cd /tmp && bash <<EOF\ngit push --no-verify origin HEAD:main\nEOF", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_heredoc_detection_ignores_quotes_comments_herestrings_and_unterminated():
    """명령 파싱(H-A1 r6, `_heredoc_scan`): heredoc 연산자는 인용·주석·산술 밖의 `<<`·`<<-`만이다(`<<<` here-string 아님). 끝
    표시 줄을 못 찾으면 본문으로 빼지 않는다(뒤 줄을 지우지 않는다). 끝 표시는 줄 전체가 낱말과 같을 때만이다(`<<-`는 앞 탭만
    뗀다). 그래서 `rg "<<EOF"`·주석 속 `<<EOF`·`<<< word`·`$((1<<X))` 뒤 줄의 병합·Approve·main push가 판정된다. 진짜 heredoc
    본문은 여전히 명령으로 읽지 않는다(셸이 읽는 본문만 명령)."""
    ws = shared()
    c = ws.clone
    wt = ws.work / "wt-heredoc"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    merge = f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge"
    rows = [
        ('rg -n "<<EOF" scripts/ | head -3\ngh pr merge 3 --squash', wt, "ask"),
        ("# 확인: heredoc(<<EOF) 본문 포함\ngh pr review 3 --approve", wt, "deny"),
        ("read -r a <<< word\ngh pr merge 3 --squash", c, "ask"),
        ("git log --oneline -3   # <<HEAD\ngit push --no-verify origin HEAD:main", c, "deny"),
        ("echo $((1<<X))\ngh pr merge 3 --squash", c, "ask"),
        ("((n <<= 1))\ngh pr merge 3", c, "ask"),
        ("echo '<<EOF'\ngh pr merge 3 --squash", c, "ask"),
        ("echo x # <<EOF\ngh pr merge 3 --auto --squash", c, "deny"),
        (f'true\nrg -n "<<EOF" scripts/\ntrue\n{merge}', c, "ask"),
        ("cat <<EOF\ngh pr merge 3 --squash", c, "ask"),                      # 끝 표시 없음
        ('echo "\n<<EOF\n"; gh pr merge 3\nEOF', c, "ask"),                  # 여러 줄 인용 안 `<<EOF`
        ("cat > f <<EOF\n  EOF\ncd /tmp\nEOF\ngh pr merge 3", c, "deny"),     # 공백 붙은 `  EOF`는 끝 표시가 아니다
        ("cat <<'EOF' | bash\ngh pr merge 3\nEOF", c, "ask"),                # 셸이 읽는 본문은 명령이다
        # 진짜 heredoc 본문은 명령이 아니다(오탐 없음)
        ("cat >/dev/null <<'EOF'\ngh pr merge 3\nEOF", c, None),
        ("cat >/dev/null <<-EOF\n\tgh pr merge 3\n\tEOF", c, None),
        ("cat >/dev/null <<\\EOF\ngh pr merge 3\nEOF", c, None),
        ("cat >/dev/null <<'END-X'\ngh pr merge 3\nEND-X", c, None),
        ("cat <<A >/dev/null <<B\ngh pr merge 3\nA\ngh pr merge 4\nB", c, None),
        ("X=\"$(cat <<'EOF'\ngh pr merge 3\nEOF\n)\"; echo \"$X\"", c, None),
        ("cat <<EOF\nhello\nEOF\ngh pr merge 3 --squash", c, "ask")]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_dirstack_tilde_cd_targets_follow_bash():
    """명령 파싱(H 계획 A2 뒤 — 규칙 11에 남았던 P1): cd·pushd 대상의 디렉토리 스택 tilde(`~-` = OLDPWD, `~+` = PWD, `~N`·`~+N` =
    dirs 왼쪽에서 N번째(0 = cwd), `~-N` = 오른쪽에서 N번째, 뒤 `/…` 포함)는 이 글이 따라간 상태로 푼다(`cd -`·`pushd +N`·`popd`와
    같은 상태). 예전에는 글자 경로(`/tmp/~-`)로 보아 `cd /tmp && cd ~- && git push --no-verify origin main`(이슈 DB clone에서)이 규칙 5를 피했다.
    풀 수 없으면(새 셸의 OLDPWD는 없다·스택이 짧다) bash는 글자 그대로 두어 cd가 실패하고 cwd는 그대로다 — 이전 후보를 버리지 않는다.
    `~-N`은 아래에서 세므로 `popd -N`처럼 스택 칸 어디든·모르는 디렉토리다. 명령 글에서 OLDPWD·PWD를 바꿀 수 있으면 `cd -`·`~-`·`~+`는
    모르는 디렉토리도 후보다. 따옴표 안·`\\`로 막은 tilde(`"~-"`·`\\~-`·`~"-"`)는 bash처럼 글자 그대로다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-tilde"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    push = "git push --no-verify origin HEAD:main"
    rows = [
        ("cd /tmp && cd ~- && git push --no-verify origin main", c, "deny"), (f"cd /tmp; cd ~-; {push}", c, "deny"),
        (f"cd /tmp; cd ~-; {push}", wt, "deny"), (f"cd {c}; cd /tmp; cd ~-; {push}", plain, "deny"),
        (f"pushd /tmp; cd ~1; {push}", c, "deny"), (f"pushd /tmp; cd ~+1; {push}", c, "deny"),
        (f"pushd /tmp; cd ~-0; {push}", c, "deny"), (f"pushd /tmp >/dev/null; pushd ~1; {push}", c, "deny"),
        (f"pushd {c}; pushd /tmp; cd ~1; {push}", plain, "deny"), (f"pushd -n {c}; cd ~1; {push}", plain, "deny"),
        (f"pushd /tmp; pushd -n {plain}; cd ~2; {push}", c, "deny"), (f"cd {c}/data; cd /tmp; cd ~-/..; {push}", plain, "deny"),
        (f"cd /tmp; cd ~-/; {push}", c, "deny"), (f"cd {c}; cd ~+; {push}", plain, "deny"),
        ("cd /tmp; cd ~-; git commit --no-verify -m x", c, "deny"), ("cd /tmp; cd ~-; git checkout -b x", c, "deny"),
        ("cd /tmp; cd ~-; git commit --no-verify -m x", wt, "deny"),
        # 풀 수 없다(새 셸 — OLDPWD 없음·빈 스택): 글자 그대로라 cd가 실패한다 — cwd 그대로
        (f"cd ~-; {push}", c, "deny"), (f"cd ~1; {push}", c, "deny"), (f"cd ~-1 2>/dev/null; {push}", c, "deny"),
        (f"pushd ~1; {push}", c, "deny"),
        (f"cd {c}; cd /tmp; cd ~-; cd ~-; {push}", plain, None), (f"cd /tmp; cd ~+; cd ~-; {push}", c, None),
        (f"pushd {c}; pushd /tmp; cd ~2; {push}", plain, None), (f"cd /tmp; cd ~+; {push}", c, None),
        (f'cd /tmp; cd "~-"; {push}', c, None), (f"cd /tmp; cd \\~-; {push}", c, None),
        (f'cd /tmp; cd ~"-"; {push}', c, None), (f"cd {c}; cd ~-; {push}", plain, None),
        (f"cd /tmp; cd ~-; cd {plain}; {push}", c, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_redirections_and_heredocs_glued_to_command_word():
    """명령 파싱(H 계획 A2 뒤 — 규칙 11에 남았던 P1): 따옴표 밖 `<`도 `>`처럼 연산자 글자다. bash는 `git</dev/null push`를 낱말
    `git`·리디렉션 `</dev/null`·낱말 `push`로 읽는데 예전에는 `git</dev/null`을 한 낱말로 보아 git을 몰랐다(`gh<x pr merge 3`도).
    같은 까닭으로 공백 없는 `bash<<EOF`(`sh<<'EOF'`·`bash<<-EOF`·`env bash<<EOF`)도 셸이 읽는 heredoc 본문으로 걷고, `-c` 없는
    셸의 here-string(`bash<<<"…"`·`bash <<< '…'`)도 스크립트로 걷는다. 리디렉션 앞 숫자는 공백 없이 붙었을 때만 fd다(`2>`·`0<` —
    `timeout 5 >/dev/null git …`의 `5`는 timeout 인자다). 따옴표 안 `<`, `<( )` 프로세스 치환, `$(( ))`·`[[ ]]` 비교, 셸이 아닌
    명령의 heredoc·here-string(`cat<<EOF`)은 그대로 글이다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    push = "git push --no-verify origin HEAD:main"
    rows = [
        ("git</dev/null push --no-verify origin main", c, "deny"), ("git>/dev/null push --no-verify origin main", c, "deny"),
        ("git<>/dev/null push --no-verify origin main", c, "deny"), ("git>|/dev/null push --no-verify origin main", c, "deny"),
        ("git>&2 push --no-verify origin main", c, "deny"), ("git&>/dev/null push --no-verify origin main", c, "deny"),
        ("git 2</dev/null push --no-verify origin main", c, "deny"), ("git<<<x push --no-verify origin main", c, "deny"),
        ("git push --no-verify origin main</dev/null", c, "deny"), ("gh<x pr merge 3", c, "ask"), ("<x gh pr merge 3", c, "ask"),
        ("gh</dev/null pr review 3 --approve", c, "deny"), ("gh pr merge 3</dev/null", c, "ask"),
        ("timeout 5 </dev/null git push --no-verify origin main", c, "deny"), ("timeout 5 >/dev/null git push --no-verify origin main", c, "deny"),
        (f"cd {c}</dev/null; {push}", plain, "deny"), ("git</dev/null checkout -b x", c, "deny"),
        # 공백 없는 heredoc·셸의 here-string
        ("bash<<EOF\ngh pr merge 12\nEOF", c, "ask"), ("sh<<'EOF'\ngh pr merge 12\nEOF", c, "ask"),
        ("bash<<-EOF\n\tgh pr merge 12\n\tEOF", c, "ask"), ("env bash<<EOF\ngh pr merge 12\nEOF", c, "ask"),
        ("X=1 bash<<EOF\ngit push --no-verify origin main\nEOF", c, "deny"), (f"cd {c}; bash<<EOF\n{push}\nEOF", plain, "deny"),
        ('bash<<<"gh pr merge 3"', c, "ask"), ("bash <<< 'gh pr merge 3'", c, "ask"), ("sh<<<$'gh pr merge 3'", c, "ask"),
        (f'bash<<<"cd {c}; {push}"', plain, "deny"), ("bash -s<<<'gh pr review 3 --approve'", c, "deny"),
        # 오탐 방지: 따옴표 안 `<`, 입력 리디렉션은 쓰기가 아니다, 프로세스 치환·산술·비교, 셸이 아닌 명령의 heredoc·here-string
        ('grep -n "gh<x pr merge 3" notes.md', c, None), ("echo 'a<b>c'", c, None),
        (f"echo a<{c}/README.md", ws.base, None), (f"sort 0<{c}/README.md >/tmp/o", ws.base, None),
        ("diff <(git log -1) <(git log -2)", c, None), ("echo $((1<2)) $((1<<3))", c, None),
        ("[[ a < b ]] && echo ok", c, None), ("cat <<EOF\ngh pr merge 3\nEOF", c, None),
        ("cat<<EOF\ngh pr merge 3\nEOF", c, None), ("cat >/dev/null<<'EOF'\ngh pr merge 3\nEOF", c, None),
        ('cat <<<"gh pr merge 3"', c, None), ("grep -c x<<<'gh pr merge 3'", c, None),
        ("bash -c 'echo hi'<<<'gh pr merge 3'", c, None), ("git 2>/dev/null log -1 && echo 2 >/dev/null", c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_fd_words_heredoc_dash_rw_redirection_and_tilde_tails_follow_bash():
    """명령 파싱(H 계획 A2 뒤 `<`·tilde 수정의 재리뷰 P0·P1): `<`를 연산자 글자로 나눈 뒤 bash 어휘 분석과 어긋나 약해졌던 자리.
    `{이름}<`·`{이름}>`(bash 4.1+ fd 변수)도 숫자처럼 연산자에 붙은 fd다 — 예전에는 `{fd}`가 git·gh 낱말로 남아 하위 명령을 가렸다.
    `>&`·`<&` 바로 뒤 숫자는 복제 대상이지 뒤 `<`의 fd가 아니다(`2>&1</dev/null`). `[n]<>f`는 읽고 쓰기로 열어 쓰기 대상이다(규칙 8).
    `<<-`는 한 연산자이고 셸의 `-c`는 리디렉션을 뺀 argv에서 찾는다(`bash <<-cmds`의 끝 표시가 `-c`로 보여 본문을 걷지 않았다).
    tilde 뒤 `//`는 bash처럼 그 디렉토리 아래다(`~-//` = `$OLDPWD//`), `~N`의 N은 ASCII 숫자만이다(`~\u0661`는 글자). 줄 이음은 먼저
    지우고 fd·tilde를 가른다(`2\\⏎>`·`~\\⏎-`)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-fdword"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    push = "git push --no-verify origin HEAD:main"
    rows = [
        # `{이름}` fd
        ("git {fd}</dev/null push --no-verify origin main", c, "deny"), ("git {fd}<<<x push --no-verify origin main", c, "deny"),
        ("git {fd}>/dev/null push --no-verify origin main", c, "deny"), ("gh {fd}</dev/null pr merge 3", c, "ask"),
        ("gh {x}<x pr review 3 --approve", c, "deny"), ("gh pr {fd}<1 merge 3", c, "ask"),
        (f"git -C {c} {{fd}}</dev/null push --no-verify origin main", plain, "deny"),
        (f"cd {{fd}}</dev/null {c} && git push --no-verify origin main", plain, "deny"),
        (f"gh -R {DB_SLUG} {{fd}}</dev/null pr merge 3", plain, "ask"), ("echo x {fd}>README.md", c, "deny"),
        # `>&`·`<&` 뒤 숫자는 복제 대상
        (f"git -C {c} 2>&1</dev/null push --no-verify origin main", plain, "deny"),
        (f"git -C {c} 2>& 1</dev/null push --no-verify origin main", plain, "deny"),
        (f"gh -R {DB_SLUG} 2>&1</dev/null pr merge 3", plain, "ask"),
        (f"cd 2>&1</dev/null {c} && git push --no-verify origin main", plain, "deny"),
        (f"git -C {c} 0<&3</dev/null push --no-verify origin main", plain, "deny"),
        # `<>`는 쓰기 대상
        ("echo x 1<>README.md", c, "deny"), ("echo x 1<> README.md", c, "deny"), ("echo x 3<>README.md >&3", c, "deny"),
        ("echo x <>README.md", c, "deny"), (f"echo x 1<>{c}/README.md", plain, "deny"),
        (f"printf x {{fd}}<>{c}/README.md", plain, "deny"),
        # `<<-` 한 연산자, 리디렉션 대상은 `-c`가 아니다
        ("bash <<-cmds\ngh pr merge 3\ncmds", c, "ask"), ("bash <<-cmd\ngit push --no-verify origin main\ncmd", c, "deny"),
        ("env bash <<-code\ngh pr merge 3\ncode", c, "ask"), ("bash -s <<-cmd\ngh pr merge 3\ncmd", c, "ask"),
        ("bash<<-cmd\n\tgh pr merge 3\n\tcmd", c, "ask"), ("bash 0<<-cmd\ngh pr merge 3\ncmd", c, "ask"),
        ("bash << -c\ngh pr merge 3\n-c", c, "ask"), ("bash -c </dev/null 'gh pr merge 3'", c, "ask"),
        # tilde 뒤 `//`, ASCII 숫자만
        (f"cd {c}; cd /tmp; cd ~-//; {push}", plain, "deny"), (f"cd {c}; cd /tmp; cd ~-//./; {push}", plain, "deny"),
        (f"cd ~+//; {push}", c, "deny"), (f"cd {c}; cd ~+//; gh pr merge 3", plain, "ask"),
        (f"pushd {c}; pushd /tmp; cd ~1//; {push}", plain, "deny"),
        (f"pushd {c}; pushd /tmp; cd ~1//data; {push}", plain, "deny"),
        (f"cd /tmp && pushd -n ~-//. && popd && {push}", c, "deny"),
        (f"pushd {c}; cd ~\u0661; {push}", plain, "deny"), (f"pushd {c}; cd ~+\u0661; {push}", plain, "deny"),
        (f"cd {c}; cd ~\uff10/..; {push}", plain, "deny"),
        # 줄 이음은 먼저 지운다
        ("git 2\\\n>/dev/null push --no-verify origin main", c, "deny"), ("git {fd}\\\n</dev/null push --no-verify origin main", c, "deny"),
        (f"cd /tmp; cd ~\\\n-; {push}", c, "deny"), (f"git -C {c} 2>&\\\n1</dev/null push --no-verify origin main", plain, "deny"),
        # 오탐 방지
        ("git log -1 2>&1</dev/null", c, None), ("git '{x}'</dev/null push --no-verify origin main", c, None),
        ("git a\\\n2>/dev/null push --no-verify origin main", c, None), ("git 2\\\\\n>/dev/null push --no-verify origin main", c, None),
        (f"cat 0<{c}/README.md >/dev/null", plain, None), (f"cd /tmp; cd ~-//; {push}", plain, None),
        ("git commit -F - <<-end\nmsg\nend", wt, None), ("git commit -F - <<- end\nmsg\nend", wt, None),
        ("bash -c 'echo hi' <<-cmd\ngh pr merge 3\ncmd", c, None), ("cat <<-cmd\ngh pr merge 3\ncmd", c, None),
        ("pushd /tmp; pushd /usr; pushd -n ~2; popd -n; popd; git push --no-verify origin main", c, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))

def test_guard_close_fd_redirection_glued_to_word():
    r"""명령 파싱(11/04 P2): `>&-`·`<&-`(앞 fd·`{이름}` 포함)는 fd를 닫는 연산자이고, 바로 뒤에 붙은(또는 공백 뒤) 낱말은 복제
    대상이 아니라 별도 인자다(bash). 예전에는 `-낱말`을 복제 대상으로 떼어 버려 clone에서 `git 0<&-push --no-verify origin main`이 None(bash는
    git push를 돈다)이었다. 닫기 뒤 `N>f`는 새 fd 리디렉션이다(`>&-2>o`). 따옴표 친 `-`는 닫기가 아니라 파일이다(`>&"-x"`)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        ("git 0<&-push --no-verify origin main", c, "deny"), ("git 2>&-push --no-verify origin main", c, "deny"),
        ("git <&-push --no-verify origin main", c, "deny"), ("git 3>&-push --no-verify origin main", c, "deny"),
        ("git {fd}>&-push --no-verify origin main", c, "deny"), ("git 0<& -push --no-verify origin main", c, "deny"),
        ("git 2>&--C . push --no-verify origin main", c, "deny"), (">&-git push --no-verify origin main", c, "deny"),
        ("gh 2>&-pr merge 3", c, "ask"), ("gh 0<&-pr merge 3", c, "ask"), (">&-gh pr merge 3", c, "ask"),
        (f"git -C {c} 0<&-push --no-verify origin main", plain, "deny"), (f"gh -R {DB_SLUG} 2>&-pr merge 3", plain, "ask"),
        ("git 2>&-\\\npush --no-verify origin main", c, "deny"), ("git 2>&\\\n-push --no-verify origin main", c, "deny"),
        # 오탐 방지: 닫기만(뒤 낱말 없음)·상태 명령·복제·따옴표 친 `-`·닫기 + 새 리디렉션
        ("git status >&-", c, None), ("git status 2>&- </dev/null", c, None), ("echo x >&-", c, None),
        ("echo x >&- ; git status", c, None), ("git log 2>&1 >&-", c, None),
        ('git >&"-x" push --no-verify origin main', plain, None), ("git log 0<&-2>o", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_nested_shell_inherits_oldpwd():
    r"""명령 파싱(11/04 P2): bash는 `$OLDPWD`·`$PWD`를 자식 셸에 내보낸다. 중첩 셸(`bash -c '…'`·here-string·heredoc·파이프 글)의
    `cd -`·`~-`는 부모가 따라간 이전 디렉토리(와 정적 OLDPWD 대입·앞 `env OLDPWD=`)를 쓴다. 예전에는 중첩을 old=None으로 시작해
    `cd <C>; cd /tmp; bash -c 'cd ~-; git push'`가 None이었다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        (f"cd {c}; cd /tmp; bash -c 'cd ~-; git push --no-verify origin main'", plain, "deny"),
        (f"cd {c}; cd /tmp; bash -c 'cd -; git push --no-verify origin main'", plain, "deny"),
        (f"cd {c}; cd /tmp; sh -c 'cd -; git push --no-verify origin main'", plain, "deny"),
        (f"cd {c}; cd /tmp; bash <<<'cd ~-; git push --no-verify origin main'", plain, "deny"),
        (f"cd {c}; cd /tmp; bash<<<'cd -; git push --no-verify origin main'", plain, "deny"),
        (f"cd {c}; cd /tmp; bash -c 'cd ~-; gh pr merge 3'", plain, "ask"),
        (f"cd {c}; cd /tmp; bash -c 'bash -c \"cd ~-; git push --no-verify origin main\"'", plain, "deny"),
        (f"env OLDPWD={c} bash -c 'cd -; git push --no-verify origin main'", plain, "deny"),
        (f"cd {c}; cd /tmp; bash <<EOF\ncd ~-\ngit push --no-verify origin main\nEOF", plain, "deny"),
        # 오탐 방지: 부모의 이전 디렉토리가 clone이 아니면 중첩 cd ~-도 clone이 아니다
        ("cd /usr; cd /tmp; bash -c 'cd ~-; git push --no-verify origin main'", plain, None),
        (f"cd {c}; cd /tmp; bash -c 'cd ~-; ls'", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_wrapper_option_values_skip_redirections():
    r"""명령 파싱(11/04 P2): 앞 래퍼의 값 받는 옵션(`env -C`·`sudo -D`·`timeout -s/-k`·`nice -n`·`ionice -c`·`stdbuf -o`·`exec -a`·
    `xargs -n` 등)이 값을 다음 낱말로 받을 때, 사이 리디렉션(대상째)을 bash처럼 먼저 뗀다. 예전에는 `env -C</dev/null <C> git push`가
    리디렉션을 값으로 먹어 작업 디렉토리를 못 바꿔 None이었다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        (f"env -C</dev/null {c} git push --no-verify origin main", plain, "deny"),
        (f"env -C </dev/null {c} git push --no-verify origin main", plain, "deny"),
        (f"sudo -D</dev/null {c} git push --no-verify origin main", plain, "deny"),
        (f"sudo -D </dev/null {c} git push --no-verify origin main", plain, "deny"),
        (f"env --chdir </dev/null {c} git push --no-verify origin main", plain, "deny"),
        (f"env -C 2>/dev/null {c} git push --no-verify origin main", plain, "deny"),
        (f"env -C</dev/null {c} gh pr merge 3", plain, "ask"),
        (f"env -u</dev/null X git -C {c} push --no-verify origin main", plain, "deny"),
        (f"timeout -s </dev/null KILL 5 git -C {c} push --no-verify origin main", plain, "deny"),
        (f"nice -n </dev/null 5 git -C {c} push --no-verify origin main", plain, "deny"),
        (f"stdbuf -o </dev/null L git -C {c} push --no-verify origin main", plain, "deny"),
        (f"xargs -n </dev/null 1 git -C {c} push --no-verify origin main", plain, "deny"),
        # 오탐 방지: 리디렉션만 뗀다 — 값·명령은 그대로
        (f"env -C {c} git status", plain, None), (f"env -C {plain} git push --no-verify origin main", c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_static_text_fed_to_shell():
    r"""명령 파싱(11/04 P2): 파이프·stdin으로 셸에 넘겨 실행되는 정적 글을 스크립트로 걷는다 — `echo "…" | bash`·`printf … | sh`·
    `cat <<<"…" | bash`·`echo … | cat | bash`·`(echo …) | bash`·`echo … |& bash`·`source /dev/stdin <<<"…"`·`bash -s <<<"…"`.
    파이프 요소는 서브셸이라 그 글의 cd는 밖으로 새지 않는다. 동적(확장) 글·브레이스 그룹·`eval "$(cat)"`은 보지 않는다(한계)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        ('echo "gh pr merge 3" | bash', c, "ask"), ("echo gh pr merge 3 | bash", c, "ask"),
        ("printf '%s\\n' 'git push --no-verify origin main' | sh", c, "deny"),
        ('cat <<<"git push --no-verify origin main" | bash', c, "deny"), ('cat <<<"gh pr merge 3" | bash', c, "ask"),
        ('source /dev/stdin <<<"gh pr merge 3"', c, "ask"), ('. /dev/stdin<<<"gh pr merge 3"', c, "ask"),
        ('bash /dev/stdin <<<"gh pr merge 3"', c, "ask"), ('bash -s <<<"gh pr merge 3"', c, "ask"),
        ('echo "gh pr merge 3" |& bash', c, "ask"), ('echo "gh pr merge 3" | cat | bash', c, "ask"),
        ('(echo "gh pr merge 3") | bash', c, "ask"), ('echo "gh pr merge 3" | source /dev/stdin', c, "ask"),
        ("cat <<EOF | sh\ngh pr merge 3\nEOF", c, "ask"),
        (f'echo "cd {c}; git push --no-verify origin main" | bash', plain, "deny"),
        # 오탐 방지: 셸이 아닌 소비자, 정적이 아닌 글, 비-DB cwd, 서브셸 cd는 새지 않는다
        ('echo "gh pr merge $N" | bash', c, "ask"),
        ('echo "gh pr merge 3"', c, None), ("echo text | grep x", c, None),
        ('cat <<<"gh pr merge 3" | wc -l', c, None), ("printf 'echo hi\\n' | sh", c, None),
        ("echo 'ls -la' | bash", c, None), (f'echo "cd {c}" | bash; git push --no-verify origin main', plain, None),
        ('echo "git push --no-verify origin HEAD:main" | bash', plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_static_pwd_oldpwd_writes_track_value():
    r"""명령 파싱(11/04 P2): 같은 글에서 OLDPWD·PWD에 정적 절대 경로를 넣으면(`OLDPWD=<C>`·`export`·`declare -x`·`env OLDPWD=`,
    `else OLDPWD=…` 같은 예약어 뒤 포함) `cd -`·`~-`·`~+`가 그 값을 쓴다 — cd가 `$PWD`를 OLDPWD로 복사하므로 가짜 PWD도. 숨긴 이름
    (`export $'OLD\x50WD'=…`·`export "OLDPWD"=…`)도 푼다. 예전에는 모르는 디렉토리만 더해 git 규칙(모르는 후보 건너뜀)이 None이었다.
    동적·상대 값은 그대로 모르는 디렉토리(한계)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        (f"OLDPWD={c}; cd ~-; git push --no-verify origin main", plain, "deny"),
        (f"export OLDPWD={c}; cd -; git push --no-verify origin main", plain, "deny"),
        (f"declare -x OLDPWD={c}; cd -; git push --no-verify origin main", plain, "deny"),
        (f"PWD={c}; cd ~+; git push --no-verify origin main", plain, "deny"),
        (f"PWD={c}; cd /tmp; cd -; git push --no-verify origin main", plain, "deny"),
        (f"PWD={c}; cd ~0; git push --no-verify origin main", plain, "deny"),
        (r"export $'OLD\x50WD'=" + str(c) + "; cd -; git push --no-verify origin main", plain, "deny"),
        (f'export "OLDPWD"={c}; cd ~-; git push --no-verify origin main', plain, "deny"),
        (f"typeset OLDPWD={c}; cd ~-; git push --no-verify origin main", plain, "deny"),
        (f"OLDPWD={c} cd -; git push --no-verify origin main", plain, "deny"),
        (f"OLDPWD={c}; cd ~-; gh pr merge 3", plain, "ask"),
        (f"export OLDPWD={c}/data; cd ~-/..; git push --no-verify origin main", plain, "deny"),
        (f"true && OLDPWD={c}; cd ~-; git push --no-verify origin main", plain, "deny"),
        (f"if false; then :; else OLDPWD={c}; fi; cd ~-; git push --no-verify origin main", plain, "deny"),
        # 오탐 방지: 비-clone 값, 읽기 명령
        ("OLDPWD=/tmp; cd ~-; git push --no-verify origin main", plain, None),
        ("OLDPWD=/tmp; cd ~-; gh pr view 3", plain, None),
        ("OLDPWD=/tmp; cd ~-; ls", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_dirstack_tilde_outside_cd_targets():
    r"""명령 파싱(11/04 P2): cd·pushd 대상 밖의 디렉토리 스택 tilde(`git -C ~-`·`git -C ~1`·`env -C ~-`·`sudo -D ~-`·리디렉션 대상
    `> ~-/f`)도 이 글의 cd/스택 상태로 푼다(F). 예전에는 글자(`~-`)로 보아 clone에서 `cd /tmp && git -C ~- push`가 None이었다.
    셸이 풀지 않는 꼴(`"~-"`·`--opt=~-`)은 그대로 둔다. 대입꼴 값(`GIT_DIR=~-/.git`)은 bash가 풀므로 푼다(재리뷰 — 아래 테스트)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        ("cd /tmp && git -C ~- push --no-verify origin main", c, "deny"), ("cd /tmp; git -C ~- push --no-verify origin main", c, "deny"),
        ("pushd /tmp; git -C ~1 push --no-verify origin main", c, "deny"), ("git -C ~+ push --no-verify origin main", c, "deny"),
        ("cd /tmp && env -C ~- git push --no-verify origin main", c, "deny"), ("cd /tmp && sudo -D ~- git push --no-verify origin main", c, "deny"),
        ("cd /tmp && echo x > ~-/README.md", c, "deny"), ("cd /tmp && echo x >~-/README.md", c, "deny"),
        ("cd /tmp && cp /etc/hosts ~-/x", c, "deny"), ("cd /tmp && touch ~-/x", c, "deny"),
        (f"cd {c}; cd /tmp; env -C ~- gh pr merge 3", plain, "ask"),
        # 오탐 방지: 읽기 명령, OLDPWD 모름(새 셸)·따옴표 친 tilde
        ("git -C ~- status", c, None), ("cd /tmp; git -C ~- status", c, None),
        ("git -C ~- push --no-verify origin main", plain, None), ('cd /tmp; git -C "~-" push --no-verify origin main', c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_marked_tokens_records_heredoc_operator_ids():
    """명령 파싱(11/04 P2, G 회귀): `_marked_tokens`는 본문을 먼저 뺀 글에 표시를 끼워 셸이 읽는 heredoc 연산자별 cwd(`hd_at`)를
    기록한다. 예전에는 표시가 끝 표시 낱말에 끼어 `_strip_heredocs`가 본문을 못 빼 연산자 번호가 기록되지 않고(늘 대체 경로) 큰
    본문을 토큰으로 썰어 느려졌다. `cd X && bash <<EOF`·붙은 `bash<<EOF`·`bash<<-EOF`에서 연산자 번호를 찾는다."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("guard_mt", str(REPO / "plugin" / "scripts" / "guard.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    for cmd in ("cd X && bash <<EOF\ngit status\nEOF", "bash<<EOF\ngit status\nEOF",
                "bash<<-EOF\n\tgit status\n\tEOF"):
        hds = g._heredoc_scan(cmd)
        fed = [k for k, hd in enumerate(hds) if hd.found and g._feeds_shell(hd.unit, Path("/tmp"))]
        assert fed, cmd
        toks, ids = g._Walk._marked_tokens(cmd, hds, fed)
        assert sorted({i for tup in ids for i in tup}) == sorted(fed), cmd
        assert [str(t) for t in toks] == [str(t) for t in g._tokens(cmd)], cmd


def test_guard_nested_shell_oldpwd_at_operator_keeps_unknown():
    r"""명령 파싱(11/04 재리뷰 P0·P1, B): 중첩 셸의 OLDPWD 후보는 그 자리의 부모 후보다 — `-c`·here-string은 그 명령, heredoc은
    연산자가 든 명령(본문 안 `git -C ~-`도), 파이프 글은 묶음이 시작할 때(뒤 cd가 숨기지 않는다). 부모 OLDPWD를 모르면(처음 OLDPWD,
    실패할 수 있는 cd, `cd -`·`popd` 뒤) 모르는 디렉토리도 물려준다 — 예전에는 빼서 자식 `cd -; gh pr merge 3`이 None이었다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        (f"cd {c}; cd /tmp; bash <<EOF\ngit -C ~- push --no-verify origin main\nEOF", "deny"),
        (f"cd {c}; cd /tmp; cat <<EOF | bash\ngit -C ~- push --no-verify origin main\nEOF", "deny"),
        (f"cd {c}; cd /tmp; bash<<EOF\ngit -C ~- push --no-verify origin main\nEOF", "deny"),
        (f"cd {c}; cd /tmp; bash <<-EOF\n\tgit -C ~- push --no-verify origin main\n\tEOF", "deny"),
        (f"cd {c}; cd /tmp; bash <<EOF\nenv -C ~- git push --no-verify origin main\nEOF", "deny"),
        (f"cd {c}; cd /tmp; echo 'cd -; git push --no-verify origin main' | bash; cd /", "deny"),
        (f"cd {c}; cd /tmp; echo 'cd -; git push --no-verify origin main' | bash; cd -", "deny"),
        (f"cd {c}; cd /tmp; echo 'git -C ~- push --no-verify origin main' | bash; cd /", "deny"),
        (f"cd {c}; cd /tmp; printf 'cd -\\ngit push --no-verify origin main\\n' | sh; cd ~", "deny"),
        (f"cd {c}; cd /tmp; cat <<<'cd -; gh pr merge 3' | bash; cd /", "ask"),
        ("cd /nonexist; bash -c 'cd -; gh pr merge 3'", "ask"),
        ("test -d /x && cd /usr; bash -c 'cd -; gh pr merge 3'", "ask"),
        ("if false; then cd /usr; fi\nbash -c 'cd - >/dev/null; gh pr merge 3'", "ask"),
        ("cd -; cd /tmp; bash -c 'cd -; gh pr merge 3'", "ask"),
        ("popd; cd /tmp; sh -c 'cd ~-; gh pr merge 3'", "ask"),
        ('cd -; cd /tmp; R="$(cd -; gh pr merge 3)"', "ask"),
        ("cd -; cd /tmp; bash <<<'cd -; gh pr merge 3'", "ask"),
        ("bash -c 'cd -; gh pr merge 3'", "ask"),
        # 오탐 방지: 그 자리의 OLDPWD가 clone이 아니면 자식 cd -도 clone이 아니다
        ("cd /usr; cd /tmp; bash <<EOF\ngit -C ~- push --no-verify origin main\nEOF", None),
        (f"cd /usr; cd /tmp; echo 'cd -; git push --no-verify origin main' | bash; cd {c}", None),
        (f"cd {c}/data && bash -c 'cd ~-; git push --no-verify origin HEAD:main'", None),
        ("cd /tmp; bash -c 'cd -; git push --no-verify origin HEAD:main'", None)]
    for cmd, want in rows:
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_dash_children_keep_literal_dirstack_tilde():
    r"""명령 파싱(11/04 재리뷰 P0): dash(이 머신의 `sh`)는 `~-`·`~+`를 풀지 않는다(`sh -c 'cd ~-'`는 실패하고 cwd 그대로). 물려받은
    OLDPWD로 이동이 확실하다고 보면 `cd <C>/data && sh -c 'cd ~-; git push'`(push는 clone에서 돈다)가 None이었다. zsh·ksh는 이
    머신에 없어 확인하지 못해 같은 쪽(글자 그대로·OLDPWD를 모를 수 있다)으로 본다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        (f"cd {c}/data && sh -c 'cd ~-; git push --no-verify origin HEAD:main'", "deny"),
        (f"cd {c}/data && dash -c 'cd ~-; git push --no-verify origin HEAD:main'", "deny"),
        (f"cd {c}/data && sh -c 'git -C ~+ push --no-verify origin HEAD:main'", "deny"),
        (f"cd {c}/data && zsh -c 'cd ~-; git push --no-verify origin HEAD:main'", "deny"),
        (f"cd {c}/data && ksh -c 'cd -; git push --no-verify origin HEAD:main'", "deny"),
        (f"cd {c}/data && sh <<EOF\ncd ~-\ngit push --no-verify origin HEAD:main\nEOF", "deny"),
        # dash의 `cd -`는 물려받은 OLDPWD로 간다(확인함)
        (f"cd {c}/data && sh -c 'cd -; git push --no-verify origin HEAD:main'", None)]
    for cmd, want in rows:
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_fed_text_printf_source_heredoc_and_shell_options():
    r"""명령 파싱(11/04 재리뷰 P1, D): 셸에 넘기는 글 — `printf`는 bash처럼 서식을 인자마다 되풀이한 출력을 걷는다(예전에는 인자를
    공백으로 이어 `true git push …` 한 명령으로 보았다). `source`·`.`의 stdin heredoc·`/proc/self/fd/0`, 셸 값이 든 글(`bash -c`처럼
    셸 값으로 판정), 묶음 가운데의 셸(`… | bash 2>&1 | cat`), 값 받는 셸 옵션(`-o errexit`·`--rcfile x`)과 `+x`도 본다.
    `source /dev/stdin <<…`은 이 셸에서 돈다(cd가 남는다)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        ("printf '%s\\n' 'true' 'git push --no-verify origin main' | bash", c, "deny"),
        ("printf '%s;' 'true' 'git push --no-verify origin main' | bash", c, "deny"),
        ("printf '%s\\n%s\\n' true 'git push --no-verify origin main' | bash", c, "deny"),
        ("printf '%b\\n' true 'git push --no-verify origin main' | bash", c, "deny"),
        ("printf 'gh pr %s 3\\n' merge | bash", c, "ask"), ("printf 'gh pr merge %d\\n' 3 | bash", c, "ask"),
        ("printf 'gh pr merge %s\\n' 3 | bash", c, "ask"), ("echo -e 'true\\ngh pr merge 3' | bash", c, "ask"),
        ("source /dev/stdin <<EOF\ngh pr merge 3\nEOF", c, "ask"), (". /dev/stdin <<EOF\ngh pr merge 3\nEOF", c, "ask"),
        ("cat <<EOF | source /dev/stdin\ngh pr merge 3\nEOF", c, "ask"),
        ('source /proc/self/fd/0 <<<"gh pr merge 3"', c, "ask"),
        ("echo gh pr merge 3 | bash /proc/self/fd/0", c, "ask"), ("echo gh pr merge 3 | source /proc/self/fd/0", c, "ask"),
        (f"source /dev/stdin <<EOF\ncd {c}\nEOF\ngit push --no-verify origin main", plain, "deny"),
        (f"source /dev/stdin <<<'cd {c}'; git push --no-verify origin main", plain, "deny"),
        ('echo "gh pr merge $N" | bash', c, "ask"), ('cat <<<"gh pr merge $N" | bash', c, "ask"),
        ('echo "gh pr merge 3" | bash 2>&1 | cat', c, "ask"), ('echo "gh pr merge 3" | sh -s | cat', c, "ask"),
        ("echo gh pr merge 3 | bash -o errexit", c, "ask"), ("echo gh pr merge 3 | bash -O extglob", c, "ask"),
        ("echo gh pr merge 3 | bash --rcfile /dev/null", c, "ask"), ("echo gh pr merge 3 | bash +x", c, "ask"),
        ("echo gh pr merge 3 | bash +o posix", c, "ask"),
        # 오탐 방지: %q는 한 낱말, 셸이 아닌 소비자·스크립트 파일·`-c`, 파이프 요소의 cd는 새지 않는다
        ("printf '%q\\n' 'git status' | bash", c, None), ("printf 'echo %s\\n' a b | bash", c, None),
        ("echo gh pr merge 3 | bash script.sh", c, None), ("echo gh pr merge 3 | bash -c 'cat'", c, None),
        ("echo gh pr merge 3 | grep gh", c, None), (f"echo 'cd {c}' | source /dev/stdin; git push --no-verify origin main", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_oldpwd_writes_any_spelling_keep_unknown_candidate():
    r"""명령 파싱(11/04 재리뷰 P0·P1, E): OLDPWD·PWD 대입은 푼 이름으로 본다(`$'OLDP\x57D'`·`OLDPW''D`·`"OLDPW"D`·`OLDPW\D`). 대입
    빌트인 뒤 모든 `NAME=값`(`export FOO=1 OLDPWD=…`), `builtin`·`command` 앞, `eval` 안, `${OLDPWD:=/abs}`의 정적 값도 후보다.
    정적 값은 후보를 더할 뿐 모르는 디렉토리를 빼지 않는다 — 돌지 않았을 수 있는 대입(`true || export …`·서브셸·함수·파이프
    요소·`env` 자식 환경) 뒤의 `cd -`는 셸이 물려받은 OLDPWD(모르는 디렉토리)로도 간다(예전에는 None)."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    hid = r"$'OLD\x50WD'"
    rows = [
        (f"export FOO=1 OLDPWD={c}; cd -; git push --no-verify origin main", "deny"),
        (f"declare -x FOO=1 OLDPWD={c}; cd -; git push --no-verify origin main", "deny"),
        (f"builtin export OLDPWD={c}; cd -; git push --no-verify origin main", "deny"),
        (f"command export OLDPWD={c}; cd -; git push --no-verify origin main", "deny"),
        (f"eval 'OLDPWD={c}'; cd -; git push --no-verify origin main", "deny"), (f"eval OLDPWD={c}; cd ~-; git push --no-verify origin main", "deny"),
        (f"cd /usr; cd /tmp; export FOO=1 OLDPWD={c}; cd -; git push --no-verify origin main", "deny"),
        (rf"export $'OLDP\x57D'={c}; cd -; git push --no-verify origin main", "deny"),
        (rf"export $'OLD\x50\x57D'={c}; cd ~-; git push --no-verify origin main", "deny"),
        (f'export "OLDPW"D={c}; cd -; git push --no-verify origin main', "deny"),
        (rf"export OLDPW\D={c}; cd -; git push --no-verify origin main", "deny"),
        (f"export OLDPW''D={c}; cd -; git push --no-verify origin main", "deny"),
        (rf"declare -x $'OLDP\x57D'={c}; cd -; git push --no-verify origin main", "deny"),
        (f"export PW''D={c}; cd ~+; git push --no-verify origin main", "deny"),
        (f"cd /usr; cd /tmp; export OLDPW''D={c}; cd -; git push --no-verify origin main", "deny"),
        (f": ${{OLDPWD:={c}}}; cd -; git push --no-verify origin main", "deny"),
        (f"true || export {hid}=/tmp; bash -c 'cd -; gh pr merge 3'", "ask"),     # 자식 셸 글도 걷는다(gh를 찾았다)
        # 오탐 방지: 비-clone 정적 값만이면 git 규칙은 모르는 후보를 건너뛴다
        ("export FOO=1 OLDPWD=/tmp; cd -; git push --no-verify origin main", None),
        (": ${OLDPWD:=/tmp}; cd -; git push --no-verify origin main", None)]
    for cmd, want in rows:
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_dirstack_tilde_variants_and_assignment_values():
    r"""명령 파싱(11/04 재리뷰 P1, F): 한 단순 명령의 같은 tilde 접두는 같은 값이라 접두 값마다 변형 하나다 — 예전에는 낱말마다 곱해
    8개로 잘라 `cd a || cd b || cd <C>; cd /tmp; git -C ~- push … 2>~-/x`의 clone 후보를 버렸다. 대입꼴 낱말 값의 tilde
    (`GIT_DIR=~-/.git`·`env GIT_DIR=~-/.git`·`X=a:~-`)도 bash처럼 푼다. `--opt=~-`·`a=x=~-`는 bash도 풀지 않는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        (f"cd /tmp/nx-a || cd /tmp/nx-b || cd {c}; cd /tmp; git -C ~- push --no-verify origin main 2>~-/../x.log", plain, "deny"),
        ((f"cd /tmp/nx-a || cd /tmp/nx-b || cd /tmp/nx-d || cd /tmp/nx-e || cd {c}; cd /tmp; "
          "git -C ~- push --no-verify origin main 2>~-/x.log >~-/y.log"), plain, "deny"),
        (f"cd /tmp/nx-a || cd /tmp/nx-b || cd {c}; pushd /tmp; git -C ~- push --no-verify origin main 2>~1/x.log", plain, "deny"),
        (f"cd {c} && cd /tmp && GIT_DIR=~-/.git git push --no-verify origin main", plain, "deny"),
        (f"cd {c} && cd /tmp && env GIT_DIR=~-/.git git push --no-verify origin main", plain, "deny"),
        (f"cd {c} && cd /tmp && GIT_WORK_TREE=~- GIT_DIR=~-/.git git push --no-verify origin main", plain, "deny"),
        ("cd /tmp && GIT_DIR=~-/.git git push --no-verify origin main", c, "deny"),
        ("cd /tmp && env Y=1 GIT_DIR=~-/.git git push --no-verify origin main", c, "deny"),
        # bash가 풀지 않는 꼴
        ("cd /tmp && GIT_DIR=x=~-/.git git push --no-verify origin main", c, None),
        ("cd /tmp && git --git-dir=~-/.git push --no-verify origin main", c, None),
        ('cd /tmp && GIT_DIR="~-/.git" git push --no-verify origin main', c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_wrapper_quoted_option_values_are_not_redirections():
    r"""명령 파싱(11/04 재리뷰 P0, C): 래퍼 옵션 값 앞의 리디렉션을 뗄 때 따옴표 밖 연산자만 리디렉션이다. 인용한 값
    (`sudo -p '<pw>'`·`time -f '<%e>'`·`xargs -E '<<'`·`time -f \<%e`)을 리디렉션으로 떼면 뒤 `git`·`gh`가 대상으로 사라져 None이었다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [
        ("sudo -p '<pw>' gh pr review 3 --approve", c), ("/usr/bin/time -f '<%e>' git push --no-verify origin main", c),
        ('/usr/bin/time -f "<%e>" git push --no-verify origin main', c), ("/usr/bin/time --format '<%e>' git push --no-verify origin main", c),
        ("/usr/bin/time --format '<%e>' gh pr review 3 --approve", c), ("xargs -a '<f' git push --no-verify origin main", c),
        ("xargs -E '<<' git push --no-verify origin main", c), ("timeout -s '<x' 5 git push --no-verify origin main", c),
        ("/usr/bin/time -f \\<%e git push --no-verify origin main", c), (f"/usr/bin/time -f '<%e>' git -C {c} push --no-verify origin main", plain),
        (f"sudo -p '<pw>' gh -R {DB_SLUG} pr review 3 --approve", plain), (f"env -C</dev/null {c} git push --no-verify origin main", plain)]
    for cmd, cwd in rows:
        assert decision(bash(ws, cmd, cwd)) == "deny", (cmd, cwd)


def test_guard_fed_pipe_text_walked_once_at_pipeline_start():
    r"""명령 파싱(11/04 재리뷰 P1 성능, D): 파이프로 셸에 넘긴 글은 그 묶음이 시작할 때의 cwd 후보로 한 번만 걷는다 — 예전에는 그
    글에서 거친 cwd마다 다시 걸어 상대 cd 1000개 뒤 파이프 500개가 hook 시간 한도(180초)를 넘겨 판정 없이 통과했다."""
    import time
    ws = shared()
    c = ws.clone
    cmd = ("\n".join(f"cd r{i}" for i in range(200)) + "\n" + "\n".join(f"echo 'cd s{i}; git status' | bash" for i in range(100))
           + "\necho '" + "; ".join(f"cd t{i}" for i in range(300)) + "' | bash\ngit push --no-verify origin HEAD:main")
    t0 = time.time()
    assert decision(bash(ws, cmd, c)) == "deny"
    assert time.time() - t0 < 30


def test_guard_gh_api_shell_resolved_endpoint_may_be_graphql():
    """규칙 11(H-A1 r6·4-c): 셸이 푸는 엔드포인트(`"$GHE_API/graphql"`·`$X/graphql`·`"${X}/graphql"`)는 실행 때 GraphQL URL일 수
    있다(gh는 `://`가 든 경로를 그대로 쓰고 필드를 JSON 본문으로 보낸다). Approve·기각 mutation은 대상과 무관하게 거부, 병합·자동
    병합은 ask(병합 계열), 자동 병합 켜기 mutation은 거부(원칙 12 — db_pr merge만). 끝 칸이 `graphql`이면 읽지 못한 본문은 ask다. 읽기 query는 그대로, 다른 REST 쓰기는 ask다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    merge = "mutation { mergePullRequest(input:{pullRequestId:\"PR_x\"}) { clientMutationId } }"
    approve = "mutation { addPullRequestReview(input:{pullRequestId:\"PR_x\", event: APPROVE}) { clientMutationId } }"
    auto = "mutation { enablePullRequestAutoMerge(input:{pullRequestId:\"PR_x\"}) { clientMutationId } }"
    dismiss = "mutation { dismissPullRequestReview(input:{pullReviewId:\"R_x\", message:\"m\"}) { clientMutationId } }"
    rows = [(f"gh api \"$GHE_API/graphql\" -f query='{merge}'", plain, "ask", "머지"),
            (f"gh api \"$GHE_API/graphql\" -f query='{approve}'", plain, "deny", "Approve"),
            (f"gh api \"$GHE_API/graphql\" -f query='{auto}'", c, "deny", "자동 병합"),    # 자동 병합 켜기(원칙 12)
            (f"gh api \"$GHE_API/graphql\" -f query='{dismiss}'", plain, "deny", "기각"),
            (f"gh api $GHE_API/graphql -f query='{merge}'", plain, "ask", "머지"),
            (f"gh api \"${{GHE_API}}/graphql\" -f query='{merge}'", plain, "ask", "머지"),
            (f"gh api \"$BASE/api/%67raphql\" -f query='{merge}'", plain, "ask", "머지"),
            (f"Q='{merge}'; gh api \"$GHE_API/graphql\" -f query=\"$Q\"", plain, "ask", "머지"),
            (f"gh api \"$EP\" -f query='{approve}'", plain, "deny", "Approve"),
            ("gh api \"$GHE_API/graphql\" -f query=\"$Q\"", plain, "ask", None),
            ("gh api \"$GHE_API/graphql\" -f query='query { viewer { login } }'", plain, None, None),
            ("gh api \"$BASE/repos/other/x/issues\" -f title=t", plain, "ask", None)]     # 대상 레포를 보지 않는다(4-c)
    for cmd, cwd, want, why in rows:
        out = bash(ws, cmd, cwd)
        assert decision(out) == want, (cmd, cwd)
        assert why is None or why in out["permissionDecisionReason"], cmd


def test_guard_scp_remote_enables_rule11_and_warns_unparsable():
    """규칙 11(H-A1 r6·4-c): `issue_db.remote`가 user 없는 git SCP 꼴(`ghe-ssh:o/r.git` — ~/.ssh/config의 별칭)·숫자뿐인 owner여도
    owner/repo로 풀려(`userconfig.repo_slug`) 규칙 11이 켜진다(경고 없음 — Approve는 거부, 병합은 ask). owner/repo로 못 푸는 원격이면
    guard가 경고하지만(doctor `config` 행은 fail) 규칙 11은 원격 값만 보고 그대로 켠다(4-c — 꺼지면 Approve 거부도 꺼진다)."""
    ws = Workspace(build=False)
    ws.json("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA_TOOLS[0],
                          "--search-issues", JIRA_TOOLS[1], "--get-comments", JIRA_TOOLS[2]])

    def set_remote(old: str, value: str) -> None:
        for p in ws.home.rglob("*.yaml"):
            text = p.read_text(encoding="utf-8")
            if old in text:
                p.write_text(text.replace(old, value), encoding="utf-8")
    plain = tmp("tt-gh-plain-")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(plain)}
    current = f"https://ghe.mock.invalid/{DB_SLUG}.git"
    for remote in (f"ghe-ssh:{DB_SLUG}.git", "git@ghe.mock.invalid:1234/telephony-issue-db.git",
                   "ghe-ssh:20231234/telephony-issue-db.git"):
        set_remote(current, remote)
        current = remote
        for cmd, want in (("gh pr review 3 --approve", "deny"), ("gh pr merge 3", "ask"), ("gh pr comment 3 -b x", "ask")):
            assert decision(bash(ws, cmd, plain)) == want, (remote, cmd)
        out = guard(ws, "mcp__github__pull_request_review_write", {"owner": "o", "repo": "r", "event": "APPROVE"}, plain)
        assert decision(out) == "deny", remote
        proc = run("guard.py", [], root=ws.root, cwd=plain, env=ws.env(), stdin=json.dumps(event))
        assert proc.returncode == 0 and "규칙 11" not in proc.stderr, (remote, proc.stderr)
    # 못 푸는 원격: 경고(stderr)하고 규칙 11은 그대로
    set_remote(current, "telephony-issue-db")
    proc = run("guard.py", [], root=ws.root, cwd=plain, env=ws.env(), stdin=json.dumps(event))
    assert proc.returncode == 0 and "issue_db.remote(telephony-issue-db)" in proc.stderr and "규칙 11" in proc.stderr, proc.stderr
    for cmd, want in (("gh pr review 3 --approve", "deny"), ("gh pr merge 3", "ask"), ("gh pr comment 3 -b x", "ask")):
        assert decision(bash(ws, cmd, plain)) == want, ("unparsable", cmd)
    out = guard(ws, "mcp__github__pull_request_review_write", {"owner": "o", "repo": "r", "event": "APPROVE"}, plain)
    assert decision(out) == "deny"


def test_guard_mcp_strong_words_before_write_gate():
    """규칙 11 MCP(H-A1 r5·4-c): 병합·Approve·기각 낱말은 쓰기형 판정(`mcptools.is_write`)과 따로, 먼저 본다 — `pr_approve`·
    `automerge_pr`·`squash_and_merge`·입력 `event` APPROVE. 동사가 읽기 동사(`get_merge_status`)면 보지 않는다. Approve·기각은
    대상 레포와 무관하게 거부, 병합·자동 병합은 ask."""
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db", "number": 3}
    rows = [("mcp__ghe__pr_approve", db, "deny", "Approve하지 않는다"),
            ("mcp__ghe__pull_request_approve", db, "deny", "Approve하지 않는다"),
            ("mcp__ghe__approvePullRequest", db, "deny", "Approve하지 않는다"),
            ("mcp__ghe__pr_review", {**db, "event": "APPROVE"}, "deny", "Approve하지 않는다"),
            ("mcp__ghe__automerge_pr", db, "deny", "자동 병합"), ("mcp__ghe__squash_and_merge", db, "ask", "머지"),
            ("mcp__ghe__pr_dismiss_review", db, "deny", "기각"),
            ("mcp__ghe__disable_auto_merge", db, "ask", None), ("mcp__ghe__request_approval", db, "ask", None),
            ("mcp__ghe__get_merge_status", db, None, None), ("mcp__ghe__list_approvals", db, None, None),
            ("mcp__github__list_pull_requests", {**db, "state": "merged"}, None, None),
            ("mcp__ghe__pr_approve", {"owner": "other", "repo": "x"}, "deny", "Approve하지 않는다")]
    for tool, tool_input, want, why in rows:
        out = guard(ws, tool, tool_input, ws.base)
        assert decision(out) == want, tool
        assert why is None or why in out["permissionDecisionReason"], tool


def test_guard_without_pyyaml_asks_file_writes():
    ws = shared()
    env = _no_yaml_env(ws)
    for cmd, want in ((f'echo x > "{ws.clone}/README.md"', "ask"), ("echo hi 2>/dev/null", None)):
        event = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, cwd=ws.base, env=env, stdin=json.dumps(event))
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert proc.returncode == 0 and decision(out) == want, cmd


# -- Claude hook: GitHub 트래커(트래커 범용화 묶음 3, 설계 §4-3·§6-2) ---------------------------------------

GH_READ, GH_SEARCH = "mcp__mock-github-issues__issue_read", "mcp__mock-github-issues__search_issues"
GH_COMMENT = "mcp__mock-github-issues__add_issue_comment"
GH_KEY = "mock-org.mock-issues-12"
GH_ARGS = {"owner": "mock-org", "repo": "mock-issues", "issue_number": 12}
_GH: Workspace | None = None


def gh_shared() -> Workspace:
    """site-defaults 트래커가 github(`runner.github_root`)이고 사용자 clone이 github 변형 DB인 작업공간."""
    global _GH
    if _GH is None:
        from runner import github_root, variant_db
        _GH = Workspace(src=variant_db("issue-db-github"), root=github_root())
    return _GH


def _gh_approve(ws: Workspace, key: str, body: str, **over) -> None:
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import issuepost
    at = issuepost.now()
    record = {"schema": 1, "key": key, "tool": GH_COMMENT, "key_arg": "owner,repo,issue_number", "kind": "github",
              "body_sha256": issuepost.body_sha256(body), "format": "markdown", "request_hash": "0" * 16,
              "approved_at": issuepost.iso(at), "expires_at": issuepost.iso(issuepost.expires(at)), "used_at": None, **over}
    job = ws.job_dir(key)
    job.mkdir(parents=True, exist_ok=True)
    (job / "post.approved.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (job / "post.md").write_text(issuepost.normalize_body(body) + "\n", encoding="utf-8")
    (job / "post.result.json").unlink(missing_ok=True)


def test_guard_github_tracker_rule2():
    """github 트래커 서버: read_tools(`issue_read`·`search_issues`)만 통과, 나머지 쓰기는 deny — 이슈 DB 레포 대상
    `create_pull_request`도 규칙 11(ask)보다 규칙 2가 먼저다(설계 §4-3 S30). 설정 밖 Jira·Atlassian 서버 쓰기도 그대로 deny."""
    ws = gh_shared()
    for tool, ti in ((GH_READ, {"method": "get", **GH_ARGS}), (GH_READ, {"method": "get_comments", **GH_ARGS}),
                     (GH_SEARCH, {"query": "데이터"})):
        assert decision(guard(ws, tool, ti, ws.base)) is None, tool
    db = {"owner": "mock-org", "repo": "telephony-issue-db"}
    for tool, ti in (("mcp__mock-github-issues__update_issue", {**GH_ARGS, "state": "closed"}),
                     ("mcp__mock-github-issues__create_pull_request", {**db, "title": "x", "head": "h", "base": "main"}),
                     ("mcp__mock-github-issues__create_pull_request", {"owner": "mock-org", "repo": "other", "title": "x"}),
                     ("mcp__mock-github-issues__get_file_contents", {"owner": "a", "repo": "b"})):
        out = guard(ws, tool, ti, ws.base)
        assert decision(out) == "deny" and "규칙 2" in out["permissionDecisionReason"], tool
    for tool in ("mcp__x-jira__add_comment", "mcp__corp-atlassian__update_issue"):     # kind=github여도 휴리스틱 합집합
        out = guard(ws, tool, {}, ws.base)
        assert decision(out) == "deny" and "Jira/Atlassian" in out["permissionDecisionReason"], tool
    # 트래커가 아닌 일반 GitHub MCP: 쓰기형은 대상 레포와 무관하게 규칙 11 ask(4-c), 읽기형은 판정 없음(github server_words는 비어 있다)
    assert decision(guard(ws, "mcp__github__create_pull_request", {**db, "title": "x"}, ws.base)) == "ask"
    assert decision(guard(ws, "mcp__github__update_issue", {"owner": "a", "repo": "b", "issue_number": 1}, ws.base)) == "ask"
    assert decision(guard(ws, "mcp__github__get_issue", {"owner": "a", "repo": "b", "issue_number": 1}, ws.base)) is None


def test_guard_github_approved_comment():
    ws = gh_shared()
    body = "### PROBLEM\n- GitHub: mock-org/mock-issues#12\n\n### CAUSE\n- 분류: 후보 없음"
    _gh_approve(ws, GH_KEY, body)
    ok = guard(ws, GH_COMMENT, {**GH_ARGS, "body": body}, ws.base)
    assert decision(ok) == "ask" and GH_KEY in ok["permissionDecisionReason"]
    assert decision(guard(ws, GH_COMMENT, {**GH_ARGS, "owner": "Mock-Org", "body": body}, ws.base)) == "ask"
    for ti, why in (({**GH_ARGS, "issue_number": 13, "body": body}, "승인 기록 없음"),
                    ({**GH_ARGS, "issue_number": "12", "body": body}, "이슈 키 형식 불일치"),
                    ({**GH_ARGS, "issue_number": 12.0, "body": body}, "이슈 키 형식 불일치"),
                    ({**GH_ARGS, "repo": "other", "body": body}, "승인 기록 없음"),
                    ({**GH_ARGS, "body": body, "reaction": "+1"}, "승인 범위 밖 인자: reaction"),
                    ({**GH_ARGS, "body": body + "\n- 끼워 넣기"}, "sha256")):
        out = guard(ws, GH_COMMENT, ti, ws.base)
        assert decision(out) == "deny" and why in out["permissionDecisionReason"], (ti, out)
    _gh_approve(ws, GH_KEY, body, kind="jira")                                    # P2-5: 다른 트래커의 승인 기록
    out = guard(ws, GH_COMMENT, {**GH_ARGS, "body": body}, ws.base)
    assert decision(out) == "deny" and "트래커(kind)" in out["permissionDecisionReason"]
    out = guard(ws, "Write", {"file_path": str(ws.job_dir(GH_KEY) / "post.approved.json"), "content": "{}"}, ws.base)
    assert decision(out) == "deny"


def test_guard_github_legacy_or_unknown_kind_denies_all_mcp():
    ws = gh_shared()
    cfg_path = ws.home / "config.yaml"
    saved = cfg_path.read_text(encoding="utf-8")
    try:
        for edit in ({"tracker": {"kind": "nosuch"}}, {"jira": {"mcp_server": "mock-jira"}}):
            data = yaml.safe_load(saved)
            data.update(edit)
            cfg_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
            for tool in (GH_READ, "mcp__github__get_file_contents"):
                assert decision(guard(ws, tool, {"method": "get", **GH_ARGS}, ws.base)) == "deny", (edit, tool)
    finally:
        cfg_path.write_text(saved, encoding="utf-8")


def _gh_bridge(ws: Workspace, tool_input, response, tool: str = GH_READ) -> str:
    event = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": tool_input, "tool_response": response}
    proc = run("jira_bridge.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"] if proc.stdout.strip() else ""


def test_bridge_github_issue_read_merges_and_isolates():
    import importlib.util
    spec = importlib.util.spec_from_file_location("github_issues_mcp_server", REPO / "tests" / "mocks" / "github_issues_mcp" / "server.py")
    gh_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gh_server)
    ws = gh_shared()
    key = "mock-org.mock-issues-13"
    raw = ws.job_dir(key) / "issue_raw.json"
    raw.unlink(missing_ok=True)
    args = {"owner": "mock-org", "repo": "mock-issues", "issue_number": 13}
    issue, _ = gh_server.call_tool("issue_read", {"method": "get", **args})
    text = _gh_bridge(ws, {"method": "get", **args}, gh_server.wrap(issue, False))
    assert "파일로만 저장" in text and "VoLTE" in text                                 # 마스킹 요약
    comments, _ = gh_server.call_tool("issue_read", {"method": "get_comments", **args})
    text = _gh_bridge(ws, {"method": "get_comments", **args}, gh_server.wrap(comments, False))
    saved = json.loads(raw.read_text(encoding="utf-8"))
    assert saved["key"] == key and saved["title"] == issue["title"] and saved["comments"] == comments
    assert stat_mode(raw) == 0o600
    # 매핑된 도구인데 지원하지 않는 method(get_labels): 원문 대체(fail-closed)
    labels, _ = gh_server.call_tool("issue_read", {"method": "get_labels", **args})
    text = _gh_bridge(ws, {"method": "get_labels", **args}, gh_server.wrap(labels, False))
    assert "지원하지 않는 읽기" in text and "Call" not in text
    # DB key_regex 밖 레포·문자열 issue_number: 저장하지 않고 원문도 보이지 않는다
    for ti in ({"method": "get", "owner": "other-org", "repo": "x", "issue_number": 1},
               {"method": "get", **args, "issue_number": "13"}):
        text = _gh_bridge(ws, ti, gh_server.wrap({"title": "비밀 제목", "body": "imsi=450081234567890"}, False))
        assert "저장하지 않았다" in text and "비밀 제목" not in text and "450081234567890" not in text, ti
    assert not (ws.work / "other-org.x-1").exists()


def stat_mode(path: Path) -> int:
    import stat
    return stat.S_IMODE(path.stat().st_mode)


def test_bridge_github_comment_result_marks_approval_used():
    ws = gh_shared()
    key = "mock-org.mock-issues-14"
    body = "### PROBLEM\n- GitHub: mock-org/mock-issues#14"
    _gh_approve(ws, key, body)
    args = {"owner": "mock-org", "repo": "mock-issues", "issue_number": 14, "body": body}
    text = _gh_bridge(ws, args, {"content": [{"type": "text", "text": json.dumps({"id": 9001, "html_url": "x"})}],
                                 "isError": False}, tool=GH_COMMENT)
    assert "게시했다" in text and "9001" in text
    result = json.loads((ws.job_dir(key) / "post.result.json").read_text(encoding="utf-8"))
    assert result["status"] == "posted" and result["comment_id"] == "9001" and result["key"] == key
    assert json.loads((ws.job_dir(key) / "post.approved.json").read_text(encoding="utf-8"))["used_at"]
    assert decision(guard(ws, GH_COMMENT, args, ws.base)) == "deny"                    # 1회용


def test_hooks_json_has_eight_rules_wired_to_guard():
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    assert "sync-scripts-path" in hooks["SessionStart"][0]["hooks"][0]["command"]
    matchers = {h["matcher"]: [x["command"] for x in h["hooks"]] for h in hooks["PreToolUse"]}
    assert set(matchers) == {"mcp__.*", "Bash", "Write|Edit|MultiEdit|NotebookEdit", "AskUserQuestion|mcp__.*__ask_user"}
    guarded = {m: cmds for m, cmds in matchers.items() if m != "AskUserQuestion|mcp__.*__ask_user"}
    assert all("${CLAUDE_PLUGIN_ROOT}/scripts/guard.py" in cmds[0] for cmds in guarded.values())
    # 표시 보조(08-safety.md "표시 보조 hook"): guard 뒤에 붙고, 판정은 show_guard.py 모드별
    assert matchers["Bash"][1].endswith('/scripts/show_guard.py" pre-bash') and len(matchers["Bash"]) == 2
    assert matchers["AskUserQuestion|mcp__.*__ask_user"] == ['python3 "${CLAUDE_PLUGIN_ROOT}/scripts/show_guard.py" pre-ask']
    assert len(matchers["mcp__.*"]) == 1 and len(matchers["Write|Edit|MultiEdit|NotebookEdit"]) == 1


def test_hooks_json_wires_show_guard_display_aid():
    hooks = json.loads((REPO / "plugin" / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
    (stop,) = hooks["Stop"]
    assert "matcher" not in stop and stop["hooks"] == [
        {"type": "command", "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/scripts/show_guard.py" stop', "timeout": 30}]
    post = {h["matcher"]: [x["command"] for x in h["hooks"]] for h in hooks["PostToolUse"]}
    assert post["Bash"] == ['python3 "${CLAUDE_PLUGIN_ROOT}/scripts/show_guard.py" post']
    assert all(x.get("timeout") for g in hooks["PostToolUse"] + hooks["PreToolUse"] for x in g["hooks"])


# -- 규칙 12 (a)(b): 모듈 스킬 관리 clone·기록 (B1 설계 §7, B2-22) ------------------------------------------

MODULE_REMOTE = "https://ghe.example.invalid/tt/module-skills.git"


def _reason(out: dict | None) -> str:
    return (out or {}).get("permissionDecisionReason", "")


def _module_ws(**top) -> Workspace:
    """사용자 config에 키를 더한 작업공간(clone을 바꾸지 않는다). 생성 파일 빌드는 하지 않는다."""
    ws = Workspace(build=False)
    cfg = ws.home / "config.yaml"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    data.update(top)
    cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return ws


def test_guard_module_clone_file_tools_denied_with_and_without_config():
    ws = shared()
    m = ws.work / "_module-skills"
    nohome = tmp("tt-nohome-")
    for target in (m / "ofono" / "data" / "SKILL.md", ws.work / "_module-skills.lock", ws.work / "MOCK-1" / "skill-wt" / "x.md",
                   ws.work / "_module-skills.tmp-1-2" / "x"):
        for tool in ("Write", "Edit", "NotebookEdit"):
            key = "notebook_path" if tool == "NotebookEdit" else "file_path"
            out = guard(ws, tool, {key: str(target), "content": "x"}, ws.base)
            assert decision(out) == "deny" and "규칙 12" in _reason(out), (tool, target)
    # 사용자 config 없이도 이름 기반(경로 조각) — 기본 work_dir의 skill-wt도
    env = {"TELEPHONY_TRIAGE_HOME": str(nohome)}
    out = guard(ws, "Write", {"file_path": str(nohome / "work" / "_module-skills" / "README.md")}, ws.base, env=env)
    assert decision(out) == "deny"
    out = guard(ws, "Write", {"file_path": str(nohome / "work" / "K-1" / "skill-wt" / "a.md")}, ws.base, env=env)
    assert decision(out) == "deny"
    assert decision(guard(ws, "Write", {"file_path": str(nohome / "work" / "K-1" / "notes.md")}, ws.base, env=env)) is None


def test_guard_module_clone_default_work_dir_of_enabled_platform():
    root = plugin_root("module-enabled", platform={"name": "android", "enabled": ["android", "ofono"]})
    ws = Workspace(root=root, build=False)
    target = ws.home / "work-ofono" / "K-1" / "skill-wt" / "x.md"       # 사용자 ofono 프로필은 없다
    assert decision(guard(ws, "Write", {"file_path": str(target)}, ws.base)) == "deny"
    rec = ws.home / "work-ofono" / "K-1" / "module-skill.json"
    assert decision(guard(ws, "Write", {"file_path": str(rec)}, ws.base)) == "deny"


def test_guard_module_clone_bash_writes_denied():
    ws = shared()
    m = ws.work / "_module-skills"
    lock = ws.work / "_module-skills.lock"
    cmds = [f"echo x > {m}/CLAUDE.md", f"cp a {m}/ofono/data/SKILL.md", f"sed -i s/a/b/ {m}/README.md", f"rm -rf {m}",
            f"cd {m} && rm -f README.md", f"tee {lock}", f"mv {lock} /tmp/x", f"mv {m} /tmp/x",
            f"ln -s {m} /tmp/l && echo x > /tmp/l/CLAUDE.md", f"rsync --remove-source-files {m}/README.md /tmp/",
            f"touch {ws.work}/_module-skills.tmp-1-2/x", f"mv -t /tmp {m}"]
    for cmd in cmds:
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "deny" and "규칙 12" in _reason(out), cmd
    # 읽기는 통과, 관문 밖 평소 명령은 지금과 같은 결정
    for cmd in (f"cat {m}/README.md", f"ls {m}", f"cp {m}/README.md /tmp/r.md", "ls /tmp"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd
    nohome = {"TELEPHONY_TRIAGE_HOME": str(tmp("tt-nohome-"))}
    assert decision(bash(ws, "ls /tmp", ws.base, env=nohome)) is None
    assert decision(bash(ws, f"rm -rf {m}", ws.base, env=nohome)) == "deny"      # 이름 기반


def test_guard_module_clone_git_allowlist_without_issue_db_path():
    ws = shared()
    nohome = tmp("tt-nohome-")
    env = {"TELEPHONY_TRIAGE_HOME": str(nohome)}            # 사용자 config·issue_db.path 없음: git_rules 꺼짐
    m = nohome / "work" / "_module-skills"
    job = nohome / "work" / "K-1"
    deny = [f"git -C {m} commit -m x", f"git -C {m} push", f"git -C {m} stash", f"git -C {m} reset --hard",
            f"git -C {m} checkout .", f"git -C {m} sparse-checkout set x", f"git -C {m} worktree add ../w",
            f"git -C {m} fetch", f"git -C {m} remote set-url origin x", f"git -C {m} config core.fsmonitor x",
            f"git -C {m} -c core.fsmonitor=x status", f"GIT_DIR={m}/.git git reset --hard",
            f"git --git-dir={m}/.git --work-tree=/tmp/y checkout .", f"git clone file:///x {m}",
            f"git -C {m} grep -Ovim x", f"git -C {m} grep --open-files-in-pager x", f"git -C {m} diff --ext-diff",
            f"git -C {m} branch -D main", f"git -C {m} branch newb", f"git -C {m} config --unset core.x"]
    for cmd in deny:
        out = bash(ws, cmd, ws.base, env=env)
        assert decision(out) == "deny" and "규칙 12" in _reason(out), cmd
    # 어디서 돌든 경로 옵션
    for cmd in (f"git config --file {m}/.git/config core.fsmonitor x", f"git -C /tmp diff --output={m}/CLAUDE.md",
                f"git -C {m} log --output={job}/module-skill/deep/ofono/data/SKILL.md",
                f"git -C /tmp format-patch -o {m} HEAD~1"):
        out = bash(ws, cmd, tmp("tt-elsewhere-"), env=env)
        assert decision(out) == "deny" and "규칙 12" in _reason(out), cmd
    for cmd in (f"git -C {m} status", f"git -C {m} log -1", f"git -C {m} diff", f"git -C {m} sparse-checkout list",
                f"git -C {m} remote -v", f"git -C {m} config --get remote.origin.url", f"git -C {m} branch -a",
                f"git -C {m} grep -n x", f"git -C {m} remote get-url origin", f"git -C {m} stash list"):
        assert decision(bash(ws, cmd, ws.base, env=env)) is None, cmd
    assert decision(bash(ws, "git -C /tmp status", ws.base, env=env)) is None


def test_guard_module_records_denied_copies_and_notes_pass():
    ws = shared()
    job = ws.work / "MOCK-1"
    for rel in ("module-skill.json", "deep-input.json", "skill-input.json", "check-output.json",
                "module-skill/deep/ofono/data/SKILL.md"):
        out = guard(ws, "Write", {"file_path": str(job / rel), "content": "x"}, ws.base)
        assert decision(out) == "deny" and "만 쓴다" in _reason(out) and "규칙 12" in _reason(out), rel
        for cmd in (f"echo x > {job / rel}", f"rm -f {job / rel}"):
            assert decision(bash(ws, cmd, ws.base)) == "deny", cmd
    assert decision(bash(ws, f"rm -rf {job}/module-skill", ws.base)) == "deny"
    for rel in ("skill-suggestions/ofono/data/SKILL.md", "notes.md", "deep-output.md", "explore-output.md"):
        assert decision(guard(ws, "Write", {"file_path": str(job / rel), "content": "x"}, ws.base)) is None, rel


def test_guard_module_records_relative_paths_use_hook_cwd():
    """B2-22: 상대 경로는 hook 입력 `cwd`로 푼다(guard 프로세스의 cwd가 아니다 — OpenCode 셈이 workdir를 cwd에 넣는다)."""
    ws = shared()
    job = ws.work / "MOCK-1"
    job.mkdir(parents=True, exist_ok=True)
    event = {"tool_name": "Bash", "tool_input": {"command": "rm -f module-skill.json"}, "cwd": str(job)}
    proc = run("guard.py", [], root=ws.root, cwd=tmp("tt-other-cwd-"), env=ws.env(), stdin=json.dumps(event))
    assert proc.returncode == 0 and json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    event = {"tool_name": "Write", "tool_input": {"file_path": "check-output.json", "content": "x"}, "cwd": str(job)}
    proc = run("guard.py", [], root=ws.root, cwd=tmp("tt-other-cwd-"), env=ws.env(), stdin=json.dumps(event))
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_guard_word_net_signature_pinned_for_oc_adapter():
    """R26: oc_adapter가 쓰는 guard 내부 함수의 모양을 고정한다."""
    import inspect

    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import guard as guard_mod

    sig = inspect.signature(guard_mod.word_net)
    assert [(p.name, p.default) for p in sig.parameters.values()] == [
        ("command", inspect.Parameter.empty), ("name", "db_pr"), ("word", "publish")]
    assert guard_mod.word_net("python3 db_pr.py publish x") is True
    assert guard_mod.word_net("triage.py module K --for deep", "module_eval", "module") is False


def test_guard_triage_module_has_no_decision_normal_and_degraded():
    ws = shared()
    cmd = f'python3 "{ws.root}/scripts/triage.py" module MOCK-1 --for deep'
    assert decision(bash(ws, cmd, ws.base)) is None
    event = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(ws.base)}
    proc = run("guard.py", [], root=ws.root, cwd=ws.base, env=_no_yaml_env(ws), stdin=json.dumps(event))
    assert proc.returncode == 0 and not proc.stdout.strip() and "의존성 없음" in proc.stderr


def test_guard_degraded_denies_module_clone_writes():
    ws = shared()
    env = _no_yaml_env(ws)

    def judge(tool: str, tool_input: dict):
        event = {"tool_name": tool, "tool_input": tool_input, "cwd": str(ws.base)}
        proc = run("guard.py", [], root=ws.root, cwd=ws.base, env=env, stdin=json.dumps(event))
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

    m = ws.work / "_module-skills"
    assert decision(judge("Write", {"file_path": str(m / "x.md")})) == "deny"
    assert decision(judge("Write", {"file_path": str(ws.base / "x.md")})) == "ask"
    assert decision(judge("Bash", {"command": f"echo x > {m}/CLAUDE.md"})) == "deny"
    assert decision(judge("Bash", {"command": f"mv {ws.work}/_module-skills.lock /tmp/x"})) == "deny"


def test_guard_gh_and_mcp_with_module_remote():
    ws = _module_ws(module_skills={"remote": MODULE_REMOTE})
    plain = tmp("tt-gh-plain-")
    module_clone = _repo_with_origin(MODULE_REMOTE)
    baseline = bash(shared(), f"gh pr create -R {DB_SLUG} -t x", plain)
    out = bash(ws, "gh pr create -R tt/module-skills -t x", plain)
    assert decision(out) == "ask" and _reason(out) == _reason(baseline)       # 규칙 11 문구 그대로(메모 없음)
    assert decision(bash(ws, "gh pr merge 1 -R tt/module-skills", plain)) == "ask"         # 병합 계열은 ask(4-c)
    assert decision(bash(ws, "gh pr review 1 --approve -R tt/module-skills", plain)) == "deny"
    assert decision(bash(ws, "gh pr create -t x", module_clone)) == "ask"
    assert decision(guard(ws, "mcp__github__merge_pull_request", {"owner": "tt", "repo": "module-skills"}, ws.base)) == "ask"
    assert decision(bash(ws, "gh pr create -R tt/other -t x", plain)) == "ask"       # 대상 레포를 보지 않는다(4-c)
    # 사용자 config 없이 site-defaults의 remote만 있어도 판정한다
    root = plugin_root("module-remote-site", module_skills={"remote": MODULE_REMOTE})
    nohome = {"TELEPHONY_TRIAGE_HOME": str(tmp("tt-nohome-"))}
    proc = run("guard.py", [], root=root, cwd=plain, env=nohome, stdin=json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 1 -R tt/module-skills"}, "cwd": str(plain)}))
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_guard_module_remote_warnings():
    def warn(remote: str) -> str:
        ws = _module_ws(module_skills={"remote": remote})
        event = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(ws.base)}
        return run("guard.py", [], root=ws.root, cwd=ws.base, env=ws.env(), stdin=json.dumps(event)).stderr

    assert "module_skills" not in warn("file:///tmp/r.git")
    err = warn("not a url")
    assert "module_skills.remote" in err and "규칙 11" in err
    err = warn("https://u:secret@x.invalid/o")
    assert "module_skills.remote" in err and "secret" not in err


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


# -- 종합 리뷰 A 묶음: S1 미확인 Jira 읽기 ask, 인터프리터 인라인 코드·링크의 clone/원문 경로 ask -------------------------------------


def test_guard_asks_jira_reads_until_isolation_confirmed():
    """규칙 9(원문 격리)는 PostToolUse 출력 대체에 기대고 미지원이면 열린다. S1 확인 기록(site-defaults `tracker.isolation_confirmed`)
    전에는 read_tools 호출도 ask(위험 고지), 쓰기는 그대로 deny. OpenCode 어댑터 환경(TT_OC_ADAPTER)은 자체 관문·대체가 있어 묻지 않는다."""
    home = tmp("tt-home-")

    def judge(root: Path, tool: str, extra: dict | None = None) -> dict | None:
        event = {"tool_name": tool, "tool_input": {}, "cwd": str(home)}
        proc = run("guard.py", [], root=root, env={"TELEPHONY_TRIAGE_HOME": home, **(extra or {})}, stdin=json.dumps(event))
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None

    tracker = _jira("mock-jira", JIRA_TOOLS[0])
    tracker.pop("isolation_confirmed", None)
    unconfirmed = plugin_root("jira-unconfirmed", tracker=tracker)
    out = judge(unconfirmed, JIRA_TOOLS[0])
    assert decision(out) == "ask" and "isolation_confirmed" in out["permissionDecisionReason"] and "S1" in out["permissionDecisionReason"]
    assert decision(judge(unconfirmed, "mcp__mock-jira__jira_add_comment")) == "deny"
    assert judge(unconfirmed, JIRA_TOOLS[0], {"TT_OC_ADAPTER": "1"}) is None
    confirmed = plugin_root("jira-confirmed", tracker={**tracker, "isolation_confirmed": True})
    assert judge(confirmed, JIRA_TOOLS[0]) is None
    assert decision(judge(plugin_root("jira-false", tracker={**tracker, "isolation_confirmed": False}), JIRA_TOOLS[0])) == "ask"


def test_guard_inline_interpreter_code_and_symlink_into_clone_ask():
    """종합 리뷰에서 재현된 우회: `python3 -c`/heredoc/`perl -e` 안의 clone 쓰기와 원문 읽기, `ln -s <clone>`은 셸 파서가 보지 못해
    통과했다. 코드 의미는 모르므로 ask. 무관한 경로·경로 없는 코드·clone 밖 링크는 그대로 통과한다."""
    ws = shared()
    clone = ws.clone
    raw_dir = ws.root / "work" / "INLINE-1"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "events.json").write_text("{}", encoding="utf-8")
    link = tmp("tt-link-") / "lk"
    job = ws.job_dir("INLINE-2").as_posix()          # 스크립트만 쓰는 기록 경로(규칙 2·7·12)
    asks = [
        (f"python3 -c \"open('{job}/post.approved.json','w').write('x')\"", "기록 경로"),
        (f"python3 - <<'EOF'\nopen('{job}/post.result.json','w').write('x')\nEOF", "기록 경로"),
        (f"perl -e 'open(F,\">{job}/merge-offer.json\");print F 1'", "기록 경로"),
        (f"python3 -c \"open('{job}/post.approved.json'); open('{clone.as_posix()}/x','w')\"", "기록 경로"),
        (f"python3 -c \"open('{job}/post.approved.json'); open('{clone.as_posix()}/x','w')\"", "규칙 8"),
        (f"python3 -c \"open('{clone}/README.md','w').write('x')\"", "규칙 8"),
        (f"python3 - <<'EOF'\nopen('{clone}/README.md','w').write('x')\nEOF", "규칙 8"),
        (f"perl -e 'open(F,\">{clone}/README.md\");print F 1'", "규칙 8"),
        (f"python3 -c'import pathlib; pathlib.Path(\"{clone}/x\").write_text(\"1\")'", "규칙 8"),
        (f"ln -s {clone} {link}", "규칙 8"),
        (f"python3 -c \"print(open('{raw_dir}/events.json').read())\"", "규칙 10"),
    ]
    for cmd, rule in asks:
        out = bash(ws, cmd, clone)
        assert decision(out) == "ask" and rule in out["permissionDecisionReason"], (cmd, out)
    home = {"HOME": ws.base, "USERPROFILE": ws.base}  # `~/…` 꼴(Windows expanduser는 USERPROFILE)
    out = bash(ws, "python3 -c \"open('~/work/INLINE-2/post.result.json','w')\"", clone, env=ws.env(**home))
    assert decision(out) == "ask" and "기록 경로" in out["permissionDecisionReason"], out
    # 기록 경로 ask는 clone·원문 낱말이 먼저 나와도 남고, 기록 경로가 여럿이어도 코드 하나에 한 번이다
    for first, rule in ((f"{clone.as_posix()}/x", "규칙 8"), (f"{raw_dir.as_posix()}/events.json", "규칙 10")):
        out = bash(ws, f"python3 -c \"open('{first}'); open('{job}/post.approved.json')\"", clone)
        assert decision(out) == "ask" and "기록 경로" in out["permissionDecisionReason"], out
        assert rule in out["permissionDecisionReason"], out
    out = bash(ws, f"python3 -c \"open('{job}/post.approved.json'); open('{job}/merge-offer.json')\"", clone)
    assert decision(out) == "ask" and out["permissionDecisionReason"].count("기록 경로") == 1, out
    for cmd in (f"python3 -c \"print(open('{ws.root}/no-such-notes.txt').read())\"", "python3 -c 'print(1+1)'",
                f"python3 -c \"open('{job}/notes.txt','w')\"", "python3 -c \"open('/tmp/K1/post.approved.json','w')\"",
                f"python3 -c \"open('{job}/skill-suggestions/a/rel.txt','w')\"",
                f"ln -s {link} {link}2", "perl -e 'print 1'", f"python3 -c \"import json; json.load(open('{clone}'))\" --flag"):
        out = bash(ws, cmd, clone)
        assert decision(out) in (None, "ask") if "import json" in cmd else decision(out) is None, (cmd, out)
