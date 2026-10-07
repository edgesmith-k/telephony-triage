#!/usr/bin/env python3
"""사외 초안을 사내 레포로 재반입한다 (15-local-draft.md §15.6).

**통째로 교체하지 않는다.** 반입 기준선 `.draft-manifest.json`(마지막으로
반입한 사외 초안의 버전 표시와 파일 경로·해시 목록)과 비교해서 처리한다.

규칙
- `SITE_PATHS`에 있는 경로는 건드리지 않는다.
- 기준선 이후 **사내에서 고친 사외 파일**(현재 해시 ≠ 기준선 해시)이 있으면
  목록을 보여주고 **멈춘다** (종료 코드 1). 그 변경 내용을 사용자가 사내 정보 없는
  문장으로 직접 사외에 전달해 반영하거나(파일 반출 없음), 되돌린 뒤 다시 실행한다.
- 새 초안에 있는 파일은 덮어쓴다.
- 기준선에 있었는데 새 초안에 없는 파일은 **지운다** (사외에서 지운 것).
- 기준선에도 새 초안에도 없는 파일(사내에서 새로 만든 비-`SITE_PATHS` 파일)은
  **지우지 않고** 목록으로 보고한다. 사내 전용이면 `SITE_PATHS`로 옮기라고
  안내한다.
- `.local-draft`(사외 PC 전용 표식)는 원본에 있어도 가져오지 않는다.
- 파일 목록은 git 무시 규칙을 따른다: git 레포면 `git ls-files -co --exclude-standard`
  (`git add -A`와 같은 기준), 아니면 원본 `.gitignore`만 적용한다(PC 전역 무시 제외). 반입 뒤 모습
  (경계 검사·사내 새 파일 보고)에는 들어오는 `.gitignore`도 적용한다. git 필요.
- 현재 사내 파일이 이미 새 초안과 같으면 사내에서 고친 것으로 보지 않는다.
- 새 초안 `SITE_PATHS`에만 있는 줄은 보고만 한다(사내 `SITE_PATHS`는 쓰지 않는다).
- 끝나면 새 초안 기준으로 `.draft-manifest.json`을 다시 쓴다.
  첫 반입이면 기준선 없이 전체를 복사하고 기준선을 만든다. 첫 반입이라도 대상에
  같은 경로의 다른 파일이 있으면 위 "사내에서 고친 파일"처럼 멈춘다.

적용 순서 (사내 레포를 반쯤 바뀐 채로 두지 않는다)
    1. staging: 새 초안 파일을 대상 옆 임시 디렉토리에 복사하고 계획 때의 해시와 대조
    2. 검증: `--check-boundary`면 반입 뒤 모습(staging + 남는 사내 파일)에
       `check_boundary.py --mode site` 규칙을 돌린다. 위반이면 대상은 그대로
    3. 활성 전환: 대상 파일을 백업하고 staging 파일을 `os.replace`로 옮긴 뒤 지울 파일을
       지우고 기준선을 쓴다. 옮긴 파일 해시를 다시 대조한다
    4. 3에서 무엇이든 실패하면 백업으로 되돌린다 (파일·새 디렉토리·기준선)

CLI:
    python3 tools/import_draft.py <새 사외 초안 경로> [--dest <사내 레포>]
        [--label <버전 표시>] [--dry-run] [--check-boundary] [--json]

종료 코드 (contracts.md §종료 코드)
    0  반입 완료 (경고 포함)
    1  사내에서 고친 사외 파일이 있거나 경계 검사 위반이라 멈춤 (대상 변경 없음)
    2  사용 오류·환경 오류 (적용 중 실패면 되돌린 뒤)
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = ".draft-manifest.json"
SITE_PATHS_FILE = "SITE_PATHS"
MANIFEST_SCHEMA = 1

# 어느 쪽에서도 반입 대상이 아닌 경로.
ALWAYS_SKIP = {
    ".git",
    ".local-draft",  # 사외 PC 전용 표식 (15-local-draft.md §15.2)
    "__pycache__",
    ".pytest_cache",
    MANIFEST,
}

OK, CHECK_FAILED, USAGE = 0, 1, 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_lines(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def load_site_paths(dest: Path, source: Path) -> list[str]:
    """`SITE_PATHS` 목록. 사내 레포 것이 우선이고, 없으면 새 초안 것을 쓴다."""
    for base in (dest, source):
        path = base / SITE_PATHS_FILE
        if path.is_file():
            return _read_lines(path)
    return []


def is_site_path(rel: str, patterns: list[str]) -> bool:
    """`SITE_PATHS` 한 줄과 맞는지. 끝이 `/`면 그 디렉토리 아래 전부,
    `*`가 있으면 glob, 그 밖에는 정확히 그 경로다."""
    for pattern in patterns:
        if pattern.endswith("/"):
            if rel == pattern.rstrip("/") or rel.startswith(pattern):
                return True
        elif any(ch in pattern for ch in "*?["):
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(
                rel, pattern.rstrip("/") + "/*"
            ):
                return True
        elif rel == pattern:
            return True
    return False


def _git(root: Path, args: list[str], stdin: str = "", ok=(0,)) -> str:
    try:
        proc = subprocess.run(["git", *args], cwd=root, input=stdin.encode("utf-8"),
                              capture_output=True, timeout=60)
    except FileNotFoundError as exc:
        raise subprocess.SubprocessError(f"git이 필요합니다: {exc}") from exc
    if proc.returncode not in ok:
        raise subprocess.SubprocessError(
            f"git {args[0]} 실패 ({proc.returncode}): {proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout.decode("utf-8")


def _is_gitignore(rel: str) -> bool:
    return rel.rsplit("/", 1)[-1] == ".gitignore"


def _ignored(work_tree: Path, rels: set[str]) -> set[str]:
    """`work_tree`의 `.gitignore`들로 무시되는 경로 (PC 전역 무시 제외). 경로는 없어도 된다.

    git 무시 규칙은 레포 안에서만 돈다. 빈 임시 git 디렉토리를 붙여 쓴다
    (상위 디렉토리, 예를 들어 홈의 git 레포를 찾아가지 않는다).
    """
    if not any(_is_gitignore(rel) for rel in rels):  # 없으면 git 없이도 돈다
        return set()
    with tempfile.TemporaryDirectory(prefix="tt-ignore-") as git_dir:
        _git(work_tree, ["init", "-q", "--bare", "--template=", git_dir])
        # check-ignore는 무시된 것이 없으면 종료 1이다.
        out = _git(work_tree, ["--git-dir", git_dir, "--work-tree", str(work_tree),
                               "-c", f"core.excludesFile={os.devnull}",
                               "check-ignore", "--no-index", "--stdin", "-z"],
                   "\0".join(sorted(rels)), ok=(0, 1))
    return {r for r in out.split("\0") if r}


def walk(root: Path, site_patterns: list[str]) -> dict[str, Path]:
    """`SITE_PATHS`·항상 제외 대상·git 무시 파일을 뺀 파일 목록 {상대경로: 절대경로}.

    git 레포(사내 레포)면 `git add -A`와 같은 기준이고, 아니면(압축 푼 초안) 원본
    `.gitignore`만 적용한다. 사외 PC의 전역 무시는 사내에서 재현되지 않으므로 끈다.
    """
    if (root / ".git").exists():
        out = _git(root, ["ls-files", "-co", "--exclude-standard", "-z"])
        rels = {r for r in out.split("\0") if r}
    else:
        rels = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
        rels -= _ignored(root, rels)
    files: dict[str, Path] = {}
    for rel in sorted(rels):
        if any(part in ALWAYS_SKIP for part in rel.split("/")):
            continue
        if is_site_path(rel, site_patterns):
            continue
        path = root / rel
        if path.is_file():
            files[rel] = path
    return files


def load_manifest(dest: Path) -> dict | None:
    path = dest / MANIFEST
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"{path}를 읽을 수 없습니다: {exc}")
    if data.get("schema") != MANIFEST_SCHEMA:
        raise SystemExit(
            f"{path}의 schema={data.get('schema')}를 이 도구가 모릅니다 "
            f"(아는 값: {MANIFEST_SCHEMA})."
        )
    return data


def plan(source: Path, dest: Path, label: str | None) -> dict:
    site_patterns = load_site_paths(dest, source)
    src_files = walk(source, site_patterns)
    dest_files = walk(dest, site_patterns)
    manifest = load_manifest(dest)
    baseline: dict[str, str] = (manifest or {}).get("files", {})
    first_import = manifest is None
    # The local protection registry itself is never replaced by an incoming draft.
    if (dest / SITE_PATHS_FILE).exists():
        src_files.pop(SITE_PATHS_FILE, None)
    dest_files.pop(SITE_PATHS_FILE, None)

    source_hashes = {rel: sha256(path) for rel, path in src_files.items()}
    site_paths_new: list[str] = []
    if (dest / SITE_PATHS_FILE).is_file() and (source / SITE_PATHS_FILE).is_file():
        site_paths_new = sorted(set(_read_lines(source / SITE_PATHS_FILE))
                                - set(_read_lines(dest / SITE_PATHS_FILE)))

    locally_modified: list[dict] = []
    if not first_import:
        for rel, digest in baseline.items():
            if rel == SITE_PATHS_FILE or is_site_path(rel, site_patterns):
                continue
            current = dest_files.get(rel)
            if current is None:
                # 사내에서 지운 사외 파일. 새 초안에 있으면 다시 놓인다.
                continue
            now = sha256(current)
            # 이미 새 초안과 같으면 덮어써도 잃는 것이 없다 (아래에서 unchanged).
            if now != digest and now != source_hashes.get(rel):
                locally_modified.append({"path": rel, "baseline": digest, "current": now})

    to_write, to_delete, untouched = [], [], []
    for rel, path in src_files.items():
        target = _contained(dest, rel)
        if target.is_file() and sha256(target) == source_hashes[rel]:
            untouched.append(rel)
        else:
            to_write.append(rel)
            if rel not in baseline and target.exists():
                locally_modified.append({"path": rel, "baseline": None,
                                         "current": sha256(target) if target.is_file() else "directory"})
    for rel in baseline:
        _contained(dest, rel)
        if rel not in src_files and rel in dest_files:
            to_delete.append(rel)

    site_only = sorted(
        rel
        for rel in (
            p.relative_to(dest).as_posix()
            for p in dest.rglob("*")
            if p.is_file() and not any(part in ALWAYS_SKIP for part in p.relative_to(dest).parts)
        )
        if is_site_path(rel, site_patterns)
    )
    new_in_site = {rel for rel in dest_files if rel not in baseline and rel not in src_files}
    # 반입 뒤 무시될 파일 제외. 기준은 원본 `.gitignore`만이다(사내에만 있는 `.gitignore`는 이미 dest_files에 반영됨).
    # `final_view`는 반입 뒤 `.gitignore` 전부를 쓴다. 차이는 사내 전용 `.gitignore`가 원본 쪽 무시를 바꾸는 드문 경우뿐이다.
    new_in_site = sorted(new_in_site - _ignored(source, new_in_site | set(src_files)))

    return {
        "first_import": first_import,
        "label": label or (manifest or {}).get("label") or source.name,
        "site_patterns": site_patterns,
        "locally_modified": sorted(locally_modified, key=lambda item: item["path"]),
        "to_write": sorted(to_write),
        "to_delete": sorted(to_delete),
        "unchanged": sorted(untouched),
        "kept_site_paths": site_only,
        "kept_new_in_site": new_in_site,
        "site_paths_new": site_paths_new,
        "source_files": src_files,
        "source_hashes": source_hashes,
    }


def _contained(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"반입 루트 밖 경로: {relative}")
    for part in (path, *path.parents):
        if part == root.parent:
            break
        if part.is_symlink() or getattr(part, "is_junction", lambda: False)():
            raise ValueError(f"반입 경로 symlink/junction: {relative}")
    return path


class BoundaryViolation(ValueError):
    def __init__(self, findings: list):
        super().__init__(f"경계 검사 위반 {len(findings)}건")
        self.findings = findings


def _stage(result: dict, source: Path, staging: Path) -> dict[str, Path]:
    """새 초안 파일을 staging에 복사하고 계획 때 해시와 대조한다. 대상은 건드리지 않는다."""
    staged = {}
    for rel in result["to_write"]:
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_contained(source, rel), target)
        if sha256(target) != result["source_hashes"][rel]:
            raise ValueError(f"staging 사본이 계획 때와 다릅니다 (반입 중 원본이 바뀜?): {rel}")
        staged[rel] = target
    return staged


def _activate(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, target)


def _verify_active(result: dict, dest: Path) -> None:
    for rel in result["to_write"]:
        if sha256(dest / rel) != result["source_hashes"][rel]:
            raise ValueError(f"활성 전환 뒤 해시가 다릅니다: {rel}")
    for rel in result["to_delete"]:
        if (dest / rel).exists():
            raise ValueError(f"지울 파일이 남아 있습니다: {rel}")


def final_view(result: dict, dest: Path, staged: dict[str, Path]) -> dict[str, Path]:
    """반입 뒤 사내 레포의 비-SITE_PATHS 파일 모습 {상대경로: 지금 읽을 경로}."""
    view = {rel: path for rel, path in walk(dest, result["site_patterns"]).items()
            if rel not in result["to_delete"]}
    view.update(staged)
    # 들어오는 `.gitignore`가 반입 뒤 무시할 사내 파일(.venv 등)은 뺀다 (반입 뒤 `git add -A`와 같게).
    with tempfile.TemporaryDirectory(prefix="tt-ignore-") as rules:
        for rel in filter(_is_gitignore, view):
            (Path(rules) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(view[rel], Path(rules) / rel)
        ignored = _ignored(Path(rules), set(view))
    return {rel: path for rel, path in sorted(view.items()) if rel not in ignored}


def boundary_check(dest: Path):
    """`--check-boundary`용 검사 함수. `check_boundary.py`는 이 도구 옆에 있다."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check_boundary

    def check(result: dict, staged: dict[str, Path]) -> None:
        findings = check_boundary.scan(dest, "site", files=final_view(result, dest, staged))
        if findings:
            raise BoundaryViolation(findings)
    return check


def apply(result: dict, source: Path, dest: Path, check=None) -> None:
    """staging → 검증(`check`) → 활성 전환. 활성 전환 중 실패하면 파일·새 디렉토리·기준선을 되돌린다."""
    if result["locally_modified"]:
        raise ValueError("사내 변경 파일이 있어 반입할 수 없습니다")
    paths = sorted(set(result["to_write"] + result["to_delete"] + [MANIFEST]))
    targets = {rel: _contained(dest, rel) for rel in paths}
    with tempfile.TemporaryDirectory(prefix="tt-import-", dir=dest.parent) as work:
        staged = _stage(result, source, Path(work) / "staging")
        if check is not None:
            check(result, staged)
        backup_dir = Path(work) / "backup"
        backup_dir.mkdir()
        existing_dirs = {p for p in dest.rglob("*") if p.is_dir()}
        backups = {}
        for i, (rel, target) in enumerate(targets.items()):
            if target.exists():
                backup = backup_dir / str(i)
                shutil.copy2(target, backup)
                backups[rel] = backup
        try:
            for rel in result["to_write"]:
                _activate(staged[rel], targets[rel])
            for rel in result["to_delete"]:
                targets[rel].unlink(missing_ok=True)
            write_manifest(result, source, dest)
            _verify_active(result, dest)
        except BaseException:
            for rel, target in targets.items():
                if rel in backups:
                    os.replace(backups[rel], target)
                else:
                    target.unlink(missing_ok=True)
            for directory in sorted((p for p in dest.rglob("*") if p.is_dir() and p not in existing_dirs),
                                    key=lambda p: len(p.parts), reverse=True):
                directory.rmdir()
            raise


def write_manifest(result: dict, source: Path, dest: Path) -> None:
    # SITE_PATHS는 첫 반입 뒤 사내 소유라 기준선에 넣지 않는다 (반입마다 기준선이 같도록).
    files = {rel: digest for rel, digest in sorted(result["source_hashes"].items()) if rel != SITE_PATHS_FILE}
    payload = {
        "schema": MANIFEST_SCHEMA,
        "label": result["label"],
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source),
        "files": files,
    }
    (dest / MANIFEST).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def report(result: dict, applied: bool) -> str:
    lines = []
    if result["first_import"]:
        lines.append("첫 반입입니다 (기준선 없음). 전체를 복사하고 기준선을 만듭니다.")
    lines.append(
        f"덮어씀 {len(result['to_write'])} / 지움 {len(result['to_delete'])} / "
        f"그대로 {len(result['unchanged'])}"
    )
    if result["to_delete"]:
        lines.append("사외에서 지워져 사내에서도 지운 파일:")
        lines += [f"  - {rel}" for rel in result["to_delete"]]
    if result["kept_new_in_site"]:
        lines.append(
            "사내에서 새로 만든 비-SITE_PATHS 파일 (지우지 않았습니다). "
            "사내 전용이면 SITE_PATHS로 옮기세요:"
        )
        lines += [f"  - {rel}" for rel in result["kept_new_in_site"]]
    if result["site_paths_new"]:
        lines.append(f"새 초안 SITE_PATHS에만 있는 줄: {', '.join(result['site_paths_new'])} (경고 참고)")
    if result["kept_site_paths"]:
        lines.append(f"SITE_PATHS 경로 {len(result['kept_site_paths'])}개는 건드리지 않았습니다.")
    if not applied:
        lines.append("(--dry-run: 아무것도 바꾸지 않았습니다)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="import_draft.py", description=__doc__)
    parser.add_argument("source", help="새 사외 초안 경로")
    parser.add_argument("--dest", default=".", help="사내 플러그인 레포 (기본: 현재 디렉토리)")
    parser.add_argument("--label", default=None, help="기준선에 적을 버전 표시")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-boundary", action="store_true",
                        help="활성 전환 전에 반입 뒤 모습을 check_boundary.py --mode site로 검사")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    dest = Path(args.dest).resolve()
    if not source.is_dir():
        print(f"사외 초안 경로가 없습니다: {source}", file=sys.stderr)
        return USAGE
    if not dest.is_dir():
        print(f"사내 레포 경로가 없습니다: {dest}", file=sys.stderr)
        return USAGE
    if source == dest or source.is_relative_to(dest) or dest.is_relative_to(source):
        print("원본과 대상 경로가 겹칩니다.", file=sys.stderr)
        return USAGE

    try:
        result = plan(source, dest, args.label)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    site_paths_new = result["site_paths_new"]
    if site_paths_new and not args.json:
        print(f"경고: 새 초안 SITE_PATHS에만 있는 줄: {', '.join(site_paths_new)} — "
              "사내 SITE_PATHS에 직접 추가하세요 (아래에서 멈췄다면 추가한 뒤 다시 실행).", file=sys.stderr)

    if result["locally_modified"]:
        payload = {
            "status": "stopped",
            "reason": "locally-modified",
            "locally_modified": result["locally_modified"],
            "site_paths_new": site_paths_new,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                "기준선 이후 사내에서 고친 사외 파일이 있어 멈춥니다. "
                "변경 요지를 사용자가 직접 사외에 전달해 반영하거나(파일 반출 없음), 되돌린 뒤 다시 실행하세요 "
                "(15-local-draft.md §15.6):",
                file=sys.stderr,
            )
            for item in result["locally_modified"]:
                print(f"  - {item['path']}", file=sys.stderr)
        return CHECK_FAILED

    check = boundary_check(dest) if args.check_boundary else None
    try:
        if not args.dry_run:
            apply(result, source, dest, check)
        elif check is not None:
            with tempfile.TemporaryDirectory(prefix="tt-import-", dir=dest.parent) as work:
                check(result, _stage(result, source, Path(work) / "staging"))
    except BoundaryViolation as exc:
        import check_boundary
        if args.json:
            print(json.dumps({"status": "stopped", "reason": "boundary",
                              "violations": [vars(f) for f in exc.findings],
                              "site_paths_new": site_paths_new}, ensure_ascii=False, indent=2))
        else:
            print(f"{exc}. 사내 레포는 바뀌지 않았습니다:", file=sys.stderr)
            print(check_boundary.format_findings(exc.findings), file=sys.stderr)
        return CHECK_FAILED
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"반입 실패 (사내 레포는 바뀌지 않았거나 되돌렸습니다): {exc}", file=sys.stderr)
        return USAGE

    if args.json:
        payload = {k: v for k, v in result.items() if k not in ("source_files", "source_hashes")}
        payload["status"] = "dry-run" if args.dry_run else "applied"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(report(result, applied=not args.dry_run))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
