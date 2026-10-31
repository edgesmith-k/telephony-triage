#!/usr/bin/env python3
"""skill_patch.py — 분석 스킬 `[스킬]` 규칙 제안의 담당자용 patch (analyze Step 7, `reference/skill-patch.md`, 16-existing-assets §16.5.1).

    skill_patch.py <KEY> --skill-dir <SK> --name <analyzer.skill> [--source <SRC>] [--platform <이름>] [--json]
    skill_patch.py <KEY> --name <analyzer.skill> --apply --sha <patch sha256> [--source <SRC>] [--platform <이름>] [--json]

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

하나라도 실패하면 patch를 쓰지 않고(이전 patch·meta도 지운다) `스킬 제안 patch 없음(직접 반영할 메모): <사유>` 한 줄을 낸다(종료 1).
낸 줄(안내 줄·줄 수, 또는 메모)은 표시 기록(`kind: patch`, contracts.md "표시 기록")으로 남아 표시 보조 hook이 다음 질문·턴
끝 전에 글자 그대로 보였는지 본다. `SK` 안은 쓰지 않는다. 네트워크·lock 없음, git 쓰기는 `--apply`의 스킬 소스 워킹 트리
(`git apply`)뿐이다(index·커밋·push 없음).

**스킬 소스 적용(선택, 16-existing-assets §16.5.1)**: 스킬 소스 `SRC` = `--source` 또는 선택 플랫폼 config의 `analyzers.<카테고리>.source`
(기본 아닌 플랫폼은 `platforms.<p>.analyzers` — android 것을 물려받지 않는다, 17-platforms §10. `skill`이 `--name`과 같은 항목, 절대 경로 — 분석 스킬 소스 checkout 안의 스킬 폴더). patch를 만들 때 `SRC`가 있으면 적용 가능성을
미리 본다(아래 검사): 되면 `스킬 소스 적용 대기: …` 줄과 patch 전문(```diff 울타리 — patch에 백틱 줄이 있으면 그보다 긴 울타리)을, 안 되면 `스킬 소스에 바로 적용할 수 없음(patch만
남김): <사유>` 줄을 더한다(종료 0 그대로). patch가 200줄·12KB를 넘으면 제안하지 않는다("patch 파일을 열어 확인"). 마스킹이
추가 줄을 바꿨으면 대기 줄 끝에 `추가 줄 N개가 마스킹으로 바뀜 — placeholder가 소스에 들어간다`. 사용자가 "적용"을 고르면
`--apply --sha <그 줄의 sha256>`(`--source`는 못 쓴다): meta가 있고 patch 파일 sha256이 같고, 적용 대상은 meta에 기록한(제안 때 보인)
스킬 소스이며 지금 설정된 스킬 소스가 있으면 그것과 같고, 검사를 다시 통과하면 `SRC`가 든 저장소 최상위에서 `git apply [--directory=<SRC의 저장소 안 경로>]`(워킹 트리만 — index·커밋·push 없음)를
하고 `스킬 소스에 적용함(커밋 안 함): <SRC> — 확인 후 직접 커밋·push`와 파일별 줄 수를 낸다(종료 0). 검사: `SRC`가 폴더이고 `SK`·
설치된 플러그인 폴더(경로에 `.claude/plugins`)·이슈 DB clone과 겹치지 않고, git 저장소 안이고, patch가 바꾸는 파일에 커밋하지 않은
변경(추적 안 하는 파일 포함)이 없고, `git apply --check`가 통과한다. 하나라도 아니면 적용하지 않고 `스킬 소스에 적용 안 함(patch는
남김): <사유>`(종료 1). 적용 결과 줄도 표시 기록(`kind: patch`, key `apply:<KEY>/<이름>`)으로 남는다. 제안하지 않은 patch(`SRC` 없음·적용 불가)의
`--apply`는 메모(종료 1), `--apply`와 `--source`를 함께 주면 종료 2.
patch를 만들면 `JOB/skill-suggestions/<이름>.meta.json`(`{skill_dir, sha256, files, source}` — source는 적용을 제안했을 때만)도
쓴다. guard가 patch·meta 직접 쓰기를 거부한다(규칙 12).

출력: 기본은 사용자에게 보일 줄 그대로(텍스트). `--json`이면 `{status: ok|memo, patch, files[{path, added, removed}], lines[],
reason}`(`patch`는 ok일 때만, `reason`은 memo일 때만). ok면 `sha256`, `SRC`가 있으면 `source`·`apply{offer, sha256|reason}`.
`--apply`면 `{status: applied|memo, source, files, lines, reason}`.

종료 코드: 0 = patch를 만들었다, 1 = 만들지 않았다(메모 — 사본 없음·경로 거부·변경 없음·텍스트 아님·마스킹이 문맥을 바꿈·
`git apply --check` 실패·`SK` 없음; `--apply`면 적용 안 함), 2 = 사용·환경 오류(`--skill-dir`·`--apply` 둘 다 없음, `--apply`와 `--source`를 함께 줌, site-defaults·사용자 config 없음, 키 형식·플랫폼 불일치, 작업
디렉토리 없음, 이름이 비거나 점뿐, git 없음, `mask.allow_patterns` 정규식 오류).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
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
GUIDE = "스킬 제안 patch(적용 안 함, 마스킹됨): {path} — 직접 검토해 스킬 소스의 dev 브랜치에 git apply, main에는 PR로 반영"
MEMO = "스킬 제안 patch 없음(직접 반영할 메모): {reason}"
APPLY_OFFER = "스킬 소스 적용 대기: {source} — 아래 patch(마스킹됨, sha256 {sha})를 그대로 보이고 바로 적용할지 묻는다"
MASKED_NOTE = " — 추가 줄 {n}개가 마스킹으로 바뀜 — placeholder가 소스에 들어간다"
OFFER_MAX_LINES, OFFER_MAX_BYTES = 200, 12288    # 화면에 patch 전문을 보일 수 있는 크기까지만 바로 적용을 제안한다
APPLY_NO = "스킬 소스에 바로 적용할 수 없음(patch만 남김): {reason}"
APPLIED = "스킬 소스에 적용함(커밋 안 함): {source} — 확인 후 직접 커밋·push"
APPLY_MEMO = "스킬 소스에 적용 안 함(patch는 남김): {reason}"
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
    args._cfg = cfg     # 스킬 소스(analyzers.<카테고리>.source)·이슈 DB clone 경로를 본다
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


def _fence(text: str) -> str:
    """patch에 든 가장 긴 백틱 줄보다 한 칸 긴 울타리(최소 3) — 스킬 파일의 코드 울타리가 화면의 diff 울타리를 닫지 못하게."""
    return "`" * max(3, max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)


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
    build.masked_added = sum(1 for r, m in zip(raw.split("\n"), masked.split("\n"))
                             if r != m and r.startswith("+") and not r.startswith("+++ "))
    return masked, files


def run(args, defaults: dict) -> tuple[dict, int]:
    job, allow = job_dir(args, defaults)
    name = safe_name(args.name)
    out = job / SUGGEST_DIR / f"{name}.patch"
    meta = job / SUGGEST_DIR / f"{name}.meta.json"
    try:
        try:
            patch, files = build(job, args.skill_dir, name, allow)
        except OSError as exc:      # 읽기·임시 사본 복사 실패(shutil.Error 포함)
            raise Memo(f"파일을 읽거나 복사하지 못했다({type(exc).__name__})") from exc
    except Memo as exc:
        for stale in (out, meta):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
        reason = " ".join(str(exc).split())
        line = MEMO.format(reason=reason)
        shown.record(job.parent, "skill_patch", "patch", job.name, key=f"patch:{job.name}/{name}", lines=[line])
        return {"status": "memo", "reason": reason, "files": [], "lines": [line]}, CHECK_FAILED
    data = patch.encode("utf-8")
    tmp = out.with_name(out.name + ".tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, out)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    sha = hashlib.sha256(data).hexdigest()
    sk = str(Path(args.skill_dir).expanduser().resolve())
    lines = [GUIDE.format(path=out.absolute())] + [f"- {f['path']} +{f['added']} −{f['removed']}" for f in files]
    doc = {"status": "ok", "patch": str(out.absolute()), "files": files, "sha256": sha}
    offered = None
    src_raw = configured_source(args)
    if src_raw:
        src, _, _, why = source_check(src_raw, sk, out, [f["path"] for f in files], getattr(args, "_cfg", None) or {})
        n_lines = patch.count("\n")
        if not why and (n_lines > OFFER_MAX_LINES or len(data) > OFFER_MAX_BYTES):
            why = f"patch가 커서({n_lines}줄, {len(data)}B) 화면에 다 보일 수 없다 — patch 파일을 열어 확인"
        doc["source"] = str(src or src_raw)
        if why:
            lines.append(APPLY_NO.format(reason=why))
            doc["apply"] = {"offer": False, "reason": why}
        else:
            masked_n = getattr(build, "masked_added", 0)
            fence = _fence(patch)
            lines += [APPLY_OFFER.format(source=src, sha=sha) + (MASKED_NOTE.format(n=masked_n) if masked_n else ""),
                      f"{fence}diff", *patch.rstrip("\n").split("\n"), fence]
            doc["apply"] = {"offer": True, "sha256": sha, "masked_added": masked_n}
            offered = str(src)
    try:        # --apply는 이 기록(보인 스킬 소스·sha256)과 같을 때만 적용한다
        meta.write_text(json.dumps({"skill_dir": sk, "sha256": sha, "files": [f["path"] for f in files],
                                    "source": offered}, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass        # 없으면 --apply가 거부한다
    shown.record(job.parent, "skill_patch", "patch", job.name, key=f"patch:{job.name}/{name}", lines=lines,
                 path=str(out.absolute()))
    doc["lines"] = lines
    return doc, OK


# -- 스킬 소스 적용 -------------------------------------------------------------------------------


def configured_source(args) -> str | None:
    """`--source` > 선택 플랫폼 config `analyzers.<카테고리>.source`(`skill`이 `--name`과 같은 첫 항목, 기본 아닌 플랫폼은
    `platforms.<p>.analyzers`의 것 — `userconfig.merged`)."""
    if getattr(args, "source", None):
        return str(args.source)
    cfg = getattr(args, "_cfg", None) or {}
    analyzers = cfg.get("analyzers") if isinstance(cfg.get("analyzers"), dict) else {}
    for entry in analyzers.values():
        if isinstance(entry, dict) and entry.get("skill") == args.name and str(entry.get("source") or "").strip():
            return str(entry["source"])
    return None


def _git_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    git = shutil.which("git")
    if git is None:
        raise Usage("git이 없다 — 스킬 소스에 적용할 수 없다")
    try:
        return subprocess.run([git, *argv], cwd=cwd, env=_git_env(), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess([git, *argv], 1, "", f"git 실행 실패({type(exc).__name__})")


def _first(proc: subprocess.CompletedProcess) -> str:
    return masking.mask_brief(next((ln.strip() for ln in (proc.stderr or proc.stdout).splitlines() if ln.strip()),
                                   f"종료 {proc.returncode}"), 160)


def source_check(src_raw: str, sk: str | None, patch: Path, files: list[str], cfg: dict):
    """`(SRC, 저장소 최상위, SRC의 저장소 안 경로, 사유 또는 None)`. 사유가 있으면 적용하지 않는다(쓰기 없음)."""
    src = Path(os.path.expanduser(src_raw))
    if not src.is_absolute():
        return None, None, None, f"스킬 소스가 절대 경로가 아니다({src_raw})"
    if not src.is_dir():
        return None, None, None, f"스킬 소스 폴더가 없다({src_raw})"
    src = src.resolve()
    parts = src.parts
    if any(parts[i:i + 2] == (".claude", "plugins") for i in range(len(parts))):
        return src, None, None, "설치된 플러그인 폴더다 — 플러그인 캐시의 스킬은 바꾸지 않는다"
    if sk and (_inside(src, Path(sk)) or _inside(Path(sk), src)):
        return src, None, None, "설치된 분석 스킬 폴더(SK)와 겹친다 — 플러그인 캐시의 스킬은 바꾸지 않는다"
    for clone in _clones(cfg):
        if _inside(src, clone) or _inside(clone, src):
            return src, None, None, "이슈 DB clone과 겹친다"
    top = _git(src, "rev-parse", "--show-toplevel")
    if top.returncode != 0 or not top.stdout.strip():
        return src, None, None, f"git 저장소가 아니다({src})"
    root = Path(top.stdout.strip()).resolve()
    prefix = src.relative_to(root).as_posix() if src != root else ""
    paths = [f"{prefix}/{rel}" if prefix else rel for rel in files]
    st = _git(root, "--no-optional-locks", "status", "--porcelain", "--untracked-files=all", "--", *paths)
    if st.returncode != 0:
        return src, root, prefix, f"git status 실패 — {_first(st)}"
    if st.stdout.strip():
        dirty = sorted({ln[3:].strip() for ln in st.stdout.splitlines() if ln.strip()})
        return src, root, prefix, f"스킬 소스에 커밋하지 않은 변경이 있다({', '.join(dirty[:3])}) — 먼저 커밋하거나 되돌린다"
    chk = _git(root, "apply", "--check", *_dir_arg(prefix), str(patch))
    if chk.returncode != 0:
        return src, root, prefix, f"git apply --check 실패 — {_first(chk)}"
    return src, root, prefix, None


def _dir_arg(prefix: str) -> list[str]:
    return [f"--directory={prefix}"] if prefix else []


def _clones(cfg: dict) -> list[Path]:
    out = []
    for key in ("issue_db.path",):
        raw = userconfig.get(cfg, key)
        if isinstance(raw, str) and raw.strip():
            p = Path(os.path.expanduser(raw))
            if p.is_dir():
                out.append(p.resolve())
    return out


def patch_counts(text: str) -> list[dict]:
    """patch 글 → 파일별 `{path, added, removed}`(`+++ b/<rel>` 머리 기준)."""
    out: list[dict] = []
    for line in text.split("\n"):
        if line.startswith("+++ b/"):
            out.append({"path": line[len("+++ b/"):], "added": 0, "removed": 0})
        elif line.startswith("--- ") or line.startswith("+++ ") or not out:
            continue
        elif line.startswith("+"):
            out[-1]["added"] += 1
        elif line.startswith("-"):
            out[-1]["removed"] += 1
    return out


def run_apply(args, defaults: dict) -> tuple[dict, int]:
    job, _ = job_dir(args, defaults)
    name = safe_name(args.name)
    out = job / SUGGEST_DIR / f"{name}.patch"
    key = f"apply:{job.name}/{name}"
    if getattr(args, "source", None):
        raise Usage("--apply는 patch를 만들 때 보인 스킬 소스에만 적용한다 — --source 없이 부른다")
    configured = configured_source(args)

    def memo(reason: str) -> tuple[dict, int]:
        line = APPLY_MEMO.format(reason=" ".join(reason.split()))
        shown.record(job.parent, "skill_patch", "patch", job.name, key=key, lines=[line])
        return {"status": "memo", "reason": reason, "files": [], "lines": [line]}, CHECK_FAILED

    if not out.is_file():
        return memo("patch가 없다 — skill_patch.py로 patch부터 만든다")
    data = out.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", args.sha or "") or args.sha != sha:
        return memo("patch가 보여 준 것과 다르다(sha256 불일치) — patch를 다시 보이고 다시 묻는다")
    try:
        meta = json.loads((job / SUGGEST_DIR / f"{name}.meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = None
    if not isinstance(meta, dict) or meta.get("sha256") != sha:
        return memo("patch 기록(meta)이 없거나 patch와 맞지 않는다 — skill_patch.py로 patch를 다시 만든다")
    src_raw = meta.get("source")
    if not src_raw:
        return memo("patch를 만들 때 스킬 소스 적용을 제안하지 않았다(스킬 소스 없음·적용 불가)")
    if configured and str(Path(os.path.expanduser(configured)).resolve()) != src_raw:
        return memo("설정된 스킬 소스가 patch를 보일 때와 다르다 — skill_patch.py로 patch를 다시 만든다")
    files = patch_counts(data.decode("utf-8", errors="replace"))
    src, root, prefix, why = source_check(src_raw, meta.get("skill_dir"), out,
                                          [f["path"] for f in files], getattr(args, "_cfg", None) or {})
    if why:
        return memo(why)
    proc = _git(root, "apply", *_dir_arg(prefix), str(out))
    if proc.returncode != 0:
        return memo(f"git apply 실패 — {_first(proc)}")
    lines = [APPLIED.format(source=src)] + [f"- {f['path']} +{f['added']} −{f['removed']}" for f in files]
    shown.record(job.parent, "skill_patch", "patch", job.name, key=key, lines=lines, path=str(src))
    return {"status": "applied", "source": str(src), "files": files, "lines": lines}, OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill_patch.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("key", metavar="KEY", help="작업 키")
    parser.add_argument("--skill-dir", metavar="SK",
                        help="분석 스킬 디렉토리(5-1 Skill 결과의 `Base directory for this skill:`). patch를 만들 때 필수")
    parser.add_argument("--name", required=True, metavar="analyzer.skill", help="분석 스킬 이름(`analyzers.<카테고리>.skill`)")
    parser.add_argument("--source", metavar="SRC", help="patch를 만들 때만: 분석 스킬 소스 폴더(없으면 config analyzers.<카테고리>.source). --apply와 함께 못 쓴다")
    parser.add_argument("--apply", action="store_true",
                        help="만든 patch를 스킬 소스 워킹 트리에 git apply(사용자가 '적용'을 고른 뒤에만, 커밋·push 없음)")
    parser.add_argument("--sha", metavar="sha256", help="--apply: 보인 patch의 sha256(`스킬 소스 적용 대기:` 줄)")
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
        if args.apply:
            doc, code = run_apply(args, defaults)
        elif not args.skill_dir:
            raise Usage("--skill-dir가 필요하다(patch 만들기) — 적용은 --apply --sha")
        else:
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
