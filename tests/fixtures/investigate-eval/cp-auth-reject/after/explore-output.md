가설 1: vrild가 SETUP_DATA_CALL을 인증 실패로 끝냄
책임 경계: CP 내부
로그로 확인:
- 15:10:01.200 p0 E vrild RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM
- 15:10:03.400 p0 I datad network manager daemon state=disconnected reason=pdn_reject
코드로 추정: 코드 근거 없음
반대 근거: 없음
다음 확인: 모뎀 로그 15:10:01 구간, CP 담당
기대 체인:
| 단계 | 기대 | 기대 주체 | 기대 근거 | 관측 줄 | 일치 |
|---|---|---|---|---|---|
| 1 | SETUP 요청이 나간다 | AP 내부 | log:15:10:00 | 15:10:00.100 p0 I ofonod src/gprs.c:gprs_attach() attach requested apn=internet | true |
| 2 | SETUP 응답이 성공 | CP 내부 | spec:3GPP 24.301 | 15:10:01.200 p0 E vrild RIL_REQUEST_SETUP_DATA_CALL fail cause=AUTH_FAILURE_ON_EMM | false |
첫 갈라짐: 단계 2 — CP가 인증 실패로 응답
