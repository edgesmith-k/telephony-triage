"""5-2 모듈 고르기(`triagelib/modulecmd.py` rank·ask_text·_hints, B2 §5.3 E5–E8, §12.2).

후보 줄 수(modulefilter 결과)는 손으로 준다 — 이 파일은 순위·힌트·질문 문구만 본다. 비용이 드는 호출은 없다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import plugin_root  # noqa: E402

sys.path.insert(0, str(plugin_root() / "scripts"))
from triagelib import modulecmd  # noqa: E402

_spec = importlib.util.spec_from_file_location("tt_grade_for_choice", REPO / "tests" / "skill_evals" / "grade.py")
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

ORDER = ["data", "sim", "network", "call", "modem"]
TREE = frozenset(f"ofono/{d}/explore.md" for d in ("data", "sim", "network", "modem"))
BY_CAT = {"data": "data", "sim": "sim", "network": "network", "call": "call", "common": "modem"}


def counts(**lines) -> dict:
    return {d: {"lines": n, "why": [[f"tag:T{d}", n]]} for d, n in lines.items()}


def test_rank_by_lines_then_hint_then_order():
    got, missing = modulecmd.rank(counts(sim=4, data=4, network=9), [("sim", "요약 유형 SIM-001")], ORDER, TREE, "ofono")
    assert [c["module"] for c in got] == ["ofono/network", "ofono/sim", "ofono/data"]
    assert got[1]["hint"] and got[1]["why"] == ["Tsim 4줄", "요약 유형 SIM-001"] and missing == []


def test_rank_ties_follow_modules_yaml_order_every_run():
    first = modulecmd.rank(counts(network=2, data=2, sim=2), [], ORDER, TREE, "ofono")
    for _ in range(5):
        assert modulecmd.rank(counts(sim=2, network=2, data=2), [], ORDER, TREE, "ofono") == first
    assert [c["module"] for c in first[0]] == ["ofono/data", "ofono/sim", "ofono/network"]


def test_hint_takes_third_slot():
    got, _ = modulecmd.rank(counts(data=9, sim=8, network=7), [("modem", "실패 스텝 유형 MODEM-001")], ORDER, TREE, "ofono")
    assert [c["module"] for c in got] == ["ofono/data", "ofono/sim", "ofono/modem"]
    assert got[2]["lines"] == 0 and got[2]["why"] == ["실패 스텝 유형 MODEM-001"]


def test_missing_docs_listed_not_offered():
    got, missing = modulecmd.rank(counts(call=5, data=1), [], ORDER, TREE, "ofono")
    assert [c["module"] for c in got] == ["ofono/data"] and missing == ["ofono/call"]


def test_odd_names_become_other_tag():
    got, _ = modulecmd.rank({"data": {"lines": 3, "why": [["tag:a b<c>", 2], ["ril:SETUP_DATA_CALL", 1],
                                                          ["file:src/gprs.c", 1]]}}, [], ORDER, TREE, "ofono")
    assert got[0]["why"] == ["기타 태그 2줄", "RIL SETUP_DATA_CALL 1줄", "ofonod src/gprs.c 1줄"]


def _job(tmp_path: Path, analysis: dict, match: dict | None = None) -> Path:
    if match is not None:
        (tmp_path / "match.json").write_text(json.dumps(match), encoding="utf-8")
    return tmp_path


def test_every_hint_source(tmp_path):
    analysis = {"candidates": [{"type": "SIM-002", "category": "sim"}], "explore": {"reason": "cause_unconfirmed"},
                "no_candidate": {"search_hits": [{"id": "NETWORK-003-02", "kind": "cause"}, {"id": "DATA-001", "kind": "type"},
                                                 {"id": "MOCK-1", "kind": "issue"}]}}
    job = _job(tmp_path, analysis, {"step_focus": {"types": ["CALL-001"]}})
    hints, unmapped = modulecmd._hints(job, {"work_dir": str(tmp_path)}, analysis, BY_CAT)
    assert hints == [("sim", "1위 유형 SIM-002(원인 미확인)"), ("call", "실패 스텝 유형 CALL-001"),
                     ("network", "요약 유형 NETWORK-003"), ("data", "요약 유형 DATA-001")]
    assert unmapped == []


def test_hint_prefix_paths(tmp_path):
    snap = tmp_path / "_snapshot"
    snap.mkdir()
    (snap / "issue-db.config.yaml").write_text("categories:\n  - {key: data, id_prefix: PDN}\n", encoding="utf-8")
    analysis = {"candidates": [{"type": "X-001", "category": "sim"}], "snapshot": {"sha": "x"},
                "no_candidate": {"search_hits": [{"id": "X-001", "kind": "type"}, {"id": "PDN-002", "kind": "type"},
                                                 {"id": "SIM-003", "kind": "type"}, {"id": "IMS-004", "kind": "type"},
                                                 {"id": "WEIRD-005", "kind": "type"}, {"id": "ODD-006", "kind": "type"},
                                                 {"id": "ZZ-007", "kind": "type"}]}}
    hints, unmapped = modulecmd._hints(tmp_path, {"work_dir": str(tmp_path)}, analysis, BY_CAT)
    assert hints == [("sim", "요약 유형 X-001"), ("data", "요약 유형 PDN-002"), ("sim", "요약 유형 SIM-003")]
    assert unmapped == ["IMS-004", "WEIRD-005", "ODD-006"]          # ≤ 3


def test_no_snapshot_no_prefix_table(tmp_path):
    snap = tmp_path / "_snapshot"
    snap.mkdir()
    (snap / "issue-db.config.yaml").write_text("categories:\n  - {key: data, id_prefix: PDN}\n", encoding="utf-8")
    analysis = {"no_candidate": {"search_hits": [{"id": "PDN-002", "kind": "type"}]}}
    assert modulecmd._hints(tmp_path, {"work_dir": str(tmp_path)}, analysis, BY_CAT) == ([], ["PDN-002"])


QUESTIONS = [
    [{"module": "ofono/data", "lines": 12, "why": [], "hint": True}, {"module": "ofono/network", "lines": 7, "why": [],
                                                                       "hint": False}],
    [{"module": "ofono/sim", "lines": 1, "why": [], "hint": False}, {"module": "ofono/modem", "lines": 0, "why": [],
                                                                      "hint": True},
     {"module": "ofono/call", "lines": 3, "why": [], "hint": False}],
]


@pytest.mark.parametrize("cands", QUESTIONS)
def test_questions_are_not_5x_questions(cands):
    ask = modulecmd.ask_text(cands)
    switch = modulecmd._ask_switch("data", {"hot_modules": {"network": 5, "sim": 2}}, cands)
    texts = [ask["question"], *ask["options"], switch["question"], *switch["options"]]
    assert len(ask["options"]) <= 3
    for text in texts:
        assert not modulecmd.FORBIDDEN_ASK.search(text), text
        assert not grade.is_question(text, r"탐색 분석|explore|심층 분석"), text
    assert ask["question"].startswith("어느 모듈 문서로 볼까요? (모듈 신호 줄 수: ")
    assert ask["options"][0].endswith(" (요약과 맞음)") == cands[0]["hint"]
