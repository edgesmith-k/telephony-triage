"""contracts.md의 § 참조 유효성과 줄 바이트 상한 (diff 가독성, 4-b A).

1. 참조: 다른 문서·코드의 `contracts.md` + `§<대상>`과, contracts.md 안의 파일 이름 없는 `§<이름>`이 contracts.md의
   실제 제목을 가리킨다. `§3.2`처럼 번호면 그 번호로 시작하는 제목, 이름이면 제목 글(번호·백틱 뺌)과 낱말 단위로
   앞이 맞는다(참조가 제목 전체로 시작하거나 — `§작업 계획 drift` — 참조 전체가 제목의 앞부분 — `§표시 기록`).
   대상은 백틱·괄호·쉼표·마침표·`·` 등에서 끝나고, 끝 낱말에 붙은 조사(`§브랜치의`)는 떼고도 본다. `§A·§B`, `§A, §B`처럼 바로 이어진 대상도 같은 파일 참조다.
   contracts.md 안의 번호 참조(`04 §5.11`, `MODULE_SKILLS_PLAN_IMPL §2.2`)는 다른 문서 절이라 이름만 본다.
   `§<절>` 같은 자리 표시는 대상이 아니다.
2. 줄 상한: contracts.md의 모든 줄은 UTF-8 4,096B 이하다(긴 셀은 표 밖 세부 블록으로 푼다).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "docs" / "design" / "contracts.md"
GLOBS = ("docs/design/**/*.md", "docs/*.md", "plugin/**/*.md", "plugin/scripts/**/*.py", "tests/**/*.py",
         "tools/*.py", "opencode/**/*.md")
EXCLUDE = ("docs/history/", "tests/skill_evals/workspace/")
LINE_MAX = 4096

DOC_BEFORE = re.compile(r"([\w.-]+\.md)`?\s*$")              # `§` 바로 앞의 문서 이름
TARGET = re.compile(r"\d+(?:\.\d+)*|[^\s`()\[\],.·:;\"'*|<>]+(?: [^\s`()\[\],.·:;\"'*|<>]+)*")
CHAIN = re.compile(r"`?(?:·|, )`?")                          # `§A·§B`, `§A, §B`
PARTICLE = re.compile(r"(?:의|에서|에만|에|을|를|으로|로|와|과|은|는|이|가|도)$")
MIN_REFS = 250                                               # 파서가 망가져 참조를 못 찾으면 통과하지 않게


def _headings() -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^#{2,6} (.+)$", CONTRACTS.read_text(encoding="utf-8"), re.M)]


def _resolves(target: str, headings: list[str]) -> bool:
    if target[0].isdigit():
        return any(h == target or h.startswith(target + " ") for h in headings)
    for words in (target.split(), PARTICLE.sub("", target).split()):     # `§브랜치의`처럼 조사가 붙은 끝 낱말
        for h in headings:
            name = re.sub(r"^\d+(?:\.\d+)*\s+", "", h.replace("`", "")).split()
            if words and (words[:len(name)] == name or name[:len(words)] == words):
                return True
    return False


def _refs(rel: str, text: str):
    """(줄 번호, 대상) — contracts.md를 가리키는 § 참조."""
    own = rel == "docs/design/contracts.md"
    for n, line in enumerate(text.split("\n"), 1):
        prev_end = None                                      # 바로 앞 contracts 참조 대상의 끝
        for m in re.finditer("§", line):
            t = TARGET.match(line, m.end())
            doc = DOC_BEFORE.search(line[:m.start()])
            chained = prev_end is not None and CHAIN.fullmatch(line[prev_end:m.start()])
            if doc:
                hit = doc.group(1) == "contracts.md"
            else:
                hit = bool(chained) or (own and t is not None and not t.group(0)[0].isdigit())
            prev_end = t.end() if hit and t else None
            if hit and t:
                yield n, t.group(0)


def _files():
    seen = set()
    for pattern in GLOBS:
        for path in sorted(REPO.glob(pattern)):
            rel = path.relative_to(REPO).as_posix()
            if path.is_file() and rel not in seen and not rel.startswith(EXCLUDE):
                seen.add(rel)
                yield rel, path


def test_contracts_section_refs_resolve():
    headings = _headings()
    bad, count = [], 0
    for rel, path in _files():
        for n, target in _refs(rel, path.read_text(encoding="utf-8", errors="replace")):
            count += 1
            if not _resolves(target, headings):
                bad.append(f"{rel}:{n} §{target}")
    assert not bad, "contracts.md에 없는 절 참조:\n" + "\n".join(bad)
    assert count >= MIN_REFS, count


def test_contracts_lines_fit_4kb():
    long = [f"contracts.md:{n} {len(line.encode('utf-8'))}B"
            for n, line in enumerate(CONTRACTS.read_text(encoding="utf-8").split("\n"), 1)
            if len(line.encode("utf-8")) > LINE_MAX]
    assert not long, f"{LINE_MAX}B 넘는 줄 (표 밖 세부 블록으로 푼다):\n" + "\n".join(long)
