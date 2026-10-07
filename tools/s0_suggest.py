#!/usr/bin/env python3
"""s0_suggest.py — S-0/S-4 보조: 사내 logcat에서 `tags.yaml`·`platform.*` 설정 **초안**을 제안한다.

    python3 tools/s0_suggest.py <logcat...> --rules <parser-rules 디렉토리> --tz <IANA> [--year <YYYY>]
                                [--plugin-root <루트>] [--min-count 3] [--shapes <태그 정규식>] [--json]

**출력은 사내 전용이다. 사외로 반출하지 않는다.** 개수·태그 이름·숫자를 가린 메시지 모양만 나오지만 모양도 문구다
(벤더 접두어가 남는다). 파일은 쓰지 않는다(stdout만). 제안은 **사용자 확인 후** 사람이 `tags.yaml` PR·
`site-defaults.yaml`에 옮긴다. 메시지 모양은 마스커 -> 숫자·16진 런을 `#`로 바꾼 것이고, `--min-count` 미만 모양은 숨긴다.

절: 1 줄 형식 / 2 미수집 태그 후보 + tags.yaml diff / 3 슬롯 표기 후보 / 4 RIL 계열 태그 후보 + `platform.ril.vendor`
초안 / 5 파싱률 요약 / (`--shapes`) 임의 태그의 상위 모양. 지표 계산은 `s0_stats`를 재사용한다.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import difflib
import json
import re
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import s0_stats  # noqa: E402

# AOSP 공개 태그만 (벤더 태그는 넣지 않는다): 태그 전체 일치 -> 카테고리. 모르면 '?'.
AOSP_CATEGORIES = [
    (r"(?:DSMGR|DNC|DPM|DRM|DCM|DSRM)-\d+", "data"), (r"DSM-[CI]-\d+", "data"), (r"DN-\d+-[CI]", "data"),
    (r"(?:SST|ServiceStateTracker)(?:-\d+)?", "network"), (r"Ims\w*", "ims"),
    (r"Uicc\w*|SubscriptionManagerService", "sim"), (r"Sms\w*", "sms"),
    (r"AirplaneModeStats|CarrierConfig\w*", "common"),
]
NUM = re.compile(r"0x[0-9a-fA-F]+|\d+")
WINDOW = 2.0  # ponytail: RILJ 요청/응답 +-2s 고정 창. 사내 분포(R4)를 보고 조정


def shape(masker, text: str, n: int = 100) -> str:
    return NUM.sub("#", masker.mask(text))[:n]


def shape_regex(sh: str, group: str | None = None) -> str:
    """모양(`#` = 숫자) -> 정규식. `-C-#`의 C/I는 `[CI]`. group이 있으면 마지막 `#`가 그 그룹."""
    parts = re.split(r"(#|(?<=-)[CI](?=-#))", sh)
    last = max((i for i, p in enumerate(parts) if p == "#"), default=-1)
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(r"\d+" if p == "#" and not (group and i == last) else (f"({group})" if p == "#" else "[CI]"))
        else:
            out.append(re.escape(p).replace("\\-", "-").replace("\\ ", " "))
    return "".join(out)


def prefix_shape(masker, text: str) -> str:
    """RIL 초안용 접두어 모양: 마스커 토큰 \x02, `=값` 값 \x03, 숫자·16진 런 \x01 (제어 문자 자리표시자)."""
    t = re.sub(r"<[A-Z][A-Z_]*#?\d*>", "\x02", masker.mask(text))
    t = re.sub(r"=\S+", "=\x03", t)
    return re.sub(r"0x[0-9a-fA-F]+|\b[0-9a-fA-F]*\d[0-9a-fA-F]*\b|\d+", "\x01", t)


def prefix_regex(sh: str) -> str:
    sub = {"\x01": r"(?:0x[0-9a-fA-F]+|\d+)", "\x02": r"\S+", "\x03": r"\S+"}
    return "".join(sub.get(p) or re.escape(p).replace("\\-", "-").replace("\\ ", " ") for p in re.split("([\x01-\x03])", sh))


def y(p: str) -> str:
    return "'" + p.replace("'", "''") + "'"


def format_counts(log: Path, logcat) -> dict:
    c = collections.Counter()
    with logcat.open_log(log) as fh:
        for raw in fh:
            t = raw.rstrip("\r\n")
            c["beginning"] += t.startswith("--------- beginning of ")
            if not t.strip() or t.startswith(logcat.BEGINNING_PREFIX):
                continue
            kind, m = "threadtime", logcat.THREADTIME_RE.match(t)
            if not m:
                kind, m = "time", logcat.TIME_RE.match(t)
            if not m:
                c["unparsed"] += 1
                continue
            c[kind] += 1
            for g in ("year", "zone", "uid"):
                c[g] += bool(m.group(g))
    return c


def tags_section(lines, all_tags, coll, rules_dir, today, min_count, ril_tags) -> dict:
    phone_pids = {ln.pid for ln in lines if ln.tag in coll or ln.tag in ril_tags}
    unc = all_tags - coll
    in_pid = collections.Counter(ln.tag for ln in lines if ln.tag in unc and ln.pid in phone_pids)
    groups: dict[str, dict] = {}
    for tag, n in unc.items():
        cat = next((c for p, c in AOSP_CATEGORIES if re.fullmatch(p, tag)), None)
        if cat is None and in_pid[tag] * 2 < n:
            continue
        sh = re.sub(r"\d+", "#", tag)
        rx = "^" + shape_regex(sh) + "$" if "#" in sh else None
        g = groups.setdefault(rx or sh, {"tag": sh, "rx": rx, "lines": 0, "category": cat or "?",
                                         "why": "접두어 표" if cat else "phone pid"})
        g["lines"] += n
    shown = sorted((g for g in groups.values() if g["lines"] >= min_count), key=lambda g: -g["lines"])[:15]
    new = []
    for g in shown:
        key = f"tag_regex: {y(g['rx'])}" if g["rx"] else f"tag: {g['tag']}"
        cat = y("?") if g["category"] == "?" else g["category"]
        new.append(f"  - {{{key}, category: {cat}, added_for: '-', added_on: {today}, reason: s0_suggest 후보}}")
    path = Path(rules_dir) / "tags.yaml"
    old = path.read_text(encoding="utf-8") if path.is_file() else ""
    if old and not old.endswith("\n"):
        old += "\n"
    diff = "".join(difflib.unified_diff(old.splitlines(True), (old + "\n  # --- s0_suggest 후보 ---\n" + "\n".join(new) + "\n").splitlines(True),
                                        "tags.yaml", "tags.yaml(제안)")) if new else ""
    items = (yaml.safe_load(old) or {}).get("tags") or [] if old else []
    zero = []
    for it in items:
        k = it.get("tag") or it.get("tag_regex")
        hit = (lambda t: t == it["tag"]) if "tag" in it else (lambda t, r=re.compile(it["tag_regex"]): r.search(t))
        if not any(hit(t) for t in all_tags):
            zero.append(k)
    return {"candidates": [{k: g[k] for k in ("tag", "rx", "lines", "category", "why")} for g in shown],
            "diff": diff, "zero_line_rules": zero}


def slots_section(lines, tags_ok, phone, logcat, min_count) -> dict:
    rules = {"tag": logcat.PhoneIdRules(phone.tag, (), ()), "msg_prefix": logcat.PhoneIdRules((), phone.prefix, ()),
             "msg_suffix": logcat.PhoneIdRules((), (), phone.suffix)}
    forms = collections.defaultdict(lambda: [0, 0])
    for ln in lines:
        if ln.tag not in tags_ok:
            continue
        found = []
        sh = re.sub(r"\d+", "#", ln.tag)
        if re.fullmatch(r"[A-Za-z]+(?:-[A-Za-z]+)?-#", sh):
            found.append(("tag", sh))
        for pos, rx in (("msg_prefix", r"^\[([A-Za-z]+)\d+\]"), ("msg_suffix", r"\[([A-Za-z]+)\d+\]$")):
            m = re.search(rx, ln.msg)
            if m:
                found.append((pos, f"[{m.group(1)}#]"))
        for pos, key in found:
            forms[(pos, key)][rules[pos].phone_id(ln.tag, ln.msg) is None] += 1
    rows = [{"position": p, "shape": k, "matched": a, "unmatched": b} for (p, k), (a, b) in sorted(forms.items())
            if a + b >= min_count]
    draft: dict[str, list[str]] = {}
    for r in rows:
        if r["unmatched"] >= min_count:
            p, k = r["position"], r["shape"]
            w = re.escape(k[1:-2])
            pat = {"tag": lambda: "^" + shape_regex(k, r"\d+"), "msg_prefix": lambda: rf"^\[{w}(\d+)\]\s?",
                   "msg_suffix": lambda: rf"\s?\[{w}(\d+)\]$"}[p]()
            draft.setdefault(p, [x.pattern for x in {"tag": phone.tag, "msg_prefix": phone.prefix, "msg_suffix": phone.suffix}[p]])
            draft[p].append(pat + ("$" if p == "tag" else ""))
    return {"forms": rows, "draft": draft}


def ril_section(lines, ril_tags, phone, ril, masker, min_count) -> dict:
    reqs = collections.defaultdict(list)    # serial -> [[req_ts, resp_ts]]
    for ln in lines:
        r = ril.parse(ln.tag, ln.msg, ril_tags, phone)
        if r and r["serial"] is not None:
            ts = ln.dt.timestamp()
            if r["dir"] == "req":
                reqs[r["serial"]].append([ts, None])
            elif r["dir"] == "resp":
                for e in reversed(reqs[r["serial"]]):
                    if e[1] is None:
                        e[1] = ts
                        break
    total, hits = collections.Counter(), collections.defaultdict(list)
    for ln in lines:
        if ln.tag in ril_tags:
            continue
        total[ln.tag] += 1
        if not reqs:
            continue
        ts = ln.dt.timestamp()
        for m in re.finditer(r"\d+", ln.msg):
            best = None
            for rq, rs in reqs.get(int(m.group()), ()):
                d = min((abs(ts - rq), 0), (abs(ts - rs), 1) if rs else (1e9, 1))
                if d[0] <= WINDOW and (best is None or d < best[0]):
                    best = (d, ts - rq)
            if best:
                hits[ln.tag].append((best[1], best[0][1], ln.msg[:m.start()], ln.msg))
                break
    rows, draft = [], {}
    for tag, n in total.items():
        h = hits.get(tag, [])
        if n < min_count:
            continue
        ratio = len(h) / n
        verdict = "후보" if len(h) >= min_count and ratio >= 0.5 else (
            "대량·무관 — 설정하지 않음" if ratio < 0.2 and n >= 3 * min_count else "참고(일치 부족)")
        row = {"tag": tag, "lines": n, "matched": len(h), "ratio": round(ratio, 2), "verdict": verdict}
        if h:
            dts = [d * 1000 for d, _, _, _ in h]
            row["dt_ms"] = {"min": round(min(dts)), "median": round(statistics.median(dts)), "max": round(max(dts))}
            row["resp_side"] = round(sum(h_[1] for h_ in h) / len(h), 2)
        if verdict == "후보":
            name = "token" if row["resp_side"] > 0.5 else "serial"
            shapes = collections.Counter(prefix_shape(masker, x[2]) for x in h)
            top, cnt = shapes.most_common(1)[0]
            if cnt < min_count:
                row["verdict"] = "후보 — 모양 분산(초안 없음)"
            else:
                pat = "^" + prefix_regex(top) + f"(?P<{name}>\\d+)"
                ok = sum(bool(re.search(pat, x[3])) for x in h)     # 마스킹 전 원문에 다시 맞춘다(출력은 개수만)
                draft[tag] = pat
                row["draft_matched"], row["draft_coverage"] = ok, round(ok / len(h), 2)
        rows.append(row)
    rows.sort(key=lambda r: (-r["matched"], -r["lines"]))
    return {"tags": rows[:15], "draft_layers": draft, "ril_requests": sum(len(v) for v in reqs.values())}


def analyze(args) -> dict:
    root = Path(args.plugin_root) if args.plugin_root else s0_stats.REPO / "plugin"
    sys.path.insert(0, str(root / "scripts"))
    from common.masking import new_masker
    from platforms import load
    from platforms.android import logcat, ril
    profile = load(yaml.safe_load((root / "site-defaults.yaml").read_text(encoding="utf-8")))
    masker = new_masker()
    logs = [Path(p) for p in args.logs]
    results = [s0_stats.stats(p, s0_stats.parse(p, args), args) for p in logs]
    fmt, lines = collections.Counter(), []
    for i, p in enumerate(logs):
        fmt.update(format_counts(p, logcat))
        lines += logcat.read_file(p, i, args.tz, args.year)[0]
    all_tags = sum((r["all_tags"] for r in results), collections.Counter())
    coll = sum((r["tags"] for r in results), collections.Counter())
    mc = args.min_count
    tsec = tags_section(lines, all_tags, coll, args.rules, datetime.date.today().isoformat(), mc, profile.ril_tags)
    cand = [re.compile(c["rx"] or "^" + re.escape(c["tag"]) + "$") for c in tsec["candidates"]]
    ok = set(coll) | {t for t in all_tags if any(r.search(t) for r in cand)}
    tot = {k: sum(r[k] for r in results) for k in ("raw_lines", "format_lines", "parsed_lines", "ril_requests", "ril_paired", "slot_lines")}
    out = {"format": {k: fmt[k] for k in ("threadtime", "time", "year", "zone", "uid", "unparsed", "beginning")},
           "tags": tsec, "slots": slots_section(lines, ok, profile.phone, logcat, mc),
           "ril": ril_section(lines, profile.ril_tags, profile.phone, ril, masker, mc), "summary": tot, "shapes": {}}
    kind = "threadtime" if fmt["threadtime"] >= fmt["time"] else "time"
    out["format"]["verdict"] = f"{kind}(연도 {'있음' if fmt['year'] else '없음'}, zone {'있음' if fmt['zone'] else '없음'}, uid {'있음' if fmt['uid'] else '없음'})"
    if args.shapes:
        rx = re.compile(args.shapes)
        for ln in lines:
            if rx.search(ln.tag):
                out["shapes"].setdefault(ln.tag if not NUM.search(ln.tag) else re.sub(r"\d+", "#", ln.tag), collections.Counter())[shape(masker, ln.msg)] += 1
        out["shapes"] = {t: [[s, n] for s, n in c.most_common(5) if n >= mc] for t, c in out["shapes"].items()}
    return out


def show(o: dict) -> None:
    f = o["format"]
    print(f"[1 줄 형식] {f['verdict']}  threadtime {f['threadtime']} / time {f['time']} / 미해석 {f['unparsed']} / 구분선 {f['beginning']}")
    t = o["tags"]
    print("[2 미수집 telephony 태그 후보]")
    for c in t["candidates"]:
        print(f"  {c['tag']}  {c['lines']}줄  category={c['category']}  ({c['why']})")
    print(t["diff"] or "  (제안 없음)")
    print(f"  수집 규칙 중 0줄: {', '.join(t['zero_line_rules']) or '-'}")
    print("[3 슬롯 표기]")
    for r in o["slots"]["forms"]:
        print(f"  {r['position']} {r['shape']}: 현재 규칙 일치 {r['matched']} / 불일치 {r['unmatched']}")
    if o["slots"]["draft"]:
        print("  platform:\n    log:\n      phone_id:")
        for p, pats in o["slots"]["draft"].items():
            print(f"        {p}: [{', '.join(y(x) for x in pats)}]")
    print(f"[4 RIL 계열 태그 후보] RILJ 요청 {o['ril']['ril_requests']}건")
    for r in o["ril"]["tags"]:
        print(f"  {r['tag']}: 일치 {r['matched']}/{r['lines']} ({r['ratio']:.0%}) dt_ms={r.get('dt_ms')} 응답쪽 {r.get('resp_side')} -> {r['verdict']}"
              + (f"  초안 일치 {r['draft_matched']}/{r['matched']} ({r['draft_coverage']:.0%})" if "draft_matched" in r else ""))
    if o["ril"]["draft_layers"]:
        print("  platform:\n    ril:\n      vendor:        # L2 적용 후 유효\n        layers:")
        for tag, pat in o["ril"]["draft_layers"].items():
            print(f"          - {{tag: {tag}, patterns: [{y(pat)}]}}")
    s = o["summary"]
    print(f"[5 요약] 시각 파싱 {s0_stats.pct(s['format_lines'], s['raw_lines'])}, 수집 태그 {s0_stats.pct(s['parsed_lines'], s['format_lines'])}, "
          f"RIL 짝 {s0_stats.pct(s['ril_paired'], s['ril_requests'])}, phone_id {s0_stats.pct(s['slot_lines'], s['parsed_lines'])}")
    for tag, rows in o["shapes"].items():
        print(f"[--shapes] {tag}")
        for sh, n in rows:
            print(f"  {n:>5}  {sh}")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="s0_suggest.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+")
    ap.add_argument("--rules", required=True, help="<이슈 DB>/parser-rules")
    ap.add_argument("--tz", required=True)
    ap.add_argument("--year", type=int)
    ap.add_argument("--plugin-root")
    ap.add_argument("--min-count", type=int, default=3, help="이 미만인 모양·태그는 숨긴다(기본 3)")
    ap.add_argument("--shapes", help="이 정규식에 맞는 태그의 상위 메시지 모양(기본 끔). 마스킹되지 않은 설정값(APN 등)이 나올 수 있다 — 사내 SITE_PROFILE에만")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    out = analyze(args)
    print(json.dumps(out, ensure_ascii=False, indent=1) if args.json else "", end="\n" if args.json else "")
    if not args.json:
        show(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
