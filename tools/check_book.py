#!/usr/bin/env python3
"""안내서(책)·소개 자료 HTML 검사. 표준 라이브러리만 쓴다.

검사
    link      `#id` 링크가 같은 파일의 id로, 상대 링크(`../book/x.html#id`, `xx.html`)가 실제 파일·id로 이어짐
    dup-id    한 파일 안 id 중복
    external  `src`·`srcset`·`<link href>`, `<style>`·style 속성의 `@import`·`url()`이 http(s)·`//`로 외부를 부름
              (`<a href>`는 허용)
    command   본문의 `/telephony-triage:<이름>`에 맞는 `plugin/commands/<이름>.md`가 없음
    wording   금지 문구(과장된 결정성 표현 등)
    common    02 소개와 19 팀 소개의 `<style>`·`<script>`·hero·footer·공통 `<section>`이 글자 그대로 같고,
              목차 링크 순서가 같음(19 전용 절과 서로 다른 절은 `PROMO_ONLY`에 적은 id만 뺀다.
              title은 비교하지 않는다. hero 안 `<p class="hero-ask">` 한 줄은 파일마다 다른 첫 화면
              안내라 내용을 빼고 비교한다. 둘 다 대상일 때만 검사)

대상 기본값은 `docs/book/telephony-triage-book.html`과 `docs/materials/*.html`(`git add -A` 기준, 디스크에 있는 것)이다.
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
PROMO_PAIR = ("docs/materials/02-marketing.html", "docs/materials/19-team-intro.html")
# 공통 비교에서 빼는 절: story는 19에만, contact는 파일마다 다른 마무리. title은 비교하지 않고, 목차는 story·contact 링크를 뺀 순서만 비교한다.
PROMO_ONLY = {"story", "contact"}
VARIANT_RE = re.compile(r'(<p class="hero-ask">)[^\n]*?(</p>)')
TOC_RE = re.compile(r'<details class="toc".*?</details>', re.S)
BLOCK_RE = re.compile(r'<style>.*?</style>|<script>.*?</script>|<header class="hero">.*?</header>|<footer>.*?</footer>'
                      r'|<section id="([^"]+)"[^>]*>.*?</section>', re.S)
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
    # `git add -A`와 같은 기준(추적 + 무시되지 않은 새 파일). 반입 직후 스테이징 전이면 지운 파일이
    # 인덱스에 남고 새 파일은 미추적이라, 디스크에 있는 것만 남긴다.
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z", "--", "docs/materials/*.html"],
                         cwd=root, capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape").split("\0")
    return [root / BOOK] + [root / p for p in sorted(set(out)) if p and (root / p).is_file()]


def _blocks(src: str) -> list[tuple[str, int, str]]:
    """비교할 블록 (이름, 시작 위치, 본문). 절은 `PROMO_ONLY`를 뺀다."""
    out, n = [], {"style": 0, "script": 0}
    for m in BLOCK_RE.finditer(src):
        if m.group(1):
            if m.group(1) in PROMO_ONLY:
                continue
            key = f"section#{m.group(1)}"
        else:
            tag = re.match(r"<(\w+)", m.group(0)).group(1)
            n[tag] = n.get(tag, 0) + 1
            key = f"{tag}{n[tag]}"
        body = VARIANT_RE.sub(r"\1\2", m.group(0), count=1) if key.startswith("header") else m.group(0)
        out.append((key, m.start(), body))
    return out


def check_common(a: Path, b: Path, names: tuple[str, str] | None = None) -> list[str]:
    """두 소개 파일의 공통 블록이 같은지. 다르면 첫 차이를 양쪽 파일:행으로 하나 보인다."""
    na, nb = names or (str(a), str(b))
    sa, sb = a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8")
    toc = [[h for h in re.findall(r'href="([^"]+)"', (TOC_RE.search(x) or re.match("", x)).group(0))
            if h.lstrip("#") not in PROMO_ONLY] for x in (sa, sb)]
    if toc[0] != toc[1]:
        return [f"{na}: common: 목차 링크 순서가 {nb}와 다름 ({' '.join(toc[0])} / {' '.join(toc[1])})"]
    for name, src in ((na, sa), (nb, sb)):
        hero = re.search(r'<header class="hero">.*?</header>', src, re.S)
        n = len(VARIANT_RE.findall(hero.group(0))) if hero else 0
        if n != 1:
            return [f"{name}: common: hero의 hero-ask 줄이 {n}개 (정확히 1개여야 함)"]
    ba, bb = _blocks(sa), _blocks(sb)
    ka, kb = [k for k, _, _ in ba], [k for k, _, _ in bb]
    if ka != kb:
        return [f"{na}: common: 공통 블록 목록이 {nb}와 다름 ({' '.join(ka)} / {' '.join(kb)})"]
    for (key, pa, ta), (_, pb, tb) in zip(ba, bb):
        if ta == tb:
            continue
        i = next((j for j, (x, y) in enumerate(zip(ta, tb)) if x != y), min(len(ta), len(tb)))
        la = sa.count("\n", 0, pa) + ta.count("\n", 0, i) + 1
        lb = sb.count("\n", 0, pb) + tb.count("\n", 0, i) + 1
        return [f"{na}:{la}: common: {key}가 {nb}:{lb}와 다름"]
    return []


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
    pair = [(root / p).resolve() for p in PROMO_PAIR]
    if all(p in {f.resolve() for f in files} for p in pair):
        problems += check_common(*pair, names=PROMO_PAIR)
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
