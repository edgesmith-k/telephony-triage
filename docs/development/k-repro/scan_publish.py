"""Scan recorded eval transcripts: every Bash command that runs db_pr.py publish (per show_guard's PUSH_END,
which was fixed for ${S}) vs. guard.py rule-7 detection (runs_publish | publish_text, after the K P0-1 fix)."""
import sys, json, glob
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
import guard
from common import shown

def guard_sees_publish(cmd):
    # 수정 후 규칙 7 판정(guard.check_bash와 같은 합집합): argv `runs_publish` 또는 명령 글 `publish_text`
    return guard.publish_text(cmd) or any(guard.runs_publish(inv.argv) for inv in guard.invocations(cmd, Path("/tmp")))

seen = {}
for f in glob.glob(str(REPO / "tests/skill_evals/workspace/*/*/*/session.jsonl")) + glob.glob(str(REPO / "tests/skill_evals/workspace/*/*/*/events.jsonl")):
    run = str(Path(f).parent)
    for line in open(f, encoding="utf-8", errors="replace"):
        try: ev = json.loads(line)
        except Exception: continue
        msg = ev.get("message") or {}
        cont = msg.get("content") if isinstance(msg, dict) and isinstance(msg.get("content"), list) else []
        for c in cont:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Bash":
                cmd = (c.get("input") or {}).get("command", "")
                if "db_pr.py" not in cmd: continue
                ms = [m for m in shown.PUSH_END.finditer(shown.command_of({"input": {"command": cmd}})) if m.group(1) == "publish"]
                if not ms: continue
                key = (run, c.get("id"))
                if key in seen: continue
                seen[key] = (guard_sees_publish(cmd), cmd)
tot = len(seen); miss = [(k, v[1]) for k, v in seen.items() if not v[0]]
print("publish calls (show_guard PUSH_END):", tot, " guard rule-7 ask missed:", len(miss))
for (run, tid), cmd in miss:
    print(" -", run.split("workspace/")[1], "::", cmd.replace("\n", " \\n ")[:260])
