"""op `update-signature`·`set-status`."""

from __future__ import annotations

import copy

from ..core import CAUSE_ID_RE, SIG_LISTS, TYPE_ID_RE, Reject


class SignatureOps:

    def op_update_signature(self, i, op):
        owner, kind = op["owner"], op["kind"]
        if kind == "symptom":
            if not TYPE_ID_RE.match(owner) or owner not in self.tree.docs:
                raise Reject("signature-owner", f"증상 시그니처의 owner는 있는 유형 ID여야 합니다: {owner}", i)
            target = self.tree.docs[owner].data
        else:
            if not CAUSE_ID_RE.match(owner):
                raise Reject("signature-owner", f"{kind} 시그니처의 owner는 원인 ID여야 합니다: {owner}", i)
            _, target = self._cause_or_reject(i, owner)
        key = SIG_LISTS[kind]
        sigs = copy.deepcopy(target.get(key) or [])
        sig = op["signature"]
        if op.get("sig_id"):
            n = next((k for k, s in enumerate(sigs) if s.get("id") == op["sig_id"]), None)
            if n is None:
                raise Reject("signature-missing", f"{owner}에 {kind} 시그니처 {op['sig_id']}가 없습니다.", i)
            sigs[n] = sig
        else:
            if any(s.get("id") == sig["id"] for s in sigs):
                raise Reject("signature-exists", f"{owner}에 {kind} 시그니처 {sig['id']}가 이미 있습니다 "
                             "(교체하려면 sig_id).", i)
            sigs.append(sig)
        target[key] = sigs
        if kind == "cause" and target.get("signatures_pending"):
            del target["signatures_pending"]

    def op_set_status(self, i, op):
        ident, status = op["id"], op["status"]
        if TYPE_ID_RE.match(ident):
            if ident not in self.tree.docs:
                raise Reject("unknown-type", f"유형 {ident}가 없습니다.", i)
            target = self.tree.docs[ident].data
            pattern = TYPE_ID_RE
        else:
            _, target = self._cause_or_reject(i, ident)
            pattern = CAUSE_ID_RE
        if status.startswith("merged-into:"):
            dest = status.split(":", 1)[1]
            exists = dest in self.tree.docs if pattern is TYPE_ID_RE else self.tree.cause(dest)[1] is not None
            if not pattern.match(dest) or not exists or dest == ident:
                raise Reject("merged-into", f"병합 대상 {dest}가 없거나 종류가 다릅니다.", i)
        target["status"] = status
