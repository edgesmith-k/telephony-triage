#!/usr/bin/env python3
"""Phase 5 완료 기준 확인: 린터 `db_lint.py` (11-phases.md Phase 5).

`tests/fixtures/issue-db-lint-errors/`(`tests/helpers/make_variant_dbs.py`가 샘플에서 만든다)에 일부러
넣은 오류를 모두 잡고, 샘플의 `.resolved.1.log`·`.extra.1.log`·다른 유형 원인을 담은 `also_allowed`는
통과시키는지 본다. 범위 모드(`--changed`·`--staged`·`--ref`), `--residual`, 새 원인 fixed 금지,
`synthetic_allowed: false`도 확인한다.

`pytest tests/test_db_lint.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import make_variant_dbs  # noqa: E402
from runner import SAMPLE, edit, git, git_db, plugin_root, run, run_json  # noqa: E402

LINT_DB = REPO / "tests" / "fixtures" / "issue-db-lint-errors"
D = "data/DATA-001-no-setup-data-call"
C = "call/CALL-001-volte-not-working"
N = "network/NETWORK-001-no-service"

# (코드, 파일) — 11-phases.md Phase 5 완료 기준의 오류 목록 순서
EXPECTED = [
    ("duplicate-id", "sms/SMS-001-sms-send-failed/type.md"),               # ID 중복
    ("duplicate-jira", f"{C}/jira/MOCK-1101.yaml"),                         # Jira 중복
    ("glossary", f"{C}/type.md"),                                           # 금지 동의어 (경고)
    ("related", f"{N}/type.md"),                                            # 없는 related
    ("code-ref", f"{D}/type.md"),                                           # 절대 경로 code_refs
    ("id-prefix", "network/NET-002-bad-prefix/type.md"),                    # 잘못된 id_prefix
    ("fixture-name", f"{D}/fixtures/DATA-001-01.resolved.log"),             # 규칙 밖 이름
    ("fixture-name", f"{D}/fixtures/DATA-001-02.1.log"),                    # 양성 .1
    ("raw-identifier", "sim/SIM-001-sim-not-detected/type.md"),             # 시그니처의 원본 IMSI 패턴
    ("raw-identifier", "parser-rules/extractors.yaml"),                     # extractor의 원본 식별자 패턴
    ("signatures-missing", "sms/SMS-001-sms-send-failed/type.md"),          # pending 표시 없이 빈 시그니처
    ("pending-on-type", "ims/IMS-001-ims-registration-failed/type.md"),     # 유형에 붙은 signatures_pending
    ("symptom-missing", "sim/SIM-002-no-symptom/type.md"),                  # 빈 symptom_signatures
    ("verified-without-evidence", f"{D}/type.md"),                          # evidence 없는 verified
    ("fix-ref", "sim/SIM-001-sim-not-detected/type.md"),                    # fix_ref_regex
    ("builtin-event", f"{D}/type.md"),                                      # builtin_events()에 없는 builtin.*
    ("ext-event", f"{C}/type.md"),                                          # external_parsers에 없는 ext.*
    ("fixed-token", f"{N}/type.md"),                                        # 특정 마스킹 번호 고정 (경고)
    ("regex-unsafe", "ims/IMS-001-ims-registration-failed/type.md"),        # 중첩 수량자
    ("sequence", f"{C}/type.md"),                                           # sequence 없는 id·중복·must_not_match
    ("raw-identifier", f"{N}/jira/MOCK-3101.yaml"),                         # note의 원본 전화번호
    ("raw-identifier", f"{N}/type.md"),                                     # cp_evidence의 원본 전화번호
    ("also-allowed", f"{D}/fixtures/DATA-001-01.expect.yaml"),              # 자기·같은 유형·없는 ID
    ("evidence-missing", f"{C}/type.md"),                                   # 없는 fixture 경로·Jira 키
]


def _lint(db, *extra, expect=(0, 1), **kw) -> dict:
    return run_json("db_lint.py", ["--db", db, *extra], expect=expect, **kw)


def _pairs(result) -> set[tuple[str, str]]:
    return {(f["code"], f["file"]) for f in result["errors"] + result["warnings"]}


def test_variant_trees_match_builder():
    result = make_variant_dbs.run(check=True)
    assert not any(result.values()), result


def test_sample_db_is_clean():
    result = _lint(SAMPLE, "--all", expect=0)
    assert result["errors"] == [] and result["warnings"] == []
    # 규칙 안의 이름과 다른 유형 원인을 담은 also_allowed가 샘플에 실제로 있다
    names = {p.name for p in SAMPLE.glob("*/*/fixtures/*")}
    assert {"CALL-001-01.resolved.1.log", "DATA-001-02.extra.1.log", "CALL-001-01.expect.yaml"} <= names
    import yaml

    expect = yaml.safe_load((SAMPLE / C / "fixtures/CALL-001-01.expect.yaml").read_text(encoding="utf-8"))
    assert expect["also_allowed"] == ["IMS-001-01"]


def test_injected_errors_are_all_caught():
    result = _lint(LINT_DB, "--all", expect=1)
    found = _pairs(result)
    missing = [pair for pair in EXPECTED if pair not in found]
    assert not missing, f"잡지 못한 오류: {missing}"
    messages = " ".join(f["message"] for f in result["errors"] if f["code"] == "sequence")
    assert "조건에 없습니다" in messages and "겹칩니다" in messages and "must_not_match" in messages
    also = [f["message"] for f in result["errors"] if f["code"] == "also-allowed"]
    assert len(also) == 3
    evidence = [f["message"] for f in result["errors"] if f["code"] == "evidence-missing"]
    assert any("resolved.9.log" in m for m in evidence) and any("MOCK-9999" in m for m in evidence)
    levels = {f["code"]: f["level"] for f in result["errors"] + result["warnings"]}
    assert levels["glossary"] == "warning" and levels["fixed-token"] == "warning"


def test_residual_ids():
    result = _lint(SAMPLE, "--all", "--residual", "DATA-001-02=DATA-001-09", expect=1)
    files = {f["file"] for f in result["errors"] if f["code"] == "residual-id"}
    assert {f"{D}/type.md", f"{D}/jira/MOCK-1103.yaml", f"{D}/fixtures/DATA-001-02.log"} <= files
    assert _lint(SAMPLE, "--all", "--residual", "DATA-001-77=DATA-001-78", expect=0)["errors"] == []


def test_synthetic_fixtures_warn_when_not_allowed():
    root = plugin_root("no-synthetic", synthetic_allowed=False)
    result = _lint(SAMPLE, "--all", expect=0, root=root)
    synthetic = [f for f in result["warnings"] if f["code"] == "synthetic"]
    assert synthetic and all(f["file"].endswith(".expect.yaml") for f in synthetic)
    assert not [f for f in _lint(SAMPLE, "--all", expect=0)["warnings"] if f["code"] == "synthetic"]


def test_changed_and_staged_scope():
    repo = git_db()
    note = repo / N / "jira/MOCK-3101.yaml"
    edit(note, "note: 등록 거절 코드 13 반복", "note: 고객 010-1234-5678 등록 거절 코드 13 반복")
    changed = _lint(repo, "--changed", "main", expect=1)
    assert _pairs(changed) == {("raw-identifier", f"{N}/jira/MOCK-3101.yaml")}
    assert _lint(repo, "--staged", expect=0)["errors"] == []  # 아직 index에 없다
    git(repo, "add", "-A")
    assert _pairs(_lint(repo, "--staged", expect=1)) == {("raw-identifier", f"{N}/jira/MOCK-3101.yaml")}
    edit(note, "고객 010-1234-5678 ", "")  # 워킹 트리만 고쳐도 index 기준이라 여전히 걸린다
    assert _lint(repo, "--staged", expect=1)["errors"]
    assert _lint(repo, "--ref", "HEAD", expect=0)["errors"] == []


NEW_FIXED_CAUSE = """  - id: DATA-001-04
    status: active
    title: 새 원인
    description: 새 원인
    signatures:
      - id: probe
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*CONGESTED.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 확인한다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix:
      status: fixed
      ref: MOCKCL-11111
      fixed_in: [{branch: MOCKA56_U1, build: MOCKA56_U1_20260920}]
      verification: {result: passed, build: MOCKA56_U1_20260920, date: 2026-09-28, by: mock-user1}
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: [data-evaluation]"""


def test_new_cause_cannot_start_fixed():
    repo = git_db()
    edit(repo / D / "type.md", "tags: [data-evaluation]", NEW_FIXED_CAUSE)
    changed = _lint(repo, "--changed", "main", expect=1)
    assert ("new-cause-fixed", f"{D}/type.md") in _pairs(changed)
    # base ref가 없는 검사(--all)는 예외다 (03-issue-db.md §5.9)
    assert ("new-cause-fixed", f"{D}/type.md") not in _pairs(_lint(repo, "--all"))
    # 이미 main에 있는 fixed 원인(CALL-001-01)은 걸리지 않는다
    assert not [f for f in changed["errors"] if f["code"] == "new-cause-fixed" and "CALL" in f["message"]]


def test_regex_safety_heuristics():
    import db_lint

    # (ab|ac)*처럼 파서가 공통 접두어를 묶는 선택지는 실제로 안전해서 넣지 않는다.
    # (\d|\w)+처럼 서로 다른 문자 집합이 겹치는 선택지는 이 정적 검사가 잡지 못한다(한계,
    # 실행 시간 상한이 대신 막는다 — DRAFT_NOTES Phase 5 세부).
    unsafe = [r"(a+)+b", r"(a|a)*", r"(\w+)\1", r"(?P<x>a)(?P=x)", r"(\d+\s?)+$", r"(\s|\s)+$"]
    safe = [r"evaluation result:\s*NOT_ALLOWED\s+reasons=\[(?P<reasons>[^\]]*)\]", r"(?:\s+reason=(?P<r>\S+))?",
            r".*DATA_DISABLED.*", r"(foo|bar)*x", r"RILJ.*>\s*SETUP_DATA_CALL", r"cellId=<CELL#\d+>"]
    assert [p for p in unsafe if not db_lint.unsafe_regex(p)] == []
    assert [p for p in safe if db_lint.unsafe_regex(p)] == []
    raw = [r"imsi=\d{15}", r"[0-9]{15}", r"450081234567890", r"010-\d{4}-\d{4}", r"ip=10\.1\.2\.3", r"\+82"]
    fine = [r"cause=(?P<cause>\d+)", r"cellId=<CELL#\d+>", r"code=403", r"serial=\d{4}"]
    assert [p for p in raw if not db_lint.raw_identifier_in_pattern(p)] == []
    assert [p for p in fine if db_lint.raw_identifier_in_pattern(p)] == []


def test_skeleton_is_clean():
    import subprocess

    from runner import tmp

    skeleton = tmp("tt-skeleton-") / "db"
    subprocess.run([sys.executable, str(REPO / "tools/make_db_skeleton.py"), str(skeleton)], check=True,
                   capture_output=True)
    assert _lint(skeleton, "--all", expect=0)["errors"] == []


def _all_tests():
    return [(n, o) for n, o in sorted(globals().items()) if n.startswith("test_") and callable(o)]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
