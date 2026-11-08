"""run의 5-1 줄(B2 §7.1·§7.3), `report.rewrite_line`·`current_line`, 타임라인 분해(§1.4), 이전 실행 기록 지우기(§7.4).

`analysis.json.analyzer` 모양: `{skill, when}`(레거시·prefer: skill, 바이트 그대로) | `{category, when}`(모듈 스킬) |
`{error, when: never}`(설정 오류 — 5-1 질문을 건너뛴다). 원격 없고 prefer 없으면 run 출력이 이전과 같다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(SCRIPTS))

from runner import plugin_root, run_json, tmp, variant_db  # noqa: E402
from triagelib import core, report  # noqa: E402

LOGS = REPO / "tests" / "fixtures" / "logs" / "ofono"
ON = {"name": "android", "enabled": ["android", "ofono"]}
NO_ANALYZER_LINE = "- 심층 분석: 해당 없음(1위 카테고리에 분석 스킬 설정 없음)"


def _run(analyzers: dict | None, user: dict | None = None) -> tuple[dict, str, Path]:
    over = {"platform": ON}
    if analyzers is not None:
        over["platforms"] = {"ofono": {"analyzers": analyzers}}
    root = plugin_root("b2-lines-" + json.dumps(analyzers, sort_keys=True), **over)
    work = tmp("tt-b2-lines-")
    home = work / "home"
    home.mkdir()
    if user:
        (home / "config.yaml").write_text(yaml.safe_dump(user, allow_unicode=True), encoding="utf-8")
    meta = work / "meta.json"
    meta.write_text(json.dumps({"key": "MOCK-9001", "occurred_at": "2026-09-20T05:32:10Z", "summary": "x",
                                "platform_version": "2"}), encoding="utf-8")
    run_json("triage.py", ["run", "MOCK-9001", "--offline-db", variant_db("issue-db-ofono"), "--logs", LOGS / "journal-iso.log",
                           "--issue-meta", meta, "--out", work / "job", "--platform", "ofono"],
             root=root, env={"TELEPHONY_TRIAGE_HOME": home})
    job = work / "job"
    return json.loads((job / "analysis.json").read_text(encoding="utf-8")), (job / "report.md").read_text(encoding="utf-8"), job


NOTE_51 = "답 전 로그 원문 grep·sed·Read 금지 — report.md를 보이고 묻는다(SKILL 5-1)"     # driver.ASK_NOTE(when: ask)
REMOTE = {"module_skills": {"remote": "file:///nonexistent/module-skills.git"}}


def test_remote_gives_category_shape_and_pending_line():
    analysis, text, _ = _run(None, REMOTE)
    assert analysis["analyzer"] == {"category": "data", "when": "ask", "note": "답 전 로그 원문 grep·sed·Read 금지 — report.md를 보이고 묻는다(SKILL 5-1)"}
    line = core.DEEP_MODULE_PENDING.format(platform="ofono", category="data", key="MOCK-9001")
    assert line in text.split("\n") and "TODO(LLM)" in line


def test_remote_with_when_never_keeps_never_line():
    analysis, text, _ = _run({"data": {"when": "never"}}, REMOTE)
    assert analysis["analyzer"] == {"category": "data", "when": "never"}
    assert "- 심층 분석 생략: platforms.ofono.analyzers.data.when: never" in text


def test_prefer_skill_keeps_legacy_shape_bytes():
    analysis, text, _ = _run({"data": {"skill": "mock-ofono-analyzer", "when": "ask", "prefer": "skill"}}, REMOTE)
    assert list(analysis["analyzer"].items()) == [("skill", "mock-ofono-analyzer"), ("when", "ask"), ("note", NOTE_51)]
    assert "- 심층 분석 (mock-ofono-analyzer): TODO(LLM) 결과 요약" in text


@pytest.mark.parametrize("entry, needle", [
    ({"prefer": "modul"}, "analyzers.data.prefer: module 또는 skill이어야 합니다"),
    ({"prefer": "skill"}, "analyzers.data.prefer: skill인데 skill(설치된 분석 스킬 이름)이 없습니다"),
])
def test_error_shape_renders_config_error_before_never(entry, needle):
    analysis, text, _ = _run({"data": entry})
    assert analysis["analyzer"]["when"] == "never" and needle in analysis["analyzer"]["error"]
    line = next(x for x in text.split("\n") if x.startswith("- 심층 분석"))
    assert line.startswith("- 심층 분석 생략: 설정 오류(") and needle in line


def test_prefer_only_without_remote_is_not_applicable():
    analysis, text, _ = _run({"data": {"prefer": "module"}})
    assert analysis.get("analyzer") is None and NO_ANALYZER_LINE in text


def test_no_remote_legacy_skill_unchanged():
    analysis, text, _ = _run({"data": {"skill": "mock-ofono-analyzer", "when": "ask"}})
    assert analysis["analyzer"] == {"skill": "mock-ofono-analyzer", "when": "ask", "note": NOTE_51}
    assert "- 심층 분석 (mock-ofono-analyzer): TODO(LLM) 결과 요약 / 분석 스킬 의견:" in text


# --- rewrite_line / current_line ------------------------------------------------------------------------------

REPORT = "# r\n\n- 분류 후보: X\n- 심층 분석 (a): TODO(LLM) 결과\n  - 모듈 타임라인: 3/9줄\n  - old sub\n- 탐색 분석: 생략\n"


def test_rewrite_line_keep_sub_and_pending(tmp_path):
    p = tmp_path / "report.md"
    p.write_text(REPORT, encoding="utf-8")
    assert report.current_line(p, "- 심층 분석") == "- 심층 분석 (a): TODO(LLM) 결과"
    assert report.rewrite_line(p, "- 심층 분석", ["- 심층 분석 (a): 끝", "  - 근거: q"], keep_sub=("  - 모듈 타임라인:",),
                               only_pending=True)
    assert p.read_text(encoding="utf-8") == ("# r\n\n- 분류 후보: X\n- 심층 분석 (a): 끝\n  - 근거: q\n  - 모듈 타임라인: 3/9줄\n"
                                             "- 탐색 분석: 생략\n")
    before = p.read_bytes()
    assert not report.rewrite_line(p, "- 심층 분석", ["x"], only_pending=True)           # TODO(LLM) 없음: 쓰지 않는다
    assert not report.rewrite_line(p, "- 없는 줄", ["x"])
    assert p.read_bytes() == before
    assert report.rewrite_line(p, "- 탐색 분석", ["- 탐색 분석 생략: y"])                 # 성공 경로는 항상 쓴다
    assert "- 탐색 분석 생략: y\n" in p.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="symlink")
def test_rewrite_line_refuses_link_and_survives_oserror(tmp_path, monkeypatch):
    target = tmp_path / "real.md"
    target.write_text(REPORT, encoding="utf-8")
    link = tmp_path / "report.md"
    os.symlink(target, link)
    assert report.current_line(link, "- 심층 분석") is None
    assert not report.rewrite_line(link, "- 심층 분석", ["x"]) and target.read_text(encoding="utf-8") == REPORT
    assert report.current_line(tmp_path / "missing.md", "- 심층") is None
    plain = tmp_path / "plain.md"
    plain.write_text(REPORT, encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(os, "replace", boom)
    assert report.rewrite_line(plain, "- 심층 분석", ["x"]) is False
    assert plain.read_text(encoding="utf-8") == REPORT and not list(tmp_path.glob("*.tmp"))


# --- 타임라인 분해 = timeline() -----------------------------------------------------------------------------------

def _rows():
    rows = [{"ts": f"2026-09-20T05:{i:02d}:00.000Z", "tag": "DNC-0", "msg": f"line {i}", "level": "D", "phone_id": 1,
             "category_hint": "data" if i % 2 else None, "pid": 100 + i, "line_ref": f"f0:L{i}"} for i in range(60)]
    rows[5].update(level="E", msg="setup failed")
    rows[50].update(event="data_evaluation_rejected", fields={"reasons": "X"}, category_hint="ims")
    rows.append({**rows[50], "event": None, "fields": {}, "category_hint": "data", "ril": {"request": "SETUP_DATA_CALL"}})
    return rows


def test_split_composition_equals_timeline():
    ev = {"events": _rows(), "input": {"window": {"start": "a", "end": "b"}}}
    for around, limit, fs, anchor in (("2026-09-20T05:30:00Z", 20, None, None), (None, 200, "4 | x", None),
                                      ("2026-09-20T05:30:00Z", 10, None, {"source": "marker", "step": "S", "start": None,
                                                                          "fail": "2026-09-20T05:31:00Z"})):
        rows = report.merge_rows(ev)
        items, total = report.select_rows(rows, around, limit)
        text = report.render_timeline("K-1", ev, items, total, around, limit, fs, anchor)
        assert report.timeline("K-1", ev, around, limit, fs, anchor) == (text, len(items), total)


def test_merge_rows_extra_keys():
    rows = report.merge_rows({"events": _rows()})
    assert len(rows) == 60 and [r["idx"] for r in rows] == list(range(60))
    r50 = rows[50]
    assert r50["marks"] == ["data_evaluation_rejected(reasons=X)"]
    assert r50["cat"] == "data" and r50["ril"] == {"request": "SETUP_DATA_CALL"}     # 원 줄 기록의 분류·RIL
    assert rows[1]["cat"] == "data" and rows[2]["cat"] is None and rows[3]["pid"] == 103 and rows[3]["line_ref"] == "f0:L3"


def _ev(**k):
    base = {"ts": "2026-11-06T10:00:00.000Z", "tag": "RIL", "msg": "SETUP_DATA_CALL failed", "level": "E", "phone_id": None,
            "pid": None, "line_ref": None, "event": None, "fields": {}, "category_hint": None, "ril": None}
    base.update(k)
    return base


def test_merge_rows_keeps_other_slots_files_and_repeats_apart():
    """종합 리뷰 F2: 같은 (시각, 태그, 메시지)라도 다른 슬롯·다른 pid·다른 파일·같은 문구의 반복은 줄 위치가 다르므로 따로 둔다."""
    rows = report.merge_rows({"events": [_ev(phone_id=0, pid=100, line_ref={"file_index": 0, "line_no": 10}),
                                         _ev(phone_id=1, pid=101, line_ref={"file_index": 0, "line_no": 11})]})
    assert [(r["phone"], r["pid"], r["idx"]) for r in rows] == [(0, 100, 0), (1, 101, 1)]
    assert len(report.merge_rows({"events": [_ev(line_ref={"file_index": 0, "line_no": 5}),
                                             _ev(line_ref={"file_index": 1, "line_no": 5})]})) == 2      # 다른 파일
    assert len(report.merge_rows({"events": [_ev(line_ref={"file_index": 0, "line_no": 5}),
                                             _ev(line_ref={"file_index": 0, "line_no": 6})]})) == 2      # 같은 문구 반복
    # 슬롯 미상(None) 원 줄과 슬롯이 있는 파생 이벤트는 같은 줄이면 합치고 슬롯을 채운다
    rows = report.merge_rows({"events": [_ev(line_ref={"file_index": 0, "line_no": 7}),
                                         _ev(phone_id=1, line_ref={"file_index": 0, "line_no": 7}, event="ril_error")]})
    assert len(rows) == 1 and rows[0]["phone"] == 1 and rows[0]["marks"] == ["ril_error"]


def test_merge_rows_same_line_derived_events_still_merge():
    ref = {"file_index": 0, "line_no": 10}
    rows = report.merge_rows({"events": [_ev(phone_id=0, line_ref=ref, category_hint="data", ril={"request": "SETUP_DATA_CALL"}),
                                         _ev(phone_id=0, line_ref=ref, event="ril_error", fields={"code": "2"}, category_hint="ims"),
                                         _ev(phone_id=0, line_ref=ref, event="data_fail")]})
    assert len(rows) == 1
    assert rows[0]["marks"] == ["ril_error(code=2)", "data_fail"] and rows[0]["cat"] == "data" and rows[0]["ril"] == {"request": "SETUP_DATA_CALL"}


def test_merge_rows_events_without_line_ref_join_matching_slot():
    """줄 위치 없는 이벤트(외부 파서)는 같은 문구의 행 가운데 슬롯·pid가 맞는 첫 행에 붙고, 맞는 행이 없으면 새 행이다."""
    base = [_ev(phone_id=0, pid=100, line_ref={"file_index": 0, "line_no": 10}),
            _ev(phone_id=1, pid=101, line_ref={"file_index": 0, "line_no": 11})]
    rows = report.merge_rows({"events": base + [_ev(phone_id=1, event="ext_fail")]})
    assert [(r["phone"], r["marks"]) for r in rows] == [(0, []), (1, ["ext_fail"])]
    rows = report.merge_rows({"events": base + [_ev(event="ext_fail")]})                      # 슬롯 미상 → 첫 행
    assert [(r["phone"], r["marks"]) for r in rows] == [(0, ["ext_fail"]), (1, [])]
    rows = report.merge_rows({"events": base + [_ev(phone_id=2, event="ext_fail")]})          # 맞는 행 없음 → 새 행
    assert [(r["phone"], r["marks"]) for r in rows] == [(0, []), (1, []), (2, ["ext_fail"])]
    # line_ref가 전혀 없는 옛 events.json: (시각, 태그, 메시지, 슬롯, pid)로 합친다
    rows = report.merge_rows({"events": [_ev(phone_id=0), _ev(phone_id=0, event="x"), _ev(phone_id=1)]})
    assert [(r["phone"], r["marks"]) for r in rows] == [(0, ["x"]), (1, [])]
    text = report.row_line(rows[1], clip=None)
    assert text.startswith("10:00:00.000 p1 E RIL SETUP_DATA_CALL failed")


def test_split_on_ofono_fixture():
    path = REPO / "templates" / "module-skills" / "ofono" / "data" / "evals" / "data-apn-auth-reject" / "files" / "events.json"
    ev = json.loads(path.read_text(encoding="utf-8"))
    for around in (None, "2026-09-20T15:10:02Z"):
        items, total = report.select_rows(report.merge_rows(ev), around, 50)
        assert report.timeline("K", ev, around, 50) == (report.render_timeline("K", ev, items, total, around, 50), len(items),
                                                        total)


# --- 이전 실행 기록(driver.prepare) ------------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="symlink")
def test_drop_stale_records_unlinks_links_without_following(tmp_path):
    from triagelib.driver import Driver
    job = tmp_path / "job"
    (job / "module-skill" / "deep").mkdir(parents=True)
    for name in core.STALE_FILES:
        (job / name).write_text("x", encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text("keep", encoding="utf-8")
    (job / "check-output.json").unlink()
    os.symlink(outside, job / "check-output.json")
    (job / "keep.txt").write_text("k", encoding="utf-8")
    drv = Driver.__new__(Driver)
    drv.job = job
    drv.drop_stale_records()
    assert sorted(p.name for p in job.iterdir()) == ["keep.txt"] and outside.read_text(encoding="utf-8") == "keep"
    drv.drop_stale_records()                            # 없으면 아무것도 바꾸지 않는다
    assert sorted(p.name for p in job.iterdir()) == ["keep.txt"]
    link_dir = tmp_path / "elsewhere"
    link_dir.mkdir()
    (link_dir / "a").write_text("a", encoding="utf-8")
    os.symlink(link_dir, job / "module-skill")
    drv.drop_stale_records()
    assert not (job / "module-skill").exists() and (link_dir / "a").is_file()
