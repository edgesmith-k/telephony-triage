"""이슈 시작 때 플랫폼 정하기 (17-platforms §11, K18 — "로그 자동 + 애매하면 질문", 10/30 사용자 결정 D1~D6).

- `platforms/sniff.py`: 켠 플랫폼의 `raw_line`·`capture.looks_like`로 파일 형식 판별(표본 200줄·256KiB, 비율 0.5, 최소 3줄)
- `triagelib/pick.py choose()`: 명시(`--answer platform=` > `--platform` > `TT_PLATFORM`) × 로그 형식 × Jira 대응표 × 이어 하는 작업
- 켠 플랫폼이 하나면(android 단독 등) 아무것도 읽지 않는다(바이트 동일)
- e2e(두 프로필): lock·JOB 전 질문, 답 재실행, 충돌 질문, 사용자 기본 platform을 로그가 이김(출력 `platform`, D5),
  hook이 암묵 work_dir에 둔 Jira 원문 옮기기, 로그 없음 → lock 전 logs 질문, pending 이어 하기, release가 다른 work_dir 작업을 찾음
"""

from __future__ import annotations

import argparse
import codecs
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_repo  # noqa: E402
from runner import plugin_root, tmp, variant_db  # noqa: E402
from workspace import Workspace  # noqa: E402

import platforms  # noqa: E402
from common import userconfig  # noqa: E402
from platforms import sniff  # noqa: E402
from triagelib import pick  # noqa: E402
from triagelib.core import Fail  # noqa: E402

LOGS = REPO / "tests" / "fixtures" / "logs"
ALOG = LOGS / "data-disabled.log"
OLOG = LOGS / "ofono" / "journal-iso.log"
MOCK_JIRA = REPO / "tests" / "mocks" / "jira" / "MOCK-1001.yaml"
NAMES = ["android", "ofono"]
ON = {"name": "android", "enabled": NAMES}
OFONO_REMOTE = "https://ghe.mock.invalid/mock-org/ofono-issue-db.git"
SCHEMA = {"TT_SCHEMA_CHECK": "1"}


def _write(path: Path, lines: list[str], encoding: str = "utf-8") -> Path:
    path.write_text("\n".join(lines) + "\n", encoding=encoding)
    return path


# -- sniff -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("log, want", [
    *[(p, ["android"]) for p in sorted(LOGS.glob("*.log"))],
    *[(p, ["ofono"]) for p in sorted((LOGS / "ofono").glob("*.log"))],
], ids=lambda v: v.name if isinstance(v, Path) else None)
def test_fixture_logs_detect_their_platform(log, want):
    assert sniff.file_match(log, NAMES) == want


def test_bugreport_text_and_zip_are_android_bundles(tmp_path):
    txt = _write(tmp_path / "bugreport.txt", ["== dumpstate: 2026-09-20 14:30:00", "plain text", "more text"])
    assert sniff.file_match(txt, NAMES) == ["android"]
    z = tmp_path / "bugreport.zip"
    with zipfile.ZipFile(z, "w") as fh:
        fh.writestr("x.txt", "x")
    assert sniff.file_match(z, NAMES) == ["android"]
    assert sniff.file_match(z, ["ofono"]) == []       # 켠 플랫폼 판별만 쓴다


def test_utf16_empty_unreadable_and_prose(tmp_path):
    lines = OLOG.read_text(encoding="utf-8").splitlines()
    u16 = tmp_path / "u16.log"
    u16.write_bytes(codecs.BOM_UTF16_LE + ("\n".join(lines) + "\n").encode("utf-16-le"))
    assert sniff.file_match(u16, NAMES) == ["ofono"]
    assert sniff.file_match(_write(tmp_path / "empty.log", [""]), NAMES) == []
    assert sniff.file_match(tmp_path / "missing.log", NAMES) == []
    assert sniff.file_match(_write(tmp_path / "prose.log", ["just some words"] * 10), NAMES) == []


def test_threshold_ratio_min_hits_and_sample_cap(tmp_path):
    raw = OLOG.read_text(encoding="utf-8").splitlines()[0]
    assert sniff.file_match(_write(tmp_path / "two.log", [raw, raw]), NAMES) == ["ofono"]           # 표본 2줄 → 2줄이면 충분
    assert sniff.file_match(_write(tmp_path / "few.log", [raw, raw] + ["prose"] * 3), NAMES) == []  # 2 < 3
    assert sniff.file_match(_write(tmp_path / "half.log", [raw] * 3 + ["prose"] * 3), NAMES) == ["ofono"]
    assert sniff.file_match(_write(tmp_path / "less.log", [raw] * 3 + ["prose"] * 4), NAMES) == []
    late = _write(tmp_path / "late.log", ["prose"] * sniff.SAMPLE_LINES + [raw] * 500)              # 앞 200줄만 본다
    assert sniff.file_match(late, NAMES) == []


def test_sniff_summary_mixed_and_unknown(tmp_path):
    prose = _write(tmp_path / "prose.txt", ["words"] * 5)
    assert sniff.sniff([OLOG, prose], NAMES) == {"files": [{"index": 0, "match": ["ofono"]}, {"index": 1, "match": []}],
                                                  "platforms": ["ofono"], "unknown": 1}
    assert sniff.sniff([OLOG, ALOG], NAMES)["platforms"] == ["android", "ofono"]
    assert sniff.sniff([prose], NAMES)["platforms"] == []


def test_sniff_module_is_not_a_platform():
    assert "sniff" not in platforms.known()


# -- detect 설정 -------------------------------------------------------------------------------------


def _detect(values=None, path="fields.components[].name", **platform) -> dict:
    return {"platform": {**ON, **platform, "detect": {"tracker_field": {"path": path, "values": values or {"Data": "ofono"}}}}}


def test_detect_rules_valid_and_default_off():
    assert platforms.detect_rules({"platform": ON}) is None
    assert platforms.detect_rules({"platform": {**ON, "detect": {}}}) is None
    assert platforms.detect_rules(_detect()) == {"path": "fields.components[].name", "values": {"Data": "ofono"}}
    assert platforms.load(_detect()).name == "android"


@pytest.mark.parametrize("defaults, needle", [
    (_detect(values={"Data": "nosuch"}), "platform.detect.tracker_field.values.Data"),
    (_detect(path=""), "platform.detect.tracker_field.path"),
    ({"platform": {**ON, "detect": {"other": 1}}}, "platform.detect.other"),
    ({"platform": {**ON, "detect": {"tracker_field": {"path": "x", "values": {}}}}}, "platform.detect.tracker_field.values"),
    ({"platform": {"name": "android", "detect": {"tracker_field": {"path": "x", "values": {"v": "ofono"}}}}}, "켠 플랫폼"),
])
def test_detect_rules_errors(defaults, needle):
    with pytest.raises(platforms.PlatformConfigError, match=needle.replace(".", r"\.")):
        platforms.detect_rules(defaults)
    with pytest.raises(platforms.PlatformConfigError):
        platforms.load(defaults)


def test_no_platform_block_keys_use_detect():
    assert all("detect" not in platforms.get(n).block_keys for n in platforms.known())


# -- choose() 표 ---------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv(userconfig.HOME_ENV, str(tmp_path / "home"))
    monkeypatch.delenv(platforms.ENV, raising=False)
    return tmp_path / "home"


def _user(home: Path, **extra) -> None:
    home.mkdir(parents=True, exist_ok=True)
    cfg = {"work_dir": str(home / "work"), "platforms": {"ofono": {"work_dir": str(home / "work-ofono")}}, **extra}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")


def _args(defaults, *, logs=None, platform=None, answer=None, more=None, issue_file=None, key="MOCK-1001"):
    from platforms import session
    args = argparse.Namespace(offline_db=None, answer=answer, logs=logs, more_logs=more, platform=platform, key=key,
                              issue_file=issue_file, issue_raw=None)
    args.platform_name, args.platform_cfg = session.resolve(defaults, platform)
    return args


def _choose(defaults, **kw):
    args = _args(defaults, **kw)
    return args, pick.choose(args, defaults, kw.get("key", "MOCK-1001"))


def _state(home: Path, platform: str, data: dict, key: str = "MOCK-1001") -> None:
    work = home / ("work" if platform == "android" else f"work-{platform}") / key
    work.mkdir(parents=True, exist_ok=True)
    (work / "triage-state.json").write_text(json.dumps(data), encoding="utf-8")


def test_single_platform_reads_nothing(home, monkeypatch):
    _user(home)
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("읽으면 안 된다"))  # noqa: E731
    monkeypatch.setattr(sniff, "open_log", boom)
    monkeypatch.setattr(sniff, "file_match", boom)
    defaults = {"platform": {"name": "android"}}
    args = _args(defaults, logs=[str(OLOG)], answer=["platform=android"])
    monkeypatch.setattr(userconfig, "load_user", boom)
    assert pick.choose(args, defaults, "MOCK-1001") is None
    assert not hasattr(args, "platform_implicit") and args.answer == ["platform=android"]    # 지금 동작 그대로
    args.offline_db = "/x"
    assert pick.choose(args, {"platform": ON}, "MOCK-1001") is None                          # --offline-db도 안 읽는다


def test_logs_pick_platform_and_note(home):
    _user(home)
    defaults = {"platform": ON}
    args, out = _choose(defaults, logs=[str(OLOG)])
    assert out is None and args.platform_name == "ofono" and args.platform_implicit == "android"
    assert args.platform_pick == {"platform": "ofono", "source": "logs", "note": "로그 형식으로 oFono 선택 (기본 Android 대신)",
                                  "line": "플랫폼: oFono (로그 형식으로 선택)"}
    args, out = _choose(defaults, logs=[str(ALOG)])
    assert out is None and args.platform_name == "android" and args.platform_pick["note"] == "로그 형식으로 Android 선택"


def test_unknown_files_are_ignored_with_note(home, tmp_path):
    _user(home)
    prose = _write(tmp_path / "notes.txt", ["words"] * 5)
    args, out = _choose({"platform": ON}, logs=[str(OLOG), str(prose)])
    assert out is None and args.platform_name == "ofono"
    assert args.platform_pick["note"].endswith("형식 미확인 파일 1개는 판별에서 뺐다")


def test_mixed_and_unknown_logs_ask(home, tmp_path):
    _user(home)
    _, out = _choose({"platform": ON}, logs=[str(OLOG), str(ALOG)])
    ni = out["needs_input"]
    assert out["status"] == "needs_input" and out["lock_owner"] is None and ni["kind"] == "platform"
    assert ni["answer"] == "--answer platform=<값>" and "f0 oFono, f1 Android" in ni["question"]
    assert str(OLOG) not in json.dumps(out) and OLOG.name not in json.dumps(out)       # 경로·파일 이름 없음
    assert [o["value"] for o in ni["options"]] == ["android", "ofono"]
    prose = _write(tmp_path / "notes.txt", ["words"] * 5)
    _, out = _choose({"platform": ON}, logs=[str(prose)])
    assert "로그 형식을 알 수 없다" in out["needs_input"]["question"]
    assert out["needs_input"]["options"][0] == {"value": "android", "label": "Android (기본)"}


def test_user_default_loses_to_logs_but_explicit_conflict_asks(home, monkeypatch):
    _user(home, platform="ofono")
    defaults = {"platform": ON}
    args, out = _choose(defaults, logs=[str(ALOG)])                    # D1: 사용자 platform은 기본값
    assert out is None and args.platform_name == "android" and args.platform_implicit == "ofono"
    assert args.platform_pick["note"] == "로그 형식으로 Android 선택 (기본 oFono 대신)"
    _, out = _choose(defaults, logs=[str(ALOG)], platform="ofono")     # D2: 명시와 로그 형식이 다르면 묻는다
    assert out["needs_input"]["options"] == [{"value": "ofono", "label": "oFono (지정)"},
                                             {"value": "android", "label": "Android (로그 형식)"}]
    assert out["needs_input"]["question"] == "지정한 플랫폼은 oFono인데 로그 형식은 Android다. 어느 플랫폼으로 분석할까?"
    monkeypatch.setenv(platforms.ENV, "ofono")
    _, out = _choose(defaults, logs=[str(ALOG)])                       # TT_PLATFORM도 명시
    assert out["needs_input"]["kind"] == "platform"
    monkeypatch.delenv(platforms.ENV)
    args, out = _choose(defaults, logs=[str(OLOG)], platform="ofono")  # 같으면 지금 동작(노트 없음)
    assert out is None and args.platform_name == "ofono" and args.platform_pick is None


def test_answer_wins_and_is_removed_from_answers(home):
    _user(home)
    args, out = _choose({"platform": ON}, logs=[str(ALOG)], platform="android", answer=["code=skip", "platform=ofono"])
    assert out is None and args.platform_name == "ofono" and args.answer == ["code=skip"]
    assert args.platform_pick["source"] == "answer"
    with pytest.raises(Fail) as err:
        _choose({"platform": ON}, logs=[str(ALOG)], answer=["platform=nosuch"])
    assert err.value.code == 2 and "켜져 있지 않습니다" in str(err.value)


def test_no_logs_asks_logs_before_lock_with_all_log_dirs(home):
    adir, odir = home / "alogs", home / "ologs"
    adir.mkdir(parents=True)
    odir.mkdir()
    _write(adir / "a.log", ["x"])
    _write(odir / "o.log", ["x"])
    _user(home, log_dir=str(adir))
    cfg = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"]["ofono"]["log_dir"] = str(odir)
    (home / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    _, out = _choose({"platform": ON})
    assert out["needs_input"]["kind"] == "logs" and out["needs_input"]["question"] == pick.LOGS_QUESTION
    assert sorted(o["label"] for o in out["needs_input"]["options"]) == ["a.log (Android)", "o.log (oFono)"]
    _, out = _choose({"platform": ON}, platform="ofono")      # 명시가 있으면 지금처럼 Driver가 묻는다
    assert out is None


def test_resume_pending_and_conflict(home):
    _user(home)
    defaults = {"platform": ON}
    _state(home, "ofono", {"pending": {"kind": "code"}, "platform": "ofono"})
    args, out = _choose(defaults, logs=[str(OLOG), str(ALOG)])          # 섞인 로그 + 이어 하는 작업 → 그 플랫폼
    assert out is None and args.platform_name == "ofono" and args.platform_pick["source"] == "resume"
    _, out = _choose(defaults, logs=[str(ALOG)])                         # 로그 형식과 다르면 묻는다
    assert out["needs_input"]["kind"] == "platform" and "이어 하는 작업: oFono" in out["needs_input"]["question"]
    _, out = _choose(defaults, logs=[str(OLOG)], platform="android")     # 명시와 다른 로그 형식 → 이어 하는 작업이 같아도 답이 아니면 묻는다(D2)
    assert out["lock_owner"] is None and [o["label"] for o in out["needs_input"]["options"]] == ["Android (지정)", "oFono (로그 형식)"]
    args, out = _choose(defaults)                                        # 로그 없이 이어 하기
    assert out is None and args.platform_name == "ofono"
    _state(home, "ofono", {"platform": "ofono", "job": {"logs": [{"path": "x"}]}})     # 끝난 oFono 작업 + --more-logs도 같다
    _, out = _choose(defaults, more=[str(OLOG)], platform="android")
    assert out["needs_input"]["kind"] == "platform"
    _state(home, "android", {"job": {"logs": [{"path": "x"}]}})
    _, out = _choose(defaults)                                           # 이어 하는 작업이 둘이면 표 없음 → logs 질문
    assert out["needs_input"]["kind"] == "logs"


def test_jira_mapping_vote_and_conflict(home):
    _user(home)
    defaults = _detect()
    args, out = _choose(defaults, logs=[str(OLOG)], issue_file=str(MOCK_JIRA))
    assert out is None and args.platform_name == "ofono" and args.platform_pick["source"] == "logs"
    _, out = _choose(defaults, logs=[str(ALOG)], issue_file=str(MOCK_JIRA))
    q = out["needs_input"]["question"]
    assert "Jira fields.components[].name: oFono" in q and "Data" not in q          # 트래커 값은 내지 않는다
    args, out = _choose(defaults, logs=[str(OLOG), str(ALOG)], issue_file=str(MOCK_JIRA))
    assert out is None and args.platform_pick["note"] == "Jira fields.components[].name 값으로 oFono 선택 (기본 Android 대신)"
    raw = home / "work" / "MOCK-1001"                                    # hook이 암묵 work_dir에 둔 원문도 읽는다
    raw.mkdir(parents=True)
    (raw / "issue_raw.json").write_text(MOCK_JIRA.read_text(encoding="utf-8"), encoding="utf-8")
    args, out = _choose(defaults, logs=[str(OLOG), str(ALOG)])
    assert out is None and args.platform_name == "ofono"
    with pytest.raises(Fail):
        _choose(_detect(values={"Data": "nosuch"}), logs=[str(OLOG)])


def test_missing_log_file_leaves_it_to_driver(home, tmp_path):
    _user(home)
    args, out = _choose({"platform": ON}, logs=[str(tmp_path / "nope.log")])
    assert out is None and args.platform_name == "android" and args.platform_pick is None


# -- e2e (두 프로필, 실제 triage.py) ---------------------------------------------------------------------


def _env(user_platform: str | None = None, log_dirs: bool = False, **site) -> dict:
    ws = Workspace(root=plugin_root("detect-on", platform={**ON, **site}))
    info = make_repo.make(variant_db("issue-db-ofono"), ws.base / "ofono-repo")
    owork = ws.base / "work-ofono"
    cfg = yaml.safe_load((ws.home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"] = {"ofono": {"issue_db": {"path": str(info["clone"]), "remote": OFONO_REMOTE}, "work_dir": str(owork)}}
    if user_platform:
        cfg["platform"] = user_platform
    if log_dirs:
        for at, name, src in ((cfg, "alogs", ALOG), (cfg["platforms"]["ofono"], "ologs", OLOG)):
            folder = ws.base / name
            folder.mkdir()
            (folder / src.name).write_bytes(src.read_bytes())
            at["log_dir"] = str(folder)
    (ws.home / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return {"ws": ws, "owork": owork}


def _run(env, *args, issue=True) -> dict:
    extra = ["--issue-file", MOCK_JIRA] if issue else []
    proc = env["ws"].run("triage.py", ["run", "MOCK-1001", "--analysis-only", *extra, "--code", "skip", *args], env=SCHEMA)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _trace(job: Path) -> list[dict]:
    return [json.loads(x) for x in (job / "trace.jsonl").read_text(encoding="utf-8").splitlines()]


def _nothing(env) -> bool:
    ws = env["ws"]
    return not (ws.work / "MOCK-1001").exists() and not (env["owork"] / "MOCK-1001").exists() \
        and not (ws.work / "session.lock").exists() and not (env["owork"] / "session.lock").exists()


def test_e2e_logs_pick_mixed_asks_and_answer_reruns():
    env = _env()
    ws, owork = env["ws"], env["owork"]
    mixed = _run(env, "--logs", OLOG, ALOG)
    assert mixed["status"] == "needs_input" and mixed["needs_input"]["kind"] == "platform" and _nothing(env)
    done = _run(env, "--logs", OLOG, ALOG, "--answer", "platform=ofono")
    assert done["status"] == "ok" and done["platform"] == "ofono" and done["notes"] == ["답한 플랫폼(oFono)으로 분석 (기본 Android 대신)"]
    job = owork / "MOCK-1001"
    assert {"step": "platform", "platform": "ofono", "source": "answer"}.items() <= next(
        r for r in _trace(job) if r["step"] == "platform").items()
    state = json.loads((job / "triage-state.json").read_text(encoding="utf-8"))
    assert "platform" not in state["answers"] and state["platform"] == "ofono"
    assert "- 플랫폼: oFono (답한 플랫폼)" in (job / "report.md").read_text(encoding="utf-8")
    assert not (ws.work / "MOCK-1001").exists()
    # 로그만 주면 형식으로 정한다(같은 작업, 이어서)
    again = _run(env, "--logs", OLOG)
    assert again["platform"] == "ofono" and again["notes"][0] == "로그 형식으로 oFono 선택 (기본 Android 대신)"
    assert again["candidates"][0]["type"] == "DATA-001"
    assert "- 플랫폼: oFono (로그 형식으로 선택)" in (job / "report.md").read_text(encoding="utf-8")


def test_e2e_explicit_conflict_and_user_default():
    env = _env(user_platform="ofono")
    asked = _run(env, "--logs", ALOG, "--platform", "ofono")
    assert asked["needs_input"]["kind"] == "platform" and "platform" not in asked and _nothing(env)
    done = _run(env, "--logs", ALOG)                                     # 사용자 기본 ofono를 로그 형식이 이긴다
    assert done["status"] == "ok" and done["platform"] == "android"      # D5: 암묵 선택(ofono)과 다르면 android여도 낸다
    assert done["notes"][0] == "로그 형식으로 Android 선택 (기본 oFono 대신)"
    assert (env["ws"].work / "MOCK-1001" / "analysis.json").is_file() and not (env["owork"] / "MOCK-1001").exists()


def test_e2e_hook_raw_in_implicit_work_dir_is_moved():
    env = _env()
    ws, owork = env["ws"], env["owork"]
    for extra in ([], ["--platform", "ofono"]):        # 명시 --platform에도 같은 틈이 있었다
        raw_dir = ws.work / "MOCK-1001"                # hook은 암묵 선택(android) work_dir에 둔다
        raw_dir.mkdir(parents=True)
        (raw_dir / "issue_raw.json").write_text(MOCK_JIRA.read_text(encoding="utf-8"), encoding="utf-8")
        done = _run(env, "--logs", OLOG, *extra, issue=False)
        assert done["status"] == "ok" and done["platform"] == "ofono" and done["issue"]["origin"] == "mcp"
        assert not raw_dir.exists()                    # 옮긴 뒤 빈 디렉토리는 지운다
        assert not (owork / "MOCK-1001" / "issue_raw.json").exists()     # --consume
        assert any(r["step"] == "platform-raw" for r in _trace(owork / "MOCK-1001"))


def test_e2e_no_logs_asks_before_lock_then_pending_resume_and_release():
    env = _env(log_dirs=True)
    ws, owork = env["ws"], env["owork"]
    asked = _run(env)
    assert asked["needs_input"]["kind"] == "logs" and _nothing(env)
    assert sorted(o["label"] for o in asked["needs_input"]["options"]) == [f"{ALOG.name} (Android)", f"{OLOG.name} (oFono)"]
    # 섞인 로그 + 답 → 코드 질문에서 멈춤(pending code, lock 보유)
    proc = ws.run("triage.py", ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA, "--logs", OLOG, ALOG,
                                "--answer", "platform=ofono"], env=SCHEMA)
    first = json.loads(proc.stdout)
    assert first["status"] == "needs_input" and first["needs_input"]["kind"] == "code" and first["platform"] == "ofono"
    # 스킬이 --answer platform=을 빼고 다시 불러도 이어 하는 작업으로 ofono
    proc = ws.run("triage.py", ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA, "--logs", OLOG, ALOG,
                                "--answer", "code=skip"], env=SCHEMA)
    done = json.loads(proc.stdout)
    assert done["status"] == "ok" and done["platform"] == "ofono", proc.stderr
    assert done["notes"][0].startswith("이어 하는 작업의 플랫폼(oFono)")
    assert (owork / "session.lock").exists() and not (ws.work / "MOCK-1001").exists()
    # explore·release는 --platform 없이도 KEY 작업이 있는 다른 work_dir를 찾는다(explore: 작업은 찾았고 후보가 있어 해당 없음 = 1)
    explore = ws.run("triage.py", ["explore", "MOCK-1001"])
    assert explore.returncode == 1 and "해당 없음" in explore.stderr
    released = ws.json("triage.py", ["release", "MOCK-1001"])
    assert released["released"] is True and not (owork / "session.lock").exists()


# -- 리뷰 보완: 답의 지속(P1-1)·지정과 다른 출력(P1-2)·읽기 오류(P2) ----------------------------------------------


def test_answered_job_persists_without_answer_explicit_and_jira(home):
    """앞선 실행이 `--answer platform=`으로 정해 질문에서 멈춘 작업(`pending`+`platform_answer`)은 답을 뺀 재실행에서 다시 묻지 않는다."""
    _user(home)
    defaults = _detect()
    # 시나리오 A: --platform ofono + Android 로그 → ofono로 답함 → 재실행은 답 없이 같은 --platform
    _state(home, "ofono", {"pending": {"kind": "code"}, "platform": "ofono"})
    _, out = _choose({"platform": ON}, logs=[str(ALOG)], platform="ofono")         # 답 표시가 없으면 D2대로 묻는다
    assert out["needs_input"]["kind"] == "platform"
    _state(home, "ofono", {"pending": {"kind": "code"}, "platform": "ofono", "platform_answer": "ofono"})
    args, out = _choose({"platform": ON}, logs=[str(ALOG)], platform="ofono")
    assert out is None and args.platform_name == "ofono" and args.platform_pick["source"] == "resume"
    assert args.platform_pick["answered"] is True
    # 시나리오 B: 명시 없음, 로그 android·Jira ofono 충돌 → ofono로 답함 → 답 없이(또는 출력 platform으로 --platform ofono) 재실행
    for extra in ({}, {"platform": "ofono"}):
        args, out = _choose(defaults, logs=[str(ALOG)], issue_file=str(MOCK_JIRA), **extra)
        assert out is None and args.platform_name == "ofono" and args.platform_pick["answered"] is True
    # 대칭: --platform android + oFono 로그 → android로 답함
    _state(home, "ofono", {"platform": "ofono"})                                    # pending 없음 → 답 표시는 쓰지 않는다
    _state(home, "android", {"pending": {"kind": "code"}, "platform_answer": "android"})
    args, out = _choose({"platform": ON}, logs=[str(OLOG)], platform="android")
    assert out is None and args.platform_name == "android"
    args, out = _choose({"platform": ON}, logs=[str(ALOG)], platform="ofono")    # 옛 지정 + 답과 같은 로그 형식(resume == fmt)
    assert out is None and args.platform_name == "android" and args.platform_pick["answered"] is True
    # 새 답이 앞선 답보다 앞서고, 명시가 로그 형식과 같으면 명시대로
    args, out = _choose({"platform": ON}, logs=[str(OLOG)], answer=["platform=ofono"])
    assert out is None and args.platform_name == "ofono" and args.platform_pick["source"] == "answer"
    args, out = _choose({"platform": ON}, logs=[str(OLOG)], platform="ofono")
    assert out is None and args.platform_name == "ofono" and args.platform_pick is None


def test_several_resume_jobs_prefer_answered_then_latest(home):
    """리뷰 2차 P1: 이어 하는 작업이 여럿이면 답으로 정한 작업만, 둘 이상이면 `pending.asked_at`이 늦은 쪽(같으면 없음)."""
    _user(home)
    defaults = {"platform": ON}
    t0, t1, t2 = "2026-10-30T01:00:00+00:00", "2026-10-30T01:05:00+00:00", "2026-10-30T01:09:00+00:00"
    _state(home, "ofono", {"pending": {"kind": "code", "asked_at": t0}, "platform": "ofono"})
    _state(home, "android", {"pending": {"kind": "code", "asked_at": t1}, "platform_answer": "android"})
    args, out = _choose(defaults, logs=[str(OLOG)], platform="android", answer=["code=skip"])   # (a) 새 답은 Driver로
    assert out is None and args.platform_name == "android" and args.answer == ["code=skip"]
    assert args.platform_pick["source"] == "resume" and args.platform_pick["answered"] is True
    args, out = _choose(defaults, logs=[str(OLOG)])                                            # (b) 명시 없음
    assert out is None and args.platform_name == "android" and args.platform_pick["source"] == "resume"
    _state(home, "ofono", {"pending": {"kind": "code", "asked_at": t2}, "platform": "ofono", "platform_answer": "ofono"})
    args, out = _choose(defaults, logs=[str(OLOG)], platform="android")                       # (c) 답한 작업 둘 → 늦은 쪽
    assert out is None and args.platform_name == "ofono" and args.platform_pick["answered"] is True
    _state(home, "ofono", {"pending": {"kind": "code", "asked_at": t1}, "platform": "ofono", "platform_answer": "ofono"})
    assert _choose(defaults, logs=[str(OLOG)], platform="android")[1]["needs_input"]["kind"] == "platform"   # 같은 시각
    _state(home, "ofono", {"pending": {"kind": "code", "asked_at": t2}, "platform": "ofono"})
    _state(home, "android", {"pending": {"kind": "code", "asked_at": t1}})
    args, out = _choose(defaults, logs=[str(ALOG)])                                           # 답 없는 작업끼리는 고르지 않음
    assert out is None and args.platform_name == "android" and args.platform_pick["source"] == "logs"


def test_stale_answer_after_other_platform_activity_is_not_used(home):
    """리뷰 3차 P1: 답한 뒤 다른 플랫폼 작업이 묻거나 끝났으면(답을 버리고 옮겨 감) 남은 답이 D2를 덮지 않는다 — 답은 그 질문이
    이 KEY의 가장 늦은 활동일 때만 쓴다(다른 켠 플랫폼 작업의 마지막 질문·완료가 더 이르면 쓰고, 같은 초면 쓰지 않는다, §11-3)."""
    _user(home)
    defaults = {"platform": ON}
    t0, t1, t2 = "2026-10-30T01:00:00+00:00", "2026-10-30T01:05:00+00:00", "2026-10-30T01:09:00+00:00"
    _state(home, "android", {"pending": {"kind": "code", "asked_at": t1}, "platform_answer": "android"})     # t1에 android로 답함
    for ofono in ({"pending": {"kind": "code", "asked_at": t2}, "platform": "ofono"},                      # 그 뒤 oFono가 물음
                  {"platform": "ofono", "job": {"logs": [{"path": "o"}], "runs": [{"n": 1, "at": t2}]}}):  # 그 뒤 oFono가 끝남
        _state(home, "ofono", ofono)
        _, out = _choose(defaults, logs=[str(ALOG)], platform="ofono")        # 지정 ≠ 로그 형식 → 버린 답으로 잇지 않고 D2
        assert out["needs_input"]["kind"] == "platform"
        assert [o["label"] for o in out["needs_input"]["options"]] == ["oFono (지정)", "Android (로그 형식)"]
        _, out = _choose(defaults, more=[str(ALOG)], platform="ofono")
        assert out["needs_input"]["kind"] == "platform"
        _, out = _choose(defaults)                                             # 이어 하는 작업 둘·쓸 답 없음 → logs 질문
        assert out["needs_input"]["kind"] == "logs"
    _state(home, "ofono", {"platform": "ofono", "job": {"logs": [{"path": "o"}], "runs": [{"n": 1, "at": t0}]}})
    args, out = _choose(defaults, logs=[str(ALOG)], platform="ofono")         # 대조: 다른 작업이 답보다 이르면 답을 쓴다
    assert out is None and args.platform_name == "android" and args.platform_pick["source"] == "resume"
    assert args.platform_pick["answered"] is True
    _state(home, "ofono", {"pending": {"kind": "code", "asked_at": t1}, "platform": "ofono"})
    _, out = _choose(defaults, logs=[str(ALOG)], platform="ofono")            # 답과 같은 초 → 어느 쪽이 늦은지 몰라 D2
    assert out["needs_input"]["kind"] == "platform"
    _state(home, "android", {"pending": {"kind": "code", "asked_at": t2}, "platform_answer": "android"})
    args, out = _choose(defaults, logs=[str(ALOG)], platform="ofono")         # Android가 더 늦게 다시 물음 → 답을 쓴다(반복 없음)
    assert out is None and args.platform_name == "android" and args.platform_pick["answered"] is True


def test_answer_without_asked_at(home):
    """시각(`pending.asked_at`·`job.runs[-1].at`)이 없는 작업(옛 상태 파일 등)은 답을 막지 않지만, 시각 없는 답은 시각 있는 다른
    작업보다 늦다고 볼 수 없어 쓰지 않는다(§11-3)."""
    _user(home)
    defaults = {"platform": ON}
    t1 = "2026-10-30T01:05:00+00:00"
    _state(home, "android", {"pending": {"kind": "code"}, "platform_answer": "android"})                   # asked_at 없는 답
    # (i) 다른 플랫폼 작업(질문 중·끝난 작업)에도 시각이 없으면 답을 쓴다: 지정 oFono + Android 로그인데 묻지 않고 Android로 잇는다
    for ofono in ({"pending": {"kind": "code"}, "platform": "ofono"},
                  {"platform": "ofono", "job": {"logs": [{"path": "o"}], "runs": [{"n": 1}]}}):
        _state(home, "ofono", ofono)
        args, out = _choose(defaults, logs=[str(ALOG)], platform="ofono")
        assert out is None and args.platform_name == "android" and args.platform_pick["answered"] is True
    # (ii) 시각 없는 답 + 시각 있는 oFono 질문 → 답을 쓰지 않는다: 지정 Android + oFono 로그는 D2로 묻는다(답을 쓰면 묻지 않는다)
    _state(home, "ofono", {"pending": {"kind": "code", "asked_at": t1}, "platform": "ofono"})
    _, out = _choose(defaults, logs=[str(OLOG)], platform="android")
    assert [o["label"] for o in out["needs_input"]["options"]] == ["Android (지정)", "oFono (로그 형식)"]
    # (iii) 답한 작업 둘 다 시각 없음 → 가장 늦은 하나를 못 정해 답을 쓰지 않는다: 어느 답을 써도 묻지 않을 조합인데 D2로 묻는다
    _state(home, "ofono", {"pending": {"kind": "code"}, "platform": "ofono", "platform_answer": "ofono"})
    _, out = _choose(defaults, logs=[str(OLOG)], platform="android")
    assert out["needs_input"]["kind"] == "platform"
    # (iv) 시각 있는 Android 답 + 시각 없는 oFono 답 → Android 답을 쓴다: 명시 없이 oFono 로그여도 로그 형식보다 앞선다
    # (답을 쓰지 않으면 로그 형식으로 oFono, oFono 답을 쓰면 이어 하는 작업 oFono)
    _state(home, "android", {"pending": {"kind": "code", "asked_at": t1}, "platform_answer": "android"})
    args, out = _choose(defaults, logs=[str(OLOG)])
    assert out is None and args.platform_name == "android" and args.platform_pick["source"] == "resume"
    assert args.platform_pick["answered"] is True


def test_sample_reads_bounded_without_newlines(tmp_path, monkeypatch):
    monkeypatch.setattr(sniff, "SAMPLE_BYTES", 1024)
    blob = tmp_path / "capture.bin"
    blob.write_text("x" * 50_000, encoding="utf-8")                  # 개행 없는 큰 파일
    seen = []
    real = sniff.open_log

    def spy(path):
        fh = real(path)
        orig = fh.readline
        fh.readline = lambda size=-1: (seen.append(size), orig(size))[1]     # noqa: E731
        return fh
    monkeypatch.setattr(sniff, "open_log", spy)
    lines = sniff._sample(blob)
    assert seen and all(0 < s <= 1024 for s in seen) and sum(map(len, lines)) <= 1024
    assert sniff.file_match(blob, NAMES) == []


def test_ask_logs_skips_unreadable_folder_and_vanished_file(home, monkeypatch):
    adir, odir = home / "alogs", home / "ologs"
    adir.mkdir(parents=True)
    odir.mkdir()
    _write(adir / "a.log", ["x"])
    _write(odir / "o.log", ["x"])
    _user(home, log_dir=str(adir))
    cfg = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    cfg["platforms"]["ofono"]["log_dir"] = str(odir)
    (home / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    real_iter, real_is_file = Path.iterdir, Path.is_file

    def iterdir(self):
        if self == odir:
            raise PermissionError(13, "Permission denied")
        out = list(real_iter(self))
        return iter(out + [adir / "gone.log"] if self == adir else out)     # 목록 뒤 사라진 파일(stat이 실패)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    monkeypatch.setattr(Path, "is_file", lambda self: True if self.name == "gone.log" else real_is_file(self))
    _, out = _choose({"platform": ON})
    assert out["needs_input"]["kind"] == "logs" and out["lock_owner"] is None
    assert [o["label"] for o in out["needs_input"]["options"]] == ["a.log (Android)"]


def test_adopt_raw_move_failure_fails_cleanly(home, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from triagelib import driver as driver_mod
    _user(home)
    src_dir = home / "work" / "MOCK-1001"
    src_dir.mkdir(parents=True)
    src = src_dir / "issue_raw.json"
    src.write_text("{}", encoding="utf-8")
    dest_dir = home / "work-ofono" / "MOCK-1001"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "issue_raw.json"

    def boom(*a, **k):
        raise OSError(18, "Invalid cross-device link")

    def half_move(s, d):
        Path(d).write_text("{", encoding="utf-8")                   # 반쯤 복사하고 실패
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(driver_mod.os, "replace", boom)
    monkeypatch.setattr(driver_mod.shutil, "move", half_move)
    fake = SimpleNamespace(picked="android", platform="ofono", defaults={"platform": ON}, key="MOCK-1001",
                           run=SimpleNamespace(note=lambda *a, **k: None))
    with pytest.raises(Fail) as err:
        driver_mod.Driver.adopt_raw(fake, dest)
    assert err.value.code == 2 and "Jira 원문을 옮기지 못했다" in str(err.value) and "Permission denied" in str(err.value)
    assert src.is_file() and not dest.exists()                     # 원문은 그대로, 반쪽 파일은 지웠다


def test_find_job_ignores_dir_with_only_raw(home, monkeypatch):
    import importlib
    triage = importlib.import_module("triage")
    from platforms import session
    _user(home)
    defaults = {"platform": ON}
    raw_only = home / "work" / "MOCK-1001"
    raw_only.mkdir(parents=True)
    (raw_only / "issue_raw.json").write_text("{}", encoding="utf-8")     # hook이 남긴 원문만
    _state(home, "ofono", {"platform": "ofono"})
    args = argparse.Namespace(platform=None)
    args.platform_name, args.platform_cfg = session.resolve(defaults, None)
    triage._find_job(args, defaults, "MOCK-1001")
    assert args.platform_name == "ofono"
    _state(home, "android", {"owner": "x"})                              # 선택 플랫폼에 작업이 있으면 그대로
    args.platform_name, args.platform_cfg = session.resolve(defaults, None)
    triage._find_job(args, defaults, "MOCK-1001")
    assert args.platform_name == "android"


def test_e2e_explicit_conflict_answer_persists_and_override_is_output():
    """P1-1 시나리오 A(e2e): `--platform ofono` + Android 로그 → ofono로 답해 질문에서 멈춤 → 답 없이 재실행해도 다시 묻지 않는다.
    P1-2: 지정(`--platform ofono`)과 다른 android를 답하면 출력에 `platform: android`(이후 호출에 --platform android)."""
    env = _env()
    ws, owork = env["ws"], env["owork"]
    base = ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA, "--logs", ALOG, "--platform", "ofono"]
    first = json.loads(ws.run("triage.py", [*base, "--answer", "platform=ofono"], env=SCHEMA).stdout)
    assert first["status"] == "needs_input" and first["needs_input"]["kind"] == "code" and first["platform"] == "ofono"
    state = json.loads((owork / "MOCK-1001" / "triage-state.json").read_text(encoding="utf-8"))
    assert state["platform_answer"] == "ofono" and "platform" not in state["answers"]
    proc = ws.run("triage.py", [*base, "--answer", "code=skip"], env=SCHEMA)
    done = json.loads(proc.stdout)
    assert done["status"] == "ok" and done["platform"] == "ofono", proc.stderr
    assert done["notes"][0].startswith("이어 하는 작업의 플랫폼(oFono)")
    assert ws.json("triage.py", ["release", "MOCK-1001", "--platform", "ofono"])["released"] is True
    # P1-2: 같은 지정에 android를 답함 → android는 기본(암묵)이지만 지정과 달라 출력에 낸다(질문 출력에도)
    env = _env()
    ws = env["ws"]
    asked = json.loads(ws.run("triage.py", [*base, "--answer", "platform=android"], env=SCHEMA).stdout)
    assert asked["status"] == "needs_input" and asked["needs_input"]["kind"] == "code" and asked["platform"] == "android"
    proc = ws.run("triage.py", [*base, "--answer", "code=skip"], env=SCHEMA)       # 스킬이 아직 --platform ofono를 붙여도
    done = json.loads(proc.stdout)
    assert done["status"] == "ok" and done["platform"] == "android", proc.stderr
    assert json.loads((ws.work / "MOCK-1001" / "analysis.json").read_text(encoding="utf-8"))["platform"] == "android"
    assert not (env["owork"] / "MOCK-1001").exists()


def test_e2e_correction_after_auto_pick_resumes_answered_job():
    """리뷰 2차 P1(e2e): R0 자동 선택(로그 형식 oFono)이 코드 질문에서 멈춤 → R1 사용자가 `--platform android`로 바로잡음 → D2 질문
    → R2 android로 답해 Android 작업이 코드 질문에서 멈춤 → R3 `--answer code=skip`만 주면 답으로 정한 Android 작업을 잇는다
    (플랫폼 질문 없이 코드 답이 Driver에 닿는다). 버려진 oFono 작업의 `pending`은 그대로 남는다. R2 전에 1초 쉰다: R2 질문이
    R0 질문보다 늦어야(같은 초면 막는다) 답이 이 KEY의 가장 늦은 활동이다(§11-3)."""
    env = _env()
    ws, owork = env["ws"], env["owork"]
    base = ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA, "--logs", OLOG]
    first = json.loads(ws.run("triage.py", base, env=SCHEMA).stdout)
    assert first["needs_input"]["kind"] == "code" and first["platform"] == "ofono"           # R0
    fixed = [*base, "--platform", "android"]
    assert json.loads(ws.run("triage.py", fixed, env=SCHEMA).stdout)["needs_input"]["kind"] == "platform"   # R1 D2
    time.sleep(1)  # 사람이 답하는 시간: R0·R2 질문이 같은 초면 어느 쪽이 늦은지 몰라 다시 묻는다(§11-3)
    second = json.loads(ws.run("triage.py", [*fixed, "--answer", "platform=android"], env=SCHEMA).stdout)
    assert second["needs_input"]["kind"] == "code" and "platform" not in second               # R2
    proc = ws.run("triage.py", [*fixed, "--answer", "code=skip"], env=SCHEMA)                 # R3: 새 답만
    done = json.loads(proc.stdout)
    assert done["status"] == "ok" and "platform" not in done, proc.stderr
    assert done["notes"][0].startswith("이어 하는 작업의 플랫폼(Android)")
    assert json.loads((owork / "MOCK-1001" / "triage-state.json").read_text(encoding="utf-8"))["pending"]["kind"] == "code"


def test_e2e_jira_conflict_answer_persists():
    """P1-1 시나리오 B(e2e): 명시 없음, 로그 android·Jira 대응표 ofono → ofono로 답해 멈춤 → 답 없이, 또는 출력 platform으로
    `--platform ofono`를 붙여 재실행해도 다시 묻지 않는다."""
    env = _env(detect={"tracker_field": {"path": "fields.components[].name", "values": {"Data": "ofono"}}})
    ws = env["ws"]
    base = ["run", "MOCK-1001", "--dry-run", "--issue-file", MOCK_JIRA, "--logs", ALOG]
    asked = json.loads(ws.run("triage.py", base, env=SCHEMA).stdout)
    assert asked["needs_input"]["kind"] == "platform" and _nothing(env)
    first = json.loads(ws.run("triage.py", [*base, "--answer", "platform=ofono"], env=SCHEMA).stdout)
    assert first["needs_input"]["kind"] == "code" and first["platform"] == "ofono"
    again = json.loads(ws.run("triage.py", base, env=SCHEMA).stdout)                      # 답 없이 → code 질문 그대로
    assert again["needs_input"]["kind"] == "code" and again["platform"] == "ofono"
    proc = ws.run("triage.py", [*base, "--platform", "ofono", "--answer", "code=skip"], env=SCHEMA)
    done = json.loads(proc.stdout)
    assert done["status"] == "ok" and done["platform"] == "ofono", proc.stderr
