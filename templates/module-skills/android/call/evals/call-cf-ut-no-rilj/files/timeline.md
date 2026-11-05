# MOCK-9809 모듈 타임라인 (android/call, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/call, 중심: 2026-08-09T13:13:03+00:00 (발생 시각), 구간: 파일 전체
- 줄: 16/21 (잡음 6, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SET_CLIR · ENABLE_VONR · UNSOL_EMERGENCY_NUMBER_LIST · DIAL · HANGUP
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

13:13:00.448 - D VCD UsbAgent: ATD*21*123%23<CR>
13:13:00.451 - V RIL ================TelephonyStatusTracker(0)=======================
13:13:00.508 - D ImsPhone [0] dialInternal: dialing w/ mmi 'ImsPhoneMmiCode {State=PENDING action=* sc=21 sia=123 poundString=[qhCueMgbPEqjXw3pS7-HmXzqYus]}'...
13:13:00.508 - D ImsPhoneMmiCode processCode: is CF
13:13:00.508 - D ImsPhoneMmiCode processCode: is CF setCallForward
13:13:00.508 - D ImsPhone [0] setCallForwardingOption action=3, reason=0 serviceClass=0
13:13:00.508 - D ImsUt updateCallForward :: Ut=com.android.ims.internal.IImsUt$Stub$Proxy@8065000, action=3, condition=0, number=[QL0AFWMIX8NRZTKeof9cXsvbvu8], serviceClass=0, timeSe…
13:13:00.508 - D SHANNON_IMS 1531 [UT##] Request to update Call forward. Action : 3, Condition : 0, ServiceClass : 0, Time : 0 (ShannonImsUtImpl%updateCallForward:316)
13:13:00.510 - D SHANNON_IMS 1532 [UT##] Process SET_CALL_FORWARD_TYPE through CP_NETWORK [SLID:0 ] (UtOperatorProcessor%getUtProcessor:173)
13:13:01.692 - I SHANNON_IMS 1617 [HELP] #:PURP:# SOL TX{RILC_REQ_AIMS_SET_CALL_FORWARD_STATUS} : status : 3 reason : 0 service-class : 1 toa : 129 number-len : 3 number : 1** timeseconds …
13:13:01.695 - V RIL [<DEV#1>][TX] SIT_AIMS_SET_CALL_FORWARD_STATUS, REQ, 79 bytes, Token(0x01c4)
13:13:03.667 - V RIL [<DEV#1>][RX] SIT_AIMS_SET_CALL_FORWARD_STATUS, RSP, 19 bytes, Token(0x01c4), OK(RCM_E_SUCCESS)
13:13:03.670 - I SHANNON_IMS 1618 [DATA] SOL RX{RILC_REQ_AIMS_SET_CALL_FORWARD_STATUS} status : STATUS_SUCCESS [status : 3 reason : 0 service-class : 1 toa : 129 number-len : 3 number : 1*…
13:13:03.672 - D SHANNON_IMS 1619 [UT##] #:BLUE:# Receive update result from CP about Id 1693469021 [SLID:0 ] (UtCpProcessor$UtNetworkListener%callOnUpdated:623)
13:13:03.706 - D ImsPhoneMmiCode onSetComplete: mmi=ImsPhoneMmiCode {State=COMPLETE action=* sc=21 sia=123 poundString=[qhCueMgbPEqjXw3pS7-HmXzqYus]}
13:13:03.706 - D ImsPhone [0] onMMIDone: mmi=ImsPhoneMmiCode {State=COMPLETE action=* sc=21 sia=123 poundString=[qhCueMgbPEqjXw3pS7-HmXzqYus]}
