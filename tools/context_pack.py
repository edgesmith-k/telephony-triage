#!/usr/bin/env python3
"""docs/tasks.md의 pack(S-n)이 지정한 파일·절만 출력한다. 모르는 pack·못 찾는 참조는 종료 2."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def pack_items(name):
    """tasks.md 표에서 pack의 `읽을 것` 항목을 [(path, [절...])]로 돌려준다."""
    for line in (ROOT / "docs/tasks.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == name:
            items = []
            for raw in cells[1].split(","):
                raw = raw.strip().strip("`").strip()
                if raw and raw != "—":
                    path, _, secs = raw.partition(" §")
                    items.append((path.strip(), secs.split("·") if secs else []))
            return items
    raise KeyError(name)


def section(text, num):
    """num 제목(예: 5.8)부터 같은 수준 이하의 다음 제목 전까지. 없으면 None."""
    lines, out, level = text.splitlines(), [], 0
    for ln in lines:
        m = re.match(r"(#+)\s+(\S+)", ln)
        if m and not level and m.group(2).rstrip(".") == num:
            level = len(m.group(1))
        elif m and level and len(m.group(1)) <= level:
            break
        if level:
            out.append(ln)
    return "\n".join(out) or None


def render(name):
    parts = []
    for path, secs in pack_items(name):
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
