#!/usr/bin/env python3
"""쓰기 경로(Step 8·공통 쓰기 절차) 테스트용 작업 환경 (11-phases.md Phase 7).

`Workspace` 하나가 다음을 갖는다.
- 임시 사용자 홈(`TELEPHONY_TRIAGE_HOME`)과 사용자 config(`config.py init --answers`), `work_dir`
- `make_repo.make()`로 만든 모의 원격(bare)과 사용자 clone (`core.hooksPath .githooks`)
- 작업공간 전용 `gh` 스텁 상태 디렉토리(`MOCK_GH_STATE_DIR`)

스킬 없이 Step 8을 돌린다: 손으로 쓴 계획(`tests/fixtures/plans/*.json`)을 `<work_dir>/<작업 키>/plan.json`에
놓고 `db_pr stage → summary → git add/commit(별도 호출) → publish → discard`를 직접 부른다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLANS = REPO / "tests" / "fixtures" / "plans"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_repo  # noqa: E402
import mock_env  # noqa: E402
from runner import SAMPLE, plugin_root, run, tmp  # noqa: E402

GIT_ID = ["-c", "user.name=Mock User", "-c", "user.email=mock-user@ghe.mock.invalid"]


def git(repo: Path, *args: str, check: bool = True, env: dict | None = None) -> str:
    full_env = None
    if env:
        full_env = dict(os.environ)
        full_env.update({k: str(v) for k, v in env.items()})
    proc = subprocess.run(["git", "-C", str(repo), *GIT_ID, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=full_env)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc.stdout.strip()


class Workspace:
    def __init__(self, src: Path = SAMPLE, root: Path | None = None, build: bool = True):
        self.base = tmp("tt-ws-")
        self.home = self.base / "home"
        self.work = self.base / "work"
        self.gh_state = self.base / "gh-state"
        self.root = root or plugin_root()
        info = make_repo.make(src, self.base / "repo")
        self.clone = Path(info["clone"])
        self.remote = Path(info["remote"])
        answers = self.base / "answers.json"
        answers.write_text(json.dumps({
            "user.ghe_id": "mock-user1", "issue_db.path": str(self.clone),
            "issue_db.remote": "https://ghe.mock.invalid/mock-org/telephony-issue-db.git",
            "work_dir": str(self.work)}), encoding="utf-8")
        self.json("config.py", ["init", "--answers", answers])
        self.json("config.py", ["sync-scripts-path"])   # setup 2: git pre-commit hook이 쓴다
        if build:   # 운영 이슈 DB처럼 main에 생성 파일이 커밋돼 있게 한다 (hook 설치 전: 원격 main 준비)
            self.json("db_build.py", ["--write", "--db", self.clone])
            git(self.clone, "add", "-A")
            git(self.clone, "commit", "-q", "-m", "생성 파일 (테스트 헬퍼)")
            git(self.clone, "push", "-q", "origin", "main")
        self.json("config.py", ["install-hooks", "--db", self.clone])

    # 스크립트 ---------------------------------------------------------------------------

    def env(self, **extra) -> dict:
        return {"TELEPHONY_TRIAGE_HOME": self.home, "MOCK_GH_STATE_DIR": self.gh_state, **extra}

    def run(self, script: str, args: list, env: dict | None = None, unauth: bool = False):
        return run(script, [str(a) for a in args], root=self.root, env=self.env(**(env or {})), cwd=self.base,
                   unauth=unauth)

    def json(self, script: str, args: list, expect=0, **kw) -> dict:
        proc = self.run(script, args, **kw)
        codes = expect if isinstance(expect, tuple) else (expect,)
        assert proc.returncode in codes, (f"{script} {args}: 종료 코드 {proc.returncode} (기대 {expect})\n"
                                          f"stderr: {proc.stderr[-3000:]}\nstdout: {proc.stdout[-3000:]}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def db_pr(self, *args, expect=0, **kw) -> dict:
        return self.json("db_pr.py", list(args), expect=expect, **kw)

    # 계획 -----------------------------------------------------------------------------------

    def main_sha(self) -> str:
        git(self.clone, "fetch", "origin")
        return git(self.clone, "rev-parse", "origin/main")

    def job_dir(self, job: str) -> Path:
        return self.work / job

    def wt(self, job: str) -> Path:
        return self.work / job / "wt"

    def plan(self, job: str, name_or_plan, base_sha: str | None = None, match: str | None = "auto", **over) -> Path:
        """계획을 `<work_dir>/<job>/plan.json`에 쓴다. `base_sha`는 기본으로 지금 origin/main.

        `match="auto"`(기본): analyze 계획의 `feedback.suggested`가 비어 있지 않으면 그 후보로 `<job>/match.json`을
        써 준다(`db_pr stage`가 suggested를 match.json과 대조한다, contracts.md §stage). 테스트가 직접 둔 match.json은
        건드리지 않고, 이 헬퍼가 썼던 것만 계획에 맞게 다시 쓰거나 지운다. `match=None`이면 아무것도 안 한다."""
        if isinstance(name_or_plan, dict):
            plan = json.loads(json.dumps(name_or_plan))
        else:
            plan = json.loads((PLANS / name_or_plan).read_text(encoding="utf-8"))
        plan["base_sha"] = base_sha or self.main_sha()
        plan.update(over)
        path = self.job_dir(job) / "plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        if match == "auto":
            self._auto_match(job, plan)
        return path

    def _auto_match(self, job: str, plan: dict) -> None:
        mpath = self.job_dir(job) / "match.json"
        if mpath.is_file():
            try:
                auto = json.loads(mpath.read_text(encoding="utf-8")).get("_ws_auto")
            except ValueError:
                auto = False
            if not auto:
                return
            mpath.unlink()
        suggested = (plan.get("feedback") or {}).get("suggested") or []
        if plan.get("source") != "analyze" or not suggested:
            return
        doc = {"_ws_auto": True, "schema": 1, "mode": "analysis", "jira": {"key": (plan.get("jira") or {}).get("key")},
               "candidates": [{"type": str(c["cause"]).rsplit("-", 1)[0], "cause": c["cause"],
                               "signature": c.get("signature"), "score": c.get("score"), "S": 1, "C": 1}
                              for c in suggested]}
        mpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    def read_plan(self, job: str) -> dict:
        return json.loads((self.job_dir(job) / "plan.json").read_text(encoding="utf-8"))

    def put(self, job: str, rel: str, src_or_text) -> Path:
        """작업 디렉토리에 fixture 원본 등을 둔다 (마스킹된 텍스트)."""
        dest = self.job_dir(job) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src_or_text, Path):
            shutil.copyfile(src_or_text, dest)
        else:
            dest.write_text(src_or_text, encoding="utf-8", newline="\n")
        return dest

    # Step 8 -----------------------------------------------------------------------------------

    def acquire(self, job: str) -> dict:
        return self.db_pr("lock", "acquire", job, "--take-over")

    def stage(self, job: str, branch: str, expect=0, dry_run: bool = False, **kw) -> dict:
        args = ["stage", self.job_dir(job) / "plan.json", "--wt", self.wt(job), "--branch", branch]
        return self.db_pr(*(args + (["--dry-run"] if dry_run else [])), expect=expect, **kw)

    def commit(self, job: str, message: str | None = None) -> str:
        wt = self.wt(job)
        msg = message or json.loads((self.job_dir(job) / "state.json").read_text(encoding="utf-8"))["commit_message"]
        git(wt, "add", "-A")
        git(wt, "commit", "-q", "-m", msg, env=self.hook_env())   # .githooks/pre-commit이 돈다
        return git(wt, "rev-parse", "HEAD")

    def hook_env(self, **extra) -> dict:
        """git hook이 이 작업공간의 사용자 config를 읽게 하는 환경 (PATH의 gh 스텁 포함)."""
        env = mock_env.env_with_mocks(plugin_root=self.root, gh_state_dir=self.gh_state)
        env.update({k: str(v) for k, v in self.env(**extra).items()})
        return env

    def ship(self, job: str, branch: str, lease: str = "new", discard: bool = True, combined: bool = False) -> dict:
        """stage → summary → 커밋 → publish (→ discard). `combined`면 `stage --then-summary` →
        `publish --commit --and-discard` 2회 경로 (반환 키는 같다: summary는 approved_hash만 가진다)."""
        self.acquire(job)
        if combined:
            wt = self.wt(job)
            proc = self.run("db_pr.py", ["stage", self.job_dir(job) / "plan.json", "--wt", wt, "--branch", branch,
                                         "--then-summary"])
            assert proc.returncode in (0, 3), f"stage --then-summary: {proc.returncode}\n{proc.stderr[-2000:]}"
            digest = json.loads((self.job_dir(job) / "state.json").read_text(encoding="utf-8"))["approved_hash"]
            args = ["publish", wt, "--branch", branch, "--lease", lease, "--approved", digest, "--commit"]
            pub = self.db_pr(*(args + (["--and-discard"] if discard else [])))
            return {"stage": proc.stdout, "summary": {"approved_hash": digest}, "publish": pub}
        stage = self.stage(job, branch)
        summary = self.db_pr("summary", self.wt(job))
        self.commit(job)
        pub = self.db_pr("publish", self.wt(job), "--branch", branch, "--lease", lease,
                         "--approved", summary["approved_hash"])
        if discard:
            self.db_pr("discard", self.wt(job))
        return {"stage": stage, "summary": summary, "publish": pub}

    # 원격 조작 (다른 사람) ---------------------------------------------------------------------

    def other_clone(self) -> Path:
        path = tmp("tt-other-") / "c"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(path)], check=True, capture_output=True)
        return path

    def merge(self, branch: str) -> str:
        """리뷰어가 PR을 머지한 것처럼 원격 main에 `branch`를 머지한다."""
        other = self.other_clone()
        git(other, "merge", "--no-ff", "-q", "-m", f"Merge {branch}", f"origin/{branch}")
        git(other, "push", "-q", "origin", "main")
        return git(other, "rev-parse", "HEAD")

    def push_main(self, edit, message: str = "main 변경") -> str:
        """다른 PR이 main에 들어온 것처럼 `edit(path)`로 바꾼 커밋을 원격 main에 올린다."""
        other = self.other_clone()
        edit(other)
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", message)
        git(other, "push", "-q", "origin", "main")
        return git(other, "rev-parse", "HEAD")

    def push_branch(self, branch: str, edit, message: str = "다른 사람의 push") -> str:
        other = self.other_clone()
        git(other, "checkout", "-q", "-B", branch, f"origin/{branch}")
        edit(other)
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", message)
        git(other, "push", "-q", "origin", f"{branch}:refs/heads/{branch}")
        return git(other, "rev-parse", "HEAD")

    def remote_file(self, branch: str, rel: str) -> str | None:
        proc = subprocess.run(["git", "-C", str(self.remote), "show", f"{branch}:{rel}"], capture_output=True,
                              text=True, encoding="utf-8")
        return proc.stdout if proc.returncode == 0 else None

    def remote_files(self, branch: str) -> list[str]:
        return git(self.remote, "ls-tree", "-r", "--name-only", branch).splitlines()

    def prs(self) -> list[dict]:
        path = self.gh_state / "prs.json"
        return json.loads(path.read_text(encoding="utf-8"))["prs"] if path.is_file() else []
