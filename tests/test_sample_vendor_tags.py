#!/usr/bin/env python3
"""샘플 DB의 벤더 RIL 태그 묶음(사내 확인 전) (결정 기록 11/05 ①·②, 설계 D §3.1).

- 기존 정규식이 덮지 않는 승인 태그(보류였던 `^GsmCdmaCallTracker$`는 11/05 ① 승인대로 C1+D 보정에서 넣음, 벤더 태그는
  placeholder `VRIL*`)가 정해진 카테고리로 있고, 표식 주석 아래 파일 끝에 있다. 미수집 태그 예시(eval e004·`test_triage`)는
  `GsmCdmaConnection`이며 샘플 tags.yaml 어느 항목에도 걸리지 않는다.
- `ril.yaml` unsolicited에 `UNSOL_DATA_CALL_LIST_UPDATED`(data)가 있다.
- Android 모듈 템플릿 case 로그와 `tests/fixtures/module-filter/a-e*` 로그의 어떤 태그도
  카테고리가 다른 두 항목에 함께 걸리지 않는다.
- `issue-db-android-plain` 변형(make_variant_dbs)에는 이 묶음이 없다 — 변형이 아직 없으면 건너뛴다.

`pytest tests/test_sample_vendor_tags.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_variant_dbs  # noqa: E402
from common import parser_rules  # noqa: E402
from platforms.android import logcat  # noqa: E402

SAMPLE_RULES = REPO / "tests" / "fixtures" / "issue-db-sample" / "parser-rules"
MARKER = make_variant_dbs.ANDROID_VENDOR_BLOCK
PLAIN = "issue-db-android-plain"

APPROVED = {
    "common": [r"^(RIL|VRIL|VRIL-SVC)$", r"^RilRequest$", r"^VRIL-MODEM$",
               r"^SCED$", r"^OemRil", r"^PhoneCfgMgr$", r"^RadioConfig$", r"^RadioConfigResponseAidl$"],
    "data": [r"^ADSC$", r"^ANM-\d+$", r"^ConnectivityService$", r"^DataServiceCallback$", r"^PhoneSwitcher$",
             r"^QOSCT-\d+$", r"^TNA-\d+$", r"^TNP$", r"^VRIL-DATA$"],
    "sim": [r"^CAT$", r"^IsimUiccRecords$", r"^MultiSimSettingController$", r"^SIMRecords$",
            r"^SecureElement-Terminal-SIM\d$", r"^UiccCard$", r"^UiccCardApplication( \[\d+\])?$",
            r"^UiccHal-(SE|Interface)$", r"^UiccProfile( \[\d+\])?$", r"^UiccSlot$", r"^UsimFH$"],
    "network": [r"^CSST$", r"^CellularNetworkService$", r"^DIC-\d+$", r"^ExSST$", r"^LocaleTracker-\d+$",
                r"^NRM-[CI]-\d+$", r"^NetworkTypeController$", r"^NitzStateMachineImpl$", r"^VRIL-NETWORK$"],
    "call": [r"^GsmCdmaCallTracker$", r"^CallManager$", r"^CallNotifier$", r"^CallWaitingCtrl$", r"^ImsUt$",
             r"^MMIDialogActivity$", r"^Telecom$"],
    "sms": [r"^CellBroadcastConfigTracker-\d+$", r"^ImsSmsDispatcher( \[\d+\])?$", r"^SMSDispatcher$"],
    "ims": [r"^ImsConfig$", r"^ImsEnablementTracker$", r"^ImsProvisioning", r"^ImsRIL$", r"^ImsRegCallbackHelper$",
            r"^ImsStateCallbackController$", r"^ImsStats$", r"^VRIL-IMS$"],
}
APPROVED_UNSOL = ("UNSOL_DATA_CALL_LIST_UPDATED", "data")
UNCOLLECTED_EXAMPLE = "GsmCdmaConnection"  # e004·test_triage·test_parse_logcat의 미수집 태그 예 — 샘플에 없어야 한다


def _entries(rules_dir: Path) -> list[dict]:
    return yaml.safe_load((rules_dir / "tags.yaml").read_text(encoding="utf-8"))["tags"]


def _unsol(rules_dir: Path) -> dict[str, str]:
    data = yaml.safe_load((rules_dir / "ril.yaml").read_text(encoding="utf-8"))
    return {u["name"]: u["category"] for u in data.get("unsolicited") or []}


def _log_tags() -> set[str]:
    paths = sorted((REPO / "templates" / "module-skills" / "android").glob("*/evals/*/files/source.log"))
    paths += sorted((REPO / "tests" / "fixtures" / "module-filter").glob("a-e*/source.log"))
    tags: set[str] = set()
    for i, path in enumerate(paths):
        lines, _ = logcat.read_file(path, i, "UTC", 2026)
        tags.update(line.tag for line in lines)
    return tags


def test_approved_block_present() -> None:
    assert sum(len(v) for v in APPROVED.values()) == 55
    have = {e.get("tag_regex") or e.get("tag"): e for e in _entries(SAMPLE_RULES)}
    for category, regexes in APPROVED.items():
        for rx in regexes:
            assert rx in have, rx
            assert have[rx]["category"] == category, rx
            assert have[rx]["added_for"] == "-" and str(have[rx]["reason"]).startswith("사내 확인 전"), rx
    rules = parser_rules.load(SAMPLE_RULES)
    assert rules.tag_category(UNCOLLECTED_EXAMPLE) is None
    assert not rules.declares("level") and not rules.declares("ipc")   # 샘플은 태그 속성을 선언하지 않는다(C-F2)
    assert _unsol(SAMPLE_RULES).get(APPROVED_UNSOL[0]) == APPROVED_UNSOL[1]
    parser_rules.load(SAMPLE_RULES)  # 스키마·키 중복·정규식 검사


def test_block_is_last() -> None:
    text = (SAMPLE_RULES / "tags.yaml").read_text(encoding="utf-8")
    assert text.count(MARKER) == 1
    tail = text[text.index(MARKER):]
    approved = {rx for v in APPROVED.values() for rx in v}
    tail_regexes = set(re.findall(r"tag_regex: '([^']+)'", tail))
    assert tail_regexes == approved
    assert "tag:" not in tail.replace("tag_regex:", "")


def test_no_cross_category_collision() -> None:
    entries = _entries(SAMPLE_RULES)
    tags = _log_tags()
    assert tags, "Android 로그 태그가 없습니다"
    bad = {}
    for tag in sorted(tags):
        cats = set()
        for e in entries:
            if e.get("tag") is not None:
                hit = e["tag"] == tag
            else:
                hit = bool(re.search(e["tag_regex"], tag))
            if hit:
                cats.add(e["category"])
        if len(cats) > 1:
            bad[tag] = sorted(cats)
    assert not bad, bad


@pytest.mark.skipif(PLAIN not in make_variant_dbs.VARIANTS, reason=f"{PLAIN} 변형이 아직 없다(infra-1)")
def test_plain_variant_has_none() -> None:
    from runner import variant_db

    plain = variant_db(PLAIN) / "parser-rules"
    have = {e.get("tag_regex") or e.get("tag") for e in _entries(plain)}
    approved = {rx for v in APPROVED.values() for rx in v}
    assert not (have & approved)
    assert MARKER not in (plain / "tags.yaml").read_text(encoding="utf-8")
    assert APPROVED_UNSOL[0] not in _unsol(plain)
    base = {e.get("tag_regex") or e.get("tag") for e in _entries(SAMPLE_RULES)}
    assert have == base - approved


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
