---
id: CALL-001
category: call
secondary_categories: [ims]
title: VoLTE가 동작하지 않음
summary: VoLTE로 발신하면 연결되지 못하고 바로 종료된다
status: active
symptom_signatures:
  - id: volte-call-not-established
    must_event:
      - {id: dial, event: ims_dial_attempt}
      - {id: failed, event: call_fail_cause}
    sequence: [dial, failed]
    window_sec: 120
causes:
  - id: CALL-001-01
    status: active
    title: IMS 미등록
    description: IMS 등록이 실패한 상태에서 VoLTE 발신을 시도해 콜이 바로 종료됨
    signatures:
      - id: ims-not-registered-on-dial
        must_event:
          - {id: regfail, event: ims_registration_failed}
          - {id: dial, event: ims_dial_attempt, fields: {registered: 'false'}}
        sequence: [regfail, dial]
        window_sec: 300
    recovery_signatures:
      - id: ims-registered-call-active
        must_event:
          - {id: reg, event: ims_registered}
          - {id: dial, event: ims_dial_attempt, fields: {registered: 'true'}}
          - {id: active, event: call_state_changed, fields: {state: ACTIVE}}
        sequence: [reg, dial, active]
        window_sec: 300
    scenario_signatures:
      - id: volte-dial-attempt
        must_event:
          - {event: ims_dial_attempt}
        window_sec: 60
    resolution: 캐리어 설정의 VoLTE 항목을 켜고 IMS 등록을 다시 시도한다
    resolution_type: carrier-config
    resolution_verification:
      status: verified
      method: 캐리어 설정 반영 후 같은 시나리오에서 정상 등록·통화를 로그로 확인
      evidence: [fixtures/CALL-001-01.resolved.1.log]
      by: mock-user2
      date: 2026-09-24
    fix:
      status: fixed
      ref: MOCKCL-12345
      fixed_in:
        - {branch: MOCKB77_U2, build: MOCKB77_U2_20260920}
      verification:
        result: passed
        build: MOCKB77_U2_20260920
        date: 2026-09-26
        by: mock-user2
        fixture: fixtures/CALL-001-01.fixed.MOCKB77_U2_20260920.log
        scenario_evidence: CALL-001-01/volte-dial-attempt
        note: 재현 시나리오 3회 수행, 재발 없음
      verification_history:
        - result: partial
          build: MOCKB77_U2_20260920
          date: 2026-09-22
          by: mock-user2
          note: 원인 시그니처는 불충족이었으나 증상이 남아 있어 부분 통과로 기록
    related: [IMS-001-01]
    cp_evidence: null
    android_versions: ["17"]
    code_refs:
      - ref: aosp:frameworks/opt/telephony/src/java/com/android/internal/telephony/imsphone/ImsPhoneCallTracker.java
        symbol: ImsPhoneCallTracker#dial
tags: [volte, ims-registration]
---

## 증상

VoLTE로 발신하면 통화가 연결되지 않고 즉시 종료된다. 사용자에게는 "전화가 안 걸림"으로 보인다. CS fallback이 막힌 망에서는 통화 자체가 불가능하다.

## 증상 판별 방법

`ImsPhoneCallTracker`의 발신 시도(`dial:`) 뒤 `RILJ`의 `LAST_CALL_FAIL_CAUSE` 응답이 남는다.

```
09-18 19:43:20.000  1300  1312 D ImsPhoneCallTracker: [PHONE0] dial: isVolteEnabled=true imsRegistered=false
09-18 19:43:23.000  1300  1312 D RILJ: [PHONE0] [0078]< LAST_CALL_FAIL_CAUSE causeCode=17
```

- 발신 시도 없이 실패 코드만 있는 로그는 이 증상이 아니다(수신 실패일 수 있다).

## 원인별 상세

### CALL-001-01 IMS 미등록

- **로그 예시**:
  ```
  09-18 19:40:05.000  1300  1312 W ImsRegistration: [PHONE0] onRegistrationFailed: code=403 reason=FORBIDDEN
  09-18 19:43:20.000  1300  1312 D ImsPhoneCallTracker: [PHONE0] dial: isVolteEnabled=true imsRegistered=false
  09-18 19:43:23.000  1300  1312 D RILJ: [PHONE0] [0078]< LAST_CALL_FAIL_CAUSE causeCode=17
  ```
- **확인 방법**: 발신 시도 **앞에** IMS 등록 실패가 있고, 발신 시점의 `imsRegistered=false`다. 등록 실패 자체가 증상인 이슈는 IMS 카테고리(`IMS-001-01`)이고, 여기서는 그 결과로 통화가 실패하는 것을 다룬다. 두 원인은 `related`로 연결돼 있다.
- **재현 시나리오**: VoLTE 지원 SIM 삽입 → 캐리어 설정에서 VoLTE OFF(또는 등록 거절 망 진입) → IMS 등록 실패 확인 → VoLTE 발신
- **해결책**: 캐리어 설정의 VoLTE 항목을 켜고 IMS 등록을 다시 시도한다. 등록이 계속 실패하면 IMS-001-01 쪽을 본다.
- **코드 위치**: `ImsPhoneCallTracker#dial`이 등록 상태를 보고 발신 경로를 정한다.
- **비고**: 이 원인의 fixture(`CALL-001-01.log`)에는 IMS 등록 실패도 함께 있으므로 `IMS-001-01`이 같이 잡힌다. `.expect.yaml`의 `also_allowed`로 허용해 뒀다 (같은 로그에 실제로 두 현상이 있다).
