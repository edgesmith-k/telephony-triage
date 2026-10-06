# logcat 태그 참고

로그를 해석할 때 참고한다. **판별 기준은 이슈 DB `parser-rules/tags.yaml`이다** — 여기 표는 해석 보조일 뿐이고, 새 태그를 시그니처에
쓰려면 `tags.yaml`에 있어야 한다(없으면 파서가 그 줄을 버린다, `db-authoring.md` §4 파서 규칙).

데이터 스택은 **Android 13+ 형식으로 확정**이다. 그 밖의 태그는 버전·벤더마다 달라 사내 실제 로그로 확인해야 하는 **예시**다(TODO(SITE:S8·S9)).
분석 리포트에서 예시 태그에 기댄 결론은 "placeholder 규칙 기반"이라고 밝힌다.

## data (Android 13+, 확정)

| 태그 | 클래스 | 볼 것 |
|---|---|---|
| `DNC-<phoneId>` | DataNetworkController | 데이터 평가 결과(`evaluation result: ALLOWED / NOT_ALLOWED reasons=[…]`), 네트워크 요청, setup 시도 |
| `DN-<name>` | DataNetwork | 개별 데이터 네트워크 상태 전이(connecting/connected/disconnecting), setup 실패 원인(DataFailCause) |
| `DPM-<phoneId>` | DataProfileManager | APN/데이터 프로파일 선택, 적합한 프로파일 없음 |
| `DRM-<phoneId>` | DataRetryManager | setup/handover 재시도 규칙과 스케줄, 재시도 중단 |
| `DSM-<phoneId>` | DataSettingsManager | 모바일 데이터·로밍 설정 변경(`onDataEnabledChanged`) |
| `DCM-<phoneId>` | DataConfigManager | carrier config 기반 데이터 설정(재시도 규칙, 금지 APN 등) |
| `DSRM-<phoneId>` | DataStallRecoveryManager | data stall 감지와 복구 단계 |

- 레거시 스택(DcTracker/DCT, DataConnection)은 고려하지 않는다.
- 평가 거부 사유(`reasons=[…]`)의 예: `DATA_DISABLED`, `ROAMING_DISABLED`, `NOT_IN_SERVICE`, `SIM_NOT_READY`, `NO_SUITABLE_DATA_PROFILE`,
  `DATA_RESTRICTED_BY_NETWORK`, `CONCURRENT_VOICE_DATA_NOT_ALLOWED`, `DATA_THROTTLED`. 실제 표기는 버전 소스의 `DataEvaluationReason`으로 확인.
- 태그 접미사 숫자가 phone id(슬롯)다. 듀얼 SIM 로그에서 슬롯을 섞어 판단하지 않는다.

## 공통

| 태그 | 볼 것 |
|---|---|
| `RILJ` | RIL 요청 `[serial]> REQUEST`, 응답 `[serial]< REQUEST … error`, unsol `[UNSL]< UNSOL_…`. 요청·응답 짝은 `(pid, phone_id, serial)` |
| `RadioResponse`, `RadioIndication` 계열 | HAL 응답·indication (버전에 따라 이름 다름) |

## call (예시)

`GsmCdmaCallTracker`, `GsmCdmaPhone`, `ImsPhoneCallTracker`, `ImsPhone`, `ImsPhoneConnection`, Telecom 계열(`Telecom`, `TelecomFramework`).
발신 시도·IMS 등록 여부, 통화 상태 전이, 종료 원인(`LAST_CALL_FAIL_CAUSE`, IMS reason info).

## network (예시)

`ServiceStateTracker`(축약 `SST`, `-<phoneId>` 접미사 가능), `NetworkRegistrationInfo` 출력, `CellularNetworkService`.
voice/data 등록 상태, reject cause, RAT, 서비스 상태(IN_SERVICE / OUT_OF_SERVICE / EMERGENCY_ONLY).

## sim (예시)

`UiccController`, `UiccSlot`, `UiccCard`/`UiccProfile`, `SubscriptionManagerService`(축약 `SMSVC`), `IccCardProxy`(구버전).
카드 상태(ABSENT/PRESENT/ERROR), 앱 상태(PIN/PUK/READY), SIM refresh, 구독 활성화.

## sms (예시)

`SmsDispatchersController`, `GsmSMSDispatcher`, `ImsSmsDispatcher`, `SMSDispatcher`, `InboundSmsHandler`/`GsmInboundSmsHandler`.
전송 경로(CS / IMS), 전송 결과·error code, 재시도, 수신 처리.

## ims (예시)

`ImsManager`, `ImsResolver`, `ImsServiceController`, `ImsRegistration`/`ImsRegistrationCallbackHelper`, 벤더 ImsService 태그.
등록/재등록/해제, 등록 실패 코드·사유, capability(VoLTE/VoWiFi/SMS over IMS) 변화, IMS PDN.

## 해석 요령

- 발생 시각 ±5분의 **마스킹된 이벤트**부터 본다. 원문을 통째로 읽지 않는다.
- "무엇이 일어나지 않았나"(요청이 안 나감)는 `must_not_match`로만 확인된다. 로그 범위(`coverage`)가 그 구간을 덮는지 먼저 본다.
- 시계 역행·점프(`clock_anomalies`)는 시각이 불연속이라는 관측 사실이다. 원인(재부팅, NITZ·NTP 갱신, 수동 시각 변경, 로그 파일 이어 붙이기,
  버퍼 회전)은 근처의 부팅·시각 갱신 로그가 있을 때만 적고, 없으면 "원인 미상"으로 둔다. 어느 쪽이든 불연속을 넘는 시각 비교에 기대는 결론은 조심한다.
