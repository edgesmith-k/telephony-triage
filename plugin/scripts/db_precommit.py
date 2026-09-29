#!/usr/bin/env python3
"""db_precommit.py — git pre-commit hook 오케스트레이터 (06-collaboration.md §6.3 ②, 01-architecture.md §3.1).

    db_precommit.py --db "$(git rev-parse --show-toplevel)" [--staged]

이슈 DB의 `.githooks/pre-commit`만 부른다. 검사는 직접 하지 않고 변경 범위(index)를 계산해서 아래를 순서대로
부른다. 모두 index 내용(`--staged`) 기준이다. `--staged`는 기본값이고 명시해도 된다.

1. `config.py check --db <top> --for dry-run` — 스키마·생성기·파서 백엔드·외부 파서 버전 (06-collaboration.md
   §6.4 "직접 편집 브랜치의 pre-commit"). `migrate/schema-v<N>` 브랜치는 버전을 보지 않는다(check가 판별).
2. `.cache/`가 staged면 차단 (캐시는 커밋하지 않는다).
3. `db_lint --staged`
4. `mask_pii --check --staged`
5. `db_regress --staged` (parser-rules 변경이면 전체로 확장, db_regress가 판단)
6. 규칙 변경(parser-rules/, type.md, fixture 기대값)이 있으면 `db_verify rules --staged`
7. `ci_mode: local`/`actions`: `db_build --verify --staged`. `actions-build`: 생성 파일이 staged면 차단
   (13-actions.md). `migrate/schema-v<N>` 브랜치에서는 생성기 버전 불일치로 검증을 못 하면 경고만 한다.

종료 코드: 하위 결과에 1이 하나라도 있으면 1, 2(실행 불가)가 있으면 2, 없고 3(승인 필요)이 있으면 경고를 출력하고 0,
모두 통과면 0 (contracts.md §종료 코드). 0이 아니면 git이 커밋을 막는다. 사람이 읽는 요약은 stderr에, 결과 JSON은
stdout에 낸다(`--json`과 상관없이 항상).

git은 hook을 부를 때 `GIT_INDEX_FILE`을 넘긴다(`git commit -a`·`git commit <경로>`의 임시 index 포함).
하위 스크립트는 환경을 그대로 물려받아 같은 index를 본다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from common import compat, gitscope, site_defaults  # noqa: E402
from common.exitcodes import CHECK_FAILED, NEEDS_APPROVAL, OK, USAGE  # noqa: E402

MIGRATE_BRANCH_RE = re.compile(r"^migrate/schema-v\d+$")
RULE_FILE_RE = re.compile(r"^(parser-rules/.+\.ya?ml|[^/]+/[^/]+/type\.md|[^/]+/[^/]+/fixtures/.+\.expect\.yaml)$")
PREFIX = "[telephony-triage pre-commit]"


def _script(name: str, args: list[str], plugin_root: str | None) -> tuple[int, dict | None, str]:
    extra = ["--plugin-root", plugin_root] if plugin_root else []
    proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args, *extra], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        data = None
    return proc.returncode, data, proc.stderr.strip()


def generated_paths(db_cfg: dict) -> set[str]:
    """생성 파일 경로 (db_build.generate와 같은 목록)."""
    paths = {"README.md", "STATS.md", "parser-rules/CHANGELOG.md"}
    for cat in db_cfg.get("categories") or []:
        if isinstance(cat, dict) and cat.get("key"):
            paths.add(f"{cat['key']}/README.md")
    return paths


def _brief(name: str, code: int, data: dict | None, err: str) -> str:
    """실패한 검사의 짧은 사유."""
    if not isinstance(data, dict):
        return err.splitlines()[-1] if err else f"종료 코드 {code}"
    if name == "lint":
        return "; ".join(f"{e.get('file') or ''}: {e.get('code', '')} {e.get('message', '')}".strip()
                         for e in (data.get("errors") or [])[:5])
    if name == "mask":
        return "; ".join(f"{d['path']}:{d['line']} {d['kind']}" for d in (data.get("detections") or [])[:10])
    if name == "regress":
        return "; ".join(f"{r['fixture']}" for r in data.get("results", []) if r.get("status") != "pass")
    if name == "verify":
        return "; ".join(f"{r['id']} {r['status']}: {r.get('reason', '')}" for r in data.get("rules", [])
                         if r.get("status") in ("fail", "needs-approval"))
    if name == "build":
        return "; ".join(f"{p['path']} ({p['status']})" for p in data.get("problems", []))
    if name == "compat":
        return "; ".join(r.get("message", r.get("code", "")) for r in data.get("reasons", []))
    return err or f"종료 코드 {code}"


def run(db: Path, plugin_root: str | None) -> tuple[dict, int]:
    staged = gitscope.staged_files(db)
    branch = subprocess.run(["git", "-C", str(db), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                            text=True, encoding="utf-8").stdout.strip()
    migrate = bool(MIGRATE_BRANCH_RE.match(branch))
    db_cfg = compat.load_db_config(db)
    ci_mode = db_cfg.get("ci_mode", "local")
    checks: list[dict] = []

    def add(name: str, code: int, data=None, err: str = "", note: str | None = None) -> None:
        item = {"check": name, "code": code}
        if code != OK:
            item["reason"] = note or _brief(name, code, data, err)
        elif note:
            item["note"] = note
        checks.append(item)

    if not staged:
        return {"db": str(db), "branch": branch, "staged": [], "checks": [], "note": "staged 변경 없음"}, OK

    # 1. 버전 호환성 (쓰기 가능 여부). gh 인증은 보지 않는다.
    code, data, err = _script("config.py", ["check", "--db", str(db), "--for", "dry-run"], plugin_root)
    add("compat", code, data, err)

    # 2. 캐시
    cache = [p for p in staged if p == ".cache" or p.startswith(".cache/")]
    add("cache", CHECK_FAILED if cache else OK,
        note=(f".cache/는 커밋하지 않는다: {', '.join(cache[:5])}" if cache else None))

    # 3~5. lint, 마스킹, 회귀
    for name, script, args in (("lint", "db_lint.py", ["--staged"]),
                               ("mask", "mask_pii.py", ["--check", "--staged"]),
                               ("regress", "db_regress.py", ["--staged"])):
        code, data, err = _script(script, [*args, "--db", str(db)], plugin_root)
        add(name, code, data, err)

    # 6. 규칙 검증 (규칙 변경이 있을 때만)
    rule_files = [p for p in staged if RULE_FILE_RE.match(p)]
    if rule_files:
        code, data, err = _script("db_verify.py", ["rules", "--staged", "--db", str(db)], plugin_root)
        add("verify", code, data, err)
    else:
        checks.append({"check": "verify", "code": OK, "skipped": "규칙 변경 없음"})

    # 7. 생성 파일
    if ci_mode == "actions-build":
        gen = sorted(set(staged) & generated_paths(db_cfg))
        add("build", CHECK_FAILED if gen else OK,
            note=(f"ci_mode: actions-build — 생성 파일은 머지 후 봇이 만든다. staged에서 빼라: {', '.join(gen)}"
                  if gen else None))
    else:
        code, data, err = _script("db_build.py", ["--verify", "--staged", "--db", str(db)], plugin_root)
        if code == USAGE and migrate and "생성기 버전" in err:
            checks.append({"check": "build", "code": OK,
                           "note": f"{branch}: 생성기 버전 불일치로 생성 파일 검증을 건너뛴다 (06-collaboration.md §6.4)"})
        else:
            add("build", code, data, err,
                note=("생성 파일(README·STATS·CHANGELOG)이 원본과 다르다. 직접 고치지 말고 "
                      "db_build.py --write로 다시 만든 뒤 git add 한다: " + _brief("build", code, data, err))
                if code == CHECK_FAILED else None)

    codes = [c["code"] for c in checks]
    overall = (CHECK_FAILED if CHECK_FAILED in codes else USAGE if USAGE in codes
               else NEEDS_APPROVAL if NEEDS_APPROVAL in codes else OK)
    return {"db": str(db), "branch": branch, "migrate_branch": migrate, "ci_mode": ci_mode,
            "staged": staged, "checks": checks, "result": overall}, overall


def report(result: dict, code: int) -> None:
    for c in result.get("checks", []):
        if c["code"] in (CHECK_FAILED, USAGE):
            print(f"{PREFIX} ✗ {c['check']}: {c.get('reason', '')}", file=sys.stderr)
        elif c["code"] == NEEDS_APPROVAL:
            print(f"{PREFIX} ! {c['check']}: 승인 필요 — {c.get('reason', '')}", file=sys.stderr)
        elif c.get("note"):
            print(f"{PREFIX} · {c['check']}: {c['note']}", file=sys.stderr)
    if code == NEEDS_APPROVAL:
        print(f"{PREFIX} 경고: 승인이 필요한 변화가 있다 (needs-approval). 커밋은 통과시킨다. "
              "PR 본문에 '승인 필요'로 적고 메인테이너 승인을 받는다.", file=sys.stderr)
    elif code in (CHECK_FAILED, USAGE):
        print(f"{PREFIX} 커밋을 막았다. 위 문제를 고친 뒤 다시 커밋한다. 우회(--no-verify 등)는 금지다 "
              "(CONTRIBUTING.md).", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(prog="db_precommit.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help='이슈 DB toplevel ("$(git rev-parse --show-toplevel)")')
    parser.add_argument("--staged", action="store_true", default=True, help="index 기준 (기본값)")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (항상 JSON)")
    parser.add_argument("--plugin-root", default=None)
    args = parser.parse_args(argv)
    site_defaults.load_or_exit(args.plugin_root)
    db = Path(args.db)
    if not (db / "issue-db.config.yaml").is_file():
        print(f"{PREFIX} 이슈 DB가 아닙니다(issue-db.config.yaml 없음): {db}", file=sys.stderr)
        return USAGE
    try:
        result, code = run(db, args.plugin_root)
    except gitscope.GitError as exc:
        print(f"{PREFIX} {exc}", file=sys.stderr)
        return USAGE
    report(result, code)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return OK if code == NEEDS_APPROVAL else code


if __name__ == "__main__":
    raise SystemExit(main())
