#!/usr/bin/env python3
"""hook_replay.py — 기록된 세션의 hook 결정 지점을 지금 코드로 다시 판정한다 (숫자만, transcript 내용 없음).

    python3 tools/hook_replay.py <session.jsonl> [<session.jsonl> ...] [--plugin-root <dir>] [--scripts <plugin/scripts>]

입력은 Claude Code transcript JSONL(사내 `~/.claude/projects/<프로젝트>/<세션>.jsonl`, eval `with_skill/session.jsonl`,
`tests/fixtures/show_guard/eval2-session.jsonl`과 같은 형식). 결정 지점은 `plugin/hooks/hooks.json`과 같다:
- PreToolUse: `tool_use`마다 guard(Bash·`mcp__*`·Write/Edit/MultiEdit/NotebookEdit), show_guard pre-bash(Bash),
  pre-ask(AskUserQuestion·`mcp__*__ask_user`). transcript는 그 호출이 기록된 줄까지 잘라 준다.
- Stop: 뒤에 다음 도구 호출 없이 실제 사용자 입력·Stop 피드백·파일 끝이 오는 assistant 텍스트.
PostToolUse(post·jira_bridge)는 허용/거부가 아니라 안내라 넣지 않는다.

`--scripts`: guard·show_guard·`common.shown`을 읽을 plugin/scripts 디렉토리(기본 이 레포). 옛 커밋 사본
(`git archive <커밋> plugin/scripts | tar -x -C <dir>`)과 지금 작업 트리를 같은 재생 드라이버로 비교할 때 쓴다(L R 전환 게이트).

stdout JSON 하나: `files[{index, lines}]`, `points[{file, line, hook, tool, decision, keys, missing, recorded}]`,
`summary{points, decisions, recorded_deny, mismatch, records}`. 파일 경로·사유 글·명령은 내지 않는다. 도구는 종류(Bash·ask·file·mcp·other),
표식 키는 `kind:` + sha1 8자(브랜치·Jira 키가 새지 않게), `missing`은 "빠진 줄 n/total" 숫자.
`recorded`는 기록상 결과(`deny:guard`·`deny:show_guard`·`deny:other`·`ran`, Stop은 `block`·`ran`, 결과 없음 null).
mismatch = recorded가 있는 지점에서 기록상 그 hook의 거부(Stop은 block)와 지금 판정의 거부가 다른 수(guard `ask`는 기록으로
구분할 수 없어 거부가 아닌 것으로 본다).
`records` = 스크립트 표시 기록(사용자 config의 모든 프로필 `work_dir`의 `.shown/log.jsonl`, L R) 중 세션 시각 범위 안의 것을
transcript의 Bash 호출에 고정한 수 `{anchored, unanchored}`. 확인할 것이 없는 파일이 하나라도 있으면 null(옛 scripts, 시각 없는
transcript, 그 범위의 기록 없음 — 건너뛴 확인이지 통과가 아니다). unanchored가 0이 아니면
"transcript 시각이 스크립트 실행을 감싼다"는 R 전제가 이 환경에서 깨진 것이다(plugin-probe 15).

한계: guard 규칙 중 디스크·git 상태에 기대는 것(10 로그 원문 읽기 — 파일이 있어야 판정, 4·5 커밋, 8 clone)과 사용자 config
(규칙 7 publish ask는 `conf.user`가 있어야)는 **지금 PC 상태**로 판정한다 — 기록 당시와 다르면 mismatch로 센다. show_guard는
(L R ②b부터) 의무를 **지금 PC의 표시 기록**으로 정한다: 세션을 돌린 PC의 work_dir 기록이 없으면(다른 PC, 회전으로 밀려남,
시각 없는 transcript) 판정하지 않아 allow로 나온다 — `records`가 null이거나 anchored가 적으면 show_guard 지점의 결과는 믿지 않는다.
옛 scripts(`--scripts`, ②a 이전)는 transcript 추론으로 판정하므로 두 판정의 차이에는 기록 유무도 섞인다. guard와 show_guard가 같은 호출을 둘 다 거부하면 기록에는
한쪽 거부만 남아 다른 쪽이 거짓 mismatch가 된다. Stop 피드백이 transcript에 기록되지 않는 버전에서는 block이 `ran`으로 세어진다.

종료 코드: 0, 파일을 못 읽으면 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO_SCRIPTS = Path(__file__).resolve().parents[1] / "plugin" / "scripts"
guard = show_guard = shown = None   # `_load`가 채운다

MISSING_RE = re.compile(r"빠진 (?:줄|규칙) (\d+)/(\d+)")


def _load(scripts=None) -> None:
    """guard·show_guard·`common.shown`을 `scripts`(기본 이 레포)에서 import한다. 이미 그 디렉토리 것이 올라와 있으면 그대로 쓰고,
    다른 디렉토리 것이면 그 디렉토리의 최상위 모듈 이름(`common`·`trackers` 등)을 sys.modules에서 지우고 다시 읽는다."""
    global guard, show_guard, shown
    d = Path(scripts).resolve() if scripts else REPO_SCRIPTS

    def elsewhere(name: str) -> bool:
        f = getattr(sys.modules.get(name), "__file__", None)
        return bool(f) and not Path(f).resolve().is_relative_to(d)

    if any(map(elsewhere, ("guard", "show_guard", "common"))):
        tops = {p.stem for p in d.iterdir() if p.suffix == ".py" or (p / "__init__.py").is_file()}
        for name in [n for n in sys.modules if n.split(".")[0] in tops]:
            del sys.modules[name]
    if sys.path[:1] != [str(d)]:
        sys.path.insert(0, str(d))
    import guard as g  # noqa: E402
    import show_guard as sg  # noqa: E402
    from common import shown as sh  # noqa: E402
    guard, show_guard, shown = g, sg, sh


def _blocks(ev) -> list[dict]:
    msg = ev.get("message") if isinstance(ev, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _user_entry(ev):
    """사용자 항목(실제 입력·Stop 피드백·주입 글)이면 `shown.parse_events(include_user=True)`의 user 항목
    `{text, feedback, meta}`, 아니면 None — 목록형 user 텍스트, isMeta가 아닌 Stop 피드백도 show_guard와 같게 읽는다."""
    if not isinstance(ev, dict) or ev.get("type") != "user":
        return None
    return next((e for e in shown.parse_events([ev], include_user=True, skip_sidechain=False) if e["kind"] == "user"), None)


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content if isinstance(b, dict))
    return ""


def _recorded(evs) -> dict:
    out = {}
    for ev in evs:
        for b in _blocks(ev):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                text = _result_text(b.get("content"))
                if b.get("is_error") and text.startswith("PreToolUse:"):
                    out[b["tool_use_id"]] = ("deny:show_guard" if shown.MARKER in text
                                             else "deny:guard" if "[telephony-triage]" in text else "deny:other")
                else:
                    out[b["tool_use_id"]] = "ran"
    return out


def _key(marker: str) -> str:
    kind, _, rest = marker.partition(":")
    return f"{kind}:{hashlib.sha1(rest.encode('utf-8')).hexdigest()[:8]}"


def summarize(out) -> dict:
    """hook 출력 → {decision, keys, missing}. 사유 글은 내지 않는다."""
    if not out:
        return {"decision": "allow", "keys": [], "missing": []}
    spec = out.get("hookSpecificOutput") or {}
    if spec.get("permissionDecision"):
        decision, text = spec["permissionDecision"], spec.get("permissionDecisionReason") or ""
    elif out.get("decision") == "block":
        decision, text = "block", out.get("reason") or ""
    else:
        decision, text = "message", out.get("systemMessage") or ""
    return {"decision": decision, "keys": [_key(k) for k in shown.MARKER_RE.findall(text)],
            "missing": [[int(a), int(b)] for a, b in MISSING_RE.findall(text)]}


def _kind(name: str) -> str:
    if name == "Bash":
        return "Bash"
    if shown.is_ask(name):
        return "ask"
    if name in guard.FILE_TOOLS:
        return "file"
    return "mcp" if name.startswith("mcp__") else "other"


def _guard(event, plugin_root):
    try:
        return guard.judge(event, plugin_root)[0]
    except Exception as exc:  # noqa: BLE001 — guard.main과 같게: 내부 오류는 _degraded 판정
        return guard._degraded(event, f"guard 내부 오류({type(exc).__name__})")[0]


def _show(mode, inp) -> dict:
    try:
        return summarize(mode(inp))
    except Exception:  # noqa: BLE001 — 실제 hook은 fail-open(판정 없음). 여기서는 따로 센다
        return {"decision": "error", "keys": [], "missing": []}


def _stop_end(evs, i):
    """evs[i](assistant 텍스트)가 턴 끝이면 ("user"|"feedback"|"eof", 피드백 글), 아니면 None."""
    for ev in evs[i + 1:]:
        if not isinstance(ev, dict) or ev.get("isSidechain"):
            continue
        if ev.get("type") == "assistant":
            if any(b.get("type") in ("text", "tool_use") for b in _blocks(ev)):
                return None
            continue
        u = _user_entry(ev)
        if u is None:
            continue
        if u["feedback"]:
            return "feedback", u["text"]
        if u["meta"]:
            continue
        return "user", None
    return "eof", None


def _work_dirs() -> list[Path]:
    """사용자 config(TELEPHONY_TRIAGE_HOME)의 모든 프로필 work_dir. 못 읽으면 빈 목록."""
    try:
        from common import userconfig
        return [Path(str(userconfig.get(c, "work_dir"))).expanduser()
                for c in userconfig.profiles({}).values() if userconfig.get(c, "work_dir")]
    except Exception:  # noqa: BLE001 — 숫자 보조: 설정이 깨졌으면 기록 없음으로 본다
        return []


def _records(lines: list[str], recs: list[dict]) -> dict | None:
    """세션 시각 범위(첫 timestamp − SLACK ~ 마지막 timestamp) 안의 기록을 고정한 수. 확인할 것이 없으면 None — `anchor`가 없는
    옛 scripts, transcript에 시각이 없음(녹화본·stream-json), 그 범위의 기록이 없음(빈 work_dir·다른 TELEPHONY_TRIAGE_HOME).
    `{anchored: 0, unanchored: 0}`을 내지 않는다: 건너뛴 확인을 통과(unanchored 0)로 읽지 않게."""
    if not hasattr(shown, "anchor"):
        return None
    seq = shown.parse_events(lines)
    stamps = [t for t in (shown._epoch(e.get(k)) for e in seq for k in ("ts", "rts")) if t is not None]
    if not stamps:
        return None
    lo, hi = min(stamps) - shown.ANCHOR_SLACK, max(stamps)
    mine = [r for r in recs if (t := shown._epoch(r.get("at"))) is not None and lo <= t <= hi]
    if not mine:
        return None
    n = len(shown.anchor(seq, mine))
    return {"anchored": n, "unanchored": len(mine) - n}


def _replay_one(fi: int, lines: list[str], plugin_root, tmp: Path) -> list[dict]:
    evs = []
    for raw in lines:
        try:
            evs.append(json.loads(raw))
        except ValueError:
            evs.append(None)
    recorded = _recorded(evs)
    path = tmp / f"{fi}.jsonl"
    points = []
    feedback_since_user = False

    def prefix(i):
        # ponytail: 지점마다 prefix 파일을 다시 쓴다(O(줄 수²) 바이트). 큰 transcript가 느리면 한 파일에 append하며 진행
        path.write_text("\n".join(lines[:i + 1]) + "\n", encoding="utf-8")
        return str(path)

    for i, ev in enumerate(evs):
        if not isinstance(ev, dict) or ev.get("isSidechain"):
            continue
        u = _user_entry(ev)
        if u is not None:
            if u["feedback"]:
                feedback_since_user = True
            elif not u["meta"]:
                feedback_since_user = False
        if ev.get("type") != "assistant":
            continue
        cwd = ev.get("cwd") or str(tmp)
        blocks = _blocks(ev)
        for k, b in enumerate(blocks):
            if b.get("type") == "tool_use":
                name, tid = str(b.get("name") or ""), b.get("id")
                inp = {"transcript_path": prefix(i), "tool_name": name, "tool_input": b.get("input") or {},
                       "tool_use_id": tid, "cwd": cwd}
                outs = []
                if name == "Bash" or name.startswith("mcp__") or name in guard.FILE_TOOLS:
                    outs.append(("guard", summarize(_guard(inp, plugin_root))))
                if name == "Bash":
                    outs.append(("pre-bash", _show(show_guard.mode_pre_bash, inp)))
                elif shown.is_ask(name):
                    outs.append(("pre-ask", _show(show_guard.mode_pre_ask, inp)))
                points += [{"file": fi, "line": i + 1, "hook": h, "tool": _kind(name), **o, "recorded": recorded.get(tid)}
                           for h, o in outs]
            elif b.get("type") == "text" and isinstance(b.get("text"), str):
                later = any(x.get("type") in ("text", "tool_use") for x in blocks[k + 1:])
                end = None if later else _stop_end(evs, i)
                if end is None:
                    continue
                inp = {"transcript_path": prefix(i), "last_assistant_message": b["text"],
                       "stop_hook_active": feedback_since_user}
                rec = "block" if end[0] == "feedback" and shown.MARKER in end[1] else "ran"
                points.append({"file": fi, "line": i + 1, "hook": "stop", "tool": None,
                               **_show(show_guard.mode_stop, inp), "recorded": rec})
    return points


def _mismatch(p) -> bool:
    if p["recorded"] is None:
        return False
    if p["hook"] == "stop":
        return (p["recorded"] == "block") != (p["decision"] == "block")
    want = "deny:guard" if p["hook"] == "guard" else "deny:show_guard"
    return (p["recorded"] == want) != (p["decision"] == "deny")


def replay(files: list[list[str]], plugin_root=None, scripts=None) -> dict:
    """파일마다 줄 목록을 받아 결정 지점 판정과 요약을 낸다."""
    _load(scripts)
    with tempfile.TemporaryDirectory() as d:
        points = [p for fi, lines in enumerate(files) for p in _replay_one(fi, lines, plugin_root, Path(d))]
    denied = {(p["file"], p["line"]) for p in points if str(p["recorded"]).startswith("deny:")}
    recs = shown.read_records(_work_dirs()) if hasattr(shown, "read_records") else []
    per = [_records(lines, recs) for lines in files]
    records = None if any(r is None for r in per) else {
        k: sum(r[k] for r in per) for k in ("anchored", "unanchored")}
    return {"files": [{"index": fi, "lines": len(lines)} for fi, lines in enumerate(files)],
            "points": points,
            "summary": {"points": len(points),
                        "decisions": dict(sorted(Counter(f"{p['hook']}:{p['decision']}" for p in points).items())),
                        "recorded_deny": len(denied), "mismatch": sum(map(_mismatch, points)), "records": records}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hook_replay.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions", nargs="+", help="Claude Code transcript JSONL")
    parser.add_argument("--plugin-root", default=None)
    parser.add_argument("--scripts", default=None, help="guard·show_guard·common.shown을 읽을 plugin/scripts (기본 이 레포)")
    args = parser.parse_args(argv)
    files = []
    for s in args.sessions:
        try:
            files.append(Path(s).read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError) as exc:
            print(f"transcript를 읽지 못했다(순번 {len(files)}): {type(exc).__name__}", file=sys.stderr)
            return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps(replay(files, args.plugin_root, args.scripts), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
