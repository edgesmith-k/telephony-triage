"""Cross-check: for eval runs with a publish call, does approvals.json contain a Bash publish ask (guard rule 7)?"""
import sys, json, glob, re
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
import guard
from common import shown

def sees(cmd):
    for inv in guard.invocations(cmd, Path("/tmp")):
        name = guard._base(inv.argv[0])
        if (name == "db_pr.py" or (name.startswith("python") and any(guard._base(a) == "db_pr.py" for a in inv.argv[1:]))) and "publish" in inv.argv:
            return True
    return False

rows = []
for f in glob.glob(str(REPO / "tests/skill_evals/workspace/*/eval-*/with_skill/session.jsonl")):
    run_dir = Path(f).parent; it = run_dir.parent.parent.name; ev = run_dir.parent.name.split("-")[1]
    pubs = []
    for line in open(f, encoding="utf-8", errors="replace"):
        try: e = json.loads(line)
        except Exception: continue
        m = e.get("message") or {}
        for c in (m.get("content") if isinstance(m, dict) and isinstance(m.get("content"), list) else []):
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Bash":
                cmd = c["input"].get("command", "")
                if any(x.group(1) == "publish" for x in shown.PUSH_END.finditer(shown.command_of({"input": {"command": cmd}}))):
                    pubs.append(cmd)
    if not pubs: continue
    ap = REPO / f"tests/skill_evals/workspace/{it}/env-{ev}/approvals.json"
    recs = json.loads(ap.read_text(encoding="utf-8")) if ap.is_file() else None
    asked = None if recs is None else any(r.get("tool_name") == "Bash" and "publish" in str((r.get("input") or {}).get("command", "")) for r in recs)
    rows.append((it, ev, all(sees(c) for c in pubs), asked))
from collections import Counter
print(Counter((g, a) for _, _, g, a in rows))
for it, ev, g, a in rows:
    if not g or a is False:
        print(" ", it, "eval", ev, "guard_detects=", g, "approvals_has_publish_ask=", a)
