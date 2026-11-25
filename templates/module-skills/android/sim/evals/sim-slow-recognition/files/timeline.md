# MOCK-9819 모듈 타임라인 (android/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/sim, 중심: 2026-09-05T08:00:14.000Z (발생 시각), 구간: 파일 전체
- 줄: 9/12 (잡음 1, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SIM_IO · SIM_OPEN_CHANNEL · SIM_CLOSE_CHANNEL · SIM_TRANSMIT_APDU_CHANNEL · STK_SEND_TERMINAL_RESPONSE
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-05T08:00:05.000Z ~ 2026-09-05T08:00:20.000Z, 줄 13, 모양 13개 중 13개. 기준 시각: 2026-09-05T08:00:14.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

08:00:14.010 - V RIL ipc[0][RX] VIPC_EXAMPLE_CARD_STATE, RSP OK(VIPC_OK) seq=0x0210 len=40  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:14.012 - I RIL [ExampleIccService_0] sim status end errorCode=0  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:14.014 - D VRIL-SVC getIccCardStatus response: serial 320  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:14.020 p0 D RILJ [0320]< GET_SIM_STATUS [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:14.100 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED READY reason null for phone: 0 sub: 1  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:15.500 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED LOADED reason null for phone: 0 sub: 1  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:20.000 - V RIL route rsp type=0001 id=0x0703 svc=5 msg=4009  〔script 모양 1줄, 기준 뒤 첫 등장〕
08:00:05.260 p0 D RILJ [0321]< GET_SIGNAL_STRENGTH [PHONE0]  〔script 모양 1줄〕
08:00:05.200 p0 D RILJ [0321]> GET_SIGNAL_STRENGTH [PHONE0]  〔script 모양 1줄〕
08:00:05.008 - V RIL ipc[0][TX] VIPC_EXAMPLE_CARD_STATE, REQ seq=0x0210 len=8  〔script 모양 1줄〕
08:00:05.006 - I RIL [ExampleIccService_0] sim status begin  〔script 모양 1줄〕
08:00:05.004 - D VRIL-SVC RadioSimProxy::getIccCardStatus: serial 320  〔script 모양 1줄〕
08:00:05.000 p0 D RILJ [0320]> GET_SIM_STATUS [PHONE0]  〔script 모양 1줄〕

## 본 타임라인

08:00:05.000 p0 D RILJ [0320]> GET_SIM_STATUS [PHONE0]
08:00:05.004 - D VRIL-SVC RadioSimProxy::getIccCardStatus: serial 320
08:00:05.008 - V RIL ipc[0][TX] VIPC_EXAMPLE_CARD_STATE, REQ seq=0x0210 len=8
08:00:14.010 - V RIL ipc[0][RX] VIPC_EXAMPLE_CARD_STATE, RSP OK(VIPC_OK) seq=0x0210 len=40
08:00:14.012 - I RIL [ExampleIccService_0] sim status end errorCode=0
08:00:14.014 - D VRIL-SVC getIccCardStatus response: serial 320
08:00:14.020 p0 D RILJ [0320]< GET_SIM_STATUS [PHONE0]  ⇒ ril_timeout(latency_ms=9020,request=GET_SIM_STATUS,serial=320,timeout_ms=5000)
08:00:14.100 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED READY reason null for phone: 0 sub: 1  ⇒ sim_state_changed(state=READY)
08:00:15.500 - D UiccController Broadcasting intent ACTION_SIM_STATE_CHANGED LOADED reason null for phone: 0 sub: 1  ⇒ sim_state_changed(state=LOADED)
