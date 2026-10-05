"""op `update-fix`·`verify-fix`: 수정 상태 (`fixed`는 verify-fix로만)."""

from __future__ import annotations

import copy

from ..core import Reject


class FixOps:

    def _check_fix_ref(self, i: int, ref) -> None:
        if ref is not None and self.fix_ref_re is not None and not self.fix_ref_re.fullmatch(str(ref)):
            raise Reject("fix-ref", f"fix.ref {ref}가 fix_ref_regex에 맞지 않습니다.", i)

    def _history_item(self, result: str, fix: dict, extra: dict, keep_fix: bool) -> dict:
        item = {"result": result}
        if extra.get("build"):
            item["build"] = extra["build"]
        item.update(date=extra.get("date") or self.day, by=extra.get("by") or self.user)
        if extra.get("jira"):
            item["jira"] = extra["jira"]
        if extra.get("fixture"):
            item["fixture"] = self.fixture_ref(extra["fixture"])
        if keep_fix:
            item["ref"] = fix.get("ref")
            item["fixed_in"] = copy.deepcopy(fix.get("fixed_in") or [])
        if extra.get("note"):
            item["note"] = extra["note"]
        return item

    def _reopen(self, fix: dict, result: str, extra: dict) -> None:
        history = list(fix.get("verification_history") or [])
        history.insert(0, self._history_item(result, fix, extra, keep_fix=True))
        fix.update(status="open", verification=None, ref=None, fixed_in=[], verification_history=history)

    def op_update_fix(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        fix = cause["fix"] = copy.deepcopy(cause.get("fix") or {})
        for key, default in (("ref", None), ("fixed_in", []), ("verification", None), ("verification_history", [])):
            fix.setdefault(key, default)
        new = op["fix"]
        status = new.get("status", fix.get("status"))
        if fix.get("status") == "fixed" and status == "fix-submitted":
            raise Reject("fixed-to-fix-submitted", "fixed 원인을 fix-submitted로 바꿀 수 없습니다. 먼저 verify-fix 실패나 "
                         "회귀 의심으로 open으로 되돌린다.", i)
        if status == "fixed":
            raise Reject("update-fix-fixed", "fixed로 바꾸는 것은 verify-fix op만 할 수 있습니다.", i)
        if status == "open" and fix.get("status") != "open":
            history = op.get("history") or {}
            result = history.get("result") or ("passed" if fix.get("verification") else "reverted")
            self._reopen(fix, result, history)
            return
        if "ref" in new:
            self._check_fix_ref(i, new["ref"])
            fix["ref"] = new["ref"]
        if "fixed_in" in new:
            merged = list(fix.get("fixed_in") or [])
            for entry in new["fixed_in"]:
                same = next((e for e in merged if e.get("branch") == entry.get("branch")), None)
                if same is None:
                    merged.append(dict(entry))
                else:
                    same.update(entry)
            fix["fixed_in"] = merged
        fix["status"] = status
        if status == "fix-submitted" and (not fix.get("ref") or not fix.get("fixed_in")):
            raise Reject("fix-fields", "fix-submitted에는 ref와 fixed_in이 필요합니다.", i)
        if status != "fixed":
            fix["verification"] = None

    def op_verify_fix(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        fix = cause["fix"] = copy.deepcopy(cause.get("fix") or {})
        v = dict(op["verification"])
        if v.get("fixture"):   # passed는 스키마가 필수로 본다. failed·partial은 선택
            v["fixture"] = self.fixture_ref(v["fixture"])
            self._require_fixture(i, op["cause"].rsplit("-", 1)[0], v["fixture"])
        if op["result"] == "passed":
            if fix.get("status") not in ("fix-submitted", "fixed"):
                raise Reject("verify-fix-status", f"verify-fix 통과는 fix-submitted(재검증이면 fixed) 원인만 됩니다 "
                             f"(지금 {fix.get('status')}).", i)
            if not any(e.get("build") for e in fix.get("fixed_in") or []):
                raise Reject("fixed-in-build-missing", "fixed_in에 빌드가 있는 항목이 없습니다. 먼저 fix-submitted로 "
                             "빌드를 추가한다.", i)
            record = {"result": "passed", "build": v["build"], "date": v["date"], "by": v["by"]}
            for key in ("jira", "fixture", "scenario_evidence", "note"):
                if v.get(key):
                    record[key] = v[key]
            fix.update(status="fixed", verification=record)
        elif op["result"] == "failed":
            self._reopen(fix, "failed", v)
        else:
            history = list(fix.get("verification_history") or [])
            history.insert(0, self._history_item("partial", fix, v, keep_fix=False))
            fix["verification_history"] = history
