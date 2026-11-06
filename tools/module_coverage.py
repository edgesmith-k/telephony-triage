#!/usr/bin/env python3
"""module_coverage.py — 사내 로그로 모듈 이름 빈틈 찾기 (토큰 0, F, 결정 기록 11/05 "사내 토큰 최소").

    python3 tools/module_coverage.py --modules <modules.yaml|모듈 레포 디렉토리> --rules <이슈 DB>/parser-rules
        --platform ofono|android --logs <파일|디렉토리>... [--db-config <이슈 DB>/issue-db.config.yaml]
        [--tz UTC] [--year Y] [--plugin-root plugin] [--min-lines 20] [--top 30] [--out <diff 파일>] [--json]
    python3 tools/site_step.py modules coverage [--json] [--out FILE] [--min-lines N]    # 사내 입력(steps.yaml)으로

사내 전용 출력이다(사내 데몬 이름이 나올 수 있다 — 사외 파일에 옮기지 않는다). 이름과 개수만 내고 로그 글은 내지 않는다.
- 로그는 한 번씩만 파싱한다(`module_measure._parse`, `parse_logcat --mask`). 모듈별 줄 수·모르는 태그·안 보인 이름·설정 지적은
  `module_measure.coverage`를 그대로 쓴다(다시 구현하지 않는다).
- 더 보는 것(`common.modulefilter` 함수 그대로): 분류 안 된 hot 줄 수(태그별), 로그에 있는데 어느 모듈의 daemons·tags에도 없고
  공통도 아닌 태그 — 이슈 DB `tags.yaml` 카테고리를 가진 모듈이 하나뿐이면 `known`(제안 후보), 공통·주인 모듈 둘 이상·없음이면
  `common`(목록만), `tags.yaml`에 없으면 `unknown`(이슈 DB에 먼저 — 계획 op PR·사용자 확인, 제안에 넣지 않는다).
- 제안: `known` 중 `--min-lines` 이상인 태그를 그 모듈 `daemons`에 더하는 modules.yaml diff. 글을 그 자리에서 고쳐 흐름 모양을
  지키고, 다시 읽은 문서가 더한 것만큼만 다르고 `skillcheck.validate_modules(strict=True)` 지적이 늘지 않을 때만 낸다(아니면 `manual`).
  지우는 제안은 하지 않는다(안 보인 이름은 목록만). 이 도구는 레포에 쓰지 않는다 — 사용자가 자기 clone에 diff를 적용해 모듈 레포
  PR(+1, `module_repo_check`)로 보낸다.
- `--tz` 기본 UTC: 개수는 시간대와 무관하다(시각을 비교하지 않는다).

종료 코드: 0 알릴 것 없음, 1 제안·`--min-lines` 이상 모르는 태그·안 보인 이름·`module_measure` 지적 있음, 2 사용 오류.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import yaml

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
if str(REPO / "plugin" / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import module_measure  # noqa: E402
from common import masking  # noqa: E402
from common import modulefilter as mf  # noqa: E402

HEADER = "사내 전용"
MIN_LINES = 20
TOP = 30
USAGE = 2
WEF = ("W", "E", "F")
# ofono_log_dir 사례 폴더의 줄 로그(site_checks.JOURNAL_RE와 같다). 그 밖(dbus.log·info.txt·json)은 넣지 않는다
JOURNAL_RE = re.compile(r"^(journal(-.+)?\.log|kernel\.log|syslog(\.\d+)?|messages(\.\d+)?)$")


class UsageError(Exception):
    pass


def expand_logs(paths: list[str | Path], platform: str | None = None) -> list[Path]:
    """파일은 그대로, 디렉토리는 안의 일반 파일(정렬, 심볼릭 링크·숨김 제외). oFono 디렉토리는 줄 로그 이름만."""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw).expanduser()
        if p.is_symlink():
            continue
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                rel = f.relative_to(p).parts
                if f.is_symlink() or not f.is_file() or any(x.startswith(".") for x in rel):
                    continue
                if any((p / Path(*rel[:i])).is_symlink() for i in range(1, len(rel))):
                    continue
                if platform == "ofono" and not JOURNAL_RE.match(f.name.removesuffix(".masked")):
                    continue
                out.append(f)
        else:
            raise UsageError(f"로그 경로 없음: {raw}")
    return out


def _modules_path(value: str | Path) -> Path:
    p = Path(value)
    return p / "modules.yaml" if p.is_dir() else p


def _ns(**kw) -> argparse.Namespace:
    base = dict(logs=None, job=None, platform="ofono", tz="UTC", year=None, rules=None, modules=None, db_config=None,
                plugin_root=None, top=TOP, baseline=None, json=True)
    base.update(kw)
    return argparse.Namespace(**base)


def _db_config(path: Path | None, job: Path) -> str | None:
    """이슈 DB 설정의 `categories`(목록 `[{key, id_prefix, …}]`)를 `module_measure.config_checks`가 읽는 매핑으로 옮긴 임시 파일."""
    if not path:
        return None
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    cats = cfg.get("categories") if isinstance(cfg, dict) else None
    if isinstance(cats, list):
        cats = {str(c["key"]): {k: v for k, v in c.items() if k != "key"} for c in cats if isinstance(c, dict) and c.get("key")}
    out = job / "db-config.yaml"
    out.write_text(yaml.safe_dump({"categories": cats if isinstance(cats, dict) else {}}, allow_unicode=True), encoding="utf-8")
    return str(out)


def _categories(spec) -> dict[str, list[str]]:
    by: dict[str, list[str]] = defaultdict(list)
    for name, m in spec.mods.items():
        if m.db_category:
            by[m.db_category].append(name)
    return by


def platform_report(modules: Path, platform: str, logs: list[Path], rules_dir: Path, db_config: Path | None = None,
                    tz: str = "UTC", year: int | None = None, plugin_root: Path | None = None, top: int = TOP,
                    min_lines: int = MIN_LINES) -> dict:
    """플랫폼 하나의 결과(이름·개수만). 로그는 한 번씩 파싱해 임시 JOB의 events.json으로 `module_measure.coverage`에 준다."""
    if not logs:
        raise UsageError("로그 파일이 없다")
    doc = yaml.safe_load(modules.read_text(encoding="utf-8")) or {}
    spec = mf.compile_spec(doc, platform)
    if spec is None:
        raise UsageError(f"modules.yaml에 platforms.{platform}가 없다")
    job = Path(tempfile.mkdtemp(prefix="tt-module-coverage-"))
    try:
        ns = _ns(platform=platform, tz=tz, year=year, rules=str(rules_dir), modules=str(modules),
                 db_config=_db_config(db_config, job), plugin_root=str(plugin_root) if plugin_root else None,
                 top=top)
        docs = [module_measure._parse(p, ns) for p in logs]
        events = {"events": [e for d in docs for e in d.get("events") or []],
                  "uncollected_tags": [t for d in docs for t in d.get("uncollected_tags") or []]}
        (job / "events.json").write_text(json.dumps(events, ensure_ascii=False), encoding="utf-8")
        ns.job, ns.logs = str(job), [str(p) for p in logs]
        base = module_measure.coverage(ns)
    finally:
        shutil.rmtree(job, ignore_errors=True)
    rules = module_measure._rules(str(rules_dir))
    rows = mf.rows_of(events)
    mf.label(spec, rows)
    hot_by: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    unowned: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["noise"]:
            continue
        tag = mf._base(r["tag"])
        if r["hot"] and not r["mods"]:
            hot_by[tag][0] += 1
            hot_by[tag][1] += (r.get("level") or "") in WEF
        if tag and not mf._owners(spec, r["tag"]) and not mf._is_common(spec, r["tag"]):
            unowned[tag][0] += 1
            unowned[tag][1] += bool(r["hot"])
    by_cat = _categories(spec)
    known, common = [], []
    for tag, (n, hot) in sorted(unowned.items(), key=lambda kv: (-kv[1][0], kv[0])):
        cat = rules.tag_category(tag) if rules is not None else None
        if cat is None:
            continue                                   # tags.yaml에 없으면 행이 되지 않는다(unknown은 module_measure 목록)
        owners = by_cat.get(cat, [])
        item = {"tag": masking.mask_brief(tag, 40), "rows": n, "hot": hot, "category": cat}
        if cat != "common" and len(owners) == 1:
            known.append({**item, "module": owners[0]})
        else:
            common.append({**item, "why": "common" if cat == "common" else (f"모듈 {len(owners)}개" if owners else "모듈 없음")})
    unlabelled = [{"tag": masking.mask_brief(t, 40), "rows": v[0], "wef": v[1]}
                  for t, v in sorted(hot_by.items(), key=lambda kv: (-kv[1][0], kv[0]))[:top]]
    return {"logs": len(logs), "rows": base["rows"], "modules": base["modules"],
            "common (세지 않음)": base["common (세지 않음)"], "분류 없음": base["분류 없음"],
            "unlabelled_hot": unlabelled,
            "unowned": {"known": known[:top], "common": common[:top], "unknown": base["unknown_tags"]},
            "never_seen": base["never_seen"], "findings": base["findings"],
            "_additions": [{"platform": platform, "module": k["module"], "name": k["tag"], "rows": k["rows"]}
                           for k in known if k["rows"] >= min_lines and mf.NAME_RX.fullmatch(k["tag"])]}


# -- modules.yaml 글 고치기 -------------------------------------------------------------------------------------------

def _scalar(name: str) -> str:
    try:
        plain = yaml.safe_load(name) == name and not re.search(r"[\s,\[\]{}#:]", name)
    except yaml.YAMLError:
        plain = False
    return name if plain else "'" + name.replace("'", "''") + "'"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block_end(lines: list[str], i: int) -> int:
    """`lines[i]` 아래로 들여쓰기가 더 깊은 줄(빈 줄·주석 포함)이 끝나는 위치."""
    ind = _indent(lines[i])
    j = i + 1
    while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#") or _indent(lines[j]) > ind):
        j += 1
    return j


def _child_indent(lines: list[str], lo: int, hi: int) -> int | None:
    for i in range(lo, hi):
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            return _indent(lines[i])
    return None


def _find_key(lines: list[str], lo: int, hi: int, key: str, indent: int | None = None) -> int | None:
    rx = re.compile(rf"^(\s*){re.escape(key)}:(\s|$)")
    for i in range(lo, hi):
        m = rx.match(lines[i])
        if m and (indent is None or len(m.group(1)) == indent):
            return i
    return None


def _insert_flow_list(text: str, names: list[str]) -> str | None:
    """`daemons: [a, b]`(한 줄) 끝에 이름을 더한다. 못 하면 None."""
    m = re.search(r"(\bdaemons:\s*\[)([^\]\n]*)(\])", text)
    if not m:
        return None
    body = m.group(2).rstrip()
    add = ", ".join(_scalar(n) for n in names)
    new = (body + ", " + add) if body.strip() else add
    return text[:m.start(2)] + new + text[m.end(2):]


def _edit_module(lines: list[str], platform: str, module: str, names: list[str]) -> bool:
    plat_root = _find_key(lines, 0, len(lines), "platforms", 0)
    if plat_root is None:
        return False
    hi = _block_end(lines, plat_root)
    p = _find_key(lines, plat_root + 1, hi, platform, _child_indent(lines, plat_root + 1, hi))
    if p is None:
        return False
    hi = _block_end(lines, p)
    mods = _find_key(lines, p + 1, hi, "modules", _child_indent(lines, p + 1, hi))
    if mods is None:
        return False
    hi = _block_end(lines, mods)
    m = _find_key(lines, mods + 1, hi, module, _child_indent(lines, mods + 1, hi))
    if m is None:
        return False
    line = lines[m]
    rest = line.split(":", 1)[1]
    if rest.strip().startswith("{"):                   # 흐름 모양 한 줄: {path: …, db_category: c, daemons: […], …}
        if not rest.rstrip().endswith("}") and "#" not in rest:
            return False
        new = _insert_flow_list(line, names)
        if new is None:
            add = "daemons: [" + ", ".join(_scalar(n) for n in names) + "]"
            mm = re.search(r"(\bdb_category:\s*[^,}\s]+)(\s*)([,}])", line)
            if not mm:
                return False
            new = line[:mm.end(1)] + ", " + add + line[mm.end(1):]
        lines[m] = new
        return True
    if rest.strip() and not rest.strip().startswith("#"):
        return False
    end = _block_end(lines, m)
    ci = _child_indent(lines, m + 1, end)
    d = _find_key(lines, m + 1, end, "daemons", ci)
    if d is not None:
        new = _insert_flow_list(lines[d], names)
        if new is None:                                # 블록 목록(- a) 모양은 사람이 고친다
            return False
        lines[d] = new
        return True
    c = _find_key(lines, m + 1, end, "db_category", ci)
    if c is None:
        return False
    lines.insert(c + 1, " " * _indent(lines[c]) + "daemons: [" + ", ".join(_scalar(n) for n in names) + "]")
    return True


def suggest_text(text: str, additions: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """(고친 글, 받아들인 추가, 사람이 고칠 추가). 모듈마다 고친 뒤 다시 읽어 더한 것만 달라졌는지·엄격 검사 지적이 늘지 않았는지 본다."""
    from common import skillcheck

    lines = text.split("\n")
    doc0 = yaml.safe_load(text) or {}
    base_errs = set(skillcheck.validate_modules(doc0, strict=True))
    accepted, manual = [], []
    expect = copy.deepcopy(doc0)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for a in additions:
        groups[(a["platform"], a["module"])].append(a)
    for (plat, mod), items in sorted(groups.items()):
        names = [a["name"] for a in items]
        trial = list(lines)
        ok = _edit_module(trial, plat, mod, names)
        if ok:
            want = copy.deepcopy(expect)
            block = want["platforms"][plat]["modules"][mod]
            block["daemons"] = list(block.get("daemons") or []) + names
            try:
                got = yaml.safe_load("\n".join(trial))
            except yaml.YAMLError:
                got = None
            ok = got == want and set(skillcheck.validate_modules(got, strict=True)) <= base_errs
        if ok:
            lines, expect = trial, want
            accepted += items
        else:
            manual += items
    return "\n".join(lines), accepted, manual


def unified(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/modules.yaml", "b/modules.yaml"))


def run(modules: str | Path, platforms: list[dict], db_config: Path | None = None, tz: str = "UTC", year: int | None = None,
        plugin_root: Path | None = None, top: int = TOP, min_lines: int = MIN_LINES) -> dict:
    """`platforms`: [{platform, logs:[Path], rules: Path, db_config?}] → 전체 결과(JSON 모양, 문서 머리 참고)."""
    path = _modules_path(modules)
    if not path.is_file():
        raise UsageError(f"modules.yaml 없음: {path}")
    text = path.read_text(encoding="utf-8")
    out: dict = {"header": HEADER, "platforms": {}, "skipped": {}}
    additions: list[dict] = []
    for p in platforms:
        rep = platform_report(path, p["platform"], p["logs"], Path(p["rules"]), p.get("db_config") or db_config, tz, year,
                              plugin_root, top, min_lines)
        additions += rep.pop("_additions")
        out["platforms"][p["platform"]] = rep
    new, accepted, manual = suggest_text(text, additions) if additions else (text, [], [])
    diff = unified(text, new) if accepted else None
    out["suggestion"] = {"additions": accepted, "diff": diff, "manual": manual}
    return out


SITE_INPUTS = (("android", "ops_db", "android_log_dir"), ("ofono", "ofono_db", "ofono_log_dir"))


def _empty(skipped: dict) -> dict:
    return {"header": HEADER, "platforms": {}, "skipped": skipped, "suggestion": {"additions": [], "diff": None, "manual": []}}


def run_site(ctx, min_lines: int = MIN_LINES, top: int = TOP) -> dict:
    """사내 입력으로: 로그 `steps.yaml` `android_log_dir`·`ofono_log_dir`, 규칙 `ctx.db_clone(ops_db|ofono_db)`(임시 clone),
    modules.yaml `ctx.module_clone()`(임시 clone). 입력이 없는 플랫폼은 건너뛰고 `skipped`에 빠진 입력을 적는다."""
    import site_checks as sc

    clone = ctx.module_clone()
    if clone is None:
        return _empty({"*": "module_skills.remote 없음"})
    have = set((sc.modules_doc(clone).get("platforms") or {}))
    plats, skipped = [], {}
    for plat, db_key, log_key in SITE_INPUTS:
        if plat not in have:
            continue
        raw = ctx.inputs.get(log_key)
        base = Path(str(raw)).expanduser() if raw else None
        if base is None or not base.is_dir():
            skipped[plat] = f"steps.yaml `{log_key}` " + ("없음" if not raw else "폴더 없음")
            continue
        logs = expand_logs([base], plat)
        if not logs:
            skipped[plat] = f"{log_key} 로그 파일 0"
            continue
        try:
            db = ctx.db_clone(db_key)
        except (sc.CloneUnavailable, RuntimeError) as exc:
            skipped[plat] = str(exc)[:160]
            continue
        if db is None:
            skipped[plat] = f"steps.yaml `{db_key}` 없음"
            continue
        cfg = db / "issue-db.config.yaml"
        plats.append({"platform": plat, "logs": logs, "rules": db / "parser-rules", "db_config": cfg if cfg.is_file() else None})
    if not plats:
        return _empty(skipped)
    try:
        result = run(clone, plats, plugin_root=ctx.root / "plugin", top=top, min_lines=min_lines)
    except (UsageError, module_measure.UsageError) as exc:
        return _empty({**skipped, "*": str(exc)[:160]})
    result["skipped"] = skipped
    return result


def exit_code(result: dict, min_lines: int = MIN_LINES) -> int:
    sug = result.get("suggestion") or {}
    if sug.get("additions") or sug.get("manual"):
        return 1
    for rep in (result.get("platforms") or {}).values():
        if rep.get("findings") or rep.get("never_seen"):
            return 1
        if any((t.get("lines") or 0) >= min_lines for t in rep["unowned"]["unknown"]):
            return 1
    return 0


def counts(result: dict, min_lines: int = MIN_LINES) -> dict:
    """근거 줄용 개수만(이름 없음, site_checks ms1.coverage)."""
    plats = result.get("platforms") or {}
    sug = result.get("suggestion") or {}
    return {"platforms": len(plats), "logs": sum(r["logs"] for r in plats.values()),
            "rows": sum(r["rows"] for r in plats.values()),
            "unlabelled_hot": sum(t["rows"] for r in plats.values() for t in r["unlabelled_hot"]),
            "known": sum(len(r["unowned"]["known"]) for r in plats.values()),
            "common": sum(len(r["unowned"]["common"]) for r in plats.values()),
            "unknown": sum(len(r["unowned"]["unknown"]) for r in plats.values()),
            "unknown_over_min": sum(1 for r in plats.values() for t in r["unowned"]["unknown"]
                                    if (t.get("lines") or 0) >= min_lines),
            "never_seen": sum(len(v) for r in plats.values() for k in r["never_seen"].values() for v in k.values()),
            "findings": sum(len(r["findings"]) for r in plats.values()),
            "additions": len(sug.get("additions") or []), "manual": len(sug.get("manual") or [])}


def render(result: dict) -> str:
    lines = [f"{HEADER} — 이름과 개수만(로그 글 없음). 사외 파일에 옮기지 않는다."]
    for plat, why in (result.get("skipped") or {}).items():
        lines.append(f"[{plat}] 건너뜀: {why}")
    for plat, r in result["platforms"].items():
        lines.append(f"\n[{plat}] 로그 {r['logs']}개 · 줄 {r['rows']}")
        for m, v in r["modules"].items():
            lines.append(f"  {m}: 표 {v['primary']}(hot {v['primary_hot']}), 분류 {v['mods']}(hot {v['mods_hot']})")
        lines.append(f"  common (세지 않음) {r['common (세지 않음)']}, 분류 없음 {r['분류 없음']}")
        for t in r["unlabelled_hot"]:
            lines.append(f"  분류 안 된 hot {t['tag']}: {t['rows']}줄 (W/E/F {t['wef']})")
        for t in r["unowned"]["known"]:
            lines.append(f"  모듈에 없음(제안 후보) {t['tag']}: {t['rows']}줄 → {t['module']} (카테고리 {t['category']})")
        for t in r["unowned"]["common"]:
            lines.append(f"  모듈에 없음(목록만) {t['tag']}: {t['rows']}줄 (카테고리 {t['category']}, {t['why']})")
        for t in r["unowned"]["unknown"]:
            lines.append(f"  tags.yaml에 없음 {t['tag']}: {t['lines']}줄 (W/E/F {t['wef']}) — 이슈 DB 계획 op PR이 먼저(사용자 확인)")
        for name, keys in r["never_seen"].items():
            for key, vals in keys.items():
                lines.append(f"  안 보임 {name}.{key}: {' · '.join(vals)} (지우지 않는다 — 목록만)")
        for f in r["findings"]:
            lines.append(f"  지적: {f}")
    sug = result["suggestion"]
    if sug["diff"]:
        lines += ["", f"modules.yaml 제안 {len(sug['additions'])}건 — 검토 뒤 자기 clone에 적용해 모듈 레포 PR로 보낸다:", sug["diff"].rstrip("\n")]
    for a in sug["manual"]:
        lines.append(f"손으로 고칠 것: {a['platform']}/{a['module']} daemons에 {a['name']} ({a['rows']}줄) — 글 모양을 자동으로 못 고침")
    if not sug["diff"] and not sug["manual"]:
        lines.append("\nmodules.yaml 제안 없음")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="module_coverage.py", description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modules", required=True)
    ap.add_argument("--platform", required=True, choices=("ofono", "android"))
    ap.add_argument("--logs", nargs="+", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--db-config")
    ap.add_argument("--tz", default="UTC")
    ap.add_argument("--year", type=int)
    ap.add_argument("--plugin-root")
    ap.add_argument("--min-lines", type=int, default=MIN_LINES)
    ap.add_argument("--top", type=int, default=TOP)
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        logs = expand_logs(args.logs, args.platform)
        result = run(args.modules, [{"platform": args.platform, "logs": logs, "rules": Path(args.rules)}],
                     Path(args.db_config) if args.db_config else None, args.tz, args.year,
                     Path(args.plugin_root) if args.plugin_root else None, args.top, args.min_lines)
    except (UsageError, module_measure.UsageError, OSError, ValueError, KeyError, yaml.YAMLError) as exc:
        print(f"사용 오류: {exc}", file=sys.stderr)
        return USAGE
    if args.out and result["suggestion"]["diff"]:
        Path(args.out).write_text(result["suggestion"]["diff"], encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True) if args.json else render(result))
    return exit_code(result, args.min_lines)


if __name__ == "__main__":
    sys.exit(main())
