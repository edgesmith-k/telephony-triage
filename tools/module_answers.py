#!/usr/bin/env python3
"""module_answers.py — 모듈 eval case 정답표("인정 후보 / 함정")를 만들고, 옛 explore expect를 schema 2로 옮긴다.

    python3 tools/module_answers.py table --platform ofono|android [--module m] [--kind explore|deep|all]
    python3 tools/module_answers.py migrate <case 디렉토리>...

- `table`: 표준출력에 한국어 md 표(읽기 전용, 토큰 0). `module_eval.load_case`로 검사한 case만 행으로 쓰고, 형식 오류는
  표 위에 `오류:` 줄. 생성물은 커밋하지 않는다(낡은 표 방지) — 사용자 확인용으로 그때그때 만든다.
- `migrate`: explore case.yaml의 옛 expect(layer·daemon·evidence·trap·wrong_layer)를 accept/trap(schema 2)으로 기계 변환
  (`accept = [옛 값 1개]`, `trap = [{label: w} for w in wrong_layer]` — 옛 wrong_layer 판정과 1:1). 이미 schema 2면 건너뛴다.
  case.yaml에서 `schema_version` 줄과 `expect:` 블록만 바꾼다. 바꾼 파일 목록을 출력한다.
종료 코드: 0 성공, 1 오류 case 있음(table) 또는 변환 실패(migrate), 2 사용 오류.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import module_eval as me  # noqa: E402
from common import yamlio  # noqa: E402

HEAD = ("explore는 '이런 후보가 있을 수 있다' — 답 목록에 인정 후보가 하나라도 있고, 가장 유력이 함정이 아니면 통과. "
        "deep은 결론 1개(스크립트 매칭 1위가 뒷받침).")
# 설계 검증 F1: 덧붙여도 싸게 맞는 정답(그 층 로그 없음·원인 아님) — 가장 유력이 그것인지(top1)를 따로 본다
COMMON_ADDON = "흔한 덧붙임 후보 — top1 확인"
ADDON_SAMPLES = ("그 층 로그 없음", "원인 아님")
CIRCLED = "①②③④⑤⑥⑦⑧"


def unfold(rx: str) -> str:
    """사람용 표기: `\\s*`·`\\s+` → 공백, `^`·`$`·`?:`·바깥 괄호 제거, `\\(`→`(`, `|` → ` 또는 `."""
    s = re.sub(r"\\s[*+?]?", " ", rx).replace("^", "").replace("$", "").replace("(?:", "(")
    s = re.sub(r"\s+", " ", s).strip()
    while s.startswith("(") and s.endswith(")") and _balanced(s[1:-1]):
        s = s[1:-1].strip()
    s = s.replace("\\(", "(").replace("\\)", ")").replace("\\.", ".")
    return re.sub(r"\s*\|\s*", " 또는 ", s)


def _balanced(s: str) -> bool:
    depth = 0
    for i, ch in enumerate(s):
        if ch == "(" and (i == 0 or s[i - 1] != "\\"):
            depth += 1
        elif ch == ")" and (i == 0 or s[i - 1] != "\\"):
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _code(rx: str) -> str:
    return "`" + rx.replace("|", "\\|") + "`"


def is_common_addon(accept: dict) -> bool:
    return any(re.match(r"\s*(?:" + accept["layer"] + ")", sample) for sample in ADDON_SAMPLES)


def _accept_text(a: dict) -> str:
    who = a.get("show") or f"{unfold(a['layer'])} / {unfold(a['daemon'])}"
    return _cell(who) + " · " + ", ".join(_code(e) for e in a["evidence"])


def _trap_text(t: dict) -> str:
    if t.get("show"):
        return _cell(t["show"])
    parts = [("데몬 " if k == "daemon" else "") + unfold(t[k]) for k in me.TRAP_MATCH_KEYS if k in t]
    return _cell(" · ".join(parts))


def _top1_text(results: dict | None, module_key: str, name: str) -> str:
    rec = ((((results or {}).get("modules") or {}).get(module_key) or {}).get("cases") or {}).get(name)
    if not isinstance(rec, dict):
        return "-"
    out = []
    for arm in me.ARMS:
        runs = rec.get(arm)
        runs = [runs] if isinstance(runs, dict) else (runs or [])
        vals = [r.get("top1") for r in runs if isinstance(r, dict)]
        if not vals or all(v is None for v in vals):
            return "-"
        out.append(f"{arm} {sum(v is True for v in vals)}/{len(vals)}")
    return " · ".join(out)


def case_row(case: me.Case, module_key: str = "", results: dict | None = None) -> str:
    summary = _cell(case.issue.get("summary", ""))
    exp = case.expect
    if case.kind == "explore":
        acc = "<br>".join(f"{CIRCLED[i]} {_accept_text(a)}" + (f" ({COMMON_ADDON})" if is_common_addon(a) else "")
                          for i, a in enumerate(exp["accept"]))
        trap = " / ".join(_trap_text(t) for t in exp["trap"])
        kind = "explore"
    else:
        acc = _accept_text(exp)
        trap = " / ".join(_cell(unfold(w)) for w in exp["wrong_layer"])
        if exp.get("trap"):
            trap += " (그 층 로그 없음 명시 필요)"
        kind = "deep(결론 1개)"
    return f"| {case.name} | {kind} | {summary} | {acc} | {trap} | {_top1_text(results, module_key, case.name)} |"


def table_lines(modules: list[tuple[str, list[me.Case], list[str]]], results: dict | None = None) -> list[str]:
    """modules = [(<platform>/<module>, 검사 통과 case, 오류 문구)] → md 줄."""
    out = ["# 모듈 eval 정답표 — 인정 후보 / 함정", "", HEAD, ""]
    for key, cases, errors in modules:
        out += [f"## {key}", ""]
        out += [f"오류: {e}" for e in errors]
        if errors:
            out.append("")
        out += ["| case | 종류 | 증상 | 인정 후보 (층 / 데몬 · 근거) | 함정 (가장 유력이면 실패) | top1 |",
                "|---|---|---|---|---|---|"]
        out += [case_row(c, key, results) for c in cases]
        out.append("")
    return out


def collect(platform: str, module: str | None, kind: str, root: Path = me.TEMPLATES):
    base = root / platform
    if not base.is_dir():
        raise SystemExit(f"플랫폼 디렉토리 없음: {base}")
    names = [module] if module else sorted(p.name for p in base.iterdir() if (p / "evals").is_dir())
    out = []
    for m in names:
        evals = base / m / "evals"
        if not evals.is_dir():
            raise SystemExit(f"모듈 evals 없음: {evals}")
        cases, errors = [], []
        for d in sorted(p for p in evals.iterdir() if p.is_dir() and (p / "case.yaml").is_file()):
            try:
                case = me.load_case(d)
            except me.CaseError as exc:
                errors.append(str(exc))
                continue
            if kind in ("all", case.kind):
                cases.append(case)
        out.append((f"{platform}/{m}", cases, errors))
    return out


# --- migrate (후보 설계 §2.3) -------------------------------------------------------------------------------

def migrate_expect(old: dict) -> dict:
    """옛 explore expect → schema 2. 옛 trap(below-layer-missing)은 accept layer(그 층 로그 없음)에 이미 들어 있어 뺀다."""
    return {"accept": [{"layer": old["layer"], "daemon": old["daemon"], "evidence": list(old["evidence"])}],
            "trap": [{"label": w} for w in old["wrong_layer"]]}


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def expect_yaml(exp: dict) -> str:
    lines = ["expect:", "  accept:"]
    for a in exp["accept"]:
        lines.append(f"    - layer: {_q(a['layer'])}")
        lines.append(f"      daemon: {_q(a['daemon'])}")
        lines.append("      evidence: [" + ", ".join(_q(e) for e in a["evidence"]) + "]")
        if "show" in a:
            lines.append(f"      show: {_q(a['show'])}")
    lines.append("  trap:")
    for t in exp["trap"]:
        keys = [k for k in (*me.TRAP_MATCH_KEYS, "show") if k in t]
        lines.append(f"    - {keys[0]}: {_q(t[keys[0]])}")
        lines += [f"      {k}: {_q(t[k])}" for k in keys[1:]]
    return "\n".join(lines) + "\n"


EXPECT_BLOCK_RX = re.compile(r"^expect:[^\n]*\n(?:(?:[ \t]+[^\n]*|[ \t]*)\n)*", re.MULTILINE)


def migrate_case(case_dir: Path) -> str | None:
    """case.yaml 하나 변환. 바꿨으면 경로, 건너뛰면 None. 실패는 ValueError."""
    path = Path(case_dir)
    if path.name != "case.yaml":            # case 디렉토리 또는 case.yaml 경로
        path = path / "case.yaml"
    text = path.read_text(encoding="utf-8")
    data = yamlio.loads(text)
    if not isinstance(data, dict) or data.get("kind") != "explore":
        return None
    if data.get("schema_version") == 2:
        return None
    old = data.get("expect")
    if not isinstance(old, dict) or not {"layer", "daemon", "evidence", "wrong_layer"} <= set(old):
        raise ValueError(f"{path}: 옛 expect 모양이 아님")
    new = migrate_expect(old)
    if not text.endswith("\n"):
        text += "\n"
    m = EXPECT_BLOCK_RX.search(text)
    if m is None:
        raise ValueError(f"{path}: expect 블록을 못 찾음")
    out = text[:m.start()] + expect_yaml(new) + text[m.end():]
    out, n = re.subn(r"(?m)^schema_version:\s*1\s*$", "schema_version: 2", out, count=1)
    if n != 1:
        raise ValueError(f"{path}: schema_version 줄을 못 찾음")
    back = yamlio.loads(out)
    if back.get("expect") != new or {k: v for k, v in back.items() if k not in ("expect", "schema_version")} != \
            {k: v for k, v in data.items() if k not in ("expect", "schema_version")}:
        raise ValueError(f"{path}: 변환 왕복이 맞지 않음")
    path.write_text(out, encoding="utf-8")
    return str(path)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="module_answers.py", description=__doc__.split("\n")[0], allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("table", allow_abbrev=False)
    t.add_argument("--platform", required=True, choices=("ofono", "android"))
    t.add_argument("--module")
    t.add_argument("--kind", choices=("explore", "deep", "all"), default="all")
    t.add_argument("--results", type=Path, default=me.RESULTS, help="top1 열을 읽을 기록(없으면 -)")
    mg = sub.add_parser("migrate", allow_abbrev=False)
    mg.add_argument("cases", nargs="+", type=Path)
    return ap


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if args.cmd == "table":
        try:
            mods = collect(args.platform, args.module, args.kind)
        except SystemExit as exc:
            print(exc, file=sys.stderr)
            return 2
        results = None
        if args.results and args.results.is_file():
            try:
                results = json.loads(args.results.read_text(encoding="utf-8"))
            except ValueError:
                results = None
        print("\n".join(table_lines(mods, results)))
        return 1 if any(errs for _, _, errs in mods) else 0
    code = 0
    for d in args.cases:
        try:
            done = migrate_case(d)
        except (OSError, ValueError) as exc:
            print(f"실패: {exc}", file=sys.stderr)
            code = 1
            continue
        if done:
            print(done)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
