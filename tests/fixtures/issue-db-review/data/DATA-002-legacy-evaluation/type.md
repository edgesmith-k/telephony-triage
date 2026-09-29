---
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
