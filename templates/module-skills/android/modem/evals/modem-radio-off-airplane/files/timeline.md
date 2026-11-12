# MOCK-9825 모듈 타임라인 (android/modem, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/modem, 중심: 2026-11-10T16:14:05+00:00 (발생 시각), 구간: 파일 전체
- 줄: 8/51 (잡음 0, 반복 접음 4), ±15초 다른 모듈 경고·오류: network 5
- 미수집(modules.yaml 이름 중 이 로그에 없음): GET_RADIO_CAPABILITY · SET_PREFERRED_DATA_MODEM · ENABLE_MODEM · BASEBAND_VERSION · UNSOL_MODEM_RESTART
- 모듈 신호 약함: ±15초에 이 모듈 경고·오류 줄이 없고 network에 5줄이 있다
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

16:14:05.379 p0 D RILJ [0268]> RADIO_POWER on = false forEmergencyCall= false preferredForEmergencyCall=false [PHONE0]
16:14:05.381 p0 D RILJ [0268]< RADIO_POWER [PHONE0]
16:14:05.381 p0 E RILJ getImsRegistrationState not supported on service NETWORK > 2.2. [PHONE0]  〔script: 같은 줄 ×2〕
16:14:05.382 p0 D RILJ [UNSL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED radioStateChanged: OFF [PHONE0]
16:14:05.423 p0 D SST-0 pollStateDone: hasRegistered = false hasDeregistered = true hasDataAttached = {1=false, 2=false} hasDataDetached = {1=true, 2=false} hasDataRegStateChanged = {…  ⇒ network_service_state(deregistered=true,registered=false)
16:14:32.763 p0 D RILJ [0285]> RADIO_POWER on = true forEmergencyCall= false preferredForEmergencyCall=false [PHONE0]
16:14:32.766 p0 D RILJ [UNSL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED radioStateChanged: ON [PHONE0]
16:14:32.766 p0 D RILJ [0285]< RADIO_POWER [PHONE0]

## 다른 모듈 줄 (±15초, 경고·오류)
16:14:05.384 p0 D RILJ [0269]< OPERATOR error 1 [PHONE0]
16:14:05.387 p0 D RILJ [0271]< DATA_REGISTRATION_STATE error 1 [PHONE0]
16:14:05.395 p0 D RILJ [0273]< VOICE_REGISTRATION_STATE error 1 [PHONE0]
16:14:05.422 p0 E SST-0 handlePollStateResult: RIL returned an error where it must succeed: java.lang.IllegalStateException: Service not connected.
16:14:05.422 p0 E SST-0 handlePollStateResult: RIL returned RADIO_NOT_AVAILABLE.
