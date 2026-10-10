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
        assert cp.step_row(p), p  # §15.5에 그 단계 행이 있다
        cp.render(p)  # 파일·절이 없으면 예외


def test_packs_match_steps_table():
    """tasks.md의 pack과 §15.5의 단계가 같다 (두 표 drift 방지)."""
    steps = cp.section((ROOT / cp.STEPS).read_text(encoding="utf-8"), "15.5")
    names = [c.strip("*").split()[0] for c in (cp._cells(ln)[0] for ln in steps.splitlines()
             if ln.startswith("| ") and not ln.startswith("| 단계")) if c.strip("*").startswith("S-")]
    assert names == PACKS


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


def test_s0_pack_is_small():
    """R-28: S-0 pack에 contracts.md §3.2 전체(약 57KB)를 싣지 않는다."""
    out = cp.render("S-0")
    assert len(out.encode()) < 30_000 and "===== docs/design/contracts.md" not in out


def test_s2_pack_has_s1_baseline():
    """R-25: S-2 pack에 사외 S1 실험 표(probe README)가 들어 있다."""
    out = cp.render("S-2")
    assert "===== tests/mocks/plugin-probe/README.md =====" in out
    assert "Bash 도구 프로세스에는 환경 변수 `CLAUDE_PLUGIN_ROOT`가 없다" in out


def test_row_filter_keeps_header_and_one_row():
    out = cp.render("S-7")
    head = "===== docs/design/14-site.md §14.2:S2 ====="
    assert head in out
    sec = out.split(head, 1)[1].split("\n=====", 1)[0]
    assert "| S2 |" in sec and "| S1 |" not in sec and "| S3 |" not in sec
    assert "| # | 항목 |" in sec                      # 표 머리는 남는다
    assert len(sec.encode()) < 1024


def test_row_filter_unknown_row_raises():
    body = cp.section((ROOT / "docs/design/14-site.md").read_text(encoding="utf-8"), "14.2")
    try:
        cp.filter_rows(body, "S99")
    except LookupError:
        return
    raise AssertionError("LookupError 기대")


def test_s1_s2_packs_exclude_external_only_sections():
    for p in ("S-1", "S-2"):
        out = cp.render(p)
        assert "새 세션 시작" not in out and "☐ Z" not in out and "사외 초안 모드로 진행해" not in out, p
        assert "## 결정" in out and "## 사내로 넘긴 것" in out and "## 진행 상태" in out, p


def test_site_profile_warning(tmp_path):
    assert cp.site_profile_warning(tmp_path) is None            # 사외: 파일 없음
    f = tmp_path / "SITE_PROFILE.md"
    f.write_bytes(b"x" * 4096)
    assert cp.site_profile_warning(tmp_path) is None
    f.write_bytes(b"x" * 4097)
    w = cp.site_profile_warning(tmp_path)
    assert w and "4097" in w and "14.3" in w
