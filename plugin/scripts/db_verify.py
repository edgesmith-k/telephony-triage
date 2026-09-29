#!/usr/bin/env python3
"""db_verify.py — 규칙·해결책·코드 수정 검증 (05-verification.md §5.12, contracts.md §3.2 `db_verify.py` 세부).

    db_verify.py rules (--plan <plan.json> [--draft <dir>] | --changed <ref> | --staged)
                       [--extra <logcat...>] [--extra-normal <logcat...>] [--db <path>]
    db_verify.py resolution --cause <ID> <logcat...> [--plan <plan.json> --draft <dir>] [--db <path>]
    db_verify.py fix --cause <ID> <logcat...> [--build <빌드>] [--plan <plan.json> --draft <dir>] [--db <path>]

모든 판정은 회귀·검증 모드다(파일 전체, bonus 0, 피드백 가중치 끔, 모든 active 원인의 C 독립 평가, 판정은 S/C만).

`rules` — R1~R6
- 대상 트리: `--plan`만이면 `--db`(계획이 이미 적용된 worktree, Step 8-4), `--plan --draft <dir>`이면 `<dir>`에 만든
  origin/<base> 분리 worktree에 계획을 적용한 트리(Step 7, 검사 뒤 지움, 세션 lock 확인), `--changed <ref>`면 `--db`의
  워킹 트리, `--staged`면 index 내용.
- 기준 트리(base): `--plan`은 대상 트리의 `HEAD`(worktree는 기준 SHA에 있다), `--changed`는 merge-base, `--staged`는 `HEAD`.
- 검사 대상은 base와 대상 트리의 **의미 비교**로 정한다(`common/rulediff.py`): 바뀐 시그니처 + 바뀐
  extractor/태그/RIL 항목에 닿는 시그니처(의존 그래프). 새 원인도 대상이다(pending이면 `시그니처 없음(pending)`).
- R1 파서: 대상 시그니처의 각 조건(`must_match`·`must_event`+`fields`)이 소유자(증상이면 그 유형)의 양성·`recurrence`·
  `extra` fixture 중 하나에서 추출된다. 흔적 검사: 바뀐 scenario 시그니처는 그 원인의 양성 fixture에서 충족되고,
  scenario/recovery 모두 그 카테고리 음성 fixture **전부**에서 충족되지는 않는다.
- R2 양성: 대상 원인(증상 시그니처면 그 유형의 모든 원인)의 양성·`recurrence`·`extra` fixture 기대값(C=1, `also_allowed`
  밖의 다른 active 원인 C=0).
- R3 음성: 원인 — 같은 카테고리 음성 fixture, 같은 카테고리의 다른 원인 양성·`recurrence`·`extra` fixture, 대상 원인의
  `fixed`·`resolved` fixture에서 대상 원인 C=0(그 fixture의 `also_allowed`에 있으면 제외). 증상 — 이슈 DB **모든** 음성
  fixture에서 대상 유형 S=0. 다른 유형 양성 fixture에서 걸리면 `allow-cause` 초안.
- R4 교차 회귀: `db_regress --all`과 같은 판정(같은 프로세스). `db_pr stage`가 이미 돌린 결과는 `--regress-json`으로 받는다.
- R5 이벤트 diff: parser-rules가 바뀌었으면 모든 fixture를 base 규칙과 새 규칙으로 파싱해 비교한다(`db_regress
  --events-diff`와 같은 함수). 기존 이벤트가 사라지거나 바뀌면 `needs-approval`(종료 코드 3).
- R6 추가 표본: 계획 `extra_samples` + `--extra`(같은 증상, `expect: match`) + `--extra-normal`(정상, `expect: nomatch`).
  `match`는 대상 원인 중 하나가 C=1(원인 대상이 없으면 대상 유형 S=1), `nomatch`는 모든 active 유형 S=0.
  R6 `fail`은 사용자가 진행을 고를 수 있으므로 종료 코드에 넣지 않는다(`blocking: false`).
- 항목 상태: `pass | fail | needs-approval | skipped`. `skipped` 사유 `해당 없음`·`fixture 없음`·`음성 fixture 없음`·
  `시그니처 없음(pending)`. `fixture 없음`·`음성 fixture 없음`은 `review_required: true`이고 통과가 아니다.
  항목 하나에 대상이 여럿이면 `fail` > 리뷰 필요한 `skipped` > `pass` > 그 밖의 `skipped` 순으로 모은다(`checks[]`에 대상별).
- 종료 코드: R1~R4에 `fail`이 있으면 1, 없고 R5가 `needs-approval`이면 3, 아니면 0. 개발·테스트용으로 환경변수
  `TT_FORCE_VERIFY_EXIT=3`이면 판정 뒤 3을 낸다(실패가 있으면 1).

`resolution` — 해결책 검증 판정 (`passed | failed | unknown`, 05-verification.md §5.12 (1))
- failed: 원인 시그니처 충족. passed: 원인 불충족이고 (a) recovery 시그니처가 있으면 충족, (b) 없으면 증상 불충족이고
  scenario 충족. 그 밖(흔적 시그니처 없음, 시나리오 흔적 없음, 증상 남음, 로그 구간 부족, pending 원인)은 unknown.

`fix` — 코드 수정 검증 판정 (`passed | partial | failed | unknown`, 05-verification.md §5.12 (2))
- 중단(종료 코드 2): pending 원인, `fix.status`가 `fix-submitted`·`fixed`가 아님, `fixed_in`에 빌드 있는 항목 없음,
  `--build`가 `build_compare`로 모든 `fixed_in` 빌드보다 이전. 비교할 수 없으면 `build_check: undetermined`로 이어가고
  스킬이 사용자에게 묻는다.
- 코드·설정 수정 유형(`framework-bug`, `vendor-ril`, `modem`, `carrier-config`)에 scenario·recovery 시그니처가 모두
  없으면 판정 없이 unknown(필수 시그니처 없음). 그 밖의 유형은 흔적 대신 사용자 확인(`user_confirmation_required`).
- failed: 원인 시그니처 충족(재발 자체가 시나리오 수행 근거다). unknown: 시나리오 흔적(scenario, 없으면 recovery) 없음.
  partial: 흔적 충족·원인 불충족·증상 남음(다른 원인 후보 `other_candidates`). passed: 흔적 충족·원인 불충족·증상
  불충족·recovery가 있으면 충족. recovery가 있는데 불충족이면 unknown.

`--plan --draft`(resolution·fix): draft에 계획을 적용한 트리로 판정한다. `--cause`에 계획의 `temp_id`를 줄 수 있다.
같은 draft에서 `rules`(R1~R6)도 돌려 `rules`로 내고, 흔적 시그니처가 R1 흔적 검사에서 실패하면 판정을 쓰지 않는다
(`withheld: true`, 판정 `unknown`). 판정 결과에는 계획 op 초안 `suggested_ops`(fixture 경로는 `parse_logcat cut` 결과로
채운다)를 붙인다. 판정은 데이터이므로 종료 코드는 0(사용 오류는 2)이다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import db_regress  # noqa: E402
import match_signatures  # noqa: E402
import parse_logcat  # noqa: E402
from common import builds, dbpath, gitscope, issuedb, rulediff, site_defaults, userconfig  # noqa: E402
from common.buildname import sanitize_build  # noqa: E402
from common.exitcodes import CHECK_FAILED, NEEDS_APPROVAL, OK, USAGE  # noqa: E402
from common.patterns import PatternError, PatternTimeout  # noqa: E402
from common.signatures import SignatureError, compile_list, compile_signature  # noqa: E402

POSITIVE_KINDS = ("positive", "recurrence", "extra")
CODE_FIX_TYPES = ("framework-bug", "vendor-ril", "modem", "carrier-config")
NA, NO_FIXTURE, NO_NEGATIVE, PENDING = "해당 없음", "fixture 없음", "음성 fixture 없음", "시그니처 없음(pending)"
REVIEW_REASONS = (NO_FIXTURE, NO_NEGATIVE)


class UsageError(Exception):
    pass


def _script(name: str, args: list[str], plugin_root: str | None) -> subprocess.CompletedProcess:
    extra = ["--plugin-root", plugin_root] if plugin_root else []
    return subprocess.run([sys.executable, str(SCRIPTS / name), *args, *extra], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


# -- draft worktree -----------------------------------------------------------------------


def _check_lock(job: str, defaults: dict) -> None:
    work_dir = Path(str(userconfig.get(userconfig.merged(defaults), "work_dir"))).expanduser()
    path = work_dir / "session.lock"
    held = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if not held or held.get("job") != job:
        raise UsageError(f"세션 lock이 작업 {job}의 것이 아닙니다 (보유자: {held and held.get('job')}).")


def make_draft(plan: Path, draft: Path, defaults: dict, plugin_root: str | None) -> dict:
    """`<draft>`에 origin/<base> 기준 분리 worktree를 만들고 계획을 적용한다. `db_add apply` 결과를 돌려준다."""
    _check_lock(draft.parent.name, defaults)
    cfg = userconfig.merged(defaults)
    repo = Path(str(userconfig.get(cfg, "issue_db.path") or "")).expanduser()
    base = userconfig.get(cfg, "issue_db.base_branch") or "main"
    _git(repo, "worktree", "prune")
    if draft.exists():
        _git(repo, "worktree", "remove", "--force", str(draft))
        shutil.rmtree(draft, ignore_errors=True)
    proc = _git(repo, "worktree", "add", "--detach", str(draft), f"origin/{base}")
    if proc.returncode != 0:
        raise UsageError(f"draft worktree를 만들 수 없습니다: {proc.stderr.strip()}")
    applied = _script("db_add.py", ["apply", str(plan), "--db", str(draft)], plugin_root)
    if applied.returncode != 0:
        remove_draft(draft, defaults)
        raise UsageError(f"draft에 계획을 적용할 수 없습니다: {applied.stdout.strip()[:500]} {applied.stderr.strip()}")
    return json.loads(applied.stdout)


def remove_draft(draft: Path, defaults: dict) -> None:
    repo = Path(str(userconfig.get(userconfig.merged(defaults), "issue_db.path") or "")).expanduser()
    _git(repo, "worktree", "remove", "--force", str(draft))
    shutil.rmtree(draft, ignore_errors=True)
    _git(repo, "worktree", "prune")


# -- fixture 실행 컨텍스트 ------------------------------------------------------------------


class Run:
    """이슈 DB 하나에 대한 파싱·매칭 캐시. 경로 하나(또는 로그 묶음)는 한 번만 파싱·매칭한다."""

    def __init__(self, root: Path, plugin_root: Path, defaults: dict):
        self.root = root
        self.plugin_root = plugin_root
        self.defaults = defaults
        try:
            self.db = issuedb.load(root)
        except issuedb.IssueDbError as exc:
            raise UsageError(str(exc)) from exc
        try:
            self.compiled = db_regress.prepare(self.db, defaults)
        except db_regress.UsageError as exc:
            raise UsageError(str(exc)) from exc
        self.items = db_regress.collect(self.db)
        self._docs: dict[tuple, dict] = {}
        self._evals: dict[tuple, object] = {}
        self._results: dict[tuple, dict] = {}

    def close(self) -> None:
        for ev in self._evals.values():
            ev.close()
        self._evals.clear()

    def parse(self, paths: list[Path], rules_dir: Path | None = None) -> dict:
        rules_dir = rules_dir or self.root / "parser-rules"
        key = (tuple(str(p) for p in paths), str(rules_dir))
        if key not in self._docs:
            try:
                self._docs[key] = db_regress.parse_logs(paths, rules_dir, self.plugin_root, self.defaults)
            except parse_logcat.UsageError as exc:
                raise UsageError(f"{', '.join(p.name for p in paths)}: {exc}") from exc
        return self._docs[key]

    def evaluator(self, paths: list[Path]):
        key = tuple(str(p) for p in paths)
        if key not in self._evals:
            self._evals[key] = match_signatures.evaluator_for(self.parse(paths), self.db)
        return self._evals[key]

    def result(self, paths: list[Path]) -> dict:
        key = tuple(str(p) for p in paths)
        if key not in self._results:
            doc = self.parse(paths)
            res = match_signatures.match(doc, self.db, self.compiled, regress=True, evaluator=self.evaluator(paths))
            self._results[key] = db_regress.match_errors(res, doc)
        return self._results[key]

    # 편의 --------------------------------------------------------------------------------

    def C(self, paths: list[Path], cause_id: str) -> int:
        return next((c["C"] for c in self.result(paths)["causes"] if c["cause"] == cause_id), 0)

    def S(self, paths: list[Path], type_id: str) -> int:
        return next((t["S"] for t in self.result(paths)["types"] if t["type"] == type_id), 0)

    def fixtures(self, pred) -> list[dict]:
        return [i for i in self.items if pred(i)]


def _sig(raw: dict, owner: str):
    try:
        return compile_signature(raw, owner)
    except SignatureError as exc:
        raise UsageError(f"시그니처 오류: {exc}") from exc


def _cond_hit(ev, cond) -> bool:
    if cond.kind == "match":
        return bool(ev.lines(cond.pattern))
    return bool(ev.matching_events(cond))


def _satisfied(ev, sig) -> tuple[bool, dict | None, str | None]:
    res = ev.evaluate(sig)
    if res.error:
        return False, None, res.error
    first = min((e["ts"] for e in res.evidence), default=None) if res.satisfied else None
    return res.satisfied, ({"signature": sig.key, "ts": first, "evidence": res.evidence} if res.satisfied else None), None


# -- 항목 모으기 ---------------------------------------------------------------------------


def _check(target: str, status: str, reason: str, **extra) -> dict:
    return {"target": target, "status": status, "reason": reason,
            "review_required": status == "skipped" and reason in REVIEW_REASONS, **extra}


def aggregate(rid: str, checks: list[dict]) -> dict:
    if not checks:
        return {"id": rid, "status": "skipped", "reason": NA, "targets": [], "review_required": False, "checks": []}
    targets = sorted({c["target"] for c in checks})
    fails = [c for c in checks if c["status"] == "fail"]
    review = [c for c in checks if c["status"] == "skipped" and c["review_required"]]
    passes = [c for c in checks if c["status"] == "pass"]
    if fails:
        status, reason = "fail", "; ".join(c["reason"] for c in fails[:3]) + (" …" if len(fails) > 3 else "")
    elif review:
        status, reason = "skipped", review[0]["reason"]
    elif passes:
        status, reason = "pass", f"대상 {len(targets)}개 통과"
    else:
        status, reason = "skipped", checks[0]["reason"]
    return {"id": rid, "status": status, "reason": reason, "targets": targets,
            "review_required": status == "skipped" and bool(review), "checks": checks}


# -- 대상 계산 -----------------------------------------------------------------------------


class Targets:
    def __init__(self, run: Run, diff: rulediff.Diff, new_causes: list[str]):
        db = run.db
        self.symptom: dict[str, list[rulediff.Change]] = {}   # 유형 ID → 바뀐 증상 시그니처
        self.cause: dict[str, list[rulediff.Change]] = {}     # 원인 ID → 바뀐 판별 시그니처
        self.trace: list[rulediff.Change] = []                # 바뀐 scenario/recovery
        for change in diff.sigs.values():
            ref = change.sig
            itype = db.type_by_id(ref.type_id)
            if itype is None or not itype.active:
                continue
            if ref.kind == "symptom":
                self.symptom.setdefault(ref.owner, []).append(change)
                continue
            cause = db.cause_by_id(ref.owner)
            if cause is None or not cause.active:
                continue
            if ref.kind == "cause":
                self.cause.setdefault(ref.owner, []).append(change)
            else:
                self.trace.append(change)
        self.pending = sorted(c for c in new_causes if (db.cause_by_id(c) or None) is not None
                              and db.cause_by_id(c).pending and db.cause_by_id(c).active)
        r2 = set(self.cause)
        for tid in self.symptom:
            r2 |= {c.id for c in db.type_by_id(tid).causes if c.active}
        r2 |= set(self.pending)
        self.r2 = sorted(r2)

    def empty(self) -> bool:
        return not (self.symptom or self.cause or self.trace or self.pending)


def _positives(run: Run, cause_id: str) -> list[dict]:
    return run.fixtures(lambda i: i["fx"].cause == cause_id and i["fx"].kind in POSITIVE_KINDS)


def _type_positives(run: Run, type_id: str) -> list[dict]:
    return run.fixtures(lambda i: i["type"].id == type_id and i["fx"].kind in POSITIVE_KINDS)


def _negatives(run: Run, category: str | None = None) -> list[dict]:
    return run.fixtures(lambda i: i["fx"].kind == "negative" and (category is None or i["type"].category == category))


def _paths(item: dict) -> list[Path]:
    return [item["path"]]


def r1(run: Run, t: Targets) -> dict:
    checks = []

    def parser_check(change: rulediff.Change, fixtures: list[dict], owner_label: str):
        ref = change.sig
        if not fixtures:
            checks.append(_check(ref.key, "skipped", NO_FIXTURE, part="parser", owner=owner_label))
            return
        sig = _sig(ref.raw, ref.owner)
        missing = []
        for cond in sig.positives:
            try:
                if not any(_cond_hit(run.evaluator(_paths(f)), cond) for f in fixtures):
                    missing.append(cond.describe())
            except (PatternTimeout, PatternError) as exc:
                missing.append(f"{cond.describe()} ({exc})")
        if missing:
            checks.append(_check(ref.key, "fail", f"{ref.key}: 양성 fixture에서 추출되지 않음 — {', '.join(missing)}",
                                 part="parser", fixtures=[f["rel"] for f in fixtures], missing=missing))
        else:
            checks.append(_check(ref.key, "pass", "추출 확인", part="parser", fixtures=[f["rel"] for f in fixtures]))

    for tid, changes in sorted(t.symptom.items()):
        for change in changes:
            parser_check(change, _type_positives(run, tid), tid)
    for cid, changes in sorted(t.cause.items()):
        for change in changes:
            parser_check(change, _positives(run, cid), cid)
    for cid in t.pending:
        checks.append(_check(cid, "skipped", PENDING, part="parser"))

    for change in t.trace:
        ref = change.sig
        sig = _sig(ref.raw, ref.owner)
        parts = []
        if ref.kind == "scenario":
            pos = _positives(run, ref.owner)
            if not pos:
                parts.append(("skipped", NO_FIXTURE, None))
            else:
                hits = [f["rel"] for f in pos if _satisfied(run.evaluator(_paths(f)), sig)[0]]
                parts.append(("pass", "재현 fixture에서 충족", hits) if hits else
                             ("fail", f"{ref.key}: 그 원인의 양성(재현) fixture에서 충족되지 않음", None))
        negs = _negatives(run, ref.category)
        if not negs:
            parts.append(("skipped", NO_NEGATIVE, None))
        else:
            hits = [f["rel"] for f in negs if _satisfied(run.evaluator(_paths(f)), sig)[0]]
            if len(hits) == len(negs):
                parts.append(("fail", f"{ref.key}: {ref.category} 음성 fixture {len(negs)}개 전부에서 충족 "
                                      "(아무 로그에나 맞는 흔적)", hits))
            else:
                parts.append(("pass", "음성 fixture 전부에 맞지는 않음", hits))
        status = ("fail" if any(p[0] == "fail" for p in parts) else
                  "skipped" if any(p[0] == "skipped" for p in parts) else "pass")
        reason = next(p[1] for p in parts if p[0] == status)
        checks.append(_check(ref.key, status, reason, part="trace", kind=ref.kind,
                             parts=[{"status": s, "reason": r, "fixtures": f} for s, r, f in parts]))
    return aggregate("R1", checks)


def r2(run: Run, t: Targets) -> dict:
    checks = []
    for cid in t.r2:
        cause = run.db.cause_by_id(cid)
        if cause.pending:
            checks.append(_check(cid, "skipped", PENDING))
            continue
        fixtures = _positives(run, cid)
        if not fixtures:
            checks.append(_check(cid, "skipped", NO_FIXTURE))
            continue
        bad = []
        for item in fixtures:
            judged = db_regress.judge(item, run.result(_paths(item)))
            if judged["status"] != "pass":
                bad.append(judged)
        if bad:
            checks.append(_check(cid, "fail", f"{cid}: 양성 fixture 기대값 불일치 "
                                              f"({', '.join(b['fixture'] for b in bad)})",
                                 failures=[{"fixture": b["fixture"], "expect": b["expect"], "reasons": b["reasons"],
                                            "allow_cause_drafts": b["allow_cause_drafts"]} for b in bad]))
        else:
            checks.append(_check(cid, "pass", "양성 fixture 기대값 유지", fixtures=[f["rel"] for f in fixtures]))
    return aggregate("R2", checks)


def _allow_draft(item: dict, cause_id: str) -> dict | None:
    fx = item["fx"]
    if fx.kind not in POSITIVE_KINDS or fx.type_id == cause_id.rsplit("-", 1)[0]:
        return None
    tdir = item["type"].path
    return {"op": "allow-cause", "fixture": f"fixtures/{fx.name}", "cause": cause_id,
            "type_dir": tdir.relative_to(tdir.parents[1]).as_posix()}


def r3(run: Run, t: Targets) -> dict:
    checks = []
    for cid in sorted(t.cause):
        cause = run.db.cause_by_id(cid)
        category = run.db.type_by_id(cause.type_id).category
        keys = [c.sig.key for c in t.cause[cid]]
        fixtures = run.fixtures(lambda i: (
            (i["fx"].kind == "negative" and i["type"].category == category)
            or (i["fx"].kind in POSITIVE_KINDS and i["type"].category == category and i["fx"].cause != cid)
            or (i["fx"].kind in ("fixed", "resolved") and i["fx"].cause == cid)))
        if not fixtures:
            checks.append(_check(cid, "skipped", NO_NEGATIVE, kind="cause"))
            continue
        hits = []
        for item in fixtures:
            if cid in item["expect"].also_allowed:
                continue
            if run.C(_paths(item), cid):
                sig = next((c["signature"] for c in run.result(_paths(item))["causes"] if c["cause"] == cid), None)
                hits.append({"fixture": item["rel"], "kind": item["fx"].kind, "signature": sig,
                             "allow_cause_draft": _allow_draft(item, cid)})
        if hits:
            checks.append(_check(cid, "fail", f"{cid}: C=1 — {', '.join(h['fixture'] for h in hits)}", kind="cause",
                                 signatures=keys, hits=hits,
                                 allow_cause_drafts=[h["allow_cause_draft"] for h in hits if h["allow_cause_draft"]]))
        else:
            checks.append(_check(cid, "pass", f"음성·다른 원인 fixture {len(fixtures)}개에서 C=0", kind="cause",
                                 signatures=keys))
    negatives = _negatives(run)
    for tid in sorted(t.symptom):
        keys = [c.sig.key for c in t.symptom[tid]]
        if not negatives:
            checks.append(_check(tid, "skipped", NO_NEGATIVE, kind="symptom"))
            continue
        hits = [{"fixture": i["rel"], "signature": next((x["signature"] for x in run.result(_paths(i))["types"]
                                                        if x["type"] == tid), None)}
                for i in negatives if run.S(_paths(i), tid)]
        if hits:
            checks.append(_check(tid, "fail", f"{tid}: 음성 fixture에서 S=1 — {', '.join(h['fixture'] for h in hits)}",
                                 kind="symptom", signatures=keys, hits=hits))
        else:
            checks.append(_check(tid, "pass", f"음성 fixture {len(negatives)}개에서 S=0", kind="symptom",
                                 signatures=keys))
    for cid in t.pending:
        checks.append(_check(cid, "skipped", PENDING, kind="cause"))
    return aggregate("R3", checks)


def r4(run: Run, regress: dict | None) -> tuple[dict, dict]:
    if regress is None:
        results = [db_regress.judge(item, run.result(_paths(item))) for item in run.items]
        failed = [r for r in results if r["status"] != "pass"]
        regress = {"summary": {"scope": "all", "expanded": False, "total": len(results),
                               "passed": len(results) - len(failed), "failed": len(failed)}, "results": results}
    failed = [r for r in regress.get("results", []) if r.get("status") != "pass"]
    row = {"id": "R4", "status": "fail" if failed else "pass",
           "reason": (f"기대값이 깨진 fixture {len(failed)}개" if failed else
                      f"전체 fixture {regress.get('summary', {}).get('total', 0)}개 기대값 유지"),
           "targets": [r["fixture"] for r in failed], "review_required": False,
           "failures": [{"fixture": r["fixture"], "expect": r.get("expect"), "reasons": r.get("reasons"),
                         "allow_cause_drafts": r.get("allow_cause_drafts")} for r in failed]}
    return row, regress


def r5(run: Run, diff: rulediff.Diff, base: Path | None) -> dict:
    if not diff.rules_changed:
        return {"id": "R5", "status": "skipped", "reason": NA, "targets": [], "review_required": False}
    if base is None or not (base / "parser-rules").is_dir():
        return {"id": "R5", "status": "skipped", "reason": NA, "targets": [], "review_required": False,
                "note": "기준 트리에 parser-rules가 없다 (모든 규칙이 새것)", "rules": diff.rules}
    try:
        result = db_regress.events_diff(run.root, base / "parser-rules", run.plugin_root, run.defaults,
                                        parse=lambda path, rules: run.parse([path], rules))
    except db_regress.UsageError as exc:
        raise UsageError(str(exc)) from exc
    changed = [r for r in result["fixtures"] if r["existing_changed"]]
    s = result["summary"]
    if changed:
        return {"id": "R5", "status": "needs-approval",
                "reason": f"기존 이벤트 변경 — fixture {len(changed)}개 (사라짐 {s['removed']}, 바뀜 {s['changed']})",
                "targets": [r["fixture"] for r in changed], "review_required": False, "rules": diff.rules,
                "impact": result["fixtures"], "summary": s}
    return {"id": "R5", "status": "pass", "reason": f"기존 이벤트 유지 (추가 {s['added']})",
            "targets": [], "review_required": False, "rules": diff.rules, "impact": result["fixtures"], "summary": s}


def r6(run: Run, t: Targets, samples: list[tuple[Path, str]]) -> dict:
    if not samples:
        return {"id": "R6", "status": "skipped", "reason": NA, "targets": [], "review_required": False,
                "blocking": False}
    causes = [c for c in t.r2 if not run.db.cause_by_id(c).pending]
    types = sorted(t.symptom) or sorted({run.db.cause_by_id(c).type_id for c in t.r2})
    rows = []
    for path, expect in samples:
        if not path.is_file():
            raise UsageError(f"R6 표본이 없습니다: {path}")
        res = run.result([path])
        c1 = sorted(c["cause"] for c in res["causes"] if c["C"])
        s1 = sorted(x["type"] for x in res["types"] if x["S"])
        if expect == "nomatch":
            ok = not s1
            why = "S=0" if ok else f"S=1: {', '.join(s1)}"
        elif causes:
            hit = [c for c in causes if c in c1]
            ok = bool(hit)
            why = f"대상 원인 C=1: {', '.join(hit)}" if ok else f"대상 원인 {', '.join(causes)} 모두 C=0"
        elif types:
            hit = [x for x in types if x in s1]
            ok = bool(hit)
            why = f"대상 유형 S=1: {', '.join(hit)}" if ok else f"대상 유형 {', '.join(types)} S=0"
        else:
            ok, why = True, "검증 대상 없음"
        rows.append({"sample": str(path), "expect": expect, "status": "pass" if ok else "fail", "reason": why,
                     "C": c1, "S": s1})
    failed = [r for r in rows if r["status"] == "fail"]
    return {"id": "R6", "status": "fail" if failed else "pass",
            "reason": (f"표본 {len(failed)}/{len(rows)}개 기대와 다름 (사용자가 진행 여부를 고른다)" if failed
                       else f"표본 {len(rows)}개 기대대로"),
            "targets": [r["sample"] for r in failed], "review_required": False, "blocking": False, "samples": rows}


# -- rules ---------------------------------------------------------------------------------


def _base_tree(repo: Path, ref: str, dest: Path) -> tuple[Path | None, str | None]:
    if not gitscope.has_ref(repo, ref):
        return None, None
    sha = gitscope.git(repo, "rev-parse", f"{ref}^{{commit}}").strip()
    return gitscope.materialize_ref(repo, sha, dest), sha


def verify_rules(root: Path, repo: Path, base_ref: str, plugin_root: Path, defaults: dict,
                 samples: list[tuple[Path, str]], regress: dict | None = None) -> tuple[dict, int]:
    """대상 트리 `root`를 `repo`의 `base_ref` 트리와 비교해 R1~R6을 돌린다."""
    tmp = Path(tempfile.mkdtemp(prefix="tt-verify-base-"))
    run = None
    try:
        try:
            base, base_sha = _base_tree(repo, base_ref, tmp / "base")
        except gitscope.GitError as exc:
            raise UsageError(str(exc)) from exc
        base_state = rulediff.load_state(base)
        cur_state = rulediff.load_state(root)
        diff = rulediff.compute(base_state, cur_state)
        run = Run(root, plugin_root, defaults)
        new_causes = [c.id for t in run.db.types for c in t.causes if c.id not in base_state.causes]
        targets = Targets(run, diff, new_causes)
        items = [r1(run, targets), r2(run, targets), r3(run, targets)]
        row4, regress = r4(run, regress)
        items += [row4, r5(run, diff, base), r6(run, targets, samples)]
    finally:
        if run is not None:
            run.close()
        shutil.rmtree(tmp, ignore_errors=True)
    blocking = [i["status"] for i in items if i.get("blocking", True)]
    code = CHECK_FAILED if "fail" in blocking else NEEDS_APPROVAL if "needs-approval" in blocking else OK
    if os.environ.get("TT_FORCE_VERIFY_EXIT") == "3" and code != CHECK_FAILED:
        code = NEEDS_APPROVAL
    changes = {"signatures": [{"key": c.sig.key, "kind": c.sig.kind, "why": c.why} for c in diff.sigs.values()],
               "parser_rules": diff.rules, "resolutions": diff.resolutions, "new_causes": new_causes}
    return {"base": base_sha, "changes": changes, "rules": items, "regress": regress.get("summary")}, code


def _samples(plan: dict | None, plan_path: Path | None, extra: list[str], normal: list[str]) -> list[tuple[Path, str]]:
    out = []
    for item in (plan or {}).get("extra_samples") or []:
        path = Path(item["path"])
        if not path.is_absolute() and plan_path is not None:
            path = plan_path.parent / path
        out.append((path, item.get("expect", "match")))
    out += [(Path(p), "match") for p in extra or []]
    out += [(Path(p), "nomatch") for p in normal or []]
    return out


def _load_plan(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(f"계획을 읽을 수 없습니다: {path}: {exc}") from exc


def rules(args, defaults: dict, plugin_root: Path) -> tuple[dict, int]:
    plan_path = Path(args.plan) if args.plan else None
    plan = _load_plan(args.plan) if plan_path else None
    samples = _samples(plan, plan_path, args.extra, args.extra_normal)
    regress = None
    if args.regress_json:
        regress = json.loads(Path(args.regress_json).read_text(encoding="utf-8"))
    if args.draft:
        if not plan_path:
            raise UsageError("--draft는 --plan과 함께 쓴다.")
        draft = Path(args.draft)
        make_draft(plan_path, draft, defaults, args.plugin_root)
        try:
            result, code = verify_rules(draft, draft, "HEAD", plugin_root, defaults, samples, regress)
        finally:
            remove_draft(draft, defaults)
        return {"db": str(draft), "scope": "plan:draft", **result}, code
    try:
        db = dbpath.resolve(args.db)
    except dbpath.DbPathError as exc:
        raise UsageError(str(exc)) from exc
    if plan_path:
        result, code = verify_rules(db, db, "HEAD", plugin_root, defaults, samples, regress)
        return {"db": str(db), "scope": "plan", **result}, code
    if args.changed:
        try:
            base = gitscope.merge_base(db, args.changed)
        except gitscope.GitError as exc:
            raise UsageError(str(exc)) from exc
        result, code = verify_rules(db, db, base, plugin_root, defaults, samples, regress)
        return {"db": str(db), "scope": f"changed:{args.changed}", **result}, code
    index_dir = Path(tempfile.mkdtemp(prefix="tt-verify-index-"))
    try:
        try:
            root = gitscope.materialize_index(db, index_dir / "db")
        except gitscope.GitError as exc:
            raise UsageError(str(exc)) from exc
        result, code = verify_rules(root, db, "HEAD", plugin_root, defaults, samples, regress)
    finally:
        shutil.rmtree(index_dir, ignore_errors=True)
    return {"db": str(db), "scope": "staged", **result}, code


# -- resolution / fix ----------------------------------------------------------------------


def _traces(run: Run, paths: list[Path], cause: issuedb.Cause, kind: str) -> tuple[list, list[dict], list[str]]:
    """(컴파일된 시그니처, 충족한 것 `[{signature, kind, ts, evidence}]`, 오류)."""
    try:
        sigs = compile_list(cause.raw.get(rulediff.SIG_KINDS[kind]), cause.id)
    except SignatureError as exc:
        raise UsageError(f"시그니처 오류: {exc}") from exc
    hits, errors = [], []
    for sig in sigs:
        ok, info, err = _satisfied(run.evaluator(paths), sig)
        if err:
            errors.append(f"{sig.key}: {err}")
        elif ok:
            hits.append({**info, "kind": kind})
    return sigs, hits, errors


def _other_candidates(result: dict, cause: issuedb.Cause, S: int) -> list[dict]:
    out = [{"type": c["type"], "cause": c["cause"], "signature": c["signature"]}
           for c in result["causes"] if c["C"] and c["cause"] != cause.id]
    out += [{"type": p["type"], "cause": p["cause"], "pending": True} for p in result["pending_causes"]
            if p["type"] == cause.type_id]
    if S and not any(o["type"] == cause.type_id for o in out):
        out.append({"type": cause.type_id, "cause": None, "note": "유형 일치, 원인 미확인 — analyze로 새 분석"})
    return out


def _brief(hits: list[dict]) -> list[dict]:
    return [{"signature": h["signature"], "kind": h["kind"], "ts": h["ts"]} for h in hits]


def _check_fix_target(cause: issuedb.Cause, build: str | None, rules_cfg: list) -> dict:
    fix = cause.raw.get("fix") or {}
    if cause.pending:
        raise UsageError(f"{cause.id}는 signatures_pending이라 verify-fix를 할 수 없습니다. 먼저 update-signature로 "
                         "판별 시그니처를 추가한다.")
    if fix.get("status") not in ("fix-submitted", "fixed"):
        raise UsageError(f"{cause.id}의 fix.status가 {fix.get('status')}입니다. verify-fix는 fix-submitted(재검증이면 "
                         "fixed) 원인만 한다.")
    fixed_in = [f for f in fix.get("fixed_in") or [] if isinstance(f, dict) and f.get("build")]
    if not fixed_in:
        raise UsageError(f"{cause.id}의 fixed_in에 빌드가 있는 항목이 없습니다. 먼저 fix-submitted 커맨드로 빌드를 "
                         "추가한다 (verify-fix passed의 전제).")
    if not build:
        return {"status": "not-given", "fixed_in": fixed_in,
                "message": "--build가 없어 fixed_in 이후인지 확인하지 못했다. 사용자에게 묻는다"}
    comparisons = [(builds.compare(build, f["build"], rules_cfg), f["build"]) for f in fixed_in]
    comparable = [(c, b) for c, b in comparisons if c is not None]
    if not comparable:
        return {"status": "undetermined", "build": build, "fixed_in": fixed_in,
                "message": "build_compare로 비교할 수 없다. 사용자에게 묻는다"}
    if all(c < 0 for c, _ in comparable):
        raise UsageError(f"로그 빌드 {build}가 fixed_in 빌드({', '.join(b for _, b in comparable)})보다 이전입니다. "
                         "수정 빌드 이후(같은 빌드 포함)의 로그로 검증한다.")
    return {"status": "after", "build": build, "fixed_in": fixed_in,
            "against": next(b for c, b in comparable if c >= 0)}


def judge_resolution(run: Run, cause: issuedb.Cause, paths: list[Path]) -> dict:
    out = {"judgement": "unknown", "reason": None}
    if cause.pending:
        return {**out, "reason": PENDING}
    doc = run.parse(paths)
    if not doc.get("events"):
        return {**out, "reason": "로그 구간 부족 (수집된 줄이 없다)"}
    result = run.result(paths)
    C, S = run.C(paths, cause.id), run.S(paths, cause.type_id)
    rec_sigs, rec_hits, e1 = _traces(run, paths, cause, "recovery")
    sce_sigs, sce_hits, e2 = _traces(run, paths, cause, "scenario")
    out.update(C=C, S=S, satisfied_traces=_brief(rec_hits + sce_hits),
               errors=[e["error"] for e in result["errors"]] + e1 + e2)
    if out["errors"]:
        return {**out, "reason": "정규식 시간 상한 초과 — 판정할 수 없다"}
    if C:
        cause_sig = next((c["signature"] for c in result["causes"] if c["cause"] == cause.id), None)
        return {**out, "judgement": "failed", "reason": f"원인 시그니처 충족 ({cause_sig})"}
    if rec_sigs:
        if rec_hits:
            return {**out, "judgement": "passed", "reason": f"원인 불충족, recovery 충족 ({rec_hits[0]['signature']})"}
        return {**out, "reason": "recovery 시그니처가 충족되지 않음 (정상 동작 흔적 없음)"}
    if not sce_sigs:
        return {**out, "reason": "recovery_signatures·scenario_signatures가 모두 없다 — 시그니처를 추가한다"}
    if not sce_hits:
        return {**out, "reason": "시나리오 흔적 없음 — 재현 시나리오를 수행한 로그가 필요하다"}
    if S:
        return {**out, "reason": "증상이 남아 있다"}
    return {**out, "judgement": "passed", "reason": f"원인·증상 불충족, 시나리오 흔적 충족 ({sce_hits[0]['signature']})"}


def judge_fix(run: Run, cause: issuedb.Cause, paths: list[Path]) -> dict:
    rtype = cause.raw.get("resolution_type")
    has_rec = bool(cause.raw.get("recovery_signatures"))
    has_sce = bool(cause.raw.get("scenario_signatures"))
    out = {"judgement": "unknown", "reason": None, "resolution_type": rtype}
    if not has_rec and not has_sce and rtype in CODE_FIX_TYPES:
        return {**out, "reason": "필수 시그니처 없음 — 코드·설정 수정 유형은 scenario_signatures 또는 "
                                 "recovery_signatures가 있어야 판정한다 (update-signature로 같은 PR에 넣을 수 있다)"}
    doc = run.parse(paths)
    if not doc.get("events"):
        return {**out, "reason": "로그 구간 부족 (수집된 줄이 없다)"}
    result = run.result(paths)
    C, S = run.C(paths, cause.id), run.S(paths, cause.type_id)
    rec_sigs, rec_hits, e1 = _traces(run, paths, cause, "recovery")
    sce_sigs, sce_hits, e2 = _traces(run, paths, cause, "scenario")
    trace_hits = sce_hits if sce_sigs else rec_hits
    out.update(C=C, S=S, satisfied_traces=_brief(rec_hits + sce_hits),
               trace=_brief(trace_hits[:1])[0] if trace_hits else None,
               errors=[e["error"] for e in result["errors"]] + e1 + e2)
    if out["errors"]:
        return {**out, "reason": "정규식 시간 상한 초과 — 판정할 수 없다"}
    if C:
        cause_sig = next((c["signature"] for c in result["causes"] if c["cause"] == cause.id), None)
        return {**out, "judgement": "failed", "reason": f"원인 시그니처 충족 — 재발 ({cause_sig})"}
    if not has_rec and not has_sce:
        out["user_confirmation_required"] = True   # user-setting·network·hw: 흔적 대신 사용자 확인 (note에 남긴다)
    elif not trace_hits:
        kind = "scenario" if sce_sigs else "recovery"
        return {**out, "reason": f"시나리오 흔적 없음 ({kind} 시그니처 불충족) — 재현 시나리오를 수행한 로그가 필요하다"}
    if S:
        return {**out, "judgement": "partial", "reason": "원인 불충족, 증상은 남아 있다 — 같은 증상의 다른 원인일 수 있다",
                "other_candidates": _other_candidates(result, cause, S)}
    if rec_sigs and not rec_hits:
        return {**out, "reason": "증상·원인 불충족이지만 recovery 시그니처가 충족되지 않음"}
    return {**out, "judgement": "passed", "reason": "시나리오 흔적 충족, 원인·증상 불충족"
                                                    + (", recovery 충족" if rec_hits else "")}


def _suggest(kind: str, cause_id: str, judged: dict, build: str | None) -> list[dict]:
    today = date.today().isoformat()
    fixture = "<parse_logcat cut 결과 경로>"
    j = judged["judgement"]
    if kind == "resolution":
        if j != "passed":
            return []
        return [{"op": "add-fixture", "for": cause_id, "kind": "resolved", "path": fixture},
                {"op": "verify-resolution", "cause": cause_id,
                 "verification": {"method": "해결책 적용 후 로그에서 재현되지 않음 (db_verify resolution passed)",
                                  "evidence": [fixture], "by": "<GHE 아이디>", "date": today}}]
    if j == "unknown":
        return []
    b = sanitize_build(build) if build else "<빌드>"
    v = {"build": build or "<빌드>", "date": today, "by": "<GHE 아이디>"}
    if j == "passed":
        trace = (judged.get("trace") or {}).get("signature")
        return [{"op": "add-fixture", "for": cause_id, "kind": "fixed", "build": b, "path": fixture},
                {"op": "verify-fix", "cause": cause_id, "result": "passed",
                 "verification": {**v, "fixture": fixture, **({"scenario_evidence": trace} if trace else {})}}]
    if j == "failed":
        return [{"op": "verify-fix", "cause": cause_id, "result": "failed",
                 "verification": {**v, "note": judged["reason"]}},
                {"op": "add-fixture", "for": cause_id, "kind": "recurrence", "build": b, "path": fixture,
                 "optional": True}]
    others = ", ".join(o.get("cause") or f"{o['type']}(원인 미확인)" for o in judged.get("other_candidates") or [])
    return [{"op": "verify-fix", "cause": cause_id, "result": "partial",
             "verification": {**v, "note": f"증상 남음. 다른 원인 후보: {others or '없음'}"}}]


def judge(args, defaults: dict, plugin_root: Path) -> tuple[dict, int]:
    if not args.cause:
        raise UsageError("--cause가 필요합니다.")
    if not args.logs:
        raise UsageError("판정할 logcat을 주세요.")
    paths = [Path(p) for p in args.logs]
    for p in paths:
        if not p.is_file():
            raise UsageError(f"로그 파일이 없습니다: {p}")
    if bool(args.plan) != bool(args.draft):
        raise UsageError("--plan과 --draft는 함께 쓴다.")
    draft = applied = None
    cause_id = args.cause
    rules_result = None
    try:
        if args.draft:
            draft = Path(args.draft)
            plan_path = Path(args.plan)
            applied = make_draft(plan_path, draft, defaults, args.plugin_root)
            mapping = {i["temp_id"]: i["id"] for i in applied.get("ids") or []}
            cause_id = mapping.get(cause_id, cause_id)
            root = draft
            rules_result, _ = verify_rules(draft, draft, "HEAD", plugin_root, defaults,
                                           _samples(_load_plan(args.plan), plan_path, [], []))
        else:
            try:
                root = dbpath.resolve(args.db)
            except dbpath.DbPathError as exc:
                raise UsageError(str(exc)) from exc
        run = Run(root, plugin_root, defaults)
        try:
            cause = run.db.cause_by_id(cause_id)
            if cause is None:
                raise UsageError(f"원인 {cause_id}가 이슈 DB에 없습니다.")
            if not cause.active or not run.db.type_by_id(cause.type_id).active:
                raise UsageError(f"원인 {cause_id}가 active가 아닙니다 ({cause.status}).")
            build_check = None
            if args.cmd == "fix":
                build_check = _check_fix_target(cause, args.build, run.db.config.get("build_compare") or [])
                judged = judge_fix(run, cause, paths)
            else:
                judged = judge_resolution(run, cause, paths)
        finally:
            run.close()
    finally:
        if draft is not None:
            remove_draft(draft, defaults)
    out = {"command": args.cmd, "db": str(root), "cause": cause_id, "type": cause.type_id, "requested": args.cause,
           "logs": [str(p) for p in paths], **judged}
    if build_check is not None:
        out["build_check"] = build_check
        out["fix_status"] = (cause.raw.get("fix") or {}).get("status")
    if rules_result is not None:
        out["rules"] = rules_result
        r1_row = next(r for r in rules_result["rules"] if r["id"] == "R1")
        trace_fail = [c for c in r1_row.get("checks", []) if c.get("part") == "trace" and c["status"] == "fail"]
        if trace_fail and out["judgement"] != "unknown":
            out.update(withheld=True, withheld_judgement=out["judgement"], judgement="unknown",
                       reason="흔적 시그니처가 R1 흔적 검사를 통과하지 못해 판정을 쓰지 않는다: "
                              + "; ".join(c["reason"] for c in trace_fail))
    out["suggested_ops"] = _suggest(args.cmd, cause_id, out, args.build if args.cmd == "fix" else None)
    return out, OK


# -- CLI -----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력 (항상 JSON)")
    common.add_argument("--plugin-root", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="db_verify.py", description=__doc__, parents=[common],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("rules", parents=[common])
    scope = p.add_mutually_exclusive_group(required=True)
    scope.add_argument("--plan")
    scope.add_argument("--changed", metavar="REF")
    scope.add_argument("--staged", action="store_true")
    p.add_argument("--draft")
    p.add_argument("--extra", nargs="*", default=[], help="R6 같은 증상 표본 (expect: match)")
    p.add_argument("--extra-normal", nargs="*", default=[], help="R6 정상 표본 (expect: nomatch)")
    p.add_argument("--regress-json", help=argparse.SUPPRESS)   # db_pr stage가 이미 돌린 회귀 결과를 넘긴다
    for name in ("resolution", "fix"):
        p = sub.add_parser(name, parents=[common])
        p.add_argument("logs", nargs="*")
        p.add_argument("--cause")
        p.add_argument("--plan")
        p.add_argument("--draft")
        if name == "fix":
            p.add_argument("--build")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    for name in ("db", "plugin_root"):
        if not hasattr(args, name):
            setattr(args, name, None)
    if not hasattr(args, "build"):
        args.build = None
    defaults = site_defaults.load_or_exit(args.plugin_root)
    plugin_root = Path(args.plugin_root) if args.plugin_root else site_defaults.plugin_root()
    try:
        if args.cmd == "rules":
            result, code = rules(args, defaults, plugin_root)
        else:
            result, code = judge(args, defaults, plugin_root)
    except UsageError as exc:
        print(str(exc), file=sys.stderr)
        return USAGE
    rows = result.get("rules") if args.cmd == "rules" else (result.get("rules") or {}).get("rules")
    for item in rows or []:
        if item["status"] in ("fail", "needs-approval"):
            print(f"{item['id']} {item['status']}: {item['reason']}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
