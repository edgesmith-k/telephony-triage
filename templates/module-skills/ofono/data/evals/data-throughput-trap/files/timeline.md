# MOCK-9106 모듈 타임라인 (ofono/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/data, 중심: 2026-09-22T09:20:02.000Z (발생 시각), 구간: 파일 전체
- 줄: 14/19 (잡음 4, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): datad · datad2 · src/lte.c · drivers/rilmodem/gprs.c · drivers/rilmodem/lte.c
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-22T09:20:00.010Z ~ 2026-09-22T09:20:31.200Z, 줄 23, 모양 16개 중 16개. 기준 시각: 2026-09-22T09:20:02.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

09:20:02.002 p0 I ofonod dbus_trace method call - i:org.ofono.ConnectionContext m:SetProperty p:/ril_0/context1 a:"Active", variant(true)  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.003 p0 D ofonod drivers/rilmodem/gprs-context.c:ril_gprs_context_activate_primary() /ril_0 context 1 activating  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.004 p0 I ofonod [0,0041]> RIL_REQUEST_SETUP_DATA_CALL 16,1,<APN#1>,0,IP  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.005 - D vrild client fd 9 VCHAN_1 REQUEST: SETUP_DATA_CALL (120 bytes)  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.006 - D vrild [IpcCtx_0] track seq 0x0241  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.006 - D vrild mux [ch0][TX] VIPC_EXAMPLE_PDN_UP, REQ seq=0x0241 len=96  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.610 - D vrild mux [ch0][RX] VIPC_EXAMPLE_PDN_UP, RSP OK(VIPC_OK) seq=0x0241 len=64  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.611 - I vrild [IpcCtx_0] OnIpcComplete Request ID=27, result=0  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.613 p0 D ofonod [0,0041]< RIL_REQUEST_SETUP_DATA_CALL {status=0,retry=-1,cid=1,active=2,type=IP,ifname=rmnet0}  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.615 - I ofonod src/gprs.c:pri_activate_callback() context 1 active on rmnet0  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.616 p0 I ofonod dbus_trace signal - i:org.ofono.ConnectionContext m:PropertyChanged p:/ril_0/context1 a:"Active", variant(true)  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.700 - D vrild mux [ch0][RX] VIPC_EXAMPLE_PDN_LIST_IND ind len=24  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:20:02.702 p0 I ofonod [0,UNSOL]< RIL_UNSOL_DATA_CALL_LIST_CHANGED [cid=1 active=2]  〔script 모양 2줄, 09:20:02.702~09:20:20.702, 기준 뒤 첫 등장〕
09:20:02.000 p0 I mgmtd dbus -> org.ofono.ConnectionContext.SetProperty on /ril_0/context1 path/example_dbus.go:12  〔script 모양 1줄〕
09:20:00.200 - I vrild [ExampleRegService_0] signal update lte rsrp=-93  〔script 모양 4줄, 09:20:00.200~09:20:31.200〕
09:20:00.010 - I mgmtd ui tick  〔script 모양 4줄, 09:20:00.010~09:20:30.010〕

## 본 타임라인

09:20:02.000 p0 I mgmtd dbus -> org.ofono.ConnectionContext.SetProperty on /ril_0/context1 path/example_dbus.go:12
09:20:02.002 p0 I ofonod dbus_trace method call - i:org.ofono.ConnectionContext m:SetProperty p:/ril_0/context1 a:"Active", variant(true)
09:20:02.003 p0 D ofonod drivers/rilmodem/gprs-context.c:ril_gprs_context_activate_primary() /ril_0 context 1 activating
09:20:02.004 p0 I ofonod [0,0041]> RIL_REQUEST_SETUP_DATA_CALL 16,1,<APN#1>,0,IP
09:20:02.005 - D vrild client fd 9 VCHAN_1 REQUEST: SETUP_DATA_CALL (120 bytes)
09:20:02.006 - D vrild [IpcCtx_0] track seq 0x0241
09:20:02.006 - D vrild mux [ch0][TX] VIPC_EXAMPLE_PDN_UP, REQ seq=0x0241 len=96
09:20:02.610 - D vrild mux [ch0][RX] VIPC_EXAMPLE_PDN_UP, RSP OK(VIPC_OK) seq=0x0241 len=64
09:20:02.611 - I vrild [IpcCtx_0] OnIpcComplete Request ID=27, result=0
09:20:02.613 p0 D ofonod [0,0041]< RIL_REQUEST_SETUP_DATA_CALL {status=0,retry=-1,cid=1,active=2,type=IP,ifname=rmnet0}
09:20:02.615 - I ofonod src/gprs.c:pri_activate_callback() context 1 active on rmnet0
09:20:02.616 p0 I ofonod dbus_trace signal - i:org.ofono.ConnectionContext m:PropertyChanged p:/ril_0/context1 a:"Active", variant(true)
09:20:02.700 - D vrild mux [ch0][RX] VIPC_EXAMPLE_PDN_LIST_IND ind len=24
09:20:02.702 p0 I ofonod [0,UNSOL]< RIL_UNSOL_DATA_CALL_LIST_CHANGED [cid=1 active=2]
