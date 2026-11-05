"""Android 모듈 스킬 템플릿(`templates/module-skills/android/`): case 15개·문서 상한·analyzer 동일·플랫폼 섞임.

H C1+D 설계 D §1·§2.0·§2.3·§4.5, 계획 R14·R21·R23·R24. 두 플랫폼 공통 시험(지위 문장·출처·크기·생성기 drift)은
`tests/test_module_templates.py`가 맡는다. 비용이 드는 호출은 없다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "plugin" / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import skillcheck, yamlio  # noqa: E402

ANDROID = REPO / "templates" / "module-skills" / "android"
MODULES = ("data", "sim", "network", "call", "sms", "ims", "modem")

# 설계 D §1 표 순서 = 키 MOCK-9801…9815(R14). (모듈, 이름, kind, 마스킹 발췌?, 함정)
CASES = [
    ("data", "data-disabled-user", "deep", False, None),
    ("data", "data-cfun-radio-off", "explore", True, None),
    ("data", "data-profile-ipc-swallowed", "explore", True, None),
    ("sim", "sim-card-io-error", "deep", False, None),
    ("sim", "sim-optional-ef-benign", "explore", True, None),
    ("network", "network-reg-reject", "deep", False, None),
    ("network", "network-radio-buffer-late", "explore", True, "below-layer-missing"),
    ("call", "call-volte-ims-unregistered", "deep", False, None),
    ("call", "call-cf-ut-no-rilj", "explore", True, None),
    ("sms", "sms-smsc-missing", "deep", False, None),
    ("sms", "sms-ims-local-reject", "explore", False, None),
    ("ims", "ims-reg-403", "deep", False, None),
    ("ims", "ims-iradioims-absent", "explore", True, None),
    ("modem", "modem-restart-chain", "deep", False, None),
    ("modem", "modem-vendor-lines-missing", "explore", False, "below-layer-missing"),
]

# 문서 상한(바이트, C1D 보정 §2.2) — skillcheck.CAPS보다 좁다(R24). 경로 키가 파일 이름 키보다 먼저
DOC_CAPS = {"layers.md": 2900, "components.md": 3300, "SKILL.md": 2000, "analyzer.md": 1150, "explore.md": 2600,
            "modem/SKILL.md": 1024, "data/explore.md": 2800}
REFERENCE_CAP = 1300
# run별 with arm 문서 합 = 그 run이 읽는 파일 상한의 합(C1D 보정 §2.3)
COMMON_BUDGET, DEEP_RUN_BUDGET, ALSO_RUN_BUDGET, EXPLORE_RUN_BUDGET = 6000, 10450, 11474, 8800
# 모듈마다 references(모뎀은 없음 — deep은 증상 모듈 + also)
REFERENCES = {"data": "DATA-001", "sim": "SIM-001", "network": "NETWORK-001", "call": "CALL-001", "sms": "SMS-001",
              "ims": "IMS-001"}
LAYER_NAMES = ("프레임워크", "RILJ", "RIL HAL", "벤더 RIL", "벤더 IMS", "모뎀·망", "곁가지(<태그>)", "그 층 로그 없음(<층>)",
               "원인 아님(정상 동작)")


def _docs() -> list[Path]:
    return sorted(p for p in ANDROID.rglob("*.md") if "evals" not in p.relative_to(ANDROID).parts)


def test_android_cases_present():
    found = sorted(p.parent for p in ANDROID.glob("*/evals/*/case.yaml"))
    assert {(p.parent.parent.name, p.name) for p in found} == {(m, n) for m, n, *_ in CASES}
    for i, (module, name, kind, excerpt, trap) in enumerate(CASES, 1):
        data = yamlio.load(ANDROID / module / "evals" / name / "case.yaml")
        assert data["name"] == name and data["kind"] == kind, name
        assert data["key"] == f"MOCK-98{i:02d}", name
        assert data["synthetic"] is (not excerpt), name
        assert ("origin" in data) is excerpt, name
        if excerpt:
            assert data["origin"]["log"] == "A" and data["origin"]["kind"] == "masked-excerpt", name
        assert data["expect"]["trap"] == trap, name
    for module in MODULES:
        kinds = {k for m, _, k, *_ in CASES if m == module}
        assert kinds == {"deep", "explore"}, module
    assert sum(1 for *_, trap in CASES if trap) >= 1


def test_android_doc_caps():
    seen = set()
    for path in _docs():
        rel = path.relative_to(ANDROID)
        cap = REFERENCE_CAP if path.parent.name == "references" else DOC_CAPS.get(rel.as_posix(), DOC_CAPS.get(path.name))
        assert path.stat().st_size <= cap, (rel.as_posix(), path.stat().st_size, cap)
        seen.add(rel.as_posix())
    want = {"_common/layers.md", "_common/components.md"}
    for module in MODULES:
        want |= {f"{module}/{n}" for n in ("SKILL.md", "analyzer.md", "explore.md")}
    want |= {f"{m}/references/{t}.md" for m, t in REFERENCES.items()}
    assert seen == want


def test_android_analyzer_identical():
    bodies = {}
    for module in MODULES:
        text = (ANDROID / module / "analyzer.md").read_text(encoding="utf-8")
        first, body = text.split("\n", 1)
        assert first == f"# Android {module} — 출력 칸", module
        bodies[module] = body
    assert len(set(bodies.values())) == 1
    block = bodies["data"].split("```", 2)[1]
    assert [m.group(1) for m in re.finditer(r"(?m)^([^\s:-][^:\n]*?):", block)] == [
        "원인 층", "원인 데몬", "근거", "반대 근거", "분석 스킬 의견", "규칙 제안"]
    layer_line = next(ln for ln in block.splitlines() if ln.startswith("원인 층:"))
    for name in LAYER_NAMES:
        assert name in layer_line, name


def test_android_run_budgets():
    """한 run의 with arm 문서 합(oFono test_doc_budgets와 같은 모양). also = 증상 모듈 deep + 모뎀 SKILL의 최댓값."""
    common = sum((ANDROID / "_common" / n).stat().st_size for n in ("layers.md", "components.md"))
    assert common <= COMMON_BUDGET, common
    modem_skill = (ANDROID / "modem" / "SKILL.md").stat().st_size
    for module in MODULES:
        refs = [p.stat().st_size for p in (ANDROID / module / "references").glob("*.md")]
        deep = common + sum((ANDROID / module / n).stat().st_size for n in ("SKILL.md", "analyzer.md")) + max(refs, default=0)
        assert deep <= DEEP_RUN_BUDGET, (module, deep)
        if module != "modem":
            assert deep + modem_skill <= ALSO_RUN_BUDGET, (module, deep + modem_skill)
        assert common + (ANDROID / module / "explore.md").stat().st_size <= EXPLORE_RUN_BUDGET, module


def test_android_layers_and_skill_frontmatter():
    layers = (ANDROID / "_common" / "layers.md").read_text(encoding="utf-8")
    for name in LAYER_NAMES:
        assert f"`{name}`" in layers, name
    for module in MODULES:
        text = (ANDROID / module / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
        assert m and m.group(1).splitlines() == [
            f"name: android-{module}", "description: telephony-triage Step 5-1에서 triage.py module 출력으로만 읽는다"]


def test_android_no_ofono_names():
    findings = [f for f in skillcheck.template_findings(REPO / "templates" / "module-skills")
                if f.get("check") == "플랫폼 섞임" and str(f.get("path", "")).startswith("android/")]
    assert findings == []
    for path in _docs():          # template_findings와 같은 목록을 직접 한 번 더(빈 결과가 점검 누락이 아니게)
        assert not skillcheck.OFONO_NAMES.search(path.read_text(encoding="utf-8")), path
