import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
import usage_stats  # noqa: E402

START = "2026-10-01T00:00:00+00:00"
START_EPOCH = 1790812800   # 2026-10-01T00:00:00Z


def _job(root: Path, key: str, plan: dict, answers: dict, files=()):
    d = root / key
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (d / "triage-state.json").write_text(json.dumps({"answers": answers}), encoding="utf-8")
    for f in files:
        (d / f).write_text("{}", encoding="utf-8")
    return d


def test_three_numbers_from_three_jobs(tmp_path):
    (tmp_path / "_snapshot").mkdir()
    done = _job(tmp_path, "A-1", {"started_at": START, "pr": {"number": 1}}, {"time": "x", "anchor": "off"})
    os.utime(done / "plan.json", (START_EPOCH + 1800, START_EPOCH + 1800))                          # PR까지 30분
    _job(tmp_path, "A-2", {"started_at": START}, {"time": "x", "year": "2026", "code": "c"})        # 취소
    _job(tmp_path, "A-3", {"started_at": START}, {}, files=["state.json"])                          # 진행 중
    s = usage_stats.stats(tmp_path)
    assert (s["cancelled"], s["started"], s["pr_jobs"]) == (1, 3, 1)
    assert s["pr_minutes"] == 30
    assert s["questions"] == (1 + 3 + 0) / 3


@pytest.mark.parametrize("pushed_files", [["state.json"], []])     # push 기록은 state.json 유무와 무관하게 취소가 아니다
def test_pr_counts_only_with_number_and_pushed_without_pr_is_separate(tmp_path, pushed_files):
    # pr.branch는 계획 시작부터 있으므로 pr 키 유무로 PR 완료를 판단하지 않는다
    _job(tmp_path, "B-1", {"started_at": START, "pr": {"number": None, "branch": "issue/MOCK-1", "head_sha": None}}, {})
    _job(tmp_path, "B-2", {"started_at": START, "pr": {"number": None, "branch": "issue/MOCK-2", "head_sha": "a" * 40}},
         {}, files=pushed_files)
    s = usage_stats.stats(tmp_path)
    assert (s["started"], s["pr_jobs"], s["cancelled"], s["pushed_no_pr"]) == (2, 0, 1, 1)


@pytest.fixture
def two_platforms(tmp_path, monkeypatch, capsys):
    """android work_dir(작업 0건)·ofono work_dir(PR 작업 1건)을 가진 사용자 config와 `main` 호출 도우미."""
    import yaml

    sys.path.insert(0, str(REPO / "tests" / "helpers"))
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import platforms
    from common import userconfig
    from runner import plugin_root

    root = plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv(userconfig.HOME_ENV, str(home))
    monkeypatch.delenv(platforms.ENV, raising=False)
    wa, wo = tmp_path / "wa", tmp_path / "wo"
    _job(wa, "A-1", {"started_at": START}, {})
    _job(wo, "O-1", {"started_at": START, "pr": {"number": 1}}, {})
    _job(wo, "O-2", {"started_at": START, "pr": {"number": 2}}, {})
    data = {"work_dir": str(wa), "platforms": {"ofono": {"work_dir": str(wo)}}}

    def write(**over):
        (home / "config.yaml").write_text(yaml.safe_dump({**data, **over}), encoding="utf-8")

    def main(*args):
        code = usage_stats.main([*args, "--plugin-root", str(root)])
        return code, capsys.readouterr()

    write()
    return {"main": main, "write": write, "wa": wa, "wo": wo, "env": platforms.ENV, "mp": monkeypatch}


def test_default_platform_is_android_and_first_line_names_target(two_platforms):
    code, out = two_platforms["main"]()
    lines = out.out.splitlines()
    assert code == 0 and lines[0] == f"집계 대상: 플랫폼 android · work_dir {two_platforms['wa']}"
    assert "PR 작업 0건" in out.out and "중도 취소 1/1" in out.out


def test_user_config_platform_and_env_select_ofono(two_platforms):
    two_platforms["write"](platform="ofono")
    code, out = two_platforms["main"]()
    assert code == 0 and out.out.startswith(f"집계 대상: 플랫폼 ofono · work_dir {two_platforms['wo']}")
    assert "PR 작업 2건" in out.out
    two_platforms["write"]()
    two_platforms["mp"].setenv(two_platforms["env"], "ofono")
    code, out = two_platforms["main"]()
    assert code == 0 and out.out.startswith("집계 대상: 플랫폼 ofono") and "PR 작업 2건" in out.out
    code, out = two_platforms["main"]("--platform", "android")       # --platform이 TT_PLATFORM보다 우선
    assert code == 0 and "PR 작업 0건" in out.out


def test_explicit_work_dir_and_errors(two_platforms, tmp_path):
    main = two_platforms["main"]
    code, out = main("--work-dir", str(two_platforms["wo"]))
    assert code == 0 and out.out.splitlines()[0] == f"집계 대상: work_dir {two_platforms['wo']} (--work-dir 지정)"
    assert "PR 작업 2건" in out.out
    with pytest.raises(SystemExit) as exc:                            # 둘은 함께 쓸 수 없다(argparse)
        main("--work-dir", str(two_platforms["wo"]), "--platform", "android")
    assert exc.value.code == 2
    code, out = main("--work-dir", str(tmp_path / "nope"))
    assert code == 2 and "work_dir가 없다" in out.err
    code, out = main("--platform", "nosuch")
    assert code == 2 and "nosuch" in out.err


def test_json_output_has_counts_only(two_platforms):
    code, out = two_platforms["main"]("--work-dir", str(two_platforms["wo"]), "--json")
    data = json.loads(out.out)
    assert code == 0 and data["platform"] is None and data["work_dir"] == str(two_platforms["wo"])
    assert (data["pr_jobs"], data["started"], data["cancelled"]) == (2, 2, 0)
