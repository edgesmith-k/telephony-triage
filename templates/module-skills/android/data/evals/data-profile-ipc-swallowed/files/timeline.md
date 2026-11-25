# MOCK-9803 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-10-15T07:05:12.000Z (발생 시각), 구간: 파일 전체
- 줄: 16/16 (잡음 12, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SETUP_DATA_CALL · DEACTIVATE_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_USER_DATA_ENABLED · SET_USER_DATA_ROAMING_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-10-15T07:05:12.402Z ~ 2026-10-15T07:05:12.472Z, 줄 28, 모양 20개 중 20개. 기준: 2026-10-15T07:05:12.000Z
- 모양은 슬롯·레벨과 숫자를 #로 바꾼 태그·메시지다. 줄 수는 로그 전체에서 셌다. 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 모양, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 순서는 고른 순서이고 줄은 그 모양의 첫 줄이다

07:05:12.410 - E VRIL reply to client token 418  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.437 - E RIL waitlist miss seq 0x0d31  〔script 모양 2줄, 07:05:12.437~07:05:12.472, 기준 뒤 첫 등장〕
07:05:12.471 - V RIL ipc[0][RX] VIPC_EXAMPLE_PROFILE, RSP Error(VIPC_E_FAILURE) seq=0x0d32 len=12  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.402 p0 D RILJ [0418]> SET_DATA_PROFILE with data profiles : [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.404 - D VRIL-SVC RadioDataProxy::setDataProfile: serial 418  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.405 - D VRIL-SVC setDataProfile request: serial 418  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.405 - I RIL VrilApp::instance  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.406 - I RIL [IpcCtx_0] OnRequest  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.406 - V RIL [IpcCtx_0] route req id=44 svc=3 msg=1210  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.407 - I RIL [ExamplePdnService_0] set data profile begin  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.407 - V RIL [ExamplePdnService_0] profile 1 of 2 type=ims  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.408 - V RIL ipc[0][TX] VIPC_EXAMPLE_PROFILE, REQ seq=0x0d31 len=180  〔script 모양 2줄, 07:05:12.408~07:05:12.409, 기준 뒤 첫 등장〕
07:05:12.410 - D VRIL-SVC setDataProfile response: serial 418  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.412 p0 D RILJ [0418]< SET_DATA_PROFILE [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.413 p0 D DSM-C-0 onSetDataProfileComplete. resultCode = 0  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.415 p0 D DNC-0 Data evaluation: evaluation reason:SIM_LOADED, Data disallowed reasons: NOT_IN_SERVICE NO_SUITABLE_DATA_PROFILE, candidate profile=null, time=07:05:12.415, net…  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.409 - V RIL [ExamplePdnService_0] profile 2 of 2 type=emergency  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.436 - V RIL ipc[0][RX] VIPC_EXAMPLE_PROFILE, RSP OK(VIPC_OK) seq=0x0d31 len=12  〔script 모양 1줄, 기준 뒤 첫 등장〕
07:05:12.437 - I RIL [IpcCtx_0] rx frame  〔script 모양 2줄, 07:05:12.437~07:05:12.472, 기준 뒤 첫 등장〕
07:05:12.408 - V RIL <HEXDUMP 16B>  〔script 모양 6줄, 07:05:12.408~07:05:12.471, 기준 뒤 첫 등장〕

## 본 타임라인

07:05:12.402 p0 D RILJ [0418]> SET_DATA_PROFILE with data profiles : [PHONE0]
07:05:12.404 - D VRIL-SVC RadioDataProxy::setDataProfile: serial 418
07:05:12.405 - D VRIL-SVC setDataProfile request: serial 418
07:05:12.407 - I RIL [ExamplePdnService_0] set data profile begin
07:05:12.407 - V RIL [ExamplePdnService_0] profile 1 of 2 type=ims
07:05:12.408 - V RIL ipc[0][TX] VIPC_EXAMPLE_PROFILE, REQ seq=0x0d31 len=180
07:05:12.409 - V RIL [ExamplePdnService_0] profile 2 of 2 type=emergency
07:05:12.409 - V RIL ipc[0][TX] VIPC_EXAMPLE_PROFILE, REQ seq=0x0d32 len=180
07:05:12.410 - D VRIL-SVC setDataProfile response: serial 418
07:05:12.412 p0 D RILJ [0418]< SET_DATA_PROFILE [PHONE0]
07:05:12.413 p0 D DSM-C-0 onSetDataProfileComplete. resultCode = 0
07:05:12.415 p0 D DNC-0 Data evaluation: evaluation reason:SIM_LOADED, Data disallowed reasons: NOT_IN_SERVICE NO_SUITABLE_DATA_PROFILE, candidate profile=null, time=07:05:12.415, net…  ⇒ data_evaluation_rejected(reasons=NOT_IN_SERVICE NO_SUITABLE_DATA_PROFILE)
07:05:12.436 - V RIL ipc[0][RX] VIPC_EXAMPLE_PROFILE, RSP OK(VIPC_OK) seq=0x0d31 len=12
07:05:12.437 - E RIL waitlist miss seq 0x0d31
07:05:12.471 - V RIL ipc[0][RX] VIPC_EXAMPLE_PROFILE, RSP Error(VIPC_E_FAILURE) seq=0x0d32 len=12  ⇒ builtin.common.vendor_ipc_error(error=VIPC_E_FAILURE,ipc=VIPC_EXAMPLE_PROFILE)
07:05:12.472 - E RIL waitlist miss seq 0x0d32

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-10-15T07:00:12.000Z ~ 2026-10-15T07:15:12.000Z (분석 구간 끝과 기준 시각 2026-10-15T07:05:12.000Z 뒤 600초 중 늦은 쪽까지).
- 기준: 2026-10-15T07:05:12.000Z
- 줄: 2. 프레임을 뺀 후보 3줄에서 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 줄, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

07:05:12.410 - E VRIL reply to client token 418
07:05:12.437 - E RIL waitlist miss seq 0x0d31  〔script 비슷한 줄 1번 더 접음(07:05:12.437~07:05:12.472)〕
