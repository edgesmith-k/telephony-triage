# DATA-001 — SETUP_DATA_CALL이 나가지 않음

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

[샘플 DB 유형 — 사내 유형 ID로 바꾼다]

## 점검 목록

1. 창 안에 RILJ `SETUP_DATA_CALL` 요청이 정말 없는지 본다. 로그가 그 시점을 덮어야 "없음"이 근거다.
2. DNC `Data disallowed reasons`의 사유를 하나씩 타임라인 줄과 맞춘다(설정 꺼짐 ↔ DSMGR `notifyDataEnabledChanged: enabled=false`).
3. 설정 변경이 평가 거부보다 앞서는지, 같은 슬롯인지 본다. 뒤의 DNC `Data allowed reason:`은 풀린 것(정상)이다.
4. 사유가 서비스 없음류면 network·radio 줄을 먼저 본다.

## 코드 경로

- `aosp:` DataNetworkController, DataSettingsManager, DataEvaluation, DataProfileManager, DataRetryManager
- `vendor_ril:` 데이터 핸들러(TODO(SITE:S25))

## 흔한 오판

- SETUP 요청이 없는데 모뎀·망을 탓한다. 요청이 나가지 않았으면 아래 층은 관계가 없다.
- 부팅 직후의 거부 사유를 증상 시각의 사유로 쓴다.
