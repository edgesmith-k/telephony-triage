#!/usr/bin/env python3
"""회귀 성능 변경이 판정을 바꾸지 않는지 (06-collaboration.md §6.8, contracts.md §3.2 이슈 기록 제외).

- `parser_rules.load` 내용 해시 캐시: 캐시 없음·빈 캐시·찬 캐시의 `db_regress` stdout이 바이트 동일,
  같은 경로 파일 수정·두 트리 번갈아 로드에서 섞이지 않음, 파싱이 캐시된 Rules를 바꾸지 않음.
- 이슈 기록·피드백은 `--all` 판정에 들어가지 않는다.
- `--staged`: 이슈 기록만 바뀐 유형은 빠지고 사유가 남는다. 이름 바뀐 파일은 옛 경로도 범위.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

from runner import copy_db, edit, git, git_db, plugin_root, run  # noqa: E402

ROOT = plugin_root()
sys.path.insert(0, str(ROOT / "scripts"))

from common import checks, gitscope, parser_rules  # noqa: E402

D = "data/DATA-001-no-setup-data-call"
C = "call/CALL-001-volte-not-working"
EXTRACTOR_EVENT = "event: data_evaluation_rejected"


def _inproc(*args) -> tuple[int, str]:
    code, out, _ = checks.run_in_process("db_regress.py", [*map(str, args), "--plugin-root", str(ROOT)])
    return code, out


def _break_negative(db: Path) -> None:
    log = db / D / "fixtures/DATA-001.none.log"
    kept = [line.replace("Data allowed reason: NORMAL", "Data disallowed reasons: CONGESTED")
            for line in log.read_text(encoding="utf-8").splitlines(keepends=True) if "SETUP_DATA_CALL" not in line]
    log.write_text("".join(kept), encoding="utf-8", newline="\n")


def test_cache_does_not_change_output(monkeypatch):
    db = copy_db()
    _break_negative(db)
    repo = git_db()
    edit(repo / "parser-rules/extractors.yaml", EXTRACTOR_EVENT, "event: data_eval_rejected_v2")
    for args, code in ((["--db", db, "--all"], 1), (["--db", repo, "--events-diff", "main"], 0)):
        monkeypatch.setattr(parser_rules, "_CACHE_MAX", 0)       # 캐시 없음(예전 동작)
        parser_rules._CACHE.clear()
        cold = _inproc(*args)
        monkeypatch.setattr(parser_rules, "_CACHE_MAX", 8)
        parser_rules._CACHE.clear()
        first, warm = _inproc(*args), _inproc(*args)
        assert cold[0] == code and cold == first == warm
    assert json.loads(cold[1])["summary"]["existing_changed"] is True   # events-diff에 변화가 실제로 있다


def _fingerprint(rules) -> list:
    return [(e.id, e.event, [p.pattern for p in e.patterns]) for e in rules.extractors]


def test_cache_keys_on_content_not_path():
    a = copy_db(name="a")
    rules_a = parser_rules.load(a / "parser-rules")
    edit(a / "parser-rules/extractors.yaml", EXTRACTOR_EVENT, "event: changed_in_place")   # 같은 경로, 다른 내용
    rules_a2 = parser_rules.load(a / "parser-rules")
    assert _fingerprint(rules_a) != _fingerprint(rules_a2)
    assert "changed_in_place" in {e.event for e in rules_a2.extractors}

    b = copy_db(name="b")
    for _ in range(3):                                         # 내용 다른 두 트리를 번갈아 로드
        got_a, got_b = parser_rules.load(a / "parser-rules"), parser_rules.load(b / "parser-rules")
        assert _fingerprint(got_a) == _fingerprint(rules_a2) and got_a.path == a / "parser-rules"
        assert _fingerprint(got_b) == _fingerprint(rules_a) and got_b.path == b / "parser-rules"

    (b / "parser-rules/tags.yaml").write_text("tags: [", encoding="utf-8")   # 오류는 캐시하지 않는다
    for _ in range(2):
        with pytest.raises(parser_rules.RulesError):
            parser_rules.load(b / "parser-rules")


def test_file_changed_during_load_is_not_cached(monkeypatch):
    db = copy_db()
    original = parser_rules._load

    def racing(rules_dir, schema_path):
        rules = original(rules_dir, schema_path)
        edit(rules_dir / "extractors.yaml", EXTRACTOR_EVENT, "event: changed_mid_load")   # 읽은 뒤 바뀜
        return rules

    monkeypatch.setattr(parser_rules, "_load", racing)
    parser_rules._CACHE.clear()
    parser_rules.load(db / "parser-rules")
    assert not parser_rules._CACHE
    monkeypatch.setattr(parser_rules, "_load", original)
    assert "changed_mid_load" in {e.event for e in parser_rules.load(db / "parser-rules").extractors}


def test_parsing_does_not_mutate_cached_rules():
    import db_regress
    from common import site_defaults

    db = copy_db()
    parser_rules._CACHE.clear()
    parser_rules.load(db / "parser-rules")
    (cached,) = parser_rules._CACHE.values()
    snapshot = copy.deepcopy(cached)
    defaults = site_defaults.load_or_exit(str(ROOT))
    for log in sorted((db / D / "fixtures").glob("*.log")):
        db_regress.parse_logs([log], db / "parser-rules", ROOT, defaults)
    assert len(parser_rules._CACHE) == 1 and cached == snapshot


def test_issue_records_and_feedback_do_not_change_all():
    before = run("db_regress.py", ["--db", copy_db(), "--all"])
    db = copy_db()
    edit(db / C / "issues/MOCK-2101.yaml", "cause: CALL-001-01", "cause: SIM-001-01")
    edit(db / C / "issues/MOCK-2101.yaml", "sw: MOCKB77_U2_20260910", "sw: OTHER_SW_1")
    for path in (db / D / "issues").glob("*.yaml"):
        path.unlink()
    shutil.rmtree(db / "feedback")
    after = run("db_regress.py", ["--db", db, "--all"])
    assert before.returncode == after.returncode == 0
    assert before.stdout == after.stdout


def _staged(repo) -> tuple[int, dict]:
    proc = run("db_regress.py", ["--db", repo, "--staged"])
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def test_staged_scope_skips_issue_record_only_types():
    repo = git_db()
    record = f"{C}/issues/MOCK-2101.yaml"
    edit(repo / record, "sw: MOCKB77_U2_20260910", "sw: OTHER_SW_1")
    git(repo, "add", "-A")
    code, out = _staged(repo)
    assert code == 0 and out["summary"]["total"] == 0 and out["summary"]["expanded"] is False
    assert out["summary"]["excluded"] == {"reason": "issues-only", "files": [record]}

    # 깨진 이슈 기록은 지금처럼 오류다 (DB 로드는 전체)
    (repo / record).write_text("key: [", encoding="utf-8")
    git(repo, "add", "-A")
    assert _staged(repo)[0] == 2
    git(repo, "checkout", "HEAD", "--", record)
    edit(repo / record, "sw: MOCKB77_U2_20260910", "sw: OTHER_SW_1")

    # 이슈 기록 + type.md → 기존 범위 (call과 related ims, 같은 카테고리). excluded에는 건너뛴 유형(data)의 기록만
    edit(repo / C / "type.md", "summary: ", "summary: (수정) ")
    other = f"{D}/issues/MOCK-1101.yaml"
    (repo / other).write_text((repo / other).read_text(encoding="utf-8") + "# 수정\n", encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    code, out = _staged(repo)
    assert code == 0 and {r["fixture"].split("/")[0] for r in out["results"]} == {"call", "ims"}
    assert out["summary"]["excluded"] == {"reason": "issues-only", "files": [other]}
    git(repo, "reset", "-q", "--", f"{C}/type.md", other)
    git(repo, "checkout", "--", f"{C}/type.md", other)
    edit(repo / C / "type.md", "summary: ", "summary: (수정) ")      # 기록이 범위에 든 유형뿐이면 키 없음
    git(repo, "add", "-A")
    assert "excluded" not in _staged(repo)[1]["summary"]
    git(repo, "reset", "-q", "--", f"{C}/type.md")
    git(repo, "checkout", "--", f"{C}/type.md")

    # 이슈 기록 + parser-rules → 전체 (확장 규칙이 먼저)
    edit(repo / "parser-rules/ril.yaml", "reason: 초기}", "reason: 초기 (수정)}")
    git(repo, "add", "-A")
    code, out = _staged(repo)
    assert out["summary"]["expanded"] is True and out["summary"]["total"] == 23 and "excluded" not in out["summary"]
    git(repo, "reset", "-q", "--hard", "HEAD")

    # fixture 기대값만 → 그 유형은 범위
    expect = next((repo / C / "fixtures").glob("*.expect.yaml"))
    expect.write_text(expect.read_text(encoding="utf-8") + "# 수정\n", encoding="utf-8", newline="\n")
    git(repo, "add", "-A")
    code, out = _staged(repo)
    assert "call" in {r["fixture"].split("/")[0] for r in out["results"]} and "excluded" not in out["summary"]


def _precommit_regress(monkeypatch, summary: dict) -> dict:
    import db_precommit
    from common import checks as checks_mod
    from types import SimpleNamespace

    repo = git_db()
    edit(repo / f"{C}/issues/MOCK-2101.yaml", "sw: MOCKB77_U2_20260910", "sw: OTHER_SW_1")
    git(repo, "add", "-A")
    step = checks_mod.StepResult("regress", 0, data={"summary": summary, "results": []})
    monkeypatch.setattr(checks_mod, "run_checks", lambda profile, ctx: SimpleNamespace(steps=[step]))
    result, code = db_precommit.run(repo, str(ROOT))
    assert code == 0
    (row,) = [c for c in result["checks"] if c["check"] == "regress"]
    return row


def test_precommit_notes_skipped_issue_record_types(monkeypatch):
    files = [f"t/T{i}/issues/K-{i}.yaml" for i in range(7)]
    row = _precommit_regress(monkeypatch, {"scope": "staged", "expanded": False, "total": 0, "passed": 0,
                                           "failed": 0, "excluded": {"reason": "issues-only", "files": files}})
    assert row["code"] == 0 and "회귀 대상 fixture 0개" in row["note"] and "issues-only" in row["note"]
    assert files[4] in row["note"] and files[5] not in row["note"] and row["note"].endswith("외 2개")

    row = _precommit_regress(monkeypatch, {"scope": "staged", "expanded": False, "total": 0, "passed": 0,
                                           "failed": 0})                      # 예: CONTRIBUTING.md만 바뀜
    assert row == {"check": "regress", "code": 0, "note": "회귀 대상 fixture 0개 (바뀐 유형 없음)"}

    row = _precommit_regress(monkeypatch, {"scope": "staged", "expanded": False, "total": 3, "passed": 3,
                                           "failed": 0})
    assert row == {"check": "regress", "code": 0}


def test_staged_files_list_both_rename_paths():
    repo = git_db()
    old = f"{D}/fixtures/DATA-001.none.log"
    git(repo, "mv", old, f"{D}/fixtures/DATA-001.none.9.log")
    assert {old, f"{D}/fixtures/DATA-001.none.9.log"} <= set(gitscope.staged_files(repo))
