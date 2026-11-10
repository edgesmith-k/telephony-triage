# MOCK-9701 모듈 타임라인 (ofono/network, 심층)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/network, 중심: 2026-09-21T10:50:05.022Z (근거), 구간: 2026-09-21T10:49:35.020Z ~ 2026-09-21T10:50:10.022Z
- 줄: 20/25 (잡음 6, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): networkd · src/network.c · src/netmon.c · drivers/rilmodem/network-registration.c · drivers/rilmodem/netmon.c
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

10:50:00.200 - I vrild [NetRegService_0] signal update nr rsrp=-88
10:50:02.050 p0 I ofonod [0,UNSOL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED (state: UNAVAILABLE)
10:50:05.002 p0 I mgmtd dbus -> org.ofono.RadioSettings.GetProperties on /ril_0
10:50:05.004 p0 I ofonod dbus_trace method call - i:org.ofono.RadioSettings m:GetProperties p:/ril_0 a:no args
10:50:05.005 - D ofonod drivers/rilmodem/radio-settings.c:ril_query_rat_mode()
10:50:05.005 p0 I ofonod [0,0511]> RIL_REQUEST_GET_PREFERRED_NETWORK_TYPE
10:50:05.006 - D vrild client fd 9 VCHAN_1 REQUEST: GET_PREFERRED_NETWORK_TYPE (8 bytes)
10:50:05.006 - I vrild [NetRegService_0] rat-mode query start
10:50:05.006 - D vrild [IpcCtx_0] track seq 0x0241
10:50:05.007 - D vrild mux [ch0][TX] SIT_GET_PREFERRED_NETWORK_TYPE, REQ seq=0x0241 len=12
10:50:05.020 - D vrild mux [ch0][RX] SIT_GET_PREFERRED_NETWORK_TYPE, RSP Error(RCM_E_FAILURE) seq=0x0241 len=12  ⇒ builtin.common.vendor_ipc_error(error=RCM_E_FAILURE,ipc=SIT_GET_PREFERRED_NETWORK_TYPE)
10:50:05.020 - I vrild [NetRegService_0] rat-mode query answer
10:50:05.021 - I vrild [IpcCtx_0] OnIpcComplete Request ID=44, result=2  ⇒ builtin.common.vendor_request_failed(request_id=44,result=2)
10:50:05.021 - D vrild [IpcCtx_0] untrack seq 0x0241
10:50:05.022 p0 D ofonod [0,0511]< RIL_REQUEST_GET_PREFERRED_NETWORK_TYPE failed GENERIC_FAILURE  ⇒ ril_error(error=GENERIC_FAILURE,request=GET_PREFERRED_NETWORK_TYPE,serial=511)
10:50:05.022 - I ofonod src/radio-settings.c:radio_rat_mode_query_callback() Error during radio access mode query
10:50:05.023 p0 I ofonod src/dbus.c:__ofono_error_failed() dbus_trace err return - i:org.ofono.RadioSettings m:GetProperties p:/ril_0
10:50:05.025 - I mgmtd load rat mode failed slot=0: Operation failed
10:50:05.100 p0 I ofonod [0,UNSOL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED (state: ON)
10:50:06.200 - I vrild [NetRegService_0] signal update nr rsrp=-89

## 모뎀 모듈 줄
10:50:02.050 p0 I ofonod [0,UNSOL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED (state: UNAVAILABLE)
10:50:02.060 - I ofonod plugins/ril.c:ril_radio_state_changed() radio unavailable
10:50:05.025 - I mgmtd load rat mode failed slot=0: Operation failed
10:50:05.100 p0 I ofonod [0,UNSOL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED (state: ON)
