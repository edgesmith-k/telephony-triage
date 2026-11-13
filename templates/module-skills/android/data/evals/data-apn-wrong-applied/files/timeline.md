# MOCK-9816 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-09-02T10:00:05+00:00 (발생 시각), 구간: 파일 전체
- 줄: 18/20 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: sim 1
- 미수집(modules.yaml 이름 중 이 로그에 없음): DEACTIVATE_DATA_CALL · SET_USER_DATA_ENABLED · SET_USER_DATA_ROAMING_ENABLED · UNSOL_DATA_CALL_LIST_CHANGED · UNSOL_DATA_CALL_LIST_UPDATED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

10:00:02.500 p0 D DCM-0 Carrier config updated. Config is carrier specific.
10:00:03.000 p0 D DPM-0 Data profiles updated: [DataProfile=[ApnSetting] DEFAULT <APN#2>, IPV4V6, preferred=false] [DataProfile=[ApnSetting] IMS <APN#3>, IPV4V6, preferred=false]
10:00:03.010 p0 D DPM-0 Preferred data profile kept from previous carrier: [DataProfile=[ApnSetting] DEFAULT <APN#1>, IPV4V6, preferred=true]
10:00:03.100 p0 D RILJ [0410]> SET_INITIAL_ATTACH_APN [DataProfile=[ApnSetting] DEFAULT <APN#1>, IPV4V6] [PHONE0]
10:00:03.104 - D VRIL-SVC RadioDataProxy::setInitialAttachApn: serial 410
10:00:03.106 - V RIL ipc[0][TX] VIPC_EXAMPLE_ATTACH_PROFILE, REQ seq=0x0310 len=120
10:00:03.150 - V RIL ipc[0][RX] VIPC_EXAMPLE_ATTACH_PROFILE, RSP OK(VIPC_OK) seq=0x0310 len=12
10:00:03.160 p0 D RILJ [0410]< SET_INITIAL_ATTACH_APN [PHONE0]
10:00:03.200 p0 D RILJ [0411]> SET_DATA_PROFILE with data profiles : [PHONE0]
10:00:03.260 p0 D RILJ [0411]< SET_DATA_PROFILE [PHONE0]
10:00:03.262 p0 D DSM-C-0 onSetDataProfileComplete. resultCode = 0
10:00:05.000 p0 D RILJ [0412]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] DEFAULT <APN#1>, IPV4V6] [PHONE0]
10:00:05.004 - D VRIL-SVC RadioDataProxy::setupDataCall: serial 412
10:00:05.006 - I RIL [ExamplePdnService_0] setup data call begin
10:00:05.300 - I RIL [ExamplePdnService_0] setup data call end errorCode=0 PdnCtx cid=2 state=connected link=up
10:00:05.310 p0 D RILJ [0412]< SETUP_DATA_CALL DataCallResponse: { cause=NONE(0x0) retry=0 cid=2 linkStatus=2 protocolType=2 ifname=rmnet1 addresses=[<IP#1>/64] } [PHONE0]
10:00:05.320 p0 D DSM-C-0 onSetupDataCallComplete. resultCode = 0
10:00:05.400 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  ⇒ data_internet_state_changed(from=DISCONNECTED,to=CONNECTED)

## 다른 모듈 줄 (±15초, 경고·오류)
10:00:02.000 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED LOADED reason null for phone: 0 sub: 1  ⇒ sim_state_changed(state=LOADED)
