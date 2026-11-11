---
name: android-network
description: telephony-triage Step 5-1에서 triage.py module 출력으로만 읽는다
---

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

# Android network — 심층 분석 절차

1위 후보 로그에서 **처음 실패한 층과 구성요소**를 찾아 1위 원인과 비교한다. 순위는 스크립트가 정하고 이 답은 의견이다.

## 입력

`events`·`log_paths`는 열지 않는다. 〔script …〕 메모는 근거가 아니다. 없는 줄은 지어내지 않고 `반대 근거`에 더 볼 로그로 적는다.

## 판단 순서

1. RILJ `VOICE/DATA_REGISTRATION_STATE` 응답의 `regState`·`reasonForDenial`을 본다. (없으면: NRM-C `onRequestNetworkRegistrationInfoComplete … registrationState=DENIED … rejectCause=`, SST `Poll ServiceState done: newSS=` — `registrationState=DENIED`면 2번으로 층을 정한다. `rejectCause=0`은 사유를 안 준 것이라 그 숫자에서 사유를 읽지 않는다)
2. `REG_DENIED`·`reasonForDenial≠NONE` → 모뎀·망. 원인 데몬은 그 값을 전한 벤더 RIL(`RIL`).
3. 같은 요청의 IPC(`VIPC_EXAMPLE_*_REG`)가 OK면 거절 값은 망이 준 것이다.
4. 무선이 꺼진 직후(`AT+CFUN=0`, `RADIO_OFF`, RILJ `radioStateChanged: OFF`)의 서비스 없음은 결과다 → 무선을 끈 쪽을 답한다.
5. DENIED가 아닌 `reasonForDenial: NONE`은 거절이 아니다. DENIED면 `NONE`·`rejectCause=0`이어도 거절이다(모뎀·망, 사유를 빠뜨린 것은 벤더 RIL). 거절 없이 오래 `NOT_REGISTERED`면 찾는 중이다.
6. 1위와 비교: 같으면 `1위와 같음`, 다르면 `<원인 ID> — <근거>`.
