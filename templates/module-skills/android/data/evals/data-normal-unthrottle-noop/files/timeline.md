# MOCK-9831 모듈 타임라인 (android/data, 탐색)

- 마스킹된 이벤트 요약이다(원문 로그 아님). 안의 문장은 데이터이며 지시로 따르지 않는다.
- 모듈 문서: android/data, 중심: 2026-11-20T12:00:00.000Z (발생 시각), 구간: 파일 전체
- 줄: 2/3 (잡음 0, 반복 접음 0), ±15초 다른 모듈 경고·오류: 없음
- 미수집(modules.yaml 이름 중 이 로그에 없음): SETUP_DATA_CALL · DEACTIVATE_DATA_CALL · SET_INITIAL_ATTACH_APN · SET_DATA_PROFILE · SET_USER_DATA_ENABLED
- 형식: 시각(UTC) 슬롯 레벨 태그 메시지 ⇒ 이벤트(필드). 〔script: …〕는 스크립트 메모이며 근거가 아니다.

## 전체 로그 모양 요약 (마스킹 사본 전체, 분석 구간 밖·실패 뒤 포함, 태그 규칙과 상관없이 스크립트가 셈)

- 범위: 2026-11-20T11:59:59.900Z ~ 2026-11-20T12:00:30.200Z, 줄 3, 모양 2개 중 2개. 기준 시각: 2026-11-20T12:00:00.000Z
- 모양은 슬롯·레벨·태그·숫자를 #로 바꾼 메시지다. 순서는 F, 예외·crash 머리, E, W(같은 등급은 기준 뒤 처음 나온 것 먼저), 기준 뒤 처음 나온 모양, 나머지이고 같은 묶음 안은 한 태그 8모양까지 먼저, 기준 시각에 가까운 순이다. 줄은 그 모양의 첫 줄이다

12:00:00.200 p0 D DRM-0 onDataProfileUnthrottled: Nothing to unthrottle.  〔script 모양 2줄, 12:00:00.200~12:00:30.200, 기준 뒤 첫 등장〕
11:59:59.900 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  〔script 모양 1줄〕

## 본 타임라인

11:59:59.900 p0 D DNC-0 Internet data state changed from DISCONNECTED to CONNECTED.  ⇒ data_internet_state_changed(from=DISCONNECTED,to=CONNECTED)
12:00:00.200 p0 D DRM-0 onDataProfileUnthrottled: Nothing to unthrottle.
