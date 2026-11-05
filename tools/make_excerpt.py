#!/usr/bin/env python3
"""make_excerpt.py — 모듈 eval case의 마스킹 발췌 `source.log`를 원본 로그에서 자른다 (H C1+D R7·R34, C1D §1.3).

    python3 tools/make_excerpt.py --case <case 디렉토리> --raw <원본 로그> [--against <원본 로그 dir>] --write|--check

`case.yaml` `origin`의 `lines` 구간(오름차순, 합계 ≤ 120줄)을 원본에서 잘라 로그 마스커(`new_masker(log_lines=True)`,
구간 전체에 하나)로 가리고, `--against`면 `fixture_residual.deny_list` 값을 메모리에서 `<APN#n>`·`<PLMN#n>`·`<AID#n>`·
`<CARRIER#n>`·`<DEV#n>`…(파일 안 번호)로 바꾼다. 1줄 `-- [마스킹 발췌] {log} {episode} 줄 {lines}`, 구간 사이 `-- [생략]`.
관문(걸리면 쓰지 않고 종료 1): 근거 regex가 모두 구간 안(원본 줄 또는 가린 줄 — 줄 번호 어긋남), `fixture_residual`
(거부 목록 포함)·`masking.residual`·`skillcheck.check_text`·`new_masker().find` 0건. `--check`는 다시 잘라 바이트 비교한다.
출력은 `masker`(sha256(masking.py)[:12])·`residual`(오늘) 값과 `파일:줄 종류`뿐, 원본 글자는 내지 않는다.
종료 코드: 0 통과, 1 관문·drift, 2 사용 오류.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))
sys.path.insert(0, str(REPO / "tools"))

import fixture_residual
from common import masking, skillcheck, yamlio

TOKEN = {"apn": "APN", "plmn": "PLMN", "aid": "AID", "carrier": "CARRIER", "device_node": "DEV", "host": "HOST",
         "product": "PRODUCT", "build": "BUILD", "build_time": "BUILD", "base64": "B64"}
OK, FAIL, USAGE = 0, 1, 2


class Usage(Exception):
    """사용 오류(종료 2)."""


def masker_id() -> str:
    return hashlib.sha256((REPO / "plugin/scripts/common/masking.py").read_bytes()).hexdigest()[:12]


def _origin(case: Path) -> tuple[dict, list[tuple[int, int]], list[str]]:
    data = yamlio.load(case / "case.yaml")
    origin = data.get("origin") if isinstance(data, dict) else None
    if not isinstance(origin, dict) or data.get("synthetic") is not False:
        raise Usage("case.yaml: synthetic: false와 origin이 필요하다")
    segs = skillcheck.parse_segments(origin.get("lines"))
    if segs is None or sum(b - a + 1 for a, b in segs) > skillcheck.EXCERPT_MAX_LINES:
        raise Usage("origin.lines: 'a-b,c-d' 오름차순·겹침 없음·합계 ≤ 120")
    if origin.get("log") not in skillcheck.ORIGIN_LOGS or not skillcheck.EPISODE_RE.fullmatch(str(origin.get("episode"))):
        raise Usage("origin.log·episode 형식")
    evidence = list(((data.get("expect") or {}).get("evidence")) or [])
    return origin, segs, evidence


def _deny_sub(lines: list[str], deny: dict) -> list[str]:
    rx = fixture_residual._deny_regex(deny)
    if rx is None:
        return lines
    text = "\n".join(lines)
    nums = {k: max((int(n) for n in re.findall(rf"<{k}#(\d+)>", text)), default=0) for k in set(TOKEN.values())}
    seen: dict[str, str] = {}

    def token(m: re.Match) -> str:
        value = m.group(0)
        if value not in seen:
            kind = TOKEN.get(deny[value][0], "VAL")
            nums[kind] = nums.get(kind, 0) + 1
            seen[value] = f"<{kind}#{nums[kind]}>"
        return seen[value]
    return [rx.sub(token, line) for line in lines]


def cut(case: Path, raw: Path, against: Path | None) -> tuple[str, list[str]]:
    """(쓸 글, 관문 지적 `줄 종류` 목록)."""
    origin, segs, evidence = _origin(case)
    lines = [ln.rstrip("\r") for ln in raw.read_bytes().decode("utf-8", "replace").split("\n")]
    if segs[-1][1] > len(lines):
        raise Usage(f"origin.lines가 원본 줄 수({len(lines)})를 넘는다")
    raw_cut = [lines[a - 1:b] for a, b in segs]
    flat = [ln for seg in raw_cut for ln in seg]
    masker = masking.new_masker("\n".join(flat), log_lines=True)
    masked = [masker.mask(ln) for ln in flat]
    deny = fixture_residual.deny_list(against) if against is not None else None
    if deny:
        masked = _deny_sub(masked, deny)
    body, i = [], 0
    for n, seg in enumerate(raw_cut):
        if n:
            body.append(skillcheck.SKIP_LINE)
        body += masked[i:i + len(seg)]
        i += len(seg)
    text = "\n".join([skillcheck.excerpt_header(origin), *body]) + "\n"
    problems = [f"evidence {k}: 구간 안에 없음(줄 번호 확인)" for k, rx in enumerate(evidence, 1)
                if not any(re.search(rx, ln) for ln in flat + masked)]
    with tempfile.TemporaryDirectory(prefix="tt-excerpt-") as d:
        tmp = Path(d) / "source.log"
        tmp.write_text(text, encoding="utf-8")
        problems += [f"{f['line']} {f['kind']}" for f in fixture_residual.check([tmp], deny)]
    problems += [f"{no} residual:{k}" for no, ln in enumerate(text.split("\n"), 1) for k in masking.residual(ln)]
    problems += [f"{f.get('line', 0)} {f['check']}:{f.get('rule')}" for f in skillcheck.check_text("source.log",
                                                                                                  text.encode("utf-8"))]
    problems += [f"? find:{f['kind']}" for f in masking.new_masker(text).find(text)]
    return text, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="make_excerpt.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--against", type=Path)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if not (args.case / "case.yaml").is_file() or not args.raw.is_file() or \
            (args.against is not None and not args.against.is_dir()):
        print("--case(case.yaml 있음)·--raw(파일)·--against(디렉토리)를 확인한다", file=sys.stderr)
        return USAGE
    (args.case / "files").mkdir(exist_ok=True)
    try:
        text, problems = cut(args.case, args.raw, args.against)
    except Usage as exc:
        print(f"{args.case.name}: {exc}", file=sys.stderr)
        return USAGE
    name = f"{args.case.name}/files/source.log"
    for p in problems:
        print(f"{name}:{p}")
    if problems:
        print(f"관문 실패 {len(problems)}건 — 쓰지 않음", file=sys.stderr)
        return FAIL
    dest = args.case / "files" / "source.log"
    if args.check:
        same = dest.is_file() and dest.read_bytes() == text.encode("utf-8")
        print(f"{name}: {'일치' if same else 'drift'}")
        return OK if same else FAIL
    dest.write_bytes(text.encode("utf-8"))
    print(f"{name}: {len(text.encode('utf-8'))}B, {text.count(chr(10))}줄 씀")
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    print(f"masker: {masker_id()}\nresidual: '{today}'")
    return OK


if __name__ == "__main__":
    sys.exit(main())
