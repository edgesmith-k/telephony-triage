"""op `add-fixture`·`allow-cause`: fixture 로그(마스킹)와 기대값 파일."""

from __future__ import annotations

from pathlib import Path

from common import masking, yamldoc, yamlio
from common.fixtures import parse_name

from ..core import FIXTURE_REF_KINDS, Reject


class FixtureOps:

    def _pending_causes(self) -> set[str]:
        return {c["id"] for d in self.tree.docs.values() for c in d.data.get("causes") or []
                if c.get("signatures_pending")}

    def _fixture_source(self, i: int, value: str) -> str:
        """fixture 원본 텍스트. 절대 경로, 계획 디렉토리 기준 상대 경로, 그리고 없으면 **이슈 DB 기준 상대 경로**
        (병합 `move/...` 계획이 옛 원인의 fixture를 새 원인 이름으로 복사할 때, 06-collaboration.md §6.6) 순서로 찾는다.
        이슈 DB 경로는 적용 중인 트리(앞 op의 결과 포함)에서 읽고, 트리 밖을 가리키면 거부한다."""
        src = Path(value)
        if src.is_absolute():
            if src.is_file():
                return src.read_text(encoding="utf-8")
        else:
            if (self.plan_dir / src).is_file():
                return (self.plan_dir / src).read_text(encoding="utf-8")
            inside = (self.tree.root / src).resolve()
            root = self.tree.root.resolve()
            if inside != root and root in inside.parents:
                text = self.tree.read(self.tree.root / src)
                if text is not None:
                    return text
        raise Reject("fixture-source", f"fixture 원본이 없습니다: {value}", i)

    def op_add_fixture(self, i, op):
        type_id, name = self.fixture_names[i]
        text = self._fixture_source(i, op["path"])
        if op["kind"] != "negative":
            self._cause_or_reject(i, op["for"])
        masked = masking.new_masker(existing_text=text, allow_patterns=self.allow).mask(text)
        fdir = self._type_dir_any(type_id) / "fixtures"
        self.tree.write(fdir / name, masked)
        fx = parse_name(name)
        expect = {}
        default = {"positive": "expect_top", "recurrence": "expect_top", "extra": "expect_top",
                   "negative": "expect_top", "fixed": "expect_not", "resolved": "expect_not"}
        for key, value in (op.get("expect") or {}).items():
            if key not in ("expect_top", "expect_not", "also_allowed"):
                raise Reject("fixture-expect", f"expect에 쓸 수 없는 필드: {key}", i)
            expect[key] = value
        if expect:
            base_key = default[fx.kind]
            base_value = "none" if fx.kind == "negative" else fx.cause
            if set(expect) == {base_key} and expect[base_key] == base_value:
                expect = {}
        if op.get("occurred_at"):
            expect["occurred_at"] = op["occurred_at"]
        if expect:
            self.tree.write(fdir / f"{fx.stem}.expect.yaml", yamldoc.dump_doc(expect))

    def op_allow_cause(self, i, op):
        rel = self.fixture_ref(op["fixture"])
        name = rel.split("/", 1)[1] if rel.startswith("fixtures/") else rel
        fx = parse_name(name)
        if fx is None or fx.suffix != ".log":
            raise Reject("allow-cause-fixture", f"fixture 이름이 규칙에 맞지 않습니다: {rel}", i)
        tdir = self._type_dir_any(fx.type_id)
        log = tdir / "fixtures" / name
        if not self.tree.exists(log):
            raise Reject("allow-cause-fixture", f"fixture가 없습니다: {fx.type_id}/fixtures/{name}", i)
        cause = op["cause"]
        self._cause_or_reject(i, cause)
        if cause == fx.cause or cause.rsplit("-", 1)[0] == fx.type_id:
            raise Reject("allow-cause-same", f"also_allowed에는 다른 유형의 원인만 넣을 수 있습니다 ({cause}, fixture "
                         f"{name}). 같은 유형 안의 충돌은 시그니처 설계 문제다.", i)
        expect_path = tdir / "fixtures" / f"{fx.stem}.expect.yaml"
        current = self.tree.read(expect_path)
        data = (yamlio.loads(current) or {}) if current else {}
        pending = self._pending_causes()
        if not data or not ("expect_top" in data or "expect_not" in data):
            if fx.kind not in FIXTURE_REF_KINDS:
                raise Reject("allow-cause-kind", f"also_allowed는 양성·recurrence·extra fixture에만 둡니다: {name}", i)
            top = f"{fx.type_id}:unresolved" if fx.cause in pending else fx.cause
            data = {"expect_top": top, **data}
        top = str(data.get("expect_top") or "")
        if not (fx.kind in FIXTURE_REF_KINDS and top) and not top.endswith(":unresolved"):
            raise Reject("allow-cause-kind", f"also_allowed는 양성·recurrence·extra 또는 unresolved 기대값 fixture에만 "
                         f"둡니다: {name}", i)
        allowed = list(data.get("also_allowed") or [])
        if cause not in allowed:
            allowed.append(cause)
        ordered = {k: data[k] for k in ("expect_top", "expect_not") if k in data}
        ordered["also_allowed"] = allowed
        ordered.update({k: v for k, v in data.items() if k not in ordered})
        self.tree.write(expect_path, yamldoc.dump_doc(ordered))
