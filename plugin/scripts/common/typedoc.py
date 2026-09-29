"""type.md 읽기·엔티티 단위 쓰기 (03-issue-db.md §5.4 (1)·§5.7 (3), 06-collaboration.md §6.2).

`TypeDoc`은 frontmatter를 `data`(dict)로 들고, 저장할 때 **바뀐 엔티티만** 다시 쓴다:
- 최상위 키(`status`, `symptom_signatures` 등)는 값이 바뀐 키 블록만 새로 렌더링한다.
- `causes`는 원인 항목 단위(`id`로 식별)로 바뀐 원인만 새로 렌더링하고, 새 원인은 ID 순서 자리에 넣는다.
- 본문 "원인별 상세"의 `### <원인 ID> <title>` 섹션을 ID 순서로 넣는다.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from . import yamldoc, yamlio

CAUSE_HEADING_RE = re.compile(r"^### ([A-Z][A-Z0-9]*-\d{3}-\d{2})\b")
DETAIL_HEADING = "## 원인별 상세"


class TypeDocError(Exception):
    pass


def split(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise TypeDocError("frontmatter가 없습니다.")
    end = text.find("\n---\n", 3)
    if end < 0:
        raise TypeDocError("frontmatter 끝(---)이 없습니다.")
    return text[4:end + 1], text[end + 5:]


def id_key(cause_id: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in cause_id.split("-"))


class TypeDoc:
    def __init__(self, path: Path, text: str | None = None):
        self.path = Path(path)
        self.text = self.path.read_text(encoding="utf-8") if text is None else text
        self.front, self.body = split(self.text)
        self.data = yamlio.loads(self.front)
        if not isinstance(self.data, dict):
            raise TypeDocError(f"{self.path}: frontmatter가 매핑이 아닙니다.")
        self.orig = copy.deepcopy(self.data)
        self.new_sections: list[tuple[str, str, str]] = []   # (원인 ID, title, 본문)
        self.is_new = False

    @classmethod
    def new(cls, path: Path, front: dict, body: str) -> "TypeDoc":
        text = "---\n" + "".join(yamldoc.dump_key(k, v) for k, v in front.items()) + "---\n" + body
        doc = cls(path, text)
        doc.is_new = True
        return doc

    # -- 조회 -------------------------------------------------------------------------

    @property
    def id(self) -> str:
        return str(self.data.get("id"))

    def cause(self, cause_id: str) -> dict | None:
        return next((c for c in self.data.get("causes") or [] if c.get("id") == cause_id), None)

    def cause_numbers(self) -> list[int]:
        return [int(str(c.get("id")).rsplit("-", 1)[1]) for c in self.data.get("causes") or []
                if re.fullmatch(r".*-\d{2}", str(c.get("id")))]

    # -- 변경 -------------------------------------------------------------------------

    def add_cause(self, cause: dict, title: str, body: str) -> None:
        causes = list(self.data.get("causes") or [])
        causes.append(cause)
        causes.sort(key=lambda c: id_key(str(c.get("id"))))
        self.data["causes"] = causes
        self.new_sections.append((str(cause["id"]), title, body))

    @property
    def changed(self) -> bool:
        return self.is_new or self.data != self.orig or bool(self.new_sections)

    # -- 쓰기 -------------------------------------------------------------------------

    def render(self) -> str:
        lines = self.front.splitlines(keepends=True)
        for key, value in self.data.items():
            if key == "causes" or self.orig.get(key) == value:
                continue
            if key in self.orig:
                lines = yamldoc.replace_block(lines, key, yamldoc.dump_key(key, value))
            else:
                lines = lines + yamldoc.dump_key(key, value).splitlines(keepends=True)
        for key in [k for k in self.orig if k not in self.data]:
            lines = yamldoc.replace_block(lines, key, "")
        if self.data.get("causes") != self.orig.get("causes"):
            section = yamldoc.ListSection(lines, "causes", self.orig.get("causes") or [])
            text = section.render(self.orig.get("causes") or [], self.data.get("causes") or [],
                                  key_of=lambda c: c.get("id"))
            lines = yamldoc.replace_block(lines, "causes", text)
        front = "".join(lines)
        body = self._render_body()
        return "---\n" + front + "---\n" + body

    def _render_body(self) -> str:
        body = self.body
        for cause_id, title, text in sorted(self.new_sections, key=lambda s: id_key(s[0])):
            section = f"### {cause_id} {title}\n\n{text.rstrip()}\n"
            lines = body.splitlines(keepends=True)
            detail = next((i for i, line in enumerate(lines) if line.rstrip() == DETAIL_HEADING), None)
            if detail is None:
                body = body.rstrip("\n") + f"\n\n{DETAIL_HEADING}\n\n{section}"
                continue
            insert_at = None
            for i in range(detail + 1, len(lines)):
                if lines[i].startswith("## "):
                    insert_at = i
                    break
                m = CAUSE_HEADING_RE.match(lines[i])
                if m and id_key(m.group(1)) > id_key(cause_id):
                    insert_at = i
                    break
            if insert_at is None:
                body = body.rstrip("\n") + "\n\n" + section
            else:
                before = "".join(lines[:insert_at]).rstrip("\n") + "\n\n"
                body = before + section + "\n" + "".join(lines[insert_at:])
        return body

    def save(self) -> bool:
        if not self.changed:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.render(), encoding="utf-8", newline="\n")
        return True
