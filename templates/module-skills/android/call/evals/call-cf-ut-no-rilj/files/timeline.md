# MOCK-9809 모듈 타임라인 (android/call, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/call, 중심: 2026-10-14T09:41:07+00:00 (발생 시각), 구간: 파일 전체
- 줄: 16/20 (잡음 3, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SET_CLIR · ENABLE_VONR · UNSOL_EMERGENCY_NUMBER_LIST · DIAL · HANGUP
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

09:41:06.812 - D VRIL-MODEM at-in: ATD*21*123#
09:41:06.840 - V RIL ==== vendor status (0) ====
09:41:06.902 - D ImsPhone [0] dialInternal: dialing w/ mmi 'ImsPhoneMmiCode {State=PENDING action=* sc=21 sia=123 poundString=[Zx81kQpLm2Vt0aRs]}'...
09:41:06.903 - D ImsPhoneMmiCode processCode: is CF
09:41:06.903 - D ImsPhoneMmiCode processCode: is CF setCallForward
09:41:06.904 - D ImsPhone [0] setCallForwardingOption action=3, reason=0 serviceClass=0
09:41:06.905 - D ImsUt updateCallForward :: Ut=com.android.ims.internal.IImsUt$Stub$Proxy, action=3, condition=0, number=[Qb7nW2cY9dLe], serviceClass=0, timeSeconds=0
09:41:06.907 - D VRIL-IMS [ut] update call forward action=3 condition=0 class=0 time=0
09:41:06.909 - D VRIL-IMS [ut] route call forward via modem slot=0
09:41:07.513 - I VRIL-IMS [ril] req -> OEM_REQ_IMS_SET_CALL_FORWARD : status : 3 reason : 0 class : 1 toa : 129 number : 1** time : 0 slot=0
09:41:07.515 - V RIL mux [ch0][TX] VIPC_EXAMPLE_IMS_CF, REQ seq=0x0b12 len=64
09:41:09.284 - V RIL mux [ch0][RX] VIPC_EXAMPLE_IMS_CF, RSP OK(VIPC_OK) seq=0x0b12 len=16
09:41:09.289 - I VRIL-IMS [ril] rsp <- OEM_REQ_IMS_SET_CALL_FORWARD : status : SUCCESS slot=0
09:41:09.291 - D VRIL-IMS [ut] call forward update result received id=4021 slot=0
09:41:09.320 - D ImsPhoneMmiCode onSetComplete: mmi=ImsPhoneMmiCode {State=COMPLETE action=* sc=21 sia=123 poundString=[Zx81kQpLm2Vt0aRs]}
09:41:09.321 - D ImsPhone [0] onMMIDone: mmi=ImsPhoneMmiCode {State=COMPLETE action=* sc=21 sia=123 poundString=[Zx81kQpLm2Vt0aRs]}
