#!/usr/bin/env python3
"""`tools/import_draft.py` 재반입 시험 (11-phases.md Phase D0 완료 기준).

가짜 사내 레포에 **두 번** 반입해서 확인한다.
- `SITE_PATHS` 경로는 보존된다.
- 두 번째 반입에서 사외에서 지운 파일은 지워진다.
- 사내에서 새로 만든 비-`SITE_PATHS` 파일은 지워지지 않고 목록으로 보고된다.
- 첫 반입 이후 사내에서 고친 사외 파일이 있으면 목록을 보여주고 멈춘다.

`pytest tests/test_import_draft.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "import_draft.py"

SITE_PATHS_TEXT = """\
# 사내 전용 경로
SITE_PROFILE.md
.draft-manifest.json
docs/site/
plugin/site-defaults.yaml
plugin/scripts/parser_backends/site/
plugin/scripts/adapters/site_*
tests/golden/
tests/site/
"""


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(source: Path, dest: Path, *extra: str) -> tuple[int, dict | str]:
    result = subprocess.run(
        [sys.executable, str(TOOL), str(source), "--dest", str(dest), "--json", *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = result.stdout.strip()
    try:
        payload = json.loads(out) if out else result.stderr
    except ValueError:
        payload = out or result.stderr
    return result.returncode, payload


def _make_draft_v1(root: Path) -> None:
    _write(root, "SITE_PATHS", SITE_PATHS_TEXT)
    _write(root, "plugin/scripts/config.py", "# v1 config\n")
    _write(root, "plugin/scripts/parse_logcat.py", "# v1 parser\n")
    _write(root, "plugin/site-defaults.example.yaml", "schema: 1\n")
    _write(root, "tests/test_a.py", "# v1 test a\n")
    _write(root, "tests/test_removed_later.py", "# 사외에서 나중에 지울 파일\n")
    _write(root, ".local-draft", "")


def _make_draft_v2(root: Path) -> None:
    _make_draft_v1(root)
    (root / "tests/test_removed_later.py").unlink()
    _write(root, "plugin/scripts/parse_logcat.py", "# v2 parser (고침)\n")
    _write(root, "plugin/scripts/db_pr.py", "# v2 새 파일\n")


def _add_site_only_files(dest: Path) -> None:
    """사내에서만 만드는 파일들 (SITE_PATHS)."""
    _write(dest, "SITE_PROFILE.md", "# SITE_PROFILE (사내 전용)\n")
    _write(dest, "plugin/site-defaults.yaml", "schema: 1\nsynthetic_allowed: false\n")
    _write(dest, "plugin/scripts/parser_backends/site/__init__.py", "# 포팅한 파서\n")
    _write(dest, "plugin/scripts/adapters/site_data_existing.py", "# 사내 어댑터\n")
    _write(dest, "tests/golden/real.orig.json", "{}\n")
    _write(dest, "tests/site/test_real_logs.py", "# 실제 로그 테스트\n")
    _write(dest, "docs/site/evidence.md", "# 확인 근거\n")


def run_scenario(base: Path) -> dict:
    draft1 = base / "draft-v1"
    draft2 = base / "draft-v2"
    dest = base / "site-repo"
    draft1.mkdir(parents=True)
    draft2.mkdir(parents=True)
    dest.mkdir(parents=True)

    _make_draft_v1(draft1)
    _make_draft_v2(draft2)

    results: dict[str, object] = {}

    # 1) 첫 반입 — 기준선이 없으므로 전체를 복사한다.
    code, first = _run(draft1, dest, "--label", "draft-v1")
    assert code == 0, first
    assert first["first_import"] is True
    assert (dest / ".draft-manifest.json").is_file()
    assert (dest / "plugin/scripts/parse_logcat.py").read_text(encoding="utf-8") == "# v1 parser\n"
    # `.local-draft`는 원본에 있어도 가져오지 않는다.
    assert not (dest / ".local-draft").exists()
    results["first"] = first

    # 2) 사내에서만 만드는 파일들과, 사내에서 새로 만든 비-SITE_PATHS 파일
    _add_site_only_files(dest)
    _write(dest, "tests/test_site_extra.py", "# 사내에서 만든 일반 파일\n")

    # 3) 두 번째 반입
    code, second = _run(draft2, dest, "--label", "draft-v2")
    assert code == 0, second
    assert second["first_import"] is False

    # SITE_PATHS 경로 보존
    assert (dest / "SITE_PROFILE.md").is_file()
    assert (dest / "plugin/site-defaults.yaml").is_file()
    assert (dest / "plugin/scripts/parser_backends/site/__init__.py").is_file()
    assert (dest / "plugin/scripts/adapters/site_data_existing.py").is_file()
    assert (dest / "tests/golden/real.orig.json").is_file()
    assert (dest / "tests/site/test_real_logs.py").is_file()
    assert (dest / "docs/site/evidence.md").is_file()

    # 사외에서 지운 파일은 지워진다
    assert not (dest / "tests/test_removed_later.py").exists()
    assert "tests/test_removed_later.py" in second["to_delete"]

    # 사외에서 고친 파일은 덮어써진다, 새 파일은 들어온다
    assert (dest / "plugin/scripts/parse_logcat.py").read_text(encoding="utf-8") == "# v2 parser (고침)\n"
    assert (dest / "plugin/scripts/db_pr.py").is_file()

    # 사내에서 새로 만든 비-SITE_PATHS 파일은 지우지 않고 보고한다
    assert (dest / "tests/test_site_extra.py").is_file()
    assert "tests/test_site_extra.py" in second["kept_new_in_site"]
    results["second"] = second

    # 4) 사내에서 사외 파일을 고친 뒤 다시 반입하면 멈춘다
    _write(dest, "plugin/scripts/config.py", "# 사내에서 고침\n")
    code, stopped = _run(draft2, dest)
    assert code == 1, stopped
    assert stopped["reason"] == "locally-modified"
    assert [item["path"] for item in stopped["locally_modified"]] == ["plugin/scripts/config.py"]
    # 멈췄으므로 아무것도 바뀌지 않았다
    assert (dest / "plugin/scripts/config.py").read_text(encoding="utf-8") == "# 사내에서 고침\n"
    results["stopped"] = stopped

    return results


def test_import_draft_twice():
    with tempfile.TemporaryDirectory(prefix="tt-import-") as tmp:
        run_scenario(Path(tmp))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="tt-import-") as tmp:
        out = run_scenario(Path(tmp))
    print("첫 반입:", out["first"]["first_import"], "덮어씀", len(out["first"]["to_write"]))
    print("두 번째 반입: 지움", out["second"]["to_delete"])
    print("  사내 새 파일 유지:", out["second"]["kept_new_in_site"])
    print("  SITE_PATHS 보존:", len(out["second"]["kept_site_paths"]), "개")
    print("세 번째(사내 수정 후):", out["stopped"]["reason"],
          [i["path"] for i in out["stopped"]["locally_modified"]])
    print("import_draft 재반입 시험 통과")
