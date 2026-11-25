# MOCK-9815 모듈 타임라인 (android/modem, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/modem, 중심: 2026-08-28T17:00:15.000Z (발생 시각), 구간: 파일 전체
- 줄: 6/25 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: call 2 · data 1
- 미수집(modules.yaml 이름 중 이 로그에 없음): GET_RADIO_CAPABILITY · SET_PREFERRED_DATA_MODEM · ENABLE_MODEM · BASEBAND_VERSION · UNSOL_MODEM_RESTART
- 모듈 신호 약함: ±15초에 이 모듈 경고·오류 줄이 없고 call에 2줄이 있다
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-08-28T17:00:02.000Z ~ 2026-08-28T17:01:45.000Z, 줄 25, 모양 11개 중 11개. 기준 시각: 2026-08-28T17:00:15.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

17:00:45.000 - W ImsPhoneCallTracker [0] call ended: cause=65535  〔script 모양 1줄, 기준 뒤 첫 등장〕
17:00:25.000 p0 I DNC-0 onEvaluateNetworkRequests: reason=DATA_SERVICE_STATE_CHANGED  〔script 모양 1줄, 기준 뒤 첫 등장〕
17:00:40.000 p0 I DNC-0 onEvaluateNetworkRequests: reason=RETRY_SCHEDULED  〔script 모양 5줄, 17:00:40.000~17:01:40.000, 기준 뒤 첫 등장〕
17:01:15.000 p0 D RILJ [0605]> DATA_CALL_LIST [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
17:00:15.000 p0 D DNC-0 Internet data state changed from CONNECTED to DISCONNECTED.  〔script 모양 1줄〕
17:00:12.500 p0 D RILJ [0603]> DIAL [PHONE0]  〔script 모양 1줄〕
17:00:12.000 - I GsmCdmaPhone [0] useImsForCall=false, useOnlyDialedSimEccList=false, isEmergency=false, useImsForEmergency=false, useImsForUt=false, isUt=false, isSuppServiceCode=false, is…  〔script 모양 1줄〕
17:00:05.000 p0 D SST-0 pollStateDone: hasRegistered = false hasDeregistered = false hasDataAttached = {1=false, 2=false} hasDataDetached = {1=false, 2=false} hasDataRegStateChanged =…  〔script 모양 8줄, 17:00:05.000~17:01:45.000〕
17:00:10.000 p0 D RILJ [0601]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] internet, internet.example, IPV4V6] [PHONE0]  〔script 모양 1줄〕
17:00:08.000 - D ImsPhone [0] handleImsRegistered: onImsMmTelConnected imsTransportType=WWAN  〔script 모양 4줄, 17:00:08.000~17:01:30.000〕
17:00:02.000 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  〔script 모양 1줄〕

## 본 타임라인

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

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-08-28T16:55:15.000Z ~ 2026-08-28T17:10:15.000Z (분석 구간 끝과 기준 시각 2026-08-28T17:00:15.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 1. 프레임을 뺀 후보 1줄에서 F, 예외·crash 머리, E, 레벨을 믿지 않는 줄의 오류 문구, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

17:00:45.000 - W ImsPhoneCallTracker [0] call ended: cause=65535
