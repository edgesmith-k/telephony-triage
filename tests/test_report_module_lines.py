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


def test_select_rows_folds_repeated_plain_rows_but_keeps_every_event_row():
    """sim1122 F3(S-10): 같은 오류 문구 반복(이벤트 표시 없음)이 상한을 채워 로그 끝 이벤트 줄이 빠졌다. 넘칠 때 같은 줄 반복은
    먼저 뽑힐 한 줄로 접고(스크립트 메모 `〔script …〕`, 근거 검사는 떼고 본다), 이벤트 줄은 같은 문구여도 접지 않는다."""
    ev = []
    for i in range(30):          # 이벤트 없는 E 줄 세 문장이 열 번씩 되풀이 — 시각은 이벤트보다 앞
        for j, msg in enumerate(("Unsupported band type 0", "Unsupported unknown band.", "Invalid cell ID")):
            ev.append(_ev(ts=f"2026-11-06T10:{i:02d}:{j:02d}.000Z", tag="RILJ", msg=msg, phone_id=0,
                          line_ref={"file_index": 0, "line_no": 3 * i + j}))
    for k in range(4):           # 로그 끝 이벤트 줄: 같은 문구 두 번(다른 시각의 같은 사건)
        ev.append(_ev(ts=f"2026-11-06T11:00:{k:02d}.000Z", tag="SST-0", msg="pollStateDone: hasRegistered = true" if k % 2
                      else "detach", phone_id=0, level="D", line_ref={"file_index": 0, "line_no": 500 + k}, event=f"e{k % 2}"))
    rows = report.merge_rows({"events": ev})
    items, total = report.select_rows(rows, None, 10)      # time=full: 거리 0, 우선 줄을 시각순으로
    assert total == 94 and len(items) == 7
    assert [r["msg"] for r in items if r["marks"]] == ["detach", "pollStateDone: hasRegistered = true"] * 2
    plain = [r for r in items if not r["marks"]]
    assert [(r["msg"], r["fold"]["n"]) for r in plain] == [("Unsupported band type 0", 29), ("Unsupported unknown band.", 29),
                                                             ("Invalid cell ID", 29)]
    assert all("fold" not in r for r in rows)                # merge_rows의 행은 바꾸지 않는다(근거 원문·모듈 필터가 같이 쓴다)
    text = report.render_timeline("K", {"events": ev}, items, total, None, 10)
    assert "- 줄: 7/94 (이벤트·경고·오류 줄 우선, 발생 시각에 가까운 순으로 골랐다, 같은 줄 반복 87줄은 접었다)" in text
    line = next(t for t in text.splitlines() if "Unsupported band type 0" in t)
    assert line == "10:00:00.000 p0 E RILJ Unsupported band type 0  〔script 같은 줄 29번 더 접음(10:01:00.000~10:29:00.000)〕"
    from common import evidence
    source, tags = evidence.source_text(text)
    # RP-13: 줄 끝 메모까지 그대로 복사한 인용도 본 줄로 판정한다(메모만 인용하면 지어낸 것)
    assert evidence.check_quotes([line], source, tags)["fabricated"] == 0
    assert evidence.check_quotes(["〔script 같은 줄 29번 더 접음(10:01:00.000~10:29:00.000)〕"], source, tags)["fabricated"] == 1
    # 상한 안이면 접지 않는다(지금과 같다)
    items, _ = report.select_rows(rows, None, 200)
    assert len(items) == 94 and all("fold" not in r for r in items)
    # RP-5: 발생 시각 ±60초 안의 줄은 접지 않고, 그 밖의 반복은 발생 시각에 가장 가까운 한 줄로 접는다
    # (CP-1 뒤 이벤트 4줄이 먼저 자리를 차지하므로 상한을 13으로 — 이벤트 4 + 창 안 6 + 접은 대표 3)
    items, _ = report.select_rows(rows, "2026-11-06T10:20:30Z", 13)
    band = [r for r in items if r["msg"] == "Unsupported band type 0"]
    assert [(r["ts"][11:19], "fold" in r) for r in band] == [("10:19:00", True), ("10:20:00", False), ("10:21:00", False)]


def test_select_rows_keeps_few_repeats_and_log_end_rows():
    """RP-5: 반복이 `FOLD_MIN`번보다 적은 상태 줄(회차마다 나오는 OOS 등)과 로그 끝 60초 안의 줄은 접지 않는다."""
    ev = [_ev(ts=f"2026-11-06T10:{i:02d}:00.000Z", tag="RILJ", msg="spam", phone_id=0, line_ref={"file_index": 0, "line_no": i})
          for i in range(30)]
    ev += [_ev(ts=f"2026-11-06T10:{i:02d}:30.000Z", tag="SST-0", msg="Poll ServiceState done: OUT_OF_SERVICE", phone_id=0,
               line_ref={"file_index": 0, "line_no": 100 + i}) for i in (5, 15, 25)]          # 회차마다 한 번 — 3번뿐
    ev += [_ev(ts=f"2026-11-06T10:40:{s:02d}.000Z", tag="RILJ", msg="spam", phone_id=0, line_ref={"file_index": 0, "line_no": 200 + s})
           for s in (0, 20, 40)]                                                                # 로그 끝 반복
    items, total = report.select_rows(report.merge_rows({"events": ev}), None, 10)
    assert total == 36
    assert [r["ts"][11:19] for r in items if r["msg"].startswith("Poll")] == ["10:05:30", "10:15:30", "10:25:30"]
    assert [r["ts"][11:19] for r in items if r["msg"] == "spam" and "fold" not in r] == ["10:40:00", "10:40:20", "10:40:40"]
    assert [r["fold"]["n"] for r in items if "fold" in r] == [29]
    assert report.FOLD_MIN == 10 and report.FOLD_KEEP_SEC == 60


def test_select_rows_picks_event_rows_before_error_rows_on_short_log():
    """CP-1(S-10 모양): 짧은 로그에 발생 시각을 가운데로 주면 접지 않는 창(±60초·로그 끝 60초)이 로그 거의 전체를 덮어 접기가
    꺼진다. 그때 발생 시각 근처 E 줄 반복이 상한을 채워 로그 끝 이벤트 줄(재등록)이 빠지면 안 된다 — 이벤트 줄을 W/E 줄보다 먼저."""
    ev = [_ev(ts=f"2026-11-06T10:{s // 60:02d}:{s % 60:02d}.000Z", tag="RILJ", msg="Unsupported band type 0", phone_id=0,
              line_ref={"file_index": 0, "line_no": s}) for s in range(150)]
    for k, s in enumerate((10, 11, 12, 168, 169, 170)):      # 로그 앞·끝 이벤트 줄(발생 시각에서 80초 넘게 떨어짐)
        ev.append(_ev(ts=f"2026-11-06T10:{s // 60:02d}:{s % 60:02d}.000Z", tag="SST-0", msg=f"state {k}", phone_id=0, level="D",
                      line_ref={"file_index": 0, "line_no": 500 + k}, event="network_service_state"))
    rows = report.merge_rows({"events": ev})
    for limit in (20, 10):
        items, total = report.select_rows(rows, "2026-11-06T10:01:30Z", limit)
        assert total == 156 and len(items) == limit
        assert sorted(r["msg"] for r in items if r["marks"]) == [f"state {k}" for k in range(6)]


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


# --- 조사 모드 5-1 건너뜀(반입 8 할 일 2) ------------------------------------------------------------------------

from runner import SAMPLE  # noqa: E402

C0_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"     # DSMGR 줄을 빼면 1위 DATA-001 C=0


def _run_c0(user: dict | None, *extra: str, work: Path | None = None) -> tuple[dict, str]:
    work = work or tmp("tt-skip51-")
    home = work / "home"
    home.mkdir(exist_ok=True)
    if user:
        (home / "config.yaml").write_text(yaml.safe_dump(user, allow_unicode=True), encoding="utf-8")
    log = work / "c0.log"
    log.write_text("".join(x for x in C0_LOG.read_text(encoding="utf-8").splitlines(keepends=True) if "DSMGR" not in x),
                   encoding="utf-8")
    meta = work / "meta.json"
    meta.write_text(json.dumps({"key": "MOCK-9051", "occurred_at": "2026-09-20T14:30:20+09:00", "summary": "data"}),
                    encoding="utf-8")
    job = work / "job"
    run_json("triage.py", ["run", "MOCK-9051", "--offline-db", SAMPLE, "--out", job, "--logs", log, "--issue-meta", meta,
                           "--tz", "Asia/Seoul", "--year", "2026", *extra], root=plugin_root(), env={"TELEPHONY_TRIAGE_HOME": home})
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["investigate"]["mode"] and analysis["candidates"][0]["C"] == 0
    return analysis, (job / "report.md").read_text(encoding="utf-8")


def _deep_line(text: str) -> str:
    return next(x for x in text.split("\n") if x.startswith("- 심층 분석"))


def test_investigate_module_source_skips_51():
    """조사 모드 + 모듈 문서 출처 → 5-1을 내지 않는다(never와 같은 모양에 사유), 리포트 줄은 사실대로(실패·미실행 아님)."""
    analysis, text = _run_c0(REMOTE)
    assert analysis["analyzer"] == {"skipped": "조사 모드", "when": "never"}
    assert _deep_line(text) == core.DEEP_INVESTIGATE_SKIPPED


def test_investigate_forced_by_analyzer_flag_runs_51():
    """되돌리는 길: `--analyzer`면 조사 모드에서도 지금처럼 5-1(모듈 문서)."""
    analysis, text = _run_c0(REMOTE, "--analyzer")
    assert analysis["analyzer"] == {"category": "data", "when": "ask", "note": NOTE_51}
    assert _deep_line(text) == core.DEEP_MODULE_PENDING.format(platform="android", category="data", key="MOCK-9051")


def test_investigate_registered_skill_source_still_runs_51():
    """출처가 등록 스킬(`prefer: skill`)이면 조사 모드여도 지금처럼 돈다."""
    user = {**REMOTE, "analyzers": {"data": {"skill": "mock-data-analyzer", "prefer": "skill"}}}
    analysis, text = _run_c0(user)
    assert analysis["analyzer"] == {"skill": "mock-data-analyzer", "when": "ask", "note": NOTE_51}
    assert _deep_line(text).startswith("- 심층 분석 (mock-data-analyzer): TODO(LLM)")


def test_investigate_without_remote_keeps_legacy_skill():
    """모듈 문서 주소가 없으면(설치 스킬 `analyzers.data.skill`, 예전 Q2) 조사 모드여도 그대로."""
    analysis, _ = _run_c0(None)
    assert analysis["analyzer"] == {"skill": "mock-data-analyzer", "when": "ask", "note": NOTE_51}


def test_explore_rerun_with_model_look_at_keeps_forced_analyzer():
    """탐색 중 다시 한 run(`--look-at-source model --look-at`, explore.md 2·4번 — 하위 에이전트는 시작 플래그를 모른다)은
    직전 조사 모드 실행의 `--analyzer`를 이어받는다. 아니면 이미 돈 5-1이 "생략: 조사 모드"로 바뀐다."""
    work = tmp("tt-skip51-rerun-")
    _run_c0(REMOTE, "--analyzer", work=work)
    run_json("triage.py", ["explore", "MOCK-9051", "--out", work / "job"], root=plugin_root(),
             env={"TELEPHONY_TRIAGE_HOME": work / "home"})
    look = ("--look-at-source", "model", "--look-at", "DCM-0: Carrier config updated. Config is carrier specific.")
    analysis, text = _run_c0(REMOTE, *look, work=work)
    assert analysis["analyzer"] == {"category": "data", "when": "ask", "note": NOTE_51}
    assert _deep_line(text) == core.DEEP_MODULE_PENDING.format(platform="android", category="data", key="MOCK-9051")
    analysis, _ = _run_c0(REMOTE, "--no-analyzer", *look, work=work)      # 끄는 쪽은 그대로 끈다
    assert analysis["analyzer"] == {"skipped": "조사 모드", "when": "never"}


def test_user_rerun_without_flag_does_not_inherit_analyzer():
    """사용자가 다시 한 분석(기준 줄 없음·user)은 이어받지 않는다 — 있음/없음 비교가 플래그 하나로 된다."""
    work = tmp("tt-skip51-cmp-")
    _run_c0(REMOTE, "--analyzer", work=work)
    run_json("triage.py", ["explore", "MOCK-9051", "--out", work / "job"], root=plugin_root(),
             env={"TELEPHONY_TRIAGE_HOME": work / "home"})
    analysis, _ = _run_c0(REMOTE, work=work)
    assert analysis["analyzer"] == {"skipped": "조사 모드", "when": "never"}


@pytest.mark.parametrize("analyzer, forced", [({"category": "data", "when": "ask"}, True),
                                              ({"category": "data", "when": "never"}, False),     # C-6: 설정 never는 --analyzer 표시가 아니다
                                              ({"skipped": "조사 모드", "when": "never"}, False)])
def test_prior_forced_analyzer_ignores_config_never(tmp_path, analyzer, forced):
    from triagelib.driver import Driver
    (tmp_path / "analysis.json").write_text(json.dumps({"investigate": {"mode": True}, "analyzer": analyzer}), encoding="utf-8")
    drv = Driver.__new__(Driver)
    drv.job = tmp_path
    assert drv.prior_forced_analyzer() is forced
