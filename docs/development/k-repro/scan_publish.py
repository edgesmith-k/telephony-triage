"""Scan recorded eval transcripts: every Bash command that runs db_pr.py publish (per show_guard's PUSH_END,
which was fixed for ${S}) vs. guard.py rule-7 detection (is_db_pr and "publish" in argv)."""
import sys, json, glob
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
import guard
from common import shown

def guard_sees_publish(cmd):
    for inv in guard.invocations(cmd, Path("/tmp")):
        name = guard._base(inv.argv[0])
        is_db_pr = name == "db_pr.py" or (name.startswith("python") and any(guard._base(a) == "db_pr.py" for a in inv.argv[1:]))
        if is_db_pr and "publish" in inv.argv:
            return True
    return False

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
