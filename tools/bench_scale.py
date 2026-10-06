#!/usr/bin/env python3
"""대용량 로그 처리 측정 (ARCHITECTURE_REVIEW_2026-10.md R15, DRAFT_NOTES 항목 8).

합성 logcat(커밋된 마스킹 fixture를 타일로 이어 붙이고 잡음 줄을 섞는다)을 만들어 단계별 시간과
메모리를 잰다. 최적화는 이 측정에서 임계값을 넘은 것만 적용한다 (아래 THRESHOLDS 표).

    python3 tools/bench_scale.py [--plugin-root <dir>] [--only parse,window,symbol]

출력은 JSON(stdout). 크기마다 자식 프로세스를 따로 띄워 `ru_maxrss`를 정확히 잰다
(자식 시간 상한 CHILD_TIMEOUT_SEC, 넘으면 `"timeout"`).

측정
  parse     단일 파일 10k·50k·200k줄, 2파일 50k줄: masker_init(`_read_texts`+`new_masker`),
            coverage, backend_parse, postprocess, parse_e2e(`parse --full --mask`),
            match_regress, match_analysis(가운데 ±5분), 최대 조건 hit 수, 최대 RSS, events.json 크기
  window    `Evaluator._search_window` 마이크로: hit K ∈ {500, 2000, 8000}, evaluate·evaluate_all 시간
  symbol    `code_roots.py find-symbol` 마이크로: 파일 수 F ∈ {5000, 20000}, `Foo#bar`·`bar` 시간

pytest가 모으지 않는다(`tools/`, 이름이 `test_*`가 아니다). 합성 로그에는 전화번호·IP 형태 값이 없다.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOG_DIR = REPO / "tests" / "fixtures" / "logs"
SAMPLE_DB = REPO / "tests" / "fixtures" / "issue-db-sample"
CHILD_TIMEOUT_SEC = 300
TZ, YEAR = "UTC", 2026

PARSE_SPECS = ["single:10000", "single:50000", "single:200000", "split:50000"]
WINDOW_SIZES = [500, 2000, 8000]
SYMBOL_SIZES = [5000, 20000]

# 최적화 적용 기준 (측정값이 넘을 때만 적용한다).
THRESHOLDS = {
    "O1": "window K=8000 evaluate > 1.0s 또는 t(8000)/t(2000) > 6 -> _search_window를 bisect로",
    "O2": "200k에서 coverage >= parse_e2e의 15% -> 읽기 공유(shared_reads)",
    "O3": "masker_init >= parse_e2e의 5% 또는 200k 최대 RSS > 입력 바이트의 10배 -> 스트리밍 observe",
    "O4": "20k 파일 트리에서 find-symbol > 3s -> os.walk + 바이트 사전 필터",
}

_STAMP = re.compile(r"^(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d{3})  (\d+)  (\d+) ([VDIWEFA]) (.*)$")
_NOISE_TAGS = ["DSM-0", "DPM-0", "DCM-0", "DSRM-0", "SST", "ImsManager"]
_NOISE_MSGS = ["periodic check ok", "heartbeat tick", "state unchanged", "poll complete", "cache refreshed"]
_BASE = datetime(2026, 9, 21, 10, 0, 0, tzinfo=timezone.utc)
_STEP_MS = 20  # 줄 사이 최소 간격 (시각이 줄 순서대로 늘도록)
_MAX_GAP_MS = 50_000  # 연속 줄 간격은 60초 미만 (시계 점프 판정과 무관하게)


def _tiles() -> list[list[tuple[int, str, str, str, str]]]:
    """fixture마다 [(앞 줄과의 간격 ms, pid 증분, level, tag, msg)]. 마스킹된 합성 로그만 쓴다."""
    out = []
    for path in sorted(LOG_DIR.glob("*.log")):
        prev, rows = None, []
        for text in path.read_text(encoding="utf-8").splitlines():
            m = _STAMP.match(text)
            if not m:
                continue
            mon, day, h, mi, s, ms = (int(m.group(i)) for i in range(1, 7))
            t = ((day * 24 + h) * 60 + mi) * 60_000 + s * 1000 + ms
            tag, _, msg = m.group(10).partition(": ")
            rows.append((0 if prev is None else min(max(t - prev, _STEP_MS), _MAX_GAP_MS),
                         int(m.group(7)), m.group(9), tag, msg))
            prev = t
        if rows:
            out.append(rows)
    return out


def generate(path_list: list[Path], lines: int) -> int:
    """`lines`줄을 시간순으로 만들어 파일 목록에 나눠 쓴다. 쓴 바이트 수를 준다.
    줄의 90%는 잡음이다. 같은 입력이면 같은 파일이 나온다."""
    tiles = _tiles()
    per_file = -(-lines // len(path_list))
    handles = [open(p, "w", encoding="utf-8", newline="\n") for p in path_list]
    total = n = tile_no = 0
    cursor = 0
    try:
        while n < lines:
            rows = tiles[tile_no % len(tiles)]
            pid_off = 1000 + (tile_no % 5000)
            for gap, pid, level, tag, msg in rows:
                for burst in range(10):
                    if n >= lines:
                        break
                    if burst == 9:
                        cursor += max(gap, _STEP_MS)
                        row = f"{pid + pid_off}  {pid + pid_off + 10} {level} {tag}: {msg}"
                    else:
                        cursor += _STEP_MS
                        ntag = _NOISE_TAGS[(n + burst) % len(_NOISE_TAGS)]
                        nmsg = _NOISE_MSGS[(n // 7 + burst) % len(_NOISE_MSGS)]
                        row = f"{pid + pid_off}  {pid + pid_off + 10} D {ntag}: [PHONE0] {nmsg} seq={n % 1000}"
                    t = _BASE + timedelta(milliseconds=cursor)
                    text = f"{t:%m-%d %H:%M:%S}.{t.microsecond // 1000:03d}  {row}\n"
                    handles[min(n // per_file, len(handles) - 1)].write(text)
                    total += len(text.encode("utf-8"))
                    n += 1
            tile_no += 1
    finally:
        for h in handles:
            h.close()
    return total


@contextlib.contextmanager
def _quiet(stdout_path: Path | None = None):
    out = open(stdout_path, "w", encoding="utf-8") if stdout_path else io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            yield
    finally:
        if stdout_path:
            out.close()


def _timed(fn):
    start = time.perf_counter()
    value = fn()
    return round(time.perf_counter() - start, 4), value


def _rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)  # Linux: KB


# -- 자식: 한 크기를 잰다 ----------------------------------------------------------------


def run_parse_one(spec: str, root: Path, work: Path) -> dict:
    kind, _, count = spec.partition(":")
    lines = int(count)
    paths = [work / "a.log"] if kind == "single" else [work / "a.log", work / "b.log"]
    nbytes = generate(paths, lines)

    sys.path.insert(0, str(root / "scripts"))
    import match_signatures
    import parse_logcat
    import parser_backends
    from common import masking, parser_rules, signatures

    rules_dir = SAMPLE_DB / "parser-rules"
    rules = parser_rules.load(rules_dir)
    backend = parser_backends.load("reference")
    res: dict = {"spec": spec, "lines": lines, "bytes": nbytes, "files": len(paths)}

    events_path = work / "events.json"
    argv = ["parse", *map(str, paths), "--full", "--mask", "--rules", str(rules_dir),
            "--tz", TZ, "--year", str(YEAR), "--plugin-root", str(root)]
    res["parse_e2e"], code = _timed(lambda: _call(parse_logcat.main, argv, events_path))
    res["parse_exit"] = code
    res["peak_rss_after_parse_mb"] = _rss_mb()
    res["events_json_bytes"] = events_path.stat().st_size

    allow: list[str] = []
    res["masker_init"], masker = _timed(lambda: masking.new_masker(parse_logcat._read_texts(paths), allow))
    res["coverage"], cov = _timed(lambda: backend.coverage(paths, TZ, YEAR))
    res["backend_parse"], events = _timed(lambda: backend.parse(paths, TZ, YEAR, None))
    res["postprocess"], out = _timed(lambda: parse_logcat.postprocess(
        events, rules, masker=masker, last_ts=cov["last_ts"], timeout_ms=2000))
    res["events"] = len(out)
    del events, out

    # 시그니처 조건별 hit 수 최대값 (조건 평가기를 감싸 센다)
    seen = {"max": 0}
    for name in ("lines", "matching_events"):
        orig = getattr(signatures.Evaluator, name)

        def wrap(self, arg, _orig=orig):
            hits = _orig(self, arg)
            seen["max"] = max(seen["max"], len(hits))
            return hits

        setattr(signatures.Evaluator, name, wrap)

    margv = ["--db", str(SAMPLE_DB), "--events", str(events_path), "--regress", "--top", "0",
             "--plugin-root", str(root)]
    res["match_regress"], code = _timed(lambda: _call(match_signatures.main, margv, work / "regress.json"))
    res["match_regress_exit"] = code

    doc = json.loads(events_path.read_text(encoding="utf-8"))
    ts = [e["ts"] for e in doc["events"]]
    mid = datetime.fromisoformat(ts[len(ts) // 2].replace("Z", "+00:00"))
    start, end = mid - timedelta(minutes=5), mid + timedelta(minutes=5)
    fmt = lambda d: f"{d:%Y-%m-%dT%H:%M:%S}.{d.microsecond // 1000:03d}Z"  # noqa: E731
    doc["events"] = [e for e in doc["events"] if fmt(start) <= e["ts"] <= fmt(end)]
    doc["input"]["mode"] = "around"
    doc["input"]["window"] = {"start": fmt(start), "end": fmt(end)}
    around = work / "around.json"
    around.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    meta = work / "meta.json"
    meta.write_text(json.dumps({"key": "BENCH-1", "occurred_at": mid.isoformat(), "sw": ""}), encoding="utf-8")
    aargv = ["--db", str(SAMPLE_DB), "--events", str(around), "--jira-meta", str(meta), "--top", "0",
             "--plugin-root", str(root)]
    res["match_analysis"], code = _timed(lambda: _call(match_signatures.main, aargv, work / "analysis.json"))
    res["match_analysis_exit"] = code
    res["match_analysis_events"] = len(doc["events"])

    res["max_condition_hits"] = seen["max"]
    res["peak_rss_mb"] = _rss_mb()
    return res


def _call(main, argv: list[str], stdout_path: Path):
    with _quiet(stdout_path):
        return main(argv)


def run_window_one(spec: str, root: Path, work: Path) -> dict:
    """`window:<K>:<evaluate|evaluate_all>` — 합성 이벤트에서 `_search_window` 시간."""
    _, k, which = spec.split(":")
    k = int(k)
    sys.path.insert(0, str(root / "scripts"))
    from common import signatures

    # 두 must_match 조건이 각각 K번 맞고(1초 간격으로 번갈아), 맞지 않는 must_not_match 하나.
    base = _BASE
    events = []
    for i in range(2 * k):
        word = "alpha" if i % 2 == 0 else "beta"
        events.append({"ts": f"{base + timedelta(seconds=i):%Y-%m-%dT%H:%M:%S}.000Z", "pid": 1, "tid": 1,
                       "level": "D", "tag": "T", "msg": f"{word} item {i}", "phone_id": 0,
                       "category_hint": None, "ril": None, "event": None, "fields": {}, "source": "bench"})
    sig = signatures.compile_signature(
        {"id": "w", "must_match": ["T: alpha", "T: beta"], "must_not_match": ["T: zzz"], "window_sec": 60},
        "BENCH")
    lo, hi = base, base + timedelta(seconds=2 * k)
    with signatures.Evaluator(events, lo, hi, 60_000) as ev:
        if which == "evaluate":
            sec, result = _timed(lambda: ev.evaluate(sig))
            found = int(result.satisfied)
        else:
            sec, results = _timed(lambda: ev.evaluate_all(sig))
            found = len(results)
    return {"spec": spec, "K": k, "fn": which, "seconds": sec, "results": found}


def run_symbol_one(spec: str, root: Path, work: Path) -> dict:
    """`symbol:<F>` — F개 소스 파일 트리에서 `Foo#bar`·`bar` 시간."""
    _, count = spec.split(":")
    files = int(count)
    tree = work / "src"
    body = "".join(f"    int field{j} = {j};  // filler line for scale measurement\n" for j in range(200))
    for n in range(files):
        d = tree / f"d{n % 8}" / f"e{n // 8 % 8}" / f"f{n // 64 % 8}" / f"g{n // 512 % 8}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"Gen{n}.java").write_text(f"class Gen{n} {{\n{body}}}\n", encoding="utf-8")
    target = tree / "d1" / "e1"
    (target / "Foo.java").write_text("class Foo {\n    void bar(int x) {\n    }\n}\n", encoding="utf-8")

    sys.path.insert(0, str(root / "scripts"))
    import code_roots

    res: dict = {"spec": spec, "files": files}
    for label, symbol in (("class_method", "Foo#bar"), ("function", "bar")):
        argv = ["find-symbol", symbol, "--roots", f"aosp={tree}", "--plugin-root", str(root)]
        res[label], code = _timed(lambda: _call(code_roots.main, argv, work / "symbol.json"))
        res[f"{label}_exit"] = code
    res["matches"] = len(json.loads((work / "symbol.json").read_text(encoding="utf-8"))["matches"])
    return res


def run_one(spec: str, root: Path) -> dict:
    work = Path(tempfile.mkdtemp(prefix="tt-bench-"))
    try:
        kind = spec.split(":")[0]
        if kind in ("single", "split"):
            return run_parse_one(spec, root, work)
        if kind == "window":
            return run_window_one(spec, root, work)
        return run_symbol_one(spec, root, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -- 부모 ---------------------------------------------------------------------------------


def _child(spec: str, root: Path):
    try:
        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--one", spec,
                               "--plugin-root", str(root)],
                              capture_output=True, text=True, encoding="utf-8", timeout=CHILD_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return "timeout"
    if proc.returncode != 0:
        return {"error": proc.stderr.strip().splitlines()[-1:] or ["?"]}
    return json.loads(proc.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plugin-root", default=None, help="없으면 테스트 헬퍼 루트를 임시로 만든다")
    parser.add_argument("--only", default="parse,window,symbol")
    parser.add_argument("--one", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    made = None
    if args.plugin_root:
        root = Path(args.plugin_root)
    else:
        sys.path.insert(0, str(REPO / "tests" / "helpers"))
        import make_plugin_root
        root = made = make_plugin_root.make()
    try:
        if args.one:
            json.dump(run_one(args.one, root), sys.stdout)
            return 0
        only = set(args.only.split(","))
        result: dict = {"thresholds": THRESHOLDS, "python": sys.version.split()[0]}
        if "parse" in only:
            result["parse"] = [_child(spec, root) for spec in PARSE_SPECS]
        if "window" in only:
            result["window"] = [_child(f"window:{k}:{fn}", root)
                                for k in WINDOW_SIZES for fn in ("evaluate", "evaluate_all")]
        if "symbol" in only:
            result["symbol"] = [_child(f"symbol:{f}", root) for f in SYMBOL_SIZES]
        json.dump(result, sys.stdout, indent=1)
        sys.stdout.write("\n")
        return 0
    finally:
        if made:
            shutil.rmtree(made, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
