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
import shutil
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
            "verify-fix", "fix-submitted", "migrate", "help", "status"]
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
    assert files == sorted(EXPECTED) and len(files) == 14
    table = (DOCS / "09-commands.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| `([a-z-]+)[ `]", table, re.M)
    assert sorted(set(names)) == sorted(EXPECTED)
    arch = (DOCS / "01-architecture.md").read_text(encoding="utf-8")
    assert "commands/" in arch and "(14개)" in arch


def test_every_command_has_description_and_argument_hint_where_it_takes_args():
    for name in EXPECTED:
        meta = _frontmatter(name)
        assert meta.get("description"), name
        if name not in NO_ARGS:
            assert meta.get("argument-hint"), f"{name}: 인자를 받는데 argument-hint 없음"


def test_skill_linked_commands_call_the_skill_and_others_call_scripts_only():
    for name in SKILL_LINKED:
        assert "telephony-triage" in (COMMANDS / f"{name}.md").read_text(encoding="utf-8"), name
    for name in ("sync", "search", "preview", "review", "sync-pr", "migrate", "status"):
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
    for name in ("search", "preview", "review", "help", "status"):
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



def test_flow_a_b_wording():
    """사용 흐름 A(찾기·분석)·B(등록) 구분: help 안내 줄·표 머리, SKILL 한 줄, db-authoring §0 준비물·리뷰어, record 안내."""
    skill_dir = REPO / "plugin" / "skills" / "telephony-triage"
    help_text = (COMMANDS / "help.md").read_text(encoding="utf-8")
    table = help_text.split("## 상황별 추천", 1)[1].split("\n## ", 1)[0]
    assert "흐름 A(찾기·분석)는 이슈 DB를 바꾸지 않거나 기존 원인에 사례만 더한다" in table
    assert "흐름 B(등록)는 새 유형·원인·규칙을 만들고" in table and "카테고리 오너(파서 규칙은 메인테이너)" in table
    assert "아래 안내 줄과 표를 그대로 보인다" in help_text
    assert len(re.findall(r"^\| \(A\) ", table, re.M)) >= 3 and len(re.findall(r"^\| \(B\) ", table, re.M)) >= 2
    assert "`record <JIRA-KEY> --new-cause <유형 ID>`" in table
    skill = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    for needle in ("**A 찾기·분석**", "**B 등록**", "`db-authoring.md` §0", "흐름은 묻지 않고(기본 analyze) A에 B를 권하지 않는다", "기록하지 않음·중간 취소",
                   "기록 전환은 플래그만 빼고 같은 명령(`--issue-file`이면 `--dry-run`", "`[--platform <p>]` 필수", "`rules.md` 대상만"):
        assert needle in skill, needle
    authoring = (skill_dir / "reference" / "db-authoring.md").read_text(encoding="utf-8")
    sec0 = authoring.split("## 0. 등록(흐름 B) 준비물·리뷰어", 1)[1].split("\n## 1.", 1)[0]
    for needle in ("CODEOWNERS", "메인테이너", "`unjudged`", "`triage.py release <KEY>`", "`db_pr discard <wt>`", "dir_slug"):
        assert needle in sec0, needle
    assert "op 필수 키 (" not in sec0 and "S/" not in sec0
    record = (skill_dir / "reference" / "record.md").read_text(encoding="utf-8")
    assert "준비물·리뷰어 목록은 `db-authoring.md` §0" in record

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


def test_token_waste_wording_in_review_record_and_search():
    """review 1단계는 오너만(`--owners`, 전체 리뷰 안 돌림), record 초안 검증은 기본(접힌) 출력, search는 질의가
    keyword일 때만 키·ID로 다시 검색한다."""
    review = (COMMANDS / "review.md").read_text(encoding="utf-8")
    assert "db_review.py --owners" in review and "`db_review.py --json`을 먼저" not in review
    record = (REFERENCE / "record.md").read_text(encoding="utf-8")
    line = next(l for l in record.splitlines() if "db_verify.py rules --plan" in l and "--draft" in l)
    assert "--verbose" not in line.split("`")[1]
    assert "접힌 세부가 필요하면 같은 명령에 `--verbose`" in record
    search = (REFERENCE / "search.md").read_text(encoding="utf-8")
    assert "최상위 `kind`(질의 종류)가 `keyword`이고" in search
    assert "최상위 `kind`가 `type-id`·`cause-id`·`issue`이면 다시 부르지 않는다(결과 항목의 `kind`(type·cause·issue)와 다르다)" in search
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))
    import db_review
    assert db_review.build_parser().parse_args(["--owners"]).owners is True


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
    (job / "issue_raw.json").write_text("{}", encoding="utf-8")
    if logs:
        (job / "logs").mkdir()
        (job / "logs" / "radio.txt").write_text("raw", encoding="utf-8")
    if age:
        _age(job, age)
    return job


def test_cleanup_sees_jobs_left_with_pre_rename_file_names():
    """개명 전 작업 파일(jira_raw.json·jira.json·jira_meta.json)만 남은 옛 JOB도 cleanup 대상이고 원문 잔여로 보인다(방어)."""
    ws = Workspace()
    for name, files in (("OLD-1", ("jira_raw.json",)), ("OLD-2", ("jira.json", "jira_meta.json"))):
        job = ws.work / name
        job.mkdir(parents=True)
        for f in files:
            (job / f).write_text("{}", encoding="utf-8")
        _age(job, 120)
    unpub = ws.plan("MOCK-7003", "p7-analyze-append.plan.json").parent
    (unpub / "jira_raw.json").write_text("{}", encoding="utf-8")
    _age(unpub)
    dry = ws.db_pr("cleanup", "--dry-run", "--older-than")
    assert {t["job"] for t in dry["targets"] if t["kind"] == "job-dir"} == {"OLD-1", "OLD-2"}
    assert {r["job"]: r["raw_remains"] for r in dry["retained"]} == {"MOCK-7003": True}


def test_cleanup_older_than_candidates_are_tool_jobs_only_and_dry_run_equals_yes():
    ws = Workspace()
    raw = _raw_job(ws, "RAW-1")                                      # 원문만 남은 중단 작업(plan.json 없음)
    recent = _raw_job(ws, "RECENT-1", age=None)
    copied = _raw_job(ws, "COPIED-1", age=None)                      # 방금 만든 폴더에 옛 mtime 파일을 복사
    old = time.time() - 120 * 86400
    os.utime(copied / "issue_raw.json", (old, old))
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
    (job / "issue_raw.json").write_text("{}", encoding="utf-8")
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
    assert len(list(COMMANDS.glob("*.md"))) == 14
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
    proc = _offline(str(labelset), "--json")
    assert proc.returncode == 1, proc.stderr          # 전부 오류 = 통과 아님
    out = json.loads(proc.stdout)
    assert out["summary"]["errors"] == 1 and out["summary"]["evaluated"] == 0
    assert out["summary"]["top1_accuracy"] is None
    assert "평가 0/전체 1" in _offline(str(labelset)).stdout


def _eval_with(tmp_path, monkeypatch, unjudged: dict | None, expect: str = "unresolved", causes: list | None = None) -> dict:
    """triage 결과를 꾸며 evaluate_item 한 건을 돌린다 (candidates의 cause 목록, unjudged)."""
    sys.path.insert(0, str(REPO / "tools"))
    import offline_eval
    analysis = {"status": "ok", "logs": {"in_range": True, "events": 3},
                "candidates": [{"cause": c} for c in (causes or [])]}
    if unjudged is not None:
        analysis["unjudged"] = unjudged
    monkeypatch.setattr(offline_eval, "_script", lambda root, name, args: subprocess.CompletedProcess(
        args, 0, json.dumps(analysis), ""))
    work = tmp_path / f"w{len(list(tmp_path.iterdir()))}"
    work.mkdir()
    item = {"key": "U-1", "logs": ["none.log"], "occurred_at": "2026-09-20T14:32:10+09:00", "expect": expect}
    return offline_eval.evaluate_item(tmp_path, tmp_path, tmp_path, {}, item, work)


def test_offline_eval_unresolved_without_candidates_is_correct_when_fully_judged(tmp_path, monkeypatch):
    r = _eval_with(tmp_path, monkeypatch, None)
    import offline_eval
    s = offline_eval.summarize([r])
    assert r["error"] is None and r["warning"] is None and r["unjudged"] is None
    assert r["verdict"] == "정답" and s["evaluated"] == 1 and s["unjudged_errors"] == 0


def test_offline_eval_unjudged_unresolved_without_cause_candidate_is_error(tmp_path, monkeypatch):
    # S/C null 유형 → 판정 불가 = 오류(분모 제외). 유형만 후보(cause: null)도 오탐 확정이 아니다
    r = _eval_with(tmp_path, monkeypatch, {"count": 1, "types": ["DATA-001"],
                                           "errors": [{"signature": "DATA-001/slow", "error": "timeout"}]}, causes=[None])
    import offline_eval
    assert r["error"] == "판정 불가(시그니처 시간 초과·오류): 유형 1·원인 0 — DATA-001/slow: timeout"
    assert r["unjudged"] == {"count": 1, "cause_count": 0} and r["top"] is None and r["top3"] == []
    s = offline_eval.summarize([r])
    assert s["errors"] == s["unjudged_errors"] == 1 and s["evaluated"] == 0 and s["false_positive_rate"] is None
    # 원인만 판정 불가(목록은 크기 제한으로 빠질 수 있다)
    r = _eval_with(tmp_path, monkeypatch, {"count": 0, "cause_count": 1})
    assert r["error"] == "판정 불가(시그니처 시간 초과·오류): 유형 0·원인 1" and "—" not in r["error"]


def test_offline_eval_unjudged_positive_item_is_error_even_when_top_matches(tmp_path, monkeypatch):
    r = _eval_with(tmp_path, monkeypatch, {"count": 1}, expect="DATA-001-01", causes=["DATA-001-01"])
    import offline_eval
    assert r["error"].startswith("판정 불가") and r["top"] is None and r["top3"] == []   # 판정 못 한 유형이 앞설 수 있다
    s = offline_eval.summarize([r])
    assert s["positive"] == 0 and s["top1_accuracy"] is None and s["unjudged_errors"] == 1


def test_offline_eval_unjudged_unresolved_with_cause_candidate_is_definite_false_positive(tmp_path, monkeypatch):
    r = _eval_with(tmp_path, monkeypatch, {"count": 1, "errors": [{"signature": "X/slow", "error": "timeout"}]},
                   causes=[None, "DATA-001-01"])
    import offline_eval
    assert r["error"] is None and r["unjudged"] == {"count": 1, "cause_count": 0}
    assert r["warning"].startswith("판정 불완전(시그니처 시간 초과·오류): 유형 1·원인 0 — X/slow: timeout")
    s = offline_eval.summarize([r])
    assert r["verdict"] == "오탐" and s["false_positive_rate"] == 1.0 and s["errors"] == s["unjudged_errors"] == 0
    assert "경고 U-1: 판정 불완전" in offline_eval.render([r], s)


def test_offline_eval_signature_only_error_is_warning_and_evaluated(tmp_path, monkeypatch):
    # 충족된 유형의 다른 시그니처만 오류(count 0, cause_count 없음) → 평가하고 경고
    r = _eval_with(tmp_path, monkeypatch, {"count": 0, "errors": [{"signature": "DATA-001/slow", "error": "timeout"}]})
    import offline_eval
    assert r["error"] is None and r["warning"] == "시그니처 오류(S/C 영향 없음) — DATA-001/slow: timeout"
    assert r["unjudged"] is None
    s = offline_eval.summarize([r])
    assert r["verdict"] == "정답" and s["errors"] == 0 and s["evaluated"] == 1
    assert "경고 U-1: 시그니처 오류" in offline_eval.render([r], s)


def test_offline_eval_all_error_labelset_is_not_shown_as_pass(tmp_path, monkeypatch):
    r = _eval_with(tmp_path, monkeypatch, {"count": 1})
    import offline_eval
    s = offline_eval.summarize([r])
    assert s["evaluated"] == 0 and s["error_rate"] == 1.0
    text = offline_eval.render([r], s)
    assert "평가 가능한 항목 없음 — 전부 오류" in text and "그중 판정 불가 1건" in text
    assert "정답 원인 ID 0·unresolved 1, 평가된 것 원인 0·unresolved 0, 오류 1" in text
    assert s["positive_total"] == 0 and s["negative_total"] == 1
    labelset = tmp_path / "allerr.yaml"         # 실제 실행: 로그 범위 밖(연도 틀림) 한 건 → 종료 1
    labelset.write_text(yaml.safe_dump({
        "db": str(SAMPLE), "tz": "Asia/Seoul",
        "items": [{"key": "EVAL-1", "year": 2025, "occurred_at": "2026-09-20T14:32:10+09:00", "expect": "DATA-001-01",
                   "logs": [str(SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log")]}],
    }), encoding="utf-8")
    proc = _offline(str(labelset))
    assert proc.returncode == 1 and "평가 가능한 항목 없음" in proc.stdout and "전부 오류" in proc.stderr


def test_offline_eval_end_to_end_signature_timeout_is_unjudged_error(tmp_path):
    """실제 시간 초과 시그니처(test_triage_reuse의 slow-signature DB)로 unresolved 한 건 → 판정 불가 오류."""
    sys.path.insert(0, str(REPO / "tests"))
    from test_triage_reuse import LOG, _slow_symptom
    db = tmp_path / "db"
    shutil.copytree(SAMPLE, db)
    _slow_symptom(db)
    log = tmp_path / "slow.log"
    log.write_text(LOG.read_text(encoding="utf-8") + "09-20 14:30:40.000  1234  1244 D DNC-0: " + "a" * 40 + "!\n",
                   encoding="utf-8", newline="\n")
    labelset = tmp_path / "slow.yaml"
    labelset.write_text(yaml.safe_dump({
        "db": str(db), "tz": "Asia/Seoul", "year": 2026,
        "items": [{"key": "SLOW-1", "occurred_at": "2026-09-20T14:32:10+09:00", "expect": "unresolved",
                   "logs": [str(log)]}],
    }), encoding="utf-8")
    proc = _offline(str(labelset), "--json")
    assert proc.returncode == 1, proc.stderr
    out = json.loads(proc.stdout)
    assert out["summary"]["errors"] == out["summary"]["unjudged_errors"] == 1 and out["summary"]["evaluated"] == 0
    item = out["items"][0]
    assert item["error"].startswith("판정 불가") and item["unjudged"]["count"] >= 1


def test_offline_eval_rejects_bad_labelset(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("items: [{key: X-1}]\n", encoding="utf-8")
    proc = _offline(str(bad), "--db", str(SAMPLE))
    assert proc.returncode == 2 and "logs" in proc.stderr


if __name__ == "__main__":
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
