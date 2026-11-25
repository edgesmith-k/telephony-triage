# MOCK-9805 모듈 타임라인 (android/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/sim, 중심: 2026-10-16T08:30:14.000Z (발생 시각), 구간: 파일 전체
- 줄: 16/18 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): GET_SIM_STATUS · SIM_OPEN_CHANNEL · SIM_CLOSE_CHANNEL · SIM_TRANSMIT_APDU_CHANNEL · STK_SEND_TERMINAL_RESPONSE
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-10-16T08:30:14.602Z ~ 2026-10-16T08:30:18.219Z, 줄 20, 모양 17개 중 17개. 기준 시각: 2026-10-16T08:30:14.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

08:30:14.764 - D RilRequest [0233]< SIM_IO error: com.android.internal.telephony.CommandException: GENERIC_FAILURE  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:15.934 - E SIMRecords [SIMRecords-0] Exception in fetching EF_CSP data com.android.internal.telephony.CommandException: GENERIC_FAILURE  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.766 - E UsimFH exception caught from EVENT_GET_RECORD_SIZE  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.602 - D MultiSimSettingController Carrier config subId 2 is not loaded.  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.603 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED READY reason null for phone: 0 sub: 2  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.604 - D IntentBroadcaster Broadcasting and adding intent for rebroadcast: android.intent.action.SIM_STATE_CHANGED READY for phoneId 0  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.731 - V RIL ipc[0][TX] VIPC_EXAMPLE_CARD_IO, REQ seq=0x0c40 len=40  〔script 모양 2줄, 08:30:14.731~08:30:15.904, 기준 뒤 첫 등장〕
08:30:14.732 - I RIL [ExampleEfService_0] sim io begin  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.760 - V RIL ipc[0][RX] VIPC_EXAMPLE_CARD_IO, RSP Error(VIPC_E_FAILURE) seq=0x0c40 len=12  〔script 모양 2줄, 08:30:14.760~08:30:15.931, 기준 뒤 첫 등장〕
08:30:14.763 p0 D RILJ [0233]< SIM_IO error 2 [PHONE0]  〔script 모양 2줄, 08:30:14.763~08:30:15.932, 기준 뒤 첫 등장〕
08:30:14.768 p0 D RILJ [0234]> iccIO: SIM_IO command = 0xc0 fileId = 0x6f15 path = 3F007FFF p1 = 0 p2 = 0 p3 = 15 data = null aid = <AID#1> [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:14.770 - D SIMRecords [SIMRecords-0] onRecordLoaded 21 requested: true  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:15.937 - D VRIL-SVC RadioSimProxy::iccTransmitApduLogicalChannel  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:17.402 - V RIL [IpcCtx_0] untrack seq 0x0c47  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:18.215 - I RIL [EccLoader_0] emergency number list loaded  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:18.218 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED LOADED reason null for phone: 0 sub: 2  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:30:18.219 - D IntentBroadcaster Broadcasting and adding intent for rebroadcast: android.intent.action.SIM_STATE_CHANGED LOADED for phoneId 0  〔script 모양 1줄, 기준 뒤 첫 등장〕

## 본 타임라인

08:30:14.602 - D MultiSimSettingController Carrier config subId 2 is not loaded.
08:30:14.603 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED READY reason null for phone: 0 sub: 2  ⇒ sim_state_changed(state=READY)
08:30:14.731 - V RIL ipc[0][TX] VIPC_EXAMPLE_CARD_IO, REQ seq=0x0c40 len=40
08:30:14.732 - I RIL [ExampleEfService_0] sim io begin
08:30:14.760 - V RIL ipc[0][RX] VIPC_EXAMPLE_CARD_IO, RSP Error(VIPC_E_FAILURE) seq=0x0c40 len=12  ⇒ builtin.common.vendor_ipc_error(error=VIPC_E_FAILURE,ipc=VIPC_EXAMPLE_CARD_IO)
08:30:14.763 p0 D RILJ [0233]< SIM_IO error 2 [PHONE0]
08:30:14.764 - D RilRequest [0233]< SIM_IO error: com.android.internal.telephony.CommandException: GENERIC_FAILURE
08:30:14.766 - E UsimFH exception caught from EVENT_GET_RECORD_SIZE
08:30:14.768 p0 D RILJ [0234]> iccIO: SIM_IO command = 0xc0 fileId = 0x6f15 path = 3F007FFF p1 = 0 p2 = 0 p3 = 15 data = null aid = <AID#1> [PHONE0]
08:30:14.770 - D SIMRecords [SIMRecords-0] onRecordLoaded 21 requested: true
08:30:15.904 - V RIL ipc[0][TX] VIPC_EXAMPLE_CARD_IO, REQ seq=0x0c47 len=40
08:30:15.931 - V RIL ipc[0][RX] VIPC_EXAMPLE_CARD_IO, RSP Error(VIPC_E_FAILURE) seq=0x0c47 len=12  ⇒ builtin.common.vendor_ipc_error(error=VIPC_E_FAILURE,ipc=VIPC_EXAMPLE_CARD_IO)
08:30:15.932 p0 D RILJ [0234]< SIM_IO error 2 [PHONE0]
08:30:15.934 - E SIMRecords [SIMRecords-0] Exception in fetching EF_CSP data com.android.internal.telephony.CommandException: GENERIC_FAILURE
08:30:15.937 - D VRIL-SVC RadioSimProxy::iccTransmitApduLogicalChannel
08:30:18.218 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED LOADED reason null for phone: 0 sub: 2  ⇒ sim_state_changed(state=LOADED)

## 이상 줄: W/E/F 레벨과 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 빠짐)

- 범위: 2026-10-16T08:25:14.000Z ~ 2026-10-16T08:40:14.000Z (분석 구간 끝과 기준 시각 2026-10-16T08:30:14.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 3. 프레임을 뺀 후보 3줄에서 F, 예외·crash 머리, E, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

08:30:14.764 - D RilRequest [0233]< SIM_IO error: com.android.internal.telephony.CommandException: GENERIC_FAILURE
08:30:14.766 - E UsimFH exception caught from EVENT_GET_RECORD_SIZE
08:30:15.934 - E SIMRecords [SIMRecords-0] Exception in fetching EF_CSP data com.android.internal.telephony.CommandException: GENERIC_FAILURE
