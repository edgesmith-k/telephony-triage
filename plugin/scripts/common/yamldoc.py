"""YAML 문서의 엔티티 단위 다시 쓰기 (06-collaboration.md §6.2, 03-issue-db.md §5.7 (3)).

`db_add.py`는 type.md frontmatter와 `parser-rules/*.yaml`을 **엔티티 단위로** 다시 쓴다. 파일 전체를
다시 덤프하면 손대지 않은 원인·규칙의 서식(흐름 표기, 주석, 빈 줄)까지 바뀌어 diff가 커지고 리뷰가
어려워진다. 그래서 텍스트를 최상위 키 블록과 목록 항목으로 나누고, **바뀐 엔티티만** 새로 렌더링한다.
바뀌지 않은 엔티티는 원래 텍스트를 그대로 둔다.

- 최상위 키 블록: 0열에서 `key:`로 시작하는 줄부터 다음 최상위 키 직전까지.
- 목록 항목: 블록 안에서 첫 항목과 같은 들여쓰기의 `- `로 시작하는 줄부터 다음 항목 직전까지.
  항목 끝의 빈 줄·주석 줄은 항목 사이 구분으로 보고 항목 텍스트에서 뺀다.

렌더링(`dump_item`, `dump_key`)은 결정적이다: 스칼라 목록과 작은 매핑은 흐름 표기, 그 밖은 블록 표기,
블록 목록은 들여 쓴다(`key:\\n  - a`). 같은 값은 항상 같은 텍스트가 된다.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

import yaml

TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(?:\s|$)")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FLOW_MAP_MAX = 90   # 이 길이(대략)를 넘는 매핑은 블록으로 쓴다


class YamlDocError(Exception):
    pass


# -- 덤프 ------------------------------------------------------------------------------


class _FlowList(list):
    pass


class _FlowMap(dict):
    pass


class _Dumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # 블록 목록을 키 아래로 들여 쓴다
        return super().increase_indent(flow, False)


def _rep_flow_list(dumper, data):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def _rep_flow_map(dumper, data):
    return dumper.represent_mapping("tag:yaml.org,2002:map", data.items(), flow_style=True)


def _rep_str(dumper, data):
    # 날짜 모양 문자열은 따옴표 없이 쓴다(이슈 DB 파일의 기존 표기와 같게). 읽을 때 yamlio가 다시 문자열로 바꾼다.
    if DATE_RE.match(data):
        try:
            return dumper.represent_date(datetime.date.fromisoformat(data))
        except ValueError:
            pass
    # 따옴표가 필요한 문자열(숫자·불리언·null처럼 읽히는 값)은 큰따옴표로 쓴다: android_versions: ["16"]
    if dumper.resolve(yaml.ScalarNode, data, (True, False)) != "tag:yaml.org,2002:str":
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_str(data)


_Dumper.add_representer(_FlowList, _rep_flow_list)
_Dumper.add_representer(_FlowMap, _rep_flow_map)
_Dumper.add_representer(str, _rep_str)


def _scalar(value) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _size(value) -> int:
    if isinstance(value, dict):
        return sum(len(str(k)) + _size(v) + 4 for k, v in value.items())
    if isinstance(value, list):
        return sum(_size(v) + 2 for v in value) + 2
    return len(str(value))


def _flowable(value) -> bool:
    if _scalar(value):
        return True
    if isinstance(value, list):
        return all(_scalar(v) for v in value)
    if isinstance(value, dict):
        return all(_flowable(v) for v in value.values())
    return False


def styled(value, top: bool = True):
    """덤프용 표기 표시. `top`은 블록으로 둘 최상위 값(원인, 규칙 항목)."""
    if isinstance(value, list):
        if all(_scalar(v) for v in value):
            return _FlowList(value)
        return [styled(v, top=False) for v in value]
    if isinstance(value, dict):
        if not top and _flowable(value) and _size(value) <= FLOW_MAP_MAX:
            return _FlowMap({k: styled(v, top=False) if isinstance(v, (list, dict)) else v
                             for k, v in value.items()})
        return {k: styled(v, top=False) for k, v in value.items()}
    return value


def _dump(value) -> str:
    return yaml.dump(value, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=4096,
                     default_flow_style=False)


def dump_item(value: dict, indent: int, flow: bool = False) -> str:
    """목록 항목 하나(`<indent>- ...`). `flow`면 한 줄 흐름 표기."""
    if flow:
        text = _dump([_FlowMap({k: styled(v, top=False) if isinstance(v, (list, dict)) else v
                                for k, v in value.items()})])
    else:
        text = _dump([styled(value, top=True)])
    pad = " " * indent
    return "".join(pad + line if line.strip() else line for line in text.splitlines(keepends=True))


def dump_key(key: str, value) -> str:
    """최상위 키 블록 하나."""
    if isinstance(value, dict):
        return _dump({key: styled(value, top=True)})
    if isinstance(value, list) and value and not all(_scalar(v) for v in value):
        return _dump({key: [styled(v, top=True) for v in value]})
    return _dump({key: styled(value, top=False)})


def dump_doc(value: dict) -> str:
    """작은 YAML 파일 전체 (Jira 기록, 피드백, `.expect.yaml`)."""
    return "".join(dump_key(k, v) for k, v in value.items())


# -- 텍스트 분할 -----------------------------------------------------------------------


@dataclass
class Span:
    start: int      # 줄 번호 (포함)
    end: int        # 줄 번호 (제외)


def _is_filler(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def top_blocks(lines: list[str]) -> list[tuple[str, Span]]:
    """최상위 키 블록. 첫 키 앞의 주석·빈 줄은 어느 블록에도 넣지 않는다."""
    starts = [(i, m.group(1)) for i, line in enumerate(lines) if (m := TOP_KEY_RE.match(line))]
    out = []
    for n, (i, key) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        out.append((key, Span(i, end)))
    return out


def list_items(lines: list[str], block: Span) -> list[Span]:
    """블록 안 목록 항목. 첫 `- ` 줄의 들여쓰기를 항목 들여쓰기로 본다."""
    indent = None
    starts = []
    for i in range(block.start + 1, block.end):
        line = lines[i]
        stripped = line.lstrip(" ")
        if not stripped.startswith("- ") and stripped.rstrip("\n") != "-":
            continue
        pad = len(line) - len(stripped)
        if indent is None:
            indent = pad
        if pad == indent:
            starts.append(i)
    items = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else block.end
        while end > i + 1 and _is_filler(lines[end - 1]):
            end -= 1
        items.append(Span(i, end))
    return items


def item_indent(lines: list[str], span: Span) -> int:
    line = lines[span.start]
    return len(line) - len(line.lstrip(" "))


class ListSection:
    """최상위 키 하나의 목록(예: `causes`, `extractors`)을 항목 단위로 고친다."""

    def __init__(self, lines: list[str], key: str, data: list):
        self.lines = lines
        self.key = key
        block = dict(top_blocks(lines)).get(key)
        if block is None:
            raise YamlDocError(f"최상위 키 {key}가 없습니다.")
        self.block = block
        self.items = list_items(lines, block)
        if len(self.items) != len(data or []):
            raise YamlDocError(f"{key}: 텍스트 항목 {len(self.items)}개와 YAML 항목 {len(data or [])}개가 다릅니다. "
                               "엔티티 단위로 다시 쓸 수 없는 형식이다 (직접 편집으로 정리한다).")
        self.indent = item_indent(lines, self.items[0]) if self.items else 2

    def render(self, old: list, new: list, key_of, flow: bool = False) -> str:
        """`new` 목록을 블록 텍스트로. `key_of(item)`로 옛 항목을 찾아 값이 같으면 원래 텍스트를 쓴다.

        항목 사이 구분 줄(빈 줄·주석)은 옛 항목 뒤의 것을 따라가고, 새 항목 뒤에는 이 파일의 관례
        (항목 사이에 빈 줄을 두는지)를 따른다. 마지막 항목 뒤 구분 줄은 블록 끝에 그대로 둔다."""
        old_index = {key_of(item): n for n, item in enumerate(old or [])}
        first = self.items[0].start if self.items else self.block.end
        out = self.lines[self.block.start:first]
        gaps = [self.lines[a.end:b.start] for a, b in zip(self.items, self.items[1:])]
        default_gap = ["\n"] if any(any(not g.strip() for g in gap) for gap in gaps) else []
        for k, item in enumerate(new):
            n = old_index.get(key_of(item))
            if n is not None and old[n] == item:
                out.extend(self.lines[self.items[n].start:self.items[n].end])
            elif n is not None and not flow and isinstance(item, dict):
                out.extend(self._render_fields(n, old[n], item))
            else:
                out.extend(dump_item(item, self.indent, flow=flow).splitlines(keepends=True))
            if k < len(new) - 1:
                out.extend(gaps[n] if n is not None and n < len(gaps) else default_gap)
        if self.items:
            out.extend(self.lines[self.items[-1].end:self.block.end])
        return "".join(out)

    def _render_fields(self, n: int, old: dict, new: dict) -> list[str]:
        """바뀐 항목 안에서도 **바뀐 필드만** 다시 쓴다(블록 표기 항목, 첫 필드는 `- ` 줄)."""
        span = self.items[n]
        lines = self.lines[span.start:span.end]
        field_pad = self.indent + 2
        starts = [0] + [i for i, line in enumerate(lines) if i > 0 and len(line) - len(line.lstrip(" ")) == field_pad
                        and TOP_KEY_RE.match(line[field_pad:])]
        first_key = TOP_KEY_RE.match(lines[0].lstrip(" ")[2:])
        keys = [first_key.group(1) if first_key else None] + [TOP_KEY_RE.match(lines[i][field_pad:]).group(1)
                                                              for i in starts[1:]]
        if keys != list(old.keys()):
            return dump_item(new, self.indent).splitlines(keepends=True)
        blocks = {key: lines[s:(starts[j + 1] if j + 1 < len(starts) else len(lines))]
                  for j, (key, s) in enumerate(zip(keys, starts))}
        out: list[str] = []
        for j, (key, value) in enumerate(new.items()):
            if key in old and old[key] == value and (j > 0) == (keys.index(key) > 0):
                out.extend(blocks[key])
                continue
            text = dump_key(key, value)
            rendered = [(" " * field_pad + line if line.strip() else line) for line in text.splitlines(keepends=True)]
            if j == 0:
                rendered[0] = " " * self.indent + "- " + rendered[0][field_pad:]
            out.extend(rendered)
        return out


def replace_block(lines: list[str], key: str, new_text: str) -> list[str]:
    block = dict(top_blocks(lines)).get(key)
    if block is None:
        raise YamlDocError(f"최상위 키 {key}가 없습니다.")
    # 블록 끝의 빈 줄·주석 줄(다음 키 앞 구분)은 둔다.
    end = block.end
    while end > block.start + 1 and _is_filler(lines[end - 1]):
        end -= 1
    return lines[:block.start] + new_text.splitlines(keepends=True) + lines[end:]
