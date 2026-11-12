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

import platforms  # noqa: E402
from common import skillcheck, yamlio  # noqa: E402

ANDROID = REPO / "templates" / "module-skills" / "android"
MODULES = ("data", "sim", "network", "call", "sms", "ims", "modem")

# 설계 D §1 표 순서 = 키 MOCK-9801…9815(R14). (모듈, 이름, kind, 함정) — case는 모두 합성
CASES = [
    ("data", "data-disabled-user", "deep", None),
    ("data", "data-cfun-radio-off", "explore", None),
    ("data", "data-profile-ipc-swallowed", "explore", None),
    ("sim", "sim-card-io-error", "deep", None),
    ("sim", "sim-optional-ef-benign", "explore", None),
    ("network", "network-reg-reject", "deep", None),
    ("network", "network-radio-buffer-late", "explore", "below-layer-missing"),
    ("call", "call-volte-ims-unregistered", "deep", None),
    ("call", "call-cf-ut-no-rilj", "explore", None),
    ("sms", "sms-smsc-missing", "deep", None),
    ("sms", "sms-ims-local-reject", "explore", None),
    ("ims", "ims-reg-403", "deep", None),
    ("ims", "ims-iradioims-absent", "explore", None),
    ("modem", "modem-restart-chain", "deep", None),
    ("modem", "modem-vendor-lines-missing", "explore", "below-layer-missing"),
    ("data", "data-apn-wrong-applied", "explore", None),
    ("data", "data-dc-list-drop", "explore", None),
    ("call", "call-volte-sip-invite-error", "explore", None),
    ("sim", "sim-slow-recognition", "explore", None),
    ("modem", "modem-ril-daemon-crash", "explore", None),
    ("ims", "ims-403-vendor-lines-missing", "deep", None),
    ("sms", "sms-mt-delivered-to-app", "explore", None),
    ("call", "call-mo-out-of-service", "explore", None),
    ("sim", "sim-apps-disabled-by-request", "explore", None),
    ("modem", "modem-radio-off-airplane", "explore", None),
    ("network", "network-oos-recover-no-reject", "explore", None),
]

# 문서 상한(바이트, C1D 보정 §2.2) — skillcheck.CAPS보다 좁다(R24). 경로 키가 파일 이름 키보다 먼저.
# explore.md는 5행 계약 문구(`가설 N:`부터, 코덱스 리뷰 02e0ec2 F05)로 +66B라 100씩 올렸다
DOC_CAPS = {"layers.md": 2900, "components.md": 3300, "SKILL.md": 2000, "analyzer.md": 1150, "explore.md": 2700,
            "modem/SKILL.md": 1024, "data/explore.md": 2900}
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
    for i, (module, name, kind, trap) in enumerate(CASES, 1):
        data = yamlio.load(ANDROID / module / "evals" / name / "case.yaml")
        assert data["name"] == name and data["kind"] == kind, name
        assert data["key"] == f"MOCK-98{i:02d}", name
        assert data["synthetic"] is True and "origin" not in data, name
        if kind == "deep":
            assert data["expect"]["trap"] == trap, name
        else:   # explore schema 2: trap은 함정 목록, below-layer-missing은 accept 층 `그 층 로그 없음`으로 옮겨졌다(설계 §2.3)
            assert data["schema_version"] == 2 and isinstance(data["expect"]["trap"], list), name
            below = all(re.search(r"그\\s\*층", a["layer"]) for a in data["expect"]["accept"])
            assert below is (trap == "below-layer-missing"), name
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


def test_explore_points_to_reference_contract():
    """explore 답의 형식은 reference/explore.md 계약(`가설 N:`부터)이다 — analyzer 칸(`원인 층:`부터)이라고 쓰지 않는다
    (코덱스 리뷰 02e0ec2 F05). 모든 플랫폼의 explore.md를 본다."""
    docs = sorted(ANDROID.parent.glob("*/*/explore.md"))
    assert {p.parent.name for p in docs if p.parent.parent == ANDROID} == set(MODULES)
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "원인 층:`부터" not in text, path
        if path.parent.parent == ANDROID:
            assert "reference/explore.md 계약" in text, path


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
    findings = [f for f in skillcheck.template_findings(REPO / "templates" / "module-skills", platforms.template_metas())
                if f.get("check") == "플랫폼 섞임" and str(f.get("path", "")).startswith("android/")]
    assert findings == []
    for path in _docs():          # template_findings와 같은 목록을 직접 한 번 더(빈 결과가 점검 누락이 아니게)
        assert not platforms.get("ofono").template.names.search(path.read_text(encoding="utf-8")), path
