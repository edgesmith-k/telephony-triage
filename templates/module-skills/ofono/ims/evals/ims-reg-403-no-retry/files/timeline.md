# MOCK-9602 모듈 타임라인 (ofono/ims, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/ims, 중심: 2026-09-21T10:40:05.000Z (발생 시각), 구간: 파일 전체
- 줄: 11/20 (잡음 7, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): IMS_REQUEST_SET_PDN_INFO · IMS_REQUEST_EXAMPLE_OPER_INFO · IMS_REQUEST_EXAMPLE_APM · IMS_UNSOL_PDN_ACTIVATE · IMS_UNSOL_PDN_DEACTIVATE
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-21T10:40:00.010Z ~ 2026-09-21T10:40:25.012Z, 줄 27, 모양 14개 중 14개. 기준 시각: 2026-09-21T10:40:05.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

10:40:05.001 - D imsd [SLOT_0][V] 5110 [SUB_0] ind <- OEM_UNSOL_IMS_EXAMPLE_REG_FAIL(3100) : [example-code : 403]  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:40:05.003 - D ofonod src/ims.c:example_reg_fail_notify() fail_code = 403  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:40:05.004 p0 I ofonod [0,UNSOL]< IMS_UNSOL_REG_FAILED fail_code=403  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:40:05.006 - D imsd [SLOT_0][I] 5102 [ExampleImsRegistration] exampleRegistrationFailed() code=403  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:40:05.007 - D imsd [SLOT_0][I] 5103 [ExampleImsRegistration] registered:0 VoPS=1  〔script 모양 3줄, 10:40:05.007~10:40:25.012, 기준 뒤 첫 등장〕
10:40:10.010 - D imsd [SLOT_0][I] 5104 [ExampleImsRegistration] exampleTriggerRegistering() NOT SENT (blocked after 403)  〔script 모양 4줄, 10:40:10.010~10:40:25.010, 기준 뒤 첫 등장〕
10:40:05.000 - D vrild mux [ch0][RX] VIPC_EXAMPLE_IMS_REG_FAIL_IND ind len=40  〔script 모양 1줄〕
10:40:00.010 - I mgmtd ui tick  〔script 모양 4줄, 10:40:00.010~10:40:18.010〕
10:40:00.200 - I vrild [ExampleRegService_0] signal update lte rsrp=-90  〔script 모양 4줄, 10:40:00.200~10:40:18.200〕
10:40:02.090 - D vrild mux [ch0][RX] VIPC_EXAMPLE_IMS_REG_REQ, RSP OK(VIPC_OK) seq=0x0201 len=12  〔script 모양 1줄〕
10:40:02.021 - D vrild mux [ch0][TX] VIPC_EXAMPLE_IMS_REG_REQ, REQ seq=0x0201 len=48  〔script 모양 1줄〕
10:40:02.020 - D imsd [SLOT_0][D] 5111 [SUB_0] req -> OEM_REQ_IMS_EXAMPLE_REGISTER len=48  〔script 모양 1줄〕
10:40:02.010 - D imsd [SLOT_0][I] 5101 [ExampleImsRegistration] exampleTriggerRegistering() SENT  〔script 모양 1줄〕
10:40:01.000 - I ofonod IMSD 0: <HEXDUMP 32B>  〔script 모양 3줄, 10:40:01.000~10:40:21.000〕

## 본 타임라인

10:40:02.010 - D imsd [SLOT_0][I] 5101 [ExampleImsRegistration] exampleTriggerRegistering() SENT
10:40:02.020 - D imsd [SLOT_0][D] 5111 [SUB_0] req -> OEM_REQ_IMS_EXAMPLE_REGISTER len=48
10:40:02.021 - D vrild mux [ch0][TX] VIPC_EXAMPLE_IMS_REG_REQ, REQ seq=0x0201 len=48
10:40:02.090 - D vrild mux [ch0][RX] VIPC_EXAMPLE_IMS_REG_REQ, RSP OK(VIPC_OK) seq=0x0201 len=12
10:40:05.000 - D vrild mux [ch0][RX] VIPC_EXAMPLE_IMS_REG_FAIL_IND ind len=40
10:40:05.001 - D imsd [SLOT_0][V] 5110 [SUB_0] ind <- OEM_UNSOL_IMS_EXAMPLE_REG_FAIL(3100) : [example-code : 403]
10:40:05.003 - D ofonod src/ims.c:example_reg_fail_notify() fail_code = 403
10:40:05.004 p0 I ofonod [0,UNSOL]< IMS_UNSOL_REG_FAILED fail_code=403
10:40:05.006 - D imsd [SLOT_0][I] 5102 [ExampleImsRegistration] exampleRegistrationFailed() code=403
10:40:05.007 - D imsd [SLOT_0][I] 5103 [ExampleImsRegistration] registered:0 VoPS=1
10:40:10.010 - D imsd [SLOT_0][I] 5104 [ExampleImsRegistration] exampleTriggerRegistering() NOT SENT (blocked after 403)
