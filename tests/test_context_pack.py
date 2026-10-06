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


def test_output_sections_bounded():
    out = cp.render("S-1")
    assert "===== docs/design/14-site.md §14.2 =====" in out
    assert "### 14.3" in out and "### 14.4" not in out and "### 14.1" not in out
    assert "## 런타임 값 변경 이력" in out          # 코드 펜스 안 `#`에서 끊기지 않는다
    assert out.startswith("===== docs/design/15-local-draft.md §15.5 S-1 =====") and "| S-1 |" in out
    assert "===== 비고 =====" in out


def test_empty_pack_says_so():
    assert "읽을 파일이 없다" in cp.render("S-5")


def test_unknown_pack_exit_2():
    r = subprocess.run([sys.executable, str(ROOT / "tools/context_pack.py"), "S-99"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert r.returncode == 2 and re.search("context_pack", r.stderr)
