#!/usr/bin/env python3
"""Phase 5 완료 기준 확인: 생성기 `db_build.py` (11-phases.md Phase 5).

- 샘플 README가 03-issue-db.md §5.6 구조, 6개 카테고리 모두
- 0건 카테고리: `issue-db-empty-category/`, `make_db_skeleton.py` 결과
- 두 번 실행하면 바이트 단위로 같음, `--preview`·`--cache-only`는 워킹 트리를 바꾸지 않음
- `--verify`(워킹 트리·`--staged`), `generator_version` 불일치
- 캐시 해시가 다르면 매처가 재컴파일
- STATS: `decision: manual` 제외, `occurred_on`이 오래된 Jira는 최근 30일·급증에 들어가지 않음

`pytest tests/test_db_build.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import runner  # noqa: E402
from runner import SAMPLE, copy_db, edit, git, git_db, run, run_json, tmp, variant_db  # noqa: E402

CATEGORIES = ["Data", "Call", "Network", "SIM", "SMS", "IMS"]
EMPTY = "아직 등록된 이슈가 없습니다."


def _preview(db: Path) -> Path:
    out = tmp("tt-preview-")
    run_json("db_build.py", ["--db", db, "--preview", out])
    return out


def _hashes(root: Path, names) -> dict:
    return {n: hashlib.sha256((root / n).read_bytes()).hexdigest() for n in names}


def test_readme_structure_matches_design():
    out = _preview(SAMPLE)
    text = (out / "README.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Telephony Issue DB"
    assert lines[2].startswith("> 자동 생성 파일입니다. 직접 수정하지 마세요. (`db_build.py`, generator v1)")
    assert lines[3].startswith("> 기준일: 2026-09-27 · schema v1 · [통계](STATS.md)")
    headings = [l for l in lines if l.startswith("## ")]
    assert headings == ["## 요약", "## 최근 추가 (9건)", *[f"## {c}" for c in CATEGORIES], "## 보관"]
    summary = lines[lines.index("## 요약") + 2: lines.index("## 요약") + 2 + 8]
    assert summary[0] == "| 카테고리 | 이슈 유형 | 원인 | Jira | 수정 필요(open) |"
    assert [row.split("|")[1].strip() for row in summary[2:]] == [f"[{c}](#{c.lower()})" for c in CATEGORIES]
    assert "| # | 원인 | 해결책 | 유형 | 수정 상태 | Jira |" in lines
    assert "### 1. [SETUP_DATA_CALL이 발생하지 않음](data/DATA-001-no-setup-data-call/type.md) `DATA-001`" in lines
    # 셀 표기 (§5.6): related, 미검증, 수정 상태, Jira 링크, 원인 미확정
    assert "| 1-1 | IMS 미등록 ↔ IMS-001-01 |" in text
    assert "데이터 로밍 설정을 켠다 ⚠ 미검증" in text
    assert "fixed ✅ MOCKB77_U2_20260920 검증" in text
    assert "fix-submitted ⏳ MOCKB77_U2:MOCKB77_U2_20260920" in text
    assert "2건: [MOCK-1102](https://jira.mock.invalid/browse/MOCK-1102), [MOCK-1101]" in text
    assert "원인 미확정: [MOCK-1104](https://jira.mock.invalid/browse/MOCK-1104)" in text
    assert "망 등록 거절 · CP 근거" in text
    for key in ("data", "call", "network", "sim", "sms", "ims"):
        cat = (out / key / "README.md").read_text(encoding="utf-8")
        assert "| # | 원인 | 해결책 | 유형 | 수정 상태 | Jira | Android | 코드 |" in cat
    data = (out / "data/README.md").read_text(encoding="utf-8")
    assert "- 증상 시그니처:" in data and "| 전 버전 |" in data and "`aosp:frameworks/" in data


def test_empty_categories_are_listed():
    out = _preview(variant_db("issue-db-empty-category"))
    text = (out / "README.md").read_text(encoding="utf-8")
    assert "| [SMS](#sms) | 0 | 0 | 0 | 0 |" in text and "| [IMS](#ims) | 0 | 0 | 0 | 0 |" in text
    for name in ("SMS", "IMS"):
        section = text.split(f"## {name}\n", 1)[1].split("\n## ", 1)[0]
        assert section.strip() == EMPTY
    assert (out / "sms/README.md").read_text(encoding="utf-8").rstrip().endswith(EMPTY)


def test_skeleton_shows_all_categories_empty():
    skeleton = tmp("tt-skeleton-") / "db"
    proc = subprocess.run([sys.executable, str(REPO / "tools/make_db_skeleton.py"), str(skeleton)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    out = _preview(skeleton)
    text = (out / "README.md").read_text(encoding="utf-8")
    assert text.count(EMPTY) == 6
    assert "> 기준일: - " in text and "아직 기록된 Jira가 없습니다." in text
    for key in ("data", "call", "network", "sim", "sms", "ims"):
        assert (out / key / "README.md").read_text(encoding="utf-8").rstrip().endswith(EMPTY)


def test_write_is_deterministic_and_verify():
    db = git_db()
    first = run_json("db_build.py", ["--db", db, "--write"])
    names = first["files"]
    assert set(names) >= {"README.md", "STATS.md", "parser-rules/CHANGELOG.md", "data/README.md"}
    snap = _hashes(db, names)
    second = run_json("db_build.py", ["--db", db, "--write"])
    assert second["changed"] == [] and _hashes(db, names) == snap
    assert _hashes(_preview(db), names) == snap  # preview도 같은 바이트
    for name in names:
        raw = (db / name).read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n"), name

    assert run("db_build.py", ["--db", db, "--verify"]).returncode == 0
    edit(db / "README.md", "# Telephony Issue DB", "# Telephony Issue DB (수정)")
    proc = run("db_build.py", ["--db", db, "--verify"])
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["problems"] == [{"path": "README.md", "status": "different"}]
    # --staged: index 기준. 생성 파일을 아직 add하지 않았으므로 index에는 없다(missing)
    staged = json.loads(run("db_build.py", ["--db", db, "--verify", "--staged"]).stdout)
    assert {"path": "README.md", "status": "missing"} in staged["problems"]
    run_json("db_build.py", ["--db", db, "--write"])
    git(db, "add", "-A")
    assert run("db_build.py", ["--db", db, "--verify", "--staged"]).returncode == 0


def test_preview_and_cache_only_leave_worktree_alone():
    db = git_db()
    before = git(db, "status", "--porcelain")
    _preview(db)
    result = run_json("db_build.py", ["--db", db, "--cache-only"])
    assert Path(result["cache"]).is_file()
    assert git(db, "status", "--porcelain") == before == ""  # .cache/는 .gitignore
    assert not (db / "README.md").exists()


def test_generator_version_mismatch():
    db = copy_db()
    edit(db / "issue-db.config.yaml", "generator_version: 1", "generator_version: 2")
    proc = run("db_build.py", ["--db", db, "--write"])
    assert proc.returncode == 2 and "generator_version" in proc.stderr
    assert not (db / "README.md").exists()


def _events_file() -> Path:
    doc = run_json("parse_logcat.py", ["parse", SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log",
                                       "--full", "--mask", "--rules", SAMPLE / "parser-rules", "--tz", "UTC"])
    path = tmp() / "events.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_matcher_uses_cache_and_recompiles_when_hash_differs():
    db = copy_db()
    events = _events_file()
    match = lambda: run_json("match_signatures.py", ["--db", db, "--events", events, "--regress", "--top", "0"])  # noqa: E731
    assert match()["cache"] == "none"
    run_json("db_build.py", ["--db", db, "--cache-only"])
    hit = match()
    assert hit["cache"] == "hit" and [c["cause"] for c in hit["causes"] if c["C"]] == ["DATA-001-01"]

    # 해시는 그대로 두고 캐시의 시그니처를 바꾸면 매처가 캐시를 쓴다는 것이 드러난다
    cache_path = db / ".cache/compiled.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["signatures"]["DATA-001-01"] = [{"id": "never", "must_match": ["NO_SUCH_TEXT"], "window_sec": 60}]
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    tampered = match()
    assert tampered["cache"] == "hit" and not any(c["C"] for c in tampered["causes"])

    # 소스가 바뀌면 해시가 달라져 캐시를 버리고 메모리에서 다시 컴파일한다
    edit(db / "data/DATA-001-no-setup-data-call/type.md", "title: Roaming disabled", "title: Roaming disabled (x)")
    fresh = match()
    assert fresh["cache"] == "miss" and [c["cause"] for c in fresh["causes"] if c["C"]] == ["DATA-001-01"]


def test_stats_excludes_manual_feedback():
    text = (_preview(SAMPLE) / "STATS.md").read_text(encoding="utf-8")
    quality = text.split("## 시그니처 품질", 1)[1].split("\n## ", 1)[0]
    assert "| `DATA-001-01/data-disabled` | 1 | 0 | 0.00 | 아니오 |" in quality
    assert "| `DATA-001-02/roaming-disabled` | 1 | 1 | 1.00 | 아니오 |" in quality
    assert "SIM-001" not in quality  # MOCK-4101은 decision: manual
    assert "| 2026-09 | 2 | 1 |" in text  # 기여 현황: 분석 2, 수동 기록 1


def test_stats_use_occurred_on_for_recent_counts():
    db = copy_db()
    jira_dir = db / "network/NETWORK-001-no-service/jira"
    for n in range(3):
        (jira_dir / f"MOCK-31{n + 10}.yaml").write_text(
            f"key: MOCK-31{n + 10}\ncause: NETWORK-001-01\ndate: 2026-09-27\noccurred_on: 2025-01-1{n}\n"
            "model: MOCK-A56\nsw: MOCKA56_U1_20260901\nandroid_version: \"16\"\nanalyzed_by: mock-user1\n",
            encoding="utf-8")
    text = (_preview(db) / "STATS.md").read_text(encoding="utf-8")
    assert "| NETWORK-001-01 | 망 등록 거절 | 4 | 1 | 1 |" in text  # 누적 4, 최근 30·90일 1
    surge = text.split("## 급증 원인", 1)[1].split("\n## ", 1)[0]
    assert "NETWORK-001-01" not in surge
    # 비교: 같은 기록을 최근 발생으로 넣으면 최근 건수와 급증에 들어간다
    for path in jira_dir.glob("MOCK-311*.yaml"):
        edit(path, "occurred_on: 2025-01-1", "occurred_on: 2026-09-2")
    text = (_preview(db) / "STATS.md").read_text(encoding="utf-8")
    assert "| NETWORK-001-01 | 망 등록 거절 | 4 | 4 | 4 |" in text
    assert "NETWORK-001-01" in text.split("## 급증 원인", 1)[1].split("\n## ", 1)[0]


def test_changelog_from_history_fields():
    text = (_preview(SAMPLE) / "parser-rules/CHANGELOG.md").read_text(encoding="utf-8")
    assert "| 날짜 | 파일 | 항목 | 추가 대상 | 사유 |" in text
    assert "| 2026-09-28 | extractors.yaml | `data-evaluation-rejected` | DATA-001 | 데이터 평가 거부 사유 추출 |" in text
    assert "| 2026-09-28 | ril.yaml `requests` | `SETUP_DATA_CALL` | DATA-001 | 초기 |" in text


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
