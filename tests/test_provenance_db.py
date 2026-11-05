"""이슈 DB 쓰기의 분석 환경 출처(R5, DEC:51 ①): 커밋 메시지 마지막 trailer `Triage-Env: …`와 PR 본문 마지막 줄 `- 분석 환경: …`.

trailer는 확인 화면(`db_pr summary`)이 만드는 commit_message에 들어가므로 사용자 승인이 덮는다(publish는 그 바이트 그대로 커밋,
`dbpr/publish.py`는 바꾸지 않는다). 결과가 이 테스트를 Claude Code 안에서 돌리는지에 기대지 않도록 environ을 넘기거나
`provenance.env_info`를 바꿔 끼운다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import db_summary  # noqa: E402
from common import provenance  # noqa: E402

FIXED = {"runtime": "claude-code", "model": "모름", "model_defaults": {}, "gateway": "other", "label": "cc-internal"}


def test_trailer_shape_from_environ_and_site_label():
    env = {"CLAUDECODE": "1", "ANTHROPIC_BASE_URL": "https://gw.example.invalid/v1", "ANTHROPIC_MODEL": "example-model"}
    line = db_summary.env_trailer(env, {"runtime": {"label": "cc-internal"}})
    assert line == "Triage-Env: runtime=claude-code; model=example-model; gateway=other; label=cc-internal"
    assert "gw.example" not in line and "http" not in line                # URL은 남기지 않는다
    assert db_summary.env_trailer({}, {}) == "Triage-Env: runtime=모름; model=모름; gateway=none; label=-"


def test_with_env_trailer_appends_after_blank_line_once():
    msg = "[DATA-001-02] add MOCK-7001: 로밍 중 데이터 로밍 OFF"
    out = db_summary.with_env_trailer(msg, {}, {})
    assert out == msg + "\n\nTriage-Env: runtime=모름; model=모름; gateway=none; label=-"
    assert db_summary.with_env_trailer(out, {}, {}) == out                 # 같은 trailer를 두 번 붙이지 않는다
    assert db_summary.with_env_trailer("", {}, {}) == ""


def _git_wt(tmp_path: Path):
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q", str(wt)], check=True)

    def git(repo, *a, check=True):
        return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True)
    return wt, git


def test_screen_and_pr_body_carry_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "env_info", lambda environ=None, cfg=None: dict(FIXED))
    wt, git = _git_wt(tmp_path)
    stage = {"apply": {"ids": [], "operations": [], "commit_message": "[DATA-001-04] add MOCK-1: x"},
             "config_check": {"push_allowed": True}}
    scr = db_summary.screen(wt, {"source": "analyze"}, stage, {"branch": "b"}, {}, job="j", base="main", git=git,
                            remote_sha=None, open_prs=[], push_note=None)
    trailer = "Triage-Env: runtime=claude-code; model=모름; gateway=other; label=cc-internal"
    assert scr["commit_message"] == "[DATA-001-04] add MOCK-1: x\n\n" + trailer
    assert scr["pr_title"] == "[DATA-001-04] add MOCK-1: x"                      # 제목은 첫 줄 그대로
    body = db_summary.pr_body(scr, {})
    assert body.rstrip("\n").splitlines()[-1] == "- 분석 환경: runtime=claude-code; model=모름; gateway=other; label=cc-internal"
    md = db_summary.render_markdown(scr, {}, db_summary.screen_extras(wt, scr, [], "0" * 40))
    assert trailer in md                                                        # 확인 화면에 보인다(승인 대상)


def test_pr_body_without_trailer_is_unchanged():
    scr = {"source_label": "분석 (analyze)", "notes": [], "ids": [], "files": [], "checks": {"skipped": "x"},
           "verification": [], "approval_needed": [], "commit_message": "[X] y"}
    assert "분석 환경" not in db_summary.pr_body(scr, {})


def test_publish_untouched_by_provenance():
    """publish는 승인된 메시지와 바이트 비교만 한다 — trailer를 붙이는 곳은 summary 하나다."""
    text = (REPO / "plugin" / "scripts" / "dbpr" / "publish.py").read_text(encoding="utf-8")
    assert "Triage-Env" not in text and "env_info" not in text
