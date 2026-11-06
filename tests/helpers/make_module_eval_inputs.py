#!/usr/bin/env python3
"""모듈 eval case의 마스킹된 입력 파일을 결정적으로 만든다 (MODULE_SKILLS_PLAN_IMPL §5.5, C0 설계 §5).

`templates/module-skills/<p>/<m>/evals/<case>/files/source.log`(합성 로그 또는 마스킹 발췌)와 `case.yaml`에서
플랫폼 DB(oFono: 변형 `issue-db-ofono-modules`, Android: 샘플 `issue-db-sample`)로 `triage.py run --offline-db`·`explore`를
돌려 아래를 만든다.

| kind | 만드는 파일 |
|---|---|
| deep | `events.json`(경로 정규화), `timeline.md`, `deep-input.json`(schema_version 1) |
| explore | `timeline.md`, `explore-input.json`(run이 쓴 그대로), `analysis.json`(`generated_at`·`request_hash`·`files`·`analyzer`/`explore`의 `note` 뺌) |

`templates/module-skills/modules.yaml`에 그 플랫폼의 `common.filter`가 있으면 case `timeline.md`는 모듈 보기다
(B2 §4.6: `common.modulefilter.build`를 같은 프로세스에서, `triage.py module`과 같은 인자로 — deep은 `match.json`
1위 근거 창·고정 줄, 200줄/24KB; explore는 `anchor.fail`(없으면 발생 시각) 중심·고정 줄, 150줄/20KB). 필터가 없으면
오늘 그대로 `explore` 타임라인이다. case 디렉토리는 `skillcheck.CASE_CAP` 이하여야 한다(R34).

검사(H C1+D): deep 1위 category = modules.yaml의 그 모듈 `db_category`. 모뎀(`db_category: common`)은 1위 category가
common·없음이 아니고, 증상 모듈 = 그 category의 모듈, `deep-input.module` = `<p>/<증상>`, 보기는 `with_modem`, `op: also`
신호 ≥ 1(`triage.py module --also`와 같다, R8). 모든 case에서 `expect.evidence` regex는 생성한 `timeline.md`에 있어야 한다.

네트워크·claude를 쓰지 않는다. `files/`의 생성 파일은 손으로 고치지 않고 `--write`로만 다시 만든다.
pytest(`test_module_templates.py::test_generator_no_drift`)가 `--check`로 drift를 본다.

CLI:
    python3 tests/helpers/make_module_eval_inputs.py --write [--case NAME ...] [--templates DIR]
    python3 tests/helpers/make_module_eval_inputs.py --check [--case NAME ...] [--templates DIR] [--json]
    python3 tests/helpers/make_module_eval_inputs.py --report [--db-variant android=issue-db-android-plain] [--case ...]
    python3 tests/helpers/make_module_eval_inputs.py --write --templates <레포 밖> [--no-view] [--db-variant P=V] [--report]

`--report`(읽기 전용): case마다 "evidence rows in view n/m"(근거 regex m개 중 타임라인에 있는 n개)을 기본 DB와,
`--db-variant`가 있으면 그 DB로도 낸다($0 대조 표). `--no-view`(모듈 보기 대신 오늘 `explore` 타임라인)와 기본이 아닌
`--db-variant`로 쓰기는 레포 밖 `--templates`에서만 한다(아니면 종료 2, R16).

종료 코드: 0 = 완료·drift 없음, 1 = drift 또는 기대값 불일치, 2 = 사용·환경 오류.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO / "plugin" / "scripts", REPO / "tests" / "mocks", REPO / "tests" / "helpers"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import yamlio

TEMPLATES = REPO / "templates" / "module-skills"
VARIANT = "issue-db-ofono-modules"
SAMPLE_DB = REPO / "tests" / "fixtures" / "issue-db-sample"
DB_VARIANTS = {"ofono": VARIANT, "android": None}      # None = 샘플 그대로(make_filter_fixtures와 같다, H C1+D S7)
COMPONENTS = {"data": "Data", "sim": "SIM", "network": "Network", "call": "Call", "sms": "SMS", "ims": "IMS",
              "modem": "Modem"}                         # 모의 Jira components(S6). data는 C0 바이트 그대로


def evidence_rxs(data) -> list[str]:
    """근거 regex 목록 — `module_eval.evidence_rxs`(정본: deep은 expect.evidence, explore schema 2는 accept 합집합).
    실행기가 없는 체크아웃이면 같은 규칙으로 직접 모은다."""
    try:
        from module_eval import evidence_rxs as rxs
    except ImportError:
        exp = (data or {}).get("expect") or {}
        out = ([e for a in exp.get("accept") or [] for e in (a.get("evidence") or [])]
               if "accept" in exp else list(exp.get("evidence") or []))
        return list(dict.fromkeys(out))
    return rxs(data)
PLATFORM = {"name": "android", "enabled": ["android", "ofono"]}   # test_platform_analyzers.py ON과 같다
GENERATED = {
    "deep": ("events.json", "timeline.md", "deep-input.json"),
    "explore": ("timeline.md", "explore-input.json", "analysis.json"),
}
ANALYSIS_DROP = ("generated_at", "request_hash", "files")   # 비결정·절대 경로(report.py)
EXPLORE_LIMIT = 200
MODULES_YAML = TEMPLATES / "modules.yaml"
VIEW_CAPS = {"deep": (200, 24576), "explore": (150, 20480)}       # = modulecmd(B2 §5.4 D3, §4.3 Caps)
OK, CHECK_FAILED, USAGE = 0, 1, 2


class GenError(Exception):
    """기대값 불일치(종료 1)."""


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def _load_case(case_dir: Path, validate: bool) -> dict:
    """case.yaml 원본 dict. `validate`면 `module_eval.load_case`(단일 구현)로 검사한다.

    `--write`가 처음 만들 때는 아직 `files/`의 생성 파일이 없어 load_case 규칙 6·7을 통과할 수 없으므로,
    쓰기 뒤에 검사한다(`main`).
    """
    if validate:
        _validate(case_dir)
    data = yamlio.load(case_dir / "case.yaml")
    if not isinstance(data, dict) or data.get("kind") not in GENERATED:
        raise GenError(f"{case_dir.name}: case.yaml kind가 deep|explore가 아니다")
    return data


TOP_KEYS = {"schema_version", "name", "kind", "synthetic", "key", "issue", "parse", "input", "run_expect", "expect"}
TOP_OPTIONAL = {"origin"}
INPUT_KEYS = {"deep": {"deep_input", "events", "timeline", "log"}, "explore": {"explore_input", "timeline", "analysis"}}


def _validate(case_dir: Path) -> None:
    """`module_eval.load_case`(정본). 실행기가 없는 체크아웃이면 같은 규칙의 일부(`_basic_check`)만 본다."""
    try:
        import module_eval
    except ImportError:
        module_eval = None
    try:
        if module_eval is not None and hasattr(module_eval, "load_case"):
            module_eval.load_case(case_dir)
        else:
            print(f"경고: module_eval.load_case 없음 — {case_dir.name}은 기본 검사만 한다", file=sys.stderr)
            _basic_check(case_dir)
    except GenError:
        raise
    except Exception as exc:  # CaseError
        raise GenError(f"{case_dir.name}: case 검사 실패: {exc}") from exc


def _basic_check(case_dir: Path) -> None:
    """load_case 규칙(C0 설계 §2.2) 중 키·출처 표시(합성/마스킹 발췌)·입력 파일 집합·근거 regex만."""
    from common import skillcheck

    data = yamlio.load(case_dir / "case.yaml")
    name = case_dir.name
    if not isinstance(data, dict) or not TOP_KEYS <= set(data) <= TOP_KEYS | TOP_OPTIONAL:
        raise GenError(f"{name}: 최상위 키가 {sorted(TOP_KEYS)}(+ origin)가 아니다")
    if data["name"] != name or data["schema_version"] != (2 if data.get("kind") == "explore" else 1):
        raise GenError(f"{name}: name·schema_version")
    kind = data["kind"]
    if set(data["input"]) != INPUT_KEYS[kind]:
        raise GenError(f"{name}: input 키")
    files = case_dir / "files"
    present = {p.name for p in files.iterdir()}
    if present != {"source.log", *GENERATED[kind]}:
        raise GenError(f"{name}: files/ 집합 {sorted(present)}")
    log = (files / "source.log").read_text(encoding="utf-8")
    for why in skillcheck.origin_problems(data, log):
        raise GenError(f"{name}: origin {why}")
    staged = "\n".join((case_dir / v).read_text(encoding="utf-8") for v in data["input"].values())
    for rx in evidence_rxs(data):
        if not (re.search(rx, staged) and re.search(rx, log)):
            raise GenError(f"{name}: 근거 regex {rx!r}가 files/에 없다")


def case_dirs(templates: Path, names: list[str] | None) -> list[Path]:
    found = sorted(p.parent for p in templates.glob("*/*/evals/*/case.yaml"))
    if names:
        unknown = sorted(set(names) - {p.name for p in found})
        if unknown:
            raise ValueError(f"알 수 없는 case: {', '.join(unknown)}")
        found = [p for p in found if p.name in names]
    return found


def _issue_yaml(case: dict, module: str = "data") -> str:
    """모의 Jira 이슈 YAML(`tests/mocks/jira/MOCK-1001.yaml` 모양). `--issue-file` → `jira_fields extract`(마스킹).
    components는 모듈 이름에서(S6)."""
    issue = case["issue"]
    doc = {
        "key": case["key"],
        "fields": {
            "summary": issue["summary"],
            "description": issue["description"],
            "status": {"name": "Open"},
            "project": {"key": "MOCK", "name": "Mock Telephony"},
            "components": [{"name": COMPONENTS.get(module, module.capitalize())}],
            "customfield_10001": issue["occurred_at"],
            "customfield_10004": issue["platform_version"],
            "customfield_10006": issue["sim_slot"],
        },
        "comments": [],
    }
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"     # JSON은 YAML의 부분집합


def _run(runner, root: Path, args: list, home: Path, what: str):
    proc = runner.run("triage.py", args, root=root, env={"TELEPHONY_TRIAGE_HOME": home})
    if proc.returncode != 0:
        raise GenError(f"{what}: triage.py {args[0]} 종료 코드 {proc.returncode}\n{proc.stderr.strip()[-800:]}")
    return proc


def build_case(case_dir: Path, case: dict, db: Path, root: Path, tmp: Path, runner, doc: dict | None = None,
               view: bool = True, strict: bool = True, notes: list | None = None) -> dict[str, str]:
    """case 하나의 생성 파일 {이름: 내용}. `doc` = 템플릿 modules.yaml. `strict=False`(--report)면 기대값 불일치를
    `notes`에 적고 계속한다(근거 n/m은 호출자가 센다)."""
    name, kind = case_dir.name, case["kind"]
    module = case_dir.parent.parent.name                     # <p>/<m>/evals/<case>
    platform = case_dir.parent.parent.parent.name

    def mismatch(msg: str) -> None:
        if strict:
            raise GenError(msg)
        if notes is not None:
            notes.append(msg)

    work = tmp / name
    (work / "logs").mkdir(parents=True)
    shutil.copyfile(case_dir / "files" / "source.log", work / "logs" / "source.log")
    (work / "issue.yaml").write_text(_issue_yaml(case, module), encoding="utf-8", newline="\n")
    job, home = work / "job", work / "home"
    parse = case.get("parse") or {}
    args = ["run", case["key"], "--offline-db", db, "--logs", work / "logs" / "source.log",
            "--issue-file", work / "issue.yaml", "--out", job, "--platform", platform,
            "--tz", parse["tz"], "--year", parse["year"], "--minutes", parse.get("minutes", 5)]
    _run(runner, root, args, home, name)
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    events = json.loads((job / "events.json").read_text(encoding="utf-8"))
    logs = analysis.get("logs") or {}
    if not (logs.get("events") or 0) > 0:
        raise GenError(f"{name}: 이벤트 0건(analysis.logs.events)")
    if logs.get("in_range") in (False, "outside"):
        raise GenError(f"{name}: 로그가 발생 시각 범위 밖(analysis.logs.in_range={logs.get('in_range')})")
    if events.get("masked") is not True:
        raise GenError(f"{name}: events.json masked가 true가 아니다")
    expect = case["run_expect"]
    explore_input = job / "explore-input.json"
    candidates = analysis.get("candidates") or []
    view_module, with_modem = module, False
    if kind == "deep":
        top = candidates[0] if candidates else {}
        want = db_category(doc, platform, module) or module
        cat = top.get("category")
        if want == "common":                              # 모뎀: 증상 모듈 + also(R8)
            symptom = symptom_for(doc, platform, cat) if cat not in (None, "common") else None
            ok_cat = symptom is not None
            if symptom:
                view_module, with_modem = symptom, True
        else:
            ok_cat = cat == want
        if top.get("cause") != expect["top_cause"] or top.get("C") != expect["C"] or not ok_cat:
            mismatch(f"{name}: 1위 {top.get('cause')} C={top.get('C')} category={cat} "
                     f"— 기대 {expect['top_cause']} C={expect['C']} category={want}")
        if explore_input.exists():
            raise GenError(f"{name}: deep case인데 explore-input.json이 생겼다")
        explore_bytes = None
        # CLI만으로는 deep에 타임라인이 없다 → 같은 report.timeline 경로를 임시 입력으로 탄다
        explore_input.write_text(json.dumps({"around": (analysis.get("issue") or {}).get("occurred_at"),
                                             "failed_step": None, "limit": EXPLORE_LIMIT, "anchor": None},
                                            ensure_ascii=False), encoding="utf-8")
    else:
        reason = (analysis.get("explore") or {}).get("reason")
        if reason != expect["explore_reason"]:
            mismatch(f"{name}: explore.reason {reason} — 기대 {expect['explore_reason']}")
        if not explore_input.is_file():
            raise GenError(f"{name}: explore-input.json이 없다")
        explore_bytes = explore_input.read_bytes().decode("utf-8")
    _run(runner, root, ["explore", case["key"], "--out", job, "--platform", platform], home, name)
    timeline = (job / "timeline.md").read_bytes().decode("utf-8")
    if view:
        text = module_view(job, case, kind, platform, view_module, analysis, events, explore_bytes, doc, with_modem)
        if text is not None:
            timeline = text
    if with_modem:
        signal = modem_signal(job, doc, platform, view_module, analysis)
        if signal < 1:
            mismatch(f"{name}: 모뎀 신호 없음(op also rows 0)")
    missing = [rx for rx in evidence_rxs(case) if not re.search(rx, timeline)]
    if missing:
        mismatch(f"{name}: expect.evidence가 timeline.md에 없다: {', '.join(map(repr, missing))}")
    out: dict[str, str] = {"timeline.md": timeline}
    if kind == "deep":
        explore_input.unlink()
        events.setdefault("rules", {})["path"] = "parser-rules"
        events.setdefault("input", {})["files"] = ["source.log"]
        out["events.json"] = json.dumps(events, ensure_ascii=False) + "\n"
        issue = analysis.get("issue") or {}
        out["deep-input.json"] = _dump({
            "schema_version": 1,
            "key": analysis.get("key"),
            "platform": analysis.get("platform"),
            "module": f"{platform}/{view_module}",
            "sha": "template",
            "type_id": candidates[0].get("type"),
            "top_candidates": [{k: c.get(k) for k in ("type", "cause", "score", "confidence")}
                               for c in candidates[:3]],
            "issue_summary": issue.get("summary"),
            "occurred_at": issue.get("occurred_at"),
            "events": "events.json",
            "timeline": "timeline.md",
            "log_paths": ["source.log"],
        })
    else:
        out["explore-input.json"] = explore_bytes
        for key in ANALYSIS_DROP:
            analysis.pop(key, None)
        for key in ("analyzer", "explore"):     # 5-1·5-2 답 전 안내(driver.ASK_NOTE): 동의 뒤 입력이라 뺀다 — 원문 열람 낱말이
            if isinstance(analysis.get(key), dict):     # skillcheck raw-read에 걸린다
                analysis[key].pop("note", None)
        out["analysis.json"] = _dump(analysis)
    for fname, text in out.items():          # 결정성: 임시 경로가 남으면 안 된다
        for marker in (str(tmp), str(REPO)):
            if marker in text:
                raise GenError(f"{name}/{fname}: 절대 경로가 남았다({marker[:40]}…)")
    assert set(out) == set(GENERATED[kind])
    return out


def _modules_doc(templates: Path | None = None) -> dict | None:
    """템플릿 `modules.yaml`(엄격 검사 통과). 검사기는 함수 안에서 부른다(skillcheck, B2 §4.6)."""
    path = (templates / "modules.yaml") if templates is not None else MODULES_YAML
    if not path.is_file():
        return None
    from common import skillcheck

    doc = skillcheck.load_modules_yaml(path.read_bytes())
    errors = skillcheck.validate_modules(doc, strict=True)
    if errors:
        raise GenError("templates/module-skills/modules.yaml: " + "; ".join(errors[:3]))
    return doc


def _modules(doc: dict | None, platform: str) -> dict:
    try:
        mods = doc["platforms"][platform]["modules"]
    except (TypeError, KeyError):
        return {}
    return mods if isinstance(mods, dict) else {}


def db_category(doc: dict | None, platform: str, module: str) -> str | None:
    block = _modules(doc, platform).get(module)
    cat = block.get("db_category") if isinstance(block, dict) else None
    return cat if isinstance(cat, str) else None


def symptom_for(doc: dict | None, platform: str, category: str | None) -> str | None:
    """`db_category == category`인 모듈 이름(runtime `materialise(category=…)`와 같은 뜻)."""
    names = [m for m, b in _modules(doc, platform).items() if isinstance(b, dict) and b.get("db_category") == category]
    return names[0] if len(names) == 1 else None


def _deep_ev(job: Path, analysis: dict) -> tuple[list, str]:
    from common import modulefilter

    top = (analysis.get("candidates") or [{}])[0]
    match_path = job / "match.json"
    ev = []
    if match_path.is_file():
        ev = modulefilter.deep_evidence(json.loads(match_path.read_text(encoding="utf-8")), top)
    if ev:
        return ev, "근거"
    return [{k: e.get(k) for k in ("ts", "tag", "msg", "event")} for e in top.get("evidence") or []], "근거 (analysis.json)"


def modem_signal(job: Path, doc: dict | None, platform: str, symptom: str, analysis: dict) -> int:
    """`op: also` 모뎀 신호 줄 수(`modulecmd._deep_module`과 같은 인자)."""
    from common import modulefilter

    ev, _ = _deep_ev(job, analysis)
    res = modulefilter.build({"op": "also", "events": str(job / "events.json"), "evidence": ev, "module": symptom,
                              "modules": doc, "platform": platform})
    if res.get("error"):
        return 0
    try:
        return int(res.get("rows") or 0)
    except (TypeError, ValueError):
        return 0


def module_view(job: Path, case: dict, kind: str, platform: str, module: str, analysis: dict, events: dict,
                explore_bytes: str | None, doc: dict | None = None, with_modem: bool = False) -> str | None:
    """필터가 있으면 모듈 보기 글, 없으면 None(오늘 타임라인 그대로)."""
    if doc is None:
        return None
    from common import modulefilter

    spec = modulefilter.compile_spec(doc, platform)
    if spec is None or not spec.has_filter:
        return None
    cap_rows, cap_bytes = VIEW_CAPS[kind]
    payload = {"op": "view", "modules": doc, "platform": platform, "events": str(job / "events.json"),
               "key": case["key"], "module": module, "mode": kind, "allow": events.get("mask_allow") or [],
               "cap_rows": cap_rows, "cap_bytes": cap_bytes, "with_modem": with_modem}
    if kind == "deep":
        ev, source = _deep_ev(job, analysis)
        payload.update(center=None, center_source=source, evidence=ev, pins=ev)
    else:
        explore_input = json.loads(explore_bytes or "{}")
        fail = (explore_input.get("anchor") or {}).get("fail")
        rows = modulefilter.rows_of(events)
        pins = [{"ts": r["ts"], "tag": r["tag"], "msg": r["msg"]} for r in rows if fail and r["ts"] == fail]
        payload.update(center=fail or explore_input.get("around"), center_source="실패 스텝" if fail else "발생 시각",
                       evidence=[], pins=pins[:modulefilter.PINS_EXPLORE])
    result = modulefilter.build(payload)
    if "text" not in result:
        raise GenError(f"{case['key']}: 모듈 보기 실패 {result}")
    return result["text"]


def _case_size(case_dir: Path) -> None:
    """case 디렉토리 전체 바이트 ≤ skillcheck.CASE_CAP (R34)."""
    from common import skillcheck

    total = sum(p.stat().st_size for p in case_dir.rglob("*") if p.is_file())
    if total > skillcheck.CASE_CAP:
        raise GenError(f"{case_dir.name}: case 크기 {total}B > CASE_CAP {skillcheck.CASE_CAP}B")


def _platform(case_dir: Path) -> str:
    return case_dir.parent.parent.parent.name


def generate(dirs: list[Path], validate: bool, templates: Path = TEMPLATES, variants: dict | None = None,
             view: bool = True, strict: bool = True, notes: dict | None = None) -> dict[str, dict[str, str]]:
    """{case: {파일: 내용}}. DB는 플랫폼마다 한 번 만든다(`variants` = {플랫폼: 변형 이름 | None(샘플)})."""
    import make_variant_dbs
    import runner

    names = {**DB_VARIANTS, **(variants or {})}
    tmp = Path(tempfile.mkdtemp(prefix="tt-module-inputs-"))
    try:
        dbs: dict[str, Path] = {}
        for p in sorted({_platform(d) for d in dirs}):
            if p not in names:
                raise GenError(f"{p}: 입력 생성 DB가 정해지지 않은 플랫폼")
            dbs[p] = make_variant_dbs.build(names[p], tmp / f"db-{p}") if names[p] else SAMPLE_DB
        doc = _modules_doc(templates)
        root = runner.plugin_root("ofono-on", platform=PLATFORM)
        out = {}
        for d in dirs:
            mine = [] if notes is not None else None
            try:
                out[d.name] = build_case(d, _load_case(d, validate), dbs[_platform(d)], root, tmp, runner, doc,
                                         view=view, strict=strict, notes=mine)
            except GenError as exc:
                if strict:
                    raise
                mine.append(str(exc))
            if notes is not None:
                notes[d.name] = mine
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for path in list(runner._ROOTS.values()):           # plugin_root 임시 루트(pytest 훅 밖에서는 안 지워진다)
            shutil.rmtree(path, ignore_errors=True)
        runner._ROOTS.clear()


def write(case_dir: Path, outputs: dict[str, str]) -> None:
    files = case_dir / "files"
    for path in sorted(files.iterdir()):
        if path.name != "source.log" and path.name not in outputs and path.is_file():
            path.unlink()
    for fname, text in outputs.items():
        (files / fname).write_bytes(text.encode("utf-8"))


def compare(case_dir: Path, outputs: dict[str, str]) -> list[tuple[str, str]]:
    rows = []
    files = case_dir / "files"
    extra = sorted(p.name for p in files.iterdir() if p.name != "source.log" and p.name not in outputs)
    for fname in sorted(outputs):
        path = files / fname
        if not path.is_file():
            rows.append((fname, "없음"))
        else:
            rows.append((fname, "일치" if path.read_bytes() == outputs[fname].encode("utf-8") else "다름"))
    rows += [(fname, "남는 파일") for fname in extra]
    return rows


def _parse_variants(items: list[str]) -> dict:
    """`P=VARIANT` 목록 → {플랫폼: 변형 이름}. 모르는 플랫폼·변형은 ValueError."""
    import make_variant_dbs

    out = {}
    for item in items:
        p, sep, name = item.partition("=")
        if not sep or p not in DB_VARIANTS or name not in make_variant_dbs.VARIANTS:
            raise ValueError(f"--db-variant {item!r}: <플랫폼>=<변형>(플랫폼 {sorted(DB_VARIANTS)}, make_variant_dbs.VARIANTS)")
        if name != DB_VARIANTS[p]:
            out[p] = name
    return out


def _inside_repo(path: Path) -> bool:
    real, repo = path.resolve(), REPO.resolve()
    return real == repo or repo in real.parents


def evidence_counts(case_dir: Path, timeline: str | None) -> tuple[int | None, int]:
    """(타임라인에 있는 근거 regex 수, 근거 regex 수). 타임라인이 없으면 (None, m)."""
    data = yamlio.load(case_dir / "case.yaml")
    rxs = evidence_rxs(data)
    if timeline is None:
        return None, len(rxs)
    return sum(1 for rx in rxs if re.search(rx, timeline)), len(rxs)


def report(dirs: list[Path], templates: Path, variants: dict, as_json: bool) -> dict:
    """case마다 "evidence rows in view n/m"을 기본 DB와(있으면) 변형 DB로. 기대값 불일치는 끝내지 않고 메모로 낸다."""
    runs = {"default": {}}
    if variants:
        runs["+".join(f"{p}={v}" for p, v in sorted(variants.items()))] = variants
    table: dict[str, dict] = {}
    for label, var in runs.items():
        notes: dict = {}
        outputs = generate(dirs, validate=False, templates=templates, variants=var, strict=False, notes=notes)
        for d in dirs:
            n, m = evidence_counts(d, (outputs.get(d.name) or {}).get("timeline.md"))
            table.setdefault(d.name, {})[label] = {"n": n, "m": m, "notes": notes.get(d.name) or []}
    if as_json:
        print(json.dumps(table, ensure_ascii=False, indent=1))
    else:
        for name, cols in table.items():
            cells = [f"{label} {'?' if c['n'] is None else c['n']}/{c['m']}" for label, c in cols.items()]
            print(f"{name}: evidence rows in view " + " · ".join(cells))
            for label, c in cols.items():
                for note in c["notes"]:
                    print(f"  {label}: {note}")
    return table


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_module_eval_inputs.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="files/의 생성 파일을 다시 쓴다")
    mode.add_argument("--check", action="store_true", help="다시 만들어 커밋된 파일과 바이트 비교")
    parser.add_argument("--report", action="store_true", help="근거 줄 n/m 표(읽기 전용, --write와 함께 쓸 수 있다)")
    parser.add_argument("--case", action="append", metavar="NAME", help="case 이름(여러 번)")
    parser.add_argument("--templates", type=Path, default=TEMPLATES, help="템플릿 루트(기본 templates/module-skills)")
    parser.add_argument("--no-view", action="store_true", help="모듈 보기 대신 explore 타임라인(레포 밖 --templates 쓰기만)")
    parser.add_argument("--db-variant", action="append", default=[], metavar="P=VARIANT",
                        help="플랫폼 DB를 변형으로(예: android=issue-db-android-plain). 쓰기는 레포 밖 --templates만")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not (args.write or args.check or args.report):
        parser.error("--write·--check·--report 중 하나가 필요하다")
    templates = args.templates.resolve()
    try:
        variants = _parse_variants(args.db_variant)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return USAGE
    if (args.no_view or variants) and args.check:
        print("--check는 기본 DB·모듈 보기로만 한다(커밋된 파일과 비교)", file=sys.stderr)
        return USAGE
    if (args.no_view or variants) and args.write and _inside_repo(templates):
        print("--no-view·--db-variant로 쓰기는 레포 밖 --templates에서만 한다(R16)", file=sys.stderr)
        return USAGE
    try:
        dirs = case_dirs(templates, args.case)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return USAGE
    if not dirs:
        print(f"case가 없다: {templates}/*/*/evals/*/case.yaml", file=sys.stderr)
        return USAGE
    if args.report:
        try:
            report(dirs, templates, variants, args.json)
        except GenError as exc:
            print(f"실패: {exc}", file=sys.stderr)
            return CHECK_FAILED
        if not args.write:
            return OK
    try:
        outputs = generate(dirs, validate=args.check, templates=templates, variants=variants, view=not args.no_view)
        if args.write:
            for d in dirs:
                write(d, outputs[d.name])
            for d in dirs:
                _validate(d)
                _case_size(d)
            for d in dirs:
                print(f"{d.name}: {', '.join(sorted(outputs[d.name]))} 씀")
            return OK
    except GenError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return CHECK_FAILED
    except (OSError, KeyError, TypeError) as exc:
        print(f"환경 오류: {exc!r}", file=sys.stderr)
        return USAGE
    try:
        for d in dirs:
            _case_size(d)
    except GenError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return CHECK_FAILED
    compared = {d.name: compare(d, outputs[d.name]) for d in dirs}
    drift = {name: [f"{f}: {s}" for f, s in rows if s != "일치"] for name, rows in compared.items()}
    if args.json:
        print(json.dumps(drift, ensure_ascii=False, indent=1))
    else:
        for name, rows in compared.items():
            for fname, status in rows:
                print(f"{name}/{fname}: {status}")
    return CHECK_FAILED if any(drift.values()) else OK


if __name__ == "__main__":
    sys.exit(main())
