# MOCK-9102 모듈 타임라인 (ofono/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/data, 중심: 2026-09-20T15:20:06.000Z (발생 시각), 구간: 파일 전체
- 줄: 10/13 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/lte.c · drivers/rilmodem/gprs.c · drivers/rilmodem/lte.c · DEACTIVATE_DATA_CALL · DATA_CALL_LIST
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

15:20:01.000 - I datad profile select: apn=internet.example auth=NONE profile_id=1[./src/apn_example.cxx +20]
15:20:01.050 - I mgmtd dbus call org.ofono.ConnectionContext.SetProperty Active=true path/example_dbus.go:72
15:20:01.100 p0 D ofonod drivers/rilmodem/gprs-context.c:ril_gprs_context_activate_primary() /ril_0 context 1 activating
15:20:01.120 p0 D ofonod [0,0021]> RIL_REQUEST_SETUP_DATA_CALL 16,1,internet.example,0,IP
15:20:01.700 - I vrild SETUP_DATA_CALL rsp: ok cid=1 ifname=rmnet0
15:20:01.710 p0 D ofonod [0,0021]< RIL_REQUEST_SETUP_DATA_CALL {status=0,retry=-1,cid=1,active=2,type=IP,ifname=rmnet0}
15:20:01.720 - I ofonod src/gprs.c:pri_activate_callback() context 1 active on rmnet0
15:20:01.724 - I datad2 netlink RTM_NEWROUTE failed: err=-17 (File exists) dev=rmnet0 table=1002
15:20:01.726 - I datad2 default route not installed for rmnet0
15:20:06.000 - W datad connectivity check failed profile_id=1[./src/check_example.cxx +40]

## 이상 줄: W/E/F 레벨과 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 빠짐)

- 범위: 2026-09-20T15:15:06.000Z ~ 2026-09-20T15:30:06.000Z (분석 구간 끝과 기준 시각 2026-09-20T15:20:06.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 3. 프레임을 뺀 후보 3줄에서 F, 예외·crash 머리, E, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

15:20:01.724 - E datad2 netlink RTM_NEWROUTE failed: err=-17 (File exists) dev=rmnet0 table=1002
15:20:01.726 - W datad2 default route not installed for rmnet0
15:20:06.000 - W datad connectivity check failed profile_id=1[./src/check_example.cxx +40]
