# MOCK-9502 모듈 타임라인 (ofono/sms, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: ofono/sms, 중심: 2026-09-21T10:30:05+00:00 (발생 시각), 구간: 파일 전체
- 줄: 7/18 (잡음 7, 반복 접음 0), ±15초 다른 모듈 경고·오류: ims 2
- 미수집(modules.yaml 이름 중 이 로그에 없음): src/cbs.c · SMS_ACKNOWLEDGE · UNSOL_RESPONSE_NEW_SMS · SIT_GET_SMSC_ADDRESS · SmsService
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

10:30:05.002 p0 I mgmtd dbus -> org.ofono.MessageManager.SendMessage on /ril_0
10:30:05.005 - D ofonod src/sms.c:sms_send_message() queued msg 1, route ims smsOverLteCapable=1
10:30:05.011 - E imsd [SLOT_0][E] 4103 [ImsSmsSender::sendSms] failed to build SMS-SUBMIT ref=1
10:30:05.012 - D imsd [SLOT_0][I] 4104 [ImsSmsManager] sendSmsResult() ref=1 result=FAIL
10:30:05.015 - I ofonod src/sms.c:tx_finished() send failed, giving up
10:30:05.016 p0 I ofonod src/dbus.c:__ofono_error_failed() dbus_trace err return - i:org.ofono.MessageManager m:SendMessage p:/ril_0
10:30:05.018 - I mgmtd sms send error: Operation failed

## 다른 모듈 줄 (±15초, 경고·오류)
10:30:05.012 - D imsd [SLOT_0][I] 4104 [ImsSmsManager] sendSmsResult() ref=1 result=FAIL
