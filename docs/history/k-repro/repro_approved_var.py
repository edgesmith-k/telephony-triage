"""Repro: show_guard pre-bash silently skips publish when --approved is a shell variable.
Uses the real transcript helpers from tests/test_show_guard.py (no repo files modified)."""
import sys, tempfile, json
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))
import test_show_guard as T  # helpers: prompt, say, bash, write, pre, decision

tmp = Path(tempfile.mkdtemp(prefix="sg-"))
# Case A: stage output hidden by redirection; model never displays the screen.
stage_hidden = "python3 /p/scripts/db_pr.py stage /w/MOCK-1/plan.json --wt /w/MOCK-1/wt --branch issue/MOCK-1 --then-summary > /w/MOCK-1/screen.md"
p = T.write(tmp, T.prompt("MOCK-1 분석하고 push까지 해줘"), T.bash("s1", stage_hidden, ""), T.say("stage 완료. 바로 올리겠습니다."), name="a.jsonl")
lit = "python3 /p/scripts/db_pr.py publish /w/MOCK-1/wt --branch issue/MOCK-1 --lease new --approved abc1234def --commit --and-discard"
var = 'H=$(python3 -c "import json;print(json.load(open(\'/w/MOCK-1/state.json\'))[\'approved_hash\'])"); python3 /p/scripts/db_pr.py publish /w/MOCK-1/wt --branch issue/MOCK-1 --lease new --approved "$H" --commit --and-discard'
print("A literal hash  :", T.decision(T.pre("pre-bash", p, "Bash", {"command": lit}, tid="t1")))
print("A variable hash :", T.pre("pre-bash", p, "Bash", {"command": var}, tid="t2"))
# Case B: screen in tool output (stdout) but never shown in text; publish without asking.
stage = "python3 /p/scripts/db_pr.py stage /w/MOCK-1/plan.json --wt /w/MOCK-1/wt --branch issue/MOCK-1 --then-summary"
p2 = T.write(tmp, T.prompt("MOCK-1 분석하고 push까지 해줘"), T.bash("s1", stage, T.SCREEN), T.say(T.SUMMARY), name="b.jsonl")
lit2 = lit
var2 = 'H=abc1234def; python3 /p/scripts/db_pr.py publish /w/MOCK-1/wt --branch issue/MOCK-1 --lease new --approved $H --commit --and-discard'
print("B literal hash  :", T.decision(T.pre("pre-bash", p2, "Bash", {"command": lit2}, tid="t3")))
print("B variable hash :", T.pre("pre-bash", p2, "Bash", {"command": var2}, tid="t4"))
