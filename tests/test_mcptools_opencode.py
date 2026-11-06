"""common/mcptools.py의 OpenCode 쪽(계획 I O8): opencode.json `mcp` 읽기와 `<서버>_<도구>` 이름.

- 이름 규칙은 하나다: `oc_adapter.mcp_candidates`(guard에 넘기는 쪽)는 `mcptools.opencode_candidates`를 그대로 쓴다.
- `tool_part`: `mcp__s__t`는 도구 부분, OpenCode 이름은 `<서버>_` 접두사를 뗀다(OpenCode일 때만 — Claude Code의 맨 도구 이름
  `jira_get_issue`는 그대로).
- 설정: JSONC, local `command` 배열 → command·args, `environment` → env, `enabled:false`, remote는 command 없음. 뒤 파일이
  얕게 덮는다(우선순위 낮은 것부터 — 전역 → 프로젝트(먼 → 가까운) → 관리).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
from common import mcptools, oc_adapter  # noqa: E402


def test_opencode_candidates_is_the_adapter_rule():
    servers = ["corp", "corp_jira", "jira.corp", "mock-jira"]
    for tool in ("corp_jira_get_issue", "jira_corp_search", "mock-jira_jira_fetch_ticket", "corp_x", "corp_", "read"):
        assert oc_adapter.mcp_candidates(tool, servers) == mcptools.opencode_candidates(tool, servers), tool
    assert mcptools.opencode_candidates("corp_jira_get_issue", servers) == ["mcp__corp_jira__get_issue",
                                                                           "mcp__corp__jira_get_issue"]
    assert mcptools.opencode_candidates("jira_corp_search", servers) == ["mcp__jira_corp__search"]
    assert mcptools.opencode_candidates("read", servers) == []


def test_tool_part():
    assert mcptools.tool_part("jira", "mcp__jira__get_issue") == "get_issue"
    assert mcptools.tool_part("jira", "jira_get_issue") == "jira_get_issue"                 # Claude Code: 이미 도구 이름
    assert mcptools.tool_part("jira", "jira_jira_get_issue", opencode=True) == "jira_get_issue"
    assert mcptools.tool_part("jira.corp", "jira_corp_get_issue", opencode=True) == "get_issue"   # 정규화 비교
    assert mcptools.tool_part("jira", "other_tool", opencode=True) == "other_tool"
    assert mcptools.tool_part("jira", "jira_", opencode=True) == "jira_"


def test_load_opencode_servers_jsonc_merge_and_shapes(tmp_path):
    glob = tmp_path / "global.json"
    glob.write_text(json.dumps({"mcp": {
        "jira": {"type": "local", "command": ["npx", "-y", "mcp-jira"], "environment": {"JIRA_URL": "https://j.invalid"}},
        "remote-jira": {"type": "remote", "url": "https://mcp.invalid/x"},
        "solo": {"type": "local", "command": "uvx-solo"}}}), encoding="utf-8")
    proj = tmp_path / "opencode.jsonc"
    proj.write_text('{\n  // 프로젝트에서 끈다\n  "mcp": {"jira": {"enabled": false,},},\n  "snapshot": false\n}\n', encoding="utf-8")
    got = mcptools.load_opencode_servers([glob, tmp_path / "missing.json", proj])
    assert got["jira"] == {"type": "local", "enabled": False, "command": "npx", "args": ["-y", "mcp-jira"],
                           "env": {"JIRA_URL": "https://j.invalid"}}
    assert got["remote-jira"] == {"type": "remote", "enabled": True}              # command 없음 → 원격(probe remote)
    assert got["solo"]["command"] == "uvx-solo" and got["solo"]["args"] == []
    bad = tmp_path / "bad.json"
    bad.write_text('{"mcp": [1]}', encoding="utf-8")
    with pytest.raises(ValueError, match="mcp가 객체가 아니다"):
        mcptools.load_opencode_servers([bad])
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(ValueError, match="OpenCode 설정을 읽지 못함"):
        mcptools.load_opencode_servers([bad])


def test_opencode_config_paths_order(tmp_path, monkeypatch):
    home, top = tmp_path / "home", tmp_path / "top"
    sub = top / "proj"
    (home / ".config" / "opencode").mkdir(parents=True)
    (sub / ".opencode").mkdir(parents=True)
    g = home / ".config" / "opencode" / "opencode.json"
    far, near, dot = top / "opencode.json", sub / "opencode.json", sub / ".opencode" / "opencode.json"
    named = tmp_path / "named.json"
    for p in (g, far, near, dot, named):
        p.write_text("{}", encoding="utf-8")
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "OPENCODE_CONFIG": str(named)}
    got = [p for p in mcptools.opencode_config_paths(str(sub), env) if p.parent != mcptools.OPENCODE_MANAGED_DIR]
    assert got == [g, named, far, dot, near]          # 뒤 파일이 이긴다(가까운 프로젝트 설정이 마지막)
