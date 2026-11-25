# MOCK-9203 모듈 타임라인 (ofono/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sim, 중심: 2026-09-22T10:20:20.000Z (발생 시각), 구간: 파일 전체
- 줄: 17/19 (잡음 1, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/simfs.c · drivers/rilmodem/sim.c · SIM_IO · GET_SIM_STATUS · GET_SIM_PIN_PUK_RETRIES
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-22T10:20:18.072Z ~ 2026-09-22T10:20:21.172Z, 줄 20, 모양 20개 중 20개. 기준 시각: 2026-09-22T10:20:20.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

10:20:18.185 - E simd tid:9 ExampleSim.cpp(62):ExampleChannelOpen > open channel failed: Operation already in progress  〔script 모양 1줄〕
10:20:18.188 - W mgmtd GetEID call error: eUICC example timeout path/example_sim.go:24  〔script 모양 1줄〕
10:20:18.186 - W simd tid:9 ExampleSim.cpp(68):ExampleGetEid > GetEID failed: ExampleEuiccNoResponse (eUICC example timeout)  〔script 모양 1줄〕
10:20:21.172 - I mgmtd ui tick  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:20:18.603 - I simd tid:42 ExampleSim.cpp(80):ExampleChannelClose > channel 1 closed  〔script 모양 1줄〕
10:20:18.602 p0 I ofonod [0,0858]< RIL_REQUEST_SIM_CLOSE_CHANNEL  〔script 모양 1줄〕
10:20:18.572 p0 I ofonod [0,0858]> RIL_REQUEST_SIM_CLOSE_CHANNEL 1  〔script 모양 1줄〕
10:20:18.225 - I simd tid:42 ExampleSim.cpp(74):ExampleChannelOpen > channel 1 opened  〔script 모양 1줄〕
10:20:18.224 p0 I ofonod [0,0857]< RIL_REQUEST_SIM_OPEN_CHANNEL {1}  〔script 모양 1줄〕
10:20:18.223 - I vrild [ExampleIccService_1] open-channel answer: session 1, sw1 : 90, sw2 : 00  〔script 모양 1줄〕
10:20:18.222 - D vrild mux [ch1][RX] VIPC_EXAMPLE_CARD_OPEN, RSP OK(VIPC_OK) seq=0x09e7 len=12  〔script 모양 1줄〕
10:20:18.184 - I ofonod src/dbus.c:__ofono_error_busy() m:ExampleOpenChannel i:org.ofono.SimManager  〔script 모양 1줄〕
10:20:18.183 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#2> while channel open in progress  〔script 모양 1줄〕
10:20:18.182 - I simd tid:9 ExampleSim.cpp(56):ExampleChannelOpen > GetEID: open channel aid <AID#2>  〔script 모양 1줄〕
10:20:18.176 - D vrild mux [ch1][TX] VIPC_EXAMPLE_CARD_OPEN seq=0x09e7 len=20  〔script 모양 1줄〕
10:20:18.175 - D vrild client fd 9 VCHAN_2 REQUEST: SIM_OPEN_CHANNEL (20 bytes)  〔script 모양 1줄〕
10:20:18.174 p0 I ofonod [0,0857]> RIL_REQUEST_SIM_OPEN_CHANNEL (AID:<AID#1>) (P2:0)  〔script 모양 1줄〕
10:20:18.173 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#1>  〔script 모양 1줄〕
10:20:18.172 - I simd tid:42 ExampleSim.cpp(50):ExampleChannelOpen > profile list: open channel aid <AID#1>  〔script 모양 1줄〕
10:20:18.072 - I mgmtd GetEID requested from settings path/example_sim.go:36  〔script 모양 1줄〕

## 본 타임라인

10:20:18.072 - I mgmtd GetEID requested from settings path/example_sim.go:36
10:20:18.172 - I simd tid:42 ExampleSim.cpp(50):ExampleChannelOpen > profile list: open channel aid <AID#1>
10:20:18.173 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#1>
10:20:18.174 p0 I ofonod [0,0857]> RIL_REQUEST_SIM_OPEN_CHANNEL (AID:<AID#1>) (P2:0)
10:20:18.175 - D vrild client fd 9 VCHAN_2 REQUEST: SIM_OPEN_CHANNEL (20 bytes)
10:20:18.176 - D vrild mux [ch1][TX] VIPC_EXAMPLE_CARD_OPEN seq=0x09e7 len=20
10:20:18.182 - I simd tid:9 ExampleSim.cpp(56):ExampleChannelOpen > GetEID: open channel aid <AID#2>
10:20:18.183 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#2> while channel open in progress
10:20:18.184 - I ofonod src/dbus.c:__ofono_error_busy() m:ExampleOpenChannel i:org.ofono.SimManager
10:20:18.185 - E simd tid:9 ExampleSim.cpp(62):ExampleChannelOpen > open channel failed: Operation already in progress
10:20:18.186 - W simd tid:9 ExampleSim.cpp(68):ExampleGetEid > GetEID failed: ExampleEuiccNoResponse (eUICC example timeout)
10:20:18.188 - I mgmtd GetEID call error: eUICC example timeout path/example_sim.go:24
10:20:18.222 - D vrild mux [ch1][RX] VIPC_EXAMPLE_CARD_OPEN, RSP OK(VIPC_OK) seq=0x09e7 len=12
10:20:18.223 - I vrild [ExampleIccService_1] open-channel answer: session 1, sw1 : 90, sw2 : 00
10:20:18.224 p0 I ofonod [0,0857]< RIL_REQUEST_SIM_OPEN_CHANNEL {1}
10:20:18.225 - I simd tid:42 ExampleSim.cpp(74):ExampleChannelOpen > channel 1 opened
10:20:18.603 - I simd tid:42 ExampleSim.cpp(80):ExampleChannelClose > channel 1 closed

## 이상 줄: W/E/F 레벨과 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 빠짐)

- 범위: 2026-09-22T10:15:20.000Z ~ 2026-09-22T10:30:20.000Z (분석 구간 끝과 기준 시각 2026-09-22T10:20:20.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 3. 프레임을 뺀 후보 3줄에서 F, 예외·crash 머리, E, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

10:20:18.185 - E simd tid:9 ExampleSim.cpp(62):ExampleChannelOpen > open channel failed: Operation already in progress
10:20:18.186 - W simd tid:9 ExampleSim.cpp(68):ExampleGetEid > GetEID failed: ExampleEuiccNoResponse (eUICC example timeout)
10:20:18.188 - W mgmtd GetEID call error: eUICC example timeout path/example_sim.go:24
