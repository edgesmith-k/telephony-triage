#!/usr/bin/env python3
"""skill_patch.py — 분석 스킬 `[스킬]` 규칙 제안의 담당자용 patch (analyze Step 7, `reference/skill-patch.md`, 16-existing-assets §16.5.1).

    skill_patch.py <KEY> --skill-dir <SK> --name <analyzer.skill> [--platform <이름>] [--json]

`JOB` = `<work_dir>/<KEY>`. 스킬이 제안을 반영해 쓴 사본 `JOB/skill-suggestions/<이름>/<rel>`(`<이름>` = `--name`에서
`[A-Za-z0-9._-]` 밖 글자를 `-`로 바꾼 것)을 모두 모아, 분석 스킬 디렉토리 `SK`의 같은 `<rel>`과 비교한 unified diff를 만든다.

1. `<rel>` 검사: 사본 폴더 안 일반 파일만(심볼릭 링크 거부), `SK/<rel>`이 `SK` 밖으로 나가지 않는다(절대 경로·`..`·심볼릭 링크
   탈출 거부), 대상이 디렉토리·심볼릭 링크가 아니다, UTF-8 텍스트다.
2. diff(같은 프로세스, `difflib`): 머리 `--- a/<rel>`·`+++ b/<rel>`(새 파일은 `--- /dev/null`), 줄 끝(CRLF 포함)을 바이트
   그대로 두고, 끝 줄바꿈이 없으면 `\\ No newline at end of file`. 바뀐 파일이 없으면 메모.
3. 마스킹: `mask_pii.py`와 같은 함수(`common/masking.py`, 스냅샷 `mask.allow_patterns`, 줄마다)로 patch 전체를 마스킹한다.
   문맥·삭제·머리 줄이 바뀌면 원본에 적용되지 않으므로 메모.
4. 적용 확인: `SK`의 임시 사본(`.git` 제외, `GIT_CEILING_DIRECTORIES`로 바깥 저장소를 찾지 않는다)에서 `git apply --check`.
5. 통과하면 `JOB/skill-suggestions/<이름>.patch`를 쓰고 고정 안내 줄과 파일별 `- <rel> +N −M`을 낸다.

하나라도 실패하면 patch를 쓰지 않고(이전 patch도 지운다) `스킬 제안 patch 없음(담당자 메모로 전달): <사유>` 한 줄을 낸다(종료 1).
낸 줄(안내 줄·줄 수, 또는 메모)은 표시 기록(`kind: patch`, contracts.md "표시 기록")으로 남아 표시 보조 hook이 다음 질문·턴
끝 전에 글자 그대로 보였는지 본다. `SK` 안은 쓰지 않는다. 네트워크·git 쓰기·lock 없음.

출력: 기본은 사용자에게 보일 줄 그대로(텍스트). `--json`이면 `{status: ok|memo, patch, files[{path, added, removed}], lines[],
reason}`(`patch`는 ok일 때만, `reason`은 memo일 때만).

종료 코드: 0 = patch를 만들었다, 1 = 만들지 않았다(메모 — 사본 없음·경로 거부·변경 없음·텍스트 아님·마스킹이 문맥을 바꿈·
`git apply --check` 실패·`SK` 없음), 2 = 사용·환경 오류(site-defaults·사용자 config 없음, 키 형식·플랫폼 불일치, 작업
디렉토리 없음, 이름이 비거나 점뿐, git 없음, `mask.allow_patterns` 정규식 오류).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, masking, session_lock, shown, site_defaults, userconfig  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
import platforms  # noqa: E402
from platforms import session as platform_session  # noqa: E402
import trackers  # noqa: E402

SUGGEST_DIR = "skill-suggestions"
GUIDE = "스킬 제안 patch(적용 안 함, 마스킹됨): {path} — 분석 스킬 담당자에게 전달, 담당자가 검토 후 스킬 소스에서 git apply"
MEMO = "스킬 제안 patch 없음(담당자 메모로 전달): {reason}"
NO_EOL = "\\ No newline at end of file\n"
GIT_TIMEOUT = 60


class Usage(Exception):
    pass


class Memo(Exception):
    """patch를 만들지 않는 사유(종료 1, 메모 줄)."""


def safe_name(raw: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]", "-", str(raw or ""))
    if not name.strip("."):
        raise Usage(f"--name이 비었거나 점뿐이다: {raw!r}")
    return name


# -- 작업 디렉토리 --------------------------------------------------------------------------------


def job_dir(args, defaults: dict) -> tuple[Path, list[str]]:
    """`(JOB, mask.allow_patterns)`. 키 형식은 트래커 `safe_key_re`·스냅샷 `tracker.key_regex`(issue_post와 같다)."""
    user = userconfig.load_user()
    if user is None:
        raise Usage("사용자 config가 없다 — /telephony-triage:setup 을 먼저 한다")
    try:
        name, cfg = platform_session.resolve(defaults, args.platform, user)
        tracker = trackers.of(cfg)
    except (platforms.PlatformConfigError, trackers.TrackerConfigError) as exc:
        raise Usage(str(exc)) from exc
    raw = str(userconfig.get(cfg, "work_dir") or "")
    work = Path(raw).expanduser()
    if not raw or not work.is_dir():
        raise Usage(f"work_dir가 없다: {work} — /telephony-triage:setup 으로 설정을 확인한다")
    snap = work / session_lock.SNAPSHOT_DIR
    db_cfg = compat.load_db_config(snap) if (snap / "issue-db.config.yaml").is_file() else {}
    block = db_cfg.get("tracker") if isinstance(db_cfg.get("tracker"), dict) else {}
    key = tracker.parse_key(args.key) or args.key
    if not tracker.safe_key_re.fullmatch(key) or not re.fullmatch(str(block.get("key_regex") or tracker.default_key_regex), key):
        raise Usage(f"{tracker.label} 키 형식이 아니다: {key}")
    job = work / key
    if not job.is_dir():
        raise Usage(f"작업 디렉토리가 없다: {job} — analyze를 먼저 한다")
    try:
        done = (json.loads((job / "analysis.json").read_text(encoding="utf-8")) or {}).get("platform")
    except (OSError, ValueError, AttributeError):
        done = None
    if (done or userconfig.TOP_PROFILE) != name and (job / "analysis.json").is_file():
        raise Usage(f"이 분석은 {done or userconfig.TOP_PROFILE} 플랫폼이다(선택한 플랫폼: {name}) — --platform으로 다시 실행한다")
    return job, list((db_cfg.get("mask") or {}).get("allow_patterns") or [])


# -- 사본 → diff ----------------------------------------------------------------------------------


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def collect(copies: Path, sk: Path) -> list[tuple[str, Path, Path]]:
    """`[(rel, 사본, SK 대상)]`(rel 순). 사본 폴더 안 일반 파일만, 대상이 SK 밖이면 Memo."""
    if not copies.is_dir() or copies.is_symlink():
        raise Memo(f"사본 폴더가 없다({copies})")
    out = []
    root = sk.resolve()
    for dirpath, dirnames, filenames in os.walk(copies, followlinks=False):
        here = Path(dirpath)
        for d in dirnames:
            if (here / d).is_symlink():
                raise Memo(f"사본 폴더에 심볼릭 링크가 있다({(here / d).relative_to(copies).as_posix()})")
        for f in filenames:
            src = here / f
            rel = src.relative_to(copies).as_posix()
            if src.is_symlink() or not src.is_file():
                raise Memo(f"사본이 일반 파일이 아니다({rel})")
            parts = Path(rel).parts
            if Path(rel).is_absolute() or ".." in parts or any(p.strip() != p or not p for p in parts):
                raise Memo(f"경로가 스킬 디렉토리 밖이다({rel})")
            dst = sk / rel
            if not _inside(dst.resolve(), root):
                raise Memo(f"경로가 스킬 디렉토리 밖이다({rel})")
            if dst.is_symlink() or (dst.exists() and not dst.is_file()):
                raise Memo(f"대상이 일반 파일이 아니다({rel})")
            out.append((rel, src, dst))
    if not out:
        raise Memo(f"사본이 없다({copies})")
    return sorted(out)


def _lines(data: bytes, rel: str) -> list[str]:
    """바이트 → 줄 목록(줄 끝 `\\n`·`\\r\\n`을 그대로 붙인 채, `\\n`으로만 나눈다)."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Memo(f"UTF-8 텍스트가 아니다({rel})") from None
    if "\0" in text:
        raise Memo(f"텍스트 파일이 아니다({rel})")
    parts = text.split("\n")
    return [p + "\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def file_diff(rel: str, src: Path, dst: Path) -> tuple[str, int, int]:
    """`(diff 글, 더한 줄, 지운 줄)`. 같으면 `("", 0, 0)`."""
    new = src.read_bytes()
    old = dst.read_bytes() if dst.exists() else None
    if old == new:
        return "", 0, 0
    a, b = (_lines(old, rel) if old is not None else []), _lines(new, rel)
    out, add, rem = [], 0, 0
    for line in difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{rel}", f"b/{rel}", lineterm="\n", n=3):
        if line.startswith(("--- ", "+++ ")):
            out.append(line if line.endswith("\n") else line + "\n")
            continue
        if line.startswith("+"):
            add += 1
        elif line.startswith("-"):
            rem += 1
        if line.endswith("\n"):
            out.append(line)
        else:          # 끝 줄바꿈 없는 마지막 줄
            out += [line + "\n", NO_EOL]
    return "".join(out), add, rem


def mask_patch(text: str, allow: list[str]) -> str:
    """`mask_pii.py` 치환 모드와 같다: 마스커 하나(기존 토큰 다음 번호부터), `\\n`으로 나눈 줄마다."""
    masker = masking.new_masker(text, allow)
    return "\n".join(masker(line) for line in text.split("\n"))


def changed_context(raw: str, masked: str) -> list[str]:
    """마스킹으로 바뀐 줄 중 원본과 맞춰야 하는 줄(머리·문맥·삭제·`@@`)의 앞부분."""
    bad = []
    for r, m in zip(raw.split("\n"), masked.split("\n")):
        if r != m and not (r.startswith("+") and not r.startswith("+++ ")):
            bad.append(m[:60])
    return bad


def apply_check(sk: Path, patch: str) -> str | None:
    """SK의 임시 사본에서 `git apply --check`. 통과면 None, 아니면 사유. git이 없으면 Usage."""
    git = shutil.which("git")
    if git is None:
        raise Usage("git이 없다 — patch 적용 확인을 할 수 없다")
    with tempfile.TemporaryDirectory(prefix="tt-skill-patch-") as tmp:
        base = Path(tmp).resolve()
        copy = base / "skill"
        shutil.copytree(sk, copy, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        (base / "p.patch").write_bytes(patch.encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_CEILING_DIRECTORIES"] = str(base)
        try:
            proc = subprocess.run([git, "apply", "--check", str(base / "p.patch")], cwd=copy, env=env,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"git apply --check 실행 실패({type(exc).__name__})"
    if proc.returncode != 0:
        first = next((ln.strip() for ln in proc.stderr.splitlines() if ln.strip()), f"종료 {proc.returncode}")
        return f"git apply --check 실패 — {masking.mask_brief(first, 160)}"
    return None


# -- 실행 -----------------------------------------------------------------------------------------


def build(job: Path, sk_arg: str, name: str, allow: list[str]) -> tuple[str, list[dict]]:
    """`(마스킹된 patch, 파일별 {path, added, removed})`. 실패는 Memo."""
    sk = Path(sk_arg).expanduser()
    if not str(sk_arg or "").strip() or not sk.is_dir():
        raise Memo(f"스킬 디렉토리가 없다({sk_arg})")
    sk = sk.resolve()
    sugg = (job / SUGGEST_DIR).resolve()
    if _inside(sugg, sk) or _inside(sk, sugg):
        raise Memo("스킬 디렉토리와 작업 폴더가 겹친다")
    pieces, files = [], []
    for rel, src, dst in collect(job / SUGGEST_DIR / name, sk):
        text, add, rem = file_diff(rel, src, dst)
        if text:
            pieces.append(text)
            files.append({"path": rel, "added": add, "removed": rem})
    if not pieces:
        raise Memo("사본이 스킬 디렉토리 원본과 같다(바뀐 파일 없음)")
    raw = "".join(pieces)
    try:
        masked = mask_patch(raw, allow)
    except masking.AllowPatternError as exc:
        raise Usage(f"mask.allow_patterns 오류: {exc}") from exc
    bad = changed_context(raw, masked)
    if bad:
        raise Memo(f"마스킹이 문맥·삭제 줄을 바꿔 원본에 적용되지 않는다({len(bad)}줄, 예: {bad[0]})")
    why = apply_check(sk, masked)
    if why:
        raise Memo(why)
    return masked, files


def run(args, defaults: dict) -> tuple[dict, int]:
    job, allow = job_dir(args, defaults)
    name = safe_name(args.name)
    out = job / SUGGEST_DIR / f"{name}.patch"
    try:
        try:
            patch, files = build(job, args.skill_dir, name, allow)
        except OSError as exc:      # 읽기·임시 사본 복사 실패(shutil.Error 포함)
            raise Memo(f"파일을 읽거나 복사하지 못했다({type(exc).__name__})") from exc
    except Memo as exc:
        try:
            out.unlink()
        except FileNotFoundError:
            pass
        reason = " ".join(str(exc).split())
        line = MEMO.format(reason=reason)
        shown.record(job.parent, "skill_patch", "patch", job.name, key=f"patch:{job.name}/{name}", lines=[line])
        return {"status": "memo", "reason": reason, "files": [], "lines": [line]}, CHECK_FAILED
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_bytes(patch.encode("utf-8"))
        os.replace(tmp, out)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    lines = [GUIDE.format(path=out.absolute())] + [f"- {f['path']} +{f['added']} −{f['removed']}" for f in files]
    shown.record(job.parent, "skill_patch", "patch", job.name, key=f"patch:{job.name}/{name}", lines=lines,
                 path=str(out.absolute()))
    return {"status": "ok", "patch": str(out.absolute()), "files": files, "lines": lines}, OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill_patch.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("key", metavar="KEY", help="작업 키")
    parser.add_argument("--skill-dir", required=True, metavar="SK",
                        help="분석 스킬 디렉토리(5-1 Skill 결과의 `Base directory for this skill:`)")
    parser.add_argument("--name", required=True, metavar="analyzer.skill", help="분석 스킬 이름(`analyzers.<카테고리>.skill`)")
    platform_session.add_arg(parser)
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--json", action="store_true", help="JSON 출력(기본은 사용자에게 보일 줄)")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(Path(args.plugin_root) if args.plugin_root else None)
    try:
        doc, code = run(args, defaults)
    except Usage as exc:
        print(f"skill_patch.py: {exc}", file=sys.stderr)
        return USAGE
    if args.json:
        print(json.dumps(doc, ensure_ascii=False))
    else:
        print("\n".join(doc["lines"]))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
