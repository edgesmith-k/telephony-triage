"""op `append`·`unresolved`·`reclassify`: Jira 기록 파일."""

from __future__ import annotations

import re

from common import failedstep, masking, yamldoc, yamlio

from ..core import Reject


class JiraOps:

    def _jira_record(self, i: int, cause: str, type_id: str) -> None:
        jira = self.plan.get("jira")
        if not jira:
            raise Reject("jira-missing", "계획에 jira가 없습니다 (append·unresolved에는 필요).", i)
        key = jira["key"]
        if not self.key_re.fullmatch(key):
            raise Reject("jira-key", f"Jira 키 {key}가 jira_key_regex에 맞지 않습니다.", i)
        existing = self.tree.jira_files().get(key)
        if existing is not None:
            record = yamlio.loads(self.tree.read(existing) or "") or {}
            raise Reject("jira-exists", f"Jira {key}가 이미 이슈 DB에 있습니다 ({self.tree.rel(existing)}). "
                         "기존 분류를 유지하거나 reclassify로 바꾼다.", i,
                         existing={"path": self.tree.rel(existing), "cause": record.get("cause")})
        missing = [f for f in ("date", "model", "sw", "android_version") if not jira.get(f)]
        if missing:
            raise Reject("jira-fields", f"Jira 기록 필수 필드가 없습니다: {', '.join(missing)}", i)
        record = {"key": key, "cause": cause, "date": jira["date"]}
        if jira.get("occurred_on"):
            record["occurred_on"] = jira["occurred_on"]
        record.update(model=jira["model"], sw=jira["sw"], android_version=str(jira["android_version"]))
        if jira.get("carrier"):
            record["carrier"] = jira["carrier"]
        record["analyzed_by"] = self.user
        if jira.get("failed_step"):    # 선택 값. 마스킹은 멱등이므로 다시 거친다
            step = failedstep.normalize(masking.new_masker(allow_patterns=self.allow).mask(str(jira["failed_step"])))
            if step:
                record["failed_step"] = step
        if jira.get("note"):
            record["note"] = masking.new_masker(allow_patterns=self.allow).mask(str(jira["note"]))
        path = self.tree.type_dir(type_id) / "jira" / f"{key}.yaml"
        self.tree.write(path, yamldoc.dump_doc(record))

    def op_append(self, i, op):
        doc, cause = self.tree.cause(op["cause"])
        if cause is None:
            raise Reject("unknown-cause", f"원인 {op['cause']}가 없습니다.", i)
        self._jira_record(i, op["cause"], doc.id)

    def op_unresolved(self, i, op):
        if op["type"] not in self.tree.docs:
            raise Reject("unknown-type", f"유형 {op['type']}가 없습니다.", i)
        self._jira_record(i, "unresolved", op["type"])

    def op_reclassify(self, i, op):
        key = op["jira"]
        path = self.tree.base_jira.get(key)
        if path is None or not self.tree.exists(path):
            raise Reject("reclassify-missing", f"Jira {key}가 기준 트리(main)에 없습니다. reclassify는 main에 있는 "
                         "Jira만 옮길 수 있다 (새 Jira는 append·unresolved).", i)
        record = yamlio.loads(self.tree.read(path)) or {}
        if str(record.get("cause")) != op["from"]:
            raise Reject("reclassify-from", f"Jira {key}의 현재 원인은 {record.get('cause')}입니다 (계획 from: "
                         f"{op['from']}).", i, current=record.get("cause"))
        to = op["to"]
        if to.endswith(":unresolved"):
            # 원인 미확정 Jira를 다른 유형으로 옮긴다 (유형 병합, 06-collaboration.md §6.6)
            type_id = to.split(":", 1)[0]
            doc = self.tree.docs.get(type_id)
            if doc is None:
                raise Reject("unknown-type", f"유형 {type_id}가 없습니다.", i)
            if op["from"] != "unresolved":
                raise Reject("reclassify-unresolved", f"`{to}`로는 원인 미확정 Jira만 옮길 수 있습니다 "
                             f"(from: {op['from']}).", i)
            new_cause = "unresolved"
        else:
            doc, cause = self.tree.cause(to)
            if cause is None:
                raise Reject("unknown-cause", f"원인 {to}가 없습니다.", i)
            new_cause = to
        record["cause"] = new_cause
        origin = op["from"]
        if origin == "unresolved":
            old_type = re.match(r"[A-Z][A-Z0-9]*-\d{3}", path.parent.parent.name)
            if old_type and old_type.group(0) != doc.id:
                origin = f"{old_type.group(0)}:unresolved"
        note = f"reclassified from {origin}"
        record["note"] = f"{record['note']}; {note}" if record.get("note") else note
        dest = self.tree.type_dir(doc.id) / "jira" / f"{key}.yaml"
        if dest != path:
            self.tree.delete(path)
        self.tree.write(dest, yamldoc.dump_doc(record))
