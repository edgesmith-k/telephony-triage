#!/usr/bin/env python3
"""module_measure.py — 모듈 필터 측정 (토큰 0, B2 §4.7, 결정 기록 11/05 "모듈별 줄 수와 모르는 데몬·태그").

    python3 tools/module_measure.py coverage (--logs <log>... --platform <p> --tz <IANA> [--year Y] --rules <db>/parser-rules
                                              | --job <JOB>) --modules <modules.yaml> [--db-config <issue-db.config.yaml>]
                                             [--plugin-root R] [--top 30] [--baseline prev.json] [--json]
    python3 tools/module_measure.py episodes --episodes <episodes.yaml> --runs <dir> [--json]

coverage — 사내 전용 점검. 숫자와 이름만 내고 메시지·줄 모양은 내지 않는다. 관리되는 모듈 레포 사본은 건드리지 않는다
(`--modules`는 파일 경로).
- 모듈별 줄 수(전체·hot, 규칙 1~3 표 `primary`와 분류 `mods`), `common (세지 않음)`, `분류 없음`, 매핑 없는 카테고리;
- 잡음 비율, 분류 안 된 hot common 줄 비율;
- 모르는 ident·태그(`tags.yaml`에 없음) 상위 N개(전체·W/E/F 수, 마스킹·40자) — `--logs`일 때 플랫폼 줄 읽기로;
- 이 로그에 한 번도 안 보인 이름(소유 데몬·ofonod 파일·RIL·IPC·서비스·HAL·D-Bus·클라이언트 태그);
- 설정 점검: 엄격 검사(`skillcheck`), 소유 데몬·태그와 `tags.yaml` 카테고리 대조, 정규식 태그가 다른 카테고리 정확 이름에
  맞는지, 모듈 없는 카테고리, `id_prefix`가 `key.upper()`와 다른지.
  종료 코드 0 = 지적 없음, 1 = 지적 있음, 2 = 사용 오류. `--json`은 키 정렬(비교용), `--baseline`은 이전 `--json`과의 차이.

episodes — LM rev 2 측정표(사외 전용, scratch 실행만): `episodes.yaml`(id·줄 번호·sha256만)과 기존 JOB 실행
(`<runs>/{o1-all,o2-all,a-all-aug}/job/events.json`)으로 explore @실패·@분, 중심 오차 곡선, deep 근거 창, 틀린 모듈,
held-out, 값 20% 제거(5 seed) 재현율을 낸다.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

from common import masking
from common import modulefilter as mf

NAME_KEYS = ("daemons", "ofonod_files", "ril", "ipc", "sit", "services", "hal", "dbus", "client_tags")
RUNS = {"O1": "o1-all", "O2": "o2-all", "A": "a-all-aug"}
OFFSETS = (-120, -60, -30, 0, 30, 60, 120)
USAGE = 2


class UsageError(Exception):
    pass


# -- coverage --------------------------------------------------------------------------------------------------------

def _root(args) -> Path:
    return Path(args.plugin_root) if args.plugin_root else REPO / "plugin"


def _parse(log: Path, args) -> dict:
    root = _root(args)
    cmd = [sys.executable, str(root / "scripts" / "parse_logcat.py"), "parse", str(log), "--full", "--rules", args.rules,
           "--tz", args.tz, "--mask", "--plugin-root", str(root)]
    if args.year:
        cmd += ["--year", str(args.year)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise UsageError(f"parse_logcat 실패({log.name}, 종료 코드 {proc.returncode})")
    return json.loads(proc.stdout)


def _raw_tags(logs: list[Path], args, rules) -> Counter:
    """플랫폼 줄 읽기로 (태그, 레벨) 수. 이름은 마스킹·40자. oFono 레벨은 파싱과 같은 백엔드 보정(`_line_record` —
    site-defaults 구성요소 `level_unreliable`, tags.yaml `level: unreliable`이 있으면 그것)."""
    backend = None
    if args.platform == "ofono":
        import platforms
        from common import site_defaults
        from platforms.ofono.backend import BACKEND
        from platforms.ofono.journal import read_file

        # `_parse`가 같은 루트로 이미 돌았으므로 site-defaults·platform 블록 오류는 거기서 사용 오류가 됐다
        profile = platforms.load(site_defaults.load(_root(args)), "ofono", require_enabled=False)
        backend = BACKEND.configure(profile).apply_rules(rules)
    else:
        from platforms.android.logcat import read_file
    masker = masking.new_masker(log_lines=True)
    out: Counter = Counter()
    for i, log in enumerate(logs):
        lines, _stats = read_file(log, i, args.tz, args.year)
        for ln in lines:
            out[(masker(ln.tag)[:40], backend._line_record(ln)["level"] if backend else ln.level)] += 1
    return out


def _rules(rules_dir: str | None):
    if not rules_dir:
        return None
    from common import parser_rules

    return parser_rules.load(Path(rules_dir))


def coverage(args) -> dict:
    doc = yaml.safe_load(Path(args.modules).read_text(encoding="utf-8"))
    spec = mf.compile_spec(doc, args.platform)
    if spec is None:
        raise UsageError(f"modules.yaml에 platforms.{args.platform}가 없다")
    logs = [Path(p) for p in args.logs or []]
    if args.job:
        events = json.loads((Path(args.job) / "events.json").read_text(encoding="utf-8"))
    else:
        if not (logs and args.rules and args.tz):
            raise UsageError("--logs·--rules·--tz 또는 --job이 필요하다")
        docs = [_parse(p, args) for p in logs]
        events = {"events": [e for d in docs for e in d.get("events") or []],
                  "uncollected_tags": [t for d in docs for t in d.get("uncollected_tags") or []]}
    rows = mf.rows_of(events)
    mf.label(spec, rows)
    by_primary, by_primary_hot, by_mods, by_mods_hot, unmapped = Counter(), Counter(), Counter(), Counter(), Counter()
    common_n = none_n = noise_n = hot_common = hot_common_unlabeled = 0
    for r in rows:
        if r["noise"]:
            noise_n += 1
            continue
        if r["primary"]:
            by_primary[r["primary"]] += 1
            by_primary_hot[r["primary"]] += r["hot"]
        elif r["why"] and r["why"].startswith("unmapped:"):
            unmapped[r["why"].split(":", 1)[1]] += 1
        for m in r["mods"] or ():
            by_mods[m] += 1
            by_mods_hot[m] += r["hot"]
        if not r["mods"]:
            if r.get("cat") == "common":
                common_n += 1
            else:
                none_n += 1
        if r["hot"] and mf._is_common(spec, r["tag"]):
            hot_common += 1
            hot_common_unlabeled += not r["mods"]
    findings: list[str] = []
    result = {
        "header": "사내 전용", "rows": len(rows),
        "modules": {m: {"primary": by_primary[m], "primary_hot": by_primary_hot[m], "mods": by_mods[m],
                        "mods_hot": by_mods_hot[m]} for m in spec.dirs},
        "common (세지 않음)": common_n, "분류 없음": none_n, "unmapped": dict(sorted(unmapped.items())),
        "noise_share": round(noise_n / len(rows), 4) if rows else 0.0,
        "hot_common_unlabeled_share": round(hot_common_unlabeled / hot_common, 4) if hot_common else 0.0,
    }
    rules = _rules(args.rules)
    unknown = []
    if logs and rules is not None:
        tags = _raw_tags(logs, args, rules)
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for (tag, level), n in tags.items():
            if rules.tag_category(tag) is None:
                agg[tag][0] += n
                agg[tag][1] += n if level in ("W", "E", "F") else 0
        unknown = [{"tag": t, "lines": v[0], "wef": v[1]}
                   for t, v in sorted(agg.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))[:args.top]]
    else:
        unknown = [{"tag": str(t.get("tag"))[:40], "lines": t.get("lines"), "wef": t.get("warn")}
                   for t in events.get("uncollected_tags") or []][:args.top]
    result["unknown_tags"] = unknown
    seen_tags = {r["tag"] for r in rows} | {mf._base(r["tag"]) for r in rows}
    msgs = [r["msg"] for r in rows]
    never: dict[str, dict[str, list[str]]] = {}
    for name, m in sorted((doc["platforms"][args.platform].get("modules") or {}).items()):
        for key in NAME_KEYS:
            vals = [str(v) for v in m.get(key) or () if "*" not in str(v)]
            miss = [v for v in vals if (v not in seen_tags if key in ("daemons", "client_tags") else
                                        not any(v in t for t in msgs))]
            if miss:
                never.setdefault(name, {})[key] = [masking.mask_brief(v, 40) for v in miss]
    result["never_seen"] = never
    result["config"] = config_checks(doc, args.platform, rules, args.db_config, findings)
    result["findings"] = findings
    return result


def config_checks(doc: dict, platform: str, rules, db_config: str | None, findings: list[str]) -> dict:
    out: dict = {}
    cats = None
    if db_config:
        cfg = yaml.safe_load(Path(db_config).read_text(encoding="utf-8")) or {}
        cats = cfg.get("categories") or {}
    try:
        from common import skillcheck
        errs = skillcheck.validate_modules(doc, set(cats) if cats else None, strict=True)
        out["validate"] = errs
        findings += [f"modules.yaml: {e}" for e in errs]
    except ImportError:
        out["validate"] = "건너뜀(skillcheck 없음)"
    mods = (doc["platforms"][platform].get("modules") or {})
    if rules is not None:
        for name, m in sorted(mods.items()):
            want = m.get("db_category")
            for owner in list(m.get("daemons") or ()):
                got = rules.tag_exact.get(owner)
                if got is not None and got != want and not (got == "common" and want == "common"):
                    findings.append(f"{name}: 데몬 {owner} tags.yaml 카테고리 {got} ≠ {want}")
            for rx in m.get("tags") or ():
                import re
                for tag, cat in rules.tag_exact.items():
                    if re.search(rx, tag) and cat != want:
                        findings.append(f"{name}: 태그 정규식이 다른 카테고리({cat}) 정확 이름 {tag}에 맞음")
    if cats:
        covered = {m.get("db_category") for m in mods.values()}
        for cat in sorted(cats):
            if cat != "common" and cat not in covered:
                findings.append(f"카테고리 {cat}에 모듈이 없다")
        for key, c in sorted(cats.items()):
            prefix = (c or {}).get("id_prefix") if isinstance(c, dict) else None
            if prefix and prefix != key.upper():
                out.setdefault("id_prefix_warnings", []).append(f"{key}: {prefix}")
    return out


def _diff(old: dict, new: dict, path: str = "") -> list[str]:
    out = []
    for k in sorted(set(old) | set(new)):
        a, b = old.get(k), new.get(k)
        p = f"{path}.{k}" if path else k
        if isinstance(a, dict) and isinstance(b, dict):
            out += _diff(a, b, p)
        elif a != b and isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out.append(f"{p}: {a} → {b} ({b - a:+})")
        elif a != b:
            out.append(f"{p}: 바뀜")
    return out


# -- episodes ---------------------------------------------------------------------------------------------------------

def _votes(spec, rows, center, before_s=None, after_s=None) -> list[tuple]:
    """한 모듈에 (태그, 모양) hot 줄당 한 표; 반복 묶음은 한 번; 상태·잡음은 표가 없다(LM proto `votes`)."""
    seen: dict = defaultdict(set)
    for r in rows:
        if r["noise"] or not r["mods"] or not r["hot"] or r["state"] is not None:
            continue
        if center and r["t"] and before_s is not None:
            d = (r["t"] - center).total_seconds()
            if d < -before_s or d > after_s:
                continue
        key = r["bg"] or (r["tag"], mf.tpl(r["msg"]))
        for m in r["mods"]:
            seen[m].add(key)
    return sorted(((m, len(k)) for m, k in seen.items()), key=lambda x: (-x[1], x[0]))


def _vote(spec, rows, center):
    for b, a in ((15, 15), (60, 30)):
        v = _votes(spec, rows, center, b, a)
        if v:
            return v
    return _votes(spec, rows, None)


def _got(picked) -> set:
    return set().union(*[v["row"].get("covers", v["row"]["lines"]) for v in picked]) if picked else set()


def _perturb(doc: dict, seed: int, frac: float = 0.2) -> dict:
    d = copy.deepcopy(doc)
    rnd = random.Random(seed)
    for p in d["platforms"].values():
        for m in (p.get("modules") or {}).values():
            for k in ("ril", "sit", "ipc", "dbus", "services", "hal"):
                if m.get(k):
                    m[k] = [x for x in m[k] if rnd.random() >= frac]
    return d


def episodes(args) -> dict:
    ep_doc = yaml.safe_load(Path(args.episodes).read_text(encoding="utf-8"))
    modules = yaml.safe_load(Path(args.modules).read_text(encoding="utf-8"))
    cache: dict = {}

    def load(log, doc=modules, key="base"):
        k = (log, key)
        if k not in cache:
            events = json.loads((Path(args.runs) / RUNS[log] / "job" / "events.json").read_text(encoding="utf-8"))
            spec = mf.compile_spec(doc, "android" if log == "A" else "ofono")
            rows = mf.rows_of(events)
            mf.label(spec, rows)
            cache[k] = (spec, rows)
        return cache[k]

    out = []
    for ep in ep_doc["episodes"]:
        spec, rows = load(ep["log"])
        ess = list(ep["essential"])
        line_t = {}
        for r in rows:
            for ln in r["lines"]:
                line_t.setdefault(ln, r["t"])
        c = line_t.get(ep["fail"])
        if c is None:
            out.append({"id": ep["id"], "error": "fail not collected"})
            continue
        mod = ep["module"]

        def rec(picked):
            got = _got(picked)
            return sum(1 for x in ess if x in got)  # noqa: B023 — 같은 반복 안에서만 부른다

        e = {"id": ep["id"], "log": ep["log"], "module": mod, "set": ep.get("set"), "ess": len(ess)}
        e["explore_fail"] = rec(mf.view(spec, rows, mod, c, "explore")[0])
        cm = c.replace(second=0, microsecond=0)
        e["minute_offset_s"] = round((cm - c).total_seconds(), 1)
        e["explore_minute"] = rec(mf.view(spec, rows, mod, cm, "explore")[0])
        e["curve"] = [rec(mf.view(spec, rows, mod, c + timedelta(seconds=o), "explore")[0]) for o in OFFSETS]
        ts = [line_t[x] for x in ess if line_t.get(x)]
        ev = [{"ts": mf._fmt(min(ts)), "tag": None, "msg": None, "event": None},
              {"ts": mf._fmt(c), "tag": None, "msg": None, "event": "fail"}]
        center, window = mf.deep_window(ev, rows)
        e["deep_window"] = rec(mf.view(spec, rows, mod, center, "deep", window=window, cap_rows=200, cap_bytes=24576)[0])
        v = _vote(spec, rows, cm)
        top = v[0][0] if v else None
        e["vote_rank"] = next((i + 1 for i, (m, _) in enumerate(v) if m == mod), None)
        e["wrong_module"] = rec(mf.view(spec, rows, top, cm, "explore")[0]) if top else 0
        e["perturb20"] = [rec(mf.view(*load(ep["log"], _perturb(modules, s), f"p{s}"), mod, c, "explore")[0])
                          for s in range(5)]
        out.append(e)
    totals = defaultdict(lambda: Counter())
    for e in out:
        if "error" in e:
            continue
        group = "held-out" if str(e.get("set", "")).startswith("held-out") else ("android" if e["log"] == "A" else "ofono")
        for k in ("ess", "explore_fail", "explore_minute", "deep_window", "wrong_module"):
            totals[group][k] += e[k]
    return {"episodes": out, "totals": {g: dict(c) for g, c in sorted(totals.items())}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="module_measure.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("coverage")
    c.add_argument("--logs", nargs="+")
    c.add_argument("--job")
    c.add_argument("--platform", default="ofono", choices=("ofono", "android"))
    c.add_argument("--tz")
    c.add_argument("--year", type=int)
    c.add_argument("--rules")
    c.add_argument("--modules", required=True)
    c.add_argument("--db-config")
    c.add_argument("--plugin-root")
    c.add_argument("--top", type=int, default=30)
    c.add_argument("--baseline")
    c.add_argument("--json", action="store_true")
    e = sub.add_parser("episodes")
    e.add_argument("--episodes", required=True)
    e.add_argument("--runs", required=True)
    e.add_argument("--modules", default=str(REPO / "templates" / "module-skills" / "modules.yaml"))
    e.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "episodes":
            result = episodes(args)
            print(json.dumps(result, ensure_ascii=False, indent=1 if args.json else None, sort_keys=True))
            return 0
        if args.job is None and not args.logs:
            raise UsageError("--logs 또는 --job이 필요하다")
        result = coverage(args)
    except (UsageError, OSError, KeyError, ValueError) as exc:
        print(f"사용 오류: {exc}", file=sys.stderr)
        return USAGE
    if args.baseline:
        try:
            old = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print("사용 오류: --baseline을 읽을 수 없다", file=sys.stderr)
            return USAGE
        result["baseline_diff"] = _diff(old, {k: v for k, v in result.items() if k != "baseline_diff"})
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("사내 전용 — 숫자와 이름만")
        for m, v in result["modules"].items():
            print(f"{m}: 표 {v['primary']}(hot {v['primary_hot']}), 분류 {v['mods']}(hot {v['mods_hot']})")
        print(f"common (세지 않음) {result['common (세지 않음)']}, 분류 없음 {result['분류 없음']}, "
              f"잡음 {result['noise_share']:.1%}, 분류 안 된 hot common {result['hot_common_unlabeled_share']:.1%}")
        for t in result["unknown_tags"]:
            print(f"모르는 태그 {t['tag']}: {t['lines']}줄 (W/E/F {t['wef']})")
        for name, keys in result["never_seen"].items():
            for key, vals in keys.items():
                print(f"안 보임 {name}.{key}: {' · '.join(vals)}")
        for f in result["findings"]:
            print(f"지적: {f}")
        for d in result.get("baseline_diff") or []:
            print(f"차이: {d}")
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
