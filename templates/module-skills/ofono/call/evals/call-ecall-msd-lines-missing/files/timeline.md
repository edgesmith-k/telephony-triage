# MOCK-9404 모듈 타임라인 (ofono/call, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/call, 중심: 2026-09-23T10:20:05+00:00 (발생 시각), 구간: 파일 전체
- 줄: 15/23 (잡음 3, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/call-settings.c · src/call-forwarding.c · src/call-barring.c · drivers/rilmodem/voicecall.c · UNSOL_OEM_EMERGENCY_NUMBER_LIST
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

10:20:05.002 p0 I mgmtd [DBUS_] 000303 *BusHelperImpl->CallGenericMethod dest: org.ofono objectPath: /ril_0, dbusInterface: org.ofono.VoiceCallManager, methodName Dial mgmtd/dbus/help…
10:20:05.004 p0 I ofonod dump_dmsg method call - i:org.ofono.VoiceCallManager m:Dial p:/ril_0 a:"<MSISDN#1>", "default"
10:20:05.005 - D ofonod src/voicecall.c:manager_dial() dialing
10:20:05.006 p0 I ofonod [0,0361]> RIL_REQUEST_DIAL (<MSISDN#1>,0)
10:20:05.007 - D vrild SOCKET VCHAN_1 REQUEST: DIAL length:40
10:20:05.008 - I vrild [VoiceService_0] DialHandler OnRequest()
10:20:05.008 - D vrild [IpcCtx_0] RecordIpcHistory token=0x0361
10:20:05.008 - D vrild [<DEV#1>][TX] SIT_DIAL, REQ, 36 bytes, Token(0x0361)
10:20:05.090 - D vrild [<DEV#1>][RX] SIT_DIAL, RSP, 12 bytes, Token(0x0361), OK(RCM_E_SUCCESS)
10:20:05.091 - I vrild [IpcCtx_0] OnIpcComplete Request ID=10, result=0
10:20:05.093 p0 D ofonod [0,0361]< RIL_REQUEST_DIAL
10:20:06.402 p0 I ofonod [0,UNSOL]< RIL_UNSOL_RESPONSE_CALL_STATE_CHANGED
10:20:06.404 p0 I ofonod dump_dmsg signal - i:org.ofono.VoiceCall m:PropertyChanged p:/ril_0/voicecall01 a:"State", variant("active")
10:20:46.004 p0 I ofonod [0,0362]> RIL_REQUEST_HANGUP 1
10:20:46.090 p0 D ofonod [0,0362]< RIL_REQUEST_HANGUP
