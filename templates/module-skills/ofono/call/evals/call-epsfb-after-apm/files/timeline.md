# MOCK-9402 모듈 타임라인 (ofono/call, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/call, 중심: 2026-09-22T09:40:20.000Z (발생 시각), 구간: 파일 전체
- 줄: 5/14 (잡음 2, 반복 접음 0), ±15초 다른 모듈 경고·오류: ims 1
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/voicecall.c · src/call-settings.c · src/call-forwarding.c · src/call-barring.c · drivers/rilmodem/voicecall.c
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-22T09:40:17.630Z ~ 2026-09-22T09:40:22.419Z, 줄 16, 모양 15개 중 15개. 기준 시각: 2026-09-22T09:40:20.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

09:40:21.429 - D vrild mux [ch1][RX] VIPC_EXAMPLE_IMS_REG_IND ind len=28  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.430 - D imsd [SLOT_0][D] 6102 slot0: OEM_UNSOL_IMS_EXAMPLE_REGISTRATION parsed -> [state : 0] sid 0  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.431 - I imsd [SLOT_0][I] 6103 registered:0  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.431 - I imsd [SLOT_0][I] 6104 EPSFB failed, notify to ExampleImsCallManager  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.459 p0 I ofonod [0,UNSOL]< IMS_UNSOL_PDN_DEACTIVATE apn_class:1  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.460 - D ofonod src/ims.c:example_pdn_deactivate() apn_class:1  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.461 p0 I ofonod [0,0414]> RIL_REQUEST_DEACTIVATE_DATA_CALL (14,2)  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.462 p0 I ofonod [0,UNSOL]< IMS_UNSOL_CAPABILITIES voiceOverLteCapable=0, emerOverLteCapable=1 smsOverLteCapable=0  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.463 p0 D ofonod src/ims.c:ims_set_voice_capable() /ril_0 voice capable 0  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.539 p0 I ofonod [0,0414]< RIL_REQUEST_DEACTIVATE_DATA_CALL  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:21.719 - I mgmtd ui volte icon off path/example_ui.go:24  〔script 모양 1줄, 기준 뒤 첫 등장〕
09:40:18.419 - I mgmtd ui tick  〔script 모양 2줄, 09:40:18.419~09:40:22.419〕
09:40:17.649 p0 I ofonod [0,0412]< IMS_REQUEST_EXAMPLE_APM  〔script 모양 1줄〕
09:40:17.631 - D imsd [SLOT_0][D] 6101 slot0 <- ofonod: IMS_REQUEST_EXAMPLE_APM serial 0412, apm on  〔script 모양 1줄〕
09:40:17.630 p0 I ofonod [0,0412]> IMS_REQUEST_EXAMPLE_APM apm_on:1  〔script 모양 1줄〕

## 본 타임라인

09:40:17.630 p0 I ofonod [0,0412]> IMS_REQUEST_EXAMPLE_APM apm_on:1
09:40:17.631 - D imsd [SLOT_0][D] 6101 slot0 <- ofonod: IMS_REQUEST_EXAMPLE_APM serial 0412, apm on
09:40:17.649 p0 I ofonod [0,0412]< IMS_REQUEST_EXAMPLE_APM
09:40:21.431 - I imsd [SLOT_0][I] 6104 EPSFB failed, notify to ExampleImsCallManager
09:40:21.462 p0 I ofonod [0,UNSOL]< IMS_UNSOL_CAPABILITIES voiceOverLteCapable=0, emerOverLteCapable=1 smsOverLteCapable=0
