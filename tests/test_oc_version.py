"""`plugin/scripts/common/oc_version.py` — OpenCode 바이너리 의존 한 곳(종합 리뷰 F②).

- 고정 버전의 유일한 시험 고정값은 여기(`PINNED`)다. 버전을 올리면 oc_version.py와 이 값, 두 곳만 바뀐다.
- 버전·거부 문구·CLI 인자·환경 변수 목록·이벤트 키는 oc_adapter·tt-oc·gen_opencode·ocenv가 모두 oc_version에서 읽는다(리터럴 없음).
- `tt-guard.js`는 JS라 가져오지 못한다 → hook 이름·내장 도구 표·버전 주석을 oc_version·oc_adapter와 대조한다.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tools"))
from common import oc_adapter, oc_version  # noqa: E402
import gen_opencode  # noqa: E402

PINNED = "1.19.5"
TTOC = REPO / "opencode" / "bin" / "tt-oc"
GUARD_JS = REPO / "opencode" / "plugins" / "tt-guard.js"
# 버전 리터럴을 두면 안 되는 코드(주석·docstring의 실험 기록은 허용 — 대입만 본다)
NO_LITERAL = ("plugin/scripts/common/oc_adapter.py", "plugin/scripts/common/oc_jira_gate.py", "plugin/scripts/job_status.py",
              "opencode/bin/tt-oc", "tools/gen_opencode.py", "tools/site_step.py", "tests/opencode/ocenv.py")
VERSION_ASSIGN = re.compile(r'^\s*[A-Za-z_][A-Za-z_0-9]*\s*=\s*"\d+\.\d+\.\d+"', re.MULTILINE)


def _tt_oc():
    loader = importlib.machinery.SourceFileLoader("tt_oc_ver_test", str(TTOC))
    spec = importlib.util.spec_from_loader("tt_oc_ver_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_single_pin():
    assert oc_version.OPENCODE_VERSION == PINNED
    tt = _tt_oc()
    assert tt.PINNED == oc_adapter.OPENCODE_VERSION == gen_opencode.OPENCODE_VERSION == PINNED
    for rel in NO_LITERAL:
        assert not VERSION_ASSIGN.search((REPO / rel).read_text(encoding="utf-8")), f"{rel}: 버전 리터럴 대입 — oc_version에서 읽는다"


def test_oc_version_imports_nothing():
    src = (REPO / "plugin" / "scripts" / "common" / "oc_version.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s", src, re.MULTILINE)


def test_tt_oc_takes_every_surface_from_oc_version():
    tt = _tt_oc()
    # tt-oc는 oc_version.py를 경로로 따로 읽으므로(모듈 객체 별개) 값으로 비교한다
    assert tt.REFUSED_ARGS == oc_version.REFUSED_ARGS and tt.REFUSED_ENV == oc_version.REFUSED_ENV
    assert tt.REFUSED_ENV_PREFIX == oc_version.REFUSED_ENV_PREFIX and tt.INSTRUCTION_FILES == oc_version.INSTRUCTION_FILES
    assert set(oc_version.DENY_PHRASES) <= set(tt.BLOCK_MARKERS) and "[telephony-triage]" in tt.BLOCK_MARKERS
    assert set(oc_version.CHILD_ENV) <= set(tt.child_env({"plugin_root": "/p", "work_root": "/w"}))
    src = TTOC.read_text(encoding="utf-8")
    for literal in ('"--version"', '"debug", "config"', '"run", "--format", "json"', '"session", "delete"',
                    '"sessionID"', '"step_start"', '"step_finish"', '"tool_use"'):
        assert literal not in src, f"tt-oc에 바이너리 표면 리터럴 {literal}"


def test_adapter_shares_refused_env_and_deny_phrases():
    assert oc_adapter.REFUSED_ENV is oc_version.REFUSED_ENV
    assert oc_adapter.REFUSED_ENV_PREFIXES is oc_version.REFUSED_ENV_PREFIX
    assert oc_adapter.refused_env({"OPENCODE_AUTO_SHARE": "1", "OPENCODE_ENABLE_EXPERIMENTAL_X": "1", "PATH": "/"}) == \
        ["OPENCODE_AUTO_SHARE", "OPENCODE_ENABLE_EXPERIMENTAL_X"]       # tt-oc와 같은 목록(전에는 어댑터에 없던 둘)
    for phrase in oc_version.DENY_PHRASES:
        assert oc_adapter.error_class(f"x {phrase} y") == "permission-denied"
    assert oc_adapter.error_class("permission denied") == "auth"      # 바이너리 문구가 아닌 일반 낱말은 그대로 auth


def test_judge_reads_the_pinned_event_schema():
    V, tt = oc_version, _tt_oc()
    events = [{"type": V.EV_STEP_START, V.EV_SESSION: "ses_1"},
              {"type": V.EV_TOOL_USE, V.EV_PART: {V.PART_TOOL: "bash", V.PART_STATE: {
                  V.STATE_STATUS: V.STATUS_ERROR, V.STATE_ERROR: f"The agent config {V.DENY_PHRASES[0]}.",
                  V.STATE_INPUT: {"command": "git push"}}}},
              {"type": V.EV_TEXT, V.EV_PART: {V.PART_TEXT: "done"}},
              {"type": V.EV_STEP_FINISH, V.EV_PART: {V.PART_REASON: V.FINISH_STOP, V.PART_TOKENS: {"input": 3, "output": 2}}}]
    res = tt.judge(events, 0)
    assert res["outcome"] == "blocked" and res["session"] == "ses_1" and res["final_text"] == "done"
    assert res["tokens"] == {"input": 3, "output": 2, "reasoning": 0} and res["user_commands"] == ["git push"]
    assert res["blocked"][0]["tool"] == "bash"


def test_guard_js_matches_oc_version():
    js = GUARD_JS.read_text(encoding="utf-8")
    hooks = re.findall(r'^    "([a-z.]+)": async', js, re.MULTILINE)
    assert tuple(hooks) == oc_version.HOOKS
    assert f"OpenCode {PINNED}" in js.splitlines()[0], "tt-guard.js 머리 주석의 버전이 oc_version과 다르다 — 새 버전으로 재확인한 뒤 고친다"
    m = re.search(r"const BUILTINS = new Set\(\[(.*?)\]\)", js, re.DOTALL)
    assert m and set(re.findall(r'"([a-z_]+)"', m.group(1))) == set(oc_adapter.BUILTINS)
