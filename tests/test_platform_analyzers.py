"""분석 스킬(Step 5-1)·탐색 지식(Step 5-2)의 플랫폼 분리 (17-platforms §10, 10/30 사용자 결정).

- 최상위 `analyzers`(site·사용자)는 android 것이다. 그 밖 플랫폼은 site `platforms.<p>.analyzers` 위에 사용자
  `platforms.<p>.analyzers`를 얹은 것만 쓰고 android 것을 **물려받지 않는다**(없으면 심층 분석 해당 없음).
- 사용자 config `platforms.<p>.analyzers`는 경로 프로필(`PROFILE_KEYS`) 밖 별도 키(`PLATFORM_SCOPED_KEYS`)로 허용.
- site `platforms:` 오류(`platforms.android`·모르는 키·모양)는 사용자 흐름 종료 2, doctor는 경고 목록.
- 리포트 `when: never` 줄의 키 경로는 그 플랫폼 것(android 문구는 그대로).
- `triage.py explore`는 android가 아닐 때만 `platform`·`refs`(플러그인 `reference/platforms/<p>/*.md`)를 더한다.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(SCRIPTS))

from runner import plugin_root, run, run_json, tmp, variant_db  # noqa: E402

import platforms  # noqa: E402
from common import userconfig  # noqa: E402
from platforms import session  # noqa: E402

LOGS = REPO / "tests" / "fixtures" / "logs" / "ofono"
ON = {"name": "android", "enabled": ["android", "ofono"]}
EXAMPLE = yaml.safe_load((REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8"))
OFONO_AN = {"data": {"skill": "mock-ofono-analyzer", "when": "ask"}}
NO_ANALYZER_LINE = "- 심층 분석: 해당 없음(1위 카테고리에 분석 스킬 설정 없음)"


def _defaults(**over) -> dict:
    data = copy.deepcopy(EXAMPLE)
    data.update(over)
    return data


# -- merged: 층·물려받지 않음 ---------------------------------------------------------------------------


def test_other_platform_does_not_inherit_android_analyzers():
    user = {"analyzers": {"data": {"skill": "my-android", "source": "/src/android"}},
            "platforms": {"ofono": {"issue_db": {"path": "/x/ofono-db"}}}}
    cfg = userconfig.merged(_defaults(platform=ON), user, platform="ofono")
    assert "analyzers" not in cfg                                # site·사용자 최상위(android) 모두 버린다
    assert userconfig.merged(_defaults(platform=ON), user)["analyzers"]["data"]["skill"] == "my-android"


def test_site_and_user_platform_analyzers_deep_merge():
    defaults = _defaults(platform=ON, platforms={"ofono": {"analyzers": {**OFONO_AN, "call": {"skill": "c"}}}})
    user = {"platforms": {"ofono": {"analyzers": {"data": {"source": "/src/ofono", "when": "always"}}}}}
    cfg = userconfig.merged(defaults, user, platform="ofono")
    assert cfg["analyzers"] == {"data": {"skill": "mock-ofono-analyzer", "when": "always", "source": "/src/ofono"},
                                "call": {"skill": "c"}}
    assert defaults["platforms"]["ofono"]["analyzers"]["data"] == OFONO_AN["data"]     # 원본은 그대로


def test_android_merged_ignores_site_platforms_block():
    user = {"issue_db": {"path": "/x/db"}, "analyzers": {"data": {"when": "never"}}}
    plain = userconfig.merged(_defaults(), user)
    with_block = userconfig.merged(_defaults(platforms={"ofono": {"analyzers": OFONO_AN}}), user)
    assert plain == with_block and plain["analyzers"]["data"]["skill"] == "mock-data-analyzer"
    assert userconfig.merged(_defaults(), user, platform="android") == plain


# -- 검사: 사용자 config·site-defaults -----------------------------------------------------------------


def test_user_platform_analyzers_allowed_and_checked():
    ok = {"platforms": {"ofono": {"analyzers": {"data": {"skill": "x"}}}}}
    assert userconfig.profile_problems(ok) == []
    bad = userconfig.profile_problems({"platforms": {"ofono": {"analyzers": ["x"]}}})
    assert len(bad) == 1 and bad[0].startswith("platforms.ofono.analyzers:")
    bad = userconfig.profile_problems({"platforms": {"ofono": {"analyzers": {"data": "x"}}}})
    assert bad and bad[0].startswith("platforms.ofono.analyzers.data:")
    still = userconfig.profile_problems({"platforms": {"ofono": {"source_tree": {}}}})
    assert still and "platforms.ofono.source_tree" in still[0]                  # 상수 키는 계속 거부(RF-4)
    assert "analyzers" not in userconfig.PROFILE_KEYS                           # 최상위 PROFILE_KEYS = android 프로필 있음
    assert userconfig.profile_key("ofono", "analyzers.data.source") == "platforms.ofono.analyzers.data.source"
    assert userconfig.profile_key(None, "analyzers.data.source") == "analyzers.data.source"
    with pytest.raises(ValueError):
        userconfig.profile_key("ofono", "tracker.kind")


@pytest.mark.parametrize("block, needle", [
    ({"android": {"analyzers": OFONO_AN}}, "platforms.android"),
    ({"oFono": {"analyzers": OFONO_AN}}, "platforms.oFono"),
    ({"ofono": {"tracker": {}}}, "platforms.ofono.tracker"),
    ({"ofono": {"analyzers": "x"}}, "platforms.ofono.analyzers"),
    ({"ofono": {"analyzers": {"data": ["x"]}}}, "platforms.ofono.analyzers.data"),
    ({"ofono": "x"}, "platforms.ofono"),
    ("x", "platforms"),
])
def test_site_platform_problems_resolve_exit_and_lenient(block, needle):
    defaults = _defaults(platform=ON, platforms=block)
    problems = userconfig.site_platform_problems(defaults)
    assert problems and needle in problems[0]
    with pytest.raises(platforms.PlatformConfigError) as exc:
        session.resolve(defaults, "ofono", {})
    assert needle in str(exc.value) and "site-defaults는 관리자" in str(exc.value)
    name, _cfg, lenient = session.resolve_lenient(defaults, None, {})
    assert name == "android" and any(needle in p for p in lenient)
    userconfig.merged(defaults, {}, platform="ofono")               # 잘못된 모양이어도 merged·guard 경로는 예외 없음
    userconfig.analyzer_sources(defaults, {"platforms": block})


def test_valid_site_platforms_resolve():
    defaults = _defaults(platform=ON, platforms={"ofono": {"analyzers": OFONO_AN}})
    assert userconfig.site_platform_problems(defaults) == [] and userconfig.site_platform_problems(_defaults()) == []
    name, cfg = session.resolve(defaults, "ofono", {})
    assert name == "ofono" and cfg["analyzers"] == OFONO_AN


def test_analyzer_sources_union_of_all_layers_and_platforms():
    defaults = {"analyzers": {"data": {"source": "/s/a"}}, "platforms": {"ofono": {"analyzers": {"data": {"source": "/s/o"}}}}}
    user = {"analyzers": {"call": {"source": "/u/a"}, "x": "bad"},
            "platforms": {"ofono": {"analyzers": {"data": {"source": "/u/o"}}}, "Bad": {"analyzers": {"d": {"source": "/u/b"}}}}}
    assert userconfig.analyzer_sources(defaults, user) == ["/s/a", "/s/o", "/u/a", "/u/o", "/u/b"]
    assert userconfig.analyzer_sources(None, None) == [] and userconfig.analyzer_sources({"analyzers": 3}, {"platforms": []}) == []


# -- config.py: set --platform·init --force ------------------------------------------------------------


def test_config_set_and_init_keep_platform_analyzers():
    root = plugin_root("ofono-on", platform=ON)
    home = tmp("tt-plat-an-")
    env = {"TELEPHONY_TRIAGE_HOME": home}
    src = home / "skill-src"
    (home / "config.yaml").write_text(yaml.safe_dump({
        "user": {"ghe_id": "u"}, "issue_db": {"path": str(home / "db"), "remote": "https://x.invalid/o/db.git"},
        "work_dir": str(home / "work"),
        "platforms": {"ofono": {"issue_db": {"path": str(home / "odb"), "remote": "https://x.invalid/o/odb.git"}}}}),
        encoding="utf-8")
    out = run_json("config.py", ["set", "--platform", "ofono", "analyzers.data.source", str(src)], root=root, env=env)
    assert out["key"] == "platforms.ofono.analyzers.data.source"
    answers = home / "a.json"
    answers.write_text(json.dumps({"issue_db.path": str(home / "odb2"), "issue_db.remote": "https://x.invalid/o/odb.git"}),
                       encoding="utf-8")
    proc = run("config.py", ["init", "--platform", "ofono", "--force", "--answers", str(answers)], root=root, env=env)
    assert proc.returncode == 0, proc.stderr
    data = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
    assert data["platforms"]["ofono"]["analyzers"] == {"data": {"source": str(src)}}
    assert data["platforms"]["ofono"]["issue_db"]["path"] == str(home / "odb2") and "analyzers" not in data


# -- 드라이버·리포트 (오프라인) ------------------------------------------------------------------------


def _ofono_offline(root: Path, log: Path, occurred: str) -> tuple[dict, str, Path]:
    work = tmp("tt-plat-an-")
    meta = work / "meta.json"
    meta.write_text(json.dumps({"key": "MOCK-9001", "occurred_at": occurred, "summary": "x", "platform_version": "2"}),
                    encoding="utf-8")
    args = ["run", "MOCK-9001", "--offline-db", variant_db("issue-db-ofono"), "--logs", log, "--issue-meta", meta,
            "--out", work / "job", "--platform", "ofono"]
    run_json("triage.py", args, root=root, env={"TELEPHONY_TRIAGE_HOME": work / "home"})
    analysis = json.loads((work / "job" / "analysis.json").read_text(encoding="utf-8"))
    return analysis, (work / "job" / "report.md").read_text(encoding="utf-8"), work


def test_ofono_gets_no_android_analyzer():
    """example site-defaults의 `analyzers.data`(android 모의 스킬)는 oFono DATA 후보에 제안되지 않는다."""
    analysis, report, _ = _ofono_offline(plugin_root("ofono-on", platform=ON), LOGS / "journal-iso.log",
                                         "2026-09-20T05:32:10Z")
    assert analysis["candidates"][0]["cause"] == "DATA-001-01"
    assert analysis.get("analyzer") is None
    assert NO_ANALYZER_LINE in report and "mock-data-analyzer" not in report


@pytest.mark.parametrize("when, line", [
    ("ask", "- 심층 분석 (mock-ofono-analyzer): "),
    ("never", "- 심층 분석 생략: platforms.ofono.analyzers.data.when: never"),
])
def test_ofono_site_platform_analyzer(when, line):
    root = plugin_root(f"ofono-an-{when}", platform=ON,
                       platforms={"ofono": {"analyzers": {"data": {"skill": "mock-ofono-analyzer", "when": when}}}})
    analysis, report, _ = _ofono_offline(root, LOGS / "journal-iso.log", "2026-09-20T05:32:10Z")
    assert analysis["analyzer"] == {"skill": "mock-ofono-analyzer", "when": when}
    assert line in report


# -- 탐색 지식 refs ----------------------------------------------------------------------------------------


def test_ofono_explore_reports_platform_refs():
    root = plugin_root("ofono-on", platform=ON)
    analysis, _report, work = _ofono_offline(root, LOGS / "journal-multi.log", "2026-09-20T05:40:01Z")
    assert not analysis.get("candidates") and analysis["explore"]["reason"] == "no_candidate"
    env = {"TELEPHONY_TRIAGE_HOME": work / "home"}
    out = run_json("triage.py", ["explore", "MOCK-9001", "--out", work / "job", "--platform", "ofono"], root=root, env=env)
    assert out["platform"] == "ofono" and out["refs"] == ["reference/platforms/ofono/log-guide.md"]
    assert (root / "skills" / "telephony-triage" / out["refs"][0]).is_file()
    # 작업 플랫폼은 analysis.json 기준: 선택(android 기본)과 달라도 그 작업의 refs
    again = run_json("triage.py", ["explore", "MOCK-9001", "--out", work / "job"], root=root, env=env)
    assert again == out
    # android 작업(analysis.json에 platform 없음)이면 키가 그대로다
    data = json.loads((work / "job" / "analysis.json").read_text(encoding="utf-8"))
    data.pop("platform")
    (work / "job" / "analysis.json").write_text(json.dumps(data), encoding="utf-8")
    plain = run_json("triage.py", ["explore", "MOCK-9001", "--out", work / "job"], root=root, env=env)
    assert set(plain) == {"timeline", "lines", "total"}
