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


# -- GitHub 어댑터 (묶음 3, 설계 §3-2 github 열·§3-4) ------------------------------------------------

from trackers import github as github_tracker  # noqa: E402

G = trackers.get("github")
GKEY = "mock-org.mock-issues-12"
GSPEC = {"tool": "mcp__mock-github-issues__add_issue_comment", "key_arg": None, "body_arg": "body", "extra_args": {},
         "format": "markdown", "kind": "github"}
GARGS = {"owner": "mock-org", "repo": "mock-issues", "issue_number": 12}


def test_github_registered_and_constants():
    assert "github" in trackers.known() and G.name == "github" and G.label == "GitHub"
    assert G.server_words == ()                       # "github"를 넣으면 설정 밖 GitHub MCP 쓰기가 모두 거부된다(설계 §4-3)
    assert trackers.all_server_words() == ("atlassian", "jira")
    assert G.formats == ("markdown",) and G.default_format == "markdown" and set(G.formats) <= set(issuepost.RENDERERS)
    assert dict(G.text_defaults) == {"summary": ("title",), "description": ("body",), "comments": ("comments[].body",)}
    assert G.components_default == "labels[].name"
    assert G.safe_key_re.fullmatch(G.selftest_key) and J.safe_key_re.fullmatch(J.selftest_key)
    assert re.fullmatch(G.default_key_regex, GKEY) and not re.fullmatch(G.default_key_regex, "MOCK-1")


@pytest.mark.parametrize("text,want", [
    (GKEY, GKEY), ("Mock-Org.Mock-Issues-12", GKEY),                                    # 작업 키(소문자 정규화)
    ("mock-org/mock-issues#12", GKEY), ("Mock-Org/Mock-Issues#12", GKEY),               # owner/repo#N
    ("https://ghe.mock.invalid/mock-org/mock-issues/issues/12", GKEY),                  # 이슈 URL
    ("https://ghe.mock.invalid/mock-org/mock-issues/issues/12/", GKEY),
    ("https://ghe.mock.invalid/mock-org/mock-issues/issues/12#issuecomment-1", GKEY),
    ("http://ghe.mock.invalid/mock-org/my.repo_x/issues/3?x=1", "mock-org.my.repo_x-3"),
    ("MOCK-12", None), ("../x-1", None), ("a..b-1", None), ("o.a..b-1", None), ("o/a..b#1", None),
    ("o/r#0", None), ("o/r#012", None), ("o.r-0", None), ("own.er/r#1", None), ("o/.github#1", None),
    ("o/r/x#1", None), ("o r/x#1", None), ("o/r#1#2", None), ("https://ghe.mock.invalid/o/r/pull/1", None),
    ("o/r#12345678901", None), ("", None), (None, None), (12, None),
])
def test_github_parse_key(text, want):
    assert G.parse_key(text) == want
    if want is not None:
        assert G.safe_key_re.fullmatch(want) and want == want.lower()


def test_github_display_link_key_args_round_trip():
    assert G.display(GKEY) == "mock-org/mock-issues#12"
    assert G.link("https://ghe.mock.invalid/", GKEY) == "https://ghe.mock.invalid/mock-org/mock-issues/issues/12"
    assert G.display("not a key") == "not a key" and G.link("https://ghe.mock.invalid/", "x") == "https://ghe.mock.invalid/x"    # 표시만: 예외 없음
    assert G.key_args(GSPEC, GKEY) == GARGS and G.key_args({}, "a.b.c-1") == {"owner": "a", "repo": "b.c", "issue_number": 1}
    with pytest.raises(ValueError):
        G.key_args({}, "MOCK-1")
    assert G.arg_names(GSPEC) == {"owner", "repo", "issue_number"} and G.key_arg_id(GSPEC) == "owner,repo,issue_number"
    assert G.key_from_args(GSPEC, {**GARGS, "body": "x"}) == GKEY
    assert G.key_from_args({}, {"owner": "Mock-Org", "repo": "MOCK-Issues", "issue_number": 12}) == GKEY   # 소문자 정규화
    assert G.key_from_args(GSPEC, G.key_args(GSPEC, GKEY)) == GKEY


@pytest.mark.parametrize("over", [
    {"issue_number": "12"}, {"issue_number": 12.0}, {"issue_number": True}, {"issue_number": 0}, {"issue_number": -1},
    {"issue_number": None}, {"issue_number": 10 ** 10}, {"owner": "mock.org"}, {"owner": "../x"}, {"owner": "a/b"},
    {"owner": "-x"}, {"owner": ""}, {"owner": "x" * 40}, {"owner": 1}, {"repo": "a..b"}, {"repo": ".github"},
    {"repo": "a/b"}, {"repo": "a#b"}, {"repo": "a b"}, {"repo": ""}, {"repo": None},
])
def test_github_key_from_args_rejects(over):
    assert G.key_from_args(GSPEC, {**GARGS, **over}) is None, over


def test_github_key_from_args_needs_all_args():
    for missing in GARGS:
        assert G.key_from_args(GSPEC, {k: v for k, v in GARGS.items() if k != missing}) is None
    assert G.key_from_args(GSPEC, None) is None and G.key_from_args(GSPEC, [GARGS]) is None


def test_jira_and_github_key_formats_do_not_overlap():
    for key in ("MOCK-1001", "A_B-1", "abc-1"):
        assert J.safe_key_re.fullmatch(key) and not G.safe_key_re.fullmatch(key) and G.parse_key(key) is None
    for key in (GKEY, "o.r-1", "a1.b_c.d-99"):
        assert G.safe_key_re.fullmatch(key) and not J.safe_key_re.fullmatch(key) and J.parse_key(key) is None


def test_github_read_action_key_from_read_read_args_classify():
    both = {"get_issue", "get_comments"}
    assert G.read_action({"method": "get", **GARGS}, both) == "get_issue"
    assert G.read_action({"method": "get_comments", **GARGS}, both) == "get_comments"
    for ti in ({"method": "get_labels", **GARGS}, {"method": 1}, GARGS, None):
        assert G.read_action(ti, both) == "unsupported", ti
    kre = re.compile(r"mock-org\.mock-issues-\d+")
    assert G.key_from_read({"title": "x"}, {"method": "get", **GARGS}, kre) == GKEY        # 응답이 아니라 입력에서
    assert G.key_from_read({"key": GKEY}, {"method": "get", "owner": "other", "repo": "x", "issue_number": 1}, kre) is None
    assert G.key_from_read({}, {"method": "get", **GARGS, "issue_number": "12"}, kre) is None
    assert G.read_args("get_issue", GKEY) == {"method": "get", **GARGS}
    assert G.read_args("get_comments", GKEY) == {"method": "get_comments", **GARGS}
    assert G.read_args("search_issues", GKEY) is None
    assert G.classify_extra("issue_read", {"get_issue"}) == {"get_issue", "get_comments"}
    assert G.classify_extra("mcp__srv__issue_read", {"get_issue"}) == {"get_issue", "get_comments"}
    assert G.classify_extra("get_issue", {"get_issue"}) == {"get_issue"}
    assert G.classify_extra("issue_read", set()) == set()


GKEYARG = "add_comment.key_arg는 github 트래커에서 두지 않는다(키 인자는 owner·repo·issue_number 고정)"


@pytest.mark.parametrize("raw,want", [
    ({"body_arg": "body"}, []), ({"key_arg": None, "body_arg": "body"}, []), ({"key_arg": "", "body_arg": "body"}, []),
    ({"key_arg": "ticket", "body_arg": "body"}, [GKEYARG]),
    ({"body_arg": "issue_number"}, ["add_comment.body_arg가 키 인자(owner·repo·issue_number)와 겹친다"]),
])
def test_github_spec_problems(raw, want):
    assert G.spec_problems(raw) == want


def _gcfg(**over) -> dict:
    read = "mcp__mock-github-issues__issue_read"
    tracker = {"kind": "github", "mcp_server": "mock-github-issues", "tools": {"get_issue": read, "get_comments": read},
               "read_tools": [read], "write_tools": {"add_comment": {"tool": GSPEC["tool"], "body_arg": "body"}}}
    tracker.update(over)
    return {"tracker": tracker}


@pytest.mark.parametrize("ac,want", [
    ({}, None),
    ({"format": "jira-wiki"}, "add_comment.format은 markdown 중 하나다: jira-wiki"),
    ({"key_arg": "ticket"}, GKEYARG),
    ({"extra_args": {"owner": "x"}}, EXTRA),               # 공통 검사: 고정 인자가 키 인자를 덮어쓰지 못한다(P2-6)
    ({"extra_args": {"issue_number": 1}}, EXTRA),
    ({"extra_args": {"body": "x"}}, EXTRA),
    ({"body_arg": None}, KEYBODY),
])
def test_github_spec_check(ac, want):
    raw = {"tool": GSPEC["tool"], "body_arg": "body", **ac}
    spec, problems = issuepost.spec_check(_gcfg(write_tools={"add_comment": raw}))
    if want is None:
        assert problems == [] and spec == GSPEC and issuepost.spec_tracker(spec) is G
        assert issuepost.call_arguments(spec, GKEY, "본문 \n") == {**GARGS, "body": "본문"}
    else:
        assert spec is None and problems == [("warn", want)]


def _approval(job: Path, spec: dict, key: str, body: str, **over) -> None:
    at = issuepost.now()
    record = {"schema": 1, "key": key, "tool": spec["tool"], "key_arg": issuepost.spec_tracker(spec).key_arg_id(spec),
              "kind": spec["kind"], "body_sha256": issuepost.body_sha256(body), "approved_at": issuepost.iso(at),
              "expires_at": issuepost.iso(issuepost.expires(at)), "used_at": None, **over}
    (job / key).mkdir(parents=True, exist_ok=True)
    (job / key / "post.approved.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    (job / key / "post.md").write_text(body + "\n", encoding="utf-8")


def test_github_check_call(tmp_path):
    body = "### PROBLEM\n- GitHub: mock-org/mock-issues#12"
    call = {**GARGS, "body": body}
    assert issuepost.check_call(GSPEC["tool"], call, GSPEC, tmp_path) == f"승인 기록 없음({GKEY})"
    _approval(tmp_path, GSPEC, GKEY, body)
    assert issuepost.check_call(GSPEC["tool"], call, GSPEC, tmp_path) is None
    assert issuepost.check_call(GSPEC["tool"], {**call, "owner": "Mock-Org"}, GSPEC, tmp_path) is None   # 대소문자 무관
    for bad, why in (({**call, "issue_number": "12"}, "이슈 키 형식 불일치(owner,repo,issue_number)"),
                     ({**call, "issue_number": 13}, "승인 기록 없음(mock-org.mock-issues-13)"),
                     ({**call, "reaction": "+1"}, "승인 범위 밖 인자: reaction"),
                     ({**call, "comment_id": 1}, "승인 범위 밖 인자: comment_id"),
                     ({k: v for k, v in call.items() if k != "repo"}, "이슈 키 형식 불일치(owner,repo,issue_number)")):
        assert issuepost.check_call(GSPEC["tool"], bad, GSPEC, tmp_path) == why, bad


def test_approval_record_kind_must_match_spec(tmp_path):
    """P2-5: 승인 기록의 트래커 kind가 지금 설정과 같아야 한다(키 형식·key_arg가 우연히 같아도). 옛 기록(kind 없음)도 거부."""
    body = "h3. PROBLEM"
    call = {"ticket": KEY, "text": body}
    _approval(tmp_path, SPEC, KEY, body)
    assert issuepost.check_call(SPEC["tool"], call, SPEC, tmp_path) is None
    for kind in ("github", None):
        _approval(tmp_path, SPEC, KEY, body, kind=kind)
        assert issuepost.check_call(SPEC["tool"], call, SPEC, tmp_path) == "승인 기록의 트래커(kind)가 설정과 다르다", kind
    rec = json.loads((tmp_path / KEY / "post.approved.json").read_text(encoding="utf-8"))
    del rec["kind"]
    (tmp_path / KEY / "post.approved.json").write_text(json.dumps(rec), encoding="utf-8")
    assert "옛 형식 승인 기록" in issuepost.check_call(SPEC["tool"], call, SPEC, tmp_path)   # 리뷰 P2-6: 설정 오류와 구별


# -- GitHub 관문(서브프로세스): check-key 정규화·tracker-mismatch·driver 작업 키(P2-9)·skeleton -------------

from runner import github_root, variant_db  # noqa: E402

GH_LOG = SAMPLE / "data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.log"
GH_URL = "https://ghe.mock.invalid/mock-org/mock-issues/issues/12"
GH_ISSUES = REPO / "tests" / "mocks" / "github_issues"
_GWS: dict[str, Workspace] = {}


def gws(db: str = "issue-db-github") -> Workspace:
    """site-defaults 트래커가 github인 작업공간(사용자 clone = `db`)."""
    if db not in _GWS:
        _GWS[db] = Workspace(src=variant_db(db) if db != "issue-db-sample" else SAMPLE, root=github_root())
    return _GWS[db]


def test_github_check_key_normalizes_inputs():
    w = gws()
    for text in (GH_URL, "mock-org/mock-issues#12", "Mock-Org.Mock-Issues-12", GKEY):
        out = w.json("jira_fields.py", ["check-key", text, "--db", w.clone])
        assert out == {"key": GKEY, "valid": True, "regex": r"mock-org\.mock-issues-\d+"}, text
    out = w.json("jira_fields.py", ["check-key", "other-org/mock-issues#12", "--db", w.clone], expect=1)   # DB 정규식 밖
    assert out["valid"] is False and out["key"] == "other-org.mock-issues-12"
    out = w.json("jira_fields.py", ["check-key", "MOCK-1001", "--db", w.clone], expect=1)            # jira 키는 작업 키가 아니다
    assert out == {"key": "MOCK-1001", "valid": False, "regex": r"mock-org\.mock-issues-\d+"}


def test_github_session_with_jira_db_is_tracker_mismatch():
    w = gws("issue-db-sample")
    for script, args in (("jira_fields.py", ["check-key", GH_URL, "--db", SAMPLE]),
                         ("jira_fields.py", ["extract", GH_ISSUES / f"{GKEY}.yaml", "--origin", "file", "--db", SAMPLE]),
                         ("triage.py", ["run", GH_URL, "--dry-run", "--issue-file", GH_ISSUES / f"{GKEY}.yaml",
                                        "--logs", GH_LOG]),
                         ("issue_post.py", ["status", GKEY, "--json"])):
        proc = w.run(script, args)
        assert proc.returncode == 2 and "tracker-mismatch" in proc.stdout + proc.stderr, (script, proc.stderr[-400:])
        assert "이슈 DB 트래커는 jira, 설정 tracker.kind는 github" in proc.stdout + proc.stderr
        w.run("triage.py", ["release", GKEY])
    jira_ws = ws()                                                    # jira 세션 × github DB
    proc = jira_ws.run("jira_fields.py", ["check-key", KEY, "--db", variant_db("issue-db-github")])
    assert proc.returncode == 2 and "이슈 DB 트래커는 github, 설정 tracker.kind는 jira" in proc.stderr


def test_driver_uses_normalized_work_key():
    """P2-9: triage.py run에 URL을 줘도 작업 디렉토리·lock·출력 키는 check-key의 작업 키다(`/`가 하위 디렉토리가 되지 않는다)."""
    w = gws()
    args = ["run", GH_URL, "--dry-run", "--issue-file", GH_ISSUES / f"{GKEY}.yaml", "--logs", GH_LOG, "--code", "skip",
            "--answer", "time=2026-09-20T05:30:04.900Z"]
    out = w.json("triage.py", args)
    assert out["key"] == GKEY and out["status"] == "ok", out
    assert (w.work / GKEY / "analysis.json").is_file() and not (w.work / "https:").exists()
    analysis = json.loads((w.work / GKEY / "analysis.json").read_text(encoding="utf-8"))
    assert analysis["key"] == GKEY
    assert sorted(p.name for p in w.work.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))) == [GKEY]



def test_release_and_explore_use_work_key():
    """리뷰 P2-2: release·explore도 작업 키로 정규화한다(URL로 release해도 lock이 풀린다). 경로 안전 형식이 아니면(`..`) 거부."""
    w = gws()
    args = ["run", GH_URL, "--dry-run", "--issue-file", GH_ISSUES / f"{GKEY}.yaml", "--logs", GH_LOG, "--code", "skip",
            "--answer", "time=2026-09-20T05:30:04.900Z"]
    w.json("triage.py", args)
    out = w.json("triage.py", ["release", GH_URL])
    assert out.get("released") is True, out
    for bad in ("..", "mock-org/../x#1"):
        assert w.json("triage.py", ["release", bad]) == {"released": False, "note": "작업 디렉토리 없음"}
        assert w.run("triage.py", ["explore", bad]).returncode == 2, bad
    assert ws().run("triage.py", ["explore", ".."]).returncode == 2           # jira도 같다(이전에는 work_dir/..를 JOB으로 봤다)

def test_make_db_skeleton_tracker_option():
    import subprocess
    out = tmp("tt-skel-gh-")
    proc = subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out / "gh"), "--tracker", "github",
                           "--json"], capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["tracker"] == "github"
    conf = yaml.safe_load((out / "gh" / "issue-db.config.yaml").read_text(encoding="utf-8"))
    assert conf["tracker"]["kind"] == "github" and conf["tracker"]["key_regex"] == G.default_key_regex
    lint = json.loads(run("db_lint.py", ["--db", out / "gh", "--all"]).stdout)
    assert lint["errors"] == [], lint["errors"]
    for args in (["--tracker", "jira"], []):                          # jira는 옵션 없을 때와 같다
        subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out / f"j{len(args)}"), *args],
                       check=True, capture_output=True)
    assert (out / "j2" / "issue-db.config.yaml").read_bytes() == (out / "j0" / "issue-db.config.yaml").read_bytes()
    bad = subprocess.run([sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out / "x"), "--tracker", "nosuch"],
                         capture_output=True, text=True, encoding="utf-8")
    assert bad.returncode != 0 and "지원 트래커" in bad.stderr
