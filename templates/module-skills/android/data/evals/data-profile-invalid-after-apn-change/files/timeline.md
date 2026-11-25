# MOCK-9827 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-11-10T21:59:21.000Z (발생 시각), 구간: 파일 전체
- 줄: 22/22 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SETUP_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_USER_DATA_ENABLED · SET_USER_DATA_ROAMING_ENABLED · UNSOL_DATA_CALL_LIST_CHANGED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-11-10T21:59:20.519Z ~ 2026-11-10T21:59:23.535Z, 줄 22, 모양 22개 중 22개. 기준 시각: 2026-11-10T21:59:21.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

21:59:20.531 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-106-C, <APN#1>, state=null], cause=LOST_CONNECTION(0x10004)(65540), tearDownReason=DATA_PROFILE_INVALID  〔script 모양 1줄〕
21:59:23.535 p0 D DPM-0 Can't find any data profile that can satisfy [NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_VCN_MANAGED&NOT_BANDWI…  〔script 모양 1줄, 기준 뒤 첫 등장〕
21:59:23.535 p0 D DNC-0 Data evaluation: evaluation reason:RETRY_AFTER_DISCONNECTED, Data disallowed reasons: NO_SUITABLE_DATA_PROFILE, candidate profile=null, time=21:59:23.535, netw…  〔script 모양 1줄, 기준 뒤 첫 등장〕
21:59:20.531 p0 D DNC-0 Internet link status changed to INACTIVE  〔script 모양 1줄〕
21:59:20.531 p0 D DNC-0 Internet data state changed from CONNECTED to DISCONNECTED.  〔script 모양 1줄〕
21:59:20.531 p0 D DNC-0 IMS data state changed from CONNECTED to DISCONNECTED.  〔script 모양 1줄〕
21:59:20.530 - D DN-106-C DisconnectedState: All network requests detached.  〔script 모양 1줄〕
21:59:20.528 p0 D RILJ [2694]< DEACTIVATE_DATA_CALL [PHONE0]  〔script 모양 1줄〕
21:59:20.528 - D DN-106-C DisconnectingState: onDeactivateResponse: resultCode=RESULT_SUCCESS  〔script 모양 1줄〕
21:59:20.528 - D DN-106-C DisconnectingState: onDataStateChanged: PDN disconnected reported by WWAN data service. requireExplicitDisconnect false  〔script 모양 1줄〕
21:59:20.528 - D DN-106-C DisconnectedState: Data network disconnected. mEverConnected=true  〔script 모양 1줄〕
21:59:20.527 p0 D RILJ [2693]< SET_DATA_PROFILE [PHONE0]  〔script 모양 1줄〕
21:59:20.527 p0 D RILJ [2694]> DEACTIVATE_DATA_CALL cid = 22 reason = NORMAL [PHONE0]  〔script 모양 1줄〕
21:59:20.526 p0 D RILJ [2693]> SET_DATA_PROFILE with data profiles : [PHONE0]  〔script 모양 1줄〕
21:59:20.525 p0 D DRM-0 Remove all retry and throttling entries, reason=DATA_PROFILES_CHANGED  〔script 모양 1줄〕
21:59:20.525 p0 D DNC-0 Re-evaluating 1 existing data networks due to DATA_PROFILES_CHANGED  〔script 모양 1줄〕
21:59:20.525 p0 D DNC-0 Evaluated [DataNetwork: DN-106-C, <APN#1>, state=ConnectedState], Data evaluation: evaluation reason:DATA_PROFILES_CHANGED, Data disallowed reasons: DATA_PROFI…  〔script 모양 1줄〕
21:59:20.525 p0 D DNC-0 tearDownGracefully: Safe to tear down [DataNetwork: DN-106-C, <APN#1>, state=ConnectedState]  〔script 모양 1줄〕
21:59:20.525 - D DN-106-C ConnectedState: onTearDown: reason=DATA_PROFILE_INVALID  〔script 모양 1줄〕
21:59:20.524 p0 D DPM-0 updateDataProfilesAtModem: set 3 data profiles.  〔script 모양 1줄〕
21:59:20.522 p0 D DPM-0 Data profiles changed.  〔script 모양 1줄〕
21:59:20.519 p0 D DPM-0 Update data profiles due to APN db updated.  〔script 모양 1줄〕

## 본 타임라인

21:59:20.519 p0 D DPM-0 Update data profiles due to APN db updated.
21:59:20.522 p0 D DPM-0 Data profiles changed.
21:59:20.524 p0 D DPM-0 updateDataProfilesAtModem: set 3 data profiles.
21:59:20.525 p0 D DRM-0 Remove all retry and throttling entries, reason=DATA_PROFILES_CHANGED
21:59:20.525 p0 D DNC-0 Re-evaluating 1 existing data networks due to DATA_PROFILES_CHANGED
21:59:20.525 p0 D DNC-0 Evaluated [DataNetwork: DN-106-C, <APN#1>, state=ConnectedState], Data evaluation: evaluation reason:DATA_PROFILES_CHANGED, Data disallowed reasons: DATA_PROFI…  ⇒ data_evaluation_rejected(reasons=DATA_PROFILE_INVALID)
21:59:20.525 p0 D DNC-0 tearDownGracefully: Safe to tear down [DataNetwork: DN-106-C, <APN#1>, state=ConnectedState]
21:59:20.525 - D DN-106-C ConnectedState: onTearDown: reason=DATA_PROFILE_INVALID
21:59:20.526 p0 D RILJ [2693]> SET_DATA_PROFILE with data profiles : [PHONE0]
21:59:20.527 p0 D RILJ [2693]< SET_DATA_PROFILE [PHONE0]
21:59:20.527 p0 D RILJ [2694]> DEACTIVATE_DATA_CALL cid = 22 reason = NORMAL [PHONE0]
21:59:20.528 p0 D RILJ [2694]< DEACTIVATE_DATA_CALL [PHONE0]
21:59:20.528 - D DN-106-C DisconnectingState: onDeactivateResponse: resultCode=RESULT_SUCCESS
21:59:20.528 - D DN-106-C DisconnectingState: onDataStateChanged: PDN disconnected reported by WWAN data service. requireExplicitDisconnect false
21:59:20.528 - D DN-106-C DisconnectedState: Data network disconnected. mEverConnected=true
21:59:20.530 - D DN-106-C DisconnectedState: All network requests detached.
21:59:20.531 p0 D DNC-0 Internet link status changed to INACTIVE
21:59:20.531 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-106-C, <APN#1>, state=null], cause=LOST_CONNECTION(0x10004)(65540), tearDownReason=DATA_PROFILE_INVALID  ⇒ data_network_disconnected(cause=LOST_CONNECTION,reason=DATA_PROFILE_INVALID)
21:59:20.531 p0 D DNC-0 Internet data state changed from CONNECTED to DISCONNECTED.  ⇒ data_internet_state_changed(from=CONNECTED,to=DISCONNECTED)
21:59:20.531 p0 D DNC-0 IMS data state changed from CONNECTED to DISCONNECTED.
21:59:23.535 p0 D DPM-0 Can't find any data profile that can satisfy [NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_VCN_MANAGED&NOT_BANDWI…
21:59:23.535 p0 D DNC-0 Data evaluation: evaluation reason:RETRY_AFTER_DISCONNECTED, Data disallowed reasons: NO_SUITABLE_DATA_PROFILE, candidate profile=null, time=21:59:23.535, netw…  ⇒ data_evaluation_rejected(reasons=NO_SUITABLE_DATA_PROFILE)

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-11-10T21:54:21.000Z ~ 2026-11-10T22:09:21.000Z (분석 구간 끝과 기준 시각 2026-11-10T21:59:21.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 1. 프레임을 뺀 후보 1줄에서 F, 예외·crash 머리, E, 그 밖의 레벨 중 오류 문구 줄, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

21:59:20.531 p0 D DNC-0 onDataNetworkDisconnected: [DataNetwork: DN-106-C, <APN#1>, state=null], cause=LOST_CONNECTION(0x10004)(65540), tearDownReason=DATA_PROFILE_INVALID
