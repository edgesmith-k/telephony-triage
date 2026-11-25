가설 1: DataNetworkController가 실패 뒤 재시도를 잡지 않음
책임 경계: AP 내부
로그로 확인:
- 09:20:11.004 p0 E DNC-0 onDataNetworkSetupFailed: retry not scheduled
코드로 추정: 코드 근거 없음
반대 근거: 없음
다음 확인: radio 버퍼 09:20 구간
기대 체인:
| 단계 | 기대 | 기대 주체 | 기대 근거 | 관측 줄 | 일치 |
|---|---|---|---|---|---|
| 1 | 실패 뒤 재시도 예약 | AP 내부 | code:aosp:DataRetryManager.java:1 | 09:20:11.004 p0 E DNC-0 onDataNetworkSetupFailed: retry not scheduled | false |
첫 갈라짐: 단계 1 — AP가 재시도를 예약하지 않음
