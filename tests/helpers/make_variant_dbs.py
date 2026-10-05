#!/usr/bin/env python3
"""변형 이슈 DB를 합성 샘플에서 만든다 (11-phases.md Phase 5·§11.0).

샘플 트리(`tests/fixtures/issue-db-sample/`)를 복사한 뒤 정해진 변경을 결정적으로 적용한다.
샘플 트리는 건드리지 않는다. 결과는 커밋하지 않는다 — 테스트가 `runner.variant_db()`로 프로세스당 한 번
임시 디렉터리에 만든다. 눈으로 확인하려면 `--out DIR`로 만든다.

| 변형 | 용도 |
|---|---|
| `issue-db-lint-errors/` | 린터가 잡아야 할 오류를 일부러 넣은 트리 (`tests/test_db_lint.py`의 `EXPECTED`) |
| `issue-db-empty-category/` | sms·ims 유형을 뺀 트리. README의 0건 카테고리 표시 |
| `issue-db-pending/` | `signatures_pending` 원인(DATA-001-03)과 그 양성 fixture. 회귀 기대값 `DATA-001:unresolved` |
| `issue-db-dup-id/` | 머지 간격으로 main에 같은 ID(DATA-001-03 두 번)와 같은 Jira(MOCK-1101 두 곳)가 들어온 트리. 사후 lint 보고 (Phase 7) |
| `issue-db-verify/` | 검증(Phase 10): CALL-001-01을 `fix-submitted`로 되돌리고(수정 후 fixture 제거) 같은 증상의 다른 원인 CALL-001-02(망 거절, scenario만 있음)와 그 양성 fixture를 넣은 트리 |
| `issue-db-step-focus/` | 스텝 기준 우선 유형(순위 참고): `step_focus.map`(`데이터` → DATA-001)과 DATA-001의 같은 스텝(`5 | 데이터 켜기`) Jira 기록 2건 |
| `issue-db-step-events/` | 스텝 순서 정렬: `step_events` 규칙 10개(CP는 관측 불가, 비행기 모드 켜기·끄기는 `match`, 망 등록은 `ril`, 데이터 켜기·끄기는 `event`) |
| `issue-db-review/` | 월간 리뷰(Phase 11): §6.6 항목마다 걸리는 경우와 걸리지 않는 경우 (`REVIEW_CASES`) |
| `verify-logs/` | 이슈 DB가 아니다. `db_verify fix`·`resolution` 입력 로그(수정 후·재발·증상만 남음·시나리오 없음, 마스킹됨) |

CLI:
    python3 tests/helpers/make_variant_dbs.py --out DIR [--json]   # DIR 아래에 변형 전부를 만든다
    python3 tests/helpers/make_variant_dbs.py --check [--json]     # 두 번 만들어 결과가 같은지 확인 (결정성)
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
대상은 `issue-db-verify` 변형의 CALL-001-01(fix-submitted, fixed_in MOCKB77_U2_20260920)이다.

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


DATA_002 = """---
id: DATA-002
category: data
secondary_categories: []
title: SETUP_DATA_CALL 요청이 나가지 않음
summary: DATA-001과 같은 현상을 따로 등록한 유형 (리뷰 시험용 중복 후보)
status: active
symptom_signatures:
  - id: evaluation-rejected
    must_event:
      - {event: data_evaluation_rejected}
    window_sec: 60
causes:
  - id: DATA-002-01
    status: active
    title: 레거시 조건에서 평가 불허
    description: 예전 버전에서만 나던 평가 거부
    signatures:
      - id: legacy-only
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*LEGACY_ONLY.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures:
      - id: evaluation
        must_event:
          - {event: data_evaluation_rejected}
        window_sec: 60
    resolution: 평가 조건을 고친다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix:
      status: fix-submitted
      ref: MOCKCL-11111
      fixed_in:
        - {branch: MOCKA56_U1}
      verification: null
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: ["14", "15"]
    code_refs: []
  - id: DATA-002-02
    status: active
    title: 평가 재요청 누락
    description: RIL 복구 뒤 평가를 다시 요청하지 않음
    signatures:
      - id: retry-missing
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*RETRY_MISSING.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: RIL 복구 뒤 평가를 다시 요청하도록 고친다
    resolution_type: vendor-ril
    resolution_verification: {status: unverified}
    fix:
      status: fix-submitted
      ref: null
      fixed_in: []
      verification: null
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: [data-evaluation]
---

## 증상

리뷰 시험용 유형. DATA-001과 증상이 겹친다.

## 증상 판별 방법

`DNC-<slot>` 평가 거부.

## 원인별 상세

### DATA-002-01 레거시 조건에서 평가 불허

- 리뷰 시험용.

### DATA-002-02 평가 재요청 누락

- 리뷰 시험용.
"""

DATA_001_03_PENDING = """  - id: DATA-001-03
    status: active
    title: SIM 준비 안 됨 (미확정)
    description: 수동 기록으로 추가한 원인. 판별 시그니처는 아직 없다
    signatures: []
    signatures_pending: true
    recovery_signatures: []
    scenario_signatures: []
    resolution: SIM 상태를 확인한다
    resolution_type: user-setting
    resolution_verification: {status: unverified, method: "근거: 사용자 진술"}
    fix: {status: not-a-bug, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
"""

# (키, 유형 디렉토리, 원인, date, occurred_on, note)
REVIEW_JIRA = [
    ("MOCK-1105", "data/DATA-001-no-setup-data-call", "unresolved", "2026-08-01", "2026-07-31", "오래 방치된 원인 미확정"),
    ("MOCK-1201", "data/DATA-002-legacy-evaluation", "DATA-002-01", "2025-06-02", "2025-06-01", "옛 버전에서 접수"),
    ("MOCK-3102", "network/NETWORK-001-no-service", "NETWORK-001-01", "2026-10-06", "2026-10-05", "급증 시험"),
    ("MOCK-3103", "network/NETWORK-001-no-service", "NETWORK-001-01", "2026-10-12", "2026-10-12", "급증 시험"),
    ("MOCK-3104", "network/NETWORK-001-no-service", "NETWORK-001-01", "2026-07-02", "2026-07-01", "급증 시험(이전 구간)"),
    # 과거 이슈를 한꺼번에 record: 기록일은 최근이지만 발생일이 오래됐다 → 급증 아님
    ("MOCK-5102", "sms/SMS-001-sms-send-failed", "SMS-001-01", "2026-10-18", "2025-03-03", "과거 이슈 일괄 기록"),
    ("MOCK-5103", "sms/SMS-001-sms-send-failed", "SMS-001-01", "2026-10-18", "2025-03-10", "과거 이슈 일괄 기록"),
    ("MOCK-5104", "sms/SMS-001-sms-send-failed", "SMS-001-01", "2026-10-18", "2025-04-02", "과거 이슈 일괄 기록"),
]

# (Jira, 날짜, 1위 시그니처, decision, final)
REVIEW_FEEDBACK = [
    ("MOCK-1111", "2026-10-01T10:00+09:00", "DATA-001-01/data-disabled", "accepted", "DATA-001-01"),
    ("MOCK-1112", "2026-10-02T10:00+09:00", "DATA-001-01/data-disabled", "accepted", "DATA-001-01"),
    ("MOCK-1113", "2026-10-03T10:00+09:00", "DATA-001-01/data-disabled", "chose-other", "DATA-001-02"),
    ("MOCK-1114", "2026-10-04T10:00+09:00", "DATA-001-01/data-disabled", "chose-other", "DATA-001-02"),
    ("MOCK-1115", "2026-10-05T10:00+09:00", "DATA-001-01/data-disabled", "chose-other", "DATA-001-02"),
    # 표본 부족(1위 3건): 수락률이 낮아도 리포트에 넣지 않는다
    ("MOCK-1116", "2026-10-06T10:00+09:00", "DATA-001-02/roaming-disabled", "chose-other", "DATA-001-01"),
    ("MOCK-1117", "2026-10-07T10:00+09:00", "DATA-001-02/roaming-disabled", "chose-other", "DATA-001-01"),
]

# 수동 기록 피드백: suggested가 비어 수락률에 들어가지 않는다
REVIEW_MANUAL = [("MOCK-1118", "2026-10-08T10:00+09:00", "DATA-001-01"),
                 ("MOCK-1119", "2026-10-09T10:00+09:00", "DATA-001-01"),
                 ("MOCK-1120", "2026-10-10T10:00+09:00", "DATA-001-01")]

REVIEW_CASES = """# 리뷰 변형 (Phase 11)

`tests/helpers/make_variant_dbs.py`가 만든다. 기준일 `--as-of 2026-10-20`, 시험은 `tests/test_db_review.py`.

- 오래된 unresolved: MOCK-1105(2026-08-01 기록) 걸림, MOCK-1104(2026-09-26) 안 걸림
- 낮은 수락률: DATA-001-01/data-disabled 2/6 걸림, DATA-001-02/roaming-disabled 1/3은 표본 부족
- 수동 기록 피드백 3건(MOCK-1118~1120)은 수락률에서 빠짐
- 중복 후보: DATA-001 ↔ DATA-002 (동시 매칭 + 제목 유사도)
- 지원 종료: DATA-002-01 ["14","15"] 걸림, DATA-001-02 [] 안 걸림
- fixed 전환 불가: DATA-002-02(vendor-ril), IMS-001-01, SMS-001-01
- 시그니처 없는 원인: DATA-001-03 / fixture 없는 원인: DATA-002-01, DATA-002-02 (pending은 제외)
- 사용자 진술만: DATA-001-03(method), DATA-001-02(MOCK-1103 note)
- 수정 상태 누락: DATA-002-02 / 빌드 없는 fix-submitted: DATA-002-01
- also_allowed 누적: NETWORK-001-01 fixture 3개, IMS-001-01이 다른 유형 fixture 5개에서 허용
- 급증: NETWORK-001-01 걸림, SMS-001-01(과거 occurred_on 일괄 기록) 안 걸림
- 오래 안 쓰인 원인: DATA-002-01(마지막 발생 2025-06-01)
- 방치 기간(해결책 미검증, 수정 검증 대기)은 git 이력이 필요해서 테스트가 날짜를 지정한 커밋으로 만든다
"""


def review(db: Path) -> None:
    """월간 리뷰(Phase 11) 완료 기준 케이스. 목록은 `REVIEW_CASES`."""
    data = db / "data/DATA-001-no-setup-data-call"
    _edit(data / "type.md", "tags: [data-evaluation]\n---", DATA_001_03_PENDING + "tags: [data-evaluation]\n---")
    _write(db / "data/DATA-002-legacy-evaluation/type.md", DATA_002)
    _edit(data / "jira/MOCK-1103.yaml", "note: 로밍 SIM 테스트 중 발생, 슬롯 1",
          "note: '로밍 SIM 테스트 중 발생, 슬롯 1. 로밍을 켜니 됐다고 함(근거: 사용자 진술)'")
    for key, rel, cause, when, occurred, note in REVIEW_JIRA:
        sw, ver = ("MOCKA56_U1_20260901", "15") if "DATA-002" in rel else ("MOCKA56_U1_20260920", "16")
        _write(db / rel / "jira" / f"{key}.yaml",
               f"key: {key}\ncause: {cause}\ndate: {when}\noccurred_on: {occurred}\nmodel: MOCK-A56\nsw: {sw}\n"
               f"android_version: \"{ver}\"\ncarrier: MockTel KR\nanalyzed_by: mock-user1\nnote: {note}\n")
    for key, when, sig, decision, final in REVIEW_FEEDBACK:
        stamp = when[:16].replace("-", "").replace(":", "")
        _write(db / "feedback" / when[:7] / f"{key}-{stamp}.yaml",
               f"jira: {key}\ndate: {when}\nby: mock-user1\nsuggested:\n"
               f"  - {{cause: {sig.split('/', 1)[0]}, signature: {sig}, score: 0.8}}\ndecision: {decision}\n"
               f"final: {final}\n")
    for key, when, final in REVIEW_MANUAL:
        stamp = when[:16].replace("-", "").replace(":", "")
        _write(db / "feedback" / when[:7] / f"{key}-{stamp}.yaml",
               f"jira: {key}\ndate: {when}\nby: mock-user2\nsuggested: []\ndecision: manual\nfinal: {final}\n")
    _edit(db / "network/NETWORK-001-no-service/fixtures/NETWORK-001-01.expect.yaml", "origin: synthetic",
          "also_allowed:\n- CALL-001-01\n- SIM-001-01\n- IMS-001-01\norigin: synthetic")
    for rel in ("data/DATA-001-no-setup-data-call/fixtures/DATA-001-01.expect.yaml",
                "sim/SIM-001-sim-not-detected/fixtures/SIM-001-01.expect.yaml",
                "sms/SMS-001-sms-send-failed/fixtures/SMS-001-01.expect.yaml"):
        _edit(db / rel, "origin: synthetic", "also_allowed:\n- IMS-001-01\norigin: synthetic")


def step_focus(db: Path) -> None:
    """`step_focus.map`(`데이터` → DATA-001)과 DATA-001에 같은 실패 스텝("5 | 데이터 켜기") 기록 2건. 우선 유형 시험용."""
    _edit(db / "issue-db.config.yaml", "  map: []",
          "  map:\n    - {pattern: '데이터', types: [DATA-001], categories: []}")
    for key in ("MOCK-1131", "MOCK-1132"):
        _write(db / "data/DATA-001-no-setup-data-call/jira" / f"{key}.yaml",
               f"key: {key}\ncause: DATA-001-01\ndate: 2026-09-25\noccurred_on: 2026-09-24\nmodel: MOCK-A56\n"
               "sw: MOCKA56_U1_20260915\nandroid_version: \"16\"\ncarrier: MockTel KR\nanalyzed_by: mock-user1\n"
               "failed_step: 5 | 데이터 켜기\nnote: 스텝 우선 유형 시험\n")


STEP_EVENTS = """step_events:
  - {pattern: '(?i)(CP|모뎀|AT\\s*cmd)', observable: false}
  - {pattern: '(?i)(비행기|airplane).*(켜|\\bon\\b)', match: '^ConnectivityService: setAirplaneMode enabled=true'}
  - {pattern: '(?i)(비행기|airplane).*(끄|\\boff\\b)', match: '^ConnectivityService: setAirplaneMode enabled=false'}
  - {pattern: '(?i)(망|network)\\s*등록', ril: UNSOL_RESPONSE_NETWORK_STATE_CHANGED}
  - {pattern: '(?i)데이터.*켜', event: data_setting_changed, fields: {enabled: '^true$'}}
  - {pattern: '(?i)데이터.*끄', event: data_setting_changed, fields: {enabled: '^false$'}}
  - {pattern: '(?i)데이터\\s*연결', ril: SETUP_DATA_CALL}
  - {pattern: '(?i)(발신|dial)', ril: DIAL}
  - {pattern: '(?i)재부팅|reboot', match: '^(?:Zygote|AndroidRuntime): '}
  - {pattern: '(?i)SIM', event: sim_state_changed}"""


def step_events(db: Path) -> None:
    """`step_events` 규칙을 채운다(placeholder 예시 그대로). 스텝 순서 정렬 시험용."""
    _sub(db / "issue-db.config.yaml", r"step_events: \[\][^\n]*", STEP_EVENTS.replace("\\", "\\\\"))


VARIANTS = {
    "issue-db-lint-errors": lint_errors,
    "issue-db-empty-category": empty_category,
    "issue-db-pending": pending,
    "issue-db-dup-id": dup_id,
    "issue-db-verify": verify,
    "issue-db-review": review,
    "issue-db-step-focus": step_focus,
    "issue-db-step-events": step_events,
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


def build_all(out: Path) -> Path:
    """VARIANTS 전부를 `out/<name>`에 만든다."""
    out.mkdir(parents=True, exist_ok=True)
    for name in VARIANTS:
        build(name, out / name)
    return out


def check() -> dict[str, list[str]]:
    """전부를 임시 디렉터리 둘에 만들어 이름별로 다른 파일을 돌려준다 (결정성 증명)."""
    a = Path(tempfile.mkdtemp(prefix="tt-variant-check-a-"))
    b = Path(tempfile.mkdtemp(prefix="tt-variant-check-b-"))
    try:
        build_all(a)
        build_all(b)
        return {name: _diff(a / name, b / name) for name in VARIANTS}
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_variant_dbs.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", metavar="DIR", help="DIR 아래에 변형 전부를 만든다 (확인용)")
    parser.add_argument("--check", action="store_true", help="두 번 만들어 결과가 같은지 확인한다")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if not args.out and not args.check:
        parser.error("--out DIR 또는 --check가 필요합니다")
    result: dict[str, list[str]] = {}
    if args.out:
        out = build_all(Path(args.out))
        result = {name: [] for name in VARIANTS}
        if not args.json:
            print(f"{len(VARIANTS)}개를 {out}에 만들었습니다")
    if args.check:
        result = check()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.check:
        for name, diffs in result.items():
            print(f"{name}: {'일치' if not diffs else '다름 ' + ', '.join(diffs)}")
    return 1 if args.check and any(result.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
