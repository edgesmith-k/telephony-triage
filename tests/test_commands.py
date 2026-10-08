#!/usr/bin/env python3
"""Phase 12 완료 기준 확인: 나머지 커맨드와 offline_eval (11-phases.md Phase 12).

커맨드 본문은 스킬·스크립트를 부르는 마크다운이라 실행 자체는 Claude Code가 한다.
여기서는 (1) 파일 목록·frontmatter가 설계와 맞는지, (2) 커맨드 본문이 부르는 스크립트 순서를
스킬 없이 그대로 돌려 보고(`sync`, 인자 없는 `validate`), (3) `tools/offline_eval.py`가 합성 라벨셋에서
표를 내는지 확인한다. 플러그인 로드(`${CLAUDE_PLUGIN_ROOT}` 치환, S1)는 이 테스트로 확인할 수 없다.

`pytest tests/test_commands.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import SAMPLE, git, git_db, run, run_json  # noqa: E402
from workspace import Workspace  # noqa: E402

COMMANDS = REPO / "plugin" / "commands"
DOCS = REPO / "docs" / "design"
EXPECTED = ["setup", "analyze", "record", "sync", "search", "sync-pr", "preview", "review", "validate",
            "verify-fix", "fix-submitted", "migrate", "help"]
SKILL_LINKED = ["analyze", "record", "verify-fix", "fix-submitted", "validate"]
NO_ARGS = ["setup", "sync", "preview"]


def _frontmatter(name: str) -> dict:
    text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, f"{name}.md: frontmatter 없음"
    return yaml.safe_load(match.group(1))


# -- 파일 목록·frontmatter ------------------------------------------------------------------------


def test_command_files_match_design_lists():
    files = sorted(p.stem for p in COMMANDS.glob("*.md"))
    assert files == sorted(EXPECTED) and len(files) == 13
    table = (DOCS / "09-commands.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| `([a-z-]+)[ `]", table, re.M)
    assert sorted(set(names)) == sorted(EXPECTED)
    arch = (DOCS / "01-architecture.md").read_text(encoding="utf-8")
    assert "commands/" in arch and "(13개)" in arch


def test_every_command_has_description_and_argument_hint_where_it_takes_args():
    for name in EXPECTED:
        meta = _frontmatter(name)
        assert meta.get("description"), name
        if name not in NO_ARGS:
            assert meta.get("argument-hint"), f"{name}: 인자를 받는데 argument-hint 없음"


def test_skill_linked_commands_call_the_skill_and_others_call_scripts_only():
    for name in SKILL_LINKED:
        assert "telephony-triage" in (COMMANDS / f"{name}.md").read_text(encoding="utf-8"), name
    for name in ("sync", "search", "preview", "review", "sync-pr", "migrate"):
        text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "${CLAUDE_PLUGIN_ROOT}/scripts/" in text, name


def test_commands_stop_on_missing_site_defaults():
    for name in [n for n in EXPECTED if n != "help"]:      # help는 파일만 읽는다(스크립트 없음)
        text = (COMMANDS / f"{name}.md").read_text(encoding="utf-8")
        assert "S-3" in text, f"{name}: 사내 기본값 없음 중단 규칙 없음"


def test_write_commands_take_session_lock_and_readonly_commands_do_not():
    # sync-pr 절차의 단일 원본은 reference/sync-pr.md다 (커맨드는 그 파일을 가리키기만 한다)
    reference = REPO / "plugin" / "skills" / "telephony-triage" / "reference" / "sync-pr.md"
    assert "reference/sync-pr.md" in (COMMANDS / "sync-pr.md").read_text(encoding="utf-8")
    for name, path in (("sync", COMMANDS / "sync.md"), ("sync-pr", reference)):
        text = path.read_text(encoding="utf-8")
        assert "lock acquire" in text and "lock release" in text, name
    for name in ("search", "preview", "review", "help"):
        assert "lock acquire" not in (COMMANDS / f"{name}.md").read_text(encoding="utf-8"), name


def test_help_lists_commands_from_files_and_recommends_only_existing_ones():
    """help는 목록을 적지 않고 commands/*.md frontmatter에서 만든다. 상황별 추천 표의 커맨드는 실제 파일이어야 한다."""
    text = (COMMANDS / "help.md").read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}/commands/*.md" in text and "argument-hint" in text and "description" in text
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/" not in text, "help는 스크립트를 부르지 않는다 (site-defaults 검사 제외의 근거)"
    assert "`[a-z-]+`" in text and "소문자" in text, "커맨드 이름은 소문자 [a-z-]+ 만 파일로 찾는다 (경로 이탈 방지)"
    table = text.split("## 상황별 추천", 1)[1].split("\n## ", 1)[0]
    rows = re.findall(r"^\|[^|\n]+\| `([a-z-]+)([^`]*)`", table, re.M)
    names = {name for name, _ in rows}
    files = {p.stem for p in COMMANDS.glob("*.md")}
    assert names and names <= files, names - files
    for name, rest in rows:       # 추천 표의 옵션은 그 커맨드의 argument-hint에 있는 것만
        hint = str(_frontmatter(name).get("argument-hint") or "")
        assert set(re.findall(r"--[A-Za-z0-9-]+", rest)) <= set(re.findall(r"--[A-Za-z0-9-]+", hint)), (name, rest)


# -- sync: 본문이 부르는 스크립트 순서 ------------------------------------------------------------


REFERENCE = REPO / "plugin" / "skills" / "telephony-triage" / "reference"


def test_reference_calls_use_flags_the_scripts_accept():
    """write-flow.md가 부르는 `--format markdown`이 실제 argparse에 있고 값이 choices에 든다.
    search.md는 W2 eval 53(출력 토큰 증가)으로 `--brief` JSON 호출을 유지한다(markdown은 opt-in으로만 남김)."""
    search, flow = (REFERENCE / "search.md").read_text(encoding="utf-8"), (REFERENCE / "write-flow.md").read_text(encoding="utf-8")
    assert "db_search.py --db SNAP" in search and "--brief" in search and "--format markdown" not in search
    assert "summary <wt> --format markdown" in flow     # stage 성공·summary 실패 때 다시 부르는 호출
    assert "stage <plan> --wt <wt> --branch <br> [--dry-run] --then-summary" in flow
    assert "--commit --and-discard" in flow
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import db_pr, db_search
    assert db_search.build_parser().parse_args(["q", "--format", "markdown"]).format == "markdown"
    assert db_pr.build_parser().parse_args(["summary", "wt", "--format", "markdown"]).format == "markdown"
    assert db_pr.build_parser().parse_args(["summary", "wt"]).format == "json"
    parser = db_pr.build_parser()
    assert parser.parse_args(["stage", "p.json", "--wt", "wt", "--branch", "b", "--then-summary"]).then_summary is True
    assert parser.parse_args(["stage", "p.json", "--wt", "wt", "--branch", "b"]).then_summary is False
    pub = parser.parse_args(["publish", "wt", "--branch", "b", "--lease", "new", "--approved", "h", "--commit",
                             "--and-discard"])
    assert pub.commit is True and pub.and_discard is True
    pub = parser.parse_args(["publish", "wt", "--branch", "b", "--lease", "new", "--approved", "h"])
    assert pub.commit is False and pub.and_discard is False



def test_sync_sequence_lists_closed_pr_workdir_and_deletes_only_after_yes():
    ws = Workspace()
    plan = ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")
    published = ws.read_plan("MOCK-7001")
    assert (published.get("pr") or {}).get("number"), "publish가 계획에 PR 번호를 남겨야 한다"
    prs_path = ws.gh_state / "prs.json"
    state = json.loads(prs_path.read_text(encoding="utf-8"))
    state["prs"][0]["state"] = "CLOSED"
    prs_path.write_text(json.dumps(state), encoding="utf-8")
    _age(ws.job_dir("MOCK-7001"))

    assert ws.db_pr("lock", "acquire", "sync", "--command", "sync")["acquired"]
    snap = ws.db_pr("snapshot", "--job", "sync")
    assert snap["snapshot_sha"] and "post_lint" in snap
    assert ws.db_pr("lock", "release", "sync")["released"] is True

    dry = ws.db_pr("cleanup", "--dry-run", "--older-than")
    jobs = [t for t in dry["targets"] if t["kind"] == "job-dir"]
    assert [t["job"] for t in jobs] == ["MOCK-7001"] and jobs[0]["pr_state"] == "CLOSED"
    assert dry["removed"] == [] and plan.parent.exists(), "확인 전에는 지우지 않는다"

    done = ws.db_pr("cleanup", "--yes", "--older-than")
    assert not plan.parent.exists() and any(t["kind"] == "job-dir" for t in done["removed"])
    assert (ws.work / "_snapshot").exists(), "스냅샷은 지우지 않는다"


def _age(path: Path, days: int = 120) -> None:
    old = time.time() - days * 86400
    for p in [path, *path.rglob("*")]:
        os.utime(p, (old, old))


def _raw_job(ws, name: str, *, age: int | None = 120, logs: bool = True) -> Path:
    job = ws.work / name
    job.mkdir(parents=True)
    (job / "jira_raw.json").write_text("{}", encoding="utf-8")
    if logs:
        (job / "logs").mkdir()
        (job / "logs" / "radio.txt").write_text("raw", encoding="utf-8")
    if age:
        _age(job, age)
    return job


def test_cleanup_older_than_candidates_are_tool_jobs_only_and_dry_run_equals_yes():
    ws = Workspace()
    raw = _raw_job(ws, "RAW-1")                                      # 원문만 남은 중단 작업(plan.json 없음)
    recent = _raw_job(ws, "RECENT-1", age=None)
    copied = _raw_job(ws, "COPIED-1", age=None)                      # 방금 만든 폴더에 옛 mtime 파일을 복사
    old = time.time() - 120 * 86400
    os.utime(copied / "jira_raw.json", (old, old))
    empty = ws.work / "EMPTY-NEW"
    (empty / "logs").mkdir(parents=True)                             # 방금 만든 빈 폴더(표식만)
    photos = ws.work / "photos"                                      # 도구와 무관한 폴더
    photos.mkdir()
    (photos / "a.jpg").write_text("x", encoding="utf-8")
    hidden = ws.work / ".cache"
    hidden.mkdir()
    (hidden / "x").write_text("x", encoding="utf-8")
    logs_only = ws.work / "photos2"                                  # 작업 키 형식 이름 + logs/만(표식 아님)
    (logs_only / "logs").mkdir(parents=True)
    (logs_only / "logs" / "a.txt").write_text("x", encoding="utf-8")
    for d in (photos, hidden, logs_only):
        _age(d)
    unpub = ws.plan("MOCK-7003", "p7-analyze-append.plan.json").parent   # 미게시 계획(PR 없음)
    (unpub / "logs").mkdir()
    (unpub / "logs" / "radio.txt").write_text("raw", encoding="utf-8")
    _age(unpub)
    pushed = ws.plan("MOCK-7006", "p7-analyze-append.plan.json").parent      # push 기록 있음·PR 번호 없음
    plan_file = pushed / "plan.json"
    doc = json.loads(plan_file.read_text(encoding="utf-8"))
    doc["pr"] = {"number": None, "branch": "issue/MOCK-7006", "head_sha": "a" * 40}
    plan_file.write_text(json.dumps(doc), encoding="utf-8")
    _age(pushed)
    locked = ws.plan("MOCK-7005", "p7-analyze-append.plan.json").parent
    assert ws.acquire("MOCK-7005")["acquired"]
    _age(locked)

    dry = ws.db_pr("cleanup", "--dry-run", "--older-than")
    jobs = {t["job"]: t for t in dry["targets"] if t["kind"] == "job-dir"}
    assert set(jobs) == {"RAW-1"} and jobs["RAW-1"]["pr"] is None
    kept = {r["job"]: r for r in dry["retained"]}
    assert set(kept) == {"MOCK-7003", "MOCK-7006"} and kept["MOCK-7003"]["raw_remains"] is True
    assert kept["MOCK-7003"]["state"] == "unpublished" and "미게시 계획 보존" in kept["MOCK-7003"]["note"]
    assert kept["MOCK-7006"]["state"] == "pushed-no-pr" and kept["MOCK-7006"]["raw_remains"] is False
    assert "PR 연결 미확인" in kept["MOCK-7006"]["note"] and "sync-pr" in kept["MOCK-7006"]["note"]
    assert "생성 실패" not in kept["MOCK-7006"]["note"]
    assert kept["MOCK-7003"]["days"] >= 119 and kept["MOCK-7003"]["path"] == str(unpub)
    assert dry["removed"] == [] and raw.exists(), "dry-run은 지우지 않는다"

    done = ws.db_pr("cleanup", "--yes", "--older-than")
    assert [t["job"] for t in done["removed"] if t["kind"] == "job-dir"] == list(jobs)    # dry-run 목록 = --yes 대상
    assert done["failed"] == [] and {r["job"]: r["state"] for r in done["retained"]} == {r["job"]: r["state"] for r in dry["retained"]}
    assert not raw.exists()
    for keep in (recent, copied, empty, photos, hidden, logs_only, unpub, pushed, locked):
        assert keep.exists(), keep


def test_cleanup_older_than_reports_failed_when_directory_remains(tmp_path, monkeypatch):
    import importlib
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    sys.path.insert(0, str(REPO / "tests"))
    from test_safety import safety_ctx
    module, ctx = safety_ctx(tmp_path)
    job = ctx.work_dir / "RAW-9"
    (job / "logs").mkdir(parents=True)
    (job / "logs" / "r.txt").write_text("raw", encoding="utf-8")
    (job / "jira_raw.json").write_text("{}", encoding="utf-8")
    _age(job)
    monkeypatch.setattr(module.shutil, "rmtree", lambda *a, **k: None)      # 지우지 못하는 상황
    out = module.cleanup(ctx, True, 90)
    assert [t["job"] for t in out["failed"]] == ["RAW-9"] and out["removed"] == []
    assert job.exists()


def test_sync_and_setup_bodies_list_new_steps_in_order():
    sync = (COMMANDS / "sync.md").read_text(encoding="utf-8")
    calls = [sync.index(c) for c in ("lock acquire sync", "snapshot --job sync",
                                     "lock release sync", "cleanup --dry-run", "db_pr.py my-prs")]
    assert calls == sorted(calls), "my-prs는 cleanup 뒤(5번, lock 밖)다"
    assert "--cache-only" not in sync, "매칭 파일 캐시는 없다 (06 §6.8)"
    assert "base_sha_changed" in sync and "sync-pr" in sync[calls[-1]:] and "안내만" in sync[calls[-1]:]
    setup = (COMMANDS / "setup.md").read_text(encoding="utf-8")
    order = [setup.index(c) for c in ("config.py gh-status", "config.py doctor --format markdown", "getting-started.md")]
    assert order == sorted(order) and "그대로" in setup[order[1]:order[2]]
    assert "doctor" in setup[order[0]:order[1]], "gh 실패 경로도 doctor 표를 보인다"
    skill = (REPO / "plugin" / "skills" / "telephony-triage" / "SKILL.md").read_text(encoding="utf-8")
    assert "config.py doctor --format markdown" in skill
    assert len(list(COMMANDS.glob("*.md"))) == 13
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import config, db_pr
    assert config.build_parser().parse_args(["doctor"]).format == "json"
    assert config.build_parser().parse_args(["doctor", "--format", "markdown"]).format == "markdown"
    assert db_pr.build_parser().parse_args(["my-prs"]).cmd == "my-prs"


def test_sync_sequence_keeps_recent_or_open_pr_workdirs():
    ws = Workspace()
    ws.plan("MOCK-7001", "p7-analyze-append.plan.json")
    ws.ship("MOCK-7001", "issue/MOCK-7001")
    dry = ws.db_pr("cleanup", "--dry-run", "--older-than")
    assert not [t for t in dry["targets"] if t["kind"] == "job-dir"]


# -- 인자 없는 validate: 본문이 부르는 스크립트 순서 --------------------------------------------------


def _validate_chain(repo: Path, extra: list | None = None) -> dict[str, int]:
    """validate.md 본문 순서. 종료 코드를 단계별로 모은다."""
    steps = {
        "lint": ("db_lint.py", ["--changed", "HEAD", "--db", repo]),
        "mask": ("mask_pii.py", ["--check", "--changed", "HEAD", "--db", repo]),
        "regress": ("db_regress.py", ["--all", "--db", repo]),
        "rules": ("db_verify.py", ["rules", "--changed", "HEAD", "--db", repo, *(extra or [])]),
        "build": ("db_build.py", ["--verify", "--db", repo]),
    }
    return {name: run(script, [str(a) for a in args]).returncode for name, (script, args) in steps.items()}


def test_argless_validate_chain_passes_on_clean_db_and_catches_a_broken_change():
    repo = git_db()
    run_json("db_build.py", ["--write", "--db", repo])
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "generated")
    assert _validate_chain(repo) == {"lint": 0, "mask": 0, "regress": 0, "rules": 0, "build": 0}

    fixture = repo / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
    fixture.write_text(fixture.read_text(encoding="utf-8").replace("DATA_DISABLED", "SOMETHING_ELSE"),
                       encoding="utf-8", newline="\n")
    codes = _validate_chain(repo)
    assert codes["regress"] != 0, "양성 fixture를 깨면 전체 회귀가 잡는다"


def test_validate_changes_are_read_only():
    repo = git_db()
    before = git(repo, "status", "--porcelain")
    _validate_chain(repo)
    assert git(repo, "status", "--porcelain") == before


# -- offline_eval ------------------------------------------------------------------------------------


def _offline(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO / "tools" / "offline_eval.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_offline_eval_prints_accuracy_table_on_synthetic_labelset():
    proc = _offline(str(REPO / "tests" / "fixtures" / "offline-eval-sample.yaml"), "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    summary = out["summary"]
    assert summary["total"] == 8 and summary["errors"] == 0
    assert summary["positive"] == 7 and summary["negative"] == 1
    assert summary["top1_accuracy"] == round(6 / 7, 4)      # EVAL-8은 일부러 틀린 라벨
    assert summary["top3_inclusion"] == round(6 / 7, 4)
    assert summary["false_positive_rate"] == 0.0
    verdicts = {r["key"]: r["verdict"] for r in out["items"]}
    assert verdicts["EVAL-1"] == "1위" and verdicts["EVAL-7"] == "정답" and verdicts["EVAL-8"] == "미스"
    meta = out["meta"]
    assert meta["labelset_sha256"] == hashlib.sha256((REPO / "tests/fixtures/offline-eval-sample.yaml").read_bytes()).hexdigest()
    assert meta["python"] == platform.python_version() and meta["argv"][-1] == "--json"
    assert set(meta["plugin_repo"]) == set(meta["db"]) == {"sha", "dirty"}
    assert meta["db"] == {"sha": None, "dirty": None}   # 샘플 DB는 플러그인 레포 하위 폴더(git 최상위 아님)
    root = Path(meta["plugin_root"]["path"])
    assert meta["plugin_root"]["temporary"] is True and not root.exists()      # 임시 루트는 실행 뒤 지운다
    assert meta["site_defaults_sha256"] == hashlib.sha256((REPO / "plugin/site-defaults.example.yaml").read_bytes()).hexdigest()
    item = out["items"][0]
    assert item["logs_sha256"] and all(len(h) == 64 for h in item["logs_sha256"])
    assert item["backend"]["name"] and "version" in item["backend"] and item["external"] == []    # 외부 파서 없음


def test_offline_eval_text_table_has_the_three_metrics():
    proc = _offline(str(REPO / "tests" / "fixtures" / "offline-eval-sample.yaml"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("meta: ")
    for label in ("1위 정확도", "상위 3 포함률", "오탐률", "EVAL-8"):
        assert label in proc.stdout


def test_offline_eval_counts_false_positive_when_unresolved_expected_but_candidate_produced(tmp_path):
    labelset = tmp_path / "fp.yaml"
    labelset.write_text(yaml.safe_dump({
        "db": str(SAMPLE), "tz": "Asia/Seoul", "year": 2026,
        "items": [{"key": "FP-1", "occurred_at": "2026-09-20T14:32:10+09:00", "expect": "unresolved",
                   "logs": [str(SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log")]}],
    }), encoding="utf-8")
    proc = _offline(str(labelset), "--json")
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["summary"]["false_positive_rate"] == 1.0 and out["items"][0]["verdict"] == "오탐"


def _summ(**kw):
    sys.path.insert(0, str(REPO / "tools"))
    import offline_eval
    base = {"key": "K", "expect": "unresolved", "error": None, "top3": [], "top": None}
    return offline_eval.summarize([{**base, **r} for r in kw["items"]])


def test_offline_eval_type_only_candidate_is_not_false_positive_and_error_rate_reported():
    s = _summ(items=[{"top3": [None], "top": None},                       # 유형만(cause: null)
                     {"top3": ["DATA-001-01"], "top": "DATA-001-01"},     # 원인 후보 = 오탐
                     {"error": "triage 종료 1"}])
    assert s["type_only"] == 1 and s["false_positive_rate"] == 0.5
    assert s["error_rate"] == round(1 / 3, 4)


def test_offline_eval_type_only_counts_only_all_none_unresolved_and_edge_groups():
    assert _summ(items=[{"top3": [None, "X-01"], "top": None}])["type_only"] == 0     # 혼합: 오탐이지 유형만 아님
    mixed = _summ(items=[{"top3": [None, "X-01"], "top": None}])
    assert mixed["false_positive_rate"] == 1.0
    assert _summ(items=[{"top3": []}])["type_only"] == 0                              # 빈 목록
    pos = _summ(items=[{"expect": "X-01", "top3": [None, "X-01"], "top": None}])
    assert pos["type_only"] == 0 and pos["top3_inclusion"] == 1.0                     # 양성은 세지 않는다
    allerr = _summ(items=[{"error": "e"}, {"error": "e"}])
    assert allerr["error_rate"] == 1.0 and allerr["false_positive_rate"] is None and allerr["top1_accuracy"] is None
    assert _summ(items=[{"expect": "X-01", "top3": ["X-01"], "top": "X-01"}])["false_positive_rate"] is None   # 평가군 없음


def test_offline_eval_defaults_year_from_occurred_at(tmp_path):
    labelset = tmp_path / "noyear.yaml"
    labelset.write_text(yaml.safe_dump({
        "db": str(SAMPLE), "tz": "Asia/Seoul",
        "items": [{"key": "EVAL-1", "occurred_at": "2026-09-20T14:32:10+09:00", "expect": "DATA-001-01",
                   "logs": [str(SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log")]}],
    }), encoding="utf-8")
    proc = _offline(str(labelset), "--json")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["items"][0]["verdict"] == "1위"


def test_offline_eval_out_of_range_item_is_error_not_scored(tmp_path):
    labelset = tmp_path / "wrongyear.yaml"
    labelset.write_text(yaml.safe_dump({
        "db": str(SAMPLE), "tz": "Asia/Seoul",
        "items": [{"key": "EVAL-1", "year": 2025, "occurred_at": "2026-09-20T14:32:10+09:00",
                   "expect": "DATA-001-01",
                   "logs": [str(SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log")]}],
    }), encoding="utf-8")
    out = json.loads(_offline(str(labelset), "--json").stdout)
    assert out["summary"]["errors"] == 1 and out["summary"]["evaluated"] == 0
    assert out["summary"]["top1_accuracy"] is None
    assert "평가 0/전체 1" in _offline(str(labelset)).stdout


def test_offline_eval_rejects_bad_labelset(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("items: [{key: X-1}]\n", encoding="utf-8")
    proc = _offline(str(bad), "--db", str(SAMPLE))
    assert proc.returncode == 2 and "logs" in proc.stderr


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
