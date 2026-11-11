# MOCK-9815 모듈 타임라인 (android/modem, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/modem, 중심: 2026-08-28T17:00:15+00:00 (발생 시각), 구간: 파일 전체
- 줄: 6/25 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: call 2 · data 1
- 미수집(modules.yaml 이름 중 이 로그에 없음): GET_RADIO_CAPABILITY · SET_PREFERRED_DATA_MODEM · ENABLE_MODEM · BASEBAND_VERSION · UNSOL_MODEM_RESTART
- 모듈 신호 약함: ±15초에 이 모듈 경고·오류 줄이 없고 call에 2줄이 있다
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

17:00:02.000 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  ⇒ data_internet_state_changed(from=DISCONNECTED,to=CONNECTED)
17:00:08.000 - D ImsPhone [0] handleImsRegistered: onImsMmTelConnected imsTransportType=WWAN  ⇒ ims_registered(transport=WWAN)
17:00:15.000 p0 D DNC-0 Internet data state changed from CONNECTED to DISCONNECTED.  ⇒ data_internet_state_changed(from=CONNECTED,to=DISCONNECTED)
17:00:30.000 - D ImsPhone [0] handleImsRegistered: onImsMmTelConnected imsTransportType=WWAN  ⇒ ims_registered(transport=WWAN)
17:01:00.000 - D ImsPhone [0] handleImsRegistered: onImsMmTelConnected imsTransportType=WWAN  ⇒ ims_registered(transport=WWAN)
17:01:30.000 - D ImsPhone [0] handleImsRegistered: onImsMmTelConnected imsTransportType=WWAN  ⇒ ims_registered(transport=WWAN)

## 다른 모듈 줄 (±15초, 경고·오류)
17:00:10.000 p0 D RILJ [0601]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] internet, internet.example, IPV4V6] [PHONE0]  ⇒ ril_no_response(request=SETUP_DATA_CALL,serial=601,timeout_ms=30000)
17:00:12.000 - I GsmCdmaPhone [0] useImsForCall=false, useOnlyDialedSimEccList=false, isEmergency=false, useImsForEmergency=false, useImsForUt=false, isUt=false, isSuppServiceCode=false, is…  ⇒ ims_dial_attempt(ims=false,ims_state=0)
17:00:12.500 p0 D RILJ [0603]> DIAL [PHONE0]  ⇒ ril_no_response(request=DIAL,serial=603,timeout_ms=10000)
