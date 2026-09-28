---
id: SIM-001
category: sim
secondary_categories: []
title: SIM이 인식되지 않음
summary: SIM 카드가 꽂혀 있는데 단말이 SIM 없음 상태로 남는다
status: active
symptom_signatures:
  - id: sim-absent
    must_event:
      - {event: sim_state_changed, fields: {state: 'ABSENT|UNKNOWN'}}
    window_sec: 120
causes:
  - id: SIM-001-01
    status: active
    title: UICC 초기화 실패
    description: 카드 상태 조회가 CARD_IO_ERROR로 끝나 SIM이 ABSENT로 처리됨
    signatures:
      - id: card-io-error-then-absent
        must_event:
          - {id: ioerr, event: uicc_card_status_error, fields: {error: CARD_IO_ERROR}}
          - {id: absent, event: sim_state_changed, fields: {state: ABSENT}}
        sequence: [ioerr, absent]
        window_sec: 120
    recovery_signatures: []
    scenario_signatures:
      - id: sim-status-query
        must_match: ['RILJ.*>\s*GET_SIM_STATUS']
        window_sec: 120
    resolution: SIM을 다시 꽂고 재부팅한 뒤에도 재현되면 수정 CL이 반영된 빌드로 확인한다
    resolution_type: vendor-ril
    resolution_verification: {status: unverified}
    fix:
      status: fix-submitted
      ref: MOCKCL-23456
      fixed_in:
        - {branch: MOCKB77_U2, build: MOCKB77_U2_20260920}
      verification: null
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: ["17"]
    code_refs:
      - ref: vendor_ril:vendor/mockril/libril/mock_ril.c
        symbol: mock_ril_get_sim_status
tags: [uicc]
---

## 증상

SIM 카드가 꽂혀 있는데 단말이 "SIM 없음"으로 표시하고 가입자 정보를 읽지 못한다.

## 증상 판별 방법

`UiccController`의 SIM 상태가 `ABSENT`(또는 `UNKNOWN`)로 바뀐다.

```
09-25 16:20:03.000  1400  1410 W UiccController: [PHONE1] SIM state changed: ABSENT
```

## 원인별 상세

### SIM-001-01 UICC 초기화 실패

- **로그 예시**:
  ```
  09-25 16:20:00.000  1400  1410 D RILJ: [PHONE1] [0011]> GET_SIM_STATUS
  09-25 16:20:01.000  1400  1410 W UiccController: [PHONE1] onIccCardStatusDone: error=CARD_IO_ERROR
  09-25 16:20:03.000  1400  1410 W UiccController: [PHONE1] SIM state changed: ABSENT
  ```
- **확인 방법**: 카드 상태 조회가 `CARD_IO_ERROR`로 끝나고 **그 뒤에** SIM 상태가 `ABSENT`가 된다. 카드를 실제로 뽑은 경우에는 `CARD_IO_ERROR` 없이 바로 `ABSENT`가 되므로 구분된다.
- **재현 시나리오**: SIM 삽입 상태에서 재부팅 → 부팅 직후 `GET_SIM_STATUS` 응답 확인 → SIM 상태 로그 확인
- **해결책**: SIM을 다시 꽂고 재부팅한 뒤에도 재현되면 수정 CL이 반영된 빌드로 확인한다.
- **코드 위치**: vendor RIL의 카드 상태 조회 경로 (`mock_ril_get_sim_status`). 사내 경로는 다르다 — TODO(SITE:S11).
- **비고**: 수정 CL이 머지되어 `fix-submitted` 상태다. 수정 빌드(`MOCKB77_U2_20260920`) 로그로 `verify-fix`를 돌려야 `fixed`가 된다. 재현 시나리오 흔적(`sim-status-query`)이 있으므로 판정이 가능하다.
