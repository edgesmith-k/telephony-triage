"""op `put-flow`: 성공 흐름 `<category>/flows/<id>.yaml`(+ 정상 fixture)을 넣거나 통째로 바꾼다 (04-parser-matching.md §5.13)."""

from __future__ import annotations

import json

import jsonschema
import yaml

from common import yamldoc, yamlio
from common.flows import FIXTURE_RE

from ..core import Reject


class FlowOps:

    def _names(self, fdir) -> set[str]:
        """적용 중인 트리(앞 op의 쓰기·지우기 포함) 기준 디렉토리의 파일 이름."""
        names = {p.name for p in fdir.iterdir() if p not in self.tree.deletes} if fdir.is_dir() else set()
        return names | {p.name for p in self.tree.writes if p.parent == fdir}

    def op_put_flow(self, i, op):
        ref, flow = op["ref"], op["flow"]
        cat, fid = ref.split("/")
        if cat not in self.tree.categories:
            raise Reject("category", f"카테고리 {cat}가 issue-db.config.yaml categories에 없습니다.", i)
        schema = self.tree.root / "schema" / "flow.schema.json"
        if not schema.is_file():
            raise Reject("flow-schema", "이슈 DB에 schema/flow.schema.json이 없습니다 (흐름을 아는 스키마로 먼저 올린다).", i)
        error = jsonschema.exceptions.best_match(
            jsonschema.Draft202012Validator(json.loads(schema.read_text(encoding="utf-8"))).iter_errors(flow))
        if error is not None:
            where = "/".join(map(str, error.absolute_path)) or "(최상위)"
            raise Reject("flow-schema", f"흐름 {ref}: {where}: {error.message}", i)
        if flow["id"] != fid:
            raise Reject("flow-id", f"흐름 id {flow['id']}가 ref {ref}와 다릅니다.", i)
        path = self.tree.root / cat / "flows" / f"{fid}.yaml"
        old = self.tree.read(path)
        if old is not None:     # 바꾸기: 없어지는 단계를 가리키는 원인 flow_step이 있으면 거부
            try:
                steps = (yamlio.loads(old) or {}).get("steps") or []
            except (yaml.YAMLError, AttributeError):
                steps = []
            gone = {f"{ref}/{s.get('id')}" for s in steps if isinstance(s, dict)} - {f"{ref}/{s['id']}" for s in flow["steps"]}
            users = sorted(str(c.get("id")) for d in self.tree.docs.values() for c in d.data.get("causes") or []
                           if c.get("flow_step") in gone)
            if users:
                raise Reject("flow-step-in-use", f"흐름 {ref}에서 없어지는 단계를 원인이 가리킵니다: {', '.join(users)} "
                             "(단계 id를 남기거나 원인 flow_step을 먼저 바꾼다).", i)
        fdir = path.parent / "fixtures"
        names = self._names(fdir)
        for item in op.get("fixtures") or []:
            masked = self._masked_fixture(i, item["path"], "put-flow")
            n = 1
            while f"{fid}.normal.{n}.log" in names:
                n += 1
            names.add(f"{fid}.normal.{n}.log")
            self.tree.write(fdir / f"{fid}.normal.{n}.log", masked)
        if not any((m := FIXTURE_RE.match(name)) and m["id"] == fid for name in names):
            raise Reject("flow-fixture-missing", f"흐름 {ref}에 정상 fixture가 없습니다 (fixtures에 정상 로그를 하나 이상 싣는다).", i)
        self.tree.write(path, yamldoc.dump_doc(flow))
