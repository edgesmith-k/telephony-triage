#!/usr/bin/env python3
"""모듈 템플릿의 placeholder를 사내 실제 이름으로 바꾼다 (사내에서 실행).

    python3 -I -X utf8 tools/names_fill.py <레포 루트> tools/site_names/ofono-names-form.json            # 미리 보기(파일을 쓰지 않음)
    python3 -I -X utf8 tools/names_fill.py <레포 루트> tools/site_names/ofono-names-form.json --write

양식: {"platform": "ofono"|"android", "rows": [{"placeholder", "real", "kind", "count", "example_lines", "files"}]}.
"real"이 빈 행은 건너뛴다(placeholder로 남는다). 대상은 templates/module-skills/<platform>/** 와
templates/module-skills/modules.yaml의 그 플랫폼 블록뿐이다.
긴 placeholder부터 바꾼다(짧은 이름이 긴 이름의 앞부분인 경우가 있다 — 접두어 행은 남은 곳만 바뀐다).
채운 양식은 사내 값이므로 사내 밖으로 내지 않는다. 순서: tools/site_names/README.md.
"""
import json, re, sys
from pathlib import Path

def targets(root, platform):
    base = root / "templates/module-skills"
    return [base / "modules.yaml"] + sorted(p for p in (base / platform).rglob("*") if p.is_file())

def block(text, platform):                   # modules.yaml: `  <platform>:` 부터 다음 플랫폼 키 앞까지
    m = re.search(rf"(?m)^  {re.escape(platform)}:\n", text)
    e = re.search(r"(?m)^  \w+:\n", text[m.end():])
    return m.start(), m.end() + e.start() if e else len(text)

def main():
    root, form = Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    platform, rows = form["platform"], form["rows"]
    pairs = sorted(((r["placeholder"], r["real"]) for r in rows if r.get("real")), key=lambda p: -len(p[0]))
    total = 0
    for p in targets(root, platform):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        a, b = block(text, platform) if p.name == "modules.yaml" else (0, len(text))
        part = text[a:b]
        n = 0
        for old, new in pairs:
            n += part.count(old)
            part = part.replace(old, new)
        if n:
            total += n
            print(f"{n:4d}  {p.relative_to(root).as_posix()}")
            if "--write" in sys.argv:
                p.write_text(text[:a] + part + text[b:], encoding="utf-8", newline="\n")
    print(f"{platform}: 합계 {total}곳, 채운 행 {len(pairs)}/{len(rows)}" + ("" if "--write" in sys.argv else " (미리 보기)"))

if __name__ == "__main__":
    main()
