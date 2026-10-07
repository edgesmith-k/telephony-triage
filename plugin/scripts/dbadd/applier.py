"""`apply`: 임시 ID·fixture 이름 할당, op 순서 적용, 피드백 (contracts.md §작업 계획)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import yaml

from common import yamldoc, yamlio
from common.buildname import sanitize_build
from common.exitcodes import CHECK_FAILED, OK

from .core import CAUSE_ID_RE, TEMP_RE, TYPE_ID_RE, Reject, Tree, UsageError, _db, _num, load_plan, plan_day, user_id, validate_plan
from .ops.entities import EntityOps
from .ops.fix import FixOps
from .ops.fixture import FixtureOps
from .ops.jira import JiraOps
from .ops.parser_rules import ParserRuleOps
from .ops.resolution import ResolutionOps
from .ops.signature import SignatureOps


class Applier(JiraOps, EntityOps, FixOps, ResolutionOps, SignatureOps, FixtureOps, ParserRuleOps):
    """계획 하나를 메모리의 `Tree`에 순서대로 적용한다. op `<이름>`은 메서드 `op_<이름>`(ops/ 믹스인)."""

    def __init__(self, tree: Tree, plan: dict, plan_path: Path, user: str, defaults: dict):
        self.tree = tree
        self.plan = plan
        self.plan_dir = Path(plan_path).resolve().parent
        self.user = user
        self.defaults = defaults
        self.source = plan["source"]
        self.config = tree.config
        self.day = plan_day(plan)
        self.mapping: dict[str, str] = {}
        self.fixture_names: dict[int, tuple[str, str]] = {}   # op index → (유형 ID, 이름)
        self.fixture_paths: dict[str, str] = {}               # 계획 path → fixtures/<이름>
        self.created: set[str] = set()                         # 이 계획이 만든 원인·유형 (적용된 것)
        self.new_ids: set[str] = set()                         # 이 계획이 만들 원인·유형 (전체)
        self.jira_checks: list[tuple[int, str, str]] = []      # (op, cause, Jira 키) 적용 후 확인
        self.warnings: list[str] = []
        self.allow = [str(p) for p in ((self.config.get("mask") or {}).get("allow_patterns") or [])]
        self.key_re = re.compile(str(self.config.get("jira_key_regex") or r"[A-Z][A-Z0-9]+-\d+"))
        ref_re = self.config.get("fix_ref_regex")
        self.fix_ref_re = re.compile(str(ref_re)) if ref_re else None

    # 임시 ID ---------------------------------------------------------------------------

    def assign_ids(self) -> list[dict]:
        next_type: dict[str, int] = {}
        for doc in self.tree.docs.values():
            cat = str(doc.data.get("category"))
            next_type[cat] = max(next_type.get(cat, 0), _num(doc.id))
        next_cause = {tid: max(doc.cause_numbers() or [0]) for tid, doc in self.tree.docs.items()}
        out = []
        for i, op in enumerate(self.plan["operations"]):
            if op["op"] == "new-type":
                cat = op["category"]
                if cat not in self.tree.categories:
                    raise Reject("category", f"카테고리 {cat}가 issue-db.config.yaml categories에 없습니다.", i)
                n = next_type.get(cat, 0) + 1
                next_type[cat] = n
                tid = f"{self.tree.categories[cat]}-{n:03d}"
                self._map(op["temp_id"], tid, i, out)
                self._map(op["first_cause"]["temp_id"], f"{tid}-01", i, out)
                next_cause[tid] = 1
            elif op["op"] == "new-cause":
                tid = self.mapping.get(op["type"], op["type"])
                if tid not in next_cause:
                    raise Reject("unknown-type", f"유형 {op['type']}가 없습니다.", i)
                n = next_cause[tid] + 1
                if n > 99:
                    raise Reject("id-overflow", f"유형 {tid}의 원인 번호가 99를 넘습니다.", i)
                next_cause[tid] = n
                self._map(op["temp_id"], f"{tid}-{n:02d}", i, out)
        self.new_ids = set(self.mapping.values())
        return out

    def _map(self, temp: str, real: str, i: int, out: list) -> None:
        if temp in self.mapping:
            raise Reject("duplicate-temp-id", f"임시 ID {temp}가 두 번 정의됐습니다.", i)
        self.mapping[temp] = real
        out.append({"temp_id": temp, "id": real})

    def substitute(self, value):
        if isinstance(value, str):
            def repl(m):
                if m.group(0) not in self.mapping:
                    raise Reject("unknown-temp-id", f"정의되지 않은 임시 ID {m.group(0)}를 참조합니다.")
                return self.mapping[m.group(0)]
            return TEMP_RE.sub(repl, value)
        if isinstance(value, list):
            return [self.substitute(v) for v in value]
        if isinstance(value, dict):
            return {k: self.substitute(v) for k, v in value.items()}
        return value

    # fixture 이름 --------------------------------------------------------------------

    def assign_fixtures(self, ops: list[dict]) -> list[dict]:
        taken: dict[Path, set[str]] = {}
        out = []
        for i, op in enumerate(ops):
            if op["op"] != "add-fixture":
                continue
            kind, target = op["kind"], op["for"]
            if kind == "negative":
                if not TYPE_ID_RE.match(target):
                    raise Reject("fixture-for", f"negative fixture의 for는 유형 ID여야 합니다: {target}", i)
                type_id = target
            else:
                if not CAUSE_ID_RE.match(target):
                    raise Reject("fixture-for", f"{kind} fixture의 for는 원인 ID여야 합니다: {target}", i)
                type_id = target.rsplit("-", 1)[0]
            if type_id not in self.tree.docs and type_id not in self.new_ids:
                raise Reject("unknown-type", f"fixture 대상 유형 {type_id}가 없습니다.", i)
            fdir = self._fixture_dir(type_id, ops)
            names = taken.setdefault(fdir, {p.name for p in fdir.glob("*")} if fdir.is_dir() else set())
            name = self._fixture_name(kind, target, op.get("build"), names, i)
            names.add(name)
            self.fixture_names[i] = (type_id, name)
            self.fixture_paths[op["path"]] = f"fixtures/{name}"
            out.append({"op_index": i, "for": target, "kind": kind, "name": name, "path": f"fixtures/{name}"})
        return out

    def _fixture_dir(self, type_id: str, ops: list[dict]) -> Path:
        if type_id in self.tree.docs:
            return self.tree.type_dir(type_id) / "fixtures"
        for op in ops:
            if op["op"] == "new-type" and self.mapping.get(op["temp_id"]) == type_id:
                return self.tree.root / op["category"] / f"{type_id}-{op['dir_slug']}" / "fixtures"
            if op["op"] == "new-type" and op["temp_id"] == type_id:
                return self.tree.root / op["category"] / f"{type_id}-{op['dir_slug']}" / "fixtures"
        raise Reject("unknown-type", f"fixture 대상 유형 {type_id}가 없습니다.")

    @staticmethod
    def _fixture_name(kind: str, target: str, build: str | None, names: set[str], i: int) -> str:
        def free(stem: str) -> bool:
            return f"{stem}.log" not in names

        if kind in ("fixed", "recurrence"):
            if not build:
                raise Reject("fixture-build", f"{kind} fixture에는 build가 필요합니다.", i)
            stem = f"{target}.{kind}.{sanitize_build(build)}"
            if not free(stem):
                raise Reject("fixture-exists", f"같은 이름의 fixture가 이미 있습니다: {stem}.log", i)
            return f"{stem}.log"
        if kind in ("resolved", "extra"):
            n = 1
            while not free(f"{target}.{kind}.{n}"):
                n += 1
            return f"{target}.{kind}.{n}.log"
        base = f"{target}.none" if kind == "negative" else target
        if free(base):
            return f"{base}.log"
        n = 2
        while not free(f"{base}.{n}"):
            n += 1
        return f"{base}.{n}.log"

    def fixture_ref(self, value: str) -> str:
        return self.fixture_paths.get(value, value)

    # 실행 ------------------------------------------------------------------------------

    def run(self, pending: list[Path]) -> dict:
        plan = self.plan
        if plan.get("schema_version") != self.config.get("schema_version"):
            raise UsageError(
                f"계획 schema_version {plan.get('schema_version')}이 이슈 DB {self.config.get('schema_version')}와 "
                "다릅니다. 해당 마이그레이션이 upgrade_plan()을 제공하면 `db_migrate upgrade-plan`으로 계획을 먼저 "
                "올리고, 아니면 계획을 다시 만든다 (06-collaboration.md §6.4).")
        if pending and self.source != "analyze":
            raise UsageError(f"pending 피드백은 source: analyze 계획에만 넣는다 (지금 source: {self.source}).")
        if self.source == "import":
            count = sum(1 for op in plan["operations"] if op["op"] == "new-type")
            if count > 10:
                raise Reject("import-too-many", f"import 계획은 PR당 새 유형 10개 이하입니다 ({count}개).")
        ids = self.assign_ids()
        ops = [self.substitute(op) for op in plan["operations"]]
        feedback = self.substitute(plan.get("feedback")) if plan.get("feedback") else None
        commit = self.substitute(plan.get("commit_message") or "")
        fixtures = self.assign_fixtures(ops)
        self.ops = ops
        for i, op in enumerate(ops):
            try:
                getattr(self, "op_" + op["op"].replace("-", "_"))(i, op)
            except Reject as exc:
                if exc.op_index is None:
                    exc.op_index = i
                raise
        self._post_checks()
        fb_path = self._feedback(feedback)
        included = [self._pending(p) for p in pending]
        return {"ids": ids, "fixtures": fixtures, "commit_message": commit, "feedback": fb_path,
                "pending_included": [p for p in included if p], "operations": ops}

    # op들이 같이 쓰는 확인 ------------------------------------------------------------

    def _require_fixture(self, i: int, type_id: str, rel: str, evidence: bool = False) -> None:
        tdir = self._type_dir_any(type_id)
        if not rel.startswith("fixtures/") or not self.tree.exists(tdir / rel):
            planned = any(self.fixture_names.get(j) == (type_id, rel.split("/", 1)[-1]) for j in self.fixture_names)
            if not planned:
                raise Reject("evidence-missing" if evidence else "fixture-missing",
                             f"fixture {rel}가 {type_id}에 없습니다.", i)

    def _type_dir_any(self, type_id: str) -> Path:
        return self.tree.type_dir(type_id) if type_id in self.tree.docs else self._fixture_dir(type_id, self.ops).parent

    def _post_checks(self) -> None:
        jira = self.tree.jira_files()
        for i, cause_id, key in self.jira_checks:
            path = jira.get(key)
            record = yamlio.loads(self.tree.read(path) or "") if path else None
            if not record or str(record.get("cause")) != cause_id:
                raise Reject("evidence-missing", f"근거 Jira {key}가 원인 {cause_id}의 Jira 기록으로 없습니다.", i)

    # 피드백 ------------------------------------------------------------------------------

    def _feedback(self, feedback: dict | None) -> str | None:
        if not feedback:
            return None
        jira = self.plan.get("jira")
        if not jira:
            self.warnings.append("jira가 없는 계획이라 피드백을 쓰지 않았다.")
            return None
        if self.source == "import":
            self.warnings.append("import 계획은 피드백을 기록하지 않는다 (16-existing-assets.md §16.4).")
            return None
        stamp = datetime.fromisoformat(str(feedback["date"]).replace("Z", "+00:00"))
        record = {"jira": jira["key"], "date": feedback["date"], "by": self.user,
                  "suggested": feedback.get("suggested") or [], "decision": feedback["decision"],
                  "final": feedback["final"]}
        path = self.tree.root / "feedback" / f"{stamp:%Y-%m}" / f"{jira['key']}-{stamp:%Y%m%dT%H%M}.yaml"
        self.tree.write(path, yamldoc.dump_doc(record))
        return self.tree.rel(path)

    def _pending(self, src: Path) -> str | None:
        text = Path(src).read_text(encoding="utf-8")
        try:
            record = yamlio.loads(text) or {}
            stamp = datetime.fromisoformat(str(record.get("date")).replace("Z", "+00:00"))
        except (yaml.YAMLError, AttributeError, ValueError) as exc:
            raise Reject("pending-invalid", f"pending 피드백 {Path(src).name}을 읽을 수 없다(매핑·date ISO 시각 필요): {exc}") from None
        path = self.tree.root / "feedback" / f"{stamp:%Y-%m}" / Path(src).name
        if self.tree.exists(path):
            self.warnings.append(f"pending 피드백 {Path(src).name}은 이미 이슈 DB에 있어 건너뛰었다.")
            return None
        self.tree.write(path, text)
        return self.tree.rel(path)


def cmd_apply(args, defaults: dict) -> tuple[dict, int]:
    if not args.db:   # 기본값(cwd toplevel·config issue_db.path)은 사용자 clone일 수 있다 — 쓰기는 worktree만
        raise UsageError("apply는 --db <worktree>가 필요하다 (db_pr stage·db_verify rules --draft가 준다). 사용자 clone에는 쓰지 않는다.")
    db = _db(args)
    plan = load_plan(Path(args.plan))
    validate_plan(plan, db)
    tree = Tree(db)
    applier = Applier(tree, plan, Path(args.plan), user_id(args.user, defaults), defaults)
    try:
        result = applier.run([Path(p) for p in args.pending or []])
    except Reject as exc:
        return {"applied": False, "source": plan["source"], "rejected": [exc.as_dict()]}, CHECK_FAILED
    changes = tree.flush()
    return {"applied": True, "db": str(db), "source": plan["source"], "changed": changes,
            "ids": result["ids"], "fixtures": result["fixtures"], "commit_message": result["commit_message"],
            "feedback": result["feedback"], "pending_included": result["pending_included"],
            "operations": result["operations"], "warnings": applier.warnings}, OK
