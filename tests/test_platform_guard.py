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
from runner import SAMPLE, plugin_root, run, tmp  # noqa: E402
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


# -- 규칙 2: 다른 프로필의 승인 대조, jira_bridge 결과 기록 (리뷰 P1-1) -----------------------------

NOTE_TOOL = "mcp__mock-jira__jira_ticket_add_note"     # site-defaults(example) jira.write_tools.add_comment


def _approve_at(job_dir: Path, key: str, body: str) -> Path:
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    from common import issuepost
    at = issuepost.now()
    record = {"schema": 1, "key": key, "tool": NOTE_TOOL, "key_arg": "ticket", "body_sha256": issuepost.body_sha256(body),
              "format": "jira-wiki", "request_hash": "0" * 16, "approved_at": issuepost.iso(at),
              "expires_at": issuepost.iso(issuepost.expires(at)), "used_at": None}
    job = job_dir / key
    job.mkdir(parents=True, exist_ok=True)
    (job / "post.approved.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (job / "post.md").write_text(issuepost.normalize_body(body) + "\n", encoding="utf-8")
    (job / "post.result.json").unlink(missing_ok=True)
    return job


def _bridge(tool_input: dict, response) -> subprocess.CompletedProcess:
    ws = two_profiles()["ws"]
    event = {"hook_event_name": "PostToolUse", "tool_name": NOTE_TOOL, "tool_input": tool_input,
             "tool_response": response, "cwd": str(ws.base)}
    proc = run("jira_bridge.py", [], root=ws.root, env=ws.env(), cwd=ws.base, stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return proc


def test_rule2_approval_in_second_profile_is_recorded_there():
    p = two_profiles()
    ws, owork = p["ws"], p["work"]
    key, body_a, body_b = "MOCK-7301", "h3. PROBLEM\n* ofono 본문 A", "h3. PROBLEM\n* android 본문 B"
    ojob = _approve_at(owork, key, body_a)
    ajob = _approve_at(ws.work, key, body_b)          # 같은 KEY를 android에서도 승인(더 최근)
    post_a = {"ticket": key, "text": body_a}
    assert guard(NOTE_TOOL, post_a, ws.base) == "ask"                 # ofono 승인과 맞는다
    assert guard(NOTE_TOOL, {"ticket": key, "text": "다른 본문"}, ws.base) == "deny"
    _bridge(post_a, {"id": "c1"})
    o_rec = json.loads((ojob / "post.approved.json").read_text(encoding="utf-8"))
    o_res = json.loads((ojob / "post.result.json").read_text(encoding="utf-8"))
    assert o_rec["used_at"] and o_res["status"] == "posted" and o_res["comment_id"] == "c1"
    assert not (ajob / "post.result.json").exists()                  # 게시하지 않은 프로필에는 쓰지 않는다
    assert json.loads((ajob / "post.approved.json").read_text(encoding="utf-8"))["used_at"] is None
    assert guard(NOTE_TOOL, post_a, ws.base) == "deny"                # 1회용: 같은 본문을 다시 올리지 못한다
    assert guard(NOTE_TOOL, {"ticket": key, "text": body_b}, ws.base) == "ask"    # android 승인은 그대로


def test_jira_bridge_unmatched_post_is_fail_closed():
    p = two_profiles()
    ws, owork = p["ws"], p["work"]
    key = "MOCK-7302"
    ojob = _approve_at(owork, key, "h3. A")
    ajob = _approve_at(ws.work, key, "h3. B")
    _bridge({"ticket": key, "text": "h3. 승인 없는 본문"}, {"id": "c9"})
    for job in (ojob, ajob):
        assert json.loads((job / "post.approved.json").read_text(encoding="utf-8"))["used_at"]
        assert json.loads((job / "post.result.json").read_text(encoding="utf-8"))["status"] == "unknown"


def test_jira_read_goes_to_selected_platform_work_dir():
    """스킬이 triage 전에 Jira를 읽어도 선택 플랫폼(TT_PLATFORM > 사용자 config platform)의 work_dir에 저장한다."""
    p = two_profiles()
    ws = p["ws"]
    ws.json("config.py", ["set-jira", "--server", "mock-jira", "--get-issue", "mcp__mock-jira__jira_fetch_ticket"])
    event = {"hook_event_name": "PostToolUse", "tool_name": "mcp__mock-jira__jira_fetch_ticket",
             "tool_input": {"ticket": "MOCK-7401"}, "cwd": str(ws.base),
             "tool_response": {"key": "MOCK-7401", "fields": {"summary": "s"}}}
    root_on = plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    proc = run("jira_bridge.py", [], root=root_on, env=ws.env(TT_PLATFORM="ofono"), cwd=ws.base,
               stdin=json.dumps(event))
    assert proc.returncode == 0, proc.stderr
    assert (p["work"] / "MOCK-7401" / "jira_raw.json").is_file()
    assert not (ws.work / "MOCK-7401").exists()
    proc = run("jira_bridge.py", [], root=root_on, env=ws.env(), cwd=ws.base, stdin=json.dumps(
        {**event, "tool_input": {"ticket": "MOCK-7402"}, "tool_response": {"key": "MOCK-7402", "fields": {}}}))
    assert proc.returncode == 0 and (ws.work / "MOCK-7402" / "jira_raw.json").is_file()


# -- 규칙 8: 프로필 경로 겹침·잘못된 값 (리뷰 P1-2·P2-8) -----------------------------------------------


def test_rule8_second_profile_cannot_unprotect_clone():
    ws = Workspace(build=False)
    cfg_path = ws.home / "config.yaml"
    orig = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    target = str(ws.clone / "README.md")

    def judge(profs: dict, tool: str, tool_input: dict, cwd: Path):
        cfg = dict(orig)
        cfg["platforms"] = profs
        cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
        event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
        proc = run("guard.py", [], root=ws.root, cwd=cwd, env=ws.env(), stdin=json.dumps(event))
        out = json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else None
        return (out and out["permissionDecision"]), proc.stderr

    for prof in ({"work_dir": str(ws.clone.parent)}, {"work_dir": str(ws.clone)}, {"work_dir": ""}, {"work_dir": "."}):
        for cwd in (ws.base, ws.clone):
            decision, err = judge({"ofono": prof}, "Write", {"file_path": target}, cwd)
            assert decision == "deny", (prof, cwd)
            assert "플랫폼 프로필 문제" in err
            decision, _ = judge({"ofono": prof}, "Bash", {"command": f"echo x > {target}"}, cwd)
            assert decision == "deny", (prof, cwd)
    # 이름이 잘못된 프로필의 clone도 보호한다
    other = Path(make_repo.make(SAMPLE, ws.base / "other")["clone"])
    decision, err = judge({"oFono": {"issue_db": {"path": str(other)}}}, "Write", {"file_path": str(other / "a.md")}, ws.base)
    assert decision == "deny" and "플랫폼 이름이 아닙니다" in err
    # clone 안의 (유효한) work_dir은 그대로 제외된다
    inner = ws.clone / "tt-work"
    decision, _ = judge({"ofono": {"work_dir": str(inner)}}, "Write", {"file_path": str(inner / "J" / "plan.json")}, ws.base)
    assert decision is None
    cfg_path.write_text(yaml.safe_dump(orig, allow_unicode=True), encoding="utf-8")


def test_prepush_reads_platform_from_pushed_commit():
    """워킹 트리의 `platform:` 수정으로 base·토큰 디렉토리를 바꿀 수 없다(push하는 커밋의 선언을 본다)."""
    p = two_profiles()
    ws, clone = p["ws"], p["clone"]
    git(clone, "checkout", "-q", "-B", "issue/OFN-2", "origin/develop")
    (clone / "CONTRIBUTING.md").write_text("ofono 편집 2\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-q", "--no-verify", "-m", "편집 2")
    cfg = clone / "issue-db.config.yaml"
    saved = cfg.read_text(encoding="utf-8")
    cfg.write_text(saved.replace("platform: ofono\n", "platform: foo\n"), encoding="utf-8")   # 커밋하지 않은 수정
    proc = _push(clone, "HEAD:refs/heads/develop", ws.hook_env(TT_PUBLISH_TOKEN="manual"))
    assert proc.returncode != 0 and "base 브랜치(develop)" in proc.stderr
    cfg.write_text(saved, encoding="utf-8")
    git(clone, "checkout", "-q", "develop")
