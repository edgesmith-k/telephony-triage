#!/usr/bin/env python3
"""Phase D0 완료 기준 확인 (11-phases.md Phase D0).

확인하는 것
1. 모의 Jira MCP에서 이슈 읽기 (stdio JSON-RPC, 비표준 도구 이름)
2. 모의 원격으로 push와 `gh pr create` 성공
3. 합성 logcat 생성 (슬롯·시계 이상·bugreport 래핑 포함)
4. 모의 소스 트리에서 심볼 검색 (16/17 경로가 다른 파일 포함)
5. `make_plugin_root.py`가 만든 루트에는 `site-defaults.yaml`이 있고,
   개발 레포 `plugin/`에는 없다
6. `plugin/`을 직접 `${CLAUDE_PLUGIN_ROOT}`로 주면 `config.py`가 종료 코드 2
7. `.githooks/pre-commit`·`pre-push`(Phase 8부터 실제 hook)가 실행 비트(100755)와 함께 커밋된다
8. 레포 루트에 `.mcp.json`이 없다 (모의 MCP는 `tests/mocks/mcp.json`)

재반입(`tools/import_draft.py`)은 `tests/test_import_draft.py`,
골든 테스트 틀은 `tests/test_golden.py`에 있다.

`pytest tests/test_mocks.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
sys.path.insert(0, str(REPO / "tests" / "mocks"))

import logcat_gen  # noqa: E402
import make_plugin_root  # noqa: E402
import make_repo  # noqa: E402
import mock_env  # noqa: E402

MCP_SERVER = REPO / "tests" / "mocks" / "jira_mcp" / "server.py"


# -- 1. 모의 Jira MCP -------------------------------------------------------


def _mcp_roundtrip(requests: list[dict]) -> list[dict]:
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in requests) + "\n"
    result = subprocess.run(
        [sys.executable, str(MCP_SERVER)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=mock_env.env_with_mocks(),
    )
    assert result.returncode == 0, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_mock_jira_mcp_reads_issue():
    responses = _mcp_roundtrip(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "jira_fetch_ticket",
                    "arguments": {"ticket": "MOCK-1001"},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "jira_ticket_comments",
                    "arguments": {"ticket": "MOCK-1001"},
                },
            },
        ]
    )
    by_id = {r["id"]: r for r in responses if "id" in r}

    assert by_id[1]["result"]["serverInfo"]["name"] == "mock-jira"

    names = [t["name"] for t in by_id[2]["result"]["tools"]]
    # 도구 이름은 일부러 비표준이다. jira.tools 매핑을 반드시 거치게 하기 위해서다.
    assert names == [
        "jira_fetch_ticket",
        "jira_query_tickets",
        "jira_ticket_comments",
        "jira_post_comment",
        "jira_move_ticket",
    ]

    ticket = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert ticket["key"] == "MOCK-1001"
    # 커스텀 필드 이름도 일부러 사내와 다를 법한 이름이다 (jira.field_map 경유 강제).
    assert "customfield_10001" in ticket["fields"]
    assert by_id[3]["result"]["isError"] is False

    comments = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert len(comments["comments"]) == 2


def test_mock_jira_mcp_has_write_tools_for_guard_test():
    """쓰기 도구가 있어야 guard 차단 테스트(Phase 8)를 할 수 있다."""
    responses = _mcp_roundtrip([{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}])
    names = {t["name"] for t in responses[0]["result"]["tools"]}
    assert {"jira_post_comment", "jira_move_ticket"} <= names


# -- 2. 모의 원격과 gh 스텁 --------------------------------------------------


def test_mock_remote_push_and_pr():
    with tempfile.TemporaryDirectory(prefix="tt-remote-") as tmp:
        base = Path(tmp)
        info = make_repo.make(REPO / "tests" / "fixtures" / "issue-db-sample", base / "repo")
        clone = Path(info["clone"])
        env = mock_env.env_with_mocks(
            gh_state_dir=base / "gh-state", gh_host="ghe.mock.invalid"
        )
        gh = mock_env.resolve("gh", env)

        def run(args, cwd=clone):
            return subprocess.run(
                args,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        assert run(["git", "switch", "-c", "issue/MOCK-1001"]).returncode == 0
        (clone / "note.txt").write_text("모의 변경\n", encoding="utf-8")
        assert run(["git", "add", "-A"]).returncode == 0
        assert run(["git", "commit", "-m", "[DATA-001-01] 모의 변경"]).returncode == 0

        pushed = run(["git", "push", "origin", "HEAD:refs/heads/issue/MOCK-1001"])
        assert pushed.returncode == 0, pushed.stderr

        assert run([gh, "auth", "status", "--hostname", "ghe.mock.invalid"]).returncode == 0

        created = run(
            [
                gh, "pr", "create",
                "--title", "[DATA-001-01] 모의 변경",
                "--body", "모의 PR 본문",
                "--base", "main",
                "--head", "issue/MOCK-1001",
                "--reviewer", "mock-org/data-owners",
            ]
        )
        assert created.returncode == 0, created.stderr
        assert created.stdout.strip().endswith("/pull/1")

        listed = run(
            [gh, "pr", "list", "--search", "DATA-001-01", "--state", "open",
             "--json", "number,branch,reviewers"]
        )
        assert listed.returncode == 0
        rows = json.loads(listed.stdout)
        assert rows[0]["branch"] == "issue/MOCK-1001"
        assert rows[0]["reviewers"] == ["mock-org/data-owners"]

        # 같은 브랜치로 두 번 만들면 실패한다 (Step 8의 "이미 PR이 있으면 edit" 경로)
        again = run([gh, "pr", "create", "--base", "main", "--head", "issue/MOCK-1001"])
        assert again.returncode == 1

        # gh 인증 실패 경로 (setup 9번)
        unauth_env = mock_env.env_with_mocks(gh_state_dir=base / "gh-state", unauth=True)
        unauth = subprocess.run(
            [mock_env.resolve("gh", unauth_env), "auth", "status"],
            cwd=str(clone), env=unauth_env,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert unauth.returncode == 1

        # `pr list --author @me`: MOCK_GH_USER(기본 mock-user)가 만든 PR만, 목록 실패 경로는 종료 코드 1 (db_pr my-prs)
        author = {**env, "MOCK_GH_USER": "someone-else"}
        other = subprocess.run(
            [gh, "pr", "create", "--base", "main", "--head", "issue/MOCK-1002"], cwd=str(clone), env=author,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert other.returncode == 0, other.stderr
        mine = run([gh, "pr", "list", "--author", "@me", "--state", "open", "--json", "number,headRefName"])
        assert [r["headRefName"] for r in json.loads(mine.stdout)] == ["issue/MOCK-1001"]
        theirs = subprocess.run(
            [gh, "pr", "list", "--author", "@me", "--state", "open", "--json", "number,headRefName"],
            cwd=str(clone), env=author, capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert [r["headRefName"] for r in json.loads(theirs.stdout)] == ["issue/MOCK-1002"]
        failing = subprocess.run(
            [gh, "pr", "list", "--author", "@me"], cwd=str(clone), env={**env, "MOCK_GH_FAIL_LIST": "1"},
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert failing.returncode == 1 and "MOCK_GH_FAIL_LIST" in failing.stderr


# -- 3. 합성 logcat ---------------------------------------------------------


def test_logcat_generation_slots_and_clock():
    with tempfile.TemporaryDirectory(prefix="tt-logcat-") as tmp:
        out = Path(tmp)
        info = logcat_gen.generate(
            REPO / "tests/mocks/scenarios/data-001-none-cross-slot.yaml", out
        )
        text = Path(info["files"][0]).read_text(encoding="utf-8")
        # 두 슬롯이 한 파일에 섞여 있다 (교차 슬롯 음성 fixture).
        # 슬롯 0에는 거부 로그, 슬롯 1에는 원인 로그(설정 OFF)가 있다.
        assert "DNC-0:" in text and "DSM-1:" in text
        assert "[PHONE0]" in text and "[PHONE1]" in text
        # 합성 fixture 표시
        expect = Path(info["expect"]).read_text(encoding="utf-8")
        assert "origin: synthetic" in expect
        assert "expect_top: none" in expect

        # 시계 이상
        info = logcat_gen.generate(REPO / "tests/mocks/scenarios/clock-anomaly.yaml", out)
        stamps = [
            line.split()[1]
            for line in Path(info["files"][0]).read_text(encoding="utf-8").splitlines()
        ]
        assert any(b < a for a, b in zip(stamps, stamps[1:])), "시각이 뒤로 가는 줄이 없다"

        # threadtime 형식
        first = Path(info["files"][0]).read_text(encoding="utf-8").splitlines()[0]
        assert re.match(r"^\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\s+\d+\s+\d+ [VDIWEF] \S+: ", first)


def test_logcat_generation_is_deterministic():
    with tempfile.TemporaryDirectory(prefix="tt-logcat-") as tmp:
        base = Path(tmp)
        scenario = REPO / "tests/mocks/scenarios/data-001-01-positive.yaml"
        a = logcat_gen.generate(scenario, base / "a")
        b = logcat_gen.generate(scenario, base / "b")
        assert (
            Path(a["files"][0]).read_text(encoding="utf-8")
            == Path(b["files"][0]).read_text(encoding="utf-8")
        )


def test_bugreport_wrapping():
    with tempfile.TemporaryDirectory(prefix="tt-bugreport-") as tmp:
        out = Path(tmp)
        scenario = REPO / "tests/mocks/scenarios/bugreport-wrap.yaml"

        txt = logcat_gen.generate(scenario, out, bugreport="txt")
        body = Path(txt["files"][0]).read_text(encoding="utf-8")
        assert "Build fingerprint:" in body
        assert "------ RADIO LOG" in body
        assert "------ MAIN LOG" in body
        # 파서가 읽으면 안 되는 섹션도 들어 있어야 시험이 된다
        assert "------ DUMPSYS" in body

        import zipfile

        zipped = logcat_gen.generate(scenario, out, bugreport="zip")
        with zipfile.ZipFile(Path(zipped["files"][0])) as zf:
            names = zf.namelist()
            assert len(names) == 1
            assert "------ RADIO LOG" in zf.read(names[0]).decode("utf-8")


# -- 4. 모의 소스 트리 -------------------------------------------------------


def _find_symbol(root: Path, symbol: str) -> list[str]:
    hits = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".java", ".c", ".h", ".mk"}:
            continue
        if symbol in path.read_text(encoding="utf-8", errors="replace"):
            hits.append(path.relative_to(root).as_posix())
    return hits


def test_mock_source_tree_symbol_search():
    src = REPO / "tests" / "mocks" / "src"
    for version in ("android16", "android17"):
        hits = _find_symbol(src / version, "onEvaluateNetworkRequests")
        assert any("DataNetworkController.java" in h for h in hits), version

    # 16과 17에서 경로가 다른 파일 (find-symbol 시험용)
    in16 = _find_symbol(src / "android16", "class DataFailCause")
    in17 = _find_symbol(src / "android17", "class DataFailCause")
    assert in16 == ["frameworks/base/telephony/java/android/telephony/DataFailCause.java"]
    assert in17 == [
        "frameworks/opt/telephony/src/java/com/android/internal/telephony/data/fail/DataFailCause.java"
    ]

    # 트리 버전 식별 파일
    v16 = (src / "android16/build/make/core/version_defaults.mk").read_text(encoding="utf-8")
    v17 = (src / "android17/build/make/core/version_defaults.mk").read_text(encoding="utf-8")
    assert "PLATFORM_VERSION := 16" in v16
    assert "PLATFORM_VERSION := 17" in v17


# -- 5·6. 테스트 헬퍼 플러그인 루트와 site-defaults --------------------------


def test_plugin_root_helper_and_missing_site_defaults():
    # 개발 레포 plugin/ 안에는 site-defaults.yaml 이 없다 (반입 체크리스트 §15.4)
    assert not (REPO / "plugin" / "site-defaults.yaml").exists()
    assert (REPO / "plugin" / "site-defaults.example.yaml").is_file()

    with tempfile.TemporaryDirectory(prefix="tt-plugin-root-") as tmp:
        root = make_plugin_root.make(Path(tmp) / "root")
        assert (root / "site-defaults.yaml").is_file()

        env = mock_env.env_with_mocks(plugin_root=root)
        ok = subprocess.run(
            [sys.executable, str(REPO / "plugin/scripts/config.py"), "show", "--json"],
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert ok.returncode == 0, ok.stderr
        assert json.loads(ok.stdout)["plugin_root"] == str(root)

        # plugin/ 을 직접 주면 "사내 기본값 없음"으로 종료 코드 2
        bad_env = mock_env.env_with_mocks(plugin_root=REPO / "plugin")
        bad = subprocess.run(
            [sys.executable, str(REPO / "plugin/scripts/config.py"), "show"],
            env=bad_env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert bad.returncode == 2, bad.stdout
        assert "사내 기본값 없음" in bad.stderr

        # 모의 site 백엔드를 넣은 루트
        with_site = make_plugin_root.make(Path(tmp) / "root2", with_site_backend=True)
        assert (with_site / "scripts/parser_backends/site/__init__.py").is_file()
        assert (with_site / "scripts/adapters/site_data_existing.py").is_file()


def test_site_defaults_example_shape():
    import yaml

    data = yaml.safe_load(
        (REPO / "plugin" / "site-defaults.example.yaml").read_text(encoding="utf-8")
    )
    assert data["synthetic_allowed"] is True
    assert data["jira"]["exclude_servers"] == []
    assert data["jira"]["tools"]["get_issue"].startswith("mcp__mock-jira__")
    assert data["parser"]["backend"] == "reference"
    assert data["external_parsers"] == {}
    assert data["analyzers"]["data"]["when"] == "ask"
    # read_tools 는 tools 값을 모두 포함해야 한다
    # (contracts.md §기존 자산 연결 계약)
    assert set(data["jira"]["tools"].values()) <= set(data["jira"]["read_tools"])


# -- 7·8. 실행 비트와 .mcp.json ---------------------------------------------


def test_githook_stubs_committed_as_100755():
    with tempfile.TemporaryDirectory(prefix="tt-execbit-") as tmp:
        info = make_repo.make(
            REPO / "tests" / "fixtures" / "issue-db-sample", Path(tmp) / "repo"
        )
        listed = subprocess.run(
            ["git", "ls-files", "-s"],
            cwd=info["clone"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        ).stdout
        modes = {
            line.split("\t")[1]: line.split()[0] for line in listed.splitlines() if line
        }
        assert modes[".githooks/pre-commit"] == "100755"
        assert modes[".githooks/pre-push"] == "100755"


def test_no_mcp_json_at_repo_root():
    """모의 MCP는 `tests/mocks/mcp.json`에 둔다. 레포 루트 `.mcp.json`에 두면
    사내에서 가짜 Jira가 진짜로 잡힐 수 있다 (15-local-draft.md §15.2)."""
    assert not (REPO / ".mcp.json").exists()
    registered = json.loads((REPO / "tests/mocks/mcp.json").read_text(encoding="utf-8"))
    assert list(registered["mcpServers"]) == ["mock-jira"]


def test_site_paths_are_absent_in_draft():
    """`SITE_PATHS`의 경로는 사외 레포에 없어야 한다 (반입 체크리스트 §15.4)."""
    patterns = [
        line.strip()
        for line in (REPO / "SITE_PATHS").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    present = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            present += [p.as_posix() for p in REPO.glob(pattern)]
        else:
            target = REPO / pattern
            if target.exists() and any(target.iterdir() if target.is_dir() else [target]):
                present.append(pattern)
    assert not present, f"사외 레포에 SITE_PATHS 경로가 있습니다: {present}"


def test_generated_files_use_lf():
    """생성물은 어느 OS에서 만들어도 LF다.

    실행 환경은 Ubuntu이고 (`01-architecture.md §3`), fixture는 마스킹 후
    분석과 회귀가 **같은 텍스트**를 봐야 한다 (`04-parser-matching.md §5.11 (1)`).
    Windows 기본 줄바꿈 변환이 섞이면 같은 시나리오가 OS마다 다른 파일을
    내고, `#!/bin/sh` 스텁도 Ubuntu에서 실행되지 않는다.
    """
    with tempfile.TemporaryDirectory(prefix="tt-lf-") as tmp:
        out = Path(tmp)
        info = logcat_gen.generate(
            REPO / "tests/mocks/scenarios/data-001-01-positive.yaml", out
        )
        for path in [*info["files"], info["expect"]]:
            assert b"\r\n" not in Path(path).read_bytes(), path

        wrapped = logcat_gen.generate(
            REPO / "tests/mocks/scenarios/bugreport-wrap.yaml", out, bugreport="txt"
        )
        assert b"\r\n" not in Path(wrapped["files"][0]).read_bytes()


def test_repo_text_files_use_lf():
    """커밋되는 텍스트 파일에 CRLF가 섞이지 않았다 (`.gitattributes`)."""
    skip_parts = {".git", "__pycache__", ".pytest_cache"}
    skip_suffix = {".zip", ".png", ".jpg", ".gz", ".pdf"}
    bad = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO)
        if set(rel.parts) & skip_parts or path.suffix in skip_suffix:
            continue
        if rel.as_posix().startswith("tests/skill_evals/workspace/"):  # 스킬 eval 실행 결과, .gitignore (커밋 안 함)
            continue
        if rel.name == "probe-hook.log":  # 실험이 남기는 파일, 커밋하지 않는다
            continue
        if b"\r\n" in path.read_bytes():
            bad.append(rel.as_posix())
    assert not bad, f"CRLF가 섞인 파일: {bad}"


def _all_tests():
    return [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
