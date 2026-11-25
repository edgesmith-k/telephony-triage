# MOCK-9825 모듈 타임라인 (android/modem, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/modem, 중심: 2026-11-10T16:14:05.000Z (발생 시각), 구간: 파일 전체
- 줄: 8/51 (잡음 0, 반복 접음 4), ±15초 다른 모듈 경고·오류: network 5
- 미수집(modules.yaml 이름 중 이 로그에 없음): GET_RADIO_CAPABILITY · SET_PREFERRED_DATA_MODEM · ENABLE_MODEM · BASEBAND_VERSION · UNSOL_MODEM_RESTART
- 모듈 신호 약함: ±15초에 이 모듈 경고·오류 줄이 없고 network에 5줄이 있다
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-11-10T16:14:05.342Z ~ 2026-11-10T16:14:32.766Z, 줄 55, 모양 47개 중 47개. 기준: 2026-11-10T16:14:05.000Z
- 모양은 슬롯·레벨과 숫자를 #로 바꾼 태그·메시지다. 줄 수는 로그 전체에서 셌다. 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 모양, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 순서는 고른 순서이고 줄은 그 모양의 첫 줄이다

16:14:05.422 p0 D SST-0 handlePollStateResult exception java.lang.IllegalStateException: Service not connected.  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.422 p0 E SST-0 handlePollStateResult: RIL returned an error where it must succeed: java.lang.IllegalStateException: Service not connected.  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.381 p0 E RILJ getImsRegistrationState not supported on service NETWORK > 2.2. [PHONE0]  〔script 모양 2줄, 16:14:05.381~16:14:05.381, 기준 뒤 첫 등장〕
16:14:05.422 p0 E SST-0 handlePollStateResult: RIL returned RADIO_NOT_AVAILABLE.  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.384 p0 D RILJ [0269]< OPERATOR error 1 [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.387 p0 D RILJ [0271]< DATA_REGISTRATION_STATE error 1 [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.395 p0 D RILJ [0273]< VOICE_REGISTRATION_STATE error 1 [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.423 p0 D SST-0 pollStateDone: hasRegistered = false hasDeregistered = true hasDataAttached = {1=false, 2=false} hasDataDetached = {1=true, 2=false} hasDataRegStateChanged = {…  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.342 p0 D SST-0 setRadioPower power false forEmergencyCall false forceApply false reason 0  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.345 p0 D SST-0 setPowerStateToDesired: mDeviceShuttingDown=false, mDesiredPowerState=false, getRadioState=1, mRadioPowerOffReasons=[0], IMS reg state=false, pending radio off…  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.345 p0 D SST-0 setPowerStateToDesired: powerOffRadioSafely()  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.346 p0 D SST-0 powerOffRadioSafely: due to AIRPLANE_MODE_ON  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.350 p0 D RILJ [0265]> DEACTIVATE_DATA_CALL cid = 1 reason = SHUTDOWN [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.352 p0 D RILJ [0266]> NOTIFY_IMS_DATA_NETWORK accessNetwork=NGRAN dataNetworkState=DISCONNECTING physicalTransportType=WWAN physicalNetworkSlotIndex=0 [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.367 p0 D RILJ [0265]< DEACTIVATE_DATA_CALL [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.368 p0 D RILJ [0266]< NOTIFY_IMS_DATA_NETWORK [PHONE0]  〔script 모양 2줄, 16:14:05.368~16:14:05.375, 기준 뒤 첫 등장〕
16:14:05.346 p0 D SST-0 powerOffRadioSafely: Data is active on phone 1. Wait for all data disconnect.  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.368 p0 D RILJ [UNSL]< UNSOL_DATA_CALL_LIST_CHANGED [] [convertToString] [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.374 p0 D RILJ [0267]> NOTIFY_IMS_DATA_NETWORK accessNetwork=NGRAN dataNetworkState=DISCONNECTED physicalTransportType=WWAN physicalNetworkSlotIndex=0 [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.375 p0 D SST-0 onAnyDataNetworkExistingChanged: anyData=false anyCellularData=false  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.375 p0 D SST-0 EVENT_ALL_DATA_DISCONNECTED  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.375 p0 D SST-0 Data disconnected for all phones, turn radio off now.  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.379 p0 D RILJ [0268]> RADIO_POWER on = false forEmergencyCall= false preferredForEmergencyCall=false [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.380 p0 D RILJ [UNSL]< UNSOL_RESPONSE_NETWORK_STATE_CHANGED [PHONE0]  〔script 모양 2줄, 16:14:05.380~16:14:05.382, 기준 뒤 첫 등장〕
16:14:05.381 p0 D RILJ [UNSL]< UNSOL_RESPONSE_IMS_NETWORK_STATE_CHANGED [PHONE0]  〔script 모양 2줄, 16:14:05.381~16:14:05.382, 기준 뒤 첫 등장〕
16:14:05.381 p0 D RILJ [UNSL]< UNSOL_RESPONSE_SIM_STATUS_CHANGED [PHONE0]  〔script 모양 2줄, 16:14:05.381~16:14:32.766, 기준 뒤 첫 등장〕
16:14:05.381 p0 D RILJ [0268]< RADIO_POWER [PHONE0]  〔script 모양 2줄, 16:14:05.381~16:14:32.766, 기준 뒤 첫 등장〕
16:14:05.381 p0 D RILJ [UNSL]< UNSOL_UICC_SUBSCRIPTION_STATUS_CHANGED {0} [PHONE0]  〔script 모양 2줄, 16:14:05.381~16:14:32.766, 기준 뒤 첫 등장〕
16:14:05.381 p0 D SST-0 pollState: modemTriggered=true, radioState=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.382 p0 D RILJ [UNSL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED radioStateChanged: OFF [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.383 p0 D RILJ [0269]> OPERATOR [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.384 p0 D RILJ [0270]> QUERY_NETWORK_SELECTION_MODE [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.384 p0 D SST-0 EVENT_RADIO_POWER_OFF_DONE  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.385 p0 D RILJ [0271]> DATA_REGISTRATION_STATE [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.385 p0 D RILJ getDataRegistrationState: overrideHalVersion=null [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.387 p0 D RILJ [0273]> VOICE_REGISTRATION_STATE [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.387 p0 D RILJ getVoiceRegistrationState: overrideHalVersion=null [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.387 p0 D RILJ [0270]< QUERY_NETWORK_SELECTION_MODE {0} [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.422 p0 D SST-0 set service state as POWER_OFF  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.422 p0 D SST-0 Could not set ServiceState channel number. CellIdentity null  〔script 모양 2줄, 16:14:05.422~16:14:05.447, 기준 뒤 첫 등장〕
16:14:05.424 p0 D SST-0 RAT switched NR_SA -> Unknown at cell -1  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.445 p0 D SST-0 notifyVoiceRegStateRilRadioTechnologyChanged: vrs=3 rat=0  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:05.447 p0 D SST-0 EVENT_POLL_STATE_NETWORK_SELECTION_MODE  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:32.761 p0 D SST-0 setRadioPower power true forEmergencyCall false forceApply false reason 0  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:32.761 p0 D SST-0 setPowerStateToDesired: mDeviceShuttingDown=false, mDesiredPowerState=true, getRadioState=0, mRadioPowerOffReasons=[], IMS reg state=false, pending radio off=f…  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:32.763 p0 D RILJ [0285]> RADIO_POWER on = true forEmergencyCall= false preferredForEmergencyCall=false [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕
16:14:32.766 p0 D RILJ [UNSL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED radioStateChanged: ON [PHONE0]  〔script 모양 1줄, 기준 뒤 첫 등장〕

## 본 타임라인

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

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-11-10T16:09:05.000Z ~ 2026-11-10T16:24:05.000Z (분석 구간 끝과 기준 시각 2026-11-10T16:14:05.000Z 뒤 600초 중 늦은 쪽까지).
- 기준: 2026-11-10T16:14:05.000Z
- 줄: 4. 프레임을 뺀 후보 5줄에서 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 줄, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

16:14:05.381 p0 E RILJ getImsRegistrationState not supported on service NETWORK > 2.2. [PHONE0]  〔script 비슷한 줄 1번 더 접음(16:14:05.381)〕
16:14:05.422 p0 D SST-0 handlePollStateResult exception java.lang.IllegalStateException: Service not connected.
16:14:05.422 p0 E SST-0 handlePollStateResult: RIL returned an error where it must succeed: java.lang.IllegalStateException: Service not connected.
16:14:05.422 p0 E SST-0 handlePollStateResult: RIL returned RADIO_NOT_AVAILABLE.
