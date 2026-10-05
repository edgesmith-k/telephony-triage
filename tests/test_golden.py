#!/usr/bin/env python3
"""골든 테스트 틀 (16-existing-assets.md §16.3, §16.6).

사내에서 **검증된 기존 파서를 파서 백엔드로 포팅**할 때 동작이 보존되는지
확인하는 틀이다. 사외에서는 모의 site 백엔드와 모의 골든으로 틀만 돌려
동작을 확인한다.

사내(S-4a) 절차
1. 포팅 **전에** 기존 파서로 실제 로그를 돌려 출력을 저장한다:
   `tests/golden/<이름>.orig.json` (사내 전용, SITE_PATHS).
2. 기존 출력 → 이벤트 형식 변환 규칙(매핑표)을 정하고 사용자 확인을 받는다.
3. 포팅한 백엔드의 결과가 변환된 골든과 같은지 이 테스트로 비교한다.
4. 의도적으로 바꾼 부분은 사용자 승인 후에만 골든을 갱신하고 이유를
   `SITE_PROFILE.md`에 기록한다.

사외에서 도는 것 (Phase D0 틀, Phase 2에서 base.py 상속으로 바꿈)
- 케이스 목록: `tests/mocks/golden/cases.yaml`
- 골든: `tests/mocks/golden/<이름>.golden.json` (모의)
- 로그: 시나리오에서 그때그때 생성한다 (생성기는 결정적이다)

골든 갱신:
    python3 tests/test_golden.py --update

`pytest tests/test_golden.py`로도 돈다.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO / "tests" / "mocks" / "golden"
CASES = GOLDEN_DIR / "cases.yaml"

sys.path.insert(0, str(REPO / "tests" / "mocks"))
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import logcat_gen  # noqa: E402
import parser_backends  # noqa: E402  (plugin/scripts/parser_backends)
from common import masking  # noqa: E402

MOCK_SITE_DIR = REPO / "tests" / "mocks" / "parser_backends" / "site"


def _load_mock_site():
    """모의 site 백엔드를 `parser_backends.site`로 불러온다.

    사내에서는 `plugin/scripts/parser_backends/site/`(SITE_PATHS)에 있고, 사외 테스트는
    `make_plugin_root.py --with-site-backend`가 임시 루트로 복사한다. 여기서는 같은
    패키지 이름으로 직접 불러서 상대 import(`..reference`)가 그대로 동작하게 한다.
    """
    import importlib.util

    name = "parser_backends.site"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, MOCK_SITE_DIR / "__init__.py", submodule_search_locations=[str(MOCK_SITE_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


site_backend = _load_mock_site().BACKEND

# 비교에서 뺄 필드 (파일 경로·순번처럼 환경에 따라 달라지는 값이 생기면 여기에).
# `line_ref`는 입력 파일 순번·줄 번호라 골든(사내 포팅 결과)의 일부가 아니다. 백엔드가 내는지는
# `test_backend_emits_line_ref`가 따로 본다 (04-parser-matching.md §5.8 (6)).
VOLATILE_FIELDS: tuple[str, ...] = ("line_ref",)

def _mask_text(text: str) -> str:
    """마스킹 민감도 검사용: 파일 하나를 `mask_pii.py <file>`와 같이 마스킹한다
    (`common/masking.py`, 번호 토큰 `<종류#n>`, 08-safety.md §8)."""
    masker = masking.new_masker(text)
    return "\n".join(masker(line) for line in text.split("\n"))


def _normalize(events: list[dict]) -> list[dict]:
    out = []
    for event in events:
        item = {k: v for k, v in event.items() if k not in VOLATILE_FIELDS}
        out.append(item)
    return out


def _load_cases() -> list[dict]:
    with CASES.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("cases", [])


def _make_log(case: dict, out_dir: Path) -> Path:
    info = logcat_gen.generate(REPO / case["scenario"], out_dir, name=case["name"])
    return Path(info["files"][0])


def _run_backend(case: dict, log: Path) -> list[dict]:
    return _normalize(
        site_backend.parse([log], case.get("tz"), case.get("year"), None)
    )


def build_actual(case: dict, out_dir: Path) -> dict:
    log = _make_log(case, out_dir)
    events = _run_backend(case, log)

    masked_log = out_dir / f"{case['name']}.masked.log"
    masked_log.write_text(
        _mask_text(log.read_text(encoding="utf-8")),
        encoding="utf-8",
        newline="\n",
    )
    masked_events = _normalize(
        site_backend.parse([masked_log], case.get("tz"), case.get("year"), None)
    )
    return {
        "backend": {"name": site_backend.name, "version": site_backend.version()},
        "builtin_events": site_backend.builtin_events(),
        "events": events,
        "masked_builtin_events": [e["event"] for e in masked_events if e.get("event")],
    }


def golden_path(case: dict) -> Path:
    return GOLDEN_DIR / f"{case['name']}.golden.json"


def update_goldens() -> list[Path]:
    written = []
    with tempfile.TemporaryDirectory(prefix="tt-golden-") as tmp:
        for case in _load_cases():
            actual = build_actual(case, Path(tmp))
            path = golden_path(case)
            path.write_text(
                json.dumps(actual, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            written.append(path)
    return written


# -- pytest ----------------------------------------------------------------


def _cases_for_pytest():
    return [(case["name"], case) for case in _load_cases()]


def _compare(case: dict, tmp_path: Path) -> tuple[dict, dict]:
    actual = build_actual(case, tmp_path)
    expected = json.loads(golden_path(case).read_text(encoding="utf-8"))
    return actual, expected


def test_golden_matches(tmp_path=None):
    """포팅한 백엔드의 결과가 골든과 같다."""
    tmp = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp(prefix="tt-golden-"))
    for case in _load_cases():
        actual, expected = _compare(case, tmp)
        assert actual["events"] == expected["events"], (
            f"{case['name']}: 백엔드 출력이 골든과 다릅니다. "
            "포팅 버그이거나, 의도한 변경이면 사용자 승인 후 --update 하세요."
        )
        assert actual["backend"]["version"] == expected["backend"]["version"], (
            f"{case['name']}: 백엔드 버전이 바뀌었습니다. "
            "골든·회귀 기준이 흔들리므로 승인 후 갱신하세요."
        )


def test_golden_detects_change(tmp_path=None):
    """골든을 일부러 바꾸면 비교가 실패한다 (11-phases.md Phase 2 완료 기준)."""
    tmp = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp(prefix="tt-golden-"))
    case = _load_cases()[0]
    actual, expected = _compare(case, tmp)
    assert actual["events"] == expected["events"]
    tampered = copy.deepcopy(expected)
    builtin = next(e for e in tampered["events"] if e.get("event"))
    builtin["fields"] = {**builtin["fields"], "reasons": "TAMPERED"}
    assert actual["events"] != tampered["events"], "골든을 바꿨는데 비교가 통과합니다."


def test_backend_emits_line_ref(tmp_path=None):
    """백엔드가 모든 이벤트에 `line_ref`(마지막 키)를 낸다. builtin은 그 줄 레코드의 값을 그대로 갖는다."""
    tmp = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp(prefix="tt-golden-"))
    for case in _load_cases():
        log = _make_log(case, tmp)
        events = site_backend.parse([log], case.get("tz"), case.get("year"), None)
        raw = log.read_text(encoding="utf-8").split("\n")
        for n, event in enumerate(events):
            assert list(event)[-1] == "line_ref", case["name"]
            ref = event["line_ref"]
            assert ref["file_index"] == 0 and ref["line_no"] >= 1, (case["name"], ref)
            assert event["tag"] in raw[ref["line_no"] - 1], (case["name"], ref)
            if event.get("event"):
                assert events[n - 1]["line_ref"] == ref, case["name"]


def test_builtin_events_declared(tmp_path=None):
    """이벤트 이름이 `builtin_events()` 목록 안에 있다.

    `db_lint`가 시그니처의 `must_event: builtin.*`을 이 목록으로 검사한다
    (`contracts.md §기존 자산 연결 계약`).
    """
    declared = set(site_backend.builtin_events())
    tmp = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp(prefix="tt-golden-"))
    for case in _load_cases():
        actual = build_actual(case, tmp)
        produced = {e["event"] for e in actual["events"] if e.get("event")}
        assert produced <= declared, (
            f"{case['name']}: 선언되지 않은 builtin 이벤트: {sorted(produced - declared)}"
        )


def test_masking_does_not_change_detection(tmp_path=None):
    """원본과 마스킹된 로그에서 builtin 이벤트 이름이 같다.

    기존 판별 로직이 값 비교에 기대면 마스킹에 민감할 수 있다
    (16-existing-assets.md §16.3 "마스킹과의 관계"). 다르면 사내 포팅 때
    사용자에게 보고해야 한다.
    """
    tmp = Path(tmp_path) if tmp_path else Path(tempfile.mkdtemp(prefix="tt-golden-"))
    for case in _load_cases():
        actual = build_actual(case, tmp)
        original = [e["event"] for e in actual["events"] if e.get("event")]
        assert original == actual["masked_builtin_events"], (
            f"{case['name']}: 마스킹 후 판별 결과가 달라집니다. "
            "그 판별은 마스킹에 민감하므로 포팅 때 처리 방법을 정해야 합니다."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="test_golden.py", description=__doc__)
    parser.add_argument("--update", action="store_true", help="골든을 다시 쓴다")
    args = parser.parse_args(argv)

    if args.update:
        for path in update_goldens():
            print(path)
        return 0

    with tempfile.TemporaryDirectory(prefix="tt-golden-") as tmp:
        failures = 0
        for case in _load_cases():
            try:
                actual, expected = _compare(case, Path(tmp))
                assert actual["events"] == expected["events"]
                print(f"OK  {case['name']}")
            except AssertionError:
                failures += 1
                print(f"NG  {case['name']}")
                actual_copy = copy.deepcopy(actual)
                print(
                    "    첫 차이:",
                    next(
                        (
                            f"#{i} {a} != {b}"
                            for i, (a, b) in enumerate(
                                zip(actual_copy["events"], expected["events"])
                            )
                            if a != b
                        ),
                        "길이가 다릅니다",
                    ),
                )
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
