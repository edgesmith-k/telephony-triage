# MOCK-9601 모듈 타임라인 (ofono/ims, 심층)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/ims, 중심: 2026-02-27T17:28:22.032Z (근거), 구간: 2026-02-27T17:27:52.030Z ~ 2026-02-27T17:28:27.032Z
- 줄: 59/65 (잡음 6, 반복 접음 1), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): IMS_REQUEST_SET_OPERATOR_INFO · IMS_REQUEST_AIRPLANE_MODE · IMS_UNSOL_REQUEST_ACT_PDN · IMS_UNSOL_REQUEST_DEACT_PDN · IMS_UNSOL_REQUEST_GET_OPERATOR_INFO
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

17:28:21.985 p0 I ofonod [0,0012]< IMS_REQUEST_SET_PDN_INFO_EXT
17:28:21.985 - D ofonod drivers/rilmodem/ims.c:ims_setPdnInfo_cb() set_ims_pdn_info_cb was successful
17:28:22.028 - D exynos-ril [<DEV#1>][RX] SIT_IND_AIMS_REG_FAIL, IND, 10 bytes
17:28:22.029 - D exynos-ril [RilContext_0] ProcessModemData  〔script: 같은 줄 ×2〕
17:28:22.029 - I exynos-ril [ImsService_0] AimsDefaultHandler OnIndication()
17:28:22.029 - D exynos-ril [ImsService_0] AIMS Indication: msgId=8200 resultId=20359 parameter=0x0x7f74001b58 parameter length=2
17:28:22.029 - D exynos-ril [RilContext_0] OnUnsolicitedResponse Unsol Rsp ID=20359
17:28:22.029 - D exynos-ril RADIO::[RilResponseListener] OnUnsolicitedResponse Filter out Unsolicited response=20359
17:28:22.029 - I exynos-ril [OemReceiver] OnUnsolicitedResponse channel=0
17:28:22.029 - D exynos-ril [OemReceiver] unsol oem message(20359) is translated to msgId(3077)
17:28:22.030 - D IMSSVC [SLOT_0][V] 2939 [OemClient] Response received for channelId: 0; StoredChannelId: 0
17:28:22.030 - D exynos-ril [<DEV#1>][RX] <unknown sit>, IND, 82 bytes
17:28:22.030 - D IMSSVC [SLOT_0][V] 2940 getClientId() Found ClientId[0] for ChannelId[0]
17:28:22.030 - D IMSSVC [SLOT_0][V] 2941 SITRilClient__OnUnsolicitedResponse() msgId(3077), data(0x0x7f78000b70), length(2) channel(0) client(0)
17:28:22.030 - D IMSSVC [SLOT_0][V] 2942 SITRilClient__OnUnsolicitedResponse() RILC_UNSOL_AIMS_REG_FAIL msgId = 3077
17:28:22.030 - D IMSSVC [SLOT_0][V] 2943 SITRilClient__OnUnsolicitedResponse() Send unsol msg msgId = 3077, clientId = 0, channel = 0
17:28:22.030 - D IMSSVC [SLOT_0][V] 2944 [SID_0] UNSOL {RILC_UNSOL_AIMS_REG_FAIL(3077)} : 13RilIndRegFail [fail-code : 401]
17:28:22.030 - D exynos-ril [RilContext_0] SendMessage Indication: no route info for Message ID=2432
17:28:22.030 - D IMSSVC [SLOT_0][V] 2945 [13RilIndRegFail::onMessage] mFailCode : 401
17:28:22.031 - I IMSSVC [SLOT_0][I] 2946 [20RegistrationListener_0::onReceiveImsRegFail] Received IMS registration fail from CP AIMS. failCode: 401
17:28:22.031 - D IMSSVC [SLOT_0][V] 2947 RegService_0::updateImsRegFail() [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2948 RegService_0::updateImsRegFail() ########## Update IMS Reg Fail. failCode: 401
17:28:22.031 - D IMSSVC [SLOT_0][V] 2949 [RegService_0] OnUnsolicitedResponse [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2950 [ImssvcContext_0] OnUnsolicitedResponse [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2951 [ImssvcContext_0] ProcessUnsolicitedResponse [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2952 [ImssvcContext_0] ProcessUnsolicitedResponse
17:28:22.031 - D IMSSVC [SLOT_0][V] 2953 [ImssvcContext_0] ProcessUnsolicitedResponse [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2954 [ImssvcApplication] OnUnsolicitedResponse [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2955 [ImssvcApplication] OnUnsolicitedResponse [<--
17:28:22.031 - I IMSSVC [SLOT_0][I] 2956 [ImssvcResponseListener] OnUnsolicitedResponse
17:28:22.031 - D IMSSVC [SLOT_0][V] 2957 [ImssvcD] IMSSVC_onUnsolicitedResponse [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2958 [UNSL]< IMS_UNSOL_UPDATE_IMS_REG_FAIL
17:28:22.031 - D IMSSVC [SLOT_0][V] 2959 call responseFunction for id=IMS_UNSOL_UPDATE_IMS_REG_FAIL
17:28:22.031 - D IMSSVC [SLOT_0][V] 2960 [ImssvcD] responseInts [<--
17:28:22.031 - D IMSSVC [SLOT_0][V] 2961 [ImssvcD] responseInts [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2962 IMSSVC_SOCKET_1 UNSOLICITED: IMS_UNSOL_UPDATE_IMS_REG_FAIL length:16
17:28:22.031 - D IMSSVC [SLOT_0][V] 2963 [respParcel] [UNSL]< IMS_UNSOL_UPDATE_IMS_REG_FAIL {401, }
17:28:22.031 - D IMSSVC [SLOT_0][V] 2964 Send Response to socket=IMSSVC_SOCKET_1, fd=20
17:28:22.031 - D IMSSVC [SLOT_0][V] 2965 IMSSVCD Response: written=4
17:28:22.031 - D IMSSVC [SLOT_0][V] 2966 IMSSVCD Response: written=16
17:28:22.031 - D IMSSVC [SLOT_0][V] 2967 [ImssvcD] IMSSVC_onUnsolicitedResponse [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2968 [ImssvcApplication] OnUnsolicitedResponse [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2969 [ImssvcApplication] OnUnsolicitedResponse [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2970 [ImssvcContext_0] OnUnsolicitedResponse [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2971 [RegService_0] OnUnsolicitedResponse [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2972 RegService_0::updateImsRegFail() [-->
17:28:22.031 - D IMSSVC [SLOT_0][V] 2973 Unsol {3077} received
17:28:22.032 - D ofonod drivers/rilmodem/ims.c:ims_update_ims_reg_fail() fail_code = 401
17:28:22.032 p0 I ofonod [0,UNSOL]< IMS_UNSOL_UPDATE_IMS_REG_FAIL fail_code=401
17:28:22.032 - I ofonod src/ims.c:ofono_ims_reg_fail_notify()
17:28:22.125 - D IMSSVC [SLOT_0][V] 3065 RegService_0::setRegistrationState() [-->
17:28:22.125 - D IMSSVC [SLOT_0][V] 3066 RegService_0::imsRegistrationStateChanged() [-->
17:28:22.125 - I IMSSVC [SLOT_0][I] 3067 [28ImsRegistrationStateCallback_0::onStateChanged] IMS REGISTERED SUCCEEDED
17:28:22.125 - I IMSSVC [SLOT_0][I] 3068 [20RegistrationListener_0::updateImsRegFail] IMS registration successed. Notify fail code as 0
17:28:22.125 - D IMSSVC [SLOT_0][V] 3069 RegService_0::updateImsRegFail() [<--
17:28:22.128 - I IMSSVC [SLOT_0][I] 3099 VoLTECalling on
17:28:22.128 - I IMSSVC [SLOT_0][I] 3100 [19RegistrationManager_0::triggerRegistering] triggerRegistering by 2 Block:0 Prefer:CellConnectivity VoPS:1 EMC:0 RAT:NR 0 [SLID:0]
17:28:22.128 - I IMSSVC [SLOT_0][I] 3101 [19RegistrationManager_0::triggerRegistering] [IMS_REGISTERED] [Call:0] [Current:CellConnectivity VoPS:1 EMC:0 RAT:NR 0]
17:28:22.128 - I IMSSVC [SLOT_0][I] 3102 [19RegistrationManager_0::triggerRegistering] NOT SENT
