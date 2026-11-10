# MOCK-9203 모듈 타임라인 (ofono/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sim, 중심: 2026-09-22T10:20:20+00:00 (발생 시각), 구간: 파일 전체
- 줄: 17/19 (잡음 1, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/simfs.c · drivers/rilmodem/sim.c · SIM_IO · GET_SIM_STATUS · GET_SIM_PIN_PUK_RETRIES
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

10:20:18.072 - I mgmtd GetEID requested from settings
10:20:18.172 - I simd tid:42 profile list: open channel aid <AID#1>
10:20:18.173 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#1>
10:20:18.174 p0 I ofonod [0,0857]> RIL_REQUEST_SIM_OPEN_CHANNEL (AID:<AID#1>) (P2:0)
10:20:18.175 - D vrild client fd 9 VCHAN_2 REQUEST: SIM_OPEN_CHANNEL (20 bytes)
10:20:18.176 - D vrild mux [ch1][TX] SIT_SIM_OPEN_CHANNEL seq=0x09e7 len=20
10:20:18.182 - I simd tid:9 GetEID: open channel aid <AID#2>
10:20:18.183 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#2> while channel open in progress
10:20:18.184 - I ofonod src/dbus.c:__ofono_error_busy() m:ExampleOpenChannel i:org.ofono.SimManager
10:20:18.185 - E simd tid:9 open channel failed: Operation already in progress
10:20:18.186 - W simd tid:9 GetEID failed: EuiccNoResponse (eUICC not responding)
10:20:18.188 - I mgmtd GetEID call error: eUICC not responding
10:20:18.222 - D vrild mux [ch1][RX] SIT_SIM_OPEN_CHANNEL, RSP OK(RCM_E_SUCCESS) seq=0x09e7 len=12
10:20:18.223 - I vrild [SimService_1] open-channel answer: session 1, sw1 : 90, sw2 : 00
10:20:18.224 p0 I ofonod [0,0857]< RIL_REQUEST_SIM_OPEN_CHANNEL {1}
10:20:18.225 - I simd tid:42 channel 1 opened
10:20:18.603 - I simd tid:42 channel 1 closed
