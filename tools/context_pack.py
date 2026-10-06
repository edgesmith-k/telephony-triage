#!/usr/bin/env python3
"""docs/tasks.md의 pack(S-n)을 출력한다: §15.5의 그 단계 행(할 일·완료 기준), 비고, `읽을 것`의 파일·절.
모르는 pack·못 찾는 참조는 종료 2."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STEPS = "docs/design/15-local-draft.md"


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def pack_row(name):
    """tasks.md 표에서 pack의 ([(path, [절...])], 비고)."""
    for line in (ROOT / "docs/tasks.md").read_text(encoding="utf-8").splitlines():
        cells = _cells(line)
        if len(cells) >= 2 and cells[0] == name:
            items = []
            for raw in cells[1].split(","):
                raw = raw.strip().strip("`").strip()
                if raw and raw != "—":
                    path, _, secs = raw.partition(" §")
                    items.append((path.strip(), secs.split("·") if secs else []))
            return items, (cells[2] if len(cells) > 2 else "")
    raise KeyError(name)


def pack_items(name):
    return pack_row(name)[0]


def step_row(name):
    """§15.5 표의 머리줄과 그 단계 행. 없으면 None."""
    lines = section((ROOT / STEPS).read_text(encoding="utf-8"), "15.5") or ""
    rows = [ln for ln in lines.splitlines() if ln.startswith("|")]
    hit = [ln for ln in rows if (_cells(ln)[0].strip("*").split() or [""])[0] == name]   # `S-0 (선택)`
    return "\n".join(rows[:2] + hit) if hit else None


def section(text, num):
    """제목 `num`(번호 `5.8` 또는 제목 글 `Step 8`)부터 같은 수준 이하의 다음 제목 전까지. 코드 펜스 안 `#`은 제목이 아니다."""
    out, level, fence = [], 0, False
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"(#+)\s+(.+?)\s*$", ln)
        if m and not level and (m.group(2).split()[0].rstrip(".") == num or m.group(2).startswith(num)):
            level = len(m.group(1))
        elif m and level and len(m.group(1)) <= level:
            break
        if level:
            out.append(ln)
    return "\n".join(out) or None


def render(name):
    items, note = pack_row(name)
    row = step_row(name)
    parts = [f"===== {STEPS} §15.5 {name} =====\n{row}\n"] if row else []
    if note:
        parts.append(f"===== 비고 =====\n{note}\n")
    if not items:
        parts.append("(이 단계는 고정으로 읽을 파일이 없다. 비고를 따른다)\n")
    for path, secs in items:
        f = ROOT / path
        if not f.is_file():
            raise FileNotFoundError(path)
        text = f.read_text(encoding="utf-8")
        for s in secs or [None]:
            body = text if s is None else section(text, s)
            if body is None:
                raise LookupError(f"{path} §{s}")
            parts.append(f"===== {path}{' §' + s if s else ''} =====\n{body.rstrip()}\n")
    return "\n".join(parts)


def main(argv):
    if len(argv) != 2:
        print("사용: context_pack.py <pack>  (예: S-3)", file=sys.stderr)
        return 2
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        print(render(argv[1]))
    except (KeyError, FileNotFoundError, LookupError) as e:
        print(f"context_pack: 찾을 수 없음: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
