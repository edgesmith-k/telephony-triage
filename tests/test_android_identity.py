"""Android 바이트 동일성 관문 (17-platforms 설계 §7-A, 묶음 1 중립화).

중립화 뒤에도 Android 경로는 이전과 같은 객체·값을 쓴다:
- `common.logtime`의 시각 함수·상수는 `platforms.android.logcat`이 다시 내보내는 **같은 객체**다.
- 계약 타입(`platforms.base`)도 `logcat`·`ril`이 같은 객체로 다시 내보낸다.
- `platforms.load(example)`의 필드는 묶음 전 `load()`가 쓰던 android 모듈 상수 그대로다.
- `SPEC`의 함수는 옮기기 전 판정과 같은 결과를 낸다(원문 줄·bugreport 머리·재부팅 줄).
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugin" / "scripts"))

import platforms  # noqa: E402
from common import logtime  # noqa: E402
from platforms import base  # noqa: E402
from platforms.android import REQUIRED_DIRS, SPEC, TELEPHONY_DIR, VERSION_SOURCES, bugreport, logcat, ril  # noqa: E402

EXAMPLE = REPO / "plugin" / "site-defaults.example.yaml"

LOGTIME_NAMES = ["UTC", "DEFAULT_YEAR", "BACKWARD_THRESHOLD_SEC", "JUMP_THRESHOLD_SEC", "STAMP_RE",
                 "get_tz", "open_log", "format_ts", "parse_ts", "normalize_ts", "coverage"]


@pytest.mark.parametrize("name", LOGTIME_NAMES)
def test_logtime_objects_are_reexported(name):
    assert getattr(logcat, name) is getattr(logtime, name)


@pytest.mark.parametrize("module,name", [(logcat, "LogLine"), (logcat, "FileStats"), (logcat, "PhoneIdRules"),
                                         (ril, "VendorRules"), (ril, "DEFAULT_LINK_MS")])
def test_contract_types_are_reexported(module, name):
    assert getattr(module, name) is getattr(base, name)


def test_stamp_pattern_unchanged():
    assert logtime.STAMP_RE.pattern == (
        r"(?:(?P<year>\d{4})-)?(?P<mon>\d{2})-(?P<day>\d{2})\s+"
        r"(?P<h>\d{2}):(?P<mi>\d{2}):(?P<s>\d{2})\.(?P<frac>\d{3,9})"
        r"(?:\s+(?P<zone>[+-]\d{4}))?")
    assert logcat.THREADTIME_RE.pattern.startswith("^" + logtime.STAMP_RE.pattern)
    assert logcat.TIME_RE.pattern.startswith("^" + logtime.STAMP_RE.pattern)


def test_load_example_equals_pre_bundle_fields():
    """묶음 전 `load()`는 android 모듈 상수로 프로파일을 채웠다. example(주석 값 제외)의 결과가 같은 객체다."""
    defaults = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    prof = platforms.load(defaults)
    assert prof == platforms.default()
    assert prof.name == "android" and prof.spec is SPEC
    assert prof.source_tree.required_dirs == REQUIRED_DIRS == (TELEPHONY_DIR,)
    assert prof.source_tree.version_sources is VERSION_SOURCES
    assert prof.phone is logcat.DEFAULT_PHONE_RULES
    assert prof.ril_tags == frozenset(ril.RIL_TAGS)
    assert prof.bugreport == bugreport.DEFAULT_RULES
    assert prof.ril_vendor is None


def test_spec_fields():
    assert SPEC.label == "Android"
    assert SPEC.primary_root == "aosp" and SPEC.default_root_keys == ("aosp", "vendor_ril")
    assert SPEC.default_backend == "reference"
    assert SPEC.block_keys == ("source_tree", "log", "ril", "bugreport")
    assert SPEC.log.read_file is logcat.read_file
    assert [p.name for p in SPEC.protocols] == ["ril"]
    assert SPEC.protocols[0].annotate is ril.parse and SPEC.protocols[0].pair is ril.pair
    assert SPEC.capture.looks_like is bugreport.looks_like_bugreport
    assert SPEC.capture.extract is bugreport.extract and SPEC.capture.error is bugreport.BugreportError
    assert SPEC.capture.default_rules is bugreport.DEFAULT_RULES


def _old_raw_line(line):          # guard 규칙 10의 옛 판정(logcat 부분)
    return bool(logcat.THREADTIME_RE.match(line) or logcat.TIME_RE.match(line))


def _old_sniff(line):             # guard 규칙 10의 옛 판정(bugreport 머리 부분)
    return line.startswith("== dumpstate") or (line.startswith("------ ") and line.rstrip().endswith(" ------"))


def _old_find_raw(text):          # issue_post `_raw_log_line`의 옛 구현
    for m in logcat.STAMP_RE.finditer(text):
        sub = text[m.start():]
        if logcat.THREADTIME_RE.match(sub) or logcat.TIME_RE.match(sub):
            return True
    return False


SAMPLES = [
    "09-20 14:32:11.123  1234  1300 E RILJ: [0042]< SETUP_DATA_CALL error=GENERIC_FAILURE",
    "2026-09-20 14:32:11.123 +0900  1234  1300 I DNC-0: x",
    "09-20 14:32:11.123 I/RILJ( 1234): y",
    "원인: 09-20 14:32:11.123  1234  1300 E RILJ: z 줄이 끼었다",
    "09-20 14:32:11.123 만 있는 문장",
    "== dumpstate: 2026-09-20 14:32:11",
    "------ RADIO LOG (logcat -b radio -v threadtime -d *:v) ------",
    "------ not a section",
    "--------- beginning of radio",
    "",
    "평범한 문장",
]


@pytest.mark.parametrize("text", SAMPLES)
def test_spec_functions_match_old_logic(text):
    assert SPEC.log.raw_line(text) == _old_raw_line(text)
    assert SPEC.capture.sniff_line(text) == _old_sniff(text)
    assert SPEC.log.find_raw(text) == _old_find_raw(text)


@pytest.mark.parametrize("tag,msg,expect", [
    ("boot_progress_start", "1", True), ("kernel", "Linux version 6.1", True), ("Kernel", "Linux version x", True),
    ("kernel", "other", False), ("DNC-0", "Linux version 6.1", False),
])
def test_epoch_break(tag, msg, expect):
    line = base.LogLine(0, 1, datetime(2026, 1, 1, tzinfo=timezone.utc), 1, 1, "I", tag, msg)
    assert SPEC.log.epoch_break(line) is expect


def test_code_roots_defaults_come_from_spec():
    import code_roots

    assert code_roots.TELEPHONY_DIR is TELEPHONY_DIR
    assert code_roots.VERSION_SOURCES is VERSION_SOURCES
    assert code_roots.DEFAULT_KEYS == ["aosp", "vendor_ril"]


def test_parse_logcat_bugreport_alias():
    import parse_logcat

    assert parse_logcat._looks_like_bugreport is SPEC.capture.looks_like


def test_reference_backend_is_android():
    import parser_backends

    backend = parser_backends.load("reference")
    assert backend.platform == "android"
    assert backend.log_format() is SPEC.log
    assert platforms.backend_name({"parser": {"backend": "reference"}}, "android") == "reference"


def test_supported_versions_reads_only_new_key():
    """원칙 (d): 옛 이름 `android_versions_supported`는 읽지 않는다(db_lint가 config 오류로 알린다)."""
    from common import issuedb

    assert issuedb.supported_versions({"platform_versions_supported": [16, "17"]}) == (
        "platform_versions_supported", ["16", "17"])
    assert issuedb.supported_versions({}) == ("platform_versions_supported", [])
    assert issuedb.supported_versions({"android_versions_supported": ["16"]}) == ("platform_versions_supported", [])


def test_no_android_module_import_outside_platforms():
    """핵심 모듈은 `platforms.android`를 직접 import하지 않는다. 예외는 android 파서 백엔드: reference 다시 내보내기와
    사내 `site` 백엔드(`parser_backends/site/`, SITE_PATHS — reference 공통 처리를 재사용할 수 있다, 16-existing-assets.md §16.3)."""
    scripts = REPO / "plugin" / "scripts"
    allowed = {"parser_backends/reference/__init__.py"}
    offenders = []
    for path in sorted(scripts.rglob("*.py")):
        rel = path.relative_to(scripts).as_posix()
        if rel.startswith(("platforms/", "parser_backends/site/")) or rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(from\s+platforms\.android\b|import\s+platforms\.android\b"
                     r"|from\s+platforms\s+import\s+(?:\(\s*)?(?:[\w\s,]*,\s*)?android\b)", text, re.M) \
                or re.search(r"""import_module\(\s*["']platforms\.android""", text):
            offenders.append(rel)
    assert offenders == []
