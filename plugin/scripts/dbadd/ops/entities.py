"""op `new-cause`·`new-type`·`add-related`·`add-code-ref`: 원인·유형."""

from __future__ import annotations

import re

from common import masking
from common.typedoc import TypeDoc

from ..core import CAUSE_KEYS_DEFAULT, TYPE_KEYS, Reject


class EntityOps:

    def _cause_keys(self) -> list[str]:
        path = self.tree.root / "templates" / "cause.yaml"
        keys = []
        if path.is_file():
            keys = re.findall(r"^\s*(?:-\s+)?([a-z_]+):", path.read_text(encoding="utf-8"), flags=re.M)
        return keys or CAUSE_KEYS_DEFAULT

    def _build_cause(self, i: int, cause_id: str, body: dict) -> dict:
        signatures = body.get("signatures") or []
        pending = not signatures
        if pending:
            if not body.get("signatures_pending"):
                raise Reject("signatures-missing", f"새 원인 {cause_id}에 판별 시그니처가 없습니다 "
                             "(signatures_pending은 record에서 사용자가 명시할 때만).", i)
            if self.source != "record":
                raise Reject("pending-not-allowed", f"signatures_pending 원인은 source: record 계획에서만 만들 수 "
                             f"있습니다 (지금 source: {self.source}).", i)
        fix = {"status": "open", "ref": None, "fixed_in": [], "verification": None, "verification_history": []}
        fix.update({k: v for k, v in (body.get("fix") or {}).items() if k in ("status", "ref", "fixed_in")})
        if fix["status"] == "fixed":
            raise Reject("new-cause-fixed", "새 원인은 fixed로 시작할 수 없습니다 (verify-fix로만).", i)
        self._check_fix_ref(i, fix.get("ref"))
        if fix["status"] == "fix-submitted" and (not fix.get("ref") or not fix.get("fixed_in")):
            raise Reject("fix-fields", "fix-submitted에는 ref와 fixed_in이 필요합니다.", i)
        rv = {"status": "unverified"}
        method = (body.get("resolution_verification") or {}).get("method")
        if method:
            rv["method"] = method
        values = {
            "id": cause_id, "status": "active", "title": body["title"], "description": body["description"],
            "signatures": signatures, "recovery_signatures": body.get("recovery_signatures") or [],
            "scenario_signatures": body.get("scenario_signatures") or [], "resolution": body["resolution"],
            "resolution_type": body["resolution_type"], "resolution_verification": rv, "fix": fix,
            "related": [], "android_versions": body.get("android_versions") or [],
            "code_refs": body.get("code_refs") or [],
        }
        for ref in values["code_refs"]:
            self._check_code_ref(i, ref)
        out = {}
        for key in self._cause_keys():
            if key in values:
                out[key] = values.pop(key)
            if key == "signatures" and pending:
                out["signatures_pending"] = True
            if key == "related" and body.get("cp_evidence"):
                out["cp_evidence"] = masking.new_masker(allow_patterns=self.allow).mask(str(body["cp_evidence"]))
        out.update(values)
        return out

    def _link_related(self, i: int, cause_id: str, related: list[str]) -> None:
        for other in related or []:
            self._add_related(i, cause_id, other)

    def op_new_cause(self, i, op):
        type_id = op["type"]
        doc = self.tree.docs.get(type_id)
        if doc is None:
            raise Reject("unknown-type", f"유형 {type_id}가 없습니다.", i)
        cause_id = op["temp_id"]
        cause = self._build_cause(i, cause_id, op["cause"])
        doc.add_cause(cause, cause["title"], op["body"])
        self.created.add(cause_id)
        self._link_related(i, cause_id, op["cause"].get("related"))

    def op_new_type(self, i, op):
        type_id = op["temp_id"]
        spec = op["type"]
        if not spec.get("symptom_signatures"):
            raise Reject("symptom-missing", "새 유형에는 증상 시그니처가 필수입니다 (모든 source).", i)
        cat = op["category"]
        tdir = self.tree.root / cat / f"{type_id}-{op['dir_slug']}"
        if tdir.exists():
            raise Reject("type-dir-exists", f"유형 디렉토리가 이미 있습니다: {self.tree.rel(tdir)}", i)
        first = op["first_cause"]
        cause_id = first["temp_id"]
        cause = self._build_cause(i, cause_id, first["cause"])
        values = {"id": type_id, "category": cat, "secondary_categories": spec.get("secondary_categories") or [],
                  "title": spec["title"], "summary": spec["summary"], "status": "active",
                  "symptom_signatures": spec["symptom_signatures"], "causes": [cause], "tags": spec.get("tags") or []}
        front = {k: values[k] for k in TYPE_KEYS}
        body = op["body"].strip()
        if not body.startswith("## "):
            body = "## 증상\n\n" + body
        text = f"\n{body}\n\n## 원인별 상세\n\n### {cause_id} {cause['title']}\n\n{first['body'].rstrip()}\n"
        doc = TypeDoc.new(tdir / "type.md", front, text)
        self.tree.docs[type_id] = doc
        self.created.update({type_id, cause_id})
        self._link_related(i, cause_id, first["cause"].get("related"))

    def _cause_or_reject(self, i: int, cause_id: str) -> tuple[TypeDoc, dict]:
        doc, cause = self.tree.cause(cause_id)
        if cause is None:
            if cause_id in self.new_ids:
                raise Reject("order", f"원인 {cause_id}는 이 op보다 뒤에서 만들어집니다 (op 순서를 바꾼다).", i)
            raise Reject("unknown-cause", f"원인 {cause_id}가 없습니다.", i)
        return doc, cause

    def _add_related(self, i: int, a: str, b: str) -> None:
        if a == b:
            raise Reject("related-self", f"원인 {a}를 자기 자신과 연결할 수 없습니다.", i)
        _, ca = self._cause_or_reject(i, a)
        _, cb = self._cause_or_reject(i, b)
        for cause, other in ((ca, b), (cb, a)):
            related = list(cause.get("related") or [])
            if other not in related:
                related.append(other)
                cause["related"] = related

    def op_add_related(self, i, op):
        self._add_related(i, op["a"], op["b"])

    def _check_code_ref(self, i: int, ref: dict) -> None:
        value = str(ref.get("ref", ""))
        root_key, _, rel = value.partition(":")
        keys = [str(k) for k in self.config.get("code_root_keys") or []]
        if not rel or rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", rel) or root_key not in keys:
            raise Reject("code-ref", f"code_ref는 <root 키>:<상대 경로>이고 root 키는 {keys} 중 하나여야 합니다: "
                         f"{value}", i)

    def op_add_code_ref(self, i, op):
        _, cause = self._cause_or_reject(i, op["cause"])
        self._check_code_ref(i, op["code_ref"])
        refs = list(cause.get("code_refs") or [])
        if op["code_ref"] not in refs:
            refs.append(op["code_ref"])
            cause["code_refs"] = refs
