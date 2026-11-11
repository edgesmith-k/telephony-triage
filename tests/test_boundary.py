#!/usr/bin/env python3
"""사외/사내 경계 시험 (ARCHITECTURE_REVIEW_2026-10.md RF-2).

- `tools/check_boundary.py`: 이 레포는 위반 0건, 일부러 넣은 위반은 규칙마다 잡고,
  예외 파일·사내 패턴 파일이 동작한다.
- `tools/import_draft.py`: staging 단계 실패·활성 전환 뒤 검증 실패는 사내 레포를
  그대로 두고, `--check-boundary` 위반이면 반입하지 않으며, 같은 초안을 두 번
  반입하면 기준선 해시가 같다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
CHECK = TOOLS / "check_boundary.py"
IMPORT = TOOLS / "import_draft.py"

SITE_PATHS_TEXT = "SITE_PROFILE.md\n.draft-manifest.json\ndocs/site/\nplugin/site-defaults.yaml\n" \
                  "plugin/scripts/parser_backends/site/\nplugin/scripts/adapters/site_*\n"


sys.path.insert(0, str(TOOLS))
import check_boundary as boundary  # noqa: E402
import import_draft as draft  # noqa: E402


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(tool: Path, *args: str) -> tuple[int, dict | str]:
    result = subprocess.run([sys.executable, str(tool), *args], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    try:
        return result.returncode, json.loads(result.stdout)
    except ValueError:
        return result.returncode, result.stdout + result.stderr


def _rules(findings) -> set[tuple[str, str]]:
    return {(f.rule, f.path) for f in findings}


# ---------------------------------------------------------------- check_boundary


def test_repo_has_no_boundary_violations():
    code, out = _run(CHECK, "--root", str(REPO), "--json")
    assert code == 0, out
    assert out["violations"] == []


def test_site_paths_and_gitignore_cover_local_files():
    """R-22: 루트 마켓플레이스는 사내 소유, 로컬 환경 파일은 무시, plugin.json에 version 없음."""
    patterns = boundary.load_site_paths(REPO)
    assert draft.is_site_path(".claude-plugin/marketplace.json", patterns)
    assert not draft.is_site_path("plugin/.claude-plugin/plugin.json", patterns)
    for rel in (".venv/x", "build/x", "dist/x", ".claude/settings.local.json"):
        proc = subprocess.run(["git", "-C", str(REPO), "-c", "core.excludesFile=" + os.devnull,
                               "check-ignore", "-q", "--no-index", rel])
        assert proc.returncode == 0, rel
    # 실제 플러그인만 본다 (모의 플러그인 tests/mocks/plugin-probe 등은 version을 둔다).
    assert "version" not in json.loads((REPO / "plugin/.claude-plugin/plugin.json").read_text(encoding="utf-8"))


def test_no_tracked_file_matches_ignore_rules():
    """무시 규칙이 추적 파일(예: fixture의 build/)을 덮으면 반입 목록(walk)에서 빠진다."""
    out = subprocess.run(["git", "-C", str(REPO), "-c", "core.excludesFile=" + os.devnull,
                          "ls-files", "-ci", "--exclude-standard"],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == ""


def test_external_workflow_only_on_github_com():
    """R-24: 사외 CI는 github.com에서만 돈다 (사내 GHE에서 대기·실패하지 않게)."""
    jobs = yaml.safe_load((REPO / ".github/workflows/external.yml").read_text(encoding="utf-8"))["jobs"]
    assert {"boundary", "test", "site-rehearsal"} <= set(jobs)
    assert all(job.get("if") == "github.server_url == 'https://github.com'" for job in jobs.values()), jobs


@pytest.fixture
def fake_repo(tmp_path):
    root = tmp_path / "repo"
    _write(root, "SITE_PATHS", SITE_PATHS_TEXT)
    _write(root, "plugin/scripts/ok.py", "from common import site_defaults\nimport adapters\n")
    _write(root, "docs/notes.md", "모의 서버 https://ghe.mock-corp.invalid/org 와 192.0.2.10\n")
    return root


def test_clean_fake_repo_passes(fake_repo):
    assert boundary.scan(fake_repo, "external") == []


@pytest.mark.parametrize("markers, mode", [
    ((), "external"),
    ((".draft-manifest.json",), "site"),
    (("SITE_PROFILE.md",), "site"),
    ((".local-draft", ".draft-manifest.json"), "external"),
])
def test_detect_mode(tmp_path, markers, mode):
    for name in markers:
        _write(tmp_path, name, "{}\n")
    assert boundary.detect_mode(tmp_path) == mode


def test_cli_default_mode_in_site_repo(fake_repo):
    # R-1: 반입(.draft-manifest.json)·S-1(SITE_PROFILE.md)·S-3(site-defaults.yaml) 뒤 사내 레포.
    # 인자 없는 호출(test_repo_has_no_boundary_violations, related_tests --run)은 site로 통과해야 한다.
    for rel in (".draft-manifest.json", "SITE_PROFILE.md", "plugin/site-defaults.yaml"):
        _write(fake_repo, rel, "{}\n")
    code, out = _run(CHECK, "--root", str(fake_repo), "--json")
    assert code == 0, out
    assert out == {"mode": "site", "violations": []}

    code, out = _run(CHECK, "--root", str(fake_repo), "--mode", "external", "--json")
    assert code == 1, out
    assert {(v["rule"], v["path"]) for v in out["violations"]} == {
        ("site-path", "SITE_PROFILE.md"), ("site-path", "plugin/site-defaults.yaml")}


def test_cli_default_mode_external_without_markers(fake_repo):
    code, out = _run(CHECK, "--root", str(fake_repo), "--json")
    assert code == 0, out
    assert out["mode"] == "external"


def test_each_rule_reports_injected_violation(fake_repo):
    _write(fake_repo, "docs/leak.md", "\n".join([
        "-----BEGIN RSA PRIVATE KEY-----",
        "host https://build.realcorp.co.kr/job",
        "contact kim@realcorp.co.kr",
        "server 52.14.200.7",
        "imei 359881234567812",
        "api_key = abcdefghijklmnopqrstuvwxyz012345",
    ]))
    _write(fake_repo, "plugin/scripts/bad.py", "from parser_backends.site import backend\n")
    _write(fake_repo, "plugin/scripts/platforms/android/bad.py", "from parser_backends.site import backend\n")
    _write(fake_repo, "plugin/scripts/adapters/uses.py", "from . import site_data_x\n")
    _write(fake_repo, "tests/fixtures/issue-db-x/data/DATA-001-x/fixtures/DATA-001-01.log", "log\n")
    _write(fake_repo, "tests/fixtures/issue-db-x/data/DATA-001-x/fixtures/DATA-001-01.expect.yaml",
           "expect_top: DATA-001-01\n")
    _write(fake_repo, "tests/fixtures/logs/unknown.log", "log\n")
    _write(fake_repo, "plugin/site-defaults.yaml", "schema: 1\n")

    found = _rules(boundary.scan(fake_repo, "external"))
    for rule in ("private-key", "url-host", "email", "ip-address", "long-number", "secret-assign"):
        assert (f"pattern:{rule}", "docs/leak.md") in found, rule
    assert ("site-import", "plugin/scripts/bad.py") in found
    assert ("site-import", "plugin/scripts/platforms/android/bad.py") in found
    assert ("site-import", "plugin/scripts/adapters/uses.py") in found
    assert ("fixture-origin", "tests/fixtures/issue-db-x/data/DATA-001-x/fixtures/DATA-001-01.log") in found
    assert ("fixture-origin", "tests/fixtures/logs/unknown.log") in found
    assert ("site-path", "plugin/site-defaults.yaml") in found
    # 사내 모드에서는 SITE_PATHS 파일이 있는 것이 정상이고, 그 내용은 검사하지 않는다
    assert "site-path" not in {rule for rule, _ in _rules(boundary.scan(fake_repo, "site"))}

    code, out = _run(CHECK, "--root", str(fake_repo), "--json")
    assert code == 1 and out["violations"]


def test_values_glued_to_hangul_are_reported(fake_repo):
    """값 경계는 ASCII다: 한글 조사가 붙은 IP·15자리·이메일(`52.14.200.7은`)도 위반이다."""
    _write(fake_repo, "docs/leak.md", "서버52.14.200.7은 사내\n단말359881234567812로\n담당kim@realcorp.co.kr으로\n")
    found = _rules(boundary.scan(fake_repo, "external"))
    for rule in ("ip-address", "long-number", "email"):
        assert (f"pattern:{rule}", "docs/leak.md") in found, rule


def test_fullwidth_digits_and_nbsp_are_reported(fake_repo):
    """패턴은 ASCII지만 줄을 접어서 본다: 전각 15자리·전각 숫자 IP, NBSP로 띄운 인증 헤더도 위반이다."""
    fw = str.maketrans("0123456789", "".join(chr(0xff10 + n) for n in range(10)))
    nb = chr(0xa0)
    _write(fake_repo, "docs/leak.md", "단말 " + "359881234567812".translate(fw) + "\n서버 " + "52.14.200.7".translate(fw)
           + f"\nAuthorization:{nb}Bearer{nb}abcdEFGH1234ijklMNOP5678\n")
    found = _rules(boundary.scan(fake_repo, "external"))
    for rule in ("long-number", "ip-address", "auth-header"):
        assert (f"pattern:{rule}", "docs/leak.md") in found, rule


def test_synthetic_marks_and_registries_pass(fake_repo):
    fixtures = "tests/fixtures/issue-db-x/data/DATA-001-x/fixtures"
    _write(fake_repo, f"{fixtures}/DATA-001-01.log", "log\n")
    _write(fake_repo, f"{fixtures}/DATA-001-01.expect.yaml", "expect_top: DATA-001-01\norigin: synthetic\n")
    _write(fake_repo, "tests/fixtures/logs/data-connected.log", "log\n")
    _write(fake_repo, "tests/mocks/log_fixtures.yaml", "fixtures:\n  - {name: data-connected, scenario: x}\n")
    _write(fake_repo, "tests/verify-logs/fixed.log", "log\n")
    _write(fake_repo, "tests/verify-logs/README.md", "- `fixed.log` 합성\n")
    assert boundary.scan(fake_repo, "external") == []



def test_module_template_log_needs_synthetic_case(fake_repo):
    """모듈 스킬 템플릿 로그(MODULE_SKILLS_PLAN_IMPL §5.1): evals/<case>/files/ 아래이고 case.yaml에 synthetic: true."""
    base = "templates/module-skills/ofono/data/evals"
    _write(fake_repo, f"{base}/ok/case.yaml", "schema_version: 1\nname: ok\nsynthetic: true\n")
    _write(fake_repo, f"{base}/ok/files/source.log", "-- [합성] x\n")
    _write(fake_repo, f"{base}/notsyn/case.yaml", "schema_version: 1\nsynthetic: false\n")
    _write(fake_repo, f"{base}/notsyn/files/source.log", "-- [합성] x\n")
    _write(fake_repo, f"{base}/nocase/files/source.log", "-- [합성] x\n")
    _write(fake_repo, "templates/module-skills/ofono/x.log", "-- [합성] x\n")
    found = {path for rule, path in _rules(boundary.scan(fake_repo, "external")) if rule == "fixture-origin"}
    assert found == {f"{base}/notsyn/files/source.log", f"{base}/nocase/files/source.log",
                     "templates/module-skills/ofono/x.log"}

TBASE = "templates/module-skills/ofono/sim/evals"


def _origin_findings(root: Path) -> set[str]:
    return {path for rule, path in _rules(boundary.scan(root, "external")) if rule == "fixture-origin"}


def test_template_case_synthetic_only(fake_repo):
    """템플릿 case 로그는 합성만: synthetic: true + `-- [합성]`, origin 키가 있으면 위반."""
    _write(fake_repo, f"{TBASE}/syn/case.yaml", "schema_version: 1\nsynthetic: true\n")
    _write(fake_repo, f"{TBASE}/syn/files/source.log", "-- [합성] x\n")
    _write(fake_repo, f"{TBASE}/nomark/case.yaml", "schema_version: 1\nsynthetic: true\n")
    _write(fake_repo, f"{TBASE}/nomark/files/source.log", "Nov  1 10:00:00 x\n")
    _write(fake_repo, f"{TBASE}/both/case.yaml", "schema_version: 1\nsynthetic: true\norigin:\n  kind: x\n")
    _write(fake_repo, f"{TBASE}/both/files/source.log", "-- [합성] x\n")
    _write(fake_repo, f"{TBASE}/notsyn/case.yaml", "schema_version: 1\nsynthetic: false\norigin:\n  kind: x\n")
    _write(fake_repo, f"{TBASE}/notsyn/files/source.log", "-- [합성] x\n")
    assert _origin_findings(fake_repo) == {f"{TBASE}/nomark/files/source.log", f"{TBASE}/both/files/source.log",
                                           f"{TBASE}/notsyn/files/source.log"}


def test_trace_wording_pattern(fake_repo):
    """`pattern:trace-wording`: 로그 출처 흔적 문구(발췌·첨부 표시·로그 id·마스커 해시·점검 날짜)는 어느 파일이든 위반.
    시험 문자열은 이어 붙여 만든다(이 파일도 문구를 그대로 갖지 않는다)."""
    bad = ["마스킹" + " 발췌", "masked" + "-excerpt", "-- [" + "마스킹", "masker: " + "0123456789ab",
           "residual: '" + "2026-01-02'", "O" + "1 E14", "A-" + "E5", "E" + "3 줄 10-20",
           "O" + "2 E4b", "A-" + "E9b", "E" + "3c 줄 1-5", 'masker: "' + '0123456789ab"', 'residual: "' + '2026-01-02"',
           "첨부" + " 로그"]
    _write(fake_repo, "docs/trace.md", "\n".join(bad) + "\n")
    # 정당한 용어(과잉 매치 없음): 잔여 식별자 도구·옵션, Jira 첨부, 리뷰 항목 id, 마스킹 전 원본 로그
    clean = ["합성 로그, placeholder, A-E 구간 없음, E1 단계, O1 없음, residual 0건", "tools/fixture_residual.py 통과",
             "db_lint --residual 0건", "Jira 첨부 파일은 읽기만", "리뷰 항목 O1·O2", "마스킹 전 원본 로그는 사내에만"]
    _write(fake_repo, "docs/clean.md", "\n".join(clean) + "\n")
    found = [f for f in boundary.scan(fake_repo, "external") if f.rule == "pattern:trace-wording"]
    assert sorted(f.line for f in found) == list(range(1, len(bad) + 1))
    assert {f.path for f in found} == {"docs/trace.md"}
    rx = next(r for name, r, _ in boundary.DEFAULT_PATTERNS if name == "trace-wording")
    assert not rx.search((TOOLS / "check_boundary.py").read_text(encoding="utf-8"))   # 자기 파일은 예외 없이 통과


MODULES = """schema_version: 2
platforms:
  ofono:
    modules:
      data:
        path: ofono/data
        db_category: data
        dbus: [org.ofono.ConnectionManager, com.vendor.datad]   # 합집합
  android:
    modules:
      data: {path: android/data, db_category: data, keywords: [com.other.android.Thing]}
"""


def _dbus(root: Path) -> set[tuple[str, int, str]]:
    return {(f.path, f.line, f.text) for f in boundary.scan(root, "external") if f.rule == "dbus-name"}


def test_dbus_rule_flags_unknown_vendor_name(fake_repo):
    _write(fake_repo, "templates/module-skills/modules.yaml", MODULES)
    _write(fake_repo, "templates/module-skills/ofono/data/SKILL.md", "# x\ncom.vendorx.secret.Iface 를 본다\n")
    _write(fake_repo, "tests/helpers/make_variant_dbs.py",
           'OFONO_TAGS = """a\nnet.vendor.daemon.Thing\n"""\nOTHER = "com.free.form.Name"\n')
    assert _dbus(fake_repo) == {("templates/module-skills/ofono/data/SKILL.md", 2, "com.vendorx.secret.Iface"),
                                ("tests/helpers/make_variant_dbs.py", 2, "net.vendor.daemon.Thing")}


def test_dbus_rule_allows_modules_yaml_union(fake_repo):
    _write(fake_repo, "templates/module-skills/modules.yaml", MODULES)
    _write(fake_repo, "templates/module-skills/ofono/data/SKILL.md",
           "org.ofono.Modem · org.freedesktop.DBus.Properties · com.vendor.datad.Profile · org.ofono.ConnectionManager.\n")
    _write(fake_repo, "templates/module-skills/ofono/_common/components.md", "com.vendor.datad\n")
    assert _dbus(fake_repo) == set()
    # modules.yaml의 ofono 블록 안 다른 칸에 허용 밖 이름이 있으면 잡는다(android 블록은 범위 밖)
    _write(fake_repo, "templates/module-skills/modules.yaml",
           MODULES.replace("db_category: data\n        dbus", "db_category: data   # com.leak.vendor.x\n        dbus", 1))
    assert _dbus(fake_repo) == {("templates/module-skills/modules.yaml", 7, "com.leak.vendor.x")}


def test_dbus_rule_scope(fake_repo):
    _write(fake_repo, "templates/module-skills/modules.yaml", MODULES)
    name = "com.example.x.y"
    _write(fake_repo, "templates/module-skills/android/data/SKILL.md", f"{name}\n")
    _write(fake_repo, "tests/fixtures/issue-db-sample/notes.md", f"{name}\n")
    _write(fake_repo, "tests/fixtures/logs/x.log", f"{name}\n")
    _write(fake_repo, "tests/mocks/log_fixtures.yaml", "fixtures:\n  - {name: x, scenario: x}\n")
    _write(fake_repo, "docs/materials/x.html", f"{name}\n")
    _write(fake_repo, f"{TBASE}/syn/case.yaml", "schema_version: 1\nsynthetic: true\n")
    _write(fake_repo, f"{TBASE}/syn/files/source.log", f"-- [합성] x\n{name}\n")
    _write(fake_repo, f"{TBASE}/syn/files/timeline.md", f"{name}\n")
    assert _dbus(fake_repo) == set()


def test_dbus_rule_unreadable_modules_yaml(fake_repo):
    _write(fake_repo, "templates/module-skills/ofono/data/SKILL.md", "org.ofono.Modem\n")
    assert _dbus(fake_repo) == {("templates/module-skills/modules.yaml", 0, "")}       # 없음
    _write(fake_repo, "templates/module-skills/modules.yaml", "a: &x 1\nb: *x\n")
    assert _dbus(fake_repo) == {("templates/module-skills/modules.yaml", 0, "")}       # 앵커


def test_allow_file_and_site_patterns(fake_repo):
    _write(fake_repo, "tests/test_x.py", "IMEI = '359881234567812'\nOTHER = '359881234567813'\n")
    _write(fake_repo, "tools/boundary-allow.txt", "pattern:long-number tests/* ^359881234567812$\n")
    found = boundary.scan(fake_repo, "external")
    assert [f.text for f in found] == ["359881234567813"]

    # 사내 패턴은 SITE_PATHS(docs/site/)에 두고 사내 모드에서 쓴다
    _write(fake_repo, "docs/site/boundary-patterns.txt", "id:corp-name (?i)acme-telecom\n")
    _write(fake_repo, "plugin/scripts/parse_logcat.py", "# tuned for ACME-Telecom logs\n")
    found = _rules(boundary.scan(fake_repo, "site"))
    assert ("pattern:corp-name", "plugin/scripts/parse_logcat.py") in found
    # 패턴 파일 자체는 SITE_PATHS라 검사하지 않는다
    assert not any(path.startswith("docs/site/") for _, path in found)


R = "A1b2C3d4E5f6G7h8"  # 16자 합성 조각 (실제 토큰 아님)

SECRET_LINES = [
    ("private-key", "-----BEGIN OPENSSH PRIVATE KEY-----"),
    ("private-key", "-----BEGIN PGP PRIVATE KEY BLOCK-----"),
    ("github-token", "gh" + "p_" + R + R + "abcd"),
    ("github-token", "github" + "_pat_" + "11" + R + "_" + R + R),
    ("aws-access-key", "AK" + "IA" + "Q3EGRIZ7XN4LMDKV"),
    ("slack-token", "xo" + "xb-" + "1234567890-" + R),
    ("google-api-key", "AI" + "za" + "Sy" + R + R + "Z"),        # AIza + 35자
    ("atlassian-token", "ATA" + "TT3x" + R * 3),
    ("package-token", "np" + "m_" + R + R + "abcd"),
    ("llm-api-key", "sk-" + "ant-api03-" + R * 2),
    ("llm-api-key", "sk-" + "proj-" + R + "T3Blbk" + "FJ" + R),
    ("jwt", "ey" + "JhbGciOiJIUzI1NiJ9.ey" + "JzdWIiOiIxMjM0In0." + R),
    ("auth-header", "Authorization: Bearer " + R + R),
    ("auth-header", "Authorization: Basic " + "dXNlcjpwYXNz" + "d29yZDEyMw=="),
    ("url-credential", "https://kim:" + "s3cr3tPw" + "@build.mock-corp.invalid/x"),
    ("netrc", "machine ghe.invalid login kim password " + "Pw9xk2LmQ"),
    ("secret-assign", "aws_secret_access_key = " + R + R),
    ("secret-assign", '"client_secret": "' + R + R + '"'),
    ("secret-assign", "JIRA_API_TOKEN=" + R + "9z9z"),
    # 재리뷰 P1: ASCII 플래그가 없는 기본 패턴도 접은 글을 본다(NBSP·전각 숫자로 쓴 비밀값)
    ("private-key", "-----BEGIN RSA PRIVATE KEY-----"),
    ("secret-assign", "token: ABCDEFGH" + "１２３４５６７８９０１２"),
]


@pytest.mark.parametrize("rule,line", SECRET_LINES)
def test_secret_patterns_catch_values(fake_repo, rule, line):
    _write(fake_repo, "docs/leak.md", line + "\n")
    found = boundary.scan(fake_repo, "external")
    assert (f"pattern:{rule}", "docs/leak.md") in _rules(found)
    # 출력에는 비밀값 전체가 남지 않는다
    if rule != "private-key":
        assert all(line not in f.text for f in found)


def test_secret_pattern_folded_and_raw_match_reported_once(fake_repo):
    # 원문 match(`…ab`)와 접은 글 match(`…ab12`)는 자리가 달라도 같은 값이다 — 한 번만 알린다
    _write(fake_repo, "docs/leak.md", "token: ABCDEFGH1234567890ab" + "１２" + "\n")
    rules = [f.rule for f in boundary.scan(fake_repo, "external")]
    assert rules.count("pattern:secret-assign") == 1


def test_secret_values_joined_by_fullwidth_char_stay_separate(fake_repo):
    # 전각 글자 하나로 이어진 두 값: 접은 글에서는 match 하나지만 원문의 두 건으로 알린다(하나만 allow해도 다른 하나가 남게)
    _write(fake_repo, "docs/leak.md", "password=" + R + "abcd" + "１" + "token=" + R[::-1] + "zyxw" + "\n")
    rules = [f.rule for f in boundary.scan(fake_repo, "external")]
    assert rules.count("pattern:secret-assign") == 2


def test_secret_placeholders_and_code_pass(fake_repo):
    _write(fake_repo, "docs/howto.md", "\n".join([
        "-----BEGIN PUBLIC KEY-----",
        "ghp_<token>",
        "AKIAIOSFODNN7EXAMPLE",
        "xoxb-xxxxxxxxxx",
        "token: <eyJhbGciOiJIUzI1NiJ9.payload>",
        '-H "Authorization: Bearer $GH_TOKEN"',
        'Authorization: Digest username="a", response="<CRED#1>"',
        '<div class="basic label-container">',
        "https://x-access-token:${GH_TOKEN}@github.com/o/r",
        "https://user:<password>@ghe.invalid/x",
        "ssh://git@github.com/o/r",
        "login kim password ****",
        "TT_PUBLISH_TOKEN=<approved_hash>",
        "GH_TOKEN=${{ secrets.GH_TOKEN }}",
        "token = self._compute_token_for_request",
        "password: REDACTED_REDACTED_REDACTED1",
        "api_key: your_api_key_here_1234567890",
        "risk-free sk-learn",
    ]) + "\n")
    assert boundary.scan(fake_repo, "external") == []


def test_secret_assign_long_line_is_fast():
    # 키 이름 앞뒤 상한({0,30}) 덕에 긴 줄에서도 선형 시간
    regex = dict((n, r) for n, r, _ in boundary.DEFAULT_PATTERNS)["secret-assign"]
    start = time.monotonic()
    regex.search("a_" * 100000)
    assert time.monotonic() - start < 2


# ---------------------------------------------------------------- import_draft


def _draft(root: Path, extra: dict[str, str] | None = None) -> Path:
    _write(root, "SITE_PATHS", SITE_PATHS_TEXT)
    _write(root, "plugin/scripts/config.py", "# config\n")
    _write(root, "tests/test_masking.py", "IMEI = '450081234567890'\n")
    _write(root, "tools/boundary-allow.txt", "pattern:long-number tests/* ^450081234567890$\n")
    for rel, text in (extra or {}).items():
        _write(root, rel, text)
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_check_boundary_on_import_uses_incoming_allow_file(tmp_path):
    source, dest = _draft(tmp_path / "draft"), tmp_path / "site"
    dest.mkdir()
    code, out = _run(IMPORT, str(source), "--dest", str(dest), "--check-boundary", "--json")
    assert code == 0, out
    assert out["status"] == "applied"


def test_check_boundary_violation_leaves_site_repo_unchanged(tmp_path):
    source = _draft(tmp_path / "draft")
    dest = tmp_path / "site"
    dest.mkdir()
    assert _run(IMPORT, str(source), "--dest", str(dest), "--json")[0] == 0
    _write(dest, "docs/site/boundary-patterns.txt", "id:corp-name (?i)acme-telecom\n")
    _write(dest, "tools/site_notes.md", "ACME-Telecom 빌드 서버 메모\n")  # 비-SITE_PATHS 사내 새 파일
    _write(source, "plugin/scripts/config.py", "# config v2\n")
    before = _snapshot(dest)

    code, out = _run(IMPORT, str(source), "--dest", str(dest), "--check-boundary", "--json")
    assert code == 1, out
    assert out["reason"] == "boundary"
    assert [(v["rule"], v["path"]) for v in out["violations"]] == [("pattern:corp-name", "tools/site_notes.md")]
    assert _snapshot(dest) == before

    # dry-run도 같은 검사를 하고 아무것도 바꾸지 않는다
    code, out = _run(IMPORT, str(source), "--dest", str(dest), "--check-boundary", "--dry-run", "--json")
    assert code == 1 and _snapshot(dest) == before


def test_staging_mismatch_leaves_site_repo_unchanged(tmp_path):
    source, dest = _draft(tmp_path / "draft"), tmp_path / "site"
    dest.mkdir()
    result = draft.plan(source, dest, None)
    _write(source, "plugin/scripts/config.py", "# 반입 도중 바뀜\n")
    with pytest.raises(ValueError, match="staging"):
        draft.apply(result, source, dest)
    assert _snapshot(dest) == {}


def test_failed_activation_check_rolls_back(tmp_path, monkeypatch):
    source, dest = _draft(tmp_path / "draft"), tmp_path / "site"
    dest.mkdir()
    draft.apply(draft.plan(source, dest, "v1"), source, dest)
    before = _snapshot(dest)
    _write(source, "plugin/scripts/config.py", "# v2\n")
    _write(source, "plugin/scripts/new_dir/new.py", "# v2 new\n")
    result = draft.plan(source, dest, "v2")

    def broken_verify(result, dest):
        raise ValueError("synthetic verify failure")
    monkeypatch.setattr(draft, "_verify_active", broken_verify)
    with pytest.raises(ValueError, match="synthetic"):
        draft.apply(result, source, dest)
    assert _snapshot(dest) == before
    assert not (dest / "plugin/scripts/new_dir").exists()


def test_second_import_of_same_draft_is_identical(tmp_path):
    source, dest = _draft(tmp_path / "draft"), tmp_path / "site"
    dest.mkdir()
    assert _run(IMPORT, str(source), "--dest", str(dest), "--label", "v1", "--json")[0] == 0
    first = json.loads((dest / ".draft-manifest.json").read_text(encoding="utf-8"))
    code, out = _run(IMPORT, str(source), "--dest", str(dest), "--label", "v1", "--json")
    assert code == 0, out
    assert out["to_write"] == [] and out["to_delete"] == []
    second = json.loads((dest / ".draft-manifest.json").read_text(encoding="utf-8"))
    assert second["files"] == first["files"]
    assert all(draft.sha256(dest / rel) == digest for rel, digest in second["files"].items())


# ---------------------------------------------------------------- plugin/schemas


def test_plugin_schema_copy_is_in_sync():
    code, out = _run(TOOLS / "sync_schemas.py", "--check")
    assert code == 0, out
    for path in (REPO / "plugin/schemas/plan.schema.json", REPO / "tests/fixtures/issue-db-sample/schema/plan.schema.json"):
        pr = json.loads(path.read_text(encoding="utf-8"))["properties"]["pr"]
        assert "ids" in pr["properties"] and "ids" not in pr["required"], path   # publish가 기록하는 선택 필드(pr.ids)


def test_sample_plans_validate_against_plugin_schema_copy():
    import jsonschema

    schema = json.loads((REPO / "plugin/schemas/plan.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    plans = sorted((REPO / "tests/fixtures/plans").glob("*.plan.json"))
    assert plans
    for path in plans:
        errors = [e.message for e in validator.iter_errors(json.loads(path.read_text(encoding="utf-8")))]
        assert errors == [], (path.name, errors)
