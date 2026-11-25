# MOCK-9829 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-11-20T10:00:01.000Z (발생 시각), 구간: 파일 전체
- 줄: 9/9 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): DEACTIVATE_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_DATA_PROFILE · SET_USER_DATA_ENABLED · SET_USER_DATA_ROAMING_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-11-20T10:00:00.100Z ~ 2026-11-20T10:00:05.430Z, 줄 9, 모양 8개 중 8개. 기준 시각: 2026-11-20T10:00:01.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

10:00:05.420 p0 D RILJ [0401]< SETUP_DATA_CALL DataCallResponse: { cause=NONE(0x0) retry=-1 cid=1 linkStatus=2 protocolType=2 ifname=rmnet0 addresses=[<IP#1>/64] dnses=[<IP#2>] gatew…  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:00:05.430 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:00:00.310 p0 D DRM-0 retry scheduled in 5000ms  〔script 모양 1줄〕
10:00:00.302 p0 D DNC-0 onDataNetworkSetupDataFailed: [DataNetwork: DN-100-C, <APN#1>, state=null], cause=INSUFFICIENT_RESOURCES(0x1a), retryDelayMillis=-1ms.  〔script 모양 1줄〕
10:00:00.300 p0 D RILJ [0400]< SETUP_DATA_CALL DataCallResponse: { cause=INSUFFICIENT_RESOURCES(0x1a) retry=-1 cid=-1 linkStatus=0 protocolType=2 ifname=null addresses=[] dnses=[] ga…  〔script 모양 1줄〕
10:00:00.106 p0 D RILJ [0400]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, prefer…  〔script 모양 2줄, 10:00:00.106~10:00:05.320〕
10:00:00.104 p0 D DNC-0 onSetupDataNetwork: dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, preferred=true], retryEntry=null, allowed reason=…  〔script 모양 1줄〕
10:00:00.100 p0 D DNC-0 onAddNetworkRequest: added [NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_VCN_MANAGED&NOT_BANDWIDTH_CONSTRAINED Re…  〔script 모양 1줄〕

## 본 타임라인

10:00:00.100 p0 D DNC-0 onAddNetworkRequest: added [NetworkRequest [ REQUEST id=1, [ Capabilities: INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_VCN_MANAGED&NOT_BANDWIDTH_CONSTRAINED Re…
10:00:00.104 p0 D DNC-0 onSetupDataNetwork: dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, preferred=true], retryEntry=null, allowed reason=…
10:00:00.106 p0 D RILJ [0400]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, prefer…
10:00:00.300 p0 D RILJ [0400]< SETUP_DATA_CALL DataCallResponse: { cause=INSUFFICIENT_RESOURCES(0x1a) retry=-1 cid=-1 linkStatus=0 protocolType=2 ifname=null addresses=[] dnses=[] ga…
10:00:00.302 p0 D DNC-0 onDataNetworkSetupDataFailed: [DataNetwork: DN-100-C, <APN#1>, state=null], cause=INSUFFICIENT_RESOURCES(0x1a), retryDelayMillis=-1ms.
10:00:00.310 p0 D DRM-0 retry scheduled in 5000ms
10:00:05.320 p0 D RILJ [0401]> SETUP_DATA_CALL,reason=NORMAL,accessNetworkType=EUTRAN,dataProfile=[DataProfile=[ApnSetting] <APN#1>, 1, 00101, <APN#1>, default | supl, IPV4V6, prefer…
10:00:05.420 p0 D RILJ [0401]< SETUP_DATA_CALL DataCallResponse: { cause=NONE(0x0) retry=-1 cid=1 linkStatus=2 protocolType=2 ifname=rmnet0 addresses=[<IP#1>/64] dnses=[<IP#2>] gatew…
10:00:05.430 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  ⇒ data_internet_state_changed(from=DISCONNECTED,to=CONNECTED)
