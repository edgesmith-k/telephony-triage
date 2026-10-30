"""원문 로그 판별의 플랫폼 경유 (17-platforms 묶음 1 리뷰 P1-1·P1-2, P2).

- guard 규칙 10: 설치된 플랫폼 전부(`known()`)의 합집합, 플랫폼마다 따로 불러와 하나가 깨져도 나머지 판별 유지,
  레지스트리 전체가 깨져도 내장 최소 판별(logcat 스탬프·bugreport 머리), 판별 함수 예외는 원문으로 본다(fail-closed),
  늦게 생긴 경고도 출력에 들어간다.
- issue_post fill 검사: `known()` 합집합, 깨진 플랫폼은 경고하고 나머지로 계속, 잘못된 `platform:` 블록과 무관.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tests" / "helpers"))

import guard  # noqa: E402
import issue_post  # noqa: E402
import platforms  # noqa: E402
from common import masking  # noqa: E402
import make_plugin_root  # noqa: E402

PLUGIN = str(REPO / "plugin")      # site-defaults.yaml 없음 → 설정 경고 1개, 사용자 config 없음
LOGCAT = "09-20 14:32:11.123  1234  1300 E RILJ: x\n"
TIMEFMT = "09-20 14:32:11.123 E/RILJ( 1234): x\n"
DUMPSTATE = "== dumpstate: 2026-09-20 14:32:11\n"
SECTION = "------ RADIO LOG (logcat -b radio -v threadtime -d *:v) ------\n"
PLAIN = "평범한 메모\n"


@pytest.fixture
def files(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEPHONY_TRIAGE_HOME", str(tmp_path / "home"))
    out = {}
    for name, text in (("logcat", LOGCAT), ("timefmt", TIMEFMT), ("dumpstate", DUMPSTATE),
                       ("section", SECTION), ("plain", PLAIN)):
        out[name] = tmp_path / f"{name}.txt"
        out[name].write_text(text, encoding="utf-8")
    return out


def _judge(path: Path):
    out, warn = guard.judge({"tool_name": "Bash", "tool_input": {"command": f"cat {path}"}, "cwd": str(path.parent)},
                            PLUGIN)
    return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision"), [w for w in warn if "규칙 10" in w]


def _decisions(files) -> dict:
    return {k: _judge(p)[0] for k, p in files.items()}


EXPECT = {"logcat": "deny", "timefmt": "deny", "dumpstate": "deny", "section": "deny", "plain": None}


def test_normal_rule10_unchanged(files):
    assert _decisions(files) == EXPECT
    assert _judge(files["logcat"])[1] == []


def test_registry_failure_keeps_builtin_minimum(files, monkeypatch):
    def boom():
        raise RuntimeError("레지스트리 고장")
    monkeypatch.setattr(platforms, "known_raw_line_finders", boom)
    assert _decisions(files) == EXPECT
    decision, warns = _judge(files["plain"])
    assert decision is None and len(warns) == 1 and "레지스트리" in warns[0]


def test_one_broken_platform_keeps_others(files, monkeypatch):
    real = platforms.known_raw_line_finders

    def partial():
        finders, errors = real()
        return finders, errors + [("broken", ModuleNotFoundError("no_dep"))]
    monkeypatch.setattr(platforms, "known_raw_line_finders", partial)
    assert _decisions(files) == EXPECT
    warns = _judge(files["plain"])[1]
    assert len(warns) == 1 and "broken" in warns[0]


def test_android_broken_falls_back_to_builtin(files, monkeypatch):
    """android 하나만 있는 설치에서 android가 깨지면 내장 최소 판별로 logcat·bugreport 머리를 계속 막는다."""
    monkeypatch.setattr(platforms, "known_raw_line_finders", lambda: ([], [("android", ImportError("x"))]))
    assert _decisions(files) == EXPECT


def test_sniff_exception_is_fail_closed(files, monkeypatch):
    real = platforms.known_raw_line_finders

    def raiser(line):
        raise ValueError("판별 고장")

    def with_bad():
        finders, errors = real()
        return [("bad", raiser, raiser, raiser)] + finders, errors
    monkeypatch.setattr(platforms, "known_raw_line_finders", with_bad)
    assert _judge(files["plain"])[0] == "deny"          # 판별이 깨지면 원문으로 본다
    assert _judge(files["logcat"])[0] == "deny"


def test_late_warning_reaches_stderr(files, monkeypatch, capsys):
    """검사 중에 생긴 규칙 10 경고가 hook stderr에 나온다(설정 경고는 검사 뒤에 합친다)."""
    monkeypatch.setattr(platforms, "known_raw_line_finders", lambda: ([], [("android", ImportError("x"))]))
    event = {"tool_name": "Bash", "tool_input": {"command": f"cat {files['logcat']}"}, "cwd": str(files["logcat"].parent)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    bare = make_plugin_root.make(files["logcat"].parent / "bare-root")   # SITE_PATHS 제외 복사본 — 사내 레포에서도 site-defaults 없음
    (bare / "site-defaults.yaml").unlink()
    assert guard.main(["--plugin-root", str(bare)]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    err = captured.err.splitlines()
    assert any("site-defaults.yaml이 없다" in line for line in err)
    assert any("규칙 10: 플랫폼 android" in line for line in err)
    assert [i for i, line in enumerate(err) if "site-defaults" in line][0] < \
        [i for i, line in enumerate(err) if "규칙 10" in line][0]


def test_rule10_ignores_platform_config(files, tmp_path):
    """규칙 10은 설정(`platform.enabled`)과 무관하게 설치된 플랫폼 전부를 본다 — 잘못된 platform 블록에도 같은 판정."""
    import shutil

    root = tmp_path / "plugin"
    shutil.copytree(REPO / "plugin" / "scripts", root / "scripts")
    (root / "site-defaults.yaml").write_text("platform:\n  name: nosuch\n", encoding="utf-8")
    out, warn = guard.judge({"tool_name": "Bash", "tool_input": {"command": f"cat {files['logcat']}"},
                             "cwd": str(tmp_path)}, str(root))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not [w for w in warn if "규칙 10" in w]


# -- issue_post --------------------------------------------------------------------------


def _fill(text: str, finders=None):
    masker = masking.new_masker(existing_text="", allow_patterns=[])
    raw = {"problem": "증상 한 줄", "cause": [{"basis": "log", "text": text}], "next": [], "code_location": None}
    return issue_post.check_fill(raw, True, True, masker, [], finders)


def test_fill_rejects_raw_logcat_line():
    _, problems, warnings = _fill("근거 " + LOGCAT.strip())
    assert any("로그 원문 줄 모양" in p for p in problems) and warnings == []
    _, problems, _ = _fill("원문 줄이 없는 문장")
    assert not any("로그 원문 줄 모양" in p for p in problems)


def test_fill_broken_platform_warns_and_continues(monkeypatch):
    real = platforms.known_raw_line_finders
    monkeypatch.setattr(platforms, "known_raw_line_finders",
                        lambda: (real()[0], [("broken", ModuleNotFoundError("no_dep"))]))
    _, problems, warnings = _fill("근거 " + LOGCAT.strip())
    assert any("로그 원문 줄 모양" in p for p in problems)
    assert len(warnings) == 1 and "broken" in warnings[0]


def test_fill_finder_exception_is_fail_closed():
    def raiser(text):
        raise ValueError("x")
    _, problems, _ = _fill("원문 줄이 없는 문장", [raiser])
    assert any("로그 원문 줄 모양" in p for p in problems)


def test_raw_finders_use_known_platforms():
    finders, warnings = issue_post.raw_finders()
    expected = [find for _, _, find, _ in platforms.known_raw_line_finders()[0]]
    assert finders == expected and len(finders) == len(platforms.known()) and warnings == []
