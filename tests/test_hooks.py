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
    않는다(리뷰 2차 P0-2). 남는 한계(스크립트 파일 안, 변수로 만든 낱말, 가짜 heredoc)는 08-safety와 같게 고정한다."""
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
                "python3 $S/db_pr.py pub\\\nlish wt", "python3 $S/db\\\n_pr.py publish wt"):
        out = bash(ws, cmd, ws.base)
        assert decision(out) == "ask" and "규칙 7" in out["permissionDecisionReason"], cmd
    for cmd in ("cat > notes.md <<'EOF'\npython3 db_pr.py publish wt\nEOF", "cat /w/MOCK-1/publish.json",
                f"python3 {r}/db_pr.py summary wt > /w/MOCK-1/publish-preview.md",
                f"sed -n 1,20p {r}/db_pr.py {r}/dbpr/publish.py",
                # 남는 한계
                "bash /w/push.sh", f"P=pub; python3 {r}/db_pr.py ${{P}}lish wt", f"X=db; python3 {r}/${{X}}_pr.py publish wt",
                "echo \"<<EOF\"\npython3 $S/db_pr.py publish wt\nEOF"):   # 인용 안 `<<EOF`로 만든 가짜 heredoc
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
             ("gh api -X POST repos/{owner}/{repo}/issues -f title=x", db_origin, "ask"),
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
