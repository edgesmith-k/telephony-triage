# MOCK-9810 모듈 타임라인 (android/sms, 심층)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/sms, 중심: 2026-11-11T00:03:05.340Z (근거), 구간: 2026-11-11T00:02:35.340Z ~ 2026-11-11T00:03:10.340Z
- 줄: 8/16 (잡음 0, 반복 접음 1), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): GSM_SET_BROADCAST_CONFIG · GSM_BROADCAST_ACTIVATION · SEND_SMS · IMS_SEND_SMS · SMS_ACKNOWLEDGE
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

00:02:50.132 p0 D RILJ [3192]> RADIO_POWER on = false forEmergencyCall= false preferredForEmergencyCall=false [PHONE0]
00:02:50.135 p0 D RILJ [3192]< RADIO_POWER [PHONE0]
00:02:50.135 p0 D RILJ [UNSL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED radioStateChanged: OFF [PHONE0]
00:02:50.169 p0 D SST-0 pollStateDone: hasRegistered = false hasDeregistered = true hasDataAttached = {1=false, 2=false} hasDataDetached = {1=true, 2=false} hasDataRegStateChanged = {…  ⇒ network_service_state(deregistered=true,registered=false)
00:03:05.171 - D SmsDispatchersController sendTextInternal: messageId=0, uniqueMessageId=4
00:03:05.171 p0 D ImsSmsDispatcher [0] isAvailable: up=false, reg= false, cap= false  〔script: 같은 줄 ×2〕
00:03:05.171 - D SMSDispatcher sendText id: {x-message-id:0}
00:03:05.340 - D GsmSMSDispatcher sendSms: isIms()=false mRetryCount=0 mImsRetry=0 mMessageRef=0 mUsesImsServiceForIms=false SS=3 {x-message-id:0}
