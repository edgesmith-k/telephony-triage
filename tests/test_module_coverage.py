"""tools/module_coverage.py (F, 토큰 0): 사내 로그 → 모듈별 줄 수(module_measure 그대로), 분류 안 된 hot 줄, 모듈에 없는 태그
(known·common·unknown), 안 보인 이름, modules.yaml 제안 diff(더하기만, 다시 읽어 확인). 이름과 개수만 낸다.

로그는 합성(`-- [합성]`), 규칙은 변형 DB `issue-db-ofono-modules`의 parser-rules 사본(태그 몇 개를 더한다).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tests" / "helpers"))
import module_coverage as mc  # noqa: E402
import module_measure  # noqa: E402
import module_remote as mr  # noqa: E402
import runner  # noqa: E402

MOCK_MODULES = mr.MOCK / "modules.yaml"
EXTRA_TAGS = ("  - {tag: NEWD, category: data, added_for: '-', added_on: 2026-11-05, reason: 합성 (coverage 시험)}\n"
              "  - {tag: COMD, category: common, added_for: '-', added_on: 2026-11-05, reason: 합성 (coverage 시험)}\n")


@pytest.fixture(scope="module")
def plug():
    return runner.plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})


@pytest.fixture
def rules(tmp_path):
    db = tmp_path / "db"                                                 # 플랫폼(issue-db.config.yaml)·스키마가 parser-rules 옆에 있다
    shutil.copytree(runner.variant_db("issue-db-ofono-modules"), db)
    dst = db / "parser-rules"
    tags = dst / "tags.yaml"
    tags.write_text(tags.read_text(encoding="utf-8").rstrip("\n") + "\n" + EXTRA_TAGS, encoding="utf-8")
    return dst


def journal(path: Path, spec: dict[str, int], level: str = "err", secret: str = "") -> Path:
    lines = ["-- [합성] module_coverage"]
    n = 0
    for tag, count in spec.items():
        for i in range(count):
            n += 1
            lines.append(f"Sep 20 15:{n // 60:02d}:{n % 60:02d}.000 dut daemon.{level} {tag}[{100 + i}]: step failed {secret}{i}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cov(modules, logs, rules, plug, **kw):
    return mc.run(modules, [{"platform": "ofono", "logs": logs, "rules": rules}], plugin_root=plug, **kw)


def test_counts_equal_module_measure(tmp_path, rules, plug, capsys):
    log = journal(tmp_path / "a" / "journal.log", {"datad": 5, "simd": 3, "mgmtd": 2, "networkd": 4})
    out = cov(MOCK_MODULES, [log], rules, plug)["platforms"]["ofono"]
    module_measure.main(["coverage", "--logs", str(log), "--platform", "ofono", "--tz", "UTC", "--rules", str(rules),
                         "--modules", str(MOCK_MODULES), "--plugin-root", str(plug), "--json"])
    ref = json.loads(capsys.readouterr().out)
    assert out["modules"] == ref["modules"] and out["rows"] == ref["rows"]
    assert out["never_seen"] == ref["never_seen"] and out["unowned"]["unknown"] == ref["unknown_tags"]


def test_unlabelled_hot_counts_only_no_text(tmp_path, rules, plug):
    log = journal(tmp_path / "a" / "journal.log", {"networkd": 6, "datad": 2}, secret="SECRETVALUE-")
    res = cov(MOCK_MODULES, [log], rules, plug)
    hot = res["platforms"]["ofono"]["unlabelled_hot"]
    assert hot == [{"tag": "networkd", "rows": 6, "wef": 6}]
    text = json.dumps(res, ensure_ascii=False) + mc.render(res)
    assert "SECRETVALUE" not in text and "step failed" not in text


def test_unowned_known_suggests_diff_that_applies(tmp_path, rules, plug):
    log = journal(tmp_path / "a" / "journal.log", {"NEWD": 25, "datad": 3})
    res = cov(MOCK_MODULES, [log], rules, plug)
    known = res["platforms"]["ofono"]["unowned"]["known"]
    assert known == [{"tag": "NEWD", "rows": 25, "hot": 25, "category": "data", "module": "data"}]
    sug = res["suggestion"]
    assert sug["additions"] == [{"platform": "ofono", "module": "data", "name": "NEWD", "rows": 25}] and not sug["manual"]
    work = tmp_path / "apply"
    work.mkdir()
    shutil.copy(MOCK_MODULES, work / "modules.yaml")
    (work / "s.diff").write_text(sug["diff"], encoding="utf-8")
    for args in (["apply", "--check", "s.diff"], ["apply", "s.diff"]):
        r = subprocess.run(["git", *args], cwd=work, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    old = yaml.safe_load(MOCK_MODULES.read_text(encoding="utf-8"))
    new = yaml.safe_load((work / "modules.yaml").read_text(encoding="utf-8"))
    old["platforms"]["ofono"]["modules"]["data"]["daemons"].append("NEWD")
    assert new == old                                                    # 더한 것만 다르다
    assert mc.exit_code(res) == 1
    below = cov(MOCK_MODULES, [log], rules, plug, min_lines=30)
    assert below["suggestion"]["additions"] == [] and below["suggestion"]["diff"] is None


def test_unknown_tag_never_in_diff(tmp_path, rules, plug):
    log = journal(tmp_path / "a" / "journal.log", {"GHOSTD": 30, "NEWD": 21})
    res = cov(MOCK_MODULES, [log], rules, plug)
    unknown = {t["tag"]: t for t in res["platforms"]["ofono"]["unowned"]["unknown"]}
    assert unknown["GHOSTD"]["lines"] == 30
    assert "GHOSTD" not in (res["suggestion"]["diff"] or "") and "NEWD" in res["suggestion"]["diff"]
    assert "이슈 DB 계획 op PR이 먼저" in mc.render(res)


def test_common_listed_not_suggested(tmp_path, rules, plug):
    log = journal(tmp_path / "a" / "journal.log", {"COMD": 40, "networkd": 40})
    res = cov(MOCK_MODULES, [log], rules, plug)
    common = {t["tag"]: t["why"] for t in res["platforms"]["ofono"]["unowned"]["common"]}
    assert common == {"COMD": "common", "networkd": "모듈 없음"}                 # network 모듈이 없는 모의 레포
    assert res["suggestion"]["diff"] is None and res["suggestion"]["manual"] == []


def test_never_seen_not_removed(tmp_path, rules, plug):
    log = journal(tmp_path / "a" / "journal.log", {"NEWD": 25})
    res = cov(MOCK_MODULES, [log], rules, plug)
    assert "simd" in res["platforms"]["ofono"]["never_seen"]["sim"]["daemons"]
    new, accepted, _ = mc.suggest_text(MOCK_MODULES.read_text(encoding="utf-8"), res["suggestion"]["additions"])
    after = yaml.safe_load(new)["platforms"]["ofono"]["modules"]
    before = yaml.safe_load(MOCK_MODULES.read_text(encoding="utf-8"))["platforms"]["ofono"]["modules"]
    assert accepted and all(set(before[m].get("daemons") or []) <= set(after[m].get("daemons") or []) for m in before)
    assert after["sim"] == before["sim"]                                 # 안 보인 이름은 지우지 않는다


def test_block_style_manual_fallback(tmp_path, rules, plug):
    text = MOCK_MODULES.read_text(encoding="utf-8").replace(
        "      data: {path: ofono/data, db_category: data, daemons: [datad, datad2], ofonod_files: [src/gprs.c, "
        "drivers/rilmodem/gprs-context.c, src/lte.c]}\n",
        "      data:\n        path: ofono/data\n        db_category: data\n        daemons:\n          - datad\n          - datad2\n")
    assert "- datad" in text
    mods = tmp_path / "modules.yaml"
    mods.write_text(text, encoding="utf-8")
    log = journal(tmp_path / "a" / "journal.log", {"NEWD": 25})
    res = cov(mods, [log], rules, plug)
    assert res["suggestion"]["diff"] is None
    assert res["suggestion"]["manual"] == [{"platform": "ofono", "module": "data", "name": "NEWD", "rows": 25}]
    assert "손으로 고칠 것" in mc.render(res)
    # 블록 모양이라도 한 줄 흐름 목록이면 고친다
    mods.write_text(text.replace("        daemons:\n          - datad\n          - datad2\n", "        daemons: [datad, datad2]\n"),
                    encoding="utf-8")
    assert cov(mods, [log], rules, plug)["suggestion"]["additions"]


def test_exit_codes(tmp_path, rules, plug, capsys):
    mods = tmp_path / "m.yaml"
    mods.write_text("schema_version: 2\nplatforms:\n  ofono:\n    common: {daemons: []}\n    modules:\n"
                    "      data: {path: ofono/data, db_category: data, daemons: [datad]}\n", encoding="utf-8")
    log = journal(tmp_path / "a" / "journal.log", {"datad": 4})
    base = ["--modules", str(mods), "--platform", "ofono", "--rules", str(rules), "--plugin-root", str(plug)]
    assert mc.main([*base, "--logs", str(log)]) == 0, capsys.readouterr()
    capsys.readouterr()
    journal(tmp_path / "b" / "journal.log", {"NEWD": 22})
    out = tmp_path / "out.diff"
    assert mc.main([*base, "--logs", str(tmp_path / "b"), "--out", str(out), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["header"] == "사내 전용" and out.read_text(encoding="utf-8") == data["suggestion"]["diff"]
    assert mc.main([*base, "--logs", str(tmp_path / "missing")]) == 2
    assert mc.main(["--modules", str(tmp_path / "none.yaml"), "--platform", "ofono", "--rules", str(rules),
                    "--logs", str(log)]) == 2


@pytest.mark.skipif(sys.platform == "win32", reason="심볼릭 링크")
def test_logs_dir_expansion_skips_symlinks(tmp_path):
    d = tmp_path / "logs"
    journal(d / "case1" / "journal.log", {"datad": 1})
    journal(d / "case1" / "syslog.masked", {"datad": 1})
    (d / "case1" / "info.txt").write_text("x", encoding="utf-8")
    journal(d / ".hidden" / "journal.log", {"datad": 1})
    journal(tmp_path / "outside" / "journal.log", {"datad": 1})
    os.symlink(tmp_path / "outside" / "journal.log", d / "case1" / "kernel.log")
    os.symlink(tmp_path / "outside", d / "linked")
    got = [p.relative_to(d).as_posix() for p in mc.expand_logs([d], "ofono")]
    assert got == ["case1/journal.log", "case1/syslog.masked"]
    assert [p.name for p in mc.expand_logs([d], "android")] == ["info.txt", "journal.log", "syslog.masked"]
    with pytest.raises(mc.UsageError):
        mc.expand_logs([tmp_path / "nope"])
