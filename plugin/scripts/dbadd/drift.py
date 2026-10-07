"""`drift`: 계획의 `base_sha` 트리와 `<ref>` 트리 비교 (contracts.md §작업 계획 drift 표)."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from common import gitscope, issuedb, yamlio
from common.exitcodes import CHECK_FAILED, OK
from common.fixtures import parse_name

from .applier import Applier
from .core import (HISTORY_FIELDS, RULE_SECTIONS, SIG_LISTS, TEMP_RE, TYPE_ID_RE, Reject, Tree, UsageError, _db,
                   load_plan, validate_plan)
from .ops.parser_rules import ParserRuleOps


class Snapshot:
    """ref 하나의 트리(임시 디렉토리로 꺼낸 것)에서 drift 비교에 쓰는 값."""

    def __init__(self, root: Path):
        self.root = root
        self.db = issuedb.load(root)
        self.rules = {f: (yamlio.load(root / "parser-rules" / f) or {}) if (root / "parser-rules" / f).is_file()
                      else {} for f in RULE_SECTIONS}

    def cause(self, cid: str) -> dict | None:
        c = self.db.cause_by_id(cid)
        return c.raw if c else None

    def type(self, tid: str) -> dict | None:
        t = self.db.type_by_id(tid)
        return t.raw if t else None

    def status(self, ident: str) -> str | None:
        raw = self.type(ident) if TYPE_ID_RE.match(ident) else self.cause(ident)
        return str(raw.get("status", "active")) if raw else None

    def jira(self, key: str) -> dict | None:
        rec = next((r for r in self.db.jira if r.get("key") == key), None)
        return rec

    def expect(self, rel: str) -> tuple[bool, dict]:
        name = rel.split("/", 1)[-1]
        fx = parse_name(name)
        if fx is None:
            return False, {}
        t = self.db.type_by_id(fx.type_id)
        if t is None:
            return False, {}
        log = t.path / "fixtures" / name
        exp = t.path / "fixtures" / f"{fx.stem}.expect.yaml"
        data = (yamlio.load(exp) or {}) if exp.is_file() else {}
        return log.is_file(), data


def _functional(rule: dict) -> dict:
    return {k: v for k, v in (rule or {}).items() if k not in HISTORY_FIELDS}


def drift_items(plan: dict, base: Snapshot, onto: Snapshot) -> list[dict]:
    out = []
    ops = plan.get("operations") or []
    planned_fixtures = {op["path"] for op in ops if op.get("op") == "add-fixture"}

    def add(i, op, target, field, a, b, plan_value=None):
        # plan_value: 이 op가 그 field에 쓰는 값 (쓰지 않으면 None). plan_base_value는 계획 당시 main 값.
        out.append({"op_index": i, "op": op["op"], "target": target, "field": field, "plan_value": plan_value,
                    "plan_base_value": a, "current_value": b})

    def check_active(i, op, ident):
        if TEMP_RE.fullmatch(ident or ""):
            return
        a, b = base.status(ident), onto.status(ident)
        if a != b and b != "active":
            add(i, op, ident, "status", a, b)

    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind in ("append", "add-code-ref"):
            check_active(i, op, op["cause"])
        elif kind == "unresolved":
            check_active(i, op, op["type"])
        elif kind == "new-cause":
            check_active(i, op, op["type"])
        elif kind == "add-related":
            check_active(i, op, op["a"])
            check_active(i, op, op["b"])
        elif kind == "add-fixture":
            check_active(i, op, op["for"])
        elif kind == "new-type":
            spec = op["type"]
            for t in onto.db.types:
                if t.category != op["category"] or base.type(t.id) is not None:
                    continue
                if t.title == spec["title"] or t.raw.get("symptom_signatures") == spec["symptom_signatures"]:
                    add(i, op, t.id, "similar-type", None, {"id": t.id, "title": t.title},
                        {"title": spec["title"]})
        elif kind == "reclassify":
            a, b = base.jira(op["jira"]), onto.jira(op["jira"])
            if b is None or str(b.get("cause")) != op["from"]:
                add(i, op, op["jira"], "cause", a.get("cause") if a else None, b.get("cause") if b else None,
                    op.get("to"))
        elif kind in ("update-fix", "verify-fix"):
            if TEMP_RE.fullmatch(op["cause"]):
                continue
            a, b = (base.cause(op["cause"]) or {}).get("fix"), (onto.cause(op["cause"]) or {}).get("fix")
            if a != b:
                if kind == "update-fix":
                    pv = op.get("fix")
                else:
                    pv = {"result": op.get("result"), "verification": op.get("verification")}
                add(i, op, op["cause"], "fix", a, b, pv)
        elif kind in ("set-resolution", "verify-resolution"):
            if TEMP_RE.fullmatch(op["cause"]):
                continue
            ca, cb = base.cause(op["cause"]) or {}, onto.cause(op["cause"]) or {}
            for field in ("resolution", "resolution_verification"):
                if ca.get(field) != cb.get(field):
                    if kind == "set-resolution":
                        pv = op.get("resolution") if field == "resolution" else None
                    else:
                        pv = op.get("verification") if field == "resolution_verification" else None
                    add(i, op, op["cause"], field, ca.get(field), cb.get(field), pv)
        elif kind == "update-signature":
            owner = op["owner"]
            if TEMP_RE.fullmatch(owner):
                continue
            key = SIG_LISTS[op["kind"]]
            ta = (base.type(owner) if op["kind"] == "symptom" else base.cause(owner)) or {}
            tb = (onto.type(owner) if op["kind"] == "symptom" else onto.cause(owner)) or {}
            if op.get("sig_id"):
                sa = next((s for s in ta.get(key) or [] if s.get("id") == op["sig_id"]), None)
                sb = next((s for s in tb.get(key) or [] if s.get("id") == op["sig_id"]), None)
                if sa != sb:
                    add(i, op, f"{owner}/{op['sig_id']}", key, sa, sb, op.get("signature"))
            else:
                sid = op["signature"]["id"]
                sb = next((s for s in tb.get(key) or [] if s.get("id") == sid), None)
                sa = next((s for s in ta.get(key) or [] if s.get("id") == sid), None)
                if sb is not None and sa is None:
                    add(i, op, f"{owner}/{sid}", key, None, sb, op.get("signature"))
        elif kind in ("add-parser-rule", "update-parser-rule"):
            sections = RULE_SECTIONS.get(op["file"], ())
            section = op.get("section") or (sections[0] if sections else None)
            if section is None:
                continue
            key = op.get("key") or ParserRuleOps._rule_key(section, op["rule"])
            find = lambda snap: next((r for r in snap.rules.get(op["file"], {}).get(section) or []  # noqa: E731
                                      if ParserRuleOps._rule_key(section, r) == key), None)
            ra, rb = find(base), find(onto)
            if kind == "add-parser-rule":
                if rb is not None and ra is None:
                    add(i, op, f"{op['file']}:{key}", section, None, rb, _functional(op.get("rule")))
            elif rb is None or _functional(ra) != _functional(rb):
                add(i, op, f"{op['file']}:{key}", section, _functional(ra) if ra else None,
                    _functional(rb) if rb else None, _functional(op.get("rule")))
        elif kind == "set-status":
            a, b = base.status(op["id"]), onto.status(op["id"])
            if a != b:
                add(i, op, op["id"], "status", a, b, op.get("status"))
        elif kind == "allow-cause":
            if op["fixture"] in planned_fixtures or TEMP_RE.search(op["fixture"]):
                continue
            ea, da = base.expect(op["fixture"])
            eb, db_ = onto.expect(op["fixture"])
            if not eb:
                add(i, op, op["fixture"], "fixture", ea, eb, None)
                continue
            for field in ("also_allowed", "expect_top"):
                if da.get(field) != db_.get(field):
                    add(i, op, op["fixture"], field, da.get(field), db_.get(field),
                        op.get("cause") if field == "also_allowed" else None)
    return out


def _ids_at_base(plan: dict, base_root: Path, plan_path: Path, defaults: dict) -> list[dict] | None:
    """계획 당시(base_sha) 트리 기준 임시 ID 할당. 새 유형·원인이 없거나 계산할 수 없으면 None."""
    ops = plan.get("operations")
    if not isinstance(ops, list) or not any(isinstance(o, dict) and o.get("op") in ("new-cause", "new-type")
                                            for o in ops):
        return None
    try:
        return Applier(Tree(base_root), plan, plan_path, "-", defaults).assign_ids()
    except (Reject, UsageError, KeyError, TypeError):
        return None


def cmd_drift(args, defaults: dict) -> tuple[dict, int]:
    db = _db(args)
    plan = load_plan(Path(args.plan))
    base_sha = plan.get("base_sha")
    if not isinstance(base_sha, str) or not base_sha:
        raise UsageError("계획에 base_sha가 없습니다 (db_pr snapshot의 snapshot_sha를 넣는다 — write-flow.md §계획 형식).")
    temp = Path(tempfile.mkdtemp(prefix="tt-drift-"))
    try:
        try:
            onto_sha = gitscope.git(db, "rev-parse", f"{args.onto}^{{commit}}").strip()
            base_root = gitscope.materialize_ref(db, base_sha, temp / "base")
            onto_root = gitscope.materialize_ref(db, onto_sha, temp / "onto")
        except gitscope.GitError as exc:
            raise UsageError(f"drift 비교용 트리를 꺼낼 수 없습니다 (base_sha {base_sha}가 이 레포에 있는지 확인): {exc}") \
                from exc
        try:
            validate_plan(plan, onto_root)   # apply와 같은 트리·스키마(upgrade-plan·main 스키마 변경 뒤에도 맞다)
            items = drift_items(plan, Snapshot(base_root), Snapshot(onto_root))
            ids_at_base = _ids_at_base(plan, base_root, Path(args.plan), defaults)
        except (issuedb.IssueDbError, yamlio.YamlFileError) as exc:
            raise UsageError(str(exc)) from exc
    finally:
        shutil.rmtree(temp, ignore_errors=True)
    return {"base_sha": base_sha, "onto": args.onto, "onto_sha": onto_sha, "drift": items,
            "ids_at_base": ids_at_base}, (CHECK_FAILED if items else OK)
