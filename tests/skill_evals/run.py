#!/usr/bin/env python3
"""격리된 스킬 행동 평가를 준비하고 Claude Code로 실행한다.

python3 tests/skill_evals/run.py --iteration <새 디렉토리> --eval 3 4 --prepare-only
python3 tests/skill_evals/run.py --iteration <새 디렉토리> --eval 3 4 --execute [--mode plugin|direct] [--model <id>]

모드 (기본 plugin):
- plugin — `claude -p --plugin-dir <플러그인>`로 **설치된 것처럼** 불러온다. 사용자 요청을 그대로 첫 메시지로 보내므로
  `/telephony-triage:…` 커맨드·스킬 자동 선택·hook(guard·jira_bridge·SessionStart)이 실제로 돈다. Jira는 모의 MCP 서버
  (`mock-jira`, 비표준 도구 이름), 분석 스킬은 모의 플러그인(`mock-analyzers:mock-data-analyzer`)으로 붙는다.
- direct — 예전 방식. 실행자가 SKILL.md를 직접 읽고 Jira는 `call.py`, 분석 스킬은 `run.py`를 Bash로 부른다(hook 없음).
  plugin 모드 결과와 비교하거나 플러그인 로딩이 안 되는 CLI에서만 쓴다.

모델은 `--model`이 없으면 CLI 기본값이다. API 한도·인증 오류에서 배치를 멈추고, 기대 답이나
assertion을 실행자에게 주지 않는다. transcript 기반 수동 채점은 grade.py 실행 뒤 별도 수행한다.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tests" / "helpers"))
from skill_eval_env import build, _bash_path  # noqa: E402
from grade import grade  # noqa: E402


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


MOCKS = REPO / "tests" / "mocks"
ANALYZER_PLUGIN = "mock-analyzers"
APPROVER = "eval-approver"


def _rules(entry: dict, run_dir: Path) -> str:
    """실행자 공통 규칙(사용자 응답 시뮬레이션·결과 파일). 기대 답·assertion은 넣지 않는다."""
    out = (run_dir / "outputs").as_posix()
    return f"""응답 규칙: {json.dumps(entry['user_replies'], ensure_ascii=False)}
규칙에 없는 질문에는 변경하지 않는 선택지를 택하고 이를 기록한다. 스킬 지시와 사용자 응답이 충돌하면
사용자 응답을 바꾸지 말고 필요한 지점에서 멈춘다. 성공을 위해 스크립트/스킬/채점기를 수정하지 않는다.
레포 원본은 읽기만 한다. 쓰기는 이 평가의 모의 환경 및 {run_dir.as_posix()}/outputs 안에서만 한다.
실제 GitHub/Jira, 네트워크, 다른 평가 환경을 사용하지 않는다. gh는 제공된 스텁으로만 실행한다.
결과 파일은 반드시 아래 절대 경로에 쓴다(작업 디렉토리 기준 상대 경로를 쓰지 않는다).
{out}/transcript.md에는 모든 사용자용 메시지와 시뮬레이션 응답을 그대로 순서대로 저장한다.
{out}/commands.md에는 실행한 명령, 종료 코드, 요약을 기록한다. {out}/notes.md에는 막힌 지점을 적는다.
작업 계획이 생기면 {out}/plan.json에 사본을 남긴다. 끝나는 모든 경로에서 스킬의 lock 해제 절차를 따른다.
커밋 메시지는 확인 화면 commit_message 그대로(trailer·서명 줄 없음)
"""


def plugin_prompt(entry: dict, env_dir: Path, run_dir: Path) -> tuple[str, str]:
    """plugin 모드: (첫 사용자 메시지 = 요청 원문, 덧붙일 시스템 프롬프트). 스킬 파일 경로나 사용법은 알려주지 않는다 —
    커맨드·스킬 선택·hook이 실제 설치 상태처럼 동작하는지가 평가 대상이다."""
    system = f"""너는 telephony-triage 플러그인의 격리된 평가 실행자다. 실제 사용자는 없고, 첫 사용자 메시지가 요청이다.
플러그인(커맨드·스킬·hook), Jira MCP, 사내 분석 스킬은 이미 설치돼 있다. 실제 사용자 PC에서처럼 처리한다.
작업 디렉토리는 {env_dir.as_posix()}이고 요청의 logs/… 경로는 여기 기준이다. 필요한 환경 변수는 이미 설정돼 있다.
사용자가 답해야 하는 질문은 아래 응답 규칙으로 스스로 답하고 이어 간다(질문하고 멈추지 않는다).
""" + _rules(entry, run_dir)
    return entry["prompt"], system


def prepare_plugin_mode(entry: dict, info: dict, env_dir: Path) -> dict:
    """plugin 모드 부속물: 모의 Jira MCP 설정, 모의 분석 스킬 플러그인. API 없이 만든다(`--prepare-only`에서도)."""
    setup = entry.get("setup") or {}
    analyzer = env_dir / "mock-plugins" / ANALYZER_PLUGIN
    skill = analyzer / "skills" / "mock-data-analyzer"
    shutil.copytree(MOCKS / "skills" / "data-analyzer", skill, ignore=shutil.ignore_patterns("__pycache__"))
    (analyzer / ".claude-plugin").mkdir(parents=True)
    dump(analyzer / ".claude-plugin" / "plugin.json",
         {"name": ANALYZER_PLUGIN, "version": "0.0.1", "description": "스킬 eval용 모의 사내 분석 스킬"})
    if setup.get("analyzer_fail"):
        (skill / "run.py").write_text("import sys\nsys.exit('mock-data-analyzer: internal error (timeout)')\n", encoding="utf-8")
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    (skill / "SKILL.md").write_text(text.replace("tests/mocks/skills/data-analyzer/run.py",
                                                 (skill / "run.py").as_posix()), encoding="utf-8")
    mcp = env_dir / "mcp.json"
    dump(mcp, {"mcpServers": {
        "mock-jira": {"command": sys.executable, "args": [(MOCKS / "jira_mcp" / "server.py").as_posix()],
                      "env": {k: info["env"][k] for k in ("MOCK_JIRA_DIR", "MOCK_JIRA_WRITE_LOG", "PYTHONIOENCODING")}},
        # guard의 ask(예: publish 규칙 7)에 사람 대신 답하고 요청을 기록한다(`approvals.json`)
        APPROVER: {"command": sys.executable, "args": [(MOCKS / "approver_mcp" / "server.py").as_posix()],
                   "env": {"MOCK_APPROVALS_LOG": str(env_dir / "approvals.json"), "PYTHONIOENCODING": "utf-8"}}}})
    return {"plugin_dirs": [info["plugin_root"], str(analyzer)], "mcp_config": str(mcp)}


def plugin_check(events: list[dict]) -> tuple[str | None, dict]:
    """init 이벤트로 플러그인·MCP가 실제로 붙었는지 본다. 안 붙었으면 행동 평가가 아니라 환경 오류다."""
    init = next((e for e in events if e.get("type") == "system" and e.get("subtype") == "init"), None)
    uses = [c for e in events if e.get("type") == "assistant"
            for c in (e.get("message") or {}).get("content") or [] if isinstance(c, dict) and c.get("type") == "tool_use"]
    seen = {"skill_calls": [str((c.get("input") or {}).get("skill", "")) for c in uses if c.get("name") == "Skill"],
            "mcp_calls": [c.get("name") for c in uses if str(c.get("name", "")).startswith("mcp__")],
            "hooks": {}, "hooks_blocked": []}
    for e in events:        # hook 실행 요약: 이벤트별 횟수, 차단(종료 코드 2·deny)한 hook 이름
        if e.get("type") == "system" and e.get("subtype") == "hook_response":
            seen["hooks"][str(e.get("hook_event"))] = seen["hooks"].get(str(e.get("hook_event")), 0) + 1
            if e.get("exit_code") == 2 or '"deny"' in str(e.get("output", "")):
                seen["hooks_blocked"].append(str(e.get("hook_name")))
    if init is None:
        return "init 이벤트 없음(플러그인 로딩 확인 불가)", seen
    plugins = [str(p.get("name") if isinstance(p, dict) else p) for p in init.get("plugins") or []]
    servers = {str(s.get("name")): str(s.get("status")) for s in init.get("mcp_servers") or [] if isinstance(s, dict)}
    seen.update(plugins=plugins, mcp_servers=servers)
    if "telephony-triage" not in plugins:
        return f"플러그인이 로딩되지 않음: {plugins}", seen
    bad = {n: servers.get(n) for n in ("mock-jira", APPROVER) if servers.get(n) != "connected"}
    if bad:
        return f"MCP 연결 실패: {bad}", seen
    return None, seen


def evaluation_prompt(entry: dict, info: dict, env_dir: Path, run_dir: Path) -> str:
    return f"""너는 telephony-triage 스킬의 격리된 평가 실행자다. 실제 사용자는 없다.
스킬 {Path(info['skill']).as_posix()}/SKILL.md를 먼저 읽고 필요한 reference만 따른다.
환경은 {env_dir.as_posix()}/env.json이다. Bash마다 source '{env_dir.as_posix()}/env.sh' && cd '{env_dir.as_posix()}' && 를 앞에 붙인다.
스크립트는 $CLAUDE_PLUGIN_ROOT/scripts에서 실행하며, Jira MCP 대신 env.json의 jira_call/jira_tools_list,
분석 스킬 대신 analyzer_run을 쓴다. 사용자 응답은 아래 규칙으로 시뮬레이션한다.
요청: {entry['prompt']}
""" + _rules(entry, run_dir)


# 부모(원격 세션)의 정체성을 나르는 환경 변수: 자식 `claude -p`가 상속하면 부모 세션 ID로 동작해
# 커밋에 부모의 `Co-Authored-By`·`Claude-Session` 줄이 붙는다. 인증·프록시(HTTPS_PROXY, ANTHROPIC_*, *_CA_*, GH_TOKEN …)는 남긴다.
PARENT_IDENTITY_PREFIXES = ("CLAUDE_CODE_REMOTE", "CLAUDE_CODE_MESSAGING", "CLAUDE_CODE_ARTIFACT")
PARENT_IDENTITY_NAMES = frozenset({
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CONTAINER_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_USE_CCR_V2",
    "CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2", "CLAUDE_CODE_SYNC_SESSION_REFS", "CLAUDE_CODE_SYNC_SKILLS",
    "CLAUDE_CODE_WORKER_EPOCH", "TRACEPARENT"})
# 커밋·PR 서명을 끈다(`claude --settings`는 JSON 문자열을 받는다).
NO_ATTRIBUTION_SETTINGS = json.dumps({"includeCoAuthoredBy": False, "attribution": {"commit": "", "pr": ""}})
DERIVED_HEADER = "<!-- run.py: 실행자 미작성, events.jsonl에서 생성 -->"
REQUIRED_OUTPUTS = ("transcript.md", "commands.md", "notes.md")


def child_env(env: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """자식 claude에 넘길 환경 (부모 세션 정체성 변수를 뺀 사본, 뺀 이름 목록)."""
    stripped = sorted(k for k in env if k.startswith(PARENT_IDENTITY_PREFIXES) or k in PARENT_IDENTITY_NAMES)
    return {k: v for k, v in env.items() if k not in stripped}, stripped


def derive_outputs(run_dir: Path, events: list[dict], names=REQUIRED_OUTPUTS) -> list[str]:
    """실행자가 쓰지 않은 결과 파일을 events.jsonl에서 만든다. 만든 파일 이름 목록을 돌려준다."""
    out = run_dir / "outputs"
    results, calls, texts = {}, [], []
    for e in events:
        content = (e.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if e.get("type") == "assistant" and c.get("type") == "text" and str(c.get("text", "")).strip():
                texts.append(str(c["text"]).strip())
            elif e.get("type") == "assistant" and c.get("type") == "tool_use" and c.get("name") == "Bash":
                calls.append((c.get("id"), str((c.get("input") or {}).get("command", ""))))
            elif e.get("type") == "user" and c.get("type") == "tool_result":
                results[c.get("tool_use_id")] = bool(c.get("is_error"))
    made = []
    bodies = {
        "transcript.md": "\n\n".join(texts) or "(assistant 텍스트 없음)",
        "commands.md": "| # | 명령 | 상태 |\n|---|---|---|\n" + "\n".join(
            f"| {i} | {' '.join(cmd.split())[:300].replace('|', chr(92) + '|')} | "
            f"{'error' if results.get(tid) else ('ok' if tid in results else '결과 없음')} |"
            for i, (tid, cmd) in enumerate(calls, 1)),
        "notes.md": "실행자가 notes.md를 쓰지 않았다. 이 파일은 실행 기록에서 만든 대체본이다.",
    }
    for name in names:
        path = out / name
        if not path.is_file():
            path.write_text(f"{DERIVED_HEADER}\n{bodies[name]}\n", encoding="utf-8")
            made.append(name)
    return made


def classify_result(result: dict | None, returncode: int) -> tuple[str, str]:
    if not result:
        return "error", f"Claude 결과 없음 (exit {returncode})"
    reason = str(result.get("result", ""))
    if result.get("api_error_status") in (401, 403, 429):
        return "blocked", reason
    if returncode or result.get("is_error"):
        return "error", reason or str(result.get("subtype"))
    return "completed", reason


def execute(entry: dict, info: dict, env_dir: Path, run_dir: Path, claude: str,
            timeout: int, plugin: dict | None = None, model: str | None = None) -> dict:
    env = dict(os.environ)
    env.update(info["env"])
    env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), *info["path_prefix"], env["PATH"]])
    env["CLAUDE_CODE_GIT_BASH_PATH"] = env.get("CLAUDE_CODE_GIT_BASH_PATH", r"C:\Program Files\Git\bin\bash.exe") if os.name == "nt" else env.get("CLAUDE_CODE_GIT_BASH_PATH", "")
    env.pop("CLAUDECODE", None)
    env, stripped_env = child_env(env)
    # Git Bash는 python3.exe 없는 Windows에서도 같은 Python을 사용한다.
    if os.name == "nt":
        shim = env_dir / "bin"
        shim.mkdir()
        (shim / "python3").write_text(f"#!/bin/sh\nexec '{_bash_path(sys.executable)}' \"$@\"\n", encoding="utf-8", newline="\n")
        with (env_dir / "env.sh").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"export PATH='{_bash_path(str(shim))}':\"$PATH\"\n")
        env["PATH"] = os.pathsep.join([str(shim), env["PATH"]])      # plugin 모드는 env.sh를 source하지 않는다
    common = ["--output-format", "stream-json", "--verbose", "--no-session-persistence", "--setting-sources", "",
              "--settings", NO_ATTRIBUTION_SETTINGS, "--strict-mcp-config"]
    dirs = ["--add-dir", str(info["plugin_root"]), str(Path(info["issue_db_clone"]).parents[1]), str(run_dir), str(REPO)]
    if plugin:
        prompt, system = plugin_prompt(entry, env_dir, run_dir)
        (run_dir / "prompt.txt").write_text(f"[system]\n{system}\n[user]\n{prompt}\n", encoding="utf-8")
        tools = "Read,Bash,Write,Edit,Glob,Grep,Skill"
        # MCP 도구는 서버 단위로 허용한다 — Jira 쓰기 차단은 권한 거부가 아니라 guard hook이 해야 평가가 된다.
        # Bash는 매번 사용자 셸 프로필로 PATH를 다시 잡으므로(gh 스텁이 빠진다) env.sh를 명령마다 source하게 한다.
        env["CLAUDE_ENV_FILE"] = str(env_dir / "env.sh")
        command = [claude, "-p", *common, "--mcp-config", plugin["mcp_config"],
                   "--permission-prompt-tool", f"mcp__{APPROVER}__approve",
                   *[a for d in plugin["plugin_dirs"] for a in ("--plugin-dir", d)],
                   "--append-system-prompt", system,
                   "--tools", tools, "--allowedTools", tools + ",mcp__mock-jira", *dirs]
    else:
        prompt = evaluation_prompt(entry, info, env_dir, run_dir)
        (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
        command = [claude, "-p", *common, "--mcp-config", '{"mcpServers":{}}',
                   "--tools", "Read,Bash,Write,Edit,Glob,Grep", "--allowedTools", "Read,Bash,Write,Edit,Glob,Grep", *dirs]
    if model:
        command[2:2] = ["--model", model]
    start = time.monotonic()
    result = None
    derived: list[str] = []
    with (run_dir / "events.jsonl").open("w", encoding="utf-8") as events, (run_dir / "stderr.log").open("w", encoding="utf-8") as errors:
        proc = subprocess.Popen(command, cwd=env_dir, env=env, stdin=subprocess.PIPE, stdout=events, stderr=errors,
                                text=True, encoding="utf-8")
        try:
            proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            status, reason = "timeout", f"{timeout}초 제한으로 중단. 모의 환경의 lock 상태 확인 필요."
        else:
            events_list = []
            for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                events_list.append(event)
                if event.get("type") == "result":
                    result = event
            status, reason = classify_result(result, proc.returncode)
            if plugin:
                problem, seen = plugin_check(events_list)
                approvals = env_dir / "approvals.json"
                seen["approvals"] = json.loads(approvals.read_text(encoding="utf-8")) if approvals.is_file() else []
                plugin = {**plugin, "seen": seen}
                if problem and status == "completed":
                    status, reason = "error", f"플러그인 환경: {problem}"
            if status == "completed":
                derived = derive_outputs(run_dir, events_list)
    outcome = {"status": status, "reason": reason, "exit_code": proc.returncode,
               "elapsed_seconds": round(time.monotonic() - start, 2),
               "usage": (result or {}).get("usage"), "total_cost_usd": (result or {}).get("total_cost_usd"),
               "mode": "plugin" if plugin else "direct", "plugin": (plugin or {}).get("seen"),
               "outputs_derived": derived, "env_stripped": stripped_env}
    dump(run_dir / "execution.json", outcome)
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iteration", type=Path, required=True)
    parser.add_argument("--eval", type=int, nargs="+", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--mode", choices=("plugin", "direct"), default="plugin")
    parser.add_argument("--model")
    args = parser.parse_args()
    entries = {e["id"]: e for e in json.loads((HERE / "evals.json").read_text(encoding="utf-8"))["evals"]}
    for eid in args.eval:
        entry = entries.get(eid)
        if not entry or not all(entry.get(k) for k in ("prompt", "setup", "user_replies", "assertions")):
            parser.error(f"eval {eid}: 입력 정의 미완성")
    iteration = args.iteration.resolve()
    if iteration.exists():
        parser.error("기존 반복 디렉토리는 덮어쓰지 않는다. 새 경로를 지정한다.")
    claude = shutil.which("claude") if args.execute else None
    if args.execute and not claude:
        parser.error("Claude Code CLI를 PATH에서 찾을 수 없음")
    iteration.mkdir(parents=True)
    for eid in args.eval:
        entry = entries[eid]
        run_dir = iteration / f"eval-{eid}" / "with_skill"
        (run_dir / "outputs").mkdir(parents=True)
        env_dir = iteration / f"env-{eid}"
        info = build(entry, env_dir, direct_tools=(args.mode == "direct"))
        plugin = prepare_plugin_mode(entry, info, env_dir) if args.mode == "plugin" else None
        dump(run_dir.parent / "eval_metadata.json", {"eval_id": eid, "prompt": entry["prompt"], "assertions": entry["assertions"],
                                                     "mode": args.mode})
        if args.prepare_only:
            dump(run_dir / "execution.json", {"status": "prepared", "reason": "환경 준비만 수행; 행동 평가 미실행",
                                              "mode": args.mode})
            print(f"eval {eid}: prepared ({args.mode})", flush=True)
            continue
        outcome = execute(entry, info, env_dir, run_dir, claude, args.timeout, plugin, args.model)
        grade(eid, run_dir, env_dir, entry["assertions"])
        print(f"eval {eid}: {outcome['status']} — {outcome['reason'][:180]}", flush=True)
        if outcome["status"] != "completed":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
