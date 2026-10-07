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
    text = (REPO / ".github/workflows/external.yml").read_text(encoding="utf-8")
    assert text.count("    if: github.server_url == 'https://github.com'\n") == 2


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


def test_synthetic_marks_and_registries_pass(fake_repo):
    fixtures = "tests/fixtures/issue-db-x/data/DATA-001-x/fixtures"
    _write(fake_repo, f"{fixtures}/DATA-001-01.log", "log\n")
    _write(fake_repo, f"{fixtures}/DATA-001-01.expect.yaml", "expect_top: DATA-001-01\norigin: synthetic\n")
    _write(fake_repo, "tests/fixtures/logs/data-connected.log", "log\n")
    _write(fake_repo, "tests/mocks/log_fixtures.yaml", "fixtures:\n  - {name: data-connected, scenario: x}\n")
    _write(fake_repo, "tests/verify-logs/fixed.log", "log\n")
    _write(fake_repo, "tests/verify-logs/README.md", "- `fixed.log` 합성\n")
    assert boundary.scan(fake_repo, "external") == []


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
]


@pytest.mark.parametrize("rule,line", SECRET_LINES)
def test_secret_patterns_catch_values(fake_repo, rule, line):
    _write(fake_repo, "docs/leak.md", line + "\n")
    found = boundary.scan(fake_repo, "external")
    assert (f"pattern:{rule}", "docs/leak.md") in _rules(found)
    # 출력에는 비밀값 전체가 남지 않는다
    if rule != "private-key":
        assert all(line not in f.text for f in found)


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
