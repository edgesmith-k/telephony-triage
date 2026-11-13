"""`triage.py module` (B1 §10.3, B2 §12.2): JOB 기록·출력 JSON·종료 표(`next` 포함)·리포트 줄·explore E0.

모의 원격(`tests/mocks/module-skills`, file://)과 합성 JOB을 쓴다. 대부분 같은 프로세스(`triage.main`)로 부른다.
다른 묶음 함수(userconfig·report·core 줄 상수·masking.redact·skillpath·provenance·modulefilter)는 진짜를 쓴다.
네트워크·비용 드는 호출은 없다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import module_remote as mr  # noqa: E402
from runner import plugin_root, run  # noqa: E402

ROOT = plugin_root("module-skills", platform={"name": "android", "enabled": ["android", "ofono"]})
sys.path.insert(0, str(ROOT / "scripts"))
import triage  # noqa: E402
from common import moduleskills, userconfig  # noqa: E402
from triagelib import core, modulecmd, report  # noqa: E402

KEY = "MOCK-9101"
POSIX = os.name != "nt"
DEEP_READ = ["ofono/_common/layers.md", "ofono/_common/components.md", "ofono/data/SKILL.md", "ofono/data/analyzer.md",
             "ofono/data/references/DATA-001.md"]
C0_KEYS = ["schema_version", "key", "platform", "module", "sha", "type_id", "top_candidates", "issue_summary", "occurred_at",
           "events", "timeline", "log_paths"]

# -- JOB·실행 도우미 ------------------------------------------------------------------------------

EVENTS = [
    {"ts": "2026-09-20T05:32:08.000Z", "tag": "datad", "msg": "PdnCtx activate", "level": "I", "category_hint": "data"},
    {"ts": "2026-09-20T05:32:09.000Z", "tag": "ofonod", "msg": "gprs attach failed", "level": "E", "category_hint": "data",
     "event": "DATA_FAIL"},
    {"ts": "2026-09-20T05:32:10.000Z", "tag": "datad2", "msg": "route add failed", "level": "W", "category_hint": "data"},
]
SIM_EVENT = {"ts": "2026-09-20T05:32:11.000Z", "tag": "simd", "msg": "GetEID FAILED", "level": "E", "category_hint": "sim"}
MODEM_EVENT = {"ts": "2026-09-20T05:32:09.500Z", "tag": "ofonod", "msg": "src/modem.c:modem_change_state() modem reset", "level": "W",
               "category_hint": "common"}


class Env:
    def __init__(self, tmp_path: Path, monkeypatch, capsys):
        self.tmp, self.capsys = tmp_path, capsys
        self.home = tmp_path / "home"
        self.home.mkdir()
        monkeypatch.setenv(userconfig.HOME_ENV, str(self.home))
        monkeypatch.delenv("TT_PLATFORM", raising=False)
        self.url = mr.build(tmp_path / "remote")
        self.job = tmp_path / "job"
        self.user({"module_skills": {"remote": self.url}})

    def user(self, data: dict) -> None:
        (self.home / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    def make_job(self, events=None, candidates=None, platform="ofono", explore=False, extra: dict | None = None):
        job = self.job
        job.mkdir(exist_ok=True)
        cands = [{"type": "DATA-001", "cause": "DATA-001-01", "score": 9, "confidence": "high", "category": "data",
                  "evidence": []}] if candidates is None else candidates
        analysis = {"key": KEY, "issue": {"summary": "데이터 연결 실패", "occurred_at": "2026-09-20T05:32:10Z"},
                    "candidates": cands, **({} if platform == "android" else {"platform": platform}), **(extra or {})}
        if explore:
            analysis["explore"] = {"reason": "no_candidate" if not cands else "cause_unconfirmed", "when": "ask"}
        (job / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        ev = {"events": list(EVENTS if events is None else events),
              "input": {"files": ["/abs/source.log"], "window": {"start": "2026-09-20T05:27:00Z", "end": "2026-09-20T05:37:00Z"}}}
        (job / "events.json").write_text(json.dumps(ev, ensure_ascii=False), encoding="utf-8")
        lines = ["# 리포트", "", "- 심층 분석 (모듈 스킬 ofono, 1위 카테고리 data): 미실행 — TODO(LLM) 결과", "  - 옛 줄",
                 "- 탐색 분석 (추정): 미실행 — " + core.EXPLORE_HYPOTHESIS, "- 끝", ""]
        (job / "report.md").write_text("\n".join(lines), encoding="utf-8")
        if explore:
            (job / core.EXPLORE_INPUT_FILE).write_text(json.dumps({"around": "2026-09-20T05:32:10Z", "failed_step": None,
                                                                   "limit": 200, "anchor": None}), encoding="utf-8")
            code, _, _ = self.call("explore", KEY, "--out", job, "--platform", platform)
            assert code == 0
        return job

    def call(self, *argv):
        self.capsys.readouterr()
        code = triage.main([*map(str, argv), "--plugin-root", str(ROOT)])
        out, err = self.capsys.readouterr()
        lines = [ln for ln in out.splitlines() if ln.strip()]
        return code, (json.loads(lines[-1]) if lines else None), err

    def module(self, purpose="deep", *extra, platform="ofono"):
        code, out, err = self.call("module", KEY, "--for", purpose, "--out", self.job, "--platform", platform, *extra)
        if out is not None:
            assert len(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()) <= 4096
        return code, out, err

    @property
    def work(self) -> Path:
        return self.home / "work-ofono"

    def report_line(self, prefix="- 심층 분석") -> str:
        return next(r for r in (self.job / "report.md").read_text(encoding="utf-8").split("\n") if r.startswith(prefix))


@pytest.fixture
def env(tmp_path, monkeypatch, capsys):
    return Env(tmp_path, monkeypatch, capsys)


def snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(d.rglob("*")) if p.is_file()}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# -- deep: module ---------------------------------------------------------------------------------


def test_deep_success_files_and_records(env):
    job = env.make_job()
    code, out, err = env.module()
    assert code == 0, err
    assert set(out) == {"module", "sha", "read", "also", "input", "timeline"}
    assert out["module"] == "ofono/data" and out["sha"] == mr.head(env.tmp / "remote") and out["also"] == []
    assert out["read"] == [str(job / "module-skill" / "deep" / p) for p in DEEP_READ]
    for p in DEEP_READ:
        assert (job / "module-skill" / "deep" / p).read_bytes() == (mr.MOCK / p).read_bytes()
    assert (job / "module-skill" / "deep" / "modules.yaml").read_bytes() == (mr.MOCK / "modules.yaml").read_bytes()
    rec = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["deep"]
    for f in rec["files"]:
        assert f["sha256"] == sha(job / f["path"])
    assert rec["checks"]["skipped"] == {"로그 원문": "건너뜀(E)", "사내 값": "건너뜀(E)", "D-Bus 이름": "건너뜀(E)"}
    assert rec["inputs"] == {"analysis.json": sha(job / "analysis.json"), "events.json": sha(job / "events.json"),
                             "match.json": None}
    assert rec["timeline"]["sha256"] == sha(job / rec["timeline"]["path"]) and rec["center"] == "2026-09-20T05:32:10Z"
    deep_input = json.loads((job / "deep-input.json").read_text(encoding="utf-8"))
    assert list(deep_input) == C0_KEYS
    assert deep_input["timeline"] == "module-skill/deep/timeline.md" and deep_input["log_paths"] == ["/abs/source.log"]
    assert (job / deep_input["timeline"]).is_file() and not (job / "timeline.md").exists()
    assert out["timeline"]["view"] is False
    if POSIX:
        assert (job / "deep-input.json").stat().st_mode & 0o777 == 0o600
        assert (job / "module-skill" / "deep").stat().st_mode & 0o777 == 0o700
    assert env.url not in json.dumps(out) + err and "remote.git" not in json.dumps(out) + err
    assert env.report_line().startswith("- 심층 분석 (모듈 스킬 ofono/data @" + out["sha"][:7] + ")")
    assert "  - 옛 줄" not in (job / "report.md").read_text(encoding="utf-8")


def test_deep_generic_without_filter_equals_report_timeline(env):
    job = env.make_job()
    env.module()
    events = json.loads((job / "events.json").read_text(encoding="utf-8"))
    expect = report.timeline(KEY, events, "2026-09-20T05:32:10Z", 200, None, None)[0]
    assert (job / "module-skill" / "deep" / "timeline.md").read_text(encoding="utf-8") == expect


def _c0_deep_job(tmp_path: Path, src: Path) -> tuple[Path, Path, dict, Path]:
    """C0 deep case(`data-apn-auth-reject`)의 JOB을 입력 생성기와 같은 루트·변형 DB·인자로 만든다(B1 §10.3)."""
    import make_module_eval_inputs as gen
    import make_variant_dbs
    from runner import plugin_root as _root

    case_dir = gen.TEMPLATES / "ofono" / "data" / "evals" / "data-apn-auth-reject"
    case = gen._load_case(case_dir, False)
    url = mr.build(tmp_path / "remote", src=src)
    root = _root("ofono-on-ms", platform=gen.PLATFORM, module_skills={"remote": url})
    db = make_variant_dbs.build(gen.VARIANT, tmp_path / "db")
    (tmp_path / "logs").mkdir()
    log = tmp_path / "logs" / "source.log"
    log.write_bytes((case_dir / "files" / "source.log").read_bytes())
    (tmp_path / "issue.yaml").write_text(gen._issue_yaml(case), encoding="utf-8", newline="\n")
    job, home = tmp_path / "job", tmp_path / "home"
    parse = case.get("parse") or {}
    proc = run("triage.py", ["run", case["key"], "--offline-db", db, "--logs", log, "--issue-file", tmp_path / "issue.yaml",
                             "--out", job, "--platform", "ofono", "--tz", parse["tz"], "--year", parse["year"],
                             "--minutes", parse.get("minutes", 5)], root=root, env={"TELEPHONY_TRIAGE_HOME": home})
    assert proc.returncode == 0, proc.stderr
    proc = run("triage.py", ["module", case["key"], "--for", "deep", "--out", job, "--platform", "ofono"], root=root,
               env={"TELEPHONY_TRIAGE_HOME": home})
    assert proc.returncode == 0, proc.stderr
    return job, case_dir, json.loads(proc.stdout.strip().splitlines()[-1]), root


def test_deep_c0_parity(tmp_path):
    """B2 §5.6: 템플릿 원격(필터 있음)으로 받은 deep 입력·모듈 보기가 C0 case 파일과 같다."""
    job, case_dir, out, _ = _c0_deep_job(tmp_path, mr.TEMPLATES)
    assert out["module"] == "ofono/data"
    want = json.loads((case_dir / "files" / "deep-input.json").read_text(encoding="utf-8"))
    got = json.loads((job / "deep-input.json").read_text(encoding="utf-8"))
    assert list(got) == list(want) == C0_KEYS
    assert re.fullmatch(r"[0-9a-f]{40}", got["sha"])
    assert got["timeline"].endswith("module-skill/deep/timeline.md") or got["timeline"] == "module-skill/deep/timeline.md"
    assert len(got["log_paths"]) == 1 and Path(got["log_paths"][0]).is_absolute() and got["log_paths"][0].endswith("source.log")
    for k in C0_KEYS:
        if k not in ("sha", "timeline", "log_paths", "events"):
            assert got[k] == want[k], k
    view = (job / "module-skill" / "deep" / "timeline.md").read_bytes()
    assert view == (case_dir / "files" / "timeline.md").read_bytes()
    rec = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["deep"]
    assert rec.get("center") and rec["center"] in view.decode("utf-8")


def test_deep_view_independent_of_analysis_size(tmp_path):
    """B2 §5.6: analysis.json이 4 KB를 넘어도(근거가 잘려도) deep 보기는 match.json 근거로 같은 바이트다."""
    job, case_dir, _, root = _c0_deep_job(tmp_path, mr.TEMPLATES)
    view = (job / "module-skill" / "deep" / "timeline.md").read_bytes()
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    analysis["issue"]["description"] = (analysis["issue"].get("description") or "") + " 패딩" * 2000
    (job / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    assert (job / "analysis.json").stat().st_size > 4096
    proc = run("triage.py", ["module", analysis["key"], "--for", "deep", "--out", job, "--platform", "ofono"], root=root,
               env={"TELEPHONY_TRIAGE_HOME": tmp_path / "home"})
    assert proc.returncode == 0, proc.stderr
    assert (job / "module-skill" / "deep" / "timeline.md").read_bytes() == view


def test_rerun_same_sha_is_byte_identical(env):
    job = env.make_job()
    env.module()
    first = snapshot(job / "module-skill")
    di = (job / "deep-input.json").read_bytes()
    rec1 = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    env.module()
    assert {k: v[0] for k, v in snapshot(job / "module-skill").items()} == {k: v[0] for k, v in first.items()}
    assert (job / "deep-input.json").read_bytes() == di
    rec2 = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    rec1["deep"].pop("at"), rec2["deep"].pop("at")
    assert rec1 == rec2


def test_deep_also_signal_and_also(env):
    # 신호 구간은 1위 근거(실패 표시 줄)로 정한다(modulefilter.deep_window): 그 앞뒤에 모뎀 데몬 줄이 있으면 묻는다
    cands = [{"type": "DATA-001", "cause": "DATA-001-01", "score": 9, "confidence": "high", "category": "data",
              "evidence": [{k: EVENTS[1][k] for k in ("ts", "tag", "msg", "event")}]}]
    job = env.make_job(events=EVENTS + [MODEM_EVENT], candidates=cands)
    code, out, _ = env.module()
    assert code == 0 and out["also"] == ["ofono/modem"] and out["also_why"] == ["ofonod src/modem.c 1줄"]
    assert out["ask_also"]["options"] == ["아니오(기본)", "예"] and out["ask_also"]["question"].startswith("모뎀 모듈 문서도")
    code, out, _ = env.module("deep", "--also")
    assert code == 0 and out["with"] == ["ofono/modem"] and out["read"][-1].endswith("ofono/modem/SKILL.md")
    assert "ofono/data+modem @" in env.report_line()
    rec = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["deep"]
    assert rec["with"] == ["ofono/modem"]


def test_module_does_not_touch_existing_job_files(env):
    job = env.make_job(explore=True)
    (job / "match.json").write_text("{}", encoding="utf-8")
    (job / "triage-state.json").write_text("{}", encoding="utf-8")
    before = snapshot(job)
    assert env.module()[0] == 0
    assert env.module("explore", "--module", "ofono/data")[0] == 0
    after = snapshot(job)
    for name, value in before.items():
        if name != "report.md":
            assert after[name] == value, name
    rows = (job / "report.md").read_text(encoding="utf-8").split("\n")
    assert rows[2].startswith("- 심층 분석 (모듈 스킬 ofono/data @")


def test_session_lock_ignored(env):
    env.make_job()
    env.work.mkdir(parents=True)
    (env.work / "session.lock").write_text(json.dumps({"owner": "someone-else"}), encoding="utf-8")
    assert env.module()[0] == 0


# -- deep: 설치 스킬 ------------------------------------------------------------------------------


def _skill_user(env, skill_dir=None, remote=True):
    conf = {"skill": "mock-data-analyzer", "prefer": "skill"}
    if skill_dir:
        conf["skill_dir"] = str(skill_dir)
    data = {"platforms": {"ofono": {"analyzers": {"data": conf}}}}
    if remote:
        data["module_skills"] = {"remote": env.url if remote is True else remote}
    env.user(data)


def test_deep_skill_source_resolves(env):
    job = env.make_job()
    skill_dir = REPO / "tests" / "mocks" / "skills" / "data-analyzer"
    _skill_user(env, skill_dir)
    before = (job / "report.md").read_bytes()
    code, out, err = env.module()
    assert code == 0, err
    assert set(out) == {"skill", "read", "base", "input", "timeline"}
    assert out["read"] == [str(skill_dir / "SKILL.md")] and out["base"] == str(skill_dir)
    si = json.loads((job / "skill-input.json").read_text(encoding="utf-8"))
    assert list(si) == ["events_json", "log_paths", "top_candidates", "issue_summary", "timeline"]
    assert Path(si["timeline"]).is_file()
    rec = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["deep"]
    assert rec["skill"] == "mock-data-analyzer" and rec["sha256"] == sha(skill_dir / "SKILL.md")
    assert not (env.work / moduleskills.CLONE_DIR).exists() and (job / "report.md").read_bytes() == before


def test_deep_skill_not_found_writes_input(env):
    job = env.make_job()
    _skill_user(env)
    before = (job / "report.md").read_bytes()
    code, out, err = env.module()
    assert code == 1 and out["reason"] == "설치 스킬 못 찾음" and out["skill"] == "mock-data-analyzer"
    assert out["input"] == str(job / "skill-input.json") and out["next"] == core.NEXT_SKILL_MISSING
    assert err.startswith("설치 스킬 못 찾음: ") and len(err.strip().splitlines()) == 1
    assert (job / "skill-input.json").is_file() and (job / "module-skill" / "deep" / "timeline.md").is_file()
    assert json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["deep"]["path"] is None
    assert (job / "report.md").read_bytes() == before and not (env.work / moduleskills.CLONE_DIR).exists()


def test_skill_source_ignores_bad_remote(env):
    env.make_job()
    _skill_user(env, REPO / "tests" / "mocks" / "skills" / "data-analyzer", remote="https://u:tok@ghe.example.invalid/o/r.git")
    code, out, _ = env.module()
    assert code == 0 and "skill" in out


# -- explore ---------------------------------------------------------------------------------------


def test_explore_module_success(env):
    job = env.make_job(explore=True)
    env.module()
    code, out, err = env.module("explore", "--module", "ofono/data")
    assert code == 0, err
    assert out["pick"] == {"by": "user"} and len(out["read"]) == 4 and out["read"][-1] == str(job / "timeline.md")
    assert not out["timeline"]["view"]
    rec = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    assert set(rec) == {"deep", "explore"}
    assert set(rec["explore"]["inputs"]) == {"analysis.json", "events.json", "explore-input.json", "timeline.md"}
    assert env.report_line("- 탐색 분석").startswith("- 탐색 분석 (추정, timeline.md 3/3줄, 모듈 문서 ofono/data @")


def test_explore_single_candidate_auto(env):
    env.make_job(explore=True)
    code, out, _ = env.module("explore")
    assert code == 0 and out["pick"] == {"by": "auto"} and out["module"] == "ofono/data"
    assert out["candidates"][0]["module"] == "ofono/data" and out["candidates"][0]["lines"] == 3


def test_explore_two_candidates_pick_null(env):
    job = env.make_job(events=EVENTS + [SIM_EVENT], explore=True)
    before = snapshot(job)
    code, out, _ = env.module("explore")
    assert code == 0 and out["pick"] is None and [c["module"] for c in out["candidates"]] == ["ofono/data", "ofono/sim"]
    assert out["ask"]["question"] == "어느 모듈 문서로 볼까요? (모듈 신호 줄 수: data 3 · sim 1)"
    assert out["ask"]["options"] == ["data — 3줄 (요약과 맞음)", "sim — 1줄"]      # 1위 유형 DATA-001(원인 미확인) 힌트
    assert snapshot(job) == before
    import fcntl
    with open(env.work / moduleskills.LOCK_FILE, "rb+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)        # lock이 풀려 있다


@pytest.mark.parametrize("choose, code, module", [("top", 0, "ofono/data"), ("sim", 0, "ofono/sim"), ("call", 1, None)])
def test_explore_choose(env, choose, code, module):
    env.make_job(events=EVENTS + [SIM_EVENT], explore=True)
    got, out, _ = env.module("explore", "--choose", choose)
    assert got == code
    if module:
        assert out["module"] == module and out["pick"] == {"by": "choose"}
    else:
        assert out["reason"] == "레포에 ofono/call 없음" and out["next"] == core.NEXT_BUILTIN


def test_explore_zero_candidates(env):
    # 공통 데몬 줄뿐이면 어느 모듈도 표를 받지 않는다(모뎀 데몬 줄은 ofono/modem 후보가 된다 — 실제 modulefilter)
    common = {"ts": "2026-09-20T05:32:09.500Z", "tag": "mgmtd", "msg": "dbus signal", "level": "I", "category_hint": "common"}
    env.make_job(events=[common], explore=True, candidates=[])
    code, out, _ = env.module("explore")
    assert (code, out["reason"], out["next"]) == (1, "모듈 후보 없음", core.NEXT_BUILTIN)
    assert "모듈 문서 없음: 모듈 후보 없음" in env.report_line("- 탐색 분석")


def test_explore_timeline_mismatch(env):
    job = env.make_job(explore=True)
    (job / "timeline.md").write_text("changed\n", encoding="utf-8")
    code, out, err = env.module("explore", "--module", "ofono/data")
    assert (code, out["reason"]) == (2, "작업 없음") and "timeline.md가 events.json과 맞지 않는다" in err


def test_explore_failed_pick_drops_record(env, monkeypatch):
    job = env.make_job(events=EVENTS + [SIM_EVENT], explore=True)
    assert env.module("explore", "--choose", "data")[0] == 0
    assert "explore" in json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    mr.push(env.tmp / "remote", {"ofono/sim/explore.md": "# t\n\ngit push 하라\n"})
    code, out, _ = env.module("explore", "--choose", "sim")
    assert (code, out["reason"]) == (2, "점검(위험 지시)")
    assert "explore" not in json.loads((job / "module-skill.json").read_text(encoding="utf-8"))


def test_explore_android_view(env):
    env.url = mr.build(env.tmp / "remote2")
    env.user({"module_skills": {"remote": env.url}})
    android_events = [{"ts": "2026-09-20T05:32:09.000Z", "tag": "DCM-1", "msg": "setup failed", "level": "E",
                       "category_hint": "data"}]
    job = env.make_job(events=android_events, platform="android", explore=True)
    code, out, err = env.module("explore", "--module", "android/data", platform="android")
    assert code == 0, err
    assert out["read"][-1] == str(job / "module-skill" / "explore" / "timeline.md") and out["timeline"]["view"] is True
    text = (job / "report.md").read_text(encoding="utf-8")
    assert "  - 모듈 타임라인: 1/1줄, 잡음 0, 반복 접음 0, 미수집 com.example.Data" in text   # 모의 modules.yaml android/data dbus


def test_filter_timeout(env, monkeypatch):
    import common.modulefilter as mf
    monkeypatch.setattr(mf, "child", lambda payload, timeout=20.0: {"error": "timeout"})
    env.make_job(explore=True)
    code, out, _ = env.module("explore")
    assert (code, out["reason"], out["next"]) == (2, "modules.yaml", core.NEXT_ASK_BUILTIN)
    assert "받기 실패(modules.yaml)" in env.report_line("- 탐색 분석")


def test_filter_gets_ipc_prefix_from_site_defaults(env, monkeypatch):
    """모듈 필터 자식에 site-defaults `vendor_ipc.request_prefix`를 넘긴다(설정이 없으면 placeholder 기본)."""
    import common.modulefilter as mf
    from common import vendor_ipc
    seen = []
    monkeypatch.setattr(mf, "child", lambda payload, timeout=20.0: seen.append(payload) or {"error": "timeout"})
    env.make_job(explore=True)
    env.module("explore")
    assert seen and seen[0]["ipc_prefix"] == vendor_ipc.DEFAULT.request_prefix


# -- explore E0 -----------------------------------------------------------------------------------


def test_explore_stdout_module_skills(env):
    env.make_job(explore=True)
    code, out, _ = env.call("explore", KEY, "--out", env.job, "--platform", "ofono")
    assert code == 0 and out["module_skills"] is True and "mask_warnings" not in out
    env.user({})
    code, out, _ = env.call("explore", KEY, "--out", env.job, "--platform", "ofono")
    assert code == 0 and "module_skills" not in out


def test_explore_view_redacts(env):
    leaky = dict(EVENTS[0], msg="login password=hunter2secret9 ok")
    env.make_job(events=[leaky], explore=True)
    code, out, _ = env.call("explore", KEY, "--out", env.job, "--platform", "ofono")
    text = (env.job / "timeline.md").read_text(encoding="utf-8")
    assert code == 0 and "hunter2secret9" not in text and "<REDACTED:" in text
    assert out["mask_warnings"] and sum(out["mask_warnings"].values()) >= 1


# -- 실패와 종료 표 -------------------------------------------------------------------------------


def test_trace_module_row_only_when_trace_exists(env):
    # F7 확장: analyze가 연 trace가 있을 때만 정보 행 `module`(종료 코드·고른 모듈)을 덧붙이고, 없으면 만들지 않는다
    job = env.make_job()
    assert env.module()[0] == 0 and not (job / "trace.jsonl").exists()
    (job / "trace.jsonl").write_text("", encoding="utf-8")
    assert env.module()[0] == 0
    env.user({})
    assert env.module()[0] == 1
    rows = [json.loads(x) for x in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [{k: v for k, v in r.items() if k != "ts"} for r in rows] == [
        {"step": "module", "v": 2, "purpose": "deep", "exit": 0, "module": "ofono/data"},
        {"step": "module", "v": 2, "purpose": "deep", "exit": 1}]


def test_no_remote_ofono_exits_1_and_writes_nothing(env):
    job = env.make_job()
    env.user({})
    before = snapshot(job)
    code, out, err = env.module()
    assert (code, out) == (1, {"reason": "설정 없음", "next": core.NEXT_CONTINUE})
    assert not env.work.exists()
    after = snapshot(job)
    assert {k: v for k, v in after.items() if k != "report.md"} == {k: v for k, v in before.items() if k != "report.md"}
    assert env.report_line() == "- 심층 분석 생략: 설정 없음"


def test_explore_no_remote(env):
    env.make_job(explore=True)
    env.user({})
    code, out, _ = env.module("explore")
    assert (code, out["reason"], out["next"]) == (1, "설정 없음", core.NEXT_BUILTIN)
    assert "모듈 문서 없음: 모듈 스킬 레포 설정 없음" in env.report_line("- 탐색 분석")


def test_prefer_skill_without_skill_is_config_error(env):
    env.make_job()
    env.user({"module_skills": {"remote": env.url}, "platforms": {"ofono": {"analyzers": {"data": {"prefer": "skill"}}}}})
    code, out, err = env.module()
    assert (code, out["reason"]) == (2, "설정 오류") and "prefer: skill인데 skill" in err
    assert env.report_line().startswith("- 심층 분석 생략: 설정 오류(")


def test_remote_with_credentials_is_config_error(env):
    env.make_job()
    env.user({"module_skills": {"remote": "https://u:tk9tk9@ghe.example.invalid/o/r.git"}})
    code, out, err = env.module()
    assert (code, out["reason"]) == (2, "설정 오류") and "tk9tk9" not in json.dumps(out) + err


def test_job_preconditions(env):
    code, out, _ = env.module()
    assert (code, out["reason"]) == (2, "작업 없음")
    env.make_job(candidates=[])
    code, out, _ = env.module()
    assert (code, out["reason"], out["next"]) == (1, "분석 후보 없음", core.NEXT_CONTINUE)
    env.make_job()
    (env.job / "events.json").unlink()
    assert env.module()[1]["reason"] == "작업 없음"
    env.make_job()
    assert env.module("explore", "--module", "ofono/data")[1]["reason"] == "작업 없음"     # explore-input.json 없음


@pytest.mark.parametrize("extra, purpose", [
    (("--module", "ofono/data"), "deep"), (("--choose", "top"), "deep"), (("--at", "2026-09-20T05:32:10Z"), "deep"),
    (("--deep",), "deep"),
    (("--also",), "explore"), (("--choose", "top", "--module", "ofono/data"), "explore"),
    (("--at", "2026-09-20T05:32:10Z"), "explore"), (("--choose", "Bad!"), "explore"),
    (("--module", "android/data"), "explore"), (("--module", "ofono/_common"), "explore"),
])
def test_usage_errors(env, extra, purpose):
    env.make_job(explore=True)
    before = (env.job / "report.md").read_bytes()
    code, out, err = env.module(purpose, *extra)
    assert (code, out) == (2, {"reason": "사용 오류", "next": core.NEXT_FIX_CALL})
    assert err.startswith("사용 오류: ") and (env.job / "report.md").read_bytes() == before


def test_bad_key_usage_error(env):
    code, out, _ = env.call("module", "../x", "--for", "deep", "--out", env.tmp / "nojob", "--platform", "ofono")
    assert (code, out["reason"]) == (2, "사용 오류")


def test_module_not_listed_explore(env):
    env.make_job(explore=True)
    code, out, _ = env.module("explore", "--module", "ofono/call")
    assert code == 1 and out == {"reason": "레포에 ofono/call 없음", "module": "ofono/call",
                                 "sha": mr.head(env.tmp / "remote"), "next": core.NEXT_BUILTIN}


def test_deep_repo_missing_rewrites(env):
    env.make_job(candidates=[{"type": "IMS-001", "cause": "IMS-001-01", "category": "ims", "score": 1}])
    code, out, _ = env.module()
    assert code == 1 and out["reason"] == "레포에 ofono/ims 없음"
    assert env.report_line().startswith("- 심층 분석: 해당 없음(레포에 ofono/ims 없음 @")


@pytest.mark.skipif(not POSIX, reason="symlink")
def test_symlinked_record_refused(env):
    job = env.make_job()
    target = env.tmp / "elsewhere"
    target.mkdir()
    (job / "module-skill").symlink_to(target)
    code, out, _ = env.module()
    assert (code, out["reason"]) == (2, "작업 디렉토리 이상") and list(target.iterdir()) == []


def test_failure_leaves_job_unchanged(env):
    job = env.make_job()
    mr.push(env.tmp / "remote", {"ofono/data/CLAUDE.md": "x\n"})
    before = snapshot(job)
    code, out, _ = env.module()
    assert (code, out["reason"], out["next"]) == (2, "점검(자동 읽기 이름)", core.NEXT_CONTINUE)
    after = snapshot(job)
    assert {k: v for k, v in after.items() if k != "report.md"} == {k: v for k, v in before.items() if k != "report.md"}
    assert env.report_line() == "- 심층 분석 생략: 모듈 스킬 받기 실패(점검(자동 읽기 이름))"


def test_failure_does_not_overwrite_script_line(env):
    job = env.make_job()
    text = (job / "report.md").read_text(encoding="utf-8").replace(
        "- 심층 분석 (모듈 스킬 ofono, 1위 카테고리 data): 미실행 — TODO(LLM) 결과", "- 심층 분석 생략: 모듈 스킬 받기 실패(인증)")
    (job / "report.md").write_text(text, encoding="utf-8")
    env.user({"module_skills": {"remote": "file:///nonexistent/r.git"}})
    code, out, _ = env.module()
    assert (code, out["reason"]) == (2, "인증")
    assert env.report_line() == "- 심층 분석 생략: 모듈 스킬 받기 실패(인증)"


def test_write_failure_leaves_no_half_record(env, monkeypatch):
    job = env.make_job()
    assert env.module()[0] == 0
    old = snapshot(job / "module-skill" / "deep")
    real = os.replace

    def boom(src, dst, *a, **kw):
        if Path(dst).name == "deep" and Path(src).name.startswith(".deep.tmp-"):
            raise OSError(28, "No space left on device")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(modulecmd.os, "replace", boom)
    code, out, _ = env.module()
    assert (code, out["reason"]) == (2, "작업 디렉토리 이상")
    assert "deep" not in json.loads((job / "module-skill.json").read_text(encoding="utf-8"))
    assert snapshot(job / "module-skill" / "deep") == old


def test_stale_stage_dirs_cleaned(env):
    job = env.make_job()
    for name in (".deep.tmp-1-1", ".deep.old-1-1"):
        (job / "module-skill" / name).mkdir(parents=True)
    assert env.module()[0] == 0
    assert not (job / "module-skill" / ".deep.tmp-1-1").exists() and not (job / "module-skill" / ".deep.old-1-1").exists()


@pytest.mark.skipif(not POSIX, reason="sh 가짜 git")
def test_git_version_too_old(env, monkeypatch):
    env.make_job()
    bin_dir = env.tmp / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text("#!/bin/sh\necho 'git version 2.20.0'\n")
    (bin_dir / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    code, out, _ = env.module()
    assert (code, out["reason"]) == (2, "git 버전") and not env.work.exists()


@pytest.mark.skipif(not POSIX, reason="flock")
def test_lock_busy(env, monkeypatch):
    env.make_job()
    env.work.mkdir(parents=True)
    hold = ("import fcntl,os,sys,time\nfd=os.open(sys.argv[1],os.O_RDWR|os.O_CREAT,0o600)\n"
            "fcntl.flock(fd,fcntl.LOCK_EX)\nprint('ok',flush=True)\ntime.sleep(60)\n")
    proc = subprocess.Popen([sys.executable, "-c", hold, str(env.work / moduleskills.LOCK_FILE)], stdout=subprocess.PIPE,
                            text=True)
    try:
        assert proc.stdout.readline().strip() == "ok"
        monkeypatch.setenv(moduleskills.LOCK_WAIT_ENV, "0")
        code, out, _ = env.module()
        assert (code, out["reason"], out["next"]) == (2, "관리 clone 사용 중", core.NEXT_CONTINUE)
    finally:
        proc.kill()
        proc.wait()


def test_platform_reresolve_failure(env, monkeypatch):
    env.make_job()
    from platforms import session

    real = session.resolve

    def fake(defaults, name):
        if name == "ofono":
            raise triage.platforms.PlatformConfigError("깨진 설정")
        return real(defaults, name)

    monkeypatch.setattr(session, "resolve", fake)
    code, out, _ = env.call("module", KEY, "--for", "deep", "--out", env.job)
    assert (code, out["reason"], out["next"]) == (2, "설정 오류", core.NEXT_CONTINUE)


@pytest.mark.parametrize("bad, reason", [("sparse", "sparse"), ("ls-tree", "점검(트리)"), ("cat-file", "점검(읽기)")])
def test_git_faults(env, monkeypatch, bad, reason):
    env.make_job()
    real = moduleskills._git

    def fake(work, cwd, *args, **kw):
        if bad == "sparse" and args[:2] == ("sparse-checkout", "set"):
            return 1, "", "fatal: x"
        if bad == "ls-tree" and args[:1] == ("ls-tree",):
            return 128, "", "fatal: x"
        if bad == "cat-file" and args[:1] == ("cat-file",):
            return 0, b"x", ""
        return real(work, cwd, *args, **kw)

    monkeypatch.setattr(moduleskills, "_git", fake)
    code, out, _ = env.module()
    assert (code, out["reason"], out["next"]) == (2, reason, core.NEXT_CONTINUE)


def test_reasons_cover_exit_table():
    labels = set(modulecmd.REASONS)
    for label in ("설정 없음", "설치 스킬 못 찾음", "분석 후보 없음", "모듈 후보 없음", "사용 오류", "설정 오류", "작업 없음",
                  "작업 디렉토리 이상", "git 버전", "관리 clone 사용 중", "인증", "네트워크", "원격 브랜치 없음",
                  "관리 clone 불일치", "ff-only 실패", "modules.yaml", "sparse", "마스킹 점검 실패", "점검(원문 열람 지시)",
                  "점검(위험 지시)", "점검(링크)", "점검(트리)", "점검(읽기)"):
        assert label in labels, label
    assert "설치 스킬 사용 설정" not in labels


# -- 출력 경계(서브프로세스) ----------------------------------------------------------------------


def test_argparse_error_no_json(tmp_path):
    proc = run("triage.py", ["module", KEY, "--out", tmp_path], root=ROOT, env={"TELEPHONY_TRIAGE_HOME": tmp_path / "h"})
    assert proc.returncode == 2 and proc.stdout == ""


def test_resolve_failure_prints_json(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    (home / "config.yaml").write_text("platforms: {ofono: {issue_db: 3}}\n", encoding="utf-8")
    proc = run("triage.py", ["module", KEY, "--for", "deep", "--out", tmp_path, "--platform", "ofono"], root=ROOT,
               env={"TELEPHONY_TRIAGE_HOME": home})
    assert proc.returncode == 2 and json.loads(proc.stdout) == {"reason": "설정 오류"} and proc.stderr.strip()


def test_no_retracted_label_anywhere():
    """R1: `설치 스킬 사용 설정`은 코드·설계 문서 어디에도 없다."""
    proc = subprocess.run(["grep", "-r", "-l", "설치 스킬 사용 설정", str(REPO / "plugin"), str(REPO / "docs" / "design")],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 1 and proc.stdout == "", proc.stdout


def _android(env):
    events = [{"ts": "2026-09-20T05:32:09.000Z", "tag": "DCM-1", "msg": "setup failed", "level": "E", "category_hint": "data"}]
    return env.make_job(events=events, platform="android", explore=True)


def test_single_timeline_sub_and_at_recentre(env):
    job = _android(env)
    args = ("explore", "--module", "android/data")
    assert env.module(*args, platform="android")[0] == 0
    lock = env.home / "work" / moduleskills.LOCK_FILE
    mtime = lock.stat().st_mtime_ns
    (env.tmp / "remote" / "remote.git").rename(env.tmp / "remote" / "gone.git")      # --at은 받지 않는다
    code, out, err = env.module(*args, "--at", "2026-09-20T05:32:09Z", platform="android")
    assert code == 0, err
    assert out["at"] == "2026-09-20T05:32:09Z" and out["timeline"]["view"] is True and lock.stat().st_mtime_ns == mtime
    rec = json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["explore"]
    assert rec["center"] == "2026-09-20T05:32:09Z" and rec["timeline"]["sha256"] == sha(job / rec["timeline"]["path"])
    assert (job / "report.md").read_text(encoding="utf-8").count("  - 모듈 타임라인:") == 1
    code, out, _ = env.module(*args, "--at", "2030-01-01T00:00:00Z", platform="android")
    assert (code, out["reason"]) == (2, "사용 오류")           # 분석 범위 밖
    data = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    data["issue"]["summary"] = "바뀜"
    (job / "analysis.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out, err = env.module(*args, "--at", "2026-09-20T05:32:09Z", platform="android")
    assert (code, out["reason"]) == (2, "작업 없음") and "이전 분석 것" in err


# -- explore 정밀 탐색(--deep) ---------------------------------------------------------------------

DEEP_DOC = "# Android data — 정밀 탐색\n\n- 단계 사슬을 순서대로 본다.\n"


def _deep_android(env, n=300):
    """deep.md가 있는 원격 + 기본 줄 상한(150)을 넘는 android data 줄 n개."""
    env.url = mr.build(env.tmp / "remote-deep", extra={"android/data/deep.md": DEEP_DOC})
    env.user({"module_skills": {"remote": env.url}})
    events = [{"ts": f"2026-09-20T05:32:{i // 10:02d}.{i % 10}00Z", "tag": "DCM-1", "msg": f"setup failed step {i}",
               "level": "E", "category_hint": "data"} for i in range(n)]
    return env.make_job(events=events, platform="android", explore=True)


def _explore_rec(job: Path) -> dict:
    return json.loads((job / "module-skill.json").read_text(encoding="utf-8"))["explore"]


def test_explore_deep_reads_deep_md_and_widens_view(env):
    """`--deep`: read에 deep.md가 explore.md 뒤(타임라인 앞)에 붙고 보기 상한이 넓다. 플래그 없으면 상한·출력이 그대로."""
    import make_module_eval_inputs as gen

    job = _deep_android(env)
    folder = job / "module-skill" / "explore"
    tl = folder / "timeline.md"
    args = ("explore", "--module", "android/data")
    code, out, err = env.module(*args, platform="android")
    assert code == 0, err
    plain, plain_read = tl.read_bytes(), out["read"]
    assert [Path(r).name for r in plain_read] == ["layers.md", "components.md", "explore.md", "timeline.md"]
    assert out["timeline"]["lines"] == 150 and "deep" not in _explore_rec(job)
    code, out, err = env.module(*args, "--deep", platform="android")
    assert code == 0, err
    assert out["read"] == plain_read[:3] + [str(folder / "android" / "data" / "deep.md"), str(tl)]
    assert out["timeline"]["lines"] == 300 and _explore_rec(job)["deep"] is True
    assert (folder / "android" / "data" / "deep.md").read_text(encoding="utf-8") == DEEP_DOC
    code, out, err = env.module(*args, platform="android")                 # 다시 기본: 바이트 그대로
    assert code == 0 and tl.read_bytes() == plain and out["read"] == plain_read and "deep" not in _explore_rec(job)
    dummy = {"center": "c", "center_source": "s", "pins": [], "allow": []}

    def caps(**kw):
        got = modulecmd._explore_view_payload(job, KEY, "android", "data", dummy, {}, **kw)
        return got["cap_rows"], got["cap_bytes"]

    assert caps() == gen.VIEW_CAPS["explore"] == (150, 20480)               # 생성기(case 파일) 상한과 같다
    assert caps(deep=True) == (1_000_000, 98304)


def test_explore_deep_at_keeps_deep_caps(env):
    """`--at` 재개는 기록의 `deep`으로 같은 상한을 쓴다. 기본 기록에 `--at --deep`은 사용 오류(조용히 기본 상한 금지,
    기록·report 줄은 그대로)."""
    job = _deep_android(env)
    args = ("explore", "--module", "android/data")
    assert env.module(*args, platform="android")[0] == 0
    before = {n: (job / n).read_bytes() for n in ("module-skill.json", "report.md")}
    code, out, err = env.module(*args, "--at", "2026-09-20T05:32:05Z", "--deep", platform="android")
    assert (code, out) == (2, {"reason": "사용 오류", "next": core.NEXT_FIX_CALL}) and "--at 없이 먼저" in err
    assert {n: (job / n).read_bytes() for n in before} == before
    assert env.module(*args, "--deep", platform="android")[0] == 0
    code, out, err = env.module(*args, "--at", "2026-09-20T05:32:05Z", platform="android")
    assert code == 0, err
    assert out["timeline"]["lines"] == 300 and out["read"][-2].endswith("deep.md")
    rec = _explore_rec(job)
    assert rec["deep"] is True and rec["center"] == "2026-09-20T05:32:05Z"


def test_explore_deep_without_deep_md(env):
    """deep.md 없는 모듈에 `--deep`: 사용 오류(stderr `deep.md 없음`) — 앞서 받은 기록·report 줄은 그대로, 명령을 고치라는 next."""
    job = env.make_job(explore=True)
    assert env.module("explore", "--module", "ofono/data")[0] == 0
    before = {n: (job / n).read_bytes() for n in ("module-skill.json", "report.md")}
    tree = snapshot(job / "module-skill" / "explore")
    code, out, err = env.module("explore", "--module", "ofono/data", "--deep")
    assert code == 2 and out == {"reason": "사용 오류", "module": "ofono/data",
                                 "sha": mr.head(env.tmp / "remote"), "next": core.NEXT_FIX_CALL}
    assert "deep.md 없음" in err and "--deep 없이 다시" in err
    assert {n: (job / n).read_bytes() for n in before} == before and snapshot(job / "module-skill" / "explore") == tree


# -- explore 같이 보기(--with) ----------------------------------------------------------------------

WITH_EVENTS = [
    {"ts": "2026-09-20T05:32:09.000Z", "tag": "DCM-1", "msg": "setup failed", "level": "E", "category_hint": "data"},
    {"ts": "2026-09-20T05:32:08.000Z", "tag": "SIMSVC", "msg": "sim state ABSENT", "level": "E", "category_hint": "sim"},
    {"ts": "2026-09-20T05:32:07.000Z", "tag": "SIMSVC", "msg": "sim service state OUT_OF_SERVICE", "level": "I",
     "category_hint": "sim"},
]
WITH_ARGS = ("explore", "--module", "android/data")


def _with_job(env):
    return env.make_job(events=WITH_EVENTS, platform="android", explore=True)


def test_explore_with_adds_aux_section(env):
    """`--with sim`: 주 보기(data)는 그대로, 끝 `## 보조 모듈 줄 (sim)`에 주 보기에 없던 sim 줄만. 문서·read는 주 모듈만."""
    job = _with_job(env)
    tl = job / "module-skill" / "explore" / "timeline.md"
    code, plain_out, err = env.module(*WITH_ARGS, platform="android")
    assert code == 0, err
    plain = tl.read_text(encoding="utf-8")
    plain_line = env.report_line("- 탐색 분석")
    assert "## 보조 모듈 줄" not in plain and "with" not in _explore_rec(job) and "with" not in plain_out
    code, out, err = env.module(*WITH_ARGS, "--with", "sim", platform="android")
    assert code == 0, err
    text = tl.read_text(encoding="utf-8")
    head, sep, aux = text.partition("\n## 보조 모듈 줄 (sim)\n")
    assert sep and head == plain, text                                   # 주 보기 바이트 그대로 + 끝 절
    aux_lines = [x for x in aux.split("\n") if x]
    assert any("OUT_OF_SERVICE" in x for x in aux_lines) and "OUT_OF_SERVICE" not in plain   # 주 보기에 없던 줄
    assert "sim state ABSENT" in plain and not set(aux_lines) & set(plain.split("\n"))    # 주 보기와 겹치지 않는다
    assert out["read"] == plain_out["read"] and out["with"] == ["android/sim"] == _explore_rec(job)["with"]
    assert env.report_line("- 탐색 분석") == plain_line.replace("모듈 문서 android/data @", "모듈 문서 android/data+sim @")
    quote = next(x for x in aux_lines if "OUT_OF_SERVICE" in x)          # 보조 절 줄을 근거로 인용해도 원문 검사 통과
    (job / "explore-output.md").write_text("\n".join([
        "가설 1: 서비스 없음", "로그로 확인:", f"- {quote}", "코드로 추정: 코드 근거 없음", "반대 근거: 없음",
        "다음 확인: 망 등록 로그"]) + "\n", encoding="utf-8")
    code, data, err = env.call("check-output", KEY, "--for", "explore", "--out", job, "--platform", "android")
    assert code == 0 and data["evidence"].startswith("- 근거 원문 검사: 인용 1개 중 원문에 없음 0"), (data, err)


def test_explore_with_ask_switch(env):
    """약한 신호(주 모듈 오류 줄 없음)면 `ask_switch`에 같이 보기 하나, `--with` 실행에는 없다."""
    env.make_job(events=[dict(WITH_EVENTS[0], level="I", msg="setup request"), WITH_EVENTS[1]], platform="android",
                 explore=True)
    code, out, err = env.module(*WITH_ARGS, platform="android")
    assert code == 0, err
    assert out["ask_switch"]["options"] == ["그대로 data", "sim — 1줄", "data + sim 같이 보기"]
    code, out, err = env.module(*WITH_ARGS, "--with", "sim", platform="android")
    assert code == 0 and out["ask_switch"]["options"] == ["그대로 data", "sim — 1줄"], err


def test_explore_with_at_keeps_with(env):
    """`--at` 재실행은 기록의 `with`로 같은 보조 절을 다시 만든다(인자로는 받지 않는다)."""
    job = _with_job(env)
    assert env.module(*WITH_ARGS, "--with", "sim", platform="android")[0] == 0
    code, out, err = env.module(*WITH_ARGS, "--at", "2026-09-20T05:32:08Z", platform="android")
    assert code == 0, err
    assert out["with"] == ["android/sim"] == _explore_rec(job)["with"]
    assert "## 보조 모듈 줄 (sim)" in (job / "module-skill" / "explore" / "timeline.md").read_text(encoding="utf-8")
    assert "모듈 문서 android/data+sim @" in env.report_line("- 탐색 분석")


@pytest.mark.parametrize("bad", [["android/zzz"], ["android/data"], ["ofono/sim"], ["android/sim", "x"], "android/sim"])
def test_explore_at_rejects_tampered_with(env, bad):
    """기록의 `with`가 처음 받을 때의 검사(같은 플랫폼·다른 모듈·modules.yaml에 있음)를 못 넘으면 `--at`은 종료 2."""
    job = _with_job(env)
    assert env.module(*WITH_ARGS, "--with", "sim", platform="android")[0] == 0
    path = job / "module-skill.json"
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["explore"]["with"] = bad
    path.write_text(json.dumps(rec), encoding="utf-8")
    assert env.module(*WITH_ARGS, "--at", "2026-09-20T05:32:08Z", platform="android")[0] == 2


@pytest.mark.parametrize("purpose, extra", [
    ("deep", ("--with", "sim")),                                                  # deep은 --also 그대로
    ("explore", ("--with", "sim")),                                               # --module·--choose 없이
    ("explore", (*WITH_ARGS[1:], "--with", "data")),                              # 주 모듈과 같다
    ("explore", (*WITH_ARGS[1:], "--with", "ims")),                               # modules.yaml에 없다
    ("explore", (*WITH_ARGS[1:], "--with", "sim", "--at", "2026-09-20T05:32:08Z")),
])
def test_explore_with_usage_errors(env, purpose, extra):
    job = _with_job(env)
    assert env.module(*WITH_ARGS, platform="android")[0] == 0
    before = {n: (job / n).read_bytes() for n in ("module-skill.json", "report.md")}
    code, out, err = env.module(purpose, *extra, platform="android")
    assert code == 2 and out["reason"] == "사용 오류" and err.startswith("사용 오류: ")
    assert {n: (job / n).read_bytes() for n in before} == before


def test_explore_with_needs_filter(env):
    """모의 ofono `modules.yaml`에는 filter가 없다(보기 없음) — `--with`는 사용 오류, 기록·report 줄 그대로."""
    job = env.make_job(explore=True)
    assert env.module("explore", "--module", "ofono/data")[0] == 0
    before = {n: (job / n).read_bytes() for n in ("module-skill.json", "report.md")}
    code, out, err = env.module("explore", "--module", "ofono/data", "--with", "sim")
    assert code == 2 and out["reason"] == "사용 오류" and "filter" in err
    assert {n: (job / n).read_bytes() for n in before} == before


def test_ask_switch_offers_only_modules_with_explore():
    """R40(H C1+D): 약한 신호 질문은 받은 트리에 `<p>/<m>/explore.md`가 있는 모듈만 권한다(14 모듈, 일부는 없을 수 있다)."""
    stats = {"hot_modules": {"sim": 9, "network": 7, "ims": 3, "data": 20}}
    tree = frozenset({"ofono/data/explore.md", "ofono/network/explore.md", "ofono/ims/explore.md"})
    got = modulecmd._ask_switch("data", stats, [], tree=tree, platform="ofono")
    assert got["options"] == ["그대로 data", "network — 7줄", "ims — 3줄", "data + network 같이 보기"]
    assert "sim" not in got["question"]
    deep = modulecmd._ask_switch("data", stats, [], tree=tree | {"ofono/ims/deep.md"}, platform="ofono", deep=True)
    assert deep["options"] == ["그대로 data", "ims — 3줄", "data + ims 같이 보기"]     # --deep: deep.md도 있는 모듈만
    legacy = modulecmd._ask_switch("data", stats, [])                     # 트리를 모르면(--at) 예전처럼
    assert legacy["options"] == ["그대로 data", "sim — 9줄", "network — 7줄", "data + sim 같이 보기"]
    joined = modulecmd._ask_switch("data", stats, [], joined=True)        # --with로 받은 실행: 같이 보기 없음
    assert joined["options"] == ["그대로 data", "sim — 9줄", "network — 7줄"]
    assert modulecmd._ask_switch("data", {"hot_modules": {}}, [])["options"] == ["그대로 data"]
