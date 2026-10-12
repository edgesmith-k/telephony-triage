"""tools/site_step.py: "사내 설정 시작" 진행기 — SITE_PROFILE.md 생성, 단계 순서, 건너뛰기 거부, 사외 PC 거부."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import context_pack as cp  # noqa: E402
import site_step as ss  # noqa: E402


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools/site_step.py"), "--root", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)


def test_steps_follow_15_5_table_without_s0():
    assert ss.STEPS == [p for p in ("S-1", "S-2", "S-3", "S-4a", "S-4", "S-5", "S-6", "S-7") if cp.step_row(p)]


def test_start_creates_profile_with_jira_and_prints_s1(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 0, r.stderr
    prof = (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8")
    assert "- 모드: 사내 보완" in prof and "- 현재 단계: S-1" in prof and "- 트래커: jira" in prof
    for head in ("## 진행 상태", "## 확인값", "## 설계 변경", "## 사외 문서와의 차이", "## 런타임 값 변경 이력"):
        assert head in prof                                    # 14-site.md §14.3 절
    assert len(prof.encode()) < 4096
    assert "새로 만들었다" in r.stdout and "지금 단계: S-1" in r.stdout and "--done S-1" in r.stdout
    assert "===== docs/design/15-local-draft.md §15.5 S-1 =====" in r.stdout
    again = run(tmp_path)                                      # 이어 하기: 다시 만들지 않는다
    assert again.returncode == 0 and "새로 만들었다" not in again.stdout and "지금 단계: S-1" in again.stdout


def test_done_advances_in_order_and_refuses_skips(tmp_path):
    run(tmp_path)
    bad = run(tmp_path, "--done", "S-2")
    assert bad.returncode == 2 and "현재 단계는 S-1" in bad.stderr
    for cur, nxt in zip(ss.STEPS, ss.STEPS[1:]):
        r = run(tmp_path, "--done", cur)
        assert r.returncode == 0, r.stderr
        assert f"지금 단계: {nxt}" in r.stdout and f"§15.5 {nxt} =====" in r.stdout
    last = run(tmp_path, "--done", "S-7")
    assert last.returncode == 0 and "모두 완료" in last.stdout
    prof = (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8")
    assert "- 현재 단계: 완료" in prof and all(f"{s} (" in prof for s in ss.STEPS)
    assert run(tmp_path, "--done", "S-7").returncode == 2


def test_done_keeps_other_sections(tmp_path):
    run(tmp_path)
    prof = tmp_path / "SITE_PROFILE.md"
    prof.write_text(prof.read_text(encoding="utf-8") + "- (10/13) 사내 메모\n", encoding="utf-8")
    run(tmp_path, "--done", "S-1")
    text = prof.read_text(encoding="utf-8")
    assert text.endswith("- (10/13) 사내 메모\n") and "- 완료 단계: S-1 (" in text


def test_external_draft_pc_refuses(tmp_path):
    (tmp_path / ".local-draft").touch()
    r = run(tmp_path)
    assert r.returncode == 2 and "사외 초안 PC" in r.stderr
    assert not (tmp_path / "SITE_PROFILE.md").exists()


def test_other_mode_or_missing_lines_refuse(tmp_path):
    prof = tmp_path / "SITE_PROFILE.md"
    prof.write_text("# SITE_PROFILE\n\n## 진행 상태\n- 모드: 사내 처음부터\n- 현재 Phase: 3\n", encoding="utf-8")
    r = run(tmp_path)
    assert r.returncode == 2 and "사내 처음부터" in r.stderr
    prof.write_text("# SITE_PROFILE\n\n## 진행 상태\n- 모드: 사내 보완\n", encoding="utf-8")
    r = run(tmp_path)
    assert r.returncode == 2 and "현재 단계" in r.stderr
