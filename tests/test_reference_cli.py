"""W7: 스킬 문서의 CLI 호출 조각이 실제 argparse와 맞는지(drift), 계약 생성물이 최신인지, analysis 출력 스키마.

대상: plugin/skills/telephony-triage/SKILL.md, reference/*.md, plugin/commands/*.md의 인라인 코드(`…`).
코드 블록(```)은 슬래시 커맨드 사용법이라 뺀다. 조각은 인자를 생략한 것이 많으므로 "필수 인자 없음"류 오류는 허용하고,
없는 옵션·서브커맨드·상호 배제 위반만 실패로 본다.

스크립트 이름(related_tests.py가 이 파일을 고르도록): config.py code_roots.py parse_logcat.py mask_pii.py jira_fields.py
match_signatures.py db_search.py db_add.py db_build.py db_lint.py db_regress.py db_verify.py db_pr.py db_precommit.py
db_review.py db_migrate.py guard.py jira_bridge.py triage.py gen_contracts.py analysis.schema.json
"""

from __future__ import annotations

import argparse
import copy
import importlib
import importlib.util
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
SKILL = PLUGIN / "skills" / "telephony-triage"

_spec = importlib.util.spec_from_file_location("gen_contracts", REPO / "tools" / "gen_contracts.py")
gen_contracts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_contracts)

# argparse 오류 문구 (Py 3.11·3.14 확인). 조각이 인자를 생략해서 나는 오류는 허용, 이름·조합이 틀린 오류는 실패.
ARGPARSE_ALLOWED = ("the following arguments are required", "one of the arguments", "expected one argument",
                    "expected at least one argument")
ARGPARSE_FAILED = ("unrecognized arguments", "not allowed with argument", "invalid choice")
PH = "PH"           # <…> 자리 표시 (값이 PH라서 난 오류는 허용)

# 최소 수: 실제 집계(조각 104개, 스크립트 15개, W7)의 80% 내림
MIN_FRAGMENTS = 83
MIN_SCRIPTS = 12

CODE_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
FRAGMENT = re.compile(r"(?:S/|\$\{CLAUDE_PLUGIN_ROOT\}/scripts/)?\b([a-z_]+)\.py\b(.*)")
GROUP = re.compile(r"[\[(]([^\[\]()]*)[\])]")


class ArgError(Exception):
    pass


def _raise(self, message):          # ArgumentParser.error 대체: 종료 대신 예외
    raise ArgError(message)


@pytest.fixture(scope="module")
def parsers():
    return {name: importlib.import_module(name).build_parser()
            for name in gen_contracts.SCRIPTS if name not in gen_contracts.STDIN_ONLY}


def _docs() -> list[Path]:
    return [SKILL / "SKILL.md", *sorted((SKILL / "reference").glob("*.md")), *sorted((PLUGIN / "commands").glob("*.md"))]


def normalize(rest: str) -> list[str]:
    """`<…>`→PH, 생략 기호 삭제, `[…]`·`(…)`는 벗기고 첫 대안, 괄호 밖 ` | `면 앞부분."""
    text = rest.replace("\\|", "|")
    text = re.sub(r"<[^<>]*>", PH, text)
    text = text.replace("…", "").replace("...", "")
    while (m := GROUP.search(text)):
        text = text[:m.start()] + m.group(1).split("|")[0].strip() + text[m.end():]
    if " | " in text:
        text = text.split(" | ")[0]
    return shlex.split(text)


def fragments(names) -> list[tuple[str, str, str, str]]:
    out = []
    for doc in _docs():
        text = re.sub(r"^```.*?^```", "", doc.read_text(encoding="utf-8"), flags=re.S | re.M)
        for m in CODE_SPAN.finditer(text):
            frag = FRAGMENT.search(m.group(1))
            if frag and frag.group(1) in names:
                out.append((str(doc.relative_to(REPO)), m.group(1), frag.group(1), frag.group(2)))
    return out


def _subparsers(parser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


OPTION = re.compile(r"--[a-z][a-z0-9-]*")


def problems(parser: argparse.ArgumentParser, rest: str) -> list[str]:
    """`rest` = 조각에서 스크립트 이름 뒤. 검사 1은 모든 대안의 옵션 이름, 검사 2는 첫 대안으로 실제 파싱."""
    found = []
    tokens = normalize(rest)
    chain, sub = [parser], _subparsers(parser)        # 서브커맨드 경로(상위 파서 포함)
    pending = 0                                 # 앞 옵션의 값으로 건너뛸 토큰 수(-1: 다음 옵션까지)
    for tok in tokens:                          # 서브커맨드 경로 찾기(없는 서브커맨드는 실패)
        if tok.startswith("--"):
            opt, _, inline = tok.partition("=")
            action = next((q._option_string_actions[opt] for q in reversed(chain) if opt in q._option_string_actions), None)
            if action is None or inline:
                pending = 0
            else:
                nargs = action.nargs
                pending = nargs if isinstance(nargs, int) else 1 if nargs is None else -1
        elif pending:
            pending -= 1 if pending > 0 else 0
        elif sub is not None and not tok.startswith("-"):
            if tok in sub.choices:
                chain.append(sub.choices[tok])
                sub = _subparsers(sub.choices[tok])
            elif tok != PH:                     # `<서브커맨드>` 자리 표시는 넘어간다
                found.append(f"없는 서브커맨드 {tok} ({chain[-1].prog})")
                sub = None
            else:
                sub = None
    # 검사 1: 원문(모든 대안)의 옵션 이름이 그 서브파서나 상위 파서에 정확히 있다(약어 불가)
    for opt in OPTION.findall(re.sub(r"<[^<>]*>", PH, rest)):
        if not any(opt in q._option_string_actions for q in chain):
            found.append(f"없는 옵션 {opt} ({chain[-1].prog})")
    original = argparse.ArgumentParser.error
    argparse.ArgumentParser.error = _raise   # 검사 2: 첫 대안으로 실제 파싱(남는 인자도 실패)
    try:
        _, extras = parser.parse_known_args(tokens)
        if extras:
            found.append(f"argparse: 남는 인자 {extras}")
    except ArgError as exc:
        msg = str(exc)
        if any(s in msg for s in ARGPARSE_FAILED) and not ("invalid choice" in msg and f"'{PH}'" in msg):
            found.append(f"argparse: {msg}")
        elif PH not in msg and not any(s in msg for s in ARGPARSE_ALLOWED):
            found.append(f"argparse: {msg}")
    finally:
        argparse.ArgumentParser.error = original
    return found


def test_reference_cli_fragments_match_argparse(parsers):
    frags = fragments(parsers)
    assert len(frags) >= MIN_FRAGMENTS, len(frags)
    assert len({f[2] for f in frags}) >= MIN_SCRIPTS
    bad = [(path, raw, p) for path, raw, name, rest in frags for p in [problems(parsers[name], rest)] if p]
    assert not bad, "\n".join(f"{path}: `{raw}` → {p}" for path, raw, p in bad)


@pytest.mark.parametrize("name,fragment", [
    ("db_pr", "stage <plan> --wt <wt> --branch <br> --then-sumary"),   # 오타 옵션
    ("db_build", "--verify --staged --write"),                         # 상호 배제 위반
    ("db_pr", "lokc status"),                                          # 없는 서브커맨드
    ("db_lint", "(--all | --chnged <ref>) --db <db>"),                 # 두 번째 대안 오타
])
def test_drift_check_catches_bad_fragments(parsers, name, fragment):
    assert problems(parsers[name], fragment)


def test_gen_contracts_check_is_clean():
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "gen_contracts.py"), "--check"],
                          capture_output=True, text=True, encoding="utf-8", cwd=REPO)
    assert proc.returncode == 0, proc.stderr


def test_every_cli_script_is_covered():
    listed = set(gen_contracts.SCRIPTS) | set(gen_contracts.NOT_CLI)
    assert set(gen_contracts.cli_scripts()) <= listed
    for name in gen_contracts.SCRIPTS:
        if name in gen_contracts.STDIN_ONLY:
            assert "argparse" not in (PLUGIN / "scripts" / f"{name}.py").read_text(encoding="utf-8"), name
        else:
            assert callable(getattr(importlib.import_module(name), "build_parser", None)), name


# -- analysis.schema.json -------------------------------------------------------------------------------------

OK_OFFLINE = {
    "status": "ok", "key": "EVAL-1", "generated_at": "2026-10-06T00:00:00+00:00", "request_hash": "0123456789abcdef",
    "mode": "offline", "logs": {"files": ["a.log"], "range": ["t0", "t1"], "in_range": True, "events": 3},
    "candidates": [{"type": "CALL-001", "cause": "CALL-001-01", "title": "t", "category": "call", "score": 0.9,
                    "confidence": "high", "S": 1, "C": 1, "phones": [0],
                    "evidence": [{"ts": "t", "tag": "RILJ", "msg": "m", "event": "e"}],
                    "fix_judgement": None, "fix_message": None, "related": []}],
    "code": {"skipped": True}, "files": {"report": "r"}, "truncated": False,
}
NEEDS_INPUT = {"status": "needs_input", "key": "EVAL-1", "lock_owner": None,
               "needs_input": {"kind": "time", "question": "q", "options": [], "answer": "--answer time=<값>",
                               "log_range": ["t0", "t1"]}}
STOPPED = {"status": "stopped", "key": "EVAL-1", "reason": "사용자 중단", "lock_released": True}


@pytest.fixture(scope="module")
def triage():
    return importlib.import_module("triage")


@pytest.mark.parametrize("doc", [OK_OFFLINE, NEEDS_INPUT, STOPPED], ids=["ok-offline", "needs_input", "stopped"])
def test_analysis_schema_accepts_ok_needs_input_stopped_offline(triage, monkeypatch, doc):
    monkeypatch.setenv("TT_SCHEMA_CHECK", "1")
    assert triage.schema_violation(doc) is None


@pytest.mark.parametrize("where", ["top", "candidate", "evidence", "needs_input-top"])
def test_analysis_schema_rejects_added_keys(triage, monkeypatch, where):
    monkeypatch.setenv("TT_SCHEMA_CHECK", "1")
    doc = copy.deepcopy(NEEDS_INPUT if where == "needs_input-top" else OK_OFFLINE)
    target = {"top": doc, "needs_input-top": doc, "candidate": doc.get("candidates", [{}])[0],
              "evidence": doc.get("candidates", [{"evidence": [{}]}])[0]["evidence"][0]}[where]
    target["surprise"] = 1
    message = triage.schema_violation(doc)
    assert message and message.startswith("[telephony-triage] analysis 스키마 위반: ") and "surprise" in message


def test_analysis_schema_check_is_off_without_env_and_loud_without_jsonschema(triage, monkeypatch):
    monkeypatch.delenv("TT_SCHEMA_CHECK", raising=False)
    assert triage.schema_violation({"status": "ok"}) is None          # 운영 경로: 검사하지 않는다
    monkeypatch.setenv("TT_SCHEMA_CHECK", "1")
    monkeypatch.setitem(sys.modules, "jsonschema", None)               # import 실패 → 조용히 건너뛰지 않는다
    assert "analysis 스키마 위반" in (triage.schema_violation(STOPPED) or "")


def test_analysis_schema_is_plugin_owned_not_a_db_copy():
    schema = json.loads((PLUGIN / "schemas" / "output" / "analysis.schema.json").read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema")
    assert not (PLUGIN / "schemas" / "analysis.schema.json").exists()   # sync_schemas.py는 최상위만 대조한다
    kinds = schema["$defs"]["needs_input"]["properties"]["needs_input"]["properties"]["kind"]["enum"]
    contracts = (REPO / "docs" / "design" / "contracts.md").read_text(encoding="utf-8")
    assert "(kind: " + "·".join(f"`{k}`" for k in kinds) + ";" in contracts
