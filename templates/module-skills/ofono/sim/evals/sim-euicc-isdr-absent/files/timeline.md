# MOCK-9202 모듈 타임라인 (ofono/sim, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sim, 중심: 2026-02-27T17:27:50+00:00 (발생 시각), 구간: 파일 전체
- 줄: 42/42 (잡음 11, 반복 접음 5), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): ipad · src/simfs.c · SIM_IO · GET_SIM_STATUS · GET_SIM_PIN_PUK_RETRIES
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

17:27:50.347 - D LPA tid:10 Procedures.cpp(304):runProcedure > runProcedure(BEG)
17:27:50.347 - D LPA tid:10 es10c.cpp(274):getEIDProc > GetEIDProc
17:27:50.347 - D LPA tid:10 DBusClient.cpp(174):transmitAPDU > needRefresh: 0
17:27:50.347 - D LPA tid:10 DBusClient.cpp(164):waitForSimManager > Waited for sim manager for 0s  〔script: 같은 줄 ×2〕
17:27:50.347 - D LPA tid:10 DBusClient.cpp(93):openChannel > Open channel called  〔script: 같은 줄 ×2〕
17:27:50.348 p0 I ofonod dump_dmsg method call - i:org.ofono.SimManager m:OpenChannel p:/ril_0 a:"<AID#1>", 0
17:27:50.348 - D ofonod src/sim.c:sim_open_channel()  〔script: 반복 ×2 17:27:50~17:27:50; 같은 줄 ×2〕
17:27:50.348 - D ofonod drivers/rilmodem/sim.c:ril_open_channel_with_p2()  〔script: 반복 ×2 17:27:50~17:27:50; 같은 줄 ×2〕
17:27:50.348 p0 I ofonod [0,0185]> RIL_REQUEST_SIM_OPEN_CHANNEL OPEN CHANNEL with p2 (AID:<AID#1>) (P2:0)  〔script: 반복 ×2 17:27:50~17:27:50〕
17:27:50.348 - D exynos-ril SOCKET RIL_SOCKET_1 REQUEST: SIM_OPEN_CHANNEL length:84  〔script: 반복 ×2 17:27:50~17:27:50〕
17:27:50.348 - I exynos-ril getCommandInfo found {request=115 halVer=00}  〔script: 같은 줄 ×2〕
17:27:50.348 - I exynos-ril [RilContext_0] OnRequest
17:27:50.348 - D exynos-ril [RilContext_0] SendMessage RIL Request Routing : RCM ID=115 Service ID=3 Message ID=2029 delayMillis=0
17:27:50.349 - I exynos-ril [SimService_0] OpenSimChannelHandler OnRequest()
17:27:50.349 - I exynos-ril AID=<AID#1>, P2=0x00
17:27:50.349 - D exynos-ril [RilContext_0] RecordRequestHistory token=0x00CB
17:27:50.349 - I exynos-ril [RilContext_0] Send
17:27:50.349 - D exynos-ril [<DEV#1>][TX] SIT_OPEN_SIM_CHANNEL_WITH_P2, REQ, 30 bytes, Token(0x00cb)
17:27:50.381 - D exynos-ril [<DEV#1>][RX] SIT_OPEN_SIM_CHANNEL_WITH_P2, RSP, 276 bytes, Token(0x00cb), Error(RCM_E_NO_SUCH_ELEMENT)  ⇒ builtin.common.vendor_ipc_error(error=RCM_E_NO_SUCH_ELEMENT,ipc=SIT_OPEN_SIM_CHANNEL_WITH_P2)
17:27:50.382 - D exynos-ril [RilContext_0] ProcessModemData
17:27:50.382 - D exynos-ril WaitList::Find() found record : token=0x00CB SrcService ID =3 DestService ID=3 Result Id=2029
17:27:50.382 - I exynos-ril [SimService_0] OpenSimChannelHandler OnResponse()
17:27:50.382 - D exynos-ril Session ID : -1, uErrCode : 17
17:27:50.382 - D exynos-ril SimDataBuilder::BuildSimOpenChannelResponse() [<--
17:27:50.382 - I exynos-ril BuildSimOpenChannelResponse() sessionid : -1, sw1 : 6A, sw2 : 82, length : 0
17:27:50.382 - D exynos-ril SimDataBuilder::BuildSimOpenChannelResponse() [-->
17:27:50.382 - I exynos-ril [RilContext_0] OnRequestComplete Request ID=115, result=17  ⇒ builtin.common.vendor_request_failed(request_id=115,result=17)
17:27:50.382 - D exynos-ril RequestComplete, RIL_SOCKET_1
17:27:50.382 - D exynos-ril Send Response to RIL_SOCKET_1
17:27:50.382 - D exynos-ril [RilContext_0] RemoveRequestHistory token=0x00CB
17:27:50.382 p0 D ofonod [0,0185]< RIL_REQUEST_SIM_OPEN_CHANNEL failed NO_SUCH_ELEMENT  ⇒ ril_error(error=NO_SUCH_ELEMENT,request=SIM_OPEN_CHANNEL,serial=185)
17:27:50.382 - D ofonod drivers/rilmodem/sim.c:ril_open_channel_with_p2_cb() RILD reply failure: NO_SUCH_ELEMENT
17:27:50.382 - D ofonod drivers/rilmodem/sim.c:ril_open_channel_with_p2_cb() sim_error : 3
17:27:50.382 - D ofonod src/sim.c:sim_open_channel_with_p2_cb()
17:27:50.382 - I ofonod src/sim.c:sim_open_channel_with_p2_cb() error response : 5
17:27:50.382 p0 I ofonod src/dbus.c:__ofono_error_no_such_element() dump_dmsg err return - i:org.ofono.SimManager m:OpenChannel p:/ril_0
17:27:50.383 - E LPA tid:10 DBusClient.cpp(112):openChannel > DBusClient::openChannel: Application not found or not available on SIM
17:27:50.383 - W LPA tid:10 Procedures.cpp(602):runProcedure > getEIDProc() failed! (DBusClient::openChannel: Application not found or not available on SIM)
17:27:50.383 - D LPA tid:10 ecasd_eid.cpp(29):getEidFromECASD > getEidFromECASD
17:27:50.384 p0 I ofonod dump_dmsg method call - i:org.ofono.SimManager m:OpenChannel p:/ril_0 a:"<AID#2>", 0
17:27:50.384 p0 I ofonod [0,0186]> RIL_REQUEST_SIM_OPEN_CHANNEL OPEN CHANNEL with p2 (AID:<AID#2>) (P2:0)  〔script: 반복 ×2 17:27:50~17:27:50〕
17:27:50.384 - D exynos-ril SOCKET RIL_SOCKET_1 REQUEST: SIM_OPEN_CHANNEL length:84  〔script: 반복 ×2 17:27:50~17:27:50〕
