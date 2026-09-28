---
id: SMS-001
category: sms
secondary_categories: []
title: SMS가 전송되지 않음
summary: SMS 발신이 실패로 끝나고 재시도해도 같은 결과가 된다
status: active
symptom_signatures:
  - id: sms-send-failure
    must_event:
      - {event: sms_send_failed}
    window_sec: 60
causes:
  - id: SMS-001-01
    status: active
    title: SMSC 주소 없음
    description: SMSC 주소가 비어 있어 전송 요청이 만들어지지 못함
    signatures: []
    recovery_signatures: []
    scenario_signatures: []
    resolution: SMSC 주소를 캐리어 설정 값으로 다시 넣고 전송을 재시도한다
    resolution_type: carrier-config
    resolution_verification: {status: unverified}
    fix:
      status: wont-fix
      ref: null
      fixed_in: []
      verification: null
      verification_history: []
    related: []
    cp_evidence: null
    android_versions: []
    code_refs: []
tags: [smsc]
---

## 증상

SMS를 보내면 전송 실패로 끝난다. 재시도해도 같은 결과가 된다.

## 증상 판별 방법

`SmsDispatchersController`에 전송 실패 결과가 남는다.

```
09-26 13:00:05.000  1500  1510 W SmsDispatchersController: [PHONE0] sendSms failed: result=GENERIC_FAILURE
```

## 원인별 상세

### SMS-001-01 SMSC 주소 없음

- **로그 예시**:
  ```
  09-26 13:00:04.000  1500  1510 W SmsDispatchersController: [PHONE0] getSmscAddress: null
  09-26 13:00:05.000  1500  1510 W SmsDispatchersController: [PHONE0] sendSms failed: result=GENERIC_FAILURE
  ```
- **확인 방법**: 전송 실패 **직전에** SMSC 주소 조회가 비어 있다. SMSC가 정상인데 실패하는 경우는 원인이 다르므로 새 원인을 검토한다.
- **재현 시나리오**: SMSC 주소를 지운 SIM 프로필로 부팅 → 문자 발신 → 조회·실패 로그 확인
- **해결책**: SMSC 주소를 캐리어 설정 값으로 다시 넣고 전송을 재시도한다.
- **코드 위치**: 없음. 사내 SmsDispatchersController 경로를 확인하면 추가한다 — TODO(SITE:S11).
- **비고**: 단말 수정 대상이 아니라고 판단해 `wont-fix`로 뒀다. **사유**: SMSC 값은 캐리어 설정/SIM 프로필에서 오고, 값이 비어 있을 때 단말이 임의 값을 채우면 안 된다. 설정 값이 잘못 내려오는 경우는 사업자 쪽에서 처리한다.
