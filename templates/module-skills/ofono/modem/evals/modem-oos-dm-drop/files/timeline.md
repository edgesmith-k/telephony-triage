# MOCK-9702 모듈 타임라인 (ofono/modem, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/modem, 중심: 2026-09-22T09:50:21.000Z (발생 시각), 구간: 파일 전체
- 줄: 7/21 (잡음 3, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/modem.c · plugins/ril.c · RADIO_POWER · UNSOL_RESPONSE_RADIO_STATE_CHANGED · VIPC_EXAMPLE_POWER
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-22T09:50:11.153Z ~ 2026-09-22T09:50:24.153Z, 줄 24, 모양 15개 중 15개. 기준: 2026-09-22T09:50:21.000Z
- 모양은 슬롯·레벨과 숫자를 #로 바꾼 태그·메시지다. 줄 수는 로그 전체에서 셌다. 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 모양, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 순서는 고른 순서이고 줄은 그 모양의 첫 줄이다

09:50:13.154 - E vrild Fail to write diag packet to host  〔script 모양 1줄〕
09:50:13.153 - W vrild diag packet dropped: host not reading, write fail  〔script 모양 3줄, 09:50:13.153~09:50:21.153〕
09:50:11.153 - D vrild mux [ch1][RX] VIPC_EXAMPLE_NO_SERVICE_IND ind len=4 (no cell)  〔script 모양 5줄, 09:50:11.153~09:50:23.153〕
09:50:21.753 - I mgmtd data and call unavailable: no service path/example_net.go:12  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:50:19.453 - I ofonod src/gprs.c:gprs_netreg_update() attached 0  〔script 모양 1줄〕
09:50:19.364 - I ofonod drivers/rilmodem/gprs.c:ril_data_reg_cb() Data RegState=NOT_REGISTERED, RejectCause=0  〔script 모양 1줄〕
09:50:19.363 p0 I ofonod [0,0527]< RIL_REQUEST_DATA_REGISTRATION_STATE  〔script 모양 1줄〕
09:50:19.354 p0 I ofonod [0,0527]> RIL_REQUEST_DATA_REGISTRATION_STATE  〔script 모양 1줄〕
09:50:11.155 p0 I ofonod [0,UNSOL]< UNSOL_RESPONSE_VOICE_NETWORK_STATE_CHANGED  〔script 모양 2줄, 09:50:11.155~09:50:19.353〕
09:50:12.153 - I mgmtd ui tick  〔script 모양 3줄, 09:50:12.153~09:50:24.153〕
09:50:15.253 - I imsd [SLOT_0][I] 8101 registered:0 VoPS=0 RAT:NONE  〔script 모양 1줄〕
09:50:11.164 - I ofonod drivers/rilmodem/network-registration.c:ril_creg_cb() Voice RegState=NOT_REGISTERED, RejectCause=0  〔script 모양 1줄〕
09:50:11.163 p0 I ofonod [0,0526]< RIL_REQUEST_VOICE_REGISTRATION_STATE  〔script 모양 1줄〕
09:50:11.156 p0 I ofonod [0,0526]> RIL_REQUEST_VOICE_REGISTRATION_STATE  〔script 모양 1줄〕
09:50:11.154 - I vrild [ExampleRegService_1] out-of-service flag set (oos=1)  〔script 모양 1줄〕

## 본 타임라인

09:50:13.153 - W vrild diag packet dropped: host not reading, write fail
09:50:13.154 - E vrild Fail to write diag packet to host
09:50:17.153 - W vrild diag packet dropped: host not reading, write fail
09:50:19.153 - D vrild mux [ch1][RX] VIPC_EXAMPLE_NO_SERVICE_IND ind len=4 (no cell)
09:50:21.153 - W vrild diag packet dropped: host not reading, write fail
09:50:21.653 - D vrild mux [ch1][RX] VIPC_EXAMPLE_NO_SERVICE_IND ind len=4 (no cell)
09:50:23.153 - D vrild mux [ch1][RX] VIPC_EXAMPLE_NO_SERVICE_IND ind len=4 (no cell)

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-09-22T09:45:21.000Z ~ 2026-09-22T10:00:21.000Z (분석 구간 끝과 기준 시각 2026-09-22T09:50:21.000Z 뒤 600초 중 늦은 쪽까지).
- 기준: 2026-09-22T09:50:21.000Z
- 줄: 2. 프레임을 뺀 후보 4줄에서 기준 앞뒤 600초 안, 로그 전체에 5번 이하 나온 드문 모양, 예외·crash 머리의 세 몫으로 나눠 골랐다(남은 몫은 다음 몫으로). 몫 안은 본 타임라인 프로세스(pid)의 줄, 드문 모양, F·예외·E·W 등급, 기준에 가까운 순이다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

09:50:13.154 - E vrild Fail to write diag packet to host
09:50:21.153 - W vrild diag packet dropped: host not reading, write fail  〔script 비슷한 줄 2번 더 접음(09:50:13.153~09:50:21.153)〕
