---
id: NET-002
category: network
secondary_categories: []
title: 접두어가 틀린 유형
summary: 린터 시험용 유형
status: active
symptom_signatures: 
  - id: probe
    must_event:
      - {event: network_service_state}
    window_sec: 60
causes:
  - id: NET-002-01
    status: active
    title: 시험 원인
    description: 린터 시험용 원인
    signatures:
      - id: probe
        must_event:
          - {event: network_service_state}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 시험용이다
    resolution_type: network
    resolution_verification: {status: unverified}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: []
---

## 증상

린터 시험용.
