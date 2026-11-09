"""tools/related_tests.py: 바뀐 파일에서 관련 테스트 선택 (빠름, --files와 --json만 쓴다)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "related_tests.py"


def select(*files: str) -> dict:
    proc = subprocess.run([sys.executable, str(TOOL), "--json", "--files", *files], capture_output=True,
                          text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_script_change_selects_its_test_only():
    out = select("plugin/scripts/db_pr.py")
    assert "tests/test_db_pr.py" in out["tests"] and "tests/test_safety.py" in out["tests"]
    assert "tests/test_parse_logcat.py" not in out["tests"]
    assert out["full"] is False and out["reasons"] == []


def test_common_module_is_full():
    out = select("plugin/scripts/common/masking.py")
    assert out["full"] is True and "공용 모듈" in out["reasons"][0]


def test_deleted_script_is_full():
    out = select("plugin/scripts/" + "no_such_" + "deleted.py")   # 삭제된 .py: KeyError 없이 full
    assert out["full"] is True and any("삭제된 스크립트" in r for r in out["reasons"])


def test_always_full_triggers():
    for path in ("tests/conftest.py", "tests/helpers/runner.py", "pyproject.toml", "plugin/schemas/x.json",
                 "plugin/scripts/platforms/__init__.py"):
        assert select(path)["full"] is True, path


def test_skill_md_includes_size_test():
    out = select("plugin/skills/telephony-triage/SKILL.md")
    assert "tests/test_triage.py" in out["tests"] and out["full"] is False


def test_docs_only_needs_no_tests():
    out = select("docs/history/" + "CHANGES" + ".md")  # 이 파일이 문서 이름을 직접 적으면 스스로 참조가 된다
    assert out["tests"] == [] and out["full"] is False


def test_unknown_path_is_full():
    out = select("no/such/" + "zz" + "qq.xyz")
    assert out["full"] is True and "분류할 수 없는" in out["reasons"][0]


def test_test_file_and_skill_evals():
    assert select("tests/test_db_pr.py")["tests"] == ["tests/test_db_pr.py"]
    assert select("tests/skill_evals/offsite.py")["tests"] == ["tests/test_skill_evals.py"]
    shown = ["tests/test_db_verify.py", "tests/test_show_guard.py", "tests/test_shown.py", "tests/test_skill_evals.py"]
    assert select("tests/skill_evals/shown_infer.py")["tests"] == shown           # 채점기 추론: 표시 판정 테스트도
    assert select("tests/helpers/shown_records.py") == {**select("tests/helpers/shown_records.py"), "full": False}
    assert select("tests/helpers/shown_records.py")["tests"] == shown


def test_module_templates_and_generator_select_module_tests():
    """모듈 스킬(계획 H C0): 템플릿·입력 생성기·기록은 모듈 테스트 둘(helpers 규칙의 full보다 먼저), run.py·grade.py는
    common.claude_child 재수출 테스트(test_module_eval)도 고른다."""
    module = {t for t in ("tests/test_module_eval.py", "tests/test_module_templates.py", "tests/test_make_module_repo.py",
                          "tests/test_boundary.py", "tests/test_make_excerpt.py", "tests/test_module_templates_android.py")
              if (REPO / t).is_file()}
    assert "tests/test_module_eval.py" in module
    for path in ("templates/module-skills/ofono/data/SKILL.md", "tests/helpers/make_module_eval_inputs.py",
                 "templates/module-skills/ofono/data/evals/data-apn-auth-reject/files/source.log",
                 "tests/skill_evals/module_offsite_results.json"):
        out = select(path)
        assert set(out["tests"]) == module and out["full"] is False, path
    assert "tests/test_module_eval.py" in select("tests/fixtures/module-arms/ofono/pre/explore-rules.md")["tests"]
    out = select("tools/make_excerpt.py")                                       # R39: 발췌 도구도 모듈 경로
    assert set(out["tests"]) == module and out["full"] is False
    for path in ("tests/skill_evals/run.py", "tests/skill_evals/grade.py"):
        out = select(path)
        assert set(out["tests"]) == {"tests/test_skill_evals.py", "tests/test_module_eval.py",
                                    "tests/test_claude_child.py"} and out["full"] is False


def test_claude_child_and_opencode_layer():
    """계획 I: common/claude_child.py는 full이 아니라 스크립트 규칙 + CHILD_HELPER_TESTS(test_claude_child 포함), run.py·grade.py도
    test_claude_child를 고른다. opencode/**·tests/opencode/**는 OpenCode 테스트 셋과 tests/opencode/ 디렉토리(분류 불가 full 아님)."""
    out = select("plugin/scripts/common/claude_child.py")
    assert out["full"] is False and {"tests/test_claude_child.py", "tests/test_module_eval.py", "tests/test_skill_evals.py",
                                     "tests/test_site_step_runtime.py"} <= set(out["tests"])
    assert "tests/test_claude_child.py" in select("tests/skill_evals/run.py")["tests"]
    assert select("plugin/scripts/common/masking.py")["full"] is True            # 다른 common은 그대로 full
    want = ["tests/opencode", "tests/test_gen_opencode.py", "tests/test_oc_adapter.py", "tests/test_tt_oc.py"]
    for path in ("opencode/bin/tt-oc", "opencode/plugins/tt-guard.js", "opencode/opencode.json.template",
                 "tests/opencode/test_oc_e2e.py", "tests/opencode/fakes/x.py"):
        out = select(path)
        assert out["full"] is False and out["tests"] == want, path
    out = select("plugin/scripts/common/oc_version.py")      # 바이너리 의존 한 곳(F②): common이지만 OpenCode 층
    assert out["full"] is False and set(want) <= set(out["tests"])


def test_tool_change_selects_tests_mentioning_it():
    assert "tests/test_boundary.py" in select("tools/check_boundary.py")["tests"]


def test_no_files_is_usage_error():
    proc = subprocess.run([sys.executable, str(TOOL), "--files"], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    assert proc.returncode == 2


def test_pycache_ignored():
    """R39: `__pycache__`·`.pyc`는 시험도 full도 고르지 않는다."""
    for path in ("plugin/scripts/common/__pycache__/masking.cpython-313.pyc", "tools/__pycache__/x.pyc", "x.pyc"):
        out = select(path)
        assert out["tests"] == [] and out["full"] is False, path


def test_templates_include_make_module_repo_and_boundary():
    out = select("templates/module-skills/ofono/sim/SKILL.md")
    assert {"tests/test_make_module_repo.py", "tests/test_boundary.py", "tests/test_make_excerpt.py"} <= set(out["tests"])
