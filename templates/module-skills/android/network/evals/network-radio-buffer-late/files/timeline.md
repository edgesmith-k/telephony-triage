# MOCK-9807 모듈 타임라인 (android/network, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/network, 중심: 2026-10-16T06:12:33.000Z (발생 시각), 구간: 파일 전체
- 줄: 7/9 (잡음 1, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): DATA_REGISTRATION_STATE · OPERATOR · GET_CELL_INFO_LIST · SET_ALLOWED_NETWORK_TYPES_BITMAP · IS_N1_MODE_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-10-16T06:12:31.207Z ~ 2026-10-16T06:12:33.920Z, 줄 12, 모양 12개 중 12개. 기준: 2026-10-16T06:12:33.000Z
- 모양은 슬롯·레벨과 숫자를 #로 바꾼 태그·메시지다. 줄 수는 로그 전체에서 셌다. 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 모양, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 순서는 고른 순서이고 줄은 그 모양의 첫 줄이다

06:12:33.912 - W BestClock java.time.DateTimeException: No network time available  〔script 모양 1줄, 기준 뒤 첫 등장〕
06:12:33.904 - V RIL [VrilRouter] reply msg=2204 to ExampleRegService_0  〔script 모양 1줄, 기준 뒤 첫 등장〕
06:12:33.911 - D CellularNetworkService No access tech specific info passes for RegStateResult  〔script 모양 1줄, 기준 뒤 첫 등장〕
06:12:33.913 p0 D RILJ [0612]< VOICE_REGISTRATION_STATE RegStateResult{regState: NOT_REG_MT_NOT_SEARCHING_OP, rat: UNKNOWN, reasonForDenial: NONE, cellIdentity: CellIdentity.noinit(f…  〔script 모양 1줄, 기준 뒤 첫 등장〕
06:12:33.914 p0 D NRM-C-0 onRequestNetworkRegistrationInfoComplete result: 0, info: NetworkRegistrationInfo{ domain=CS transportType=WWAN registrationState=NOT_REG_OR_SEARCHING roamingT…  〔script 모양 1줄, 기준 뒤 첫 등장〕
06:12:33.920 p0 D RILJ [0611]< QUERY_NETWORK_SELECTION_MODE {0} [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
06:12:31.281 - I VRIL-IMS [adapter] stack start sim=0 type=1 slot=1  〔script 모양 1줄〕
06:12:31.275 - D SatelliteController EVENT_RADIO_STATE_CHANGED: radioState=1  〔script 모양 1줄〕
06:12:31.262 - V VRIL radio state changed: newState=RADIO_ON  〔script 모양 1줄〕
06:12:31.208 - V VRIL [UNSL]< OEM_UNSOL_RADIO_STATE_CHANGED [SUB1]  〔script 모양 1줄〕
06:12:31.208 - V VRIL radio state changed: newState=RADIO_OFF  〔script 모양 1줄〕
06:12:31.207 - D VRIL unsol received for slot 1  〔script 모양 1줄〕

## 본 타임라인

06:12:31.208 - V VRIL [UNSL]< OEM_UNSOL_RADIO_STATE_CHANGED [SUB1]
06:12:31.208 - V VRIL radio state changed: newState=RADIO_OFF
06:12:31.262 - V VRIL radio state changed: newState=RADIO_ON
06:12:33.911 - D CellularNetworkService No access tech specific info passes for RegStateResult
06:12:33.913 p0 D RILJ [0612]< VOICE_REGISTRATION_STATE RegStateResult{regState: NOT_REG_MT_NOT_SEARCHING_OP, rat: UNKNOWN, reasonForDenial: NONE, cellIdentity: CellIdentity.noinit(f…
06:12:33.914 p0 D NRM-C-0 onRequestNetworkRegistrationInfoComplete result: 0, info: NetworkRegistrationInfo{ domain=CS transportType=WWAN registrationState=NOT_REG_OR_SEARCHING roamingT…
06:12:33.920 p0 D RILJ [0611]< QUERY_NETWORK_SELECTION_MODE {0} [PHONE0]

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-10-16T06:07:33.000Z ~ 2026-10-16T06:22:33.000Z (분석 구간 끝과 기준 시각 2026-10-16T06:12:33.000Z 뒤 600초 중 늦은 쪽까지).
- 기준: 2026-10-16T06:12:33.000Z
- 줄: 1. 프레임을 뺀 후보 1줄에서 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 줄, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

06:12:33.912 - W BestClock java.time.DateTimeException: No network time available
