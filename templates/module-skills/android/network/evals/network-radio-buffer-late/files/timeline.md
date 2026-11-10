# MOCK-9807 모듈 타임라인 (android/network, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/network, 중심: 2026-10-16T06:12:33+00:00 (발생 시각), 구간: 파일 전체
- 줄: 7/9 (잡음 1, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): DATA_REGISTRATION_STATE · OPERATOR · GET_CELL_INFO_LIST · SET_ALLOWED_NETWORK_TYPES_BITMAP · IS_N1_MODE_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

06:12:31.208 - V VRIL [UNSL]< OEM_UNSOL_RADIO_STATE_CHANGED [SUB1]
06:12:31.208 - V VRIL radio state changed: newState=RADIO_OFF
06:12:31.262 - V VRIL radio state changed: newState=RADIO_ON
06:12:33.911 - D CellularNetworkService No access tech specific info passes for RegStateResult
06:12:33.913 p0 D RILJ [0612]< VOICE_REGISTRATION_STATE RegStateResult{regState: NOT_REG_MT_NOT_SEARCHING_OP, rat: UNKNOWN, reasonForDenial: NONE, cellIdentity: CellIdentity.noinit(f…
06:12:33.914 p0 D NRM-C-0 onRequestNetworkRegistrationInfoComplete result: 0, info: NetworkRegistrationInfo{ domain=CS transportType=WWAN registrationState=NOT_REG_OR_SEARCHING roamingT…
06:12:33.920 p0 D RILJ [0611]< QUERY_NETWORK_SELECTION_MODE {0} [PHONE0]
