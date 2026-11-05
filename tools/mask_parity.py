#!/usr/bin/env python3
"""mask_parity.py — 로그 마스커 관문(B2 §3.5 1번, 숫자만). 사외 전용 점검이다.

    python3 tools/mask_parity.py <log>... [--baseline <baseline.json>] [--allow <regex>]... [--json]

로그마다 로그 마스커(`masking.new_masker(log_lines=True)`, `mask_pii.py` 치환 모드와 같다)로 줄을 가리고 센다:
- `kinds`: 종류별 토큰 수(`masker.counts`);
- `b64_path_shaped`: 경로 모양(`/`가 있고 `/` 조각이 모두 소문자·CamelCase 낱말)인데 `B64`로 가린 값 수 — 0이어야 한다;
- `residual`: 가린 줄에 남은 식별자 `masking.residual()` 종류별 수 — 비어야 한다.

`--baseline`은 `{<파일 이름>: {<종류>: <수>}}`(측정 마스커 mask2+mask3 수를 저장소 종류로 옮긴 것)이다. 종류마다
가린 수 ≥ 기준 수여야 한다. 출력은 숫자와 종류 이름뿐이며 원래 값·줄 내용은 내지 않는다.

종료 코드: 0 통과, 1 관문 실패(기준 미달·경로 모양 B64·남은 식별자), 2 사용 오류(파일·기준 JSON을 못 읽음).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import masking


def _path_shaped(value: str) -> bool:
    return "/" in value and all(masking._PATH_PART.fullmatch(p) for p in value.split("/") if p)


def measure(path: Path, allow: list[str]) -> dict:
    """한 파일의 숫자: `{lines, kinds, b64_path_shaped, residual}`."""
    raw = path.read_bytes().decode("utf-8", "replace")
    lines = [ln.rstrip("\r") for ln in raw.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    masker = masking.new_masker("\n".join(lines), allow, log_lines=True)
    path_shaped = 0
    residual: dict[str, int] = {}
    for line in lines:
        for _s, _e, kind, value in masker._spans(line):
            if kind == "B64" and _path_shaped(value):
                path_shaped += 1
        for kind, n in masking.residual(masker.mask(line), allow).items():
            residual[kind] = residual.get(kind, 0) + n
    return {"lines": len(lines), "kinds": dict(sorted(masker.counts.items())), "b64_path_shaped": path_shaped,
            "residual": dict(sorted(residual.items()))}


def compare(result: dict, baseline: dict) -> list[str]:
    """관문 실패 목록(파일 이름·종류·숫자만)."""
    fails = []
    for name, got in result.items():
        if got["b64_path_shaped"]:
            fails.append(f"{name}: 경로 모양 B64 {got['b64_path_shaped']}")
        if got["residual"]:
            fails.append(f"{name}: 남은 식별자 " + " · ".join(f"{k} {n}" for k, n in got["residual"].items()))
        for kind, want in sorted((baseline.get(name) or {}).items()):
            have = got["kinds"].get(kind, 0)
            if have < want:
                fails.append(f"{name}: {kind} {have} < 기준 {want}")
    return fails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mask_parity.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--baseline", help="{파일 이름: {종류: 수}} JSON")
    parser.add_argument("--allow", action="append", default=[], help="mask.allow_patterns 정규식(여러 번)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    baseline: dict = {}
    if args.baseline:
        try:
            baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
            if not isinstance(baseline, dict):
                raise ValueError("객체가 아님")
        except (OSError, ValueError) as exc:
            print(f"기준 JSON을 읽을 수 없습니다: {type(exc).__name__}", file=sys.stderr)
            return 2
    result = {}
    for name in args.logs:
        path = Path(name)
        if not path.is_file():
            print(f"파일이 없습니다: {path.name}", file=sys.stderr)
            return 2
        try:
            result[path.name] = measure(path, args.allow)
        except masking.AllowPatternError:
            print("--allow 정규식 오류", file=sys.stderr)
            return 2
    fails = compare(result, baseline)
    if args.json:
        print(json.dumps({"files": result, "fails": fails, "ok": not fails}, ensure_ascii=False, indent=1,
                         sort_keys=True))
    else:
        for name, got in result.items():
            kinds = " · ".join(f"{k} {n}" for k, n in got["kinds"].items())
            print(f"{name}: 줄 {got['lines']}, {kinds}, 경로 모양 B64 {got['b64_path_shaped']}, "
                  f"남은 식별자 {sum(got['residual'].values())}")
        for fail in fails:
            print(f"실패: {fail}")
        print("통과" if not fails else f"실패 {len(fails)}건")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
