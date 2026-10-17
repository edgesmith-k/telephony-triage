#!/usr/bin/env python3
"""안내서(책)·소개 자료 HTML 검사. 표준 라이브러리만 쓴다.

검사
    link      `#id` 링크가 같은 파일의 id로, 상대 링크(`../book/x.html#id`, `xx.html`)가 실제 파일·id로 이어짐
    dup-id    한 파일 안 id 중복
    external  `src`·`srcset`·`<link href>`, `<style>`·style 속성의 `@import`·`url()`이 http(s)·`//`로 외부를 부름
              (`<a href>`는 허용)
    command   본문의 `/telephony-triage:<이름>`에 맞는 `plugin/commands/<이름>.md`가 없음
    wording   금지 문구(과장된 결정성 표현 등)

대상 기본값은 `docs/book/telephony-triage-book.html`과 git이 추적하는 `docs/materials/*.html`이다.
책의 숫자 중복(같은 수치가 장마다 다른지)은 오탐이 많아 검사하지 않는다.

CLI:
    python3 tools/check_book.py [파일 ...]   # 문제 있으면 `파일:행: 규칙: 이유`를 출력하고 종료 1
                                             # 대상 목록을 못 만들면(git 없음 등) 종료 2
"""

from __future__ import annotations

import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parents[1]
BOOK = "docs/book/telephony-triage-book.html"
BANNED = [
    "같은 로그면 누가 언제 돌려도",
    "같은 로그면 누가 돌려도",
    "같은 로그면 같은 후보",
    "팀 지식으로 굳지 않",
]
COMMAND_RE = re.compile(r"/telephony-triage:([a-z][a-z0-9-]*)")
EXTERNAL_RE = re.compile(r"(?i)^(https?:)?//")
CSS_EXTERNAL_RE = re.compile(r"""(?i)(@import\s+(?:url\(\s*)?|url\(\s*)['"]?((?:https?:)?//[^'")\s;]+)""")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[tuple[int, str]] = []
        self.links: list[tuple[int, str]] = []
        self.external: list[tuple[int, str, str]] = []
        self._in_style = False

    def _css(self, text: str, line: int, where: str) -> None:
        for m in CSS_EXTERNAL_RE.finditer(text):
            self.external.append((line + text.count("\n", 0, m.start()), where, m.group(2)))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if a.get("id"):
            self.ids.append((line, a["id"]))
        if tag == "a" and a.get("href"):
            self.links.append((line, a["href"]))
        for key in ("src", "href"):
            value = (a.get(key) or "").strip()
            if EXTERNAL_RE.match(value) and not (tag == "a" and key == "href"):
                self.external.append((line, tag, value))
        for cand in (a.get("srcset") or "").split(","):
            value = cand.strip().split(" ")[0]
            if EXTERNAL_RE.match(value):
                self.external.append((line, tag, value))
        if a.get("style"):
            self._css(a["style"], line, f"{tag} style")
        if tag == "style":
            self._in_style = True

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self._in_style = False

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self._css(data, self.getpos()[0], "style")


def _parse(path: Path) -> _Page:
    page = _Page()
    page.feed(path.read_text(encoding="utf-8"))
    page.close()
    return page


def default_targets(root: Path = REPO) -> list[Path]:
    out = subprocess.run(["git", "ls-files", "docs/materials/*.html"], cwd=root,
                         capture_output=True, text=True, check=True).stdout.split()
    return [root / BOOK] + [root / p for p in sorted(out)]


def check(files: list[Path], root: Path = REPO) -> list[str]:
    problems: list[str] = []
    cache: dict[Path, _Page] = {}

    def page(p: Path) -> _Page:
        p = p.resolve()
        if p not in cache:
            cache[p] = _parse(p)
        return cache[p]

    commands = {p.stem for p in (root / "plugin" / "commands").glob("*.md")}
    for f in files:
        f = f.resolve()
        name = f.relative_to(root.resolve()).as_posix() if f.is_relative_to(root.resolve()) else str(f)
        pg = page(f)
        seen: dict[str, int] = {}
        for line, i in pg.ids:
            if i in seen:
                problems.append(f"{name}:{line}: dup-id: id \"{i}\"가 {seen[i]}행에도 있음")
            else:
                seen[i] = line
        for line, tag, value in pg.external:
            problems.append(f"{name}:{line}: external: <{tag}>가 외부를 부름 {value}")
        for line, href in pg.links:
            if re.match(r"(?i)(https?:|mailto:|javascript:|//)", href):
                continue
            u = urlsplit(href)
            target = (f.parent / unquote(u.path)).resolve() if u.path else f
            if not target.exists():
                problems.append(f"{name}:{line}: link: 파일이 없음 {href}")
                continue
            if u.fragment and target.suffix == ".html" and u.fragment not in {i for _, i in page(target).ids}:
                problems.append(f"{name}:{line}: link: id가 없음 {href}")
        for n, text in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for cmd in COMMAND_RE.findall(text):
                if cmd not in commands:
                    problems.append(f"{name}:{n}: command: plugin/commands/{cmd}.md가 없음 (/telephony-triage:{cmd})")
            for w in BANNED:
                if w in text:
                    problems.append(f"{name}:{n}: wording: 금지 문구 \"{w}\"")
    return problems


def main(argv: list[str]) -> int:
    try:
        files = [Path(a) for a in argv] or default_targets()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"check_book: 대상 목록을 만들 수 없음(git ls-files 실패: {exc}). 파일을 인자로 주세요.", file=sys.stderr)
        return 2
    problems = check(files)
    for p in problems:
        print(p)
    print(f"check_book: {len(files)}개 파일, 문제 {len(problems)}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
