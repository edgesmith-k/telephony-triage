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
    assert select("tests/skill_evals/run.py")["tests"] == ["tests/test_skill_evals.py"]


def test_tool_change_selects_tests_mentioning_it():
    assert "tests/test_boundary.py" in select("tools/check_boundary.py")["tests"]


def test_no_files_is_usage_error():
    proc = subprocess.run([sys.executable, str(TOOL), "--files"], capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    assert proc.returncode == 2
