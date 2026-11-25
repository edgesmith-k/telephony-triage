"""모듈 학습 제안 줄 `- [모듈] <p>/<m> <칸> — <한 줄> — 근거: <줄>` 읽기(5-2 explore-output.md 규칙 제안 목록, 반입 7 A-1·A-2).

`skill_patch.py --module`이 쓰고, check-output(A-1)도 같은 읽기를 쓸 수 있다. 번호 `n`은 파일 안 `- [모듈]` 줄 순서(1부터, 형식이
틀린 줄도 센다)다 — check-output 기록 `check-output.json[explore][KEPT_KEY]`(남긴 번호 목록)와 Step 7 선택이 같은 번호를 쓴다.
"""

from __future__ import annotations

import re

# 칸 → (문서, 절 제목 낱말). 절은 `## ` 제목에 낱말이 모두 들어 있는 첫 절이고, 없으면 patch 도구가 파일 끝에 `## <칸>`을 만든다
SLOTS = {"첫 점검": ("explore.md", ("첫 점검",)), "함정": ("explore.md", ("함정",)), "층 경로": ("explore.md", ("층 경로",)),
         "판독 주의": ("explore.md", ("판독 주의",)), "코드 경로": ("deep.md", ("코드 경로",)),
         "버전 차이": ("deep.md", ("버전", "차이"))}
HELD_SLOTS = ("첫 점검", "함정")       # 확정 원인에서만 — 보류(decision held)면 고르지 않는다
KEPT_KEY = "module_lines"              # check-output 기록에 남긴 `n` 목록(근거 원문 확인을 통과한 줄)
HEAD = "- [모듈]"
LINE_RX = re.compile(r"^- \[모듈\] ([a-z][a-z0-9_]*)/([a-z]+) (\S+(?: \S+)?) [—–] (.+) [—–] 근거\s*[:：]\s*(.+)$")


def parse(text: str) -> list[dict]:
    """`- [모듈]`로 시작하는 줄마다 `{n, ok, platform, module, slot, text, basis, why}`(ok가 아니면 why만 믿는다)."""
    out = []
    for line in (text or "").split("\n"):
        line = line.rstrip("\r").strip()
        if not line.startswith(HEAD):
            continue
        n = len(out) + 1
        m = LINE_RX.match(line)
        if not m:
            out.append({"n": n, "ok": False, "why": "형식이 다르다(- [모듈] <p>/<m> <칸> — <한 줄> — 근거: <줄>)", "raw": line})
            continue
        p, mod, slot, body, basis = (g.strip() for g in m.groups())
        ok = slot in SLOTS
        out.append({"n": n, "ok": ok, "platform": p, "module": mod, "slot": slot, "text": body, "basis": basis,
                    "doc": SLOTS[slot][0] if ok else None, "why": None if ok else f"모르는 칸({slot})", "raw": line})
    return out

