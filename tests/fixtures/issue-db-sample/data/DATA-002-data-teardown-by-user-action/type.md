---
id: DATA-002
category: data
secondary_categories: []
title: 데이터 연결이 사용자 조작으로 끊김
summary: 연결돼 있던 인터넷 데이터가 사용자 조작(비행기 모드 등)으로 해제되어 데이터가 안 된다
status: active
symptom_signatures:
  - id: internet-disconnected
    must_event:
      - {event: data_internet_state_changed, fields: {from: CONNECTED, to: DISCONNECTED}}
    must_not_match: ['notifyDataEnabledChanged: enabled=false']
    window_sec: 60
causes:
  - id: DATA-002-01
    status: active
    title: Airplane mode on
    description: 비행기 모드가 켜져 모든 데이터 네트워크가 해제되고 라디오가 꺼짐
    signatures:
      - id: airplane-mode-teardown
        must_event:
          - {id: apm, event: data_teardown_all, fields: {reason: AIRPLANE_MODE_ON}}
          - {id: down, event: data_internet_state_changed, fields: {to: DISCONNECTED}}
        sequence: [apm, down]
        same_phone: true
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 비행기 모드를 끈다
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
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/data/DataNetworkController.java
        symbol: DataNetworkController#onTearDownAllDataNetworks
tags: [data-teardown]
---

## 증상

연결돼 있던 인터넷 데이터가 갑자기 끊긴다. 사용자에게는 "방금까지 되던 인터넷이 안 됨"으로 보인다. 단말 오동작이 아니라 **사용자 조작이 만든 정상 동작**인 경우를 가려내는 유형이다.

이 유형은 **연결이 해제되는** 경우다. 처음부터 연결 요청이 나가지 않는 경우는 `DATA-001`이다.

## 증상 판별 방법

`DNC-<slot>`(DataNetworkController)에 `Internet data state changed from CONNECTED to DISCONNECTED.`가 남는다.

```
09-26 09:40:00.720  1290  1301 I DNC-0: Internet data state changed from CONNECTED to DISCONNECTED.
```

- 해제의 원인(사용자 조작인지, 망·단말 쪽인지)은 원인 시그니처로 가린다. 원인 시그니처가 하나도 안 맞으면 "원인 미확인"이다.
- 사용자 데이터 설정 OFF(`notifyDataEnabledChanged: enabled=false`)가 같은 구간에 있으면 이 증상이 아니다(증상 시그니처의 `must_not_match`). 그 경우는 `DATA-001-01`의 표본(`DATA-001-01.extra.1`)이다.
- 비행기 모드 중에는 데이터 평가도 불허되므로 `DATA-001` 증상도 함께 맞는다(S=1). 원인은 `DATA-002-01`만 C=1이라 판정은 갈리고, 월간 리뷰의 `DATA-001↔DATA-002` 중복 후보(fixture 1개)는 의도된 겹침이다(사용자 결정 10/07).

## 원인별 상세

### DATA-002-01 Airplane mode on

- **로그 예시**:
  ```
  09-26 09:40:00.000  1290  1301 D AirplaneModeStats: Airplane mode change. Value: true
  09-26 09:40:00.010  1290  1301 D SST-0: powerOffRadioSafely: start
  09-26 09:40:00.020  1290  1301 I DNC-0: onTearDownAllDataNetworks: reason=AIRPLANE_MODE_ON
  09-26 09:40:00.730  1290  1301 I DNC-0: Internet data state changed from CONNECTED to DISCONNECTED.
  09-26 09:40:00.740  1290  1301 D RILJ: [0061]> RADIO_POWER on = false [PHONE0]
  ```
- **확인 방법**: `DNC-<slot>`에 `onTearDownAllDataNetworks: reason=AIRPLANE_MODE_ON`이 있고, **그 뒤에** 같은 슬롯의 Internet 상태가 `DISCONNECTED`로 바뀐다. 순서(`sequence`)와 슬롯(`same_phone`)을 함께 본다. 데이터를 먼저 내리고 라디오를 끄므로 `RILJ`의 `RADIO_POWER on = false`는 그 **뒤**에 나온다. 이 구간의 평가 불허 사유에는 `DATA_DISABLED`가 없다(있으면 `DATA-001-01`).
- **재현 시나리오**: 데이터 연결 상태에서 비행기 모드 ON → 로그 확인 → 비행기 모드 OFF 후 재연결 확인
- **해결책**: 비행기 모드를 끈다. (단말 수정 대상이 아니다.)
- **코드 위치**: `DataNetworkController#onTearDownAllDataNetworks`
- **비고**: 유형 이름·원인 정의는 사용자 승인(10/07). 문구는 AOSP 공개 소스 형식이고 순서는 사외 실제 단말 로그로 확인했다(10/07). 망 쪽 사유로 Internet이 DISCONNECTED가 되는 음성 사례는 아직 못 봤다. 해결책은 **미검증**이다. Android 13+ 데이터 스택(AOSP 13~17 동일 형식, Android 17 단말 로그로 형식 확인). 12 이하는 범위 밖 — 사내 S-4에서 단말 버전 확인.
