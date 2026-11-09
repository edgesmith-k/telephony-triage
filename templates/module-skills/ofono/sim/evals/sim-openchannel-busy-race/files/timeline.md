# MOCK-9203 모듈 타임라인 (ofono/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sim, 중심: 2026-02-27T17:52:14+00:00 (발생 시각), 구간: 파일 전체
- 줄: 36/36 (잡음 12, 반복 접음 1), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/simfs.c · SIM_IO · GET_SIM_STATUS · GET_SIM_PIN_PUK_RETRIES · SIM_AUTHENTICATION
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

17:52:14.897 - D LPA tid:62 Procedures.cpp(304):runProcedure > runProcedure(BEG)
17:52:14.897 - D LPA tid:62 es10c.cpp(274):getEIDProc > GetEIDProc
17:52:14.897 - D LPA tid:62 DBusClient.cpp(174):transmitAPDU > needRefresh: 0
17:52:14.897 - D LPA tid:62 DBusClient.cpp(164):waitForSimManager > Waited for sim manager for 0s
17:52:14.897 - D LPA tid:62 DBusClient.cpp(93):openChannel > Open channel called
17:52:14.898 p0 I ofonod dump_dmsg method call - i:org.ofono.SimManager m:OpenChannel p:/ril_0 a:"<AID#1>", 0
17:52:14.898 - D ofonod src/sim.c:sim_open_channel()  〔script: 반복 ×2 17:52:14~17:52:14; 같은 줄 ×2〕
17:52:14.898 - D ofonod drivers/rilmodem/sim.c:ril_open_channel_with_p2()
17:52:14.898 p0 I ofonod [0,0608]> RIL_REQUEST_SIM_OPEN_CHANNEL OPEN CHANNEL with p2 (AID:<AID#1>) (P2:0)
17:52:14.898 - D exynos-ril SOCKET RIL_SOCKET_1 REQUEST: SIM_OPEN_CHANNEL length:84
17:52:14.898 - I exynos-ril getCommandInfo found {request=115 halVer=00}
17:52:14.899 - I exynos-ril [RilContext_0] OnRequest
17:52:14.899 - D exynos-ril [RilContext_0] SendMessage RIL Request Routing : RCM ID=115 Service ID=3 Message ID=2029 delayMillis=0
17:52:14.899 - I exynos-ril [SimService_0] OpenSimChannelHandler OnRequest()
17:52:14.899 - I exynos-ril AID=<AID#1>, P2=0x00
17:52:14.899 - D exynos-ril [RilContext_0] RecordRequestHistory token=0x0296
17:52:14.900 - I exynos-ril [RilContext_0] Send
17:52:14.900 - D exynos-ril [<DEV#1>][TX] SIT_OPEN_SIM_CHANNEL_WITH_P2, REQ, 30 bytes, Token(0x0296)
17:52:14.903 p0 I ofonod dump_dmsg method call - i:org.ofono.SimManager m:OpenChannel p:/ril_0 a:"<AID#2>", 0
17:52:14.903 p0 I ofonod src/dbus.c:__ofono_error_busy() dump_dmsg err return - i:org.ofono.SimManager m:OpenChannel p:/ril_0
17:52:14.904 - E ipad [E][tid=4216] apdu_transport.cpp:216 ipa::ApduTransport::openChannel() Failed to open logical channel: Operation already in progress (org.ofono.Error.InProgres…
17:52:14.905 - E ipad [E][tid=4216] es10b_context.cpp:71 ipa::Es10bContext::sendCommand() ES10b sendCommand: failed to open channel
17:52:14.905 - E ipad [E][tid=4216] ipad_controller.cpp:769 ipa::IpadController::getEid() GetEID: no response from eUICC
17:52:14.905 - I ipad [I][tid=4216] dbus_dump.cpp:198 ipa::logDbusError() dbus method error m:GetEID e:com.vendor.ipa.EuiccNoResponse (eUICC not responding)
17:52:14.905 - D ipad [D][tid=4216] procedure_executor.cpp:82 ipa::common::ProcedureGuard::release() Procedure released: GetEID
17:52:14.906 - I MOSE [DBUS_] 000040 *BusHelperImpl->CallGenericMethod callResult: &{com.vendor.ipa /com/vendor/ipa com.vendor.ipa.GetEID [] 0x7f6b29b880 eUICC not responding [] 465…
17:52:14.906 - I MOSE bus/helper/dbus_helper_impl.go:114
17:52:14.906 - I MOSE [DBUS_] 000040 *BusHelperImpl->CallGenericMethod call error eUICC not responding mose/dbus/helper/dbus_helper_impl.go:117
17:52:14.906 - I MOSE [IPACM] 000040 *IpaCommon->getEID Failed to get EID err: eUICC not responding mose/managers/service/base/ipa_common.go:224
17:52:14.906 - I MOSE [DBUS_] 000040 *BusHelperImpl->CallIpaServiceMethod methodName: GetDefaultSmdpAddress mose/dbus/helper/dbus_helper_impl.go:74
17:52:14.906 - I MOSE [DBUS_] 000040 *BusHelperImpl->CallGenericMethod dest: com.vendor.ipa objectPath: /com/vendor/ipa, dbusInterface: com.vendor.ipa, methodName GetDefaultSmdpAddr…
17:52:14.906 - I MOSE dbus_helper_impl.go:98
17:52:14.907 - I MOSE [DBUS_] 000040 *DBusClient->Object dest: com.vendor.ipa, path: /com/vendor/ipa mose/dbus/client/dbus_client.go:135
17:52:14.907 - I ipad [I][tid=534] dbus_dump.cpp:180 ipa::logDbusCall() dbus method call m:GetDefaultSmdpAddress a:(none)
17:52:14.907 - D ipad [D][tid=534] procedure_executor.cpp:75 ipa::common::ProcedureGuard::tryEnter() Procedure entered: GetDefaultSmdpAddress
17:52:14.908 - D ipad [D][tid=4218] es10b_context.cpp:66 ipa::Es10bContext::sendCommand() ES10b sendCommand: tag=BF3C, len=3
