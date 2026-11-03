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


def test_guard_comment_does_not_swallow_next_line():
    """K 3차 P1-b: 주석 뒤 줄의 명령은 따로 본다(shlex 기본 commenters가 주석과 줄바꿈을 함께 먹어 다음 줄이 앞 argv에 붙던 우회).
    `$#`·`${#x}`·`a#b`·인용 안 `#`은 주석이 아니다."""
    ws = shared()
    c = ws.clone
    assert decision(bash(ws, "echo x # note\ngit push origin HEAD:main", c)) == "deny"
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


def test_guard_merge_and_skill_apply_ask_direct_gh_merge_denied():
    """PR 바로 병합: `db_pr.py merge`는 ask(사용자가 "병합"을 고른 뒤, 스크립트가 승인 커밋·검사 대조), gh로 직접 머지는 거부.
    분석 스킬 소스 적용: `skill_patch.py --apply`는 ask(규칙 12). patch 만들기·my-prs는 판정할 것이 없다."""
    ws = shared()
    S = f'python3 "{ws.root}/scripts/'
    out = bash(ws, f'{S}db_pr.py" merge --job MOCK-1 --approved {"a" * 40} --json', ws.base)
    assert decision(out) == "ask" and "db_pr.py merge" in out["permissionDecisionReason"]
    out = bash(ws, f"gh pr merge 3 --merge -R {DB_SLUG}", ws.base)
    assert decision(out) == "deny" and "db_pr.py merge" in out["permissionDecisionReason"]
    out = bash(ws, f'{S}skill_patch.py" MOCK-1 --name mock-data-analyzer --apply --sha {"b" * 64}', ws.base)
    assert decision(out) == "ask" and "규칙 12" in out["permissionDecisionReason"]
    for cmd in (f'{S}skill_patch.py" MOCK-1 --skill-dir /x --name mock-data-analyzer', f'{S}db_pr.py" my-prs',
                f'{S}db_pr.py" summary wt --format markdown'):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd
    # "push하고 바로 병합" = 한 명령: 권한 확인 한 번(publish·merge 사유 둘 다)
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
                f'echo "python3 {root}/db_pr.py publish wt" | bash', f"printf '%s\\n' 'python3 $S/db_pr.py publish wt' | sh",
                f"python3 -c \"import subprocess; subprocess.run(['python3', '{root}/db_pr.py', 'publish', 'wt'])\""):
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "ask" and "규칙 7" in out["permissionDecisionReason"], cmd
    for cmd in ("${S}db_pr.py stage plan.json --wt wt --branch issue/MOCK-1 --then-summary",
                "$PY $S/db_pr.py summary wt --format markdown", "${S}db_pr.py discard wt",
                f"grep -n publish {root}/db_pr.py", 'grep -n "db_pr.py publish" x.md', "cat $S/db_pr.py | grep publish",
                'rg "publish" db_pr.py', "python3 -m pytest tests/test_db_pr.py -k publish", "ls # db_pr.py publish wt"):
        assert decision(bash(ws, cmd, ws.base)) is None, cmd
    assert decision(bash(ws, "git push origin HEAD:refs/heads/main x/db_pr.py publish", ws.clone)) == "deny"
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
                "gh alias set p '!python3 $S/db_pr.py publish wt'; gh p",
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
            "read_tools": [get_issue]}


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
        ws.json("config.py", ["set", "tracker.read_tools", json.dumps([*JIRA_TOOLS, NOTE_TOOL])])
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
                 # GraphQL 병합 mutation은 대상과 무관하게 거부(H A1 — 노드 ID로 레포를 가린다)
                 ("gh api graphql -f query='mutation { mergePullRequest(input: {}) { clientMutationId } }'", c, "deny"),
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
             ("gh api -X POST repos/{owner}/{repo}/issues -f title=x", db_origin, "ask"),
             ("gh pr create -t x", db_origin, "ask"),
             (f"gh pr create --repo=ssh://git@ghe.mock.invalid/{DB_SLUG} -t x", plain, "ask"),
             # host는 보지 않는다(gh는 www.을 떼고, SSH 별칭 host는 guard가 풀 수 없다 — owner/repo로 비교, H-A1 r4)
             (f"gh pr create -R other.host.invalid/{DB_SLUG} -t x", plain, "ask"),
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
                f'S="python3 {ws.root}/scripts/"; ${{S}}db_pr.py publish wt', "$PY $S/db_pr.py publish wt"):
        out, _ = judge("Bash", {"command": cmd})
        assert decision(out) == "ask" and "레포 판별 불가" in out["permissionDecisionReason"], cmd
    out, err = judge("Bash", {"command": "echo hi"})
    assert out is None and "의존성 없음" in err
    out, _ = judge("Write", {"file_path": str(ws.base / "x.txt")})
    assert decision(out) == "ask"
    # Approve·리뷰 기각·병합·자동 병합·병합 별칭 형태는 대상 레포를 몰라도 거부(내부 오류를 입력으로 일으킬 수 있다 — 회귀 수정
    # R2), 그 밖의 gh 쓰기는 ask 그대로
    for cmd, want, why in (("gh pr review 3 --approve", "deny", "Approve"),
                           ("gh api -X PUT repos/o/r/pulls/3/reviews/9/dismissals", "deny", "Approve"),
                           ("gh -b LGTM pr review 3 --approve", "deny", "Approve"),        # 앞 옵션도 모든 읽기를 본다(H-A1 r4)
                           ("gh -X PUT api repos/o/r/pulls/3/reviews/9/dismissals", "deny", "Approve"),
                           ("if true; then gh pr review 3 --approve; fi", "deny", "Approve"),   # 예약어 뒤도 본다(H-A1 r5)
                           ('gh pr review 3 "$OPT"', "deny", "Approve"),                         # 셸 값 옵션은 Approve일 수 있다
                           ("gh pr merge 3", "deny", "머지"), ("gh pr merge 3 --auto --squash", "deny", "머지"),
                           ("gh -b x pr merge 3", "deny", "머지"), ("gh api -X PUT repos/o/r/pulls/3/merge", "deny", "머지"),
                           (f"gh api graphql -f query='{MERGE_MUTATION}'", "deny", "머지"),
                           ("gh alias set m 'pr merge --admin'", "deny", "머지"),
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
             (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", "deny"),
             (f"gh api -X POST repos/{DB_SLUG}/merges -f base=main -f head=x", "deny"),
             (f"gh api repos/{DB_SLUG}/pulls/3/merge", None)]   # GET: 머지 가능 여부 조회
    for cmd, want in cases:
        assert decision(bash(ws, cmd, plain)) == want, cmd


def test_guard_review_followups_mcp_verb_position():
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db"}
    # 자동 병합 켜기는 +1 관문 없이 서버 조건만으로 병합한다 — 거부(H A1). 끄기는 ask
    for tool, want in (("mcp__github__disable_pr_auto_merge", "ask"), ("mcp__github__enable_pr_auto_merge", "deny"),
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


APPROVE_MUTATION = 'mutation { addPullRequestReview(input: {pullRequestId: "x", event: APPROVE}) { clientMutationId } }'
MERGE_MUTATION = 'mutation { mergePullRequest(input: {pullRequestId: "x"}) { clientMutationId } }'


def test_guard_denies_claude_approve_dismiss_and_bypass_merges_on_issue_db():
    """규칙 11(H A1): Claude의 Approve·리뷰 기각, URL 선택자·붙인 `-R`의 병합, GraphQL 병합·자동 병합·Approve·기각 mutation
    (인라인·`@파일`·`--input`·stdin heredoc), 병합·리뷰 별칭 만들기는 거부. 변경 요청·코멘트 리뷰는 ask로 남는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    url = f"https://ghe.mock.invalid/{DB_SLUG}/pull/3"
    files = {"r.json": '{"event": "APPROVE", "body": "x"}', "c.json": '{"event": "COMMENT", "body": "x"}', "e.txt": "APPROVE",
             "q.graphql": APPROVE_MUTATION, "m.graphql": MERGE_MUTATION, "viewer.graphql": "query { viewer { login } }",
             "v.graphql": ("mutation($e: PullRequestReviewEvent!) { addPullRequestReview(input: {pullRequestId: \"x\", "
                           "event: $e}) { clientMutationId } }"),
             "q.json": json.dumps({"query": APPROVE_MUTATION.replace("addPullRequestReview", "submitPullRequestReview")}),
             "a.yml": "m: pr merge\n", "co.yml": "co: pr checkout\n"}
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
                   (f"gh pr review 3 --approve -R{DB_SLUG}", plain), (f"gh pr review 3 --approve -R={DB_SLUG}", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -F event=approve", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --raw-field event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --field=event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -fevent=APPROVE", plain),
                   (f"gh api -X POST repos/{DB_SLUG}/pulls/3/reviews/77/events -f event=APPROVE", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input r.json", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input -", plain),
                   (f"gh api repos/{DB_SLUG}/pulls/3/reviews -F event=@e.txt", plain),
                   # GraphQL은 대상과 무관하게(cwd = DB 아님)
                   (f"gh api graphql -f query='{APPROVE_MUTATION}'", plain), ("gh api graphql -F query=@q.graphql", plain),
                   ("gh api graphql -F query=@v.graphql -f e=APPROVE", plain), ("gh api graphql --input q.json", plain)]
        for cmd, cwd in approve:
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and "Approve하지 않는다" in out["permissionDecisionReason"], cmd
        merge = [(f"gh pr merge {url} --merge", plain), (f"gh pr merge 3 --merge -R{DB_SLUG}", plain),
                 (f"gh pr merge 3 --merge -R={DB_SLUG}", plain), (f"GH_REPO=other/repo gh pr merge 3 -R {DB_SLUG}", plain),
                 (f"gh pr merge 3 --merge -dR {DB_SLUG}", plain),       # pflag 묶음: -d(bool) + -R <값>
                 ("gh pr merge 3 -bRother/x", c),                       # 모호한 묶음은 cwd 판정을 막지 않는다
                 ("gh api graphql -F query=@m.graphql", plain),
                 (f"gh api graphql -F query=@- <<'EOF'\n{MERGE_MUTATION}\nEOF", plain),
                 ("gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'", plain),
                 ("gh api graphql -f query='mutation { enqueuePullRequest(input: {}) { clientMutationId } }'", plain)]
        for cmd, cwd in merge:
            out = bash(ws, cmd, cwd)
            assert decision(out) == "deny" and "머지" in out["permissionDecisionReason"], cmd
        for cmd in (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/reviews/9/dismissals -f message=x",
                    "gh api graphql -f query='mutation { dismissPullRequestReview(input: {}) { clientMutationId } }'"):
            out = bash(ws, cmd, plain)
            assert decision(out) == "deny" and "기각" in out["permissionDecisionReason"], cmd
        for cmd in ("gh alias set lgtm 'pr review --approve'", """gh alias set m '!gh pr merge "$1"'""",
                    "gh alias import a.yml", "gh alias import - <<'EOF'\nm: pr merge\nEOF", "cat a.yml | gh alias import -",
                    "gh alias import none.yml"):
            out = bash(ws, cmd, plain)
            assert decision(out) == "deny" and "별칭" in out["permissionDecisionReason"], cmd
        mcp = [("mcp__github__pull_request_review_write", {**db, "method": "create", "event": "APPROVE"}, "Approve하지 않는다"),
               ("mcp__github__pull_request_review_write", {**db, "method": "submit_pending", "event": "approve"},
                "Approve하지 않는다"),
               ("mcp__github__create_pull_request_review", {**db, "event": "APPROVE"}, "Approve하지 않는다"),
               ("mcp__x__approve_pull_request", db, "Approve하지 않는다"),
               ("mcp__x__dismiss_pull_request_review", db, "기각"), ("mcp__github__enable_pr_auto_merge", db, "머지")]
        for tool, tool_input, why in mcp:
            out = guard(ws, tool, tool_input, ws.base)
            assert decision(out) == "deny" and why in out["permissionDecisionReason"], tool
        asks = [(f"gh pr review 3 --request-changes -b x -R {DB_SLUG}", plain),
                (f"gh pr review 3 --comment -b x -R {DB_SLUG}", plain),
                (f"gh pr review 3 -a=false -R {DB_SLUG}", plain), (f"gh pr review 3 --approve=0 -R {DB_SLUG}", plain),
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=COMMENT -f body=x", plain),
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f event=REQUEST_CHANGES", plain),
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews -f body=x", plain),       # event 없음: PENDING 리뷰 만들기
                (f"gh api repos/{DB_SLUG}/pulls/3/reviews --input c.json", plain),
                ("gh api graphql -f query='mutation { addPullRequestReview(input: {event: COMMENT}) { clientMutationId } }'", c),
                ("gh api graphql -F query=@none.graphql", c),                   # 읽지 못한 본문은 쓰기
                ("cat x.graphql | gh api graphql -F query=@-", c),                # stdin이 heredoc이 아니면 모르는 본문
                (f"gh alias set p '!python3 {ws.root}/scripts/db_pr.py publish wt'; gh p", plain)]   # 낱말 그물 ask 그대로
        for cmd, cwd in asks:
            assert decision(bash(ws, cmd, cwd)) == "ask", cmd
        for tool, tool_input in (("mcp__github__pull_request_review_write", {**db, "method": "create", "event": "COMMENT"}),
                                 ("mcp__github__pull_request_review_write", {**db, "method": "create"}),
                                 ("mcp__github__disable_pr_auto_merge", db)):
            assert decision(guard(ws, tool, tool_input, ws.base)) == "ask", (tool, tool_input)
        # 병합·Approve는 다른 레포 명시 대상이어도 cwd(이슈 DB clone) 판정이 남는다(H-A1 r4 — 닫힌 쪽)
        out = bash(ws, "gh pr merge https://ghe.mock.invalid/other/repo/pull/3", c)
        assert decision(out) == "deny" and "머지" in out["permissionDecisionReason"]
        nothing = [("gh pr review 3 --approve -R other/repo", plain),
                   ("gh pr merge https://ghe.mock.invalid/other/repo/pull/3", plain),
                   (f"gh api -X GET repos/{DB_SLUG}/pulls/3/reviews", plain), (f"gh api repos/{DB_SLUG}/pulls/3/reviews", plain),
                   ("gh api graphql -F query=@viewer.graphql", plain),
                   ("gh api graphql -F query=@- <<'EOF'\nquery { viewer { login } }\nEOF", plain),
                   ("gh alias set co 'pr checkout'", plain), ("gh alias import co.yml", plain),
                   ("gh lgtm 3", plain)]     # 이미 만든 별칭의 실행은 보지 못한다(한계 — 08 규칙 11)
        for cmd, cwd in nothing:
            assert decision(bash(ws, cmd, cwd)) is None, cmd
        other = {"owner": "other", "repo": "x", "pullNumber": 3, "event": "APPROVE"}
        assert decision(guard(ws, "mcp__github__pull_request_review_write", other, ws.base)) is None
        empty = {"TELEPHONY_TRIAGE_HOME": tmp("tt-nohome-")}      # 사용자 config 없음: 규칙 11 없음
        assert decision(bash(ws, f"gh pr review 3 --approve -R {DB_SLUG}", plain, env=empty)) is None
        assert decision(bash(ws, f"gh api graphql -f query='{MERGE_MUTATION}'", plain, env=empty)) is None
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_gh_url_selector_option_values_api_clusters_and_graphql_url():
    """규칙 11(H A1 리뷰): URL은 `pr`·`issue` 동작 뒤 첫 위치 인자일 때만 선택자다 — 옵션 값(`--body`·`-b`·`-t=`·`-c`·
    `--duplicate-of`)의 다른 레포 URL은 cwd(이슈 DB clone) 판정을 막지 않는다. `gh api`의 bool `-i` 묶음(`-iX PUT`·`-if k=v`)과
    전체 URL GraphQL 엔드포인트도 병합·Approve·기각으로 본다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    (plain / "m.graphql").write_text(MERGE_MUTATION, encoding="utf-8")
    other = "https://ghe.mock.invalid/other/repo"
    rows = [(f"gh pr merge 3 --merge --body {other}/issues/5", c, "deny"),
            (f"gh pr merge 3 --auto --squash -b '{other}/issues/12 반영'", c, "deny"),
            (f"gh pr merge 3 -t={other}/issues/5", c, "deny"), (f"gh pr merge 3 -b{other}/issues/5", c, "deny"),
            (f"gh pr review 3 --approve -b {other}/pull/9", c, "deny"),
            (f"gh pr comment 3 --body {other}/issues/1", c, "ask"), (f"gh pr edit 3 --body {other}/issues/1", c, "ask"),
            (f"gh pr close 3 -c {other}/issues/1", c, "ask"),
            (f"gh issue close 3 --duplicate-of {other}/issues/5", c, "ask"),
            (f"gh pr comment 3 --body https://ghe.mock.invalid/{DB_SLUG}/issues/1", plain, "ask"),  # 옵션 값의 DB URL은 센다
            # 선택자 URL은 그대로 이긴다(bool 옵션·`--` 뒤도 선택자) — 쓰기(ask) 종류만. 병합·Approve·기각은 다른 레포 선택자여도
            # cwd(이슈 DB) 판정이 남는다(H-A1 r4)
            (f"gh pr edit --add-label x {other}/pull/3", c, None), (f"gh pr close -d {other}/pull/3", c, None),
            (f"gh pr comment -b x {other}/pull/3", c, None), (f"gh pr comment -- {other}/pull/3", c, None),
            (f"gh pr review --comment {other}/pull/3 -b x", c, None),
            (f"gh pr merge --squash {other}/pull/3", c, "deny"), (f"gh pr merge -sd {other}/pull/3", c, "deny"),
            (f"gh pr merge -b x {other}/pull/3", c, "deny"), (f"gh pr merge -- {other}/pull/3", c, "deny"),
            (f"gh pr merge -b x {other}/pull/3", plain, None),
            # gh api: bool -i와 묶은 짧은 옵션(pflag)
            (f"gh api -iX PUT repos/{DB_SLUG}/pulls/3/merge", plain, "deny"),
            (f"gh api -iXPUT repos/{DB_SLUG}/pulls/3/merge", plain, "deny"),
            (f"gh api -iX=PUT repos/{DB_SLUG}/pulls/3/merge", plain, "deny"),
            (f"gh api repos/{DB_SLUG}/pulls/3/reviews -if event=APPROVE", plain, "deny"),
            (f"gh api -iX PUT repos/{DB_SLUG}/pulls/3/reviews/9/dismissals -f message=x", plain, "deny"),
            (f"gh api graphql -if query='{MERGE_MUTATION}'", plain, "deny"),
            (f"gh api -iX GET repos/{DB_SLUG}/pulls/3/merge", plain, None),
            # 전체 URL GraphQL 엔드포인트(gh는 필드를 JSON 본문 {"query": …}로 보낸다)
            (f"gh api https://ghe.mock.invalid/api/graphql -f query='{MERGE_MUTATION}'", plain, "deny"),
            (f"gh api https://ghe.mock.invalid/api/graphql -f query='{APPROVE_MUTATION}'", plain, "deny"),
            ("gh api https://api.github.com/graphql -F query=@m.graphql", plain, "deny"),
            ("gh api https://ghe.mock.invalid/api/graphql -f query='query { viewer { login } }'", plain, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_gh_repo_flag_in_option_value_keeps_cwd_target():
    """규칙 11(H A1 리뷰): 값 받는 옵션의 값 자리(`-b -Rother/x`·`--body '-R other/x'`)와 `gh api`(옵션 `-R`가 없다)의 `-R` 꼴은
    gh가 레포로 읽지 않는다 — 이슈 DB일 때만 대상으로 세고 cwd(이슈 DB clone·worktree) 판정을 막지 않는다. 옵션 자리의
    `-R<v>`·`-R <v>`(다른 레포)는 그대로 cwd를 이긴다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-repo-value"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [("gh pr merge 3 --merge -b -Rother/x", "deny"), ("gh pr merge 3 --merge --body '-R other/x'", "deny"),
            ('gh pr merge 3 --squash -b "-Resolved MOCK-1101 in data/DATA-001"', "deny"),
            ("gh pr merge 3 --merge -b -R other/x", "deny"),       # 값 `-R` 뒤 other/x는 위치 인자다
            ("gh pr merge 3 --merge --subject=x -t -Rother/x", "deny"),
            ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/merge' -q -Rother/x", "deny"),
            ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/merge' -R other/x", "deny"),
            ("gh pr review 3 --approve -b -Rother/x", "deny"), ("gh pr review 3 --approve --body '-R other/x'", "deny"),
            ("gh pr review 3 --approve -b -R other/x", "deny"),
            ("gh api 'repos/{owner}/{repo}/pulls/3/reviews' -f event=APPROVE -t -Rother/x", "deny"),
            ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/reviews/9/dismissals' -f message=x -f -Rother/x", "deny"),
            ("gh pr create -t x -b '-R other/x 참고' -H issue/MOCK-1", "ask"), ("gh pr comment 3 -b -Rother/x", "ask"),
            # 옵션 자리의 다른 레포는 cwd를 이긴다 — 쓰기(ask) 종류만. 병합·Approve·기각은 cwd 판정이 남는다(H-A1 r4)
            ("gh pr comment 3 -Rother/x -b x", None), ("gh pr edit 3 -b x -R other/x", None),
            ("gh pr review 3 --comment -R other/x -b x", None),    # `pr review`의 --comment는 bool
            ("gh pr create -t x -b y -Rother/x", None),
            ("gh pr merge 3 --merge -Rother/x", "deny"), ("gh pr merge 3 --merge -b x -R other/x", "deny"),
            ("gh pr review 3 --approve -R other/x", "deny")]
    try:
        for cwd in (c, wt):
            for cmd, want in rows:
                assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
        # 값 자리의 이슈 DB는 대상으로 센다(cwd가 이슈 DB가 아니어도)
        for cmd, want in ((f"gh pr merge 3 --merge -b -R{DB_SLUG}", "deny"), (f"gh pr merge 3 -b -R {DB_SLUG}", "deny"),
                          (f"gh api -X PUT 'repos/{{owner}}/{{repo}}/pulls/3/merge' -q -R{DB_SLUG}", "deny"),
                          (f"gh pr comment 3 --body '-R {DB_SLUG}'", "ask")):
            assert decision(bash(ws, cmd, plain)) == want, cmd
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_gh_url_scheme_case_repo_id_endpoint_and_fragment():
    """규칙 11(H A1 리뷰): 대문자 스킴 URL 선택자(`HTTPS://…/pull/N` — gh는 스킴을 소문자로 바꿔 URL로 본다), REST
    `repositories/<id>/…`의 병합·Approve·기각(레포 ID라 대상을 풀 수 없다 — 대상과 무관하게 거부), 엔드포인트의 `#` 조각(gh는
    보내지 않는다)도 cwd(이슈 DB 아님)에서 거부한다. `repos/{owner}/{repo}` 자리표시는 그대로 cwd로 본다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    db = f"ghe.mock.invalid/{DB_SLUG}"
    rid = "repositories/123456/pulls/3"
    approve, merge, dismiss = "Approve하지 않는다", "머지", "기각"
    rows = [(f"gh pr review HTTPS://{db}/pull/3 --approve", plain, "deny", approve),
            (f"gh pr review Https://{db}/pull/3 -a", plain, "deny", approve),
            (f"gh pr merge HTTPS://{db}/pull/3 --squash", plain, "deny", merge),
            (f"gh pr merge hTtP://{db}/pull/3 --squash", plain, "deny", merge),
            (f"gh pr edit HTTPS://{db}/pull/3 --title x", plain, "ask", None),
            ("gh pr edit HTTPS://ghe.mock.invalid/other/repo/pull/3 --title x", c, None, None),   # 선택자 URL이 cwd를 이긴다
            ("gh pr merge HTTPS://ghe.mock.invalid/other/repo/pull/3", c, "deny", merge),   # 병합은 cwd 판정이 남는다(r4)
            # repositories/<id>: 대상과 무관하게
            (f"gh api {rid}/reviews -f event=APPROVE", plain, "deny", approve),
            (f"gh api -X PUT {rid}/merge", plain, "deny", merge),
            (f"gh api -X PUT {rid}/reviews/9/dismissals -f message=x", plain, "deny", dismiss),
            (f"gh api -X PUT https://ghe.mock.invalid/api/v3/{rid}/merge", plain, "deny", merge),
            (f"gh api {rid}/merge", plain, None, None),                          # GET: 조회
            (f"gh api {rid}/reviews -f event=COMMENT -f body=x", plain, None, None),   # 그 밖 쓰기는 cwd로 본다
            ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/merge'", plain, None, None),
            ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/merge'", c, "deny", merge),
            # `#` 조각
            (f"gh api 'repos/{DB_SLUG}/pulls/3/reviews#x' -f event=APPROVE", plain, "deny", approve),
            (f"gh api -X PUT 'repos/{DB_SLUG}/pulls/3/merge#x'", plain, "deny", merge),
            (f"gh api -X POST 'repos/{DB_SLUG}/merges#x' -f base=main -f head=x", plain, "deny", merge),
            (f"gh api -X PUT 'repos/{DB_SLUG}/pulls/3/reviews/9/dismissals#x' -f message=x", plain, "deny", dismiss),
            (f"gh api -X PUT 'https://{db.split('/')[0]}/api/v3/repos/{DB_SLUG}/pulls/3/merge#x'", plain, "deny", merge),
            (f"gh api 'repos/{DB_SLUG}/pulls/3/merge#x'", plain, None, None)]
    for cmd, cwd, want, why in rows:
        out = bash(ws, cmd, cwd)
        assert decision(out) == want, (cmd, cwd)
        assert why is None or why in out["permissionDecisionReason"], cmd


def test_guard_gh_leading_options_target_resolution_and_placeholders_close_classes():
    """규칙 11(H-A1 r4, 부류로 닫기): ① 그룹·동작 앞 옵션(`gh -b x pr merge`·`gh pr -b x merge`·`gh -X PUT api …` — cobra는 그
    단계의 모르는 옵션이 다음 토큰을 먹는다)은 가능한 읽기를 모두 보고 가장 센 결정을 쓴다. 어느 읽기도 쓰기가 아니어도 대상이
    이슈 DB면 ask. ② 병합·Approve·기각은 다른 레포로 푼 명시 대상이 cwd(이슈 DB) 판정을 끄지 않는다. ③ 대상 비교는 owner/repo만
    (`www.`·끝 점·host 무관), 퍼센트 디코딩, 셸이 풀 값(`$`·백틱·`$( )`)과 명령 글의 `GH_REPO` 대입·언급은 이슈 DB일 수 있다로
    본다. ④ 엔드포인트의 한 칸만 자리표시면 남은 칸이 이슈 DB 것과 같을 때 대상이다. 읽기·다른 레포 작업은 그대로다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    same = _repo_with_origin("https://ghe.mock.invalid/mock-org/telephony-triage")    # 같은 owner의 다른 레포
    fork = _repo_with_origin(f"https://ghe.mock.invalid/jdoe/{DB_SLUG.split('/')[1]}")
    h = "https://ghe.mock.invalid"
    wt = ws.work / "wt-r4"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    approve, merge, dismiss = "Approve하지 않는다", "머지", "기각"
    rows = [
        # ① 앞 옵션 — 병합·Approve·기각(대상 무관 GraphQL·repositories/<id> 포함)
        ("gh pr -b x merge 3 --merge", c, "deny", merge), ("gh pr --body x merge 3", c, "deny", merge),
        ("gh -b x pr merge 3", c, "deny", merge), ("gh pr -b LGTM review 3 --approve", c, "deny", approve),
        ("gh -b LGTM pr review 3 --approve", wt, "deny", approve),
        (f"gh -X PUT api repos/{DB_SLUG}/pulls/3/merge", plain, "deny", merge),
        (f"gh -f event=APPROVE api repos/{DB_SLUG}/pulls/3/reviews", plain, "deny", approve),
        (f"gh -f query='{MERGE_MUTATION}' api graphql", plain, "deny", merge),
        (f"gh pr -b x merge 3 --merge -R {DB_SLUG}", plain, "deny", merge),
        (f"gh -R {DB_SLUG} -b x pr merge 3", plain, "deny", merge),
        ("gh pr -t x merge 3 --auto", c, "deny", merge), ("gh --body x pr merge 3 --auto", c, "deny", merge),
        (f"gh --method PUT api repos/{DB_SLUG}/pulls/3/merge", plain, "deny", merge),
        (f"gh -X PUT api repos/{DB_SLUG}/pulls/3/reviews/5/dismissals", plain, "deny", dismiss),
        ("gh -X PUT api repositories/123/pulls/3/merge", plain, "deny", merge),
        (f"gh -f query='{APPROVE_MUTATION}' api graphql", plain, "deny", approve),
        ("gh -f query='mutation { dismissPullRequestReview(input: {}) { clientMutationId } }' api graphql", plain, "deny",
         dismiss),
        ("gh -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }' api graphql", plain, "deny",
         merge),
        ("gh pr -b -R merge 3", c, "deny", merge),       # pr 단계의 -b가 -R를 값으로 먹고 merge가 동작이다
        # ① 앞 옵션 — 그 밖 쓰기는 ask, 동작을 못 정해도 대상이 이슈 DB면 ask
        ("gh -b hi pr comment 3", c, "ask", None), ("gh pr -b hi comment 3", c, "ask", None),
        ("gh -t x pr create -b y", c, "ask", None), (f"gh -X PUT api repos/{DB_SLUG}/contents/x", plain, "ask", None),
        ("gh pr --json state view 3", c, "ask", None), ("gh pr --json state view 3", plain, None, None),
        (f"gh -R {DB_SLUG} pr view 3", c, None, None), ("gh --version", c, None, None),
        # ② 거부 종류는 다른 레포 명시 대상이 cwd 판정을 끄지 않는다. 쓰기는 그대로 명시 대상이 이긴다
        (f"gh pr merge {h}/other/repo/pull/3", c, "deny", merge), ("gh pr merge 3 -R other/repo", c, "deny", merge),
        ("gh pr review 3 --approve -R other/repo", wt, "deny", approve),
        ("gh api -X PUT repos/other/repo/pulls/3/merge", c, "deny", merge),
        ("gh pr merge 3 -R other/repo", plain, None, None), (f"gh pr merge {h}/other/repo/pull/3", plain, None, None),
        (f"gh pr edit {h}/other/repo/pull/3 --add-label x", c, None, None),
        ("gh pr comment 3 -R other/repo -b x", c, None, None),
        # ③ host 무관·퍼센트 디코딩·셸이 풀 값·GH_REPO 대입
        (f"gh pr merge https://www.ghe.mock.invalid/{DB_SLUG}/pull/3", plain, "deny", merge),
        (f"gh pr merge https://www.ghe.mock.invalid/{DB_SLUG}/pull/3 --auto", c, "deny", merge),
        (f"gh pr review https://www.ghe.mock.invalid/{DB_SLUG}/pull/3 --approve", wt, "deny", approve),
        (f"gh pr merge 3 -R www.ghe.mock.invalid/{DB_SLUG}", plain, "deny", merge),
        (f"GH_REPO=www.ghe.mock.invalid/{DB_SLUG} gh pr merge 3", plain, "deny", merge),
        (f"gh pr merge https://ghe.mock.invalid./{DB_SLUG}/pull/3", c, "deny", merge),
        (f"gh pr merge {h}/mock-org/telephony%2Dissue-db/pull/3 --squash", c, "deny", merge),
        (f"gh pr merge {h}/mock-org/%74elephony-issue-db/pull/3", c, "deny", merge),
        (f"gh pr review {h}/mock-org/telephony%2Dissue-db/pull/3 --approve", wt, "deny", approve),
        (f"gh pr merge {h}/{DB_SLUG}/pull/%33", plain, "deny", merge),      # gh는 경로를 풀어 /pull/N을 찾는다
        (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/%6Derge", plain, "deny", merge),
        (f"gh api {h}/api/%67raphql -f query='{MERGE_MUTATION}'", plain, "deny", merge),
        (f"gh pr merge {h}/{DB_SLUG}$NOPE/pull/3", c, "deny", merge),
        (f"gh pr merge {h}/{DB_SLUG}${{NOPE}}/pull/3", c, "deny", merge),
        (f"gh pr merge {h}/{DB_SLUG}`true`/pull/3", c, "deny", merge),
        (f"gh pr review {h}/{DB_SLUG}$NOPE/pull/3 --approve", wt, "deny", approve),
        (f"gh pr merge 3 -R {DB_SLUG}$NOPE", plain, "deny", merge), (f"gh pr merge 3 -R {DB_SLUG}`true`", plain, "deny", merge),
        (f'gh pr merge 3 -R "$(echo {DB_SLUG})"', plain, "deny", merge),
        (f"GH_REPO={DB_SLUG}$NOPE gh pr merge 3", plain, "deny", merge),
        (f"export GH_REPO={DB_SLUG}; gh pr merge 3", plain, "deny", merge),
        (f"export GH_REPO={DB_SLUG} && gh pr review 3 --approve", plain, "deny", approve),
        (f"export GH_REPO={DB_SLUG}; gh pr edit 3 --add-label x", plain, "ask", None),
        ("export GH_REPO=other/x; gh pr merge 3", plain, None, None),
        ("gh api -X PUT repos/mock-org/telephony%2Dissue-db/pulls/3/merge", c, "deny", merge),
        ("gh api repos/mock-org/telephony%2Dissue-db/pulls/3/reviews -f event=APPROVE", plain, "deny", approve),
        (f"gh api -X PUT repos/{DB_SLUG}$NOPE/pulls/3/merge", plain, "deny", merge),
        # ④ 한 칸만 자리표시(gh가 GH_REPO·cwd 레포로 그 칸을 채운다)
        ("gh api -X PUT 'repos/{owner}/telephony-issue-db/pulls/3/merge'", same, "deny", merge),
        ("gh api 'repos/{owner}/telephony-issue-db/pulls/3/reviews' -f event=APPROVE", same, "deny", approve),
        ("gh api -X PUT repos/:owner/telephony-issue-db/pulls/3/merge", same, "deny", merge),
        ("gh api -X PUT '/repos/{owner}/telephony-issue-db/pulls/3/merge'", same, "deny", merge),
        ("gh api -X POST 'repos/{owner}/telephony-issue-db/pulls/3/reviews/9/dismissals' -f message=x", same, "deny", dismiss),
        ("gh api 'repos/{owner}/telephony-issue-db/pulls/3/reviews/9/events' -f event=APPROVE", same, "deny", approve),
        ("GH_REPO=mock-org/x gh api -X PUT 'repos/{owner}/telephony-issue-db/pulls/3/merge'", plain, "deny", merge),
        ("gh api -X PUT 'repos/mock-org/{repo}/pulls/3/merge'", fork, "deny", merge),
        ("gh api -X PATCH 'repos/{owner}/telephony-issue-db/pulls/3' -f state=closed", same, "ask", None),
        ("gh api 'repos/{owner}/telephony-issue-db/issues/3/comments' -f body=x", same, "ask", None),
        ("gh api -X PUT 'repos/{owner}/{repo}/pulls/3/merge'", same, None, None),
        ("gh api 'repos/{owner}/other/issues' -f title=x", same, None, None),
        # 오탐 방지: 이슈 DB 읽기, 코멘트 리뷰, 이슈 DB가 아닌 cwd의 보통 gh
        ("gh pr view 3", c, None, None), ("gh pr view 3 --json reviews,reviewDecision", wt, None, None),
        ("gh pr list --state open", c, None, None), ("gh pr diff 3", c, None, None), ("gh pr checks 3", c, None, None),
        ("gh pr status", c, None, None), (f"gh api repos/{DB_SLUG}/pulls/3/reviews", c, None, None),
        (f"gh api -X GET repos/{DB_SLUG}/pulls/3/reviews -f per_page=100", c, None, None),
        ("gh api 'repos/{owner}/{repo}/pulls/3/reviews' --jq '.[].state'", c, None, None),
        ("gh api graphql -f query='query { repository(owner:\"mock-org\", name:\"telephony-issue-db\") "
         "{ pullRequest(number:3) { reviews(states: APPROVED) { totalCount } } } }'", c, None, None),
        ("gh pr review 3 --comment -b x", c, "ask", None), ("gh pr review 3 -c -b x", wt, "ask", None),
        ("gh pr create -t x -b y", plain, None, None), ("gh pr comment 3 -b hi", plain, None, None),
        ("gh pr merge 3 --squash", plain, None, None), ("gh pr review 3 --approve", plain, None, None),
        ("gh pr create -t x -b y", same, None, None), ("gh pr merge 3", same, None, None),
        ("gh issue list", plain, None, None), ("gh auth status", plain, None, None)]
    try:
        for cmd, cwd, want, why in rows:
            out = bash(ws, cmd, cwd)
            assert decision(out) == want, (cmd, cwd)
            assert why is None or why in out["permissionDecisionReason"], cmd
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_gh_ssh_alias_remote_and_unknown_value_options_keep_cwd():
    """규칙 11(H-A1 r4): `issue_db.remote`가 SSH 별칭 host(`git@ghe-ssh:…`)여도 gh가 찍는 https PR URL·`-R`은 owner/repo로
    이슈 DB다. 값 받는 옵션 표(`GH_SEL_SHORT_WITH_ARG`)에 없는 동작은 `=` 없는 옵션 바로 뒤의 `-R…` 꼴을 그 옵션의 값으로 보고
    cwd(이슈 DB) 판정을 막지 않는다(`label create -d -Rother/x` 등). 옵션 뒤가 아닌 `-R…`은 그대로 대상이다."""
    ws = Workspace(build=False)
    for p in ws.home.rglob("*.yaml"):
        text = p.read_text(encoding="utf-8")
        p.write_text(text.replace(f"https://ghe.mock.invalid/{DB_SLUG}.git", f"git@ghe-ssh:{DB_SLUG}.git"), encoding="utf-8")
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    alias_repo = _repo_with_origin(f"git@ghe-ssh:{DB_SLUG}.git")
    url = f"https://ghe.mock.invalid/{DB_SLUG}/pull/3"
    wt = ws.work / "wt-alias"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [(f"gh pr merge {url} --squash", c, "deny"), (f"gh pr merge {url} --squash", wt, "deny"),
            (f"gh pr merge {url} --squash", alias_repo, "deny"), (f"gh pr review {url} --approve", c, "deny"),
            (f"gh pr review {url} -a", wt, "deny"), (f"gh pr edit {url} --add-label x", c, "ask"),
            (f"gh pr edit {url} --add-label x", plain, "ask"), (f"gh pr merge 3 -R ghe.mock.invalid/{DB_SLUG}", c, "deny"),
            ("gh pr merge 3", alias_repo, "deny"), ("gh pr comment 3 -b x", alias_repo, "ask"),
            ("gh pr view 3", plain, None), (f"gh pr view {url}", c, None),
            # 표에 없는 동작의 값 받는 옵션 뒤 `-R…`
            ("gh label create bug -d -Rother/x", c, "ask"), ("gh secret set TOKEN -e -Rother/x -b v", wt, "ask"),
            ("gh release create v2 --notes '-Reworked parsers/masking'", c, "ask"),
            ("gh label create x --description '-Resolved in data/x'", c, "ask"),
            ("gh label create bug -d -Rother/x", alias_repo, "ask"),
            ("gh release create v2 --target -Rother/x", c, "ask"),
            ("gh release create v2 --discussion-category -Rother/x", c, "ask"),
            ("gh label edit bug --description -Rother/x", c, "ask"), ("gh repo edit --description -Rother/x", c, "ask"),
            ("gh variable set V -e -Rother/x -b v", c, "ask"), ("gh workflow run w.yml --ref -Rother/x", c, "ask"),
            # 옵션 뒤가 아니거나 표의 bool 옵션 뒤면 그대로 대상(gh가 그 레포를 쓴다)
            ("gh label create bug -Rother/x", c, None), ("gh run cancel 5 -Rother/x", c, None),
            ("gh pr create -t x --draft -Rother/x", c, None), ("gh label create bug -d x -Rother/x", c, None),
            ("gh pr comment 3 --edit-last -Rother/x", c, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


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
    cmds = [("gh pr merge 3 --squash", "머지"), ("gh pr review 3 --approve", "Approve하지 않는다"),
            (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", "머지"), ("git push origin HEAD:main", "규칙 6"),
            ("git checkout main", "규칙 8")]
    for form in forms:
        for x, why in cmds:
            out = bash(ws, form.format(x=x), c)
            assert decision(out) == "deny" and why in out["permissionDecisionReason"], form.format(x=x)
    nl = "\\\n  "
    rows = [(f"if true; then gh pr comment 3 -b hi -R {DB_SLUG}; fi", plain, "ask"),
            (f'm() {{ gh pr merge "$@" -R {DB_SLUG}; }}; m 3', plain, "deny"),
            ("gh 2>/dev/null pr merge 3", c, "deny"), ("git 2>&1 push origin HEAD:main", c, "deny"),
            # 줄 이음(GitHub REST 문서 꼴)
            ((f'gh api {nl}--method PUT {nl}-H "Accept: application/vnd.github+json" {nl}/repos/{DB_SLUG}/pulls/3/merge '
              f'{nl}-f "merge_method=squash"'), plain, "deny"),
            (f'gh api {nl}--method POST {nl}/repos/{DB_SLUG}/pulls/3/reviews {nl}-f "event=APPROVE"', plain, "deny"),
            (f"gh api {nl}--method PUT {nl}/repos/{DB_SLUG}/pulls/3/reviews/9/dismissals {nl}-f message=x", plain, "deny"),
            (f"gh api {nl}graphql {nl}-f query='{MERGE_MUTATION}'", plain, "deny"),
            (f"gh api {nl}-X POST {nl}repos/{DB_SLUG}/issues/3/comments {nl}-f body=hi", plain, "ask"),
            (f"gh {nl}pr merge 3 --squash", c, "deny"), (f"gh pr {nl}merge 3", c, "deny"), (f"git {nl}push origin HEAD:main", c, "deny"),
            (f"gh api {nl}-X PUT {nl}'repos/{{owner}}/{{repo}}/pulls/3/merge'", c, "deny"),
            ("echo x # 메모 \\\ngh pr merge 3", c, "deny"),             # 주석 끝 `\`는 줄을 잇지 않는다
            ("gh api graphql -f query='query { viewer \\\n { login } }'", plain, None),   # 작은따옴표 안 줄 이음은 글자
            # `$'…'`
            ("echo $'it\\'s'; gh pr merge 3 --squash", c, "deny"), ("gh pr $'merge' 3", c, "deny"),
            (f"gh api -X PUT $'repos/{DB_SLUG}/pulls/3/merge'", plain, "deny"),
            # 오탐 방지: 글 명령 안의 낱말, 이슈 DB 읽기
            (f"echo then gh pr merge 3 -R {DB_SLUG}", plain, None), ("grep -n 'do gh pr merge' notes.md", plain, None),
            ("if true; then gh pr view 3; fi", c, None), ("for n in 3 4; do gh pr view $n --json state; done", c, None)]
    for cmd, cwd, want in rows:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)


def test_guard_gh_shell_expanded_operations_are_closed():
    """규칙 11(H-A1 r5): 셸이 정하는 동작은 모른다 — 닫힌 쪽. GraphQL은 Bash 명령 글 전체(heredoc 본문 포함)에서 병합·Approve·
    기각 이름을 찾는다(`query="$(cat <<'EOF' …)"`·`Q=…; -f query="$Q"`·파이프 stdin·같은 명령에서 쓴 파일). 읽지 못한 본문은 대상과
    무관하게 ask, 리뷰 mutation의 event 변수가 셸 값이면 Approve. REST는 셸이 푼 엔드포인트의 쓰기(끝 칸이 셸 값이거나 병합·리뷰
    꼴)를 거부, 리뷰 엔드포인트의 `event="$E"`는 Approve. 그룹·`pr` 동작이 셸 값이면 거부, `pr review`의 옵션 자리 셸 값은
    Approve. 작은따옴표 안 GraphQL 변수(`$o`)·인용한 선택자·옵션 값은 그대로다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    (plain / "q.graphql").write_text("query { viewer { login } }", encoding="utf-8")
    hd = "gh api graphql -f query=\"$(cat <<'EOF'\n{q}\nEOF\n)\""
    approve, merge, dyn = "Approve하지 않는다", "머지", "셸이 푸는 값"
    rows = [(hd.format(q=MERGE_MUTATION), plain, "deny", merge),
            (hd.format(q="mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }"), c, "deny", merge),
            (hd.format(q=APPROVE_MUTATION), plain, "deny", approve),
            (f"Q='{MERGE_MUTATION}'; gh api graphql -f query=\"$Q\"", plain, "deny", merge),
            (f"echo '{MERGE_MUTATION}' | gh api graphql -F query=@-", plain, "deny", merge),
            (f"cat > m.graphql <<'E'\n{MERGE_MUTATION}\nE\ngh api graphql -F query=@m.graphql", plain, "deny", merge),
            (("gh api graphql -f query='mutation($id:ID!,$e:PullRequestReviewEvent!){addPullRequestReview(input:"
              "{pullRequestId:$id,event:$e}){clientMutationId}}' -f id=x -f e=\"$E\""), plain, "deny", approve),
            ('gh api graphql -f query="$(cat none.graphql)"', plain, "ask", "GraphQL 본문을 읽지 못했다"),
            ("cat x.graphql | gh api graphql -F query=@-", plain, "ask", "GraphQL 본문을 읽지 못했다"),
            # 글자를 알 수 있는 셸 본문은 읽는다: heredoc 본문·있는 파일
            (hd.format(q="query { viewer { login } }"), c, None, None),
            ('gh api graphql -f query="$(cat q.graphql)"', plain, None, None),
            (hd.format(q='mutation { addPullRequestReview(input: {pullRequestId: "x", event: COMMENT}) { clientMutationId } }'), c,
             "ask", None),
            (("gh api graphql -f query='mutation($id:ID!){addPullRequestReview(input:{pullRequestId:$id,event:COMMENT})"
              "{clientMutationId}}' -f id=\"$ID\""), plain, None, None),
            ("gh api graphql -f query='query($o:String!){ repository(owner:$o, name:\"x\"){ id } }' -f o=\"$OWNER\"", plain,
             None, None),
            ("gh api graphql -fquery='query($o:String!){ repository(owner:$o, name:\"x\"){ id } }' -f o=x", plain, None, None),
            # REST
            (f"EP=repos/{DB_SLUG}/pulls/3/merge; gh api -X PUT \"$EP\"", plain, "deny", dyn),
            ('gh api -X POST "$EP" -f event=APPROVE', plain, "deny", dyn),
            (f'BASE=repos/{DB_SLUG}; gh api -X PUT "$BASE/pulls/3/merge"', plain, "deny", merge),
            ('gh api -X PUT "$PR/merge"', plain, "deny", dyn),
            ('gh api "$URL/reviews" -f event=APPROVE', plain, "deny", approve),
            ('gh api "$URL/reviews" -f event=COMMENT', plain, "ask", None),       # 레포를 몰라 어디서나 ask
            ('gh api -X PUT "repos/{owner}/{repo}/pulls/$N/merge"', c, "deny", merge),
            ('gh api -X PUT "repos/{owner}/{repo}/pulls/$N/merge"', plain, None, None),
            ('gh api -X PUT "repos/other/x/pulls/3/$A"', c, "deny", dyn), ('gh api -X PUT "repos/other/x/pulls/3/$A"', plain, None, None),
            (f'gh api repos/{DB_SLUG}/pulls/3/reviews -f event="$E"', plain, "deny", approve),
            (f'gh api "repos/{DB_SLUG}/issues/$N/comments" -f body=x', plain, "ask", None),
            ('gh api "$EP"', plain, None, None),
            # 그룹·동작·리뷰 옵션
            ("gh pr $ACT 3", c, "deny", dyn), (f'gh pr "$ACT" 3 -R {DB_SLUG}', plain, "deny", dyn),
            ('gh "$G" merge 3', c, "deny", dyn), (f'gh "$G" -X PUT repos/{DB_SLUG}/pulls/3/merge', plain, "deny", dyn),
            (f'gh issue "$A" 5 -R {DB_SLUG}', plain, "ask", None), ("gh pr $ACT 3", plain, None, None),
            ('gh pr review 3 "$OPT"', c, "deny", approve), (f"gh pr review 3 $OPT -R {DB_SLUG}", plain, "deny", approve),
            ("gh pr review 3 --comment -b $B", c, "deny", approve),
            ('gh pr review "$N" --comment -b "$B"', c, "ask", None), ('gh pr review $n --comment --body="$B"', c, "ask", None),
            ('gh pr view "$N" --json state', c, None, None)]
    for cmd, cwd, want, why in rows:
        out = bash(ws, cmd, cwd)
        assert decision(out) == want, (cmd, cwd)
        assert why is None or why in out["permissionDecisionReason"], cmd


def _repo_with_remotes(remotes: list[tuple[str, str]], config: tuple = ()) -> Path:
    path = tmp("tt-gh-repo-") / "r"
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    for name, url in remotes:
        subprocess.run(["git", "-C", str(path), "remote", "add", name, url], check=True)
    for key, value in config:
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    return path


def test_guard_gh_cwd_resolution_remotes_gitdir_and_unknown_dirs():
    """규칙 11(H-A1 r5): cwd 레포는 gh처럼 넓게 본다 — 원격 하나라도(upstream·이름 있는 원격·insteadOf를 푼 URL)·`gh-resolved`
    값·앞 대입 `GIT_DIR`이 이슈 DB면 대상. 모르는 cwd(셸이 풀 경로·`cd $(…)`·없는 경로·셸이 푸는 `GIT_DIR`)는 이슈 DB로 본다(병합·
    Approve는 거부, 쓰기는 ask, 사유를 붙인다). `cd -`·`pushd`/`popd`는 이 명령 글 안에서 따라간다. 읽기는 그대로다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    db, other = f"https://ghe.mock.invalid/{DB_SLUG}", "https://ghe.mock.invalid/jdoe/telephony-issue-db"
    fork = _repo_with_remotes([("origin", other), ("upstream", db)])
    named = _repo_with_remotes([("db", db)])
    resolved = _repo_with_remotes([("origin", other)], (("remote.origin.gh-resolved", DB_SLUG),))
    alias = _repo_with_remotes([("origin", "dbx:telephony-issue-db")], (("url.https://ghe.mock.invalid/mock-org/.insteadOf", "dbx:"),))
    unrelated = _repo_with_remotes([("origin", other)])
    unknown = "알 수 없어"
    rows = [("gh pr merge 3 --squash", fork, "deny", "머지"), ("gh pr review 3 --approve", fork, "deny", "Approve"),
            ("gh pr comment 3 -b hi", fork, "ask", None), ("gh pr merge 3", named, "deny", None),
            ("gh pr merge 3", resolved, "deny", None), ("gh pr merge 3", alias, "deny", None),
            ("gh pr merge 3", unrelated, None, None), ("gh pr view 3", fork, None, None),
            (f"GIT_DIR={c}/.git gh pr merge 3 --squash", plain, "deny", None),
            (f"GIT_DIR={c}/.git gh pr review 3 --approve", plain, "deny", "Approve"),
            (f"GIT_DIR={fork}/.git gh pr comment 3 -b hi", plain, "ask", None),
            ('GIT_DIR="$G" gh pr merge 3', plain, "deny", unknown),
            (f'D={c}; cd "$D" && gh pr merge 3 --squash', plain, "deny", unknown),
            (f"cd $(git -C {c} rev-parse --show-toplevel) && gh pr merge 3", plain, "deny", unknown),
            (f"gh repo clone {DB_SLUG} {plain}/x && cd {plain}/x && gh pr merge 3", plain, "deny", unknown),
            (f"cd {plain}/nope && gh pr comment 3 -b hi", plain, "ask", unknown),
            (f"cd {c}; cd /tmp; cd -; gh pr merge 3", plain, "deny", "머지"),
            (f"cd {c}; cd /tmp; cd -; git checkout main", plain, "deny", "규칙 8"),
            (f"pushd {c} >/dev/null && gh pr merge 3", plain, "deny", None),
            # 오탐 방지: 읽기, 따라갈 수 있는 디렉토리
            (f'D={c}; cd "$D" && gh pr view 3', plain, None, None), (f"cd {plain}/nope && gh pr view 3", plain, None, None),
            (f"cd {c} && cd {plain} && gh pr merge 3", plain, None, None), (f"pushd {c} && popd && gh pr merge 3", plain, None, None)]
    for cmd, cwd, want, why in rows:
        out = bash(ws, cmd, cwd)
        assert decision(out) == want, (cmd, cwd)
        assert why is None or why in out["permissionDecisionReason"], cmd


def test_guard_gh_pr_read_list_aliases_and_repo_positional_targets():
    """규칙 11(H-A1 r5): `pr`은 읽기 목록(list·view·status·checks·diff)만 읽기다(`revert`·`update-branch`·모르는 동작은 쓰기).
    동작 별칭(`new`·`ls`·`co`)과 gh 기본 별칭 `gh co`(= `pr checkout`, 규칙 8)를 풀어 본다. `repo <동작> [<레포>]`의 위치 인자와
    `issue transfer`의 대상 레포는 명시 대상이다(URL 꼴 포함). 다른 레포를 가리키는 `repo` 위치 인자는 cwd 판정을 끈다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    rows = [(f"gh pr revert 3 -R {DB_SLUG}", plain, "ask"), ("gh pr revert 3", c, "ask"),
            (f"gh pr new -R {DB_SLUG} -t x -b y", plain, "ask"), (f"gh pr update-branch 3 -R {DB_SLUG}", plain, "ask"),
            ("gh pr co 3", c, "deny"), ("gh co 3", c, "deny"),
            (f"gh repo edit {DB_SLUG} --default-branch dev", plain, "ask"),
            (f"gh repo edit {DB_SLUG} --enable-auto-merge", plain, "ask"),
            (f"gh repo delete {DB_SLUG} --yes", plain, "ask"), (f"gh repo archive {DB_SLUG} -y", plain, "ask"),
            (f"gh repo sync {DB_SLUG} --source mock-org/other --branch main --force", plain, "ask"),
            (f"gh repo edit https://ghe.mock.invalid/{DB_SLUG} --default-branch dev", plain, "ask"),
            (f"gh issue transfer 5 {DB_SLUG}", plain, "ask"), ("gh issue transfer 5 other/x", c, "ask"),
            ("gh repo edit --description other/x", c, "ask"),        # 앞 옵션의 값일 수 있다 — cwd 판정이 남는다
            # 오탐 방지
            (f"gh pr ls -R {DB_SLUG}", plain, None), (f"gh issue ls -R {DB_SLUG}", plain, None),
            (f"gh release ls -R {DB_SLUG}", plain, None), (f"gh pr checks 3 -R {DB_SLUG}", plain, None),
            ("gh pr co 3", plain, None), (f"gh repo view {DB_SLUG}", plain, None), (f"gh repo clone {DB_SLUG}", plain, None),
            ("gh repo edit other/x --description y", c, None), ("gh repo create acme/new --private", c, None),
            ("gh issue transfer 5 other/x", plain, None), ("gh repo rename newname", plain, None)]
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
    rows = [
        # 서브셸·치환·파이프·백그라운드 안의 cd는 이슈 DB worktree·clone의 병합·Approve를 가리지 않는다
        ("(cd /tmp && ls) ; gh pr merge 3 --squash", wt, "deny"),
        ("(cd /tmp && ls) && gh pr merge 3 --auto --squash", wt, "deny"),
        (f"(cd {other} && git log -1) && gh pr review 3 --approve", wt, "deny"),
        (f"(cd {other}) ; gh pr merge 3", c, "deny"),
        (f"cd {other} | cat; gh pr merge 3 --squash", c, "deny"),
        (f"cat /dev/null | cd {other}; gh pr merge 3", c, "deny"),
        (f"echo $(cd {other} && pwd); gh pr merge 3 --squash", c, "deny"),
        (f"diff <(cd {other}; ls) x; gh pr merge 3", c, "deny"),
        (f"cd {other} && ls & gh pr merge 3", c, "deny"),
        (f"{{ cd {other}; }} | cat; gh pr merge 3", c, "deny"),
        (f"ls | while read l; do cd {other}; done; gh pr merge 3", c, "deny"),
        (f"for d in a; do cd {other}; done | cat; gh pr review 3 --approve", c, "deny"),
        (f"(cd {other} && ls) ; gh pr create -t x -b y", wt, "ask"),
        # 조건부·분기·함수 본문: 돌지 않았을 수 있다 — 전 cwd도 본다
        (f"false && cd {other}; gh pr merge 3", c, "deny"),
        (f"if test -d x; then cd {other}; fi; gh pr merge 3", c, "deny"),
        (f"case $X in a) cd {other};; esac; gh pr merge 3", c, "deny"),
        (f"f() {{ cd {other}; }}; gh pr merge 3", c, "deny"),
        (f"f() {{ cd {c}; }}; cd {plain}; f; gh pr merge 3", plain, "deny"),     # 부르면 돈다 — 모르는 cwd
        ("echo x) ; gh pr merge 3", plain, "deny"),                              # 짝 없는 `)`: 모르는 cwd
        (f"X='cd {c}'; eval \"$X\"; gh pr merge 3", plain, "deny"),            # 셸 값 eval·source: cd할 수 있다
        ("source ./env.sh && gh pr merge 3", plain, "deny"), ("source ./env.sh && gh pr view 3", plain, None),
        (f"CDPATH={c.parent} cd {c.name}; gh pr merge 3", plain, "deny"),        # CDPATH에서 먼저 찾는다
        # 셸이 읽는 heredoc 본문: 앞에서 거친 cwd로도 본다
        (f"cd {c} && bash <<'EOF'\ngh pr merge 3\nEOF", plain, "deny"),
        # 다른 레포에서 서브셸로 이슈 DB에 들어갔다 나오면 대상이 아니다
        (f"(cd {wt} && ls) ; gh pr merge 3 --squash", other, None),
        (f"echo $(cd {c} && pwd); gh pr merge 3", plain, None),
        (f"cd {c} | cat; gh pr merge 3", plain, None),
        # bash처럼 남는 cd는 그대로 따라간다
        (f"cd {other} && ls ; gh pr merge 3", c, None),
        (f"{{ cd {other}; }} ; gh pr merge 3", c, None),
        (f"cd {other} && gh pr merge 3", wt, None),
        (f"eval 'cd {c}'; gh pr merge 3", plain, "deny"),
        (f"builtin cd {c}; gh pr merge 3", plain, "deny"),
        (f"cd {c}; (gh pr merge 3)", plain, "deny"),
        # git 규칙도 같은 cwd를 쓴다
        (f"(cd {other} && ls); git push origin HEAD:main", c, "deny"),
        (f"git -C {other} log | cd {other}; git push origin HEAD:main", c, "deny")]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_cwd_moves_that_can_fail_keep_previous_candidates():
    """명령 파싱(회귀 수정 R1): 실패할 수 있거나 대상을 모르는 이동은 이전 cwd 후보를 버리지 않는다. 모르는 디렉토리는 규칙 11에선
    이슈 DB일 수 있는 것이지만 git 규칙(3~8·12)에선 판정하지 못하는 후보라, 이전 후보를 버리면 이슈 DB clone·worktree에서 도는
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
        ("popd; git push origin HEAD:main", c, "deny"), ("popd; git push origin HEAD:main", wt, "deny"),
        ("popd 2>/dev/null; git checkout -b x", c, "deny"), ("popd; git reset --hard origin/main", c, "deny"),
        ("popd; echo x > notes.txt", c, "deny"), ("popd; git commit --no-verify -m x", c, "deny"),
        ("popd; git commit --no-verify -m x", wt, "deny"), ("popd; git push --no-verify origin HEAD:issue/x", wt, "deny"),
        ("popd; gh pr merge 3", plain, "deny"),                       # 규칙 11은 모르는 cwd(이슈 DB일 수 있다) 그대로
        # popd -n·+N(N≥1)·pushd -n: cwd를 바꾸지 않는다
        (f"pushd {c} >/dev/null; popd -n; git push origin HEAD:main", plain, "deny"),
        (f"pushd {c} >/dev/null; popd -n; gh pr merge 3", plain, "deny"),
        (f"pushd {c} >/dev/null; popd +1; git push origin HEAD:main", plain, "deny"),
        ("pushd -n /tmp; git push origin HEAD:main", c, "deny"),
        (f"pushd -n {c}; popd; git push origin HEAD:main", plain, "deny"),   # -n으로 넣은 칸으로 popd
        # 인자 없는 pushd·pushd ±N·이전 디렉토리를 모르는 cd -·cd ±N: 실패하거나 모르는 칸
        ("pushd; git push origin HEAD:main", c, "deny"), ("pushd +1; git push origin HEAD:main", c, "deny"),
        ("cd -; git push origin HEAD:main", c, "deny"), ("cd -1; git push origin HEAD:main", c, "deny"),
        ("popd -0; git push origin HEAD:main", c, "deny"),
        # 분기로 스택을 모르게 되면 뒤 popd는 스택 칸·이전 후보 모두
        ("if test -d x; then pushd /tmp; fi; popd; git push origin HEAD:main", c, "deny"),
        (f"pushd {c} && pushd /tmp; popd; git push origin HEAD:main", plain, "deny"),
        # 없는 경로·셸이 풀 경로: cd가 실패하면 cwd 그대로(`||` 뒤는 실패한 경우다)
        (f"cd {plain}/nope; git push origin HEAD:main", c, "deny"),
        ('cd "$D"; git checkout -b x', c, "deny"),
        (f"cd {plain}/nope || git push origin HEAD:main", c, "deny"),
        (f"cd {plain}/nope && ls || git push origin HEAD:main", c, "deny"),
        # 오탐 방지: 따라갈 수 있는 스택은 그대로 따라간다, `&&` 뒤는 cd가 성공한 경우뿐이다
        (f"pushd {plain} >/dev/null; popd; git push origin HEAD:main", c, "deny"),
        (f"pushd {plain} >/dev/null; popd -n; git push origin HEAD:main", c, None),
        (f"pushd {plain} >/dev/null; popd +0; git push origin HEAD:main", c, "deny"),
        (f"pushd {plain} >/dev/null; pushd; git push origin HEAD:main", c, "deny"),
        (f"pushd {c} >/dev/null; pushd; git push origin HEAD:main", plain, None),
        (f"pushd {c} >/dev/null; popd +0; gh pr merge 3", plain, None),
        (f"cd {plain}; popd -n; git push origin HEAD:main", c, None),
        (f"cd {plain}/nope && git push origin HEAD:main", c, None),
        (f"pushd {c} && popd && gh pr merge 3", plain, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_cwd_candidate_overflow_keeps_first_and_latest():
    """명령 파싱(회귀 수정 R4): cwd 후보가 상한(`CWD_CAP`)을 넘으면 처음 후보와 가장 최근 후보들을 남기고 가운데를 모르는
    디렉토리로 접는다 — 넘침이 마지막 cd 대상(이슈 DB clone)을 버리지 않는다. 접힌 후보는 규칙 11에서 모르는 cwd로 남는다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    subs = [plain / f"d{i}" for i in range(9)]
    for d in subs:
        d.mkdir()
    chain = "; ".join(f"true && cd {d}" for d in subs[:7])
    arms = " ".join(f"{chr(97 + i)}) cd {d};;" for i, d in enumerate(subs[:7]))
    rows = [(f"{chain}; true && cd {c}; git push origin HEAD:main", plain, "deny"),
            (f"case $X in {arms} h) cd {c};; esac; git push origin HEAD:main", plain, "deny"),
            (f"{chain}; true && cd {subs[7]}; true && cd {subs[8]}; git push origin HEAD:main", c, "deny"),   # 처음 cwd
            (f"{chain}; true && cd {subs[7]}; true && cd {subs[8]}; gh pr merge 3", plain, "deny"),          # 접힌 후보
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
    = `ac`), 서로게이트(`\\ud800`)는 U+FFFD다. 명령 글의 날 NUL은 빼고 짝 없는 서로게이트는 U+FFFD다. 경로 연산이 예외를 내도
    그 검사만 판정하지 못한 것(ask)으로 보고 다른 검사를 이어 간다 — 같은 명령의 병합·main push·--no-verify가 내부 오류 판정
    (ask)으로 약해지지 않는다. 출력은 ASCII JSON이라 사유에 인코딩할 수 없는 글자가 들어도 종료 0이다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    wt = ws.work / "wt-ansic"
    git(c, "worktree", "add", "-q", "--detach", str(wt), "origin/main")
    rows = [("cat $'\\x00x'; gh pr merge 3 --squash", c, "deny", "머지"),
            ("cat $'\\0'; git push origin HEAD:main", wt, "deny", "규칙 6"),
            ("cat $'\\ud800'; gh pr merge 3", wt, "deny", "머지"),
            ("echo hi > $'\\0x'; gh pr merge 3", wt, "deny", "머지"),
            ("cat $'\\0'; git commit --no-verify -m x", c, "deny", "규칙 5"),
            ("cat $'\\c@'; git push origin HEAD:main", c, "deny", "규칙 6"),
            ("cat $'\\u0000'; git push origin HEAD:main", c, "deny", "규칙 6"),
            ("cat $'\\000'; git push origin HEAD:main", c, "deny", "규칙 6"),
            ("git config core.hooksPath $'\\ud800'", c, "deny", "규칙 5"),
            # bash는 NUL 뒤를 버린다: 낱말이 그 앞까지다
            ("git $'push\\0junk' origin HEAD:main", c, "deny", "규칙 6"),
            ("gh pr $'merge\\x00x' 3", c, "deny", "머지"), ("git push origin $'HEAD:main\\0x'", c, "deny", "규칙 6"),
            # 명령 글의 날 NUL·짝 없는 서로게이트(hook 입력 JSON의 \u0000·\ud800)
            ("cat \x00x; gh pr merge 3", c, "deny", "머지"), ("git config core.hooksPath \ud800", c, "deny", "규칙 5"),
            ("echo hi > x\x00y; git push origin HEAD:main", c, "deny", "규칙 6"),
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
    # 경로 연산 예외(여기선 sitecustomize로 일으킨다): 그 검사만 ask, 같은 명령의 다른 검사는 그대로
    env = _raising_realpath_env(ws)
    for cmd, cwd, want, why in [("cat RAISEMARK.log; gh pr merge 3", c, "deny", "머지"),
                                ("echo x > RAISEMARK; git push origin HEAD:main", c, "deny", "규칙 6"),
                                ("echo x > RAISEMARK; git commit --no-verify -m x", c, "deny", "규칙 5"),
                                ("echo x > RAISEMARK", plain, "ask", "규칙 8")]:
        out = bash(ws, cmd, cwd, env=env)
        assert decision(out) == want and why in out["permissionDecisionReason"], (cmd, out)
        assert "내부 오류" not in out["permissionDecisionReason"], cmd


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
    rows = [("echo $'\\c'; git push origin HEAD:main", c, "deny"), ("echo $'\\c'; gh pr merge 3", c, "deny"),
            ("echo $'\\c'; git commit --no-verify -m x", c, "deny"), ("echo $'\\c'; echo x > notes.txt", c, "deny"),
            ("echo $'\\c'; git checkout -b x", c, "deny"), ("echo $'\\c'; git push origin HEAD:main", wt, "deny"),
            ("echo $'\\c\\\\'; git push origin HEAD:main", c, "deny"),
            ("echo $'\\c\\''; git push origin HEAD:main", c, "deny"),
            ("printf %s $'x\\c' && git push origin HEAD:main", c, "deny"),
            ("echo $'\\c'\ngit push origin HEAD:main", c, "deny"),
            ("echo $'\\c'; gh api -X PUT repos/mock-org/telephony-issue-db/pulls/3/merge", plain, "deny"),
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
    hops = "data/../" * 150
    rows = [(f"cd {hops}data; git push origin HEAD:main", wt, "deny"),
            (f"cd {hops}data && git commit --no-verify -m x", wt, "deny"),
            (f"cd {wt}/{hops}; git push origin HEAD:main", plain, "deny"),
            ("cd data; ls; cd ..; " * 120 + "git push origin HEAD:main", wt, "deny"),
            (f"cd {'s/../' * 220}; echo x > post.approved.json", job, "deny"),
            (f"cd {'s/../' * 220}; echo x > merge-offer.json", job, "deny"),
            (f"cd {'s/../' * 220}; rm -f post.result.json", job, "deny"),
            (f"cd {hops}; git push origin HEAD:main", c, "deny"),
            # 오탐 방지: 길어도 이슈 DB 밖이면 그대로
            (f"cd {deep}; git push origin HEAD:main", plain, None),
            (f"cd {'x/../' * 300}; git push origin HEAD:main", plain, None)]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd[:80], cwd)
    finally:
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
EACCES_SITE = ("import errno, os\n_stat = os.stat\n\n\n"
               "def stat(path, *a, **k):\n"
               "    if not isinstance(path, int) and 'EACCESMARK' in os.fsdecode(path):\n"
               "        raise PermissionError(errno.EACCES, 'Permission denied (test)', os.fsdecode(path))\n"
               "    return _stat(path, *a, **k)\n\n\nos.stat = stat\n")
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
    rows = [(f"gh pr merge 3 --squash; cd {long_abs}", wt, "deny"), (f"git push origin HEAD:main; cd {long_abs}", c, "deny"),
            (f"git commit --no-verify -m x; pushd {long_abs}", c, "deny"),
            (f"cd {long_abs}; cd {c}; git push origin HEAD:main", plain, "deny"),
            (f"cd {long_abs} 2>/dev/null; cd {c} && gh pr merge 3 --squash", plain, "deny"),
            (f"cd {long_abs} 2>/dev/null; cd {c}; echo x > notes.txt", plain, "deny"),
            (f"cd {long_abs} 2>/dev/null; cd {c}; git checkout -b x", plain, "deny"),
            (f"true && cd {long_abs}; cd {c}; git push origin HEAD:main", wt, "deny"),
            (f"(cd {long_abs}); cd {c}; git push origin HEAD:main", plain, "deny"),
            (f"pushd -n {long_abs}; cd {c}; git push origin HEAD:main", plain, "deny"),
            (f"cd {long_abs}; gh pr review 3 --approve", plain, "deny"), (f"cd {long_abs}; gh pr review 3 --approve", c, "deny"),
            (f"echo x > notes.txt; cd {long_abs} || true", c, "deny"),
            (f"git push origin HEAD:main; cd {long_rel}", c, "deny"), (f"git push origin HEAD:main; cd {long_in}", c, "deny"),
            (f"cd {long_in}; git push origin HEAD:main", c, "deny"),         # cd가 실패하면 clone 그대로
            (f"cd {long_abs} 2>/dev/null; ls", plain, None)]
    eacces = _site_env(ws, EACCES_SITE)
    other = "/home/EACCESMARK/proj"
    erows = [(f"gh pr merge 3; cd {other}", wt, "deny"), (f"cd {other}; gh pr review 3 --approve", plain, "deny"),
             (f"echo x > notes.txt; cd {other} || true", c, "deny"), (f"cd {other}; gh pr merge 3", wt, "deny"),
             (f"cd {other} 2>/dev/null; cd {c}; git push origin HEAD:main", plain, "deny"),
             (f"pushd {other} >/dev/null 2>&1; cd {c} && gh pr merge 3 --squash", plain, "deny"),
             (f"cd {other}; git push origin HEAD:main", c, "deny"), (f"cd {other}; ls", plain, None)]
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
    """명령 파싱(재리뷰 P0): 명령 걷기(`invocations`) 자체가 예외로 끝나도 판정 전체를 내부 오류로 보내지 않는다 — ask("명령 파싱")와
    낱말 수준 거부(gh와 병합·Approve·리뷰·기각·GraphQL·별칭·셸 값 낱말)를 남기고, cd를 따라가지 않는 대체 목록(처음 cwd·cd 절대
    대상·모르는 디렉토리)으로 다른 검사를 이어 간다. 의존성 없음 판정(`_degraded`)도 걷기가 예외면 낱말 수준으로 병합을 거부한다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    env = _site_env(ws, WALK_SITE)
    for cmd, cwd, want, why in [("env -C WALKRAISE true; gh pr merge 3", plain, "deny", "명령을 풀지 못해"),
                                ("env -C WALKRAISE true; git push origin HEAD:main", c, "deny", "규칙 6"),
                                ("env -C WALKRAISE true; git commit --no-verify -m x", c, "deny", "규칙 5"),
                                (f"env -C WALKRAISE true; cd {c}; git push origin HEAD:main", plain, "deny", "규칙 6"),
                                ("env -C WALKRAISE true; ls", plain, "ask", "명령 파싱"),
                                ("env -C WALKRAISE true; gh pr view 3", plain, "ask", "명령 파싱")]:
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
        proc = run("guard.py", [], root=ws.root, cwd=cwd, env=env, stdin=json.dumps(event))
        assert proc.returncode == 0 and "내부 오류" not in proc.stderr, (cmd, proc.stderr)
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert decision(out) == want and why in out["permissionDecisionReason"], (cmd, out)
    env = _site_env(ws, WALK_SITE, no_yaml=True)
    for cmd, want in [("env -C WALKRAISE true; gh pr merge 3", "deny"), ("env -C WALKRAISE true; gh pr review 3 -a", "deny"),
                      ("env -C WALKRAISE true; gh pr view 3", "ask"), ("env -C WALKRAISE true; echo hi", None)]:
        event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(plain)}
        proc = run("guard.py", [], root=ws.root, cwd=plain, env=env, stdin=json.dumps(event))
        assert proc.returncode == 0 and "Traceback" not in proc.stderr, (cmd, proc.stderr)
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        assert decision(out) == want, (cmd, out)
        assert want is None or "의존성 없음" in out["permissionDecisionReason"], (cmd, out)


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
    rows = [(f"pushd {c} >/dev/null; dirs -c; popd; gh pr merge 3", plain, "deny"),
            (f"pushd {c} >/dev/null; dirs -c; popd; git push origin HEAD:main", plain, "deny"),
            (f"pushd {c} >/dev/null; dirs -c 2>/dev/null; popd; git commit --no-verify -m x", plain, "deny"),
            (f"pushd {c} >/dev/null; popd -q; gh pr merge 3", plain, "deny"),
            (f"pushd {c}; popd -x; git push origin HEAD:main", plain, "deny"),
            (f"pushd {c} >/dev/null; popd -q; echo x > notes.txt", plain, "deny"),
            (f"pushd {c} >/dev/null; DIRSTACK=(); popd; git push origin HEAD:main", plain, "deny"),
            (f"pushd {c} >/dev/null; pushd -q; git push origin HEAD:main", plain, "deny"),
            (f"pushd -q {c}; git push origin HEAD:main", plain, "deny"),
            ("cd -Q /tmp; git push origin HEAD:main", c, "deny"), ("cd /tmp /usr; git push origin HEAD:main", c, "deny"),
            ("cd -x /tmp && git push origin HEAD:main", c, "deny"), ("pushd -q /tmp; git push origin HEAD:main", c, "deny"),
            ("pushd /tmp /usr; git push origin HEAD:main", c, "deny"),
            # `!` 부정: 뒤 `&&`는 cd가 실패했을 때 돈다
            ("! popd && git push origin HEAD:main", c, "deny"), ("! popd && git commit --no-verify -m x", c, "deny"),
            ("! cd /nonexist && git push origin HEAD:main", c, "deny"),
            ("! cd nosub 2>/dev/null && git push origin HEAD:main", c, "deny"),
            ('! cd "$D" && git checkout -b x', c, "deny"), ("! pushd /nonexist && git reset --hard origin/main", c, "deny"),
            ("time ! cd /nonexist && git push origin HEAD:main", c, "deny"), ("! cd - && git push origin HEAD:main", c, "deny"),
            ("! cd /nonexist && echo x > notes.txt", c, "deny"), ("! cd /nonexist && git push origin HEAD:main", wt, "deny"),
            ("if ! cd /nonexist && git push origin HEAD:main; then :; fi", c, "deny"),
            # 오탐 방지: bash cd 옵션(-L·-P·-e·-@·--)과 인자 없는 dirs는 그대로 따라간다, 부정 없는 `&&` 뒤는 cd가 성공한 경우뿐이다
            ("cd -P /tmp; git push origin HEAD:main", c, None), ("cd -LP /tmp; git push origin HEAD:main", c, None),
            ("cd -e -P /tmp; git push origin HEAD:main", c, None), ("cd -- /tmp; git push origin HEAD:main", c, None),
            (f"pushd {c} >/dev/null; dirs; popd; git push origin HEAD:main", plain, None),
            (f"pushd {plain} >/dev/null; dirs -v; popd -n; git push origin HEAD:main", c, None),     # -n: cwd 그대로
            ("cd /nonexist && git push origin HEAD:main", c, None)]
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
    rows = [(f"cd {c} || cd /tmp && git push origin HEAD:main", plain, "deny"),
            ("false && cd /tmp || git push origin HEAD:main", c, "deny"),
            ("test -d x && cd /tmp || git push origin HEAD:main", c, "deny"),
            ("cd .. || pushd -q && cd -\ngit push origin HEAD:main", c, "deny"),
            ("cd /tmp || cd /usr && cd - && git push origin HEAD:main", c, "deny"),
            (f"cd {c} || pushd /tmp && gh pr merge 3", plain, "deny"),
            (f"cd {c} || cd /tmp && echo x > notes.txt", plain, "deny"),
            # if 조건의 cd도 돌았다: else·fi 뒤는 조건의 끝 상태에서도 돈다
            (f"if ! cd {c}; then cd /usr; else true; fi; git push origin HEAD:main", plain, "deny"),
            (f"if ! cd {c}; then cd /usr; fi; git push origin HEAD:main", plain, "deny"),
            (f"if cd {c}; false; then cd /usr; else git push origin HEAD:main; fi", plain, "deny"),
            (f"if false; then :; elif cd {c}; false; then cd /usr; else git push origin HEAD:main; fi", plain, "deny"),
            # 넘침: 처음에 들어간 clone을 접지 않는다
            (f"true && cd {c}; {after}; git push origin HEAD:main", plain, "deny"),
            (f"case $X in 0) cd {c};; {arms} esac; git push origin HEAD:main", plain, "deny"),
            (f'cd "$D" .. && cd -P nosub; {after}; git push origin HEAD:main', c, "deny"),
            # 오탐 방지: 건너뛸 수 없는 경우는 그대로
            ("cd /tmp && git push origin HEAD:main || true", c, None),
            ("cd /tmp && ls || ls && git push origin HEAD:main", c, None),
            ("cd /nonexist && git push origin HEAD:main", c, None),
            ("if test -d x; then cd /usr; else cd /tmp; fi; git push origin HEAD:main", plain, None),
            (f"{after}; git push origin HEAD:main", plain, None)]
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
    nested = f"{cds('n', 8)}\nbash <<EOF\n{body}\nbash <<EOG\n{body}\nEOG\nEOF\ngit push origin HEAD:main"
    first = f"git push origin HEAD:main\n{cds('n', 8)}\nbash <<EOF\n{body}\nbash <<EOG\n{body}\nEOG\nEOF"
    level3 = (f"{cds('n', 8)}\nbash <<EOF\n{cds('m', 60)}\nbash <<EOG\n{cds('q', 60)}\nbash <<EOH\n{cds('p', 60)}\ngit status\n"
              "EOH\nEOG\nEOF\ngit push origin HEAD:main")
    for cmd in (nested, first, level3):
        start = time.monotonic()
        assert decision(bash(ws, cmd, c)) == "deny", cmd[:60]
        assert time.monotonic() - start < 5, (cmd[:60], time.monotonic() - start)     # 예전: 수백 초
    after = "; ".join(f"cd {d}" for d in ("/usr", "/tmp", "/var", "/etc", "/opt", "/srv", "/home", "/usr/bin"))
    rows = [(f"cd {c}; bash <<EOF\ngit push origin HEAD:main\nEOF\n{after}", plain, "deny"),   # 연산자 뒤 cd 8개
            (f"cd {c} && bash <<EOF\ncd sub 2>/dev/null\ngit push origin HEAD:main\nEOF", plain, "deny"),
            (f"(cd {c}; bash <<EOF\ngit push origin HEAD:main\nEOF\n)", plain, "deny"),
            (f"bash <<A; cd {c}; bash <<B\ngit status\nA\ngit push origin HEAD:main\nB", plain, "deny"),
            (f"cd {c}; bash <<EOF\nbash <<EOG\ngit push origin HEAD:main\nEOG\nEOF", plain, "deny"),
            (f"cd {c}; cat <<EOF | sh\necho x > notes.txt\nEOF", plain, "deny"),
            (f"cd {c}; bash <<EOF\ngh pr merge 3\nEOF", plain, "deny"),
            ("echo ; bash <<EOF\ngit push origin HEAD:main\nEOF", c, "deny"),   # 표시 글자가 이미 든 글
            ("cd /tmp && bash <<EOF\ngit push origin HEAD:main\nEOF", plain, None)]
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
        ('rg -n "<<EOF" scripts/ | head -3\ngh pr merge 3 --squash', wt, "deny"),
        ("# 확인: heredoc(<<EOF) 본문 포함\ngh pr review 3 --approve", wt, "deny"),
        ("read -r a <<< word\ngh pr merge 3 --squash", c, "deny"),
        ("git log --oneline -3   # <<HEAD\ngit push origin HEAD:main", c, "deny"),
        ("echo $((1<<X))\ngh pr merge 3 --squash", c, "deny"),
        ("((n <<= 1))\ngh pr merge 3", c, "deny"),
        ("echo '<<EOF'\ngh pr merge 3 --squash", c, "deny"),
        ("echo x # <<EOF\ngh pr merge 3 --auto --squash", c, "deny"),
        (f'true\nrg -n "<<EOF" scripts/\ntrue\n{merge}', c, "deny"),
        ("cat <<EOF\ngh pr merge 3 --squash", c, "deny"),                      # 끝 표시 없음
        ('echo "\n<<EOF\n"; gh pr merge 3\nEOF', c, "deny"),                  # 여러 줄 인용 안 `<<EOF`
        ("cat > f <<EOF\n  EOF\ncd /tmp\nEOF\ngh pr merge 3", c, "deny"),     # 공백 붙은 `  EOF`는 끝 표시가 아니다
        ("cat <<'EOF' | bash\ngh pr merge 3\nEOF", c, "deny"),                # 셸이 읽는 본문은 명령이다
        # 진짜 heredoc 본문은 명령이 아니다(오탐 없음)
        ("cat >/dev/null <<'EOF'\ngh pr merge 3\nEOF", c, None),
        ("cat >/dev/null <<-EOF\n\tgh pr merge 3\n\tEOF", c, None),
        ("cat >/dev/null <<\\EOF\ngh pr merge 3\nEOF", c, None),
        ("cat >/dev/null <<'END-X'\ngh pr merge 3\nEND-X", c, None),
        ("cat <<A >/dev/null <<B\ngh pr merge 3\nA\ngh pr merge 4\nB", c, None),
        ("X=\"$(cat <<'EOF'\ngh pr merge 3\nEOF\n)\"; echo \"$X\"", c, None),
        ("cat <<EOF\nhello\nEOF\ngh pr merge 3 --squash", c, "deny")]
    try:
        for cmd, cwd, want in rows:
            assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    finally:
        gitp(c, "worktree", "remove", "--force", str(wt))


def test_guard_gh_api_shell_resolved_endpoint_may_be_graphql():
    """규칙 11(H-A1 r6): 셸이 푸는 엔드포인트(`"$GHE_API/graphql"`·`$X/graphql`·`"${X}/graphql"`)는 실행 때 GraphQL URL일 수 있다
    (gh는 `://`가 든 경로를 그대로 쓰고 필드를 JSON 본문으로 보낸다). 병합·자동 병합·Approve·기각 mutation은 대상과 무관하게
    거부한다. 끝 칸이 `graphql`이면 읽지 못한 본문은 ask다. 읽기 query·다른 REST 쓰기는 그대로다."""
    ws = shared()
    c = ws.clone
    plain = tmp("tt-gh-plain-")
    merge = "mutation { mergePullRequest(input:{pullRequestId:\"PR_x\"}) { clientMutationId } }"
    approve = "mutation { addPullRequestReview(input:{pullRequestId:\"PR_x\", event: APPROVE}) { clientMutationId } }"
    auto = "mutation { enablePullRequestAutoMerge(input:{pullRequestId:\"PR_x\"}) { clientMutationId } }"
    dismiss = "mutation { dismissPullRequestReview(input:{pullReviewId:\"R_x\", message:\"m\"}) { clientMutationId } }"
    rows = [(f"gh api \"$GHE_API/graphql\" -f query='{merge}'", plain, "deny", "머지"),
            (f"gh api \"$GHE_API/graphql\" -f query='{approve}'", plain, "deny", "Approve"),
            (f"gh api \"$GHE_API/graphql\" -f query='{auto}'", c, "deny", "머지"),
            (f"gh api \"$GHE_API/graphql\" -f query='{dismiss}'", plain, "deny", "기각"),
            (f"gh api $GHE_API/graphql -f query='{merge}'", plain, "deny", None),
            (f"gh api \"${{GHE_API}}/graphql\" -f query='{merge}'", plain, "deny", None),
            (f"gh api \"$BASE/api/%67raphql\" -f query='{merge}'", plain, "deny", None),
            (f"Q='{merge}'; gh api \"$GHE_API/graphql\" -f query=\"$Q\"", plain, "deny", None),
            (f"gh api \"$EP\" -f query='{approve}'", plain, "deny", None),
            ("gh api \"$GHE_API/graphql\" -f query=\"$Q\"", plain, "ask", "GraphQL"),
            ("gh api \"$GHE_API/graphql\" -f query='query { viewer { login } }'", plain, None, None),
            ("gh api \"$BASE/repos/other/x/issues\" -f title=t", plain, None, None)]
    for cmd, cwd, want, why in rows:
        out = bash(ws, cmd, cwd)
        assert decision(out) == want, (cmd, cwd)
        assert why is None or why in out["permissionDecisionReason"], cmd


def test_guard_scp_remote_without_user_keeps_explicit_targets_and_warns_unparsable():
    """규칙 11(H-A1 r6): `issue_db.remote`가 user 없는 git SCP 꼴(`ghe-ssh:o/r.git` — ~/.ssh/config의 별칭)이어도 owner/repo로
    푼다(`userconfig.repo_slug`). 그래서 `-R`·`api repos/…`·MCP owner/repo 명시 대상의 병합·Approve가 거부된다. 그 꼴 원격을 가진
    다른 clone도 이슈 DB로 본다. owner/repo로 못 푸는 원격이면 guard가 경고한다(규칙 11이 꺼진다 — doctor `config` 행은 fail)."""
    ws = Workspace(build=False)
    ws.json("config.py", ["set-tracker", "--server", "mock-jira", "--get-issue", JIRA_TOOLS[0],
                          "--search-issues", JIRA_TOOLS[1], "--get-comments", JIRA_TOOLS[2]])

    def set_remote(old: str, value: str) -> None:
        for p in ws.home.rglob("*.yaml"):
            text = p.read_text(encoding="utf-8")
            if old in text:
                p.write_text(text.replace(old, value), encoding="utf-8")
    set_remote(f"https://ghe.mock.invalid/{DB_SLUG}.git", f"ghe-ssh:{DB_SLUG}.git")
    plain = tmp("tt-gh-plain-")
    scp_clone = _repo_with_origin(f"ghe-ssh:{DB_SLUG}.git")
    db = {"owner": "mock-org", "repo": "telephony-issue-db", "pullNumber": 3}
    for cmd, cwd, want in [(f"gh pr merge 3 -R {DB_SLUG}", plain, "deny"),
                           (f"gh api -X PUT repos/{DB_SLUG}/pulls/3/merge", plain, "deny"),
                           (f"gh pr review 3 --approve -R {DB_SLUG}", plain, "deny"),
                           (f"gh pr comment 3 -b x -R {DB_SLUG}", plain, "ask"),
                           ("gh pr merge 3", ws.clone, "deny"), ("gh pr merge 3", scp_clone, "deny"),
                           ("gh pr merge 3 -R other/x", plain, None)]:
        assert decision(bash(ws, cmd, cwd)) == want, (cmd, cwd)
    for tool, tool_input, want in [("mcp__github__merge_pull_request", db, "deny"),
                                   ("mcp__github__pull_request_review_write", {**db, "method": "create", "event": "APPROVE"}, "deny"),
                                   ("mcp__github__merge_pull_request", {**db, "owner": "other"}, None)]:
        assert decision(guard(ws, tool, tool_input, plain)) == want, tool
    # https 설정이어도 user 없는 SCP 꼴 원격의 다른 clone은 이슈 DB다
    assert decision(bash(shared(), "gh pr merge 3", scp_clone)) == "deny"
    # 숫자뿐인 owner의 SCP 꼴(회귀 수정 R3): git처럼 owner로 읽는다(포트가 아니다) — 규칙 11이 켜져 있고 경고가 없다
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(plain)}
    current = f"ghe-ssh:{DB_SLUG}.git"
    for remote, owner in (("git@ghe.mock.invalid:1234/telephony-issue-db.git", "1234"),
                          ("ghe-ssh:20231234/telephony-issue-db.git", "20231234")):
        set_remote(current, remote)
        current = remote
        num_clone = _repo_with_origin(remote)
        for cmd, cwd, want in [(f"gh pr merge 3 -R {owner}/telephony-issue-db", plain, "deny"),
                               (f"gh api -X PUT repos/{owner}/telephony-issue-db/pulls/3/merge", plain, "deny"),
                               (f"gh pr comment 3 -b x -R {owner}/telephony-issue-db", plain, "ask"),
                               ("gh pr merge 3", num_clone, "deny"),
                               (f"gh pr merge 3 -R {DB_SLUG}", plain, None)]:
            assert decision(bash(ws, cmd, cwd)) == want, (remote, cmd)
        proc = run("guard.py", [], root=ws.root, cwd=plain, env=ws.env(), stdin=json.dumps(event))
        assert proc.returncode == 0 and "규칙 11" not in proc.stderr, (remote, proc.stderr)
    # 못 푸는 원격: 규칙 11이 꺼진다는 경고(stderr)
    set_remote(current, "telephony-issue-db")
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(plain)}
    proc = run("guard.py", [], root=ws.root, cwd=plain, env=ws.env(), stdin=json.dumps(event))
    assert proc.returncode == 0 and "issue_db.remote(telephony-issue-db)" in proc.stderr and "규칙 11" in proc.stderr, proc.stderr


def test_guard_mcp_strong_words_before_write_gate():
    """규칙 11 MCP(H-A1 r5): 병합·Approve·기각 낱말은 쓰기형 판정(`mcptools.is_write`)과 따로, 먼저 본다 — `pr_approve`·
    `automerge_pr`·`squash_and_merge`·입력 `event` APPROVE. 동사가 읽기 동사(`get_merge_status`)면 보지 않는다."""
    ws = shared()
    db = {"owner": "mock-org", "repo": "telephony-issue-db", "number": 3}
    rows = [("mcp__ghe__pr_approve", db, "deny", "Approve하지 않는다"),
            ("mcp__ghe__pull_request_approve", db, "deny", "Approve하지 않는다"),
            ("mcp__ghe__approvePullRequest", db, "deny", "Approve하지 않는다"),
            ("mcp__ghe__pr_review", {**db, "event": "APPROVE"}, "deny", "Approve하지 않는다"),
            ("mcp__ghe__automerge_pr", db, "deny", "머지"), ("mcp__ghe__squash_and_merge", db, "deny", "머지"),
            ("mcp__ghe__pr_dismiss_review", db, "deny", "기각"),
            ("mcp__ghe__disable_auto_merge", db, "ask", None), ("mcp__ghe__request_approval", db, "ask", None),
            ("mcp__ghe__get_merge_status", db, None, None), ("mcp__ghe__list_approvals", db, None, None),
            ("mcp__github__list_pull_requests", {**db, "state": "merged"}, None, None),
            ("mcp__ghe__pr_approve", {"owner": "other", "repo": "x"}, None, None)]
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
    # 트래커가 아닌 일반 GitHub MCP: 이슈 DB 대상 쓰기는 규칙 11 ask, 그 밖은 판정 없음(github server_words는 비어 있다)
    assert decision(guard(ws, "mcp__github__create_pull_request", {**db, "title": "x"}, ws.base)) == "ask"
    assert decision(guard(ws, "mcp__github__update_issue", {"owner": "a", "repo": "b", "issue_number": 1}, ws.base)) is None


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


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
