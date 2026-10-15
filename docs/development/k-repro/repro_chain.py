"""Chain repro: screen never shown + `${S}db_pr.py publish` (SKILL.md `S/` convention).
show_guard (display aid) denies once, then only a systemMessage; guard rule 7 (the human gate) never asks."""
import sys, json, tempfile
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))
import test_show_guard as T
import test_hooks as H

S = 'S="python3 /p/scripts/"\n'
stage = S + "${S}db_pr.py stage /w/MOCK-1/plan.json --wt /w/MOCK-1/wt --branch issue/MOCK-1 --then-summary > /w/MOCK-1/screen.md"
pub = S + "${S}db_pr.py publish /w/MOCK-1/wt --branch issue/MOCK-1 --lease new --approved abc1234def --commit --and-discard --json"
tmp = Path(tempfile.mkdtemp(prefix="sg-chain-"))
base = [T.prompt("MOCK-1 분석하고 push까지 해줘"), T.bash("s1", stage, ""), T.say("stage 완료. 올리겠습니다.")]
p1 = T.write(tmp, *base, name="1.jsonl")
out1 = T.pre("pre-bash", p1, "Bash", {"command": pub}, tid="x1")
print("show_guard 1st publish :", T.decision(out1))
reason = out1["hookSpecificOutput"]["permissionDecisionReason"]
p2 = T.write(tmp, *base, T.call("x1", "Bash", {"command": pub}, "PreToolUse:Bash hook error: " + reason, True), name="2.jsonl")
out2 = T.pre("pre-bash", p2, "Bash", {"command": pub}, tid="x2")
print("show_guard 2nd (same)  :", T.decision(out2), "| systemMessage:", (out2 or {}).get("systemMessage"))
ws = H.shared()
real_pub = 'S="python3 %s/"\n${S}db_pr.py publish wt --branch issue/MOCK-1 --lease new --approved x --commit --and-discard --json' % (ws.root / "scripts")
print("guard rule 7 on publish:", H.decision(H.bash(ws, real_pub, ws.base)))
