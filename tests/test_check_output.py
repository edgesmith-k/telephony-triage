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
        ("2026-09-20T15:10:01.200Z", "vrild", "E", "RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"),
        ("2026-09-20T15:10:02.300Z", "ofonod", "W", "drivers/rilmodem/gprs-context.c:setup_cb() activation failed"),
        ("2026-09-20T15:10:03.400Z", "datad", "I", "network manager daemon state=disconnected reason=pdn_reject")]
EXTRA_ROW = ("2026-09-20T15:20:09.000Z", "datad2", "I", "policy table refreshed for interface rmnet_data7 entries=12")


def _events(rows=ROWS, allow=(), mask_off=False) -> dict:
    return {"events": [{"ts": ts, "tag": tag, "level": lv, "msg": msg, "phone_id": 0, "event": None} for ts, tag, lv, msg in rows],
            "input": {"window": {"start": "2026-09-20T15:00:00Z", "end": "2026-09-20T15:30:00Z"}}, "mask_allow": list(allow),
            **({"mask_off": True} if mask_off else {})}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _report(line: str, sub: list[str] = ()) -> str:
    return "\n".join(["# MOCK-9076 분석 리포트", "", "- 분류 후보: DATA-001-01", line, *sub, "- 기타 후보: 없음", ""])


def make_job(base: Path, purpose: str = "deep", mode: str = "module", line: str | None = None, *, analyzer=None,
             rows=ROWS, timeline_rows=None, allow=(), record: bool = True, failed_step: str | None = None,
             mask_off: bool = False) -> Path:
    """JOB 하나. mode: module(모듈 기록) | skill(설치 스킬 기록) | none(기록 없음) | explore(뷰 기록) | plain(JOB/timeline.md만)."""
    job = base / KEY
    job.mkdir(parents=True)
    ev = _events(rows, allow, mask_off)
    (job / "events.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
    tl_ev = _events(timeline_rows if timeline_rows is not None else rows, allow, mask_off)
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


def _deep_out(quotes, layer="벤더 RIL(vrild) — 인증 거절", daemon="vrild", against="없음",
              opinion="DATA-001-01 — 1위와 같음") -> str:
    return "\n".join([f"원인 층: {layer}", f"원인 데몬: {daemon}", "근거:", *[f"- {q}" for q in quotes],
                      f"반대 근거: {against}", f"분석 스킬 의견: {opinion}", "규칙 제안:", "- 없음", ""])


def _skill_out(quotes, summary="망이 PDN 인증을 거절했다") -> str:
    return "\n".join([f"요약: {summary}", "근거:", *[f"- {q}" for q in quotes], "분석 스킬 의견: DATA-001-01 — 1위와 같음",
                      "규칙 제안:", "- 없음", ""])


CHAIN_OK = ("기대 체인:", "| 단계 | 기대 | 기대 근거 | 관측 줄 | 일치 |", "|---|---|---|---|---|",
            "| 1 | 망이 PDN을 받아 준다 | spec:3GPP 24.301 | 없음(찾은 곳: 타임라인 전체) | 모름 |")


def _explore_out(hyps, chain=CHAIN_OK) -> str:
    """가설 블록들. 기대 체인(11/25)은 가설마다 붙인다 — 형식 경고 없는 출력(`chain=()`면 옛 형식)."""
    out = []
    for i, (h, quotes) in enumerate(hyps, 1):
        out += [f"가설 {i}: {h}", "로그로 확인:", *[f"- {q}" for q in quotes], "코드로 추정: 코드 근거 없음", "반대 근거: 없음",
                "다음 확인: 망 측 거절 사유 로그", *chain]
    return "\n".join(out) + "\n"


def _line(job: Path, prefix: str = "- 심층 분석") -> str:
    return report.current_line(job / "report.md", prefix)


def _rec(job: Path, purpose: str = "deep") -> dict:
    return json.loads((job / "check-output.json").read_text(encoding="utf-8"))[purpose]


Q1 = "15:10:01.200 p0 E vrild RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"
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
    assert text[i] == head + "원인 층 벤더 RIL(vrild) — 인증 거절 · 원인 데몬 vrild / 분석 스킬 의견: DATA-001-01 — 1위와 같음"
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


def test_altered_quote_head_counts_weak_not_fabricated(tmp_path, capsys):
    # F-A01-min: 메시지는 원문 그대로인데 시각·슬롯을 바꿔 적은 인용은 기존 약함 칸으로 센다(원문에 없음 0)
    job = make_job(tmp_path)
    altered = [Q1.replace("p0", "p1", 1), Q1.replace("15:10:01.200", "15:10:09.200", 1)]
    (job / "deep-output.md").write_text(_deep_out([Q1, *altered, Q2]), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and (data["quotes"], data["fabricated"], data["weak"]) == (4, 0, 2)
    assert data["evidence"] == "- 근거 원문 검사: 인용 4개 중 원문에 없음 0 · 약함 2"
    assert _rec(job)["weak"] == 2


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


def test_explore_hypothesis_line_marks_fabricated_count(tmp_path, capsys):
    """코덱스 리뷰 02e0ec2 Q01: 가설 줄에 그 가설의 원문에 없는 인용 수 `[근거 불일치 N]`(0이면 표기 없음). 종료·기록은 그대로."""
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1]), ("모뎀 펌웨어 오류", [Q1, FAKE])]),
                                           encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and data["fabricated"] == 1
    text = (job / "report.md").read_text(encoding="utf-8").split("\n")
    i = text.index(next(t for t in text if t.startswith("- 탐색 분석")))
    assert text[i + 1].startswith("  - 가설 1: 망 인증 거절 / 로그로 확인: ")
    assert text[i + 2].startswith("  - 가설 2 [근거 불일치 1]: 모뎀 펌웨어 오류 / 로그로 확인: ")
    assert text[i + 3].startswith("  - 근거 원문 검사: 인용 3개 중 원문에 없음 1 (")
    assert _rec(job, "explore")["fabricated"] == 1


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


def test_mask_off_events_leave_output_and_timeline_unmasked(tmp_path, capsys):
    """마스킹 끔 DB의 events(`mask_off`, 08-safety §8): 출력을 다시 가리지 않고 남은 식별자 점검도 하지 않는다. 타임라인 머리말에 "마스킹된"이 없다."""
    job = make_job(tmp_path, mask_off=True)
    body = _deep_out([Q1], against="imsi=310260" + "000000000 가입자 문제 아님")
    (job / "deep-output.md").write_text(body, encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and (job / "deep-output.md").read_text(encoding="utf-8") == body, data
    head = (job / "module-skill" / "deep" / "timeline.md").read_text(encoding="utf-8").split("\n")[2]
    assert head.startswith("- 이벤트 요약이다(원문 로그 아님)"), head


def test_mask_off_emitted_line_equals_report_line(tmp_path, capsys):
    """11/15 리뷰 D2-02: 마스킹 끔 DB에서는 돌려주는 줄(`line`, 꼭 보일 줄 기록)도 다시 가리지 않는다 — report.md 줄과 같은 글자."""
    job = make_job(tmp_path, mask_off=True)
    (job / "deep-output.md").write_text(_deep_out([Q1], layer="벤더 RIL(vrild) — APN 10.20.30.40 인증 거절"), encoding="utf-8")
    code, data, _ = check(job, capsys=capsys)
    assert code == 0 and "10.20.30.40" in _line(job) and data["line"] == _line(job), data


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


def test_trace_checked_row_only_when_trace_exists(tmp_path, capsys):
    # F7 확장: trace가 있을 때만 정보 행 `checked`(purpose·skipped 여부·종료 코드). 사유 글은 싣지 않는다
    job = make_job(tmp_path)
    assert check(job, skipped="첫 사유", capsys=capsys)[0] == 0 and not (job / "trace.jsonl").exists()
    (job / "trace.jsonl").write_text("", encoding="utf-8")
    assert check(job, skipped="SECRET-REASON", capsys=capsys)[0] == 0
    text = (job / "trace.jsonl").read_text(encoding="utf-8")
    assert "SECRET-REASON" not in text
    assert [{k: v for k, v in json.loads(x).items() if k != "ts"} for x in text.splitlines()] == [
        {"step": "checked", "v": 2, "purpose": "deep", "skipped": True, "exit": 0}]


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
    code, data, _ = check(job, out=False, capsys=capsys)
    assert code == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    assert len(recs) == 1 and recs[0]["key"] == f"evidence:{KEY}/deep" and recs[0]["job"] == KEY
    # 심층 분석: 첫 줄 = 결과 줄(낸 "line"과 같은 글, 끝 "…" 없이), 지어낸 인용이 있으면 근거 원문 검사 줄이 뒤에
    assert recs[0]["lines"][0] == data["line"].removesuffix("…") and recs[0]["lines"][0].startswith("- 심층 분석 (모듈 스킬")
    assert recs[0]["lines"][1].startswith("- 근거 원문 검사: 인용 2개 중 원문에 없음 1") and recs[0]["path"] == str(job / "report.md")
    assert len(recs[0]["lines"]) == 2
    # 고쳐 다시(같은 턴): 줄을 다시 TODO로 두고 맞는 인용으로 → 결과 줄만 든 새 의무(내용이 달라 앞 의무를 갈음한다)
    rows = (job / "report.md").read_text(encoding="utf-8").split("\n")
    i = next(k for k, t in enumerate(rows) if t.startswith("- 심층 분석"))
    rows[i:i + 4] = [DEEP_PENDING]
    (job / "report.md").write_text("\n".join(rows), encoding="utf-8")
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    code, data2, _ = check(job, out=False, capsys=capsys)
    assert code == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    # RP-14: 앞 검사의 원문에 없는 인용(1)은 고친 뒤에도 보일 의무에 남는다(근거 검사 줄 끝 "앞 검사 원문에 없음 1")
    assert len(recs) == 2 and recs[1]["lines"] == [data2["line"].removesuffix("…"), data2["evidence"]]
    assert data2["evidence"].endswith(output.FAB_BEFORE.format(n=1))
    # 같은 key의 두 기록을 순서대로 고정하면 열린 의무는 둘째(결과 줄) 하나다
    seq = [{"kind": "tool", "name": "Bash", "id": f"b{k}", "input": {"command": f"python3 triage.py check-output {KEY} --for deep"},
            "result": "{}", "error": False} for k in range(2)]
    monkeypatch.setattr(shown, "anchor", lambda s, r: list(enumerate(r)))
    assert [ob.kind for ob in shown.record_obligations(seq, recs[:1]) if ob.open] == ["evidence"]
    out = [ob for ob in shown.record_obligations(seq, recs) if ob.open]
    assert len(out) == 1 and out[0].start == 1 and out[0].lines == recs[1]["lines"]


def test_weak_only_records_head_line_and_out_job_records_nothing(tmp_path, capsys):
    work = tmp_path / "work"
    job = make_job(work)
    (job / "deep-output.md").write_text(_deep_out([Q1]), encoding="utf-8")
    code, data, _ = check(job, out=False, capsys=capsys)
    assert code == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    assert len(recs) == 1 and recs[0]["lines"] == [data["line"].removesuffix("…")]
    other = make_job(tmp_path / "o")
    (other / "deep-output.md").write_text(_deep_out([Q1, FAKE]), encoding="utf-8")
    assert check(other, capsys=capsys)[0] == 0
    assert not (tmp_path / "o" / shown.SHOWN_DIR).exists()


def test_long_deep_head_line_recorded_without_ellipsis(tmp_path, capsys):
    work = tmp_path / "work"
    job = make_job(work)
    (job / "deep-output.md").write_text(_deep_out([Q1], opinion="DATA-001-01 — " + "가" * 200), encoding="utf-8")
    code, data, _ = check(job, out=False, capsys=capsys)
    assert code == 0 and data["line"].endswith("…") and len(data["line"]) == 300
    rec = next(r for r in _shown(work) if r["kind"] == "evidence")
    assert rec["lines"] == [data["line"][:-1]]


def test_explore_clean_records_empty_lines_but_fabricated_records_sub(tmp_path, capsys):
    """탐색은 결과 줄 의무가 없다 — 지어낸 인용이 있을 때만 근거 원문 검사 줄."""
    work = tmp_path / "work"
    job = make_job(work, "explore", "plain")
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    assert check(job, "explore", out=False, capsys=capsys)[0] == 0
    recs = [r for r in _shown(work) if r["kind"] == "evidence"]
    assert len(recs) == 1 and recs[0]["key"] == f"evidence:{KEY}/explore" and recs[0]["lines"] == []
    other = make_job(tmp_path / "b", "explore", "plain")
    (other / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1, FAKE])]), encoding="utf-8")
    assert check(other, "explore", out=False, capsys=capsys)[0] == 0
    recs = [r for r in _shown(tmp_path / "b") if r["kind"] == "evidence"]
    assert len(recs) == 1 and len(recs[0]["lines"]) == 1 and recs[0]["lines"][0].startswith("- 근거 원문 검사")


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


# --- 단계 4 판단(decision) 고치기 ---------------------------------------------------------------------------

ACCEPTED = {"state": "accepted", "reason": "anchored_top",
            "selected": {"category": "data", "type": "DATA-001", "cause": "DATA-001-01"},
            "location": {"state": "confirmed", "source": "look_at", "kind": "point"}}


# analysis 스키마 `ok`의 필수 키(합성 JOB을 완전한 run 출력으로 만들 때)
OK_KEYS = {"status": "ok", "generated_at": "2026-09-20T06:00:00+00:00", "request_hash": "0123456789abcdef", "mode": "offline",
           "logs": {"files": ["a.log"], "range": ["t0", "t1"], "in_range": True, "events": 4}, "code": {"skipped": True},
           "files": {"report": "r"}, "truncated": False,
           "candidates": [{"type": "DATA-001", "cause": "DATA-001-01", "category": "data", "score": 1.0, "confidence": "high",
                           "S": 1, "C": 1, "evidence": []}]}


def _decision_job(base: Path, decision=ACCEPTED, full: bool = False) -> Path:
    """탐색 모듈 기록(입력 해시에 analysis.json)이 있는 JOB에 심층 분석(설치 스킬)·판단을 더한다 — 둘 다 TODO 줄.
    full이면 analysis.json이 스키마 `ok`의 필수 키를 다 갖춘 run 출력이다(판단만 스키마를 어길 수 있게)."""
    job = make_job(base, "explore", "explore")
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    analysis.update(analyzer={"skill": "mock-data-analyzer", "when": "ask"}, **({"decision": decision} if decision else {}),
                    **(OK_KEYS if full else {}))
    (job / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    msj = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    msj["explore"]["inputs"]["analysis.json"] = _sha(job / "analysis.json")
    (job / "module-skill.json").write_text(json.dumps(msj, ensure_ascii=False), encoding="utf-8")
    (job / "report.md").write_text("\n".join(["# MOCK-9076 분석 리포트", "", report.decision_line(decision or ACCEPTED, [{}]),
                                              "- 분류 후보: DATA-001-01", SKILL_PENDING, EXPLORE_PENDING, SUB,
                                              "- 기타 후보: 없음", ""]), encoding="utf-8")
    return job


def test_opinion_id_shapes():
    m = lambda s: (output.OPINION_ID.match(s) or [None, None])[1]     # noqa: E731
    assert m("DATA-001-02 — 망 거절") == "DATA-001-02" and m("  `DATA-001-02` — x") == "DATA-001-02"
    assert m("**DATA-001-02** — x") == "DATA-001-02" and m("DATA-001-02와 같은 망 거절") == "DATA-001-02"
    assert m("DATA-001-021 — x") is None and m("1위와 같음") is None and m("해당 없음(후보 없음)") is None


def test_deep_counter_rebases_module_inputs_so_later_explore_check_uses_its_view(tmp_path, capsys, monkeypatch):
    """P2-1: 섞인 순서(module --for explore → check-output deep이 counter로 analysis.json을 다시 씀 → check-output explore)에서
    탐색 기록의 입력 해시를 새 analysis.json으로 옮겨, 탐색 검사가 기록한 모듈 보기로 근거를 검사한다(건너뛰거나 다른 원문 아님)."""
    monkeypatch.delenv("TT_SCHEMA_CHECK")          # 합성 analysis.json(필수 키 없음)이라 스키마 검사는 끈다
    job = _decision_job(tmp_path)
    before = _sha(job / "analysis.json")
    (job / "deep-output.md").write_text(_skill_out([Q1]).replace("DATA-001-01 — 1위와 같음", "**DATA-001-02** — 망 거절"),
                                        encoding="utf-8")
    code, _, err = check(job, "deep", capsys=capsys)
    assert code == 0 and "판단" not in err, err
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["decision"] == {**ACCEPTED, "counter": {"cause": "DATA-001-02"}}
    after = _sha(job / "analysis.json")
    assert after != before
    msj = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    assert msj["explore"]["inputs"]["analysis.json"] == after
    assert _line(job, "- 판단:").endswith("· 모델 검토 의견이 다름(DATA-001-02) — 확인 필요")
    assert "decision_unwritten" not in _rec(job, "deep")
    (job / "explore-output.md").write_text(_explore_out([("망 거절", [Q2])]), encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and data["fabricated"] == 0 and _rec(job, "explore")["source"] == "module-skill/explore/timeline.md"


def test_decision_not_written_on_schema_violation_or_changed_file(tmp_path, capsys, monkeypatch):
    """P2-2·P2-3: 판단이 불변식을 어기거나(TT_SCHEMA_CHECK — 완전한 run 출력에 accepted인데 selected null) 검사 중 analysis.json이
    바뀌었으면 쓰지 않고 경고, 기록에 `decision_unwritten`. report.md 판단 줄도 그대로. module-skill.json 해시를 못 고치면
    판단은 쓰고 `module_inputs_unwritten`."""
    sound = json.loads((_decision_job(tmp_path / "ok", full=True) / "analysis.json").read_text(encoding="utf-8"))
    assert report.schema_violation(sound) is None                       # 판단만 바꾸면 위반이 되는 완전한 출력
    job = _decision_job(tmp_path / "bad", decision={**ACCEPTED, "selected": None}, full=True)
    raw = (job / "analysis.json").read_bytes()
    judge = _line(job, "- 판단:")
    (job / "deep-output.md").write_text(_skill_out([Q1]).replace("DATA-001-01 — 1위와 같음", "DATA-001-02 — 망 거절"),
                                        encoding="utf-8")
    code, _, err = check(job, "deep", capsys=capsys)
    assert code == 0 and "판단(decision)을 고치지 못했다" in err and "decision" in err, err
    assert (job / "analysis.json").read_bytes() == raw and _line(job, "- 판단:") == judge
    assert _rec(job, "deep")["decision_unwritten"] == "스키마 위반"
    # 처음 읽은 뒤 바뀐 파일: 쓰지 않는다
    job = _decision_job(tmp_path / "race", full=True)
    raw = (job / "analysis.json").read_bytes()
    analysis = json.loads(raw)
    (job / "analysis.json").write_text(json.dumps({**analysis, "truncated": True}), encoding="utf-8")
    changed = (job / "analysis.json").read_bytes()
    out = output._decision_update(_args(job, "deep"), job, analysis, hashlib.sha256(raw).hexdigest(), opinion="DATA-001-02 — x")
    assert out == {"decision_unwritten": "검사 중 analysis.json이 바뀌었다"} and (job / "analysis.json").read_bytes() == changed
    # module-skill.json 해시 갱신 실패: 판단은 쓰고 따로 남긴다
    (job / "analysis.json").write_bytes(raw)
    monkeypatch.setattr(output, "_rebase_module_inputs", lambda *a: False)
    out = output._decision_update(_args(job, "deep"), job, analysis, hashlib.sha256(raw).hexdigest(), opinion="DATA-001-02 — x")
    assert out == {"module_inputs_unwritten": True}
    assert json.loads((job / "analysis.json").read_text(encoding="utf-8"))["decision"]["counter"] == {"cause": "DATA-001-02"}


def test_old_job_without_decision_leaves_analysis_untouched(tmp_path, capsys, monkeypatch):
    """decision 없는 옛 JOB: 심층 의견이 달라도 check-output은 analysis.json·판단 줄을 건드리지 않는다(기록도 없음)."""
    monkeypatch.delenv("TT_SCHEMA_CHECK")
    job = _decision_job(tmp_path, decision=None)
    raw, msj = (job / "analysis.json").read_bytes(), (job / "module-skill.json").read_bytes()
    (job / "deep-output.md").write_text(_skill_out([Q1]).replace("DATA-001-01 — 1위와 같음", "DATA-001-02 — 망 거절"),
                                        encoding="utf-8")
    code, _, err = check(job, "deep", capsys=capsys)
    assert code == 0 and "판단" not in err
    assert (job / "analysis.json").read_bytes() == raw and (job / "module-skill.json").read_bytes() == msj
    assert "decision_unwritten" not in _rec(job, "deep")


# -- sim1122 F7·F9: 확인할 내용 줄 꼬리, 다시 검사해도 남는 근거 불일치 --------------------------------------------

QUESTION = "- 확인할 내용(사용자 질문): 재시도가 오는지"


def _question_job(base: Path) -> Path:
    job = make_job(base, "explore", "plain")
    text = (job / "report.md").read_text(encoding="utf-8")
    text = text.replace("- 분류 후보: DATA-001-01\n",
                        f"- 분류 후보: DATA-001-01\n{QUESTION}{output.QUESTION_PENDING}\n  - 질문 아래 줄은 그대로\n")
    (job / "report.md").write_text(text, encoding="utf-8")
    return job


def test_question_line_points_to_answer_after_explore_check(tmp_path, capsys):
    job = _question_job(tmp_path)
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    assert check(job, "explore", capsys=capsys)[0] == 0
    assert _line(job, QUESTION) == QUESTION + output.QUESTION_DONE
    assert "  - 질문 아래 줄은 그대로" in (job / "report.md").read_text(encoding="utf-8")
    none = _question_job(tmp_path / "none")
    (none / "explore-output.md").write_text("가설 없음: 실패 구간 로그가 없다\n다음 확인: 실패 시각 앞뒤 30초 로그\n", encoding="utf-8")
    assert check(none, "explore", capsys=capsys)[0] == 0
    assert _line(none, QUESTION) == QUESTION + output.QUESTION_DONE_NONE
    # 생략(--skipped)·형식 실패는 답하지 않는다고 적는다
    skipped = _question_job(tmp_path / "skip")
    assert check(skipped, "explore", skipped="사용자가 하지 않음", capsys=capsys)[0] == 0
    assert _line(skipped, QUESTION) == QUESTION + output.QUESTION_SKIPPED
    bad = _question_job(tmp_path / "bad")
    (bad / "explore-output.md").write_text("가설 1: 칸이 모자란 가설\n", encoding="utf-8")
    assert check(bad, "explore", capsys=capsys)[0] == 1
    assert _line(bad, QUESTION) == QUESTION + output.QUESTION_SKIPPED
    # RP-8: `triage.py explore` 재실행 뒤 다시 검사하면 꼬리도 이번 결과로 바뀐다(통과 → 실패, 생략 → 통과)
    report.rewrite_line(job / "report.md", "- 탐색 분석", [EXPLORE_PENDING])
    (job / "explore-output.md").write_text("가설 1: 칸이 모자란 가설\n", encoding="utf-8")
    assert check(job, "explore", capsys=capsys)[0] == 1 and _line(job, QUESTION) == QUESTION + output.QUESTION_SKIPPED
    report.rewrite_line(skipped / "report.md", "- 탐색 분석", [EXPLORE_PENDING])
    (skipped / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    assert check(skipped, "explore", capsys=capsys)[0] == 0 and _line(skipped, QUESTION) == QUESTION + output.QUESTION_DONE
    # 꼬리가 다른 줄(never·--no-explore 안내)은 고치지 않는다
    other = make_job(tmp_path / "other", "explore", "plain")
    keep = f"{QUESTION} — 탐색 분석 안 함 — 확인할 내용은 답하지 않음(근거 로그로 직접 확인)"
    (other / "report.md").write_text(_report(EXPLORE_PENDING, []) + keep + "\n", encoding="utf-8")
    (other / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    assert check(other, "explore", capsys=capsys)[0] == 0 and _line(other, QUESTION) == keep


def test_recheck_keeps_earlier_fabricated_count(tmp_path, capsys):
    """VERIFY-B 5: `triage.py explore`를 다시 돌려 고친 출력으로 다시 검사해도 앞 검사의 원문에 없는 인용 수는 지우지 않는다."""
    job = make_job(tmp_path, "explore", "plain")
    (job / "trace.jsonl").write_text("", encoding="utf-8")
    (job / "explore-output.md").write_text(_explore_out([("모뎀 펌웨어 오류", [FAKE])]), encoding="utf-8")
    assert check(job, "explore", capsys=capsys)[1]["fabricated"] == 1
    report_md = job / "report.md"      # `triage.py explore` 재실행이 탐색 줄을 다시 TODO로 돌린다
    report.rewrite_line(report_md, "- 탐색 분석", [EXPLORE_PENDING])
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and data["fabricated"] == 0
    assert data["evidence"] == "- 근거 원문 검사: 인용 1개 중 원문에 없음 0" + output.FAB_BEFORE.format(n=1)
    rec = _rec(job, "explore")
    assert rec["fabricated"] == 0 and rec["fabricated_before"] == 1
    rows = [json.loads(x) for x in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r.get("fabricated") for r in rows] == [1, 0]
    # 그 뒤 생략으로 바꿔도 이어 간다
    report.rewrite_line(report_md, "- 탐색 분석", [EXPLORE_PENDING])
    assert check(job, "explore", skipped="그만", capsys=capsys)[0] == 0
    assert _rec(job, "explore")["fabricated_before"] == 1
    # 처음 검사는 표시가 없다(기록도 없음)
    fresh = make_job(tmp_path / "fresh", "explore", "plain")
    (fresh / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    assert "앞 검사" not in check(fresh, "explore", capsys=capsys)[1]["evidence"]
    assert "fabricated_before" not in _rec(fresh, "explore")


# --- triage.py window 구간(근거 원문에 더함) ------------------------------------------------------------------

WIN_ROW = "15:10:01.900 p0 E hiddend carrier link lost on rmnet_data3 after reject"     # 타임라인에 없는 줄(버려진 태그)


def _window(job: Path, n: int = 1, rows=(WIN_ROW,), record: bool = True) -> Path:
    path = job / f"window-{n}.md"
    path.write_text("\n".join([f"# {KEY} 로그 구간 {n}", "", "- 중심: x", "", *rows, ""]), encoding="utf-8")
    if record:
        rec = job / core.WINDOW_RECORD
        old = json.loads(rec.read_text(encoding="utf-8"))["windows"] if rec.is_file() else []
        rec.write_text(json.dumps({"windows": [*old, {"path": path.name, "sha256": _sha(path), "at": "x", "lines": len(rows),
                                                      "tags": []}]}), encoding="utf-8")
    return path


@pytest.mark.parametrize("purpose, mode", [("deep", "module"), ("explore", "plain"), ("explore", "explore"), ("deep", "skill")])
def test_window_lines_count_as_source(tmp_path, capsys, purpose, mode):
    """`triage.py window` 구간의 줄은 근거 원문이다(없으면 `[근거 불일치]` 오탐). 기록 source에 구간 이름이 붙는다."""
    job = make_job(tmp_path, purpose, mode)
    _window(job)
    out = _deep_out([Q1, WIN_ROW]) if mode == "module" else (
        _skill_out([WIN_ROW]) if mode == "skill" else _explore_out([("망 인증 거절", [Q1, WIN_ROW])]))
    (job / output.OUTPUT_FILE[purpose]).write_text(out, encoding="utf-8")
    code, data, err = check(job, purpose, capsys=capsys)
    assert code == 0 and data["fabricated"] == 0, (data, err)
    assert "window-1.md" in _rec(job, purpose)["source"] and "windows_excluded" not in data


def test_window_changed_or_unrecorded_is_not_source(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    _window(job).write_text("바꾼 글\n" + WIN_ROW + "\n", encoding="utf-8")     # 기록 뒤 바뀜: 빼고 경고
    _window(job, 2, rows=("15:10:01.950 p0 E otherd not recorded either",), record=False)    # 기록에 없음: 보지 않는다
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1, WIN_ROW])]), encoding="utf-8")
    code, data, err = check(job, "explore", capsys=capsys)
    assert code == 0 and data["fabricated"] == 1 and data["windows_excluded"] == ["window-1.md"]
    assert "구간 파일이 기록과 달라" in err and _rec(job, "explore")["source"] == "timeline.md"


def test_no_window_record_output_unchanged(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and set(data) == {"line", "evidence", "quotes", "fabricated", "weak", "raw"}


# --- 규칙 제안 하위 줄(SKILL Step 7이 report.md에서 읽는다) ---------------------------------------------------

RULE_OK = "[이슈 DB] add-parser-rule file=extractors.yaml rule={id: x} — 근거: RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM"
RULE_FAKE = "[이슈 DB] add-parser-rule file=tags.yaml rule={tag: X} — 근거: modem firmware crashed with assertion"
RULE_PLAIN = "[이슈 DB] update-signature DATA-001-01 — must_match에 거절 사유를 더한다"


def _with_rules(text: str, rules) -> str:
    return text.rstrip("\n") + "\n규칙 제안:\n" + "".join(f"- {r}\n" for r in rules)


def test_explore_rule_proposals_reach_report_only_when_grounded(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text(_with_rules(_explore_out([("망 인증 거절", [Q1])]), [RULE_OK, RULE_FAKE, RULE_PLAIN]),
                                           encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and data["fabricated"] == 0
    text = (job / "report.md").read_text(encoding="utf-8").split("\n")
    assert f"  - 규칙 제안 (탐색): {RULE_OK}" in text and f"  - 규칙 제안 (탐색): {RULE_PLAIN}" in text
    assert not any("modem firmware" in t for t in text)                       # 근거 문구가 원문에 없다
    assert "  - 탐색 출력의 제안 1개는 근거가 원문에서 확인되지 않아 뺐다" in text            # Step 7이 고르지 않게 `규칙 제안` 낱말 없음
    rec = _rec(job, "explore")
    assert (rec["rules"], rec["rules_dropped"]) == (2, 1)


def test_rule_without_basis_dropped_when_any_quote_fabricated_and_none_skipped(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text(_with_rules(_explore_out([("모뎀 펌웨어 오류", [FAKE])]), [RULE_PLAIN, "없음"]),
                                           encoding="utf-8")
    check(job, "explore", capsys=capsys)
    text = (job / "report.md").read_text(encoding="utf-8")
    assert "규칙 제안" not in text and "제안 1개는 근거가" in text      # [근거 불일치] 가설이 있으면 근거 없는 제안은 뺀다
    none = make_job(tmp_path / "n", "explore", "plain")
    (none / "explore-output.md").write_text(_with_rules(_explore_out([("망 인증 거절", [Q1])]), ["없음"]), encoding="utf-8")
    check(none, "explore", capsys=capsys)
    assert "규칙 제안" not in (none / "report.md").read_text(encoding="utf-8") and "rules" not in _rec(none, "explore")


def test_deep_rule_proposals_use_same_lines(tmp_path, capsys):
    job = make_job(tmp_path)
    out = _deep_out([Q1, Q2]).replace("규칙 제안:\n- 없음", f"규칙 제안:\n- {RULE_OK}")
    (job / "deep-output.md").write_text(out, encoding="utf-8")
    assert check(job, capsys=capsys)[0] == 0
    text = (job / "report.md").read_text(encoding="utf-8").split("\n")
    i = text.index(f"  - 규칙 제안 (심층): {RULE_OK}")
    assert text[i - 1] == "  - 근거 원문 검사: 인용 2개 중 원문에 없음 0" and text[i + 1] == SUB


def test_rule_proposals_need_ok_verdict_and_a_ran_check_and_same_line_item(tmp_path, capsys):
    """리뷰 2·5: 근거 문구가 약함(원문에 없는 짧은 낱말)이면 뺀다. 근거 없는 제안은 원문 검사를 실제로 했을 때만(인용 없음이면 뺀다).
    `규칙 제안: [이슈 DB] …`처럼 칸 이름 줄에 바로 쓴 제안도 항목 하나다(탐색·심층 같은 파서)."""
    weak = "[이슈 DB] update-signature DATA-001-01 — 근거: LOADED"
    job = make_job(tmp_path, "explore", "plain")
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]).rstrip("\n") + f"\n규칙 제안: {RULE_PLAIN}\n- {weak}\n",
                                           encoding="utf-8")
    check(job, "explore", capsys=capsys)
    text = (job / "report.md").read_text(encoding="utf-8").split("\n")
    assert f"  - 규칙 제안 (탐색): {RULE_PLAIN}" in text and not any("LOADED" in t for t in text)
    assert (_rec(job, "explore")["rules"], _rec(job, "explore")["rules_dropped"]) == (1, 1)
    deep = make_job(tmp_path / "d")
    (deep / "deep-output.md").write_text(_deep_out([Q1, Q2]).replace("규칙 제안:\n- 없음", f"규칙 제안: {RULE_OK}"), encoding="utf-8")
    check(deep, capsys=capsys)
    assert f"  - 규칙 제안 (심층): {RULE_OK}" in (deep / "report.md").read_text(encoding="utf-8").split("\n")
    bare = make_job(tmp_path / "b")                         # 인용 없음: 원문 검사를 안 했다 — 근거 없는 제안은 싣지 않는다
    (bare / "deep-output.md").write_text(_deep_out([]).replace("규칙 제안:\n- 없음", f"규칙 제안:\n- {RULE_PLAIN}"), encoding="utf-8")
    check(bare, capsys=capsys)
    assert "규칙 제안 (심층): " not in (bare / "report.md").read_text(encoding="utf-8")


def test_same_line_rule_item_parses_in_both_paths():
    from common import evidence

    deep = evidence.parse_fields(_deep_out([Q1]).replace("규칙 제안:\n- 없음", f"규칙 제안: {RULE_PLAIN}"))
    assert deep["규칙 제안"] == [RULE_PLAIN]
    assert evidence.parse_fields(_deep_out([Q1]).replace("규칙 제안:\n- 없음", "규칙 제안: 없음"))["규칙 제안"] == []
    exp = evidence.parse_explore(_explore_out([("망 인증 거절", [Q1])]) + f"규칙 제안: {RULE_PLAIN}\n- {RULE_OK}\n")
    assert exp["rules"] == [RULE_PLAIN, RULE_OK]


@pytest.mark.parametrize("purpose", ["deep", "explore"])
def test_none_with_reason_is_not_a_proposal(tmp_path, capsys, purpose):
    """확인 리뷰 C: `없음`·`해당 없음`으로 시작하면(뒤 설명 무엇이든) 제안이 아니다 — 같은 줄·목록 모두, deep·탐색 모두."""
    for k, block in enumerate(("규칙 제안: 없음 (새 규칙 필요 없음)\n", "규칙 제안:\n- 없음 — 시그니처가 이미 있다\n- `해당 없음`\n")):
        job = make_job(tmp_path / f"{purpose}{k}", purpose, "module" if purpose == "deep" else "plain")
        if purpose == "deep":
            (job / "deep-output.md").write_text(_deep_out([Q1, Q2]).replace("규칙 제안:\n- 없음\n", block), encoding="utf-8")
        else:
            (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])]) + block, encoding="utf-8")
        check(job, purpose, capsys=capsys)
        text = (job / "report.md").read_text(encoding="utf-8")
        assert "규칙 제안" not in text and "제안 " not in text.split("근거 원문 검사")[-1].split("\n")[1], (purpose, k)
        assert "rules" not in _rec(job, purpose) and "rules_dropped" not in _rec(job, purpose)


# -- 11/25 기대 체인(explore.md 쓰는 것): 형식 경고 · 다시 검사 한 번 · 관측 줄 원문 검사 ---------------------------------------

def _chain(rows, claim=None, extra=()):
    head = ["기대 체인:", "| 단계 | 기대 | 기대 근거 | 관측 줄 | 일치 |", "|---|---|---|---|---|"]
    return (*head, *[f"| {n} | {e} | log:15:10:0{n} | {o} | {v} |" for n, e, o, v in rows],
            *([f"첫 갈라짐: {claim}"] if claim else []), *extra)


CHAIN_FALSE2 = [(1, "SETUP 요청이 나간다", "src/gprs.c:gprs_attach() attach requested apn=internet", "true"),
                (2, "SETUP 응답이 성공", Q1, "false"),
                (3, "데이터 연결", "없음(찾은 곳: 타임라인 15:10:03~)", "false")]


def test_explore_chain_parses_new_fields_and_old_format_still_parses():
    text = _explore_out([("망 인증 거절", [Q1])], _chain(CHAIN_FALSE2, "단계 2 — 망이 PDN 거절",
                                                      ("찾았는데 없음:", "- 재요청 — window --at 15:10:05", "책임 경계: CP-망 경계")))
    h = evidence.parse_explore(text)["hyps"][0]
    assert [r["단계"] for r in h["기대 체인"]] == [1, 2, 3] and [r["일치"] for r in h["기대 체인"]] == ["true", "false", "false"]
    assert h["첫 갈라짐"].startswith("단계 2") and h["찾았는데 없음"] == ["재요청 — window --at 15:10:05"]
    assert h["책임 경계"] == "CP-망 경계" and h["로그로 확인"] == [Q1]
    assert evidence.chain_quotes(h) == [CHAIN_FALSE2[0][2], Q1]            # `없음(찾은 곳…)`은 인용이 아니다
    old = evidence.parse_explore(_explore_out([("망 인증 거절", [Q1])], ()))
    assert old["hyps"][0]["기대 체인"] is None and old["hyps"][0]["로그로 확인"] == [Q1]


def test_explore_chain_warnings(tmp_path, capsys):
    cases = {
        "missing": (_explore_out([("망 인증 거절", [Q1])], ()), "`기대 체인:` 표 없음"),
        "not_earliest": (_explore_out([("망 인증 거절", [Q1])], _chain(CHAIN_FALSE2, "단계 3 — 연결 안 됨")),
                         "첫 갈라짐 단계 3 ≠ 표의 가장 이른 false 단계 2"),
        "timer": ("가설 1: 재시도 타이머가 늦게 풀림\n원인 층: 프레임워크\n" + _explore_out([("x", [Q1])],
                  _chain(CHAIN_FALSE2, "단계 2"))[len("가설 1: x\n"):], "`메커니즘 재계산:` 없음"),
    }
    for name, (text, needle) in cases.items():
        job = make_job(tmp_path / name, "explore", "plain")
        (job / "explore-output.md").write_text(text, encoding="utf-8")
        code, data, _ = check(job, "explore", capsys=capsys)
        assert code == 0 and any(needle in w for w in data["format_warnings"]), (name, data)
        assert data["next"] == output.FORMAT_NEXT
        assert any(t.startswith("  - 형식 경고(탐색, 판정 아님): ") and needle in t
                   for t in (job / "report.md").read_text(encoding="utf-8").split("\n")), name
    # 올바른 표본: 가장 이른 false = 첫 갈라짐, 원인 층 있음, 타이머 낱말 + 메커니즘 재계산 예 → 경고 없음
    good = ("가설 1: 재시도 간격 뒤 망 거절\n원인 층: 망 — 거절\n책임 경계: CP-망 경계\n"
            + _explore_out([("x", [Q1])], _chain(CHAIN_FALSE2, "단계 2 — 망이 거절",
                           ("메커니즘 재계산: 15:10:00 + 1s = 15:10:01 → 고치면 결과가 뒤집히나: 예",)))[len("가설 1: x\n"):])
    job = make_job(tmp_path / "good", "explore", "plain")
    (job / "explore-output.md").write_text(good, encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and "format_warnings" not in data and "next" not in data and data["fabricated"] == 0
    assert data["quotes"] == 3                                               # 로그로 확인 1 + 관측 줄 2
    assert "첫 갈라짐: 단계 2 — 망이 거절" in _line(job, "  - 가설 1")


def test_explore_chain_observed_quote_goes_through_evidence_check(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    rows = [(1, "SETUP 응답", FAKE, "false")]
    (job / "explore-output.md").write_text(_explore_out([("망 인증 거절", [Q1])], _chain(rows, "단계 1")), encoding="utf-8")
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and data["fabricated"] == 1 and data["quotes"] == 2
    assert _line(job, "  - 가설 1").startswith("  - 가설 1 [근거 불일치 1]: ")


def test_explore_format_warning_allows_one_recheck(tmp_path, capsys):
    job = make_job(tmp_path, "explore", "plain")
    out = job / "explore-output.md"
    out.write_text(_explore_out([("망 인증 거절", [Q1])], ()), encoding="utf-8")
    assert check(job, "explore", capsys=capsys)[1]["format_warnings"]
    out.write_text(_explore_out([("망 인증 거절", [Q1])]), encoding="utf-8")          # 고쳐 쓴 뒤 한 번 더
    code, data, _ = check(job, "explore", capsys=capsys)
    assert code == 0 and "format_warnings" not in data and _rec(job, "explore")["format_recheck"] is True
    assert not any(t.startswith("  - 형식 경고") for t in (job / "report.md").read_text(encoding="utf-8").split("\n"))
    code, data, _ = check(job, "explore", capsys=capsys)                              # 세 번째는 평소처럼 막힌다
    assert code == 2 and data["reason"] == "작업 없음"
