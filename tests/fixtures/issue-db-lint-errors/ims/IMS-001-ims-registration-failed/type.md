---
id: IMS-001
category: ims
secondary_categories: []
title: IMS 등록이 되지 않음
summary: IMS 등록이 실패로 끝나고 재시도해도 등록 상태가 되지 않는다
status: active
signatures_pending: true
symptom_signatures:
  - id: ims-registration-failure
    must_event:
      - {event: ims_registration_failed}
    window_sec: 300
causes:
  - id: IMS-001-01
    status: active
    title: 등록 거절 (403)
    description: IMS 망이 등록 요청을 403으로 거절해 등록이 완료되지 않음
    signatures:
      - id: nested
        must_match: ['(a+)+b']
        window_sec: 60
      - id: registration-forbidden
        must_event:
          - {event: ims_registration_failed, fields: {code: '403'}}
        window_sec: 300
    recovery_signatures: []
    scenario_signatures: []
    resolution: 캐리어 설정의 IMS 항목과 가입 상태를 확인하고 재등록을 시도한다
    resolution_type: framework-bug
    resolution_verification: {status: unverified}
    fix:
      status: open
      ref: null
      fixed_in: []
      verification: null
      verification_history:
        - result: failed
          build: MOCKB77_U2_20260920
          date: 2026-09-27
          by: mock-user2
          fixture: fixtures/IMS-001-01.recurrence.MOCKB77_U2_20260920.log
          ref: MOCKCL-34567
          fixed_in:
            - {branch: MOCKB77_U2, build: MOCKB77_U2_20260920}
          note: 수정 반영 빌드에서 같은 403 거절이 재발해 open으로 되돌림
    related: [CALL-001-01]
    cp_evidence: null
    android_versions: ["17"]
    code_refs: []
tags: [ims-registration]
---

## 증상

IMS 등록이 완료되지 않아 VoLTE/VoWiFi 기능이 동작하지 않는다. 등록 실패가 반복된다.

## 증상 판별 방법

IMS 등록 콜백에 실패가 남는다.

```
09-27 09:30:05.000  1600  1610 W ImsRegistration: [PHONE0] onRegistrationFailed: code=403 reason=FORBIDDEN
```

- 등록 성공(`onRegistered:`) 뒤 해제된 경우는 이 증상이 아니다.

## 원인별 상세

### IMS-001-01 등록 거절 (403)

- **로그 예시**:
  ```
  09-27 09:30:00.000  1600  1610 D ImsResolver: [PHONE0] bound to mock ImsService
  09-27 09:30:05.000  1600  1610 W ImsRegistration: [PHONE0] onRegistrationFailed: code=403 reason=FORBIDDEN
  09-27 09:30:35.000  1600  1610 W ImsRegistration: [PHONE0] onRegistrationFailed: code=403 reason=FORBIDDEN
  ```
- **확인 방법**: 거절 코드가 403이다. 다른 코드(408 타임아웃 등)는 원인이 다르므로 새 원인을 검토한다.
- **재현 시나리오**: IMS 지원 SIM 삽입 → 비행기 모드 OFF → 등록 시도 로그 확인
- **해결책**: 캐리어 설정의 IMS 항목과 가입 상태를 확인하고 재등록을 시도한다.
- **코드 위치**: 없음. 사내 ImsService/ImsRegistration 경로를 확인하면 추가한다 — TODO(SITE:S11).
- **비고**: 수정 CL(`MOCKCL-34567`)을 반영한 빌드에서 재발해 `verify-fix`가 실패했고 `open`으로 되돌아왔다. 실패 기록과 그때의 `ref`·`fixed_in`은 `verification_history`에 남아 있고, 재발 로그는 `recurrence` fixture로 들어가 있다.
  `resolution_type`이 `framework-bug`인데 `scenario_signatures`·`recovery_signatures`가 아직 없어서, 다음 `verify-fix` 전에 흔적 시그니처를 먼저 넣어야 한다(월간 리뷰의 "fixed 전환 불가" 항목).
- **연관**: VoLTE 발신이 실패하는 증상은 call 카테고리의 `CALL-001-01`이다 (`related` 양방향).
