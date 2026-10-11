#!/usr/bin/env python3
"""db_regress.py — fixture 회귀 (contracts.md §fixture, 04-parser-matching.md §5.11 (4)).

    db_regress.py [--db <path>] (--all | --changed <ref> | --staged)
    db_regress.py [--db <path>] --events-diff <ref>

fixture마다 `parse_logcat.py parse --full --mask`와 `match_signatures.py --regress`(항상 회귀·검증
모드: 파일 전체, bonus 0, 피드백 가중치 끔, 모든 active 원인의 C 독립 평가)를 돌려
`contracts.md §fixture` 기대값과 비교한다. 판정은 S/C 값만 쓴다.

- 대상: active 유형의 fixture. `status`가 active가 아닌 원인의 fixture는 뺀다.
  `signatures_pending` 원인의 양성 fixture는 넣고 기본 기대값은 `"<유형 ID>:unresolved"`다.
- 범위: `--changed`/`--staged`면 바뀐 유형과 그 `related` 원인의 유형, 같은 카테고리의
  fixture(06-collaboration.md §6.8). `parser-rules/`·`schema/`·`issue-db.config.yaml`이 바뀌었으면
  전체(범위 확장 규칙). `--staged`는 index 내용으로 돈다.
- 실패 원인: 음성 fixture면 S=1이 된 유형과 증상 시그니처 전역 키, 양성이면 C=1인 원인과
  시그니처 전역 키. 실패가 **다른 유형의 원인**이 C=1이 된 것 때문이면 `allow-cause` op 초안.
- 정규식 시간 상한 초과(매처·extractor)는 실패다(04 §5.8 (4)).
- 파서 백엔드·외부 파서가 이슈 DB 고정값과 다르면 종료 코드 2(사람마다 결과가 달라지지 않게).
- `--events-diff <ref>`(R5 이벤트 변화, 05-verification.md §5.12 (1)): 현재 트리(`--db`)의 **모든** fixture를 `<ref>`
  트리의 parser-rules와 현재 parser-rules로 각각 파싱해 이벤트(줄 레코드 제외)를 비교한다. 이벤트 식별은
  `(ts, phone_id, tag, event)`이고 `fields`가 다르면 `changed`, 한쪽에만 있으면 `added`/`removed`다.
  `existing_changed`(= removed 또는 changed가 있음)는 `db_verify rules`가 R5 `needs-approval`로 바꾼다.
  이 모드는 판정하지 않으므로 종료 코드는 0(또는 2)이다.

종료 코드: 0 전부 통과, 1 실패 있음, 2 사용·환경 오류.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import match_signatures  # noqa: E402
import parse_logcat  # noqa: E402
from common import compat, dbpath, gitscope, issuedb, site_defaults, yamlio  # noqa: E402
from common import compiled as compiled_cache  # noqa: E402
from common.exitcodes import CHECK_FAILED, OK, USAGE  # noqa: E402
from common.fixtures import load_expectation, parse_name  # noqa: E402
from common.signatures import SignatureError  # noqa: E402

GLOBAL_PATHS = ("parser-rules/", "schema/", "issue-db.config.yaml")
DRAFTABLE = ("positive", "recurrence", "extra")


class UsageError(Exception):
    pass


def collect(db: issuedb.IssueDb) -> list[dict]:
    """회귀 대상 fixture 목록 `[{path, rel, type, fx, expect}]` (유형 ID·파일 이름 순)."""
    out = []
    for itype in sorted(db.types, key=lambda t: t.id):
        if not itype.active:
            continue
        causes = {c.id: c for c in itype.causes}
        pending = {c.id for c in itype.causes if c.pending}
        for path in sorted((itype.path / "fixtures").glob("*.log")):
            fx = parse_name(path.name)
            if fx is None:
                continue  # 이름 규칙 밖은 db_lint 오류다
            if fx.cause is not None:
                cause = causes.get(fx.cause)
                if cause is None or not cause.active:
                    continue
            out.append({
                "path": path,
                "rel": path.relative_to(db.root).as_posix(),
                "type": itype,
                "fx": fx,
                "expect": load_expectation(path, fx, pending),
            })
    return out


def scope_types(db: issuedb.IssueDb, changed: list[str]) -> set[str] | None:
    """바뀐 파일로 회귀할 유형 ID 집합. 전체면 None."""
    if any(name.startswith(GLOBAL_PATHS) for name in changed):
        return None
    touched: set[str] = set()
    for itype in db.types:
        rel = itype.path.relative_to(db.root).as_posix() + "/"
        if any(name.startswith(rel) for name in changed):
            touched.add(itype.id)
    selected = set(touched)
    for itype in db.types:
        if itype.id not in touched:
            continue
        for cause in itype.causes:
            for rid in cause.raw.get("related") or []:
                other = db.cause_by_id(str(rid))
                if other:
                    selected.add(other.type_id)
        selected |= {t.id for t in db.types if t.category == itype.category}
    return selected


def judge(item: dict, result: dict) -> dict:
    exp = item["expect"]
    fx = item["fx"]
    S = {t["type"]: t["S"] for t in result["types"]}
    sym_key = {t["type"]: t["signature"] for t in result["types"]}
    C = {c["cause"]: c["C"] for c in result["causes"]}
    cause_key = {c["cause"]: c["signature"] for c in result["causes"]}
    cause_type = {c["cause"]: c["type"] for c in result["causes"]}
    allowed = set(exp.also_allowed)
    reasons, drafts = [], []

    for err in result.get("errors") or []:
        reasons.append({"kind": "error", "signature": err.get("signature") or err.get("extractor"),
                        "message": err["error"]})

    def unexpected(except_ids: set[str]) -> list[str]:
        return sorted(c for c, v in C.items() if v and c not in except_ids and c not in allowed)

    top = exp.expect_top
    if top == "none":
        for type_id, value in sorted(S.items()):
            if value:
                reasons.append({"kind": "symptom", "type": type_id, "signature": sym_key[type_id],
                                "message": f"음성 fixture에서 {type_id}의 증상이 잡혔다"})
    elif top and top.endswith(":unresolved"):
        type_id = top.split(":", 1)[0]
        if not S.get(type_id):
            reasons.append({"kind": "missing", "type": type_id,
                            "message": f"{type_id}의 증상이 잡히지 않았다"})
        for cause in unexpected(set()):
            reasons.append({"kind": "cause", "cause": cause, "signature": cause_key[cause],
                            "message": f"{cause}가 C=1이다 (기대: 모든 원인 C=0)"})
    elif top:
        if not C.get(top):
            reasons.append({"kind": "missing", "cause": top, "message": f"{top}가 C=0이다"})
        owner = cause_type.get(top) or fx.type_id
        if S.get(owner) == 0:      # None(판정 불가)은 이미 kind: error로 실패
            reasons.append({"kind": "missing-symptom", "type": owner, "signature": None,
                            "message": f"{owner}의 증상이 잡히지 않았다 (S=0) — 양성 fixture는 소속 유형 S=1이어야 한다"})
        for cause in unexpected({top}):
            reasons.append({"kind": "cause", "cause": cause, "signature": cause_key[cause],
                            "message": f"{cause}도 C=1이다"})
    if exp.expect_not and C.get(exp.expect_not):
        reasons.append({"kind": "expect_not", "cause": exp.expect_not,
                        "signature": cause_key.get(exp.expect_not),
                        "message": f"{exp.expect_not}가 C=1이다 (기대: C=0)"})

    if fx.kind in DRAFTABLE:
        for reason in reasons:
            cause = reason.get("cause")
            if reason["kind"] == "cause" and cause and cause_type.get(cause) != fx.type_id:
                drafts.append({"op": "allow-cause", "fixture": f"fixtures/{fx.name}", "cause": cause})
    return {
        "fixture": item["rel"],
        "kind": fx.kind,
        "expect": exp.describe(),
        "status": "fail" if reasons else "pass",
        "S": sorted(t for t, v in S.items() if v),
        "C": sorted(c for c, v in C.items() if v),
        "reasons": reasons,
        "allow_cause_drafts": drafts,
    }


def parse_logs(paths: list[Path], rules_dir: Path, plugin_root: Path, defaults: dict) -> dict:
    """회귀·검증 모드 파싱: 파일 전체, 마스킹(멱등), UTC. `db_verify`도 이것을 쓴다."""
    args = Namespace(logs=[str(p) for p in paths], full=True, around=None, minutes=5, rules=str(rules_dir),
                     tz="UTC", year=None, mask=True, no_external=False)
    return parse_logcat.run_parse(args, plugin_root, defaults)


def _parse_fixture(path: Path, rules_dir: Path, plugin_root: Path, defaults: dict) -> dict:
    return parse_logs([path], rules_dir, plugin_root, defaults)


def all_fixtures(root: Path, config: dict) -> list[tuple[Path, str]]:
    """트리의 모든 fixture `(경로, DB 기준 경로)` — 상태와 무관 (R5 이벤트 diff 대상)."""
    out = []
    for type_md in issuedb.type_files(root, config):
        for path in sorted((type_md.parent / "fixtures").glob("*.log")):
            if parse_name(path.name) is not None:
                out.append((path, path.relative_to(root).as_posix()))
    return out


def _event_records(doc: dict) -> dict[tuple, list[str]]:
    out: dict[tuple, list[str]] = {}
    for e in doc.get("events") or []:
        if not e.get("event"):
            continue
        ident = (e["ts"], e.get("phone_id"), e.get("tag"), e["event"])
        out.setdefault(ident, []).append(json.dumps(e.get("fields") or {}, sort_keys=True, ensure_ascii=False))
    return out


def compare_events(before: dict, after: dict) -> dict:
    """한 fixture의 이벤트 변화 `{added, removed, changed}` (각각 `{ts, phone_id, tag, event, fields...}`)."""
    a, b = _event_records(before), _event_records(after)
    added, removed, changed = [], [], []
    for ident in sorted(set(a) | set(b), key=lambda k: tuple("" if x is None else str(x) for x in k)):
        old, new = sorted(a.get(ident, [])), sorted(b.get(ident, []))
        base = {"ts": ident[0], "phone_id": ident[1], "tag": ident[2], "event": ident[3]}
        rest_old = list(old)
        rest_new = []
        for item in new:
            if item in rest_old:
                rest_old.remove(item)
            else:
                rest_new.append(item)
        while rest_old and rest_new:
            changed.append({**base, "fields_before": json.loads(rest_old.pop(0)),
                            "fields_after": json.loads(rest_new.pop(0))})
        removed += [{**base, "fields": json.loads(x)} for x in rest_old]
        added += [{**base, "fields": json.loads(x)} for x in rest_new]
    return {"added": added, "removed": removed, "changed": changed}


def events_diff(root: Path, base_rules: Path, plugin_root: Path, defaults: dict, parse=None) -> dict:
    """현재 트리의 모든 fixture를 `base_rules`와 현재 규칙으로 파싱해 비교한다. `parse(path, rules_dir)`로
    파싱 함수(캐시)를 바꿀 수 있다."""
    config = issuedb.load_config(root)
    parse = parse or (lambda path, rules: _parse_fixture(path, rules, plugin_root, defaults))
    rows = []
    totals = {"added": 0, "removed": 0, "changed": 0}
    fixtures = all_fixtures(root, config)
    for path, rel in fixtures:
        try:
            before = parse(path, base_rules)
            after = parse(path, root / "parser-rules")
        except parse_logcat.UsageError as exc:
            raise UsageError(f"{rel}: {exc}") from exc
        delta = compare_events(before, after)
        for k in totals:
            totals[k] += len(delta[k])
        if any(delta.values()):
            rows.append({"fixture": rel, **delta,
                         "existing_changed": bool(delta["removed"] or delta["changed"])})
    return {"summary": {"fixtures": len(fixtures), **totals,
                        "existing_changed": any(r["existing_changed"] for r in rows)},
            "fixtures": rows}


def run_events_diff(args, defaults: dict, plugin_root: Path) -> dict:
    try:
        repo = dbpath.resolve(args.db)
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc
    workdir = Path(tempfile.mkdtemp(prefix="tt-events-diff-"))
    try:
        try:
            sha = gitscope.git(repo, "rev-parse", "--verify", f"{args.events_diff}^{{commit}}").strip()
            base = gitscope.materialize_ref(repo, sha, workdir / "base")
        except gitscope.GitError as exc:
            raise UsageError(str(exc)) from exc
        result = events_diff(repo, base / "parser-rules", plugin_root, defaults)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return {"ref": args.events_diff, "base_sha": sha, **result}


def prepare(db: issuedb.IssueDb, defaults: dict) -> dict:
    """파서 백엔드·외부 파서가 이슈 DB 고정값과 같은지 확인하고 시그니처를 컴파일한다 (다르면 UsageError)."""
    env = compiled_cache.environment(defaults)
    mismatch = compat.check_parser_backend(db.config, env["backend"]["name"], str(env["backend"]["version"]))
    configured = {cat: {**info, "available": True} for cat, info in env["external"].items()}
    mismatch += compat.check_external(db.config, configured)
    if mismatch:
        raise UsageError("회귀를 돌릴 수 없습니다 (결과가 사람마다 달라진다): "
                         + "; ".join(m["message"] for m in mismatch))
    try:
        return compiled_cache.compile_signatures(db)
    except SignatureError as exc:
        raise UsageError(f"시그니처 오류: {exc}") from exc


def match_errors(result: dict, events: dict) -> dict:
    """매처 결과에 extractor 시간 상한 오류를 합친다 (회귀·검증 모드에서는 실패다)."""
    result["errors"] = list(result["errors"]) + [
        {"extractor": e["extractor"], "error": e["error"]} for e in events.get("errors") or []]
    result["errors"] += parse_logcat.observation_errors(events)
    return result


def run(args, defaults: dict, plugin_root: Path) -> tuple[dict, int]:
    try:
        repo = dbpath.resolve(args.db)
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc

    changed: list[str] | None = None
    workdir = None
    root = repo
    try:
        if args.staged:
            changed = gitscope.staged_files(repo)
            workdir = Path(tempfile.mkdtemp(prefix="tt-regress-index-"))
            root = gitscope.materialize_index(repo, workdir / "db")
        elif args.changed:
            changed = gitscope.changed_files(repo, args.changed)
    except gitscope.GitError as exc:
        raise UsageError(str(exc)) from exc

    try:
        try:
            db = issuedb.load(root)
        except issuedb.IssueDbError as exc:
            raise UsageError(str(exc)) from exc

        compiled = prepare(db, defaults)

        items = collect(db)
        selected = scope_types(db, changed) if changed is not None else None
        if selected is not None:
            items = [i for i in items if i["type"].id in selected]

        results = []
        for item in items:
            try:
                events = _parse_fixture(item["path"], root / "parser-rules", plugin_root, defaults)
            except parse_logcat.UsageError as exc:
                raise UsageError(f"{item['rel']}: {exc}") from exc
            result = match_errors(match_signatures.match(events, db, compiled, regress=True), events)
            results.append(judge(item, result))
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)

    failed = [r for r in results if r["status"] != "pass"]
    summary = {
        "scope": "staged" if args.staged else (f"changed:{args.changed}" if args.changed else "all"),
        "expanded": changed is not None and selected is None,
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
    }
    return {"summary": summary, "results": results}, (CHECK_FAILED if failed else OK)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="db_regress.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=None)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true")
    scope.add_argument("--changed", metavar="ref")
    scope.add_argument("--staged", action="store_true")
    scope.add_argument("--events-diff", metavar="ref", help="규칙 변경 전후 이벤트 변화 (R5)")
    parser.add_argument("--no-external", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    parser.add_argument("--plugin-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    defaults = site_defaults.load_or_exit(args.plugin_root)
    plugin_root = Path(args.plugin_root) if args.plugin_root else site_defaults.plugin_root()
    try:
        if args.no_external:
            raise UsageError("db_regress는 --no-external을 받지 않습니다 (분석 디버그용 옵션이다).")
        if args.events_diff:
            print(json.dumps(run_events_diff(args, defaults, plugin_root), ensure_ascii=False, indent=1))
            return OK
        result, code = run(args, defaults, plugin_root)
    except (UsageError, yamlio.YamlFileError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    for r in result["results"]:
        if r["status"] != "pass":
            print(f"실패: {r['fixture']} ({r['expect']})", file=sys.stderr)
            for reason in r["reasons"]:
                key = f" [{reason['signature']}]" if reason.get("signature") else ""
                print(f"  - {reason['message']}{key}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
