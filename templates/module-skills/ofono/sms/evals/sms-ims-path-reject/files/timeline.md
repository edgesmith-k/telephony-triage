# MOCK-9502 모듈 타임라인 (ofono/sms, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sms, 중심: 2026-09-21T10:30:05.000Z (발생 시각), 구간: 파일 전체
- 줄: 7/18 (잡음 7, 반복 접음 0), ±15초 다른 모듈 경고·오류: ims 2
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/cbs.c · SMS_ACKNOWLEDGE · UNSOL_RESPONSE_NEW_SMS · VIPC_EXAMPLE_SMSC_QUERY · ExampleSmsService
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-09-21T10:30:00.010Z ~ 2026-09-21T10:30:10.000Z, 줄 25, 모양 18개 중 18개. 기준 시각: 2026-09-21T10:30:05.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

10:30:05.011 - E imsd [SLOT_0][E] 4103 [ExampleImsSmsSender::sendSms] failed to build SMS-SUBMIT ref=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.018 - I mgmtd sms send error: Operation failed path/example_sms.go:12  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.012 - D imsd [SLOT_0][I] 4104 [ExampleImsSmsManager] exampleSendSmsResult() ref=1 result=FAIL  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.015 - I ofonod src/sms.c:tx_finished() send failed, giving up  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.016 p0 I ofonod src/dbus.c:__ofono_error_failed() dbus_trace err return - i:org.ofono.MessageManager m:SendMessage p:/ril_0  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.002 p0 I mgmtd dbus -> org.ofono.MessageManager.SendMessage on /ril_0 path/example_dbus.go:24  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.004 p0 I ofonod dbus_trace method call - i:org.ofono.MessageManager m:SendMessage p:/ril_0 a:"<MSISDN#1>", <HEXDUMP 20B>  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.005 - D ofonod src/sms.c:sms_send_message() queued msg 1, route ims smsOverLteCapable=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.006 - I ofonod src/ims.c:example_send_sms() IMS_REQUEST_SEND_SMS ref=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.008 - D imsd [SLOT_0][I] 4101 [ExampleImsSmsManager] exampleOnSendSmsRequest() ref=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.009 - D imsd [SLOT_0][I] 4102 [ExampleImsSmsSender::sendSms] start ref=1 format=3gpp  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.014 - I ofonod src/ims.c:example_sms_result() IMS_UNSOL_SMS_RESULT ref=1 result=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:10.000 - D imsd [SLOT_0][I] 4105 [ExampleImsRegistration] registered:1 VoPS=1  〔script 모양 1줄, 기준 뒤 첫 등장〕
10:30:05.000 - I mgmtd sms send requested to=<MSISDN#1> len=20 path/example_sms.go:24  〔script 모양 1줄〕
10:30:00.010 - I mgmtd ui tick  〔script 모양 4줄, 10:30:00.010~10:30:08.010〕
10:30:00.200 - I vrild [ExampleRegService_0] signal update lte rsrp=-92  〔script 모양 4줄, 10:30:00.200~10:30:09.200〕
10:30:01.000 - I ofonod IMSD 0: <HEXDUMP 32B>  〔script 모양 2줄, 10:30:01.000~10:30:07.000〕
10:30:01.500 - I ofonod src/ims.c:ims_set_sms_capable() IMS_UNSOL_CAPABILITIES voiceOverLteCapable=1 smsOverLteCapable=1  〔script 모양 1줄〕

## 본 타임라인

10:30:05.002 p0 I mgmtd dbus -> org.ofono.MessageManager.SendMessage on /ril_0 path/example_dbus.go:24
10:30:05.005 - D ofonod src/sms.c:sms_send_message() queued msg 1, route ims smsOverLteCapable=1
10:30:05.011 - E imsd [SLOT_0][E] 4103 [ExampleImsSmsSender::sendSms] failed to build SMS-SUBMIT ref=1
10:30:05.012 - D imsd [SLOT_0][I] 4104 [ExampleImsSmsManager] exampleSendSmsResult() ref=1 result=FAIL
10:30:05.015 - I ofonod src/sms.c:tx_finished() send failed, giving up
10:30:05.016 p0 I ofonod src/dbus.c:__ofono_error_failed() dbus_trace err return - i:org.ofono.MessageManager m:SendMessage p:/ril_0
10:30:05.018 - I mgmtd sms send error: Operation failed path/example_sms.go:12

## 다른 모듈 줄 (±15초, 경고·오류)
10:30:05.012 - D imsd [SLOT_0][I] 4104 [ExampleImsSmsManager] exampleSendSmsResult() ref=1 result=FAIL

## 이상 줄: W/E/F 레벨, 오류 문구, 예외 (태그 규칙과 상관없이 스크립트가 마스킹 사본에서 고름, 레벨을 믿지 않는 태그는 오류 문구로 고름)

- 범위: 2026-09-21T10:25:05.000Z ~ 2026-09-21T10:40:05.000Z (분석 구간 끝과 기준 시각 2026-09-21T10:30:05.000Z 뒤 600초 중 늦은 쪽까지).
- 줄: 2. 프레임을 뺀 후보 2줄에서 F, 예외·crash 머리, E, 레벨을 믿지 않는 줄의 오류 문구, W 순으로, 같은 등급은 기준 시각에 가까운 순으로 골랐다. 예외 머리 뒤에는 프레임 2줄을 붙이고 숫자만 다른 반복은 접었다. 형식은 위와 같다

10:30:05.011 - E imsd [SLOT_0][E] 4103 [ExampleImsSmsSender::sendSms] failed to build SMS-SUBMIT ref=1
10:30:05.018 - I mgmtd sms send error: Operation failed path/example_sms.go:12
