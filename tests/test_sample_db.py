#!/usr/bin/env python3
"""Phase 1 완료 기준 확인 (11-phases.md Phase 1).

확인하는 것
1. 스키마 6종이 유효한 JSON Schema다
2. 합성 샘플의 모든 파일이 해당 스키마를 통과한다
   (type.md frontmatter, jira, feedback, .expect.yaml, parser-rules, 샘플 계획)
3. 파일 배치가 `03-issue-db.md §5.2`와 같다
4. fixture 이름이 `contracts.md §fixture`의 명명 규칙과 같다
5. fixture 내용이 시나리오에서 재생성한 결과와 같다 (결정성)
6. ID·참조 정합: 원인 ID 접두어와 순서, `related` 양방향, Jira `cause` 존재,
   `resolution_verification.evidence`·`fix.verification.fixture` 존재,
   `also_allowed`가 같은 유형·자기 자신을 가리키지 않음
7. `tools/make_db_skeleton.py` 결과에 유형·Jira·fixture·피드백이 없고 스키마를 통과한다

전체 lint(용어집, 정규식 안전, 마스킹 등)는 Phase 5의 `db_lint.py`가 한다.
여기서는 **이 시점까지 만든 것만으로** 확인할 수 있는 범위를 본다.

`pytest tests/test_sample_db.py`로도, 그냥 실행해도 돈다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
SCHEMA_DIR = SAMPLE / "schema"
PLAN_DIR = REPO / "tests" / "fixtures" / "plans"

sys.path.insert(0, str(REPO / "tests" / "helpers"))
import make_sample_fixtures  # noqa: E402

SCHEMAS = [
    "type.schema.json",
    "jira.schema.json",
    "feedback.schema.json",
    "plan.schema.json",
    "parser-rules.schema.json",
    "expect.schema.json",
]

CATEGORIES = ["data", "call", "network", "sim", "sms", "ims"]

TYPE_ID = r"[A-Z][A-Z0-9]*-\d{3}"
CAUSE_ID = TYPE_ID + r"-\d{2}"
BUILD = r"[A-Za-z0-9_+-][A-Za-z0-9._+-]*"
N1 = r"[1-9]\d*"
N2 = r"(?:[2-9]|[1-9]\d+)"

FIXTURE_PATTERNS = {
    "positive": rf"{CAUSE_ID}(?:\.{N2})?",
    "fixed": rf"{CAUSE_ID}\.fixed\.{BUILD}",
    "resolved": rf"{CAUSE_ID}\.resolved\.{N1}",
    "recurrence": rf"{CAUSE_ID}\.recurrence\.{BUILD}",
    "negative": rf"{TYPE_ID}\.none(?:\.{N2})?",
    "extra": rf"{CAUSE_ID}\.extra\.{N1}",
}


# -- 공통 ------------------------------------------------------------------


def _schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(_schema(name))


def test_plan_signatures_accept_named_patterns_and_legacy_strings():
    plan = json.loads((PLAN_DIR / "p7-analyze-new-cause.plan.json").read_text(encoding="utf-8"))
    signature = plan["operations"][0]["cause"]["signatures"][0]
    signature["must_match"] = [{"id": "reason", "pattern": "SIM_NOT_READY"}]
    signature["must_event"][0]["id"] = "rejected"
    signature["sequence"] = ["reason", "rejected"]
    for path in [SAMPLE / "schema/plan.schema.json"]:
        validator = Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
        assert not list(validator.iter_errors(plan)), path
        legacy = json.loads(json.dumps(plan))
        legacy_sig = legacy["operations"][0]["cause"]["signatures"][0]
        legacy_sig["must_match"] = ["SIM_NOT_READY"]
        legacy_sig.pop("sequence")
        assert not list(validator.iter_errors(legacy)), path


def test_plan_signature_rejects_incomplete_named_patterns():
    plan = json.loads((PLAN_DIR / "p7-analyze-new-cause.plan.json").read_text(encoding="utf-8"))
    signature = plan["operations"][0]["cause"]["signatures"][0]
    validator = _validator("plan.schema.json")
    for condition in ({"pattern": "SIM_NOT_READY"}, {"id": "reason"},
                      {"id": "bad id", "pattern": "SIM_NOT_READY"}, {"id": "reason", "pattern": ""},
                      {"id": "reason", "pattern": "SIM_NOT_READY", "extra": True}):
        signature["must_match"] = [condition]
        assert list(validator.iter_errors(plan)), condition


def _normalize(value):
    """YAML이 날짜로 읽은 값을 ISO 문자열로 되돌린다.

    `date: 2026-09-15`처럼 따옴표 없이 쓴 값을 PyYAML은 `datetime.date`로 읽는다.
    스키마는 **직렬화된 형태**(ISO 문자열)를 검사하므로 검사 전에 정규화한다.
    Phase 5의 `db_lint.py`도 같은 정규화를 거친다.
    """
    import datetime

    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return value


def _load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return _normalize(yaml.safe_load(fh))


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: frontmatter가 없습니다."
    end = text.index("\n---\n", 3)
    return _normalize(yaml.safe_load(text[4:end]))


def _type_files(root: Path = SAMPLE) -> list[Path]:
    return sorted(root.glob("*/*/type.md"))


def _fixture_kind(name: str) -> str | None:
    for kind, pattern in FIXTURE_PATTERNS.items():
        if re.fullmatch(pattern, name):
            return kind
    return None


def _errors(validator: Draft202012Validator, data, label: str) -> list[str]:
    return [
        f"{label}: {'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in validator.iter_errors(data)
    ]


# -- 1. 스키마 자체 --------------------------------------------------------


def test_schemas_are_valid_json_schema():
    missing = [name for name in SCHEMAS if not (SCHEMA_DIR / name).exists()]
    assert not missing, f"없는 스키마: {missing}"
    for name in SCHEMAS:
        Draft202012Validator.check_schema(_schema(name))


# -- 2. 샘플 파일이 스키마를 통과한다 --------------------------------------


def test_type_frontmatter_validates():
    validator = _validator("type.schema.json")
    types = _type_files()
    assert len(types) == len(CATEGORIES), f"유형 파일 수: {len(types)}"
    errors: list[str] = []
    for path in types:
        errors += _errors(validator, _frontmatter(path), path.relative_to(SAMPLE).as_posix())
    assert not errors, "\n".join(errors)


def test_jira_records_validate():
    validator = _validator("jira.schema.json")
    records = sorted(SAMPLE.glob("*/*/jira/*.yaml"))
    assert records, "Jira 기록이 없습니다."
    errors: list[str] = []
    for path in records:
        data = _load_yaml(path)
        errors += _errors(validator, data, path.relative_to(SAMPLE).as_posix())
        if data.get("key") != path.stem:
            errors.append(f"{path.name}: 파일명과 key가 다릅니다 ({data.get('key')})")
    assert not errors, "\n".join(errors)


def test_feedback_records_validate():
    validator = _validator("feedback.schema.json")
    records = sorted((SAMPLE / "feedback").glob("*/*.yaml"))
    assert records, "피드백 기록이 없습니다."
    errors: list[str] = []
    for path in records:
        data = _load_yaml(path)
        errors += _errors(validator, data, path.relative_to(SAMPLE).as_posix())
        if not path.name.startswith(str(data.get("jira")) + "-"):
            errors.append(f"{path.name}: 파일명이 jira 키로 시작하지 않습니다")
    assert not errors, "\n".join(errors)


def test_expect_files_validate():
    validator = _validator("expect.schema.json")
    files = sorted(SAMPLE.glob("*/*/fixtures/*.expect.yaml"))
    assert files, ".expect.yaml이 없습니다."
    errors: list[str] = []
    for path in files:
        data = _load_yaml(path)
        errors += _errors(validator, data, path.relative_to(SAMPLE).as_posix())
        if data.get("origin") != "synthetic":
            errors.append(f"{path.name}: 합성 fixture인데 origin: synthetic이 없습니다")
    assert not errors, "\n".join(errors)


def test_parser_rules_validate():
    validator = _validator("parser-rules.schema.json")
    files = sorted((SAMPLE / "parser-rules").glob("*.yaml"))
    assert len(files) == 3, f"parser-rules 파일 수: {len(files)}"
    errors: list[str] = []
    for path in files:
        errors += _errors(validator, _load_yaml(path), path.name)
    assert not errors, "\n".join(errors)


def test_sample_plans_validate():
    validator = _validator("plan.schema.json")
    plans = sorted(PLAN_DIR.glob("*.plan.json"))
    assert plans, "샘플 계획이 없습니다."
    errors: list[str] = []
    for path in plans:
        with path.open(encoding="utf-8") as fh:
            errors += _errors(validator, json.load(fh), path.name)
    assert not errors, "\n".join(errors)


# -- 3. 파일 배치 ----------------------------------------------------------


def test_sample_tree_layout():
    required = [
        "issue-db.config.yaml",
        ".gitignore",
        ".gitattributes",
        "CONTRIBUTING.md",
        "GLOSSARY.md",
        ".github/CODEOWNERS",
        ".github/pull_request_template.md",
        ".githooks/pre-commit",
        ".githooks/pre-push",
        "docs/getting-started.md",
        "docs/review-guide.md",
        "docs/branch-protection.md",
        "templates/type.md",
        "templates/cause.yaml",
        "templates/jira.yaml",
        "parser-rules/tags.yaml",
        "parser-rules/ril.yaml",
        "parser-rules/extractors.yaml",
    ]
    missing = [rel for rel in required if not (SAMPLE / rel).exists()]
    assert not missing, f"없는 파일: {missing}"

    for key in CATEGORIES:
        type_dirs = [p for p in (SAMPLE / key).iterdir() if p.is_dir()]
        assert len(type_dirs) == 1, f"{key}: 유형 디렉토리 {len(type_dirs)}개"
        type_dir = type_dirs[0]
        assert re.fullmatch(rf"{TYPE_ID}-[a-z0-9]+(?:-[a-z0-9]+)*", type_dir.name), type_dir.name
        assert (type_dir / "type.md").exists(), f"{type_dir.name}: type.md 없음"
        assert (type_dir / "jira").is_dir(), f"{type_dir.name}: jira/ 없음"
        assert (type_dir / "fixtures").is_dir(), f"{type_dir.name}: fixtures/ 없음"


def test_no_generated_files_committed():
    """생성 파일(README, STATS, CHANGELOG)은 db_build.py가 만든다 (Phase 5)."""
    generated = [
        SAMPLE / "README.md",
        SAMPLE / "STATS.md",
        SAMPLE / "parser-rules" / "CHANGELOG.md",
        *[SAMPLE / key / "README.md" for key in CATEGORIES],
    ]
    present = [p.relative_to(SAMPLE).as_posix() for p in generated if p.exists()]
    assert not present, f"생성 파일이 커밋돼 있습니다: {present}"


# -- 4. fixture 이름 -------------------------------------------------------


def test_fixture_names_match_contract():
    bad: list[str] = []
    for path in sorted(SAMPLE.glob("*/*/fixtures/*")):
        name = path.name
        if name.endswith(".expect.yaml"):
            base = name[: -len(".expect.yaml")]
        elif name.endswith(".log"):
            base = name[: -len(".log")]
        else:
            bad.append(f"{name}: .log도 .expect.yaml도 아님")
            continue
        if _fixture_kind(base) is None:
            bad.append(f"{name}: 명명 규칙에 맞지 않음")
            continue
        type_dir_id = path.parents[1].name.split("-")[0] + "-" + path.parents[1].name.split("-")[1]
        if not base.startswith(type_dir_id + "-") and not base.startswith(type_dir_id + "."):
            bad.append(f"{name}: 유형 디렉토리({type_dir_id})와 다른 ID")
    assert not bad, "\n".join(bad)


def test_every_active_cause_has_positive_fixture():
    missing: list[str] = []
    for path in _type_files():
        data = _frontmatter(path)
        names = {p.name for p in (path.parent / "fixtures").glob("*.log")}
        for cause in data["causes"]:
            if cause["status"] != "active":
                continue
            positives = [n for n in names if _fixture_kind(n[:-4]) == "positive" and n.startswith(cause["id"])]
            if not positives:
                missing.append(cause["id"])
    assert not missing, f"양성 fixture가 없는 원인: {missing}"


def test_fixtures_match_scenarios():
    """커밋된 fixture가 시나리오에서 재생성한 결과와 같다 (생성기는 결정적이다)."""
    result = make_sample_fixtures.run(check=True)
    assert not result["missing"], f"없는 fixture: {result['missing']}"
    assert not result["mismatched"], f"시나리오와 다른 fixture: {result['mismatched']}"


# -- 5. ID·참조 정합 -------------------------------------------------------


def _load_all_causes() -> dict[str, dict]:
    causes: dict[str, dict] = {}
    for path in _type_files():
        data = _frontmatter(path)
        for cause in data["causes"]:
            causes[cause["id"]] = {"cause": cause, "type": data, "path": path}
    return causes


def test_ids_and_category_prefixes():
    config = _load_yaml(SAMPLE / "issue-db.config.yaml")
    prefixes = {c["key"]: c["id_prefix"] for c in config["categories"]}
    errors: list[str] = []
    for path in _type_files():
        data = _frontmatter(path)
        category = path.parents[1].name
        rel = path.relative_to(SAMPLE).as_posix()
        if data["category"] != category:
            errors.append(f"{rel}: category({data['category']})가 디렉토리와 다름")
        if not data["id"].startswith(prefixes[category] + "-"):
            errors.append(f"{rel}: ID 접두어가 {prefixes[category]}가 아님")
        if not path.parent.name.startswith(data["id"] + "-"):
            errors.append(f"{rel}: 디렉토리 이름이 ID로 시작하지 않음")
        for index, cause in enumerate(data["causes"], start=1):
            expected = f"{data['id']}-{index:02d}"
            if cause["id"] != expected:
                errors.append(f"{rel}: 원인 ID 순서가 어긋남 ({cause['id']} != {expected})")
        for key in data["secondary_categories"]:
            if key not in prefixes:
                errors.append(f"{rel}: 없는 카테고리 {key}")
    assert not errors, "\n".join(errors)


def test_related_is_bidirectional():
    causes = _load_all_causes()
    errors: list[str] = []
    for cause_id, entry in causes.items():
        for other in entry["cause"]["related"]:
            if other not in causes:
                errors.append(f"{cause_id}: 없는 원인을 가리킴 ({other})")
            elif cause_id not in causes[other]["cause"]["related"]:
                errors.append(f"{cause_id} -> {other}: 역방향 related가 없음")
    assert not errors, "\n".join(errors)


def test_jira_cause_exists():
    causes = _load_all_causes()
    errors: list[str] = []
    keys: dict[str, str] = {}
    for path in sorted(SAMPLE.glob("*/*/jira/*.yaml")):
        data = _load_yaml(path)
        rel = path.relative_to(SAMPLE).as_posix()
        if data["key"] in keys:
            errors.append(f"{data['key']}: Jira 키가 중복됨 ({keys[data['key']]}, {rel})")
        keys[data["key"]] = rel
        if data["cause"] == "unresolved":
            continue
        if data["cause"] not in causes:
            errors.append(f"{rel}: 없는 원인 ({data['cause']})")
        elif causes[data["cause"]]["path"].parent != path.parents[1]:
            errors.append(f"{rel}: 원인의 유형 디렉토리에 있지 않음")
    assert not errors, "\n".join(errors)


def test_verification_references_exist():
    errors: list[str] = []
    jira_keys = {p.stem for p in SAMPLE.glob("*/*/jira/*.yaml")}
    for path in _type_files():
        data = _frontmatter(path)
        type_dir = path.parent
        rel = path.relative_to(SAMPLE).as_posix()
        for cause in data["causes"]:
            verification = cause["resolution_verification"]
            if verification["status"] == "verified":
                for item in verification["evidence"]:
                    if item.startswith("fixtures/"):
                        if not (type_dir / item).exists():
                            errors.append(f"{rel} {cause['id']}: evidence fixture 없음 ({item})")
                    elif item not in jira_keys:
                        errors.append(f"{rel} {cause['id']}: evidence Jira 없음 ({item})")
            fix = cause["fix"]
            entries = list(fix["verification_history"])
            if fix["verification"]:
                entries.append(fix["verification"])
            for entry in entries:
                fixture = entry.get("fixture")
                if fixture and not (type_dir / fixture).exists():
                    errors.append(f"{rel} {cause['id']}: 검증 fixture 없음 ({fixture})")
    assert not errors, "\n".join(errors)


def test_also_allowed_targets_other_types():
    causes = _load_all_causes()
    errors: list[str] = []
    for path in sorted(SAMPLE.glob("*/*/fixtures/*.expect.yaml")):
        data = _load_yaml(path)
        allowed = data.get("also_allowed") or []
        base = path.name[: -len(".expect.yaml")]
        own_type = base.split("-")[0] + "-" + base.split("-")[1]
        rel = path.relative_to(SAMPLE).as_posix()
        for cause_id in allowed:
            if cause_id not in causes:
                errors.append(f"{rel}: 없는 원인 ({cause_id})")
            elif cause_id.rsplit("-", 1)[0] == own_type:
                errors.append(f"{rel}: 같은 유형의 원인은 also_allowed에 넣을 수 없음 ({cause_id})")
    assert not errors, "\n".join(errors)


def test_signature_references_exist_in_parser_rules():
    """시그니처의 must_event가 parser-rules의 extractor 이벤트에 있다."""
    extractors = _load_yaml(SAMPLE / "parser-rules" / "extractors.yaml")["extractors"]
    events = {item["event"] for item in extractors}
    errors: list[str] = []
    for path in _type_files():
        data = _frontmatter(path)
        rel = path.relative_to(SAMPLE).as_posix()
        groups = [("symptom", data["symptom_signatures"])]
        for cause in data["causes"]:
            for kind in ("signatures", "recovery_signatures", "scenario_signatures"):
                groups.append((f"{cause['id']}/{kind}", cause[kind]))
        for label, signatures in groups:
            for signature in signatures:
                for item in signature.get("must_event", []):
                    name = item["event"]
                    if name.startswith("builtin.") or name.startswith("ext."):
                        continue  # 백엔드·어댑터 이벤트는 Phase 2에서 검사한다
                    if name not in events:
                        errors.append(f"{rel} {label}: extractor에 없는 이벤트 ({name})")
                ids = {item.get("id") for item in signature.get("must_event", []) if item.get("id")}
                for sig_id in signature.get("sequence", []):
                    if sig_id not in ids:
                        errors.append(f"{rel} {label}: sequence가 없는 id를 가리킴 ({sig_id})")
    assert not errors, "\n".join(errors)


# -- 6. 뼈대 ---------------------------------------------------------------


def test_skeleton_has_no_types_and_validates():
    out = Path(tempfile.mkdtemp(prefix="tt-skeleton-")) / "telephony-issue-db"
    try:
        subprocess.run(
            [sys.executable, str(REPO / "tools" / "make_db_skeleton.py"), str(out)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert not list(out.glob("*/*/type.md")), "뼈대에 유형이 있습니다."
        assert not list(out.glob("*/*/jira")), "뼈대에 Jira 기록이 있습니다."
        assert not list(out.glob("*/*/fixtures")), "뼈대에 fixture가 있습니다."
        assert not list((out / "feedback").glob("*/*.yaml")), "뼈대에 피드백이 있습니다."
        assert not (out / "README.md").exists(), "뼈대에 생성 파일이 있습니다."

        for key in CATEGORIES:
            assert (out / key / ".gitkeep").exists(), f"뼈대에 {key}/ 가 없습니다."
        for name in SCHEMAS:
            assert (out / "schema" / name).exists(), f"뼈대에 {name}이 없습니다."
        for name in ("type.md", "cause.yaml", "jira.yaml"):
            assert (out / "templates" / name).exists(), f"뼈대에 템플릿 {name}이 없습니다."

        validator = Draft202012Validator(
            json.loads((out / "schema" / "parser-rules.schema.json").read_text(encoding="utf-8"))
        )
        errors: list[str] = []
        for path in sorted((out / "parser-rules").glob("*.yaml")):
            data = _load_yaml(path)
            errors += _errors(validator, data, path.name)
            for section in ("tags", "requests", "unsolicited", "extractors"):
                for item in data.get(section) or []:
                    if item["added_for"] != "-":
                        errors.append(f"{path.name}: added_for가 '-'가 아님 ({item['added_for']})")
        assert not errors, "\n".join(errors)
    finally:
        shutil.rmtree(out.parent, ignore_errors=True)


def _all_tests():
    return [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]


if __name__ == "__main__":
    failures = 0
    for name, func in _all_tests():
        try:
            func()
            print(f"OK  {name}")
        except AssertionError as exc:
            failures += 1
            print(f"NG  {name}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERR {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(_all_tests()) - failures}/{len(_all_tests())} 통과")
    raise SystemExit(1 if failures else 0)
