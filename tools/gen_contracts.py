#!/usr/bin/env python3
"""계약 문서의 생성 부분을 코드에서 만든다 (W7).

출력
    (a) `docs/design/contracts-cli.md` 전체: 스크립트별 서브커맨드·옵션(각 스크립트의 `build_parser()`)과
        `triage.py run` 출력 키 트리(`plugin/schemas/output/analysis.schema.json`).
    (b) `plugin/skills/telephony-triage/reference/db-authoring.md`의 "op 필수 키" 요약 블록
        (`plugin/schemas/plan.schema.json`). 블록 경계는 기존 앵커 줄(`op 필수 키 (` ~ `여기 없는 op·세부 제약은 …`)이다.

결정성: Python 3.11·3.14(CI 행렬)와 3.12(boundary job)에서 바이트가 같아야 하므로 `format_usage`/`format_help`
(버전마다 줄바꿈·문구가 다르다)를 쓰지 않고 `parser._actions`·`_mutually_exclusive_groups`·
`_SubParsersAction.choices`를 정의 순서 그대로 돈다(choices·option_strings도 정렬하지 않는다).

CLI:
    python3 tools/gen_contracts.py --check    # 생성 결과와 다르면 종료 코드 1
    python3 tools/gen_contracts.py --write    # 생성 결과로 덮어씀

종료 코드: 0 같음·갱신함 / 1 다름 / 2 사용 오류(목록 밖 CLI 스크립트, 요약 블록 1,152B 초과, 앵커 없음)
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO / "plugin" / "scripts"
CLI_DOC = REPO / "docs" / "design" / "contracts-cli.md"
ANALYSIS_SCHEMA = REPO / "plugin" / "schemas" / "output" / "analysis.schema.json"
PLAN_SCHEMA = REPO / "plugin" / "schemas" / "plan.schema.json"
DB_AUTHORING = REPO / "plugin" / "skills" / "telephony-triage" / "reference" / "db-authoring.md"

OK, DIFFERENT, USAGE = 0, 1, 2

# contracts.md §3.2 표 순서. argparse가 있는 CLI 스크립트(`build_parser()`)
SCRIPTS = ("config", "code_roots", "parse_logcat", "mask_pii", "jira_fields", "match_signatures", "db_search",
           "db_add", "db_build", "db_lint", "db_regress", "db_verify", "db_pr", "db_precommit", "db_review",
           "db_migrate", "guard", "jira_bridge", "triage")
# argparse 없이 stdin만 받는 스크립트
STDIN_ONLY = {"jira_bridge": "stdin: PostToolUse hook 입력 JSON"}
# `__main__`이 있지만 CLI가 아닌 모듈(현재 없음)
NOT_CLI: tuple[str, ...] = ()

BLOCK_START = "op 필수 키 ("
BLOCK_END = "여기 없는 op·세부 제약은 `SNAP/schema/plan.schema.json`\n"
BLOCK_MAX = 1152       # W7 add-fixture 세부 포함(그 전 1,024B)
# 요약에 싣는 op(순서 그대로)와 하위 필수 키를 펼칠 속성, 값 목록·조건부 필수·선택 키를 펼칠 속성
OPS = ("append", "unresolved", "new-cause", "new-type", "add-fixture", "update-signature", "add-parser-rule",
       "update-parser-rule", "set-resolution", "verify-resolution", "allow-cause", "reclassify", "update-fix",
       "add-code-ref", "set-status")
SUB_REQUIRED = {"new-cause": "cause", "new-type": "type", "verify-resolution": "verification"}
DETAIL = {"add-fixture": "kind"}

HEADER = """# CLI 계약 (생성)

> 자동 생성 — 직접 수정 금지(`python3 tools/gen_contracts.py --write`). 원본: 각 스크립트의 `build_parser()`,
> `plugin/schemas/output/analysis.schema.json`(triage 출력), `plugin/schemas/plan.schema.json`(db-authoring 요약).
> 서브커맨드·옵션 구문과 `analysis.json` 키 구조는 이 파일이 기준이다. 출력·동작·공통 규칙과 그 밖의 표·정의는 `contracts.md`(손으로 쓴다)가 기준이다.

표기: `<값>` 위치 인자·옵션 값, `[…]` 선택, `(a | b)` 하나 필수, `[a | b]` 하나까지, `{a,b}` 값 목록, `…` 여러 개.
"""


class GenError(Exception):
    pass


# -- argparse → 표 ---------------------------------------------------------------------------------


def _load_parsers() -> dict[str, argparse.ArgumentParser]:
    sys.path.insert(0, str(SCRIPTS_DIR))
    parsers = {}
    for name in SCRIPTS:
        if name in STDIN_ONLY:
            continue
        try:
            module = importlib.import_module(name)
        except ImportError as exc:      # 의존성(jsonschema·yaml) 없음 등: 생성하지 않고 사용 오류로 알린다
            raise GenError(f"{name}.py를 import하지 못했다: {exc}") from exc
        if not hasattr(module, "build_parser"):
            raise GenError(f"{name}.py: build_parser()가 없다")
        parsers[name] = module.build_parser()
    return parsers


def cli_scripts() -> list[str]:
    """`if __name__ == "__main__":`이 있는 plugin/scripts/*.py 이름."""
    return sorted(p.stem for p in SCRIPTS_DIR.glob("*.py")
                  if re.search(r"""^if __name__ == ["']__main__["']:""", p.read_text(encoding="utf-8"), re.M))


def _subparsers(parser: argparse.ArgumentParser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def _shown(action: argparse.Action) -> bool:
    return not isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)) and action.help != argparse.SUPPRESS


def _key(action: argparse.Action) -> str:
    return action.option_strings[0] if action.option_strings else "<" + action.dest + ">"


def _leaves(parser: argparse.ArgumentParser, prefix: str = ""):
    """(서브커맨드 이름, 파서). 서브-서브커맨드는 `lock acquire`처럼 펼친다. 같은 파서(별칭)는 한 번만."""
    sub = _subparsers(parser)
    if sub is None:
        yield prefix, parser
        return
    seen = set()
    for name, child in sub.choices.items():
        if id(child) in seen:
            continue
        seen.add(id(child))
        yield from _leaves(child, f"{prefix} {name}".strip())


def _value(action: argparse.Action) -> str:
    if action.choices is not None:
        return "{" + ",".join(str(c) for c in action.choices) + "}"
    if isinstance(action.metavar, str):
        return f"<{action.metavar}>"
    return "<" + (action.dest if not action.option_strings else action.dest.upper()) + ">"


def _token(action: argparse.Action) -> str:
    """괄호 없는 한 토큰(선택 여부는 호출자가 감싼다)."""
    nargs = action.nargs
    if not action.option_strings:
        value = _value(action)
        return {"+": f"{value}...", "*": f"[{value}...]", "?": f"[{value}]"}.get(nargs, value)
    opt = action.option_strings[0]
    if nargs == 0:
        return opt
    value = _value(action)
    if nargs == "+":
        return f"{opt} {value}..."
    if nargs == "*":
        return f"{opt} [{value}...]"
    if nargs == "?":
        return f"{opt} [{value}]"
    if isinstance(nargs, int):
        if isinstance(action.metavar, tuple):          # 값마다 이름이 다른 경우 (예: --between <ISO 시작> <ISO 끝>)
            return " ".join([opt] + [f"<{m}>" for m in action.metavar])
        return " ".join([opt] + [value] * nargs)
    return f"{opt} {value}"


def _usage(parser: argparse.ArgumentParser, skip: set[str]) -> str:
    groups = {}
    for group in parser._mutually_exclusive_groups:
        for action in group._group_actions:
            groups[id(action)] = group
    parts, done = [], set()
    for action in parser._actions:
        if not _shown(action) or _key(action) in skip:
            continue
        group = groups.get(id(action))
        if group is not None:
            if id(group) in done:
                continue
            done.add(id(group))
            members = [a for a in group._group_actions if _shown(a) and _key(a) not in skip]
            inner = " | ".join(_token(a) for a in members)
            parts.append(f"({inner})" if group.required else f"[{inner}]")
            continue
        token = _token(action)
        if action.option_strings and not action.required:
            token = f"[{token}]"
        if isinstance(action, argparse._AppendAction):
            token += "..."
        parts.append(token)
    return " ".join(parts)


def _clean(text: str) -> str:
    return " ".join(str(text).split())


def _describe(action: argparse.Action) -> str | None:
    bits = []
    if action.help:
        bits.append(_clean(action.help))
    default = action.default
    # `in (None, False, …)`은 0 == False라 기본값 0을 숨긴다. 동일성으로 거른다
    if not (default is None or default is False or default == [] or default is argparse.SUPPRESS):
        bits.append(f"기본 {default}")
    if not bits:
        return None
    return f"`{action.option_strings[0] if action.option_strings else action.dest}`: " + ", ".join(bits)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _option_notes(parser: argparse.ArgumentParser, skip: set[str]) -> str:
    notes = [d for a in parser._actions if _shown(a) and _key(a) not in skip for d in [_describe(a)] if d]
    return "; ".join(notes)


def render_script(name: str, parser: argparse.ArgumentParser | None) -> str:
    out = [f"## `{name}.py`", ""]
    if parser is None:
        out += [STDIN_ONLY[name] + " (argparse 없음)", ""]
        return "\n".join(out)
    leaves = list(_leaves(parser))
    sub = _subparsers(parser)
    common: list[argparse.Action] = []
    if sub is not None:
        # 공통 옵션 = 모든 서브커맨드에 있는 선택 옵션(위치 인자·상호 배제 그룹 소속 제외). 서브커맨드가 하나면 최상위에도 있어야 한다
        holders = [leaf for _, leaf in leaves] + ([parser] if len(leaves) == 1 else [])
        keysets = [{_key(a) for a in p._actions if _shown(a) and a.option_strings} for p in holders]
        for p in holders:
            for group in p._mutually_exclusive_groups:
                for keyset in keysets:
                    keyset.difference_update(_key(a) for a in group._group_actions)
        shared = set.intersection(*keysets)
        common = [a for a in leaves[0][1]._actions if _shown(a) and _key(a) in shared]
    skip = {_key(a) for a in common}
    if common:
        line = "; ".join(f"`{_token(a)}`" + (f" — {_clean(a.help)}" if a.help else "") for a in common)
        out += [f"공통 옵션(모든 서브커맨드): {line}", ""]
    out += ["| 서브커맨드 | 사용법 | 옵션 설명 |", "|---|---|---|"]
    rows = []
    if sub is not None:
        top_usage = _usage(parser, skip)
        if top_usage or not sub.required:
            rows.append(("(최상위)", top_usage, _option_notes(parser, skip)))
    for leaf_name, leaf in leaves:
        rows.append((leaf_name or "—", _usage(leaf, skip), _option_notes(leaf, skip)))
    for label, usage, notes in rows:
        usage_cell = f"`{_cell(usage)}`" if usage else ""
        label_cell = f"`{label}`" if not label.startswith(("(", "—")) else label
        out.append(f"| {label_cell} | {usage_cell} | {_cell(notes)} |")
    out.append("")
    return "\n".join(out)


# -- analysis.schema.json → 키 트리 ---------------------------------------------------------------------


def _resolve(schema: dict, node: dict) -> dict:
    while "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/$defs/"):
            raise GenError(f"지원하지 않는 $ref: {ref}")
        node = schema["$defs"][ref[len("#/$defs/"):]]
    return node


def _tree(schema: dict, node: dict, depth: int) -> list[str]:
    node = _resolve(schema, node)
    lines = []
    required = set(node.get("required") or [])
    for key, prop in (node.get("properties") or {}).items():
        prop = _resolve(schema, prop)
        label = key + ("" if key in required else "?")       # 옛 표기와 같게: `키?[≤N]`
        child = prop
        if prop.get("type") == "array":
            if isinstance(prop.get("items"), dict):
                child = _resolve(schema, prop["items"])
            limit = prop.get("maxItems")
            if limit is not None:
                label += f"[≤{limit}]"
            elif child.get("properties"):
                label += "[]"
        text = label
        if prop.get("description"):
            text += f"({_clean(prop['description'])})"
        if "const" in prop:
            text += ": " + json.dumps(prop["const"], ensure_ascii=False)
        elif "enum" in prop:
            text += ": " + " | ".join(str(v) for v in prop["enum"])
        lines.append("  " * depth + f"- {text}")
        if child.get("properties"):
            lines += _tree(schema, child, depth + 1)
    return lines


def render_analysis() -> str:
    schema = json.loads(ANALYSIS_SCHEMA.read_text(encoding="utf-8"))
    out = ["## `triage.py run` → analysis.json 키", "",
           "원본 `plugin/schemas/output/analysis.schema.json`. `키?`는 있을 때만, `(…)`는 설명, `[≤N]`은 목록 상한(`[]`는 상한 없는 객체 목록).",
           "`TT_SCHEMA_CHECK=1`(테스트·CI)이면 `triage.py run`이 출력을 이 스키마로 검사한다(위반이면 종료 코드 2).", ""]
    for status in ("ok", "needs_input", "stopped"):
        node = schema["$defs"][status]
        out.append(f"### `status: {status}`")
        out.append("")
        if node.get("description"):
            out += [_clean(node["description"]), ""]
        out += [line for line in _tree(schema, node, 0) if not line.startswith("- status")]
        out.append("")
    return "\n".join(out)


def render_cli_doc() -> str:
    missing = [n for n in cli_scripts() if n not in SCRIPTS and n not in NOT_CLI]
    if missing:
        raise GenError("SCRIPTS·STDIN_ONLY에 없는 CLI 스크립트: " + ", ".join(f"{n}.py" for n in missing)
                       + " — tools/gen_contracts.py 목록에 넣는다")
    parsers = _load_parsers()
    parts = [HEADER]
    for name in SCRIPTS:
        parts.append(render_script(name, parsers.get(name)))
    parts.append(render_analysis())
    return "\n".join(parts).rstrip("\n") + "\n"


# -- plan.schema.json → db-authoring 요약 블록 --------------------------------------------------------------


def render_block() -> str:
    schema = json.loads(PLAN_SCHEMA.read_text(encoding="utf-8"))
    ops = {b["properties"]["op"]["const"]: b for b in schema["$defs"]["operation"]["oneOf"]}
    lines = ["op 필수 키 (`op` 외, plan.schema.json 기준):"]
    for op in OPS:
        if op not in ops:
            raise GenError(f"plan.schema.json에 op `{op}`가 없다")
        body = ops[op]
        keys = [k for k in body["required"] if k != "op"]
        line = f"- `{op}`: " + ", ".join(keys)
        if op in SUB_REQUIRED:
            prop = SUB_REQUIRED[op]
            node = body["properties"][prop]
            sub = node.get("required") or _resolve(schema, node).get("required") or []
            line += f" — {prop}: " + "·".join(sub)
        if op in DETAIL:
            prop = DETAIL[op]
            detail = [f"{prop}: " + "·".join(body["properties"][prop]["enum"])]
            for cond in body.get("allOf") or []:
                when = ((cond.get("if") or {}).get("properties") or {}).get(prop, {}).get("enum")
                need = (cond.get("then") or {}).get("required")
                if when and need:
                    detail.append("·".join(when) + "면 " + "·".join(need) + " 필수")
            optional = [k for k in body["properties"] if k not in body["required"]]
            if optional:
                detail.append("선택 " + "·".join(optional))
            line += " — " + "; ".join(detail)
        lines.append(line)
    sig = schema["$defs"]["signature"]
    optional = [k for k in sig["properties"] if k not in sig["required"]]
    lines.append(f"- `signature`: {'·'.join(sig['required'])} 필수, 선택 {'·'.join(optional)}")
    block = "\n".join(lines) + "\n" + BLOCK_END
    size = len(block.encode("utf-8"))
    if size > BLOCK_MAX:
        raise GenError(f"db-authoring 요약 블록이 {size}B다(한도 {BLOCK_MAX}B) — OPS·DETAIL을 줄이거나 한도를 다시 정한다")
    return block


def splice_block(text: str, block: str) -> str:
    try:
        start = text.index(BLOCK_START)
        end = text.index(BLOCK_END, start) + len(BLOCK_END)
    except ValueError as exc:
        raise GenError(f"{DB_AUTHORING.relative_to(REPO)}: 요약 블록 앵커가 없다") from exc
    return text[:start] + block + text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gen_contracts.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        cli = render_cli_doc()
        authoring_old = DB_AUTHORING.read_text(encoding="utf-8")
        authoring = splice_block(authoring_old, render_block())
    except GenError as exc:
        print(f"gen_contracts: {exc}", file=sys.stderr)
        return USAGE
    targets = [(CLI_DOC, cli), (DB_AUTHORING, authoring)]
    if args.write:
        for path, text in targets:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8", newline="\n")
                print(f"갱신: {path.relative_to(REPO)}")
        return OK
    stale = [path for path, text in targets if not path.is_file() or path.read_bytes() != text.encode("utf-8")]
    if stale:
        for path in stale:
            print(f"생성 결과와 다름: {path.relative_to(REPO)}", file=sys.stderr)
        print("코드·스키마가 맞으면 `python3 tools/gen_contracts.py --write`로 다시 만든다.", file=sys.stderr)
        return DIFFERENT
    print(f"계약 생성물 최신 ({len(targets)}개)")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
