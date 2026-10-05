"""op `set-resolution`·`verify-resolution`: 해결책과 검증 근거."""

from __future__ import annotations

from ..core import Reject


class ResolutionOps:

    def op_set_resolution(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        cause["resolution"] = op["resolution"]
        if op.get("resolution_type"):
            cause["resolution_type"] = op["resolution_type"]
        cause["resolution_verification"] = {"status": "unverified"}

    def op_verify_resolution(self, i, op):
        cause_id = op["cause"]
        doc, cause = self._cause_or_reject(i, cause_id)
        later = [j for j, o in enumerate(self.ops) if j > i and o["op"] == "set-resolution" and o["cause"] == cause_id]
        if later:
            raise Reject("order", f"verify-resolution은 같은 원인의 set-resolution(op {later[0]})보다 뒤에 와야 "
                         "합니다.", i)
        if cause.get("signatures_pending"):
            raise Reject("pending-verified", f"원인 {cause_id}는 signatures_pending이라 해결책을 verified로 할 수 "
                         "없습니다.", i)
        v = dict(op["verification"])
        evidence = []
        own = ((self.plan.get("jira") or {}).get("key")) if self.source == "record" else None
        for item in v["evidence"]:
            item = self.fixture_ref(item)
            if self.key_re.fullmatch(item):
                if own and item == own:
                    raise Reject("self-evidence", f"record 계획에서는 기록 대상 Jira {own} 자신을 해결책 근거로 쓸 수 "
                                 "없습니다 (사용자 진술이다).", i)
                self.jira_checks.append((i, cause_id, item))
            else:
                self._require_fixture(i, doc.id, item, evidence=True)
            evidence.append(item)
        rv = {"status": "verified"}
        if v.get("method"):
            rv["method"] = v["method"]
        rv.update(evidence=evidence, by=v["by"], date=v["date"])
        cause["resolution_verification"] = rv
