---
id: DATA-001
category: data
secondary_categories: []
title: SETUP_DATA_CALL이 발생하지 않음
summary: 데이터 연결이 필요한 상황인데 RIL로 SETUP_DATA_CALL 요청이 나가지 않는다
status: active
symptom_signatures:
  - id: no-setup-data-call-request
    must_event:
      - {event: data_evaluation_rejected}
    must_not_match: ['RILJ.*>\s*SETUP_DATA_CALL']
    window_sec: 60
causes:
  - id: DATA-001-01
    status: active
    title: Data disabled
    description: 사용자 모바일 데이터 설정이 꺼져 있어 데이터 평가가 거부됨
    signatures:
      - id: data-disabled
        must_event:
          - {id: setting-off, event: data_setting_changed, fields: {enabled: 'false'}}
          - {id: rejected, event: data_evaluation_rejected, fields: {reasons: '.*DATA_DISABLED.*'}}
        sequence: [setting-off, rejected]
        same_phone: true
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 모바일 데이터 설정을 켠다
    resolution_type: user-setting
    resolution_verification:
      status: verified
      method: 설정을 켠 뒤 같은 단말에서 재현되지 않음을 확인
      evidence: [MOCK-1102]
      by: mock-user1
      date: 2026-09-12
    fix:
      status: not-a-bug
      ref: null
      fixed_in: []
      verification: null
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: ["16", "17"]
    code_refs:
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataNetworkController.java
        symbol: DataNetworkController#onEvaluateNetworkRequests
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataSettingsManager.java
        symbol: DataSettingsManager#isDataEnabled
      - ref: aosp:frameworks/base/telephony/java/android/telephony/DataFailCause.java
        symbol: DataFailCause#toString
        android_versions: ["16"]
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/fail/DataFailCause.java
        symbol: DataFailCause#toString
        android_versions: ["17"]
  - id: DATA-001-02
    status: active
    title: Roaming disabled
    description: 로밍 중인데 데이터 로밍 설정이 꺼져 있음
    signatures:
      - id: roaming-disabled
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*ROAMING_DISABLED.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 데이터 로밍 설정을 켠다
    resolution_type: user-setting
    resolution_verification: {status: unverified}
    fix:
      status: not-a-bug
      ref: null
      fixed_in: []
      verification: null
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: []
    code_refs:
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataSettingsManager.java
        symbol: DataSettingsManager#isDataRoamingEnabled
  - id: DATA-001-03
    status: active
    title: SIM 미준비
    description: SIM 초기화 전에 평가가 거부됨
    signatures:
      - id: sim-not-ready
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*SIM_NOT_READY.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: SIM 로딩 뒤 데이터 평가를 다시 요청하도록 고친다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
  - id: DATA-001-03
    status: active
    title: 무선 꺼짐
    description: 무선이 꺼진 상태에서 평가가 거부됨
    signatures:
      - id: radio-off
        must_event:
          - {event: data_evaluation_rejected, fields: {reasons: '.*RADIO_POWER_OFF.*'}}
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 무선 전원 상태 복구 뒤 평가를 다시 요청하도록 고친다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix: {status: open, ref: null, fixed_in: [], verification: null, verification_history: []}
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: [data-evaluation]
---

## 증상

데이터가 필요한 상황(앱의 네트워크 요청, 데이터 설정 변경, 로밍 진입 등)인데도 RIL로 `SETUP_DATA_CALL` 요청이 나가지 않는다. 사용자에게는 "LTE/5G 표시는 있는데 인터넷이 안 됨"으로 보인다.

이 유형은 **요청 자체가 나가지 않는** 경우다. 요청은 나갔는데 에러 응답을 받는 경우는 다른 유형이다.

## 증상 판별 방법

`DNC-<slot>`(DataNetworkController)의 평가 결과가 `NOT_ALLOWED`로 남고, 같은 구간에 `RILJ`의 `SETUP_DATA_CALL` 요청이 없다.

```
09-20 14:30:04.500  1234  1244 W DNC-0: [PHONE0] evaluation result: NOT_ALLOWED reasons=[DATA_DISABLED]
09-20 14:30:12.500  1234  1244 D DRM-0: [PHONE0] no retry scheduled: setup not allowed
```

- 거부 사유(`reasons=[...]`)가 어느 원인인지 정한다.
- 듀얼 SIM에서는 **슬롯(`phone_id`)별로** 본다. 한 슬롯이 정상 연결돼 있어도 다른 슬롯이 거부될 수 있다.

## 원인별 상세

### DATA-001-01 Data disabled

- **로그 예시**:
  ```
  09-20 14:30:03.000  1234  1244 D DSM-0: [PHONE0] onDataEnabledChanged: enabled=false reason=USER
  09-20 14:30:03.400  1234  1244 D DSM-0: [PHONE0] isDataEnabled=false (user setting off)
  09-20 14:30:04.600  1234  1244 I DNC-0: [PHONE0] onEvaluateNetworkRequests: reason=DATA_ENABLED_CHANGED
  09-20 14:30:04.900  1234  1244 W DNC-0: [PHONE0] evaluation result: NOT_ALLOWED reasons=[DATA_DISABLED]
  ```
- **확인 방법**: `DSM-<slot>`에 `onDataEnabledChanged: enabled=false`가 있고, **그 뒤에** 같은 슬롯의 `DNC-<slot>` 평가가 `DATA_DISABLED`로 거부된다. 순서(`sequence`)와 슬롯(`same_phone`)을 함께 본다. "먼저 setup이 실패하고 나중에 사용자가 데이터를 끈" 경우와 구분하기 위해서다.
- **재현 시나리오**: 설정 > 네트워크 > 모바일 데이터 OFF → 데이터를 쓰는 앱 실행 → 평가 로그 확인
- **해결책**: 모바일 데이터 설정을 켠다. (단말 수정 대상이 아니다.)
- **코드 위치**: 설정 값은 `DataSettingsManager#isDataEnabled`, 평가는 `DataNetworkController#onEvaluateNetworkRequests`. 실패 코드 상수는 Android 16과 17의 경로가 다르다(`code_refs`의 `android_versions` 참고).
- **비고**: 로그 문구는 사외 초안의 placeholder다 — TODO(SITE:S9).

### DATA-001-02 Roaming disabled

- **로그 예시**:
  ```
  09-22 08:00:02.000  1234  1250 D DSM-1: [PHONE1] isDataRoamingEnabled=false
  09-22 08:00:03.000  1234  1250 I DNC-1: [PHONE1] onEvaluateNetworkRequests: reason=ROAMING_STATE_CHANGED
  09-22 08:00:03.500  1234  1250 W DNC-1: [PHONE1] evaluation result: NOT_ALLOWED reasons=[ROAMING_DISABLED]
  ```
- **확인 방법**: 로밍 상태(`SST-<slot>`의 `onRoamingOn`)에서 평가가 `ROAMING_DISABLED`로 거부된다. 데이터 설정 자체는 켜져 있다.
- **재현 시나리오**: 로밍 SIM 삽입(또는 로밍 망 진입) → 데이터 로밍 OFF 확인 → 데이터를 쓰는 앱 실행
- **해결책**: 데이터 로밍 설정을 켠다.
- **코드 위치**: `DataSettingsManager#isDataRoamingEnabled`
- **비고**: 해결책이 아직 **미검증**이다(설정을 켠 뒤 재현되지 않음을 확인한 근거가 없다). 근거가 생기면 `verify-resolution`으로 올린다.
