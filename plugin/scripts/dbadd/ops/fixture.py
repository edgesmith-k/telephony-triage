"""op `add-fixture`·`allow-cause`: fixture 로그(마스킹)와 기대값 파일."""

from __future__ import annotations

import re
from pathlib import Path

from common import logtime, masking, yamldoc, yamlio
from common.fixtures import parse_name

from ..core import FIXTURE_REF_KINDS, Reject

# 줄 머리 시각: logcat(`logtime.STAMP`)과 syslog·journal(M11 호스트 칸 앞 시각)
_LINE_STAMP = re.compile(r"(?m)^(?:" + logtime.STAMP + "|" + "|".join(masking.LINE_STAMPS) + ")")


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
                return src.read_text(encoding="utf-8-sig")     # BOM을 떼야 첫 줄 머리 규칙(syslog 호스트)이 맞는다
        else:
            if (self.plan_dir / src).is_file():
                return (self.plan_dir / src).read_text(encoding="utf-8-sig")
            inside = (self.tree.root / src).resolve()
            root = self.tree.root.resolve()
            if inside != root and root in inside.parents:
                text = self.tree.read(self.tree.root / src)
                if text is not None:
                    return text
        raise Reject("fixture-source", f"fixture 원본이 없습니다: {value}", i)

    def op_add_fixture(self, i, op):
        type_id, name = self.fixture_names[i]
        try:
            text = self._fixture_source(i, op["path"])
        except UnicodeDecodeError:     # 그대로 두면 traceback이다
            raise Reject("fixture-source", f"fixture 원본이 UTF-8 텍스트가 아닙니다: {op['path']} — {masking.NUL_HELP}", i) from None
        if op["kind"] != "negative":
            self._cause_or_reject(i, op["for"])
        lines, nul = masking.blank_nul_lines(text.split("\n"))     # NUL 든 줄은 통째로 비운다(줄 수 그대로)
        total = len(lines) - (lines[-1] == "")
        if nul * 2 > total:     # 절반 넘게 비면(BOM 없는 UTF-16 등) fixture로 쓸모가 없다
            raise Reject("fixture-source", f"fixture 원본 {total}줄 중 {nul}줄에 NUL이 있습니다: {op['path']} — "
                         f"{masking.NUL_HELP}", i)
        if nul:
            self.warnings.append(masking.nul_warning(nul, total, f"add-fixture {op['path']}"))
        text = "\n".join(lines)
        # 커밋 관문(`mask_pii --check`)이 fixtures/*.log에 쓰는 로그 마스커·줄 나눔 그대로(줄 머리 규칙·갈린 덤프 조각)
        masker = masking.new_masker(existing_text=text, allow_patterns=self.allow, log_lines=True)
        masked = "\n".join(masking.mask_lines(masker, text.split("\n")))
        # 그 위에 기본 마스커를 글 전체로 한 번 더: 줄 단위로는 다음 줄로 접힌 SIP Digest `nonce=`·`response=`가 문맥을 못 본다.
        # 줄 머리 시각은 비워 둔다 — 아니면 줄 끝 키(`token:`·`password=`)가 다음 줄 시각을 값으로 잡는다
        masked = masking.new_masker(existing_text=masked, allow_patterns=self.allow).mask(
            masked, reserved=[m.span() for m in _LINE_STAMP.finditer(masked)])
        # 줄 단위로 한 번 더: 앞 패스가 넣은 토큰이 줄을 나눠 덤프 규칙이 새로 맞는다(`rsp: 90 00 01 02 <MSISDN#1>`, 관문이 본다)
        again = masking.new_masker(existing_text=masked, allow_patterns=self.allow, log_lines=True)
        masked = "\n".join(masking.mask_lines(again, masked.split("\n")))
        fdir = self._type_dir_any(type_id) / "fixtures"
        self.tree.write(fdir / name, masked)
        fx = parse_name(name)
        expect = {}
        default = {"positive": "expect_top", "recurrence": "expect_top", "extra": "expect_top",
                   "negative": "expect_top", "fixed": "expect_not", "resolved": "expect_not"}
        for key, value in (op.get("expect") or {}).items():
            if key == "origin":     # 합성 fixture 표시(contracts.md §fixture) — 값은 synthetic만
                if value != "synthetic":
                    raise Reject("fixture-expect", f"expect.origin에는 synthetic만 쓸 수 있습니다: {value}", i)
            elif key not in ("expect_top", "expect_not", "also_allowed"):
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
