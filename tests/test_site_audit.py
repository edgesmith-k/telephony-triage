"""tools/site_audit.py·`site_step.py audit` (F, 결정 기록 11/05 ③): 사내 모델 출처 커밋 고르기, 토큰 0 검사 먼저, Claude가 볼 것과
추정 토큰(상한 안 = 이번, 넘으면 미룸), 기준점 기록. Claude는 부르지 않는다(PATH의 가짜 claude가 불리면 표식이 남는다).

이슈 DB 스크립트(db_lint·db_regress·db_verify·db_review·mask_pii)와 module_eval --dry-run 출력은 `Ctx.py` 바꿔치기로 준다
(그 스크립트 자체는 각자의 테스트가 본다). git·임시 clone은 진짜다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "helpers"))
import module_remote as mr  # noqa: E402
import runner  # noqa: E402
import site_audit as sa  # noqa: E402
import site_checks as sc  # noqa: E402
import site_step as ss  # noqa: E402
from tests.test_site_checks import git, site_root  # noqa: E402

INHOUSE = "Triage-Env: runtime=claude-code; model=glm-5.2; gateway=other; label=-"
CLAUDE = "Triage-Env: runtime=claude-code; model=claude-sonnet-5-5; gateway=anthropic; label=-"
TYPE = "data/DATA-001-no-setup-data-call"
MOCK_MODULES = ("ofono/data", "ofono/sim", "ofono/modem", "android/data", "android/sim")


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    runner.git(repo, "add", "-A")
    runner.git(repo, "commit", "-qm", message)
    return runner.git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def site(tmp_path, monkeypatch):
    """사내 루트 + 운영 DB clone(커밋: init → 사내 → Claude → 출처 모름) + 모듈 레포. 가짜 claude·gh는 PATH."""
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GH_HOST", "invalid.example")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "claude").write_text(f"#!/bin/sh\necho \"$@\" >> '{tmp_path / 'claude-called'}'\nexit 9\n", encoding="utf-8")
    (bin_ / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_), str(ROOT / "tests" / "mocks" / "bin"), os.environ["PATH"]]))
    root = site_root(tmp_path)
    remote = mr.build(tmp_path / "mod", extra={f"{m}/evals/case-one/case.yaml": "key: MOCK-1\n" for m in MOCK_MODULES})
    for plat in ("ofono", "android"):                                  # module_eval arm 자료(레포 루트 기준) — 있어야 dry-run을 부른다
        (root / sa.ARM_MATERIAL / plat).mkdir(parents=True)
        (root / sa.ARM_MATERIAL / plat / ".keep").write_text("", encoding="utf-8")
    (root / "plugin").mkdir()
    (root / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump({"module_skills": {"remote": remote}}), encoding="utf-8")
    db = runner.git_db()
    init = runner.git(db, "rev-parse", "HEAD").strip()
    shas = {
        "inhouse": commit(db, {f"{TYPE}/type.md": (db / TYPE / "type.md").read_text(encoding="utf-8") + "\n추가 메모\n"},
                          f"분석 기록 MOCK-1001\n\n{INHOUSE}"),
        "claude": commit(db, {"data/DATA-002-data-teardown-by-user-action/type.md":
                              (db / "data/DATA-002-data-teardown-by-user-action/type.md").read_text(encoding="utf-8") + "\nx\n"},
                         f"분석 기록 MOCK-1002\n\n{CLAUDE}"),
        "unknown": commit(db, {f"{TYPE}/issues/MOCK-1003.yaml": "key: MOCK-1003\n"}, "웹 편집 MOCK-1003"),
    }
    (root / sc.STEPS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / sc.STEPS_FILE).write_text(f"ops_db: {db}\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "site")
    jobs = tmp_path / "jobs"
    (jobs / "MOCK-1003").mkdir(parents=True)
    (jobs / "MOCK-1003" / "check-output.json").write_text(json.dumps({"deep": {"quotes": 3, "fabricated": 0, "weak": 0}}),
                                                          encoding="utf-8")
    return {"root": root, "db": db, "init": init, "shas": shas, "mod": tmp_path / "mod", "mod_head": mr.head(tmp_path / "mod"),
            "jobs": jobs, "marker": tmp_path / "claude-called", "tmp": tmp_path}


DEFAULTS = {
    "db_lint.py": {"errors": [], "warnings": []},
    "db_regress.py": {"results": [{"fixture": f"{TYPE}/fixtures/DATA-001-01.log", "status": "pass"}]},
    "db_verify.py": {"rules": [{"id": "R3", "status": "pass", "targets": []}]},
    "db_review.py": {"items": [{"key": "duplicate-candidates", "entries": []}]},
    "mask_pii.py": {"detections": []},
    "module_eval.py": {"estimate": {"runs": 4}, "plan": [{}] * 4},
}


@pytest.fixture
def fake_py(monkeypatch):
    """`Ctx.py` 바꿔치기: 스크립트 이름 → (종료 코드, JSON). 받은 인자를 기록한다."""
    outputs: dict = {}
    calls: list = []

    def py(self, script, *args, timeout=None):
        name = Path(script).name
        calls.append((name, args))
        code, data = outputs.get(name, (0, DEFAULTS[name]))
        return code, json.dumps(data), ""

    monkeypatch.setattr(sc.Ctx, "py", py)
    return outputs, calls


def plan(site, **kw):
    ctx = sc.Ctx(site["root"])
    try:
        kw.setdefault("jobs", str(site["jobs"]))
        return sa.plan(ctx, **kw)
    finally:
        ctx.cleanup()


def test_parse_env_trailer_and_classify():
    body = f"제목\n\nTriage-Env: runtime=x; model=old\n{INHOUSE}\n"
    env = sa.parse_env_trailer(body)
    assert env == {"runtime": "claude-code", "model": "glm-5.2", "gateway": "other", "label": "-"}   # 마지막 줄
    assert sa.parse_env_trailer("제목만") is None
    assert sa.classify(env) == "inhouse"
    assert sa.classify(sa.parse_env_trailer(CLAUDE)) == "claude"
    assert sa.classify({"runtime": "opencode", "model": "모름", "gateway": "none"}) == "inhouse"
    assert sa.classify({"runtime": "claude-code", "model": "모름", "gateway": "none"}) == "unknown"
    assert sa.classify(None) == "unknown"
    assert sa.classify({"model": "acme-7b", "gateway": "none"}, inhouse=[r"^acme-"]) == "inhouse"
    # trailer 모양은 db_summary.env_trailer와 같다
    sys.path.insert(0, str(ROOT / "plugin" / "scripts"))
    import db_summary
    line = db_summary.env_trailer({"TT_RUNTIME": "opencode", "TT_MODEL": "glm-5"}, {})
    assert sa.classify(sa.parse_env_trailer("x\n\n" + line)) == "inhouse"


def test_selects_inhouse_unknown_skips_claude(site, fake_py):
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"])
    w = p["window"]["ops_db"]
    assert w["provenance"] == {"inhouse": 1, "unknown": 1, "claude": 1} and w["commits"] == 3
    assert w["from"] == site["init"] and w["base"] == site["init"]
    lint = next(a for n, a in fake_py[1] if n == "db_lint.py")
    assert lint[lint.index("--changed") + 1] == site["init"]
    mask = next(a for n, a in fake_py[1] if n == "mask_pii.py")
    assert any(a.endswith("MOCK-1003.yaml") for a in mask) and not any("DATA-002" in a for a in mask)   # Claude 커밋 파일 뺌
    checks = {c["id"]: c for c in p["checks"]}
    assert checks["audit.ops_db.grounding"]["status"] == "pass" and "ok 1" in checks["audit.ops_db.grounding"]["evidence"]
    assert p["items"] == [] and p["fix"] == [] and p["exit"] == 0
    assert not site["marker"].exists()


def test_first_window_and_last_requires_state(site, fake_py, capsys):
    p = plan(site, repos=["ops_db"])
    w = p["window"]["ops_db"]
    assert w["label"].startswith("첫 점검") and w["since"] and w["commits"] == 4      # init(출처 모름)도 든다
    with pytest.raises(sa.AuditUsage):
        plan(site, last=True)
    assert ss.main(["--root", str(site["root"]), "audit", "--last"]) == 2
    assert "기록된 점검이 없다" in capsys.readouterr().err
    assert ss.main(["--root", str(site["root"]), "audit", "--since", "2026-13-01"]) == 2
    assert ss.main(["--root", str(site["root"]), "audit", "--since", "nope=abc1234"]) == 2


def test_rewritten_point_falls_back_flagged(site, fake_py):
    state = site["root"] / sa.STATE_FILE
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"points": {"ops_db": {"sha": "0" * 40, "at": "2026-10-01T00:00:00"}}, "carry": [],
                                 "history": [{"at": "2026-10-01T00:00:00"}]}), encoding="utf-8")
    w = plan(site, repos=["ops_db"])["window"]["ops_db"]
    assert w["label"].startswith("기준점 없음") and w["from"] is None and w["commits"] == 4
    state.write_text(json.dumps({"points": {"ops_db": {"sha": site["shas"]["claude"], "at": "2026-11-01T00:00:00"}},
                                 "carry": [], "history": [{"at": "2026-11-01T00:00:00"}]}), encoding="utf-8")
    w = plan(site, repos=["ops_db"], last=True)["window"]["ops_db"]
    assert w["from"] == site["shas"]["claude"] and w["commits"] == 1 and w["label"].startswith("지난 점검 2026-11-01")


def test_flags_map_to_commits_and_priority(site, fake_py):
    outputs, _ = fake_py
    outputs["mask_pii.py"] = (1, {"detections": [{"path": f"{TYPE}/type.md", "line": 3, "kind": "MSISDN"}]})
    outputs["db_lint.py"] = (0, {"errors": [], "warnings": [{"code": "w1", "files": ["sim/SIM-001-x/type.md"]}]})
    outputs["db_verify.py"] = (1, {"rules": [{"id": "R3", "status": "fail", "targets": ["DATA-001"]},
                                             {"id": "R4", "status": "fail", "targets": ["DATA-002-C01"]}]})
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"])
    items = {i["id"]: i for i in p["items"]}
    mask_id = f"rec:ops_db:{site['shas']['inhouse'][:12]}"      # type.md를 건드린 커밋(파일이 먼저)
    sig_id = f"rec:ops_db:{site['shas']['unknown'][:12]}"       # 유형 DATA-001 폴더를 건드린 가장 새 고른 커밋
    assert list(items) == [mask_id, sig_id]                     # P0이 먼저
    assert items[mask_id]["priority"] == "P0" and items[mask_id]["flags"] == ["마스킹 안 됨 MSISDN"]
    assert items[sig_id]["priority"] == "P1" and items[sig_id]["flags"] == ["시그니처 겹침 R3"]
    it = items[mask_id]
    assert it["cmds"][0] == f"git -C {site['db']} show {site['shas']['inhouse'][:12]} -- {TYPE}/type.md"
    assert it["est_tokens"] >= sa.RECORD_PER and it["slot"] == "이번" and it["provenance"] == "inhouse"
    assert any("lint 경고 w1" in f and "고른 커밋 밖" in f for f in p["fix"])        # 고른 커밋이 안 건드린 파일
    assert any("시그니처 겹침 R4" in f for f in p["fix"])                             # Claude 커밋의 유형 → 고른 것 밖
    checks = {c["id"]: c["status"] for c in p["checks"]}
    assert checks["audit.ops_db.mask"] == "fail" and checks["audit.ops_db.verify"] == "fail" and p["exit"] == 1


def test_grounding_from_jobs_dir(site, fake_py):
    jobs = site["jobs"]
    (jobs / "MOCK-1003" / "check-output.json").write_text(json.dumps({"deep": {"fabricated": 1, "weak": 0}}), encoding="utf-8")
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"])
    g = next(c for c in p["checks"] if c["id"] == "audit.ops_db.grounding")
    assert g["status"] == "fail" and "fabricated 1" in g["evidence"]
    assert p["items"][0]["priority"] == "P0" and "근거 fabricated MOCK-1003" in p["items"][0]["flags"]
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"], jobs=str(site["tmp"] / "empty"))
    g = next(c for c in p["checks"] if c["id"] == "audit.ops_db.grounding")
    assert g["status"] == "skip" and "근거 기록 없음 1" in g["evidence"]                  # 기록 없음은 통과가 아니다


def test_module_items_from_mock_remote(site, fake_py):
    _, calls = fake_py
    base = site["mod_head"]
    mr.push(site["mod"], files={"ofono/data/explore.md": "# 바뀜\n"}, message="explore 고침")
    p = plan(site, since=[f"modules={base}"], repos=["modules"])
    items = [i for i in p["items"] if i["kind"] == "module"]
    assert [i["id"] for i in items] == ["mod:ofono/data"]
    it = items[0]
    assert it["est_tokens"] == 4 * sa.MODULE_RUN_TOKENS and it["priority"] == "M"
    assert "--module ofono/data --templates <모듈 레포 clone> --sha" in it["cmds"][1]
    assert str(site["tmp"]) not in it["cmds"][0]                                       # 주소는 redact
    dry = [a for n, a in calls if n == "module_eval.py"]
    assert dry and all("--dry-run" in a and "--claude" in a for a in dry)
    assert {c["id"]: c["status"] for c in p["checks"]}["audit.modules.repo_check"] == "pass"
    mr.push(site["mod"], files={"ofono/_common/layers.md": "# 바뀜\n"}, message="공통")
    p = plan(site, since=[f"modules={base}"], repos=["modules"])
    assert sorted(i["id"] for i in p["items"]) == ["mod:ofono/data", "mod:ofono/modem", "mod:ofono/sim"]
    assert not site["marker"].exists()


def test_module_repo_check_failure_goes_to_fix(site, fake_py):
    base = site["mod_head"]
    mr.push(site["mod"], files={"ofono/sim/CLAUDE.md": "x\n"}, message="나쁜 파일")
    p = plan(site, since=[f"modules={base}"], repos=["modules"])
    assert {c["id"]: c["status"] for c in p["checks"]}["audit.modules.repo_check"] == "fail"
    assert any(f.startswith("모듈 레포: ofono/sim/CLAUDE.md") for f in p["fix"])
    assert "mod:ofono/sim" not in {i["id"] for i in p["items"]}                     # 스크립트 판정 → Claude 대상 아님


def test_cap_packs_and_defers_deterministically(site, fake_py):
    base = site["mod_head"]
    mr.push(site["mod"], files={"ofono/data/explore.md": "# a\n", "ofono/data/SKILL.md": "# a\n",
                                "ofono/sim/explore.md": "# b\n", "android/data/explore.md": "# c\n"}, message="여럿")
    first = plan(site, since=[f"modules={base}"], repos=["modules"], cap=300_000)
    slots = [(i["id"], i["slot"]) for i in first["items"]]
    assert slots == [("mod:ofono/data", "이번"), ("mod:android/data", "이번"), ("mod:ofono/sim", "미룸")]
    assert first["est_now"] == 2 * 4 * sa.MODULE_RUN_TOKENS and first["est_deferred"] == 4 * sa.MODULE_RUN_TOKENS
    again = plan(site, since=[f"modules={base}"], repos=["modules"], cap=300_000)
    assert [(i["id"], i["slot"]) for i in again["items"]] == slots
    tiny = plan(site, since=[f"modules={base}"], repos=["modules"], cap=100_000)
    assert all(i["slot"] == "미룸" and i["why"] == "상한보다 큼" for i in tiny["items"])
    assert "이번 0 / 상한 100,000" in sa.render(tiny)


def test_record_writes_plan_points_and_carry(site, fake_py, capsys):
    base = site["mod_head"]
    mr.push(site["mod"], files={"ofono/data/explore.md": "# a\n", "ofono/sim/explore.md": "# b\n"}, message="둘")
    r = ss.main(["--root", str(site["root"]), "audit", "--since", f"modules={base}", "--since", f"ops_db={site['init']}",
                 "--cap-tokens", "150000", "--jobs", str(site["jobs"])])
    out = capsys.readouterr().out
    assert r == 1 and "미룸 1" in out and "audit --record" in out
    plan_data = json.loads((site["root"] / sa.PLAN_FILE).read_text(encoding="utf-8"))
    later = [i["id"] for i in plan_data["items"] if i["slot"] == "미룸"]
    now = [i["id"] for i in plan_data["items"] if i["slot"] == "이번"]
    newer = mr.push(site["mod"], files={"ofono/modem/explore.md": "# 뒤에 들어온 커밋\n"}, message="뒤")
    assert ss.main(["--root", str(site["root"]), "audit", "--record", "--defer", now[0]]) == 0
    capsys.readouterr()
    state = json.loads((site["root"] / sa.STATE_FILE).read_text(encoding="utf-8"))
    assert state["points"]["modules"]["sha"] == plan_data["window"]["modules"]["to"] != newer     # 계획의 끝, 지금 HEAD 아님
    assert state["points"]["ops_db"]["sha"] == plan_data["window"]["ops_db"]["to"]
    assert state["carry"] == later + [now[0]] and len(state["history"]) == 1
    nxt = plan(site, repos=["modules"])                                  # 이월이 먼저, 뒤에 들어온 커밋은 든다
    ids = [i["id"] for i in nxt["items"]]
    assert set(later + [now[0]]) <= set(ids) and "mod:ofono/modem" in ids
    assert all("이월" in i["flags"] for i in nxt["items"][:len(later) + 1])


def test_record_refuses_stale_plan(site, fake_py, capsys):
    root = str(site["root"])
    assert ss.main(["--root", root, "audit", "--record"]) == 2                          # 계획 없음
    ss.main(["--root", root, "audit", "--since", f"ops_db={site['init']}", "--jobs", str(site["jobs"]), "--repo", "ops_db"])
    assert ss.main(["--root", root, "audit", "--record", "--defer", "rec:nope"]) == 2  # 계획에 없는 항목
    assert ss.main(["--root", root, "audit", "--record"]) == 0
    assert ss.main(["--root", root, "audit", "--record"]) == 2                          # 이미 기록함
    err = capsys.readouterr().err
    assert "이미 기록했다" in err
    for bad in (["audit", "--defer", "x"], ["check", "--since", "2026-01-01"], ["audit", "--record", "--repo", "ops_db"],
                ["audit", "S-1"]):
        with pytest.raises(SystemExit) as exc:                                           # 사용 오류(argparse)
            ss.main(["--root", root, *bad])
        assert exc.value.code == 2


def test_writes_only_under_docs_site_audit(site, fake_py):
    root = site["root"]
    db_before = runner.git(site["db"], "status", "--porcelain")
    head = runner.git(site["db"], "rev-parse", "HEAD")
    assert ss.main(["--root", str(root), "audit", "--since", f"ops_db={site['init']}", "--jobs", str(site["jobs"])]) in (0, 1)
    assert ss.main(["--root", str(root), "audit", "--record"]) == 0
    changed = sorted(ln[3:] for ln in git(root, "status", "--porcelain", "--untracked-files=all").splitlines())
    assert changed and all(c.startswith("docs/site/audit/") for c in changed), changed
    assert {Path(c).name for c in changed} >= {"plan.json", "state.json"} and any(c.endswith("-review.md") for c in changed)
    assert runner.git(site["db"], "status", "--porcelain") == db_before and runner.git(site["db"], "rev-parse", "HEAD") == head
    assert not site["marker"].exists()


def test_json_shape_and_exit(site, fake_py, capsys):
    code = ss.main(["--root", str(site["root"]), "audit", "--since", f"ops_db={site['init']}", "--jobs", str(site["jobs"]),
                    "--json", "--inhouse-model", "^glm-"])
    data = json.loads(capsys.readouterr().out)
    assert set(data) >= {"window", "checks", "fix", "items", "cap", "est_now", "est_deferred", "every_days", "last_audit",
                         "next_due", "exit"}
    assert data["cap"] == sa.AUDIT_CAP_TOKENS == 300_000 and data["every_days"] == 7 and data["overdue_days"] == 14
    assert code == data["exit"]
    review = sorted((site["root"] / sa.AUDIT_DIR).glob("*-review.md"))
    assert review and "파일 쓰기·push·Jira 쓰기는 하지 않는다" in review[0].read_text(encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        ss.main(["--root", str(site["root"]), "audit", "--cap-tokens", "0"])
    assert exc.value.code == 2


def _carry_state(site, carry):
    path = site["root"] / sa.STATE_FILE
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"points": {}, "history": []}
    state["carry"] = carry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def _drop_arm(site, plat):
    (site["root"] / sa.ARM_MATERIAL / plat / ".keep").unlink()
    (site["root"] / sa.ARM_MATERIAL / plat).rmdir()


def test_record_keeps_carry_of_repos_not_processed(site, fake_py, capsys):
    """--repo·clone 건너뜀으로 이번에 안 본 레포의 이월은 남는다(기준점은 이미 지나갔다 — 잃으면 리뷰가 사라진다)."""
    root = str(site["root"])
    base = site["mod_head"]
    mr.push(site["mod"], files={"ofono/data/explore.md": "# a\n", "ofono/sim/explore.md": "# b\n"}, message="둘")
    ss.main(["--root", root, "audit", "--since", f"modules={base}", "--repo", "modules", "--cap-tokens", "150000"])
    assert ss.main(["--root", root, "audit", "--record"]) == 0
    carried = json.loads((site["root"] / sa.STATE_FILE).read_text(encoding="utf-8"))["carry"]
    assert carried == ["mod:ofono/sim"]
    # --repo ops_db: 모듈 레포를 안 봤다 → 모듈 이월 유지. ofono_db는 steps.yaml에 없어 clone 건너뜀 → 그 이월도 유지
    _carry_state(site, carried + ["rec:ofono_db:0123456789ab"])
    ss.main(["--root", root, "audit", "--since", f"ops_db={site['init']}", "--repo", "ops_db", "--repo", "ofono_db",
             "--jobs", str(site["jobs"])])
    p = json.loads((site["root"] / sa.PLAN_FILE).read_text(encoding="utf-8"))
    assert "ofono_db" in p["skipped"] and "modules" not in p["window"]
    assert ss.main(["--root", root, "audit", "--record"]) == 0
    state = json.loads((site["root"] / sa.STATE_FILE).read_text(encoding="utf-8"))
    assert state["carry"][:2] == ["mod:ofono/sim", "rec:ofono_db:0123456789ab"]
    nxt = plan(site, repos=["modules"])
    assert "mod:ofono/sim" in {i["id"] for i in nxt["items"]}
    capsys.readouterr()


def test_record_keeps_carry_when_window_over_max(site, fake_py, monkeypatch):
    monkeypatch.setattr(sa, "MAX_COMMITS", 1)
    _carry_state(site, ["rec:ops_db:0123456789ab"])
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"])
    assert p["window"]["ops_db"]["provenance"] == {}                                   # 커밋 수 초과 — 기준점도 이월도 그대로
    sa.write_plan(site["root"], p)
    sa.record(site["root"])
    state = json.loads((site["root"] / sa.STATE_FILE).read_text(encoding="utf-8"))
    assert state["carry"] == ["rec:ops_db:0123456789ab"] and "ops_db" not in state["points"]


def test_module_without_case_or_arm_material_is_doc_review(site, fake_py):
    """eval case 없음·그 플랫폼 arm 자료 없음은 dry-run 실패가 아니다 — 문서 리뷰 항목(run 0)으로 남아 이월도 된다."""
    _, calls = fake_py
    base = site["mod_head"]
    mr.push(site["mod"], files={"ofono/data/evals/case-one/case.yaml": None, "ofono/data/explore.md": "# a\n",
                                "android/data/explore.md": "# b\n", "ofono/sim/explore.md": "# c\n"}, message="셋")
    _drop_arm(site, "android")
    p = plan(site, since=[f"modules={base}"], repos=["modules"])
    by = {i["id"]: i for i in p["items"]}
    assert set(by) == {"mod:ofono/data", "mod:android/data", "mod:ofono/sim"}
    assert "eval case 없음 — 문서 리뷰만" in by["mod:ofono/data"]["flags"] and by["mod:ofono/data"]["doc_only"]
    assert "arm 자료 없음 — 문서 리뷰만" in by["mod:android/data"]["flags"]
    assert by["mod:android/data"]["est_tokens"] == sa.MODULE_DOC_TOKENS and "module_eval" not in by["mod:android/data"]["cmds"][1]
    assert not by["mod:ofono/sim"]["doc_only"] and by["mod:ofono/sim"]["est_tokens"] == 4 * sa.MODULE_RUN_TOKENS
    dry = {c["id"]: c for c in p["checks"]}["audit.modules.dry_run"]
    assert dry["status"] == "pass" and "문서 리뷰만 2" in dry["evidence"] and not p["fix"]
    assert [a[1] for n, a in calls if n == "module_eval.py"] == ["ofono/sim"]          # 못 돌리는 모듈은 부르지 않는다
    assert "diff로만 본다" in sa.review_md(p)


def test_module_dry_run_real_script_on_templates(site, monkeypatch, tmp_path):
    """진짜 module_eval --dry-run(없는 claude 경로): 템플릿 ofono/data는 통과, arm 자료 없는 android 모듈은 문서 리뷰."""
    monkeypatch.setattr(sc.Ctx, "py", lambda self, script, *a, timeout=None:
                        self.run([sys.executable, str(ROOT / script), *a], timeout=timeout))
    remote = mr.build(tmp_path / "tpl", src=mr.TEMPLATES)
    (site["root"] / "plugin" / "site-defaults.yaml").write_text(yaml.safe_dump({"module_skills": {"remote": remote}}),
                                                               encoding="utf-8")
    _drop_arm(site, "android")
    base = mr.head(tmp_path / "tpl")
    src = mr.TEMPLATES / "ofono" / "data"
    copy = {f"android/data/{f.relative_to(src).as_posix()}": f.read_bytes() for f in src.rglob("*") if f.is_file()}
    mr.push(tmp_path / "tpl", files={"ofono/data/explore.md": (src / "explore.md").read_text(encoding="utf-8") + "\n메모\n",
                                     **copy}, message="data 고침·android 복사")
    p = plan(site, since=[f"modules={base}"], repos=["modules"])
    dry = {c["id"]: c for c in p["checks"]}["audit.modules.dry_run"]
    assert dry["status"] == "pass", (dry, p["fix"])
    by = {i["id"]: i for i in p["items"]}
    assert not by["mod:ofono/data"]["doc_only"] and by["mod:ofono/data"]["est_tokens"] > 0
    assert by["mod:android/data"]["doc_only"] and "arm 자료 없음 — 문서 리뷰만" in by["mod:android/data"]["flags"]
    assert not site["marker"].exists()


# -- 시그니처 소실(drift): feedback suggested × issues sw·platform_version (설계 C §3) ------------------------------------

DD = "data/DATA-001-no-setup-data-call"
SIG = "DATA-001-01/data-disabled"


def _rec(db: Path, key: str, cause: str, sw: str, pv: str | None, sigs: list[str], decision: str = "accepted",
         stamp: str = "20261015T1000") -> None:
    """기록 하나: `<유형>/issues/<KEY>.yaml` + `feedback/<YYYY-MM>/<KEY>-<시각>.yaml`(마스킹된 값만, 로그 원문 없음)."""
    issue = {"key": key, "cause": cause, "date": "2026-10-15", "occurred_on": "2026-10-14", "model": "MOCK-A56", "sw": sw,
             "carrier": "MockTel KR", "analyzed_by": "mock-user1"}
    if pv is not None:
        issue["platform_version"] = pv
    (db / DD / "issues").mkdir(parents=True, exist_ok=True)
    (db / DD / "issues" / f"{key}.yaml").write_text(yaml.safe_dump(issue, allow_unicode=True), encoding="utf-8")
    month = f"{stamp[:4]}-{stamp[4:6]}"
    fb = {"issue": key, "date": f"{month}-{stamp[6:8]}T{stamp[9:11]}:{stamp[11:13]}+09:00", "by": "mock-user1",
          "suggested": [{"cause": s.split("/")[0], "signature": s, "score": 0.5} for s in sigs], "decision": decision,
          "final": cause}
    (db / "feedback" / month).mkdir(parents=True, exist_ok=True)
    (db / "feedback" / month / f"{key}-{stamp}.yaml").write_text(yaml.safe_dump(fb), encoding="utf-8")


def _old_hits(db: Path) -> Path:
    """MOCK-1101·1102(U1_0901)도 SIG 제안 → SIG hits 4(1101·1102·1103·1104, 마지막 U1_20260920)."""
    for k in ("MOCK-1101", "MOCK-1102"):
        _rec(db, k, "DATA-001-01", "MOCKA56_U1_20260901", "16", [SIG], stamp="20260905T1000")
    return db


def _drift_db() -> Path:
    return _old_hits(runner.copy_db(name="drift-db"))


def _drift(db: Path) -> list[dict]:
    return sa.drift_checks("ops_db", db)


def _rows(out, status=None):
    return [o["row"] for o in out if o["row"] and (status is None or o["row"]["status"] == status)]


def test_drift_sample_db_passes():
    out = _drift(runner.copy_db(name="sample"))
    assert [r["status"] for r in _rows(out)] == ["pass"] and not any(o["sig"] for o in out)
    assert "자주(≥3) 시그니처 0" in _rows(out)[0]["evidence"]


def test_drift_needs_user_same_branch_newer_sw():
    db = _drift_db()
    _rec(db, "MOCK-1201", "DATA-001-01", "MOCKA56_U1_20261010", "16", [], decision="unresolved")
    _rec(db, "MOCK-1202", "unresolved", "MOCKA56_U1_20261012", "16", ["DATA-001-02/roaming-disabled"], decision="unresolved")
    _rec(db, "MOCK-1203", "DATA-001-01", "MOCKA56_U1_20260910", "16", [], decision="new-cause")   # 더 옛 빌드 → 셈 밖
    out = _drift(db)
    bad = _rows(out, "needs-user")
    assert [o["sig"] for o in out if o["sig"]] == [SIG] and len(bad) == 1
    ev = bad[0]["evidence"]
    assert ev.startswith(f"{SIG}: 이전 hits 4 (마지막 MOCKA56_U1_20260920) → 새 빌드 기록 2건 0회 (예: MOCK-1201, MOCK-1202)")
    assert "update-signature" in bad[0]["cmd"] and not _rows(out, "pass")


def test_drift_other_cause_only_is_info_not_needs_user():
    """원인 둘인 유형: 새 빌드에 다른 원인(DATA-001-02) 기록만 있으면 needs-user가 아니라 info 개수뿐."""
    db = _drift_db()
    for k, sw in (("MOCK-1211", "MOCKA56_U1_20261010"), ("MOCK-1212", "MOCKA56_U1_20261011")):
        _rec(db, k, "DATA-001-02", sw, "16", ["DATA-001-02/roaming-disabled"])
    out = _drift(db)
    assert not _rows(out, "needs-user") and not any(o["sig"] for o in out)
    info = _rows(out, "info")
    assert len(info) == 1 and "새 빌드 기록 0건" in info[0]["evidence"]
    assert "다른 원인 새 빌드 기록 2건(셈에서 뺌)" in info[0]["evidence"]
    assert _rows(out)[0]["status"] == "pass"


def test_drift_one_after_is_info_sample_short():
    db = _drift_db()
    _rec(db, "MOCK-1221", "DATA-001-01", "MOCKA56_U1_20261010", "16", [])
    info = _rows(_drift(db), "info")
    assert len(info) == 1 and info[0]["evidence"].endswith("— 표본 부족")


def test_drift_cross_branch_same_platform_is_not_newer():
    """다른 브랜치(MOCKB77_U2)는 sw 비교 불가 → platform_version이 같으면(16) 새 빌드 아님."""
    db = _drift_db()
    for k in ("MOCK-1231", "MOCK-1232"):
        _rec(db, k, "DATA-001-01", "MOCKB77_U2_20261231", "16", [])
    assert [r["status"] for r in _rows(_drift(db))] == ["pass"]


def test_drift_cross_branch_newer_platform_is_newer():
    """16 → 17 새 플랫폼(다른 브랜치·sw를 못 푸는 기록도 platform_version으로)."""
    db = _drift_db()
    _rec(db, "MOCK-1241", "DATA-001-01", "MOCKB77_U2_20260101", "17", [])     # 브랜치 다름: sw 날짜가 옛것이어도 17 > 16
    _rec(db, "MOCK-1242", "unresolved", "UNPARSABLE_BUILD", "17", [], decision="unresolved")
    bad = _rows(_drift(db), "needs-user")
    assert len(bad) == 1 and "새 빌드 기록 2건 0회 (예: MOCK-1241, MOCK-1242)" in bad[0]["evidence"]


def test_drift_same_branch_uses_sw_only_never_platform():
    """같은 브랜치에서 sw가 옛것이면 platform_version이 커도 새 빌드 아님(두 순서를 섞지 않는다)."""
    db = _drift_db()
    for k in ("MOCK-1251", "MOCK-1252"):
        _rec(db, k, "DATA-001-01", "MOCKA56_U1_20260801", "17", [])
    assert [r["status"] for r in _rows(_drift(db))] == ["pass"]


def test_drift_unparsable_builds_skip_not_pass():
    db = _drift_db()
    for f in (db / DD / "issues").glob("*.yaml"):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        data["sw"] = "UNKNOWN"
        data.pop("platform_version", None)
        f.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    out = _drift(db)
    assert [r["status"] for r in _rows(out)] == ["skip"]
    assert "빌드 판정 불가 4/4" in _rows(out)[0]["evidence"]


def test_drift_manual_and_oversized_feedback_excluded():
    db = _drift_db()
    _rec(db, "MOCK-1261", "DATA-001-01", "MOCKA56_U1_20261010", "16", [], decision="manual")
    _rec(db, "MOCK-1262", "DATA-001-01", "MOCKA56_U1_20261011", "16", [])
    big = db / "feedback" / "2026-10" / "MOCK-1262-20261015T1000.yaml"
    big.write_text(big.read_text(encoding="utf-8") + "#" * (sa.DRIFT_MAX_BYTES + 1) + "\n", encoding="utf-8")
    out = _drift(db)
    assert not _rows(out, "needs-user")
    assert any("KiB 넘음 1" in r["evidence"] for r in _rows(out, "info"))


def test_drift_item_review_and_carry(site, fake_py):
    db = _old_hits(site["db"])
    _rec(db, "MOCK-1201", "DATA-001-01", "MOCKA56_U1_20261010", "16", [])
    _rec(db, "MOCK-1202", "unresolved", "MOCKA56_U1_20261012", "16", [], decision="unresolved")
    runner.git(db, "add", "-A")
    runner.git(db, "commit", "-qm", f"분석 기록 MOCK-1201\n\n{CLAUDE}")
    p = plan(site, repos=["ops_db"], cap=1)
    did = f"drift:ops_db:{SIG}"
    it = next(i for i in p["items"] if i["id"] == did)
    assert it["kind"] == "drift" and it["priority"] == "P1" and it["est_tokens"] == sa.DRIFT_TOKENS and it["slot"] == "미룸"
    assert any(c["id"] == "audit.ops_db.drift" and c["status"] == "needs-user" for c in p["checks"]) and p["exit"] == 1
    assert sa._carry_repo(did) == "ops_db"
    assert "update-signature" in sa.review_md({**p, "items": [{**it, "slot": "이번"}]})
    assert not site["marker"].exists()                                  # Claude를 부르지 않는다
    sa.write_plan(site["root"], p)
    sa.record(site["root"])
    state = json.loads((site["root"] / sa.STATE_FILE).read_text(encoding="utf-8"))
    assert did in state["carry"]
    p2 = plan(site, repos=["ops_db"])
    assert "이월" in next(i for i in p2["items"] if i["id"] == did)["flags"]


def _grounding(site, record) -> dict:
    (site["jobs"] / "MOCK-1003" / "check-output.json").write_text(json.dumps(record), encoding="utf-8")
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"])
    return next(c for c in p["checks"] if c["id"] == "audit.ops_db.grounding")


def test_grounding_skipped_is_not_pass(site, fake_py):
    g = _grounding(site, {"deep": {"skipped": "근거 원본 없음"}})
    assert g["status"] == "skip" and "건너뜀/오류 1" in g["evidence"]


def test_grounding_error_is_not_pass(site, fake_py):
    g = _grounding(site, {"deep": {"error": "읽기 실패", "fabricated": 0}})
    assert g["status"] == "skip" and "건너뜀/오류 1" in g["evidence"]


def test_grounding_source_null_is_not_pass(site, fake_py):
    g = _grounding(site, {"deep": {"quotes": 0, "fabricated": 0, "source": None}})
    assert g["status"] == "skip" and "건너뜀/오류 1" in g["evidence"]


def test_grounding_mixed_ok_and_skipped(site, fake_py):
    g = _grounding(site, {"deep": {"quotes": 2, "fabricated": 0, "weak": 0, "source": "a.log"},
                          "quick": {"skipped": True}})
    assert g["status"] == "skip" and "ok 0" in g["evidence"] and "건너뜀/오류 1" in g["evidence"]


# -- 알림(종합 리뷰 C①): 걸린 항목 → 이슈 DB 레포 Issue, 기본 보기만, 표식으로 중복 방지 ----------------------------------

@pytest.fixture
def fake_gh(monkeypatch):
    """`Ctx.gh` 바꿔치기(모의 gh 러너): 받은 인자를 기록하고 issue list는 `state["issues"]`(열린 것)를, create는 번호를 준다."""
    state = {"issues": [], "auth": 0, "calls": [], "list_fail": False}

    def gh(self, *args, host=None):
        state["calls"].append(list(args))
        if args[:2] == ("auth", "status"):
            return state["auth"], "", "" if state["auth"] == 0 else "not logged in"
        if args[:2] == ("issue", "list"):
            if state["list_fail"]:
                return 1, "", "HTTP 500"
            marker = args[args.index("--search") + 1].strip('"').replace('" in:title', "")
            rows = [i for i in state["issues"] if marker in i["title"] and i["state"] == "open"]
            return 0, json.dumps([{"number": i["number"], "title": i["title"], "url": i["url"]} for i in rows]), ""
        if args[:2] == ("issue", "create"):
            n = len(state["issues"]) + 1
            repo = args[args.index("--repo") + 1]
            title, body = args[args.index("--title") + 1], args[args.index("--body") + 1]
            state["issues"].append({"number": n, "title": title, "body": body, "state": "open", "repo": repo,
                                    "url": f"https://ghe.example/{repo}/issues/{n}"})
            return 0, f"Creating issue in {repo}\nhttps://ghe.example/{repo}/issues/{n}\n", ""
        raise AssertionError(f"뜻밖의 gh 호출: {args}")

    monkeypatch.setattr(sc.Ctx, "gh", gh)
    return state


def _plan_with_flags(site, fake_py):
    fake_py[0]["mask_pii.py"] = (1, {"detections": [{"path": f"{TYPE}/type.md", "line": 3, "kind": "MSISDN"}]})     # P0 기록
    fake_py[0]["db_verify.py"] = (1, {"rules": [{"id": "R3", "status": "fail", "targets": ["DATA-001"]}]})       # P1 기록
    fake_py[0]["db_lint.py"] = (1, {"errors": [{"code": "e1", "files": ["sim/SIM-001-x/type.md"]}], "warnings": []})  # 실패 행
    p = plan(site, since=[f"ops_db={site['init']}"], repos=["ops_db"])
    sa.write_plan(site["root"], p)
    return p


def test_notify_candidates_only_p0_p1_and_failed_checks(site, fake_py):
    p = _plan_with_flags(site, fake_py)
    cands = sa.notify_candidates(p)
    ids = [c["id"] for c in cands]
    assert any(i.startswith("rec:ops_db:") for i in ids) and "audit.ops_db.lint" in ids
    assert all(c["title"] == f"{sa.ISSUE_PREFIX} {c['id']}" and c["repo"] == "ops_db" for c in cands)
    rec = next(c for c in cands if c["id"].startswith("rec:"))
    assert "근거: 마스킹 안 됨 MSISDN" in rec["body"] and "git -C" in rec["body"] and "커밋: " in rec["body"]
    for line in (site["db"] / TYPE / "fixtures").glob("*.log"):           # 본문에 로그 원문은 없다
        for raw in line.read_text(encoding="utf-8").splitlines()[:5]:
            assert raw.strip() and raw not in rec["body"]
    # 모듈 항목(M)·P2는 후보가 아니다
    assert sa.notify_candidates({"items": [{"id": "mod:ofono/data", "kind": "module", "priority": "M", "repo": "modules"},
                                           {"id": "rec:ops_db:abc", "kind": "record", "priority": "P2", "repo": "ops_db"}],
                                 "checks": [{"id": "audit.ops_db.window", "status": "info"},
                                            {"id": "audit.modules.check", "status": "fail"}]}) == []


def test_notify_dry_run_reads_only_and_create_dedups(site, fake_py, fake_gh):
    p = _plan_with_flags(site, fake_py)
    (site["root"] / sc.STEPS_FILE).write_text(f"ops_db: {site['db']}\nops_db_repo: org/ops-db\n", encoding="utf-8")
    ctx = sc.Ctx(site["root"])
    try:
        res = sa.notify(ctx, p)                                             # 보기만: auth·list만 부른다
        assert res["exit"] == 0 and res["created"] == 0
        assert {r["status"] for r in res["rows"]} == {"would-create"} and len(res["rows"]) >= 2
        assert not any(c[:2] == ["issue", "create"] for c in fake_gh["calls"])
        assert sum(1 for c in fake_gh["calls"] if c[:2] == ["auth", "status"]) == 1
        text = sa.render_notify(res)
        assert "보기만" in text and "--notify --create" in text and "만들 것" in text
        made = sa.notify(ctx, p, create=True)                               # 만든다
        assert made["exit"] == 0 and made["created"] == len(res["rows"])
        assert all(r["status"] == "created" and r["url"].startswith("https://ghe.example/org/ops-db/issues/") for r in made["rows"])
        create = next(c for c in fake_gh["calls"] if c[:2] == ["issue", "create"])
        assert create[2:4] == ["--repo", "org/ops-db"] and create[5].startswith(sa.ISSUE_PREFIX)
        again = sa.notify(ctx, p, create=True)                              # 같은 표식이 열려 있으면 안 만든다
        assert again["created"] == 0 and {r["status"] for r in again["rows"]} == {"exists"}
        assert all(r["detail"].startswith("#") for r in again["rows"])
        for i in fake_gh["issues"]:                                          # 닫히면 다시 만든다(재발)
            i["state"] = "closed"
        assert sa.notify(ctx, p, create=True)["created"] == len(res["rows"])
    finally:
        ctx.cleanup()


def test_notify_dedup_needs_exact_title_not_prefix(site, fake_py, fake_gh):
    """코덱스 리뷰 R2: 검색은 낱말 단위라 `…/setup`을 찾아도 `…/setup-retry`가 돌아온다. 제목이 정확히 같은 열린 Issue만 "있음"이다."""
    p = _plan_with_flags(site, fake_py)
    (site["root"] / sc.STEPS_FILE).write_text(f"ops_db: {site['db']}\nops_db_repo: org/ops-db\n", encoding="utf-8")
    titles = [c["title"] for c in sa.notify_candidates(p)]
    assert titles
    for i, title in enumerate(titles):                                   # 접두사가 같은 **다른** ID의 열린 Issue
        fake_gh["issues"].append({"number": 100 + i, "title": title + "-retry", "body": "", "state": "open", "repo": "org/ops-db",
                                  "url": f"https://ghe.example/org/ops-db/issues/{100 + i}"})
    ctx = sc.Ctx(site["root"])
    try:
        res = sa.notify(ctx, p)
        assert {r["status"] for r in res["rows"]} == {"would-create"}       # 전에는 marker in title이라 전부 exists였다
        fake_gh["issues"].append({"number": 500, "title": "  " + titles[0] + " ", "body": "", "state": "open", "repo": "org/ops-db",
                                  "url": "https://ghe.example/org/ops-db/issues/500"})
        res = sa.notify(ctx, p)
        by = {r["id"]: r for r in res["rows"]}
        first = sa.notify_candidates(p)[0]["id"]
        assert by[first]["status"] == "exists" and by[first]["detail"] == "#500"   # 공백만 다른 같은 제목은 같다
        assert all(r["status"] == "would-create" for k, r in by.items() if k != first)
    finally:
        ctx.cleanup()


def test_notify_skips_without_repo_or_auth_and_reports_errors(site, fake_py, fake_gh):
    p = _plan_with_flags(site, fake_py)
    ctx = sc.Ctx(site["root"])                                              # steps.yaml에 ops_db_repo 없음
    try:
        res = sa.notify(ctx, p, create=True)
        assert res["exit"] == 1 and {r["status"] for r in res["rows"]} == {"skip"} and fake_gh["calls"] == []
        assert "ops_db_repo" in res["rows"][0]["detail"]
    finally:
        ctx.cleanup()
    (site["root"] / sc.STEPS_FILE).write_text(f"ops_db: {site['db']}\nops_db_repo: org/ops-db\n", encoding="utf-8")
    fake_gh["auth"] = 4
    ctx = sc.Ctx(site["root"])
    try:
        res = sa.notify(ctx, p, create=True)
        assert res["exit"] == 1 and {r["status"] for r in res["rows"]} == {"skip"} and "gh auth login" in res["rows"][0]["detail"]
        fake_gh["auth"], fake_gh["list_fail"] = 0, True
        res = sa.notify(ctx, p, create=True)
        assert res["exit"] == 1 and {r["status"] for r in res["rows"]} == {"error"} and fake_gh["issues"] == []
    finally:
        ctx.cleanup()


def test_notify_cli_needs_plan_and_flags(site, fake_py, fake_gh, capsys):
    root = str(site["root"])
    assert ss.main(["--root", root, "audit", "--notify"]) == 2                          # 계획 없음
    assert "먼저" in capsys.readouterr().err
    _plan_with_flags(site, fake_py)
    (site["root"] / sc.STEPS_FILE).write_text(f"ops_db: {site['db']}\nops_db_repo: org/ops-db\n", encoding="utf-8")
    assert ss.main(["--root", root, "audit", "--notify", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["create"] is False and doc["rows"] and all(r["status"] == "would-create" for r in doc["rows"])
    assert ss.main(["--root", root, "audit", "--notify", "--create"]) == 0
    out = capsys.readouterr().out
    assert "만듦" in out and "https://ghe.example/org/ops-db/issues/1" in out
    assert sa.notify_candidates(sa.load_plan(site["root"]))                              # 계획 파일은 그대로(쓰지 않는다)
    for bad in (["audit", "--create"], ["audit", "--notify", "--record"], ["audit", "--notify", "--repo", "ops_db"],
                ["check", "--notify"]):
        with pytest.raises(SystemExit) as exc:
            ss.main(["--root", root, *bad])
        assert exc.value.code == 2
