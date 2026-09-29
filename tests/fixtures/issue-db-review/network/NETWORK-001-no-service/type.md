---
id: NETWORK-001
category: network
secondary_categories: []
title: 서비스가 잡히지 않음
summary: 망 등록이 거절되어 서비스 상태가 되지 않는다
status: active
symptom_signatures:
  - id: registration-rejected
    must_event:
      - {event: network_registration_rejected}
    window_sec: 120
causes:
  - id: NETWORK-001-01
    status: active
    title: 망 등록 거절
    description: 망이 등록 요청을 거절해(가입자 확인 실패 등) 서비스 상태로 가지 못함
    signatures:
      - id: reject-cause-subscriber
        must_event:
          - {event: network_registration_rejected, fields: {cause: '(11|13|15)'}}
        window_sec: 120
    recovery_signatures: []
    scenario_signatures: []
    resolution: 거절 코드를 확인하고 가입 상태를 사업자에 문의한다. 단말 설정으로 해결되지 않으면 망 쪽 처리가 필요하다
    resolution_type: network
    resolution_verification: {status: unverified}
    fix:
      status: open
      ref: null
      fixed_in: []
      verification: null
      verification_history: []
    related: []
    cp_evidence: 거절 코드 자체는 CP에서 올라온다. DM 로그의 NAS 구간(등록 요청~거절 응답)을 함께 받아 거절 원인 값을 확인한다. CP 티켓은 TODO(SITE) — 사내에서 실제 티켓 번호를 연결한다.
    android_versions: []
    code_refs: []
tags: [registration]
---

## 증상

단말이 망에 등록되지 못해 "서비스 없음"으로 남는다. 데이터도 통화도 되지 않는다.

## 증상 판별 방법

`SST`(ServiceStateTracker)에 등록 거절 로그가 남는다.

```
09-24 10:11:02.000  1234  1244 W SST-0: [PHONE0] registration rejected: cause=13 domain=PS
```

- 거절 없이 검색만 반복하는 경우(커버리지 문제)는 이 유형이 아니다.

## 원인별 상세

### NETWORK-001-01 망 등록 거절

- **로그 예시**:
  ```
  09-24 10:11:00.000  1234  1244 I SST-0: [PHONE0] onServiceStateChanged: regState=NOT_REGISTERED
  09-24 10:11:02.000  1234  1244 W SST-0: [PHONE0] registration rejected: cause=13 domain=PS
  09-24 10:11:12.000  1234  1244 W SST-0: [PHONE0] registration rejected: cause=13 domain=PS
  ```
- **확인 방법**: 거절 코드가 가입자 관련 값(11/13/15)인지 본다. 다른 코드는 원인이 다르므로 새 원인을 검토한다.
- **재현 시나리오**: 해당 망에서 단말 재부팅 또는 비행기 모드 OFF → 등록 시도 → 거절 로그 확인
- **해결책**: 거절 코드를 확인하고 가입 상태를 사업자에 문의한다.
- **코드 위치**: 없음. AP 쪽은 상태 전이만 기록하고 판단 근거는 CP 로그다(`cp_evidence`). 사내에서 ServiceStateTracker 경로를 확인하면 추가한다 — TODO(SITE:S11).
- **비고**: `resolution_type: network`이므로 단말 코드 수정 대상이 아니다. 수정 상태는 `open`으로 두고 재발 추이를 본다.
