#!/usr/bin/env python3
"""모듈 스킬 레포의 첫 커밋을 템플릿에서 만든다 (H C1 C1D §3.4, MS-1 준비).

    python3 tools/make_module_repo.py <out> [--templates templates/module-skills] [--json]

1. `<out>`은 없거나 빈 디렉토리이고 이 레포 밖이어야 한다(아니면 종료 2).
2. 템플릿이 `skillcheck.check_worktree`(받을 때 규칙) + `skillcheck.template_findings`(템플릿 점검)를 통과해야 한다.
   지적이 있으면 `경로[:줄] 점검`만 내고 종료 1, 아무것도 만들지 않는다.
3. `skillcheck.ALLOWED` 이름의 파일만 복사한다(`evals/results/`·`__pycache__` 제외), 모드 0644.
4. `git init -q -b main`, 모두 add, 한 커밋. 작성자·커미터 `telephony-triage`, 날짜는 템플릿의 이 레포 HEAD 커밋 날짜,
   메시지 `module-skills: import from telephony-triage <sha7>`. 원격·push는 없다 — 다음 할 일(GHE 레포 만들기, +1 브랜치
   보호, MS-1)은 stderr로 안내만 한다.
5. stdout: `<out> <커밋 sha>` (`--json`이면 `{"out", "commit", "files"}`).

같은 템플릿·같은 HEAD면 같은 트리·같은 커밋 sha가 나온다. 종료 코드: 0 만듦, 1 템플릿 지적, 2 사용·환경 오류.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import skillcheck  # noqa: E402

OK, FOUND, USAGE = 0, 1, 2
AUTHOR = "telephony-triage"
EMAIL = "telephony-triage@invalid"
NEXT_STEPS = ("다음: GHE에 빈 모듈 레포를 만들고 이 디렉토리를 push한다(사람). main 브랜치 보호에 +1 승인 1·up to date를 켠다. "
              "그다음 MS-1(site_step) 절차로 플러그인 설정에 레포를 적는다.")


class Usage(Exception):
    """사용·환경 오류(종료 2)."""


def _git(cwd: Path, *args: str, env: dict | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env)
    if proc.returncode != 0:
        raise Usage(f"git {args[0]} 실패: {proc.stderr.strip()[-300:]}")
    return proc.stdout.strip()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _files(templates: Path) -> list[str]:
    out = []
    for cur, dirs, names in os.walk(templates, followlinks=False):
        rel_dir = Path(cur).relative_to(templates).as_posix()
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git")
                         and not (d == "results" and rel_dir.endswith("/evals")))
        for name in sorted(names):
            rel = f"{rel_dir}/{name}" if rel_dir != "." else name
            if any(rx.fullmatch(rel) for rx in skillcheck.ALLOWED):
                out.append(rel)
    return sorted(out)


def _source_commit(templates: Path) -> tuple[str, str]:
    """(sha7, ISO 날짜) — 템플릿을 담은 레포의 HEAD. git 레포가 아니면 종료 2."""
    sha = _git(templates, "rev-parse", "HEAD")
    date = _git(templates, "log", "-1", "--format=%cI", "HEAD")
    return sha[:7], date


def build(out: Path, templates: Path) -> tuple[str, list[str]]:
    if not templates.is_dir():
        raise Usage(f"템플릿 디렉토리가 아니다: {templates}")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Usage(f"<out>은 없거나 빈 디렉토리여야 한다: {out}")
    if _inside(out, REPO):
        raise Usage("<out>은 이 레포 밖이어야 한다")
    found = skillcheck.check_worktree(templates) + skillcheck.template_findings(templates)
    if found:
        lines = [f"{f['path']}:{f['line']} {f['check']}" if "line" in f else f"{f['path']} {f['check']}" for f in found]
        raise LookupError("\n".join(lines))
    sha7, date = _source_commit(templates)
    files = _files(templates)
    out.mkdir(parents=True, exist_ok=True)
    for rel in files:
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(templates / rel, dest)
        dest.chmod(0o644)
    env = {**os.environ, "GIT_AUTHOR_NAME": AUTHOR, "GIT_AUTHOR_EMAIL": EMAIL, "GIT_COMMITTER_NAME": AUTHOR,
           "GIT_COMMITTER_EMAIL": EMAIL, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    _git(out, "init", "-q", "-b", "main", env=env)
    _git(out, "-c", "core.fileMode=true", "add", "-A", env=env)
    _git(out, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m",
         f"module-skills: import from telephony-triage {sha7}", env=env)
    return _git(out, "rev-parse", "HEAD", env=env), files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="make_module_repo.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--templates", type=Path, default=REPO / "templates" / "module-skills")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        commit, files = build(args.out, args.templates)
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    except LookupError as exc:
        print(str(exc))
        print("템플릿 지적이 있어 만들지 않았다", file=sys.stderr)
        return FOUND
    if args.json:
        print(json.dumps({"out": str(args.out), "commit": commit, "files": len(files)}, ensure_ascii=False))
    else:
        print(f"{args.out} {commit}")
    print(NEXT_STEPS, file=sys.stderr)
    return OK


if __name__ == "__main__":
    sys.exit(main())
