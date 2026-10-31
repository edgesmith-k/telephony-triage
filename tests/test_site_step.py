"""tools/site_step.py: "사내 설정 시작" 진행기 — SITE_PROFILE.md 생성, 단계 순서, 건너뛰기 거부, 사외 PC 거부."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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


def all_skip(monkeypatch):
    """--waive 기록만 보는 테스트: 점검을 모두 건너뜀으로 바꾼다(면제해야 --done이 된다)."""
    monkeypatch.setattr(ss.sc, "CHECKS", {s: [lambda ctx, s=s: ss.sc.res(f"{s}.x", "skip", "합성")] for s in ss.STEPS})


WAIVE_LINE_RE = re.compile(r"^- \((\d{4}-\d{2}-\d{2})\) (S-\S+) (\S+) 면제\(사용자 결정\): (.+)$")


@pytest.mark.parametrize("form", ["sep", "eq"])
@pytest.mark.parametrize("why", ["사내 Jira 없음 - S-4에서 다시", "A -- B", "-로 시작", "--foo 이유", "a | b", "x — y", "LTE-A 망"])
def test_waive_reason_with_dashes_is_recorded_whole_at_line_end(tmp_path, monkeypatch, capsys, why, form):
    all_skip(monkeypatch)
    main(tmp_path, capsys)
    args = ["--waive", f"S-1.x={why}"] if form == "sep" else [f"--waive=S-1.x={why}"]
    code, out, err = main(tmp_path, capsys, "--done", "S-1", *args)
    assert code == 0, err
    lines = [l for l in (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8").split("## 설계 변경")[1].splitlines()
             if "면제" in l]
    assert len(lines) == 1
    m = WAIVE_LINE_RE.match(lines[0])
    assert m and m.group(2, 3, 4) == ("S-1", "S-1.x", why)                  # 사유가 줄 끝 — 그대로 되읽힌다
    assert lines[0] in out                                                  # 기록한 줄을 출력에 보인다
    assert (tmp_path / ss.sc.EVIDENCE_FILE).read_text(encoding="utf-8").endswith(f" 사용자 결정: {why}\n")


def test_long_waive_reason_points_to_evidence_instead_of_silent_cut(tmp_path, monkeypatch, capsys):
    all_skip(monkeypatch)
    main(tmp_path, capsys)
    why = "사내 Jira 프로젝트가 아직 없어 S-4에서 샘플을 받는다 - " + "가나다라마바사아자차 " * 15 + "끝"
    assert len(why) > 200
    code, out, err = main(tmp_path, capsys, "--done", "S-1", "--waive", f"S-1.x={why}")
    assert code == 0, err
    prof = (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8")
    line = next(l for l in prof.splitlines() if "면제(사용자 결정)" in l)
    reason = WAIVE_LINE_RE.match(line).group(4)
    assert reason == why[:ss.WAIVE_PROFILE_MAX].rstrip() + "…(전체: docs/site/evidence.md)"
    assert line in out and len(prof.encode("utf-8")) <= 4096
    assert (tmp_path / ss.sc.EVIDENCE_FILE).read_text(encoding="utf-8").endswith(f" 사용자 결정: {why}\n")   # 전체 사유


def test_duplicate_waive_id_refused(tmp_path, monkeypatch, capsys):
    all_skip(monkeypatch)
    main(tmp_path, capsys)
    code, _, err = main(tmp_path, capsys, "--done", "S-1", "--waive", "S-1.x=a", "--waive", "S-1.x=b")
    assert code == 2 and "두 번" in err
    prof = (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8")
    assert "- 현재 단계: S-1" in prof and "면제" not in prof                 # 아무것도 기록하지 않는다


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


# --- oFono 트랙 (O-1~O-4, 15-local-draft.md §15.5) ---------------------------------------------------------------

def all_pass_all(monkeypatch):
    """S·O 단계 점검을 모두 통과로 바꾼다(순서·기록만 본다)."""
    monkeypatch.setattr(ss.sc, "CHECKS", {s: [lambda ctx, s=s: ss.sc.res(f"{s}.ok", "pass", "합성")]
                                          for s in ss.STEPS + ss.OFONO_STEPS})


def all_skip_all(monkeypatch):
    monkeypatch.setattr(ss.sc, "CHECKS", {s: [lambda ctx, s=s: ss.sc.res(f"{s}.x", "skip", "합성")]
                                          for s in ss.STEPS + ss.OFONO_STEPS})


def _done_through(root: Path, capsys, last: str, *extra: str) -> None:
    main(root, capsys)
    for s in ss.STEPS[:ss.STEPS.index(last) + 1]:
        code, _, err = main(root, capsys, "--done", s, *[x.format(s=s) for x in extra])
        assert code == 0, err


def _progress(root: Path) -> list[str]:
    text = (root / "SITE_PROFILE.md").read_text(encoding="utf-8")
    return [ln for ln in text.split("## 진행 상태", 1)[1].split("\n## ", 1)[0].splitlines() if ln.startswith("- ")]


def test_ofono_steps_follow_15_5_table():
    assert ss.OFONO_STEPS == [p for p in ("O-1", "O-2", "O-3", "O-4", "O-5") if cp.step_row(p)]
    assert set(ss.sc.CHECKS) == set(ss.STEPS) | set(ss.OFONO_STEPS)
    for rx in (ss.OFONO_CURRENT_RE, ss.OFONO_FINISHED_RE):        # Android 진행 줄과 겹치지 않는다
        assert not rx.search("- 현재 단계: S-1\n- 완료 단계: S-1 (2026-10-01)\n")
    for rx in (ss.CURRENT_RE, ss.FINISHED_RE):
        assert not rx.search("- oFono 단계: O-1\n- oFono 완료: (없음)\n")
    assert ss.S3_DONE_RE.search("S-1 (2026-10-01), S-2 (2026-10-02), S-3 (2026-10-03)")
    assert not ss.S3_DONE_RE.search("S-1 (2026-10-01), S-2 (2026-10-02)")


def test_ofono_start_requires_s3_done(tmp_path, monkeypatch, capsys):
    all_pass_all(monkeypatch)
    code, _, err = main(tmp_path, capsys, "ofono")
    assert code == 2 and "SITE_PROFILE.md가 없다" in err
    _done_through(tmp_path, capsys, "S-2")
    before = (tmp_path / "SITE_PROFILE.md").read_bytes()
    code, _, err = main(tmp_path, capsys, "ofono")
    assert code == 2 and "S-3 완료" in err and "S-3" in err
    assert (tmp_path / "SITE_PROFILE.md").read_bytes() == before
    with pytest.raises(SystemExit):                                     # 단계 인자는 받지 않는다
        ss.main(["--root", str(tmp_path), "ofono", "O-2"])


def test_ofono_start_adds_two_lines_once(tmp_path, monkeypatch, capsys):
    all_pass_all(monkeypatch)
    _done_through(tmp_path, capsys, "S-3")
    android = [ln for ln in _progress(tmp_path)]
    code, out, err = main(tmp_path, capsys, "ofono")
    assert code == 0, err
    assert "oFono 트랙을 시작했다. oFono 트랙 지금 단계: O-1" in out and "§15.5 O-1" in out and "--done O-1" in out
    assert "자동 점검 O-1" in out
    code, again, _ = main(tmp_path, capsys, "ofono")
    assert code == 0 and "시작했다" not in again and "oFono 트랙 지금 단계: O-1" in again and "요약 — 이미 본 단계" in again
    lines = _progress(tmp_path)
    assert lines == android + ["- oFono 단계: O-1", "- oFono 완료: (없음)"]
    assert (tmp_path / "docs/site/steps/O-1.json").is_file()
    # 인자 없는 check·propose는 Android 현재 단계를 보므로 oFono 안내는 단계를 붙인다(Android 안내는 그대로)
    assert "`site_step.py check O-1` 보고" in out and "`python3 tools/site_step.py check O-1`" in out
    assert "propose O-1 [--set 키=값]" in out and "`propose O-1 --apply ID[,ID]`" in out
    _, android_out, _ = main(tmp_path, capsys)
    assert "`site_step.py check` 보고" in android_out and "check O-" not in android_out.replace("site_step.py ofono", "")


def test_no_arg_pointer_line_only_when_started(tmp_path, monkeypatch, capsys):
    all_pass_all(monkeypatch)
    _done_through(tmp_path, capsys, "S-3")
    _, before, _ = main(tmp_path, capsys)
    assert "oFono 트랙" not in before and "site_step.py ofono" not in before
    main(tmp_path, capsys, "ofono")
    _, after, _ = main(tmp_path, capsys)
    assert after == before.rstrip("\n") + "\noFono 트랙: O-1 진행 중 → python3 tools/site_step.py ofono\n"
    assert after.count("oFono 트랙:") == 1 and "지금 단계: S-4a" in after


def test_ofono_done_order_refuses_skip_and_marks_done(tmp_path, monkeypatch, capsys):
    all_pass_all(monkeypatch)
    _done_through(tmp_path, capsys, "S-3")
    main(tmp_path, capsys, "ofono")
    code, _, err = main(tmp_path, capsys, "--done", "O-2")
    assert code == 2 and "oFono 현재 단계는 O-1" in err
    for cur, nxt in zip(ss.OFONO_STEPS, ss.OFONO_STEPS[1:]):
        code, out, err = main(tmp_path, capsys, "--done", cur)
        assert code == 0, err
        assert f"oFono 트랙 지금 단계: {nxt}" in out and f"§15.5 {nxt}" in out
    code, out, _ = main(tmp_path, capsys, "--done", "O-4")
    assert code == 0 and "oFono 트랙 O-1~O-4가 모두 완료" in out
    lines = _progress(tmp_path)
    assert "- oFono 단계: 완료" in lines and "- 현재 단계: S-4a" in lines
    fin = next(ln for ln in lines if ln.startswith("- oFono 완료:"))
    assert all(f"{s} (" in fin for s in ss.OFONO_STEPS)
    assert main(tmp_path, capsys, "--done", "O-4")[0] == 2
    _, out, _ = main(tmp_path, capsys)
    assert out.rstrip("\n").endswith("\noFono 트랙: 완료")


def test_ofono_done_before_start_is_usage(tmp_path, monkeypatch, capsys):
    all_pass_all(monkeypatch)
    _done_through(tmp_path, capsys, "S-3")
    before = (tmp_path / "SITE_PROFILE.md").read_bytes()
    for args in (("--done", "O-1"), ("check", "O-1"), ("propose", "O-1")):
        code, _, err = main(tmp_path, capsys, *args)
        assert code == 2 and "oFono 트랙이 시작되지 않았다" in err, args
    assert (tmp_path / "SITE_PROFILE.md").read_bytes() == before


def test_android_done_shows_ofono_step_directly(tmp_path, monkeypatch, capsys):
    all_pass_all(monkeypatch)
    _done_through(tmp_path, capsys, "S-3")
    main(tmp_path, capsys, "ofono")
    for s in ss.STEPS[3:]:
        assert main(tmp_path, capsys, "--done", s)[0] == 0
    code, out, _ = main(tmp_path, capsys)
    assert code == 0 and "oFono 트랙 지금 단계: O-1" in out and "자동 점검 O-1" in out and "S-1~S-7이 모두 완료" not in out
    code, out, _ = main(tmp_path, capsys, "check")
    assert code == 0 and "자동 점검 O-1" in out


def test_ofono_waiver_recorded(tmp_path, monkeypatch, capsys):
    all_skip_all(monkeypatch)
    _done_through(tmp_path, capsys, "S-3", "--waive", "{s}.x=합성")
    main(tmp_path, capsys, "ofono")
    assert main(tmp_path, capsys, "--done", "O-1")[0] == 1                 # 면제 없이는 거부
    code, out, err = main(tmp_path, capsys, "--done", "O-1", "--waive", "O-1.x=짝 없음(S26) - 확인")
    assert code == 0, err
    line = next(ln for ln in (tmp_path / "SITE_PROFILE.md").read_text(encoding="utf-8").split("## 설계 변경")[1].splitlines()
                if " O-1 " in ln)
    assert re.match(r"^- \(\d{4}-\d{2}-\d{2}\) O-1 O-1\.x 면제\(사용자 결정\): 짝 없음\(S26\) - 확인$", line), line   # S 단계와 같은 형식
    assert line in out and "- oFono 단계: O-2" in _progress(tmp_path)
    assert (tmp_path / ss.sc.EVIDENCE_FILE).read_text(encoding="utf-8").endswith("O-1 O-1.x 면제(skip, 근거 합성) 사용자 결정: 짝 없음(S26) - 확인\n")


def test_check_o_step_writes_only_O_json(tmp_path):
    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a], capture_output=True, text=True, check=True).stdout
    git("init", "-q")
    prof = ss.skeleton(tmp_path).replace("- 현재 단계: S-1", "- 현재 단계: S-4a").replace(
        "- 완료 단계: (없음)", "- 완료 단계: S-1 (2026-10-01), S-2 (2026-10-02), S-3 (2026-10-03)")
    (tmp_path / "SITE_PROFILE.md").write_text(prof, encoding="utf-8")
    r = run(tmp_path, "check", "O-1")
    assert r.returncode == 2 and "oFono 트랙이 시작되지 않았다" in r.stderr
    r = run(tmp_path, "ofono")
    assert r.returncode == 1 and "o1.masked" in r.stdout and "ofono_log_dir" in r.stdout, r.stderr
    git("add", "-A")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-qm", "init")
    r = run(tmp_path, "check", "O-2")
    assert r.returncode == 1 and "자동 점검 O-2" in r.stdout and "o2.rows" in r.stdout
    changed = [ln[3:] for ln in git("status", "--porcelain", "--untracked-files=all").splitlines()]
    assert changed == ["docs/site/steps/O-2.json"], changed
    r = run(tmp_path, "check", "O-9")
    assert r.returncode == 2 and "oFono 단계 'O-9'를 모른다" in r.stderr and "O-1 → O-2" in r.stderr
    assert run(tmp_path, "check", "S-9").stderr.count("S-1 → S-2") == 1    # Android 메시지는 그대로
