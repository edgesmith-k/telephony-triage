# MOCK-9301 모듈 타임라인 (ofono/network, 심층)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/network, 중심: 2026-02-27T17:28:15.211Z (근거), 구간: 2026-02-27T17:27:45.209Z ~ 2026-02-27T17:28:20.211Z
- 줄: 30/30 (잡음 8, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): PTD · ENT · src/network.c · src/netmon.c · src/satellite.c
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

17:28:15.204 p0 I MOSE [DBUS_] 000023 *BusHelperImpl->CallGenericMethod dest: org.ofono objectPath: /ril_0, dbusInterface: org.ofono.RadioSettings, methodName GetNRMode, args [] mose…
17:28:15.205 p0 I MOSE [DBUS_] 000023 *DBusClient->Object dest: org.ofono, path: /ril_0 mose/dbus/client/dbus_client.go:135
17:28:15.206 p0 I ofonod dump_dmsg method call - i:org.ofono.RadioSettings m:GetNRMode p:/ril_0 a:no args
17:28:15.206 - D ofonod drivers/rilmodem/radio-settings.c:ril_get_nr_mode()
17:28:15.206 p0 I ofonod [0,0205]> RIL_REQUEST_GET_NR_MODE
17:28:15.206 - D exynos-ril SOCKET RIL_SOCKET_1 REQUEST: RIL_REQUEST_GET_NR_MODE length:8
17:28:15.206 - I exynos-ril getCommandInfo found {request=5047 halVer=00}
17:28:15.206 - I exynos-ril [RilContext_0] OnRequest
17:28:15.207 - D exynos-ril [RilContext_0] SendMessage RIL Request Routing : RCM ID=5047 Service ID=5 Message ID=4118 delayMillis=0
17:28:15.207 - I exynos-ril [NetworkService_0] GetNrModeHandler OnRequest()
17:28:15.207 - D exynos-ril [RilContext_0] RecordRequestHistory token=0x00E1
17:28:15.207 - I exynos-ril [RilContext_0] Send
17:28:15.207 - D exynos-ril [<DEV#1>][TX] SIT_GET_NR_MODE, REQ, 12 bytes, Token(0x00e1)
17:28:15.209 - D exynos-ril [<DEV#1>][RX] SIT_GET_NR_MODE, RSP, 12 bytes, Token(0x00e1), Error(RCM_E_GENERIC_FAILURE)  ⇒ builtin.common.vendor_ipc_error(error=RCM_E_GENERIC_FAILURE,ipc=SIT_GET_NR_MODE)
17:28:15.210 - D exynos-ril [RilContext_0] ProcessModemData
17:28:15.210 - D exynos-ril WaitList::Find() found record : token=0x00E1 SrcService ID =5 DestService ID=5 Result Id=4118
17:28:15.210 - I exynos-ril [NetworkService_0] GetNrModeHandler OnResponse()
17:28:15.210 - I exynos-ril [RilContext_0] OnRequestComplete Request ID=5047, result=2  ⇒ builtin.common.vendor_request_failed(request_id=5047,result=2)
17:28:15.210 - D exynos-ril RequestComplete, RIL_SOCKET_1
17:28:15.210 - D exynos-ril Send Response to RIL_SOCKET_1
17:28:15.210 - D exynos-ril [RilContext_0] RemoveRequestHistory token=0x00E1
17:28:15.211 p0 D ofonod [0,0205]< RIL_REQUEST_GET_NR_MODE failed GENERIC_FAILURE  ⇒ ril_error(error=GENERIC_FAILURE,request=GET_NR_MODE,serial=205)
17:28:15.211 p0 I ofonod [0,0205]< RIL_REQUEST_GET_NR_MODE GENERIC_FAILURE
17:28:15.211 - I ofonod src/radio-settings.c:radio_query_nr_mode_callback() Error during nr mode enabled query
17:28:15.211 p0 I ofonod src/dbus.c:__ofono_error_failed() dump_dmsg err return - i:org.ofono.RadioSettings m:GetNRMode p:/ril_0
17:28:15.215 p0 I MOSE [DBUS_] 000023 *BusHelperImpl->CallGenericMethod callResult: &{org.ofono /ril_0 org.ofono.RadioSettings.GetNRMode [] 0x4000096480 Operation failed [] 104 0x400…
17:28:15.215 - I MOSE _helper_impl.go:106
17:28:15.215 - I MOSE [DBUS_] 000023 *BusHelperImpl->CallGenericMethod call error Operation failed mose/dbus/helper/dbus_helper_impl.go:109
17:28:15.215 - I MOSE [CRADIO_] 000023 *RadioCommon->loadNrMode SlotId:0, Load data failed err: Operation failed mose/managers/service/base/radio_common.go:86
17:28:15.215 - I MOSE [CRADIO_] 000023 *RadioCommon->loadVoNrCapa slotId: 0 mose/managers/service/base/radio_common.go:107
