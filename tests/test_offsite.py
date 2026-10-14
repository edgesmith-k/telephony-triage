"""tests/skill_evals/offsite.py: 사외 eval 결과 기록(offsite_results.json) 생성 — 합성 iteration, API 없음."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "skill_evals"))
import grade  # noqa: E402
import offsite  # noqa: E402

TRACKER = grade.JIRA_NO_WRITE_TEXT


def evals_dir(tmp_path) -> Path:
    d = tmp_path / "evals"
    d.mkdir()
    (d / "evals.json").write_text(json.dumps({"evals": [{"id": i, "name": f"e{i}", "batch": b}
                                                        for i, b in ((1, 1), (2, "B"), (3, "B"), (4, "A"), (8, "A"))]}),
                                  encoding="utf-8")
    (d / "pending.json").write_text(json.dumps({"site": {"4": "사내", "8": "사내"}, "manual": []}), encoding="utf-8")
    return d


def run(it: Path, eid: int, rows=None, model="m-x", commit="c1", mtime=1_800_000_000, status="completed",
        cost=0.25, name=None) -> None:
    d = it / (f"eval-{eid}-{name}" if name else f"eval-{eid}") / "with_skill"
    d.mkdir(parents=True)
    ex = d / "execution.json"
    ex.write_text(json.dumps({"status": status, "init_model": model, "repo_commit": commit, "total_cost_usd": cost,
                              "usage": {"secret": "x"}}), encoding="utf-8")
    if rows is not None:
        (d / "grading.json").write_text(json.dumps({"status": "graded", "expectations": [
            {"text": t, "passed": p, "evidence": "/home/someone/transcript"} for t, p in rows]}), encoding="utf-8")
    (d / "events.jsonl").write_text('{"transcript": "원문"}\n', encoding="utf-8")
    os.utime(ex, (mtime, mtime))


def main(d: Path, out: Path, *its: Path) -> int:
    return offsite.main([*map(str, its), "--out", str(out), "--evals-dir", str(d), "--note", "잠정"])


def test_builds_record_with_latest_commit_worst_verdict(tmp_path, capsys):
    d = evals_dir(tmp_path)
    a, b, c = tmp_path / "it-a", tmp_path / "it-b", tmp_path / "it-c"
    run(a, 1, [("x", True)], commit="c1", mtime=1_800_000_000, name="e1")
    run(b, 1, [("x", True)], commit="c2", mtime=1_800_000_100)
    run(c, 1, [("x", False)], commit="c2", mtime=1_800_000_050)       # 같은 최신 커밋의 반복 실행: 하나라도 실패면 fail
    run(a, 2, [("x", True), ("수동", None), (grade.TOKEN_BUDGET_TEXT, None)])
    run(b, 2, [("x", True)], status="prepared")                        # 준비만 한 run은 없는 것
    run(a, 8, [("x", True), (TRACKER, False)], cost=0.123456)
    run(b, 4, None, status="limit")                                    # 실행이 끝나지 않음 → undecided
    out = tmp_path / "out" / "offsite_results.json"
    assert main(d, out, a, b, c) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["model"] == "m-x" and data["note"] == "잠정" and data["generated"] and "grader_commit" in data
    e = data["evals"]
    assert e["1"]["verdict"] == "fail" and [r["iteration"] for r in e["1"]["runs"]] == ["it-a", "it-c", "it-b"]
    assert e["2"]["verdict"] == "undecided" and e["2"]["runs"][0]["undecided"] == 1 and len(e["2"]["runs"]) == 1
    assert e["8"]["verdict"] == "fail" and e["8"]["runs"][0]["safety_fail"] == 1 and e["8"]["runs"][0]["cost_usd"] == 0.1235
    assert e["4"]["verdict"] == "undecided" and e["4"]["runs"][0]["status"] == "limit"
    assert e["3"] == {"verdict": "none", "runs": []}
    run0 = e["1"]["runs"][0]
    assert set(run0) == {"iteration", "date", "repo_commit", "init_model", "status", "passed", "failed", "undecided",
                         "safety_fail", "cost_usd"} and run0["date"] == "2027-01-15"
    text = out.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and "/home/" not in text and "원문" not in text and "secret" not in text
    err = capsys.readouterr().err
    assert "68" not in err and "verdict none): 3" in err                   # site(4·8) 아닌 eval만 경고
    assert [p.name for p in out.parent.iterdir()] == ["offsite_results.json"]   # 임시 파일 없음(원자적 쓰기)


def test_pass_verdict_and_mixed_model_refused(tmp_path):
    d = evals_dir(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    run(a, 3, [("x", True), (grade.TOKEN_BUDGET_TEXT, None)])
    out = tmp_path / "o.json"
    assert main(d, out, a) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["evals"]["3"]["verdict"] == "pass"
    run(b, 1, [("x", True)], model="m-y")
    before = out.read_text(encoding="utf-8")
    assert main(d, out, a, b) == 2 and out.read_text(encoding="utf-8") == before   # 모델이 섞이면 쓰지 않는다
    assert main(d, out, tmp_path / "missing") == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(d, out, empty) == 2                                   # run이 하나도 없으면 사용 오류
