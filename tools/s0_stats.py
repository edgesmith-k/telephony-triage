#!/usr/bin/env python3
"""s0_stats.py — S-0 선행 확인용 지표 (15-local-draft.md §15.5 S-0, docs/development/S0_PROBE_CHECKLIST.md).

사외 초안의 파서(`parse_logcat.py parse`)를 실제 로그에 돌려서 **개수와 비율만** 낸다. 로그 문구는 출력하지
않는다(태그 이름은 낸다). 결과는 사내 `SITE_PROFILE.md`에만 적는다.

    python3 tools/s0_stats.py <logcat...> --rules <parser-rules 디렉토리> --tz <IANA> [--year <YYYY>]
                              [--plugin-root <루트>] [--json]

`--plugin-root`: `site-defaults.yaml`이 있는 플러그인 루트. S-0는 S-3(그 파일을 만드는 단계)보다 앞이라
없을 수 있다. 그때는 `python3 tests/helpers/make_plugin_root.py`가 출력하는 임시 루트를 준다.

지표 (파일마다, 그리고 합계):
- 시각 파싱: 비어 있지 않은 원문 줄 수 대비 줄 레코드(`event` 없음) 수. 모자라면 형식을 못 읽은 줄이 있다.
- 태그 빈도 상위, RIL 요청 대비 응답 짝 맞춤 비율, `phone_id` 추출 비율.
- coverage: 시각 범위, 시계 이상(`backward`/`jump`) 개수, `warnings`·`errors` 개수.
"""

from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def parse(log: Path, args) -> dict:
    root = Path(args.plugin_root) if args.plugin_root else REPO / "plugin"
    cmd = [sys.executable, str(root / "scripts" / "parse_logcat.py"), "parse", str(log), "--full",
           "--rules", args.rules, "--tz", args.tz, "--mask", "--plugin-root", str(root)]
    if args.year:
        cmd += ["--year", str(args.year)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"parse_logcat 실패 ({log.name}, 종료 코드 {proc.returncode}):\n{proc.stderr.strip()[-600:]}")
    return json.loads(proc.stdout)


def stats(log: Path, data: dict) -> dict:
    events = data["events"]
    lines = [e for e in events if e.get("event") is None]
    raw = sum(1 for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())
    req = [e for e in events if (e.get("ril") or {}).get("dir") == "req"]
    paired = [e for e in req if e["ril"].get("paired_ts")]
    slotted = [e for e in lines if e.get("phone_id") is not None]
    coverage = data.get("coverage") or {}
    return {
        "file": log.name, "raw_lines": raw, "parsed_lines": len(lines),
        "tags": collections.Counter(e.get("tag") for e in lines),
        "ril_requests": len(req), "ril_paired": len(paired),
        "slot_lines": len(slotted),
        "first_ts": coverage.get("first_ts"), "last_ts": coverage.get("last_ts"),
        "clock_anomalies": len(coverage.get("clock_anomalies") or []),
        "warnings": len(data.get("warnings") or []), "errors": len(data.get("errors") or []),
        "backend": data.get("backend"),
    }


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({a / b:.0%})" if b else f"{a}/0 (-)"


def show(s: dict) -> None:
    print(f"[{s['file']}] 백엔드 {s['backend']}")
    print(f"  시각 파싱: {pct(s['parsed_lines'], s['raw_lines'])}   (모자라면 읽지 못한 줄이 있다)")
    print(f"  시각 범위: {s['first_ts']} ~ {s['last_ts']}   시계 이상 {s['clock_anomalies']}건")
    print(f"  RIL 짝 맞춤: {pct(s['ril_paired'], s['ril_requests'])}")
    print(f"  phone_id 추출: {pct(s['slot_lines'], s['parsed_lines'])}")
    print(f"  태그 상위: {s['tags'].most_common(8)}")
    print(f"  warnings {s['warnings']} / errors {s['errors']}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):   # 출력은 UTF-8 (Windows 콘솔 기본 인코딩과 무관하게)
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="s0_stats.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--rules", required=True, help="<이슈 DB>/parser-rules")
    ap.add_argument("--tz", required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("--plugin-root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    results = [stats(Path(p), parse(Path(p), args)) for p in args.logs]
    if args.json:
        for r in results:
            r["tags"] = dict(r["tags"])
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return 0
    for r in results:
        show(r)
    if len(results) > 1:
        total = {k: sum(r[k] for r in results) for k in ("raw_lines", "parsed_lines", "ril_requests", "ril_paired",
                                                          "slot_lines", "clock_anomalies")}
        print(f"[합계 {len(results)}개] 시각 파싱 {pct(total['parsed_lines'], total['raw_lines'])}, "
              f"RIL 짝 {pct(total['ril_paired'], total['ril_requests'])}, "
              f"phone_id {pct(total['slot_lines'], total['parsed_lines'])}, 시계 이상 {total['clock_anomalies']}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
