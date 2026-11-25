# MOCK-9835 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-11-20T10:00:01.000Z (발생 시각), 구간: 파일 전체
- 줄: 9/9 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): DEACTIVATE_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_DATA_PROFILE · SET_USER_DATA_ENABLED · SET_USER_DATA_ROAMING_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

10:00:00.100 p0 D DNC-0 onAddNetworkRequest: added [NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_VCN_MANAGED&NOT_BANDWIDTH_CONSTRAINED Re…
10:00:00.104 p0 D DNC-0 onSetupDataNetwork: dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, preferred=true], retryEntry=null, allowed reason=…
10:00:00.106 p0 D RILJ [0400]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, prefer…
10:00:00.300 p0 D RILJ [0400]< SETUP_DATA_CALL DataCallResponse: { cause=INSUFFICIENT_RESOURCES(0x1a) retry=-1 cid=-1 linkStatus=0 protocolType=2 ifname=null addresses=[] dnses=[] ga…
10:00:00.302 p0 D DNC-0 onDataNetworkSetupDataFailed: [DataNetwork: DN-100-C, <APN#1>, state=null], cause=INSUFFICIENT_RESOURCES(0x1a), retryDelayMillis=-1ms.
10:00:00.310 p0 D DRM-0 retry scheduled in 5000ms
10:00:05.320 p0 D RILJ [0401]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, prefer…
10:00:05.420 p0 D RILJ [0401]< SETUP_DATA_CALL DataCallResponse: { cause=NONE(0x0) retry=-1 cid=1 linkStatus=2 protocolType=2 ifname=rmnet0 addresses=[<IP#1>/64] dnses=[<IP#2>] gatew…
10:00:05.430 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  ⇒ data_internet_state_changed(from=DISCONNECTED,to=CONNECTED)

## 이상 줄: W/E/F 레벨과 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 빠짐)

- 범위: 2026-11-20T09:55:01.000Z ~ 2026-11-20T10:10:01.000Z (분석 구간 끝과 기준 시각 2026-11-20T10:00:01.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 9. 프레임을 뺀 후보 5줄에서 F, 예외·crash 머리, E, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

10:00:40.210 - E AndroidRuntime FATAL EXCEPTION: main
10:00:40.210 - E AndroidRuntime Process: com.android.phone, PID: 2101
10:00:40.210 - E AndroidRuntime java.lang.NullPointerException: Attempt to invoke virtual method 'int android.net.LinkProperties.getMtu()' on a null object reference
10:00:40.210 - E AndroidRuntime at com.android.internal.telephony.data.DataNetwork.updateLinkProperties(DataNetwork.java:2214)
10:00:40.210 - E AndroidRuntime at com.android.internal.telephony.data.DataNetwork$ConnectedState.processMessage(DataNetwork.java:1290)
10:06:12.500 - E JavaBinder *** Uncaught remote exception! (Exceptions are not yet supported across processes.)
10:06:12.500 - E JavaBinder java.lang.IllegalStateException: telephony service is not running
10:06:12.500 - E JavaBinder at com.android.server.TelephonyRegistry.notifyDataConnectionForSubscriber(TelephonyRegistry.java:1876)
10:06:12.500 - E JavaBinder at android.os.Binder.execTransact(Binder.java:1310)
