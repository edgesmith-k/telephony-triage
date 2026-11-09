#!/usr/bin/env python3
"""`tools/module_measure.py coverage` (B2 §4.7): 모듈별 줄 수, 모르는 태그, 안 보인 이름, 종료 코드, 글 미출력, 기준 차이.

`triagelib.report.merge_rows`(group 4)가 없는 체크아웃에서는 `test_modulefilter`의 대체를 같은 프로세스에 끼운다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests"))
if str(REPO / "plugin" / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import module_measure
import test_modulefilter  # noqa: F401  (merge_rows 대체를 끼운다)
from common import modulefilter as mf

JOB = REPO / "tests" / "fixtures" / "module-filter" / "e1-euicc-poll"
MODULES = REPO / "templates" / "module-skills" / "modules.yaml"


def _cov(capsys, *extra) -> tuple[int, dict]:
    code = module_measure.main(["coverage", "--job", str(JOB), "--modules", str(MODULES), "--json", *map(str, extra)])
    return code, json.loads(capsys.readouterr().out)


def test_coverage_counts_match_primary(capsys):
    code, out = _cov(capsys)
    assert code == 0 and out["header"] == "사내 전용"
    events = json.loads((JOB / "events.json").read_text(encoding="utf-8"))
    spec = mf.compile_spec(yaml.safe_load(MODULES.read_text(encoding="utf-8")), "ofono")
    rows = mf.rows_of(events)
    mf.label(spec, rows)
    items = [r for r in rows if not r["noise"]]
    direct = {}
    for r in items:
        d, _ = mf.primary(spec, r)
        if d:
            direct[d] = direct.get(d, 0) + 1
    assert {m: v["primary"] for m, v in out["modules"].items() if v["primary"]} == direct
    assert out["rows"] == len(rows)
    assert "sim" in out["never_seen"]                    # 이 짧은 발췌에 없는 sim 이름이 있다


def test_coverage_json_has_no_message_text(capsys):
    _code, out = _cov(capsys)
    text = json.dumps(out, ensure_ascii=False)
    events = json.loads((JOB / "events.json").read_text(encoding="utf-8"))
    for e in events["events"]:
        msg = e.get("msg") or ""
        if len(msg) >= 12:
            assert msg not in text


def test_unknown_tags_from_logs(tmp_path, capsys):
    import runner

    db = runner.variant_db("issue-db-ofono-modules")
    root = runner.plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    log = tmp_path / "x.log"
    log.write_text("\n".join([
        "-- [합성] module_measure unknown tag test",
        "Sep 20 15:10:00.000 dut daemon.info ofonod[812]: src/gprs.c:f() activating",
        "Sep 20 15:10:01.000 dut daemon.err ofonod/x[812]: something failed",
        "Sep 20 15:10:02.000 dut daemon.err UNKNOWND[9]: something failed",
    ]) + "\n", encoding="utf-8")
    code = module_measure.main(["coverage", "--logs", str(log), "--platform", "ofono", "--tz", "UTC", "--year", "2026",
                                "--rules", str(db / "parser-rules"), "--modules", str(MODULES), "--plugin-root", str(root),
                                "--json"])
    out = json.loads(capsys.readouterr().out)
    tags = {t["tag"]: t for t in out["unknown_tags"]}
    assert "UNKNOWND" in tags and tags["UNKNOWND"]["wef"] == 1
    assert code in (0, 1)


def test_findings_exit_and_baseline(tmp_path, capsys):
    import runner

    db = runner.variant_db("issue-db-ofono-modules")
    doc = yaml.safe_load(MODULES.read_text(encoding="utf-8"))
    doc["platforms"]["ofono"]["modules"]["sim"]["daemons"] = ["LPA", "NMD"]      # NMD는 tags.yaml에서 data
    bad = tmp_path / "modules.yaml"
    bad.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    code = module_measure.main(["coverage", "--job", str(JOB), "--modules", str(bad), "--rules", str(db / "parser-rules"),
                                "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and any("NMD" in f for f in out["findings"])
    base = tmp_path / "base.json"
    base.write_text(json.dumps(out), encoding="utf-8")
    code, again = _cov(capsys, "--baseline", base)
    assert any(d.startswith("modules.sim.primary") or "바뀜" in d for d in again["baseline_diff"]) or again["baseline_diff"]
    assert module_measure.main(["coverage", "--modules", str(MODULES)]) == 2
    assert module_measure.main(["coverage", "--job", str(tmp_path / "nojob"), "--modules", str(MODULES)]) == 2


def test_raw_tags_profile_error_is_usage_error(tmp_path):
    """oFono 줄 읽기의 site-defaults 로드 실패(파일 없음)는 traceback이 아니라 사용 오류(종료 2)다."""
    import argparse

    import pytest

    args = argparse.Namespace(platform="ofono", plugin_root=str(tmp_path), tz="UTC", year=2026)
    with pytest.raises(module_measure.UsageError):
        module_measure._raw_tags([], args, None)
