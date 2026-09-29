#!/usr/bin/env python3
"""변형 이슈 DB를 합성 샘플에서 만든다 (11-phases.md Phase 5, CLAUDE.md §11.0).

샘플 트리(`tests/fixtures/issue-db-sample/`)를 복사한 뒤 정해진 변경을 결정적으로 적용한다.
샘플 트리는 건드리지 않는다. 결과는 **커밋한다**.

| 변형 | 용도 |
|---|---|
| `issue-db-lint-errors/` | 린터가 잡아야 할 오류를 일부러 넣은 트리 (`tests/test_db_lint.py`의 `EXPECTED`) |
| `issue-db-empty-category/` | sms·ims 유형을 뺀 트리. README의 0건 카테고리 표시 |
| `issue-db-pending/` | `signatures_pending` 원인(DATA-001-03)과 그 양성 fixture. 회귀 기대값 `DATA-001:unresolved` |
| `issue-db-dup-id/` | 머지 간격으로 main에 같은 ID(DATA-001-03 두 번)와 같은 Jira(MOCK-1101 두 곳)가 들어온 트리. 사후 lint 보고 (Phase 7) |
| `issue-db-verify/` | 검증(Phase 10): CALL-001-01을 `fix-submitted`로 되돌리고(수정 후 fixture 제거) 같은 증상의 다른 원인 CALL-001-02(망 거절, scenario만 있음)와 그 양성 fixture를 넣은 트리 |
| `verify-logs/` | 이슈 DB가 아니다. `db_verify fix`·`resolution` 입력 로그(수정 후·재발·증상만 남음·시나리오 없음, 마스킹됨) |

CLI:
    python3 tests/helpers/make_variant_dbs.py [--check] [--json]
"""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "tests" / "fixtures" / "issue-db-sample"
OUT = REPO / "tests" / "fixtures"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "tests" / "mocks"))


def _edit(path: Path, old: str, new: str, count: int = 1) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"{path}: 바꿀 문자열이 없습니다: {old[:60]!r}")
    path.write_text(text.replace(old, new, count), encoding="utf-8", newline="\n")


def _sub(path: Path, pattern: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    out, n = re.subn(pattern, new, text, count=1, flags=re.S)
    if not n:
        raise SystemExit(f"{path}: 패턴이 없습니다: {pattern[:60]!r}")
    path.write_text(out, encoding="utf-8", newline="\n")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


MINIMAL_TYPE = """---
id: {tid}
category: {cat}
secondary_categories: []
title: {title}
summary: 린터 시험용 유형
status: active
symptom_signatures: {symptoms}
causes:
  - id: {tid}-01
    status: active
    title: 시험 원인
    description: 린터 시험용 원인
    signatures:
      - id: probe
        must_event:
          - {{event: network_service_state}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 시험용이다
    resolution_type: network
    resolution_verification: {{status: unverified}}
    fix: {{status: open, ref: null, fixed_in: [], verification: null, verification_history: []}}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: []
---

## 증상

린터 시험용.
"""


def lint_errors(db: Path) -> None:
    data = db / "data/DATA-001-no-setup-data-call"
    call = db / "call/CALL-001-volte-not-working"
    net = db / "network/NETWORK-001-no-service"
    sim = db / "sim/SIM-001-sim-not-detected"
    sms = db / "sms/SMS-001-sms-send-failed"
    ims = db / "ims/IMS-001-ims-registration-failed"

    # duplicate-id: 같은 유형 ID(SMS-001)와 원인 ID(SMS-001-01)를 가진 두 번째 유형
    dup = db / "sms/SMS-001-duplicate-id"
    dup.mkdir(parents=True)
    shutil.copyfile(sms / "type.md", dup / "type.md")
    # duplicate-jira: 다른 유형 디렉토리에 같은 Jira 키
    _write(call / "jira/MOCK-1101.yaml",
           (data / "jira/MOCK-1101.yaml").read_text(encoding="utf-8").replace("cause: DATA-001-01", "cause: CALL-001-01"))
    # glossary: 금지 동의어 "통화 단절"
    _edit(call / "type.md", "title: VoLTE가 동작하지 않음", "title: VoLTE 통화 단절")
    # related: 없는 원인
    _edit(net / "type.md", "    related: []", "    related: [NETWORK-009-01]")
    # code-ref: 절대 경로
    _edit(data / "type.md",
          "      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataSettingsManager.java\n"
          "        symbol: DataSettingsManager#isDataRoamingEnabled",
          "      - ref: /home/user/android16/frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataSettingsManager.java\n"
          "        symbol: DataSettingsManager#isDataRoamingEnabled")
    # id-prefix: network 카테고리에 NET- 접두어
    _write(db / "network/NET-002-bad-prefix/type.md",
           MINIMAL_TYPE.format(tid="NET-002", cat="network", title="접두어가 틀린 유형",
                               symptoms="\n  - id: probe\n    must_event:\n      - {event: network_service_state}\n    window_sec: 60"))
    # symptom-missing: 빈 증상 시그니처
    _write(db / "sim/SIM-002-no-symptom/type.md",
           MINIMAL_TYPE.format(tid="SIM-002", cat="sim", title="증상 시그니처 없는 유형", symptoms="[]"))
    # fixture-name: 규칙 밖 이름 (.resolved에 번호 없음, 양성 .1)
    shutil.copyfile(data / "fixtures/DATA-001-01.log", data / "fixtures/DATA-001-01.resolved.log")
    shutil.copyfile(data / "fixtures/DATA-001-02.log", data / "fixtures/DATA-001-02.1.log")
    # raw-identifier: 시그니처와 extractor의 원본 IMSI/ICCID 패턴
    _edit(sim / "type.md", "    signatures:\n      - id: card-io-error-then-absent\n",
          "    signatures:\n      - id: raw-imsi\n        must_match: ['imsi=\\d{15}']\n        window_sec: 60\n"
          "      - id: card-io-error-then-absent\n")
    _edit(db / "parser-rules/extractors.yaml", "extractors:\n",
          "extractors:\n  - id: raw-iccid\n    added_for: SIM-001\n    added_on: 2026-09-29\n    reason: 린터 시험용\n"
          "    tag: UiccController\n    patterns: ['iccid=(?P<iccid>89\\d{17})']\n    event: raw_iccid\n    fields: [iccid]\n\n")
    # signatures-missing: pending 표시 없이 빈 시그니처
    _sub(sms / "type.md", r"    signatures:\n      - id: smsc-missing-then-fail\n.*?(    recovery_signatures:)",
         "    signatures: []\n\\1")
    # pending-on-type: 유형에 붙은 signatures_pending
    _edit(ims / "type.md", "status: active\nsymptom_signatures:", "status: active\nsignatures_pending: true\nsymptom_signatures:")
    # verified-without-evidence
    _edit(data / "type.md", "    resolution_verification: {status: unverified}",
          "    resolution_verification: {status: verified, method: 확인, by: mock-user1, date: 2026-09-20}")
    # fix-ref: fix_ref_regex에 맞지 않는 ref
    _edit(sim / "type.md", "      ref: MOCKCL-23456", "      ref: CL 23456")
    # builtin-event (reference 백엔드에는 builtin 이벤트가 없다), ext-event (external_parsers 없음)
    _edit(data / "type.md", "    signatures:\n      - id: data-disabled\n",
          "    signatures:\n      - id: builtin-ref\n        must_event:\n          - {event: builtin.data.setup_not_allowed}\n"
          "        window_sec: 60\n      - id: data-disabled\n")
    _edit(call / "type.md", "    signatures:\n      - id: ims-not-registered-on-dial\n",
          "    signatures:\n"
          "      - id: ext-ref\n        must_event:\n          - {event: ext.call.dropped}\n        window_sec: 60\n"
          "      - id: seq-missing\n        must_event:\n          - {id: a, event: ims_dial_attempt}\n"
          "          - {id: b, event: call_fail_cause}\n        sequence: [a, c]\n        window_sec: 60\n"
          "      - id: seq-dup\n        must_event:\n          - {id: a, event: ims_dial_attempt}\n"
          "          - {id: a, event: call_fail_cause}\n        window_sec: 60\n"
          "      - id: seq-not\n        must_event:\n          - {id: a, event: ims_dial_attempt}\n"
          "        must_not_match:\n          - {id: nm, pattern: 'X'}\n        sequence: [a, nm]\n        window_sec: 60\n"
          "      - id: ims-not-registered-on-dial\n")
    # fixed-token: 특정 마스킹 번호 고정
    _edit(net / "type.md", "    signatures:\n      - id: reject-cause-subscriber\n",
          "    signatures:\n      - id: fixed-token\n        must_match: ['cellId=<CELL#1>']\n        window_sec: 60\n"
          "      - id: reject-cause-subscriber\n")
    # regex-unsafe: 중첩 수량자
    _edit(ims / "type.md", "    signatures:\n      - id: registration-forbidden\n",
          "    signatures:\n      - id: nested\n        must_match: ['(a+)+b']\n        window_sec: 60\n"
          "      - id: registration-forbidden\n")
    # raw-identifier: Jira note와 cp_evidence의 원본 전화번호
    _edit(net / "jira/MOCK-3101.yaml", "note: 등록 거절 코드 13 반복, 서비스 없음 표시",
          "note: 등록 거절 코드 13 반복, 고객 010-1234-5678 확인")
    _edit(net / "type.md", "    cp_evidence: 거절 코드 자체는 CP에서 올라온다.",
          "    cp_evidence: 담당자 연락처 +82-10-1111-2222. 거절 코드 자체는 CP에서 올라온다.")
    # also-allowed: 자기 원인, 같은 유형 원인, 없는 ID
    _edit(data / "fixtures/DATA-001-01.expect.yaml", "origin: synthetic",
          "also_allowed: [DATA-001-01, DATA-001-02, NOPE-001-01]\norigin: synthetic")
    # evidence-missing: 없는 fixture 경로와 없는 Jira 키
    _edit(call / "type.md", "      evidence: [fixtures/CALL-001-01.resolved.1.log]",
          "      evidence: [fixtures/CALL-001-01.resolved.9.log, MOCK-9999]")


def empty_category(db: Path) -> None:
    for rel in ("sms/SMS-001-sms-send-failed", "ims/IMS-001-ims-registration-failed"):
        shutil.rmtree(db / rel)
    for key in ("sms", "ims"):
        _write(db / key / ".gitkeep", "")
    _edit(db / "call/CALL-001-volte-not-working/type.md", "    related: [IMS-001-01]", "    related: []")
    _edit(db / "call/CALL-001-volte-not-working/type.md", "secondary_categories: [ims]", "secondary_categories: []")
    expect = db / "call/CALL-001-volte-not-working/fixtures/CALL-001-01.expect.yaml"
    _sub(expect, r"also_allowed:\n(?:- .*\n)+", "")
    for path in sorted((db / "feedback").glob("*/*.yaml")):
        if "SMS-" in path.read_text(encoding="utf-8") or "IMS-" in path.read_text(encoding="utf-8"):
            path.unlink()


def pending(db: Path) -> None:
    import make_sample_fixtures  # noqa: WPS433 — 같은 마스킹·생성 규칙을 쓴다

    import logcat_gen

    data = db / "data/DATA-001-no-setup-data-call"
    _edit(data / "type.md", "tags: [data-evaluation]\n---", """  - id: DATA-001-03
    status: active
    title: SIM 준비 안 됨 (미확정)
    description: 수동 기록으로 추가한 원인. 판별 시그니처는 아직 없다
    signatures: []
    signatures_pending: true
    recovery_signatures: []
    scenario_signatures: []
    resolution: SIM 상태를 확인한다
    resolution_type: framework-bug
    resolution_verification: {status: unverified, method: "근거: 사용자 진술"}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: [data-evaluation]
---""")
    tmp = Path(tempfile.mkdtemp(prefix="tt-variant-"))
    try:
        info = logcat_gen.generate(REPO / "tests/mocks/scenarios/data-001-03-pending.yaml", tmp, name="DATA-001-03")
        log = Path(info["files"][0])
        make_sample_fixtures.mask_log(log, make_sample_fixtures.sample_allow_patterns())
        shutil.copyfile(log, data / "fixtures/DATA-001-03.log")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def dup_id(db: Path) -> None:
    """두 PR이 sync-pr 없이 차례로 머지된 결과: 같은 원인 ID 두 개, 같은 Jira 파일 두 개 (06-collaboration.md §6.3)."""
    data = db / "data/DATA-001-no-setup-data-call"
    block = """  - id: DATA-001-03
    status: active
    title: {title}
    description: {desc}
    signatures:
      - id: {sig}
        must_event:
          - {{event: data_evaluation_rejected, fields: {{reasons: '.*{reason}.*'}}}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: {res}
    resolution_type: framework-bug
    resolution_verification: {{status: unverified}}
    fix: {{status: open, ref: null, fixed_in: [], verification: null, verification_history: []}}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
"""
    first = block.format(title="SIM 미준비", desc="SIM 초기화 전에 평가가 거부됨", sig="sim-not-ready",
                         reason="SIM_NOT_READY", res="SIM 로딩 뒤 데이터 평가를 다시 요청하도록 고친다")
    second = block.format(title="무선 꺼짐", desc="무선이 꺼진 상태에서 평가가 거부됨", sig="radio-off",
                          reason="RADIO_POWER_OFF", res="무선 전원 상태 복구 뒤 평가를 다시 요청하도록 고친다")
    _edit(data / "type.md", "tags: [data-evaluation]\n---", first + second + "tags: [data-evaluation]\n---")
    dup = db / "call/CALL-001-volte-not-working/jira/MOCK-1101.yaml"
    text = (data / "jira/MOCK-1101.yaml").read_text(encoding="utf-8").replace("cause: DATA-001-01", "cause: CALL-001-01")
    _write(dup, text)


CALL_001_02 = """  - id: CALL-001-02
    status: active
    title: 망 측 통화 거절
    description: IMS 등록은 정상인데 망이 통화를 거절(cause 31)해 콜이 바로 종료됨
    signatures:
      - id: network-reject-31
        must_event:
          - {id: dial, event: ims_dial_attempt, fields: {registered: 'true'}}
          - {id: failed, event: call_fail_cause, fields: {cause: '31'}}
        sequence: [dial, failed]
        window_sec: 120
    recovery_signatures: []
    scenario_signatures:
      - id: volte-dial-attempt
        must_event:
          - {event: ims_dial_attempt}
        window_sec: 60
    resolution: 망 측 거절 사유를 캐리어에 문의한다
    resolution_type: network
    resolution_verification: {status: unverified}
    fix: {status: not-a-bug, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: ["17"]
    code_refs: []
"""


def _gen(scenario: str, dest: Path, name: str) -> None:
    """시나리오 하나를 만들어 마스킹한 뒤 `dest`에 쓴다 (샘플 fixture와 같은 규칙)."""
    import make_sample_fixtures  # noqa: WPS433

    import logcat_gen

    tmp = Path(tempfile.mkdtemp(prefix="tt-variant-"))
    try:
        info = logcat_gen.generate(REPO / "tests/mocks/scenarios" / scenario, tmp, name=name)
        log = Path(info["files"][0])
        make_sample_fixtures.mask_log(log, make_sample_fixtures.sample_allow_patterns())
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(log, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verify(db: Path) -> None:
    """Phase 10 검증용: CALL-001-01 fix-submitted(빌드 있는 fixed_in), 수정 후 fixture 없음, CALL-001-02 추가."""
    call = db / "call/CALL-001-volte-not-working"
    _sub(call / "type.md", r"    fix:\n      status: fixed\n.*?      verification_history:\n",
         "    fix:\n      status: fix-submitted\n      ref: MOCKCL-12345\n      fixed_in:\n"
         "        - {branch: MOCKB77_U2, build: MOCKB77_U2_20260920}\n      verification: null\n"
         "      verification_history:\n")
    _edit(call / "type.md", "tags: [volte, ims-registration]\n---", CALL_001_02 + "tags: [volte, ims-registration]\n---")
    for name in ("CALL-001-01.fixed.MOCKB77_U2_20260920.log", "CALL-001-01.fixed.MOCKB77_U2_20260920.expect.yaml"):
        (call / "fixtures" / name).unlink()
    _gen("call-001-02-positive.yaml", call / "fixtures/CALL-001-02.log", "CALL-001-02")
    _write(call / "fixtures/CALL-001-02.expect.yaml", "origin: synthetic\n")


VERIFY_LOGS = {"call-fixed.log": "verify-call-fixed.yaml", "call-recurrence.log": "verify-call-recurrence.yaml",
               "call-partial.log": "verify-call-partial.yaml", "call-noscenario.log": "verify-call-noscenario.yaml"}

VERIFY_LOGS_README = """# db_verify 입력 로그 (Phase 10)

`tests/helpers/make_variant_dbs.py`가 `tests/mocks/scenarios/verify-call-*.yaml`에서 만든다(마스킹됨). 이슈 DB가 아니다.
대상은 `tests/fixtures/issue-db-verify/`의 CALL-001-01(fix-submitted, fixed_in MOCKB77_U2_20260920)이다.

| 파일 | 내용 | `db_verify fix --cause CALL-001-01` |
|---|---|---|
| `call-fixed.log` | 등록 정상, 등록 상태로 발신, 통화 ACTIVE | passed |
| `call-recurrence.log` | 등록 실패 뒤 미등록 발신, cause 17 | failed |
| `call-partial.log` | 등록 상태로 발신했지만 망 거절 cause 31 (CALL-001-02) | partial |
| `call-noscenario.log` | 등록만 있고 발신 없음 | unknown |
"""


def verify_logs(dest: Path) -> None:
    """이슈 DB가 아닌 입력 로그 묶음 (build()가 샘플을 복사한 뒤 비우고 이것만 남긴다)."""
    for name in [p.name for p in dest.iterdir()]:
        target = dest / name
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    for name, scenario in VERIFY_LOGS.items():
        _gen(scenario, dest / name, Path(name).stem)
    _write(dest / "README.md", VERIFY_LOGS_README)


VARIANTS = {
    "issue-db-lint-errors": lint_errors,
    "issue-db-empty-category": empty_category,
    "issue-db-pending": pending,
    "issue-db-dup-id": dup_id,
    "issue-db-verify": verify,
    "verify-logs": verify_logs,
}


def build(name: str, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SAMPLE, dest)
    VARIANTS[name](dest)
    return dest


def _diff(a: Path, b: Path) -> list[str]:
    out = []
    names = {p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()}
    names |= {p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()}
    for rel in sorted(names):
        pa, pb = a / rel, b / rel
        if not pa.is_file() or not pb.is_file() or not filecmp.cmp(pa, pb, shallow=False):
            out.append(rel)
    return out


def run(check: bool = False) -> dict:
    result = {}
    for name in VARIANTS:
        target = OUT / name
        if check:
            tmp = Path(tempfile.mkdtemp(prefix="tt-variant-check-"))
            try:
                fresh = build(name, tmp / name)
                result[name] = _diff(fresh, target) if target.is_dir() else ["(없음)"]
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        else:
            build(name, target)
            result[name] = []
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_variant_dbs.py", description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run(check=args.check)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for name, diffs in result.items():
            print(f"{name}: {'일치' if not diffs else '다름 ' + ', '.join(diffs)}" if args.check else name)
    return 1 if any(result.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
