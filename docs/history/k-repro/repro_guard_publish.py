"""Repro: guard rule 7 (publish -> ask) misses `${S}db_pr.py publish` forms seen in real eval transcripts."""
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tests"))
import test_hooks as H

ws = H.shared()
root = ws.root / "scripts"
tail = "publish wt --branch issue/MOCK-1 --lease new --approved x --commit --and-discard --json"
cases = {
    "literal path": f'python3 "{root}/db_pr.py" {tail}',
    "$S/db_pr.py (S=dir)": f'S={root}; python3 $S/db_pr.py {tail}',
    "python3 ${S}db_pr.py (h1-e eval-29 form)": f'S="{root}/"; python3 ${{S}}db_pr.py {tail}',
    "${S}db_pr.py (S=\"python3 dir/\", sm4-1-b eval-67 form)": f'S="python3 {root}/"\n${{S}}db_pr.py {tail}',
    "$PY $S/db_pr.py": f'PY=python3; S={root}; $PY $S/db_pr.py {tail}',
    "cd + ./db_pr.py": f'cd {root} && ./db_pr.py {tail}',
}
for name, cmd in cases.items():
    out = H.bash(ws, cmd, ws.base)
    print(f"{name:55s} -> {H.decision(out)}")
