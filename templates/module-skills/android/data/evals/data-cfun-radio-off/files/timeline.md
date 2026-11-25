# MOCK-9802 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-10-14T15:22:40.000Z (발생 시각), 구간: 파일 전체
- 줄: 14/18 (잡음 1, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SETUP_DATA_CALL · DEACTIVATE_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_DATA_PROFILE · SET_USER_DATA_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-10-14T15:22:40.118Z ~ 2026-10-14T15:22:40.333Z, 줄 20, 모양 20개 중 20개. 기준 시각: 2026-10-14T15:22:40.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

15:22:40.270 - D TNA-7 NetworkAgent channel lost  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.118 - D VRIL-MODEM at-in: AT+CFUN=0  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.226 - D VRIL-MODEM at-out: AT+CFUN=0  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.231 - V SatelliteController satelliteConfigParser is not ready  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.233 p0 D RILJ [UNSL]< UNSOL_DATA_CALL_LIST_UPDATED [SetupDataCallResult{cause: NONE, suggestedRetryTime: 0, cid: 3, active: 0, type: IPV4V6, ifname: rmnet2, addresses: [Link…  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.252 - D DN-7-C ConnectedState: onDataStateChanged: PDN inactive reported by WWAN data service.  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.253 - D DN-7-C DisconnectedState: Data network disconnected. mEverConnected=true  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.266 p0 D RILJ [UNSL]< UNSOL_RESPONSE_NETWORK_STATE_CHANGED [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.267 p0 D DNC-0 Internet link status changed to INACTIVE  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.268 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-7-C, IMS, state=null], cause=NONE(0x0)(0), tearDownReason=NONE  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.268 p0 D DNC-0 IMS data state changed from CONNECTED to DISCONNECTED.  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.269 p0 D NRM-C-0 onNetworkStateChanged  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.271 - D DN-8-C DisconnectedState: All network requests detached.  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.272 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-8-C, <APN#1>, state=null], cause=NONE(0x0)(0), tearDownReason=NONE  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.272 p0 D DNC-0 Internet data state changed from CONNECTED to DISCONNECTED.  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.284 - D ImsRegCallbackHelper updateRegistrationState: registration state from REGISTRATION_STATE_REGISTERED to REGISTRATION_STATE_NOT_REGISTERED  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.285 - D ImsPhone [0] handleImsUnregistered: onImsMmTelDisconnected imsReasonInfo=ImsReasonInfo :: {121 : CODE_LOCAL_NETWORK_NO_SERVICE, 0, null}, suggestedAction=0, disconnecte…  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.331 - I RIL [IpcCtx_0] rx frame unsol id=3  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.332 - D VRIL-MODEM at-out: OK  〔script 모양 1줄, 기준 뒤 첫 등장〕
15:22:40.333 - D VRIL-SVC emergencyNumberList indication  〔script 모양 1줄, 기준 뒤 첫 등장〕

## 본 타임라인

15:22:40.118 - D VRIL-MODEM at-in: AT+CFUN=0
15:22:40.226 - D VRIL-MODEM at-out: AT+CFUN=0
15:22:40.233 p0 D RILJ [UNSL]< UNSOL_DATA_CALL_LIST_UPDATED [SetupDataCallResult{cause: NONE, suggestedRetryTime: 0, cid: 3, active: 0, type: IPV4V6, ifname: rmnet2, addresses: [Link…
15:22:40.252 - D DN-7-C ConnectedState: onDataStateChanged: PDN inactive reported by WWAN data service.
15:22:40.253 - D DN-7-C DisconnectedState: Data network disconnected. mEverConnected=true
15:22:40.267 p0 D DNC-0 Internet link status changed to INACTIVE
15:22:40.268 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-7-C, IMS, state=null], cause=NONE(0x0)(0), tearDownReason=NONE  ⇒ data_network_disconnected(cause=NONE,reason=NONE)
15:22:40.268 p0 D DNC-0 IMS data state changed from CONNECTED to DISCONNECTED.
15:22:40.270 - D TNA-7 NetworkAgent channel lost
15:22:40.271 - D DN-8-C DisconnectedState: All network requests detached.
15:22:40.272 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-8-C, <APN#1>, state=null], cause=NONE(0x0)(0), tearDownReason=NONE  ⇒ data_network_disconnected(cause=NONE,reason=NONE)
15:22:40.272 p0 D DNC-0 Internet data state changed from CONNECTED to DISCONNECTED.  ⇒ data_internet_state_changed(from=CONNECTED,to=DISCONNECTED)
15:22:40.285 - D ImsPhone [0] handleImsUnregistered: onImsMmTelDisconnected imsReasonInfo=ImsReasonInfo :: {121 : CODE_LOCAL_NETWORK_NO_SERVICE, 0, null}, suggestedAction=0, disconnecte…  ⇒ ims_registration_failed(code=121,extra=0,reason=CODE_LOCAL_NETWORK_NO_SERVICE)
15:22:40.332 - D VRIL-MODEM at-out: OK
