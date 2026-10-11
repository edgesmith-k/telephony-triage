"""guard 다중 프로필·pre-push 플랫폼 분기 (17-platforms 설계 §1-C·§7-B, 묶음 2).

사용자 config에 android(최상위)와 ofono(`platforms.ofono`) 프로필이 함께 있을 때 규칙마다 **두 번째 프로필**도 보호되는지 본다.
android만 있을 때의 판정은 기존 테스트(test_hooks·test_safety)가 그대로 지킨다.

- 규칙 8(파일·Bash): ofono clone 파일 쓰기 거부, ofono work_dir은 제외
- 규칙 2: ofono `work_dir/<KEY>/post.approved.json` 쓰기 거부
- 규칙 11: `gh -R <ofono 원격>` 쓰기 ask·머지 거부, 비Jira MCP(owner/repo) ask
- git 규칙: ofono clone 본체의 브랜치 변경 거부, push base 브랜치는 그 프로필의 것(develop)
- pre-push: ofono DB는 `platforms.ofono.work_dir`의 state.json 토큰만 받는다
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import make_repo  # noqa: E402
from runner import SAMPLE, run, tmp  # noqa: E402
from workspace import GIT_ID, Workspace, git  # noqa: E402

OFONO_REMOTE = "https://ghe.mock.invalid/mock-org/ofono-issue-db.git"

_WS: dict = {}


def two_profiles() -> dict:
    """android 작업공간 + ofono 변형 DB clone(core.hooksPath .githooks)과 `platforms.ofono` 프로필."""
    if _WS:
        return _WS
    ws = Workspace(build=False)
    src = tmp("tt-ofono-src-") / "db"
    shutil.copytree(SAMPLE, src)
    cfg_path = src / "issue-db.config.yaml"
    cfg_path.write_text("platform: ofono\n" + cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
    info = make_repo.make(src, ws.base / "ofono-repo")
    clone = Path(info["clone"])
    git(clone, "checkout", "-q", "-b", "develop")
    git(clone, "push", "-q", "origin", "develop")
    git(clone, "config", "core.hooksPath", ".githooks")
    work = ws.base / "work-ofono"
    cfg = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"] = {"ofono": {"issue_db": {"path": str(clone), "remote": OFONO_REMOTE, "base_branch": "develop"},
                                  "work_dir": str(work)}}
    (ws.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    _WS.update(ws=ws, clone=clone, work=work)
    return _WS


def guard(tool: str, tool_input: dict, cwd: Path) -> str | None:
    ws = two_profiles()["ws"]
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
    proc = run("guard.py", [], root=ws.root, cwd=cwd, env=ws.env(), stdin=json.dumps(event))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
    return out and out["permissionDecision"]


def bash(command: str, cwd: Path) -> str | None:
    return guard("Bash", {"command": command}, cwd)


def test_rule8_file_tools_protect_second_clone():
    p = two_profiles()
    assert guard("Write", {"file_path": str(p["clone"] / "README.md")}, p["ws"].base) == "deny"
    assert guard("Edit", {"file_path": str(p["ws"].clone / "README.md")}, p["ws"].base) == "deny"   # android 그대로
    assert guard("Write", {"file_path": str(p["work"] / "OFN-1" / "plan.json")}, p["ws"].base) is None


def test_rule8_bash_writes_protect_second_clone():
    p = two_profiles()
    assert bash(f"echo x > {p['clone'] / 'a.txt'}", p["ws"].base) == "deny"
    assert bash(f"echo x > {p['work'] / 'note.txt'}", p["ws"].base) is None


def test_rule2_post_records_in_second_work_dir():
    p = two_profiles()
    target = p["work"] / "OFN-1" / "post.approved.json"
    assert guard("Write", {"file_path": str(target)}, p["ws"].base) == "deny"
    assert bash(f"echo '{{}}' > {target}", p["ws"].base) == "deny"


def test_rule11_gh_and_mcp_target_second_remote():
    p = two_profiles()
    base = p["ws"].base
    assert bash("gh pr create -R mock-org/ofono-issue-db --title t --body b", base) == "ask"
    assert bash("gh pr merge 3 -R mock-org/ofono-issue-db", base) == "deny"
    assert bash("gh pr list -R mock-org/ofono-issue-db", base) is None
    assert bash("gh pr create -R mock-org/unrelated --title t --body b", base) is None
    assert guard("mcp__github__create_pull_request", {"owner": "mock-org", "repo": "ofono-issue-db"}, base) == "ask"


def test_git_rules_in_second_clone_use_its_base():
    p = two_profiles()
    clone = p["clone"]
    assert bash("git checkout -b topic", clone) == "deny"                      # clone 본체 브랜치 변경
    assert bash("git push origin HEAD:refs/heads/develop", clone) == "deny"    # 그 프로필 base
    assert bash("git push origin HEAD:refs/heads/issue/OFN-1", clone) == "ask"
    # android clone의 base는 main 그대로: develop은 base가 아니다(ask만)
    assert bash("git push origin HEAD:refs/heads/develop", p["ws"].clone) == "ask"
    assert bash("git push origin HEAD:refs/heads/main", p["ws"].clone) == "deny"


def _push(clone: Path, ref: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(clone), *GIT_ID, "push", "-q", "origin", ref], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)


def test_prepush_uses_platform_profile():
    p = two_profiles()
    ws, clone = p["ws"], p["clone"]
    git(clone, "checkout", "-q", "-B", "issue/OFN-1", "origin/develop")
    (clone / "CONTRIBUTING.md").write_text("ofono 편집\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "--no-verify", "-m", "편집")
    tree = git(clone, "rev-parse", "HEAD^{tree}")
    env = ws.hook_env(TT_PUBLISH_TOKEN="manual")
    proc = _push(clone, "HEAD:refs/heads/develop", env)
    assert proc.returncode != 0 and "base 브랜치(develop)" in proc.stderr
    # 승인 state.json이 android work_dir에만 있으면 거부, ofono work_dir에 있으면 통과
    state = {"approved_hash": tree, "branch": "issue/OFN-1"}
    (ws.work / "OFN-1").mkdir(parents=True, exist_ok=True)
    (ws.work / "OFN-1" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    proc = _push(clone, "HEAD:refs/heads/issue/OFN-1", ws.hook_env(TT_PUBLISH_TOKEN=tree))
    assert proc.returncode != 0 and "approved_hash" in proc.stderr
    (p["work"] / "OFN-1").mkdir(parents=True, exist_ok=True)
    (p["work"] / "OFN-1" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    proc = _push(clone, "HEAD:refs/heads/issue/OFN-1", ws.hook_env(TT_PUBLISH_TOKEN=tree))
    assert proc.returncode == 0, proc.stderr
    git(clone, "checkout", "-q", "develop")
