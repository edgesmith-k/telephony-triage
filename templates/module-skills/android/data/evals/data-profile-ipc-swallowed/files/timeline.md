# MOCK-9803 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-08-09T13:11:01+00:00 (발생 시각), 구간: 파일 전체
- 줄: 26/27 (잡음 14, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SETUP_DATA_CALL · DEACTIVATE_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_USER_DATA_ENABLED · SET_USER_DATA_ROAMING_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

13:11:01.259 p0 D RILJ [0272]> SET_DATA_PROFILE with data profiles : [PHONE0]
13:11:01.259 - D ADSC OPPT switch excluded: primary phone doesn't enable the feature!
13:11:01.259 - E ADSC onEvaluateAutoDataSwitch: switch requires two active subscriptions.
13:11:01.259 p0 D RILJ [DataProfile=[ApnSetting] DEFAULT IMS, 0, null, ims, null, null, null, null, null, 0, ims, IPV4V6, IPV4V6, true, 0, false, 0, 0, 0, 0, 0, null, null, false, UN…
13:11:01.259 p0 D RILJ [DataProfile=[ApnSetting] DEFAULT EIMS, 0, null, sos, null, null, null, null, null, 0, emergency, IPV4V6, IPV4V6, true, 0, false, 0, 0, 0, 0, 0, null, null, fa…
13:11:01.260 - D RILC-AIDL_SERVICE V2_2::RadioDataProxy::setDataProfile: serial 272
13:11:01.260 - D RILC-AIDL_SERVICE SetDataProfileCommand_V2_2::onRequest: serial 272
13:11:01.260 p0 D DNC-0 Re-evaluating 20 unsatisfied network requests in 3 groups, [INTERNET|NOT_RESTRICTED|TRUSTED|NOT_VCN_MANAGED|NOT_BANDWIDTH_CONSTRAINED]-, [INTERNET|NOT_RESTRICT…
13:11:01.260 - V RIL [PsService_0] IsPossibleToPassInRadioOffState cmd 128
13:11:01.260 - I RIL SetDataProfileHandler: OnRequest() -->
13:11:01.260 - V RIL [<DEV#1>][TX] SIT_SET_DATA_PROFILE, REQ, 246 bytes, Token(0x0141)
13:11:01.261 - V RIL [<DEV#1>][TX] SIT_SET_DATA_PROFILE, REQ, 246 bytes, Token(0x0142)
13:11:01.261 - D RILC-AIDL_SERVICE SetDataProfileCommand_V2_2::onResponse: serial 272
13:11:01.261 p0 D DPM-0 Can't find any data profile that can satisfy [NetworkRequest [ BACKGROUND_REQUEST id=2, [ Transports: CELLULAR Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NO…
13:11:01.261 p0 D DNC-0 Data evaluation: evaluation reason:SIM_LOADED, Data disallowed reasons: NOT_IN_SERVICE SERVICE_OPTION_NOT_SUPPORTED NO_SUITABLE_DATA_PROFILE DATA_CONFIG_NOT_RE…  ⇒ data_evaluation_rejected(reasons=NOT_IN_SERVICE SERVICE_OPTION_NOT_SUPPORTED NO_SUITABLE_DATA_PROFILE DA…)
13:11:01.261 p0 D DPM-0 Can't find any data profile that can satisfy [NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_VCN_MANAGED&NOT_BANDWI…
13:11:01.261 p0 D RILJ [0272]< SET_DATA_PROFILE [PHONE0]
13:11:01.261 p0 D DNC-0 Data evaluation: evaluation reason:SIM_LOADED, Data disallowed reasons: NOT_IN_SERVICE SERVICE_OPTION_NOT_SUPPORTED NO_SUITABLE_DATA_PROFILE DATA_CONFIG_NOT_RE…  ⇒ data_evaluation_rejected(reasons=NOT_IN_SERVICE SERVICE_OPTION_NOT_SUPPORTED NO_SUITABLE_DATA_PROFILE DA…)
13:11:01.262 p0 D DSMGR-0 notifyDataServiceUserDataEnabled: enabled=false
13:11:01.262 p0 D DSM-C-0 notifyUserDataEnabled
13:11:01.262 p0 D DSM-C-0 onSetDataProfileComplete. resultCode = 0
13:11:01.262 p0 D DSM-I-0 notifyUserDataEnabled
13:11:01.263 - V RIL [<DEV#1>][RX] SIT_SET_DATA_PROFILE, RSP, 12 bytes, Token(0x0141), OK(RCM_E_SUCCESS)
13:11:01.263 - E RIL WaitList::Find() found record error : token=0x0141
13:11:01.264 - V RIL [<DEV#1>][RX] SIT_SET_DATA_PROFILE, RSP, 12 bytes, Token(0x0142), Error(RCM_E_GENERIC_FAILURE)  ⇒ builtin.common.vendor_ipc_error(error=RCM_E_GENERIC_FAILURE,ipc=SIT_SET_DATA_PROFILE)
13:11:01.264 - E RIL WaitList::Find() found record error : token=0x0142
