#!/usr/bin/env python3
"""mask_pii.py — 개인정보 마스킹 (contracts.md §3.2, 08-safety.md §8).

    mask_pii.py <file...> [--in-place | --out <file>] [--db <path>]
        치환 모드. 파일마다 마스커 하나(같은 값 = 같은 번호, 기존 토큰 다음 번호부터).
        --in-place/--out이 없으면 파일 하나의 결과를 stdout으로 낸다.
    mask_pii.py (<file...> | --changed <ref> | --staged) --check [--db <path>]
        검사 모드. 마스킹되지 않은 식별자가 있으면 목록(JSON)과 종료 코드 1.
        --staged는 index 내용, --changed는 `git merge-base <ref> HEAD` 이후 바뀐 파일의
        워킹 트리 내용을 본다(contracts.md §3.2 공통 규칙). 값은 출력하지 않는다.
    mask_pii.py --events <json> --out <json> [--db <path>]
        외부에서 받은 이벤트 JSON의 `msg`와 `fields`를 마스킹하고 `masked: true`를 붙인다.
        `events` 목록이 없는 JSON(예: Jira 응답)은 모든 문자열 값을 마스킹한다
        (08-safety.md §8.1). 분석 경로의 logcat은 `parse_logcat.py parse --mask`를 쓴다.

`mask.allow_patterns`는 이슈 DB(`--db`, 없으면 cwd의 이슈 DB)의 `issue-db.config.yaml`에서
읽는다. 이슈 DB를 찾지 못하면 예외 없이 마스킹한다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, dbpath, masking, site_defaults  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402


class UsageError(Exception):
    pass


def _db(arg: str | None) -> Path | None:
    try:
        return dbpath.resolve(arg)
    except dbpath.DbPathError:
        if arg:
            raise
        return None


def _allow(db: Path | None) -> list[str]:
    if db is None:
        return []
    return list((compat.load_db_config(db).get("mask") or {}).get("allow_patterns") or [])


def _git(db: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(db), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise UsageError(f"git {' '.join(args)} 실패: {proc.stderr.strip()}")
    return proc.stdout


def _scope_files(db: Path, changed: str | None, staged: bool) -> list[tuple[str, str]]:
    """`[(표시 경로, 내용)]`. 삭제된 파일은 뺀다."""
    out = []
    if staged:
        names = _git(db, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0")
        for name in filter(None, names):
            raw = subprocess.run(["git", "-C", str(db), "show", f":{name}"], capture_output=True)
            out.append((name, raw.stdout))
    else:
        base = _git(db, "merge-base", changed, "HEAD").strip()
        names = _git(db, "diff", "--name-only", "--diff-filter=ACMR", "-z", base).split("\0")
        names += _git(db, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
        for name in sorted(set(filter(None, names))):
            path = db / name
            if path.is_file():
                out.append((name, path.read_bytes()))
    return [(name, data.decode("utf-8", errors="replace")) for name, data in out if b"\0" not in data]


def run_check(args, db: Path | None) -> dict:
    if args.changed or args.staged:
        if db is None:
            raise UsageError("--changed/--staged는 이슈 DB(--db 또는 cwd)가 필요합니다.")
        targets = _scope_files(db, args.changed, args.staged)
    else:
        targets = []
        for name in args.files:
            path = Path(name)
            if not path.is_file():
                raise UsageError(f"파일이 없습니다: {path}")
            targets.append((name, path.read_text(encoding="utf-8", errors="replace")))
    masker = masking.new_masker(allow_patterns=_allow(db))
    detections = []
    for name, text in targets:
        for line_no, line in enumerate(text.splitlines(), 1):
            for hit in masker.find(line):
                detections.append({"path": name, "line": line_no, "col": hit["start"] + 1, "kind": hit["kind"]})
    return {"checked": len(targets), "detections": detections}


def run_replace(args, db: Path | None) -> tuple[dict, str | None]:
    if not args.files:
        raise UsageError("파일을 주세요.")
    if len(args.files) > 1 and not args.in_place:
        raise UsageError("파일이 여럿이면 --in-place를 쓰세요.")
    allow = _allow(db)
    results, stdout_text = [], None
    for name in args.files:
        path = Path(name)
        if not path.is_file():
            raise UsageError(f"파일이 없습니다: {path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        masker = masking.new_masker(text, allow)
        masked = "\n".join(masker(line) for line in text.split("\n"))
        if args.in_place:
            path.write_text(masked, encoding="utf-8", newline="\n")
        elif args.out:
            Path(args.out).write_text(masked, encoding="utf-8", newline="\n")
        else:
            stdout_text = masked
        results.append({"path": name, "replacements": dict(sorted(masker.counts.items()))})
    return {"files": results}, stdout_text


def _mask_tree(value, masker):
    if isinstance(value, str):
        return masker(value)
    if isinstance(value, list):
        return [_mask_tree(v, masker) for v in value]
    if isinstance(value, dict):
        return {k: _mask_tree(v, masker) for k, v in value.items()}
    return value


def run_events(args, db: Path | None) -> dict:
    if not args.out:
        raise UsageError("--events는 --out이 필요합니다.")
    try:
        doc = json.loads(Path(args.events).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"--events를 읽을 수 없습니다: {exc}") from exc
    masker = masking.new_masker(json.dumps(doc, ensure_ascii=False), _allow(db))
    if isinstance(doc, dict) and isinstance(doc.get("events"), list):
        events = []
        for event in doc["events"]:
            event = dict(event)
            if isinstance(event.get("msg"), str):
                event["msg"] = masker(event["msg"])
            event["fields"] = {
                k: masker.mask_value(v) if isinstance(v, str) else v
                for k, v in (event.get("fields") or {}).items()
            }
            events.append(event)
        doc = dict(doc, events=events, masked=True)
        mode = "events"
    else:
        doc = _mask_tree(doc, masker)
        if isinstance(doc, dict):
            doc["masked"] = True
        mode = "text"
    Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8", newline="\n")
    return {"out": args.out, "mode": mode, "replacements": dict(sorted(masker.counts.items()))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mask_pii.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--check", action="store_true")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--changed", metavar="REF")
    scope.add_argument("--staged", action="store_true")
    parser.add_argument("--events")
    parser.add_argument("--out")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--db", default=None)
    parser.add_argument("--json", action="store_true", help="요약을 JSON으로 (검사·이벤트 모드는 항상 JSON)")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    site_defaults.load_or_exit(args.plugin_root)
    try:
        db = _db(args.db)
        if args.events:
            result = run_events(args, db)
        elif args.check:
            if args.files and (args.changed or args.staged):
                raise UsageError("파일 목록과 --changed/--staged는 함께 쓰지 않습니다.")
            if not args.files and not (args.changed or args.staged):
                raise UsageError("검사할 파일이나 --changed/--staged를 주세요.")
            result = run_check(args, db)
            print(json.dumps(result, ensure_ascii=False, indent=1))
            for d in result["detections"]:
                print(f"마스킹 안 됨: {d['path']}:{d['line']}:{d['col']} {d['kind']}", file=sys.stderr)
            return CHECK_FAILED if result["detections"] else OK
        else:
            if args.changed or args.staged:
                raise UsageError("--changed/--staged는 --check와 함께 씁니다.")
            result, text = run_replace(args, db)
            if text is not None:
                sys.stdout.write(text)
                if args.json:
                    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
                return OK
    except (UsageError, dbpath.DbPathError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
