"""tools/site_step.py: "사내 설정 시작" 진행기 — SITE_PROFILE.md 생성, 단계 순서, 건너뛰기 거부, 사외 PC 거부."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import context_pack as cp  # noqa: E402
import site_step as ss  # noqa: E402


def stub_path(root: Path) -> str:
    """gh·claude PATH 스텁(네트워크·API 없음). claude가 불리면 표식 파일을 남긴다."""
    bin_ = root.parent / f"{root.name}-bin"
    bin_.mkdir(exist_ok=True)
    (bin_ / "gh").write_text("#!/bin/sh\necho 'not logged in' >&2\nexit 1\n", encoding="utf-8")
    (bin_ / "claude").write_text(f"#!/bin/sh\necho \"$@\" >> '{bin_ / 'claude-called'}'\necho '9.9.9 (Claude Code)'\n",
                                 encoding="utf-8")
    for f in ("gh", "claude"):
        (bin_ / f).chmod(0o755)
    return f"{bin_}{os.pathsep}{os.environ['PATH']}"


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / "tools/site_step.py"), "--root", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL,
                          env=dict(os.environ, PATH=stub_path(root)))


def all_pass(monkeypatch):
    """단계 순서·기록만 보는 테스트: 점검을 모두 통과로 바꾼다(점검 자체는 test_site_checks.py)."""
    monkeypatch.setattr(ss.sc, "CHECKS", {s: [lambda ctx, s=s: ss.sc.res(f"{s}.ok", "pass", "합성")] for s in ss.STEPS})


def main(root: Path, capsys, *args: str) -> tuple[int, str, str]:
    code = ss.main(["--root", str(root), *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_steps_follow_15_5_table_without_s0():
    assert ss.STEPS == [p for p in ("S-1", "S-2", "S-3", "S-4a", "S-4", "S-5", "S-6", "S-7") if cp.step_row(p)]


def test_start_creates_profile_with_jira_and_prints_s1(tmp_path):
    r = run(tmp_path)
    assert r.returncode == 1, r.stderr      # 출력은 낸다. 종료 코드는 점검 결과(게이트 줄·샘플 없음 = 사용자 필요)
    prof = (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8")
    assert "- 모드: 사내 보완" in prof and "- 현재 단계: S-1" in prof and "- 트래커: jira" in prof
    for head in ("## 진행 상태", "## 확인값", "## 설계 변경", "## 사외 문서와의 차이", "## 런타임 값 변경 이력"):
        assert head in prof                                    # 14-site.md §14.3 절
    assert len(prof.encode()) < 4096
    assert "새로 만들었다" in r.stdout and "지금 단계: S-1" in r.stdout and "--done S-1" in r.stdout
    assert "===== docs/design/15-local-draft.md §15.5 S-1 =====" in r.stdout
    again = run(tmp_path)                                      # 이어 하기: 다시 만들지 않는다
    assert again.returncode == 1 and "새로 만들었다" not in again.stdout and "지금 단계: S-1" in again.stdout


def test_done_advances_in_order_and_refuses_skips(tmp_path, monkeypatch, capsys):
    all_pass(monkeypatch)
    main(tmp_path, capsys)
    code, _, err = main(tmp_path, capsys, "--done", "S-2")
    assert code == 2 and "현재 단계는 S-1" in err
    for cur, nxt in zip(ss.STEPS, ss.STEPS[1:]):
        code, out, err = main(tmp_path, capsys, "--done", cur)
        assert code == 0, err
        assert f"지금 단계: {nxt}" in out and f"§15.5 {nxt}" in out
    code, out, _ = main(tmp_path, capsys, "--done", "S-7")
    assert code == 0 and "모두 완료" in out
    prof = (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8")
    assert "- 현재 단계: 완료" in prof and all(f"{s} (" in prof for s in ss.STEPS)
    assert main(tmp_path, capsys, "--done", "S-7")[0] == 2


def test_done_keeps_other_sections(tmp_path, monkeypatch, capsys):
    all_pass(monkeypatch)
    main(tmp_path, capsys)
    prof = tmp_path / "SITE_PROFILE.md"
    prof.write_text(prof.read_text(encoding="utf-8") + "- (10/13) 사내 메모\n", encoding="utf-8")
    main(tmp_path, capsys, "--done", "S-1")
    text = prof.read_text(encoding="utf-8")
    assert text.endswith("- (10/13) 사내 메모\n") and "- 완료 단계: S-1 (" in text


def test_start_full_pack_first_visit_then_brief(tmp_path, monkeypatch, capsys):
    all_pass(monkeypatch)
    code, first, _ = main(tmp_path, capsys)
    assert code == 0                                                     # 점검이 모두 통과면 0
    _, again, _ = main(tmp_path, capsys)
    assert "===== docs/design/14-site.md §14.2 =====" in first and "§14.2 =====" not in again
    assert "요약 — 이미 본 단계" in again and "context_pack.py S-1" in again
    for out in (first, again):
        assert "자동 점검 S-1" in out and "사용자에게 물을 것" in out and "--done S-1" in out
    state = (tmp_path / "docs/site/steps/S-1.json").read_text(encoding="utf-8")
    assert '"visited"' in state and '"S-1.ok"' in state


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


def test_baseline_evals_are_in_site_set_and_help_has_no_rerun():
    pend = ss.sc.load_pending(ROOT)
    assert ss.BASELINE_EVALS is ss.sc.BASELINE_EVALS and set(ss.BASELINE_EVALS) <= set(pend["site"])
    assert set(pend["manual"]) <= set(pend["site"])
    assert "rerun" not in ss.__doc__ and "사내 대상" in ss.__doc__ and "offsite_results.json" in ss.__doc__
