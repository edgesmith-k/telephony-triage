"""실행되지 않은 평가를 통과로 세지 않고 API 중단을 보존한다."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "skill_evals"))
import grade as grader  # noqa: E402

spec = importlib.util.spec_from_file_location("skill_eval_run", REPO / "tests" / "skill_evals" / "run.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def run_dir(tmp_path):
    run = tmp_path / "with_skill"
    (run / "outputs").mkdir(parents=True)
    return run


def test_empty_output_directory_is_not_a_success(tmp_path):
    run = run_dir(tmp_path)
    result = grader.grade(24, run, tmp_path / "nonexistent-env", ["기록하지 않고 끝냄"])
    assert result["status"] == "not-run"
    assert result["summary"]["passed"] == 0
    assert result["summary"]["undecided"] == result["summary"]["total"]
    assert all(row["passed"] is None for row in result["expectations"])


@pytest.mark.parametrize("has_artifacts", [True, False])
def test_api_failure_is_incomplete_even_with_output_artifacts(tmp_path, has_artifacts):
    run = run_dir(tmp_path)
    if has_artifacts:
        for name in ("transcript.md", "commands.md"):
            (run / "outputs" / name).write_text("일부 실행 기록", encoding="utf-8")
    (run / "execution.json").write_text(json.dumps({"status": "blocked", "reason": "HTTP 429"}), encoding="utf-8")
    result = grader.grade(24, run, tmp_path / "nonexistent-env", ["lock 해제"])
    assert result["status"] == "incomplete"
    assert result["expectations"][0]["evidence"] == "HTTP 429"
    assert result["summary"]["passed"] == 0


def test_machine_grades_refresh_but_manual_grades_are_preserved(tmp_path, monkeypatch):
    run = run_dir(tmp_path)
    for name in ("transcript.md", "commands.md"):
        (run / "outputs" / name).write_text("실행 기록", encoding="utf-8")
    (run / "grading.json").write_text(json.dumps({"expectations": [
        {"text": "기계", "passed": True, "source": "script", "evidence": "옛 결과"},
        {"text": "대화", "passed": True, "source": "manual", "evidence": "독립 평가"},
        {"text": "새 수동 항목", "passed": True, "source": "script", "evidence": "폐기할 옛 기계 판정"},
    ]}), encoding="utf-8")
    class FakeContext:
        def __init__(self, *_):
            pass
        def jira_writes(self):
            return True, "쓰기 없음"
    monkeypatch.setattr(grader, "Ctx", FakeContext)
    monkeypatch.setattr(grader, "checks", lambda *_: [lambda: (False, "새 상태 실패"), None, None])
    result = grader.grade(1, run, tmp_path, ["기계", "대화", "새 수동 항목"])
    assert result["expectations"][0]["passed"] is False
    assert result["expectations"][1]["passed"] is True
    assert result["expectations"][1]["evidence"] == "독립 평가"
    assert result["expectations"][2]["passed"] is None
    assert result["expectations"][2]["source"] == "manual"


def test_weekly_limit_stops_batch_without_claiming_completion():
    status, reason = evaluation.classify_result({"is_error": True, "api_error_status": 429,
                                                "result": "weekly limit"}, 1)
    assert status == "blocked"
    assert reason == "weekly limit"


def test_evaluator_prompt_does_not_leak_expected_answers(tmp_path):
    entry = {"prompt": "로그 분석해줘", "user_replies": ["취소"],
             "assertions": ["SECRET_EXPECTATION"], "expected_output": "SECRET_ANSWER"}
    prompt = evaluation.evaluation_prompt(entry, {"skill": "isolated/skill"}, tmp_path, tmp_path)
    assert "SECRET_EXPECTATION" not in prompt and "SECRET_ANSWER" not in prompt
    assert "로그 분석해줘" in prompt and "취소" in prompt


# -- 정의 정합성 (실행 없이) ---------------------------------------------------------------------

EVALS = REPO / "tests" / "skill_evals"
sys.path.insert(0, str(REPO / "tests" / "helpers"))


def _entries() -> list[dict]:
    return json.loads((EVALS / "evals.json").read_text(encoding="utf-8"))["evals"]


def test_eval_ids_are_unique_and_consecutive():
    ids = [e["id"] for e in _entries()]
    assert ids == list(range(1, len(ids) + 1)), ids


def test_every_eval_has_required_keys_and_assertions():
    for e in _entries():
        for key in ("id", "name", "prompt", "setup", "user_replies", "expected_output", "assertions"):
            assert e.get(key), (e["id"], key)
        assert all(isinstance(a, str) and a for a in e["assertions"]), e["id"]


def test_eval_setup_references_resolve():
    import make_variant_dbs
    import skill_eval_env
    from runner import fixture_path

    dbs = {"issue-db-sample", *make_variant_dbs.VARIANTS}
    for e in _entries():
        setup = e["setup"]
        assert setup.get("db", "issue-db-sample") in dbs, (e["id"], setup.get("db"))
        for key in setup.get("jira") or []:
            assert skill_eval_env._find_jira(key).is_file(), (e["id"], key)
        for item in setup.get("logs") or []:
            if "src" in item:
                assert fixture_path(item["src"]).is_file(), (e["id"], item["src"])
            else:
                assert (EVALS / "scenarios" / item["scenario"]).is_file(), (e["id"], item["scenario"])
        for inj in setup.get("inject_main") or []:
            assert (EVALS / "scenarios" / inj["scenario"]).is_file(), (e["id"], inj["scenario"])


def test_split_buffers_setup_writes_one_file_per_buffer(tmp_path):
    import skill_eval_env

    entry = next(e for e in _entries() if e["id"] == 50)
    env = skill_eval_env.build(entry, tmp_path / "env")
    assert env is not None
    logs = sorted(p.name for p in (tmp_path / "env" / "logs").iterdir())
    assert logs == ["e050.main.log", "e050.radio.log"], logs
