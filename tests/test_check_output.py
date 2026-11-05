"""`triage.py check-output` (B2 §6): 출력 마스킹·칸·바이트 한도·근거 원문 검사·report 줄·기록·표시 의무·종료표.

`module`(작업 묶음 2)을 부르지 않는다: `module-skill.json`·타임라인·`skill-input.json`은 이 파일의 도우미가 쓴다(B1 §4.5·B2 §5.4
모양). 명령은 `output.cmd_check_output(args, defaults)`를 같은 프로세스에서 부른다(파서는 triage.py, 작업 묶음 2).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import evidence, masking, provenance, shown  # noqa: E402
from triagelib import core, output, report  # noqa: E402

KEY = "MOCK-9076"
SHA = "a" * 40
DEEP_PENDING = core.DEEP_MODULE_FETCHED.format(module="ofono/data", sha7=SHA[:7])
SKILL_PENDING = ("- 심층 분석 (mock-data-analyzer): TODO(LLM) 결과 요약 / 분석 스킬 의견: <원인 ID — 근거 | 1위와 같음>. "
                 "실행 안 함·실패면 이 줄을 \"심층 분석 생략: <사유>\"로")
EXPLORE_PENDING = core.EXPLORE_DONE_LINE.format(lines=4, total=4)
SUB = "  - 모듈 타임라인: 4/4줄, 잡음 0, 반복 접음 0"

ROWS = [("2026-09-20T15:10:00.100Z", "ofonod", "I", "src/gprs.c:gprs_attach() attach requested apn=internet"),
        ("2026-09-20T15:10:01.200Z", "exynos-ril", "E", "RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"),
        ("2026-09-20T15:10:02.300Z", "ofonod", "W", "drivers/rilmodem/gprs-context.c:setup_cb() activation failed"),
        ("2026-09-20T15:10:03.400Z", "NMD", "I", "network manager daemon state=disconnected reason=pdn_reject")]
EXTRA_ROW = ("2026-09-20T15:20:09.000Z", "DITD", "I", "policy table refreshed for interface rmnet_data7 entries=12")


def _events(rows=ROWS, allow=()) -> dict:
    return {"events": [{"ts": ts, "tag": tag, "level": lv, "msg": msg, "phone_id": 0, "event": None} for ts, tag, lv, msg in rows],
            "input": {"window": {"start": "2026-09-20T15:00:00Z", "end": "2026-09-20T15:30:00Z"}}, "mask_allow": list(allow)}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _report(line: str, sub: list[str] = ()) -> str:
    return "\n".join(["# MOCK-9076 분석 리포트", "", "- 분류 후보: DATA-001-01", line, *sub, "- 기타 후보: 없음", ""])


def make_job(base: Path, purpose: str = "deep", mode: str = "module", line: str | None = None, *, analyzer=None,
             rows=ROWS, timeline_rows=None, allow=(), record: bool = True, failed_step: str | None = None) -> Path:
    """JOB 하나. mode: module(모듈 기록) | skill(설치 스킬 기록) | none(기록 없음) | explore(뷰 기록) | plain(JOB/timeline.md만)."""
    job = base / KEY
    job.mkdir(parents=True)
    ev = _events(rows, allow)
    (job / "events.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    tl_ev = _events(timeline_rows if timeline_rows is not None else rows, allow)
    text, kept, total = report.timeline(KEY, tl_ev, "2026-09-20T15:10:02Z", 200, failed_step)
    if analyzer is None:
        analyzer = {"category": "data", "when": "ask"} if mode == "module" else {"skill": "mock-data-analyzer", "when": "ask"}
    analysis = {"key": KEY, "platform": "ofono", "candidates": [{"type": "DATA-001", "cause": "DATA-001-01", "category": "data"}],
                "analyzer": analyzer if purpose == "deep" else None,
                "explore": {"reason": "no_candidate", "when": "ask"} if purpose == "explore" else None}
    (job / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    msj: dict = {}
    if purpose == "deep":
        line = line or (DEEP_PENDING if mode == "module" else SKILL_PENDING)
        (job / "report.md").write_text(_report(line, [SUB] if mode == "module" else []), encoding="utf-8")
        tdir = job / "module-skill" / "deep"
        tdir.mkdir(parents=True)
        (tdir / "timeline.md").write_text(text, encoding="utf-8")
        inputs = {"analysis.json": _sha(job / "analysis.json"), "events.json": _sha(job / "events.json"), "match.json": None}
        tl = {"path": "module-skill/deep/timeline.md", "sha256": _sha(tdir / "timeline.md"), "lines": kept, "total": total}
        if mode == "module":
            msj["deep"] = {"module": "ofono/data", "sha": SHA, "at": "x", "files": [], "timeline": tl, "inputs": inputs}
        elif mode == "skill":
            msj["deep"] = {"skill": "mock-data-analyzer", "path": "/x/SKILL.md", "sha256": "0" * 64, "at": "x", "timeline": tl,
                           "inputs": inputs}
            (job / "skill-input.json").write_text("{}", encoding="utf-8")
    else:
        (job / "report.md").write_text(_report(line or EXPLORE_PENDING, [SUB] if mode == "explore" else []), encoding="utf-8")
        (job / "explore-input.json").write_text(json.dumps({"limit": 200, "around": "2026-09-20T15:10:02Z"}), encoding="utf-8")
        plain, _k, _t = report.timeline(KEY, ev, "2026-09-20T15:10:02Z", 200)
        (job / "timeline.md").write_text(plain, encoding="utf-8")
        if mode == "explore":
            vdir = job / "module-skill" / "explore"
            vdir.mkdir(parents=True)
            (vdir / "timeline.md").write_text(text, encoding="utf-8")
            inputs = {n: _sha(job / n) for n in ("timeline.md", "events.json", "explore-input.json", "analysis.json")}
            msj["explore"] = {"module": "ofono/data", "sha": SHA, "at": "x", "files": [], "inputs": inputs,
                              "timeline": {"path": "module-skill/explore/timeline.md", "sha256": _sha(vdir / "timeline.md"),
                                           "lines": kept, "total": total}}
    if msj and record:
        (job / "module-skill.json").write_text(json.dumps(msj, ensure_ascii=False), encoding="utf-8")
    return job


def _args(job: Path, purpose: str = "deep", skipped=None, out: bool = True, key: str = KEY) -> argparse.Namespace:
    return argparse.Namespace(key=key, purpose=purpose, skipped=skipped, out=str(job) if out else None, platform=None,
                              platform_name="android", platform_cfg={"work_dir": str(job.parent)}, plugin_root=None)


def check(job: Path, purpose: str = "deep", skipped=None, out: bool = True, defaults=None, key: str = KEY, capsys=None):
    code = output.cmd_check_output(_args(job, purpose, skipped, out, key), defaults or {})
    printed = capsys.readouterr() if capsys else None
    data = json.loads(printed.out.strip().splitlines()[-1]) if printed and printed.out.strip() else None
    return code, data, (printed.err if printed else "")


def _deep_out(quotes, layer="벤더 RIL(exynos-ril) — 인증 거절", daemon="exynos-ril", against="없음",
              opinion="DATA-001-01 — 1위와 같음") -> str:
    return "\n".join([f"원인 층: {layer}", f"원인 데몬: {daemon}", "근거:", *[f"- {q}" for q in quotes],
                      f"반대 근거: {against}", f"분석 스킬 의견: {opinion}", "규칙 제안:", "- 없음", ""])


def _skill_out(quotes, summary="망이 PDN 인증을 거절했다") -> str:
    return "\n".join([f"요약: {summary}", "근거:", *[f"- {q}" for q in quotes], "분석 스킬 의견: DATA-001-01 — 1위와 같음",
                      "규칙 제안:", "- 없음", ""])


def _explore_out(hyps) -> str:
    out = []
    for i, (h, quotes) in enumerate(hyps, 1):
        out += [f"가설 {i}: {h}", "로그로 확인:", *[f"- {q}" for q in quotes], "코드로 추정: 코드 근거 없음", "반대 근거: 없음",
                "다음 확인: 망 측 거절 사유 로그"]
    return "\n".join(out) + "\n"


def _line(job: Path, prefix: str = "- 심층 분석") -> str:
    return report.current_line(job / "report.md", prefix)


def _rec(job: Path, purpose: str = "deep") -> dict:
    return json.loads((job / "check-output.json").read_text(encoding="utf-8"))[purpose]


Q1 = "15:10:01.200 p0 E exynos-ril RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"
Q2 = "drivers/rilmodem/gprs-context.c:setup_cb() activation failed"
FAKE = "ofonod: modem firmware crashed with assertion in qmi_wds_start_network handler"


# --- deep module ---------------------------------------------------------------------------------------------

def test_deep_module_renders_lines_and_record(tmp_path, capsys):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out([Q1, Q2]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0
    text = (job / "report.md").read_text(encoding="utf-8").split("\n")
    i = text.index(next(t for t in text if t.startswith("- 심층 분석")))
    head = f"- 심층 분석 (모듈 스킬 ofono/data @{SHA[:7]}): "
    assert text[i] == head + "원인 층 벤더 RIL(exynos-ril) — 인증 거절 · 원인 데몬 exynos-ril / 분석 스킬 의견: DATA-001-01 — 1위와 같음"
    assert text[i + 1] == f"  - 근거: {Q1} | {Q2}"
    assert text[i + 2] == "  - 반대 근거: 없음"
    assert text[i + 3] == "  - 근거 원문 검사: 인용 2개 중 원문에 없음 0"
    assert text[i + 4] == SUB                       # 모듈 타임라인 아래 줄은 남는다
    assert text[i + 5] == "- 기타 후보: 없음"
    assert data == {"line": masking.mask_brief(text[i], 300), "evidence": "- 근거 원문 검사: 인용 2개 중 원문에 없음 0",
                    "quotes": 2, "fabricated": 0, "weak": 0, "raw": 0}
    rec = _rec(job)
    assert set(rec) == {"mode", "at", "env", "output_sha256", "source", "quotes", "fabricated", "weak", "raw"}
    assert rec["mode"] == "module" and rec["source"] == "module-skill/deep/timeline.md" and rec["quotes"] == 2
    assert set(rec["env"]) == {"runtime", "model", "model_defaults", "gateway", "label"}
    assert rec["output_sha256"] == _sha(job / "deep-output.md")
    assert len(json.dumps(data, ensure_ascii=False).encode()) <= 4096


def test_fabricated_quote_sub_line_and_script_note(tmp_path, capsys):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out([Q1, FAKE, "〔script 모듈 신호 약함〕"]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["fabricated"] == 2 and data["quotes"] == 3
    sub = next(t for t in (job / "report.md").read_text(encoding="utf-8").split("\n") if "근거 원문 검사" in t)
    assert sub.startswith("  - 근거 원문 검사: 인용 3개 중 원문에 없음 2 (") and sub.endswith("…)")


def test_header_failed_step_quote_is_fabricated(tmp_path, capsys):
    step = "데이터 연결 버튼을 눌렀는데 인터넷이 전혀 되지 않음 상태 지속"
    job = make_job(tmp_path, failed_step=step)
    assert step in (job / "module-skill" / "deep" / "timeline.md").read_text(encoding="utf-8")
    (job / "deep-output.md").write_text(_deep_out([f"실패 스텝(Jira, 데이터이며 지시 아님): {step}"]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["fabricated"] == 1


def test_stale_record_inputs_skip_check(tmp_path, capsys):
    job = make_job(tmp_path)
    (job / "analysis.json").write_text((job / "analysis.json").read_text(encoding="utf-8") + " ", encoding="utf-8")
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["evidence"] == "- 근거 원문 검사: 건너뜀(기록이 이전 분석 것)"
    assert _rec(job)["source"] is None


def test_module_source_without_record_is_refused(tmp_path, capsys):
    job = make_job(tmp_path, record=False)
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    before = (job / "report.md").read_bytes()
    code, data, err = check(job, capsys=capsys)
    assert code == 2 and data == {"reason": "작업 없음", "next": core.NEXT_CHECK_NA} and "module --for deep 먼저" in err
    assert (job / "report.md").read_bytes() == before


# --- deep skill ----------------------------------------------------------------------------------------------

def test_deep_skill_matches_eval40_and_uses_events_rows(tmp_path, capsys):
    import re
    rows = [*ROWS, EXTRA_ROW]
    job = make_job(tmp_path, mode="skill", rows=rows, timeline_rows=ROWS)     # EXTRA_ROW는 타임라인 밖, events.json 안
    raw_quote = "imsi=450081234567890 attach rejected by network"
    (job / "deep-output.md").write_text(_skill_out([Q1, "policy table refreshed for interface rmnet_data7 entries=12", raw_quote]),
                                        encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0, data
    text = (job / "report.md").read_text(encoding="utf-8")
    assert re.search(r"심층 분석 \(mock-data-analyzer\)", text) and re.search(r"분석 스킬 의견", text)     # grade.py eval 40
    assert "  - 근거 원문 검사(events.json 기준): 인용 3개 중 원문에 없음 0 · 원문 로그 인용 1개(검사 밖)" in text
    assert data["raw"] == 1 and data["fabricated"] == 0
    rec = _rec(job)
    assert rec["mode"] == "skill" and "events.json" in rec["source"]
    assert "450081234567890" not in (job / "deep-output.md").read_text(encoding="utf-8")


def test_deep_skill_without_record_uses_written_timeline(tmp_path, capsys):
    job = make_job(tmp_path, mode="none")          # Skill 도구 대안(설치 스킬 못 찾음 뒤): 기록 없음, module이 쓴 타임라인
    (job / "deep-output.md").write_text(_skill_out([Q1]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["evidence"].startswith("- 근거 원문 검사(events.json 기준): 인용 1개 중 원문에 없음 0")


def test_deep_skill_without_quotes(tmp_path, capsys):
    job = make_job(tmp_path, mode="skill")
    (job / "deep-output.md").write_text(_skill_out([]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["evidence"] == "- 근거 원문 검사(events.json 기준): 건너뜀(인용 없음)"


# --- explore -------------------------------------------------------------------------------------------------

def test_explore_view_source_and_render(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "explore")
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1, Q2]), ("APN 설정 오류", [Q2])]), encoding="utf-8")
    code, _data, _ = check(job, "explore", capsys=capsys)
    assert code == 0
    text = (job / "report.md").read_text(encoding="utf-8").split("\n")
    i = text.index(next(t for t in text if t.startswith("- 탐색 분석")))
    assert text[i] == "- 탐색 분석 (추정, timeline.md 4/4줄): 가설 2개 — 점수·분류·검증에 쓰지 않는다"
    assert text[i + 1] == (f"  - 가설 1: 망 인증 거절 / 로그로 확인: {Q1} | {Q2} / 코드로 추정: 코드 근거 없음 / 반대 근거: 없음 / "
                           "다음 확인: 망 측 거절 사유 로그")
    assert text[i + 3] == "  - 근거 원문 검사: 인용 3개 중 원문에 없음 0" and text[i + 4] == SUB
    assert _rec(job, "explore")["source"] == "module-skill/explore/timeline.md"


def test_explore_source_falls_back_to_job_timeline(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    assert check(job, "explore", capsys=capsys)[0] == 0
    assert _rec(job, "explore")["source"] == "timeline.md"
    other = make_job(tmp_path / "b", "explore", "plain")
    (other / "timeline.md").unlink()
    (other / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    code, data, _ = check(other, "explore", capsys=capsys)
    assert code == 0 and data["evidence"] == "- 근거 원문 검사: 건너뜀(타임라인 없음)"


def test_explore_none_form_and_hypothesis_cap(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text("가설 없음: 실패 구간 로그가 없다\n다음 확인: 실패 시각 앞뒤 30초 로그\n", encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0
    assert _line(job, "- 탐색 분석") == ("- 탐색 분석 (추정, timeline.md 4/4줄): 가설 없음: 실패 구간 로그가 없다 / "
                                        "다음 확인: 실패 시각 앞뒤 30초 로그")
    assert data["evidence"] == "- 근거 원문 검사: 건너뜀(인용 없음)"
    four = make_job(tmp_path / "b", "explore", "plain")
    (four / "explore-output.md").write_text(_explore_out([(f"가설{i}", [Q1]) for i in range(4)]), encoding="utf-8")
    code, data, _ = check(four, "explore", capsys=capsys)
    assert code == 1 and data == {"reason": "출력 형식 불일치", "detail": "출력 형식 불일치(가설 한도)", "next": core.NEXT_CHECK_FAILED}
    assert _line(four, "- 탐색 분석") == "- 탐색 분석 생략: 출력 형식 불일치(가설 한도)"


# --- 형식·한도·마스킹 실패 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("body, detail", [
    ("원인 층만 썼다\n", "출력 형식 불일치(칸)"),
    (_deep_out([]), "출력 형식 불일치(근거 한도)"),
    (_deep_out([Q1] * 6), "출력 형식 불일치(근거 한도)"),
    (_deep_out([Q1], against="가" * 300), "출력 형식 불일치(반대 근거 한도)"),
    (_deep_out([Q1], opinion="x" * 769), "출력 형식 불일치(분석 스킬 의견 한도)"),
])
def test_cap_violation_writes_skipped_line(tmp_path, capsys, body, detail):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(body, encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 1 and data == {"reason": "출력 형식 불일치", "detail": detail, "next": core.NEXT_CHECK_FAILED}
    assert _line(job) == f"- 심층 분석 생략: {detail}"
    assert SUB not in (job / "report.md").read_text(encoding="utf-8")
    assert _rec(job)["error"] == detail


def test_byte_caps_korean(tmp_path, capsys):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out([Q1], against="가" * 250), encoding="utf-8")   # 750B
    assert check(job, capsys=capsys)[0] == 0
    big = make_job(tmp_path / "b")
    (big / "deep-output.md").write_text(_deep_out([Q1], against="가" * 300), encoding="utf-8")   # 900B
    assert check(big, capsys=capsys)[0] == 1
    whole = make_job(tmp_path / "c")
    (whole / "deep-output.md").write_text(_deep_out([Q1]) + "규칙 제안 메모 " * 600, encoding="utf-8")
    code, data, _ = check(whole, capsys=capsys)
    assert code == 1 and data["detail"] == "출력 형식 불일치(전체 한도)"


def test_residual_hit_is_masking_failure(tmp_path, capsys, monkeypatch):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    monkeypatch.setattr(masking, "residual", lambda text, allow=(), **kw: {"IMSI": 1})
    code, data, _ = check(job, capsys=capsys)
    assert code == 1 and data == {"reason": "마스킹 점검 실패", "detail": "마스킹 점검 실패(IMSI 1건)", "next": core.NEXT_CHECK_FAILED}
    assert _line(job) == "- 심층 분석 생략: 마스킹 점검 실패(IMSI 1건)"


def test_output_file_rewritten_masked(tmp_path, capsys):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out([Q1], against="imsi=450081234567890 가입자 문제 아님"), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    body = (job / "deep-output.md").read_text(encoding="utf-8")
    assert code == 0 and "450081234567890" not in body and "<IMSI#" in body
    assert _rec(job)["output_sha256"] == _sha(job / "deep-output.md")
    assert "450081234567890" not in (job / "report.md").read_text(encoding="utf-8")


def test_module_mode_raw_value_quote_counts_fabricated(tmp_path, capsys):
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out(["imsi=450081234567890 attach rejected by network side"]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["fabricated"] == 1 and data["raw"] == 0


def test_allow_listed_value_is_not_fabricated(tmp_path, capsys):
    imsi = "00101" + "0123456789"          # 시험망 IMSI(허용 목록), 경계 점검의 15자리 숫자 규칙을 피해 나눠 쓴다
    rows = [*ROWS, ("2026-09-20T15:10:04.000Z", "ofonod", "I", f"test sim imsi={imsi} registered on home network")]
    job = make_job(tmp_path, rows=rows, allow=[r"00101\d{10}"])
    (job / "deep-output.md").write_text(_deep_out([f"test sim imsi={imsi} registered on home network"]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and data["fabricated"] == 0
    assert imsi in (job / "deep-output.md").read_text(encoding="utf-8")


# --- --skipped -----------------------------------------------------------------------------------------------

def test_skipped_masks_and_records(tmp_path, capsys):
    job = make_job(tmp_path)
    code, data, _ = check(job, skipped="분석 스킬이 imsi=450081234567890 에서 멈춤", capsys=capsys)
    assert code == 0 and "450081234567890" not in json.dumps(data, ensure_ascii=False)
    assert _line(job).startswith("- 심층 분석 생략: 분석 스킬이 imsi=<IMSI#1>")
    assert SUB not in (job / "report.md").read_text(encoding="utf-8")
    rec = _rec(job)
    assert set(rec) == {"skipped", "at", "env"}


def test_skipped_keeps_script_written_line(tmp_path, capsys):
    job = make_job(tmp_path, line=core.DEEP_FETCH_FAILED.format(reason="인증"))
    before = (job / "report.md").read_bytes()
    code, data, _ = check(job, skipped="설치 스킬 못 찾음", capsys=capsys)
    assert code == 0 and data == {"kept": "- 심층 분석 생략: 모듈 스킬 받기 실패(인증)"}
    assert (job / "report.md").read_bytes() == before and not (job / "check-output.json").exists()


# --- 전제 조건·종료표 ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("purpose, analyzer, explore_when", [
    ("deep", {"error": "analyzers.data.prefer: …", "when": "never"}, None),
    ("deep", {"skill": "mock-data-analyzer", "when": "never"}, None),
    ("deep", "none", None),
    ("explore", None, "never"),
])
def test_precondition_not_met_leaves_report(tmp_path, capsys, purpose, analyzer, explore_when):
    job = make_job(tmp_path, purpose, "module" if purpose == "deep" else "plain")
    data = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    if purpose == "deep":
        data["analyzer"] = None if analyzer == "none" else analyzer
    else:
        data["explore"]["when"] = explore_when
    (job / "analysis.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (job / OUTPUT_FILE(purpose)).write_text("x", encoding="utf-8")
    before = (job / "report.md").read_bytes()
    code, out, _ = check(job, purpose, capsys=capsys)
    assert code == 2 and out == {"reason": "작업 없음", "next": core.NEXT_CHECK_NA}
    assert (job / "report.md").read_bytes() == before


def OUTPUT_FILE(purpose):        # noqa: N802
    return output.OUTPUT_FILE[purpose]


def test_stale_module_record_with_fetch_failed_line_unchanged(tmp_path, capsys):
    job = make_job(tmp_path, line=core.DEEP_FETCH_FAILED.format(reason="인증"))
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    before = (job / "report.md").read_bytes()
    code, out, _ = check(job, capsys=capsys)
    assert code == 2 and out["next"] == core.NEXT_CHECK_NA and (job / "report.md").read_bytes() == before


def _link_output(job):
    target = job.parent / "elsewhere.md"
    target.write_text(_deep_out([Q1]), encoding="utf-8")
    os.symlink(target, job / "deep-output.md")


def _link_report(job):
    target = job.parent / "r.md"
    target.write_text((job / "report.md").read_text(encoding="utf-8"), encoding="utf-8")
    (job / "report.md").unlink()
    os.symlink(target, job / "report.md")


EXIT_TABLE = [   # (설정, 종료, reason, next) — next None = 멈춤(R20)
    ("bad_key", 2, "사용 오류", None),
    ("no_job", 2, "작업 없음", None),
    ("no_report", 2, "작업 없음", None),
    ("report_link", 2, "작업 디렉토리 이상", core.NEXT_CHECK_NA),
    ("no_output", 2, "작업 없음", core.NEXT_CHECK_NA),
    ("output_link", 2, "작업 디렉토리 이상", core.NEXT_CHECK_NA),
    ("format", 1, "출력 형식 불일치", core.NEXT_CHECK_FAILED),
    ("ok", 0, None, None),
]


@pytest.mark.skipif(os.name == "nt", reason="symlink")
@pytest.mark.parametrize("case, code, reason, nxt", EXIT_TABLE)
def test_exit_table(tmp_path, capsys, case, code, reason, nxt):
    job = make_job(tmp_path)
    key = KEY
    if case != "no_output":
        (job / "deep-output.md").write_text(_deep_out([Q1]) if case != "format" else "x\n", encoding="utf-8")
    if case == "bad_key":
        key = "../evil"
    elif case == "no_job":
        job = tmp_path / "missing"
    elif case == "no_report":
        (job / "report.md").unlink()
    elif case == "report_link":
        _link_report(job)
    elif case == "output_link":
        (job / "deep-output.md").unlink()
        _link_output(job)
    got, data, _ = check(job, key=key, capsys=capsys)
    assert got == code
    if reason is None:
        assert "reason" not in data
    else:
        assert data["reason"] == reason and data.get("next") == nxt


# --- 표시 의무·출처 ------------------------------------------------------------------------------------------------

def _shown(work: Path) -> list[dict]:
    path = work / shown.SHOWN_DIR / shown.LOG_NAME
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_evidence_record_on_work_dir_job(tmp_path, capsys, monkeypatch):
    work = tmp_path / "work"
    job = make_job(work)
    (job / "deep-output.md").write_text(_deep_out([Q1, FAKE]), encoding="utf-8")
    assert check(job, out=False, capsys=capsys)[0] == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    assert len(recs) == 1 and recs[0]["key"] == f"evidence:{KEY}/deep" and recs[0]["job"] == KEY
    assert recs[0]["lines"][0].startswith("- 근거 원문 검사: 인용 2개 중 원문에 없음 1") and recs[0]["path"] == str(job / "report.md")
    # 고쳐 다시(같은 턴): 줄을 다시 TODO로 두고 맞는 인용으로 → lines=[] 기록이 앞 의무를 닫는다
    rows = (job / "report.md").read_text(encoding="utf-8").split("\n")
    i = next(k for k, t in enumerate(rows) if t.startswith("- 심층 분석"))
    rows[i:i + 4] = [DEEP_PENDING]
    (job / "report.md").write_text("\n".join(rows), encoding="utf-8")
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    assert check(job, out=False, capsys=capsys)[0] == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    assert len(recs) == 2 and recs[1]["lines"] == []
    # 같은 key의 두 기록을 순서대로 고정하면(첫 기록 = 열린 의무, 둘째 = 빈 줄) 열린 의무가 없다
    seq = [{"kind": "tool", "name": "Bash", "id": f"b{k}", "input": {"command": f"python3 triage.py check-output {KEY} --for deep"},
            "result": "{}", "error": False} for k in range(2)]
    monkeypatch.setattr(shown, "anchor", lambda s, r: list(enumerate(r)))
    assert [ob.kind for ob in shown.record_obligations(seq, recs[:1]) if ob.open] == ["evidence"]
    out = shown.record_obligations(seq, recs)
    assert [ob for ob in out if ob.open] == []


def test_weak_only_records_empty_lines_and_out_job_records_nothing(tmp_path, capsys):
    work = tmp_path / "work"
    job = make_job(work)
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    assert check(job, out=False, capsys=capsys)[0] == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    assert len(recs) == 1 and recs[0]["lines"] == []
    other = make_job(tmp_path / "o")
    (other / "deep-output.md").write_text(_deep_out([Q1, FAKE]), encoding="utf-8")
    assert check(other, capsys=capsys)[0] == 0
    assert not (tmp_path / "o" / shown.SHOWN_DIR).exists()


def test_runtime_label_from_site_defaults(tmp_path, capsys, monkeypatch):
    """R23: env_info는 site-defaults dict를 받는다 → check-output.json[purpose].env.label."""
    job = make_job(tmp_path)
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    seen = {}
    real = provenance.env_info

    def spy(environ=None, cfg=None):
        seen["cfg"] = cfg
        return real({}, cfg)
    monkeypatch.setattr(provenance, "env_info", spy)
    assert check(job, defaults={"runtime": {"label": "cc-internal"}}, capsys=capsys)[0] == 0
    assert _rec(job)["env"]["label"] == "cc-internal" and seen["cfg"] == {"runtime": {"label": "cc-internal"}}
    assert "http" not in json.dumps(_rec(job), ensure_ascii=False)


def test_evidence_parsers_used_are_the_shared_ones():
    assert output.evidence is evidence and evidence.FIELDS_DEEP[0] == "원인 층"
