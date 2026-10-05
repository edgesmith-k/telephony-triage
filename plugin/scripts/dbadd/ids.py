"""`check-ids`·`renumber`: ID 중복·충돌 검사와 브랜치 안 "내 ID" 옮기기 (contracts.md §renumber 참조)."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from common import gitscope, issuedb
from common.exitcodes import CHECK_FAILED, OK

from .core import CAUSE_ID_RE, GENERATED, TYPE_ID_RE, UsageError, _db, _num


def collect_ids(root: Path) -> dict[str, list[str]]:
    """ID → 정의 위치(유형 디렉토리 기준 type.md 경로) 목록."""
    config = issuedb.load_config(root)
    found: dict[str, list[str]] = {}
    for path in issuedb.type_files(root, config):
        data = issuedb.read_frontmatter(path)
        rel = path.relative_to(root).as_posix()
        found.setdefault(str(data.get("id")), []).append(rel)
        for c in data.get("causes") or []:
            found.setdefault(str(c.get("id")), []).append(rel)
    return found


def _base_trees(db: Path, base: str, temp: Path) -> tuple[dict, dict]:
    try:
        mb = gitscope.merge_base(db, base)
        mine_root = gitscope.materialize_ref(db, mb, temp / "merge-base")
        base_root = gitscope.materialize_ref(db, base, temp / "base")
    except gitscope.GitError as exc:
        raise UsageError(str(exc)) from exc
    return collect_ids(mine_root), collect_ids(base_root)


def cmd_check_ids(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    current = collect_ids(db)
    duplicates = [{"id": k, "files": v} for k, v in sorted(current.items()) if len(v) > 1]
    conflicts, mine = [], []
    if args.base:
        temp = Path(tempfile.mkdtemp(prefix="tt-ids-"))
        try:
            merge_ids, base_ids = _base_trees(db, args.base, temp)
        finally:
            shutil.rmtree(temp, ignore_errors=True)
        mine = sorted(k for k in current if k not in merge_ids)
        conflicts = [{"id": k, "mine": current[k], "base": base_ids[k]} for k in mine if k in base_ids]
    result = {"db": str(db), "duplicates": duplicates, "mine": mine, "conflicts": conflicts}
    return result, (CHECK_FAILED if duplicates or conflicts else OK)


def _next_id(old: str, pools: list[dict]) -> str:
    if CAUSE_ID_RE.match(old):
        prefix = old.rsplit("-", 1)[0]
        nums = [_num(k) for pool in pools for k in pool if CAUSE_ID_RE.match(k) and k.rsplit("-", 1)[0] == prefix]
        return f"{prefix}-{max(nums or [0]) + 1:02d}"
    prefix = old.split("-")[0]
    nums = [_num(k) for pool in pools for k in pool if TYPE_ID_RE.match(k) and k.split("-")[0] == prefix]
    return f"{prefix}-{max(nums or [0]) + 1:03d}"


def cmd_renumber(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    old = args.old_id
    if not (CAUSE_ID_RE.match(old) or TYPE_ID_RE.match(old)):
        raise UsageError(f"유형·원인 ID 형식이 아닙니다: {old}")
    current = collect_ids(db)
    if old not in current:
        raise UsageError(f"{old}가 이 트리에 없습니다.")
    temp = Path(tempfile.mkdtemp(prefix="tt-renumber-"))
    try:
        merge_ids, base_ids = _base_trees(db, args.base, temp)
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    if old in merge_ids:
        raise UsageError(f"{old}는 merge-base(main)에 이미 있는 ID입니다. main에 들어간 ID는 바꾸지 않는다 "
                         "(사후 정리는 메인테이너 수동, 06-collaboration.md §6.3).")
    new = _next_id(old, [current, base_ids])
    token = re.compile(rf"(?<![A-Za-z0-9]){re.escape(old)}(?![0-9])")
    files, renamed = [], []
    tracked = gitscope.git(db, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
    for rel in sorted(filter(None, set(tracked))):
        path = db / rel
        if not path.is_file() or rel in GENERATED or rel.endswith("/README.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if token.search(text):
            path.write_text(token.sub(new, text), encoding="utf-8", newline="\n")
            files.append(rel)
    for path in sorted(db.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if ".git" in path.parts or not token.search(path.name):
            continue
        dest = path.with_name(token.sub(new, path.name))
        path.rename(dest)
        renamed.append({"from": path.relative_to(db).as_posix(), "to": dest.relative_to(db).as_posix()})
    return {"old": old, "new": new, "files": files, "renamed": renamed,
            "next": f"db_lint.py --changed {args.base} --residual {old}={new}"}, OK
