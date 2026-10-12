"""트래커 레지스트리·Jira 어댑터 (트래커 범용화 설계 §3·§4, 묶음 2 — jira 부분).

- 레지스트리: 이름 검증(정규식·`base`·`_x`), `known`, `get` 오류(모르는 이름·SPEC 타입·이름 불일치·패키지·하위 의존성),
  `kind_of`·`db_kind`(없으면 jira), `mismatch`, `all_server_words`(합집합, 깨진 트래커·레지스트리 실패 시 내장 jira·atlassian)
- 계층 규칙: `trackers/*`는 표준 라이브러리와 `trackers.base`만 import한다(트래커끼리 import 금지)
- Jira 어댑터: parse_key·safe_key·key_args·key_from_args·arg_names·key_arg_id·read_action·key_from_read·link·spec_problems
- 관문(서브프로세스): `tracker.kind` 오류 → guard 모든 MCP 거부·bridge 대체·스크립트 종료 2·doctor fail,
  `tracker-mismatch`(세션 kind ≠ DB kind) → check-key·issue_post 종료 2, 휴리스틱 합집합(설치된 트래커 단어)
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "plugin" / "scripts"
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(SCRIPTS))

import make_plugin_root  # noqa: E402
from runner import SAMPLE, run, tmp  # noqa: E402
from workspace import Workspace  # noqa: E402

import trackers  # noqa: E402
from common import issuepost  # noqa: E402
from trackers import TrackerConfigError, TrackerSpec  # noqa: E402
from trackers import jira as jira_tracker  # noqa: E402

KEY = "MOCK-1001"
MOCK_JIRA = REPO / "tests" / "mocks" / "jira"
LOG = REPO / "tests" / "fixtures" / "logs" / "data-disabled.log"
READ = "mcp__mock-jira__jira_fetch_ticket"
SECRET = "데이터 안 됨 imsi=450081234567890"
J = trackers.get("jira")
SPEC = {"tool": "mcp__mock-jira__jira_ticket_add_note", "key_arg": "ticket", "body_arg": "text", "extra_args": {},
        "format": "jira-wiki", "kind": "jira"}
# 테스트용 두 번째 트래커: jira 함수를 그대로 쓰고 이름·서버 단어만 다르다(플러그인 루트 복사본에만 둔다)
FAKE = textwrap.dedent('''\
    from dataclasses import replace
    import trackers.jira as _jira
    SPEC = replace(_jira.SPEC, name="fakebug", label="Fakebug", server_words=("bugzilla",))
''')


@pytest.fixture
def fake_trackers(tmp_path, monkeypatch):
    """`trackers.__path__`에 임시 디렉토리를 더해 가짜 트래커 모듈을 만든다. 끝나면 모듈·캐시를 지운다."""
    monkeypatch.setattr(trackers, "__path__", list(trackers.__path__) + [str(tmp_path)])
    made: list[str] = []

    def make(name: str, body: str, package: bool = False) -> None:
        if package:
            (tmp_path / name).mkdir()
            (tmp_path / name / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")
        else:
            (tmp_path / f"{name}.py").write_text(textwrap.dedent(body), encoding="utf-8")
        made.append(name)

    yield make
    for name in made:
        sys.modules.pop(f"trackers.{name}", None)
        trackers._SPECS.pop(name, None)


# -- 레지스트리 ----------------------------------------------------------------------------------


def test_known_lists_installed_modules_only():
    names = trackers.known()
    assert "jira" in names
    assert "base" not in names and all(not n.startswith("_") for n in names)
    assert names == sorted(names)


@pytest.mark.parametrize("name", ["../x", "Jira", "_x", "base", "a.b", "a/b", "", None, 1, "1x"])
def test_bad_names_rejected(name):
    with pytest.raises(TrackerConfigError, match="지원 트래커: .*jira"):
        trackers.get(name)


def test_unknown_name_rejected():
    with pytest.raises(TrackerConfigError, match=r"지원 트래커: .*'nosuch'"):
        trackers.get("nosuch")


def test_get_returns_cached_spec():
    assert trackers.get("jira") is trackers.get("jira") is jira_tracker.SPEC
    assert isinstance(J, TrackerSpec) and J.name == "jira" and J.label == "Jira"


def test_get_checks_spec_type_name_and_module_kind(fake_trackers):
    fake_trackers("notspec", "SPEC = 1\n")
    fake_trackers("wrongname", FAKE)          # SPEC.name이 fakebug
    fake_trackers("pkgtracker", FAKE, package=True)
    fake_trackers("fakebug", FAKE)
    with pytest.raises(TrackerConfigError, match="TrackerSpec이 아닙니다"):
        trackers.get("notspec")
    with pytest.raises(TrackerConfigError, match="모듈 이름과 다릅니다"):
        trackers.get("wrongname")
    with pytest.raises(TrackerConfigError, match="지원 트래커"):
        trackers.get("pkgtracker")             # 트래커는 패키지가 아니라 모듈이다
    assert trackers.get("fakebug").server_words == ("bugzilla",)
    assert "fakebug" in trackers.known() and "pkgtracker" not in trackers.known()


@pytest.mark.parametrize("body,why", [("import no_such_dependency_xyz\n", "ModuleNotFoundError"),
                                      ("SPEC = (\n", "SyntaxError"), ("raise RuntimeError('boom')\n", "RuntimeError"),
                                      ("from os import no_such_name\n", "ImportError")])
def test_broken_tracker_module_is_config_error(fake_trackers, body, why):
    """트래커 모듈을 불러오지 못하면(하위 의존성·문법·최상위 예외) 모두 `TrackerConfigError` — 스크립트는 종료 2, guard는 MCP 거부."""
    fake_trackers("broken", body)
    with pytest.raises(TrackerConfigError, match=f"트래커 broken을\\(를\\) 불러오지 못했다 \\({why}"):
        trackers.get("broken")
    with pytest.raises(TrackerConfigError):
        trackers.kind_of({"tracker": {"kind": "broken"}})


@pytest.mark.parametrize("cfg,want", [(None, "jira"), ({}, "jira"), ({"tracker": None}, "jira"), ({"tracker": {}}, "jira"),
                                      ({"tracker": {"kind": None}}, "jira"), ({"tracker": {"kind": "jira"}}, "jira")])
def test_kind_defaults_to_jira(cfg, want):
    assert trackers.kind_of(cfg) == want and trackers.db_kind(cfg) == want
    assert trackers.of(cfg) is J and trackers.of_db(cfg) is J


@pytest.mark.parametrize("kind", ["nosuch", "", "Jira", "base", 3])
def test_bad_kind_is_config_error(kind):
    with pytest.raises(TrackerConfigError, match=r"^설정 tracker\.kind: 지원 트래커"):
        trackers.kind_of({"tracker": {"kind": kind}})
    with pytest.raises(TrackerConfigError, match=r"^이슈 DB tracker\.kind: 지원 트래커"):
        trackers.db_kind({"tracker": {"kind": kind}})


def test_mismatch(fake_trackers):
    fake_trackers("fakebug", FAKE)
    assert trackers.mismatch({}, {"tracker": {"kind": "jira"}}) is None
    msg = trackers.mismatch({"tracker": {"kind": "fakebug"}}, {})
    assert msg.startswith("tracker-mismatch") and "이슈 DB 트래커는 jira" in msg and "tracker.kind는 fakebug" in msg
    with pytest.raises(TrackerConfigError):
        trackers.mismatch({}, {"tracker": {"kind": "nosuch"}})


def test_all_server_words_union_and_fallback(fake_trackers, monkeypatch):
    assert trackers.all_server_words() == ("atlassian", "jira")
    fake_trackers("fakebug", FAKE)
    assert trackers.all_server_words() == ("atlassian", "bugzilla", "jira")            # 설치된 모든 트래커(설정과 무관)
    fake_trackers("broken", "import no_such_dependency_xyz\n")
    words, errors = trackers.known_server_words()
    assert [n for n, _ in errors] == ["broken"] and "bugzilla" in words                 # 하나가 깨져도 나머지는 쓴다
    assert set(trackers.FALLBACK_SERVER_WORDS) <= set(trackers.all_server_words())


def test_all_server_words_registry_failure_uses_builtin(monkeypatch):
    def boom():
        raise RuntimeError("registry")
    monkeypatch.setattr(trackers, "known", boom)
    assert trackers.all_server_words() == ("atlassian", "jira")
    monkeypatch.setattr(trackers, "known", lambda: ["jira"])
    monkeypatch.setattr(trackers, "get", lambda kind: (_ for _ in ()).throw(ImportError("x")))
    assert trackers.all_server_words() == ("atlassian", "jira")                        # 전부 깨져도 내장 단어


def test_all_server_words_keeps_builtin_without_jira(fake_trackers, monkeypatch):
    """jira.py가 없는 설치(다른 트래커만)에서도 jira·atlassian 휴리스틱은 남는다."""
    fake_trackers("fakebug", FAKE)
    monkeypatch.setattr(trackers, "known", lambda: ["fakebug"])
    assert trackers.all_server_words() == ("atlassian", "bugzilla", "jira")


# -- 계층 규칙 ------------------------------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: 상대 import 금지"
            found.add(node.module or "")
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) \
                and isinstance(node.args[0].value, str) and getattr(node.func, "attr", getattr(node.func, "id", "")) \
                in ("import_module", "__import__"):
            found.add(node.args[0].value)
    return found


DYNAMIC_NAMES = {"__import__", "exec", "eval", "compile", "execfile", "importlib", "runpy", "import_module", "getattr"}
DYNAMIC_MODULES = {"importlib", "runpy", "builtins"}


@pytest.mark.parametrize("path", sorted(p for p in (SCRIPTS / "trackers").glob("*.py") if p.name != "__init__.py"),
                         ids=lambda p: p.name)
def test_tracker_modules_use_no_dynamic_import_or_exec(path):
    """트래커 모듈(레지스트리 제외)은 동적 import·exec·eval을 아예 쓰지 않는다 — 인자가 상수가 아니어도 정적 검사가 닿게.
    (`re.compile` 같은 속성 호출은 괜찮다. 맨 이름 `compile`·`getattr`·`import_module`과 importlib·runpy·builtins import는 금지)"""
    bad = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name) and node.id in DYNAMIC_NAMES:
            bad.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in ("import_module", "__import__"):
            bad.add(node.attr)
        elif isinstance(node, ast.Import):
            bad |= {a.name for a in node.names if a.name.split(".")[0] in DYNAMIC_MODULES}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in DYNAMIC_MODULES:
            bad.add(node.module)
    assert bad == set()


@pytest.mark.parametrize("path", sorted((SCRIPTS / "trackers").glob("*.py")), ids=lambda p: p.name)
def test_trackers_import_only_stdlib_and_base(path):
    """`trackers/*`는 표준 라이브러리와 `trackers.base`만 import한다(guard가 issuepost를 거쳐 불러온다). 트래커끼리 금지."""
    bad = set()
    for module in _imports(path):
        top = module.split(".")[0]
        if top in sys.stdlib_module_names or top == "__future__" or module == "trackers.base":
            continue
        bad.add(module)
    assert bad == set()


def test_registry_dynamic_import_is_name_based():
    text = (SCRIPTS / "trackers" / "__init__.py").read_text(encoding="utf-8")
    assert 'importlib.import_module(module_name)' in text and '"jira"' in text   # 기본 이름(DEFAULT_KIND)만 안다
    assert not re.search(r"import\s+trackers\.jira|from\s+trackers\s+import\s+jira", text)


# -- Jira 어댑터 ----------------------------------------------------------------------------------


@pytest.mark.parametrize("text,want", [("MOCK-1001", "MOCK-1001"), ("abc-1", "abc-1"), ("A_B-12", "A_B-12"),
                                       ("MOCK-1001 ", None), ("../MOCK-1", None), ("MOCK/1-1", None), ("1MOCK-1", None),
                                       ("MOCK-", None), ("org.repo-1", None), ("", None), (None, None), (5, None)])
def test_jira_parse_key_is_safe_key(text, want):
    assert J.parse_key(text) == want
    assert (want is not None) == bool(isinstance(text, str) and J.safe_key_re.fullmatch(text))


def test_jira_constants_are_previous_values():
    assert J.safe_key_re.pattern == r"^[A-Za-z][A-Za-z0-9_]*-[0-9]+$"          # 이전 `\d`를 ASCII로
    assert J.default_key_regex == r"[A-Z][A-Z0-9]+-[0-9]+"
    for key in ("MOCK-١٢٣", "MOCK-１"):                                              # 유니코드 숫자는 작업 키가 아니다
        assert J.parse_key(key) is None and not re.fullmatch(J.default_key_regex, key)
    assert J.server_words == ("jira", "atlassian")
    assert J.formats == ("jira-wiki", "markdown") and J.default_format == "jira-wiki"
    assert set(J.formats) <= set(issuepost.RENDERERS)
    assert dict(J.text_defaults) == {"summary": ("fields.summary", "summary"),
                                     "description": ("fields.description", "description"),
                                     "comments": ("comments[].body", "fields.comment.comments[].body")}
    assert J.components_default == "fields.components[].name"


def test_jira_key_args_and_round_trip():
    assert J.key_args(SPEC, KEY) == {"ticket": KEY}
    assert J.arg_names(SPEC) == {"ticket"} and J.key_arg_id(SPEC) == "ticket"
    assert J.key_from_args(SPEC, {"ticket": KEY, "text": "x"}) == KEY
    for bad in ({"ticket": "../x-1"}, {"ticket": 1001}, {"ticket": None}, {"key": KEY}, {}, "MOCK-1", None):
        assert J.key_from_args(SPEC, bad) is None, bad
    assert J.key_from_args(SPEC, J.key_args(SPEC, KEY)) == KEY


def test_jira_display_link_read_args_classify():
    assert J.display(KEY) == KEY
    assert J.link("https://jira.mock.invalid/browse/", KEY) == "https://jira.mock.invalid/browse/MOCK-1001"
    assert J.read_args("get_issue", KEY) is None and J.read_args("get_comments", KEY) is None
    assert J.classify_extra("jira_fetch_ticket", {"get_issue"}) == {"get_issue"}


@pytest.mark.parametrize("mapped,want", [({"get_issue"}, "get_issue"), ({"get_comments"}, "get_comments"),
                                         ({"get_issue", "get_comments"}, "get_issue"), (set(), None)])
def test_jira_read_action(mapped, want):
    assert J.read_action({"ticket": KEY}, mapped) == want


def test_jira_key_from_read():
    kre = re.compile(J.default_key_regex)
    assert J.key_from_read({"key": KEY}, {}, kre) == KEY
    assert J.key_from_read({"issue": {"key": KEY}}, {}, kre) == KEY
    assert J.key_from_read({"fields": {}}, {"ticket": KEY}, kre) == KEY                 # 응답에 없으면 도구 입력
    assert J.key_from_read({"key": "bad key"}, {"x": 1}, kre) is None
    loose = re.compile(r".+-\d+")                                                        # 넓은 DB 정규식이어도 경로 안전만
    assert J.key_from_read({"key": "../../etc-1"}, {}, loose) is None


KEYBODY = "add_comment.key_arg·body_arg는 서로 다른 비어 있지 않은 문자열이다"
EXTRA = "add_comment.extra_args는 객체이고 key_arg·body_arg와 겹치지 않는다"


@pytest.mark.parametrize("raw,want", [
    ({"key_arg": "ticket", "body_arg": "text"}, []),
    ({"key_arg": "ticket"}, []),                         # body_arg는 공통 검사(issuepost)
    ({"key_arg": "ticket", "extra_args": {"ticket": 1}}, []),   # extra_args도 공통 검사
    ({"body_arg": "text"}, [KEYBODY]),
    ({"key_arg": "", "body_arg": "text"}, [KEYBODY]),
    ({"key_arg": "t", "body_arg": "t"}, [KEYBODY]),
])
def test_jira_spec_problems_only_key_arg(raw, want):
    assert J.spec_problems(raw) == want


@pytest.mark.parametrize("over,want", [
    ({}, None),
    ({"extra_args": {"v": 1}}, None),
    ({"key_arg": None}, KEYBODY),
    ({"key_arg": "text"}, KEYBODY),
    ({"body_arg": None}, KEYBODY),
    ({"body_arg": 5}, KEYBODY),
    ({"extra_args": {"text": 1}}, EXTRA),
    ({"extra_args": {"ticket": 1}}, EXTRA),
    ({"extra_args": []}, EXTRA),
])
def test_spec_check_common_and_tracker_arg_problems(over, want):
    """공통 검사(body_arg·extra_args 겹침)는 issuepost, 키 인자는 어댑터 — 문구는 이전과 같다."""
    ac = {"tool": SPEC["tool"], "key_arg": "ticket", "body_arg": "text", **over}
    spec, problems = issuepost.spec_check(_cfg(write_tools={"add_comment": ac}))
    assert problems == ([] if want is None else [("warn", want)]) and (spec is None) == (want is not None)


# -- issuepost 위임 --------------------------------------------------------------------------------


def _cfg(**over) -> dict:
    tracker = {"mcp_server": "mock-jira", "tools": {"get_issue": READ}, "read_tools": [READ],
               "write_tools": {"add_comment": {"tool": SPEC["tool"], "key_arg": "ticket", "body_arg": "text"}}}
    tracker.update(over)
    return {"tracker": tracker}


def test_spec_check_carries_kind_and_uses_adapter_formats():
    spec, problems = issuepost.spec_check(_cfg())
    assert problems == [] and spec == SPEC
    assert issuepost.spec_tracker(spec) is J
    assert issuepost.call_arguments(spec, KEY, "본문\n") == {"ticket": KEY, "text": "본문"}
    spec2, problems2 = issuepost.spec_check(_cfg(write_tools={"add_comment": {**_cfg()["tracker"]["write_tools"]["add_comment"],
                                                                              "format": "adf"}}))
    assert spec2 is None and problems2 == [("warn", "add_comment.format은 jira-wiki|markdown 중 하나다: adf")]


def test_spec_check_bad_kind_disables_posting():
    spec, problems = issuepost.spec_check(_cfg(kind="nosuch"))
    assert spec is None and problems and "tracker.kind" in problems[0][1]
    assert issuepost.spec_check({"tracker": {"kind": "nosuch"}}) == (None, [])          # 게시 설정이 없으면 문제도 없다


def test_check_call_key_format_uses_adapter(tmp_path):
    assert issuepost.check_call(SPEC["tool"], {"ticket": "../x-1", "text": "x"}, SPEC, tmp_path) == "이슈 키 형식 불일치(ticket)"
    assert issuepost.check_call(SPEC["tool"], {"ticket": KEY, "text": "x", "other": 1}, SPEC, tmp_path) \
        == "승인 범위 밖 인자: other"
    assert issuepost.check_call(SPEC["tool"], {"ticket": KEY, "text": "x"}, SPEC, tmp_path) == f"승인 기록 없음({KEY})"


# -- 관문(서브프로세스) -----------------------------------------------------------------------------

_ROOTS: dict[str, Path] = {}
_WS: dict[str, Workspace] = {}


def tracker_root(name: str, files: dict[str, str]) -> Path:
    """`scripts/trackers/`에 모듈을 더한 플러그인 루트 복사본(서브프로세스는 monkeypatch가 닿지 않는다)."""
    if name not in _ROOTS:
        root = make_plugin_root.make(with_site_backend=True)
        for fname, body in files.items():
            (root / "scripts" / "trackers" / fname).write_text(body, encoding="utf-8")
        _ROOTS[name] = root
    return _ROOTS[name]


def ws(name: str = "plain", files: dict[str, str] | None = None) -> Workspace:
    if name not in _WS:
        _WS[name] = Workspace(root=tracker_root(name, files or {}))
        _WS[name].saved = (_WS[name].home / "config.yaml").read_text(encoding="utf-8")
    w = _WS[name]
    (w.home / "config.yaml").write_text(w.saved, encoding="utf-8")
    return w


def set_kind(w: Workspace, kind) -> None:
    data = yaml.safe_load(w.saved)
    data.setdefault("tracker", {})["kind"] = kind
    (w.home / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def guard(w: Workspace, tool: str, tool_input: dict) -> dict:
    event = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": str(w.base)}
    proc = run("guard.py", [], root=w.root, cwd=w.base, env=w.env(), stdin=json.dumps(event))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"] if proc.stdout.strip() else {}


def bridge(w: Workspace) -> str:
    issue = {"key": KEY, "fields": {"summary": SECRET, "description": "재현"}}
    event = {"hook_event_name": "PostToolUse", "tool_name": READ, "tool_input": {"ticket": KEY},
             "tool_response": json.dumps(issue, ensure_ascii=False)}
    proc = run("jira_bridge.py", [], root=w.root, cwd=w.base, env=w.env(), stdin=json.dumps(event, ensure_ascii=False))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]["updatedToolOutput"] if proc.stdout.strip() else ""


def snapshot(w: Workspace, db_cfg: Path = SAMPLE / "issue-db.config.yaml") -> None:
    snap = w.work / "_snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(db_cfg, snap / "issue-db.config.yaml")


def test_bad_tracker_kind_closes_every_gate():
    w = ws()
    set_kind(w, "nosuch")
    for tool, tool_input in ((READ, {"ticket": KEY}),                                    # 설정 서버 읽기도
                             ("mcp__corp-x__update_issue", {"key": KEY}),                 # 이름 휴리스틱 밖 쓰기
                             ("mcp__github__get_file_contents", {"owner": "a", "repo": "b"})):
        out = guard(w, tool, tool_input)
        assert out.get("permissionDecision") == "deny" and "트래커 설정 오류" in out["permissionDecisionReason"], tool
        assert "tracker.kind" in out["permissionDecisionReason"]
    text = bridge(w)
    assert "트래커 설정 오류" in text and SECRET not in text and "imsi" not in text
    snapshot(w)
    for script, args in (("triage.py", ["run", KEY, "--dry-run", "--issue-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", LOG]),
                         ("db_search.py", [KEY]),
                         ("jira_fields.py", ["check-key", KEY, "--db", SAMPLE]),
                         ("issue_post.py", ["status", KEY, "--json"])):
        proc = w.run(script, args)
        assert proc.returncode == 2 and "tracker.kind" in proc.stderr and "nosuch" in proc.stderr, (script, proc.stderr)
    rows = {r["check"]: r for r in w.json("config.py", ["doctor", "--format", "json"], expect=1)["rows"]}
    assert rows["tracker"]["status"] == "fail" and "tracker.kind" in rows["tracker"]["detail"] + rows["tracker"]["next"]
    assert w.run("config.py", ["show", "--keys", "work_dir"]).returncode == 0           # 고치는 길은 돈다
    assert w.run("config.py", ["set", "tracker.kind", "jira"]).returncode == 0
    assert guard(w, READ, {"ticket": KEY}).get("permissionDecision") is None             # 고치면 다시 허용


def test_tracker_mismatch_check_key_and_issue_post():
    w = ws("fakebug", {"fakebug.py": FAKE})
    snapshot(w)                                                                          # 스냅샷 DB는 jira(샘플)
    assert w.run("jira_fields.py", ["check-key", KEY, "--db", SAMPLE]).returncode == 0   # jira·jira: 그대로
    set_kind(w, "fakebug")
    for script, args in (("jira_fields.py", ["check-key", KEY, "--db", SAMPLE]),
                         ("issue_post.py", ["status", KEY, "--json"])):
        proc = w.run(script, args)
        assert proc.returncode == 2 and "tracker-mismatch" in proc.stderr and "이슈 DB 트래커는 jira" in proc.stderr, script
    # DB도 fakebug를 선언하면 맞다
    db = tmp("tt-fakebug-db-") / "db"
    shutil.copytree(SAMPLE, db)
    conf = db / "issue-db.config.yaml"
    conf.write_text(conf.read_text(encoding="utf-8").replace("  kind: jira\n", "  kind: fakebug\n"), encoding="utf-8")
    assert "kind: fakebug" in conf.read_text(encoding="utf-8")
    out = w.json("jira_fields.py", ["check-key", KEY, "--db", db])
    assert out == {"key": KEY, "valid": True, "regex": r"[A-Z][A-Z0-9]+-\d+"}
    snapshot(w, conf)
    proc = w.run("issue_post.py", ["status", KEY, "--json"])
    assert proc.returncode == 0 and "tracker-mismatch" not in proc.stderr, proc.stderr


def test_check_key_normalizes_and_rejects_unsafe_key():
    w = ws()
    assert w.json("jira_fields.py", ["check-key", KEY, "--db", SAMPLE])["key"] == KEY
    db = tmp("tt-loose-db-") / "db"
    shutil.copytree(SAMPLE, db)
    conf = db / "issue-db.config.yaml"
    text = conf.read_text(encoding="utf-8")
    conf.write_text(re.sub(r"key_regex: .*", "key_regex: '.+-\\\\d+'", text), encoding="utf-8")
    out = w.json("jira_fields.py", ["check-key", "../x-1", "--db", db], expect=1)        # DB 정규식이 넓어도 경로 안전 먼저
    assert out["valid"] is False and out["key"] == "../x-1"


def test_server_word_heuristic_is_union_of_installed_trackers():
    w = ws("fakebug", {"fakebug.py": FAKE})
    out = guard(w, "mcp__corp-bugzilla__update_bug", {"id": 1})                           # 설정은 jira여도 설치된 트래커 단어
    assert out.get("permissionDecision") == "deny" and "규칙 2" in out["permissionDecisionReason"]
    assert guard(w, "mcp__corp-bugzilla__get_bug", {"id": 1}).get("permissionDecision") is None   # 읽기형은 판정 없음
    assert guard(w, "mcp__x-atlassian__update_issue", {}).get("permissionDecision") == "deny"


def test_server_word_heuristic_keeps_builtin_with_broken_tracker():
    w = ws("broken", {"broken.py": "import no_such_dependency_xyz\n"})
    for tool in ("mcp__x-atlassian__update_issue", "mcp__probe-jira__jira_add_comment"):
        out = guard(w, tool, {})
        assert out.get("permissionDecision") == "deny" and "Jira/Atlassian" in out["permissionDecisionReason"], tool
    assert guard(w, READ, {"ticket": KEY}).get("permissionDecision") is None


# -- 리뷰 반영: 깨진 트래커·bridge 반환값·DB kind·키 형식·mismatch 경로·위임 -----------------------------

READ_ACTIONS = {   # 어댑터 read_action이 계약 밖의 값을 낼 때(core가 unsupported로 취급해 원문을 대체해야 한다)
    "runsup": 'lambda ti, mapped: "unsupported"',
    "rnone": "lambda ti, mapped: None",
    "rcomment": 'lambda ti, mapped: "add_comment"',
    "rraise": "lambda ti, mapped: (_ for _ in ()).throw(ValueError('x'))",
}


def _fake(name: str, **fields: str) -> str:
    extra = "".join(f", {k}={v}" for k, v in fields.items())
    return ("from dataclasses import replace\nimport trackers.jira as _jira\n"
            f"SPEC = replace(_jira.SPEC, name={name!r}, label={name.title()!r}{extra})\n")


def _db_copy(prefix: str, edit=None) -> Path:
    db = tmp(prefix) / "db"
    shutil.copytree(SAMPLE, db)
    if edit:
        conf = db / "issue-db.config.yaml"
        text = conf.read_text(encoding="utf-8")
        new = edit(text)
        assert new != text
        conf.write_text(new, encoding="utf-8")
    return db


def test_broken_configured_tracker_keeps_file_and_bash_rules():
    """kind로 고른 트래커 모듈이 깨져도(SyntaxError) MCP만 거부되고 파일·Bash 규칙은 평소 판정 그대로다(degraded로 약해지지 않음)."""
    w = ws("synbad", {"synbad.py": "SPEC = (\n"})
    approved = w.work / KEY / "post.approved.json"
    events = {"write_approved": ("Write", {"file_path": str(approved), "content": "{}"}),
              "write_clone": ("Write", {"file_path": str(w.clone / "README.md"), "content": "x"}),
              "push_main": ("Bash", {"command": f"git -C {w.clone} push origin main"})}
    before = {name: guard(w, tool, ti) for name, (tool, ti) in events.items()}
    set_kind(w, "synbad")
    for name, (tool, ti) in events.items():
        got = guard(w, tool, ti)
        assert got.get("permissionDecision") == before[name].get("permissionDecision") == "deny", (name, got)
        assert got["permissionDecisionReason"] == before[name]["permissionDecisionReason"], name
        assert "내부 오류" not in got["permissionDecisionReason"]
    out = guard(w, READ, {"ticket": KEY})
    assert out.get("permissionDecision") == "deny" and "SyntaxError" in out["permissionDecisionReason"]
    assert "트래커 설정 오류" in bridge(w)
    for script, args in (("jira_fields.py", ["check-key", KEY, "--db", SAMPLE]), ("db_search.py", [KEY])):
        proc = w.run(script, args)
        assert proc.returncode == 2 and "SyntaxError" in proc.stderr and "Traceback" not in proc.stderr, (script, proc.stderr)


@pytest.mark.parametrize("name", sorted(READ_ACTIONS))
def test_bridge_read_action_outside_contract_replaces_raw(name):
    w = ws("readact", {f"{n}.py": _fake(n, read_action=v) for n, v in READ_ACTIONS.items()})
    set_kind(w, name)
    text = bridge(w)
    assert "지원하지 않는 읽기" in text and SECRET not in text and "imsi" not in text, (name, text)
    assert not (w.work / KEY / "post.result.json").exists()


def test_db_tracker_kind_error_stops_db_tools():
    w = ws()
    db = _db_copy("tt-badkind-", lambda t: t.replace("  kind: jira\n", "  kind: nosuch\n"))
    for script, args in (("db_build.py", ["--db", db, "--preview", tmp("tt-prev-")]),
                         ("db_search.py", ["--db", db, "MOCK-1101"]),
                         ("db_add.py", ["apply", REPO / "tests" / "fixtures" / "plans" / "p7-analyze-append.plan.json",
                                        "--db", db, "--user", "mock-user1"])):
        proc = w.run(script, args)
        assert proc.returncode == 2 and "이슈 DB tracker.kind" in proc.stderr and "nosuch" in proc.stderr, (script, proc.stderr)
    lint = json.loads(w.run("db_lint.py", ["--db", db, "--all"]).stdout)
    assert any(e["code"] == "config" and "tracker.kind" in e["message"] for e in lint["errors"]), lint["errors"]


def test_record_key_must_be_tracker_work_key():
    """DB key_regex가 넓어도 기록 키는 DB 트래커의 작업 키 형식이어야 한다(파일 이름이 된다): db_lint issue-key, db_add reject."""
    w = ws()
    db = _db_copy("tt-loosekey-", lambda t: re.sub(r"key_regex: .*", "key_regex: '.+-[0-9]+'", t))
    src = next(db.glob("data/*/issues/MOCK-1101.yaml"))
    bad = src.with_name("org.repo-1.yaml")
    bad.write_text(src.read_text(encoding="utf-8").replace("MOCK-1101", "org.repo-1"), encoding="utf-8")
    src.unlink()
    lint = json.loads(w.run("db_lint.py", ["--db", db, "--all"]).stdout)
    hits = [e for e in lint["errors"] if e["code"] == "issue-key"]
    assert hits and "작업 키 형식" in hits[0]["message"] and "org.repo-1" in hits[0]["message"], lint["errors"]
    plan = json.loads((REPO / "tests" / "fixtures" / "plans" / "p7-analyze-append.plan.json").read_text(encoding="utf-8"))
    plan["issue"]["key"] = "org.repo-2"
    path = tmp("tt-plan-") / "p.plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    proc = w.run("db_add.py", ["apply", path, "--db", db, "--user", "mock-user1"])
    assert proc.returncode != 0 and "issue-key" in proc.stdout + proc.stderr and "작업 키 형식" in proc.stdout + proc.stderr, \
        (proc.stdout[-800:], proc.stderr[-800:])


def test_tracker_mismatch_on_triage_extract_and_offline():
    w = ws("fakebug", {"fakebug.py": FAKE})
    shutil.rmtree(w.work / "_snapshot", ignore_errors=True)        # 앞 테스트의 가짜 스냅샷(설정 파일만)은 worktree가 아니다
    set_kind(w, "fakebug")
    cases = {
        "triage": ["run", KEY, "--dry-run", "--issue-file", MOCK_JIRA / f"{KEY}.yaml", "--logs", LOG],
        "extract": ["extract", MOCK_JIRA / f"{KEY}.yaml", "--origin", "file", "--db", SAMPLE],
        "offline": ["run", KEY, "--offline-db", SAMPLE, "--out", tmp("tt-off-") / "out", "--logs", LOG,
                    "--issue-file", MOCK_JIRA / f"{KEY}.yaml", "--tz", "Asia/Seoul", "--year", "2026"],
    }
    for name, args in cases.items():
        proc = w.run("jira_fields.py" if name == "extract" else "triage.py", args)
        assert proc.returncode == 2 and "tracker-mismatch" in proc.stdout + proc.stderr, (name, proc.stdout[-500:], proc.stderr[-500:])
        w.run("triage.py", ["release", KEY])


def test_issue_post_without_snapshot_checks_clone_or_stops():
    w = ws("fakebug", {"fakebug.py": FAKE})
    shutil.rmtree(w.work / "_snapshot", ignore_errors=True)
    assert w.run("issue_post.py", ["status", KEY, "--json"]).returncode == 0          # jira·jira(clone 선언)
    set_kind(w, "fakebug")
    proc = w.run("issue_post.py", ["status", KEY, "--json"])
    assert proc.returncode == 2 and "tracker-mismatch" in proc.stderr                  # 스냅샷 없으면 clone 선언과 대조
    data = yaml.safe_load(w.saved)
    data["issue_db"]["path"] = str(tmp("tt-noclone-"))
    data.setdefault("tracker", {})["kind"] = "jira"
    (w.home / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    proc = w.run("issue_post.py", ["status", KEY, "--json"])
    assert proc.returncode == 2 and "대조할 수 없다" in proc.stderr, proc.stderr          # 둘 다 없으면 fail-closed


def test_check_key_without_db_uses_session_tracker(fake_trackers, monkeypatch):
    import jira_fields
    fake_trackers("strict", _fake("strict", default_key_regex='r"ZZ-[0-9]+"'))
    assert jira_fields.key_regex(None, {"tracker": {"kind": "strict"}}).pattern == "ZZ-[0-9]+"
    assert jira_fields.key_regex(None, {}).pattern == J.default_key_regex
    assert jira_fields.key_regex(SAMPLE, {"tracker": {"kind": "strict"}}).pattern == r"[A-Z][A-Z0-9]+-\d+"   # DB 값이 먼저


def test_tracker_candidates_delegates_classify_extra():
    w = ws("cand", {"candbug.py": _fake("candbug",
                                        classify_extra='lambda tool, a: (a | {"get_comments"}) if "get_issue" in a else a')})
    tools = tmp("tt-tools-") / "tools.json"
    tools.write_text(json.dumps({"srv": ["fetch_ticket"]}), encoding="utf-8")
    args = ["tracker-candidates", "--tools-json", tools, "--mcp-config", tmp("tt-nomcp-") / "none.json"]
    got = {}
    for kind in ("jira", "candbug"):
        set_kind(w, kind)
        srv = next(s for s in w.json("config.py", args)["servers"] if s["server"] == "srv")
        got[kind] = srv["tracker_tools"]
    assert got["jira"]["get_issue"] == ["mcp__srv__fetch_ticket"] and got["jira"]["get_comments"] == []
    assert got["candbug"]["get_comments"] == ["mcp__srv__fetch_ticket"]


def test_guard_selftest_uses_tracker_key_args(fake_trackers, monkeypatch):
    import config
    fake_trackers("refbug", _fake("refbug", key_args='lambda spec, key: {"issue_ref": key}'))
    seen = []

    class Proc:
        returncode, stderr = 0, ""
        stdout = json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                    "permissionDecisionReason": "x"}})

    monkeypatch.setattr(config.subprocess, "run", lambda *a, **kw: seen.append(json.loads(kw["input"])) or Proc())
    cfg = _cfg(kind="refbug")
    row = config._guard_selftest(type("A", (), {"plugin_root": str(REPO / "plugin")})(), None, cfg)
    assert row["status"] == "ok"
    assert seen[-1]["tool_input"] == {"issue_ref": "SELFTEST-0", "text": "selftest"}
