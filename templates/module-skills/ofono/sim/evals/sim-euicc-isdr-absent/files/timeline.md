# MOCK-9202 모듈 타임라인 (ofono/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sim, 중심: 2026-09-22T10:10:20.000Z (발생 시각), 구간: 파일 전체
- 줄: 23/23 (잡음 1, 반복 접음 2), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/simfs.c · SIM_IO · GET_SIM_STATUS · GET_SIM_PIN_PUK_RETRIES · SIM_AUTHENTICATION
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-22T10:10:19.318Z ~ 2026-09-22T10:10:22.418Z, 줄 26, 모양 19개 중 19개. 기준: 2026-09-22T10:10:20.000Z
- 모양은 슬롯·레벨과 숫자를 #로 바꾼 태그·메시지다. 줄 수는 로그 전체에서 셌다. 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 모양, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 순서는 고른 순서이고 줄은 그 모양의 첫 줄이다

10:10:19.463 - E simd tid:36 ExampleSim.cpp(32):ExampleChannelOpen > openChannel: Application not found (aid <AID#1>, slot 0)  〔script 모양 1줄〕
10:10:19.468 - I mgmtd GetEID call error: Failed to get EID path/example_sim.go:12  〔script 모양 1줄〕
10:10:19.464 - W simd tid:36 ExampleSim.cpp(38):ExampleGetEid > GetEID FAILED  〔script 모양 2줄, 10:10:19.464~10:10:21.460〕
10:10:19.462 - I ofonod src/dbus.c:__ofono_error_not_found() m:ExampleOpenChannel i:org.ofono.SimManager  〔script 모양 2줄, 10:10:19.462~10:10:21.459〕
10:10:19.461 - D ofonod drivers/rilmodem/sim.c:example_open_channel_cb() reply failure: NO_SUCH_ELEMENT  〔script 모양 1줄〕
10:10:19.460 p0 D ofonod [0,0745]< RIL_REQUEST_SIM_OPEN_CHANNEL failed NO_SUCH_ELEMENT  〔script 모양 2줄, 10:10:19.460~10:10:21.458〕
10:10:19.458 - D vrild mux [ch1][RX] VIPC_EXAMPLE_CARD_OPEN, RSP Error(VIPC_E_NO_SUCH_ELEMENT) seq=0x08d4 len=12, 35 ms  〔script 모양 2줄, 10:10:19.458~10:10:21.456〕
10:10:19.459 - I vrild [ExampleIccService_1] open-channel answer: no session, sw1 : 6A, sw2 : 82  〔script 모양 2줄, 10:10:19.459~10:10:21.457〕
10:10:19.459 - I vrild [IpcCtx_2] OnIpcComplete Request ID=93, result=17 -> chan 2 reply sent, 0 waiters, took 37 ms  〔script 모양 1줄〕
10:10:19.423 - D vrild mux [ch1][TX] VIPC_EXAMPLE_CARD_OPEN seq=0x08d4 len=20  〔script 모양 2줄, 10:10:19.423~10:10:21.421〕
10:10:19.422 - D vrild client fd 9 VCHAN_2 REQUEST: SIM_OPEN_CHANNEL (20 bytes)  〔script 모양 1줄〕
10:10:19.422 - I vrild [ExampleIccService_1] open-channel start, p2 0x00  〔script 모양 1줄〕
10:10:19.421 p0 I ofonod [0,0745]> RIL_REQUEST_SIM_OPEN_CHANNEL (AID:<AID#1>) (P2:0)  〔script 모양 2줄, 10:10:19.421~10:10:21.420〕
10:10:19.420 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#1>  〔script 모양 1줄〕
10:10:19.419 - I simd tid:36 ExampleSim.cpp(26):ExampleChannelOpen > open channel aid <AID#1>  〔script 모양 1줄〕
10:10:19.418 - I simd tid:36 ExampleSim.cpp(20):ExampleGetEid > GetEID begin  〔script 모양 1줄〕
10:10:19.318 - I mgmtd GetEID requested from settings path/example_sim.go:36  〔script 모양 1줄〕
10:10:21.418 - I simd tid:36 ExampleSim.cpp(44):ExampleChannelOpen > open channel aid <AID#1> (retry)  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:10:22.418 - I mgmtd ui tick  〔script 모양 1줄, 기준 뒤 첫 등장〕

## 본 타임라인

10:10:19.318 - I mgmtd GetEID requested from settings path/example_sim.go:36
10:10:19.418 - I simd tid:36 ExampleSim.cpp(20):ExampleGetEid > GetEID begin
10:10:19.419 - I simd tid:36 ExampleSim.cpp(26):ExampleChannelOpen > open channel aid <AID#1>
10:10:19.420 p0 D ofonod src/sim.c:example_open_channel() /ril_0 aid <AID#1>
10:10:19.421 p0 I ofonod [0,0745]> RIL_REQUEST_SIM_OPEN_CHANNEL (AID:<AID#1>) (P2:0)  〔script: 반복 ×2 10:10:19~10:10:21〕
10:10:19.422 - D vrild client fd 9 VCHAN_2 REQUEST: SIM_OPEN_CHANNEL (20 bytes)
10:10:19.422 - I vrild [ExampleIccService_1] open-channel start, p2 0x00
10:10:19.423 - D vrild mux [ch1][TX] VIPC_EXAMPLE_CARD_OPEN seq=0x08d4 len=20
10:10:19.458 - D vrild mux [ch1][RX] VIPC_EXAMPLE_CARD_OPEN, RSP Error(VIPC_E_NO_SUCH_ELEMENT) seq=0x08d4 len=12, 35 ms  ⇒ builtin.common.vendor_ipc_error(error=VIPC_E_NO_SUCH_ELEMENT,ipc=VIPC_EXAMPLE_CARD_OPEN)
10:10:19.459 - I vrild [ExampleIccService_1] open-channel answer: no session, sw1 : 6A, sw2 : 82
10:10:19.459 - I vrild [IpcCtx_2] OnIpcComplete Request ID=93, result=17 -> chan 2 reply sent, 0 waiters, took 37 ms  ⇒ builtin.common.vendor_request_failed(request_id=93,result=17)
10:10:19.460 p0 D ofonod [0,0745]< RIL_REQUEST_SIM_OPEN_CHANNEL failed NO_SUCH_ELEMENT  ⇒ ril_error(error=NO_SUCH_ELEMENT,request=SIM_OPEN_CHANNEL,serial=745)  〔script: 반복 ×2 10:10:19~10:10:21〕
10:10:19.461 - D ofonod drivers/rilmodem/sim.c:example_open_channel_cb() reply failure: NO_SUCH_ELEMENT
10:10:19.462 - I ofonod src/dbus.c:__ofono_error_not_found() m:ExampleOpenChannel i:org.ofono.SimManager  〔script: 반복 ×2 10:10:19~10:10:21; 같은 줄 ×2〕
10:10:19.463 - E simd tid:36 ExampleSim.cpp(32):ExampleChannelOpen > openChannel: Application not found (aid <AID#1>, slot 0)
10:10:19.464 - W simd tid:36 ExampleSim.cpp(38):ExampleGetEid > GetEID FAILED  〔script: 반복 ×2 10:10:19~10:10:21; 같은 줄 ×2〕
10:10:19.468 - I mgmtd GetEID call error: Failed to get EID path/example_sim.go:12
10:10:21.418 - I simd tid:36 ExampleSim.cpp(44):ExampleChannelOpen > open channel aid <AID#1> (retry)
10:10:21.420 p0 I ofonod [0,0746]> RIL_REQUEST_SIM_OPEN_CHANNEL (AID:<AID#1>) (P2:0)  〔script: 반복 ×2 10:10:19~10:10:21〕
10:10:21.421 - D vrild mux [ch1][TX] VIPC_EXAMPLE_CARD_OPEN seq=0x08d5 len=20
10:10:21.456 - D vrild mux [ch1][RX] VIPC_EXAMPLE_CARD_OPEN, RSP Error(VIPC_E_NO_SUCH_ELEMENT) seq=0x08d5 len=12, 35 ms  ⇒ builtin.common.vendor_ipc_error(error=VIPC_E_NO_SUCH_ELEMENT,ipc=VIPC_EXAMPLE_CARD_OPEN)
10:10:21.457 - I vrild [ExampleIccService_1] open-channel answer: no session, sw1 : 6A, sw2 : 82
10:10:21.458 p0 D ofonod [0,0746]< RIL_REQUEST_SIM_OPEN_CHANNEL failed NO_SUCH_ELEMENT  ⇒ ril_error(error=NO_SUCH_ELEMENT,request=SIM_OPEN_CHANNEL,serial=746)  〔script: 반복 ×2 10:10:19~10:10:21〕

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-09-22T10:05:20.000Z ~ 2026-09-22T10:20:20.000Z (분석 구간 끝과 기준 시각 2026-09-22T10:10:20.000Z 뒤 600초 중 늦은 쪽까지).
- 기준: 2026-09-22T10:10:20.000Z
- 줄: 3. 프레임을 뺀 후보 4줄에서 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 줄, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

10:10:19.463 - E simd tid:36 ExampleSim.cpp(32):ExampleChannelOpen > openChannel: Application not found (aid <AID#1>, slot 0)
10:10:19.464 - W simd tid:36 ExampleSim.cpp(38):ExampleGetEid > GetEID FAILED  〔script 비슷한 줄 1번 더 접음(10:10:19.464~10:10:21.460)〕
10:10:19.468 - I mgmtd GetEID call error: Failed to get EID path/example_sim.go:12
