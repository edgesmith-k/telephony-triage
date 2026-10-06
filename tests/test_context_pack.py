"""tools/context_pack.py: tasks.md의 모든 참조가 풀리는지, 출력 형식, 오류 종료."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import context_pack as cp  # noqa: E402

PACKS = ["S-0", "S-1", "S-2", "S-3", "S-4a", "S-4", "S-5", "S-6", "S-7"]


def test_every_pack_resolves():
    for p in PACKS:
        cp.render(p)  # 파일·절이 없으면 예외


def test_whole_file_and_multi_section_forms_present():
    items = [i for p in PACKS for i in cp.pack_items(p)]
    assert any(not s for _, s in items) and any(len(s) > 1 for _, s in items)


def test_output_sections_bounded():
    out = cp.render("S-1")
    assert "===== docs/design/14-site.md §14.2 =====" in out
    assert "### 14.3" in out and "### 14.4" not in out and "### 14.1" not in out


def test_unknown_pack_exit_2():
    r = subprocess.run([sys.executable, str(ROOT / "tools/context_pack.py"), "S-99"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 2 and re.search("context_pack", r.stderr)
