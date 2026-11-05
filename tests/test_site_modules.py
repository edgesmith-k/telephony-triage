"""tools/site_step.py modules·site_checks MS-1·MS-2 (F, MODULE_SKILLS_PLAN_IMPL §6): 모듈 스킬 사내 트랙.

네트워크·API 없음. 모듈 레포는 `tests/helpers/module_remote.py`의 file:// bare 원격, 이슈 DB는 변형 DB를 tmp git 레포로 쓴다.
gh는 PATH의 스텁(`stub_path`) 또는 `Ctx.gh` 바꿔치기, claude는 불리면 표식을 남기는 스텁이다.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "helpers"))
import module_remote as mr  # noqa: E402
import runner  # noqa: E402
import site_checks as sc  # noqa: E402
import site_step as ss  # noqa: E402
from tests.test_site_checks import by_id, site_root  # noqa: E402
from tests.test_site_step import stub_path  # noqa: E402

MS1_IDS = ["ms1.config", "ms1.git", "ms1.remote", "ms1.push", "ms1.tree", "ms1.repo_check", "ms1.tags", "ms1.prefer",
           "ms1.nested_claude", "ms1.protection", "ms1.ci", "ms1.coverage"]
S3_DONE = "- 완료 단계: S-1 (2026-10-01), S-2 (2026-10-02), S-3 (2026-10-03)"


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GH_HOST", "invalid.example")
    monkeypatch.setenv("PATH", os.pathsep.join([str(ROOT / "tests" / "mocks" / "bin"), os.environ["PATH"]]))


def make_site(tmp_path, defaults: dict | None = None, extra: dict | None = None, inputs: str = "", dbs: bool = True) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = site_root(tmp_path)
    remote = mr.build(tmp_path / "mod", extra=extra)
    d = {"module_skills": {"remote": remote}}
    d.update(defaults or {})
    (root / "plugin").mkdir()
    (root / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    if dbs:
        ofono = runner.git_db(runner.variant_db("issue-db-ofono-modules"))
        ops = runner.git_db()
        inputs = f"ofono_db: {ofono}\nops_db: {ops}\n" + inputs
    if inputs:
        (root / sc.STEPS_FILE).parent.mkdir(parents=True, exist_ok=True)
        (root / sc.STEPS_FILE).write_text(inputs, encoding="utf-8")
    return root, remote


def run_ms1(root: Path, allow_api: bool = False) -> dict:
    return by_id(sc.run_checks("MS-1", root, allow_api))


def test_ms1_rows_order_and_ids():
    assert [sc.check_id(f) for f in sc.MODULE_CHECKS["MS-1"]] == MS1_IDS
    assert [sc.check_id(f) for f in sc.MODULE_CHECKS["MS-2"]] == ["ms2.audit", "ms2.merge", "ms2.module_eval"]
    assert set(sc.CHECKS) == set(ss.STEPS) | set(ss.OFONO_STEPS)          # MS는 따로 둔 표(test_site_step와 같은 조건)
    assert set(sc.MODULE_CHECKS) == set(ss.MODULE_STEPS)


def test_ms1_pass_with_mock_remote(tmp_path):
    root, remote = make_site(tmp_path)
    out = run_ms1(root)
    assert list(out) == MS1_IDS
    st = {k: v["status"] for k, v in out.items()}
    assert st["ms1.config"] == "pass" and "site-defaults" in out["ms1.config"]["evidence"]
    assert str(tmp_path) not in out["ms1.config"]["evidence"]            # 주소는 redact_remote로만
    assert st["ms1.git"] == "pass" and st["ms1.remote"] == "pass" and out["ms1.remote"]["evidence"].startswith("main ")
    assert st["ms1.push"] == "info" and st["ms1.protection"] == "info"   # file:// 원격
    assert st["ms1.tree"] == "pass", out["ms1.tree"]["evidence"]
    assert "계획 2×7 중" in out["ms1.tree"]["evidence"]
    assert st["ms1.repo_check"] == "pass", out["ms1.repo_check"]["evidence"]
    assert st["ms1.tags"] == "pass", out["ms1.tags"]["evidence"]
    assert st["ms1.prefer"] == "pass" and st["ms1.ci"] == "info"
    assert st["ms1.nested_claude"] == "needs-user" and "--probe-restricted" in out["ms1.nested_claude"]["cmd"]
    assert st["ms1.coverage"] == "skip" and "ofono_log_dir" in out["ms1.coverage"]["ask"]
    assert not list((tmp_path / "home").rglob("_module-skills*"))         # 관리 clone을 만들지 않는다


def test_ms1_no_remote_needs_user_and_rest_skip(tmp_path):
    root, _ = make_site(tmp_path, dbs=False)
    (root / "plugin" / "site-defaults.yaml").write_text("tracker: {kind: jira}\n", encoding="utf-8")
    out = run_ms1(root)
    assert out["ms1.config"]["status"] == "needs-user" and "S33" in out["ms1.config"]["ask"]
    for cid in ("ms1.remote", "ms1.push", "ms1.tree", "ms1.tags", "ms1.prefer", "ms1.coverage"):
        assert out[cid]["status"] == "skip" and "remote 없음" in out[cid]["evidence"], cid
    assert out["ms1.protection"]["status"] == "info" and out["ms1.ci"]["status"] == "info"


def test_ms1_remote_missing_branch_and_auth_fail(tmp_path):
    root, remote = make_site(tmp_path, {"module_skills": {"remote": "x", "base_branch": "release"}}, dbs=False)
    (root / "plugin" / "site-defaults.yaml").write_text(
        yaml.safe_dump({"module_skills": {"remote": remote, "base_branch": "release"}}), encoding="utf-8")
    out = run_ms1(root)
    assert out["ms1.remote"]["status"] == "fail" and "원격 브랜치 없음" in out["ms1.remote"]["evidence"]
    assert out["ms1.tree"]["status"] == "fail" and "임시 clone 실패" in out["ms1.tree"]["evidence"]
    assert out["ms1.repo_check"]["status"] == "skip"
    gone = remote.replace("remote.git", "missing.git")
    (root / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump({"module_skills": {"remote": gone}}), encoding="utf-8")
    r = by_id(sc.run_checks("MS-1", root))["ms1.remote"]
    assert r["status"] == "fail" and r["evidence"].split(":")[0] in ("인증", "네트워크")


def test_ms1_tree_mismatch_fails(tmp_path):
    root, _ = make_site(tmp_path, dbs=False)
    mr.push(tmp_path / "mod", files={"ofono/sim/SKILL.md": None, "ofono/extra/SKILL.md": "# x\n"})
    out = run_ms1(root)
    ev = out["ms1.tree"]["evidence"]
    assert out["ms1.tree"]["status"] == "fail"
    assert "없음 ofono/sim/SKILL.md" in ev and "modules.yaml에 없는 모듈 폴더 ofono/extra" in ev


def test_ms1_tree_partial_repo_is_info(tmp_path):
    """일부만 있는 레포(템플릿 사본에서 ofono/data·ofono/_common만 남김): 목록만 있는 모듈은 정보, 실패 아님(§6 `tree`(2×7은 정보))."""
    root, _ = make_site(tmp_path, dbs=False)
    part = tmp_path / "partial"
    shutil.copytree(mr.TEMPLATES, part)
    for plat in ("ofono", "android"):
        for d in (part / plat).iterdir():
            if d.is_dir() and not (plat == "ofono" and d.name in ("_common", "data")):
                shutil.rmtree(d)
    remote = mr.build(tmp_path / "tpl", src=part)
    (root / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump({"module_skills": {"remote": remote}}), encoding="utf-8")
    out = run_ms1(root)
    ev = out["ms1.tree"]["evidence"]
    assert out["ms1.tree"]["status"] == "pass", ev
    assert out["ms1.repo_check"]["status"] == "pass", out["ms1.repo_check"]["evidence"]
    assert "modules.yaml에만 있고 폴더 없음" in ev and "android/data" in ev and "계획 2×7 중 1개" in ev
    # 폴더가 생긴 모듈은 파일이 다 있어야 하고, 그 플랫폼 _common도 있어야 한다
    mr.push(tmp_path / "tpl", files={"android/data/explore.md": "# x\n"})
    ev = run_ms1(root)["ms1.tree"]["evidence"]
    assert "없음 android/data/SKILL.md" in ev and "없음 android/_common/" in ev


def test_ms1_repo_check_finding_fails(tmp_path):
    root, _ = make_site(tmp_path, dbs=False)
    mr.push(tmp_path / "mod", files={"CLAUDE.md": "x\n"}, modes={"ofono/data/explore.md": "100755"})
    r = run_ms1(root)["ms1.repo_check"]
    assert r["status"] == "fail" and "지적" in r["evidence"]


def test_ms1_tags_missing_daemon_fails_names_capped(tmp_path):
    root, _ = make_site(tmp_path)
    doc = yaml.safe_load((mr.MOCK / "modules.yaml").read_text(encoding="utf-8"))
    names = [f"GHOST{i}" for i in range(14)]
    doc["platforms"]["ofono"]["modules"]["data"]["daemons"] += names
    mr.push(tmp_path / "mod", files={"modules.yaml": yaml.safe_dump(doc, sort_keys=False)})
    r = run_ms1(root)["ms1.tags"]
    assert r["status"] == "fail" and "tags.yaml에 없음 ofono:GHOST0" in r["evidence"] and " 외 4" in r["evidence"]
    assert "계획 op PR" in r["ask"] and "GHOST13" not in r["evidence"]


def test_ms1_tags_without_db_skips(tmp_path):
    root, _ = make_site(tmp_path, dbs=False)
    r = run_ms1(root)["ms1.tags"]
    assert r["status"] == "skip" and "propose --set ops_db" in r["ask"]


def test_ms1_prefer_rule(tmp_path):
    # android data: 레포에 모듈 있음 → info. android network: 레포에 없음 → fail + 고치기 명령
    root, _ = make_site(tmp_path, {"analyzers": {"data": {"skill": "acme-data"}, "network": {"skill": "acme-net"}}}, dbs=False)
    r = run_ms1(root)["ms1.prefer"]
    assert r["status"] == "fail"
    assert r["cmd"] == "python3 plugin/scripts/config.py set analyzers.network.prefer skill"
    assert "analyzers.data: 모듈 문서(android/data)로 바뀜" in r["evidence"] and "site-defaults `analyzers.<카테고리>.prefer: skill`" in r["ask"]
    # 플랫폼 블록: --platform
    root2, _ = make_site(tmp_path / "b", {"platforms": {"ofono": {"analyzers": {"network": {"skill": "acme-net"}}}}}, dbs=False)
    r2 = run_ms1(root2)["ms1.prefer"]
    assert r2["status"] == "fail" and r2["cmd"] == "python3 plugin/scripts/config.py set analyzers.network.prefer skill --platform ofono"
    # 모듈이 있으면 정보, prefer를 적으면 통과
    root3, _ = make_site(tmp_path / "c", {"analyzers": {"data": {"skill": "acme-data"}}}, dbs=False)
    assert run_ms1(root3)["ms1.prefer"]["status"] == "info"
    root4, _ = make_site(tmp_path / "d", {"analyzers": {"network": {"skill": "acme-net", "prefer": "skill"}}}, dbs=False)
    assert run_ms1(root4)["ms1.prefer"]["status"] == "pass"


def test_ms1_push_false_fails_unauth_skips(tmp_path, monkeypatch):
    root, _ = make_site(tmp_path, dbs=False)
    st = sc.module_settings(sc.Ctx(root))
    st["ms"] = {"remote": "https://ghe.mock.invalid/org/module-skills.git", "base_branch": "main"}
    monkeypatch.setattr(sc, "module_settings", lambda ctx: st)
    calls = []

    def gh(self, *args, host=None, auth=0, perm=None):
        calls.append((args, host))
        if args[:2] == ("auth", "status"):
            return auth, "", ""
        return 0, json.dumps({"permissions": {"push": perm}}), ""

    for perm, want in ((False, "fail"), (True, "pass")):
        monkeypatch.setattr(sc.Ctx, "gh", lambda self, *a, host=None, p=perm: gh(self, *a, host=host, perm=p))
        r = sc.ms1_push(sc.Ctx(root))
        assert r["status"] == want and "gh api repos/org/module-skills --jq .permissions.push" in r["cmd"]
    assert calls[-1] == (("api", "repos/org/module-skills"), "ghe.mock.invalid")
    monkeypatch.setattr(sc.Ctx, "gh", lambda self, *a, host=None: gh(self, *a, host=host, auth=1))
    r = sc.ms1_push(sc.Ctx(root))
    assert r["status"] == "skip" and "gh auth login" in r["ask"]


def test_ms1_nested_claude_prints_only(tmp_path, monkeypatch):
    root, _ = make_site(tmp_path, dbs=False)
    monkeypatch.setenv("PATH", stub_path(root))
    marker = root.parent / f"{root.name}-bin" / "claude-called"
    r = run_ms1(root)["ms1.nested_claude"]
    assert r["status"] == "needs-user" and not marker.exists()
    assert "--done MS-1 --waive ms1.nested_claude=" in r["ask"] and "--record" not in r["cmd"]
    r = run_ms1(root, allow_api=True)["ms1.nested_claude"]
    assert r["status"] == "needs-user" and marker.read_text(encoding="utf-8").split() == ["--version"]


def test_ms1_coverage_counts_only_in_evidence(tmp_path):
    logs = tmp_path / "ofono-logs" / "case1"
    logs.mkdir(parents=True)
    body = ["-- [합성] ms1.coverage", *[f"Sep 20 15:10:{i:02d}.000 dut daemon.err PTD[77]: attach failed {i}" for i in range(25)],
            *[f"Sep 20 15:11:{i:02d}.000 dut daemon.err SECRETD[9]: oops {i}" for i in range(22)]]
    (logs / "journal.log").write_text("\n".join(body) + "\n", encoding="utf-8")
    root, _ = make_site(tmp_path, inputs=f"ofono_log_dir: {logs.parent}\n")
    plug = runner.plugin_root("ofono-on", platform={"name": "android", "enabled": ["android", "ofono"]})
    import shutil
    shutil.rmtree(root / "plugin")
    shutil.copytree(plug, root / "plugin")
    d = yaml.safe_load((root / "plugin" / "site-defaults.yaml").read_text(encoding="utf-8"))
    d["module_skills"] = {"remote": "file://" + str((tmp_path / "mod" / "remote.git").resolve())}
    (root / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    r = run_ms1(root)["ms1.coverage"]
    assert r["status"] == "needs-user", r["evidence"]
    assert "SECRETD" not in r["evidence"] and "PTD" not in r["evidence"]      # 이름은 근거에 없다(개수만)
    assert "tags.yaml에 없음 " in r["evidence"]


def _progress(root: Path) -> list[str]:
    text = (root / "SITE_PROFILE.md").read_text(encoding="utf-8")
    return [ln for ln in text.split("## 진행 상태", 1)[1].split("\n## ", 1)[0].splitlines() if ln.startswith("- ")]


def test_modules_track_start_done_flow(tmp_path, monkeypatch, capsys):
    root, _ = make_site(tmp_path, dbs=False)
    assert ss.main(["--root", str(root), "modules"]) == 2
    assert "S-3 완료 기록 뒤" in capsys.readouterr().err
    prof = root / "SITE_PROFILE.md"
    prof.write_text(prof.read_text(encoding="utf-8").replace("- 완료 단계: (없음)", S3_DONE).replace(
        "- 현재 단계: S-1", "- 현재 단계: S-4a"), encoding="utf-8")
    before = _progress(root)
    monkeypatch.setitem(sc.MODULE_CHECKS, "MS-1", [lambda ctx: sc.res("ms1.ok", "pass", "합성")])
    monkeypatch.setitem(sc.MODULE_CHECKS, "MS-2", [lambda ctx: sc.res("ms2.ok", "pass", "합성")])
    assert ss.main(["--root", str(root), "modules"]) == 0
    out = capsys.readouterr().out
    assert "모듈 스킬 트랙을 시작했다" in out and "지금 단계: MS-1" in out and "내장 안내" in out
    after = _progress(root)
    assert after[:len(before)] == before and after[len(before):] == ["- 모듈 단계: MS-1", "- 모듈 완료: (없음)"]
    assert ss.main(["--root", str(root), "modules"]) == 0                     # 다시 넣지 않는다
    capsys.readouterr()
    assert _progress(root) == after
    assert ss.main(["--root", str(root), "--done", "MS-2"]) == 2               # 건너뛰지 않는다
    assert ss.main(["--root", str(root), "--done", "MS-1"]) == 0
    out = capsys.readouterr().out
    assert "MS-1 완료를 기록했다" in out and "지금 단계: MS-2" in out
    prog = _progress(root)
    assert "- 모듈 단계: MS-2" in prog and any(p.startswith("- 모듈 완료: MS-1 (") for p in prog)
    assert [p for p in prog if not p.startswith("- 모듈")] == before            # Android 줄은 그대로
    assert ss.main(["--root", str(root), "--done", "MS-2"]) == 0
    assert "- 모듈 단계: 완료" in _progress(root)
    assert ss.main(["--root", str(root), "modules", "nope"]) == 2
    assert ss.main(["--root", str(root), "check", "MS-9"]) == 2
    out = capsys.readouterr()
    r = ss.main(["--root", str(root)])                                        # Android 단계 출력 끝에 한 줄
    assert "모듈 스킬 트랙: 완료" in capsys.readouterr().out and r in (0, 1)


def test_modules_refused_on_offsite_pc(tmp_path, capsys):
    (tmp_path / ".local-draft").write_text("", encoding="utf-8")
    assert ss.main(["--root", str(tmp_path), "modules"]) == 2
    assert ss.main(["--root", str(tmp_path), "audit"]) == 2
    assert not (tmp_path / "SITE_PROFILE.md").exists()


def test_modules_check_json_shape(tmp_path, capsys):
    root, _ = make_site(tmp_path, dbs=False)
    prof = root / "SITE_PROFILE.md"
    prof.write_text(prof.read_text(encoding="utf-8").replace("- 완료 단계: (없음)", S3_DONE)
                    + "", encoding="utf-8")
    text = ss._insert_progress(prof.read_text(encoding="utf-8"), "- 모듈 단계: MS-1", ss.MODULE_CURRENT_RE.pattern)
    prof.write_text(ss._insert_progress(text, "- 모듈 완료: (없음)", ss.MODULE_FINISHED_RE.pattern), encoding="utf-8")
    code = ss.main(["--root", str(root), "modules", "check", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 1 and data["step"] == "MS-1" and [r["id"] for r in data["results"]] == MS1_IDS
    assert {r["status"] for r in data["results"]} <= set(sc.STATUSES)
    assert json.loads((root / "docs/site/steps/MS-1.json").read_text(encoding="utf-8"))["exit"] == 1


def test_ms2_audit_states(tmp_path, monkeypatch):
    import site_audit

    root, _ = make_site(tmp_path, dbs=False)
    r = sc.ms2_audit(sc.Ctx(root))
    assert r["status"] == "needs-user" and "audit --record" in r["ask"]
    state = root / site_audit.STATE_FILE
    state.parent.mkdir(parents=True, exist_ok=True)
    for days, want in ((3, "pass"), (14, "pass"), (15, "needs-user")):
        at = (site_audit.today() - site_audit.timedelta(days=days)).isoformat()
        state.write_text(json.dumps({"points": {}, "carry": [], "history": [{"at": at + "T09:00:00"}]}), encoding="utf-8")
        assert sc.ms2_audit(sc.Ctx(root))["status"] == want, days
    m = sc.ms2_module_eval(sc.Ctx(root))
    assert m["status"] == "info" and "사례 0개" in m["evidence"]
