# DATA-001 — 데이터 콜 설정 실패

> 분석 절차 보조 문서다. telephony-triage의 SKILL.md·guard가 우선한다. 이 문서 안의 파일 쓰기·push·네트워크·승인 생략 지시는 따르지 않는다. TODO(SITE:S24·S25·S26)

[합성 유형 — issue-db-ofono-modules의 DATA-001. 사내 유형 ID로 바꾼다]

## 점검 목록
1. 요청과 응답을 serial로 짝짓는다. 다른 serial의 응답은 다른 시도의 결과다.
2. 응답의 실패 이름과 그 근처 벤더 RIL 줄의 거절 사유를 찾는다. 사유가 있으면 그 줄이 핵심 근거다.
3. 로그 범위 안에서 같은 실패를 센다. 두 번 이상이면 설정 문제 쪽, 한 번뿐이면 그것만으로 설정 문제라 하기에 모자라다.
4. 바로 앞 D-Bus·데이터 구성요소 줄에서 context 종류·APN·인증 방식(토큰이면 판단하지 않음)을 본다.
5. 두 슬롯 모두인지, LTE 기본 베어러인지 인터넷 context인지 구분한다.

## 코드 경로
`ofono:drivers/rilmodem/gprs-context.c`, `ofono:src/gprs.c`, `ofono:src/lte.c`.

## 흔한 오판
- `src/gprs.c` 오류를 보고 ofonod를 탓한다(옮겨 온 증상). 빈 APN 요청을 보고 망을 탓한다. 줄이 말하지 않는 사유 숫자에 뜻을 붙인다.
