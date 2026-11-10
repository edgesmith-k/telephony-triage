#!/usr/bin/env python3
"""모듈 스킬 레포의 첫 커밋을 템플릿에서 만든다 (H C1 C1D §3.4, MS-1 준비).

    python3 tools/make_module_repo.py <out> [--templates templates/module-skills] [--site-overlay <dir>] [--json]

1. `<out>`은 없거나 빈 디렉토리이고 이 레포 밖이어야 한다(아니면 종료 2).
2. 템플릿이 `skillcheck.check_worktree`(받을 때 규칙) + `skillcheck.template_findings`(템플릿 점검)를 통과해야 한다.
   지적이 있으면 `경로[:줄] 점검`만 내고 종료 1, 아무것도 만들지 않는다.
3. `skillcheck.ALLOWED` 이름의 파일만 복사한다(`evals/results/`·`__pycache__` 제외), 모드 0644.
4. `git init -q -b main`, 모두 add, 한 커밋. 작성자·커미터 `telephony-triage`, 날짜는 템플릿의 이 레포 HEAD 커밋 날짜,
   메시지 `module-skills: import from telephony-triage <sha7>`. 원격·push는 없다 — 다음 할 일(GHE 레포 만들기, +1 브랜치
   보호, MS-1)은 stderr로 안내만 한다.
5. stdout: `<out> <커밋 sha>` (`--json`이면 `{"out", "commit", "files"}`).

`--site-overlay <dir>`(사내 복구, `docs/SITE_RESTORE.md`): 사내 스냅샷(`docs/site/module-skills/`)의 파일을 템플릿 복사본 위에
**같은 상대 경로로 통째로 덮어쓴다**(`<dir>/SOURCE`는 빼고, 템플릿에 없는 파일은 더한다). 순서대로 하나라도 걸리면 종료 1, 아무것도
만들지 않는다:
- 스냅샷에 `*/*/evals/**`가 있다(eval case는 스냅샷이 아니다) → `<파일> 스냅샷에 evals`.
- 스냅샷에 심볼릭 링크(파일·디렉토리)가 있다 → `<파일> 링크`.
- 덮어쓴 파일에 `{{site:`·placeholder 이름(`PLACEHOLDER_RE`)이 남아 있다 → `스냅샷이 불완전: <파일>`
  (덮어쓰지 않은 파일 — eval 로그 등 — 은 보지 않는다. `TODO(SITE:S25)`는 사내 스냅샷 문서에도 있을 수 있는 표식이라 보지 않는다).
- 덮어쓴 결과를 임시 디렉토리에 만들어 위 2의 점검 + `validate_modules(strict)`를 돌린다 → `경로[:줄] 점검`
  (`validate_modules`는 `modules.yaml 검증(strict) n건`만 — 자세히는 `module_repo_check.py`).
`<dir>/SOURCE`는 `--json`과 상관없이 맨 먼저 읽는다 — 링크·읽기 실패·UTF-8 아님이면 아무것도 만들지 않고 종료 2.
`--json`에 `overlay`(덮어쓴 파일 목록)·`source`(`<dir>/SOURCE` 내용, 없으면 null)를 더한다. 옵션이 없으면 위 1~5 그대로다.

같은 템플릿·같은 HEAD(·같은 스냅샷)면 같은 트리·같은 커밋 sha가 나온다. 종료 코드: 0 만듦, 1 템플릿·스냅샷 지적, 2 사용·환경 오류.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import platforms  # noqa: E402
from common import skillcheck  # noqa: E402

OK, FOUND, USAGE = 0, 1, 2
AUTHOR = "telephony-triage"
EMAIL = "telephony-triage@invalid"
NEXT_STEPS = ("다음: GHE에 빈 모듈 레포를 만들고 이 디렉토리를 push한다(사람). main 브랜치 보호에 +1 승인 1·up to date를 켠다. "
              "그다음 MS-1(site_step) 절차로 플러그인 설정에 레포를 적는다.")


EVALS_RE = re.compile(r"^[^/]+/[^/]+/evals/")
# 남으면 스냅샷이 불완전한 표시: 사외 템플릿의 카테고리 힌트·placeholder 이름(PR-2 §2-0).
# `TODO(SITE:S25)`는 넣지 않는다 — 사내 스냅샷 문서에도 있을 수 있는 표식이다
PLACEHOLDER_RE = re.compile(r"\{\{site:|\b(?:mgmtd|vrild|datad|imsd|simd|networkd|chatterd)\d*\b|\bVRIL\b")


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


def _overlay_files(overlay: Path) -> tuple[list[str], list[str]]:
    """(스냅샷 파일, 심볼릭 링크) 상대 경로(정렬). 최상위 `SOURCE`와 모든 깊이의 `.git`·`__pycache__`는 뺀다.
    링크(파일·디렉토리)는 따라가지 않고 따로 돌려준다 — 스냅샷 밖 내용을 복사하거나 조용히 빠뜨리지 않게."""
    out, links = [], []
    for cur, dirs, names in os.walk(overlay, followlinks=False):
        rel_dir = Path(cur).relative_to(overlay).as_posix()
        keep = []
        for d in sorted(dirs):
            if d in ("__pycache__", ".git"):
                continue
            if os.path.islink(os.path.join(cur, d)):
                links.append(f"{rel_dir}/{d}" if rel_dir != "." else d)
            else:
                keep.append(d)
        dirs[:] = keep
        for name in names:
            rel = f"{rel_dir}/{name}" if rel_dir != "." else name
            if rel == "SOURCE":
                continue
            (links if os.path.islink(os.path.join(cur, name)) else out).append(rel)
    return sorted(out), sorted(links)


def _read_source(overlay: Path | None) -> str | None:
    """`<dir>/SOURCE` 내용(앞뒤 공백 뺌), 없으면 None. 링크·읽기 실패·UTF-8 아님은 종료 2(레포를 만들기 전에)."""
    path = overlay / "SOURCE" if overlay is not None else None
    if path is None:
        return None
    if path.is_symlink():
        raise Usage(f"SOURCE가 링크다: {path}")
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as exc:
        raise Usage(f"SOURCE가 UTF-8이 아니다: {path}") from exc
    except OSError as exc:
        raise Usage(f"SOURCE를 읽지 못했다: {path}") from exc


def _copy(sources: dict[str, Path], dest_root: Path) -> None:
    for rel in sorted(sources):
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sources[rel], dest)
        dest.chmod(0o644)


def _findings(root: Path, strict: bool = False) -> list[str]:
    """`경로[:줄] 점검` 줄(파일 내용·규칙 값 없음). strict면 `validate_modules(strict=True)` 건수 한 줄을 더한다."""
    found = skillcheck.check_worktree(root) + skillcheck.template_findings(root, platforms.template_metas())
    lines = [f"{f['path']}:{f['line']} {f['check']}" if "line" in f else f"{f['path']} {f['check']}" for f in found]
    if strict:
        try:
            doc = skillcheck.load_modules_yaml((root / "modules.yaml").read_bytes())
        except Exception:  # noqa: BLE001 - 없음·크기·YAML은 template_findings가 `읽기`로 낸다
            doc = None
        errs = skillcheck.validate_modules(doc, strict=True) if doc is not None else []
        if errs:
            lines.append(f"modules.yaml 검증(strict) {len(errs)}건")
    return lines


def _overlay_problems(overlay: Path, files: list[str], links: list[str]) -> list[str]:
    evals = [f"{rel} 스냅샷에 evals" for rel in files + links if EVALS_RE.match(rel)]
    if evals or links:
        return evals + [f"{rel} 링크" for rel in links]
    return [f"스냅샷이 불완전: {rel}" for rel in files
            if PLACEHOLDER_RE.search((overlay / rel).read_text(encoding="utf-8", errors="replace"))]


def _source_commit(templates: Path) -> tuple[str, str]:
    """(sha7, ISO 날짜) — 템플릿을 담은 레포의 HEAD. git 레포가 아니면 종료 2."""
    sha = _git(templates, "rev-parse", "HEAD")
    date = _git(templates, "log", "-1", "--format=%cI", "HEAD")
    return sha[:7], date


def build(out: Path, templates: Path, overlay: Path | None = None) -> tuple[str, list[str], list[str]]:
    """(커밋 sha, 레포 파일, 덮어쓴 파일). 덮어쓴 파일은 `overlay`가 없으면 빈 목록."""
    if not templates.is_dir():
        raise Usage(f"템플릿 디렉토리가 아니다: {templates}")
    if overlay is not None and not overlay.is_dir():
        raise Usage(f"스냅샷 디렉토리가 아니다: {overlay}")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Usage(f"<out>은 없거나 빈 디렉토리여야 한다: {out}")
    if _inside(out, REPO):
        raise Usage("<out>은 이 레포 밖이어야 한다")
    sources = {rel: templates / rel for rel in _files(templates)}
    over: list[str] = []
    if overlay is None:
        found = _findings(templates)
    else:
        over, links = _overlay_files(overlay)
        found = _overlay_problems(overlay, over, links)
        sources.update({rel: overlay / rel for rel in over})
        if not found:
            with tempfile.TemporaryDirectory(prefix="tt-overlay-") as tmp:
                _copy(sources, Path(tmp))
                found = _findings(Path(tmp), strict=True)
    if found:
        raise LookupError("\n".join(found))
    sha7, date = _source_commit(templates)
    files = sorted(sources)
    out.mkdir(parents=True, exist_ok=True)
    _copy(sources, out)
    env = {**os.environ, "GIT_AUTHOR_NAME": AUTHOR, "GIT_AUTHOR_EMAIL": EMAIL, "GIT_COMMITTER_NAME": AUTHOR,
           "GIT_COMMITTER_EMAIL": EMAIL, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    _git(out, "init", "-q", "-b", "main", env=env)
    _git(out, "-c", "core.fileMode=true", "add", "-A", env=env)
    _git(out, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m",
         f"module-skills: import from telephony-triage {sha7}", env=env)
    return _git(out, "rev-parse", "HEAD", env=env), files, over


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="make_module_repo.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--templates", type=Path, default=REPO / "templates" / "module-skills")
    ap.add_argument("--site-overlay", type=Path, help="사내 스냅샷 디렉토리(같은 상대 경로로 통째로 덮어쓴다)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        source = _read_source(args.site_overlay)
        commit, files, over = build(args.out, args.templates, args.site_overlay)
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    except LookupError as exc:
        print(str(exc))
        print("템플릿·스냅샷 지적이 있어 만들지 않았다", file=sys.stderr)
        return FOUND
    if args.json:
        data = {"out": str(args.out), "commit": commit, "files": len(files)}
        if args.site_overlay is not None:
            data["overlay"] = over
            data["source"] = source
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(f"{args.out} {commit}")
    print(NEXT_STEPS, file=sys.stderr)
    return OK


if __name__ == "__main__":
    sys.exit(main())
