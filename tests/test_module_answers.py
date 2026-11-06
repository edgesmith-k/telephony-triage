"""tools/module_answers.py — 정답표(인정 후보 / 함정)와 explore expect schema 2 변환 (모듈 eval explore 후보 설계 §2.3·§5)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tools"))

import module_answers as ma  # noqa: E402
import module_eval as me  # noqa: E402

OLD_EXPLORE = {"layer": "곁가지|DITD|라우팅", "daemon": "DITD", "evidence": ["RTM_NEWROUTE failed"], "trap": None,
               "wrong_layer": [r"^\s*(벤더 RIL|exynos-ril|모뎀|망|ofonod|D-Bus|관리 데몬|NMD)", r"^\s*그\s*층\s*로그\s*없음"]}
OLD_BELOW = {"layer": r"그\s*층\s*로그\s*없음", "daemon": "알 수 없음|ofonod|없음", "evidence": ["Activating context failed"],
             "trap": "below-layer-missing", "wrong_layer": [r"^\s*(벤더 RIL|exynos-ril|모뎀|망|DITD|NMD)"]}
DEEP = {"layer": "벤더 RIL|exynos-ril|모뎀|망", "daemon": "exynos-ril", "evidence": ["SETUP_DATA_CALL failed", "USER_AUTHENTICATION"],
        "trap": None, "wrong_layer": [r"^\s*(ofonod|NMD|관리 데몬|D-Bus|MOSE|DITD)", r"^\s*그\s*층\s*로그\s*없음"]}


def _case(name, kind, expect, summary="데이터가 연결되지 않음 (합성)"):
    return me.Case(name, kind, Path("."), "MOCK-9000", {"summary": summary}, {}, {}, {}, expect)


def test_unfold():
    assert ma.unfold(r"^\s*(벤더 RIL|exynos-ril|모뎀)") == "벤더 RIL 또는 exynos-ril 또는 모뎀"
    assert ma.unfold(r"그\s*층\s*로그\s*없음") == "그 층 로그 없음"
    assert ma.unfold(r"곁가지\(DITD\)$") == "곁가지(DITD)"
    assert ma.unfold(r"(?:a|b)\s+c") == "(a 또는 b) c"
    assert ma.unfold(r"(a)|(b)") == "(a) 또는 (b)"            # 바깥 괄호가 하나로 감싸지 않으면 그대로


def test_table_golden():
    explore = _case("data-ditd-route-fail", "explore", ma.migrate_expect(OLD_EXPLORE))
    explore.expect["accept"][0]["show"] = "곁가지(DITD) — 라우팅 실패"
    below = _case("data-ofonod-only", "explore", ma.migrate_expect(OLD_BELOW), summary="a|b")
    deep = _case("data-apn-auth-reject", "deep", DEEP)
    results = {"modules": {"ofono/data": {"cases": {
        "data-ditd-route-fail": {"with": {"top1": True}, "without": [{"top1": False}, {"top1": True}]},
        "data-apn-auth-reject": {"with": {"top1": None}, "without": {"top1": None}}}}}}
    lines = ma.table_lines([("ofono/data", [deep, explore, below], ["x: 오류"])], results)
    assert lines[:4] == ["# 모듈 eval 정답표 — 인정 후보 / 함정", "", ma.HEAD, ""]
    assert lines[4:9] == ["## ofono/data", "", "오류: x: 오류", "",
                          "| case | 종류 | 증상 | 인정 후보 (층 / 데몬 · 근거) | 함정 (가장 유력이면 실패) | top1 |"]
    assert lines[10] == ("| data-apn-auth-reject | deep(결론 1개) | 데이터가 연결되지 않음 (합성) | 벤더 RIL 또는 exynos-ril 또는 "
                         "모뎀 또는 망 / exynos-ril · `SETUP_DATA_CALL failed`, `USER_AUTHENTICATION` | ofonod 또는 NMD 또는 "
                         "관리 데몬 또는 D-Bus 또는 MOSE 또는 DITD / 그 층 로그 없음 | - |")
    assert lines[11] == ("| data-ditd-route-fail | explore | 데이터가 연결되지 않음 (합성) | ① 곁가지(DITD) — 라우팅 실패 · "
                         "`RTM_NEWROUTE failed` | 벤더 RIL 또는 exynos-ril 또는 모뎀 또는 망 또는 ofonod 또는 D-Bus 또는 "
                         "관리 데몬 또는 NMD / 그 층 로그 없음 | with 1/1 · without 1/2 |")
    assert lines[12] == ("| data-ofonod-only | explore | a\\|b | ① 그 층 로그 없음 / 알 수 없음 또는 ofonod 또는 없음 · "
                         "`Activating context failed` (흔한 덧붙임 후보 — top1 확인) | 벤더 RIL 또는 exynos-ril 또는 모뎀 "
                         "또는 망 또는 DITD 또는 NMD | - |")
    assert lines[-1] == ""


def test_common_addon_mark():
    assert ma.is_common_addon({"layer": r"그\s*층\s*로그\s*없음"}) and ma.is_common_addon({"layer": "원인 아님|정상"})
    assert not ma.is_common_addon({"layer": "곁가지|DITD"})


ANSWERS = [  # (원인 층, 원인 데몬, 근거)
    ("곁가지(DITD) — 라우팅", "DITD", ["netlink RTM_NEWROUTE failed: err=-17"]),
    ("벤더 RIL(exynos-ril) — x", "exynos-ril", ["SETUP_DATA_CALL rsp: ok"]),
    ("관리 데몬 — x", "NMD", ["connectivity check failed"]),
    ("곁가지(DITD) — x", "NMD", ["netlink RTM_NEWROUTE failed"]),
    ("그 층 로그 없음(RIL trace) — x", "알 수 없음", ["Activating context failed with error"]),
    ("그 층 로그 없음(RIL trace)", "exynos-ril", ["Activating context failed"]),
    ("ofonod — x", "ofonod", ["Activating context failed"]),
    ("곁가지(MOSE)", "MOSE", ["x"]),
]


def _old_verdict(exp, layer, daemon, evidence):
    lay, dae = me.label(layer), me.label(daemon)
    ok = (re.match(r"\s*(?:" + exp["layer"] + ")", lay) is not None and re.match(r"\s*(?:" + exp["daemon"] + ")", dae) is not None
          and all(re.search(e, "\n".join(evidence)) for e in exp["evidence"]))
    wrong = any(re.search(w, lay) or re.search(w, dae) for w in exp["wrong_layer"])
    return ok, wrong


@pytest.mark.parametrize("old", [OLD_EXPLORE, OLD_BELOW])
def test_migrate_judgment_equals_old(old):
    new = ma.migrate_expect(old)
    assert new["accept"] == [{k: old[k] for k in ("layer", "daemon", "evidence")}]
    for layer, daemon, evidence in ANSWERS:
        cand = {"원인 층": layer, "원인 데몬": daemon, "근거": evidence}
        ok_new = any(me._accept_hit(a, cand) and me._evidence_hit(a, cand) for a in new["accept"])
        wrong_new = any(me.trap_hit(t, cand) for t in new["trap"])
        assert (ok_new, wrong_new) == _old_verdict(old, layer, daemon, evidence), (layer, daemon)


CASE_YAML = """# 합성 case 머리 주석
schema_version: 1
name: data-ditd-route-fail
kind: explore
run_expect:
  explore_reason: no_candidate
expect:
  layer: '곁가지|DITD|라우팅'
  daemon: 'DITD'
  evidence: ['RTM_NEWROUTE failed']
  trap: null
  wrong_layer: ['^\\s*(벤더 RIL|exynos-ril|모뎀|망|ofonod|D-Bus|관리 데몬|NMD)', '^\\s*그\\s*층\\s*로그\\s*없음']
"""


def test_migrate_round_trip(tmp_path, capsys):
    d = tmp_path / "data-ditd-route-fail"
    d.mkdir()
    (d / "case.yaml").write_text(CASE_YAML, encoding="utf-8")
    deep = tmp_path / "deep-case"
    deep.mkdir()
    (deep / "case.yaml").write_text("schema_version: 1\nkind: deep\nexpect: {}\n", encoding="utf-8")
    assert ma.main(["migrate", str(d), str(deep)]) == 0
    assert capsys.readouterr().out.strip() == str(d / "case.yaml")
    text = (d / "case.yaml").read_text(encoding="utf-8")
    assert text.startswith("# 합성 case 머리 주석\nschema_version: 2\n")
    data = yaml.safe_load(text)
    assert data["expect"] == ma.migrate_expect(yaml.safe_load(CASE_YAML)["expect"])
    assert data["expect"]["trap"][0] == {"label": OLD_EXPLORE["wrong_layer"][0]}
    assert me._expect_problem("explore", data["expect"]) is None
    assert ma.main(["migrate", str(d)]) == 0 and capsys.readouterr().out == ""          # 이미 schema 2면 건너뜀
    assert (d / "case.yaml").read_text(encoding="utf-8") == text
    assert (deep / "case.yaml").read_text(encoding="utf-8").startswith("schema_version: 1\nkind: deep")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "case.yaml").write_text("schema_version: 1\nkind: explore\nexpect: {layer: x}\n", encoding="utf-8")
    assert ma.main(["migrate", str(bad)]) == 1 and "옛 expect 모양이 아님" in capsys.readouterr().err


def test_table_cli_runs_on_templates(capsys):
    code = ma.main(["table", "--platform", "ofono", "--module", "data", "--kind", "deep"])
    out = capsys.readouterr().out
    assert code in (0, 1) and "## ofono/data" in out and "deep(결론 1개)" in out and "| explore |" not in out
    assert ma.main(["table", "--platform", "qmi"]) == 2
