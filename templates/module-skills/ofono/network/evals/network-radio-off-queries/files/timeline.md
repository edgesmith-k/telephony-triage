# MOCK-9302 모듈 타임라인 (ofono/network, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/network, 중심: 2026-02-27T17:52:08+00:00 (발생 시각), 구간: 파일 전체
- 줄: 32/78 (잡음 16, 반복 접음 2), ±15초 다른 모듈 경고·오류: data 2
- 미수집(modules.yaml 이름 중 이 로그에 없음): ENT · src/netmon.c · src/radio-settings.c · src/ntn.c · drivers/rilmodem/netmon.c
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

17:52:03.317 p0 I ofonod [0,0576]> RIL_REQUEST_RADIO_POWER (0)
17:52:08.381 p0 I ofonod [0,UNSOL]< UNSOL_RESPONSE_RADIO_STATE_CHANGED (state: OFF)
17:52:08.381 - I ofonod src/satellite.c:satellite_online_watch() online=1
17:52:08.381 - I ofonod src/satellite.c:satellite_load_settings() loaded enabled=1
17:52:08.381 p0 I ofonod dump_dmsg signal - i:org.ofono.Modem m:PropertyChanged p:/ril_0 a:"Online", variant(false)
17:52:08.381 - I ofonod src/satellite.c:satellite_online_watch() online=0
17:52:08.382 - D PTD 99680] [NETW] [SID_0] UNSOL {RILC_UNSOL_RADIO_STATE_CHANGED(1002)} : 23RilIndRadioStateChanged [State : RADIO_OFF] [NetworkAdaptor.cpp+152]
17:52:08.382 - D PTD 99680] [ADAP] Radio state changed event received : RADIO_OFF, MsgId : 1002 [RilIndRadioStateChanged.cpp+47]
17:52:08.382 - I ofonod src/satellite.c:satellite_unregister()
17:52:08.382 - D PTD 99680] [POWE] Radio state event, modem is available [PowerService.cpp+848]
17:52:08.382 - I ofonod src/satellite.c:satellite_remove()
17:52:08.488 - I exynos-ril [RilContext_0] OnRequestComplete Request ID=19, result=1  ⇒ builtin.common.vendor_request_failed(request_id=19,result=1)
17:52:08.488 - E exynos-ril invalid response: NULL
17:52:08.488 - E exynos-ril responseFunction error, ret 66
17:52:08.491 - E exynos-ril invalid cellInfoType: 0
17:52:08.491 - I exynos-ril [NetworkService_0] OperatorHandler OnRequest()
17:52:08.491 - D exynos-ril [RilContext_0] RecordRequestHistory token=0x0284
17:52:08.491 - I exynos-ril [RilContext_0] Send
17:52:08.491 - D exynos-ril [<DEV#1>][TX] SIT_GET_OPERATOR, REQ, 12 bytes, Token(0x0284)
17:52:08.492 p0 D ofonod [0,0593]< RIL_REQUEST_SIGNAL_STRENGTH failed INVALID_RESPONSE  ⇒ ril_error(error=INVALID_RESPONSE,request=SIGNAL_STRENGTH,serial=593)
17:52:08.492 - I ofonod drivers/rilmodem/network-registration.c:ril_strength_cb() Failed to retrive the signal strength
17:52:08.492 p0 I ofonod [0,0593]< RIL_REQUEST_SIGNAL_STRENGTH INVALID_RESPONSE
17:52:08.492 - I ofonod src/network.c:signal_strength_callback() Error during signal strength query
17:52:08.492 - I ofonod drivers/rilmodem/network-registration.c:ril_dreg_cb()
17:52:08.492 - D ofonod drivers/rilmodem/network-registration.c:ril_dreg_cb() Data Reg Status=0
17:52:08.492 - D ofonod drivers/rilmodem/network-registration.c:ril_dreg_cb() tech{0} denial_reason{0} type{0}
17:52:08.492 p0 I ofonod [0,0588]< RIL_REQUEST_DATA_REGISTRATION_STATE SUCCESS status(0), tech(0), denial_reason(0), cellInfoType(0) endc(0), dcnr(0), nr_available(0), vops(0), emc(0),…
17:52:08.521 - D ofonod drivers/rilmodem/network-registration.c:ril_cops_cb()
17:52:08.521 p0 I ofonod [0,0592]< RIL_REQUEST_OPERATOR SUCCESS (lalpha=(null), salpha=(null), numeric=(null))
17:52:08.521 p0 I ofonod [0,0592]< RIL_REQUEST_OPERATOR
17:52:08.521 - D ofonod src/network.c:current_operator_callback() 0x55ac6f3fa0, (nil)
17:52:08.521 - E ofonod src/network.c:current_operator_callback() Error during current operator

## 다른 모듈 줄 (±15초, 경고·오류)
17:52:08.489 - I MOSE [DBUS_] 000053 *BusHelperImpl->CallGenericMethod call error Method "GetProperties" with signature "" on interface "org.ofono.ConnectionManager" doesn't exist m…
17:52:08.489 - I MOSE [CCONN_] 000053 *BaseCommon->loadProperties SlotId:0, Load data failed err: Method "GetProperties" with signature "" on interface "org.ofono.ConnectionManager"…
