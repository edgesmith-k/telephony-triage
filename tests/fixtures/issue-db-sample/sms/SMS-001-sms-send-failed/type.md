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
  - id: sms-send-request-missing
    must_match: ['GsmSMSDispatcher: sendSms: .*isIms\(\)=false .*\bSS=[1-3]\b']
    window_sec: 60
causes:
  - id: SMS-001-01
    status: active
    title: 전송 요청이 만들어지지 않음
    description: CS 발신이 디스패처 sendSms에서 서비스 상태 아님(SS=1·2 서비스 없음, SS=3 무선 꺼짐)으로 멈춰 RIL SEND_SMS 요청이 나가지 않음
    signatures:
      - id: send-request-missing
        must_match: ['GsmSMSDispatcher: sendSms: .*isIms\(\)=false .*\bSS=[1-3]\b']
        window_sec: 60
    recovery_signatures: []
    scenario_signatures: []
    resolution: 요청이 멈춘 단계(디스패처 sendSms의 서비스 상태 SS=, SMSC 설정)를 확인해 설정을 바로잡고 전송을 재시도한다
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
    platform_versions: []
    code_refs: []
tags: [smsc]
---

## 증상

SMS를 보내면 전송 실패로 끝나거나 아예 나가지 않는다. 재시도해도 같은 결과가 된다.

## 증상 판별 방법

IMS 전송이 실패해 CS로 넘긴 줄(`ImsSmsDispatcher`, 17 소스 문구)이 남거나, CS 발신 디스패처 `sendSms:`가 서비스 상태 아님(`SS=1·2` 서비스 없음, `SS=3` 무선 꺼짐)으로 찍힌다(그 뒤 RILJ `> SEND_SMS`가 없다).

```
09-26 13:00:05.000  1500  1510 E ImsSmsDispatcher [0]: sendSms failed. Falling back to PSTN. Error: <msg>
09-26 13:00:00.000  1500  1510 D SmsDispatchersController: sendTextInternal: messageId=0, uniqueMessageId=3
```

## 원인별 상세

### SMS-001-01 전송 요청이 만들어지지 않음

- **로그 예시**:
  ```
  09-26 13:00:00.000  1500  1510 D SmsDispatchersController: sendTextInternal: messageId=0, uniqueMessageId=3
  09-26 13:00:00.170  1500  1510 D GsmSMSDispatcher: sendSms:  isIms()=false mRetryCount=0 mImsRetry=0 mMessageRef=0 mUsesImsServiceForIms=false SS=3 {x-message-id:0}
  ```
- **확인 방법**: `GsmSMSDispatcher`의 `sendSms: isIms()=false … SS=`가 1~3이다(서비스 상태, 0은 정상·3은 무선 꺼짐). 그 뒤 RILJ `> SEND_SMS`가 없는지 함께 본다. 17 발신 경로는 SMSC를 찍지 않으므로 SMSC는 캐리어 설정으로 본다. IMS로 나간 문자는 RILJ `SEND_SMS`가 없으므로 IMS 등록 상태를 함께 본다(사내 확인).
- **재현 시나리오**: 비행기 모드(또는 SMSC 주소를 지운 SIM 프로필) → 문자 발신 → 요청·디스패처 로그 확인
- **해결책**: 요청이 멈춘 단계(디스패처 sendSms의 서비스 상태 SS=, SMSC 설정)를 확인해 설정을 바로잡고 전송을 재시도한다.
- **코드 위치**: 없음. 사내 SmsDispatchersController 경로를 확인하면 추가한다 — TODO(SITE:S11).
- **비고**: 단말 수정 대상이 아니라고 판단해 `wont-fix`로 뒀다. **사유**: SMSC 값은 캐리어 설정/SIM 프로필에서 오고, 값이 비어 있을 때 단말이 임의 값을 채우면 안 된다. 설정 값이 잘못 내려오는 경우는 사업자 쪽에서 처리한다.
