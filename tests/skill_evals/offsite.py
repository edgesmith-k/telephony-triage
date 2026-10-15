#!/usr/bin/env python3
"""사외 eval 결과 기록 `offsite_results.json` 생성 (tests/skill_evals/README.md "사외 결과 기록", 15-local-draft.md §15.5 S-2).

    python3 tests/skill_evals/offsite.py <iteration 디렉토리>... [--out tests/skill_evals/offsite_results.json] [--note 메모]

사내 S-2는 `pending.json`의 `site`(사내에서만 확인되는 것)만 실행하고, 나머지 eval은 이 기록(사외 결과)으로 갈음한다.
손으로 쓰지 않는다: 각 run 디렉토리(`<iteration>/eval-<id>[-<name>]/with_skill/`)의 `execution.json`과 `grading.json`만 읽어
eval마다 run 요약을 모은다. transcript·출력·절대 경로는 넣지 않는다(iteration은 디렉토리 이름만).

- run: {iteration, date, repo_commit, init_model, status, passed, failed, undecided, safety_fail, safety_undecided,
  safety_fail_rows(실패한 안전 행의 채점 항목 문구 앞 80자 — evals.json 단언 문구일 뿐 근거·출력은 아니다), cost_usd}.
  date는 실행 시각이 아니라 `execution.json` 파일 수정일(UTC)이다(execution.json에 시각 필드가 없다). init_model이 없으면 execution.json `model`.
  status는 grading.json의 status(없으면 `ungraded`), 실행이 끝나지 않았으면 execution.json의 status. undecided는 토큰 상한 행을 뺀 미결정 행 수.
- run 순서: repo_commit의 git 조상 관계(`git merge-base --is-ancestor`)로 정한다. 커밋이 없거나 모르는 커밋이거나 서로 조상이 아닌
  커밋이 섞이면 파일 수정 시각으로 대신하고 eval의 `order`를 `mtime`으로 남긴다(경고). 같은 커밋 안에서는 수정 시각·iteration 순.
- verdict(eval): 가장 최근 커밋(`verdict_commit`)의 run들 가운데 가장 나쁜 판정(fail > undecided > pass). 같은 커밋 반복 실행(sm1·sm2 등)의
  들쭉날쭉한 결과를 마지막 하나로 덮지 않는다. run 판정: 실패 행·안전 위반이 있으면 fail, 채점 안 됨·미결정 행이 있으면 undecided,
  아니면 pass. run이 없으면 `none`.
- 여러 모델이 섞이면 쓰지 않는다(종료 2). 모델별로 따로 모아야 사내 모델과 비교할 수 있다.
- `site`가 아닌 eval에 run이 없으면 `none`으로 두고 경고한다(사내 S-2 `s2.offsite`가 사용자 필요로 본다).
- 쓰기는 원자적이다(임시 파일 → 이름 바꾸기).

종료 코드: 0 기록함, 2 사용 오류(iteration 없음·run 없음·모델 혼합).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_OUT = HERE / "offsite_results.json"
RUN_RE = re.compile(r"^eval-(\d+)(?:-.+)?$")
RANK = {"pass": 0, "undecided": 1, "fail": 2}
GRADE_API = ("safety_failures", "safety_undecided", "is_safety_eval", "TOKEN_BUDGET_TEXT")   # site_checks.py와 같이 쓰는 공개 값


def load_grade(name: str = "tt_offsite_grade"):
    """grade.py를 고유 모듈 이름으로 읽는다(`import grade`는 다른 같은 이름 모듈과 sys.modules에서 겹칠 수 있다)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / "grade.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


grade = load_grade()


class Usage(Exception):
    pass


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


class CommitOrder:
    """repo_commit 사이의 git 조상 관계(캐시). 판정할 수 없으면 None."""

    def __init__(self, repo: Path):
        self.repo, self.cache = repo, {}

    def is_ancestor(self, a: str, b: str) -> bool | None:
        if (a, b) not in self.cache:
            p = _run_git(self.repo, "merge-base", "--is-ancestor", a, b)
            self.cache[(a, b)] = {0: True, 1: False}.get(p.returncode) if p else None
        return self.cache[(a, b)]

    def ranks(self, commits: list) -> dict[str, int] | None:
        """커밋 → 그 커밋의 조상인 다른 커밋 수(전순서면 순서). 커밋이 없거나 모르거나 서로 조상이 아닌 쌍이 있으면 None."""
        if any(not c for c in commits):
            return None
        uniq = sorted(set(commits))
        rank = dict.fromkeys(uniq, 0)
        for i, a in enumerate(uniq):
            for b in uniq[i + 1:]:
                ab, ba = self.is_ancestor(a, b), self.is_ancestor(b, a)
                if ab is None or ba is None or ab == ba:
                    return None
                rank[b if ab else a] += 1
        return rank


def run_verdict(run: dict) -> str:
    if run["status"] != "graded":
        return "undecided"
    if run["failed"] or run["safety_fail"]:
        return "fail"
    return "undecided" if run["undecided"] else "pass"


def eval_verdict(runs: list[dict], commit: str | None) -> str:
    """verdict_commit의 run들 가운데 가장 나쁜 판정. run이 없으면 none."""
    latest = [r for r in runs if r["repo_commit"] == commit]
    return max((run_verdict(r) for r in latest), key=RANK.__getitem__) if latest else "none"


def read_run(it: Path, run_dir: Path, eid: int, batch) -> tuple[dict, float] | None:
    ex_p, gr_p = run_dir / "execution.json", run_dir / "grading.json"
    if not ex_p.is_file():
        return None
    ex = _load(ex_p)
    if ex.get("status") == "prepared":        # 준비만 하고 실행하지 않은 run
        return None
    mtime = ex_p.stat().st_mtime
    run = {"iteration": it.name, "date": datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%d"),
           "repo_commit": ex.get("repo_commit"), "init_model": ex.get("init_model") or ex.get("model"),
           "status": "ungraded", "passed": 0, "failed": 0, "undecided": 0, "safety_fail": 0, "safety_undecided": 0,
           "safety_fail_rows": [],
           "cost_usd": round(ex["total_cost_usd"], 4) if isinstance(ex.get("total_cost_usd"), (int, float)) else None}
    if ex.get("status") != "completed":
        run["status"] = ex.get("status") or "unknown"
    elif gr_p.is_file():
        g = _load(gr_p)
        rows = g.get("expectations") or []
        run.update(status=g.get("status") or "ungraded",
                   passed=sum(r.get("passed") is True for r in rows),
                   failed=sum(r.get("passed") is False for r in rows),
                   undecided=sum(r.get("passed") is None and r.get("text") != grade.TOKEN_BUDGET_TEXT for r in rows),
                   safety_fail=len(fails := grade.safety_failures(eid, batch, rows)),
                   safety_undecided=len(grade.safety_undecided(eid, batch, rows)),
                   safety_fail_rows=[t[:80] for t in fails])     # 채점 항목 문구(evals.json 단언)만, 근거·출력은 넣지 않는다
    return run, mtime


def collect(iterations: list[Path], entries: list[dict]) -> dict[int, list[tuple[dict, float]]]:
    batches = {e["id"]: e.get("batch") for e in entries}
    runs: dict[int, list[tuple[dict, float]]] = {e["id"]: [] for e in entries}
    for it in iterations:
        if not it.is_dir():
            raise Usage(f"iteration 디렉토리가 없다: {it}")
        found = 0
        for d in sorted(it.iterdir()):
            m = RUN_RE.match(d.name)
            if not m or not (d / "with_skill").is_dir():
                continue
            eid = int(m.group(1))
            if eid not in batches:
                print(f"경고: {it.name}/{d.name}: evals.json에 없는 eval — 건너뜀", file=sys.stderr)
                continue
            got = read_run(it, d / "with_skill", eid, batches[eid])
            if got:
                runs[eid].append(got)
                found += 1
        if not found:
            print(f"경고: {it.name}: 실행 기록(execution.json)이 있는 run 없음", file=sys.stderr)
    return runs


def order_runs(rs: list[tuple[dict, float]], order: CommitOrder) -> tuple[list[dict], str, str | None]:
    """(순서대로 run, 순서 근거 git|mtime, verdict_commit)."""
    rank = order.ranks([r["repo_commit"] for r, _ in rs])
    if rank is None:
        out = [r for r, _ in sorted(rs, key=lambda x: (x[1], x[0]["iteration"]))]
        return out, "mtime", out[-1]["repo_commit"]
    out = [r for r, _ in sorted(rs, key=lambda x: (rank[x[0]["repo_commit"]], x[1], x[0]["iteration"]))]
    return out, "git", out[-1]["repo_commit"]


def build(iterations: list[Path], entries: list[dict], site: set[int], note: str | None = None,
          repo: Path = REPO) -> tuple[dict, list[str]]:
    runs = collect(iterations, entries)
    models = sorted({r["init_model"] or "?" for rs in runs.values() for r, _ in rs})
    if not models:
        raise Usage("실행 기록이 있는 run이 없다")
    if len(models) > 1:
        raise Usage(f"모델(init_model)이 섞였다: {models} — 한 모델의 iteration만 넘긴다")
    order, warnings, evals = CommitOrder(repo), [], {}
    for eid in sorted(runs):
        if not runs[eid]:
            evals[str(eid)] = {"verdict": "none", "runs": []}
            if eid not in site:
                warnings.append(f"사내 대상(site)이 아닌 eval {eid}에 사외 run 없음(verdict none)")
            continue
        rs, basis, commit = order_runs(runs[eid], order)
        if basis == "mtime":
            warnings.append(f"eval {eid}: 커밋 조상 관계를 정할 수 없어 파일 수정 시각으로 순서를 정했다(order mtime)")
        evals[str(eid)] = {"verdict": eval_verdict(rs, commit), "verdict_commit": commit, "order": basis, "runs": rs}
    p = _run_git(REPO, "log", "-1", "--format=%H", "--", "tests/skill_evals/grade.py")
    out = {"model": models[0], "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "grader_commit": (p.stdout.strip() if p else "") or None,
           **({"note": note} if note else {}), "evals": evals}
    return out, warnings


def write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def site_ids(evals_dir: Path) -> set[int]:
    pend = _load(evals_dir / "pending.json")
    site = pend.get("site") or {}
    return {int(k) for k in (site.keys() if isinstance(site, dict) else site)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="offsite.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("iteration", nargs="+", help="사외 iteration 디렉토리(한 모델로 실행한 것만)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="기록 파일(기본 tests/skill_evals/offsite_results.json)")
    ap.add_argument("--note", help="기록에 남길 메모(예: 잠정 — 재측정 뒤 다시 만든다)")
    ap.add_argument("--evals-dir", default=str(HERE), help=argparse.SUPPRESS)   # 테스트용(evals.json·pending.json 위치)
    ap.add_argument("--git-repo", default=str(REPO), help=argparse.SUPPRESS)    # 테스트용(커밋 조상 관계를 볼 저장소)
    args = ap.parse_args(argv)
    evals_dir = Path(args.evals_dir)
    try:
        entries = json.loads((evals_dir / "evals.json").read_text(encoding="utf-8"))["evals"]
        data, warnings = build([Path(p) for p in args.iteration], entries, site_ids(evals_dir), args.note,
                               Path(args.git_repo))
    except Usage as exc:
        print(f"offsite.py: {exc}", file=sys.stderr)
        return 2
    write_atomic(Path(args.out), data)
    counts = {v: sum(e["verdict"] == v for e in data["evals"].values()) for v in ("pass", "fail", "undecided", "none")}
    print(f"{args.out}: model {data['model']} · eval {len(data['evals'])} · "
          + " · ".join(f"{k} {n}" for k, n in counts.items()))
    for w in warnings:
        print(f"경고: {w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
