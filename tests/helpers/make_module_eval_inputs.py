#!/usr/bin/env python3
"""모듈 eval case의 마스킹된 입력 파일을 결정적으로 만든다 (MODULE_SKILLS_PLAN_IMPL §5.5, C0 설계 §5).

`templates/module-skills/<p>/<m>/evals/<case>/files/source.log`(손으로 쓴 합성 로그)와 `case.yaml`에서
변형 DB `issue-db-ofono-modules`로 `triage.py run --offline-db`·`explore`를 돌려 아래를 만든다.

| kind | 만드는 파일 |
|---|---|
| deep | `events.json`(경로 정규화), `timeline.md`, `deep-input.json`(schema_version 1) |
| explore | `timeline.md`, `explore-input.json`(run이 쓴 그대로), `analysis.json`(`generated_at`·`request_hash`·`files` 뺌) |

`templates/module-skills/modules.yaml`에 그 플랫폼의 `common.filter`가 있으면 case `timeline.md`는 모듈 보기다
(B2 §4.6: `common.modulefilter.build`를 같은 프로세스에서, `triage.py module`과 같은 인자로 — deep은 `match.json`
1위 근거 창·고정 줄, 200줄/24KB; explore는 `anchor.fail`(없으면 발생 시각) 중심·고정 줄, 150줄/20KB). 필터가 없으면
오늘 그대로 `explore` 타임라인이다. case 디렉토리는 `skillcheck.CASE_CAP` 이하여야 한다(R34).

네트워크·claude를 쓰지 않는다. `files/`의 생성 파일은 손으로 고치지 않고 `--write`로만 다시 만든다.
pytest(`test_module_templates.py::test_generator_no_drift`)가 `--check`로 drift를 본다.

CLI:
    python3 tests/helpers/make_module_eval_inputs.py --write [--case NAME ...] [--templates DIR]
    python3 tests/helpers/make_module_eval_inputs.py --check [--case NAME ...] [--templates DIR] [--json]

종료 코드: 0 = 완료·drift 없음, 1 = drift 또는 기대값 불일치, 2 = 사용·환경 오류.
"""

from __future__ import annotations

import argparse
import json
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
    """load_case 규칙(C0 설계 §2.2) 중 키·합성 표시·입력 파일 집합·근거 regex·합성 표시 줄만."""
    import re

    data = yamlio.load(case_dir / "case.yaml")
    name = case_dir.name
    if not isinstance(data, dict) or set(data) != TOP_KEYS:
        raise GenError(f"{name}: 최상위 키가 {sorted(TOP_KEYS)}가 아니다")
    if data["name"] != name or data["synthetic"] is not True or data["schema_version"] != 1:
        raise GenError(f"{name}: name·synthetic·schema_version")
    kind = data["kind"]
    if set(data["input"]) != INPUT_KEYS[kind]:
        raise GenError(f"{name}: input 키")
    files = case_dir / "files"
    present = {p.name for p in files.iterdir()}
    if present != {"source.log", *GENERATED[kind]}:
        raise GenError(f"{name}: files/ 집합 {sorted(present)}")
    log = (files / "source.log").read_text(encoding="utf-8")
    if not log.startswith("-- [합성]"):
        raise GenError(f"{name}: source.log 첫 줄 합성 표시 없음")
    staged = "\n".join((case_dir / v).read_text(encoding="utf-8") for v in data["input"].values())
    for rx in data["expect"]["evidence"]:
        if not (re.search(rx, staged) and re.search(rx, log)):
            raise GenError(f"{name}: 근거 regex {rx!r}가 files/에 없다")


def case_dirs(templates: Path, names: list[str] | None) -> list[Path]:
    found = sorted(p.parent for p in templates.glob("ofono/*/evals/*/case.yaml"))
    if names:
        unknown = sorted(set(names) - {p.name for p in found})
        if unknown:
            raise ValueError(f"알 수 없는 case: {', '.join(unknown)}")
        found = [p for p in found if p.name in names]
    return found


def _issue_yaml(case: dict) -> str:
    """모의 Jira 이슈 YAML(`tests/mocks/jira/MOCK-1001.yaml` 모양). `--issue-file` → `jira_fields extract`(마스킹)."""
    issue = case["issue"]
    doc = {
        "key": case["key"],
        "fields": {
            "summary": issue["summary"],
            "description": issue["description"],
            "status": {"name": "Open"},
            "project": {"key": "MOCK", "name": "Mock Telephony"},
            "components": [{"name": "Data"}],
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


def build_case(case_dir: Path, case: dict, db: Path, root: Path, tmp: Path, runner) -> dict[str, str]:
    """case 하나의 생성 파일 {이름: 내용}."""
    name, kind = case_dir.name, case["kind"]
    module = case_dir.parent.parent.name                     # ofono/<m>/evals/<case>
    platform = case_dir.parent.parent.parent.name
    work = tmp / name
    (work / "logs").mkdir(parents=True)
    shutil.copyfile(case_dir / "files" / "source.log", work / "logs" / "source.log")
    (work / "issue.yaml").write_text(_issue_yaml(case), encoding="utf-8", newline="\n")
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
    if kind == "deep":
        top = candidates[0] if candidates else {}
        if top.get("cause") != expect["top_cause"] or top.get("C") != expect["C"] or top.get("category") != module:
            raise GenError(f"{name}: 1위 {top.get('cause')} C={top.get('C')} category={top.get('category')} "
                           f"— 기대 {expect['top_cause']} C={expect['C']} category={module}")
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
            raise GenError(f"{name}: explore.reason {reason} — 기대 {expect['explore_reason']}")
        if not explore_input.is_file():
            raise GenError(f"{name}: explore-input.json이 없다")
        explore_bytes = explore_input.read_bytes().decode("utf-8")
    _run(runner, root, ["explore", case["key"], "--out", job, "--platform", platform], home, name)
    timeline = (job / "timeline.md").read_bytes().decode("utf-8")
    view = module_view(job, case, kind, platform, module, analysis, events, explore_bytes)
    if view is not None:
        timeline = view
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
            "module": f"{platform}/{module}",
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
        out["analysis.json"] = _dump(analysis)
    for fname, text in out.items():          # 결정성: 임시 경로가 남으면 안 된다
        for marker in (str(tmp), str(REPO)):
            if marker in text:
                raise GenError(f"{name}/{fname}: 절대 경로가 남았다({marker[:40]}…)")
    assert set(out) == set(GENERATED[kind])
    return out


def _modules_doc() -> dict | None:
    """템플릿 `modules.yaml`(엄격 검사 통과). 검사기는 함수 안에서 부른다(skillcheck, B2 §4.6)."""
    if not MODULES_YAML.is_file():
        return None
    from common import skillcheck

    doc = skillcheck.load_modules_yaml(MODULES_YAML.read_bytes())
    errors = skillcheck.validate_modules(doc, strict=True)
    if errors:
        raise GenError("templates/module-skills/modules.yaml: " + "; ".join(errors[:3]))
    return doc


def module_view(job: Path, case: dict, kind: str, platform: str, module: str, analysis: dict, events: dict,
                explore_bytes: str | None) -> str | None:
    """필터가 있으면 모듈 보기 글, 없으면 None(오늘 타임라인 그대로)."""
    doc = _modules_doc()
    if doc is None:
        return None
    from common import modulefilter

    spec = modulefilter.compile_spec(doc, platform)
    if spec is None or not spec.has_filter:
        return None
    cap_rows, cap_bytes = VIEW_CAPS[kind]
    payload = {"op": "view", "modules": doc, "platform": platform, "events": str(job / "events.json"),
               "key": case["key"], "module": module, "mode": kind, "allow": events.get("mask_allow") or [],
               "cap_rows": cap_rows, "cap_bytes": cap_bytes, "with_modem": False}
    if kind == "deep":
        top = (analysis.get("candidates") or [{}])[0]
        match_path = job / "match.json"
        ev = []
        if match_path.is_file():
            ev = modulefilter.deep_evidence(json.loads(match_path.read_text(encoding="utf-8")), top)
        source = "근거"
        if not ev:
            ev = [{k: e.get(k) for k in ("ts", "tag", "msg", "event")} for e in top.get("evidence") or []]
            source = "근거 (analysis.json)"
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


def generate(dirs: list[Path], validate: bool) -> dict[str, dict[str, str]]:
    import make_variant_dbs
    import runner

    tmp = Path(tempfile.mkdtemp(prefix="tt-module-inputs-"))
    try:
        db = make_variant_dbs.build(VARIANT, tmp / "db")
        root = runner.plugin_root("ofono-on", platform=PLATFORM)
        return {d.name: build_case(d, _load_case(d, validate), db, root, tmp, runner) for d in dirs}
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_module_eval_inputs.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="files/의 생성 파일을 다시 쓴다")
    mode.add_argument("--check", action="store_true", help="다시 만들어 커밋된 파일과 바이트 비교")
    parser.add_argument("--case", action="append", metavar="NAME", help="case 이름(여러 번)")
    parser.add_argument("--templates", type=Path, default=TEMPLATES, help="템플릿 루트(기본 templates/module-skills)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    templates = args.templates.resolve()
    try:
        dirs = case_dirs(templates, args.case)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return USAGE
    if not dirs:
        print(f"case가 없다: {templates}/ofono/*/evals/*/case.yaml", file=sys.stderr)
        return USAGE
    try:
        outputs = generate(dirs, validate=args.check)
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
    report = {d.name: compare(d, outputs[d.name]) for d in dirs}
    drift = {name: [f"{f}: {s}" for f, s in rows if s != "일치"] for name, rows in report.items()}
    if args.json:
        print(json.dumps(drift, ensure_ascii=False, indent=1))
    else:
        for name, rows in report.items():
            for fname, status in rows:
                print(f"{name}/{fname}: {status}")
    return CHECK_FAILED if any(drift.values()) else OK


if __name__ == "__main__":
    sys.exit(main())
