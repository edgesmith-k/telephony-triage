#!/usr/bin/env python3
"""사외 초안을 사내 레포로 재반입한다 (15-local-draft.md §15.6).

**통째로 교체하지 않는다.** 반입 기준선 `.draft-manifest.json`(마지막으로
반입한 사외 초안의 버전 표시와 파일 경로·해시 목록)과 비교해서 처리한다.

규칙
- `SITE_PATHS`에 있는 경로는 건드리지 않는다.
- 기준선 이후 **사내에서 고친 사외 파일**(현재 해시 ≠ 기준선 해시)이 있으면
  목록을 보여주고 **멈춘다** (종료 코드 1). 사외로 옮길 요약을 만들거나
  되돌린 뒤 다시 실행한다.
- 새 초안에 있는 파일은 덮어쓴다.
- 기준선에 있었는데 새 초안에 없는 파일은 **지운다** (사외에서 지운 것).
- 기준선에도 새 초안에도 없는 파일(사내에서 새로 만든 비-`SITE_PATHS` 파일)은
  **지우지 않고** 목록으로 보고한다. 사내 전용이면 `SITE_PATHS`로 옮기라고
  안내한다.
- `.local-draft`(사외 PC 전용 표식)는 원본에 있어도 가져오지 않는다.
- 끝나면 새 초안 기준으로 `.draft-manifest.json`을 다시 쓴다.
  첫 반입이면 기준선 없이 전체를 복사하고 기준선을 만든다.

CLI:
    python3 tools/import_draft.py <새 사외 초안 경로> [--dest <사내 레포>]
        [--label <버전 표시>] [--dry-run] [--json]

종료 코드 (contracts.md §종료 코드)
    0  반입 완료 (경고 포함)
    1  사내에서 고친 사외 파일이 있어 멈춤
    2  사용 오류·환경 오류
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import shutil
import sys
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
}

OK, CHECK_FAILED, USAGE = 0, 1, 2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_site_paths(dest: Path, source: Path) -> list[str]:
    """`SITE_PATHS` 목록. 사내 레포 것이 우선이고, 없으면 새 초안 것을 쓴다."""
    for base in (dest, source):
        path = base / SITE_PATHS_FILE
        if path.is_file():
            lines = []
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    lines.append(line)
            return lines
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


def walk(root: Path, site_patterns: list[str]) -> dict[str, Path]:
    """`SITE_PATHS`와 항상 제외 대상을 뺀 파일 목록 {상대경로: 절대경로}."""
    out: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in ALWAYS_SKIP for part in rel_parts):
            continue
        rel = path.relative_to(root).as_posix()
        if is_site_path(rel, site_patterns):
            continue
        out[rel] = path
    return out


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

    locally_modified: list[dict] = []
    if not first_import:
        for rel, digest in baseline.items():
            current = dest_files.get(rel)
            if current is None:
                # 사내에서 지운 사외 파일. 새 초안에 있으면 다시 놓인다.
                continue
            now = sha256(current)
            if now != digest:
                locally_modified.append({"path": rel, "baseline": digest, "current": now})

    to_write, to_delete, untouched = [], [], []
    for rel, path in src_files.items():
        target = dest / rel
        if target.is_file() and sha256(target) == sha256(path):
            untouched.append(rel)
        else:
            to_write.append(rel)
    for rel in baseline:
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
    new_in_site = sorted(rel for rel in dest_files if rel not in baseline and rel not in src_files)

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
        "source_files": src_files,
    }


def apply(result: dict, source: Path, dest: Path) -> None:
    for rel in result["to_write"]:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)
    for rel in result["to_delete"]:
        target = dest / rel
        if target.is_file():
            target.unlink()
            parent = target.parent
            while parent != dest and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent


def write_manifest(result: dict, source: Path, dest: Path) -> None:
    files = {rel: sha256(path) for rel, path in sorted(result["source_files"].items())}
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
    if source == dest:
        print("원본과 대상이 같습니다.", file=sys.stderr)
        return USAGE

    result = plan(source, dest, args.label)

    if result["locally_modified"]:
        payload = {
            "status": "stopped",
            "reason": "locally-modified",
            "locally_modified": result["locally_modified"],
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                "기준선 이후 사내에서 고친 사외 파일이 있어 멈춥니다. "
                "사외로 옮길 요약을 만들거나 되돌린 뒤 다시 실행하세요 "
                "(15-local-draft.md §15.6):",
                file=sys.stderr,
            )
            for item in result["locally_modified"]:
                print(f"  - {item['path']}", file=sys.stderr)
        return CHECK_FAILED

    if not args.dry_run:
        apply(result, source, dest)
        write_manifest(result, source, dest)

    if args.json:
        payload = {k: v for k, v in result.items() if k != "source_files"}
        payload["status"] = "dry-run" if args.dry_run else "applied"
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(report(result, applied=not args.dry_run))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
